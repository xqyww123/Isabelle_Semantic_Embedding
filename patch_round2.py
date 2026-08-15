#!/usr/bin/env python3
"""The second adjudication round's repairs, applied to the PROMOTED store
(BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md §B.6, "The residue's adjudication").

The 13-auditor team read the whole undecided residue and condemned 58 keys over
4 theories: English written about HOL-Hoare's two-constructor ``ref`` sitting on
the phantom-address ``ref`` of HOL-Imperative_HOL / ConcurrentHOL, and
session-misattributing text sitting on the wrong member of the Jinja family.
Plus two CoSMed records whose stored NAME is an out-of-cone alias.

WHAT THIS DOES, AND WHY EACH PIECE
----------------------------------
- **delete** the 58 condemned records and their vectors. A key with no record is
  exactly what `collect` calls "needs interpretation", so deletion is what puts
  them back in front of the LLM; the vector must go with the record or it is left
  orphaned, standing for text that no longer exists.
- **rename** 2 records (`Safety_Properties.obs_defs(n)` ->
  `System_Specification.r_defs(n)`, the in-cone name for the same theorem) and
  **drop their vectors**. The name is part of the embedded document
  (`pretty_print` renders it), and `_auto_embed` only fills ABSENT vectors --
  it never refreshes a stale one -- so a rename that keeps its vector silently
  leaves the old name in the index.
- **clear `finished`** on the 4 claiming theories, or `plan_interpretation`
  reports nothing to do and the deleted records are never rebuilt.

Unlike `patch_staging_store.py`, this runs against the LIVE store: there is no
staging twin to fall back on, so every edit is read back, and `--dry-run`
reports the whole plan without opening anything for writing.

Not idempotent by design: a second run would find the 58 keys already gone and
say so (missing keys are reported, not silently skipped).

Scaffolding for one migration; delete with the rest of Part B.
"""

import argparse
import collections
import json
import os
from typing import Any

import lmdb
import msgpack

SEMANTICS_MAP_SIZE = 1 << 32
VECTOR_MAP_SIZE = 1 << 36
F_NAME = 1                      # positional codec; see _Semantic_DB._decode

# The two CoSMed renames (§B.6, D-batch rows). Written out rather than read from
# a file: two rows, and the target name is a judgement, not a computation.
RENAMES = {
    "1675a24ee99eee7072b4db5e6971f3230229c7842d9d7d6254b4ae5437a459b9":
        ("Safety_Properties.obs_defs(9)", "System_Specification.r_defs(9)"),
    "1675a24ee99eee7072b4db5e6971f32302c9d606be98bc4360fb4051bebc00d8":
        ("Safety_Properties.obs_defs(11)", "System_Specification.r_defs(11)"),
}


