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

## Entry point for step 8 (written 2026-09-11, after step 7's review)

- Git: steps 1–6 committed (`8683e6f`, `5a3c201`, `0d279d7`, `aa5b93c`).
  Step 7 is implemented, reviewed (`ai-artifacts/review_step7/judge.json`,
  re-review `rereview_judge.json`) and committed in two halves, by the
  user's decision (a) of 2026-09-11 to let the other agent's interrupt work
  land first: that agent's commits -- Isabelle_RPC `2b22658` and
  Semantic_Embedding `694ebaa`, 2026-09-11 -- swept in the Isabelle_RPC half
  of step 7 (`Connection.on_close` / `_closed` / `close()`, the rpc.pyi line,
  `close_connection` in RPC.ML) and the whole of `Tools/semantic_store.ML`
  (the lock, the wrapping, the callback arm) without naming them; the rest
  of step 7 is the Semantic_Embedding commit of 2026-09-12 (see `git log`).
  The superproject was bumped by that agent to `2b22658` / `694ebaa` and by
  the step-7 commit after.  Still foreign and uncommitted: the temporary hunt
  marker in `Tools/entity_position.ML` and `archive/tests/test_migrate_from_collection.py`.
  Version floor: v0.5.0 of Isabelle_RPC is not to be tagged before
  `on_close` is in (user, 2026-09-11); pyproject.toml's floor comment says so.
- Step-7 files (Semantic_Embedding): `Tools/semantic_store.ML`
  (`try_acquire_cmd`, `with_interpretation_lock`, `local … in … end` around
  `interpret_with_parallel'` / `interpret_with_parallel : … -> unit option`,
  `lock_busy_error`, `interpret`, the callback arm), `Tools/interpret_command.ML`,
  `Tools/semantic_interpretation_app.ML`, `Isabelle_Semantic_Embedding/
  semantic_interpretation.py` (`_locked_run`, `current_run_state`,
  `_try_acquire_interpretation_lock`, `RunState` docstring),
  `Isabelle_Semantic_Embedding/snapshot_sync.py` (`INTERPRETATION_LOCK_NAME`),
  `pyproject.toml` (floor comment), `Test/ROOT`, `Test/Interpretation_Lock_Test.thy`,
  `archive/tests/test_interpretation_lock.py`, the plan (§8.1, §8.2, status
  paragraph at commit time), this file, `ai-artifacts/review_step7/`.
- What step 7 shipped (essence): one live interpretation run per database
  directory.  Python: `FileLock(timeout=0, thread_local=False)` on
  `<semantic_DB_dir()>/.interpretation.lock`, acquired by the RPC
  `Semantic_Store.try_acquire_interpretation_lock` and released by the
  acquiring connection's `on_close` closure (which also clears the module
  slot `_locked_run` that `current_run_state()` reads -- so the step-6
  startup check's flag now reaches the run).  ML: `with_interpretation_lock`
  takes a connection of its own, arms the finaliser first, tries once, runs
  the body, CLOSES the connection (never pools it); `interpret_with_parallel`
  is wrapped ⇒ `unit option`; four `NONE` sites print/raise §12 #1–#3;
  `dry_run` unlocked.  Judged sound; the release is asynchronous to the ML
  caller (host runs it at EOF) -- the ML test waits within a bound.
- Rejected by the judges, do not re-raise: swallowing the check's RPC
  failure (step 6); a `run_config` record (step 6); lazy import of
  `INTERPRETATION_LOCK_NAME`; moving the `Connection.close()` tests into
  Isabelle_RPC; a `with_own_connection` helper in RPC.ML (filtered);
  arming the Python release before the acquire (filtered); a dry run not
  binding the run state (filtered); renaming `Missing_Dimension`.
