"""Phase 2: evaluate every candidate decision rule on pairs_phase2.json.

Pure post-processing; prints, writes nothing.

Populations (a pair whose two runs share a universal key is never used -- the
second run reused the first run's stored text, so it is not two independent
interpretations):

  NO-CHANGE   two runs of the SAME source content.  A gate should say
              "unchanged" here; saying "changed" costs a useless propagation.
  CHANGE      an unchanged run against a modified run, for an entity that the
              definition package generated out of the ROOT COMMAND THAT WAS
              EDITED.  A gate should say "changed" here; saying "unchanged"
              leaves stale English in the database.
  CONTROL     an unchanged run against a modified run, for an entity belonging
              to a root that was NOT edited (the datatype `quilm`, the
              abbreviation `vondel`).  Semantically a no-change pair, but read
              out of two different theory files; reported separately.
  DOWNSTREAM  an unchanged run against a modified run, for a hand-written lemma
              whose own statement did not change but whose root was edited.
              No ground truth: whether its English *should* change is exactly
              the open question.
"""
from __future__ import annotations

import itertools
import json
import os
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
A_RUNS = ["Sim_Measure_A1", "Sim_Measure_A2", "Sim_Measure_A3",
          "Sim_Measure_A4", "Sim_Measure_A5"]
B_CONTENT_RUNS = {"B": ["Sim_Measure_B", "Sim_Measure_B1b", "Sim_Measure_B1c"],
                  "B2": ["Sim_Measure_B2", "Sim_Measure_B2b"],
                  "B3": ["Sim_Measure_B3"], "B4": ["Sim_Measure_B4"]}
SWEEP = [0.999, 0.995, 0.99, 0.985, 0.98, 0.975, 0.97, 0.96, 0.95, 0.94, 0.93,
         0.92, 0.91, 0.90, 0.88, 0.85, 0.80, 0.75]
MARGINS = [-0.02, -0.01, -0.005, 0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12]


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


def describe(xs):
    return (f"n={len(xs):<5} min={min(xs):.4f} p10={q(xs,.1):.4f} "
            f"med={q(xs,.5):.4f} p90={q(xs,.9):.4f} max={max(xs):.4f} "
            f"mean={statistics.mean(xs):.4f}")


def sweep_table(nochange, change, cuts=SWEEP, label="similarity cut"):
    """Trade-off table for `changed iff score < cut`.

    Prints, and returns the rows so the caller can find operating points."""
    rows = []
    for t in cuts:
        fp = sum(1 for x in nochange if x < t) / len(nochange)
        fn = sum(1 for x in change if x >= t) / len(change)
        rows.append((t, fp, fn))
    print(f"  {label:>14} | no-change called 'changed' | real change called "
          f"'unchanged' | savings")
    for t, fp, fn in rows:
        print(f"  {t:>14.4f} | {fp:>25.1%} | {fn:>28.1%} | {1-fp:>6.1%}")
    return rows


def operating_points(rows, name):
    """The plain-language summary: how much propagation can be suppressed while
    missing at most 1 / 5 / 10 / 20 % of real changes, and the equal-error
    point."""
    print(f"  operating points for {name}:")
    for cap in (0.01, 0.05, 0.10, 0.20):
        ok = [r for r in rows if r[2] <= cap]
        if not ok:
            print(f"    miss <= {cap:.0%}: unreachable at any cut in the sweep")
            continue
        best = min(ok, key=lambda r: r[1])
        print(f"    miss <= {cap:.0%}: best cut {best[0]:.4f} suppresses "
              f"{1-best[1]:.1%} of useless propagations "
              f"(misses {best[2]:.1%} of real changes)")
    eer = min(rows, key=lambda r: max(r[1], r[2]))
    print(f"    equal-error-ish: cut {eer[0]:.4f}, "
          f"{eer[1]:.1%} of no-change called changed, "
          f"{eer[2]:.1%} of real changes called unchanged")


def auc(lower_should_be, higher_should_be):
    """Probability that a random member of `lower_should_be` scores below a
    random member of `higher_should_be` (ties count a half).  Computed by the
    rank identity rather than the O(n*m) double loop."""
    xs = sorted((v, 0) for v in lower_should_be)
    ys = sorted((v, 1) for v in higher_should_be)
    merged = sorted(xs + ys)
    n0 = len(xs)
    rank_sum, i = 0.0, 0
    while i < len(merged):
        j = i
        while j < len(merged) and merged[j][0] == merged[i][0]:
            j += 1
        avg_rank = (i + j - 1) / 2 + 1
        for k in range(i, j):
            if merged[k][1] == 0:
                rank_sum += avg_rank
        i = j
    n1 = len(ys)
    u = rank_sum - n0 * (n0 + 1) / 2
    return 1 - u / (n0 * n1)


