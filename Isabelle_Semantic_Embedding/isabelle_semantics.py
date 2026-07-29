#!/usr/bin/env python3
"""Manage the Isabelle semantic interpretation database.

The database is LAYERED (SEMANTIC_DB_LAYERED_PLAN.md): a read-only system DB
(the `isabelle-semantic-data` conda package, or a copy installed by `pull`)
under a writable user DB; deletions are tombstones in the user layer.

Subcommands:
  collect   Collect semantic interpretations for a theory (requires Isa-REPL)
  list      List all theories in the layered database (offline)
  remove    Remove theories: tombstone their records, any residency (offline)
  prune     Remove OLD GENERATIONS of named theories; dry run by default (offline)
  orphans   Read-only report of records no known theory name can claim (offline)
  reindex   Rebuild the user experience index from semantics.lmdb (offline)
  fsck      Check semantics.lmdb invariants; --fix repairs the derived ones (offline)
  embed     Embed interpreted entities lacking a vector for MODEL, whole DB (offline)
  status    Show the system and user layers (offline)
  pull      Install/update the system DB from the conda channel (manual, explicit)
  release   Dispatch the CI release workflow (soft HF-freshness check first)
  export    Rewrite the store into a publishable payload (CI/offline)
"""
import argparse
import os
import sys
import time
from collections import defaultdict

import lmdb
import msgpack
import platformdirs
from Isabelle_Semantic_Embedding._paths import semantic_DB_dir

from Isabelle_RPC_Host.universal_key import is_xor_prefixed_key

# NOTE: Isabelle_Semantic_Embedding is imported lazily, inside the subcommands.
# Importing it pulls in transformers, httpx and the Claude SDK — seconds of startup that
# `list` and `remove` have no use for.

CACHE_DIR = semantic_DB_dir()
SEMANTICS_DB_PATH = os.path.join(CACHE_DIR, "semantics.lmdb")
THEORY_HASH_CACHE_DIR = platformdirs.user_cache_dir("Isabelle_Theory_Hash", "Qiyuan")
THEORY_HASH_DB_PATH = os.path.join(THEORY_HASH_CACHE_DIR, "theory_hash.lmdb")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _loud(line: str) -> str:
    """Red bold on a terminal -- for the one line a skimming reader must not
    miss (user request 2026-07-28); plain when piped or redirected, so logs
    and scripts stay clean."""
    if sys.stdout.isatty():
        return f"\033[1;31m{line}\033[0m"
    return line


def _load_theory_names() -> dict[bytes, str]:
    """Load hash→name mapping from theory_hash.lmdb."""
    if not os.path.exists(THEORY_HASH_DB_PATH):
        return {}
    env = lmdb.open(THEORY_HASH_DB_PATH, readonly=True, lock=False)
    result: dict[bytes, str] = {}
    with env.begin() as txn:
        for key, val in txn.cursor():
            name, _ts = msgpack.unpackb(val)
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            result[bytes(key)] = name
    env.close()
    return result


def _vector_store_paths() -> list[str]:
    """Return paths of all vector_*.lmdb stores on disk."""
    if not os.path.isdir(CACHE_DIR):
        return []
    paths = []
    for entry in os.listdir(CACHE_DIR):
        if entry.startswith("vector_") and entry.endswith(".lmdb"):
            path = os.path.join(CACHE_DIR, entry)
            if os.path.isdir(path):
                paths.append(path)
    return paths


def _resolve_identifiers(identifiers: list[str],
                         thy_hashes_in_db: set[bytes],
                         hash_to_name: dict[bytes, str],
                         ) -> list[bytes]:
    """Resolve theory names or hex prefixes to theory hashes.

    Returns list of resolved hashes. Prints errors and returns empty list
    on ambiguity or missing identifiers.
    """
    name_to_hashes: dict[str, list[bytes]] = defaultdict(list)
    for h, name in hash_to_name.items():
        if h in thy_hashes_in_db:
            name_to_hashes[name].append(h)

    resolved: list[bytes] = []
    had_error = False

    for ident in identifiers:
        # Try as theory name first
        if ident in name_to_hashes:
            matches = name_to_hashes[ident]
            if len(matches) == 1:
                resolved.append(matches[0])
                continue
            else:
                print(f"Error: '{ident}' matches multiple universal keys:", file=sys.stderr)
                for h in matches:
                    print(f"  {h.hex()}", file=sys.stderr)
                print(f"Use a universal key prefix to disambiguate.", file=sys.stderr)
                had_error = True
                continue

        # Try as hex prefix
        try:
            prefix_bytes = bytes.fromhex(ident) if len(ident) % 2 == 0 else None
        except ValueError:
            prefix_bytes = None

        if prefix_bytes is not None:
            matches = [h for h in thy_hashes_in_db if h.startswith(prefix_bytes)]
        else:
            matches = [h for h in thy_hashes_in_db if h.hex().startswith(ident.lower())]

        if len(matches) == 1:
            resolved.append(matches[0])
        elif len(matches) == 0:
            print(f"Error: '{ident}' does not match any theory in the database.", file=sys.stderr)
            had_error = True
        else:
            print(f"Error: '{ident}' is ambiguous, matches {len(matches)} theories:", file=sys.stderr)
            for h in matches:
                name = hash_to_name.get(h, "?")
                print(f"  {h.hex()}  {name}", file=sys.stderr)
            had_error = True

    if had_error:
        return []
    return resolved


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def _parse_thy_status(val: bytes) -> dict:
    data = msgpack.unpackb(val)
    finished = data.get(b"finished", data.get("finished", False))
    cost = data.get(b"cost_usd", data.get("cost_usd", 0.0))
    model = data.get(b"model", data.get("model", b""))
    if isinstance(model, bytes):
        model = model.decode("utf-8", errors="replace")
    driver = data.get(b"driver", data.get("driver", b""))
    if isinstance(driver, bytes):
        driver = driver.decode("utf-8", errors="replace")
    # Report it back in the very syntax that would reproduce it (`--driver`,
    # `declare [[Semantic_Embedding.interpretation_driver]]`).  Records written
    # before there was a choice of backend carry no b"driver" and keep showing
    # the bare model, as they always did.
    return {"finished": finished, "cost_usd": cost,
            "model": f"{driver}.{model}" if driver else model}


