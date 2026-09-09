"""The semantic change gate proper (ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md
§5.3.1, §5.4, §10, §13 step 5) driven end to end through `interpret_file`
over an isolated store: enrolment by a CHANGED verdict, the snapshot raise,
the decision table of §3, the prefilter, the judge session and its failure
policy, corrections as second gates, concurrency, cost, and the derived
driver permissions.

The agent backend is the scripted driver of test_interpretation_driver.py;
the judge backend is a scripted judge (one verdict per entity name); the
embedding service is a fake provider whose cosine per pair is scripted.  The
store, fixtures and record helpers come from
test_semantic_change_gate_storage.py.
"""
from __future__ import annotations

import asyncio
import logging
import math
import traceback

import numpy as np
import pytest

import Isabelle_Semantic_Embedding.semantic_interpretation as SI
import Isabelle_Semantic_Embedding.semantics as S
from Isabelle_RPC_Host.universal_key import EntityKind
from Isabelle_Semantic_Embedding.document_text import entity_document_text
from Isabelle_Semantic_Embedding.interpretation_driver import (
    InterpretationDriver,
    accumulate_usage,
)
import Isabelle_Semantic_Embedding.semantic_embedding as SE
from Isabelle_Semantic_Embedding.semantic_embedding import EmbedResult
from Isabelle_Semantic_Embedding.semantic_interpretation import (
    USER_ERROR_MARKER,
    Entry,
    FatalAgentError,
    InterpretationTask,
    JudgeTask,
    RateLimitError,
    RunState,
    _DONE,
    _KIND_PROMPT_LABELS,
    _NOT_ENROLLED,
    mk_answer_tool,
    mk_verdict_tool,
)

from test_interpretation_driver import _ScriptedDriver
from test_semantic_change_gate_storage import (  # noqa: F401  (the `cache` fixture)
    WIP_THY,
    _basis,
    _full_record,
    _gate_fields,
    _mk_vector_store,
    _uk,
    cache,
)

DG = {c: c.encode() * 16 for c in "abcdefghijklmnopqrstuvwxyz"}   # a digest per letter
DG2 = {c: c.upper().encode() * 16 for c in DG}                      # "the digest changed"
THY_KEY = WIP_THY + b"\x00" * 16


# --- entries and records -----------------------------------------------------

def _entry(name: str, digest: bytes | None, deps: list[str] = (),
           kind: EntityKind = EntityKind.CONSTANT, prop: str = "nat") -> Entry:
    return Entry(kind=int(kind), name=f"T.{name}", prop_str=prop,
                 position=("$AFP/T/T.thy", 1, 1), universal_key=_uk(name),
                 semantic_digest=digest, deps=[_uk(d) for d in deps])


def _store(name: str, text: str, digest: bytes | None, deps: list[str] = (),
           version: int | None = 1, interpreted_at: int | None = 1,
           baseline: str | None = "keep") -> S.SemanticRecord:
    """A stored record of `name`: fresh by default (version 1, interpreted_at
    1 on a store whose counter reads 1), with a baseline (the gate wrote
    it) -- `baseline="keep"` means the text itself, None a legacy record."""
    rec = _full_record(name=f"T.{name}", expr="nat", interpretation=text,
                       semantic_digest=digest, deps=[_uk(d) for d in deps],
                       version=version, interpreted_at=interpreted_at,
                       baseline_interpretation=text if baseline == "keep" else baseline)
    S.Semantic_DB[_uk(name)] = rec
    return rec


def _raw(name: str) -> bytes | None:
    with S.Semantic_DB._ensure_env().begin() as txn:
        return txn.get(_uk(name))


def _rec(name: str) -> S.SemanticRecord:
    rec = S.Semantic_DB[_uk(name)]
    assert rec is not None
    return rec


def _counter() -> int:
    return S.Semantic_DB.counter_snapshot()


def _assert_post_run_invariant(entries: list[Entry]) -> None:
    """§10: every stored version and interpreted_at <= the counter."""
    c = _counter()
    for rec in S.Semantic_DB.get_many([e.universal_key for e in entries]):
        if rec is not None:
            assert (rec.version or 0) <= c and (rec.interpreted_at or 0) <= c


# --- the fakes ---------------------------------------------------------------

class _FakeProvider:
    """`emb_provider.embed` for the prefilter: the cosine of a pair is
    scripted by the FRESH interpretation text (`sims[fresh]`, `default`
    otherwise); None yields two zero vectors (not computable), an exception
    is raised from the call.  `scale` multiplies both vectors (a cosine is
    scale-free); `delay` sleeps before answering."""

    def __init__(self, sims=None, default: float = 0.95, scale: float = 1.0,
                 delay: float = 0.0):
        self.sims = sims or {}
        self.default, self.scale, self.delay = default, scale, delay
        self.calls: list[tuple[str, str]] = []
        self.tracing_gated: list[bool] = []      # the embed machinery's tracing gate, per call

    async def embed(self, text: list[str], *, role: str = "document") -> EmbedResult:
        assert role == "document" and len(text) == 2
        self.calls.append((text[0], text[1]))
        self.tracing_gated.append(SE._embed_tracing_gated.get())
        if self.delay:
            await asyncio.sleep(self.delay)
        fresh = text[1].split("\n", 1)[1]
        sim = self.sims.get(fresh, self.default)
        if isinstance(sim, BaseException):
            raise sim
        if sim is None:
            return EmbedResult(np.zeros((2, 2), dtype=np.float32))
        vectors = np.array([[1.0, 0.0], [sim, math.sqrt(1.0 - sim * sim)]],
                           dtype=np.float32) * self.scale
        return EmbedResult(vectors)


class _FakeStore:
    def __init__(self, provider: _FakeProvider):
        self.emb_provider = provider


