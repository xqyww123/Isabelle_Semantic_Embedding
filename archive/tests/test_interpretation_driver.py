"""Harness tests for the driver-agnostic interpretation loop (`_run_agent`).

A scripted fake driver stands in for the agent backend, so the loop can be
driven turn by turn with no CLI, no LLM and no LMDB.  What is under test is
everything the drivers do NOT own: the work queue's batches, the gate started
per answer, missing-entry retries, driver recycling on a poisoned session,
the gate task group's failure unwrapping, and the context-reset channel that
clears the desugar tool's already-annotated set.

The answers go through the REAL answer tool handler, so its bookkeeping
(which entries of the batch remain, what it replies) is exercised rather than
simulated.
"""
import asyncio
import logging
import traceback

import pytest

import Isabelle_Semantic_Embedding.semantic_interpretation as SI
from Isabelle_Semantic_Embedding.interpretation_driver import (
    InterpretationDriver,
    accumulate_usage,
)
from Isabelle_Semantic_Embedding.semantic_interpretation import (
    Entry,
    FatalAgentError,
    InterpretationTask,
    PoisonedSessionError,
    _DONE,
    _KIND_CONSTANT,
    _MAX_STALLED_RETRIES,
    _first_failure,
    _note_on_failure,
    _resolve_driver,
    _run_agent,
    mk_answer_tool,
)


# --- the task, with LMDB replaced by a recording ---------------------------

class _RecordingTask(InterpretationTask):
    """An InterpretationTask whose LMDB writes are recorded instead.  The
    production `start_gate` runs unchanged (counter paired to the task,
    compensation when the group refuses it); only the gate BODY is swapped,
    by the `record_gates` fixture: it records what it would have written, or
    runs the body a test supplied for that entry in `gate_bodies`."""

    def __init__(self, entries):
        super().__init__(None, "/tmp/T.thy", "T", b"\x00" * 32, entries)
        self.written: list[tuple[int, str]] = []
        self.cost_flushes: list[tuple[int, int, int, int, float]] = []
        self.gate_bodies: dict = {}          # idx -> async callable, the gate of that entry

    def write_cost(self):
        self.cost_flushes.append(
            (self.total_input_tokens, self.total_cache_creation_tokens,
             self.total_cache_read_tokens, self.total_output_tokens,
             self.total_cost_usd))
        self.total_input_tokens = 0
        self.total_cache_creation_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        return (0, 0, 0, 0, 0.0)


def _entries(n: int) -> list[Entry]:
    return [Entry(kind=_KIND_CONSTANT, name=f"T.c{i}", prop_str="nat ⇒ nat",
                  position=("$AFP/T/T.thy", i + 1, 1),
                  universal_key=bytes([i]) + b"\x00" * 31)
            for i in range(n)]


def _make_task(n: int, batch_size: int) -> _RecordingTask:
    """A task with every entry enrolled, batched `batch_size` at a time."""
    task = _RecordingTask(_entries(n))
    task.batch_size = batch_size
    for i in range(n):
        task.enqueue(i)
    return task


async def _recording_gate(task, idx):
    """The gate body under test: `start_gate` creates THIS coroutine (it
    resolves `_gate` from the module at call time)."""
    body = task.gate_bodies.get(idx)
    if body is not None:
        await body()
        return
    task.written.append((idx, task.results[idx]))
    task.state[idx] = _DONE


@pytest.fixture(autouse=True)
def record_gates(monkeypatch):
    """Every gate of this module (and of the modules importing this fixture)
    is `_recording_gate`; the starter is production's."""
    monkeypatch.setattr(SI, "_gate", _recording_gate)


async def _in_group(task, body):
    """`interpret_file`'s shape around the loop: the task group owns the
    gates, a failure is selected inside the except block and raised outside
    it.  `body` runs inside the group and may be a coroutine or a value."""
    failure = None
    result = None
    try:
        async with asyncio.timeout(10):        # a loop that never ends fails, not hangs
            async with asyncio.TaskGroup() as tg:
                task.task_group = tg
                result = await body()
    except ExceptionGroup as eg:
        failure = _first_failure(eg)
    if failure is not None:
        raise failure
    return result


# --- the scripted driver ----------------------------------------------------

