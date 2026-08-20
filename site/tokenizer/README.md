# The JavaScript tokenizer, and how the two implementations are held together

§5 of `SEMANTIC_SEARCH_SITE_PLAN.md` defines one tokenizer and the site runs it twice:
the Python implementation (`Isabelle_Semantic_Embedding/isabelle_tokenizer.py`) builds
the index, and the JavaScript one here compiles every query. **If the two disagree the
site returns silently wrong results** — no error, no log line; a query simply stops
matching documents it should match.

```
isabelle_tokenizer.js   the port. Reads the asset, asks JavaScript nothing
asset.json              the character classes and the two symbol tables (D45)
inputs.jsonl            15,253 inputs. No expected outputs — see below
expected.json           one digest, 334 bytes. This is the gate
toy_asset.json          an asset that contradicts every built-in, and 23 expectations
emit.py / emit.mjs      tokenize the inputs, hash the result, compare
test_tokenizer.mjs      what the inputs cannot express: the refusals
build_inputs.py         regenerate inputs.jsonl and asset.json (needs the store)
```

## Why no expected outputs are committed

An expectations file is a **recording of what the code currently does**. Change a rule,
regenerate, and the file agrees with the new behaviour — including when the new
behaviour is a bug. No digest, marker or ledger over such a file can tell a legitimate
change from a re-recording, because the two are identical at the byte level.

So the expectations are computed, in CI, by each implementation, and both compare their
result with one number. That number is not a recording of anything: it is a claim, and
the only way to make a broken tokenizer agree with it is to fix the tokenizer.

- A **divergence between the two implementations** moves exactly one digest.
- A **rule change** moves both — and that is the signal, not a nuisance. It is what
  catches a rule change that forgot to bump `tokenizer_rule`, which matters because
  without the bump the asset's bytes do not move, so the turbopuffer namespace name
  does not move, and §8.2's "write into a new namespace" becomes an upsert into the
  live one (§16.4).

## Why the port asks JavaScript nothing, and how that is proved

The obvious substitutes for Python's character predicates disagree with them on
characters the corpus contains: `\p{Nd}` rejects `²`, which occurs 3,950 times; `\s`
takes U+FEFF where `isspace()` does not, and `isspace()` takes U+001C–U+001F and U+0085
where `\s` does not. So every class comes from `asset.json`.

**But no real input can prove that.** `isalpha()` and `\p{L}` agree on every character
assigned in the asset's Unicode version, so a port that asks the language passes every
real input and is wrong only on characters no sample has — and it grows wrong as
browsers update, with no code change. Measured: `/\p{L}/u.test(ch)` passed 12,171 real
and hand-written vectors with zero problems.

`toy_asset.json` settles it by construction. Every class in it **contradicts** what a
built-in would say — `7` is a letter, `z` is a digit, `.` is whitespace and the real
space is not, `,` is symbolic and `+` is not — so an implementation that consults a
built-in, in either direction, diverges on the first case. Its 23 expectations are
derived from §5 by hand, not copied from a run, and they are measured to catch all
twelve single-field substitutions of the forbidden kinds, in both languages.

## Code points, not code units

4.15 % of the corpus's expressions carry a character above U+FFFF. A port that indexes
a string by UTF-16 code unit emits unpaired surrogates, which JSON transports intact
and no query can ever match. Every loop here iterates code points, and the fold scan of
§5.1 step 3b works over an array of them rather than over the string.

## Running the gate

```
python3 emit.py --check            # the Python implementation against the digest
python3 -m pytest ../../test_isabelle_tokenizer.py
node emit.mjs --check              # the port against the same digest
node test_tokenizer.mjs            # the refusals
```

None of these needs Isabelle, the semantic database, or the rest of the package
installed — which is the same property §5.5 requires of the tokenizer itself, and a
gate that needed the Isabelle stack would contradict what it gates.
`.github/workflows/tokenizer-gate.yml` runs all four.

When a digest moves and you want to know **which** input moved:

```
python3 emit.py > /tmp/py.out ; node emit.mjs > /tmp/js.out ; diff /tmp/py.out /tmp/js.out
```

An empty diff means both implementations moved together, so a rule changed and
`expected.json` is stale; a non-empty one names every input they disagree on.

## Changing a rule

Bump `TOKENIZER_RULE` in `Isabelle_Semantic_Embedding/tokenizer_asset.py`, change both
implementations, add the hand-written cases the new rule needs to
`test_isabelle_tokenizer.py` and to `build_inputs.py`'s `SYNTHETIC` — **hand-written,
because a case generated from the implementation cannot validate the implementation** —
then `python3 build_inputs.py` and `python3 emit.py --update`. The diff will show a new
asset, new inputs and one new digest, which is what a rule change should look like.
