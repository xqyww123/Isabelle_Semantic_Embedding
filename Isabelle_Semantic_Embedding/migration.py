"""Per-entity migration of persistent theories across Isabelle versions
(ai-artifacts/CROSS_VERSION_MIGRATION_PLAN.md).

The migration context is the state of one run with the switch on
(`collect --migrate-on-hash-change`, §3.1): opened by `Semantic_Store.begin_migration`
on a connection the run holds for its whole length, read by every `interpret_file`
whose payload carries its handle, and dropped when that connection closes.  It
writes the run's event log (§3.12).
"""

from __future__ import annotations

import asyncio
import datetime
import enum
import hashlib
import itertools
import json
import logging
import os
import pathlib
import socket
import subprocess
import sys
import time
from collections.abc import Iterable
from typing import Any, NamedTuple

import msgpack
from Isabelle_RPC_Host import Connection, isabelle_remote_procedure
from Isabelle_RPC_Host.theory_hash import is_persistent
from Isabelle_RPC_Host.universal_key import EntityKind, is_thm_rule_key

from . import theory_hash_registry
from ._paths import semantic_DB_dir
from .document_text import entity_document_text
from .semantic_embedding import copy_vectors
from .semantic_interpretation import Entry, _EffStar, _statement
from .semantics import (
    Semantic_DB, SemanticRecord, excluded_theory_names, is_tombstone, unpack_thy_status)

# The kinds the semantic change gate tracks (gate plan §0); every dependency
# target is one of them.
TRACKED_KINDS = frozenset(
    {EntityKind.CONSTANT, EntityKind.TYPE, EntityKind.CLASS, EntityKind.LOCALE})
# Copied only with an unchanged statement, and with no gate fields (§3.5, §3.7).
_STATEMENT_KINDS = frozenset({EntityKind.METHOD, EntityKind.THEOREM_COLLECTION})


class Reason(enum.Enum):
    """What the migration step decided for an entry whose new key read absent."""
    NO_PREDECESSOR = "no predecessor"
    DEFINITION_CHANGED = "definition changed"
    DEPENDENCY_CHANGED = "dependency changed"
    UNCHANGED = "unchanged"


class Step(NamedTuple):
    """One theory's migration step: the decision per entry whose key read absent,
    and which of them got a copy."""
    reasons: dict[bytes, Reason]
    copied: frozenset[bytes]


_NO_STEP = Step({}, frozenset())

# A dry run's recorded pass-1 outcome of an entry that will be first-written (§3.6).
_FIRST_WRITE = object()


# --- the event log (§3.12) ---

def _json_value(o: Any) -> Any:
    """What `json.dumps` writes for the values it does not know: bytes as hex."""
    if isinstance(o, (bytes, bytearray, memoryview)):
        return bytes(o).hex()
    raise TypeError(f"no JSON form for {type(o).__name__}")


class EventLog:
    """A run's event log (§3.12): `<semantic DB dir>/migration_stats/<run>.jsonl`,
    one JSON object per line, each batch appended and closed at once, so a crash
    leaves every line before it whole.  Every object has `t` (UTC, ms), `run`
    and `ev`."""

    def __init__(self, run: str) -> None:
        self.run = run
        directory = os.path.join(semantic_DB_dir(), "migration_stats")
        os.makedirs(directory, exist_ok=True)
        self.path = os.path.join(directory, run + ".jsonl")

    def write(self, ev: str, rows: Iterable[dict[str, Any]]) -> None:
        t = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
        head = {"t": t.replace("+00:00", "Z"), "run": self.run, "ev": ev}
        # ASCII escapes: a lone surrogate in a judge's text cannot break the write.
        lines = [json.dumps({**head, **row}, default=_json_value) + "\n" for row in rows]
        if lines:
            with open(self.path, "a", encoding="ascii") as f:
                f.writelines(lines)

    def event(self, ev: str, **fields: Any) -> None:
        self.write(ev, [fields])


