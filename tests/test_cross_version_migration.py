"""Per-entity migration of persistent theories across Isabelle versions
(ai-artifacts/CROSS_VERSION_MIGRATION_PLAN.md).  No Isabelle, no API.
Run with  python -m pytest contrib/Semantic_Embedding/tests/test_cross_version_migration.py
"""
import asyncio

import msgpack
import pytest

import Isabelle_Semantic_Embedding.migration as M
import Isabelle_Semantic_Embedding.semantic_interpretation as SI
import Isabelle_Semantic_Embedding.semantics as S
from Isabelle_RPC_Host.universal_key import EntityKind
from Isabelle_RPC_Host.universal_key import xor_theory_prefix
from layered_db import (  # noqa: F401
    cache, reg, reset_singletons, thm, write_user, write_user_registry)

# Every test runs on an isolated store: the migration context reads the registry
# and the store as soon as it is built, and `end_migration` writes.
pytestmark = pytest.mark.usefixtures("cache")

Record = S.SemanticRecord
OLD = thm([bytes.fromhex("22" * 16)], b"old")
NEW = thm([bytes.fromhex("24" * 16)], b"old")


def _full(**over) -> 'S.SemanticRecord':
    """A record with every stored field set."""
    return Record(
        kind=EntityKind.THEOREM, name="Tst.t", expr="P", interpretation="meaning",
        locale_provenance=S.Provenance(b"t" * 32, b"l" * 20, "q"),
        theory_constituents=[("Tst", bytes.fromhex("24" * 16))],
        experience=None, goal_patterns=None, semantic_digest=b"d" * 16, deps=[b"k" * 32],
        version=7, interpreted_at=9, position=("~~/Tst.thy", 3, 1),
        from_collection="Tst.coll", baseline_interpretation="baseline",
        migrated_from=OLD)._replace(**over)


# --- §8: the record field `migrated_from` at index 15 ---

def test_migrated_from_is_the_last_stored_field():
    raw = S.Semantic_DB._encode(_full())
    assert S.RECORD_FIELD_COUNT == 16 == len(msgpack.unpackb(raw))
    assert Record._fields.index("migrated_from") == S.RECORD_FIELD_COUNT - 1
    assert bytes(msgpack.unpackb(raw)[15]) == OLD


def test_codec_round_trip():
    for rec in (_full(), _full(migrated_from=None)):
        assert S.Semantic_DB._decode(S.Semantic_DB._encode(rec)) == rec


def test_fifteen_field_record_reads_migrated_from_none():
    rec = _full()
    old = S.pack_fields(msgpack.unpackb(S.Semantic_DB._encode(rec))[:15])
    assert S.unpack_fields(old)[15] is None
    assert S.Semantic_DB._decode(old) == rec._replace(migrated_from=None)


def test_store_keeps_migrated_from(cache):  # noqa: F811
    S.Semantic_DB[NEW] = _full()
    reset_singletons()                  # read back from disk, not from a cache
    rec = S.Semantic_DB[NEW]
    assert rec is not None and rec.migrated_from == OLD


def test_update_of_a_fifteen_field_record_writes_sixteen(cache):  # noqa: F811
    rec = _full(migrated_from=None)
    old = S.pack_fields(msgpack.unpackb(S.Semantic_DB._encode(rec))[:15])
    with S.Semantic_DB._ensure_env().begin(write=True) as txn:
        txn.put(NEW, old)
    with S.Semantic_DB._ensure_env().begin(write=True) as txn:
        S.Semantic_DB._put_fields(txn, NEW, {"interpreted_at": 11})
    with S.Semantic_DB._ensure_env().begin() as txn:
        vals = msgpack.unpackb(txn.get(NEW))
    assert len(vals) == 16 and vals[15] is None and vals[11] == 11


# --- §3.1: the migration context and its handle ---

class _Connection:
    """What `begin_migration` uses of a connection: its `on_close` list, and the
    base theory names `excluded_theory_names` caches on it."""

    class server:                       # a host that logs to no file
        logger = __import__("logging").getLogger("test_cross_version_migration")

    def __init__(self) -> None:
        self.on_close: list = []
        self._excluded_theory_names = ("Pure",)

    def close(self) -> None:
        for release in self.on_close:
            release()


PAIRS = [("Pure", bytes.fromhex("22" * 16)), ("Tst.A", bytes.fromhex("24" * 16))]


def test_context_lives_as_long_as_its_connection(cache):  # noqa: F811
    conn = _Connection()
    handle = asyncio.run(M._begin_migration([False, PAIRS], conn))  # type: ignore[arg-type]
    ctx = M.migration_context(handle)
    assert ctx is not None and not ctx.dry_run and ctx.theories == PAIRS
    assert asyncio.run(M._end_migration(handle, conn)) == [  # type: ignore[arg-type]
        "Experiences: 0 moved to the new generation, 0 were already moved."]
    assert M.migration_context(handle) is ctx         # end_migration does not drop it
    conn.close()
    with pytest.raises(RuntimeError, match="has closed"):
        M.migration_context(handle)


def test_handles_are_not_reused(cache):  # noqa: F811
    a, b = _Connection(), _Connection()
    h1 = asyncio.run(M._begin_migration([True, PAIRS], a))  # type: ignore[arg-type]
    a.close()
    h2 = asyncio.run(M._begin_migration([True, PAIRS], b))  # type: ignore[arg-type]
    assert h1 != h2
    ctx = M.migration_context(h2)
    assert ctx is not None and ctx.dry_run
    b.close()


def _wire(handle) -> list:
    return ["/x/A.thy", "Tst.A", b"\x24" * 16, "", handle, []]


def test_payload_handle(cache):  # noqa: F811
    assert SI._payload_of_wire(_wire(None))[4] is None   # switch off, or a WIP theory
    conn = _Connection()
    handle = asyncio.run(M._begin_migration([False, PAIRS], conn))  # type: ignore[arg-type]
    assert SI._payload_of_wire(_wire(handle))[4] is M.migration_context(handle)
    conn.close()
    with pytest.raises(RuntimeError, match="has closed"):
        SI._payload_of_wire(_wire(handle))


def test_payload_from_an_older_ml_half_is_refused():
    with pytest.raises(RuntimeError, match="expected 6"):
        SI._payload_of_wire(_wire(None)[:4] + [[]])


