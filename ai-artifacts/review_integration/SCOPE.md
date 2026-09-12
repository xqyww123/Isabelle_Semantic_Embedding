# Integration review: the semantic change gate, shielded invalidation and interpretation lock (steps 1–7, whole)

All paths are relative to `contrib/Semantic_Embedding/` (absolute root:
`/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/`); the sibling
repository `contrib/Isabelle_RPC/` (`/home/qiyuan/Current/MLML/contrib/Isabelle_RPC/`)
is part of the picture.  The code under review is HEAD of both repositories
(Semantic_Embedding `b16ab80`, Isabelle_RPC `2b22658`); there is nothing of
this feature in the working tree.  Do not modify any file.  You may run
pytest (command below) and small Python probes over a throw-away
`SEMANTIC_DB_DIR`; never run `isabelle build`; never start, connect to, or
kill any Isabelle process; never point anything at the real cache.

## Why this review exists

Seven implementation steps of one plan were each reviewed in isolation,
against the plan sections of that step, by a judge reading the code as it
was at that time (records: `ai-artifacts/review_step3/` … `review_step7/`,
each with `SCOPE.md`, `judge.json`, and where there was one
`rereview_judge.json`).  Nobody has yet read the whole feature as one
program: scan → work queue → gate (prefilter, judge) → write and propagate →
startup check → interpretation lock → run-scoped state.  Since the last
step, another agent's interrupt work has landed in both repositories
(Isabelle_RPC `2b22658`: callbacks answer an interrupt to Python as
`IsabelleInterrupt`, the `on_interrupt = Reraise | Swallow` policy;
Semantic_Embedding `694ebaa`), which changes what exceptions reach this
feature's `except` clauses.  Step 8 (user-visible texts §12 and docs §11)
is the only step left, so what you review is the final code minus wording.

## The plan (authoritative)

`ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md`, rev 5.4 with the step-6/7
edits.  §0 glossary fixes the vocabulary; §2 lists the user's settled
decisions D1–D17 -- do not re-open them.  §3 the gate rule and its table,
§4 eff\* (the shielded closure rule), §5 the run (5.2 scan, 5.3 queue, 5.4
gate, 5.5 tasks/tools/agent runner, 5.6 callback + startup check), §6
storage (record field, counter, field-disjoint writes, crash shapes), §7
the prefilter constant, §8 the lock, §9 what does not change, §10 tests,
§12 texts, §14 load-bearing facts, §15 code-level design (15.1–15.11).
The parent design is `CHECK_OUTDATE_PLAN.md` at the repo root of the
superproject (`/home/qiyuan/Current/MLML/CHECK_OUTDATE_PLAN.md`); its
glossary terms keep their meaning.

Settled by the five previous reviews and by the user -- do NOT re-raise:
every ruling in the five `judge.json` files; the user's declined proposals:
an `embed_tracing_gated()` context manager (step 5), a `run_config` record
bundling driver and context (step 6), rewording §12 #4's slot text ("The
system cannot continue." stays, step 6), swallowing the startup check's
RPC-level failure (step 6), a `with_own_connection` helper in RPC.ML,
arming the Python lock release before the acquire, a dry run not binding
the run state, renaming `Missing_Dimension`, moving the `Connection.close()`
tests into Isabelle_RPC, a lazy import of `INTERPRETATION_LOCK_NAME` (all
step 7).  The judge cap of 40 judge sessions (D12), corrections re-running
the gate (D11), one write per verdict (D14) are user decisions.

## The code (read it on disk, whole)

Python, `Isabelle_Semantic_Embedding/`:
- `semantic_interpretation.py` -- the feature's centre: constants
  (`_GATE_SIMILARITY`, `_PREFILTER_TIMEOUT_S`, `_JUDGE_SESSIONS`,
  `_JUDGE_SYSTEM_PROMPT`), the entity states `_NOT_ENROLLED … _DONE`,
  `RunState` / `_locked_run` / `current_run_state`, `CostSummary` / `_NO_COST`,
  `AgentTask` (queue, `next_batch`, `batch_size`, `max_stalled_retries`,
  `run_cost`), `InterpretationTask` (`enqueue`, `on_answer`, `start_gate`,
  `gate_finished`, `n_interpreted`, `rec_cache`, `results`, `judge_cost`),
  `JudgeTask`, `mk_answer_tool`, `mk_verdict_tool`, the query tool's refusal,
  `_report`, `_retry_unanswered`, `_stop_if_cancelled`, `_run_agent` (the
  queue loop with its recycle arms), `_first_failure`, `_note_on_failure`,
  the gate section (`_Verdict`, `_cosine`, `_prefilter`, `_judge`, `_write`,
  `_propagate`, `_gate`, `_EffStar`), the scan inside `interpret_file`
  (local staleness, theory-internal graph and reverse graph, seed set, dry
  run count, statement refresh), `interpret_file`'s live branch (driver,
  emb_store, judge driver factory, task, cost lines), the RPC shims
  (`interpret_file`, `interpret_file_dry_run`, `check_embedding_service`,
  `try_acquire_interpretation_lock`).
