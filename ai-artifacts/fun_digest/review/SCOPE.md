# Review scope: the plan "Function-package constants: equations into the semantic digest"

All paths are relative to `contrib/Semantic_Embedding/` (absolute root
`/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/`).  This is a
review of a PLAN before implementation: no production code has been
written.  The object under review is
`ai-artifacts/fun_digest/PLAN.md` (rev 1), together with the verification
record it rests on, `ai-artifacts/fun_digest/VERIFICATION.md`.

Do not modify any file.  Do not start, connect to, or kill any Isabelle,
poly or java process; do not run `isabelle build`; do not open any LMDB
store.  Rely on the measurements already recorded (they were taken on
Isabelle2025-2 on 2026-09-13; the raw probe theories and outputs are
readable at
`/tmp/claude-1002/-home-qiyuan-Current-MLML/8ee4dc8b-0295-46df-b280-a85bcc774433/scratchpad/fun_verify/`
and `.../scratchpad/fun_probe/`).  You may read Isabelle sources under
`/home/qiyuan/Current/MLML/contrib/Isabelle2025-2/src/` (Pure and
HOL/Tools/Function in particular) and everything in this repository.

## The problem (one paragraph)

The semantic store keeps, per constant, a digest of its meaning
(`Tools/semantic_digest.ML`, `sem_constant` / `own_defining_axioms`),
built from the constant's own defining axioms taken from `Defs`.  For a
constant defined by the function package (`fun`, `function`) the `Defs`
axiom is `f ≡ f_sumC …` — the equations are not in it; they live in the
infrastructure constant `f_graph` (no store record, limitation #6 of
`doc/invalidation_limitations.md`) and in the derived theorems
`f.simps`.  So editing a `fun`'s equations leaves its digest, its stored
English interpretation, and every dependent's interpretation untouched
(observed in the paid acceptance run, `ai-artifacts/acceptance_step10/REPORT.md`
finding 1).

## The plan's rule (PLAN.md §4; decisions §3 are the USER's and are settled)

In `own_defining_axioms`: ① class parameter → `[]` (unchanged); ② the
`Defs` axioms of the constant, own theory only via `same_theory`
(unchanged); ③ NEW: if ② is non-empty and the function package's own
registry (`Function_Common.retrieve_function_data`) has the constant,
REPLACE ② by the registry's `simps`, or `psimps` when `simps` is `NONE`
(termination unproved); ④ otherwise ② (unchanged); ⑤ the `Spec_Rules`
fallback, unchanged, serving `axiomatization` constants only.

User decisions that the review must NOT re-open: direction A (equations
into the digest), replace-not-add, the registry as the source with
`psimps` accepted for unterminated functions, no `Spec_Rules.dest_theory`,
`Spec_Rules` untouched, "sort after normalize" not done now.  You may
PROPOSE relaxing one of them if that makes the design markedly simpler or
more elegant — as an explicit proposal for the user, never smuggled in as
a defect.

## What the review is asked to judge

1. Correctness of the rule against Isabelle's actual machinery: what
   `Function_Common.retrieve_function_data` returns (Item_Net keyed on the
   function terms, `transform_function_data` with a transfer morphism,
   polymorphic constants, mutual blocks `fun f and g`, nested recursion,
   `fun` inside `instantiation` / `class` / `overloading` / `locale`,
   `function` without `termination`, theories that merge two parents);
   whether `Proof_Context.init_global thy` is the right context; whether
   the props' names and the sort make the digest deterministic; whether
   the dependency edges derived from the props are right (the `f_dom`
   edge for psimps; the mutual-block SCC that `_EffStar` folds).
2. Invalidation semantics: the change moves the digest of every
   function-package constant once (20 record-eligible in this heap); does
   the gate handle that as the plan says (seed → prefilter/judge →
   UNCHANGED walls → no dependents)?  Is anything about `interpreted_at`,
   eff\*, or the dry run affected?  Are any of the four write-back
   disciplines of `archive/plans/CHECK_OUTDATE_PLAN.md` §8 touched?
3. Elegance and reuse: is "replace the Defs axiom by the registry's
   equations" the cleanest shape, or is there a shape that makes the
   invariant impossible to violate (e.g. one that never consults `Defs`
   for such constants, or one that treats `f_graph` differently)?  Any
   dirty hack (name-string matching, `.simps` fact lookup by name,
   special-casing by suffix) must be rejected; the plan avoids these —
   check that the implementation notes do not sneak one back in.
4. Tests and documentation adequacy (PLAN.md §5): do the proposed
   `Test_Sensitivity.thy` assertions actually discriminate (they must
   FAIL on today's code and PASS after; and must not be satisfiable via an
   unrelated path — see the two rules at the top of that file); are the
   §14 rows and the limitation #6 note the right places.
5. What is missing: any case the verification did not measure that could
   bite (PLAN.md §6 lists the ones deliberately left).

## Project rules that bind the review

