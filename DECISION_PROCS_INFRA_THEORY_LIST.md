# Which `HOL-Decision_Procs` theories are infrastructure

Companion to `THEORY_HASH_REKEY_PLAN.md` §8.3. Produced 2026-08-19 by reading
every theory of the session in
`contrib/Isabelle2025-2/src/HOL/Decision_Procs/`.

## Why this list exists

`infra_filter.ML:26` marks the whole session `HOL-Decision_Procs` as
infrastructure. A session is a directory, not a semantic unit, and the marking
caught `Algebra_Aux.thy`, which is ordinary ring and field algebra. The damage
was measured: of `EC_Common`'s 15 `field` lemmas the filter rejects 12, and the
store holds exactly the other 3.

The fix is to mark theories instead of the session. No new mechanism is needed:
`infra_base_theory_names` (`infra_filter.ML:38`, today `["Minilang"]`) already
matches by theory base name, and `:315-320` puts both markers into the same
prefix list. This document is the theory-by-theory classification that fix
needs.

## What marking a theory as infrastructure does

Three effects, and the third is the one that costs money.

1. **No records for its own entities.** Its constants, theorems, types and
   locales get no record and are not retrievable.
2. **The cascade.** Any theorem anywhere whose statement mentions one of its
   constants is also dropped — `is_infra_thm` via
   `Term.exists_Const is_internal_constant` (`infra_filter.ML:444`). This is
   intended and documented behaviour (`infra_filter.ML:52-53`), and it is right
   when the constant is genuine machinery. Matching is on the **fully
   qualified** constant name, so `Cooper.unit`, `MIR.eq` and
   `Parametric_Ferrante_Rackoff.Add` cannot collide with ordinary constants of
   the same base name.
3. **The theory is never interpreted at all.** `semantic_store.ML:1867`
   `is_excluded_theory` calls `is_infra_session`, and its own comment says
   "Theories that are never interpreted". So today `Algebra_Aux.thy` has no
   records because it was never interpreted, not because a filter rejected it.
   **Every theory this list moves to `keep` has to be interpreted, which costs
   LLM budget.** Effect 3 currently keys off `is_infra_session` and not off
   `infra_base_theory_names`; wiring it to the theory list is part of the
   change, and until it is, a theory flipped to `keep` still never gets
   interpreted.

## The criterion

- **`infra`** — the content is machinery that exists only to make a decision
  procedure or proof method work: reflected syntax datatypes, their
  interpretation functions, normalisation and elimination functions on them, and
  the correctness lemmas about those. A theorem elsewhere mentioning these
  constants is genuinely worthless to retrieve, so the cascade over them is
  right.
- **`keep`** — ordinary mathematics or generally useful library material that
  merely happens to sit in this directory. Being *used by* a decision procedure
  does not make it machinery.

## The classification

`lemma` and `def` counts are `grep` counts of top-level commands, for sizing the
interpretation cost of a `keep`.

| theory | verdict | lines | lemmas | defs | what decided it |
| --- | --- | ---: | ---: | ---: | --- |
| `Algebra_Aux` | **keep** | 507 | 62 | 4 | ordinary ring/field algebra; the cascade source |
| `Polynomial_List` | **keep** | 1032 | 113 | 15 | univariate polynomials as coefficient lists |
| `DP_Library` | **keep** | 40 | 4 | 1 | generic list combinator, no reflection in it |
| `Commutative_Ring` | infra | 961 | 40 | 49 | `pol`/`polex` shadow syntax behind `method ring` |
| `Commutative_Ring_Complete` | infra | 515 | 15 | 1 | only `isnorm`, a predicate on `pol` |
| `Reflective_Field` | infra | 928 | 26 | 37 | `fexpr`/`pexpr` shadow syntax behind `method field` |
| `Conversions` | infra | 839 | 7 | 57 | declares **no HOL constant**; ML numeral conversions |
| `Cooper` | infra | 2607 | 119 | 54 | reflected Presburger QE |
| `Ferrack` | infra | 2526 | 120 | 56 | reflected linear-real QE |
| `MIR` | infra | 5709 | 238 | 104 | reflected mixed int/real QE — **real loss, see below** |
| `Approximation` | infra | 1187 | 33 | 22 | `floatarith` reflection + the trusted oracle |
| `Approximation_Bounds` | **keep** | 3101 | 119 | 19 | the authors split this file out as the ordinary-mathematics half |
| `Reflected_Multivariate_Polynomial` | infra | 2038 | 144 | 41 | reflected `poly` terms; zero ordinary mathematics |
| `Rat_Pair` | infra | 589 | 42 | 17 | rationals as `int × int` for the reflected procedures |
| `Dense_Linear_Order` | infra | 881 | 81 | 13 | QE rule tables — **small loss, see below** |
| `Parametric_Ferrante_Rackoff` | infra | 4013 | 212 | 88 | reflected `tm`/`fm` QE with polynomial parameters |
| `Decision_Procs` | infra | 17 | 0 | 0 | imports only; nothing between `begin` and `end` |
| `ex/Commutative_Ring_Ex` | infra | 134 | 28 | 0 | anonymous smoke tests |
| `ex/Approximation_Ex` | infra | 87 | 14 | 0 | anonymous smoke tests |
| `ex/Approximation_Quickcheck_Ex` | infra | 39 | 5 | 0 | 4 of 5 are **deliberately false**, kept for `oops` |
| `ex/Dense_Linear_Order_Ex` | infra | 164 | 47 | 0 | anonymous smoke tests |

