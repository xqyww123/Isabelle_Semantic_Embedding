# How similar are two interpretations of the same Isabelle entity, and how much does a real change move them?

Measurement run 2026-09-07 in `contrib/Semantic_Embedding`.
Raw data: `pairs.json`, `summary.csv`, `stats_output.txt`. Scripts: `dry_run.py`, `analyze.py`, `stats.py`. Scratch theories: `Sim_Measure_A1.thy`, `Sim_Measure_A2.thy`, `Sim_Measure_B.thy`.

## 0. What this measures and why

The semantic-interpretation pipeline turns each Isabelle entity — a constant, a lemma, a type, a locale — into a paragraph of plain English written by an LLM agent, stores it, and embeds it into a vector so entities can be retrieved by natural-language search.

**Cache invalidation.** When a definition changes, its stored paragraph is stale and so is every downstream entity's. Today the pipeline bumps a version counter and re-asks the LLM for *every* downstream entity.

**The proposed optimisation.** After re-interpreting the changed entity, embed its OLD and NEW paragraph with the same embedding model and take the cosine similarity. If the two are nearly identical — the proposal names cosine distance below 0.01, i.e. similarity ≥ 0.99 — conclude the meaning did not really move and do not propagate downstream. Same test at every hop.

Three unmeasured numbers decide whether that can work:

1. **The noise floor.** The paragraph is written by an LLM, which is not deterministic. Asked twice, independently, about the *same* entity with the *same* definition, how similar are the two paragraphs? If two answers to an identical question are typically only 0.95 similar, a rule that fires at 0.99 can never fire.
2. **The size of a real change**, in graded steps from cosmetic rename to complete replacement of the definition body.
3. **What happens downstream** to a lemma whose own statement was untouched. If those paragraphs come back inside the noise floor, the re-interpretation that produced them was money spent for nothing.

Throughout, **cosine similarity** is the dot product of two unit-length vectors (the embedding model returns unit vectors, so the dot product *is* the cosine). **Cosine distance** is `1 − similarity`; "distance below 0.01" means "similarity ≥ 0.99".

## 1. What actually ran

| | |
|---|---|
| Date | 2026-09-07, interpretation runs 13:34–13:48 local |
| Interpretation driver | production default: no `--driver`, no `INTERPRETATION_DRIVER`, no `Semantic_Embedding.interpretation_driver` declared, so `_resolve_driver` fell through to `ClaudeCode` with an empty model = "let the Claude Code CLI pick its own configured default" |
| Interpretation model that actually served | `claude-opus-4-8`, back-filled from the response stream. All three database rows read `ClaudeCode.claude-opus-4-8`. |
| Embedding driver / endpoint / model | `OpenAI_Embedding_Provider` / `https://api.fireworks.ai/inference/v1` / `Qwen/Qwen3-Embedding-8B`, 4096 dims, `normalize: true` |
| Embedding call | `Embedding_Provider.embed(texts, role="document")` — the production document template is applied |
| Isabelle | 2025-2, session `Semantic_Embedding` (its heap did not exist and was built by `repl_server.sh` in 23 s), REPL on `127.0.0.1:6701`, external RPC host on `127.0.0.1:27301` |
| Database | isolated copy at `/var/tmp/qiyuan/sim_measure_db` (local ext4), 1.8 GB, left in place |

### Per-run cost and volume

| Run | Theory | Enumerated | Sent to LLM | Cost (USD) | input / cache-write / cache-read / output |
|---|---|---|---|---|---|
| A1 | `Sim_Measure_A1` | 92 | 91 | 1.4358 | 4 971 / 67 341 / 462 705 / 20 178 |
| A2 | `Sim_Measure_A2` | 92 | 86 | 1.1282 | 4 976 / 56 572 / 326 844 / 14 902 |
| B  | `Sim_Measure_B`  | 93 | 89 | 1.0464 | 4 976 / 52 850 / 320 961 / 13 233 |
| **Total** | | | **266** | **3.6104** | |

Embedding: 490 distinct texts, 47 765 tokens on Fireworks. That provider's per-token embedding price is not recorded in this repository, so no dollar figure is claimed for it.

### Safety gate

Before any spend, `Semantic_Store.dry_run false [Sim_Measure_A1]` was run through the REPL (`dry_run.py`). It reported the work set as exactly one theory name, `Sim_Measure_A1`, with 91 entities — no ancestor cone, no HOL theories.

### Database isolation

`SEMANTIC_DB_DIR=/var/tmp/qiyuan/sim_measure_db` was exported in every shell that started the REPL server, the RPC host, the collect driver, and the analysis. The copy was made with `mdb_env_copy` (py-lmdb `Environment.copy`), not `cp`, so a concurrent writer on the real store could not tear it; only `semantics.lmdb`, `theory_hash.lmdb`, `experience_index.lmdb` were copied, not the 17 GB vector store.

