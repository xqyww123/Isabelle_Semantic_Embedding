# Overloading `fun`: a name-free way to its equations — Opus 5 agent report (2026-09-14)

Commissioned after the rev 3.0 re-review; the user's ruling: RECORD the mutual-`fun`-inside-`overloading` gap as a known limitation (doc/invalidation_limitations.md #8, PLAN.md §10.5), do not implement candidate 2 now.  Probe files were in the session scratchpad (`ovl_probe/`), not kept.

## Report — a more reliable way to reach an overloaded constant's defining equations

All probes ran on a fresh `Semantic_Embedding` REPL server (port 6703, Isabelle2025-2), now shut down. Scratch files (probe theories + raw output) are in
`/tmp/claude-1002/-home-qiyuan-Current-MLML/8ee4dc8b-0295-46df-b280-a85bcc774433/scratchpad/ovl_probe/`
(`Ovl_Probe4/5/6/7/8.thy`, outputs `probe4.txt` … `probe8.txt`).

---

### 0. Essence first

The reliable, name-free way to reach an overloaded constant's equations is **an index, built once per theory, over that theory's own `.simps`/`.psimps` facts, keyed by the head constant of each guarded equation** — candidate 2. It is the only candidate that covers all four sub-shapes (single `fun`, mutual `fun … and …`, unterminated `function`, curried), it reuses the guard the rule already has (`defining_equation`, `Tools/semantic_digest.ML:374`), its theory attribution is a table lookup rather than a string comparison, and it costs about 4 ms per env. Everything else either misses a sub-shape (Spec_Rules misses unterminated `function`; the registry misses the mutual case and answers the wrong type instance) or drags in encoding scaffolding (the graph route).

---

### 1. The shape, measured exactly

Probe `Ovl_Probe4.thy` reproduces the AFP `Pairing_Heap_List2_Analysis.thy:22-40` shape with a local datatype and adds three variants. What `Semantic_Digest.own_defining_axioms` returns today (`probe4.txt`):

| shape | constant | today's answer |
|---|---|---|
| (a) single `fun` + sibling `definition` in `overloading` | `sz` | `[size_hp_def_raw] sz ≡ λh. case h of Hp x l ⇒ sz l + 1`, `[size_hps.simps] sz [] = 0`, `[size_hps.simps] sz (Hp ?x ?hsl # ?hsr) = …` — **D9 works** |
| (b) **mutual** `fun … and …` in `overloading` | `tz` | `[tsize_hp_def] tz ≡ λx0. tsize_hps_tsize_hp_sumC (Inr x0)`, `[tsize_hps_def] tz ≡ λx0. tsize_hps_tsize_hp_sumC (Inl x0)` — **no equational content at all** |
| (c) unterminated `function` in `overloading` | `uz` | `[usize_hps.psimps] usize_hps_dom [] ⟹ uz [] = 0`, … — **D9 works** (it reaches `.psimps`) |
| (e) curried 2-argument `fun` in `overloading` | `cz` | `[csize_hps.simps] cz [] ?n = ?n`, … — **D9 works** (`cz ≡ λx0 x1. csize_hps_sumC (x0, x1)`) |

Two things are worth correcting in the brief's framing:

* In the mutual case, D9's `unsuffix "_sumC"` test *does* fire — the rhs head under the λ **is** `Const ("…tsize_hps_tsize_hp_sumC", _)` (measured). It strips to `…tsize_hps_tsize_hp` and then finds no `tsize_hps_tsize_hp.simps`, so `unfold_sumC_axiom` (`Tools/semantic_digest.ML:412-421`) falls back to `[axiom]`. The failure is in the *name reconstruction*, exactly as suspected, but it is the conglomerate binding (`Binding.conglomerate fnames`, `function.ML:82`; `fsum_name = derived_name_suffix defname "_sum"`, `mutual.ML:91`) that has no facts, not a mismatch on `_sumC`.
* **No fact whatsoever produced inside an `overloading` block is named after the constant.** I listed every own fact of the probe theory (`probe4.txt`, "Fact-table index over THIS theory's own facts"): `size_hps.{simps,psimps,induct,pinduct,cases,elims,pelims,termination}`, `tsize_hps.{simps,psimps,cases,elims,pelims}`, `tsize_hp.{…}`, `tsize_hps_tsize_hp.{induct,pinduct,termination}` — all named after the local binding or the conglomerate, never after `sz`/`tz`/`uz`/`cz`. So **candidate 5 yields nothing**: `.pinduct`, `.cases`, `.elims`, `_dom` are as unreachable by the constant's name as `.simps` is, and none of them carries the equations in a form the guard would accept anyway.

