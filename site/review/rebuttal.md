# Rebuttal round — verdict on the 29 tokenizer findings

Bound by `tok_review_bar.md`, which was frozen before any finding existed. Every
number below I measured myself; scripts are in `scratchpad/reb/` (`m1.py`
symbol-table parse, `m2.py` composition starters, `m3.py` corpus pass for the
`\<…>` cut, `m4.py` re-run of every divergence I kept).

Input: 29 findings. After merging: **19**. Deleted: **9** (47 %, quota was ≥ 7).
Surviving: **10**, plus **1** addition of my own.

---

## 1. Merges

Nine merges collapse 29 findings into 19. Merging is not deletion; every merged
finding's strongest formulation is carried forward, and I say which one it is.

### M1 = prose F1 + pipeline F6 (the fold half)
**§5.1's five numbered steps contain no step that folds `⇩x` → `ₓ`, yet the whole
of §5.4 depends on that fold.** `unicode_of_ascii` is two substitution passes:
`\<name>` → character, then `re.sub('⇩.|⇧.|❙.')` against `SUBSUP_TRANS_TABLE`.
§5.1 step 3 describes only the first. prose F1's Reading B is the stronger of the
two: fold each `\<^sub>`/`\<^sup>`/`\<^bold>` *as the escape is expanded*, together
with the character that follows it — which is exactly what step 3's stated purpose
("so a user may type `\<Longrightarrow>` or `⟹`") describes. I re-implemented that
reading (`m4.py::tokenize_B`) and confirmed **0 failures on all 32 lines of
§16.2**, while it diverges on already-Unicode input: `'x⇩i + y⇧T'` → `['x','+','y']`
(prototype) versus `['x','i','+','y','T']`. pipeline F6's Reading B (no fold at
all) is the weaker sibling — §16.2 line 12 kills it — and is absorbed.
pipeline F6's *other* half, the false whitespace sentence, goes to M5.

### M2 = subtoken F5 + prose F4
**§5.1 step 4's sentence "A `\<foo>` with no code point stays one symbol and can
therefore never be cut in half" is false at the subtoken level, which under D21 is
the only level indexed or queried.** The token survives whole; §5.4 then splits it
on `_`. Ran: `\<^const_name>foo` → tokens `['\<^const_name>','foo']` → subtokens
`['\<^const','name>','foo']`; `\<big_ast>` → `['\<big','ast>']`. Contrast
`\<transforms>`, also unconverted but with no `_`, which survives whole — so the
corruption is silent and selective. subtoken F5's corpus number is the correct one
(conflict (a) below).

### M3 = subtoken F2 + subtoken F3 + prose F3
**`SUBSUP_TRANS_TABLE` is a hand-written 142-entry Python literal, 90 of the
separator class's 99 characters come from it, §5.4 and §16.2 both say the class is
"derived from `etc/symbols`, never hand-written", and §16.4 never asks the export
to emit it.** Verified: `etc/symbols` carries only the fields `code:`, `group:`,
`font:`, `abbrev:`, `argument:`, `~:` — no folding information of any kind, so the
90 characters are not derivable from it by any means. subtoken F3 (the table is
incomplete and a port transcribing it by hand would complete the holes) is the
motivation for why the omission bites rather than a separate finding; on its own it
fails criterion 4, since §16.5 already requires "sub/superscripts that have no fold
entry". subtoken F2's second limb (nothing emitted marks which 90 of the 99 are
"rendered", which the fallback clause needs) is folded in.

### M4 = pipeline F3 + unicode F6
**Step 1 (NFC) and step 3 (`unicode_of_ascii`) do not commute, and the pipeline's
output is not NFC even though step 1 exists to make it so.** 47 of the 439
code-point-bearing symbols are canonical-composition starters (conflict (c) below),
so step 3 can reinsert exactly the decomposed sequence step 1 removed. Ran:
`'\<alpha>' + U+0301` → `['α','́']` (two tokens, the identifier split by a combining
mark) against `'ά'` → `['ά']` and `'α' + U+0301` → `['ά']` — same logical content,
three spellings, two different arrays. And NFC can destroy an escape by eating its
closing `>`: `'\<in>' + U+0338` → `['\<in','≯']`. unicode F6's separate limb — that
§3.4 contains no NFC measurement at all, though §5.1, D41 and §16.5 all cite it for
one — is carried as a sub-item of the same fix, because the sentence to be written
is the same sentence.

