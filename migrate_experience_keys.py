#!/usr/bin/env python3
"""The experience pass: migrate EXPERIENCE records onto their repaired keys
(BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md §B.10).

The join (migrate_universal_keys.py) deliberately wrote no EXPERIENCE records and
no EXPERIENCE vectors: experiences are agent-written, never enumerated from a
theory, so the dump never sees them.  After the §B.9 swap they live ONLY in the
pre-swap copies of the store.  This pass carries the 6,768 persistent ones into
the promoted store; the 93 WIP records are dropped (D15 -- their WIP bit was an
artefact of the writing session's configuration, and the pre-swap copies keep
them).

WHAT EACH RECORD GETS
---------------------
§B.10's measured partition, reproduced here record by record:

- Every named constituent theory has a corpus-unique base name and its stored
  hash equals today's -> **copy verbatim, key unchanged.**  The defect resolved
  through a memo on theory BASE names, so a mis-resolution can only ever have
  written a theory whose base name is shared; a record naming only
  corpus-unique base names cannot be carrying one.
- Empty constituent list (the GLOBAL experiences) -> copy verbatim.
- Anything else -> **recompute**: the goal patterns are re-parsed by the
  repaired Universal_Key in a context merged from the theories the record's own
  old constituent list names (the Isa-REPL app
  Semantic_Store.migrate_experience_constituents).  Outcomes:
    * unchanged -- the recomputed list equals the stored one; key unchanged.
    * repaired  -- the list changed; the key's 16-byte prefix is recomputed and
                   the record moves.  The tail (kind byte + xxhash of the
                   content) never moves: it is pure record content.
    * cleared   -- a goal pattern fails to parse in the merged context, or the
                   context cannot be built at all.  The constituent list is set
                   to **[] -- never None**: [] makes the record a GLOBAL
                   experience (experience_index.py's _GLOBAL bucket, always a
                   retrieval candidate, patterns do the filtering); None makes
                   it permanently unreachable (_experience_hits skips
                   theory_constituents is None).  Nothing can regenerate an
                   experience, so None is forbidden here.

One diagnostic, not a refusal: the count of recomputed-versus-stored hash
disagreements on theory names present in both lists.  It should be zero apart
from the 10 known Pure/Approximation names (§B.10).

WHAT THIS NEEDS RUNNING
-----------------------
A running Isa-REPL server on the AFP-ALL-4 image, RESTARTED since the app landed
(a running server does not reload edited .ML).  No RPC host: unlike the dump,
the ML side here is a pure function -- every LMDB read and write is owned by
this script.  Confirm before the real run that nothing is writing experiences
(no AoA session): anything written into the live store's EXPERIENCE keys during
the pass is invisible to it.

Not idempotent: the pass refuses if the target already holds any EXPERIENCE
key.  Since the target held none before the pass, a partial run is redone by
deleting every EXPERIENCE key in the target -- the sources are never written.

After a successful real run: rebuild the experience index
(`isabelle-semantics reindex`), and only then remove the
NEEDS_rebuild_experience_index marker.  §B.9 records why rebuilding before this
pass yields an empty index.

Scaffolding for one migration; delete with the rest of Part B.
"""

import argparse
import asyncio
import collections
import json
import os
import time
from typing import Any

import lmdb
import msgpack

EXPERIENCE_TAG = 0x08
# The real writers' sizes (semantics.py / semantic_embedding.py); an lmdb.open
# with a smaller map_size than the file would refuse.
SEMANTICS_MAP_SIZE = 1 << 32
VECTOR_MAP_SIZE = 1 << 36
F_CONSTS, F_PATTERNS = 5, 7          # positional codec, _Semantic_DB._decode

# §B.10's population, measured 2026-08-14 after the swap.  A gate is a
# comparison against a number fixed BEFORE the run (the join's discipline).
GATES = {
    "experiences_total": 6861,
    "wip_skipped": 93,
    "persistent": 6768,
    "class_verbatim": 5922,
    "class_global": 4,
    "class_recompute": 842,          # 832 shared-base-name + 10 Pure/Approximation
}


