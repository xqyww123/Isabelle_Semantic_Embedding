# Reworking the infrastructure filter

Started 2026-08-19. Supersedes `THEORY_HASH_REKEY_PLAN.md` §8, which is now a
pointer here. Companion: `DECISION_PROCS_INFRA_THEORY_LIST.md` holds the
theory-by-theory classification and its evidence.

`infra_filter.ML` decides which Isabelle entities are **infrastructure** —
machinery that exists only to make a package or a decision procedure work, which
no proof agent would cite. Infrastructure entities get no record in the semantic
database, and any theorem whose statement mentions an infrastructure constant is
dropped with them.

The trigger for this rework: the whole Isabelle session `HOL-Decision_Procs` was
marked infrastructure. `Algebra_Aux.thy` sits in that directory while being
ordinary ring algebra, so downstream AFP entries lost real lemmas — measured, of
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
   is genuine machinery. An earlier revision of §8 proposed separating the entity
   judgement from the theorem judgement; that would have broken a correct design
   and is withdrawn.
3. **The theory is never interpreted at all.** `is_excluded_theory`
   (`semantic_store.ML:1867`) calls `is_infra_session`; its own comment reads
   "Theories that are never interpreted". So `Algebra_Aux` has no records because
   it was never interpreted, not because a filter rejected it. Confirmed by store
   scan: `Algebra_Aux`, `Polynomial_List` and `DP_Library` have **0 records**.

Effect 1 does not cover every entity kind. The store knows seven kinds —
Constant, Theorem, Theorem_Collection, Type, Class, Locale, Method — and the
theory marking gates only five. **Method** goes through `is_infra_method`
(`:470-476`), which drops a method only when its declaring theory is `Main` or a
`Main` ancestor; **Theorem_Collection** has its own prefix list (`:499`,
`["Transfer.", "Lifting.", "SMT.", "Pure."]`), with a comment at `:496-498`
saying so explicitly. There is no Attribute kind, so `attribute_setup` produces
nothing either way.

Consequence: the 10 `method_setup` declarations of `HOL-Decision_Procs` and its
one `named_theorems` all pass the filter and are lost **only to effect 3**.
`approximation` (`Approximation.thy:1110`) is invoked on 87 AFP lines; `ring`
(`Commutative_Ring.thy:957`) and `field` (`Reflective_Field.thy:923`) likewise.
Method records do exist in the store (832 of them), so the storage path works —
the source is simply switched off.

## 2. Decisions taken

| # | Decision | Date |
| --- | --- | --- |
| D1 | The classification stands: 3 theories kept, 18 marked. See `DECISION_PROCS_INFRA_THEORY_LIST.md`. | 08-19 |
| D2 | Retire the session concept. `infra_session_names` is emptied and `is_infra_session` deleted. | 08-19 |
| D3 | Key the marker on theory **long** names, not base names. One `Symtab.set`, three consumers. | 08-20 |
| D4 | Populate that set by **enumeration** (19 entries), not by "session default plus exceptions". | 08-20 |
| D5 | `learning.ML:123` keeps calling `Infra_Filter.is_infra_theory`; `Algebra_Aux` entering AoA-learning scope is accepted. | 08-20 |
| D6 | Hoist the theory marking out of the `preserved_set` guard — **after** the measurement in §5. | 08-20 |
| D7 | Unfuse effect 3: delete the `is_infra_session` disjunct from `is_excluded_theory`, keeping the three base theories. | 08-20 |
| D8 | `MIR.thy` is discarded whole. Its ~21 items of ordinary mathematics are accepted as lost. | 08-20 |
| D9 | `Polynomial_List` stays kept and gets interpreted. | 08-20 |
| D10 | LLM budget is not a gate. Measure for sizing, not for permission. | 08-20 |
| D11 | The Python-side theory skip list moves behind an RPC callback, cached module-level in the host. | 08-20 |

### Why long names (D3), with the number

`infra_base_theory_names` (`:38`) matches by theory **base name**, and a base
name is not an identity. Two of the 18 names are already taken elsewhere in the
AFP: `LinearQuantifierElim/Thys/Cooper.thy` and
`Correctness_Algebras/Approximation.thy` (Walter Guttmann's approximation in
correctness algebras — ordinary mathematics, unrelated to floating point).
Measured against the live store: adding those two base names destroys **216 + 43
= 259 existing records**; the other 14 destroy none.

Today's code does not have this bug, because the session half of the marker is
ancestry-gated (`:306-310`, `Theory.ancestors_of thy`) and neither AFP entry has
a `HOL-Decision_Procs` ancestor. **The bug would have been introduced by the
"obvious" fix.**

Isabelle can resolve an entity name to its declaring theory's long name —
`Name_Space.theory_name {long: bool}` (`Pure/General/name_space.ML:24, :263`) —
and this file already does it three times: `:258`, `:267` (constant space) and
`:471` (`is_infra_method`, against a `Symtab.set` of theory long names). The
shape:

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
first name segment that is not their declaring theory (all `instantiation`
-generated, e.g. `Set.typerep_set_inst.typerep_set` declared in `HOL.List`), and
45 of 168 types carry no qualifier at all (Pure syntax types). The lookup is
right on all of them; the prefix test is wrong on all of them.

**Do not fold `internal_prefixes` (`:312-313`) into the long-name set.** It
contains `"HOL.equal"`, a *constant*-name prefix, which as a theory long name
would read `HOL.HOL` and classify all of `HOL.thy` as infrastructure. Only the
`infra_session_thy_prefixes` tail leaves it — that tail is spliced into both
`:313` and `:318` and therefore tested twice at `:355`/`:356`.

### Why enumeration (D4)

Both forms are safe once keyed on long names, so the choice is about how the list
rots. A session default classifies a future 19th theory as infrastructure by
default: if it is ordinary mathematics it **vanishes silently**, which is exactly
the `Algebra_Aux` failure. Enumeration classifies it as ordinary mathematics by
default: if it is machinery, noise **appears in the store**, which is visible and
repairable. Deletion is invisible; noise is not. Measured churn between
Isabelle2024 and Isabelle2025-2 in that directory: **zero files changed**, so the
maintenance the session form would save is maintenance on a scenario that has not
occurred.

### Why the marking must beat `preserved_set` (D6)

`is_infra_const'` has three tiers (`:348-370`):

```sml
  Symtab.defined decl_consts name                         (* explicit declaration *)
  orelse (not (Strhashtab.defined preserved_set name)     (* veto *)
          andalso ( ...twelve rules... ))
```

