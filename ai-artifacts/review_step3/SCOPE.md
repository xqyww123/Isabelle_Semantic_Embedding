# Review scope: semantic change gate, implementation step 3

All paths are relative to `contrib/Semantic_Embedding/` (absolute root:
`/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/`).

## What is being reviewed

The plan is `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` (rev 5.2, authoritative;
its §0 glossary fixes the vocabulary).  Its §13 lists eight implementation steps.
Steps 1–2 (storage field + `gate_write`, eff\*) were reviewed and accepted
earlier.  **Step 3 is what you review now**: the structural refactor of the
interpreter side that makes the gate possible, WITHOUT the gate's judge yet.
Plan §13 item 3, §15.1–§15.4, §15.7, §15.10 (the step-3 bullets), §15.11 (the
"After step 3" bullet) are the specification; §5.3, §5.4 and §5.5 the design it
derives from.  After step 3 the observable behaviour must equal today's: every
answer is written at once with the scan's `(version, interpreted_at)` pair; the
only behavioural difference is that each batch is now one agent turn.

The working tree is uncommitted.  `ai-artifacts/review_step3/working_tree.diff`
is `git diff` of the six touched files plus the new `archive/tests/conftest.py`;
NOTE it also contains the already-accepted steps 1–2 hunks in `semantics.py`
(`RECORD_FIELD_COUNT = 15`, `baseline_interpretation`, `update_interpretation`,
`Gate_Writer.counter_value/mint/update_gate_fields`, `gate_write`,
`_check_raw_put_grant`) and in `semantic_interpretation.py` (the `_contrib`
helper inside the eff\* evaluator).  Do not re-review those; read the files as
they are on disk for the full picture.

### Step 3 deliverables (what changed)

`Isabelle_Semantic_Embedding/semantics.py`
- `_Semantic_DB._put_fields(txn, key, fields, *, create=False) -> Record`: the
  shared copy-up-then-modify body; `update_interpretation`,
  `Gate_Writer.put_interpretation`, `Gate_Writer.update_gate_fields` and
  `backfill_field` all go through it.
- `Gate_Writer.put_interpretation(...)`: whole record in one put inside the
  gate transaction, vectors invalidated first, creates/resurrects.
- `Semantic_DB.counter_snapshot()`: read-only counter (1 on an empty store);
  `_unpack_counter` shared with `counter_value`.

`Isabelle_Semantic_Embedding/semantic_interpretation.py`
- Entity states `_NOT_ENROLLED, _QUEUED, _SENT, _GATING, _DONE`.
- `class AgentTask` (base): today's task fields; the queue primitives
  `enqueue`, `next_batch`, `unanswered_in_batch`, `unanswered`, `enrolled`,
  `answered`, `wait_for_progress`, `gate_started`/`gate_finished`,
  `session_started` hook; abstract `format_entries`, `build_prompt`,
  `on_answer`, `retry_report`, `retry_prompt`, `unanswered_failure`;
  `historical_cost`/`write_cost` with `_COST_KEYS` and the `cost_prefix`
  folding (§15.9; prefix is `b""` on every task that exists today).
- `class InterpretationTask(AgentTask)`: `unicode_file_path`,
  `_first_turn_sent` (reset by `session_started`), the step-3-only
  `inv_fields` pair field, `task_group`, `n_interpreted`; `on_answer`
  (D11 correction paths, otherwise `_GATING` + `start_gate`), `build_prompt`
  (first-turn / continue forms), the three retry strings.
- `mk_answer_tool(task)`: closure factory replacing the module-level tool and
  the `_local_task` ContextVar (deleted).  Refuses `_NOT_ENROLLED` / unknown
  labels.  Replies "Batch complete. ..." when the batch is answered.
