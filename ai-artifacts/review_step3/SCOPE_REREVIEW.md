# Re-review scope: semantic change gate, step 3 after its fixes (2026-09-09)

All paths are relative to `contrib/Semantic_Embedding/` (absolute root:
`/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/`).  Do not modify any
file.  You may run pytest (command below); never run `isabelle build`.

## What this review is

The first review of step 3 (`REPORT.md`, 2026-09-08) ruled 9 findings, two of
them "fix-then-rereview" (F3, F10).  A follow-up design review
(`D11_REGATE_DESIGN.md` + `d11_judge.json`, 2026-09-09) approved the user's
revised D11 with 7 fix items and also asked for a re-review of the result.
Every ruling was compiled into `FIX_LIST.md` and has now been applied to the
plan, the code and the tests.  **You review the result**: does the code do
what the (amended) plan says, is it sound, is it elegant, and are the tests
adequate?  The judge decides whether step 3 is now acceptable.

Authoritative texts, in this order: the plan
`ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` (rev 5.3; §0 glossary; §2 D11 and
D14 as revised; §3 preamble and the paragraph after its table; §5.3.1; §5.4
"Failures" and "Corrections"; §6.4; §12 derived numbers; §13 items 1 and 3;
§14; §15.1–§15.5, §15.10, §15.11), then `FIX_LIST.md` (the rulings being
applied), then the code on disk.

## Decisions that are SETTLED (do not re-raise; check the transcription)

- **Correction** (vocabulary): the agent re-submits, through the `answer`
  tool, an entity it already answered in the same run.  Kept (the user).
- **D11 revised**: a correction re-runs the gate; the gate compares texts.
  `on_answer`: byte-identical text → no-op; `_GATING` → return (the running
  gate re-judges); else `_GATING` + `start_gate` (also from `_DONE`).  No
  `update_interpretation` (deleted from `semantics.py` with its tests).
- **Gate fixpoint**: `_gate` captures the text at the top of a round and, with
  no await between the test and the write, starts over if `task.results[idx]`
  moved; `_write(task, idx, text)` takes the judged text.  In step 3 the gate
  has no await, so the loop runs exactly once by construction.
- **Record source** (step 4/5): the gate reads `rec_cache`, never a pre-run
  record; `recs` stays a scan local.  Not code in step 3 (no `rec_cache` on the
  task yet), plan text only.
- **`n_interpreted()`** derived: `count(state == _DONE)`.
- **No `GateError`**: the store's own exception propagates after
  `exc.add_note("while writing the interpretation of <E>")` via the
  `_note_on_failure(note)` context manager (`except Exception`);
  `_first_failure(eg) -> BaseException` returns the first non-cancellation leaf
  (or `eg`); `interpret_file` raises it OUTSIDE the `except ExceptionGroup`
  block, no `from`.
- **F3**: `_stop_if_cancelled()` called first in all four recovering arms of
  `_run_agent` (a bare `raise` re-raises the arm's exception when
  `asyncio.current_task().cancelling()`).
- **F4**: `start_gate` increments, `create_task`, `add_done_callback(lambda _t:
  self.gate_finished())`; compensates and `coro.close()` when `create_task`
  raises (`except BaseException`).
- **F10**: `results` is a list index-aligned with `entries`; `_keys` deleted;
  the completeness backstop keeps BOTH the payload clause (`results` None) and
  the state assert.
- **P1**: `batch_size` is an `AgentTask` class attribute defaulting to
  `_BATCH_SIZE`; tests set `task.batch_size`; `archive/tests/conftest.py`
  deleted.
- Judge sessions cap 40 (D12); step 3 has no judge; scan unchanged in step 3.
- Test-related choices were delegated to the implementer by the user.

## What changed since the first review (the diff)

`working_tree_v2.diff` = `git diff` of the six tracked files (it still
contains the already-accepted steps 1–2 hunks and the whole step-3 refactor;
the NEW material since `working_tree.diff` is what the settled list above
names).  `archive/tests/test_semantic_change_gate_storage.py` is untracked;
read it on disk.  Specifically:

