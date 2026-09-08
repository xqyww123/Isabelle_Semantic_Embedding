# Uninterpreted constants: a second, weaker verdict for the infrastructure filter

Started 2026-08-30. Revision 2, after a two-round adversarial review (two Opus 5
reviewers); the owner's rulings of 2026-08-30 are folded into the body.
Implemented 2026-08-30 and revised after a second two-round review of the code;
`Test/Infra_Decl_Test.thy` and `Test/SSymb_Infra_Test.thy` pass through Isa-REPL
(base `Minilang`, `Semantic_Embedding` loaded from source). The typedef
morphism's full name is `SSymb.symbol.mk_symbol`, not `SSymb.mk_symbol`.

## 1. Glossary

- **Infrastructure constant** — a constant judged to be machinery (`infra_filter.ML`,
  `infra_const_rule`). It gets no record in the semantic database, it is not
  interpreted, and it **cascades**: any theorem whose statement mentions it is
  judged infrastructure too (`infra_thm_rule`, bucket `"const:<name>"`). Declared by
  the user with `declare [[infra_constant c]]`, by a theory marking, or by a
  built-in rule.
- **Uninterpreted constant** (new) — a constant that gets no record and is not
  interpreted, but does **not** cascade: theorems mentioning it are judged on their
  own. Declared with `declare [[uninterpreted_constant c]]` or by a theory marking.
- **Verdict** (new) — the judgement on one constant: `Kept`, `Uninterpreted`, or
  `Infra`. The verdicts are not ordered by the code; the only relation between
  them is the one the two projections below express.
- **Theory marking** — the enumerated table of theory long names whose own
  entities get no record (`infra_filter.ML:56`, today a set). It becomes a table
  from theory long name to the verdict of that theory's constants.
- **Cascade** — the rule that a theorem mentioning an infrastructure constant is
  infrastructure. Unchanged; it just does not apply to uninterpreted constants.

## 2. Problem and status quo

The constant judgement is a single yes/no (`infra_const_rule : string -> typ
option -> string option`, `infra_filter.ML:454`), read with two meanings:

1. "does this constant get a record / an interpretation?" — `is_infra_const`
   (`semantic_store.ML:1403`, `:1463`; `explain_term.ML:106`);
2. "does mentioning this constant make a theorem infrastructure?" —
   `is_internal_constant` (`infra_filter.ML:571`, file-local), feeding
   `first_internal_const` in `infra_thm_rule` (`:582`).

There is no way to say "skip this constant, but keep the theorems that mention
it". The motivating case is the runtime-symbol theory
`Performant_Isabelle_HOL.SSymb` (`Performant_Isabelle_ML/HOL/SSymb.thy`): its
digits `Z`, `A` … `F` and `mk_symbol` are process-local numerals with nothing to
interpret, while the theorems mentioning them (phi-system aggregate lemmas over
named fields, printed as `SYMBOL(foo)`) are ordinary, retrievable mathematics.

Measured status quo (2026-08-30, Isa-REPL over `Minilang_AoA`): `SSymb.Z`, `A`,
`F`, `mk_symbol` are **Kept** today — they get records and interpretations; only
the hidden `Abs_symbol` is rejected (`hidden`); a lemma stating
`AG_IDX(SYMBOL(foo)) = AG_IDX(SYMBOL(foo))` is Kept. So nothing is lost today.
What this change buys: the SSymb constants and SSymb's own lemmas (`Z_def`,
`A.rep_eq`, the digit disequalities — all statements about process-local
numerals) stop consuming interpretations, with zero change to any theorem
outside `SSymb` on the measured corpus (the marking is consulted before the
built-in rules, so `Abs_symbol` moves from `Infra "hidden"` to `Uninterpreted`
and no longer cascades; nothing outside `SSymb` mentions it); and
`infra_constant` / `uninterpreted_constant` become a vocabulary for the next
case of this shape. No semantic database has collected `SSymb` records (owner,
2026-08-30), so no records need deleting.

