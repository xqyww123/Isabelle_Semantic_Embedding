# `explain_term` — Compact Term Printer Design

**Date**: 2026-05-21
**Status**: Prototype in `contrib/Isa-Mini/Test/Uncheck_Experiment.thy`
**Purpose**: Part of the planned `explain_term` MCP tool for the agentic deformalizer

## Goal

Given a checked Isabelle/HOL term (possibly with fancy syntax like `{x. P x}`, `let ... in ...`, `case ... of ...`, list syntax `[1,2,3]`, quantifiers `\<forall>x. ...`), produce a compact raw-lambda-expression string that:

1. Unfolds all syntax sugar to show the underlying constant applications
2. Contracts locale abbreviations (via `Syntax.uncheck_terms`)
3. Pretty-prints `case` and `let` expressions in readable form
4. Renders numerals as decimal integers (not `numeral (Bit0 (Bit1 One))`)
5. Resolves de Bruijn indices to named variables
6. Uses minimal, correct parenthesization

The output is meant for the deformalizer agent. Each constant in the output can then be looked up for its semantic interpretation via `query`.

## Architecture

### Entry point

```ml
fun raw_lambda_printer (ctxt : Proof.context) (t : term) : string
```

1. Sets `show_cases := false` in the context (prevents uncheck from expanding case combinators into the `case_guard/case_cons/case_elem/case_abs/case_nil` intermediate syntax)
2. Calls `Syntax.uncheck_terms ctxt' [t]` — this contracts abbreviations (including locale fixed-variable abbreviations) but preserves case combinators like `case_nat`
3. Calls `pt ctxt' [] false t'` to print the unchecked term
4. Concatenates the string list result

### `Syntax.uncheck_terms` behavior

- **Abbreviation contraction** (`contract_abbrevs` in `proof_context.ML:728-746`): Reverses abbreviation expansion. Example: in a locale with `fixes y`, `Const("locale.f") $ Free("y") $ Free("x")` becomes `Const("local.f") $ Free("x")`.
- **Case uncheck** (`Case_Translation.uncheck_case` in `case_translation.ML:594-597`): When `show_cases = true` (default), converts `case_nat True (\<lambda>n. False) a` into the intermediate `case_guard` form. We disable this with `show_cases := false` so the case combinator stays as-is, and our printer handles it via `Case_Translation.strip_case`.

### Core printer: `pt ctxt env parens t`

Returns `string list` (concatenated at the end — avoids O(n^2) `^` string concatenation).

Parameters:
- `ctxt`: proof context (needed for `Case_Translation.strip_case`)
- `env`: list of bound variable names from enclosing lambdas (head = innermost)
- `parens`: whether to wrap the output in parentheses
- `t`: the term to print

Detection priority (top to bottom):
1. **Numeral** — `HOLogic.dest_number t` returns `SOME (_, n)` for `0`, `1`, `numeral(Bit0 ...)`, etc. Printed as `string_of_int n`.
2. **Case expression** — `Case_Translation.strip_case ctxt false t` returns `SOME (scrutinee, [(pat, rhs), ...])`. Guarded by `can Term.type_of t` because `strip_case` calls `type_of` internally, which fails on terms with dangling `Bound` variables. Printed as `case scrutinee of pat1 => rhs1 | pat2 => rhs2`.
3. **Let expression** — pattern match on `Const("HOL.Let", _) $ value $ Abs(name, T, body)`. Printed as `let name = value in body`. Chained lets nest naturally: `let x = a in let y = b in c`.
4. **Const/Free/Var/Bound** — atoms, printed by name.
5. **Abs** — lambda, printed as `\<lambda>name. body`. The body is obtained via `Term.subst_bound(Free(name, T), body)` to replace `Bound 0` with a named `Free` (enables `strip_case` to work inside lambda bodies).
6. **Application** (`_ $ _`) — `strip_app` flattens left-associative application to `(head, [arg1, arg2, ...])`. Head and arguments parenthesized per `needs_parens`.

### Parenthesization rules

Three predicates control parenthesization:

**`is_atom t`** — true for `Const`, `Free`, `Var`, `Bound`, and numerals. These never need parens.

