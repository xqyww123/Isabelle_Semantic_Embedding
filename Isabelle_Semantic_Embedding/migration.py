"""Per-entity migration of persistent theories across Isabelle versions
(ai-artifacts/CROSS_VERSION_MIGRATION_PLAN.md).

The migration context is the state of one run with the switch on
(`collect --migrate-on-hash-change`, §3.1): opened by `Semantic_Store.begin_migration`
on a connection the run holds for its whole length, read by every `interpret_file`
whose payload carries its handle, and dropped when that connection closes.
"""

from __future__ import annotations

import asyncio
import enum
import itertools
import os
import time
from typing import Any, NamedTuple

import msgpack
from Isabelle_RPC_Host import Connection, isabelle_remote_procedure
from Isabelle_RPC_Host.theory_hash import is_persistent
from Isabelle_RPC_Host.universal_key import EntityKind, is_thm_rule_key

from . import theory_hash_registry
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
                 base_names: 'set[str]') -> None:
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

    async def predecessors(self) -> dict[bytes, bytes]:
        """The predecessor map (§3.4), built on first use -- a resume with nothing
        to do scans nothing -- in a worker thread, so the minutes-long scan does not
        stall the host's other work; concurrent first uses share the one build."""
        if self._predecessors is None:
            if self._building is None:
                self._building = asyncio.ensure_future(
                    asyncio.to_thread(predecessor_map, self.forward))
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

    async def migrate(self, entries: list[Entry],
                      rec_cache: 'dict[bytes, SemanticRecord | None]') -> Step:
        """One theory's migration step (§3.5-3.7), before the scan: every entry
        whose key reads absent in `rec_cache` and has a predecessor gets a copy
        -- written create-only in one transaction, its vector copied, in a live
        run; only into `rec_cache` in a dry run -- and `rec_cache` then holds
        what the store (or the dry run) holds."""
        absent = [e for e in entries if rec_cache[e.universal_key] is None]
        if not absent:
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
        epsilon = Semantic_DB.counter_snapshot()
        for e in absent:
            uk, kind = e.universal_key, EntityKind(e.kind)
            k_old = old_keys[uk]
            p = preds.get(k_old) if k_old is not None else None
            if (p is None or p.interpretation is None
                    or (kind in TRACKED_KINDS and p.semantic_digest is None)):
                reasons[uk] = Reason.NO_PREDECESSOR
                continue
            if kind in _STATEMENT_KINDS and not (
                    e.prop_str == p.expr or (not e.prop_str and not p.expr)):
                reasons[uk] = Reason.DEFINITION_CHANGED
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

        def unchanged(d: bytes, p: SemanticRecord) -> bool:
            r = rec_at(d)
            if r is _FIRST_WRITE:
                return False
            if p.version is not None:      # clause 1, or clause 3 at Y = X
                x = next((x for x in p.deps or [] if x[16:] == d[16:]), None)
                if r is not None:
                    return (x is not None and (d == x or r.migrated_from == x)
                            and (r.version or 0) <= (p.interpreted_at or 0))
                y = x
            else:                          # clause 2, or clause 3 at Y = inverse
                if r is not None:
                    m = rec_at(r.migrated_from) if r.migrated_from is not None else None
                    return m is not None and m is not _FIRST_WRITE and m.version is None
                old = self.inverse.get(d[:16])
                y = None if old is None else old + d[16:]
            return (d not in first_written and y is not None
                    and rec_at(y) is None and self.generation_kept(y[:16]))

        eligible: list[Entry] = []
        for e in absent:
            uk = e.universal_key
            c = copies.get(uk)
            if c is None or c.version is None:     # no copy, or a method / collection
                continue
            p = sources[uk]
            if EntityKind(e.kind) in TRACKED_KINDS and p.semantic_digest != e.semantic_digest:
                reasons[uk] = Reason.DEFINITION_CHANGED
            elif ((p.version is not None and p.interpreted_at is None)     # P2 mark
                  or not all(unchanged(d, p) for d in e.deps or [])):
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
            for uk, (rec, _) in written.items():
                rec_cache[uk] = rec
            copy_vectors([
                (c.migrated_from, uk) for uk, (c, created) in written.items()
                if created and c.migrated_from is not None
                and entity_document_text(c) == entity_document_text(sources[uk])])
        return Step(reasons, frozenset(copies))

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
        replaced, in four phases -- (1) the record, create-only, with
        `migrated_from` = the old key; (2) its vector; (3) the new key into the
        index; (4) LAST the old key out of its buckets.  The buckets are the
        done-marker and every phase is idempotent, so an interrupted move is
        completed by the next run.  The old record and its vector stay.  Returns
        (moved, already moved)."""
        from .experience_index import Experience_Index
        listed = self.listed_experiences()
        # new key -> (old key, its constituent hashes, the new record)
        moves: dict[bytes, tuple[bytes, list[bytes], SemanticRecord]] = {}
        gone: list[bytes] = []          # listed, but the record is absent: phase (4) only
        for old_key, rec in zip(listed, Semantic_DB.get_many(listed)):
            if rec is None:
                gone.append(old_key)
                continue
            moved = Semantic_DB._moved_constituents(rec.theory_constituents or [], self.forward)
            if moved is None:           # a stale listing; `rebuild_experience_index` repairs it
                continue
            consts, prefix = moved
            moves[prefix + old_key[16:]] = (
                old_key, [h for _, h in rec.theory_constituents or []],
                rec._replace(theory_constituents=consts, migrated_from=old_key))
        written = Semantic_DB.create_records({k: r for k, (_, _, r) in moves.items()})
        copy_vectors([(old_key, k) for k, (old_key, _, _) in moves.items()])
        for k, (_, _, r) in moves.items():
            Experience_Index.add(k, [h for _, h in r.theory_constituents or []])
        for old_key, old_hashes, _ in moves.values():
            Experience_Index.remove(old_key, old_hashes)
        for old_key in gone:
            Experience_Index.remove_scanning(old_key)
        created = sum(1 for _, c in written.values() if c)
        return created, len(written) - created

    def summary(self, log_dir: str) -> list[str]:
        """What `end_migration` returns for ML to print (§3.9): one line per kind,
        then the experiences -- moved in a live run (§3.8), counted in a dry run,
        which also writes the forward map as a TSV into `log_dir` (§3.1)."""
        lines = [f"{kind.label}: {n} entities; predecessor found {p}; copied {c}; "
                 f"to interpret {s}"
                 for kind, (n, p, c, s) in sorted(self._kinds.items())]
        if not self.dry_run:
            moved, already = self.move_experiences()
            return lines + [f"Experiences: {moved} moved to the new generation, "
                            f"{already} were already moved."]
        path = os.path.join(log_dir, time.strftime("forward_map-%Y%m%d-%H%M%S.tsv",
                                                   time.gmtime()))
        with open(path, "w", encoding="utf-8") as f:
            for name, h in self.theories:
                old = self.inverse.get(h)
                f.write(f"{name}\t{h.hex()}\t{old.hex() if old else ''}\n")
        return lines + [f"Experiences: {len(self.listed_experiences())} still listed "
                        "under an old hash.", f"Forward map written to {path}."]


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
                           set(await excluded_theory_names(connection)))
    handle = next(_handles)
    _contexts[handle] = ctx

    def drop() -> None:
        _contexts.pop(handle, None)

    connection.on_close.append(drop)
    return handle


@isabelle_remote_procedure("Semantic_Store.end_migration")
async def _end_migration(arg: Any, connection: Connection) -> list[str]:
    ctx = migration_context(arg)
    assert ctx is not None
    return ctx.summary(_host_log_dir(connection))


def _host_log_dir(connection: Connection) -> str:
    """The directory of the host's log file (§3.1: the dry run's TSV goes beside
    it); the semantic DB directory when the host logs to no file."""
    import logging
    from ._paths import semantic_DB_dir
    for h in connection.server.logger.handlers:
        if isinstance(h, logging.FileHandler):
            return os.path.dirname(h.baseFilename)
    return semantic_DB_dir()