def _provenance() -> dict[str, Any]:
    """Which code runs (§3.12): the package's checkout, its git commit and the
    tracked files that differ from it (both null outside a git checkout), and the
    SHA-1 of Tools/semantic_digest.ML (null where the package ships without it)."""
    checkout = pathlib.Path(__file__).resolve().parent.parent

    def git(*args: str) -> 'str | None':
        if not (checkout / ".git").exists():     # an install inside some other repository
            return None
        try:
            p = subprocess.run(["git", "-C", str(checkout), *args],
                               capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return p.stdout if p.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=no")
    ml = checkout / "Tools" / "semantic_digest.ML"
    return {"checkout": str(checkout),
            "git_commit": commit.strip() if commit is not None else None,
            "git_changed": status.splitlines() if status is not None else None,
            "semantic_digest_ml_sha1":
                hashlib.sha1(ml.read_bytes()).hexdigest() if ml.is_file() else None}


def _tombstoned(key: bytes) -> bool:
    """The user layer holds a tombstone at `key`."""
    with Semantic_DB._ensure_env().begin() as txn:
        raw = txn.get(key)
    return raw is not None and is_tombstone(raw)


def _finished(txn: Any, h: bytes) -> bool:
    """The user layer's theory-status record of `h` says finished; a tombstone does
    not."""
    raw = txn.get(h)
    return bool(raw) and unpack_thy_status(bytes(raw)).get(b"finished", False)


def old_hashes(current: dict[str, bytes]) -> dict[str, bytes]:
    """A3 (§3.3), for every long name of `current` (name -> current hash): among the
    registry's other hashes of that name, the most recently seen one whose theory
    status is finished, else the most recently seen persistent one; a name with
    neither is absent.  One pass over the registry."""
    seen: dict[str, list[tuple[int, bytes]]] = {name: [] for name in current}
    for h, raw in theory_hash_registry.iter_items():
        name, ts = theory_hash_registry.decode_entry(raw)
        candidates = seen.get(name)
        if candidates is not None and h != current[name]:
            candidates.append((ts, h))
    picks: dict[str, bytes] = {}
    with Semantic_DB._ensure_env().begin() as txn:
        for name, candidates in seen.items():
            candidates.sort(reverse=True)
            pick = (next((h for _, h in candidates if _finished(txn, h)), None)
                    or next((h for _, h in candidates if is_persistent(h)), None))
            if pick is not None:
                picks[name] = pick
    return picks


def predecessor_map(forward: dict[bytes, bytes]) -> dict[bytes, bytes]:
    """New key -> old key of the theorem-alike records of the user layer whose
    constituents meet `forward`'s domain, every mapped hash replaced at once (§3.4).
    Two old records with one new key: the one with fewer rewritten constituents
    stays, then the smaller old key."""
    def rewrite(raw: bytes) -> 'tuple[int, bytes] | None':
        vals = msgpack.unpackb(raw)
        if len(vals) <= 5 or not vals[5]:
            return None
        consts = [(n, bytes(h)) for n, h in vals[5]]
        moved = Semantic_DB._moved_constituents(consts, forward)
        if moved is None:
            return None
        return sum(h in forward for _, h in consts), moved[1]

    found: dict[bytes, bytes] = {}
    with Semantic_DB._ensure_env().begin() as txn:
        for key, raw in txn.cursor():
            # A WIP key has a WIP constituent, so no persistent entry asks for it.
            if not is_thm_rule_key(key) or not is_persistent(key[:16]) or is_tombstone(raw):
                continue
            moved = rewrite(bytes(raw))
            if moved is None:
                continue
            n, prefix = moved
            key, new_key = bytes(key), prefix + key[16:]
            kept = found.get(new_key)
            if kept is not None:    # rare: recount the kept record rather than store counts
                kept_n = rewrite(bytes(txn.get(kept)))[0]  # type: ignore[index]
                if (kept_n, kept) <= (n, key):
                    continue
            found[new_key] = key
    return found


class MigrationContext:
    """One run's migration state (§3.1)."""

    def __init__(self, dry_run: bool, theories: list[tuple[str, bytes]],
                 base_names: 'set[str]', host_log: 'str | None') -> None:
        self.handle = next(_handles)
        self._started = time.monotonic()
        # A dry run writes nothing (A12): its copies stay in memory (§3.9).
        self.dry_run = dry_run
        # (long name, current hash) of the cone and the base theories, as ML sent them.
        self.theories = theories
        # The long names of the base theories (`excluded_theory_names`), which
        # never have records (§3.6 clause 3).
        self.base_names = base_names
        self._generation_kept: dict[bytes, bool] = {}
        # A dry run's pass-1 outcome per tracked entry whose new key read absent:
        # its in-memory copy, or _FIRST_WRITE (§3.6).
        self._dry_outcomes: dict[bytes, Any] = {}
        # Per kind: entities, predecessor found, copied, to interpret (§3.9).
        self._kinds: dict[EntityKind, list[int]] = {}
        # The forward map, old hash -> current hash, over the persistent current
        # hashes (§3.4): A3 is evaluated here, once per run; every later lookup
        # reads this map or its inverse.
        current = {name: h for name, h in theories if is_persistent(h)}
        self.forward: dict[bytes, bytes] = {
            old: current[name] for name, old in old_hashes(current).items()}
        self.inverse: dict[bytes, bytes] = {new: old for old, new in self.forward.items()}
        self._predecessors: 'dict[bytes, bytes] | None' = None
        self._building: 'asyncio.Future[dict[bytes, bytes]] | None' = None
        mode = "dry" if dry_run else "live"
        self.log = EventLog(time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                            + f"-{mode}-{os.getpid()}-{self.handle}")
        self.log.event(
            "run_start", mode=mode, host=socket.gethostname(), pid=os.getpid(),
            argv=sys.argv, python=sys.version, db_dir=semantic_DB_dir(), host_log=host_log,
            counter=Semantic_DB.counter_snapshot(), **_provenance(),
            theories=[(name, h, self.inverse.get(h)) for name, h in theories],
            base_names=sorted(base_names))

    async def predecessors(self) -> dict[bytes, bytes]:
        """The predecessor map (§3.4), built on first use -- a resume with nothing
        to do scans nothing -- in a worker thread, so the minutes-long scan does not
        stall the host's other work; concurrent first uses share the one build."""
        async def build() -> dict[bytes, bytes]:
            t0 = time.monotonic()
            found = await asyncio.to_thread(predecessor_map, self.forward)
            self.log.event("predecessor_map", size=len(found),
                           seconds=round(time.monotonic() - t0, 3))
            return found

        if self._predecessors is None:
            if self._building is None:
                self._building = asyncio.ensure_future(build())
            self._predecessors = await self._building
        return self._predecessors

    async def old_key(self, key: bytes) -> 'bytes | None':
        """The key of the predecessor record of the entry under `key` (§3.4)."""
        if is_thm_rule_key(key):
            return (await self.predecessors()).get(key)
        old = self.inverse.get(key[:16])
        return None if old is None else old + key[16:]

    def generation_kept(self, h: bytes) -> bool:
        """§3.6 clause 3: the generation `h` was not pruned -- `h` names a base
        theory in the registry, or its theory-status record exists.  Memoised."""
        kept = self._generation_kept.get(h)
        if kept is None:
            raw = theory_hash_registry._get_raw(h)
            kept = ((raw is not None
                     and theory_hash_registry.decode_entry(raw)[0] in self.base_names)
                    or Semantic_DB._get_raw(h) is not None)
            self._generation_kept[h] = kept
        return kept

    async def migrate(self, theory: str, entries: list[Entry],
                      rec_cache: 'dict[bytes, SemanticRecord | None]') -> Step:
        """One theory's migration step (§3.5-3.7), before the scan: every entry
        whose key reads absent in `rec_cache` and has a predecessor gets a copy
        -- written create-only in one transaction, its vector copied, in a live
        run; only into `rec_cache` in a dry run -- and `rec_cache` then holds
        what the store (or the dry run) holds.  Every entry gets an `entry` event
        (§3.12)."""
        absent = [e for e in entries if rec_cache[e.universal_key] is None]
        if not absent:
            self._log_entries(theory, entries, {})
            return _NO_STEP
        old_keys = {e.universal_key: await self.old_key(e.universal_key) for e in absent}
        # No await below: the reads and the one write transaction run without
        # another task of the host in between.
        wanted = [k for k in old_keys.values() if k is not None]
        preds = dict(zip(wanted, Semantic_DB.get_many(wanted)))

        # Pass 1: which entries get a copy.
        reasons: dict[bytes, Reason] = {}
        copies: dict[bytes, SemanticRecord] = {}
        sources: dict[bytes, SemanticRecord] = {}
        # What the `entry` event says of each absent entry, beyond its identity.
        trace: dict[bytes, dict[str, Any]] = {}
        epsilon = Semantic_DB.counter_snapshot()
        for e in absent:
            uk, kind = e.universal_key, EntityKind(e.kind)
            k_old = old_keys[uk]
            p = preds.get(k_old) if k_old is not None else None
            t = trace[uk] = {"old_key": k_old, "predecessor": "found",
                             "old_digest": p.semantic_digest if p else None,
                             "new_digest": e.semantic_digest, "p2": None, "deps": None,
                             "created": None, "same_document_text": None,
                             "vector_stores": None}
            if k_old is None:
                t["predecessor"] = "no old key"
            elif p is None:
                t["predecessor"] = "tombstone" if _tombstoned(k_old) else "no record"
            elif p.interpretation is None:
                t["predecessor"] = "no interpretation"
            elif kind in TRACKED_KINDS and p.semantic_digest is None:
                t["predecessor"] = "no digest"
            elif kind in _STATEMENT_KINDS and not (
                    e.prop_str == p.expr or (not e.prop_str and not p.expr)):
                t["predecessor"] = "statement changed"
                reasons[uk] = Reason.DEFINITION_CHANGED
                continue
            if p is None or t["predecessor"] != "found":
                reasons[uk] = Reason.NO_PREDECESSOR
                continue
            assert k_old is not None
            gated = kind not in _STATEMENT_KINDS
            sources[uk] = p
            copies[uk] = SemanticRecord(
                kind, e.name, _statement(e, p), p.interpretation,
                locale_provenance=e.locale_provenance,
                theory_constituents=e.theory_constituents,
                position=e.position, from_collection=e.from_collection,
                semantic_digest=p.semantic_digest if kind in TRACKED_KINDS else None,
                baseline_interpretation=(p.baseline_interpretation or p.interpretation
                                         if kind in TRACKED_KINDS else None),
                deps=list(e.deps or []) if gated else None,
                version=(p.version or epsilon) if gated else None,
                migrated_from=k_old)
            reasons[uk] = Reason.UNCHANGED

        # Pass 2: the dependency check, then interpreted_at.
        first_written = {e.universal_key for e in absent} - copies.keys()

        def rec_at(k: bytes) -> Any:
            """The record at `k`: this theory's copy, else the store (through
            rec_cache), else -- in a dry run -- an ancestor's recorded outcome."""
            if k in copies:
                return copies[k]
            if k not in rec_cache:
                rec_cache[k] = Semantic_DB[k]
            r = rec_cache[k]
            if r is None and k in self._dry_outcomes:
                o = self._dry_outcomes[k]
                if o is not _FIRST_WRITE:
                    rec_cache[k] = o
                return o
            return r

        def check(d: bytes, p: SemanticRecord) -> tuple[str, 'bytes | None', bool]:
            """The dependency check of `d` against `p` (§3.6): the clause that
            decides, the key it reads beside `d` (X, M or Y), and the result."""
            r = rec_at(d)
            if r is _FIRST_WRITE:
                return "first write", None, False
            if p.version is not None:      # clause 1, or clause 3 at Y = X
                x = next((x for x in p.deps or [] if x[16:] == d[16:]), None)
                if r is not None:
                    return "1", x, (x is not None and (d == x or r.migrated_from == x)
                                    and (r.version or 0) <= (p.interpreted_at or 0))
                y = x
            else:                          # clause 2, or clause 3 at Y = inverse
                if r is not None:
                    m = rec_at(r.migrated_from) if r.migrated_from is not None else None
                    return "2", r.migrated_from, (m is not None and m is not _FIRST_WRITE
                                                  and m.version is None)
                old = self.inverse.get(d[:16])
                y = None if old is None else old + d[16:]
            return "3", y, (d not in first_written and y is not None
                            and rec_at(y) is None and self.generation_kept(y[:16]))

        def checked(e: Entry, p: SemanticRecord) -> list[dict[str, Any]]:
            """The checks of `e`'s dependencies against `p`, in order, up to and
            including the first that finds a change."""
            checks: list[dict[str, Any]] = []
            for d in e.deps or []:
                clause, via, ok = check(d, p)
                checks.append({"key": d, "clause": clause, "via": via, "result": ok})
                if not ok:
                    break
            return checks

        eligible: list[Entry] = []
        for e in absent:
            uk = e.universal_key
            c = copies.get(uk)
            if c is None or c.version is None:     # no copy, or a method / collection
                continue
            p, t = sources[uk], trace[uk]
            t["p2"] = p.version is not None and p.interpreted_at is None     # P2 mark
            if EntityKind(e.kind) in TRACKED_KINDS and p.semantic_digest != e.semantic_digest:
                reasons[uk] = Reason.DEFINITION_CHANGED
                continue
            if not t["p2"]:
                t["deps"] = checked(e, p)
            if t["p2"] or not all(c["result"] for c in t["deps"]):
                reasons[uk] = Reason.DEPENDENCY_CHANGED
            else:
                eligible.append(e)
        # One evaluation over the store and this batch, as the scan does (§3.7).
        eff = _EffStar({**rec_cache, **copies})
        for e in eligible:
            c = copies[e.universal_key]
            copies[e.universal_key] = c._replace(
                interpreted_at=eff.eff_value(c.version, e.deps))  # type: ignore[arg-type]

        if self.dry_run:
            rec_cache.update(copies)
            for e in absent:
                if EntityKind(e.kind) in TRACKED_KINDS:
                    self._dry_outcomes[e.universal_key] = copies.get(
                        e.universal_key, _FIRST_WRITE)
        elif copies:
            written = Semantic_DB.create_records(copies)
            for uk, (rec, created) in written.items():
                rec_cache[uk] = rec
                trace[uk]["created"] = created
                if created:
                    trace[uk]["same_document_text"] = (
                        entity_document_text(rec) == entity_document_text(sources[uk]))
            vectors = copy_vectors([(k_old, uk) for uk, k_old in old_keys.items()
                                    if k_old is not None and trace[uk]["same_document_text"]])
            for uk, stores in vectors.items():
                trace[uk]["vector_stores"] = stores
        for uk, t in trace.items():
            r = rec_cache[uk] if uk in copies else None
            t.update(reason=reasons[uk].value, copied=uk in copies,
                     version=r.version if r else None,
                     interpreted_at=r.interpreted_at if r else None)
        self._log_entries(theory, entries, trace)
        return Step(reasons, frozenset(copies))

    def _log_entries(self, theory: str, entries: list[Entry],
                     trace: dict[bytes, dict[str, Any]]) -> None:
        """One `entry` event per entry of a migrating theory (§3.12); `trace` has
        the absent ones."""
        self.log.write("entry", (
            {"theory": theory, "key": e.universal_key, "kind": EntityKind(e.kind).name,
             "name": e.name, "absent": e.universal_key in trace,
             **trace.get(e.universal_key, {})}
            for e in entries))

    def count(self, entries: list[Entry], step: Step, seeds: list[int]) -> str:
        """Add one theory's numbers to the per-kind summary and return its dry-run
        line (§3.9, §9) after the theory's name: every seed counted under its
        step's reason, a seed the step did not decide as stale."""
        by_reason = dict.fromkeys(Reason, 0)
        for i in seeds:
            by_reason[step.reasons.get(entries[i].universal_key, Reason.UNCHANGED)] += 1
        seeded = {entries[i].universal_key for i in seeds}
        for e in entries:
            uk = e.universal_key
            n = self._kinds.setdefault(EntityKind(e.kind), [0, 0, 0, 0])
            n[0] += 1
            n[1] += uk in step.reasons and step.reasons[uk] is not Reason.NO_PREDECESSOR
            n[2] += uk in step.copied
            n[3] += uk in seeded
        return (f"{len(entries)} entities; copied {len(step.copied)}; to interpret "
                f"{len(seeds)} (no predecessor {by_reason[Reason.NO_PREDECESSOR]}, "
                f"definition changed {by_reason[Reason.DEFINITION_CHANGED]}, "
                f"dependency changed {by_reason[Reason.DEPENDENCY_CHANGED]}, "
                f"stale {by_reason[Reason.UNCHANGED]})")

    def listed_experiences(self) -> list[bytes]:
        """The experiences still listed in a USER-index bucket of an old hash: what
        the move (below) has left to do.  A WIP-prefixed key has a WIP
        constituent, which no move replaces: no experience ever takes a WIP key
        (§3.4)."""
        from .experience_index import Experience_Index
        return list(dict.fromkeys(
            k for h in self.forward for k in Experience_Index.user_bucket(h)
            if is_persistent(k[:16])))

    def move_experiences(self) -> tuple[int, int]:
        """§3.8 (A8): every experience listed in a USER-index bucket of an old hash
        gets one copy under the key its constituents give once every mapped hash is
        replaced, in three phases -- (1) the record, create-only, with
        `migrated_from` = the old key; (2) its vector; (3) in one index
        transaction, the new key in and the old key out.  The buckets are the
        done-marker and every phase is idempotent, so an interrupted move is
        completed by the next run.  The old record and its vector stay.  Every
        listed experience gets an `experience` event (§3.12).  Returns (moved,
        already moved)."""
        from .experience_index import Experience_Index
        listed = self.listed_experiences()
        # new key -> (old key, its constituent hashes, the new record)
        moves: dict[bytes, tuple[bytes, list[bytes], SemanticRecord]] = {}
        gone: list[bytes] = []          # listed, but the record is absent: it only leaves
        rows: list[dict[str, Any]] = []
        for old_key, rec in zip(listed, Semantic_DB.get_many(listed)):
            if rec is None:
                gone.append(old_key)
                continue
            moved = Semantic_DB._moved_constituents(rec.theory_constituents or [], self.forward)
            if moved is None:           # a stale listing; `rebuild_experience_index` repairs it
                rows.append({"old_key": old_key, "new_key": None, "outcome": "stale listing",
                             "vector_stores": None})
                continue
            consts, prefix = moved
            moves[prefix + old_key[16:]] = (
                old_key, [h for _, h in rec.theory_constituents or []],
                rec._replace(theory_constituents=consts, migrated_from=old_key))
        written = Semantic_DB.create_records({k: r for k, (_, _, r) in moves.items()})
        vectors = copy_vectors([(old_key, k) for k, (old_key, _, _) in moves.items()])
        for k, (old_key, old_hashes, r) in moves.items():
            Experience_Index.move(old_key, old_hashes, k,
                                  [h for _, h in r.theory_constituents or []])
            rows.append({"old_key": old_key, "new_key": k,
                         "outcome": "moved" if written[k][1] else "already moved",
                         "vector_stores": vectors[k]})
        for old_key in gone:
            Experience_Index.remove_scanning(old_key)
            rows.append({"old_key": old_key, "new_key": None, "outcome": "gone",
                         "vector_stores": None})
        self.log.write("experience", rows)
        created = sum(1 for _, c in written.values() if c)
        return created, len(written) - created

    def summary(self, log_dir: str) -> list[str]:
        """What `end_migration` returns for ML to print (§3.9): one line per kind,
        then the experiences -- moved in a live run (§3.8), counted in a dry run,
        which also writes the forward map as a TSV into `log_dir` (§3.1).  Ends
        the event log with `run_end` (§3.12)."""
        lines = [f"{kind.label}: {n} entities; predecessor found {p}; copied {c}; "
                 f"to interpret {s}"
                 for kind, (n, p, c, s) in sorted(self._kinds.items())]
        end: dict[str, Any] = {"kinds": {
            kind.name: dict(zip(("entities", "predecessor_found", "copied", "to_interpret"), n))
            for kind, n in sorted(self._kinds.items())}}
        if not self.dry_run:
            moved, already = self.move_experiences()
            end.update(experiences_moved=moved, experiences_already_moved=already)
            lines.append(f"Experiences: {moved} moved to the new generation, "
                         f"{already} were already moved.")
        else:
            path = os.path.join(log_dir, time.strftime("forward_map-%Y%m%d-%H%M%S.tsv",
                                                       time.gmtime()))
            with open(path, "w", encoding="utf-8") as f:
                for name, h in self.theories:
                    old = self.inverse.get(h)
                    f.write(f"{name}\t{h.hex()}\t{old.hex() if old else ''}\n")
            listed = len(self.listed_experiences())
            end.update(experiences_listed=listed, forward_map=path)
            lines += [f"Experiences: {listed} still listed under an old hash.",
                      f"Forward map written to {path}."]
        self.log.event("run_end", **end, counter=Semantic_DB.counter_snapshot(),
                       seconds=round(time.monotonic() - self._started, 3))
        return lines


# Live contexts by handle.  A handle is never reused within the host process.
_contexts: dict[int, MigrationContext] = {}
_handles = itertools.count(1)


def migration_context(handle: int | None) -> MigrationContext | None:
    """The live context behind a payload's handle; None for no handle (the switch is
    off, or the theory is WIP)."""
    if handle is None:
        return None
    try:
        return _contexts[handle]
    except KeyError:
        raise RuntimeError(f"no migration context {handle}: the connection of the run "
                           "that opened it has closed") from None


@isabelle_remote_procedure("Semantic_Store.begin_migration")
async def _begin_migration(arg: Any, connection: Connection) -> int:
    """Open a run's migration context, owned by `connection`: it goes when the
    connection closes, as the interpretation lock's `RunState` does."""
    dry_run, theories = arg
    ctx = MigrationContext(bool(dry_run), [(name, bytes(h)) for name, h in theories],
                           set(await excluded_theory_names(connection)),
                           _host_log_file(connection))
    _contexts[ctx.handle] = ctx

    def drop() -> None:
        _contexts.pop(ctx.handle, None)

    connection.on_close.append(drop)
    return ctx.handle


@isabelle_remote_procedure("Semantic_Store.end_migration")
async def _end_migration(arg: Any, connection: Connection) -> list[str]:
    ctx = migration_context(arg)
    assert ctx is not None
    return ctx.summary(_host_log_dir(connection))


def _host_log_file(connection: Connection) -> 'str | None':
    """The host's log file, None when it logs to no file.  The handler is looked
    up the way a record propagates: `mk_logger_` puts it on the root."""
    lg: 'logging.Logger | None' = connection.server.logger
    while lg is not None:
        for h in lg.handlers:
            if isinstance(h, logging.FileHandler):
                return h.baseFilename
        lg = lg.parent if lg.propagate else None
    return None


def _host_log_dir(connection: Connection) -> str:
    """The directory of the host's log file (§3.1: the dry run's TSV goes beside
    it); the semantic DB directory when the host logs to no file."""
    path = _host_log_file(connection)
    return os.path.dirname(path) if path is not None else semantic_DB_dir()