Known, pre-existing, out of scope: `Universal_Key` / `Term_Digest` hash a
`Const` by its internal name (`Isabelle_RPC/Tools/Universal_Key.ML:591`) and do
not canonicalise symbol numerals through `Phi_Tool_Symbol.dest_symbol`, so keys
of propositions containing a literal symbol may depend on the process. This plan
neither creates nor changes that; it is tracked separately.

## 3. Design

### 3.1 One verdict type, two projections

In `infra_filter.ML`, exported through `INFRA_FILTER`:

```sml
(*The judgement on a constant.  The string names the rule that decided, for
  diagnostics.  Uninterpreted and Infra both deny the constant a record; only
  Infra makes theorems mentioning the constant infrastructure.*)
datatype const_verdict = Kept | Uninterpreted of string | Infra of string

val why_of_verdict : const_verdict -> string option   (*Kept => NONE*)
```

The two existing predicates become the two projections, and are the only
readers of the constructors outside diagnostics:

```sml
fun is_uninterpreted_const name = (case infra_const_rule name of Kept => false | _ => true)
fun cascades_const (name, _ : typ) = (case infra_const_rule name of Infra _ => true | _ => false)
```

- `is_infra_const` is **renamed** `is_uninterpreted_const` (owner ruling): the old
  name would return true for constants the glossary says are not infrastructure.
  Its meaning at every call site — "no record, no interpretation" — is unchanged.
  Call sites: `semantic_store.ML:1403`, `:1463`; `explain_term.ML:88,106`;
  `Test/Infra_Test.thy`, `Test/Test_All.thy`, `Test/Infra_Decl_Test.thy`;
  `Isa-Mini/Test_InfraFilter/Test_LTE_InfraFilter.thy`;
  `Isa-Mini/Agent/ScratchInfraStudy.thy`.
- `is_internal_constant` is renamed `cascades_const` (file-local: `:571`, `:578`);
  "internal" already names the unrelated `is_internal_class`.
- `infra_const_rule` loses its `typ option` parameter, documented as dead at
  `:450-453`; that comment's decision to keep it for the callers' signature is
  overturned because every caller is edited here anyway.

### 3.2 The theory marking carries a verdict

`infra_theory_long_names : Symtab.set` becomes
`marked_theories : const_verdict Symtab.table`. Every existing entry maps to
`Infra "infra_theory"` (the rule name is unchanged, so the archived measurement
buckets still match). One entry is added:

```
"Performant_Isabelle_HOL.SSymb" ↦ Uninterpreted "uninterpreted_theory"
```

The consumers that ask only "is this theory marked?" — `is_marked_theory`
(renamed from `is_infra_theory`, exported; sole caller
`tasks/AoA-learning/learning.ML`, which therefore now also skips SSymb's proofs
when harvesting experiences — acceptable, they are `transfer`/`simp` proofs
about numerals), and the fact / type / class / locale rules through
`is_from_marked_theory` (renamed from `is_from_infra_space`) — keep reading
membership: a marked theory's own entities of every kind get no record, whatever
the verdict on its constants. Only rule 2 of the constant chain reads the stored
verdict, through `theory_marking_of`. Effect for SSymb: its constants are
uninterpreted and do not cascade; its own lemmas and the type `symbol` get no
record; every theorem in a downstream theory is judged exactly as today.

Matching is by the declaring theory recorded in the name-space entry (`:217-224`),
so renaming a digit cannot switch the marking off — no string copy of
`Phi_Tool_Symbol.digits`, no tripwire.

### 3.3 The declaration store

`Infra_Decl` (`:115`) currently holds `Symtab.set * thm iNet.net * Symtab.set`.
The constant component becomes `const_verdict Symtab.table`: one constant, one
verdict. The store never holds `Kept` (no attribute produces it; a comment says
so).