### M5 = pipeline F4 + pipeline F6 (whitespace half) + prose F10 + subtoken F6 (whitespace consequence)
**§5.2's opening sentence — "Whitespace produces no output at all; token boundaries
come from the grouping, not from whitespace" — is false in both halves, and its
literal reading also makes `?` a non-boundary.** All four reviewers hit the same
sentence from different sides. Ran: `'f x'` → `['f','x']` vs `'fx'` → `['fx']` (so
whitespace *is* a hard boundary, and §5.3 line 776 declares exactly this pair
inequivalent); `'a?b'` → `['a','b']` (so `?` flushes as well as vanishing);
`'\<^bold>x'` → `['𝐱']` vs `'\<^bold> x'` → `['x']`, and `'x⇧c'` → `['x']` vs
`'x ⇧c'` → `['x','ᶜ']` (so beyond boundaries, a space changes which *character*
survives — a space suppresses the fold). §16.2's annotation "← whitespace is not a
boundary" on the `'?a + ?b' ≡ '?a+?b' ≡ 'a+b'` line repeats the error.

### M6 = pipeline F1 + prose F5
**Neither §5.1 step 4 nor §5.2 says anything about a malformed or unterminated
`\<`, and two different mechanisms diverge on the same inputs.** pipeline F1: §5.2's
symbolic-token bullet says "a maximal run of **characters** from `! # $ … \ ^ …`",
where every other bullet in the list says *symbol* — so `\<` (a two-character
symbol made entirely of class members) either joins the run or does not. prose F5:
`symbol_explode` accepts an unterminated `\<…>` as one symbol, where the obvious
JavaScript regex `/\\<\^?[A-Za-z][A-Za-z0-9_']*>/` would not. The two land on the
same inputs and the same repair. Ran: `'x \<= y'` → prototype `['x','\<','=','y']`;
under either reading B, `['x','\<=','y']`. `'A \<Longrightarrow B'` (no `>`) →
prototype `['A','\<Longrightarrow','B']`; under a `>`-requiring scanner,
`['A','\<','Longrightarrow','B']`.

### M7 = pipeline F5 + prose F6  *(merged, then deleted — see §3)*
A leading `'` (type variables) and a leading `_` cannot begin an identifier.

### M8 = unicode F3 + prose F8  *(merged, then deleted — see §3)*
The `letter`/`greek` group of `etc/symbols` contributes no letters the `isalpha()`
limb does not already contain. Re-verified: 164 symbols, **164** with a code point,
**164** whose character is `isalpha()`; the `or` in §5.2 never fires and
`_is_letter`'s multi-character branch is unreachable. prose F8's separate limb
about the letters/digits overlap is moved to U4, where it belongs.

### M9 = pipeline F7 + prose F7  *(merged, then deleted — see §3)*
A digit run not preceded by a letter becomes one subtoken per digit, and §16.5
samples only stored expressions while §5.1 applies to four kinds of input.

**Not merged, though adjacent.** subtoken F1 (fallback narrowness) and subtoken F4
(fallback breaks adjacency) both concern the fallback clause but have opposite
root causes — one says the clause is too narrow, the other that it fires at all —
so they stay separate. unicode F5 (no whitespace asset) and unicode F2 (`\p{L}`
drift) both concern §16.4's asset list but the first is an omission and the second
a versioning gap; separate.

---

## 2. Conflicts resolved by re-measuring

### (a) Records affected by the `\<…>`-with-underscore split: **502 expression records. subtoken F5 is right; prose F4's 19 is wrong.**

Method: one full LMDB pass (`scratchpad/reb/m3.py`, 10 s), running the reference
implementation rather than pattern-matching a symbol list — for every record,
`tokenize(expr)`, and for every token starting with `\<`, test
`subtokens([t]) != [t]`.

```
expr records                                        1,362,096
records carrying a literal \<…> after step 3            3,562
records with a \<…> token the subtoken splitter cuts      502
distinct literal \<…> tokens seen                         102
  of which cut                                              8
per-kind RECORD counts (second pass, m3 variant):
  \<big_ast> 323   \<half_blkcirc> 86   \<black_circle> 76
  \<heavy_comma> 16   \<^named_theorems> 13   \<half_bc2> 6
  \<^const_name> 5   \<^type_name> 1
name records with such a token                              0
```

subtoken F5's eight per-kind counts reproduce **exactly**, digit for digit.

