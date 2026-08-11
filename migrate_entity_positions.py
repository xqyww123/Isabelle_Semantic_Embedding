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

What is written: the ``position`` field of each entity record, and
``positions_done`` on each theory's status record, in one transaction per theory.
Explicitly untouched: every interpretation, the incremental-invalidation fields,
the global counter, and EVERY VECTOR STORE (plan L6 -- routing 1.35M records
through ``Semantic_DB.__setitem__`` would tombstone every vector, and would be
gratuitous because ``position`` does not feed the embedded document text).

Idempotent and resumable: a theory whose status carries ``positions_done`` is
skipped, so an interrupted sweep resumes where it stopped.

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

    Opened and closed here rather than through Semantic_DB: py-lmdb refuses to
    open one environment twice in a process, and this script goes on to run the
    RPC host, whose handlers open the real singleton."""
    env = lmdb.open(DB_PATH, map_size=SEMANTICS_MAP_SIZE, readonly=True, lock=False)
    try:
        backup = f"{DB_PATH}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        os.makedirs(backup)
        env.copy(backup, compact=True)
    finally:
        env.close()
    return backup


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

    async def run() -> None:
        async with Client(args.repl_addr, args.session, timeout=None) as c:
            await c.set_register_thy(False)
            print(f"Loading {len(targets)} theories...", flush=True)
            fullnames = await c.load_theory(
                targets + ["Semantic_Embedding.Semantic_Collection_App"])
            roots = fullnames[:-1]      # drop the Semantic_Collection_App entry
            print(f"Loaded {len(roots)} roots.", flush=True)

            await c.run_app("Semantic_Store.backfill_positions")
            await c._write(roots)       # protocol: one value, the root theory names
            if await stream_app_messages(c):
                sys.exit("Failed.")
            print("Backfill done.")

    asyncio.run(run())


if __name__ == "__main__":
    main()