class _Connection:
    """What `interpret_file` touches on its connection: the host logger and
    the per-connection vector store resolution (`store=None`: the
    resolution raises, as an unconfigured service does)."""

    class server:
        logger = logging.getLogger("test_semantic_change_gate.stub")

    def __init__(self, store):
        self.store = store
        self.store_calls = 0

    async def semantic_vector_store(self):
        self.store_calls += 1
        if self.store is None:
            raise RuntimeError("no embedding service is configured")
        return self.store


class _ScriptedJudge(InterpretationDriver):
    """The judge session stand-in.  `verdicts[name]`: True / False call the
    `verdict` tool, None says nothing (no verdict), an exception is raised
    from the turn.  Every session waits for `hold` (when given) before it
    answers, and yields to the loop once, as a real session does."""

    open_sessions = 0

    def __init__(self, *, verdicts, log, hold, **kw):
        super().__init__(**kw)
        self._verdicts, self._log, self._hold = verdicts, log, hold

    @property
    def _name(self) -> str:
        return self.task.entries[0].name

    async def __aenter__(self):
        _ScriptedJudge.open_sessions += 1
        self._log.append(("judge-enter", self._name, _ScriptedJudge.open_sessions))
        return self

    async def __aexit__(self, *exc):
        _ScriptedJudge.open_sessions -= 1
        self._log.append(("judge-exit", self._name))

    async def run_turn(self, prompt: str) -> None:
        self._log.append(("judge-turn", self._name, prompt))
        await asyncio.sleep(0)
        if self._hold is not None:
            await self._hold.wait()
        v = self._verdicts.get(self._name, True)
        accumulate_usage(self.task, input_tokens=5, output_tokens=1, cost_usd=0.25)
        if isinstance(v, BaseException):
            raise v
        if v is None:
            return
        await self.tools[0].handler({"same": v, "why": "scripted"})


# --- the harness -------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_judge_cap(monkeypatch):
    """Every test runs its own event loop; a semaphore that once waited is
    bound to the loop it waited on."""
    monkeypatch.setattr(SI, "_JUDGE_SESSIONS", asyncio.Semaphore(40))
    _ScriptedJudge.open_sessions = 0


class _Run:
    """One `interpret_file` run with scripted backends.  After `go()`:
    `result`, `task` (the interpretation task), `log` (driver events),
    `provider`, `run_state`, `judged` (entity names, one per judge session)."""

    def __init__(self, tmp_path, monkeypatch):
        self._tmp, self._mp = tmp_path, monkeypatch
        self.log: list = []
        self.task: InterpretationTask | None = None

    def go(self, script, entries, **kw):
        """Run `interpret_file` to completion on a loop of its own."""
        self.result = asyncio.run(self.start(script, entries, **kw))
        if not kw.get("dry_run"):
            _assert_post_run_invariant(list(entries))
        return self.result

    def start(self, script, entries, *, verdicts=None, provider=None, store=True,
              hold=None, prefilter_disabled=False, dry_run=False, judge_cls=_ScriptedJudge):
        """Wire the scripted backends up and return the run as an awaitable
        (bounded by 20 s), for a caller that owns the loop."""
        thy = self._tmp / "T.thy"
        thy.write_text("theory T imports Main begin\nend\n")
        self._mp.setattr(SI, "interpretation_driver_override", "")
        self._mp.delenv("INTERPRETATION_DRIVER", raising=False)
        self.provider = provider or _FakeProvider()
        self.run_state = RunState()
        self.run_state.prefilter_disabled = prefilter_disabled
        self._mp.setattr(SI, "current_run_state", lambda: self.run_state)
        self.connection = _Connection(_FakeStore(self.provider) if store else None)
        verdicts = verdicts or {}

        def make(name, *, model, system_prompt, tools, task, on_context_reset,
                 cli_tools=True):
            if isinstance(task, JudgeTask):
                assert cli_tools is False and system_prompt is SI._JUDGE_SYSTEM_PROMPT
                assert [t.name for t in tools] == ["verdict"] and len(task.entries) == 1
                return judge_cls(verdicts=verdicts, log=self.log, hold=hold,
                                 model=model, system_prompt=system_prompt,
                                 tools=tools, task=task,
                                 on_context_reset=on_context_reset)
            assert cli_tools is True
            self.task = task
            self.log.append(("make", name))
            return _ScriptedDriver(script=script, log=self.log, model=model,
                                   system_prompt=system_prompt, tools=tools,
                                   task=task, on_context_reset=on_context_reset)

        self._mp.setattr(SI, "make_interpretation_driver", make)
        return asyncio.wait_for(SI.interpret_file(
            self.connection, str(thy), "T", THY_KEY, list(entries), dry_run=dry_run), 20)

    def events(self, *kinds: str) -> list:
        return [ev for ev in self.log if ev[0] in kinds]

    @property
    def judged(self) -> list[str]:
        return [ev[1] for ev in self.events("judge-enter")]

    @property
    def turns(self) -> list[str]:
        return [ev[1] for ev in self.events("turn")]

    def asked(self, name: str) -> int:
        """How many interpretation turns named the entity."""
        return sum(1 for p in self.turns if f"T.{name}" in p)


@pytest.fixture
def run(cache, tmp_path, monkeypatch) -> _Run:
    return _Run(tmp_path, monkeypatch)


def _dry(entries) -> int:
    n = asyncio.run(SI.interpret_file(_Connection(None), "/tmp/T.thy", "T", THY_KEY,
                                      list(entries), dry_run=True))
    assert isinstance(n, int)
    return n


def _answer_batch(texts: dict[str, str] | None = None, *, after=None):
    """An action answering every entry of the batch in flight, `texts` by
    short name (default "new <name>"); `after(task)` runs once the answers
    are in (a correction, a wait for a gate)."""
    texts = texts or {}

    async def act(driver, prompt):
        task = driver.task
        items = [{"type": _KIND_PROMPT_LABELS[task.entries[i].kind],
                  "name": task.entries[i].name,
                  "translation": texts.get(task.entries[i].name[2:],
                                           f"new {task.entries[i].name[2:]}")}
                 for i in task.unanswered_in_batch()]
        await mk_answer_tool(task).handler({"interpretations": items})
        accumulate_usage(task, input_tokens=10, output_tokens=1, cost_usd=0.5)
        if after is not None:
            await after(task)
    return act