def load():
    with open(os.path.join(HERE, "pairs_phase2.json")) as f:
        return json.load(f)


def populations(pairs, key):
    """Similarity lists for the four populations, under one (model|form) key."""
    out = defaultdict(list)
    for p in pairs:
        if p["shared_key"]:
            continue
        s = p["sims"].get(key)
        if s is None:
            continue
        if p["relation"] == "no-change":
            out["nochange"].append(s)
        elif p["class"] == "definitional":
            out["change"].append(s)
        elif p["class"] == "control":
            out["control"].append(s)
        elif p["class"] == "downstream":
            out["downstream"].append(s)
    return out


# --------------------------------------------------------------------------
# Rule 2: per-entity relative rules
# --------------------------------------------------------------------------

def per_entity_sims(pairs, key):
    """{(entity,kind): {(g1,g2): sim}} for every usable pair."""
    d = defaultdict(dict)
    for p in pairs:
        if p["shared_key"]:
            continue
        s = p["sims"].get(key)
        if s is not None:
            d[(p["entity"], p["kind"])][(p["g1"], p["g2"])] = s
    return d


def sim_of(tab, a, b):
    return tab.get((a, b), tab.get((b, a)))


def oracle_relative(pairs, key, meta):
    """Rule 2a: compare a pair's similarity against THAT entity's own spread of
    no-change similarities inside the unchanged content.  Leave-one-out on the
    no-change side, so a pair is never judged against itself.  This is an upper
    bound, not a production rule: it needs several stored samples of the OLD
    text, which the database does not keep."""
    tab = per_entity_sims(pairs, key)
    grade_of = meta["grades"]

    rows_min = []
    for margin in MARGINS:
        fp = fn = tot_nc = tot_ch = 0
        for ent, t in tab.items():
            # keyed by the run pair, so leave-one-out drops exactly the pair
            # being judged rather than every pair with the same value
            ref_pairs = {(a, b): sim_of(t, a, b)
                         for a, b in itertools.combinations(A_RUNS, 2)}
            ref_pairs = {k2: v for k2, v in ref_pairs.items() if v is not None}
            if len(ref_pairs) < 3:
                continue
            ref_all = list(ref_pairs.values())
            # no-change side, leave-one-out
            for ab, s in ref_pairs.items():
                ref = [v for k2, v in ref_pairs.items() if k2 != ab]
                if not ref:
                    continue
                tot_nc += 1
                if s < min(ref) - margin:
                    fp += 1
            # change side
            for content, runs in B_CONTENT_RUNS.items():
                g = grade_of[content].get(ent_key_root(ent))
                if g is None:
                    continue
                if not is_definitional(ent):
                    continue
                for a in A_RUNS:
                    for r in runs:
                        s = sim_of(t, a, r)
                        if s is None:
                            continue
                        tot_ch += 1
                        if not (s < min(ref_all) - margin):
                            fn += 1
        if tot_nc and tot_ch:
            rows_min.append((margin, fp / tot_nc, fn / tot_ch))
    return rows_min


HAND_WRITTEN_LEMMAS = {
    "kolvar_commute", "kolvar_zero_right", "kolvar_mono_left", "kolvar_positive",
    "tirneb_step", "tirneb_at_zero", "tirneb_mono", "tirneb_injective",
    "galmuth_nil", "galmuth_append", "galmuth_singleton", "galmuth_le_sum",
    "galmuth_rev", "vondel_zero", "vondel_weaken", "vondel_base", "vondel_le",
    "narquil_small", "narquil_large", "narquil_glaive_commute",
    "narquil_glaive_assoc", "plerx_two", "plerx_add", "plerx_not_one",
    "plerx_double", "dremnok.swap_outer", "dremnok.swap_inner",
    "dremnok.swap_pair", "dremnok.swap_triple",
}
_ROOTS = ["kolvar", "tirneb", "galmuth", "vondel", "narquil", "quilm",
          "plerx", "dremnok"]


def ent_key_root(ent):
    n = ent[0]
    best, chosen = "", "?"
    for p in _ROOTS:
        if n == p or n.startswith(p + "_") or n.startswith(p + "."):
            if len(p) > len(best):
                best, chosen = p, p
    return chosen


def is_definitional(ent):
    return ent[0] not in HAND_WRITTEN_LEMMAS


