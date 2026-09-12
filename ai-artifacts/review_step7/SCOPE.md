# Review scope: semantic change gate, implementation step 7 (the interpretation lock)

All paths are relative to `contrib/Semantic_Embedding/` (absolute root:
`/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/`); the sibling
repository `contrib/Isabelle_RPC/` (`/home/qiyuan/Current/MLML/contrib/Isabelle_RPC/`)
is touched too.  Do not modify any file.  You may run pytest (command
below); never run `isabelle build`; never start, connect to, or kill any
Isabelle process (an Isabelle REPL server of the implementer's is listening
on 127.0.0.1:6702 -- leave it alone, and leave every other Isabelle process
alone too); never point anything at the real cache (`SEMANTIC_DB_DIR` must
be a throw-away directory in every probe).

## What is being reviewed

The plan is `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` (rev 5.4,
authoritative; §0 glossary fixes the vocabulary; §2 lists the user's settled
decisions D1–D17 -- do not re-open them).  Its §13 lists eight implementation
steps.  Steps 1–6 are reviewed, accepted and committed (`8683e6f`, `5a3c201`,
`0d279d7`, `aa5b93c`; review records under `ai-artifacts/review_step3/` …
`review_step6/`).  **Step 7 is what you review now**: §13 item 7, "Lock:
Python procedure + `Connection.on_close` + ML `with_interpretation_lock` +
the four call sites (§8)".  Specification: §8 (8.1 Python side incl. the
release-ordering paragraph, 8.2 ML side with the code block, 8.3 scope), D8
(try once, never wait; who skips, who errors; a dry run is never locked),
D17 (the exported `interpret` reuses text §12 #2), §12 #1–#3 (the three
approved lock-busy texts -- verbatim), §15.8 "Run-scoped state" (the lock
creates the `RunState`; `current_run_state()` is the holder's while a run
holds the lock; the step-6 startup check's flag now reaches the run), §10's
lock lines ("ML: the three `NONE` behaviours of the lock; interrupt during
the acquire round trip leaves the next acquire succeeding"; "lock: two
processes on one `SEMANTIC_DB_DIR`; two instances in one process"), §11's
limitation corner (documentation, step 8 -- not code).

`working_tree.diff` is `git diff` against the step-6 commit (`aa5b93c`) for
the Semantic_Embedding files; `isabelle_rpc.diff` is the Isabelle_RPC
working tree's diff of `Isabelle_RPC_Host/rpc.py`, `rpc.pyi` and
`Tools/RPC.ML` -- NB that diff ALSO carries another agent's uncommitted
interrupt work (`IsabelleInterrupt`, `on_interrupt`, …); step 7's part is
only `Connection.on_close` / `_closed` / `close()` in rpc.py, the `on_close`
line in rpc.pyi, and the `close_connection` signature entry in RPC.ML.  Do
not review the rest.  Read the files on disk for the full picture:

- `Isabelle_RPC/Isabelle_RPC_Host/rpc.py`: `Connection.__init__` (the two
  new fields), `close()`, `__aexit__`, `handle_client`'s `finally`;
  `Isabelle_RPC/Tools/RPC.ML`: `close_connection`, `get_connection`,
  `release_connection`, `call_command` / `call_command'`, the
  `\<^try>\<open>… finally …\<close>` and `Thread_Attributes.uninterruptible`
  idioms (the lifeline code around :805-840), `connection_pool`.
- `Isabelle_Semantic_Embedding/semantic_interpretation.py`: the imports
  (`filelock`, `semantic_DB_dir`, `INTERPRETATION_LOCK_NAME`), `RunState`,
  `_locked_run`, `current_run_state`, `_try_acquire_interpretation_lock`
  (RPC `Semantic_Store.try_acquire_interpretation_lock` → bool), and, for
  what consumes it, `interpret_file`'s `run_state = current_run_state()` and
  `_check_embedding_service` (step 6).
- `Isabelle_Semantic_Embedding/snapshot_sync.py`: `INTERPRETATION_LOCK_NAME`
  beside `INSTALL_LOCK_NAME`, and `_install_lock` (the precedent).
- `Tools/semantic_store.ML`: the signature entries (`interpret_with_parallel`
  now `… -> unit option`, `with_interpretation_lock`, `lock_busy_error`),
  `try_acquire_cmd`, `with_interpretation_lock`, `interpret_with_parallel'`
  (the former body) and `interpret_with_parallel` (the wrapped one),
  `lock_busy_error`, `interpret`, the callback arm in
  `make_interpret_theory_callback`; `Tools/interpret_command.ML` `go ()`;
  `Tools/semantic_interpretation_app.ML` the collect app; `dry_run` (must
  stay unwrapped).
- Tests: `archive/tests/test_interpretation_lock.py` (new) and
  `Test/Interpretation_Lock_Test.thy` (new, listed in `Test/ROOT`).

### Step 7 deliverables (what changed)

Isabelle_RPC
- `Connection.on_close: list[Callable[[], None]]` and `_closed`; `close()` is
  idempotent, runs every `on_close` callback once (a raising callback is
  logged, the rest still run), then closes the writer.  `rpc.pyi` typed.
- `REMOTE_PROCEDURE_CALLING` exports `close_connection`.

Python
- `INTERPRETATION_LOCK_NAME = ".interpretation.lock"` (snapshot_sync.py).
- `_try_acquire_interpretation_lock`: `FileLock(<semantic_DB_dir()>/name,
  timeout=0, thread_local=False)` (directory created as `_install_lock`
  does); `Timeout` ⇒ False; else a fresh `RunState` becomes `_locked_run`,
  and `connection.on_close` gets a `release` closure that clears the slot
  (only if it still holds this run) and releases the lock ⇒ True.
- `current_run_state()` returns `_locked_run` when set, else a fresh
  `RunState` (the off-lock scope of §15.8, unchanged).

ML
- `try_acquire_cmd` (unit → bool, no callbacks); `with_interpretation_lock`
  per §8.2's code block (finaliser armed first; `Thread_Attributes.uninterruptible
  (fn run => fn () => …)` around connect-and-record with `get_connection`
  under `run`; the connection is CLOSED in the finaliser, never released to
  the pool); `interpret_with_parallel` = the old body renamed
  `interpret_with_parallel'` wrapped in it ⇒ `unit option`; `dry_run`
  untouched.
- The four `NONE` sites: the callback arm (`writeln` §12 #1, still returns
  `([], ~1)`); `interpret_command.ML`'s `go ()` (`error
  Semantic_Store.lock_busy_error` = §12 #2); the collect app (`error` §12
  #3); the exported `interpret` (`error lock_busy_error`, D17).

Tests
- Python (7): two instances in one process exclude each other until the
  holder closes (and a refusal returns within 0.5 s -- D8's "never wait");
  the holder's `RunState` is `current_run_state()` for every call until
  release, then a fresh one; the step-6 startup check's flag reaches the run
  through the lock (§15.8); two processes on one directory (a daemon child
  holding a `FileLock`, both directions); a killed holder leaves no stale
  lock; the real `Connection.close()` runs every callback once across a
  second `close()` and `__aexit__`, a raising callback does not stop the
  rest, the writer is closed once.
- ML (`Interpretation_Lock_Test.thy`, run through the REPL server whose
  attached host had `SEMANTIC_DB_DIR` pointed at a scratch directory; the
  host log confirms the lock file lived there): the primitive takes and
  gives back twice in a row; under a held lock a nested attempt is `NONE`
  at once and `Semantic_Store.interpret` raises exactly `lock_busy_error`
  (§12 #2), and the lock is free afterwards; an interrupted holder thread
  (forked with interrupts enabled, `Exn.capture` records "interrupted",
  join within 10 s) releases through its closed connection and the next
  acquire succeeds -- the host log shows the release ~1 s after the
  interrupt, not after the 30 s sleep.  The callback arm's `writeln` (#1)
  and the collect app's `error` (#3) are not driven by a test (they need a
  Python caller / the REPL app protocol); `interpret_command.ML`'s arm
  shares the constant with `interpret`, which is driven.
- Mutation checks (each reverted alone fails at least one Python test): no
  release on close; run state not registered; run state not cleared;
  `timeout=1` instead of 0; `close()` not idempotent; a failing callback
  stopping the rest.

### Derivations the implementer made (not literally in the plan — judge them)

1. The run's `RunState` is registered in a module-level slot `_locked_run`
   (one host serves one database directory; the lock admits one run), and
   the FileLock lives only in the `release` closure appended to
   `connection.on_close`.  The plan says "stores the FileLock and the run's
   `RunState` on the `Connection`": nothing else is stored on the connection
   object -- the closure IS the ownership.
2. `close()` runs the `on_close` callbacks BEFORE closing the writer, and a
   callback that raises is logged through `server.logger.exception` while
   the others still run.  The plan only says "run by `close()` at most once".
3. `lock_busy_error` (§12 #2) is one exported constant, used by both
   `interpret` and `interpret_command.ML`, rather than the literal written
   twice (D17 says `interpret` reuses #2 "deliberately").
4. The unwrapped body keeps its old text and is renamed
   `interpret_with_parallel'`; the exported name is the wrapped one, so no
   caller changes its call except for the `unit option` result.
5. §12 #1 is printed with `writeln` inside the callback arm and the arm
   still returns `([], ~1)`, as the plan says ("a convention only").
6. The ML interrupt test interrupts the holder's BODY, not the acquire
   round trip (§10's wording): the round trip cannot be hit deterministically
   from a test; the finaliser-armed-first structure is what covers it, and
   the body-interrupt case exercises the same release path (the socket).
7. `_holder_process` children are daemons and are terminated in `finally`:
   a failed assertion in the parent must not leave a child blocking the
   interpreter's exit (it did, once).
8. The acquire creates the database directory (`os.makedirs(exist_ok=True)`),
   as `_install_lock` does -- a run on a fresh directory would otherwise fail
   before the store is even opened.
9. The Python tests of `Connection.close()` live in Semantic_Embedding's
   lock test file (its consumer), not in Isabelle_RPC's test directory.
10. `filelock` 3.25 deletes the lock file on release (observed); nothing in
    the code relies on the file persisting.
11. `thread_local=False` as the plan says; the acquire runs on the event
    loop thread and the release runs from `close()` on the same loop, so
    the flag is belt-and-braces.

## Suite

    cd /home/qiyuan/Current/MLML/contrib/Semantic_Embedding && \
    python -m pytest archive/tests/ -q -p no:cacheprovider --continue-on-collection-errors

→ 399 passed, 16 failed: 13 in `test_agent_dir_packaging.py` (skills
packaging, another agent's area, failing before this step) and
`test_config_resolution` ×2 + `test_embedding_provider_refactor::test_fireworks_qwen`
(pre-existing, unrelated).  `test_interpretation_lock.py` alone: 7 passed.

## Project rules that bind the review

- Elegance is a review criterion equal to correctness: a shape that makes an
  invariant impossible to violate beats one that asks people to remember it.
  Reject dirty hacks.
- Reuse code; never reinvent; consistent terminology (the plan's §0
  glossary).  Comments in code short and load-bearing.
- Nitpicking (style-only remarks, hypotheticals with no concrete failure,
  restating the plan, "consider adding a comment", re-raising a settled
  decision D1–D17 or a ruling of the step-3 … step-6 reviews, or the user's
  declined proposals: the `embed_tracing_gated()` context manager, a
  `run_config` record, rewording §12 #4) is to be rejected harshly.
- If slightly relaxing one of the user's constraints or design decisions
  would make the code markedly simpler or more elegant, say so explicitly as
  a PROPOSAL for the user — do not smuggle it in as a bug.

## What changed since the first review (the rulings of `judge.json`, all applied 2026-09-11)

`working_tree_v2.diff` is the current `git diff` against `aa5b93c` (same
files plus `pyproject.toml` and the plan).  The judge's rulings and what was
done:

1. **ml-S7-ML-1 (fix-then-rereview, test)**: `Interpretation_Lock_Test.thy`
   block 3 rewritten: one state variable (`Not_started | Holding | Done of
   string`), every wait a `Synchronized.timed_access` with a deadline
   computed once (20 s to reach `Holding`, 10 s to reach `Done`), the
   outcome distinguishes finished / refused / interrupted / failed; a
   `free_within` helper (bounded retry, 5 s) replaces the two "free again"
   assertions, since the release is asynchronous to the ML caller (the host
   runs it at EOF).  Run through the REPL server after the change: passes.
2. **ml-S7-ML-2 (fix, test)**: block 2 checks the nested refusal INSIDE the
   holder's body, before calling `Semantic_Store.interpret`, with an `error`
   naming the reason; the body returns only the error text.
3. **py-S7-PY-1 (fix, test)**: the `_acquire` helper pins "a refusal leaves
   `_locked_run` where it was" for every refusal in the file.
4. **agreement-S7-01 (fix; the user left the ROOT question to the
   implementer)**: the theory stays in `Test/ROOT`; its header now states
   what is true (writes nothing; the lock file is the only artefact;
   test-exclusivity discipline as for Test_All; a scratch `SEMANTIC_DB_DIR`
   removes the coupling).
5. **agreement-S7-02 (fix, plan)**: §8.1's ownership sentence rewritten by
   hand (closure + module slot; why the slot; `on_close` semantics; the
   asynchronous release).
6. **agreement-S7-06 (fix, approved)**: `interpret_with_parallel'` is now
   inside `local … in … end` with `interpret_with_parallel` as the only
   export.
7. **agreement-S7-07 (fix, approved)**: `Thread_Attributes.uninterruptible_body
   (fn run => …)` in `with_interpretation_lock`; plan §8.2's code block and
   prose edited by hand accordingly.
8. **agreement-S7-09 (fix, test)**: the same-process "other way round" lines
   deleted from the two-process test.
9. **agreement-S7-10 (fix, approved)**: `RunState`'s docstring is timeless.
10. Rejected (no change): agreement-S7-05, agreement-S7-08, agreement-S7-12.
11. User decisions: commit sequencing (a) -- wait for the other agent's
    interrupt work to land in Isabelle_RPC, then commit step 7 on top; the
    version floor: v0.5.0 is not to be tagged before `on_close` is in, and
    pyproject.toml's floor comment names `Connection.on_close` (edited).

Suite after the fixes (repo root): 399 passed, the same 16 pre-existing
failures.  `test_interpretation_lock.py` alone: 7 passed.  Both ML tests
pass through the REPL server on the rebuilt heap.

### What the re-review is asked to judge

Only: (a) the rewritten ML test -- bounded waits (is every wait really
bounded; is the deadline computed once; can the theory still wedge; does
`free_within` mask a real release failure or is 5 s the right bound; does
block 2 refuse safely before the live call), (b) the `local … in … end`
hiding and the `uninterruptible_body` change in `with_interpretation_lock`
(compiles -- it did; semantics identical), (c) the plan §8.1 / §8.2 edits
describe the code, (d) the Python test additions (the `_acquire` pin), (e)
nothing regressed.  Do not re-open the first review's rulings or the user's
decisions.
