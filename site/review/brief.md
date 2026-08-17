# Review brief — the isasearch tokenizer specification, before it is frozen

## What is being reviewed

A normative specification for a text tokenizer that will be implemented **twice**:
once in Python (runs at export time, produces the stored index) and once in
JavaScript (runs in a Cloudflare Worker, processes the user's live query). The two
implementations must produce **byte-identical** output. If they diverge, the
search silently returns wrong results — no error is raised anywhere, by anyone.

The specification is `contrib/Semantic_Embedding/SEMANTIC_SEARCH_SITE_PLAN.md` §5
(lines 729–906). Read it in full. Also read:

- **D41**, lines 184–203 of the same file — character classes ship as data.
- **D21**, the decision that only *subtokens* are indexed or queried. Find it with
  `grep -n 'D21' SEMANTIC_SEARCH_SITE_PLAN.md`; the decision text is in §2.
- **§3.4** (lines 569–595) and **§3.6** (lines 623–712) — the measurements §5 rests on.
- **§16.2** (lines 2106–2164) — the input→subtoken table an implementation must reproduce.
- **§16.4 / §16.5** (lines 2197–2239) — the assets and the test-vector file.
- The prototype, which is the de-facto reference implementation:
  `contrib/Semantic_Embedding/site/prototype/tokenize_prototype.py` (`tokenize`)
  and `subtoken_rule.py` (`subtokens`).

## The question

> **Find constructions where two implementations both pass the test vectors and
> still behave differently on real input.**

The test-vector gate (§16.5/§16.6) catches an implementation that is wrong on the
cases someone thought to write down. It cannot catch a specification that is
*ambiguous* — where two competent implementers read the same prose, write
different code, and both pass. That is the failure mode you are hunting.

A finding is worth reporting when you can name:

1. the sentence or code in §5 (or D41, or the prototype) that admits two readings,
   or that the prototype and the prose disagree about;
2. two concrete implementations, both defensible from the text;
3. an input on which they differ — ideally one that occurs in the real corpus, or
   that a user could plausibly type;
4. why the vectors of §16.5 as currently specified would not catch it.

Point 4 matters. "The port might forget X" is not a finding if §16.2's table or
§16.5's synthetic list already pins X. Check before you write it up.

## Specific things the plan asks you to examine

These are named in §16.7. They are starting points, not the boundary of the review.

- **The fallback clause** in `subtokens()` — the branch that keeps a token whole
  when it splits to nothing *and* consists entirely of rendered sub/superscript
  characters. §5.4 says it is load-bearing and must stay narrow.
- **The boundary of "letter."** §5.2 defines it as "a single character for which
  `isalpha()` holds, **or** one of the `letter`/`greek` group symbols of
  `etc/symbols`." Those are two different kinds of thing. Where do they overlap,
  where do they conflict, and what does D41's asset emission have to do to make
  the union reproducible without `isalpha()`?
- **`symbol_explode`.** Can it emit a symbol that the separator class then splits
  in half — or that the token grouping of §5.2 treats inconsistently?
- **NFC stability of every symbol value.** §3.4 checked this once. Check the check:
  is the property that was measured the property §5.1 needs?

## Things you should also consider, unprompted

The list above is what the plan's author already suspects. The review is more
valuable where it does not. Consider at least: how JavaScript represents strings
and what that does to characters outside the Basic Multilingual Plane; regex
semantics differences; the *order* of the pipeline steps and whether any pair
commutes; what happens at the ends of a string; and empty or degenerate input.

## How to verify a claim

Do not report a behavioural claim you have not run. The prototype runs like this
from `contrib/Semantic_Embedding/site/prototype/`:

```python
import sys, os
sys.path.insert(0, '.')
sys.path.insert(0, os.path.abspath('../..'))
sys.path.insert(0, os.path.abspath('../../../Isabelle_RPC'))
os.environ.setdefault('ISABELLE_HOME', os.path.abspath('../../../Isabelle2025-2'))
from tokenize_prototype import tokenize
from subtoken_rule import subtokens
print(tokenize('sorted_wrt R ?xs'), subtokens(tokenize('sorted_wrt R ?xs')))
```

To count how often something occurs in the real corpus, use the existing harness
rather than writing your own — a second probe is a second implementation of the
matching rule:

```
python3 corpus_probe.py '?a + ?b = ?b + ?a'          # ~60 s, 1.36 M records
python3 corpus_probe.py --field name 'Path_Connected'
```

For direct corpus statistics that `corpus_probe.py` does not compute (character
frequencies, say), read the LMDB the way `corpus_probe.py` does — copy its
`_Semantic_DB._decode` loop. The DB is at
`~/.cache/Isabelle_Semantic_Embedding/semantics.lmdb`, read-only, and a full pass
costs about 25–60 seconds.

If you want to test a JavaScript hypothesis, `node` is available. Write the
snippet, run it, report what it printed.

## Hard constraints

- **Never run `isabelle build`**, in any session, with any flags, however small.
  It deletes heaps before rebuilding and has destroyed every user heap on this
  machine once already.
- **Never** run `git clean`, `git stash`, `git checkout`, or `git reset --hard`.
  This is a shared working tree with other agents in it.
- Do not modify any file under `ICSE27/` or `ICSE27-x/`.
- Write scratch files only under
  `/tmp/claude-1002/-home-qiyuan-Current-MLML/191c16f2-3fa2-4e2b-b337-d141aea09fc8/scratchpad/`.
- Do not edit the plan, the prototype, or any other repository file. You are
  reviewing, not fixing.

## What to return

A numbered list of findings. For each:

```
Fn. <one-line claim>
    WHERE:      the sentence / line / function at issue
    READING A:  what one implementer would write
    READING B:  what another would write
    DIVERGES:   the input, and both outputs (say which you ran, and how)
    VECTORS:    why §16.5 as specified does not catch it
    SEVERITY:   silently-wrong-results / degraded-results / cosmetic
```

Order by severity. If you find nothing in some area you were asked about, say so
explicitly and say what you checked — a cleared area is a real result.

Do not pad. A short list of things that are actually true is worth more than a
long one, and the next round will be deleting findings, not collecting them.
