# Reworking the infrastructure filter

Started 2026-08-19; integrated 2026-08-23. Supersedes `THEORY_HASH_REKEY_PLAN.md`
§8, which is now a pointer here. Companion:
`DECISION_PROCS_INFRA_THEORY_LIST.md` holds the theory-by-theory classification
and its evidence.

This document was assembled from two sessions that unknowingly worked the same
problem in parallel, plus six reviewers across them. An earlier revision carried
its review findings in an appendix that declared itself to outrank the body;
that appendix is now folded in and the body is the only authority. The
pre-integration text is preserved at
`scratchpad/INFRA_FILTER_REWORK_PLAN.pre-integration.md` for one session only.

`infra_filter.ML` decides which Isabelle entities are **infrastructure** —
machinery that exists only to make a package or a decision procedure work, which
no proof agent would cite. Infrastructure entities get no record in the semantic
database, and any theorem whose statement mentions an infrastructure constant is
dropped with them.

The trigger: the whole Isabelle session `HOL-Decision_Procs` was marked
infrastructure. `Algebra_Aux.thy` sits in that directory while being ordinary
ring algebra, so downstream AFP entries lost real lemmas — measured, of
`EC_Common`'s 15 `field` lemmas the filter rejects 12 and the store holds exactly
the other 3.

## 1. What "marked as infrastructure" does today

Three effects. Only the first two were intended.

1. **The theory's own entities get no record.** `is_from_infra_theory`
   (`infra_filter.ML:319-320`) is consulted at exactly five places: `:355`
   constants, `:441` fact names, `:538` types, `:541` classes, `:544` locales.
2. **The cascade.** `is_infra_thm` drops any theorem whose statement mentions an
   infrastructure constant (`:444`, `Term.exists_Const is_internal_constant`).
   This is intended and documented at `:52-53`, and it is right when the constant
   is genuine machinery. An earlier revision proposed separating the entity
   judgement from the theorem judgement; that would have broken a correct design
   and is withdrawn.
3. **The theory is never interpreted at all.** `is_excluded_theory`
   (`semantic_store.ML:1867`) calls `is_infra_session`; its own comment reads
   "Theories that are never interpreted". So `Algebra_Aux` has no records because
   it was never interpreted, not because a filter rejected it. Confirmed by store
   scan: `Algebra_Aux`, `Polynomial_List` and `DP_Library` have **0 records**.

**Which entity kinds effect 1 reaches.** `Universal_Key.ML:31-35` defines
**eleven** entity tags: `0x01`–`0x07` plus `0x12`/`0x22`/`0x32`/`0x42` for
Introduction/Elimination/Induction/Case_Split rules. The four rule kinds **are**
gated — they route through `is_infra_thm` at `:441`. Two kinds escape the
marking:

- **Method** — `is_infra_method` (`:470-476`) drops a method when its declaring
  theory is `Main` or a `Main` ancestor, **or** when it is concealed, hidden,
  `"??."`-shadowed, or has no name-space entry (`:473`, `| NONE => true`). A
  `HOL-Decision_Procs` method meets none of these.
- **Theorem_Collection** — its own prefix list (`:499`,
  `["Transfer.", "Lifting.", "SMT.", "Pure."]`), with a comment at `:496-498`
  saying so explicitly.

There is no Attribute kind, so `attribute_setup` produces nothing either way.

**Consequence**: the 10 `method_setup` declarations of `HOL-Decision_Procs` and
its one `named_theorems` all pass the filter and are lost **only to effect 3**.
`approximation` (`Approximation.thy:1110`) is invoked on 87 AFP lines; `ring`
(`Commutative_Ring.thy:957`) and `field` (`Reflective_Field.thy:923`) likewise.
Method records do exist in the store (832 of them), so the storage path works —
the source is simply switched off.

## 2. Decisions

