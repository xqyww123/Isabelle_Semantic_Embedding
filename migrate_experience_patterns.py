#!/usr/bin/env python3
"""Migrate EXPERIENCE records: JSON-packed `expr` -> the real `goal_patterns` field.

An experience's goal patterns used to be JSON-packed into `expr` -- the Record field
meant for an entity's single expression -- because Record had nowhere else to put a
list. Every reader therefore had to `json.loads` it, each with its own try/except and
its own divergent failure policy, "corrupt expr" became a failure class that existed
only because of the packing, and `pretty_print` rendered an experience as
`experience <name>: ["\\<forall>x. ...", "finite S"]`.

`goal_patterns: list[str] | None` is now a real field. This script rewrites every
legacy experience record to use it and clears `expr`.

It is SAFE to run repeatedly: already-migrated records are skipped. It is also safe NOT
to run it -- `_Semantic_DB._decode` unpacks legacy records at the storage boundary, so
they keep working; running this just retires that legacy branch for your store (and
fixes pretty_print).

The universal key is content-addressed over (name, patterns, description, experience) --
NOT over `expr` -- so keys do NOT change and no vector or index entry is invalidated.

    SEMANTIC_DB_DIR=... python migrate_experience_patterns.py [--dry-run]
"""

import argparse
import sys

from Isabelle_Semantic_Embedding.semantics import Semantic_DB, SemanticRecord
from Isabelle_RPC_Host.universal_key import EntityKind


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change; write nothing.")
    args = ap.parse_args()

    todo: list[tuple[bytes, SemanticRecord]] = []
    already = corrupt = 0
    for key, rec in Semantic_DB.iter_entity_records():
        if rec.kind != EntityKind.EXPERIENCE:
            continue
        if rec.expr is None and rec.goal_patterns is not None:
            already += 1                       # migrated
        elif rec.goal_patterns:
            todo.append((key, rec))            # _decode unpacked it; persist + clear expr
        else:
            corrupt += 1                       # expr present but unparseable, or no patterns

    print(f"EXPERIENCE records: {already + len(todo) + corrupt}")
    print(f"  already migrated : {already}")
    print(f"  to migrate       : {len(todo)}")
    if corrupt:
        print(f"  UNPARSEABLE      : {corrupt}  (left untouched; they have no patterns and "
              f"cannot be embedded -- inspect them by hand)", file=sys.stderr)
    if not todo:
        print("Nothing to do.")
        return 0
    if args.dry_run:
        print("--dry-run: nothing written.")
        return 0

    for key, rec in todo:
        # goal_patterns is already populated (by _decode's legacy unpack); persist it as
        # a real field and drop the JSON from expr.
        Semantic_DB[key] = rec._replace(expr=None)
    print(f"Migrated {len(todo)} experience record(s): goal_patterns is now a real field, "
          f"expr cleared. Keys unchanged, so vectors and the index stay valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