- `semantics.py` -- `SemanticRecord` / the 15-field record and its codec,
  `Semantic_DB` (`get_many`, `counter_snapshot`, `counter_value`, the
  gate-related writes: `Gate_Writer` / `gate_write` / `put_interpretation` /
  `update_gate_fields`, `_put_fields`, the shared assert helper), eff\*
  (`eff_uk` / `eff_value`), `_resolve_embedding_config(warn=)`,
  `_conn_semantic_vector_store(warn=)`, `Semantic_Vector_Store.__init__`'s
  registry, `update_interpretations` (how the ML callback's result is used),
  the RPC wrappers.
- `document_text.py` (`entity_document_text`, what the prefilter embeds),
  `semantic_embedding.py` (`_embed_tracing_gated`, `make_embedding_provider`,
  `Embedding_Provider.__init__`), `embedding_config.py` (`Missing_Dimension`,
  `dimension`), `snapshot_sync.py` (`INTERPRETATION_LOCK_NAME`,
  `_install_lock`), `interpretation_driver/__init__.py` (`SERVER_NAME`,
  `cli_tools`), `interpretation_driver/claude_code.py` (`_CLI_BUILTINS`,
  `_options`, the permission hook), `codex.py`, `mcp_server.py`.

Isabelle/ML, `Tools/`:
- `semantic_store.ML` -- the signature; `enumerate_entries` and the wire
  entries (digest, deps); `interpret_file_callbacks`, `send_for_interpretation`,
  `interpret'`, `interpret_cone`, `schedule_dag`; `try_acquire_cmd`,
  `with_interpretation_lock`, `check_embedding_service`, the `local … in …
  end` around `interpret_with_parallel'` / `interpret_with_parallel`,
  `lock_busy_error`, `interpret`, `make_interpret_theory_callback` (the
  callback arm), `dry_run` / `dry_run'` / `dry_run_payload`; `interpretation_driver`
  (the config option).
- `interpret_command.ML` (`run_semantic_interpretation`: dry run, dialog,
  `go ()`, the embed phase), `semantic_interpretation_app.ML` (the collect
  app), `semantic_digest.ML` (`semantics_of`: digest and deps -- read for
  what the wire carries, not for re-review of the digest itself).

Isabelle_RPC (`/home/qiyuan/Current/MLML/contrib/Isabelle_RPC/`):
- `Isabelle_RPC_Host/rpc.py` -- `Connection` (`current`, `set_current`,
  `callback`, `config_lookup`, `warning`/`writeln`, `on_close`/`_closed`/`close()`,
  `__aexit__`), `IsabelleError`, `IsabelleInterrupt`, `handle_client` (the
  dispatch loop, the 3 s grace period, the `finally`), `Server`.
- `Tools/RPC.ML` -- `mk_callback` (the `on_interrupt` policy, the
  uninterruptible body), `call_command` / `call_command'`, `get_connection` /
  `release_connection` / `close_connection`, `connection_pool`, the
  `\<^try>…finally` idioms.

Tests (all pytest under `archive/tests/`, run from the repo root):
`test_semantic_change_gate.py` (37: the gate end to end),
`test_semantic_change_gate_storage.py` (22: record field, codec, gate
writes, counter, crash shapes, arities), `test_eff_star.py` and
`eff_reference.py` (the ported verification), `test_interpretation_lock.py`
(7), `test_interpretation_driver.py`, `test_interpretation_mcp_server.py`,
`test_update_interpretations.py`, `test_auto_embed_gate_off.py`,
`test_interpretation_config.py`, `test_interpretation_codex.py`,
`test_interpretation_error_classifier.py`.  ML under `Test/`:
`Interpretation_Driver_Config_Test.thy`, `Interpretation_Lock_Test.thy`
(both run through a REPL server by the implementer; you cannot run them).

## Suite

    cd /home/qiyuan/Current/MLML/contrib/Semantic_Embedding && \
    python -m pytest archive/tests/ -q -p no:cacheprovider --continue-on-collection-errors

→ 399 passed, 16 failed: 13 in `test_agent_dir_packaging.py` (skills
packaging, another agent's area, failing before this feature) and
`test_config_resolution` ×2 + `test_embedding_provider_refactor::test_fireworks_qwen`
(pre-existing, unrelated).

## What is still owed after this review (not defects)

Step 8: §12 texts to their sites (e.g. §12 #5 today lacks the
`[Semantic_Embedding]` prefix; #7/#13–#16 wording), §11 docs
(CHECK_OUTDATE_PLAN.md sections, the comment sites listed there,
`doc/invalidation_limitations.md` #7, README §5).  The §10 items that need
a live service (the non-LLM regression on `pairs_phase2.json`, the
interactive scaffold, a live run's host log) are the user's call, after.

## Project rules that bind the review

- Elegance is a review criterion equal to correctness: a shape that makes an
  invariant impossible to violate beats one that asks people to remember it.
  Reject dirty hacks.
- Reuse code; never reinvent; consistent terminology (the plan's §0
  glossary).  Comments in code short and load-bearing.
- Nitpicking (style-only remarks, hypotheticals with no concrete failure,
  restating the plan, "consider adding a comment", re-raising a settled
  decision or a previous ruling) is to be rejected harshly and named as
  such.
- If slightly relaxing one of the user's constraints or design decisions
  would make the code markedly simpler or more elegant, say so explicitly as
  a PROPOSAL for the user — do not smuggle it in as a bug.

## What changed since the integration review (rulings of `judge.json`, applied 2026-09-12)

`working_tree.diff` is the current `git diff` against `b16ab80`.  Out of
scope in it: `Tools/entity_position.ML` and `archive/tests/test_migrate_from_collection.py`
(another agent's uncommitted edits).  The user's decisions on the two
proposals: **P1 (narrowing `update_gate_fields`) REJECTED** -- the
five-field writer stays; **P2 accepted as option A**, now D19.  The user
also replaced the judge's fix for flow-INT-1 with a stronger rule, now D18.

1. **flow-INT-1 → D18 (fix-then-rereview).**  Not the judge's
   enrolment-keyed predicate: the user ruled that inside a session NO stored
   interpretation of the theory being interpreted is disclosed, enrolled or
   not (an entity enrolled by a later CHANGED verdict could have been read
   before enrolment).  `AgentTask.theory_keys: frozenset[bytes]` is fixed at
   construction from `entries`; `enrolled_names` is deleted (its only use was
   the old refusal).  `mk_query_by_name_tool(connection, *, hidden_keys=frozenset(), …)`
   refuses on the RESOLVED key at all three disclosure points (name lookup,
   `_try_resolve_syntax_token` -- which now takes `hidden_keys` and answers
   the notation resolution without the text -- and the short-name fallback);
   the name-keyed early check is gone.  `mk_desugar_and_explain_tool(…,
   hidden_keys=frozenset())` annotates a hidden constant with "(belongs to
   the theory being interpreted; read its definition from the source)" and
   does not count it as seen.  Both defaults keep every other caller
   unchanged (the package export `query_by_name_tool`).  Tool texts
   changed accordingly (agent-facing; not §12).  Tests:
   `test_the_lookup_tools_hide_every_entity_of_the_theory_being_interpreted`
   (enrolled b, not-enrolled d via the short-name fallback, a glyph
   resolving to b's key, the desugar annotation; a foreign entity served)
   and `test_the_query_tool_refuses_by_the_resolved_key_in_either_spelling`.
   Plan: D18 row; §15.8's addressing paragraph rewritten; §10 bullet.
2. **interrupt-INT-1 (fix).**  `_stop_if_cancelled` logs the laundered
   exception and raises `asyncio.CancelledError()`; docstring rewritten.
   Test: `test_a_cancellation_laundered_by_the_judge_s_teardown_still_writes_nothing`
   (`_LaunderingJudge`).  Plan: §15.1 row, §15.4 paragraph.
3. **storage-S2 (fix).**  `update_gate_fields` binds its dict and checks
   THAT through `_check_raw_put_grant("update_gate_fields", fields)`;
   `_GATE_FIELDS` and the check in `gate_write` deleted.  Test retargeted
   (direct checks + the writer's routing pinned through a recorded
   `_check_raw_put_grant`).
4. **ml-ML-INT-1 (fix).**  The acquire in `with_interpretation_lock` converts
   `Remote_Calling_Failure` through `interpretation_rpc_error` inside the
   `\<^try>` body (the finaliser still closes the connection).  Plan §8.2's
   block edited.  Both ML tests re-run through the REPL server: pass.
5. **elegance-INT-2 (fix).**  `InterpretationTask.format_entries` calls
   `_label(e)`; the `answer` schema's `type` enum is
   `list(_KIND_PROMPT_LABELS.values())`; the NB comment shrank.
6. **P2 → D19.**  `_statement(e, rec)` = the wire `prop_str` or, when "",
   the stored `expr`; used by `_write` (`expr=_statement(e, rec)`) and by
   `_refresh_statements` (rewrite iff it differs from the stored `expr`).
   Test: `test_an_empty_wire_statement_keeps_the_stored_one` (dry path,
   record byte-identical).  Plan: D19 row; §15.8 item 8 rewritten.
7. **tests-F5, tests-F7 (fix, tests).**  `test_an_entry_answered_before_its_batch_goes_out_is_not_re_sent`
   and `test_the_rate_limit_backoff_doubles_caps_jitters_and_resets`
   (`[2, 4, 8, 16, 32, 60, 2]`, `uniform(0.5, 1.5)` each time) in
   test_interpretation_driver.py.  Plan §10 bullet extended.
8. **elegance-INT-4** deferred to step 8 (the judge's own suggestion).
9. Rejected, unchanged: storage-S1, ml-ML-INT-2, elegance-INT-1, -5, -6,
   tests-F2.

Mutation checks (each reverted alone fails a test): the desugar hiding,
the query tool's main path, its notation fallback, its short-name fallback,
the bare `raise`, the writer's grant routing, `_statement` returning the
bare wire text, the `_QUEUED` guard, `throttled = 0`.  Suite: 403 passed,
the same 16 pre-existing failures.

### What the re-review is asked to judge

(a) D18 as shipped: every site inside an interpretation session that reads
a stored interpretation goes through `hidden_keys` on the RESOLVED key --
grep for `Semantic_DB.query(`, `query_by_name_raw(`, `.interpretation`
reads reachable from the agent's tools (`query`, `desugar_and_explain`,
`definition`, `hover`) and confirm nothing else discloses; `theory_keys`
covers exactly the theory's entries (what about the `Context.Proof` root's
proof-local entities -- are they in `entries`?); the agent-facing texts
make sense; no other caller of the two factories changed behaviour.
(b) `_stop_if_cancelled`'s new shape: the CancelledError propagates through
`_judge`, `_gate`, the task group, `_first_failure` (CancelledError leaves
are dropped there -- does `interpret_file` still end as a cancellation?),
and the interpretation `_run_agent`; the log line is not noise on the
normal path.  (c) S2, INT-2, ML-INT-1, D19: correct and minimal; `_statement`
on a first write with no record.  (d) The plan edits describe the code.
(e) The new tests pin what they claim (the mutation list above) and the
harness stubs do not bypass the real code path (the notation callback stub
answers every pattern; `raw` stubs the ML lookup).  Do not re-open the
integration judge's rulings or the user's decisions (P1 rejected, D18, D19).

## Round two: what changed since the re-review (rulings of `rereview_judge.json`, applied 2026-09-12)

`working_tree_v2.diff` is the current `git diff` against `b16ab80` (same
out-of-scope files as before).  Suite: 405 passed, the same 16 pre-existing
failures; both ML tests pass through the REPL server on the rebuilt heap.

1. **d18-D18-1 (blocker, fix-then-rereview) → the ML hint.**  In
   `build_entries` (Tools/semantic_store.ML) the run's own keys are dropped
   before the store is consulted: `val own_uks = Bytehashtab.make_set (map #4 raw)`
   and `|> filter_out (Bytehashtab.defined own_uks)` on `wanted_uks`, with a
   two-line D18 comment.  So `available` never holds a key of this run's
   entries, `sem_of` returns NONE for them, and the hint keeps its head, the
   template's current proposition and the provenance note; a locale of a
   parent theory (not in `raw`) is unchanged.  The user ruled the hint's
   behaviour for other theories must NOT change and the system prompt must
   NOT change (d18-D18-2 withdrawn as a nitpick: the tool description and
   the refusal message carry the rule).  Plan: D18 row ("an entity this
   run enumerated for that theory"), §15.8 addressing paragraph (the third
   disclosure point), §10 D18 bullet.
2. **cancel-stop-if-cancelled-per-arm (fix).**  `_judge`'s `except Exception`
   calls `_stop_if_cancelled()` first; the helper's docstring names its
   second call site.  Test: `test_a_cancellation_laundered_into_a_fatal_error_still_writes_nothing`
   (a judge whose teardown raises `FatalAgentError` -- the one non-recovering
   arm of `_run_agent`); reverting the line fails it.
3. **d18-D19-4 / tests-D19-WRITE (fix, test).**  `test_an_empty_wire_statement_keeps_the_stored_expr_on_the_gate_s_write`
   added; §10 D19 bullet extended.
4. **cancel-d19-prefilter-statement (fix).**  The docstring option: `_prefilter`'s
   docstring now says "each under the wire statement" (no code change; the
   two documents share their header line, so the cosine is unaffected).
5. **d18-D18-3 (fix).**  `_try_resolve_syntax_token` binds the three-line
   prefix once and chooses the tail (hidden / stored / not yet interpreted);
   behaviour identical; `show_defs` is still appended after the choice.
6. **d18-D19-5 / cancel-d19-stale-write-comment (fix).**  The refresh call
   site's comment names `_statement`.
7. **Plan leftovers (all fix).**  §3 (:146), §5.3.2, §10 crash-shapes and
   D19 bullets, §15.2 listing (`theory_keys`), §15.3 listing (`enrolled_names`
   deleted), §15.10 mirror sentence -- all edited by hand.
8. **agreement-plan-D18-PROOF-ROOT** folded into the D18 row wording.

### What this round's re-review is asked to judge

(a) The ML hunk: `own_uks` built from `raw` (the 4-tuples of this run's
entries), the filter on `wanted_uks`, the comment; that `available` /
`sem_of` / `mk_instance_hint` need no other change; that a parent-theory
locale's hint is byte-identical to before; that the dry-run path (which
shares `build_entries`) is unaffected in what it returns.  (b) EXHAUSTIVE:
is there any FOURTH path by which a stored interpretation of this run's own
entries can reach the agent -- grep both repositories for every reader of
`interpretation` / `Semantic_DB.query` / `query_semantics` / `sem_of` that
feeds a prompt, a tool reply, a hint, a wire field the Python side prints
(`prompt_extra`, `pretty_prints`, the retry prompt, the answer tool's reply,
the judge prompt); state each and whether it is closed.  (c) The `_judge`
guard and its test; the docstring/comment edits; the notation-prefix
rearrangement (behaviour identical, `show_defs` intact).  (d) The plan
edits describe the code.  Do not re-open the rulings or the user's
decisions (P1 rejected; D18; D19; the hint's behaviour for other theories
and the system prompt stay as they are).

## Outcome of round two (`rereview2_judge.json`, 2026-09-12): ACCEPTABLE; four minor repairs applied in the same change set

`working_tree_v3.diff` is the final `git diff` against `b16ab80`.  Applied:
(a) `_collapse_provenance` keys on the head line alone (docstring updated;
test `test_sibling_facts_collapse_on_the_head_line_when_the_locale_line_is_absent`,
mutation-checked); (b) `_try_resolve_syntax_token`'s hidden branch returns
early again, one predicate, no dead binding; (c) `sem_of` refuses the run's
own keys at the disclosure point, the list filter kept for the round trip
(comments moved accordingly); (d) plan §15.8, §15.5 and §10 edited.  The
CLI built-ins channel (PATH 20) is recorded, not closed, per the ruling.
Suite: 408 passed, 16 pre-existing failures; both ML tests pass on the
rebuilt heap.  Also added, outside the review's scope: the free §10
acceptance item `test_prefilter_regression_phase2.py`.
