# Verification for direction A (use the equational `Spec_Rules` item as a `fun` constant's defining axioms)

All measurements below were taken on Isabelle2025-2, session `Semantic_Embedding`, through an
Isa-REPL server on `127.0.0.1:6703` started with `repl_server.sh` (no `isabelle build` was run).
Probe theories and raw output live in
`/tmp/claude-1002/-home-qiyuan-Current-MLML/8ee4dc8b-0295-46df-b280-a85bcc774433/scratchpad/fun_verify/`
(`Fun_Probe_A.thy`, `Fun_Probe.thy`, `P2_A/B/C/D.thy`, `P3.thy`, `P4.thy`, `P5.thy`,
`P6_A.thy`, `P6.thy`, `P7.thy`, `galA/Gal_Probe.thy`, `galB/Gal_Probe.thy`; outputs
`probe_out.txt`, `probe2_out.txt` … `probe7_out.txt`, `gal_A.txt`, `gal_B.txt`,
`recdef_consts.txt`).  Nothing in the repository was modified except this file.

One thing asked for could **not** be measured: the isolated store copy named in the brief,
`/var/tmp/qiyuan/gate_accept_db/`, **no longer exists** (only `/var/tmp/qiyuan/gate_accept_logs/`
survives, and there is no other LMDB copy anywhere under `/var/tmp`).  Recreating it would mean
reading the production store, which the brief forbids, so item 5(b) is reported as *not measured*
and a heap-side proxy is given instead.  See §5.

---

## 1. Trigger criterion: which commands produce `Equational Recdef`

### The datatype

`contrib/Isabelle2025-2/src/Pure/Isar/spec_rules.ML:11-13` and `:20`:

```
datatype recursion =
  Primrec of string list | Recdef | Primcorec of string list | Corec | Unknown_Recursion
datatype rough_classification = Equational of recursion | Inductive | Co_Inductive | Unknown
```

Both datatypes are declared **inside the signature `SPEC_RULES`** (`spec_rules.ML:11-12` and
`:18`), so their constructors are exported and client code may pattern-match them directly.
`val is_equational: rough_classification -> bool` (`:26`) collapses all five recursion shapes into
one boolean and is therefore *not* enough on its own, but it is not the only route: I compiled and
ran

```ml
val is_recdef = fn Spec_Rules.Equational Spec_Rules.Recdef => true | _ => false;
```

in every probe theory (e.g. `P2_D.thy`, `P3.thy`), and it works.  **No new export is needed** —
`own_defining_axioms` can test the classification by pattern-matching the exported datatype.

### Who produces `equational_recdef`

`grep -rn "equational_recdef"` over `contrib/Isabelle2025-2/src/` and
`contrib/afp-2026-05-13/thys/` (excluding `spec_rules.ML` itself) returns exactly five sites:

| file:line | command | binding passed | rules passed |
|---|---|---|---|
| `src/HOL/Tools/Function/function.ML:217` | `function` / `fun`, in the `afterqed` of the **termination** proof | `Binding.empty` (→ name `""`) | `tsimps` (the total simps) |
| `src/HOL/Tools/Function/partial_function.ML:304` | `partial_function (…)` | `Binding.empty` | `[rec_rule']`, the single unfolding equation |
| `src/HOL/Library/old_recdef.ML:2838` | the deprecated `recdef` (HOL-Library `Old_Recdef`) | `Binding.name bname` (→ **non-empty** name) | `flat rules` |
| `afp-2026-05-13/thys/Partial_Function_MR/partial_function_mr.ML:317` | `partial_function_mr` | `Binding.empty` | `simps` |
| `afp-2026-05-13/thys/Nominal2/nominal_termination.ML:69` | Nominal2's `nominal_termination` | `Binding.empty` | `tsimps` |

So "classification is `Equational Recdef`" is **not** exactly "function package + `partial_function`":
three further producers exist, one of them in the Isabelle distribution (`recdef`) and two in the
AFP.  All five produce *equational rules for the constant named in `terms`*, which is what direction
A wants, so the extra producers are not a correctness problem — but the empty-name assumption is not
universal: `old_recdef.ML` gives its item a real name.

