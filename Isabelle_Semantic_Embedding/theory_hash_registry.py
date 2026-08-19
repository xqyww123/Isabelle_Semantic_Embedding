"""The layered read of the theory-hash registry (THEORY_HASH_REGISTRY_PLAN.md §8).

The registry, `theory_hash.lmdb`, maps a 16-byte theory hash to msgpack
``[theory long name, last-seen unix seconds]``. Its user layer — the writable
store inside `semantic_DB_dir()` — belongs to the lower package:
`Isabelle_RPC_Host.theory_hash` opens it (`open_theory_hash_store`) and owns
the only write path, a blind ``put``. This module adds the half the lower
package must not know about (plan §8.1): the read-only system layer a data
package installs, reachable only through `snapshot_sync.validated_system_db`.

The reading rule is the layered DB's one rule (plan §8): a point read consults
the user layer first, where a tombstone (``b""``, `semantics.TOMBSTONE`)
answers "absent" and stops the fall-through, then the system layer; a scan is
the union of both layers with the user layer winning per key, and a user-layer
tombstone removing the key from the result entirely.
"""

import os
import threading
from collections.abc import Iterator

import lmdb
import msgpack
from Isabelle_RPC_Host.theory_hash import open_theory_hash_store

_lock = threading.Lock()
_system_env: 'lmdb.Environment | None' = None
_system_env_checked = False


def _ensure_system_env() -> 'lmdb.Environment | None':
    """The system layer's ``theory_hash.lmdb``, or None when no (valid) system DB
    is installed — or the installed one predates the registry and simply has no
    such store.  ``readonly=True, lock=False``: the store is immutable for its
    whole installed life (updates replace the directory wholesale), so no reader
    table and no writer coordination exist for it."""
    global _system_env, _system_env_checked
    if not _system_env_checked:
        with _lock:
            if not _system_env_checked:
                from .snapshot_sync import validated_system_db
                sysdb = validated_system_db()
                if sysdb is not None:
                    path = os.path.join(sysdb.path, "theory_hash.lmdb")
                    if os.path.exists(path):
                        try:
                            import atexit
                            _system_env = lmdb.open(path, readonly=True, lock=False)
                            atexit.register(_close)
                        except lmdb.Error as e:
                            import sys
                            print(f"[Semantic_Embedding] WARNING: cannot open the "
                                  f"system theory-hash registry at {path}: {e}",
                                  file=sys.stderr, flush=True)
                _system_env_checked = True
    return _system_env


def _close() -> None:
    """Drop the system-layer environment and forget the probe result (the user
    layer's environment belongs to `Isabelle_RPC_Host.theory_hash`, which has
    its own `_close_theory_hash_store`)."""
    global _system_env, _system_env_checked
    with _lock:
        if _system_env is not None:
            _system_env.close()
            _system_env = None
        _system_env_checked = False


def _system_get(key: bytes) -> 'bytes | None':
    """Raw value of ``key`` in the system layer, or None.  Safe to call while
    holding a user-layer write transaction: the two environments are distinct,
    and the system one takes no locks at all."""
    env = _ensure_system_env()
    if env is None:
        return None
    with env.begin() as txn:
        raw = txn.get(key)
    return bytes(raw) if raw is not None else None


def _get_raw(key: bytes) -> 'bytes | None':
    """THE layered point read (plan §8): user first — where a tombstone reports
    absent without falling through — then the system layer."""
    with open_theory_hash_store().begin() as txn:
        raw = txn.get(key)
    if raw is not None:
        return None if len(raw) == 0 else bytes(raw)
    return _system_get(key)


def _raw_for_update(txn, key: bytes) -> 'bytes | None':
    """The layered point read done INSIDE a user-layer write transaction; the
    user-layer reads must see (and share) the write transaction they belong to,
    so ``_get_raw`` — which opens a read transaction of its own — cannot be
    used there."""
    raw = txn.get(key)
    if raw is not None:
        return None if len(raw) == 0 else bytes(raw)
    return _system_get(key)


def iter_items() -> 'Iterator[tuple[bytes, bytes]]':
    """The merged layered scan (plan §8): a two-way sorted merge of the user and
    system layers, in key order.  On equal keys the user value wins, and a user
    tombstone emits nothing — shadowing and deletion ride the same merge.  Raw
    values; callers decode (`decode_entry`).  Both read transactions stay open
    for the whole walk."""
    sys_env = _ensure_system_env()
    with open_theory_hash_store().begin() as utxn:
        if sys_env is None:
            for k, v in utxn.cursor():
                if len(v):
                    yield bytes(k), bytes(v)
            return
        with sys_env.begin() as stxn:
            uiter = ((bytes(k), bytes(v)) for k, v in utxn.cursor())
            siter = ((bytes(k), bytes(v)) for k, v in stxn.cursor())
            u = next(uiter, None)
            s = next(siter, None)
            while u is not None or s is not None:
                if u is not None and (s is None or u[0] <= s[0]):
                    if s is not None and u[0] == s[0]:   # shadowed system entry
                        s = next(siter, None)
                    if len(u[1]):
                        yield u
                    u = next(uiter, None)
                elif s is not None:
                    yield s
                    s = next(siter, None)


def decode_entry(raw: bytes) -> 'tuple[str, int]':
    """Decode a registry value into ``(theory long name, last-seen unix seconds)``.
    Some entries were packed with a bytes name; the normalisation to str lives
    here, at the storage boundary, so no consumer repeats it."""
    name, ts = msgpack.unpackb(raw)
    if isinstance(name, bytes):
        name = name.decode("utf-8")
    return name, int(ts)