`Approximation.unicode.thy` is not in this table. There are 648 `*.unicode.thy`
files in the two distributions and no `ROOT` or theory references any of them —
they are our generated transcriptions and are never loaded. It was confirmed
line-for-line identical to `Approximation.thy` up to symbol spelling.

## The two `keep` theories

**`Algebra_Aux.thy`** — header: "Things that can be added to the Algebra
library"; imports `HOL-Algebra.Ring`. Defines `of_natural` (`:11`, the canonical
embedding of the naturals into a ring), `of_integer` (`:14`), `m_div` (`:318`,
ring division `⊘`), and the record `cring_class_ops` (`:236`) that presents a
`comm_ring_1` type class as a `ring` record. Its ~30 `(in field)` fraction
lemmas (`:394-465`) are the generic facts every `field` interpretation inherits.
`Elliptic_Locale.thy:48` writes the elliptic-curve addition law itself as
`l = («3» ⊗ x⇩1 [^] 2 ⊕ a) ⊘ («2» ⊗ y⇩1)`, and `EC_Common.thy:87-155` does the
same. Dropping those is the failure this whole exercise is about.

**`Polynomial_List.thy`** — "Univariate Polynomials as lists", by Amine Chaieb.
Defines `poly` (evaluation), `+++`, `%*`, `***`, `%^`, `pquot`, `pnormalize`,
`order` (root multiplicity), `degree`, `rsquarefree`. Contains the factor
theorem `poly_linear_divides` (`:253`), finiteness of the root set
`poly_roots_finite` (`:389`), `poly_entire` (`:419`), `poly_primes` (`:495`),
the order existence/uniqueness results (`:618, :663, :684`), `order_root`
(`:704`), `order_mult` (`:741`), `order_degree` (`:992`). No `datatype` appears
in the file at all.

One caveat that is a naming problem, not an infrastructure problem: its `poly`,
`degree` and `order` shadow the same short names in
`HOL-Computational_Algebra.Polynomial`. They are distinct constants and both
would be in the store.

## Where marking a theory `infra` genuinely destroys something

The filter has **no per-theorem keep-list**. `preserved_set`
(`infra_filter.ML:175-215`) is computed, not declared — it holds datatype
constructors and selectors, record fields and BNF `map`/`pred`/`rel`/`sets`, to
stop other rules from killing them. The only user-facing declarations run the
other way: `[[infra_constant c]]`, `[[infra_type T]]`, `lemma[infra_thm]`. So
each theory is all-or-nothing, and these three losses are real.

**`MIR.thy` — about 19 unique lemmas, the largest loss.** Roughly 10% of the
file is ordinary mathematics about `int`, `real` and `⌊·⌋`, and it introduces a
constant that exists nowhere else: `rdvd` (`:34`), divisibility lifted to the
reals, `x rdvd y ⟷ (∃k::int. y = x * real_of_int k)`, with 8 lemmas
(`:37, :53, :57, :75, :78, :81, :1112, :1115`). Then the 8 floor case-split
lemmas at `:1658-1720` — `split_int_less_real`,
`real_of_int a < b ⟷ (a < ⌊b⌋ ∨ (a = ⌊b⌋ ∧ real_of_int ⌊b⌋ < b))`, and its
seven siblings; `Archimedean_Field.thy` has the plain forms (`:220`, `:232`) but
not these. Then `real_ex_int_real01` (`:4786`),
`(∃x::real. P x) = (∃i::int. ∃u. 0 ≤ u ∧ u < 1 ∧ P (real_of_int i + u))`, and
`real_in_int_intervals` (`:3498`), `small_le` (`:3788`), `small_lt` (`:3793`).
`rdvd` has zero users outside `MIR.thy` in the distribution and the whole AFP,
so the cascade is empty; the loss is direct.