# --- §3.3: the old hash of a long name (A3) ---

def H(byte: int) -> bytes:
    """A theory hash; an odd first byte is a WIP hash."""
    return bytes([byte]) * 16


FINISHED = msgpack.packb({"finished": True})


def _registry(entries: 'list[tuple[bytes, str, int]]', finished: 'list[bytes]' = ()) -> None:
    write_user_registry({h: reg(name, ts) for h, name, ts in entries})
    write_user({h: FINISHED for h in finished})


def test_old_hash_prefers_the_newest_finished(cache):  # noqa: F811
    _registry([(H(2), "A", 1), (H(4), "A", 2), (H(6), "A", 3), (H(8), "A", 9)],
              finished=[H(2), H(4)])
    assert M.old_hashes({"A": H(8)}) == {"A": H(4)}


def test_old_hash_falls_back_to_the_newest_persistent(cache):  # noqa: F811
    _registry([(H(2), "A", 1), (H(4), "A", 2), (H(5), "A", 3), (H(8), "A", 9)])
    assert M.old_hashes({"A": H(8)}) == {"A": H(4)}   # the WIP H(5) is newer, ignored


def test_old_hash_excludes_the_current_hash(cache):  # noqa: F811
    _registry([(H(2), "A", 1), (H(8), "A", 9)], finished=[H(8)])
    assert M.old_hashes({"A": H(8)}) == {"A": H(2)}
    assert M.old_hashes({"B": H(10)}) == {}           # no registry entry at all
    _registry([(H(10), "B", 5)])
    assert M.old_hashes({"B": H(10)}) == {}           # only its current hash


def test_old_hash_ignores_a_tombstoned_status(cache):  # noqa: F811
    _registry([(H(2), "A", 1), (H(4), "A", 2), (H(8), "A", 9)], finished=[H(2)])
    write_user({H(4): S.TOMBSTONE})
    assert M.old_hashes({"A": H(8)}) == {"A": H(2)}


# --- §3.4: the forward map and the predecessor map ---

PURE0, PURE1 = H(0x20), H(0x22)       # Pure in two Isabelle versions
A0, A1 = H(0x40), H(0x42)             # a changed theory
U = H(0x60)                           # a theory with one hash in both
W = H(0x81)                           # a WIP cone theory


BASES = {"Pure", "HOL.Code_Generator", "HOL.Code_Evaluation", "HOL.Typerep"}


def _ctx(theories, dry_run=False) -> 'M.MigrationContext':
    return M.MigrationContext(dry_run, theories, BASES)


def _thm_record(consts: 'list[tuple[str, bytes]]') -> bytes:
    return S.Semantic_DB._encode(Record(
        EntityKind.THEOREM, "Tst.t", "P", "meaning", theory_constituents=consts))


def test_forward_map_over_cone_and_base_theories(cache):  # noqa: F811
    _registry([(PURE0, "Pure", 1), (A0, "Tst.A", 1), (U, "Tst.U", 1), (PURE1, "Pure", 2),
               (A1, "Tst.A", 2), (H(0x84), "Tst.W", 1)],
              finished=[PURE0, A0, U, H(0x84)])
    # W was persistent and finished, and is now being edited: its current hash is WIP.
    ctx = _ctx([("Pure", PURE1), ("Tst.A", A1), ("Tst.U", U), ("Tst.W", W)])
    assert ctx.forward == {PURE0: PURE1, A0: A1}      # U has no other hash; W is WIP
    assert ctx.inverse == {PURE1: PURE0, A1: A0}


def test_a3_is_evaluated_once_per_run(cache, monkeypatch):  # noqa: F811
    _registry([(PURE0, "Pure", 1), (PURE1, "Pure", 2)], finished=[PURE0])
    calls = []
    real = M.theory_hash_registry.iter_items
    monkeypatch.setattr(M.theory_hash_registry, "iter_items",
                        lambda: calls.append(1) or real())
    ctx = _ctx([("Pure", PURE1)])
    asyncio.run(ctx.predecessors()), asyncio.run(ctx.predecessors())
    assert len(calls) == 1


def _upgrade_store():
    """Pure and A re-hash, U does not: theorems over {Pure}, {Pure, A}, {Pure, U},
    {U}, and one WIP theorem over {Pure, W'}."""
    _registry([(PURE0, "Pure", 1), (A0, "Tst.A", 1), (U, "Tst.U", 1), (PURE1, "Pure", 2),
               (A1, "Tst.A", 2)], finished=[PURE0, A0, U])
    recs = {}
    for consts, sfx in ([[("Pure", PURE0)], b"p"],
                        [[("Pure", PURE0), ("Tst.A", A0)], b"pa"],
                        [[("Pure", PURE0), ("Tst.U", U)], b"pu"],
                        [[("Tst.U", U)], b"u"],
                        [[("Pure", PURE0), ("Tst.W", H(0x85))], b"pw"]):
        recs[thm([h for _, h in consts], sfx)] = _thm_record(consts)
    write_user(recs)
    return recs


def test_predecessor_map_rewrites_every_mapped_constituent(cache):  # noqa: F811
    _upgrade_store()
    ctx = _ctx([("Pure", PURE1), ("Tst.A", A1), ("Tst.U", U)])
    assert asyncio.run(ctx.predecessors()) == {
        thm([PURE1], b"p"): thm([PURE0], b"p"),
        thm([PURE1, A1], b"pa"): thm([PURE0, A0], b"pa"),
        thm([PURE1, U], b"pu"): thm([PURE0, U], b"pu")}   # {U} unmapped, WIP key skipped


def test_same_isabelle_refresh_finds_predecessors(cache):  # noqa: F811
    # Pure keeps its hash; only A re-hashes.
    _registry([(PURE0, "Pure", 1), (A0, "Tst.A", 1), (A1, "Tst.A", 2)],
              finished=[PURE0, A0])
    old = thm([PURE0, A0], b"pa")
    write_user({old: _thm_record([("Pure", PURE0), ("Tst.A", A0)])})
    ctx = _ctx([("Pure", PURE0), ("Tst.A", A1)])
    assert ctx.forward == {A0: A1}
    assert asyncio.run(ctx.predecessors()) == {thm([PURE0, A1], b"pa"): old}