Sequential re-declaration in one theory is last-wins (`Symtab.update`), like
`simp` / `simp del`. On theory merge, two different verdicts for the same
constant produce a `warning` naming the constant and both verdicts, and the first
parent's verdict is kept — which is what `Symtab.merge (K true)` does today, so
no ordering between verdicts is introduced anywhere.

### 3.4 The attributes

`infra_constant` keeps its syntax and meaning (stores `Infra "declared"`).
`uninterpreted_constant` is new, same syntax (repeated constants, optional
leading `del`), stores `Uninterpreted "declared"`. Both are one parser:

```sml
fun const_decl_attr verdict =
  (del_flag -- Scan.repeat1 (Args.const {proper = true, strict = false})) >>
    (fn (del, ns) => infra_decl_attr (fn (c, t, y) =>
       (fold (if del then Symtab.delete_safe else fn n => Symtab.update (n, verdict)) ns c,
        t, y)))
```

`del` on either attribute clears whatever verdict the constant has.

A declaration reaches a target theory only if that theory imports the declaring
theory: the collector interprets each target in its own `Context.Theory`
(`semantic_interpretation_app.ML:114`). For SSymb this is why the theory
marking (§3.2) is used rather than a `declare` somewhere downstream.

### 3.5 `infra_const_rule`

Returns `const_verdict`. The chain (`:454-512`) keeps its order:

1. the declared verdict, if any (`Symtab.lookup decl_consts name`);
2. the theory marking's verdict, if the constant's declaring theory is marked;
3. the `preserved_set` veto → `Kept`;
4. the built-in heuristic rules → `Infra why` for the first that fires, else `Kept`.

Every built-in rule stays `Infra`. The cache `infra_const_cache` stores the
verdict; same keying.

### 3.6 The persistent-cache re-filter

`is_declared_infra_thm` (`:684`) reproduces the declaration-driven theorem drops
for the persistent theorem caches (`semantic_store.ML:1309-1327`). It stays
declaration-scoped — its comment promises "exactly the decl-driven drops … and
nothing else" — and its constant clause becomes
`case Symtab.lookup decl_consts n of SOME (Infra _) => true | _ => false`.
(Routing it through `cascades_const` was considered and rejected: that would
make the cache filter's behaviour depend on whether an unrelated declaration
exists, and would move the `inst_infixes` type-name scan onto the cache path.)

`has_infra_decls` is **deleted**. The record field becomes
`is_declared_infra_thm : (string * thm -> bool) option`, `NONE` when no
declaration can make it fire (no theorem declaration and no `Infra` constant
declaration). The gate at `semantic_store.ML:1320` becomes the presence of the
function, so gate and predicate cannot disagree; the stale inclusion of
`decl_types` in the old gate (`:199-201`) disappears with it.

### 3.7 Diagnostics

`Test/Infra_Filter_Step1_Measure.thy` (`:29`, `:40-44`, `:52`) and
`Test/Infra_Filter_Step1_EC.thy` (`:35`) pattern-match the old `string option`.
They use `why_of_verdict`: `Kept` is still skipped when bucketing, and the
cascade bucket keys stay `"cascade/" ^ why`, so the output still diffs against
`archive/data/INFRA_FILTER_STEP1_*.tsv` and `INFRA_FLIP_SET.tsv`.

### 3.8 Comments, documentation, tests

