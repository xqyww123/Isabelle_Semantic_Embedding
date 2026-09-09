# Design change under review: a correction re-runs the gate (D11 revised)

Context: `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` rev 5.2 (authoritative;
§0 glossary), the step-3 code on disk (`Isabelle_Semantic_Embedding/
semantic_interpretation.py`, `semantics.py`), the first review's report
`ai-artifacts/review_step3/REPORT.md` (F1–F11), and yesterday's design note
`P2_DESIGN.md` with its judge ruling `p2_judge.json`.  **P2_DESIGN.md is
SUPERSEDED by this note**: the user, on 2026-09-09, overruled the premise
behind D11 and P2.  Nothing here is in the plan or the code yet.

## Vocabulary (fixed)

- **Answer**: the agent submits, through the `answer` tool, the English
  interpretation of an entity it was asked for.
- **Correction**: a second (third, ...) submission for the SAME entity in the
  same run.  The tool description invites it ("You may also resubmit an entry
  to correct a previous answer", since 2026-03-17); the batch-complete reply
  repeats the invitation.  A correction is not a re-interpretation of a stale
  entity; the entity's formal definition is unchanged, the agent wants
  different English.
- **Gate** (plan §5.4): per entity, after its answer arrives: decide whether a
  judge is needed, prefilter, judge (compare the FRESH TEXT against
  `baseline_interpretation`, the text stored at the entity's last mint),
  decide CHANGED / UNCHANGED, write everything in one transaction (mint iff
  CHANGED), propagate (CHANGED only).  In step 3 the gate is the write alone.

## What the user decided (2026-09-09)

1. **D11 was wrong.**  It said: a correction of an entity already written
   overwrites the text only, "the gate fields stand (the definition did not
   change between the two submissions), no re-gating".  But the gate does not
   compare definitions; it compares interpretation TEXTS.  A correction
   changes the fresh text, so the verdict can change.  New rule: **a
   correction of a `_DONE` entity re-runs the gate**, the same procedure as
   for the first answer.

2. **No special correction path.**  `on_answer(idx, text)`:
   ```python
   self.results[idx] = text
   if self.state[idx] == _GATING:          # the running gate writes the newest text
       return
   self.state[idx] = _GATING               # from _QUEUED/_SENT (an answer) or from _DONE (a correction)
   self.start_gate(idx)
   ```
   Both histories are handled by the one procedure without inspecting the
   previous verdict:
   - previous verdict UNCHANGED: baseline is still the old text B; the second
     gate compares T2 with B: CHANGED → mint, write T2, baseline := T2,
     propagate; UNCHANGED → write T2, version stands.
   - previous verdict CHANGED: the mint already happened and baseline := T1;
     the second gate compares T2 with T1 → almost surely UNCHANGED → write T2,
     no second mint.  If the agent really changed the meaning, a second mint is
     correct.
   Cost: one judge session per correction (~10 s, ~$0.13); corrections are rare.

3. **Consequences.**
   - `Semantic_DB.update_interpretation` (step 1, built for the old D11) has
     no caller: delete it and its tests; `gate_write` is the ONLY write entry
     point for interpretations (§6.4 shrinks to one entry point, two puts).
   - Yesterday's P2 design (correction write as a separate "write task",
     `start_write`, `_correct`, `writes_running`, a "write task" glossary row,
     crash shape (iii)) is void: the task group holds gates only, so
     `gates_running` / `start_gate` are the right names again.  "A failed
     correction write fails the run" holds automatically (it is a gate write).
   - The gate must read the entity's CURRENT record (`task.rec_cache[uk]`, which
     the first gate's write updated), not the scan-time `task.recs[idx]`
     (plan §15.5's `rec = task.recs[idx]  # record before this run`), or the
     second gate would see the pre-run baseline.  Step 4/5 change.
   - D13 ("every entity is interpreted at most once per run") stands: the LLM
     interpretation happens once; the gate may run more than once.
   - `n_interpreted` (the closing line's A) counts entities, not gate runs:
     increment only when an entity first reaches `_DONE`.
   - Step 3 today (gate = write only): a correction re-runs `_write` with the
     same scan pair, rewriting the text — behaviour equals today's (a
     correction overwrote the text) except that a failed write fails the run.
   - Crash shape: a correction whose gate write fails leaves the first write's
     record (complete, fresh by the scan's criteria); the run fails; the next
     run does not re-ask the entity; the correction is lost.  The user judged
     this harmless (the first interpretation is valid).
   - Kept from the first review and yesterday's ruling, unaffected by this:
     F1 (no `GateError`; native exception + `add_note("while writing the
     interpretation of <E>")`; the unwrap helper RETURNS the first
     non-cancellation leaf and `interpret_file` raises it outside the
     `except` block), F3 (`_stop_if_cancelled` in the recovery arms), F4
     (counter paired to the task via `add_done_callback`, compensate when
     `create_task` raises), F6/F7/F8 (tests: store-backed `_gate`, the
     wait-for-gate path, the correction path = a second gate on a `_DONE`
     entity), F10 (`results` as an index-aligned list), P1 (`batch_size` a
     task attribute; delete conftest).

## Open questions for the reviewers

- **Concurrency of two gates on one entity.**  A correction arriving while the
  entity is `_GATING` only replaces the text (no second gate).  A correction
  arriving when `_DONE` starts a second gate; can the first gate still be
  running?  (Claim: no — `_DONE` is set at the end of the first gate's
  synchronous write, and `gate_finished` follows; the state is `_DONE` only
  after the first gate has fully written.)  Two corrections in quick
  succession on a `_DONE` entity: the first flips the state to `_GATING`, the
  second only replaces the text.  Sound?
- **Second gate + propagation.**  A second CHANGED verdict on an entity whose
  first verdict was CHANGED: dependents already `_DONE` get their snapshot
  raised again, not-enrolled ones enrolled — is anything double-counted or
  unsound in eff\*?  A second CHANGED on an entity whose first was UNCHANGED:
  the normal propagation.  Any interaction with the queue loop's termination?
- **rec_cache as the gate's record source.**  Plan §15.5 reads `task.recs[idx]`
  and §15.8 keeps `recs` for the scan; is switching the gate to
  `task.rec_cache[e.universal_key]` (written back after every gate write)
  enough, and does it affect `_EffStar` (a fresh instance per gate call over
  `rec_cache`)?
- **Deleting `update_interpretation`.**  Any other consumer, present or
  planned (steps 4–8), of a text-only write that keeps gate fields?
- **The step-3 acceptance bullet (§15.11).**  Wording: "behaviour equals
  today's except that each batch is a turn and a failed store write (an
  answer's or a correction's) fails the run".
- **Elegance.**  Is anything about this shape a hack?  Does the plan's
  §5.3.1 state diagram need a `_DONE → _GATING` edge and does any argument
  in §5.3.1 / §14 ("a second verdict on an already written entity does not
  exist under D11 and D13") break?  List every plan passage that must change.
