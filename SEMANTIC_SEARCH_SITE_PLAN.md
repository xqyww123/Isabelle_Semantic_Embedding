# A public semantic-search site over the Isabelle semantic DB

Draft 3, 2026-08-12. This document is the design agreed in conversation on
2026-08-09 and revised on 2026-08-12; it is written to be reviewed
adversarially, **which has still not happened**. Draft 2 recorded the decisions
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
positions exist only on `cslh19`; this machine holds 8,306. Everything else in
§12.2 is unstarted: no tokenizer module, no site export, no Worker, no site.

Orientation for a reader arriving with no other context: §2 is the settled
decisions (do not reopen), §3 is the measured evidence every decision rests on,
§13 is the open questions, §14 is what was considered and rejected. Citations
name **functions and files, not line numbers** — this is a shared working tree
and line numbers move (the convention `VECTOR_INVALIDATION_PLAN.md` and
`ENTITY_POSITION_PLAN.md` both adopted).

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
subtokens** (D21, §5.4), in four panels plus a kind filter (D22):

1. **Entity Name** — the entity's own name;
2. **Expression** — the printed entity expression;
3. **Theory Name** — the associated theories. What that means differs by kind
   and is stated in the interface (D14, D15, §7.2, §9.2b);
4. **All** — any of the three above, compiled to an `Or` (§6.3);
5. **Kind** — a chip group, everything selected by default (D29).

Serving is fully serverless: Cloudflare Pages + Worker for the front end,
turbopuffer for vectors *and* filtering, Fireworks for the query embedding. No
server to operate. A one-off **site export** derives the published index from
the semantic DB.

## 1. Glossary — canonical names, never paraphrased

| Term | Meaning |
|---|---|
| **entity** | One record in `semantics.lmdb`: a constant, type, class, locale, method, theorem collection, theorem, or derived rule. Never "item", "object", "fact". |
| **entity expression** | The `expr` field of the record. For theorem-alike kinds it is the proposition; for constants it is the type; for the five source-text kinds (`TYPE`, `CLASS`, `LOCALE`, `METHOD`, `THEOREM_COLLECTION`) it is the declaration's source text. |
| **declaring theory** | The theory whose source declares the entity, named by its **session-qualified long name** (e.g. `HOL-Library.Sorted_Sort`). **Applies only to name-addressed entities.** Theorem-alike entities are content-addressed and have no declaring theory in this data model (§7). Never "owning theory", "home theory". |
| **constituent theories** | The `theory_constituents` field: the theories of the **constants occurring in the entity expression**, as `(long name, 16-byte hash)` pairs. Present on every theorem-alike and experience record. **Not** a declaring theory. |
| **the associated theories** | The set of theories a *site document* is filtered by (D14): its declaring theory when name-addressed, its constituent theories when theorem-alike. **This exact phrase, always** — never "related theories", "relevant theories", "theory domains", or any other paraphrase. The word "domain" is specifically excluded: `dom`, `Dom` and `domain` name unrelated Isabelle concepts (the domain of a map or relation, and HOLCF's `domain` command) in about 27,500 entities of this very corpus, and "domain" also reads as "subject area", a plausible but wrong meaning. |
| **the tokenizer** | The single normalisation described in §5, applied identically to stored text and to user queries. Never "the analyser", "the lexer", "the splitter". |
| **token** | One output element of the tokenizer. |
| **subtoken** | One output element of the second-level split described in §5.4. Under D21 this is the only level that is indexed or queried. |
| **site export** | The batch job (§8) that turns the semantic DB into the turbopuffer namespace and its attributes. Never "publish", "sync", "ingest". |
| **site document** | One turbopuffer document, one per exported *record* (D5, reversed 2026-08-13). Records sharing a `(name, entity expression)` are collapsed into one card in the response, not in the index. |
| **entity page** | The server-rendered permanent page for one site document (§9.4). |

## 2. LOCKED decisions

D1–D20 taken by the user on 2026-08-09, D21 on 2026-08-12. Do not re-litigate;
ask before deviating.

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
  against 1,241,679 merged documents), which at f16 is ~11.9 GB against
  ~10.83 GB and is invisible beside a full-length query's embedding cost; a
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
- **D9** — **entity pages exist**, server-rendered, one per site document, for
  search-engine discoverability (§9.4).
- **D10** — **displayed fields are the entity name and the entity expression.**
  The interpretation is present but collapsed by default.
