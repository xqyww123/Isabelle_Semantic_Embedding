# Review — lens: §5.1 pipeline + §5.2 token formation

Everything below was run. Scratch harnesses in `scratchpad/tokrev/`:
`h.py` (prototype loader), `order.py` (pipeline-order permutations),
`scan.py` (full-corpus character scan, 1,362,343 records, 44 s),
`diff.py` (differential tokenizer variants over 200,000 records, 61 s).

## Measurements I rely on

    records                                    1,362,343  (expr 1,362,096)
    expr not in NFC                                    0
    expr where unicode_of_ascii(e) != e                0
    expr containing U+007F                             0   (§10 repair landed)
    expr containing a bare `\<` not followed by ident  0
    expr containing a foldable `⇩x` / `⇧x` / `❙x` pair 0
    expr with a token-initial `'` (type var `?'a`)   178,545  (13.1 %)
    expr with a standalone multi-digit numeral         13,048  (0.96 %)
    name with a standalone multi-digit numeral        126,442  (9.3 %)
    etc/symbols: 512 names, 439 with a code point, 164 in letter/greek
    symbols whose code point is < U+00A0                   0
    letter/greek group symbols with NO code point          0
    symbol values that are not NFC-stable                  0
    symbol values that compose with a following mark      46

---

F1. `\<` and `\<^` are multi-character symbols made only of ASCII-symbolic
    characters; §5.2's "maximal run of characters" does not say whether they
    join a symbolic run, and real data can never expose the choice.
    WHERE:      §5.2 bullet 3, "**symbolic token**: a maximal run of characters
                from `! # $ % & * + - / : < = > @ \ ^ | ~` (D8)"; prototype
                `tokenize_prototype.py:59`, `if len(sym) == 1 and sym in ASCII_SYM`.
    READING A:  (prototype) only a **one-character** symbol can be in a symbolic
                run; a multi-character symbol falls to "anything else: one
                symbol, one token".
    READING B:  a symbol joins the run when every character of it is in the
                class — `all(c in ASCII_SYM for c in sym)`. §5.2 says
                "characters", and `\` `<` `^` `>` are all members, so this is
                the sentence read literally.
    DIVERGES:   `symbol_explode` (position.py:40-54) emits `\<` as one 2-char
                symbol whenever `\<` is followed by anything that is not an
                ASCII letter or `^`+letter.
                  ran `tokenize('A \\<-> B')`:
                    A → ['A', '\\<', '->', 'B']   B → ['A', '\\<->', 'B']
                  ran `tokenize('x \\<= y')`:
                    A → ['x', '\\<', '=', 'y']    B → ['x', '\\<=', 'y']
                Subtokens follow the tokens (no separator in either), so the
                indexed arrays differ element for element.
                Plausibility: §9.3 promises the user may type
                `\<Longrightarrow>`; a user reaching for that route who types
                the ASCII arrow abbreviation with a stray backslash (`\<->`,
                `\<=`, `\<=>`) lands here directly.
    VECTORS:    §16.5's 10,000 triples are "sampled from real entity
                expressions". I scanned all 1,362,343 records: **zero** contain a
                `\<` not followed by an identifier, so no real sample can carry
                it. §16.2 has no malformed-escape line, and §16.5's required
                synthetic list (§16.2 lines, ASCII-escaped input, NFD input,
                unfoldable subscripts, separator-only conditions, `²`, U+FEFF,
                U+001C–U+001F, U+0085, an all-superscript token) has no
                truncated or malformed escape. Confirmed: the differential run
                of variant B against the prototype differs on **0 of 200,000**
                real records.
    SEVERITY:   silently-wrong-results (query side only — the store cannot
                contain the construction, so it is the query that mis-tokenizes
                and returns nothing)

F2. Pipeline step 2 (U+007F → space) is exercised by no vector at all, and
    §5.1's own wording invites one implementation to drop it.
    WHERE:      §5.1 step 2, "Replace U+007F with a space (a stop-gap until §10
                lands; harmless after)."
    READING A:  keep the replacement.
    READING B:  omit the step. §10/D12's repair **has landed** — I scanned the
                whole corpus and found 0 of 1,362,343 records containing U+007F
                — so "harmless after" reads as permission to delete it.
                (A third reading, "delete the character rather than replace it
                with a space", is excluded by the prose but is the more natural
                thing to write.)
    DIVERGES:   ran all three on `'f\x7fx'` and `'x\x7f1'`:
                  A  (replace with space) → ['f','x']       ['x','1']
                  B  (omit step 2)        → ['f','\x7f','x'] ['x','\x7f','1']
                  C  (delete)             → ['fx']           ['x1']
                U+007F is not `isspace()` and is not in the separator class, so
                under B it becomes its own token **and its own subtoken**,
                which under `ContainsTokenSequence` (adjacent, ordered) breaks
                every run through it.
    VECTORS:    U+007F appears in no line of §16.2, in no item of §16.5's
                required synthetic list, and in 0 real records. The gate as
                specified cannot distinguish A, B and C.
    SEVERITY:   silently-wrong-results (query side; a paste out of a terminal,
                a PDF, or a PIDE dump carries U+007F)

F3. Step 1 (NFC) does **not** commute with step 3 (`unicode_of_ascii`), and the
    reason is the opposite of the obvious one: NFC can rewrite the ASCII
    characters of an escape. §16.5 cannot pin the order because it asks for
    "ASCII-escaped input" and "NFD input" as two separate categories and never
    for one input that is both.
    WHERE:      §5.1, the ordering of steps 1 and 3. The prose gives a reason
                for NFC ("queries pasted from macOS may be NFD") and a reason
                for `unicode_of_ascii`, but never says the order between them
                matters or which way round it must be.
    READING A:  (spec, prototype) NFC first, then escape conversion.
    READING B:  escape conversion first, then NFC — defensible as "normalise
                once the text is in its final Unicode spelling", and it is the
                order that actually guarantees the output is NFC.
    DIVERGES:   `>` + U+0338 canonically composes to `≯` U+226F (verified:
                `unicodedata.normalize('NFC','>'+'̸')` is U+226F; likewise
                `<`→U+226E, `=`→U+2260). So NFC can eat an escape's closing `>`.
                  ran on `'\\<in>' + '̸'` (bytes 5c 3c 69 6e 3e 0338):
                    A → ['\\<in', '≯']      (the escape is destroyed)
                    B → ['∉']               (i.e. `∉`, one token)
                  ran on `'\\<alpha>' + '́'`:
                    A → ['α', '́']     B → ['ά']
                Corollary worth stating in §5.1 regardless of which order is
                chosen: **A's output is not NFC**. 46 of the 439 symbol values
                compose with a following combining mark, so step 3 can
                reintroduce exactly the decomposed sequence that step 1 exists
                to remove — a combining mark is not a letter, so it splits the
                identifier, which is the failure §5.1 cites as the reason for
                step 1.
    VECTORS:    step 1 and step 3 are both the identity on every real record
                (measured: 0 non-NFC, 0 with `unicode_of_ascii(e) != e`), so no
                sampled triple can order them. §16.5's synthetic list has
                "ASCII-escaped input" and "NFD input" as separate bullets; an
                escape immediately followed by a combining mark satisfies
                neither bullet's obvious instantiation.
    SEVERITY:   silently-wrong-results (rare input)

F4. §5.2's normative text never says that `?` is a token boundary as well as
    being discarded; the only place it is written down is one line of §16.2.
    WHERE:      §5.2, "**discard**: any symbol for which `isspace()` holds, and
                the symbol `?` (D4)", read against the paragraph directly above
                it: "Whitespace produces **no output at all**; token boundaries
                come from the grouping, not from whitespace."
    READING A:  (prototype) a discarded symbol flushes the run in progress.
    READING B:  discarded symbols are removed from the stream and the grouping
                runs on what is left — which is literally what "produces no
                output at all … boundaries come from the grouping, not from
                whitespace" says, and is also the simplest way to implement
                D4's "the query loses `?`".
    DIVERGES:   ran the differential variant "`?` deleted, not a boundary" over
                200,000 real records: it changes the **subtoken array** on 279
                of them (0.14 % of expressions). Smallest case, run directly:
                  `tokenize('a?b')` → A ['a','b']   B ['ab']
                Real instance from the corpus (record shown by diff.py):
                  `'∀c. ⌊𝐎ᵢ?φ⌋⇩c ⟶ ob (pv (World c)) …'`
                  A tokens … '𝐎ᵢ', 'φ' …   B tokens … '𝐎ᵢφ' …
    VECTORS:    **caught** — §16.2 carries `'a?b' → ['a','b']  ← `?` divides as
                well as vanishing`, which §16.5 requires verbatim, and at
                0.14 % of expressions roughly 14 of the 10,000 real samples
                would also carry it. Reporting it anyway because §5 is the part
                that gets frozen as normative and §16.2 is described as build
                guidance; the sentence belongs in §5.2.
    SEVERITY:   degraded-results if §16.2's line is ever dropped; today,
                cosmetic (prose defect)

F5. §5.2 does not say what a token beginning with `'` does, and Isabelle type
    variables put that construction in 13.1 % of stored expressions.
    WHERE:      §5.2, "**identifier token**: a maximal run beginning with a
                *letter* … *Quasi* = `_` and `'`" plus "**anything else**: one
                symbol, one token".
    READING A:  (prototype) `'` is not a letter, so it cannot start an
                identifier; it falls to "anything else" and becomes its own
                token, and — since `'` is not in the separator class — its own
                subtoken. `tokenize("?'a::zero mat ⇒ bool")` →
                `["'", 'a', '::', 'zero', 'mat', '⇒', 'bool']` (ran).
    READING B:  a quasi-letter may start an identifier, so `'a` is one token —
                the reading an implementer reaches for the moment they notice
                that `'a` is how Isabelle spells a type variable, and it is what
                Isabelle's own lexer does for type variables.
    DIVERGES:   ran the differential variant over 200,000 records: the subtoken
                array changes on **25,448 expressions (12.7 %)** and 27 names.
                Example (real record): `?'a::zero mat ⇒ bool`
                  A subtokens ["'", 'a', '::', 'zero', 'mat', '⇒', 'bool']
                  B subtokens ["'a", '::', 'zero', 'mat', '⇒', 'bool']
    VECTORS:    **caught** by the 10,000 real samples (12.7 % hit rate), but
                **not** by §16.2, which has `"f'" → ["f'"]` — a *trailing* `'`
                — and no leading-`'` line at all. Since §16.2 is called "the
                acceptance criteria for the port", a port could be declared
                accepted against §16.2 alone and be wrong on an eighth of the
                corpus. Worth one more line in §16.2: `"?'a" → ["'", 'a']`.
    SEVERITY:   degraded-results (silently-wrong if §16.2 is used as the gate)

