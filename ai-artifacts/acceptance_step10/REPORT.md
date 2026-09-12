# Acceptance of the semantic change gate: the paid §10 items (2026-09-12)

The two items of `SEMANTIC_CHANGE_GATE_PLAN.md` §10 that need a live
service -- "interactive scaffold: production driver as judge on
`Sim_Measure_B.thy` vs `Sim_Measure_A1.thy`" and "a live run's host log must
show judgements" -- were run as one experiment.  This report is the
record; the raw material it cites (both collect logs, both host logs
`host_run1.log` / `host_run2.log`, the store dumps `inspect_after_run1.txt`
/ `inspect_after_run2.txt`, the two probe scripts) is kept outside git in
`/var/tmp/qiyuan/gate_accept_logs/`.  Nothing touched the production store.

## Setup

- Isolated store: `mdb_env_copy` of the production `semantics.lmdb`
  (1.7 GB), `theory_hash.lmdb`, `experience_index.lmdb` into
  `/var/tmp/qiyuan/gate_accept_db/`; `SEMANTIC_DB_DIR` exported to every
  process (REPL server, the ML-launched RPC host inherits it -- both host
  logs show the lock file under that directory).  HOL is marked
  interpreted in the copy, so the work set is the scratch theory alone.
- Driver: `INTERPRETATION_DRIVER=ClaudeCode.claude-opus-5` (the user asked
  for Codex first; its login had expired: "Your access token could not be
  refreshed").  Embedding: the production stack (Fireworks,
  Qwen/Qwen3-Embedding-8B); the startup check passed silently (no §12 #4
  in either host log).
- Harness: `../Isa-REPL/repl_server.sh 127.0.0.1:6702 Semantic_Embedding`,
  `gate_dry_run.py` (a dry run through `Semantic_Store.dry_run`, no LLM),
  `isabelle-semantics collect --session Semantic_Embedding <path>`
  (the `Semantic_Store.collect` app), `gate_inspect.py` (dumps every record
  of the scratch theory and the counter).  A fresh REPL process per run
  (the WIP skip criterion is the (process id, theory serial) pair).
- Scaffold: `Sim_Measure_A1.thy` copied to `/var/tmp/qiyuan/gate_accept_thy/`;
  for run 2 the file was overwritten with `Sim_Measure_B.thy`'s content
  under the theory name `Sim_Measure_A1` (only the `theory` line differs),
  so the six edited roots keep their universal keys and meet their
  baselines.

## Runs

| run | content | dry run | sent | closing line | cost |
|---|---|---|---|---|---|
| 1 (baseline) | A1 | 1 theory, N = 91 | 91 | `Sim_Measure_A1: 91 entities interpreted; cost $7.7123.` | USD 7.71 |
| 2 (gate) | B under A1's name | 1 theory, N = 26 | 44 (26 seeds + 18 enrolled) | `Sim_Measure_A1: 44 entities interpreted; cost $3.0484.` | USD 3.05 |
| 3 (dry, after run 2) | same as run 2 | N = 0 | -- | -- | 0 |

Total USD 10.76 (the pre-run estimate of 2–3 was made from the phase-2
measurement's Opus 4.8 prices; Opus 5 costs about six times more per
theory).

## What the host log of run 2 shows (`host_run2.log`)

Judge verdicts (`verdict:` lines), one session per entity:

- `constant Sim_Measure_A1.kolvar same=False: Description 1 defines
  kolvar m n = m * n + 1 while description 2 defines it as m * n + 2, a
  different result.`
- `locale Sim_Measure_A1.dremnok same=False: Description 1 says the
  assumption zug_law is commutativity (zug x y = zug y x), while
  Description 2 says it is associativity -- a different assumed law.`

Prefilter decisions (`gate:` lines, cosine below 0.90, no judge):

- `constant Sim_Measure_A1.plerx CHANGED by the prefilter (similarity 0.897)`
- `constant Sim_Measure_A1.tirneb CHANGED by the prefilter (similarity 0.791)`
- `constant Sim_Measure_A1.dremnok CHANGED by the prefilter (similarity 0.816)`

No `judge: … failed` line, no `prefilter: … failed` line, no §12 #4/#5.

## What the store shows (`inspect_after_run2.txt` vs `inspect_after_run1.txt`)