`Isabelle_Semantic_Embedding/semantic_interpretation.py`
- imports: `contextlib`, `Generator`; `NoReturn` dropped.
- `AgentTask`: `batch_size` class attribute; `results: list[str | None]`;
  `_label_to_idx` is its own seen-set; `_keys` gone; `enqueue` /
  `next_batch` (reads `self.batch_size`); `n_interpreted()` beside
  `enrolled()` / `answered()`.
- `InterpretationTask`: no `n_interpreted` field; `start_gate` per F4;
  `on_answer` per D11 revised (docstring rewritten).
- `mk_answer_tool`: comment no longer names `_keys`.
- `GateError` deleted; `_note_on_failure`; `_write(task, idx, text)`;
  `_gate` with the fixpoint loop (no try/finally — the counter is paired to
  the task); `_first_failure`; `_stop_if_cancelled` + four calls.
- `interpret_file`: `failure = _first_failure(eg)` inside the except, `raise
  failure` after; `task.n_interpreted()` at both readers; `missing` from
  `results`; the remap iterates `task.results`.

`Isabelle_Semantic_Embedding/semantics.py`: `update_interpretation` deleted
(`_put_fields(create=True)` keeps its user in `put_interpretation`).

Tests
- `archive/tests/test_interpretation_driver.py`: `_RecordingTask.start_gate`
  records `(idx, results[idx])`; `_make_task` sets `task.batch_size`; F10
  lines; new `_TaskGroupGateTask` (one entry's gate is a real task built by a
  supplied body, started with the production `start_gate` shape) and
  `_run_in_group` (interpret_file's shape); tests: correction re-gates /
  identical resubmission no-op; gate failure leaves as the store's exception
  with note, cause, no group context; a leaf's own `__context__` survives;
  `_first_failure` selection; F3 regression (`_TeardownConvertsCancellation`);
  F7 wait-for-gate.
- `archive/tests/test_semantic_change_gate_storage.py`: the four
  `update_interpretation` tests and the docstring clause deleted; new
  store-backed section: `_gate` over a tracked and an untracked entry
  (fields, states, `n_interpreted() == 2`); a corrupt record makes the gate
  write fail with the store's exception and the note; a correction as a
  second gate rewrites the text with the same pair and tombstones the vector;
  `interpret_file` end to end with the scripted driver (both records, ε and
  the snapshot, one session); `interpret_file` raising the store's exception
  itself (`lmdb.MapFullError` from a patched `gate_write`) with the note and
  no group context.
- `archive/tests/conftest.py` deleted.

Mutation checks performed by the implementer (each new test fails when its
fix is reverted): `_stop_if_cancelled` removed from the catch-all arm; the
`_progress.set()` in `gate_finished` removed; the identical-resubmission
guard removed; `raise _first_failure(eg)` inside the except block.

## Suite

    cd /home/qiyuan/Current/MLML/contrib/Semantic_Embedding && \
    python -m pytest archive/tests/ --ignore=archive/tests/test_e2e_source_prop.py \
      --deselect archive/tests/test_agent_dir_packaging.py -q -p no:cacheprovider

→ 348 passed, 3 failed (test_config_resolution ×2,
test_embedding_provider_refactor::test_fireworks_qwen: API-key/config
environment, pre-existing, unrelated).

## Project rules that bind the review

- Elegance is a review criterion equal to correctness: a shape that makes an
  invariant impossible to violate beats one that asks people to remember it.
  Reject dirty hacks.
- Reuse code; never reinvent; consistent terminology (the plan's §0 glossary;
  "correction" as defined above).  Comments short and load-bearing.
- Nitpicking (style-only remarks, hypotheticals with no concrete failure,
  restating the plan, "consider adding a comment", re-raising a settled
  decision) is to be rejected harshly.
- If slightly relaxing one of the user's decisions would make the code
  markedly simpler, say so explicitly as a PROPOSAL for the user — never
  smuggle it in as a bug.