F6. §5.1 step 3 describes `unicode_of_ascii` as escape conversion only; it is
    in fact two passes, and the second one consumes the character after a
    `⇩`/`⇧`/`❙`. §5.2's whitespace sentence is false as a consequence.
    WHERE:      §5.1 step 3, "`unicode_of_ascii(s)` — so a user may type
                `\<Longrightarrow>` or `⟹`. Identity on stored text (§3.4)."
                The implementation (`unicode.py:185-203`) is
                `re.sub('⇩.|⇧.|❙.', fold, re.sub(r'\\<[^>]+>', table, src))`.
    READING A:  (prototype) table substitution **then** the sub/superscript
                fold.
    READING B:  table substitution only. Nothing in §5.1 or §5.2 mentions a
                fold; `\<^sub>` is in the symbol table in its own right
                (→ `⇩` U+21E9), so a table-only port produces well-formed output
                and looks correct.
    DIVERGES:   ran `tokenize(r'x\<^sub>1')`:
                  A tokens ['x₁']            subtokens ['x']
                  B tokens ['x','⇩','1']     subtokens ['x','1']
    VECTORS:    **caught** — §16.2's `'x\<^sub>i + y\<^sup>T' → ['x','+','y']`
                becomes `['x','i','+','y','T']` under B. Reported because the
                normative section is silent about a pass that decides whether a
                subscript's content survives, and because of its visible
                consequence:
                §5.2 opens "Whitespace produces **no output at all**; token
                boundaries come from the grouping, not from whitespace." Both
                halves are wrong. Whitespace *is* a hard boundary (that is
                exactly what makes `f x` ≢ `fx`), and beyond boundaries it
                changes content, because a space suppresses the fold. Ran:
                  `x\<^sub>1`  → subtokens ['x']     (the `1` is folded to `₁`,
                                                      then deleted as a separator)
                  `x\<^sub> 1` → subtokens ['x','1']
                  `\<^bold>x`  → subtokens ['𝐱']
                  `\<^bold> x` → subtokens ['x']
                These are the whitespace-only pairs the brief asked me to hunt
                for that are *not* of the `f x` / `fx` kind: the difference is
                not a merge, it is a different character surviving.
    SEVERITY:   cosmetic today (vector-caught) / prose defect that misleads