| # | Decision | Date |
| --- | --- | --- |
| D1 | The classification stands: ~~**3 theories kept, 17 marked**~~ **5 kept, 15 marked** — the 08-24 constant-verdict audit moved `Approximation` (`interpret_floatarith`/`approx` ecosystem, cited by 20 AFP files) and `Rat_Pair` (`INum`, used by Taylor_Models) to kept; `Reflected_Multivariate_Polynomial` stays marked (zero external citers). See `DECISION_PROCS_INFRA_THEORY_LIST.md`. | 08-19, revised 08-20 and 08-24 |
| D2 | Retire the session concept. `infra_session_names` emptied, `is_infra_session` deleted. | 08-19 |
| D3 | Key the marker on theory **long** names, not base names. One `Symtab.set`, three consumers. | 08-20 |
| D4 | Populate that set by **enumeration**, not by "session default plus exceptions". | 08-20 |
| D5 | `learning.ML:123` keeps calling `Infra_Filter.is_infra_theory`; `Algebra_Aux` entering AoA-learning scope is accepted. | 08-20 |
| D6 | Hoist the theory marking out of the `preserved_set` guard — **after** step 1's measurement. **REVOKED 08-24**: the ordering is semantically correct as it stands; see the ruling block under "Why the marking must beat `preserved_set`". Steps 3 and 3½ are void. | 08-20, revoked 08-24 |
| D7 | Unfuse effect 3: `is_excluded_theory` keeps only the three base theories. | 08-20 |
| D8 | `MIR.thy` is discarded whole. Its 21 items of ordinary mathematics are accepted as lost. | 08-20 |
| D9 | `Polynomial_List` stays kept and gets interpreted. | 08-20 |
| D10 | LLM budget is not a gate. Measure for sizing, not for permission. | 08-20 |
| D11 | The Python-side theory skip list moves behind an RPC callback. | 08-20 |
| D12 | `Approximation_Bounds` is **not** marked. Its header (`:5-9`) says the authors split the file deliberately — the bound material is "morally immaculate", the oracle lives in `Approximation.thy`. Marking it was the `Algebra_Aux` failure in a new place. Also stops a cascade into `Chebyshev_Prime_Bounds/Chebyshev_Prime_Exhaust.thy`, which names `lb_ln`/`ub_ln` in `[code]` equation statements. | 08-20 |
| D13 | Save all 14 `Dense_Linear_Order` keep-worthy lemmas by aliasing. Select them **offline** by the authors' `[no_atp]` complement — read the bracket in the source. **Never a runtime mechanism**; see §4. | 08-20 |
| D14 | Every name-string guess in the rule chain is retired **only** where an authoritative Isabelle query replaces it with no coverage loss. Where no such query exists, the guess stays. One rule at a time, each with evidence. See §3. | 08-23 |
| D15 | **The tool-support marking list (08-25)**: 23 theories join the marking set, from the KEPT-side audit's ~558 unmarked tool constants, each vetted for AFP statement-level citations by a dedicated research pass — `HOL.Quickcheck_Exhaustive`, `HOL.Quickcheck_Narrowing`, `HOL.Quickcheck_Random`, `HOL.Random_Pred`, `HOL.Random_Sequence`, `HOL.Lazy_Sequence`, `HOL.Limited_Sequence`, `HOL.Nitpick`, `HOL.Nunchaku`, `HOL.SMT`, `HOL.Meson`, `HOL.Metis`, `HOL.Record` (iso_tuple layer; user record fields are whitelisted separately), `HOL.Typerep`, `HOL.Extraction`, `HOL-Library.Code_Test`, `HOL-Library.Code_Lazy`, `HOL-Library.Code_Target_Nat`, `HOL-Library.Code_Target_Int`, `HOL-Library.Code_Cardinality`, `Tools.Code_Generator`, `HOL-Real_Asymp.Multiseries_Expansion`, `HOL-Real_Asymp.Lazy_Eval`. **Withheld under the zero-casualty bar**: `HOL.Random` (JinjaThreads' random scheduler and Containers' benchmark generators would lose hand-written defining equations) and `HOL.Predicate_Compile` (three entries' hand-written `code_pred_intro` rules). **Never mark `HOL.Code_Numeral`**: `nat_of_integer`/`int_of_integer` appear in statements across ~100 AFP entries (92 files cite `nat_of_integer` alone, spot-verified) — the `Algebra_Aux` failure at 10x scale. Evidence table and known plumbing casualties: `TOOL_THEORY_MARKING_LIST.md`; the post-step-2 re-run is the final check (textual grep cannot see mentions that appear only after unfolding). | 08-25 |
| D16 | **Store reconciliation with the reworked filter (08-25)**: the store and the new filter disagree in both directions — entities the old filter wrongly rejected have no records (`EC_Common`'s 44, the `Abs_fps` 239, the `class.linorder` relativization lemmas, …), and records exist for entities the new filter now rejects (`_sumC`, instance plumbing, D15's 23 theories' constants). Ruling: **backfill later, never purge.** Legacy records the new filter would reject stay as visible noise (the step-3½ question, returned in a new guise, answered "accept"). Backfill is a later activity: when scheduled, an offline re-filter pass over the store (pure ML, no LLM, no build) buckets newly-accepted entities by declaring theory into a sized worklist; collection then covers those theories. Not part of steps 1-6. | 08-25 |

### Why long names (D3), with the number

`infra_base_theory_names` (`:38`) matches by theory **base name**, and a base
name is not an identity. Two of the marked names are already taken elsewhere in
the AFP: `LinearQuantifierElim/Thys/Cooper.thy` and
`Correctness_Algebras/Approximation.thy` (Walter Guttmann's approximation in
correctness algebras — ordinary mathematics, unrelated to floating point).
Measured against the live store: adding those two base names destroys **216 + 43
= 259 existing records**; the other **15** destroy none.

Today's code does not have this bug, because the session half of the marker is
ancestry-gated (`:306-310`, `Theory.ancestors_of thy`) and neither AFP entry has
a `HOL-Decision_Procs` ancestor. **The bug would have been introduced by the
"obvious" fix.**

Isabelle resolves an entity name to its declaring theory's long name —
`Name_Space.theory_name {long: bool}` (`Pure/General/name_space.ML:24, :263`) —
and this file already does it **once**, at `:471-472` (`is_infra_method`,
against a `Symtab.set` of theory long names). (`:258` and `:267` call
`Name_Space.the_entry` to read `#pos`, never a theory name;
`Name_Space.theory_name` appears nowhere in the file.) The shape:

```sml
val infra_theory_long_names = Symtab.make_set ["Minilang.Minilang", ...]

fun is_infra_theory thy =
  Symtab.defined infra_theory_long_names (Context.theory_long_name thy)

fun is_from_infra_space space name =
  (case try (Name_Space.theory_name {long = true} space) name of
     SOME t => Symtab.defined infra_theory_long_names t
   | NONE => false)
```

Each call site passes its own name space. `infra_theory_prefixes` and
`is_from_infra_theory` (`:315-320`) are deleted.

This also fixes a class of case the prefix test gets wrong. Measured in a live
`HOL` image over `Complex_Main`: 8 of 3568 constants and 24 of 29985 facts have a
first name segment that is not their declaring theory (all `instantiation`-
generated, e.g. `Set.typerep_set_inst.typerep_set` declared in `HOL.List`), and
45 of 168 types carry no qualifier at all (Pure syntax types). The lookup is
right on all of them; the prefix test is wrong on all of them.

#### Two traps in this refactor, both of which would ship silently

**`infra_theory_prefixes` (`:315-318`) has THREE components**, not two:

```sml
["Code_Evaluation."] @ map (fn n => n ^ ".") infra_base_theory_names
                     @ infra_session_thy_prefixes
```

Replacing only the last two **drops the `Code_Evaluation` gate**. Constants stay
covered by `internal_prefixes` (`:313`), but facts (`:441`), types (`:538`),
classes (`:541`) and locales (`:544`) lose it — and that gate runs on live
inherited names (`agent_server.ML:1323` folds `Proof_Context.facts_of`).
**The enumerated set must contain `"HOL.Code_Evaluation"`.** (Approved
2026-08-20.)

**Do not fold `internal_prefixes` (`:312-313`) into the long-name set.** It
contains `"HOL.equal"`, a *constant*-name prefix, which as a theory long name
would read `HOL.HOL` and classify all of `HOL.thy` as infrastructure. Only the
`infra_session_thy_prefixes` tail leaves it — that tail is spliced into both
`:313` and `:318` and therefore tested twice at `:355`/`:356`.

So the set is: `Minilang.Minilang` + `HOL.Code_Evaluation` + the 23 tool-support theories (D15) + the 15 marked
theories of `HOL-Decision_Procs` = **19 entries**.

### Why enumeration (D4)

Both forms are safe once keyed on long names, so the choice is about how the list
rots. A session default classifies a future additional theory as infrastructure
by default: if it is ordinary mathematics it **vanishes silently**, which is
exactly the `Algebra_Aux` failure. Enumeration classifies it as ordinary
mathematics by default: if it is machinery, noise **appears in the store**, which
is visible and repairable. Deletion is invisible; noise is not.

Measured churn in that directory between Isabelle2024 and Isabelle2025-2: the
`.thy` **file set is unchanged** — nothing added, nothing removed — though **10
`.thy` files differ in content** (MIR, Algebra_Aux, Approximation,
Approximation_Bounds, Commutative_Ring, Conversions, Cooper, Dense_Linear_Order,
Ferrack, Reflected_Multivariate_Polynomial) plus 6 `.ML`. The argument stands on
the file set: the maintenance a session default would save is maintenance on a
scenario that has not occurred.

### Why the marking must beat `preserved_set` (D6 — REVOKED 08-24, ruling below)

`is_infra_const'` has three tiers (`:348-370`):

```sml
  Symtab.defined decl_consts name                         (* explicit declaration *)
  orelse (not (Strhashtab.defined preserved_set name)     (* veto *)
          andalso ( ...twelve rules... ))
```

`preserved_set` (`:175-215`) holds the datatype constructors, selectors, `case`
combinators, BNF map/pred/rel/sets and record fields of **every visible type**
(`:154`, `Name_Space.get_names type_space` — inherited types included). It exists
to stop the *heuristic* rules below it from deleting legitimate generated
entities. The comment at `:349` shows the author already knew ordering matters:
"explicit declaration takes precedence over `preserved_set`".

The theory marking is an explicit judgement, not a heuristic, but it sits in the
third tier, under the veto. So a marked theory's constructors escape the marking
and do not cascade: asking about `MIR.Ifm` yields infrastructure, asking about
`MIR.fm.Eq` does not.

Measured: **1,451 store records mention `floatarith`** — 419 from
`Straight_Line_Program`, 413 from `Floatarith_Expression`, 143 from
`Init_ODE_Solver`, 137 from `Taylor_Models`, 57 from
`Abstract_Reachability_Analysis`, the rest spread over further declaring
locations across 6 AFP sessions — against **52 mentioning
`interpret_floatarith`**. Records named
`Straight_Line_Program.slp_of_fa.simps(N)` are the N-th recursion equation of a
function defined by cases on `floatarith`, so by construction their statements
name a constructor. They exist today because of this veto.

The fix is two lines — move `is_from_infra_theory` up beside `decl_consts` — and
it makes the tiering read as an invariant: explicit judgements beat the veto,
heuristics never do. **It also widens the cascade**, which is why it waits for
step 1's measurement, and why step 3½ exists.

> **REVOKED (owner ruling, 2026-08-24).** The argument above mistakes two
> different judgements for one. Declaring a single constant infrastructure and
> marking a theory are not the same judgement at different granularity: the
> marking says "what this theory *declares* is machinery", while the
> mentioned-constant cascade in `is_infra_thm` amplifies any constant-level
> judgement into "any theorem *anywhere* that touches this name is machinery".
> For genuinely internal names that amplification is sound — nothing legitimate
> touches them. For a datatype's constructors it is not: they are the type's
> public interface, and downstream libraries legitimately build on them. The
> 1,451 `floatarith`-mentioning records are not collateral noise but exactly
> the content retrieval exists for — `Straight_Line_Program.slp_of_fa.simps(N)`
> is a defining equation of a function in an AFP verified-numerics development.
> So the current ordering is not an accident violating a tier invariant; it is
> the correct boundary: **the marking's kill zone stops at the public interface
> of the types it declares.** A middle form — hoist the direct judgement but
> exempt the cascade — was considered and rejected as incoherent: the store
> would keep `slp_of_fa.simps(3)`, whose statement names the constructor
> `Add`, while refusing to answer a query for `Add` itself.
>
> Consequences: steps 3 and 3½ are void (step 1 loses its gating role but
> keeps every other purpose); the asymmetry becomes deliberate (the type name
> `MIR.Ifm` is judged infrastructure, its constructor `MIR.fm.Eq` is not); the
> ordering is documented as load-bearing by a comment at the `preserved_set`
> veto in `infra_filter.ML`.

### Why unfusing is safe and what it buys (D7)

`enumerate_entries` applies every filter *before* building the payload (`:1445`
constants, `:1452` theorems, `:1547` methods), so interpreting a marked theory
costs only the survivors. `MIR.thy`'s 213 reflection lemmas never enter the
payload. What does enter is the two kinds the marking does not gate: **10 proof
methods and 1 `named_theorems`**. `lemmas` aliasing cannot recover a method, so
this is the only route to them.

`is_excluded_theory` has to be rewritten regardless — it keys off
`is_infra_session`, which D2 retires, and it is what keeps the three kept
theories out today. **See step 2 for the ordering trap this creates.**

### What was decided about the direct losses (D8, D9)

**`MIR.thy`** — discarded whole. Its 21 items of ordinary mathematics split in
two:

- **9 lemmas plus the definition of `rdvd`** (`:34`, divisibility lifted to the
  reals; lemmas at `:37, :53, :57, :75, :78, :81, :1112, :1115, :3798`). Their
  statements mention `MIR.rdvd`, which the theory marking makes an infrastructure
  constant, so the `:444` cascade kills a `lemmas` alias as surely as the
  original. `[[infra_constant MIR.rdvd del]]` does not help: `del` only removes a
  name from `decl_consts` (`:93-97`), leaving the theory-marking disjunct to fire.
- **12 lemmas that name no `MIR` constant** — the 8 floor case-split lemmas at
  `:1658-1720`, `real_in_int_intervals` (`:3498`), `small_le` (`:3788`),
  `small_lt` (`:3793`), `real_ex_int_real01` (`:4786`). These *could* be aliased.

**The reason for discarding is not that no rescue exists** — three do: restate
the 9 `rdvd` lemmas with `rdvd_def` unfolded so their statements name no `MIR`
constant; re-define `rdvd'` in a kept theory; or add a keep declaration to
`Infra_Decl`, which already has the shape. **The reason is that `rdvd` has zero
users outside `MIR.thy` in the whole distribution and the whole AFP**, so its
retrieval value is speculative. The user ruled "完全丢弃 MIR" on 08-20, having
been offered the rescue of the 12 aliasable ones and declining it.

**`Polynomial_List`** — kept. The objection was that it collides with
`HOL-Computational_Algebra.Polynomial` on 16 base names, eight of which are the
theorems cited as the reason to keep it. That objection is answered at two
layers, and the second is the load-bearing one:

- A result line's **name and statement are re-rendered against the live query
  context** (`agent_server.ML:900-903`, `:932`, `:942`, `:964-967`); only the
  English explanation is the stored string. `Name_Space.extern` refuses an
  ambiguous short access path when `names_unique` is set, and that option
  defaults to `true` (`Isabelle2025-2/etc/options:84`) with no override anywhere
  in this repo. Observed in a real run:
  `tools/aoa_putnam_eval/state/logs/ee54724c2_2/interaction.yaml:129` renders
  `Rat.Rats_sum`, qualified, because `Bernoulli.thy:42` also declares
  `Rats_sum`.
- **But display-time qualification does not reach ranking.** Ranking scores
  stored embeddings of stored English, and `extern` runs after. What actually
  saves D9 is that the candidate pool is a **live enumeration** of what is in
  scope (`semantics.py:2150-2161`, `entities_of`), not the store — so the two
  `order_root`s only ever compete in a session importing both.
- **Residual, stated rather than hidden**: in such a session — anything importing
  `Taylor_Models/Polynomial_Expression.thy`, which imports `Polynomial_List` at
  `:11` — both entities enter the pool with near-identical stored English and
  both can rank. Qualification stops mis-citation, not the duplicate occupying a
  result slot.

Keeping it also **stops a cascade that is running today**: `Polynomial_List` is
covered by the session marking, so statements in
`Taylor_Models/Polynomial_Expression.thy` that name `Polynomial_List.degree`
(`:2067`) are being dropped. That file has 834 surviving records.

## 3. The twelve-rule chain: every rule accounted for (D14)

All measurements below were run on **Isabelle2025-2** via
`contrib/Isabelle2025-2/bin/isabelle console -l SESSION -n`, no build.

| # | rule | disposition |
| --- | --- | --- |
| 1 | `concealed` | untouched — `Name_Space.is_concealed` is already authoritative |
| 2 | `hidden` | untouched — `Long_Name.is_hidden (Name_Space.intern …)` |
| 3 | `infra_theory` | → theory **long** names (D3/D4), including `"HOL.Code_Evaluation"` |
| 4 | `internal_prefix` | split: theory prefixes join the long-name set; **`"HOL.equal"` stays a name test** |
| 5 | `pre_bnf_prefix` | untouched — derived from `BNF_FP_Def_Sugar.fp_sugar_of` |
| 6 | `inst_infix` | **KEPT** (08-23). No authoritative query exists for "generated by an `instantiation` block" |
| 7 | `class_variant` | → `Sign.all_classes` + `Class.class_prefix` (approved 08-19) |
| 8 | `quotient_typedef` | untouched — `Quotient_Info` + `Typedef.get_info_global` |
| 9 | `abs_rep_name` | ~~→ `Typedef.get_info_global` over **all** types, dropping the quotient gate (approved 08-19)~~ **Superseded 08-25 (owner ruling): DELETE the rule.** Probe (12 representative types): the old Quotient registry separates "Abs_ is internal" types (`int`/`rat`/`real`/`word`/`fract`, all registered) from "Abs_ is the de-facto constructor" types (`fps`/`poly_mapping`/`fset`/`poly`/`multiset`/`filter`/`float`, none registered) with zero exceptions — and rule 8 already rejects exactly the registered types' morphisms authoritatively. Rule 9's net contribution was the misfires: `Abs_fps` (24 AFP files, 239 cascade kills) and ~8 siblings. Deletion also kills the `Abs_Int` homonym problem the 08-19 replacement was designed for, with zero new code. The ~70 remaining unregistered morphisms become visible noise (D4). |
| 10 | `adt_record` | untouched — `Ctr_Sugar`/`Record` info plus a position check. **08-25 (owner ruling)**: the rule stays; `preserved_set`'s enumeration gains the DISCRIMINATORS (from `Ctr_Sugar`) — the 08-24 audit's misfire 4 (`sum.isl` 33 AFP entries + 20 cascade kills, `llist.lnull` 47 entries + 225 cascade kills). **Ruled 08-25: the size-plugin family joins the whitelist as a whole family** (`size_list` 78 entries/15 cascade kills must live; the 24 barely-cited siblings enter as visible noise per D4 — per-name keep-lists are rejected, so it was all-or-none). |
| 11 | `class_infix` | ~~→ `Locale.specification_of` + `Locale.intros_of`, **with** `Class.is_class` (approved 08-23)~~ **Superseded 08-25 (owner ruling)**: the rule becomes the plain name test — reject iff the name contains `.class.` AND its base name ends `_axioms`. Base predicates (`class.X`, human-cited — the 08-24 audit's misfire 1) survive; only the 134 `_axioms` companions stay rejected; the record-collision names survive without leaning on the `preserved_set` veto order. Corner cases dismissed as far-fetched by ruling: a record named `class` with a field ending `_axioms`, and a class literally named `*_axioms`. Zero init cost — no enumeration, no table. |
| 12 | `class_pred` | → `Logic.const_of_class` over `Sign.all_classes`, **without** `Class.is_class` (approved 08-23) |

### Rule 7 — `class_variant`

`:322-337`, consumed at `:359`, infers "L is a type class" from the string
`_class`. Wrong: `Algebra_Aux.thy:286` writes `interpretation cring_class: cring
…` with a human-chosen prefix, so `Elliptic_Locale.cring_class.pdouble` exists
and the rule deletes the general locale constant, taking all 20
`Elliptic_Locale.cring.*` facts. Ask `Class.is_class` and derive the prefix with
`Class.class_prefix` (`Pure/Isar/class.ML:353`, used by
`class_declaration.ML:75, :295`).

**This does not bring the type-class templates back.** Excluding the
locale-level twin of a genuine class is the rule's intended behaviour; only ~500
of the 55,679 dangling `template_uk` references are misfire victims.

### Rule 9 — `abs_rep_name`

`:361-362` classifies a constant as infrastructure when its base name starts with
`Abs_` or `Rep_`. `Abs_` is a homonym: in `HOL/IMP/Abs_Int1.thy` it abbreviates
**Abstract Interpretation**. Measured: the locale predicate `Abs_Int1.Abs_Int`
is classified infrastructure and 7 of that locale's 9 facts die with it.
`locale Abs_Int` (`Abs_Int1.thy:35`) is the centrepiece of Nipkow's *Concrete
Semantics* chapter on abstract interpretation — parameterised by a concretisation
`γ :: 'av ⇒ val set`, defining `step'` and `AI c = pfp (step' ⊤) (bot c)`,
proving `AI_correct : AI c = Some C ⟹ CS c ≤ γ⇩c C`, instantiated ten times by
`global_interpretation` across `Abs_Int1_const/parity`, `Abs_Int2_ivl`,
`Abs_Int3`. Its derived locales `Abs_Int_mono` and `Abs_Int_measure` are hit for
the same reason.

Locale predicate constants are to be kept: `:542` already treats every visible
locale as not infrastructure, and the file has an explicit rule for **class**
predicates (rule 12) and none for locale predicates. Three of the six locale
predicates in that one theory are dropped and three kept, decided by the first
four letters of the name.

**The fix is not a two-line deletion.** `:287` already calls
`Typedef.get_info_global`, but inside `quotient_typedef_infra` (`:278-291`),
which is gated on `Quotient_Info.lookup_quotients_global` returning `SOME` — so
it covers only *quotient* types. The replacement must **drop that gate** and ask
`Typedef.get_info_global` for every type in `type_names`, so plain typedefs are
covered too. Cost: one query per visible type at filter-construction time (367
types in `MathBench_ProverBase`), the same shape as the existing fold.

### Rule 12 — `class_pred`, measured

Today: `String.isSuffix "_class" (Long_Name.base_name name)` **and**
`returns_prop`. Replacement: `map Logic.const_of_class (Sign.all_classes thy)`.

| | `HOL`/`Complex_Main` (3568 consts) | `MathBench_ProverBase` (12519 consts) |
| --- | ---: | ---: |
| A (string rule) | 242 | 312 |
| B (enumeration) | **242** | **312** |
| A \ B, B \ A | **0, 0** | **0, 0** |
| phantoms (B not declared) | 0 | 0 |

**Do not add `Class.is_class`**: it drops exactly one name, `HOL.type_class`, in
both sessions — a genuine class predicate created by
`Axclass.class_axiomatization` (`HOL.thy:76`), which declares the constant but
registers no `Class` data. That would be a coverage loss.

Stronger than the measurement: **`B ⊆ A` holds by construction.**
`Logic.const_of_class = suffix class_suffix` (`logic.ML:306`) and `mk_of_class`
(`:315`) builds `Const (const_of_class c, itselfT ty --> propT)`, so every class
predicate's base name ends in `_class` and its type returns `prop`. The only
possible discrepancy is A ⊋ B — the string rule over-matching — which after the
change means *keeping* a constant, i.e. fail-closed.

**The replacement is also the better shape.** `returns_prop` is load-bearing
today: `Sigma_Algebra.subset_class :: 'a set ⇒ 'a set set ⇒ bool`
(`HOL/Analysis/Sigma_Algebra.thy:33`) is the predicate of `locale subset_class`
— `Locale.check` succeeds, `Sign.certify_class "Sigma_Algebra.subset"` fails —
and only the `returns_prop` conjunct keeps it out. The enumeration cannot produce
a locale predicate at all, so it retires **two** string tests and needs no guard.

### Rule 11 — `class_infix`, measured

> **Superseded 08-25** — see the disposition table above: the enumeration
> below stays as evidence, but the shipped fix is the plain name test
> (`.class.` infix + `_axioms` base-name suffix → reject; everything else
> untouched). The measurements below (coverage A = B in three contexts, 3 ms
> init) were what established that the two forms agree on all real data.

`.class.` names come from `class_declaration.ML:335`
(`Binding.qualify true "class" b`) plus `expression.ML:690` (`Sign.full_name`),
with the `_axioms` companion from `:751`. Plain `locale foo` uses
`add_locale b b`, so ordinary locale predicates carry no `class` segment. Their
result type is `bool` and their base name is the class name, so neither sibling
rule reaches them — `class_infix` is the only rule that can.

| session | theories | A | B | A \ B | B \ A | phantoms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `HOL`/`Main` | 119 | 231 | **231** | **0** | 0 | 0 |
| `MathBench_ProverBase` | 703 | 397 | **397** | **0** | 0 | 0 |
| `HOL-NanoJava.Decl` | 121 | 251 | 231 | **20** | 0 | 0 |
| `HOL-Bali.Decl` | 126 | 249 | 231 | **18** | 0 | 0 |

**`intros_of` is required**: `specification_of` alone covered only 151 of 222 in
an earlier probe — it misses the `_axioms` companions.

**Performance measured (08-24, MathBench_ProverBase + Decision_Procs context)**:
313 classes; building both authoritative sets (base predicates + `_axioms`
companions, via `Class.is_class` + `Locale.defined` + `specification_of` +
`intros_of`) costs **3 ms** one-time — noise next to `gen_infra_filters`'
existing init (preserved_set over all visible types). Per-query, a full pass
over all 13,905 constants: substring guess 3 ms vs hashtable lookup 4 ms —
indistinguishable. Bonus coverage re-check: both classify exactly the same 398
names (264 base + 134 `_axioms`), a third context confirming A = B.

**`Class.is_class` IS required here**, the opposite of rule 12:
`Locale.specification_of thy "HOL.type"` **raises** (`Locale.defined` is false),
because an `Axclass`-created class has no locale. Exactly one class is filtered
out per session. The two rules need opposite treatment because they ask different
questions — "is there a class predicate constant" versus "is there a locale
generated by the `class` command".

**Empty `specification_of` results are not failures.** 36 (HOL) / 48
(`MathBench_ProverBase`) classes return `NONE`: parameter-only classes with
`fixes` and no `assumes` (`Groups.plus`, `Orderings.ord`,
`Real_Vector_Spaces.norm`, `Topological_Spaces.open`, `Type_Length.len0`). They
generate no predicate; measured, `Sign.declared_const thy "Groups.class.plus"` is
**false**. Genuine extraction failures across all four runs: **zero**.

**`A \ B` is a benign substring collision, verified name by name.**
`HOL/NanoJava/Decl.thy:28` and `HOL/Bali/Decl.thy:329` each declare
`record "class" = …`, so the record's own name supplies the `class` segment:
`Decl.class.super`, `Decl.class.make`, `Decl.class.truncate`,
`Decl.class.class_ext.Abs_class_ext`, `Decl.class.typerep_class_ext_inst.…`. For
every one, the segment after `.class.` is not in the class name space. None is a
class predicate. Neither target session loads those theories, so they were
brought in deliberately with `Thy_Info.use_thy_legacy` to test the collision.

**So the change is looser, and looser in the right direction**: it stops
`class_infix` fighting `preserved_set` over record accessors, which is exactly
what `preserved_set` exists to protect — decoupling that was doubly
motivated while D6 planned to narrow `preserved_set`'s reach (D6 revoked 08-24;
the change stands on its own merits). Not measured: which of those 38 names actually
change status, since `inst_infix` (position 6) and `abs_rep_name` (position 9)
fire before `class_infix` (position 11) and `preserved_set` precedes the chain;
the store already holds 61 distinct `Decl.class.*` names, so most of the family
survives today. Step 1 answers this exactly.

### Consequence for the narrow-cascade proposal

After rules 7, 9, 11 and 12 are replaced, the only guesses left that can feed the
cascade are `inst_infix` (kept) and the `"HOL.equal"` half of
`internal_prefix`. The proposal to let only explicit judgements cascade rested
entirely on the cascade propagating the errors of `class_variant` and
`abs_rep_name` — both now fixed. **Revisit only if step 1 shows `inst_infix`
driving a significant share of cascade rejections.**

## 4. Rejected — do not re-propose

| Proposal | Why it dies |
| --- | --- |
| Separate "this entity deserves no record" from "any theorem mentioning it is worthless" | The cascade is intended and documented (`:52-53`) and is right for genuine machinery. The fault was one input, not the rule. |
| Session default plus a keep-list | See D4. Rots toward silent deletion. |
| Mark the reflected datatypes and add "a constant whose type mentions an infrastructure type is infrastructure" | Not judged on its merits — it was killed as "its only target is `MIR`'s `rdvd` group, which D8 discards", while D8's stated ground was that no rescue exists, which was itself wrong. It stands rejected because D8's real reason (zero users) stands. Independently: it cannot work for `Approximation_Bounds` (no `datatype`) or `Rat_Pair` (`Num` is a `type_synonym`), needs D6 first (since revoked), and would promote the `infra_const_cache` key defect from latent to live. |
| "`Dense_Linear_Order`'s cascade is provably empty because it declares no HOL constant" | It declares four locales (`:323, :334, :364, :394`); a locale with assumptions yields a predicate constant. |
| Retire `Infra_Filter.is_infra_theory` as callerless | It has a live caller, `tasks/AoA-learning/learning.ML:123`. |

### `no_atp` as a filter predicate — rejected in every runtime form (08-23)

Two forms were on the table; both are dead. **Conjunctive**: drop a fact when its
declaring theory is marked **and** it carries `no_atp`. **Disjunctive**: keep the
theory marking and add `no_atp` as a second disjunct in `is_infra_thm`.

**The runtime test cannot be made precise.** `Named_Theorems.member` is
`Item_Net.member` (`Pure/Tools/named_theorems.ML:53`) over `Thm.item_net`, which
is `Item_Net.init eq_thm_prop (single o Thm.full_prop_of)` (`Pure/more_thm.ML:253`).
**It matches by proposition.** The net stores thms with no name and no
provenance, so "was this tagged?" is not answerable — only "does its statement
equal something tagged?".

Tags come in two kinds: `lemma foo[no_atp]:` (the author tagging their own lemma
— a true signal) and `lemmas bar[no_atp] = x y z` (the author tagging *other
theories'* theorems, to keep them out of their own tactic's reach — a noise
source). Measured: `Isabelle2025-2/src/HOL` has 404 `no_atp` lines of which **43**
are bundles; `afp-2026-05-13/thys` has 71 of which **2** are.

The conjunctive form survives the 45 bundles because the declaring-theory clause
filters first. **The disjunctive form has no guard**, and the casualties are
concrete:

- `HOL.thy:1172` `lemmas if_splits [no_atp] = if_split if_split_asm`
  → **`if_split` and `if_split_asm` dropped store-wide.**
- `Dense_Linear_Order.thy:279`
  `lemmas dlo_simps[no_atp] = order_refl less_irrefl not_less not_le exists_neq`
  → **`order_refl`, `less_irrefl`, `not_less`, `not_le` dropped.**
- `Dense_Linear_Order.thy:298` `lemmas weak_dnf_simps[no_atp] = simp_thms dnf`
  → **all ~40 conclusions of `simp_thms` (`HOL.thy:1012`) dropped** — `not_not`,
  `eq_True`, `eq_False`, `(P ∧ True) = P`, `(∀x. P) = P`, the core of HOL
  simplification.

The ruling turned on `if_splits`: those must never be dropped.

**Correction to an earlier rejection**: it was first killed on "its `[no_atp]`
declarations *are* bundles of other theories' theorems", which is true of 9 of
`Dense_Linear_Order`'s 76 and false of the other 67. The rejection stands on the
evidence above, not on that claim.

**Unexplored routes, recorded so nobody re-derives them.** Both would have made
the predicate precise; neither was pursued once the predicate was rejected. (i)
An **offline name list** — parse the sources for `lemma X[…no_atp…]`, skip
`lemmas`; the runtime test becomes exact name-set membership (~361 own-tags in
HOL, ~69 in the AFP; regeneration on every bump, stale-fails safe). (ii) A
**name-hint set** built at filter-construction time from `Named_Theorems.get` +
`Thm.get_name_hint`. Unverified and decisive if revived: does
`lemmas dlo_simps = order_refl …` re-stamp the hint to
`Dense_Linear_Order.dlo_simps`, or keep `Orderings.order_refl`? Re-stamped ⇒ the
runtime form is exact. A five-line probe in `isabelle console -l HOL -n` settles
it.

**The policy question underneath.** `no_atp` reads `"theorems that should be
filtered out by Sledgehammer"` (`HOL.thy:811`). Sledgehammer is an automatic
prover and fears over-general facts; a proof agent retrieves facts to cite in a
structured proof. `if_splits` separates them. **"Bad for Sledgehammer" is not
"not worth retrieving."** A softer option was raised and not pursued: treat the
tag as a *ranking demotion* rather than a drop — ranking changes, not filter
changes.

**Reading the bracket in the source, offline, to choose which lemmas to alias
(D13) is a different thing and remains approved.** Nothing about `no_atp` reaches
the code; the product is 11 ordinary `lemmas` lines.

## 5. Corrections to earlier claims

Recorded because `THEORY_HASH_REKEY_PLAN.md` §8, this document's own earlier
revisions, or the companion asserted each of these, and they were wrong:

- "`is_infra_theory` has no callers." It has one: `learning.ML:123`. The grep
  that missed it was scoped to `contrib/` and `ICSE27/`, omitting `tasks/`.
- "The filter has no per-theorem keep-list." Aliasing with `lemmas` in a
  non-infrastructure theory works — `MathBench_Prover.thy:204-216` does it for 13
  facts — because the alias's fact name passes `:441` and its statement names no
  infrastructure constant. **But those 13 have never been collected: store scan
  gives `MathBench_Prover` 0 records.**
- "Each theory is all-or-nothing." False: a marked theory's constructors
  escape via the `preserved_set` veto — deliberately, since D6's revocation.
- "`Cooper.unit`, `MIR.eq`, `Parametric_Ferrante_Rackoff.Add` cannot collide."
  Two of the three do not exist: the real names are `MIR.fm.Eq` and
  `Parametric_Ferrante_Rackoff.tm.Add`, constructors, and therefore exactly the
  case `preserved_set` exempts.
- "16 theories to mark." Then 18. **It is 17** — `Approximation_Bounds` was
  reversed to kept (D12). 21 real theories minus 3 kept minus
  `Approximation_Bounds`; the generated `Approximation.unicode.thy` is not one of
  them.
- "The per-constant matcher cannot see a theory long name." It can; see D3.
- "This file already resolves long names three times (`:258`, `:267`, `:471`)."
  **Once**, at `:471-472`.
- "The store knows seven entity kinds and the marking gates five." Eleven tags;
  the four rule kinds are gated; only Method and Theorem_Collection escape.
- "`is_infra_method` drops a method **only** on Main-ancestry." Also concealed,
  hidden, `"??."`-shadowed, and no name-space entry.
- "Zero files changed between Isabelle2024 and Isabelle2025-2." The file *set* is
  unchanged; 10 `.thy` and 6 `.ML` differ in content.
- "`Dense_Linear_Order`'s keep set is `interval_empty_iff`,
  `finite_set_intervals`, `finite_set_intervals2`." The latter two carry
  `[no_atp]` and were explicitly rejected by an audit recorded at
  `MathBench_Prover.thy:193-203`. The correct set is the **14** untagged lemmas:
  `interval_empty_iff` (`:219`) plus the thirteen sign-of-product inequalities at
  `:555-625`. **11 remain to write** — `MathBench_Prover.thy:214-216` already
  aliases `neg_prod_sum_le`, `neg_prod_sum_lt`, `nz_prod_sum_eq` (uncollected,
  like the rest).
- "`Approximation_Bounds` loses 13 lemmas." `cos_periodic_nat` and
  `cos_periodic_int` are both verbatim in
  `Complex_Geometry/More_Transcendental.thy:150,:155`, so 11 are novel, of which
  **8** are already aliased. Moot under D12.
- "`Rat_Pair.of_int_div_aux` duplicates `Euclidean_Rings.thy:1714`." That is
  `of_int_div`; `of_int_div_aux` duplicates `Real.thy:999`.
- "The `Approximation_Bounds` cascade has two consumers, both checked (Bertrand,
  Karatsuba)." A third was not:
  `Chebyshev_Prime_Bounds/Chebyshev_Prime_Exhaust.thy` names `lb_ln`/`ub_ln` in
  `[code]` equation statements.
