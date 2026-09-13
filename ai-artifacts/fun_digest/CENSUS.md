# Census: what `Function_Common.retrieve_function_data` returns, measured

Measured 2026-09-13 on the real Isabelle2025-2 system, through an Isa-REPL server
on the `Semantic_Embedding` session heap (`repl_server.sh 127.0.0.1:6705
Semantic_Embedding`).  Probe theories live outside the repository, in
`/tmp/claude-1002/-home-qiyuan-Current-MLML/8ee4dc8b-.../scratchpad/fun_census/`
(`FunCensus.thy` … `FunCensus4.thy`, raw output `out_*.txt`).  Nothing in the
repository was built, edited or rebuilt; no `isabelle build` was issued beyond
the one `repl_server.sh` runs itself to start the REPL.

Every query has exactly the production shape the plan prescribes:

```ML
val ctxt = Proof_Context.init_global thy          (* thy DECLARES the constant *)
val T    = Consts.the_constraint (Sign.consts_of thy) c
val res  = Function_Common.retrieve_function_data ctxt (Const (c, T))
```

and every `own_defining_axioms` figure is today's code, `Semantic_Digest.make_env
thy` followed by `Semantic_Digest.own_defining_axioms env c`, with the same `thy`.

Terms are printed with `Syntax.string_of_term` cleaned through `XML.content_of
(YXML.parse_body …)`.  The printer emits Isabelle's ASCII symbol spellings; in
this report `\<equiv>`, `\<Rightarrow>` and `\<Longrightarrow>` have been rendered
as `≡`, `⇒` and `⟹` and nothing else was changed.

---

## (a) Theory-level `fun` and `function`

Subjects declared in the probe theory `FunCensus` (which imports
`Semantic_Embedding`); the env is `Proof_Context.init_global` of `FunCensus`
itself.  Raw output: `out_a.txt`.

```isabelle
fun pa_narq :: "nat ⇒ nat" where
  "pa_narq 0 = 0"
| "pa_narq (Suc n) = (if n < 3 then Suc n else pa_narq n)"

function pb_vurn :: "nat ⇒ nat" where
  "pb_vurn n = (if n = 0 then 0 else pb_vurn (n - 1))"
  by pat_completeness auto              (* NO termination *)

function pc_tarv :: "nat ⇒ nat ⇒ nat" where
  "pc_tarv 0 m = m"
| "pc_tarv (Suc n) m = pc_tarv n (Suc m)"
  by pat_completeness auto
termination by lexicographic_order
```

### `FunCensus.pa_narq` — `fun`

* entries returned: **1**
* `own_defining_axioms` today: **1** — `[FunCensus.pa_narq_def] pa_narq ≡ pa_narq_sumC`
* entry 1: key `pa_narq`, key head `Const FunCensus.pa_narq` (= the queried constant)
* `#fs` = `[pa_narq]`; `is_partial = false`; `simps = SOME` (2 thms)
* chosen rules (`simps`, 2):

```
pa_narq 0 = 0
pa_narq (Suc ?n) = (if ?n < 3 then Suc ?n else pa_narq ?n)
```

### `FunCensus.pb_vurn` — `function` without `termination`

* entries returned: **1**
* `own_defining_axioms` today: **1** — `[FunCensus.pb_vurn_def] pb_vurn ≡ pb_vurn_sumC`
* entry 1: key `pb_vurn`, key head `Const FunCensus.pb_vurn` (= the queried constant)
* `#fs` = `[pb_vurn]`; `is_partial = **true**`; `simps = **NONE**`
* chosen rules (`psimps`, 1):

```
pb_vurn_dom ?n ⟹ pb_vurn ?n = (if ?n = 0 then 0 else pb_vurn (?n - 1))
```

(`pb_vurn_dom` is the printed form of `Wellfounded.accp pb_vurn_rel`; the
abbreviation is folded back by the pretty printer, the certified term contains
`accp` and the concealed relation constant.)

So a `function` without `termination` **does** have a registry entry — unlike
`Spec_Rules`, which has no item at all before `termination` (VERIFICATION.md §2,
row 4).  This is the substantive difference between the two sources at this
shape.

### `FunCensus.pc_tarv` — `function` + `termination`

* entries returned: **1**
* `own_defining_axioms` today: **1** — `[FunCensus.pc_tarv_def] pc_tarv ≡ λx0 x1. pc_tarv_sumC (x0, x1)`
* entry 1: key `pc_tarv`, key head `Const FunCensus.pc_tarv` (= the queried constant)
* `#fs` = `[pc_tarv]`; `is_partial = false`; `simps = SOME` (2 thms)
* chosen rules (`simps`, 2):

