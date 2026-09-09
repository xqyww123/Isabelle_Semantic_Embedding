# Review scope: semantic change gate, implementation step 4 (the scan rewrite)

All paths are relative to `contrib/Semantic_Embedding/` (absolute root:
`/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/`).  Do not modify any
file.  You may run pytest (command below); never run `isabelle build`.

## What is being reviewed

The plan is `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` (rev 5.3,
authoritative; §0 glossary fixes the vocabulary).  Its §13 lists eight
implementation steps.  Steps 1–3 are reviewed, accepted and committed
(`8683e6f`; the review records are under `ai-artifacts/review_step3/`).
**Step 4 is what you review now**: the scan rewrite.  Specification: §13
item 4, §15.8 (items 1–8), §5.2, §5.3.2, §15.5 (`_EffStar`, the record
source `rec_cache`, `_write`'s two predicates), §15.3 (the task's
`rec_cache` / `dependents`), §15.10 (the step-4 test edits) and §15.11's
"After step 4" bullet.  §3 (the gate rule) and §4 (eff\*) are the design it
derives from.

`working_tree.diff` is `git diff` against the step-3 commit for the five
touched files.  Read the files on disk for the full picture:
`Isabelle_Semantic_Embedding/semantic_interpretation.py` (`_EffStar`,
`_refresh_statements`, `_write`, `_gate`, `AgentTask.enqueue` /
`enrolled_names`, `InterpretationTask.__init__`, and the whole of
`interpret_file`), and the tests `archive/tests/test_incremental_criteria.py`,
`test_eff_star.py` (+ `eff_reference.py`), `test_semantic_change_gate_storage.py`,
`test_interpretation_driver.py`.

### Step 4 deliverables (what changed)

`semantic_interpretation.py`
- `class _EffStar(rec_cache)`: today's closure family `_rec_of` / `_contrib`
  / `eff_uk` / `eff_value` moved out of `interpret_file` into a class over a
  `rec_cache` dict and its own memo; the code inside is unchanged (§15.5).
  The scan builds ONE instance; a gate builds a FRESH one per call.
- `_refresh_statements(entries, rec_cache, not_enrolled)`: the statement
  refresh (§5.3.2, §15.8 item 8) — today's guard verbatim.
- The scan in `interpret_file` (§15.8 items 1–6): no write transaction, no
  mint, no `counter_next`, no digest re-stamp; ε from `counter_snapshot()`;
  local staleness (digest changed / never digested / dep keys moved) and
  eff\* over the store (`_EffStar.eff_value(rec.version or epsilon, e.deps)`);
  seeds = uncached ∨ stale, in wire order; `results` prefilled from the store
  for non-seeds; the theory-internal reverse graph `dependents`.  Dry run:
  statement refresh over the not-enrolled entries, then `return len(seeds)`
  with the approved comment (§5.2).
- Live run (item 7): the task spans ALL entries (`InterpretationTask(...,
  entries, rec_cache=rec_cache, dependents=dependents)`); non-seeds start
  `_NOT_ENROLLED` with `task.results[i]` prefilled; seeds `enqueue`d in wire
  order; the query tool is handed `task.enrolled_names` (a list `enqueue`
  appends to); statement refresh after the group joined and the completeness
  certificate; `results = list(task.results)`.
- `InterpretationTask.__init__`: `inv_fields` (the step-3-only pair) deleted;
  `rec_cache` and `dependents` keyword parameters (§15.3).