- Elegance is a review criterion equal to correctness; reject dirty hacks.
- Reuse code, never reinvent; consistent terminology (the glossary of
  `archive/plans/CHECK_OUTDATE_PLAN.md` and `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` §0
  are authoritative; never coin new words).  Code comments short and
  load-bearing.
- Never `isabelle build`; the only Isabelle entry point is the REPL server
  (not to be used in this review).
- Nitpicking is to be rejected harshly and named as such: style-only
  remarks, hypotheticals with no concrete failure, restating the plan,
  "consider adding a comment", re-raising a settled user decision, asking
  for measurements that cannot change the design.
- Minimal fixes; never change existing behaviour beyond the user's
  decision.

## Round two: re-review of PLAN.md rev 2.1 (2026-09-13)

The object is now `ai-artifacts/fun_digest/PLAN.md` **rev 2.1**; the first
round's judge ruling is the material in the workflow journal summarised in
the plan's status line.  What changed since rev 1, and what this round is
asked to judge:

- **User decisions taken after round one** (settled, do not re-open):
  F2 revised from "replace" to **merge** (③ adds the registry's equations
  to the own-theory `Defs` axioms; nothing is filtered by name); the
  judge's type-conjunct proposal withdrawn as a consequence; **F6′**: the
  alpha-normaliser `normalize` is REMOVED and the sort of a constant's
  props kept, folded into this work (PLAN.md §5); the end-to-end acceptance
  is PAID (§9 item 3).
- **Rulings of round one applied** (verify each is in the plan and true):
  the `f_dom`/`accp` correction; the one-time cost restated (persistent
  theories carry no digest); the `instantiation` test subject deleted; the
  `partial_function (option)` control added; the new test subsection builds
  its own env; §7 bullets for the locale target, `termination` flip and
  diamond merge, Nominal's own registry; §7.3 item 1, the signature comment
  and the header comment listed; the census marked as taken on the wrong
  source, to be re-taken on the registry (§9 item 2).
