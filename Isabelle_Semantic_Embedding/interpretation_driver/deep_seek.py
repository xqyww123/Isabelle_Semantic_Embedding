"""The DeepSeek interpretation driver: the Claude Code CLI, redirected.

DeepSeek ships no agent CLI of its own; its documented route to agentic
tooling is an Anthropic-compatible endpoint that the unmodified Claude Code
CLI can be pointed at.  So this driver IS `ClaudeCodeDriver` -- same tools,
skills, hooks and message classification -- with the CLI's traffic sent to
DeepSeek and everything that is true only of Anthropic's own API overridden.

Measured against the live endpoint (2026-08-27):
- It accepts real model names (`deepseek-v4-pro`) and echoes them back; a
  bogus name is a hard invalid_request_error, never a silent substitution.
- The CLI's `total_cost_usd` prices tokens at Anthropic list prices --
  measured ~100x too high here -- so `_turn_cost_usd` recomputes from tokens.
- Usage follows the Anthropic convention: `input_tokens` EXCLUDES cache
  reads (`cache_read_input_tokens`); cache writes report as 0 (DeepSeek's
  prefix cache is automatic; a write is just miss-priced input).
- The CLI does not recognize DeepSeek models and would clamp auto-compact to
  a GUESSED context window; `CLAUDE_CODE_MAX_CONTEXT_TOKENS` is its own
  documented remedy.
"""

from __future__ import annotations

import os
from typing import Any

from ..semantic_interpretation import FatalAgentError
from . import register_interpretation_driver
from .claude_code import ClaudeCodeDriver
from .config import MissingPricing, pricing_of

_BASE_URL = "https://api.deepseek.com/anthropic"
# Deliberately NOT honoring $DEEPSEEK_BASE_URL: in this repo that variable
# already means AoA's OpenAI-compatible endpoint (/beta), which speaks a
# different protocol.  One name may not mean two incompatible endpoints.

# Env vars that would redirect the CLI's traffic or credentials past
# ANTHROPIC_BASE_URL.  options.env can override but never REMOVE an inherited
# variable, and ""-means-unset is unverified -- so a set one is refused, not
# scrubbed (the failure it prevents: Claude traffic recorded as
# driver="DeepSeek" at DeepSeek prices, silently).
_HIJACK_ENV = (
    "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_UNIX_SOCKET",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_GATEWAY",
    "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_API_BASE_URL",
)


@register_interpretation_driver("DeepSeek")
class DeepSeekDriver(ClaudeCodeDriver):

    DEFAULT_MODEL = "deepseek-v4-pro"

    # Real windows for models the CLI does not recognize (it would otherwise
    # clamp auto-compact to a GUESSED window -- systematic premature
    # compaction).  The models serve 1M; 384K is the practical cap AoA
    # settled on (contrib/Isa-Mini/IsaMini/AoA/driver_openai_api.py),
    # owner-ruled here.
    CONTEXT_WINDOW = {"deepseek-v4-pro": 384_000,
                      "deepseek-v4-flash": 384_000,
                      "deepseek-v4-flash-vision-exp": 384_000}

    MSG_AUTH_FAILED = (
        "Semantic interpretation failed: DeepSeek rejected the API key. "
        "Check DEEPSEEK_API_KEY in the environment, then retry.")
    MSG_BILLING = (
        "Semantic interpretation failed: the DeepSeek account has a billing "
        "problem (out of balance?). Top it up, then retry.")
    MSG_INVALID_REQUEST = (
        "Semantic interpretation failed: DeepSeek rejected the request as "
        "invalid. Most often this is the model name in the driver spec -- "
        "DeepSeek serves deepseek-v4-pro, deepseek-v4-flash and "
        "deepseek-v4-flash-vision-exp. If the model name is right, this is "
        "a bug - please report it with the RPC host log.")

    @property
    def status_messages(self) -> dict[int, str]:
        # 402 (out of balance) is DeepSeek's most likely operational failure;
        # whether the adapter actually surfaces it as a status is unverified
        # -- if it does not, the unrecognised bucket still catches it loudly.
        return {**super().status_messages, 402: self.MSG_BILLING}

    @classmethod
    def canonical_model(cls, model: str) -> str:
        # AoA's documented shorthand for the same backend
        # (driver_openai_api.py): DeepSeek.V4-pro / DeepSeek.V4-flash.
        # Normalised HERE -- before the task exists -- so task.model, the
        # priced name and the name on the wire are one string.
        arg = (model or "v4-pro").strip().lower()
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

    def _options(self):
        opts = super()._options()
        opts.env.update({
            "ANTHROPIC_BASE_URL": _BASE_URL,
            "ANTHROPIC_API_KEY": self._api_key,
            # --model pins only the MAIN loop.  Every other model the CLI may
            # reach for is pinned to the SAME model: the CLI's built-in
            # fallbacks are Claude names this endpoint hard-rejects, and a
            # weaker model writing the compaction summary would be a second
            # quality variable.  Whether each aux path fires in headless SDK
            # use is unmeasured -- pinning makes the answer not matter.
            "ANTHROPIC_MODEL": self.model,
            "ANTHROPIC_SMALL_FAST_MODEL": self.model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": self.model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": self.model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": self.model,
            "ANTHROPIC_DEFAULT_FABLE_MODEL": self.model,
            "CLAUDE_CODE_SUBAGENT_MODEL": self.model,
            "CLAUDE_CODE_BG_CLASSIFIER_MODEL": self.model,
            "CLAUDE_CONTEXT_COLLAPSE_MODEL": self.model,
            "CLAUDE_CODE_AUTO_MODE_MODEL": self.model,
            # The CLI does not recognise this model and would otherwise
            # ASSUME its context window; this variable is its own documented
            # remedy.  DECLARING the window is not ENFORCING it, though: for
            # an unrecognised model the CLI leaves threshold-triggered
            # compaction off ("this session can grow past it" -- its words)
            # and defers to an API prompt-too-long signal that only
            # Anthropic's own API is known to send.  The second variable is
            # the CLI's own enforcement knob; with it set, auto-compact fires
            # and the PreCompact hook reaches on_context_reset (measured
            # 2026-08-27; trigger lands at <= window - 13000, checked at turn
            # boundaries, so it can run somewhat late).
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(self._context_window),
            "CLAUDE_CODE_AUTO_COMPACT_WINDOW": str(self._context_window),
        })
        return opts

    def _turn_cost_usd(self, *, input_tokens: int, cache_creation_tokens: int,
                       cache_read_tokens: int, output_tokens: int,
                       reported_usd: float) -> float:
        # reported_usd is the CLI's Anthropic-priced figure -- ignored
        # (measured ~100x too high).  Pricing.cost wants the INCLUSIVE input
        # count; this endpoint's input_tokens EXCLUDES cache reads, and a
        # cache write here is just miss-priced input, so both join the sum.
        return self._pricing.cost(
            input_tokens=input_tokens + cache_creation_tokens + cache_read_tokens,
            cached_input_tokens=cache_read_tokens,
            output_tokens=output_tokens)
