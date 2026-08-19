# The JavaScript tokenizer, and the file both implementations are gated on

§5 of `SEMANTIC_SEARCH_SITE_PLAN.md` defines one tokenizer and the site runs it
twice: the Python implementation
(`Isabelle_Semantic_Embedding/isabelle_tokenizer.py`) builds the index, and the
JavaScript one here compiles every query. **If the two disagree the site returns
silently wrong results** — no error, no exception, no log line; a query simply stops
matching documents it should match. Everything in this directory exists to make that
disagreement impossible to introduce unnoticed.

```
isabelle_tokenizer.js     the port. Reads the asset, asks JavaScript nothing
asset.json                the character classes and the two symbol tables (D45)
test_vectors.jsonl        12,171 input/tokens/subtokens triples (§16.5)
test_vectors.meta.json    what the vectors are: counts, digests, the sampling rule
test_vectors.history      one append-only line per generation (§16.6's guard)
check_test_vectors.mjs    the gate, JavaScript half
check_test_vectors.py     the gate, Python half — the same assertions, deliberately
test_tokenizer.mjs        what the vectors cannot express: the refusals
build_test_vectors.py     regenerates the vectors, the meta and the asset
```

## Why the port asks JavaScript nothing

The obvious substitutes for Python's character predicates disagree with them on
characters the corpus actually contains, so a port that reached for them would be
wrong on real data rather than in principle:

- `\p{L}` is 145,672 code points under Unicode 15; `isalpha()` is 136,104.
- `\p{Nd}` rejects `²`, which `isdigit()` accepts — and `²` occurs 3,950 times.
- `\s` takes U+FEFF, which `isspace()` does not; `isspace()` takes U+001C–U+001F and
  U+0085, which `\s` does not. All of them appear in the corpus.

So every class comes from `asset.json`, and the asset also carries a
`tokenizer_rule` version that both implementations refuse if they do not implement
it. The vectors carry a case for each of the four characters above.

## Code points, not code units

4.15 % of the corpus's expressions carry a character above U+FFFF. A port that
indexes a string by UTF-16 code unit emits unpaired surrogates, which JSON transports
intact and no query can ever match. Every loop here iterates code points, and the
fold scan of §5.1 step 3b works over an array of them rather than over the string.
The `astral_symbol` vectors are what catches a port that forgets.

## Running the gate

```
node check_test_vectors.mjs        # the port against the vectors
node test_tokenizer.mjs            # the refusals
python3 check_test_vectors.py      # the Python implementation against the same file
python3 -m pytest ../../test_isabelle_tokenizer.py
```

None of these needs Isabelle, a symbol table, or the rest of the package installed —
which is the same property §5.5 requires of the tokenizer itself.
`.github/workflows/tokenizer-gate.yml` runs all four.

## Changing a rule

Bump `TOKENIZER_RULE` in `Isabelle_Semantic_Embedding/tokenizer_asset.py`, change
both implementations, add the vectors the new rule needs (§16.5), and regenerate with
`build_test_vectors.py`. If the count somehow does not move, the newest line of
`test_vectors.history` must carry a `rule-change:` marker saying what changed —
otherwise the gate refuses the file, because a digest that moves while the count
stands still is exactly the shape of a vector file quietly regenerated to match a
broken implementation.