`preserved_set` (`:175-215`) holds the datatype constructors, selectors, `case`
combinators, BNF map/pred/rel/sets and record fields of **every visible type**
(`:154`, `Name_Space.get_names type_space` — inherited types included). It exists
to stop the *heuristic* rules below it (the `Abs_`/`Rep_` name test,
`has_class_variant`, `adt_record_prefixes`) from deleting legitimate generated
entities. The comment at `:349` shows the author already knew ordering matters:
"explicit declaration takes precedence over `preserved_set`".

The theory marking is an explicit judgement, not a heuristic, but it sits in the
third tier, under the veto. So a marked theory's constructors escape the marking
and do not cascade: asking about `MIR.Ifm` yields infrastructure, asking about
`MIR.fm.Eq` does not.

Measured: **1,451 store records mention `floatarith`** — 419 from
`Straight_Line_Program`, 413 from `Floatarith_Expression`, 143 from
`Init_ODE_Solver`, 137 from `Taylor_Models`, the rest across 8 more theories —
against **52 mentioning `interpret_floatarith`**. Records named
`Straight_Line_Program.slp_of_fa.simps(N)` are the N-th recursion equation of a
function defined by cases on `floatarith`, so by construction their statements
name a constructor. They exist today because of this veto.

The fix is two lines — move `is_from_infra_theory` up beside `decl_consts` — and
it makes the tiering read as an invariant: explicit judgements beat the veto,
heuristics never do. **It also widens the cascade**, which is why it waits for
§5's measurement.

### Why unfusing is safe and what it buys (D7)

`enumerate_entries` applies every filter *before* building the payload (`:1445`
constants, `:1453` theorems, `:1547` methods), so interpreting a marked theory
costs only the survivors. `MIR.thy`'s 213 reflection lemmas never enter the
payload. What does enter is the two kinds the marking does not gate: **10 proof
methods and 1 `named_theorems`**. `lemmas` aliasing cannot recover a method, so
this is the only route to them.

`is_excluded_theory` has to be rewritten regardless — it keys off
`is_infra_session`, which D2 retires, and it is what keeps the three kept
theories out today.

### What was decided about the direct losses (D8, D9)

**`MIR.thy`** — discarded whole. The 21 items of ordinary mathematics in it split
in two, and the split matters for why no cheap rescue exists:

- **9 lemmas plus the definition of `rdvd`** (`:34`, divisibility lifted to the
  reals; lemmas at `:37, :53, :57, :75, :78, :81, :1112, :1115, :3798`). Their
  statements mention `MIR.rdvd`, which the theory marking makes an infrastructure
  constant, so the `:444` cascade kills an alias as surely as the original.
  `[[infra_constant MIR.rdvd del]]` does not help: `del` only removes a name from
  `decl_consts` (`:92-96`), leaving the theory-marking disjunct to fire.
- **12 lemmas that name no `MIR` constant** — the 8 floor case-split lemmas at
  `:1658-1720`, `real_in_int_intervals` (`:3498`), `small_le` (`:3788`),
  `small_lt` (`:3793`), `real_ex_int_real01` (`:4786`). These *could* be aliased.

Both are accepted as lost. `rdvd` has zero users outside `MIR.thy` in the whole
distribution and the whole AFP.

**`Polynomial_List`** — kept. The objection was that it collides with
`HOL-Computational_Algebra.Polynomial` on 16 base names, eight of which are the
theorems cited as the reason to keep it. That objection is answered by the
display layer, not by the database:

- A result line's **name and statement are re-rendered against the live query
  context** (`agent_server.ML:900-903`, `:932`, `:942`, `:964-967`); only the
  English explanation is the stored string.
- `Name_Space.extern` refuses an ambiguous short access path when
  `names_unique` is set, and that option defaults to `true`
  (`Isabelle2025-2/etc/options:84`) with no override anywhere in this repo.
- Observed in a real run: `tools/aoa_putnam_eval/state/logs/ee54724c2_2/interaction.yaml:129`
  renders `Rat.Rats_sum`, qualified, because `Bernoulli.thy:42` also declares
  `Rats_sum`.
- The candidate pool is a live enumeration of what is in scope
  (`semantics.py:2150-2161`, `entities_of`), not the store — so the two
  `order_root`s only ever compete in a session importing both.

Keeping it also **stops a cascade that is running today**: `Polynomial_List` is
covered by the session marking, so statements in
`Taylor_Models/Polynomial_Expression.thy` that name `Polynomial_List.degree`
(`:2067`) are being dropped. That file has 834 surviving records.

## 3. Rejected — do not re-propose

| Proposal | Why it dies |
| --- | --- |
| Separate "this entity deserves no record" from "any theorem mentioning it is worthless" | The cascade is intended and documented (`:52-53`) and is right for genuine machinery. The fault was one input, not the rule. |
| Drive the `Dense_Linear_Order` filter from the authors' `[no_atp]` tags | Its `[no_atp]` declarations are `lemmas` bundles of *other* theories' theorems (`:279, :296, :298, :311`), and `Infra_Decl` matches by proposition. It would delete `order_refl`, `less_irrefl`, `not_less`, `not_le`, `simp_thms`, `nnf_simps` from the whole store. |
| Session default plus a keep-list | See D4. Rots toward silent deletion. |
| Mark the reflected datatypes and add "a constant whose type mentions an infrastructure type is infrastructure" | Its only target was `MIR`'s `rdvd` group, which D8 discards. It cannot work for `Approximation_Bounds` (no `datatype`) or `Rat_Pair` (`Num` is a `type_synonym`). It also needs D6 first, and would promote the `infra_const_cache` key defect from latent to live. |
| "`Dense_Linear_Order`'s cascade is provably empty because it declares no HOL constant" | It declares four locales (`:323, :334, :364, :394`); a locale with assumptions yields a predicate constant. |
| Retire `Infra_Filter.is_infra_theory` as callerless | It has a live caller, `tasks/AoA-learning/learning.ML:123`. |

## 4. Corrections to earlier claims

Recorded because §8 and the list document asserted each of these, and they were
wrong:

- "`is_infra_theory` has no callers." It has one: `learning.ML:123`.
- "The filter has no per-theorem keep-list." Aliasing with `lemmas` in a
  non-infrastructure theory works — `MathBench_Prover.thy:204-216` does it for 13
  facts — because the alias's fact name passes `:441` and its statement names no
  infrastructure constant. **But those 13 have never been collected: store scan
  gives `MathBench_Prover` 0 records.**
- "Each theory is all-or-nothing." False; see D6.
- "`Cooper.unit`, `MIR.eq`, `Parametric_Ferrante_Rackoff.Add` cannot collide."
  Two of the three do not exist: the real names are `MIR.fm.Eq` and
  `Parametric_Ferrante_Rackoff.tm.Add`, constructors, and therefore exactly the
  case `preserved_set` exempts.