Frequency, re-measured independently (textual scan of `contrib/Isabelle2025-2/src` + `contrib/afp-2026-05-13/thys`): 257 `overloading` blocks on their own line, of which 216 contain a `definition`, 28 a `primrec`, 16 a `fun`, 4 an `abbreviation`; **0 contain a mutual specification** (`fun`/`function`/`primrec`/`nominal_function` with `and` before `where`). A looser scan that also catches `overloading name ≡ …` on one line finds 496 blocks, 64 with a recursive command, again **0 mutual**. This confirms the project's own count. The gap is real but currently unrealised.

One thing the census framing understates: for `primrec` inside `overloading` (28 blocks, the `Nat.compow` shape) today's rule is **not** blind — the Defs axiom has a body (`compow ≡ rec_nat (λf. id) (λn na f. f ∘ na f)`, measured in `probe8.txt`), so equation edits do move the digest. Total insensitivity is confined to the function package, and total insensitivity *with no recovery* is confined to mutual `fun` inside `overloading`.

---

### 2. Candidate 1 — follow `Defs` structurally to the graph

**What it looks like** (measured, `probe4.txt`). For the mutual block:

```
tz                              ≡ λx0. tsize_hps_tsize_hp_sumC (Inl x0)
tsize_hps_tsize_hp_sumC         ≡ λx. THE_default undefined (tsize_hps_tsize_hp_graph x)
tsize_hps_tsize_hp_graph_def:
  tsize_hps_tsize_hp_graph ≡ lfp (λp x1 x2.
      (∃f. x1 = Inl [] ∧ x2 = 0)
    ∨ (∃f h hs. x1 = Inl (h # hs) ∧ x2 = f (Inr h) + f (Inl hs) ∧ p (Inr h) (f (Inr h)) ∧ p (Inl hs) (f (Inl hs)))
    ∨ (∃f x l. x1 = Inr (Hp x l) ∧ x2 = f (Inl l) + 1 ∧ p (Inl l) (f (Inl l))))
```

**Correctness.** Every clause is in there, so the content moves when any equation changes (inferred from `function_core.ML:483-500`, `define_graph` builds one intro per clause; confirmed by inspection of the printed body). It does **not** move when `termination` is added — the graph is defined in `prepare_function`, before the termination proof (`function.ML:92`, `function_core.ML:874-876`), and the unterminated probe (c) has a `usize_hps_graph` of the same shape. So on the "moves iff the equations change" axis this is the *best* candidate.

**Coverage.** Single, mutual (one graph per block, `tsize_hps_tsize_hp_graph`), curried, unterminated — all measured present. Nominal2 has its own `nominal_function_core.ML` and would need checking separately.

**Why I reject it anyway.** Three reasons, in order of weight:

1. *No stopping rule.* Reaching the graph from `tz` takes two hops through `Defs` (`tz → …_sumC → …_graph`). Making that structural means "transitively follow the Defs axioms of constants mentioned in the rhs", which has no principled terminating condition and no way to say which hop is the right one. Every trigger I could think of for "stop here" is name arithmetic in disguise — and I measured that the one genuinely structural marker fails: `Name_Space.is_concealed` on the constant space says `size_hps_sumC : false`, `usize_hps_sumC : false`, `tsize_hps_tsize_hp_sumC : false`, while `size_hps_graph : true` and `size_hps_rel : true` (`probe7.txt`). The `_sumC` constant is *not* concealed, so "the rhs head is concealed" cannot be the trigger; it fires instead on 42 datatype constructors/recursors whose Defs rhs is `ctor_*` (measured list in `probe7.txt`).
2. *Foreign content in the dependency edges.* `deps_of_term` (`Tools/semantic_digest.ML:203`) derives edges from the props. The graph body would give `tz` edges to `Complete_Lattices.lfp`, `Sum_Type.Inl/Inr`, `HOL.THE_default` — `lfp` in particular is a real record, so editing `Complete_Lattices` would invalidate every overloaded function constant. That is exactly the mass false invalidation the same-theory filter exists to prevent (`Tools/semantic_digest.ML:225-245`).
3. *It is not what the rule's philosophy says a definition is.* §10.1's "definition content = the facts the defining command produced" is abandoned entirely: the graph's `lfp` encoding is an internal artefact, not a user-facing statement, and the digest would be over a sum-type compilation whose shape changes with arity re-currying.

