PHASE 2 -- LOOKING FOR A USABLE DECISION RULE

Measurement run on 2026-09-07 in contrib/Semantic_Embedding, continuing
REPORT.md.  Raw data: pairs_phase2.json, judge_phase2.json.  Scripts:
analyze2.py, stats2.py, judge.py, judge_stats.py, digests.py.  Full printed
tables: stats2_output.txt, judge_stats_output.txt.


0. WHAT QUESTION PHASE 2 ANSWERS
================================

Phase 1 established one thing: when the semantic-interpretation agent is asked
the SAME question twice, the two English paragraphs it writes are only about
0.96 cosine-similar under the production embedding model.  The proposed
invalidation gate -- "stop propagating when the old and new paragraphs are at
least 0.99 similar" -- therefore never fires, and no single cut on that number
separates "the agent rephrased itself" from "the definition really changed".

Phase 2 asks the follow-up question: is there ANY decision rule, of any shape,
that does separate them well enough to use?  The answer is yes, and it is not a
threshold on an embedding distance -- it is an LLM asked directly whether the
two paragraphs say the same thing.  The numbers are in section 7 and the
recommendation in section 11.

Two words are used throughout with fixed meanings, because everything below is
a trade-off between them:

  a MISS -- the gate says "unchanged" when the meaning really did change.  The
    database keeps a wrong English description of the entity, and every entity
    downstream of it keeps a description built on the wrong one.  This is a
    correctness failure and it is silent.

  a FALSE ALARM -- the gate says "changed" when the meaning did not change.
    Nothing is wrong; the pipeline simply re-interprets downstream entities it
    did not need to.  This is exactly today's behaviour, so a false alarm costs
    money and nothing else.

SAVINGS below always means the fraction of useless propagations a rule
suppresses, i.e. one minus the false-alarm rate.


1. WHAT RAN AND WHAT IT COST
============================

New interpretation runs
-----------------------

Nine more theories were interpreted, each with the production default driver
(ClaudeCode, model claude-opus-4-8, the same as phase 1), each preceded by its
own Semantic_Store.dry_run safety gate.  Every gate returned a work set of
exactly the one scratch theory -- no ancestor cone -- with 86 to 88 entities.

  run              source content      purpose                       entities  cost USD
  Sim_Measure_A3   identical to A1     third no-change sample            86     1.1973
  Sim_Measure_A4   identical to A1     fourth no-change sample           86     1.3333
  Sim_Measure_A5   identical to A1     fifth no-change sample            86     1.1656
  Sim_Measure_B2   second rotation     more real changes                 88     1.0360
  Sim_Measure_B3   third rotation      more real changes                 88     1.0968
  Sim_Measure_B4   fourth rotation     more real changes                 88     1.1768
  Sim_Measure_B1b  identical to B      second sample of the NEW text     87     1.0332
  Sim_Measure_B1c  identical to B      third sample of the NEW text      87     1.0506
  Sim_Measure_B2b  identical to B2     second sample of the NEW text     87     1.0126
  ------------------------------------------------------------------------------------
  phase-2 total                                                                10.1022

Phase 1 spent 3.6104, so the whole experiment has cost USD 13.71 of
interpretation.  Twelve runs now exist in the isolated database: five of the
unchanged content, three of the B content, two of the B2 content, one each of
B3 and B4.

The graded modifications, rotated
---------------------------------

Every B variant edits all six modifiable roots at once, one grade each, and the
grade assigned to each root rotates so that each grade is instantiated on four
different roots.  Lemma statements are identical to A1 in all four variants.

  root                            B            B2           B3           B4
  kolvar   (definition, nat)      b-numeric    a-cosmetic   e-overhaul   c-condition
  tirneb   (definition, int)      e-overhaul   b-numeric    a-cosmetic   d-negation
  galmuth  (fun, list)            a-cosmetic   c-condition  d-negation   e-overhaul
  narquil  (fun, on datatype)     c-condition  d-negation   b-numeric    a-cosmetic
  plerx    (inductive)            d-negation   e-overhaul   c-condition  b-numeric
  dremnok  (locale)               f-assumes    f-assumes    f-assumes    f-assumes
  vondel   (abbreviation)         control      control      control      control
  quilm    (datatype)             unchanged    unchanged    unchanged    unchanged

