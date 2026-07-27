"""Semantic interpretation of Isabelle entities, driven by an LLM agent.

Driver-agnostic core: the batching, the missing-entry retry loop, the failure
classes and the completeness invariant live here; which agent backend actually
runs a prompt is the `interpretation_driver` subpackage's business.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import re
from collections.abc import Callable, Iterable
from typing import Any, NamedTuple

from Isabelle_RPC_Host import Connection, isabelle_remote_procedure
from Isabelle_RPC_Host.universal_key import EntityKind, universal_key
from Isabelle_RPC_Host.unicode import pretty_unicode
from claude_agent_sdk import tool

from .base import ToolCall_ret, mk_ret as _mk_ret
from .desugar import mk_desugar_and_explain_tool
from .interpretation_driver import (
    InterpretationDriver,
    available_interpretation_drivers,
    make_interpretation_driver,
    resolve_interpretation_driver_class,
)
from .semantics import Provenance, Semantic_DB, SemanticRecord, unpack_thy_status

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

# --- Context-local state ---

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


def _label(e: Entry) -> str:
    """The agent-facing addressing label for an entry: kind-title + name.

    This is the ONLY handle the agent has to address an entry (it echoes
    ``{type, name}`` back through the ``answer`` tool).  It must be IDENTICAL
    everywhere it is formed — the prompt the agent reads (`format_entries` /
    `_pretty_print_entry`), the `results` key, and the answer-routing map — so
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
    line_number: int     # source line (-1 if unavailable)
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


class CostSummary(NamedTuple):
    """Token usage and dollar cost for an interpretation run."""
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_tokens: int
    cost_usd: float


class InterpretationResult(NamedTuple):
    """Result of interpreting a theory file."""
    interpretations: list[str | None]   # per-entry semantic interpretation (None if unanswered)
    pretty_prints: list[str]            # per-entry Unicode pretty-print
    current_cost: CostSummary           # cost incurred in this call
    cumulative_cost: CostSummary        # total cost including historical