**Verdict: reject.**

---

### 3. Candidate 2 — an index over the theory's own fact table (**recommended**)

Build, once per env, from `Facts.dest_static true (map Global_Theory.facts_of (Theory.parents_of thy)) (Global_Theory.facts_of thy)`: for every fact whose name ends in `.simps`/`.psimps`, for every theorem in it, if the conclusion is an equation whose lhs head is `Const (c, _)` (the existing `defining_equation`, `Tools/semantic_digest.ML:374`), file it under `c`.

**Coverage — measured on the probe theory (`probe4.txt`):**

```
Ovl_Probe4.sz  <- size_hps.simps, size_hps.psimps          (2 equations)
Ovl_Probe4.tz  <- tsize_hps.simps, tsize_hps.psimps,
                  tsize_hp.simps,  tsize_hp.psimps         (3 equations)   ← the gap, closed
Ovl_Probe4.uz  <- usize_hps.psimps                         (2 equations)   ← partial function
Ovl_Probe4.cz  <- csize_hps.simps, csize_hps.psimps        (2 equations)   ← curried
```

It also subsumes the plain cases: `plain_size`, `mut_hps`, `mut_hp`, `pfun` all appear under their own names.

**Theory attribution is structural, not a string comparison.** `Facts.dest_static verbose prev_facts` filters out everything already defined in a parent (`Pure/facts.ML:232-243`), and `verbose = true` keeps concealed and private entries — which matters: `Bit_Operations.fold2_bit_int.F.simps` is private (its `termination` is `private`, `Bit_Operations.thy:1760`) and the index reaches it, just as `Facts.lookup` does today. Restricting the index of theory *T* to constants declared in *T* replaces `same_theory`'s leading-component fallback (`Tools/semantic_digest.ML:262-268`, whose two known casualties are documented there) with a table lookup on this path.

**Cost — measured (`probe5.txt`, `probe6.txt`, 87-theory heap):**

| | |
|---|---|
| `Facts.dest_static` over all 87 theories (cold / warm) | 0.155 s / 0.148 s, 21 510 own facts total |
| one call on `Semantic_Embedding` (whole table ≈ 21.5 k facts) | **0.004 s** |
| building the index from those facts, all 87 theories | 0.001 s, 325 indexed head constants |

Against §10.2's measured 0.42 s for a whole `semantics_of` pass, one index build per env is about **1 %**. Scaling is linear in the theory's *total* fact table (≈ 0.19 µs/fact), so a 200 k-fact AFP session costs ≈ 40 ms per env — still once per pass. Caveat: `Facts.dest_static` calls `consolidate`, which forces every unfinished lazy fact in the table (`Pure/facts.ML:219-228, 238`); my numbers are from a loaded heap where they were already forced.