- ML tests: run through the REPL server ONLY, started with
  `SEMANTIC_DB_DIR=<scratch>` in its environment (the attached Python host
  inherits it; the host log under `$ISABELLE_HOME_USER/log/RPC_attached_*`
  shows the lock file's path), e.g.
  `SEMANTIC_DB_DIR=$SCR/lockdb ../Isa-REPL/repl_server.sh 127.0.0.1:6702 Semantic_Embedding $SCR/repl_out`;
  wait for a line matching `^Running REPL` AND for the port to listen
  (`ss -ltn`), then `IsaREPL.Client` async `file()`; stop it by the pid
  `ss -ltnp` shows on the port, in a shell step whose command line does not
  contain the launch string.  An edited `.ML` needs a restart (rebuilds the
  heap in ~20 s); an edited `.thy` test does not.
- WAIT for the user's explicit go-ahead ("开工" / "继续") before step 8.
- Step 8 = §13 item 8: texts (§12 -- every approved text to its site, found
  by grepping the current text's distinctive words, never by line number;
  #4 stays verbatim per the user; #1–#3 already in place from step 7; #5
  from step 5 lacks the `[Semantic_Embedding]` prefix today -- harmonise) and
  docs (§11: CHECK_OUTDATE_PLAN.md sections, the ML/Python comment sites
  listed there, `doc/invalidation_limitations.md` #7 incl. the §8.1
  release-ordering corner, README §5).  Then the acceptance items of §10
  that need a live service (non-LLM regression on `pairs_phase2.json`, the
  interactive scaffold, a live run's host log).

## Entry point for step 7 (done; kept as the record)

- Git: steps 1–5 committed (`8683e6f`, `5a3c201`, `0d279d7`; superproject
  `7ec6756b`, `7793813f`, `666cdae7`).  Step 6 is accepted by review and
  re-review (`ai-artifacts/review_step6/judge.json`, `rereview_judge.json`)
  and, at the time of writing, UNCOMMITTED: the user commits only on
  "提交".  Step-6 files: `Tools/semantic_store.ML` (also carries another
  agent's two `on_interrupt = Reraise` lines -- if they are still there at
  commit time they get swept in; say so in the message), `Test/Interpretation_Driver_Config_Test.thy`,
  `Isabelle_Semantic_Embedding/{semantics,semantic_interpretation,embedding_config}.py`,
  `archive/tests/test_semantic_change_gate.py` (37 tests), the plan (status
  paragraph, §5.6, §12 #4 note), this file, `ai-artifacts/review_step6/`.
  Foreign uncommitted edits still in the tree: `Tools/entity_position.ML`,
  `explain_term.ML`, `pide_state.ML`, `archive/tests/test_migrate_from_collection.py`
  -- not ours.  Nothing pushed.  Bump the superproject with
  `git add -f contrib/Semantic_Embedding` after the commit.
- What step 6 shipped (essence): `interpret_with_parallel` builds the run's
  one `Config.lookup` callback from `cfg_context` and threads that VALUE
  (`config_cb : Remote_Procedure_Calling.callback'`) through `interpret_cone`
  / `interpret'` / `send_for_interpretation` / `interpret_file_callbacks`
  (exported) / `check_embedding_service`; the startup check RPC
  `Semantic_Store.check_embedding_service` (unit → unit) runs once after the
  opening block when `n_units > 0`; Python's `_check_embedding_service`
  resolves with `warn=False`, constructs and discards the provider, and on any
  `Exception` sets `current_run_state().prefilter_disabled` and reports §12
  #4 once; `semantic_vector_store(warn=False)` in `interpret_file`;
  `embedding_config.Missing_Dimension`.  User rulings during step 6: keep
  §12 #4's slot text verbatim ("The system cannot continue." stays); an
  RPC-level failure of the check is fatal (judge: an old Python half must not
  run the pre-gate pipeline silently).  Rejected by the judges, do not
  re-raise: swallowing the check's RPC failure; a `run_config` record instead
  of `driver` + `config_cb`; fusing the check into the opening block's
  `n_units` guard; renaming `Missing_Dimension`.
- WAIT for the user's explicit go-ahead ("开工" / "继续") before step 7.
- Step 7 = §13 item 7: plan §8 (all three subsections), D8, D17, §12 #1–#3,
  §15.8 "Run-scoped state" (the lock creates the `RunState`; `current_run_state()`
  changes ONLY where the RunState comes from -- `Connection`-owned when a lock
  is held, fresh otherwise; step 6's flag write then reaches the run's
  theories), §10's lock lines ("three `NONE` behaviours of the lock; interrupt
  during the acquire round trip leaves the next acquire succeeding"; "lock: two
  processes on one `SEMANTIC_DB_DIR`; two instances in one process"), §11's
  limitation #7 corner.
- Python anchors: `snapshot_sync._install_lock` (snapshot_sync.py ~:248-257,
  `FileLock(..., timeout=0)`, `INSTALL_LOCK_NAME`) is the precedent to reuse;
  `Isabelle_RPC_Host/rpc.py` `Connection.close()` ~:236 (reached from
  `handle_client`'s `finally` and `__aexit__` -- gains an `on_close` list and
  a `_closed` flag, §8.1; that is a change in the Isabelle_RPC repo: commit
  there too); new RPC `Semantic_Store.try_acquire_interpretation_lock` → bool;
  `RunState` / `current_run_state()` in semantic_interpretation.py.
- ML anchors (Tools/): `with_interpretation_lock` per §8.2 (the code block is
  in the plan; `close_connection` RPC.ML:334 needs a signature entry in
  Isabelle_RPC's REMOTE_PROCEDURE_CALLING); wrap `interpret_with_parallel`
  (semantic_store.ML ~:2292) → `unit option`; the four `NONE` sites:
  `make_interpret_theory_callback` (~:2358; writeln §12 #1, return `([], ~1)`),
  `interpret_command.ML` `go ()` (error §12 #2), the collect app
  `semantic_interpretation_app.ML:99` (error §12 #3), the exported
  `interpret` (~:2353; error §12 #2, D17).  `dry_run` stays unwrapped.
- Tests: Python in `test_semantic_change_gate.py` or a new
  `test_interpretation_lock.py` (two processes on one dir via
  `multiprocessing`, two instances in one process, `on_close` releasing,
  `current_run_state()` returning the lock's RunState -- and now the
  step-6 startup check's flag reaching a run); ML in `Test/` through the
  REPL server only (`../Isa-REPL/repl_server.sh 127.0.0.1:6702 Semantic_Embedding <outdir>`;
  wait for a line matching `^Running REPL` -- the banner also contains the
  words, so anchor the grep; drive the theory with `IsaREPL.Client` async:
  `async with Client(addr, qualifier) as c: await c.set_register_thy(False); await c.file(path)`;
  kill the server by the pid `ss -ltnp` shows on the port, never by a
  `pkill -f` pattern that your own shell's command line also matches).
- Then: `ai-artifacts/review_step7/SCOPE.md` + diff, the review workflow
  (same shape as `review-gate-step6-*.js`; write the script with string
  concatenation, not backticks inside template literals), Chinese report
  with a fix plan, approval before production fixes, re-review, commit when
  asked.

## Entry point for step 6 (done; kept as the record)

- Git: steps 1–5 committed in this repo (`8683e6f`, `5a3c201`, `0d279d7`)
  and bumped in the superproject (`7ec6756b`, `7793813f`, `666cdae7`);
  nothing pushed.  The working tree carries foreign uncommitted edits
  (`Tools/entity_position.ML`, `explain_term.ML`, `pide_state.ML`,
  `semantic_store.ML` (+2 lines), `archive/tests/test_migrate_from_collection.py`)
  — not ours, leave them; if a step-6 commit must touch semantic_store.ML,
  say so in the commit message (CLAUDE.md allows sweeping them in).
- WAIT for the user's explicit go-ahead ("开工" / "继续") before touching
  production code.  The user declined the re-review's `embed_tracing_gated()`
  context-manager proposal ("看不到什么收益") — do not re-raise it.
- Step 6 = §13 item 6: plan §5.6 (the callback prerequisite and the startup
  check), D5, D16, §12 #4, §15.8 "Run-scoped state" (the startup check sets
  `RunState.prefilter_disabled`; NB until step 7 `current_run_state()`
  returns a fresh RunState per `interpret_file`, so the flag set by the
  startup check cannot reach `interpret_file` before step 7 — the
  re-review noted this: in that window it is `warn=False`, not the flag,
  that silences the per-theory repetition of the 23-line setup message;
  design the RPC so that step 7 only has to change where the RunState
  comes from), §10 ("`Config.lookup` among interpret_file's callback names";
  "an unconfigured embedding service completes the run with every gate
  judged and no error"), §11.
- ML anchors (Tools/semantic_store.ML, line numbers of 2026-09-10):
  `send_for_interpretation` builds its callback list at :1819-1835 (`su =
  Context_Callbacks.static_context_unpacker context`; the list has NO
  `Config.lookup` today); `interpret'` :1861, `interpret_cone` :2005,
  `interpret_with_parallel (cfg_context) (force) (roots)` :2255 — it calls
  `interpret_cone driver force cone` (:2288) and `interpret' driver ctx`
  for proof roots (:2293); thread `cfg_context` down both paths as one ML
  parameter beside `driver` (no wire change).  The existing pattern for the
  callback: `embed_all_missing` :2405-2415 and `query_knn` :2429
  (`Config.make_config_lookup_callback (Context_Callbacks.static_context_unpacker
  context)`; Isabelle_RPC/Tools/config.ML:35).  The startup check is one
  new RPC `Semantic_Store.check_embedding_service` called once per cone run
  at the top of `interpret_with_parallel`, carrying the same callback.
- Python anchors: `_resolve_embedding_config(connection)` semantics.py
  ~:2760 (warns with `_missing_api_key_message()` BEFORE raising, ~:2795-2802
  — gains `warn: bool = True`; the check passes `warn=False` and prints §12
  #4 itself once through `_report(..., warn=True)`), `_conn_semantic_vector_store`
  ~:2815 (threads `warn`), `Connection.config_lookup` (Isabelle_RPC_Host/rpc.py:209,
  callback name "Config.lookup"), `make_embedding_provider` (constructing the
  provider is where the model's dimension is looked up), `RunState` /
  `current_run_state` in semantic_interpretation.py, `_report`.
- Tests: Python side in `archive/tests/test_semantic_change_gate.py` (the
  `_Run` harness; a startup-check test through the RPC shim with a stub
  connection whose `config_lookup` answers, and the unconfigured case:
  §12 #4 once, `prefilter_disabled` set, a run completes with every gate
  judged); ML side per §10 in `Test/` (a callback-name assertion like the
  existing Test/*.thy — read one first, e.g. Test/Interpretation_Driver_Config_Test.thy),
  driven ONLY through the REPL server, never `isabelle build`.
- Then: `ai-artifacts/review_step6/SCOPE.md` + diff, the review workflow
  (same shape as `review-gate-step5-*.js`: 3 lenses → filter → rebutters →
  judge, Opus 5, English), Chinese report with a fix plan, approval before
  production fixes, a small re-review, commit when asked ("提交"), bump the
  superproject with `git add -f contrib/Semantic_Embedding`.

## Entry point for step 5 (done; kept as the record)

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