def test_predecessor_tie_break_keeps_fewer_rewritten_constituents(cache):  # noqa: F811
    # Plan §3.4's example: Y re-hashes in release k only, Z in release k+1 only.
    Y0, Y1, Z0, Z2 = H(0x10), H(0x12), H(0x30), H(0x32)
    _registry([(Y0, "Tst.Y", 1), (Z0, "Tst.Z", 1), (Y1, "Tst.Y", 2), (Z2, "Tst.Z", 3)],
              finished=[Y0, Z0, Y1])
    older = thm([Y0, Z0], b"s")                       # release k-1
    newer = thm([Y1, Z0], b"s")                       # release k
    write_user({older: _thm_record([("Tst.Y", Y0), ("Tst.Z", Z0)]),
                newer: _thm_record([("Tst.Y", Y1), ("Tst.Z", Z0)])})
    # Release k+1: Y keeps Y1, so its old hash is Y0; Z's is Z0.  Both records
    # rewrite to {Y1, Z2}: the older one through two constituents, the newer one
    # through one.
    ctx = _ctx([("Tst.Y", Y1), ("Tst.Z", Z2)])
    assert ctx.forward == {Y0: Y1, Z0: Z2}
    assert asyncio.run(ctx.predecessors()) == {thm([Y1, Z2], b"s"): newer}


def test_predecessor_map_is_built_once_and_recomputed_alike(cache, monkeypatch):  # noqa: F811
    _upgrade_store()
    theories = [("Pure", PURE1), ("Tst.A", A1), ("Tst.U", U)]
    scans = []
    real = M.predecessor_map
    monkeypatch.setattr(M, "predecessor_map", lambda fwd: scans.append(1) or real(fwd))
    ctx = _ctx(theories, dry_run=True)
    first = asyncio.run(ctx.predecessors())
    assert asyncio.run(ctx.predecessors()) is first and len(scans) == 1
    assert asyncio.run(_ctx(theories).predecessors()) == first   # a crash re-run: the same map


# --- §3.5-3.7: predecessor, dependency check, copy ---

P0, P1 = H(0xa0), H(0xa2)      # Pure
T0, T1 = H(0xb0), H(0xb4)      # the theory being migrated (P0^T0 != P1^T1)
D0, D1 = H(0xc0), H(0xc2)      # an ancestor of T
CONST, TYPE, METHOD, COLL = (EntityKind.CONSTANT, EntityKind.TYPE, EntityKind.METHOD,
                             EntityKind.THEOREM_COLLECTION)
DG, DG2 = b"g" * 16, b"h" * 16  # two semantic digests


def ns(h: bytes, kind: EntityKind, name: str) -> bytes:
    return h + bytes([int(kind)]) + name.encode()


def trec(kind: EntityKind, name: str, *, digest=DG, deps=None, version=None, ia=None,
         interp="meaning", baseline=None, migrated_from=None, expr="P",
         consts=None) -> 'S.SemanticRecord':
    return Record(kind, name, expr, interp, semantic_digest=digest, deps=deps,
                  version=version, interpreted_at=ia, baseline_interpretation=baseline,
                  migrated_from=migrated_from, theory_constituents=consts)


def ent(kind: EntityKind, name: str, key: bytes, *, digest=DG, deps=(), prop="P"):
    return SI.Entry(int(kind), name, prop, None, key, semantic_digest=digest, deps=list(deps))


def _world(records: 'dict[bytes, S.SemanticRecord | bytes]', finished=(P0, T0, D0)) -> None:
    """Registry: P0, T0, D0 older and finished, P1, T1, D1 current; `records`
    (a bytes value is written raw)."""
    _registry([(P0, "Pure", 1), (T0, "Tst.T", 1), (D0, "Tst.D", 1),
               (P1, "Pure", 2), (T1, "Tst.T", 2), (D1, "Tst.D", 2)], finished=list(finished))
    write_user({k: r if isinstance(r, bytes) else S.Semantic_DB._encode(r)
                for k, r in records.items()})


def _migrate(entries, dry_run=False, ctx=None):
    ctx = ctx or _ctx([("Pure", P1), ("Tst.T", T1), ("Tst.D", D1)], dry_run)
    rec_cache = dict(zip((e.universal_key for e in entries),
                         S.Semantic_DB.get_many([e.universal_key for e in entries])))
    reasons = asyncio.run(ctx.migrate(entries, rec_cache)).reasons
    return reasons, rec_cache, ctx


def _stored(key: bytes) -> 'S.SemanticRecord | None':
    return S.Semantic_DB[key]


C0, C1 = ns(T0, CONST, "Tst.c"), ns(T1, CONST, "Tst.c")    # a constant of T
X, K = ns(D0, CONST, "Tst.d"), ns(D1, CONST, "Tst.d")      # its dependency, in D


def test_namespace_copy_fields(cache):  # noqa: F811
    _world({C0: trec(CONST, "Tst.c", deps=[C0, X], version=5, ia=7, baseline="base"),
            X: trec(CONST, "Tst.d", deps=[X], version=5, ia=5),
            K: trec(CONST, "Tst.d", deps=[K], version=5, ia=5, migrated_from=X)})
    e = ent(CONST, "Tst.c", C1, deps=[C1, K], prop="nat")
    reasons, rec_cache, _ = _migrate([e])
    assert reasons == {C1: M.Reason.UNCHANGED}
    c = _stored(C1)
    assert c is not None and rec_cache[C1] == c
    assert (c.kind, c.name, c.expr, c.interpretation, c.semantic_digest, c.deps,
            c.version, c.baseline_interpretation, c.migrated_from) == (
        CONST, "Tst.c", "nat", "meaning", DG, [C1, K], 5, "base", C0)
    assert c.interpreted_at == 5                    # eff* over the store and the batch


def test_predecessor_must_be_live_and_digested(cache):  # noqa: F811
    _world({C0: S.TOMBSTONE, ns(T0, TYPE, "Tst.t"): trec(TYPE, "Tst.t", digest=None)})
    reasons, rec_cache, _ = _migrate([ent(CONST, "Tst.c", C1),
                                      ent(TYPE, "Tst.t", ns(T1, TYPE, "Tst.t"))])
    assert set(reasons.values()) == {M.Reason.NO_PREDECESSOR}
    assert all(v is None for v in rec_cache.values())


