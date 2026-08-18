# A public semantic-search site over the Isabelle semantic DB

Draft 3, 2026-08-12. This document is the design agreed in conversation on
2026-08-09 and revised on 2026-08-12; it is written to be reviewed
adversarially, and **two rounds have run**: a full review on 2026-08-13 covering
the plan up to roughly D32, and a narrow review of §5 and D41 on 2026-08-14 whose
evidence is committed under `site/review/` (§16.7). D43-D46 postdate both and have
not been reviewed. Draft 2 recorded the decisions
D13–D19, corrected the treatment of theories for theorem-alike entities (§7,
which draft 1 got wrong), and added the Fireworks latency measurements (§3.5)
that moved the region decision. Draft 3 records D21 — the collapse of the two
expression-matching mechanisms into one (§5.4, §6.1, §6.3) — withdraws the
open question Q5 and the false statement that produced it, and updates the
implementation status below.

Draft 3 also corrects **three factual errors** found on 2026-08-12, changing no
decision — D1–D21 stand unaltered. Each correction is marked *Draft 3
correction* where it applies. In short: the theory-hash registry was reported as
9.9 % complete and in need of an Isabelle enumeration run (§3.2, §7.3), when in
fact `cslh19`'s copy already resolves 100 % of the persistent hashes that ship —
the earlier figure was measured on the wrong machine; §12.2's step 2 changes
accordingly from *build* to *publish*; and D19's stated premise, that the three
copies of the database were in sync, was false.

**Implementation status.** The U+007F repair (D12, §10) is **done**: measured
on 2026-08-12, zero of the 1,362,343 entity records still contain U+007F, on
both machines and in the published snapshot. `ENTITY_POSITION_PLAN.md` is
**done** and 1,092,855 records (80.2 %) carry an entity position — but that
backfill finished *after* the Hugging Face snapshot was packaged, so those
positions exist only on `cslh19`; this machine holds 8,306. **Prerequisite A of §12.2 —
the key repair, D33 — is also done, 2026-08-18.** `site/COPY.md` and
`site/design/IsaSearch.dc.html` exist and are authoritative for the interface copy;
`site/prototype/` holds the measured tokenizer prototype, which is **pre-D43** and
whose blast radius is stated in §16.1; and `site/review/` holds the evidence of the
§5 review that §16.7 required. Everything else in §12.2 is
unstarted: no tokenizer module, no site export, no Worker, no served site.

Orientation for a reader arriving with no other context: §2 is the settled
decisions (do not reopen), §3 is the measured evidence every decision rests on,
§13 is the open questions, §14 is what was considered and rejected. Citations
name **functions and files, not line numbers** — this is a shared working tree
and line numbers move (the convention `VECTOR_INVALIDATION_PLAN.md` and
`ENTITY_POSITION_PLAN.md` both adopted).

**Where the numbers were measured.** Every corpus figure in this document was taken
on **this** machine's copy of the database unless it says otherwise, and this
machine is not the authority — `cslh19` is (D19), and it publishes to Hugging Face.
The figures re-measured on 2026-08-19 are stamped with that date; the earlier ones,
stamped 2026-08-09 or 2026-08-12, predate the D33 key repair and the entity-position
backfill and are kept only where the older reading is itself the point. A figure
about a *document frequency* always names the population it was counted over —
either the whole corpus or §3.3's 230,944-document test namespace — because those
two denominators differ by six times and an unlabelled percentage from the second
has been mistaken for the first three times already.

**Relationship to `ENTITY_POSITION_PLAN.md`**: that plan (approved, being
implemented as of 2026-08-09 19:21 — `position` is already the 13th record
field) adds an **entity position** to every record and backfills the ~1.35 M
existing records. This plan **consumes it and requires no change to it**. Draft
1 proposed folding a declaring theory for theorem-alike entities into its
backfill; D13 withdraws that — the concept does not apply to them (§7.1). The
only thing this plan needs from it is the source link on entity pages (§9.4).

## 0. Summary

Publish a web site — **`isasearch`** (D30) — that lets anyone search
Isabelle/HOL and AFP entities over the ~1.35 M entities already in the semantic
DB. A search is always a **semantic query**: natural language, ranked by cosine
similarity of Qwen3-Embedding-8B vectors, fused with BM25 over the English
interpretation by reciprocal rank fusion (D29). A required query, never a bare
filter (D7).

It may be narrowed by **syntactic conditions**, every one of them
`contains` / `excludes` matched as an adjacent ordered run of **Isabelle
subtokens** (D21, §5.4), in five filter panels (D22):

1. **Entity Name** — the entity's own name;
2. **Expression** — the printed entity expression;
3. **Theory Name** — the associated theories. What that means differs by kind
   and is stated in the interface (D14, D15, §7.2, §9.2b);
4. **All** — any of the three above, compiled to an `Or` (§6.3);
5. **Kind** — a chip group, everything selected by default (D29).

Serving is fully serverless: Cloudflare Pages + Worker for the front end,
turbopuffer for vectors *and* filtering, Fireworks for the query embedding. No
server to operate. A **site export** derives the published index from the semantic
DB; it runs whenever the data or the tokenizer asset changes, and §8 requires it to
be re-runnable and deterministic.

## 1. Glossary — canonical names, never paraphrased

| Term | Meaning |
|---|---|
| **entity** | One record in `semantics.lmdb`: a constant, type, class, locale, method, theorem collection, theorem, or derived rule. Never "item", "object", "fact". |
| **entity expression** | The `expr` field of the record. For theorem-alike kinds it is the proposition; for constants it is the type; for the five source-text kinds (`TYPE`, `CLASS`, `LOCALE`, `METHOD`, `THEOREM_COLLECTION`) it is the declaration's source text. |
| **declaring theory** | The theory whose source declares the entity, named by its **session-qualified long name** (e.g. `HOL-Library.Sorted_Sort`). **Applies only to name-addressed entities.** Theorem-alike entities are content-addressed and have no declaring theory in this data model (§7). Never "owning theory", "home theory". |
| **constituent theories** | The `theory_constituents` field: the theories of the **constants occurring in the entity expression**, as `(long name, 16-byte hash)` pairs. Present on every theorem-alike and experience record. **Not** a declaring theory. |
| **the associated theories** | The set of theories a *site document* is filtered by (D14): its declaring theory when name-addressed, its constituent theories when theorem-alike. **This exact phrase, always** — never "related theories", "relevant theories", "theory domains", or any other paraphrase. The word "domain" is specifically excluded: `dom`, `Dom` and `domain` name unrelated Isabelle concepts (the domain of a map or relation, and HOLCF's `domain` command) in about 27,500 entities of this very corpus, and "domain" also reads as "subject area", a plausible but wrong meaning. |
| **theorem-alike entity** | A record of kind `Theorem`, `Introduction rule`, `Elimination rule`, `Induction rule` or `Case split rule`. Such a record is **content-addressed**: its key is the statement's digest under an XOR pseudo-theory prefix, so it has no declaring theory (D13, §7.1). 1,156,153 of 1,362,343 records, 84.9 %. Never "theorem-like", "a fact", "a lemma record". |
| **name-addressed entity** | A record of kind `Constant`, `Type`, `Class`, `Locale`, `Theorem collection` or `Proof method`. Its universal key carries its declaring theory's 16-byte hash as the prefix, so the declaring theory is recoverable from the key alone once §7.3's table is available. 206,010 records, 15.1 %. The two categories partition the corpus apart from the 180 `EXPERIENCE` records, which are never published. |
| **universal key** | A record's key in `semantics.lmdb`, constructed by `Isabelle_RPC_Host.universal_key`: a 16-byte theory-or-XOR prefix, one kind byte, and the addressing tail that kind uses. Never "record key", "entity id". The turbopuffer document id is a 128-bit hash **of** the universal key, not the key itself (§6.2). |
| **the tokenizer** | The single normalisation described in §5, applied identically to stored text and to user queries. Never "the analyser", "the lexer", "the splitter". Its reference implementation of symbol conversion is `Isabelle_RPC_Host.pretty_unicode`; this document names that function and never `unicode_of_ascii`, which is a one-line alias of it in the same module. |
| **token** | One output element of the tokenizer. |
| **subtoken** | One output element of the second-level split described in §5.4. Under D21 this is the only level that is indexed or queried. |
| **interpretation** | The `interpretation` field of the record: the English text a language model wrote from the formal statement. **This word, always**, for the field and for what a card shows — never "explanation", "description" or "summary" in this document. (`site/COPY.md` may and does choose a different word for visitors, who do not read this plan; that is its call, not a second name for the field.) |
| **the machine-generated disclosure** | The one locked sentence pair that must appear wherever an interpretation is shown, fixed by D30 as amended and D40 and reproduced verbatim in `site/COPY.md` §4.2. **This exact phrase for it** — never "the disclaimer", "the disclosure sentence" or "the notice". |
| **site export** | The batch job (§8) that turns the semantic DB into the turbopuffer namespace and its attributes. Never "publish", "sync", "ingest". |
| **site document** | One turbopuffer document, one per exported *record* (D5, reversed 2026-08-13). Records sharing a `(name, entity expression)` are collapsed into one card in the response, not in the index. |
| **entity page** | The server-rendered permanent page for one site document (§9.4). |

**The unit of counting is the record**, and it is worth stating because four words
have been used for it. There are **1,362,343** entity records; each exported one
becomes exactly one **site document** (D5 as reversed); **1,362,096** of them carry
an entity expression and **1,362,343** carry a name, so a figure about expressions
has a different denominator from a figure about names; and **1,362,163** are
exportable before D24's scope test, the difference being the 180 `EXPERIENCE`
records. "Entity", "document" and "expression" are not interchangeable units in this
document, and a count that does not say which one it means is a defect.

## 2. LOCKED decisions

D1–D20 were taken by the user on 2026-08-09, D21 on 2026-08-12, D22–D31 on
2026-08-12/13, D32–D42 on 2026-08-13/14, and D43–D46 on 2026-08-17/18. Do not
re-litigate; ask before deviating.

**The list is not in one order, and that is deliberate.** It opens with D1–D20 in
ascending order, as they were first written, and then continues from **D46
downwards** to D21, so that the newest decision is the first one a reader meets
after the original twenty. Two of the early entries are struck through in place
rather than deleted — D20, superseded by D32, and D28, cancelled the same day it
was taken — because §9 and §12.2 were written under D20 and §11.1b under D28, and a
reader of those sections needs to find the decision that used to govern them.

- **D1** — **turbopuffer** hosts both the vectors and the syntactic filtering.
  Cloudflare Vectorize was rejected: it supports no substring matching and no
  vector-ID allow-list (§14.1).
- **D2** — **no first-order pattern matching.** Dropped from scope. Its removal
  is what makes the site serverless: matching a user-written pattern would
  require Isabelle's parser at query time (§14.2).
- **D3** — **no reranker.** Retrieval is the bi-encoder alone. The cross-encoder
  `qwen3-reranker-8b` path stays off; `_get_reranker` returning `None` already
  degrades `lookup` to pure kNN, so no code change is needed.
- **D4** — **the query loses `?`.** The tokenizer discards `?` on both sides, so
  the stored `sorted_wrt R ?xs` and the user's `sorted_wrt R xs` match.
  Consequence: schematic and free variables become indistinguishable to search.
- **D5** (2026-08-09, **reversed 2026-08-13**) — **there is no merge.** One site
  document per *record*, carrying that record's own universal key, vector,
  interpretation and single `kind`. Cross-kind duplicates — the same `(name,
  entity expression)` recorded once as a `Theorem` and again as an
  `Introduction rule` — are collapsed **in the response, after ranking**, into
  one card whose kinds are the union and whose interpretation is **the
  highest-scoring member's**. The original decision merged at export time; it
  was reversed because nothing could say which member supplied the id, the
  vector or the interpretation, and all three genuinely differ (the kind is
  inside the embedded text via `pretty_print`). Collapsing after ranking makes
  that choice non-arbitrary: the ranking picks the representative.
  Consequences, all accepted: the namespace grows ~9.7 % (1,362,343 records
  against 1,241,679 merged documents), which at D31's f16 is **11.16 GB of vectors
  against 10.17 GB**, a difference of about one gigabyte and invisible beside a
  full-length query's embedding cost (§11.1b recomputes the whole cost model on the
  1,362,343; the ~11.9 / ~10.83 GB this sentence used to give were the same
  calculation with a namespace overhead folded in and did not match §11.1b's own
  arithmetic); a
  200-row fetch collapses to ~182 distinct entities on average, so D29's "200
  results" reads as **at most** 200 entities and there is no over-fetch; and the
  `kind` filter becomes an unambiguous single-valued test instead of the
  any-of/all-of question a multi-valued `kinds` would have raised (§13, F18).

- **D6** — **mid-identifier substrings are not searchable.** Searching `orted`
  will not find `sorted_wrt`. Queries that break at `_` or `.` boundaries are
  served by the subtoken field (§5.4).
- **D7** — **no filter-only browsing.** A semantic query is required; an empty
  query is rejected rather than falling back to some other ordering.
