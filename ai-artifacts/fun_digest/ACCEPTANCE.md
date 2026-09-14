# Acceptance of the `fun` digest change: the paid end-to-end runs

Two runs of the same setup: the rev 2.3 run of 2026-09-13 (below) and the
rev 3.0 run of 2026-09-14 (last section), the latter with the named-fact
source of PLAN.md §10 including D9.

## Rev 2.3 run (2026-09-13)

PLAN.md §9 item 3, run at 17:05 with `Tools/semantic_digest.ML` as
implemented at the time; the F1/option-A amendment recorded in PLAN.md §8
came out of the implementation review that follows (§9 item 4) and is not
exercised here.  It
repeats the setup of `ai-artifacts/acceptance_step10/REPORT.md` (whose
finding 1 this change repairs).  Raw material outside git:
`/var/tmp/qiyuan/fun_accept_logs/` (`collect_run{1,2}.log`,
`host_run{1,2}.log`, `inspect_after_run{1,2}.txt`, `dryrun.txt`,
`dryrun3.txt`, the REPL server logs, `gate_dry_run.py`, `gate_inspect.py`)
— deleted on 2026-09-14 on the user's instruction; this file is the record.
Nothing touched the production store.

## Setup

- Isolated store: `env.copy` (LMDB, compact) of the production
  `semantics.lmdb` (1.75 GB), `theory_hash.lmdb`, `experience_index.lmdb`
  into `/var/tmp/qiyuan/gate_accept_db/`; `SEMANTIC_DB_DIR` exported to the
  REPL server and to every Python process.  After run 1 a second copy was
  taken to `/var/tmp/qiyuan/gate_accept_db_after_run1/`, so run 2 can be
  repeated without re-paying the baseline.  Both directories may be deleted.
- Driver `INTERPRETATION_DRIVER=ClaudeCode.claude-opus-5`; embedding stack
  as in production.
- Harness: `../Isa-REPL/repl_server.sh 127.0.0.1:6702 Semantic_Embedding`,
  a fresh REPL process per run; `gate_dry_run.py`
  (`Semantic_Store.dry_run false [Context.Theory thy]`, no LLM);
  `python -m Isabelle_Semantic_Embedding.isabelle_semantics collect --repl-addr 127.0.0.1:6702 --session Semantic_Embedding --rpc-addr 127.0.0.1:27183 <path>`;
  `gate_inspect.py` (every record of the scratch theory, plus the counter).
- Scaffold: `ai-artifacts/similarity_measurement/Sim_Measure_A1.thy` copied
  to `/var/tmp/qiyuan/gate_accept_thy/`; for run 2 overwritten with
  `Sim_Measure_B.thy`'s content under the theory name `Sim_Measure_A1`
  (only the `theory` line differs), so the edited roots keep their
  universal keys and meet their baselines.  The two `fun` roots:
  `narquil (Brint n) = (if n < 5 …)` becomes `n <= 5` (a real change of
  meaning); `galmuth`'s two clauses are swapped and their pattern
  variables renamed `x`/`xs` → `a`/`as` (no change of meaning).

## Runs

| run | content | dry run | sent | closing line | cost |
|---|---|---|---|---|---|
| 1 (baseline) | A1 | N = 91 | 91 | `Sim_Measure_A1: 91 entities interpreted; cost $6.3541.` | USD 6.35 |
| 2 (gate) | B under A1's name | N = 28 | 51 (28 seeds + 23 enrolled) | `Sim_Measure_A1: 51 entities interpreted; cost $3.5656.` | USD 3.57 |
| 3 (dry, after run 2) | same as run 2 | see below | — | — | 0 |

Total USD 9.92 (acceptance_step10: USD 10.76 for the same two runs).
Counter 128 after run 1, 134 after run 2; `gate_inspect.py` reports no
invariant violation in either dump.

## (ii) The free go/no-go: N = 28 > 26

acceptance_step10 run 2 counted 26 seeds for the same A1→B transition.
With the new ML the dry run counts 28: the two extra seeds are exactly the
two `fun` roots, `narquil` (its equation changed; its digest now carries
the equations, change 1) and `galmuth` (its pattern variables were
renamed; the digest now carries the equations AND no longer normalises
variable names away, change 1 + change 2).  The dry run yields a count,
not a seed set; the attribution rests on the run-2 host log below, where
both constants are judged — only seeds are sent.

