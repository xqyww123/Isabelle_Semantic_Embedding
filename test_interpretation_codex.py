"""Tests for the Codex interpretation driver.

No model is called and no `codex app-server` is started: what is under test is
the two places where this driver has to disagree with the obvious reading of
the SDK -- how a turn is billed, and what a failed turn means.
"""
import asyncio

import pytest
import yaml

pytest.importorskip("openai_codex", reason="the Codex backend is an optional extra")

from openai_codex.models import Notification                       # noqa: E402
from openai_codex.generated.v2_all import (                        # noqa: E402
    ActiveTurnNotSteerable,
    ActiveTurnNotSteerableCodexErrorInfo,
    CodexErrorInfo,
    CodexErrorInfoValue,
    HttpConnectionFailed,
    HttpConnectionFailedCodexErrorInfo,
    ResponseStreamDisconnected,
    ResponseStreamDisconnectedCodexErrorInfo,
    ResponseTooManyFailedAttempts,
    ResponseTooManyFailedAttemptsCodexErrorInfo,
    ThreadTokenUsage,
    ThreadTokenUsageUpdatedNotification,
    TokenUsageBreakdown,
    Turn,
    TurnCompletedNotification,
    TurnError,
)

from Isabelle_Semantic_Embedding.interpretation_driver import config as C  # noqa: E402
from Isabelle_Semantic_Embedding.interpretation_driver.codex import (      # noqa: E402
    CodexDriver,
    classify_turn_error,
)
from Isabelle_Semantic_Embedding.semantic_interpretation import (          # noqa: E402
    USER_ERROR_MARKER,
    FatalAgentError,
    PoisonedSessionError,
    ReachLimitError,
    TransientAgentError,
)

from test_interpretation_driver import _make_task                  # noqa: E402


MODEL = "priced-model"


@pytest.fixture
def priced(tmp_path, monkeypatch):
    """A price table naming MODEL, at round numbers so a bill can be read."""
    path = tmp_path / "interpretation_config"
    path.write_text(yaml.safe_dump({"models": {MODEL: {"pricing": {
        "input": 10.0, "cached_input": 1.0, "output": 100.0}}}}), encoding="utf-8")
    monkeypatch.setenv("INTERPRETATION_CONFIG_PATH", str(path))
    C.load_interpretation_config(force_reload=True)
    yield
    C.load_interpretation_config(force_reload=True)


def _driver(task, model=MODEL):
    return CodexDriver(model=model, system_prompt="sys", tools=[], task=task,
                       on_context_reset=lambda: None)


# --- what a turn costs ------------------------------------------------------

def _usage(method_total, last):
    """One `thread/tokenUsage/updated` notification."""
    return Notification(
        method="thread/tokenUsage/updated",
        payload=ThreadTokenUsageUpdatedNotification(
            threadId="t", turnId="u",
            tokenUsage=ThreadTokenUsage(last=last, total=method_total)))


def _breakdown(input_tokens=0, cached=0, output=0):
    return TokenUsageBreakdown(
        inputTokens=input_tokens, cachedInputTokens=cached, outputTokens=output,
        reasoningOutputTokens=0, totalTokens=input_tokens + output)


def _completed(error=None):
    return Notification(
        method="turn/completed",
        payload=TurnCompletedNotification(
            threadId="t", turn=Turn(id="u", items=[], status="completed",
                                    error=error)))


class _FakeHandle:
    def __init__(self, notifications):
        self._notifications = notifications

    async def stream(self):
        for n in self._notifications:
            yield n


class _FakeThread:
    id = "thread-1"

    def __init__(self, notifications):
        self._notifications = notifications
        self.prompts: list[str] = []

    async def turn(self, prompt, **kw):
        self.prompts.append(prompt)
        return _FakeHandle(self._notifications)


def _run_turn(driver, notifications, prompt="go"):
    driver._thread = _FakeThread(notifications)
    asyncio.run(driver.run_turn(prompt))


