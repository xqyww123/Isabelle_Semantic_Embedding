#!/usr/bin/env python3
"""Give dynamic-collection-member records their real fact name and position
(ENTITY_POSITION_PLAN.md §10 rule 1; the investigation is recorded there).

THE PROBLEM
-----------
A member of a dynamic fact collection (`named_theorems foo`, `add_thms_dynamic`)
has no entry in Isabelle's fact name space: `Facts.add_dynamic`
(Pure/facts.ML:294-296) registers ONE entry, for the collection.  So our
enumeration stamps each member with the collection's name plus its 1-based
position in that sweep's member list and a literal `("", 0, 0)` position
(semantic_store.ML:1108, rendered as `coll(i)` by A6 at :852-856; the empty
position becomes `None` at entity_position.ML:98-105).

Two things are wrong with the result.  The index is context-relative -- measured,
one name `Topological_Spaces.tendsto_intros(104)` denotes THREE different
propositions in the store -- so it reads like Isabelle's own citable fact
selection while denoting something else.  And the record carries no position
even when the very same theorem, enumerated under its static name in another
theory's sweep, carries one.

WHAT THIS FIXES, AND WHERE THE TRUTH COMES FROM
-----------------------------------------------
Only the records whose real name is ALREADY IN OUR OWN DATA.  Nothing is
guessed, and Isabelle is not consulted:

- **sibling**: the same proposition under a different kind tag.  A theorem-alike
  key is `XOR(constituent hashes) ++ tag ++ thm128[:15]`, so records of one
  proposition differ only in the tag byte.  A member yields both a Theorem entry
  and a rule-kind entry (semantic_store.ML:1113-1120); when the theorem face was
  enumerated statically (in a sweep that saw the declaration) it holds the real
  name and position while the rule face kept the member name.  Measured: 4,519.
- **samekey**: the dump holds a POSITIONED record on the very same key, i.e. the
  join's pick (§B.6, prefer the name matching the old record, else sorted order)
  chose the member-named candidate over the static one.  That rule never knew
  about static-versus-member; measured over 2,557 contested keys it happened to
  choose the static name 2,547 times and the member name 10 times.  Those 10.

RENAMING IS SAFE, AND THIS IS WHY
---------------------------------
A theorem-alike key does not contain the name (the tail is the proposition's
digest), so changing `name` moves nothing.  Contrast the name-addressed kinds
(constant/type/class/locale/collection/method), where the name IS the key.

The vector MUST be dropped with the rename: the embedded document is
`pretty_print + interpretation` (document_text.py:50) and `pretty_print` renders
the stored name, while `_auto_embed` only fills ABSENT vectors and never
refreshes a stale one.  Re-embed afterwards (`isabelle-semantics embed`).

WHAT IS NOT TOUCHED
-------------------
The ~9,603 member records with no positioned counterpart anywhere in store or
dump.  Whether those theorems have a real name at all cannot be settled from our
data -- it needs `Thm.get_name_hint` per member, in Isabelle.  They keep
`coll(i)` and `None`.

One-off; delete when the follow-up decisions in ENTITY_POSITION_PLAN.md are made.
"""

import argparse
import collections
import json
import os
import re
from typing import Any

import lmdb
import msgpack

SEMANTICS_MAP_SIZE = 1 << 32
VECTOR_MAP_SIZE = 1 << 36
F_NAME, F_POS = 1, 12                 # positional codec, _Semantic_DB._decode
D_NAME, D_POS = 0, 2                  # dump record layout, rekey_dump.py
COLLECTION_TAG = 6
THM_TAGS = (2, 0x12, 0x22, 0x32, 0x42)
IDX = re.compile(r"^(.*)\((\d+)\)$")


def dec(v: Any) -> Any:
    return v.decode() if isinstance(v, bytes) else v


