"""Inverted index: theory hash (16B) -> set of experience universal keys.

An AoA "experience memory" (a Record of kind EXPERIENCE; see semantics.py and
AoA/docs/EXPERIENCE_MEMORY.md) is available in a proof only when EVERY theory in
its minimal-antichain constituent list is loaded.  To find the available
experiences for a proof without scanning every experience, we keep this inverted
index: each 16-byte constituent theory hash maps to the set of experience keys
whose constituent list mentions it.

Availability is then: union the buckets of the loaded theories to get the
candidate experiences, and keep those whose FULL constituent set is loaded (the
subset check is done by the caller against the record's theory_constituents,
since a bucket only proves "mentions this ONE loaded theory").

This lives in its OWN LMDB (experience_index.lmdb), deliberately separate from
semantics.lmdb: whole-DB cursor scans over the semantic store (clean_wip,
isabelle_semantics list/remove, migration) must never encounter these buckets,
which are keyed by bare 16-byte theory hashes and hold non-Record payloads.

Concurrency: like _Semantic_DB, every write-txn body here runs to completion
without awaiting, so the single event loop cannot interleave two write txns.
Do not introduce an ``await`` inside a write transaction.
"""

import os
import threading
from collections.abc import Iterable
from typing import Any

import lmdb
import msgpack
from ._paths import semantic_DB_dir

from Isabelle_RPC_Host.universal_key import universal_key

type theory_hash = bytes

# Sentinel bucket for experiences with NO constituent theories — a "global"
# experience available in every context. Uses the all-zero 16-byte hash, matching
# xor_theory_prefix([]) = 0x00..00 (the key prefix such experiences already carry);
# a real xxhash128 theory hash colliding with all-zeros is astronomically improbable.
_GLOBAL: theory_hash = b'\x00' * 16


