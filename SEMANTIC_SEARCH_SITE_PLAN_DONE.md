# Finished work, moved out of SEMANTIC_SEARCH_SITE_PLAN.md

Sections whose work is done. They are kept because the reasoning and the measurements
behind a finished decision are still evidence — several later sections cite them — but
they are no longer things anyone has to read to know what to do next.

The live plan is `SEMANTIC_SEARCH_SITE_PLAN.md`. Section numbers here are the ones it
used, so a citation like "§15.3" still resolves; it resolves to this file.

Moved 2026-08-18.

---

## 10. Repairing U+007F

### 10.1 Root cause

`command_spans_of_file` in `Tools/pide_state.ML` builds a command's source with
`Token.source_of`. For tokens that carry delimiters — `"…"`, `` `…` ``,
cartouches, comments — `source_of` returns Isabelle's *internal* representation,
in which each consumed delimiter symbol is replaced by `Symbol_Pos.DEL`
(U+007F) as position padding. `Token.unparse` is the function that reconstructs
the source. The comment above that line, asserting `source_of` is verbatim, is
wrong. This is the only `Token.source_of` call in the repository.

Reproduced under `isabelle ML_process`:

```
source_of : type_synonym eq = \127('f, 'v) term * ('f, 'v) term\127
unparse   : type_synonym eq = "('f, 'v) term * ('f, 'v) term"      byte-identical to source
```

Only the fallback path is affected; the live PIDE path goes through Scala's
`command.source` and is clean. Only the five source-text kinds can be affected,
which matches the data exactly: TYPE 221, LOCALE 11, CLASS 4, METHOD 2.

Blast radius: **238 of the 15,723 records that carry source text (1.5 %)**, in
109 theories — of which only **48 records in 14 theories are real AFP or
Isabelle content** (`Example_PIL` 14, `Amortized_Examples` 7, `Enumeration` 6,
`Example_SOL` 4, `Example_Bounded_FOL` 4, and ten more with 1–2 each). The other
190 are in why3/NTP4VC generated working files.

### 10.2 The repair

Reconstruct the true text from the theory source rather than guessing a
mapping. Split the stored expression on U+007F; join the fragments with a
pattern matching exactly one Isabelle symbol (`(?:\\<[^>]*>|.)`), because one
DEL stands for one deleted *symbol*, not one character; search the theory file
(after `unicode_of_ascii`) for that pattern.

**Dry run result: 238 of 238 reconstructed, zero ambiguity.** Six expressions
matched in more than one place, but every match was textually identical, so
those are determined too. No rule-based fallback is needed.

190 of the 238 currently have vectors; `update_expr` invalidates them and the
lazy cache refills them. The interpretations are unaffected and must not be
re-run: spot checks show the interpreting agent read the DEL correctly as a
delimiter.

---

## 13b. Reader testing of the interface copy, 2026-08-14

Four readers were given **only** the visitor-facing text — an Isabelle user, a
Lean/Coq user, a reader assessing it for a non-native-English audience, and a
hostile copy reviewer. **All four returned "not fit to use as written."**
The material findings, kept because they are cheap to lose and expensive to
rediscover:

**The empty-state page demonstrates a failure that does not occur.** It shows
`?P ⟹ ?Q` returning nothing and explains that "almost no statement names a
constant `P` immediately before `⟹`". Measured on the real corpus: after D4
discards `?`, that condition is the subtoken run `['P','⟹','Q']`, and it
**matches 60 records** — `IFOL.iffI`, `FOL.case_split`, `IFOL.contrapos` among
them. The premise is false, and this is the only empty state the design has.

**Five further statements are false.** "Theorems have no declaring theory" —
true of this index, false of Isabelle, and read by three of the four readers as
evidence the site is broken. "An adjacent run of Isabelle tokens" — `sorted_wrt`
is one token; the unit is subtokens, and the real rule appears only inside an
error message. "It does not match inside a name: `sorted` finds `sorted_wrt`" —
the example refutes the rule. "Matched literally … Case-sensitive" — four
transformations precede matching, so the always-visible panel line teaches the
model the empty state then has to correct. And `sledgehammer` offered as a
term-pattern search tool, which it is not.

**"Try instead: `⟹`" is a locked exit.** `⟹` is in 42.35 % of documents, so the
suggested filter narrows nothing; and a reader who cannot type the glyph finds
the ASCII escape four lines away, in a checklist that never says `==>` *is* `⟹`.
The Lean reader named this the exact line at which they would leave.