**`is_binder ctxt t`** — true for case expressions (detected by `strip_case`), `Let _ $ _ $ Abs _`, and bare `Abs _`. These need parens when they appear in positions where their keywords would bleed into surrounding syntax.

**`needs_parens a`** = `not (is_atom a)` — used for application head and arguments.

Parenthesization by position:

| Position | Condition for adding parens |
|----------|---------------------------|
| Top level | Never |
| Application head | `not (is_atom head)` — catches lambda-as-head: `(\<lambda>x. f x) y` |
| Application argument | `not (is_atom arg)` — catches nested apps: `f (g x) y` |
| Case scrutinee | `is_binder ctxt scrutinee` — catches: `case (case ...) of ...` |
| Case clause RHS | `is_binder ctxt rhs` — catches: `pat => (case ... of ...)` to prevent `|` ambiguity |
| Case clause pattern | Never (patterns are constructor applications) |
| Let value | `is_binder ctxt value` — catches: `let x = (let y = ...) in ...` |
| Let body | Never (extends to end, unambiguous) |
| Lambda body | Never (extends to end, unambiguous) |

### De Bruijn resolution

`resolve_bound env i` looks up index `i` in the `env` list (most recent binding at head). The `env` is extended when entering `Abs` and `Let` bodies. Since we also `subst_bound` in those cases, the `env` is only used as a fallback for unsubstituted `Bound` variables (shouldn't happen in practice).

The `subst_bound` approach is essential: it replaces `Bound 0` with `Free(name, T)`, which (a) makes `Term.type_of` succeed on the body (enabling `strip_case`), and (b) makes the variable name visible without needing the `env` lookup.

## Example outputs

```
Input (user syntax)                          | Output (raw_lambda_printer)
---------------------------------------------|-----------------------------------------------
f x (in locale with fixed y)                 | f x
map Suc (filter (\<lambda>x. x > 0) [1,2,3::nat])  | map Suc (filter (\<lambda>x. less 0 x) (Cons 1 (Cons 2 (Cons 3 Nil))))
\<forall>x::nat. \<exists>y. x + y = 0                      | All (\<lambda>x. Ex (\<lambda>y. eq (plus x y) 0))
{x::nat. x \<in> S \<and> x > 0}                     | Collect (\<lambda>x. conj (member x S) (less 0 x))
my_add a b (abbreviation for a + b + 1)     | my_add a b
case xs of [] => 0 | x#rest => Suc (f rest)  | case xs of Nil => 0 | Cons x rest => Suc (f rest)
let a = Suc 0 in case a of 0 => ...          | let a = Suc 0 in case a of 0 => True | Suc n => False
case x of 0 => (case y of ...) | Suc n => 3  | case x of 0 => (case y of True => 1 | False => 2) | Suc n => 3
let x = (let y = 1 in y+1) in x*2            | let x = (let y = 1 in plus y 1) in times x 2
case (case b of ...) of 0 => True | ...       | case (case b of True => 0 | False => 1) of 0 => True | Suc n => False
```

## Key Isabelle references

### Syntax.uncheck_terms
- **Definition**: `/home/qiyuan/Downloads/Isabelle2025/src/Pure/Syntax/syntax.ML:264-265` — delegates to registered uncheck phases
- **Abbreviation contraction**: `/home/qiyuan/Downloads/Isabelle2025/src/Pure/Isar/proof_context.ML:728-746` — `contract_abbrevs`
- **Pretty printing pipeline**: `pretty_term ctxt = singleton (uncheck_terms ctxt) #> unparse_term ctxt` (syntax.ML:335)

### Case translation
- **`Case_Translation.strip_case`**: `/home/qiyuan/Downloads/Isabelle2025/src/HOL/Tools/Ctr_Sugar/case_translation.ML:571-574` — extracts `(scrutinee, [(pat, rhs)])` from case combinator applications
- **`Case_Translation.show_cases`**: same file, line 592 — config bool controlling whether uncheck expands case combinators
- **`case_guard/case_cons/case_elem/case_abs/case_nil`**: intermediate syntax constants defined in `/home/qiyuan/Downloads/Isabelle2025/src/HOL/Ctr_Sugar.thy:18-23` — exist only between uncheck and unparse; we avoid them by setting `show_cases := false`
- **`uncheck_case`**: same ML file, lines 594-597 — the uncheck phase that calls `strip_case_full`; guarded by `can Term.type_of`

### Let
- **Definition**: `/home/qiyuan/Downloads/Isabelle2025/src/HOL/HOL.thy:232-233` — `Let s f = f s`
- **Syntax translation**: same file, line 249 — `let x = a in e` translates to `CONST Let a (\<lambda>x. e)`
- Chained `let x = a; y = b in e` desugars to `Let a (\<lambda>x. Let b (\<lambda>y. e))`

### Numerals
- **`HOLogic.dest_number`**: `/home/qiyuan/Downloads/Isabelle2025/src/HOL/Tools/hologic.ML` — destructs `0`, `1`, `numeral(Bit0/Bit1/One)` to `(typ, int)`
- Internal representation: `numeral (Bit1 (Bit0 One))` for 5, `Suc (Suc ...)` NOT used for large numbers

### Raw term printing (for reference, NOT used)
- **`ML_Syntax.print_term`**: `/home/qiyuan/Downloads/Isabelle2025/src/Pure/ML/ml_syntax.ML:124-130` — verbose output with full `Term.Type(...)` annotations; we built our own printer to avoid this

### Existing usage of Syntax.uncheck in the project
- `/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/Tools/Sledgehammer/sledgehammer_embedding_ctxt.ML:553` — `singleton (Syntax.uncheck_terms ctxt) term0` used before constant extraction

## Integration plan for the `explain_term` MCP tool

### ML side (new RPC command)
The printer will live in `contrib/Semantic_Embedding/Tools/` as a new ML file. The RPC command accepts:
- `term_string`: the term to explain (parsed via `Syntax.read_term`)
- `context_at`: optional `(file, line, column)` for position-based context resolution (reuses the `context_at_position` mechanism from `position_context_resolution.md`)

It returns:
- The compact printed term (unchecked, via `raw_lambda_printer`)
- A list of non-infrastructure constants appearing in the **checked** term (for semantic lookup), extracted via `Term.fold_aterms` on the checked term, filtered by `Infra_Filter.gen_infra_filters`

The constant names come from the **checked** (not unchecked) term because:
- The checked term has real constant names like `Uncheck_Experiment.my_locale.f`
- The unchecked term may have `local.f` which doesn't resolve in theory context
- `Universal_Key.key_of` needs the real name

### Python side (new MCP tool)
Following the existing pattern in `semantics.py`:
- Factory function `mk_explain_term_tool(connection, ...)` returns an `SdkMcpTool`
- Input schema: `{term: string, context_at?: {file, line, column}}`
- Output: compact term string + semantic interpretations of each non-trivial constant
- Per-session cache of "already explained constants" (like `seen_entities` in AoA) to avoid repetition; reset on compaction via `PreCompact` hook / `_reset_view_state()`

### Error handling
- Parse errors: plain text, reuse Isabelle's error message
- Ambiguity: take first line of error, strip `(N displayed)` suffix (pattern from `_clean_warning` in `contrib/Isa-Mini/IsaMini/AoA/model.py:26-31`)
- Well-typed-unique ambiguity (warning only): ignore, Isabelle picks the right parse

### Constant filtering
Filter out infrastructure constants using the session-based approach from `infra_filter.ML`:
- `Long_Name.qualifier (Context.theory_long_name thy)` extracts session name
- Constants from Pure, HOL, Main sessions are filtered
- `Infra_Filter.gen_infra_filters` provides `is_infra_const` for fine-grained filtering

### Tool name
Recommended: **`explain_term`**

## Prototype location
`/home/qiyuan/Current/MLML/contrib/Isa-Mini/Test/Uncheck_Experiment.thy` — full working code with 13 test cases covering locale abbreviation, case, let, numerals, quantifiers, set comprehension, nested structures, and adversarial parenthesization edge cases.