The real database's `semantics.lmdb/data.mdb` mtime **did** change during the experiment — but that is not us: this machine is shared, and three pre-existing attached RPC hosts belonging to other Isabelle sessions had it open before this work started. The check that actually proves isolation is our own RPC host's open-file table, which listed only `/var/tmp/qiyuan/sim_measure_db/{semantics,theory_hash}.lmdb/{data,lock}.mdb` and nothing under `~/.cache`. No `vector_*.lmdb` was created anywhere by this experiment.

### Deviations from the brief

1. **Entity count is 92–93 per theory, not 40–45.** The 7 root commands and 29 hand-written lemmas are exactly as specified; the surplus is what Isabelle's `definition`/`fun`/`datatype`/`inductive`/`locale` packages generate automatically (`kolvar_def`, `galmuth.simps`, `quilm.induct`, `plerx.intros`, …), all of which the pipeline treats as interpretable entities. Left as is — cheap, and a larger sample.
2. **The `abbreviation` is the CONTROL root, not a graded one.** Isabelle expands an `abbreviation` at parse time, so changing its body silently changes the *elaborated statements* of every lemma written over it — which would violate the "downstream statements unchanged" requirement. So `vondel` is identical in all three theories and the six grades went on the other six roots.
3. **The four `vondel_*` lemmas dropped out of the comparison anyway**, for the same underlying reason: because the abbreviation is expanded away, those statements mention no constant local to the scratch theory, so the pipeline (which keys a theorem by the XOR of the theories of the constants it mentions) computed the *same* universal key in all three runs; A2 and B found A1's record cached and reused its text verbatim. Such a pair is not two independent interpretations and would contribute a spurious 1.0, so it is excluded everywhere. Same happened to `galmuth.cases` (its statement *is* `list.exhaust`, already in the copied production DB) and `dremnok.zug_law`.
4. **`galmuth.simps` shifted index.** The cosmetic reorder makes A1/A2's `simps(2)` into B's `simps(1)`; name-based pairing would compare the cons equation against the nil equation, so those rows fall out of the intersection.
5. **A secondary measurement was added.** The proposal compares interpretation paragraphs; the vector store actually embeds `pretty_print + "\n" + interpretation` (`document_text.entity_document_text`). Both were embedded; §6.7 reports the production-document-text distributions too.

After exclusions, **85 entities** are present in all three runs and were genuinely interpreted independently in each. Everything below is computed on those 85.

## 2. The graded modifications

All three theories import `Semantic_Embedding.Semantic_Embedding`, contain the same seven roots and the same 29 hand-written lemmas (all `sorry`), and are byte-identical apart from the lines below. `Sim_Measure_A2.thy` differs from `Sim_Measure_A1.thy` in the theory name only (verified byte-identical otherwise).

| Root | Root command | Grade | Exact change, A1 → B |
|---|---|---|---|
| `galmuth` | `fun` over `nat list` | **(a) cosmetic** | equations swapped in order and bound variables renamed: `"galmuth [] = 0" \| "galmuth (x # xs) = …"` → `"galmuth (a # as) = …" \| "galmuth [] = 0"`. Meaning identical. |
| `kolvar` | `definition` over `nat` | **(b) small numeric tweak** | `"kolvar m n = m * n + 1"` → `"kolvar m n = m * n + 2"` |
| `narquil` | `fun` over datatype `quilm` | **(c) condition change** | `"narquil (Brint n) = (if n < 5 then 1 else 0)"` → `(if n <= 5 then 1 else 0)` |
| `plerx` | `inductive` over `nat` | **(d) negation / flip** | `plerx_base: "plerx 0"` → `plerx_base: "plerx 1"`. Held of exactly the even naturals; now holds of exactly the odd ones — exactly where it used to fail. |
| `tirneb` | `definition` over `int` | **(e) complete overhaul** | `"tirneb x = 3 * x + 1"` → `"tirneb x = x * x - 7"`. Same type signature, unrelated meaning. |
| `dremnok` | `locale` with one `assumes` | **(f) locale assumption** | `assumes zug_law: "zug x y = zug y x"` (commutativity) → `assumes zug_law: "zug (zug x y) z = zug x (zug y z)"` (associativity). Fact name kept so entities still pair. |
| `vondel` | `abbreviation` | **control** | unchanged in all three |
| `quilm` | `datatype` (`narquil` lives on it) | **unchanged** | the datatype itself is identical in all three; only `narquil` was modified |

Lemma statements in B are exactly those in A1, even where the modification makes them false.

**Terminology used below.** A **definitional entity of a root** is one that Isabelle's package generated out of the root command itself — the constant, its `_def`, its `simps`/`cases`/`induct`/`elims`/`intros`, the locale predicate; these are the entities whose own content the edit changed. A **downstream lemma** is one of the 29 hand-written lemmas, whose statement is unchanged between A1 and B. Splitting on the stored statement text alone would be wrong here: a constant's stored statement is only its type signature, so replacing `3 * x + 1` by `x * x - 7` leaves `tirneb`'s statement untouched even though `tirneb` is precisely what changed.