class _ScriptedDriver(InterpretationDriver):
    """Runs one scripted action per turn.

    Each action is ``async def act(driver, prompt)``; the script is shared
    across recycles (a recycle builds a NEW driver but continues the script),
    which is what lets a test assert that the loop resumed rather than restarted.
    """

    def __init__(self, *, script, log, **kw):
        super().__init__(**kw)
        self._script = script
        self._log = log

    async def __aenter__(self):
        self._log.append(("enter", id(self)))
        return self

    async def __aexit__(self, *exc):
        self._log.append(("exit", id(self)))

    async def run_turn(self, prompt: str) -> None:
        self._log.append(("turn", prompt))
        if not self._script:
            raise AssertionError("the loop asked for a turn the script has no action for")
        await self._script.pop(0)(self, prompt)


def _answer(*indices):
    """An action that submits translations for `indices` of the task."""
    async def act(driver, prompt):
        task = driver.task
        await mk_answer_tool(task).handler({"interpretations": [
            {"type": "constant", "name": task.entries[i].name,
             "translation": f"description of c{i}"}
            for i in indices]})
        # Every turn costs something and must be flushed as it happens.
        accumulate_usage(task, input_tokens=10, output_tokens=1, cost_usd=0.5)
    return act


def _raise(exc):
    async def act(driver, prompt):
        raise exc
    return act


def _make_driver_factory(task, script, log):
    def make_driver():
        return _ScriptedDriver(
            script=script, log=log, model="m", system_prompt="sys", tools=[],
            task=task, on_context_reset=lambda: None)
    return make_driver


def _run(task, script, make_driver=None) -> list:
    """Drive `_run_agent` over `script` inside the gate task group, returning
    the driver call log."""
    log: list = []
    make_driver = make_driver or _make_driver_factory(task, script, log)
    asyncio.run(_in_group(task, lambda: _run_agent(make_driver, task)))
    return log


# --- batching and answer writing -------------------------------------------

def test_batches_advance_and_every_answer_is_written():
    task = _make_task(4, batch_size=2)
    log = _run(task, [_answer(0, 1), _answer(2, 3)])

    assert all(v is not None for v in task.results)
    assert task.written == [(i, f"description of c{i}") for i in range(4)]
    # One turn per batch, on one session.
    assert [k for k, _ in log] == ["enter", "turn", "turn", "exit"]
    # Only the first turn asks for the skills; the second continues with the
    # next batch and never re-sends batch 0.
    assert log[1][1].startswith("Load the skills") and "T.c0" in log[1][1]
    assert log[2][1].startswith("Continue with") and "T.c2" in log[2][1]
    assert "T.c0" not in log[2][1]


def test_each_turn_flushes_its_cost():
    task = _make_task(4, batch_size=2)
    _run(task, [_answer(0, 1), _answer(2, 3)])

    assert task.cost_flushes == [(10, 0, 0, 1, 0.5)] * 2
    # run_* survives the flushes; it is what interpret_file reports as this
    # invocation's cost.
    assert (task.run_input_tokens, task.run_output_tokens, task.run_cost_usd) \
        == (20, 2, 1.0)


async def _settle(task):
    """Let every started gate run and its done callback fire."""
    for _ in range(3):
        await asyncio.sleep(0)
    assert task.gates_running == 0, "every finished gate must have released the counter"


def test_the_answer_tool_reports_the_batch_and_refuses_unknown_entries():
    task = _make_task(3, batch_size=3)
    task.next_batch()                               # as _run_agent leaves it

    async def go():
        ret = await mk_answer_tool(task).handler({"interpretations": [
            {"type": "constant", "name": task.entries[i].name,
             "translation": f"description of c{i}"} for i in (0, 2)]
            + [{"type": "constant", "name": "T.nobody", "translation": "?"}]})
        assert task.gates_running == 2, "two gates started, none run yet"
        await _settle(task)
        return ret

    text = asyncio.run(_in_group(task, go))["content"][0]["text"]
    assert task.written == [(0, "description of c0"), (2, "description of c2")]
    assert text.startswith("Answered 2 translations, remaining 1 in this batch.")
    assert "T.c1" in text and "nat ⇒ nat" in text, "the unanswered entry, in full"
    assert "Unknown entry: 'constant T.nobody'" in text


