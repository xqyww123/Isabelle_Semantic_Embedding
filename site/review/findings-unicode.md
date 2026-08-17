# Review — Unicode, character classes, and the Python/JavaScript gap (D41)

All numbers below were produced by running code. Environment: Python 3.12.3
(`unicodedata.unidata_version` = **15.0.0**), node **v20.20.2**
(`process.versions.unicode` = **17.0**). Corpus = `~/.cache/Isabelle_Semantic_Embedding/semantics.lmdb`,
1,362,096 records with an `expr`, 1,362,343 with a `name`.
Scripts under `scratchpad/rev4/`.

---

## F1. §5.2's "a single character" is a code point in Python and a UTF-16 code unit in JavaScript; 4.17 % of the corpus has astral characters in its subtokens, and D41's code-point *sets* do not fix this because the ambiguity is in how a string is *iterated*, not in what the classes contain.

WHERE:
  - §5.2: "*Letter* = **a single character** for which `isalpha()` holds".
  - §5.1 step 4: `symbol_explode` — its else-branch is `result.append(text[i]); i += 1`
    (`contrib/Isabelle_RPC/Isabelle_RPC_Host/position.py:56-58`).
  - `tokenize_prototype.py:40` `_is_letter`: `... if len(sym) == 1 else sym in _LETTER_SYMS`.
  - D41 / §16.4 emit *code-point sets*. Neither says what a "character" is when
    iterating, nor that strings must be iterated by code point.

READING A (Python semantics, what the prototype does): a string is a sequence of
  code points. `text[i]` is one code point; `len(sym) == 1` means one code point.

READING B (the obvious JavaScript transliteration): `text[i]` is one UTF-16 code
  unit; `sym.length === 1` means one code unit. An astral character is two units.
  This is the *literal* port of the Python, and nothing in §5, D41 or §16.4
  forbids it.

DIVERGES (ran `scratchpad/rev4/js4.mjs` with node v20.20.2, and
  `scratchpad/rev4/p1.py` / `p7.py` with the prototype):

```
input            Python prototype        naive JS port
'\<^bold>x'      ['𝐱']  (U+1D431)        ["\ud835","\udc31"]      2 tokens
'x\<^bold>a'     ['x𝐚'] (one identifier) ["x","\ud835","\udc1a"]  3 tokens
'\<bool>'        ['𝔹']  (U+1D539)        ["\ud835","\udd39"]
'\<AA> \<bool>'  ['𝔄','𝔹']               ["\ud835","\udd04","\ud835","\udd39"]
```
  A *partly* fixed port — one that iterates by code point but keeps
  `sym.length === 1` for the letter test — is worse, because it agrees with
  Python on the common case and disagrees on the rest: `𝒮` alone still becomes
  one token (by accident, via the "anything else: one symbol, one token"
  branch), but any astral letter adjacent to another letter splits.
  **Measured (`scratchpad/rev4/scan2.py`, 32 s): 5,219 expressions and 771 names
  carry a subtoken that mixes an astral character with at least one other
  character** — `𝔄𝔯𝔦𝔱𝔶` (1,440), `𝔇𝔢ℑ𝔫𝔩` (1,411), `𝔗𝔶𝔭𝔢𝔒𝔣𝔒𝔭` (899),
  `𝒱s` (922), `𝔉'` (704), `𝒩i`, `λ𝒱`, `ℱ𝒢`, `𝗆𝖺𝗉`. Every one of those splits
  under the half-fix and is then unmatchable.

  Scale, measured in one full pass (`scratchpad/rev4/scan.py`, 166 s):
  **56,797 of 1,362,096 expressions (4.17 %) and 5,087 names contain a character
  above U+FFFF, and all 56,797 still carry one in their subtoken array.**
  Commonest: `𝒮` U+1D4AE (15,606 subtoken occurrences), `𝔄` U+1D504 (14,423),
  `𝒯` (12,623), `𝒢` (10,734), `𝔅` (10,854), `𝔉` (10,639), `𝖺` (10,475),
  `𝗂` (10,339), and the bold digits `𝟬` U+1D7EC (6,281) / `𝟭` (4,491).
  **124 of the 439 code-point-bearing entries in `etc/symbols` (28 %) map to an
  astral character** — the whole script (`\<A>`…`\<Z>`), fraktur (`\<AA>`…`\<zz>`),
  blackboard-bold (`\<bbbA>`, `\<bool>`), sans-serif (`\<a>`…`\<z>`), bold-digit
  (`\<zero>`…`\<nine>`) and document-markup (`\<^url>` 🌐, `\<^doc>` 📓,
  `\<^dir>` 🗀, `\<^file>` 🗏) families. `SUBSUP_TRANS_TABLE` adds 52 more via
  `\<^bold>` (`𝐚`–`𝐳`, `𝐀`–`𝐙`).

  JSON does not save the port: `JSON.stringify(["\ud835","\udc31"])` is
  well-formed (ES2019) and round-trips through UTF-8 unchanged, so the two
  unpaired surrogates travel to turbopuffer as two perfectly valid, permanently
  unmatchable subtokens. No error anywhere.