class InterpretationTask:
    def __init__(self, connection: Connection, file_path: str,
                 theory_longname: str, theory_key: universal_key,
                 entries: list[Entry], driver: str = _DEFAULT_DRIVER,
                 model: str = ""):
        self.connection = connection
        self.file_path = file_path
        self.theory_longname = theory_longname
        self.theory_key = theory_key
        self.entries = entries
        # Which backend and model produced these interpretations, both already
        # resolved (no empty halves).  write_cost records them, so a theory's
        # provenance stays readable after the config that chose them has changed.
        self.driver = driver
        self.model = model
        # results / _keys / _label_to_idx are strictly 1:1 with `entries`, in
        # order.  Because the agent addresses an entry only by its label (see
        # `_label` and `_answer_tool`), two entries sharing a label are mutually
        # un-addressable; a label-keyed dict comprehension would SILENTLY
        # collapse them, desyncing _keys vs entries and mis-routing write_answer
        # (the "name != content" LMDB corruption).  Build it with a loop that
        # RAISES on the first duplicate instead — the ML side
        # (Semantic_Store, (entity-kind, name) assert) guarantees uniqueness, so
        # this only ever fires on a genuine regression.
        self.results: dict[str, str | None] = {}
        self._label_to_idx: dict[str, int] = {}
        for i, e in enumerate(entries):
            key = _label(e)
            if key in self.results:
                j = self._label_to_idx[key]
                raise ValueError(
                    f"duplicate interpretation label {key!r} at entries {j} and {i} "
                    f"(uks {bytes(entries[j].universal_key).hex()} and "
                    f"{bytes(e.universal_key).hex()}); (kind,name) labels must be "
                    f"unique to be addressable by the agent")
            self.results[key] = None
            self._label_to_idx[key] = i
        self._keys = list(self.results.keys())
        self.batches: list[tuple[str, range]] = []
        self.current_batch: int = 0
        self.batch_range: range = range(0)
        # `total_*` is the pending delta not yet flushed to LMDB; write_cost()
        # accumulates it into the theory record and resets it to 0.  Cost is
        # flushed per agent round (see _accumulate_usage), mirroring how answers
        # are written per-answer (write_answer) — so an interrupt (the parallel
        # scheduler's by-design hard-crash) cannot drop cost for answers that
        # are already cached.
        self.total_input_tokens = 0
        self.total_cache_creation_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        # `run_*` is the cumulative cost of THIS interpret_file invocation; it is
        # never reset by write_cost(), so it survives the per-round flushes and
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

    def __enter__(self) -> InterpretationTask:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def write_answer(self, task_idx: int, sem: str) -> None:
        """Write a single answer to the LMDB store."""
        entry = self.entries[task_idx]
        Semantic_DB[entry.universal_key] = SemanticRecord(
            EntityKind(entry.kind), entry.name, entry.prop_str, sem,
            entry.locale_provenance, entry.theory_constituents)

    def historical_cost(self) -> tuple[int, int, int, int, float]:
        """Read cumulative cost from LMDB (without modifying it).  A layered
        read: a system-resident status counts, a tombstoned one reads as zero."""
        raw = Semantic_DB._get_raw(self.theory_key)
        if not raw:
            return (0, 0, 0, 0, 0.0)
        prev = unpack_thy_status(raw)
        return (prev.get(b"input_tokens", 0),
                prev.get(b"cache_creation_tokens", 0),
                prev.get(b"cache_read_tokens", 0),
                prev.get(b"output_tokens", 0),
                prev.get(b"cost_usd", 0.0))

    def write_cost(self) -> tuple[int, int, int, int, float]:
        """Accumulate cost into the LMDB store. Returns updated cumulative totals.

        Read-modify-write: copy-up-then-modify (plan §3.1).  The previous status
        is read through the layers (user first, tombstone = start fresh, then
        system), the updated one lands in the user env with every untouched
        field carried forward -- so system-layer cost/tokens accumulate onward
        and ``finished`` is never defaulted to False over a layered True."""
        import msgpack
        env = Semantic_DB._ensure_env()
        with env.begin(write=True) as txn:
            raw = txn.get(self.theory_key)
            if raw is not None and len(raw) == 0:
                raw = None                                # tombstoned: start fresh
            elif raw is None:
                raw = Semantic_DB._system_get(self.theory_key)   # copy-up
            prev = unpack_thy_status(raw) if raw else {}
            total = (prev.get(b"input_tokens", 0) + self.total_input_tokens,
                     prev.get(b"cache_creation_tokens", 0) + self.total_cache_creation_tokens,
                     prev.get(b"cache_read_tokens", 0) + self.total_cache_read_tokens,
                     prev.get(b"output_tokens", 0) + self.total_output_tokens,
                     prev.get(b"cost_usd", 0.0) + self.total_cost_usd)
            data = dict(prev)      # preserve every field this write does not touch
            data.update({
                b"input_tokens": total[0],
                b"cache_creation_tokens": total[1],
                b"cache_read_tokens": total[2],
                b"output_tokens": total[3],
                b"cost_usd": total[4],
                b"finished": prev.get(b"finished", False),
                b"model": self.model,
                # New field; readers use .get, so older records (no b"driver")
                # need no migration -- they all predate any driver but ClaudeCode.
                b"driver": self.driver,
            })
            packed: bytes = msgpack.packb(data)  # type: ignore[assignment]
            txn.put(self.theory_key, packed)
        self.total_input_tokens = 0
        self.total_cache_creation_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        return total

    def advance_batch(self) -> str | None:
        self.current_batch += 1
        if self.current_batch >= len(self.batches):
            return None
        prompt, self.batch_range = self.batches[self.current_batch]
        return prompt

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

    def build_prompt(self, file_path: str, theory_longname: str, indices: range | None = None) -> str:
        if indices is None:
            indices = range(len(self.entries))
        entries_text = self.format_entries(indices)

        if indices.start != 0:
            return (
                f'Continue with the following entities from Isabelle theory "{theory_longname}" (location: {file_path}).\n\n'
                f"Entries:\n{entries_text}\n\n"
                f"Submit translations via `mcp__isabelle_semantics__answer`."
            )

        return (
            f"Load the skills `isabelle-intro-elim-rules`, `isabelle-datatype`, and `isabelle-record`.\n"
            f'Informalize the following entities from Isabelle theory "{theory_longname}" (location: {file_path}).\n\n'
            f"Entries:\n{entries_text}\n\n"
            f"Submit translations via `mcp__isabelle_semantics__answer`."
        )

_local_task: contextvars.ContextVar[InterpretationTask] = contextvars.ContextVar('_local_task')


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


