# Self-consistency audit of SEMANTIC_SEARCH_SITE_PLAN.md

Run 2026-08-18 by an agent given the plan, its companion
`SEMANTIC_SEARCH_SITE_PLAN_DONE.md`, and nothing else. About sixty findings. This file is
the work list; it is not evidence, and the plan remains the authority on anything the two
disagree about.

**Line numbers were taken before the first round of fixes and have moved.** Grep the
quoted text instead.

A second audit — the plan checked against the code and the corpus rather than against
itself — was still running when this was written. Append its findings here when it lands.

## Already fixed, commit 5a42646

- §16.2 carried "It is derived from `etc/symbols`, never hand-written" — the claim §5.4
  retracts. Nine of the 99 come from `etc/symbols`, ninety from a hand-maintained dict.
- §16.2 annotated `'?a + ?b' ≡ '?a+?b' ≡ 'a+b'` with "whitespace is not a boundary", which
  §5.2 retracts in as many words.
- §16.2 annotated seven inputs as "(all six)".
- §16.4, the definition of the asset, **omitted the fold table** — without it the port
  cannot fold at all and cannot tell which 90 of the 99 separators are rendered
  characters. Step 1's corpus comparison cannot catch this, because both sides read the
  same asset.
- §16.4 listed the `letter`/`greek` groups of `etc/symbols` among the emitted sets; §5.2
  says they are not consulted.
- §16.4 carried `²` at 640 occurrences "in the corpus"; 3,955 over the whole corpus, 640
  over §3.3's 230,944-document namespace.
- §16.7 asked a review whether `symbol_explode` can split a symbol — a step D43 deleted —
  and about a letter-group boundary §5.2 says does not exist.
- §6.1's schema declared `[4096]f32`; D31 locks f16. The schema is what an implementer
  copies.
- §0 and §16.9 both said all three prerequisites still block the export; D33 and §12.2 say
  A is done.
- The header said the document "has still not" been reviewed adversarially. Two rounds
  have run.
- D33's caveat that §7.2's "already in the DB, 100 %" cell "is wrong until that plan has
  run" — it has run.

## Outstanding, ranked

### Would make an implementer build the wrong thing

1. **§8.1 step 5 specifies a rule §5 does not contain.** "§5's tokenizer strips one
   trailing `(_)` from an `Entity Name` condition before tokenizing … That normalisation
   is a shared asset (§5.5)." §5.1's pipeline has four steps and none strips `(_)`;
   §5.5's asset list does not carry it; §16.2 does not test it. Either specify it in §5
   and §5.5 and add a §16.2 case, or delete the claim and say where `coll(_)` is handled.
2. **§8.2's namespace naming predates D45.** It names the namespace for the data only
   (`isabelle-2025-2-afp-2026-05-13`); D45 requires the asset digest in the name and D46
   makes a mismatched component set a hard failure. §8.2 is the only place the scheme is
   specified.
3. **§8.1 step 6 emits the pre-D45 asset set** — "the shared test vector file and the
   symbol table JSON" — where D45 requires one stamped asset carrying the symbol table,
   the fold table, five character-class sets, the abbreviations, the `ISABELLE_SYMBOLS`
   file list and the Unicode version.
4. **§9.2 rests on a measurement D37 retracted.** "`?P ⟹ ?Q` returns 1 document" — D37
   records 60, and the empty-state copy was rebuilt on `?n + ?m = ?m + ?n`, measured 0.
   A whole subsection argues from the withdrawn figure.
5. **D46's failure condition names a "declared component set" the plan never locates.**
   Nothing says where the declaration lives or what it is compared against.
6. **§16.3 step 1's acceptance is "reproduces every line of §16.2"** — repairable now that
   §16.2's three retracted claims are fixed, but the dependency should be stated.

### Figures that disagree with themselves

7. **Corpus total.** §3.1 gives 1,364,990 entries / 1,353,574 entity records; §0, D5,
   §3.4 and §16.2 use the 1,362,343 family. §3.1 is the section the plan tells reviewers
   to trust and is 8,769 low. Needs a dated correction note like §3.2 and §3.4 carry.
8. **Theorem-alike records.** 1,148,833 in §3.1 and §7.2; 1,156,333 in D24, whose every
   percentage is computed against it.
9. **`⟹` document frequency.** 42 %, 42.35 % and 45.34 % across §3.3, §3.4, §3.6, §14.6
   and the companion, against two denominators, one of them unstated.
10. **Fallback-kept-token frequency** appears as 3.18 % (230,944 base), 3.81 %
    (1,362,096 base) and 3.71 % (§14.7, matching neither).
11. **Per-search cost.** §11.1b computes $0.000022 from "~20 KB returned"; D29 computes
    $0.000031 from "~200 KB". D29 is internally consistent; §11.1b is an order of
    magnitude low, and its per-day table and the "13,600 searches a day" floor inherit it.
12. **§11.1b's whole cost model runs on 1,241,679 site documents**, the count D5 reversed
    to 1,362,343. §3.3's "230,944 is 18.6 % of the real corpus" has the same base; against
    the reversed D5 it is 17.0 %.