def test_methods_and_collections_by_statement(cache):  # noqa: F811
    keep, change, empty = (ns(T0, METHOD, "Tst.m"), ns(T0, COLL, "Tst.s"),
                           ns(T0, METHOD, "Tst.ml"))
    _world({keep: trec(METHOD, "Tst.m", digest=None, expr="method_setup m"),
            change: trec(COLL, "Tst.s", digest=None, expr="named_theorems s"),
            empty: trec(METHOD, "Tst.ml", digest=None, expr="")})
    es = [ent(METHOD, "Tst.m", ns(T1, METHOD, "Tst.m"), digest=None, prop="method_setup m"),
          ent(COLL, "Tst.s", ns(T1, COLL, "Tst.s"), digest=None, prop="named_theorems t"),
          ent(METHOD, "Tst.ml", ns(T1, METHOD, "Tst.ml"), digest=None, prop="")]
    reasons, rec_cache, _ = _migrate(es)
    assert [reasons[e.universal_key] for e in es] == [
        M.Reason.UNCHANGED, M.Reason.DEFINITION_CHANGED, M.Reason.UNCHANGED]
    m = rec_cache[es[0].universal_key]
    assert m is not None and m.migrated_from == keep and m.interpretation == "meaning"
    assert (m.semantic_digest, m.deps, m.version, m.interpreted_at,
            m.baseline_interpretation) == (None, None, None, None, None)
    assert rec_cache[es[1].universal_key] is None


def test_changed_digest_copies_the_old_digest(cache):  # noqa: F811
    _world({C0: trec(CONST, "Tst.c", deps=[C0], version=5, ia=5)})
    reasons, rec_cache, _ = _migrate([ent(CONST, "Tst.c", C1, digest=DG2, deps=[C1])])
    c = rec_cache[C1]
    assert reasons[C1] is M.Reason.DEFINITION_CHANGED
    assert c is not None and c.semantic_digest == DG and c.interpreted_at is None
    assert c.baseline_interpretation == "meaning"   # p had none: its interpretation


def _dep_case(dep_rec, *, p_version=5, p_ia=7, dep_in_store=True, extra=None,
              finished=(P0, T0, D0)):
    """T's constant c depends on D's d; p is c's old record.  Returns c's reason."""
    recs = {C0: trec(CONST, "Tst.c", deps=None if p_version is None else [C0, X],
                     version=p_version, ia=p_ia),
            **(extra or {})}
    if dep_in_store and dep_rec is not None:
        recs[K] = dep_rec
    _world(recs, finished=finished)
    reasons, rec_cache, _ = _migrate([ent(CONST, "Tst.c", C1, deps=[C1, K])])
    return reasons[C1], rec_cache[C1]


def test_clause_1_lineage_and_version(cache):  # noqa: F811
    assert _dep_case(trec(CONST, "Tst.d", version=5, ia=5, migrated_from=X))[0] \
        is M.Reason.UNCHANGED


def test_clause_1_minted_dependency_is_changed(cache):  # noqa: F811
    # an ancestor CHANGED verdict: the minted record carries migrated_from None
    reason, c = _dep_case(trec(CONST, "Tst.d", version=9, ia=9))
    assert reason is M.Reason.DEPENDENCY_CHANGED and c is not None and c.interpreted_at is None


def test_clause_1_first_write_tying_interpreted_at_is_changed(cache):  # noqa: F811
    assert _dep_case(trec(CONST, "Tst.d", version=7, ia=7))[0] is M.Reason.DEPENDENCY_CHANGED


def test_clause_1_mint_at_x_after_p_was_written(cache):  # noqa: F811
    assert _dep_case(trec(CONST, "Tst.d", version=9, ia=9, migrated_from=X))[0] \
        is M.Reason.DEPENDENCY_CHANGED


def test_clause_1_copy_from_another_generation(cache):  # noqa: F811
    # d's copy descends from a generation p was not written against
    other = ns(H(0xc4), CONST, "Tst.d")
    assert _dep_case(trec(CONST, "Tst.d", version=5, ia=5, migrated_from=other))[0] \
        is M.Reason.DEPENDENCY_CHANGED


def test_clause_2_switch_off_predecessor(cache):  # noqa: F811
    off = trec(CONST, "Tst.d")                      # version None: a switch-off record
    copy = trec(CONST, "Tst.d", version=3, ia=3, migrated_from=X)
    assert _dep_case(copy, p_version=None, p_ia=None, extra={X: off})[0] \
        is M.Reason.UNCHANGED


def test_clause_2_switch_on_m_is_changed(cache):  # noqa: F811
    on = trec(CONST, "Tst.d", deps=[X], version=2, ia=2)
    copy = trec(CONST, "Tst.d", version=3, ia=3, migrated_from=X)
    assert _dep_case(copy, p_version=None, p_ia=None, extra={X: on})[0] \
        is M.Reason.DEPENDENCY_CHANGED


def test_clause_2_pruned_m_is_changed(cache):  # noqa: F811
    copy = trec(CONST, "Tst.d", version=3, ia=3, migrated_from=X)
    assert _dep_case(copy, p_version=None, p_ia=None)[0] is M.Reason.DEPENDENCY_CHANGED


def test_clause_3_target_never_had_a_record(cache):  # noqa: F811
    assert _dep_case(None)[0] is M.Reason.UNCHANGED                 # D0's status exists


def test_clause_3_switch_off_reads_the_inverse_map(cache):  # noqa: F811
    assert _dep_case(None, p_version=None, p_ia=None)[0] is M.Reason.UNCHANGED


def test_clause_3_pruned_generation_is_changed(cache):  # noqa: F811
    assert _dep_case(None, finished=(P0, T0))[0] is M.Reason.DEPENDENCY_CHANGED


def test_clause_3_base_theory_generation_is_kept(cache):  # noqa: F811
    # X in Pure: no status record, but Pure is a base theory
    global X, K
    saved = X, K
    X, K = ns(P0, CONST, "Pure.d"), ns(P1, CONST, "Pure.d")
    try:
        assert _dep_case(None, finished=(T0,))[0] is M.Reason.UNCHANGED
    finally:
        X, K = saved


def test_clause_3_target_had_a_record_and_has_none_now(cache):  # noqa: F811
    assert _dep_case(None, extra={X: trec(CONST, "Tst.d", version=5, ia=5)})[0] \
        is M.Reason.DEPENDENCY_CHANGED


