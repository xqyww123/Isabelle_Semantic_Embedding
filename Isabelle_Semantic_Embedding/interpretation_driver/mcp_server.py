"""Serve the interpretation tools over HTTP, for backends that run out of process.

The Claude Code path hands its five tools to `create_sdk_mcp_server`, which runs
them inside the Python process and reaches the CLI over the SDK's own transport.
A backend whose agent lives in a subprocess of its own (Codex) has no such
channel -- and the tools cannot simply move there, because their handlers close
over a live `Isabelle_RPC_Host.Connection`.  So the tools stay here and the
subprocess connects back to them over loopback HTTP.

ONE server per process, sessions on separate paths (`/mcp/<id>`).  Not one
server per interpretation: each would call `uvicorn.Server.serve()`, which
installs process-wide SIGINT/SIGTERM handlers for its lifetime and restores the
previous ones on exit -- with cone nodes interpreting concurrently, their
lifetimes interleave arbitrarily, and the last one out would leave a dead
server's `handle_exit` installed as the process handler.  The RPC host would
then survive Ctrl-C.  This server goes further and does not touch signals at
all (see `_EmbeddedServer`): it is a guest in the host's process.

Independent implementation of the same architecture AoA uses for its proof
tools; deliberately no shared code (see the project rule on the two packages).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from typing import TYPE_CHECKING, Any

import uvicorn
from mcp import types
from mcp.server.lowlevel import Server as MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from Isabelle_RPC_Host import Connection

if TYPE_CHECKING:
    from claude_agent_sdk import SdkMcpTool

    from ..semantic_interpretation import InterpretationTask

_log = logging.getLogger(__name__)

#: Server name, and hence the flat tool names the model sees
#: (`mcp__isabelle_semantics__answer`).  It MUST match the name the Claude Code
#: path registers, because the system prompt, the batch prompts and the answer
#: tool's own replies all address the tools by those names -- one wording serves
#: both backends only as long as this string does.
SERVER_NAME = "isabelle_semantics"


# --- result translation -----------------------------------------------------

def _content_block(block: Any) -> types.ContentBlock | None:
    """One block of a tool's `ToolCall_ret` as MCP content."""
    if not isinstance(block, dict):
        return None
    kind = block.get("type")
    if kind == "text":
        return types.TextContent(type="text", text=str(block.get("text", "")))
    if kind == "image":
        return types.ImageContent(type="image", data=block.get("data", ""),
                                  mimeType=block.get("mimeType", "image/png"))
    if kind == "resource":
        return types.EmbeddedResource(type="resource", resource=block["resource"])
    return None


def to_call_tool_result(ret: Any) -> types.CallToolResult:
    """Translate a tool handler's return value into an MCP tool result.

    The handlers return the Claude Agent SDK's private `ToolCall_ret` shape
    (`base.mk_ret`): a plain dict, snake_case, `{"content": [...],
    "is_error"?: bool}`.  MCP's low-level server does NOT recognise it -- handed
    a bare dict it treats the whole thing as *structured* content, renders the
    body as `json.dumps(..., indent=2)` text, and hardcodes `isError` to False.

    Both consequences are silent and both damage the run: the answer tool
    returns the NEXT BATCH of entries in its result, so the model would receive
    its work wrapped in JSON with the newlines escaped, and an error flagged by
    `desugar_and_explain` would arrive looking like a success.  The Claude Code
    path is spared only because `create_sdk_mcp_server` does this translation
    internally, where this server cannot reach it -- hence this function.
    """
    blocks = ret.get("content", []) if isinstance(ret, dict) else []
    content = [b for b in (_content_block(x) for x in blocks) if b is not None]
    if not content:
        # Never hand back an empty result: to the model that is indistinguishable
        # from a tool that did nothing.
        content = [types.TextContent(type="text", text=repr(ret))]
    return types.CallToolResult(
        content=content,
        isError=bool(ret.get("is_error", False)) if isinstance(ret, dict) else False)


# --- one MCP server per interpretation session ------------------------------

def build_mcp_server(tools: list["SdkMcpTool[Any]"],
                     task: "InterpretationTask") -> MCPServer:
    """An MCP server exposing `tools`, with `task` as their ambient state."""
    by_name = {t.name: t for t in tools}

    def bind_context() -> None:
        """Re-establish the ambient state a tool handler expects.

        Per request, by necessity: uvicorn runs each ASGI request in a fresh,
        empty `contextvars.Context`, so nothing set outside the request is
        visible here.  The answer tool reads the task from a contextvar, and
        every tool's progress reporting reads the connection from another; both
        would otherwise be missing on this path and only on this path.
        """
        from ..semantic_interpretation import _local_task
        _local_task.set(task)
        if task.connection is not None:
            Connection.set_current(task.connection)

    server: MCPServer = MCPServer(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [types.Tool(name=t.name, description=t.description,
                           inputSchema=t.input_schema)
                for t in tools]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        tool = by_name.get(name)
        if tool is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Unknown tool: {name}")],
                isError=True)
        bind_context()
        return to_call_tool_result(await tool.handler(arguments))

    return server