VECTORS: §16.2 contains **exactly one** astral case, `'\<^bold>x \<^bold>('` →
  `['𝐱','(']`, and §16.5 requires it. But `\<^bold>` is the *rarest* of the three
  routes into the astral plane — the 56,797 corpus documents get there through the
  `etc/symbols` **table**, not through `SUBSUP_TRANS_TABLE` folding. A port author
  who fails that one vector fixes the fold path (make the `⇩.|⇧.|❙.` replacement
  code-point-aware) and stops; `\<S>` → `𝒮` still breaks. The 10,000 real-data
  triples would probably catch it — but §16.5 pins only a *count* and a digest,
  never the sampling method, so "10,000 triples sampled from real entity
  expressions" is satisfied by a sample of short expressions or of the first
  10,000 keys. The gate's coverage of the largest single divergence in this
  review is therefore an accident of an unpinned sampling procedure.

SEVERITY: silently-wrong-results.

---

## F2. `\p{L}` is not `isalpha()`: 9,568 code points apart on this machine, because the two sit on different Unicode versions. D41's asset removes the drift only for as long as index and asset ship together — which §16.4 does not require.

WHERE: D41 / §16.4 — "the export emits ... the explicit code-point sets ...
  Neither implementation may consult a language built-in." §16.3 step 1 says the
  production Python "reads its character classes from the emitted assets".

READING A: emit the set once from the export machine's Python; both sides read it.
READING B: the port uses `\p{L}` (the obvious substitute D41 warns about but
  which §16.4 never lists a divergence for — D41's measured list covers `\p{Nd}`
  and `\s`, not `\p{L}`).

DIVERGES (`scratchpad/rev4/js3.mjs`, node v20.20.2 vs Python 3.12.3):
```
Python  isalpha()  136,104 code points   ( == Unicode category L*, exactly; 0 difference)
node    \p{L}      145,672 code points
        \p{L} not isalpha: 9,568        isalpha not \p{L}: 0
        e.g. U+088F, U+0C5C, U+0CDC, U+1C89, U+1C8A, U+A7CB…A7CD
```
  The whole 9,568 is Unicode-version drift (15.0 → 17.0), not a definitional
  difference. Which means the same hazard exists on the *Python* side across
  Python releases (3.12 = Unicode 15.0, 3.13 = 15.1, 3.14 = 16.0). Pinning the
  set into an asset makes the two implementations agree **with each other**; it
  does not make a re-export agree with the index already in turbopuffer. §16.4
  does not say the asset is versioned with the index, and §5.5 versions only the
  *test vector file* with the data.

  Sizing, since D41 calls for an "explicit letter code-point set": 136,104 code
  points, of which **87,139 (64 %) are astral** — 1.02 MB as a flat JSON array,
  **10.2 kB as 659 ranges** (`scratchpad/rev4/p6.py`). So the asset is small and
  the set is finite and enumerable; the size worry is unfounded, but a JS port
  must do range binary search, not `new Set()` (136 k V8 Set entries in a Worker
  is several MB of heap).

