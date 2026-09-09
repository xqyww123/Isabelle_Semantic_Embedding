"""Storage half of the semantic change gate
(ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md §6, §10): the 15th record field, the
one entry point `gate_write` (with its two puts), the raw-put grant it shares
with `backfill_field`, the read-only `counter_snapshot` -- and, over the same
isolated store, the gate of semantic_interpretation.py (`_gate` / `_write`,
as it stands before §13 step 5 adds the judge), the only way an
interpretation reaches the store.

Isolation follows test_layered_db.py: fresh SEMANTIC_DB_DIR per test, every
singleton environment closed around it.
"""
from __future__ import annotations

import sys

import msgpack
import numpy as np
import pytest

import Isabelle_Semantic_Embedding.semantic_embedding as SE
import Isabelle_Semantic_Embedding.semantics as S
from Isabelle_RPC_Host.universal_key import EntityKind

Record = S._Semantic_DB.Record
_encode = S._Semantic_DB._encode
_decode = S._Semantic_DB._decode

WIP_THY = bytes([0x31]) + b"\x11" * 15          # LSB set: a WIP theory hash
D = 128                                          # see test_layered_db.D
STORE = "vector_test.lmdb"


def _reset_singletons() -> None:
    S.Semantic_DB.__dict__.clear()
    S._Semantic_DB._close()
    SE._close_all_lmdb_envs()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("SEMANTIC_DB_DIR", str(cache))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "prefix"))
    _reset_singletons()
    yield cache
    _reset_singletons()


def _uk(name: str) -> bytes:
    return WIP_THY + bytes([int(EntityKind.CONSTANT)]) + name.encode()


def _full_record(**kw) -> Record:
    """Every field before the new one distinctive, so a shift by one position
    cannot pass unnoticed (the test_entity_position_codec discipline)."""
    base = dict(kind=EntityKind.CONSTANT, name="Foo.c", expr="c :: nat",
                interpretation="the c", locale_provenance=None,
                theory_constituents=None, experience=None, goal_patterns=None,
                semantic_digest=b"\x02" * 16, deps=[b"\x03" * 17],
                version=7, interpreted_at=9,
                position=("$AFP/Foo/Bar.thy", 42, 7), from_collection="Foo.coll")
    return Record(**{**base, **kw})


def _pack_n(rec: Record, n: int) -> bytes:
    """The exact n-field packing an older codec produced (12 <= n <= 15)."""
    full = (int(rec.kind), rec.name, rec.expr, rec.interpretation, None,
            rec.theory_constituents, rec.experience, rec.goal_patterns,
            rec.semantic_digest, rec.deps, rec.version, rec.interpreted_at,
            rec.position, rec.from_collection, rec.baseline_interpretation)
    return msgpack.packb(full[:n])  # type: ignore[return-value]


def _raw_len(key: bytes) -> int:
    with S.Semantic_DB._ensure_env().begin() as txn:
        return len(msgpack.unpackb(txn.get(key)))


def _write_raw(key: bytes, raw: bytes) -> None:
    with S.Semantic_DB._ensure_env().begin(write=True) as txn:
        txn.put(key, raw)


def _wire(rec: Record) -> dict:
    """put_interpretation's wire-field keyword arguments taken from a record."""
    return dict(kind=rec.kind, name=rec.name, expr=rec.expr,
                interpretation=rec.interpretation,
                locale_provenance=rec.locale_provenance,
                theory_constituents=rec.theory_constituents,
                position=rec.position, from_collection=rec.from_collection)


def _gate(rec: Record) -> dict:
    return dict(semantic_digest=rec.semantic_digest, deps=rec.deps,
                version=rec.version, interpreted_at=rec.interpreted_at,
                baseline_interpretation=rec.baseline_interpretation)


class _FakeProvider:
    dimension = D
    canonical_model = "test"


def _mk_vector_store(cache) -> SE.Vector_Store:
    return SE.Vector_Store(str(cache / STORE), _FakeProvider(), None)


def _basis(i: int) -> np.ndarray:
    v = np.zeros(D, dtype=np.float32)
    v[i] = 1.0
    return v


