"""The DeepSeek interpretation driver: the Claude Code CLI, redirected.

DeepSeek ships no agent CLI of its own; its documented route to agentic
tooling is an Anthropic-compatible endpoint that the unmodified Claude Code
CLI can be pointed at.  So this driver IS `ClaudeCodeDriver` -- same tools,
skills, hooks and message classification -- with the CLI's traffic sent to
DeepSeek and everything that is true only of Anthropic's own API overridden.

Measured against the live endpoint (2026-08-27):
- It accepts real model names (`deepseek-v4-pro`) and echoes them back; a
  bogus name is a hard invalid_request_error, never a silent substitution.
- The CLI's `total_cost_usd` prices tokens at Anthropic list prices, so
  `_turn_cost_usd` recomputes from tokens.  How far the CLI's figure lands
  above ours depends on the turn's cache-hit ratio: 4.8x on a cache-heavy
  turn, ~100x on a cache-miss-dominated one.
- Usage follows the Anthropic convention: `input_tokens` EXCLUDES cache
  reads (`cache_read_input_tokens`); cache writes report as 0 (DeepSeek's
  prefix cache is automatic; a write is just miss-priced input).
- The CLI does not recognize these models, so auto-compact needs BOTH env
  vars in `_options` -- one declares the window, the other enforces it.
"""

from __future__ import annotations

import os
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from ..semantic_interpretation import FatalAgentError
from . import register_interpretation_driver
from .claude_code import ClaudeCodeDriver
from .config import MissingPricing, pricing_of

_BASE_URL = "https://api.deepseek.com/anthropic"
# Deliberately NOT honoring $DEEPSEEK_BASE_URL: in this repo that variable
# already means AoA's OpenAI-compatible endpoint (/beta), which speaks a
# different protocol.  One name may not mean two incompatible endpoints.

# The two env lists below were read out of the Claude Code CLI binary at
# version 2.1.247; re-extract them when the CLI major-updates.

# Vars that would redirect the CLI's traffic or credentials past
# ANTHROPIC_BASE_URL.  options.env can override but never REMOVE an inherited
# variable, and ""-means-unset is unverified -- so a set one is refused, not
# scrubbed (the failure it prevents: Claude traffic recorded as
# driver="DeepSeek" at DeepSeek prices, silently).  The CLI's federated
# credential vars (ANTHROPIC_IDENTITY_TOKEN, _FILE, ANTHROPIC_FEDERATION_RULE_ID,
# ANTHROPIC_ORGANIZATION_ID) are deliberately NOT here: the profile they build
# still takes its base URL from ANTHROPIC_BASE_URL, which we pin, so they can
# only produce a credential DeepSeek rejects loudly -- and refusing to start
# is too heavy a hammer for that.
_HIJACK_ENV = (
    "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_UNIX_SOCKET",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_GATEWAY",
    "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_API_BASE_URL",
)

# Every model the CLI may select. `--model` pins only the main loop; each of
# these is pinned to the SAME model, because the CLI's built-in fallbacks are
# Claude names this endpoint hard-rejects, and a weaker model writing the
# compaction summary would be a second quality variable.  Whether each path
# fires in headless SDK use is unmeasured -- pinning makes it not matter.
_AUX_MODEL_ENV = (
    "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_BG_CLASSIFIER_MODEL",
    "CLAUDE_CONTEXT_COLLAPSE_MODEL", "CLAUDE_CODE_AUTO_MODE_MODEL",
)


