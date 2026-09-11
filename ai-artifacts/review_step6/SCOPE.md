# Review scope: semantic change gate, implementation step 6 (the `Config.lookup` callback and the startup check)

All paths are relative to `contrib/Semantic_Embedding/` (absolute root:
`/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/`).  Do not modify any
file.  You may run pytest (command below); never run `isabelle build`; do
not start or touch any Isabelle process (an Isabelle REPL server of the
implementer's is listening on 127.0.0.1:6702 -- leave it alone, and leave
every other Isabelle process alone too).

## What is being reviewed

The plan is `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` (rev 5.4,
authoritative; §0 glossary fixes the vocabulary; §2 lists the user's settled
decisions D1–D17 -- do not re-open them).  Its §13 lists eight implementation
steps.  Steps 1–5 are reviewed, accepted and committed (`8683e6f`, `5a3c201`,
`0d279d7`; review records under `ai-artifacts/review_step3/`, `review_step4/`,
`review_step5/`).  **Step 6 is what you review now**: §13 item 6, "`Config.lookup`
callback with `cfg_context`; startup check RPC (§5.6)".  Specification:
§5.6 (both paragraphs), D5, D16, §12 #4 (the one user-visible text of this
step), §15.8 "Run-scoped state" (the paragraph on the startup check and the
`warn` threading; note its statement that until step 7 `current_run_state()`
returns a fresh `RunState` per call), §5.4 step 2's first sentence, §10's two
lines "`"Config.lookup"` among interpret_file's callback names" and "an
unconfigured embedding service (startup check failed) completes the run with
every gate judged and no error", and §15.11's "After step 6" bullet if there is
one.

`working_tree.diff` is `git diff` against the step-5 commit (`0d279d7`) for
the touched files.  NB the two `on_interrupt = Remote_Procedure_Calling.Reraise,`
hunks in `Tools/semantic_store.ML` (`Semantic_Store.excluded_theory_names`,
`Semantic_Store.interpret_theories`) are ANOTHER agent's uncommitted edit that
happens to sit in the same file -- not part of step 6, do not review them.
Read the files on disk for the full picture:

- `Tools/semantic_store.ML`: the signature entry `interpret_file_callbacks`;
  `interpret_file_callbacks`, `send_for_interpretation`, `interpret'`,
  `interpret_cone`, `check_embedding_service`, `interpret_with_parallel`;
  for the existing pattern `embed_all_missing` and `query_knn` (both carry
  `Config.make_config_lookup_callback (Context_Callbacks.static_context_unpacker
  context)`), and `make_interpret_theory_callback` (how `cfg_context` reaches
  `interpret_with_parallel` from Python's `Semantic_Store.interpret_theories`
  callback).  `Config.make_config_lookup_callback` is in
  `../Isabelle_RPC/Tools/config.ML`; `Context_Callbacks.static_context_unpacker`
  is `Universal_Key.static_context_unpacker` (`../Isabelle_RPC/Tools/context.ML:186`).
- `Isabelle_Semantic_Embedding/semantics.py`: `_resolve_embedding_config`
  (gains `warn`), `_conn_semantic_vector_store` (threads it),
  `_missing_api_key_message`, `Semantic_Vector_Store.__init__`'s registry
  block, `make_embedding_provider` and `Embedding_Provider.__init__` in
  `semantic_embedding.py` (the dimension lookup in `embedding_config.py`).
- `Isabelle_Semantic_Embedding/semantic_interpretation.py`: the import
  block, `RunState` / `current_run_state`, `_report`, `interpret_file`'s
  `emb_store` resolution, and the new RPC shim `_check_embedding_service`
  (`Semantic_Store.check_embedding_service`) beside `_interpret_file`.
- `../Isabelle_RPC/Isabelle_RPC_Host/rpc.py`: `Connection.current` /
  `set_current` (contextvar), `config_lookup` ("Config.lookup"), `warning`.
- Tests: `Test/Interpretation_Driver_Config_Test.thy` (the new last ML block)
  and `archive/tests/test_semantic_change_gate.py` (`_Connection` gains
  `warn` recording; `_ConfigConnection`; `_Run.start` gains `run_state=`;
  the section "the startup check (§5.6, D16)").

### Step 6 deliverables (what changed)