async def _settled(task, name: str) -> None:
    """Yield until the entity's gate has written (its state is _DONE)."""
    idx = next(i for i, e in enumerate(task.entries) if e.name == f"T.{name}")
    for _ in range(200):
        if task.state[idx] == _DONE:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"the gate of {name} did not finish")


# --- enrolment (D13, §5.3.1) --------------------------------------------------

def _chain(run, verdicts, *, order=("d", "a", "b", "c")):
    """d (unrelated, fresh) | a -> b -> c, all stored fresh with baselines;
    a's digest changed on the wire.  `d` in FIRST position: a not-enrolled
    entry that is not the last one (the step-4 review's requirement)."""
    _store("d", "the d", DG["d"])
    _store("a", "the a", DG["a"])
    _store("b", "the b", DG["b"], deps=["a"])
    _store("c", "the c", DG["c"], deps=["b"])
    by_name = {"d": _entry("d", DG["d"]), "a": _entry("a", DG2["a"]),
               "b": _entry("b", DG["b"], ["a"]), "c": _entry("c", DG["c"], ["b"])}
    entries = [by_name[n] for n in order]
    assert _dry(entries) == 1, "only a is a seed: b and c are wall-shielded until a's verdict"
    res = run.go([_answer_batch() for _ in range(3)], entries, verdicts=verdicts)
    return res, entries


def test_a_changed_verdict_enrols_the_dependent_and_an_unchanged_one_stops_there(run):
    """The live half of test_incremental_criteria's dep-edge test: a's
    CHANGED verdict enrols b (asked in its own later turn), b's UNCHANGED
    verdict enrols nothing; d and c are never asked."""
    res, entries = _chain(run, {"T.a": False, "T.b": True})
    assert len(run.turns) == 2 and [run.asked(n) for n in "abcd"] == [1, 1, 0, 0]
    assert "T.a" in run.turns[0] and "T.b" in run.turns[1] and "T.b" not in run.turns[0]
    assert run.judged == ["T.a", "T.b"]
    assert run.task.state == [_NOT_ENROLLED, _DONE, _DONE, _NOT_ENROLLED]
    assert res.interpretations == ["the d", "new a", "new b", "the c"]
    a, b = _rec("a"), _rec("b")
    assert (a.version, a.interpreted_at, a.baseline_interpretation) == (2, 2, "new a"), \
        "CHANGED: minted, the fresh text is the new baseline"
    assert (b.version, b.interpreted_at, b.baseline_interpretation, b.interpretation) \
        == (1, 2, "the b", "new b"), \
        "UNCHANGED: the version and baseline stand, the snapshot absorbs a's mint, the text is rewritten"
    assert _dry(entries) == 0, "the next scan finds b a wall and c fresh"


def test_enrolment_follows_every_changed_verdict_down_the_chain(run):
    res, entries = _chain(run, {"T.a": False, "T.b": False, "T.c": True})
    assert [run.asked(n) for n in "abcd"] == [1, 1, 1, 0]
    assert len(run.turns) == 3, "one batch per enrolment: each dependent lands after the queue emptied"
    assert run.judged == ["T.a", "T.b", "T.c"]
    assert [_rec(n).version for n in "abc"] == [2, 3, 1]
    assert _rec("c").interpreted_at == 3
    assert _dry(entries) == 0


def test_the_query_tool_refuses_a_dependent_from_the_moment_it_is_enrolled(run, monkeypatch):
    """The mirror of the unrequested-answer rejection: once a's CHANGED
    verdict enrols b, the agent may not look b up (it would be handed the
    stored text of the entity it is re-interpreting)."""
    reached: list = []

    async def raw(connection, tag, name, **kw):
        reached.append(name)
        raise LookupError("no such entity")
    monkeypatch.setattr(S, "query_by_name_raw", raw)
    _chain(run, {"T.a": False, "T.b": True})
    tool = S.mk_query_by_name_tool(run.connection, run.task.enrolled_names)

    async def ask(name):
        return (await tool.handler({"type": "constant", "name": name}))["content"][0]["text"]
    async def both():
        return await ask("T.b"), await ask("T.c")
    refused, other = asyncio.run(both())
    assert run.task.enrolled_names == ["T.a", "T.b"]
    assert refused.startswith('Cannot query "T.b"') and "no such entity" in other


def test_an_answer_for_an_entity_this_run_did_not_ask_for_is_refused(run):
    """§15.8's addressing rule: an answer naming an entry that is not
    enrolled is refused ("Unknown entry"), starts no gate, writes nothing,
    mints nothing, judges nothing.  The seed is a first write, so any judge
    session or counter bump could only be the unrequested answer's.  The
    unrequested entity comes first in wire order (a not-enrolled entry not
    in last position).  Its mirror -- the query tool refusing an entity the
    run DID enrol -- is the test above."""
    _store("d", "the d", DG["d"])                                   # cached and fresh: no seed
    entries = [_entry("d", DG["d"]), _entry("a", DG["a"])]          # a uncached: the only seed
    assert _dry(entries) == 1
    before, c0 = _raw("d"), _counter()
    replies: list[str] = []

    async def act(driver, prompt):
        assert "T.d" not in prompt, "the turn asks for the seed alone"
        ret = await mk_answer_tool(driver.task).handler({"interpretations": [
            {"type": "constant", "name": "T.d", "translation": "unrequested"},
            {"type": "constant", "name": "T.a", "translation": "new a"}]})
        replies.append(ret["content"][0]["text"])
        accumulate_usage(driver.task, input_tokens=10, output_tokens=1, cost_usd=0.5)

    # a CHANGED verdict scripted for the entity that must never be judged:
    # inert on the shipped code, it makes the counter assertion below real
    # under any regression that lets the unrequested answer through
    res = run.go([act], entries, verdicts={"T.d": False})
    assert "Unknown entry: 'constant T.d'" in replies[0]
    assert res.interpretations == ["the d", "new a"]
    assert run.task.state == [_NOT_ENROLLED, _DONE]
    assert _raw("d") == before, "the unrequested entity's record is byte-identical"
    assert _counter() == c0 and run.judged == [] and run.task.judge_cost == SI._NO_COST