def test_same_theory_first_write_is_changed(cache):  # noqa: F811
    d0, d1 = ns(T0, CONST, "Tst.e"), ns(T1, CONST, "Tst.e")
    _world({C0: trec(CONST, "Tst.c", deps=[C0, d0], version=5, ia=7)})
    es = [ent(CONST, "Tst.c", C1, deps=[C1, d1]), ent(CONST, "Tst.e", d1, deps=[d1])]
    reasons, _, _ = _migrate(es)
    assert reasons == {C1: M.Reason.DEPENDENCY_CHANGED, d1: M.Reason.NO_PREDECESSOR}


def test_same_theory_copies_take_one_evaluation(cache):  # noqa: F811
    d0, d1 = ns(T0, CONST, "Tst.e"), ns(T1, CONST, "Tst.e")
    _world({C0: trec(CONST, "Tst.c", deps=[C0, d0], version=5, ia=8),
            d0: trec(CONST, "Tst.e", deps=[d0], version=8, ia=8)})
    es = [ent(CONST, "Tst.c", C1, deps=[C1, d1]), ent(CONST, "Tst.e", d1, deps=[d1])]
    reasons, rec_cache, _ = _migrate(es)
    assert set(reasons.values()) == {M.Reason.UNCHANGED}
    c, d = rec_cache[C1], rec_cache[d1]
    assert c is not None and d is not None and (c.interpreted_at, d.interpreted_at) == (8, 8)


def test_p2_mark_is_inherited(cache):  # noqa: F811
    # p marked: version set, interpreted_at None
    reason, c = _dep_case(trec(CONST, "Tst.d", version=5, ia=5, migrated_from=X), p_ia=None)
    assert reason is M.Reason.DEPENDENCY_CHANGED and c is not None
    assert c.version == 5 and c.interpreted_at is None


def test_p2_mark_reached_through_the_persistent_clause(cache):  # noqa: F811
    # T0 is not finished: A3's second clause picks it.  p is marked, and its only
    # target has no record in either generation, so clause 3 calls it unchanged:
    # the mark alone makes e judged.
    th0, th1 = thm([P0, T0], b"t"), thm([P1, T1], b"t")
    _world({th0: trec(EntityKind.THEOREM, "Tst.t", digest=None, deps=[X], version=4,
                      ia=None, consts=[("Pure", P0), ("Tst.T", T0)])}, finished=(P0, D0))
    reasons, rec_cache, ctx = _migrate([ent(EntityKind.THEOREM, "Tst.t", th1, digest=None,
                                            deps=[K])])
    assert ctx.inverse[T1] == T0 and reasons[th1] is M.Reason.DEPENDENCY_CHANGED
    t = rec_cache[th1]
    assert t is not None and t.version == 4 and t.interpreted_at is None


def test_version_none_is_not_a_mark(cache):  # noqa: F811
    th0, th1 = thm([P0, T0], b"t"), thm([P1, T1], b"t")
    _world({C0: trec(CONST, "Tst.c"),                      # switch-off
            th0: trec(EntityKind.THEOREM, "Tst.t", digest=None,      # theorem, no deps
                      consts=[("Pure", P0), ("Tst.T", T0)])})
    es = [ent(CONST, "Tst.c", C1, deps=[C1]),
          ent(EntityKind.THEOREM, "Tst.t", th1, digest=None)]
    reasons, rec_cache, _ = _migrate(es)
    assert set(reasons.values()) == {M.Reason.UNCHANGED}
    t = rec_cache[th1]
    assert t is not None and t.migrated_from == th0 and t.version and t.interpreted_at


def test_theorem_alike_copy_is_judged_by_its_deps(cache):  # noqa: F811
    th0, th1 = thm([P0, T0], b"t"), thm([P1, T1], b"t")
    _world({th0: trec(EntityKind.THEOREM, "Tst.t", digest=None, deps=[X], version=4, ia=6,
                      consts=[("Pure", P0), ("Tst.T", T0)]),
            K: trec(CONST, "Tst.d", version=9, ia=9)})
    reasons, rec_cache, _ = _migrate([ent(EntityKind.THEOREM, "Tst.t", th1, digest=None,
                                          deps=[K])])
    t = rec_cache[th1]
    assert reasons[th1] is M.Reason.DEPENDENCY_CHANGED and t is not None
    assert t.semantic_digest is None and t.version == 4 and t.interpreted_at is None


def test_create_records_is_create_only(cache):  # noqa: F811
    live, dead, new = thm([P1], b"l"), thm([P1], b"d"), thm([P1], b"n")
    write_user({live: S.Semantic_DB._encode(trec(CONST, "live")), dead: S.TOMBSTONE})
    out = S.Semantic_DB.create_records({k: trec(CONST, "copy") for k in (live, dead, new)})
    assert {k: (r.name, created) for k, (r, created) in out.items()} == {
        live: ("live", False), dead: ("copy", True), new: ("copy", True)}
    assert [r.name for r in S.Semantic_DB.get_many([live, dead, new])] == ["live", "copy", "copy"]


def test_migration_step_writes_in_one_transaction(cache, monkeypatch):  # noqa: F811
    _world({C0: trec(CONST, "Tst.c", deps=[C0], version=5, ia=5),
            ns(T0, TYPE, "Tst.t"): trec(TYPE, "Tst.t", deps=[], version=5, ia=5)})
    env = S.Semantic_DB._ensure_env()
    writes = []

    class Env:
        def begin(self, write=False, **kw):
            if write:
                writes.append(1)
            return env.begin(write=write, **kw)

        def __getattr__(self, name):
            return getattr(env, name)

    monkeypatch.setattr(S._Semantic_DB, "_ensure_env", lambda self: Env())
    _migrate([ent(CONST, "Tst.c", C1, deps=[C1]),
              ent(TYPE, "Tst.t", ns(T1, TYPE, "Tst.t"))])
    assert len(writes) == 1


def _vectors(cache, items=None):
    import Isabelle_Semantic_Embedding.semantic_embedding as SE
    from layered_db import STORE
    env = SE._get_lmdb_env(str(cache / STORE))
    with env.begin(write=items is not None) as txn:
        for k, v in (items or {}).items():
            txn.put(k, v)
        return {bytes(k): bytes(v) for k, v in txn.cursor()}