# --- codec ------------------------------------------------------------------

def test_record_field_count_is_the_codec_arity():
    assert S.RECORD_FIELD_COUNT == 15 == len(Record._fields)
    assert Record._fields[14] == "baseline_interpretation"
    assert len(S.unpack_fields(_pack_n(_full_record(), 12))) == 15


def test_15_field_round_trip_and_legacy_arities_read_none():
    rec = _full_record(baseline_interpretation="the c, at its last mint")
    assert _decode(_encode(rec)) == rec
    for n in (12, 13, 14):
        legacy = _decode(_pack_n(rec, n))
        assert legacy.baseline_interpretation is None
        assert legacy == rec._replace(**{f: None for f in Record._fields[n:]})


def test_baseline_survives_as_str_not_bytes():
    packed = msgpack.packb((int(EntityKind.CONSTANT), "Foo.c", None, "the c",
                            None, None, None, None, None, None, None, None,
                            None, None, b"baseline"))
    assert _decode(packed).baseline_interpretation == "baseline"  # type: ignore[arg-type]


# --- gate_write -------------------------------------------------------------

def test_gate_write_mints_in_the_same_transaction_and_returns_the_record(cache):
    k = _uk("c")
    S.Semantic_DB[k] = _full_record(version=None, interpreted_at=None)
    with S.Semantic_DB.gate_write() as w:
        eps = w.counter_value()
        v = w.mint()
        assert v == eps + 1
        written = w.update_gate_fields(k, semantic_digest=b"\x05" * 16, deps=[],
                                       version=v, interpreted_at=v,
                                       baseline_interpretation="the c")
    got = S.Semantic_DB[k]
    assert got == written
    assert (got.version, got.interpreted_at, got.baseline_interpretation) == (v, v, "the c")
    assert got.interpretation == "the c" and got.expr == "c :: nat", "wire fields untouched"
    with S.Semantic_DB._ensure_env().begin() as txn:
        assert S.Semantic_DB.counter_value(txn) == v


@pytest.mark.parametrize("n", [12, 13, 14])
def test_gate_write_on_a_legacy_arity_record(cache, n):
    k = _uk("c")
    _write_raw(k, _pack_n(_full_record(), n))
    with S.Semantic_DB.gate_write() as w:
        w.update_gate_fields(k, **_gate(_full_record(version=8, interpreted_at=8,
                                                     baseline_interpretation="b")))
    got = S.Semantic_DB[k]
    assert (got.version, got.baseline_interpretation) == (8, "b")
    assert got.position == (("$AFP/Foo/Bar.thy", 42, 7) if n >= 13 else None)
    assert got.from_collection == ("Foo.coll" if n >= 14 else None)
    assert _raw_len(k) == 15


def test_gate_write_aborted_mid_batch_leaves_store_and_counter_byte_identical(cache):
    """Crash shape (ii): nothing written, not even the mints."""
    ka, kb = _uk("a"), _uk("b")
    S.Semantic_DB[ka] = _full_record(name="a")
    S.Semantic_DB[kb] = _full_record(name="b")
    with S.Semantic_DB._ensure_env().begin(write=True) as txn:
        before = (S.Semantic_DB.counter_value(txn), txn.get(ka), txn.get(kb))
    with pytest.raises(RuntimeError):
        with S.Semantic_DB.gate_write() as w:
            v = w.mint()
            w.update_gate_fields(ka, **_gate(_full_record(version=v, interpreted_at=v)))
            raise RuntimeError("judge output lost mid-write")
    with S.Semantic_DB._ensure_env().begin() as txn:
        assert (S.Semantic_DB.counter_value(txn), txn.get(ka), txn.get(kb)) == before


def test_gate_write_on_a_missing_record_aborts_the_batch(cache):
    """The gate runs after the answer was written; a missing record is a bug
    and must not turn into a silent partial batch."""
    ka = _uk("a")
    S.Semantic_DB[ka] = _full_record(name="a")
    with pytest.raises(LookupError):
        with S.Semantic_DB.gate_write() as w:
            v = w.mint()
            w.update_gate_fields(ka, **_gate(_full_record(version=v, interpreted_at=v)))
            w.update_gate_fields(_uk("ghost"), **_gate(_full_record()))
    assert S.Semantic_DB[ka].version == 7, "the batch rolled back whole"