`Tools/semantic_store.ML`
- `interpret_file_callbacks cfg_context context`: the callback list of a
  live interpret_file RPC, factored out of `send_for_interpretation` and
  exported; it now carries `Config.make_config_lookup_callback
  (Context_Callbacks.static_context_unpacker cfg_context)` (one entry, served
  from the user's context, D5) beside the entity callbacks served from the
  node's context.
- `send_for_interpretation driver cfg_context context payload`,
  `interpret' driver cfg_context context`, `interpret_cone driver cfg_context
  force cone`: `cfg_context` threaded beside `driver`, no wire change;
  `interpret_with_parallel` passes it down both paths (the cone and the
  `Context.Proof` roots).
- `check_embedding_service cfg_context`: one RPC
  `Semantic_Store.check_embedding_service` (unit → unit) carrying the same
  `Config.lookup` callback; `Remote_Calling_Failure` → `interpretation_rpc_error`
  like `send_for_interpretation`.  Called once in `interpret_with_parallel`,
  after the opening block and before `interpret_cone`, only when `n_units > 0`.

`semantics.py`
- `_resolve_embedding_config(connection, *, warn=True)`: the missing-key
  warning is sent iff `warn`; the exception is raised either way.
- `_conn_semantic_vector_store(self, embedding_model=None, *, warn=True)`
  threads `warn`.

`semantic_interpretation.py`
- `interpret_file` resolves its store with `semantic_vector_store(warn=False)`.
- `_check_embedding_service(arg, connection)`: `_resolve_embedding_config(
  connection, warn=False)`, then `make_embedding_provider(driver, base_url,
  model, api_key)` (constructed and discarded: the dimension lookup is the
  validation); on any `Exception`: host-log warning with the traceback,
  `current_run_state().prefilter_disabled = True`, `_report("[Semantic_Embedding]
  The embedding service is not configured: <str(exc) or type name>", warn=True)`.

Tests
- ML: `Test/Interpretation_Driver_Config_Test.thy` asserts `"Config.lookup"`
  is on `Semantic_Store.interpret_file_callbacks ctx ctx` exactly once.  Run
  through the REPL server: passes; a negative probe (asserting
  `"Config.lookupX"`) fails with "Assertion failed" at that line.
- Python, `test_semantic_change_gate.py` (37 tests, +4): the startup check
  on a stub connection whose `config_lookup` answers, bound as the current
  connection, against a `RunState` of the test's, with the embedding
  environment cleared: nothing configured ⇒ §12 #4 exactly once, carrying
  `_missing_api_key_message()`, flag set; a configured endpoint (base URL from
  `Config.lookup`, default model) ⇒ nothing printed, flag clear, no store
  registered on the connection; an unknown model ⇒ the provider's dimension
  lookup fails ⇒ §12 #4 once naming the model, flag set; the check's flagged
  `RunState` handed to a run ⇒ no store resolution, no embed call, every gate
  judged, the run completes (a CHANGED a, an UNCHANGED dependent b with its
  snapshot raised); `_resolve_embedding_config(warn=False)` and
  `_conn_semantic_vector_store(warn=False)` raise without warning, the default
  warns once; the existing failing-store-resolution test now asserts the run
  resolved with `warn=False`.
- Mutation checks (each reverted alone fails at least one test): the store
  resolved with `warn=True`; the check never setting the flag; the check
  skipping the provider construction; the resolution warning regardless of
  `warn`; the check calling the resolution with its warning on; the check
  reporting through writeln instead of warning; the registry not threading
  `warn`.

### Derivations the implementer made (not literally in the plan — judge them)

1. The callback list is factored into an exported `interpret_file_callbacks`
   so the ML test of §10 can assert on it without a live RPC; the plan only
   says "the list gains ...".
2. The check is skipped when `n_units = 0`: the plan says "once per cone run,
   before any theory starts"; a run with nothing to interpret starts no
   theory, has no prefilter to configure, and should not print §12 #4.
3. The check runs after the opening block's `writeln` and before
   `interpret_cone`, so the user reads "Interpreting N theories ..." and then,
   if at all, "The embedding service is not configured: ...".
4. `check_embedding_service` wraps `Remote_Calling_Failure` in
   `interpretation_rpc_error`, as `send_for_interpretation` does; a
   configuration problem never reaches ML as an error (the handler catches
   every `Exception`); only an RPC-level failure does, and it would have
   failed the first interpret_file anyway.
5. §12 #4's `<existing message with the settings hint>` slot is `str(exc) or
   type(exc).__name__` for ANY exception of the resolution or of the provider
   construction (the missing-key `RuntimeError` carries the hint; an unknown
   driver is an `ImportError`, an unknown model a `KeyError` from the
   embedding config) -- same shape as §12 #5's slot in step 5.
6. The handler sets `prefilter_disabled = True` directly rather than calling
   `claim_prefilter_disable()`: at startup nobody has claimed, and the
   "did THIS caller flip it" answer has no use here.
7. `Context_Callbacks.static_context_unpacker` is used where the plan writes
   `Universal_Key.static_context_unpacker` (the former is an alias of the
   latter and is this file's convention).
8. `warn` is keyword-only on both Python functions.
9. The handler's host-log line is at warning level with the traceback
   (`exc_info=True`), so a misconfiguration is diagnosable from the log.
10. The check resolves `current_run_state()` at the moment of the failure
    (inside the `except`), not at entry.  Until step 7 that is a fresh
    `RunState` per call, so the flag cannot reach `interpret_file` yet -- the
    plan records this (§15.8); step 7 changes only where the RunState comes
    from.
11. Test side: the RPC shim is called directly with the stub bound through
    `Connection.set_current` inside the coroutine, so `_report` reaches the
    stub's `warning` the way it reaches the live connection inside a handler.

## Suite

    cd /home/qiyuan/Current/MLML/contrib/Semantic_Embedding && \
    python -m pytest archive/tests/ -q -p no:cacheprovider --continue-on-collection-errors

→ 392 passed, 16 failed: 13 in `test_agent_dir_packaging.py` (skills
packaging, another agent's area, failing before this step) and
`test_config_resolution` ×2 + `test_embedding_provider_refactor::test_fireworks_qwen`
(API-key/config environment, pre-existing, unrelated).  Run from `archive/tests`
three more files fail on missing helper modules that live at the repo root;
run from the root as above.

## Project rules that bind the review

- Elegance is a review criterion equal to correctness: a shape that makes an
  invariant impossible to violate beats one that asks people to remember it.
  Reject dirty hacks.
- Reuse code; never reinvent; consistent terminology (the plan's §0
  glossary).  Comments in code short and load-bearing.
- Nitpicking (style-only remarks, hypotheticals with no concrete failure,
  restating the plan, "consider adding a comment", re-raising a settled
  decision D1–D17 or a ruling of the step-3 / step-4 / step-5 reviews, or the
  user's declined proposal of an `embed_tracing_gated()` context manager) is
  to be rejected harshly.
- If slightly relaxing one of the user's constraints or design decisions
  would make the code markedly simpler or more elegant, say so explicitly as
  a PROPOSAL for the user — do not smuggle it in as a bug.

## What changed since the first review (the rulings of `judge.json`, all applied 2026-09-11)

`working_tree_v2.diff` is the current `git diff` against `0d279d7` (same
files plus `Isabelle_Semantic_Embedding/embedding_config.py`).  The judge's
rulings and what was done:

1. **py-F1 (fix-then-rereview, the subject of this re-review)**: the
   `Config.lookup` callback is now built ONCE in `interpret_with_parallel`,
   beside the driver read (`val config_cb = Config.make_config_lookup_callback
   (Context_Callbacks.static_context_unpacker cfg_context)`), and that
   `Remote_Procedure_Calling.callback'` VALUE -- not the context -- is threaded
   through `interpret_cone`, `interpret'`, `send_for_interpretation`,
   `interpret_file_callbacks` (signature now `callback' -> Context.generic ->
   callback' list`) and `check_embedding_service` (`callback = [config_cb]`).
   Below `interpret_with_parallel` no function takes two contexts any more;
   the two constructions of the same expression are gone.  The ML test builds
   the callback itself and asserts `"Config.lookup"` is on the returned list
   exactly once (one assertion: "exactly once" implies membership).  Run
   through the REPL server after the change: passes.  Plan §5.6 both
   paragraphs hand-edited accordingly (also: the `n_units = 0` guard and the
   ordering after the opening block are now written down; the RPC-level
   failure policy carries the judge's corrected justification).
2. **agreement-F3 (fix)**: `embedding_config.Missing_Dimension(KeyError)`
   with `__str__` returning the message; `dimension()` raises it; the test
   `test_the_startup_check_covers_the_provider_s_construction` asserts the
   user line ends with the message's last sentence, not a quote.
3. **py-F2 (fix, test-only)**: the `check` fixture pins
   `EMBEDDING_CONFIG_PATH` to `EC._CONFIG.template_path()` and drops the
   loader's cache under monkeypatch (`_data`, `_source`), so the machine's
   embedding config is out of the tests and restored on teardown.
4. **py-F4 (proposal-for-user)**: pending the user's wording decision; not
   part of this re-review.
5. Rejected (no change): ml-ML-1, py-F3, agreement-F4.

Suite after the fixes (repo root): 392 passed, the same 16 pre-existing
failures.  `test_semantic_change_gate.py` alone: 37 passed.

### What the re-review is asked to judge

Only: (a) py-F1's fix as shipped -- correctness of the threading at every
call site (both `interpret'` paths, `interpret_cone`, the check), the
sharing of one `callback'` value across the cone's parallel RPCs
(`mk_callback`'s closure is stateless per call -- verify in RPC.ML), the
signature/comment accuracy, the ML test; (b) agreement-F3's subclass (every
`except KeyError` consumer of `dimension()` still works; `str()` and
`repr()`; nothing else in the package depended on the repr); (c) the
plan §5.6 edits describe the code; (d) nothing regressed in the Python
side (`warn` threading, the RPC shim).  Do not re-open the first review's
rulings.