def resample_rule(pairs, key, meta, k):
    """Rule 2b, the production-realisable variant.  The database stores ONE old
    text.  Re-interpret the current source k times; compare the old-vs-new
    similarities against the new-vs-new similarities of the same entity.

    Two statistics, both swept over an additive margin:
      mean : changed iff mean_i sim(old,new_i) < mean_{i<j} sim(new_i,new_j) - m
      minmax: changed iff max_i sim(old,new_i) < min_{i<j} sim(new_i,new_j) - m
    """
    tab = per_entity_sims(pairs, key)
    grade_of = meta["grades"]
    inst = {"nochange": [], "change": []}
    for ent, t in tab.items():
        for old in A_RUNS:
            others = [r for r in A_RUNS if r != old]
            for news in itertools.combinations(others, k):
                cross = [sim_of(t, old, n) for n in news]
                self_ = [sim_of(t, a, b) for a, b in itertools.combinations(news, 2)]
                if any(x is None for x in cross + self_) or not self_:
                    continue
                inst["nochange"].append((cross, self_))
            for content, runs in B_CONTENT_RUNS.items():
                if len(runs) < k or not is_definitional(ent):
                    continue
                if grade_of[content].get(ent_key_root(ent)) is None:
                    continue
                for news in itertools.combinations(runs, k):
                    cross = [sim_of(t, old, n) for n in news]
                    self_ = [sim_of(t, a, b)
                             for a, b in itertools.combinations(news, 2)]
                    if any(x is None for x in cross + self_) or not self_:
                        continue
                    inst["change"].append((cross, self_))
    out = {}
    for stat in ("mean", "minmax"):
        rows = []
        for m in MARGINS:
            def changed(cs):
                cross, self_ = cs
                if stat == "mean":
                    return statistics.mean(cross) < statistics.mean(self_) - m
                return max(cross) < min(self_) - m
            fp = sum(1 for c in inst["nochange"] if changed(c)) / len(inst["nochange"])
            fn = sum(1 for c in inst["change"] if not changed(c)) / len(inst["change"])
            rows.append((m, fp, fn))
        out[stat] = (rows, len(inst["nochange"]), len(inst["change"]))
    return out


# --------------------------------------------------------------------------

DIGEST_DIR = "/var/tmp/qiyuan/sim_measure_logs/digests"


def load_digests() -> dict:
    """{run: {short entity name: (digest hex or '-', universal key hex)}}.

    Written by digests.py straight out of `Semantic_Store.enumerate_entries`."""
    out = {}
    if not os.path.isdir(DIGEST_DIR):
        return out
    for fn in sorted(os.listdir(DIGEST_DIR)):
        if not fn.endswith(".tsv"):
            continue
        run, d = fn[:-4], {}
        with open(os.path.join(DIGEST_DIR, fn)) as f:
            for ln in f:
                parts = ln.rstrip("\n").split("\t")
                if len(parts) < 3 or not parts[0].startswith(run + "."):
                    continue
                d[parts[0][len(run) + 1:]] = (parts[1], parts[2])
        out[run] = d
    return out


def digest_differs(dig: dict, p: dict):
    """Did the entity's own FORMAL content change between the two runs?

    Two comparators, picked by what the entity carries.  The four
    name-addressed kinds (constant/type/class/locale) carry a
    `Semantic_Digest`, so compare that.  Theorem-alike entities carry none --
    their statement hash lives in the second half of the universal key (the
    first half is the exclusive-or of the constituent theories, which differs
    between two theories by construction and says nothing about content) -- so
    compare that half.  None when an entity is absent from a run's enumeration."""
    e1 = dig.get(p["g1"], {}).get(p["entity"])
    e2 = dig.get(p["g2"], {}).get(p["entity"])
    if e1 is None or e2 is None:
        return None
    (d1, k1), (d2, k2) = e1, e2
    if d1 != "-" and d2 != "-":
        return d1 != d2
    return k1[32:] != k2[32:]


