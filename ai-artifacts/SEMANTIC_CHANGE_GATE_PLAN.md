# Semantic change gate, shielded invalidation and interpretation lock — implementation plan (rev 5)

Status: **rev 5.4 (2026-09-09); §13 steps 1–5 implemented, reviewed and
accepted (step 3: `ai-artifacts/review_step3/`; step 4:
`ai-artifacts/review_step4/`, judge `judge.json`, five fixes applied — the
live-path statement refresh unconditional, the query tool's refusal compared
in one spelling, no self edge in the reverse graph; step 5:
`ai-artifacts/review_step5/`, judge `judge.json` and `rereview_judge.json`,
three production fixes applied — the prefilter's `embed` call under the embed
machinery's tracing gate, `RunState.claim_prefilter_disable()` so §12 #5 is
printed once even by gates already inside the failing call, the `<error>`
slot filled by the exception's class name when its `str` is empty — plus
tests); step 6: `ai-artifacts/review_step6/`, judge `judge.json` and
`rereview_judge.json`, two production fixes applied — the `Config.lookup`
callback built once in `interpret_with_parallel` and threaded as a value
(§5.6), `embedding_config.Missing_Dimension` so §12 #4 carries the message
and not its repr — plus tests, and the user's ruling to keep #4's slot text
verbatim; step 7: `ai-artifacts/review_step7/`, judge `judge.json` and
`rereview_judge.json`, accepted with three production fixes applied — the
unlocked body hidden in `local … in … end`, `uninterruptible_body` in
`with_interpretation_lock`, a timeless `RunState` docstring — and the ML
test rewritten to bounded waits; §8.1 and §8.2 edited accordingly; the
user's decisions of 2026-09-11: the ML lock test stays in `Test/ROOT`, the
step-7 commit waited for the other agent's interrupt work to land in
Isabelle_RPC first (it did, 2026-09-11, and its commits `2b22658` /
`694ebaa` swept in the Isabelle_RPC half of step 7 and `semantic_store.ML`;
the rest followed in the step-7 commit of 2026-09-12), and Isabelle_RPC's
v0.5.0 is not tagged before `Connection.on_close` is in; integration review
of steps 1–7 as one program (2026-09-12, `ai-artifacts/review_integration/`,
`judge.json`, `rereview_judge.json`, `rereview2_judge.json`): accepted after
D18 (no stored interpretation of this run's entries reaches the agent --
both lookup tools and the ML provenance hint), D19 (an empty wire statement
keeps the stored `expr`), the cancellation fix (`_stop_if_cancelled` raises
a `CancelledError`, also from `_judge`'s handler), the grant check on the
writer's own dict, the lock acquire's RPC-error conversion, the `_label`
reuse, the head-keyed provenance collapse, and the tests §10 now lists;
the user rejected narrowing `update_gate_fields` and any change to the
system prompt or to the hint's behaviour for other theories; step 8 (§12
texts, §11 docs, elegance-INT-4) done and reviewed 2026-09-12
(`ai-artifacts/review_step8/`, `judge.json`, `rereview_judge.json`): the
review refuted the "dry-run count is a lower bound over a cone" claim (D7,
§5.2 corrected: neither bound, exact at zero) and the user re-approved §12
#8–#11 with "About n"; all §13 items are implemented.  The paid §10 items
were run on 2026-09-12 (`ai-artifacts/acceptance_step10/REPORT.md`,
ClaudeCode/Opus 5, USD 10.76, isolated store): both pass -- 2 judge
verdicts, 3 prefilter decisions, 5 mints propagated to 31 dependents, a
post-run dry run of 0; one finding outside the gate, a `fun`-defined
constant's digest does not see a change of its equations (`narquil`; repaired 2026-09-13 by `ai-artifacts/fun_digest/PLAN.md`, acceptance in `ai-artifacts/fun_digest/ACCEPTANCE.md`; source revised 2026-09-14 to the facts named after the constant, PLAN.md §10),
raised with the user.  PATH 20 of the disclosure audit accepted as is
(D20).**
Three review rounds (rev 1: 98 agents; rev 2: 23; rev 3: 23) and the user's
rulings on them are absorbed.  Rev 5.3 records the user's decisions of
2026-09-08/09 after the step-3 code review: D11 revised (a correction re-runs
the gate; `update_interpretation` deleted), D14 reworded ("one write per
verdict"), no `GateError` (the store's own exception propagates with a note),
`n_interpreted()` derived from the states, `batch_size` a task attribute, and
the three mechanics the review fixed (`_stop_if_cancelled`, the
`add_done_callback` pairing of the gate counter, `results` as an index-aligned
list).  Rev 5 (2026-09-08) replaces rev 4's candidate
list, batch-wise gate and two-phase write with the user's decisions D12–D17:
a first-in-first-out work queue, one judge session per entity started when
its answer arrives, one write per entity.  All texts in §12 are approved.
Also approved on 2026-09-08 after the rev 5 checklist: the judge's one-round
retry (§5.4 step 3), the `judge_` cost breakdown (§5.5), the Codex sandbox
deviation (§5.5) and the 3-second window of §8.1 recorded as a limitation.

Parent design: `archive/plans/CHECK_OUTDATE_PLAN.md` (moved there from the
superproject root on 2026-09-12); its glossary terms keep
their meaning.  Measurements: `ai-artifacts/similarity_measurement/REPORT.md`,
`REPORT_PHASE2.md`.  Verification of §4: `ai-artifacts/eff_shield_verification/
REPORT.md` (scope in §4; that directory is kept locally only, removed from
git on 2026-09-12).

## 0. Glossary (one word per concept)

| term | meaning |
|---|---|
| **semantic change gate** (the gate) | the decision, after a tracked entity has been re-interpreted, whether its meaning changed.  "changed" mints a new `version`; "unchanged" leaves it |
| **tracked entity**, **tracked kinds** | a WIP entity of the four name-addressed kinds (constant / type / class / locale): its wire entry carries a `semantic_digest`.  Theorem-alike entities are leaves, never mint (parent I2), never gated |
| **baseline interpretation** | the interpretation text stored at the entity's last mint (or first write).  New Record field |
| **prefilter similarity** | cosine similarity, under the connection's embedding model, between the document texts (`document_text.entity_document_text`, current `expr`) built with the baseline and with the fresh interpretation |
| **judge session** | one fresh agent session per judged entity (same driver and model as the interpretation session, D12) answering the one (baseline, fresh) pair through one `verdict` tool |
| **eff\***, **wall** | the shielded effective version of §4; a wall is a dependency fresh under eff\* that hands its dependents only its own `version` |
| **local staleness** | uncached, or digest differs from stored, or stored dep keys differ from current (parent §4.3), or record has no digest (parent §4.4).  Decided from the entry and its own record; never changes during a run |
| **seed set** | the entries the scan can already prove need interpretation: locally stale, or stale under eff\* over the store, or uncached (§5.2) |
| **queue** | the theory's work queue, first in first out: the seed set in wire order, then the dependents enrolled by CHANGED verdicts (§5.3) |
| **interpretation lock** | one advisory file lock per semantic database directory |

## 1. What is being changed, and why

Today (parent §4.1) a tracked entity whose digest changed mints a `version` at
scan time and every entity whose closure contains it is re-interpreted.
Measured (`REPORT_PHASE2.md` §7, §11): where the digest changed but the meaning
did not, this is wasted (91 of 100 downstream paragraphs did not change
meaning); an embedding threshold cannot separate the cases, a language-model
judge can (0.8 % false alarms, one miss in 87, caught by a similarity backstop).

Two changes: `version` is minted only when the gate says the meaning changed,
after re-interpretation; and the closure rule becomes eff\* (§4), so an
"unchanged" verdict at any hop shields the dependents below it.  Independently,
parallel `by aoa` commands each start their own interpretation of the same
cone; the interpretation lock (§8) serialises runs per database.

## 2. Decisions taken by the user (settled)

| # | decision |
|---|---|
| D1 | Gate at every hop; closure rule eff\* (verified) |
| D2 | **UNCHANGED requires an explicit "same" verdict from the judge, with prefilter similarity ≥ 0.90 when the similarity can be computed; every other outcome is CHANGED.**  If the embedding service is not configured or does not respond, the prefilter is skipped and the judge decides alone.  A few needless propagations are acceptable; a missed change is the outcome to avoid |
| D3 | The judge uses the interpretation driver's own driver and model at the driver's own reasoning effort (ClaudeCode/DeepSeek `effort="high"`, claude_code.py:456; Codex: its default), with exactly one tool, `verdict`.  Measured cost of one fresh session judging one pair (2026-09-08, three runs each): Claude Code 8–10 s, ≈ $0.13 API-equivalent (55k cached tokens are the CLI's fixed context); Codex gpt-5.6-sol 13–20 s, ≈ $0.06 |
| D4 | The baseline interpretation is stored as text in the Record |
| D5 | The prefilter embedding model follows `Semantic_Embedding.embedding_model` |
| D6 | **No on/off option**: gate and eff\* are always on (they must switch together) |
| D7 | The dry run returns one number per theory, the seed set's size (§5.2) — per theory, against the store state that scan read, every counted seed is sent, but summed over a cone **neither bound** (step-8 review, 2026-09-12); it serves the two existing `n = 0` guards (where it is exact) and the 400 threshold, and is shown to the user as "About n" (§12, re-approved 2026-09-12) |
| D8 | Interpretation lock, **try once, never wait**: `by aoa`'s startup check and `_auto_embed` skip with one line; `run_semantic_interpretation` and `Semantic_Store.collect` raise an error.  A dry run is never locked |
| D9 | 0.90 is a Python constant, not an option |
| D10 | **Failure principle**: nothing ever mints a version silently or hides a failure — a mint happens only on the gate's explicit CHANGED verdict; an outcome the gate could not judge is CHANGED (conservative) and is logged; an answer whose gate did not finish is never written (D14), so the next scan re-lists the entity by the very criterion that enrolled it (§5.4, §6.4) |
| D11 | **Corrections** (revised 2026-09-09): a re-submitted answer is an answer — it re-runs the entity's gate, the same procedure as the first answer.  The gate compares interpretation texts, not definitions, so a correction can change the verdict: it may mint and propagate like any other verdict.  No text-only write and no separate correction path.  A correction arriving while the entity's gate is running is picked up and judged by that gate, never adopted by it (§5.4).  A byte-identical resubmission starts nothing.  No drain |
| D12 | **One entity per judge session** (2026-09-08): the judge compares exactly one (baseline, fresh) pair per session, in a fresh agent session each time; the session is started the moment the entity's answer arrives.  At most **40** judge sessions run at once (user's ruling after the rev 5 review: a process-wide `asyncio.Semaphore(40)` around §5.4 step 3 only; gates still start the instant an answer arrives, so the ordering and termination arguments of §5.3 are untouched) |
| D13 | **Work queue** (2026-09-08): the scan enrols only the seed set, in wire order; a CHANGED verdict enrols the entity's theory-internal direct dependents; no closure, no topological order.  A dependent already written this run is not re-interpreted: its `interpreted_at` is raised to the current eff\* (§5.3.1).  Every entity is interpreted at most once per run (the LLM is asked once; the entity's gate runs once per accepted correction, D11) |
| D14 | **One write per verdict** (2026-09-08; wording adjusted 2026-09-09 for D11): an entity's record is written when its verdict is known, with the interpretation text and the gate fields together; nothing about it is written before.  One answer, one verdict, one write — so a corrected entity is written once per gate (D11) and never otherwise |
| D15 | **Entries outside the four tracked kinds** (2026-09-08): theorem-alike entries, WIP collections / methods and persistent-theory entries keep today's behaviour exactly: written when their answer arrives, no judge, no mint, no baseline; theorem-alike carry `version` (stored or ε) and `interpreted_at`, the other two carry `None` everywhere (§3) |
| D16 | Startup check (2026-09-08): `_resolve_embedding_config` gains `warn=True`; the startup check calls it with `warn=False` so text §12 #4 is printed once, not on top of the function's own warning (§5.6) |
| D17 | The exported `Semantic_Store.interpret` (no caller in the repo) reuses text §12 #2 deliberately (§8.2) |
| D18 | **No stored interpretation of the theory being interpreted is disclosed to the agent** (2026-09-12, integration review): inside an interpretation session nothing hands the agent a stored interpretation of an entity this run enumerated for that theory, enrolled or not -- the two lookup tools `query` and `desugar_and_explain` hide them, keyed on the resolved universal key at every point a text would be returned (`AgentTask.theory_keys`, fixed at construction), and the locale-interpretation provenance hint the ML side composes into the batch prompt omits its `Template meaning:` / `Locale "…":` lines for them (`build_entries`, the run's own keys dropped before the store is consulted).  Supersedes the enrolment-time refusal of §15.8's step-4 ruling: an entity enrolled by a later CHANGED verdict may already have been read otherwise, and an echoed text would make the judge say "same" on a real change.  The agent reads the definitions from the source instead |
| D19 | **An empty wire statement means "could not be computed", never "empty"** (2026-09-12): `mk_prop_str` yields "" for an ML_file method, an unreadable theory file, a failed constraint lookup; both writers (the gate's write and the statement refresh) store the wire `prop_str` or, when it is "", the stored `expr` -- one rule, `_statement(e, rec)`, so a re-interpreted entity whose statement could not be computed keeps its stored one |
| D20 | **The CLI built-ins stay in the interpretation session; PATH 20 is accepted, not closed** (2026-09-12, after step 8): the interpretation driver keeps `cli_tools=True`, so Claude Code's `Read`/`Grep`/`Glob`/`Bash` remain allowed -- D18 tells the agent to read the definitions from the source, and these are its means.  D18's guarantee is therefore about what the pipeline hands the agent, not about the store being unreachable from a process with a filesystem (the store is an on-disk LMDB and its reader an importable package; no prompt or tool text names it).  The judge session keeps `cli_tools=False` |

## 3. The gate rule

For a tracked entity E just re-interpreted (fresh text `new`), with R the
record as it stands when THIS gate runs — `task.rec_cache[E.universal_key]`:
the record before this run for a first gate, the record the previous gate
wrote for a correction's gate (D11); R may be absent — rows in order, mutually
exclusive:

```
not gated (first write)  if R is absent or R.semantic_digest is None   (no record before this run, or a never-digested one)
                         -> version := ε (counter value at write, parent §4.4), baseline := new
CHANGED                  if R.baseline_interpretation is None        (record predates this plan)
CHANGED                  if the similarity could be computed and is < 0.90
UNCHANGED                if the judge says "same"
CHANGED                  otherwise: "different", no verdict for this entry, judge session failed
```

A record with a digest but no baseline is forced CHANGED without prefilter or
judge (one-time cost per legacy record; never seed the baseline from the
stored interpretation, §6.2).  Writes — one transaction per entity, the
interpretation text and the wire fields together with the gate fields (D14);
`semantic_digest` and `deps` from the wire; `interpreted_at` = eff\*(E) over
`rec_cache` at the time of the write, after this entity's own mint if any:

| entry | judged | written when | version | baseline_interpretation | interpreted_at |
|---|---|---|---|---|---|
| tracked, first write | no | answer arrives | ε | new | eff\*(E) |
| tracked, CHANGED | rows 2–5 | verdict known | `counter_next` | new | eff\*(E) |
| tracked, UNCHANGED | yes | verdict known | unchanged | unchanged | eff\*(E) |
| theorem-alike (WIP: `semantic_digest` None, deps present) | no | answer arrives | stored, else ε | None | eff\*(E) |
| WIP collection / method (`semantic_digest` None, no deps; semantic_store.ML:1798-1800, :711-712) | no | answer arrives | None | None | None (all gate fields None) |
| persistent theory | no | answer arrives | None | None | None (all gate fields None) |

The last two rows are today's behaviour (D15).  Every written entity is
subject to the snapshot raise of §5.3.1 when a dependency mints later in the
run.

A correction (D11) re-enters this table with R = what its first gate wrote,
so its row may differ from the first gate's: an entity this run first wrote
now has a digest and a baseline, so its correction takes the judged rows and
a CHANGED verdict there mints and propagates.  That is deliberate
over-signalling under D2 — nothing consumed the superseded text (no stored
interpretation of this theory's entities reaches the agent at all, D18/§15.8), and a needless
propagation is acceptable while a missed change is not — not a defect.  The
not-judged rows re-run unchanged, taking their version from R, so a second
write keeps the ε its first write committed instead of re-reading a counter
that may have risen.

## 4. The shielded closure rule (eff\*)

```
eff*(E)    = max( version(E), max over direct deps d of contrib(d) )
contrib(d) = 0           if d has no record                               (parent §4.4)
contrib(d) = version(d)  if version(d) > 0 and interpreted_at(d) > 0 and eff*(d) <= interpreted_at(d)
contrib(d) = eff*(d)     otherwise
E is stale iff eff*(E) > interpreted_at(E)
```

`contrib(d)` is `version(d)` when d is not stale and `eff*(d)` when it is.  No
wall inside an SCC; the wall test applies only on the edge from a parent to an
already-finalised node.  `None` reads as 0 and is never a wall.  The freshness
test MUST use eff\*(d), not the raw eff(d) (`eff_shield_verification/REPORT.md`
§2).

Implementation: `eff_shield_verification/eff_uk_shielded.diff` — one helper
`_contrib(d, e)` beside `_rec_of`, applied at the finalised-successor edge in
`eff_uk`, at the SCC-root flow to the parent, and in `eff_value`.  Tarjan
shape, memo and cost unchanged; no extra database read.

**Scope of the verification.**  Its soundness, forced-CHANGED equivalence,
order independence and compatibility results were measured on a prototype that
kept today's scan-time mint.  This plan removes that mint, so the soundness of
*enrolment* rests on §5.3.1's argument (a stale entity is a seed or is
enrolled by the mint that made it stale; a written entity's snapshot is
raised); the ported tests (§10) drive the production scan and the queue.

Parent plan: §4.1 → eff\*; §4.2 I2 ("mint when the gate says changed"), I3
reworded (§11).

## 5. The interpretation run (semantic_interpretation.py)

### 5.1 What stays

One theory = one `Semantic_Store.interpret_file` RPC = one `interpret_file`
coroutine on one connection = one interpretation session.  The ML thread
blocks in `dispatch_loop` until the coroutine returns; `interpret_cone` then
`mark_interpreted`.  Theories run as futures under `schedule_dag`, ancestors
first, so cross-theory dependencies are final when a theory is scanned.  The
completeness invariant (an interpretation per entry, or raise) holds.
Enumeration, digest/deps, serial ordering, the label assert, the proof channel
and the persistent path are untouched.

### 5.2 Scan (replaces phases 1–3)

Nothing minted, no gate field written, no counter put; the only write a scan
ever makes is the dry path's statement refresh (§5.3.2, §15.8 item 6).
Untracked entries (persistent theories): today's cached / uncached split, no
gate; the scan's `expr` shortcut moves to §5.3.2.  Tracked entries: local
staleness (§0).

Build the theory-internal dependency graph (edges = `deps` targets that are
entries of this theory) and its reverse (each entry's direct dependents), as
index lists over `entries`.  No condensation, no topological order (D13).
**Seed set** = locally stale ∪ (eff\* over the store > interpreted_at) ∪
uncached untracked.  Every other entry is filled from the store into
`task.results`, as today's cached path does.  The **queue** starts as the seed
set in wire order.  The digest is not invariant under renaming (the alpha
normaliser was removed 2026-09-13), so an entity whose only change is a
variable rename is a seed: it is re-interpreted once and judged — UNCHANGED
walls its dependents when the record carries a baseline; a record predating
the gate (digest, no baseline) is forced CHANGED and mints (§3 row 2).  That
is the designed path.

Why no closure: a dependent of a seed is enrolled the moment the seed's
verdict is CHANGED (§5.3.1); until then the seed's record, which still looks
fresh, is rightly a wall.  Why the run is bounded: an entity is interpreted at
most once per run (§5.3.1), versions are minted only at verdicts, and a path
from an entry of T to an entry of T cannot leave T.  Gate runs and mints are
bounded by the number of SUBMISSIONS rather than by the entity count, because
a correction re-runs the gate (D11); submissions are agent-initiated and
finite, and no gate run ever re-interprets an entity.

**Dry run (D7).**  `interpret_file(dry_run=True)` returns the seed set's size
after the statement refresh of the not-enrolled entries (its only write: an
`expr` and a vector tombstone, no gate field, no mint, no counter put); ML
`dry_run`, `interpret_file_dry_run_cmd`, `pack_arg` unchanged (one `int`).  The number is the sum of the
theories' seed sets against the store as it stands before the run.  Per
theory, against the store state the dry run read, every counted seed is
sent (dependents are not counted: whether a change propagates is decided
by the gate after re-interpretation, which a dry run never runs).  Summed over a cone it is
**neither bound** (step-8 review, 2026-09-12): the live run can send more (a
CHANGED verdict enrols dependents) or fewer -- `schedule_dag` scans a
descendant theory only after its ancestors' writes, and an ancestor's
UNCHANGED verdict raises its `interpreted_at` to eff\*, walling off a
dependent in the later theory that the dry run had counted.  It is exact at
zero (no seed anywhere ⇒ no gate mints ⇒ the `n == 0` guards in
`update_interpretations` and `interpret_command.ML:122` stay exact); the
user-visible texts therefore say "About n" (§12 #8–#11).  The comment at both dry-run sites (semantic_store.ML's dry-run
comment, Python's `dry_run` branch), approved wording (2026-09-08, rev 5):

> A LOWER BOUND on the live run's work: this theory's changed / uncached
> entities.  Their dependents are not counted -- whether a change propagates
> is decided by the semantic change gate after re-interpretation, which a dry
> run never runs.  Exact at zero.

Parent §14's "quote = actual work" equality is retired (§11).

### 5.3 The queue

`_run_agent` drives the session from the theory's queue (D13); the `answer`
tool no longer advances batches: it records the answer in `task.results`,
starts that entity's gate (§5.4) and reports how many of the batch are still
unanswered; the turn ends when the batch is answered.

```
loop:
  batch := entries sent but unanswered (only after a recycle) ++ take(queue, up to _BATCH_SIZE)
  if batch is empty:
      if no entry is sent-unanswered and no gate is running: break
      wait until a gate enrols an entry or every gate has finished; continue
  run_turn(prompt(batch)); retry the batch's unanswered entries -- today's theory-wide retry loop (chunks of _BATCH_SIZE, stall counter, raise on give-up; semantic_interpretation.py:774-810) re-scoped to the batch; its give-up message is one of §5.5's task-supplied strings
await every gate                     -- the gate task group (§5.4), before the session is closed
statement refresh                    -- §5.3.2 (in interpret_file, after the loop)
```

The loop is the interpretation task's (§5.5); a judge task has one entry and
no queue.

**5.3.1 Entity states and enrolment.**  Each entry is in one of five states:
*not enrolled* (filled from the store at scan), *queued*, *sent*, *gating*
(answered, gate running), *done* (written).  The edges are *not enrolled* →
*queued* → *sent* → *gating* → *done*, plus *done* → *gating*, which a
correction takes (D11): a written entity may be gated again, and its *gating*
state is why `_propagate` passes over it.  `task.results[i] is None` iff
queued or sent, so today's retry loop and `batch_remaining` are unchanged;
the completeness invariant keeps its shape but not its warrant (§15.4).
When an entity's verdict is CHANGED (it minted), for each theory-internal
direct dependent j:

- not enrolled → **enrol**: `results[j] := None`, appended to the queue's
  tail;
- queued, sent or gating → nothing: its write comes later and its snapshot
  will include the mint (for an entity gating again after a correction, that
  is its next write, which recomputes eff\* from `rec_cache` from scratch);
- done → **raise the snapshot**: `interpreted_at(j) := eff*(j)` over
  `rec_cache` now, a gate-field write with no mint and no re-interpretation.
  Sound because j's text was produced this run from the same source file, so
  it already describes the changed definition; the raised snapshot records
  that.  No propagation beyond j: if j's own verdict was CHANGED its
  dependents were handled then; if UNCHANGED, j is a wall.

Consequences: every entity is interpreted at most once per run (D13 — the LLM
is asked once; the entity's gate runs again for each accepted correction,
D11); the queue is plain first-in-first-out in wire order with no ordering
constraint between
dependencies and dependents; strongly connected components need no special
treatment; no entry is ever dropped, so there is no drop bookkeeping.  Cost:
the `answer` tool's array submits several entries at once and independent
theories run under `schedule_dag` concurrently, so several gates are in flight
at a time (D12: at most 40 judge sessions).  A sixth case that is not a
state: an answer naming an entry that is `_NOT_ENROLLED` is rejected by the
answer tool (today's "Unknown entry" reply) and starts nothing (§15.8).

Batches are whatever `take` returns; the prompt is built at send time:
`build_prompt(indices)` replaces today's `build_prompt(file_path,
theory_longname, indices=None)` (semantic_interpretation.py:517) -- the file
path, theory long name and the unicode file path (today passed in at :1187)
become task attributes, and "first batch or not" is a task flag set after the
first `run_turn`, not `indices.start != 0`.

**Recycle paths.**  A session abandoned mid-turn (usage cap, rate limit,
poisoned session, transient error) is re-entered through `make_driver` as
today; the sent-but-unanswered entries lead the next batch, and no recycle
handler knows the queue exists.  Gates are independent tasks and survive a
recycle of the interpretation session.

**Termination.**  The loop ends only when the queue is empty, nothing is
sent-unanswered and every gate has finished: a gate may enrol an entry after
the queue emptied, so the session is kept open while gates run, and
`interpret_file` returns only after the gate task group has joined, which is
what makes every mint of this theory visible to the descendants `schedule_dag`
starts afterwards.

**5.3.2 Statement refresh.**  For every not-enrolled entry whose statement
`_statement(e, rec)` -- the wire `prop_str`, or the stored `expr` when the
wire's is "" (D19, §15.8 item 8) -- differs from the stored `expr`,
`Semantic_DB.update_expr` (invalidates vectors).  On the live path it runs
after the loop (today's scan-time refresh moved after the LLM work); on the
dry path it runs before the early return, so an `expr`-only change is
refreshed even when the cone quotes zero and both `n == 0` guards short-circuit.

### 5.4 gate(entity)

Started by the `answer` tool the moment entity E's answer arrives (D12): one
asyncio task per entity in an `asyncio.TaskGroup` owned by `interpret_file`.
The gate tasks themselves are unbounded; only the judge session of step 3
takes a permit from `_JUDGE_SESSIONS` (D12: 40).  A task waiting for a
permit holds none, and the loop's wake-up comes from `gate_finished`, so the
cap cannot deadlock the queue.  Steps:

1. **Which entries need a judge.**  §3 rows "first write" and "digest but no
   baseline": no prefilter, no judge, straight to step 5 with the row's
   verdict.  Theorem-alike, WIP collection / method and persistent entries:
   straight to step 5 (D15).  Tracked entries with a digest and a baseline:
   steps 2–4.
2. **Prefilter** — skipped for the whole run when the startup check (§5.6)
   found the embedding service unconfigured, and for the rest of the run after
   a failed call.  Two document texts (baseline and fresh, both with the
   current `expr`), one `store.emb_provider.embed(text, role="document")` call
   for the pair, where `store` is the `Semantic_Vector_Store` this
   `interpret_file` resolved on its own connection through
   `await connection.semantic_vector_store()` (semantics.py:2792-2811; §15.8
   "Run-scoped state" — never a store resolved on another connection, D5)
   and the vectors are the call's `.vectors`
   (`Embedding_Provider.embed` returns an `EmbedResult`,
   semantic_embedding.py:456-468); **cosine = dot(u, v) / (‖u‖ ‖v‖)** —
   provider normalisation is a per-model config entry defaulting False
   (`embedding_config.py`), and every other consumer normalises for itself
   inside `encode_q15`; a zero norm or a non-finite value counts as "could not
   be computed" (a bare `sim < 0.90` would let NaN through in the wrong
   direction).  Below 0.90 ⇒ CHANGED, no judge.
3. **Judge session** (≥ 0.90, or always when the prefilter is skipped): under
   a permit of `_JUDGE_SESSIONS` (D12), one `JudgeTask` holding this one
   entity (§5.5), run through `_run_agent` with a fresh driver (D3, D12); the
   retry budget is one round (the session ended without calling `verdict` ⇒
   ask once more); still no verdict ⇒ CHANGED.
4. **Decide** per §3.
5. **Write**, one transaction (`gate_write`, §6.4): mint iff CHANGED;
   `put_interpretation(...)` with the text, the wire fields and the gate
   fields, `interpreted_at` = eff\*(E) over `rec_cache` after this mint; on
   commit the record is put back into `rec_cache` (so "rec_cache == store"
   holds for every later eff\*).  Nothing about E is written before this step
   (D14): each gate writes once, at its own verdict, so an interrupted run
   loses only the answers still in flight, and the next scan re-lists them
   unchanged in shape.
6. **Propagate** (CHANGED only) per §5.3.1.

**Failures (D10).**  Steps 2–4 never raise past the task: an embedding failure
skips the prefilter for the rest of the run (`RunState.prefilter_disabled`,
§15.8; text §12 #5 through `_report(..., warn=True)`, once per run: the
caller that flips the flag is the one that reports —
`RunState.claim_prefilter_disable()`, §15.5 — so "skipped for the rest of the
run" and "printed once" are one operation even for the gates already inside
the failing call); the prefilter's one `embed` call is bounded by
`asyncio.timeout(_PREFILTER_TIMEOUT_S)` (a constant beside
`_GATE_SIMILARITY`, 60 s) because `embed` otherwise inherits the corpus
embedding's ten-step retry ladder (semantic_embedding.py:341-372, about 17
minutes), which is the right policy for a corpus pass and the wrong one for a
gate whose failure answer D2 already fixes; a judge session that ends in
`FatalAgentError`, or gives no verdict, resolves CHANGED (conservative,
converges, today's behaviour) and is written to the **host log only**
(`_log.warning`) — `except Exception` only, so a cancellation propagates.
Step 5's or step 6's failure is the store's own exception
(`lmdb.MapFullError`, `lmdb.Error`, `OSError`, `UnicodeEncodeError`,
`LookupError`, ...), propagated as it is — there is no wrapper class: nothing
matches a gate failure by class, and for a store failure the traceback is the
lead — after `exc.add_note(...)` through the `_note_on_failure(note)` context
manager (`except Exception` only, never a cancellation): step 5 notes
"while writing the interpretation of <E>", step 6 "while raising the
interpreted_at snapshot of <j>".  It fails the task group and therefore
`interpret_file` (session closed, theory not marked).  `interpret_file` owns
the `TaskGroup` and unwraps its `ExceptionGroup` before it leaves (`except
ExceptionGroup`, not `BaseExceptionGroup`: a group carrying `SystemExit` /
`KeyboardInterrupt` propagates untouched, D10): `_first_failure(eg) ->
BaseException` flattens the group, drops `CancelledError` leaves, logs every
leaf it does not report and RETURNS the first (an empty leaf list returns the
group unchanged); `interpret_file` raises the returned exception OUTSIDE the
`except` block (`failure = _first_failure(eg)` inside it, `raise failure`
after it), with no `from` — raising inside the handler would overwrite the
leaf's own `__context__` with the group, and the leaf's own cause and context
are what the traceback must show.  One bare exception, not a group, is also
what keeps the one-line user-error contract with ML (rpc.py sends the
formatted traceback and `Semantic_Store.extract_user_error` shows everything
after `USER_ERROR_MARKER`, so a group's gutter would reach the user).  The
judge's nested `_run_agent` keeps its own recycle budget.

**Corrections (D11).**  A re-submitted answer is recorded in
`task.results[i]`; if it is byte-identical to what is already there it does
nothing at all.  Otherwise: for a *queued* or *sent* entity it is simply the
answer; for a *done* entity the state goes back to *gating* and its gate is
started again — the same procedure, over the record its first gate wrote
(§3's R), so the verdict may differ from the first; for an entity whose gate
is running, nothing is started, because that gate picks the new text up
itself.  A gate never writes a text it did not judge: it captures
`task.results[i]` before the prefilter, judges that text, and — with no
`await` between the test and the write, so the value cannot move under it —
writes only if `task.results[i]` still equals it, otherwise it starts over on
the newer text.  The loop terminates because every extra round is paid for by
one distinct correction and corrections are finite; in a gate with no `await`
(step 3) it runs exactly once.  This is also what keeps the store in
agreement with `task.results`, which is what `interpret_file` returns to
Isabelle.

**Closing line** per theory (§12 #7): the number of entities this run
interpreted — entities, not writes, so a corrected entity counts once (§12) —
and the cost.

### 5.5 Tasks, tools and the agent runner

`_run_agent(make_driver, task)` takes its task explicitly.  The
`_local_task` ContextVar is deleted: `_answer_tool` becomes
`mk_answer_tool(task)` and the judge's tool `mk_verdict_tool(judge_task)`,
closure factories, so the interpretation task and the many concurrent judge
tasks can never be misrouted;
`mcp_server.build_mcp_server`'s `bind_context` keeps `Connection.set_current`
and loses its `_local_task` half.

`AgentTask` base owns: connection, theory identity, `entries`,
`results` (a list index-aligned with `entries`, like `state`) and
`_label_to_idx` with the duplicate-label raise,
`batch` (the indices in flight, for `batch_remaining`; no cursor), `api_retry_errors`,
driver/model, `max_stalled_retries`, three task-supplied strings (retry
prompt, stall warning, unanswered-failure message), the abstract renderer
`format_entries(indices)` that the retry loop (semantic_interpretation.py:802)
and the batch-remaining reply (:643) call (the interpretation task's is
today's, with `_collapse_provenance`; the judge's renders pairs), and
`cost_prefix` (`b""` / `b"judge_"`).  Cost: every task keeps today's
accumulators and `accumulate_usage` (interpretation_driver/__init__.py:193-220)
is unchanged; `write_cost` folds a task's delta into the unprefixed
theory-status keys as today and, for prefix `b"judge_"`, additionally into
`judge_input_tokens`, `judge_cache_creation_tokens`, `judge_cache_read_tokens`,
`judge_output_tokens`, `judge_cost_usd` (additive keys), so the judge figures
are a breakdown of the totals; the run's reported cost is the interpretation
task's plus the judges' (§15.9).
`InterpretationTask(AgentTask)` adds the queue, the entity states, `on_answer`
(starts the gate task) and `build_prompt`; `JudgeTask(AgentTask)` holds one
entry, renders its pair and records its verdict, and has no database writer.  Every `task: "InterpretationTask"` annotation is
re-typed to the base: `make_interpretation_driver`, `accumulate_usage`,
`InterpretationDriver.__init__` (interpretation_driver/__init__.py:161),
`mcp_server.build_mcp_server` (:99) and
`InterpretationMCPServer.register_session` (:254).

**Judge session.**  `make_interpretation_driver(driver_name, model=model,
system_prompt=_JUDGE_SYSTEM_PROMPT, tools=[mk_verdict_tool(judge_task)],
task=judge_task, on_context_reset=noop, cli_tools=False)`.  Permissions are
derived, never listed: `SERVER_NAME` moves from mcp_server.py to beside
`AGENT_DIR` in `interpretation_driver/__init__.py`, read by mcp_server.py,
claude_code.py and codex.py (codex.py:53 imports it from mcp_server today);
`_TOOL_WHITELIST` shrinks to the CLI built-ins and is renamed `_CLI_BUILTINS`;
the derived set feeds BOTH `allowed_tools` and the PreToolUse hook (§15.6);
`_permission_control` becomes a closure inside `_options()`; `allowed_tools` =
`mcp__<SERVER_NAME>__<t.name>` for `t in self.tools` plus the built-ins iff
`cli_tools`.  The `mcp__isabelle_semantics__*` literals in prompts are prompt
text.  Codex derives from `self.tools` already; its read-only sandbox still
lets the judge read files (recorded deviation).  DeepSeek inherits.

The `verdict` tool takes `{same: bool, why: str}` for the session's one
entity (D12: no entry list, no addressing), records it on the `JudgeTask`,
replies "Verdict received. Stop now.", writes nothing.  Whether an entry is
judged is decided by its digest (§15.5), never by its kind, so no kind list
is needed in code.  Prompt: the entity's kind and name, Description 1 always the baseline,
Description 2 always the fresh text.  Deviations from the measured comparator
(model, effort, kind list) are recorded in the docs.

### 5.6 Callback prerequisite and startup check

`_resolve_embedding_config` issues `Config.lookup` callbacks (static context)
and `send_for_interpretation`'s callback list has none.  `interpret_with_parallel`
builds `Config.make_config_lookup_callback (Context_Callbacks.static_context_unpacker
cfg_context)` once, beside the driver read, and threads that `callback'` -- not
the context it was made from -- through `interpret_cone` and `interpret'`
beside `driver` (one ML parameter, no wire change; `interpret_with_parallel`
calls `interpret'` directly for its `Context.Proof` roots as well as through
`interpret_cone` -- both call sites), where `interpret_file_callbacks config_cb
context` (exported, so a test can assert on the list) puts it beside the
node's entity callbacks: the user's context governs the prefilter (D5), and
because the threaded value is a callback rather than a context, no cone
node's context can be substituted for it (step-6 review, `review_step6/judge.json`).

**Startup check** (once per cone run, in `interpret_with_parallel` after the
opening block and before any theory starts, and only when the run has
something to interpret -- the opening block's own `n_units = 0` guard, so a
nothing-to-do resume prints neither line): one RPC
`Semantic_Store.check_embedding_service`, carrying that same callback value,
resolves the embedding configuration (`_resolve_embedding_config`: driver,
base URL, model name, API key) and constructs the provider, which is where the
model's dimension is looked up (`Embedding_Provider.__init__`,
semantic_embedding.py:288).  Failure -- any exception of the resolution or of
the construction -- ⇒ text §12 #4 once, its slot `str(exc) or the class name`
as in #5, through `_report(..., warn=True)` (user-visible, like the function's
own warning it replaces), and `RunState.prefilter_disabled` is set for the run
(§15.8, D2).  An RPC-level failure of the check is fatal, as
`send_for_interpretation`'s is: while the connection is healthy the only way
it can fail is a Python half that predates the gate, and running that half
silently would be worse than stopping (step-6 review ruling).
`_resolve_embedding_config` already warns with the full setup text before
raising (semantics.py:2778-2779, deliberately); it gains `warn: bool = True`,
the startup check passes `warn=False` and prints #4 itself, so the hint
appears once (D16); `semantic_vector_store` threads `warn` through so the
per-theory resolution of §15.8 never repeats it.  Network reachability is
only known at the first call (§5.4 step 2's failure path).

## 6. Storage

### 6.1 Record field

`baseline_interpretation: str | None` at index 14, codec 14 → 15: `_decode`'s
pad literal, slice, unpacking tuple and docstring; `_encode`; `RECORD_FIELD_COUNT`
(semantics.py:168) that `unpack_fields` pads to.  Earlier indices unchanged;
`_EMBEDDED_DOC_FIELDS` not extended; the two completed one-off migration passes
hard-code 14 fields and must be re-read before ever being re-run.  `None` for
theorem-alike, collection / method, experience and persistent records.  No
offline migration.

### 6.2 Why a separate field

After an UNCHANGED verdict the stored `interpretation` is the fresh text (the
record keeps the wording written for the current source) while the baseline
stays the text written at the last mint, so every later verdict compares
against the last *minted* meaning and small "unchanged" drifts cannot
accumulate into an unnoticed change (D4).  Storing text rather than a vector
also makes an embedding-model change harmless.

### 6.3 Counter

Unchanged (`0xF0`, user env).  Minted only inside `gate_write`, in the same
transaction as the record that stores the minted value (D14); the scan and a
dry run never touch it (`counter_snapshot()` reads it without the put
`counter_value` makes on a fresh store, §15.8), and their only write is the
dry path's statement refresh (§15.8 item 6).  Invariant: no stored `version`
or `interpreted_at` exceeds the counter.

### 6.4 Field-disjoint writes

One entry point on `Semantic_DB` (two puts), all built on
`backfill_field`'s per-key body (`_raw_for_update` → `_decode` →
`Record._replace` → `_encode` → `txn.put`, shared as `_put_fields`), not on
`update_expr`'s positional shape (which would fail at index 14 on 14-field
records).  One shared helper (`_check_raw_put_grant`) holds
`backfill_field`'s "field ∉ `_EMBEDDED_DOC_FIELDS` unless invalidating"
assert.

- `gate_write()` — a context manager yielding one write transaction
  (`Gate_Writer`) with `counter_value()` (ε), `mint()` (`counter_next`) and
  two puts: `put_interpretation(key, *, kind, name, expr, interpretation,
  locale_provenance, theory_constituents, position, from_collection,
  semantic_digest, deps, version, interpreted_at, baseline_interpretation)`
  — the whole record, **invalidates vectors first** (the text changes),
  creates the record when absent and resurrects a tombstoned key; the one
  write of §5.4 step 5 — and `update_gate_fields(key, *, semantic_digest,
  deps, version, interpreted_at, baseline_interpretation)` — gate fields
  only, no vector invalidation, the snapshot raise of §5.3.1.  The gate-field
  names are asserted disjoint from `_EMBEDDED_DOC_FIELDS`; the body is
  synchronous and opens no second write transaction.

Step 1 implemented `update_interpretation` (a text-only write for the
original D11) and `gate_write` with `update_gate_fields`; step 3 adds
`put_interpretation` and DELETES `update_interpretation` with its tests, so
`gate_write` is the only way an interpretation reaches the store (§13).

Crash shapes (D10): (i) answered, not yet written — nothing on disk, the entry
is re-listed by the next scan by the very criterion that enrolled it; (ii) the
write aborted — nothing written, counter untouched; (iii) a correction whose
gate write fails — the first gate's write stands, complete and fresh by the
scan's criteria, so the next run does not re-ask the entity and the
correction is lost; the run fails and the theory is not marked (the user
judged this harmless on 2026-09-09: the first interpretation is valid).  No
mint ever commits without the record that stores it; shapes (i) and (ii) lose
no signal the next scan needs, and shape (iii) loses a correction, loudly.

## 7. The prefilter constant

`_GATE_SIMILARITY = 0.90`, a cosine on the document text (`|doc` column of
`pairs_phase2.json`), measured on a provider configured `normalize: true` where
dot and cosine coincide, so the value carries over.  Strict populations:
tracked kinds 0/24 misses, 6/136 needless (4/136 at 0.80–0.85); all kinds
0/87, 14/663.  Free band (0.7824, 0.8685]; 0.90 sits above it as margin against
vague fresh paragraphs.  `REPORT_PHASE2.md`'s 0.70 is an
interpretation-paragraph number and does not carry over.

## 8. The interpretation lock

### 8.1 Python side

`filelock.FileLock(<semantic_DB_dir()>/INTERPRETATION_LOCK_NAME, timeout=0,
thread_local=False)` (the package depends on `filelock`;
`snapshot_sync._install_lock` is the precedent; constant beside
`INSTALL_LOCK_NAME`).  Two instances in one process exclude each other; the OS
drops the lock when the holder dies; a failed acquire leaks nothing.  Owned by
the RPC **connection** that acquired it: `Semantic_Store.try_acquire_interpretation_lock`
→ bool appends to the acquiring `Connection`'s `on_close` one `release`
closure that holds the FileLock and the run's `RunState` (§15.8), and only
then publishes the `RunState` in the module-level slot `_locked_run` that
`current_run_state()` reads; the closure clears the slot (if it still holds
this run) and releases the lock.  Nothing is set as an attribute of the
connection -- the closure IS the ownership; the slot is needed because the
run state's consumers (`interpret_file`, the §5.6 startup check) run on
OTHER, pooled connections, while the lock connection carries nothing but the
acquire.  `Isabelle_RPC_Host.rpc.Connection` gains the `on_close` callback
list, run by `close()` at most once (a `_closed` flag: `close()` is reached
both from `handle_client`'s `finally` and from `Connection.__aexit__`); a
callback that raises is logged and the others still run.  No release
procedure, no sidecar.  The release is asynchronous to the ML caller:
`close_connection` only closes the socket, and the host runs the closure when
it sees EOF, so an acquire issued immediately after a run returns may still
be refused (the ML test waits within a bound).

**Release ordering.**  On an ML interrupt, `schedule_dag` cancels the group and
returns without joining, so the lock connection's close is not ordered against
the workers' connection closes; each worker's socket is closed by
`call_command`'s finaliser, and rpc.py cancels that worker's handler 3 s after
*its* socket closes.  A cancelled handler's residue may therefore still run a
`gate_write` (which can mint) after a second run has acquired the lock.  No
record can be corrupted (each write is one transaction); a run that already
read the pre-mint record can miss the mint, bounded by `schedule_dag`'s
ancestor-before-descendant order across theories and by §5.3.1's enrolment
and snapshot raise inside a theory; the one surviving corner — an
interrupted forced run over a theory already marked in this process — is
recorded in `doc/invalidation_limitations.md` (§11).

### 8.2 ML side

`with_interpretation_lock : (unit -> 'a) -> 'a option` in semantic_store.ML,
combining two RPC.ML idioms -- the finaliser armed first
(`\<^try>\<open>launch_body () finally ...\<close>`, RPC.ML:815-826) and the
connect-and-record uninterruptible bubble (RPC.ML:779-791);
`Thread_Attributes.uninterruptible_body` (thread_attributes.ML:21) keeps
`get_connection ()` interruptible inside the bubble through `run` -- the same
form `schedule_dag` already uses, and the one `Isabelle_Thread.try_finally`,
i.e. `\<^try>\<open>… finally …\<close>` itself, is built from
(isabelle_thread.ML:186):

```
fun with_interpretation_lock body =
  let val conn : connection option Unsynchronized.ref = Unsynchronized.ref NONE in
    \<^try>\<open>
      let
        val c = Thread_Attributes.uninterruptible_body (fn run =>
                  let val c = run get_connection () in conn := SOME c; c end)
      in
        if (call_command' try_acquire_cmd c ()
              handle Remote_Calling_Failure {message, ...} => interpretation_rpc_error message)
        then SOME (body ()) else NONE
      end
    finally
      (case ! conn of SOME c => (try close_connection c; ()) | NONE => ())\<close>
  end
```

The finaliser is armed before the connection exists, so no interrupt can leave
a connection unguarded; `get_connection ()` stays interruptible inside `run`
(it may launch a host) and so does `body ()`; the `NONE` arm is live (an
interrupt inside `get_connection`).  The connection is never released to the
pool: closing it is what releases the lock.  `close_connection` (RPC.ML:334)
gains a `REMOTE_PROCEDURE_CALLING` signature entry.

`interpret_with_parallel` is wrapped at its definition and returns
`unit option`.  `NONE` handling (texts §12): the callback arm of
`make_interpret_theory_callback` (used by `update_interpretations` for the `by
aoa` startup check and `_auto_embed`) — `writeln` #1, return `([], ~1)` (a
convention only: `update_interpretations` discards the live callback's result,
semantics.py:1850, 1885, so Python needs no change for this arm);
`interpret_command.ML`'s `go ()` — `error` #2; the collect app — `error` #3
(propagates through the streaming app; the CLI reports `Failed.`, exits
non-zero); the exported `interpret` — `error` #2, reused deliberately: it has
no caller in the repository and `run_semantic_interpretation` is the only user
command on this path (D17).  `dry_run` is not wrapped.

### 8.3 Scope and caveats

Scope = the database directory (`SEMANTIC_DB_DIR`).  NFS: flock over NFS is
emulated with POSIX record locks, which do not conflict between two descriptors
of one process, so the cross-process half works while the same-instance half
silently does not; same remedy as for LMDB.

## 9. What does NOT change

Persistent theories; theorem-alike entities (D15); the unified dep criterion;
the (process id, theory serial) skip; the counter; the SCC memo; the ε epoch;
prune / orphans; the CI export filter; the entry wire format and the
`interpret_theories` callback schemas; the threshold value 400;
`update_interpretations`' structure apart from the count's meaning (D7) and
the texts (§12 #6, #9–#11).

## 10. Tests

pytest (isolated `SEMANTIC_DB_DIR`, fabricated wire entries, stub connection,
fake driver and fake provider injectable), driving the production scan, the
queue loop and the per-entity gate:

- eff\*: ported verification assertions (soundness, forced-CHANGED equals
  today, order independence, raw-phrasing counterexample, None/ε/missing
  cases, A→B→C shield, direct dependency on A not shielded);
- enrolment (D13): digest-only change on A with fresh dependents B, C — only
  A is a seed; B enrolled after A's CHANGED, C after B's CHANGED, nothing after
  an UNCHANGED; a dependent enrolled after the queue emptied is still
  interpreted (the loop waits for gates); every entity interpreted at most
  once per run in every wire-order permutation of a seed set that contains
  both a dependency and its dependent;
- snapshot raise: B done before A's verdict, A CHANGED ⇒ B's `interpreted_at`
  rises to the new eff\*, B is not re-interpreted, B's own dependents are not
  enrolled through the raise; the next scan finds B fresh;
- gate decision table (§3) per entity, including forced CHANGED with no judge
  call for a legacy record, the theorem-alike and persistent rows (no judge,
  today's fields); no-verdict ⇒ CHANGED; judge `FatalAgentError` ⇒ CHANGED,
  log only, no recycle; embedding failure ⇒ prefilter skipped, judge alone;
  a failed gate write fails the run with the store's own exception, its note
  naming the entity: session closed, theory not marked;
  `CancelledError` propagates and cancels running gates;
- queue loop: a fake driver raising `RateLimitError` mid-turn with part of the
  batch answered — after the recycle every entry ends non-`None`, none
  interpreted twice, none lost; gates started before the recycle finish and
  write; an entry answered before its batch goes out (the whole seed set is
  enqueued up front while a batch is `_BATCH_SIZE`) is not re-sent by
  `next_batch`, so no written entity returns to `_SENT` and the retry rounds
  do not give up on it; the rate-limit backoff doubles, caps at 60 s, jitters
  by ±50 % and resets after a completed turn (`[2, 4, 8, 16, 32, 60, 2]`);
  a cancellation laundered by the judge driver's teardown still writes and
  mints nothing;
- D18: inside a session the `query` tool's name lookup, notation fallback
  and short-name fallback, and the desugar tool's annotations, disclose no
  stored interpretation of the theory's entities, enrolled or not, while an
  entity of another theory is served; the provenance hint the ML side
  composes likewise omits the stored text of this run's own entries (ML,
  not reachable from pytest); a run of sibling facts whose hint carries no
  `Locale "…":` line still collapses on the head line;
- D19: an empty wire statement leaves the stored `expr` (dry path:
  byte-identical record; live path: the gate's write keeps the stored `expr`
  while the interpretation and version change);
- rec_cache write-back: an UNCHANGED entity written earlier in the run is a
  wall for every later eff\* in the run;
- concurrency: several gates in flight at once write correct, distinct
  records; at most 40 judge sessions are open at once; each judge session
  receives exactly one entity; an unrequested answer is rejected;
- prefilter: same directions at norm 20 and norm 1 give the same verdicts; a
  zero vector counts as not computable;
- corrections: a re-submitted answer for a done entity runs a second gate —
  one that changes the meaning mints and propagates, one that does not leaves
  the version standing; a correction landing while the gate is judging is
  re-judged, not adopted (the stored text and its verdict always come from the
  same text); a byte-identical resubmission starts no gate at all;
- crash shapes (i)–(ii); a write aborted mid-transaction leaves store and
  counter byte-identical; creation-from-absent and tombstone resurrection; a
  `from_collection` record whose enumerated name changed rewrites `name` and
  tombstones its vector; the gate writer checks the very dict it puts (an
  embedded-document field in it raises, an unknown field raises, and
  `update_gate_fields` really routes its five fields through
  `_check_raw_put_grant`); legacy-arity round trip (12-, 13-, 14-field tuples through
  `update_gate_fields`, 15 read back; `put_interpretation` writes the three
  formerly truncated fields itself and is arity-invariant, so it is pinned
  once, on a 12-field record whose `experience` / `goal_patterns` must
  survive the put);
- statement refresh: a theory whose only difference is one `prop_str`, with
  one uncached entry beside it, quotes 1 on a dry run, leaves record and
  counter otherwise byte-identical, and still ends with that `expr`
  refreshed and its vector invalidated; the seed count is exact at zero;
- an unconfigured embedding service (startup check failed) completes the
  run with every gate judged and no error; the decision table's WIP
  collection / method row (all gate fields None);
- JudgeTask cannot write; judge stall text is judge wording; `allowed_tools`
  for a judge driver is exactly the `verdict` name; the interpretation task
  and concurrent judge tasks route correctly (update
  `archive/tests/test_interpretation_driver.py`,
  `test_interpretation_mcp_server.py`);
- cost: `cost_usd == interpretation + judge`, `judge_cost_usd <= cost_usd`;
- ML (Test/): `"Config.lookup"` among interpret_file's callback names; the
  three `NONE` behaviours of the lock; interrupt during the acquire round trip
  leaves the next acquire succeeding;
- lock: two processes on one `SEMANTIC_DB_DIR`; two instances in one process;
- post-run invariant: every stored version and interpreted_at ≤ counter;
- non-LLM regression from `pairs_phase2.json` + `judge_phase2.json`: 0 tracked
  misses at 0.90 on the `|doc` column;
- interactive scaffold: production driver as judge on `Sim_Measure_B.thy` vs
  `Sim_Measure_A1.thy`; a live run's host log must show judgements.

## 11. Documentation updates

- `CHECK_OUTDATE_PLAN.md`: §3.1's construction point (`write_answer` →
  `Gate_Writer.put_interpretation`, field count 15); §4.1 → eff\*; §4.2
  I2/I3, and I4's second clause ("interpreted_at is updated only at
  re-interpretation") → "or raised by a later mint of a dependency in the
  same run (§5.3.1 snapshot raise)"; §8 discipline 3 (the scan and a dry
  run write nothing but the dry-path statement refresh; the live refresh
  runs after the LLM work — reversing "the scan's own bump may be written")
  and 4 (snapshot at the entity's own write, after its mint, raised when a
  dependency mints later in the run; sound because a run's theory values are
  immutable and concurrent runs are excluded by the lock, up to rpc.py's 3 s
  grace after a worker connection closes, during which a cancelled handler's
  gate write may still mint); §8's pipeline block; §8 metering: the dry run
  count is the sum of the seed sets, neither bound over a cone (§5.2),
  shown as "About n"; §14's dry-run row: the "quote = actual work" assertion
  is **retired**, replaced by "n = 0 iff the following live run sends none"
  (the step-8 review refuted the interim "n ≤ …" row, 2026-09-12); glossary.