Measured on the `Semantic_Embedding` heap (88 theories, `P2_D.thy` census): of the 40 recdef items
found, **0 have a non-empty name** — `Old_Recdef` is not loaded in this session.

### Other classifications, measured (probe `Fun_Probe.thy`)

| command | classification of the item(s) | item name |
|---|---|---|
| `fun` / `function` (after `termination`) | `Equational(Recdef)` | `""` |
| `partial_function (option)` / `(tailrec)` | `Equational(Recdef)` | `""` |
| `primrec` | `Equational(Primrec [List.list])` | `Fun_Probe.pr_len` |
| `primcorec` | two items: `Equational(Primcorec [Fun_Probe.strem])` **and** `Equational(Unknown_Recursion)` | both `""` |
| `definition` | `Equational(Unknown_Recursion)` | `Fun_Probe.mulgrav_def` |
| `inductive` | `Inductive` | `Fun_Probe.zeldip` |
| `datatype`-generated (`case_*`, `rec_*`, `size_*`, `equal_*`, …) | `Equational(Unknown_Recursion)` | mixed |
| function-package auxiliaries `f_graph`, `f_rel` | `Inductive` | `Fun_Probe.narquil_graph` etc. |

---

## 2. Which definitional commands are body-free in `Defs`

Probe `Fun_Probe.thy` (imports `Fun_Probe_A` imports `Main`); for each constant it printed every
`Defs.specifications_of` entry with its resolved proposition, and every `Spec_Rules.get_global` item
whose `terms` or `rules` mention the constant.  Raw output: `probe_out.txt`.

| # | command | `Defs` axiom (proposition) | body in Defs? | recdef item? |
|---|---|---|---|---|
| 1 | `fun narquil` (unary) | `narquil ≡ narquil_sumC` | **no** | yes, 1 rule |
| 2 | `fun zelmor` (binary) | `zelmor ≡ λx0 x1. zelmor_sumC (x0, x1)` | **no** | yes, 2 rules |
| 3 | `fun pevin and qevin` (mutual) | `pevin ≡ λx0. pevin_qevin_sumC (Inl x0)` / `qevin ≡ … (Inr x0)` | **no** | yes, **one shared item**, `terms = [pevin, qevin]`, 4 rules |
| 4 | `function (domintros) vurnak`, **before** `termination` | `vurnak ≡ vurnak_sumC` | **no** | **NO ITEM AT ALL (0)** |
| 4′ | the same constant **after** `termination vurnak by …` | unchanged | **no** | yes, 1 rule |
| 5 | `function tarvox` + `termination` | `tarvox ≡ λx0 x1. tarvox_sumC (x0, x1)` | **no** | yes, 2 rules |
| 6 | `function (sequential) kraldo` + `termination by lexicographic_order` | `kraldo ≡ λx0 x1. kraldo_sumC (x0, x1)` | **no** | yes, 3 rules (the disambiguated ones: `kraldo (Suc ?v) 0 = 1`, …) |
| 7 | `fun plus_wobix` inside `instantiation wobix :: plus` | for `Groups.plus_class.plus`: 10 instance axioms, the new one `Fun_Probe.plus_wobix_inst.plus_wobix_def : (+) ≡ plus_wobix_inst.plus_wobix`.  For the instance constant `Fun_Probe.plus_wobix_inst.plus_wobix` itself (probe `P6.thy`): `plus_wobix_inst.plus_wobix ≡ λx0 x1. plus_wobix_sumC (x0, x1)` | **no** | the item's `terms` is `(+)` = `Groups.plus_class.plus`; the instance constant `plus_wobix_inst.plus_wobix` appears in **no** item |
| 8 | `fun dworl_wobix` under `overloading dworl_wobix ≡ "dworl :: wobix ⇒ nat"`, `dworl` declared by `consts` in the **parent** theory | for `Fun_Probe_A.dworl`: `Fun_Probe.dworl_wobix_def : dworl ≡ dworl_wobix_sumC` | **no** | yes — an item **in `Fun_Probe`** whose `terms` names `Fun_Probe_A.dworl` |
| 9 | `partial_function (option) hovrik` | `Fun_Probe.hovrik ≡ option.fixp_fun (λhovrik n. if n = 0 then Some 0 else hovrik (n - 1))` | **YES** | yes, 1 rule |
| 9′ | `partial_function (tailrec) jemlok` | `Fun_Probe.jemlok ≡ tailrec.fixp_fun (λjemlok n. …)` | **YES** | yes, 1 rule |
| 10 | `primrec pr_len` | `pr_len ≡ rec_list 0 (λx xs. Suc)` | **YES** (via the recursor arguments) | primrec item, not recdef |
| 11 | `primcorec sconst` | `sconst ≡ corec_strem (λx. x) (λx. False) (λx. undefined) (λx. x)` | **YES** | primcorec + unknown items, not recdef |
| 12 | `definition mulgrav` | `Fun_Probe.mulgrav_def_raw : mulgrav ≡ λn. n + 3` | **YES** | unknown-recursion item |
| 13 | `abbreviation tylvin` | **0 Defs entries** (probe `P7.thy`); handled by the existing `Consts.the_abbreviation` branch | n/a | no |
| 14 | `inductive zeldip` | `zeldip ≡ lfp (λp x. x = 0 ∨ (∃n. x = Suc (Suc n) ∧ p n))` | **YES** | inductive item |
| 15 | `fun rosy_size` with nested/higher-order recursion (`map rosy_size ts`) | `rosy_size ≡ rosy_size_sumC` | **no** | yes, 1 rule `rosy_size (Node ?ts) = Suc (sum_list (map rosy_size ?ts))` |

