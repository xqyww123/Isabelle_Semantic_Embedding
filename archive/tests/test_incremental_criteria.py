"""The incremental-invalidation criteria over an ISOLATED store
(CHECK_OUTDATE_PLAN.md step 16, the three new-mechanism assertion groups of
§14: dry run, the staleness criteria with eff propagation and the unified dep
criterion, and the (process id, theory serial) pair).

These criteria are Python-side logic (interpret_file's todo-set scan and the
theory-status predicates), so they are tested HERE, with fabricated wire
entries, an isolated SEMANTIC_DB_DIR and a stub connection -- no Isabelle, no
RPC, no LLM.  The ML half (digest/deps computation, enumeration) is covered by
the batch Test/ session (Test_Sensitivity, Test_All); the end-to-end joint over
the real wire, including the live LLM paths, stays with the interactive
Scratch_*Verify scaffolds at the superproject root.

Isolation follows test_experience_index.py: the store singletons are
class-level, so the cache directory must be repointed (and the singletons
reset) before anything opens an environment.
"""
import asyncio
import logging
import os

import msgpack
import pytest

from Isabelle_RPC_Host.universal_key import EntityKind


@pytest.fixture(scope="module", autouse=True)
def isolated_db(tmp_path_factory):
    """Point the whole database set at a throwaway directory for THIS MODULE.

    Module-scoped on purpose: a session-scoped teardown would leave
    SEMANTIC_DB_DIR set (and the store singleton open on the throwaway
    directory) for every later test file in the same pytest run -- measured,
    that made test_experience_index's lock-contention subprocess write to a
    different store than its parent."""
    dbdir = tmp_path_factory.mktemp("semdb")
    prior = os.environ.get("SEMANTIC_DB_DIR")
    os.environ["SEMANTIC_DB_DIR"] = str(dbdir)
    import Isabelle_Semantic_Embedding.semantics as S
    S.Semantic_DB._close()
    yield str(dbdir)
    S.Semantic_DB._close()
    if prior is None:
        os.environ.pop("SEMANTIC_DB_DIR", None)
    else:
        os.environ["SEMANTIC_DB_DIR"] = prior


class _StubConn:
    """What interpret_file's dry path touches: the host logger handle."""
    class _Server:
        logger = logging.getLogger("test_incremental_criteria")
    server = _Server()


# --- fabricated wire entries -------------------------------------------------

WIP_THY = bytes([0x31]) + b"\x11" * 15          # LSB set: a WIP theory hash
DEP_X = WIP_THY + bytes([int(EntityKind.CONSTANT)]) + b"depX"
DEP_Y = WIP_THY + bytes([int(EntityKind.CONSTANT)]) + b"depY"


def _uk(name: str) -> bytes:
    return WIP_THY + bytes([int(EntityKind.CONSTANT)]) + name.encode()


def _entry(name: str, digest: bytes, deps: list) -> 'object':
    from Isabelle_Semantic_Embedding.semantic_interpretation import Entry
    return Entry(kind=int(EntityKind.CONSTANT), name=name, prop_str="nat",
                 position=("$AFP/T/T.thy", 1, 1), universal_key=_uk(name),
                 semantic_digest=digest, deps=deps)


def _dry(entries) -> int:
    from Isabelle_Semantic_Embedding.semantic_interpretation import interpret_file
    n = asyncio.run(interpret_file(
        _StubConn(), "/tmp/nonexistent.thy", "Draft.Fabricated", WIP_THY,
        entries, dry_run=True))
    assert isinstance(n, int)
    return n


def _put(name: str, interpretation: 'str | None', digest: 'bytes | None',
         deps: 'list | None', version: 'int | None', ia: 'int | None') -> None:
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB, SemanticRecord
    Semantic_DB[_uk(name)] = SemanticRecord(
        EntityKind.CONSTANT, name, "nat", interpretation, None, None, None, None,
        digest, deps, version, ia)


def _rec(name: str):
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB
    return Semantic_DB[_uk(name)]


DG_A = b"\xaa" * 16
DG_B = b"\xbb" * 16