def test_update_gate_fields_does_not_invalidate_vectors(cache):
    k = _uk("c")
    S.Semantic_DB[k] = _full_record()
    store = _mk_vector_store(cache)
    store.put(k, _basis(0))
    with S.Semantic_DB.gate_write() as w:
        w.update_gate_fields(k, **_gate(_full_record(version=8, interpreted_at=8,
                                                     baseline_interpretation="b")))
    assert store.contains([k]) == [True]


def test_the_raw_put_grant_is_checked_for_the_gate_writer(cache, monkeypatch):
    """Adding an embedded-document field to the gate writer's set raises
    before any transaction is opened."""
    monkeypatch.setattr(S._Semantic_DB, "_GATE_FIELDS",
                        S._Semantic_DB._GATE_FIELDS + ("interpretation",))
    with pytest.raises(AssertionError, match="gate_write\\('interpretation'\\)"):
        with S.Semantic_DB.gate_write():
            pass
    monkeypatch.setattr(S._Semantic_DB, "_GATE_FIELDS", ("no_such_field",))
    with pytest.raises(AssertionError, match="no such record field"):
        with S.Semantic_DB.gate_write():
            pass


def test_backfill_field_keeps_its_grant_check(cache):
    with pytest.raises(AssertionError, match="backfill_field\\('interpretation'\\)"):
        S.Semantic_DB.backfill_field("interpretation", [])
    with pytest.raises(AssertionError, match="no such record field"):
        S.Semantic_DB.backfill_field("nope", [])
    assert S.Semantic_DB.backfill_field("baseline_interpretation", []) == (0, 0)


# --- put_interpretation -----------------------------------------------------

def _all(rec: Record) -> dict:
    """put_interpretation's keyword arguments taken from a record."""
    return {**_wire(rec), **_gate(rec)}


def test_put_interpretation_writes_text_and_gate_fields_in_one_transaction(cache):
    k = _uk("c")
    S.Semantic_DB[k] = _full_record(interpretation="the old c", version=None,
                                    interpreted_at=None)
    with S.Semantic_DB.gate_write() as w:
        v = w.mint()
        written = w.put_interpretation(k, **_all(_full_record(
            interpretation="the new c", version=v, interpreted_at=v,
            baseline_interpretation="the new c")))
    got = S.Semantic_DB[k]
    assert got == written
    assert got.interpretation == "the new c"
    assert (got.version, got.interpreted_at, got.baseline_interpretation) \
        == (v, v, "the new c")
    assert _raw_len(k) == 15


def test_put_interpretation_invalidates_the_vector_first(cache):
    k = _uk("c")
    S.Semantic_DB[k] = _full_record()
    store = _mk_vector_store(cache)
    store.put(k, _basis(0))
    with S.Semantic_DB.gate_write() as w:
        w.put_interpretation(k, **_all(_full_record(interpretation="reworded")))
    assert store.contains([k]) == [False], "the embedded document changed"


def test_put_interpretation_creates_and_resurrects(cache):
    fresh, dead = _uk("fresh"), _uk("dead")
    S.Semantic_DB[dead] = _full_record(name="dead", version=3)
    assert S.Semantic_DB.delete(dead)
    with S.Semantic_DB.gate_write() as w:
        eps = w.counter_value()
        w.put_interpretation(fresh, **_all(_full_record(
            name="fresh", version=eps, interpreted_at=eps, baseline_interpretation="the c")))
        w.put_interpretation(dead, **_all(_full_record(
            name="dead", version=eps, interpreted_at=eps, baseline_interpretation="the c")))
    assert S.Semantic_DB[fresh] == _full_record(
        name="fresh", version=eps, interpreted_at=eps, baseline_interpretation="the c")
    assert S.Semantic_DB[dead].version == eps, \
        "a tombstoned key is rewritten whole; the tombstone was the end of its history"