**What the index would contaminate — measured over the 1 079 record-eligible constants of the heap** (`probe5.txt`, cross-tabulated against today's routing):

```
shipped=c_def   index=none        676
shipped=empty   index=none        204
shipped=struct  index=none         48
shipped=c_def   index=OTHER-name   39
shipped=empty   index=OTHER-name    3
shipped=c.simps index=same-name    107      ← the index reproduces the named source exactly
shipped=c.simps index=OTHER-name     1
shipped=struct  index=OTHER-name     1
```

So the index **exactly reproduces** the `c.simps`/`c.psimps` half of the named-fact source on 107 of 108 constants. The 44 "OTHER-name" rows are:

* 36 datatype-generated constants (`List.list.{map,set,rec_list,case_list,list_all2}`, `Option.option.*`, `Num.num.*`, `Enum.finite_n.*`, `String.char.*`, `Predicate.{seq,pred}.*`) picking up their type's `T.simps`. That is the datatype's *characteristic equations for that constant*, not foreign content — `rec_list ?f1 ?f2 (?x # ?xs) = …` really is `rec_list`'s meaning. The brief's worry ("a datatype `T.simps`'s equations are headed by `case_T`/`rec_T`, fine") is confirmed: they are headed correctly and the guard keeps only those.
* 5 duplicate-name pairs where a type has both a new and an `old.` fact bundle (`Sum_Type.sum.simps` + `Sum_Type.old.sum.simps`, likewise `Product_Type.{bool,prod,unit}`, `Nat.nat`) — same props under two labels. Harmless but noisy: the digest sorts by `(label, term)` (`prop_ord`, `Tools/semantic_digest.ML:299`), so the duplicate label is hashed.
* `Bit_Operations.semiring_bit_operations_class.{or,and,xor}` ← `{or,and,xor}_int.F.simps`. **These are class parameters** (`Axclass.class_of_param` returns `SOME "Bit_Operations.semiring_bit_operations"`, measured in `probe8.txt`), so rule ① (`class_param_of`, `Tools/semantic_digest.ML:294`) zeroes them before any table is read. The index must therefore stay *after* rule ①; it must never be allowed to precede it.
* `Nat.compow` ← `Nat.funpow.simps`. This is the `primrec`-in-`overloading` case, and it is a genuine improvement.
* `Zorn.pred_on.suc_Union_closedp` picks up `Zorn.subset.suc_Union_closedp.simps` **in addition to** its own `.simps` — a locale-exported twin. This is the one real "foreign `.simps` happens to be headed by c" case on the heap. `lemmas foo.simps = …` would behave the same way; `inductive_set` does not (its `.simps` is headed by `Set.member`, so the guard rejects it — 17 such constants already measured in §10.2 and unchanged here).

**Where to put it.** I measured two placements:

*Replace the whole `.simps`/`.psimps` half of the named source (step ②).* 44 digests move, 36 of them datatype constants. That is a defensible but large change and buys nothing the narrow placement does not.

*Put it at step ③ in D9's position.* Then step ② (`c.simps` → `c.psimps` → `c_def`) still short-circuits for everything that names its facts after the constant, and the index is consulted only where the named source came up empty. Measured blast radius (`probe8.txt`): the eligible, non-class-parameter constants with **no** named fact but index equations number **12** — the 11 `rec_T` recursors whose `*_def` lives in the axiom table, not the fact table (so §10.7's "50 whose Defs axiom names end in `_def`" route), plus `Nat.compow`. Those 12 gain their characteristic equations alongside the BNF `ctor_rec` body; no constant loses anything.

**Two implementation notes.**
1. The `.simps`-before-`.psimps` preference must be **per fact base name**, not global per constant. With a global preference, a hypothetical `overloading` block containing one terminated `fun` and one unterminated `function` at another type instance would have its partial member's `.psimps` silently dropped because the other member contributed a `.simps`. Per base name (`X.simps` if present, else `X.psimps`) has no such hole.
2. Labels stay real fact names (`tsize_hps.simps`, `tsize_hp.simps`), so the signature comment at `Tools/semantic_digest.ML:63-69` needs only its D9 clause rewritten, not its shape.

---

### 4. Candidate 3 — `Spec_Rules`

**It does close the mutual gap, precisely** (`probe4.txt`, `probe6.txt`):

```
item name=""  class=Equational Recdef  terms: tz, tz
  tz [] = 0
  tz (?h # ?hs) = tz ?h + tz ?hs
  tz (Hp ?x ?l) = tz ?l + 1
```

and for `sz` it also returns the sibling `definition`'s rule (`[Ovl_Probe7.size_hp_def] sz ?h = (case ?h of Hp x l ⇒ sz l + 1)`) in the same constant-headed equational form. Theory attribution is available structurally: **`Spec_Rules.dest_theory thy`** (`Pure/Isar/spec_rules.ML:148`) returns only the items this theory added and none of its parents' — it does not need the item's name (which is `Binding.empty` here, and would defeat `same_theory` since `leading_component "" ≠ "Ovl_Probe7"`). Cost: 0.007 s for all 87 theories, 1 343 items, 119 nameless.