VECTORS: the 9,568 drifting code points are all in scripts (Arabic, Kannada,
  Cyrillic extensions, Latin extended-D) that occur nowhere in an Isabelle corpus,
  so no sampled real triple exercises them and §16.5's synthetic list names none.
  A `\p{L}`-based port passes the gate today and diverges the first time a user
  pastes text in one of those scripts — or, more likely, the first time the export
  machine's Python is upgraded and the index no longer matches the deployed asset.

SEVERITY: degraded-results (query side) / silently-wrong-results (asset–index skew).

---

## F3. The letter/greek group of `etc/symbols` contributes **nothing** to the letter class — all 164 of its members are already `isalpha()`. §5.2's two-limbed definition is one limb, and D41's asset spec inherits a redundancy that reads like a requirement.

WHERE: §5.2 "*Letter* = a single character for which `isalpha()` holds, **or** one
  of the `letter`/`greek` group symbols of `etc/symbols` (`get_LETTER_SYMBOLS`)";
  §16.4 "**letters** (including the `letter` and `greek` group symbols of
  `etc/symbols`)"; `unicode.py:105` and `tokenize_prototype.py:14,40`.

MEASURED (`scratchpad/rev4/p5.py`):
```
get_LETTER_SYMBOLS()                       164 symbols
  … that have a code point                 164   (none without)
  … whose character satisfies isalpha()    164   (all of them)
  … that are astral                        110
genuine extras (in the group, not isalpha):  0
```
  So `_LETTER_CHARS` in `tokenize_prototype.py:14` is a subset of `isalpha()` and
  the `or` never fires. And because every one of the 164 has a code point,
  `unicode_of_ascii` (step 3) converts all of them, so the multi-character branch
  of `_is_letter` (`sym in _LETTER_SYMS`, for a `\<foo>` that survived step 3)
  is unreachable in the pipeline too — the only escapes that reach step 5 intact
  are the 32 code-point-less kinds in §3.4's 1,140 records, none of which is in
  the letter/greek group.

CONSEQUENCE: an implementer who takes §5.2 at its word builds a *union* of a
  code-point set and a **string** set, and has to decide what `sym in
  _LETTER_SYMS` means for a multi-character symbol — a decision with no
  observable consequence, which is exactly the kind of dead requirement that
  gets implemented differently in two places and then becomes live when someone
  adds a letter-group symbol without a code point to `etc/symbols`.

VECTORS: unobservable today, so no vector can distinguish the readings. That is
  the point: the spec asks for machinery the vectors cannot constrain.

SEVERITY: cosmetic today; a latent silent divergence if `etc/symbols` ever gains
  a letter-group symbol with no code point.

---

## F4. `isdigit()` ⊆ `isnumeric()` exactly, so D41's single "digits" asset is sound — but 81 code points are in **both** the letter and the digit asset, ten of them occur in the corpus, and neither §5.2 nor D41 says which class wins.

WHERE: §5.2 "*Digit* = `isdigit()` or `isnumeric()`"; D41 emits "**digits**" as one
  set and "**letters**" as another, and says nothing about their intersection.
  §5.2's identifier rule is "a maximal run **beginning with a letter** and
  continuing with letters, digits or quasi-letters" — the prototype
  (`tokenize_prototype.py:56`) tests `_is_letter` first.

