#!/usr/bin/env python3
"""Promote the re-keyed store: the §B.9 swap, as one script.

BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md §B.2 (preconditions) and §B.9 (promotion).

WHY ONE SCRIPT
--------------
**Two directories move and there is no atomicity or crash heal across them.** §B.9
cites `install_system_db`, which heals exactly one directory via a single `.old`
name checked at the next run. An interruption *between* the two renames leaves new
records addressing old vectors: every key then gathers as missing, `_auto_embed` is
handed the whole domain, and 16 GiB of paid vectors are silently recomputed. So both
renames live here, a marker file makes the half-swapped state detectable, and
`preflight` refuses to start while that marker exists.

WHAT MOVES, AND WHAT DOES NOT
-----------------------------
- `semantics.lmdb` — **moves**; the join produced a new one.
- `vector_<model>.lmdb` — **moves**; the join produced a new one. It is the only
  vector store on the machine, and the script refuses if it finds several.
- `experience_index.lmdb` — **renamed aside, not replaced**: the join produces no new
  version and §B.10 has not run. It must not be rebuilt in place either, or a
  rollback leaves a post-migration index over a pre-migration store and
  `_experience_hits` drops every candidate (`semantics.py:1917-1919`).
- `theory_hash.lmdb` — **not touched.** Different parent, not re-keyed (§B.7 gate 2
  proves it: 10,550 dump theory keys byte-identical to store keys), and a rebuildable
  cache in any case.

THE PRECONDITION THAT KEEPS BEING UNDERESTIMATED
------------------------------------------------
**A live RPC host makes the swap unsafe even when `fuser` is clean.** The
environments open LAZILY: measured 2026-08-14, the attached host held
`semantics.lmdb` and `theory_hash.lmdb` open while showing no holder on
`experience_index.lmdb` or the vector store, because that REPL had never queried
them. `_Semantic_DB._env` and `_Experience_Index._env` cache on the class for the
process lifetime with no inode re-check, and POSIX rename does not disturb an open
fd or mmap — so a surviving host keeps writing into the rollback target. Killing the
host is not enough: it is a child of `poly`, which forks a fresh one on the next RPC
call. **The REPL server must be stopped**, and stopping it needs the user's say-so
each time (§B.2 item 3). Liveness is checked with `ss` — never by connecting to
:6666, which kills the server.

Scaffolding for one migration; delete with the rest of Part B.
"""

import argparse
import json
import os
import subprocess
import sys
import time

MARKER = "SWAP_IN_PROGRESS"
REBUILD_MARKER = "NEEDS_rebuild_experience_index"
DISK_FLOOR_GIB = 45


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def gib_free(path: str) -> float:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / (1 << 30)


def vector_name(d: str) -> str:
    names = sorted(x for x in os.listdir(d)
                   if x.startswith("vector_") and x.endswith(".lmdb"))
    if len(names) != 1:
        raise SystemExit(
            f"{d} holds {len(names)} vector stores ({', '.join(names) or 'none'}). "
            "This script swaps one; migrating one and leaving the rest old-keyed "
            "would orphan every entry in them.")
    return names[0]


def preflight(cache: str, staging: str, strict: bool) -> 'list[str]':
    bad: list[str] = []

    if os.path.exists(os.path.join(cache, MARKER)):
        bad.append(f"HALF-SWAPPED: {os.path.join(cache, MARKER)} exists. Read it and "
                   "finish or reverse that swap by hand before running this again.")

    # -- the staging directory --
    for n in ("semantics.lmdb", vector_name(staging)):
        p = os.path.join(staging, n)
        if not os.path.isdir(p):
            bad.append(f"staging is missing {n}")
    if any(x.endswith(".building") for x in os.listdir(staging)):
        bad.append(f"{staging} holds a .building name; `_store_dirs` keeps only names "
                   "ending .lmdb, so such a directory is invisible and `_get_lmdb_env` "
                   "would create the real name empty")
    rep = os.path.join(staging, "patch_report.json")
    if os.path.isfile(rep):
        r = json.load(open(rep))
        if r.get("problems"):
            bad.append(f"{rep} reports {len(r['problems'])} problem(s)")
    else:
        bad.append(f"{rep} is absent: the suspect list's repairs (§B.6) have not been "
                   "applied to this staging store")

    # -- no holders, and no REPL --
    listening = sh("ss -ltn 2>/dev/null | grep -c ':6666 '").strip()
    if listening not in ("", "0"):
        bad.append("something is LISTENING on :6666 — the REPL server is up. Stop it "
                   "(that needs the user's say-so, §B.2 item 3); do not connect to the "
                   "port to check, which kills the server.")
    procs = sh("pgrep -a -f 'repl_server|Isa_REPL' | grep -v pgrep").strip()
    if procs:
        bad.append("REPL processes alive:\n      " + procs.replace("\n", "\n      "))
    env_dirs = [os.path.join(cache, "semantics.lmdb"),
                os.path.join(cache, vector_name(cache)),
                os.path.join(cache, "experience_index.lmdb"),
                os.path.expanduser("~/.cache/Isabelle_Theory_Hash/theory_hash.lmdb")]
    for d in env_dirs:
        f = os.path.join(d, "data.mdb")
        if not os.path.exists(f):
            continue
        holders = sh(f"fuser {f} 2>/dev/null").strip()
        if holders:
            bad.append(f"{d} is held by PID(s) {holders}. POSIX rename does not disturb "
                       "an open fd or mmap, so this process would go on writing into the "
                       "rollback target.")
    # A clean fuser proves nothing while a host lives -- the environments open lazily.
    hosts = sh("pgrep -a -f 'Isabelle_RPC_Host|rpc_host' | grep -v pgrep").strip()
    if hosts:
        bad.append("an RPC host is alive; the environments open lazily, so a clean "
                   "fuser above does not clear it:\n      "
                   + hosts.replace("\n", "\n      "))

    # -- disk --
    free = gib_free(cache)
    if free < DISK_FLOOR_GIB:
        bad.append(f"only {free:.1f} GiB free, floor is {DISK_FLOOR_GIB}")
    else:
        print(f"  disk: {free:.1f} GiB free (floor {DISK_FLOOR_GIB})")

    # -- the §B.2 2a backup --
    have = [x for x in os.listdir(cache) if ".pre-swap-" in x]
    if not have:
        msg = ("no *.pre-swap-* backup exists. Every other backup on this machine "
               "predates the 2026-08-13 theory-hash re-key, so the live directory is "
               "the only copy of the post-re-key corpus; §B.9's rollback restores the "
               "pre-swap clones, not a renamed live directory.")
        bad.append(msg) if strict else print(f"  NOTE: {msg}")
    else:
        print(f"  backups present: {len(have)} pre-swap entries")
    return bad