def test_vectors_follow_created_copies_with_the_same_text(cache):  # noqa: F811
    same0, same1 = ns(T0, TYPE, "Tst.t"), ns(T1, TYPE, "Tst.t")
    moved0, moved1 = ns(T0, TYPE, "Tst.u"), ns(T1, TYPE, "Tst.u")
    _world({same0: trec(TYPE, "Tst.t", deps=[], version=5, ia=5),
            moved0: trec(TYPE, "Tst.u", deps=[], version=5, ia=5)})
    _vectors(cache, {same0: b"vs", moved0: b"vm", moved1: b"stale"})
    _migrate([ent(TYPE, "Tst.t", same1, prop="P"), ent(TYPE, "Tst.u", moved1, prop="Q")])
    v = _vectors(cache)
    assert v[same1] == b"vs"                        # same document text: p's vector
    assert v[moved1] == S.TOMBSTONE                 # the text changed: none, not the stale one


def test_dry_run_writes_nothing(cache):  # noqa: F811
    _world({C0: trec(CONST, "Tst.c", deps=[C0], version=5, ia=5)})
    before = {bytes(k): bytes(v) for k, v in S.Semantic_DB._ensure_env().begin().cursor()}
    reasons, rec_cache, _ = _migrate([ent(CONST, "Tst.c", C1, deps=[C1])], dry_run=True)
    assert reasons[C1] is M.Reason.UNCHANGED and rec_cache[C1] is not None
    after = {bytes(k): bytes(v) for k, v in S.Semantic_DB._ensure_env().begin().cursor()}
    assert after == before


def test_removed_generation_comes_back(cache):  # noqa: F811
    _world({C0: trec(CONST, "Tst.c", deps=[C0], version=5, ia=5)})
    e = ent(CONST, "Tst.c", C1, deps=[C1])
    first = _migrate([e])[1][C1]
    S.Semantic_DB.delete(C1)                        # the new generation removed
    again = _migrate([e])[1][C1]
    assert first is not None and again == first


def _dry_vs_live(cache, records, d_entries, t_entries):
    """Reasons of T's entries after D's step, in a dry run and in a live run."""
    _world(records)
    theories = [("Pure", P1), ("Tst.T", T1), ("Tst.D", D1)]
    dry = _ctx(theories, dry_run=True)
    _migrate(d_entries, ctx=dry)
    dry_reasons = _migrate(t_entries, ctx=dry)[0]
    _, d_cache, _ = _migrate(d_entries)
    # D's live run first-writes what got no copy before T runs (its gate's write:
    # migrated_from None, version ε)
    write_user({e.universal_key: S.Semantic_DB._encode(trec(
        EntityKind(e.kind), e.name, deps=e.deps, version=S.Semantic_DB.counter_snapshot(),
        ia=S.Semantic_DB.counter_snapshot())) for e in d_entries if d_cache[e.universal_key] is None})
    live_reasons = _migrate(t_entries)[0]
    return dry_reasons, live_reasons


def test_dry_path_reads_ancestor_outcomes(cache):  # noqa: F811
    p = trec(CONST, "Tst.c", deps=[C0, X], version=5, ia=7)
    cases = {
        # an ancestor copy: clause 1 reads the in-memory copy
        "copied": ({C0: p, X: trec(CONST, "Tst.d", deps=[X], version=5, ia=5)},
                   [ent(CONST, "Tst.d", K, deps=[K])], M.Reason.UNCHANGED),
        # not an entry of D's new generation; its old record carries a digest
        "not enumerated": ({C0: p, X: trec(CONST, "Tst.d", deps=[X], version=5, ia=5)},
                           [], M.Reason.DEPENDENCY_CHANGED),
        # an ancestor target without a predecessor
        "no predecessor": ({C0: p}, [ent(CONST, "Tst.d", K, deps=[K])],
                           M.Reason.DEPENDENCY_CHANGED),
        # an ancestor target whose old record lacks a digest
        "no digest": ({C0: p, X: trec(CONST, "Tst.d", digest=None)},
                      [ent(CONST, "Tst.d", K, deps=[K])], M.Reason.DEPENDENCY_CHANGED),
    }
    for name, (records, d_entries, expected) in cases.items():
        reset_singletons()
        import shutil
        shutil.rmtree(cache)
        cache.mkdir()
        dry, live = _dry_vs_live(cache, records, d_entries,
                                 [ent(CONST, "Tst.c", C1, deps=[C1, K])])
        assert dry == live == {C1: expected}, name


def test_dry_path_target_in_a_finished_theory(cache):  # noqa: F811
    # a same-Isabelle refresh: D kept its hash, so its records stand in the store
    k = ns(D0, CONST, "Tst.d")
    _registry([(P0, "Pure", 1), (D0, "Tst.D", 1), (T0, "Tst.T", 1), (T1, "Tst.T", 2)],
              finished=[P0, D0, T0])
    write_user({C0: S.Semantic_DB._encode(trec(CONST, "Tst.c", deps=[C0, k], version=5, ia=7)),
                k: S.Semantic_DB._encode(trec(CONST, "Tst.d", deps=[k], version=5, ia=5))})
    theories = [("Pure", P0), ("Tst.T", T1), ("Tst.D", D0)]
    e = ent(CONST, "Tst.c", C1, deps=[C1, k])
    dry = _migrate([e], ctx=_ctx(theories, dry_run=True))[0]
    live = _migrate([e], ctx=_ctx(theories))[0]
    assert dry == live == {C1: M.Reason.UNCHANGED}


# --- §3.8: migrated_from through the gate's write ---

def _written(rec, verdict, entry) -> 'S.SemanticRecord':
    task = SI.InterpretationTask(None, "/tmp/T.thy", "Tst.T", T1, [entry])  # type: ignore[arg-type]
    task.rec_cache[entry.universal_key] = rec
    if rec is not None:
        write_user({entry.universal_key: S.Semantic_DB._encode(rec)})
    SI._write(task, 0, rec, verdict, "fresh text")
    out = S.Semantic_DB[entry.universal_key]
    assert out is not None and task.rec_cache[entry.universal_key] == out
    return out


COPY = trec(CONST, "Tst.c", deps=[C1], version=5, ia=None, baseline="base", migrated_from=C0)


def test_unchanged_verdict_keeps_migrated_from(cache):  # noqa: F811
    w = _written(COPY, SI._Verdict.UNCHANGED, ent(CONST, "Tst.c", C1, digest=DG2, deps=[C1]))
    assert (w.migrated_from, w.version, w.baseline_interpretation, w.semantic_digest) == (
        C0, 5, "base", DG2)


