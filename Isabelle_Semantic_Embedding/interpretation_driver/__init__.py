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

    Returns None when there is no such driver, so a caller can report the names
    there are.  A driver that EXISTS but cannot be imported raises instead --
    that is a backend whose optional dependency is not installed, and reporting
    it as an unknown name would send the user looking for a typo."""
    cls = DRIVERS.get(name)
    if cls is not None:
        return cls
    module = _module_basename(name)
    if not (Path(__file__).parent / f"{module}.py").exists():
        return None
    importlib.import_module(f".{module}", __package__)
    return DRIVERS.get(name)


def available_interpretation_drivers() -> list[str]:
    """Every driver name this package can serve.

    For REPORTING an unknown name only -- it imports every module in the package
    to find out, whereas the happy path imports exactly one.  A module that
    cannot be imported (an optional dependency of some other backend) is skipped:
    it must not stop us naming the backends that do work.  Modules that are not
    drivers at all simply register nothing, which is why there is no second list
    of driver names here to drift from the decorators."""
    for path in sorted(Path(__file__).parent.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        try:
            importlib.import_module(f".{path.stem}", __package__)
        except Exception:
            continue
    return sorted(DRIVERS)


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
            f"known drivers: {available_interpretation_drivers()}")
    return cls(model=model, system_prompt=system_prompt, tools=tools,
               task=task, on_context_reset=on_context_reset)


class InterpretationDriver(ABC):
    """One agent backend for the interpretation loop.

    Constructed once per attempt: ``_run_agent`` builds a FRESH instance for
    every recycle, so a driver may keep per-session state (a client, a thread, a
    subprocess) in ``__aenter__`` without having to reset it."""

    #: user-facing name, set by @register_interpretation_driver
    NAME: str = ""

    #: model used when the driver spec names none (`Codex` rather than
    #: `Codex.gpt-5.6`).  Which model is sensible is the backend's own business,
    #: so a shared default would be a model name from one backend handed to
    #: another.  A backend that has its own default-model setting may keep this
    #: empty, meaning "pass no model and let the backend pick" (ClaudeCode: the
    #: CLI's configured default) -- such a driver must backfill task.model with
    #: the model that actually ran, so provenance never records an empty name.
    DEFAULT_MODEL: str = ""

    #: whether this backend tells us when it compacts the conversation, i.e.
    #: whether `on_context_reset` is ever called.  The desugar tool spends
    #: tokens once per constant only while someone can clear its record of what
    #: it has already explained; a backend that compacts silently must have it
    #: explain every time (see `mk_desugar_and_explain_tool`'s `dedup`).
    REPORTS_CONTEXT_RESET: bool = False

    def __init__(self, *, model: str, system_prompt: str,
                 tools: list["SdkMcpTool[Any]"],
                 task: "InterpretationTask",
                 on_context_reset: Callable[[], None]) -> None:
        # The spec may name only the backend ("Codex"), leaving the model to it.
        self.model = model or self.DEFAULT_MODEL
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