def cmd_list(args: argparse.Namespace) -> None:
    """List the theories of the LAYERED database.

    The `Layer` column reads `system` / `user` / `system+user` / `removed`
    (all records tombstoned); entities are counted at their VISIBLE layer (a
    user record shadowing a system one counts as user).  Status is
    `complete` / `partial` (the b"finished" flag; a removed theory shows —).
    """
    from Isabelle_Semantic_Embedding.snapshot_sync import validated_system_db
    from Isabelle_Semantic_Embedding.semantics import record_constituent_hashes
    sysdb = validated_system_db()
    if not os.path.exists(SEMANTICS_DB_PATH) and sysdb is None:
        print(f"No semantic database found at {SEMANTICS_DB_PATH}")
        return
    hash_to_name = _load_theory_names()

    def attr_of(key: bytes, val: bytes) -> 'set[bytes] | None':
        """The theories a record belongs to; None for a legacy XOR record."""
        if is_xor_prefixed_key(key):
            return record_constituent_hashes(val)
        if len(key) > 16:
            return {key[:16]}
        return set()

    usr_status: dict[bytes, dict] = {}
    usr_status_tomb: set[bytes] = set()
    usr_keys: set[bytes] = set()          # entity keys visible in the user layer
    user_tombs: set[bytes] = set()        # entity keys tombstoned in the user layer
    usr_count: dict[bytes, int] = defaultdict(int)
    legacy_thm_count = 0

    if os.path.exists(SEMANTICS_DB_PATH):
        env = lmdb.open(SEMANTICS_DB_PATH, readonly=True, lock=False)
        with env.begin() as txn:
            for key, val in txn.cursor():
                key, val = bytes(key), bytes(val)
                if len(key) == 16:
                    if val == b"":
                        usr_status_tomb.add(key)
                    else:
                        usr_status[key] = _parse_thy_status(val)
                elif val == b"":
                    user_tombs.add(key)
                else:
                    attr = attr_of(key, val)
                    if attr is None:
                        legacy_thm_count += 1
                        continue
                    usr_keys.add(key)
                    for h in attr:
                        usr_count[h] += 1
        env.close()

    sys_status: dict[bytes, dict] = {}
    sys_count: dict[bytes, int] = defaultdict(int)
    tomb_count: dict[bytes, int] = defaultdict(int)
    if sysdb is not None:
        env = lmdb.open(os.path.join(sysdb.path, "semantics.lmdb"),
                        readonly=True, lock=False)
        with env.begin() as txn:
            for key, val in txn.cursor():
                key, val = bytes(key), bytes(val)
                if len(key) == 16:
                    sys_status[key] = _parse_thy_status(val)
                    continue
                attr = attr_of(key, val)
                if attr is None:
                    legacy_thm_count += 1
                    continue
                if key in user_tombs:
                    for h in attr:
                        tomb_count[h] += 1       # a masked system record
                elif key not in usr_keys:        # not shadowed by a user record
                    for h in attr:
                        sys_count[h] += 1
        env.close()
    # Inert-or-user-only tombstones: attribution is only possible for
    # prefix-addressed keys (an XOR tombstone's constituents died with its value).
    for key in user_tombs:
        if not is_xor_prefixed_key(key) and len(key) > 16:
            tomb_count[key[:16]] += 1

    all_hashes = sorted(
        set(usr_status) | set(usr_status_tomb) | set(sys_status)
        | set(usr_count) | set(sys_count) | set(tomb_count),
        key=lambda h: hash_to_name.get(h, h.hex()),
    )
    if not all_hashes:
        print("Database is empty.")
        return

    name_w = max(max((len(hash_to_name.get(h, "?")) for h in all_hashes), default=6), 6)
    name_w = min(name_w, 60)

    print(f"{'Theory':<{name_w}}  {'Entities':>8}  {'Layer':<12}  {'Status':<10}  "
          f"{'Cost':>9}  {'Driver':<32}  Universal Key")
    print("─" * (name_w + 8 + 12 + 10 + 9 + 20 + 16 + 14))

    n_complete = n_partial = n_removed = 0
    from Isabelle_RPC_Host.theory_hash import is_persistent
    for h in all_hashes:
        name = hash_to_name.get(h, "?")
        usr, syc, tmb = usr_count.get(h, 0), sys_count.get(h, 0), tomb_count.get(h, 0)
        # LIVE evidence (visible entities, then a live status record) decides
        # the layer BEFORE any tombstone evidence: a masked XOR record is
        # attributed to ALL its constituent theories, so `removed` on tombstone
        # counts alone would mislabel a live zero-direct-entity co-constituent
        # (the common "theory complete, 0 entities" case).  `removed` = no
        # visible entities AND no live status record, per §14's "all records
        # tombstoned".
        status_tombed = h in usr_status_tomb
        live_status = (usr_status.get(h) if not status_tombed else None) \
            or (sys_status.get(h) if not status_tombed else None)
        if usr and syc:
            layer = "system+user"
        elif syc:
            layer = "system"
        elif usr:
            layer = "user"
        elif live_status is not None:
            layer = "user" if h in usr_status and not status_tombed else "system"
        else:
            layer = "removed"
        if layer == "removed":
            status = "—"
            meta: dict = {}
            n_removed += 1
        else:
            # A tombstoned status key must NOT fall through to the system
            # status (the tombstone masks it, same as every other read).
            meta = live_status or {}
            status = "complete" if meta.get("finished", False) else "partial"
            if meta.get("finished", False):
                n_complete += 1
            else:
                n_partial += 1
        if not is_persistent(h):
            status += " *"
        cost = meta.get("cost_usd", 0.0)
        model = meta.get("model", "")
        print(f"{name:<{name_w}}  {usr + syc:>8}  {layer:<12}  {status:<10}  "
              f"${cost:>8.4f}  {model:<32}  {h.hex()}")

    print()
    total_entities = sum(usr_count.values()) + sum(sys_count.values())
    print(f"{len(all_hashes)} theories ({n_complete} complete, {n_partial} partial, "
          f"{n_removed} removed), {total_entities} entities total "
          f"(theorem/rule records are counted once per constituent theory)")
    if legacy_thm_count:
        print(f"WARNING: {legacy_thm_count} legacy theorem/rule records without "
              f"constituent lists (pre-XOR keys); run migrate_xor_thm_keys.py to purge them.")


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

def _system_sem_path() -> 'str | None':
    """Path of the system layer's semantics.lmdb, or None; exits when NEITHER
    layer exists."""
    from Isabelle_Semantic_Embedding.snapshot_sync import validated_system_db
    sysdb = validated_system_db()
    if not os.path.exists(SEMANTICS_DB_PATH) and sysdb is None:
        print(f"No semantic database found at {SEMANTICS_DB_PATH}", file=sys.stderr)
        sys.exit(1)
    return (os.path.join(sysdb.path, "semantics.lmdb")
            if sysdb is not None else None)


def _discover_theory_hashes(system_sem_path: 'str | None',
                            ) -> tuple[set[bytes], set[bytes]]:
    """(theory hashes attributable in EITHER layer, user-tombstoned keys).

    User tombstones are not records.  Theorem/rule keys carry XOR pseudo-theory
    prefixes: their theories come from the record's constituent list, never
    from the prefix."""
    from Isabelle_Semantic_Embedding.semantics import record_constituent_hashes
    thy_hashes_in_db: set[bytes] = set()
    tombstoned_keys: set[bytes] = set()
    if os.path.exists(SEMANTICS_DB_PATH):
        env = lmdb.open(SEMANTICS_DB_PATH, readonly=True, lock=False)
        with env.begin() as txn:
            for key, val in txn.cursor():
                key, val = bytes(key), bytes(val)
                if val == b"":
                    tombstoned_keys.add(key)
                elif is_xor_prefixed_key(key):
                    thy_hashes_in_db |= record_constituent_hashes(val) or set()
                elif len(key) >= 16:             # < 16 = the 0xF0 counter key
                    thy_hashes_in_db.add(key[:16])
        env.close()
    if system_sem_path is not None:
        env = lmdb.open(system_sem_path, readonly=True, lock=False)
        with env.begin() as txn:
            for key, val in txn.cursor():
                key = bytes(key)
                if key in tombstoned_keys:
                    continue                     # already masked
                if is_xor_prefixed_key(key):
                    thy_hashes_in_db |= record_constituent_hashes(bytes(val)) or set()
                elif len(key) >= 16:             # < 16 = the 0xF0 counter key
                    thy_hashes_in_db.add(key[:16])
        env.close()
    return thy_hashes_in_db, tombstoned_keys


def _collect_removal(resolved_set: set[bytes], tombstoned_keys: set[bytes],
                     system_sem_path: 'str | None',
                     include_experiences: bool = True,
                     ) -> 'tuple[set[bytes], dict[bytes, int], dict[bytes, list[bytes]], bool]':
    """Every key belonging to a theory hash in `resolved_set`, over BOTH layers:
    name-addressed by prefix, thm/rule/experience by constituent list, the
    16-byte theory-status key included.  Returns (keys_to_tomb, per-hash entity
    counts, experience removals with their constituents, any_system_resident).

    `include_experiences=False` leaves EXPERIENCE records untouched (prune's
    scope, CHECK_OUTDATE_PLAN §10: experience retrieval walks the bucket index,
    not recomputed keys, so old-generation constituents do not strand them)."""
    from Isabelle_RPC_Host.universal_key import EntityKind
    from Isabelle_Semantic_Embedding.semantics import record_constituent_hashes
    exp_tag = int(EntityKind.EXPERIENCE)
    del_counts: dict[bytes, int] = defaultdict(int)
    keys_to_tomb: set[bytes] = set()
    exp_removals: dict[bytes, list[bytes]] = {}
    any_system_resident = False

    def visit(key: bytes, val: bytes, in_system: bool) -> None:
        nonlocal any_system_resident
        is_exp = len(key) == 32 and key[16] == exp_tag
        if is_exp and not include_experiences:
            return
        if key in keys_to_tomb:
            # Already collected from the user layer — but a system-resident
            # copy at the same key IS still being masked, and the §14 Note
            # must say so (a user copy shadowing it does not change that).
            if in_system:
                any_system_resident = True
            return
        matched: set[bytes] = set()
        consts: 'set[bytes] | None' = None
        if is_xor_prefixed_key(key):
            consts = record_constituent_hashes(val)
            if consts:
                matched = consts & resolved_set
        elif key[:16] in resolved_set:
            matched = {key[:16]}                 # incl. the 16-byte status key
        if not matched:
            return
        keys_to_tomb.add(key)
        if in_system:
            any_system_resident = True
        for thy in matched:
            if len(key) > 16:
                del_counts[thy] += 1
        if is_exp:
            exp_removals[key] = sorted(consts or set())

    if os.path.exists(SEMANTICS_DB_PATH):
        env = lmdb.open(SEMANTICS_DB_PATH, readonly=True, lock=False)
        with env.begin() as txn:
            for key, val in txn.cursor():
                key, val = bytes(key), bytes(val)
                if val != b"":
                    visit(key, val, in_system=False)
        env.close()
    if system_sem_path is not None:
        env = lmdb.open(system_sem_path, readonly=True, lock=False)
        with env.begin() as txn:
            for key, val in txn.cursor():
                key = bytes(key)
                if key not in tombstoned_keys:
                    visit(key, bytes(val), in_system=True)
        env.close()
    return keys_to_tomb, del_counts, exp_removals, any_system_resident