## (iii) The live run: PASS

The host log of run 2 (`host_run2.log`) shows every gate line of the run:

```
gate: constant Sim_Measure_A1.plerx CHANGED by the prefilter (similarity 0.870)
gate: constant Sim_Measure_A1.tirneb CHANGED by the prefilter (similarity 0.739)
verdict: constant Sim_Measure_A1.kolvar same=False: …
verdict: constant Sim_Measure_A1.galmuth same=True: Same domain (list of natural numbers), same result (sum of even entries, odd ignored), same base case (zero on empty list), and same recursive-over-list-structure definition; the only differences are wording details …
verdict: constant Sim_Measure_A1.narquil same=False: Description 1 counts leaves whose number is strictly less than five, whereas description 2 counts leaves whose number is at most five, so the leaf condition differs.
gate: locale Sim_Measure_A1.dremnok CHANGED by the prefilter (similarity 0.873)
gate: constant Sim_Measure_A1.dremnok CHANGED by the prefilter (similarity 0.830)
```

PASS criteria (PLAN.md §9 item 3):

- a `verdict:` line names `constant Sim_Measure_A1.narquil` — yes;
- `narquil` judged CHANGED — `same=False`, and the store shows it minted:
  version 128 → 132, `interpreted_at` 132, baseline present;
- its lemmas re-interpreted by ENROLMENT: the five same-key records
  `narquil_small`, `narquil_large`, `narquil_glaive_commute`,
  `narquil_glaive_assoc` and `narquil.simps(2)` rose from `interpreted_at`
  128 to 132 and were answered after the verdict (host log :324-328).  In
  acceptance_step10 these five were untouched — that was finding 1.
  Cross-check: 23 enrolled here − 18 enrolled there = 5.  Not evidence:
  `narquil.simps(1)` and `narquil.elims` (both kinds) quote the edited
  equation, so their statements changed and they were answered in the seed
  batch as new theorem keys (host log :244-246), in acceptance_step10 as
  well.

Observation, not a criterion (the first live sample of the UNCHANGED path,
acceptance_step10 finding 3): `galmuth` is a seed, is re-interpreted, and
the judge answers `same=True`; its record keeps version 128 (no mint) with
the fresh interpretation text stored (313 characters, was 284), and its
dependents that kept their keys (`galmuth_nil`, `galmuth_singleton`,
`galmuth_append`, `galmuth_rev`, `galmuth_le_sum`) stay at
version 128 / `interpreted_at` 128 — walled.  (`galmuth_dom`, the
abbreviation `accp galmuth_rel`, has no edge to `galmuth` and says nothing
about the wall, as `narquil_dom` staying at 128/128 beside the minted
`narquil` shows.)  `galmuth.simps(1)`,
`galmuth.cases`, `galmuth.induct`, `galmuth.elims` were answered because
their statements changed (new theorem keys, uncached), not by enrolment.
The prefilter's cosine for `galmuth` is not in the log: the pipeline logs
the similarity only when the prefilter itself decides CHANGED
(`semantic_interpretation.py:1448-1451`); that `galmuth` reached the judge
means its cosine was at least 0.90, or the similarity was unavailable.

## Run 3 (free dry run after run 2)

On a fresh REPL process, the dry run of the same file against the store as
run 2 left it counts N = 0 (`dryrun3.txt`): nothing re-seeds, the digest of
each root now equals the stored one.

## Verdict

§9 item 3 PASSES: the `fun` constant's equation edit reaches its digest, the
gate judges it CHANGED, and its dependent lemmas are re-interpreted — the
direct repair of acceptance_step10 finding 1.  The UNCHANGED path was seen
live once (`galmuth`), behaving as SEMANTIC_CHANGE_GATE_PLAN §3 says.

## Rev 3.0 run (2026-09-14, PLAN.md §10.7 item 3)

