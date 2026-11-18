"""The Claude Code driver's per-turn usage: a ResultMessage's `model_usage` holds its
session's running totals per model, so a turn uses their advance, which is never
negative.  The `turn` event records the session id, the CLI's running total and the
per-model advance (§3.12).
No Isabelle, no model, no store.
Run with  python -m pytest contrib/Semantic_Embedding/tests/test_claude_code_accounting.py
"""
import asyncio
from typing import Any

import pytest
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock

from Isabelle_Semantic_Embedding.interpretation_driver.claude_code import ClaudeCodeDriver
from Isabelle_Semantic_Embedding.semantic_interpretation import FatalAgentError

OPUS, HAIKU = "claude-opus-5-5", "claude-haiku-5-5"


class _Task:
    """What the accounting touches: the two accumulators, the flush and the turn event."""

    model = OPUS
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


def _usage(cost, out, **optional):
    """One model's running totals, as `model_usage` carries them."""
    return {"inputTokens": 0, "cacheCreationInputTokens": 0, "cacheReadInputTokens": 0,
            "outputTokens": out, "costUSD": cost, "webSearchRequests": 0,
            "contextWindow": 1_000_000, "maxOutputTokens": 64_000,
            "canonicalModel": OPUS, "provider": "firstParty", **optional}


def _turn(driver, model_usage, session="s1", is_error=False):
    # `usage` (the main loop's alone) and `total_cost_usd` must not be what is billed
    driver._client.next = [AssistantMessage(content=[TextBlock("ok")], model=OPUS),
                           ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                                         is_error=is_error, num_turns=1, session_id=session,
                                         total_cost_usd=9.0, usage={"output_tokens": 999},
                                         model_usage=model_usage)]
    asyncio.run(driver.run_turn("prompt"))


def test_a_turn_uses_the_advance_of_the_running_totals():
    driver, task = _driver()
    for mu in ({OPUS: _usage(0.30, 7)}, None, {OPUS: _usage(0.50, 14)}, {OPUS: _usage(0.80, 21)}):
        _turn(driver, mu)
    assert [t["cost_usd"] for t in task.turns] == pytest.approx([0.30, 0.0, 0.20, 0.30])
    assert [t["output_tokens"] for t in task.turns] == [7, 0, 7, 7]
    assert task.run_cost_usd == pytest.approx(0.80)


def test_a_new_session_starts_from_zero():
    driver, task = _driver()
    _turn(driver, {OPUS: _usage(0.50, 7)})
    _turn(driver, {OPUS: _usage(0.10, 3)}, session="s2")
    assert [t["cost_usd"] for t in task.turns] == pytest.approx([0.50, 0.10])


def test_a_crash_result_with_zeroed_totals_costs_nothing():
    driver, task = _driver()
    _turn(driver, {OPUS: _usage(0.50, 7)})
    with pytest.raises(FatalAgentError):
        _turn(driver, {OPUS: _usage(0.0, 0)}, is_error=True)
    _turn(driver, {OPUS: _usage(0.60, 9)})        # the baseline was not lowered
    assert [t["cost_usd"] for t in task.turns] == pytest.approx([0.50, 0.0, 0.10])
    assert task.run_cost_usd == pytest.approx(0.60)


def test_every_model_that_billed_counts_and_the_turn_event_records_its_advance():
    driver, task = _driver()
    _turn(driver, {OPUS: _usage(0.30, 7)})
    _turn(driver, {OPUS: _usage(0.45, 14, thinkingTokens=4), HAIKU: _usage(0.01, 5)})
    last = task.turns[-1]
    assert (last["cost_usd"], last["output_tokens"]) == (pytest.approx(0.16), 12)
    assert (last["model_usage"][OPUS]["thinkingTokens"], last["model_usage"][HAIKU]["thinkingTokens"]) == (4, 0)
    assert (last["session_id"], last["total_cost_usd"]) == ("s1", 9.0)
    assert sorted(last["model_usage"]) == [HAIKU, OPUS]
    assert (last["model_usage"][OPUS]["costUSD"], last["model_usage"][OPUS]["outputTokens"]) == (
        pytest.approx(0.15), 7)