def backup(cache: str) -> None:
    ts = time.strftime("%Y%m%d-%H%M%S")
    made = []
    for n in ("semantics.lmdb", vector_name(cache), "experience_index.lmdb"):
        src = os.path.join(cache, n)
        dst = os.path.join(cache, f"{n}.pre-swap-{ts}")
        if not os.path.isdir(src):
            print(f"  {n}: absent, nothing to back up")
            continue
        # /home is btrfs: a reflink clone is near-instant and initially free.
        r = subprocess.run(["cp", "-a", "--reflink=always", src, dst])
        if r.returncode != 0:
            raise SystemExit(f"reflink clone of {n} failed; refusing to continue "
                             "without a backup")
        made.append(dst)
        print(f"  cloned {n} -> {os.path.basename(dst)}")
    json.dump({"timestamp": ts, "backups": made},
              open(os.path.join(cache, f"pre-swap-{ts}.json"), "w"), indent=1)
    print(f"\nrollback target recorded in pre-swap-{ts}.json")


def swap(cache: str, staging: str) -> None:
    ts = time.strftime("%Y%m%d-%H%M%S")
    vec = vector_name(staging)
    if vec != vector_name(cache):
        raise SystemExit(f"staging's vector store is {vec} but the live one is "
                         f"{vector_name(cache)}; refusing to rename across models")
    plan = [("semantics.lmdb", True), (vec, True), ("experience_index.lmdb", False)]
    mark = os.path.join(cache, MARKER)
    with open(mark, "w") as f:
        json.dump({"timestamp": ts, "staging": staging,
                   "moves": [n for n, _ in plan]}, f, indent=1)
    try:
        for name, replace in plan:
            live = os.path.join(cache, name)
            aside = os.path.join(cache, f"{name}.bak-{ts}")
            if os.path.isdir(live):
                os.rename(live, aside)
                print(f"  {name} -> {os.path.basename(aside)}")
            if replace:
                os.rename(os.path.join(staging, name), live)
                print(f"  staging/{name} -> {name}")
            else:
                print(f"  {name}: renamed aside only; §B.10 owns it and it must be "
                      "rebuilt, not replaced")
    except BaseException:
        print(f"\nFAILED MID-SWAP. {mark} is still there and records what was "
              "intended; finish or reverse by hand before anything opens the store.",
              file=sys.stderr)
        raise
    os.remove(mark)
    with open(os.path.join(cache, REBUILD_MARKER), "w") as f:
        f.write(f"experience_index.lmdb was renamed aside at {ts}.\n"
                "Run `isabelle-semantics reindex` (rebuild_experience_index) before any\n"
                "retrieval relies on experiences: an absent index is created empty on\n"
                "first open, which silently returns no experience hits.\n"
                "Keep semantics.lmdb.bak-* and the vector .bak-* until §B.10 has run --\n"
                "the 6,768 persistent EXPERIENCE records live only there and nothing can\n"
                "regenerate them.\n")
    print(f"\nswapped at {ts}. Left to do: rebuild the experience index "
          f"(see {REBUILD_MARKER}).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["preflight", "backup", "swap"])
    ap.add_argument("--cache", default=os.path.expanduser(
        "~/.cache/Isabelle_Semantic_Embedding"))
    ap.add_argument("--staging", required=True)
    args = ap.parse_args()

    print(f"{args.command}: cache {args.cache}\n            staging {args.staging}")
    strict = args.command == "swap"
    bad = preflight(args.cache, args.staging, strict)
    for b in bad:
        print(f"  [BLOCK] {b}")
    if args.command == "preflight":
        print(f"\n{len(bad)} blocker(s)")
        sys.exit(1 if bad else 0)
    if bad:
        raise SystemExit(f"\n{len(bad)} blocker(s); refusing to {args.command}.")
    print()
    if args.command == "backup":
        backup(args.cache)
    else:
        swap(args.cache, args.staging)


if __name__ == "__main__":
    main()