def test_dry_run_counts_and_marks_nothing(isolated_db):
    """§14 dry-run group: the quote counts uncached + stale, writes no status."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB, unpack_thy_status
    entries = [_entry("a", DG_A, [DEP_X]), _entry("b", DG_B, [_uk("a")])]
    assert _dry(entries) == 2                    # both uncached
    assert _dry(entries) == 2                    # stable across reruns
    raw = Semantic_DB._get_raw(WIP_THY)
    assert raw is None or b"process_id" not in unpack_thy_status(raw), \
        "a dry run must not write the (process id, serial) pair"


def _raw_and_counter():
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB
    with Semantic_DB._ensure_env().begin() as txn:
        return (txn.get(_uk("a")), txn.get(Semantic_DB.COUNTER_KEY))


def test_fresh_record_leaves_and_digest_mismatch_reenters(isolated_db):
    """A dry run leaves the record and the counter byte-identical (plan §5.2:
    the scan mints nothing; the gate re-stamps the digest at the write)."""
    entries = [_entry("a", DG_A, [DEP_X]), _entry("b", DG_B, [_uk("a")])]
    _put("a", "described", DG_A, [DEP_X], 1, 1)
    assert _dry(entries) == 1                    # a is cached AND fresh
    bad = bytes([DG_A[0] ^ 0xFF]) + DG_A[1:]
    _put("a", "described", bad, [DEP_X], 1, 1)
    before = _raw_and_counter()
    assert _dry(entries) == 2                    # a is stale again
    assert _raw_and_counter() == before, "a dry run writes no digest, no version, no counter"
    assert _dry(entries) == 2                    # stable


def test_a_changed_dependency_does_not_pull_its_fresh_dependent_in(isolated_db):
    """D13: only a is a seed.  b's record still looks fresh (eff*(b) = 1 =
    interpreted_at) and is a wall until a's verdict; b is enrolled by a
    CHANGED verdict, not by the scan -- the live half of this case is the
    enrolment test of the step-5 file (plan §10, §15.10)."""
    entries = [_entry("a", DG_A, [DEP_X]), _entry("b", DG_B, [_uk("a")])]
    _put("a", "described", DG_A, [DEP_X], 1, 1)
    _put("b", "described", DG_B, [_uk("a")], 1, 1)
    assert _dry(entries) == 0                    # both fresh
    bad = bytes([DG_A[0] ^ 0xFF]) + DG_A[1:]
    _put("a", "described", bad, [DEP_X], 1, 1)
    assert _dry(entries) == 1, "a is the seed; b is wall-shielded until a's verdict"


def test_a_dry_run_refreshes_a_changed_statement_and_nothing_else(isolated_db):
    """§5.3.2 on the dry path: a theory whose only difference is one
    `prop_str`, beside one uncached entry, quotes 1, and still ends with that
    `expr` refreshed -- so an expr-only change is not lost when both n == 0
    guards short-circuit -- while its gate fields stay byte-identical."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB
    _put("a", "described", DG_A, [DEP_X], 1, 1)
    Semantic_DB.delete(_uk("b"))
    entries = [_entry("a", DG_A, [DEP_X])._replace(prop_str="nat ⇒ nat"),
               _entry("b", DG_B, [_uk("a")])]
    assert _dry(entries) == 1
    r = _rec("a")
    assert r.expr == "nat ⇒ nat" and r.interpretation == "described"
    assert (r.semantic_digest, r.version, r.interpreted_at) == (DG_A, 1, 1)