def norm_pos(p: Any) -> 'list | None':
    return None if p is None else [dec(x) for x in p]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=os.path.expanduser(
        "~/.cache/Isabelle_Semantic_Embedding"))
    ap.add_argument("--dump", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sem_path = os.path.join(args.cache, "semantics.lmdb")
    vec_name = next(d for d in sorted(os.listdir(args.cache))
                    if d.startswith("vector_") and d.endswith(".lmdb"))
    vec_path = os.path.join(args.cache, vec_name)

    # ---- pass 1: group theorem-alike records by proposition; find the targets
    print("pass 1: scanning the store ...", flush=True)
    colls: set[str] = set()
    grp: dict[tuple, list] = collections.defaultdict(list)
    # (kind, name) -> number of keys, for the collision statistic
    kn_before: collections.Counter = collections.Counter()
    env = lmdb.open(sem_path, readonly=True, lock=False)
    with env.begin() as t:
        for k, v in t.cursor():
            k = bytes(k)
            if len(k) <= 16:
                continue
            vals = msgpack.unpackb(bytes(v))
            name = dec(vals[F_NAME]) or ""
            if k[16] == COLLECTION_TAG:
                colls.add(name)
            kn_before[(k[16], name)] += 1
            if k[16] in THM_TAGS:
                pos = vals[F_POS] if len(vals) > F_POS else None
                grp[(k[:16], k[17:])].append((k, k[16], name, pos))
    env.close()

    def is_member_style(n: str) -> bool:
        m = IDX.match(n or "")
        return bool(m) and m.group(1) in colls

    targets: dict[bytes, dict] = {}          # key -> {name, pos, source}
    multi_name_groups = 0
    for _, rows in grp.items():
        bad = [r for r in rows if r[3] is None and is_member_style(r[2])]
        if not bad:
            continue
        good = [r for r in rows if r[3] is not None]
        if not good:
            continue
        names = {r[2] for r in good}
        if len(names) > 1:
            multi_name_groups += 1
        pick = min(good, key=lambda r: (r[1], r[2]))     # deterministic
        if is_member_style(pick[2]):
            raise SystemExit(f"a positioned record has a member-style name: "
                             f"{pick[2]!r} -- the dichotomy this pass relies on "
                             "does not hold; refusing")
        for key, tag, name, _ in bad:
            targets[key] = {"name": pick[2], "pos": norm_pos(pick[3]),
                            "source": "sibling", "old_name": name, "kind": tag,
                            "from_key": pick[0].hex()}
    print(f"  sibling targets: {len(targets)}"
          f" (groups whose positioned records disagree on the name: {multi_name_groups})",
          flush=True)

    # ---- pass 2: the same-key candidates, from the dump
    print("pass 2: scanning the dump for same-key positioned records ...", flush=True)
    still = [k for (pre, dig), rows in grp.items() for k, tag, name, pos in rows
             if pos is None and is_member_style(name) and k not in targets]
    dmp = lmdb.open(args.dump, readonly=True, lock=False)
    samekey_multi = 0
    with dmp.begin() as t:
        for key in still:
            raw = t.get(key)
            if raw is None:
                continue
            posd = [r for r in msgpack.unpackb(bytes(raw)) if r[D_POS] is not None]
            if not posd:
                continue
            if len({dec(r[D_NAME]) for r in posd}) > 1:
                samekey_multi += 1
            pick = min(posd, key=lambda r: dec(r[D_NAME]))
            nm = dec(pick[D_NAME])
            if is_member_style(nm):
                raise SystemExit(f"a positioned DUMP record has a member-style "
                                 f"name: {nm!r}; refusing")
            store_rec = next(r for (pre, dig), rows in grp.items() for r in rows
                             if r[0] == key)
            targets[key] = {"name": nm, "pos": norm_pos(pick[D_POS]),
                            "source": "samekey", "old_name": store_rec[2],
                            "kind": store_rec[1], "from_key": key.hex()}
    dmp.close()
    n_same = sum(1 for v in targets.values() if v["source"] == "samekey")
    print(f"  samekey targets: {n_same}"
          f" (dump records disagreeing on the name: {samekey_multi})", flush=True)

    # ---- the collision statistic the user asked for
    # After the rename, does another record of the SAME KIND carry the same name?
    kn_after = collections.Counter(kn_before)
    for key, tgt in targets.items():
        kn_after[(tgt["kind"], tgt["old_name"])] -= 1
        kn_after[(tgt["kind"], tgt["name"])] += 1
    joined = [(k, v) for k, v in
              (((tgt["kind"], tgt["name"]), kn_after[(tgt["kind"], tgt["name"])])
               for tgt in targets.values()) if v > 1]
    coll_pairs = {p for p, _ in joined}
    pre_existing = sum(1 for p, c in kn_before.items() if c > 1)
    print(f"\ncollision statistic (same kind AND same name):")
    print(f"  renamed records landing on a (kind, name) shared with another "
          f"record: {len(joined)}")
    print(f"  distinct (kind, name) pairs involved: {len(coll_pairs)}")
    print(f"  for context, (kind, name) pairs already shared before this pass: "
          f"{pre_existing}", flush=True)

    by_kind = collections.Counter(t["kind"] for t in targets.values())
    by_src = collections.Counter(t["source"] for t in targets.values())
    report = {
        "dry_run": args.dry_run, "vector_store": vec_name,
        "targets": len(targets), "by_kind": {hex(k): v for k, v in by_kind.items()},
        "by_source": dict(by_src),
        "groups_with_disagreeing_positioned_names": multi_name_groups,
        "dump_records_disagreeing_on_name": samekey_multi,
        "collisions_after": {
            "renamed_records_in_a_collision": len(joined),
            "distinct_kind_name_pairs": len(coll_pairs),
            "pairs": sorted(f"{hex(k)} {n}" for k, n in coll_pairs)[:200],
            "pre_existing_shared_pairs": pre_existing,
        },
        "rows": [{"key": k.hex(), "kind": hex(t["kind"]), "source": t["source"],
                  "old_name": t["old_name"], "new_name": t["name"],
                  "position": t["pos"], "from_key": t["from_key"]}
                 for k, t in sorted(targets.items())],
    }

    # ---- write
    problems: list[str] = []
    counts: collections.Counter = collections.Counter()
    if not args.dry_run:
        print("\nwriting ...", flush=True)
        sem = lmdb.open(sem_path, map_size=SEMANTICS_MAP_SIZE)
        vec = lmdb.open(vec_path, map_size=VECTOR_MAP_SIZE)
        with sem.begin(write=True) as st, vec.begin(write=True) as vt:
            for key, tgt in targets.items():
                raw = st.get(key)
                if raw is None:
                    problems.append(f"target vanished: {key.hex()}")
                    continue
                vals = list(msgpack.unpackb(bytes(raw)))
                if dec(vals[F_NAME]) != tgt["old_name"]:
                    problems.append(f"{key.hex()} holds {dec(vals[F_NAME])!r}, "
                                    f"expected {tgt['old_name']!r}")
                    continue
                vals[F_NAME] = tgt["name"]
                while len(vals) <= F_POS:
                    vals.append(None)
                vals[F_POS] = tgt["pos"]
                st.put(key, bytes(msgpack.packb(vals) or b""))
                back = msgpack.unpackb(bytes(st.get(key) or b""))
                if dec(back[F_NAME]) != tgt["name"] or norm_pos(back[F_POS]) != tgt["pos"]:
                    problems.append(f"read-back mismatch: {key.hex()}")
                counts["renamed"] += 1
                if vt.get(key) is not None:
                    vt.delete(key)
                    if vt.get(key) is not None:
                        problems.append(f"vector survived: {key.hex()}")
                    counts["vectors_dropped"] += 1
        sem.close(); vec.close()
        report["write"] = dict(counts)
        report["problems"] = problems
        print(f"  {dict(counts)}", flush=True)
        for p in problems[:20]:
            print("  [PROBLEM]", p)

    with open(args.report, "w") as f:
        json.dump(report, f, indent=1)
    print(f"\nreport: {args.report}")
    if problems:
        raise SystemExit(f"{len(problems)} problem(s)")
    if not args.dry_run:
        print("Left to do: `isabelle-semantics embed Qwen/Qwen3-Embedding-8B --yes` "
              "to refill the dropped vectors.")


if __name__ == "__main__":
    main()