def test_every_entity_is_interpreted_at_most_once_in_every_wire_order(run):
    """A seed set holding both a dependency and its dependent (a and b are
    both locally stale), in every permutation with c and d."""
    import itertools
    for order in itertools.permutations("abcd"):
        S.Semantic_DB._close()
        for n in "abcd":
            S.Semantic_DB.delete(_uk(n))
        _store("d", "the d", DG["d"])
        _store("a", "the a", DG["a"])
        _store("b", "the b", DG["b"], deps=["a"])
        _store("c", "the c", DG["c"], deps=["b"])
        by_name = {"d": _entry("d", DG["d"]), "a": _entry("a", DG2["a"]),
                   "b": _entry("b", DG2["b"], ["a"]), "c": _entry("c", DG["c"], ["b"])}
        entries = [by_name[n] for n in order]
        run.log.clear()
        run.go([_answer_batch() for _ in range(3)], entries,
               verdicts={"T.a": False, "T.b": False, "T.c": True})
        assert [run.asked(n) for n in "abcd"] == [1, 1, 1, 0], order
        assert sorted(run.judged) == ["T.a", "T.b", "T.c"], order
        assert run.task.n_interpreted() == 3


# --- the snapshot raise (§5.3.1) ---------------------------------------------

def test_a_dependent_written_before_its_dependency_s_verdict_has_its_snapshot_raised(run):
    """b (uncached, a first write) and a (digest changed) are both seeds; b's
    gate writes at once, a's waits for the judge.  a's CHANGED then raises
    b's interpreted_at to the eff* that includes the mint -- no second
    interpretation of b, nothing enrolled through the raise (c stays out),
    and the next scan finds b fresh."""
    _store("a", "the a", DG["a"])
    _store("c", "the c", DG["c"], deps=["b"])
    entries = [_entry("b", DG["b"], ["a"]), _entry("a", DG2["a"]), _entry("c", DG["c"], ["b"])]
    run.go([_answer_batch()], entries, verdicts={"T.a": False})
    assert len(run.turns) == 1 and run.asked("b") == 1 and run.asked("c") == 0
    b, a = _rec("b"), _rec("a")
    assert (a.version, a.interpreted_at) == (2, 2)
    assert (b.version, b.interpreted_at, b.baseline_interpretation) == (1, 2, "new b"), \
        "b's first write took ε = 1; the raise moved only interpreted_at, to a's new version"
    assert run.task.state == [_DONE, _DONE, _NOT_ENROLLED]
    assert _dry(entries) == 0


def test_the_raise_is_a_gate_field_write_that_keeps_the_vector(run, cache):
    """`update_gate_fields`, not `put_interpretation`: b's text did not
    change, so its embedding vector survives the raise."""
    _store("a", "the a", DG["a"])
    entries = [_entry("b", DG["b"], ["a"]), _entry("a", DG2["a"])]

    async def embed_b_then_wait(task):
        await _settled(task, "b")
        _mk_vector_store(cache).put(_uk("b"), _basis(0))
    run.go([_answer_batch(after=embed_b_then_wait)], entries, verdicts={"T.a": False})
    assert _rec("b").interpreted_at == 2
    assert _mk_vector_store(cache).contains([_uk("b")]) == [True]


def test_a_failed_snapshot_raise_fails_the_run_with_its_own_exception_and_note(run, monkeypatch):
    """§5.4 failures, step 6: the store's exception, noting which entity's
    snapshot was being raised; a's own write (its transaction) had committed."""
    import lmdb

    def full(self, key, **kw):
        raise lmdb.MapFullError("mdb_put: MDB_MAP_FULL: Environment mapsize limit reached")
    monkeypatch.setattr(S._Semantic_DB.Gate_Writer, "update_gate_fields", full)
    _store("a", "the a", DG["a"])
    entries = [_entry("b", DG["b"], ["a"]), _entry("a", DG2["a"])]
    with pytest.raises(lmdb.MapFullError) as e:
        run.go([_answer_batch()], entries, verdicts={"T.a": False})
    assert e.value.__notes__ == ["while raising the interpreted_at snapshot of T.b"]
    assert not isinstance(e.value.__context__, BaseExceptionGroup)
    assert _rec("a").version == 2 and _rec("b").interpreted_at == 1, "a committed; b's raise did not"


# --- the decision table (§3) --------------------------------------------------

def test_a_first_write_needs_neither_prefilter_nor_judge(run):
    entries = [_entry("a", DG["a"])]
    run.go([_answer_batch()], entries)
    assert run.provider.calls == [] and run.judged == []
    assert _gate_fields(_rec("a")) == (DG["a"], [], 1, 1, "new a")


def test_a_legacy_record_is_changed_without_prefilter_or_judge(run):
    """§3 row 2: a record from before the gate (a digest, no baseline) whose
    definition changed: CHANGED at once, never seeding the baseline from the
    stored text."""
    _store("a", "the a", DG["a"], baseline=None)
    _store("b", "the b", DG["b"], deps=["a"])
    entries = [_entry("a", DG2["a"]), _entry("b", DG["b"], ["a"])]
    assert _dry(entries) == 1
    run.go([_answer_batch(), _answer_batch()], entries, verdicts={"T.b": True})
    assert run.provider.calls[0][1].endswith("\nnew b") and len(run.provider.calls) == 1
    assert run.judged == ["T.b"], "a was never judged; b was enrolled by a's mint"
    assert _gate_fields(_rec("a")) == (DG2["a"], [], 2, 2, "new a")


