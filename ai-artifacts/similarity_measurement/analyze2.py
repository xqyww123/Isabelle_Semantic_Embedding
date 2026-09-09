"""Phase 2: read every scratch run out of the isolated semantic database, embed
the texts in several forms with several models, and write pairs_phase2.json.

Run with SEMANTIC_DB_DIR pointing at the isolated copy and EMBEDDING_API_KEY in
the environment (easiest: `isabelle env python3 analyze2.py`).

Output shape (pairs_phase2.json):
  meta      -- models, forms, group -> content map
  entities  -- per entity: name, kind, root, and per group its key and texts
  pairs     -- one record per (entity, group1, group2) with, for every
               (model, form), the cosine similarity of the two texts
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# Every run, and which SOURCE CONTENT it interpreted.  Runs sharing a content
# differ only in the theory name, so a pair inside one content class is a
# no-change pair; a pair across content classes A and B* is a change pair.
GROUP_CONTENT = {
    "Sim_Measure_A1": "A", "Sim_Measure_A2": "A", "Sim_Measure_A3": "A",
    "Sim_Measure_A4": "A", "Sim_Measure_A5": "A",
    "Sim_Measure_B": "B", "Sim_Measure_B1b": "B", "Sim_Measure_B1c": "B",
    "Sim_Measure_B2": "B2", "Sim_Measure_B2b": "B2",
    "Sim_Measure_B3": "B3",
    "Sim_Measure_B4": "B4",
}
GROUPS = list(GROUP_CONTENT)

# Which graded modification each root received in each modified content.
# A root absent from a row is identical to the unchanged content A.
GRADE = {
    "B":  {"kolvar": "b-numeric", "tirneb": "e-overhaul", "galmuth": "a-cosmetic",
           "narquil": "c-condition", "plerx": "d-negation", "dremnok": "f-locale"},
    "B2": {"kolvar": "a-cosmetic", "tirneb": "b-numeric", "galmuth": "c-condition",
           "narquil": "d-negation", "plerx": "e-overhaul", "dremnok": "f-locale"},
    "B3": {"kolvar": "e-overhaul", "tirneb": "a-cosmetic", "galmuth": "d-negation",
           "narquil": "b-numeric", "plerx": "c-condition", "dremnok": "f-locale"},
    "B4": {"kolvar": "c-condition", "tirneb": "d-negation", "galmuth": "e-overhaul",
           "narquil": "a-cosmetic", "plerx": "b-numeric", "dremnok": "f-locale"},
}

HAND_WRITTEN_LEMMAS = {
    "kolvar_commute", "kolvar_zero_right", "kolvar_mono_left", "kolvar_positive",
    "tirneb_step", "tirneb_at_zero", "tirneb_mono", "tirneb_injective",
    "galmuth_nil", "galmuth_append", "galmuth_singleton", "galmuth_le_sum",
    "galmuth_rev",
    "vondel_zero", "vondel_weaken", "vondel_base", "vondel_le",
    "narquil_small", "narquil_large", "narquil_glaive_commute",
    "narquil_glaive_assoc",
    "plerx_two", "plerx_add", "plerx_not_one", "plerx_double",
    "dremnok.swap_outer", "dremnok.swap_inner", "dremnok.swap_pair",
    "dremnok.swap_triple",
}

ROOT_PREFIXES = ["kolvar", "tirneb", "galmuth", "vondel", "narquil", "quilm",
                 "Brint", "Glaive", "plerx", "dremnok"]
PREFIX_ROOT = {"Brint": "quilm", "Glaive": "quilm"}

# Embedding models to try.  Only the production one is left: the other two
# models the embedding config knows about on this endpoint
# (fireworks/harrier-oss-v1-27b, fireworks/llama-nv-embed-reasoning-3b) both
# answer HTTP 400 "not available" for this account, and no key for any other
# provider exists in the Isabelle settings, so no second model is reachable
# without adding credentials.  A model that fails is dropped, not fatal.
MODELS = ["Qwen/Qwen3-Embedding-8B"]
BASE_URL = "https://api.fireworks.ai/inference/v1"


def root_of(short_name: str) -> str:
    best, chosen = "", "?"
    for p in ROOT_PREFIXES:
        if short_name == p or short_name.startswith(p + "_") \
           or short_name.startswith(p + "."):
            if len(p) > len(best):
                best, chosen = p, PREFIX_ROOT.get(p, p)
    return chosen


# --- text forms ------------------------------------------------------------
# `interp` and `doc` are the two texts production actually deals with; the rest
# are the preprocessing experiments of candidate rule 5.

_PAREN = re.compile(r"\s*\([^()]*\)")
_SENT = re.compile(r"(?<=[.!?])\s+")


def strip_parentheticals(t: str) -> str:
    """Drop every parenthesised aside.  Applied repeatedly so nested ones go
    too.  Motivated by phase 1: the agent's decision to add '(two is even)' or
    not is the single largest source of run-to-run distance."""
    prev = None
    while prev != t:
        prev, t = t, _PAREN.sub("", t)
    return t.strip()


def first_sentence(t: str) -> str:
    return _SENT.split(t.strip(), 1)[0] if t.strip() else t


FORMS = {
    "interp": lambda r: r["interpretation"],
    "doc": lambda r: r["pretty_print"] + "\n" + r["interpretation"],
    "interp_noparen": lambda r: strip_parentheticals(r["interpretation"]),
    "interp_first": lambda r: first_sentence(r["interpretation"]),
    "interp_first_noparen": lambda r: strip_parentheticals(
        first_sentence(r["interpretation"])),
}


def collect_records() -> dict:
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB
    from Isabelle_Semantic_Embedding._paths import semantic_DB_dir
    print("reading DB at", semantic_DB_dir(), flush=True)
    out = {g: {} for g in GROUPS}
    for key, rec in Semantic_DB.iter_entity_records():
        name = rec.name or ""
        for g in GROUPS:
            if name.startswith(g + "."):
                slot = (name[len(g) + 1:], rec.kind.label)
                if slot in out[g]:
                    raise SystemExit(f"duplicate entity {g}.{slot}")
                out[g][slot] = {
                    "key": bytes(key).hex(),
                    "kind": rec.kind.label,
                    "expr": rec.expr,
                    "interpretation": rec.interpretation,
                    "pretty_print": rec.pretty_print,
                }
                break
    return out


async def embed_model(model: str, texts: list[str]):
    from Isabelle_Semantic_Embedding.semantic_embedding import make_embedding_provider
    provider = make_embedding_provider("OpenAI_Embedding_Provider", BASE_URL, model)
    vecs = {}
    CHUNK = 512
    for i in range(0, len(texts), CHUNK):
        part = texts[i:i + CHUNK]
        res = await provider.embed(part, role="document")
        for t, v in zip(part, res.vectors):
            vecs[t] = v
        print(f"  {model}: {i + len(part)}/{len(texts)}", flush=True)
    return provider, vecs


def main() -> None:
    recs = collect_records()
    for g in GROUPS:
        print(f"{g}: {len(recs[g])} entities", flush=True)
    missing = [g for g in GROUPS if not recs[g]]
    if missing:
        raise SystemExit(f"no records for {missing} -- did those runs finish?")

    slots = sorted(set.intersection(*(set(recs[g]) for g in GROUPS)))
    print(f"entities present in all {len(GROUPS)} runs: {len(slots)}", flush=True)
    for g in GROUPS:
        extra = sorted(set(recs[g]) - set(slots))
        if extra:
            print(f"  {g}: {len(extra)} not in the intersection: "
                  f"{[e[0] for e in extra]}", flush=True)

    # Every text we will ever need, per form.
    texts_by_form = {f: set() for f in FORMS}
    for g in GROUPS:
        for slot in slots:
            for f, fn in FORMS.items():
                texts_by_form[f].add(fn(recs[g][slot]))

    all_texts = sorted(set().union(*texts_by_form.values()))
    print(f"distinct texts to embed: {len(all_texts)}", flush=True)

    vectors, model_info = {}, {}
    for model in MODELS:
        try:
            provider, vecs = asyncio.run(embed_model(model, all_texts))
        except Exception as e:                      # endpoint does not serve it
            print(f"  {model}: UNAVAILABLE ({type(e).__name__}: {str(e)[:200]})",
                  flush=True)
            continue
        vectors[model] = vecs
        model_info[model] = {"canonical": provider.canonical_model,
                             "dimension": provider.dimension,
                             "normalize": provider.normalize,
                             "base_url": provider.base_url}
        print(f"  {model}: done", flush=True)

    entities = []
    for slot in slots:
        short, kind = slot
        e = {"entity": short, "kind": kind, "root": root_of(short),
             "hand_written_lemma": short in HAND_WRITTEN_LEMMAS, "runs": {}}
        for g in GROUPS:
            r = recs[g][slot]
            e["runs"][g] = {"key": r["key"], "expr": r["expr"],
                            "interpretation": r["interpretation"],
                            "pretty_print": r["pretty_print"]}
        entities.append(e)

    pairs = []
    for idx, slot in enumerate(slots):
        short, kind = slot
        root = root_of(short)
        hand = short in HAND_WRITTEN_LEMMAS
        for g1, g2 in itertools.combinations(GROUPS, 2):
            c1, c2 = GROUP_CONTENT[g1], GROUP_CONTENT[g2]
            if c1 == c2:
                relation, changed_content = "no-change", None
            elif c1 == "A":
                relation, changed_content = "change", c2
            elif c2 == "A":
                relation, changed_content = "change", c1
            else:
                continue                     # two different modified contents
            if relation == "change":
                grade = GRADE[changed_content].get(root)
                if grade is None:
                    cls, grade = "control", "unchanged-root"
                elif hand:
                    cls = "downstream"
                else:
                    cls = "definitional"
            else:
                cls, grade = "same-content", None
            r1, r2 = recs[g1][slot], recs[g2][slot]
            rec = {"i": idx, "entity": short, "kind": kind, "root": root,
                   "g1": g1, "g2": g2, "relation": relation,
                   "changed_content": changed_content, "class": cls,
                   "grade": grade,
                   "shared_key": r1["key"] == r2["key"],
                   "expr_same": r1["expr"] == r2["expr"],
                   "sims": {}}
            for model, vecs in vectors.items():
                for f, fn in FORMS.items():
                    t1, t2 = fn(r1), fn(r2)
                    rec["sims"][f"{model}|{f}"] = float(np.dot(vecs[t1], vecs[t2]))
            pairs.append(rec)

    out = {"meta": {"groups": GROUP_CONTENT, "grades": GRADE,
                    "models": model_info, "forms": list(FORMS)},
           "entities": entities, "pairs": pairs}
    path = os.path.join(HERE, "pairs_phase2.json")
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"wrote {path}: {len(entities)} entities, {len(pairs)} pairs, "
          f"{len(vectors)} embedding models", flush=True)


if __name__ == "__main__":
    sys.exit(main())