```
pc_tarv 0 ?m = ?m
pc_tarv (Suc ?n) ?m = pc_tarv ?n (Suc ?m)
```

---

## (b) The shipped locale-target case: `Bit_Operations.fold2_bit_int.F`

Declaring theory, measured: `HOL.Bit_Operations`.  Env =
`Proof_Context.init_global` of `Thy_Info`'s `HOL.Bit_Operations`.  Raw output:
`out_b.txt`, `out_t.txt`.

* `Bit_Operations.fold2_bit_int.F :: (bool ⇒ bool ⇒ bool) ⇒ int ⇒ int ⇒ int`
* entries returned: **0** (as expected)
* `own_defining_axioms` today: **1** —
  `[Bit_Operations.fold2_bit_int.F_def] fold2_bit_int.F ?f ≡ λx0 x1. fold2_bit_int.F_sumC ?f (x0, x1)`
  (body-free)

### What keys the registry holds that mention `fold2_bit_int`

`Function_Common.get_functions` is **not** in the `FUNCTION_COMMON` signature, so
the net was enumerated instead through a wildcard query: `Net.unify_term` with a
`Var`-headed query takes the `net_skip` branch (`net.ML:198-203`) and returns
every leaf, so `Function_Common.retrieve_function_data ctxt (Var (("wildcard",0),
dummyT))` yields the complete content.

* content visible in `HOL.Bit_Operations`: **19 entries**, all `Const`-keyed —
  `xor_num`, `…_class.or_num`, `and_num`, `or_not_num_neg`, `and_not_num`,
  `semiring_bit_operations_class.{xor,or,and}`, and the eleven inherited from
  `HOL.List` / `HOL.Set_Interval`.
* keys mentioning `fold2_bit_int`: **0**.  Neither the locale constant
  `fold2_bit_int.F` nor any morphism image of it is in the net.
* Content of the whole heap (see (g)): **38 entries**, none mentioning
  `fold2_bit_int`.

### The three `global_interpretation`s

The interpretations at `Bit_Operations.thy:1830-1836` (`defines and_int =
and_int.F`, etc.) declare the constants `Bit_Operations.and_int.F`,
`Bit_Operations.or_int.F`, `Bit_Operations.xor_int.F` (that is the actual
constant spelling — there is no bare `Bit_Operations.and_int`).  Queried in
`HOL.Bit_Operations`:

| constant | type | entries | `own_defining_axioms` today |
|---|---|---|---|
| `Bit_Operations.and_int.F` | `int ⇒ int ⇒ int` | **0** | 0 |
| `Bit_Operations.or_int.F`  | `int ⇒ int ⇒ int` | **0** | 0 |
| `Bit_Operations.xor_int.F` | `int ⇒ int ⇒ int` | **0** | 0 |

So the registration does not reach the background theory under any of the four
names.

---

## (c) The class-body case: `or_num`

Both constants are declared in `HOL.Bit_Operations` (`Bit_Operations.thy` ~:3307,
`fun or_num` inside `context linordered_euclidean_semiring_bit_operations`).
Each was queried by its own name, in `HOL.Bit_Operations`.  Raw output:
`out_c.txt`.

### `Bit_Operations.linordered_euclidean_semiring_bit_operations_class.or_num` (the class operation)

* entries returned: **1**
* `own_defining_axioms` today: **1** —
  `[…_class.or_num_dict] or_num ≡ linordered_euclidean_semiring_bit_operations.or_num`
* entry 1: key `or_num`, key head
  `Const Bit_Operations.linordered_euclidean_semiring_bit_operations_class.or_num`
  (= the queried constant)
* `#fs` = `[or_num]` (the class operation); `is_partial = false`; `simps = SOME` (9 thms)
* chosen rules (`simps`, 9) — **premise-free**; the class predicate appears
  nowhere, it is carried by the sort constraint on the type variable:

```
or_num num.One num.One = num.One
or_num num.One (num.Bit0 ?n) = num.Bit1 ?n
or_num num.One (num.Bit1 ?n) = num.Bit1 ?n
or_num (num.Bit0 ?m) num.One = num.Bit1 ?m
or_num (num.Bit0 ?m) (num.Bit0 ?n) = num.Bit0 (or_num ?m ?n)
or_num (num.Bit0 ?m) (num.Bit1 ?n) = num.Bit1 (or_num ?m ?n)
or_num (num.Bit1 ?m) num.One = num.Bit1 ?m
or_num (num.Bit1 ?m) (num.Bit0 ?n) = num.Bit1 (or_num ?m ?n)
or_num (num.Bit1 ?m) (num.Bit1 ?n) = num.Bit1 (or_num ?m ?n)
```

