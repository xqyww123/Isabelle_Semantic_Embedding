"""The Claude Code interpretation driver (the original, and still the default).

Everything Claude-Code-specific lives here: the tool whitelist and its
PreToolUse hook, the PreCompact hook that resets the desugar tool's dedup set,
the message-stream classifier that turns an SDK message into one of
``semantic_interpretation``'s failure classes, and the usage accounting.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    CLINotFoundError,
    HookMatcher,
    ThinkingConfigAdaptive,
    create_sdk_mcp_server,
)
try:
    from claude_agent_sdk import RateLimitEvent
except ImportError:
    RateLimitEvent = None
from claude_agent_sdk.types import (
    AssistantMessage,
    HookContext,
    HookInput,
    HookJSONOutput,
    PreToolUseHookInput,
    ResultMessage,
    SystemMessage,
)

from ..semantic_interpretation import (
    FatalAgentError,
    InterpretationTask,
    PoisonedSessionError,
    RateLimitError,
    ReachLimitError,
    TransientAgentError,
)
from . import (
    AGENT_DIR,
    InterpretationDriver,
    accumulate_usage,
    register_interpretation_driver,
)

_log = logging.getLogger(__name__)


# --- Permission control ---

_TOOL_WHITELIST = {
    "Read",
    "Grep",
    "Glob",
    "LS",
    "Bash",
    "Skill",
    "Agent",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "TaskOutput",
    "TaskStop",
    "WebFetch",
    "WebSearch",
    "ExitPlanMode",
    "MCPSearch",
    "ToolSearch",
    "mcp__isabelle_semantics__query",
    "mcp__isabelle_semantics__definition",
    "mcp__isabelle_semantics__hover",
    "mcp__isabelle_semantics__answer",
    "mcp__isabelle_semantics__desugar_and_explain",
}


def _deny(reason: str) -> HookJSONOutput:
    return {
        "continue_": False,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }


async def _permission_control(
    hook_input: HookInput, tool_use_id: str | None, context: HookContext
) -> HookJSONOutput:
    pre = cast(PreToolUseHookInput, hook_input)
    tool_name = pre["tool_name"]
    tool_input = pre.get("tool_input") or {}

    if tool_name not in _TOOL_WHITELIST:
        _log.warning("tool denied: %s %s", tool_name, tool_input)
        return _deny(f"Tool {tool_name!r} is not allowed.")

    _log.info("tool allowed: %s %s", tool_name, tool_input)
    return {}


# --- Message handling ---

def _model_error_text(message: Any) -> str:
    """The model's own words for a failure, e.g.
    'Failed to authenticate. API Error: 403 ...'.

    Worth surfacing verbatim: the SDK's error enum is coarse -- it reports a 403
    out-of-quota as `authentication_failed` -- so our summary of it can be actively
    misleading, while this text says exactly what went wrong."""
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return ""
    texts = [t for b in content
             if isinstance(t := getattr(b, "text", None), str) and t.strip()]
    return " ".join(texts).strip()


def _log_message(message: Any) -> None:
    """Log model output and thinking from a response message."""
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text:
            _log.info("[model] %s", text)
        thinking = getattr(block, "thinking", None)
        if isinstance(thinking, str) and thinking:
            _log.debug("[thinking] %s", thinking)


async def _list_tools(client: ClaudeSDKClient) -> None:
    """Ask the model to list all available tools, for debugging."""
    await client.query("List all available tools you have access to.")
    async for message in client.receive_response():
        _log_message(message)


def _accumulate_usage(task: InterpretationTask, message: ResultMessage) -> None:
    if message.usage:
        d_in = message.usage.get("input_tokens", 0)
        d_cw = message.usage.get("cache_creation_input_tokens", 0)
        d_cr = message.usage.get("cache_read_input_tokens", 0)
        d_out = message.usage.get("output_tokens", 0)
    else:
        d_in = d_cw = d_cr = d_out = 0
    _log.info("round usage: %s, cost: $%.4f", message.usage, message.total_cost_usd or 0)
    accumulate_usage(task, input_tokens=d_in, cache_creation_tokens=d_cw,
                     cache_read_tokens=d_cr, output_tokens=d_out,
                     cost_usd=message.total_cost_usd or 0.0)


# ---------------------------------------------------------------------------
# User-facing failure text.  Kept together so the wording can be reviewed in one
# place rather than hunted through the control flow.
# ---------------------------------------------------------------------------

# One message for both "never logged in" and "login expired".  They are NOT
# distinguishable at the point we must raise: a live unauthenticated session
# reports AssistantMessage.error = 'authentication_failed' before the terminal
# ResultMessage (the only carrier of the "Not logged in" text) ever arrives.  The
# remedy is identical either way, so guessing would add a wrong claim and no value.
_MSG_AUTH_FAILED = (
    "Semantic interpretation failed: Claude Code could not authenticate. "
    "Run 'claude' and use /login (it may not be logged in, or the login may have "
    "expired), then retry.")

_MSG_BILLING = (
    "Semantic interpretation failed: the Claude account has a billing problem. "
    "Check the account, then retry.")

_MSG_INVALID_REQUEST = (
    "Semantic interpretation failed: the request was rejected as invalid. "
    "This is a bug - please report it with the RPC host log.")


def _raise_for_agent_error(task: InterpretationTask,
                           err: str | None,
                           result_msg: Any,
                           model_text: str = "") -> None:
    """Classify a failure and raise.  Never returns.

    `err` is AssistantMessage.error when we have it; otherwise `result_msg` is a
    failed ResultMessage and the class is inferred from the api_retry trail plus
    its own fields.  `model_text` is the model's own description of the failure; it is
    appended to every recognised class because our own summary can be wrong -- the SDK
    reports an out-of-quota 403 as `authentication_failed`, so "log in again" would be
    exactly the wrong advice and only this text reveals it."""
    def fatal(summary: str) -> None:
        raise FatalAgentError(
            summary + (f'\nThe model reported: "{model_text}"' if model_text else ""))

    if err == "rate_limit":
        raise RateLimitError()
    if err == "server_error":
        raise TransientAgentError("agent reported a server error")
    if err == "authentication_failed":
        fatal(_MSG_AUTH_FAILED)
    if err == "billing_error":
        fatal(_MSG_BILLING)
    if err == "invalid_request":
        fatal(_MSG_INVALID_REQUEST)

    # err is None or "unknown": infer from what the run left behind.
    statuses = {s for s, _ in task.api_retry_errors}
    kinds = {k for _, k in task.api_retry_errors}
    result_text = (getattr(result_msg, "result", None) or "") if result_msg else ""
    status = getattr(result_msg, "api_error_status", None) if result_msg else None

    # Never authenticated: the CLI fails locally in ~100 ms with no retries at all,
    # so an empty api_retry trail is itself part of the signature.
    if "not logged in" in result_text.lower():
        fatal(_MSG_AUTH_FAILED)
    if status == 401 or 401 in statuses or "authentication_failed" in kinds:
        fatal(_MSG_AUTH_FAILED)

    # Unrecognised: there is no honest one-liner, so let the full traceback through.
    detail = f"error={err!r} api_error_status={status!r} result={result_text[:500]!r}"
    if model_text:
        detail += f" model_said={model_text[:500]!r}"
    if task.api_retry_errors:
        detail += f" api_retry={task.api_retry_errors[:10]!r}"
    errors = getattr(result_msg, "errors", None) if result_msg else None
    if errors:
        detail += f" errors={errors!r}"
    raise FatalAgentError(None, detail)


def _handle_message(task: InterpretationTask, message: Any) -> None:
    """Process one message from a `receive_response` loop: log it, accumulate
    usage for ResultMessages, and raise ReachLimitError/RateLimitError on a
    usage-cap or rate-limit signal so `_run_agent`'s handlers apply the 20-min
    wait / backoff.

    Shared by BOTH the batch-0 turn and the missing-entry retry turns.  The
    retry loop used to inline only `_log_message` + `_accumulate_usage`,
    swallowing the limit/rate signals — so a usage cap hit during retries
    span instantly (thousands of "You've hit your limit" rounds with no wait)
    instead of sleeping until the reset."""
    if RateLimitEvent is not None and isinstance(message, RateLimitEvent):
        if message.rate_limit_info.status == "rejected":
            raise ReachLimitError()
        return
    _log_message(message)

    # `api_retry` system messages are the ONLY place that distinguishes an expired
    # credential from an unreachable network: both terminate with an identical
    # ResultMessage (error_during_execution / aborted_streaming) whose `errors`
    # carry only an opaque [ede_diagnostic] string.  Record them as they stream by
    # so the terminal message can be classified.
    if isinstance(message, SystemMessage) and message.subtype == "api_retry":
        data = message.data or {}
        task.api_retry_errors.append(
            (data.get("error_status"), data.get("error")))
        return

    # The structured error enum (claude_agent_sdk.types.AssistantMessageError) is
    # the primary classification -- it is stable across CLI versions, unlike the
    # result text.
    if isinstance(message, AssistantMessage):
        err = getattr(message, "error", None)
        if err is not None:
            _raise_for_agent_error(task, err, None, _model_error_text(message))

    content = getattr(message, "content", None)
    if content is not None and isinstance(content, list) and content:
        block = content[0]
        text = getattr(block, "text", None)
        if isinstance(text, str):
            if text.startswith("You've hit your limit"):
                raise ReachLimitError()
            if "Rate limit" in text:
                raise RateLimitError()
    if isinstance(message, ResultMessage):
        status = getattr(message, "api_error_status", None)
        # A hard request-level rejection (e.g. 400 from a lone surrogate in the
        # transcript) carries its text in `errors`, NOT `result` (which is None
        # here), so the result-string checks below would miss it.  Detect via
        # the language-independent api_error_status, and raise BEFORE
        # _accumulate_usage so the poisoned round does not flush cost.
        if message.is_error and status == 400:
            raise PoisonedSessionError()
        _accumulate_usage(task, message)
        if message.is_error and message.result:
            if message.result.startswith("You've hit your limit"):
                raise ReachLimitError()
            if "Rate limit" in message.result:
                raise RateLimitError()
        # FAIL-SAFE.  Everything above is a whitelist of conditions we recognise;
        # this is the catch-all that makes an unrecognised failure loud instead of
        # silent.  Without it, an is_error result we have no branch for -- which is
        # exactly what an unauthenticated CLI produces -- flows on as if the round
        # had succeeded, the entries stay unanswered, and the theory ends up marked
        # interpreted with nothing in it.
        #
        # NB: do NOT branch on `subtype`.  It is 'success' even on an auth failure.
        if message.is_error:
            _raise_for_agent_error(task, None, message)


# --- The driver ---

@register_interpretation_driver("ClaudeCode")
class ClaudeCodeDriver(InterpretationDriver):
    """Runs the interpretation agent through the Claude Code CLI (Agent SDK).

    The five interpretation tools are served in-process
    (`create_sdk_mcp_server`), so their handlers keep their live Isabelle RPC
    connection; the CLI subprocess reaches them over the SDK's own transport."""

    DEFAULT_MODEL = "claude-opus-4-8[1m]"

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._client: ClaudeSDKClient | None = None

    def _options(self) -> ClaudeAgentOptions:
        mcp = create_sdk_mcp_server("isabelle_semantics", tools=self.tools)

        async def _on_compact(
            hook_input: HookInput,
            tool_use_id: str | None,
            context: HookContext,
        ) -> HookJSONOutput:
            self.on_context_reset()
            return {}

        return ClaudeAgentOptions(
            model=self.model,
            system_prompt=self.system_prompt,
            cwd=str(AGENT_DIR),
            setting_sources=["project"],
            permission_mode="default",
            allowed_tools=list(_TOOL_WHITELIST),
            mcp_servers={"isabelle_semantics": mcp},
            thinking=ThinkingConfigAdaptive(type="adaptive"),
            effort="high",
            # The answer tool hands the next batch of entries back in its
            # result; that payload is dense Isabelle Unicode (⟦⟧⟹…), which
            # tokenizes ~2x heavier per char than English, so a ~50KB batch
            # crosses the 25,000-token default MCP-output cap and gets
            # spilled to disk (forcing the agent to re-read it via Bash/jq).
            # Raise the cap so the batch is returned inline.  Merged onto the
            # inherited environment by the SDK, so other env vars are kept.
            env={"MAX_MCP_OUTPUT_TOKENS": "100000"},
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="*", hooks=[_permission_control]),
                ],
                "PreCompact": [
                    HookMatcher(matcher="*", hooks=[_on_compact]),
                ],
            },
        )

    async def __aenter__(self) -> "ClaudeCodeDriver":
        client = ClaudeSDKClient(options=self._options())
        try:
            await client.__aenter__()
        except CLINotFoundError as e:
            # No CLI to run: deterministic, and no amount of recycling conjures
            # one.  ProcessError is deliberately NOT treated this way -- the SDK
            # raises it for EVERY non-zero exit (subprocess_cli.py:700-707),
            # including an OOM kill or a segfault mid-stream, which a fresh
            # subprocess recovers from; those keep falling to _run_agent's
            # bounded recycle handler.
            raise FatalAgentError(None, f"Claude Code CLI not found: {e}") from e
        self._client = client
        return self

    async def __aexit__(self, *exc: object) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.__aexit__(*exc)

    async def run_turn(self, prompt: str) -> None:
        assert self._client is not None, "run_turn outside the driver's context"
        await self._client.query(prompt)
        async for message in self._client.receive_response():
            _handle_message(self.task, message)
