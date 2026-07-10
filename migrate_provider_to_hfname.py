#!/usr/bin/env python3
"""Migration: rename embedding vector stores to the canonical HuggingFace-name scheme.

The embedding provider refactor changed the vector-store identity from the old
per-provider registration short name to the canonical model name (HuggingFace
name where one exists), with the LMDB directory using a filesystem-safe form
(`/` -> `__`). This renames the existing store directory accordingly.

  vector_qwen3-embedding-8b.lmdb  ->  vector_Qwen__Qwen3-Embedding-8B.lmdb

This is a plain directory rename: cheap and reversible. It does NOT touch the
embed disk cache (its key prefix changes too, so old entries simply expire by
their 3-day TTL and repopulate) nor semantics.lmdb (whose `model` field records
the interpretation/Claude model, unrelated to the embedding model).

Run with --dry-run first to see what would change. Re-run without it to apply.
"""
import argparse
import os
import sys

from Isabelle_Semantic_Embedding._paths import semantic_DB_dir

CACHE_DIR = semantic_DB_dir()

# old store dir name -> new store dir name (both without the cache dir prefix)
RENAMES = {
    "vector_qwen3-embedding-8b.lmdb": "vector_Qwen__Qwen3-Embedding-8B.lmdb",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be renamed without changing anything")
    args = ap.parse_args()

    if not os.path.isdir(CACHE_DIR):
        print(f"No cache dir at {CACHE_DIR}; nothing to do.")
        return 0

    did = 0
    for old, new in RENAMES.items():
        old_path = os.path.join(CACHE_DIR, old)
        new_path = os.path.join(CACHE_DIR, new)
        if not os.path.isdir(old_path):
            print(f"skip: {old} not present")
            continue
        if os.path.exists(new_path):
            print(f"ERROR: target {new} already exists; refusing to overwrite. "
                  f"Resolve manually.", file=sys.stderr)
            return 1
        if args.dry_run:
            print(f"would rename: {old}  ->  {new}")
            continue
        os.rename(old_path, new_path)
        print(f"renamed: {old}  ->  {new}")
        print(f"  (to roll back: mv {new_path!r} {old_path!r})")
        did += 1

    if args.dry_run:
        print("\n(dry run; no changes made)")
    else:
        print(f"\nDone. {did} store(s) renamed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())