- Comments stating the old two-valued invariant are rewritten: the signature
  comment (`:18-24`, "`is_infra_*` is `is_some` of these"), the `Infra_Decl`
  comment (`:104-114`, "a declared infra constant behaves identically to a
  built-in … filtered AND cascading" — now true of `infra_constant` only), the
  theory-marking comment (`:31-55`), and `:450-453`.
- `README.md` §7.2: `uninterpreted_constant` stated as the equation
  "`infra_constant` = `uninterpreted_constant` plus the cascade to theorems
  mentioning it", and `del` noted as clearing the verdict whichever attribute set
  it.
- `Test/Infra_Decl_Test.thy`: a block declaring `[[uninterpreted_constant List.rev]]`,
  asserting `is_uninterpreted_const "List.rev"` and **not** `is_infra_thm (foo)`;
  `del`; sequential last-wins (`infra_constant` then `uninterpreted_constant` →
  `foo` kept). The `has_infra_decls` assertion becomes `is_none is_declared_infra_thm`.
  Theory merge is not tested (it needs two auxiliary theories); the merge code is
  three lines.
- `Test/SSymb_Infra_Test.thy`, in the `Semantic_Embedding_Test` session
  (`Test/ROOT` gains `sessions Performant_Isabelle_HOL`), importing
  `Semantic_Embedding` and `Performant_Isabelle_HOL.SSymb` directly (sibling
  sessions over HOL, no cycle): asserts that the digits and `mk_symbol` are
  `Uninterpreted "uninterpreted_theory"`, that an SSymb-own fact is rejected by
  exactly the rule `"infra_theory"` (the bucket name covers both markings, kept
  for the archived measurements), and that a lemma mentioning `SYMBOL(foo)` is
  not `is_infra_thm`.
- `doc/invalidation_limitations.md` defect 6: one sentence that uninterpreted
  constants join the population of dependency targets without a record.

## 4. Change inventory

| File | Change |
|---|---|
| `Semantic_Embedding/Tools/infra_filter.ML` | datatype, `why_of_verdict`; `marked_theories` table + SSymb entry; `Infra_Decl` constant table, merge warning; `const_decl_attr`, second `Attrib.setup`; `infra_const_rule` return type and parameter; `is_uninterpreted_const`, `cascades_const`; `is_declared_infra_thm` option; signature and comments |
| `Semantic_Embedding/Tools/semantic_store.ML` | `:1301-1324` (option gate), `:1403`, `:1457-1463` (rename) |
| `Semantic_Embedding/Tools/explain_term.ML` | `:88`, `:106` (rename) |
| `Semantic_Embedding/Test/Infra_Decl_Test.thy` | rename; new blocks (§3.8) |
| `Semantic_Embedding/Test/Infra_Filter_Step1_Measure.thy`, `…_EC.thy` | `why_of_verdict` |
| `Semantic_Embedding/Test/Infra_Test.thy`, `Test/Test_All.thy` | rename |
| `Semantic_Embedding/README.md`, `doc/invalidation_limitations.md` | §3.8 |
| `Isa-Mini/Test_InfraFilter/Test_LTE_InfraFilter.thy`, `Isa-Mini/Agent/ScratchInfraStudy.thy` | rename |
| `Semantic_Embedding/Test/SSymb_Infra_Test.thy`, `Test/ROOT` | new SSymb test theory, registered |
| `tasks/AoA-learning/learning.ML` | `is_marked_theory`; comment records that uninterpreted theories are skipped too |

## 5. Out of scope

- Reclassifying any built-in heuristic rule as `Uninterpreted`.
- Types (`infra_type`) — no cascade exists for types, so no second level.
- The `Universal_Key` / `Term_Digest` symbol-numeral hazard (§2).
- Rejected alternatives, so they are not re-proposed: a built-in rule matching
  the seven digit names as strings (a fourth copy of `Phi_Tool_Symbol.digits`,
  silently rotting on rename, untestable from `Semantic_Embedding`'s own tests);
  a `declare` in `Minilang_AoA.thy` (reaches phi-system, but not the theories
  between `SSymb` and `Minilang_AoA`, and leaves SSymb's own lemmas interpreted);
  moving the declaration store below `SSymb` into `Performant_Isabelle_HOL`
  (moves retrieval vocabulary into the data-structure repository for no gain
  once the marking exists); an ordering between verdicts with "stronger wins"
  on merge (silently deletes what one branch deliberately kept).
