#!/usr/bin/env python3
r"""Repair the stored `template_uk` and `locale_uk` pointers of one user layer, once
(ai-artifacts/TEMPLATE_UK_MIGRATION_PLAN.md §3.2; E5, E6, E14, E15, E16).

A HOLDER is a record whose `locale_provenance` stores the key of its template's
record (`template_uk`) and of its locale's (`locale_uk`).  The theory-hash re-key of
2026-08 moved every record but left many `template_uk` at a generation that has no
record (§2.2); migrations now move the pointers (§3.1), and this script repairs the
ones already wrong.

THE RULE (E5).  A key's bytes after the first 16 do not depend on theory hashes, so
the records sharing a pointer's suffix -- its CANDIDATES -- are one statement at its
different generations, or the statement of a homonymous theory in another session
(a constant's internal name carries its theory's base name).  A candidate PASSES when
its stored constituent hashes equal the holder's on every theory base name both lists
contain (E15): the true template is in the holder's cone, where a base name is
unique.  A pointer whose current target fails the check (an absent target fails it)
is rewritten when exactly one candidate passes; otherwise it stays.  No entity name
is used.  Both pointers are judged so (E16); a locale stores no constituent list, and
its own theory stands for one, read off its key.

CLASSES (§3.2), a partition of each pointer's judged holders, counted apart for
pointers that name no record and for resolving pointers whose target fails the check
(E9): taken (exactly one candidate passes); several pass; refused, a shared theory's
hash differs (candidates exist, none passes); none passes (no candidate).

Refuses when a system layer is installed, with no override: the write's
copy-up-then-modify would copy system-layer holders into the user layer.  Writes
through `Semantic_DB.backfill_field("locale_provenance", ...)`: grant-checked,
batched, vectors untouched.  A backup (`backup_store`) comes first.  A second run
takes nothing, so an interrupted run is resumed by running it again.  Nothing else
may write semantics.lmdb for the duration.

    python repair_template_uk.py --dry-run --report dry.json
    python repair_template_uk.py --report run.json
"""

import argparse
import json
import os
from collections import defaultdict

from Isabelle_RPC_Host.universal_key import is_xor_prefixed_key
from Isabelle_Semantic_Embedding._paths import semantic_DB_dir
from Isabelle_Semantic_Embedding.semantics import Provenance, Semantic_DB, backup_store
from Isabelle_Semantic_Embedding.snapshot_sync import validated_system_db

FIELDS = ("template_uk", "locale_uk")
TAKEN, SEVERAL, REFUSED, NONE = (
    "taken", "several pass", "refused, a shared theory's hash differs", "none passes")
GROUPS = ("names no record", "resolves, its target fails the check")
EXAMPLES = 3


def constituents(key: bytes, rec) -> 'dict[str, bytes]':
    """`rec`'s constituent hashes by theory base name (E15).  A locale's key is its
    theory's hash, a tag and its name, qualified by that theory's base name (E16)."""
    if not is_xor_prefixed_key(key):
        return {key[17:].decode().split(".", 1)[0]: key[:16]}
    if rec.theory_constituents is None:
        raise ValueError(f"XOR-prefixed record {key.hex()} has no constituent list")
    return {n.rsplit(".", 1)[-1]: h for n, h in rec.theory_constituents}


def passes(holder: 'dict[str, bytes]', cand: 'dict[str, bytes]') -> bool:
    """E5's check: the hashes agree on every theory base name both lists contain."""
    return all(cand[n] == h for n, h in holder.items() if n in cand)


def plan() -> 'tuple[list[tuple[bytes, Provenance]], dict]':
    """The writes and the report, from two walks of the user layer (the guard leaves no
    system layer)."""
    holders = []
    for k, v in Semantic_DB.iter_items():
        if len(k) > 16:
            rec = Semantic_DB._decode(v)
            if rec.locale_provenance is not None:
                holders.append((k, rec.name, constituents(k, rec), rec.locale_provenance))
    wanted = {ptr[16:] for *_, prov in holders for f in FIELDS
              if (ptr := getattr(prov, f)) is not None}
    by_suffix = defaultdict(dict)       # suffix -> {key: (name, constituents)}
    for k, v in Semantic_DB.iter_items():
        if len(k) > 16 and k[16:] in wanted:
            rec = Semantic_DB._decode(v)
            by_suffix[k[16:]][k] = (rec.name, constituents(k, rec))

    counts = {f: {"absent": 0, "resolves, its target passes": 0,
                  **{f"{g}: {c}": 0 for g in GROUPS for c in (TAKEN, SEVERAL, REFUSED, NONE)}}
              for f in FIELDS}
    examples = {f: defaultdict(list) for f in FIELDS}
    itself = 0
    writes = []
    for key, name, held, prov in holders:
        new = {}
        for f in FIELDS:
            ptr = getattr(prov, f)
            if ptr is None:
                counts[f]["absent"] += 1
                continue
            cands = by_suffix.get(ptr[16:], {})
            target = cands.get(ptr)
            if target is not None and passes(held, target[1]):
                counts[f]["resolves, its target passes"] += 1
                continue
            passing = [(k, n) for k, (n, c) in cands.items() if passes(held, c)]
            cls = (TAKEN if len(passing) == 1 else SEVERAL if passing
                   else REFUSED if cands else NONE)
            label = f"{GROUPS[0] if target is None else GROUPS[1]}: {cls}"
            counts[f][label] += 1
            if cls == TAKEN:
                new[f] = passing[0][0]
                itself += new[f] == key
            if len(examples[f][label]) < EXAMPLES:
                examples[f][label].append([name] + ([passing[0][1]] if cls == TAKEN else []))
        if new:
            writes.append((key, prov._replace(**new)))
    report = {"holders": len(holders), **counts, "of the taken, the holder itself": itself,
              "writes": len(writes), "examples": examples}
    return writes, report


def main(argv: 'list[str] | None' = None) -> dict:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", required=True, help="where the JSON report is written")
    ap.add_argument("--dry-run", action="store_true", help="count and report; write nothing")
    args = ap.parse_args(argv)

    if validated_system_db() is not None:
        raise SystemExit("refusing: a system layer is installed (no override, "
                         "TEMPLATE_UK_MIGRATION_PLAN.md §3.2)")
    backup = None
    if not args.dry_run:
        # Before this process opens the store (backup_store's precondition).
        backup = backup_store(os.path.join(semantic_DB_dir(), "semantics.lmdb"))
        print(f"backup: {backup}", flush=True)

    writes, report = plan()
    report = {"dry_run": args.dry_run, "backup": backup, **report}
    if not args.dry_run:
        hit, missing = Semantic_DB.backfill_field("locale_provenance", writes)
        written = Semantic_DB.get_many([k for k, _ in writes])
        again, _ = plan()
        report["write"] = {
            "hit": hit, "missing": missing,
            "read back differently": sum(r is None or r.locale_provenance != p
                                         for r, (_, p) in zip(written, writes)),
            "taken by a second plan": len(again)}
    with open(args.report, "w") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in report.items() if k != "examples"},
                     indent=1, ensure_ascii=False))
    if not args.dry_run and any(report["write"][k] for k in (
            "missing", "read back differently", "taken by a second plan")):
        raise SystemExit(f"verification FAILED; report: {args.report}")
    return report


if __name__ == "__main__":
    main()