def _execute_removal(keys_to_tomb: set[bytes],
                     exp_removals: 'dict[bytes, list[bytes]]') -> None:
    """The tombstoning engine shared by `remove` and `prune`.

    ORDER: derived data first, the tombstones LAST -- the exact dual of the
    discipline in experience_store.delete_experience.  The tombstone is what
    makes a key invisible to the discovery scans, so writing it first would
    leave an interruption unrecoverable: a re-run could no longer derive
    keys_to_tomb, and the stale user vectors would keep serving (the L23
    shortcut relies on "tombstoned => user vector already gone").  Interrupted
    THIS way, a re-run just re-derives everything and converges."""
    from Isabelle_Semantic_Embedding.semantics import SEMANTICS_MAP_SIZE
    from Isabelle_Semantic_Embedding.semantic_embedding import VECTOR_MAP_SIZE

    # Really drop the user-layer vectors (vectors carry no tombstones).
    for path in _vector_store_paths():
        venv = lmdb.open(path, map_size=VECTOR_MAP_SIZE)
        with venv.begin(write=True) as txn:
            for key in keys_to_tomb:
                txn.delete(key)
        venv.close()

    # Drop the user-index entries of removed experiences.
    if exp_removals:
        from Isabelle_Semantic_Embedding.experience_index import Experience_Index
        for uk, consts in exp_removals.items():
            if consts:
                Experience_Index.remove(uk, consts)
            else:
                Experience_Index.remove_scanning(uk)

    # Tombstone in the user layer (L8: uniform, no residency check).  The user
    # store may not exist yet on a system-DB-only machine: create it.
    os.makedirs(CACHE_DIR, exist_ok=True)
    env = lmdb.open(SEMANTICS_DB_PATH, map_size=SEMANTICS_MAP_SIZE)
    with env.begin(write=True) as txn:
        for key in keys_to_tomb:
            txn.put(key, b"")
    env.close()