- **D8** — **runs of ASCII symbolic characters merge into one token**
  (Isabelle's `sym_ident` rule): `::` is one token, not two colons.
- **D9** — **entity pages exist**, server-rendered, **one per `group`** — that is,
  one per distinct `(name, entity expression)` pair, which is exactly what a result
  card collapses to (D5 as reversed, §6.1) — for search-engine discoverability
  (§9.4). This decision said "one per site document" until 2026-08-19, which was
  written under the original D5 where the two coincided; under the reversal a site
  document is one per *record* and several records can share a `group`.
- **D10** — **displayed fields are the entity name and the entity expression.**
  The interpretation is present but collapsed by default.
- **D11** — **`Token.source_of` in `pide_state.ML` is a defect and will be
  fixed** to `Token.unparse` (§10.1). It is our own file, not part of the
  Isabelle distribution.

  **Not done as of 2026-08-19.** `Tools/pide_state.ML` still calls
  `Token.source_of`, and the comment above the call still asserts that `source_of`
  returns each token's original text — the assertion the companion's §10.1 disproves
  by measurement. §10's "done" is a statement about the **data**: D12 repaired the
  238 affected records one at a time, and zero records carry U+007F today. The
  **cause** is untouched, so a fresh collection run over a theory containing a
  delimited token can reintroduce the character through the fallback path. That is
  why §5.1's pipeline step 2 stays in the tokenizer rather than being deleted as a
  no-op.
- **D12** — **the 238 records containing U+007F are repaired surgically**, by
  reading the true text back out of the theory source, and the repaired DB is
  re-uploaded to Hugging Face (§10.2).
- **D13** — **theorem-alike entities have no declaring theory** and none is to be
  invented for them. They are content-addressed; their key prefix is an XOR
  pseudo-theory and availability is governed by their constituent theories. An
  earlier draft of this plan treated the absence as a 14.7 % data gap to be
  filled; that framing was wrong and is withdrawn (§7).
- **D14** — **the theory filter matches constituent theories for theorem-alike
  entities**, and the declaring theory for name-addressed ones. The two
  alternatives were measured and rejected: letting theorems pass unfiltered
  leaves the candidate set at 84.9–85.0 % whatever is filtered, i.e. the filter
  silently stops working; excluding theorems when the filter is active hides the
  85 % of the corpus users mostly want (§7.2).
- **D15** — **the difference in meaning is stated plainly in the interface**, not
  hidden and not smoothed over with an option. No mode selector.
- **D16** — **the site lives in this repository**: the site export as a module of
  the Python package, the web application under `site/` (§12.1).
- **D17** — **the domain is `isabelle-semantics.qiyuan.me`.**
- **D18** — **the turbopuffer namespace goes in North America**, co-located with
  the Fireworks origin so that Cloudflare Smart Placement can put the Worker
  near both (§6.4).
- **D19** — **the U+007F repair runs on this machine and Hugging Face is
  uploaded from here.** Premise given by the user: this machine, `cslh19` and
  Hugging Face are currently in sync.

  **Draft 3 correction — the premise was false and the work took another
  route.** The three were not in sync: this machine and the published snapshot
  differed by roughly 1.24 M vectors. What actually happened on 2026-08-11/12 is
  that this machine published first, `cslh19` pulled and merged (a merge that
  needed a new tool, `merge_snapshot.py`, because `cslh19` held vectors the
  snapshot lacked and a plain extraction would have destroyed them), and the
  snapshot was then republished **from `cslh19`**. The repair itself did run
  here, and it is done. `cslh19` is now the authority: it publishes to Hugging
  Face, and every other machine syncs from there.
- **D20** — ~~the web application is deferred~~ — **superseded by D32 on
  2026-08-13.** Kept for the record because §9 and §12.2 were written under it.
  Original text: Work proceeds on the data side
  only: the repair (§10), the theory-hash registry (§7.3), the tokenizer (§5), the
  site export (§8), the turbopuffer namespace (§6), and the Worker's search API
  (§11.1's rate limiting included). §9 stays in this document as the agreed
  design but is **not** to be built yet, and the questions it raises need no
  answer to unblock anything.
- **D46** (2026-08-18) — **the tokenizer asset carries the export machine's whole
  symbol table, component files included.** On this machine that means
  `contrib/phi-system/symbols` and `contrib/phi-system/symbols-words` on top of the
  distribution's own `etc/symbols`: measured 2026-08-19, the distribution file defines
  **439** symbols with a code point and the two phi-System files add **185** more, for
  a loaded table of **624**. Not one of the 185 is used by a published entity, since
  D24 excludes every phi-System entity from the corpus (135 of them are the private-use
  word glyphs of D44, and the other 50 are ordinary symbols). They ship anyway: a visitor who pastes `\<big_ast>` out of a phi-System buffer then gets
  `✱` rather than a condition split into three parts, and the alternative — filtering the
  asset to symbols the corpus uses — makes the asset depend on the corpus as well as on
  the installation, for no gain a visitor can see. What was **not** acceptable was
  leaving this to chance: before this decision the asset's contents depended on which
  components happened to be registered on whichever machine ran the export, which is an
  accident, not a policy. The operational consequence follows from D45 and is stated here
  because it is surprising: **registering or unregistering an unrelated Isabelle component
  changes the asset digest, and therefore the namespace name, even though not one
  published document changes.** An export that finds a different component set than the
  declared one must fail rather than quietly build a differently-named namespace. **The declared
  set is the `ISABELLE_SYMBOLS` file list recorded inside the committed asset from
  the previous export** — §8.2 states the comparison and what the first export does
  instead, since it has nothing to compare against. This decision mandated the
  failure and did not say where the declaration lives; that gap is closed there, not
  here.
- **D45** (2026-08-18) — **the tokenizer's data ships as one stamped asset, and
  the namespace name carries its digest.** Step 3 needs the symbol table and the
  fold table; §5.2 needs the letter, digit, quasi-letter and ASCII-symbolic sets;
  §5.4 needs the separator class; the condition box needs the abbreviations. All
  of it is emitted once at export time and read by both implementations, which may
  carry none of it themselves (§5.5). The asset also records **where it came
  from** — the `ISABELLE_SYMBOLS` file list, and the Unicode version of the
  character classes — because the file list depends on which components are
  registered, so identical code loads different tables on two machines, and the
  classes depend on the Python release (`isalpha()` is 136,104 code points under
  Unicode 15.0 and node's `\p{L}` is 145,672). Rather than check the asset against
  the index at run time, **the turbopuffer namespace name embeds the asset's
  digest**: a Worker holding an older asset addresses the namespace that asset
  built, so "new index, old asset" is not a state that can be constructed. The
  alternative considered and rejected was moving step 3 out of the tokenizer
  altogether — the interface would rewrite `\<Longrightarrow>` while typing, as it
  already rewrites `==>` (§9.3), and the export would normalise the stored text.
  It was rejected because the symbol table is needed either way and that plan only
  moves it to the browser, where the conversion becomes a second implementation
  with no gate over it, whereas inside the tokenizer it is covered by the
  test-vector gate that must exist regardless.
- **D44** (2026-08-17) — **a private-use code point is not substituted.** Step 3
  leaves such a symbol as its literal `\<name>`. A private-use code point means
  only what the font declaring it draws — phi-System draws 135 keywords that way
  from U+E000 to U+E086, and no other symbol in the distribution or in that
  component uses the range — so substituting it would put a character in the index
  that renders as a blank box outside jEdit and that no visitor can type, while
  the escape at least spells the word. `Isabelle_RPC_Host.pretty_unicode`
  implements this; its reverse direction still names a raw private-use character,
  because text dragged out of jEdit carries one and naming it is a repair. Both
  directions settle: `ascii_of_unicode` then `pretty_unicode` is a fixed point.
- **D43** (2026-08-18) — **the tokenizer is defined over characters, not Isabelle
  symbols.** The `symbol_explode` step is dropped, and with it the claim that a
  `\<foo>` "can never be cut in half" — false of the subtoken level, the only one
  indexed, since §5.4 splits at `_` regardless of symbol boundaries. Measured, and re-measured
  independently on 2026-08-19 with the same result: the change moves 0.23 % of
  subtoken arrays (3,135 of 1,362,096 expressions), all of them escapes left literal
  by step 3. **3,118 of the 3,135 are pure refinements** — `\<^named_theorems>` stops
  indexing as the unsearchable `['\<^named','theorems>']` — and the remaining **17
  lose one subtoken of bare punctuation**, of which **three are AFP entries that D24
  exports**: see §5.1 for the pattern and the three names.
  Two review findings dissolve with the step: that §5.1's justification was false,
  and that the treatment of a malformed or unterminated `\<` was unspecified —
  `\<=` is now simply one symbolic run. §5.3's eleven equivalences and §16.2's
  thirty-two cases were re-run under the new definition and all still hold, and were
  re-run again on 2026-08-19 with zero mismatches, so no line of either table is
  stale. **The prototype in `site/prototype/` still implements the old, pre-D43
  rule**, and the difference between the two is exactly these 3,135 records and
  nothing else — see §16.1 for what that means for anything the prototype measured.
- **D42** (2026-08-14) — **every result card carries a source link**, not just
  the entity page (§9.4). It resolves through the entity position, whose coverage
  is **80.2 %**, so roughly one card in five has no link and needs a defined
  absent form — the link is not to be rendered dead or blank without a word.
  Visible only once prerequisite C lands (§12.2).
- **D41** (2026-08-14, extended by D45) — **the tokenizer's character classes ship as data, and
  the test vectors must contain synthetic input.** §5.2 defined its classes by
  naming Python's `isalpha`, `isdigit`, `isnumeric` and `isspace`, which have no
  JavaScript equivalent, so §5.5's required port could not be written from this
  document without hard-coding exactly what §5.5 forbids. Measured divergences
  that follow from the obvious substitutes: `²` (U+00B2 — this said "640
  occurrences in the corpus", which is the count over §3.3's 230,944-document test
  namespace; over the whole corpus it is **3,955**) satisfies `isdigit()` but is
  category `No`, so `\p{Nd}` disagrees; **`\p{L}` is not `isalpha()` either** —
  136,104 code points against node's 145,672, a 9,568 gap that is pure Unicode
  version drift (15.0 against 17.0) and exists across Python releases too, which is
  why D45's asset records the version it was built under;
  U+001C-U+001F and U+0085 satisfy `isspace()` but lie outside `\s`; U+FEFF is
  the reverse. So the export emits the letter, digit, quasi-letter, separator and
  ASCII-symbolic code-point sets into **the asset** alongside the symbol table, and
  neither implementation may consult a language built-in. (D45 later fixed that this
  is **one file**, and this document says "the asset", singular, everywhere: the
  digest that names the turbopuffer namespace is the digest of one file, so a plural
  would leave it undefined which one is meant.) Separately, §5.5's 10,000 test
  triples are all sampled from real entity expressions, on which pipeline steps 1
  and 3 are provably the identity (§3.4: the store is 100 % NFC and
  `unicode_of_ascii` is identity on it) — so a port that omits NFC normalisation
  and ASCII-escape conversion passes the gate byte for byte and then returns
  nothing for `\<Longrightarrow>`, one of the two input routes §9.3 promises.
  The file must therefore also carry synthetic cases: ASCII-escaped input, NFD
  input, unfoldable subscripts, separator-only conditions, and the `²` / U+FEFF
  boundary characters. Its encoding, ordering, count and digest are pinned so
  that "both implementations passed" is itself checkable.
- **D40** (2026-08-14) — **the result card shows a cosine similarity, and says
  whose.** Hover copy: *"Cosine similarity between your query and this entity,
  computed with Qwen3-Embedding-8B. The result order also accounts for keyword
  matching, so a lower score can appear higher up."* Naming the model settles an
  open point: the number displayed is the **vector leg's cosine similarity**,
  not the RRF fusion score, which is a function of rank (`1/(k+rank)` summed)
  and means nothing to a reader. The consequence is that the displayed numbers
  are not monotone down the page, since D36 orders by the fused score — hence
  the third sentence. The expanded explanation's disclaimer gains one clause,
  that the explanation also feeds retrieval, so a poor one can cost an entity
  its place in the results. No "AI" label on the collapsed row: twenty of them
  on a page is noise.
- **D39** (2026-08-14) — **`name_subtokens` indexes the long name only**, and
  the interface speaks in long names. Measured: subtoken splitting decomposes
  `Path_Connected.path_image_join` into
  `['Path','Connected','path','image','join']`, so the short name is an adjacent
  run inside it and `path_image_join`, `image_join` and the full long name all
  match. Indexing both forms was considered and is unnecessary. Accepted
  consequence: a condition like `List` in `Entity Name` matches everything whose
  long name begins with that theory, so `Entity Name` and `Theory Name` overlap.

  **Example corrected, 2026-08-14.** This decision was first written with
  `HOL-Analysis.Path_Connected.path_image_join` as the worked example, which is
  not a name that exists. An Isabelle fact's long name is qualified by the
  **theory base name**, not by the session — that is simply how Isabelle names
  facts — and the store agrees: no entity name in the 1,362,343 records carries a
  session prefix. (The 1,266 names with a hyphen in their first segment are
  theories whose own base name contains one, such as `Nominal-HOLCF.Def_eqvt` and
  `HOLCF-Utils.fun_upd_cont`.) The export therefore indexes the stored name
  unchanged and adds nothing. Nothing else in D39 changes.

  Worth noting for the interface, since the two fields differ: `theory_subtokens`
  **is** session-qualified — 8,329 distinct theory long names, of which only
  `Pure`, `FOL`, `IFOL` and `ZF` carry no session. So the same theory is written
  `Path_Connected` inside an entity name and `HOL-Analysis.Path_Connected` in the
  theory field, and `site/COPY.md` §3.1 tells the visitor so.
- **D38** (2026-08-14) — **selected Kind chips are OR-ed**: ticking several
  means "any of these kinds". Text conditions are AND-ed (§6.3), so the two
  controls combine differently and the interface has to say so. Under the
  reversed D5 each record carries exactly one `kind`, so the chips are a
  straightforward membership test; `Introduction rule` and `Theorem` are
  disjoint record kinds rather than one containing the other, which is a
  labelling matter for a tooltip and not a functional one — D29's default of
  everything selected means most users never meet it. The export additionally
  stores, on every record, the full set of kinds its `(name, entity expression)`
  group appears under, so a card's kind badges are complete and do not vary with
  which group members reached the result set; it is aggregated during the §8.1
  grouping step at effectively no cost.
- **D37** (2026-08-14) — **variable names stay in the index; the noise is
  accepted.** D4 discards `?`, which demotes a schematic variable to an ordinary
  name, so `P`, `Q`, `x`, `f` are indexed exactly like constant names. The cost
  is measured and real: over §3.3's 230,944-document test namespace, `x` is a
  subtoken of 22.95 % of documents, `a` 17.50 %, `P` 10.80 % and `f` 10.49 %. That
  denominator was not stated here before, and it matters: over the whole corpus the
  same quantities move — `P` up to about 12.8 % and `a` down to about 16.6 % — so a
  user filtering on `f` matches roughly a tenth of the corpus either way, nearly all
  of it accidental, which is the point and is robust to which population is counted. Excluding variable positions was
  considered and not taken — the records store printed text, not term structure,
  and a free variable is indistinguishable from a constant in that text, so
  excluding them would mean changing what the collection side records, not the
  export. Reinstating `?` was also rejected: it would reverse D4, whose reason
  (users do not type the question mark) still holds, and it would not help with
  free variables anyway. **Consequence, discharged 2026-08-14:** §13b's empty-state page was premised on
  `?P ⟹ ?Q` matching nothing, which is false — it matches 60 records. The page was
  rebuilt on `?n + ?m = ?m + ?n`, measured 0, paired with `?a + ?b = ?b + ?a`,
  measured 15, so that the reason for the miss is visible. `site/COPY.md` §5.1 carries
  the result and is authoritative; nothing is outstanding here.
- **D36** (2026-08-14) — **hybrid retrieval is one `multi_query`, RRF-fused by
  turbopuffer, with the filter tree attached to both legs**, 200 rows per leg
  truncated to 200 after fusion, RRF constant 60 (§6.6). Attaching the filter to
  both legs is a correctness requirement: otherwise BM25-side documents bypass
  every syntactic condition, including D22's "appears in none of the three".
- **D35** (2026-08-14) — **rate limiting is two built layers plus one
  specified-but-unbuilt**, detailed in §11.1: a free Cloudflare edge rule at 5
  requests per IP per 10 seconds, a Workers KV counter at 1,000 per IP per UTC
  day, and a Durable Object global token bucket at 10,000/hour that is **not**
  built yet. Every trip returns 429; there is no BM25 degradation path. The
  Cloudflare zone stays on the Free plan and the only recurring cost is Workers
  Paid at $5/month. Layer 1 is load-bearing for layer 2, not redundant with it
  (KV allows one write per second per key).
- **D34** (2026-08-13) — **the `f⇩C` / `f C` subtoken collision is accepted, not
  fixed.** A subscripted identifier whose subscript character has no fold entry
  tokenizes to `['f','⇩','C']` and therefore yields the subtokens `['f','C']`,
  identical to the function application `f C`; where a fold entry does exist the
  opposite happens and `f⇩i` collapses to `['f']`, losing the subscript. Both
  measured. The consequence is real — an `excludes f C` condition silently drops
  documents mentioning the constant `f⇩C` — and the user has judged it
  acceptable rather than narrow D21's rule again. **Do not re-raise this**; it is
  a known, deliberate limitation of the single-mechanism design.
- **D33** (2026-08-13) — **`BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md` is a
  prerequisite of everything in phase one that touches the store**, which is §12.2's
  steps 4 and 5. It is **not** a prerequisite of step 3, the tokenizer freeze, which
  touches no keys: §12.2 says so and this decision used to say "the whole of phase
  one", which contradicted it. Its defect — a process-global
  first-writer-wins memo on theory short names — leaves 234,398 records holding
  keys the current process cannot reproduce and mis-targets anything that
  selects records by theory, which is precisely what the theory filter does
  (D14, D23), and it passes the XOR self-check silently. Its repair rebuilds the
  store under corrected keys, so any export run before it would publish wrong
  theory data under document ids that the rebuild then changes — taking every
  permanent entity-page URL D25 ships with it. §7.2's "already in the DB, 100 %"
  cell was wrong until that plan ran; it is now correct.

  **Done, 2026-08-18.** The store on `cslh19` has been migrated: a persistent theory's
  hash is now `clear_lsb(xxh128(long_name ++ 0x00 ++ file bytes ++ parent hashes))`, with
  parents contributing their own new hashes so the long name — which is session-qualified
  — propagates down the ancestor DAG. Verified on the authoritative store, read-only:
  `fsck` passes every invariant over 1,343,793 records, **including "XOR key prefix
  disagrees with constituents: 0"**, which is the self-check the original defect used to
  pass silently and which only became meaningful once two theories sharing a base name
  stopped sharing an identity. `orphans` reports **84 records (0.006 %)** owned by a
  theory hash no local name claims, against the defect's original signature of 234,398.
  Not re-verified: G1 of `THEORY_HASH_REKEY_PLAN.md` — that every stored hash is
  reproducible from the `.thy` file by today's algorithm — because it needs the
  dependency table dumped from an Isabelle image, and that file is no longer on disk.
  **To regenerate it**: on `cslh19`, feed the SML snippet of `THEORY_HASH_REKEY_PLAN.md`
  §9.1 to `isabelle console -l AFP-ALL-4 -n` on stdin (`-n` suppresses any build; the
  image takes about four minutes to load), strip the `Poly/ML>` prompts, and keep the
  `DEP`-prefixed rows as `deps.tsv` — 10,598 of them, `Pure` included by the parent
  closure. Then build the tables per §9.2 of that plan and run G1. It is a read-only
  check and needs no rebuild.
- **D32** (2026-08-13) — **D20 is lifted, and the work is staged: the whole
  data side first, the web application after.** The phase boundary is §12.2's
  step 5/6 line. Phase one is the tokenizer module, the site export, the
  production namespace, and the Worker's search API with its rate limiting —
  everything that can be verified without a page to look at. Phase two is the
  interface of §9, whose design is now settled to D22/D26/D29/D30 and whose
  mockup exists at `site/design/IsaSearch.dc.html`. Nothing in phase two starts
  before phase one's export has produced a namespace that answers queries
  correctly.
- **D31** (2026-08-13) — **the published vector is f16, 4096 dimensions.**
  Not a reduction in dimension: only in dtype. turbopuffer counts f16 at 2
  bytes per dimension for storage and queries, halving the namespace from
  ~23 GB to ~11.5 GB and the per-query charge from $0.000023 to $0.0000115 on
  1,362,343 documents (§11.1b — these read ~21 GB and $0.000021 while that
  subsection was still computed on the merged count D5's reversal replaced). Dimension reduction, which would have cut a further 5×, is **not**
  taken — it discards information, its recall cost is unmeasured, and D3 leaves
  no reranker to absorb the loss. f16 is the option that costs nothing to
  reason about: the local store already holds Q1.15 int16, and for the
  component magnitudes of a unit-norm 4096-dimension vector (~0.016) f16's
  exponent makes it *finer* than Q1.15, not coarser. **That last point is
  analysis, not measurement** — converting the real stored vectors and
  measuring the ranking change would settle it, and should be done before the
  export publishes. Note writes are unaffected: turbopuffer bills f16 at 4
  bytes per dimension for writes because it does not linearly reduce indexing
  cost, so the one-off load still costs ~$42, or ~$21 batched. This settles Q14.
- **D30** (2026-08-13) — **the site is `isasearch`, its interface is English,
  and the machine-generated disclosure is the sentence the design already
  carries**: "Written by a language model from the formal statement, not by the
  theory's authors. It may be imprecise or wrong; the statement above is
  authoritative." All three come from `site/design/IsaSearch.dc.html` rather
  than being invented here. This settles Q7.

  **Amended by the user on 2026-08-14 — the second sentence changes.** The
  disclosure now reads: *"Written by a language model from the formal statement,
  not by the theory's authors. It may be imprecise or wrong. Where the
  explanation and the statement disagree, the statement is the correct one."*
  (D40's third sentence follows it; see `site/COPY.md` §4.2, "The expanded
  explanation", for the whole string.) Reason: two consecutive rounds of reader testing named
  **`authoritative`** the worst word on the site. Its everyday sense is *sounds
  expert*, so the original sentence can be read as praise for the explanation
  rather than as ranking the formal statement above it — the reverse of its
  purpose, in the single sentence that guards against trusting machine-written
  prose about a formal statement. The first sentence and the site name are
  unchanged, and the amendment does not reopen anything else in D30.
- **D29** (2026-08-13) — three of Q11's choices, settled:
  - **Hybrid retrieval is on by default, fused with RRF** (reciprocal rank
    fusion). No weight to tune, and it covers the exact-name intent a
    bi-encoder handles poorly (§6.5). Whether turbopuffer bills a `multi_query`
    once or once per sub-query is unmeasured and is **not** a design input —
    even at double it is ~$2/day at 100,000 searches.
  - **The kind filter defaults to everything selected.** Defaulting to theorems
    only would leave someone hunting a constant with no results and no visible
    reason, which is this site's worst failure mode; theorems are 84.9 % of the
    corpus and dominate the ranking anyway.
  - **A search fetches 200 results in one request** and pages in the browser at
    20 a screen; turning a page issues no new request. **200 is the end of the
    result list — there is no "load more" and no second request.** This follows
    from turbopuffer charging the whole
    namespace per *request*: 200 results in one request costs $0.000031, the
    same 200 fetched twenty at a time costs $0.00021 — **minimise requests, not
    results**, which is the opposite of the usual instinct. Against a
    full-length query the returned-data term is 4 % of a search, so the real
    ceiling is response payload: 200 results is ~200 KB, fine; 1,000 would be
    ~1 MB paid on every search including the ones answered by result three.
    Nobody reads to result 200 of a ranked semantic search, and D7 guarantees
    there is always a ranking, so a bounded list is honest rather than limiting.
  - **A dataset download link is offered.** It points at the existing Hugging
    Face dataset and conda channel — the database is already published there,
    so this is a link and not a second copy to maintain. The user weighed this
    against the fact that it lets someone build a competing site from the same
    data and chose the citation.
  - **The five test namespaces stay** (§3.6, ~168 MB, ~$0.06/month, absorbed by
    the $16 floor). The user left the call to the author; three of them are the
    evidence D21 and D22 rest on and will be wanted for regression once the
    export is real. Revisit after the first production namespace is verified.
  - **The query is capped at 8,000 characters, and each filter condition at
    512 characters** (revised 2026-08-14; originally "2,048 tokens"). Two
    reasons. **`token` already means something else here** — §1's glossary fixes
    it as an output element of the tokenizer, while the cap meant the embedding
    model's BPE tokens, so one word carried two meanings in one document. And
    **a Worker cannot count BPE tokens**: that needs the model's ~151,000-entry
    vocabulary shipped to the edge, so the one component on the query path could
    not enforce the cap in the unit it was written in. Characters are exact and
    free to count there. The per-condition cap is new — draft 3 bounded the
    natural-language query and bounded a filter condition nowhere, though the
    Worker runs the tokenizer over those too. With no spend cap (D28) these
    bounds exist to stay inside Fireworks' own input limit, to stop an unbounded
    request body being an attack surface, and to bound the tokenizer's work;
    they are not a cost control. 8,000 characters is roughly what 2,048 tokens
    meant. The original argument against a character cap — `⟹` is one character
    and its ASCII escape eighteen, so a character cap is harsher on users who
    cannot type Unicode mathematics — still stands, and is why the limit is
    generous rather than tight.
- **D28** (2026-08-13, **cancelled the same day**) — there is **no daily spend
  cap**. A $5/day figure was floated and then withdrawn: the user's instruction
  is that cost is not a design constraint and no functionality is to be traded
  for it. Nothing in this plan may be justified by, or cut because of, the
  running bill. §11.1b's measurements stay — they are useful for capacity
  planning and for noticing a runaway — but they are **not** a budget, and no
  component enforces one. Rate limiting survives on its own footing (§11.1): an
  anonymous public endpoint that spends someone's API credit needs a bound
  against hammering and runaway clients, which is an operational concern, not an
  accounting one.

- **D27** (2026-08-13) — **no cache warming.** `hint_cache_warm` is not to be
  used. It is free only when the namespace is already warm — that is, only when
  the search it precedes would have been fast anyway — and when the namespace is
  cold it "is billed as a query that returns zero rows", which at the shipped
  f16 namespace of ~11.5 GB costs $0.0000115, exactly what a real search's queried
  term costs (§11.1b). It therefore charges full price
  precisely when it would help, and a visitor who loads a page and searches once
  pays twice. Accepted cost: the first query after an idle period pays cold
  latency, which turbopuffer's own figures put at ~300 ms, p90 1,214 ms on large
  datasets.
- **D26** (2026-08-13) — **a theorem's result card shows no theory line**, unless
  a theory condition is active, in which case it shows the theories that matched
  it, marked as matches and with no "+N more". Name-addressed entities always
  show their one declaring theory. Measured justification: only 0.2 % of
  theorem-alike records have fewer than three constituent theories, so
  truncation is the norm; and the alphabetically first constituent belongs to
  session `HOL` in **40.8 %** of records and to some `HOL-*` session in ~12 %
  more, so an alphabetical rule shows a base logic most of the time. The rule
  that does work — show the constituent whose base name matches the entity
  name's first segment, 85.3 % unique per §3.2 — shows a word the user has
  already read in the name directly above. So the line is either redundant or
  uninformative, with no third case. The complete list stays on the entity page
  (§9.4). This settles Q8.
- **D25** (2026-08-12) — **entity pages ship in the first release** (D9, §9.4),
  and every result card links to one. The delivered design already does this:
  the entity name on each card is an anchor, as is the related-entities list on
  the entity page itself. This settles Q9.
- **D24** (2026-08-12, rule revised 2026-08-13) — **only entities that live
  entirely inside AFP and the Isabelle distribution are exported.** The original
  wording gated on the *declaring theory* being in the `AFP-ALL-4` chain, which
  is inexpressible for the 84.9 % of records that are content-addressed and have
  no declaring theory (D13). The rule that works, and that covers both
  addressing schemes with one test:

  > An entity is exported iff every theory it names has a session prefix in the
  > set of sessions declared by the `ROOT` files of `contrib/afp-2026-05-13` and
  > `contrib/Isabelle2025-2` (1,150 sessions), treating the four prefix-less base
  > logics `Pure`, `FOL`, `IFOL` and `ZF` as members (§7.2).

  For a theorem-alike entity "the theories it names" is `theory_constituents`;
  for a name-addressed one it is its declaring theory. No `AFP-ALL-4` chain
  resolution and no entity position is needed.

  Measured 2026-08-13 over 1,156,333 records — which is the 1,156,153 theorem-alike
  records of §3.1 **plus the 180 `EXPERIENCE` records**, since the scan took every
  record carrying `theory_constituents`; the 180 are excluded from the export
  separately by step 0 of §8.1, so they cannot change the outcome, only the
  denominator by 0.016 %. Of those: **30,304 (2.62 %)**
  fall outside, of which 12,421 are the `IFOL` false positive the base-logic
  clause above fixes, leaving **17,883 (1.55 %)** genuinely outside. They are two
  families: the why3/NTP4VC generated material (`pearl_*`, `Why3STD`,
  `NTP4Verif`, `frama_c_*`, ~7,700) and **phi-system** (`Phi_BI`, `Phi_System`,
  `Phi_Logic_Programming_Reasoner`, `Phi_Semantics_Framework`, ~10,173). **Both
  are excluded**; the user decided on 2026-08-13 that phi-system does not go in
  the public index, so no session is whitelisted.

  The user has also accepted that this rule may leak: it is a session-name test,
  not a provenance test, so a statement written in a local file whose constants
  all come from published sessions still ships. Do not add machinery to close
  that — it was weighed and accepted.

- **D23** (2026-08-12) — **every filterable array is a subtoken array.** The
  theory filter switches from whole tokens to subtokens, so `theory_tokens`
  becomes `theory_subtokens` and D21's rule governs all three. D22 forces this:
  the `All` panel `Or`s one typed string across all three fields, and if one of
  them tokenised differently the same string would mean different things inside
  a single condition — `Sorted` matching in two fields and silently failing in
  the third, inside a control that promises "any of the three". Independently it
  fixes the same defect D6/§5.4 exist to fix, left standing in a second field:
  a user who types `Sorted` did not match `HOL-Library.Sorted_Sort`. §3.6's `Or`
  experiment already used a `theory_subtokens` field, so its measured figures
  assume this.
- **D22** (2026-08-12) — **five filter panels, in this order and with these
  labels**: `Entity Name`, `Expression`, `Theory Name`, `All`, `Kind`. Each of
  the first three is a repeatable list of single-line conditions, every
  condition carrying its own `contains`/`excludes` toggle (the control model the
  delivered design uses — §9.1). `All` matches a condition against any of the
  other three and compiles to an `Or` (§6.3), verified available and affordable
  (§3.6); hovering it reveals which three fields it covers. `Kind` stays a
  multi-select chip group. This closes Q12: `name_subtokens` now has an
  interface control and stays in the export.
  *The user rejected `Anywhere` as a label — too vague — and rejected placing
  the combined panel first; `All` sits after the three specific panels.* The
  author argued for a bare `Theory` label on the ground that a theorem carries
  a mean of 7.1 associated theories (§7.2) and `Theory Name` reads singular;
  the user judged `Theory Name` clearly clearer and took `Entity Name` as its
  parallel. Recorded as decided. The plural sense is carried by D15's
  explanatory sentence beside the field (§9.2b), not by the label.
- **D21** (2026-08-12) — **one matching mechanism, not two.** An expression
  condition is matched as `["expr_subtokens", "ContainsTokenSequence", …]` and
  nothing else. The `expr_tokens` field and the `ContainsAllTokens` operator are
  both dropped. To make that survivable, §5.4's subtoken rule is narrowed: it
  discards only the separators it splits on (`_`, `.`, and sub/superscript
  characters) and **keeps every operator token**, where the old rule discarded
  every fragment with no alphanumeric character and so erased `⟹`, `::`, `=`,
  `⟦`, `⟧` from the filterable index entirely. See §5.4 for the rule, §6.3 for
  what a condition compiles to, and §14.6 for the two alternatives rejected —
  including the literal form of this decision the user first proposed
  (`ContainsAllTokens` as the single operator), which was rejected on measured
  grounds.

## 3. Measured evidence

Everything in this section was measured, not assumed. A reviewer should treat any
claim elsewhere in this document that is *not* here as an assumption. The first pass
was taken on 2026-08-09; §3.1's counts, §3.2's prefix arithmetic and §3.4's character
figures were re-measured on **2026-08-19** and each says so where it differs from the
original reading. All of it is this machine's copy of the database, which is not the
authority (`cslh19` is, per D19) — so a figure here can be one snapshot behind
what the export will actually see.

### 3.1 The corpus

**Re-measured 2026-08-19.** Every count in this subsection moved between 2026-08-09
and today, because collection continued and because the D33 key repair rebuilt the
store. The percentages did not move at all. The figures below are the current ones;
the 2026-08-09 readings they replace are given in the right-hand column, because
several other sections still quote them and this is where a reader finds out that
they are old.

```
                              2026-08-19        was 2026-08-09
semantics.lmdb, all entries    1,373,817          1,364,990
  entity records               1,362,343          1,353,574
    theorem-alike              1,156,153 (84.9 %) 1,148,833 (84.9 %)
    name-addressed               206,010 (15.1 %)   204,741 (15.1 %)
    EXPERIENCE                       180             — never published (D24)
  per-theory cost records         11,474             11,415   (§7.3, not entity records)
vector store (Qwen3-8B)
  real vectors                 1,354,534            110,329
  tombstones                       7,809                  —
  keys, i.e. both together     1,362,343            110,329
entity expression
  records carrying one         1,362,096          1,353,394
  characters total               170.5 M            169.7 M
  mean / median / p95              125 / 73 / 379   126 / 75 / 375
  longest expression              88,517             32,228
interpretation                  ~0.40 GB total (2026-08-09; not re-measured)
```

**The vector store is no longer a hole.** It carries exactly one key per entity
record — 1,354,534 real vectors of 8,192 B each (4096 dimensions × int16) plus 7,809
tombstones, and 1,354,534 + 7,809 = 1,362,343 is the record count to the record. The
2026-08-09 reading of 110,329 was a lazy cache mid-fill and is what this subsection
used to report as 8 % coverage; do not size anything from it. §8.1's completeness gate is
therefore 7,809 records short (0.57 %), all of them tombstoned, not 8,908 (0.65 %).

At full coverage the vectors are 1,362,343 × 8,192 B = **11.2 GB**.

### 3.2 What the DB does *not* contain

- **No position — fixed since, and the fix is deployed.** As measured on
  2026-08-09 the raw msgpack tuples had 6, 7, 8 or 12 fields, all accounted for by
  the twelve named `Record` fields, and nothing carried a position: `semantic_store.ML`
  computed `Position.line_of` only to put it in the interpreting agent's prompt, and
  source text was obtained by asking a **live Isabelle** through
  `PIDE_State.command_at_position`. `ENTITY_POSITION_PLAN.md` fixed this and is done:
  `position` is the 13th `Record` field and 1,092,855 records (80.2 %) carry one on
  `cslh19`. The line computation has moved with it, to `Tools/entity_position.ML` and
  `Tools/pide_state.ML`; `semantic_store.ML` no longer performs it. What is **not**
  done is prerequisite C of §12.2 — those positions reaching the published snapshot.
- **No declaring theory for theorem-alike records.** Their key prefix is an XOR
  pseudo-theory. Matching the first segment of `name` against the constituent
  theories' base names resolves **85.3 %** uniquely, **0 %** ambiguously, and
  **fails on 14.7 %** (≈170 k records) — the declaring theory contributes no
  constant to the statement. Example: `Abstract_Reachability_Analysis.max_Var_floatariths_concat`,
  whose constituents are five other theories.
- **Partial declaring theory for name-addressed records.** The key prefix *is*
  the declaring theory's hash. Measured 2026-08-19, the 206,010 name-addressed
  records carry **9,188 distinct prefixes**, of which **8,697 are persistent** —
  and a persistent prefix is the only kind that ships. The 2026-08-09 reading of
  this bullet, kept because §7.3's arithmetic still quotes it, was that harvesting
  `(long name, hash)` pairs out of theorem-alike records' constituent theories
  yields 8,336 mappings resolving 8,311 of the then 9,148 prefixes, i.e. 192,244 of
  204,741 records (93.9 %), leaving 12,497 records in 837 theories with nothing but
  a theory base name. **That harvest is not needed and is not part of this plan** —
  the Draft 3 correction in the next bullet explains why, and §7.3 states the
  measurement that replaced it.
  **Draft 3 correction.** This bullet then said the theory-hash registry
  `~/.cache/Isabelle_Theory_Hash/theory_hash.lmdb` "does not help: 2,910
  entries, 9.9 % hit rate". Both figures were measured on **this** machine,
  which is not the machine that did the interpreting. `cslh19`'s registry holds
  12,208 entries and resolves **8,702 of the 8,704** persistent hashes that ship
  — 100 %, the two apparent misses being a measurement artefact (§7.3). The
  harvest-from-constituents fallback described above is therefore not needed
  either. What remains true is that `snapshot_sync` does not ship the registry;
  `THEORY_HASH_REGISTRY_PLAN.md` fixes that.

### 3.3 turbopuffer, verified against a live account

Namespaces `isa-tok-semantics-test` (10 documents) and `isa-scale-test`
(230,944 documents) in `aws-us-east-1`. *Draft 3 correction:* the document
text is real, the vectors are not — every document carries the same constant
8-dimension vector, so none of the timings below involved vector search, and
230,944 is **17.0 %** of the real corpus — 18.6 % was against the merged
1,241,679 of the original D5, which D5's reversal replaced with 1,362,343 (§1).

| Question | Result |
|---|---|
| Does `ContainsTokenSequence` match across elements of a `pre_tokenized_array`? | **Yes.** `["a","b"]` matches `[a,b,c,d]` only; `["b","a"]` matches `[b,a,c]`; `["b","c","d"]` matches `[a,b,c,d]`. Adjacency and order both honoured. |
| Is there a negated form for `excludes`? | `NotContainsTokenSequence` does not exist (HTTP 422). **`["Not", <filter>]` works** and composes inside `And`. |
| Does the 4 KiB filterable-value limit apply? | **No.** Accepted 40,000 tokens / 262 KiB, and sequence queries still matched. Namespace metadata shows the field as `filterable: false` with a `full_text_search` config — a different storage path. |
| Speed on high-frequency tokens | `server_total_ms`: `⟹` (in 42 % of documents) **82 ms**; `sorted_wrt` 78 ms; `finite` 9 ms; `x = y` 13 ms; include+exclude combinations 14–20 ms. |
| Cold start | **Not a problem.** After 10–40 min idle the first query reports `cache_temperature: "hot"`, `cache_hit_ratio: 1.0`, 15–19 ms. The 6.3 s seen once was index building right after a bulk upsert. A free `GET /v1/namespaces/:ns/hint_cache_warm` exists. |

`pre_tokenized_array` is confirmed `case_sensitive: true`, `stemming: false`,
`remove_stopwords: false`, `ascii_folding: false` — all correct for Isabelle.

Wall-clock from the developer machine was ~900 ms against `server_total_ms` of
15 ms; the difference is network round-trip, not turbopuffer (§6.4).

### 3.4 The tokenizer, on real data

**Every figure in this block is over §3.3's 230,944-document test namespace, not
over the corpus**, and the two lines that disagree do so because they were taken
against different samples of it — the caveat is now on each line that needs it rather
than on one of them.

```
230,944 documents          mean 39.0 tokens before ASCII symbolic runs are merged,
                           37.0 after (the merge is the line below); max 6,981
distinct tokens            56,336 (in a 150 k sample of the 230,944)
document frequency of the commonest tokens
   '(' ')' 65 %   '.' 53 %   '=' 50 %   '⟹' 42 %   ';' 26 %   '⟦' '⟧' 25 %
merging ASCII symbolic runs changes little   39.0 → 38.5 tokens, 56,336 → 56,455 vocabulary
   but creates 130 distinct operators: '::' **9.89 %** of the 230,944 documents
   (9.1 % was the reading on a 150 k sample of them, and is the number to drop),
   ':=' 1.4 %, '::=' 0.3 %, '=>', '->', '**', … — the last three from the sample
   and shortens the ':' postings list from 12.8 % of documents to 2.4 %
```

The `⟹` frequency in the table above, **42 %**, is likewise over these 230,944
documents; §3.6 gives it as 42.35 % against the same population, and over the whole
corpus it is **617,652 documents, 45.34 %** (the companion's §15.1). Three numbers,
two populations, and nothing wrong with any of them except that two of them used to
appear without saying which population they were over.

Whitespace erasure was checked for collisions across the corpus as it stood on
2026-08-09: **200 collision classes out of 1,353,348 expressions (0.015 %)**, and
inspection of all 200 found **none** whose two source texts differ by anything other
than whitespace. Not re-run on the 1,362,096 of today; the conclusion is a property of
the rule rather than of the population. So
discarding whitespace introduces no semantic false positive on this corpus.

**NFC, measured 2026-08-14 — it was not measured here before.** §5.1, D41 and
§16.5 each cite this subsection for "the store is 100 % NFC", and until that date
no NFC figure appeared in it. The claim is true: `NFC(expr) != expr` for **0 of
1,362,096** records and `NFC(name) != name` for **0 of 1,362,343**. It is recorded
here so the three citations have something to point at.

**`unicode_of_ascii(expr) == expr` held for all 1,353,394 records, and no longer
holds.** Since the loader began reading the symbol table Isabelle actually
presents on 2026-08-17, component files included, step 3 changes **1,056 of
1,362,096** stored expressions — the records carrying a phi-System component
symbol such as `\<big_ast>`. One thing that leaned on the old identity is simply
gone: highlight offsets no longer map straight back to `expr` for those records.
D41's argument for synthetic test vectors survives — see the paragraph on the
export scope below — but its wording needs care, so state it once here and cite
this: **on the published corpus, pipeline steps 1, 2 and 3 are all the identity.**
Step 1 because the store is 100 % NFC; step 2 because the U+007F repair is done
(§12.2 step 1 — the 238 records counted below are the 2026-08-09 figure, before
it ran); step 3 because every record it changes is excluded by D24.

Character hygiene, re-measured 2026-08-19: **one** record's `expr` carries
private-use-area characters, and `name` and `interpretation` carry none.
The one is `IDE_CP_Core.φlemmata`, which holds U+E015, U+E028, U+E057 and U+E068 —
four phi-System word glyphs stored as raw characters rather than as escapes,
presumably dragged out of a jEdit buffer. §3.2 used to state this as a flat **0**,
and D44's argument does not depend on which it is: D44 stops the *conversion* from
introducing a private-use character, and a raw one already sitting in the store is
exactly the case D44 names when it says the reverse direction, `ascii_of_unicode`,
"still names a raw private-use character, because text dragged out of jEdit carries
one and naming it is a repair". D24 excludes this record from the export in any case,
phi-System being neither AFP nor the distribution. Also re-measured: **0** records
contain U+007F, the 238 of 2026-08-09 having been repaired (§10); **835** occurrences
of CR, unchanged.

**Literal `\<…>` escapes, re-measured 2026-08-17, and re-characterised.** The
earlier figure — 1,140 records "for a symbol with no code point", 32 kinds —
named the wrong class. The operative distinction is not "in the table without a
`code:` field" but **"not in the table at all"**, and the two behave identically
for the tokenizer while having very different sizes. Of the 3,562 records whose
raw text carries an escape: 77 carry one that the distribution's table defines
without a code point; 1,056 carry one defined only in `contrib/phi-system/symbols`,
and those are exactly the 1,056 that now convert. Of the rest, **1,980** carry a
word-glyph escape that `contrib/phi-system/symbols-words` **does** define — with a
private-use code point, so D44 leaves it alone deliberately — and **1,078**, in 20
distinct kinds, carry one declared in no `symbols` file in this repository at all
(`\<Empt>`, `\<PR>`, `\<aA>`), which no asset can ever convert. (The word-glyph
figure read 1,981 until 2026-08-19; the four classes were re-measured that day and
every other one reproduced to the record. The four do not sum to 3,562 and are not
meant to: a record carrying two escapes of different classes is counted in both.) The three reasons
an escape survives are therefore different in kind, and only the last is a gap.

After step 3 with the widened table, **3,135 records** still carry a literal
escape, and 17 of those carry one the §5.4 split cuts at an underscore. (An
earlier draft of this paragraph said 1,155, which is `77 + 1,078` — it counted
only the escapes absent from the loaded table and silently dropped the 1,981 that
D44 keeps. 3,135 is also the figure D43 quotes for the subtoken arrays the
character-level rule moves; the two are the same set, and the draft had them
disagreeing.)

**All 1,056 newly-converting records are phi-System theories** — `Phi_Types` 716,
`Phi_BI` 74, `Algebras` 49, `Arrow_st` 46, `Len_Intvl` 42, `Phi_Type` 39, and so
on — and **D24 excludes every one of them from the export**, since phi-System is
neither AFP nor the distribution. So on the corpus that is actually published,
step 3 remains the identity, and D41's argument for synthetic vectors survives
intact for the sample §16.5 draws. The asset must still carry phi-System's names,
or a visitor pasting one would tokenize it differently from anything indexed.

### 3.5 The query embedding is network, not compute

`api.fireworks.ai` resolves to Cloudflare (`2606:4700::…`), so a TCP handshake
measures the nearest Cloudflare edge, not the inference host. Sending a request
with a nonexistent model id forces a round trip to the origin without any
inference, which separates the two.

```
                     edge connect   error request   real embedding   response header
                                    (origin, no inference)           fireworks-server-processing-time
developer machine        10 ms          386 ms          653 ms              0.044
Singapore VPS             3 ms          288 ms          470 ms              0.044
```

**Inference costs 44 ms; everything else is network.** The origin is in North
America — 288 ms edge-to-origin-and-back from Singapore exceeds Singapore's
175 ms round trip to `aws-us-west-2`. Which North American region could not be
determined from outside; the response carries no locality header
(`server: istio-envoy`).

Two consequences. First, D18: putting turbopuffer in North America too lets
Smart Placement run the Worker near both backends, so a request crosses an
ocean once (user to Worker) instead of twice. Estimated end to end for a
European user, ~400 ms today against ~170 ms then. Second, the
query-embedding cache is worth less than first thought — once the Worker sits
next to Fireworks a cache hit saves ~54 ms, not ~650 ms. It is still worth
building, but for cost rather than latency (§11.1).

### 3.6 D21 measured, 2026-08-12

Three namespaces in `aws-us-east-1` — the revised single array, a same-session
control carrying the current two-field design, and a three-field namespace for
the `Or` experiments. `isa-tok-semantics-test` and `isa-scale-test` were read
but never written.

**Read the caveat before the numbers.** Every vector in every namespace here is
the constant `[0.1]*8`, an 8-dimension stand-in. That was not a shortcut: the
pre-existing `isa-scale-test` was already built that way, so **§3.3's published
timings never involved vector search either**, and matching it keeps the
comparison exact. What is faithfully measured is filter evaluation — posting
list traversal, adjacency checking, `And`/`Not`/`Or` composition — which does
not depend on vector dimension. What is **not** measured is ANN search over
4096 dimensions, vector fetch, or cache behaviour at real size: every namespace
here is 40–69 MB and reported `cache_temperature: hot`, `cache_hit_ratio: 1.00`
on every query, where production carries ~11 GB of vectors. These are a valid
relative comparison between field designs; they are not a production estimate.

**Index size**, same 230,944 documents, like for like:

```
                       elements    UTF-8 bytes      distinct subtokens
current, both fields   13,924,220  40,922,175       79,720 (union)
revised, one array      8,711,494  22,164,121       33,363
                            62.6%       54.2%            41.9%
turbopuffer logical bytes: revised 40,332,349 vs control 59,090,403 (68 %)
```

Per document the revised array is mean 37.7, median 23, p90 75, p95 111, p99
258, max 6,427; the distribution is strongly right-skewed with a 4.3 % tail at
≥120. The largest structural change is that **the `.` posting list vanishes** —
third-largest in `expr_tokens` at 53.5 % of documents, and a separator here.
Total postings fall from 5.58 M to 3.48 M.

**The operator conditions D21 exists to enable, and their cost.**
`subtokens(tokenize('⟹'))` is `[]` under the old rule, and §6.3 rejects an
empty array, so these were not slow — they were inexpressible:

```
                    old rule   revised   server_total_ms (median)
'⟹'  (42.35 %)      0          97,807    14
'::' ( 9.89 %)      0          22,849    23
'-->'               0               7    —
```

Single-condition queries are otherwise indistinguishable from the current
design. §3.3's `⟹` 82 ms and `sorted_wrt` 78 ms **do not reproduce**: against
that very namespace they measure 11–17 ms, so those two readings were warm-up
noise of the same kind as the 6.3 s already attributed to index building.

**The one real cost of D21**, and it is a genuine one. Two conditions on the
*same* array are markedly slower than the same two spread across two arrays,
which is what the current design would issue for a partial-name include plus an
operator exclude:

```                              revised, one array   current, cross-field
include 'set'    exclude '⟹'    81 ms                17 ms      (13,050 hits)
include 'sorted' exclude '⟹'    20 ms                15 ms         (287 hits)
include 'type'   exclude '::'   54 ms                14 ms       (3,367 hits)
```

Up to 4.8× for identical results. Field-sharing dominates, not posting-list
length: on the control namespace the same two conditions cost 55 ms on one
field and 17 ms across two, and the cross-field version has the *larger*
include list. The mechanism is **inferred, not measured** — presumably
turbopuffer intersects two `ContainsTokenSequence` conditions on one
`pre_tokenized_array` less efficiently than across two.

**No regression, and one strict improvement.** With the recommended rule, no
case behaves worse than the old rule. The old rule leaves **71 documents with
an empty subtoken array**, unmatchable by any condition at all (e.g.
`Syntax.direction.simps(1)` = `['«','≠','»']`); the revised rule leaves zero.
Two properties worth knowing: a fallback-kept token such as `ᶜᵉ` can break an
adjacent run *through* it, which is a consequence of matching becoming ordered
rather than of the class; and subscript folding widens matching slightly —
`x + y` matches 448 documents against 435 that literally contain the run, the
extra 13 being things like `x⇩1 + y`, which is intended under D6.

**`Or` exists, spelled exactly `"Or"`** — `"or"`, `"OR"`, `"Any"`, `"Union"`
all return HTTP 422. It nests in both directions that matter, verified by
inclusion–exclusion on real data: expr-only 836, name-only 563, `And` 424, and
`Or` returns exactly 836 + 563 − 424 = 975. `Not(Or(a,b,c))` — "exclude this
from everywhere" — returns 229,969 = 230,944 − 975, exact. `And(Or(…), Not(…))`
and `Or(And(…), …)` also work. Cost is roughly additive per field, about +17 to
+20 ms, and tracks the fields' posting lists rather than the result size. A
cross-field `Or` is therefore affordable and **no materialised fourth
concatenated array is needed on latency grounds**.

## 4. Architecture

```
browser
  │
  ├── Cloudflare Pages ──── static assets, Isabelle fonts (§9.3)
  │
  └── Cloudflare Worker
        ├── the tokenizer (JavaScript port, §5.5)
        ├── query-embedding cache            → Workers KV
        ├── query embedding                  → Fireworks  (Qwen3-Embedding-8B)
        └── search + attribute fetch         → turbopuffer (one namespace)
```

There is no origin server. The VPS `sg.qiyuan.me` is not in the serving path;
it was benchmarked (§14.3) and rejected for serving.

## 5. The tokenizer — normative specification

This is the single most safety-critical component: the stored token arrays and
the query token arrays must be produced by **byte-identical** logic. A silent
divergence produces silently wrong search results with no error anywhere.

### 5.1 Pipeline

Applied identically to stored entity expressions, stored names, stored theory
long names, and every user-supplied filter string. Steps 1 to 4 are the tokenizer
proper and have no exceptions; step 0 is the one input-dependent step and its
condition is part of the specification.

0. **Strip one trailing `(_)`, and only from an `Entity Name` filter condition.**
   Never from stored text, never from the other panels, never more than once. The
   reason is D5 and `from_collection` (§6.1): where the enumeration invented a name
   for a member of a dynamic fact collection, the card displays
   `<from_collection>(_)` rather than the stored name, so a visitor who copies what
   they see and pastes it into `Entity Name` types `coll(_)` — which tokenizes to
   `['coll','(',')']` and matches nothing, because `name_subtokens` is built from the
   **raw** name (§8.1 step 5). Stripping the suffix makes the pasted form behave
   exactly like the raw one. `DYNAMIC_MEMBER_NAMING_PLAN.md` §2.3 decides this and
   requires it here, as a named step both implementations share with a row in §5.5's
   test-vector file; §16.2 carries the case. The alternative it rejects is filtering
   member rows through `from_collection`, which has no compilation: §6.3 compiles a
   name condition to exactly one form over `name_subtokens`, and the Worker emits one
   filter for the whole namespace, so it cannot branch per row.

1. `unicodedata.normalize('NFC', s)` — the store is already 100 % NFC; queries
   pasted from macOS may be NFD, whose combining marks are not `\w` and would
   split identifiers. **NFKC must not be used**: it maps `₁`→`1` and `𝐚`→`a`,
   destroying Isabelle subscript semantics.
2. Replace U+007F with a space. §10 has landed — zero records carry the character
   as of 2026-08-19 — so this is a no-op on stored text, and it stays for two
   reasons: a visitor can paste one, and D11's root cause is **not** fixed, so the
   collection path can still write one into a new record.
3. **Symbol conversion, which is two passes in this order, not one.**
   a. Replace each `\<name>` by the code point the symbol table gives it, so a
      user may type `\<Longrightarrow>` or `⟹`. A symbol the table does not
      define, and a symbol whose code point is private-use, are both left as the
      literal `\<name>` (D44).

      **What counts as a `\<name>` is Isabelle's rule**, not a looser one: `\<`,
      an optional `^`, a letter, then letters, digits, `_` or `'`, then `>` —
      exactly the pattern `Pure/General/symbol.scala` uses to name a symbol. Text
      that does not match is not an escape and is simply carried through to §5.2,
      where it becomes ordinary characters. This has to be stated because nothing
      else states it any more: until D43 a `symbol_explode` step re-established
      symbol boundaries after this pass, and deleting it left this pass as the only
      place where an escape is recognised at all.

      The reference implementation scanned with `\<[^>]+>` instead — from a `\<`
      to the **next** `>` wherever it falls. The two agree on every well-formed
      escape and on all 1,362,096 stored expressions, and differ only on malformed
      input, which no sample can reach and which the query box produces on the
      first day: under the loose pattern `\<alpha \<beta>` is one unrecognised
      span and `\<beta>` is lost with it, where under Isabelle's rule `\<beta>`
      converts. `Isabelle_RPC_Host.unicode` is tightened to match.
   b. Replace each `⇩x`, `⇧x`, `❙x` pair by the character the fold table gives
      it, so that `x⇩1` and `x\<^sub>1` become the same text. §5.4's separator
      class is defined over the characters this pass produces, so **without this
      pass §5.4 has no meaning** — an earlier draft named only pass (a) and left
      the fold undocumented while the rest of §5 depended on it.
   Both tables come from **the asset** of §5.5, and neither implementation may carry
   its own (D45). `Isabelle_RPC_Host.unicode_of_ascii` is the reference.
   **This step is no longer the identity on stored text**: since the loader began
   reading the symbol table Isabelle actually presents, component files included,
   it changes 1,056 of 1,362,096 stored expressions. §3.4 records the old figure
   and the sections that cite it are corrected there.
4. Group into tokens per §5.2, **one character at a time**.

**The tokenizer is defined over characters** (D43). An earlier draft inserted a
`symbol_explode` step here, so that a `\<foo>` left literal by step 3 stayed one
indivisible unit, and justified it with the claim that such a symbol "can
therefore never be cut in half". That claim was false of the only level that is
indexed: §5.4 splits at `_` without regard to symbol boundaries, so
`\<^const_name>` became `['\<^const','name>']`. Dropping the step changes 0.23 %
of subtoken arrays (3,135 of 1,362,096 expressions), and 3,118 of those 3,135 are
pure refinements: every old subtoken is preserved or split further, so
`\<^named_theorems>` stops indexing as the unsearchable pair
`['\<^named','theorems>']` and indexes as `['\<^','named','theorems','>']`, which a
visitor typing `named_theorems` now finds.

**The remaining 17 lose a subtoken**, and an earlier draft of this decision
claimed there were none. Where an escape sits against an ASCII-symbolic
character, the escape's closing `>` now merges into a symbolic run with it:
`['\<param>',':']` becomes `['\<','param','>:']`, and the standalone `':'` that
used to be indexed is gone.

**Fourteen of the seventeen are phi-System theories, which D24 excludes from the
export — but three are not, and an earlier draft of this section said all of them
were.** The three that D24 does export are AFP entries:

```
AbsCFCorrect.lemma6                            AFP Shivers-CFA
    ['|','\<PR>','l','|', …]      →  ['|\<','PR','>','l','|', …]        loses a '|'
AbsCFCorrect.contour_a_class.abs_cnt_initial   AFP Shivers-CFA
    ['|','\<binit>','|','=', …]   →  ['|\<','binit','>|','=', …]        loses a '|'
Matrix.matrix                                  AFP Kleene_Algebra
    [ …,'~','\<^cite>', …]        →  [ …,'~\<^','cite','>', …]          loses a '~'
```

Both AFP theories use escapes the distribution does not define (`\<PR>`,
`\<binit>`, `\<abinit>`, `\<aPR>` — they are the 1,078 records of §3.4 that no
asset can ever convert), so step 3 leaves the escape literal and the adjacent `|`
or `~` merges into it. The remaining fourteen are phi-System —
`Calculus_of_Programming.φapply_proc`, `PLPR.Premise_const_True(4)`,
`Phi_Types.Param_Annot_def` and their siblings — and nine distinct patterns occur
across the seventeen.

What is lost in every one of the seventeen, AFP included, is **one token of bare
punctuation** — a `|`, a `~` or a `:` that stood alone and now sits inside a
symbolic run. The decision stands on 3,118 refinements against that; it does not
stand on the absolute claim, and it does not stand on the claim that the losses are
confined to material the site never publishes.

### 5.2 Token formation

A **character** here is a Unicode **code point**, never a UTF-16 code unit. The
JavaScript port must iterate code points: 4.17 % of expressions (56,797 of
1,362,096) carry a character above U+FFFF — `𝒮` from `\<S>`, `𝔄` from `\<AA>`,
and 151 of the 624 code-point-bearing symbols in the loaded table are astral (124
of 439 counting the distribution's file alone, which is not the table D45 ships) —
and a port that iterates
code units emits unpaired surrogates, which JSON transports intact and no query
can ever match.

Whitespace produces no token of its own, and it **is** a boundary: `x + y` and
`x+y` are identical because an identifier run and a symbolic run cannot merge in
either spelling, while `f x` and `fx` differ because the space ends the run. Any
discarded character ends the run in progress, which is why `a?b` is `['a','b']`
and not `['ab']`. (An earlier draft said the opposite — "token boundaries come
from the grouping, not from whitespace" — which contradicted both `f x` ≢ `fx`
in §5.3 and the `a?b` line in §16.2.)

- **discard**: any character for which `isspace()` holds, and `?` (D4). Both end
  the current token.
- **identifier token**: a maximal run beginning with a *letter* and continuing
  with letters, digits or quasi-letters. *Letter* = a character for which
  `isalpha()` holds. *Digit* = `isdigit()` or `isnumeric()` (so `₁` continues an
  identifier). *Quasi* = `_` and `'`.
- **symbolic token**: a maximal run of characters from
  `! # $ % & * + - / : < = > @ \ ^ | ~` (D8).
- **anything else**: one character, one token.

The letter and digit sets are **not disjoint**: 81 code points, the CJK
ideographic numerals, satisfy both. The order of the tests is therefore
normative — *letter* is tested first, so `一二三` is one identifier token and not
three. D45's asset must preserve the overlap rather than partition it.

A quasi-letter cannot **begin** an identifier, only continue one. So Isabelle's
type variable `'a` is two tokens, `["'", 'a']`, and `_wrt` is `['_','wrt']` whose
first token then disappears in §5.4. Both are load-bearing and neither is
obvious; §16.2 carries a case for each.

The `letter`/`greek` groups of `etc/symbols` are **not** consulted, though an
earlier draft said they were. Re-measured 2026-08-19 against the table Isabelle
actually presents: those groups have **190** members (they had 164 when the loader
still rebuilt the table from `ISABELLE_HOME` alone), and **every one of the 190**
satisfies `isalpha()`, so the union adds nothing; and every one has a code point, so
step 3 substitutes it before token formation ever sees it. The prototype in
`site/prototype/` does consult them — its `_is_letter` unions the group members in —
which is the second of the two ways it is stale (§16.1); it makes no difference to
any output for exactly the reason just measured.

Neither `.` nor `?` is an identifier character. `.` must not be, or
`λx. P x` and `λx.P x` would differ.

### 5.3 Verified equivalences

```
'x + y'          ≡ 'x+y'                 'f x'      ≢ 'fx'
'(- x)'          ≡ '(-x)'                'map f xs' ≢ 'mapfxs'
'A ⟹ B ⟹ C'      ≡ 'A⟹B⟹C'
'⟦?P; ?Q⟧'       ≡ '⟦?P;?Q⟧'
'λx. P x'        ≡ 'λx.P x'
'x :: nat'       ≡ 'x::nat'
'x⇩1 + y'        ≡ 'x⇩1+y'
'sorted_wrt R ?xs' ≡ 'sorted_wrt R xs'
'size Č = 0'     ≡ its NFD spelling
```

### 5.4 Subtokens

A second level, derived from the tokens. Under D21 it is the **only** level
that is indexed or queried; tokens are an intermediate product of §5.2 that no
filter ever sees.

**The rule.** Split each token on `_`, `.` and sub/superscript characters, and
discard those separators. Discard nothing else: a token that is an operator, a
bracket or any other punctuation survives unchanged, because it is a legitimate
thing to filter on. A token consisting only of separators disappears entirely.
That is what makes the user's query `_wrt` compile to `['wrt']` — though not by
the route the wording suggests: `_wrt` is already **two** tokens by §5.2, since a
quasi-letter cannot begin an identifier, and it is the separator-only first token
that disappears here. The example does not discriminate between that reading and
one where `_wrt` is a single token split by the rule, so do not use it to check
an implementation's token boundaries.

```
['sorted_wrt','R','xs']        → ['sorted','wrt','R','xs']
['Kelly_1_39']                 → ['Kelly','1','39']
['Fₒ','Obj','⇩','A']           → ['F','Obj','A']        ← constructed, see below
['x','+','y']                  → ['x','+','y']          ← operator kept (D21)
['⟦','P',';','Q','⟧','⟹']      → unchanged              ← operators kept (D21)
```

*Draft 3 correction.* The third line is **not a real record**, though drafts 1
and 2 presented it as one. No document contains `['Fₒ','Obj','⇩','A']` as an
adjacent run; `Fₒ` occurs in 50 documents and `Obj⇩A` in 44, never adjacent.
Both halves verify separately on real data, so the point the example makes
stands — only the example is fabricated. It is kept, labelled, because it shows
both folding behaviours in one line.

**The separator character class**, settled by measurement on 2026-08-12 (§3.6).
99 characters, **derived rather than typed out by hand** — a hand-written class
is exactly what went wrong before. Derived from what, precisely: seven of them,
the control characters, are read from a symbols file; `_` and `.` are ASCII
literals in the rule itself; and the other 90
come from `SUBSUP_TRANS_TABLE`, a 142-entry dict in
`Isabelle_RPC_Host/unicode.py`. That table **is** hand-maintained, and no symbol
file carries folding information of any kind, so an earlier claim here that the
whole class derives from `etc/symbols` was wrong. The consequence is D45's: the
fold table has to ship in the asset, or the JavaScript port cannot fold at all
and cannot reconstruct the class.

```python
from Isabelle_RPC_Host.unicode import get_SYMBOLS_AND_REVERSED, SUBSUP_TRANS_TABLE
_SYMS = get_SYMBOLS_AND_REVERSED()[0]
_SUB, _SUP = _SYMS[r'\<^sub>'], _SYMS[r'\<^sup>']            # ⇩ U+21E9, ⇧ U+21E7

# control characters: a sub/superscript or bold marker must never survive alone
CONTROL_SEPARATORS = ''.join(_SYMS[s] for s in (
    r'\<^sub>', r'\<^sup>', r'\<^bsub>', r'\<^esub>',
    r'\<^bsup>', r'\<^esup>', r'\<^bold>'))                  # ⇩⇧⇘⇙⇗⇖❙   (7)

# the rendered characters the folding produces from a ⇩ or ⇧ marker
RENDERED_SEPARATORS = ''.join(sorted(
    {v for k, v in SUBSUP_TRANS_TABLE.items() if k[0] in (_SUB, _SUP)}))   # 90

SUBTOK_SPLIT = re.compile('[' + re.escape('_.' + CONTROL_SEPARATORS
                                          + RENDERED_SEPARATORS) + ']+')
_RENDERED = frozenset(RENDERED_SEPARATORS)

def subtokens(toks):
    out = []
    for t in toks:
        parts = [p for p in SUBTOK_SPLIT.split(t) if p]
        if parts:
            out.extend(parts)
        elif t and all(c in _RENDERED for c in t):
            out.append(t)                    # the fallback; see below
    return out
```

**The fallback clause is load-bearing and must stay narrow.** A token that
splits to nothing normally disappears — that is what makes the query `_wrt`
compile to `['wrt']`. But a token made *entirely* of rendered sub/superscripts
is real content, not decoration: `ₚₜᵣ` (317 occurrences), `ᶜᵉ` (336), `ᵢₛₒ`
(178), `ₜᵣₛ` (164), `²` (640), `₁` (1,281). Without the clause, 108 such tokens
in **7,346 documents (3.18 %)** become unsearchable. **Every figure carried over
from the 2026-08-12 measurement — that is, every one in this subsection except
where the next sentence gives a whole-corpus replacement — is against 230,944
documents**, the §3.3 test namespace, not the 1,362,096 expressions §16.2 gives as
the corpus scale; an earlier draft named no denominator at all, and a later one
claimed the 230,944 denominator for the replacements too. Re-measured over the whole corpus the
same quantity is **51,891 documents (3.81 %) and 154 distinct tokens** — independently
reproduced 2026-08-19, to the record, under the character-level tokenizer of D43 — and
the raw occurrence counts move too: `²` is 3,955, not 640, and `₁` is 7,023, not
1,281. **3.81 % is the whole-corpus figure and the only one to quote outside this
subsection**; 3.18 % is the same quantity over §3.3's 230,944 documents, and §14.7
used to give it as 3.71 %, which was neither.
D41 and §16.4 both used to repeat the 640 as "occurrences in the corpus", where it
is six times low; both now give 3,955 and say that 640 is the count over §3.3's
230,944-document namespace. Restricting it to rendered
characters is equally load-bearing: the obvious unrestricted version ("keep any
token that splits to nothing") was measured and **breaks the `_wrt`
counter-example outright** — `_` would survive, the query would become
`['_','wrt']`, and 130 targets would drop to 0.

**The old class was already wrong, and this fixes it.** The prototype's
`[_.⁰-₟²³¹]` (U+2070–U+209F plus three) covers only **44 of the 90** rendered
characters the folding actually produces. The 46 it misses — `ᵢ` U+1D62, `ᵀ`
U+1D40, `ⱼ` U+2C7C, the modifier capitals and smalls, `ʰʲʷʸˡˢˣ` — occur in
**6,445 documents (2.79 %)**. Measured consequence today: of the 20 documents
containing the token `xᵢ`, a query for `x` finds **0** under the current rule
and **20** under this one.

`❙` (U+2759, from `\<^bold>`) is in the class on evidence, not by analogy: it
behaves exactly like `⇩`, folding into the next character (`❙x` → `𝐱`) and
being stranded as a lone token when the next character has no folding (`❙(`),
in 1,689 documents. Its 52 folded outputs `𝐚`–`𝐳`, `𝐀`–`𝐙` stay **out** — they
carry the letter's identity and are real content. The other 20 `\<^…>` control
symbols also stay out: 14 never occur, and the remaining 6 occur in 11
documents in total and are document markup, i.e. content.

Keeping the old character class while narrowing the discard rule would have
emitted 112,680 separator-only subtokens across **24,654 documents (10.68 %)**,
every one an adjacency break.

Re-verified under the narrowed rule **and** under `ContainsTokenSequence`,
which demands adjacency where `ContainsAllTokens` demanded only containment —
all six adversarial-review counter-examples still find their targets, and the
three operator conditions that were previously inexpressible now work (§3.6).

**What D21 costs and why it is affordable.** `ContainsTokenSequence` is ordered
and adjacent, so a single condition can no longer express "these words in any
order" — `sorted append` no longer matches `sorted_wrt_append`. That intent is
still expressible, because an expression filter takes **several conditions and
conjoins them** (§9.1): the user enters `sorted` and `append` as two separate
conditions, and two single-subtoken sequences conjoined **is** unordered
containment. So the capability moves from an operator to a second condition; it
is not lost. This argument holds whichever control model §9.1 ends up with —
one multi-line text area per polarity, or repeatable single-line rows with an
include/exclude toggle — because both let a user enter two conditions.

### 5.5 The two implementations

The site export runs the Python implementation; the Worker runs a JavaScript
port. To stop them drifting:

- **One asset, emitted at export time, read by both** (D45). It carries the
  symbol table, the fold table, the letter / digit / quasi-letter /
  ASCII-symbolic / separator sets, and the abbreviations the condition box needs.
  Neither implementation may hard-code any of it, and neither may consult a
  language built-in for a character class — §5.2 names Python predicates to
  *define* the sets, not to be called at run time.

  Naming the source files is not optional bookkeeping. `etc/symbols` is not one
  file: Isabelle assembles `ISABELLE_SYMBOLS` by appending, so every registered
  component contributes, and rebuilding the list from `ISABELLE_HOME` instead —
  which the loader did until 2026-08-17 — silently drops all of them. The asset
  therefore records the exact file list and the Unicode version of the classes,
  and `Isabelle_RPC_Host.unicode.get_SYMBOL_FILES()` reports the former.

- **The namespace name embeds the asset's digest** (D45), so an index and the
  asset that built it cannot come apart. This replaces a run-time consistency
  check: there is nothing to check, because a Worker carrying an older asset
  addresses the namespace that asset built.

- The export emits a **shared test vector file** and both implementations must
  reproduce it exactly in CI — see §16.5 for what it must contain and §16.6 for
  what the gate must assert. Sampling real expressions is necessary but not
  sufficient: **on the corpus that is actually published**, pipeline steps 1, 2 and 3
  are all the identity (§3.4 — step 3 does change 1,056 stored expressions, and D24
  excludes every one of them), so the gate must assert **coverage of named features**
  and not merely a sample size. Step 0 needs a row of its own too: a condition ending
  in `(_)` and the same condition without it must produce the same subtokens.

- The test vector file is versioned with the data, and so is the asset.

## 6. turbopuffer schema and queries

### 6.1 Schema

```
id               UUID  = a 128-bit hash of the universal key (§6.2); stable,
                       because D33's key repair runs before any export
group            string  128-bit hash of `(name, entity expression)`: the
                       identity of the entity page (§9.4) and the key the
                       response collapses on (D5). Filtering is unbilled, so
                       assembling a page from a group costs nothing extra
vector           [4096]f16, cosine_distance   (D31)

  display
name             string
expr             string        cleaned per §8.3, original whitespace kept
theories         []string      the theory long names this document is filtered
                               by (§7.2): the declaring theory when
                               name-addressed, all constituents when
                               theorem-alike (mean 7.1, max 42)
kind             string        this record's single kind — D5 does not merge
position         string        symbolic path + line, from ENTITY_POSITION_PLAN
from_collection  string        empty unless `name` is a name the enumeration
                               INVENTED for a member of a dynamic fact
                               collection, in which case it is that
                               collection's full name and the row is displayed
                               as `<from_collection>(_)` instead of `name`.
                               DYNAMIC_MEMBER_NAMING_PLAN.md §2.3 states the
                               rule and why the raw `name` must not be
                               rewritten here (it feeds `group` and
                               `name_subtokens`).  Must be present in the FIRST
                               export: §8.2 makes every export a fresh
                               namespace, so adding it later re-exports the
                               whole corpus.  Implemented twice, like every
                               field here — Python export and Worker (§6)

  filtering — all pre_tokenized_array
expr_subtokens   []string      the only expression field there is (D21); an
                               `expr_tokens` field was in draft 2 and is gone.
                               Mean 39.19 elements over the whole corpus, and
                               NOT ONE of the 1,362,096 arrays is empty --
                               the old rule left 71 unmatchable (§3.6)
name_subtokens   []string      reached by the `Entity Name` panel (D22).
                               Mean 6.77 elements; this is the short one
theory_subtokens []string      the subtokens of every name in `theories`,
                               concatenated with a separator token between
                               names (§6.3).  Subtokens, not tokens, per D23;
                               named `theory_tokens` through draft 2.  Mean
                               24.71 elements over the records that have
                               constituents, separator tokens counted

  ranking
interpretation   string        BM25-indexed (§6.5)
```

### 6.2 Document id

The universal key cannot be the id: keys run from 20 to **308 bytes**, and
**89,137 of 1,362,343 (6.54 %)** exceed turbopuffer's 64-byte string-id limit once
base64url-encoded (re-measured 2026-08-19; it read 88,798 / 6.6 % on 2026-08-09, and
it grows with the corpus).
Use a **128-bit hash of the universal key as a UUID**, and keep the full key as
an ordinary attribute. The hash must be **deterministic**, so that a re-export
upserts in place instead of creating duplicates.

### 6.3 Query construction

Under D21 there is one form for an expression condition, and `ContainsAllTokens`
appears nowhere:

The two polarities are named `contains` and `excludes` throughout, matching the
toggle the interface shows (D22); an earlier draft of this table wrote the first one
`includes`.

```
contains(expr)   ["expr_subtokens", "ContainsTokenSequence", subtokens(tokenize(s))]
excludes(expr)   ["Not", ["expr_subtokens", "ContainsTokenSequence", subtokens(tokenize(s))]]
contains(name)   ["name_subtokens", "ContainsTokenSequence", subtokens(tokenize(s))]
contains(theory) ["theory_subtokens","ContainsTokenSequence", subtokens(tokenize(s))]
contains(all)    ["Or", [ the three contains forms above ]]                   ← D22
excludes(all)    ["Not", ["Or", [ the three contains forms above ]]]          ← D22
combination      ["And", [ … ]]
```

`Or` is verified to exist, to nest inside `And`, and to sit inside `Not`; the
`excludes(all)` form above returned exactly `total − contains(all)` on real
data (§3.6), and the user confirmed on 2026-08-12 that "appears in none of the
three" is the intended reading. **`excludes` on the `All` panel is `Not(Or(…))` — "appears in none
of the three" — and never `Or(Not(…),…)`, which would be satisfied by almost
every document.** An `Or` across three fields costs about +17 to +20 ms per
extra field, so no materialised concatenated field is needed.

There is consequently **no routing rule, no mode selector, and no fallback
query**. Draft 2 left all three undecided, and the "no exact match, showing
word matches" notice that `site/DESIGN_PROMPT.md` requires (its deliverable 5)
exists only to explain a fallback that D21 deletes; that brief must lose it.

An empty subtoken list must be rejected before it reaches turbopuffer: it would
match everything (D7 also forbids the empty query outright). This is not a
corner case under D21 — a condition consisting only of separators, such as `_`
or `.` or `⇩`, reduces to the empty list, and the interface must say why it was
rejected rather than silently dropping the condition.

**`theory_subtokens` needs a separator.** A theorem-alike document carries a mean
of 7.1 theory names, and `ContainsTokenSequence` matches across the whole array
(that is exactly what §3.3 verified), so a naive concatenation would let a
sequence straddle two names: `[HOL.List, Affine_Arithmetic.Foo]` becomes the
subtokens `[HOL, List, Affine_Arithmetic, Foo]` — under D21 the `.` is a
separator, so it does not even stand between them — and would match a query for
`List Affine_Arithmetic`, which is not any theory's name. Put one separator
token between names. `"\n"` is the intended choice precisely because the tokenizer
discards whitespace and can therefore never emit it, so no user query can
contain it — and it survives subtoken formation untouched, being injected by
the export rather than produced by the tokenizer and absent from D21's
separator class.

**It is not yet settled, and §8.1 owns the test.** Whether turbopuffer stores and
indexes a whitespace-only element of a `pre_tokenized_array` at all was never
measured (§3.3 did not test it), and if it is dropped the adjacency straddle above
comes back. One upsert against a test namespace settles it; if `"\n"` is dropped,
choose a non-whitespace character the tokenizer cannot emit — every character the
tokenizer can emit is either a letter, a digit, a quasi-letter, an ASCII-symbolic
character or a single other character it passes through, so a control character
outside the separator class is the natural fallback. This test is **step 0b of §8.1**
so that it cannot be forgotten; §16.8 lists it as one of the questions to settle
during the work.

Index cost. Two sets of figures, and the difference between them is the population,
not the rule — an earlier draft gave the first set with no denominator at all:

```
                    §3.6's 230,944-document namespace   the whole corpus, 2026-08-19
expr_subtokens                        37.72                        39.19
theory_subtokens                      21.46                        24.71
name_subtokens                         6.30                         6.77
```

Quote the whole-corpus column when sizing the production namespace, since that is what
gets built. `theory_subtokens` is counted over the records that carry constituent
theories, separator tokens included.

### 6.4 Region

**North America (D18)**, co-located with the Fireworks origin (§3.5) so that
Cloudflare Smart Placement can put the Worker next to both backends. Which
North American region is second-order and **reversible** — turbopuffer has
`copy_from_namespace` — so start with one and measure from inside a deployed
Worker, which can time the Fireworks origin far better than anything from
outside can.

Recommended start: `aws-us-west-2`, on the weak prior that Fireworks is a Bay
Area company. Confirm or move after launch.

Round-trip times measured for the record (TCP connect, i.e. one RTT; a fresh
HTTPS request costs about four times this, but the Worker keeps connections
alive so steady state is one):

```
from Singapore   gcp-asia-southeast1 3 ms │ aws-ap-south-1 62 ms │ aws-ap-southeast-2 94 ms
                 aws-eu-west-2 160 ms │ aws-eu-central-1 161 ms │ aws-eu-west-1 168 ms
                 aws-us-west-2 175 ms │ gcp-us-central1 209 ms │ aws-us-east-1 213 ms
                 gcp-europe-west1/3/4 227 ms
from China       aws-eu-central-1 0.61 s │ aws-eu-west-1 0.70 s │ aws-us-west-2 0.87 s
                 aws-us-east-1 1.13 s   (full query, cold connection)
```

Public regions confirmed reachable: AWS `us-east-1 us-east-2 us-west-2
ca-central-1 eu-west-1 eu-west-2 eu-central-1 ap-south-1 ap-southeast-2`; GCP
`us-central1 us-east4 us-west1 europe-west1 europe-west3 europe-west4
asia-southeast1`. `aws-ap-southeast-1` and `aws-ap-northeast-1` do not resolve.

### 6.5 BM25 over the interpretation

Worth carrying because hybrid keyword+vector retrieval measurably helps
exact-name intents ("the one called `sorted_wrt_append`"), which a bi-encoder
alone handles poorly.

**Stale text removed, 2026-08-14.** This section used to give a second reason:
that BM25 is the degradation path when the embedding budget is exhausted.
**D35 deleted that path** — the user rejected it on 2026-08-14 ("this
degradation is pointless and only adds code complexity"), and every limit now
returns 429. §11.1 already says so; this section did not.

**What BM25 indexes matters for the interface, and it is only
`interpretation`** (§8.1's field table). Not the name, not the entity
expression. So a visitor who half-remembers a name and types it into the search
box is relying on the interpretation happening to contain it — the reliable
route is to type the name into an `Entity Name` condition and let the query
rank what survives. **The interface must say this**: §13b's Isabelle reader
named the required query as the single thing that would send them back to
`find_theorems`, and their need is fully served by the design as it stands.
This is a copy defect, not a case for reopening D7.

### 6.6 How the two legs are fused (D36)

D29 locks hybrid retrieval with reciprocal rank fusion; this is the mechanism.

**One `multi_query` request, fused by turbopuffer.** Two legs — the vector leg
over the query embedding, and the BM25 leg over `interpretation` — submitted
together and fused by turbopuffer's own RRF. Fusing in the Worker instead would
cost a second round trip and re-implement what the service already does.

**The filter tree is attached to BOTH legs.** This is a correctness
requirement, not a preference. §6.3 shows one filter tree, and attaching it only
to the vector leg would let every document arriving through the BM25 leg bypass
every syntactic condition — including D22's `excludes` on `All`, whose whole
meaning is "appears in none of the three". A user who writes an exclusion and
then sees the excluded thing in the results has been given a wrong answer, not
a ranking they disagree with.

**Each leg fetches 200; the fused list is truncated to 200.** Under D5 those
200 rows collapse to ~182 distinct entities in the response, which is what
D29's "200 results" means — at most 200, no second request, no `load more`.

**The RRF smoothing constant is 60**, the conventional default. It is recorded
here so that an implementer does not have to invent one; nothing measured
argues for a different value, and changing it is a ranking-quality question to
settle against real queries, not a design decision.

Unmeasured, and deliberately not a design input: whether turbopuffer bills a
`multi_query` once or once per leg. Cost is not a constraint on this plan
(D28), so it does not bear on any choice above. It is settled by reading
`billing.billable_logical_bytes_queried` off one `multi_query` response.

## 7. Theories for filtering

### 7.1 Theorem-alike entities have no declaring theory (D13)

An earlier draft treated "the declaring theory is missing for 14.7 % of
theorem-alike records" as a data gap needing an Isabelle pass to fill. **That
framing was wrong.** In this data model a theorem-alike entity is
*content-addressed*: its key is the statement's digest under an XOR
pseudo-theory prefix, so the same statement is the same entity wherever it is
written, and what governs it is its constituent theories. There is no declaring
theory to recover, and nothing should invent one.

Consequently **`ENTITY_POSITION_PLAN.md` needs no change** — no 14th field, no
extra work folded into its backfill. An earlier revision of this plan
recommended exactly that; it is withdrawn.

### 7.2 What the theory filter matches (D14)

| entity kind | filtered against | source | coverage |
|---|---|---|---|
| theorem-alike (1,156,153) | its **constituent theories** | the `theory_constituents` field | already in the DB, 100 %, session-qualified |
| name-addressed (206,010) | its **declaring theory** | the key's 16-byte theory hash | needs the theory-hash registry (§7.3) |

Measured 2026-08-19: **7.09** constituent theories per theorem-alike record on average
(median 6, maximum 42), drawn from **8,329** distinct theory long names — the same
figure D39 gives; this subsection said 8,299 until today and was the stale half of the
pair. Only four of the 8,329 carry no session prefix — `Pure`, `FOL`, `IFOL`, `ZF` —
which are Isabelle's own base logics and genuinely have none. The counts in the table
above are the 2026-08-19 record counts; the measured rows below it are from 2026-08-13
and are proportions, which have not moved.

The two alternatives were measured against real data and rejected:

```
filter               theorem-alike matched   candidate set,      candidate set,
                     by constituents         D14                 if theorems always pass
HOL-Analysis            50,244  ( 4.4 %)      50,906  ( 3.8 %)    1,149,495  (84.9 %)
HOL-Probability         17,986  ( 1.6 %)      18,254  ( 1.3 %)    1,149,101  (84.9 %)
HOL-Library            159,559  (13.9 %)     161,558  (11.9 %)    1,150,832  (85.0 %)
Affine_Arithmetic        4,213  ( 0.4 %)       4,642  ( 0.3 %)    1,149,262  (84.9 %)
Jordan_Normal_Form      10,291  ( 0.9 %)      10,694  ( 0.8 %)    1,149,236  (84.9 %)
HOL.                 1,136,936  (99.0 %)   1,139,036  (84.2 %)    1,150,933  (85.0 %)
```

Letting theorem-alike entities pass unfiltered pins the candidate set at
84.9–85.0 % **whatever is filtered** — the filter stops working, silently, for
the 85 % of the corpus users mostly want. Excluding them instead removes that
same 85 % from the results. Matching constituents narrows to 0.3–12 %, which is
what a filter is for.

Note the last row: 99 % of theorem-alike statements mention something from
`HOL`, so filtering on a base session has no discriminating power. That is
inherent to the corpus, not a defect of the design.

### 7.3 The theory-hash registry

One name for it, used everywhere below and in §12.2: **the theory-hash registry**.
Earlier drafts also called it "the hash-to-name table" and "the complete hash-to-name
table"; those are gone.

Name-addressed entities carry their declaring theory's hash in the key prefix,
and a per-theory record does exist in `semantics.lmdb` under that 16-byte key —
but it holds only interpretation cost accounting (`input_tokens`, `cost_usd`,
`model`, `driver`, `finished`), **no name**. **11,474** such records exist
(2026-08-19; 11,415 on 2026-08-12).

The table that does map hash to name is a separate store, the **theory-hash
registry** `~/.cache/Isabelle_Theory_Hash/theory_hash.lmdb`
(`hash -> [long name, timestamp]`). `snapshot_sync` does not ship it, so a
published database has none of it — that is the real problem, and
`THEORY_HASH_REGISTRY_PLAN.md` is the plan that fixes it.

**Draft 3 correction — the table does not need to be rebuilt.** Drafts 1 and 2
said this store "holds 2,910 entries and resolves only 9.9 % of the 9,148
prefixes we need", and concluded it was *deterministically reconstructible* by
one enumeration run over Isabelle2025-2 and afp-2026-05-13 — "a light,
independent job". **That conclusion was wrong**, because the measurement was
taken on this machine, which never did the interpreting. Measured on 2026-08-12:

```
hashes the site must resolve            9,214
  this machine's registry   3,145 →  1,057   (11.5 %)
  cslh19's registry        12,208 →  9,154   (99.3 %)

restricted to PERSISTENT hashes, the only ones that ship   8,704
  cslh19's registry alone               →  8,702  (100.0 %)
```

The 60 that `cslh19` misses are WIP hashes, which never ship; the one remaining
apparent miss is the one-byte global version counter, which `_ships` rejects
anyway. **The shortfall on persistent hashes is zero.** So the "two apparent
misses" §3.2 mentions are these: one is a WIP hash and one is the version counter,
and neither is a theory whose name is unavailable.

**The population has moved since, and the conclusion has not.** Re-measured on this
machine 2026-08-19, the name-addressed records carry **9,188** distinct key prefixes
of which **8,697** are persistent, against the 9,214 / 8,704 above. The registry
arithmetic was not re-run — it needs `cslh19`, which is the authority for it — and the
numbers to quote for the registry remain the 2026-08-12 ones. What a reader should
take from the pair is that the count of hashes to resolve is a little over nine
thousand and a little under nine thousand of them are persistent; the exact figure
depends on which machine and which day, and no decision turns on it.

That is structural rather than lucky: `store_theory_hash` walks
`Theory.nodes_of` at the start of every interpretation run, so the registry
accumulates exactly the theory cones that were interpreted — and the published
snapshot is what those same runs produced.

Consequently the enumeration run is not part of this plan's critical path (keep
`Isabelle_RPC/list_theory_hash.py` and `List_Theory_Hash_App.thy` as the
recovery path if a registry is ever lost), and the interim
harvest-from-constituents fallback that drafts 1 and 2 described — 8,336
mappings, 93.9 % of name-addressed records, with the rest degraded to a
non-unique base name — is not needed.

One caveat this plan must honour: a persistent hash does **not** determine one
theory long name. Byte-identical theory text vendored into a second session
gets one hash under two session-qualified names (measured: 2 cases of 9,214,
both from phi-system's copies of `HOL-Statespace`). See
`THEORY_HASH_REGISTRY_PLAN.md` §3.5 and its decision R9.

## 8. The site export

A batch job producing the turbopuffer namespace from the semantic DB. It must
be re-runnable and deterministic.

### 8.1 Steps

0. **Scope.** Keep only entities every one of whose theories has a session
   prefix in the declared-session set of AFP plus the distribution (D24) — the
   `theory_constituents` for a theorem-alike entity, the declaring theory for a
   name-addressed one. Also drop WIP-prefixed and EXPERIENCE keys, which no
   session test can reach.
0b. **Settle the `theory_subtokens` separator** (§6.3) before anything is written
   into a production namespace: one upsert into a test namespace, checking that a
   whitespace-only element of a `pre_tokenized_array` is stored and indexed. If it is
   not, pick a non-whitespace separator the tokenizer cannot emit. This is first
   because getting it wrong is only visible as a theory filter that matches a name no
   theory has, and because §8.2 makes every export a fresh namespace, so changing the
   separator later re-exports the whole corpus.
1. **Completeness gate.** Assert that every entity record has a vector. The
   vector store is a lazy cache and missing vectors are legal in normal
   operation, so the export must **fail loudly** rather than publish a corpus
   with holes. *Status 2026-08-19:* **7,809 records (0.57 %)** have no vector, all of
   them tombstoned and awaiting re-embedding, so the gate does not pass yet. (It read
   8,908 / 0.65 % on 2026-08-12; the shortfall is shrinking, and "all of them
   tombstoned" holds exactly — the vector store carries 1,354,534 real vectors plus
   7,809 tombstones, which is one key per entity record, §3.1.) The user has taken
   this as a known item to be resolved before the first export, not as a reason to
   weaken the gate.
2. **Group.** Compute the `group` hash of `(name, entity expression)` for each
   record. Nothing is merged (D5); the collapse happens in the Worker's response
   after ranking.
3. **Clean** the display text (§8.3).
4. **Resolve** the declaring theory (§7) and the position.
4a. **Copy `from_collection`** from the record (§6.1). It is stored, never
   re-derived from the name: the test that would re-derive it depends on the
   corpus and fails silently on a static bundle whose base happens to name a
   collection (DYNAMIC_MEMBER_NAMING_PLAN.md §4).
5. **Tokenize** into the filterable arrays of §6.1 (§5). `name_subtokens` comes
   from the raw `name`, never the displayed form: `from_collection` is a display
   attribute and the Worker emits one filter for the whole namespace, so it
   cannot route a member row to a different field. A pasted `coll(_)` is handled
   on the **query** side instead, by **§5.1's step 0**, which strips one trailing
   `(_)` from an `Entity Name` condition before tokenizing so that it behaves exactly
   like the raw name. That step is part of the tokenizer both implementations share
   and it has a row in the test-vector file (§5.5) and a case in §16.2; it is **not**
   part of the asset, which carries character classes and tables rather than rules.
6. **Emit** the one stamped tokenizer asset (D45, D46) and the shared test-vector
   file (§5.5). The asset is a single file, and §16.4 lists exactly what it carries:
   the symbol table, the fold table `SUBSUP_TRANS_TABLE`, the five character-class
   sets (letters, digits, quasi-letters, the 99 separators, the ASCII-symbolic set),
   the abbreviation table, and its own provenance — the `ISABELLE_SYMBOLS` file list
   and the Unicode version the classes were built under. "The symbol table JSON" was
   this step's wording before D45 and describes about a fifth of what must be
   emitted; an implementer following it would ship a port that cannot fold, cannot
   classify characters and cannot offer live abbreviation replacement.
7. **Upsert** into a fresh namespace (§8.2), then switch the Worker over.

### 8.2 Versioning

Write each export into a **new namespace**, and switch the Worker's target when it
verifies. turbopuffer has no "delete everything absent from this batch"
operation, so upserting into the live namespace would leave deleted entities
behind forever. A fresh namespace also gives an instant rollback.

**The name carries both the data and the asset digest (D45).** An earlier draft
named it for the data alone — `isabelle-2025-2-afp-2026-05-13` — which predates D45
and loses the whole point of that decision: the digest in the name is what makes
"new index, old asset" unconstructible, because a Worker holding an older asset
addresses the namespace that asset built and simply finds the old index. The scheme:

```
isasearch-<isabelle release>-<afp snapshot>-<asset digest, 12 hex characters>
e.g. isasearch-2025-2-afp-2026-05-13-9f3c1ab77d02
```

The digest is the SHA-256 of the asset file's bytes; twelve hex characters is this
author's choice implementing D45, which fixed that a digest appears and not how long
it is — twelve is short enough to read in a dashboard and long enough that a
collision is not a thing to think about.

**And the export must fail rather than silently rename the namespace (D46).** D46
requires that "an export that finds a different component set than the declared one
must fail", and never said where the declaration lives. It is the **committed asset
from the previous export**: the export recomputes the asset from the live
installation and compares its `ISABELLE_SYMBOLS` file list and its digest against
that file, and stops if either differs unless it is told on the command line that the
change is intended. No second declaration file is introduced, because the invariant
that matters — the committed asset is the deployed asset — is exactly what makes the
comparison meaningful, and a separate list of expected components would be a second
thing to keep in step. The first export has nothing to compare against and writes the
baseline; from the second onwards, registering or unregistering an Isabelle component
is a loud failure rather than a quietly differently-named namespace.

### 8.3 Display cleaning

```python
def clean_for_display(expr):
    expr = repair_del(expr)          # §10.2; a no-op once the DB is repaired
    return expr.replace('\r\n', '\n').replace('\r', '\n')
```

The 835 CR occurrences affect display only, and search is unaffected — but for a
different reason than an earlier draft gave. That draft said `symbol_explode` folds
CR to LF and the tokenizer then discards the LF; D43 deleted `symbol_explode`, so
that route is gone. The conclusion survives on the simpler ground that `'\r'`
satisfies `isspace()`, so §5.2 discards it and it ends the run in progress exactly as
a newline or a space does. The `replace` above is therefore about what a card shows,
not about what matches.

## 9. The front end — phase two (D32)

This section records the design that was agreed, so that it does not have to be
re-derived later. It was written under D20, which deferred the web application
outright; **D20 is superseded by D32**, which lifts the deferral and stages the work
instead — the whole data side first (§12.2 steps 1-5), the interface after. So
nothing here is to be built until phase one's export answers queries correctly, but
this is scheduled work rather than shelved work, and its design is settled to
D22/D26/D29/D30 with a mockup at `site/design/IsaSearch.dc.html`. The authoritative
source for every visitor-facing string is `site/COPY.md`, never this section.

A reader working on the backend can skip to §11; §10 is a four-line pointer into the
companion file.


### 9.1 Layout

One prominent box for the semantic query, plus a collapsible panel for the
syntactic filters: the five panels of D22 — `Entity Name`, `Expression`,
`Theory Name`, `All`, `Kind` — where the first three and `All` are repeatable
lists of single-line conditions, each condition carrying its own
`contains`/`excludes` toggle, and `Kind` is a chip group. An inline prefix
syntax
(`sorted_wrt -inductive theory:HOL-Library`) is offered as a shortcut, and the
parse result is echoed back into the structured fields so the user can see how
it was understood.

### 9.2 A required piece of user education

`ContainsTokenSequence` is **literal adjacent matching, not pattern matching**.
Users type a pattern, expect Isabelle pattern semantics, and conclude the site is
broken.

**The measurement, corrected.** An earlier draft of this subsection said `?P ⟹ ?Q`
returns 1 document. It returns **60** (D37, and the companion's §15.1 table), because
`P` and `Q` really are common variable names and D4 discards the `?` that would have
distinguished them. The example that makes the point honestly is
**`?n + ?m = ?m + ?n`, which returns 0** while commutativity of addition is certainly
in the index — the condition fails for exactly one reason, that the variable names
differ, and nothing else has to be explained. `?a + ?b = ?b + ?a` returns 15, one of
them `Groups.ab_semigroup_add_class.add.commute`, which is the pair that makes the
reason visible. `site/COPY.md` is built on that pair and is authoritative for the
wording; do not rebuild the empty state from this paragraph.

Therefore: never label this feature "pattern"; and when a syntactic filter
returns nothing, say explicitly that the filter is literal and does not support
variable placeholders.

### 9.2b The theory filter means two things, and says so (D15)

Per D14 the theory filter matches a name-addressed entity's declaring theory
but a theorem-alike entity's constituent theories. The interface states this
rather than hiding it. One sentence carries it, shown beside the field:

> **Theory Name** — matches an entity's **associated theories**: for constants,
> types, classes, locales and methods, the theory that declares them; for
> theorems, the theories of the constants their statement uses.

The field's own label is **`Theory Name`**, fixed by D22, which records that the bare
`Theory` was argued for and rejected — an earlier draft of this subsection used the
bare form in both the label and the sentence. The plural sense is carried by this
sentence, not by the label.

Nothing about this is offered as an option or a mode: the alternatives were
measured and are worse (§7.2).

### 9.3 Fonts

`⟹ ⟦ ⟧ 𝔍 ℭ ₁` render as tofu in most default fonts. The Isabelle
distribution's `IsabelleDejaVu` family must be subsetted to WOFF2 and embedded.
This is easy to miss because a developer's own machine has the fonts installed.

Input needs three routes: pasting Unicode; typing the ASCII escape
`\<Longrightarrow>` (already handled by the tokenizer); and live abbreviation
replacement (`==>` → `⟹`).

**Correction, 2026-08-14.** The abbreviations are **not** in a file named
`etc/abbrevs` — no such file exists in the distribution. They are the `abbrev:`
fields of `etc/symbols` itself, e.g. line 189
`\<Longrightarrow>  code: 0x0027f9  group: arrow  abbrev: .>  abbrev: ==>`.
So the export emits them from the table it already reads, and the site needs no
second asset.

The distinction matters for the copy, and §13b's draft got it wrong: the
tokenizer does **not** convert `==>`. Measured — `tokenize('==>')` returns
`['==>']`, an ASCII symbolic token, which matches `⟹` nowhere. Only the escape
`\<Longrightarrow>` is converted, by `unicode_of_ascii` in step 2. `==>` works
solely because the input control replaces the text in the box before the
condition is ever sent. The interface may therefore say *"the box turns `==>`
into `⟹` while you type"*; it may never say that `==>` **is** `⟹`. A second
consequence: an abbreviation with more than one expansion (`.>` and `<.` each
serve four or more arrows) cannot be replaced without asking, so live
replacement covers the unambiguous abbreviations only.

### 9.4 Entity pages

One server-rendered page per **`group`** at a stable URL, carrying name, kinds,
theory, expression, interpretation, source link, and a "related entities" block
computed from the ten nearest vectors. The related block is not decoration: it is
what keeps these pages from being classed as thin content.

**The page identity is `group`, not the site document**, and an earlier draft of D9
and of this subsection said "one per site document". Under D5 as reversed there is
one site document per *record*, and cross-kind duplicates — the same
`(name, entity expression)` recorded once as a `Theorem` and again as an
`Introduction rule` — are several records. They collapse into one card after ranking,
and the thing that card links to is one page. §6.1 already says so: `group` is "the
identity of the entity page (§9.4) and the key the response collapses on".

Search results must link to these URLs from day one even if the pages ship
later, so the URL scheme never has to change and no inbound links are lost.

Sitemaps must be sharded (50 k URLs each, so ≥28 shards plus an index). Crawl budget
will not cover ~1.36 M pages on a new site, so the sitemap is ordered rather than
arbitrary: **the distribution's own sessions first, then AFP, and inside each the
206,010 name-addressed entities before the theorem-alike ones**, since a
name-addressed entity carries a name a person might actually search for. An earlier
draft said "prioritise HOL and widely-used AFP entries", which is not actionable —
no record field records use, and this plan defines no popularity signal. If one is
ever wanted the only honest source is the site's own request log, which does not
exist before launch.

### 9.5 Rendering

Server-rendered from the Worker rather than a client-side application: entity
pages need it for indexing, it works without JavaScript, and the page structure
is simple enough that a framework earns nothing.

## 10. Repairing U+007F — done

Done, and moved to `SEMANTIC_SEARCH_SITE_PLAN_DONE.md` §10, taking §10.1 (the root cause)
and §10.2 (the repair) with it — citations to either resolve there. Zero of 1,362,343 records still carry U+007F, measured
2026-08-12. §5.1's pipeline step 2 is retained and is now a no-op on stored text.

## 11. Operations

### 11.1 Abuse protection (D35)

Not a spend control — D28 cancelled the budget. This exists because an
anonymous public endpoint that spends someone else's API credit needs a bound
against hammering and runaway clients. Two layers are built; a third is
specified but deliberately not built.

**Layer 1 — one Cloudflare edge rate limiting rule, per IP, 5 requests per
10 seconds.** The zone stays on the **Free** plan, which includes exactly one
rule, counting by `ip.src`, with a 10-second period — all this layer needs.
Excess requests are rejected at the edge and never reach the Worker.

**Layer 2 — a per-IP daily counter in Workers KV, 1,000 requests per UTC day.**
Key `rl:<hash of the IP>:<YYYY-MM-DD>`, TTL ~26 h so it expires itself. The IP
is stored **hashed with a rotating salt, never in the clear** — the gate needs
the equivalence "same client", not the address. On trip: 429 with `Retry-After`
set to UTC midnight.

**Layer 1 is what makes layer 2 work, and must not be removed as redundant.**
KV limits writes to a *single key* to 1 per second, on every plan, and one IP's
counter is one key. Without layer 1 a client hammering at 10 requests/second
would have most of its increments dropped and the counter would under-count
precisely against the behaviour it exists to catch. Layer 1 caps the sustained
rate at 0.5 requests/second, comfortably under that limit. (A momentary burst
of 5 within one second can still exceed 1 write/second and lose an increment or
two; against a 1,000/day budget that is immaterial. The guarantee that matters
is on the sustained rate.)

**Layer 3 — a global gate, specified but not built.** A global counter cannot
live in KV: it is a single key and the site-wide rate would sit around 3
requests/second, straight into the same 1-write-per-second limit. It needs a
Durable Object holding a token bucket — refill 2.78 tokens/second (10,000/hour)
with a burst capacity, and a 429 when empty, never a fixed hourly quota that
can be exhausted early and leave the site dark for the rest of the hour. It is
**not built now** because layers 1 and 2 already require roughly 240 distinct
IPs to saturate that rate, which is a high enough bar for casual abuse, and
because it is the only piece here needing a new stateful component. Revisit from the
Worker's own telemetry (§11.2), not from speculation — which is why §11.2 requires
every 429 to be logged with the layer that produced it. An earlier draft pointed at
a "§11.4" that does not exist and never did.

**On a trip, every layer returns 429 with `Retry-After`** and an interface
message naming which limit was hit. There is **no degradation to BM25**: BM25
over machine-written English is a materially worse search, and serving a
plausible-looking second-rate result set to a user who cannot tell is worse
than an honest "too busy, try again" (D35). BM25 remains a normal leg of the
hybrid query (D29) — what is rejected is the *fallback mode*, not the feature.

**Recurring cost of all of this**: Workers Paid at $5/month, which KV writes
require and which includes 1 M writes and 10 M reads per month — enough for
~33,000 searches a day before any overage. The Cloudflare zone itself stays
free. Cloudflare Pro ($20/mo) and Business ($200/mo) buy nothing this design
needs; the only thing that would ever justify Business is
`cf.unique_visitor_id`, which distinguishes visitors behind one NAT address and
would matter if university networks turn out to be widely throttled as one
client. Enterprise, whose only relevant advantage is a 3,600-second counting
period, is reported to start around $3,000–5,000/month and is out of the
question.

**Two things unverified, with the procedure for each.** Neither is settled by
reading more documentation.

1. *Does the Free plan's single rate-limiting rule accept a threshold of 5?* The
   documentation states the period and the characteristic and not the permitted
   thresholds. **Procedure:** create the rule in the zone's Security → WAF →
   Rate limiting rules with `ip.src`, period 10 s, threshold 5, and read back what
   the dashboard saved. If 5 is rejected, take the lowest accepted value and redo
   layer 1's arithmetic — the number that has to survive is the sustained rate
   staying under KV's 1 write per second per key.
2. *What request allowance does Workers Paid include?* The figure quoted above —
   1 M KV writes and 10 M reads a month, enough for ~33,000 searches a day —
   comes from Cloudflare's published plan comparison and is **not** verified against
   a live account. **Procedure:** subscribe, then read the Workers → Usage panel,
   which reports the included allowance and the overage rate for the account
   actually being billed. Until then treat the 33,000/day as an estimate.

A **query-embedding cache in Workers KV**, keyed on the normalised query
string, remains worth building: search traffic is strongly Zipf-distributed, so
it removes more Fireworks calls than any rate limit and cuts latency on a hit.
**Cloudflare Turnstile** stays in reserve if the two built layers prove
insufficient.

### 11.1b What it costs, measured against the published price lists (2026-08-13, recomputed 2026-08-19)

**This section is capacity information, not a constraint (D28).** It is here so
that a runaway is recognisable and so that a future decision about corpus size
or vector dtype can be taken with the numbers in view. No decision in this plan
is justified by it, and none may be reversed on its account.

**turbopuffer bills every query as if it read the whole namespace.** Not per
document scanned, not per byte actually touched — the FAQ's words are "data
queried is calculated as the actual size of the queried namespace or 1.28 GB,
whichever is greater". Three consequences that shape this design:

- **Per-search cost is proportional to corpus size**, not logarithmic in it.
  Every document added makes every future search dearer.
- **Filters are free and selectivity buys nothing.** A condition narrowing the
  candidate set to 500 documents still bills the full namespace. So D21's
  collapse to one array, and D22's `All` panel with its three-field `Or`, cost
  nothing on this meter — only on latency (§3.6).
- **The vector dimension is the dominant lever on price**, because the vectors
  are ~97 % of the namespace.

Rates: storage $0.33/GB-month; data queried $1/PB; data returned $0.05/GB;
writes $2/GB with a batch discount reaching 50 % at ~3.1 MB per batch; plan
floor $16/month. Enterprise adds a 35 % usage premium. Logical bytes are
billed, so index amplification is not passed through.

**Corrected 2026-08-19: the base and the returned-data term were both wrong.** This
subsection was computed on 1,241,679 site documents, which is the *merged* count from
the original D5 — and D5 was reversed on 2026-08-13, making it one document per
record, **1,362,343**. And the returned-data term was taken as ~20 KB where D29
measures a 200-result response at **~200 KB**, an order of magnitude, which made the
per-search total $0.000022 against D29's internally consistent $0.000031. Everything
below is recomputed on the reversed D5 and D29's payload.

At 1,362,343 site documents × 4096 dimensions × 4 bytes the vectors are 22.32 GB and
the namespace ~23 GB. At D31's f16 — which is what actually ships — they are 11.16 GB
and the namespace ~11.5 GB:

```
f32, for comparison only
per search   23 GB queried  $0.000023   +  ~200 KB returned  $0.000010  =  $0.000033
per day      10 k searches $0.33   100 k $3.30   1 M $33.00
per month    storage $7.59; initial load at 4 B/dim for writes, 22.3 GB x $2 = $45, or $22 batched

f16, as shipped (D31)
per search   11.5 GB queried $0.0000115 +  ~200 KB returned  $0.000010  =  $0.0000215
per day      10 k searches $0.22   100 k $2.15   1 M $21.50
per month    storage $3.80; the one-off load is unchanged at ~$45 / ~$22 batched,
             because turbopuffer counts 4 bytes per dimension for writes whatever the dtype
```

Two things change qualitatively. The queried term is no longer 95 % of a search: at
f16 it is 53 %, and **the response payload is now the other half**, which is a reason
to keep D29's 200-result bound and no reason to shrink the vector further. And the
$16 monthly floor absorbs everything below roughly **24,000 searches a day at f16**
(about 16,000 at f32), so marginal searches are free until then — the earlier
"13,600 a day" inherited both errors.

**Reducing the vector changes this by up to 16×**, because namespace size *is*
the per-query price. turbopuffer counts f16 at 2 bytes per dimension and i8 at
1 (for storage and queries; writes still count 4). Recomputed on 1,362,343
documents, and showing the **queried** term alone so the four rows are comparable —
the ~$0.000010 returned-data term is the same in every row and does not shrink with
the vector:

```
                        namespace   queried, per M searches   storage / month
4096-d f32               23.00 GB    $23.00                    $7.59
4096-d f16 (D31, ships)  11.50 GB    $11.50                    $3.80
1024-d f32                5.75 GB     $5.75                    $1.90
1024-d i8                 1.44 GB     $1.44                    $0.48
```

The namespace column is the vectors plus 3 %, which is the ratio the two 4096-d rows
were measured at; the vectors themselves are 22.32, 11.16, 5.58 and 1.40 GB.

The 1.28 GB per-query floor puts a hard bottom of $1.28 per million searches on
this workload however small the vectors get. **Whether recall survives any of
this is unevaluated — the figures above are money only.** Note the local vector
store already holds Q1.15 int16, so f16 is a format change rather than a new
loss of precision, while dimension reduction is not. This is Q14.

**Compared with the query embedding, turbopuffer is the larger cost at every
volume**, not just at scale: Fireworks costs $3–13 per million searches against
turbopuffer's $21.50 at f16. The two cross over only if the namespace shrinks below
about 13 GB, which at f16 it nearly has — so at the shipped dtype the two backends
cost within a factor of two of each other rather than one dominating.

**The BM25 degradation path this paragraph used to argue about no longer exists.**
D35 deleted it on 2026-08-14: every limit returns 429, and there is no fallback mode.
§6.5 and §11.1 both record the deletion and this subsection did not. What the
arithmetic *would* have shown, had the path survived, is that falling back to BM25
saves the smaller half of the bill and not most of it, because the turbopuffer query
is charged in full either way — which is one more reason the deletion was right.
BM25 remains a normal leg of the hybrid query (D29); what is gone is the fallback.

turbopuffer publishes **no spend cap and no budget alert**, so if a hard limit were
ever wanted this application would have to enforce it, metering itself on the
`billing` object every query response carries (`billable_logical_bytes_queried`,
`billable_logical_bytes_returned`). **None is wanted: D28 cancelled the spend cap and
no component enforces one.** What the `billing` object is for here is visibility —
§11.2 requires logging it so that a runaway is noticed, which is a different thing
from a limit.

Sources: turbopuffer's pricing page and pricing changelog, and the query,
warm-cache, pinning, regions and limits docs. The per-unit rates are not prose
on the pricing page — they live in the cost calculator's own constants — so
they are turbopuffer's numbers but not quotable at a finance department.

### 11.2 Cache warming, and why there is none (D27)

`GET /v1/namespaces/:ns/hint_cache_warm` looks free and is not. The warm-cache
doc: free "if turbopuffer is ready to serve requests with low latency, or it is
already getting the namespace ready" — otherwise "this request is billed as a
query that returns zero rows", and a zero-row query still pays the full
namespace charge, $0.0000115 here at f16 (§11.1b). The mechanism therefore costs a full
search exactly when it would have helped, and nothing when it would not. D27
drops it.

What is worth keeping from this section: **log `cache_temperature` and
`cache_hit_ratio` from every query response**, so a real regression is visible
rather than inferred, and log the `billing` object too. turbopuffer publishes no spend cap, and neither
does this application (D28) — the log is how a runaway becomes visible, not how it is
stopped (§11.1b).

**And log every 429 with the layer that produced it** (edge rule, KV daily counter,
or the unbuilt global bucket). §11.1 defers layer 3 explicitly "from the Worker's own
telemetry, not from speculation", and that decision cannot be taken without knowing
how often layers 1 and 2 actually trip and against how many distinct clients. This is
the only telemetry any decision in this plan is waiting on.

### 11.3 Disclosure

The interpretations are LLM-generated. The site must say so plainly; readers
will otherwise treat them as authoritative documentation.

## 12. Repository layout and implementation order

### 12.1 Layout (D16)

The site lives in this repository because the tokenizer has two
implementations that must not drift (§5.5); one repository and one CI run is
what enforces that, and version-number coordination across repositories would
not.

Planned, and not yet built:

```
Isabelle_Semantic_Embedding/
  isabelle_tokenizer.py   the tokenizer (§5), Python side
  site_export.py          the site export (§8), a subcommand of isabelle-semantics
site/
  worker/                 Cloudflare Worker: search API, embedding cache, rate
                          limits, entity page rendering
  pages/                  static assets: subsetted IsabelleDejaVu, styles, scripts
  tokenizer/              the JavaScript port + the shared test-vector runner
```

Already in the repository, all of it cited as load-bearing elsewhere in this plan and
none of it listed here before 2026-08-19:

```
site/COPY.md              the authoritative source of every visitor-facing string
                          (§13b) — the mockup follows it, never the reverse
site/DESIGN_PROMPT.md     the designer brief
site/design/              the delivered mockup, IsaSearch.dc.html, plus the
                          generated Claude Design runtime, which is not edited
site/prototype/           the measured tokenizer prototype and corpus_probe.py
                          (§16.1) — PRE-D43, see there for what that costs
site/review/              the evidence of the §5 review §16.7 required: the brief,
                          the frozen bar, four lens reports and the rebuttal
```

**Two plans this document cites live at the MLML checkout root, not beside it**, and
the citation convention here gives no path, so they read as though they were
neighbours: `BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md` (D33) and
`THEORY_HASH_REKEY_PLAN.md` (D33's G1). Everything else this plan cites —
`ENTITY_POSITION_PLAN.md`, `THEORY_HASH_REGISTRY_PLAN.md`,
`DYNAMIC_MEMBER_NAMING_PLAN.md`, `VECTOR_INVALIDATION_PLAN.md`,
`SEMANTIC_DB_LAYERED_PLAN.md` and the companion
`SEMANTIC_SEARCH_SITE_PLAN_DONE.md` — is in this directory.

The export belongs to the Python package, not to `site/`: it reads LMDB, reuses
the Python tokenizer, and should ship in the conda package so that others can
export their own database.

Verified safe: `conda/recipe.yaml`'s build script installs an **explicit
allow-list** (`ROOT`, a few `.thy` files, `etc/`, `lib/`, `src/`, `Tools/`), so
`site/` cannot leak into the package. It is still copied into the build sandbox
by `source: path: ../`, so `node_modules/` and similar must be git-ignored.

### 12.2 Order, and what actually blocks what

Steps 1-5 are phase one and 6 is phase two (D32). Within phase one the order is
not a preference — three prerequisites feed the export, and none of them is
this plan's work.

**Prerequisite A — the key repair (D33). DONE, 2026-08-18.**
`BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN` rebuilt the store under corrected keys, and
`THEORY_HASH_REKEY_PLAN.md`'s migration ran with it, so a persistent theory's hash now
folds in its session-qualified long name. It had to run **first** because any export
taken before it would publish wrong theory data under document ids the rebuild then
changes, taking every permanent entity-page URL (D25) with them — that risk is now past.
Verified read-only on `cslh19`: `fsck` passes every invariant over 1,343,793 records,
including the XOR check the original defect used to pass silently; `orphans` reports 84
records against the defect's original 234,398. See D33 for what was not re-verified.

**Prerequisite B — the theory-hash registry**, per `THEORY_HASH_REGISTRY_PLAN.md`.
A name-addressed entity's declaring theory lives as a 16-byte hash in its key and
is unreadable without the table. Two things fail without it: the `Theory Name`
filter for the 206,010 name-addressed records (15.1 %), and **D24's scope test**,
which is exactly the declaring theory for those records — so the export cannot
even decide what to publish.

**Prerequisite C — the published snapshot carries the entity positions.** One
artefact, and the diagram below used to label it differently from this paragraph. The
backfill is done on `cslh19` (80.2 %) but the Hugging Face snapshot was packaged
before it finished, so this machine holds 8,306. The store half is therefore already
in hand, including its dependency on A — positions are stored against keys, so they
had to survive the rebuild, and they did. **What remains is the republish**, after
which every machine that syncs gets the positions.

```
step 3  FREEZE THE TOKENIZER          <-- the live work; needs none of A, B, C
   |
   |    (it needs the symbol table and the distribution, nothing from the store)
   |
   |    A  key repair                              DONE 2026-08-18
   |          |
   |          +-- B  theory-hash registry published        outstanding
   |          |        the Theory Name filter for the 206,010 name-addressed
   |          |        records, AND D24's scope test for them — so without B the
   |          |        export cannot even decide what to publish
   |          |
   |          +-- C  positions in the published snapshot   outstanding
   |                   |
   |                   +--> snapshot republished from cslh19
   |                                |
   +--------------------------------+--> step 4  site export, one full namespace
                                             |     (runs the Python tokenizer and
                                             |      emits the asset that names the
                                             |      namespace, §8.2 — hence the
                                             |      dependency on step 3)
                                             +--> step 5  Worker: search API,
                                                    |      embedding cache, limits
                                                    +--> step 6  front end, phase two
```

1. ~~Repair U+007F (§10).~~ **Done** — zero of 1,362,343 records still carry
   U+007F, measured 2026-08-12.
2. Prerequisites A, B and C above. **A is done; B and C are outstanding and owned
   outside this plan.**
3. **Freeze the tokenizer**: Python implementation, JavaScript port, the shipped
   asset (D45, D46), the test-vector file with its synthetic cases, and the CI gate
   (§5.5, §16). **This never depended on A, B or C** — it needs the symbol table and
   the distribution, and although its test vectors are sampled from real entity
   expressions, the repair changed keys and not text. It remains the part of phase one
   that can proceed now, and it is where the work is.
4. Build the site export (§8) and load one full namespace. **Blocked on B, C and
   step 3** — the export runs the Python tokenizer and emits the asset whose digest
   names the namespace (§8.2).
5. Worker: search API, embedding cache, rate limits (§11.1). Blocked on 4.
6. Front end: search page, then entity pages. Phase two (D32).

The interface copy and the mockup are **done**, and this paragraph used to offer them
as available work: `site/COPY.md` reached draft 3 on 2026-08-14 after three rounds of
reader testing, `site/design/IsaSearch.dc.html` was brought in line with it, and both
are committed. Anything that reopens them is a change to `COPY.md` first (§13b). Note
also that the decision range is now **D21-D46**, not the D21-D41 this paragraph used
to name.

**Draft 3 correction.** Step 2 used to read "Build the complete hash-to-name
table (§7.3) - light, independent", meaning an Isabelle enumeration run. §7.3
now shows the table already exists and is already complete; what it needs is to
be *published*, which is a different job in a different plan.

## 13. Open questions

Q1, Q2 and Q4 of draft 1 are settled — see D19, D18 and D13 respectively.

- ~~Q3~~ — **settled, and the settlement has moved twice.** The rate limit is
  **D35's**: 5 requests per IP per 10 seconds at the Cloudflare edge, plus 1,000 per
  IP per UTC day in Workers KV, plus an unbuilt global bucket at 10,000/hour (§11.1).
  This entry said "12 requests per IP per minute", which was the answer before D35
  and is superseded. The daily *spend* cap is cancelled (D28), and D28 therefore
  contains no query-count figure — an earlier version of this entry attributed
  "~150,000" to it. Arithmetic retained purely as capacity information, since a
  per-IP limit does nothing against distributed abuse: Fireworks prices
  Qwen3-Embedding-8B at **$0.10 per million tokens** (its own tier; ≤150 M-parameter
  models are $0.008 and 150–350 M are $0.016), and a query costs 6 tokens when short.
  At D29's **8,000-character query cap** that is roughly 2,000 tokens, i.e. ~$0.0002 a
  search — the 512-character cap is D29's cap on a single *filter condition*, which
  is not what gets embedded, and an earlier version of this entry costed the query at
  it (~130 tokens). Whatever the figure, the arithmetic to do is not Fireworks alone:
  the query-embedding cache protects Fireworks only, every search hits turbopuffer
  whether or not the embedding was cached, and at f16 the two are within a factor of
  two of each other (§11.1b).
- ~~Q5~~ — **withdrawn, and it was never a real question.** It asked whether a
  second search field for whole-word matching was wanted, on the stated ground
  that "the syntactic filter is substring matching: searching `set` also hits
  `insert` and `setsum`". That ground was false in both draft-1 and draft-2
  designs. `insert` is a single token whose only subtoken is `insert`, so
  neither `expr_tokens` nor `expr_subtokens` ever matched `set` inside it —
  which is exactly what D6 says. Whole-word matching was not missing; it was
  the default. The real question hiding behind Q5 was how a condition should be
  routed between the two mechanisms, and D21 answers it by deleting one of them.
- ~~Q6~~ — settled: the concept is **the associated theories** (§1), and the
  notice required by D15 is drafted in §9.2b. The interface language it is
  finally written in is part of Q7.
- ~~Q7~~ — **settled by D30**: `isasearch`, English, and the design's own
  disclosure sentence.
- ~~Q8~~ — **settled by D26**: a theorem card shows no theory line at all
  unless a theory condition is active.
- ~~Q9~~ — **settled by D25**: they ship in the first release, and cards link
  to them.
- ~~Q10~~ — **settled by D24**: only entities living entirely inside AFP and
  the distribution; phi-system and the why3/NTP4VC material are both out.
- ~~Q14~~ — **settled by D31**: f16 at 4096 dimensions. One task falls out of
  it — measure the ranking change from Q1.15 int16 to f16 on real vectors
  before the export publishes.
- ~~Q11~~ — **settled by D29**, every part of it.
- ~~Q12~~ — **settled by D22**: the `Entity Name` panel reaches
  `name_subtokens`, so it stays in the export.
- ~~Q13~~ — **settled by D23**: the theory filter matches subtokens like the
  other two, and the field is `theory_subtokens`.

## 13b. Reader testing of the interface copy — done

Three rounds, drafts 1 through 3, moved to `SEMANTIC_SEARCH_SITE_PLAN_DONE.md` §13b, where
the citations elsewhere in this document resolve. What
each round changed, and what was rejected and why, is in `site/COPY.md` §12; that is the
list not to re-raise. `site/COPY.md` is the authoritative source of every visitor-facing
string, and `site/design/IsaSearch.dc.html` follows it, never the reverse.

## 14. Considered and rejected

Do not re-raise these without new evidence.

### 14.1 Cloudflare Vectorize
Maximum 1536 dimensions against our 4096; eight comparison operators with a
64-byte indexed prefix and no substring matching; and, decisively, **no vector
ID allow-list**, so a mask computed elsewhere cannot be handed to it. Filtering
is a genuine pre-filter, which does not help when the filter is inexpressible.

### 14.2 First-order pattern matching
Matching a user-written pattern requires parsing it, which requires Isabelle's
parser and a theory context (notation is theory-local). That means a resident
Isabelle process in the query path — the single heaviest operational burden in
any design considered. Dropping it is what makes the site serverless. The
record codec is positional tail-append, so `term_skel` / `type_skel` fields can
be added later without redesign.

### 14.3 Self-hosting on the VPS
Measured on `sg.qiyuan.me`: 2 vCPU that are **two hyperthreads of one physical
core** — two-thread aggregate memory bandwidth 12.44 GB/s against 12.28 GB/s for
one thread, i.e. **no scaling**. Kernels: sequential read 29.6 GB/s,
XOR+popcount 8.55 GB/s (no AVX512_VPOPCNTDQ), Q1.15 dot product 11.55 GB/s.
Disk is network-attached EBS: 131 MB/s sequential, **7.3 MB/s random 4 K
(≈1,870 IOPS)**.

Consequences: a full-precision scan of 11.1 GB takes **85 s** from disk, 0.96 s
if resident — and 3.7 GB of RAM cannot hold it. Upgrading to 8 GB does not help
(11.1 GB still does not fit); 16 GB would, at 0.96 s per query, still too slow
to be interactive. A compressed two-stage design would work (binary coarse pass
693 MB at 81 ms), but requires operating a server. It also has one genuine
advantage turbopuffer lacks — a locally measured 47–85 ms full-corpus substring
scan over a 163 MB blob, which supports arbitrary mid-identifier substrings
(D6). Rejected on operational cost.

### 14.4 Qdrant Cloud
Native `HasIdCondition` is the cleanest allow-list of any service examined, but
it has no arbitrary substring filter (`MatchText` is tokenised full-text), so a
mask would have to be computed outside and shipped in. Third-party figures put
a suitable cluster at $120–200/month against turbopuffer's $16 minimum;
turbopuffer's own `Glob`/`Regex` and `["id","In",…]` cover both needs anyway.

### 14.5 Encoding token boundaries into a string
An earlier design normalised to a string with a private-use-area sentinel at
every token boundary, to be matched with `Glob`. The adversarial review found
it fatal: anchoring the query at both ends broke every partial-identifier
query. It also cost 187 % of the original size in UTF-8, brushed the 4 KiB
filterable limit, and inherited `globset`'s metacharacter problems — `?` alone
is 6.2 % of all characters in the corpus, and an unclosed `[` or `{` makes the
whole query **error** rather than return nothing. Token arrays dissolve all of
it: boundaries are structural, and no character is special.

### 14.6 Keeping two expression mechanisms, and collapsing to the wrong one

Two alternatives were weighed against D21 on 2026-08-12.

**Keeping both mechanisms and routing between them.** Draft 2 did this without
ever deciding the routing rule. Three routings were put to the user on
2026-08-09 — a per-condition exact/loose toggle, the union of both, and "exact
by default, fall back to word matching when the whole query returns nothing" —
and none was answered before the front end was deferred. Each has a defect. The
toggle makes every user learn a distinction before they can use the control.
The union reintroduces the noise the subtoken level was supposed to be
quarantined from: `f x` becomes `f` and `x` anywhere, and those are the two
commonest variable names in the corpus. The fallback has a structural blind
spot — it fires only on zero results, so a query that happens to score three
exact hits never reaches the several hundred word-level hits the user wanted.
D21 removes the question rather than answering it.

**Collapsing to `ContainsAllTokens` instead.** This was the user's first
proposal and the literal meaning of "replace". Rejected on two measured
grounds. First, the old subtoken rule discards every fragment with no
alphanumeric character, so every operator and bracket vanishes from the index:
`⟹` (42 % of documents), `=` (50 %), `⟦`/`⟧` (25 %) and `::` (9.89 %) would all
become unfilterable — those four are over §3.3's 230,944-document namespace, which is
where the D21 experiments were run, and an `excludes` on any of them would reduce to the empty
list. Two of the three example conditions written into the design brief
(`-->`, `⟦?P; ?Q⟧`) could not be expressed at all. Second, `ContainsAllTokens`
is unordered and non-adjacent, which is not a looser syntactic filter but a
different thing: `f x` would match any expression containing an `f` and an `x`
anywhere, i.e. very nearly the whole corpus. Adjacency is what makes the filter
syntactic. Keeping `ContainsTokenSequence` and narrowing the discard rule
instead retains both properties at the cost of a rule that names its separators
explicitly.

Note a defect the narrowed rule also fixes. With operators discarded, `f x + y`
has subtokens `['f','x','y']`, so an adjacency query for `x y` would match
across a `+` that sits between them in the real expression. Keeping the
operator makes `['f','x','+','y']` and the false match disappears.

### 14.7 Making `'` a separator, so a type variable stops splitting

Raised 2026-08-18, rejected the same day. Under §5.2 a quasi-letter may continue an
identifier but not begin one, so Isabelle's type variable `'a` is two tokens and
the bare `'` survives into the subtoken array — measured, **179,860 expressions
(13.20 %)** carry one, **169,005** of them in the array interior, where under
`ContainsTokenSequence` it breaks any run passing through it. That is three and a
half times commoner than the fallback-kept-token case (**3.81 %** over the whole
corpus, §5.4 — this said 3.71 %, which matches no denominator) that the 2026-08-14
review raised and its rebuttal round deleted, and no reviewer raised this one at
all.

The proposal was to put `'` in §5.4's separator class, so that `'a` and `a` index
alike. It was rejected on the argument that **the query it would fix is not a legal
Isabelle expression**. `set ⇒ a set` does not mean the same thing as `set ⇒ 'a
set`: in Isabelle's type syntax `a` names a type constructor and `'a` is a type
variable, and a visitor of this site is an Isabelle user who writes the second.
An earlier framing here — that the quote is punctuation the visitor does not think
of as content — was simply wrong; the quote is what makes it a type variable.

The property that makes the split harmless is that **the quote is visible on both
sides**: the card prints `?'a set ⇒ ?'a set`, and any legal expression the visitor
types carries the quote too, so both tokenize to the same stray `'` in the same
place and the run matches. It is unlike a folded subscript, where `x⇩1` indexes as
`x` and the visitor cannot see what to omit. A stray `'` costs a match only when
the visitor leaves out a character that is really there, which is a typo.

The cost of accepting the proposal was also concrete: `'` in the separator class
collapses every primed name, so `sorted'` and `sorted` become indistinguishable
across **158,120 expressions (11.61 %) and 47,768 names (3.51 %)**. (This read
150,679 and 41,554 / 3.05 % until 2026-08-19; re-measured that day, both were low,
while the 179,860 / 13.20 % and 169,005 in the same subsection reproduced to the
record. Counted precisely: a record is included when its subtoken array holds a
subtoken that contains a `'` **and is longer than one character** — that is, a primed
identifier rather than the stray bare quote the previous paragraph is about. The
earlier pair was reported without its counting rule, which is why it could not be
reproduced; state the rule with any figure that replaces it.) A third option — letting
a leading quote attach to the following identifier, as Isabelle's own lexer does —
was measured and buys nothing: the document holds `'a` either way, so a visitor
who omits the quote still fails to match.

## 15. Implementation handover, 2026-08-14 — superseded

Moved to `SEMANTIC_SEARCH_SITE_PLAN_DONE.md` §15. It is superseded by §16, which was
written at the next context boundary and says what changed; citations elsewhere to
§15.1, §15.3 and §15.4 resolve into that file. Its §15.1, the copy rewrite, is
complete, and its §15.4's two reviews have both been overtaken — the first has run and
its evidence is in `site/review/` (§16.7), and what is left unreviewed is D43-D46,
which postdate §15 entirely.

## 16. Tokenizer freeze — detailed handover, 2026-08-14

Written at a second context boundary, immediately before the tokenizer work
begins. §15 remains valid except where this section says otherwise. Everything
needed to start is here; nothing below should have to be recovered from the
conversation that produced it.

### 16.0 What changed since §15 was written

**§15.1, the copy rewrite, is complete.** `site/COPY.md` is at draft 3 and is
the authoritative source of every visitor-facing string.
`site/design/IsaSearch.dc.html` has been brought in line with it. Both are
committed. Do not re-derive copy from §9 of this plan or from the mockup — the
mockup follows `COPY.md`, never the reverse.

Three rounds of reader testing produced drafts 1→2→3; `COPY.md` §12 records what
each round changed and, more importantly, **what was rejected and why**. Do not
re-raise those.

**Corrections landed in this plan**, each in place:

- **D30 amended** by the user: the disclosure's second sentence loses the word
  `authoritative`.
- **D39's worked example corrected.** It gave
  `HOL-Analysis.Path_Connected.path_image_join` as an indexed name. No such name
  exists — an Isabelle fact's long name is qualified by the **theory base name**,
  never by the session, and no entity name in the store carries a session prefix.
  The export indexes the stored name unchanged. `theory_subtokens`, by contrast,
  **is** session-qualified. The two fields genuinely differ and the interface
  says so.
- **§9.3 corrected.** There is no `etc/abbrevs` file. The abbreviations are the
  `abbrev:` fields of `etc/symbols` (line 189 gives `\<Longrightarrow>` the
  abbreviation `==>`). **The tokenizer does not convert `==>`** — measured,
  `tokenize('==>')` returns `['==>']`. Only `\<…>` escapes are converted, by
  `unicode_of_ascii` in pipeline step 3. `==>` works solely because the input
  control rewrites the box before the condition is sent. This distinction is
  load-bearing for both the JavaScript port and the copy.
- **§6.5 corrected.** Its second reason for carrying BM25 — a degradation path
  when the embedding budget is exhausted — was deleted by D35 and had been left
  in. Also recorded there: BM25 indexes **only `interpretation`**, not the name
  and not the expression.

**The prototype and the probe harness are in the repository**, no longer in a
scratchpad: `site/prototype/`, with a `README.md` saying what they are and when
`isabelle_tokenizer.py` replaces them. **They are pre-D43 and D43 postdates this
whole subsection** — §16.1 states exactly what that costs and what it does not.

**And the review §16.7 required has since run.** Its brief, its frozen bar, its four
lens reports and its rebuttal are committed under `site/review/`, with a `README.md`
saying which numbers in it were superseded on 2026-08-17. §16.7 below is kept in the
present tense because it records what the review was asked and why; read it as the
brief that was given, not as work outstanding.

### 16.1 The artefacts, and what each is for

```
site/prototype/subtoken_rule.py       the settled separator class + subtokens(), with the fallback clause
site/prototype/tokenize_prototype.py  tokenize(), plus the superseded subtoken variants the measurements compared
site/prototype/corpus_probe.py        counts how many entities a condition matches, on the real corpus
site/prototype/README.md              what these are; delete none of them until the CI gate is green
```

`corpus_probe.py` reproduces every match count quoted in this plan and in
`COPY.md`. Verified from its committed location on 2026-08-14 and again on 2026-08-19:
`?n + ?m = ?m + ?n` → 0, `?a + ?b = ?b + ?a` → 15, in 25 s over 1,362,096 records. It
resolves `ISABELLE_HOME` and the package paths relative to itself, so it runs from
anywhere. **Use it rather than writing a new probe**; a differently-written probe
is a second implementation of the matching rule and will disagree eventually.

**These files implement the pre-D43 rule, and here is exactly what that costs.**
`tokenize_prototype.py` calls `symbol_explode`, which D43 deleted, and its
`_is_letter` unions in the `letter`/`greek` groups of `etc/symbols`, which §5.2 says
are not consulted. Both were measured on 2026-08-19:

- The `symbol_explode` difference is **exactly the 3,135 records D43 names**. The two
  definitions agree on the other 1,358,961 expressions, element for element. So no
  corpus figure in this plan is at risk from the prototype's age **unless it is one of
  those 3,135 records** — and none of the quoted figures is.
- The letter-group difference is **nothing at all**: all 190 group members satisfy
  `isalpha()`, and every one has a code point that step 3 substitutes before token
  formation sees it (§5.2).
- §16.2's 32 cases and §5.3's 11 relations were re-run under **both** definitions,
  with **zero mismatches under either**. Neither table is prototype-stale and neither
  needs re-deriving.

So the prototype remains usable as the measuring instrument for match counts, which is
what `corpus_probe.py` is for, and it is **not** a specification of the tokenizer.
Where it and §5 disagree, §5 wins; §16.3 step 1 says how the production
implementation is accepted, and it is not by agreeing with these files.

### 16.2 The facts a correct implementation must reproduce

Every line below was measured on 2026-08-14 with the prototype. They are the
seed of the test-vector file (§16.5) and the acceptance criteria for the port.
`→` gives the **subtokens**, which is the only level that is indexed (D21).

The separator class is **99 characters**, and each third of it comes from somewhere
different (§5.4): `_` and `.` are **ASCII literals in the rule itself**; the seven
control symbols `⇩⇧⇘⇙⇗⇖❙` are **read from a symbols file** by name; and the 90
rendered sub/superscript characters are what `SUBSUP_TRANS_TABLE` produces from `⇩`
and `⇧` — a **hand-maintained** 142-entry dict in `Isabelle_RPC_Host/unicode.py`. No
symbol file carries folding information of any kind, so the fold table has to ship in
the asset (D45). An earlier draft of this paragraph said nine of the 99 come from
`etc/symbols`, which over-counts by two: `_` and `.` are not in any symbols file.

```
'sorted_wrt R ?xs'            → ['sorted','wrt','R','xs']
'Kelly_1_39 ?C ?T ?a'         → ['Kelly','1','39','C','T','a']
'Stirling_Formula.c = ln (2*pi)/2'
                              → ['Stirling','Formula','c','=','ln','(','2','*','pi',')','/','2']
'f x + y'                     → ['f','x','+','y']
'x y'                         → ['x','y']
'_wrt'                        → ['wrt']            ← a leading separator vanishes
'F'                           → ['F']
'\<Longrightarrow>'           → ['⟹']              ← escape converted in step 3
'::'                          → ['::']             ← ASCII-symbolic run stays one token
'-->'                         → ['-->']
'==>'                         → ['==>']            ← NOT ⟹; see §16.0
'x\<^sub>i + y\<^sup>T'      → ['x','+','y']      ← folded subscripts are separators
'f\<^bsub>i\<^esub> = g'     → ['f','i','=','g']  ← bracketed sub/superscript controls likewise
'\<^bold>x \<^bold>('        → ['𝐱','(']          ← bold folds into the letter; a stranded ❙ vanishes
'[x]\<^sup>c\<^sup>e'        → ['[','x',']','ᶜᵉ'] ← THE FALLBACK CLAUSE, see below
'f\<^sub>1'                  → ['f']
'a?b'                         → ['a','b']          ← `?` divides as well as vanishing
'?a + ?b' ≡ '?a+?b' ≡ 'a+b'  → ['a','+','b']      ← spacing does not change these; but whitespace IS a boundary (§5.2)
'HOL-Analysis.Path_Connected.path_image_join'
                              → ['HOL','-','Analysis','Path','Connected','path','image','join']
'Path_Connected.path_image_join'
                              → ['Path','Connected','path','image','join']
"f'"                          → ["f'"]             ← `'` is a quasi-letter, not a separator
'x-y'                         → ['x','-','y']
'%x. x'                       → ['%','x','x']      ← `%` is not converted to λ by the tokenizer
'_'  '.'  '?'  '   '  '???'  '_.'  '\<^sub>'   → [] (all seven)
```

**The fallback clause is the one piece of the rule that prose alone loses.**
Splitting a token on the separator class normally yields its parts; but a token
made **entirely** of rendered sub/superscript characters would yield nothing and
disappear. Such a token survives whole instead — which is why
`[x]\<^sup>c\<^sup>e` keeps `ᶜᵉ`. `subtoken_rule.py` implements it; §5.4 describes
it; any reimplementation that omits it passes most tests and silently drops a
class of real superscripted operators.

**Matching, for completeness** (this is §6.3, not the tokenizer, but the copy and
the tests depend on it): a condition matches when its subtokens appear as an
**adjacent, ordered run** — whole parts only. Measured: `sorted` matches
`sorted_wrt`; **`sort` does not**; `image_join` matches
`Path_Connected.path_image_join`; `join_path` does not. `COPY.md` §0 states this
for visitors and must not drift from it.

Corpus scale, for sizing anything: 1,362,343 records carry a name, 1,362,096
carry an expression, 1,362,163 are exportable (the difference is 180
`EXPERIENCE` records, which are not published).

### 16.3 Build order, with an acceptance test for each step

Do these in order. Each step is finished when its test passes, not before.

1. **`Isabelle_Semantic_Embedding/isabelle_tokenizer.py`** — the production
   Python implementation, lifted from `site/prototype/` and changed in **two**
   respects, not the one an earlier draft of this step claimed:
   **(i)** it reads its character classes and its two tables from the emitted asset
   (§16.4) instead of from Python built-ins and a live `Isabelle_RPC_Host` import; and
   **(ii)** it drops `symbol_explode` and iterates characters, per D43, and stops
   consulting the `letter`/`greek` groups of `etc/symbols`, per §5.2.

   *Accepted when* both of these hold:

   - It reproduces **every line of §16.2**, all 32 of them, and every relation in
     §5.3. Both tables have been re-run under the character-level definition with zero
     mismatches (§16.1), so this is a target that is known to be reachable.
   - Run over the whole corpus, its subtoken arrays **differ from the prototype's on
     exactly the 3,135 expressions D43 names and are identical on the other
     1,358,961**. Compare with a digest of the concatenated arrays per record, not by
     eyeballing samples, and check the differing set by name — the two AFP records
     `AbsCFCorrect.lemma6` and `AbsCFCorrect.contour_a_class.abs_cnt_initial` plus
     `Matrix.matrix` must be among the 17 that lose a subtoken (§5.1), and the count of
     losses must be 17 and not 18.

   **An earlier draft of this step required the arrays to be *identical* to the
   prototype's for all 1,362,096 expressions.** That test cannot pass and must not be
   restored: by D43 the two definitions **must** differ, and gating the production
   tokenizer on agreeing with the rule §5 replaced would have accepted only an
   implementation that ignored D43.

2. **Asset emission in the export** (§16.4). *Accepted when* the asset loads
   standalone, with `Isabelle_RPC_Host` and `ISABELLE_HOME` unavailable, and step
   1's corpus comparison still passes.

3. **`site/tokenizer/`** — the JavaScript port, reading the same asset.
   *Accepted when* it passes the shared test-vector file (§16.5) with zero
   mismatches. It must not consult any JavaScript built-in for character
   classification — see D41 for the measured divergences that motivates this.

4. **The shared test-vector file** (§16.5). Build it before step 3 so the port
   has a target.

5. **The CI gate** (§16.6).

6. **`_truncate_to_token_limit`** — decide whether it is still needed. D29 caps
   the query in *characters*, so it probably is not. If not, do not move it out
   of `premise_selection.py`; leave it where it is and record that it is unused
   by the site. Note that `premise_selection.py` imports the symbol conversion as
   `_pretty_unicode` and wraps it rather than shadowing it, so nothing there is
   affected by the tokenizer landing.

**Two callers unpack the tokenizer's output by arity** and will break if the return
shape changes: `site/prototype/tokenize_prototype.py`'s own `__main__` block, and
`contrib/Isabelle_RPC/test_unicode.py`, which does
`symbols, reverse, _, _ = get_SYMBOLS_AND_REVERSED()`. An earlier note here said there
was exactly one. Neither is production code; both are in-repository and must be
updated in the same commit.

### 16.4 What the asset is, and why it exists (D41, D45, D46)

§5.2 defines the character classes by naming Python's `isalpha`, `isdigit`,
`isnumeric` and `isspace`. JavaScript has no equivalent, and the obvious
substitutes **disagree on real corpus characters** — this is measured, not
hypothetical:

- `²` (U+00B2, **3,955** occurrences over the whole corpus; an earlier draft said 640,
  which is the count over §3.3's 230,944-document test namespace) satisfies `isdigit()` but
  is Unicode category `No`, so `\p{Nd}` disagrees.
- U+001C–U+001F and U+0085 satisfy Python's `isspace()` but lie outside
  JavaScript's `\s`.
- U+FEFF is the reverse: inside `\s`, outside `isspace()`.

So the export emits, beside the symbol table, the explicit code-point sets for:
**letters** (`isalpha()` alone — the `letter`/`greek` groups of `etc/symbols` add nothing,
see §5.2), **the fold table** `SUBSUP_TRANS_TABLE` without which the port cannot fold at
all and cannot tell which 90 of the 99 separators are rendered characters,
**digits**, **quasi-letters** (`_` and `'`), **the separator class** (all 99
characters), and **the ASCII-symbolic set** (`! # $ % & * + - / : < = > @ \ ^ | ~`).
Neither implementation may consult a language built-in for any of these.

Emit the abbreviation table too, from the `abbrev:` fields of `etc/symbols` —
the interface needs it for live replacement in the condition box (§9.3), and it
is already being read. Note that an abbreviation with more than one expansion
(`.>` and `<.` each serve four or more arrows) cannot be replaced without
asking, so the interface uses the unambiguous ones only.

### 16.5 The test-vector file

At least **10,000 triples** — input, tokens, subtokens — sampled from real entity
expressions, **plus** synthetic cases, because real expressions cannot exercise
pipeline steps 1 and 3 at all. §3.4 establishes both halves of that, and the second
half needs care: the store is 100 % NFC, so step 1 is the identity on it; and step 3
is the identity **on the corpus that is published**, though not on the store as a
whole — since the loader began reading the table Isabelle actually presents it changes
1,056 stored expressions, and D24 excludes every one of them, all being phi-System.
So a port that omits NFC normalisation and escape conversion passes a
purely-real-data gate byte for byte, and then returns nothing for
`\<Longrightarrow>` — one of the two input routes §9.3 promises.

The synthetic cases must include, at minimum: every line of §16.2; ASCII-escaped
input; NFD input; sub/superscripts that have no fold entry; separator-only
conditions; the `²` and U+FEFF boundary characters; U+001C–U+001F and U+0085; a token
made entirely of rendered superscripts, for the fallback clause; an escape carrying a
**private-use** code point, which D44 requires to survive as its literal `\<name>`; an
escape sitting against an ASCII-symbolic character, which is D43's 17-record loss
pattern; an **astral** symbol value such as `\<S>` → `𝒮`, which is what catches a
JavaScript port iterating UTF-16 code units (§5.2); and an `Entity Name` condition
ending in `(_)` together with the same condition without it, for §5.1's step 0.

Pin the file's **encoding, ordering, count and digest**, so that "both
implementations passed" is itself a checkable claim rather than a report.

### 16.6 The CI gate

Runs both implementations against the test-vector file and fails on any
mismatch. It must also fail if the file's digest changes without the count
changing, which catches a vector file quietly edited to match a broken
implementation.

### 16.7 The review that ran first — and the one still owed

**This review has run: 2026-08-14, and its evidence is committed under
`site/review/`.** The brief, the bar (written and frozen before any finding existed),
the four lens reports and the rebuttal are all there, with a `README.md` saying which
of its figures were superseded on 2026-08-17 when the symbol-table loader was fixed.
29 findings went in, 19 survived merging, 9 were deleted, 10 stood, and the rebuttal
round found one more itself. Every change it caused is already in §5 and D41. Read
`site/review/` before reopening anything in §5; the rest of this subsection is the
brief that was given, kept because it records *why* the round was run that way.

**What is still owed is a review of D43-D46**, which postdate that round entirely and
are structural: D43 changed what the tokenizer is defined over, D45 made the asset a
single stamped file whose digest names the namespace, and D46 made the component set a
hard failure condition. §12.2's step 3 should not be called finished until they have
been through the same treatment.

Per §15.4, the round that ran was **a narrow adversarial review of §5 and D41, before
writing `isabelle_tokenizer.py`.** Small scope, deep agents. The specific question
asked, because it is the failure mode that a test-vector gate cannot catch:

> Find constructions where two implementations both pass the test vectors and
> still behave differently on real input.

It was given §5 in full, D41, D21, `site/prototype/`, and §16.2, and asked
specifically about: the fallback clause; the boundary between "letter" as `isalpha()`
and as an `etc/symbols` group membership; whether `symbol_explode` could produce a
symbol the separator class splits in half; and NFC stability of every symbol value.
**Three of those four are settled and must not be asked again**: the `etc/symbols`
groups are not consulted (§5.2, and all 190 members satisfy `isalpha()` anyway);
`symbol_explode` no longer exists (D43), so the question about it is about a deleted
step; and §3.4 now records the NFC measurement the question wanted checked — 0 of
1,362,096 expressions and 0 of 1,362,343 names are non-NFC. The fallback clause
survives as a live concern and §5.4 marks it as load-bearing.

**The questions to give the D43-D46 review instead**: whether the character-level rule
can cut a *converted* symbol's code point in half (it cannot — a code point is
atomic — but the JavaScript port iterating UTF-16 code units can, which is §5.2's
astral warning and is worth an adversary); whether the asset's digest can change
without any published document changing, and whether the export's failure on a
different component set can be bypassed by accident (D46, §8.2); and whether the 17
subtoken losses of D43 include anything that is not bare punctuation.

**Method fix, and it is not optional.** In the 2026-08-13 review the rebuttal
round deleted **none** of 35 findings, because the defender was told that killing
a true finding is worse than keeping a weak one, and so passed everything
through. Give the defender an **explicit deletion quota with justification**, and
state the judge's bar **before** the round rather than after.

### 16.8 Sub-questions to settle during the work, not before

- **Does turbopuffer store and index a whitespace-only element in a
  `pre_tokenized_array`?** §6.3 puts `"\n"` between theory names in
  `theory_subtokens` precisely because the tokenizer can never emit it. Untested.
  One upsert against a test namespace settles it; if it is dropped, choose a
  non-whitespace separator the tokenizer cannot emit. **This is step 0b of §8.1** —
  it was listed here as a question and nowhere as a step, so nothing owned it.
- **What number does the RRF fusion return per row?** One `multi_query` against a
  live namespace settles it. D40 already fixes what is *displayed* — the vector
  leg's cosine similarity — so this affects plumbing only.
- **Does the f16 conversion change the ranking?** D31 says its reasoning is
  analysis rather than measurement, and that converting the real stored vectors
  and measuring the ranking change should happen before the export publishes.

### 16.9 What is still blocked, and by whom

Per §12.2: the key repair (D33) is **done** as of 2026-08-18. The site export still waits
on the theory-hash registry (prerequisite B) and on entity positions reaching the
published snapshot (prerequisite C), both owned by the user. **The tokenizer freeze
touches no keys and waits on none of them** — D33 used to describe itself as a
prerequisite of the whole of phase one, which contradicted this; it is a prerequisite
of steps 4 and 5. After the freeze, the next unblocked thing is the export's asset
emission, which is step 2 above.
