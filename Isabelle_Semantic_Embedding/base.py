"""Shared utilities for MCP tool implementations."""

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from Isabelle_RPC_Host import Connection

type ToolCall_ret = dict[str, Any]

def mk_ret(text: str, is_error: bool = False) -> ToolCall_ret:
    ret: ToolCall_ret = {"content": [{"type": "text", "text": text}]}
    if is_error:
        ret["is_error"] = True
    return ret


def logger_of(connection: 'Connection | None', name: str) -> logging.Logger:
    """The logger to use for *name*, preferring the RPC host's own.

    ``connection.server.logger.getChild(name)`` is the convention every logging
    call site in this package follows (hover, desugar, semantics), because it
    keeps the line under the host's logger and thus in the host's log file.  This
    helper only adds the fallback for the paths that may run without a
    connection -- the CLI, the tests -- where the module logger is all there is.
    """
    if connection is not None:
        return connection.server.logger.getChild(name)
    return logging.getLogger(f"{__package__}.{name}")