def test_put_interpretation_carries_the_fields_it_does_not_write_up_from_a_legacy_record(cache):
    """A 12-field record (no position / from_collection / baseline) with
    experience and goal_patterns set: the put rewrites the three truncated
    fields itself and carries the two it does not name up unchanged."""
    k = _uk("c")
    old = _full_record(experience="learned", goal_patterns=["p"])
    _write_raw(k, _pack_n(old, 12))
    with S.Semantic_DB.gate_write() as w:
        w.put_interpretation(k, **_all(_full_record(interpretation="fresh")))
    got = S.Semantic_DB[k]
    assert (got.experience, got.goal_patterns) == ("learned", ["p"])
    assert got.interpretation == "fresh" and got.position == ("$AFP/Foo/Bar.thy", 42, 7)
    assert _raw_len(k) == 15


def test_put_interpretation_aborted_leaves_nothing(cache):
    """Crash shape (ii): the mint and the record commit together or not at all."""
    k = _uk("c")
    with S.Semantic_DB._ensure_env().begin(write=True) as txn:
        before = S.Semantic_DB.counter_value(txn)
    with pytest.raises(RuntimeError):
        with S.Semantic_DB.gate_write() as w:
            v = w.mint()
            w.put_interpretation(k, **_all(_full_record(version=v, interpreted_at=v)))
            raise RuntimeError("lost mid-write")
    assert S.Semantic_DB[k] is None
    with S.Semantic_DB._ensure_env().begin() as txn:
        assert S.Semantic_DB.counter_value(txn) == before


# --- counter_snapshot -------------------------------------------------------

def test_counter_snapshot_reads_one_on_an_empty_store_and_writes_nothing(cache):
    assert S.Semantic_DB.counter_snapshot() == 1
    with S.Semantic_DB._ensure_env().begin() as txn:
        assert txn.get(S.Semantic_DB.COUNTER_KEY) is None, "a read, not a put"
    with S.Semantic_DB.gate_write() as w:
        v = w.mint()
    assert S.Semantic_DB.counter_snapshot() == v


# --- the gate over the store (semantic_interpretation._gate) ----------------
#
# `interpret_file`'s gate is driven directly: an `InterpretationTask` over two
# entries whose `rec_cache` says the store holds neither, its entries
# answered, `asyncio.run(_run_gate(task, i))`.  No task group: `_gate` is
# the coroutine `start_gate` would create.

import asyncio

from Isabelle_Semantic_Embedding.semantic_interpretation import (
    Entry,
    InterpretationTask,
    _DONE,
    _GATING,
)
from Isabelle_Semantic_Embedding.semantic_interpretation import _gate as _run_gate

_TRACKED = Entry(kind=int(EntityKind.CONSTANT), name="Foo.c", prop_str="c :: nat",
                 position=("$AFP/Foo/Bar.thy", 42, 7), universal_key=_uk("c"),
                 semantic_digest=b"\x02" * 16, deps=[b"\x03" * 17, b"\x04" * 17])
_UNTRACKED = Entry(kind=int(EntityKind.CONSTANT), name="Foo.p", prop_str="p :: int",
                   position=("$AFP/Foo/Bar.thy", 50, 1), universal_key=_uk("p"))


def _gate_task(answers: list[str]) -> InterpretationTask:
    """Both entries answered (state _GATING, as `on_answer` leaves them) over
    a store that holds neither: the scan's `rec_cache` says so."""
    task = InterpretationTask(None, "/tmp/Foo.thy", "Foo", WIP_THY + b"\x00" * 16,
                              [_TRACKED, _UNTRACKED],
                              rec_cache={_TRACKED.universal_key: None,
                                         _UNTRACKED.universal_key: None})
    for i, text in enumerate(answers):
        task.enqueue(i)
        task.results[i] = text
        task.state[i] = _GATING
    return task


def _gate_fields(rec: Record) -> tuple:
    return (rec.semantic_digest, rec.deps, rec.version, rec.interpreted_at,
            rec.baseline_interpretation)