### `Bit_Operations.linordered_euclidean_semiring_bit_operations.or_num` (the locale-level twin)

* entries returned: **0**
* `own_defining_axioms` today: **1** —
  `[….or_num_def] linordered_euclidean_semiring_bit_operations.or_num ≡ λx0 x1. linordered_euclidean_semiring_bit_operations.or_num_sumC (x0, x1)`
  (body-free)

So of the pair, the **class operation is reached and the locale-level twin is
not**.  The measured rules carry no class-predicate premise.

---

## (d) `fun` under `overloading` of a same-theory `consts` constant

Subjects declared in `FunCensus` (the AFP `Pairing_Heap_List2_Analysis.thy:22-38`
shape reproduced with a local datatype).  Raw output: `out_d.txt`,
`out_names.txt`.

```isabelle
datatype 'a hp = Hp 'a "'a hp list"
consts sz :: "'a ⇒ nat"

overloading
  size_hps ≡ "sz :: 'a hp list ⇒ nat"
  size_hp  ≡ "sz :: 'a hp ⇒ nat"
  size_heap ≡ "sz :: 'a hp option ⇒ nat"
begin
  fun size_hps …            (* one fun *)
  definition size_hp …      (* two definitions *)
  definition size_heap …
end
```

Measured aside: `overloading` declares **no** new constants.  The theory's
constant list (`out_names.txt`) contains `FunCensus.sz`, plus the function
package's concealed `FunCensus.size_hps_{graph,sumC,rel,dom}`, but no
`FunCensus.size_hps` / `size_hp` / `size_heap` — those names are local aliases for
`sz` at the three type instances.  So there is exactly one constant to query.

### `FunCensus.sz`

* entries returned: **1**
* key: `sz`, key head `Const FunCensus.sz` (= the queried constant) — the entry
  was registered at the instance type `'a hp list ⇒ nat`, and the net drops the
  type, so the query at the declared constraint `'a ⇒ nat` finds it.
* `#fs` = `[sz]`; `is_partial = false`; `simps = SOME` (2 thms)
* chosen rules (`simps`, 2):

```
sz (Hp ?x ?hsl # ?hsr) = sz ?hsl + sz ?hsr + 1
sz [] = 0
```

* `own_defining_axioms` today: **3** — all three `Defs` axioms of the family come
  back, the two bodies and the body-free one:

```
[FunCensus.size_heap_def_raw] sz ≡ λh. case h of None ⇒ 0 | Some x ⇒ sz x
[FunCensus.size_hp_def_raw]   sz ≡ λh. case h of Hp x l ⇒ sz l + 1
[FunCensus.size_hps_def]      sz ≡ size_hps_sumC
```

Under the merging rule of PLAN.md §4/F2 this constant would carry all three
axioms plus the two `simps`.

---

## (e) `fun` inside `instantiation` of a local datatype in class `plus`

Subjects declared in `FunCensus`.  Raw output: `out_e.txt`, `out_s.txt`.

```isabelle
datatype pe_t = PE_A | PE_B pe_t
instantiation pe_t :: plus begin
  fun plus_pe_t :: "pe_t ⇒ pe_t ⇒ pe_t" where
    "plus_pe_t PE_A y = y"
  | "plus_pe_t (PE_B x) y = PE_B (plus_pe_t x y)"
  instance ..
end
```

### `Groups.plus_class.plus`, queried in `FunCensus` (the env where the instance lives)

* entries returned: **1**
* key `(+)`, key head `Const Groups.plus_class.plus` (= the queried constant)
* `#fs` = `[(+)]`; `is_partial = false`; `simps = SOME` (2 thms)
* chosen rules (`simps`, 2) — the instance's equations, stated on the class
  operation:

```
PE_A + ?y = ?y
PE_B ?x + ?y = PE_B (?x + ?y)
```

* `own_defining_axioms` today: **0** (the `class_param_of` rule ① fires first and
  returns `[]` before any axiom source is consulted, so the entry above is never
  looked at in production).

### `Groups.plus_class.plus`, queried in its own declaring theory `HOL.Groups`

* entries returned: **0**; `own_defining_axioms` today: **0**.

This is the env production would actually build for this constant, and there the
registry is empty for it: no instance exists yet in `HOL.Groups`.

### `FunCensus.plus_pe_t_inst.plus_pe_t` (the instance constant)

* entries returned: **0**
* `own_defining_axioms` today: **1** —
  `[FunCensus.plus_pe_t_def] plus_pe_t_inst.plus_pe_t ≡ λx0 x1. plus_pe_t_sumC (x0, x1)`
  (body-free)

