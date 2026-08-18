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
- The plan's §16.2 (32 cases) and §5.3 (11 relations) were re-run under **both**
  definitions with **zero mismatches under either**.

So these files remain sound as the measuring instrument for match counts, and they
are **not** a specification of the tokenizer. Where they and §5 disagree, §5 wins.

## What replaces them

`Isabelle_Semantic_Embedding/isabelle_tokenizer.py` — step 1 of the plan's **§16.3**
build order (§15.3, which an earlier version of this file cited, has moved into
`SEMANTIC_SEARCH_SITE_PLAN_DONE.md` and is superseded). It must read its character
classes and its two tables from the one stamped asset (D45) rather than from Python
built-ins and a live `Isabelle_RPC_Host` import, which is what makes the JavaScript
port possible; and it must drop `symbol_explode` per D43. **Delete nothing here until
the CI gate of §16.6 is green.** Until then this directory is the only executable
statement of anything.

Run any file directly to see the classes and a table of worked examples.
