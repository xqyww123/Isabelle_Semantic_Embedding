#!/usr/bin/env python3
"""Step 1 of the universal-key migration: dump every entity under its REPAIRED key
(BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md §B.3).

Before the fix, a theorem's key prefix depended on the order theories happened to be
resolved in, because a constant's defining theory was taken to be the leading
qualifier of its internal name -- a theory BASE name, which 1,652 of AFP-ALL-4's
10,614 theories share with another theory.  Part A repaired the computation, which
moves the keys of every theorem-alike record already in ``semantics.lmdb``.  This pass
re-enumerates the corpus with the repaired keys and writes the result to a scratch
store; the join (``migrate_universal_keys.py``, §B.5-B.7) then carries each old
record's interpretation onto its new key.

**Nothing the system uses is written.**  This reads no semantic store and writes only
``semantics.rekey-dump.lmdb`` -- plus, unavoidably, the derived
``Isabelle_Theory_Hash/theory_hash.lmdb`` that resolving the roots refreshes (a
rebuildable hash-to-name cache; §B.2 item 1).  No LLM is involved.

It needs a running Isa-REPL server on a session image holding the theories being
swept (the AFP corpus was collected under ``AFP-ALL-4``), plus the Python RPC host --
started here if nothing is listening.  The REPL must have been restarted since Part A
landed: a running server does not reload edited ``.ML``.

**This script never opens the dump.**  The process that writes it is the RPC host, not
this one, and the two need not even agree on where it is (``semantic_DB_dir()`` is
re-read per process).  So the claim on the scratch store and the read-back of what
landed are both remote procedures served in the host -- ``Semantic_Store.dump_preflight``
and ``Semantic_Store.dump_scan``, called from ML at the start and end of the sweep --
and this script only prints what they report.

**Not idempotent, and there is no resume** (D17).  A second run over an existing dump
would append every record again and make every key look ambiguous; ``dump_preflight``
refuses to start against a store that already exists, and refuses outright if the host
it runs in already has one open.  An interrupted run is redone by moving the directory
aside **and restarting the RPC host** -- without the restart the host keeps writing
into the directory that was moved away.

The target list is ``afp_all4_roots.heap.txt`` -- what the image actually holds, as
opposed to what any wanted-list says it should (§B.4).  Do not substitute
``tools/Build_AFP_Image/afp_all4_theories.txt``: it is a strict subset, 1,283 root
names short, and every one of its names resolves, so the mistake is silent.  This
script echoes the file it was given, and its line count, into the run log.
``collect_cone`` then drops the infrastructure sessions and the three base theories,
so the dumped count is smaller than the target list; the sweep logs which roots it
dropped, by name.
"""

import argparse
import asyncio
import socket
import sys
import threading
import time

from Isabelle_Semantic_Embedding.isabelle_semantics import stream_app_messages


def _read_targets(args: argparse.Namespace) -> list[str]:
    targets = list(args.theory)
    if args.theory_file:
        with open(args.theory_file) as f:
            targets += [ln.strip() for ln in f if ln.strip()
                        and not ln.lstrip().startswith("#")]
    return targets


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--theory", action="append", default=[],
                    help="a root theory to sweep (its whole ancestor cone is swept); "
                         "repeatable")
    ap.add_argument("--theory-file",
                    help="file of root theory names, one per line, '#' comments "
                         "ignored (§B.4: afp_all4_roots.heap.txt, 10,614 names -- NOT "
                         "afp_all4_theories.txt, which is a silent 9,331-name subset)")
    ap.add_argument("--repl-addr", default="127.0.0.1:6666",
                    help="Isa-REPL server address")
    ap.add_argument("--rpc-addr", default="127.0.0.1:27182",
                    help="Python RPC host address; started here if nothing listens")
    ap.add_argument("--session", default="HOL",
                    help="session qualifier for theory name resolution")
    args = ap.parse_args()

    targets = _read_targets(args)
    if not targets:
        sys.exit("nothing to do: pass --theory and/or --theory-file")

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

    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = f"dump_universal_keys-{stamp}.log"

    async def run() -> None:
        async with Client(args.repl_addr, args.session, timeout=None) as c:
            await c.set_register_thy(False)
            # §B.4: which list this ran against is the one thing no later scan can
            # recover, and the plausible wrong file succeeds silently.
            print(f"target list: {args.theory_file or '(--theory only)'} "
                  f"-> {len(targets)} names", flush=True)
            print(f"Loading {len(targets)} theories...", flush=True)
            fullnames = await c.load_theory(
                targets + ["Semantic_Embedding.Semantic_Collection_App"])
            roots = fullnames[:-1]      # drop the Semantic_Collection_App entry
            print(f"Loaded {len(roots)} roots.", flush=True)

            await c.run_app("Semantic_Store.dump_entities")
            await c._write(roots)       # protocol: one value, the root theory names
            # Keep every streamed line: the per-theory lines, the excluded-root names
            # and the final scan are how §B.7's gates are audited when one fails.
            with open(log_path, "w") as log:
                log.write(f"target list: {args.theory_file} -> {len(targets)} names\n")
                failed = await stream_app_messages(
                    c, sink=lambda line: (log.write(line + "\n"), log.flush()))
            print(f"run log: {log_path}", flush=True)
            if failed:
                sys.exit("Failed.")
            print("Dump done.")

    asyncio.run(run())


if __name__ == "__main__":
    main()