@tool(
    "answer",
    "Submit English translations for one or more of the listed entries. "
    "Each translation should be a concise plain-English description of what the entity defines or asserts. "
    "You may also resubmit an entry to correct a previous answer. "
    "To see the remaining unanswered entries in the current batch, call this tool with an empty list [].",
    input_schema=_answer_schema,
)
async def _answer_tool(args: dict[str, Any]) -> ToolCall_ret:
    task = _local_task.get()
    interpretations = args["interpretations"]
    errors = []
    count = 0
    for item in interpretations:
        key = f"{item['type']} {item['name']}"
        if key not in task.results:
            errors.append(f"Unknown entry: {key!r}")
            continue
        # Strip lone UTF-16 surrogates the model occasionally emits mid math-
        # alphanumeric glyph (e.g. a bare U+D835 with no low half).  They crash
        # msgpack's strict-UTF-8 packb in write_answer (semantics.py) — so the
        # answer would be silently lost on exactly the entry that glitched — and,
        # left in the conversation, make every subsequent API request fail with
        # 400 "no low surrogate in string", wedging the whole file.
        trans = re.sub(r"[\ud800-\udfff]", "", item["translation"])
        task.results[key] = trans
        # Address by the precomputed label->entry-index map (O(1), and indexes
        # the FULL `entries` list correctly).  The old `_keys.index(key)` indexed
        # the deduped key list against the full entries list — the misalignment
        # that wrote translations onto neighbouring entries' universal_keys.
        task.write_answer(task._label_to_idx[key], trans)
        _log.info("answer: %s = %s", key, trans)
        count += 1
    batch_remaining = sum(1 for i in task.batch_range if task.results[task._keys[i]] is None)
    cs = "" if count == 1 else "s"
    total_answered = sum(1 for v in task.results.values() if v is not None)
    _log.info("answer: submitted %d, batch_remaining %d, %d/%d done",
               count, batch_remaining, total_answered, len(task.results))
    # The only fine-grained sign of life during a long theory.  Always name the theory:
    # several run concurrently, so an unqualified "20 of 244" would be unattributable.
    await _report(f"{task.theory_longname}: "
                  f"{total_answered} of {len(task.results)} done.")
    if batch_remaining == 0:
        next_prompt = task.advance_batch()
        if next_prompt is None:
            msg = "All done! If you noticed any mistakes in your earlier translations, correct them now using `mcp__isabelle_semantics__answer`. Otherwise, stop immediately without any further output."
        else:
            msg = f"Good job! You can resubmit corrections later using the `mcp__isabelle_semantics__answer` tool if needed.\n\n{next_prompt}"
    else:
        remaining_indices = [i for i in task.batch_range if task.results[task._keys[i]] is None]
        remaining_text = task.format_entries(remaining_indices)
        msg = (f"Answered {count} translation{cs}, remaining {batch_remaining} in this batch.\n\n"
               f"Unanswered entries:\n{remaining_text}\n"
               f"In file: {task.file_path}\n\n"
               f"Submit translations via `mcp__isabelle_semantics__answer`.")
    if errors:
        msg += "\nErrors:\n" + "\n".join(errors)
    return _mk_ret(msg)


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


