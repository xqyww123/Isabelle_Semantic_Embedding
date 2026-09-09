"""Semantic interpretation of Isabelle entities, driven by an LLM agent.

Driver-agnostic core: the work queue and its batches, the missing-entry retry
loop, the per-entity gate, the failure classes and the completeness invariant
live here; which agent backend actually runs a prompt is the
`interpretation_driver` subpackage's business.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
import math
import os
import random
import re
from collections import deque
from collections.abc import Callable, Generator, Iterable
from typing import TYPE_CHECKING, Any, NamedTuple, Self

import numpy as np
from Isabelle_RPC_Host import Connection, isabelle_remote_procedure
from Isabelle_RPC_Host.universal_key import EntityKind, is_WIP, universal_key
from Isabelle_RPC_Host.unicode import pretty_unicode
from claude_agent_sdk import SdkMcpTool, tool

from .base import ToolCall_ret, mk_ret as _mk_ret
from .desugar import mk_desugar_and_explain_tool
from .document_text import entity_document_text
from .interpretation_driver import (
    InterpretationDriver,
    available_interpretation_drivers,
    make_interpretation_driver,
    resolve_interpretation_driver_class,
)
from .semantic_embedding import _embed_tracing_gated
from .semantics import Provenance, Semantic_DB, SemanticRecord, unpack_thy_status

if TYPE_CHECKING:
    from .semantics import Semantic_Vector_Store

# --- Module-level configuration ---

_DEFAULT_DRIVER = "ClaudeCode"

interpretation_driver_override: str = ""
"""Process-wide choice of agent backend, outranking every other source.

A ``"<Driver>[.<model>]"`` string, exactly as the Isabelle config option and the
environment variable carry it (see `_resolve_driver`).  Empty means "not set":
this is the batch CLI's channel into the pipeline (`semantics_manage collect
--driver`), and it must stay empty when the user did not ask for one."""


def _resolve_driver(from_isabelle: str) -> tuple[str, str]:
    """Which agent backend and model to run, as ``(driver_name, model)``.

    Four sources, first non-empty wins: the batch CLI, the Isabelle config option
    `Semantic_Embedding.interpretation_driver` (already resolved ML-side and
    passed down as data -- never looked up per theory, see its comment in
    semantic_store.ML), the environment, and finally ClaudeCode.  Empty string is
    "not set" at every layer, which is this package's one convention for it
    (cf. `embedding_driver`).

    The value is ONE string carrying both halves, split at the FIRST dot -- so a
    model name may contain dots (``Codex.gpt-5.5``) while a driver name may not.
    Keeping them in one value is what makes a mismatched pair (one layer naming
    the driver, another naming a model that backend has never heard of)
    structurally impossible.  An empty model half means "that driver's own
    default".  Same rule as AoA's driver spec (independent implementation)."""
    spec = (interpretation_driver_override or from_isabelle
            or os.environ.get("INTERPRETATION_DRIVER", "") or _DEFAULT_DRIVER)
    driver_name, _, model = spec.partition(".")
    return driver_name, model


def _resolve_driver_and_model(from_isabelle: str):
    """`_resolve_driver`, then the backend class and its canonical model name.

    One function because the three steps are one decision: a misspelt backend
    and a shorthand model name are both configuration errors, and both must be
    settled BEFORE the task is built -- the task's model is what the database
    records, so a name normalised any later would be recorded wrong."""
    driver_name, model = _resolve_driver(from_isabelle)
    driver_cls = resolve_interpretation_driver_class(driver_name)
    if driver_cls is None:
        raise FatalAgentError(
            f"Semantic interpretation failed: unknown interpretation driver "
            f"{driver_name!r}. Known drivers: "
            f"{', '.join(available_interpretation_drivers())}.")
    return driver_name, driver_cls, driver_cls.canonical_model(model)

# --- Entity kinds and the agent's addressing labels ---

_KIND_CONSTANT = 1
_KIND_THEOREM = 2
_KIND_TYPE = 3
_KIND_CLASS = 4
_KIND_LOCALE = 5
_KIND_THEOREM_COLLECTION = 6
_KIND_METHOD = 7
_KIND_INTRODUCTION_RULE = 0x12
_KIND_ELIMINATION_RULE = 0x22
_KIND_INDUCTION_RULE = 0x32
_KIND_CASE_SPLIT_RULE = 0x42
# NB: these label strings must stay identical to the `type` enum in
# _answer_schema below — the agent echoes the label back and it is matched
# against the keys built from _KIND_PROMPT_LABELS; any drift silently drops
# every answer for that kind ("Unknown entry").
_KIND_PROMPT_LABELS = {
    _KIND_CONSTANT: "constant",
    _KIND_THEOREM: "lemma",
    _KIND_TYPE: "type",
    _KIND_CLASS: "typeclass",
    _KIND_LOCALE: "locale",
    _KIND_THEOREM_COLLECTION: "named theorem bundles",
    _KIND_METHOD: "proof method",
    _KIND_INTRODUCTION_RULE: "introduction rule",
    _KIND_ELIMINATION_RULE: "elimination rule",
    _KIND_INDUCTION_RULE: "induction rule",
    _KIND_CASE_SPLIT_RULE: "case-split rule",
}

# Module-load invariants for the agent addressing scheme (see `_label`).  The
# ML side (Universal_Key.entity_kind_int) and this dict must agree: every
# interpretable entity kind needs exactly one title, and titles must be
# injective — the agent echoes the title back to address an entry, so two kinds
# sharing a title would make answers ambiguous, and a missing kind would route
# to the dead "unknown" branch.  Asserting here makes such drift fail fast at
# import rather than only on a coincidental runtime collision.  THEORY (0) and
# EXPERIENCE (8) are excluded: theory entities are never interpreted, and an
# experience carries its own goal_description as the interpretation (it is
# written directly, never produced by this deformalization pipeline).
_NON_INTERPRETABLE_KINDS = (EntityKind.THEORY, EntityKind.EXPERIENCE)
assert len(set(_KIND_PROMPT_LABELS.values())) == len(_KIND_PROMPT_LABELS), (
    "_KIND_PROMPT_LABELS titles must be injective (the agent addresses entries "
    "by title + name)")
assert set(_KIND_PROMPT_LABELS) == {
    k.value for k in EntityKind if k not in _NON_INTERPRETABLE_KINDS
}, ("_KIND_PROMPT_LABELS keys must cover exactly the interpretable EntityKind "
    "ints (all kinds except THEORY and EXPERIENCE); it has drifted from "
    "Universal_Key.entity_kind_int")

_BATCH_SIZE = 20

# Provenance-collapse markers.  Sibling facts produced by one locale
# interpretation carry, in their prompt_extra hint (built by mk_instance_hint in
# semantic_store.ML), an identical "Generated by a locale interpretation ..."
# head line and an identical — often ~1KB — 'Locale "...": ...' description
# line.  When a batch is a run of such siblings (e.g. the Tarski geometry
# interpretations), those two lines are repeated verbatim per entry and can
# dominate the batch payload, pushing the answer-tool result past the harness
# MCP token cap.  Within a batch, when an entry's two lines are byte-identical
# to the immediately preceding entry's, the head is collapsed to a back-
# reference and the locale-description line is dropped.
_HINT_HEAD_PREFIX = "Generated by a locale interpretation"
_HINT_LOCALE_PREFIX = 'Locale "'
_HINT_SAME_LOCALE = "Generated from the same locale interpretation as the fore entry"

# Upper bound on how many times _run_agent may recycle its client for the SAME
# file on hard-failure paths (poisoned session, or an unexpected transport
# exception) before giving up — these paths make no progress on their own, so
# without a cap they spin.  Usage-limit / rate-limit waits do NOT consume this
# budget (they are throttled and resume legitimately).
_MAX_AGENT_RECYCLES = 8

# Consecutive retry rounds with no newly-answered entry after which the retry
# loop gives up on the still-missing entries.  Giving up RAISES: an entry that
# never gets an interpretation is a failure, never a silently-empty result.
# See the completeness invariant on `interpret_file`.
_MAX_STALLED_RETRIES = 10

# The semantic change gate's prefilter (plan §5.4 step 2, §7): a cosine on the
# two embedding-document texts below this is CHANGED without a judge; the
# constant was measured on the document text (0 misses / 24 tracked pairs).
_GATE_SIMILARITY = 0.90
# The prefilter's one `embed` call is bounded: `embed` otherwise inherits the
# corpus embedding's retry ladder (about 17 minutes), the right policy for a
# corpus pass and the wrong one for a gate whose failure answer D2 fixes.
_PREFILTER_TIMEOUT_S = 60
# At most this many judge sessions at once, process-wide (D12).  Gates still
# start the instant an answer arrives; only the session waits for a permit.
_JUDGE_SESSIONS = asyncio.Semaphore(40)

# Standing instructions for the interpretation agent.  These are batch- and
# file-independent, so they live in the system prompt rather than the per-batch
# user messages: the system prompt is re-sent verbatim on every request and is
# never folded into a context-compaction summary, so the agent keeps the full
# translation spec even after the original batch prompts have been compacted
# away.  Only the per-batch work (which theory/file, which entries) stays in
# the user messages built by `build_prompt`.
_SYSTEM_PROMPT = """\
You informalize entities from Isabelle theory files: you translate each formal \
statement you are given into a thorough, self-contained plain-English description.

For each entry, aim for 2–5 sentences. \
State only what the entity defines or asserts. \
Do NOT explain how it is derived or why it is useful. \
The formal statement is already shown; describe its meaning **rather than** transcribing it. \
Prefer plain English over formulas. Wrap formulas in backticks (e.g., `x`, `x + 1`). \
When a lemma/rule/term has a well-known name (e.g., proof by contradiction), you MUST mention it explicitly in the translation. \
Every translation must be **self-contained**: assume the reader has no prior context and knows no notation. \
Do not assume they know what any symbol means — for instance, do not assume they know that `x # l` prepends `x` \
to the list `l`; spell out such notation wherever you use it. \
Make sure that every nonstandard notion has been clearly explained somewhere in each of your translations. \
Be thorough rather than terse: fully unfold what the statement means — name and explain every variable, symbol, \
and sub-expression it involves — instead of compressing it into a single line (still without explaining its \
derivation or usefulness).

- For a `named theorem bundles` entry, describe what kind of facts the collection gathers and its purpose; \
you may use the listed current members to infer this, but do NOT enumerate the members in your answer. \
The declared comment in the command (if any) is often terse, inaccurate, or incomplete, so check it \
against the members: copy it verbatim only when it is genuinely complete and accurate, otherwise \
correct and expand it into a full description using the members. \
- For a `proof method` entry, describe the proof strategy or tactic it performs, when it should be used, \
and what kinds of proof goals it is meant to solve; if its description is empty, \
draw on the surrounding context and its uses in other files to learn what it does.