**Why prose F4 got 19.** It enumerated the 73 code-point-less names in
`$ISABELLE_HOME/etc/symbols`, intersected with the corpus, and found three kinds
containing `_` — then *summed* their document counts (13 + 5 + 1). Two errors. The
smaller one: the union of those three kinds is **17** records, not 19, because
records carry more than one. The larger one: the restriction to `etc/symbols` is
wrong. `\<big_ast>`, `\<half_blkcirc>`, `\<black_circle>`, `\<heavy_comma>` and
`\<half_bc2>` are **not in `$ISABELLE_HOME/etc/symbols` at all** (verified with
`grep`; they live in `contrib/phi-system/symbols`, a component file the tokenizer's
loader never reads). For the tokenizer they behave identically to a code-point-less
symbol: step 3 leaves them as literal text, `symbol_explode` makes them one symbol,
§5.2 routes them through "anything else: one symbol, one token", and §5.4 cuts them
at the `_`. Ran all of them (`m4.py`) to confirm.

The reviewer who checked whether `\<big_ast>` "has a code point" would have found
it absent from the file and concluded "not applicable"; the right conclusion is
"has no code point in the strongest possible sense". That absence is itself a
finding — see §5.

### (b) Symbol names containing `_`: **35 in total, of which 34 have no `code:` field. Both reviewers measured a real number; subtoken F5's accompanying claim is false.**

```
etc/symbols entries                       512   (439 with code:, 73 without)
names whose \<…> body contains '_'         35
  … with a code point                       1   \<^theory_text>   (⬚ U+2B1A)
  … without a code point                   34
```

subtoken F5 says "35 symbol names contain `_`, **and all of them are control
symbols with no `code:` field**" — the count is right, the clause after it is
wrong by one: `\<^theory_text>` has a code point, is therefore converted at step 3,
and never reaches the splitter. prose F4's "34 of 73 no-code-point symbol names" is
exactly right. **For the purpose of M2 the operative number is 34** (plus an
unbounded number of component symbols outside the file — see (a)).

### (c) Symbol values that are canonical-composition starters: **47. unicode F6 is right; pipeline F3's 46 is wrong.**

Measured twice, by independent methods (`scratchpad/reb/m2.py`):

1. Enumerate all 0x110000 code points, take those with a two-part canonical
   decomposition that round-trips under NFC (941 composition pairs, 377 distinct
   starters), and intersect with the 439 symbol values → **47**.
2. Enumerate the 922 combining marks and test, for each symbol value `v`, whether
   any mark `m` gives `len(NFC(v+m)) == 1` → **47**.

Both give the same 47 symbol names, listed in `m2.py`'s output; they include
`\<dieresis>` (¨), the nine Greek vowels, the arrows, and the whole
`≤ ≥ ∈ ⊆ ⊂ ≡ ∼ ⊢ ⊨ ⊲ …` family. No symbol has a multi-character value and no two
symbols share a value, so "47 symbols" and "47 distinct values" coincide and the
discrepancy cannot come from that. pipeline F3's 46 is one short; its listing is
not shown in full so I cannot say which entry it dropped, but its number is not
reproducible by either method.

---

## 3. Deleted — 9 of 19 (47 %, quota ≥ 7)

**M7** (pipeline F5 + prose F6) — *a leading `'` or `_` cannot begin an identifier.*
Fails **criterion 4**, on both authors' own evidence: pipeline F5 writes "**caught**
by the 10,000 real samples (12.7 % hit rate)" and prose F6 writes "the `'a` half is
caught by any real sample". At 12.7 % of expressions, *any* sample of 10,000
however drawn contains ~1,270 instances; the `_`-then-rendered half is 2,168
documents (0.16 %), ~16 expected draws. Also weak on **criterion 2**: §5.2 says "a
maximal run **beginning with a letter**" and separately lists "*Quasi* = `_` and
`'`" among the continuation classes, so a competent implementer has the answer in
the text. Free fix worth taking anyway: add `"?'a" → ["'", 'a']` to §16.2, whose
only quote case is the trailing `"f'"`.

**M8** (unicode F3 + prose F8) — *the letter/greek group contributes no letters.*
Fails **criterion 3**: unicode F3 states it outright — "unobservable today, so no
vector can distinguish the readings" — and an unrun, unobservable divergence is
dead under the bar. The one observable variant, prose F8's "an implementer emits
164 code points instead of 136,104", fails **criterion 2**: §16.4 says "**letters**
(*including* the `letter` and `greek` group symbols)", and no competent reader
turns "including" into "only". I re-verified the underlying measurement (164 / 164
with a code point / 164 `isalpha()`) and it is correct — it just has no consequence.

