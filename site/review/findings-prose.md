# Tokenizer review — reviewer "does the frozen text describe the code?"

Reference implementation used for every run below:
`contrib/Semantic_Embedding/site/prototype/tokenize_prototype.py::tokenize`
composed with `contrib/Semantic_Embedding/site/prototype/subtoken_rule.py::subtokens`
(the pairing `corpus_probe.py` itself uses, lines 29–30).

Runner scripts (in this scratchpad): `run162.py`, `run53.py`, `corpus_stats.py`, `checks2.py`.

## Section 1 — every line of §16.2 (plan lines 2117–2143), run

All 32 lines reproduce. `tokens` column added because it is not in §16.2 and is
load-bearing for two findings below.

| # | input | §16.2 expects | got | tokens actually produced | verdict |
|---|---|---|---|---|---|
| 1 | `'sorted_wrt R ?xs'` | `['sorted','wrt','R','xs']` | same | `['sorted_wrt','R','xs']` | reproduces |
| 2 | `'Kelly_1_39 ?C ?T ?a'` | `['Kelly','1','39','C','T','a']` | same | `['Kelly_1_39','C','T','a']` | reproduces |
| 3 | `'Stirling_Formula.c = ln (2*pi)/2'` | `['Stirling','Formula','c','=','ln','(','2','*','pi',')','/','2']` | same | `['Stirling_Formula','.','c','=','ln','(','2','*','pi',')','/','2']` | reproduces |
| 4 | `'f x + y'` | `['f','x','+','y']` | same | `['f','x','+','y']` | reproduces |
| 5 | `'x y'` | `['x','y']` | same | `['x','y']` | reproduces |
| 6 | `'_wrt'` | `['wrt']` | same | **`['_','wrt']` — TWO tokens** | reproduces (but see F3) |
| 7 | `'F'` | `['F']` | same | `['F']` | reproduces |
| 8 | `'\<Longrightarrow>'` | `['⟹']` | same | `['⟹']` | reproduces |
| 9 | `'::'` | `['::']` | same | `['::']` | reproduces |
| 10 | `'-->'` | `['-->']` | same | `['-->']` | reproduces |
| 11 | `'==>'` | `['==>']` | same | `['==>']` | reproduces |
| 12 | `'x\<^sub>i + y\<^sup>T'` | `['x','+','y']` | same | `['xᵢ','+','yᵀ']` (folded in step 3) | reproduces |
| 13 | `'f\<^bsub>i\<^esub> = g'` | `['f','i','=','g']` | same | `['f','⇘','i','⇙','=','g']` | reproduces |
| 14 | `'\<^bold>x \<^bold>('` | `['𝐱','(']` | same | `['𝐱','❙','(']` | reproduces |
| 15 | `'[x]\<^sup>c\<^sup>e'` | `['[','x',']','ᶜᵉ']` | same | `['[','x',']','ᶜᵉ']` | reproduces |
| 16 | `'f\<^sub>1'` | `['f']` | same | `['f₁']` | reproduces |
| 17 | `'a?b'` | `['a','b']` | same | `['a','b']` | reproduces |
| 18 | `'?a + ?b'` | `['a','+','b']` | same | `['a','+','b']` | reproduces |
| 19 | `'?a+?b'` | `['a','+','b']` | same | `['a','+','b']` | reproduces |
| 20 | `'a+b'` | `['a','+','b']` | same | `['a','+','b']` | reproduces |
| 21 | `'HOL-Analysis.Path_Connected.path_image_join'` | `['HOL','-','Analysis','Path','Connected','path','image','join']` | same | `['HOL','-','Analysis','.','Path_Connected','.','path_image_join']` | reproduces |
| 22 | `'Path_Connected.path_image_join'` | `['Path','Connected','path','image','join']` | same | `['Path_Connected','.','path_image_join']` | reproduces |
| 23 | `"f'"` | `["f'"]` | same | `["f'"]` | reproduces |
| 24 | `'x-y'` | `['x','-','y']` | same | `['x','-','y']` | reproduces |
| 25 | `'%x. x'` | `['%','x','x']` | same | `['%','x','.','x']` | reproduces |
| 26 | `'_'` | `[]` | same | `['_']` | reproduces |
| 27 | `'.'` | `[]` | same | `['.']` | reproduces |
| 28 | `'?'` | `[]` | same | `[]` | reproduces |
| 29 | `'   '` | `[]` | same | `[]` | reproduces |
| 30 | `'???'` | `[]` | same | `[]` | reproduces |
| 31 | `'_.'` | `[]` | same | `['_','.']` | reproduces |
| 32 | `'\<^sub>'` | `[]` | same | `['⇩']` | reproduces |

