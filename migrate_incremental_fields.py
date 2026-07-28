#!/usr/bin/env python3
"""Migrate semantics.lmdb entity records to the 12-field codec, appending the
four incremental-invalidation fields (semantic_digest, deps, version,
interpreted_at) as None (CHECK_OUTDATE_PLAN.md §3.1/§11).

The codec is positional tail-append, so this rewrite changes NO reader's
behavior -- a short record already decodes with the trailing fields None.  The
script exists to normalize a store in one pass so that nothing older than the
12-field codec ever rewrites a record from a truncated [:8] view.

Also runs the upgrade-time clean_wip (§11): WIP records are a disposable
cache, and the pre-incremental ones carry no digest -- they would all be
re-interpreted as stale anyway, so the upgrade clears them once (pass
--keep-wip to skip).  The 0xF0 counter key and 16-byte theory-status records
are untouched; tombstones (b"") are left as they are.

Idempotent: a record already at 12 fields is compared against its re-encoding
and skipped when the disk bytes would not change.  A timestamped backup copy of
the environment is written next to the original before any modification
(lmdb's live-safe Environment.copy); --dry-run reports counts and writes
nothing (and takes no backup)."""

import argparse
import os
import sys
import time

import lmdb
import msgpack
from Isabelle_RPC_Host.theory_hash import is_persistent
from Isabelle_Semantic_Embedding._paths import semantic_DB_dir
from Isabelle_Semantic_Embedding.semantics import SEMANTICS_MAP_SIZE

DB_PATH = os.path.join(semantic_DB_dir(), "semantics.lmdb")
N_FIELDS = 12


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change; write nothing, no backup")
    ap.add_argument("--keep-wip", action="store_true",
                    help="skip the upgrade-time clean_wip")
    args = ap.parse_args()

    if not os.path.isdir(DB_PATH):
        sys.exit(f"semantic DB not found: {DB_PATH}")

    env = lmdb.open(DB_PATH, map_size=SEMANTICS_MAP_SIZE)
    if not args.dry_run:
        backup = f"{DB_PATH}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        os.makedirs(backup)
        env.copy(backup, compact=True)
        print(f"backup written: {backup}")

    padded = full = theory = tomb = other = wip_cleared = 0
    with env.begin(write=True) as txn:
        wip_keys: list[bytes] = []
        for key, val in txn.cursor():
            key, val = bytes(key), bytes(val)
            if len(key) < 16:
                other += 1                      # the 0xF0 counter key
                continue
            if len(key) == 16:
                theory += 1
                continue
            if val == b"":
                tomb += 1
                continue
            if not args.keep_wip and not is_persistent(key):
                wip_keys.append(key)
                continue
            vals = msgpack.unpackb(val)
            if not isinstance(vals, (list, tuple)):
                other += 1
                continue
            if len(vals) >= N_FIELDS:
                full += 1
                continue
            new = msgpack.packb(list(vals) + [None] * (N_FIELDS - len(vals)))
            if new == val:
                full += 1
                continue
            padded += 1
            if not args.dry_run:
                txn.put(key, new)               # type: ignore[arg-type]
        # §11 upgrade clean_wip: WIP records (and their WIP theory-status keys,
        # which the length-16 branch above kept out of wip_keys -- collect them
        # here) are cleared outright, not tombstoned: they are machine-local
        # working state, and the pre-incremental ones would re-interpret anyway.
        if not args.keep_wip:
            for key, _ in txn.cursor():
                key = bytes(key)
                if len(key) == 16 and not is_persistent(key):
                    wip_keys.append(key)
            wip_cleared = len(wip_keys)
            if not args.dry_run:
                for k in wip_keys:
                    txn.delete(k)
    env.close()
    mode = "DRY RUN -- nothing written.  " if args.dry_run else ""
    print(f"{mode}padded {padded} records to {N_FIELDS} fields; "
          f"already-full {full}, theory-status {theory}, tombstones {tomb}, "
          f"wip cleared {wip_cleared}, other {other}")


if __name__ == "__main__":
    main()
