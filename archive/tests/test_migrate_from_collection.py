"""Mechanics of migrate_from_collection.py (DYNAMIC_MEMBER_NAMING_PLAN.md §3)
on a small synthetic store: the classifier, the two gates, the SOME-change
refusal, the skip/untouched populations, the post-commit verification and
idempotent re-running.  No count here validates anything about the production
corpus -- that is the pass's own gates' job on `cslh19`.

Isolation mirrors test_layered_db: every test gets a fresh ``SEMANTIC_DB_DIR``
and the store singletons are closed around it.
"""

import json
import os
import sys

import lmdb
import msgpack
import pytest

import Isabelle_Semantic_Embedding.semantics as S


PFX = bytes(16)                       # persistent theory prefix (key[0] even)


def key_of(tag: int, i: int) -> bytes:
    return PFX + bytes([tag]) + bytes([i]) * 15


def rec13(kind: int, name: str, position) -> bytes:
    """A 13-field record as the position sweep left them."""
    return msgpack.packb((kind, name, None, "sem", None, None, None, None,
                          None, None, None, None, position))


@pytest.fixture()
def store(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("SEMANTIC_DB_DIR", str(cache))
    S._Semantic_DB._close()
    yield str(cache)
    S._Semantic_DB._close()


def seed(cache: str, extra: 'dict[bytes, bytes] | None' = None) -> str:
    path = os.path.join(cache, "semantics.lmdb")
    env = lmdb.open(path, map_size=S.SEMANTICS_MAP_SIZE)
    with env.begin(write=True) as txn:
        txn.put(key_of(0x06, 1), rec13(0x06, "Thy.coll", ("f.thy", 1, 1)))
        txn.put(key_of(0x02, 2), rec13(0x02, "Thy.coll(3)", None))       # member
        txn.put(key_of(0x02, 3), rec13(0x02, "Thy.foo", ("f.thy", 2, 1)))
        txn.put(key_of(0x02, 4), rec13(0x02, "Thy.bar(2)", ("f.thy", 3, 1)))  # static bundle
        txn.put(key_of(0x07, 5), rec13(0x07, "Named.simp(1)", None))     # method
        txn.put(key_of(0x08, 6), msgpack.packb(                          # experience, 8 fields
            (0x08, "attempt(3)", None, "how", None, None, "payload", ["pat"])))
        txn.put(PFX, msgpack.packb({b"finished": True}))                 # theory status
        txn.put(b"\x00", msgpack.packb(7))                               # the counter key
        for k, v in (extra or {}).items():
            txn.put(k, v)
    env.close()
    return path


def run_main(report_path: str, dry: bool = False) -> None:
    import migrate_from_collection as M
    argv = ["migrate_from_collection.py", "--report", report_path]
    if dry:
        argv.append("--dry-run")
    old = sys.argv
    sys.argv = argv
    try:
        M.main()
    finally:
        sys.argv = old


def raw_fields(path: str, key: bytes) -> list:
    env = lmdb.open(path, readonly=True, lock=False)
    try:
        with env.begin() as txn:
            return list(msgpack.unpackb(txn.get(key)))
    finally:
        env.close()


def test_classifier_owns_only_the_shared_conjuncts():
    from migrate_from_collection import parse_member_base
    assert parse_member_base(0x02, "Thy.coll(3)") == "Thy.coll"
    assert parse_member_base(0x02, "Thy.foo") is None
    assert parse_member_base(0x08, "attempt(3)") is None    # kind exclusion
    assert parse_member_base(0x07, "Named.simp(1)") is None  # kind exclusion
    # position and collection-set membership are deliberately NOT its business


def test_happy_path_writes_field_14_everywhere_walked(store):
    path = seed(store)
    report = os.path.join(store, "report.json")
    run_main(report)
    rep = json.load(open(report))
    assert rep["verified"] is True
    assert rep["walked"] == 5            # coll, member, foo, bar bundle, method
    assert rep["matched"] == 1
    assert rep["nil_written"] == 4
    assert rep["experience_skipped"] == 1
    assert rep["undecodable"] == 0
    S._Semantic_DB._close()              # reopen raw below
    member = raw_fields(path, key_of(0x02, 2))
    assert len(member) == 14 and member[13] == "Thy.coll"
    for i, tag in ((3, 0x02), (4, 0x02), (5, 0x07)):
        vals = raw_fields(path, key_of(tag, i))
        assert len(vals) == 14 and vals[13] is None
    assert len(raw_fields(path, key_of(0x08, 6))) == 8      # experience untouched
    # the status map and the counter survive byte-identically
    env = lmdb.open(path, readonly=True, lock=False)
    with env.begin() as txn:
        assert msgpack.unpackb(txn.get(PFX)) == {"finished": True} or \
               msgpack.unpackb(txn.get(PFX)) == {b"finished": True}
        assert msgpack.unpackb(txn.get(b"\x00")) == 7
    env.close()
    # a timestamped backup was taken beside the store
    assert any(d.startswith("semantics.lmdb.bak-") for d in os.listdir(store))


def test_rerun_is_idempotent(store):
    path = seed(store)
    report = os.path.join(store, "r1.json")
    run_main(report)
    S._Semantic_DB._close()
    before = raw_fields(path, key_of(0x02, 2))
    report2 = os.path.join(store, "r2.json")
    run_main(report2)
    assert json.load(open(report2))["verified"] is True
    S._Semantic_DB._close()
    assert raw_fields(path, key_of(0x02, 2)) == before


def test_orphan_gate_aborts_before_writing(store):
    path = seed(store, extra={
        key_of(0x02, 9): rec13(0x02, "Thy.gone(4)", None)})  # base not a collection
    with pytest.raises(SystemExit, match="ORPHAN"):
        run_main(os.path.join(store, "r.json"))
    S._Semantic_DB._close()
    assert len(raw_fields(path, key_of(0x02, 2))) == 13      # nothing written


def test_window_gate_aborts_before_writing(store):
    path = seed(store, extra={
        key_of(0x02, 9): rec13(0x02, "Thy.coll(5)", ("f.thy", 9, 1))})
    with pytest.raises(SystemExit, match="WINDOW"):
        run_main(os.path.join(store, "r.json"))
    S._Semantic_DB._close()
    assert len(raw_fields(path, key_of(0x02, 2))) == 13


def test_refuses_to_change_an_existing_some(store):
    poisoned = msgpack.packb((0x02, "Thy.renamed", None, "sem", None, None,
                              None, None, None, None, None, None,
                              ("f.thy", 4, 1), "Thy.coll"))
    path = seed(store, extra={key_of(0x02, 9): poisoned})
    with pytest.raises(SystemExit, match="SOME"):
        run_main(os.path.join(store, "r.json"))
    S._Semantic_DB._close()
    assert len(raw_fields(path, key_of(0x02, 2))) == 13


def test_dry_run_writes_nothing(store):
    path = seed(store)
    report = os.path.join(store, "dry.json")
    run_main(report, dry=True)
    rep = json.load(open(report))
    assert rep["dry_run"] is True and rep["matched"] == 1
    S._Semantic_DB._close()
    assert len(raw_fields(path, key_of(0x02, 2))) == 13
    assert not any(d.startswith("semantics.lmdb.bak-") for d in os.listdir(store))