def dec(v: Any) -> Any:
    return v.decode() if isinstance(v, bytes) else v


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=os.path.expanduser(
        "~/.cache/Isabelle_Semantic_Embedding"))
    ap.add_argument("--patchlist", required=True,
                    help="suspect_round2_patchlist.json")
    ap.add_argument("--dump", required=True,
                    help="semantics.rekey-dump.lmdb, for theory long name -> hash")
    ap.add_argument("--report", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    plist = json.load(open(args.patchlist))
    condemned = [row["key"] for row in plist["delete_and_reinterpret"]]
    theories = plist["theories"]
    if len(set(condemned)) != len(condemned):
        raise SystemExit("the patchlist repeats a key")

    sem_path = os.path.join(args.cache, "semantics.lmdb")
    vec_name = next(d for d in sorted(os.listdir(args.cache))
                    if d.startswith("vector_") and d.endswith(".lmdb"))
    vec_path = os.path.join(args.cache, vec_name)

    # theory long name -> 16-byte hash (the theory-status key IS the hash)
    name2h = {}
    dmp = lmdb.open(args.dump, readonly=True, lock=False)
    with dmp.begin() as t:
        for k, v in t.cursor():
            k = bytes(k)
            if len(k) <= 16:
                name2h[dec(msgpack.unpackb(bytes(v))[0])] = k
    dmp.close()
    missing_thy = [t for t in theories if t not in name2h]
    if missing_thy:
        raise SystemExit(f"no dump theory key for {missing_thy}")

    ro = args.dry_run
    sem = lmdb.open(sem_path, readonly=True, lock=False) if ro else \
        lmdb.open(sem_path, map_size=SEMANTICS_MAP_SIZE)
    vec = lmdb.open(vec_path, readonly=True, lock=False) if ro else \
        lmdb.open(vec_path, map_size=VECTOR_MAP_SIZE)
    st = sem.begin(write=not ro)
    vt = vec.begin(write=not ro)

    counts: collections.Counter = collections.Counter()
    problems: list[str] = []
    detail: list[dict] = []

    # -- 1. the 58 condemned records ----------------------------------------
    for kh in condemned:
        k = bytes.fromhex(kh)
        raw = st.get(k)
        if raw is None:
            problems.append(f"condemned key already absent: {kh}")
            continue
        name = dec(msgpack.unpackb(bytes(raw))[F_NAME])
        had_vec = vt.get(k) is not None
        detail.append({"action": "delete", "key": kh, "name": name,
                       "had_vector": had_vec})
        if not ro:
            st.delete(k)
            if had_vec:
                vt.delete(k)
            if st.get(k) is not None or vt.get(k) is not None:
                problems.append(f"delete did not take: {kh}")
        counts["deleted_records"] += 1
        counts["deleted_vectors"] += int(had_vec)

    # -- 2. the 2 renames ----------------------------------------------------
    for kh, (want_old, want_new) in RENAMES.items():
        k = bytes.fromhex(kh)
        raw = st.get(k)
        if raw is None:
            problems.append(f"rename target absent: {kh}")
            continue
        vals = list(msgpack.unpackb(bytes(raw)))
        cur = dec(vals[F_NAME])
        if cur != want_old:
            # Refuse rather than guess: the stored name is the evidence the
            # audit reasoned from, and a different one means a different record.
            problems.append(f"rename target {kh} holds {cur!r}, expected {want_old!r}")
            continue
        vals[F_NAME] = want_new
        new_raw = bytes(msgpack.packb(vals) or b"")
        had_vec = vt.get(k) is not None
        detail.append({"action": "rename", "key": kh, "from": cur, "to": want_new,
                       "vector_dropped": had_vec})
        if not ro:
            st.put(k, new_raw)
            if had_vec:
                vt.delete(k)          # the name is in the embedded document
            back = st.get(k)
            if back is None or dec(msgpack.unpackb(bytes(back))[F_NAME]) != want_new:
                problems.append(f"rename did not take: {kh}")
            if vt.get(k) is not None:
                problems.append(f"stale vector survived the rename: {kh}")
        counts["renamed_records"] += 1
        counts["renamed_vectors_dropped"] += int(had_vec)

    # -- 3. clear `finished` on the claiming theories ------------------------
    for thy in theories:
        h = name2h[thy]
        raw = st.get(h)
        if raw is None:
            detail.append({"action": "clear_finished", "theory": thy,
                           "note": "no status record; collect will treat it as fresh"})
            counts["theory_no_status"] += 1
            continue
        d = msgpack.unpackb(bytes(raw))
        was = d.get(b"finished", d.get("finished"))
        d[b"finished"] = False
        detail.append({"action": "clear_finished", "theory": thy, "was": bool(was)})
        if not ro:
            st.put(h, bytes(msgpack.packb(d) or b""))
            raw_back = st.get(h)
            back = msgpack.unpackb(bytes(raw_back)) if raw_back is not None else {}
            if back.get(b"finished", back.get("finished")) is not False:
                problems.append(f"clearing finished did not take: {thy}")
        counts["finished_cleared"] += 1

    if ro:
        st.abort(); vt.abort()
    else:
        st.commit(); vt.commit()
    sem.close(); vec.close()

    rep = {"dry_run": ro, "vector_store": vec_name, "counts": dict(counts),
           "problems": problems, "detail": detail}
    with open(args.report, "w") as f:
        json.dump(rep, f, indent=1)
    print(("DRY RUN: " if ro else "") + json.dumps(dict(counts)))
    for p in problems:
        print("  [PROBLEM]", p)
    print(f"report: {args.report}")
    if problems:
        raise SystemExit(f"{len(problems)} problem(s)")


if __name__ == "__main__":
    main()