- "16 theories to mark." It is 18.
- "The per-constant matcher cannot see a theory long name." It can; see D3.
- "`Dense_Linear_Order`'s keep set is `interval_empty_iff`,
  `finite_set_intervals`, `finite_set_intervals2`." The latter two carry
  `[no_atp]` and were explicitly rejected by an audit recorded at
  `MathBench_Prover.thy:193-203`. The correct set is the 14 untagged lemmas:
  `interval_empty_iff` (`:219`) plus the thirteen sign-of-product inequalities at
  `:555-625`.
- "`Approximation_Bounds` loses 13 lemmas." `cos_periodic_nat` and
  `cos_periodic_int` are both verbatim in `Complex_Geometry/More_Transcendental.thy:150,:155`,
  so 11 are novel; 10 of those are already aliased (uncollected).
- "`Rat_Pair.of_int_div_aux` duplicates `Euclidean_Rings.thy:1714`." That is
  `of_int_div`; `of_int_div_aux` duplicates `Real.thy:999`.

## 5. Order of operations

Each step's result gates the next. Nothing here is irreversible before step 4.

**Step 1 — instrument and measure (no LLM, no build).**
Make `is_infra_thm` (`:432-446`) report *which* disjunct fired instead of a
`bool`, and do the same for `is_infra_const'` (`:344-372`) so a cascade rejection
can be traced to the rule that made its constant infrastructure. Fold
`Infra_Filter.gen_infra_filters` over `Global_Theory.facts_of` for every theory of
the AFP-ALL image and bucket the rejections. This answers three questions at
once: the size of D6's blast radius; how many `Taylor_Models` theorems the
`Polynomial_List` cascade is costing; and whether `EC_Common`'s 12 lost lemmas
died to the session marking or to the `has_class_variant` defect (§7) or both —
which nobody can currently tell apart.

**Step 2 — the long-name refactor (D2, D3, D4).**
One `Symtab.set` of 19 theory long names; `is_from_infra_space` per name space at
`:355, :441, :538, :541, :544`; delete `:306-320`; `is_infra_theory` and
`is_excluded_theory` read the same set. Rewrite `learning.ML:119-121`'s comment:
the reason to skip is that these are machinery proofs whose experience is
worthless, not that they are unretrievable — the latter stops being true after
D7. Fix `contrib/Isa-Mini/Test/Test_Infra_Session_Prefixes.thy:6-14`, which
inlines its own `["HOL-Decision_Procs"]` instead of calling `Infra_Filter` and
would pass unchanged after the concept it tests is deleted.

**Step 3 — hoist the marking (D6), if step 1 supports it.**

**Step 4 — `dry_run'` the 18 marked and 3 kept theories.**
`semantic_store.ML:1862`, no LLM, no build. Sizing only. Note that 106 of
`Polynomial_List`'s 113 lemmas are `lemma (in <class>)`, so class-target material
has a second name path and the real entity count exceeds the command count.

**Step 5 — unfuse (D7), then collect.**
Collect the three kept theories, the 18 marked ones (for their methods), and
`MathBench_Prover` — 13 aliases written 2026-06-17 that have never reached the
store.

**Step 6 — the Python-side skip list (D11).** See §6.

## 6. The Python-side skip list

`semantics.py:127` keeps its own list:

```python
_SKIP_THEORY_LONG_NAMES = ["Pure", "Tools.Code_Generator", "HOL.Code_Evaluation", "HOL.Typerep"]
_SKIP_THEORY_BASES = {n.rsplit(".", 1)[-1] for n in _SKIP_THEORY_LONG_NAMES}
```

Two uses, and they may not want the same list:

- `is_thy_skipped` (`:2037`), inside `_auto_embed`: don't ask Isabelle to
  interpret a theory that is never interpreted. This mirrors ML's
  `is_excluded_theory`. It fires only when a query meets keys without vectors,
  and loops over distinct theories, so it is rare.
- `theories_not_include` at `:2155` and `:2171`: keep these theories' entities
  out of the retrieval candidate pool. Different question.

The ML counterpart, `base_theory_ids` (`semantic_store.ML:375`), is
`Code_Generator`, `Pure`, `Code_Evaluation` — **`HOL.Typerep` is only in the
Python list**, which suggests the list was tuned for the candidate-filter use and
the interpret guard rode along.

Two defects:

- `is_thy_skipped` compares **base names** (`:132-135`), the same "a base name is
  not an identity" mistake D3 fixes in ML. Any theory named `Typerep` or `Pure`
  under any session is skipped. The other use is exact: `theories_not_include`
  reaches `context.ML:1028-1030`, which compares `#theory_long_name` against a
  `Strhashtab`.
- Passing a non-empty exclusion list **defeats the candidate cache**.
  `_cached_or_call` (`context.py:98-120`) caches the `entities_of` result on the
  connection, but only when `_is_default` holds, and `_is_default` (`:85-95`)
  requires `not exclude`. So every query with no term/type patterns still
  re-enumerates the whole live context over RPC, purely because four theory names
  are being excluded.

Plan:

1. **Find out why `HOL.Typerep` is in the list** (`git log -L` on that line).
   That decides whether this is one concept or two, and therefore one callback or
   two.
2. **Register the authority in ML** as a global callback, modelled on
   `Theory_Hash.theory_name_of` (`theory_hash.ML:306-314`), and have Python call
   it instead of holding a literal. Cache the answer **module-level in the host**:
   a host serves exactly one Isabelle process and dies with it
   (`RPC_EPHEMERAL_HOST_PLAN.md`, D-external), so a module-level dict has exactly
   the right lifetime.
3. **Make `_cached_or_call` key its cache on the arguments** rather than caching
   only the all-defaults call, so a constant exclusion list stops defeating it.
   Do not push the exclusion policy down into `context.ML`: that layer is generic
   RPC and should not know about the semantic database.

## 7. Still open

- **`Dense_Linear_Order`'s 14 keep-worthy lemmas** — alias them (near-free) or
  accept the loss. Its two proof methods `dlo` and `ferrack` come back via D7
  regardless.
- **`has_class_variant` (old §8.1)** — the rule at `:322-337`, consumed at
  `:359`, infers "L is a type class" from the string `_class`. It is wrong:
  `Algebra_Aux.thy:286` writes `interpretation cring_class: cring …` with a
  human-chosen prefix, so `Elliptic_Locale.cring_class.pdouble` exists and the
  rule deletes the general locale constant, taking all 20
  `Elliptic_Locale.cring.*` facts. The fix is to ask `Class.is_class` and derive
  the prefix with `Class.class_prefix` (`Pure/Isar/class.ML:353`, used by
  `class_declaration.ML:75, :295`). **Undecided: whether to fix it in this round.**
  Step 1's instrumentation makes attribution possible either way, which removes
  the usual argument for doing it separately.