The new edits, exactly (A1 -> variant):

  B2  kolvar   a  "kolvar m n = m * n + 1"  ->  "kolvar a b = a * b + 1"
  B2  tirneb   b  3 * x + 1  ->  3 * x + 4
  B2  galmuth  c  if x mod 2 = 0  ->  if x mod 2 = 0 & x < 100
  B2  narquil  d  (if n < 5 then 1 else 0)  ->  (if n < 5 then 0 else 1)
  B2  plerx    e  base plerx 0, step +2  ->  base plerx 3, step plerx (3 * n)
  B2  dremnok  f  commutativity  ->  zug x x = x   (idempotence)
  B3  kolvar   e  m * n + 1  ->  (if m < n then n - m else m - n)
  B3  tirneb   a  "tirneb x = 3 * x + 1"  ->  "tirneb t = 3 * t + 1"
  B3  galmuth  d  if x mod 2 = 0  ->  if x mod 2 = 1
  B3  narquil  b  if n < 5  ->  if n < 6
  B3  plerx    c  step plerx n ==> plerx (n+2)  ->  plerx n ==> 2 < n ==> plerx (n+2)
  B3  dremnok  f  commutativity  ->  zug (zug x y) y = x
  B4  kolvar   c  m * n + 1  ->  (if m <= n then m * n + 1 else 0)
  B4  tirneb   d  3 * x + 1  ->  - (3 * x + 1)
  B4  galmuth  e  sum of even entries  ->  galmuth [] = 1, galmuth (x#xs) = x * galmuth xs
  B4  narquil  a  bound variables renamed n,s,t -> k,u,v
  B4  plerx    b  step +2  ->  +3
  B4  dremnok  f  commutativity  ->  zug x (zug x y) = y

Embedding
---------

3086 distinct texts embedded with the production stack
(OpenAI_Embedding_Provider -> https://api.fireworks.ai/inference/v1,
Qwen/Qwen3-Embedding-8B, 4096 dimensions, normalised, document template), in
five text forms -- see section 9.  The embedding cache in the isolated database
holds every vector, so re-analysis is free.

LLM judge
---------

943 calls to gpt-5.6-sol through the local auth2api proxy that the AoA
Codex-API driver already uses (AOA_CODEX_API_BASE_URL + AOA_CODEX_API_KEY,
openai.AsyncOpenAI, the Responses endpoint) -- no new API plumbing, the same
client and the same two environment variables.  850 judgements, 265 929 input
tokens and 43 870 output tokens in total (about 280 in / 46 out per judgement).
This backend runs on a ChatGPT subscription, so it draws plan credits rather
than dollars; the first pass lost 93 calls to HTTP 429, and a second pass with
concurrency 4 and a longer backoff completed all of them, so the final data set
has ZERO unparsable or errored judgements.

The data set
------------

85 entities are present in all twelve runs and were genuinely interpreted
independently in each.  (The same six entities as in phase 1 fall out: the four
vondel_* lemmas, galmuth.cases and the galmuth.simps / galmuth.induct family,
all because an abbreviation is expanded at parse time or because a fun reorder
renumbers simps.  See REPORT.md section 1.)  That gives 4165 pairs of one
entity between two runs.


2. THE FOUR POPULATIONS
=======================

Every pair is one entity compared between two runs.  A pair whose two runs
stored the entity under the SAME universal key is never used: the second run
read the first run's text out of the cache, so it is not two independent
interpretations.

  population    n     what it is                                what a gate should say
  no-change    1190   two runs of the SAME source content       "unchanged"
  change       1085   an unchanged run against a modified run,  "changed"
                      for an entity the definition package
                      generated out of the root command that
                      was edited
  control      1015   ditto, but for an entity of a root that   "unchanged"
                      was NOT edited (datatype quilm,
                      abbreviation vondel)
  downstream    875   ditto, for a hand-written lemma whose     this is the open question
                      own statement did not change but whose
                      root was edited

Similarity distributions, production embedding, interpretation text:

  population    n     min      p10      median   p90      max      mean
  no-change    1190   0.7342   0.8973   0.9569   0.9847   1.0000   0.9480
  change       1085   0.5709   0.8228   0.9320   0.9780   1.0000   0.9137
  control      1015   0.6755   0.8897   0.9461   0.9783   0.9975   0.9386
  downstream    875   0.7231   0.8551   0.9301   0.9834   1.0000   0.9231

Fourteen times the phase-1 sample, and the picture is unchanged: the two
populations that a gate must tell apart have medians 0.957 and 0.932, against a
no-change spread that runs from 0.73 to 1.00.

A CAVEAT ON THE "change" LABEL, which matters for every table below.  Labelling
an entity "changed" because the root command that generated it was edited is
too crude in two ways, and section 7 corrects for both:

  1. a COSMETIC edit (grade a) does not change any meaning, so nothing about
     that entity's English needs updating -- a gate that stops propagation
     there is right, not wrong;
  2. editing a root regenerates facts whose meaning does not depend on the
     edited part.  The termination predicate galmuth_dom holds for every list
     whether the function sums the even or the odd entries; narquil.cases
     splits a quilm value the same way whether the leaf threshold is 5 or 6.


3. CANDIDATE 1 -- A GLOBAL THRESHOLD, ON FOURTEEN TIMES THE SAMPLE
==================================================================

Rule: changed iff sim(old, new) < cut.  Production embedding.

On the interpretation text (what the proposal compares)
-------------------------------------------------------

  cut      no-change called "changed"   real change called "unchanged"   savings
  0.999               99.7 %                        0.1 %                 0.3 %
  0.995               98.2 %                        0.2 %                 1.8 %
  0.99                95.5 %                        1.0 %                 4.5 %
  0.985               90.3 %                        3.3 %                 9.7 %
  0.98                82.9 %                        7.8 %                17.1 %
  0.97                67.9 %                       18.2 %                32.1 %
  0.96                54.5 %                       28.3 %                45.5 %
  0.95                42.7 %                       37.7 %                57.3 %
  0.94                33.2 %                       44.1 %                66.8 %
  0.93                25.0 %                       52.1 %                75.0 %
  0.92                19.6 %                       58.0 %                80.4 %
  0.90                10.8 %                       66.5 %                89.2 %
  0.88                 5.3 %                       75.2 %                94.7 %
  0.85                 1.5 %                       83.1 %                98.5 %
  0.80                 0.3 %                       93.4 %                99.7 %

Best operating points: at most 1 % misses buys 1.8 % savings; at most 5 % misses
buys 9.7 %; at most 10 % buys 17.1 %; at most 20 % buys 32.1 %.  Equal-error
point: cut 0.95, with 42.7 % false alarms and 37.7 % misses.

On the production document text ("kind name: statement" + paragraph)
--------------------------------------------------------------------

This is what the vector store actually holds, and it is materially better,
because the statement prefix is a formal signal rather than free prose.

  cut      no-change called "changed"   real change called "unchanged"   savings
  0.995               96.7 %                        0.0 %                 3.3 %
  0.99                89.2 %                        0.9 %                10.8 %
  0.985               77.6 %                        4.5 %                22.4 %
  0.98                67.6 %                       10.9 %                32.4 %
  0.975               56.4 %                       17.0 %                43.6 %
  0.97                45.3 %                       24.4 %                54.7 %
  0.96                29.2 %                       36.2 %                70.8 %
  0.95                19.7 %                       46.5 %                80.3 %
  0.94                11.8 %                       55.6 %                88.2 %
  0.92                 3.9 %                       68.1 %                96.1 %
  0.90                 1.3 %                       77.1 %                98.7 %

Best operating points: at most 1 % misses buys 10.8 % savings; at most 5 % buys
22.4 %; at most 20 % buys 43.6 %.  Equal-error point: cut 0.96, 29.2 % false
alarms and 36.2 % misses.

VERDICT.  The larger sample does not rescue the global threshold, but it does
show the proposal was measuring the wrong text: switching from the paragraph to
the production document text roughly doubles the savings at every miss rate.
Even so, the best honest reading is "at a 5 % miss rate you save 22 % of the
propagations" -- and a 5 % silent-staleness rate is not a rate anyone should
accept for a cache-correctness decision.

Discrimination as one number, the area under the ROC curve -- the probability
that a randomly chosen real change scores below a randomly chosen no-change
pair, where 0.5 is a coin flip:

  document text                                 AUC 0.7452
  interpretation text                           AUC 0.6631
  interpretation text, parentheticals stripped  AUC 0.6596
  first sentence only                           AUC 0.5902
  first sentence, parentheticals stripped       AUC 0.5818


4. CANDIDATE 2a -- AN ORACLE PER-ENTITY RELATIVE RULE
=====================================================

The idea from phase 1: each entity has its own noise level (0.73 for
plerx_not_one, 0.99 for plerx.intros(1)), so compare against that entity's own
spread rather than a global cut.  With five no-change runs there are ten
no-change similarities per entity.  The rule is

    changed iff sim(old, new) < (that entity's minimum no-change similarity) - margin

evaluated leave-one-out on the no-change side so a pair is never judged against
itself.  This is an UPPER BOUND, NOT A PRODUCTION RULE: it needs several stored
samples of the OLD text, and the database keeps one.

  margin   no-change called "changed"   real change called "unchanged"   savings
  -0.02              44.9 %                       25.3 %                55.1 %
  -0.01              27.6 %                       35.0 %                72.4 %
  -0.005             17.4 %                       40.7 %                82.6 %
   0.00               9.9 %                       47.1 %                90.1 %
  +0.01               2.8 %                       54.0 %                97.2 %
  +0.03               0.8 %                       62.2 %                99.2 %
  +0.05               0.2 %                       71.8 %                99.8 %

No margin reaches even a 20 % miss rate.  Equal-error point: 27.6 % false alarms
against 35.0 % misses -- barely better than the global document-text cut
(29.2 / 36.2), and that is with an oracle's worth of extra information.

VERDICT: PER-ENTITY CALIBRATION DOES NOT HELP.  This is the clearest negative
result of phase 2: the reason a global threshold fails is not that entities have
different noise levels, it is that for any single entity the real change is the
same size as the noise.


5. CANDIDATE 2b -- THE REALISTIC RESAMPLING RULE
================================================

The production-realisable version.  The database stores one old text.
Re-interpret the current source k times; for each entity compare the
old-vs-new similarities against the new-vs-new similarities of the same entity.
If the old text sits no further from the new ones than they sit from each other,
nothing moved.

Two statistics: "mean" (mean of sim(old, new_i) against mean of
sim(new_i, new_j)) and "minmax" (max_i sim(old, new_i) against
min_{i<j} sim(new_i, new_j)), both swept over an additive margin.

Best of the eight combinations (k in {2,3} x two statistics x two text forms),
on the document text with k = 2 and the mean statistic:

  margin   no-change called "changed"   real change called "unchanged"   savings
  -0.005             60.9 %                       15.5 %                39.1 %
   0.000             46.6 %                       22.4 %                53.4 %
  +0.005             31.4 %                       28.7 %                68.6 %
  +0.01              24.4 %                       34.5 %                75.6 %

Equal-error points for all eight:

  k  statistic  text            false alarms   misses
  2  mean       document           31.4 %      28.7 %
  2  minmax     document           33.3 %      30.2 %
  3  mean       document           25.8 %      36.1 %
  3  minmax     document           30.8 %      32.9 %
  2  mean       interpretation     36.6 %      37.1 %
  2  minmax     interpretation     33.3 %      40.3 %
  3  mean       interpretation     41.6 %      35.5 %
  3  minmax     interpretation     40.0 %      32.9 %

No combination reaches a 10 % miss rate at any margin.  Sample sizes: 2550
no-change and 620 change instances at k = 2; 1700 and 155 at k = 3.

VERDICT: RESAMPLING DOES NOT HELP EITHER, AND k = 3 IS NOT BETTER THAN k = 2.
It costs two or three extra LLM interpretations of every changed entity to buy
an error rate around 30 % on both sides -- worse than paying for the downstream
propagation you were trying to avoid.


6. CANDIDATE 3 -- OTHER EMBEDDING MODELS: NONE REACHABLE
========================================================

The embedding config knows three models on the configured endpoint.  Probed
directly with the account's own key:

  POST https://api.fireworks.ai/inference/v1/embeddings
    fireworks/harrier-oss-v1-27b           -> HTTP 400  "... not available"
    fireworks/llama-nv-embed-reasoning-3b  -> HTTP 400  "... not available"
    fireworks/qwen3-embedding-8b           -> HTTP 200

The local Codex proxy has no embeddings route (POST /v1/embeddings -> HTTP 404),
and the Isabelle settings carry no OpenAI, Mistral, Gemini, Cohere or DashScope
key.  Adding credentials was out of scope, so this candidate is SKIPPED, with
that evidence.  Only Qwen/Qwen3-Embedding-8B was reachable and every embedding
number in this report uses it.


7. CANDIDATE 4 -- AN LLM JUDGE INSTEAD OF A DISTANCE
====================================================

The comparator
--------------

gpt-5.6-sol, reasoning effort low, one call per pair, this prompt verbatim
({label} is "kind name", {t1} and {t2} the two paragraphs):

    You compare two English descriptions of the same named entity from an
    Isabelle/HOL theory (a constant, a lemma, a type, or a locale). The two
    descriptions were written independently and may differ in wording.

    Decide ONE thing: do the two descriptions describe the SAME mathematical
    object and assert the SAME thing? Wording, level of detail, examples and
    asides do not matter -- only whether the mathematical content is the same.
    If one description states a different value, a different condition, a
    different formula, a different assumption, or a different logical direction
    from the other, they are NOT the same.

    Entity: {label}

    Description 1:
    {t1}

    Description 2:
    {t2}

    Answer with a single JSON object and nothing else:
    {"same": true or false, "why": "<one sentence>"}

The two paragraphs are presented symmetrically and the model is never told which
is old, which is new, or that anything might have changed.

850 pairs were judged: for every one of the 85 entities, four no-change pairs
inside the unchanged content (A1~A2, A3~A4, A2~A5, A1~A4), two no-change pairs
inside modified content (B~B1b, B2~B2b), and one pair against each of the four
modified contents, each from a different unchanged run (A1~B, A2~B2, A3~B3,
A4~B4).

The raw confusion matrix
------------------------

  population                                     n     judge: same   judge: different
  no-change (truth: same)                       510        508              2
  control, root not edited (truth: same)        116        115              1
  definitional, root edited (labelled diff.)    124         36             88
  downstream (no ground truth)                  100         91              9

Read straight off: 3 false alarms in 626, and 36 of 124 labelled changes called
"same".

Correcting the ground truth
---------------------------

Both corrections announced in section 2 apply, and both make the judge look
better because the judge was right and the label was wrong.

Reclassifying cosmetic edits as "same" (a reordered fun equation or a renamed
bound variable changes no meaning, so stopping propagation there is correct):
0.5 % false alarms, 18.5 % misses.

Also excluding regenerated facts whose meaning does not depend on the edited
part.  The strict population is: grades b-f only, and either the entity's own
printed statement changed, or the entity IS the edited constant or locale
(whose printed statement is only its type signature).  87 pairs unambiguously
changed meaning; the other 663 judged pairs did not.

  ground truth                                 false alarms      misses      savings
  raw (root command edited => "different")     3/626 = 0.5 %   36/124 = 29.0 %  99.5 %
  cosmetic edits reclassified as "same"        3/642 = 0.5 %   20/108 = 18.5 %  99.5 %
  strict: only unambiguous meaning changes     5/663 = 0.8 %    1/87  =  1.1 %  99.2 %

The single miss under the strict truth is galmuth (the constant) between A4 and
B4, a grade-(e) overhaul.  It is worth reading, because it is not a judge error
about identical content:

  A4: "A function taking a list of natural numbers and returning a single
       natural number. It sums up those entries of the list that are even
       (divisible by two), ignoring the odd entries; the empty list yields
       zero."
  B4: "A function named `galmuth` that takes a list of natural numbers and
       returns a single natural number. It is defined by recursion over the
       list, computing one number from the sequence of elements; its recursion
       equations are stated separately."
  judge: "Both describe the same list-recursive natural-number function
       `galmuth`, with the second merely omitting the specific recursion
       equations that characterize it as summing the even entries."

The B4 paragraph is vague -- the interpretation agent declined to state what the
function computes -- so the judge had nothing to contradict.  The embedding
similarity of that pair is 0.611, the lowest in the whole data set; section 11
uses that fact.

The five false alarms are all one shape: one paragraph asserts something the
other leaves out, and the judge treats an added claim as a difference.

  entity          runs          cos      the judge's reason
  galmuth_dom     A2 vs A5     0.9706   one paragraph adds that the domain
                                        predicate holds for EVERY list
  galmuth_dom     A2 vs B2     0.9566   same
  galmuth_dom     A4 vs B4     0.9292   same
  tirneb_at_zero  B2 vs B2b    0.8957   one paragraph also quotes the defining
                                        formula
  vondel          A4 vs B4     0.6755   one paragraph omits the defining
                                        condition m * m < n

Three of the five are the same auto-generated termination predicate, whose
paragraphs vary in whether they assert totality -- a specific, fixable prompt
issue rather than a property of the method.

The production-relevant comparison
----------------------------------

In production the gate is only consulted when the formal comparator has already
fired, so the population that matters is ENTITIES WHOSE FORMAL CONTENT CHANGED
BUT WHOSE MEANING DID NOT.  In this data set that is 37 pairs: 16 cosmetic edits
plus 21 regenerated facts that do not depend on the edited part.

  comparator                              useless propagations suppressed   real changes missed
  LLM judge                                     35/37 = 94.6 %                1/87 = 1.1 %
  embedding, document text, cut 0.99             1/37 =  2.7 %                1/87 = 1.1 %
  embedding, document text, cut 0.985            2/37 =  5.4 %                4/87 = 4.6 %
  embedding, document text, cut 0.96            23/37 = 62.2 %               24/87 = 27.6 %

At the same miss rate the judge suppresses roughly 35 times as many useless
propagations as the best embedding threshold.

By grade
--------

  grade         n     judge said "different"
  a-cosmetic    16     0 %      -- correct: nothing changed
  b-numeric     22    72.7 %
  c-condition   24    75.0 %
  d-negation    24    70.8 %
  e-overhaul    18    94.4 %
  f-locale      20   100 %

The 25-29 % of grades b, c and d that the judge called "same" are almost
entirely the regenerated facts of section 2 -- which is why the strict truth
above drops the miss rate to 1.1 %.  Note in particular that grade (d),
NEGATION, is caught 70.8 % of the time by the judge and essentially never by the
embedding (phase 1 section 6.4): asked in words whether "holds of the even
numbers" and "holds of the odd numbers" are the same claim, a language model
says no; measured as a distance in embedding space, they are 0.98 similar.

Stability across runs
---------------------

  run pair             n     judge said "different"
  A1 vs A2            85      0 %
  A1 vs A4            85      0 %
  A2 vs A5            85      1.2 %
  A3 vs A4            85      0 %
  B  vs B1b           85      0 %
  B2 vs B2b           85      1.2 %

The judge is stable on both unchanged and modified content.

Downstream: what the judge says, and whether the paragraph quoted the definition
--------------------------------------------------------------------------------

The 100 judged downstream pairs are hand-written lemmas whose own statement did
not change but whose root was edited.  Against a mechanical indicator -- does
the old paragraph contain a marker of the part of the definition that changed
("plus one"/"+ 1" for kolvar; "three"/"3 * x" for tirneb; "even" for galmuth and
plerx; "five"/"n < 5" for narquil; "commutat"/"commutes" for dremnok):

  old paragraph quotes the definition   judge: same   judge: different
  yes                                        49              9
  no                                         42              0

  grade         quotes+same  quotes+diff  noquote+same  noquote+diff
  a-cosmetic         8            0             9            0
  b-numeric          6            0            10            0
  c-condition       10            1             6            0
  d-negation        10            0             7            0
  e-overhaul         7            0            10            0
  f-locale           8            8             0            0

This is the cleanest structural result of phase 2.  A DOWNSTREAM PARAGRAPH
CHANGES ITS MEANING ONLY WHEN IT QUOTED THE UPSTREAM DEFINITION, and in this
data set that happens for exactly one root: the locale, whose assumption every
one of its lemmas restates in words.  All eight grade-(f) downstream pairs whose
paragraph quotes the assumption were called "different"; every one of the 42
pairs that did not quote the definition was called "same".  Overall 91 OF 100
DOWNSTREAM RE-INTERPRETATIONS PRODUCED NO CHANGE OF MEANING -- measured by a
comparator with a 0.8 % false-alarm rate, which is a far more trustworthy number
than phase 1's embedding-based estimate.

The indicator is imprecise and is reported as such: narquil_small and
narquil_large mention five in their OWN statement, so they trip the narquil
marker without quoting the definition.  That inflates the "quotes + same" cell
and does not affect the conclusion.


8. CANDIDATE 5a -- PER-RUN-PAIR NORMALISATION
=============================================

If one run is simply terser than another, every entity's similarity moves
together, so score an entity against the median similarity of all entities
compared between the same two runs.  This IS production-realisable:
re-interpreting a theory yields many entities to calibrate on.

Document text (the better of the two):

  offset cut   no-change called "changed"   real change called "unchanged"   savings
  +0.02                 93.6 %                       10.7 %                  6.4 %
  +0.01                 71.8 %                       23.2 %                 28.2 %
   0.00                 49.4 %                       38.7 %                 50.6 %
  -0.01                 32.0 %                       48.0 %                 68.0 %
  -0.02                 21.6 %                       55.7 %                 78.4 %
  -0.05                  3.6 %                       73.2 %                 96.4 %

Equal-error: 32.0 % false alarms against 48.0 % misses -- WORSE than the plain
global cut on the same text (29.2 / 36.2).  On the interpretation text it is
worse still (49.3 / 47.3).

VERDICT: NEGATIVE.  Run-to-run "terseness" is not a shared offset that can be
subtracted out; the variation is per entity and it swamps the signal.


9. CANDIDATE 5b -- TEXT PREPROCESSING, AND NON-EMBEDDING COMPARATORS
====================================================================

Stripping the parenthetical asides, and first sentences
-------------------------------------------------------

Phase 1's inspection of the lowest-similarity noise pairs suggested one culprit:
the agent sometimes adds a parenthetical gloss ("(two is even)", "(the sum of
two even numbers is even)") and sometimes does not.  Three transformed forms
were embedded and scored exactly like the raw text.

  form                                       AUC      equal-error point
  document text                             0.7452   cut 0.96 -> 29.2 % / 36.2 %
  interpretation text                       0.6631   cut 0.95 -> 42.7 % / 37.7 %
  interpretation, parentheticals stripped   0.6596   cut 0.94 -> 37.5 % / 38.9 %
  first sentence only                       0.5902   cut 0.93 -> 44.1 % / 40.2 %
  first sentence, parentheticals stripped   0.5818   cut 0.92 -> 39.8 % / 45.0 %

ALL THREE ARE NEGATIVE RESULTS.  Stripping parentheticals moves the AUC by
-0.004 (it lowers the noise AND the signal by about the same amount).  Keeping
only the first sentence is clearly harmful: it makes both populations noisier
(the no-change minimum falls from 0.734 to 0.578) and it destroys the signal,
because the sentence that carries the definition body is usually the second or
third.

Comparing the formal content instead
------------------------------------

WHAT THIS EXPERIMENT CANNOT MEASURE, STATED PLAINLY.  Semantic_Digest (the
alpha-canonical formal digest the pipeline already computes) and the statement
hash inside a universal key both incorporate the FULLY QUALIFIED name of every
constant involved.  In this experiment the qualifier is the theory name, which
differs between every run by construction, so both differ for all 1190
byte-identical-source pairs -- 0 of 1190 agree.  That is an artifact of running
each variant as its own theory, not a property of the mechanism.  In production
an edit happens inside one theory, the qualified names do not move, and the
digest changes exactly when the alpha-canonical formal content changes.

The measurable, name-independent stand-in is the printed statement expr, which
carries no theory qualifier:

  comparator                  false alarms        misses            savings
  printed statement differs   0/1190 = 0.0 %   420/1085 = 38.7 %    100 %

Zero false alarms, as it must be -- identical source, identical statement.  The
38.7 % "misses" are the entities whose printed statement is not their content: a
constant, whose expr is only its type signature.  Those are exactly the ones
Semantic_Digest handles, by hashing the definition body.

How much of the invalidation a statement-level comparator already avoids, per
grade -- the fraction of an edited root's own entities whose printed statement
moves at all:

  a-cosmetic    75/130 = 58 %
  b-numeric     75/140 = 54 %
  c-condition  105/220 = 48 %
  d-negation   150/260 = 58 %
  e-overhaul   120/160 = 75 %
  f-locale     140/175 = 80 %

Note that a cosmetic edit still moves 58 % of the statements -- a reordered fun
equation changes the printed elims rule.  This is precisely why the formal
comparator alone over-invalidates and why a meaning-level gate on top of it has
something to do.


10. RANKING
===========

Every rule at its best balanced operating point, on the full 1190 / 1085
populations except the judge, which is on the 663 / 87 strict populations of
section 7:

  rank  rule                                              false alarms  misses  savings
   1    LLM judge (gpt-5.6-sol) on the two paragraphs         0.8 %      1.1 %   99.2 %
   2    global threshold, document text, cut 0.99            89.2 %      0.9 %   10.8 %
   3    global threshold, document text, cut 0.985           77.6 %      4.5 %   22.4 %
   4    global threshold, interpretation text, cut 0.99      95.5 %      1.0 %    4.5 %
   5    oracle per-entity relative rule (not realisable)     27.6 %     35.0 %   72.4 %
   6    resampling rule, k = 2, mean, document text          31.4 %     28.7 %   68.6 %
   7    per-run-pair normalisation, document text            32.0 %     48.0 %   68.0 %
   8    first-sentence embedding                             44.1 %     40.2 %   55.9 %

Rows 2-8 are not on one scale with row 1 -- rows 2-8 use the crude ground truth
that a cosmetic edit counts as a change -- but the gap is far larger than that
correction.  Scored on the identical production-relevant population (section 7),
the judge suppresses 94.6 % of useless propagations at a 1.1 % miss rate where
the best embedding cut suppresses 2.7 % at the same miss rate.


11. RECOMMENDATION, AND WHAT A USER WOULD LIVE WITH
===================================================

The rule
--------

  When the formal comparator (Semantic_Digest) reports that an entity's
  definition changed, re-interpret that entity, then ask an LLM whether the old
  and new English paragraphs assert the same thing, using the section 7 prompt.
  Do not propagate the invalidation downstream if the answer is "same" AND the
  cosine similarity of the two paragraphs is at least 0.70.

The embedding term is a backstop, not a threshold: it exists solely to catch the
one failure mode the judge showed, a new paragraph so vague that there is
nothing to contradict.  Swept against the strict ground truth:

  backstop cut     false alarms       misses        savings
  none (judge)    5/663 = 0.8 %    1/87 = 1.1 %     99.2 %
  0.60            5/663 = 0.8 %    1/87 = 1.1 %     99.2 %
  0.65 - 0.70     5/663 = 0.8 %    0/87 = 0.0 %     99.2 %
  0.75            6/663 = 0.9 %    0/87 = 0.0 %     99.1 %
  0.80            9/663 = 1.4 %    0/87 = 0.0 %     98.6 %
  0.85           21/663 = 3.2 %    0/87 = 0.0 %     96.8 %
  0.90           89/663 = 13.4 %   0/87 = 0.0 %     86.6 %

The cut is chosen at 0.70 because the whole band 0.65-0.75 gives the same
answer, so it is not perched on an edge: the lowest similarity anywhere in the
no-change population is 0.734, and the pair the backstop must catch sits at
0.611.

What that means in plain sentences
----------------------------------

At this operating point, on this data:

  * Of every 100 entities whose definition the formal comparator flagged but
    whose meaning did not really change -- a cosmetic rename, a reordered
    equation, a regenerated fact that does not depend on the edited part -- the
    gate correctly stops the invalidation for about 99 of them, and needlessly
    propagates for about 1.  A needless propagation costs money and nothing
    else; it is what the system does today for all 100.

  * Of the entities whose meaning really did change, none was missed.  The gate
    is not proven to never miss -- the sample is 87 -- but the one case that the
    judge alone got wrong is caught by the backstop, and it was caught because
    it was the single most dissimilar pair in 4165.

  * The gate costs one extra LLM call per changed entity: about 280 input and 46
    output tokens on a small model.  That is roughly a thousandth of the cost of
    the interpretation call it may save, and it saves not one call but the whole
    downstream cone.

  * The separate finding, independent of any rule: 91 of 100 downstream
    re-interpretations in this experiment produced no change of meaning at all,
    and the 9 that did were all lemmas that restate a locale assumption in
    words.  The saving on offer is real and large.

What I would not do
-------------------

Do not ship a bare cosine threshold in any form.  The proposal's 0.01 cosine
distance never fires (it suppresses 4.5 % of propagations on the interpretation
text), and the cuts that do fire buy their savings with silent staleness at
rates between 4 % and 40 %.  On this evidence the embedding distance is not a
usable gate signal; it is usable only as the loose sanity backstop above.


12. WHAT THE SAMPLE SUPPORTS, AND WHAT IT DOES NOT
==================================================

SUPPORTED.

  * The judge's false-alarm rate.  626 no-change pairs across six different run
    pairs, on both unchanged and modified content, gave 3 false alarms.  That
    0.5 % is a well-measured number.
  * The ordering of the rules.  The gap between the judge and every
    distance-based rule is an order of magnitude in savings at equal miss rate;
    no plausible resampling of 4165 pairs closes it.
  * The negative results: per-entity calibration, resampling (k = 2 and k = 3),
    per-run-pair normalisation, parenthetical stripping and first-sentence
    truncation all fail to beat the plain global cut on the document text, and
    most are worse than it.
  * That the production document text is a better score than the paragraph
    alone (AUC 0.745 against 0.663), which is a free improvement to the proposal
    as originally framed.

NOT SUPPORTED.

  * The judge's miss rate to better than about one part in a hundred.  87 strict
    positives gave one miss.  A 95 % confidence interval on that is roughly 0 %
    to 6 %; the honest claim is "around 1 %, and no worse than a few per cent",
    not "1.1 %".
  * Any per-grade rate.  Each grade has four instantiations across B, B2, B3, B4
    and 16-24 judged pairs; the per-grade table is an illustration.
  * Generalisation to real formalisations.  One toy theory of one-line
    statements, one interpretation model (claude-opus-4-8), one embedding model,
    one judge model.  Real AFP statements are longer and more varied; a judge
    facing a five-line locale assumption or a heavily notated analysis lemma may
    behave differently, and the vague-paragraph failure mode the backstop exists
    for is likely to be MORE common there, not less.
  * Independence between entities.  All entities of one theory were interpreted
    in one agent session sharing one conversation and one file, so their errors
    are correlated; the effective sample is smaller than the pair counts
    suggest.
  * The behaviour of Semantic_Digest as a comparator, which this cross-theory
    design cannot measure at all (section 9).  Any decision that depends on the
    digest's exact firing behaviour needs a same-theory experiment: edit one
    file in place, re-run, and compare.
  * Anything about entity kinds with few members here -- types, classes,
    locales, theorem collections and proof methods are represented by one or two
    entities each.


13. WHERE THE DATA IS
=====================

  pairs_phase2.json       2.9 MB.  All 85 entities with their text in each of
                          the 12 runs, and all 4165 pairs with, for every text
                          form, the cosine similarity, the universal keys, and
                          the class and grade labels.
  judge_phase2.json       289 KB.  All 850 judgements with the verdict, the
                          model's one-sentence reason, and the exact prompt
                          template.
  stats2_output.txt       The complete printed output of stats2.py -- every
                          trade-off table in full.
  judge_stats_output.txt  The complete printed output of judge_stats.py,
                          including the misses and false alarms with their
                          texts.
  pairs.json, summary.csv Phase 1's data, unchanged.
  isolated database       /var/tmp/qiyuan/sim_measure_db, 1.8 GB, local ext4
                          disk.  All twelve runs' interpretations plus the
                          embedding cache; a follow-up can re-analyse without
                          paying again.
  logs                    /var/tmp/qiyuan/sim_measure_logs/ -- per-run collect
                          logs, chain.log, analyze2.log, judge.log, judge2.log,
                          digests/*.tsv.
  theories and scripts    this directory.
  real database           ~/.cache/Isabelle_Semantic_Embedding -- never opened
                          by any process of this experiment.