@register_interpretation_driver("DeepSeek")
class DeepSeekDriver(ClaudeCodeDriver):

    DEFAULT_MODEL = "deepseek-v4-pro"

    # The window to run with, per model.  The CLI does not recognise these
    # models, so left alone it applies the window it assumes for an unknown
    # one; the two env vars in _options override that.  The models serve 1M;
    # 384K is the practical cap AoA settled on
    # (contrib/Isa-Mini/IsaMini/AoA/driver_openai_api.py), owner-ruled here.
    # A value here must lie in 100_000..1_000_000: the CLI clamps its
    # enforcement knob to that range, and a smaller number would arm
    # compaction ABOVE the window we declare.
    CONTEXT_WINDOW = {"deepseek-v4-pro": 384_000,
                      "deepseek-v4-flash": 384_000}

    MSG_AUTH_FAILED = (
        "Semantic interpretation failed: DeepSeek rejected the API key. "
        "Check DEEPSEEK_API_KEY in the environment, then retry.")
    MSG_BILLING = (
        "Semantic interpretation failed: the DeepSeek account has a billing "
        "problem (out of balance?). Top it up, then retry.")
    MSG_INVALID_REQUEST = (
        "Semantic interpretation failed: DeepSeek rejected the request as "
        "invalid. Most often this is the model name in the driver spec -- "
        "this backend runs deepseek-v4-pro and deepseek-v4-flash. If the "
        "model name is right, this is a bug - please report it with the RPC "
        "host log.")

    @property
    def status_messages(self) -> dict[int, str]:
        # 402 (out of balance) is DeepSeek's most likely operational failure;
        # whether the adapter actually surfaces it as a status is unverified
        # -- if it does not, the unrecognised bucket still catches it loudly.
        return {**super().status_messages, 402: self.MSG_BILLING}

    @property
    def billable_models(self) -> set[str]:
        # Every model selector is pinned in _options, so exactly one model can
        # bill; anything else on a turn means a pin did not hold.
        return {self.model}

    @classmethod
    def canonical_model(cls, model: str) -> str:
        # AoA's documented shorthand for the same backend
        # (driver_openai_api.py): DeepSeek.V4-pro / DeepSeek.V4-flash.
        # Normalised HERE -- before the task exists -- so task.model, the
        # priced name and the name on the wire are one string.
        arg = super().canonical_model(model).lower()
        return f"deepseek-{arg}" if arg in ("v4-pro", "v4-flash") else arg

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not self._api_key:
            raise FatalAgentError(
                "Semantic interpretation failed: DEEPSEEK_API_KEY is not set "
                "in the environment, so the DeepSeek backend cannot "
                "authenticate. Export it, then retry.")
        hijacked = [v for v in _HIJACK_ENV if os.environ.get(v)]
        if hijacked:
            raise FatalAgentError(
                "Semantic interpretation failed: the environment sets "
                f"{', '.join(hijacked)}, which would redirect the Claude Code "
                "CLI's traffic or credentials away from DeepSeek while the "
                "database still records DeepSeek provenance. Unset them for "
                "this process, then retry.")
        # Both resolved before anything is spent, as the configuration errors
        # they are (the same shape as codex.py's pricing resolution).
        try:
            self._pricing = pricing_of(self.model)
        except MissingPricing as e:
            raise FatalAgentError(str(e)) from e
        window = self.CONTEXT_WINDOW.get(self.model)
        if window is None:
            raise FatalAgentError(
                f"Semantic interpretation failed: no context window is "
                f"curated for model {self.model!r} (deep_seek.py "
                f"CONTEXT_WINDOW). Add it, then retry.")
        self._context_window = window

    def _options(self) -> ClaudeAgentOptions:
        opts = super()._options()
        window = str(self._context_window)
        opts.env.update({
            "ANTHROPIC_BASE_URL": _BASE_URL,
            "ANTHROPIC_API_KEY": self._api_key,
            **{v: self.model for v in _AUX_MODEL_ENV},
            # Two vars, one number, because the CLI treats declaring and
            # enforcing as separate settings: for a model it does not
            # recognise, MAX_CONTEXT_TOKENS states the window but leaves
            # compaction unarmed ("this session can grow past it", in the
            # CLI's own words -- measured 2026-08-27: eight turns ran far
            # past the declared window and nothing compacted), while
            # AUTO_COMPACT_WINDOW is the knob that arms it.  With both set,
            # auto-compact fires and the inherited PreCompact hook reaches
            # on_context_reset (also measured).  The trigger sits a summary
            # buffer below the window and is checked at turn boundaries.
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": window,
            "CLAUDE_CODE_AUTO_COMPACT_WINDOW": window,
        })
        return opts

    def _turn_cost_usd(self, *, input_tokens: int, cache_creation_tokens: int,
                       cache_read_tokens: int, output_tokens: int,
                       reported_usd: float) -> float:
        # reported_usd is the CLI's Anthropic-priced figure -- ignored.
        # Pricing.cost wants the INCLUSIVE input count; this endpoint's
        # input_tokens EXCLUDES cache reads, and a cache write here is just
        # miss-priced input, so both join the sum.
        return self._pricing.cost(
            input_tokens=input_tokens + cache_creation_tokens + cache_read_tokens,
            cached_input_tokens=cache_read_tokens,
            output_tokens=output_tokens)