def test_the_prefilter_decides_changed_below_the_threshold_and_defers_above_it(run):
    _store("a", "the a", DG["a"])
    _store("b", "the b", DG["b"])
    entries = [_entry("a", DG2["a"]), _entry("b", DG2["b"])]
    provider = _FakeProvider(sims={"new a": 0.5, "new b": 0.95})
    run.go([_answer_batch()], entries, provider=provider, verdicts={"T.b": True})
    assert run.judged == ["T.b"], "a: CHANGED by the prefilter alone"
    assert _rec("a").version == 2 and _rec("b").version == 1
    assert provider.tracing_gated == [True, True], \
        "the embed machinery's tracing is gated for the prefilter's call"
    # the two document texts: the baseline and the fresh text, each under
    # the entity's CURRENT statement, rendered by the one authority
    e = entries[0]
    assert provider.calls[0] == tuple(
        entity_document_text(S.SemanticRecord(EntityKind.CONSTANT, e.name, e.prop_str, t))
        for t in ("the a", "new a"))


def test_the_prefilter_is_scale_free_and_a_zero_vector_is_not_computable(run):
    """Same directions at norm 20 and norm 1 give the same verdicts; a zero
    vector counts as "could not be computed", so the judge decides."""
    for scale in (1.0, 20.0):
        S.Semantic_DB.delete(_uk("a")); S.Semantic_DB.delete(_uk("z"))
        _store("a", "the a", DG["a"])
        _store("z", "the z", DG["z"])
        entries = [_entry("a", DG2["a"]), _entry("z", DG2["z"])]
        run.log.clear()
        run.go([_answer_batch()], entries,
               provider=_FakeProvider(sims={"new a": 0.5, "new z": None}, scale=scale),
               verdicts={"T.z": True})
        assert run.judged == ["T.z"], scale
        assert (_rec("a").version, _rec("z").version) == (_counter(), 1), scale


def test_the_prefilter_resets_the_tracing_gate_on_both_paths(cache):
    """The reset assertion MUST run in the task that awaited `_prefilter`:
    `asyncio.run` and every `create_task` copy the context (PEP 567), so a
    read after a run returns the default whatever the `finally` does (the
    lesson of test_complete_vector_store.py::test_gate_reset_in_same_task_context)."""
    async def go(provider):
        task = InterpretationTask(None, "/tmp/T.thy", "T", THY_KEY, [_entry("a", DG["a"])],
                                  emb_store=_FakeStore(provider), run_state=RunState())
        await SI._prefilter(task, task.entries[0], "the a", "new a")
        assert provider.tracing_gated == [True]
        assert SE._embed_tracing_gated.get() is False, "reset after the call"
    asyncio.run(go(_FakeProvider()))
    asyncio.run(go(_FakeProvider(sims={"new a": ConnectionError("down")})))


def test_the_judge_s_verdicts_and_its_silence(run, caplog):
    """same -> UNCHANGED; different -> CHANGED; no verdict after one extra
    ask -> CHANGED (the retry prompt is the judge's wording); a session that
    fails -> CHANGED, one session, no recycle, host log only."""
    for n in "abcd":
        _store(n, f"the {n}", DG[n])
    entries = [_entry(n, DG2[n]) for n in "abcd"]
    verdicts = {"T.a": True, "T.b": False, "T.c": None,
                "T.d": FatalAgentError("judge exploded")}
    with caplog.at_level(logging.WARNING, logger=SI.__name__):
        run.go([_answer_batch()], entries, verdicts=verdicts)
    assert (_rec("a").version, _rec("b").version) == (1, 2)
    assert sorted(_rec(n).version for n in "cd") == [3, 4], "both minted, in gate order"
    assert [_rec(n).baseline_interpretation for n in "abcd"] == ["the a", "new b", "new c", "new d"]
    assert run.judged == ["T.a", "T.b", "T.c", "T.d"], "one session each, never recycled"
    c_turns = [ev[2] for ev in run.events("judge-turn") if ev[1] == "T.c"]
    assert len(c_turns) == 2 and c_turns[1].startswith("You have not reported a verdict")
    assert sum("judge gave no verdict for T.c" in r.getMessage() for r in caplog.records) == 0, \
        "the judge's give-up is not a user-visible line"
    assert any("T.d" in r.getMessage() and "verdict CHANGED" in r.getMessage() for r in caplog.records)
    assert not any(r.getMessage().startswith("T:") for r in caplog.records), \
        "no retry warning of the interpretation wording either"


def test_the_theorem_alike_rows_keep_the_stored_version_or_take_epsilon(run):
    """No digest, deps present: no judge, no baseline; the stored version
    stands (5) or, with no record, ε; interpreted_at is eff*."""
    with S.Semantic_DB.gate_write() as w:
        for _ in range(5):
            w.mint()                        # the counter reads 6: stored versions below it
    _store("dep", "the dep", DG["d"], version=3, interpreted_at=3)
    _store("thm1", "the thm1", None, deps=["dep"], version=5, interpreted_at=5, baseline=None)
    entries = [_entry("thm1", None, ["dep"], kind=EntityKind.THEOREM),
               _entry("thm2", None, ["dep"], kind=EntityKind.THEOREM)]
    assert _dry(entries) == 1, "thm1 is fresh (version 5 >= dep's 3), thm2 uncached"
    S.Semantic_DB.delete(_uk("thm1"))
    _store("thm1", "the thm1", None, deps=["dep"], version=5, interpreted_at=None, baseline=None)
    assert _dry(entries) == 2
    run.go([_answer_batch()], entries)
    assert run.judged == [] and run.provider.calls == []
    assert _gate_fields(_rec("thm1")) == (None, [_uk("dep")], 5, 5, None)
    assert _gate_fields(_rec("thm2")) == (None, [_uk("dep")], 6, 6, None), "ε = 6, eff* = max(6, dep's 3)"