def test_an_empty_wire_statement_keeps_the_stored_one(isolated_db):
    """D19: an empty wire `prop_str` means the statement could not be
    computed, not that the entity has none -- the dry-path refresh leaves the
    record byte-identical (no write, no vector tombstone)."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB
    _put("a", "described", DG_A, [DEP_X], 1, 1)
    Semantic_DB.delete(_uk("b"))
    before = _raw_and_counter()
    entries = [_entry("a", DG_A, [DEP_X])._replace(prop_str=""),
               _entry("b", DG_B, [_uk("a")])]
    assert _dry(entries) == 1
    assert _raw_and_counter() == before and _rec("a").expr == "nat"


def test_a_cached_theorem_is_re_listed_when_its_definition_mints(isolated_db):
    """The `bool(e.deps)` half of the scan's gate-field predicate: a
    theorem-alike entry (no digest, deps present) takes the eff* test like a
    tracked one, so a mint above it re-lists it."""
    _put("up", "t", DG_A, [], 1, 1)
    _put("thm", "t", None, [_uk("up")], 1, 1)
    entries = [_entry("thm", None, [_uk("up")])]
    assert _dry(entries) == 0
    _put("up", "t", DG_A, [], 5, 5)               # minted above the theorem
    assert _dry(entries) == 1


def test_eff_scc_memo_is_order_independent(isolated_db):
    """R1 regression (2026-07-28 review, blocker): eff's memo must be finalized
    SCC-wide.  Shape: r <-> x mutual deps (one SCC), x also depends on h; h was
    bumped to version 5.  Two probes with interpreted_at=2 hang off r and off x.
    True eff over the closure {r, x, h} is 5 > 2, so BOTH probes are stale --
    in either evaluation order.  The pre-Tarjan code memoized r as 1 when the
    x-side probe ran first (the on-stack fold took only r's own version), so
    the r-side probe came out falsely fresh and the count dropped to 1."""
    dg_c, dg_d = b"\xcc" * 16, b"\xdd" * 16
    e_pr = _entry("pr", dg_d, [_uk("r")])
    e_px = _entry("px", dg_d, [_uk("x")])
    for order in ([e_px, e_pr], [e_pr, e_px]):
        # rebuild the store per order: both orders must start from identical state
        _put("r", "t", DG_A, [_uk("x")], 1, 1)
        _put("x", "t", DG_B, [_uk("r"), _uk("h")], 1, 1)
        _put("h", "t", dg_c, [], 5, 5)
        _put("pr", "t", dg_d, [_uk("r")], 1, 2)
        _put("px", "t", dg_d, [_uk("x")], 1, 2)
        assert _dry(order) == 2, \
            f"both probes must be stale regardless of order {order[0].name} first"


def test_unified_dep_criterion_catches_uk_drift(isolated_db):
    """§4.3: with the digest equal, one drifted stored dep uk means stale --
    the dead-edge detector (a WIP<->persistent flip re-keys the target)."""
    entries = [_entry("a", DG_A, [DEP_X, DEP_Y])]
    _put("a", "described", DG_A, [DEP_X, DEP_Y], 1, 1)
    assert _dry(entries) == 0
    drifted = bytes([DEP_X[0] ^ 0xFF]) + DEP_X[1:]
    _put("a", "described", DG_A, [drifted, DEP_Y], 1, 1)
    assert _dry(entries) == 1


def test_never_digested_record_is_stale_but_not_stamped(isolated_db):
    """A record interpreted before digests existed: stale by §4.4, and the scan
    must NOT stamp today's digest onto its old text."""
    entries = [_entry("a", DG_A, [DEP_X])]
    _put("a", "pre-digest text", None, None, None, None)
    assert _dry(entries) == 1
    assert _rec("a").semantic_digest is None, \
        "stamping would freshly certify text written for unknown content"


def test_serial_pair_predicates(isolated_db):
    """§14 serial group, on the store predicates: same pair skips, a foreign
    process id or another serial does not, WIP status carries no finished."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB, unpack_thy_status
    Semantic_DB.mark_interpreted(WIP_THY)        # no pair in hand: must no-op
    assert Semantic_DB._get_raw(WIP_THY) is None
    Semantic_DB.mark_interpreted(WIP_THY, "pid-1", 42)
    assert Semantic_DB.is_thy_interpreted(WIP_THY, "pid-1", 42) is True
    assert Semantic_DB.is_thy_interpreted(WIP_THY, "pid-2", 42) is False
    assert Semantic_DB.is_thy_interpreted(WIP_THY, "pid-1", 43) is False
    assert Semantic_DB.is_thy_interpreted(WIP_THY) is False      # no pair in hand
    st = unpack_thy_status(Semantic_DB._get_raw(WIP_THY))
    assert b"finished" not in st
    # a legacy finished field is dropped on the next mark
    st[b"finished"] = True
    with Semantic_DB._ensure_env().begin(write=True) as txn:
        txn.put(WIP_THY, msgpack.packb(st))
    Semantic_DB.mark_interpreted(WIP_THY, "pid-1", 44)
    assert b"finished" not in unpack_thy_status(Semantic_DB._get_raw(WIP_THY))


def test_embed_side_pair_predicates(isolated_db, tmp_path):
    """The embed-side mirror: is/mark_thy_embedded with a stamp."""
    import Isabelle_Semantic_Embedding.semantics as S
    store = object.__new__(S.Semantic_Vector_Store)
    store.path = str(tmp_path / "vec.lmdb")     # _env is a property over path
    store.connection = None
    stamp = ("pid-1", 42)
    assert store.is_thy_embedded(WIP_THY, stamp) is False
    store.mark_thy_embedded(WIP_THY)             # no stamp: must no-op on WIP
    assert store.is_thy_embedded(WIP_THY, stamp) is False
    store.mark_thy_embedded(WIP_THY, 0, stamp)
    assert store.is_thy_embedded(WIP_THY, stamp) is True
    assert store.is_thy_embedded(WIP_THY, ("pid-1", 43)) is False
    assert store.is_thy_embedded(WIP_THY) is False


def test_eff_scc_fresh_cycle_stays_fresh(isolated_db):
    """Companion of the order-independence case: the SCC-wide value must be
    EXACTLY the max over the closure, not merely large enough.  Same r <-> x
    + external h shape, probes' interpreted_at raised to the closure max (5):
    a fresh cycle must stay fresh, in both evaluation orders."""
    dg_c, dg_d = b"\xcc" * 16, b"\xdd" * 16
    e_pr = _entry("pr", dg_d, [_uk("r")])
    e_px = _entry("px", dg_d, [_uk("x")])
    for order in ([e_px, e_pr], [e_pr, e_px]):
        _put("r", "t", DG_A, [_uk("x")], 1, 1)
        _put("x", "t", DG_B, [_uk("r"), _uk("h")], 1, 1)
        _put("h", "t", dg_c, [], 5, 5)
        _put("pr", "t", dg_d, [_uk("r")], 1, 5)
        _put("px", "t", dg_d, [_uk("x")], 1, 5)
        assert _dry(order) == 0, "a fresh cycle must stay fresh"
