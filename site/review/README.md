# The adversarial review of §5, 2026-08-14

The evidence behind every change this review caused in `SEMANTIC_SEARCH_SITE_PLAN.md`.
The plan states conclusions; these files say who measured what, how, and what was
rejected. Read them when a sentence of §5 or D41 looks arbitrary, or before reopening a
question the review already settled.

`SEMANTIC_SEARCH_SITE_PLAN.md` §16.7 mandated this review: §5 specifies a tokenizer that
will be implemented twice, once in Python for the export and once in JavaScript for the
Worker, and the two must agree byte for byte or the search returns wrong results with no
error anywhere. The review had to run **before** `isabelle_tokenizer.py` was written,
because a specification is cheaper to fix while nothing implements it.

## The files

- `brief.md` — what the four reviewers were asked, and the one question that shaped the
  round: *find constructions where two implementations both pass the test vectors and
  still behave differently on real input*. A test-vector gate catches an implementation
  that is wrong on cases somebody thought to write down; it cannot catch a specification
  that is **ambiguous**. That is what this review hunted.
- `bar.md` — the four criteria a finding had to clear, **written and frozen before any
  finding existed**, so the standard could not be bent to fit what arrived. It also
  carries the deletion quota, and the reason for it: the 2026-08-13 review deleted 0 of
  35 findings and so produced a list rather than a decision.
- `findings-pipeline.md`, `findings-unicode.md`, `findings-subtoken.md`,
  `findings-prose.md` — the four reviewers' output. They worked blind to each other, one
  lens each: the five pipeline steps and token formation; Unicode and the Python/
  JavaScript gap; the subtoken rule and its fallback clause; and whether the prose
  actually describes the reference implementation.
- `rebuttal.md` — the verdict. 29 findings in, 19 after merging, 9 deleted, 10 surviving
  plus 1 the rebuttal round found itself. It also re-measured three numbers the reviewers
  disagreed on, and says which reviewer was wrong and why.

`findings-prose.md` carries something worth knowing about separately: a line-by-line
reproduction of every case in §16.2 and every equivalence in §5.3 against the reference
implementation, run rather than trusted. Both tables came out clean.

## What to distrust

Each finding names the corpus figure it rests on. Several of those figures moved on
2026-08-17, when `Isabelle_RPC_Host.unicode` began reading the symbol table Isabelle
actually presents — component files included — instead of rebuilding it from
`ISABELLE_HOME`. The largest movement: the stored expression records whose literal
`\<...>` the subtoken splitter cuts at an underscore fell from 502 to 17. Where the plan
and a file here disagree on a number, the plan is the later measurement.

Re-measure with `../prototype/corpus_probe.py` rather than writing a new probe. A
second probe is a second implementation of the matching rule and will disagree eventually.
