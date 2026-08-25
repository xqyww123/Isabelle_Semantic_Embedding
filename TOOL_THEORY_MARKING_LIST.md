# Tool-support theory marking list (D15, ruled 2026-08-25)

Companion to `INFRA_FILTER_REWORK_PLAN.md` D15 and the sibling
`DECISION_PROCS_INFRA_THEORY_LIST.md`. Source: the 2026-08-24 KEPT-side
constant audit found ~558 tool-plumbing constants in unmarked theories; a
dedicated research pass then vetted each candidate theory for AFP
statement-level citations (grep universe: `afp-2026-05-13/thys` `*.thy`,
unicode copies excluded, the tool's own session excluded). Owner ruling:
**23 marked, `Random`/`Predicate_Compile` withheld (zero-casualty bar),
`Code_Numeral` never marked.**

Reading note: "cascade casualty" = a theorem whose STATEMENT mentions the
theory's constants (marking rejects it everywhere). Fact-NAME citations in
proof methods (`metis Foo.bar`) are not cascade casualties, but marking does
drop those facts from retrieval. Textual grep cannot see mentions that appear
only after unfolding — the post-step-2 re-run is the final check.

## Marked (23)

| Theory (kept consts) | Key evidence |
| --- | --- |
| `HOL.Quickcheck_Exhaustive` (77) | 6 citation lines / 2 files (Linear_Recurrences/RatFPS, Native_Word) — all quickcheck-generator instantiation equations |
| `HOL.Quickcheck_Narrowing` (49) | 10 lines / 4 files — all narrowing / `partial_term_of` instantiation plumbing (Native_Word, Coinductive, Go) |
| `HOL.Quickcheck_Random` (12) | 3 lines / 1 file (RatFPS random-generator instantiation) |
| `HOL.Random_Pred` (13) | 0 AFP citations |
| `HOL.Random_Sequence` (32) | 1 hit = commented-out `hide_fact`; no `random_dseq` `code_pred` mode used anywhere in AFP |
| `HOL.Lazy_Sequence` (32) | 0 citations (qualified and unqualified) |
| `HOL.Limited_Sequence` (28) | 0 citations |
| `HOL.Nitpick` (45) | 65 lines / 37 files, ALL fact-name citations in proofs (`Nitpick.size_list_simp`, `case_nat_unfold`, `rtranclp_unfold`, … — sledgehammer artifacts); zero statement mentions. Effect-1 loss: those five convenience facts (standard alternatives exist) |
| `HOL.Nunchaku` (3) | 0 citations |
| `HOL.SMT` (8) | `SMT.trigger`/`pat` in AFP statements: **0** (spot-verified); the feared trigger-in-user-statement scenario occurs nowhere in AFP or src/HOL. Other hits are fact citations only |
| `HOL.Meson` (6) | COMB*/skolem: 0 statement citations; `Meson.disj_comm` etc. used as proof rules in 4 files |
| `HOL.Metis` (2) | only false-positive hits (Zippy's own ML structure) |
| `HOL.Record` (15, iso_tuple layer) | one statement-level citation in all of AFP (Physical_Quantities `mmore_def`, itself plumbing-grade); dominant hit is the fact `iso_tuple_UNIV_I` (statement has no Record constants). User record FIELDS are separately whitelisted and unaffected |
| `HOL.Typerep` (6) | 8 lines / 6 files — typerep instantiations and code-printing setup only |
| `HOL.Extraction` (4) | `sumbool` → 0 AFP hits |
| `HOL-Library.Code_Test` (24) | 3 hits: ML `setup` + a comment |
| `HOL-Library.Code_Lazy` (6) | constant citations 0; 8 entries use only the `code_lazy_type` command; casualties = auto-generated lazy code equations |
| `HOL-Library.Code_Target_Nat` | 3 hits: comment, proof-fact, `[code_computation_unfold]` setup |
| `HOL-Library.Code_Target_Int` | 4 lines / 1 file (ODE `[code_computation_unfold]` lemmas) |
| `HOL-Library.Code_Cardinality` (5) | 5 lines / 2 files — `[code]` bridging/refinement lemmas |
| `Tools.Code_Generator` (1) | `Code_Generator.holds` → 0 hits |
| `HOL-Real_Asymp.Multiseries_Expansion` (127) | zero statement-level constant citations (spot-verified: `expands_to`/`dominant_term` 0 hits); 30 entries import HOL-Real_Asymp only for the `real_asymp` METHOD (cascade-irrelevant); 2 entries cite `intyness_simps` FACTS in smt/metis calls. Structurally the HOL-Decision_Procs analog |
| `HOL-Real_Asymp.Lazy_Eval` (7) | 0 hits |

Known plumbing casualties accepted with the 23: quickcheck instantiations
(Native_Word, Coinductive, Linear_Recurrences), `code_lazy_type` /
`[code_computation_unfold]` / `[code]` refinement lemmas (8 entries + ODE +
EFSM/Containers), one `mmore_def` (Physical_Quantities).

## Withheld under the zero-casualty bar (2)

- `HOL.Random` (14) — the only candidate whose statement-level citations are
  NOT machine-generated: JinjaThreads' hand-written random scheduler and
  Containers' benchmark generators would lose ~20 defining equations. No
  mathematical lemma anywhere cites a Random constant, but the casualties are
  hand-written entry content.
- `HOL.Predicate_Compile` (2) — ~25 hand-written `code_pred_intro`
  executability rules in three entries (CoreC++, JinjaThreads, Safe_OCL)
  mention `Predicate_Compile.contains` in their statements.

## Never mark (1)

- `HOL.Code_Numeral` (29) — `nat_of_integer` cited in 92 AFP files
  (spot-verified), `integer_of_nat` 74, `int_of_integer` 66, including
  ordinary proved lemmas; total blast radius ≈ hundreds of theorems across
  ~100 entries. The `Algebra_Aux` failure mode at 10x scale. Its 29 plumbing
  constants stay as visible noise.
