#!/usr/bin/env python3
"""Backfill entity positions into an already-collected semantics.lmdb
(ENTITY_POSITION_PLAN.md §8).

Records collected before the position field existed carry ``position = None``.
This pass gives them the real thing.  Route A: it RECOMPUTES each entity's
universal key by re-running the very enumeration a live collection performs
(``Semantic_Store.backfill_positions`` on the Isabelle side), which is what makes
it agree with collection on which occurrence of a duplicated proposition wins.
No LLM is involved and no interpretation is touched.

It therefore needs a running Isa-REPL server on a session image that contains the
theories being swept (the AFP data was collected under ``AFP-ALL-4``), plus the
Python RPC host -- started here if it is not already listening.

What is written: the ``position`` field of each entity record, one transaction per
theory, and nothing else.  Explicitly untouched: every interpretation, the
incremental-invalidation fields, every theory-status record, the global counter,
and EVERY VECTOR STORE (plan L6 -- routing 1.35M records
through ``Semantic_DB.__setitem__`` would tombstone every vector, and would be
gratuitous because ``position`` does not feed the embedded document text).

Idempotent, and that IS the resume story (plan L9): the pass keeps no bookkeeping
of any kind, so an interrupted sweep is resumed by running it again.  Re-encoding a
record whose position is already the value being written produces the same bytes.
The cost of a rerun is re-paying the enumeration, nothing else.

Before and after the sweep it runs the **completeness scan** (§8.4): one pass over
the store counting entity records by codec length.  That is what says how much the
run actually landed -- and it is all it says.  It cannot certify that every record
that should have a position has one, because the store also holds records from
theories no sweep of this image can load, and a record cannot name the theory that
produced it.  Attribution comes from the run log, which is written beside the
backup.

A timestamped backup of semantics.lmdb is taken before the first write (lmdb's
live-safe ``Environment.copy``); ``--no-backup`` skips it, which is what you want
when resuming a sweep that already has one.  The backup covers semantics.lmdb
only -- sufficient precisely BECAUSE no vector store is written.
"""

import argparse
import asyncio
import os
import socket
import sys
import threading
import time

import lmdb
import msgpack

from Isabelle_Semantic_Embedding._paths import semantic_DB_dir
from Isabelle_Semantic_Embedding.isabelle_semantics import stream_app_messages
from Isabelle_Semantic_Embedding.semantics import SEMANTICS_MAP_SIZE

DB_PATH = os.path.join(semantic_DB_dir(), "semantics.lmdb")


def _read_targets(args: argparse.Namespace) -> list[str]:
    targets = list(args.theory)
    if args.theory_file:
        with open(args.theory_file) as f:
            targets += [ln.strip() for ln in f if ln.strip()
                        and not ln.lstrip().startswith("#")]
    return targets


def _backup() -> str:
    """Live-safe copy of semantics.lmdb, taken before anything is written.

    A direct ``lmdb.open`` rather than the Semantic_DB singleton, which is legitimate
    ONLY here: py-lmdb refuses to open a path it already holds (measured, and the
    refusal does not depend on the flags), and this runs -- and closes -- before the
    RPC host starts and its handlers open the singleton.  Everything after this point
    must go through Semantic_DB instead; see ``_scan``."""
    env = lmdb.open(DB_PATH, map_size=SEMANTICS_MAP_SIZE, readonly=True)
    try:
        backup = f"{DB_PATH}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        os.makedirs(backup)
        env.copy(backup, compact=True)
    finally:
        env.close()
    return backup