def test_changed_verdict_clears_migrated_from(cache):  # noqa: F811
    w = _written(COPY, SI._Verdict.CHANGED, ent(CONST, "Tst.c", C1, digest=DG2, deps=[C1]))
    assert w.migrated_from is None and w.version != 5 and w.baseline_interpretation == "fresh text"


def test_first_and_untracked_writes_carry_no_migrated_from(cache):  # noqa: F811
    assert _written(None, None, ent(CONST, "Tst.c", C1, deps=[C1])).migrated_from is None
    th = thm([P1, T1], b"t")
    seed = trec(EntityKind.THEOREM, "Tst.t", digest=None, deps=[K], version=4, migrated_from=th)
    w = _written(seed, None, ent(EntityKind.THEOREM, "Tst.t", th, digest=None, deps=[K]))
    assert w.migrated_from is None and w.version == 4


# --- §3.8: experiences, at end_migration of a live run ---

from Isabelle_Semantic_Embedding.experience_index import Experience_Index  # noqa: E402

A_0, A_1, B_0, B_W = H(0x50), H(0x54), H(0x70), H(0x71)   # B is being edited: WIP now


def exp_key(hashes: 'list[bytes]', sfx: bytes) -> bytes:
    return xor_theory_prefix(hashes) + bytes([int(EntityKind.EXPERIENCE)]) + sfx.ljust(15, b"\0")


def _experience(consts: 'list[tuple[str, bytes]]', sfx: bytes, vector=b"ve") -> bytes:
    k = exp_key([h for _, h in consts], sfx)
    write_user({k: S.Semantic_DB._encode(Record(
        EntityKind.EXPERIENCE, "exp_" + sfx.decode(), None, "when", theory_constituents=consts,
        experience="how", goal_patterns=["?P"]))})
    Experience_Index.add(k, [h for _, h in consts])
    return k


def _exp_world(cache):
    _registry([(P0, "Pure", 1), (A_0, "Tst.A", 1), (B_0, "Tst.B", 1), (P1, "Pure", 2),
               (A_1, "Tst.A", 2), (B_W, "Tst.B", 3)], finished=[P0, A_0, B_0])
    return _ctx([("Pure", P1), ("Tst.A", A_1), ("Tst.B", B_W)])


def test_experiences_move_once_with_every_mapped_constituent(cache):  # noqa: F811
    ctx = _exp_world(cache)
    both = _experience([("Pure", P0), ("Tst.A", A_0)], b"both")
    base = _experience([("Pure", P0)], b"base")
    mixed = _experience([("Tst.A", A_0), ("Tst.B", B_0)], b"mixed")
    _vectors(cache, {both: b"vb"})
    assert ctx.summary(str(cache)) == ["Experiences: 3 moved to the new generation, 0 were already moved."]
    new = {k: exp_key(hs, k[17:].rstrip(b"\0")) for k, hs in
           ((both, [P1, A_1]), (base, [P1]), (mixed, [A_1, B_0]))}
    for old, k in new.items():
        rec, prev = S.Semantic_DB[k], S.Semantic_DB[old]
        assert rec is not None and prev is not None          # the old record stays
        assert rec.migrated_from == old and rec.experience == "how"
    assert not (new[mixed][0] & 1)                           # a persistent key
    assert Experience_Index.user_bucket(P0) == Experience_Index.user_bucket(A_0) == []
    assert set(Experience_Index.user_bucket(A_1)) == {new[both], new[mixed]}
    assert Experience_Index.user_bucket(B_0) == [new[mixed]]  # reachable while B is WIP
    assert set(Experience_Index.user_bucket(P1)) == {new[both], new[base]}
    assert _vectors(cache)[new[both]] == b"vb"


def test_experience_move_resumes_after_an_interrupt(cache):  # noqa: F811
    ctx = _exp_world(cache)
    old = _experience([("Pure", P0)], b"e")
    new = exp_key([P1], b"e")
    rec = S.Semantic_DB[old]
    assert rec is not None
    # interrupted after phase (1): the record exists, the index still lists the old key
    S.Semantic_DB.create_records({new: rec._replace(theory_constituents=[("Pure", P1)],
                                                    migrated_from=old)})
    assert ctx.summary(str(cache)) == ["Experiences: 0 moved to the new generation, 1 were already moved."]
    assert Experience_Index.user_bucket(P1) == [new] and Experience_Index.user_bucket(P0) == []
    assert ctx.summary(str(cache)) == ["Experiences: 0 moved to the new generation, 0 were already moved."]


def test_experience_whose_record_is_gone_only_leaves_the_index(cache):  # noqa: F811
    ctx = _exp_world(cache)
    old = _experience([("Pure", P0)], b"gone")
    write_user({old: S.TOMBSTONE})
    assert ctx.summary(str(cache)) == ["Experiences: 0 moved to the new generation, 0 were already moved."]
    assert Experience_Index.user_bucket(P0) == [] and S.Semantic_DB[exp_key([P1], b"gone")] is None


def test_dry_run_moves_no_experience(cache):  # noqa: F811
    _exp_world(cache)
    old = _experience([("Pure", P0)], b"e")
    lines = _ctx([("Pure", P1)], dry_run=True).summary(str(cache))
    assert lines[0] == "Experiences: 1 still listed under an old hash."
    assert Experience_Index.user_bucket(P0) == [old]


def test_an_experience_with_a_wip_key_is_not_moved(cache):  # noqa: F811
    ctx = _exp_world(cache)
    old = _experience([("Pure", P0), ("Tst.B", B_W)], b"w")    # written against a WIP B
    assert old[0] & 1
    assert ctx.summary(str(cache)) == ["Experiences: 0 moved to the new generation, 0 were already moved."]
    assert Experience_Index.user_bucket(P0) == [old] and Experience_Index.user_bucket(P1) == []


# --- §3.10: the export strips the build-only fields ---