- Line-number drift: `:1453`→**`:1452`**; `:92-96`→**`:93-97`**;
  `learning.ML:119-121`→**`:119-122`**; `context.ML:1028-1030`→ the
  `Strhashtab.defined` test is at **`:1031`**.

## 6. Order of operations

**Steps 1→2 and 4→5 do not gate each other** — step 2 consumes nothing from step
1, and step 4 is sizing only (D10 says budget is not a gate). The former gates 1→3 and
3→3½ died with D6's revocation — no step gates on another now. **The first irreversible step is 5**: step 4 is `dry_run'`,
documented at `semantic_store.ML:1848-1851` as "No driver is involved: nothing
runs". **Step 6 shares no file and no decision with steps 1-5 and should run in
parallel from day one.**

**Step 1 — instrument and measure (no LLM, no build).**
The instrumentation is written and compiles; see §7. Fold
`Infra_Filter.gen_infra_filters` over `Global_Theory.facts_of` and bucket the
rejections **by `(rule, responsible theory long name)`, not by rule alone** —
today the marking covers all 21 session theories via `infra_session_thy_prefixes`,
after step 2 it covers 15 + `Minilang` + `Code_Evaluation`, and a rule-only
bucket folds in constants of the four theories that stop being marked and cannot
be corrected afterwards. **Re-run after step 2** — the coverage change re-attributes constants between
the marking and the other rules, and re-running costs nothing. (The third run
after the hoist is gone with D6's revocation.)

This answers: how many `Taylor_Models` theorems
the `Polynomial_List` cascade costs; whether `EC_Common`'s 12 lost lemmas died to
the session marking or to `class_variant` or both; and whether `inst_infix`
drives enough cascade rejections to revive the narrow-cascade proposal.

**Blocker and its likely unblock.** No local heap has both `HOL-Decision_Procs`
and `Infra_Filter`: `MathBench_ProverBase` has the former but not `Strhashtab`
(`Performant_Isabelle_ML` absent), and `Semantic_Embedding` has the latter but no
Decision_Procs. `MathBench_ProverBase.thy` imports
`"HOL-Decision_Procs.Reflective_Field"` but no `Minilang`/`Semantic_Embedding`
theory, even though `tasks/MathBench_Prover/ROOT` lists `Minilang_AoA` under
`sessions` — `sessions` makes a theory *importable*, not *imported*. That ROOT
also has `Semantic_Embedding` explicitly commented out; find out why before
uncommenting. **`Thy_Info.use_thy_legacy` loads an out-of-session theory into a
live console in well under a second** (measured), so a `MathBench_ProverBase`
console pulling in `Semantic_Embedding.Semantic_Embedding` should work with no
build.

**Step 2 — the long-name refactor (D2, D3, D4).**
One `Symtab.set` of 40 theory long names (15 Decision_Procs-marked + 23 tool-support (D15) + `Minilang` + `Code_Evaluation`); `is_from_infra_space` per name space at
`:355, :441, :538, :541, :544`; delete `:306-320`; `is_infra_theory` and
`is_excluded_theory` read the same set.

**The ordering trap.** D2 deletes `is_infra_session`, so `semantic_store.ML:378`
and `:1868` stop compiling and step 2 **must** rewrite `is_excluded_theory`. It
must deliberately leave the disjunct in:

```sml
fun is_excluded_theory thy =
  is_infra_theory thy orelse member (op =) base_theory_ids (Context.theory_identifier thy)