def test_a_correction_gates_again_and_an_identical_resubmission_does_nothing():
    """A re-submitted answer (a correction, D11) is an answer: it re-runs the
    gate, so the second text is written too.  One that repeats the stored
    text byte for byte starts nothing."""
    task = _make_task(1, batch_size=1)
    task.next_batch()

    async def go():
        task.on_answer(0, "first wording")
        await _settle(task)                             # the gate wrote; the entry is _DONE
        task.on_answer(0, "first wording")              # byte-identical: no gate
        assert task.gates_running == 0 and task.written == [(0, "first wording")]
        task.on_answer(0, "second wording")             # a correction: gated again
        assert task.gates_running == 1
        await _settle(task)

    asyncio.run(_in_group(task, go))
    assert task.written == [(0, "first wording"), (0, "second wording")]
    assert task.results[0] == "second wording"
    assert task.n_interpreted() == 1, "an entity counts once however many gates it needed"


def test_a_correction_arriving_while_the_gate_runs_is_picked_up_by_that_gate():
    """Two items for ONE entry in one `answer` call: the handler's item loop
    has no await, so the second lands while the first's gate has not run yet
    (state _GATING).  Exactly one gate runs, and it writes the newer text
    (D11: picked up by the running gate, not a second gate)."""
    task = _make_task(1, batch_size=1)
    task.next_batch()

    async def go():
        await mk_answer_tool(task).handler({"interpretations": [
            {"type": "constant", "name": "T.c0", "translation": "first wording"},
            {"type": "constant", "name": "T.c0", "translation": "second wording"}]})
        assert task.gates_running == 1
        await _settle(task)

    asyncio.run(_in_group(task, go))
    assert task.written == [(0, "second wording")]


class _RefusingGroup:
    """A task group that refuses new tasks -- what a real group does once it
    is aborting after another gate failed."""

    def create_task(self, coro):
        raise RuntimeError("TaskGroup is shutting down")


def test_a_refused_gate_releases_the_counter_and_closes_its_coroutine(monkeypatch):
    """F4: the counter is incremented before `create_task` and compensated
    when the group refuses the task; the never-started coroutine is closed
    (no 'coroutine was never awaited')."""
    created: list = []

    def gate(task, idx):
        created.append(_recording_gate(task, idx))
        return created[-1]

    monkeypatch.setattr(SI, "_gate", gate)
    task = _make_task(1, batch_size=1)
    task.next_batch()
    task.task_group = _RefusingGroup()
    with pytest.raises(RuntimeError):
        task.on_answer(0, "description of c0")
    assert task.gates_running == 0
    assert len(created) == 1 and created[0].cr_frame is None, "closed, never awaited"


# --- missing-entry retries --------------------------------------------------

def test_unanswered_entries_are_retried_with_their_full_text():
    task = _make_task(3, batch_size=3)
    log = _run(task, [_answer(0), _answer(1, 2)])

    assert all(v is not None for v in task.results)
    retry_prompt = log[2][1]
    assert "unanswered entries" in retry_prompt
    # Full entry text, not bare names: after a compaction the propositions are
    # the agent's only remaining handle on what it is translating.
    assert "T.c1" in retry_prompt and "nat ⇒ nat" in retry_prompt
    assert "T.c0" not in retry_prompt


def test_a_stalled_retry_loop_raises_rather_than_returning_partial():
    task = _make_task(2, batch_size=2)
    script = [_answer(0)] + [_answer() for _ in range(_MAX_STALLED_RETRIES + 2)]
    with pytest.raises(FatalAgentError) as e:
        _run(task, script)
    assert "T.c1" in str(e.value)
    assert task.results[0] is not None


# --- recycling --------------------------------------------------------------

def test_poisoned_session_recycles_a_fresh_driver_and_keeps_answers():
    task = _make_task(3, batch_size=3)
    log = _run(task, [_answer(0), _raise(PoisonedSessionError()), _answer(1, 2)])

    assert all(v is not None for v in task.results)
    drivers = [i for k, i in log if k == "enter"]
    assert len(drivers) == 2 and drivers[0] != drivers[1], \
        "the recycle must build a new driver, not reuse the poisoned one"
    # Answers written before the poisoning are not redone: the fresh session
    # is asked for the two still unanswered, in the first-turn form (it has
    # to load the skills too).
    assert task.written == [(0, "description of c0"), (1, "description of c1"),
                            (2, "description of c2")]
    resumed = log[-2][1]
    assert resumed.startswith("Load the skills")
    assert "T.c1" in resumed and "T.c2" in resumed and "T.c0" not in resumed


# --- the gate task group ----------------------------------------------------

def _with_gate(n, idx, body):
    """A task with every entry enrolled whose gate for entry `idx` is `body`."""
    task = _make_task(n, batch_size=n)
    task.gate_bodies[idx] = body
    return task