def test_the_persistent_and_collection_rows_carry_no_gate_field(run):
    entries = [_entry("p", None, prop="p :: nat"),
               _entry("coll", None, kind=EntityKind.THEOREM_COLLECTION, prop="")]
    run.go([_answer_batch()], entries)
    assert run.judged == []
    for n in ("p", "coll"):
        assert _gate_fields(_rec(n)) == (None, None, None, None, None)
    assert _rec("coll").interpretation == "new coll"


# --- the prefilter's failure policy (D2, §5.4 failures) ---------------------

@pytest.mark.parametrize("delay", [0.0, 0.01])
def test_an_embedding_failure_skips_the_prefilter_for_the_rest_of_the_run(run, monkeypatch, caplog, delay):
    """A failed call sets the flag and prints §12 #5 ONCE -- also when a and
    b were both inside the failing call (`delay`: an embed that yields, as a
    real one does); c, in the next batch, is judged without an embed call."""
    monkeypatch.setattr(SI.AgentTask, "batch_size", 2)
    for n in "abc":
        _store(n, f"the {n}", DG[n])
    entries = [_entry(n, DG2[n]) for n in "abc"]
    down = ConnectionError("embedding service down")
    provider = _FakeProvider(sims={"new a": down, "new b": down}, delay=delay)

    async def answer_c_after_the_failure(driver, prompt):
        for _ in range(200):
            if run.run_state.prefilter_disabled:
                break
            await asyncio.sleep(0.001)
        await _answer_batch()(driver, prompt)
    with caplog.at_level(logging.WARNING, logger=SI.__name__):
        run.go([_answer_batch(), answer_c_after_the_failure], entries, provider=provider,
               verdicts={"T.a": True, "T.b": True, "T.c": True})
    assert len(provider.calls) == (1 if delay == 0 else 2), "no call after the flag is set"
    assert run.run_state.prefilter_disabled
    assert run.judged == ["T.a", "T.b", "T.c"], "the judge decides alone"
    assert [_rec(n).version for n in "abc"] == [1, 1, 1]
    lines = [r.getMessage() for r in caplog.records if "did not respond" in r.getMessage()]
    assert lines == ["The embedding service did not respond: embedding service down"]
    assert sum("prefilter: the embedding call failed" in r.getMessage() for r in caplog.records) \
        == len(provider.calls), "the host log keeps every failure"


def test_a_slow_embedding_call_is_cut_at_the_prefilter_timeout(run, monkeypatch, caplog):
    monkeypatch.setattr(SI, "_PREFILTER_TIMEOUT_S", 0.01)
    _store("a", "the a", DG["a"])
    entries = [_entry("a", DG2["a"])]
    with caplog.at_level(logging.WARNING, logger=SI.__name__):
        run.go([_answer_batch()], entries, provider=_FakeProvider(delay=1.0),
               verdicts={"T.a": False})
    assert run.run_state.prefilter_disabled and run.judged == ["T.a"]
    assert _rec("a").version == 2
    lines = [r.getMessage() for r in caplog.records if "did not respond" in r.getMessage()]
    assert lines == ["The embedding service did not respond: TimeoutError"], \
        "a bare TimeoutError has an empty str; the class name fills the slot"


def test_an_unconfigured_service_means_no_store_and_the_judge_alone(run):
    """The startup check (§5.6) set the flag: no store is resolved, every
    gate is judged, the run completes."""
    _store("a", "the a", DG["a"])
    entries = [_entry("a", DG2["a"])]
    run.go([_answer_batch()], entries, verdicts={"T.a": True}, prefilter_disabled=True)
    assert run.connection.store_calls == 0 and run.judged == ["T.a"]
    assert run.task.emb_store is None and _rec("a").version == 1


def test_a_failing_store_resolution_is_logged_and_the_judge_decides_alone(run, caplog):
    _store("a", "the a", DG["a"])
    entries = [_entry("a", DG2["a"])]
    with caplog.at_level(logging.WARNING, logger=SI.__name__):
        run.go([_answer_batch()], entries, verdicts={"T.a": True}, store=False)
    assert run.connection.store_calls == 1 and run.task.emb_store is None
    assert run.judged == ["T.a"] and not run.run_state.prefilter_disabled
    assert any("no embedding store" in r.getMessage() for r in caplog.records)


# --- corrections (D11) as second gates ----------------------------------------

def _correct(name: str, text: str):
    """`after` hook: wait for the entity's first gate, then resubmit `text`."""
    async def after(task):
        await _settled(task, name)
        await mk_answer_tool(task).handler({"interpretations": [
            {"type": "constant", "name": f"T.{name}", "translation": text}]})
    return after


def test_a_correction_that_changes_the_meaning_mints_and_propagates(run):
    """a is a first write (uncached); its correction re-enters §3 with the
    record the first gate wrote -- a digest and a baseline now -- so it is
    judged: CHANGED mints and enrols b."""
    _store("b", "the b", DG["b"], deps=["a"])
    entries = [_entry("a", DG["a"]), _entry("b", DG["b"], ["a"])]
    run.go([_answer_batch(after=_correct("a", "corrected a")), _answer_batch()], entries,
           verdicts={"T.a": False, "T.b": True})
    assert run.judged == ["T.a", "T.b"] and run.asked("a") == 1 and run.asked("b") == 1
    assert run.provider.calls[0] == tuple(
        entity_document_text(S.SemanticRecord(EntityKind.CONSTANT, "T.a", "nat", t))
        for t in ("new a", "corrected a")), "judged against the first gate's baseline"
    a = _rec("a")
    assert (a.interpretation, a.version, a.baseline_interpretation) == ("corrected a", 2, "corrected a")
    assert run.result.interpretations[0] == "corrected a"
    assert run.task.n_interpreted() == 2, "an entity counts once however many gates it needed"