## 3. The noise floor: A1 versus A2

Byte-identical sources apart from the theory name, each interpreted by its own independent agent session. Pure run-to-run variation.

**All 85 entities:**

| min | p10 | p25 | median | p75 | p90 | max | mean |
|---|---|---|---|---|---|---|---|
| 0.7342 | 0.9169 | 0.9345 | **0.9579** | 0.9748 | 0.9834 | 0.9925 | 0.9505 |

**By kind:**

| kind | n | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| lemma | 60 | 0.7342 | 0.9331 | 0.9568 | 0.9734 | 0.9925 |
| constant | 14 | 0.8932 | 0.9443 | 0.9490 | 0.9662 | 0.9861 |
| introduction rule | 3 | 0.9748 | 0.9748 | 0.9801 | 0.9907 | 0.9907 |
| case-split rule | 2 | 0.9670 | — | 0.9670 | 0.9799 | 0.9799 |
| elimination rule | 2 | 0.9336 | — | 0.9336 | 0.9551 | 0.9551 |
| induction rule | 2 | 0.9745 | — | 0.9745 | 0.9864 | 0.9864 |
| locale | 1 | — | — | 0.9597 | — | — |
| type | 1 | — | — | 0.9185 | — | — |

(Kinds with fewer than five members are listed for completeness; conclude nothing from them.)

**The headline: only 2 of 85 pairs (2.4 %) reach similarity 0.99.** Asking the same agent the same question twice yields paragraphs that a 0.01-cosine-distance test calls "different" 97.6 % of the time.

## 4. Real change: the 31 definitional entities of the six modified roots

`A1~A2` is that entity's own noise level. Bold = the before/after similarity came out **at or above** its own noise, i.e. a real edit the embedding cannot distinguish from the agent rephrasing itself.

| entity | kind | root | grade | A1~A2 | A1~B | A2~B |
|---|---|---|---|---|---|---|
| `galmuth` | constant | galmuth | a-cosmetic | 0.9490 | 0.9472 | 0.9817 |
| `galmuth_dom` | constant | galmuth | a-cosmetic | 0.9548 | **0.9679** | 0.9315 |
| `galmuth.elims` | elimination rule | galmuth | a-cosmetic | 0.9551 | 0.9038 | 0.8857 |
| `galmuth.elims` | lemma | galmuth | a-cosmetic | 0.9551 | 0.9038 | 0.8857 |
| `kolvar` | constant | kolvar | b-numeric | 0.9834 | 0.9289 | 0.9278 |
| `kolvar_def` | lemma | kolvar | b-numeric | 0.9784 | **0.9834** | 0.9568 |
| `narquil` | constant | narquil | c-condition | 0.9455 | 0.9205 | 0.9617 |
| `narquil_dom` | constant | narquil | c-condition | 0.8932 | **0.9632** | 0.9192 |
| `narquil.cases` | lemma | narquil | c-condition | 0.9770 | 0.9543 | 0.9609 |
| `narquil.induct` | lemma | narquil | c-condition | 0.9360 | **0.9585** | 0.9353 |
| `narquil.simps(1)` | lemma | narquil | c-condition | 0.9865 | 0.9778 | 0.9788 |
| `narquil.simps(2)` | lemma | narquil | c-condition | 0.9925 | 0.9266 | 0.9178 |
| `narquil.elims` | elimination rule | narquil | c-condition | 0.9336 | 0.9009 | 0.8819 |
| `narquil.elims` | lemma | narquil | c-condition | 0.9336 | 0.9009 | 0.8819 |
| `plerx` | constant | plerx | d-negation | 0.9590 | 0.9185 | 0.8695 |
| `plerx.intros(1)` | introduction rule | plerx | d-negation | 0.9907 | 0.9089 | 0.9092 |
| `plerx.intros(1)` | lemma | plerx | d-negation | 0.9621 | 0.9121 | 0.9092 |
| `plerx.intros(2)` | introduction rule | plerx | d-negation | 0.9801 | 0.9761 | 0.9850 |
| `plerx.intros(2)` | lemma | plerx | d-negation | 0.9690 | **0.9705** | 0.9850 |
| `plerx.cases` | case-split rule | plerx | d-negation | 0.9799 | **0.9800** | 0.9730 |
| `plerx.cases` | lemma | plerx | d-negation | 0.9680 | **0.9738** | 0.9730 |
| `plerx.induct` | lemma | plerx | d-negation | 0.9833 | 0.9817 | 0.9878 |
| `plerx.inducts` | induction rule | plerx | d-negation | 0.9864 | 0.9798 | 0.9843 |
| `plerx.simps` | lemma | plerx | d-negation | 0.9463 | **0.9576** | 0.9495 |
| `tirneb` | constant | tirneb | e-overhaul | 0.9662 | 0.7771 | 0.7862 |
| `tirneb_def` | lemma | tirneb | e-overhaul | 0.9855 | 0.8572 | 0.8238 |
| `dremnok` | constant | dremnok | f-locale | 0.9359 | 0.8201 | 0.7894 |
| `dremnok` | locale | dremnok | f-locale | 0.9597 | 0.8548 | 0.8634 |
| `dremnok_def` | lemma | dremnok | f-locale | 0.9625 | 0.8422 | 0.8734 |
| `dremnok.intro` | introduction rule | dremnok | f-locale | 0.9748 | 0.8622 | 0.8841 |
| `dremnok.intro` | lemma | dremnok | f-locale | 0.9364 | 0.8800 | 0.8841 |