def cmd_remove(args: argparse.Namespace) -> None:
    """Remove theories from the LAYERED database (§4 of the plan, per L8).

    Every record of each requested theory -- ANY residency -- is tombstoned in
    the user layer (`put(key, b"")`); user-layer vectors and user-index entries
    are really dropped.  A system-resident record is thereby masked locally and
    drops out of the published snapshot at the next release."""
    system_sem_path = _system_sem_path()
    hash_to_name = _load_theory_names()

    thy_hashes_in_db, tombstoned_keys = _discover_theory_hashes(system_sem_path)

    resolved = _resolve_identifiers(args.identifiers, thy_hashes_in_db, hash_to_name)
    if not resolved:
        sys.exit(1)
    resolved_set = set(resolved)

    keys_to_tomb, del_counts, exp_removals, any_system_resident = \
        _collect_removal(resolved_set, tombstoned_keys, system_sem_path)

    # Print summary
    print("Will remove:")
    for h in resolved:
        name = hash_to_name.get(h, "?")
        count = del_counts.get(h, 0)
        print(f"  {name:<50}  {count:>5} entities  [{h.hex()}]")

    vec_paths = _vector_store_paths()
    if vec_paths:
        print(f"Also cleaning {len(vec_paths)} vector store(s).")

    if not args.force:
        try:
            answer = input("\nConfirm? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if answer != "y":
            print("Aborted.")
            return

    _execute_removal(keys_to_tomb, exp_removals)

    theories_word = "theory" if len(resolved) == 1 else "theories"
    print(f"Removed {len(resolved)} {theories_word} ({len(keys_to_tomb)} records "
          f"tombstoned; vectors and index entries dropped).")
    if any_system_resident:
        print("Note: system-resident records are now masked locally; they drop "
              "out of the\npublished snapshot at the next release.")


# ---------------------------------------------------------------------------
# prune / orphans (CHECK_OUTDATE_PLAN §10: batch deletion, not GC)
# ---------------------------------------------------------------------------

def _load_theory_generations() -> 'dict[str, list[tuple[bytes, int]]]':
    """theory long name -> [(hash, ts)] from theory_hash.lmdb, PERSISTENT
    hashes only (WIP garbage belongs to clean_wip, §10).  ts is the
    last-touched time the registry keeps per hash (puts overwrite)."""
    from Isabelle_RPC_Host.theory_hash import is_persistent
    out: 'dict[str, list[tuple[bytes, int]]]' = defaultdict(list)
    if not os.path.exists(THEORY_HASH_DB_PATH):
        return out
    env = lmdb.open(THEORY_HASH_DB_PATH, readonly=True, lock=False)
    with env.begin() as txn:
        for key, val in txn.cursor():
            key = bytes(key)
            if not is_persistent(key):
                continue
            name, ts = msgpack.unpackb(val)
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            out[name].append((key, int(ts)))
    env.close()
    return out


def _prune_backup() -> None:
    """The prune-owned rolling backup (§10, approved variant (a)): ONE copy of
    the semantics.lmdb store alone, refreshed in place -- copy to a temp
    directory, then swap it in for the previous backup, so exactly one backup
    ever exists.  Vector stores and the experience index are deliberately NOT
    backed up: vectors are a lazily refilled cache and the index can be rebuilt
    (rebuild_experience_index); the only irreplaceable data is the
    interpretation text itself.  A failed copy (ENOSPC included) aborts the
    whole prune BEFORE anything is deleted."""
    import shutil
    from Isabelle_Semantic_Embedding.semantics import SEMANTICS_MAP_SIZE
    dst = SEMANTICS_DB_PATH + ".prune-backup"
    tmp = f"{dst}.tmp-{os.getpid()}"
    env = lmdb.open(SEMANTICS_DB_PATH, map_size=SEMANTICS_MAP_SIZE)
    try:
        os.makedirs(tmp)
        env.copy(tmp, compact=True)
    except (lmdb.Error, OSError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit(f"backup failed ({e}); nothing was deleted")
    finally:
        env.close()
    old = dst + ".old"
    if os.path.isdir(old):
        shutil.rmtree(old)
    if os.path.isdir(dst):
        os.rename(dst, old)
    os.rename(tmp, dst)
    if os.path.isdir(old):
        shutil.rmtree(old)
    print(f"backup written: {dst}")
    print("  (restore = stop the RPC host, then swap this directory back in "
          f"place of {os.path.basename(SEMANTICS_DB_PATH)})")


def cmd_prune(args: argparse.Namespace) -> None:
    """Remove OLD GENERATIONS of the named theories (§10).

    A "generation" is one persistent hash the theory-hash registry has seen for
    a theory name and that still owns records in the semantic store.  The
    newest --keep generations (by registry timestamp) survive; the rest are
    handed to the shared removal engine.  EXPERIENCE records are out of scope.
    DEFAULT IS A DRY RUN: nothing is deleted without --apply."""
    # --current-from repl: DELIBERATELY UNIMPLEMENTED (user decision,
    # 2026-07-28).  What it would be: instead of trusting the registry's
    # newest timestamp, ask a LIVE Isabelle session -- via the Isa-REPL Python
    # client, hence the --repl-addr/--session flags -- for the hash each named
    # theory is ACTUALLY loaded under right now, and treat those hashes as the
    # current generations.  Why it exists on paper (CHECK_OUTDATE_PLAN §10):
    # "most recently touched" can lie about "current" -- run anything on an
    # old checkout and the OLD content's hash gets a fresh registry timestamp,
    # so a subsequent store-mode prune would keep the old generation and offer
    # to delete the main line's.  Why it is deferred: the failure needs that
    # inverted-recency workflow AND an --apply without reading the dry-run
    # listing (which prints every generation with its timestamp and verdict),
    # AND the damage is bounded anyway (tombstones + the pre-apply backup;
    # worst case, the pruned generation re-interprets as uncached at LLM
    # cost).  If the scenario ever bites, implement it here: connect with the
    # Isa-REPL client, resolve each target name in the session, fetch its
    # current theory hash (Theory_Hash.hash_of on the loaded value), and use
    # that set -- with an explicit error for a theory the session has not
    # loaded -- in place of the newest-timestamp rule below.
    if args.current_from == "repl":
        sys.exit("--current-from repl is not implemented (see the comment "
                 "here for the design); the default store mode -- newest "
                 "registry timestamp -- covers the common case")
    system_sem_path = _system_sem_path()
    thy_hashes_in_db, tombstoned_keys = _discover_theory_hashes(system_sem_path)
    generations = _load_theory_generations()

    # Generations that actually own records, newest first, per name.
    live: 'dict[str, list[tuple[bytes, int]]]' = {
        name: sorted((g for g in gens if g[0] in thy_hashes_in_db),
                     key=lambda g: -g[1])
        for name, gens in generations.items()}

    if args.all:
        targets = sorted(n for n, gens in live.items() if len(gens) > args.keep)
        if not targets:
            print(f"No theory has more than {args.keep} generation(s) with "
                  f"records; nothing to prune.")
            return
    else:
        if not args.identifiers:
            sys.exit("name at least one theory, or pass --all")
        targets = []
        for ident in args.identifiers:
            if ident in live:
                targets.append(ident)
                continue
            matches = [n for n in live if n.endswith("." + ident) or n == ident]
            if len(matches) == 1:
                targets.append(matches[0])
            elif not matches:
                sys.exit(f"unknown theory {ident!r} (not in the theory-hash "
                         f"registry, or no records)")
            else:
                sys.exit(f"ambiguous theory {ident!r}: " + ", ".join(sorted(matches)))

    doomed: set[bytes] = set()
    print("Generations (newest first; the newest "
          f"{args.keep} per theory survive):")
    for name in targets:
        gens = live.get(name, [])
        print(f"  {name}")
        for rank, (h, ts) in enumerate(gens):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
            if rank < args.keep:
                print(f"    keep    {h.hex()}  {when}")
            else:
                doomed.add(h)
                print(f"    DELETE  {h.hex()}  {when}")
        if len(gens) <= args.keep:
            print(f"    (only {len(gens)} generation(s) with records -- nothing to delete)")

    if not doomed:
        print("Nothing to prune.")
        return

    keys_to_tomb, del_counts, exp_removals, _sys_res = _collect_removal(
        doomed, tombstoned_keys, system_sem_path, include_experiences=False)
    n_vec = len(_vector_store_paths())
    print(f"\nWould tombstone {len(keys_to_tomb)} records across "
          f"{len(doomed)} old generation(s)"
          + (f"; vectors dropped from {n_vec} store(s)." if n_vec else "."))

    if not args.apply:
        print(_loud("This was a DRY RUN: the listing above only shows what "
                    "WOULD be deleted -- nothing has been touched.  Re-run "
                    "the same command with --apply to actually delete."))
        return

    # Confirm FIRST, backup second, delete last (review R8): the rolling
    # backup rotation is irreversible -- it replaces the previous backup, the
    # only recovery copy of whatever the LAST applied prune deleted.  A run
    # the user aborts at the prompt must consume nothing; the invariant is
    # only ever "backup before deletion".
    if not args.yes:
        try:
            answer = input("\nConfirm? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if answer != "y":
            print("Aborted.")
            return
    if not args.no_backup:
        _prune_backup()
    _execute_removal(keys_to_tomb, exp_removals)
    print(f"Pruned {len(doomed)} old generation(s): {len(keys_to_tomb)} records "
          f"tombstoned; vectors and index entries dropped.")


def cmd_orphans(args: argparse.Namespace) -> None:
    """Read-only report of records whose prefix/constituents resolve to no
    known theory name (§10).  No automatic deletion: review, then use
    `remove <hash>` on what you judge dead."""
    from Isabelle_Semantic_Embedding.semantics import record_constituent_hashes
    hash_to_name = _load_theory_names()
    if args.system:
        path = _system_sem_path()
        if path is None:
            sys.exit("no system DB installed")
    else:
        if not os.path.exists(SEMANTICS_DB_PATH):
            sys.exit(f"No semantic database found at {SEMANTICS_DB_PATH}")
        path = SEMANTICS_DB_PATH
    from Isabelle_RPC_Host.universal_key import EntityKind
    # Orphans GROUPED by the unknown theory hash that claims them: orphans come
    # in clusters (all the records of one forgotten theory), the group's hash
    # is exactly what `remove` takes, and kind numbers mean nothing to a
    # reader -- so each group shows a count and a few sample entities by kind
    # label and name.
    groups: 'dict[bytes, list[str]]' = defaultdict(list)
    legacy = scanned = n_orphans = 0
    env = lmdb.open(path, readonly=True, lock=False)
    with env.begin() as txn:
        for key, val in txn.cursor():
            key, val = bytes(key), bytes(val)
            if len(key) <= 16 or val == b"":
                continue                         # status / counter / tombstone
            scanned += 1
            owner: 'bytes | None'
            if is_xor_prefixed_key(key):
                consts = record_constituent_hashes(val)
                if consts is None:
                    legacy += 1                  # pre-constituent record: unattributable
                    continue
                if any(h in hash_to_name for h in consts):
                    continue
                owner = min(consts) if consts else None
            else:
                if key[:16] in hash_to_name:
                    continue
                owner = key[:16]
            n_orphans += 1
            if owner is None:
                continue
            try:
                vals = msgpack.unpackb(val)
                kind = EntityKind(vals[0]).label
                name = vals[1].decode() if isinstance(vals[1], bytes) else vals[1]
                groups[owner].append(f"{kind} {name}")
            except Exception:
                groups[owner].append("<undecodable record>")
    env.close()

    where = ("the read-only system database" if args.system
             else "your local (user) database")
    print(f"Scanned {scanned} records in {where}.")
    if not n_orphans and not legacy:
        print("No orphans: every record belongs to a theory name this "
              "machine's registry knows.")
        return
    print(f"{n_orphans} of them are ORPHANED: no theory name known to this "
          f"machine claims them.  That usually means leftovers of theories "
          f"interpreted long ago, or on another machine, whose names never "
          f"reached the local registry.  Grouped by the unknown theory hash "
          f"that owns them:")
    ranked = sorted(groups.items(), key=lambda g: -len(g[1]))
    for owner, members in ranked[:args.limit]:
        samples = "; ".join(members[:3]) + (", ..." if len(members) > 3 else "")
        print(f"  {owner.hex()}  --  {len(members)} record(s), e.g. {samples}")
    if len(ranked) > args.limit:
        rest = sum(len(m) for _, m in ranked[args.limit:])
        print(f"  ... (and {len(ranked) - args.limit} more group(s), "
              f"{rest} record(s); raise --limit to see them)")
    if legacy:
        print(f"  (plus {legacy} very old record(s) that carry no theory "
              f"information at all and cannot be grouped)")
    print(_loud("Read-only report; nothing was deleted.")
          + "  To delete one group after reviewing it, feed its hash to the "
            "remove command:\n"
            f"  isabelle-semantics remove {ranked[0][0].hex() if ranked else '<hash>'}")


# ---------------------------------------------------------------------------
# reindex / fsck
# ---------------------------------------------------------------------------

def _require_db() -> None:
    if not os.path.exists(SEMANTICS_DB_PATH):
        print(f"No semantic database found at {SEMANTICS_DB_PATH}", file=sys.stderr)
        sys.exit(1)


def cmd_reindex(args: argparse.Namespace) -> None:
    _require_db()
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB
    n = Semantic_DB.rebuild_experience_index()
    print(f"Rebuilt the experience index from {n} EXPERIENCE record(s) in semantics.lmdb.")


def _count_user_tombstones() -> int:
    """One cursor scan of the user semantics env, counting b'' values (the
    same single-scan mechanism `status` uses)."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB, is_tombstone
    n = 0
    with Semantic_DB._ensure_env().begin() as txn:
        for _k, v in txn.cursor():
            if is_tombstone(v):
                n += 1
    return n


def _count_shadowed_user_vectors() -> int:
    """User-layer vectors the L23 binding rule currently does not serve: the
    key is tombstoned, or its visible record is system-resident and the system
    store ships a vector for it.  Disk-usage diagnostics only."""
    import contextlib
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB, is_tombstone
    from Isabelle_Semantic_Embedding.semantic_embedding import (
        _get_lmdb_env, _try_system_store_env)
    from Isabelle_Semantic_Embedding.snapshot_sync import validated_system_db
    sysdb = validated_system_db()
    sys_sem = Semantic_DB._ensure_system_env() if sysdb is not None else None
    if sysdb is None or sys_sem is None:
        return 0
    total = 0
    for path in _vector_store_paths():
        sys_env = _try_system_store_env(os.path.join(sysdb.path, os.path.basename(path)))
        with contextlib.ExitStack() as stack:
            vtxn = stack.enter_context(_get_lmdb_env(path).begin())
            utxn = stack.enter_context(Semantic_DB._ensure_env().begin())
            stxn = stack.enter_context(sys_sem.begin())
            svtxn = (stack.enter_context(sys_env.begin())
                     if sys_env is not None else None)
            for k, _v in vtxn.cursor():
                k = bytes(k)
                if len(k) == 16:
                    continue                     # embed status, not a vector
                ur = utxn.get(k)
                if ur is not None:
                    if is_tombstone(ur):
                        total += 1               # tombstoned: nothing is served
                    continue                     # user record: this vector serves
                if (stxn.get(k) is not None and svtxn is not None
                        and svtxn.get(k) is not None):
                    total += 1                   # the system vector wins (L23)
    return total


def cmd_fsck(args: argparse.Namespace) -> None:
    """Check the invariants of semantics.lmdb that can break silently.

    Deliberately NOT checked: whether a record has a vector.  Vectors are a
    lazily-filled derived cache — topk hands unknown keys to _auto_embed, which
    embeds anything whose interpretation is already stored.  A record with no
    vector is legitimate; reporting a cold cache as damage would be noise.

    Both repairable classes are repaired the same way, by recomputing a derived
    artefact from the primary data it is derived from:
      * the experience index is a derived view of the EXPERIENCE records -> rebuild
      * an XOR key prefix is derived from the record's constituent list -> re-key
    """
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB, SEMANTICS_MAP_SIZE
    from Isabelle_Semantic_Embedding.experience_index import Experience_Index

    if args.system:
        # Read-only report on the system layer; nothing here is repairable
        # locally (the payload is immutable), so --fix is refused.
        if args.fix:
            print("Error: --fix cannot repair the read-only system DB.", file=sys.stderr)
            sys.exit(1)
        sys_env = Semantic_DB._ensure_system_env()
        if sys_env is None:
            print("No system DB is installed.", file=sys.stderr)
            sys.exit(1)
        c = Semantic_DB.check_consistency(env=sys_env)
        print(f"system semantics.lmdb : {c.n_records} records, of which "
              f"{len(c.experience_keys)} experiences")
        print(f"  legacy XOR record (no constituent list)      {c.legacy_xor:>7}")
        print(f"  XOR key prefix disagrees with constituents   {len(c.xor_mismatches):>7}")
        if c.legacy_xor or c.xor_mismatches:
            print(
                "\nThe system DB is the published read-only snapshot: nothing on this\n"
                "machine can legitimately produce the problems above, and --fix cannot\n"
                "repair a read-only layer. First rule out a corrupted install by\n"
                "reinstalling it:\n"
                "    conda install --force-reinstall isabelle-semantic-data"
                "   (conda-managed)\n"
                "    isabelle-semantics pull --force"
                "                          (pulled copy)\n"
                "If the problems persist, the published snapshot itself is defective —\n"
                "please report it at https://github.com/xqyww123/Premise_Embedding/issues\n"
                "so the next release can be fixed. Retrieval keeps working meanwhile;\n"
                "the affected records only misbehave for theory attribution\n"
                "(`list` / `remove`).")
            sys.exit(1)
        print("All checks passed.")
        return

    _require_db()
    c = Semantic_DB.check_consistency()
    # USER index only: check_consistency scanned the user layer, so both sides
    # of the two set differences below must be user-scoped -- the system index
    # is immutable and legitimately lists uks the user layer lacks (L17).
    indexed = Experience_Index.all_keys(include_system=False)
    missing_from_index = c.experience_keys - indexed
    stale_in_index = indexed - c.experience_keys

    def row(label: str, n: int, note: str = "") -> None:
        print(f"  {label:<46}{n:>7}{'   ' + note if note else ''}")

    print(f"semantics.lmdb   : {c.n_records} records, of which {len(c.experience_keys)} experiences")
    print(f"experience_index : {len(indexed)} keys")
    print()

    print("[repairable by --fix]")
    row("EXPERIENCE record present, missing from index", len(missing_from_index))
    row("index key with no EXPERIENCE record", len(stale_in_index))
    row("XOR key prefix disagrees with constituents", len(c.xor_mismatches))
    for bad, good in c.xor_mismatches[:5]:
        rec = Semantic_DB[bad]
        print(f"      {rec.name if rec else '?'}")
        print(f"        prefix {bad[:16].hex()} -> should be {good[:16].hex()}")
        if rec is not None and rec.theory_constituents:
            print(f"        constituents: {', '.join(n for n, _ in rec.theory_constituents)}")
    if len(c.xor_mismatches) > 5:
        print(f"      ... and {len(c.xor_mismatches) - 5} more")
    if c.xor_mismatches:
        print("      !! This invariant cannot break on its own. Something wrote a key that")
        print("         disagrees with its own constituent list — check that ML's")
        print("         Universal_Key.compute_constituents still mirrors xor_theory_prefix.")

    print("\n[report only]")
    row("legacy XOR record (no constituent list)", c.legacy_xor, "(run migrate_xor_thm_keys.py)")
    n_tombstones = _count_user_tombstones()
    row("tombstones in the user DB", n_tombstones)
    n_shadowed = _count_shadowed_user_vectors()
    if n_shadowed:
        row("user-layer vectors shadowed by the system DB", n_shadowed,
            "(safe to ignore; disk only)")

    db_bytes = os.path.getsize(os.path.join(SEMANTICS_DB_PATH, "data.mdb"))
    pct = 100.0 * db_bytes / SEMANTICS_MAP_SIZE
    print(f"\n  semantics.lmdb size {db_bytes / 1024 ** 2:.1f} MiB / "
          f"{SEMANTICS_MAP_SIZE / 1024 ** 3:.0f} GiB map_size ({pct:.1f}%)"
          f"{'   ** writes fail once this reaches 100% **' if pct > 80 else ''}")

    problems = (len(missing_from_index) + len(stale_in_index)
                + len(c.xor_mismatches) + c.legacy_xor)

    if args.fix:
        repaired = 0
        if c.xor_mismatches:
            print("\n--fix: re-keying records whose XOR prefix disagrees with their constituents...")
            moved, conflicts = Semantic_DB.repair_xor_prefixes(c.xor_mismatches)
            for bad, good in moved:
                print(f"  moved {bad.hex()[:24]}… -> {good.hex()[:24]}…")
            repaired += len(moved)
            for bad in conflicts:
                print(f"  CONFLICT, left alone: {bad.hex()} — the correct key already holds "
                      f"a different record", file=sys.stderr)
        if missing_from_index or stale_in_index or repaired:
            print("\n--fix: rebuilding the experience index...")
            # The index is derived, so one rebuild subsumes every index-level
            # discrepancy: the entries missing above, the stale ones, and the
            # re-keyed experiences just moved by repair_xor_prefixes.
            n = Semantic_DB.rebuild_experience_index()
            print(f"  Rebuilt from {n} EXPERIENCE record(s) in semantics.lmdb.")
            repaired += len(missing_from_index) + len(stale_in_index)
        problems -= repaired

    print()
    if problems:
        print(f"{problems} problem(s) remain.")
        sys.exit(1)
    print("All checks passed.")


# ---------------------------------------------------------------------------
# status / pull / release / export  (the snapshot artifact surfaces)
# ---------------------------------------------------------------------------

def _run_fail_fast(fn, *a, **kw) -> None:
    """Run a snapshot_sync entry point under this script's fail-fast contract:
    every subcommand is typed by a human at a terminal, so an incompatible
    snapshot or a busy installer must stop the run with a non-zero exit."""
    from Isabelle_Semantic_Embedding.snapshot_sync import SnapshotError
    try:
        fn(*a, **kw)
    except SnapshotError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _confirm() -> bool:
    try:
        return input("\nConfirm? [y/N] ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    from Isabelle_Semantic_Embedding import snapshot_sync
    _run_fail_fast(snapshot_sync.status)


def cmd_pull(args: argparse.Namespace) -> None:
    from Isabelle_Semantic_Embedding import snapshot_sync
    _run_fail_fast(snapshot_sync.install_system_db, force=args.force)


def cmd_export(args: argparse.Namespace) -> None:
    _require_db()
    from Isabelle_Semantic_Embedding import snapshot_sync
    _run_fail_fast(snapshot_sync.export, args.outdir)


# The HF dev-sync source of the published snapshot (see manage_data.py at the
# repo root; the release workflow downloads exactly this file).
HF_DATASET = "ANTPG/MLML-data"
HF_DB_FILE = "contrib/Semantic_Embedding/Isabelle_Semantic_Embedding.tar.zst"
RELEASE_WORKFLOW = "release-semantic-db"
RELEASE_REPO = "xqyww123/isabelle-packaging-ci"


def _hf_db_last_modified():
    """When the HF copy of the semantic DB last changed, or None if unknowable."""
    from huggingface_hub import HfApi
    api = HfApi()
    try:
        [info] = api.get_paths_info(HF_DATASET, [HF_DB_FILE],
                                    repo_type="dataset", expand=True)
        if info.last_commit is not None:
            return info.last_commit.date
    except Exception:
        pass
    return api.repo_info(HF_DATASET, repo_type="dataset").last_modified


def _local_db_last_modified() -> 'float | None':
    """Max mtime over the local stores' data files, or None with no store."""
    latest = None
    if not os.path.isdir(CACHE_DIR):
        return None
    for entry in os.listdir(CACHE_DIR):
        if not (entry.endswith(".lmdb")
                and (entry == "semantics.lmdb" or entry.startswith("vector_")
                     or entry == "experience_index.lmdb")):
            continue
        data = os.path.join(CACHE_DIR, entry, "data.mdb")
        if os.path.isfile(data):
            mtime = os.path.getmtime(data)
            latest = mtime if latest is None else max(latest, mtime)
    return latest


def cmd_release(args: argparse.Namespace) -> None:
    """The soft checklist (L13), then the workflow dispatch.

    The release publishes the HF state, so the ONLY local check is freshness:
    when the local stores look newer than the last HF upload, warn (wording
    §14) and let the user confirm; when the comparison is unverifiable, say so
    and ask the same confirmation.

    INTERACTIVE-ONLY, deliberately with no --yes escape hatch: the prompt
    count varies with environment state (the freshness question is
    conditional), so a piped answer binds positionally to whichever question
    happens to come first — `echo y |` could answer "Publish for real?" and
    fire an unattended REAL release.  Publishing is a human's call."""
    import datetime as _dt
    import subprocess

    if not sys.stdin.isatty():
        print("Error: release is interactive-only — run it from a terminal.",
              file=sys.stderr)
        sys.exit(1)

    local = _local_db_last_modified()
    try:
        remote = _hf_db_last_modified()
    except Exception as e:
        remote = None
        reason = str(e)
    else:
        reason = None

    if local is not None and remote is not None:
        local_dt = _dt.datetime.fromtimestamp(local, tz=_dt.timezone.utc)
        if local_dt > remote:
            print(f"The local database looks NEWER than the last Hugging Face upload\n"
                  f"(local last modified {local_dt:%Y-%m-%d %H:%M}; "
                  f"HF revision from {remote:%Y-%m-%d %H:%M}).\n"
                  f"The release publishes the HF state — your local changes would "
                  f"NOT be included.\n"
                  f"Run `manage_data.py update` first to include them.")
            print("\nRelease the HF state anyway? [y/N] ", end="")
            if input().strip().lower() != "y":
                print("Aborted.")
                return
    elif remote is None:
        print(f"Could not check the Hugging Face upload date"
              f"{f' ({reason})' if reason else ''} — the freshness of the "
              f"release input is unverified.")
        print("\nRelease the HF state anyway? [y/N] ", end="")
        if input().strip().lower() != "y":
            print("Aborted.")
            return

    # Real release or dry run?  The workflow's dry_run input DEFAULTS TO TRUE
    # (a bare dispatch publishes nothing), so the flag must be explicit either
    # way -- a green dry run reading as a completed release was the failure
    # mode this question exists to prevent.
    print("\nPublish for real? [y/N]  (N = dry run: CI builds and validates, "
          "nothing is published)", end=" ")
    try:
        real = input().strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return
    flag = "dry_run=false" if real else "dry_run=true"

    import shutil as _shutil
    if _shutil.which("gh") is None:
        print("`gh` is not available; dispatch manually:\n"
              f"    gh workflow run {RELEASE_WORKFLOW} --repo {RELEASE_REPO} -f {flag}\n"
              "(dry_run=true builds and validates on CI without publishing)")
        return
    print(f"Dispatching the release workflow ({RELEASE_WORKFLOW}"
          f"{'' if real else ', dry run'})...")
    r = subprocess.run(["gh", "workflow", "run", RELEASE_WORKFLOW,
                        "--repo", RELEASE_REPO, "-f", flag])
    if r.returncode != 0:
        print(f"Error: `gh workflow run` exited {r.returncode}.", file=sys.stderr)
        sys.exit(1)
    print("Dispatched." if real
          else "Dispatched (dry run; nothing will be published).")


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------

def cmd_collect(args: argparse.Namespace) -> None:
    if args.reinterpret and args.migrate_on_hash_change:
        print("Error: --reinterpret and --migrate-on-hash-change are mutually exclusive.",
              file=sys.stderr)
        sys.exit(1)
    if args.re_embed and args.reinterpret:
        print("Error: --re-embed and --reinterpret are mutually exclusive.",
              file=sys.stderr)
        sys.exit(1)
    if args.re_embed and args.migrate_on_hash_change:
        print("Error: --re-embed and --migrate-on-hash-change are mutually exclusive.",
              file=sys.stderr)
        sys.exit(1)
    if args.re_embed and not args.embed_models:
        print("Error: --re-embed requires --embed-models.", file=sys.stderr)
        sys.exit(1)

    import asyncio
    import Isabelle_Semantic_Embedding.semantics as sem
    sem.migrate_on_hash_change = args.migrate_on_hash_change

    # Interpretation phase (needs the REPL + RPC host). --re-embed skips it entirely
    # and goes straight to the offline embed below — no Isabelle required.
    if not args.re_embed:
        import threading
        import time
        import Isabelle_RPC_Host
        import Isabelle_Semantic_Embedding.semantic_interpretation as si
        # Only when the user actually asked for one: left empty, the Isabelle
        # config option / environment / default chain decides (see
        # semantic_interpretation._resolve_driver).
        si.interpretation_driver_override = args.driver
        from IsaREPL import Client

        import socket
        host, port = args.rpc_addr.split(":")
        port = int(port)
        rpc_already_running = False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            rpc_already_running = s.connect_ex((host, port)) == 0

        if rpc_already_running:
            print(f"RPC server already running on {args.rpc_addr}, reusing.", flush=True)
        else:
            logger = Isabelle_RPC_Host.mk_logger_(args.rpc_addr, None)
            rpc_thread = threading.Thread(
                target=Isabelle_RPC_Host.launch_server_,
                args=(args.rpc_addr, logger), daemon=True)
            rpc_thread.start()
            time.sleep(1)

        async def main():
            async with Client(args.repl_addr, args.session, timeout=None) as c:
                await c.set_register_thy(False)
                print("Loading theories...", flush=True)
                fullnames = await c.load_theory(
                    list(args.theory) + ["Semantic_Embedding.Semantic_Collection_App"])
                print(f"Loaded: {fullnames}", flush=True)
                targets = fullnames[:-1]   # drop the Semantic_Collection_App entry

                print("Running app...", flush=True)
                await c.run_app("Semantic_Store.collect")
                # Interpret-only protocol: (theory_names, force). Concurrency width is the
                # REPL's own -o threads=N; there is no per-call override.
                await c._write(targets, args.reinterpret)

                has_error = False
                try:
                    while True:
                        raw = await c._feed_and_unpack()
                        if isinstance(raw, (list, tuple)) and len(raw) == 2:
                            msg, err = raw
                            if err is not None and err != ():
                                err_str = err.decode("utf-8") if isinstance(err, bytes) else str(err)
                                print(err_str, file=sys.stderr, flush=True)
                                has_error = True
                                continue
                            if msg is None or msg == ():
                                if (msg is None or msg == ()) and (err is None or err == ()):
                                    break
                                continue
                            if isinstance(msg, bytes):
                                msg = msg.decode("utf-8", errors="replace")
                            if isinstance(msg, str):
                                if msg.startswith("ERROR:"):
                                    print(msg, file=sys.stderr, flush=True)
                                    has_error = True
                                else:
                                    print(msg, flush=True)
                        elif raw is None:
                            break
                        else:
                            print(f"[unexpected: {raw!r}]", flush=True)
                except Exception as e:
                    print(f"Connection error: {e}", file=sys.stderr, flush=True)
                    has_error = True
                    raise

                if has_error:
                    print("Failed.", file=sys.stderr)
                    sys.exit(1)
                else:
                    print("Interpretation done.")

        asyncio.run(main())

    # Embed phase (option D): Python-side whole-DB completeness, offline.
    models = [m.strip() for m in args.embed_models.split(",") if m.strip()] \
        if args.embed_models else []
    if models:
        asyncio.run(_embed_models(models, driver="", base_url="",
                                  force=args.re_embed, yes=args.yes_embed))


# ---------------------------------------------------------------------------
# embed
# ---------------------------------------------------------------------------

def _purge_experience_vectors() -> int:
    """Delete every EXPERIENCE vector from EVERY ``vector_*.lmdb`` (plan §5 migration).

    Experience keys are 32 bytes, XOR-prefixed, with the kind tag at byte 16 (the same
    judgment `_Semantic_DB._scan_experiences` uses), so they are recognized from the key
    alone -- which means this also removes ORPHANS (vectors whose record is gone). A
    force re-embed alone cannot: it only overwrites keys still present in Semantic_DB,
    and it only touches the models named on the command line, leaving old-convention
    vectors alive in every other store (where `contains()` would then keep `_auto_embed`
    from ever refreshing them). Purging everywhere and re-embedding is what makes the
    single document-text convention actually hold across models: unnamed stores simply
    backfill lazily under the new convention (Del1's asymmetry).

    Returns the number of vectors deleted."""
    from Isabelle_Semantic_Embedding.semantics import _iter_vector_store_envs
    from Isabelle_RPC_Host.universal_key import EntityKind
    tag = int(EntityKind.EXPERIENCE)
    deleted = 0
    for env in _iter_vector_store_envs():
        to_delete: list[bytes] = []
        with env.begin() as txn:
            for k, _ in txn.cursor():
                k = bytes(k)
                if len(k) == 32 and k[16] == tag:
                    to_delete.append(k)
        if to_delete:
            with env.begin(write=True) as txn:
                for k in to_delete:
                    txn.delete(k)
            deleted += len(to_delete)
    return deleted


def _parse_kinds(spec: str) -> 'set | None':
    """Parse a comma-separated EntityKind list (e.g. 'experience,theorem') to a set,
    or None for 'all'. Unknown names are a hard error listing the valid ones."""
    from Isabelle_RPC_Host.universal_key import EntityKind
    spec = (spec or "").strip()
    if not spec:
        return None
    out = set()
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.add(EntityKind[tok.upper()])
        except KeyError:
            valid = ", ".join(k.name.lower() for k in EntityKind)
            raise SystemExit(f"unknown kind {tok!r}; valid kinds: {valid}")
    return out


async def _embed_models(models: list[str], *, driver: str, base_url: str,
                        force: bool, yes: bool, kinds: 'set | None' = None) -> None:
    """Make vector_MODEL complete w.r.t. semantics.lmdb, for each model.

    Config resolution + per-model store construction + the CLI's report/warn/confirm
    hooks around the shared ``complete_vector_store`` routine (semantics.py), which
    owns the scan/partition/batch logic and the progress strings.  Drives the scan
    off the Semantic_DB singleton (never a second lmdb.open of semantics.lmdb).
    Non-interactive without ``yes`` and with real work to do is a hard error, never
    a silent skip or an input() hang. Text is derived per (key, record) by
    embed_records -> document_text_of; this tool never assembles it."""
    from Isabelle_Semantic_Embedding.semantics import (
        Semantic_Vector_Store, _resolve_embedding_config_env,
        _collect_embed_candidates, complete_vector_store)
    from Isabelle_Semantic_Embedding.semantic_embedding import make_embedding_provider
    env_driver, env_base_url, _ = _resolve_embedding_config_env()
    driver = driver or env_driver
    base_url = base_url or env_base_url

    async def report(msg: str) -> None:
        print(msg, flush=True)

    async def warn(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    async def confirm(n: int, total: int, chars: int) -> bool:
        if yes:
            return True
        if sys.stdin.isatty():
            return input("Proceed? [y/N] ").strip().lower() == "y"
        # sys.exit is a CLI-only concern and stays in this hook --
        # complete_vector_store itself never exits the process.
        print(f"Refusing to embed {n} entities non-interactively; pass --yes "
              f"(or --yes-embed to `collect`).", file=sys.stderr)
        sys.exit(1)

    candidates = _collect_embed_candidates(kinds)
    for model in models:
        provider = make_embedding_provider(driver, base_url, model)
        store = Semantic_Vector_Store(emb_provider=provider, connection=None)
        await complete_vector_store(
            store, candidates, force=force, label=model,
            report=report, warn=warn, confirm=confirm)


def cmd_embed(args: argparse.Namespace) -> None:
    """Make vector_MODEL complete w.r.t. semantics.lmdb, offline (no Isabelle)."""
    _require_db()
    import asyncio
    from Isabelle_RPC_Host.universal_key import EntityKind
    kinds = _parse_kinds(args.kinds)
    yes = args.yes
    # §5 migration: `--kinds experience --force` must first PURGE every experience vector
    # from EVERY vector_*.lmdb -- otherwise old-convention vectors survive in the stores
    # not named here (and orphans survive everywhere), and `contains()` would keep
    # `_auto_embed` from ever refreshing them. See _purge_experience_vectors.
    #
    # The purge is DESTRUCTIVE, so its confirmation must happen HERE, before it runs --
    # NOT in _embed_models, whose gate sits after it. Otherwise every abort path
    # ("Aborted." on a declined prompt; "Refusing ... non-interactively" + exit 1) would
    # report that nothing was done while the vectors were already gone.
    if args.force and kinds == {EntityKind.EXPERIENCE}:
        if not yes:
            if not sys.stdin.isatty():
                print("Refusing to purge and re-embed experience vectors "
                      "non-interactively; pass --yes.", file=sys.stderr)
                sys.exit(1)
            if input("This DELETES every experience vector from every vector_*.lmdb, "
                     "then re-embeds them. Proceed? [y/N] ").strip().lower() != "y":
                print("Aborted.")
                return
            yes = True           # confirmed here; don't prompt again per model below
        n = _purge_experience_vectors()
        print(f"Purged {n} experience vector(s) from all vector_*.lmdb; re-embedding "
              f"the named model(s) now (other models backfill lazily).")
    asyncio.run(_embed_models(args.models, driver=args.driver, base_url=args.base_url,
                              force=args.force, yes=yes, kinds=kinds))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Console entry point (``isabelle-semantics``).

    The parser and dispatch used to run at import time, which is fine for
    ``python isabelle_semantics.py`` and impossible for an entry point: importing
    the module would parse argv and exit.  Wrapped so it can be both.
    """
    parser = argparse.ArgumentParser(
        description="Manage the Isabelle semantic interpretation database.")
    sub = parser.add_subparsers(dest="command", required=True)

    # collect
    p_collect = sub.add_parser("collect", help="Collect semantic interpretations for theories")
    p_collect.add_argument("theory", nargs="+",
        help="Theory name(s) to interpret (e.g., HOL.List HOL.Map). Their ancestor cones "
             "are merged and interpreted under one DAG.")
    p_collect.add_argument("--repl-addr", default="127.0.0.1:6666", help="Isa-REPL server address")
    p_collect.add_argument("--rpc-addr", default="127.0.0.1:27182", help="RPC host address")
    p_collect.add_argument("--session", default="HOL", help="Session qualifier for theory name resolution")
    p_collect.add_argument("--driver", default="",
        help="Agent backend and model for semantic interpretation, as "
             "'<Driver>[.<model>]' (e.g. 'ClaudeCode', 'Codex.gpt-5.6-sol'); the "
             "model part is optional and defaults to that backend's own. Outranks "
             "the Isabelle config option Semantic_Embedding.interpretation_driver "
             "and the INTERPRETATION_DRIVER environment variable; unset means let "
             "those decide (default: ClaudeCode). REQUIRES the REPL server to have "
             "been started with RPC_Host set to this --rpc-addr: this setting is "
             "delivered in-process, and with RPC_Host unset Isabelle starts an RPC "
             "host of its own, which never sees it.")
    p_collect.add_argument("--embed-models", default="",
        help="Comma-separated canonical (HuggingFace) embedding model names "
             "(e.g., 'Qwen/Qwen3-Embedding-8B'). NOTE: all listed models are embedded "
             "via the one active driver+base_url, so they must be served by the same "
             "endpoint.")
    p_collect.add_argument("--reinterpret", action="store_true",
        help="Re-interpret already-finished theories to pick up new entities")
    p_collect.add_argument("--migrate-on-hash-change", action="store_true",
        help="Copy old data to new hash instead of re-interpreting when hash changes")
    p_collect.add_argument("--re-embed", action="store_true",
        help="Re-embed vectors for --embed-models (force, whole DB), not just the missing ones")
    p_collect.add_argument("--yes-embed", action="store_true",
        help="Proceed with the chained embed without confirmation (needed when stdin is not a "
             "TTY, e.g. in a fleet).")
    # Interpretation runs on Isabelle's future worker pool, so its DAG width is the REPL's own
    # `-o threads=N` (Multithreading.max_threads). Start the REPL with the width you want:
    #   ./repl_server.sh 127.0.0.1:6666 <SESSION> <outdir> -o threads=32

    # list
    p_list = sub.add_parser("list", help="List all theories in the semantic database")

    # remove
    p_remove = sub.add_parser("remove", help="Remove theories from the database")
    p_remove.add_argument("identifiers", nargs="+",
        help="Theory names or universal key hex prefixes (from 'list' output)")
    p_remove.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    # prune (CHECK_OUTDATE_PLAN §10)
    p_prune = sub.add_parser("prune",
        help="Remove OLD GENERATIONS of the named theories (dry run by default)")
    p_prune.add_argument("identifiers", nargs="*",
        help="Theory names (long, or unambiguous base names)")
    p_prune.add_argument("--all", action="store_true",
        help="Every theory that has prunable old generations")
    p_prune.add_argument("--keep", type=int, default=1, metavar="N",
        help="How many newest generations survive per theory (default 1)")
    p_prune.add_argument("--apply", action="store_true",
        help="Actually delete (the default is a dry run)")
    p_prune.add_argument("--yes", action="store_true",
        help="With --apply: skip the confirmation prompt")
    p_prune.add_argument("--no-backup", action="store_true",
        help="With --apply: skip the rolling semantics.lmdb backup")
    p_prune.add_argument("--current-from", choices=["store", "repl"],
        default="store",
        help="What decides the current generation: the registry's newest "
             "timestamp (store, default) or a live REPL session (repl)")
    p_prune.add_argument("--repl-addr", default=None,
        help="With --current-from repl: the Isa-REPL address")
    p_prune.add_argument("--session", default=None,
        help="With --current-from repl: the session name")

    # orphans (CHECK_OUTDATE_PLAN §10)
    p_orphans = sub.add_parser("orphans",
        help="Read-only report of records attributable to no known theory name")
    p_orphans.add_argument("--limit", type=int, default=50, metavar="N",
        help="How many orphans to list (default 50)")
    p_orphans.add_argument("--system", action="store_true",
        help="Report on the read-only system layer instead of the user layer")

    # reindex
    p_reindex = sub.add_parser("reindex",
        help="Rebuild experience_index.lmdb from the EXPERIENCE records in semantics.lmdb")

    # fsck
    p_fsck = sub.add_parser("fsck", help="Check semantics.lmdb invariants")
    p_fsck.add_argument("--fix", action="store_true",
        help="Repair the derived artefacts: rebuild the experience index, and re-key "
             "records whose XOR prefix disagrees with their constituent list.")
    p_fsck.add_argument("--system", action="store_true",
        help="Report on the read-only system DB instead of the user DB (no --fix).")

    # embed
    p_embed = sub.add_parser("embed",
        help="Embed every interpreted entity that lacks a vector for MODEL, over the whole "
             "database (offline; no Isabelle). Incremental.")
    p_embed.add_argument("models", nargs="+", metavar="MODEL",
        help="Canonical (HuggingFace) embedding model name(s), e.g. 'Qwen/Qwen3-Embedding-8B'. "
             "All are served by the one active driver+base_url.")
    p_embed.add_argument("--yes", action="store_true",
        help="Proceed without the confirmation prompt (required when stdin is not a TTY).")
    p_embed.add_argument("--force", action="store_true",
        help="Re-embed even entities that already have a vector for the model.")
    p_embed.add_argument("--kinds", default="",
        help="Comma-separated EntityKinds to restrict to (e.g. 'experience'); default all. "
             "Use '--kinds experience --force' for the §5 experience-vector migration "
             "(re-embed every experience under the single document-text convention).")
    p_embed.add_argument("--driver", default="",
        help="Override the embedding driver class (else env EMBEDDING_DRIVER / default).")
    p_embed.add_argument("--base-url", dest="base_url", default="",
        help="Override the embedding endpoint base_url, version segment included, "
             "e.g. https://api.openai.com/v1 (else env EMBEDDING_BASE_URL / default).")

    # status
    p_status = sub.add_parser("status",
        help="Show the system and user layers of the semantic database (offline)")

    # pull
    p_pull = sub.add_parser("pull",
        help="Install or update the read-only system DB from the conda channel "
             "into <cache>/system (manual, explicit; atomic swap)")
    p_pull.add_argument("--force", action="store_true",
        help="Install even when the installed snapshot already matches the channel.")

    # release
    p_release = sub.add_parser("release",
        help="Dispatch the CI release workflow (publishes the Hugging Face state "
             "as the isabelle-semantic-data conda package); soft freshness check first")

    # export
    p_export = sub.add_parser("export",
        help="Rewrite the store at SEMANTIC_DB_DIR into a publishable system-DB "
             "payload: tombstones dropped, experience index rebuilt, manifest "
             "stamped, gates run. Used by CI; offline.")
    p_export.add_argument("outdir", help="Output directory (must be empty or absent)")

    args = parser.parse_args()
    {"collect": cmd_collect, "list": cmd_list, "remove": cmd_remove,
     "prune": cmd_prune, "orphans": cmd_orphans,
     "reindex": cmd_reindex, "fsck": cmd_fsck, "embed": cmd_embed,
     "status": cmd_status, "pull": cmd_pull, "release": cmd_release,
     "export": cmd_export}[args.command](args)


if __name__ == "__main__":
    main()
