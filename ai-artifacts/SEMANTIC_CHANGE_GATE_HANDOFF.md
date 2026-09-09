# Semantic change gate — session handoff (2026-09-09)

Read this first after a context compaction; the plan itself is the authority.
All paths relative to `contrib/Semantic_Embedding/`.

## State (updated 2026-09-09 after the user's "开工")

- Plan: `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` rev 5.3 — every plan edit
  of `ai-artifacts/review_step3/FIX_LIST.md` is applied (work list item A).
- Code: work list items B and C are applied (uncommitted); suite 348 passed /
  3 pre-existing env failures (test_config_resolution ×2, test_fireworks_qwen).
  `archive/tests/conftest.py` deleted; `Semantic_DB.update_interpretation`
  deleted.  Four mutation checks confirm the new tests discriminate.
- Re-review (item D) done: scope `ai-artifacts/review_step3/SCOPE_REREVIEW.md`,
  diff `working_tree_v2.diff`, judgement `rereview_judge.json` (10 agents).
  Verdict: no production defect, no hack, nothing for the user; 5 fix items
  (tests + plan prose only), ALL APPLIED the same day: the driver tests now
  swap the gate BODY (`monkeypatch.setattr(SI, "_gate", ...)`) so the shipped
  `start_gate` runs everywhere, all loop tests run inside a `TaskGroup` via
  `_in_group`, + tests for the `create_task`-refusal compensation and for two
  items of one entry in one `answer` call (one gate, newer text); MCP tests
  own a `TaskGroup` around the client; one arity-invariant
  `put_interpretation` test; plan §15.11 (store vs loop), §15.10 (c)/(d) and
  the arity note, §10 arity clause, §15.2/§15.6 `retry_prompt(chunk)`.
  Acceptance gates measured: each of F4's four mutations and the D11
  `_GATING` mutation fails a test by assertion.
- Next: §13 step 4 (scan rewrite) — needs the user's go-ahead; no commit
  unless asked.

The decisions and work list below are kept as the record of what was done.

## Decisions taken 2026-09-08/09 (all by the user; write them into the plan)