- ML and Python sites that state the retired equality or the scan-time
  bump, found by grepping for `metering`, `quote`, `actual work`, `by
  construction`, `would be asked` (not for a local `n`): semantic_store.ML
  :39-48, :1447-1451, the dry-run comment, and :2199-2207 — whose
  de-duplication below the proof channel is justified there ONLY by the
  retired equality and must be restated on a premise that survives ("no uk
  may be counted twice inside one dry run, or n overstates the seed set");
  interpret_command.ML:94-98; semantic_interpretation.py:890-894 (the scan
  comment) and :1228-1240 (the completeness-invariant comment, restated per
  §15.4: every `results` non-None AND every gate joined without raising).
- `doc/invalidation_limitations.md`: new #7 (a false "same" leaves the
  entity's exclusively-downstream dependents stale until the next upstream
  change; judge rate about 1 % on a lemma-dominated population, 0/24 on the
  tracked kinds with type class and type unmeasured; 0.90 backstop; 0.6 missed
  re-interpretations per false verdict at 1 %); the production judge's
  deviations from the measured comparator; the interrupted-forced-run corner
  of §8.1.
- README §5: one sentence on the gate.

## 12. User-visible texts — all approved 2026-09-08

1. `by aoa` / `_auto_embed`, lock busy (writeln):
   `[Semantic_Embedding] Another semantic interpretation run is in progress on this database; skipping the automatic update. The proof continues with the interpretations already stored.`