**The commonest failure has no copy at all.** Four repeatable condition
sections, and the words "and" and "or" appear nowhere about them. Conditions
AND-ing down to zero is the modal outcome of this panel, and there is no empty
state for it.

**Terminology is unstable in the copy** even where §1's glossary is stable:
filter/condition/row for two levels of structure, `expression` for three
different things, six kinds named on the landing page against eleven chips, and
"Collection" defined nowhere.

Seven things the readers exposed that are **design, not wording**, and are open:
whether variable names are indexed at all; how conditions combine within and
across sections, and what the Kind chips do; whether `Introduction rule` is
disjoint from `Theorem` (under the reversed D5 it is, so selecting `Theorem`
misses the intro-rule record of the same statement); what the similarity score
compares, given the vector is built over `pretty_print` plus the interpretation,
so ranking rests partly on machine-written prose the disclaimer only warns about
for *reading*; short versus long name in `Entity Name`; what "expression"
denotes for a non-theorem kind; and whether the site states the Isabelle
release, AFP snapshot and index date — absence of a result being this product's
primary output, and uninterpretable without them.

---

## 15. Implementation handover, 2026-08-14

Written at a context boundary. Everything needed to resume is here; nothing
below should have to be re-derived from the conversation that produced it.

### 15.0 Where the work stands

D1-D42 are settled and §13 has no open questions. §12.2 shows the dependency
chain: the site export is blocked on three prerequisites owned outside this plan
(the key repair, the theory-hash registry, entity positions in the published
snapshot). **Two pieces are unblocked and are the immediate work: the interface
copy with the mockup, and the tokenizer freeze.**

**Superseded on 2026-08-14 — everything is committed**, in the submodule and in
the super-repo pointer. §15.1 is **done** (see §16.0); §15.3's warning that the
prototype lives only in a scratchpad is **obsolete** — it is in
`site/prototype/`. Read **§16** for the current state; the rest of §15 is kept
because §15.2 and §15.4 are still live.

### 15.1 The copy rewrite — do this first

**Status, 2026-08-14: drafted. `site/COPY.md` draft 1 carries every
visitor-facing string.** It closes all five false statements, rebuilds the empty
state on a measured example, and writes the states that had no copy at all. Two
labelling choices are marked `[DECIDE]` in it and are the only things left open.
The measurements it rests on, all taken over the full 1362096 expressions of
`semantics.lmdb` with the §5 tokenizer and the D21 subtoken rule:

| Expression condition | Subtokens | Matches |
|---|---|---|
| `?P ⟹ ?Q` (the old example) | `P ⟹ Q` | **60** |
| `?n + ?m = ?m + ?n` (the new example) | `n + m = m + n` | **0** |
| `?a + ?b = ?b + ?a` | `a + b = b + a` | **15**, one of them `Groups.ab_semigroup_add_class.add.commute` |
| `?x + ?y = ?y + ?x` | `x + y = y + x` | 41 |
| `?m * ?n = ?n * ?m` | `m * n = n * m` | **0** |
| `?a * ?b = ?b * ?a` | `a * b = b * a` | 12 |
| `⟹` (the old suggestion) | `⟹` | **617652**, 45.34 % |
| `continuous_on` | `continuous on` | 2269 |
| `sorted_wrt` | `sorted wrt` | 813 |

The new example is the strongest available because the theorem the visitor wants
**is in the index** and the condition still returns nothing, for exactly one
reason: the variable names differ. Nothing else has to be explained.

The harness is `site/prototype/`; the probe scripts that produced the table are
`zero_probe.py` and `zero_probe2.py` in the 2026-08-14 session scratchpad, and
they are cheap to rewrite from the prototype if that directory is cleaned.

The rest of this section is the specification the draft was written against.

It depends on no data, and §13b showed the current copy states things that are
false, so anything built from it now would be built wrong.

**Five statements to remove or replace.** Each is false, not merely unclear:

1. *"Theorems have no declaring theory."* False of Isabelle; true only of this
   index. Three of four readers took it as evidence the site is broken.
   Replacement: *"isasearch does not record which theory declares a theorem.
   A Theory Name condition on a theorem is matched against the theories of the
   constants that appear in its statement. There are often several of these, and
   sometimes more than twenty."*
