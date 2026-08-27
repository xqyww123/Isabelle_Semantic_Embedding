"""Tests for the interpretation failure classifier (ClaudeCodeDriver._handle_message).

The regression these guard: an unauthenticated Claude Code CLI does NOT raise.
`connect()` succeeds and the failure arrives as an ordinary ResultMessage whose
`subtype` is still 'success' and whose only honest signal is `is_error`.  Before
the fail-safe branch existed, that message flowed through as if the round had
succeeded -- every entry stayed unanswered, the retry loop gave up quietly, and
Isabelle marked the whole cone interpreted with nothing in it.
"""
import pytest
from claude_agent_sdk.types import AssistantMessage, ResultMessage, SystemMessage

from Isabelle_Semantic_Embedding.interpretation_driver.claude_code import (
    ClaudeCodeDriver,
)
from Isabelle_Semantic_Embedding.semantic_interpretation import (
    FatalAgentError,
    InterpretationTask,
    RateLimitError,
    ReachLimitError,
    PoisonedSessionError,
    TransientAgentError,
    USER_ERROR_MARKER,
)


class _StubTask(InterpretationTask):
    """A real InterpretationTask (so any field the classifier reads exists),
    with the LMDB flush counted instead of performed."""

    def __init__(self):
        super().__init__(None, "/tmp/T.thy", "T", b"\x00" * 32, [])
        self.cost_writes = 0

    def write_cost(self):
        self.cost_writes += 1


def _driver(task):
    return ClaudeCodeDriver(model="m", system_prompt="s", tools=[],
                            task=task, on_context_reset=lambda: None)


def _result(**kw):
    base = dict(subtype="success", duration_ms=100, duration_api_ms=0,
                is_error=False, num_turns=1, session_id="s")
    base.update(kw)
    return ResultMessage(**base)


def _assistant(error=None):
    return AssistantMessage(content=[], model="m", error=error)


# --- the headline case ------------------------------------------------------

def test_unauthenticated_result_raises_despite_subtype_success():
    """The exact shape observed from a credential-free CLI: is_error is True but
    subtype still says 'success'.  Branching on subtype would miss it."""
    msg = _result(is_error=True, subtype="success",
                  result="Not logged in · Please run /login")
    with pytest.raises(FatalAgentError) as e:
        _driver(_StubTask())._handle_message(msg)
    assert e.value.human is not None, "should be a recognised, one-line failure"
    assert "authenticate" in e.value.human.lower()
    assert "/login" in e.value.human
    assert str(e.value).startswith(USER_ERROR_MARKER)


def test_successful_result_does_not_raise():
    _driver(_StubTask())._handle_message(
        _result(is_error=False, result="fine", total_cost_usd=0.1))


def test_claudecode_cost_passes_through_unrepriced():
    """Pins "the ClaudeCode path is observably unchanged" through the driver
    refactor: the CLI's own dollar figure is recorded as-is (its tokens are
    never repriced), and the round's usage is flushed exactly once."""
    task = _StubTask()
    usage = {"input_tokens": 9, "cache_creation_input_tokens": 3,
             "cache_read_input_tokens": 1280, "output_tokens": 16}
    _driver(task)._handle_message(
        _result(is_error=False, total_cost_usd=0.1, usage=usage))
    assert task.total_cost_usd == 0.1
    assert (task.total_input_tokens, task.total_cache_creation_tokens,
            task.total_cache_read_tokens, task.total_output_tokens) \
        == (9, 3, 1280, 16)
    assert task.cost_writes == 1


# --- the structured enum ----------------------------------------------------

@pytest.mark.parametrize("err,exc", [
    ("rate_limit", RateLimitError),
    ("server_error", TransientAgentError),
    ("authentication_failed", FatalAgentError),
    ("billing_error", FatalAgentError),
    ("invalid_request", FatalAgentError),
])
def test_assistant_error_enum_is_classified(err, exc):
    with pytest.raises(exc):
        _driver(_StubTask())._handle_message(_assistant(error=err))


def test_assistant_without_error_does_not_raise():
    _driver(_StubTask())._handle_message(_assistant(error=None))


def test_unknown_enum_value_keeps_the_traceback():
    """No honest one-liner exists for 'unknown', so `human` stays None and the
    caller lets the full Python traceback through."""
    with pytest.raises(FatalAgentError) as e:
        _driver(_StubTask())._handle_message(_assistant(error="unknown"))
    assert e.value.human is None
    assert USER_ERROR_MARKER not in str(e.value)


# --- expired credentials vs dead network ------------------------------------

def test_api_retry_401_trail_identifies_expired_auth():
    """An expired token and an unreachable network terminate with byte-identical
    ResultMessages; only the api_retry trail tells them apart."""
    task = _StubTask()
    driver = _driver(task)
    driver._handle_message(SystemMessage(
        subtype="api_retry",
        data={"error_status": 401, "error": "authentication_failed"}))
    assert task.api_retry_errors == [(401, "authentication_failed")]

    with pytest.raises(FatalAgentError) as e:
        driver._handle_message(_result(is_error=True, subtype="error_during_execution",
                                       errors=["[ede_diagnostic] result_type=user"]))
    assert e.value.human is not None
    assert "/login" in e.value.human


def test_network_failure_trail_is_not_reported_as_auth():
    driver = _driver(_StubTask())
    driver._handle_message(SystemMessage(
        subtype="api_retry", data={"error_status": None, "error": "unknown"}))
    with pytest.raises(FatalAgentError) as e:
        driver._handle_message(_result(is_error=True, subtype="error_during_execution"))
    assert e.value.human is None, "must not claim an auth problem it cannot prove"


# --- previously recognised conditions still behave --------------------------

def test_api_400_is_still_a_poisoned_session():
    with pytest.raises(PoisonedSessionError):
        _driver(_StubTask())._handle_message(
            _result(is_error=True, api_error_status=400))


def test_usage_cap_text_still_raises_reach_limit():
    with pytest.raises(ReachLimitError):
        _driver(_StubTask())._handle_message(
            _result(is_error=True, result="You've hit your limit for today"))


def test_unrecognised_error_result_raises_with_detail():
    with pytest.raises(FatalAgentError) as e:
        _driver(_StubTask())._handle_message(
            _result(is_error=True, result="something novel"))
    assert e.value.human is None
    assert "something novel" in e.value.detail