Distribution of the 31 `A1~B` values: **min 0.7771, median 0.9266, p90 0.9798, max 0.9834.** None reaches 0.99.

## 5. Downstream: the 25 hand-written lemmas whose statements did not change

| entity | root | grade | A1~A2 (noise) | A1~B | A2~B |
|---|---|---|---|---|---|
| `galmuth_append` | galmuth | a | 0.9412 | 0.9431 | 0.9759 |
| `galmuth_le_sum` | galmuth | a | 0.9682 | 0.9242 | 0.8969 |
| `galmuth_nil` | galmuth | a | 0.9534 | 0.9885 | 0.9567 |
| `galmuth_rev` | galmuth | a | 0.9598 | 0.9197 | 0.9015 |
| `galmuth_singleton` | galmuth | a | 0.9453 | 0.9544 | 0.9753 |
| `kolvar_commute` | kolvar | b | 0.9827 | 0.9755 | 0.9621 |
| `kolvar_mono_left` | kolvar | b | 0.9794 | 0.9931 | 0.9794 |
| `kolvar_positive` | kolvar | b | 0.9794 | 0.9824 | 0.9975 |
| `kolvar_zero_right` | kolvar | b | 0.9203 | 0.9259 | 0.9914 |
| `narquil_glaive_assoc` | narquil | c | 0.9579 | 0.9248 | 0.9368 |
| `narquil_glaive_commute` | narquil | c | 0.9491 | 0.9351 | 0.8762 |
| `narquil_large` | narquil | c | 0.9204 | 0.9187 | 0.9575 |
| `narquil_small` | narquil | c | 0.9202 | 0.9377 | 0.9466 |
| `plerx_add` | plerx | d | 0.8978 | 0.8978 | 1.0000 |
| `plerx_double` | plerx | d | 0.9276 | 0.8862 | 0.8947 |
| `plerx_not_one` | plerx | d | 0.7342 | 0.7547 | 0.9588 |
| `plerx_two` | plerx | d | 0.8830 | 0.9039 | 0.9289 |
| `tirneb_at_zero` | tirneb | e | 0.9137 | 0.9078 | 0.9457 |
| `tirneb_injective` | tirneb | e | 0.9742 | 0.9926 | 0.9764 |
| `tirneb_mono` | tirneb | e | 0.9834 | 0.9951 | 0.9831 |
| `tirneb_step` | tirneb | e | 0.9843 | 0.9504 | 0.9462 |
| `dremnok.swap_inner` | dremnok | f | 0.9807 | 0.8410 | 0.8567 |
| `dremnok.swap_outer` | dremnok | f | 0.9775 | 0.8467 | 0.8558 |
| `dremnok.swap_pair` | dremnok | f | 0.8967 | 0.9002 | 0.8670 |
| `dremnok.swap_triple` | dremnok | f | 0.9271 | 0.7745 | 0.8251 |

Per root:

| root | grade | n | noise min / median | downstream A1~B min / median |
|---|---|---|---|---|
| galmuth | a-cosmetic | 5 | 0.9412 / 0.9534 | 0.9197 / 0.9431 |
| kolvar | b-numeric | 4 | 0.9203 / 0.9794 | 0.9259 / 0.9824 |
| narquil | c-condition | 4 | 0.9202 / 0.9348 | 0.9187 / 0.9351 |
| plerx | d-negation | 4 | 0.7342 / 0.8904 | 0.7547 / 0.8978 |
| tirneb | e-overhaul | 4 | 0.9137 / 0.9788 | 0.9078 / 0.9926 |
| dremnok | f-locale | 4 | 0.8967 / 0.9523 | 0.7745 / 0.8467 |

**Control groups** (nothing upstream moved): the 28 definitional entities of the unchanged datatype `quilm`, plus the control abbreviation constant `vondel` (`A1~A2` 0.9861, `A1~B` 0.9557). For these 29, `A1~B` has min 0.8187, median 0.9505 — indistinguishable from their own noise (median 0.9467).

**The paired test** — for the *same entity*, `A1~B` minus its own `A1~A2`. Near zero means the B run's paragraph differs from A1's no more than two runs of the *unchanged* source differ:

| group | n | min | p25 | median | p75 | max | mean |
|---|---|---|---|---|---|---|---|
| downstream lemmas of a changed root | 25 | −0.1526 | −0.0339 | **0.0000** | +0.0117 | +0.0352 | −0.0193 |
| definitional entities of a changed root | 31 | −0.1891 | −0.0564 | −0.0327 | −0.0015 | +0.0700 | −0.0397 |
| definitional entities of an unchanged root (control) | 29 | −0.1284 | −0.0285 | −0.0012 | +0.0111 | +0.0433 | −0.0116 |

The downstream group's median is exactly zero and its whole interquartile range (−0.034 … +0.012) sits inside the control group's (−0.029 … +0.011).

## 6. Analysis

### 6.1 The proposed 0.01-distance threshold never fires

Of 85 no-change pairs, 2 reach 0.99. Of 31 real root changes, **none** does — the highest is `kolvar_def` at 0.9834. A rule "stop propagating when similarity ≥ 0.99" would never once have suppressed a propagation here (0 of 31), so it would save nothing while adding two embedding calls per changed entity. **It is a no-op.** The reason: the agent's own run-to-run variation (median 0.9579 between two answers to an *identical* question) is an order of magnitude larger than the 0.01 budget.

### 6.2 No threshold on this signal separates the two populations

Noise runs 0.7342–0.9925; real change runs 0.7771–0.9834. Almost complete overlap.

| threshold | no-change pairs still called "changed" | real changes wrongly called "unchanged" |
|---|---|---|
| ≥ 0.99 | 83 / 85 (98 %) | 0 / 31 (0 %) |
| ≥ 0.98 | 70 / 85 (82 %) | 3 / 31 (10 %) |
| ≥ 0.97 | 59 / 85 (69 %) | 8 / 31 (26 %) |
| ≥ 0.96 | 46 / 85 (54 %) | 10 / 31 (32 %) |
| ≥ 0.95 | 37 / 85 (44 %) | 13 / 31 (42 %) |
| ≥ 0.94 | 27 / 85 (32 %) | 14 / 31 (45 %) |
| ≥ 0.92 | 10 / 85 (12 %) | 17 / 31 (55 %) |
| ≥ 0.90 |  6 / 85 (7 %)  | 24 / 31 (77 %) |

To suppress even half the useless propagations you must accept losing roughly a third of the real ones — a third of genuinely stale entities keeping a wrong English description indefinitely.

### 6.3 Does cosmetic look like noise? Yes

Grade (a) is invisible where it should be: constant `galmuth` 0.9472 against its own noise 0.9490; its five downstream lemmas median 0.9431 against noise median 0.9534. The one place it shows is `galmuth.elims` (0.9038), because that rule's printed statement literally lists the two cases in source order — a correct detection of a real (if meaningless) textual difference, not a failure.

### 6.4 Does negation get caught? Only partly, and not where it matters

Grade (d) flipped `plerx` from "exactly the even naturals" to "exactly the odd naturals" — it now holds exactly where it used to fail.

- The base introduction rule (`plerx 0` → `plerx 1`) dropped to 0.9089 against noise 0.9907 — clearly caught.
- But `plerx.cases` came back at 0.9800 against noise 0.9799, and `plerx.induct` at 0.9817 against 0.9833. Both *inside* their own noise: the paragraphs differ only in "either `a` equals `0`" versus "either `a` equals `1`", and the embedding is essentially blind to that.
- The four downstream lemmas: median 0.8978 against noise median 0.8904 — no signal at all, even though `plerx_two: plerx 2` went from true to false.

So the known weakness of embeddings on negation and small symbolic differences does bite, and it bites hardest on exactly the entities a propagation gate would be consulted about.

### 6.5 What fraction of downstream re-interpretation was wasted?

Of the 25 downstream lemmas whose upstream really changed:

- **25/25 (100 %)** landed at or above the global noise minimum (0.7342);
- **16/25 (64 %)** at or above the global noise p10 (0.9169);
- **13/25 (52 %)** at or above *that entity's own* A1-vs-A2 similarity — the re-interpretation moved the text less than a second identical run would have.

The one grade where downstream text genuinely moved is (f), the locale assumption: three of four `dremnok.*` lemmas fell far below their own noise (0.8410 vs 0.9807; 0.8467 vs 0.9775; 0.7745 vs 0.9271). The texts show why — every such lemma is stated under hypothesis `dremnok zug`, and the agent spells it out: "assuming the binary operation `zug` is commutative" became "assuming `dremnok zug` (so `zug` is associative)".

**The structural finding: whether a downstream re-interpretation is worth anything depends on whether the downstream paragraph happens to quote the upstream definition, and no upstream-only similarity threshold can predict that in advance.** `tirneb_mono`'s paragraph never mentions `3 * x + 1`, so replacing the body wholesale changed nothing.

