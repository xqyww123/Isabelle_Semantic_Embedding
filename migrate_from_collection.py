#!/usr/bin/env python3
r"""Give every entity record its `from_collection` field, once
(DYNAMIC_MEMBER_NAMING_PLAN.md §3; the criterion is §2.2's).

WHAT IS WRITTEN
---------------
Field 14 of every walked entity record: the full name of the dynamic
collection the record's NAME was invented from where the criterion selects the
record, nil otherwise -- so that afterwards a stored tuple of FEWER than 14
components means exactly "this record was not reached".  EXPERIENCE records
are skipped (not walked): their names are agent-chosen strings of any shape,
and they keep whatever arity they had.  Theory-status records (16-byte keys)
and the counter key are not entity records and are never touched -- applying
the unpack-pad-put ritual to a status MAP would destroy its values silently.

THE CRITERION (§2.2, written once there and factored here)
----------------------------------------------------------
A record is selected when all four hold: its kind is neither EXPERIENCE (0x08)
nor METHOD (0x07); its position is None; its name matches ^(.*)\((\d+)\)$; and
the base names a THEOREM_COLLECTION record.  `parse_member_base` owns the two
conjuncts every caller agrees on (the kind exclusions and the regex); the
position test and collection-set membership are the CALLERS' tests -- their
polarity is exactly what distinguishes the classifier from the two gates, and
a polarity is each caller's meaning, stated at its call site.

GATES (pre-write, both must be zero)
------------------------------------
- ORPHAN count (base parsed + position ABSENT + base names NO collection
  record): a collection record is produced only in its declaring theory's
  sweep while members are produced wherever the collection is visible, so a
  member whose collection was never interpreted would otherwise be silently
  left unflagged forever.
- WINDOW-VIOLATION count (base parsed + position PRESENT + base IN the
  collection set): non-zero means a position sweep ran inside §2.2's forbidden
  window (a §2.4-renamed member acquired a position while its stored name is
  still coll(i)); abort with the offending keys.

The pass also refuses, loudly, to change any record's existing SOME -- an
existing SOME that this run would write differently (nil included) is the
poisoned-resume signature of §2.2's window paragraph.

PRECONDITIONS
-------------
- migrate_entity_positions._scan reports reachable_short == 0 (checked here,
  and to be archived separately BEFORE this pass runs: afterwards the arity
  signal that scan reads is permanently gone).
- No system-layer database installed (checked; no override): iter_items
  yields the merged view and the read-modify-write pair would materialise
  every system-resident record into the user layer.
- Nothing else reads or writes semantics.lmdb for the duration.  READERS ARE
  NOT OPTIONAL: LMDB cannot recycle pages freed by the batched commits while
  any older read transaction is registered (a resident reader pins roughly a
  full data copy under the 4 GiB map ceiling), and a lock=False reader does
  not register at all and can observe pages being reused under it.
  env.reader_check() is called and env.readers() asserted empty before the
  first write batch.
- Map headroom, checked with numbers: map_size == SEMANTICS_MAP_SIZE and free
  map space >= one live-data copy (the pass rewrites every record once, so
  worst-case growth is on the order of one full copy plus B-tree churn).

Re-running IS the resume mechanism and is idempotent while §2.2's
no-position-sweep window holds (the field is a function of the record's own
name, its position and the collection set); a sweep inside the window is
exactly what the refuse-SOME-change abort exists to catch.

One-off; the backup, the write batching and the raw-put grant live in the
package (semantics.backup_store / semantics.backfill_field), not here.
"""

import argparse
import json
import os
import re
import sys

import lmdb
import msgpack

from Isabelle_Semantic_Embedding._paths import semantic_DB_dir
from Isabelle_Semantic_Embedding.semantics import (
    SEMANTICS_MAP_SIZE, F_NAME, F_POSITION, F_FROM_COLLECTION,
    unpack_fields, backup_store)

EXPERIENCE_TAG, METHOD_TAG, COLLECTION_TAG = 0x08, 0x07, 0x06
IDX = re.compile(r"^(.*)\((\d+)\)$")


def dec(v):
    return v.decode() if isinstance(v, bytes) else v