async def _run_agent(make_driver: Callable[[], InterpretationDriver],
                     depth: int = 0) -> None:
    """Drive one agent session to completion: batch 0, then retries until every
    entry is answered.

    `make_driver` builds a FRESH driver per attempt — every recycle path below
    re-enters through it, which is what discards a poisoned conversation."""
    task = _local_task.get()
    first_prompt, task.batch_range = task.batches[0]
    try:
        async with make_driver() as driver:
            _log.info("agent: starting batch 0 (%d–%d)",
                    task.batch_range.start, task.batch_range.stop - 1)
            await driver.run_turn(first_prompt)
            # Retry any globally missing entries.  Re-send the full entry text
            # (line, kind, name, proposition) via format_entries, NOT bare names:
            # after context compaction the original batch prompts are gone, and
            # for facts generated by locale interpretations the proposition is
            # unrecoverable from the source file — a names-only list forces the
            # agent to answer from memory, inviting mispaired translations.
            # Retries go in _BATCH_SIZE chunks: a pathological run can leave
            # hundreds of entries unanswered, and a single message carrying all
            # their propositions + provenance hints would dwarf the normal
            # batch prompts and immediately re-trigger compaction.
            prev_missing: int | None = None
            stall = 0
            while True:
                missing_idx = [i for i, k in enumerate(task._keys)
                               if task.results[k] is None]
                if not missing_idx:
                    break
                # Stop if the retry loop makes no progress: a chunk the agent cannot
                # (or will not) answer — refusal, an undetected request error — must
                # not spin forever.  Stopping RAISES rather than leaving the entries
                # None: an entry with no interpretation is a failure, and swallowing
                # it here is what used to let a whole cone be marked interpreted with
                # nothing in it.  See the completeness invariant on interpret_file.
                if prev_missing is not None and len(missing_idx) >= prev_missing:
                    stall += 1
                    if stall >= _MAX_STALLED_RETRIES:
                        missing_names = [task.entries[i].name for i in missing_idx]
                        _log.error("agent: %d entries unanswered after %d stalled "
                                   "retry rounds: %s", len(missing_idx),
                                   stall, missing_names)
                        raise FatalAgentError(_msg_unanswered(
                            task.theory_longname, missing_names, len(task.entries)))
                else:
                    stall = 0
                prev_missing = len(missing_idx)
                chunk = missing_idx[:_BATCH_SIZE]
                await _report(
                    f"{task.theory_longname}: {len(missing_idx)} of "
                    f"{len(task.entries)} entities still have no description; "
                    f"asking the LLM again (attempt {stall + 1} of {_MAX_STALLED_RETRIES}).",
                    warn=True)
                missing_text = task.format_entries(chunk)
                header = (
                    f"You still have {len(missing_idx)} unanswered entries from theory "
                    f'"{task.theory_longname}" (location: {task.file_path})'
                    + (f"; here are the first {len(chunk)}"
                       if len(missing_idx) > len(chunk) else "")
                )
                await driver.run_turn(
                    f"{header}:\n"
                    f"{missing_text}\n\n"
                    f"Submit their translations via the `mcp__isabelle_semantics__answer` tool. "
                    f"Each translation must describe the formal statement shown above next to that exact name."
                )
        _log.info("total usage: input=%d cache_write=%d cache_read=%d output=%d tokens, cost=$%.4f",
                task.total_input_tokens, task.total_cache_creation_tokens,
                task.total_cache_read_tokens, task.total_output_tokens, task.total_cost_usd)
    except ReachLimitError:
        # Throttled, legitimate retry — does not consume the recycle budget.
        _log.info("agent: reached usage limit, waiting 20min to retry")
        await asyncio.sleep(1200)
        return await _run_agent(make_driver, depth)
    except RateLimitError:
        # Throttled, legitimate retry — does not consume the recycle budget.
        _log.info("agent: API rate limit, waiting 2s to retry")
        await asyncio.sleep(2)
        return await _run_agent(make_driver, depth)
    except PoisonedSessionError:
        # The conversation is irrecoverably rejected by the API (e.g. a lone
        # surrogate pinned in the transcript).  Recycle with a FRESH driver
        # (it starts a new session, so the bad history is dropped) and continue
        # with the still-missing entries — answers already written persist in
        # `task.results`, so we do not redo them.
        if depth >= _MAX_AGENT_RECYCLES:
            # Do NOT return here: returning would hand back a task with unanswered
            # entries and no error, which interpret_file would report as success.
            raise FatalAgentError(None,
                f"poisoned session (API 400) persisted after {depth} client recycles")
        _log.warning("agent: poisoned session (API 400); recycling client "
                     "(recycle %d/%d)", depth + 1, _MAX_AGENT_RECYCLES)
        return await _run_agent(make_driver, depth + 1)
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
        if depth >= _MAX_AGENT_RECYCLES:
            _log.exception("agent: unexpected failure persisted after %d "
                           "recycles; re-raising", depth)
            raise
        _log.exception("agent: unexpected failure; recycling client "
                       "(recycle %d/%d)", depth + 1, _MAX_AGENT_RECYCLES)
        await asyncio.sleep(2)
        return await _run_agent(make_driver, depth + 1)


# --- Public API ---