- **The `Abs_`/`Rep_` name test (old §8.2)** — approved 2026-08-19: replace the
  base-name test at `:361-362` with `Typedef.get_info_global`, which `:287`
  already uses. Not yet scheduled. It currently classifies the locale predicate
  `Abs_Int1.Abs_Int` as infrastructure and takes 7 of that locale's 9 facts;
  `Abs_` there abbreviates *Abstract Interpretation*.
- **`infra_const_cache` keys on `name` while the function takes `(name, typ_opt)`**
  (`:343-372`); call sites disagree (`:373` passes `NONE`, `:430` passes
  `SOME T`). No reachable divergence was constructed by three reviewers. Record,
  do not act.
- **The unmeasured loss.** An entity dropped where no instance of it is stored
  leaves no trace, so the store cannot size this. Step 1 is what sizes it.

---

# Handover, 2026-08-20 20:0x — corrections not yet integrated above

This session took over the whole thread from the session that wrote everything
above. **Three plan reviews ran after that text was written and none of their
findings reached it.** They are transcribed here verbatim in substance, because
they existed only in a conversation transcript. **Everything in this appendix
outranks the corresponding text above.** Integrating them into the body is a
separate pass, not yet done.

## H1. A regression the naive long-name fix ships

`infra_theory_prefixes` (`infra_filter.ML:315-318`) has **three** components —
`["Code_Evaluation."]` + `Minilang` + the session tail — and step 2 replaces
only the last two. Constants stay covered by `internal_prefixes` (`:313`), but
facts (`:441`), types (`:538`), classes (`:541`) and locales (`:544`) lose the
gate, and it runs on live inherited names (`agent_server.ML:1323` folds
`Proof_Context.facts_of`). **The enumerated set must contain
`"HOL.Code_Evaluation"`. APPROVED by the user 2026-08-20 — this is a
decision now, not just a finding.**

Related trap, same shape: do **not** fold `internal_prefixes` into the long-name
set. It contains `"HOL.equal"`, a *constant*-name prefix, not a theory prefix;
mapping it to a theory long name yields `HOL.HOL` and marks all of `HOL.thy`.

## H2. An ordering trap that costs a collection run

D2 deletes `is_infra_session`, so `semantic_store.ML:378` and `:1868` stop
compiling and **step 2 must rewrite `is_excluded_theory`**. After that there is
no `is_infra_session` disjunct left for step 5 to delete. The plan is coherent
only if step 2 deliberately leaves

```sml
fun is_excluded_theory thy =
  is_infra_theory thy orelse member (op =) base_theory_ids (Context.theory_identifier thy)
```

An implementer who writes the final form during step 2 has silently executed
step 5 three steps early: the unfuse ships before the hoist, the 17 theories get
collected under the un-hoisted filter, and the store fills with records the hoist
then rejects. **Restate step 5 as "delete the `is_infra_theory` disjunct", and
say in step 2 that the disjunct is kept on purpose.** D3's "one set, three
consumers" framing is what tells the implementer to keep it — fix both together.

## H3. The measurement must be bucketed and re-run

- **Bucket by `(rule, responsible theory long name)`, not by rule alone.** Today
  the marking covers all 21 session theories through
  `infra_session_thy_prefixes`; after step 2 it covers 17 + `Minilang`. A
  rule-only bucket folds in constants of `Algebra_Aux`, `Polynomial_List`,
  `DP_Library` and `Approximation_Bounds` that stop being marked, and cannot be
  corrected afterwards.
- **Re-run the fold after step 2 and again after step 3.** The hoist moves the
  marking above the `preserved_set` veto while the other eleven rules stay below
  it, so a constant previously attributed to `has_class_variant` or the
  `Abs_`/`Rep_` test re-attributes to the marking. §7's `has_class_variant`
  decision leans on that attribution; taken pre-hoist it is wrong. Re-running
  costs nothing — no LLM, no build.

## H4. A missing step: nothing purges what the hoist invalidates

The hoist's blast radius is 1,451 existing `floatarith`-mentioning records.
After it, the filter rejects them; no step deletes them. The codebase already
knows filter changes do not propagate — `is_declared_infra_thm` exists precisely
because "the live KNN CACHED pass does not re-filter"
(`infra_filter.ML:522-531`). **Decide purge / re-collect / accept between steps
3 and 5.** Not yet decided.

## H5. Numeric errors in the body above

| Body says | Correct |
| --- | --- |
| "the other **14** destroy none" | **15** (18 marked names − 2 colliding − `Approximation_Bounds`) |
| "the rest across **8** more theories" | **25** further declaring locations, across 6 AFP sessions |
| "seven entity kinds … the marking gates only five" | `Universal_Key.ML:31-35` defines **eleven** tags: 0x01–0x07 plus 0x12/0x22/0x32/0x42 for Introduction/Elimination/Induction/Case_Split rules. **The four rule kinds ARE gated** — they route through `is_infra_thm` at `:441`. Substance survives: only **Method** and **Theorem_Collection** escape. The arithmetic does not. |
| "**zero files changed** between Isabelle2024 and Isabelle2025-2" | The `.thy` file **set** is unchanged; **10 `.thy` files differ in content** (MIR, Algebra_Aux, Approximation, Approximation_Bounds, Commutative_Ring, Conversions, Cooper, Dense_Linear_Order, Ferrack, Reflected_Multivariate_Polynomial) plus 6 `.ML`. D4's argument survives — nothing added or removed — but the sentence is false as written. |
| "11 novel, **10** already aliased" | **8**. Two of the ten are `cos_periodic_nat`/`cos_periodic_int`, exactly the two excluded from the novel set. Moot now that `Approximation_Bounds` is kept. |
| "this file already does it **three times**: `:258`, `:267`, `:471`" | **Once** (`:471-472`). `:258`/`:267` call `Name_Space.the_entry` to read `#pos`, never a theory name. `Name_Space.theory_name` appears nowhere in `infra_filter.ML`. |

Line-number drift: `:1453`→**`:1452`**; `:92-96`→**`:93-97`**;
`learning.ML:119-121`→**`:119-122`**; `context.ML:1028-1030`→ the
`Strhashtab.defined` test is at **`:1031`**.

Over-strong phrasings: `is_infra_method` does **not** drop "only" on
Main-ancestry — also concealed, hidden, `"??."`-shadowed, and no name-space entry
(`:473` `| NONE => true`). And **only 9 of `Dense_Linear_Order`'s 76 `[no_atp]`
declarations are `lemmas` bundles**; 67 are its own lemmas. Say "Among its
`[no_atp]` declarations are…". That second one matters — see H6.

## H6. Three rejections in §3 that do not survive

