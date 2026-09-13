# Function-package constants: equations into the semantic digest — plan

Status: **rev 2.3 (2026-09-13); after three adversarial review rounds
(`ai-artifacts/fun_digest/review/`: `SCOPE.md`, `judge.json`,
`rereview_judge.json`, `rereview2_judge.json` — all READY_AFTER_FIXES,
every "fix" ruling applied here; round three found no design defect; the
CODE was then reviewed in the same directory — `impl_judge.json`,
READY_AFTER_FIXES, whose F1 is not the F1 of §3 and is decided in §8, and
`rereview_impl_judge.json`, READY_AFTER_FIXES on four record-only
clauses, applied) and
the user's decisions of the same day (F2 changed to MERGE, the type
conjunct withdrawn, paid end-to-end acceptance chosen; §5 (b), the
exported `digest_term` guard, chosen); no open items; IMPLEMENTED
2026-09-13 after "开工" (code, tests, docs; `Test_Sensitivity` red on the
old module for S13a–e/S14 and green after, S13i red on the pre-option-A
module and green after, `Test_All` green, the registry
re-check of §9 item 2 gives 32 gain / 6 class parameters `[]` /
`fold2_bit_int.F` unchanged); the paid acceptance of §9 item 3 is reported
in `ACCEPTANCE.md`.**
Verification record: `ai-artifacts/fun_digest/VERIFICATION.md` (Opus 5
agent, Isabelle2025-2) — NOTE its census (§5) and structural rows were
taken on `Spec_Rules`, not on the source chosen in F3, and its §4 remedy
("sorting the normalised props") is superseded by F6′ (the ruling is §2
here); the registry-source census is `ai-artifacts/fun_digest/CENSUS.md`
(2026-09-13, pre-flight, referenced below as CENSUS).  Timing of the
normaliser: `ai-artifacts/fun_digest/NORMALIZE_TIMING.md`.  Parent design:
`archive/plans/CHECK_OUTDATE_PLAN.md` (digest §3.1/§7.3, sensitivity §14);
accepted-gap register `doc/invalidation_limitations.md`.

## 1. Essence

Two changes to `Tools/semantic_digest.ML`, one function each.

1. A constant defined by the function package (`fun`, `function`) keeps the
   same semantic digest when its equations change, so its stored English
   interpretation and its dependents' go stale silently.  Cause: the digest
   takes the constant's defining axioms from `Defs`, and for the function
   package that axiom is `f ≡ f_sumC …` (no equation body); the equations
   live only in the infrastructure constant `f_graph` (no store record) and
   in the derived theorems `f.simps`/`f.psimps`.  Fix (F1–F5): for a
   constant the function package's own registry knows
   (`Function_Common.retrieve_function_data`), the digest takes the
   registry's `simps`, or `psimps` when termination is unproved, **in
   addition to** its `Defs` axioms (the body-free axiom stays as harmless,
   deterministic content; nothing is filtered by name).
2. The digest's alpha-normalisation (`normalize`: renaming every
   Free/Var/TFree/TVar by first occurrence and erasing binder names before
   hashing) is **removed** (F6′).  It was never proposed to the user (it came
   in with the first digest commit `a2cd02b`, 2026-07-21), buys nothing for
   correctness (a digest that moves on a rename makes the entity a seed:
   one re-interpretation, then the prefilter and the judge, which answers
   UNCHANGED and walls the dependents), and its only benefit — saving that
   re-interpretation and gate call on cosmetic renames — was never measured
   to matter.  The sort of a constant's props (clause reorder does not move
   the digest) is kept (F6′).

## 2. Facts the rule rests on (measured unless marked)

- Only the function package is body-free in `Defs`.  `definition`,
  `inductive`, `primrec` (`pr_len ≡ rec_list 0 (λx xs. Suc)`), `primcorec`,
  `partial_function` (`≡ option.fixp_fun (λf n. …)`) carry the body;
  `abbreviation` has no `Defs` entry and is handled by the existing
  `Consts.the_abbreviation` branch (VERIFICATION.md §2).