def dec(v: Any) -> str:
    return v.decode() if isinstance(v, bytes) else v


def is_wip(key: bytes) -> bool:
    return bool(key[0] & 1)


# ---------------------------------------------------------------------------
# phase 1: scan the source, partition
# ---------------------------------------------------------------------------

class ExpRecord:
    __slots__ = ("key", "raw", "vals", "consts", "patterns", "cls",
                 "outcome", "new_consts", "message", "new_key")

    def __init__(self, key: bytes, raw: bytes):
        self.key = key
        self.raw = raw
        self.vals = list(msgpack.unpackb(raw))
        consts_raw = self.vals[F_CONSTS] if len(self.vals) > F_CONSTS else None
        if consts_raw is None:
            # None differs from [] exactly as in the write path: no experience
            # writer ever stores None, so this is corruption, not a class.
            raise SystemExit(f"record {key.hex()} has theory_constituents=None; "
                             "no EXPERIENCE writer stores that -- refusing")
        self.consts: list[tuple[str, bytes]] = [(dec(n), bytes(h)) for n, h in consts_raw]
        pats_raw = self.vals[F_PATTERNS] if len(self.vals) > F_PATTERNS else None
        self.patterns: 'list[str] | None' = (
            [dec(p) for p in pats_raw] if pats_raw is not None else None)
        self.cls = ""                # verbatim | global | recompute
        self.outcome = ""            # verbatim | unchanged | repaired | cleared
        self.new_consts: 'list[tuple[str, bytes]] | None' = None
        self.message: 'str | None' = None
        self.new_key: bytes = key


def scan_source(source: str) -> 'tuple[list[ExpRecord], int]':
    records, wip = [], 0
    env = lmdb.open(source, readonly=True, lock=False)
    try:
        with env.begin() as txn:
            for k, v in txn.cursor():
                k = bytes(k)
                if len(k) != 32 or k[16] != EXPERIENCE_TAG:
                    continue
                if is_wip(k):
                    wip += 1         # D15: dropped, the pre-swap copies keep them
                    continue
                records.append(ExpRecord(k, bytes(v)))
    finally:
        env.close()
    return records, wip


def dump_census(dump: str) -> 'tuple[dict[str, bytes], dict[str, int]]':
    """Theory long name -> current hash, and base name -> #theories carrying it,
    from the dump's 16-byte theory keys (the key IS the hash)."""
    name_hash: dict[str, bytes] = {}
    base_count: dict[str, int] = collections.defaultdict(int)
    env = lmdb.open(dump, readonly=True, lock=False)
    try:
        with env.begin() as txn:
            for k, v in txn.cursor():
                k = bytes(k)
                if len(k) > 16:
                    continue
                name = dec(msgpack.unpackb(bytes(v))[0])
                name_hash[name] = k
                base_count[name.rsplit(".", 1)[-1]] += 1
    finally:
        env.close()
    return name_hash, base_count


def partition(records: 'list[ExpRecord]', name_hash: 'dict[str, bytes]',
              base_count: 'dict[str, int]') -> None:
    from Isabelle_RPC_Host.universal_key import xor_theory_prefix
    for r in records:
        if not r.consts:
            r.cls, r.outcome = "global", "verbatim"
        elif all(base_count.get(n.rsplit(".", 1)[-1], 0) == 1
                 and name_hash.get(n) == h
                 for n, h in r.consts):
            r.cls, r.outcome = "verbatim", "verbatim"
        else:
            r.cls = "recompute"
        # The invariant measured clean in §B.10 -- prefix = XOR of the stored
        # hashes -- re-checked per record; a failure means this script decoded
        # the record wrongly, not that the store is damaged.
        if xor_theory_prefix([h for _, h in r.consts]) != r.key[:16]:
            raise SystemExit(f"record {r.key.hex()}: stored prefix is not the "
                             "XOR of its stored constituent hashes -- refusing")