def test_a_gate_failure_ends_the_run_as_the_store_s_own_exception():
    """A failed gate write fails the task group; what leaves `interpret_file`
    is the store's exception itself -- with the note naming the entity, its
    own cause, and NOT an ExceptionGroup as its context (a group's gutter
    would reach the user through ML's one-line error contract)."""
    cause = ValueError("record is not msgpack")

    async def failing_write():
        with _note_on_failure("while writing the interpretation of T.c1"):
            raise OSError(28, "No space left on device") from cause

    task = _with_gate(3, 1, failing_write)
    with pytest.raises(OSError) as e:
        _run(task, [_answer(0, 1, 2)])
    formatted = "".join(traceback.format_exception(e.value))
    assert "while writing the interpretation of T.c1" in formatted
    assert e.value.__cause__ is cause
    assert not isinstance(e.value.__context__, BaseExceptionGroup), \
        "raised outside the except block: the leaf keeps its own context"
    assert task.gates_running == 0


def test_a_leaf_raised_with_its_own_context_still_shows_it():
    context = KeyError("the record")

    async def failing_write():
        try:
            raise context
        except KeyError:
            raise OSError(5, "Input/output error")     # implicit __context__

    task = _with_gate(1, 0, failing_write)
    with pytest.raises(OSError) as e:
        _run(task, [_answer(0)])
    assert e.value.__context__ is context


def test_the_first_failure_is_selected_and_cancellations_are_ignored():
    first, second = OSError("first"), FatalAgentError("second")
    nested = BaseExceptionGroup("run", [asyncio.CancelledError(),
                                        ExceptionGroup("inner", [first]), second])
    assert _first_failure(nested) is first
    # Nothing but cancellations: the group itself comes back, unchanged.
    only_cancelled = BaseExceptionGroup("run", [asyncio.CancelledError()])
    assert _first_failure(only_cancelled) is only_cancelled


class _TeardownConvertsCancellation(_ScriptedDriver):
    """A driver whose session teardown turns the cancellation into an ordinary
    exception -- what a cost flush on the broken store, or the subprocess
    transport's __aexit__, does during the group's unwind."""

    async def __aexit__(self, *exc):
        await super().__aexit__(*exc)
        if exc and exc[0] is asyncio.CancelledError:
            raise RuntimeError("cost flush failed during teardown")


def test_a_cancelled_session_is_not_recycled_when_its_teardown_hides_the_cancellation():
    """The gate's failure cancels the loop; the driver's teardown replaces the
    CancelledError with a RuntimeError that lands in the recycle arm.  The
    arm must re-raise, not recycle: a recycled session would have every gate
    refused by the aborting group and park for ever."""
    async def failing_write():
        raise OSError(28, "No space left on device")

    task = _with_gate(2, 1, failing_write)
    log: list = []

    def make_driver():
        return _TeardownConvertsCancellation(
            script=[_answer(0, 1), _answer()], log=log, model="m",
            system_prompt="sys", tools=[], task=task, on_context_reset=lambda: None)

    async def go():
        await asyncio.wait_for(_in_group(task, lambda: _run_agent(make_driver, task)), 5)

    with pytest.raises(OSError):
        asyncio.run(go())
    assert [k for k, _ in log].count("turn") == 1, "no further turn after the cancellation"
    assert [k for k, _ in log].count("enter") == 1, "the session was not recycled"
    assert task.gates_running == 0


def test_the_loop_waits_for_a_gate_that_outlives_the_queue():
    """§5.3 Termination: with the queue empty and nothing unanswered, the
    session stays open until the last gate has finished, then returns."""
    release = asyncio.Event()
    written: list = []

    async def slow_write():
        await release.wait()
        written.append(1)
        task.state[1] = _DONE

    task = _with_gate(2, 1, slow_write)
    log: list = []
    make_driver = _make_driver_factory(task, [_answer(0, 1)], log)

    async def go():
        runner = asyncio.ensure_future(
            _in_group(task, lambda: _run_agent(make_driver, task)))
        for _ in range(20):
            await asyncio.sleep(0)
        assert not runner.done(), "the loop must wait for the running gate"
        assert task.gates_running == 1
        release.set()
        await asyncio.wait_for(runner, 5)

    asyncio.run(go())
    assert written == [1] and all(v is not None for v in task.results)
    assert task.gates_running == 0
    assert [k for k, _ in log].count("enter") == 1, "one session, never recycled"
    assert task.n_interpreted() == 2


