"""The shielded closure rule eff* (ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md §4)
on the production scan: the assertions of the verification under
`ai-artifacts/eff_shield_verification/` that can be driven through
`interpret_file(dry_run=True)` over an isolated store, plus a random-store
cross-check of the production evaluator against the independent reference
evaluator (`eff_reference.py`, component condensation -- a different shape
from production's iterative Tarjan closure).

Shared fixture and wire helpers come from test_incremental_criteria.py.
"""
import random
from typing import NamedTuple

import msgpack

from eff_reference import eff_entity
from test_incremental_criteria import (isolated_db, _uk, _entry, _put,  # noqa: F401
                                       _dry, DG_A, DG_B)

DG_U = b"\xee" * 16


# --- the wall, on the shapes of the plan ------------------------------------

def test_a_fresh_dependency_becomes_a_wall(isolated_db):
    """A -> B -> C.  A changed (version 9); B absorbed it and was judged
    unchanged (version 1, interpreted_at 9).  Today C is dragged in by A's
    number through B; under eff* B is a wall and C stays fresh."""
    _put("up", "t", DG_U, [], 9, 9)
    _put("a", "t", DG_A, [_uk("up")], 1, 9)
    _put("b", "t", DG_B, [_uk("a")], 1, 1)
    assert _dry([_entry("b", DG_B, [_uk("a")])]) == 0


def test_a_stale_dependency_is_no_wall(isolated_db):
    _put("up", "t", DG_U, [], 9, 9)
    _put("a", "t", DG_A, [_uk("up")], 1, 1)      # interpreted_at 1 < 9: stale
    _put("b", "t", DG_B, [_uk("a")], 1, 1)
    assert _dry([_entry("b", DG_B, [_uk("a")])]) == 1


def test_a_direct_dependency_on_the_changed_entity_is_not_shielded(isolated_db):
    _put("up", "t", DG_U, [], 9, 9)
    _put("a", "t", DG_A, [_uk("up")], 1, 9)      # the wall
    _put("d", "t", DG_B, [_uk("up")], 1, 1)      # depends on `up` directly
    assert _dry([_entry("d", DG_B, [_uk("up")])]) == 1


def test_raw_freshness_phrasing_counterexample(isolated_db):
    """A -> B -> C -> D with a second upstream E of C (eff_shield_verification/
    REPORT.md §2).  E changed once and C absorbed it (version 1, interpreted_at
    2); then A changed and B absorbed it (version 1, interpreted_at 4).  Under
    the recursive phrasing B and C are walls and D stays fresh; the raw
    phrasing (freshness of C tested with today's eff, which still carries A's
    4 through B) would pull D in.  Today's rule pulls in C and D."""
    _put("A", "t", DG_A, [], 4, 4)
    _put("E", "t", DG_U, [], 2, 2)
    _put("B", "t", DG_B, [_uk("A")], 1, 4)
    _put("C", "t", DG_B, [_uk("B"), _uk("E")], 1, 2)
    _put("D", "t", DG_B, [_uk("C")], 1, 1)
    assert _dry([_entry("D", DG_B, [_uk("C")])]) == 0
    assert _dry([_entry("C", DG_B, [_uk("B"), _uk("E")])]) == 0


# --- None / ε / missing --------------------------------------------------------

def test_interpreted_at_none_is_never_a_wall(isolated_db):
    _put("u", "t", DG_U, [], 9, 9)
    _put("d", "t", DG_A, [_uk("u")], 3, None)
    _put("e", "t", DG_B, [_uk("d")], 1, 1)
    assert _dry([_entry("e", DG_B, [_uk("d")])]) == 1


def test_version_none_is_never_a_wall(isolated_db):
    _put("u", "t", DG_U, [], 9, 9)
    _put("d", "t", DG_A, [_uk("u")], None, 20)
    _put("e", "t", DG_B, [_uk("d")], 1, 1)
    assert _dry([_entry("e", DG_B, [_uk("d")])]) == 1


def test_missing_record_contributes_zero(isolated_db):
    _put("e", "t", DG_B, [_uk("gone")], 1, 1)
    assert _dry([_entry("e", DG_B, [_uk("gone")])]) == 0


def test_epsilon_baseline_can_be_a_wall(isolated_db):
    """A wall whose version is the ε baseline is a wall like any other."""
    _put("u", "t", DG_U, [], 9, 9)
    _put("d", "t", DG_A, [_uk("u")], 100, 100)
    _put("e", "t", DG_B, [_uk("d")], 1, 100)
    assert _dry([_entry("e", DG_B, [_uk("d")])]) == 0


# --- random stores against the independent reference -------------------------

class _Rec(NamedTuple):
    version: 'int | None'
    interpreted_at: 'int | None'
    deps: tuple


def _random_store(rng, n=18):
    """Arbitrary (not necessarily reachable) versions and interpreted_at
    values, None fields, keys without a record, and edges to a key that never
    has one."""
    keys = [f"k{i}" for i in range(n)]
    store = {}
    for i, k in enumerate(keys):
        if rng.random() < 0.12:
            continue
        deps = [keys[j] for j in range(n) if j != i and rng.random() < 0.18]
        deps += ["missing"] if rng.random() < 0.2 else []
        store[k] = _Rec(version=rng.choice([None, 0, rng.randint(1, 9)]),
                        interpreted_at=rng.choice([None, 0, rng.randint(1, 9)]),
                        deps=tuple(deps))
    return keys, store


def _epsilon() -> int:
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB
    raw = Semantic_DB._get_raw(Semantic_DB.COUNTER_KEY)
    return msgpack.unpackb(raw) if raw else 1


def _expected_stale(store, keys, epsilon):
    """Production's phase-3 verdict per key, computed with the reference: an
    entry with no record is uncached; otherwise stale iff eff*(E), with E's
    own version read as ε when it is None or 0 (phase 1), exceeds its
    interpreted_at.  Digest and deps match the record, so no other criterion
    fires."""
    by_key = {_uk(k): r._replace(deps=tuple(_uk(d) for d in r.deps))
              for k, r in store.items()}
    n = 0
    for k in keys:
        r = by_key.get(_uk(k))
        if r is None:
            n += 1
            continue
        own = r.version or epsilon
        if eff_entity(by_key, own, r.deps, shielded=True) > (r.interpreted_at or 0):
            n += 1
    return n


def test_production_scan_agrees_with_the_reference_on_random_stores(isolated_db):
    from Isabelle_Semantic_Embedding.semantics import Semantic_DB
    for seed in range(150):
        rng = random.Random(seed)
        keys, store = _random_store(rng)
        for k in keys:
            r = store.get(k)
            if r is None:
                Semantic_DB.delete(_uk(k))       # a leftover from an earlier seed
            else:
                _put(k, "t", DG_A, [_uk(d) for d in r.deps], r.version, r.interpreted_at)
        entries = [_entry(k, DG_A, [_uk(d) for d in store[k].deps] if k in store else [])
                   for k in keys]
        expected = _expected_stale(store, keys, _epsilon())
        assert _dry(entries) == expected, f"seed {seed}"
        # order independence (R1): the shared memo must not make the verdicts
        # depend on the order the entries are walked in
        rng.shuffle(entries)
        assert _dry(entries) == expected, f"seed {seed}, shuffled"