# ---------------------------------------------------------------------------
# phase 2: recompute via the Isa-REPL app
# ---------------------------------------------------------------------------

def parse_expmig(msg: str, got: 'dict[str, tuple[str, str]]') -> None:
    """Fold one streamed app message into key-hex -> (OK|FAIL, hex payload)."""
    for line in msg.splitlines():
        if not line.startswith("EXPMIG "):
            continue
        _, status, kh, *rest = line.split(" ", 3)
        got[kh] = (status, rest[0] if rest else "")


def apply_results(todo: 'dict[str, ExpRecord]',
                  got: 'dict[str, tuple[str, str]]') -> None:
    """§B.10's outcome per recompute record: cleared on a FAIL (to [], never
    None), else unchanged/repaired by comparing the recomputed list."""
    missing = sorted(set(todo) - set(got))
    if missing:
        raise SystemExit(f"{len(missing)} record(s) got no result from the app, "
                         f"first {missing[:3]} -- refusing")
    for kh, (status, payload) in got.items():
        r = todo[kh]
        if status == "FAIL":
            r.outcome, r.new_consts = "cleared", []
            r.message = bytes.fromhex(payload).decode("utf-8", errors="replace")
        else:
            pairs = []
            if payload:
                for item in payload.split(","):
                    nh, hh = item.split(":")
                    pairs.append((bytes.fromhex(nh).decode("utf-8"), bytes.fromhex(hh)))
            r.new_consts = pairs
            r.outcome = "unchanged" if set(pairs) == set(r.consts) else "repaired"


async def recompute(records: 'list[ExpRecord]', repl_addr: str, session: str,
                    log_path: str) -> None:
    from IsaREPL import Client
    from Isabelle_Semantic_Embedding.isabelle_semantics import stream_app_messages

    todo = {r.key.hex(): r for r in records if r.cls == "recompute"}
    for kh, r in todo.items():
        if r.patterns is None:       # §B.10 measured 0 of these; belt and braces
            raise SystemExit(f"record {kh} needs recomputation but stores no "
                             "goal_patterns -- refusing (the plan measured none)")
    triples = [(kh, [n for n, _ in r.consts], r.patterns)
               for kh, r in sorted(todo.items())]

    got: dict[str, 'tuple[str, str]'] = {}    # key hex -> (OK|FAIL, payload)

    async with Client(repl_addr, session, timeout=None) as c:
        await c.set_register_thy(False)
        await c.run_app("Semantic_Store.migrate_experience_constituents")
        await c._write(triples)
        with open(log_path, "w") as log:
            failed = await stream_app_messages(
                c, sink=lambda line: (parse_expmig(line, got),
                                      log.write(line + "\n"), log.flush()))
    if failed:
        raise SystemExit("the Isa-REPL app itself failed (see the log); a FAIL "
                         "line per record is expected, an app error is not")
    apply_results(todo, got)


def decide_keys(records: 'list[ExpRecord]') -> 'dict[str, int]':
    """New key per record + the hash-disagreement diagnostic (§B.10: report,
    never a refusal; should be zero apart from the 10 Pure/Approximation names)."""
    from Isabelle_RPC_Host.universal_key import xor_theory_prefix
    disagreements = 0
    for r in records:
        if r.cls != "recompute":
            continue
        assert r.new_consts is not None
        r.new_key = xor_theory_prefix([h for _, h in r.new_consts]) + r.key[16:]
        if r.outcome == "unchanged" and r.new_key != r.key:
            raise SystemExit(f"record {r.key.hex()}: recomputed list equals the "
                             "stored one but the prefix moved -- refusing")
        old = dict(r.consts)
        disagreements += sum(1 for n, h in r.new_consts
                             if n in old and old[n] != h)
    news = [r.new_key for r in records]
    dup = [k for k, c in collections.Counter(news).items() if c > 1]
    if dup:
        raise SystemExit(f"{len(dup)} new-key collision(s), first "
                         f"{dup[0].hex()} -- two records may only collide if "
                         "their tails do, which §B.10 measured they do not")
    return {"hash_disagreements": disagreements}


