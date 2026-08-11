#!/usr/bin/env python3
"""Merge an extracted semantic-DB snapshot into this machine's cache.

WHEN THIS IS THE RIGHT TOOL
---------------------------
The normal sync (see the `sync-semantic-embedding-db` skill) extracts the
published tarball straight over `~/.cache/Isabelle_Semantic_Embedding`.  That is
correct exactly when the snapshot is newer in every respect.  It is WRONG, and
destructive, when this machine has been embedding: the snapshot's vector store
replaces the local one, and every vector this machine paid for that the snapshot
lacks is gone.

That is the case this script handles.  Extract the tarball to a staging
directory, not over the cache, and merge from there.

WHAT IT DOES
------------
The snapshot ("incoming") is authoritative for the RECORDS; this machine
("local") may hold vectors the snapshot lacks.  So neither side is copied over
the other:

  semantics.lmdb   incoming wins on every key it carries.  A key that exists
                   only locally aborts the run -- the snapshot is then not a
                   superset and this script is the wrong tool for the job.

  vector_*.lmdb    a vector is only valid relative to the record it was computed
                   from, so the decision follows the record:

                   incoming real vector          -> incoming wins (its record won)
                   incoming tombstone, local real vector
                       record unchanged by the merge -> KEEP the local vector
                       record changed by the merge   -> write the tombstone
                   incoming tombstone, no local vector -> write the tombstone
                   key only local                -> untouched

The "record unchanged" branch is the point of the whole script: without it, a
tombstone that merely means "the snapshot's machine had not re-embedded yet"
would throw away a local embedding that is perfectly valid and cost money.

The plan is computed entirely from the PRE-merge state of both sides and only
then applied, which is why the record comparison stays meaningful while
semantics is being overwritten in the same run.

Nothing may be writing either side while this runs -- same rule as packaging a
snapshot.  Stop any RPC host / REPL server first, and restart it afterwards
(they mmap the stores and would keep serving the old inodes).

  merge_snapshot.py --incoming <staging>/Isabelle_Semantic_Embedding \
                    --local ~/.cache/Isabelle_Semantic_Embedding
  merge_snapshot.py ... --apply --undo-out merge_undo.pkl
  merge_snapshot.py --undo-from merge_undo.pkl

`--undo-out` is required with `--apply` and is not optional insurance: a full
backup of a 16 GiB vector store costs tens of minutes and tens of gigabytes,
while recording the pre-merge value of the handful of keys actually written
costs about a megabyte and reverses exactly the same change.
"""

from __future__ import annotations

import argparse
import collections
import os
import pickle
import sys

import lmdb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from Isabelle_Semantic_Embedding.semantic_embedding import (  # noqa: E402
    VECTOR_MAP_SIZE)
from Isabelle_Semantic_Embedding.semantics import (  # noqa: E402
    SEMANTICS_MAP_SIZE, TOMBSTONE)
from Isabelle_Semantic_Embedding.snapshot_sync import _store_dirs  # noqa: E402

# One write transaction per batch: a batch is atomic, and committing as we go
# lets LMDB reuse freed pages instead of holding every dirty page of the run.
BATCH = 2000

VECTOR_BYTES = 8192          # 4096 Q1.15 components; anything else is a marker


def _open_ro(path: str) -> lmdb.Environment:
    """A private read-only open, never the package's singleton env: py-lmdb
    refuses a second open of an env this process already holds."""
    return lmdb.open(path, readonly=True, lock=False, subdir=True)


def _kind(v: bytes) -> str:
    """V real vector | T tombstone | M marker (per-theory progress, format
    sentinel -- everything a vector store holds that is not a vector)."""
    if v == TOMBSTONE:
        return "T"
    return "V" if len(v) == VECTOR_BYTES else "M"


def _vector_stores(root: str) -> list[str]:
    return [s for s in _store_dirs(root) if s.startswith("vector_")]


def plan_semantics(incoming: str, local: str):
    """(writes, local_only, stats); writes is [(key, value)] taken from incoming."""
    writes: list[tuple[bytes, bytes]] = []
    n_same = n_new = n_upd = 0
    inc_keys = set()
    with _open_ro(incoming).begin() as ti, _open_ro(local).begin() as tl:
        for k, v in ti.cursor():
            inc_keys.add(k)
            cur = tl.get(k)
            if cur is None:
                n_new += 1
                writes.append((k, v))
            elif cur != v:
                n_upd += 1
                writes.append((k, v))
            else:
                n_same += 1
        local_only = [k for k, _ in tl.cursor() if k not in inc_keys]
    return writes, local_only, dict(identical=n_same, added=n_new, updated=n_upd)