# --- which backend and model to run ----------------------------------------

@pytest.fixture(autouse=True)
def _clean_driver_sources(monkeypatch):
    """No ambient driver choice: neither the batch CLI's nor the environment's."""
    monkeypatch.setattr(SI, "interpretation_driver_override", "")
    monkeypatch.delenv("INTERPRETATION_DRIVER", raising=False)


def test_nothing_set_anywhere_is_the_default_driver():
    assert _resolve_driver("") == ("ClaudeCode", "")


def test_the_model_half_is_optional_and_splits_at_the_first_dot():
    assert _resolve_driver("Codex") == ("Codex", "")
    # Model names contain dots; driver names do not, which is why the split is
    # at the FIRST one.
    assert _resolve_driver("Codex.gpt-5.5") == ("Codex", "gpt-5.5")
    assert _resolve_driver("ClaudeCode.claude-opus-4-8[1m]") \
        == ("ClaudeCode", "claude-opus-4-8[1m]")


def test_sources_are_tried_in_order_and_empty_means_unset(monkeypatch):
    monkeypatch.setenv("INTERPRETATION_DRIVER", "Codex.from-env")
    assert _resolve_driver("") == ("Codex", "from-env")           # env
    assert _resolve_driver("Codex.from-isabelle") \
        == ("Codex", "from-isabelle")                             # declare beats env
    monkeypatch.setattr(SI, "interpretation_driver_override", "Codex.from-cli")
    assert _resolve_driver("Codex.from-isabelle") == ("Codex", "from-cli")
    # An empty batch-CLI setting is "not asked for", not "use the default".
    monkeypatch.setattr(SI, "interpretation_driver_override", "")
    assert _resolve_driver("Codex.from-isabelle") == ("Codex", "from-isabelle")


class _StubConnection:
    class server:
        logger = logging.getLogger("test_interpretation_driver.stub")


def test_an_unknown_driver_fails_before_any_work():
    """Loudly, and before the cache is even read: it is a config typo, and the
    quiet alternative is a whole cone silently interpreted by the wrong backend."""
    with pytest.raises(FatalAgentError) as e:
        asyncio.run(SI.interpret_file(
            _StubConnection(), "/tmp/T.thy", "T", b"\x00" * 32, [],
            driver="Codx.gpt-5.5"))
    assert "Codx" in str(e.value)
    assert "ClaudeCode" in str(e.value), "should name what it does know"


def test_the_resolved_pair_is_what_gets_recorded():
    """`write_cost` records the backend and model actually used, so a theory's
    provenance survives a later change of configuration."""
    task = _make_task(1, batch_size=1)
    assert (task.driver, task.model) == ("ClaudeCode", "")
    task2 = InterpretationTask(None, "/tmp/T.thy", "T", b"\x00" * 32, [],
                               driver="Codex", model="gpt-5.5")
    assert (task2.driver, task2.model) == ("Codex", "gpt-5.5")


def test_claudecode_with_no_model_leaves_the_choice_to_the_cli():
    """An empty model half means the CLI runs its own configured default: the
    driver must pass NO model (None), not an empty string the CLI would treat
    as a model name."""
    from Isabelle_Semantic_Embedding.interpretation_driver.claude_code import (
        ClaudeCodeDriver,
    )
    task = _make_task(1, batch_size=1)
    driver = ClaudeCodeDriver(model="", system_prompt="sys", tools=[],
                              task=task, on_context_reset=lambda: None)
    assert driver.model == ""
    assert driver._options().model is None
    # An explicit model in the spec still pins the CLI to it.
    pinned = ClaudeCodeDriver(model="claude-opus-4-8[1m]", system_prompt="sys",
                              tools=[], task=task,
                              on_context_reset=lambda: None)
    assert pinned._options().model == "claude-opus-4-8[1m]"


def test_the_cli_chosen_model_is_backfilled_into_provenance():
    """When the CLI picked the model, the first assistant message names it and
    `_handle_message` records it on the task -- so write_cost never stores an
    empty model.  A later, different echo does NOT overwrite it."""
    from claude_agent_sdk.types import AssistantMessage

    from Isabelle_Semantic_Embedding.interpretation_driver.claude_code import (
        ClaudeCodeDriver,
    )
    task = _make_task(1, batch_size=1)
    assert task.model == ""
    driver = ClaudeCodeDriver(model="", system_prompt="sys", tools=[],
                              task=task, on_context_reset=lambda: None)
    driver._handle_message(AssistantMessage(content=[], model="claude-cli-pick"))
    assert task.model == "claude-cli-pick"
    driver._handle_message(AssistantMessage(content=[], model="something-else"))
    assert task.model == "claude-cli-pick", "first backfill wins"