def test_a_correction_that_keeps_the_meaning_leaves_the_version_standing(run):
    _store("b", "the b", DG["b"], deps=["a"])
    entries = [_entry("a", DG["a"]), _entry("b", DG["b"], ["a"])]
    run.go([_answer_batch(after=_correct("a", "corrected a"))], entries, verdicts={"T.a": True})
    assert run.judged == ["T.a"] and run.asked("b") == 0
    a = _rec("a")
    assert (a.interpretation, a.version, a.baseline_interpretation) == ("corrected a", 1, "new a")


def test_a_byte_identical_resubmission_starts_no_gate(run):
    entries = [_entry("a", DG["a"])]
    seen: dict = {}

    async def resubmit(task):
        await _settled(task, "a")
        seen["raw"] = _raw("a")
        await mk_answer_tool(task).handler({"interpretations": [
            {"type": "constant", "name": "T.a", "translation": "new a"}]})
        assert task.gates_running == 0
    run.go([_answer_batch(after=resubmit)], entries)
    assert run.judged == [] and _raw("a") == seen["raw"]


class _JudgeByText(_ScriptedJudge):
    """Verdicts scripted by the FRESH text (`verdicts[fresh]`) instead of the
    entity name: for a gate that judges two texts of one entity."""

    async def run_turn(self, prompt):
        self._verdicts[self._name] = self._verdicts[self.task.fresh]
        await super().run_turn(prompt)


def test_a_correction_landing_during_the_judge_session_is_judged_not_adopted(run):
    """The gate was judging "v1" when "v2" arrived: it starts over on v2
    instead of writing v1's verdict over v2's text.  Two judge sessions, one
    gate; the stored text and its verdict come from the same text (v1's
    CHANGED would have minted; v2's UNCHANGED leaves the version standing)."""
    _store("a", "the a", DG["a"])
    entries = [_entry("a", DG2["a"])]
    hold = asyncio.Event()

    async def correct_mid_judge(task):
        for _ in range(200):
            if run.events("judge-turn"):
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError("the judge session never started")
        await mk_answer_tool(task).handler({"interpretations": [
            {"type": "constant", "name": "T.a", "translation": "v2"}]})
        assert task.gates_running == 1, "the running gate picks v2 up; no second gate"
        hold.set()
    run.go([_answer_batch({"a": "v1"}, after=correct_mid_judge)], entries,
           verdicts={"v1": False, "v2": True}, hold=hold, judge_cls=_JudgeByText)
    judge_texts = [ev[2].split("Description 2:\n")[1].split("\n")[0]
                   for ev in run.events("judge-turn")]
    assert judge_texts == ["v1", "v2"]
    a = _rec("a")
    assert (a.interpretation, a.version, a.baseline_interpretation) == ("v2", 1, "the a"), \
        "v2's own verdict (UNCHANGED), not v1's CHANGED"
    assert run.result.interpretations == ["v2"]


# --- concurrency (D12) --------------------------------------------------------

def test_judge_sessions_are_capped_and_each_holds_one_entity(run, monkeypatch):
    monkeypatch.setattr(SI, "_JUDGE_SESSIONS", asyncio.Semaphore(2))
    for n in "abcde":
        _store(n, f"the {n}", DG[n])
    entries = [_entry(n, DG2[n]) for n in "abcde"]
    hold = asyncio.Event()

    async def release_when_two_are_open(task):
        for _ in range(200):
            if _ScriptedJudge.open_sessions == 2:
                break
            await asyncio.sleep(0)
        assert _ScriptedJudge.open_sessions == 2
        assert task.gates_running == 5, "every gate started at its answer; only the sessions wait"
        hold.set()
    run.go([_answer_batch(after=release_when_two_are_open)], entries, hold=hold,
           verdicts={"T.a": True, "T.b": False, "T.c": True, "T.d": False, "T.e": True})
    assert max(ev[2] for ev in run.events("judge-enter")) == 2
    assert sorted(run.judged) == ["T.a", "T.b", "T.c", "T.d", "T.e"]
    for _, n, p in run.events("judge-turn"):
        assert p.count("Entity:") == 1 and n in p
    assert [_rec(n).version for n in "abcde"] == [1, 2, 1, 3, 1], "each verdict reached its own entity"


def test_a_cancellation_propagates_and_closes_the_judge_session(run):
    _store("a", "the a", DG["a"])
    entries = [_entry("a", DG2["a"])]
    hold = asyncio.Event()                  # never set: the judge hangs

    async def go():
        runner = asyncio.ensure_future(run.start([_answer_batch()], entries, hold=hold))
        for _ in range(50):
            await asyncio.sleep(0)
        assert run.events("judge-turn")
        runner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
    asyncio.run(go())
    assert ("judge-exit", "T.a") in run.log, "the session was closed"
    assert _rec("a").interpretation == "the a", "nothing written"


# --- the queue loop over the store ---------------------------------------------

def test_a_rate_limit_mid_turn_recycles_and_loses_nothing(run, monkeypatch):
    """a answered, then the turn dies of a rate limit: after the recycle b
    is re-sent alone, a's gate has written, nothing is asked twice."""
    monkeypatch.setattr(SI.random, "uniform", lambda lo, hi: 0.0)   # no throttle sleep
    entries = [_entry("a", DG["a"]), _entry("b", DG["b"])]

    async def answer_a_then_die(driver, prompt):
        await mk_answer_tool(driver.task).handler({"interpretations": [
            {"type": "constant", "name": "T.a", "translation": "new a"}]})
        raise RateLimitError()
    res = run.go([answer_a_then_die, _answer_batch()], entries)
    assert res.interpretations == ["new a", "new b"]
    assert [ev[0] for ev in run.events("enter", "turn")] == ["enter", "turn", "enter", "turn"]
    assert run.asked("a") == 1 and "T.b" in run.turns[1] and "T.a" not in run.turns[1]