```

An implementer who writes the final form here has silently executed **step 5
early**: the unfuse ships and the 15 marked theories get collected before step 4's
sizing, and before anyone decided to collect them. D3's "one set, three consumers" framing is what tells the
implementer to keep it — step 5 removes the third consumer.

Also in step 2: rewrite `learning.ML:119-122`'s comment. It justifies skipping by
"excluded from semantic collection/retrieval by design", which stops being true
after D7. The durable rationale is that these are machinery proofs whose learned
experience is worthless regardless of retrievability.

**Steps 3 and 3½ — VOID (D6 revoked 08-24).** There is no hoist, so no
records are invalidated and no purge/re-collect/accept decision exists. The
revocation ruling is recorded under "Why the marking must beat
`preserved_set`" in §3.

**Step 4 — `dry_run'` the 15 marked and 5 kept theories.**
`semantic_store.ML:1862`, no LLM, no build. Sizing only. Note that 106 of
`Polynomial_List`'s 113 lemmas are `lemma (in <class>)`, so class-target material
has a second name path and the real entity count exceeds the command count.

**Step 5 — unfuse (D7), then collect.**
Delete the **`is_infra_theory`** disjunct from `is_excluded_theory`, leaving only
`base_theory_ids`. Then collect the five kept theories, the 15 marked ones (for
their methods), and `MathBench_Prover` — 13 aliases written 2026-06-17 that have
never reached the store, plus the 11 new `Dense_Linear_Order` aliases (D13).