- The registry (`Function_Common`, `add_function_data`) has exactly two
  writers in the distribution and the shipped AFP, `function.ML:136` and
  `:216` (judge, by grep); `partial_function`, `old_recdef`, Nominal2's
  `nominal_function` (own registry, `nominal_function_common.ML:110`) and
  `partial_function_mr` are not in it.  Measured 2026-09-13
  (`Psimps_Probe.thy`): `vurnak` (`function`, no `termination`):
  `psimps = [vurnak_dom ?n ⟹ vurnak ?n = (if ?n = 0 then 0 else vurnak (?n - 1))]`,
  `simps = NONE`; `narquil` (`fun`): both present.  The psimps premise is
  built in ML as `Wellfounded.accp <f>_rel $ lhs` (function_core.ML:575-576);
  `<f>_dom` is an abbreviation created afterwards (function_core.ML:890-893)
  and never occurs in the certified term.
- The registry is an `Item_Net` keyed on the function TERM
  (`function_common.ML:261`; a mutual block stores its one info once per
  element of `fs`, `:286`).  `retrieve_function_data` returns
  `(term * info) list`, the `term` being the net's key, untouched by the
  transfer morphism (`:279-281`).  `Item_Net.retrieve` is `Net.unify_term`:
  the net encodes `Const (c, _)` by NAME only (`net.ML:53-62`), so an atomic
  query returns every entry keyed on the atom `c` at any type (`net.ML:193`)
  PLUS the whole top-level wildcard branch (`net.ML:208`), i.e. any entry
  whose key term has a Var or Abs head (`:59-61`); the key is the morphism
  image of the `fs` element, hence a bare `Const` only when no
  term-rewriting mixin intervened AND the constant was not declared under
  `context fixes x` with `x` in its equations — there the block's fixed
  variable becomes a parameter on export and the key is the application
  `f ?x` (measured 2026-09-13, implementation review F1: `Ctx_Probe`,
  key `step ?k`, bare query 0 entries, one-argument query 1 entry;
  distribution instances `Power_By_Squaring.efficient_funpow`,
  `IMP.Collecting.Step`, both outside this heap).  The net matches a query
  only against keys of the same argument count (`net.ML:188-207`), a `Var`
  argument being a wildcard.  CENSUS (g): the heap's registry holds
  38 entries, every key a bare `Const`, no wildcard-keyed entry.  Entries
  are installed with `pervasive = false` (`function.ML:135-136`,
  `:215-216`), so a `fun`/`function` in a LOCALE target reaches the
  background theory only through that locale's registrations, keyed on the
  registration morphism's image, never on the bare constant (CENSUS (b):
  `fold2_bit_int.F` and the three `global_interpretation … defines`
  constants all return 0; no key in the heap mentions `fold2_bit_int`).  A
  CLASS-body `fun` IS reached through the class operation: CENSUS (c),
  `…_class.or_num` returns 1 entry with 9 premise-free simps; its
  locale-level twin returns 0.  The returned theorems are re-stamped with
  the env's theory by the transfer morphism (`:279-281`;
  `Thm.join_transfer`), so the answer carries no theory attribution of its
  own.  An unterminated `function` HAS a registry entry (`psimps`, CENSUS
  (a) `pb_vurn`) — the one shape where the registry sees more than
  `Spec_Rules`.
- Theory attribution therefore rests on ②: the digest env of a constant is
  built from the theory that declares it (`theory_structure.ML:171-183`
  enumerates only constants whose `theory_long_name` is the scanned theory;
  `semantic_store.ML:1811` builds `make_env` from that theory), and the
  function-package constant's `Defs` axiom `f_def` passes `same_theory`
  there.  The registry branch is sound only under this convention (every
  production caller obeys it; `Test_All.thy:46`'s Main-wide env does not,
  and is a test).