---

## (f) A mutual block `fun f and g`

Subjects declared in `FunCensus`.  Raw output: `out_f.txt`.

```isabelle
fun pf_f :: "nat ⇒ nat" and pf_g :: "nat ⇒ nat" where
  "pf_f 0 = 0"
| "pf_f (Suc n) = Suc (pf_g n)"
| "pf_g 0 = 1"
| "pf_g (Suc n) = pf_f n"
```

### `FunCensus.pf_f`

* entries returned: **1**
* key `pf_f`, key head `Const FunCensus.pf_f` (= the queried constant)
* `#fs` = `[pf_f, pf_g]` — heads `Const FunCensus.pf_f`, `Const FunCensus.pf_g`
* `is_partial = false`; `simps = SOME` (4 thms)
* chosen rules (`simps`, 4) — the **whole block**:

```
pf_f 0 = 0
pf_f (Suc ?n) = Suc (pf_g ?n)
pf_g 0 = 1
pf_g (Suc ?n) = pf_f ?n
```

* `own_defining_axioms` today: **1** — `[FunCensus.pf_f_def] pf_f ≡ λx0. pf_f_pf_g_sumC (Inl x0)`

### `FunCensus.pf_g`

* entries returned: **1**
* key `pf_g`, key head `Const FunCensus.pf_g` (= the queried constant)
* `#fs` = `[pf_f, pf_g]`; `is_partial = false`; `simps = SOME` (4 thms)
* chosen rules: identical to `pf_f`'s — the same four equations, in the same
  order.  The one `info` is stored twice in the net, once per `fs` element
  (`function_common.ML:283-285`), so each constant of the block sees the whole
  block.
* `own_defining_axioms` today: **1** — `[FunCensus.pf_g_def] pf_g ≡ λx0. pf_f_pf_g_sumC (Inr x0)`

---

## Shape table

"Reached by the new branch" = the query in the constant's declaring theory
returns at least one entry whose key head is exactly that constant, **and** the
constant is not short-circuited by `class_param_of` (①).

| shape | entries returned | reached by the new branch |
|---|---|---|
| theory-level `fun` (`pa_narq`) | 1 | yes (`simps`, 2 rules) |
| theory-level `function`, no `termination` (`pb_vurn`) | 1 | yes (`psimps`, 1 rule, `accp` premise) |
| theory-level `function` + `termination` (`pc_tarv`) | 1 | yes (`simps`, 2 rules) |
| `fun`/`function` in a locale target, queried bare (`fold2_bit_int.F`) | 0 | no |
| constants derived by `global_interpretation … defines` (`and_int.F`, `or_int.F`, `xor_int.F`) | 0 | no |
| `fun` in a class body, class operation (`…_class.or_num`) | 1 | yes (`simps`, 9 premise-free rules) |
| `fun` in a class body, locale-level twin (`…_operations.or_num`) | 0 | no |
| `fun` under `overloading` of a same-theory `consts` (`sz`) | 1 | yes (`simps`, 2 rules; merged with 3 `Defs` axioms) |
| class parameter with an instance defined by `fun`, queried in the instance's theory (`Groups.plus_class.plus` in `FunCensus`) | 1 | no — ① `class_param_of` short-circuits |
| the same class parameter in its declaring theory (`Groups.plus_class.plus` in `HOL.Groups`) | 0 | no |
| the instance constant (`plus_pe_t_inst.plus_pe_t`) | 0 | no |
| mutual block, each member (`pf_f`, `pf_g`) | 1 each | yes (`simps`, all 4 rules to both) |

---

## (g) The heap census

Walked `thy :: Theory.ancestors_of thy` for `thy = Semantic_Embedding` (the
session's last theory): **87 theories**.  (VERIFICATION.md §5a reports 88 for the
same walk; that count is one higher, presumably because it counted the probe
theory itself.  Not otherwise reconciled.)  For every constant whose
`Name_Space` entry names that theory as its `theory_long_name` — **2489
constants** in total — the production-shaped query was run in that theory's own
`Proof_Context.init_global`.

* constants for which the query returns **≥ 1 entry whose key head is exactly
  that constant**: **38**
* constants for which the query returns entries but **no** entry is keyed on the
  constant itself: **0**
* every one of the 38 returns exactly **1** entry, and every one of those entries
  has `simps = SOME`

