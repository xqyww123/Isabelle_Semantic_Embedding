#!/usr/bin/env python3
"""Rewrite a semantic vector store's float32 vectors as Q1.15 int16, in place.

This is irreversible: the float32 originals are gone once a record is rewritten.
Take a filesystem backup first (the script refuses to write without --backup
pointing at one that already exists).

Two hazards the store's layout creates, both handled here:

  * The env is not vectors-only. Theory-status records (msgpack, ~12 bytes) live
    under the same keyspace. A blind "read float32, write int16" sweep would
    corrupt every one of them, is_thy_embedded would go False across the board,
    and the next run would re-embed the whole library. Only values whose length is
    exactly D*4 are touched.
  * Any process still running the old code holds this env open and reads vectors
    as float32. After migration it would read int16 as float32 — silent garbage,
    not a crash. Stop and restart every reader on the new code before running.

Re-running is safe: records already at D*2 are skipped.

    python migrate_float32_to_q15.py --store ~/.cache/.../vector_<model>.lmdb   # dry run
    cp -r <store> <store>.bak_$(date +%Y%m%d_%H%M%S)
    python migrate_float32_to_q15.py --store <store> --backup <store>.bak_... --yes
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

import lmdb
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from Isabelle_Semantic_Embedding._vecarith import encode_q15, TARGET_NORM, Q15_SCALE
from Isabelle_Semantic_Embedding import embedding_config as cfg
from Isabelle_Semantic_Embedding.semantic_embedding import unsanitize_model

SCHEMA_KEY = b"\x00__vector_format__"
SCHEMA_VALUE = b"q15/v1"
BATCH = 2000

# Semantic_Vector_Store.clean_all_wip_in_created_dbs cursor-walks this very env and
# deletes every key for which theory_hash.is_persistent(key) is false — and that
# predicate is just `key[0] & 1 == 0`. So the marker's first byte must be even, or
# the next WIP sweep silently eats it.
assert SCHEMA_KEY[0] & 1 == 0, "schema marker would be deleted by the WIP sweep"


def dimension_of(store: pathlib.Path) -> int:
    name = store.name
    if not (name.startswith("vector_") and name.endswith(".lmdb")):
        raise SystemExit(f"{store} does not look like a vector_<model>.lmdb store")
    return cfg.dimension(unsanitize_model(name[len("vector_"):-len(".lmdb")]))


def classify(env: lmdb.Environment, D: int) -> tuple[list[bytes], int, int, dict[int, int]]:
    """Partition the keyspace by value length: to-migrate / already-Q15 / other."""
    todo: list[bytes] = []
    done = other = 0
    sizes: dict[int, int] = {}
    with env.begin(buffers=True) as txn:
        for k, v in txn.cursor():
            n = len(v)
            sizes[n] = sizes.get(n, 0) + 1
            if n == D * 4:
                todo.append(bytes(k))
            elif n == D * 2:
                done += 1
            else:
                other += 1
    return todo, done, other, sizes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", required=True, type=pathlib.Path)
    ap.add_argument("--backup", type=pathlib.Path,
                    help="path to an existing backup copy; required with --yes")
    ap.add_argument("--yes", action="store_true", help="actually write (default: dry run)")
    args = ap.parse_args()

    store = args.store.expanduser()
    if not (store / "data.mdb").exists():
        raise SystemExit(f"no data.mdb under {store}")
    D = dimension_of(store)
    print(f"store     : {store}")
    print(f"dimension : {D}  (float32 {D*4} B -> Q1.15 {D*2} B per vector)")
    print(f"encoding  : rint({TARGET_NORM} * v/|v| * {Q15_SCALE:.0f}) as '<i2'")

    env = lmdb.open(str(store), map_size=1 << 34, readonly=not args.yes,
                    lock=True, max_readers=256)
    try:
        readers = env.readers()
        n_readers = max(0, len(readers.strip().splitlines()) - 1)
        if n_readers > 0:
            print(f"\n!! {n_readers} other reader(s) hold this env open:\n{readers}")
            print("!! Any of them running the OLD code will read int16 as float32 after")
            print("!! migration. Stop and restart them on the new code first.")
            if args.yes:
                raise SystemExit("refusing to migrate with live readers")

        todo, done, other, sizes = classify(env, D)
        print("\nvalue-length histogram:")
        for n, c in sorted(sizes.items(), key=lambda t: -t[1])[:6]:
            tag = ("float32 vector -> MIGRATE" if n == D * 4 else
                   "Q1.15 vector   -> skip (already migrated)" if n == D * 2 else
                   "NOT a vector   -> skip (theory status / meta)")
            print(f"  {n:7d} B x {c:7d}   {tag}")
        print(f"\nto migrate: {len(todo)}   already Q1.15: {done}   untouched: {other}")

        if not args.yes:
            print("\nDRY RUN — nothing written. Re-run with --backup <path> --yes to migrate.")
            return 0
        if args.backup is None or not args.backup.exists():
            raise SystemExit("--yes requires --backup pointing at an existing backup copy")
        if not todo:
            print("nothing to do")
            return 0

        t0 = time.perf_counter()
        migrated = 0
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            with env.begin(write=True, buffers=True) as txn:
                for k in batch:
                    raw = txn.get(k)
                    if raw is None or len(raw) != D * 4:
                        continue  # changed under us; leave it alone
                    vec = np.frombuffer(bytes(raw), dtype=np.float32)
                    txn.put(k, encode_q15(vec).tobytes())
                    migrated += 1
            print(f"  {migrated}/{len(todo)}  ({time.perf_counter()-t0:.1f}s)", end="\r", flush=True)
        with env.begin(write=True) as txn:
            txn.put(SCHEMA_KEY, SCHEMA_VALUE)
        print(f"\nmigrated {migrated} vectors in {time.perf_counter()-t0:.1f}s")

        todo2, done2, _, _ = classify(env, D)
        print(f"verify: remaining float32 = {len(todo2)}   Q1.15 = {done2}")
        if todo2:
            print("!! some float32 records remain; re-run")
            return 1
        # Spot-check a record this run actually rewrote, not just any Q1.15 value.
        with env.begin(buffers=True) as txn:
            raw = txn.get(todo[0])
            q = np.frombuffer(bytes(raw), dtype="<i2").astype(np.float64) / Q15_SCALE
            print(f"spot check {todo[0].hex()[:12]}…: |v| = {np.linalg.norm(q):.4f} "
                  f"(expect ~{TARGET_NORM})")
            marker = txn.get(SCHEMA_KEY)
            print(f"schema marker: {bytes(marker) if marker else None!r}")
        print("\nNote: LMDB never shrinks data.mdb; freed pages are reused, not returned.")
        print("Run mdb_copy -c if you need the disk back.")
        return 0
    finally:
        env.close()


if __name__ == "__main__":
    raise SystemExit(main())
