"""The Codex driver's HTTP server for the interpretation tools
(`interpretation_driver/mcp_server.py`), driven over loopback HTTP by the
`mcp` client in both MCP eras: the handshake (`initialize`) and 2026-07-28
(`server/discover`).  Results are read in the wire form.  The tools and the
task are stand-ins; no Isabelle, no model.
Run with  python -m pytest contrib/Semantic_Embedding/tests/test_interpretation_mcp_server.py
"""
import asyncio

import jsonschema
import pytest
from claude_agent_sdk import SdkMcpTool
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from Isabelle_RPC_Host import Connection
from Isabelle_Semantic_Embedding.interpretation_driver.mcp_server import InterpretationMCPServer

ERAS = ["handshake", "2026-07-28"]

CONNECTION = object()                   # the stand-in task's connection
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
          "additionalProperties": False}
seen_connections = []


async def echo(arguments):
    seen_connections.append(Connection.current())
    return {"content": [{"type": "text", "text": f"first line\n{arguments['text']}\nlast line"}]}


async def flagged(arguments):
    return {"content": [{"type": "text", "text": "a flagged answer"}], "is_error": True}


async def raising(arguments):
    raise RuntimeError("the handler broke")


TOOLS = [SdkMcpTool("echo", "answers its text between two lines", SCHEMA, echo),
         SdkMcpTool("flagged", "answers an error", SCHEMA, flagged),
         SdkMcpTool("raising", "raises", SCHEMA, raising)]


class Task:
    connection = CONNECTION


def wire(model) -> dict:
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


def served(era, calls):
    """The tools served for the stand-in task on a server of their own, a
    client opened on their endpoint in `era`; `calls(client)`'s value."""
    async def run():
        server = InterpretationMCPServer()
        await server._ensure_serving()
        try:
            url = await server.register_session(server.allocate_session_id(), TOOLS, Task())  # type: ignore[arg-type]
            async with streamable_http_client(url) as (read, write, *_), ClientSession(read, write) as client:
                await (client.initialize() if era == "handshake" else client.discover())
                return await calls(client)
        finally:
            await server.shutdown()
    return asyncio.run(run())


@pytest.mark.parametrize("era", ERAS)
def test_tools_list_gives_each_advertised_schema(era):
    async def listed(client):
        return [wire(tool) for tool in (await client.list_tools()).tools]
    assert [(t["name"], t["description"], t["inputSchema"]) for t in served(era, listed)] == [
        (t.name, t.description, t.input_schema) for t in TOOLS]


@pytest.mark.parametrize("era", ERAS)
def test_a_call_is_answered_whole_and_its_errors_are_flagged(era):
    """A valid call's text arrives whole, `isError` false, its handler having
    seen the task's connection as the current one; invalid arguments are
    answered the SDK's `Input validation error: …`; a tool's `is_error`
    arrives as `isError`; a handler that raises, as `isError` with its
    exception's text."""
    seen_connections.clear()
    with pytest.raises(jsonschema.ValidationError) as caught:
        jsonschema.validate({}, SCHEMA)

    async def calls(client):
        return [wire(await client.call_tool(name, arguments)) for name, arguments in (
            ("echo", {"text": "the middle"}), ("echo", {}), ("flagged", {"text": "x"}), ("raising", {"text": "x"}))]
    valid, invalid, flagged_result, raised = served(era, calls)
    assert (valid["content"], valid.get("isError", False)) == (
        [{"type": "text", "text": "first line\nthe middle\nlast line"}], False)
    assert seen_connections == [CONNECTION]
    assert (invalid["content"], invalid["isError"]) == (
        [{"type": "text", "text": f"Input validation error: {caught.value.message}"}], True)
    assert (flagged_result["content"], flagged_result["isError"]) == (
        [{"type": "text", "text": "a flagged answer"}], True)
    assert (raised["content"], raised["isError"]) == ([{"type": "text", "text": "the handler broke"}], True)