2. `run_semantic_interpretation`, lock busy (error):
   `run_semantic_interpretation: another semantic interpretation run is in progress on this database. Wait for it to finish, then run the command again.`
3. `Semantic_Store.collect`, lock busy (error):
   `Semantic_Store.collect: another semantic interpretation run is in progress on this database. Two runs must never share a database; wait for the other run to finish, then retry.`
4. Startup, embedding service not configured (once per run):
   `[Semantic_Embedding] The embedding service is not configured: <existing message with the settings hint>`
   (the existing message verbatim, "The system cannot continue." included --
   the user's ruling of 2026-09-11 on the step-6 review's proposal to drop or
   reword that sentence for this site: leave it)
5. Mid-run, embedding call failed (once per run):
   `[Semantic_Embedding] The embedding service did not respond: <error>`
6. After the user clicks Yes in the AoA startup dialog:
   `[Semantic_Embedding] Choice received.`
7. Closing line per theory (approved 2026-09-08, rev 5 wording):
   `[Semantic_Embedding] <theory>: <A> entities interpreted; cost $<x>.`
8. Isar command confirmation (re-approved 2026-09-12 with "About": the
   dry-run count is neither bound over a cone, §5.2; n = 1 reads
   `1 entity … is`):
   `[Semantic_Embedding] About <n> entities in the following theories are new or outdated:` / `<theory list>` / `The run interprets these and, where a meaning changed, their dependents.` / `This calls the LLM: it may take a long time and cost money.` / `Afterwards, missing vector embeddings are computed as well (embedding API; far cheaper).`