MEASURED (`scratchpad/rev4/p5.py`, `p6.py`, corpus pass `scan.py`):
```
isdigit()                808        isnumeric()   1,912        union  1,912
isdigit but not isnumeric    0      → the union IS isnumeric(); one asset suffices ✓
of the union: astral     1,112      not \p{Nd}    1,232        (node \p{N} = 1,924)
in BOTH the letter and the digit asset:  81 code points
   — the CJK ideographic numerals, category Lo: 一 二 三 四 五 六 七 八 九 十 …
in the corpus: 一二三四五六七八九十, 50 occurrences each
also in the corpus: ₁ (75,455) ₂ (59,745) ₀ (50,938) ₃ (7,895) ² (7,196)
   𝟬 (6,281) 𝟭 (4,491) ⁰ ¹ ³ ⁴ ₄–₉, and ½ U+00BD (2) — isnumeric() but NOT isdigit()
```
  `½` is a second documented-`²`-class case D41 does not mention: it is
  `isnumeric()`-only, so a port that reads "digit" as `isdigit()` alone, or as
  `\p{Nd}`, loses it. It occurs twice, so the consequence is tiny — but it shows
  the union is not `isdigit()` and not `\p{Nd}`.

READING A: build one `classOf(cp)` lookup by loading letters first, then digits
  (digits overwrite): `一二三` are digits → cannot start an identifier → each falls
  to "anything else, one symbol one token".
READING B: load digits first, then letters (letters overwrite), or test
  `isLetter` before `isDigit` as the prototype does: `一二三` are letters → they
  start and continue an identifier.

DIVERGES: `一二三` → Reading A `['一','二','三']`, Reading B `['一二三']`. Building a
  single class table from five overlapping sets is the natural way to consume
  D41's assets in JavaScript, and the spec never says the sets are disjoint or
  gives a precedence.

VECTORS: §16.2 has no CJK line and §16.5's synthetic list names only `²` and
  U+FEFF. Measured: **142 expressions** contain a CJK numeral (the AFP `Chinese`
  theory), 0.01 % of the corpus, so a 10,000-triple real sample contains one with
  probability ≈ 0.65 — a coin flip. Inspected all six sampled examples
  (`scratchpad/rev4/scan2.out`): in every one the numeral is isolated
  (`cons 一`, `|五| = 5`), so the two readings agree on today's data and the
  divergence needs `一二` adjacent or `十x`. Honest severity: the ambiguity is
  real and unpinned, the blast radius on this corpus is currently zero.

  One thing the same examples do show, which no §16.2 line covers: `'|十| = 10'`
  → `['|','十','|','=','1','0']`. A bare numeral is **never** one subtoken,
  because a digit cannot begin an identifier, so `10` is two tokens. §16.2's
  `'Kelly_1_39 ?C ?T ?a'` → `['Kelly','1','39',…]` shows `39` staying whole and
  reads as if numbers were atomic; they are atomic only *inside* an identifier.

SEVERITY: degraded-results (potential); zero observed on this corpus.

---

## F5. §16.4 emits no whitespace asset, so the one class D41 measured a divergence for is the one class the port has no data for.

WHERE: D41 lists U+001C–U+001F, U+0085 (`isspace()` but not JS `\s`) and U+FEFF
  (the reverse) as measured divergences — then §16.4's asset list is "**letters**,
  **digits**, **quasi-letters**, **the separator class**, **the ASCII-symbolic
  set**". No whitespace. §5.2's discard rule needs it; §5.5 says "neither
  implementation may consult a language built-in".

