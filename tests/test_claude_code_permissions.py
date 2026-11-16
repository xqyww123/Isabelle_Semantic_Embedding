"""The Claude Code driver's tool permissions, as its PreToolUse hook decides them:
the semantic change gate's judge may call `verdict` and the CLI's tool search
(which it needs to fetch `verdict`'s schema, the CLI deferring MCP tools) and
nothing else; the interpretation agent keeps its own tools and the CLI's.
No Isabelle, no model, no store.
Run with  python -m pytest contrib/Semantic_Embedding/tests/test_claude_code_permissions.py
"""
import asyncio

import pytest
from claude_agent_sdk import tool

from Isabelle_Semantic_Embedding.interpretation_driver.claude_code import (
    SERVER_NAME, ClaudeCodeDriver)


@tool("verdict", "the judge's tool", {"same": bool, "why": str})
async def _verdict(args):
    return {"content": []}


@tool("answer", "an interpretation tool", {"text": str})
async def _answer(args):
    return {"content": []}


VERDICT, ANSWER = f"mcp__{SERVER_NAME}__verdict", f"mcp__{SERVER_NAME}__answer"


def _session(cli_tools: bool, tools: list):
    """The allowed tools and the PreToolUse hook of a session's options."""
    driver = ClaudeCodeDriver(model="", system_prompt="", tools=tools, task=None,  # type: ignore[arg-type]
                              on_context_reset=lambda: None, cli_tools=cli_tools)
    options = driver._options()  # type: ignore[attr-defined]
    return options.allowed_tools, options.hooks["PreToolUse"][0].hooks[0]


def _allows(hook, tool_name: str) -> bool:
    out = asyncio.run(hook({"tool_name": tool_name, "tool_input": {}}, None, None))
    return out.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"


def test_the_judge_may_call_verdict_and_the_tool_search_only():
    allowed, hook = _session(False, [_verdict])
    assert allowed == sorted([VERDICT, "ToolSearch"])
    assert _allows(hook, VERDICT) and _allows(hook, "ToolSearch")


@pytest.mark.parametrize("name", ["Read", "Bash", "WebFetch", "MCPSearch", ANSWER])
def test_the_judge_is_denied_every_other_tool(name):
    _, hook = _session(False, [_verdict])
    assert not _allows(hook, name)


@pytest.mark.parametrize("name", [ANSWER, "ToolSearch", "MCPSearch", "Read", "Bash"])
def test_the_interpretation_agent_keeps_its_tools(name):
    _, hook = _session(True, [_answer])
    assert _allows(hook, name)


def test_the_interpretation_agent_cannot_call_the_judge_s_tool():
    _, hook = _session(True, [_answer])
    assert not _allows(hook, VERDICT)