Same setup, repeated on `Tools/semantic_digest.ML` as it stands after the
rev 3.0 review fixes and D9 (`unfold_sumC_axiom`): fresh `env.copy`
(compact) of the production `semantics.lmdb` (1.8 GB), `theory_hash.lmdb`,
`experience_index.lmdb` into `/var/tmp/qiyuan/gate_accept_db/`, a second
copy `gate_accept_db_after_run1/` taken after run 1; `SEMANTIC_DB_DIR` and
`INTERPRETATION_DRIVER=ClaudeCode.claude-opus-5` exported to the REPL
server and every Python process; a fresh REPL process per run; the same
`gate_dry_run.py`, `gate_inspect.py`, the same A1 scaffold and the same B
content under A1's name.  Raw logs in the session scratchpad
(`…/scratchpad/fun_accept2/logs/`: `collect_run{1,2}.log`,
`host_run2.log`, `inspect_after_run{1,2}.txt`, `dryrun_run{2,3}.txt`);
the 2026-09-13 log directories under `/var/tmp/qiyuan/` were deleted the
same day on the user's instruction, so the durable record is this file.
Nothing touched the production store.

| run | content | dry run | sent | closing line | cost |
|---|---|---|---|---|---|
| 1 (baseline) | A1 | N = 91 | 91 | `Sim_Measure_A1: 91 entities interpreted; cost $7.1348.` | USD 7.13 |
| 2 (gate) | B under A1's name | N = 28 | 51 (28 seeds + 23 enrolled) | `Sim_Measure_A1: 51 entities interpreted; cost $5.1759.` | USD 5.18 |
| 3 (dry, after run 2) | same as run 2 | N = 0 | — | — | 0 |

Total USD 12.31 (rev 2.3 run: 9.92; the difference is the driver's
token accounting, the entity counts are identical).  Counter 128 after
run 1, 134 after run 2; `gate_inspect.py` reports no invariant violation
in either dump.

(ii) N = 28 > 26 again: the two `fun` roots `narquil` and `galmuth` are
seeds, now because their digests are built from `narquil.simps` /
`galmuth.simps` (the named-fact source) — the same two seeds the rev 2.3
registry source produced.

(iii) PASS.  The gate lines of `host_run2.log` (:264-329):

```
gate: constant Sim_Measure_A1.tirneb CHANGED by the prefilter (similarity 0.795)
verdict: constant Sim_Measure_A1.kolvar same=False: …
verdict: constant Sim_Measure_A1.narquil same=False: The leaf conditions differ: description 1 counts leaves with n < 5, description 2 counts leaves w…
verdict: constant Sim_Measure_A1.galmuth same=True: Both describe the same recursive function summing exactly the even entries of a list of natural nu…
verdict: constant Sim_Measure_A1.plerx same=False: …
gate: constant Sim_Measure_A1.dremnok CHANGED by the prefilter (similarity 0.823)
verdict: locale Sim_Measure_A1.dremnok same=False: …
```

- a `verdict:` line names `constant Sim_Measure_A1.narquil` — yes;
- `narquil` judged CHANGED and minted: version 128 → 131, `interpreted_at`
  131, baseline present;
- its lemmas re-interpreted by ENROLMENT: `narquil_small`, `narquil_large`,
  `narquil_glaive_commute`, `narquil_glaive_assoc` and `narquil.simps(2)`
  rose from `interpreted_at` 128 to 131 and were answered after the
  verdict (host log :340-343); 23 enrolled − 18 in acceptance_step10 = 5,
  as on 2026-09-13.

Observation (the UNCHANGED path, second live sample): `galmuth` is a seed,
re-interpreted, judged `same=True`; its record keeps version 128 with the
fresh text stored (318 characters, was 289), and its dependents
`galmuth_nil`, `galmuth_singleton`, `galmuth_append`, `galmuth_rev`,
`galmuth_le_sum` stay at 128 / 128 — walled.  `plerx` reached the judge
this time (2026-09-13: decided by the prefilter) — the prefilter's cosine
is not logged when the judge decides, so nothing more can be said.

Run 3: on a fresh REPL process the dry run counts N = 0 — every root's
digest equals the stored one.

Verdict: §10.7 item 3 PASSES with the same evidence as the rev 2.3 run.