- **Implementer's choices routed self-decide-then-rereview**: `ctxt` in
  the `env` record; one shared comparator `prop_ord` for the fallback and
  the new branch (the `Defs` branch's name-only sort untouched); a NEW
  numbered entry in `doc/invalidation_limitations.md` for the class "a
  constant whose own definitional content does not reach its own digest".
  Judge these on elegance and on whether nothing outside the
  function-package family moves.

Questions for this round:

1. Under MERGE, is anything counted twice, and does any constant outside
   the function-package family change digest through change 1?  Is the
   surviving `f_sumC` dead edge and the body-free axiom in the payload
   acceptable (the plan says yes; a name-based filter would be a hack)?
2. Change 2 (removing the normaliser): is every use of `normalize` in
   `Tools/semantic_digest.ML` and `Test/Test_Sensitivity.thy` accounted
   for (§5)?  Do the rewritten S3e/S8 assertions still discriminate?  Does
   any statement in `archive/plans/CHECK_OUTDATE_PLAN.md`,
   `doc/invalidation_limitations.md`, `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md`
   or a code comment become false, beyond the sites §5 lists?  Are the
   locale/type-abbreviation parameter payloads (`Free`, `typ_payload`)
   still correct without normalisation (a parameter rename now moves the
   digest — by decision)?
3. Is the paid acceptance (§9 item 3) specified so that it actually
   proves the change (seed set contains `narquil` for the digest reason,
   `galmuth` now a seed by F6′ and judged UNCHANGED)?
4. Anything left that blocks "开工".

## Round three: verification of PLAN.md rev 2.2 (2026-09-13)

The object is `ai-artifacts/fun_digest/PLAN.md` **rev 2.2**.  Since round
two: every round-two ruling routed "fix" was applied by hand; the
pre-flight census was taken on the registry source
(`ai-artifacts/fun_digest/CENSUS.md`) and §2/§7/§9 were rewritten from
it; the user chose §5 (b) — `digest_term` exported from `SEMANTIC_DIGEST`
as the standing guard of change 2, S3e/S8 deleted.  Round-two rulings and
the round-two SCOPE section above remain the reference; the plan's
decisions F1–F7 and §8 are settled.

This round is a VERIFICATION round, not a new hunt: (1) is every
round-two "fix" ruling present in rev 2.2 and true of the code and the
census (cite the ruling id and the plan line)?  (2) does any sentence
rewritten from CENSUS.md misquote it?  (3) is anything in rev 2.2
internally inconsistent (a cross-reference that resolves to nothing, a
number that disagrees between sections, a decision stated two ways)?
(4) does the §6 MERGE pin assertion and the §5 (b) guard assertion each
FAIL today and PASS after, and is neither satisfiable through an
unrelated path?  (5) is anything left that blocks "开工"?  Nitpicks,
re-opened decisions and new hypotheticals without a concrete failure are
rejected as before.

## Round four: review of the IMPLEMENTATION (2026-09-13, evening)

The object is now the CODE, not the plan.  Uncommitted working-tree changes
(read them with `git diff` in `contrib/Semantic_Embedding/`; the plan is
`ai-artifacts/fun_digest/PLAN.md` rev 2.3, the acceptance record
`ai-artifacts/fun_digest/ACCEPTANCE.md`):

- `Tools/semantic_digest.ML`: `env` gains `ctxt` (built once in `make_env`);
  the alpha normaliser is deleted and `digest_term = Term_Digest.term128`,
  exported; one comparator `prop_ord` shared by `spec_rule_axioms` and the
  new `function_equations`; `own_defining_axioms` MERGES the own-theory
  `Defs` axioms with `function_equations` (registry `simps`, else `psimps`)
  when the `Defs` result is non-empty; comments rewritten (header, the
  hash, `typ_payload`, `sem_type` and `sem_locale` parameter comments).
- `Test/Test_Sensitivity.thy`: S3e and S8 deleted with their subjects; new
  S13 (a–h) and S14.  Observed: S13a–e and S14 FAIL on the old module (with
  only the `val digest_term` signature line added) and PASS on the new;
  S13f–h pass on both; `Test_All` passes (19672/19672 resolved, 1134 with
  digest, 211734 edges, determinism OK); the registry re-check over the 38
  census constants gives 32 gain simps / 6 class parameters `[]` /
  `fold2_bit_int.F` unchanged.
- Docs: `archive/plans/CHECK_OUTDATE_PLAN.md` §7.3 (四条→三条, item 1 gains
  the registry layer), §14 (four rows), glossary; `doc/invalidation_limitations.md`
  (#8 new, #6 and #7 one paragraph each, header date);
  `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` §5.2; `semantics.py:318`.
- Paid acceptance (ACCEPTANCE.md): dry run N = 28 (was 26), `narquil`
  judged CHANGED and minted (128 → 132), its lemmas re-interpreted;
  `galmuth` judged UNCHANGED (same=True), version kept, dependents walled.

Judge the code against PLAN.md §4/§5/§6 (every implementation note
honoured? anything beyond the user's decisions changed? elegance: is the
merge branch the cleanest shape, are the comments short and load-bearing,
is anything dead or duplicated?), the tests (do S13a–e/S14 discriminate as
claimed, are the controls honest, is the `_def_raw` note right), the docs
(is any rewritten sentence false or coined), and the acceptance (does the
evidence prove what ACCEPTANCE.md says).  Same nitpick rules as before;
decisions F1–F7 and §8 are settled.

## Round five: re-review of the round-four fixes (2026-09-13, evening)

Round four's judge (`review/impl_judge.json`) ruled READY_AFTER_FIXES: F1
routed to the user, nine wording items routed self-decide-then-rereview.
What changed since (verify each; everything else is unchanged and NOT
re-opened):

- **F1, decided by the user as option A** after an Opus 5 agent verified
  option B (query with each Defs axiom's lhs) correct only with two extra
  guards (premise-carrying `resolve_prop` answers raise `dest_equals` on 21
  heap constants; `overloading` families duplicate) and another measured
  A's cost (0.3 ms per heap pass, 0.07 % of `Test_All`'s pass; all extra
  queries miss).  Code: `function_equations` now issues one query per
  argument count 0..arity with `Var` placeholders (`Tools/semantic_digest.ML`,
  the block comment explains the `f ?x` key); test S13i
  (`context fixes sens_k … fun sens_cfun`, asserting `plus` is mentioned) —
  red on the pre-A module (measured by the verifying agent), green now;
  PLAN.md §2 (the `f ?x` fact), §4 (the per-count lookup), §8 (the
  decision); CHECK_OUTDATE_PLAN §7.3 item 1 and §14 gain the shape;
  limitation #8 says the shape is NOT in its list.
- The nine wording fixes, each as the judge specified: S13g's `_def_raw`
  note (always `_def_raw`, `Specification.gen_def`); `prop_ord` moved to
  directly after `class_param_of`; ACCEPTANCE.md's narquil bullet (five
  same-key enrolments, the two new-key facts excluded, 23 − 18 = 5) and
  `galmuth_dom` removed from the walled list; limitation #8's first bullet
  and '为何接受' reworded to the measured absence (D1); §7.3 item 1's
  "只能从登记表取到" replaced by the two facts (nameless `Spec_Rules` item,
  no item for unterminated `function`) and PLAN.md §6 likewise (D2); §3.2's
  constant row (D3); §14's change-2 row (D4); the gate plan's status
  paragraph (D8).

Measured after the fixes (fresh REPL): `Test_Sensitivity` all green
(S13a–i, S14), `Test_All` green, registry re-check 32/6/1 unchanged,
`Ctx_Probe`: `step` now carries its two simps beside `step_def`.

Judge only the delta: is option A implemented exactly and minimally (no
dead code, the comment true and short), does S13i discriminate and is its
placement right, is every wording fix faithful to the ruling and true, does
anything in PLAN.md now contradict itself (rev 2.3 text vs the F1
amendments), and is anything left that blocks "提交".
