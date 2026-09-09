"""Read the three scratch theories' interpretations out of the isolated semantic
database, embed them with the production embedding stack, and emit the pairwise
cosine similarities the measurement needs.

Run with SEMANTIC_DB_DIR pointing at the isolated copy and with EMBEDDING_API_KEY
in the environment (easiest: `isabelle env python3 analyze.py`).

Outputs, next to this file:
  pairs.json   every cross-run pair, with both texts and both similarities
  summary.csv  one row per pair, no texts
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import statistics
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GROUPS = ["Sim_Measure_A1", "Sim_Measure_A2", "Sim_Measure_B"]

# The lemmas written by hand in the scratch theories.  Everything else that a
# theory contributes is produced by Isabelle's definition packages (`definition`,
# `fun`, `datatype`, `inductive`, `locale`) out of the root command itself.
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

# Which root command each entity belongs to, decided by the leading segment of
# its unqualified name.  Longest prefix wins.
ROOT_OF_PREFIX = [
    ("kolvar", "kolvar"),
    ("tirneb", "tirneb"),
    ("galmuth", "galmuth"),
    ("vondel", "vondel"),
    ("narquil", "narquil"),
    ("quilm", "quilm"),
    ("Brint", "quilm"),
    ("Glaive", "quilm"),
    ("plerx", "plerx"),
    ("dremnok", "dremnok"),
]

# The graded modification each root received in Sim_Measure_B.
GRADE_OF_ROOT = {
    "kolvar": "b-numeric",
    "tirneb": "e-overhaul",
    "galmuth": "a-cosmetic",
    "vondel": "control",
    "narquil": "c-condition",
    "quilm": "unchanged-datatype",
    "plerx": "d-negation",
    "dremnok": "f-locale-assumes",
}


def root_of(short_name: str) -> str:
    best, chosen = "", "?"
    for prefix, root in ROOT_OF_PREFIX:
        if short_name == prefix or short_name.startswith(prefix + "_") \
           or short_name.startswith(prefix + "."):
            if len(prefix) > len(best):
                best, chosen = prefix, root
    return chosen


def collect_records() -> dict:
    """{group: {(short_name, kind_label): {...}}} from the isolated DB."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB
    from Isabelle_Semantic_Embedding._paths import semantic_DB_dir
    print("reading DB at", semantic_DB_dir(), flush=True)
    out = {g: {} for g in GROUPS}
    for _key, rec in Semantic_DB.iter_entity_records():
        name = rec.name or ""
        for g in GROUPS:
            if name.startswith(g + "."):
                short = name[len(g) + 1:]
                slot = (short, rec.kind.label)
                if slot in out[g]:
                    # Two records with the same name and kind would make the
                    # pairing ambiguous; refuse rather than pick one silently.
                    raise SystemExit(f"duplicate entity {g}.{short} [{rec.kind.label}]")
                out[g][slot] = {
                    "short_name": short,
                    "kind": rec.kind.label,
                    "key": bytes(_key).hex(),
                    "expr": rec.expr,
                    "interpretation": rec.interpretation,
                    "pretty_print": rec.pretty_print,
                }
                break
    return out


async def embed_all(texts: list[str]) -> dict:
    from Isabelle_Semantic_Embedding.semantic_embedding import make_embedding_provider
    from Isabelle_Semantic_Embedding.semantics import _resolve_embedding_config_env
    driver, base_url, model = _resolve_embedding_config_env()
    print(f"embedding driver={driver} base_url={base_url} model={model}", flush=True)
    provider = make_embedding_provider(driver, base_url, model)
    print(f"canonical_model={provider.canonical_model} dim={provider.dimension} "
          f"normalize={provider.normalize}", flush=True)
    result = await provider.embed(texts, role="document")
    vecs = result.vectors
    print(f"embedded {len(texts)} texts, tokens={result.total_tokens}", flush=True)
    return {t: vecs[i] for i, t in enumerate(texts)}, provider


