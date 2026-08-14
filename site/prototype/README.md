# Tokenizer prototype — validated, not production

These two files are the measured prototype behind §5 and D41 of
`SEMANTIC_SEARCH_SITE_PLAN.md`. Every number in §3.6 (index size, separator-class
coverage, the `x⇩i` query result) was produced by running them. They are kept
because the plan carries the rule in prose only, and prose loses the edge cases.

- `subtoken_rule.py` — the settled separator class (99 characters, derived from
  `etc/symbols`, nothing hand-written but `_`, `.` and seven symbol names) and
  the `subtokens` implementation, including the fallback clause for a token made
  entirely of rendered sub/superscript characters.
- `tokenize_prototype.py` — `tokenize`, plus the older and intermediate subtoken
  variants that the measurements compared against.

`isabelle_tokenizer.py` (§15.3 step 1) replaces both. It must read its character
classes from the emitted assets rather than from Python built-ins and from a
live `Isabelle_RPC_Host` import, which is what makes the JavaScript port
possible. Until it exists, this directory is the only executable statement of
the rule.

Run either file directly to see the classes and a table of worked examples.