def test_the_gate_writes_the_answer_as_a_first_write_in_one_record(cache):
    """§3 row 1 (the only row until step 5 judges): version ε, the wire
    digest and deps, baseline := the text, interpreted_at = eff* over
    rec_cache; an untracked entry keeps every gate field None."""
    task = _gate_task(["the c", "the p"])
    for i in range(2):
        asyncio.run(_run_gate(task, i))
    c, p = S.Semantic_DB[_uk("c")], S.Semantic_DB[_uk("p")]
    eps = S.Semantic_DB.counter_snapshot()
    assert (c.interpretation, c.expr, c.position, c.name) \
        == ("the c", "c :: nat", ("$AFP/Foo/Bar.thy", 42, 7), "Foo.c")
    assert _gate_fields(c) == (b"\x02" * 16, [b"\x03" * 17, b"\x04" * 17], eps, eps, "the c")
    assert p.interpretation == "the p"
    assert _gate_fields(p) == (None, None, None, None, None), \
        "an untracked entry keeps every gate field None"
    assert task.state == [_DONE, _DONE]
    assert task.n_interpreted() == 2
    assert task.rec_cache[_uk("c")] == c and task.rec_cache[_uk("p")] == p, \
        "written back from the transaction: rec_cache == store"


def test_the_gate_takes_a_snapshot_over_the_current_records(cache):
    """interpreted_at = eff*(E) over rec_cache at the write: a stale
    dependency's number passes through (no wall), a fresh one's own version
    is the wall."""
    dep = _uk("dep")
    S.Semantic_DB[dep] = _full_record(name="Foo.dep", deps=[], version=9, interpreted_at=9)
    upstream = _uk("up")
    S.Semantic_DB[upstream] = _full_record(name="Foo.up", deps=[], version=20, interpreted_at=20)
    S.Semantic_DB[dep] = _full_record(name="Foo.dep", deps=[upstream], version=9, interpreted_at=9)
    e = _TRACKED._replace(deps=[dep])
    task = InterpretationTask(None, "/tmp/Foo.thy", "Foo", WIP_THY + b"\x00" * 16, [e],
                              rec_cache={e.universal_key: None})
    task.enqueue(0); task.results[0] = "the c"; task.state[0] = _GATING
    asyncio.run(_run_gate(task, 0))
    assert S.Semantic_DB[_uk("c")].interpreted_at == 20, \
        "dep is stale (eff* 20 > interpreted_at 9): its whole upstream signal passes"


def test_a_gate_write_failure_propagates_the_store_s_exception_with_a_note(cache):
    """A corrupt record under the key (one of the failure causes a write has)
    fails the gate with the store's own exception; the note says which
    entity, the entry is not marked written."""
    _write_raw(_uk("c"), b"not msgpack at all")
    task = _gate_task(["the c", "the p"])
    with pytest.raises(ValueError) as e:
        asyncio.run(_run_gate(task, 0))
    assert not isinstance(e.value, AssertionError)
    assert e.value.__notes__ == ["while writing the interpretation of Foo.c"]
    assert task.state[0] == _GATING


def test_a_correction_is_a_second_gate_that_rewrites_the_text(cache):
    """D11: a correction of a written entity re-runs the gate over the record
    the first gate wrote.  Until step 5 judges, the second gate is again a
    first write (§3 row 1): the same ε and snapshot, the baseline moved to
    the new text -- the over-signalling §15.11 accepts for step 4."""
    task = _gate_task(["the c", "the p"])
    asyncio.run(_run_gate(task, 0))
    first = S.Semantic_DB[_uk("c")]
    store = _mk_vector_store(cache)
    store.put(_uk("c"), _basis(0))
    task.state[0] = _GATING                      # what on_answer does for a _DONE entry
    task.results[0] = "corrected text"
    asyncio.run(_run_gate(task, 0))
    second = S.Semantic_DB[_uk("c")]
    assert second.interpretation == "corrected text"
    assert _gate_fields(second) == _gate_fields(first)[:4] + ("corrected text",)
    assert store.contains([_uk("c")]) == [False], "the embedded document changed"
    assert task.state[0] == _DONE and task.n_interpreted() == 1


# --- interpret_file end to end (scan, loop, gates, closing count) ------------

