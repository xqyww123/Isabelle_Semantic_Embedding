"""Tests for the layered semantic DB read facade (SEMANTIC_DB_LAYERED_PLAN §9.1-9.4b).

Two read layers: the writable user DB under ``semantic_DB_dir()`` and the
read-only system DB under ``<cache>/system`` (or a conda payload at
``sys.prefix/share/isabelle-semantic-data``).  Reads consult user first --
where an empty value is a TOMBSTONE meaning "absent, do not fall through" --
then system.  Vectors follow the vector-record binding invariant (L23).

Isolation: every test gets a fresh ``SEMANTIC_DB_DIR`` (and a fake
``sys.prefix``, so a real conda payload on the dev machine can never leak in),
with all the package's singleton LMDB environments closed before and after --
py-lmdb allows sequential close-and-reopen of one path, just never two
concurrent opens.
"""
from __future__ import annotations

import json
import os
import sys

import lmdb
import msgpack
import numpy as np
import pytest

import Isabelle_Semantic_Embedding.semantic_embedding as SE
import Isabelle_Semantic_Embedding.semantics as S
import Isabelle_Semantic_Embedding.snapshot_sync as SS
from Isabelle_Semantic_Embedding._vecarith import encode_q15
from Isabelle_RPC_Host.universal_key import EntityKind, xor_theory_prefix

# Persistent (non-WIP) theory hashes: LSB of byte 0 must be 0.
HA = bytes.fromhex("22" * 16)
HB = bytes.fromhex("44" * 16)
EXP = int(EntityKind.EXPERIENCE)
THM = int(EntityKind.THEOREM)
CONST = int(EntityKind.CONSTANT)

# Embedding dimension for the vector tests.  Not tiny: the top_k kernel runs
# unaligned SIMD loads over the value bytes, so a value much smaller than a
# SIMD lane at the tail of a small mmap'd test store can fault past the last
# page (bus error).  128 int16s = 256 bytes, a multiple of every lane width.
D = 128
STORE = "vector_test.lmdb"           # one model's store, same name in both layers


def _key(prefix: bytes, kind: int, suffix: bytes) -> bytes:
    return prefix + bytes([kind]) + suffix.ljust(15, b"\x00")


def _record(kind: int, name: str, interpretation: str = "meaning",
            consts=None, expr="[]") -> bytes:
    """A stored record tuple: (kind, name, expr, interpretation, prov, consts, exp)."""
    return msgpack.packb((kind, name, expr, interpretation, None, consts, None))


