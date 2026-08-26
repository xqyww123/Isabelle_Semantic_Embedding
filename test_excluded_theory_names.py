"""Contract tests for ``excluded_theory_names`` (INFRA_FILTER_REWORK_PLAN §18, D11/D19).

The caching scope is a correctness property, not an optimization detail: one RPC
host serves a whole fleet of Isabelle processes (run_fleet_eval.sh), so the list
must be cached per CONNECTION -- a module-level cache would leak one process's
answer to every other.  And the cache must be uncorruptible by its callers: the
returned list flows into the generic RPC layer three frames down.
"""
import asyncio

import Isabelle_Semantic_Embedding.semantics as S


class _CountingConn:
    """Counts fetches of the exclusion list; any other callback is unexpected."""

    def __init__(self, answer):
        self.answer = answer
        self.n = 0

    async def callback(self, name, arg):
        assert name == "Semantic_Store.excluded_theory_names"
        self.n += 1
        return list(self.answer)


def test_one_fetch_per_connection():
    conn = _CountingConn(["Pure"])
    a = asyncio.run(S.excluded_theory_names(conn))
    b = asyncio.run(S.excluded_theory_names(conn))
    assert a == b == ["Pure"]
    assert conn.n == 1


def test_each_connection_fetches_its_own():
    """The fleet property: two Isabelle processes, two answers, no bleed."""
    conn_a, conn_b = _CountingConn(["Pure"]), _CountingConn(["HOL.Typerep"])
    assert asyncio.run(S.excluded_theory_names(conn_a)) == ["Pure"]
    assert asyncio.run(S.excluded_theory_names(conn_b)) == ["HOL.Typerep"]
    assert (conn_a.n, conn_b.n) == (1, 1)


def test_a_caller_cannot_corrupt_the_cache():
    """Mutating a returned list must not poison later answers on the connection."""
    conn = _CountingConn(["Pure"])
    first = asyncio.run(S.excluded_theory_names(conn))
    first.append("Bogus")
    assert "Bogus" not in asyncio.run(S.excluded_theory_names(conn))