- `_write(task, idx, rec, text)` (§15.5's shape minus the verdict): the two
  predicates `judged` / `has_gate_fields`; not judged → stored version else
  ε (theorem-alike) or None everywhere (persistent, collection, method);
  judged → **§3 row 1 for every judged entry until step 5**: version = ε
  (`counter_value()`), baseline := text, digest from the wire;
  `interpreted_at` = `_EffStar(task.rec_cache).eff_value(version, e.deps)`
  inside the transaction; `task.rec_cache[uk] = written`.  `_gate` reads
  `rec = task.rec_cache[uk]` at the top of each round and hands it to `_write`.
- `AgentTask.enrolled_names` appended by `enqueue`.

Tests
- `test_incremental_criteria.py`: "re-stamps / bumps" → "a dry run leaves
  the record and the counter byte-identical"; the dep-edge test → `_dry == 1`
  with the cross-reference to the step-5 enrolment test; + the dry-path
  statement refresh (quotes 1, `expr` refreshed, gate fields byte-identical).
- `test_eff_star.py`: `_epsilon()` reads `counter_snapshot()`.
- `test_semantic_change_gate_storage.py`: the gate tests build the task with
  `rec_cache` instead of `inv_fields`; the first-write assertions (ε, ε,
  baseline = text, rec_cache == store); + a snapshot test (a stale dependency
  passes its upstream number through, no wall); the correction test's
  expectation (same ε and snapshot, baseline moved to the new text); the
  end-to-end `interpret_file` test's baseline expectation.
- `test_interpretation_driver.py`: unchanged in substance (the recording
  task takes the constructor's defaults).

### Derivations the implementer made (not literally in the plan — judge them)

1. `RunState` / `current_run_state()` (§15.8 "Run-scoped state"), `emb_store`
   and `make_judge_driver` (§15.3) are NOT added in step 4: nothing in step 4
   reads them (their only consumers are step 5's prefilter and judge), and
   §13 item 4 does not list them.  Step 5 adds them.
2. `enrolled_names` lives on `AgentTask` (where `enqueue` is) rather than on
   `InterpretationTask` as §15.3 lists it: the base class's `enqueue`
   maintains it, so no override is needed; a judge task's one-entry list is
   harmless.
3. `rec_cache` is a keyword parameter of `InterpretationTask.__init__`
   (default `{}`), not an attribute set afterwards.
4. Step 4's `_write` writes every judged entry as §3 row 1 (first write,
   baseline := text), not only those with no digest-bearing record: with no
   verdict there is no other honest row, and §15.11 records the consequence
   (ε at write time, over-signalling; throw-away store only).  A correction
   in step 4 therefore rewrites the baseline; step 5 replaces the branch.
5. The three opening lines keep today's wording with the seed count in the
   place of the todo count (§12 #16's approved texts land in step 8 with the
   other texts).  The dry-run host-log line says "at least".
6. The live-path statement refresh runs after the completeness certificate
   (the assert), i.e. "after the loop" as §5.3.2 says, on the success path
   only.
7. `_EffStar.eff_value` is called INSIDE the `gate_write` transaction (as
   §15.5 shows); `_rec_of` may read the store through `Semantic_DB[k]` (a
   read transaction) while the write transaction is open in the same thread
   — measured to work on this py-lmdb (no MDB_NOTLS conflict).
8. The reverse graph does not exclude self-edges (`dependents[j]` may contain
   `j`); §15.8 item 5 does not either.

## Suite

    cd /home/qiyuan/Current/MLML/contrib/Semantic_Embedding && \
    python -m pytest archive/tests/ --ignore=archive/tests/test_e2e_source_prop.py \
      --deselect archive/tests/test_agent_dir_packaging.py -q -p no:cacheprovider

→ 353 passed, 3 failed (test_config_resolution ×2,
test_embedding_provider_refactor::test_fireworks_qwen: API-key/config
environment, pre-existing, unrelated).

## Project rules that bind the review

- Elegance is a review criterion equal to correctness: a shape that makes an
  invariant impossible to violate beats one that asks people to remember it.
  Reject dirty hacks.
- Reuse code; never reinvent; consistent terminology (the plan's §0
  glossary).  Comments in code short and load-bearing.
- Nitpicking (style-only remarks, hypotheticals with no concrete failure,
  restating the plan, "consider adding a comment", re-raising a settled
  decision D1–D17 or a ruling of the step-3 reviews) is to be rejected
  harshly.
- If slightly relaxing one of the user's constraints or design decisions
  would make the code markedly simpler or more elegant, say so explicitly as
  a PROPOSAL for the user — do not smuggle it in as a bug.