**Step 6 — the Python-side skip list (D11).** See §8. Independent; start it now.

**Not in any step, and needed**: RUN the filter tests around step 2. **Ruled
08-24: running them does not require ROOT membership** — evaluate the test
files directly (isabelle-mcp / Isa-REPL over a heap that precompiles the
imports); "in no session" only means the build system will never run them by
itself, not that they cannot be run. The inventory: `Infra_Test.thy` (four
`gen_infra_filters` sites, in no session) and `Test_LTE_InfraFilter.thy` (its
`Infra_Filter_Test` session is entirely commented out) are the real tests —
evaluate them before and after step 2 as the regression pair.
`Infra_Decl_Test` and `Test_All` live in the opt-in `Semantic_Embedding_Test`
session. `Test_Infra_Session_Prefixes.thy` never references `Infra_Filter`, so
running it tests nothing — repair or delete it is a separate small decision,
still open.

## 7. State of the code

**`Tools/infra_filter.ML`, +77 −40 — compiles, never run, no numbers exist.**
Committed as `dd22e1b` in this submodule. Pre-edit backup:
`scratchpad/infra_filter.ML.bak`.

- New `first_rule tests` — thunked deliberately, because the plain `orelse` chain
  short-circuited and `on_bnf_origin_pos` / `Consts.the_constraint` are not cheap.
- `is_infra_const'` → **`infra_const_rule : string -> typ option -> string option`**,
  returning the name of the rule that fired. Cache retyped from
  `bool Strhashtab.table` to `string option Strhashtab.table`. Structure preserved
  exactly: `declared` first, then the `preserved_set` veto, then the twelve rules
  in their original order — `concealed`, `hidden`, `infra_theory`,
  `internal_prefix`, `pre_bnf_prefix`, `inst_infix`, `class_variant`,
  `quotient_typedef`, `abs_rep_name`, `adt_record`, `class_infix`, `class_pred`.
- New `first_internal_const thm` — `Term.exists_Const` answers *whether*, not
  *which*, and the cascade bucket needs which.
- `is_infra_thm` → **`infra_thm_rule : string * thm -> string option`**, order
  preserved including the cascade's position between `inductive_infra` and
  `internal_class`. A cascade rejection reads `"const:<name>"`.
- **The `bool` API is untouched**: `is_infra_const`, `is_infra_thm`,
  `is_infra_induct_thm` keep their signatures and are now `is_some` of the rule
  functions — one disjunction, not two to keep in agreement. The six production
  call sites (`explain_term.ML:88`, `semantic_store.ML:1288, :1442, :2327`,
  `agent_server.ML:1323`) and ~15 test sites are unaffected.