**The `[no_atp]` rejection was factually wrong.** It rested on "its `[no_atp]`
declarations are bundles of other theories' theorems", true of 4 of 76. The
**proposition-seeded** form is still correctly rejected: `Infra_Decl` matches by
`Thm.eq_thm_prop`, so seeding it from `no_atp` would delete `order_refl`,
`not_less`, `not_le` and `simp_thms` store-wide. **But a name-based variant
escapes**: drop a fact when its own declaring theory is marked AND it carries
`no_atp`, resolved through `Thm.get_name_hint` (`Pure/more_thm.ML:95, :657`). For
the `:279` bundle that name is `Orderings…order_refl`, whose theory is not
marked, so it survives. The variant **derives exactly the 14-lemma keep set** the
plan hardcodes by hand. **Open — put to the user, unanswered.**

**The reflected-datatype rejection is circular.** It was killed because "its only
target was `MIR`'s `rdvd` group, which D8 discards", while D8's stated ground for
discarding is that no cheap rescue exists. Neither was judged on its merits. The
two extra reasons (no datatype in `Approximation_Bounds`; `Rat_Pair`'s `Num` is a
`type_synonym`) show only that it cannot *replace* the theory marking, which it
never claimed to.

**The cascade rejection over-corrects.** Killing the broad form is right. But the
cascade runs through `is_infra_const'`, which puts `decl_consts` and the theory
marking in the same disjunction as `has_class_variant` and the `Abs_`/`Rep_`
test — and §7 records that **both of those heuristics are wrong**. So the cascade
today carries heuristic errors into other theories' theorems. A narrow form
survives: **cascade only on explicitly-judged infrastructure (`decl_consts` + the
theory marking), never on heuristically-inferred constants** — the same
explicit-beats-heuristic invariant D6 adopts for the `preserved_set` veto and
then stops applying. Note the comment cited as authority (`:52-53`) sits inside
the `Infra_Decl` block and speaks only of *declared* infra constants; it says
nothing about heuristics cascading. **Open — put to the user, unanswered.**

## H7. D8's reason is wrong; its conclusion probably is not

`MIR`'s content is not unrescuable. Three rescues exist: restate the 9 `rdvd`
lemmas with `rdvd_def` unfolded (then no statement names a `MIR` constant and
`:444` never fires); re-define `rdvd'` in a kept theory; or add a keep
declaration to `Infra_Decl`, which already has the shape and which `del` looks
like it should do and does not. **The right reason is the one the body states
one sentence later and never promotes: `rdvd` has zero users outside `MIR.thy`
in the whole distribution and the whole AFP.** Conclusion unchanged (the user
ruled "完全丢弃 MIR"); the stated reason should be replaced. **Open.**

## H8. D9 is incomplete

The display-layer argument (`Name_Space.extern`, `names_unique = true`) prevents
mis-citation but does **not** reach ranking — ranking scores stored embeddings of
stored English, and extern runs after. What saves D9 is that the candidate pool
is a live enumeration (`semantics.py:2150-2161`), so the two `order_root`s only
compete in a context importing both. **State the residual**: in such a context
(anything importing `Taylor_Models/Polynomial_Expression.thy`, which imports
`Polynomial_List` at `:11`), both enter the pool with near-identical stored
English and both can rank; display-time qualification does not stop the duplicate
occupying a result slot.

## H9. The `Dense_Linear_Order` aliasing is 11, not 14

`MathBench_Prover.thy:214-216` already aliases `neg_prod_sum_le`,
`neg_prod_sum_lt`, `nz_prod_sum_eq`. Those three share the
written-but-never-collected status of the other ten.

## H10. There is almost no test safety net, and step 2 repairs the wrong test

- `Test_Infra_Session_Prefixes.thy` is **in no ROOT at all** and never references
  `Infra_Filter`. Step 2's "fix the fake test" targets a file nothing builds.
- `Test_LTE_InfraFilter.thy` sits in Isa-Mini's `Infra_Filter_Test` session,
  which is **entirely commented out**.
- `Infra_Test.thy` (four `gen_infra_filters` sites) is in no session either.
- Only `Infra_Decl_Test` and `Test_All` are in the opt-in
  `Semantic_Embedding_Test` session.

**The refactor is going in largely uncovered.**

## H11. §6 (the Python skip list) — three corrections

- **`_cached_or_call_thm` needs the same fix** (`context.py:150-176`), same
  `_is_default` gate at `:165-167`; `entities_of` routes THEOREM and the four
  rule kinds through it (`:208, :311, :329, :349, :369`). Fixing only
  `_cached_or_call` leaves the expensive kinds uncached.
- **"`is_thy_skipped` mirrors ML's `is_excluded_theory`" is false.** They diverge
  both ways: Python carries `HOL.Typerep` that ML lacks; ML carries the whole
  `HOL-Decision_Procs` session that Python lacks.
- `_is_default` also requires `ctxt is None`, and `semantics.py` passes
  `ctxt=ctxt` on every `entities_of` call — possibly a second cause.

## H12. §5's preamble is wrong twice, and step 6 is independent

"Each step's result gates the next" is false for 1→2 (step 2 consumes nothing
from step 1) and 4→5 (sizing only; D10 says budget is not a gate). "Nothing here
is irreversible before step 4" is off by one — step 4 *is* `dry_run'`, documented
at `semantic_store.ML:1848-1851` as "No driver is involved: nothing runs". The
first irreversible step is **5**. And **step 6 shares no file and no decision
with steps 1-5; run it in parallel from day one.**

## H13. Approvals from the other session, not otherwise recorded here

All from our user, in the handing-over session, 2026-08-20 unless noted.

1. **`Approximation_Bounds` reversed to kept** (19:35). **Marked set is 17.**
   Its header (`:5-9`) says the authors split the file deliberately: the
   bound-computation material is "morally immaculate" and the oracle/reflection
   lives in `Approximation.thy`. Marking it was the `Algebra_Aux` failure in a
   new place. Also stops a cascade into
   `Chebyshev_Prime_Bounds/Chebyshev_Prime_Exhaust.thy`, which mentions
   `lb_ln`/`ub_ln` in `[code]` equation statements.
2. **Save all 14 `Dense_Linear_Order` lemmas by aliasing**, and **do not
   hand-pick** — use the authors' `[no_atp]` complement as the selection
   criterion, because both prior hand-picks were wrong (the 2026-06-17 audit
   chose 3 and missed 11; the later nomination of
   `finite_set_intervals`/`finite_set_intervals2` was wrong, both carry
   `[no_atp]` and that audit had explicitly rejected them). **Offline selection
   criterion only — never a runtime mechanism.**
3. **`MIR` fully discarded, both groups** — "不要紧，可以完全丢弃 MIR". A rescue
   of the 12 aliasable ones was offered and declined.