### 6.6 The measurement point matters

For one and the same edit, different definitional entities of the same root give very different similarities. Grade (b) (`+1` → `+2`) put `kolvar_def` at 0.9834 (**above** its own noise 0.9784, undetectable) but the constant `kolvar` at 0.9289 (below its noise 0.9834, detectable). Any rule of this shape must also specify *which* entity's paragraphs it compares, and that choice changes the outcome.

### 6.7 The same picture on the production document text

The vector store embeds `kind name: statement` followed by the paragraph. Redoing everything on that text pushes all numbers up (the shared statement prefix pulls similarity towards 1) but changes nothing qualitatively:

| population | n | min | p10 | median | p90 | max |
|---|---|---|---|---|---|---|
| noise, A1~A2 | 85 | 0.8326 | 0.9451 | 0.9756 | 0.9915 | 0.9965 |
| real change, A1~B | 31 | 0.8437 | 0.8859 | 0.9543 | 0.9818 | 0.9898 |
| downstream, A1~B | 25 | 0.8185 | 0.9062 | 0.9624 | 0.9943 | 0.9962 |

The real-change median (0.9543) sits *above* the noise p10 (0.9451); the ranges still overlap almost entirely; only 15 of 85 no-change pairs reach 0.99. Same conclusion.

### 6.8 What the sample size does and does not support

**Supported.**
- The noise-floor distribution itself. 85 entities, each interpreted twice independently, is enough to say with confidence that two runs of this agent on identical input give median cosine similarity ≈ 0.96 and essentially never reach 0.99. That single fact suffices to kill the 0.01-distance threshold, and it does not depend on any graded modification.
- The gross overlap of the two populations: noise min 0.7342 is far below real-change max 0.9834, and the aggregate medians differ by 0.03 against a noise interquartile width of 0.04.
- The direction of the downstream result: downstream paragraphs of a changed root moved, in the median, exactly as much as they move between two identical runs.

**Not supported.**
- Any per-grade conclusion at the level of a single number. Each grade has one edit on one root and 4–5 downstream lemmas. The per-root rows are illustrations, not estimates; a different `+1 → +2` could land anywhere in 0.9–0.99.
- Any per-entity noise estimate: each entity's noise comes from a single A1/A2 pair. The *distribution* of paired differences is meaningful; individual rows are not.
- Independence between entities: all ~91 entities of one theory were interpreted by one agent session sharing one conversation, one file, one system prompt. Correlated variation is likely and unmodelled.
- Generalisation beyond these inputs: one toy theory of one-line statements, one interpretation model (`claude-opus-4-8`), one embedding model (`Qwen/Qwen3-Embedding-8B`). Real AFP entities have much longer statements, and longer texts generally embed more stably, so the noise floor there could be narrower — but it would have to become *dramatically* narrower (median above 0.99 rather than 0.96) before the proposal's threshold became usable.
- Anything about how often, in real work, a downstream paragraph quotes its upstream definition. §6.5 shows that this is the property that decides whether a re-interpretation is worth anything, and this experiment contains exactly one root (the locale) where it happens.

### 6.9 Conclusion

**As specified, the optimisation cannot work.** The threshold is more than an order of magnitude tighter than the interpretation agent's own reproducibility, so it would never fire; and loosening it enough to fire buys suppression of useless propagations only at the price of leaving a comparable fraction of genuinely stale entities un-refreshed, because the two populations overlap almost completely.

If a "did the meaning really move?" gate is still wanted, the signal must come from somewhere with far less variance than a freshly generated English paragraph. Three directions the data point at, none measured here:

- compare the *formal* content rather than the English — which is what the existing `Semantic_Digest` already does, and it is exact;
- ask a model to judge the two paragraphs directly ("do these describe the same thing?") instead of relying on a distance in embedding space, which is what fails on negation in §6.4;
- remove the variance at the source, by making the interpretation agent reproducible for identical input, and only then measure distances. Note that even a perfectly reproducible agent leaves the §6.5 problem intact: a downstream paragraph that never quotes its upstream definition will be identical before and after (so the gate would correctly skip it), but one that does quote it will change — and no upstream-only similarity test tells those two apart.

## 7. Texts, for eyeballing

### 7a. The five lowest-similarity noise pairs (A1 vs A2 — nothing changed)

**`plerx_not_one` [lemma], 0.7342** — statement `¬ plerx 1`
> **A1:** The inductive predicate `plerx` (which holds exactly of the even natural numbers) does not hold of one: `plerx 1` is false, i.e. `¬ plerx 1` (one is odd).
> **A2:** The number one does not satisfy the predicate `plerx`: `plerx 1` is false.

**`plerx_two` [lemma], 0.8830** — statement `plerx 2`
> **A1:** The predicate `plerx` holds of the number two, i.e. `plerx 2` is true (two is even).
> **A2:** The number two satisfies the predicate `plerx`: `plerx 2` holds.

