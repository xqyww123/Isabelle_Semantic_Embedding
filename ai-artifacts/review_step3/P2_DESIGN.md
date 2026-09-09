# Design change under review: the failure channel of every store write

Context: `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` rev 5.2 (authoritative;
§0 glossary), the step-3 code on disk (`Isabelle_Semantic_Embedding/
semantic_interpretation.py`, `semantics.py`), and the first review's report
`ai-artifacts/review_step3/REPORT.md` (findings F1, F2, F3, F4, F10 and the
second proposal are the background).  This note is what the user decided
after that review, on 2026-09-08.  It is NOT yet in the plan or the code.

## The decision

1. **A correction's store write failing fails the run.**  Plan D11: the
   agent may re-submit an entity's interpretation.  For an entity already
   written (`_DONE`), today's code (and the step-3 code) calls
   `Semantic_DB.update_interpretation` synchronously inside the `answer`
   tool handler; a failure there (LMDB map full, disk full, I/O error,
   corrupt record) can only be reported back to the agent in the tool
   reply, because the MCP SDK turns a handler exception into an `isError`
   result and nothing reaches `_run_agent` or Isabelle.  The run then ends
   as a success and the theory is marked interpreted with the correction
   lost.  The user ruled: this must be an error of the run, like a gate
   write failure.

2. **Mechanism: the correction write becomes a task of the gate task
   group.**  `on_answer`'s `_DONE` branch no longer writes; it submits a
   coroutine that performs the `update_interpretation` to
   `task.task_group`, counted by the same `gate_started` / `gate_finished`
   pair so `_run_agent`'s termination condition (`gates_running == 0`)
   waits for it.  `on_answer` therefore never raises for a store reason,
   and the `answer` tool handler needs no per-item try/except (first
   review's F2 dissolves).  A failed correction fails the group, the
   session is cancelled, `interpret_file` raises, the theory is not
   marked.  (D11 itself is untouched: no re-gating, no re-judging, the
   text is overwritten, gate fields stand.)

3. **No `GateError` at all.**  The step-3 code wraps a gate write failure as
   `GateError(...) from exc`.  The first review found (F1) that plan §5.4's
   own `raise leaves[0] from None` then erases the cause, and the user asked
   why the raw exception is not propagated as it is.  Analysis: nothing
   matches `GateError` by class anywhere (`_run_agent`'s except arms never
   see it -- the gate runs in a separate task; `_unwrap_gate_failures`
   re-raises the first leaf whatever its class; the `USER_ERROR_MARKER`
   one-line contract is not used for it, and a store failure is exactly the
   case where the traceback IS the lead).  The wrapper's only real content
   is the entity's name.  Decision: delete `GateError`; both the gate write
   and the correction write let the native exception (`lmdb.MapFullError`,
   `lmdb.Error`, `OSError`, `UnicodeEncodeError`, `LookupError`, ...) propagate
   unchanged, after `exc.add_note(f"while writing the interpretation of
   {e.name}")` (Python ≥ 3.11).  `_unwrap_gate_failures` re-raises the
   first non-cancellation leaf with `raise leaves[0] from leaves[0].__cause__`
   (keeps a cause, hides the group's context; for a leaf with no cause this
   is today's `from None`).  The plan text is amended accordingly
   (§5.4 "Failures", §13 item 3, §15.1 table row, §15.3 `on_answer`,
   §15.5 `_write`'s "re-raised as GateError").

## Sketch of the code (for the reviewers; not final)

```python
class InterpretationTask(AgentTask):
    def start_gate(self, idx): ...                     # unchanged shape (F4 fix: compensate on create_task failure)

    def _spawn(self, coro) -> None:
        """Run `coro` as a write task of the run: counted like a gate, so the
        loop waits for it; its exception fails the run."""
        assert self.task_group is not None
        self.gate_started()
        try:
            self.task_group.create_task(self._finishing(coro))
        except BaseException:
            self.gate_finished(); raise

    async def _finishing(self, coro):
        try: await coro
        finally: self.gate_finished()

    def on_answer(self, idx, text):
        self.results[idx] = text
        match self.state[idx]:
            case _DONE:   self._spawn(_correct(self, idx))          # D11 on a written entity
            case _GATING: pass                                      # the gate writes the newest text
            case _:       self.state[idx] = _GATING; self._spawn(_gate(self, idx))

def _noting(e: Entry):            # context manager: add_note on any exception
    ...

async def _correct(task, idx):
    e = task.entries[idx]
    with _noting(e):
        Semantic_DB.update_interpretation(e.universal_key, ..., interpretation=task.results[idx])

def _write(task, idx):            # step 3's write, GateError wrapper replaced by _noting(e)
async def _gate(task, idx): _write(task, idx)   # gate_finished now in _finishing
```

Open questions the reviewers should settle or flag:

- Is one counter (`gates_running`) for gates AND correction writes right, or
  does the glossary/plan need a broader name ("write tasks")?  The loop's
  wait condition is "no task of the run is outstanding"; the plan calls
  them gates.
- Ordering: a correction task and the entity's earlier gate can never
  overlap (the correction is only spawned when the state is `_DONE`, i.e.
  the gate has written).  Two corrections of the same entity spawned in
  quick succession are two tasks; both are synchronous LMDB writes without
  an `await`, so on one event loop they run to completion in creation
  order.  Is that argument sound?  Is the last-submitted text guaranteed to
  be the one on disk?
- `add_note` vs a wrapper class: does dropping the class lose anything the
  plan relies on later (steps 4–8: the snapshot raise in `_propagate`, the
  judge's failures which are NOT store failures and are logged, not raised)?
- `raise leaves[0] from leaves[0].__cause__`: any case where this changes
  the traceback Isabelle shows for the worse?
- Should `_unwrap_gate_failures` keep its CancelledError filter (the first
  review's F11 said it is unreachable but harmless)?
