# Review: §5.4, the subtoken rule, the separator class, the fallback clause

Reviewer lens: the subtoken level (D21 — the only level indexed or queried).
Everything below was run. Scripts are in `scratchpad/tok/`.

---

F1. The fallback clause has exactly one alternative reading that survives every
    §16.2 vector, and it differs on real corpus data.

    WHERE:      `subtoken_rule.py:32`, `elif t and all(c in _RENDERED for c in t)`
                — reproduced verbatim as §5.4's normative code block (line 843).
                The prose that justifies it, §5.4 line 854: "the obvious
                unrestricted version ('keep any token that splits to nothing')
                was measured and **breaks the `_wrt` counter-example outright** —
                `_` would survive".
    READING A:  (implemented) keep the token iff EVERY character is one of the 90
                rendered sub/superscripts.
    READING B:  keep it iff AT LEAST ONE character is rendered — i.e. "keep a
                token that splits to nothing unless it consists only of `_`, `.`
                and control markers". This is the minimal repair that §5.4's own
                justification sentence asks for: the only defect named in the
                unrestricted version is that `_` survives, and Reading B fixes
                exactly that. §5.4's other sentence, "a token made *entirely* of
                rendered sub/superscripts is real content", is offered as the
                motivation for the clause, not as its boundary.
    DIVERGES:   real record `Infinite_Set_Sum.infsetsum_0`, whose `expr` is
                `(∑ₐ_∈?A. ?'a0) = ?'a0`. Tokens contain `ₐ_` (a rendered ₐ
                followed by `_`, one identifier token because ₐ is `isalpha()`
                and `_` is a quasi-letter).
                  A → ['(','∑','∈','A',"'",'a0',')','=',"'",'a0']
                  B → ['(','∑','ₐ_','∈','A',"'",'a0',')','=',"'",'a0']
                Ran `tokenize`/`subtokens` on the string (tok/t7.py).
                Frequency: a full LMDB pass over 1,362,096 expressions (146 s,
                tok/scan.py) finds 11 tokens that split to nothing, contain a
                rendered separator, and contain a `_`. Because matching is
                adjacent and ordered, the extra element is not additive: it
                breaks every run that crosses that position.
    VECTORS:    I ran all 28 lines of §16.2 under four readings (A; B; "keep
                anything that splits to nothing"; "keep iff all characters are
                rendered-or-control"). The last two are killed — by `'_wrt'`,
                `'_'`, `'.'`, `'_.'`, `'%x. x'`, `'Stirling_Formula.c…'` and by
                `'\<^sub>' → []`, `'f\<^bsub>i\<^esub> = g'`,
                `'\<^bold>x \<^bold>('`. Reading B agrees with the implementation
                on **every one of the 28 lines**. §16.5's synthetic list requires
                "a token made entirely of rendered superscripts" — a case where A
                and B agree by construction. No listed vector mixes `_` with a
                rendered character inside one token.
    SEVERITY:   silently-wrong-results

---

F2. §16.4's asset list omits `SUBSUP_TRANS_TABLE`, which pipeline step 3 needs,
    and omits the 90-element rendered subset, which the fallback clause needs.

    WHERE:      §16.4 / D41 emit "the symbol table", the abbreviation table, and
                code-point sets for letters, digits, quasi-letters, "the separator
                class (all 99 characters)" and the ASCII-symbolic set.
    READING A:  the fold table is `Isabelle_RPC_Host/unicode.py:121`, a literal
                142-entry Python dict. It is NOT in `etc/symbols` and is not
                emitted. Without it a port cannot do §5.1 step 3 at all
                (`unicode_of_ascii` folds `⇩`/`⇧`/`❙` + next char). §5.5 forbids
                hard-coding a symbol table, so the port has no legal source.
    READING B:  the fallback needs to tell 90 of the emitted 99 apart. Nothing
                emitted marks which 90. A port can reconstruct them only by
                looking up `\<^sub>`, `\<^sup>`, `\<^bsub>`, `\<^esub>`,
                `\<^bsup>`, `\<^esup>`, `\<^bold>` in the symbol table and
                subtracting, plus `_` and `.` — which is nowhere stated.
    DIVERGES:   a port lacking the fold table fails §16.2's
                `'x\<^sub>i + y\<^sup>T' → ['x','+','y']`, so that form is caught.
                A port that reconstructs "rendered" as "the 99 minus `_` and `.`"
                is caught by `'\<^sub>' → []`. What is not caught is a port
                carrying a slightly different fold table — see F3.
    VECTORS:    §16.2 catches the crude failures; it cannot catch a table that
                differs only in entries no vector exercises.
    SEVERITY:   degraded-results (and it blocks the port outright as written)

---

F3. `⇩`-subscripting is lossy or lossless depending on which letter follows,
    because the fold table is incomplete — and "complete it" is a change a port
    author would plausibly make.

    WHERE:      `SUBSUP_TRANS_TABLE`, `unicode.py:121-151`. `⇩` has 32 entries
                (digits, `- + = ( )`, and only the 17 letters a e h i j k l m n o
                p r s t u v x); `⇧` has 58. `⇩b`, `⇩c`, `⇩d`, `⇩f`, `⇩g`, `⇩q`,
                `⇩w`, `⇩y`, `⇩z` and every uppercase subscript have no entry.
    READING A:  (implemented) an unfoldable subscript leaves the marker standing
                as its own token, which then vanishes, and its operand survives
                as a separate identifier.
    READING B:  a port author transcribing the table by hand — which F2 forces —
                sees `⇧a…⇧z` nearly complete and `⇩` full of holes, and completes
                it. Isabelle's own renderer displays `⇩b` as a subscript b, so the
                holes read as omissions rather than as Unicode's limits.
    DIVERGES:   ran: `'f\<^sub>a'` → `['f']` (the `a` is destroyed);
                `'f\<^sub>b'` → `['f','b']` (the `b` survives). Under a completed
                table the second becomes `['f']`.
                Real record: `NodePointer.castₙₒ⇩dₑ⇩_ₚₜᵣ₂ₒ⇩bⱼₑ⇩cₜ⇩_ₚₜᵣ_inject`
                — the entity `cast_node_ptr2object_ptr_inject` spelled with
                subscripts. Its name subtokens are
                `['NodePointer','cast','d','ₚₜᵣ₂ₒ','b','c','inject']`
                (ran). A user querying `cast_node_ptr` compiles to
                `['cast','node','ptr']` and does not match it — `node` was folded
                away, `d` survived because `⇩d` has no fold entry, and `ₚₜᵣ₂ₒ`
                survived whole through the fallback clause.
    VECTORS:    §16.2 contains no unfoldable sub/superscript — its `\<^sub>i`,
                `\<^sub>1`, `\<^sup>T`, `\<^sup>c`, `\<^sup>e` all fold. §16.5's
                prose does require "sub/superscripts that have no fold entry" as a
                synthetic case, so this is nominally covered *if* the vector file
                is generated as specified; it is the one §16.5 line standing
                between the two implementations here, and §16.2 — the list §16.3
                makes the acceptance criterion for step 1 — does not carry it.
    SEVERITY:   degraded-results

---

F4. A fallback-kept token breaks an adjacent run in 50,582 expression records;
    §3.6 records the phenomenon in one clause and never says it is intended, and
    the plan quantifies the fallback's benefit but not its cost.

    WHERE:      §3.6 line 696: "a fallback-kept token such as `ᶜᵉ` can break an
                adjacent run *through* it, which is a consequence of matching
                becoming ordered rather than of the class". §5.4 quantifies the
                benefit (108 tokens, 7,346 documents, 3.18 %) and gives no cost
                figure.
    READING A:  keep the token, accept the break (implemented).
    READING B:  an implementer reading §3.6's clause as a defect report — it is
                filed under "Two properties worth knowing", not under a decision —
                emits nothing for an interior fallback token, or emits it only at
                an array end. Nothing in §5.4 or D21 says the break is wanted.
    DIVERGES:   ran `(A ∪ B)⇧c = A⇧c ∩ B⇧c` →
                `['(','A','∪','B',')','ᶜ','=','A','∩','B']`. The condition
                `(A ∪ B) =` is not an adjacent run under A and is under B.
                Full LMDB pass (tok/scan.py): 50,582 of 1,362,096 expression
                records (3.71 %) and 153 name records contain a fallback-kept
                token strictly between two other subtokens; 113,624 fallback-kept
                token occurrences in `expr` overall. Note the denominators differ
                from §5.4's (230,944 exported documents), so these rates are
                comparable in magnitude but not like for like.
    VECTORS:    §16.2's single fallback line, `'[x]\<^sup>c\<^sup>e' →
                `['[','x',']','ᶜᵉ']`, puts the kept token at the END of the array,
                where readings A and B agree. §16.5 requires "a token made
                entirely of rendered superscripts" without saying it must be
                interior.
    SEVERITY:   silently-wrong-results (it silently costs matches) — but see the
                note: both readings are self-consistent, so the damage is a port
                divergence rather than a defect in A.

---

F5. §5.1 step 4's justification is false at the subtoken level: the separator
    class does cut a `\<…>` symbol in half.

    WHERE:      §5.1 step 4 (line 747): "A `\<foo>` with no code point stays
                **one** symbol and can therefore never be cut in half. This is
                what makes the matching genuinely symbol-level rather than
                character-level."
    READING A:  true of `symbol_explode` and of §5.2's tokens.
    READING B:  false of subtokens, which under D21 are the only level indexed.
                35 symbol names in `Isabelle2025-2/etc/symbols` contain `_`, and
                all of them are control symbols with no `code:` field, so they
                survive step 3 as literal text and become a single token under
                §5.2's "anything else" clause — and §5.4 then splits that token on
                the `_`.
    DIVERGES:   ran `tokenize(r'\<^const_name>foo')` → tokens
                `['\\<^const_name>','foo']` → subtokens
                `['\\<^const','name>','foo']`. Same for `\<^Const_fn>` →
                `['\\<^Const','fn>']`. A user pasting `\<^const_name>` into the
                condition box gets two junk subtokens that appear in no document.
                It happens on stored data too, not only on typed queries: a second
                full LMDB pass (tok/scan2.py, 1,362,343 records) finds **502
                expression records** carrying a literal `\<…>` with no code point
                whose name contains `_` — `\<big_ast>` 323 occurrences,
                `\<half_blkcirc>` 86, `\<black_circle>` 76, `\<heavy_comma>` 16,
                `\<^named_theorems>` 13, `\<half_bc2>` 6, `\<^const_name>` 5,
                `\<^type_name>` 1. Ran: `\<big_ast>` → `['\\<big','ast>']`,
                `\<half_blkcirc>` → `['\\<half','blkcirc>']`. Contrast
                `\<transforms>`, also code-point-less but with no `_`, which
                survives whole as one subtoken — so the corruption is silent and
                selective.
    VECTORS:    §16.2 has no `\<…>` without a code point; its only escape line is
                `'\<Longrightarrow>' → ['⟹']`, which has one. §16.5 requires
                "ASCII-escaped input" but does not require an escape with no code
                point, still less one whose name contains `_`.
    SEVERITY:   degraded-results (both ports agree; the spec sentence is wrong,
                and it is the stated justification for the symbol-level design)

---

F6. Sixty of the ninety separator characters are also §5.2 letters and twenty are
    §5.2 digits, so whether a sub/superscript is content depends on its left
    neighbour. Neither §5.2 nor §5.4 says the two classes overlap.

    WHERE:      §5.2's letter class (`isalpha()`) and §5.4's separator class.
    MEASURED:   of the 90 rendered separators, 60 satisfy `isalpha()`
                (ʰʲʷʸˡˢˣ ᴬ…ⱽ ᵃ…ᶻ ₐₑₒₓₕₖₗₘₙₚₛₜ ᵢᵣᵤᵥ ⱼ), 20 satisfy
                `isdigit()`/`isnumeric()` (₀–₉ ⁰–⁹), 10 are neither
                (`⁺⁻⁼⁽⁾₊₋₌₍₎`, categories Sm/Ps/Pe). None is in `etc/symbols`'
                letter/greek group, none is in the ASCII-symbolic set, none is a
                quasi-letter. So 60 characters both start an identifier token and
                split it, and 20 continue one and split it.
    CONSEQUENCE:ran `'x⇧c'` → `['x']` (the superscript is destroyed) against
                `'x ⇧c'` → `['x','ᶜ']` and `']⇧c'` → `[']','ᶜ']` (it is content).
                Also `'xᶜ'` and `'x'` index identically, so `A⇧c` (set complement)
                and `A` are indistinguishable.
                This also contradicts §5.2's "token boundaries come from the
                grouping, not from whitespace": inserting a space changes the
                subtoken array.
    VECTORS:    a port that de-overlaps the two assets (excluding the 90 from the
                letter set, which the prose invites since "letter" and "separator"
                read as disjoint roles) IS caught — it turns
                `'[x]\<^sup>c\<^sup>e'` into `['[','x',']','ᶜ','ᵉ']` against
                §16.2's `['[','x',']','ᶜᵉ']`. So this is not a port divergence;
                it is an undocumented property that D41's asset emission must
                deliberately preserve, and §16.4 does not say so.
    SEVERITY:   degraded-results

---

## Cleared areas

C1. **The separator-class derivation is well defined.** Ran: every key of
    `SUBSUP_TRANS_TABLE` has length 2 and every value has length 1 (142 entries),
    so `k[0]` is always a single character and the `k[0] in (_SUB,_SUP)` filter is
    total. All 142 values are distinct and no value is produced by more than one
    marker, so the filter is unambiguous. Per-marker: `⇩` 32, `⇧` 58 (→ 90
    rendered), `❙` 52 (all in the U+1D400 mathematical-bold block, all excluded,
    all astral). §5.4's counts are exact: 7 controls (⇩⇧⇘⇙⇗⇖❙, all category So),
    90 rendered, class size 2+7+90 = **99**, compiled pattern 103 characters.
    All 90 are BMP and all are NFC-stable (`normalize('NFC',c)==c`); so are all
    142 fold values.
    One fragility, not a defect: `subtoken_rule.py:16` writes the filter as
    `k[0] in CONTROL_SEPARATORS[:2]` — a substring test on the first two
    characters of a joined string — where §5.4's published code writes
    `k[0] in (_SUB, _SUP)`. They agree only because every symbol maps to exactly
    one character and `\<^sub>`/`\<^sup>` happen to be first in the join order.
    The published form is the safe one; the prototype, which §16.3 calls the
    thing to be lifted, is not.

C2. **A token mixing a control separator with a rendered one cannot arise.** All
    seven controls are Unicode category So — not `isalpha()`, not a digit, not a
    quasi-letter, not ASCII-symbolic — so §5.2 routes every one of them through
    "anything else: one symbol, one token". A control character is therefore
    always a **singleton** token. Ran `'⇩ᶜ'` → tokens `['⇩','ᶜ']` → `['ᶜ']`;
    `'x⇩ᶜ'` → `['x','⇩','ᶜ']` → `['x','ᶜ']`; `'\<^sub>\<^sup>c'` → `['⇩','⇧','c']`
    → `['c']`. Fed by hand, `subtokens(['⇩ᶜ'])` is `[]` — the fallback rejects it
    because `⇩ ∉ _RENDERED` — but no input produces that token. Confirmed on the
    corpus: over 1,362,096 expressions and their names, **zero** surviving
    subtokens consist only of control characters. So the "all rendered" versus
    "all rendered or control" distinction is unreachable, and every reachable
    difference from the implemented clause involves `_` (F1).

C3. **`re.escape`'s 99-character class transfers to JavaScript unchanged.** Ran
    under node v20.20.2 (tok/t5.js, tok/t8.js). The compiled pattern
    `[_\.⇩⇧⇘⇙⇗⇖❙²³¹ʰ…ⱽ]+` compiles as a `RegExp` both without flags and with `u`,
    and `String.split` reproduces Python's `re.split` on 13 probes including
    `sorted_wrt`, `Kelly_1_39`, `a.b`, `x_y`, `ᶜ_ᵉ`, `ₐ_`, `_wrt`, `x₁`, `[x]`,
    `a\b`, `a-b`, `a]b`, `a^b`. The only structural character `re.escape` inserts
    is the `\` before `.`, a legal identity escape in a JS class in both modes.
    Building the class from D41's asset with no escaping at all
    (`'[' + chars + ']+'`) gives byte-identical results, because `.` is literal
    inside a class and the class contains no `-`, `]`, `^` or `\`.
    Conditional, not a defect today: `re.escape` also escapes `&`, `~`, `#` and
    space. `new RegExp('[_\\&]+','u')` is a **SyntaxError** in JS while
    `new RegExp('[_\\&]+')` is fine (ran both). Since D41 ships the class as data,
    a port that pipes a Python-escaped class into a `u`-flagged RegExp is one
    table entry away from a hard failure, and a port that concatenates raw is one
    `-`, `]`, `^` or `\` away from a silent character range.
    Also cleared: the `+` in the class is semantically inert here (empty
    fragments are filtered either way), and code-unit versus code-point iteration
    in the fallback cannot diverge, because no rendered separator is astral — ran
    the bold fold `𝐱` (U+1D431) through both iteration styles, both reject it.