**`narquil_dom` [constant], 0.8932** — statement `quilm ⇒ bool`
> **A1:** An auto-generated domain predicate for the recursive function `narquil`, which takes a `quilm` tree and returns a boolean. It holds of a given `quilm` value exactly when the recursive definition of `narquil` is well-defined (terminates) on that value. Because `narquil` recurses on strictly smaller subtrees, this predicate is true for every `quilm`.
> **A2:** The domain-condition predicate automatically generated for the recursive function `narquil`. It takes a `quilm` value and returns a boolean, holding of exactly those inputs for which the recursion defining `narquil` is well-defined (terminates).

**`dremnok.swap_pair` [lemma], 0.8967** — `dremnok ?zug ⟹ ?zug ?x ?y = ?zug ?y ?x`
> **A1:** Assuming the binary operation `zug` is commutative (`dremnok zug` holds), the operation commutes: `zug x y` equals `zug y x` for all `x` and `y`. This restates the commutativity assumption of the locale for an arbitrary operation known to satisfy `dremnok`.
> **A2:** Assuming the binary operation `zug` is commutative (`dremnok zug` holds), its two arguments may be exchanged: `zug x y` equals `zug y x`.

**`plerx_add` [lemma], 0.8978** — `⟦plerx ?m; plerx ?n⟧ ⟹ plerx (?m + ?n)`
> **A1:** The predicate `plerx` is closed under addition: if `plerx m` and `plerx n` both hold for natural numbers `m` and `n`, then `plerx (m + n)` holds (the sum of two even numbers is even).
> **A2:** The predicate `plerx` is closed under addition: if `plerx m` and `plerx n` both hold, then `plerx (m + n)` holds.

The pattern is the whole problem: the agent sometimes adds a parenthetical about what the entity *means* ("two is even", "the sum of two even numbers is even") and sometimes does not. That single stylistic coin flip costs 0.05–0.25 of cosine similarity — far more than most real edits cost.

### 7b. The five highest-similarity real-change pairs (A1 vs B, definition edited)

**`kolvar_def` [lemma], grade (b), 0.9834 — own noise 0.9784**
> `kolvar ?m ?n = ?m * ?n + 1` → `... + 2`
> **A1:** The defining equation of the function `kolvar`: for any two natural numbers `m` and `n`, the value `kolvar m n` equals the product of `m` and `n` plus one, i.e. `m * n + 1`.
> **B:** The defining equation of the function `kolvar`: for any two natural numbers `m` and `n`, the value `kolvar m n` equals the product of `m` and `n` plus two, that is `m * n + 2`.

**`plerx.induct` [lemma], grade (d), 0.9817 — noise 0.9833**
> `⟦plerx ?x; ?P 0; ⋀n. ⟦plerx n; ?P n⟧ ⟹ ?P (n + 2)⟧ ⟹ ?P ?x` → same with `?P 1`
> **A1:** The rule induction principle for the inductive predicate `plerx`. To prove that a property `P` holds of every natural number `x` satisfying `plerx x`, it suffices to prove `P 0` (the base case), and to prove `P (n + 2)` for every `n` for which `plerx n` holds and `P n` is already known (the step case). Given these, `P x` holds whenever `plerx x` holds.
> **B:** The rule induction principle for the inductive predicate `plerx`. To prove that a property `P` holds for every `x` satisfying `plerx x`, it suffices to prove: `P` holds for `1`; and for every `n`, if `plerx n` holds and `P` holds for `n`, then `P` holds for `n + 2`.

**`plerx.cases` [case-split rule], grade (d), 0.9800 — noise 0.9799**
> `⟦plerx ?a; ?a = 0 ⟹ ?P; ⋀n. ⟦?a = n + 2; plerx n⟧ ⟹ ?P⟧ ⟹ ?P` → same with `?a = 1`
> **A1:** The case-analysis rule for the inductive predicate `plerx`. Given that `plerx a` holds for some natural number `a`, and a goal `P` to prove, one may split into two cases matching the two ways `plerx` can be established: either `a` is zero, or `a` has the form `n + 2` for some natural number `n` with `plerx n` holding. If `P` follows in each case, then `P` holds.
> **B:** The case-analysis rule for the inductive predicate `plerx`. If `plerx a` holds, then to prove a goal `P` it suffices to handle the two ways `plerx a` could have been established: either `a` equals `1`, or `a` equals `n + 2` for some natural number `n` with `plerx n` holding. If `P` follows in both cases, then `P` holds.

**`plerx.inducts` [induction rule], grade (d), 0.9798 — noise 0.9864** — same `?P 0` → `?P 1` flip, same shape of texts.

