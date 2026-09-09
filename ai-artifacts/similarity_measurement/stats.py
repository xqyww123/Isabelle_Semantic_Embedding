"""Turn pairs.json into the tables the report needs.  Pure post-processing:
reads pairs.json, writes nothing, prints everything.

Two entities are compared only when the two runs really did interpret them
independently.  They did not whenever the two runs stored the entity under the
SAME universal key: the second run then found the first run's record in the
cache and reused its text verbatim.  Such a pair is dropped from every
distribution below (it would otherwise contribute a spurious similarity of
exactly 1)."""
from __future__ import annotations

import json
import os
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
QUANTILES = [(0.0, "min"), (0.10, "p10"), (0.25, "p25"), (0.50, "median"),
             (0.75, "p75"), (0.90, "p90"), (1.0, "max")]


def quant(xs: list[float]) -> dict:
    xs = sorted(xs)
    out = {}
    for q, lbl in QUANTILES:
        i = min(len(xs) - 1, int(round(q * (len(xs) - 1))))
        out[lbl] = xs[i]
    out["mean"] = statistics.mean(xs)
    out["n"] = len(xs)
    return out


def fmt(d: dict) -> str:
    return (f"n={d['n']:<4} min={d['min']:.4f} p10={d['p10']:.4f} p25={d['p25']:.4f} "
            f"med={d['median']:.4f} p75={d['p75']:.4f} p90={d['p90']:.4f} "
            f"max={d['max']:.4f} mean={d['mean']:.4f}")