Line numbers in brackets (e.g. [line 42]) indicate where each entity appears in the source file.

Examples of good translations:
- constant Nat.add: The addition operator on natural numbers, taking two natural numbers and returning their sum.
- lemma List.length_append: The length of the concatenation of two lists equals the sum of their individual lengths.
- lemma List.map_comp: Mapping `f` then `g` over a list is the same as mapping their composition `g ∘ f`.
- type Prod: The product type, consisting of a pair of two values of possibly different types.
- introduction rule notI `(P ⟹ False) ⟹ ¬P`: The rule of proof by contradiction — to prove `¬P`, assume `P` and derive `False`.
- named theorem bundles Groups.algebra_simps: A collection of rewrite rules that normalise expressions over groups, rings and related structures — multiplying products out and ordering sums and products into a canonical form — so the simplifier can decide algebraic equalities and help discharge inequalities.
- proof method Presburger.presburger: An automatic decision procedure for first-order linear arithmetic over integers and naturals (Presburger arithmetic) — it eliminates quantifiers and handles divisibility and modulo constraints via Cooper's algorithm.

Translation hints:
- Suc n → "the successor of n" or "n + 1"

When you encounter an entity whose meaning is unclear, use `mcp__isabelle_semantics__query`, \
`mcp__isabelle_semantics__hover`, or \
`mcp__isabelle_semantics__definition` to look it up before translating. \
However, you cannot query entries you have been asked to translate — do it yourself.

Submit all translations via `mcp__isabelle_semantics__answer`."""

# Standing instructions for the judge session of the semantic change gate
# (plan §5.4 step 3, §15.6): one entity, two descriptions, one verdict.
_JUDGE_SYSTEM_PROMPT = """\
You compare two English descriptions of one Isabelle entity (a constant, type, \
typeclass or locale) and report whether they describe the same mathematical meaning.

Wording, order and level of detail do not matter. A change in what is asserted or \
defined does: a different definition, a different domain, an added or dropped \
condition or argument, a different result.