**`narquil.simps(1)` [lemma], grade (c), 0.9778 — noise 0.9865**
> `narquil (Brint ?n) = (if ?n < 5 then 1 else 0)` → `(if ?n ≤ 5 then 1 else 0)`
> **A1:** The defining equation of `narquil` on a leaf: `narquil (Brint n)` equals one if the stored natural number `n` is less than five, and zero otherwise.
> **B:** The defining equation of `narquil` on a leaf: for a leaf `Brint n` carrying a natural number `n`, `narquil (Brint n)` equals one if `n` is less than or equal to five, and zero otherwise.

Four of these five are genuine changes in the formal statement that produced a before/after similarity at or barely below the entity's own noise — precisely the failure mode that makes a similarity gate unsafe.

### 7c. The five highest-similarity downstream pairs (statement unchanged, upstream edited)

Re-interpretations that produced nothing — the paragraph after the upstream change is *more* similar to the one before it than two identical runs were to each other.

**`tirneb_mono`, grade (e), 0.9951 — noise 0.9834**, statement (unchanged) `?x ≤ ?y ⟹ tirneb ?x ≤ tirneb ?y`
> **A1:** The function `tirneb` is monotonic (non-decreasing): for integers `x` and `y`, if `x` is less than or equal to `y`, then `tirneb x` is less than or equal to `tirneb y`.
> **B:** The function `tirneb` is monotone (non-decreasing): for integers `x` and `y`, if `x` is less than or equal to `y`, then `tirneb x` is less than or equal to `tirneb y`.

The definition of `tirneb` had been replaced wholesale (`3 * x + 1` → `x * x − 7`, which is not monotone at all) and the paragraph changed by one word.

Also `kolvar_mono_left` (b) 0.9931 vs noise 0.9794; `tirneb_injective` (e) 0.9926 vs 0.9742; `galmuth_nil` (a) 0.9885 vs 0.9534; `kolvar_positive` (b) 0.9824 vs 0.9794 — all the same shape: the paragraph describes the lemma's own statement, never mentions the definition body, so it does not move when the body changes.

### 7d. The five lowest-similarity downstream pairs

**`plerx_not_one`, grade (d), 0.7547 — but its own noise is 0.7342.** Noise, not signal.

**`dremnok.swap_triple`, grade (f), 0.7745 — noise 0.9271**
> **A1:** Assuming the binary operation `zug` is commutative (`dremnok zug` holds), an outer application commutes with its compound left argument: `zug (zug x y) z` equals `zug z (zug x y)` for all `x`, `y`, and `z`.
> **B:** A consequence within the `dremnok` locale: assuming `dremnok zug` (so `zug` is associative), the combined value `zug x y` can be moved from the left operand to the right operand, that is `zug (zug x y) z` equals `zug z (zug x y)`.

**`dremnok.swap_inner`, (f), 0.8410 — noise 0.9807** and **`dremnok.swap_outer`, (f), 0.8467 — noise 0.9775**: same shape — the locale assumption is restated in words inside each paragraph, so changing it changes them.

**`plerx_double`, (d), 0.8862 — noise 0.9276**
> **A1:** The inductive predicate `plerx` holds of every doubled natural number: for any natural number `n`, `plerx (2 * n)` is true (twice any number is even).
> **B:** The predicate `plerx` holds for every even number: for any natural number `n`, `plerx (2 * n)` holds.

Even here the drop (0.9276 → 0.8862) is smaller than the gap between two *identical* runs of `plerx_not_one` (0.7342), so it cannot be separated from noise.

## 8. Where everything is

| | |
|---|---|
| Isolated database (left in place, as instructed) | `/var/tmp/qiyuan/sim_measure_db`, **1.8 GB**, ext4 local disk. Holds `semantics.lmdb`, `theory_hash.lmdb`, `experience_index.lmdb`, `embed_cache/`. All three runs' interpretations are in it, and the embed cache holds every vector computed here, so a follow-up can re-analyse without paying again. |
| Logs | `/var/tmp/qiyuan/sim_measure_logs/` — `repl.log`, `rpc_host.log`, `run_A1.log`, `run_A2.log`, `run_B.log`, `dryrun.txt`, `entities_A1.txt`, `stats.txt` |
| Artifacts | `contrib/Semantic_Embedding/ai-artifacts/similarity_measurement/` — three `.thy` files (plus the `.unicode.thy` copies the pipeline generated), `dry_run.py`, `analyze.py`, `stats.py`, `pairs.json`, `summary.csv`, `stats_output.txt` |
| Real database | `~/.cache/Isabelle_Semantic_Embedding` — never opened by any process of this experiment; nothing deleted |

**Cleanup done:** the REPL server (port 6701) and the RPC host (port 27301) were killed and both ports are free. Nothing was committed; no `git stash/checkout/reset/clean` was ever run. One side effect worth flagging: `repl_server.sh` built the `Semantic_Embedding` session heap (10.8 MB, `~/.isabelle/Isabelle2025-2/heaps/polyml-5.9.2_x86_64_32-linux/Semantic_Embedding`), which did not previously exist — that is inherent to starting the REPL on that base session, and no other `isabelle build` was run.