- Class parameters overloaded by a `fun` inside `instantiation` are
  short-circuited by `class_param_of` before any axiom source is consulted
  (`Groups.plus_class.plus` would otherwise absorb the instance's
  equations; VERIFICATION.md §3; CENSUS (e): queried in the instance's
  theory the registry returns 1 entry keyed on `(+)` with the instance's
  equations, queried in `HOL.Groups` it returns 0).  For
  `Groups.plus_class.plus` ② is empty in every env (Groups.thy declares no
  instance), so ③ can never fire for it; the instance constant
  `…_inst.plus_…` returns 0 and keeps its body-free axiom (infra, no
  record).
- Cost of the digest move: the semantic digest and the dependency list are
  computed ONLY for WIP theories (`semantic_store.ML:1795-1808`: a
  persistent theory's entries get `NONE`/`[]` without calling
  `Semantic_Digest.semantics_of`).  Digests that ③ would move in the
  session heap (CENSUS (g), registry source, 87 theories, 2489 constants):
  38 constants are self-keyed in the registry (six of them class `fixes`
  parameters that ① short-circuits before any axiom source is consulted,
  so ③ moves 32 digests; CENSUS's own criterion, its shape table) — a
  strict subset of the `Spec_Rules` census's 40, the two missing being the locale-target shapes
  `fold2_bit_int.F` and the locale-level `or_num` twin; of VERIFICATION.md
  §5b′'s 20 record-eligible constants ③ reaches 19 (all but
  `fold2_bit_int.F`).  All sit in loaded, persistent theories and pay
  nothing.  The same holds for change 2: removing the normaliser moves the
  digest of every WIP-keyed name-addressed entity once.  What pays is only
  a WIP-keyed record: it becomes a seed at the next scan; a record written
  before the semantic change gate (no stored baseline) takes
  `SEMANTIC_CHANGE_GATE_PLAN.md` §3 row 2 (forced CHANGED, no prefilter, no
  judge, mints, enrols its theory-internal dependents of the four tracked
  kinds; theorem-alike dependents are re-interpreted once and never mint)
  — an accepted one-time cost of that plan.  The number of WIP-keyed
  records in the production store is not measured; the plan does not need
  it (they pay once whatever the number).
- Cost of the query: 3–5 µs per constant, 0.009 s over the whole heap
  (CENSUS, timing).
- Sort order: `own_defining_axioms` sorts the props; the `Defs` branch by
  axiom name (`:396`), the fallback by name then `Term_Ord.term_ord`
  (`:383-384`).  `Term_Ord.term_ord` decides a tie at a Var/Var position by
  index then NAME (`term_ord.ML:127, :157-158`).  With the normaliser gone
  names are hashed anyway, so the order being name-sensitive adds nothing
  new: a pattern-variable rename moves the digest directly (F6′).

## 3. User decisions (2026-09-13)