**When is the item added for `function`?**  `function.ML:180-221` places the
`Spec_Rules.add Binding.empty Spec_Rules.equational_recdef fs tsimps` (`:217`) inside
`afterqed` of `prepare_termination_proof`, i.e. it runs only when the **termination** proof
succeeds, and it registers `tsimps` (the psimps with the domain condition simplified away by
`remove_domain_condition`, `:194-196`), never the psimps.  Measured (row 4/4′): before
`termination`, `Spec_Rules` has **zero** items for `vurnak`; after, exactly one.

**Conclusion for item 2.** The body-free-in-`Defs` family is exactly the **function package**
(`fun`, `function`, in every variant I tried — unary, binary, mutual, `(sequential)`, `(domintros)`,
nested recursion, inside `instantiation`, under `overloading`).  `partial_function`, `primrec`,
`primcorec`, `definition` and `inductive` all carry their body in the `Defs` axiom.
`abbreviation` has no `Defs` entry at all and is already covered.

---

## 3. Theory membership for empty-name items

### `#pos`

For every item in `Fun_Probe`, `Position.file_of` returned the **absolute path of the loaded `.thy`
file**, and for items inherited from the heap it returned the distribution's abbreviated path, e.g.
`~~/src/HOL/Factorial.thy`, `~~/src/HOL/Quickcheck_Exhaustive.thy`.  `Position.id_of` returned small
integers (`258` for everything declared in `Fun_Probe`, `156` for a `Factorial` item, `184` for a
`Quickcheck_Exhaustive` item) — these are command/exec ids, not theory identities; every item
declared by the same REPL load shares one.  `Position.line_of`/`offset_of` are present.
`Pure/General/position.ML` has **no** `theory_of`.

So `pos` identifies a *file*, not a theory, and recovering a theory long name from a path would mean
re-implementing the theory-path resolution.  I do not recommend it.

### Is "the constant is a member of `#terms`" a sound same-theory criterion?

**No.**  Probe `P6.thy` builds the counterexample directly:

```
=== P6_A.dworl
  declaring theory      : P6_A
  class_param_of        : NONE
  own_defining_axioms   : 0                      <- today: name+type digest only
  dirA member-criterion : 2
      dworl (Wob ?a) = ?a
      dworl (Bix ?a) = Suc ?a                    <- rules from the CHILD theory P6
  dirA dest_theory-crit : 0
```

`dworl` is declared by `consts` in `P6_A`; `P6` overloads it for `wobix` with a `fun`.  The recdef
item lives in `P6` and its `terms` names `P6_A.dworl`.  Membership in `#terms` would therefore make
an **upstream** constant's digest move whenever a **downstream** theory adds an overloading — exactly
the failure mode the existing same-theory filter was written to prevent (`semantic_digest.ML:270-278`).

### The class-parameter case

Also measured in `P6.thy`:

```
=== Groups.plus_class.plus
  class_param_of        : Groups.plus
  own_defining_axioms   : 0
  dirA member-criterion : 4     (Wob ?a + Wob ?b = Wob (?a + ?b), …)
  dirA dest_theory-crit : 0
```

`class_param_of` (`semantic_digest.ML:336`, `Axclass.class_of_param`) **does** short-circuit it —
but only because `own_defining_axioms` tests it **first** (`:389`).  If direction A were wired in
ahead of that test, `plus` would absorb every downstream instance's `fun` equations.  Measured on
the real heap (probe `P3.thy`): the six recdef constants that are class parameters
(`Bit_Operations.semiring_bit_operations_class.{and,or,xor}`,
`Lazy_Sequence.small_lazy_class.small_lazy`,
`Quickcheck_Exhaustive.{exhaustive_class.exhaustive, full_exhaustive_class.full_exhaustive}`) all
keep an unchanged digest under direction A precisely because the class-parameter test fires first.

### The plain `overloading` case (no class involved)

`P6_A.dworl` above: `class_param_of` is `NONE`, so nothing protects it.  Today its digest is
name+type only (`own_defining_axioms = 0`), because `same_theory` rejects
`P6.dworl_wobix_def` against `P6_A.dworl`.  Under a membership-only direction A it would silently
pick up `P6`'s equations.

### The instance constant itself

`P6.plus_wobix_inst.plus_wobix` *is* a real constant (`Consts.the_constraint` succeeds) declared in
`P6`, its `Defs` axiom is body-free (`≡ λx0 x1. plus_wobix_sumC (x0, x1)`), and it appears in **no**
`Spec_Rules` item at all — the item's `terms` carries `(+)` instead.  So a `fun` inside
`instantiation` stays a limitation-#6 case under either criterion.  This costs nothing in practice:
probe `P7.thy` shows such constants are dropped by the infrastructure filter —
`Nat.plus_nat_inst.plus_nat`, `String.plus_literal_inst.plus_literal`,
`Nat.ord_nat_inst.less_eq_nat`, `List.equal_list_inst.equal_list` are all
`Infra("inst_infix")`, i.e. they never get a store record or an interpretation.

### A sound criterion that works: `Spec_Rules.dest_theory`

`Spec_Rules.dest_theory thy` (`spec_rules.ML:145`) returns the items declared **in `thy` itself**,
filtering out everything already present in any parent (`get_generic (Theory.parents_of thy)`,
`:135-143`).  Used as "the item must be in `dest_theory (theory that declares the constant)`", it
gives 0 for `P6_A.dworl` and for `Groups.plus_class.plus` (rows above) and the right rules for every
ordinary `fun`.

**Merge behaviour** (probe `P2_D.thy`): `P2_B` and `P2_C` each import `P2_A` and each define one
`fun`; `P2_D` imports both.  In `P2_D`, `Spec_Rules.get_global` sees all three items (1 for
`P2_A.ancfun`, 1 for `P2_B.bfun`, 1 for `P2_C.cfun`) — `Item_Net.merge` keeps them — while
`Spec_Rules.dest_theory P2_D` returns **0**, and `dest_theory P2_B` / `dest_theory P2_C` each return
their own single item.  So the criterion survives a diamond merge.

**Cost** (probe `P5.thy`): `dest_theory` over all 88 heap theories = **1343 items in 0.016 s**
elapsed; `dest_theory HOL.List` alone = 134 items in 0.003 s; `get_global` on the leaf = 1343 items
in 0.002 s.  Today's `spec_rule_axioms` already scans all 1343 items per constant, so a
per-theory-memoised `dest_theory` is not a regression.

### Empirical cross-theory rate on the real heap

Probe `P2_D.thy` checked, for every recdef item in every one of the 88 heap theories, whether any
constant in its `terms` is declared in a different theory:

```
### recdef items whose theory <> the const's declaring theory: 0
```

So the unsound membership criterion happens to agree with the sound one **everywhere in this heap**;
the divergence is constructible (`P6`) but does not occur in HOL + Isabelle_RPC +
Performant_Isabelle_ML.

---

## 4. Digest stability under cosmetic edits

### How the digest normalises (`Tools/semantic_digest.ML:117-176`)