MEASURED (`scratchpad/rev4/js2.mjs`, `scan.py`), the complete divergence:
```
Python isspace()  29 code points   JS \s  25 code points
   isspace() minus \s : U+001C U+001D U+001E U+001F U+0085
   \s minus isspace() : U+FEFF
   (everything else identical, incl. U+00A0, U+1680, U+2000–200A, U+2028/9,
    U+202F, U+205F, U+3000)
corpus occurrences of any whitespace other than space/TAB/LF/CR, in expr or name: 0
```
  So the index side is unaffected and the exposure is entirely query-side. U+FEFF
  is the realistic one — a BOM survives a copy-paste and a user pastes it into the
  condition box. Python keeps it (`isspace()` false) → it becomes its own token
  **and its own subtoken**, wedged into the `ContainsTokenSequence` run and
  breaking adjacency; JS `\s` discards it. `'﻿sorted_wrt'` therefore yields
  `['﻿','sorted','wrt']` on one side and `['sorted','wrt']` on the other.

  The class is **not** derivable from the other four assets: U+00A0 is in none of
  letters/digits/quasi/separators/ASCII-symbolic, so "not in any class" would send
  it to the "anything else, one symbol one token" branch instead of discarding it.

VECTORS: §16.5 does pin all six divergent code points, so a port that gets them
  wrong fails the gate — this is the rare case where the vectors are ahead of the
  asset list. The residual is structural rather than behavioural: with no asset,
  the only way to pass is `\s` (a built-in §5.5 forbids) patched with a hard-coded
  six-element delta (a hard-coding D41 exists to abolish), and the resulting class
  is pinned to the *engine's* Unicode version rather than to the data — the exact
  property D41 set out to remove. It also leaves the production Python of §16.3
  step 1 calling `isspace()`, so §16.3 step 2's acceptance test ("the assets load
  standalone, with `Isabelle_RPC_Host` and `ISABELLE_HOME` unavailable") is
  satisfiable while one of the five classes is still a built-in.

SEVERITY: cosmetic behaviourally (all six divergent code points are pinned by
  §16.5); a real hole in D41's stated invariant.

---

## F6. §3.4 never measured NFC. The claim three other sections cite it for is true — I measured it — but the property §5.1 needs is NFC-idempotence of the *pipeline*, which is a different property and does not hold.

WHERE: §5.1 step 1 "the store is already 100 % NFC"; D41 "§3.4: the store is
  100 % NFC and `unicode_of_ascii` is identity on it"; §16.5 "§3.4 established the
  store is 100 % NFC". §3.4 (lines 569–595) states the `unicode_of_ascii`
  identity for all 1,353,394 records, the whitespace-collision count, the PUA
  count, the `\<…>` count, U+007F and CR — **and no NFC measurement at all**.
  `grep -n 'NFC' SEMANTIC_SEARCH_SITE_PLAN.md` returns no hit inside §3.4.

MEASURED, filling the gap (`scratchpad/rev4/scan.py`, full pass):
```
records whose expr is not NFC : 0 / 1,362,096
records whose name is not NFC : 0 / 1,362,343
```
  So the claim is true; it is simply not where the document says it is, and a
  future reader who re-derives it will re-derive a *different* property.

THE CHECK OF THE CHECK. §5.1 runs NFC at step 1 and `unicode_of_ascii` at step 3,
  so everything step 3 inserts is never normalised. Measured over the symbol
  table (`scratchpad/rev4/p2.py`, `p3.py`, `p4.py`):
```
439 symbols carry a code point
  values that are not NFC-stable on their own : 0
  values that are combining marks (Mn/Mc/Me)  : 0     ← this is what makes step 3 safe
  values that are canonical composition STARTERS : 47
      \<alpha> \<epsilon> \<eta> \<iota> \<rho> \<upsilon> \<omega> \<Upsilon>
      \<Omega> \<leftarrow> \<rightarrow> \<Rightarrow> \<le> \<ge> \<in>
      \<subseteq> \<equiv> \<parallel> \<dieresis> …
  SUBSUP_TRANS_TABLE values that are composition starters : 0
```
  "Every value is NFC-stable in isolation" is **not** "the concatenation is NFC".
  A starter inserted at step 3 immediately followed by a combining mark that
  survived step 1 gives a non-NFC token. Ran it (`scratchpad/rev4/p7.py`):
