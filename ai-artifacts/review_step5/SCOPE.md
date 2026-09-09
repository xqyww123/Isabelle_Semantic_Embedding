# Review scope: semantic change gate, implementation step 5 (the gate proper)

> RE-REVIEW (after the first review's five rulings, `judge.json`,
> `FIX_LIST.md`, all applied 2026-09-09): see the section "What changed
> since the first review" at the end.

All paths are relative to `contrib/Semantic_Embedding/` (absolute root:
`/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/`).  Do not modify any
file.  You may run pytest (command below); never run `isabelle build`.

## What is being reviewed

The plan is `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` (rev 5.3,
authoritative; §0 glossary fixes the vocabulary; §2 lists the user's settled
decisions D1–D17 -- do not re-open them).  Its §13 lists eight implementation
steps.  Steps 1–4 are reviewed, accepted and committed (`8683e6f`, `5a3c201`;
review records under `ai-artifacts/review_step3/` and `review_step4/`).
**Step 5 is what you review now**: the gate per entity.  Specification: §13
item 5, §3 (the gate rule and its table), §5.3.1 (enrolment and the snapshot
raise), §5.4 (the gate's six steps, Failures, Corrections), §5.5 (tasks,
tools, the judge session, derived permissions), §7, §12 #5 (the one new
user-visible text), §15.1, §15.2 (`max_stalled_retries`), §15.3 (the task's
new fields), §15.5 (`_gate`, `_prefilter`, `_judge`, `_write`, `_propagate`,
the concurrency argument), §15.6 (`JudgeTask`, `verdict`, the judge driver,
the permission derivation), §15.8 "Run-scoped state" (`RunState`,
`current_run_state`, `emb_store`), §15.9 (cost), §15.10 (the step-5 test
file) and §15.11's "After step 5" bullet.