**Result: 0 failures out of 32.** (`run162.py`.)

Caveat that matters for line 15: the table reproduces only against
`subtoken_rule.subtokens`. Against `tokenize_prototype.subtokens_rev` —
the other live-looking function in the same directory, same separator class —
line 15 returns `['[','x',']']`, losing `ᶜᵉ`. See F1.

## Section 2 — every line of §5.3 (plan lines 776–784), run

Checked at BOTH levels, because §5.3 does not say which level `≡` is about.
All nine equivalences and both inequivalences hold, at both levels.

| # | pair | claim | tokens equal? | subtokens equal? | verdict |
|---|---|---|---|---|---|
| 1 | `'x + y'` / `'x+y'` | ≡ | yes | yes | holds |
| 2 | `'(- x)'` / `'(-x)'` | ≡ | yes | yes | holds |
| 3 | `'A ⟹ B ⟹ C'` / `'A⟹B⟹C'` | ≡ | yes | yes | holds |
| 4 | `'⟦?P; ?Q⟧'` / `'⟦?P;?Q⟧'` | ≡ | yes | yes | holds |
| 5 | `'λx. P x'` / `'λx.P x'` | ≡ | yes (`['λx','.','P','x']`) | yes (`['λx','P','x']`) | holds |
| 6 | `'x :: nat'` / `'x::nat'` | ≡ | yes | yes | holds |
| 7 | `'x⇩1 + y'` / `'x⇩1+y'` | ≡ | yes (`['x₁','+','y']`) | yes (`['x','+','y']`) | holds |
| 8 | `'sorted_wrt R ?xs'` / `'sorted_wrt R xs'` | ≡ | yes | yes | holds |
| 9 | `'size Č = 0'` / its NFD spelling | ≡ | yes | yes | holds |
| 10 | `'f x'` / `'fx'` | ≢ | differ ✓ | differ ✓ | holds |
| 11 | `'map f xs'` / `'mapfxs'` | ≢ | differ ✓ | differ ✓ | holds |

Line 9 detail — NFD form constructed with `unicodedata.normalize('NFD', 'size Č = 0')`:
NFC is `73 69 7a 65 20 10c 20 3d 20 30` (`Č` = U+010C);
NFD is `73 69 7a 65 20 43 30c 20 3d 20 30` (`C` U+0043 + U+030C COMBINING CARON).
Both tokenize to `['size','Č','=','0']` and subtokenise to `['size','Č','=','0']`.
So the ≡ is real and it is step 1 that produces it. (`run53.py`.)

**Result: 0 failures out of 11.**

## Section 3 — corpus measurements I ran myself

Full pass over the LMDB at `~/.cache/Isabelle_Semantic_Embedding/semantics.lmdb`,
`expr` field, 1,362,096 records, 198 s (`corpus_stats.py`):

| quantity | measured |
|---|---|
| records with an `expr` | 1,362,096 |
| `unicodedata.normalize('NFC', expr) != expr` | **0** |
| `unicode_of_ascii(NFC(expr)) != NFC(expr)` | **0** |
| rendered separators produced by ⇩/⇧ | 90 |
| of those, covered by the old class `[_.⁰-₟²³¹]` | 44 (46 missed) — matches §5.4 |
| the 46 missed chars | `ʰʲʷʸˡˢˣᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁᵂᵃᵇᵈᵉᵍᵏᵐᵒᵖᵗᵘᵛᵢᵣᵤᵥᶜᶠᶻⱼⱽ` |
| documents containing ≥1 of the 46 | 38,086 = **2.80 %** of 1.36 M |
| documents with ≥1 fallback-kept token | 51,891 = **3.81 %** of 1.36 M |
| distinct fallback-kept tokens | **154** |
| commonest fallback tokens (occurrences) | `ᵣ` 9,261 · `⁺` 8,236 · `ₛ` 7,698 · `ₚ` 7,623 · `₁` 7,023 · `₀` 5,651 · `ₐ` 5,530 · `ₘ` 5,134 · `⁼` 4,231 · `ᵢ` 3,968 · `²` 3,955 · `ₕ` 3,732 |
| documents with token `xᵢ` | 159 |
| documents containing `❙` after step 3 | 11,420 |
| documents containing `⇩⇩` / `⇧⇧` / `❙❙` | **0** |
| separator-only subtokens under the OLD class + narrowed rule | 833,510 across 159,508 documents |


