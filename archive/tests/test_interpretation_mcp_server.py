"""Tests for the HTTP MCP server that exposes the interpretation tools.

Everything here goes over a REAL loopback HTTP round trip rather than calling
the server's handlers directly.  That is the point of the exercise: the two
failures this module exists to prevent -- a tool result mangled on the way out,
and the ambient state a handler needs being absent because uvicorn starts each
request in an empty contextvars.Context -- are both invisible to a direct call
and only appear across the ASGI boundary.
"""
import asyncio
import signal

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from Isabelle_Semantic_Embedding.base import mk_ret
from Isabelle_Semantic_Embedding.interpretation_driver.mcp_server import (
    InterpretationMCPServer,
    to_call_tool_result,
)
from Isabelle_Semantic_Embedding.semantic_interpretation import _answer_tool

from test_interpretation_driver import _make_task


class _FakeTool:
    """Enough of an SdkMcpTool to be served (it is a plain dataclass)."""

    def __init__(self, name, description, input_schema, handler):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler


async def _failing_handler(args):
    return mk_ret("Invalid argument: 'term' must be a non-empty string.",
                  is_error=True)


_FAILING_TOOL = _FakeTool("always_fails", "Always reports an error.",
                          {"type": "object", "properties": {}}, _failing_handler)


def _serve(body):
    """Run `body(server)` against a freshly started server, then shut it down.

    Each test gets its own: the server is a per-process singleton bound to the
    event loop that started it, and every test here runs its own loop."""
    async def go():
        server = await InterpretationMCPServer.get_or_create()
        try:
            return await body(server)
        finally:
            await server.shutdown()

    return asyncio.run(go())


def _with_client(tools, task, body):
    """Register a session, run `body(client_session)` against it, clean up."""
    async def run(server):
        session_id = server.allocate_session_id()
        url = await server.register_session(session_id, tools, task)
        try:
            async with streamable_http_client(url) as (read, write, _):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    return await body(client)
        finally:
            await server.unregister_session(session_id)

    return _serve(run)


def test_a_tool_result_arrives_as_the_handler_wrote_it():
    """No JSON wrapper, no escaped newlines, and the answer is really recorded.

    The answer tool returns the NEXT BATCH of entries in its own result, so a
    result treated as structured content would reach the model as
    `json.dumps(..., indent=2)` -- its work, wrapped in JSON, newlines escaped.
    """
    task = _make_task(4, batch_size=2)
    task.batch_range = task.batches[0][1]          # as _run_agent leaves it

    async def answer(client, i, text):
        return await client.call_tool("answer", {"interpretations": [
            {"type": "constant", "name": f"T.c{i}", "translation": text}]})

    async def body(client):
        return (await answer(client, 0, "the zeroth"),
                await answer(client, 1, "the first"))

    mid_batch, handoff = _with_client([_answer_tool], task, body)

    for result in (mid_batch, handoff):
        assert result.isError is False
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert "\n" in result.content[0].text, "real newlines, not \\n in a JSON string"
        assert not result.content[0].text.lstrip().startswith("{"), "not JSON-wrapped"
        assert result.structuredContent is None
    assert mid_batch.content[0].text.startswith(
        "Answered 1 translation, remaining 1 in this batch.")
    # The batch is finished, so the result carries the NEXT one -- the payload
    # that a JSON wrapper would have mangled.
    assert handoff.content[0].text.startswith("Good job!")
    assert "constant T.c2" in handoff.content[0].text
    # The handlers ran against THIS task -- i.e. the ambient state survived the
    # ASGI boundary, which is exactly what uvicorn's empty per-request context
    # would otherwise have lost.
    assert task.written == [(0, "the zeroth"), (1, "the first")]


def test_an_error_from_a_handler_stays_an_error():
    """`is_error` is snake_case in the handlers' return shape and `isError` in
    MCP's; dropping the translation makes every failure look like a success."""
    task = _make_task(1, batch_size=1)

    async def body(client):
        return await client.call_tool("always_fails", {})

    result = _with_client([_FAILING_TOOL], task, body)
    assert result.isError is True
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text.startswith("Invalid argument")


def test_the_tools_are_listed_under_the_names_the_prompts_use():
    task = _make_task(1, batch_size=1)

    async def body(client):
        return await client.list_tools()

    listing = _with_client([_answer_tool, _FAILING_TOOL], task, body)
    names = {t.name for t in listing.tools}
    assert names == {"answer", "always_fails"}
    answer = next(t for t in listing.tools if t.name == "answer")
    # The schema is passed through, so the backend validates arguments for us.
    assert answer.inputSchema["properties"]["interpretations"]["type"] == "array"


def test_sessions_never_touch_the_process_signal_handlers():
    """Interleaved sessions, non-LIFO -- the shape that made a per-session
    uvicorn leave a dead server's handler installed and the RPC host unkillable."""
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    task = _make_task(1, batch_size=1)

    async def body(server):
        a = server.allocate_session_id()
        b = server.allocate_session_id()
        await server.register_session(a, [_answer_tool], task)
        await server.register_session(b, [_answer_tool], task)
        await server.unregister_session(a)          # out of order, on purpose
        await server.unregister_session(b)

    _serve(body)
    after = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    assert before[0] is after[0]
    assert before[1] is after[1]


def test_an_unknown_session_path_is_a_404_not_a_crash():
    async def body(server):
        scope = {"type": "http", "path": "/mcp/no-such-session", "method": "POST",
                 "headers": []}
        sent = []

        async def send(msg):
            sent.append(msg)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        await server._router(scope, receive, send)
        return sent

    sent = _serve(body)
    assert sent[0]["status"] == 404


# --- the translation itself, without the transport --------------------------

@pytest.mark.parametrize("ret,text,is_error", [
    (mk_ret("plain"), "plain", False),
    (mk_ret("bad", is_error=True), "bad", True),
])
def test_translation_of_the_handler_return_shape(ret, text, is_error):
    result = to_call_tool_result(ret)
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == text
    assert result.isError is is_error


def test_a_result_with_no_usable_content_still_says_something():
    """An empty result is indistinguishable from a tool that did nothing."""
    result = to_call_tool_result({"content": []})
    assert result.content and isinstance(result.content[0], TextContent)
    assert result.content[0].text