F7. §16.5 samples only entity expressions, but §5.1 applies the tokenizer to
    four kinds of input, and names carry shapes expressions do not.
    WHERE:      §5.1's opening — "Applied identically to stored entity
                expressions, stored names, stored theory long names, and every
                user-supplied filter string" — against §16.5, "at least 10 000
                triples … sampled from real entity expressions".
    READING A / B:  not a two-reading ambiguity; a coverage hole.
    DIVERGES:   the multi-digit numeral rule is the sharpest instance. §5.2
                gives no rule for a digit run that does not follow a letter, so
                it falls to "anything else: one symbol, one token": ran
                `tokenize('simps(15)')` → [… 'simps','(','1','5',')']. An
                implementer who adds the obvious numeral rule gets
                [… 'simps','(','15',')']. Differential run over 200,000
                records: this changes the subtoken array on **14,531 names
                (7.3 %)** but only 2,259 expressions (1.1 %). Names also carry
                constructions such as
                `NodePointer.castₙₒ⇩dₑ⇩_ₚₜᵣ₂ₒ⇩bⱼₑ⇩cₜ⇩_ₚₜᵣ_inject` (a control
                separator immediately followed by `_`) and trailing `''`
                (`MFMC_Network.antiparallel_edges.Δ''`).
    VECTORS:    the expression-only sample still catches the numeral rule at
                1.1 %, so this particular instance is covered by luck rather
                than by design. I did not find a construction that occurs in
                names and in no expression, so I cannot show a miss — but the
                sampling rule should name all four input kinds, since nothing
                else in the plan guarantees the coverage.
    SEVERITY:   degraded-results (latent)