Report exactly one verdict through `mcp__isabelle_semantics__verdict` \
(same=true when the two descriptions mean the same, same=false otherwise, \
with a one-sentence reason), then stop."""


def _label(e: Entry) -> str:
    """The agent-facing addressing label for an entry: kind-title + name.

    This is the ONLY handle the agent has to address an entry (it echoes
    ``{type, name}`` back through the ``answer`` tool).  It must be IDENTICAL
    everywhere it is formed — the prompt the agent reads (`format_entries` /
    `_pretty_print_entry`) and the answer-routing map `_label_to_idx` — so
    the label the agent echoes round-trips to the right entry.  Use `.get(...,
    "unknown")` (not `[...]`) so the key matches what `format_entries` shows."""
    return f"{_KIND_PROMPT_LABELS.get(e.kind, 'unknown')} {e.name}"


def _pretty_print_entry(e: Entry) -> str:
    pp = _label(e)
    if e.prop_str:
        pp += f": {e.prop_str}"
    return pp


class Entry(NamedTuple):
    """A single entity to interpret."""
    kind: int            # _KIND_CONSTANT, _KIND_THEOREM, etc.
    name: str            # fully qualified name (Unicode)
    prop_str: str        # printed proposition / type signature (Unicode); stored as expr
    # where the entity is declared, as (portable symbolic file path, line, byte
    # column); None when it has none (archive/plans/ENTITY_POSITION_PLAN.md §10).  Stored in the
    # semantic DB record; `line_number` below reads its line.
    position: "tuple[str, int, int] | None"
    universal_key: universal_key
    prompt_extra: str = ""  # extra context shown to the agent only, NOT stored as expr
                            # (e.g. current members of a named_theorems collection,
                            # or locale-interpretation provenance)
    # locale-interpretation provenance (None for ordinary entries); stored
    # alongside the interpretation in the semantic DB
    locale_provenance: "Provenance | None" = None
    # constituent theories of theorem/rule entities — sorted (theory long
    # name, 16-byte theory hash) list whose XOR is the key's theory prefix;
    # None for non-theorem kinds.  Stored in the semantic DB record.
    theory_constituents: "list[tuple[str, bytes]] | None" = None
    # full name of the dynamic collection the entry's name was invented from;
    # None when the name was adopted from the producer
    # (archive/plans/DYNAMIC_MEMBER_NAMING_PLAN.md §2.2).  Stored in the semantic DB record.
    from_collection: "str | None" = None
    # --- incremental invalidation (CHECK_OUTDATE_PLAN.md §3.2, step 9) ---
    # 16-byte semantic digest of the entity's own content; None for
    # theorem-alike entries (their key's thm128 is the digest) and for every
    # entry of a persistent theory (content-addressed keys need no digest).
    semantic_digest: "bytes | None" = None
    # dependency edges as the targets' CURRENT universal keys, resolved at
    # scan time on the ML side; empty for entries of persistent theories.
    # An entry is increment-tracked iff it carries a digest or any edges.
    deps: "list[bytes] | None" = None

    @property
    def line_number(self) -> int:
        """Source line, -1 if unavailable -- the form the agent prompt speaks
        (format_entries guards on line_number > 0).  A property, not a field: the
        line now travels inside `position`, and a NamedTuple may carry properties
        as long as the name is not also a field."""
        return self.position[1] if self.position is not None else -1


class CostSummary(NamedTuple):
    """Token usage and dollar cost for an interpretation run."""
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_tokens: int
    cost_usd: float

    def plus(self, other: 'CostSummary') -> 'CostSummary':
        return CostSummary(*(a + b for a, b in zip(self, other)))  # type: ignore[arg-type]


_NO_COST = CostSummary(0, 0, 0, 0, 0.0)


class InterpretationResult(NamedTuple):
    """Result of interpreting a theory file."""
    interpretations: list[str | None]   # per-entry semantic interpretation (None if unanswered)
    pretty_prints: list[str]            # per-entry Unicode pretty-print
    current_cost: CostSummary           # cost incurred in this call
    cumulative_cost: CostSummary        # total cost including historical


# The entity states of one interpretation run (plan §5.3.1), 1:1 with the
# task's entries.  `results[idx] is None` iff _QUEUED or _SENT.
_NOT_ENROLLED, _QUEUED, _SENT, _GATING, _DONE = range(5)


class RunState:
    """State scoped to one interpretation run (plan §15.8 "Run-scoped
    state"): one holder of the interpretation lock (§8, §13 step 7) once the
    lock lands; until then, one `interpret_file`."""

    def __init__(self) -> None:
        # The prefilter is skipped for the rest of the run: set by the startup
        # check when the embedding service is unconfigured, and by the first
        # failed embedding call (§5.4 failures).
        self.prefilter_disabled = False

    def claim_prefilter_disable(self) -> bool:
        """Disable the prefilter for the rest of the run, and say whether THIS
        caller disabled it -- so §12 #5 is announced once even by the gates
        that were all inside the failing call when the service went down.
        One synchronous step: the read and the flip cannot be separated."""
        first, self.prefilter_disabled = not self.prefilter_disabled, True
        return first


def current_run_state() -> RunState:
    """The run's `RunState`.  No run holds the lock before §13 step 7, so
    this is a fresh one per call and the scope degrades to the one
    `interpret_file` that resolves it at its top -- never a module-level
    singleton that would outlive the run."""
    return RunState()


# Theory-status keys of the cost accumulators, in the order of the
# `(input, cache_creation, cache_read, output, cost)` tuples used throughout.
_COST_KEYS = (b"input_tokens", b"cache_creation_tokens", b"cache_read_tokens",
              b"output_tokens", b"cost_usd")


class AgentTask:
    """The state of one agent session: the entries it may be asked about, the
    answers, the batch in flight and the cost accumulators.  `_run_agent`, the
    drivers and the MCP server all take "the task" through this base; the
    interpretation task adds the theory's work queue and the entity states,
    the judge task (plan §15.6) holds one entity and records a verdict."""

    #: prefix of the extra theory-status keys `write_cost` folds this task's
    #: cost into beside the unprefixed totals (b"judge_" on a judge task, §15.9)
    cost_prefix: bytes = b""
    #: entries per turn; fixed when the task is built (tests set it per task)
    batch_size: int = _BATCH_SIZE
    #: stalled retry rounds `_retry_unanswered` allows before it gives up: on
    #: the interpretation task "raise after this many", on the judge "ask
    #: once more, then CHANGED" (plan §15.6)
    max_stalled_retries: int = _MAX_STALLED_RETRIES

    def __init__(self, connection: Connection, file_path: str,
                 theory_longname: str, theory_key: universal_key,
                 entries: list[Entry], driver: str = _DEFAULT_DRIVER,
                 model: str = ""):
        self.connection = connection
        self.file_path = file_path
        self.theory_longname = theory_longname
        self.theory_key = theory_key
        self.entries = entries
        # Which backend and model produced these interpretations.  write_cost
        # records them, so a theory's provenance stays readable after the config
        # that chose them has changed.  `model` may start empty when the backend
        # picks the model itself (ClaudeCode with an empty model half runs the
        # CLI's configured default); the driver then backfills it from the
        # response stream before the first cost flush.
        self.driver = driver
        self.model = model
        # results / state are index-aligned with `entries`; the agent addresses
        # an entry only by its label (see `_label` and `mk_answer_tool`), routed
        # through _label_to_idx.  Two entries sharing a label would be mutually
        # un-addressable, so the map RAISES on the first duplicate -- the ML
        # side (Semantic_Store, (entity-kind, name) assert) guarantees
        # uniqueness, so this only ever fires on a genuine regression.
        self.results: list[str | None] = [None] * len(entries)
        self._label_to_idx: dict[str, int] = {}
        for i, e in enumerate(entries):
            key = _label(e)
            if key in self._label_to_idx:
                j = self._label_to_idx[key]
                raise ValueError(
                    f"duplicate interpretation label {key!r} at entries {j} and {i} "
                    f"(uks {bytes(entries[j].universal_key).hex()} and "
                    f"{bytes(e.universal_key).hex()}); (kind,name) labels must be "
                    f"unique to be addressable by the agent")
            self._label_to_idx[key] = i
        self.state: list[int] = [_NOT_ENROLLED] * len(entries)
        self._queue: deque[int] = deque()
        # The enrolled entries' names, appended by `enqueue`; handed to the
        # query tool as the same mutable list, so its refusal follows enrolment.
        self.enrolled_names: list[str] = []
        self.batch: list[int] = []          # indices sent in the turn in flight
        self.gates_running = 0
        self._progress = asyncio.Event()    # set when a gate finishes or enrols
        # `total_*` is the pending delta not yet flushed to LMDB; write_cost()
        # accumulates it into the theory record and resets it to 0.  Cost is
        # flushed per agent turn (see the drivers' _record_turn_cost) -- so an
        # interrupt (the parallel scheduler's by-design hard-crash) cannot drop
        # the cost of the turns already run.
        self.total_input_tokens = 0
        self.total_cache_creation_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        # `run_*` is the cumulative cost of THIS interpret_file invocation; it is
        # never reset by write_cost(), so it survives the per-turn flushes and
        # is reported as `current_cost`.
        self.run_input_tokens = 0
        self.run_cache_creation_tokens = 0
        self.run_cache_read_tokens = 0
        self.run_output_tokens = 0
        self.run_cost_usd = 0.0
        # (error_status, error) of every `api_retry` system message seen this run.
        # The terminal ResultMessage of an expired credential is byte-identical to
        # that of a dead network; this trail is the only thing that tells them apart.
        self.api_retry_errors: list[tuple[Any, Any]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    # --- the work queue (plan §5.3) ---

    def enqueue(self, idx: int) -> None:
        """Enrol an entry: it will be sent in a later batch."""
        self.results[idx] = None
        self.state[idx] = _QUEUED
        self._queue.append(idx)
        self.enrolled_names.append(self.entries[idx].name)
        self._progress.set()

    def next_batch(self) -> list[int]:
        """The indices to send next: what the turn in flight left unanswered
        (non-empty only after a recycle), then the queue's head, up to
        `batch_size` in all -- marked sent and remembered as the batch in flight."""
        batch = self.unanswered_in_batch()
        while self._queue and len(batch) < self.batch_size:
            i = self._queue.popleft()
            if self.state[i] == _QUEUED:        # else answered ahead of its turn
                self.state[i] = _SENT
                batch.append(i)
        self.batch = batch
        return batch

    def unanswered_in_batch(self) -> list[int]:
        return [i for i in self.batch if self.state[i] == _SENT]

    def unanswered(self) -> list[int]:
        """The enrolled entries still without an answer, run-wide (m of §12)."""
        return [i for i, s in enumerate(self.state) if s in (_QUEUED, _SENT)]

    def enrolled(self) -> int:
        """N of §12: the entries enrolled so far (grows, never shrinks)."""
        return sum(1 for s in self.state if s != _NOT_ENROLLED)

    def answered(self) -> int:
        """k of §12: the entries answered so far, gate running or done."""
        return sum(1 for s in self.state if s in (_GATING, _DONE))

    def n_interpreted(self) -> int:
        """A of §12 #7: the entities this run wrote -- counted once however
        many gates each needed (a correction re-runs the gate, D11)."""
        return sum(1 for s in self.state if s == _DONE)

    async def wait_for_progress(self) -> None:
        """Sleep until a gate finishes or enrols an entry.  A set that lands
        before the wait is not lost: the event stays set until cleared here."""
        await self._progress.wait()
        self._progress.clear()

    def gate_started(self) -> None:
        self.gates_running += 1

    def gate_finished(self) -> None:
        self.gates_running -= 1
        self._progress.set()

    def session_started(self) -> None:
        """Called by `_run_agent` when a fresh driver session opens (the first
        one and every recycle)."""

    # --- supplied by the subclasses ---

    def format_entries(self, indices: Iterable[int]) -> str:
        raise NotImplementedError

    def build_prompt(self, indices: list[int]) -> str:
        raise NotImplementedError

    def on_answer(self, idx: int, text: str) -> None:
        raise NotImplementedError

    def retry_report(self, n_missing: int, attempt: int) -> str:
        """The warning line shown before a retry turn; "" for none."""
        raise NotImplementedError

    def retry_prompt(self, chunk: list[int]) -> str:
        raise NotImplementedError

    def unanswered_failure(self, missing_names: list[str]) -> str:
        """The message of the FatalAgentError raised when retries give up."""
        raise NotImplementedError

    # --- cost ---

    def run_cost(self) -> CostSummary:
        """The cost of THIS invocation so far (the `run_*` accumulators)."""
        return CostSummary(self.run_input_tokens, self.run_cache_creation_tokens,
                           self.run_cache_read_tokens, self.run_output_tokens,
                           self.run_cost_usd)

    def historical_cost(self) -> tuple[int, int, int, int, float]:
        """Read cumulative cost from LMDB (without modifying it).  A layered
        read: a system-resident status counts, a tombstoned one reads as zero."""
        raw = Semantic_DB._get_raw(self.theory_key)
        if not raw:
            return (0, 0, 0, 0, 0.0)
        prev = unpack_thy_status(raw)
        return tuple(prev.get(k, 0) for k in _COST_KEYS)  # type: ignore[return-value]

    def write_cost(self) -> tuple[int, int, int, int, float]:
        """Accumulate cost into the LMDB store. Returns updated cumulative totals.

        Read-modify-write: copy-up-then-modify (plan §3.1).  The previous status
        is read through the layers (user first, tombstone = start fresh, then
        system), the updated one lands in the user env with every untouched
        field carried forward -- so system-layer cost/tokens accumulate onward
        and ``finished`` is never defaulted to False over a layered True.

        The delta goes into the unprefixed keys (the theory's totals) and, when
        `cost_prefix` is set, into the prefixed keys as well, so a judge's cost
        is a breakdown of the totals rather than a second sum (§15.9)."""
        import msgpack
        delta = (self.total_input_tokens, self.total_cache_creation_tokens,
                 self.total_cache_read_tokens, self.total_output_tokens,
                 self.total_cost_usd)
        env = Semantic_DB._ensure_env()
        with env.begin(write=True) as txn:
            raw = txn.get(self.theory_key)
            if raw is not None and len(raw) == 0:
                raw = None                                # tombstoned: start fresh
            elif raw is None:
                raw = Semantic_DB._system_get(self.theory_key)   # copy-up
            prev = unpack_thy_status(raw) if raw else {}
            total = tuple(prev.get(k, 0) + d for k, d in zip(_COST_KEYS, delta))
            data = dict(prev)      # preserve every field this write does not touch
            data.update(zip(_COST_KEYS, total))
            if self.cost_prefix:
                data.update({self.cost_prefix + k: prev.get(self.cost_prefix + k, 0) + d
                             for k, d in zip(_COST_KEYS, delta)})
            data.update({
                b"model": self.model,
                # New field; readers use .get, so older records (no b"driver")
                # need no migration -- they all predate any driver but ClaudeCode.
                b"driver": self.driver,
            })
            if is_WIP(self.theory_key):
                # WIP status records carry no `finished` field at all
                # (CHECK_OUTDATE_PLAN.md §3.4) -- their skip criterion is the
                # (process id, theory serial) pair, written by mark_interpreted
                # only after a completed run; this cost flush must neither
                # introduce the field nor keep a legacy one alive.
                data.pop(b"finished", None)
            else:
                data[b"finished"] = prev.get(b"finished", False)
            packed: bytes = msgpack.packb(data)  # type: ignore[assignment]
            txn.put(self.theory_key, packed)
        self.total_input_tokens = 0
        self.total_cache_creation_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        return total  # type: ignore[return-value]


class InterpretationTask(AgentTask):
    """One theory's interpretation run: the work queue over its entries, the
    entity states, and the gate started by each answer (plan §5.3-§5.5)."""

    def __init__(self, connection: Connection, file_path: str,
                 theory_longname: str, theory_key: universal_key,
                 entries: list[Entry], driver: str = _DEFAULT_DRIVER,
                 model: str = "", *, unicode_file_path: str = "",
                 rec_cache: 'dict[bytes, SemanticRecord | None] | None' = None,
                 dependents: 'list[list[int]] | None' = None,
                 emb_store: 'Semantic_Vector_Store | None' = None,
                 run_state: RunState | None = None,
                 make_judge_driver: 'Callable[[JudgeTask], InterpretationDriver] | None' = None):
        super().__init__(connection, file_path, theory_longname, theory_key,
                         entries, driver, model)
        self.unicode_file_path = unicode_file_path or file_path
        self._first_turn_sent = False
        # The gate's collaborators (plan §15.3): the vector store whose
        # provider embeds the prefilter's two texts (None: no prefilter for
        # this theory), the run's state, and the judge session factory.
        self.emb_store = emb_store
        self.run_state = run_state if run_state is not None else RunState()
        self.make_judge_driver = make_judge_driver
        self.judge_cost = _NO_COST          # the finished judge sessions' cost (§15.9)
        # The record per universal key AS CURRENTLY STORED: filled by the
        # scan, written back from inside every gate transaction, read by every
        # eff* (plan §15.5, §15.8).  The task carries no pre-run record, so a
        # second gate on an entity cannot roll a committed version back (§3).
        self.rec_cache = rec_cache if rec_cache is not None else {}
        # The theory-internal reverse graph: dependents[j] = the entries whose
        # deps name entry j (§15.8 item 5); read by the propagation (§5.3.1).
        self.dependents = dependents or [[] for _ in entries]
        # The task group owning the gate tasks; `interpret_file` sets it.
        self.task_group: asyncio.TaskGroup | None = None

    def session_started(self) -> None:
        # Every fresh session must be told to load the skills: the first
        # prompt it sees takes the first-turn form.
        self._first_turn_sent = False

    def start_gate(self, idx: int) -> None:
        """Run the entry's gate as a task of the group, the `gates_running`
        count paired to the task itself: incremented before `create_task` (the
        loop must never see zero gates between an answer and its gate's first
        step), decremented by the task's done callback whatever its terminal
        state, compensated if the group refuses the task."""
        assert self.task_group is not None, "interpret_file owns the gate task group"
        coro = _gate(self, idx)
        self.gate_started()
        try:
            t = self.task_group.create_task(coro)
        except BaseException:               # an aborting group; or a cancellation delivered here
            self.gate_finished()
            coro.close()
            raise
        t.add_done_callback(lambda _t: self.gate_finished())

    def on_answer(self, idx: int, text: str) -> None:
        """Record an answer in memory and start its gate (plan §5.3, D14).  A
        re-submission of an entry (a correction, D11) is an answer like any
        other: it re-runs the gate, whose verdict depends on the text; one that
        changes nothing does nothing, and a gate already running picks the new
        text up itself (see `_gate`)."""
        old, self.results[idx] = self.results[idx], text
        if text == old:
            return
        if self.state[idx] == _GATING:
            return
        self.state[idx] = _GATING           # from _QUEUED / _SENT, or from _DONE (a correction)
        self.start_gate(idx)

    @staticmethod
    def _collapse_provenance(prompt_extra: str,
                             prev: 'tuple[str | None, str | None]',
                             ) -> 'tuple[str, tuple[str | None, str | None]]':
        """Collapse the repeated locale-interpretation provenance of a sibling
        fact against the preceding entry.

        When this entry's "Generated by ..." head line AND its 'Locale "...": '
        description line are both byte-identical to ``prev`` (the preceding
        entry's same two lines), the head is replaced by a back-reference and
        the description line is dropped.  Returns the (possibly rewritten)
        prompt_extra and this entry's ORIGINAL (head, locale) pair, which feeds
        the next entry's comparison — chaining always compares against the
        un-collapsed lines, so a whole run of siblings collapses correctly."""
        src = prompt_extra.split("\n")
        head = next((l for l in src if l.startswith(_HINT_HEAD_PREFIX)), None)
        locale = next((l for l in src if l.startswith(_HINT_LOCALE_PREFIX)), None)
        if head is not None and locale is not None and (head, locale) == prev:
            kept = [_HINT_SAME_LOCALE if l == head else l
                    for l in src if l != locale]
            return "\n".join(kept), (head, locale)
        return prompt_extra, (head, locale)

    def format_entries(self, indices: Iterable[int]) -> str:
        lines = []
        prev_prov: 'tuple[str | None, str | None]' = (None, None)
        for i in indices:
            e = self.entries[i]
            label = _KIND_PROMPT_LABELS.get(e.kind, "unknown")
            line = (f"  [line {e.line_number}] " if e.line_number > 0 else "  ") + f"{label} {e.name}"
            if e.prop_str:
                line += f": {e.prop_str}"
            if e.prompt_extra:
                extra, prev_prov = self._collapse_provenance(e.prompt_extra, prev_prov)
                # indent the extra context block under the entry line
                line += "\n    " + extra.replace("\n", "\n    ")
            else:
                prev_prov = (None, None)
            lines.append(line)
        return "\n".join(lines)

    def build_prompt(self, indices: list[int]) -> str:
        entries_text = self.format_entries(indices)
        if self._first_turn_sent:
            return (
                f'Continue with the following entities from Isabelle theory "{self.theory_longname}" (location: {self.unicode_file_path}).\n\n'
                f"Entries:\n{entries_text}\n\n"
                f"Submit translations via `mcp__isabelle_semantics__answer`."
            )
        self._first_turn_sent = True
        return (
            f"Load the skills `isabelle-intro-elim-rules`, `isabelle-datatype`, and `isabelle-record`.\n"
            f'Informalize the following entities from Isabelle theory "{self.theory_longname}" (location: {self.unicode_file_path}).\n\n'
            f"Entries:\n{entries_text}\n\n"
            f"Submit translations via `mcp__isabelle_semantics__answer`."
        )

    def retry_report(self, n_missing: int, attempt: int) -> str:
        return (f"{self.theory_longname}: {n_missing} of {self.enrolled()} entities "
                f"still have no interpretation; asking the LLM again "
                f"(attempt {attempt} of {_MAX_STALLED_RETRIES}).")

    def retry_prompt(self, chunk: list[int]) -> str:
        # Re-send the full entry text (line, kind, name, proposition) via
        # format_entries, NOT bare names: after context compaction the original
        # batch prompts are gone, and for facts generated by locale
        # interpretations the proposition is unrecoverable from the source file
        # -- a names-only list forces the agent to answer from memory, inviting
        # mispaired translations.
        return (
            f"You still have {len(chunk)} unanswered entries from theory "
            f'"{self.theory_longname}" (location: {self.file_path}):\n'
            f"{self.format_entries(chunk)}\n\n"
            f"Submit their translations via the `mcp__isabelle_semantics__answer` tool. "
            f"Each translation must describe the formal statement shown above next to that exact name."
        )

    def unanswered_failure(self, missing_names: list[str]) -> str:
        return _msg_unanswered(self.theory_longname, missing_names, self.enrolled())


class JudgeTask(AgentTask):
    """One judge session of the semantic change gate (plan §15.6): the one
    entity whose baseline and fresh descriptions it compares, and the
    verdict it reports through the `verdict` tool.  No queue beyond its one
    entry, no database writer: the gate that built it writes."""

    cost_prefix = b"judge_"
    max_stalled_retries = 1             # ask once more, then CHANGED (§5.4 step 3)

    def __init__(self, parent: InterpretationTask, idx: int, baseline: str, fresh: str):
        super().__init__(parent.connection, parent.file_path, parent.theory_longname,
                         parent.theory_key, [parent.entries[idx]], parent.driver,
                         parent.model)
        self.baseline, self.fresh = baseline, fresh
        self.verdict: bool | None = None    # True: "same"; None: no verdict given
        self.enqueue(0)

    def format_entries(self, indices: Iterable[int]) -> str:
        return "\n".join(_label(self.entries[i]) for i in indices)

    def build_prompt(self, indices: list[int]) -> str:
        return (f"Entity: {_label(self.entries[0])}\n\n"
                f"Description 1:\n{self.baseline}\n\n"
                f"Description 2:\n{self.fresh}\n\n"
                f"Do they describe the same meaning? "
                f"Answer with the `mcp__isabelle_semantics__verdict` tool.")

    def on_answer(self, idx: int, text: str) -> None:
        self.results[idx] = text            # the verdict's `why`
        self.state[idx] = _DONE

    def retry_report(self, n_missing: int, attempt: int) -> str:
        return ""                           # host log only (D10)

    def retry_prompt(self, chunk: list[int]) -> str:
        return ("You have not reported a verdict. Call "
                "`mcp__isabelle_semantics__verdict` now with same=true or "
                "same=false, then stop.")

    def unanswered_failure(self, missing_names: list[str]) -> str:
        return f"judge gave no verdict for {missing_names[0]}"


_log = logging.getLogger(__name__)


# --- MCP Tool: answer ---

_answer_schema = {
    "type": "object",
    "properties": {
        "interpretations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["constant", "lemma", "type", "typeclass", "locale",
                                 "named theorem bundles", "proof method",
                                 "introduction rule", "elimination rule",
                                 "induction rule", "case-split rule"]
                    },
                    "name": {
                        "type": "string",
                        "description": "The name of the entity, e.g. 'Groups.abel_semigroup'.",
                    },
                    "translation": {
                        "type": "string",
                        "description": "The plain-English translation of this entity.",
                    },
                },
                "required": ["type", "name", "translation"],
            },
            "description": "List of English translations to submit.",
        },
    },
    "required": ["interpretations"],
}


def mk_answer_tool(task: InterpretationTask) -> SdkMcpTool[Any]:
    """The `answer` tool of one interpretation task.  A closure over the task
    (not an ambient variable): the interpretation session and the concurrent
    judge sessions each carry their own tools, so an answer can never be
    routed to another task."""

    @tool(
        "answer",
        "Submit English translations for one or more of the listed entries. "
        "Each translation should be a concise plain-English description of what the entity defines or asserts. "
        "You may also resubmit an entry to correct a previous answer. "
        "To see the remaining unanswered entries in the current batch, call this tool with an empty list [].",
        input_schema=_answer_schema,
    )
    async def answer(args: dict[str, Any]) -> ToolCall_ret:
        errors = []
        count = 0
        for item in args["interpretations"]:
            key = f"{item['type']} {item['name']}"
            # Address by the label->entry-index map: it indexes the FULL
            # `entries` list (a lookup through a deduplicated label list once
            # wrote translations onto neighbouring entries' universal_keys).
            # An entry this run did not ask for is refused (plan §15.8): it
            # starts no gate.
            idx = task._label_to_idx.get(key)
            if idx is None or task.state[idx] == _NOT_ENROLLED:
                errors.append(f"Unknown entry: {key!r}")
                continue
            # Strip lone UTF-16 surrogates the model occasionally emits mid math-
            # alphanumeric glyph (e.g. a bare U+D835 with no low half).  They
            # crash msgpack's strict-UTF-8 packb at the write -- so the answer
            # would be lost on exactly the entry that glitched -- and, left in
            # the conversation, make every subsequent API request fail with 400
            # "no low surrogate in string", wedging the whole file.
            trans = re.sub(r"[\ud800-\udfff]", "", item["translation"])
            task.on_answer(idx, trans)
            _log.info("answer: %s = %s", key, trans)
            count += 1
        remaining = task.unanswered_in_batch()
        cs = "" if count == 1 else "s"
        _log.info("answer: submitted %d, batch_remaining %d, %d/%d done",
                  count, len(remaining), task.answered(), task.enrolled())
        # The only fine-grained sign of life during a long theory.  Always name
        # the theory: several run concurrently, so an unqualified "20 of 244"
        # would be unattributable.
        await _report(f"{task.theory_longname}: "
                      f"{task.answered()} of {task.enrolled()} done.")
        if not remaining:
            msg = ("Batch complete. If you noticed any mistakes in your translations, "
                   "correct them now using `mcp__isabelle_semantics__answer`. "
                   "Otherwise, stop immediately without any further output.")
        else:
            msg = (f"Answered {count} translation{cs}, remaining {len(remaining)} in this batch.\n\n"
                   f"Unanswered entries:\n{task.format_entries(remaining)}\n"
                   f"In file: {task.file_path}\n\n"
                   f"Submit translations via `mcp__isabelle_semantics__answer`.")
        if errors:
            msg += "\nErrors:\n" + "\n".join(errors)
        return _mk_ret(msg)

    return answer


# --- MCP Tool: verdict ---

_verdict_schema = {
    "type": "object",
    "properties": {
        "same": {
            "type": "boolean",
            "description": "true when the two descriptions describe the same meaning, false otherwise.",
        },
        "why": {
            "type": "string",
            "description": "One sentence: what is the same, or what differs.",
        },
    },
    "required": ["same", "why"],
}


def mk_verdict_tool(judge: JudgeTask) -> SdkMcpTool[Any]:
    """The `verdict` tool of one judge session (plan §15.6): records the
    verdict on its task and writes nothing.  A closure like `mk_answer_tool`,
    for the same reason: many judge sessions run at once."""

    @tool(
        "verdict",
        "Report whether Description 1 and Description 2 describe the same meaning.",
        input_schema=_verdict_schema,
    )
    async def verdict(args: dict[str, Any]) -> ToolCall_ret:
        judge.verdict = bool(args["same"])
        judge.on_answer(0, str(args["why"]))     # answered, for the retry loop
        _log.info("verdict: %s same=%s: %s", _label(judge.entries[0]),
                  judge.verdict, args["why"])
        return _mk_ret("Verdict received. Stop now.")

    return verdict


# --- Agent runner ---

async def _report(msg: str, *, warn: bool = False) -> None:
    """Put one progress line in front of the user, in Isabelle.

    Everything this pipeline knows used to go only to the host log file
    ($ISABELLE_HOME_USER/log/RPC_*), which neither frontend ever shows: the REPL app
    hijacks *ML* output channels, and the jEdit command has no hijack at all.  So a run
    could stall, retry, or fail for a reason plainly visible in the log while Isabelle
    showed nothing.  Connection.writeln/warning is the existing route back (the global
    `log` callback), so use it -- and keep logging too, so the log stays complete.

    writeln, not tracing: tracing is capped by the `editor_tracing_messages` option
    (default 1000) and exceeding it pops Isabelle's own blocking "Tracing paused" dialog
    (isabelle_process.ML:35-60).  A large cone would hit that.
    """
    (_log.warning if warn else _log.info)("%s", msg)
    conn = Connection.current()
    if conn is None:
        return          # no live call (unit tests, offline use) -- the log line stands
    try:
        await (conn.warning(msg) if warn else conn.writeln(msg))
    except Exception:
        # Reporting must never be able to fail the interpretation it is reporting on.
        _log.exception("could not forward this line to Isabelle")


class ReachLimitError(Exception):
    """Usage cap hit (e.g. 'You've hit your limit')."""
    pass

class RateLimitError(Exception):
    """API rate limit (429)."""
    pass

class PoisonedSessionError(Exception):
    """The conversation carries content the API rejects on every request
    (HTTP 400) — e.g. a lone UTF-16 surrogate the model emitted in an earlier
    answer is now pinned in the subprocess transcript.  Recoverable only by
    discarding the session, so `_run_agent` recycles the client (fresh, no
    resume) and continues with the still-missing entries."""
    pass

# Prefix marking an exception message as ALREADY human-readable: the Isabelle
# side reports only the marked line and suppresses the Python traceback, which
# for a recognised condition ("not logged in") carries no information a user can
# act on.  Anything WITHOUT this marker keeps its full traceback -- for the
# unrecognised bucket there is no one-liner to give, and the stack is the only
# lead.  Matched by Semantic_Store's RPC failure handler in semantic_store.ML.
USER_ERROR_MARKER = "[SEMANTIC_INTERPRETATION_USER_ERROR] "


class FatalAgentError(Exception):
    """A failure that retrying cannot fix: authentication, billing, a malformed
    request, or an unrecognised agent error.

    Raised the moment it is detected and NEVER recycled -- unlike a poisoned
    session or a transport blip, no amount of client recycling changes the
    outcome, and the 8 x 2 s recycle loop would only bury the cause.

    `human` is a one-line actionable message; when given it is emitted under
    USER_ERROR_MARKER so Isabelle can drop the traceback."""

    def __init__(self, human: str | None = None, detail: str = ""):
        self.human = human
        self.detail = detail
        msg = (USER_ERROR_MARKER + human) if human else (detail or "unexpected agent failure")
        if human and detail:
            msg = f"{msg}\n({detail})"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# User-facing failure text.  Kept next to the failure classes so the wording can
# be reviewed in one place rather than hunted through the control flow.  The
# driver-specific wording (authentication, billing, invalid request) lives with
# the driver that can recognise those conditions.
# ---------------------------------------------------------------------------

def _msg_unanswered(theory: str, missing: list[str], total: int) -> str:
    shown = ", ".join(missing[:10])
    more = f" (and {len(missing) - 10} more)" if len(missing) > 10 else ""
    return (f"Semantic interpretation failed: theory {theory} left {len(missing)} of "
            f"{total} entities uninterpreted after {_MAX_STALLED_RETRIES} retry rounds: "
            f"{shown}{more}\n"
            f"The theory has NOT been marked as interpreted; re-running will retry it.")

class TransientAgentError(Exception):
    """A server-side failure worth one more attempt.  Falls into `_run_agent`'s
    recycle handler, which is bounded by _MAX_AGENT_RECYCLES."""
    pass


# --- the eff* evaluator (plan §4, §15.5) ---

class _EffStar:
    """eff*(E) = max(version(E), contrib of each direct dependency), where a
    FRESH dependency contributes only its own version and a stale one its
    whole eff* (`_contrib`; ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md §4),
    evaluated by iterative Tarjan DFS with one numeric memo over `rec_cache`
    ∪ store (parent §4.1).  A missing record contributes 0 (§4.4:
    infrastructure targets carry no record by design).

    Folding a cycle to a max is lossless for INTRA-SCC signal (SCC members
    are defined by one command and bump together), but memo finalization must
    be SCC-wide: a node memoized before its SCC root pops misses contributions
    reachable only through the back edge (an SCC-mate's external dep), and the
    poisoned memo then serves every later lookup -- the order-dependent
    false-fresh of the 2026-07-28 review (R1, blocker; class parameter <->
    class edges make the shape an everyday one).  So no node writes memo until
    its SCC root pops; the root assigns the SCC-wide value (max over member
    versions and the effs of all external successors) to all members.

    The memo is per instance: the scan builds one and shares it across every
    entry (nothing changes during a scan); a gate builds a FRESH one per
    call, because a write between two calls changes a record.  `rec_cache`
    is the caller's dict and is extended in place by every store read, so
    "rec_cache == store" keeps holding for the keys it has seen."""

    def __init__(self, rec_cache: 'dict[bytes, SemanticRecord | None]'):
        self.rec_cache = rec_cache
        self.memo: dict[bytes, int] = {}

    def _rec_of(self, k: bytes) -> 'SemanticRecord | None':
        if k not in self.rec_cache:
            self.rec_cache[k] = Semantic_DB[k]
        return self.rec_cache[k]

    def _contrib(self, d: bytes, e: int) -> int:
        """What a FINALIZED dependency `d` whose eff is `e` hands upwards.

        A dependency that has absorbed everything upstream of it (eff <=
        interpreted_at) and whose meaning the semantic change gate judged
        unchanged (version not bumped) is a wall: the parent sees only
        version(d), not the upstream number d already dealt with.  A dependency
        that is itself stale passes its whole upstream signal through, as
        before.  None reads as 0 (§4.4), so a record with no version or no
        interpreted_at is never a wall."""
        r = self._rec_of(d)
        if r is None:
            return 0
        ver, ia = r.version or 0, r.interpreted_at or 0
        return ver if ver > 0 and ia > 0 and e <= ia else e

    def eff_uk(self, root: bytes) -> int:
        memo = self.memo
        if root in memo:
            return memo[root]
        r0 = self._rec_of(root)
        if r0 is None:
            memo[root] = 0
            return 0
        # index/low are per-call (finalized nodes live in memo and are never
        # re-indexed); scc is the candidate stack -- a node stays on it,
        # un-memoized, until its SCC root pops.  An SCC always forms a
        # contiguous DFS subtree under its root, so the val flow at non-root
        # frame pops accumulates every member's contribution into the root.
        index: dict[bytes, int] = {}
        low: dict[bytes, int] = {}
        val: dict[bytes, int] = {}
        scc: list[bytes] = []
        on_scc: set[bytes] = set()

        def _open(k: bytes, r: 'SemanticRecord') -> list:
            index[k] = low[k] = len(index)
            val[k] = r.version or 0
            scc.append(k)
            on_scc.add(k)
            return [k, iter(r.deps or [])]

        stack = [_open(root, r0)]
        while stack:
            frame = stack[-1]
            k = frame[0]
            pushed = False
            for d in frame[1]:
                if d in memo:              # finalized in an earlier SCC
                    c = self._contrib(d, memo[d])
                    if c > val[k]:
                        val[k] = c
                    continue
                if d in on_scc:            # edge into the candidate region:
                    if index[d] < low[k]:  # lowlink only -- d's own value
                        low[k] = index[d]  # reaches the root via tree pops
                    continue
                r = self._rec_of(d)
                if r is None:
                    memo[d] = 0
                    continue
                stack.append(_open(d, r))
                pushed = True
                break
            if not pushed:
                stack.pop()
                if low[k] == index[k]:
                    # SCC root: assign the SCC-wide value to every member,
                    # then flow it to the parent like any finalized successor
                    # (the parent pushed this child, so it never saw a memo
                    # hit for it -- without this flow the whole subtree's
                    # contribution would be lost).  A finished SCC never
                    # lowers the parent's lowlink.  The parent is necessarily
                    # OUTSIDE this SCC -- a parent inside it would have pulled
                    # low[k] below index[k] -- so this edge, and only this
                    # edge, takes the wall test; inside an SCC the members are
                    # defined by one command and bump together, so no wall.
                    v = val[k]
                    while True:
                        m = scc.pop()
                        on_scc.discard(m)
                        memo[m] = v
                        if m == k:
                            break
                    if stack:
                        c = self._contrib(k, v)
                        if c > val[stack[-1][0]]:
                            val[stack[-1][0]] = c
                else:
                    parent = stack[-1][0]
                    if low[k] < low[parent]:
                        low[parent] = low[k]
                    if val[k] > val[parent]:
                        val[parent] = val[k]
        return memo[root]

    def eff_value(self, version: int, deps: 'list[bytes] | None') -> int:
        """eff* of an entity whose own version is `version` (passed, never
        read back from a fabricated record) and whose direct deps are `deps`."""
        best = version
        for d in deps or []:
            v = self._contrib(d, self.eff_uk(d))
            if v > best:
                best = v
        return best


def _refresh_statements(entries: list[Entry],
                        rec_cache: 'dict[bytes, SemanticRecord | None]',
                        not_enrolled: Iterable[int]) -> None:
    """The statement refresh (plan §5.3.2): for every entry this run did not
    write, a stored `expr` that differs from the wire `prop_str` is rewritten
    (and its vector tombstoned).  The truthiness test matters: `mk_prop_str`
    yields "" for some entries, and a bare inequality would blank a stored
    `expr` and tombstone its vector.  The one write a dry run makes."""
    for i in not_enrolled:
        e = entries[i]
        rec = rec_cache[e.universal_key]
        assert rec is not None, "not enrolled means filled from the store"
        if e.prop_str and rec.expr != e.prop_str:
            Semantic_DB.update_expr(e.universal_key, e.prop_str)


# --- the gate (plan §5.4) ---

@contextlib.contextmanager
def _note_on_failure(note: str) -> Generator[None, None, None]:
    """Let a store write's own exception propagate, saying which entity it was
    writing (plan §5.4 failures).  No wrapper class: nothing matches a gate
    failure by class, and the traceback is the lead.  `Exception` only, so a
    cancellation passes untouched."""
    try:
        yield
    except Exception as exc:
        exc.add_note(note)
        raise


class _Verdict(enum.Enum):
    """The gate's verdict on a judged entry whose record carries a digest
    (plan §3 rows 2-5): CHANGED mints, UNCHANGED keeps the stored version."""
    CHANGED = enum.auto()
    UNCHANGED = enum.auto()


def _cosine(u: np.ndarray, v: np.ndarray) -> float | None:
    """dot(u, v) / (‖u‖ ‖v‖) by hand: provider normalisation is a per-model
    config entry defaulting False.  None when it cannot be computed -- a zero
    norm or a non-finite value -- because a bare `sim < 0.90` would let NaN
    through in the wrong direction (§5.4 step 2)."""
    nu, nv = float(np.linalg.norm(u)), float(np.linalg.norm(v))
    if not (nu > 0.0 and nv > 0.0):
        return None
    sim = float(np.dot(u, v)) / (nu * nv)
    return sim if math.isfinite(sim) else None


async def _prefilter(task: InterpretationTask, e: Entry,
                     baseline: str, fresh: str) -> float | None:
    """The prefilter (§5.4 step 2): the cosine of the two embedding-document
    texts -- the baseline and the fresh interpretation, each under the
    entity's current statement, rendered by the ONE document-text authority
    -- or None when it is skipped or could not be computed.  A failed call
    disables it for the rest of the run; the caller that flips the flag is
    the one that reports it (§12 #5), so "skipped for the rest of the run"
    and "printed once" are one operation, whatever gates were already
    inside the failing call.  The embed machinery's own tracing is gated
    for the call: per judged entity it would count against Isabelle's
    editor_tracing_messages cap, whose overflow blocks the command."""
    if task.emb_store is None or task.run_state.prefilter_disabled:
        return None
    docs = [entity_document_text(SemanticRecord(EntityKind(e.kind), e.name, e.prop_str, t))
            for t in (baseline, fresh)]
    token = _embed_tracing_gated.set(True)
    try:
        async with asyncio.timeout(_PREFILTER_TIMEOUT_S):
            u, v = (await task.emb_store.emb_provider.embed(docs, role="document")).vectors
    except Exception as exc:
        _log.warning("prefilter: the embedding call failed; skipped for the rest "
                     "of the run", exc_info=True)
        if task.run_state.claim_prefilter_disable():
            # a bare TimeoutError (the timeout cuts the provider's retry
            # ladder before it can raise a message) has an empty str
            await _report(f"The embedding service did not respond: "
                          f"{str(exc) or type(exc).__name__}", warn=True)
        return None
    finally:
        _embed_tracing_gated.reset(token)
    return _cosine(u, v)


async def _judge(task: InterpretationTask, idx: int, baseline: str, fresh: str) -> bool:
    """The judge session (§5.4 step 3): one fresh session over the one pair,
    under a permit of `_JUDGE_SESSIONS` (D12).  True iff the judge said
    "same".  Every other outcome -- no verdict after the one extra ask, a
    `FatalAgentError`, any failure of the session -- reads as CHANGED,
    logged to the host only (D10); a cancellation propagates."""
    assert task.make_judge_driver is not None, "interpret_file hands the task its judge driver"
    judge = JudgeTask(task, idx, baseline, fresh)
    try:
        async with _JUDGE_SESSIONS:
            await _run_agent(lambda: task.make_judge_driver(judge), judge)  # type: ignore[misc]
    except Exception:
        _log.warning("judge: the session on %s failed; verdict CHANGED",
                     _label(judge.entries[0]), exc_info=True)
    finally:
        task.judge_cost = task.judge_cost.plus(judge.run_cost())
    return judge.verdict is True


def _write(task: InterpretationTask, idx: int, rec: 'SemanticRecord | None',
           verdict: _Verdict | None, text: str) -> bool:
    """Write one answered entry: `text`, the other wire fields and the gate
    fields in ONE transaction (plan §5.4 step 5, §3, §6.4), over `rec`, the
    record as stored when this gate read it, at the `verdict` reached on
    `text` -- so what is written and what was judged cannot drift.  Returns
    whether a version was minted.

    Two predicates, each keyed on the digest, never on the kind (a persistent
    constant, or a four-kind entry whose digest is NONE, has a tracked kind
    and no digest and must NOT be given a baseline): `judged` = the entry has
    a digest (§3 rows 1-5); `has_gate_fields` = digest or deps (false only for
    persistent entries and WIP collections / methods, which get None
    everywhere, D15)."""
    e = task.entries[idx]
    judged = e.semantic_digest is not None
    has_gate_fields = judged or bool(e.deps)
    with _note_on_failure(f"while writing the interpretation of {e.name}"), \
         Semantic_DB.gate_write() as w:
        if not judged:
            # theorem-alike (deps present): the stored version, else ε; never
            # a mint (I2).  Persistent, collection, method: None everywhere.
            version = ((rec.version if rec is not None and rec.version else w.counter_value())
                       if has_gate_fields else None)
            baseline, digest = None, None
        elif rec is None or rec.semantic_digest is None:
            # §3 row 1, a first write: ε, the text becomes the baseline
            version, baseline, digest = w.counter_value(), text, e.semantic_digest
        elif verdict is _Verdict.CHANGED:
            # §3 rows 2-5: a new version, the text becomes the new baseline
            version, baseline, digest = w.mint(), text, e.semantic_digest
        else:
            # UNCHANGED: the stored version and baseline stand (a version-less
            # record reads ε, the same reading as everywhere else)
            assert verdict is _Verdict.UNCHANGED, "a digest-bearing record needs a verdict"
            version = rec.version or w.counter_value()
            baseline, digest = rec.baseline_interpretation, e.semantic_digest
        deps = (e.deps or []) if has_gate_fields else None
        # The snapshot after this entity's own version: passed to a FRESH
        # evaluator over rec_cache, not read back from a fabricated record.
        ia = (_EffStar(task.rec_cache).eff_value(version, e.deps)  # type: ignore[arg-type]
              if has_gate_fields else None)
        written = w.put_interpretation(
            e.universal_key, kind=EntityKind(e.kind), name=e.name,
            expr=e.prop_str, interpretation=text,
            locale_provenance=e.locale_provenance,
            theory_constituents=e.theory_constituents,
            position=e.position, from_collection=e.from_collection,
            semantic_digest=digest, deps=deps, version=version,
            interpreted_at=ia, baseline_interpretation=baseline)
    task.rec_cache[e.universal_key] = written    # "rec_cache == store" for every later eff*
    task.state[idx] = _DONE
    return judged and verdict is _Verdict.CHANGED


def _propagate(task: InterpretationTask, idx: int) -> None:
    """Entry `idx` minted (§5.3.1): each of its theory-internal direct
    dependents is enrolled (not enrolled yet), left to its own coming write
    (queued, sent, gating -- that write recomputes eff* from `rec_cache`), or
    has its `interpreted_at` raised to the eff* that now includes the mint
    (done) -- a gate-field write, no mint, no re-interpretation, and nothing
    beyond it: a dependent's own dependents were handled at its own verdict."""
    for j in task.dependents[idx]:
        if task.state[j] == _NOT_ENROLLED:
            task.enqueue(j)
        elif task.state[j] == _DONE:
            ej = task.entries[j]
            r = task.rec_cache[ej.universal_key]
            assert r is not None, "done means written and put back into rec_cache"
            ia = _EffStar(task.rec_cache).eff_value(r.version or 0, r.deps)
            with _note_on_failure(f"while raising the interpreted_at snapshot of {ej.name}"), \
                 Semantic_DB.gate_write() as w:
                task.rec_cache[ej.universal_key] = w.update_gate_fields(
                    ej.universal_key, semantic_digest=r.semantic_digest, deps=r.deps,
                    version=r.version, interpreted_at=ia,
                    baseline_interpretation=r.baseline_interpretation)


async def _gate(task: InterpretationTask, idx: int) -> None:
    """The gate of one answered entry (plan §5.4), a task of `interpret_file`'s
    group: which §3 row applies, the prefilter, the judge, the one write,
    and the propagation of a mint.

    A gate writes only the text it judged, over the record it read: both are
    captured at the top of a round and, with no await between the test and
    the write, a round whose text a correction (D11) replaced meanwhile
    starts over on the newer text instead of writing.  Every extra round is
    paid for by one distinct correction, so the loop terminates.  The record
    cannot move under a round: only this entity's own gate writes it, and
    two gates of one entity never overlap (`_write` marks the entry done as
    its last statement and nothing awaits after it -- `_propagate`'s writes
    are synchronous -- so an answer that finds the entry done runs strictly
    after this gate)."""
    e = task.entries[idx]
    while True:
        rec = task.rec_cache[e.universal_key]       # the record as currently stored (§3's R)
        text = task.results[idx]
        assert text is not None
        verdict: _Verdict | None = None             # rows 1, theorem-alike, persistent: no verdict needed
        if e.semantic_digest is not None and rec is not None and rec.semantic_digest is not None:
            if rec.baseline_interpretation is None:
                verdict = _Verdict.CHANGED          # §3 row 2: a record from before the gate
            else:
                sim = await _prefilter(task, e, rec.baseline_interpretation, text)
                if sim is not None and sim < _GATE_SIMILARITY:
                    verdict = _Verdict.CHANGED      # §3 row 3
                    _log.info("gate: %s CHANGED by the prefilter (similarity %.3f)",
                              _label(e), sim)
                elif await _judge(task, idx, rec.baseline_interpretation, text):
                    verdict = _Verdict.UNCHANGED    # §3 row 4
                else:
                    verdict = _Verdict.CHANGED      # §3 row 5
        if task.results[idx] != text:               # a correction landed mid-gate:
            continue                                # judge the new text; nothing written, nothing minted
        minted = _write(task, idx, rec, verdict, text)
        break
    if minted:
        _propagate(task, idx)


def _first_failure(eg: BaseExceptionGroup) -> BaseException:
    """The ONE exception `interpret_file` raises for what the gate task group
    collected (plan §5.4 failures): the first leaf, with the others logged.
    A group would reach the user with its gutter, and ML's one-line
    user-error contract (`USER_ERROR_MARKER`, extract_user_error) needs the
    bare exception.  Cancellations are not failures; a group of nothing else
    is returned as it is.  Returned, not raised: raising inside the caller's
    `except` block would overwrite the leaf's own `__context__` with the
    group."""
    def leaves(exc: BaseException) -> list[BaseException]:
        if isinstance(exc, BaseExceptionGroup):
            return [leaf for sub in exc.exceptions for leaf in leaves(sub)]
        return [exc]

    failures = [x for x in leaves(eg) if not isinstance(x, asyncio.CancelledError)]
    if not failures:
        return eg
    for extra in failures[1:]:
        _log.error("interpret_file: a further failure in the same run",
                   exc_info=extra)
    return failures[0]


# --- the queue loop (plan §5.3, §15.4) ---

async def _retry_unanswered(driver: InterpretationDriver, task: AgentTask) -> None:
    """Ask again for the entries of the batch in flight the agent left
    unanswered, until none is left or the loop stalls.

    Stopping RAISES rather than leaving the entries None: an entry with no
    interpretation is a failure, and swallowing it here is what used to let a
    whole cone be marked interpreted with nothing in it.  See the completeness
    invariant on interpret_file."""
    prev_missing: int | None = None
    stall = 0
    while True:
        chunk = task.unanswered_in_batch()
        if not chunk:
            return
        # Stop if the retry loop makes no progress: a chunk the agent cannot
        # (or will not) answer — refusal, an undetected request error — must
        # not spin forever.
        if prev_missing is not None and len(chunk) >= prev_missing:
            stall += 1
            if stall >= task.max_stalled_retries:
                missing_names = [task.entries[i].name for i in task.unanswered()]
                _log.error("agent: %d entries unanswered after %d stalled "
                           "retry rounds: %s", len(missing_names), stall, missing_names)
                raise FatalAgentError(task.unanswered_failure(missing_names))
        else:
            stall = 0
        prev_missing = len(chunk)
        line = task.retry_report(len(task.unanswered()), stall + 1)
        if line:
            await _report(line, warn=True)
        await driver.run_turn(task.retry_prompt(chunk))


def _stop_if_cancelled() -> None:
    """Called first in every recovering arm of `_run_agent`: a cancellation
    that a driver's teardown replaced with an ordinary exception (a cost
    flush on the broken store, the transport's __aexit__) must not be
    recycled -- the gate task group is tearing this session down, and a
    recycled session would have every gate refused and park for ever.  A bare
    `raise` re-raises the exception the calling arm is handling."""
    t = asyncio.current_task()
    if t is not None and t.cancelling():
        raise


async def _run_agent(make_driver: Callable[[], InterpretationDriver],
                     task: AgentTask) -> None:
    """Drive agent sessions over `task`'s queue until it is empty and every
    gate has finished (plan §5.3): one turn per batch, the batch's unanswered
    entries retried, the session kept open while a gate may still enrol.

    `make_driver` builds a FRESH driver per attempt — every recycle path below
    re-enters through it, which is what discards a poisoned conversation; the
    task's queue and states survive, so a recycle continues where the session
    stopped (its unanswered entries lead the next batch).  The two throttle
    arms never give up and never consume the recycle budget; their sleeps are
    jittered so concurrent sessions do not retry in lockstep."""
    recycles = 0        # consumed by the two hard-failure arms only
    throttled = 0       # consecutive rate-limit hits; reset by a completed turn
    while True:
        try:
            async with make_driver() as driver:
                task.session_started()
                while True:
                    batch = task.next_batch()
                    if not batch:
                        if not task.gates_running:
                            break
                        await task.wait_for_progress()
                        continue
                    _log.info("agent: sending %d entries (%d gates running)",
                              len(batch), task.gates_running)
                    await driver.run_turn(task.build_prompt(batch))
                    throttled = 0
                    await _retry_unanswered(driver, task)
            _log.info("total usage: input=%d cache_write=%d cache_read=%d output=%d tokens, cost=$%.4f",
                      task.run_input_tokens, task.run_cache_creation_tokens,
                      task.run_cache_read_tokens, task.run_output_tokens, task.run_cost_usd)
            return
        except ReachLimitError:
            _stop_if_cancelled()
            delay = 1200 + random.uniform(-60, 60)
            _log.info("agent: reached usage limit, waiting %.0fs to retry", delay)
            await asyncio.sleep(delay)
        except RateLimitError:
            _stop_if_cancelled()
            delay = min(2 * 2 ** throttled, 60) * random.uniform(0.5, 1.5)
            throttled += 1
            _log.info("agent: API rate limit, waiting %.1fs to retry", delay)
            await asyncio.sleep(delay)
        except PoisonedSessionError:
            # The conversation is irrecoverably rejected by the API (e.g. a lone
            # surrogate pinned in the transcript).  Recycle with a FRESH driver
            # (it starts a new session, so the bad history is dropped) and
            # continue with the still-unanswered entries.
            _stop_if_cancelled()
            if recycles >= _MAX_AGENT_RECYCLES:
                # Do NOT return here: returning would hand back a task with
                # unanswered entries and no error, which interpret_file would
                # report as success.
                raise FatalAgentError(None,
                    f"poisoned session (API 400) persisted after {recycles} client recycles")
            recycles += 1
            _log.warning("agent: poisoned session (API 400); recycling client "
                         "(recycle %d/%d)", recycles, _MAX_AGENT_RECYCLES)
        except FatalAgentError:
            # Authentication, billing, a malformed request, unanswered entries, or an
            # unrecognised agent error.  Recycling cannot change any of these outcomes;
            # it would only burn 8 x 2 s and bury the cause under the last failure.
            # A driver raises this itself for its own deterministic failures (e.g. a
            # missing Claude Code CLI), which is why no driver-specific exception
            # reaches this level.
            raise
        except Exception:
            # An unexpected transport/SDK failure can escape a driver's run_turn with
            # no preceding error message, bypassing the loops above and killing the
            # whole file.  Recycle a bounded number of times, then re-raise so
            # genuine bugs still surface.  TransientAgentError lands here too.
            _stop_if_cancelled()
            if recycles >= _MAX_AGENT_RECYCLES:
                _log.exception("agent: unexpected failure persisted after %d "
                               "recycles; re-raising", recycles)
                raise
            recycles += 1
            _log.exception("agent: unexpected failure; recycling client "
                           "(recycle %d/%d)", recycles, _MAX_AGENT_RECYCLES)
            await asyncio.sleep(2)


# --- Public API ---

async def interpret_file(
    connection: Connection,
    file_path: str,
    theory_longname: str,
    theory_key: universal_key,
    entries: list[Entry],
    driver: str = "",
    dry_run: bool = False,
) -> InterpretationResult | int:
    """Interpret entities from an Isabelle theory file.

    Looks up cached interpretations in LMDB. For uncached entries, launches
    an agent to generate plain-English translations.

    Args:
        connection: Active Isabelle RPC connection.
        file_path: Path to the theory source file.
        theory_longname: Fully qualified theory name (e.g. "HOL.List").
        theory_key: Universal key for the theory (used for cost tracking).
        entries: Entities to interpret, each with kind, name, prop_str,
            position, and universal_key.
        driver: The Isabelle side's `"<Driver>[.<model>]"` choice, "" if it made
            none; `_resolve_driver` decides what actually runs.
        dry_run: Mode 4 (CHECK_OUTDATE_PLAN.md §8): stop right after the cache
            filter and return how many entries an ordinary run would send to
            the LLM.  No LLM runs, no cost is written, and the theory is never
            marked interpreted; the count comes from the same filter an
            ordinary run applies, so it cannot drift from the actual work.

    Returns:
        InterpretationResult with per-entry interpretations, pretty-prints,
        and cost summaries (current run + cumulative); under ``dry_run``, the
        number of entries that still need interpretation.
    """
    n = len(entries)

    # Inherit RPC server's logging configuration (idempotent, no race).  The
    # driver package gets it too: its loggers are NOT children of this module's,
    # so without this the driver's lines (tool allowed/denied, model output,
    # per-turn usage) would silently vanish from the host log.
    for lg in (_log, logging.getLogger(f"{__package__}.interpretation_driver")):
        if not lg.handlers and connection.server.logger.handlers:
            for h in connection.server.logger.handlers:
                lg.addHandler(h)
            lg.setLevel(connection.server.logger.level)
    _log.info("interpret_file%s: %s (%s), %d entries",
              " (dry run)" if dry_run else "", theory_longname, file_path, n)
    run_state = current_run_state()

    # --- the scan (plan §5.2, §15.8) ---
    # Nothing minted, no gate field written, no counter put.  Per entry: the
    # stored record serves (filled into `results`), or the entry is a SEED of
    # the work queue -- uncached, locally stale (digest changed, never
    # digested, dep keys moved) or stale under eff* over the store.  A
    # dependent of a seed is NOT enrolled here: it is enrolled the moment the
    # seed's verdict is CHANGED (§5.3.1); until then the seed's record, which
    # still looks fresh, is rightly a wall.
    results: list[str | None] = [None] * n
    recs = Semantic_DB.get_many([e.universal_key for e in entries])
    rec_cache: 'dict[bytes, SemanticRecord | None]' = {
        e.universal_key: r for e, r in zip(entries, recs)}
    # ε for a version-less record (§9 "ε epoch"): read, never put -- the gate
    # takes its own ε from its own transaction.
    epsilon = Semantic_DB.counter_snapshot()
    eff = _EffStar(rec_cache)          # one instance: nothing changes during a scan
    seeds: list[int] = []
    for i, (e, rec) in enumerate(zip(entries, recs)):
        has_gate_fields = e.semantic_digest is not None or bool(e.deps)
        cached = rec is not None and rec.interpretation is not None
        stale = False
        if cached and has_gate_fields:
            assert rec is not None
            if e.semantic_digest is not None and (
                    rec.semantic_digest is None or
                    rec.semantic_digest != e.semantic_digest):
                # Changed -- or a record that never had a digest: its text was
                # written for content nobody can reconstruct, stale by §4.4.
                stale = True
            elif rec.deps is not None and set(rec.deps) != set(e.deps or []):
                # Unified dep criterion (§4.3): every stored edge is compared,
                # by value, against the target's CURRENT universal key as the
                # scan just resolved it.  With the digest equal, the dep NAME
                # set is unchanged (invariant I3), so a set difference here
                # means some target's KEY moved -- typically a WIP<->persistent
                # flip re-keying the target.  Without this, the version walk
                # would query the OLD key forever and read silence: the dead
                # edge.  Re-interpretation stores the current uks (the gate's
                # write takes deps off the wire entry), which heals the edge.
                stale = True
            else:
                stale = (eff.eff_value(rec.version or epsilon, e.deps)
                         > (rec.interpreted_at or 0))
        if cached and not stale:
            assert rec is not None
            results[i] = rec.interpretation
        else:
            seeds.append(i)
    not_enrolled = [i for i in range(n) if results[i] is not None]   # filled from the store

    # The theory-internal dependency graph, reversed: dependents[j] lists the
    # entries whose deps name entry j; a CHANGED verdict on j enrols them
    # (§5.3.1).  Nothing outside the theory is walked.
    uk_to_idx = {e.universal_key: i for i, e in enumerate(entries)}
    dependents: list[list[int]] = [[] for _ in entries]
    for i, e in enumerate(entries):
        for d in e.deps or []:
            j = uk_to_idx.get(d)
            # A constant's dep list names its own key (semantic_digest.ML's
            # deps_of_term (Const ...)); the self edge carries no signal --
            # the entity's own version is already eff*'s floor -- and following
            # it would make every CHANGED verdict re-write its own record.
            if j is not None and j != i:
                dependents[j].append(i)

    if dry_run:
        # A LOWER BOUND on the live run's work: this theory's changed /
        # uncached entities.  Their dependents are not counted -- whether a
        # change propagates is decided by the semantic change gate after
        # re-interpretation, which a dry run never runs.  Exact at zero.
        #
        # Mode 4 returns here: no driver resolution (nothing will run), no
        # cost write, no report into the user's buffer (the caller aggregates
        # the per-theory counts and does the talking), and no
        # InterpretationTask is ever created -- so nothing marks the theory.
        # The statement refresh is its only write, so an `expr`-only change
        # is refreshed even when the cone quotes zero (§5.3.2).
        _refresh_statements(entries, rec_cache, not_enrolled)
        _log.info("interpret_file (dry run): %s -- at least %d of %d entries need "
                  "interpretation", theory_longname, len(seeds), n)
        return len(seeds)

    # Resolve before any LLM work: a misspelt driver name is a configuration
    # error and should say so immediately rather than mid-run.
    driver_name, driver_cls, model = _resolve_driver_and_model(driver)

    # Build Unicode pretty-prints for all entries
    pretty_prints = [_pretty_print_entry(e) for e in entries]
    n_cached = n - len(seeds)
    # Say what is about to happen in words, not internal vocabulary: "entries/cached/to
    # interpret" means nothing to someone watching from a theory buffer.
    if not seeds:
        await _report(f"{theory_longname}: all {n} entities are already interpreted "
                      f"in the semantic database and up to date, nothing to ask.")
    elif n_cached:
        await _report(f"Interpreting {theory_longname}: found {n} entities to interpret; "
                      f"{n_cached} are already interpreted and up to date, asking the "
                      f"LLM for the remaining {len(seeds)} (new or outdated).")
    else:
        await _report(f"Interpreting {theory_longname}: found {n} entities to interpret; "
                      f"none are in the semantic database yet, asking the LLM for all {n}.")
    current_cost = cumulative_cost = _NO_COST

    if seeds:
        from .hover import mk_definition_tool, mk_hover_tool
        from .semantics import mk_query_by_name_tool
        from .theory_structure import mk_unicode_file

        unicode_file_path = mk_unicode_file(file_path)

        # The prefilter's embedding store, resolved on THIS connection (the
        # user's context governs the model, D5) and only for this run's use.
        # None -- unconfigured (the startup check said so, or the resolution
        # raises here), or the service already failed this run -- means the
        # judge decides alone (D2); the host log keeps the reason.
        emb_store: 'Semantic_Vector_Store | None' = None
        if not run_state.prefilter_disabled:
            try:
                emb_store = await connection.semantic_vector_store()   # type: ignore[attr-defined]
            except Exception:
                _log.warning("interpret_file: no embedding store for the prefilter; "
                             "the judge decides alone", exc_info=True)

        def make_judge_driver(judge: JudgeTask) -> InterpretationDriver:
            return make_interpretation_driver(
                driver_name,
                model=model,
                system_prompt=_JUDGE_SYSTEM_PROMPT,
                tools=[mk_verdict_tool(judge)],
                task=judge,
                on_context_reset=lambda: None,
                cli_tools=False,
            )

        # The task spans ALL of the theory's entries: a dependent that is not
        # a seed must be enrollable later, so it needs an index, a state and a
        # result slot.  Non-seeds start _NOT_ENROLLED with their stored text;
        # seeds are enqueued in wire order.
        with InterpretationTask(
            connection, file_path, theory_longname, theory_key, entries,
            driver=driver_name, model=model,
            unicode_file_path=unicode_file_path,
            rec_cache=rec_cache, dependents=dependents,
            emb_store=emb_store, run_state=run_state,
            make_judge_driver=make_judge_driver,
        ) as task:
            for i in not_enrolled:
                task.results[i] = results[i]
            for i in seeds:
                task.enqueue(i)

            # The desugar tool annotates each constant it shows with its English
            # description, and skips a constant it has already annotated in this
            # conversation.  Once the backend compacts the conversation those
            # annotations are gone from the agent's context while this set still
            # says "told them" — so the driver clears it just before compacting
            # (`on_context_reset`), and the agent never sees an unexplained
            # constant.  It is a bare local reachable from neither `task` nor the
            # tool objects, hence its own channel into the driver.
            seen_constants: set[str] = set()
            # The names the agent may not look up: every ENROLLED entry's,
            # read live -- an entity enrolled by a later CHANGED verdict is
            # refused from that moment on, or the agent could be handed the
            # stored text of the very entity it is re-interpreting (§15.8).
            query_by_name_tool = mk_query_by_name_tool(
                connection, task.enrolled_names, file_path=file_path)
            definition_tool = mk_definition_tool(connection, unicode=True)
            hover_tool = mk_hover_tool(connection, unicode=True)
            desugar_tool = mk_desugar_and_explain_tool(
                connection, file_path=file_path, seen_constants=seen_constants,
                dedup=driver_cls.REPORTS_CONTEXT_RESET)
            tools = [query_by_name_tool, definition_tool, hover_tool,
                     desugar_tool, mk_answer_tool(task)]

            def make_driver() -> InterpretationDriver:
                return make_interpretation_driver(
                    driver_name,
                    model=model,
                    system_prompt=_SYSTEM_PROMPT,
                    tools=tools,
                    task=task,
                    on_context_reset=seen_constants.clear,
                )

            _log.info("interpret_file: starting %s agent on %s with %d entries",
                      driver_name, model or "the backend's default model",
                      task.enrolled())
            # The gates are tasks of this group, so interpret_file returns only
            # after every one of them has joined -- which is what makes every
            # write of this theory visible to the descendants schedule_dag
            # starts afterwards (plan §5.3 termination).  A failure is raised
            # OUTSIDE the except block, so the leaf keeps its own __context__
            # instead of the group (plan §5.4 failures).
            failure: BaseException | None = None
            try:
                async with asyncio.TaskGroup() as tg:
                    task.task_group = tg
                    await _run_agent(make_driver, task)
            except ExceptionGroup as eg:
                failure = _first_failure(eg)
            if failure is not None:
                raise failure
            _log.info("interpret_file: agent finished, %d/%d interpreted",
                      task.n_interpreted(), task.enrolled())
            # COMPLETENESS INVARIANT: interpret_file either gives every entry an
            # interpretation or raises; the returned `interpretations` never
            # contains None.  Isabelle relies on this -- Semantic_Store.interpret'
            # discards the list entirely, and interpret_cone marks a theory
            # interpreted as soon as interpret' RETURNS.  Were a partial result to
            # get back, the theory would be recorded as done with entities missing,
            # and only `force` could ever redo it.
            #
            # The retry loop already raises when it stalls; this is the backstop
            # that keeps the invariant true no matter how the loop is later
            # restructured.  "Answered" is not "durable" (D14): the certificate
            # that licenses mark_interpreted is that every gate joined without
            # raising (the group above) AND every entry is written or was in
            # the store to begin with -- the state clause asserted here.
            # ANYONE RELAXING THIS must also revisit semantic_store.ML's
            # `val (_, _, current, cumulative)` and interpret_cone's
            # unconditional mark_interpreted.
            missing = [i for i, sem in enumerate(task.results) if sem is None]
            if missing:
                raise FatalAgentError(task.unanswered_failure(
                    [task.entries[i].name for i in missing]))
            assert all(s in (_DONE, _NOT_ENROLLED) for s in task.state), \
                "every gate joined, yet an answered entry was not written"
            # Cost is flushed per turn by the driver, so this is normally
            # a no-op flush; it still returns the up-to-date cumulative totals.
            cum = task.write_cost()
            # current_cost = cost of THIS run: the interpretation session's
            # run-level accumulator (write_cost resets total_*, never run_*)
            # plus the judge sessions' (§15.9).
            current_cost = task.run_cost().plus(task.judge_cost)
            cumulative_cost = CostSummary(*cum)
            await _report(f"{theory_longname}: done -- {task.n_interpreted()} entities "
                          f"interpreted, cost ${current_cost.cost_usd:.4f}.")

            results = list(task.results)     # 1:1 with `entries`; the store was written by the gates
    else:
        # All cached — read cumulative cost from DB
        with InterpretationTask(
            connection, file_path, theory_longname, theory_key,
            entries=[], driver=driver_name, model=model,
        ) as task:
            cumulative_cost = CostSummary(*task.historical_cost())

    # The statement refresh (§5.3.2), on every live path -- a theory with no
    # seed included.  The scan's not-enrolled list is the right one: every
    # entry that left _NOT_ENROLLED was written by its gate with `expr =
    # e.prop_str` and put back into rec_cache, so the guard is a no-op for it.
    _refresh_statements(entries, rec_cache, not_enrolled)
    return InterpretationResult(
        results,
        pretty_prints,
        current_cost,
        cumulative_cost,
    )


# --- RPC shims ---

def _entries_of_wire(raw_entries: Any) -> list[Entry]:
    """Decode the wire entries of Semantic_Store.interpret_file / its dry-run
    twin (one `pack_arg` on the ML side, so one decoder here)."""
    from Isabelle_RPC_Host.universal_key import THM_RULE_KINDS
    for e in raw_entries:
        if len(e) != 11:
            raise RuntimeError(
                f"interpret_file wire entry has {len(e)} components, expected 11:"
                " the Isabelle/ML and Python halves are from different releases."
                " Install matching versions (the conda package ships both"
                " together; PyPI ships the Python half alone).")
    return [
        Entry(
            kind=kind,
            name=pretty_unicode(name),
            prop_str=pretty_unicode(prop),
            # The file is a filesystem path, NOT Isabelle source text: it does
            # not go through pretty_unicode, which would rewrite a literal
            # \<...> inside a path into a Unicode character.
            position=(tuple(position) if position is not None else None),
            universal_key=bytes(uk),
            prompt_extra=pretty_unicode(hint),
            locale_provenance=(Provenance(
                template_uk=bytes(prov[0]) if prov[0] is not None else None,
                locale_uk=bytes(prov[1]) if prov[1] is not None else None,
                qualifier=prov[2],
            ) if prov is not None else None),
            theory_constituents=(
                [(n, bytes(h)) for n, h in consts]
                if EntityKind(kind) in THM_RULE_KINDS else None),
            # like `name` where present, guarded like `position` when nil: the
            # field is nil on every non-member entry and pretty_unicode(None)
            # raises.  Where present it MUST go through, or ML-written and
            # pass-written records would hold two spellings of one collection
            # (collections with symbols in their names do occur).
            from_collection=(pretty_unicode(from_coll)
                            if from_coll is not None else None),
            semantic_digest=bytes(digest) if digest is not None else None,
            deps=[bytes(u) for u in deps],
        )
        for kind, name, prop, position, uk, hint, prov, consts, from_coll,
            digest, deps
        in raw_entries
    ]


@isabelle_remote_procedure("Semantic_Store.interpret_file")
async def _interpret_file(arg: Any, connection: Connection) -> InterpretationResult:
    (file_path, theory_longname, theory_key, driver, raw_entries) = arg
    result = await interpret_file(
        connection, file_path, theory_longname, bytes(theory_key),
        _entries_of_wire(raw_entries), driver
    )
    assert isinstance(result, InterpretationResult)  # not a dry run
    return result


@isabelle_remote_procedure("Semantic_Store.interpret_file_dry_run")
async def _interpret_file_dry_run(arg: Any, connection: Connection) -> int:
    """Mode 4 (CHECK_OUTDATE_PLAN.md §8): count, over the same wire payload an
    ordinary run sends, how many entries still need interpretation.  The driver
    field arrives as "" and is never read -- nothing runs on this path."""
    (file_path, theory_longname, theory_key, driver, raw_entries) = arg
    count = await interpret_file(
        connection, file_path, theory_longname, bytes(theory_key),
        _entries_of_wire(raw_entries), driver, dry_run=True
    )
    assert isinstance(count, int)  # the dry-run branch returns the count
    return count