2. *"an adjacent run of Isabelle tokens, in order."* False: `sorted_wrt` is one
   token, and the matching unit is the subtoken. The true rule already appears,
   buried, in an error message — `_`, `.` and subscript marks are separators.
   Replacement: *"The Expression filter looks for Isabelle tokens that appear
   next to each other, in the same order you typed them. Matching respects name
   boundaries, and `_` and `.` count as boundaries — so `sorted` finds
   `sorted_wrt`, but `orted`, which starts in the middle of a name, finds
   nothing."*
3. *"It does not match inside a name: `sorted` finds `sorted_wrt`"* — the example
   refutes the rule in the same sentence. Covered by the replacement above.
4. *"Conditions are matched literally against the printed text ... Case-sensitive."*
   Four transformations precede matching (`?` discarded, ASCII escapes converted,
   splitting at separators, whitespace dropped), so "literally" is false — and
   this line is always visible, so it teaches the model the empty-state page then
   has to correct. State the real rule, or drop the word.
5. *`sledgehammer` offered as a term-pattern search tool.* It dispatches goals to
   external provers. `find_consts` is the name that was wanted, and
   `find_theorems` only searches loaded theories — worth saying, since the reader
   is on a website precisely because no session is open.

**The empty-state page needs a new example.** It currently shows `?P ⟹ ?Q`
returning nothing; measured, that condition matches 60 records (§13b). Find a
condition that genuinely returns zero and rebuild the page around it. Do not
reuse `⟹` as the "try instead" suggestion either: it is in 42.35 % of documents,
so it narrows nothing. Suggest a real constant — `sorted_wrt`, `continuous_on`,
`measurable`. Wherever a symbol appears in an actionable position, put its ASCII
form beside it and say that `==>` *is* `⟹`; the escape hatch currently exists
four lines from where it is needed and never states the equivalence.

**Remove the condescension.** A reader who typed `?P ⟹ ?Q` has demonstrated they
know what a schematic variable is. The page currently explains schematic
variables and `find_theorems` to them. The audience is Isabelle users (the user
settled this on 2026-08-14: readers who do not know Isabelle are not customers),
so what they need explained is *this index*, not the prover.

**Copy that is already approved and must be preserved:**

- Similarity hover (D40): *"Cosine similarity between your query and this entity,
  computed with Qwen3-Embedding-8B. The result order also accounts for keyword
  matching, so a lower score can appear higher up."*
- The disclaimer keeps its existing two sentences and gains one clause saying the
  explanation also feeds retrieval, so a poor one costs an entity its ranking.
- No "AI" label on the collapsed explanation row — twenty per page is noise.
- Limit messages, to be revised per the notes below: query 8,000 characters,
  condition 512 characters, per-IP 5 requests per 10 seconds, per-IP 1,000 per
  UTC day, and the separator-only rejection.

**Language, from the non-native-reader assessment.** The audience is
international; the current register is native-writer compressed. Fix: dropped
relative pronouns, stacked genitives, sentence-initial reduced passives
(*"Read as three tokens"*), phrasal verbs (*"stand for"*, *"drop"*, *"sit in"*),
and low-frequency noun senses — **"run"** (read as *execute* in a software
context), **"literally"** (now an intensifier in everyday English), **"declaring"**
(everyday sense: *to announce*), **"authoritative"** (everyday sense: *sounds
expert*, not *is the source of truth*), **"resets"** (attaches to "the limit",
suggesting the number changes, not the count). Write `1000` and `8000` without
thousands separators — the comma is a decimal point across continental Europe.
Replace *"and let the natural-language query carry the shape"*, an invented
metaphor carrying the page's actual advice.

**Terminology to unify** — the copy is unstable where §1's glossary is not:
*filter* / *condition* / *row* used for two levels of structure; *expression* for
a filter field, the monospace term on a card, and "regular expressions" in the
same list; *query* versus *search* when counting the daily allowance; six kinds
named on the landing page against eleven chips; *Collection* defined nowhere.

**States that have no copy at all** and must be written:

- **Filters returning zero.** This is the modal failure of the panel and there is
  nothing for it. It must name each active condition and offer to remove it
  individually. The words "and" and "or" appear nowhere in the current copy —
  state that text conditions are AND-ed and Kind chips are OR-ed (D38).
- A server or network error; a search still running; an entity whose
  interpretation is missing (some of 1.3 M will be); what the copy button copies;
  whether filters persist between visits.
- **The absent form of the card source link** (D42): coverage is 80.2 %, so about
  one card in five has no link and must not render a dead one.

### 15.2 Small things being decided without further consultation

The user asked on 2026-08-14 that wording, styling and duplicated-copy matters be
settled directly rather than raised. Recorded so the decisions are traceable:

- **The footer states the indexed Isabelle release, the AFP snapshot and the
  index build date.** Absence of a result is this product's primary output and is
  uninterpretable without them.
- **The search response returns exactly** what a card renders: `name`, `expr`,
  the full kind set (D38), `theories`, `position`, `interpretation`, `group`. Not
  the vector — 200 of those would dominate the payload.
- **The `"\n"` separator in `theory_subtokens` is verified at implementation
  time**, not before: §3.3 never tested whether turbopuffer stores and indexes a
  whitespace-only element in a `pre_tokenized_array`. One upsert against a test
  namespace settles it; if it is dropped, choose a non-whitespace separator that
  the tokenizer cannot emit.
- **What number the RRF fusion returns per row** is likewise settled by one
  `multi_query` against a live namespace. D40 already fixes what is *displayed*
  (the vector leg's cosine similarity), so this only affects plumbing.

### 15.3 The tokenizer freeze — the one build step that is unblocked

Per D41 and §5. It touches no keys, so the key repair does not gate it.

**The working prototype is in a session scratchpad and will not survive**:
`.../scratchpad/rev/recommended.py` holds the settled separator class and the
`subtokens` implementation with its fallback clause; `isa_tok_rev.py` holds
`tokenize`. **Copy both into the repository before anything cleans that
directory** — §5.4 carries the rule in prose, but the validated code is only
there.

Then, in order:

1. `Isabelle_Semantic_Embedding/isabelle_tokenizer.py` — the Python
   implementation, lifted from the prototype, reading its character classes from
   the emitted assets rather than from Python built-ins (D41).
2. The export emits the assets: the symbol table, and the letter, digit,
   quasi-letter, separator and ASCII-symbolic code-point sets.
3. `site/tokenizer/` — the JavaScript port, reading the same assets.
4. The shared test-vector file: at least 10,000 triples sampled from real entity
   expressions **plus** synthetic cases for ASCII-escaped input, NFD input,
   unfoldable subscripts, separator-only conditions, and the `²` / U+FEFF
   boundary characters — real expressions cannot exercise pipeline steps 1 and 3
   at all (§3.4). Pin its encoding, ordering, count and digest.
5. The CI gate running both implementations against that file.

Also lift `_truncate_to_token_limit` out of `premise_selection.py` if the query
cap needs it — D29 now caps in characters, so it may not.

### 15.4 Two reviews, at named moments

The 2026-08-13 adversarial review covered the plan up to roughly D32. **D33-D42
have never been reviewed**, and several are structural: D5's reversal changed the
unit of indexing for the whole corpus, D24's rule was rewritten, and D35, D36 and
D41 are entirely new. The defect rate observed so far does not support skipping
this: that review found five blockers in a document already carefully drafted,
and the reader testing then found five false statements in copy written from it.

- **A narrow review of §5 and D41, immediately before writing the tokenizer.**
  Small scope, deep agents; ask specifically for constructions where two
  implementations both pass the test vectors and still behave differently.
- **A full review before the export is built**, once the copy has landed and the
  three prerequisites are in.

**Method fix for both.** In the 2026-08-13 run the rebuttal round deleted *none*
of 35 findings, because the defender was told that killing a true finding is
worse than keeping a weak one and simply passed everything through. Give the
defender an explicit deletion quota with justification, and state the judge's bar
before the round rather than after.

### 15.5 Files, and their state

```
SEMANTIC_SEARCH_SITE_PLAN.md      this document — UNTRACKED
site/DESIGN_PROMPT.md             the designer brief — UNTRACKED, partly synced
site/design/IsaSearch.dc.html     the delivered mockup, edited — UNTRACKED
site/design/IsaSearch.dc.html.bak the mockup as delivered, before any edit
site/design/support.js            the Claude Design runtime, generated, do not edit
```

The mockup already carries the D22 five-panel layout, the D15 amber notice with
its trigger, the D26 theory-line rule and the `All` hint. It still carries the
false copy of §15.1, a `load 8 more` control and a total match count that D29
forbids, an empty Kind chip default against D29, and pagination at 8 rather
than 20.

Unrelated and outstanding: `contrib/Isa-Mini/statistics.py` was renamed to
`translation_statistics.py` (it shadowed the standard library and exited the
interpreter on import) and is staged but uncommitted, to go in with the next
commit. The copy of it under `ICSE27/` is deliberately untouched — that tree is a
frozen paper snapshot and must never be modified.