13. **Distinct theory long names** 8,299 (§7.2) vs 8,329 (D39).
14. **Hashes the site must resolve** 9,148 (§3.2) vs 9,214 (§7.3).
15. **§3.2 says two apparent misses; §7.3 explains one.**
16. **§3.1's vector count is 110,329** (8 % coverage); §8.1's gate reports 0.65 % missing.
    A reader sizing the export from §3.1 is off by twelve times.
17. §3.1's full-coverage vector count (1,353,570) does not match its own record count
    (1,353,574).
18. Mean tokens per document 37.0 and 39.0 in adjacent lines; `::` at 9.1 % and 9.89 %
    with the sample caveat attached to the wrong line.
19. Thousands separators alternate between comma and space for the same quantity.

### Status and structure

20. §12.2's diagram omits step 3 — the only live work — and leaves B feeding nothing,
    though the prose says B blocks the export through D24's scope test.
21. §12.2's prerequisite C is "positions in the published snapshot" in prose and
    "positions carried into the rebuilt store" in the diagram. Different artefacts.
22. §12.2's closing paragraph offers the copy and mockup as available work; both are done.
    It also cites "D21-D41" where the range now runs to D46.
23. §2's preamble accounts for D1-D21 only, and does not explain why the list runs
    ascending to D20 then descending from D46.
24. The companion's §15.0 status block says "D1-D42 are settled" and lists the copy and
    the tokenizer freeze as the two unblocked pieces. The copy is done, D43-D46 exist,
    and prerequisite A is done.
25. §9's heading and preamble still assert D20 ("DEFERRED", "nothing here is to be built
    yet"); D20 is superseded by D32, which stages §9 as phase two.
26. §5.1 step 2 still calls the U+007F replacement "a stop-gap until §10 lands". It landed.
27. D37's "consequence to act on" — rebuild the empty-state page — is discharged.
28. §11.1b argues for a BM25 degradation path D35 deleted; §6.5 and §11.1 record the
    deletion, §11.1b does not.
29. D9/§9.4 say one entity page per site document; §6.1 makes `group` the page identity
    while D5's reversal makes a site document one per record.
30. §13's Q3 gives a rate D35 superseded (12/minute against 5 per 10 seconds), applies
    D29's 512-character condition cap to the 8,000-character query cap, and cites a figure
    D28 no longer contains.
31. D33 calls itself "a prerequisite of the whole of phase one" while §12.2 step 3 says
    the tokenizer freeze never depended on it.

### Cross-references

32. **§11.4 does not exist.** §11.1's instruction for when to build D35's layer 3 points
    at nothing.
33. "A reader working on the backend can skip to §10" now lands on a four-line pointer
    stub.
34. §6.6 is filed before §6.5.
35. A `site/COPY.md §3.2` citation should be §4.2.
36. §5.4 says D41 carries the stale 640; D41 was corrected and §16.4 carried it (now
    fixed). The sentence should name §16.4.
37. §16.7 leans on §15.4 without saying §15.4 is now in the companion.

### Terminology, against §1's rule of one canonical name

38. `unicode_of_ascii` and `pretty_unicode` for one function (they are aliases in the
    source; the plan should pick one).
39. "one stamped asset" (D45) against "the assets" (D41, §5.2, §16.3, §16.4). The digest
    that names the namespace is of one file, so the number matters.
40. The theory-hash registry is also "the hash-to-name table" and "the complete
    hash-to-name table".
41. `interpretation` / "explanation" / "the disclosure" / "the disclaimer" / "the
    disclosure sentence" for one field and one locked sentence.
42. `contains`/`excludes` in the interface, `includes`/`excludes` in §6.3's compilation.
43. "four panels plus a kind filter" (§0) against "five filter panels" (D22, §9.1).
44. §9.2b labels the theory panel "theory"; D22 fixes it as `Theory Name` and records that
    the bare form was considered and rejected.
45. `theorem-alike`, `name-addressed` and `universal key` are load-bearing throughout and
    absent from §1.
46. The unit of counting drifts among records, documents, expressions and entities for the
    same corpus, sometimes within a sentence. §1's `site document` is none of them.
47. §0 calls the export "one-off"; §8 requires it to be re-runnable and deterministic.
48. §8.3 still says `symbol_explode` folds CR to LF; D43 deleted the step.

### Cannot be acted on as written

49. §9.4 says to prioritise "widely-used AFP entries" for crawl budget; no field records
    popularity and the plan defines no signal.
50. §11.1's two unverified items give no procedure, and the paragraph above already
    asserts one of them as fact.
51. §6.3's `theory_subtokens` separator `"\n"` is specified as settled while §16.8 says the
    question it depends on — whether turbopuffer stores a whitespace-only element — is
    untested. Neither §8.1 nor §12.2 lists the test as a step.
52. D33 records G1 as not re-verified and does not state the command that regenerates the
    dependency table it needs.
53. §12.1's repository layout omits `site/COPY.md`, `site/design/`, `site/prototype/` and
    `site/review/`, all cited as load-bearing elsewhere.
54. Two cited plan files live at the repository root, not beside this plan as the citation
    convention implies; one is cited without its extension.
55. The companion's §15.1 sends the reader to probe scripts in a deleted scratchpad; the
    live answer is `site/prototype/corpus_probe.py`. Same at §15.3 for the prototype files.