| theory | count | constants |
|---|---|---|
| `HOL.Quickcheck_Exhaustive` | 12 | `exhaustive_class.exhaustive`, `full_exhaustive_class.full_exhaustive`, `exhaustive_fun'`, `full_exhaustive_fun'`, `exhaustive_int'`, `full_exhaustive_int'`, `exhaustive_integer'`, `full_exhaustive_integer'`, `exhaustive_natural'`, `full_exhaustive_natural'`, `check_all_n_lists`, `check_all_subsets` |
| `HOL.List` | 10 | `arg_min_list`, `min_list`, `remdups_adj`, `shuffles`, `sorted_wrt`, `splice`, `successively`, `trancl_list`, `transpose`, `upto` |
| `HOL.Bit_Operations` | 8 | `and_not_num`, `and_num`, `or_not_num_neg`, `xor_num`, `linordered_euclidean_semiring_bit_operations_class.or_num`, `semiring_bit_operations_class.and`, `semiring_bit_operations_class.or`, `semiring_bit_operations_class.xor` |
| `HOL.Lazy_Sequence` | 3 | `iterate_upto`, `small_lazy'`, `small_lazy_class.small_lazy` |
| `HOL.Random` | 2 | `iterate`, `log` |
| `HOL.Predicate` | 1 | `iterate_upto` |
| `HOL.Quickcheck_Random` | 1 | `random_aux_set` |
| `HOL.Set_Interval` | 1 | `fold_atLeastAtMost_nat` |

### Comparison with VERIFICATION.md §5's 40 (`Spec_Rules`)

The `Spec_Rules` census was re-run in the same session to make the comparison
exact (`out_s.txt`): `Spec_Rules.dest_theory` items classified
`equational_recdef`, **40 items / 40 constants**, same eight theories, the
distribution VERIFICATION.md §5a records.

The registry's 38 are a **strict subset** of the `Spec_Rules` 40.  The two
missing, both in `HOL.Bit_Operations`, are exactly the two locale-target shapes:

| constant | `Spec_Rules` | registry (query on the bare constant) |
|---|---|---|
| `Bit_Operations.fold2_bit_int.F` | 1 item | 0 entries |
| `Bit_Operations.linordered_euclidean_semiring_bit_operations.or_num` | 1 item | 0 entries |

Everything else coincides constant for constant.  The two sources also differ in
the opposite direction at a shape that does not occur in this heap: an
unterminated `function` has a registry entry (with `psimps`) but no `Spec_Rules`
item at all — measured at (a), `pb_vurn`.

### The 20 record-eligible constants of VERIFICATION.md §5b′

Queried one by one in their declaring theories (`out_r.txt`): **19 of 20 are
reached**, each with exactly 1 self-keyed entry.

* **reached (19):** `List.arg_min_list`, `List.min_list`, `List.remdups_adj`,
  `List.shuffles`, `List.sorted_wrt`, `List.splice`, `List.successively`,
  `List.trancl_list`, `List.transpose`, `List.upto`,
  `Bit_Operations.and_not_num`, `Bit_Operations.and_num`,
  `Bit_Operations.or_not_num_neg`, `Bit_Operations.xor_num`,
  `Bit_Operations.linordered_euclidean_semiring_bit_operations_class.or_num`,
  `Random.iterate`, `Random.log`, `Predicate.iterate_upto`,
  `Set_Interval.fold_atLeastAtMost_nat`
* **not reached (1):** `Bit_Operations.fold2_bit_int.F` — 0 entries, the locale
  target case of PLAN.md §7

(The locale-level twin
`Bit_Operations.linordered_euclidean_semiring_bit_operations.or_num` is not among
the 20: VERIFICATION.md §5b′ classifies it `Infra("class_variant")`, no record.)

### Wildcard-keyed entries anywhere in the heap

The full registry content visible in `Semantic_Embedding` (wildcard query, see
(b) for the method) is **38 entries** — the same 38 constants, one entry each.

* entries whose key head is **not** a `Const`: **0**.  No `Var`- or `Abs`-headed
  key exists anywhere in this heap's registry, so the wildcard branch of
  `Net.unify_term` contributes nothing to any query here.
* every key is the bare constant itself, with no arguments: e.g. key `or_num`
  for `…_class.or_num`, key `and_num` for `and_num`, key `upto` for `List.upto`.

---

## Timing

The whole-heap per-constant query (87 theories, 2489 constants; one
`Proof_Context.init_global` per theory, one `Consts.the_constraint` and one
`retrieve_function_data` per constant, all inside the timed region):

* first run, cold: **0.013 s**
* five consecutive repetitions: **0.0086 s, 0.0087 s, 0.0085 s, 0.0081 s,
  0.0081 s** (38 hits each time)

That is roughly 3–5 µs per constant on this machine.