- **D11** — **`Token.source_of` in `pide_state.ML` is a defect and will be
  fixed** to `Token.unparse` (§10.1). It is our own file, not part of the
  Isabelle distribution.
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
  only: the repair (§10), the hash-to-name table (§7.3), the tokenizer (§5), the
  site export (§8), the turbopuffer namespace (§6), and the Worker's search API
  (§11.1's rate limiting included). §9 stays in this document as the agreed
  design but is **not** to be built yet, and the questions it raises need no
  answer to unblock anything.
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
  indexed, since §5.4 splits at `_` regardless of symbol boundaries. Measured: the
  change moves 0.23 % of subtoken arrays (3,135 of 1,362,096 expressions), all of
  them escapes left literal by step 3, and every move is an improvement, since
  `\<^named_theorems>` stops indexing as the unsearchable `['\<^named','theorems>']`.
  Two review findings dissolve with the step: that §5.1's justification was false,
  and that the treatment of a malformed or unterminated `\<` was unspecified —
  `\<=` is now simply one symbolic run. §5.3's eleven equivalences and §16.2's
  thirty-two cases were re-run under the new definition and all still hold.
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
  ASCII-symbolic code-point sets as assets beside the symbol table, and neither
  implementation may consult a language built-in. Separately, §5.5's 10,000 test
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
  facts — and the store agrees: no entity name in the 1 362 343 records carries a
  session prefix. (The 1 266 names with a hyphen in their first segment are
  theories whose own base name contains one, such as `Nominal-HOLCF.Def_eqvt` and
  `HOLCF-Utils.fun_upd_cont`.) The export therefore indexes the stored name
  unchanged and adds nothing. Nothing else in D39 changes.

  Worth noting for the interface, since the two fields differ: `theory_subtokens`
  **is** session-qualified — 8 329 distinct theory long names, of which only
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
  is measured and real: `x` is a subtoken of 22.95 % of documents, `a` 17.50 %,
  `P` 10.80 %, `f` 10.49 %, so a user filtering on `f` matches a tenth of the
  corpus, nearly all of it accidental. Excluding variable positions was
  considered and not taken — the records store printed text, not term structure,
  and a free variable is indistinguishable from a constant in that text, so
  excluding them would mean changing what the collection side records, not the
  export. Reinstating `?` was also rejected: it would reverse D4, whose reason
  (users do not type the question mark) still holds, and it would not help with
  free variables anyway. **Consequence to act on:** §13b's empty-state page is
  premised on `?P ⟹ ?Q` matching nothing, which is false — it matches 60 records
  — so that page needs an example that genuinely returns nothing.
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
- **D33** (2026-08-13) — **`BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN` is a
  prerequisite of the whole of phase one.** Its defect — a process-global
  first-writer-wins memo on theory short names — leaves 234,398 records holding
  keys the current process cannot reproduce and mis-targets anything that
  selects records by theory, which is precisely what the theory filter does
  (D14, D23), and it passes the XOR self-check silently. Its repair rebuilds the
  store under corrected keys, so any export run before it would publish wrong
  theory data under document ids that the rebuild then changes — taking every
  permanent entity-page URL D25 ships with it. §7.2's "already in the DB, 100 %"
  cell is wrong until that plan has run. The user will complete the repair before
  execution begins.
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
  ~21 GB to ~10.8 GB and the per-query charge from $0.000021 to $0.0000108
  (§11.1b). Dimension reduction, which would have cut a further 5×, is **not**
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
  (D40's third sentence follows it; see `site/COPY.md` §3.2 for the whole
  string.) Reason: two consecutive rounds of reader testing named
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
  cold it "is billed as a query that returns zero rows", which at 21 GB costs
  exactly what a real search costs (§11.1b). It therefore charges full price
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

  Measured 2026-08-13 over 1,156,333 theorem-alike records: **30,304 (2.62 %)**
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

Everything in this section was measured on 2026-08-09, not assumed. A reviewer
should treat any claim elsewhere in this document that is *not* here as an
assumption.

### 3.1 The corpus

```
semantics.lmdb            1,364,990 entries;  1,353,574 entity records;  1.7 GB
  theorem-alike           1,148,833  (84.9 %)
  name-addressed            204,741  (15.1 %)
vector store (Qwen3-8B)     110,329 vectors × 4096 dims × int16 = 862 MiB
                            (a lazy cache; the full run is in progress on cslh19)
entity expression        169.7 M characters total; mean 126, median 75, p95 375, max 32,228
interpretation           ~0.40 GB total
```

At full coverage the vectors are 1,353,570 × 8192 B = **11.1 GB**.

### 3.2 What the DB does *not* contain

- **No position.** Raw msgpack tuples have 6, 7, 8 or 12 fields, all accounted
  for by the twelve named `Record` fields. `semantic_store.ML` computes
  `Position.line_of` but passes it only to the interpreting agent's prompt.
  `entity_source` obtains source by asking a **live Isabelle** through
  `command_at_position`. → `ENTITY_POSITION_PLAN.md` fixes this.
- **No declaring theory for theorem-alike records.** Their key prefix is an XOR
  pseudo-theory. Matching the first segment of `name` against the constituent
  theories' base names resolves **85.3 %** uniquely, **0 %** ambiguously, and
  **fails on 14.7 %** (≈170 k records) — the declaring theory contributes no
  constant to the statement. Example: `Abstract_Reachability_Analysis.max_Var_floatariths_concat`,
  whose constituents are five other theories.
- **Partial declaring theory for name-addressed records.** The key prefix *is*
  the declaring theory's hash. Harvesting `(long name, hash)` pairs from every
  theorem-alike record's constituent theories yields 8,336 mappings, which
  resolve **8,311 of the 9,148** distinct prefixes → **192,244 of 204,741
  records (93.9 %)**. The remaining **12,497 records (0.9 % of the corpus)**, in
  837 theories, keep only the theory base name from their own long name.
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
230,944 is 18.6 % of the real corpus (D5).

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

```
230,944 documents          mean 37.0 tokens, max 6,981
distinct tokens            56,336 (in a 150 k sample)
document frequency of the commonest tokens
   '(' ')' 65 %   '.' 53 %   '=' 50 %   '⟹' 42 %   ';' 26 %   '⟦' '⟧' 25 %
merging ASCII symbolic runs changes little   39.0 → 38.5 tokens, 56,336 → 56,455 vocabulary
   but creates 130 distinct operators: '::' 9.1 % (9.89 % on the full 230,944;
   this line came from a 150 k sample), ':=' 1.4 %, '::=' 0.3 %, '=>', '->', '**', …
   and shortens the ':' postings list from 12.8 % of documents to 2.4 %
```

Whitespace erasure was checked for collisions across the whole corpus: **200
collision classes out of 1,353,348 (0.015 %)**, and inspection of all 200 found
**none** whose two source texts differ by anything other than whitespace. So
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

Character hygiene: **0** private-use-area characters in `expr`, `name` or
`interpretation` — still true after the widening, because D44 leaves a
private-use symbol as its escape rather than substituting it. **238 records**
contain U+007F (§10); **835** occurrences of CR.

**Literal `\<…>` escapes, re-measured 2026-08-17, and re-characterised.** The
earlier figure — 1,140 records "for a symbol with no code point", 32 kinds —
named the wrong class. The operative distinction is not "in the table without a
`code:` field" but **"not in the table at all"**, and the two behave identically
for the tokenizer while having very different sizes. Of the 3,562 records whose
raw text carries an escape: 77 carry one that the distribution's table defines
without a code point; 1,056 carry one defined only in `contrib/phi-system/symbols`,
and those are exactly the 1,056 that now convert. Of the rest, **1,981** carry a
word-glyph escape that `contrib/phi-system/symbols-words` **does** define — with a
private-use code point, so D44 leaves it alone deliberately — and **1,078**, in 20
distinct kinds, carry one declared in no `symbols` file in this repository at all
(`\<Empt>`, `\<PR>`, `\<aA>`), which no asset can ever convert. The three reasons
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
long names, and every user-supplied filter string:

1. `unicodedata.normalize('NFC', s)` — the store is already 100 % NFC; queries
   pasted from macOS may be NFD, whose combining marks are not `\w` and would
   split identifiers. **NFKC must not be used**: it maps `₁`→`1` and `𝐚`→`a`,
   destroying Isabelle subscript semantics.
2. Replace U+007F with a space (a stop-gap until §10 lands; harmless after).
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
   Both tables come from the assets of §5.5, and neither implementation may carry
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
used to be indexed is gone. Nine such patterns occur, all in phi-System theories
that D24 excludes from the export — `Calculus_of_Programming.φapply_proc`,
`PLPR.Premise_const_True(4)` and their siblings. The decision stands on 3,118
refinements against 17 losses of bare punctuation, but it does not stand on the
absolute claim.

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
three. D45's assets must preserve the overlap rather than partition it.

A quasi-letter cannot **begin** an identifier, only continue one. So Isabelle's
type variable `'a` is two tokens, `["'", 'a']`, and `_wrt` is `['_','wrt']` whose
first token then disappears in §5.4. Both are load-bearing and neither is
obvious; §16.2 carries a case for each.

The `letter`/`greek` groups of `etc/symbols` are **not** consulted, though an
earlier draft said they were. All 164 of their members already satisfy
`isalpha()`, so the union added nothing; and every one of them has a code point,
so step 3 substitutes it before token formation ever sees it.

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
same quantity is 51,891 documents (3.81 %) and 154 distinct tokens, and the raw
occurrence counts move too: `²` is 3,955, not 640, and `₁` is 7,023, not 1,281.
D41 repeats the 640 as "occurrences in the corpus", where it is six times low. Restricting it to rendered
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
  sufficient: real data cannot exercise pipeline steps 1, 2 or 3 at all (§3.4),
  and the gate must assert **coverage of named features**, not merely a sample
  size.

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
vector           [4096]f32, cosine_distance

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
                               `expr_tokens` field was in draft 2 and is gone
name_subtokens   []string      reached by the `Entity Name` panel (D22).
                               Measured mean 21.46 -> see below; this array is
                               short, mean 6.30 elements
theory_subtokens []string      the subtokens of every name in `theories`,
                               concatenated with a separator token between
                               names (below).  Subtokens, not tokens, per D23;
                               named `theory_tokens` through draft 2.  Mean
                               21.46 elements

  ranking
interpretation   string        BM25-indexed (§6.5)
```

### 6.2 Document id

The universal key cannot be the id: keys run from 20 to **308 bytes**, and
**88,798 (6.6 %)** exceed turbopuffer's 64-byte string-id limit once encoded.
Use a **128-bit hash of the universal key as a UUID**, and keep the full key as
an ordinary attribute. The hash must be **deterministic**, so that a re-export
upserts in place instead of creating duplicates.

### 6.3 Query construction

Under D21 there is one form for an expression condition, and `ContainsAllTokens`
appears nowhere:

```
includes(expr)   ["expr_subtokens", "ContainsTokenSequence", subtokens(tokenize(s))]
excludes(expr)   ["Not", ["expr_subtokens", "ContainsTokenSequence", subtokens(tokenize(s))]]
includes(name)   ["name_subtokens", "ContainsTokenSequence", subtokens(tokenize(s))]
includes(theory) ["theory_subtokens","ContainsTokenSequence", subtokens(tokenize(s))]
includes(all)    ["Or", [ the three includes above ]]                         ← D22
excludes(all)    ["Not", ["Or", [ the three includes above ]]]                ← D22
combination      ["And", [ … ]]
```

`Or` is verified to exist, to nest inside `And`, and to sit inside `Not`; the
`excludes(all)` form above returned exactly `total − includes(all)` on real
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
token between names. `"\n"` is a safe choice precisely because the tokenizer
discards whitespace and can therefore never emit it, so no user query can
contain it — and it survives subtoken formation untouched, being injected by
the export rather than produced by the tokenizer and absent from D21's
separator class.

Index cost, measured on the §3.6 namespace: `theory_subtokens` averages 21.46
elements per document against the expression array's 37.72, and
`name_subtokens` 6.30.

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
| theorem-alike (1,148,833) | its **constituent theories** | the `theory_constituents` field | already in the DB, 100 %, session-qualified |
| name-addressed (204,741) | its **declaring theory** | the key's 16-byte theory hash | needs the hash-to-name table (§7.3) |

Measured: 7.10 constituent theories per theorem-alike record on average
(median 6, maximum 42), drawn from 8,299 distinct theory long names. Only four
carry no session prefix — `Pure`, `FOL`, `IFOL`, `ZF` — which are Isabelle's own
base logics and genuinely have none.

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

### 7.3 The hash-to-name table

Name-addressed entities carry their declaring theory's hash in the key prefix,
and a per-theory record does exist in `semantics.lmdb` under that 16-byte key —
but it holds only interpretation cost accounting (`input_tokens`, `cost_usd`,
`model`, `driver`, `finished`), **no name**. 11,415 such records exist.

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
anyway. **The shortfall on persistent hashes is zero.**

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
1. **Completeness gate.** Assert that every entity record has a vector. The
   vector store is a lazy cache and missing vectors are legal in normal
   operation, so the export must **fail loudly** rather than publish a corpus
   with holes. *Status 2026-08-12:* 8,908 records (0.65 %) have no vector, all
   of them tombstoned and awaiting re-embedding, so the gate does not pass yet.
   The user has taken this as a known item to be resolved before the first
   export, not as a reason to weaken the gate.
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
   on the **query** side instead — §5's tokenizer strips one trailing `(_)` from
   an `Entity Name` condition before tokenizing, so it behaves exactly like the
   raw name. That normalisation is a shared asset (§5.5).
6. **Emit** the shared test vector file (§5.5) and the symbol table JSON.
7. **Upsert** into a fresh namespace (§8.2), then switch the Worker over.

### 8.2 Versioning

Write each export into a **new namespace** named for the data it came from
(e.g. `isabelle-2025-2-afp-2026-05-13`), and switch the Worker's target when it
verifies. turbopuffer has no "delete everything absent from this batch"
operation, so upserting into the live namespace would leave deleted entities
behind forever. A fresh namespace also gives an instant rollback.

### 8.3 Display cleaning

```python
def clean_for_display(expr):
    expr = repair_del(expr)          # §10.2; a no-op once the DB is repaired
    return expr.replace('\r\n', '\n').replace('\r', '\n')
```

The 835 CR occurrences affect display only — `symbol_explode` already folds CR
to LF and the tokenizer then discards it, so search is unaffected.

## 9. The front end — DEFERRED (D20)

This section records the design that was agreed, so that it does not have to be
re-derived later. **Nothing here is to be built yet**, and none of its open
questions blocks the data-side work. A reader working on the backend can skip
to §10.


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
Measured: `?P ⟹ ?Q` returns 1 document and `⟦?P; ?Q⟧` returns 0, because real
statements do not contain literal tokens named `P` and `Q`. Users will type
exactly these, expecting Isabelle pattern semantics, and conclude the site is
broken.

Therefore: never label this feature "pattern"; and when a syntactic filter
returns nothing, say explicitly that the filter is literal and does not support
variable placeholders.

### 9.2b The theory filter means two things, and says so (D15)

Per D14 the theory filter matches a name-addressed entity's declaring theory
but a theorem-alike entity's constituent theories. The interface states this
rather than hiding it. One sentence carries it, shown beside the field:

> **theory** — matches an entity's **associated theories**: for constants,
> types, classes, locales and methods, the theory that declares them; for
> theorems, the theories of the constants their statement uses.

The field's own label is just **theory**; the full phrase belongs in the
explanation, not on the control.

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

One server-rendered page per site document at a stable URL, carrying name,
kinds, theory, expression, interpretation, source link, and a "related
entities" block computed from the ten nearest vectors. The related block is not
decoration: it is what keeps these pages from being classed as thin content.

Search results must link to these URLs from day one even if the pages ship
later, so the URL scheme never has to change and no inbound links are lost.

Sitemaps must be sharded (50 k URLs each, so ≥28 shards plus an index).
Crawl budget will not cover 1.35 M pages on a new site; prioritise HOL and
widely-used AFP entries.

### 9.5 Rendering

Server-rendered from the Worker rather than a client-side application: entity
pages need it for indexing, it works without JavaScript, and the page structure
is simple enough that a framework earns nothing.

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
because it is the only piece here needing a new stateful component. Revisit
from the Analytics Engine data (§11.4), not from speculation.

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

Two things unverified at the time of writing, both settled by trying them:
whether the Free plan's single rule accepts a threshold of 5 (the documentation
states the period and the characteristic, not the permitted thresholds), and
what request allowance the Workers Paid plan includes.

A **query-embedding cache in Workers KV**, keyed on the normalised query
string, remains worth building: search traffic is strongly Zipf-distributed, so
it removes more Fireworks calls than any rate limit and cuts latency on a hit.
**Cloudflare Turnstile** stays in reserve if the two built layers prove
insufficient.

### 11.1b What it costs, measured against the published price lists (2026-08-13)

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

At 1,241,679 site documents × 4096 dimensions × 4 bytes the vectors are
20.34 GB and the namespace ~21 GB:

```
per search   21 GB queried  $0.000021   +  ~20 KB returned  $0.000001  =  $0.000022
             i.e. $22 per million searches; the queried term is 95 % of it
per day      10 k searches $0.22   100 k $2.20   1 M $22.00
per month    storage $6.93; initial load 21 GB x $2 = $42, or $21 batched
```

The $16 floor absorbs everything below roughly **13,600 searches a day**, so
marginal searches are free until then.

**Reducing the vector changes this by up to 16×**, because namespace size *is*
the per-query price. turbopuffer counts f16 at 2 bytes per dimension and i8 at
1 (for storage and queries; writes still count 4):

```
4096-d f32   21.00 GB   $22.00 / M searches   storage $6.93 / month
4096-d f16   10.83 GB   $10.83                        $3.57
1024-d f32    5.74 GB    $5.74                        $1.89
1024-d i8     1.93 GB    $1.93                        $0.64
```

The 1.28 GB per-query floor puts a hard bottom of $1.28 per million searches on
this workload however small the vectors get. **Whether recall survives any of
this is unevaluated — the figures above are money only.** Note the local vector
store already holds Q1.15 int16, so f16 is a format change rather than a new
loss of precision, while dimension reduction is not. This is Q14.

**Compared with the query embedding, turbopuffer is the larger cost at every
volume**, not just at scale: Fireworks costs $3–13 per million searches against
turbopuffer's $22. The two cross over only if the namespace shrinks below about
13 GB. **This weakens the BM25 degradation path of §6.5 and §11.1**: falling
back to BM25 when the Fireworks budget is exhausted saves the smaller half of
the bill, not most of it, because the turbopuffer query is still charged in
full. It remains worth doing — the site keeps working — but not as a cost
control.

turbopuffer publishes **no spend cap and no budget alert**. A hard limit has to
be enforced by this application, metering itself on the `billing` object every
query response carries (`billable_logical_bytes_queried`,
`billable_logical_bytes_returned`).

Sources: turbopuffer's pricing page and pricing changelog, and the query,
warm-cache, pinning, regions and limits docs. The per-unit rates are not prose
on the pricing page — they live in the cost calculator's own constants — so
they are turbopuffer's numbers but not quotable at a finance department.

### 11.2 Cache warming, and why there is none (D27)

`GET /v1/namespaces/:ns/hint_cache_warm` looks free and is not. The warm-cache
doc: free "if turbopuffer is ready to serve requests with low latency, or it is
already getting the namespace ready" — otherwise "this request is billed as a
query that returns zero rows", and a zero-row query still pays the full
namespace charge, $0.000021 here (§11.1b). The mechanism therefore costs a full
search exactly when it would have helped, and nothing when it would not. D27
drops it.

What is worth keeping from this section: **log `cache_temperature` and
`cache_hit_ratio` from every query response**, so a real regression is visible
rather than inferred, and log the `billing` object too — turbopuffer publishes
no spend cap, so self-metering is the only hard limit available (§11.1b).

### 11.3 Disclosure

The interpretations are LLM-generated. The site must say so plainly; readers
will otherwise treat them as authoritative documentation.

## 12. Repository layout and implementation order

### 12.1 Layout (D16)

The site lives in this repository because the tokenizer has two
implementations that must not drift (§5.5); one repository and one CI run is
what enforces that, and version-number coordination across repositories would
not.

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

**Prerequisite A — the key repair (D33).** `BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN`
rebuilds the store under corrected keys. It must run **first**: any export taken
before it publishes wrong theory data under document ids the rebuild then
changes, taking every permanent entity-page URL (D25) with them.

**Prerequisite B — the theory-hash registry**, per `THEORY_HASH_REGISTRY_PLAN.md`.
A name-addressed entity's declaring theory lives as a 16-byte hash in its key and
is unreadable without the table. Two things fail without it: the `Theory Name`
filter for the 204,741 name-addressed records (15.1 %), and **D24's scope test**,
which is exactly the declaring theory for those records — so the export cannot
even decide what to publish.

**Prerequisite C — entity positions in the published snapshot.** The backfill is
done on `cslh19` (80.2 %) but the Hugging Face snapshot was packaged before it
finished, so this machine holds 8,306. Note the interaction with A: positions are
stored against keys, so the republish has to follow the rebuild, not precede it.

```
A  key repair (rebuilds the store)
      |
      +-- B  theory-hash registry published
      +-- C  positions carried into the rebuilt store
                  |
                  +--> snapshot republished from cslh19
                              |
                              +--> step 4 onwards
```

1. ~~Repair U+007F (§10).~~ **Done** — zero of 1,362,343 records still carry
   U+007F, measured 2026-08-12.
2. Prerequisites A, B and C above. **Owned outside this plan; in progress.**
3. **Freeze the tokenizer**: Python implementation, JavaScript port, the shipped
   character-class and symbol assets, the test-vector file with its synthetic
   cases, and the CI gate (§5.5, D41). **This does not depend on A, B or C** —
   it needs `etc/symbols` and the distribution, and although its test vectors are
   sampled from real entity expressions, the repair changes keys and not text.
   It is therefore the one part of phase one that can proceed now.
4. Build the site export (§8) and load one full namespace. **Blocked on A, B, C.**
5. Worker: search API, embedding cache, rate limits (§11.1). Blocked on 4.
6. Front end: search page, then entity pages. Phase two (D32).

Independently of all of the above, the interface copy and the mockup can be
brought in line with §13b and with D21-D41 at any time; that work touches no
data.

**Draft 3 correction.** Step 2 used to read "Build the complete hash-to-name
table (§7.3) - light, independent", meaning an Isabelle enumeration run. §7.3
now shows the table already exists and is already complete; what it needs is to
be *published*, which is a different job in a different plan.

## 13. Open questions

Q1, Q2 and Q4 of draft 1 are settled — see D19, D18 and D13 respectively.

- ~~Q3~~ — **settled**: **12 requests per IP per minute** at the Cloudflare
  edge. The global daily cap is cancelled (D28). Arithmetic retained below only
  as capacity information — a per-IP limit does nothing against
  distributed abuse. Fireworks prices Qwen3-Embedding-8B at **$0.10 per million
  tokens** (its own tier; ≤150 M-parameter models are $0.008 and 150–350 M are
  $0.016), and a query costs 6 tokens short, ~130 at the 512-character cap.
  Fireworks alone would put $5/day at ~385,000 queries, but that is the wrong
  arithmetic: the query-embedding cache protects Fireworks only, every search
  hits turbopuffer whether or not the embedding was cached, and turbopuffer is
  the larger half of a search (§11.1b). Counting both gives D28's ~150,000.
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
`⟹` (42 % of documents), `=` (50 %), `⟦`/`⟧` (25 %) and `::` (9.1 %) would all
become unfilterable, and an `excludes` on any of them would reduce to the empty
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
half times commoner than the fallback-kept-token case (3.71 %) the 2026-08-14
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
across **150,679 expressions and 41,554 names (3.05 %)**. A third option — letting
a leading quote attach to the following identifier, as Isabelle's own lexer does —
was measured and buys nothing: the document holds `'a` either way, so a visitor
who omits the quote still fails to match.

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
`isabelle_tokenizer.py` replaces them.

### 16.1 The artefacts, and what each is for

```
site/prototype/subtoken_rule.py       the settled separator class + subtokens(), with the fallback clause
site/prototype/tokenize_prototype.py  tokenize(), plus the superseded subtoken variants the measurements compared
site/prototype/corpus_probe.py        counts how many entities a condition matches, on the real corpus
site/prototype/README.md              what these are; delete none of them until the CI gate is green
```

`corpus_probe.py` reproduces every match count quoted in this plan and in
`COPY.md`. Verified from its committed location on 2026-08-14: `?n + ?m = ?m + ?n`
→ 0, `?a + ?b = ?b + ?a` → 15, in 25 s over 1 362 096 records. It resolves
`ISABELLE_HOME` and the package paths relative to itself, so it runs from
anywhere. **Use it rather than writing a new probe**; a differently-written probe
is a second implementation of the matching rule and will disagree eventually.

### 16.2 The facts a correct implementation must reproduce

Every line below was measured on 2026-08-14 with the prototype. They are the
seed of the test-vector file (§16.5) and the acceptance criteria for the port.
`→` gives the **subtokens**, which is the only level that is indexed (D21).

The separator class is **99 characters**: `_`, `.`, seven control symbols
`⇩⇧⇘⇙⇗⇖❙`, and the 90 rendered sub/superscript characters that `SUBSUP_TRANS_TABLE`
produces from `⇩` and `⇧`. It is derived from `etc/symbols`, never hand-written.

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
'?a + ?b' ≡ '?a+?b' ≡ 'a+b'  → ['a','+','b']      ← whitespace is not a boundary
'HOL-Analysis.Path_Connected.path_image_join'
                              → ['HOL','-','Analysis','Path','Connected','path','image','join']
'Path_Connected.path_image_join'
                              → ['Path','Connected','path','image','join']
"f'"                          → ["f'"]             ← `'` is a quasi-letter, not a separator
'x-y'                         → ['x','-','y']
'%x. x'                       → ['%','x','x']      ← `%` is not converted to λ by the tokenizer
'_'  '.'  '?'  '   '  '???'  '_.'  '\<^sub>'   → [] (all six)
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

Corpus scale, for sizing anything: 1 362 343 records carry a name, 1 362 096
carry an expression, 1 362 163 are exportable (the difference is 180
`EXPERIENCE` records, which are not published).

### 16.3 Build order, with an acceptance test for each step

Do these in order. Each step is finished when its test passes, not before.

1. **`Isabelle_Semantic_Embedding/isabelle_tokenizer.py`** — the production
   Python implementation, lifted from `site/prototype/` and changed in exactly
   one respect: it reads its character classes from the emitted assets (§16.4)
   instead of from Python built-ins and a live `Isabelle_RPC_Host` import.
   *Accepted when* it reproduces every line of §16.2 and, run over the whole
   corpus, produces subtoken arrays identical to the prototype's for all
   1 362 096 expressions. Identical means equal element by element; compare with
   a digest of the concatenated arrays, not by eyeballing samples.

2. **Asset emission in the export** (§16.4). *Accepted when* the assets load
   standalone, with `Isabelle_RPC_Host` and `ISABELLE_HOME` unavailable, and step
   1's corpus comparison still passes.

3. **`site/tokenizer/`** — the JavaScript port, reading the same assets.
   *Accepted when* it passes the shared test-vector file (§16.5) with zero
   mismatches. It must not consult any JavaScript built-in for character
   classification — see D41 for the measured divergences that motivates this.

4. **The shared test-vector file** (§16.5). Build it before step 3 so the port
   has a target.

5. **The CI gate** (§16.6).

6. **`_truncate_to_token_limit`** — decide whether it is still needed. D29 caps
   the query in *characters*, so it probably is not. If not, do not move it out
   of `premise_selection.py`; leave it where it is and record that it is unused
   by the site.

### 16.4 What the assets are, and why they exist (D41)

§5.2 defines the character classes by naming Python's `isalpha`, `isdigit`,
`isnumeric` and `isspace`. JavaScript has no equivalent, and the obvious
substitutes **disagree on real corpus characters** — this is measured, not
hypothetical:

- `²` (U+00B2, 640 occurrences in the corpus) satisfies Python's `isdigit()` but
  is Unicode category `No`, so `\p{Nd}` disagrees.
- U+001C–U+001F and U+0085 satisfy Python's `isspace()` but lie outside
  JavaScript's `\s`.
- U+FEFF is the reverse: inside `\s`, outside `isspace()`.

So the export emits, beside the symbol table, the explicit code-point sets for:
**letters** (including the `letter` and `greek` group symbols of `etc/symbols`),
**digits**, **quasi-letters** (`_` and `'`), **the separator class** (all 99
characters), and **the ASCII-symbolic set** (`! # $ % & * + - / : < = > @ \ ^ | ~`).
Neither implementation may consult a language built-in for any of these.

Emit the abbreviation table too, from the `abbrev:` fields of `etc/symbols` —
the interface needs it for live replacement in the condition box (§9.3), and it
is already being read. Note that an abbreviation with more than one expansion
(`.>` and `<.` each serve four or more arrows) cannot be replaced without
asking, so the interface uses the unambiguous ones only.

### 16.5 The test-vector file

At least **10 000 triples** — input, tokens, subtokens — sampled from real entity
expressions, **plus** synthetic cases, because real expressions cannot exercise
pipeline steps 1 and 3 at all: §3.4 established the store is 100 % NFC and that
`unicode_of_ascii` is the identity on it. A port that omits NFC normalisation and
escape conversion therefore passes a purely-real-data gate byte for byte, and
then returns nothing for `\<Longrightarrow>` — one of the two input routes §9.3
promises.

The synthetic cases must include, at minimum: every line of §16.2; ASCII-escaped
input; NFD input; sub/superscripts that have no fold entry; separator-only
conditions; the `²` and U+FEFF boundary characters; U+001C–U+001F and U+0085; and
a token made entirely of rendered superscripts, for the fallback clause.

Pin the file's **encoding, ordering, count and digest**, so that "both
implementations passed" is itself a checkable claim rather than a report.

### 16.6 The CI gate

Runs both implementations against the test-vector file and fails on any
mismatch. It must also fail if the file's digest changes without the count
changing, which catches a vector file quietly edited to match a broken
implementation.

### 16.7 Run this review first

Per §15.4, **a narrow adversarial review of §5 and D41, before writing
`isabelle_tokenizer.py`.** Small scope, deep agents. The specific question to
ask, because it is the failure mode that a test-vector gate cannot catch:

> Find constructions where two implementations both pass the test vectors and
> still behave differently on real input.

Give the review §5 in full, D41, D21, `site/prototype/`, and §16.2. Ask
specifically about: the fallback clause; the boundary between "letter" as
`isalpha()` and as an `etc/symbols` group membership; whether `symbol_explode`
can produce a symbol that the separator class splits in half; and NFC stability
of every symbol value (§3.4 checked this once — have the review check the check).

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
  non-whitespace separator the tokenizer cannot emit.
- **What number does the RRF fusion return per row?** One `multi_query` against a
  live namespace settles it. D40 already fixes what is *displayed* — the vector
  leg's cosine similarity — so this affects plumbing only.
- **Does the f16 conversion change the ranking?** D31 says its reasoning is
  analysis rather than measurement, and that converting the real stored vectors
  and measuring the ranking change should happen before the export publishes.

### 16.9 What is still blocked, and by whom

Unchanged from §12.2: the site export waits on the key repair (D33), the
theory-hash registry, and entity positions in the published snapshot — all three
owned by the user. **The tokenizer freeze touches no keys and waits on none of
them.** After it, the next unblocked thing is the export's asset emission, which
is step 2 above.
