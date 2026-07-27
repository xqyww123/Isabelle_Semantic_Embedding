"""The Codex interpretation driver.

Runs the interpretation agent through the official Codex Python SDK, which
spawns a `codex app-server` of its own.  The agent therefore lives in another
process and reaches the five interpretation tools over the HTTP MCP server in
`mcp_server`.  Everything else -- batching, retries, recycling -- is the shared
`_run_agent`'s, exactly as for Claude Code.

Requires the optional dependency: `pip install Isabelle_Semantic_Embedding[codex]`.

Three things here follow from measurements rather than from the SDK's shape, and
each is commented where it is done:

  - a turn's cost is the DIFFERENCE of `usage.total`, never `usage.last`;
  - `default_tools_approval_mode` must be "approve", or every tool call is
    auto-rejected;
  - an unrecognised failure is treated as transient, the opposite of the Claude
    Code driver's polarity, because this backend's failures are mostly network.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from openai_codex import ApprovalMode, AsyncCodex, Sandbox, TransportClosedError
from openai_codex.generated.v2_all import (
    ActiveTurnNotSteerableCodexErrorInfo,
    CodexErrorInfoValue,
    GetAccountRateLimitsResponse,
    ListMcpServerStatusResponse,
    ThreadTokenUsageUpdatedNotification,
    TokenUsageBreakdown,
    TurnCompletedNotification,
    TurnError,
)

from ..semantic_interpretation import (
    FatalAgentError,
    PoisonedSessionError,
    ReachLimitError,
    TransientAgentError,
)
from . import (
    AGENT_DIR,
    InterpretationDriver,
    accumulate_usage,
    register_interpretation_driver,
)
from .config import MissingPricing, pricing_of
from .mcp_server import SERVER_NAME, InterpretationMCPServer

_log = logging.getLogger(__name__)

#: How long to wait for the tool-registration check before giving up on it.
#: Generous: it is one local round trip, but it queues behind the app-server's
#: own startup.
_HEALTHCHECK_TIMEOUT_S = 30.0


# --- user-facing failure text -----------------------------------------------

_MSG_AUTH_FAILED = (
    "Semantic interpretation failed: Codex could not authenticate. Run 'codex "
    "login' (it may not be logged in, or the login may have expired), then retry.")

_MSG_BILLING = (
    "Semantic interpretation failed: the Codex account is out of credits. "
    "Top it up, then retry.")

_MSG_INVALID_REQUEST = (
    "Semantic interpretation failed: Codex rejected the request as invalid. "
    "This is a bug - please report it with the RPC host log.")

_MSG_SESSION_BUDGET = (
    "Semantic interpretation failed: the Codex session budget was exhausted.")


# --- error classification ---------------------------------------------------

#: Enum values whose remedy is to try again with a fresh session.
_TRANSIENT_VALUES = frozenset({
    CodexErrorInfoValue.internal_server_error,
    CodexErrorInfoValue.server_overloaded,
    CodexErrorInfoValue.sandbox_error,
    CodexErrorInfoValue.thread_rollback_failed,
    CodexErrorInfoValue.other,
})


_ZERO_USAGE = TokenUsageBreakdown(
    cached_input_tokens=0, input_tokens=0, output_tokens=0,
    reasoning_output_tokens=0, total_tokens=0)


def _http_status_of(root: Any) -> "int | None":
    """The HTTP status buried in one of the object-shaped error variants.

    Each wraps a single field holding a detail model, and each of those (bar
    the not-steerable one) carries `http_status_code` -- one hop deeper than a
    reader of the union would expect."""
    for inner in vars(root).values():
        status = getattr(inner, "http_status_code", None)
        if status is not None:
            return int(status)
    return None


def classify_turn_error(err: TurnError) -> Exception:
    """Which of the shared failure classes a failed turn belongs to.

    `codex_error_info` is NOT an enum: it is a union of the enum with five
    object variants, and FOUR of those object variants are precisely the
    network failures -- including `responseTooManyFailedAttempts`, the terminal
    state of the CLI's own internal retries and so the likeliest failure of a
    long run.  Reading it as an enum would drop every one of them into the
    fall-through.

    That fall-through is TRANSIENT, deliberately the opposite of the Claude Code
    driver's: this backend fails mostly by network, and defaulting an unknown
    failure to fatal would let one dropped stream kill a whole theory cone hours
    into an AFP run.  Every branch logs the variant it saw, so an unrecognised
    one can be added here afterwards rather than merely suspected."""
    detail = err.message + (f" ({err.additional_details})"
                            if err.additional_details else "")
    info = err.codex_error_info
    if info is None:
        _log.warning("codex: turn failed with no error info: %s", detail)
        return TransientAgentError(f"codex turn failed: {detail}")

    root = info.root
    _log.warning("codex: turn failed, error info %s: %s",
                 getattr(root, "value", None) or type(root).__name__, detail)

    if isinstance(root, CodexErrorInfoValue):
        if root is CodexErrorInfoValue.usage_limit_exceeded:
            return ReachLimitError()
        if root is CodexErrorInfoValue.unauthorized:
            return FatalAgentError(_MSG_AUTH_FAILED, detail)
        if root in (CodexErrorInfoValue.bad_request, CodexErrorInfoValue.cyber_policy):
            return FatalAgentError(_MSG_INVALID_REQUEST, detail)
        if root is CodexErrorInfoValue.context_window_exceeded:
            # Recoverable only by discarding the conversation, which is exactly
            # what _run_agent's recycle does.
            return PoisonedSessionError()
        if root is CodexErrorInfoValue.session_budget_exceeded:
            return FatalAgentError(_MSG_SESSION_BUDGET, detail)
        if root not in _TRANSIENT_VALUES:
            _log.warning("codex: unrecognised error value %r; treating as "
                         "transient", root)
        return TransientAgentError(f"codex: {root.value}: {detail}")

    if isinstance(root, ActiveTurnNotSteerableCodexErrorInfo):
        return TransientAgentError(f"codex: turn not steerable: {detail}")

    status = _http_status_of(root)
    if status == 429:
        return ReachLimitError()
    if status in (401, 403):
        return FatalAgentError(_MSG_AUTH_FAILED, detail)
    return TransientAgentError(
        f"codex: {type(root).__name__} (HTTP {status}): {detail}")


# --- the driver -------------------------------------------------------------

@register_interpretation_driver("Codex")
class CodexDriver(InterpretationDriver):
    """Runs the interpretation agent through the Codex SDK."""

    #: Codex's own documented default ("the default Power setting, which uses
    #: gpt-5.6-sol"), named here rather than left implicit: the model has to be
    #: one we can record in the theory entry and price, and "whatever this
    #: machine's codex happens to be configured for" is neither.  It must be a
    #: real catalogue slug -- `gpt-5.6` appears in the documentation but is not
    #: one, and has no published price.
    DEFAULT_MODEL = "gpt-5.6-sol"

    #: 0.144.4 never sends `thread/compacted`, and hooks registered through the
    #: SDK are never executed by the headless app-server, so there is no signal
    #: at all when the conversation is compacted.  Measured, not assumed: 13
    #: real compactions produced neither.
    REPORTS_CONTEXT_RESET = False

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        # Before anything is spent, not lazily at the first turn: an unpriced
        # model would otherwise be found only after the run had cost money, and
        # the failure would arrive as a mid-run exception rather than as the
        # configuration error it is.
        try:
            self._pricing = pricing_of(self.model)
        except MissingPricing as e:
            raise FatalAgentError(str(e)) from e
        self._codex: AsyncCodex | None = None
        self._thread: Any = None
        self._server: InterpretationMCPServer | None = None
        self._session_id: str | None = None
        self._total = _ZERO_USAGE

    async def __aenter__(self) -> "CodexDriver":
        self._server = await InterpretationMCPServer.get_or_create()
        self._session_id = self._server.allocate_session_id()
        url = await self._server.register_session(
            self._session_id, self.tools, self.task)
        try:
            codex = AsyncCodex()
            await codex.__aenter__()
            self._codex = codex
            self._thread = await codex.thread_start(
                model=self.model,
                # A full REPLACEMENT of the built-in system prompt, not an
                # addition: what we have is a specification of the translation
                # task, and the 20 KB it replaces is coding-agent guidance that
                # would only compete with it.  Measured to leave the shell and
                # our MCP tools working.
                base_instructions=self.system_prompt,
                cwd=str(AGENT_DIR),
                # read-only is the semantics we want -- the agent may read the
                # theory sources and anything else on disk, and write nothing --
                # and it restricts the network too.  Reads outside cwd are
                # already permitted; no extra configuration achieves that (the
                # key that looks as if it would is silently ignored).
                sandbox=Sandbox.read_only,
                # Never block waiting for an approval nobody can give.
                approval_mode=ApprovalMode.deny_all,
                config={"mcp_servers": {SERVER_NAME: {
                    "url": url,
                    "enabled": True,
                    # Required.  Without it every one of our tool calls is
                    # auto-rejected ("user rejected MCP tool call"); the model
                    # retries once, gives up, and the failed turn costs MORE
                    # than a successful one.
                    "default_tools_approval_mode": "approve",
                }}})
            await self._check_tools_registered()
        except BaseException:
            await self._release()
            raise
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._release()

    async def _release(self) -> None:
        codex, self._codex, self._thread = self._codex, None, None
        if codex is not None:
            try:
                await codex.close()
            except Exception:
                _log.exception("codex: closing the client failed")
        if self._server is not None and self._session_id is not None:
            await self._server.unregister_session(self._session_id)
        self._session_id = None

    async def _check_tools_registered(self) -> None:
        """Assert the agent can actually see our tools.

        The one guard against this backend's habit of failing silently: an MCP
        server it could not reach is not reported anywhere, and the run would go
        on to produce translations made without any of the tools.

        Scoped to this thread ON PURPOSE -- MCP registration is a per-thread
        overlay, so an unscoped listing looks at an empty process-level view and
        would either always fail or vacuously pass."""
        want = {t.name for t in self.tools}
        try:
            resp = await asyncio.wait_for(
                self._codex._client.request(          # no typed method for this
                    "mcpServerStatus/list",
                    {"detail": "toolsAndAuthOnly", "threadId": self._thread.id},
                    response_model=ListMcpServerStatusResponse),
                timeout=_HEALTHCHECK_TIMEOUT_S)
        except Exception:
            # A warning, not an abort: the check is younger and less proven than
            # the thing it checks, so a broken check must not stop a good run.
            _log.warning("codex: could not verify that the interpretation tools "
                         "registered; continuing", exc_info=True)
            return
        entry = next((s for s in resp.data if s.name == SERVER_NAME), None)
        if entry is None:
            raise FatalAgentError(
                None, f"codex did not register the {SERVER_NAME!r} MCP server; "
                      f"it sees {[s.name for s in resp.data]}")
        missing = sorted(want - set(entry.tools))
        if missing:
            raise FatalAgentError(
                None, f"codex is missing interpretation tools {missing}; "
                      f"it sees {sorted(entry.tools)}")
        _log.info("codex: %d interpretation tools registered", len(entry.tools))

    async def run_turn(self, prompt: str) -> None:
        before = self._total
        try:
            handle = await self._thread.turn(prompt)
            err: TurnError | None = None
            async for note in handle.stream():
                payload = note.payload
                if isinstance(payload, ThreadTokenUsageUpdatedNotification):
                    self._total = payload.token_usage.total
                elif isinstance(payload, TurnCompletedNotification):
                    # Read the error HERE.  The convenience `run()` raises a
                    # bare RuntimeError carrying only the message, discarding
                    # the classification this driver needs.
                    err = payload.turn.error
                _log.debug("codex: %s", note.method)
        except TransportClosedError as e:
            raise TransientAgentError(f"codex transport closed: {e}") from e
        self._record_turn_cost(before)
        if err is not None:
            raise await self._classify(err)

    async def _classify(self, err: TurnError) -> Exception:
        exc = classify_turn_error(err)
        if isinstance(exc, ReachLimitError):
            # Out of quota and out of money look alike here and the remedies do
            # not: one is worth waiting for, the other never will be.
            billing = await self._billing_failure()
            if billing is not None:
                return billing
        return exc

    async def _billing_failure(self) -> "FatalAgentError | None":
        """A billing failure when the account has no credits, else None.

        Best effort, and deliberately so: a rate limit whose cause we cannot
        confirm stays a rate limit -- waiting for a reset that comes is the
        recoverable guess."""
        try:
            resp = await asyncio.wait_for(
                self._codex._client.request(       # no typed method for this
                    "account/rateLimits/read", {},
                    response_model=GetAccountRateLimitsResponse),
                timeout=_HEALTHCHECK_TIMEOUT_S)
        except Exception:
            _log.warning("codex: could not read the account rate limits",
                         exc_info=True)
            return None
        limits = resp.rate_limits
        credits = limits.credits
        primary = limits.primary
        if primary is not None and primary.resets_at is not None:
            _log.info("codex: usage limit reached, resets at %s (%d%% used)",
                      primary.resets_at, primary.used_percent)
        if credits is not None and not credits.unlimited and not credits.has_credits:
            return FatalAgentError(_MSG_BILLING,
                                   f"credits balance {credits.balance!r}")
        return None

    def _record_turn_cost(self, before: TokenUsageBreakdown) -> None:
        """Bill this turn from the ADVANCE of the cumulative usage.

        Not from `usage.last`, which is per model REQUEST: a turn makes one
        request per tool call, so `last` is only the final one and undercounts a
        tool-using turn several-fold -- with a figure that looks entirely
        plausible.

        The counts overlap in two ways the reporting does not spell out: the
        input count includes the cached part, and the output count already
        includes reasoning tokens.  `Pricing.cost` handles both; what is stored
        as this package's "input" is the uncached remainder, matching what the
        Claude Code path stores there.  Deltas are floored at zero -- a small
        share of reports carry all-zero component counts, which would otherwise
        show up as a negative bill."""
        now = self._total
        d_in = max(0, now.input_tokens - before.input_tokens)
        d_cached = max(0, now.cached_input_tokens - before.cached_input_tokens)
        d_out = max(0, now.output_tokens - before.output_tokens)
        cost = self._pricing.cost(input_tokens=d_in, cached_input_tokens=d_cached,
                                  output_tokens=d_out)
        _log.info("codex: turn used input=%d (cached %d) output=%d, cost $%.4f",
                  d_in, d_cached, d_out, cost)
        accumulate_usage(self.task,
                         input_tokens=max(0, d_in - d_cached),
                         cache_read_tokens=d_cached,
                         output_tokens=d_out,
                         cost_usd=cost)


_ZERO_USAGE = TokenUsageBreakdown(
    cached_input_tokens=0, input_tokens=0, output_tokens=0,
    reasoning_output_tokens=0, total_tokens=0)
