"""Tests for the DeepSeek interpretation driver (no network, no LMDB).

What these pin down is the owner's provenance requirement: a run through this
driver must be recorded as driver="DeepSeek", model="deepseek-v4-pro", at
DeepSeek prices -- never as a Claude model, never at Claude prices, and never
silently otherwise.  Hence the guards (refuse to start when the environment
would redirect the CLI), the env pins, the repricing, and the sentinel that
reads back which models actually billed.
"""
import pytest
from claude_agent_sdk.types import ResultMessage

import Isabelle_Semantic_Embedding.interpretation_driver.claude_code as CC
import Isabelle_Semantic_Embedding.interpretation_driver.config as C
import Isabelle_Semantic_Embedding.interpretation_driver.deep_seek as DS
from Isabelle_Semantic_Embedding.interpretation_driver.config import (
    MissingPricing,
    Pricing,
)
from Isabelle_Semantic_Embedding.semantic_interpretation import (
    FatalAgentError,
    InterpretationTask,
)

#: The peak list rates (2026-08-27).  Used BOTH as the pricing the cost test
#: runs against and as the expected value of the shipped table, so the two
#: cannot drift apart.
_V4_PRO = Pricing(input=1.32e-6, cached_input=4.4e-8, output=3.96e-6)


@pytest.fixture(autouse=True)
def _controlled_environment(monkeypatch):
    """A deterministic environment: the key is set, no hijack var is, pricing
    comes from the constant above rather than the user's config, and the
    process-wide record of already-reported models starts empty."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    for var in DS._HIJACK_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(DS, "pricing_of", lambda model: _V4_PRO)
    monkeypatch.setattr(CC, "_UNEXPECTED_BILLING_WARNED", set())


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


def test_a_blank_model_half_is_not_set_rather_than_a_model_name():
    """`DeepSeek. ` must mean "this backend's default", not the model named
    by a space: an empty name would be recorded while a real one was run."""
    assert DS.DeepSeekDriver.canonical_model("  ") == "deepseek-v4-pro"
    assert DS.DeepSeekDriver.canonical_model("\t") == "deepseek-v4-pro"


def test_canonical_model_is_idempotent():
    """It is applied at both doors -- resolution and construction -- so
    applying it twice must not move the name."""
    once = [DS.DeepSeekDriver.canonical_model(m)
            for m in ("", "  ", "V4-pro", " V4-Pro ", "v4-flash", "unknown-x")]
    assert [DS.DeepSeekDriver.canonical_model(m) for m in once] == once


def test_construction_lands_on_the_same_name_as_resolution():
    assert _driver(model="V4-pro").model == "deepseek-v4-pro"


# --- refuse to start rather than run wrong ----------------------------------

def test_missing_api_key_is_fatal_and_names_the_variable(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(FatalAgentError) as e:
        _driver()
    assert "DEEPSEEK_API_KEY" in str(e.value)


@pytest.mark.parametrize("var", DS._HIJACK_ENV)
def test_a_hijacking_env_var_is_refused_and_named(monkeypatch, var):
    """options.env can override but never REMOVE an inherited variable, so an
    env var that would redirect the CLI's traffic or credentials cannot be
    neutralised -- the driver must refuse to start, naming the one it found."""
    monkeypatch.setenv(var, "planted")
    with pytest.raises(FatalAgentError) as e:
        _driver()
    assert var in str(e.value)


def test_an_ambient_endpoint_is_warned_about_but_not_refused(monkeypatch, caplog):
    """The environment pointing ANTHROPIC_BASE_URL elsewhere is not a refusal --
    this driver overrides it.  It IS worth one warning, because that ambient
    value is what runs whenever the backend selection never reaches this class
    (measured: a DeepSeek run whose --driver flag stayed in the process driving
    the REPL, while the agent ran in the RPC host Isabelle starts, went to a
    third-party relay instead)."""
    monkeypatch.setattr(DS, "_ambient_base_url_warned", False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.somewhere-else.com")
    with caplog.at_level("WARNING"):
        driver = _driver()
        _driver()                      # second construction, same process
    assert driver._options().env["ANTHROPIC_BASE_URL"] == DS._BASE_URL
    warned = [r for r in caplog.records if "somewhere-else" in r.getMessage()]
    assert len(warned) == 1, "one line per process, not one per theory"


def test_our_own_endpoint_in_the_environment_is_not_warned_about(monkeypatch, caplog):
    monkeypatch.setattr(DS, "_ambient_base_url_warned", False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", DS._BASE_URL)
    with caplog.at_level("WARNING"):
        _driver()
    assert not caplog.records


def test_missing_pricing_is_fatal_at_construction(monkeypatch):
    def no_pricing(model):
        raise MissingPricing(model)
    monkeypatch.setattr(DS, "pricing_of", no_pricing)
    with pytest.raises(FatalAgentError) as e:
        _driver()
    assert "deepseek-v4-pro" in str(e.value)


def test_a_model_without_a_curated_context_window_is_fatal():
    """A model that is priced but absent from CONTEXT_WINDOW would run with
    the window the CLI assumes for a model it does not recognise; refuse."""
    with pytest.raises(FatalAgentError) as e:
        _driver(model="deepseek-v4-flash-vision-exp")
    assert "CONTEXT_WINDOW" in str(e.value)


# --- the shipped price table ------------------------------------------------

def test_the_shipped_template_prices_this_backend(monkeypatch):
    """Every other test here monkeypatches `pricing_of`, so without this one a
    wrong digit in the shipped table would record every run's dollars wrong
    with the suite still green.  Exact equality, not `> 0`: the failure to
    catch is a wrong rate, not a missing block."""
    monkeypatch.setenv("INTERPRETATION_CONFIG_PATH", str(C.template_path()))
    C.load_interpretation_config(force_reload=True)
    try:
        assert C.pricing_of(DS.DeepSeekDriver.DEFAULT_MODEL) == _V4_PRO
        assert C.pricing_of("deepseek-v4-flash") == Pricing(
            input=4.4e-7, cached_input=1.4e-8, output=1.32e-6)
    finally:
        C.load_interpretation_config(force_reload=True)


# --- the environment handed to the CLI --------------------------------------

def test_options_env_pins_endpoint_key_models_and_window():
    env = _driver()._options().env
    assert env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert env["ANTHROPIC_API_KEY"] == "test-key"
    for var in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_MODEL",
                "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                "ANTHROPIC_DEFAULT_FABLE_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL",
                "CLAUDE_CODE_BG_CLASSIFIER_MODEL", "CLAUDE_CONTEXT_COLLAPSE_MODEL",
                "CLAUDE_CODE_AUTO_MODE_MODEL"):
        assert env[var] == "deepseek-v4-pro", var
    # Declared window AND the enforcement knob -- the CLI treats them as two
    # settings, and without the second, compaction never fires for a model it
    # does not recognise.
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "384000"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "384000"
    # The base class's own env entry must survive the update.
    assert env["MAX_MCP_OUTPUT_TOKENS"] == "100000"


def test_every_curated_window_is_within_the_clis_enforceable_range():
    """The CLI clamps its enforcement knob to 100k..1M, so a value outside
    that range would arm compaction at a threshold unrelated to the window we
    declare."""
    assert all(100_000 <= w <= 1_000_000
               for w in DS.DeepSeekDriver.CONTEXT_WINDOW.values())


# --- repricing ---------------------------------------------------------------

def test_cost_is_recomputed_from_tokens_not_the_cli_figure():
    """The probe shape that measured the gap: the CLI priced this turn at
    Anthropic rates ($0.142204), DeepSeek's rates say ~$0.0002.  input_tokens
    EXCLUDES cache reads on this endpoint, and a cache write is just
    miss-priced input, so both join the input sum while only the cache reads
    are billed at the hit rate."""
    driver = _driver()
    task = driver.task
    driver._handle_message(ResultMessage(
        subtype="success", duration_ms=100, duration_api_ms=0, is_error=False,
        num_turns=1, session_id="s", total_cost_usd=0.142204,
        usage={"input_tokens": 9, "cache_creation_input_tokens": 3,
               "cache_read_input_tokens": 1280, "output_tokens": 16}))
    expected = (9 + 3) * 1.32e-6 + 1280 * 4.4e-8 + 16 * 3.96e-6
    assert task.total_cost_usd == pytest.approx(expected)
    assert task.total_cost_usd != pytest.approx(0.142204)
    assert (task.total_input_tokens, task.total_cache_creation_tokens,
            task.total_cache_read_tokens, task.total_output_tokens) \
        == (9, 3, 1280, 16)
    assert task.cost_writes == 1


# --- which models actually billed -------------------------------------------

def _turn(model_usage):
    return ResultMessage(subtype="success", duration_ms=100, duration_api_ms=0,
                         is_error=False, num_turns=1, session_id="s",
                         total_cost_usd=0.0, usage={"input_tokens": 1},
                         model_usage=model_usage)


def test_only_the_pinned_model_may_bill(caplog):
    """The per-model usage of the terminal message names EVERY model that
    billed, including the auxiliary ones the CLI picks itself -- which is the
    check that the ten env pins held.  It warns and never raises: a run
    billing correctly must not die because a sentinel disagrees."""
    driver = _driver()
    with caplog.at_level("WARNING"):
        driver._handle_message(_turn({"deepseek-v4-pro": {"costUSD": 0.1}}))
        assert not caplog.records, "the pinned model billing is the normal case"
        driver._handle_message(_turn({"deepseek-v4-pro": {}, "claude-haiku-4-5": {}}))
        driver._handle_message(_turn({"claude-haiku-4-5": {}}))
    warned = [r for r in caplog.records if "claude-haiku-4-5" in r.getMessage()]
    assert len(warned) == 1, "one line per unexpected model, however many turns"


def test_the_sentinel_is_inert_for_a_backend_that_does_not_pin(caplog):
    """ClaudeCode lets the CLI choose auxiliary models, so extra names there
    are normal and must not warn."""
    from Isabelle_Semantic_Embedding.interpretation_driver.claude_code import (
        ClaudeCodeDriver,
    )
    driver = ClaudeCodeDriver(model="", system_prompt="s", tools=[],
                              task=_StubTask(), on_context_reset=lambda: None)
    with caplog.at_level("WARNING"):
        driver._handle_message(_turn({"claude-opus-4-8": {}, "claude-haiku-4-5": {}}))
    assert not caplog.records


# --- vendor wording ----------------------------------------------------------

def test_status_messages_carry_the_deepseek_wording():
    """The property-not-class-dict trap: were `status_messages` a class-body
    dict on the base, the 401 entry would still carry the Claude wording."""
    table = _driver().status_messages
    assert "DEEPSEEK_API_KEY" in table[401]
    assert "balance" in table[402]


def test_the_terminal_status_outranks_the_retry_trail():
    """A run that ends out of balance, having survived a transient 401, must
    be told to top up the account -- not to check its API key."""
    driver = _driver()
    driver.task.api_retry_errors.append((401, "authentication_failed"))
    with pytest.raises(FatalAgentError) as e:
        driver._raise_for_agent_error(
            None, ResultMessage(subtype="error", duration_ms=1, duration_api_ms=0,
                                is_error=True, num_turns=1, session_id="s",
                                api_error_status=402))
    assert "balance" in str(e.value)
