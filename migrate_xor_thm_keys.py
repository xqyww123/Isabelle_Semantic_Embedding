#!/usr/bin/env python3
"""Purge all theorem/rule records from semantics.lmdb and all vector stores.

Run once when switching the store to the XOR theory-key scheme.  A theorem/rule
key (32 bytes, tag 0x02/0x12/0x22/0x32/0x42) carries its constituent theories in
the record's 6th field and its 16-byte prefix is an XOR pseudo-theory; a record
without that list cannot be located by theory and is unsafe to keep, since a
single-constituent key equals hash(T) and can collide byte-for-byte with another
key for the same proposition.  This wipes every theorem/rule record so the
scheme starts clean.

A timestamped backup copy of every touched environment is written next to the
original before any modification (lmdb's live-safe Environment.copy).
Idempotent: a second run finds nothing to delete.
"""

import os
import sys
import time

import lmdb
import platformdirs

from Isabelle_RPC_Host.universal_key import is_thm_rule_key

CACHE_DIR = platformdirs.user_cache_dir("Isabelle_Semantic_Embedding", "Qiyuan")
SEMANTICS_DB_PATH = os.path.join(CACHE_DIR, "semantics.lmdb")


def purge_env(path: str, stamp: str) -> int:
    """Back up the environment at path, then delete all theorem/rule keys."""
    env = lmdb.open(path, map_size=1 << 33)
    backup = f"{path}.bak-{stamp}"
    os.makedirs(backup)
    env.copy(backup, compact=True)
    print(f"backup written: {backup}")

    with env.begin(write=True) as txn:
        to_delete = [bytes(key) for key, _ in txn.cursor() if is_thm_rule_key(bytes(key))]
        for key in to_delete:
            txn.delete(key)
    env.close()
    print(f"  purged {len(to_delete)} theorem/rule entries from {os.path.basename(path)}")
    return len(to_delete)


def main() -> None:
    if not os.path.isdir(SEMANTICS_DB_PATH):
        sys.exit(f"semantic DB not found: {SEMANTICS_DB_PATH}")

    paths = [SEMANTICS_DB_PATH]
    for entry in sorted(os.listdir(CACHE_DIR)):
        if entry.startswith("vector_") and entry.endswith(".lmdb"):
            path = os.path.join(CACHE_DIR, entry)
            if os.path.isdir(path):
                paths.append(path)

    print("Will back up and purge theorem/rule entries from:")
    for p in paths:
        print(f"  {p}")
    if "--yes" not in sys.argv:
        answer = input("\nConfirm? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    stamp = time.strftime("%Y%m%d-%H%M%S")
    total = sum(purge_env(p, stamp) for p in paths)
    print(f"done: {total} entries purged across {len(paths)} environment(s)")


if __name__ == "__main__":
    main()