- `_write(task, idx)` (the step-3 write: one `gate_write` + `put_interpretation`
  with the scan's pair, `baseline_interpretation=None`) wrapped as `GateError`
  on failure; `_gate(task, idx)` = `_write` in try/finally `gate_finished`.
- `GateError`; `_unwrap_gate_failures(eg)`.
- `_retry_unanswered(driver, task)`; `_run_agent(make_driver, task)` as a
  `while True` loop (no recursion): throttle arms with jitter
  (ReachLimit 1200±60 s; RateLimit min(2·2^n, 60) s ±50 %), `recycles` local
  consumed by the two hard-failure arms only.
- `interpret_file`: task over the `uncached` entries (as today — the scan is
  unchanged in step 3), `enqueue` all, tools include `mk_answer_tool(task)`,
  `async with asyncio.TaskGroup()` owning the gates, `except ExceptionGroup`
  → `_unwrap_gate_failures`, completeness check = no `unanswered()` +
  `assert all(state in (_DONE, _NOT_ENROLLED))`, closing line uses
  `task.n_interpreted`.

`interpretation_driver/mcp_server.py`, `interpretation_driver/__init__.py`:
type annotations re-typed to `AgentTask`; `bind_context` keeps only
`Connection.set_current`.

Tests: `archive/tests/test_interpretation_driver.py` (rewritten harness:
`_RecordingTask.start_gate` override, `_make_task` enrols all and sets
`SI._BATCH_SIZE`, new tests for the answer tool's reply / unknown entries, the
gate failure through a real `TaskGroup`, `_unwrap_gate_failures`),
`archive/tests/test_interpretation_mcp_server.py` (adapted),
`archive/tests/test_semantic_change_gate_storage.py` (+ `put_interpretation`
×4, `counter_snapshot`), new `archive/tests/conftest.py` (autouse fixture
restoring `_BATCH_SIZE`).

### Derivations the implementer made (not literally in the plan — judge them)

1. `retry_prompt(chunk)` instead of the plan's `retry_prompt(missing, chunk)`:
   a batch is at most `_BATCH_SIZE`, so the batch's unanswered set is never
   chunked further and the old "here are the first K" branch is dead.  The
   user-visible lines #14/#15 still use the run-wide m and N as the plan says.
2. `AgentTask.session_started()` hook, called by `_run_agent` when a fresh
   driver opens; `InterpretationTask` resets `_first_turn_sent` there, so
   every fresh session (first or recycled) gets the first-turn prompt form
   with the "Load the skills" line (today's code re-sends batch 0 to every
   recycled session, which had the same effect).
3. `_run_agent`'s `depth` parameter became the local `recycles` (the plan says
   depth "becomes a local").
4. `RunState` / `current_run_state()` are NOT added in step 3: §13 item 3 does
   not list them, §15.8 (step 4) defines them, nothing in step 3 uses them.
5. `archive/tests/conftest.py` with one autouse fixture restoring
   `SI._BATCH_SIZE`, because `_make_task` is imported by three test modules.
6. The `answer` tool's batch-complete reply text (agent-facing, needs no
   approval per plan §12).
7. `_unwrap_gate_failures` is annotated `BaseExceptionGroup` (the caller's
   `except ExceptionGroup` is as the plan says) so the CancelledError-leaf
   filter the plan asks for is testable.

## Suite

    cd /home/qiyuan/Current/MLML/contrib/Semantic_Embedding && \
    python -m pytest archive/tests/ --ignore=archive/tests/test_e2e_source_prop.py \
      --deselect archive/tests/test_agent_dir_packaging.py -q

→ 346 passed, 3 failed (test_config_resolution ×2,
test_embedding_provider_refactor::test_fireworks_qwen: API-key/config
environment, pre-existing, unrelated).  You may run pytest; never run
`isabelle build`; do not modify any file.

## Project rules that bind the review

- Elegance is a review criterion equal to correctness: a shape that makes an
  invariant impossible to violate beats one that asks people to remember it.
  Reject dirty hacks.
- Reuse code; never reinvent; consistent terminology (the plan's §0 glossary).
- Comments in code short and load-bearing.
- Nitpicking (style-only remarks, hypotheticals with no concrete failure,
  restating the plan, "consider adding a comment") is to be rejected harshly.
- If slightly relaxing one of the user's constraints or design decisions
  (plan §2 D1–D17) would make the code markedly simpler or more elegant,
  say so explicitly as a PROPOSAL for the user — do not smuggle it in as a bug.