def test_a_turn_is_billed_from_the_whole_advance_not_the_last_request(priced):
    """One turn makes one model request per tool call.  `usage.last` is only the
    final request, so billing from it undercounts a tool-using turn severalfold
    -- with a figure that looks entirely plausible."""
    task = _make_task(1, batch_size=1)
    driver = _driver(task)
    _run_turn(driver, [
        # total climbs 0 -> 100 -> 300 while `last` stays small
        _usage(_breakdown(input_tokens=100), _breakdown(input_tokens=100)),
        _usage(_breakdown(input_tokens=300, output=5), _breakdown(input_tokens=200)),
        _completed(),
    ])
    # input 300 at $10, output 5 at $100 -> 3000 + 500
    assert task.cost_flushes == [(300, 0, 0, 5, 3500.0)]


def test_cached_input_is_billed_at_its_own_rate_and_recorded_as_a_cache_read(priced):
    task = _make_task(1, batch_size=1)
    driver = _driver(task)
    _run_turn(driver, [
        _usage(_breakdown(input_tokens=100, cached=40), _breakdown()),
        _completed(),
    ])
    # 60 uncached at $10 + 40 cached at $1 = 640; and what is stored under
    # "input" is the uncached remainder, as on the Claude Code path.
    (uncached, cache_write, cache_read, output, cost), = task.cost_flushes
    assert (uncached, cache_write, cache_read, output) == (60, 0, 40, 0)
    assert cost == 640.0


def test_a_turn_that_reports_nothing_costs_nothing(priced):
    task = _make_task(1, batch_size=1)
    driver = _driver(task)
    _run_turn(driver, [_completed()])
    assert task.cost_flushes == [(0, 0, 0, 0, 0.0)]


def test_a_turn_bills_only_its_own_advance(priced):
    """The second turn must not be charged for the first one again."""
    task = _make_task(1, batch_size=1)
    driver = _driver(task)
    _run_turn(driver, [_usage(_breakdown(input_tokens=100), _breakdown()), _completed()])
    _run_turn(driver, [_usage(_breakdown(input_tokens=250), _breakdown()), _completed()])
    assert [f[0] for f in task.cost_flushes] == [100, 150]


# --- what a failed turn means ----------------------------------------------

def _obj(cls, inner_cls, field, status=None):
    return CodexErrorInfo(cls(**{field: inner_cls(httpStatusCode=status)}))


@pytest.mark.parametrize("info,expected", [
    (CodexErrorInfo(CodexErrorInfoValue.usage_limit_exceeded), ReachLimitError),
    (CodexErrorInfo(CodexErrorInfoValue.unauthorized), FatalAgentError),
    (CodexErrorInfo(CodexErrorInfoValue.bad_request), FatalAgentError),
    (CodexErrorInfo(CodexErrorInfoValue.cyber_policy), FatalAgentError),
    (CodexErrorInfo(CodexErrorInfoValue.session_budget_exceeded), FatalAgentError),
    (CodexErrorInfo(CodexErrorInfoValue.context_window_exceeded), PoisonedSessionError),
    (CodexErrorInfo(CodexErrorInfoValue.server_overloaded), TransientAgentError),
    (CodexErrorInfo(CodexErrorInfoValue.internal_server_error), TransientAgentError),
    (CodexErrorInfo(CodexErrorInfoValue.sandbox_error), TransientAgentError),
    (CodexErrorInfo(CodexErrorInfoValue.thread_rollback_failed), TransientAgentError),
    (CodexErrorInfo(CodexErrorInfoValue.other), TransientAgentError),
])
def test_each_error_value_maps_to_a_shared_failure_class(info, expected):
    assert isinstance(classify_turn_error(TurnError(message="m", codexErrorInfo=info)),
                      expected)