Counter 128 → 133: five mints, in the order the gates finished --
`plerx` 129, `tirneb` 130, `kolvar` 131, `dremnok` (the locale's predicate
constant) 132, `dremnok` (the locale) 133.  Every dependent of a minted
entity was either re-interpreted or had its snapshot raised: the
`kolvar_*` lemmas carry `interpreted_at` 131, `tirneb_*` 130, `plerx_*` and
the `plerx.*` facts 129, `dremnok.*` 132 (their `deps` name the predicate
constant, not the locale entity, so 132 is the right snapshot).  No
`version` or `interpreted_at` exceeds the counter (the post-run invariant).
The dry run of run 3 returned 0: nothing was left stale.

Expected versus observed on the six edited roots:

| root | grade | expected | observed |
|---|---|---|---|
| kolvar (definition) | b numeric | CHANGED | judge: same=False; minted 131; 5 dependents raised |
| tirneb (definition) | e overhaul | CHANGED | prefilter 0.791; minted 130; 5 dependents raised |
| plerx (inductive) | d negation | CHANGED | prefilter 0.897; minted 129; 13 dependents raised |
| dremnok (locale) | f assumes | CHANGED | judge: same=False on the locale, prefilter 0.816 on its predicate; minted 132/133; 8 dependents raised |
| galmuth (fun) | a cosmetic | UNCHANGED | **not a seed**: the digest did not change, so no gate ran; the `galmuth.simps/.induct/.cases/.elims` facts are new statement-keyed entities and were interpreted afresh |
| narquil (fun) | c condition | CHANGED | **not a seed** (see finding 1) |

## Findings

1. **A `fun`-defined constant's digest does not see a change of its
   equations** (pre-existing, in `semantic_digest.ML`, not in the gate).
   `narquil (Brint n) = (if n < 5 …)` became `(if n <= 5 …)`; the constant
   `narquil` kept digest `bde28b89…`, version 128, `interpreted_at` 128,
   and its stored interpretation still says "smaller than five"; the lemmas
   `narquil_small` / `narquil_large` / `narquil_glaive_*` were not
   re-interpreted and still say "strictly less than five".  Cause:
   `own_defining_axioms` takes the constant's defining axioms from
   `Defs.specifications_of`; for the function package that is
   `narquil_def: narquil ≡ narquil_sumC …`, whose body never changes -- the
   equations live in `narquil_graph`'s introduction rules (an infra entity,
   no record: limitation #6) and in `narquil.simps` (theorem-alike,
   statement-keyed: re-interpreted as NEW entities, which does not reach
   the constant's dependents).  The `spec_rule_axioms` fallback, which
   would return the simps equations through `Spec_Rules`, is consulted
   only when `Defs` yields nothing.  Not covered by `Test_Sensitivity.thy`
   (no `fun` row in CHECK_OUTDATE_PLAN.md §14's table) nor by
   `doc/invalidation_limitations.md`.  `definition`, `inductive` and
   `locale` roots were all caught.  Raised with the user; not fixed here.
2. **The judge session asks `ToolSearch` for its own tool and is denied.**
   `host_run2.log` :266 and :300: `tool denied: ToolSearch {'query':
   'select:mcp__isabelle_semantics__verdict'}` -- Claude Code's deferred
   tool loading -- followed a few seconds later by the verdict itself
   (both sessions reported).  No failure, but a judge that gave up after
   the denial would count as "no verdict ⇒ CHANGED" (sound, wasteful).
   Observation only.
3. The plan's expectation that `galmuth` (cosmetic) would be judged
   UNCHANGED was not exercised: with a normalised digest the cosmetic edit
   never reaches the gate at all, which is the cheaper correct outcome.
   The UNCHANGED path of the gate therefore has no live sample in this
   run; it is covered by the pytest suite.

## Texts observed live (§12)

`#16` (second form: `Interpreting Sim_Measure_A1: 93 entities; 67 are
already interpreted, asking the LLM for 26 (or more).`), `#13`
(`Sim_Measure_A1: 20 of 26 done.` … `44 of 44 done.` -- N grew from 26 to
40 to 44 as verdicts enrolled dependents), `#7` (`Sim_Measure_A1: 44
entities interpreted; cost $3.0484.`), all with the `[Semantic_Embedding]`
prefix.  The "About n" texts (#8–#11) belong to the Isar command and the
AoA startup path, which this batch harness does not exercise.

## Verdict on §10

Both paid items pass: the production driver judged (2 verdicts), the
prefilter decided (3), five mints propagated to 31 dependents by
enrolment or snapshot raise, the post-run scan found nothing stale, and
the invariant holds.  Finding 1 is a limitation of the digest that the
gate inherits; it is the one item to take to the user.
