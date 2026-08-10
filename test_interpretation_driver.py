"""Harness tests for the driver-agnostic interpretation loop (`_run_agent`).

A scripted fake driver stands in for the agent backend, so the loop can be
driven turn by turn with no CLI, no LLM and no LMDB.  What is under test is
everything the drivers do NOT own: batch advancement, per-answer writing,
missing-entry retries, driver recycling on a poisoned session, and the
context-reset channel that clears the desugar tool's already-annotated set.

The answers go through the REAL `_answer_tool` handler, so its batch
bookkeeping (which entries remain, when to advance, what the next prompt is) is
exercised rather than simulated.
"""
import asyncio
import logging

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
    _KIND_CONSTANT,
    _MAX_STALLED_RETRIES,
    _answer_tool,
    _label,
    _local_task,
    _resolve_driver,
    _run_agent,
)


# --- the task, with LMDB replaced by a recording ---------------------------

class _RecordingTask(InterpretationTask):
    """An InterpretationTask whose two LMDB writes are recorded instead."""

    def __init__(self, entries):
        super().__init__(None, "/tmp/T.thy", "T", b"\x00" * 32, entries)
        self.written: list[tuple[int, str]] = []
        self.cost_flushes: list[tuple[int, int, int, int, float]] = []

    def write_answer(self, task_idx: int, sem: str) -> None:
        self.written.append((task_idx, sem))

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
                  line_number=i + 1, universal_key=bytes([i]) + b"\x00" * 31)
            for i in range(n)]


def _make_task(n: int, batch_size: int) -> _RecordingTask:
    """A task batched exactly the way `interpret_file` batches one."""
    task = _RecordingTask(_entries(n))
    for start in range(0, n, batch_size):
        r = range(start, min(start + batch_size, n))
        task.batches.append((task.build_prompt("/tmp/T.thy", "T", r), r))
    return task


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
        await _answer_tool.handler({"interpretations": [
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


def _run(task, script) -> list:
    """Drive `_run_agent` over `script`, returning the driver call log."""
    log: list = []

    def make_driver():
        return _ScriptedDriver(
            script=script, log=log, model="m", system_prompt="sys", tools=[],
            task=task, on_context_reset=lambda: None)

    async def go():
        _local_task.set(task)
        await _run_agent(make_driver)

    asyncio.run(go())
    return log


# --- batching and answer writing -------------------------------------------

def test_batches_advance_and_every_answer_is_written():
    task = _make_task(4, batch_size=2)
    log = _run(task, [_answer(0, 1), _answer(2, 3)])

    assert all(v is not None for v in task.results.values())
    assert task.written == [(i, f"description of c{i}") for i in range(4)]
    # One turn per batch: the answer tool hands the next batch back in its own
    # result, so the loop does not have to prompt again for it.
    assert [k for k, _ in log] == ["enter", "turn", "turn", "exit"]
    # The second batch's prompt is the one the answer tool returned, i.e. the
    # loop never re-sent batch 0.
    assert "T.c2" in log[2][1]


def test_each_turn_flushes_its_cost():
    task = _make_task(4, batch_size=2)
    _run(task, [_answer(0, 1), _answer(2, 3)])

    assert task.cost_flushes == [(10, 0, 0, 1, 0.5)] * 2
    # run_* survives the flushes; it is what interpret_file reports as this
    # invocation's cost.
    assert (task.run_input_tokens, task.run_output_tokens, task.run_cost_usd) \
        == (20, 2, 1.0)


def test_an_answer_that_cannot_be_written_is_not_counted_as_answered():
    """A failed write must not leave memory claiming an answer that is not on
    disk, and must not abandon the items after it in the same call.

    `task.results` is what decides which entries the next batch asks for, so
    marking before persisting loses the entry silently for the whole run: the
    MCP SDK turns the exception into an isError result for the agent, and
    nothing reaches Isabelle."""
    task = _make_task(3, batch_size=3)
    task.batch_range = task.batches[0][1]          # as _run_agent leaves it
    real_write = task.write_answer

    def write_answer(task_idx, sem):
        if task_idx == 1:
            raise OSError(28, "No space left on device")
        real_write(task_idx, sem)

    task.write_answer = write_answer                # type: ignore[method-assign]

    async def go():
        _local_task.set(task)
        return await _answer_tool.handler({"interpretations": [
            {"type": "constant", "name": task.entries[i].name,
             "translation": f"description of c{i}"} for i in range(3)]})

    ret = asyncio.run(go())

    # Item 1 failed; items 0 and 2 were written anyway -- the failure did not
    # abandon what came after it.
    assert task.written == [(0, "description of c0"), (2, "description of c2")]
    assert task.results[_label(task.entries[1])] is None, \
        "the entry whose write failed must stay unanswered, so it is asked again"
    assert task.results[_label(task.entries[0])] is not None
    assert task.results[_label(task.entries[2])] is not None
    # And the agent is told, in the errors list the handler already returns.
    text = ret["content"][0]["text"]
    assert "Failed to store" in text and "No space left on device" in text
    assert "Answered 2 translations, remaining 1 in this batch." in text


# --- missing-entry retries --------------------------------------------------

def test_unanswered_entries_are_retried_with_their_full_text():
    task = _make_task(3, batch_size=3)
    log = _run(task, [_answer(0), _answer(1, 2)])

    assert all(v is not None for v in task.results.values())
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
    assert task.results[_label(task.entries[0])] is not None


# --- recycling --------------------------------------------------------------

def test_poisoned_session_recycles_a_fresh_driver_and_keeps_answers():
    task = _make_task(3, batch_size=3)
    log = _run(task, [_answer(0), _raise(PoisonedSessionError()), _answer(1, 2)])

    assert all(v is not None for v in task.results.values())
    drivers = [i for k, i in log if k == "enter"]
    assert len(drivers) == 2 and drivers[0] != drivers[1], \
        "the recycle must build a new driver, not reuse the poisoned one"
    # Answers written before the poisoning are not redone.
    assert task.written == [(0, "description of c0"), (1, "description of c1"),
                            (2, "description of c2")]


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
    empty model.  An explicitly configured model is NOT overwritten."""
    from claude_agent_sdk.types import AssistantMessage

    from Isabelle_Semantic_Embedding.interpretation_driver.claude_code import (
        _handle_message,
    )
    task = _make_task(1, batch_size=1)
    assert task.model == ""
    _handle_message(task, AssistantMessage(content=[], model="claude-cli-pick"))
    assert task.model == "claude-cli-pick"
    _handle_message(task, AssistantMessage(content=[], model="something-else"))
    assert task.model == "claude-cli-pick", "first backfill wins"


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
        _local_task.set(task)
        drv = make_driver()
        drv.on_context_reset()
        assert seen == set()
        await _run_agent(make_driver)

    asyncio.run(go())
    assert all(v is not None for v in task.results.values())
