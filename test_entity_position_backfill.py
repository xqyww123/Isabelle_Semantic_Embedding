"""T8 and T11 of ENTITY_POSITION_PLAN.md §12: the backfill's write path.

The two properties that matter and cannot be read off the code:

* **T8 (L6)** -- the backfill leaves every vector store untouched.  It writes
  records with a raw ``txn.put`` precisely to avoid ``Semantic_DB.__setitem__``'s
  unconditional ``invalidate_vectors``, which would tombstone ~1.35M vectors that
  nothing refills incrementally.
* **T11** -- an enumerated key with no record is counted as missing and creates
  nothing.

Isolation follows test_incremental_criteria.py: the store singletons are
class-level, so SEMANTIC_DB_DIR must be repointed (and the singletons reset)
before anything opens an environment.
"""
import os

import lmdb
import pytest

from Isabelle_RPC_Host.theory_hash import is_persistent
from Isabelle_RPC_Host.universal_key import EntityKind


@pytest.fixture(scope="module", autouse=True)
def isolated_db(tmp_path_factory):
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


THY_KEY = bytes([0x30]) + b"\x11" * 15          # LSB clear: a persistent theory hash


def _uk(name: str) -> bytes:
    return THY_KEY + bytes([int(EntityKind.CONSTANT)]) + name.encode()


def test_the_test_key_is_persistent():
    """Guard: the sweep skips non-persistent theories outright, so a WIP key would
    make every assertion below test something else."""
    assert is_persistent(THY_KEY)


def _dump_vector_stores() -> dict:
    from Isabelle_Semantic_Embedding.semantic_embedding import user_vector_store_paths
    out = {}
    for path in user_vector_store_paths():
        env = lmdb.open(path, readonly=True, lock=False)
        try:
            with env.begin() as txn:
                out[path] = {bytes(k): bytes(v) for k, v in txn.cursor()}
        finally:
            env.close()
    return out


def test_backfill_writes_the_position_and_touches_no_vector(isolated_db):
    """T8."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB, SemanticRecord

    uk = _uk("Foo.c")
    # Through the facade, so the record lands exactly as a live collection leaves it.
    Semantic_DB[uk] = SemanticRecord(EntityKind.CONSTANT, "Foo.c", "nat", "the constant c")

    # A vector store with a vector for that key -- what the backfill must not disturb.
    vec_path = os.path.join(isolated_db, "vector_test-model.lmdb")
    env = lmdb.open(vec_path, map_size=1 << 20)
    try:
        with env.begin(write=True) as txn:
            txn.put(uk, b"\x00\x01\x02\x03")
    finally:
        env.close()
    before = _dump_vector_stores()
    assert before[vec_path][uk] == b"\x00\x01\x02\x03"

    hit, missing = Semantic_DB.backfill_positions(THY_KEY, [(uk, ("$AFP/Foo/Bar.thy", 7, 3))])
    assert (hit, missing) == (1, 0)

    rec = Semantic_DB[uk]
    assert rec is not None
    assert rec.position == ("$AFP/Foo/Bar.thy", 7, 3)
    # Everything else is byte-identical.
    assert rec._replace(position=None) == SemanticRecord(
        EntityKind.CONSTANT, "Foo.c", "nat", "the constant c")

    assert Semantic_DB.contains([uk]) == [True]
    assert _dump_vector_stores() == before      # no tombstone, no deletion


def test_backfill_is_idempotent():
    """T12.  Under L9 this is the ENTIRE resume mechanism -- there is no flag and no
    skip, so "resuming" an interrupted sweep means running it again.  A second pass
    must leave the store byte-identical, not merely equivalent."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB

    uk = _uk("Foo.c")
    before_vec = _dump_vector_stores()
    before_rec = Semantic_DB._get_raw(uk)
    hit, missing = Semantic_DB.backfill_positions(THY_KEY, [(uk, ("$AFP/Foo/Bar.thy", 7, 3))])
    assert (hit, missing) == (1, 0)
    assert Semantic_DB._get_raw(uk) == before_rec      # byte-identical
    assert _dump_vector_stores() == before_vec


def test_the_backfill_writes_no_theory_status_record():
    """L9: the pass keeps no bookkeeping.  A theory-status key that did not exist
    before must not exist after -- that is what makes the data the only source of
    truth, and what keeps the published payload free of migration residue."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB

    assert Semantic_DB._get_raw(THY_KEY) is None
    Semantic_DB.backfill_positions(THY_KEY, [(_uk("Foo.c"), ("$AFP/Foo/Bar.thy", 7, 3))])
    assert Semantic_DB._get_raw(THY_KEY) is None


def test_a_key_with_no_record_is_counted_and_creates_nothing():
    """T11.  An enumerated entity legitimately has no record when it was never
    interpreted; the backfill must not conjure one."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB

    absent = _uk("Foo.never_interpreted")
    assert Semantic_DB.contains([absent]) == [False]
    hit, missing = Semantic_DB.backfill_positions(THY_KEY, [(absent, ("$AFP/Foo/Bar.thy", 1, 1))])
    assert (hit, missing) == (0, 1)
    assert Semantic_DB.contains([absent]) == [False]
    assert Semantic_DB[absent] is None


def test_a_position_of_none_is_stored_as_none():
    """§10: an entity with no source position keeps None -- nothing is guessed."""
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB, SemanticRecord

    uk = _uk("Foo.dynamic_member")
    Semantic_DB[uk] = SemanticRecord(EntityKind.CONSTANT, "Foo.dynamic_member", "nat", "d")
    hit, missing = Semantic_DB.backfill_positions(THY_KEY, [(uk, None)])
    assert (hit, missing) == (1, 0)
    rec = Semantic_DB[uk]
    assert rec is not None and rec.position is None


# --- T13: the completeness scan (ENTITY_POSITION_PLAN.md §8.4) ---

WIP_THY = bytes([0x31]) + b"\x11" * 15          # LSB set: a WIP theory hash


def test_the_completeness_scan_counts_the_right_things():
    """T13.  The scan's two traps, both of which would silently invert its verdict:

    * a 13-field record whose position is None has been REACHED (None is the
      permanent, correct value for every §10 case) and must not count as outstanding;
    * WIP-prefixed and EXPERIENCE records can never be reached by any sweep, and must
      not sit in the denominator.
    """
    import msgpack
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB
    from migrate_entity_positions import _scan, _scan_line

    def put(key: bytes, n_fields: int, position=None) -> None:
        vals = [int(EntityKind.CONSTANT), "n", None, "sem"] + [None] * (n_fields - 4)
        if n_fields >= 13:
            vals[12] = position
        with Semantic_DB._ensure_env().begin(write=True) as txn:
            txn.put(key, msgpack.packb(vals))

    put(_uk("Scan.outstanding"), 12)                              # not reached
    put(_uk("Scan.legacy"), 8)                                    # not reached, older stratum
    put(_uk("Scan.done"), 13, ("$AFP/A/B.thy", 1, 1))             # reached, has a position
    put(_uk("Scan.done_but_none"), 13, None)                      # reached, legitimately None
    put(WIP_THY + bytes([int(EntityKind.CONSTANT)]) + b"w", 12)    # unreachable: WIP
    put(THY_KEY + bytes([int(EntityKind.EXPERIENCE)]) + b"x", 8)   # unreachable: experience

    c = _scan()
    assert c["reachable_short"] == 2          # outstanding + legacy, NOT done_but_none
    assert c["wip"] == 1
    assert c["experience"] == 1
    assert c["with_position"] >= 1
    assert "short and reachable 2" in _scan_line(c)