class _ManagedMCPApp:
    """ASGI app wrapping one MCP server in a StreamableHTTP session manager.

    The manager's `run()` holds an anyio task group, which must be entered and
    left in one task; a dedicated background task owns it for the session's
    lifetime."""

    def __init__(self, mcp_server: MCPServer) -> None:
        self._manager = StreamableHTTPSessionManager(app=mcp_server, stateless=False)
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._start_error: BaseException | None = None

    async def start(self) -> None:
        async def _run() -> None:
            try:
                async with self._manager.run():
                    self._ready.set()
                    await self._stop.wait()
            except BaseException as e:
                self._start_error = e
                self._ready.set()          # unblock start(), which re-raises
                raise

        self._task = asyncio.create_task(_run())
        await self._ready.wait()
        if self._start_error is not None:
            raise self._start_error

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        with contextlib.suppress(Exception):
            await self._task
        self._task = None

    async def __call__(self, scope, receive, send) -> None:
        await self._manager.handle_request(scope, receive, send)


class _SessionRouter:
    """ASGI app dispatching `/mcp/<session_id>/...` to that session's app."""

    def __init__(self) -> None:
        self.apps: dict[str, _ManagedMCPApp] = {}

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return
        path: str = scope["path"]
        for session_id, app in list(self.apps.items()):
            prefix = f"/mcp/{session_id}"
            if path == prefix or path.startswith(prefix + "/"):
                inner = dict(scope)
                inner["path"] = path[len(prefix):] or "/"
                inner["root_path"] = scope.get("root_path", "") + prefix
                await app(inner, receive, send)
                return
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"Session not found"})


class _EmbeddedServer(uvicorn.Server):
    """A uvicorn server that leaves the process's signal handlers alone.

    `uvicorn.Server.serve` normally installs its own SIGINT/SIGTERM handlers for
    the duration.  Here uvicorn is a guest inside the Isabelle RPC host, which
    owns the process and its shutdown; taking its signals away would mean
    Ctrl-C stops the MCP server instead of the host, for as long as any
    interpretation is running."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


class InterpretationMCPServer:
    """The process's one HTTP endpoint for the interpretation tools."""

    _instance: "InterpretationMCPServer | None" = None
    _lock = asyncio.Lock()

    def __init__(self, port: int = 0) -> None:
        self._port = port or self._find_free_port()
        self._router = _SessionRouter()
        self._server: uvicorn.Server | None = None
        self._serve_task: asyncio.Task | None = None
        self._next_id = 0

    @classmethod
    async def get_or_create(cls, port: int = 0) -> "InterpretationMCPServer":
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(port)
            await cls._instance._ensure_serving()
        return cls._instance

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    @property
    def port(self) -> int:
        return self._port

    def allocate_session_id(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    async def register_session(self, session_id: str,
                               tools: list["SdkMcpTool[Any]"],
                               task: "InterpretationTask") -> str:
        """Serve `tools` at a URL of this session's own.  Returns that URL."""
        app = _ManagedMCPApp(build_mcp_server(tools, task))
        await app.start()
        self._router.apps[session_id] = app
        return f"http://127.0.0.1:{self._port}/mcp/{session_id}"

    async def unregister_session(self, session_id: str) -> None:
        app = self._router.apps.pop(session_id, None)
        if app is not None:
            await app.stop()

    async def _ensure_serving(self) -> None:
        if self._serve_task is not None:
            if not self._serve_task.done():
                return
            self._serve_task = self._server = None      # last attempt died; retry
        config = uvicorn.Config(self._router, host="127.0.0.1", port=self._port,
                                log_level="warning")
        self._server = _EmbeddedServer(config)
        self._serve_task = asyncio.create_task(self._server.serve())
        while not (self._server.started or self._serve_task.done()):
            await asyncio.sleep(0.01)
        if self._serve_task.done():
            exc = self._serve_task.exception()
            self._serve_task = self._server = None
            raise exc if exc is not None else RuntimeError(
                "the interpretation MCP server stopped before it started serving")
        _log.info("interpretation MCP server listening on 127.0.0.1:%d", self._port)

    async def shutdown(self) -> None:
        for session_id in list(self._router.apps):
            await self.unregister_session(session_id)
        if self._server is not None:
            self._server.should_exit = True
        if self._serve_task is not None:
            with contextlib.suppress(Exception):
                await self._serve_task
        self._serve_task = self._server = None
        if InterpretationMCPServer._instance is self:
            InterpretationMCPServer._instance = None