def main() -> None:
    with open(os.path.join(HERE, "pairs.json")) as f:
        data = json.load(f)
    pairs = data["pairs"]
    print(f"embedding: {data['embedding_model']} @ {data['embedding_base_url']} "
          f"dim={data['dimension']} normalize={data['normalize']}")
    print(f"entities paired across all three runs: {len(pairs)}\n")

    noise_pairs = [p for p in pairs if not p["shared_key_A1_A2"]]
    b_pairs = [p for p in pairs if not p["shared_key_A1_B"]]
    dropped_noise = [p for p in pairs if p["shared_key_A1_A2"]]
    dropped_b = [p for p in pairs if p["shared_key_A1_B"]]
    if dropped_noise:
        print(f"dropped from the A1-vs-A2 comparison ({len(dropped_noise)}, shared "
              f"universal key -> A2 reused A1's stored text): "
              f"{[p['entity'] for p in dropped_noise]}")
    if dropped_b:
        print(f"dropped from the A1-vs-B comparison ({len(dropped_b)}, shared "
              f"universal key -> B reused A1's stored text): "
              f"{[p['entity'] for p in dropped_b]}")
    print()

    print("=== 1. NOISE FLOOR: A1 vs A2, independently interpreted entities ===")
    print("  all           ", fmt(quant([p["sim_A1_A2"] for p in noise_pairs])))
    by_kind = defaultdict(list)
    for p in noise_pairs:
        by_kind[p["kind"]].append(p["sim_A1_A2"])
    for k in sorted(by_kind):
        print(f"  {k:<22}", fmt(quant(by_kind[k])))
    print()

    # The root entities are exactly the ones Isabelle's definition packages
    # generated out of the root command -- the constant itself, its `_def`, its
    # simps/cases/induct/elims/intros, the locale predicate.  Splitting on
    # `expr` would be wrong here: a constant's `expr` is only its type
    # signature, so a completely rewritten definition body leaves it unchanged.
    CHANGED_ROOTS = {"kolvar", "tirneb", "galmuth", "narquil", "plerx", "dremnok"}
    changed = [p for p in b_pairs
               if not p["hand_written_lemma"] and p["root"] in CHANGED_ROOTS]
    same = [p for p in b_pairs if p["hand_written_lemma"]]
    control = [p for p in b_pairs
               if not p["hand_written_lemma"] and p["root"] not in CHANGED_ROOTS]

    print("=== 2. DEFINITIONAL ENTITIES OF A ROOT MODIFIED IN B ===")
    hdr = (f"{'entity':<28}{'kind':<20}{'root':<10}{'grade':<20}"
           f"{'A1~A2':>8}{'A1~B':>8}{'A2~B':>8}{'expr=':>7}")

    def show(ps, key):
        print(hdr)
        for p in sorted(ps, key=key):
            noise = (f"{p['sim_A1_A2']:>8.4f}" if not p["shared_key_A1_A2"]
                     else "     n/a")
            print(f"{p['entity']:<28}{p['kind']:<20}{p['root']:<10}{p['grade']:<20}"
                  f"{noise}{p['sim_A1_B']:>8.4f}{p['sim_A2_B']:>8.4f}"
                  f"{'Y' if p['expr_same_A1_B'] else 'N':>7}")
        print()

    show(changed, lambda p: (p["grade"], p["entity"]))

    print("=== 3. HAND-WRITTEN LEMMAS, STATEMENT UNCHANGED IN B (downstream) ===")
    show(same, lambda p: (p["grade"], p["root"], p["entity"]))

    print("=== 3b. DEFINITIONAL ENTITIES OF AN UNCHANGED ROOT (control) ===")
    show(control, lambda p: (p["root"], p["entity"]))

    print("=== 4. DOWNSTREAM SUMMARY PER ROOT (hand-written lemmas only) ===")
    by_root = defaultdict(list)
    for p in same:
        by_root[(p["root"], p["grade"])].append(p)
    print(f"{'root':<10}{'grade':<20}{'n':>4}  {'A1~A2 (noise)':<26}"
          f"{'A1~B (downstream)':<26}")
    for (root, grade), ps in sorted(by_root.items(), key=lambda kv: kv[0][1]):
        nn = [p["sim_A1_A2"] for p in ps if not p["shared_key_A1_A2"]]
        d = quant([p["sim_A1_B"] for p in ps])
        ntxt = (f"n={len(nn)} min={min(nn):.4f} med={statistics.median(nn):.4f}"
                if nn else "n=0")
        print(f"{root:<10}{grade:<20}{len(ps):>4}  {ntxt:<26}"
              f"min={d['min']:.4f} med={d['median']:.4f}")
    print()

    print("=== 5. SEPARATION TEST ===")
    noise = [p["sim_A1_A2"] for p in noise_pairs]
    real = [p["sim_A1_B"] for p in changed]
    qn, qr = quant(noise), quant(real)
    print(f"noise (A1~A2, all): min={min(noise):.4f} p10={qn['p10']:.4f} "
          f"med={qn['median']:.4f}")
    print(f"real change (A1~B, expr differs): max={max(real):.4f} "
          f"p90={qr['p90']:.4f} med={qr['median']:.4f}")
    print(f"a threshold cleanly separating them exists: "
          f"{'YES' if max(real) < min(noise) else 'NO'}")
    for thr in (0.99, 0.98, 0.97, 0.96, 0.95, 0.94, 0.92, 0.90, 0.85):
        fp = sum(1 for x in noise if x < thr)     # noise misread as a real change
        fn = sum(1 for x in real if x >= thr)     # real change misread as noise
        print(f"  threshold sim>={thr:.2f}: {fp:>3}/{len(noise)} noise pairs called "
              f"'changed'; {fn:>2}/{len(real)} real changes called 'unchanged'")
    print()

    print("=== 6. WASTED DOWNSTREAM RE-INTERPRETATION ===")
    p10_noise, min_noise = qn["p10"], min(noise)
    for label, ps in (("hand-written lemmas of a CHANGED root", same),
                      ("definitional entities of an UNCHANGED root", control)):
        if not ps:
            continue
        a = sum(1 for p in ps if p["sim_A1_B"] >= min_noise)
        b = sum(1 for p in ps if p["sim_A1_B"] >= p10_noise)
        c = sum(1 for p in ps if p["sim_A1_B"] >= p["sim_A1_A2"])
        print(f"{label}: n={len(ps)}; "
              f"{a} ({100*a/len(ps):.0f}%) at or above the noise minimum "
              f"{min_noise:.4f}; "
              f"{b} ({100*b/len(ps):.0f}%) at or above the noise p10 {p10_noise:.4f}; "
              f"{c} ({100*c/len(ps):.0f}%) at or above THAT ENTITY's own A1-vs-A2 "
              f"noise similarity")
    print()

    print("=== 6b. PAIRED TEST: (A1~B) minus (A1~A2) for the SAME entity ===")
    print("A value near zero means the B run's text differs from the A1 run's text "
          "no more than\ntwo independent runs of the SAME source differ.")
    for label, ps in (("hand-written lemmas of a CHANGED root", same),
                      ("definitional entities of a CHANGED root", changed),
                      ("definitional entities of an UNCHANGED root", control)):
        d = [p["sim_A1_B"] - p["sim_A1_A2"] for p in ps if not p["shared_key_A1_A2"]]
        print(f"  {label:<45} {fmt(quant(d))}")
    print()

    print("=== 7a. FIVE LOWEST-SIMILARITY NOISE PAIRS (A1 vs A2) ===")
    for p in sorted(noise_pairs, key=lambda p: p["sim_A1_A2"])[:5]:
        print(f"--- {p['entity']} [{p['kind']}]  sim={p['sim_A1_A2']:.4f}")
        print(f"    expr : {p['expr_A1']}")
        print(f"    A1   : {p['text_A1']}")
        print(f"    A2   : {p['text_A2']}")
    print()

    print("=== 7b. FIVE HIGHEST-SIMILARITY REAL-CHANGE PAIRS (A1 vs B, expr differs) ===")
    for p in sorted(changed, key=lambda p: -p["sim_A1_B"])[:5]:
        n = f"{p['sim_A1_A2']:.4f}" if not p["shared_key_A1_A2"] else "n/a"
        print(f"--- {p['entity']} [{p['kind']}] grade={p['grade']} "
              f"sim={p['sim_A1_B']:.4f} (noise for this entity {n})")
        print(f"    expr A1: {p['expr_A1']}")
        print(f"    expr B : {p['expr_B']}")
        print(f"    A1     : {p['text_A1']}")
        print(f"    B      : {p['text_B']}")
    print()

    print("=== 7c. FIVE HIGHEST-SIMILARITY DOWNSTREAM PAIRS OF A CHANGED ROOT ===")
    dn = same
    for p in sorted(dn, key=lambda p: -p["sim_A1_B"])[:5]:
        n = f"{p['sim_A1_A2']:.4f}" if not p["shared_key_A1_A2"] else "n/a"
        print(f"--- {p['entity']} [{p['kind']}] grade={p['grade']} "
              f"sim={p['sim_A1_B']:.4f} (noise for this entity {n})")
        print(f"    expr   : {p['expr_A1']}")
        print(f"    A1     : {p['text_A1']}")
        print(f"    B      : {p['text_B']}")
    print()

    print("=== 7d. FIVE LOWEST-SIMILARITY DOWNSTREAM PAIRS OF A CHANGED ROOT ===")
    for p in sorted(dn, key=lambda p: p["sim_A1_B"])[:5]:
        n = f"{p['sim_A1_A2']:.4f}" if not p["shared_key_A1_A2"] else "n/a"
        print(f"--- {p['entity']} [{p['kind']}] grade={p['grade']} "
              f"sim={p['sim_A1_B']:.4f} (noise for this entity {n})")
        print(f"    expr   : {p['expr_A1']}")
        print(f"    A1     : {p['text_A1']}")
        print(f"    B      : {p['text_B']}")
    print()

    print("=== 8. SAME QUANTITIES ON THE PRODUCTION DOCUMENT TEXT "
          "(pretty_print + interpretation) ===")
    print("  noise A1~A2 ", fmt(quant([p["doc_sim_A1_A2"] for p in noise_pairs])))
    print("  real  A1~B  ", fmt(quant([p["doc_sim_A1_B"] for p in changed])))
    print("  downstr A1~B", fmt(quant([p["doc_sim_A1_B"] for p in same])))


if __name__ == "__main__":
    sys.exit(main())