## Section 4 — second corpus pass (corpus_stats2.py, 69 s) and third (corpus_stats3.py, 72 s)

| quantity (all over the 1,362,096 `expr` records) | measured |
|---|---|
| docs with a multi-digit numeral outside an identifier | 14,986 = 1.100 % |
| docs with a standalone `'` token (type variables) | 168,036 = 12.34 % |
| docs with a standalone `_` token | 17,981 = 1.320 % |
| docs where a `_` token is immediately followed by an all-rendered token | 2,168 |
| docs containing a literal `\<` | 3,562 |
| distinct no-code-point `\<…>` kinds occurring in `expr` | 16 |
| of those, kinds containing `_` | 3 — `\<^named_theorems>` (13 docs), `\<^const_name>` (5), `\<^type_name>` (1) |
| the 20 non-separator `\<^…>` control symbols with a code point | 12 never occur; 8 occur, in 261 docs (`\<^emph>` 190, `\<^marker>` 30, `\<^here>` 10, `\<^theory_text>` 9, `\<^undefined>` 8, `\<^cancel>` 7, `\<^url>` 6, `\<^verbatim>` 1) |
| docs with token `Fₒ` | 116 |
| docs with the token run `['Obj','⇩','A']` | 98 |
| docs with the run `['Fₒ','Obj','⇩','A']` | **0** (§5.4's "never adjacent" holds) |
| Unicode code points satisfying `isalpha()` | 136,104 (Lu 1831, Ll 2233, Lt 31, Lm 397, Lo 131612) |
| Unicode code points satisfying `isdigit() or isnumeric()` | 1,912 (Nd 680, No 915, Nl 236, **Lo 81** — also letters) |
| Unicode code points satisfying `isspace()` | 29 |
| `etc/symbols` letter/greek group symbols | 164, **all** with a code point, **all** `isalpha()` |
| letter-group chars ∩ rendered separators | ∅ |
| ASCII-symbolic chars ∩ separator class | ∅ |
| non-BMP chars in the separator class | none |
| of the 90 rendered separators: `isalpha()` / digit-ish / neither | 60 / 20 / 10 |

## Section 5 — §5.4's worked examples (plan lines 800–806), reality check

Run with `corpus_probe.py` (the plan's own harness, §16.1), full corpus:

| §5.4 line | example | is it real? |
|---|---|---|
| 801 | `['sorted_wrt','R','xs'] → ['sorted','wrt','R','xs']` | real — the run occurs in **52** documents |
| 802 | `['Kelly_1_39'] → ['Kelly','1','39']` | real — `Kelly_1_39` is a real name, **16** records (`EnrichedCategory.Kelly_1_39_def`, `…intro`, `…axioms(4)`) |
| 803 | `['Fₒ','Obj','⇩','A'] → ['F','Obj','A']` | **labelled fabricated, and the label is right** — the 4-token run occurs in **0** documents; `Fₒ` alone in 116, the run `['Obj','⇩','A']` in 98. The arithmetic of the example is nevertheless correct. |
| 804 | `['x','+','y'] → ['x','+','y']` | real — **3,138** documents |
| 805 | `['⟦','P',';','Q','⟧','⟹'] → unchanged` | real — **20** documents (`FOL.iffCE`, `IFOL.conjI`, `IFOL.conjE`) |

§16.2's matching claims (lines 2154–2158) also reproduce: `sorted` matches
`sorted_wrt`, `sort` does not, `image_join` matches `path_image_join`,
`join_path` does not. 4/4.

## Section 6 — findings

### F1. §5.1's five-step pipeline contains no step that folds `⇩x` → `ₓ`, yet everything in §5.4 depends on that fold. A port that folds only inside its escape expander passes all 32 lines of §16.2 and all of §5.3, and then breaks on Unicode input.

    WHERE:      §5.1 step 3 (plan line 745): "`unicode_of_ascii(s)` — so a user
                may type `\<Longrightarrow>` or `⟹`. Identity on stored text."
                `unicode_of_ascii` is `pretty_unicode`, Isabelle_RPC_Host/unicode.py:185–206.
                It does TWO substitutions, not one: first `\<name>` → code point,
                then `re.sub(r'⇩.|⇧.|❙.')` against the SUBSUP_TRANS_TABLE dict,
                which turns `⇩i`→`ᵢ`, `⇧T`→`ᵀ`, `❙x`→`𝐱`. §5.4 speaks of "the
                folding" and of "the rendered characters the folding produces"
                but never says which pipeline step performs it, and none of
                §5.1's five steps does.
    READING A:  step 3 = expand escapes, then fold every ⇩/⇧/❙ pair in the whole
                string, whatever its origin. (What the prototype does.)
    READING B:  step 3 = expand escapes, folding each `\<^sub>`/`\<^sup>`/`\<^bold>`
                as it is expanded, together with whatever follows it. This is the
                natural structure for a port, because it is the reading in which
                step 3 really is "so a user may type `\<Longrightarrow>` or `⟹`" —
                a converter for the ASCII escape route only.
    DIVERGES:   already-Unicode input, no backslash anywhere.
                  'x⇩i + y⇧T'  A ['x','+','y']            B ['x','i','+','y','T']
                  'x⇩1 + y'    A ['x','+','y']            B ['x','1','+','y']
                  'f⇩1'        A ['f']                    B ['f','1']
                  '[x]⇧c⇧e'    A ['[','x',']','ᶜᵉ']       B ['[','x',']','c','e']
                  '❙x ❙('      A ['𝐱','(']                B ['x','(']
                I implemented Reading B (`checks4.py::tokenize_B`) and ran it:
                **0 failures on all 32 lines of §16.2.**
    VECTORS:    provably cannot catch it. §16.5's 10,000 real triples are drawn
                from stored expressions, and I measured that
                `unicode_of_ascii(expr) == expr` for **all 1,362,096** of them —
                i.e. no stored expression contains an unfolded ⇩/⇧/❙ pair, so no
                real triple exercises the fold. Every ⇩-bearing line in §16.2 is
                written in the `\<^sub>` escape spelling, which both readings
                agree on. §16.5's mandatory synthetic list asks for "ASCII-escaped
                input" and "sub/superscripts that have no fold entry" — neither is
                a foldable already-Unicode pair. §5.3 line 782 *is* written with a
                raw `⇩`, but it is an equivalence (`'x⇩1 + y' ≡ 'x⇩1+y'`) and it
                holds under both readings — I ran it: True/True under Reading B.
                Real user input: Isabelle/jEdit stores symbols as U+21E9 in the
                buffer, so anything copied out of jEdit carries raw `⇩`.
    SEVERITY:   silently-wrong-results

### F2. Two functions in `site/prototype/` implement §5.4's separator class over an identical character set; only one has the fallback clause; nothing in §5 says which is normative.

    WHERE:      `subtoken_rule.py::subtokens` (has the fallback) versus
                `tokenize_prototype.py::subtokens_rev` (does not). I tested every
                candidate character: `FULL_SPLIT` and `SUBTOK_SPLIT` have
                **identical membership** — zero differences. The fallback clause
                is the only difference between the two functions.
                §5.4's code block is `subtokens`, but §5 never names a file or a
                function, and `tokenize_prototype.py`'s own module docstring
                (lines 1–5) advertises itself as "Revised tokenizer … with
                subtokens() narrowed per the revised rule". Only §16.1 line 2094,
                in a different section, calls its variants "superseded". §16.3
                step 1 says the production implementation is "lifted from
                `site/prototype/`" without naming the function.
    READING A:  lift `subtoken_rule.subtokens`.
    READING B:  lift `tokenize_prototype.subtokens_rev` — it is in the file whose
                name says "tokenize prototype", it is the last-defined and
                best-named variant there, and its `__main__` block prints it as
                the `full=` column.
    DIVERGES:   '[x]\<^sup>c\<^sup>e'  A ['[','x',']','ᶜᵉ']  B ['[','x',']']
                '²'                     A ['²']                B []
                Corpus scale: 51,891 documents (3.81 %) carry at least one
                fallback-kept token; 154 distinct such tokens.
    VECTORS:    the vector file is *generated by* the Python implementation
                (§16.3 step 4, §16.5). If the Python side lifts the wrong
                function, the vectors record the wrong answers and the JS port
                reproduces them exactly. §16.6's digest rule fails to help: the
                count is right and the digest is self-consistent.
    SEVERITY:   silently-wrong-results

### F3. §5.4 and §16.2 say the separator class is "derived from `etc/symbols`, never hand-written". 90 of its 99 characters come from a hand-written Python dict, and §16.4 never asks the export to emit that dict.

    WHERE:      §5.4 lines 815–817, §16.2 lines 2112–2114, README line 9.
                `RENDERED_SEPARATORS` is built from `SUBSUP_TRANS_TABLE`, a
                literal dict at Isabelle_RPC_Host/unicode.py:121–151.
                `etc/symbols` carries `code:`, `group:`, `font:` and `abbrev:`
                fields only — it contains no folding information at all, so the
                90 characters are not derivable from it by any means.
                Only the 7 control characters are etc/symbols-derived.
    READING A:  ship the 99 characters as data, as §16.4 says.
    READING B:  derive them at export time from `etc/symbols`, as §5.4 says they
                are derived — which yields 9 characters, silently.
    DIVERGES:   the whole subtoken rule. Under a 9-character class, `x⇧c⇧e`
                subtokenises to `['xᶜᵉ']` instead of `['x']`, and every one of
                the 38,086 documents (2.80 %) containing one of the 46
                previously-missed rendered characters indexes differently.
    VECTORS:    the vectors would catch a divergence *between the two ports*, but
                not this: this is a failure mode of the single export step that
                feeds both. Both implementations read the same asset, so both are
                wrong together and the gate is green.
    ALSO:       `SUBSUP_TRANS_TABLE` is hand-curated and *incomplete*: `⇩` has no
                entry for b, c, d, f, g, q, w, y, z or any capital; `⇧` has none
                for q, r, C, F, Q, S, X, Y, Z. §5.4 leans on exactly this
                asymmetry (`Obj⇩A` survives unfolded, `❙(` is stranded) without
                ever saying the table is partial or where it lives. §16.4's asset
                list does not include it, so the JS port has no way to fold.
    SEVERITY:   silently-wrong-results

### F4. §5.1 step 4 says a `\<foo>` with no code point "can therefore never be cut in half". The subtoken split cuts it in half, on real data.

    WHERE:      §5.1 lines 747–750. The claim is true of tokens and false of
                subtokens, which under D21 is the only level indexed or queried.
                `SUBTOK_SPLIT` splits on `_`, and 34 of `etc/symbols`' 73
                no-code-point symbol names contain `_`.
    DIVERGES:   tokenize(r'\<^const_name>')  → ['\<^const_name>']    (one token)
                subtokens(...)                → ['\<^const', 'name>']  (cut in half)
                Reading B — carry the symbol list through the subtoken step and
                split only at separator *symbols*, which is what §5.1's sentence
                tells you to do — gives ['\<^const_name>'].
                Real data: 19 stored expressions contain such a symbol —
                `\<^named_theorems>` (13 documents), `\<^const_name>` (5),
                `\<^type_name>` (1).
    VECTORS:    §16.2 has no `\<…>` with an underscore. §16.5's mandatory
                synthetic list has none either. 19 documents in 1.36 M means a
                10,000-triple random sample draws one with probability ~0.014 %.
    SEVERITY:   degraded-results

### F5. `symbol_explode` accepts an unterminated `\<…>` as one symbol. Nothing in §5 or §16 says so, and the ASCII-escape input route §9.3 promises is exactly where half-typed escapes occur.

    WHERE:      position.py:40–54 emits `text[i:j]` whether or not it found the
                closing `>`. §5.1 step 4 describes only the terminated case.
    READING A:  prototype — `\<Longrightarrow` (no `>`) is ONE symbol.
    READING B:  a scanner that requires the `>`, e.g. the obvious JS regex
                `/\\<\^?[A-Za-z][A-Za-z0-9_']*>/`, so an unterminated escape
                falls through to character-level classification.
    DIVERGES:   'A \<Longrightarrow B'  A ['A','\<Longrightarrow','B']
                                        B ['A','\<','Longrightarrow','B']
                '\<='                   A ['\<','=']       B ['\<=']
                '\<^sub'                A ['\<^sub']       B ['\<^','sub']
    VECTORS:    no stored expression can contain an unterminated escape (they are
                all well-formed), so the 10,000 real triples cannot reach it.
                §16.5 asks for "ASCII-escaped input", not *unterminated*
                ASCII-escaped input; §16.2 has none.
    SEVERITY:   degraded-results

### F6. `_` and `'` cannot begin an identifier — and §5.4's `_wrt` example, the plan's own load-bearing counter-example, does not pin that.

    WHERE:      §5.4 lines 796–798: "A token consisting only of separators
                disappears entirely, which is what makes the user's query `_wrt`
                compile to `['wrt']` rather than to `['_','wrt']`."
                The sentence describes the mechanism correctly — I ran it:
                `tokenize('_wrt')` is `['_','wrt']`, two tokens, and the `_`
                token is separator-only and disappears. But the example does not
                *discriminate*: under the ordinary lexer convention
                `identifier = [letter|_|'][letter|digit|_|']*`, `_wrt` is ONE
                token, `SUBTOK_SPLIT.split('_wrt')` is `['','wrt']`, and the
                answer is `['wrt']` either way. A reader who checks their
                grouping against this example learns nothing about it.
    READING A:  identifiers begin with a letter only (§5.2's actual words).
    READING B:  identifiers may begin with a quasi-letter too (the convention
                everyone writes reflexively, and the one under which the `_wrt`
                example still comes out right).
    DIVERGES:   wherever a leading `_` is followed by rendered-only material,
                because the fallback clause is applied *per token*:
                  'f _\<^sub>1'          A ['f','₁']   B ['f']
                  '_\<^sup>c\<^sup>e'    A ['ᶜᵉ']      B []
                  '(_\<^sub>1)'          A ['(','₁',')']  B ['(',')']
                and on every type variable:
                  "'a list"              A ["'",'a','list']  B ["'a",'list']
                Real data: 2,168 documents have a `_` token immediately followed
                by an all-rendered token (e.g.
                `Core_DOM_BaseTest.get_child_nodes⇩Cₒᵣₑ⇩_⇩D⇩O⇩M_with_null.elims`);
                168,036 documents (12.34 %) contain a standalone `'` subtoken.
    VECTORS:    the `'a` half is caught by any real sample (12 % of documents).
                The `_`-plus-rendered half is at 0.16 %, ~16 expected draws in
                10,000, and it is commonest in *names* while §16.5 samples
                *expressions* only. §16.2's only quote case is `"f'"` — a
                *trailing* quote, which both readings agree on. The type variable
                `'a`, the most common Isabelle-specific token shape there is, is
                absent from §16.2 entirely.
    SEVERITY:   degraded-results

### F7. A numeral not preceded by a letter becomes one subtoken per digit. §5 never says so and §16.2 has no case.

    WHERE:      §5.2 lines 760–765. An identifier must begin with a letter, and a
                digit is not one, so a leading digit falls to "anything else: one
                symbol, one token".
    DIVERGES:   'n < 100'   A ['n','<','1','0','0']   B ['n','<','100']
                '2 ^ 32'    A ['2','^','3','2']       B ['2','^','32']
                'Kelly_1_39' both ['Kelly','1','39'] — so the *same* numeral is
                one subtoken inside an identifier and N outside.
                Reading B ("a maximal run of digits is a token") is invited by
                D41/§16.4 emitting a separate "digits" code-point set.
                User-visible: the query `39` compiles to `['3','9']` and can
                never find `Kelly_1_39`, whose array holds `'39'`.
                Real data: 14,986 documents (1.100 %) contain a multi-digit
                numeral outside an identifier — e.g.
                `PromelaDatastructures.hashcode_varType.simps(2)`,
                `hashcode VTChan = 23` → `['hashcode','VTChan','=','2','3']`.
    VECTORS:    at 1.1 % a 10,000-triple sample draws ~110, so the *port* gate
                would catch it. What it does not catch is §16.3 step 1, whose
                stated acceptance criterion for the production **Python**
                implementation is "reproduces every line of §16.2" — and §16.2
                has no standalone multi-digit numeral. The Python implementation
                can be accepted with the wrong rule and then generate the vectors.
    SEVERITY:   degraded-results

### F8. §5.2's "letter" is `isalpha()` — 136,104 code points. The `etc/symbols` half of the definition adds exactly zero of them, and §16.4's phrasing makes it sound like the substantive half.

    WHERE:      §5.2 lines 761–763 and §16.4 lines 2210–2213: "**letters**
                (including the `letter` and `greek` group symbols of `etc/symbols`)".
    MEASURED:   the `letter`/`greek` groups hold **164** symbols; **all 164** have
                a code point and **all 164** satisfy `isalpha()`. The union in
                §5.2 is therefore exactly `isalpha()`, which is 136,104 code
                points (categories Lu 1,831 · Ll 2,233 · Lt 31 · Lm 397 ·
                Lo 131,612). An implementer who reads §16.4 as "emit the
                etc/symbols letter set" emits 164 code points instead of 136,104
                and every non-ASCII identifier stops grouping.
    ALSO:       §16.4 emits a "letters" set and a "digits" set that **overlap in
                81 code points** (the CJK numerals, category Lo and numeric), and
                never says which test wins. The prototype tests letter first, so
                such a character *starts* an identifier. Two ports can differ
                here with no sentence to appeal to. No realistic Isabelle input.
    ALSO:       `tokenize_prototype._is_letter`'s `len(sym) > 1` branch
                (`sym in _LETTER_SYMS`) is **dead code**: 0 of the 164 letter/greek
                symbols lack a code point, so no letter symbol ever survives step
                3 as a multi-character string. It contradicts §5.2's "anything
                else: one symbol, one token — including a whole `\<foo>`" and
                should not be carried into the port.
    SEVERITY:   degraded-results (silently-wrong if the letters asset is built
                from `etc/symbols` alone)

### F9. Every percentage in §5.4 has an unstated denominator of 230,944 — 17 % of the corpus §16.2 defines. D41 and §16.4 repeat one of the raw counts as "occurrences in the corpus", where it is 6× low.

    WHERE:      §5.4 lines 852–853 (7,346 documents, 3.18 %), 863 (6,445, 2.79 %),
                864 (20 documents containing `xᵢ`), 870 (1,689 with `❙`), 876
                (112,680 separator-only subtokens across 24,654 documents,
                10.68 %); D41 line 189 and §16.4 line 2204 ("`²` … 640
                occurrences in the corpus").
                7,346/0.0318 = 231,006; 6,445/0.0279 = 231,004;
                24,654/0.1068 = 230,843 — all ≈ **230,944**, the `isa-scale-test`
                namespace of §3.3 line 549, which §3.3 line 553 says is
                "18.6 % of the real corpus". §5.4 names no denominator anywhere,
                and §16.2 line 2161 states the corpus scale as 1,362,096
                expressions one section away. Divide by that and 7,346 documents
                is 0.54 %, not 3.18 %.
    MEASURED    (mine, over all 1,362,096 expressions):
                fallback-token documents 51,891 (3.81 %), 154 distinct such tokens;
                the-46-missed-characters documents 38,086 (2.80 %);
                documents with token `xᵢ` 159; documents containing `❙` 11,420;
                standalone `²` token 3,955 occurrences (not 640);
                standalone `₁` token 7,023 occurrences (not 1,281).
                §5.4 line 872's "14 never occur, and the remaining 6 occur in 11
                documents in total" is, on the real corpus, **12 never occur and
                8 occur in 261 documents** (`\<^emph>` alone in 190).
                §5.4 line 810's "`Fₒ` occurs in 50 documents and `Obj⇩A` in 44"
                is 116 and 98 on the real corpus — a ratio of 2.3, not the 5.9
                the 230,944 denominator would predict, so §5.4's numbers come
                from at least two different unstated denominators.
    SEVERITY:   cosmetic for the tokenizer, but these are the numbers that
                justify the rule, and a future implementer re-measuring against
                1.36 M will conclude the plan is wrong.

### F10. §5.2's headline sentence and §16.2's annotation both say whitespace is not a token boundary. It is.

    WHERE:      §5.2 lines 755–757 ("Whitespace produces **no output at all**;
                token boundaries come from the grouping, not from whitespace")
                and §16.2 line 2135 ("← whitespace is not a boundary").
                The code flushes the current token on `sym.isspace()`.
    DIVERGES:   'f x' → ['f','x'] (prototype) versus ['fx'] under the sentence
                read literally — which is the very case §5.3 line 776 declares
                inequivalent. §16.2's own lines 4 and 5 refute the literal
                reading, so the vectors do catch a port that implements it.
    SEVERITY:   cosmetic — but it is the sentence that defines the class, and it
                says the opposite of the code and of §5.3.

## Section 7 — areas checked and cleared

- **`symbol_explode` producing a symbol the separator class splits in half**:
  yes for `_` in symbol names (F4). Beyond that, no: the class contains no
  character that appears inside a code-point-bearing symbol's rendered value,
  the letter-group characters and the rendered separators are disjoint, the
  ASCII-symbolic set and the separator class are disjoint, and the separator
  class contains no non-BMP character.
- **NFC stability**: `unicodedata.normalize('NFC', expr) != expr` for **0** of
  1,362,096 expressions, so §3.4's claim holds on the corpus that will be
  indexed. §5.3's `'size Č = 0'` ≡ NFD case reproduces, constructed with
  `unicodedata.normalize('NFD', …)` (U+010C vs U+0043 + U+030C).
- **`unicode_of_ascii` identity on the store**: holds, **0** differences over
  1,362,096 expressions. This is what makes F1 unfalsifiable by the vector file.
- **Double control characters** (`⇩⇩`, the case where the fold's single
  non-overlapping regex pass differs from a fixpoint fold): **0** occurrences in
  the corpus. `'\<^sub>\<^sub>a'` → `['a']` under the prototype; a fixpoint
  folder gives `['ₐ']`. Real only for a hand-typed query; not worth a finding.
- **CR normalization** in `symbol_explode` (`\r\n`/`\r` → `\n`), undocumented in
  §5.1: no effect, both are `isspace()` and both are discarded.
- **The `.` in the fold regex not matching newline**: no effect; `⇩\n` has no
  fold entry either way.
- **U+FEFF**: survives as its own token *and* its own subtoken
  (`'x﻿y'` → `['x','﻿','y']`). D41 flags the character; §16.5 requires
  it in the vectors. Cleared.
- **U+001C–U+001F, U+0085, U+00A0, U+000B**: all boundaries under the prototype;
  D41 already records the JS `\s` divergence for the first two.
- **`?` as a boundary as well as a discard**: undocumented in §5.2's wording
  ("discard"), but pinned by §16.2 line 2134 (`'a?b'` → `['a','b']`) with an
  explicit annotation. Cleared.
- **§16.2's matching claims** (lines 2154–2158): 4/4 reproduce.
- **§5.4's worked examples**: 4 of 5 verified real on the corpus, the fifth
  correctly labelled fabricated and verified to occur 0 times. See Section 5.

## Section 8 — leftovers from an earlier design, in the code

- `tokenize_prototype.py` lines 30–36 and 67–90: `OLD_CLASS` (the hand-written
  `[_.⁰-₟²³¹]`), `OLD_SPLIT`, `subtokens_old`, `MIN_CLASS`, `MIN_SPLIT`,
  `subtokens_rev_min`, `subtokens_rev` — all superseded, none named in §5, and
  `subtokens_rev` is the F2 trap.
- `tokenize_prototype.py` lines 8–9 hard-code the absolute paths
  `/home/qiyuan/Current/MLML/contrib/Isabelle_RPC` and `…/Isabelle2025-2`.
  §16.1 praises `corpus_probe.py` for resolving these relative to itself; the
  file the port is to be lifted from does not.
- `subtoken_rule.py` sets `sys.path` only under `__main__`, so importing it
  requires the caller to have arranged the path first.
- `tokenize_prototype.py` line 13 binds `_REV` and `_TRANS`, both unused.
- `_is_letter`'s `len(sym) > 1` branch is dead (F8).