def main() -> None:
    data = load()
    pairs, meta = data["pairs"], data["meta"]
    hand = {(e["entity"], e["kind"]): e["hand_written_lemma"]
            for e in data["entities"]}
    for p in pairs:
        p["hand"] = hand[(p["entity"], p["kind"])]

    models = list(meta["models"])
    forms = meta["forms"]
    print("runs:", ", ".join(f"{g}({c})" for g, c in meta["groups"].items()))
    print("embedding models:", models)
    print("text forms:", forms)
    print(f"entities: {len(data['entities'])}, pairs: {len(pairs)}\n")

    prod = f"Qwen/Qwen3-Embedding-8B|interp"

    print("=" * 78)
    print("A. POPULATION SUMMARIES, production embedding, interpretation text")
    print("=" * 78)
    pop = populations(pairs, prod)
    for name in ("nochange", "change", "control", "downstream"):
        print(f"  {name:<11}", describe(pop[name]))
    print()

    print("=" * 78)
    print("B. CANDIDATE RULE 1 -- GLOBAL THRESHOLD, every model x every form")
    print("=" * 78)
    best_overall = []
    for model in models:
        for form in forms:
            key = f"{model}|{form}"
            pp = populations(pairs, key)
            if not pp["nochange"] or not pp["change"]:
                continue
            print(f"\n--- {key}")
            print(f"    no-change {describe(pp['nochange'])}")
            print(f"    change    {describe(pp['change'])}")
            rows = sweep_table(pp["nochange"], pp["change"])
            operating_points(rows, key)
            eer = min(rows, key=lambda r: max(r[1], r[2]))
            best_overall.append((max(eer[1], eer[2]), key, eer))
    print("\n  RANKING by equal-error rate (lower is better):")
    for e, key, row in sorted(best_overall):
        print(f"    {e:.3f}  {key}  (cut {row[0]:.4f}, fp {row[1]:.1%}, "
              f"fn {row[2]:.1%})")
    print("\n  RANKING by AUC -- the probability that a randomly chosen real")
    print("  change scores LOWER than a randomly chosen no-change pair.")
    print("  0.5 = the score carries no information; 1.0 = perfect separation.")
    for model in models:
        for form in forms:
            key = f"{model}|{form}"
            pp = populations(pairs, key)
            if not pp["nochange"] or not pp["change"]:
                continue
            print(f"    AUC {auc(pp['change'], pp['nochange']):.4f}  {key}")
    print()

    print("=" * 78)
    print("C. CANDIDATE RULE 2a -- ORACLE PER-ENTITY RELATIVE RULE")
    print("   changed iff sim(old,new) < (that entity's own minimum no-change")
    print("   similarity) - margin.  Needs several stored samples of the OLD")
    print("   text, which production does not have: an upper bound only.")
    print("=" * 78)
    for model in models:
        key = f"{model}|interp"
        rows = oracle_relative(pairs, key, meta)
        if not rows:
            continue
        print(f"\n--- {key}")
        print(f"  {'margin':>14} | no-change called 'changed' | real change "
              f"called 'unchanged' | savings")
        for m, fp, fn in rows:
            print(f"  {m:>14.4f} | {fp:>25.1%} | {fn:>28.1%} | {1-fp:>6.1%}")
        operating_points(rows, key + " (oracle relative)")
    print()

    print("=" * 78)
    print("D. CANDIDATE RULE 2b -- REALISTIC RESAMPLING RULE")
    print("   One stored old text; re-interpret the current source k times;")
    print("   compare old-vs-new against new-vs-new for the same entity.")
    print("=" * 78)
    for k in (2, 3):
        for model, form in ((m, f) for m in models for f in ("interp", "doc")):
            key = f"{model}|{form}"
            res = resample_rule(pairs, key, meta, k)
            for stat, (rows, n_nc, n_ch) in res.items():
                print(f"\n--- k={k}  {key}  statistic={stat}  "
                      f"(no-change instances {n_nc}, change instances {n_ch})")
                print(f"  {'margin':>14} | no-change called 'changed' | real "
                      f"change called 'unchanged' | savings")
                for m, fp, fn in rows:
                    print(f"  {m:>14.4f} | {fp:>25.1%} | {fn:>28.1%} | "
                          f"{1-fp:>6.1%}")
                operating_points(rows, f"k={k} {stat} {key}")
    print()

    print("=" * 78)
    print("E. CANDIDATE RULE 5a -- PER-RUN-PAIR NORMALISATION")
    print("   One run may simply be terser than another, moving every entity's")
    print("   similarity together.  Judge an entity against the MEDIAN")
    print("   similarity of all entities compared between the same two runs.")
    print("   Production-realisable: re-interpreting a theory yields many")
    print("   entities to calibrate on.")
    print("=" * 78)
    for model in models:
        for form in ("interp", "doc"):
            key = f"{model}|{form}"
            med = defaultdict(list)
            for p in pairs:
                if p["shared_key"]:
                    continue
                s = p["sims"].get(key)
                if s is not None:
                    med[(p["g1"], p["g2"])].append(s)
            med = {k2: statistics.median(v) for k2, v in med.items()}
            nc, ch = [], []
            for p in pairs:
                if p["shared_key"]:
                    continue
                s = p["sims"].get(key)
                if s is None:
                    continue
                d = s - med[(p["g1"], p["g2"])]
                if p["relation"] == "no-change":
                    nc.append(d)
                elif p["class"] == "definitional":
                    ch.append(d)
            if not nc or not ch:
                continue
            print(f"\n--- {key}  (score = similarity minus this run pair's median)")
            print(f"    no-change {describe(nc)}")
            print(f"    change    {describe(ch)}")
            rows = sweep_table(nc, ch, cuts=[0.02, 0.01, 0.0, -0.01, -0.02,
                                             -0.03, -0.05, -0.08, -0.12, -0.18],
                               label="offset cut")
            operating_points(rows, key + " (run-pair normalised)")
    print()

    print("=" * 78)
    print("F. CANDIDATE RULE 5b -- NON-EMBEDDING COMPARATORS")
    print("   No LLM, no embedding: compare the formal content directly.")
    print()
    print("   IMPORTANT -- what this experiment can and cannot measure.")
    print("   `Semantic_Digest` and the universal key's statement hash both")
    print("   incorporate the FULLY QUALIFIED name of every constant involved,")
    print("   and in this experiment the qualifier is the theory name, which")
    print("   differs between every run by construction.  Both therefore differ")
    print("   for every pair here, including pairs of byte-identical sources --")
    print("   an artifact of running each variant as its own theory, not a")
    print("   property of the mechanism.  In production an edit happens inside")
    print("   ONE theory, the qualified names do not move, and the digest")
    print("   changes exactly when the alpha-canonical formal content changes.")
    print("   The measurable, name-independent stand-in is the printed")
    print("   statement `expr`, which carries no theory qualifier.")
    print("=" * 78)
    dig = load_digests()
    print("\n  cross-run digest equality check (should be 0 if it were "
          "name-independent):")
    same_dig = tot = 0
    for p in pairs:
        if p["shared_key"] or p["relation"] != "no-change":
            continue
        v = digest_differs(dig, p)
        if v is None:
            continue
        tot += 1
        same_dig += (not v)
    print(f"    identical-source pairs whose digest/key hash agrees: "
          f"{same_dig}/{tot} -> the digest is name-dependent, as expected")

    for name, fn in (("printed statement (expr) differs",
                      lambda p: not p["expr_same"]),):
        nc = ch = tot_nc = tot_ch = 0
        undecidable = 0
        for p in pairs:
            if p["shared_key"]:
                continue
            v = fn(p)
            if v is None:
                undecidable += 1
                continue
            if p["relation"] == "no-change":
                tot_nc += 1
                nc += bool(v)
            elif p["class"] == "definitional":
                tot_ch += 1
                ch += (not v)
        if not tot_nc or not tot_ch:
            continue
        print(f"\n--- {name}")
        print(f"    no-change called 'changed':      {nc}/{tot_nc} = "
              f"{nc/tot_nc:.1%}")
        print(f"    real change called 'unchanged':  {ch}/{tot_ch} = "
              f"{ch/tot_ch:.1%}")
        print(f"    savings (propagations suppressed): {1-nc/tot_nc:.1%}")
        if undecidable:
            print(f"    undecidable (entity missing a digest): {undecidable}")
    print("\n  how often the printed statement moves, per grade -- i.e. how much"
          "\n  of the invalidation a statement-level comparator already avoids:")
    per = defaultdict(lambda: [0, 0])
    for p in pairs:
        if p["shared_key"] or p["relation"] != "change" \
           or p["class"] != "definitional":
            continue
        per[p["grade"]][0] += 1
        per[p["grade"]][1] += (not p["expr_same"])
    for g in sorted(per):
        n, ch = per[g]
        print(f"    {g:<16} {ch}/{n} = {ch/n:.0%} of the edited root's own "
              f"entities change their printed statement")
    print()

    print("=" * 78)
    print("G. DOWNSTREAM AND CONTROL, production embedding")
    print("=" * 78)
    by_grade = defaultdict(list)
    for p in pairs:
        if p["shared_key"] or p["relation"] != "change":
            continue
        s = p["sims"].get(prod)
        if s is None:
            continue
        by_grade[(p["class"], p["grade"])].append(s)
    for kk in sorted(by_grade, key=lambda x: (x[0], str(x[1]))):
        print(f"  {kk[0]:<13} {str(kk[1]):<18}", describe(by_grade[kk]))
    print()


if __name__ == "__main__":
    sys.exit(main())