async def interpret_file(
    connection: Connection,
    file_path: str,
    theory_longname: str,
    theory_key: universal_key,
    entries: list[Entry],
    driver: str = "",
) -> InterpretationResult:
    """Interpret entities from an Isabelle theory file.

    Looks up cached interpretations in LMDB. For uncached entries, launches
    an agent to generate plain-English translations.

    Args:
        connection: Active Isabelle RPC connection.
        file_path: Path to the theory source file.
        theory_longname: Fully qualified theory name (e.g. "HOL.List").
        theory_key: Universal key for the theory (used for cost tracking).
        entries: Entities to interpret, each with kind, name, prop_str,
            line_number, and universal_key.
        driver: The Isabelle side's `"<Driver>[.<model>]"` choice, "" if it made
            none; `_resolve_driver` decides what actually runs.

    Returns:
        InterpretationResult with per-entry interpretations, pretty-prints,
        and cost summaries (current run + cumulative).
    """
    n = len(entries)
    # Resolve up front, before any cache read or LLM work: a misspelt driver
    # name is a configuration error and should say so immediately rather than
    # after the cone has been walked.
    driver_name, model = _resolve_driver(driver)
    driver_cls = resolve_interpretation_driver_class(driver_name)
    if driver_cls is None:
        raise FatalAgentError(
            f"Semantic interpretation failed: unknown interpretation driver "
            f"{driver_name!r}. Known drivers: "
            f"{', '.join(available_interpretation_drivers())}.")
    model = model or driver_cls.DEFAULT_MODEL

    # Build Unicode pretty-prints for all entries
    pretty_prints = [_pretty_print_entry(e) for e in entries]

    # Inherit RPC server's logging configuration (idempotent, no race).  The
    # driver package gets it too: its loggers are NOT children of this module's,
    # so without this the driver's lines (tool allowed/denied, model output,
    # per-round usage) would silently vanish from the host log.
    for lg in (_log, logging.getLogger(f"{__package__}.interpretation_driver")):
        if not lg.handlers and connection.server.logger.handlers:
            for h in connection.server.logger.handlers:
                lg.addHandler(h)
            lg.setLevel(connection.server.logger.level)
    _log.info("interpret_file: %s (%s), %d entries", theory_longname, file_path, n)

    # Check LMDB cache
    results: list[str | None] = [None] * n
    for i, e in enumerate(entries):
        rec = Semantic_DB[e.universal_key]
        if rec is not None and rec.interpretation is not None:
            results[i] = rec.interpretation
            if e.prop_str and rec.expr != e.prop_str:
                Semantic_DB.update_expr(e.universal_key, e.prop_str)

    uncached = [i for i, r in enumerate(results) if r is None]
    n_cached = n - len(uncached)
    # Say what is about to happen in words, not internal vocabulary: "entries/cached/to
    # interpret" means nothing to someone watching from a theory buffer.
    if not uncached:
        await _report(f"{theory_longname}: all {n} entities are already described "
                      f"in the database, nothing to ask.")
    elif n_cached:
        await _report(f"{theory_longname}: found {n} entities to describe; "
                      f"{n_cached} are already in the database, asking the LLM for the "
                      f"remaining {len(uncached)}.")
    else:
        await _report(f"{theory_longname}: found {n} entities to describe; none are in "
                      f"the database yet, asking the LLM for all {n}.")
    current_cost = CostSummary(0, 0, 0, 0, 0.0)
    cumulative_cost = CostSummary(0, 0, 0, 0, 0.0)

    if uncached:
        from .hover import mk_definition_tool, mk_hover_tool
        from .semantics import mk_query_by_name_tool
        from .theory_structure import mk_unicode_file

        unicode_file_path = mk_unicode_file(file_path)

        with InterpretationTask(
            connection, file_path, theory_longname, theory_key,
            entries=[entries[i] for i in uncached],
            driver=driver_name, model=model,
        ) as task:
            _local_task.set(task)

            m = len(task.entries)

            for start in range(0, m, _BATCH_SIZE):
                batch_range = range(start, min(start + _BATCH_SIZE, m))
                task.batches.append((
                    task.build_prompt(unicode_file_path, theory_longname, batch_range),
                    batch_range,
                ))

            working_names = [e.name for e in task.entries]
            # The desugar tool annotates each constant it shows with its English
            # description, and skips a constant it has already annotated in this
            # conversation.  Once the backend compacts the conversation those
            # annotations are gone from the agent's context while this set still
            # says "told them" — so the driver clears it just before compacting
            # (`on_context_reset`), and the agent never sees an unexplained
            # constant.  It is a bare local reachable from neither `task` nor the
            # tool objects, hence its own channel into the driver.
            seen_constants: set[str] = set()
            query_by_name_tool = mk_query_by_name_tool(
                connection, working_names, file_path=file_path)
            definition_tool = mk_definition_tool(connection, unicode=True)
            hover_tool = mk_hover_tool(connection, unicode=True)
            desugar_tool = mk_desugar_and_explain_tool(
                connection, file_path=file_path, seen_constants=seen_constants,
                dedup=driver_cls.REPORTS_CONTEXT_RESET)
            tools = [query_by_name_tool, definition_tool, hover_tool,
                     desugar_tool, _answer_tool]

            def make_driver() -> InterpretationDriver:
                return make_interpretation_driver(
                    driver_name,
                    model=model,
                    system_prompt=_SYSTEM_PROMPT,
                    tools=tools,
                    task=task,
                    on_context_reset=seen_constants.clear,
                )

            _log.info("interpret_file: starting %s agent on %s with %d batches",
                      driver_name, model, len(task.batches))
            await _run_agent(make_driver)
            answered = sum(1 for v in task.results.values() if v is not None)
            _log.info("interpret_file: agent finished, %d/%d interpreted",
                       answered, len(task.entries))
            # COMPLETENESS INVARIANT: interpret_file either gives every entry an
            # interpretation or raises; the returned `interpretations` never
            # contains None.  Isabelle relies on this -- Semantic_Store.interpret'
            # discards the list entirely, and interpret_cone marks a theory
            # interpreted as soon as interpret' RETURNS.  Were a partial result to
            # get back, the theory would be recorded as done with entities missing,
            # and only `force` could ever redo it.
            #
            # The retry loop above already raises when it stalls; this is the
            # backstop that keeps the invariant true no matter how the loop is
            # later restructured.  ANYONE RELAXING THIS must also revisit
            # semantic_store.ML's `val (_, _, current, cumulative)` and
            # interpret_cone's unconditional mark_interpreted.
            if answered < len(task.entries):
                missing_names = [e.name for e, k in zip(task.entries, task._keys)
                                 if task.results[k] is None]
                raise FatalAgentError(_msg_unanswered(
                    theory_longname, missing_names, len(task.entries)))
            # Cost is flushed per round in _accumulate_usage, so this is normally
            # a no-op flush; it still returns the up-to-date cumulative totals.
            cum = task.write_cost()
            # current_cost = cost of THIS run; read from the run-level
            # accumulator (write_cost resets total_*, but never run_*).
            current_cost = CostSummary(
                task.run_input_tokens, task.run_cache_creation_tokens,
                task.run_cache_read_tokens, task.run_output_tokens,
                task.run_cost_usd)
            cumulative_cost = CostSummary(*cum)
            await _report(f"{theory_longname}: done -- {answered} entities described, "
                          f"cost ${current_cost.cost_usd:.4f}.")

            # Remap agent results to original indices (cache already written
            # incrementally). Iterate _keys by position — it is 1:1 with
            # task.entries and with `uncached` — instead of relying on
            # results.values() insertion order.
            for i, key in enumerate(task._keys):
                sem = task.results[key]
                if sem is not None:
                    results[uncached[i]] = sem
    else:
        # All cached — read cumulative cost from DB
        with InterpretationTask(
            connection, file_path, theory_longname, theory_key,
            entries=[], driver=driver_name, model=model,
        ) as task:
            cumulative_cost = CostSummary(*task.historical_cost())

    return InterpretationResult(
        results,
        pretty_prints,
        current_cost,
        cumulative_cost,
    )


# --- RPC shim ---

@isabelle_remote_procedure("Semantic_Store.interpret_file")
async def _interpret_file(arg: Any, connection: Connection) -> InterpretationResult:
    from Isabelle_RPC_Host.universal_key import THM_RULE_KINDS
    (file_path, theory_longname, theory_key, driver, raw_entries) = arg
    entries = [
        Entry(
            kind=kind,
            name=pretty_unicode(name),
            prop_str=pretty_unicode(prop),
            line_number=lineno,
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
        )
        for kind, name, prop, lineno, uk, hint, prov, consts in raw_entries
    ]
    return await interpret_file(
        connection, file_path, theory_longname, bytes(theory_key), entries, driver
    )