def _scan() -> dict:
    """The completeness scan (ENTITY_POSITION_PLAN.md §8.4).

    Counts entity records by codec length, and among 13-field ones how many carry a
    position.  Two populations are excluded from the reachable count because no
    sweep can ever reach them, and both are decidable from the key alone: records
    with a WIP theory hash (``key[0]`` LSB set -- ``backfill_theory`` skips every
    non-persistent theory) and EXPERIENCE records (``key[16] == 8`` -- they come
    from ``put_experience``, never from ``enumerate_entries``).

    Goes through ``Semantic_DB.iter_items``, NOT ``lmdb.open``: by the time the
    post-sweep scan runs, the RPC handlers hold the singleton environment in this
    same process, and a second open of that path is refused."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB

    by_len: dict[int, int] = {}
    counts = {"reachable_short": 0, "wip": 0, "experience": 0, "with_position": 0}
    for k, v in Semantic_DB.iter_items():
        if len(k) <= 16:
            continue                                  # theory status / the counter key
        vals = msgpack.unpackb(v)
        n = len(vals)
        by_len[n] = by_len.get(n, 0) + 1
        if n >= 13:
            # A 13-field record has been REACHED even when its position is None:
            # None is the permanent, correct value for every §10 case.
            if vals[12] is not None:
                counts["with_position"] += 1
            continue
        if k[0] & 1:
            counts["wip"] += 1
        elif k[16] == 8:
            counts["experience"] += 1
        else:
            counts["reachable_short"] += 1
    counts["by_len"] = by_len
    return counts


def _scan_line(c: dict) -> str:
    lens = " · ".join(f"{n}:{k}" for n, k in sorted(c["by_len"].items()))
    return (f"lengths {lens} | with a position {c['with_position']} | "
            f"short and reachable {c['reachable_short']} "
            f"(excluded: {c['wip']} WIP, {c['experience']} experience)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--theory", action="append", default=[],
                    help="a root theory to sweep (its whole ancestor cone is swept); "
                         "repeatable")
    ap.add_argument("--theory-file",
                    help="file of root theory names, one per line, '#' comments ignored "
                         "(e.g. tools/Build_AFP_Image/afp_all4_theories.txt)")
    ap.add_argument("--repl-addr", default="127.0.0.1:6666",
                    help="Isa-REPL server address")
    ap.add_argument("--rpc-addr", default="127.0.0.1:27182",
                    help="Python RPC host address; started here if nothing listens")
    ap.add_argument("--session", default="HOL",
                    help="session qualifier for theory name resolution")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip the backup (for resuming a sweep that already has one)")
    args = ap.parse_args()

    targets = _read_targets(args)
    if not targets:
        sys.exit("nothing to do: pass --theory and/or --theory-file")
    if not os.path.isdir(DB_PATH):
        sys.exit(f"semantic DB not found: {DB_PATH}")

    if args.no_backup:
        print("skipping backup (--no-backup)", flush=True)
    else:
        print(f"backing up {DB_PATH} ...", flush=True)
        print(f"backup written: {_backup()}", flush=True)

    import Isabelle_RPC_Host
    from IsaREPL import Client

    host, port = args.rpc_addr.split(":")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        rpc_already_running = s.connect_ex((host, int(port))) == 0
    if rpc_already_running:
        print(f"RPC server already running on {args.rpc_addr}, reusing.", flush=True)
    else:
        logger = Isabelle_RPC_Host.mk_logger_(args.rpc_addr, None)
        threading.Thread(target=Isabelle_RPC_Host.launch_server_,
                         args=(args.rpc_addr, logger), daemon=True).start()
        time.sleep(1)

    log_path = f"{DB_PATH}.positions-{time.strftime('%Y%m%d-%H%M%S')}.log"

    async def run() -> None:
        async with Client(args.repl_addr, args.session, timeout=None) as c:
            await c.set_register_thy(False)
            print(f"Loading {len(targets)} theories...", flush=True)
            fullnames = await c.load_theory(
                targets + ["Semantic_Embedding.Semantic_Collection_App"])
            roots = fullnames[:-1]      # drop the Semantic_Collection_App entry
            print(f"Loaded {len(roots)} roots.", flush=True)

            # The scan opens the store through Semantic_DB, so run it only once the
            # handlers are live -- and never through lmdb.open (see _scan).
            print(f"scan before: {_scan_line(_scan())}", flush=True)

            await c.run_app("Semantic_Store.backfill_positions")
            await c._write(roots)       # protocol: one value, the root theory names
            # Keep the per-theory lines: after the sweep they are the only way to
            # attribute leftover records to theories (§8.4).
            with open(log_path, "w") as log:
                failed = await stream_app_messages(
                    c, sink=lambda line: (log.write(line + "\n"), log.flush()))
            print(f"run log: {log_path}", flush=True)
            print(f"scan after:  {_scan_line(_scan())}", flush=True)
            if failed:
                sys.exit("Failed.")
            print("Backfill done.")

    asyncio.run(run())


if __name__ == "__main__":
    main()