**`Approximation_Bounds.thy` — 13 unique lemmas.** Of 119 statements, 106
mention a constant of the file or `float`/`interval`/`prec`/`set_of`. The 13
that do not are: `horner_schema'` (`:31`), `sqrt_ub_pos_pos_1` (`:415`, the
Heron step), `arctan_lower_bound` (`:701`, `0 ≤ x ⟹ x/(1+x²) ≤ arctan x`), the
`arctan` monotonicity quartet `arctan_divide_mono`/`arctan_mult_mono`/
`arctan_mult_le`/`arctan_le_mult` (`:712-733`), `cos_periodic_nat` (`:1719`),
`cos_periodic_int` (`:1733`), `exp_m1_ge_quarter` (`:2109`), `ln_bounds`
(`:2391`), `ln_add` (`:2458`), `mono_exp_real` (`:3000`). None has a namesake
elsewhere in the distribution; only `cos_periodic_int` has one in the AFP.

Two reassurances on this theory's cascade, both checked: in
`Bertrands_Postulate/Bertrand.thy` every `ub_ln` occurrence
(`:380, :901, :907, :913, :1032, :1449`) is inside a `by code_simp` proof step
and never in a statement, so Bertrand's number theory is untouched; and
`Karatsuba_Sqrt_Float.thy:89` defines its **own** `sqrt_float_interval`, a
different constant sharing a short name, so its statements are not victims.

**`Dense_Linear_Order.thy` — 3 lemmas and 2 proof methods.** The authors tagged
76 of its 90 lemmas `[no_atp]` themselves; those are the quantifier-elimination
rule tables fed to `langford.ML`/`ferrante_rackoff.ML` through the
`declare … [langford …]` and `[ferrack …]` attributes (`:290`, `:507`). Worth
keeping are `interval_empty_iff` (`:219`) and `finite_set_intervals` /
`finite_set_intervals2` (`:149`, `:198`). Separately, marking it infra removes
the **methods** `dlo` (`:314`) and `ferrack` (`:548`) from the store, so an
agent would not learn that `by dlo` exists.

## Where marking a theory `infra` costs nothing

Checked, not assumed:

- `Cooper`, `Ferrack`, `Reflected_Multivariate_Polynomial`,
  `Parametric_Ferrante_Rackoff`: no theory in the distribution or the AFP
  imports them except the session's own `Decision_Procs.thy`. Sixteen AFP
  sessions name `HOL-Decision_Procs` as their parent, so the constants are in
  scope, but no AFP statement uses one.
- `Commutative_Ring`, `Reflective_Field`: the two AFP entries that do import
  them, `Elliptic_Axclass.thy` and `Elliptic_Locale.thy`, use them only through
  `apply (ring …)` / `apply (field …)`. A method invocation leaves no constant
  in the theorem's term, so `Term.exists_Const` never fires.
- `Approximation`: 26 AFP entries plus `HOL/Real_Asymp/Real_Asymp_Approx.thy`
  import it, but almost all only invoke `by approximation`. The real cascade
  footprint is 15 files (Affine_Arithmetic, Taylor_Models,
  Ordinary_Differential_Equations, Poincare_Bendixson, Safe_Distance,
  Floatarith_Expression), and every one is itself rigorous-numerics machinery
  whose statements say "the interval evaluation is sound". The theory ends with
  a section titled "Avoid pollution of name space" (`:1143`) followed by
  `hide_const (open) Add Minus Mult …`, so it declares its own constants unfit
  for the global name space.
- `Rat_Pair`: its only two non-reflected lemmas, `of_int_div_aux` (`:216`) and
  `of_int_div` (`:233`), duplicate `Euclidean_Rings.thy:1714`.
- `Conversions`: introduces no HOL constant at all, so the cascade cannot fire
  from it. Its seven lemmas include the reflexivity stubs
  `minus_one: "- 1 = - 1"` and `minus_numeral: "- numeral b = - numeral b"`
  (`:341-342`).