@pytest.mark.parametrize("cls,inner,field", [
    (HttpConnectionFailedCodexErrorInfo, HttpConnectionFailed, "httpConnectionFailed"),
    (ResponseStreamDisconnectedCodexErrorInfo, ResponseStreamDisconnected,
     "responseStreamDisconnected"),
    (ResponseTooManyFailedAttemptsCodexErrorInfo, ResponseTooManyFailedAttempts,
     "responseTooManyFailedAttempts"),
])
def test_the_network_variants_are_transient_not_fatal(cls, inner, field):
    """These four are objects, not enum members, and they are exactly the
    network failures -- `responseTooManyFailedAttempts` being the terminal state
    of the CLI's own retries, so the likeliest failure of a long run.  Reading
    the union as an enum drops every one of them into the fall-through."""
    err = TurnError(message="m", codexErrorInfo=_obj(cls, inner, field, 502))
    assert isinstance(classify_turn_error(err), TransientAgentError)


@pytest.mark.parametrize("status,expected", [
    (429, ReachLimitError),
    (401, FatalAgentError),
    (403, FatalAgentError),
    (500, TransientAgentError),
    (None, TransientAgentError),
])
def test_the_http_status_inside_a_network_variant_is_read(status, expected):
    """It sits one level deeper than the union suggests."""
    err = TurnError(message="m", codexErrorInfo=_obj(
        HttpConnectionFailedCodexErrorInfo, HttpConnectionFailed,
        "httpConnectionFailed", status))
    assert isinstance(classify_turn_error(err), expected)


def test_an_unrecognisable_failure_is_transient():
    """The opposite polarity to the Claude Code driver, deliberately: this
    backend fails mostly by network, and killing a whole theory cone hours into
    a run over one dropped stream is the worse mistake."""
    assert isinstance(classify_turn_error(TurnError(message="m")), TransientAgentError)
    err = TurnError(message="m", codexErrorInfo=CodexErrorInfo(
        ActiveTurnNotSteerableCodexErrorInfo(
            activeTurnNotSteerable=ActiveTurnNotSteerable(turnKind="review"))))
    assert isinstance(classify_turn_error(err), TransientAgentError)


def test_a_failed_turn_raises_out_of_run_turn(priced):
    task = _make_task(1, batch_size=1)
    driver = _driver(task)
    err = TurnError(message="context is full",
                    codexErrorInfo=CodexErrorInfo(
                        CodexErrorInfoValue.context_window_exceeded))
    with pytest.raises(PoisonedSessionError):
        _run_turn(driver, [_usage(_breakdown(input_tokens=10), _breakdown()),
                           _completed(error=err)])
    # The turn still cost what it cost; the failure does not erase it.
    assert task.cost_flushes == [(10, 0, 0, 0, 100.0)]


# --- refusing to start ------------------------------------------------------

def test_the_model_has_to_be_spelled_out(priced):
    """Codex has no default model we could name, let alone price."""
    with pytest.raises(FatalAgentError) as e:
        _driver(_make_task(1, batch_size=1), model="")
    assert str(e.value).startswith(USER_ERROR_MARKER)
    assert "Codex.gpt-5.5" in str(e.value)


def test_an_unpriced_model_is_refused_before_anything_is_spent(priced):
    with pytest.raises(FatalAgentError) as e:
        _driver(_make_task(1, batch_size=1), model="never-heard-of-it")
    assert str(e.value).startswith(USER_ERROR_MARKER)
    assert "never-heard-of-it" in str(e.value)


def test_it_declares_that_it_cannot_report_a_compaction():
    """Which is what turns off the desugar tool's per-constant dedup: 0.144.4
    sends no compaction notification and runs no SDK-registered hook, so nothing
    could clear the record of what has already been explained."""
    from Isabelle_Semantic_Embedding.interpretation_driver.claude_code import (
        ClaudeCodeDriver)
    assert CodexDriver.REPORTS_CONTEXT_RESET is False
    assert ClaudeCodeDriver.REPORTS_CONTEXT_RESET is True