1. **Correction** = the agent re-submits, through the `answer` tool, an entity
   it already answered in the same run (the tool invites it: "You may also
   resubmit an entry to correct a previous answer").  Not a re-interpretation
   of a stale entity.  The user did not know this ability existed; it MUST be
   kept ("不能删掉！").  Always define the term when it comes up.
2. **D11 revised: a correction re-runs the gate.**  The gate compares TEXTS
   (fresh vs `baseline_interpretation`), so a new text can change the verdict.
   `on_answer`: record text; if byte-identical to the previous text → no-op;
   if `_GATING` → return (the running gate re-judges, see 3); else (from
   `_QUEUED`/`_SENT` or from `_DONE`) → state `_GATING`, `start_gate`.
   No special correction path; `Semantic_DB.update_interpretation` is deleted
   (only caller was the old branch) together with its tests; `gate_write` is
   the only interpretation write entry point.
3. **Gate fixpoint (blocker from the D11 review):** `_gate` loops: read
   `rec = task.rec_cache[uk]` and `text = task.results[idx]` at the top of a
   round, judge THAT text, and just before the write (no await in between)
   `if task.results[idx] != text: continue`; `_write(task, idx, rec, verdict,
   text)` takes the judged text and record, never re-reads.  In steps 3–4 the
   body has no await so it runs once.
4. **Record source**: the gate reads the CURRENT record from `rec_cache`
   (written back after every gate write), once per round; `task.recs` is
   deleted from the task (scan-local only).  Reason: with the pre-run record a
   second UNCHANGED verdict would write back the pre-run version and roll a
   committed, propagated mint back.  §3's preamble: R = the record as stored
   when THIS gate runs.  A correction of an entity first written this run
   takes the judged rows and may mint — deliberate over-signalling (D2).
5. **`n_interpreted`** becomes a derived method `n_interpreted()` =
   count(state == _DONE) (entities, not gate runs).
6. **No `GateError`** (user + both judges): the native store exception
   propagates after `exc.add_note("while writing the interpretation of <E>")`
   via a `_note_on_failure(note)` context manager (`except Exception`, never a
   cancellation).  The unwrap helper becomes `_first_failure(eg) ->
   BaseException` (flatten, drop CancelledError leaves, log the rest, return
   the first; return `eg` itself if none) and `interpret_file` raises it
   OUTSIDE the `except ExceptionGroup` block (raising inside would overwrite
   the leaf's `__context__` with the group).  Plan §5.4 "raise leaves[0] from
   None" is replaced accordingly.
7. **Failure of any gate write fails the run** (incl. a correction's): true
   automatically since it is a gate write.  Crash shape (iii) for §6.4: a
   correction whose write fails leaves the first write's complete record; the
   next run does not re-ask; the correction is lost — harmless (user).
8. **P1**: `batch_size` becomes an `AgentTask` class attribute defaulting to
   `_BATCH_SIZE`; `next_batch` reads it; tests set `task.batch_size`; delete
   `archive/tests/conftest.py`.
9. Test-related choices are mine to make ("与测试相关的可以由你自行决定").

## Work list (in order)

A. Plan edits by hand (no scripts): every item in
   `ai-artifacts/review_step3/FIX_LIST.md` "plan edits" (D11 row, D13 split
   "interpreted once; gated once per accepted correction", D14 → "One write
   per verdict", §3 preamble + paragraph after the table, §5.3.1 `_DONE →
   _GATING` edge, §5.4 Failures (no GateError; `_first_failure`; note texts)
   and Corrections, §6.4 (one entry point; crash shape iii; qualify "No shape
   loses a signal"), §10, §13 item 3, §14 parenthesis, §15.1 table, §15.3
   `on_answer` + delete `recs`, §15.5 `_gate` fixpoint + `_write(task, idx,
   rec, verdict, text)` + `_note_on_failure`, §15.8 item 7 (no `recs=`),
   §15.10 (start_gate stub covers corrections; F8 recipe = drive a second
   gate; identical-resubmission case; batch_size), §15.11 step-3 bullet
   ("behaviour equals today's except: each batch is a turn; a failed store
   write, an answer's or a correction's, fails the run"), status paragraph.
B. Code, `semantic_interpretation.py`: `on_answer` per decision 2 (identical
   text no-op; `_DONE` re-gates); `_gate` fixpoint (decision 3; in step 3 the
   verdict is absent, `_write(task, idx, text)` with the scan pair);
   `n_interpreted()`; `results` as an index-aligned list, `_keys` deleted
   (F10; completeness check keeps BOTH clauses); `start_gate`: increment,
   `create_task`, `add_done_callback(lambda _t: self.gate_finished())`,
   compensate + `coro.close()` if `create_task` raises (F4; pre-start
   cancellation covered); `_stop_if_cancelled()` helper called first in the
   four recovering arms of `_run_agent` (F3; `asyncio.current_task().cancelling()`);
   `_first_failure` + raise outside the except (F1); `_note_on_failure`;
   delete `GateError`; `batch_size` attribute (P1).  `semantics.py`: delete
   `update_interpretation`; keep `_put_fields`, `put_interpretation`,
   `update_gate_fields`, `counter_snapshot`.
C. Tests: `test_interpretation_driver.py` — rewrite the two GateError tests
   against a native exception (assert the note is in the formatted traceback,
   `__cause__`/`__context__` preserved), add F3 regression (gate fails while
   the scripted driver's teardown converts the CancelledError into a
   RuntimeError → run ends, no extra turns, `gates_running == 0`), F7 (gate
   awaiting an Event after the queue emptied; `wait_for`; exactly one
   session), identical-resubmission no-op, `_DONE` correction re-gates
   (stub records twice), `_make_task` sets `task.batch_size`; delete
   conftest.  New store-backed tests beside
   `test_semantic_change_gate_storage.py` (reuse its `cache` fixture): F6
   (`_gate` over two entries, tracked/untracked, asserts the stored fields
   and `n_interpreted() == 2`), gate write failure propagates the native
   exception with the note, F8 (second gate on a `_DONE` entry rewrites the
   text with the same pair).  Delete the `update_interpretation` tests.
D. Run the suite; report in Chinese; then start a small re-review workflow
   (challenge → judge, Opus 5) over the fixed step (F1/F3/F10 + the D11
   fixpoint + plan/code agreement), as both judges required.

## User rules learned (keep obeying)

- Ask before changing production code; new design behaviour must be
  proposed; reasonable derivations of the user's decisions need no approval;
  do not re-raise decided items (judge cap 40; corrections are kept).
- DEFINE EVERY TERM when it first appears in a reply; never assume the user
  knows a label from the plan or from earlier turns; essence first, then the
  mechanism; Chinese for discussion, English for plan/code/texts; no coined
  words.  The "correction" misunderstanding cost an afternoon — a feedback
  draft about it is queued (`/feedback`).
- Reviews: workflow, Opus 5, English, nitpick filter, judge decides
  readiness and routing; report all concerns + fix plan in Chinese; no code
  before the user agrees.
- Plan documents edited by hand; comments short and load-bearing; never
  `isabelle build`; commit only when asked.