9. AoA startup dialog (re-approved 2026-09-12; the existing NOTE paragraph
   sits between the two parts):
   `[Semantic_Embedding] About <n> entities in the following theories are new or outdated: <theory list>` … `The run interprets these and, where a meaning changed, their dependents.` / `This calls the LLM: it may take a long time and cost money. Proceed?`
10. Below-threshold tracing line (re-approved 2026-09-12; `entity … its` at
    n = 1, `theory` at M = 1):
    `[Semantic_Embedding] interpreting about <n> new or outdated entities in <M> theories, and their dependents where a meaning changed`
11. Non-interactive warning (re-approved 2026-09-12; `theory` at M = 1):
    `[Semantic_Embedding] About <n> entities in <M> theories are new or outdated and were not interpreted automatically. This can degrade AoA's retrieval quality. Run run_semantic_interpretation to update them.`

12. Dry-run comment at both dry-run sites (approved 2026-09-08, rev 5
    wording; the text is in §5.2).

The four lines below existed before this plan; their numbers are re-derived
from the entity states (§15.8): N = the entries enrolled so far (the seed
set plus every dependent enrolled by a CHANGED verdict, so N can grow during
a run and never shrinks; `count(state != _NOT_ENROLLED)`), k = the entries
answered so far (`count(state in {_GATING, _DONE})`), m = the enrolled
entries still unanswered run-wide (`count(state in {_QUEUED, _SENT})`).
A (#7's number) is derived the same way: `count(state == _DONE)` at the end
of the run — the entities this run wrote, counted once however many gates
each needed (D11).  The set `{_GATING, _DONE}` is closed under D11's *done*
→ *gating* edge, so k never falls.
Approved 2026-09-08:

13. Per-answer progress line (unchanged wording; N as above):
    `[Semantic_Embedding] <theory>: <k> of <N> done.`
14. Stalled-retry warning (unchanged wording; m = the enrolled entries still
    unanswered run-wide, N as above):
    `[Semantic_Embedding] <theory>: <m> of <N> entities still have no interpretation; asking the LLM again (attempt <i> of 10).`
15. The give-up error (unchanged wording; m and N as in #14):
    `Semantic interpretation failed: theory <theory> left <m> of <N> entities uninterpreted after 10 retry rounds: <names>` / `The theory has NOT been marked as interpreted; re-running will retry it.`
16. The per-theory opening line, one of three (T = the theory's entity count,
    M = the entries filled from the store, K = the seed count):
    `[Semantic_Embedding] <theory>: all <T> entities are already interpreted in the semantic database, nothing to ask.`
    `[Semantic_Embedding] Interpreting <theory>: <T> entities; <M> are already interpreted, asking the LLM for <K> (or more).`
    `[Semantic_Embedding] Interpreting <theory>: <T> entities, none are in the semantic database yet, asking the LLM for all <T>.`

Host-log only (never shown): judge session failed; judge gave no verdict for
some entries.

Not user-visible, not subject to approval: the judge system prompt (as in rev
3, kinds constant / type / typeclass / locale), the `answer` tool's
batch-complete reply, identifier names.

## 13. Implementation order

1. Record field + codec + `update_interpretation` + `gate_write` + shared
   assert helper (§6); tests.  (`update_interpretation` and its tests are
   deleted again in step 3: the revised D11 leaves it with no caller.)
2. eff\* in `eff_uk`/`eff_value` (§4); port the verification tests.
3. `Gate_Writer.put_interpretation` and `Semantic_DB.counter_snapshot`
   (§6.4, §15.8); `AgentTask` split, explicit `task`, tool factories (delete
   `_local_task`), the queue loop in `_run_agent` as a plain loop with the
   throttle arms' jitter and capped backoff (§15.4), the gate task group
   with `ExceptionGroup` unwrapping — `_first_failure`, the store's own
   exception with a note, no wrapper class (§5.3, §5.4, §5.5);
   `write_answer` replaced by `on_answer` (records the answer, starts the
   gate — including a second gate for a correction of a written entity,
   D11); `Semantic_DB.update_interpretation` and its tests deleted;
   `n_interpreted` derived from the states instead of counted at the write;
   the scan's per-entry `(version, interpreted_at)` pair stays as a
   step-3-only task field (§15.11) and is deleted in step 4; the
   completeness-invariant comment restated (§11).
4. Scan rewrite: local staleness, theory-internal graph and its reverse, seed
   set, queue; dry run = seed count with the approved comment;
   statement refresh.
5. Gate per entity: which rows need a judge, prefilter (explicit cosine),
   `JudgeTask` + `verdict`, decisions, the write with rec_cache write-back,
   propagation and the snapshot raise, failure handling; derived permissions,
   `SERVER_NAME` move, `cli_tools`.
6. `Config.lookup` callback with `cfg_context`; startup check RPC (§5.6).
7. Lock: Python procedure + `Connection.on_close` + ML
   `with_interpretation_lock` + the four call sites (§8).
8. Texts (§12; the sites are found by grepping for each current text's
   distinctive words, and for the §11 phrases, not by line number), docs
   (§11).

## 14. Load-bearing facts carried from the eff\* verification

The gate and eff\* ship together (D6); a dependent is enrolled by its
dependency's CHANGED verdict, and a dependent already written when a
dependency mints has its snapshot raised instead of being re-judged (§5.3.1);
the only second verdict on a written entity is the one its own correction
triggers (D11), and that one mints and propagates exactly like a first, so
§5.3.1's enrolment argument is untouched; no provisional number ever reaches a
stored `interpreted_at` (mints only
inside `gate_write`, each snapshot taken at its own write after that entity's
mint).  The verification's soundness result was measured on a prototype with
topologically ordered enrolment; the queue's soundness rests on the argument
of §5.3.1 (every stale entity is either a seed or enrolled by the mint that
made it stale; a written entity's raised snapshot is exact) and on the §10
enrolment and snapshot-raise tests.

## 15. Code-level design of steps 3–5 (semantic_interpretation.py)

This section is the implementation blueprint the reviewers judge and the
implementer follows.  Names are final unless a reviewer shows a better one;
every behaviour here is either a decision of §2 or a derivation of one, and
the derivations say which.  Line numbers refer to the file as it is after
§13 steps 1–2.

### 15.1 Module layout

New or changed top-level names, in file order:

| name | kind | role |
|---|---|---|
| `_GATE_SIMILARITY = 0.90` | constant | §7 |
| `_PREFILTER_TIMEOUT_S = 60` | constant | §5.4 failures |
| `_JUDGE_SESSIONS = asyncio.Semaphore(40)` | module-level | D12 |
| `_first_failure(eg) -> BaseException` | helper | §5.4 failures: selects the leaf `interpret_file` raises (outside its `except`) from the gate task group's `ExceptionGroup` |
| `_note_on_failure(note)` | context manager | §5.4 failures: `exc.add_note(note)` on any `Exception` leaving a store write; the exception itself propagates |
| `_stop_if_cancelled()` | helper | §15.4: called first in every recovering arm of `_run_agent`; raises a `CancelledError` (the arm's laundered exception kept as its context) when the current task is being cancelled, so no `except Exception` above can absorb it |
| `class RunState` | | §15.8 run-scoped state, owned by the lock (§8.1) |
| `_NOT_ENROLLED, _QUEUED, _SENT, _GATING, _DONE = range(5)` | constants | the entity states of §5.3.1 |
| `_JUDGE_SYSTEM_PROMPT` | constant | §15.6 |
| `class AgentTask` | base class | §15.2 |
| `class InterpretationTask(AgentTask)` | | §15.3 |
| `class JudgeTask(AgentTask)` | | §15.6 |
| `def mk_answer_tool(task: InterpretationTask) -> SdkMcpTool` | closure factory | replaces the module-level `_answer_tool` (:577-651) and the `_local_task` ContextVar (:536) |
| `def mk_verdict_tool(task: JudgeTask) -> SdkMcpTool` | closure factory | §15.6 |
| `async def _retry_unanswered(driver, task)` | | the retry loop lifted out of today's `_run_agent` (:761-810), scoped to `task.batch` |
| `async def _run_agent(make_driver, task)` | | the queue loop, §15.4 |
| `async def _gate(task: InterpretationTask, idx: int, ...)` | coroutine | the per-entity gate, §15.5 |
| `async def interpret_file(...)` | | scan (§15.8), task group, closing line |

Deleted: `_local_task`, `InterpretationTask.batches`, `.current_batch`,
`.batch_range`, `.advance_batch`, `.inv_fields`, `_msg_unanswered`'s callers
outside the task (the function stays, called by
`InterpretationTask.unanswered_failure`).

### 15.2 `AgentTask`

```python
class AgentTask:
    cost_prefix: bytes = b""                     # b"judge_" on JudgeTask (§15.9)
    batch_size: int = _BATCH_SIZE                # fixed when the task is built; tests set it per task

    def __init__(self, connection, file_path, theory_longname, theory_key,
                 entries: list[Entry], driver: str = _DEFAULT_DRIVER, model: str = ""):
        # today's fields (:300-378): connection, file_path, theory_longname,
        # theory_key, entries, driver, model, _label_to_idx (with the
        # duplicate-label raise; the map is its own seen-set), total_* and
        # run_* cost accumulators, api_retry_errors
        self.results: list[str | None] = [None] * len(entries)   # index-aligned with entries, like state
        self.state: list[int] = [_NOT_ENROLLED] * len(entries)
        self._queue: deque[int] = deque()
        self.batch: list[int] = []               # indices sent in the turn in flight
        self.gates_running: int = 0
        self._progress = asyncio.Event()         # set when a gate finishes or enrols
        self.theory_keys: frozenset[bytes] = frozenset(e.universal_key for e in entries)   # D18: what the lookup tools hide

    # the queue (§5.3)
    def enqueue(self, idx) -> None:
        # results[idx] = None; state = _QUEUED; append; _progress.set()
    def next_batch(self) -> list[int]:
        # [i for i in self.batch if state[i] == _SENT]      (only after a recycle)
        # + popleft until self.batch_size, each marked _SENT; stored in self.batch; returned
    def unanswered_in_batch(self) -> list[int]:   # state == _SENT within self.batch
    def unanswered(self) -> list[int]             # state in {_QUEUED, _SENT}: m of §12
    def enrolled(self) -> int                     # count(state != _NOT_ENROLLED): N of §12
    def answered(self) -> int                     # count(state in {_GATING, _DONE}): k of §12
    def n_interpreted(self) -> int                # count(state == _DONE): A of §12 #7 -- the entities this
                                                  # run wrote, counted once however many gates each needed
                                                  # (D11).  No counter field; both readers (the host-log
                                                  # line and the closing line) run after the group joined
    async def wait_for_progress(self) -> None:    # await _progress.wait(); clear
    def gate_started(self) / gate_finished(self)  # counter; finished sets _progress

    # supplied by the subclasses
    def format_entries(self, indices) -> str
    def build_prompt(self, indices: list[int]) -> str
    def on_answer(self, idx: int, text: str) -> None
    def retry_report(self, n_missing: int, attempt: int) -> str   # "" = no line
    def retry_prompt(self, chunk: list[int]) -> str
    def unanswered_failure(self, missing_names: list[str]) -> str

    # cost: historical_cost() and write_cost() as today (:404-469), write_cost
    # folding the delta into the unprefixed keys and, when cost_prefix is set,
    # into the prefixed keys too (§15.9)
```

Why a base class: `_run_agent`, the drivers (`accumulate_usage`, the Claude
driver's `api_retry_errors` and model backfill, the Codex driver's cost
flush) and `mcp_server.build_mcp_server` all take "the task"; the judge needs
the same session machinery with one entry and no queue semantics beyond that
entry.  Every `task: "InterpretationTask"` annotation in the driver package
is re-typed to `AgentTask` (§5.5 lists the five).

### 15.3 `InterpretationTask`

```python
class InterpretationTask(AgentTask):
    def __init__(self, connection, file_path, theory_longname, theory_key, entries,
                 driver=_DEFAULT_DRIVER, model="", *, unicode_file_path: str = "",
                 dependents: list[list[int]] | None = None,
                 emb_store: Semantic_Vector_Store | None = None,
                 run_state: RunState | None = None,
                 make_judge_driver: Callable[[JudgeTask], InterpretationDriver] | None = None):
        self.unicode_file_path = unicode_file_path or file_path
        self._first_turn_sent = False
        self.dependents = dependents or [[] for _ in entries]   # theory-internal reverse graph
        # The record per universal key AS CURRENTLY STORED: filled by the scan,
        # written back from inside every gate transaction (§15.5 step 5, §15.8).
        # The scan's pre-run `recs` stays a local of the scan: the task carries
        # no pre-run record, so no gate can read one (a second gate reading the
        # pre-run record would roll a committed mint back, §3).
        self.rec_cache: dict[bytes, SemanticRecord | None]
        self.emb_store = emb_store                 # None: prefilter skipped for this theory (§15.8)
        self.run_state = run_state                 # the run's RunState (§15.8), one per interpret_file
        self.make_judge_driver = make_judge_driver
        self.judge_cost: CostSummary               # sum of finished judges' run_* (§15.9)
```

(No `n_interpreted` field: the number is derived on `AgentTask`, §15.2.)

`build_prompt(indices)` is today's (:517-533) with the file path and theory
name read from the task and the first-turn distinction from
`_first_turn_sent`.  `format_entries` is today's.  `_collapse_provenance` keys the collapse on
the head line alone (`if head is not None and (head, locale) == prev`): D18
removes the `Locale "…":` line whenever the instantiated locale is an entry
of this run, and the former two-line key would silently stop collapsing
exactly there -- the sibling runs D18 was introduced for.  Where the locale
line is present the rendered bytes are identical to today's.
`retry_report` / `retry_prompt` / `unanswered_failure` carry today's three
wordings (:733-739, :798-810); their numbers are §12 #14–#15's (m and N from
`state`), and `_retry_unanswered` hands the run-wide unanswered set to
`retry_report` and `unanswered_failure` (so the give-up line's names and its
m are one set) while the chunk it re-asks is `unanswered_in_batch()`, whose
own count is the number `retry_prompt` shows: a retry turn must not name
entries the agent has never been sent (the run-wide m stays on the host
line, §12 #14).

`on_answer(idx, text)` (called by the answer tool):

```python
old, self.results[idx] = self.results[idx], text   # in memory only (D14)
if text == old:                        # a resubmission that changes nothing changes nothing:
    return                             # no second gate, no judge session, no vector tombstone
if self.state[idx] == _GATING:         # a gate is running: it picks this text up and judges it
    return
self.state[idx] = _GATING              # from _QUEUED/_SENT (an answer) or from _DONE (a correction, D11)
self.start_gate(idx)                   # task_group.create_task(_gate(self, idx))
```

(`old` is None for a queued or sent entry, so the equality guard never fires
on a first answer.)  `on_answer` cannot fail for a store reason: it records a
text and starts a task, so the `answer` tool handler needs no per-item guard.

The `TaskGroup` is created by `interpret_file` and handed to the task
(`self.task_group`).  `start_gate` pairs the counter to the task object, so
the two are inseparable:

```python
def start_gate(self, idx):
    assert self.task_group is not None, "interpret_file owns the gate task group"
    coro = _gate(self, idx)
    self.gate_started()                                  # before create_task: the loop must never
    try:                                                 # observe zero gates between the answer and
        t = self.task_group.create_task(coro)            # the gate's first step
    except BaseException:                                # a group that is aborting refuses the task
        self.gate_finished(); coro.close(); raise        # (BaseException: a CancelledError delivered here too)
    t.add_done_callback(lambda _t: self.gate_finished()) # every terminal state, pre-start cancellation included
```

The decrement therefore runs one `loop.call_soon` after the task finishes; the
counter can only read too high, which is the safe direction for a termination
test, and the same callback sets `_progress`, so a parked loop wakes and reads
the decremented value.  The judge tasks' `run_*` totals are added to
`judge_cost` when each gate finishes.

### 15.4 The queue loop

```python
async def _run_agent(make_driver, task):
    try:
        async with make_driver() as driver:
            while True:
                batch = task.next_batch()
                if not batch:
                    if not task.gates_running:
                        break                                 # §5.3 termination
                    await task.wait_for_progress()
                    continue
                await driver.run_turn(task.build_prompt(batch))
                await _retry_unanswered(driver, task)        # today's loop over task.batch
    except ReachLimitError / RateLimitError / PoisonedSessionError / FatalAgentError / Exception:
        exactly today's handlers (:811-862) and their policies (the two throttle
        arms never give up and never consume the recycle budget), with three
        changes: every recovering arm (the two throttle arms and the two
        recycle arms) first calls `_stop_if_cancelled()` -- when
        `asyncio.current_task().cancelling()` is true the gate task group is
        tearing this session down and a driver's teardown replaced the
        CancelledError with an ordinary exception (a cost flush on the broken
        store, the subprocess transport's __aexit__); the helper raises a
        `CancelledError` -- not the arm's laundered exception, which it logs
        first -- instead of recycling: a recycled session would have every
        create_task refused and the loop would park in wait_for_progress for
        ever, and re-raising the ordinary exception would be swallowed again
        by `_judge`'s `except Exception` (§5.4 step 3) one frame above the
        judge's nested `_run_agent`, which reads any session failure as
        CHANGED and lets the gate write and mint on a run being torn down
        (integration review) (Python 3.12's wait_for/timeout call uncancel() before raising
        TimeoutError, so a driver's own timeout does not trip it);
        the whole try is inside `while True` and a handler `continue`s
        instead of `return await _run_agent(...)` (no recursion, so no
        RecursionError termination mode; `depth` becomes a local that exactly
        the two recycle arms increment and the two throttle arms leave alone,
        so `_MAX_AGENT_RECYCLES` keeps its meaning), and the throttle sleeps get jitter —
        ReachLimitError: 1200 s ± up to 60 s; RateLimitError: min(2 * 2**throttled, 60) s
        ± up to 50 %, `throttled` incremented only by that arm and reset by a
        completed turn — so many concurrent sessions do not retry in lockstep.
```

`_retry_unanswered` is today's loop body (:774-810) with `missing_idx =
task.unanswered_in_batch()`, the report line from `task.retry_report`, the
prompt from `task.retry_prompt`, the give-up error from
`task.unanswered_failure`.  Because a drop no longer exists and an enrolled
entry's `results` is `None` until its answer, the completeness invariant's
final check in `interpret_file` keeps its shape (every `results` non-None,
else `FatalAgentError`); its warrant changes with D14: "answered" no longer
means "durable", and the certificate that licenses `mark_interpreted` is
"every `results` non-None AND every gate joined without raising", which
together mean every entry is `_DONE` (its gate wrote it) or `_NOT_ENROLLED`
(already in the store).  The final check also asserts that state clause, so
the certificate is structural rather than remembered.

Recycle: `next_batch` re-sends the still-`_SENT` entries of `task.batch`
first; states `_GATING`/`_DONE` are untouched by a recycle; gates are tasks
of the group, not of the session, so they continue.

Wait-for-progress correctness: a gate that enrols or finishes sets the event;
`wait_for_progress` clears it after waking; a set that happens between
`next_batch` and `wait` is not lost (the event stays set until cleared).
The loop can only exit with `gates_running == 0` and an empty queue, so no
enrolment is ever left unsent.

### 15.5 The gate coroutine

```python
async def _gate(task, idx):
    e = task.entries[idx]
    while True:                                              # a fixpoint over the text (D11)
        rec = task.rec_cache[e.universal_key]                # the record as currently stored (§3's R)
        text = task.results[idx]                             # the text this round judges
        verdict = None                                       # CHANGED / UNCHANGED / None (no mint decision needed)
        judged = e.semantic_digest is not None               # §15.5 _write's predicate
        if judged and rec is not None and rec.semantic_digest is not None:
            if rec.baseline_interpretation is None:
                verdict = CHANGED                            # §3 row 2 (legacy record)
            else:
                sim = await _prefilter(task, rec.baseline_interpretation, text, e)
                if sim is not None and sim < _GATE_SIMILARITY:
                    verdict = CHANGED                        # §3 row 3
                else:
                    verdict = await _judge(task, idx, rec.baseline_interpretation, text)
        # else: §3 row 1 (first write), theorem-alike, persistent: no verdict needed
        if task.results[idx] != text:                        # a correction landed mid-gate:
            continue                                         # judge the new text; nothing written, nothing minted
        minted = _write(task, idx, rec, verdict, text)       # step 5 below
        break
    if minted:
        _propagate(task, idx)                                # §5.3.1
```

No `await` between the test and the write, so the text cannot move under the
test.  Terminates because every extra round is paid for by one distinct
correction; in step 3 (no await in the body) it always runs exactly once.
`gate_finished` is not called here: `start_gate` paired it to the task with
`add_done_callback` (§15.3), so it fires for every terminal state, a
pre-start cancellation included.

`_prefilter` (§5.4 step 2): returns a float or `None` (not computable /
disabled).  Skipped (`None`) when `task.emb_store is None or
task.run_state.prefilter_disabled`.  Two `entity_document_text` renderings
(one with the baseline text, one with the fresh text, both with
`e.prop_str`), one `await task.emb_store.emb_provider.embed(text=[doc_baseline,
doc_fresh], role="document")` (the parameter is named `text`,
semantic_embedding.py:456) inside `async with asyncio.timeout(_PREFILTER_TIMEOUT_S)`,
cosine by hand, `None` on zero norm / non-finite.  The embed machinery's own
tracing is gated for the call (`_embed_tracing_gated`, set before the `try`
and reset in a `finally`): per judged entity it would count against
Isabelle's `editor_tracing_messages` cap, whose overflow blocks the command
— the hazard the whole-DB embed already guards against.  On any `Exception`
(`TimeoutError` included): log the traceback, then
`if task.run_state.claim_prefilter_disable(): await _report(text §12 #5,
warn=True)`, return `None` — `claim_prefilter_disable()` flips the flag and
says whether THIS caller flipped it, one synchronous step, so the caller that
disables the prefilter is the one that reports it and "skipped for the rest
of the run" and "printed once" are one operation even for the gates that were
all inside the failing call when the service went down (a flag merely set
before the report would let each of them report).  The `<error>` slot is
`str(exc) or type(exc).__name__`: the timeout cuts the provider's retry
ladder before it can raise a message, so the dominant failure is a bare
`TimeoutError` whose `str` is empty.

`_judge` (§5.4 step 3, §15.6): builds a `JudgeTask` with the single entity,
runs `_run_agent(lambda: task.make_judge_driver(judge), judge)`; returns
UNCHANGED iff `judge.verdict is True`; CHANGED otherwise (including
`FatalAgentError`, caught with `except Exception`, logged at warning).

`_write(task, idx, rec, verdict, text)` (§5.4 step 5, §3 table), one
`Semantic_DB.gate_write()`.  It takes the record it judged against and the
text the verdict was reached on, so the value written and the value judged
cannot drift; it never re-reads either from the task.  Two predicates, each
defined once and keyed on the digest, never on the kind (a
persistent constant, or a four-kind entry whose `Semantic_Digest.semantics_of`
returned NONE, has a tracked kind and no digest and must NOT be judged or
given a baseline): `judged = e.semantic_digest is not None` (§3 rows 1–5)
and `has_gate_fields = e.semantic_digest is not None or bool(e.deps)` (the
scan's own test, :1101; false only for persistent entries and WIP
collections / methods, which get `None` everywhere, D15):

```python
with _note_on_failure(f"while writing the interpretation of {e.name}"), \
     Semantic_DB.gate_write() as w:
    if not judged:                               # theorem-alike (deps present), persistent, collection, method
        # today's :945-947 verbatim: the stored version, else ε; never a mint (I2)
        version = ((rec.version if rec is not None and rec.version else w.counter_value())
                   if has_gate_fields else None)
        baseline, digest = None, None
    elif rec is None or rec.semantic_digest is None:   # §3 row 1: first write
        version, baseline, digest = w.counter_value(), text, e.semantic_digest
    elif verdict is CHANGED:                     # §3 rows 2–5, CHANGED (rec has a digest here)
        version, baseline, digest = w.mint(), text, e.semantic_digest
    else:                                        # UNCHANGED (rec has a digest and a baseline here)
        version, baseline, digest = rec.version, rec.baseline_interpretation, e.semantic_digest
    deps = (e.deps or []) if has_gate_fields else None
    # the snapshot after this entity's own mint: the version is PASSED to the
    # evaluator (a fresh _EffStar over rec_cache), not read back from a
    # fabricated record -- §15.8 item 4 uses the same call shape
    ia = _EffStar(task.rec_cache).eff_value(version, e.deps) if has_gate_fields else None
    written = w.put_interpretation(e.universal_key, kind=EntityKind(e.kind), name=e.name,
        expr=e.prop_str, interpretation=text, locale_provenance=e.locale_provenance,
        theory_constituents=e.theory_constituents, position=e.position,
        from_collection=e.from_collection, semantic_digest=digest, deps=deps,
        version=version, interpreted_at=ia, baseline_interpretation=baseline)
task.rec_cache[e.universal_key] = written         # assigned exactly once, from the transaction
task.state[idx] = _DONE                           # the count is derived (§15.2)
return judged and verdict is CHANGED
```

A failure inside `gate_write` propagates as the store's own exception with
the note added (§5.4 Failures); `_note_on_failure` is `except Exception`
only, so a cancellation passes through untouched.  `_TRACKED_KINDS` is not
needed by any of this and is not defined (§5.5).

`_propagate(task, idx)` (§5.3.1), for each `j in task.dependents[idx]`:

```python
match task.state[j]:
    case _NOT_ENROLLED: task.enqueue(j)
    case _QUEUED | _SENT | _GATING: pass
    case _DONE:
        r = task.rec_cache[uk_j]
        ia = _EffStar(task.rec_cache).eff_value(r.version or 0, r.deps)   # includes the mint
        with _note_on_failure(f"while raising the interpreted_at snapshot of {task.entries[j].name}"), \
             Semantic_DB.gate_write() as w:
            task.rec_cache[uk_j] = w.update_gate_fields(uk_j, semantic_digest=r.semantic_digest,
                deps=r.deps, version=r.version, interpreted_at=ia,
                baseline_interpretation=r.baseline_interpretation)
```

`_EffStar(rec_cache)` is today's closure family `eff_uk` / `eff_value` /
`_contrib` / `_rec_of` (:983-1088) moved out of `interpret_file` into a small
class over a `rec_cache` dict and its own memo, so the scan and the gates
share one implementation; the code inside is unchanged.  The scan builds one
instance and reuses its memo across all entries (as today: nothing changes
during the scan).  A gate builds a FRESH instance per call (a mint changes a
record, so a memo from before it is stale); the cost is one Tarjan walk over
the entity's closure.  A gate never calls the scan's memo-sharing instance.

Concurrency: every gate is an `asyncio` task on one loop; the LMDB writes are
synchronous blocks with no `await` inside, so two gates never interleave
inside a transaction, and `rec_cache` mutations are likewise atomic per gate
step.  Between a gate's `await` points another gate may write; that is the
intended semantics (each write reads `rec_cache` as it is then).  Two gates
for ONE entity never overlap: `_write` sets `state[idx] = _DONE` as its last
statement and there is no `await` between that and the gate coroutine's
return (`_propagate`'s writes are synchronous), so an `answer` handler that
observes `_DONE` — the only state from which a correction starts a second
gate — is running strictly after the first gate finished, propagation
included.  The warrant is "no await after the write", NOT the counter, whose
decrement is deferred by one `loop.call_soon` by the `add_done_callback`
pairing (measured).  Anything that later puts an `await` after the write
(moving the LMDB write to a thread, an awaiting propagation) breaks this and
must re-establish it.

### 15.6 `JudgeTask`, the `verdict` tool, the judge driver

```python
class JudgeTask(AgentTask):
    cost_prefix = b"judge_"
    def __init__(self, parent: InterpretationTask, idx: int, baseline: str, fresh: str):
        super().__init__(parent.connection, parent.file_path, parent.theory_longname,
                         parent.theory_key, [parent.entries[idx]], parent.driver, parent.model)
        self.baseline, self.fresh = baseline, fresh
        self.verdict: bool | None = None
        self.enqueue(0)
    def build_prompt(self, indices): -> the pair prompt (below)
    def format_entries(self, indices): -> "<kind label> <name>"
    def on_answer(self, idx, text): -> self.results[0] = text; self.state[0] = _DONE   # the verdict's `why`
    def retry_report(self, n, attempt): -> ""                 # host log only (D10)
    def retry_prompt(self, chunk): -> "You have not reported a verdict. Call `verdict` now with same=true or same=false, then stop."
    def unanswered_failure(self, names): -> f"judge gave no verdict for {names[0]}"
```

`_MAX_STALLED_RETRIES` is a module constant read by `_retry_unanswered`; the
judge's one-round retry (approved) is expressed as an `AgentTask` attribute
`max_stalled_retries` (interpretation: `_MAX_STALLED_RETRIES`; judge: 1) that
`_retry_unanswered` reads.  NB the attribute carries two meanings: on the
interpretation task it is "give up after this many stalled rounds", on the
judge it is "ask once more, then CHANGED"; `_retry_unanswered` prints the
task's `retry_report` only when it is non-empty, so the judge's second ask
produces no user-visible line.

`mk_verdict_tool(judge)`: schema `{same: bool, why: str}`, both required;
handler sets `judge.verdict = bool(args["same"])`, then calls
`judge.on_answer(0, args["why"])` (so the retry loop sees the entry
answered — the same shape as the answer tool, no hook left unused), logs
`why`, replies "Verdict received. Stop now."

Pair prompt (user turn): `Entity: <kind label> <name>` / `Description 1:` +
baseline / `Description 2:` + fresh / "Do they describe the same meaning?
Answer with the `verdict` tool."  `_JUDGE_SYSTEM_PROMPT` (rev 3's wording):
the judge compares two English descriptions of one Isabelle entity
(constant / type / typeclass / locale) and reports whether they describe the
same mathematical meaning; wording, order and level of detail do not matter,
a change in what is asserted or defined does; report exactly one verdict
through `verdict`, then stop.  Not user-visible, not subject to approval.

Judge driver: `make_interpretation_driver(driver_name, model=model,
system_prompt=_JUDGE_SYSTEM_PROMPT, tools=[mk_verdict_tool(judge)],
task=judge, on_context_reset=noop, cli_tools=False)`; the permission
derivation of §5.5: in the Claude driver `_options()` computes the allowed
set ONCE into a local — `mcp__<SERVER_NAME>__<t.name>` for `t in self.tools`,
plus `_CLI_BUILTINS` iff `cli_tools` — and BOTH `allowed_tools=sorted(allowed)`
and the `_permission_control` closure (the PreToolUse hook, the hard
enforcement: `allowed_tools` only suppresses prompts) read that one local, so
the option and the hook cannot disagree.  `_TOOL_WHITELIST` is renamed
`_CLI_BUILTINS` so a stale reference to the old name cannot compile as "the
whole allowed set".  `interpret_file` builds `make_judge_driver` next to
`make_driver` and hands it to the task.  Judge sessions are limited to 40
at once (D12): `_judge` acquires a module-level `asyncio.Semaphore(40)`
around the session only.

### 15.7 Storage calls

Step 1 delivered `Semantic_DB.update_interpretation(...)`,
`Semantic_DB.gate_write()` → `Gate_Writer.counter_value() / mint() /
update_gate_fields(...)`.  Step 3 adds `Gate_Writer.put_interpretation(key, *,
kind, name, expr, interpretation, locale_provenance, theory_constituents,
position, from_collection, semantic_digest, deps, version, interpreted_at,
baseline_interpretation) -> Record`: `invalidate_vectors([key])` first, then
copy-up-then-modify (`_raw_for_update` → `_decode` → `_replace` → `_encode`
→ `txn.put`), creating the record when absent or tombstoned.  Step 3 also
DELETES `Semantic_DB.update_interpretation`, which the revised D11 leaves
with no caller; `put_interpretation` and `update_gate_fields` share the
private `_put_fields(txn, key, fields, *, create=False) -> Record` with
`backfill_field`.

### 15.8 The scan (step 4)

Today's phases 1–3 (:930-1130) become:

1. `recs = Semantic_DB.get_many(...)`, `rec_cache = {uk: rec}` (as today).
2. Phase 1 loses its `txn.put` and `counter_next` (no scan-time mint) and
   its write transaction; it keeps computing, per entry, whether the digest
   differs (local staleness).  The ε reading of a version-less record (today's
   `rec.version if rec.version else epsilon`, :949-951, :962) is kept — the
   §9 "ε epoch" unchanged, the same reading §15.5 uses — with ε from a new
   read-only sibling `Semantic_DB.counter_snapshot()` (a read transaction on
   the USER env only, 1 when absent or tombstoned; `counter_value` PUTS 1 on
   a missing counter and so cannot serve a scan that writes nothing).
3. Phase 2's evaluator becomes `_EffStar(rec_cache)`, one instance for the scan.
4. Phase 3 computes the seed set: `has_gate_fields = digest or deps` (the
   predicate semantic_interpretation.py:1101 calls `tracked` today; §15.5's
   name); `stale` = today's three criteria with eff\*
   (`_EffStar.eff_value(rec.version or epsilon, e.deps)` — no `version_to_write`);
   the `expr` shortcut and `update_expr` move to the statement refresh (item
   8).  Seeds: uncached ∨ stale.  Non-seeds: `results[i] = rec.interpretation`.
5. The theory-internal reverse graph: `uk_to_idx = {e.universal_key: i}`;
   `dependents[j].append(i)` for every `d in e_i.deps` with `j = uk_to_idx.get(d)`
   and `j != i` — a constant's dep list names its own key
   (semantic_digest.ML's `deps_of_term (Const ...)`); the self edge carries no
   signal (the entity's own version is already eff\*'s floor) and following it
   would make every CHANGED verdict re-write its own record unchanged.  The
   stored dep list keeps the self dep: it is the imprint §4.3 compares by value.
6. Dry run: the statement refresh of item 8 over the not-enrolled entries —
   exactly the scan's `cached and not stale` set, where `rec` is provably
   non-None; on this path those are also "the entries this run did not
   write", and a seed's `expr` is rewritten by the live run that interprets
   it — which keeps an `expr`-only change refreshable when the cone quotes
   zero and both `n == 0` guards short-circuit (the one write a dry run
   makes: no gate field, no mint, no counter put); then `return len(seeds)`
   with the approved comment.
7. Live run: `InterpretationTask(connection, file_path, theory_longname,
   theory_key, entries, ..., dependents=dependents, emb_store=...,
   run_state=run_state, make_judge_driver=...)` — `recs` stays a local of the
   scan, the task is handed `rec_cache` only — over ALL of the theory's entries (not today's
   `uncached` sub-list): a dependent that is not a seed must be enrollable,
   so it needs an index, a state and a result slot.  Non-seeds start
   `_NOT_ENROLLED` with `results` prefilled from the store; seeds are
   `task.enqueue(i)`-ed in wire order.  `interpret_file`'s final remap
   (:1247-1252) becomes a direct read of `task.results` in entry order.  The
   larger `results` dict costs nothing noticeable; the label map already
   covers all entries today.

8. Statement refresh (§5.3.2), after the loop on the live path and before the
   return on the dry path: for `i` with `state[i] == _NOT_ENROLLED`, when
   `_statement(e, rec)` -- the wire `prop_str`, or the stored `expr` when the
   wire's is "" (D19; the same rule the gate's write uses for `expr`) --
   differs from the stored `expr`, `Semantic_DB.update_expr`.  So an entry
   whose statement could not be computed is left byte-identical.

The addressing rule follows the states: the answer tool accepts an answer
only for an entry whose state is not `_NOT_ENROLLED` (an unrequested name
goes to the reply's `errors` list, exactly today's "Unknown entry", and
starts no gate, writes nothing, mints nothing); what the lookup tools hide
is `task.theory_keys` -- the universal keys of every entry of the theory,
fixed when the task is built (D18) -- checked on the RESOLVED key at every
point a stored text would be returned: `mk_query_by_name_tool`'s name
lookup, its notation fallback and its short-name fallback, and
`mk_desugar_and_explain_tool`'s per-constant annotations (which say "read
its definition from the source" instead).  The third disclosure point is
upstream of Python: `build_entries` (semantic_store.ML) composes the
locale-interpretation provenance hint, whose `Template meaning:` and
`Locale "…":` lines carry stored interpretations of the instantiated locale
and its template theorem; the run's own keys are dropped from the lookup
(`own_uks`) and `sem_of` refuses them outright, so a `Template meaning:` or
`Locale "…":` line is omitted whenever the template theorem or the
instantiated locale is itself an entry of this run -- the hint then degrades
to the shape it already has when the store holds no text for that key -- and
a locale of a parent theory keeps its hint byte-identical.  Enrolment plays no part: an
entity enrolled by a later CHANGED verdict could otherwise have been read
before it was enrolled, and an echoed text would make the judge say "same"
on a real change (the integration review's flow-INT-1, which replaced the
step-4 ruling's enrolment-time list).  The counters of §12 #13–#16
are derived from `state`, never from `results` (§12 gives the formulas).

**Run-scoped state.**  A run = one holder of the interpretation lock (§8):
`try_acquire_interpretation_lock` creates a `RunState` (field:
`prefilter_disabled: bool`) and registers it, with the FileLock, on the lock
connection; the connection's `on_close` releases both.  Exactly one run
holds the lock per database directory, and a host process serves one
database directory (semantics.py:130-133), so a module-level
`current_run_state()` accessor is per run by construction.  `interpret_file`
resolves it ONCE at its top and hands it to the task (`run_state=`); when
no lock is held (unit tests, an unlocked caller) `current_run_state()`
returns a new `RunState`, so off the lock the scope degrades to one
`interpret_file` — never a fresh object per access, never a module-level
singleton that outlives the run.  `RunState` and `current_run_state()` live
in semantic_interpretation.py (§15.1); until the lock lands (§13 step 7) no
run ever holds one, so steps 3–6 run entirely on the off-lock scope.  The
startup check (§5.6) sets
`prefilter_disabled` when the service is unconfigured; its provider is
constructed only to validate the configuration and then discarded.  Each
`interpret_file` resolves its own `Semantic_Vector_Store` through the
existing per-connection registry `await connection.semantic_vector_store()`
(semantics.py:2792-2812), which the `Config.lookup` callback of §5.6 makes
correct per context (D5) — skipped when `run_state.prefilter_disabled` is
already set, and otherwise inside `except Exception` ⇒ `emb_store = None`
with a host-log line only (`_conn_semantic_vector_store` raises in exactly
the unconfigured case, semantics.py:2779, and #4 was printed once by the
startup check, D16); D16's `warn` is threaded one hop further through
`semantic_vector_store` so the multi-line hint is not repeated per theory.
There is no server-level or module-level store handle.

### 15.9 Cost accounting

Each `AgentTask` keeps its own `total_*` (pending) and `run_*` (cumulative)
accumulators exactly as today; `accumulate_usage(task, ...)` is unchanged.
`write_cost` folds the pending delta into the theory status's unprefixed keys
and, for `cost_prefix == b"judge_"`, additionally into
`judge_input_tokens`, `judge_cache_creation_tokens`, `judge_cache_read_tokens`,
`judge_output_tokens`, `judge_cost_usd` (approved).  `interpret_file` reports
`current_cost` = the interpretation task's `run_*` plus `task.judge_cost`
(the sum of the judges' `run_*`, added when each gate finishes).  This is
§5.5's "one `RunCost` per run" without a separate class: the status record
is the shared accumulator.

### 15.10 Tests (mapping §10 to files)

- `archive/tests/test_interpretation_driver.py` (step 3): the import of
  `_local_task` (:32) and its three `.set(task)` calls (:138, :192, :441) go
  with the ContextVar; `_run` and the context-reset test call
  `_run_agent(make_driver, task)` (today `_run_agent(make_driver)`, :139,
  :445); `_make_task(n, batch_size)` builds a task with every entry enrolled
  and sets `task.batch_size` (a per-task attribute, §15.2: no module global
  is mutated and no autouse fixture is needed);
  `_RecordingTask` overrides `start_gate` to record `(idx, results[idx])`
  and mark the entry `_DONE` (no LMDB, no task group), so `task.written` and
  every assertion resting on it survive — the stub covers a correction too,
  since `on_answer` reaches `start_gate` from `_DONE` as well; `_answer` goes
  through `mk_answer_tool(task).handler`; the scenarios batches advance,
  cost flush per turn, retries with full text, stalled retry raises,
  poisoned session recycles keep their assertions with the batch handoff now
  being the loop's next turn.  "A failed write is not counted as answered"
  (:171-207, the test that sets `task.batch_range`) pins the persist-first
  discipline D14 retires; it is replaced by "a failed gate write fails the
  run" (§10): a gate raising a native exception inside a real `TaskGroup`
  leaves `interpret_file`'s shape as that exception, its note in the
  formatted traceback, its own `__cause__`/`__context__` intact and no
  `ExceptionGroup` as its context; `_first_failure` on a nested group takes
  the first non-cancellation leaf and returns a cancellation-only group
  unchanged.  Three further tests of the loop: (a) a gate that fails while
  the scripted driver's teardown converts the CancelledError into a
  RuntimeError — the run ends as the gate's exception, no further turn runs,
  `gates_running == 0` (the `_stop_if_cancelled` rule); (b) a gate that
  awaits an `asyncio.Event` after the queue emptied — the loop waits (still
  pending while the gate pends), returns when the event is set with every
  write landed and `gates_running == 0`, and entered exactly one session
  (§5.3 Termination; under `asyncio.wait_for` so a regression fails instead
  of hanging); (c) corrections: a byte-identical resubmission of a `_DONE`
  entry starts nothing, a different text records a second write, and two
  items for ONE entry with different texts in ONE `answer` call run exactly
  one gate, on the newer text — reachable in step 3 through the handler's
  synchronous item loop (no await between items), so it is not the
  judge-session case the step-5 file defers; (d) F4's compensation: a group
  whose `create_task` refuses the gate leaves `gates_running == 0` and the
  never-started coroutine closed.  The test doubles swap the gate BODY
  (`monkeypatch.setattr(SI, "_gate", ...)`; `start_gate` resolves it at call
  time), never `start_gate` itself, so the shipped starter runs in every
  test and each of F4's four clauses fails a test by assertion when removed.
  Because `test_interpretation_mcp_server.py:25` and
  `test_interpretation_codex.py:48` import `_make_task` from this module,
  leaving any of this unwritten fails all three modules at collection.
- `archive/tests/test_interpretation_mcp_server.py` (step 3): imports
  `mk_answer_tool` instead of `_answer_tool` (:23); the line `task.batch_range
  = task.batches[0][1]` (:86) becomes `task.next_batch()`; the four session
  registrations (:96, :137, :154, :155) pass `mk_answer_tool(task)`; the
  handoff result is the "Batch complete" reply, not the next batch.
  `test_interpretation_codex.py` imports `_make_task` and needs nothing else.
- `archive/tests/test_incremental_criteria.py` (step 4): the "scan
  re-stamps the wire digest" / "a genuine change bumps" assertions (:121-122)
  become "a dry run leaves the record and the counter byte-identical"; the
  dep-edge test (:135, "corrupting only a must pull b in") becomes `_dry ==
  1` (B is wall-shielded until A's verdict, D13), and its live half moves to
  the enrolment test of the new file with a cross-reference so the coverage
  is visibly moved, not dropped.
- `archive/tests/test_eff_star.py` (step 4): `_epsilon()` reads
  `counter_snapshot()`; no other change (the ε reading is kept).
- `archive/tests/test_semantic_change_gate_storage.py` (step 3): +
  `put_interpretation` (text and gate fields in one transaction, vectors
  invalidated first, creation and resurrection, aborted write leaves
  nothing).  The legacy-arity parametrisation stays on `update_gate_fields`,
  where the assertion depends on n because that writer inherits `position` /
  `from_collection` from the stored record; `put_interpretation` writes all
  three formerly truncated fields itself and is therefore arity-invariant
  (measured: four identical records from n = 12..15), so it gets one
  unparametrised test instead — a 12-field record whose `experience` and
  `goal_patterns` survive the put while `position` is rewritten — and keeps
  its 15-field round trip through `assert _raw_len(k) == 15`.
  `test_gate_write_does_not_invalidate_vectors`
  renamed to name `update_gate_fields`; + `counter_snapshot` reads 1 on an
  empty store and writes nothing.  The four `update_interpretation` tests
  and the module docstring's "two field-disjoint entry points" go with the
  deleted method.  Beside them, store-backed tests of the step-3 gate over
  the same `cache` fixture (no second isolation mechanism): `_gate` over two
  entries, one tracked with `inv_fields` `(7, 3)` and one untracked, driven
  by `asyncio.run(_gate(task, i))` with `state[i] = _GATING` set by hand —
  asserts the stored fields (entry 0: version 7, interpreted_at 3, the wire
  digest and deps, baseline None; entry 1: all five gate fields None), both
  states `_DONE`, `task.n_interpreted() == 2`; a gate write that fails
  (`gate_write` monkeypatched to raise) propagates the native exception with
  the note naming the entity; a correction as a SECOND GATE on a `_DONE`
  entry (`state[0] = _GATING`, `results[0] = "corrected text"`,
  `asyncio.run(_gate(task, 0))` — not `on_answer`, which needs a task group)
  rewrites the text with the gate fields unchanged, because in step 3 the
  same scan pair is written again, not because a correction skips the gate.
- new `archive/tests/test_semantic_change_gate.py` (step 5): the enrolment,
  snapshot raise, decision table (with and without a stored record for the
  theorem-alike row; persistent row all None), queue loop, concurrency,
  corrections — a second gate on a done entity for both verdicts, a
  correction that lands during the judge session (judged, not adopted: the
  stored text and its verdict come from the same text), and a byte-identical
  resubmission (no gate, record byte-identical) — unrequested-answer
  rejection and its mirror (D18: neither lookup tool discloses a stored
  interpretation of this theory's entities, enrolled or not, at the name
  lookup, the notation fallback, the short-name fallback or the desugar
  annotations, while an entity of another theory is served), dry-run and cost assertions of
  §10, driving `interpret_file` with a fake driver (scripted answers), a
  fake judge driver (scripted verdicts) and a fake embedding store (scripted
  similarities), over an isolated store; the `ExceptionGroup` unwrapping
  (the text after `USER_ERROR_MARKER` contains no `"    | "` gutter); the
  prefilter timeout; the Claude driver's hook closure allows
  `mcp__isabelle_semantics__verdict` and denies a built-in for a
  `cli_tools=False` driver, and allows `mcp__isabelle_semantics__answer` for
  the interpretation driver; the dry-path statement refresh (a theory whose
  only difference is `prop_str` quotes 0 and still ends with `expr`
  refreshed and the vector invalidated).
Each edit lands in the same commit as the step that breaks the old
assertion, so the suite is never red for an unwritten reason.

### 15.11 What works after each step

- After step 3: the queue holds today's todo set as seeds (scan unchanged);
  the scan's per-entry `(version, interpreted_at)` pair — today's
  `inv_fields`, whose version comes from `version_to_write` (phase 1 writes
  its mint back into `recs[i]` only in the digest-mismatch branch, :957-959;
  the two ε branches carry their number in `version_to_write` alone) and
  whose snapshot is `ia_snapshot` (:1131), neither of which `recs` carries —
  stays as a step-3-only task field, deleted in step 4 when `_EffStar` and
  `rec_cache` take over; every answer is written at once with that pair (no
  gate yet), and a correction of a written entity runs that write again
  through a second gate.  What reaches the STORE is today's with two
  exceptions: every interpretation write — an answer's and a D11
  correction's alike — is a task of the run's task group, so a write that
  fails now fails the run (session closed, theory not marked) where today a
  failed correction escaped the tool handler as an opaque tool error and the
  run still succeeded; and on the success path a correction's write is no
  longer synchronous with the tool reply — it lands at the handler's next
  `await` (`await _report(...)`), still before the reply reaches the agent.
  The session loop itself is the new one of §5.3 / §15.4, not today's: one
  turn per batch; a recycle or throttle retry resumes from the entries still
  `_SENT` instead of re-sending the pre-built batch-0 prompt in full (today's
  `_run_agent` re-enters at `task.batches[0]`), so answered entries are
  neither re-asked nor re-written; the throttle sleeps jitter and back off;
  the handlers loop rather than recurse.  The closing line still counts
  entities, not writes.  Suite green with the §15.10 step-3 test edits.
- After step 4: scan writes nothing but the dry-path refresh; seeds by
  eff\*; dry run = seed count; first writes take ε at write time; no gate
  yet, so nothing mints: a re-interpreted entity is written with version ε
  = the counter and `interpreted_at` = its eff\*, i.e. it over-signals, and
  a changed definition's dependents are re-listed on the next run only
  where their stored `interpreted_at` is strictly below the counter — one
  already at the counter loses the signal.  An intermediate state, not
  shipped: run it against a throw-away `SEMANTIC_DB_DIR` only, never
  against the real cache.  Suite green with the §15.10 step-4 test edits.
- After step 5: the gate, propagation, snapshot raise; the feature complete
  on the Python side.  Steps 6–8 add the callback, the lock and the texts.

