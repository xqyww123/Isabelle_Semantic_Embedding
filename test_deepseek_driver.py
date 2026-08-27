"""Tests for the DeepSeek interpretation driver (no network, no LMDB).

What these pin down is the owner's provenance requirement: a run through this
driver must be recorded as driver="DeepSeek", model="deepseek-v4-pro", at
DeepSeek prices -- never as a Claude model, never at Claude prices, and never
silently otherwise.  Hence the guards (refuse to start when the environment
would redirect the CLI), the env pins, and the repricing test.
"""
import pytest
from claude_agent_sdk.types import ResultMessage

import Isabelle_Semantic_Embedding.interpretation_driver.deep_seek as DS
from Isabelle_Semantic_Embedding.interpretation_driver.config import (
    MissingPricing,
    Pricing,
)
from Isabelle_Semantic_Embedding.semantic_interpretation import (
    FatalAgentError,
    InterpretationTask,
)

# The peak list rates (2026-08-27); the config file is deliberately not read.
_V4_PRO = Pricing(input=1.32e-6, cached_input=4.4e-8, output=3.96e-6)


@pytest.fixture(autouse=True)
def _controlled_environment(monkeypatch):
    """A deterministic environment: the key is set, no hijack var is, and
    pricing comes from the constant above rather than the user's config."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    for var in DS._HIJACK_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(DS, "pricing_of", lambda model: _V4_PRO)


class _StubTask(InterpretationTask):
    """A real InterpretationTask with the LMDB flush counted instead."""

    def __init__(self):
        super().__init__(None, "/tmp/T.thy", "T", b"\x00" * 32, [],
                         driver="DeepSeek", model="deepseek-v4-pro")
        self.cost_writes = 0

    def write_cost(self):
        self.cost_writes += 1


def _driver(model="deepseek-v4-pro"):
    return DS.DeepSeekDriver(model=model, system_prompt="s", tools=[],
                             task=_StubTask(), on_context_reset=lambda: None)


# --- the model-name shorthand ----------------------------------------------

def test_canonical_model_expands_the_shorthands():
    """AoA's vocabulary (DeepSeek.V4-pro) and the bare driver name both land
    on canonical names -- BEFORE the task exists, so the recorded, priced and
    transmitted names are one string."""
    assert DS.DeepSeekDriver.canonical_model("") == "deepseek-v4-pro"
    assert DS.DeepSeekDriver.canonical_model("V4-pro") == "deepseek-v4-pro"
    assert DS.DeepSeekDriver.canonical_model("v4-flash") == "deepseek-v4-flash"


def test_canonical_model_passes_other_names_through():
    assert DS.DeepSeekDriver.canonical_model("deepseek-v4-pro") == "deepseek-v4-pro"
    assert DS.DeepSeekDriver.canonical_model("deepseek-v4-flash-vision-exp") \
        == "deepseek-v4-flash-vision-exp"


# --- refuse to start rather than run wrong ----------------------------------

def test_missing_api_key_is_fatal_and_names_the_variable(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(FatalAgentError) as e:
        _driver()
    assert "DEEPSEEK_API_KEY" in str(e.value)


def test_a_hijacking_env_var_is_refused_and_named(monkeypatch):
    """options.env can override but never REMOVE an inherited variable, so an
    env var that would redirect the CLI's traffic or credentials cannot be
    neutralised -- the driver must refuse to start."""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-something")
    with pytest.raises(FatalAgentError) as e:
        _driver()
    assert "ANTHROPIC_AUTH_TOKEN" in str(e.value)


def test_missing_pricing_is_fatal_at_construction(monkeypatch):
    def no_pricing(model):
        raise MissingPricing(model)
    monkeypatch.setattr(DS, "pricing_of", no_pricing)
    with pytest.raises(FatalAgentError) as e:
        _driver()
    assert "deepseek-v4-pro" in str(e.value)


def test_a_model_without_a_curated_context_window_is_fatal():
    """A model that is priced but absent from CONTEXT_WINDOW would run with
    the CLI's GUESSED window (systematic premature compaction); refuse."""
    with pytest.raises(FatalAgentError) as e:
        _driver(model="deepseek-v5")
    assert "CONTEXT_WINDOW" in str(e.value)


# --- the environment handed to the CLI --------------------------------------

def test_options_env_pins_endpoint_key_models_and_window():
    env = _driver()._options().env
    assert env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert env["ANTHROPIC_API_KEY"] == "test-key"
    for var in ("ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL",
                "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_BG_CLASSIFIER_MODEL",
                "CLAUDE_CONTEXT_COLLAPSE_MODEL", "CLAUDE_CODE_AUTO_MODE_MODEL"):
        assert env[var] == "deepseek-v4-pro", var
    # Declared window AND the enforcement knob -- the CLI treats them as two
    # settings, and without the second, compaction never fires for a model it
    # does not recognise.
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "384000"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "384000"
    # The base class's own env entry must survive the update.
    assert env["MAX_MCP_OUTPUT_TOKENS"] == "100000"


# --- repricing ---------------------------------------------------------------

def test_cost_is_recomputed_from_tokens_not_the_cli_figure():
    """The probe shape that measured the ~100x gap: the CLI said $0.142204,
    DeepSeek's rates say ~$0.0002.  input_tokens EXCLUDES cache reads on this
    endpoint, so the cached tokens join the input sum and are billed at the
    cache-hit rate."""
    driver = _driver()
    task = driver.task
    driver._handle_message(ResultMessage(
        subtype="success", duration_ms=100, duration_api_ms=0, is_error=False,
        num_turns=1, session_id="s", total_cost_usd=0.142204,
        usage={"input_tokens": 9, "cache_read_input_tokens": 1280,
               "output_tokens": 16}))
    expected = 9 * 1.32e-6 + 1280 * 4.4e-8 + 16 * 3.96e-6
    assert task.total_cost_usd == pytest.approx(expected)
    assert task.total_cost_usd != pytest.approx(0.142204)
    assert (task.total_input_tokens, task.total_cache_read_tokens,
            task.total_output_tokens) == (9, 1280, 16)
    assert task.cost_writes == 1


# --- vendor wording ----------------------------------------------------------

def test_status_messages_carry_the_deepseek_wording():
    """The property-not-class-dict trap: were `status_messages` a class-body
    dict on the base, the 401 entry would still carry the Claude wording."""
    table = _driver().status_messages
    assert "DEEPSEEK_API_KEY" in table[401]
    assert "balance" in table[402]