def test_an_unchanged_entity_written_this_run_is_a_wall_for_every_later_eff_star(run):
    """u CHANGED, a (deps u) UNCHANGED: a's record in rec_cache carries u's
    mint in its snapshot with its own version standing, so a later eff*
    through a sees a's version, not u's."""
    _store("u", "the u", DG["u"])
    _store("a", "the a", DG["a"], deps=["u"])
    _store("b", "the b", DG["b"], deps=["a"])
    entries = [_entry("u", DG2["u"]), _entry("a", DG["a"], ["u"]), _entry("b", DG["b"], ["a"])]
    run.go([_answer_batch(), _answer_batch()], entries, verdicts={"T.u": False, "T.a": True})
    assert run.judged == ["T.u", "T.a"] and run.asked("b") == 0
    assert (_rec("u").version, _rec("a").version, _rec("a").interpreted_at) == (2, 1, 2)
    assert SI._EffStar(run.task.rec_cache).eff_value(1, [_uk("a")]) == 1, "a is a wall"
    assert SI._EffStar({}).eff_value(1, [_uk("a")]) == 1, "and the store agrees"
    assert _dry(entries) == 0


def test_the_agent_giving_up_leaves_one_bare_user_error_without_a_group_gutter(run):
    """The retry loop's FatalAgentError is raised inside the gate task group;
    `interpret_file` raises it bare, so the text after USER_ERROR_MARKER --
    what ML shows -- carries no ExceptionGroup gutter."""
    entries = [_entry("a", DG["a"])]

    async def silent(driver, prompt):
        pass
    with pytest.raises(FatalAgentError) as e:
        run.go([silent] * (SI._MAX_STALLED_RETRIES + 2), entries)
    formatted = "".join(traceback.format_exception(e.value))
    assert USER_ERROR_MARKER in formatted
    assert "    | " not in formatted.split(USER_ERROR_MARKER, 1)[1]
    assert not isinstance(e.value.__context__, BaseExceptionGroup)


# --- cost (§15.9) ----------------------------------------------------------------

def test_the_run_s_cost_is_the_session_s_plus_the_judges_and_the_status_breaks_it_down(run):
    for n in "ab":
        _store(n, f"the {n}", DG[n])
    entries = [_entry(n, DG2[n]) for n in "ab"]
    res = run.go([_answer_batch()], entries, verdicts={"T.a": True, "T.b": False})
    assert res.current_cost.cost_usd == pytest.approx(0.5 + 2 * 0.25)
    assert res.current_cost.input_tokens == 10 + 2 * 5
    status = S.unpack_thy_status(S.Semantic_DB._get_raw(THY_KEY))
    assert status[b"judge_cost_usd"] == pytest.approx(0.5)
    assert status[b"cost_usd"] == pytest.approx(1.0) == pytest.approx(res.cumulative_cost.cost_usd)
    assert status[b"judge_cost_usd"] <= status[b"cost_usd"], "a breakdown of the total, not a second sum"
    assert status[b"judge_input_tokens"] == 10 and status[b"input_tokens"] == 20


# --- the judge task and the derived permissions (§5.5, §15.6) --------------------

def _judge_task(cache) -> JudgeTask:
    parent = InterpretationTask(None, "/tmp/T.thy", "T", THY_KEY, [_entry("a", DG["a"])])
    return JudgeTask(parent, 0, "the a", "new a")


def test_the_judge_task_holds_one_entry_and_cannot_write(cache):
    judge = _judge_task(cache)
    assert len(judge.entries) == 1 and judge.state == [SI._QUEUED]
    assert not hasattr(judge, "start_gate") and not hasattr(judge, "task_group")
    assert judge.max_stalled_retries == 1 and judge.cost_prefix == b"judge_"
    assert judge.retry_report(1, 1) == ""
    assert judge.retry_prompt([0]).startswith("You have not reported a verdict")
    assert judge.unanswered_failure(["T.a"]) == "judge gave no verdict for T.a"
    prompt = judge.build_prompt([0])
    assert prompt.index("Description 1:\nthe a") < prompt.index("Description 2:\nnew a")
    asyncio.run(mk_verdict_tool(judge).handler({"same": True, "why": "same thing"}))
    assert judge.verdict is True and judge.state == [_DONE] and judge.results == ["same thing"]
    assert S.Semantic_DB[_uk("a")] is None, "a verdict writes nothing"


def test_the_claude_driver_derives_its_permissions_from_the_tools_it_serves(cache):
    """`allowed_tools` and the PreToolUse hook read ONE set: the served
    tools' MCP names plus the CLI built-ins iff `cli_tools`."""
    from Isabelle_Semantic_Embedding.interpretation_driver.claude_code import ClaudeCodeDriver
    judge = _judge_task(cache)
    judge_driver = ClaudeCodeDriver(model="", system_prompt="s", tools=[mk_verdict_tool(judge)],
                                    task=judge, on_context_reset=lambda: None, cli_tools=False)
    parent = InterpretationTask(None, "/tmp/T.thy", "T", THY_KEY, [_entry("a", DG["a"])])
    agent_driver = ClaudeCodeDriver(model="", system_prompt="s", tools=[mk_answer_tool(parent)],
                                    task=parent, on_context_reset=lambda: None)
    j_opts, a_opts = judge_driver._options(), agent_driver._options()
    assert j_opts.allowed_tools == ["mcp__isabelle_semantics__verdict"]
    assert "mcp__isabelle_semantics__answer" in a_opts.allowed_tools \
        and "Read" in a_opts.allowed_tools \
        and "mcp__isabelle_semantics__verdict" not in a_opts.allowed_tools

    def decision(opts, tool_name):
        hook = opts.hooks["PreToolUse"][0].hooks[0]
        out = asyncio.run(hook({"tool_name": tool_name, "tool_input": {}}, None, None))
        return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")
    assert decision(j_opts, "mcp__isabelle_semantics__verdict") == "allow"
    assert decision(j_opts, "Bash") == "deny"
    assert decision(j_opts, "mcp__isabelle_semantics__answer") == "deny"
    assert decision(a_opts, "mcp__isabelle_semantics__answer") == "allow"
    assert decision(a_opts, "Read") == "allow"