**M9** (pipeline F7 + prose F7) — *numerals outside an identifier.* Fails
**criterion 4** on both authors' own evidence: prose F7 writes "at 1.1 % a
10,000-triple sample draws ~110, so the *port* gate would catch it" and pipeline F7
writes "covered by luck rather than by design". pipeline F7's other limb — §16.5
samples only expressions though §5.1 names four input kinds — fails **criterion 3**
by its own admission: "I did not find a construction that occurs in names and in no
expression, so I cannot show a miss". Free fix: add `'n < 100' → ['n','<','1','0','0']`
to §16.2 and name all four input kinds in §16.5's sampling rule.

**subtoken F1** — *the fallback clause: "all characters rendered" versus "at least
one rendered".* Fails **criterion 2**, decisively. §5.4 prints the implementation
verbatim as a normative code block, including the literal line
`elif t and all(c in _RENDERED for c in t)`. The bar asks whether someone competent
"reading only §5 + D41 + the emitted assets would have no way to prefer A" — they
have the code. Reading B requires discarding the printed code in favour of an
inference from the justifying prose. The finding's underlying observation is real
(11 corpus tokens differ) and the justification sentence in §5.4 could be tightened
to say the clause's boundary is "every character", not "not `_`" — but that is
prose polish, which the bar excludes.

**subtoken F4** — *a fallback-kept token breaks an adjacent run in 50,582 records;
§5.4 quantifies the benefit and not the cost.* Fails **criterion 2**: §5.4's code
block appends the token unconditionally, and nothing anywhere hints at a
position-dependent rule, so no competent implementer writes "emit it only at an
array end". Fails **criterion 1**: the real complaint is that §3.6 files the
adjacency break under "two properties worth knowing" rather than under a decision,
which is the bar's excluded category "the prose could be clearer without a
demonstrated divergence". The 3.71 % cost figure is genuinely useful and §5.4 would
be better for carrying it; that is an edit, not a finding.

**subtoken F6** — *60 of the 90 rendered separators are also §5.2 letters and 20
are digits; the overlap is undocumented.* Fails **criterion 4** on the author's own
evidence: "a port that de-overlaps the two assets **IS caught** — it turns
`'[x]\<^sup>c\<^sup>e'` into `['[','x',']','ᶜ','ᵉ']` against §16.2's
`['[','x',']','ᶜᵉ']`. So this is not a port divergence." Also **criterion 2**: an
implementer emitting each asset from its own definition preserves the overlap
without thinking about it; only a deliberate de-overlapping breaks it. Its one
live consequence — that inserting a space changes which character survives — is
merged into M5, where it is a statement about a false sentence rather than about
implementation divergence.

**unicode F5** — *§16.4 emits no whitespace asset.* Fails **criterion 4** on the
author's own evidence: "§16.5 **does** pin all six divergent code points, so a port
that gets them wrong fails the gate — this is the rare case where the vectors are
ahead of the asset list", and the severity line reads "cosmetic behaviourally". I
confirmed §16.5's synthetic list names all six (U+001C–U+001F, U+0085, U+FEFF) and
that the corpus contains no exotic whitespace at all. The residual claim — that
§16.3 step 2's acceptance test ("the assets load standalone") is satisfiable while
`isspace()` is still a built-in — is a structural observation with no behaviour
behind it. Free fix worth taking: add the whitespace/discard class to §16.4's asset
list so all five classes §5.2 names are covered, since the omission looks like an
oversight rather than a decision.

**prose F2** — *two `subtokens` functions in `site/prototype/`; §5 names neither.*
Fails **criterion 2**: §5.4 prints `subtokens` with the fallback clause,
§16.2 flags the fallback line in capitals, and §16.1 explicitly calls the
`tokenize_prototype.py` variants "superseded" — three signposts. Fails
**criterion 4** as well: §16.3 step 1's acceptance criterion is "reproduces every
line of §16.2", which includes `'[x]\<^sup>c\<^sup>e' → ['[','x',']','ᶜᵉ']`, and
`subtokens_rev` fails that line, so a wrong lift is caught before the vector file
is ever generated. The finding's structural point (the vector file is generated by
the Python side, so a wrong Python makes both sides wrong together) is real and is
kept — it is M3's criterion-4 argument. Free fix: §16.3 step 1 should name the file
and the function.

**pipeline F2** — *step 2 (U+007F → space) is exercised by no vector and §5.1
invites omitting it.* Fails **criterion 2**. Step 2 is a numbered imperative in a
normative pipeline: "Replace U+007F with a space". The parenthetical "(a stop-gap
until §10 lands; harmless after)" says the step *remains harmless*, i.e. leave it;
reading it as permission to delete requires preferring an aside to the instruction,
and criterion 2 requires that a competent implementer have "no way to prefer A" —
here A is written out. Free fix: §16.5's synthetic list names U+001C–U+001F, U+0085
and U+FEFF but not U+007F, which looks like an omission in a list meant to be
exhaustive about control characters; add it.