def main() -> None:
    recs = collect_records()
    for g in GROUPS:
        print(f"{g}: {len(recs[g])} entities", flush=True)

    # Every entity present in all three runs, keyed by (short name, kind).
    slots = sorted(set(recs[GROUPS[0]]) & set(recs[GROUPS[1]]) & set(recs[GROUPS[2]]))
    missing = {g: sorted(set(recs[g]) - set(slots)) for g in GROUPS}
    for g, m in missing.items():
        if m:
            print(f"{g}: {len(m)} entities not present in all three runs: {m}", flush=True)

    texts: list[str] = []
    for g in GROUPS:
        for slot in slots:
            r = recs[g][slot]
            if r["interpretation"] is None:
                raise SystemExit(f"{g}.{slot} has no interpretation")
            texts.append(r["interpretation"])
            texts.append(r["pretty_print"] + "\n" + r["interpretation"])
    uniq = sorted(set(texts))
    vec, provider = asyncio.run(embed_all(uniq))

    def cos(a: str, b: str) -> float:
        return float(np.dot(vec[a], vec[b]))

    pairs = []
    for slot in slots:
        short, kind = slot
        r1, r2, rb = (recs[g][slot] for g in GROUPS)
        root = root_of(short)
        row = {
            "entity": short,
            "kind": kind,
            "root": root,
            "grade": GRADE_OF_ROOT.get(root, "?"),
            "hand_written_lemma": short in HAND_WRITTEN_LEMMAS,
            "expr_A1": r1["expr"],
            "expr_A2": r2["expr"],
            "expr_B": rb["expr"],
            "expr_same_A1_A2": r1["expr"] == r2["expr"],
            "expr_same_A1_B": r1["expr"] == rb["expr"],
            # A shared universal key means the three runs did NOT interpret this
            # entity independently: the later run read the earlier run's record
            # out of the cache.  Such a pair carries no information about the
            # agent's variability and must be dropped from the distributions.
            "key_A1": r1["key"],
            "key_A2": r2["key"],
            "key_B": rb["key"],
            "shared_key_A1_A2": r1["key"] == r2["key"],
            "shared_key_A1_B": r1["key"] == rb["key"],
            "shared_key_A2_B": r2["key"] == rb["key"],
            "text_A1": r1["interpretation"],
            "text_A2": r2["interpretation"],
            "text_B": rb["interpretation"],
            "doc_A1": r1["pretty_print"] + "\n" + r1["interpretation"],
            "doc_A2": r2["pretty_print"] + "\n" + r2["interpretation"],
            "doc_B": rb["pretty_print"] + "\n" + rb["interpretation"],
        }
        row["sim_A1_A2"] = cos(row["text_A1"], row["text_A2"])
        row["sim_A1_B"] = cos(row["text_A1"], row["text_B"])
        row["sim_A2_B"] = cos(row["text_A2"], row["text_B"])
        row["doc_sim_A1_A2"] = cos(row["doc_A1"], row["doc_A2"])
        row["doc_sim_A1_B"] = cos(row["doc_A1"], row["doc_B"])
        row["doc_sim_A2_B"] = cos(row["doc_A2"], row["doc_B"])
        pairs.append(row)

    with open(os.path.join(HERE, "pairs.json"), "w") as f:
        json.dump({"embedding_model": provider.canonical_model,
                   "embedding_base_url": provider.base_url,
                   "normalize": provider.normalize,
                   "dimension": provider.dimension,
                   "pairs": pairs}, f, indent=1, ensure_ascii=False)

    cols = ["entity", "kind", "root", "grade", "hand_written_lemma",
            "expr_same_A1_A2", "expr_same_A1_B",
            "shared_key_A1_A2", "shared_key_A1_B", "shared_key_A2_B",
            "sim_A1_A2", "sim_A1_B", "sim_A2_B",
            "doc_sim_A1_A2", "doc_sim_A1_B", "doc_sim_A2_B"]
    with open(os.path.join(HERE, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in pairs:
            w.writerow(row)

    noise = sorted(r["sim_A1_A2"] for r in pairs)
    print(f"\nnoise floor (A1 vs A2), n={len(noise)}")
    for q, lbl in ((0.0, "min"), (0.10, "p10"), (0.25, "p25"), (0.50, "median"),
                   (0.75, "p75"), (0.90, "p90"), (1.0, "max")):
        i = min(len(noise) - 1, int(round(q * (len(noise) - 1))))
        print(f"  {lbl:>6}: {noise[i]:.4f}")
    print(f"  mean: {statistics.mean(noise):.4f}")
    print("\nwrote pairs.json and summary.csv")


if __name__ == "__main__":
    sys.exit(main())