def test_the_backend_s_own_shorthand_is_canonicalised_at_resolution():
    """The resolution step must hand back the name the API is given, because
    the SAME string is what the task records: a spec normalised any later
    would write a name into the database that no price table and no endpoint
    knows.  `DeepSeek.V4-pro` is the documented shorthand (README)."""
    name, cls, model = SI._resolve_driver_and_model("DeepSeek.V4-pro")
    assert (name, model) == ("DeepSeek", "deepseek-v4-pro")
    assert cls.NAME == "DeepSeek"
    # A backend with no shorthands is unaffected: ClaudeCode's empty model
    # half still means "let the CLI choose".
    assert SI._resolve_driver_and_model("ClaudeCode")[2] == ""


def test_every_door_into_a_driver_resolves_the_model_the_same_way():
    """Construction is the other door: a driver built directly (tests, future
    callers, `make_interpretation_driver`) must land on the same name as the
    one `interpret_file` records, or provenance and pricing split."""
    from Isabelle_Semantic_Embedding.interpretation_driver import (
        resolve_interpretation_driver_class,
    )
    cls = resolve_interpretation_driver_class("DeepSeek")
    for spec in ("", "  ", "V4-pro", "deepseek-v4-pro"):
        assert cls.canonical_model(cls.canonical_model(spec)) \
            == cls.canonical_model(spec), "canonical_model must be idempotent"
    task = _make_task(1, batch_size=1)
    driver = _ScriptedDriver(script=[], log=[], model="  ", system_prompt="s",
                             tools=[], task=task, on_context_reset=lambda: None)
    assert driver.model == "", \
        "a whitespace-only model half is 'not set', not a model name"


# --- explaining the same constant twice ------------------------------------

class _DesugarConnection:
    """Just enough connection for the desugar tool: a logger and one callback."""

    class server:
        logger = logging.getLogger("test_interpretation_driver.desugar")

    def __init__(self, constants):
        self._constants = constants

    async def callback(self, name, args):
        return "compact term", self._constants


def _desugar_twice(dedup, monkeypatch):
    """Call the desugar tool twice on the same constant; return both replies."""
    from Isabelle_Semantic_Embedding import desugar as D
    monkeypatch.setattr(D.Semantic_DB, "query",
                        lambda uk, with_pretty=False: "the successor function")
    tool = D.mk_desugar_and_explain_tool(
        _DesugarConnection([("Nat.Suc", b"\x01" * 32)]), dedup=dedup)

    async def go():
        return (await tool.handler({"term": "Suc n"}),
                await tool.handler({"term": "Suc n"}))

    return asyncio.run(go())


def test_the_desugar_tool_explains_a_constant_once_when_it_may(monkeypatch):
    first, second = _desugar_twice(True, monkeypatch)
    assert "the successor function" in first["content"][0]["text"]
    assert "the successor function" not in second["content"][0]["text"]


def test_the_desugar_tool_explains_it_every_time_when_it_must(monkeypatch):
    """For a backend that compacts the conversation without telling anyone: the
    earlier explanation is gone from the agent's context while the record still
    says it was given, so the agent would meet a constant it cannot see the
    meaning of -- and would not know it was missing.  Explaining twice costs
    tokens; explaining never costs the translation."""
    first, second = _desugar_twice(False, monkeypatch)
    assert "the successor function" in first["content"][0]["text"]
    assert "the successor function" in second["content"][0]["text"]


# --- the context-reset channel ---------------------------------------------

def test_on_context_reset_reaches_the_desugar_dedup_set():
    """The channel `interpret_file` wires from a bare local to the driver."""
    task = _make_task(1, batch_size=1)
    seen = {"Nat.plus", "List.append"}
    log: list = []

    def make_driver():
        return _ScriptedDriver(
            script=[_answer(0)], log=log, model="m", system_prompt="sys",
            tools=[], task=task, on_context_reset=seen.clear)

    async def go():
        drv = make_driver()
        drv.on_context_reset()
        assert seen == set()
        await _in_group(task, lambda: _run_agent(make_driver, task))

    asyncio.run(go())
    assert all(v is not None for v in task.results)
