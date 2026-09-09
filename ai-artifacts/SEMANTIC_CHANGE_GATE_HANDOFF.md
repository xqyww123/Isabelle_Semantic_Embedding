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
- Step 4 (scan rewrite) implemented 2026-09-09 after the user's "继续";
  reviewed (`ai-artifacts/review_step4/`: SCOPE.md, working_tree.diff,
  judge.json — 13 agents, 5 fixes, no user decision): live-path statement
  refresh made unconditional (one call before the return), the query tool's
  refusal compares `pretty_unicode(name)` against `enrolled_names`, the
  "starting agent" log counts `task.enrolled()`, no self edge in
  `dependents`, three test comments; + tests (zero-seed live refresh,
  refusal in either spelling, theorem-alike eff* disjunct).  Suite 356
  passed / 3 env failures.  Derivations ruled sound: RunState / emb_store /
  make_judge_driver deferred to step 5; `enrolled_names` on AgentTask;
  `rec_cache` a constructor keyword; every judged entry written as §3 row 1
  until step 5 (baseline := text); opening lines' wording waits for step 8.
- Step 5 (the gate proper) implemented 2026-09-09 after the user's "开工";
  reviewed (`ai-artifacts/review_step5/`: SCOPE.md, working_tree*.diff,
  judge.json — 10 agents; rereview_judge.json — 3 agents; FIX_LIST.md):
  three production fixes approved by the user and applied (the prefilter's
  `embed` under `_embed_tracing_gated`; `RunState.claim_prefilter_disable()`
  so §12 #5 is printed once per run even by gates already inside the
  failing call; the `<error>` slot `str(exc) or type(exc).__name__`), plan
  §5.4 Failures / §15.5 / status edited by hand (rev 5.4); the re-review
  accepted the production code and asked four test-only fixes, all applied
  (the tracing gate's reset pinned from inside the awaiting task; `_Run.start`
  / `go` split, no hand copy; pytest's `caplog`; a scripted CHANGED verdict
  in the unrequested-answer test).  Suite 388 passed / 3 env failures; 33
  tests in the new file.  Proposal from the re-review, DECLINED by the user
  2026-09-09 ("看不到什么收益"; do not re-raise): an `embed_tracing_gated()` context manager beside the ContextVar in
  semantic_embedding.py replacing the two hand-written token/`finally` pairs
  (semantic_interpretation.py `_prefilter`, semantics.py
  `complete_vector_store`).  Until §13 step 6 threads D16's `warn`, an
  unconfigured embedding service prints the 23-line setup message once per
  seeded theory (recorded, not a regression).
- Next (was): §13 step 5 (the gate proper: prefilter, JudgeTask + verdict tool,
  decisions, propagation, snapshot raise, failure handling, derived
  permissions, SERVER_NAME move, cli_tools; RunState / current_run_state,
  emb_store, make_judge_driver; `_propagate` with `_note_on_failure`) —
  needs the user's go-ahead.  Step 5's test file must carry the enrolment
  test with a not-enrolled entry NOT in last position (step-4 judge).

## Entry point for step 5 (read this after the compaction)

- Git: steps 1–4 committed in this repo (`8683e6f`, `5a3c201`) and bumped in
  the superproject (`7ec6756b`, `7793813f`); nothing pushed.  The working
  tree still carries two foreign edits (`Tools/entity_position.ML`,
  `archive/tests/test_migrate_from_collection.py`) — not ours, leave them.
- WAIT for the user's explicit go-ahead ("开工" / "继续") before touching
  production code.  Then: read plan §3, §5.4, §5.5, §5.6, §12, §15.1,
  §15.5, §15.6, §15.8 "Run-scoped state", §15.9, §15.10 (step-5 file), §15.11
  (after step 5); then the code on disk (`_write` / `_gate` / `_EffStar` /
  `interpret_file` in semantic_interpretation.py; the driver package's
  `_options` / permissions in claude_code.py, codex.py; mcp_server.py's
  `SERVER_NAME`).  Implement, test (new `archive/tests/test_semantic_change_gate.py`
  driving `interpret_file` with a scripted driver, a scripted judge driver and
  a fake embedding store over the `cache` fixture; reuse the helpers of
  test_semantic_change_gate_storage.py / test_interpretation_driver.py), run
  the suite, write `ai-artifacts/review_step5/SCOPE.md` + diff, run the
  review workflow (same script shape as `review-gate-step4-*.js`: 3 lenses →
  filter → rebutters → judge, Opus 5, English), report in Chinese with the
  fix plan, wait for approval on production fixes, apply, commit when asked.
- Step-5 specifics already decided: `_write(task, idx, rec, verdict, text)`
  gains the verdict and §3 rows 2–5; `_gate`'s fixpoint gets its awaits
  (prefilter, judge); `_propagate` per §15.5 with
  `_note_on_failure("while raising the interpreted_at snapshot of <j>")`;
  judge cap `asyncio.Semaphore(40)` around the session only; `JudgeTask`
  with `max_stalled_retries` attribute (interpretation: `_MAX_STALLED_RETRIES`,
  judge: 1) read by `_retry_unanswered`; `mk_verdict_tool`; derived
  permissions (`_CLI_BUILTINS`, one local feeding both `allowed_tools` and
  the hook); `SERVER_NAME` moves to `interpretation_driver/__init__.py`;
  `cli_tools` flag; `RunState` / `current_run_state()`; `emb_store` resolved
  per `interpret_file` via `connection.semantic_vector_store()` inside
  `except Exception`; texts stay today's (step 8).

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