```
'\<alpha>' + U+0301  → tokens ['α', '́']   (two tokens: U+0301 is Mn,
                                                 so it takes the "anything else" branch)
'ά' (U+03AC)         → tokens ['ά']             (one token)
'α' + U+0301         → tokens ['ά']             (step 1 composes it)
```
  Same logical content, three spellings, two different token arrays — because
  U+0301 does not compose with the `>` of `\<alpha>` at step 1, so it is still
  there when step 3 removes the `>`. A related case where step 1 actively
  *destroys* an escape:
```
'\<in>' + U+0338     → step 1 gives '\<in' + '≯' (U+226F)
                     → tokens ['\\<in', '≯']    — the escape is gone and an
                                                  unconverted '\<in' becomes a subtoken
```
  Both implementations agree here (both follow §5.1's numbering), so this is a
  specification defect rather than a Python/JS divergence — but it is what the
  brief's "check the check" asks for: the measured property (store is NFC) is not
  the needed property (the pipeline's output is NFC), and the needed property is
  false. What actually saves the pipeline in practice is the *unstated and
  unmeasured* invariant "no `etc/symbols` value is a combining mark", which I
  measured at 0/439 and which nothing in the plan requires to stay 0.

VECTORS: §16.5 requires "NFD input", which exercises step 1 on ordinary accented
  Latin (`Č`, §5.3) and passes on both readings. It does not require an escape
  followed by a combining mark, and no real record contains one (0 non-NFC
  records in the corpus). Any implementer who "helpfully" normalises again after
  step 3 — a defensible reading of §5.1's stated *purpose* — passes every vector
  and diverges here.

SEVERITY: cosmetic on today's corpus (0 records); the citation error is the
  durable part, because §16.5's whole argument for synthetic vectors rests on it.

---

## Cleared areas (checked, nothing found)

- **NFC itself is not a cross-language risk.** I compared `unicodedata.normalize('NFC', c)`
  against `c.normalize('NFC')` for every one of the 1,112,064 non-surrogate code
  points (`scratchpad/rev4/pynfc.json` + node): **0 mismatches**, despite the two
  runtimes sitting on Unicode 15.0 and 17.0. Unicode's normalization-stability
  policy guarantees this, so step 1 needs no asset and no vector beyond the NFD
  case §16.5 already requires.
- **The 99-character separator class is entirely BMP** (7 controls `⇩⇧⇘⇙⇗⇖❙`,
  90 rendered characters from `⇩`/`⇧` only — `❙`'s 52 outputs `𝐚`–`𝐙` are
  deliberately excluded, and they are the only astral ones). So a JavaScript
  character-class regex behaves identically with or without the `u` flag on it,
  and a lone surrogate can never accidentally match a separator. The `all(c in
  _RENDERED …)` fallback test also gives the same answer under code-unit and
  code-point iteration.
- **The `⇩.|⇧.|❙.` folding regex in `unicode_of_ascii`** does not diverge: every
  key's second character is ASCII, so `.` matching one code unit versus one code
  point changes nothing, and both engines resume scanning after the same amount
  of text.
- **`isalpha()` is exactly Unicode category `L*`** (measured: 0 code points of
  difference in either direction), so the letter class has a clean definition to
  pin the asset against; it is finite at 136,104 code points and compresses to
  659 ranges / 10.2 kB.
- **`isdigit()` is a subset of `isnumeric()`** (0 code points in the difference),
  so D41's single "digits" asset can represent §5.2's union exactly.
- **No `etc/symbols` value is a combining mark** (0 of 439) and none is
  decomposable (0 of 439 fail NFC), which is what makes step 3 safe today —
  see F6 for why that is an invariant nothing currently protects.
- **The corpus contains no exotic whitespace at all** (0 occurrences of any
  `isspace()` character other than space/TAB/LF/CR in `expr` or `name`), so the
  whitespace divergence is purely query-side.
