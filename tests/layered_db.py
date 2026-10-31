"""An isolated layered DB for tests: every test using `cache` gets a fresh
``SEMANTIC_DB_DIR`` (and a fake ``sys.prefix``, so a real conda payload on the
dev machine can never leak in), with all the package's singleton LMDB
environments closed before and after -- py-lmdb allows sequential
close-and-reopen of one path, just never two concurrent opens.

A plain module, not a conftest.py: pytest would load a conftest beside
test_vecarith.py, which CI runs against a --no-deps install.
"""
from __future__ import annotations

import json
import sys

import lmdb
import msgpack
import pytest

import Isabelle_Semantic_Embedding.semantic_embedding as SE
import Isabelle_Semantic_Embedding.semantics as S
import Isabelle_Semantic_Embedding.snapshot_sync as SS


def reset_singletons() -> None:
    S._Semantic_DB._close()
    from Isabelle_Semantic_Embedding.experience_index import _Experience_Index
    _Experience_Index._close()
    SE._close_all_lmdb_envs()
    SS._system_db_cache = SS._SYSTEM_DB_UNSET
    # The theory-hash registry: its user layer is the lower package's singleton
    # (pinned to the SEMANTIC_DB_DIR seen at first open), its system layer this
    # package's -- both must drop for the next test's fresh dirs to take.
    from Isabelle_RPC_Host.theory_hash import _close_theory_hash_store
    _close_theory_hash_store()
    import Isabelle_Semantic_Embedding.theory_hash_registry as THR
    THR._close()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Fresh user-DB dir; fake sys.prefix; all singletons reset around the test."""
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("SEMANTIC_DB_DIR", str(cache))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "prefix"))
    reset_singletons()
    yield cache
    reset_singletons()


def mk_system(cache, records=None):
    """A system DB at ``<cache>/system`` (the `pulled` location) holding `records`."""
    sysdir = cache / "system"
    sysdir.mkdir(exist_ok=True)
    (sysdir / SS.MANIFEST_NAME).write_text(json.dumps(
        {"schema_version": SS.SCHEMA_VERSION, "vector_format": SS.VECTOR_FORMAT}))
    env = lmdb.open(str(sysdir / "semantics.lmdb"), map_size=1 << 24)
    with env.begin(write=True) as txn:
        for k, v in (records or {}).items():
            txn.put(k, v)
    env.close()
    return sysdir


def write_user(records: dict[bytes, bytes]) -> None:
    with S.Semantic_DB._ensure_env().begin(write=True) as txn:
        for k, v in records.items():
            txn.put(k, v)


def reg(name: str, ts: int) -> bytes:
    """A registry value: msgpack [theory long name, last-seen unix seconds]."""
    return msgpack.packb([name, ts])  # type: ignore


def write_user_registry(entries: dict[bytes, bytes]) -> None:
    from Isabelle_RPC_Host.theory_hash import open_theory_hash_store
    with open_theory_hash_store().begin(write=True) as txn:
        for k, v in entries.items():
            txn.put(k, v)