| # | decision |
|---|---|
| F1 | Direction A: the function-package constant's digest is built from its equations. |
| F2 | (revised 2026-09-13, after F3) The equations are **merged with** the `Defs` axioms, not substituted for them.  "Replace" had been chosen against double counting with `partial_function` under a `Spec_Rules` source.  Under the registry source nothing is counted twice, because the function package's own `Defs` axiom is body-free in every measured variant (VERIFICATION.md §2 rows 1–8, 15; CENSUS (a)–(f)) and the registry has only the two writers at `function.ML:136`/`:216`, so a body-carrying `Defs` axiom and a registry equation can never come from the same definitional act — a constant may hold both (the same-theory `overloading` family `sz` does: 3 `Defs` axioms + 2 simps, CENSUS (d)) but they then cover different type instances.  Merging keeps every sibling definition and needs no type conjunct. |
| F3 | Source = the function package's registry, not `Spec_Rules`; `simps` if present else `psimps`. |
| F4 | Theory criterion = the existing `same_theory`-filtered `Defs` axiom ("② non-empty"); no `Spec_Rules.dest_theory`. |
| F5 | `Spec_Rules` stays exactly as today: the fallback for `axiomatization` constants only. |
| F6′ | (replaces rev 1's F6) **Remove the alpha-normaliser**; keep the sort of a constant's props; fold this into the present work. |
| F7 | Tests, comments and the plan's details are the implementer's call. |

## 4. Change 1: the rule (`own_defining_axioms`)

```
① class parameter?  (class_param_of)          → []                (unchanged)
② Defs axioms of c, own theory only (same_theory)                  (unchanged)
③ NEW: ② non-empty AND the registry has an entry for c
        → props := ② ∪ (simps, or psimps when simps is NONE)
④ ② non-empty                                  → the Defs axioms   (unchanged)
⑤ Spec_Rules fallback (axiomatization)                              (unchanged)
```

③ adds a source; it never removes one.  A same-theory `overloading`
family that mixes a `fun` with `definition`s (AFP
`Amortized_Complexity/Pairing_Heap_List2_Analysis.thy:22-38`, `sz`) keeps
all its `Defs` axioms and gains the `fun`'s equations.

Implementation notes (rulings of the review applied):

- Lookup: one `Function_Common.retrieve_function_data (#ctxt env) q` per
  argument count `n` from 0 to the arity of `T` (`length (binder_types T)`),
  with `q = list_comb (Const (c, T), n Var placeholders)` — the bare
  constant at `n = 0`, `f ?x` at `n = 1` for the `context fixes` shape (§2;
  decided by the user 2026-09-13 as option A over querying with each Defs
  axiom's lhs, which was verified correct only with two extra guards
  against premise-carrying `resolve_prop` answers and `overloading`
  duplicates; the counts are disjoint, so no entry is returned twice; cost
  measured at 0.3 ms per heap pass, 0.07 % of `Test_All`'s whole pass) —
  with `ctxt = Proof_Context.init_global thy` added to the `env` record and
  built once in `make_env` (consistency with the file's per-pass env
  discipline, not performance — round-one elegance-4), and `T` the
  `Consts.the_constraint` type `sem_constant` already computed.  The type
  in the query is not a filter (the net drops it).  The answer is
  `(term * info) list`; keep only the entries the net indexed under this
  constant — `filter (fn (t, _) => case head_of t of Const (n, _) => n = c | _ => false)`
  then `map snd` — with the comment "the net also returns its wildcard
  branch; keep only entries keyed on this constant".  This drops
  wildcard-keyed entries (none exist in the heap today, CENSUS (g)); it is
  the same discipline `spec_rule_axioms` applies to its Item_Net answer
  (`mentions_const`), not an unconditional invariant.  For a mutual block
  `fun f and g` the one info (`fs = [f, g]`, all clauses) is stored under
  each key, so both constants carry the whole block (CENSUS (f)), an
  intra-theory SCC that `_EffStar` (`semantic_interpretation.py`) folds by
  design.
- Props are `(name, term)` pairs because the exported type demands it;
  nothing reads the name (`sem_constant` keeps `map snd`).  Label them
  `c ^ ".simps"` / `c ^ ".psimps"`; for a mutual block that label is not the
  name of any real fact.  The branch shares one comparator with the
  fallback (bind `prop_ord` once above `spec_rule_axioms`: name, then
  `Term_Ord.term_ord`; def2-4), so the order is `Term_Ord.term_ord` on the
  terms alone; the `Defs` branch's name-only sort at `:396` is untouched.
  ③ means the props of ALL entries that survive the key filter, sorted
  TOGETHER by `prop_ord`, so the result never depends on the order
  `Item_Net.retrieve` returned them (def-5); how the sorted ② and the
  sorted ③ are concatenated is the implementer's choice (deterministic
  either way).
- Dependency edges come from the props as today: a `fun` constant now
  depends on the constants of its equations in addition to today's
  recordless `f_sumC` edge (kept, limitation #6, harmless); on the psimps
  path also on `Wellfounded.accp` and on the concealed, recordless
  `<f>_rel`.
- No type test on the registry answer (withdrawn with the revised F2): a
  registration at another type instance of the same name is a definition
  of that constant too, and merging its equations is correct; a
  registration from a descendant theory is never visible in the declaring
  theory's env.
- Comments (short, load-bearing): the header of `semantic_digest.ML`; the
  block above `own_defining_axioms` (why the function package is special;
  the registry answer carries no theory of its own, so "② non-empty" is the
  only theory evidence; the branch is sound only when env's theory is the
  constant's declaring theory, which every production caller guarantees);
  the signature comment at `:63-65` restated (the propositions carrying a
  constant's own definitional content after the own-theory filter — its
  own-theory `Defs` axioms, plus, for a function-package constant, its
  equations from the registry — the first component a fact-like label, not
  necessarily a fact name).

## 5. Change 2: remove the normaliser

- `digest_term = Term_Digest.term128`; delete `norm_st`, `canon`,
  `norm_typ`, `norm_term`, `normalize`, the signature entry
  `val normalize`, the "alpha normalisation" header comment, and the
  `typ_payload` comment's "one alpha normaliser".
- The locale and type-abbreviation parameter payloads stay as they are
  (`Free (nm, T)` / `typ_payload`); the comments there that justify the
  encoding by "the same alpha canonicalisation as the body" are cut to what
  remains true (parameters as `Free` are invisible to `deps_of_term`, their
  types still contribute edges).  Renaming a parameter now moves the digest
  — by decision.
- `Test/Test_Sensitivity.thy`: S3e (`:99-127`) and S8a/S8b (`:182-204`) are
  the only callers of `Semantic_Digest.normalize` (`:122`, `:194`); apart
  from that call they compare hand-built terms and touch no production
  code, so once the call is gone they cannot detect a reintroduced
  normaliser (round-two elegance-2).  Two honest shapes, the choice is the user's
  (§8): (a) delete S3e and S8 with their subjects (`:68-69`, `:184-187`),
  delete the §14 row, and state that change 2 keeps no standing in-suite
  guard (the only two-sided evidence would then be §9 item 3 (iii)'s
  OBSERVATION of a `gate:`/`verdict:` line naming `galmuth`, since (ii)'s
  N > 26 is cleared by `narquil` alone); (b) export
  `val digest_term: term -> Term_Digest.digest128` from `SEMANTIC_DIGEST`
  (the function exists at `:178`; `val normalize` is being deleted, so the
  signature does not grow; precedent: `own_defining_axioms`, "exposed for
  the sensitivity suite") and keep ONE assertion
  `digest_term t = Term_Digest.term128 t` for a `t` containing a `Free`, a
  `TFree`, a schematic `Var` with a non-zero index and an `Abs` with a
  non-empty binder name (e.g.
  `Abs ("y", TFree ("'a", []), Free ("x", TFree ("'b", [])) $ Bound 0 $ Var (("v", 3), TFree ("'c", [])))`),
  which goes red under any of the transforms `normalize` performed, each
  on its own; S3e/S8 and their
  subjects are deleted either way, and the subsection title at `:182` and
  the block comment at `:99-107` go with them.  `Test/Test_All.thy`'s
  determinism block (`:113-128`) is one in-process pass repeated over the
  same `all` and `env`; it is green with and without the normaliser and is
  NOT a guard for change 2 (normaliser-1).
- `archive/plans/CHECK_OUTDATE_PLAN.md`: delete §7.3 item 3 ("参数归一化用
  TFree/Free"), change the §7.3 heading at `:349` from 四条 to 三条 and
  renumber the present item 4 to 3; §14 row at `:732` ("参数置换 vs 参数改名 |
  参数未与 body 同步归一化"): both cells rewritten under (b) — "参数改名使
  digest 变化（归一化已撤销，2026-09-13）| digest 在 hash 前被做了变换" — or
  the row deleted under (a); the glossary's `semantic digest` row gains
  "对改名不作不变处理".
- `Isabelle_Semantic_Embedding/semantics.py:318`: the record-schema comment
  "(ML-side Semantic_Digest; alpha-canonical)" loses "alpha-canonical".
- `doc/invalidation_limitations.md` (inside the gate entry #7, no new
  numbered entry) and `ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` §5: one
  sentence each — a rename now moves the digest, so the entity becomes a
  seed, is re-interpreted once and judged, answered UNCHANGED and walling
  its dependents WHEN the record carries a baseline; a record predating
  the gate (digest, no baseline) is forced CHANGED and mints
  (`SEMANTIC_CHANGE_GATE_PLAN.md` §3 row 2).  That is the designed path,
  not a defect.

## 6. Tests and documentation for change 1 (implementer's call, F7)

- `Test/Test_Sensitivity.thy`, new subsection "S? constant: function-package
  equations".  Subjects are declared immediately above the checks and the
  subsection builds its own env (`Semantic_Digest.make_env \<^theory>`) as
  S3 does at `:74-78`; the file-level env at `:20` predates them and the
  subjects are NOT hoisted above it (that would change the input of every
  assertion built on the file-level env).
  - `fun sens_fun` whose body mentions a constant absent from its type
    (`Orderings.ord_class.less`): `own_defining_axioms` has a prop mentioning
    it.  FAILS today (sole prop `sens_fun ≡ sens_fun_sumC`), PASSES after.
  - MERGE pin (merge-2), on `sens_fun` and repeated on `sens_pfun`: the
    props contain BOTH a Pure meta-equality (`exists (can Logic.dest_equals) ps`,
    the surviving `Defs` axiom) AND a prop that is not one (a `fun` simp is
    `Trueprop (… = …)`).  FAILS today (only the meta-equality), PASSES under
    merge, FAILS under replace, FAILS under any `_sumC` name filter — it
    pins both F2 and "nothing is filtered by name".
  - `function sens_pfun` without `termination`: the body-constant
    assertion, plus "mentions `Wellfounded.accp`" (discriminates: cannot
    arrive through a `nat ⇒ nat` subject's type).
  - `context fixes sens_k … fun sens_cfun`: under a `context fixes` block the
    fixed variable becomes a parameter on export and the registry key is the
    application `sens_cfun ?sens_k` (§2), which the bare-constant query misses
    and the per-argument-count lookup of §4 finds.  Assert the props mention
    `Groups.plus_class.plus` (discriminates: neither the exported type
    `nat ⇒ nat ⇒ nat` nor the body-free `Defs` axiom can supply it).  FAILS on
    the pre-option-A module, PASSES after.
  - Controls: a `primrec`, a `definition`, and a `partial_function (option)`
    keep exactly their `Defs` axiom (count and name) — the branch does not
    fire, and `partial_function` pins F3 against the `Spec_Rules` source.
  - No `instantiation` subject (it cannot discriminate, see §2); S2d/S2e stay
    as no-regression checks.
- `archive/plans/CHECK_OUTDATE_PLAN.md`: §14 table two rows (`fun` equations
  reach the digest; unterminated `function` reaches its psimps); §7.3 item 1
  gains the registry layer with the facts that make it undeletable (the
  function package's `Defs` axiom carries no body, so the equations are
  reachable only through the registry: the `Spec_Rules` item is nameless
  (`Binding.empty`, `function.ML:217`) and cannot pass `same_theory`, and an
  unterminated `function` has no `Spec_Rules` item at all; merged, not
  substituted, so sibling definitions of an `overloading` family survive).
  Edited by hand.
- `doc/invalidation_limitations.md`: a new numbered entry (with an index
  row) for the class "a constant whose own definitional content does not
  reach its own digest", listing the surviving shapes of §7 and pointing
  back to #6 for the dead-edge half (def1-2, implementer's choice: new
  entry); #6 gets the one sentence that function-package constants no
  longer depend on the `f_sumC` edge for their equations.
- `ai-artifacts/SEMANTIC_CHANGE_GATE_HANDOFF.md` top section: points here.

## 7. Known, deliberately left (change 1)

- **`fun`/`function` in a locale target** (measured, CENSUS (b)): the
  registry holds no key mentioning the locale constant or any of its
  `global_interpretation … defines` images, so the bare-constant query
  returns 0; the constant keeps its body-free `Defs` axiom and remains a
  limitation-#6 case.  Shipped instances: `Bit_Operations.fold2_bit_int.F`
  (the one record-eligible constant of the 20 that ③ does not reach) and
  the locale-level twin `…bit_operations.or_num` (`Infra("class_variant")`,
  no record anyway).  A `fun` in a CLASS body is reached through the class
  operation (`…_class.or_num`: 1 entry, 9 premise-free simps, CENSUS (c)).
- **`input_eqns`** (the registry's copy of the user's equations as written)
  was proposed twice as a uniform source and rejected twice (review rounds
  1 and 2): it is taken from the user's spec BEFORE the sequential
  preprocessor (`function.ML:74-81`), so with the sort kept a reorder of
  overlapping `(sequential)` clauses — a real change of the function —
  would leave the digest unmoved; its heads are `Free`s, which
  `deps_of_term` cannot see; nothing reads the field; Isabelle2024 lacks
  it.  Do not re-raise.
- **`termination` added or deleted** re-registers the info
  (`Item_Net.update`), so the digest of a function whose equations never
  changed moves once (one re-interpretation plus one judge call, dependents
  walled).  A `termination` proved in another theory never reaches the
  declaring theory's env: the constant keeps the psimps form, equation edits
  are still caught.  In a diamond import the registry keeps one info per
  function term, so a descendant env's answer depends on parent order when
  one parent proved `termination` and the other did not (production is
  never in that env).
- **Packages with their own registry**: a definitional package producing a
  body-free `_sumC` `Defs` axiom but writing its OWN registry is not reached
  by ③ and is a blind spot today; shipped instance Nominal2's
  `nominal_function` (`nominal_function_core.ML:1021`).
- `fun` inside `instantiation`: the instance constant is `Infra("inst_infix")`,
  no record.  A locale-level twin of a `fun` inside a `class` body carries
  the class predicate as premise; it is `Infra("class_variant")`, no record.
- Unterminated `function` uses psimps (with the `accp` premise) — by F3.
- Not measured, expected to carry a body in `Defs`: HOL `specification`,
  `lift_definition`, `quotient_definition`, `record` fields, AFP definition
  packages other than Nominal2.

## 8. Decided and open items

Decided by the user on 2026-09-13:

- The judge's type-conjunct proposal (def2-2) is withdrawn: with F2
  revised to MERGE, the `overloading` family it guarded against keeps all
  its definitions, and no type test is needed.
- End-to-end acceptance is PAID (user's choice over dropping it): a fresh
  copy of the production store holds no `Sim_Measure_A1` records, so a
  free dry run would count `narquil` as a seed merely for being uncached;
  the check therefore repeats the §10 acceptance's baseline (§9 item 3).
  Re-copying the production store for this purpose is authorised by that
  choice; the production store itself is never touched.

- Implementation review F1 (2026-09-13, evening): the `context fixes` shape
  (§2) is repaired by querying every argument count up to the arity —
  option A, chosen by the user over option B (query with each Defs axiom's
  lhs) after an Opus 5 agent verified B correct only with two guards and
  another measured A's cost at 0.3 ms per heap pass; test S13i.
- §5's (b) chosen (2026-09-13): `digest_term` is exported from
  `SEMANTIC_DIGEST` and one assertion `digest_term t = Term_Digest.term128 t`
  is the standing guard of change 2; S3e/S8 and their subjects are
  deleted; the §14 row is rewritten (both cells) as §5 says.

No open items.

## 9. Acceptance

1. `Test/Test_Sensitivity.thy` through the REPL server (no `isabelle
   build`): every new assertion §6 annotates as discriminating FAILS on the
   current code and PASSES after; §6's three controls, like S2d/S2e, pass
   both before and after; the change-2 guard is the one exception to
   "FAILS today" — it names `digest_term`, which today's signature does
   not export, so on unmodified code it errors rather than printing FAIL;
   to see it red first, add only the `val digest_term` signature line and
   run it while `normalize` is still in the pipeline.  All other
   assertions unchanged (S3e/S8 deleted per §5).  `Test/Test_All.thy`
   passes: no crash, resolution coverage ≥ 95 %, non-empty edge and digest
   counts (it prints the timing but bounds nothing; the registry query adds
   3–5 µs per constant, CENSUS).
2. Registry census: DONE pre-flight (CENSUS.md, 2026-09-13); §2 and §7
   carry its figures.  At implementation time re-run its heap query once
   with the shipped ML, reporting `class_param_of` and `own_defining_axioms`
   for each of the 38 in the same evaluation: the 32 non-parameters each
   gain their simps; the six class `fixes` parameters
   (`Quickcheck_Exhaustive.exhaustive_class.exhaustive`,
   `…full_exhaustive_class.full_exhaustive`,
   `Lazy_Sequence.small_lazy_class.small_lazy`,
   `Bit_Operations.semiring_bit_operations_class.{and,or,xor}`) keep
   `own_defining_axioms = []` by rule ① (as S2d/S2e assert for
   `Groups.plus_class.plus`); `fold2_bit_int.F` gains nothing.
3. Paid end-to-end (repeats `ai-artifacts/acceptance_step10/REPORT.md`'s
   setup with the new ML): `env.copy` of the production store to
   `/var/tmp/qiyuan/gate_accept_db/`, `SEMANTIC_DB_DIR` exported, driver
   `ClaudeCode.claude-opus-5`.
   (i) baseline run of `Sim_Measure_A1` (~USD 8); then a second `env.copy`
   of the store, so that (iii) can be repeated for ~USD 3 without
   re-paying the baseline.
   (ii) free dry run with `Sim_Measure_B`'s content under A1's name.  The
   dry run yields one number (`len(seeds)`, `semantic_interpretation.py:1757`;
   `Semantic_Store.dry_run : … -> string list * int`), not a seed set:
   the go/no-go is that N exceeds the 26 recorded for the same A1→B
   transition in acceptance_step10 run 2 (the two `fun` roots `narquil`
   and `galmuth` are new seeds; the count does not attribute).  If N does
   not rise, stop before paying (iii).
   (iii) live run (~USD 3).  PASS/FAIL: the host log shows a `gate:` or
   `verdict:` line naming `constant Sim_Measure_A1.narquil` (only sent
   entities produce one; neither `fun` root has an enrolment route in this
   scaffold), `narquil` is judged CHANGED and minted, and
   `narquil_small`/`narquil_large`/`narquil_glaive_*` are re-interpreted or
   have `interpreted_at` raised — the direct repair of acceptance_step10
   finding 1.  This criterion is safe because every failure mode of the
   gate reads CHANGED (`semantic_interpretation.py:1327-1330`): it fails
   only if the gate affirmatively finds the two texts the same, which would
   be a gate finding, not a refutation of this change.  OBSERVATION, not a
   criterion: `galmuth`'s line, its prefilter cosine and, if reached, the
   judge's sentence — the first live sample of the UNCHANGED path
   (acceptance_step10 finding 3); `galmuth` becomes a seed only because
   change 1 puts its renamed pattern variables into the payload AND F6′
   stops normalising them away (VERIFICATION.md §4: unmoved under change 1
   alone; its `Defs` axiom is variable-free, so unmoved under F6′ alone).
   Report in `ai-artifacts/fun_digest/ACCEPTANCE.md`; raw logs outside git.
4. Review as an Agent Workflow (Opus 5) after implementation; report in
   Chinese; commit on "提交".