def plan_vectors(incoming: str, local: str, changed_records: set):
    """`changed_records` = the keys whose semantics record this merge rewrites.
    Only for those may an incoming tombstone displace a local vector."""
    writes: list[tuple[bytes, bytes]] = []
    tab: collections.Counter = collections.Counter()
    with _open_ro(incoming).begin() as ti, _open_ro(local).begin() as tl:
        for k, v in ti.cursor():
            ik = _kind(v)
            cur = tl.get(k)
            lk = "absent" if cur is None else _kind(cur)
            if cur == v:
                tab[(ik, lk, "no-op: identical")] += 1
                continue
            if ik == "T" and lk == "V" and k not in changed_records:
                tab[(ik, lk, "KEEP local vector: record unchanged")] += 1
                continue
            what = {"T": "write tombstone", "V": "write vector",
                    "M": "write marker"}[ik]
            tab[(ik, lk, what)] += 1
            writes.append((k, v))
    return writes, tab


def capture_undo(path: str, writes) -> list:
    """The pre-merge value of every key about to be written (None = absent)."""
    with _open_ro(path).begin() as t:
        return [(k, t.get(k)) for k, _ in writes]


def _map_size(path: str) -> int:
    return (SEMANTICS_MAP_SIZE if os.path.basename(path.rstrip(os.sep)) ==
            "semantics.lmdb" else VECTOR_MAP_SIZE)


def apply_writes(path: str, writes, label: str) -> None:
    if not writes:
        print(f"  {label}: nothing to write")
        return
    env = lmdb.open(path, map_size=_map_size(path), subdir=True)
    try:
        for i in range(0, len(writes), BATCH):
            chunk = writes[i:i + BATCH]
            with env.begin(write=True) as txn:
                for k, v in chunk:
                    txn.put(k, v)
            print(f"  {label}: {i + len(chunk)}/{len(writes)}", flush=True)
    finally:
        env.close()


def restore(undo_path: str) -> int:
    """Put every recorded key back to its pre-merge value, deleting the ones
    that did not exist before."""
    with open(undo_path, "rb") as f:
        undo = pickle.load(f)
    for path, entries in undo.items():
        env = lmdb.open(path, map_size=_map_size(path), subdir=True)
        try:
            with env.begin(write=True) as txn:
                for k, v in entries:
                    txn.delete(k) if v is None else txn.put(k, v)
        finally:
            env.close()
        print(f"  restored {len(entries)} keys in {path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Merge an extracted snapshot into this machine's cache.")
    ap.add_argument("--incoming", help="extracted snapshot dir "
                                       "(the one named Isabelle_Semantic_Embedding)")
    ap.add_argument("--local", help="this machine's cache dir")
    ap.add_argument("--undo-from", help="roll a merge back and exit")
    ap.add_argument("--apply", action="store_true",
                    help="without this, only the plan is printed")
    ap.add_argument("--undo-out", help="where to record the pre-merge values "
                                       "(required with --apply)")
    args = ap.parse_args()

    if args.undo_from:
        return restore(args.undo_from)
    if not (args.incoming and args.local):
        ap.error("--incoming and --local are required")
    if args.apply and not args.undo_out:
        ap.error("--apply requires --undo-out")

    inc_sem = os.path.join(args.incoming, "semantics.lmdb")
    loc_sem = os.path.join(args.local, "semantics.lmdb")

    print("== semantics ==")
    sem_writes, local_only, stats = plan_semantics(inc_sem, loc_sem)
    print(f"  identical {stats['identical']}  added {stats['added']}  "
          f"updated {stats['updated']}  local-only {len(local_only)}")
    if local_only:
        print("ABORT: the snapshot does not carry every local record, so it is "
              "not the superset this script assumes.")
        for k in local_only[:10]:
            print("  local-only key:", k.hex())
        return 1
    changed = {k for k, _ in sem_writes}

    vec_plans = []
    for store in _vector_stores(args.incoming):
        loc_vec = os.path.join(args.local, store)
        print(f"== {store} ==")
        if not os.path.isdir(loc_vec):
            print("  no local store of this name; copying a whole store is not "
                  "what this script is for -- skipping")
            continue
        writes, tab = plan_vectors(os.path.join(args.incoming, store),
                                   loc_vec, changed)
        for (ik, lk, what), n in sorted(tab.items()):
            print(f"  incoming {ik}  local {lk:6s}  {what:34s}  {n}")
        print(f"  -> {len(writes)} writes")
        vec_plans.append((loc_vec, writes))

    if not args.apply:
        print("\n(plan only; pass --apply to write)")
        return 0

    print("\n== recording undo ==")
    undo = {loc_sem: capture_undo(loc_sem, sem_writes)}
    for loc_vec, writes in vec_plans:
        undo[loc_vec] = capture_undo(loc_vec, writes)
    with open(args.undo_out, "wb") as f:
        pickle.dump(undo, f, protocol=4)
    print(f"  {sum(len(v) for v in undo.values())} keys recorded -> "
          f"{args.undo_out} ({os.path.getsize(args.undo_out)} bytes)")

    print("\n== applying ==")
    apply_writes(loc_sem, sem_writes, "semantics")
    for loc_vec, writes in vec_plans:
        apply_writes(loc_vec, writes, os.path.basename(loc_vec))
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