## Areas checked and cleared

- **Can NFC produce U+007F?** No. U+007F has an empty decomposition, combining
  class 0, and no character in the whole of Unicode has a decomposition
  mentioning 007F (scanned all 0x110000 code points). NFC is the identity on it.
- **Can a `\<…>` escape expand to U+007F after step 3, i.e. after step 2 has
  already run?** No. Zero symbols in `etc/symbols` have a code point below
  U+00A0 (checked all 439 with code points), and `SUBSUP_TRANS_TABLE`'s values
  are all above U+00B2. So steps 2 and 3 genuinely commute *for this symbol
  table*. Caveat worth one sentence in §5.1: `get_SYMBOLS_AND_REVERSED` layers
  `$ISABELLE_HOME_USER/etc/symbols` on top of the system file, so this is a
  property of the shipped distribution and not of the algorithm.
- **Steps 1 and 2 commute** — NFC neither creates nor destroys U+007F.
- **Step 4 before step 3** (explode, then look each symbol up in the table)
  is a natural-looking reordering and it breaks badly — ran: `x\<^sub>i +
  y\<^sup>T` → ['x','⇩','i','+','y','⇧','T'] instead of ['xᵢ','+','yᵀ'] —
  but §16.2's line for that exact input catches it.
- **NFC must precede `symbol_explode`, and must be applied to the whole string
  rather than per symbol.** Ran the per-symbol variant: `size Č = 0` in NFD →
  ['size','C','̌','=','0'] instead of ['size','Č','=','0'], and a NFD `≠` (which
  decomposes to `=` + U+0338) → ['=','̸'] instead of ['≠']. §5.3's last line and
  §16.5's NFD requirement both pin this; cleared.
- **Multi-character letter symbols.** `_is_letter` has a branch for symbols
  longer than one character (`sym in _LETTER_SYMS`, keyed on `\<name>`
  spellings) which D41's code-point-set assets could not represent. It is dead
  code for this distribution: every one of the 164 `letter`/`greek` group
  symbols has a code point, so none can survive `unicode_of_ascii` as a
  multi-character symbol. Only a user `etc/symbols` overlay adding a
  code-point-less letter symbol would wake it.
- **Astral-plane letters and the identifier run.** `\<^bold>x\<^bold>y` folds to
  `𝐱𝐲` (U+1D431 U+1D432) and the prototype makes it **one** identifier token
  (ran, checked the code points). A JavaScript port that indexes by UTF-16 code
  unit would produce four lone-surrogate tokens — but §16.2's
  `'\<^bold>x \<^bold>(' → ['𝐱','(']` already fails for it, so the gate catches it.
- **Degenerate input — nothing crashes and nothing is silently swallowed.** Ran
  all of: `''` → []; `' '`, `'   '`, `'\t\n\r'` → []; `'\x7f'` → []; `'\\'` →
  ['\\']; `'\\\\'` → ['\\\\']; `'\<'` → ['\\<']; `'\<^'` → ['\\<^']; `'\<^>'` →
  ['\\<^>']; `'\<>'` → ['\\<>']; `'\<Longrightarrow'` (unterminated) →
  ['\\<Longrightarrow'], which survives whole as one subtoken and matches
  nothing; `'a\\'` → ['a','\\']. `symbol_explode`'s closing `>` is optional and
  its `\<` with no identifier yields a 2-character symbol — neither fact is in
  §5.1, which only says "a `\<foo>` with no code point stays one symbol".
- **One genuine degenerate-input hazard, not an implementation divergence.**
  U+FEFF is neither `isspace()` nor a separator, so it becomes its own token and
  its own subtoken: ran `tokenize('x﻿y')` → ['x','﻿','y']. Because
  §6.3 matches with `ContainsTokenSequence` (adjacent and ordered), a byte-order
  mark pasted anywhere inside a condition makes that condition match nothing at
  all. §16.5 requires a U+FEFF vector, so both implementations will agree — they
  will agree on returning zero results. Worth a decision in §5.1 (strip it, or
  add it to the discard class), not just a vector.
- **`''` (two apostrophes alone)** → ["'", "'"], two tokens, because the quasi
  letter cannot start a run and the flush resets the mode. Consistent with §5.2
  read literally; noted because `Δ''` occurs in real names.