---

## 4. Survivors — 10, ordered by severity

### S1. The fold has no pipeline step. *(M1: prose F1 + pipeline F6)* — silently-wrong-results
§5.1 lists five numbered steps and none of them folds `⇩x` → `ₓ`. The fold lives
inside `unicode_of_ascii`, whose description in step 3 is "so a user may type
`\<Longrightarrow>` or `⟹`" — a description of escape conversion only. §5.4 then
leans on the fold in every one of its examples and calls its outputs "the rendered
characters the folding produces", without ever saying which step produces them. An
implementer who reads step 3 as its stated purpose folds each
`\<^sub>`/`\<^sup>`/`\<^bold>` *as it expands the escape*, together with the
character that follows — a natural and self-consistent structure. I built that
implementation and ran it: it passes **all 32 lines of §16.2** and diverges on
already-Unicode input, which is what comes out of Isabelle/jEdit's buffer:
`'x⇩i + y⇧T'` → `['x','+','y']` versus `['x','i','+','y','T']`; `'[x]⇧c⇧e'` →
`['[','x',']','ᶜᵉ']` versus `['[','x',']','c','e']`; `'❙x ❙('` → `['𝐱','(']` versus
`['x','(']`. §16.5's real-data triples provably cannot catch it: I confirmed
`unicode_of_ascii(expr) == expr` on all 1,362,096 stored expressions, so no stored
expression contains an unfolded pair, and every subscript line of §16.2 is written
in the `\<^sub>` escape spelling that both readings agree on.
**Change demanded:** rewrite §5.1 step 3 to state both passes and their order —
"expand every `\<name>` via the symbol table, then fold every remaining
`⇩x`/`⇧x`/`❙x` pair anywhere in the string, whatever its origin" — and add
`'x⇩i + y⇧T' → ['x','+','y']` to §16.5's mandatory synthetic list.

### S2. "A single character" does not say code point, and D41's assets cannot fix an iteration-granularity bug. *(unicode F1)* — silently-wrong-results
§5.2 defines *Letter* as "**a single character** for which `isalpha()` holds" and
§5.1 step 4's `symbol_explode` advances with `text[i]`. In Python that is a code
point; in JavaScript it is a UTF-16 code unit, and 124 of the 439 code-point-bearing
symbols (28 %) — the whole script, fraktur, blackboard-bold, sans-serif and
bold-digit families — map above U+FFFF, as do `\<^bold>`'s 52 fold outputs. The
naive port turns `'\<^bold>x'` into two lone surrogates; §16.2's single astral line
catches that one. A port that fixes only what that vector exercises, making the
*fold* code-point-aware while keeping `sym.length === 1` for the letter test, still
splits every astral letter adjacent to another letter: 5,219 expressions and 771
names carry a subtoken mixing an astral character with another (`𝔄𝔯𝔦𝔱𝔶` 1,440,
`𝒱s` 922, `𝔉'` 704). JSON round-trips lone surrogates without error, so the
breakage reaches turbopuffer silently. It survives criterion 4 only because §16.5
pins a count and a digest but **never a sampling method**: at 0.38 % the coverage
depends on a sample nobody has specified, and astral characters cluster in a few
AFP entries.
**Change demanded:** one sentence in §5.2 — "a *character* throughout §5 means one
Unicode code point; every implementation iterates strings by code point, never by
UTF-16 code unit" — and pin §16.5's sampling procedure so the coverage stops being
an accident.

### S3. §5.1 step 4's "can therefore never be cut in half" is false. *(M2: subtoken F5 + prose F4)* — degraded-results, and the sentence is the stated justification for the whole design
The claim holds of tokens and fails of subtokens, which under D21 are the only
level indexed or queried: 34 of the 73 code-point-less names in `etc/symbols`
contain `_`, and §5.4 splits on `_`. Ran: `\<^const_name>foo` → subtokens
`['\<^const','name>','foo']`; `\<big_ast>` → `['\<big','ast>']`; but
`\<transforms>`, equally unconverted and with no `_`, survives whole. **502 stored
expression records** carry a token this cuts (measured, §2(a)), and a user pasting
`\<^const_name>` into the condition box gets two junk subtokens matching nothing.
Both implementations agree, so this is a defect in the frozen text rather than a
port divergence — but the sentence it defeats is the one §5.1 offers as "what makes
the matching genuinely symbol-level rather than character-level".
**Change demanded:** replace §5.1 step 4's last two sentences with a truthful
statement — the symbol survives step 4 whole, but §5.4's split is character-level
and does cut it, on 502 stored records — and add `'\<^const_name>' →
['\<^const','name>']` to §16.5's synthetic list.

