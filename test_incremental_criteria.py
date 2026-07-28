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
                 line_number=1, universal_key=_uk(name),
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


def test_fresh_record_leaves_and_digest_mismatch_reenters(isolated_db):
    entries = [_entry("a", DG_A, [DEP_X]), _entry("b", DG_B, [_uk("a")])]
    _put("a", "described", DG_A, [DEP_X], 1, 1)
    assert _dry(entries) == 1                    # a is cached AND fresh
    # corrupt the stored digest: stale again, and phase 1 bumps + restamps
    bad = bytes([DG_A[0] ^ 0xFF]) + DG_A[1:]
    _put("a", "described", bad, [DEP_X], 1, 1)
    assert _dry(entries) == 2
    r = _rec("a")
    assert r.semantic_digest == DG_A, "the scan re-stamps the wire digest"
    assert r.version is not None and r.version > 1, "a genuine change bumps"
    v_after = r.version
    assert _dry(entries) == 2                    # stable (eff > interpreted_at)
    assert _rec("a").version == v_after, "no second bump on an equal digest"


def test_eff_propagates_through_the_dep_edge(isolated_db):
    entries = [_entry("a", DG_A, [DEP_X]), _entry("b", DG_B, [_uk("a")])]
    _put("a", "described", DG_A, [DEP_X], 1, 1)
    _put("b", "described", DG_B, [_uk("a")], 1, 1)
    assert _dry(entries) == 0                    # both fresh
    bad = bytes([DG_A[0] ^ 0xFF]) + DG_A[1:]
    _put("a", "described", bad, [DEP_X], 1, 1)
    assert _dry(entries) == 2, \
        "corrupting only a must pull b in through its dep edge (eff)"


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