class _Experience_Index:
    """TWO-LAYER (plan §3.3): the writable user index below, plus -- when a
    system DB is installed -- the immutable system index shipped inside its
    payload (built by the CI export, always consistent with the system
    records).  Queries (``candidates``, ``all_keys``) union both, dedup by uk;
    every write (``add``/``remove``/``remove_scanning``/``rebuild``) touches
    the user index only.  There is no index-side deletion mechanism at all
    (L17): a tombstoned uk still listed by the system index dies when its
    record is read through the facade, which every consumer already checks."""
    _env: 'lmdb.Environment | None' = None
    # Like _Semantic_DB._system_env: probed once per process; _checked tells
    # "not probed yet" apart from "probed, absent".
    _system_env: 'lmdb.Environment | None' = None
    _system_env_checked: bool = False
    _lock = threading.Lock()

    def _ensure_env(self) -> 'lmdb.Environment':
        if self._env is None:
            with self._lock:
                if self._env is None:
                    import atexit
                    cache_dir = semantic_DB_dir()
                    os.makedirs(cache_dir, exist_ok=True)
                    _Experience_Index._env = lmdb.open(
                        os.path.join(cache_dir, "experience_index.lmdb"), map_size=1 << 27)
                    try:
                        # Reap dead readers at every open (attached RPC hosts die by
                        # os._exit by design).  See RPC_EPHEMERAL_HOST_PLAN.md, H0.
                        _Experience_Index._env.reader_check()
                    except lmdb.Error:
                        pass
                    atexit.register(_Experience_Index._close)
        return self._env  # type: ignore

    def _ensure_system_env(self) -> 'lmdb.Environment | None':
        """The system layer's ``experience_index.lmdb``, or None when no (valid)
        system DB is installed or it ships no index."""
        if not self._system_env_checked:
            with self._lock:
                if not _Experience_Index._system_env_checked:
                    from .snapshot_sync import validated_system_db
                    sysdb = validated_system_db()
                    if sysdb is not None:
                        path = os.path.join(sysdb.path, "experience_index.lmdb")
                        if os.path.isdir(path):
                            try:
                                import atexit
                                _Experience_Index._system_env = lmdb.open(
                                    path, readonly=True, lock=False)
                                atexit.register(_Experience_Index._close)
                            except lmdb.Error as e:
                                import sys
                                print(f"[Semantic_Embedding] WARNING: cannot open "
                                      f"the system experience index at {path}: {e}",
                                      file=sys.stderr, flush=True)
                    _Experience_Index._system_env_checked = True
        return self._system_env

    @staticmethod
    def _close() -> None:
        with _Experience_Index._lock:
            if _Experience_Index._env is not None:
                _Experience_Index._env.close()
                _Experience_Index._env = None
            if _Experience_Index._system_env is not None:
                _Experience_Index._system_env.close()
                _Experience_Index._system_env = None
            _Experience_Index._system_env_checked = False

    @staticmethod
    def _get_bucket(txn: Any, h: theory_hash) -> 'list[bytes]':
        raw = txn.get(h)
        if raw is None:
            return []
        return [bytes(x) for x in msgpack.unpackb(raw)]

    @staticmethod
    def _put_bucket(txn: Any, h: theory_hash, uks: 'list[bytes]') -> None:
        if uks:
            txn.put(h, msgpack.packb(uks))
        else:
            txn.delete(h)

    def add(self, uk: universal_key, constituent_hashes: 'list[theory_hash]') -> None:
        """Register ``uk`` under each of its constituent theory hashes (idempotent).

        An empty constituent list registers ``uk`` under the ``_GLOBAL`` sentinel
        bucket instead (a global experience), so it stays retrievable + dedup-visible
        rather than being orphaned (never added to any bucket)."""
        uk = bytes(uk)
        with self._ensure_env().begin(write=True) as txn:
            for h in (constituent_hashes or [_GLOBAL]):
                h = bytes(h)
                bucket = self._get_bucket(txn, h)
                if uk not in bucket:
                    bucket.append(uk)
                    self._put_bucket(txn, h, bucket)

    def remove(self, uk: universal_key, constituent_hashes: 'list[theory_hash]') -> None:
        """Remove ``uk`` from each of its constituent theory hashes' buckets (an empty
        list removes it from the ``_GLOBAL`` bucket — symmetric with ``add``)."""
        uk = bytes(uk)
        with self._ensure_env().begin(write=True) as txn:
            for h in (constituent_hashes or [_GLOBAL]):
                h = bytes(h)
                bucket = self._get_bucket(txn, h)
                if uk in bucket:
                    bucket.remove(uk)
                    self._put_bucket(txn, h, bucket)

    def remove_scanning(self, uk: universal_key) -> None:
        """Remove ``uk`` from every bucket, scanning the whole index.

        Fallback for when the constituent list is unknown (e.g. the record has
        already been deleted).  Prefer ``remove`` with the known constituents."""
        uk = bytes(uk)
        with self._ensure_env().begin(write=True) as txn:
            updates: list[tuple[bytes, list[bytes]]] = []
            for h, raw in txn.cursor():
                bucket = [bytes(x) for x in msgpack.unpackb(raw)]
                if uk in bucket:
                    bucket.remove(uk)
                    updates.append((bytes(h), bucket))
            for h, bucket in updates:
                self._put_bucket(txn, h, bucket)

    def rebuild(self, entries: 'Iterable[tuple[universal_key, list[theory_hash]]]',
                env: 'lmdb.Environment | None' = None) -> int:
        """Drop every bucket and rebuild the index from ``entries``.

        ``env`` overrides the target environment (default: the user index).
        The override serves ONE caller: snapshot_sync.export, which builds the
        system experience index of a payload over the exported records.

        This index is a pure derived view of the EXPERIENCE records in
        semantics.lmdb — an experience belongs in the bucket of each of its
        constituent theory hashes (``_GLOBAL`` when it has none), and nothing
        else is stored here — so a full rebuild is always correct, and is the
        only repair for drift.  Drift is reachable: an experience lives in three
        stores (semantics.lmdb, the vector store, this index) written in three
        separate transactions with no cross-store atomicity, so a crash between
        them leaves a record that no bucket mentions.  ``candidates`` would then
        never return it and the experience becomes silently unretrievable (and
        invisible to AoA's ``all_keys``-based dedup, which re-learns it).

        One write transaction: readers see either the whole old index or the
        whole new one.  Returns the number of experiences indexed.

        CONTRACT: ``entries`` must be a snapshot the caller keeps valid for the
        duration of this call — in practice, taken while holding the semantics
        write transaction (see Semantic_DB.rebuild_experience_index).  Rebuilding
        from a snapshot that another writer has already moved past would erase the
        buckets of whatever it added, which is the very drift this repairs."""
        # dict-keyed buckets: O(1) dedup, insertion order preserved (bucket
        # order is semantically irrelevant — every reader unions them).
        buckets: 'dict[bytes, dict[bytes, None]]' = {}
        n = 0
        for uk, constituent_hashes in entries:
            uk = bytes(uk)
            n += 1
            for h in (constituent_hashes or [_GLOBAL]):
                buckets.setdefault(bytes(h), {})[uk] = None
        with (env if env is not None else self._ensure_env()).begin(write=True) as txn:
            for h in [bytes(h) for h, _ in txn.cursor()]:
                txn.delete(h)
            for h, bucket in buckets.items():
                self._put_bucket(txn, h, list(bucket))
        return n

    def candidates(self, loaded_hashes: 'set[theory_hash]') -> 'set[bytes]':
        """Union of the buckets of the given (loaded) theory hashes.

        A superset of the truly-available experiences: an experience appears here
        as soon as ONE of its constituents is loaded; the caller must still filter
        to those whose FULL constituent set is loaded. The ``_GLOBAL`` bucket is
        always included (global experiences are available in every context; the
        caller's full-subset check passes them vacuously).

        Unions the user and system indexes (a ``set``, so dedup is free).  A
        stale system listing -- a tombstoned or user-modified experience -- is a
        false-positive candidate; it dies when the caller reads its record
        through the facade (L17)."""
        result: set[bytes] = set()
        with self._ensure_env().begin() as txn:
            for h in (loaded_hashes | {_GLOBAL}):
                raw = txn.get(bytes(h))
                if raw is not None:
                    result.update(bytes(x) for x in msgpack.unpackb(raw))
        senv = self._ensure_system_env()
        if senv is not None:
            with senv.begin() as txn:
                for h in (loaded_hashes | {_GLOBAL}):
                    raw = txn.get(bytes(h))
                    if raw is not None:
                        result.update(bytes(x) for x in msgpack.unpackb(raw))
        return result

    def all_keys(self, include_system: bool = True) -> 'set[bytes]':
        """Every experience key registered in the index (union of all buckets,
        user and system layers alike -- so cross-layer duplicate detection sees
        system-shipped experiences too).

        ``include_system=False`` restricts to the USER index -- for `fsck`,
        whose user-vs-index consistency comparison must scope both sides to the
        user layer (the system index is immutable and legitimately lists
        tombstoned or user-superseded uks, L17)."""
        result: set[bytes] = set()
        with self._ensure_env().begin() as txn:
            for _, raw in txn.cursor():
                result.update(bytes(x) for x in msgpack.unpackb(raw))
        senv = self._ensure_system_env() if include_system else None
        if senv is not None:
            with senv.begin() as txn:
                for _, raw in txn.cursor():
                    result.update(bytes(x) for x in msgpack.unpackb(raw))
        return result


Experience_Index = _Experience_Index()