**Cost of `gen_infra_filters` itself, measured (08-25)**: ~25 ms per call in
the step-1 measurement context (MathBench_ProverBase + full Decision_Procs;
three calls: 23/30/26 ms), ~5 ms on `Main`. Call frequency: once per AoA
command build (`agent_server.ML:1738` via `make_entity_callbacks`), once per
invocation of the potential-defs callback (`agent_server.ML:1354`), once per
theory body in batch collection (`semantic_store.ML:1442`), and per call at
`semantic_store.ML:2327` / `explain_term.ML:88` — all fine at this cost.

**What it is for**: feed a `"const:<name>"` rejection back into
`infra_const_rule` and you learn why that constant is infrastructure. That chain
is the only instrument that can separate `EC_Common`'s two possible causes.

**`Tools/semantic_store.ML`, +1 −1** — `:1289` destructured all ten filter fields
with no `...`, so adding fields broke it.

**`contrib/_se_check/SE_Check`** — the compile check for the whole `Tools/` chain:

```
contrib/Isabelle2025-2/bin/isabelle build -d contrib/_se_check SE_Check
```

`-d` required (`_se_check` is not in `contrib/ROOTS`). Covers `pide_state.ML`,
`sledgehammer_embedding_ctxt.ML`, `infra_filter.ML`, `explain_term.ML`,
`entity_position.ML`, `theory_structure.ML`, `locale_instance.ML`,
`semantic_digest.ML`, `semantic_store.ML`, all from source. Session is
`= HOL + Isabelle_RPC + Performant_Isabelle_ML`; the `HOL` heap is valid.
**~12 seconds.** It had never built before 2026-08-20 — it was missing the
`entity_position.ML` and `semantic_digest.ML` `ML_file` lines. **Caveat**: a
backgrounded invocation returns the backgrounding's exit code, not the build's;
read the log for `Finished SE_Check` and grep for `***`. **`.gitignore:12`
excludes all of `contrib/`, so this directory is preserved by no commit.**

**Not started**: the `Isabelle_RPC_Host/context.py` cache re-keying and the ML
global callback (§8).

### Step 1 baseline numbers (2026-08-24, pre-step-2)

