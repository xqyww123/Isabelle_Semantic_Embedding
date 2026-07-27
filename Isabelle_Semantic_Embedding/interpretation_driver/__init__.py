"""Driver abstraction for the semantic-interpretation (deformalization) agent.

A driver's whole job is "send one user prompt and run it until the model stops".
Everything around that -- batching, missing-entry retries, usage-limit waits,
client recycling, the completeness invariant -- stays in the driver-agnostic
``_run_agent`` / ``interpret_file`` of :mod:`..semantic_interpretation`, so a new
driver only has to implement :meth:`InterpretationDriver.run_turn`.

INVARIANT: this module must NEVER import a concrete driver.  Concrete drivers
import ``semantic_interpretation`` (for the failure classes and
``InterpretationTask``) and ``semantic_interpretation`` imports this module, so
an eager ``from . import claude_code`` here would close the cycle at import
time.  ``make_interpretation_driver`` imports lazily instead, which keeps it
open -- the same shape as ``make_embedding_provider``
(``semantic_embedding.py``), which loads ``drivers/<name>.py`` on demand.

NB this is a DIFFERENT abstraction from the ``drivers/`` subpackage: that one is
the embedding layer's ``Embedding_Provider`` (text -> vector).  This one is the
interpretation layer's agent backend (Isabelle entity -> English).
"""

from __future__ import annotations

import importlib
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claude_agent_sdk import SdkMcpTool

    from ..semantic_interpretation import InterpretationTask

# Working directory handed to every agent backend.  It carries the per-backend
# skill directories (`.claude/skills/`, and `.codex/skills/` alongside it) that
# the interpretation prompt asks the agent to load.
AGENT_DIR = Path(__file__).resolve().parent.parent / "Agent_Interpretation_Dir"

DRIVERS: dict[str, type["InterpretationDriver"]] = {}


def register_interpretation_driver(name: str):
    """Register a driver class under its user-facing name.

    The name is what the Isabelle config option / env var carries and what is
    stored alongside the interpretation cost, so it is CamelCase (``ClaudeCode``,
    ``Codex``) rather than the module basename."""
    def deco(cls: type[InterpretationDriver]) -> type[InterpretationDriver]:
        cls.NAME = name
        DRIVERS[name] = cls
        return cls
    return deco


def _module_basename(name: str) -> str:
    """``ClaudeCode`` -> ``claude_code``.

    The user-facing driver name is CamelCase while Python module files are
    snake_case, so the lazy import derives one from the other instead of keeping
    a second table that could drift from the ``@register_interpretation_driver``
    decorators."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def resolve_interpretation_driver_class(name: str) -> type[InterpretationDriver] | None:
    """The driver class for `name`, importing its module on first use.

    Returns None when no such driver exists, so a caller can report the
    available names; a driver module that fails to LOAD still raises."""
    cls = DRIVERS.get(name)
    if cls is not None:
        return cls
    try:
        importlib.import_module(f".{_module_basename(name)}", __package__)
    except ModuleNotFoundError:
        return None
    return DRIVERS.get(name)


def make_interpretation_driver(
    name: str,
    *,
    model: str,
    system_prompt: str,
    tools: list["SdkMcpTool[Any]"],
    task: "InterpretationTask",
    on_context_reset: Callable[[], None],
) -> InterpretationDriver:
    cls = resolve_interpretation_driver_class(name)
    if cls is None:
        raise ValueError(
            f"unknown interpretation driver {name!r}; "
            f"known drivers: {sorted(DRIVERS) or ['(none loaded)']}")
    return cls(model=model, system_prompt=system_prompt, tools=tools,
               task=task, on_context_reset=on_context_reset)


class InterpretationDriver(ABC):
    """One agent backend for the interpretation loop.

    Constructed once per attempt: ``_run_agent`` builds a FRESH instance for
    every recycle, so a driver may keep per-session state (a client, a thread, a
    subprocess) in ``__aenter__`` without having to reset it."""

    #: user-facing name, set by @register_interpretation_driver
    NAME: str = ""

    def __init__(self, *, model: str, system_prompt: str,
                 tools: list["SdkMcpTool[Any]"],
                 task: "InterpretationTask",
                 on_context_reset: Callable[[], None]) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.tools = tools
        self.task = task
        # Called just BEFORE the backend compacts the conversation.  It is the
        # fifth channel because what it resets -- the desugar tool's
        # already-annotated-constant set -- is a bare local of `interpret_file`,
        # reachable through neither `task` nor the tool objects.
        self.on_context_reset = on_context_reset

    async def __aenter__(self) -> "InterpretationDriver":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    @abstractmethod
    async def run_turn(self, prompt: str) -> None:
        """Send one user prompt and run it until the model stops.

        Must accumulate this turn's usage into ``self.task`` and flush it with
        ``write_cost()`` (see `accumulate_usage`) -- answers are persisted as
        they arrive, so their cost has to be just as eagerly persisted.  On
        failure it must raise one of ``semantic_interpretation``'s five failure
        classes; anything else falls into ``_run_agent``'s bounded catch-all."""
        raise NotImplementedError


def accumulate_usage(task: "InterpretationTask", *,
                     input_tokens: int = 0,
                     cache_creation_tokens: int = 0,
                     cache_read_tokens: int = 0,
                     output_tokens: int = 0,
                     cost_usd: float = 0.0) -> None:
    """Add one round's usage to `task` and flush it to the theory record.

    Two accumulators, deliberately: ``total_*`` is the pending delta that
    ``write_cost`` folds into LMDB and then zeroes, ``run_*`` is the whole
    invocation's cost and is never reset (it is what ``interpret_file`` reports
    as ``current_cost``).

    Flushing every round -- rather than once at the end -- is what makes an
    interrupt safe: the parallel scheduler kills the run by design, and answers
    already written to LMDB become free cache hits on resume, so the cost that
    produced them must already be recorded."""
    task.total_input_tokens += input_tokens
    task.total_cache_creation_tokens += cache_creation_tokens
    task.total_cache_read_tokens += cache_read_tokens
    task.total_output_tokens += output_tokens
    task.total_cost_usd += cost_usd
    task.run_input_tokens += input_tokens
    task.run_cache_creation_tokens += cache_creation_tokens
    task.run_cache_read_tokens += cache_read_tokens
    task.run_output_tokens += output_tokens
    task.run_cost_usd += cost_usd
    task.write_cost()