### S4. *(Mine — see §5.)* The symbol-table asset's provenance is unspecified, and the corpus was built with a wider table than §5.5 describes. — silently-wrong-results

### S5. The fold table is hand-written, is not in `etc/symbols`, and §16.4 does not emit it. *(M3: subtoken F2 + F3 + prose F3)* — silently-wrong-results, both sides wrong together
§5.4 and §16.2 both assert the separator class is "derived from `etc/symbols` —
never hand-written". Verified false: `etc/symbols` carries only `code:`, `group:`,
`font:`, `abbrev:`, `argument:` and `~:` — no folding information at all — and 90
of the class's 99 characters come from `SUBSUP_TRANS_TABLE`, a 142-entry literal
dict at `Isabelle_RPC_Host/unicode.py:121`. Only the 7 control characters are
`etc/symbols`-derived. §16.4's asset list emits letters, digits, quasi-letters, the
separator class and the ASCII-symbolic set — not the fold table — so the JavaScript
port has no legal source for step 3's second pass at all, while §5.5 forbids
hard-coding. Nor does anything emitted mark *which* 90 of the 99 are "rendered",
which the fallback clause needs; reconstructing them requires looking up seven
symbol names and subtracting, which is stated nowhere. §16.5 cannot catch any of
this, because the vector file is generated by the Python implementation from the
same asset: both sides are wrong together and the gate is green.
**Change demanded:** add the fold map and the 90-character rendered subset to
§16.4's asset list, and correct §5.4's and §16.2's "derived from `etc/symbols`,
never hand-written" to name the fold table's real home.

### S6. Nothing specifies behaviour on a malformed or unterminated `\<`. *(M6: pipeline F1 + prose F5)* — silently-wrong-results, query side only
§5.2's symbolic-token bullet says "a maximal run of **characters** from
`! # $ % & * + - / : < = > @ \ ^ | ~`" where every other bullet in the list says
*symbol*; `\<` is a two-character symbol all of whose characters are in that class.
Read as written, `\<` joins the run. The prototype requires `len(sym) == 1`. Ran:
`'x \<= y'` → `['x','\<','=','y']` versus `['x','\<=','y']`. Independently,
`symbol_explode` accepts an unterminated escape as one symbol — ran,
`'A \<Longrightarrow B'` → `['A','\<Longrightarrow','B']` — where the obvious
JavaScript regex `/\\<\^?[A-Za-z][A-Za-z0-9_']*>/` falls through to character-level
classification. §9.3 promises the `\<Longrightarrow>` input route, so half-typed
escapes are exactly where users land. Uncatchable by real data: I confirmed **zero**
of 1,362,343 records contain a `\<` not followed by an identifier, §16.2 has no
malformed-escape line, and §16.5's synthetic list asks for "ASCII-escaped input",
not malformed ASCII-escaped input.
**Change demanded:** one sentence in §5.1 step 4 giving `symbol_explode`'s behaviour
on a `\<` with no identifier and on an unterminated escape, plus a word in §5.2's
symbolic bullet saying *symbol* rather than *character*; add `'\<='` and
`'A \<Longrightarrow B'` to §16.5.

### S7. Steps 1 and 3 do not commute, and the pipeline's output is not NFC. *(M4: pipeline F3 + unicode F6)* — silently-wrong-results on rare input
§5.1 applies NFC at step 1 and inserts new characters at step 3, so nothing step 3
produces is ever normalised. 47 of the 439 symbol values are canonical-composition
starters (§2(c)), so a combining mark that step 1 could not compose — because the
escape's `>` still stood between them — is still there when step 3 removes the `>`.
Ran: `'\<alpha>' + U+0301` → `['α','́']`, two tokens, the identifier split by exactly
the combining mark step 1 exists to eliminate, against `'ά'` → `['ά']`. In the other
direction NFC can destroy an escape outright: `'\<in>' + U+0338` → `['\<in','≯']`,
because `>` + U+0338 composes to U+226F. What saves the pipeline today is an
unstated, unmeasured invariant — no `etc/symbols` value is a combining mark (0 of
439) — that nothing in the plan requires to stay true. Separately, §5.1, D41 and
§16.5 all cite **§3.4** for "the store is 100 % NFC" and §3.4 contains no NFC
measurement; the claim is true (I confirm 0 of 1,362,096) but is not where the
document says it is. §16.5 requires "NFD input", which exercises step 1 on ordinary
accented Latin and agrees under both readings; it never requires an escape followed
by a combining mark.
**Change demanded:** a sentence in §5.1 stating that no re-normalisation happens
after step 3 and that the output is therefore NFC only because no symbol value is a
combining mark (making that an invariant the export checks); move or add the NFC
measurement to §3.4 so the citation is honest; add `'\<alpha>' + U+0301` to §16.5.