**Context**: the `MathBench_ProverBase` heap via isabelle-mcp, plus
`HOL-Decision_Procs.Decision_Procs` and
`Performant_Isabelle_ML.Performant_Isabelle_ML` loaded from source, then
`ML_file` of `infra_filter.ML` — no build, ~5 min end to end. The measurement
theory is committed as `Test/Infra_Filter_Step1_Measure.thy` (re-run it after
step 2 for the diff); the full `(rule, responsible theory)` table is
`INFRA_FILTER_STEP1_MEASUREMENT.tsv` (TOTAL/CONST/THM/CASCC rows; THM rows
carry thm-count and distinct-fact-count; cascade rejections are resolved to
`cascade/<const rule>` and bucketed on the CONSTANT's declaring theory).

Totals: 13,905 constants, 7,007 rejected (50.4%); 150,439 theorems (static
facts, thm granularity, concealed included), 62,880 rejected (41.8%).

Theorem kills by rule (thms / distinct facts): concealed 26,481/15,498;
infra_theory 17,604/4,055; cascade/class_infix 7,221/6,510;
cascade/internal_prefix 3,815/3,432; cascade/class_variant 3,200/2,951;
cascade/class_pred 1,259/990; cascade/abs_rep_name 1,125/1,043;
cascade/concealed 617/487; cascade/adt_record 446/310; hidden 396/371;
cascade/infra_theory 210/205; adt_infra 158/158; cascade/hidden 135/118;
cascade/quotient_typedef 116/116; inductive_infra 54/54;
cascade/pre_bnf_prefix 41/41; shadowed 2/2.

What this answers:

- **`inst_infix` drives ZERO theorem cascades** (1,728 constant rejections,
  no `cascade/inst_infix` row). The narrow-cascade proposal's revisit
  condition (§3) is answered: it stays dead.
- **`too_big` fired zero times; `declared` fired zero times** (this context
  carries no infra declarations); `shadowed` caught 2.
- **Recovery upper bounds for the three kept theories** (their current
  `infra_theory` kills, thm/fact): `Algebra_Aux` 538/452, `Polynomial_List`
  341/323, `Approximation_Bounds` 309/277. Upper bounds only — after step 2
  unmarks them, some facts fall through to later rules; the post-step-2
  re-run measures the real recovery.
- Top cascade constants (thm kills): `BNF_Def.rel_fun` 1,657,
  `HOL.equal_class.equal` 553, `Orderings.class.linorder` 305,
  `BNF_Def.eq_onp` 293, `Formal_Power_Series.fps.Abs_fps` 239 — all
  pre-existing intended behaviour, recorded as the re-run diff base.
- **The `Taylor_Models` sub-question is closed as moot**: `Taylor_Models`
  is not in this context, and after step 2 `Polynomial_List` stays kept and
  therefore unmarked — there is no `Polynomial_List` cascade to size.
- **`EC_Common` is not in this context** (it is
  `Crypto_Standards.EC_Common`, reachable only with the AFP dirs); its
  attribution is measured separately — see below.

**`EC_Common` attribution (same day; `Test/Infra_Filter_Step1_EC.thy`, same
heap plus the AFP dirs; full verdicts in `INFRA_FILTER_STEP1_EC_COMMON.tsv`).**
`Crypto_Standards.EC_Common` declares 199 theorems: 126 kept, 73 rejected
(44 cascade/infra_theory, 16 concealed, 11 cascade/class_variant, 1
cascade/concealed, 1 cascade/class_infix). Of its 15 `lemma (in field)`
lemmas the filter keeps exactly the 3 the store holds (§0's number
confirmed). The 12 losses split: **11 to the session marking's cascade
through `Algebra_Aux` constants** (`m_div`, `of_integer`, `of_natural`) and
**1 to `cascade/class_variant`** (`on_curvep_nz_identity` — via
`Elliptic_Locale.cring.on_curvep`). Answer to §6's question: **both causes,
dominated by the marking** — step 2 (keeping `Algebra_Aux`) recovers 11 of
the 12; theory-wide, all 44 cascade/infra_theory kills go through just four
`Algebra_Aux` constants (`cring_class_ops` 19, `m_div` 12, `of_integer` 12,
`of_natural` 1), so they all recover with step 2.

New finding for D14: **the 11 `cascade/class_variant` kills in `EC_Common`
all go through ordinary locale constants of `Elliptic_Locale`**
(`cring.on_curvep` 9, `cring.padd` 1, `field.make_affine` 1) — legitimate
elliptic-curve mathematics misjudged as class variants. Direct evidence for
replacing rule 7 (`class_variant`) with an authoritative query.

### Constant-verdict audit (2026-08-24): two adversarial auditors over the full dump

The per-constant verdicts (all 13,905, same context and same bucket counts as
the baseline) are `INFRA_FILTER_STEP1_CONST_VERDICTS.tsv`; the dumping theory
is the `Test/Infra_Filter_Step1_Measure.thy` pattern with `infra_const_rule`
only. One auditor swept the 7,007 rejections for false positives, one swept
the 6,898 keeps for false negatives; headline claims were re-verified by hand
(rule table lines, tsv rows, AFP citation greps).

**Buckets confirmed CLEAN on the rejected side**: `concealed`, `inst_infix`,
`class_pred`, `hidden`, `quotient_typedef`, `pre_bnf_prefix` — and notably
`class_variant`: all 213 penultimate qualifiers in THIS context are genuine
classes; zero victims of the `interpretation foo_class:` mechanism here (the
`EC_Common` victims live in the AFP context, not this one).

**Rejected-side misfires** (legitimate, cited mathematics rejected), ranked:

1. `class_infix` rejects the `class.X` locale-predicate constants — humans
   state relativization/interpretation lemmas about them (`class.linorder`
   cited in 32 AFP files; verified `Orderings.class.linorder` → class_infix).
   ~263 of the bucket's 397 lines; the 134 `class.X_axioms` lines are fine.
2. `infra_theory` (session sweep) catches two MORE theories with
   externally-cited math beyond the three D1 already keeps:
   `Approximation` (69 consts; `interpret_floatarith` cited in 20 AFP files,
   plus `approx`, `approx_form`, `bounded_by`, `isDERIV` — the ecosystem the
   verified-numerics AFP entries build on) and `Rat_Pair` (17 consts; `INum`,
   `isnormNum` used by Taylor_Models). `Reflected_Multivariate_Polynomial`
   (92 consts) is borderline: real polynomial library, zero external citers
   (Taylor_Models forked it rather than import it).
3. `internal_prefix` on `BNF_Cardinal_Order_Relation.` erases the cardinal
   library re-exported by HOL-Cardinals: `card_of` (the `|A|` notation),
   `cardSuc`, `regularCard`, `card_order`, `natLeq` … — 14 of that prefix's
   18 lines, heavily cited; also every custom-BNF registration proves
   `card_order` goals.
4. `adt_record` rejects free-constructor discriminators and the size plugin:
   `Sum_Type.sum.isl` (33 AFP entries), `Coinductive_List.llist.lnull` (47),
   `List.list.size_list` (own lemma section in `List.thy`, 78 AFP entries) —
   they sit in `bnf_origin_pos_set` but not in `preserved_set`.

Design calls: `abs_rep_name` has zero homonym victims in
this context, but ~9 genuine `Abs_` morphisms are their type's de-facto
constructor (`Abs_fps` — 24 AFP files and 239 baseline cascade kills,
`Abs_poly_mapping`, `Abs_fset` …) — **ruled 08-25: rule 9 deleted outright;
see the disposition table.** And `BNF_Def.rel_fun`/`eq_onp`,
`Transfer.bi_unique` etc. are cited in thousands of `transfer_rule` lemmas
yet are lifting plumbing — kept rejected by design for now.

**KEPT-side misses** (~950-1,000 of 6,898, ~14%), by mechanism:

1. Function-package `*_sumC` combinators: 285 (verified count). `f_sumC` is
   the pre-derivation combinator; humans cite `f.simps`, never it. (`*_dom`
   is user-facing and correctly kept.) **Ruled 08-25 (amended same day): new rule — reject
   iff the base name ends `_sumC` AND a sibling constant `<base>_graph`
   is declared in the constant space** (the function package generates
   both in one batch; the existence check makes a hand-written `*_sumC`
   structurally impossible to misjudge). Reliability verified: all 285 kept ones
   have a `_graph` sibling in the same dump (function-package birthmark);
   zero human-written `*_sumC` definitions in distribution+AFP; zero named
   lemma statements mention one (the only human contact is unnamed `have`
   steps inside nominal_function/HOLCF definition rituals, 10 AFP entries),
   so the cascade kills no stored theorem.
2. `inst_infix` blind spots: the pattern table (`infra_filter.ML:165-167`)
   excludes the `fun` type and concealed types, so 32 `_fun_inst.` constants
   (`Sup_fun_inst.Sup_fun` …) and 13 instance constants over concealed
   Quickcheck types slip through — same machinery as the 1,728 it catches.
   **Ruled 08-25: fix approved** — `inst_infixes` gets its own UNFILTERED
   type-name list (`fun` and concealed types included); the other consumers
   of `type_names` keep the filtered list.
3. Unmarked tool-support theories: ~558 constants of Quickcheck_*, Random_*,
   Lazy/Limited_Sequence, Nitpick, Nunchaku, SMT/Meson/Metis internals,
   Record's iso_tuple combinators, Code_* serializers, and HOL-Real_Asymp's
   Multiseries_Expansion+Lazy_Eval (127+7 — a decision-procedure support
   session directly analogous to HOL-Decision_Procs). A marking-list scope
   question, not a rule bug.
4. Locale-interpretation copies of generic order/lattice vocabulary: ~313
   (`Sublist.prefix_order.atLeastAtMost`, `Word.signed.*` …). Policy-level:
   some interpretation copies ARE the intended interface (`Geo_Real2.real2.*`
   was rightly not flagged). **Ruled 08-25: abandoned — accepted as visible
   noise.** No mechanical criterion separates intended-interface copies from
   vocabulary copies; per D4, noise is preferred over invisible deletion.
5. Small: corec-friend internals 11; per-library Quickcheck plumbing 10
   (`valtermify_*`, `random_aux_*`); assorted Fun_Def/BNF_Greatest_Fixpoint
   internals. **Ruled 08-25, corec + assorted internals only (with item 4):
   no batch project — clean up ad hoc with `declare [[infra_constant …]]`
   point declarations when one annoys.** The Quickcheck-in-library plumbing
   is **ruled 08-25** as two new rules: (a) base name starts `random_aux_`
   AND a `<base>_graph` sibling is declared (same guard as `_sumC`);
   (b) base name starts `valtermify_` OR `valterm_` AND the constant's type
   mentions the type `Code_Evaluation.term` (read via `Consts.the_constraint`,
   as rule 12 already does) — a mathematical constant's type never mentions
   the reflection term type, so misjudgement is structurally impossible.
   Family recount: TWO prefixes (the audit's original list missed
   `valterm_ratreal`/`valterm_fract`/`RatFPS.valterm_ratfps`); the
   Quickcheck_Random/Code_Lazy members already fall to D15's marking; net
   new targets: 7 constants (FSet ×2, Interval, Float, Real, Rat, AFP
   RatFPS).
6. Already ruled, listed for completeness: 193 constructors of the marked
   Decision_Procs theories' own reflected-syntax datatypes are KEPT via
   `preserved_set` — this is the deliberate boundary from D6's revocation
   (the kill zone stops at a type's public interface), not a miss.

## 8. The Python-side skip list (D11)

`semantics.py:127` keeps its own list:

```python
_SKIP_THEORY_LONG_NAMES = ["Pure", "Tools.Code_Generator", "HOL.Code_Evaluation", "HOL.Typerep"]
_SKIP_THEORY_BASES = {n.rsplit(".", 1)[-1] for n in _SKIP_THEORY_LONG_NAMES}
```

Two uses, and they may not want the same list:

- `is_thy_skipped` (`:2037`), inside `_auto_embed`: don't ask Isabelle to
  interpret a theory that is never interpreted. **It does not mirror ML's
  `is_excluded_theory`** — they diverge both ways: Python carries `HOL.Typerep`
  that ML lacks, and ML carries the whole `HOL-Decision_Procs` session that
  Python lacks.
- `theories_not_include` at `:2155` and `:2171`: keep these theories' entities out
  of the retrieval candidate pool. A different question.

Two defects:

- `is_thy_skipped` compares **base names** (`:132-135`), the same "a base name is
  not an identity" mistake D3 fixes in ML. Any theory named `Typerep` or `Pure`
  under any session is skipped. The other use is exact: `theories_not_include`
  reaches `context.ML:1031`, which compares `#theory_long_name` against a
  `Strhashtab`.
- Passing a non-empty exclusion list **defeats the candidate cache**.
  `_cached_or_call` (`context.py:98-120`) caches the `entities_of` result on the
  connection, but only when `_is_default` holds, and `_is_default` (`:85-95`)
  requires `not exclude`. So every query with no term/type patterns re-enumerates
  the whole live context over RPC, purely because four theory names are excluded.
  **`_cached_or_call_thm` (`:150-176`) needs the same treatment** — same
  `_is_default` gate at `:165-167`, and `entities_of` routes THEOREM and the four
  rule kinds through it (`:208, :311, :329, :349, :369`), so fixing only
  `_cached_or_call` leaves the expensive kinds uncached. **`_is_default` also
  requires `ctxt is None`** and `semantics.py` passes `ctxt=ctxt` on every call —
  possibly a second cause; check before scoping the fix.

Plan:

1. **Find out why `HOL.Typerep` is in the list** (`git log -L` on that line). That
   decides whether this is one concept or two, and therefore one callback or two.
2. **Register the authority in ML** as a global callback, modelled on
   `Theory_Hash.theory_name_of` (`theory_hash.ML:306-314`), and have Python call
   it instead of holding a literal. A list-returning callback serves both uses and
   fixes the base-name comparison for free. A **module-level** host cache was
   approved on the ground that one host serves one Isabelle process and dies with
   it — **that is true of the ephemeral mode only**;
   `tools/aoa_putnam_eval/run_fleet_eval.sh:201-229` shares one host across a
   fleet. Scope the cache accordingly.
3. **Make `_cached_or_call` and `_cached_or_call_thm` key their caches on the
   arguments.** Do not push the exclusion policy down into `context.ML`: that
   layer is generic RPC and should not know about the semantic database.

**Interaction with the `??.` measurement** in
`QUERY_BY_NAME_LIVE_RENDER_PLAN.md`: those numbers assume the ML candidate fold
runs in full on every query, which is true *because* this cache never fires. Fix
it and the per-query cost becomes per-cache-miss. The conclusion there is
unaffected — the display step is free either way — but the figure is the
pre-fix worst case.

## 9. Still open

1. ~~**Step 3½** — purge, re-collect, or accept the records the hoist
   invalidates.~~ Void — D6 revoked 08-24: no hoist, nothing invalidated.
2. ~~**`tools/slurm.py:95`** still forces `RPC_Host=127.0.0.1:27182` on every
   compute node; if nothing is LISTENing there, every REPL hard-errors on its
   first RPC call. `tools/slurm_run_server.sh:26`'s default was removed but is
   defeated by this caller. A production behaviour decision.~~ Ruled 08-24:
   intended behaviour, leave as is.
3. **The filter tests** — run them around step 2 by evaluating the files
   directly (ruled 08-24: ROOT membership not required; see §6). Open sliver:
   `Test_Infra_Session_Prefixes.thy` is fake (never references `Infra_Filter`)
   — repair or delete, undecided.
4. **`infra_const_cache` keys on `name` while the function takes
   `(name, typ_opt)`** (`:343-372`); call sites disagree (`:373` `NONE`, `:430`
   `SOME T`). No reachable divergence was constructed by three reviewers.
   **Record, do not act** — but it becomes live the moment any type-dependent
   rule is added; then read the type from `Consts.the_constraint` unconditionally,
   as rule 12 already does at `:369`.
5. **The unmeasured loss.** An entity dropped where no instance of it is stored
   leaves no trace, so the store cannot size this. Step 1 is what sizes it.

## 10. Traps, each paid for once already

- **The heaps are in `contrib/Isabelle2025-2/heaps/`** — the SYSTEM heaps, not
  `~/.isabelle/…/heaps`. Several turns were wasted concluding
  `MathBench_ProverBase` did not exist locally. It does, and loads in ~14 s.
- **Most heaps are stale.** Valid: `Pure`, `HOL`, `Main`, `MathBench_ProverBase`,
  `MathBench_Prover`. Invalid (`parent for this saved state does not match`):
  `Semantic_Embedding`, `Minilang`, `Auto_Sledgehammer`, `HOL-Algebra`,
  `Premise_Extraction`, `NTP4Verif`, `MiniF2F_Prover`, `Minilang_Translator`. That
  error usually means a rebuild was killed mid-way — **do not kill a rebuild with
  a timeout.** Probe with `-n`.
- **`isabelle console -n` gives the Pure ML environment.** `HOLogic` is absent
  (`Structure (HOLogic) has not been declared`) — strip `Trueprop` inline.
  `PolyML.print_depth` is absent; use `ML_Print_Depth.set_print_depth 0`.
  Cartouches do not survive (`error: ; expected but open was found`), and a bare
  console has no theory context, so antiquotations fail with `No context`. Bind
  `thy`/`ctxt` explicitly from `Thy_Info.get_theory`.
- **In the `HOL` heap `Thy_Info.get_theory "HOL.Main"` fails** — `Main` and
  `Complex_Main` are registered unqualified. Select from `Thy_Info.get_names ()`
  by base name.
- **`Thy_Info.use_thy_legacy` loads an out-of-session theory in under a second** —
  this is how out-of-scope material is brought in without a build.
- **Checking "all destructuring sites use `...`" with `grep -B 3` around
  `gen_infra_filters` misses `semantic_store.ML:1286`** — the one site listing all
  ten fields. Grep for `val {` upward from each call site instead.
- **A backgrounded `isabelle build` reports the backgrounding's exit code.**
- **The `isabelle-rpc` SKILL was wrong about host sharing.**
  `contrib/Isabelle_RPC/README.md:193` and
  `tools/aoa_putnam_eval/run_fleet_eval.sh:201-229` are ground truth: several
  Isabelle processes sharing one externally-launched host **is** supported and is
  in production. `RPC_EPHEMERAL_HOST_PLAN.md:476`'s `D-external` abolished
  fixed-address **auto-launch**, not sharing. Three files were "corrected" on the
  wrong reading and had to be reverted. **Do not infer from the SKILL; check
  `README.md` and the plan.**
- **Reader agents cannot detect that a document's facts are false.** Two approved
  the wrong SKILL edit; only a third with source access caught it. **Any review
  of a document about code needs a source-reading role.**
- **An agent asked to measure on Isabelle2025-2 fell back to Isabelle2024** after
  wrongly concluding no 2025-2 heaps existed, and reported the numbers without
  flagging the substitution prominently. State the required distribution as a hard
  constraint and require an explicit stop-and-report if it cannot be met.
- **Store scan idiom** (~4 min for 1.35M entries): `lmdb.open(…, readonly=True,
  lock=False, subdir=True)`; msgpack values, index 0 the kind, index 1 the entity
  name; key byte 16 is the kind tag.
- **Never open a bare TCP connection to port 6666** — it kills a running Isa-REPL
  server. Use `ss`/`lsof`.
- **`isabelle` is not on PATH.** Use `contrib/Isabelle2025-2/bin/isabelle`.

## 11. Session state at the 2026-08-24 hand-back (read before resuming step 1)

The session that owns this plan spent 08-23/24 closing its OTHER thread (the
by-name query live render; see the superproject's
`QUERY_BY_NAME_LIVE_RENDER_PLAN.md`, all committed). Nothing in §1-§10 changed.
What DID change is the environment this plan's steps will run in:

- **Build permission is broad now.** The owner approved `isabelle build` for
  the sessions this work needs (2026-08-23) — no longer only `SE_Check`. Never
  `-c`/`-f`. So step 1's unblock may simply be a small session with both
  `HOL-Decision_Procs` and `Semantic_Embedding` as parents, instead of the
  `Thy_Info.use_thy_legacy` console trick (§6 keeps that as the no-build
  route).
- **Port 6666 is occupied by ANOTHER session's REPL server** (a
  `MathBench_Prover` hierarchy server, up for hours as of 08-24 evening). Do
  not kill it; do not probe it with a bare TCP connect. Run any REPL this
  plan needs on an isolated port. The recipe that worked, end to end:
  1. `RPC_Host=<addr>` set means the heap build itself needs a Python host
     LISTENING there (`Semantic_Embedding.thy`'s `end` checks); start one
     first: `python3 -c 'import Isabelle_RPC_Host;
     Isabelle_RPC_Host.fork_and_launch__()' 127.0.0.1:27183 <log-file>`.
  2. `contrib/Isa-REPL/repl_server.sh 127.0.0.1:6667 <BASE_SESSION> <outdir>
     -d /home/qiyuan/Current/MLML -d contrib/Semantic_Embedding [-d …]` with
     `PATH` including `contrib/Isabelle2025-2/bin` and `RPC_Host` exported.
     Ready when a LINE-INITIAL `Running REPL<pid> ...` appears (the banner
     also contains that string — anchor the grep).
  3. The REPL build runs `-o quick_and_dirty=true`, which keys a SEPARATE
     heap chain under `~/.isabelle/Isabelle2025-2/heaps/` — first launch
     rebuilds Pure upward (~10 min), later launches reuse it.
  4. `27182` is what `tools/slurm.py` forces; leave it to the other session's
     infrastructure and use 27183+ for isolated work.
- **`MathBench_ProverBase` heap exists and is loadable** — the other
  session's server hierarchy loads `HOL-Analysis → HOL-Complex_Analysis →
  MathBench_ProverBase → MathBench_Prover` from the user heap dir, so §6
  step 1's console route has its heap ready.
- **Python processes need `EMBEDDING_API_KEY` in the process environment**
  (`os.getenv`); it lives in `~/.isabelle/Isabelle2025-2/etc/settings`, so
  export it via `"$(contrib/Isabelle2025-2/bin/isabelle getenv -b
  EMBEDDING_API_KEY)"` before running anything that touches semantic
  retrieval. Without it every semantic query dies with "no embedding service
  is configured".
- **The store's vectors were re-embedded at some point after 2026-07-09**
  (provenance not investigated): KNN similarity scores drifted ~0.01
  deterministically, and five Isa-Mini golden baselines were re-baselined to
  the drifted scores (owner-approved 08-24). If step 1's measurements are
  ever compared against pre-drift numbers, know the vectors moved.

**Post-hand-back, same day (08-24): D6 was revoked.** See the decision table,
the ruling block in §3, and §6 — steps 3 and 3½ are void.

## 12. Session state at the 2026-08-25 hand-back (read before implementing)

**Every decision is closed** (D1 revised, D14 rows finalized or superseded,
D15, D16, the preserved_set additions, three new rules). What remains is
IMPLEMENTATION, then verification. No open approvals.

### The consolidated `infra_filter.ML` worklist

Step 2 (long-name refactor, D2/D3/D4) plus every approved rule edit, in one
pass:

1. **The marking set**: one `Symtab.set` of 40 theory long names — the 15
   Decision_Procs marked (per `DECISION_PROCS_INFRA_THEORY_LIST.md`; note
   `Approximation` and `Rat_Pair` are now KEEP) + the 23 tool theories
   (`TOOL_THEORY_MARKING_LIST.md`) + `Minilang.Minilang` +
   `HOL.Code_Evaluation`. `is_from_infra_space` per name space; delete the
   base-name/session machinery (`:306-320` pre-drift — re-grep). **Ordering
   trap (§6 step 2)**: `is_excluded_theory` KEEPS the `is_infra_theory`
   disjunct until step 5. Rewrite `learning.ML:119-122`'s comment.
2. **Rule edits** (all owner-approved, see §3 table + §7 audit annotations):
   - DELETE rule 9 (`abs_rep_name`) outright.
   - Rule 11 `class_infix` → name test: `.class.` infix AND base name ends
     `_axioms`.
   - Rule 7 `class_variant` → `Sign.all_classes` + `Class.class_prefix`
     (approved 08-19, still to implement).
   - Rule 12 `class_pred` → `Logic.const_of_class` over `Sign.all_classes`
     (approved 08-23, still to implement).
   - Rule 4 `internal_prefix`: remove `"BNF_Cardinal_Order_Relation."`;
     theory prefixes join the long-name set; `"HOL.equal"` stays a name test.
   - `inst_infixes`: build from an UNFILTERED type-name list (`fun` and
     concealed types included); other `type_names` consumers keep the filter.
   - NEW rules: base name ends `_sumC` AND `<base>_graph` declared; base
     name starts `random_aux_` AND `<base>_graph` declared; base name starts
     `valtermify_`/`valterm_` AND type mentions `Code_Evaluation.term`
     (type via `Consts.the_constraint`, as rule 12 does).
   - `preserved_set` += discriminators (`Ctr_Sugar` `#discs`) and the
     size-plugin family (whole family; find the size plugin's registry —
     `BNF_LFP_Size` — rather than name-guessing).
3. **Do NOT purge the store** (D16): legacy records the new filter rejects
   stay. Backfill is a later, separate activity.

### Verification protocol (after the edits)

1. Compile check, then evaluate `Infra_Test.thy` and `Test_LTE_InfraFilter.thy`
   by direct file evaluation (ruled: no ROOT membership needed) — compare
   against a pre-edit run of the same files.
2. Re-run `Test/Infra_Filter_Step1_Measure.thy`, `Test/Infra_Filter_Step1_EC.thy`
   and the const-verdict dump; diff against `INFRA_FILTER_STEP1_MEASUREMENT.tsv`
   / `INFRA_FILTER_STEP1_EC_COMMON.tsv` / `INFRA_FILTER_STEP1_CONST_VERDICTS.tsv`.
   Expected movements: `EC_Common` keeps 11 of the 12 `field` lemmas (the 12th
   needs the rule-7 replacement); `cascade/class_infix` loses its base-predicate
   share (~264 consts recover); `cascade/abs_rep_name` disappears as a bucket;
   `Abs_fps` alone recovers 239 thms; `lnull` 225, `isl` 20, `size_list` 15;
   `_sumC` flips 285 KEPT→rejected; D15 marks flip ~500 KEPT→rejected;
   `Approximation`/`Rat_Pair` infra_theory kills (2,065+62 thms) recover.
3. Then steps 4/5/6 per §6 (unchanged).

### Environment deltas since §11

- The isabelle-mcp prover is (or was) running session `MathBench_ProverBase`
  with `session_dirs = [tasks/MathBench_Prover, contrib/Performant_Isabelle_ML,
  contrib/afp-2026-05-13/thys]` — relaunch with the same dirs re-loads the
  measurement context in ~5 min (Decision_Procs from source). The measurement
  scratch theories live in the session scratchpad (`Step1_*.thy`); the
  committed `Test/Infra_Filter_Step1_*.thy` are the durable copies.
- Port 6666 still belongs to another session's REPL server; everything here
  ran via isabelle-mcp, no REPL needed.