4. **B2 resolved**: keep the `learning.ML:123` call site, accept the scope
   change, and **rewrite the comment's rationale** at `:119-122`. It justifies
   skipping by "excluded from semantic collection/retrieval by design", which
   stops being true after D7. The durable rationale: these are machinery proofs
   whose learned experience is worthless regardless of retrievability.
   **The edit was never made.**
5. **D10: LLM budget is not a gate** — "别管预算，我有订阅".
6. **The order: measure → hoist → `dry_run'` → unfuse**, explicitly agreed, on
   the ground that hoisting first makes the unfuse cheaper.
7. **Build permission was granted in that session** ("批准你自行编译").
   **NOT carried over.** `CLAUDE.md` forbids `isabelle build` without the user's
   explicit command in *this* session, and a peer relaying an approval is not
   that. Ask before building.

## H14. State of the code at handover

**`Tools/infra_filter.ML`, +77 −40 — compiles, never run, no numbers exist.**
Pre-edit backup:
`/tmp/claude-1002/-home-qiyuan-Current-MLML/b27550a8-ffdc-4225-ab65-13ff4cccb658/scratchpad/infra_filter.ML.bak`

- New `first_rule tests` — thunked, deliberately, because the plain `orelse`
  chain short-circuited and `on_bnf_origin_pos` / `Consts.the_constraint` are not
  cheap.
- `is_infra_const'` → **`infra_const_rule : string -> typ option -> string option`**,
  returning the name of the rule that fired. Cache retyped from
  `bool Strhashtab.table` to `string option Strhashtab.table`. Structure
  preserved exactly: `declared` first, then the `preserved_set` veto, then the
  twelve rules in their original order — `concealed`, `hidden`, `infra_theory`,
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

**What it is for:** feed a `"const:<name>"` rejection back into
`infra_const_rule` and you learn why that constant is infrastructure. **That
chain is what settles whether `EC_Common`'s 12 lost lemmas died to the session
marking or to `has_class_variant` or both.** Nobody can currently tell them
apart, and this is the only instrument that can.

**`Tools/semantic_store.ML`, +1 −1** — `:1289` destructured all ten record
fields with no `...`, so adding fields broke it. Added `, ...`. Compiles.

**Other edits held at handover** (all working, none committed):
`THEORY_HASH_REKEY_PLAN.md` (§8 rewritten in place; **should have become a
one-line pointer here**), `tasks/AoA-learning/learn.py` (docstring `:14-21`,
comment `~:529`), `tools/slurm_run_server.sh` (deleted the
`RPC_Host=127.0.0.1:27182` default at `:26` — **defeated by its caller**,
`tools/slurm.py:95` always sets it, and the real fix is upstream and unmade),
`tools/slurm.py` (comment only, `:92-95`),
`tools/missing_lemma_loop/watcher.py` (comment only, `:70-71`),
`contrib/_se_check/SE_Check_Thy.thy` (+2 `ML_file` lines),
`contrib/Isabelle_RPC/.claude/skills/isabelle-rpc/SKILL.md` (+25 −20).

## H15. Not started

- **`Isabelle_RPC_Host/context.py` cache re-keying.** Nothing touched. Key the
  cache on the arguments instead of caching only the all-defaults call. **Do not
  push the exclusion policy down into `context.ML`** — that layer is generic RPC
  and must not know about the semantic database. See H11.
- **The ML global callback replacing the Python skip list.** Nothing written.
  Intended shape modelled on `Theory_Hash.theory_name_of`
  (`theory_hash.ML:306-314`): a global callback returning the authoritative
  theory long-name exclusion list. Two unresolved sub-questions: **why
  `HOL.Typerep` is in the Python list and not in ML's `base_theory_ids`**
  (`git log -L` on `semantics.py:127` would settle it, and it decides whether
  this is one concept or two, hence one callback or two); and that a
  list-returning callback fixes the base-name comparison at `is_thy_skipped`
  (`:132-135`) for free. A **module-level** host cache was approved on the ground
  that one host serves one Isabelle process — **true only of ephemeral mode**;
  `tools/aoa_putnam_eval/run_fleet_eval.sh:201-229` shares one host across a
  fleet.

## H16. `contrib/_se_check/SE_Check` — the compile check for the whole chain

```
contrib/Isabelle2025-2/bin/isabelle build -d contrib/_se_check SE_Check
```

`-d` is required (`_se_check` is not in `contrib/ROOTS`). Covers `pide_state.ML`,
`sledgehammer_embedding_ctxt.ML`, `infra_filter.ML`, `explain_term.ML`,
`entity_position.ML`, `theory_structure.ML`, `locale_instance.ML`,
`semantic_digest.ML`, `semantic_store.ML`, all from source. Session is
`= HOL + Isabelle_RPC + Performant_Isabelle_ML`; the `HOL` heap is valid.
**~12 seconds.** Writes only its own heap. It had never built before 2026-08-20 —
it was missing the `entity_position.ML` and `semantic_digest.ML` lines.
**Caveat:** a backgrounded invocation returns the backgrounding's exit code, not
the build's; read the log for `Finished SE_Check` and grep for `***`.

(This is an `isabelle build`. Under `CLAUDE.md` it needs the user's explicit
command in the session that runs it.)

## H17. Traps, paid for once already

- **The heaps are in `contrib/Isabelle2025-2/heaps/`** — the SYSTEM heaps, not
  `~/.isabelle/…/heaps`. Several turns were wasted concluding
  `MathBench_ProverBase` did not exist locally. It does.
- **Most heaps are stale.** Valid: `Pure`, `HOL`, `Main`, `MathBench_ProverBase`,
  `MathBench_Prover`. Invalid (`parent for this saved state does not match`):
  `Semantic_Embedding`, `Minilang`, `Auto_Sledgehammer`, `HOL-Algebra`,
  `Premise_Extraction`, `NTP4Verif`, `MiniF2F_Prover`, `Minilang_Translator`.
  That error usually means a rebuild was killed mid-way — **do not kill a rebuild
  with a timeout.** Probe with `-n`.
- **No local heap has both `HOL-Decision_Procs` and `Infra_Filter`.**
  `MathBench_ProverBase` has Decision_Procs but no `Strhashtab`
  (`Performant_Isabelle_ML` absent). `MathBench_ProverBase.thy` imports
  `"HOL-Decision_Procs.Reflective_Field"` but imports no `Minilang`/
  `Semantic_Embedding` theory, even though `tasks/MathBench_Prover/ROOT` lists
  `Minilang_AoA` under `sessions` — `sessions` makes a theory *importable*, not
  *imported*. That ROOT also has `Semantic_Embedding` explicitly commented out;
  find out why before uncommenting. Isabelle can load any theory dynamically, so
  a `MathBench_ProverBase` REPL evaluating
  `theory Probe imports Semantic_Embedding.Semantic_Embedding begin` should work
  without a build — `Semantic_Embedding = HOL + Isabelle_RPC +
  Performant_Isabelle_ML`, all small.