# ---------------------------------------------------------------------------
# phase 3: write
# ---------------------------------------------------------------------------

def write_phase(records: 'list[ExpRecord]', source_vectors: str,
                target_sem: str, target_vec: str) -> 'dict[str, int]':
    stats = collections.Counter()
    svec = lmdb.open(source_vectors, readonly=True, lock=False)
    sem = lmdb.open(target_sem, map_size=SEMANTICS_MAP_SIZE)
    vec = lmdb.open(target_vec, map_size=VECTOR_MAP_SIZE)
    try:
        with sem.begin(write=True) as st, vec.begin(write=True) as vt, \
             svec.begin() as sv:
            for r in records:
                if r.outcome == "verbatim" or r.outcome == "unchanged":
                    value = r.raw
                else:
                    vals = list(r.vals)
                    vals[F_CONSTS] = [[n, h] for n, h in (r.new_consts or [])]
                    value = bytes(msgpack.packb(vals) or b"")
                if st.get(r.new_key) is not None:
                    raise SystemExit(f"target already holds {r.new_key.hex()} -- "
                                     "refusing mid-write; delete this run's "
                                     "EXPERIENCE keys and rerun")
                st.put(r.new_key, value)
                if bytes(st.get(r.new_key) or b"") != value:
                    raise SystemExit(f"read-back mismatch at {r.new_key.hex()}")
                stats["records_written"] += 1

                v = sv.get(r.key)
                if v is None:
                    stats["vectors_missing"] += 1   # _auto_embed refills lazily
                else:
                    vt.put(r.new_key, bytes(v))
                    stats["vectors_copied"] += 1
    finally:
        svec.close(); sem.close(); vec.close()

    # Post-write scan: the target's EXPERIENCE population is exactly this pass's.
    sem = lmdb.open(target_sem, readonly=True, lock=False)
    try:
        with sem.begin() as txn:
            n = sum(1 for k in txn.cursor().iternext(keys=True, values=False)
                    if len(bytes(k)) == 32 and bytes(k)[16] == EXPERIENCE_TAG)
    finally:
        sem.close()
    stats["target_experience_keys_after"] = n
    return dict(stats)


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True,
                    help="pre-swap semantics.lmdb holding the experiences "
                         "(semantics.lmdb.bak-20260814-152023)")
    ap.add_argument("--source-vectors", required=True,
                    help="pre-swap vector store (vector_*.lmdb.bak-20260814-152023)")
    ap.add_argument("--dump", required=True,
                    help="semantics.rekey-dump.lmdb (theory name/hash census)")
    ap.add_argument("--target-cache", required=True,
                    help="the live cache dir whose semantics.lmdb and vector "
                         "store receive the records")
    ap.add_argument("--repl-addr", default="127.0.0.1:6666")
    ap.add_argument("--session", default="AFP-ALL-4")
    ap.add_argument("--out", required=True, help="report directory")
    ap.add_argument("--dry-run", action="store_true",
                    help="everything except the write phase (the recompute app "
                         "is read-only on the REPL side)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    target_sem = os.path.join(args.target_cache, "semantics.lmdb")
    vec_names = sorted(x for x in os.listdir(args.target_cache)
                       if x.startswith("vector_") and x.endswith(".lmdb"))
    if len(vec_names) != 1:
        raise SystemExit(f"{args.target_cache} holds {len(vec_names)} vector "
                         "stores; expected exactly one")
    target_vec = os.path.join(args.target_cache, vec_names[0])

    # -- preflight: one-shot-ness --
    env = lmdb.open(target_sem, readonly=True, lock=False)
    try:
        with env.begin() as txn:
            pre = sum(1 for k in txn.cursor().iternext(keys=True, values=False)
                      if len(bytes(k)) == 32 and bytes(k)[16] == EXPERIENCE_TAG)
    finally:
        env.close()
    if pre:
        raise SystemExit(f"target already holds {pre} EXPERIENCE key(s); this "
                         "pass is one-shot -- the target held none before it, "
                         "so delete every EXPERIENCE key before rerunning")

    print("phase 1: scanning the source ...", flush=True)
    records, wip = scan_source(args.source)
    name_hash, base_count = dump_census(args.dump)
    partition(records, name_hash, base_count)

    counts = collections.Counter(r.cls for r in records)
    gate_values = {
        "experiences_total": len(records) + wip,
        "wip_skipped": wip,
        "persistent": len(records),
        "class_verbatim": counts["verbatim"],
        "class_global": counts["global"],
        "class_recompute": counts["recompute"],
    }
    problems = [f"{k}: expected {GATES[k]}, got {v}"
                for k, v in gate_values.items() if v != GATES[k]]
    for k, v in gate_values.items():
        mark = "ok" if v == GATES[k] else "!!"
        print(f"  [ {mark} ] {k}: {v}" +
              ("" if v == GATES[k] else f"  (expected {GATES[k]})"), flush=True)
    if problems:
        raise SystemExit("population gates failed; the source is not the store "
                         "§B.10 measured -- refusing")

    print(f"phase 2: recomputing {counts['recompute']} record(s) via the "
          f"Isa-REPL app ...", flush=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(args.out, f"migrate_experience_keys-{stamp}.log")
    asyncio.run(recompute(records, args.repl_addr, args.session, log_path))
    diag = decide_keys(records)

    outcomes = collections.Counter(r.outcome for r in records)
    print(f"  outcomes: {dict(outcomes)}", flush=True)
    print(f"  recomputed-versus-stored hash disagreements: "
          f"{diag['hash_disagreements']} (10 expected: the Pure/Approximation "
          f"names)", flush=True)

    report = {
        "stamp": stamp,
        "source": args.source,
        "gates": gate_values,
        "outcomes": dict(outcomes),
        "hash_disagreements": diag["hash_disagreements"],
        "records": [
            {"old_key": r.key.hex(), "new_key": r.new_key.hex(),
             "class": r.cls, "outcome": r.outcome,
             "old_constituents": [n for n, _ in r.consts],
             **({"new_constituents": [n for n, _ in r.new_consts]}
                if r.new_consts is not None else {}),
             **({"message": r.message} if r.message else {})}
            for r in records if r.cls == "recompute"
        ],
    }

    if args.dry_run:
        report["dry_run"] = True
        path = os.path.join(args.out, "experience_migration_report.json")
        with open(path, "w") as f:
            json.dump(report, f, indent=1)
        print(f"dry run: no store was written; report in {path}", flush=True)
        return

    print("phase 3: writing ...", flush=True)
    stats = write_phase(records, args.source_vectors, target_sem, target_vec)
    report["write"] = stats
    ok = stats["records_written"] == len(records) == \
        stats["target_experience_keys_after"]
    print(f"  written {stats['records_written']}, target now holds "
          f"{stats['target_experience_keys_after']} EXPERIENCE key(s); vectors "
          f"copied {stats.get('vectors_copied', 0)}, missing "
          f"{stats.get('vectors_missing', 0)}", flush=True)
    path = os.path.join(args.out, "experience_migration_report.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=1)
    print(f"report in {path}", flush=True)
    if not ok:
        raise SystemExit("write-phase counts disagree -- inspect the report")
    print("Left to do: `isabelle-semantics reindex`, then remove "
          "NEEDS_rebuild_experience_index.", flush=True)


if __name__ == "__main__":
    main()
