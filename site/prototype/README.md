# Tokenizer prototype — validated, not production, and now PRE-D43

These three files are the measured prototype behind §5 and D41 of
`SEMANTIC_SEARCH_SITE_PLAN.md`. Every number in §3.6 (index size, separator-class
coverage, the `x⇩i` query result) was produced by running them. They are kept
because the plan carries the rule in prose only, and prose loses the edge cases.

- `subtoken_rule.py` — the settled separator class and the `subtokens`
  implementation, including the fallback clause for a token made entirely of
  rendered sub/superscript characters. The class is 99 characters and each third
  of it comes from somewhere different: `_` and `.` are ASCII literals in the
  rule, seven control symbols are read from a symbols file by name, and the other
  90 are what `SUBSUP_TRANS_TABLE` — a hand-maintained dict in
  `Isabelle_RPC_Host/unicode.py` — produces from `⇩` and `⇧`. No symbols file
  carries folding information of any kind, so "derived from `etc/symbols`" is not
  a true description of the class and an earlier version of this file said it was.
- `tokenize_prototype.py` — `tokenize`, plus the older and intermediate subtoken
  variants that the measurements compared against.
- `corpus_probe.py` — counts how many entities a syntactic condition matches, over
  the real corpus. It is what reproduces every match count quoted in the plan and
  in `site/COPY.md`, and the plan's §16.1 requires it to be used rather than a
  freshly written probe, a second probe being a second implementation of the
  matching rule.

## These files implement the pre-D43 rule

**D43 (2026-08-18) defines the tokenizer over characters and deletes the
`symbol_explode` step**, which `tokenize_prototype.py` still calls; and §5.2 says
the `letter`/`greek` groups of `etc/symbols` are not consulted, which its
`_is_letter` still consults. Measured on 2026-08-19:

- The `symbol_explode` difference is **exactly the 3,135 expressions D43 names**.
  The two definitions agree on the other 1,358,961, element for element.
- The letter-group difference is **nothing at all**: all 190 group members satisfy
  `isalpha()`, and every one has a code point that step 3 substitutes before token
  formation sees it.
- The plan's §16.2 and §5.3 (11 relations) were re-run under **both** definitions
  with **zero mismatches under either**. That re-run covered the 32 cases §16.2 held
  on 2026-08-19; the table has 33 now, the added row being the repair of the one case
  that named `\<alpha>` as an unconverted escape and could therefore never pass.

So these files remain sound as the measuring instrument for match counts, and they
are **not** a specification of the tokenizer. Where they and §5 disagree, §5 wins.

## The frozen baseline

`baseline/` holds the prototype's tokenization of the whole corpus, taken once and
stamped. It exists because these files read a **live** symbol table through a **live**
`Isabelle_RPC_Host` import, so an acceptance test that re-runs them is a claim about
the day it ran rather than something anyone can re-check later. The user approved
freezing it on 2026-08-19.

- `baseline/asset.json` — the exact asset the run used, so the comparison needs
  nothing from the environment.
- `baseline/baseline.json` — provenance (which store, which symbol files, which
  `Isabelle_RPC` revision, which Unicode version), the whole-corpus digests, every
  count, and in full every record that is neither a pure refinement nor a pure merge.
- `baseline/baseline.classes.zst` — one byte per record per change per field, in the
  key order the digests use, so a later run can say *which* record moved rather than
  only that one did.
- `baseline/build_baseline.py` — what produced all three. Re-running it on a store
  whose digest matches `store_digest` must reproduce them byte for byte.

## What replaces them

`Isabelle_Semantic_Embedding/isabelle_tokenizer.py` — step 1 of the plan's **§16.3**
build order (§15.3, which an earlier version of this file cited, has moved into
`SEMANTIC_SEARCH_SITE_PLAN_DONE.md` and is superseded). **Written 2026-08-19**, with
`tokenizer_asset.py` beside it to build what it reads and
`test_isabelle_tokenizer.py` to run §16.2 and §5.3 against it. It reads its character
classes and its two tables from the one stamped asset (D45) rather than from Python
built-ins and a live `Isabelle_RPC_Host` import, which is what makes the JavaScript
port possible, and it drops `symbol_explode` per D43. **Delete nothing here until
the CI gate of §16.6 is green.** Until then this directory is the only executable
statement of anything.

Run any file directly to see the classes and a table of worked examples.