def parse_member_base(kind_tag: int, name: 'str | None') -> 'str | None':
    """§2.2's shared classifier core: the kind exclusions and the name regex,
    returning the parsed base name or None.  Position and collection-set
    membership are deliberately NOT here -- see the module docstring."""
    if kind_tag in (EXPERIENCE_TAG, METHOD_TAG):
        return None
    m = IDX.match(name or "")
    return m.group(1) if m else None


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sem_path = os.path.join(semantic_DB_dir(), "semantics.lmdb")

    # Backup on line one: backup_store must run BEFORE this process opens the
    # store through the Semantic_DB singleton (its hard precondition).
    backup = None
    if not args.dry_run:
        backup = backup_store(sem_path)
        print(f"backup: {backup}", flush=True)

    from Isabelle_Semantic_Embedding.snapshot_sync import validated_system_db
    if validated_system_db() is not None:
        raise SystemExit(
            "refusing to run against an installed system-layer database: the "
            "read-modify-write pair would materialise every system-resident "
            "record into the user layer -- the whole walked corpus, not just "
            "the members.  No override flag exists on purpose.")

    from Isabelle_Semantic_Embedding.semantics import Semantic_DB

    # Precondition: the position sweep completed on THIS store.  §2.2's
    # criterion tests `position is None`; on a store whose sweep never
    # completed it would select most of the corpus.
    from migrate_entity_positions import _scan, _scan_line
    scan = _scan()
    print("pre-pass scan:", _scan_line(scan), flush=True)
    if scan["reachable_short"] != 0:
        raise SystemExit(
            f"reachable_short = {scan['reachable_short']}: the position sweep "
            "has not completed on this store.  Refusing.")

    # ---- phase 1 (read).  Two sub-passes, because the two key families are
    # unordered relative to each other: the collection-name set must be
    # COMPLETE before anything is classified.
    print("phase 1a: collecting THEOREM_COLLECTION names ...", flush=True)
    colls: set = set()
    for k, v in Semantic_DB.iter_items():
        if len(k) <= 16:
            continue                      # theory status / the counter key
        if k[16] == COLLECTION_TAG:
            try:
                colls.add(dec(unpack_fields(v)[F_NAME]))
            except Exception:
                pass                      # surfaces as undecodable in 1b
    print(f"  {len(colls)} collections", flush=True)

    print("phase 1b: classifying every entity record ...", flush=True)
    decisions: list = []                  # (key, base | None) for every walked record
    counts = {"walked": 0, "matched": 0, "nil_written": 0,
              "experience_skipped": 0, "undecodable": 0}
    orphans: list = []
    violations: list = []
    some_changed: list = []
    for k, v in Semantic_DB.iter_items():
        if len(k) <= 16:
            continue
        if k[16] == EXPERIENCE_TAG:
            counts["experience_skipped"] += 1
            continue
        try:
            vals = unpack_fields(v)
            name = dec(vals[F_NAME])
        except Exception:
            counts["undecodable"] += 1
            continue
        counts["walked"] += 1
        pos_absent = vals[F_POSITION] is None
        cur = dec(vals[F_FROM_COLLECTION]) if vals[F_FROM_COLLECTION] is not None else None
        base = parse_member_base(k[16], name)
        in_set = base is not None and base in colls
        decision = base if (in_set and pos_absent) else None
        if base is not None and pos_absent and not in_set:
            orphans.append(f"{k.hex()} {name}")
        if in_set and not pos_absent:
            violations.append(f"{k.hex()} {name}")
        if cur is not None and decision != cur:
            some_changed.append(f"{k.hex()} {name}: {cur!r} -> {decision!r}")
        decisions.append((bytes(k), decision))
    counts["matched"] = sum(1 for _, d in decisions if d is not None)
    counts["nil_written"] = len(decisions) - counts["matched"]
    print(f"  {counts}", flush=True)

    def bail(msg: str, offenders: list) -> None:
        for x in offenders[:20]:
            print("  [OFFENDER]", x, file=sys.stderr)
        raise SystemExit(msg)

    if orphans:
        bail(f"ORPHAN GATE: {len(orphans)} member-shaped positionless records "
             "whose base names no collection record.  Refusing.", orphans)
    if violations:
        bail(f"WINDOW GATE: {len(violations)} positioned records whose base is "
             "in the collection set -- a position sweep ran inside §2.2's "
             "forbidden window.  Refusing.", violations)
    if some_changed:
        bail(f"{len(some_changed)} records hold a SOME this run would change "
             "-- the poisoned-resume signature.  Refusing.", some_changed)
    if counts["undecodable"]:
        print(f"[WARN] {counts['undecodable']} undecodable records (skipped)",
              file=sys.stderr)

    report = {"dry_run": args.dry_run, "backup": backup,
              "collections": len(colls), **counts,
              "orphans": 0, "window_violations": 0}

    if args.dry_run:
        with open(args.report, "w") as f:
            json.dump(report, f, indent=1)
        print(f"dry run only; report: {args.report}")
        return

    # ---- quiesce + headroom, before the first write batch.  Phase 1's read
    # transactions are closed (both iter_items generators ran to exhaustion).
    env = Semantic_DB._ensure_env()
    try:
        env.reader_check()
    except lmdb.Error:
        pass
    readers = env.readers() or ""
    if "no active readers" not in readers:
        raise SystemExit(
            "resident readers on semantics.lmdb -- LMDB cannot recycle pages "
            "under them and the map would fill.  Stop them first:\n" + readers)
    used = (env.info()["last_pgno"] + 1) * env.stat()["psize"]
    map_size = env.info()["map_size"]
    if map_size != SEMANTICS_MAP_SIZE:
        raise SystemExit(f"map_size {map_size:,} != SEMANTICS_MAP_SIZE "
                         f"{SEMANTICS_MAP_SIZE:,}: refusing")
    if map_size - used < used:
        raise SystemExit(
            f"headroom: {used:,} bytes used of {map_size:,}; the pass "
            f"rewrites every record once (worst case ~one more live copy) "
            f"and {map_size - used:,} bytes free is not enough")

    # ---- phase 2: batched raw puts through the package's one grant holder.
    print("phase 2: writing ...", flush=True)
    hit, missing = Semantic_DB.backfill_field("from_collection", decisions)
    print(f"  hit {hit}, missing {missing}", flush=True)
    report["write"] = {"hit": hit, "missing": missing}
    if missing:
        print(f"[WARN] {missing} keys vanished between the phases -- "
              "something else wrote the store", file=sys.stderr)

    # ---- post-commit verification, in a FRESH read transaction: the
    # precedent read-back (rename_dynamic_members) verified the encoding
    # inside the still-uncommitted transaction, not the committed bytes.
    # Arity is read RAW (len of the unpacked tuple): this audit must keep the
    # tuple-length signal that unpack_fields' padding would destroy.
    print("verify: fresh read pass ...", flush=True)
    expected = dict(decisions)
    vcounts = {"checked": 0, "wrong_value": 0, "short_arity": 0,
               "experience_arity_changed": 0}
    with env.begin() as txn:
        for k, v in txn.cursor():
            k = bytes(k)
            if len(k) <= 16:
                continue
            raw_vals = msgpack.unpackb(bytes(v))
            if k[16] == EXPERIENCE_TAG:
                if len(raw_vals) >= 14:
                    vcounts["experience_arity_changed"] += 1
                continue
            if k not in expected:
                continue                  # undecodable in phase 1, skipped
            vcounts["checked"] += 1
            if len(raw_vals) < 14:
                vcounts["short_arity"] += 1
                continue
            got = dec(raw_vals[13]) if raw_vals[13] is not None else None
            if got != expected[k]:
                vcounts["wrong_value"] += 1
    print(f"  {vcounts}", flush=True)
    report["verify"] = vcounts
    ok = (vcounts["short_arity"] == 0 and vcounts["wrong_value"] == 0
          and vcounts["experience_arity_changed"] == 0
          and vcounts["checked"] == len(expected) - missing)
    report["verified"] = ok
    with open(args.report, "w") as f:
        json.dump(report, f, indent=1)
    print(f"report: {args.report}")
    if not ok:
        raise SystemExit("post-commit verification FAILED -- see the report")
    print("verified OK")


if __name__ == "__main__":
    main()