**But it misses the unterminated `function` — measured, not inferred.** `Spec_Rules.add` appears only in `prepare_termination_proof` (`function.ML:217`); the partial branch in `prepare_function` never calls it. Measured: `Spec_Rules items whose TERMS mention Ovl_Probe4.uz: 0` and `… Ovl_Probe4.pfun: 0` (`probe4.txt`). Nominal2 is the same — `Spec_Rules.add Binding.empty Spec_Rules.equational_recdef fs tsimps` is in `Nominal2/nominal_termination.ML:69` and nowhere in `nominal_function.ML`.

**And as a general source it is far worse than the named facts.** Cross-tab over the 1 079 eligible constants (`probe6.txt`):

* **30 constants that answer from `c.simps` today would lose everything** — all of them `inductive`/`inductive_set` predicates (`Wellfounded.accp`, `Transitive_Closure.tranclp`, `Finite_Set.finite`, `Relation.Domainp`, `List.ord_class.lexordp`, …). `inductive` registers an `Inductive` item whose rules are the intro rules, not equations headed by `c`; the `c.simps` "case" characterisation is a fact only.
* **470 constants would gain content** the shipped rule does not have, mostly `definition`s where the item is named `c_def` and its rule is the unfolded `c x = body` beside the Defs `c ≡ λx. body` — i.e. a second, near-duplicate source for the majority of the heap.

**Verdict:** excellent as a *corroborating* source and a proof that the information is available structurally; unusable as a replacement, and unusable even as the narrow fix because the unterminated `function` inside `overloading` is precisely one of the four sub-shapes. (Also note the existing `spec_rule_axioms`, `Tools/semantic_digest.ML:331-343`, would drop these items anyway: its `same_theory` call is fed the empty item name.)

---

### 5. Candidate 4 — `Function.get_info` / `Function_Common.retrieve_function_data`

Argued and measured, not asserted:

* **The exported entry point is broken in exactly this shape.** `Function.get_info ctxt t = Function_Common.retrieve_function_data ctxt t |> the_single |> snd` (`function.ML:274-275`). In the mutual-`overloading` case the item net returns **two** entries (measured, `probe6.txt`: both keyed on `tz`, at `?'a hp ⇒ nat` and `?'a hp list ⇒ nat`, both carrying `defname=tsize_hps_tsize_hp`), so `the_single` raises and `get_info` gives nothing. Only the *internal* `retrieve_function_data`/`import_function_data` work — the `Function_Common` dependency D1 deliberately abandoned.
* **It answers the wrong type instance.** The item net indexes on the term with types dropped (`Item_Net.init (op aconv o apply2 fst) (single o fst)`, `function_common.ML:261`). Measured (`probe4.txt`): querying `sz :: 'a hp ⇒ nat` — the instance defined by the sibling `definition size_hp` — returns the `fun size_hps` info and its two `simps`. Querying the declared constraint `sz :: 'a ⇒ nat` does the same. There is no way, from a constant name, to ask the registry "the equations for *this* instance"; the digest is name-addressed, so it has only the name.
* It gives nothing for packages that do not use it, and the fact-table route already covers Nominal2 (which copies `add_simps`, `Nominal2/nominal_function.ML:105-121`, producing `<fname>.simps`/`.psimps`).

**Verdict: reject, including for this one shape.** It is not merely "an internal registry"; it is wrong here.

---

### 6. Candidate 5 — anything else the package emits

Measured above (§1): nothing the package emits inside an `overloading` block is named after the constant, and nothing besides `.simps`/`.psimps` carries the equations in a form the guard accepts. `size_hps.termination`, `.induct`, `.pinduct`, `.cases`, `.elims`, `.pelims` are all named after the local binding or the conglomerate. `<f>_dom` is a constant, not a fact, and its Defs entry is empty (`probe4.txt`: `Ovl_Probe4.tsize_hps_tsize_hp_dom — Defs.specifications_of: ⟨none⟩`). Nothing here.

---

### 7. Recommendation

**Replace D9's lookup by the theory-own equation index (candidate 2), keeping D9's position at step ③.** Concretely, in `own_defining_axioms` (`Tools/semantic_digest.ML:423-437`), replace `unfold_sumC_axiom` (`:412-421`) with:

```
③ Defs axioms of c, own theory only.
   If the env's theory-own equation index has entries for c
   (.simps preferred over .psimps PER FACT BASE NAME):
       the answer is those equations TOGETHER WITH the Defs axioms
   else: the Defs axioms as they are.
```

and add to `env` (`Tools/semantic_digest.ML:80-88`, built in `make_env`, `:108`) one `(string, (string * term) list) Symtab.table`: the theory's own `.simps`/`.psimps` facts grouped by the head constant of their guarded equations.

Why union rather than "replace the body-free axiom": there is no name-free test for "this axiom is body-free". I tried the one structural candidate — `Name_Space.is_concealed` on the rhs head — and **measured that it fails** (`_sumC` is not concealed, `_graph`/`_rel` are; `probe7.txt`). `Infra_Filter.infra_const_rule` says `size_hps_sumC → Infra "hidden"` but also `List.list.ctor_fold_list → Infra "concealed"`, so it does not discriminate either. Union needs no such test: it is monotone (content can only be added), deterministic, and it makes the invariant impossible to violate — *you cannot lose a package's equations by failing to guess a name*. The cost is one extra label (`tsize_hps_def`, `sz ≡ size_hps_sumC`) and the return of the `f_sumC` dead dependency edge (limitation #6) on this path only — which is what rev 2.3's MERGE already accepted, and which step ② keeps rare: a plain `fun` never reaches step ③.

Measured consequences of shipping this:

| | |
|---|---|
| `Ovl_Probe8.sz` (single `fun` in `overloading`) | today's 3 props **plus** `[size_hps_def] sz ≡ size_hps_sumC` |
| `Ovl_Probe8.tz` (mutual `fun` in `overloading`) | today's 2 body-free axioms **plus** all 3 equations — **the gap closes** |
| `uz`, `cz` | unchanged (D9 already reached them; the index reaches the same facts) |
| 87-theory heap, record-eligible constants whose digest moves | **12** — 11 `rec_T` recursors gaining their datatype's equations, plus `Nat.compow` gaining `Nat.funpow.simps` |
| heap constants that lose content | **0** |
| added cost per env | ≈ 4 ms (≈ 1 % of a `semantics_of` pass) |

What I would **not** do: extend step ② (the whole `.simps` half of the named-fact source) by the index. It moves 44 digests instead of 12, for no coverage the narrow placement lacks, and it puts a table scan in front of a lookup that already answers 107 of 108 cases identically.

Tests to add: the D9 subject S13n generalised to a two-member **mutual** `fun` inside `overloading` (assert three props, labels `[…tsize_hp.simps, …tsize_hps.simps, …]`, `plus` mentioned, and — red on the shipped module — that the answer is not two body-free axioms); plus an unterminated `function` inside `overloading` pinning that the index reaches `.psimps` where `Spec_Rules` has nothing.

---

### 8. Measured vs inferred

**Measured** (REPL, Isabelle2025-2, this session): every row of §1; the index's answers for `sz`/`tz`/`uz`/`cz` and the whole-heap cross-tabs of §3; all timings; `Spec_Rules` returning 0 items for both unterminated `function`s and the exact item contents for `sz`/`tz`; `Function.get_info` failing on `tz` while `retrieve_function_data` returns two entries; `get_info` answering the wrong type instance for `sz`; `Name_Space.is_concealed` on `_sumC`/`_graph`/`_rel`; `Axclass.class_of_param` on the three `Bit_Operations` names; `Infra_Filter` verdicts; the AFP+Isabelle textual scan (0 mutual-in-`overloading`, 257/496 blocks depending on the pattern).

**Inferred from source, not run:** that the graph body changes on every clause edit and never on a `termination` proof (`function_core.ML:483-500`, `function.ML:92`) — the *shape* of the graph def and its presence for the unterminated case were measured, the change-sensitivity was not; that Nominal2 names its facts `<fname>.simps`/`.psimps` and registers `Spec_Rules` only on termination (`Nominal2/nominal_function.ML:105-121`, `nominal_termination.ML:55,69`) — read, not run; the per-base-name `.simps`/`.psimps` preference hole (§3, note 1) is a construction I reasoned about, not a shape I found in a library.