- `Decision_Procs` and the four `ex/` files: zero entities defined; every `ex/`
  lemma is anonymous, and four statements in
  `ex/Approximation_Quickcheck_Ex.thy` (`:5-11, :22-38`) are deliberately false,
  kept as `quickcheck[expect=counterexample] oops` regression tests.

## Decision taken (2026-08-20): `Approximation_Bounds` is kept

Reversed from `infra`. The authors state the split themselves, in the file's own
header (`Approximation_Bounds.thy:5-9`):

> This file contains only general material about computing lower/upper bounds on
> real functions. Approximation.thy contains the actual approximation algorithm
> and the approximation oracle. This is in order to make a clear separation
> between "morally immaculate" material about upper/lower bounds and the trusted
> oracle/reflection.

Marking it was the `Algebra_Aux` failure in a new place: a file of ordinary
mathematics classified by the directory it sits in, against an explicit
authorial statement that it is the ordinary half. The counter-evidence stands
and is recorded below — 106 of its 119 statements mention `float`, `interval`,
`prec` or `set_of` — but it is evidence about the *shape* of the statements, not
about what the file is for, and it does not outweigh the authors' own division.

Consequences: the marked set drops from 18 to 17; the 11 novel lemmas listed
below stop being a loss and need no aliasing; and `Approximation.thy` — the
oracle-and-reflection half — stays marked, which is exactly the separation the
header describes.

## Decisions taken (2026-08-19)

1. **`DP_Library.thy` is `keep`.** It is a generic list combinator
   (`alluopairs :: 'a list ⇒ ('a × 'a) list`) with no reflected syntax in it;
   that its only callers happen to be `Ferrack` and `MIR` does not make it
   machinery. 5 records.
2. **The direct losses are accepted** — the ~19 `MIR` lemmas, the 13
   `Approximation_Bounds` lemmas, and `Dense_Linear_Order`'s 3 lemmas and two
   proof methods. No per-theorem keep-list will be built for this.
3. **The interpretation budget is approved** for the three `keep` theories:
   `Algebra_Aux` (62 lemmas + 4 definitions), `Polynomial_List` (113 + 15),
   `DP_Library` (4 + 1).
4. **`infra_session_names` is emptied and the session concept retired.**

## Identity: theory LONG names, resolved through the name space

An earlier revision of this document had a section here called "The unsolved
problem", claiming the per-entity matcher could only see theory base names
because Isabelle qualifies constants that way. **That was wrong and is
withdrawn.**

`Name_Space.theory_name {long: bool}`
(`contrib/Isabelle2025-2/src/Pure/General/name_space.ML:24, :263`) returns the
name of the theory that declared an entity, reading the name-space entry rather
than the spelling of the name. And this file already uses it three times:
`infra_filter.ML:471-472` (`is_infra_method`, comparing `#theory_long_name`
against a `Symtab.set` of theory long names), and `:258` / `:267` on the constant
space.

So `Cooper.qelim` resolves to `HOL-Decision_Procs.Cooper` while the AFP theory of
the same base name resolves to `LinearQuantifierElim.Cooper`. Exact, no
collision.