`normalize` renames by first occurrence, threading one counter through types and terms:
`TFree`/`TVar` → `'z<i>`, `Free` → `z<i>`, `Var ((a,j),T)` → `Var (("z<i>",0),T)` (so **both the
name and the index of a schematic variable are erased**), and `Abs (_, T, body)` → `Abs ("", T, body)`
(binder names erased; de Bruijn indices carry the binding).  Types are kept structurally; only the
*names* of type variables are canonicalised.  `digest_term = Term_Digest.term128 o normalize`
(`:176`).

`sem_constant` (`:413-452`) builds one payload term
`fold (fn p => fn acc => tagged "def" p $ acc) props (tagged "const" (Const (name, T)) $ cls_payload $ abbrev_payload)`
and digests that — so the **props' order is part of the digest**, and the constant's own name and
declared type are in it.

I re-implemented that payload construction in probe `P3.thy` and checked it against the real
`Semantic_Digest.semantics_of` on 46 constants: **46/46 identical hex digests, 0 mismatches**.  Every
"direction A" digest quoted below therefore comes from a verified-faithful simulation.

### The `galmuth` measurement

`diff ai-artifacts/similarity_measurement/Sim_Measure_A1.thy Sim_Measure_B.thy` shows, for `galmuth`,
exactly this change (the file's "cosmetic" grade):

```
<   "galmuth [] = 0"
< | "galmuth (x # xs) = (if x mod 2 = 0 then x + galmuth xs else galmuth xs)"
---
>   "galmuth (a # as) = (if a mod 2 = 0 then a + galmuth as else galmuth as)"
> | "galmuth [] = 0"
```

i.e. pattern variables `x, xs` renamed to `a, as` **and** the two clauses swapped.

The two `Sim_Measure_*` theories have different theory names, so their constants have different long
names and their digests differ for a trivial reason.  To measure the real thing I built two copies of
one theory `Gal_Probe` (`galA/`, `galB/`), identical except for the edits, and loaded each into a
**freshly restarted** REPL server so the theory name was identical in both runs.  Results
(`gal_A.txt`, `gal_B.txt`):

| constant | edit | digest today | digest under direction A |
|---|---|---|---|
| `Gal_Probe.galmuth` | `x,xs` → `a,as` + clauses swapped | `5d6361e1cf80a3ee4e89bb4d96f85578` (A) = `5d6361e1cf80a3ee4e89bb4d96f85578` (B) | `c52ee61575690c9a84e219c903239d45` (A) = `c52ee61575690c9a84e219c903239d45` (B) → **UNCHANGED** |
| `Gal_Probe.narquil` | `n < 5` → `n ≤ 5` | `03f86a41757560c23067056a02393dee` both — **blind today** | `296e82bbc791bf7d0c86fd14465d4a88` (A) vs `6e78fdeed5e0965cd14ac8320b602e20` (B) → **CHANGED**, as required |
| `Gal_Probe.dkol` (`definition`) | `dkol m n = m*n+1` → `dkol p q = p*q+1` | `03bcf1e07f7e95843c968d215578a479` both (the `Defs` axiom is closed, `≡ λm n. …` / `≡ λp q. …`, and `normalize` erases `Abs` binder names) | same |

So direction A gives the wanted behaviour on both sides: the cosmetic rename-plus-reorder does
**not** move `galmuth`'s digest, and the semantic edit `< 5` → `≤ 5` **does** move `narquil`'s
digest (which today is invisible — limitation #6).  The clause reorder is absorbed because
`own_defining_axioms` sorts the props (`semantic_digest.ML:377-379`), and schematic names are erased
by `normalize`.

### One latent instability in the sort key (recommend fixing if direction A lands)

The props are sorted by `Term_Ord.term_ord` on the **raw** term, and that order **is** sensitive to
schematic-variable names: `term_ord.ML:157-158` compares heads with
`prod_ord (prod_ord indexname_ord typ_ord) int_ord (dest_hd f, dest_hd g)`, and `indexname_ord`
compares the name string.  Demonstrated in probe `P5.thy` on two synthetic prop lists that are
alpha-variants of each other:

```
term_ord (f ?a ?b = ?a , f ?a ?b = ?b) = LESS
term_ord (f ?z ?b = ?z , f ?z ?b = ?b) = GREATER
digest of sorted [p1,p2] = dc0a8b54ba98e66ab780d7d0b833a3fd
digest of sorted [q1,q2] = 9e5cf95645bec17361ddb392b64fbd4d
```

I did **not** manage to produce this from a real `fun`: two clauses of one `fun` cannot be
alpha-variants of one another (they would be non-confluent), and in the `galmuth` case the order came
out the same in both variants.  So this is a latent risk, not an observed defect.  It is removed for
free by sorting the **normalised** props (`sort Term_Ord.term_ord (map Semantic_Digest.normalize props)`)
instead of the raw ones — note this would move the digest of anything that has more than one prop
today, so it is a change to make *together with* direction A, not afterwards.

---

## 5. One-time cost

### (a) Heap-side census — measured

Probe `P2_D.thy` walked `Semantic_Embedding :: Theory.ancestors_of` (**88 theories**: HOL,
`Isabelle_RPC`, `Performant_Isabelle_ML`, `Semantic_Embedding`) and counted, per theory,
`Spec_Rules.dest_theory` items with classification `Equational Recdef`:

```
total recdef items: 40      distinct constants in their #terms: 40
recdef items with a non-empty name: 0
recdef items whose theory <> the const's declaring theory: 0
```

| theory | items | constants |
|---|---|---|
| `HOL.Quickcheck_Exhaustive` | 12 | 12 |
| `HOL.Bit_Operations` | 10 | 10 |
| `HOL.List` | 10 | 10 |
| `HOL.Lazy_Sequence` | 3 | 3 |
| `HOL.Random` | 2 | 2 |
| `HOL.Quickcheck_Random` | 1 | 1 |
| `HOL.Predicate` | 1 | 1 |
| `HOL.Set_Interval` | 1 | 1 |

All 40 are function-package constants (their `Defs` axiom is `… ≡ …_sumC …`, or, for
`Bit_Operations.linordered_euclidean_semiring_bit_operations_class.or_num`, the class-operation alias
`or_num ≡ linordered_euclidean_semiring_bit_operations.or_num`).  **No `partial_function` constant
exists in this heap** — none of the 40 has a `fixp_fun` body.

Probe `P3.thy` then computed, per constant, today's digest and the direction-A digest:

* **34 of 40 change**, 6 do not.
* The 6 that do not are exactly the 6 class parameters, protected by `class_param_of`.

### (b) How many have a store record — NOT MEASURED

The isolated copy `/var/tmp/qiyuan/gate_accept_db/` named in the brief does not exist any more
(`ls` fails; `find /var/tmp -name '*.lmdb'` finds nothing; only
`/var/tmp/qiyuan/gate_accept_logs/` with `gate_inspect.py`, `gate_dry_run.py` and the run logs
survives).  Recreating it would require reading the production store at
`~/.cache/Isabelle_Semantic_Embedding/`, which the brief forbids, so I did not.
**To finish this item, say whether I may re-copy the production store to
`/var/tmp/qiyuan/gate_accept_db/` (read-only `Environment.copy` of `semantics.lmdb` and
`theory_hash.lmdb`, as `REPORT.md` §"Database isolation" describes), or point me at another copy.**

### (b′) Heap-side proxy that *was* measured

Probe `P4.thy` asked `Infra_Filter.gen_infra_filters`, which is what decides whether a constant gets
a record and an interpretation at all:

* `Infra_Filter.is_marked_theory`: `HOL.Quickcheck_Exhaustive`, `HOL.Quickcheck_Random`,
  `HOL.Lazy_Sequence` are **marked** (infrastructure); `HOL.Bit_Operations`, `HOL.List`,
  `HOL.Set_Interval`, `HOL.Random`, `HOL.Predicate` are not.
* Verdicts on the 40: **23 `Kept`**, 16 `Infra("infra_theory")`,
  1 `Infra("class_variant")`
  (`Bit_Operations.linordered_euclidean_semiring_bit_operations.or_num`, the locale-level twin).
* Intersecting "`Kept`" with "digest changes": **20 constants**, in 5 theories:

| theory | count | constants |
|---|---|---|
| `HOL.List` | 10 | `arg_min_list`, `min_list`, `remdups_adj`, `shuffles`, `sorted_wrt`, `splice`, `successively`, `trancl_list`, `transpose`, `upto` |
| `HOL.Bit_Operations` | 6 | `and_not_num`, `and_num`, `fold2_bit_int.F`, `linordered_euclidean_semiring_bit_operations_class.or_num`, `or_not_num_neg`, `xor_num` |
| `HOL.Random` | 2 | `iterate`, `log` |
| `HOL.Predicate` | 1 | `iterate_upto` |
| `HOL.Set_Interval` | 1 | `fold_atLeastAtMost_nat` |

So, **for the theories this session's heap reaches**, direction A makes at most 20 constants into
seeds — 20 LLM interpretations plus their gate calls, plus whatever the gate decides to propagate.
Whether the production store actually holds records for those 20 is the unmeasured part (b).

**Not measured:** anything beyond these 88 theories.  The store is reported (memory note) to cover
~142 theories; theories outside this heap were not loaded and not counted.

---

## 6. Anything else that would break direction A

**(a) Constants with BOTH a body-carrying `Defs` axiom and a recdef item — real, but only for
`partial_function`.**  Measured (`probe_out.txt`, rows 9/9′): `hovrik`'s `Defs` axiom is
`hovrik ≡ option.fixp_fun (λhovrik n. if n = 0 then Some 0 else hovrik (n - 1))` **and** it has a
recdef item with the rule `hovrik ?n = (if ?n = 0 then Some 0 else hovrik (?n - 1))`.  If direction A
*adds* the recdef rules to the `Defs` axioms, such a constant carries the same content twice (bigger
payload, duplicate dependency edges, and its digest moves for no gain).  If direction A *replaces*
the `Defs` axioms when a recdef item is present, no double counting occurs — but `partial_function`
constants' digests move once too.  Restricting direction A to the case "the `Defs` axioms are all
body-free" is not directly testable; restricting it to "a recdef item exists" catches
`partial_function` as well.  No `partial_function` constant exists in this heap, so in this heap the
choice is free.

**(b) Mutual blocks: each constant gets the whole block's equations, creating a dependency cycle.**
Measured (`probe_out.txt`, row 3): `fun pevin and qevin` produces **one** item with
`terms = [pevin, qevin]` and all four equations.  Under direction A, `pevin`'s props would be all
four equations — including `qevin (Suc ?n) = pevin ?n` — so `pevin` gains a dependency edge to
`qevin` and vice versa: a two-node SCC inside one theory.  Today the `Defs` axioms
(`pevin ≡ λx0. pevin_qevin_sumC (Inl x0)`) create no such edge.  This is **tolerated by design**:
`Isabelle_Semantic_Embedding/semantic_interpretation.py:1091-1110` (`_EffStar`) evaluates eff* by
"iterative Tarjan DFS", explicitly states "Folding a cycle to a max is lossless for INTRA-SCC signal
(SCC members are defined by one command and bump together)", and finalises memos SCC-wide; the
enrolment graph at `:1734-1740` skips only the self-edge (`j != i`).  Worth noting as a consequence,
not a blocker.  Side effect: both constants of a mutual block get an identical prop set, so their
digests differ only through the `Const (name, T)` head of the payload — which is present
(`semantic_digest.ML:442`), so they do not collide.

**(c) `fun` inside a `class` body produces rules carrying the class predicate.**  Measured
(`probe3_out.txt`): `Bit_Operations.linordered_euclidean_semiring_bit_operations.or_num` has 9 rules,
each of the form
`class.linordered_euclidean_semiring_bit_operations ?plus ?minus … ?less ⟹ …or_num num.One num.One = num.One`,
mentioning all 22 class parameters.  That would add 22 dependency edges and a very large payload.
It is `Infra("class_variant")` so it never gets a record — but the same shape would appear for any
locale-level `fun` twin that *is* kept.  The `_class.`-qualified sibling
(`…_class.or_num`) gets the clean premise-free rules.

**(d) Nested / higher-order recursion is fine.**  `fun rosy_size` over `datatype rosy = Node "rosy list"`
gives the item rule `rosy_size (Node ?ts) = Suc (sum_list (map rosy_size ?ts))` — the equation, with
`sum_list`/`map` as new dependency edges.  No `_sumC` leakage.

**(e) `(domintros)` makes no difference.**  Measured: `function (domintros) vurnak` produces exactly
the same single recdef item after `termination` as a plain `function`.  The `domintros` theorems do
not enter `Spec_Rules`.

**(f) psimps never reach the digest.**  A `function` whose `termination` is unproved registers **no**
`Spec_Rules` item at all (measured, row 4), because the registration is inside the termination
`afterqed`.  Under direction A such a constant keeps today's body-free `Defs` axiom, i.e. limitation
#6 survives for partial functions defined by `function` without `termination`.  This is the correct
outcome (the psimps carry an unresolved `f_dom` premise), but it should be stated as a remaining gap.

**(g) `Item_Net` merge keeps the items.**  Measured in `P2_D.thy` (diamond `P2_A ← P2_B, P2_C ← P2_D`):
`get_global` in `P2_D` sees all three parents' items; `dest_theory P2_D` sees none.  No loss, no
duplication.

**(h) `Old_Recdef`'s items have a non-empty name.**  `old_recdef.ML:2838` passes `Binding.name bname`,
so a `recdef`-defined constant's item name *would* pass the existing `same_theory` filter on its own.
Not loaded in this heap (0 named recdef items measured), but any rule that assumes `name = ""` for
recdef items is wrong in general.

**(i) The existing `spec_rule_axioms` fall-back would double-fire.**  `own_defining_axioms`
(`semantic_digest.ML:387-402`) calls `spec_rule_axioms` only when `from_defs` is empty.  For a `fun`
constant `from_defs` is non-empty (the body-free axiom), so the fall-back never runs today.  Direction
A must therefore be a new branch, not a tweak of the fall-back condition.

---

## Recommendation (for you to decide, not a decision)

I would state the rule for `own_defining_axioms` as follows.  Keep the current first test
untouched — `if is_some (class_param_of env const_name) then []` — because it is the only thing that
stops a downstream `instantiation … fun …` from being attributed to an upstream class parameter
(measured: `Groups.plus_class.plus` would otherwise absorb 4 foreign equations).  Then, **before**
consulting `Defs`, look for an *equational-recursive* `Spec_Rules` item — that is, one whose
`rough_classification` pattern-matches `Spec_Rules.Equational Spec_Rules.Recdef`, which the exported
datatype permits without any change to Isabelle — among the items returned by
`Spec_Rules.dest_theory T`, where `T` is the theory value whose long name equals the constant's own
declaring theory (from `Name_Space.the_entry` on the constant space, i.e. the same theory notion
`same_theory` already uses), memoising `dest_theory` per theory in `env` (the whole 88-theory heap
costs 16 ms, so the memo is cheap).  Among those items keep the ones whose `#terms` mention the
constant, and take **`#rules`, replacing the `Defs` axioms entirely** rather than adding to them, so
that the one constant family which has both a body-carrying `Defs` axiom and a recdef item
(`partial_function`) is not counted twice; if you would rather leave `partial_function` exactly as it
is today, the trigger can be narrowed further by requiring that every `Defs` axiom of the constant be
body-free, though I have no cheap syntactic test for that and would not add one.  Fall back to
today's `Defs` path, and then to `spec_rule_axioms`, whenever no such item is found — which keeps
`function`-without-`termination`, `primrec`, `primcorec`, `definition`, `inductive` and
`abbreviation` bit-for-bit unchanged (measured: 6 control constants, all digests identical).
Two riders: use `Spec_Rules.dest_theory`, **not** membership in `#terms` alone, as the theory test —
the `overloading` construction in `P6.thy` shows membership lets a child theory rewrite a parent
constant's digest, even though that never happens in the current heap (0 offenders in 88 theories);
and sort the props **after** `normalize`, since `Term_Ord.term_ord` compares schematic-variable names
(demonstrated in `P5.thy`) and the payload is order-sensitive.  The measured one-time price in this
heap is 20 constants across `HOL.List` (10), `HOL.Bit_Operations` (6), `HOL.Random` (2),
`HOL.Predicate` (1) and `HOL.Set_Interval` (1); how many of those actually hold a store record is the
one thing I could not check, because the isolated database copy the brief names has been deleted.