### S8. The letter and digit assets overlap in 81 code points with no precedence. *(unicode F4, absorbing prose F8's second limb)* — degraded-results, zero blast radius today
§5.2 defines *Letter* as `isalpha()` and *Digit* as `isdigit() or isnumeric()`, and
D41 emits them as two separate sets. Re-verified: **81 code points are in both** —
the CJK ideographic numerals `一 二 三 四 五 六 七 八 九 十 …`, category `Lo` and
numeric. §5.2's identifier rule is "a maximal run **beginning with a letter**", so
whether `十` can start an identifier depends on which test is applied first, and
nothing in §5.2, D41 or §16.4 says the sets are disjoint or gives a precedence.
Building one `classOf(codepoint)` lookup by loading five overlapping sets is the
natural way to consume D41's assets in JavaScript, and load order decides it. Ran:
`'一二三'` → `['一二三']` (prototype tests letter first) versus `['一','二','三']`.
§16.2 has no CJK line and §16.5's synthetic list names only `²` and U+FEFF; the 142
corpus expressions containing a CJK numeral (AFP `Chinese`, 0.01 %) all have it
isolated, so the two readings agree on every real record and no sample can pin it.
**Change demanded:** one sentence in §5.2 or §16.4 — "the classes are not disjoint;
the letter test is applied before the digit test" — and `'一二三' → ['一二三']` in
§16.5.

### S9. The class assets are not versioned with the index, and D41's divergence list omits the largest class. *(unicode F2)* — silently-wrong-results on asset–index skew
D41 lists the measured Python/JavaScript divergences for `\p{Nd}` (via `²`) and for
`\s` (U+001C–U+001F, U+0085, U+FEFF), and does not list one for `\p{L}` — the
largest class of the five. Measured: Python 3.12's `isalpha()` is 136,104 code
points and node v20's `\p{L}` is 145,672, **9,568 apart**, all of it Unicode-version
drift (15.0 versus 17.0) rather than definitional difference. The same drift exists
across Python releases (3.12 = Unicode 15.0, 3.13 = 15.1, 3.14 = 16.0). Pinning the
set into an asset makes the two implementations agree *with each other*; it does not
make a re-export agree with the index already in turbopuffer, and §5.5 versions only
the **test vector file** with the data, singling it out in a way that implies the
other artefacts are not. No vector can catch this: the vectors are generated from
whatever asset the export machine produced.
**Change demanded:** add `\p{L}` and its 9,568-code-point measurement to D41's list,
and add to §16.4 that every class asset records the Unicode version it was derived
from and is versioned with the index, exactly as §5.5 requires of the vector file.

### S10. §5.2's opening sentence is false in both halves. *(M5: pipeline F4 + F6 + prose F10 + subtoken F6)* — cosmetic behaviourally, but it is the sentence that opens the normative section
"Whitespace produces **no output at all**; token boundaries come from the grouping,
not from whitespace." Whitespace *is* a hard boundary — that is precisely what makes
`f x` ≢ `fx`, which §5.3 declares two lines later — and beyond boundaries it changes
*content*, because a space suppresses the fold: ran `'\<^bold>x'` → `['𝐱']` against
`'\<^bold> x'` → `['x']`, and `'x⇧c'` → `['x']` against `'x ⇧c'` → `['x','ᶜ']`. Read
literally the sentence also makes `?` a non-boundary, since `?` sits in the same
discard bullet; `'a?b'` → `['a','b']` in the prototype, `['ab']` under the literal
reading, and that behaviour is written down only in §16.2, which §16.0 describes as
build guidance while §5 is what gets frozen as normative. §16.2's own annotation
"← whitespace is not a boundary" repeats the error.
**Change demanded:** rewrite the sentence — "a discarded symbol (whitespace or `?`)
terminates the token in progress and contributes nothing to the output; it is a
boundary that produces no token. Two tokens separated by whitespace never merge,
which is what keeps `f x` and `fx` distinct, while `x + y` and `x+y` agree because
the grouping separates them anyway" — and delete §16.2's annotation.