**Why it matters, measured.** Base-name matching would have destroyed 259
existing store records on day one: 216 from `Correctness_Algebras.Approximation`
(Walter Guttmann's approximation in correctness algebras) and 43 from
`LinearQuantifierElim.Cooper` (Nipkow 2007). The other 14 names destroy 0. Note
that today's code does **not** have this bug: `infra_filter.ML:306-310` gates the
session-derived prefixes through `Theory.ancestors_of thy`, and neither AFP
session has `HOL-Decision_Procs` in its cone. The exposure belonged to the
*proposed* edit, because `infra_base_theory_names` (`:38`) is static and
unconditional.

A second, independent benefit, measured live over `Complex_Main`: entity names
are not always qualified by their declaring theory's base name — 8 of 3568
constants, 24 of 29985 facts (all `instantiation`-generated, e.g.
`Set.typerep_set_inst.typerep_set` declared in `HOL.List`), 45 of 168 types
(Pure syntax types with no qualifier at all). The prefix test misjudges all of
these; the lookup judges them all correctly.

## Decisions taken in review, 2026-08-20

A three-reviewer, two-round adversarial review (Opus 5) ran over this document
and the code. These are the rulings.

1. **Identity is the theory long name.** One `Symtab.set` of theory long names,
   consulted per name space via `try (Name_Space.theory_name {long = true} space)`,
   shared by three consumers: the per-entity filter (`:355` constants, `:441`
   facts, `:538` types, `:541` classes, `:544` locales), `is_infra_theory`, and
   `is_excluded_theory` (`semantic_store.ML:1867`). The prefix machinery at
   `:306-320` is deleted.
   **Implementation trap:** do NOT fold `internal_prefixes` (`:312-313`) into the
   long-name set. It contains `"HOL.equal"`, a *constant*-name prefix; mapping it
   to a theory long name yields `HOL.HOL` and would mark the whole of `HOL.thy`
   as infrastructure. Only the duplicated `infra_session_thy_prefixes` tail is
   removed from it (it is tested twice today, at `:355` and `:356`).
2. **The list is enumerated, not derived from the session.** 19 long names
   (`Minilang.Minilang` plus the 18 infrastructure theories of this session).
   The alternative — session default plus a three-entry keep-list, four entries
   total — was considered and declined. Reason: it fails in the *deleting*
   direction. A nineteenth theory added upstream would default to
   infrastructure and vanish silently, which is exactly the `Algebra_Aux`
   incident; enumeration defaults it to ordinary mathematics, so it appears as
   visible retrieval noise that can be fixed later. Measured: the `.thy` file set
   of this directory is unchanged between Isabelle2024 and Isabelle2025-2, so the
   maintenance saving was hypothetical.
3. **The count is 18, not 16** (21 real theories minus 3 keeps). Earlier
   revisions of this document said 16 in the prose and in "The edit".
4. **`is_infra_theory` is NOT retired.** It has a live caller:
   `tasks/AoA-learning/learning.ML:123`, loaded by `ML_file` from
   `AoA_Learning_App.thy:5`. An earlier revision of this document said it had no
   callers anywhere; that was a grep scoped to `contrib/` and `ICSE27/`, missing
   `tasks/`. The call site keeps its name and signature; only the set behind it
   changes. Its scope does change: `Algebra_Aux` enters the AoA learning target
   set (it is one of 7 `Decision_Procs` theories in
   `tasks/AoA-learning/targets_full`; the other 6 stay marked, and
   `Polynomial_List` / `DP_Library` are not in that file at all). Accepted. The
   comment at `learning.ML:113-121` must be rewritten: its stated reason
   ("excluded from semantic collection, so the experience is not retrievable")
   stops being true once decision 6 lands; the durable reason is that these are
   machinery proofs and an experience learned from them is worthless regardless
   of retrievability.
5. **`preserved_set` must stop overriding the theory marking — but measure
   first.** `infra_filter.ML:351` places `is_from_infra_theory` inside
   `not (Strhashtab.defined preserved_set name) andalso (…)`, while the explicit
   `decl_consts` sits outside it at `:350` with a comment saying explicit
   declaration takes precedence. `preserved_set` (`:175-215`) is computed over
   **all visible types** (`:154`, `Name_Space.get_names type_space`), so a marked
   theory's datatype constructors escape the marking and do not cascade. Store
   evidence: 1,451 records mention `floatarith` (419 `Straight_Line_Program`,
   413 `Floatarith_Expression`, 143 `Init_ODE_Solver`, 137 `Taylor_Models`, …)
   against 52 mentioning `interpret_floatarith`. The fix is to hoist
   `is_from_infra_theory` beside `decl_consts`, making "explicit judgements beat
   heuristics, heuristics never beat explicit judgements" true by shape. **This
   widens the cascade**, so it is gated on the measurement in decision 8.
6. **"Marked infrastructure" stops meaning "never interpreted".**
   `is_excluded_theory` (`semantic_store.ML:1867-1869`) loses its
   `is_infra_session` disjunct and keeps only `base_theory_ids`
   (`Code_Generator`, `Pure`, `Code_Evaluation`). Rationale: the theory marking
   is consulted for only 5 of the 7 entity kinds. **Method** and
   **Theorem_Collection** have their own rules (`is_infra_method` at `:470-476`
   keys on Main-ancestry; theorem collections use their own prefix list
   `["Transfer.", "Lifting.", "SMT.", "Pure."]` at `:499`), so they pass the
   filter and are lost only because the theory never enters the cone. That is 10
   proof methods (`approximation` — 87 AFP call sites — plus `ring`, `field`,
   `cooper`, `mir`, `rferrack`, `frpar`, `frpar2`, `dlo`, `ferrack`) and 1
   `named_theorems` (`approximation_preproc`, `Approximation.thy:1053`) = 11
   records. `lemmas` aliasing cannot recover a method. Note there is no
   Attribute entity kind (the seven are Class, Constant, Locale, Method,
   Theorem, Theorem_Collection, Type), so `attribute_setup meta`
   (`Conversions.thy:22`) is not part of the payoff. **Sequenced after decision
   5**, or the escaping constructors get interpreted as noise.
7. **`MIR.thy` is discarded entirely.** Both groups of its salvageable content
   are given up, and the type-based marking proposal that existed only to rescue
   them is dropped. For the record, so the choice can be revisited: 9 lemmas
   whose statements mention `MIR.rdvd` (`:37, :53, :57, :75, :78, :81, :1112,
   :1115, :3798`) plus the `rdvd` definition (`:34`, divisibility lifted to the
   reals, zero users outside `MIR.thy` in the whole distribution and AFP) —
   these are structurally unrescuable by aliasing, because the alias keeps the
   statement and the statement mentions an infrastructure constant, so the
   cascade at `:444` kills it; and 12 lemmas that mention no `MIR` constant and
   therefore *could* be aliased (8 floor case-splits at `:1658-1720`,
   `real_in_int_intervals` `:3498`, `small_le` `:3788`, `small_lt` `:3793`,
   `real_ex_int_real01` `:4786`). Re-running interpretation does **not** recover
   either group: they are filtered, not merely uncollected.
8. **Measurement comes first.** Instrument `is_infra_thm` (`:432-446`) — and
   `is_infra_const'` (`:344-372`), which the original proposal omitted — to
   report *which disjunct fired*, then fold `gen_infra_filters` over
   `Global_Theory.facts_of` for the AFP-ALL image and bucket rejections by
   reason. No LLM, no build. It sizes decision 5, and it settles whether the 12
   lost `EC_Common` lemmas died to the session marking or to §8.1's
   `has_class_variant` defect (they may have two independent causes). Then run
   `dry_run'` (`semantic_store.ML:1862`) on the affected theories for the real
   entity counts — every budget figure in this document is a `grep` of top-level
   commands, and `Polynomial_List` has 106 of 113 lemmas in a class target, so
   its true count is probably higher.
9. **`Polynomial_List` stays a keep** (leaning; may be revisited on the
   `dry_run'` numbers). The reviewer's case for reversing it was that its 16
   base names collide with `HOL-Computational_Algebra.Polynomial` — `degree`,
   `order`, `order_decomp`, `order_degree`, `order_divides`, `order_mult`,
   `order_root`, `order_unique_lemma`, `poly`, `poly_0`, `poly_add`,
   `poly_minus`, `poly_mult`, `poly_roots_finite`, `poly_zero`, `rsquarefree` —
   so an agent could cite the wrong one. **That risk is handled at display
   time**: AoA renders the name of every search result through
   `Name_Space.extern` / `Facts.extern` against the live proof context
   (`agent_server.ML:932, :964-966, :980-985`), and `names_unique` defaults to
   `true` (`contrib/Isabelle2025-2/etc/options:84`, unoverridden here), so an
   ambiguous short name comes out qualified. Real instance:
   `tools/aoa_putnam_eval/state/logs/ee54724c2_2/interaction.yaml:129` renders
   `Rat.Rats_sum`, because `Rats_sum` is declared both at `HOL/Rat.thy:881` and
   `Bernoulli/Bernoulli.thy:42`. What remains is LLM budget and retrieval noise,
   against the benefit that keeping it **stops** a cascade that is firing today
   into `Polynomial_Expression.thy` (834 store records survive there now).
10. **Production-code editing is unblocked** as of 2026-08-20; the earlier
    "migration code only" restriction is lifted.

### Rejected in review, with the reason (do not re-propose)

- **Driving the `Dense_Linear_Order` filter from the authors' `[no_atp]` tags.**
  `Infra_Decl` matches by **proposition** (`Thm.eq_thm_prop`, `:51`, `:141-144`),
  and that theory's `[no_atp]` declarations are `lemmas` bundles of *other*
  theories' theorems — `:279` `lemmas dlo_simps[no_atp] = order_refl less_irrefl
  not_less not_le exists_neq`, and likewise `:296`, `:298`, `:311` covering
  `conj_disj_distribL/R`, `simp_thms`, `nnf_simps`, `ex_distrib`. Seeding the
  net from them would delete `order_refl`, `not_less`, `not_le` and `simp_thms`
  from the entire store. The file's own warning at `:114-116` says proposition
  matching "also suppresses every same-statement lemma from retrieval".
- **"`Dense_Linear_Order` declares zero HOL constants, so its cascade is
  provably empty."** It declares four locales (`:323, :334, :364, :394`), and a
  locale with assumptions creates a predicate constant — the same phenomenon as
  `Abs_Int1.Abs_Int` in plan §8.2.
- **`Decision_Procs` being a collision-prone name.** No second `Decision_Procs.thy`
  exists in either distribution pair, and under long names collision-proneness is
  nil.
- **The `infra_const_cache` keying defect** (`:343-345` memoises on `name` while
  the function takes `(name, typ_opt)`; call sites disagree, `:373` `NONE` versus
  `:430` `SOME T`). All three reviewers failed to construct a reachable
  divergence. Recorded, not acted on — but it becomes live if a type-based rule
  is ever added.

### Corrections to this document made in review

- `Dense_Linear_Order`'s keep set is **14 lemmas**, not the 3 an earlier revision
  named. `finite_set_intervals` (`:149`) and `finite_set_intervals2` (`:198`) are
  themselves `[no_atp]`, and `tasks/MathBench_Prover/MathBench_Prover.thy:193-203`
  records a 2026-06-17 audit that explicitly rejected them as
  quantifier-elimination machinery. The correct set is `interval_empty_iff`
  (`:219`) plus the thirteen sign-of-product linear-inequality lemmas at
  `:555-625`. None mentions a constant of that theory, so all 14 are aliasable.
- `Approximation_Bounds`' novel loss is **11**, not 13: `cos_periodic_nat` and
  `cos_periodic_int` are both verbatim in
  `Complex_Geometry/More_Transcendental.thy:150, :155`. Ten of the eleven are
  already aliased at `MathBench_Prover.thy:204-213`, leaving `horner_schema'`
  (`:31`), `sqrt_ub_pos_pos_1` (`:415`) and `mono_exp_real` (`:3000`).
- A per-theorem keep-list **does** exist — `lemmas` aliasing into a non-marked
  theory, as at `MathBench_Prover.thy:204-216`. An earlier revision said none
  existed, and decision 7's "accept the losses" was originally taken on that
  false premise. **But `MathBench_Prover` has zero records in the store** (full
  scan of 1,355,222 entries), so none of the 13 aliases has ever been
  collected; the remedy exists on disk and has never been cashed in.
- "Each theory is all-or-nothing" is false — see decision 5.
- The examples `MIR.eq` and `Parametric_Ferrante_Rackoff.Add` do not exist in
  that form; they are constructors `MIR.fm.Eq` and
  `Parametric_Ferrante_Rackoff.tm.Add`, which is exactly what puts them in
  `preserved_set`.
- The `defs` column counts ML `fun`s for `Conversions` (57) and
  `Dense_Linear_Order` (13); both theories declare zero HOL constants.
- `Rat_Pair.of_int_div_aux` duplicates `Real.thy:999`, not
  `Euclidean_Rings.thy:1714` (only `of_int_div` duplicates that).
- A third `Approximation_Bounds` consumer was not checked in the "costs nothing"
  survey: `Chebyshev_Prime_Bounds/Chebyshev_Prime_Exhaust.thy` mentions
  `lb_ln`/`ub_ln` in `[code]` equation statements.

## Order of work

1. Instrument and measure (decision 8).
2. Hoist the theory marking out of the `preserved_set` guard (decision 5), if
   the measurement supports it.
3. Re-key to theory long names and enumerate the 19 (decisions 1-3); rewrite
   `is_excluded_theory` and the `learning.ML` comment (decisions 4, 6).
4. `dry_run'` for the real entity counts; settle `Polynomial_List` (decision 9).
5. Collect `MathBench_Prover` — 13 aliases already written, zero records — and
   consider adding the 14 `Dense_Linear_Order` aliases.
6. Fix the test that inlines its own copy of the session list and will keep
   passing after the concept is deleted:
   `contrib/Isa-Mini/Test/Test_Infra_Session_Prefixes.thy:6-14`.

Interpreting the theories moved to `keep` is a separate, budgeted run.