def _reset_singletons() -> None:
    # Drop stubbed instance attributes other test files leave on the singleton
    # (test_auto_embed_gate_off pins get_many/is_thy_interpreted on it without
    # restoring; the real state all lives on the class).
    S.Semantic_DB.__dict__.clear()
    S._Semantic_DB._close()
    from Isabelle_Semantic_Embedding.experience_index import _Experience_Index
    _Experience_Index._close()
    SE._close_all_lmdb_envs()
    SS._system_db_cache = SS._SYSTEM_DB_UNSET


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Fresh user-DB dir; fake sys.prefix; all singletons reset around the test."""
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("SEMANTIC_DB_DIR", str(cache))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "prefix"))
    _reset_singletons()
    yield cache
    _reset_singletons()


def _mk_system(cache, records=None, vectors=None, index=None, manifest=None):
    """Build a system DB at ``<cache>/system`` (the `pulled` location)."""
    sysdir = cache / "system"
    sysdir.mkdir(exist_ok=True)
    m = manifest if manifest is not None else {
        "schema_version": SS.SCHEMA_VERSION, "vector_format": SS.VECTOR_FORMAT}
    (sysdir / SS.MANIFEST_NAME).write_text(json.dumps(m))
    env = lmdb.open(str(sysdir / "semantics.lmdb"), map_size=1 << 24)
    with env.begin(write=True) as txn:
        for k, v in (records or {}).items():
            txn.put(k, v)
    env.close()
    for store, vecs in (vectors or {}).items():
        venv = lmdb.open(str(sysdir / store), map_size=1 << 24)
        with venv.begin(write=True) as txn:
            for k, v in vecs.items():
                txn.put(k, v)
        venv.close()
    if index is not None:
        ienv = lmdb.open(str(sysdir / "experience_index.lmdb"), map_size=1 << 24)
        with ienv.begin(write=True) as txn:
            for h, uks in index.items():
                txn.put(h, msgpack.packb(uks))
        ienv.close()
    return sysdir


def _write_user(records: dict[bytes, bytes]) -> None:
    with S.Semantic_DB._ensure_env().begin(write=True) as txn:
        for k, v in records.items():
            txn.put(k, v)


def _user_raw(key: bytes):
    with S.Semantic_DB._ensure_env().begin() as txn:
        raw = txn.get(key)
    return bytes(raw) if raw is not None else None


def _basis(i: int) -> np.ndarray:
    v = np.zeros(D, dtype=np.float32)
    v[i] = 1.0
    return v


def _q15(v: np.ndarray) -> bytes:
    return encode_q15(v).tobytes()


class _FakeProvider:
    dimension = D
    canonical_model = "test"


def _mk_vector_store(cache) -> SE.Vector_Store:
    return SE.Vector_Store(str(cache / STORE), _FakeProvider(), None)


# ---------------------------------------------------------------------------
# §9.1  Facade: shadowing, merged iteration, degenerate cases
# ---------------------------------------------------------------------------

def test_user_shadows_system_on_point_reads(cache):
    a = _key(HA, CONST, b"\x01")
    b = _key(HA, CONST, b"\x02")
    _mk_system(cache, records={a: _record(CONST, "a", "system a"),
                               b: _record(CONST, "b", "system b")})
    _write_user({a: _record(CONST, "a", "user a")})

    assert S.Semantic_DB[a].interpretation == "user a"       # user wins
    assert S.Semantic_DB[b].interpretation == "system b"     # falls through
    assert a in S.Semantic_DB and b in S.Semantic_DB
    assert S.Semantic_DB.contains([a, b, _key(HB, CONST, b"\x09")]) == [True, True, False]
    got = S.Semantic_DB.get_many([b, a])
    assert [r.interpretation for r in got] == ["system b", "user a"]


def test_merged_iteration_sorted_user_wins(cache):
    k1 = _key(HA, CONST, b"\x01")
    k2 = _key(HA, CONST, b"\x02")
    k3 = _key(HA, CONST, b"\x03")
    _mk_system(cache, records={k1: _record(CONST, "k1", "sys"),
                               k2: _record(CONST, "k2", "sys"),
                               HA: msgpack.packb({b"finished": True})})
    _write_user({k2: _record(CONST, "k2", "usr"),
                 k3: _record(CONST, "k3", "usr")})

    items = list(S.Semantic_DB.iter_items())
    assert [k for k, _ in items] == sorted([HA, k1, k2, k3])
    by_key = dict(items)
    assert S.Semantic_DB._decode(by_key[k2]).interpretation == "usr"

    ents = dict(S.Semantic_DB.iter_entity_records())
    assert HA not in ents                       # 16-byte status keys skipped
    assert set(ents) == {k1, k2, k3}
    assert ents[k2].interpretation == "usr"


def test_no_system_degenerate(cache):
    k = _key(HA, CONST, b"\x01")
    _write_user({k: _record(CONST, "k", "usr")})
    assert SS.validated_system_db() is None
    assert S.Semantic_DB[k].interpretation == "usr"
    assert list(S.Semantic_DB.iter_items()) == [(k, _record(CONST, "k", "usr"))]


def test_empty_user_reads_come_from_system(cache):
    k = _key(HA, CONST, b"\x01")
    _mk_system(cache, records={k: _record(CONST, "k", "sys")})
    assert S.Semantic_DB[k].interpretation == "sys"
    assert [kk for kk, _ in S.Semantic_DB.iter_items()] == [k]


# ---------------------------------------------------------------------------
# §9.3  Discovery precedence and the manifest gate
# ---------------------------------------------------------------------------

def test_find_system_db_precedence(cache, tmp_path):
    _mk_system(cache)                                        # the `pulled` copy
    payload = tmp_path / "prefix" / "share" / "isabelle-semantic-data"
    payload.mkdir(parents=True)
    (payload / SS.MANIFEST_NAME).write_text(json.dumps(
        {"schema_version": SS.SCHEMA_VERSION, "vector_format": SS.VECTOR_FORMAT}))

    found = SS.find_system_db()
    assert found is not None and found.source == "conda"
    assert found.path == str(payload)

    (payload / SS.MANIFEST_NAME).unlink()                    # conda payload gone
    found = SS.find_system_db()
    assert found is not None and found.source == "pulled"
    assert found.path == str(cache / "system")

    (cache / "system" / SS.MANIFEST_NAME).unlink()
    assert SS.find_system_db() is None


def test_manifest_gate_treats_incompatible_as_absent(cache, capfd):
    k = _key(HA, CONST, b"\x01")
    _mk_system(cache, records={k: _record(CONST, "k", "sys")},
               manifest={"schema_version": "1", "vector_format": SS.VECTOR_FORMAT})
    assert SS.validated_system_db() is None
    assert "WARNING" in capfd.readouterr().err
    assert SS.validated_system_db() is None                  # cached verdict...
    assert capfd.readouterr().err == ""                      # ...warns only once
    assert S.Semantic_DB[k] is None                          # layer really absent


def test_system_db_without_semantics_store_is_absent(cache, capfd):
    sysdir = cache / "system"
    sysdir.mkdir()
    (sysdir / SS.MANIFEST_NAME).write_text(json.dumps(
        {"schema_version": SS.SCHEMA_VERSION, "vector_format": SS.VECTOR_FORMAT}))
    assert SS.validated_system_db() is None
    assert "WARNING" in capfd.readouterr().err


# ---------------------------------------------------------------------------
# §9.2  Tombstones
# ---------------------------------------------------------------------------

def test_tombstone_masks_system_record(cache):
    k = _key(HA, CONST, b"\x01")
    _mk_system(cache, records={k: _record(CONST, "k", "sys")})
    assert S.Semantic_DB[k] is not None                      # visible before
    assert S.Semantic_DB.delete(k) is True                   # tombstone, not txn.delete
    assert _user_raw(k) == S.TOMBSTONE                       # the marker is on disk
    assert S.Semantic_DB[k] is None                          # absent, no fall-through
    assert k not in S.Semantic_DB
    assert S.Semantic_DB.contains([k]) == [False]
    assert S.Semantic_DB.get_many([k]) == [None]
    assert list(S.Semantic_DB.iter_items()) == []            # iteration emits nothing


def test_tombstoning_a_user_only_key_equals_deletion(cache):
    k = _key(HA, CONST, b"\x01")
    _write_user({k: _record(CONST, "k", "usr")})
    assert S.Semantic_DB.delete(k) is True
    assert S.Semantic_DB[k] is None
    assert _user_raw(k) == S.TOMBSTONE


def test_tombstone_of_an_unknown_key_is_inert(cache):
    k = _key(HA, CONST, b"\x01")
    assert S.Semantic_DB.delete(k) is False                  # nothing was visible
    assert S.Semantic_DB[k] is None
    assert list(S.Semantic_DB.iter_items()) == []


def test_tombstone_hides_system_vector(cache):
    k = _key(HA, CONST, b"\x01")
    _mk_system(cache, records={k: _record(CONST, "k", "sys")},
               vectors={STORE: {k: _q15(_basis(0))}})
    store = _mk_vector_store(cache)
    assert store[k] is not None                              # served before
    S.Semantic_DB.delete(k)
    assert store[k] is None                                  # no vector for an absent record
    assert k not in store


def test_delete_experience_drops_vectors_and_index_entries(cache):
    from Isabelle_Semantic_Embedding.experience_index import Experience_Index
    from Isabelle_Semantic_Embedding.experience_store import delete_experience
    uk = _key(xor_theory_prefix([HA]), EXP, b"\x01")
    S.Semantic_DB[uk] = S.SemanticRecord(
        EntityKind.EXPERIENCE, "e", None, "when", None, [("T", HA)], "how", ["pat"])
    store = _mk_vector_store(cache)
    store.put(uk, _basis(0))
    Experience_Index.add(uk, [HA])
    assert uk in Experience_Index.all_keys()

    delete_experience(uk)
    assert _user_raw(uk) == S.TOMBSTONE                      # record tombstoned (L8)
    assert S.Semantic_DB[uk] is None
    assert store[uk] is None                                 # user vector really deleted
    assert uk not in Experience_Index.all_keys()             # user index entry dropped


# ---------------------------------------------------------------------------
# §9.2b  Tombstones vs raw readers and single-layer scans
# ---------------------------------------------------------------------------

def test_raw_readers_survive_tombstones(cache):
    from Isabelle_Semantic_Embedding.experience_index import Experience_Index
    uk_live = _key(xor_theory_prefix([HA]), EXP, b"\x01")
    uk_dead = _key(xor_theory_prefix([HB]), EXP, b"\x02")
    thm_dead = _key(xor_theory_prefix([HA]), THM, b"\x03")
    _write_user({
        uk_live: msgpack.packb((EXP, "live", None, "when", None, [("A", HA)], "how")),
        uk_dead: S.TOMBSTONE,                                # tombstoned experience
        thm_dead: S.TOMBSTONE,                               # tombstoned theorem record
        HA: S.TOMBSTONE,                                     # tombstoned thy-status key
    })

    # cmd_reindex's core completes, and the rebuilt user index omits the dead uk
    assert S.Semantic_DB.rebuild_experience_index() == 1
    assert Experience_Index.all_keys() == {uk_live}

    # fsck's core completes and counts only live records
    cons = S.Semantic_DB.check_consistency()
    assert cons.n_records == 1
    assert cons.experience_keys == {uk_live}
    assert S.Semantic_DB.repair_xor_prefixes(cons.xor_mismatches) == ([], [])

    # thy-status readers: a tombstoned status reads as absent / not finished
    assert S.unpack_thy_status(b"") == {}
    assert S.Semantic_DB.is_thy_interpreted(HA) is False

    # keys_belonging_to decodes only live values (the tombstoned uk_dead, whose
    # old record mentioned HB, must not resurface)
    assert set(S.Semantic_DB.keys_belonging_to({HB})) == set()
    assert set(S.Semantic_DB.keys_belonging_to({HA})) == {uk_live}

    # the migration XOR scan skips tombstones instead of decoding them
    assert S.Semantic_DB._migrate_constituent_records(HA, HB) == 1  # only uk_live moves
    migrated = xor_theory_prefix([HB]) + uk_live[16:]
    assert set(S.Semantic_DB.keys_belonging_to({HB})) == {migrated}


# ---------------------------------------------------------------------------
# §9.2c  Read-modify-write: copy-up-then-modify (policy A)
# ---------------------------------------------------------------------------

def test_update_expr_copies_up_a_system_record(cache):
    k = _key(HA, CONST, b"\x01")
    _mk_system(cache, records={k: _record(CONST, "k", "sys meaning", expr="old")})
    S.Semantic_DB.update_expr(k, "new")
    raw = _user_raw(k)
    assert raw is not None and raw != S.TOMBSTONE            # landed in the user layer
    rec = S.Semantic_DB[k]
    assert rec.expr == "new"
    assert rec.interpretation == "sys meaning"               # untouched fields preserved
    assert rec.name == "k"


def test_update_expr_noops_on_tombstoned_and_absent_keys(cache):
    k = _key(HA, CONST, b"\x01")
    _mk_system(cache, records={k: _record(CONST, "k", "sys", expr="old")})
    S.Semantic_DB.delete(k)
    S.Semantic_DB.update_expr(k, "new")
    assert _user_raw(k) == S.TOMBSTONE                       # still just the tombstone
    missing = _key(HB, CONST, b"\x02")
    S.Semantic_DB.update_expr(missing, "new")
    assert _user_raw(missing) is None                        # nothing materialized


def test_mark_interpreted_continues_system_status(cache):
    _mk_system(cache, records={HA: msgpack.packb(
        {b"input_tokens": 5, b"cost_usd": 1.5, b"finished": False, b"model": "m"})})
    S.Semantic_DB.mark_interpreted(HA)
    st = S.unpack_thy_status(_user_raw(HA))
    assert st[b"finished"] is True
    assert st[b"input_tokens"] == 5                          # continued, not zeroed
    assert st[b"cost_usd"] == 1.5
    assert st[b"model"] == b"m" or st[b"model"] == "m"


def test_mark_interpreted_starts_fresh_on_tombstone(cache):
    _mk_system(cache, records={HA: msgpack.packb({b"input_tokens": 5, b"finished": False})})
    S.Semantic_DB.delete(HA)
    S.Semantic_DB.mark_interpreted(HA)
    st = S.unpack_thy_status(_user_raw(HA))
    assert st[b"finished"] is True
    assert st[b"input_tokens"] == 0                          # the zeroed template


def test_write_cost_accumulates_onto_system_status(cache):
    import Isabelle_Semantic_Embedding.semantic_interpretation as SI
    _mk_system(cache, records={HA: msgpack.packb(
        {b"input_tokens": 10, b"cache_creation_tokens": 0, b"cache_read_tokens": 0,
         b"output_tokens": 2, b"cost_usd": 1.0, b"finished": True, b"model": "m"})})
    task = object.__new__(SI.InterpretationTask)
    task.theory_key = HA
    task.driver = "ClaudeCode"
    task.model = "m"
    task.total_input_tokens = 1
    task.total_cache_creation_tokens = 0
    task.total_cache_read_tokens = 0
    task.total_output_tokens = 4
    task.total_cost_usd = 0.5
    assert task.historical_cost() == (10, 0, 0, 2, 1.0)      # layered read
    total = task.write_cost()
    assert total == (11, 0, 0, 6, 1.5)                       # system values continue
    st = S.unpack_thy_status(_user_raw(HA))
    assert st[b"finished"] is True                           # never defaulted to False
    assert st[b"input_tokens"] == 11
    # Which backend produced it, recorded alongside the model.
    assert st[b"driver"] == b"ClaudeCode" or st[b"driver"] == "ClaudeCode"


def test_mark_thy_embedded_continues_system_status(cache):
    _mk_system(cache, vectors={STORE: {HA: msgpack.packb(
        {b"finished": True, b"total_tokens": 10})}})
    store = object.__new__(S.Semantic_Vector_Store)
    store.path = str(cache / STORE)
    store.emb_provider = _FakeProvider()
    store.dimension = D
    store.connection = None
    assert store.is_thy_embedded(HA) is True                 # layered read
    assert store.thy_embed_tokens(HA) == 10
    store.mark_thy_embedded(HA, total_tokens=5)
    with store._env.begin() as txn:                          # landed in the user store
        st = S.unpack_thy_status(bytes(txn.get(HA)))
    assert st[b"finished"] is True
    assert st[b"total_tokens"] == 15                         # accumulated onward


# ---------------------------------------------------------------------------
# §9.4  Two-layer experience index
# ---------------------------------------------------------------------------

def test_experience_index_union_and_dedup(cache):
    from Isabelle_Semantic_Embedding.experience_index import Experience_Index
    uk_sys = _key(xor_theory_prefix([HA]), EXP, b"\x01")
    uk_usr = _key(xor_theory_prefix([HA]), EXP, b"\x02")
    uk_both = _key(xor_theory_prefix([HA]), EXP, b"\x03")
    _mk_system(cache,
               records={uk_sys: _record(EXP, "s", "when"),
                        uk_both: _record(EXP, "b", "when")},
               index={HA: [uk_sys, uk_both]})
    Experience_Index.add(uk_usr, [HA])
    Experience_Index.add(uk_both, [HA])                      # listed in BOTH indexes

    got = Experience_Index.candidates({HA})
    assert got == {uk_sys, uk_usr, uk_both}                  # union, dedup by uk
    assert Experience_Index.all_keys() == {uk_sys, uk_usr, uk_both}


def test_tombstoned_uk_dies_at_record_read(cache):
    from Isabelle_Semantic_Embedding.experience_index import Experience_Index
    uk = _key(xor_theory_prefix([HA]), EXP, b"\x01")
    _mk_system(cache, records={uk: _record(EXP, "s", "when")}, index={HA: [uk]})
    S.Semantic_DB.delete(uk)
    assert uk in Experience_Index.candidates({HA})           # still listed (L17)...
    assert S.Semantic_DB[uk] is None                         # ...but dies at record read


def test_reindex_touches_only_the_user_index(cache):
    from Isabelle_Semantic_Embedding.experience_index import Experience_Index
    uk_sys = _key(xor_theory_prefix([HA]), EXP, b"\x01")
    uk_usr = _key(xor_theory_prefix([HA]), EXP, b"\x02")
    _mk_system(cache, records={uk_sys: _record(EXP, "s", "when")},
               index={HA: [uk_sys]})
    S.Semantic_DB[uk_usr] = S.SemanticRecord(
        EntityKind.EXPERIENCE, "u", None, "when", None, [("A", HA)], "how", ["p"])
    assert S.Semantic_DB.rebuild_experience_index() == 1     # user records only
    assert Experience_Index.candidates({HA}) == {uk_sys, uk_usr}


# ---------------------------------------------------------------------------
# §9.4b  L23 corollaries: vector residency follows record residency
# ---------------------------------------------------------------------------

def test_system_vector_wins_over_stale_user_cache(cache):
    k = _key(HA, CONST, b"\x01")
    v_sys, v_usr = _basis(0), _basis(1)
    _mk_system(cache, records={k: _record(CONST, "k", "sys")},
               vectors={STORE: {k: _q15(v_sys)}})
    store = _mk_vector_store(cache)
    store.put(k, v_usr)                                      # an older lazy cache fill

    got = store[k]
    assert got is not None
    assert np.dot(got, _basis(0)) > np.dot(got, _basis(1))  # the system one

    results, missing = store._topk_sync(encode_q15(v_sys), [k], 1)
    assert missing == []
    assert results[0][0] == k and results[0][1] > 0.99       # gathered the system vector


def test_user_record_takes_user_vector(cache):
    k = _key(HA, CONST, b"\x01")
    _mk_system(cache, records={k: _record(CONST, "k", "sys")},
               vectors={STORE: {k: _q15(_basis(0))}})
    _write_user({k: _record(CONST, "k", "usr")})             # user re-interpretation
    store = _mk_vector_store(cache)
    store.put(k, _basis(1))                           # its user-layer vector

    got = store[k]
    assert np.dot(got, _basis(1)) > 0.9               # user layer serves


def test_system_record_without_system_vector_missing_then_user_cache(cache):
    k = _key(HA, CONST, b"\x01")
    _mk_system(cache, records={k: _record(CONST, "k", "sys")})   # no vector shipped
    store = _mk_vector_store(cache)
    assert store[k] is None                                  # missing -> _auto_embed's cue
    _, missing = store._topk_sync(encode_q15(_basis(0)), [k], 1)
    assert missing == [k]
    store.put(k, _basis(0))                           # the L14 stand-in fill
    assert store[k] is not None                              # user cache now serves


def test_candidate_collection_counts_system_covered_keys_complete(cache):
    k_sys = _key(HA, CONST, b"\x01")
    k_usr = _key(HA, CONST, b"\x02")
    _mk_system(cache, records={k_sys: _record(CONST, "s", "sys")},
               vectors={STORE: {k_sys: _q15(_basis(0))}})
    _write_user({k_usr: _record(CONST, "u", "usr")})
    store = _mk_vector_store(cache)
    # embed/complete_vector_store filter on contains: the system-covered key is
    # COMPLETE (no user-layer re-embedding), the user-only one is a candidate.
    assert store.contains([k_sys, k_usr]) == [True, False]