### S11. §5.4's percentages have an unstated denominator and D41 restates one count as a full-corpus figure. *(prose F9)* — cosmetic, but D41 contains a false sentence
Every percentage in §5.4 divides by ≈ 230,944, the `isa-scale-test` namespace of
§3.3, which §3.3 itself calls 18.6 % of the real corpus — while §16.2 states the
corpus scale as 1,362,096 one section away and §5.4 names no denominator anywhere.
Worse, D41 line 189 and §16.4 line 2204 lift one raw count out and label it
"`²` (U+00B2, **640 occurrences in the corpus**)". I re-measured over all 1,362,096
expressions (`scratchpad/reb/`, 100 s) and reproduce prose F9 exactly: `²` occurs
**3,955** times as a standalone subtoken across 2,369 documents, not 640; `₁`
**7,023**, not 1,281; documents with a fallback-kept token **51,891 (3.81 %)**, not
7,346 (3.18 %), across **154** distinct tokens, not 108; `Fₒ` in **116** documents,
not 50. This changes no line of code, but D41 is in scope and the sentence is false.
**Change demanded:** correct D41's and §16.4's `²` count to 3,955, and add one
clause to §5.4 naming its denominator ("measured on the 230,944-document
`isa-scale-test` namespace of §3.3") or re-measure it against 1,362,096.

---

## 5. My own addition

### S4. The symbol-table asset's provenance is unspecified, and the corpus was indexed with a wider symbol table than the asset will carry. — silently-wrong-results

I found this while resolving conflict (a), and I hold it to the same four criteria.

§5.5's first bullet says "`etc/symbols` is compiled into **one JSON asset** at export
time, read by both. Neither implementation may hard-code a symbol table." It never
says *which* `etc/symbols`. Isabelle's real symbol table is a union: the
distribution's `$ISABELLE_HOME/etc/symbols`, `$ISABELLE_HOME_USER/etc/symbols`, and
one `symbols` file per installed **component**. `get_SYMBOLS_AND_REVERSED` reads
only the first two (verified in `Isabelle_RPC_Host/unicode.py`), and there is no
user overlay on this machine (`~/.isabelle/Isabelle2025-2/etc/symbols` does not
exist), so the tokenizer sees exactly the distribution's 512 entries.

The corpus does not. Measured over all 1,362,096 stored expressions:

```
records carrying a literal \<…> after step 3                        3,562
  … carrying one UNKNOWN to $ISABELLE_HOME/etc/symbols              3,486   (86 distinct kinds)
  … carrying one that IS in etc/symbols with no code point             77
commonest unknown kinds: \<Empt> 1783, \<transforms> 1599, \<subj> 1551,
  \<OTast> 1055, \<with> 977, \<condition> 802, \<big_ast> 767, \<congruent> 740
contrib/phi-system/symbols                            50 names, all 50 absent from the distribution
```

So **98 % of the corpus's unconverted escapes are symbols the asset will not
contain**, not code-point-less symbols of the distribution — which is also why
conflict (a)'s two reviewers disagreed by 26×, and why §3.4's "1,140 records still
contain a literal `\<…>` **for a symbol with no code point**" is misdescribed: the
operative class is "not in the table", not "in the table without a `code:`".

Against the bar. **(1) Ambiguity, not diligence:** "`etc/symbols` is compiled into
one JSON asset" admits at least two readings — the distribution's file, or the
symbol table Isabelle actually presents for the sessions the corpus was built from.
**(2) Both defensible:** the second is the more natural reading of "the symbol
table", and it is what an implementer who runs `isabelle getenv` to locate the file
would not even notice they had chosen. **(3) Demonstrated:** ran the tokenizer on
`\<big_ast>` under the current asset — one token, subtokens `['\<big','ast>']`; under
an asset including `contrib/phi-system/symbols` it becomes a single converted
character and no split occurs at all. 3,486 records change behaviour between the two
assets. **(4) Vectors:** the vector file is generated by the Python implementation
from whatever asset the export produced, so both implementations agree and the gate
is green under either choice — and the 10,000 real triples record the same choice.

**Change demanded:** §5.5's first bullet must name the exact set of files the asset
is compiled from and say that the export fails if it differs from the table the
indexed corpus was produced under; §16.4 must repeat it; and §3.4's sentence should
be corrected to distinguish "no `code:` field" from "not in the table at all", with
the 3,486 / 77 split recorded.