import lmdb

import Isabelle_Semantic_Embedding.semantic_interpretation as SI
from test_interpretation_driver import _ScriptedDriver, _answer


class _StubConnection:
    class server:
        import logging
        logger = logging.getLogger("test_semantic_change_gate_storage.stub")


@pytest.fixture
def scripted_run(cache, tmp_path, monkeypatch):
    """`interpret_file` over the isolated store with the scripted driver in
    place of the agent backend.  Returns a runner taking the driver script."""
    thy = tmp_path / "Foo.thy"
    thy.write_text('theory Foo imports Main begin\ndefinition c :: nat where "c = 0"\nend\n')
    monkeypatch.setattr(SI, "interpretation_driver_override", "")
    monkeypatch.delenv("INTERPRETATION_DRIVER", raising=False)
    log: list = []

    def run(script, entries=(_TRACKED, _UNTRACKED)):
        def make(name, *, model, system_prompt, tools, task, on_context_reset):
            log.append(("make", name))
            return _ScriptedDriver(script=script, log=log, model=model,
                                   system_prompt=system_prompt, tools=tools,
                                   task=task, on_context_reset=on_context_reset)
        monkeypatch.setattr(SI, "make_interpretation_driver", make)
        return asyncio.run(SI.interpret_file(
            _StubConnection(), str(thy), "Foo", WIP_THY + b"\x00" * 16,
            list(entries)))
    run.log = log
    return run


def test_interpret_file_writes_every_answer_through_its_gate(scripted_run):
    res = scripted_run([_answer(0, 1)])
    assert res.interpretations == ["description of c0", "description of c1"]
    c, p = S.Semantic_DB[_uk("c")], S.Semantic_DB[_uk("p")]
    assert c.interpretation == "description of c0" and p.interpretation == "description of c1"
    eps = S.Semantic_DB.counter_snapshot()
    assert _gate_fields(c) == (b"\x02" * 16, [b"\x03" * 17, b"\x04" * 17], eps, eps,
                               "description of c0"), \
        "a first write: ε, its eff* snapshot, the text as baseline (§3 row 1)"
    assert _gate_fields(p) == (None, None, None, None, None)
    assert [k for k, _ in scripted_run.log] == ["make", "enter", "turn", "exit"]


def test_interpret_file_raises_the_store_s_exception_itself_when_a_gate_write_fails(
        scripted_run, monkeypatch):
    """The failing gate's exception leaves `interpret_file` bare: its note
    names the entity, and its context is NOT the task group's
    ExceptionGroup (it is raised outside the except block)."""
    def full(self):
        raise lmdb.MapFullError("mdb_put: MDB_MAP_FULL: Environment mapsize limit reached")
    monkeypatch.setattr(S._Semantic_DB, "gate_write", full)
    with pytest.raises(lmdb.MapFullError) as e:
        scripted_run([_answer(0, 1)])
    assert e.value.__notes__ == ["while writing the interpretation of Foo.c"]
    assert not isinstance(e.value.__context__, BaseExceptionGroup)
    assert S.Semantic_DB[_uk("c")] is None, "nothing written; the theory is not marked"


def test_a_live_run_with_no_seed_still_refreshes_the_statement(scripted_run):
    """§5.3.2 on the live path, zero seeds (the shape `collect --reinterpret`
    produces for almost every theory): no driver is built, the stored text is
    returned, and the changed `prop_str` is written to `expr` while the five
    gate fields stay byte-identical."""
    stored = _full_record(name="Foo.c", expr="c :: nat", interpretation="the stored c",
                          deps=[b"\x03" * 17, b"\x04" * 17], version=1, interpreted_at=1)
    S.Semantic_DB[_uk("c")] = stored
    res = scripted_run([], entries=[_TRACKED._replace(prop_str="c :: nat ⇒ nat")])
    assert res.interpretations == ["the stored c"]
    assert scripted_run.log == [], "no driver was built: nothing to ask"
    got = S.Semantic_DB[_uk("c")]
    assert got.expr == "c :: nat ⇒ nat"
    assert _gate_fields(got) == _gate_fields(stored)
