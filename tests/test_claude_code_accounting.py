"""The Claude Code driver's per-turn cost: a ResultMessage's `total_cost_usd` is its
session's running total, so a turn costs its advance, which is never negative.  The
`turn` event keeps the raw figures (§3.12).
No Isabelle, no model, no store.
Run with  python -m pytest contrib/Semantic_Embedding/tests/test_claude_code_accounting.py
"""
import asyncio
from typing import Any

import pytest
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock

from Isabelle_Semantic_Embedding.interpretation_driver.claude_code import ClaudeCodeDriver
from Isabelle_Semantic_Embedding.semantic_interpretation import FatalAgentError


class _Task:
    """What the accounting touches: the two accumulators, the flush and the turn event."""

    model = "claude-opus-5-5"
    run_cost_usd: float
    run_output_tokens: int

    def __init__(self):
        for k in ("input_tokens", "cache_creation_tokens", "cache_read_tokens",
                  "output_tokens", "cost_usd"):
            setattr(self, "total_" + k, 0)
            setattr(self, "run_" + k, 0)
        self.api_retry_errors = []
        self.turns = []

    def write_cost(self):
        pass

    def log_turn(self, **fields):
        self.turns.append(fields)


class _Client:
    """A connected CLI whose next turn streams the given messages."""

    def __init__(self):
        self.next: list = []

    async def query(self, prompt):
        pass

    async def receive_response(self):
        for m in self.next:
            yield m


def _driver():
    task = _Task()
    driver: Any = ClaudeCodeDriver(model="", system_prompt="", tools=[], task=task,  # type: ignore[arg-type]
                                   on_context_reset=lambda: None, cli_tools=True)
    driver._client = _Client()
    return driver, task


def _turn(driver, total, session="s1", model="claude-opus-5-5", is_error=False):
    driver._client.next = [AssistantMessage(content=[TextBlock("ok")], model=model),
                           ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                                         is_error=is_error, num_turns=1, session_id=session,
                                         total_cost_usd=total, usage={"output_tokens": 7})]
    asyncio.run(driver.run_turn("prompt"))


def test_a_turn_costs_the_advance_of_the_running_total():
    driver, task = _driver()
    for total in (0.30, None, 0.50, 0.80):
        _turn(driver, total)
    assert [t["cost_usd"] for t in task.turns] == pytest.approx([0.30, 0.0, 0.20, 0.30])
    assert task.run_cost_usd == pytest.approx(0.80)
    assert task.run_output_tokens == 28


def test_a_new_session_starts_from_zero():
    driver, task = _driver()
    _turn(driver, 0.50)
    _turn(driver, 0.10, session="s2")
    assert [t["cost_usd"] for t in task.turns] == pytest.approx([0.50, 0.10])


def test_a_crash_result_with_a_zeroed_total_costs_nothing():
    driver, task = _driver()
    _turn(driver, 0.50)
    with pytest.raises(FatalAgentError):
        _turn(driver, 0.0, is_error=True)
    assert [t["cost_usd"] for t in task.turns] == pytest.approx([0.50, 0.0])
    assert task.run_cost_usd == pytest.approx(0.50)


def test_the_turn_event_keeps_the_raw_figures():
    driver, task = _driver()
    _turn(driver, 0.30)
    _turn(driver, 0.45, model="claude-haiku-5-5")
    last = task.turns[-1]
    assert (last["session_id"], last["total_cost_usd"], last["models"]) == (
        "s1", 0.45, ["claude-haiku-5-5"])