def test_export_strips_the_build_only_fields(cache, tmp_path):  # noqa: F811
    import lmdb as _lmdb
    import Isabelle_Semantic_Embedding.snapshot_sync as SS
    full = trec(CONST, "Tst.c", deps=[C1], version=5, ia=7, baseline="base",
                migrated_from=C0)._replace(position=("~~/T.thy", 3, 1))
    th = thm([T1], b"t")
    _registry([(T1, "Tst.T", 2)], finished=[T1])
    write_user({C1: S.Semantic_DB._encode(full),
                th: S.Semantic_DB._encode(trec(EntityKind.THEOREM, "Tst.t", digest=None,
                                               deps=[C1], version=5, ia=6,
                                               consts=[("Tst.T", T1)]))})
    SS.export(str(tmp_path / "out"))
    env = _lmdb.open(str(tmp_path / "out" / "semantics.lmdb"), readonly=True, lock=False)
    with env.begin() as txn:
        c = S.Semantic_DB._decode(bytes(txn.get(C1)))
        t = S.Semantic_DB._decode(bytes(txn.get(th)))
        status = bytes(txn.get(T1))
    env.close()
    assert c == full._replace(semantic_digest=None, deps=None, version=None,
                              interpreted_at=None, baseline_interpretation=None,
                              migrated_from=None)
    assert (t.deps, t.version, t.interpreted_at, t.theory_constituents) == (
        None, None, None, [("Tst.T", T1)])
    assert status == FINISHED                       # a theory-status record ships as it is


# --- §3.9: the dry run ---

class _HostConnection:
    """What interpret_file's dry path touches of a connection."""

    class server:
        logger = __import__("logging").getLogger("test_cross_version_migration")


def _snapshot() -> dict:
    with S.Semantic_DB._ensure_env().begin() as txn:
        return {bytes(k): bytes(v) for k, v in txn.cursor()}


def _dry_world():
    """T: c copies unchanged; e has no predecessor; t (a theorem) copies unchanged."""
    th0, th1 = thm([P0, T0], b"t"), thm([P1, T1], b"t")
    _world({C0: trec(CONST, "Tst.c", deps=[C0], version=5, ia=5),
            th0: trec(EntityKind.THEOREM, "Tst.t", digest=None, deps=[C0], version=5,
                      ia=5, consts=[("Pure", P0), ("Tst.T", T0)])})
    return [ent(CONST, "Tst.c", C1, deps=[C1]),
            ent(CONST, "Tst.e", ns(T1, CONST, "Tst.e"), deps=[ns(T1, CONST, "Tst.e")]),
            ent(EntityKind.THEOREM, "Tst.t", th1, digest=None, deps=[C1])]


def _interpret_dry(ctx, entries) -> int:
    n = asyncio.run(SI.interpret_file(_HostConnection(), "/tmp/T.thy", "Tst.T",  # type: ignore[arg-type]
                                      T1, entries, dry_run=True, migration=ctx))
    assert isinstance(n, int)
    return n


def test_dry_run_counts_over_the_in_memory_copies_and_writes_nothing(cache):  # noqa: F811
    entries = _dry_world()
    before = _snapshot()
    ctx = _ctx([("Pure", P1), ("Tst.T", T1)], dry_run=True)
    assert _interpret_dry(ctx, entries) == 1                  # only e is sent
    assert _snapshot() == before
    lines = ctx.summary(str(cache))
    assert lines[:2] == [
        "constant: 2 entities; predecessor found 1; copied 1; to interpret 1",
        "lemma: 1 entities; predecessor found 1; copied 1; to interpret 0"]
    assert lines[2] == "Experiences: 0 still listed under an old hash."
    path = lines[3].removeprefix("Forward map written to ").removesuffix(".")
    rows = [r.split("\t") for r in open(path).read().splitlines()]
    assert rows == [["Pure", P1.hex(), P0.hex()], ["Tst.T", T1.hex(), T0.hex()]]


def test_per_theory_line_and_kind_summary_agree(cache):  # noqa: F811
    f1 = ns(T1, CONST, "Tst.f")      # already has a record: the step leaves it to the scan
    entries = _dry_world() + [ent(CONST, "Tst.f", f1, deps=[f1])]
    write_user({f1: S.Semantic_DB._encode(trec(CONST, "Tst.f", deps=[f1], version=5, ia=5))})
    ctx = _ctx([("Pure", P1), ("Tst.T", T1)], dry_run=True)
    rec_cache = dict(zip((e.universal_key for e in entries),
                         S.Semantic_DB.get_many([e.universal_key for e in entries])))
    step = asyncio.run(ctx.migrate(entries, rec_cache))
    seeds = [1, 3]          # e: no predecessor; f: stale by the scan's own criteria
    assert ctx.count(entries, step, seeds) == (
        "4 entities; copied 2; to interpret 2 (no predecessor 1, definition changed 0, "
        "dependency changed 0, stale 1)")
    kinds = [line.split(": ", 1)[1] for line in ctx.summary(str(cache))[:2]]
    totals = [sum(int(part.split()[-1] if i else part.split()[0])
                  for part in [k.split("; ")[i] for k in kinds]) for i in range(4)]
    assert totals == [4, 2, 2, 2]


def test_dry_run_then_live_run_leaves_what_a_live_run_leaves(cache, tmp_path):  # noqa: F811
    def run(dry_first: bool) -> dict:
        reset_singletons()
        import shutil
        shutil.rmtree(cache)
        cache.mkdir()
        entries = _dry_world()
        theories = [("Pure", P1), ("Tst.T", T1)]
        if dry_first:
            _interpret_dry(_ctx(theories, dry_run=True), entries)
        _migrate(entries, ctx=_ctx(theories))
        return _snapshot()
    assert run(True) == run(False)


@pytest.mark.parametrize("argv, error", [
    (["--dry-run", "Tst.T"], "Error: --dry-run requires --migrate-on-hash-change."),
    (["--migrate-on-hash-change", "--dry-run", "--embed-models", "Q", "Tst.T"],
     "Error: --dry-run and --embed-models are mutually exclusive (a dry run writes nothing)."),
])
def test_dry_run_option_errors(cache, monkeypatch, capsys, argv, error):  # noqa: F811
    import sys as _sys
    import Isabelle_Semantic_Embedding.isabelle_semantics as CLI
    before = sorted(p.name for p in cache.iterdir())
    monkeypatch.setattr(_sys, "argv", ["isabelle-semantics", "collect", *argv])
    with pytest.raises(SystemExit) as exc:
        CLI.main()
    assert exc.value.code == 1 and capsys.readouterr().err.strip() == error
    assert sorted(p.name for p in cache.iterdir()) == before