- **`isabelle console` takes plain SML only** — `\<open>…\<close>` cartouches
  give `error: ; expected but open was found` — and a bare console has no theory
  context, so antiquotations fail with `No context`. The way round:
  ```sml
  val thy = Thy_Info.get_theory "MathBench_ProverBase.MathBench_ProverBase";
  val _ = Context.setmp_generic_context (SOME (Context.Theory thy))
            (fn () => use "…/infra_filter.ML") ();
  ```
- **Checking "all destructuring sites use `...`" with `grep -B 3` around
  `gen_infra_filters` misses `semantic_store.ML:1286`** — the one site listing
  all ten fields. Grep for `val {` upward from each call site instead.
- **The `isabelle-rpc` SKILL was wrong about host sharing.**
  `contrib/Isabelle_RPC/README.md:193` and
  `tools/aoa_putnam_eval/run_fleet_eval.sh:201-229` are ground truth: several
  Isabelle processes sharing one externally-launched host **is** supported and is
  in production. `RPC_EPHEMERAL_HOST_PLAN.md:476`'s `D-external (v3, supersedes
  v2 D-shared)` abolished fixed-address **auto-launch**, not sharing. Three files
  were "corrected" on the wrong reading and had to be reverted. **Do not infer
  from the SKILL; check `README.md` and the plan.**
- **Reader agents cannot detect that a document's facts are false.** Two approved
  the wrong SKILL edit; only a third with source access caught it. Any review of
  a document about code needs a source-reading role.
- **Store scan idiom** (~4 min for 1.35M entries): `lmdb.open(…, readonly=True,
  lock=False, subdir=True)`; msgpack values, index 0 the kind, index 1 the entity
  name; key byte 16 is the kind tag.
- **Never open a bare TCP connection to port 6666** — it kills a running
  Isa-REPL server. Use `ss`/`lsof`.
- **`isabelle` is not on PATH.** Use `contrib/Isabelle2025-2/bin/isabelle`.

## H18. Open, needing the user

1. ~~The `no_atp` name-based variant (H6)~~ — **REJECTED by the user
   2026-08-21, in every runtime form.** `no_atp` is not introduced as a
   predicate at all; the filter ignores it. See H19 for the measurement that
   settled it.
2. The **narrow cascade** form (H6) — cascade only on explicit judgements.
3. D8's **reason** (H7) — conclusion stands, stated reason is wrong.
4. **Purge / re-collect / accept** the 1,451 records the hoist invalidates (H4).
5. Whether `THEORY_HASH_REKEY_PLAN.md` §8 becomes a pointer here.
6. `tools/slurm.py:95` still forces `RPC_Host=127.0.0.1:27182` on every compute
   node; if nothing is LISTENing there, every REPL hard-errors on its first RPC
   call. A production behaviour decision, not a cleanup.
7. Getting the filter tests into a session that runs (H10).
8. **Nothing is committed.** Not one file in H14.


## H19. `no_atp` as a filter predicate — rejected, with the measurement

**Decision (user, 2026-08-21): do not introduce `no_atp` as a predicate in any
form. Keep the current facilities; ignore `no_atp` entirely.**

Two forms were on the table and both are dead:

- **Conjunctive** (H6): drop a fact when its declaring theory is marked **and**
  it carries `no_atp`. Proposed as a way to derive `Dense_Linear_Order`'s
  14-lemma keep set instead of hand-picking it.
- **Disjunctive**: keep the theory marking as it is and add `no_atp` as a second
  disjunct inside `is_infra_thm`, so either one drops a fact.

### Why the runtime test cannot be made precise

`Named_Theorems.member ctxt "HOL.no_atp" thm` is the only way to ask, and it is
`Item_Net.member` (`Pure/Tools/named_theorems.ML:53`) over `Thm.item_net`, which
is `Item_Net.init eq_thm_prop (single o Thm.full_prop_of)`
(`Pure/more_thm.ML:253`). **It matches by proposition.** The net stores thms with
no name and no provenance, so "was this tagged?" is not answerable — only "does
its statement equal something tagged?".

That distinction matters because tags come in two kinds:

- **`lemma foo[no_atp]: …`** — the author tagging their own lemma. A true signal.
- **`lemmas bar[no_atp] = x y z`** — the author tagging *other theories'*
  theorems, to keep them out of their own tactic's reach. A noise source.

Measured across the distribution and the AFP snapshot:

| | `no_atp` lines | of which `lemmas` bundles |
| --- | ---: | ---: |
| `Isabelle2025-2/src/HOL` | 404 | **43** |
| `afp-2026-05-13/thys` | 71 | **2** |

The conjunctive form survives the 45 bundles because the declaring-theory clause
filters first: `Orderings.order_refl` tests positive for `no_atp` but its theory
is not marked, so it is kept. **The disjunctive form has no such guard**, and the
casualties are concrete:

- `HOL.thy:1172` `lemmas if_splits [no_atp] = if_split if_split_asm`
  → **`if_split` and `if_split_asm` dropped store-wide.**
- `Dense_Linear_Order.thy:279`
  `lemmas dlo_simps[no_atp] = order_refl less_irrefl not_less not_le exists_neq`
  → **`order_refl`, `less_irrefl`, `not_less`, `not_le` dropped.**
- `Dense_Linear_Order.thy:298` `lemmas weak_dnf_simps[no_atp] = simp_thms dnf`
  → **all ~40 conclusions of `simp_thms` (`HOL.thy:1012`) dropped** — `not_not`,
  `eq_True`, `eq_False`, `(P ∧ True) = P`, `(∀x. P) = P`, the core of HOL
  simplification.

The user's ruling turned on `if_splits`: those must never be dropped.

### The unexplored routes, recorded so nobody re-derives them

Both would have made the predicate precise; neither was pursued once the
predicate itself was rejected.

- **An offline name list.** Parse the sources for `lemma X[…no_atp…]` and skip
  `lemmas`; the runtime test becomes name-set membership, which is exact. ~361
  own-tags in HOL, ~69 in the AFP. Cost: regeneration on every Isabelle/AFP
  bump, but stale-fails safe.
- **A name-hint set built at filter-construction time.** `Named_Theorems.get`
  yields the net's thms; ask each for `Thm.get_name_hint`. **Unverified and
  decisive if anyone revives this:** does `lemmas dlo_simps = order_refl …`
  re-stamp the hint to `Dense_Linear_Order.dlo_simps`, or keep
  `Orderings.order_refl`? Re-stamped ⇒ the runtime form is exact and needs no
  script. Kept ⇒ the hint is as useless as the proposition. A five-line probe in
  `isabelle console -l HOL -n` settles it; it was never run.

### The policy question underneath, also unresolved

`no_atp` reads `"theorems that should be filtered out by Sledgehammer"`
(`HOL.thy:811`). Sledgehammer is an automatic prover and fears over-general
facts; a proof agent retrieves facts to cite in a structured proof. `if_splits`
is the case that separates them — harmful to Sledgehammer, wanted by an agent
doing a manual case split. **"Bad for Sledgehammer" is not "not worth
retrieving", and this decision records that.** A softer option was raised and not
pursued: treat the tag as a *ranking demotion* rather than a drop. That needs
ranking changes, not filter changes.

## H20. The twelve-rule chain: every rule accounted for

**Principle (user, 2026-08-23): a name-string guess may be retired only if its
replacement asks the authoritative question the string was approximating, and
loses no coverage. Where no such question exists, the guess stays.** Not a
batch removal — one rule at a time, each with evidence.

All measurements below were run on **Isabelle2025-2** via
`contrib/Isabelle2025-2/bin/isabelle console -l SESSION -n`, no build.

| # | rule | disposition |
| --- | --- | --- |
| 1 | `concealed` | untouched — `Name_Space.is_concealed` is already authoritative |
| 2 | `hidden` | untouched — `Long_Name.is_hidden (Name_Space.intern …)` |
| 3 | `infra_theory` | → theory **long** names via `Name_Space.theory_name {long=true}` (D3/D4) |
| 4 | `internal_prefix` | split: the theory prefixes join the long-name set; **`"HOL.equal"` is a CONSTANT-name prefix and must stay a name test** — mapping it to a theory name yields `HOL.HOL` and marks all of `HOL.thy` |
| 5 | `pre_bnf_prefix` | untouched — derived from `BNF_FP_Def_Sugar.fp_sugar_of`, authoritative |
| 6 | `inst_infix` | **KEPT** (user, 2026-08-23). No authoritative query exists for "was this generated by an `instantiation` block" |
| 7 | `class_variant` | → `Sign.all_classes` + `Class.class_prefix` (approved 2026-08-19; §8.1's defect) |
| 8 | `quotient_typedef` | untouched — `Quotient_Info` + `Typedef.get_info_global`, authoritative |
| 9 | `abs_rep_name` | → `Typedef.get_info_global` over **all** types, **dropping the quotient gate** at `:278-291` — not a two-line deletion (approved 2026-08-19; §8.2's defect) |
| 10 | `adt_record` | untouched — `Ctr_Sugar`/`Record` info plus a position check |
| 11 | `class_infix` | → `Locale.specification_of` + `Locale.intros_of`, **with** `Class.is_class` (approved 2026-08-23) |
| 12 | `class_pred` | → `Logic.const_of_class` over `Sign.all_classes`, **without** `Class.is_class` (approved 2026-08-23) |

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
and only the `returns_prop` conjunct keeps it out. The enumeration cannot
produce a locale predicate at all, so it retires **two** string tests and needs
no guard.

### Rule 11 — `class_infix`, measured

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

`specification_of` alone covers only 151 of 222 in an earlier Isabelle2024 probe
— it misses the `_axioms` companions; **`intros_of` is required.**

**`Class.is_class` IS required here**, the opposite of rule 12:
`Locale.specification_of thy "HOL.type"` **raises** (`Locale.defined` is false),
because an `Axclass`-created class has no locale. Exactly one class is filtered
out in each session. The two rules need opposite treatment because they ask
different questions — "is there a class predicate constant" versus "is there a
locale generated by the `class` command".

**Empty `specification_of` results are not failures.** 36 (HOL) / 48
(MathBench_ProverBase) classes return `NONE`: parameter-only classes with
`fixes` and no `assumes` (`Groups.plus`, `Orderings.ord`,
`Real_Vector_Spaces.norm`, `Topological_Spaces.open`, `Type_Length.len0`). They
generate no predicate, and there is nothing to miss — measured:
`Sign.declared_const thy "Groups.class.plus"` is **false**. Genuine extraction
failures across all four runs: **zero**.

**The `A \ B` set is a benign substring collision, verified name by name.**
`HOL/NanoJava/Decl.thy:28` and `HOL/Bali/Decl.thy:329` each declare
`record "class" = …`, so the record's own name supplies the `class` segment:
`Decl.class.super`, `Decl.class.make`, `Decl.class.truncate`,
`Decl.class.class_ext.Abs_class_ext`, `Decl.class.typerep_class_ext_inst.…`.
For every one, the segment after `.class.` is not in the class name space
(`inClassSpace=false`, `isClass=false`). None is a class predicate. Neither
target session loads those theories, so they were brought in deliberately with
`Thy_Info.use_thy_legacy` to test the collision.

**So the change is looser, and looser in the right direction**: it stops
`class_infix` fighting `preserved_set` over record accessors, which is exactly
what `preserved_set` exists to protect. That matters because the hoist (D6)
narrows `preserved_set`'s reach — every place that stops depending on it is
decoupling. Not measured: which of those 38 names actually change status, since
`inst_infix` (position 6) and `abs_rep_name` (position 9) fire before
`class_infix` (position 11) and `preserved_set` precedes the whole chain; the
store already holds 61 distinct `Decl.class.*` names, so most of the family
survives today. The instrumentation answers this exactly.

### Consequence for the narrow-cascade proposal (H6)

After rules 7, 9, 11 and 12 are replaced, the only guesses left that can feed the
cascade are `inst_infix` (kept, no replacement exists) and the `"HOL.equal"` half
of `internal_prefix`. The proposal's whole evidential basis was that the cascade
propagates the errors of `class_variant` and `abs_rep_name` — both now fixed.
**Revisit only if the step-1 measurement shows `inst_infix` driving a
significant share of cascade rejections.**

### Method notes for whoever runs more of these

- `isabelle console -n` gives the **Pure** ML environment: `HOLogic` is absent
  (`Structure (HOLogic) has not been declared`) — strip `Trueprop` inline
  instead. `PolyML.print_depth` is absent too; use
  `ML_Print_Depth.set_print_depth 0`.
- In the `HOL` heap `Thy_Info.get_theory "HOL.Main"` **fails** — `Main` and
  `Complex_Main` are registered unqualified. Select from `Thy_Info.get_names ()`
  by base name.
- `MathBench_ProverBase` loads in ~14 s, not minutes.
- `Thy_Info.use_thy_legacy` loads a theory into a live console in well under a
  second — this is how out-of-session material is brought into scope without a
  build, and it is the likely unblock for step 1's "no heap has both
  `HOL-Decision_Procs` and `Infra_Filter`" problem.