`working_tree.diff` is `git diff` against the step-4 commit (`5a3c201`) for
the touched files.  Read the files on disk for the full picture:
`Isabelle_Semantic_Embedding/semantic_interpretation.py` (constants,
`_JUDGE_SYSTEM_PROMPT`, `CostSummary.plus`, `RunState` /
`current_run_state`, `AgentTask.max_stalled_retries` / `run_cost`,
`InterpretationTask.__init__`, `JudgeTask`, `mk_verdict_tool`,
`_retry_unanswered`, and the gate section `_Verdict` / `_cosine` /
`_prefilter` / `_judge` / `_write` / `_propagate` / `_gate`, and
`interpret_file`'s live branch), `interpretation_driver/__init__.py`
(`SERVER_NAME`, `cli_tools`), `interpretation_driver/claude_code.py`
(`_CLI_BUILTINS`, `_options`), `codex.py` and `mcp_server.py` (the import),
and the tests `archive/tests/test_semantic_change_gate.py` (new) and
`test_semantic_change_gate_storage.py`.

### Step 5 deliverables (what changed)

`semantic_interpretation.py`
- Constants `_GATE_SIMILARITY = 0.90`, `_PREFILTER_TIMEOUT_S = 60`,
  `_JUDGE_SESSIONS = asyncio.Semaphore(40)`; `_JUDGE_SYSTEM_PROMPT`.
- `RunState` (field `prefilter_disabled`) and `current_run_state()`, which
  returns a fresh `RunState` until the lock (§13 step 7) lands;
  `interpret_file` resolves it once at its top.
- `AgentTask.max_stalled_retries` (class attribute, `_MAX_STALLED_RETRIES`;
  read by `_retry_unanswered`), `AgentTask.run_cost()`; `CostSummary.plus`;
  `_NO_COST`.
- `InterpretationTask.__init__` gains `emb_store`, `run_state`,
  `make_judge_driver` keywords and `judge_cost`.
- `JudgeTask(AgentTask)`: `cost_prefix = b"judge_"`, `max_stalled_retries =
  1`, one entry (`enqueue(0)` in the constructor), the pair prompt
  (Description 1 = baseline, Description 2 = fresh), `on_answer` records the
  `why` and marks the entry done, `retry_report` "", the judge's retry prompt
  and give-up text.  `mk_verdict_tool(judge)`: `{same, why}`, sets
  `judge.verdict`, calls `judge.on_answer`, replies "Verdict received. Stop
  now.", writes nothing.
- The gate: `_Verdict` (CHANGED / UNCHANGED enum), `_cosine` (None on a zero
  norm or a non-finite value), `_prefilter` (skipped when `emb_store is None`
  or `prefilter_disabled`; two `entity_document_text` renderings over
  `SemanticRecord(kind, name, prop_str, text)`; one `embed([...],
  role="document")` under `asyncio.timeout`; on any `Exception`: flag first,
  host-log warning, `_report(§12 #5, warn=True)`, None), `_judge` (asserts
  `make_judge_driver`, builds a `JudgeTask`, runs `_run_agent` under the
  semaphore; `except Exception` → warning, CHANGED; `finally` adds the
  judge's `run_cost()` to `task.judge_cost`; returns `verdict is True`),
  `_write(task, idx, rec, verdict, text) -> bool` with §3's rows (not judged
  → today's; row 1 → ε; CHANGED → `mint()`; UNCHANGED → the stored version
  and baseline; returns whether it minted), `_propagate` (§5.3.1: enqueue /
  pass / snapshot raise through `update_gate_fields` under
  `_note_on_failure("while raising the interpreted_at snapshot of <j>")`),
  `_gate` (the fixpoint of §15.5 with its awaits; `_propagate` after the
  loop when minted).
- `interpret_file`: resolves `emb_store` on the live path through
  `await connection.semantic_vector_store()` inside `except Exception`
  (skipped when `prefilter_disabled`); builds `make_judge_driver`
  (`system_prompt=_JUDGE_SYSTEM_PROMPT`, `tools=[mk_verdict_tool(judge)]`,
  `cli_tools=False`); hands the three to the task; `current_cost =
  task.run_cost().plus(task.judge_cost)`.

`interpretation_driver/`
- `SERVER_NAME` moved to `__init__.py` beside `AGENT_DIR`; `mcp_server.py`,
  `codex.py`, `claude_code.py` import it.
- `make_interpretation_driver(..., cli_tools=True)` and
  `InterpretationDriver.__init__(..., cli_tools=True)` storing `self.cli_tools`.
- `claude_code.py`: `_TOOL_WHITELIST` → `_CLI_BUILTINS` (built-ins only);
  `_options()` computes `allowed` once (`mcp__<SERVER_NAME>__<t.name>` for
  the served tools, plus `_CLI_BUILTINS` iff `cli_tools`) and BOTH
  `allowed_tools=sorted(allowed)` and the `_permission_control` closure read
  it.  Codex derives from `self.tools` already (its read-only sandbox still
  lets the judge read files -- the plan's recorded deviation).  DeepSeek
  inherits.

Tests
- New `archive/tests/test_semantic_change_gate.py` (33 tests): a scripted
  judge driver (verdict per entity name, or per fresh text), a fake
  embedding provider (cosine per fresh text, scale, zero vector, exception,
  delay), a stub connection with `semantic_vector_store()`; enrolment (with a
  not-enrolled entry in FIRST position, the step-4 judge's requirement), the
  query refusal of an enrolled dependent, every wire-order permutation, the
  snapshot raise (and that it keeps the vector; and that a failed raise
  fails the run with the store's exception and its note), the decision table (first
  write, legacy record, prefilter, scale-free / zero vector, the four judge
  outcomes, theorem-alike with and without a record, persistent /
  collection), the prefilter's failure policy (once per run, timeout,
  unconfigured, failing resolution), corrections (both verdicts,
  byte-identical, mid-judge), the judge cap and one entity per session,
  cancellation, a rate limit mid-turn, the rec_cache wall, the bare user
  error without a group gutter, cost, the judge task's shape, the derived
  permissions.  Every run ends with the post-run invariant (version and
  interpreted_at ≤ counter) and is bounded by a 20 s `wait_for`.
- `test_semantic_change_gate_storage.py`: the step-4 correction test (a
  correction re-run as a first write) deleted -- a correction is now a judged
  second gate, covered in the new file; docstrings updated.
- Mutation checks (each fails at least one test when applied): the mid-gate
  correction test removed; no snapshot raise; cosine without the zero-norm
  guard; the prefilter failure not disabling; a failed judge reading as
  "same"; UNCHANGED minting; built-ins always allowed; no judge cap; no
  enrolment; the judge retrying like the agent; no note on the snapshot
  raise.

### Derivations the implementer made (not literally in the plan — judge them)

1. `_Verdict` is a two-member `enum.Enum` (CHANGED / UNCHANGED); "no verdict
   needed" is `None`.  The plan writes the names bare.
2. `_write`'s UNCHANGED row reads a version-less record as ε
   (`rec.version or w.counter_value()`), the same reading as the theorem-alike
   row and the scan (§9 "ε epoch"); the plan's table says "unchanged".  A
   record with a digest and a baseline but no version cannot come from the
   gate, but the reading costs nothing and keeps `eff_value` off a None.
3. `_judge` adds the judge's cost in a `finally`, so a failed session's
   cost is counted too; the plan says "when each gate finishes".
4. `CostSummary.plus` and `AgentTask.run_cost()` replace the hand-built
   `CostSummary(task.run_input_tokens, ...)`; `_NO_COST` replaces the two
   zero literals.
5. The judge's pair prompt and `_JUDGE_SYSTEM_PROMPT` name the tool by its
   flat MCP name `mcp__isabelle_semantics__verdict`, as the interpretation
   prompts do (§5.5: prompt literals are prompt text).
6. `_prefilter` logs the exception with `exc_info` at warning and reports
   §12 #5's wording WITHOUT the `[Semantic_Embedding]` prefix, like every
   other `_report` line of this module today (step 8 harmonises the texts).
7. `interpret_file` resolves `emb_store` inside the `if seeds:` branch (only
   a run that judges needs it), after the driver resolution and the opening
   line.  D16's `warn` threading is step 6's: until then an unconfigured
   embedding service prints the whole 23-line `_missing_api_key_message` on
   the user-visible warning channel once per seeded theory
   (`_resolve_embedding_config` warns before it raises, semantics.py; nothing
   is memoised because the resolution precedes the registry read).
8. `RunState()` is the default of `InterpretationTask.__init__`'s
   `run_state` (a task built directly, as the storage tests do, has one).
9. The judge session's `on_context_reset` is `lambda: None`.
10. `_gate` logs a prefilter CHANGED at info with the similarity.
11. The judge's `enqueue(0)` in the constructor appends to its own
    `enrolled_names` and sets its own `_progress` event: harmless, and no
    override of `enqueue` is needed.

## Suite

    cd /home/qiyuan/Current/MLML/contrib/Semantic_Embedding && \
    python -m pytest archive/tests/ --ignore=archive/tests/test_e2e_source_prop.py \
      --deselect archive/tests/test_agent_dir_packaging.py -q -p no:cacheprovider

→ 384 passed, 3 failed (test_config_resolution ×2,
test_embedding_provider_refactor::test_fireworks_qwen: API-key/config
environment, pre-existing, unrelated).

## Project rules that bind the review

- Elegance is a review criterion equal to correctness: a shape that makes an
  invariant impossible to violate beats one that asks people to remember it.
  Reject dirty hacks.
- Reuse code; never reinvent; consistent terminology (the plan's §0
  glossary).  Comments in code short and load-bearing.
- Nitpicking (style-only remarks, hypotheticals with no concrete failure,
  restating the plan, "consider adding a comment", re-raising a settled
  decision D1–D17 or a ruling of the step-3 / step-4 reviews) is to be
  rejected harshly.
- If slightly relaxing one of the user's constraints or design decisions
  would make the code markedly simpler or more elegant, say so explicitly as
  a PROPOSAL for the user — do not smuggle it in as a bug.

## What changed since the first review (the five rulings, all applied)

1. machinery-F2: `_prefilter` sets `_embed_tracing_gated` (imported from
   semantic_embedding, the whole-DB embed's own gate) before the `try` and
   resets it in a `finally`; `_FakeProvider` records the flag, the
   prefilter test asserts `[True, True]` and reset afterwards.
2. gate-F1: `RunState.claim_prefilter_disable() -> bool` (flip and say
   whether this caller flipped, one synchronous step); `_prefilter` logs the
   traceback unconditionally and reports §12 #5 only when the claim returns
   True.  Plan §15.5 and §5.4 Failures edited by hand accordingly.  The
   failure test is parametrised over `delay in (0.0, 0.01)` with a and b both
   inside the failing call and c answered after the flag flipped (batch size
   2): one line in both cases, every failure in the host log.
3. agreement-F4: the `<error>` slot is `str(exc) or type(exc).__name__`; the
   timeout test asserts the line "...did not respond: TimeoutError".
4. agreement-F1: `test_an_answer_for_an_entity_this_run_did_not_ask_for_is_refused`
   (the unrequested entity first in wire order; record byte-identical, counter
   untouched, no judge, no judge cost; fails with the `_NOT_ENROLLED` clause
   removed).
5. machinery-F3: derivation 7 reworded (above); no code change.

Mutations after the fixes (each fails a test): the tracing gate set to False;
the old "set the flag, then report" shape; a bare `{exc}`.  Suite: 387
passed / 3 pre-existing env failures.

## Re-review (rereview_judge.json): production code accepted; four test-only fixes, all applied

- The tracing gate's reset is pinned from inside the awaiting task
  (`test_the_prefilter_resets_the_tracing_gate_on_both_paths`; the vacuous
  after-the-run read deleted); mutation "the `finally` reset removed" fails it.
- `_Run.start` returns the bounded awaitable, `go` runs it; the hand copy
  `_run_under` deleted; the cancellation test uses `start`.
- `_caplog_at` replaced by pytest's `caplog` at its four sites.
- The unrequested-answer test scripts `verdicts={"T.d": False}` so the
  counter assertion discriminates under the `_NOT_ENROLLED` mutation.
- Proposal for the user (not blocking): an `embed_tracing_gated()` context
  manager beside the ContextVar, replacing the two hand-written token /
  `finally` pairs (semantic_interpretation.py `_prefilter`, semantics.py
  `complete_vector_store`).
