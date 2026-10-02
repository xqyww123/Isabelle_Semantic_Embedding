# Embed phase: find the records lacking a vector without decoding every record

Status: **IMPLEMENTED in the working tree on 2026-10-02, NOT committed** (the user
ordered "implement, do not commit"). The two open decisions were taken by the user on
2026-10-02 (§7). A two-round adversarial code review followed (§10.1); its fixes and
the four decisions it put to the user (all taken on 2026-10-02) are in the tree, as are
the fixes of the re-review (§10.2) and of the single-reviewer conformance check that
closed it (`ai-artifacts/review_embed_scan_code/conformance.json`: one false clause in
§8, corrected). §11 records what was done and what the implemented code measured.
Revision 2 incorporates the findings of four independent reviewers (§10): revision 1
contained one false claim about callers, one false claim about cost, an over-absolute
safety claim, and a design that ignored an existing convention of the module.

**In one sentence.** Today the embed phase of `run_semantic_interpretation` turns every
record of the semantic DB into a Python `Record` object before it asks which of them lack
a vector; this plan makes it ask that question on the keys alone, and build `Record`
objects only for the records that turn out to lack a vector.

Citations name functions, not line numbers: this is a shared working tree and line
numbers move (the convention of `archive/plans/VECTOR_INVALIDATION_PLAN.md` §1).

## 1. The problem, measured

### 1.1 What the user sees

`run_semantic_interpretation` prints

    [Semantic_Embedding] Completing missing vector embeddings...

and then nothing for a long time. The next line is either
`<model>: already complete (N entities).` or
`<model>: n of N entities need vectors (c chars).`

From the log of the user's own RPC host
(`~/.isabelle/Isabelle2025-2/log/RPC_attached_634417-*.log`):

| Run | What happened | Silence before the first result line |
| --- | --- | --- |
| 2026-10-01 23:23 | 2,464 of 1,451,029 records lacked a vector | 39 s (23:23:41 → 23:24:20; this interval also contains whatever ML does after the last theory finishes, which the log cannot separate; why it is twice the morning figure is not established) |
| 2026-10-02 09:29 | nothing lacked a vector | at most 18.6 s |
| 2026-10-02 09:30 | nothing lacked a vector | at most 16.0 s |
| 2026-10-02 09:42 | nothing lacked a vector | at most 19.6 s |

("At most": the three morning intervals are measured from `Loading RPC component`, which
precedes the dry run of the interpretation phase as well.)

The wait does not depend on how much there is to embed. On the three morning runs
nothing was embedded at all.

### 1.2 Where the time goes

"The embed phase" is the term `Tools/interpret_command.ML` uses for the second phase of
the command (`embed_phase`). It makes one RPC call, `Semantic_Embedding.embed_all_missing`,
whose Python handler `_embed_all_missing` (`semantics.py`) does this before it prints
anything:

1. `_collect_embed_candidates()` walks all of `semantics.lmdb` through
   `Semantic_DB.iter_entity_records()`, which decodes **every** value into a `Record`
   (`_Semantic_DB._decode`), and keeps every `(key, Record)` whose `interpretation` is
   not `None` in one list. These are "the candidates".
2. `complete_vector_store` asks the vector store which candidate keys already have a
   vector (`store.contains`), and keeps the rest as `todo`.

Measured on the user's database on 2026-10-02, in separate read-only processes, with a
warm page cache (1,462,602 key/value pairs, 1,125 MB of values, 1,451,029 candidates).
"Author" is my measurement; "reviewer" is the independent re-measurement of §10, taken
while the machine was busier.

| Work | Author | Reviewer | Is it LMDB reading? |
| --- | --- | --- | --- |
| Walk every key/value of `semantics.lmdb` (bytes only, nothing decoded) | 1.1 s | 1.1–1.3 s | yes |
| Decode every value into a `Record`, keeping none | 6.3 s on top of the walk | 8–10 s on top of the walk | no |
| Python's cyclic garbage collector while 1.45 million `Record` objects accumulate in one list | 7.9 s (by subtraction) | 8.3–9.2 s (timed directly with `gc.callbacks`: 20,698 collections) | no |
| `store.contains` over 1.45 million keys | 1.9 s | 1.9–3.4 s | yes |
| **Total** | **≈ 18 s** | **21–24 s** | |

Decoding everything while keeping nothing triggers no garbage collection at all
(reviewer); the collector's cost comes entirely from the list of live objects.

So about 15 of the 18 seconds are spent building, and then garbage-scanning, 1.45
million `Record` objects — and in the run of 2026-10-01 only 2,464 of those objects were
ever used. On the three morning runs none was.

Two more costs of the same cause:

- **Memory.** The list of candidates stays alive for the whole embed phase, including
  all the embedding API calls. Measured as anonymous memory (`/proc/self/smaps_rollup`):
  3.78 GB today (reviewer), 3.96 GB (author). After the list is freed about 0.6 GB is
  not returned to the operating system (reviewer), so a long-running RPC host keeps it.
- **The text that is embedded is read early.** It is the text read during the scan,
  possibly minutes before the vector is written (§6.3).

## 2. What must not change

1. **The command still completes the whole vector store.** Decision L1 of
   `archive/plans/AUTO_EMBED_AFTER_INTERPRETATION_PLAN.md`: scan all of `semantics.lmdb`
   and embed every interpreted record that has no vector — not only the records of the
   theories interpreted by this run. This plan keeps the whole-DB scan; it only makes
   the scan cheaper.
2. **No user-visible text changes and none is added** (approved texts S2, S3, S4 of that
   plan): the opening line, `already complete (N entities).`,
   `n of N entities need vectors (c chars).`, the per-batch `embedded i/n` lines, the
   `done` line, the warning about records with no embeddable document text, and
   `nothing embeddable.` On every run in which no record is written or deleted during
   the embed phase and every record decodes, the output is byte-identical to today's.
   When a record is deleted or rewritten during the embed phase, or does not decode, the
   same texts can appear in different situations than today; §6.4 and §7 say which.
3. **N keeps its meaning**: the number of records that have an interpretation.
4. **The CLI (`isabelle-semantics embed`, `collect --embed-models`) keeps identical
   behaviour**, including `--force` and `--kinds`. It shares `_collect_embed_candidates`
   and `complete_vector_store` with the command.
5. **The vector-layer self-sufficiency invariant** (`VECTOR_INVALIDATION_PLAN.md` §2) is
   untouched: whether a key has a vector is still answered by `Vector_Store._raw_getter`
   alone (real vector → present; tombstone → absent; no user entry → the system vector
   store decides).
6. **The layered reading of records is untouched**: user layer first, a record tombstone
   hides the system record, otherwise the system layer (`iter_items`; `_raw_getter`,
   which replaced `_get_raw_many` with the same rule, §3.5).
7. **Document text has one authority**: `document_text_of`. This plan does not assemble
   text anywhere.

## 3. The change

### 3.1 Today's order and the proposed order

Running example: the run of 2026-10-01, 1,451,029 interpreted records, 2,464 lacking a
vector.

Today:

1. The scan: decode all 1,451,029 records into `Record` objects; keep all of them.
2. The presence check: ask the vector store about all 1,451,029 keys. 2,464 are absent.
3. Compute the document text of those 2,464 records, print the `need vectors` line,
   embed them in batches of 256.

Proposed:

1. The scan: walk all records, but for each one only find out whether it has an
   interpretation. Keep the 1,451,029 **keys**; build no `Record`.
2. The presence check: as today. 2,464 are absent.
3. The fetch: read and decode those 2,464 records.
4. As today's step 3.

### 3.2 Codec: one function that answers "is this a record with an interpretation?"

`semantics.py` already names the positions of the positional record codec
(`F_KIND, F_NAME, F_POSITION, F_FROM_COLLECTION`), has `unpack_fields` as the one
spelling of "unpack the stored tuple and pad it to `RECORD_FIELD_COUNT`", and its
comment forbids a reader from writing those numbers a second time ("a second copy of
those numbers is how index drift happens"). The new function follows that convention,
and so, from now on, does `_decode`: its first two statements become
`vals = unpack_fields(raw)`, so the shared first stage is one function and not a copy
(review C4, §10.1).

Add `F_INTERPRETATION = 3` to the existing `F_*` constants, and next to
`_Semantic_DB._decode`:

```python
_KIND_VALUES = frozenset(int(k) for k in EntityKind)

@staticmethod
def _interpreted_kind(raw: bytes) -> 'int | None':
    """F_KIND of a stored value on which `unpack_fields` (`_decode`'s first
    stage) succeeds, with a non-None F_INTERPRETATION and a kind `EntityKind`
    accepts; None otherwise.  No Record is built.

    Never None where `_decode` succeeds with an interpretation.  Not
    conversely: `_decode` may still reject such a value
    (archive/plans/EMBED_COMPLETION_SCAN_PLAN.md §6.1, D1)."""
    try:
        vals = unpack_fields(raw)
        kind = vals[F_KIND]
        return (kind if vals[F_INTERPRETATION] is not None
                and kind in _Semantic_DB._KIND_VALUES else None)
    except (ValueError, TypeError):
        # Unpacking, and the membership test on an unhashable kind, raise
        # only these on a value that is not a record; anything else is a
        # programming error and surfaces.
        return None
```

Three details, each checked by running (§6.1):

- `unpack_fields` pads a short record with `None`, so a record with fewer than four
  fields reads as "no interpretation", exactly as in `_decode`. Revision 1 tested
  `isinstance(vals, list)` instead, which made the two rules disagree on values that
  are not msgpack arrays.
- `kind in _KIND_VALUES` accepts exactly what `EntityKind(kind)` accepts, including
  `2.0` and `True`. Revision 1 added `isinstance(kind, int)`, which rejected a float
  kind that today's code embeds.
- The `except` is narrow: on a value that is not a record, unpacking and the membership
  test (on a kind that cannot be hashed, such as a list or a map) raise only
  `ValueError` and `TypeError` subclasses (reviewers' fuzzing over 200k, 300k and 800k
  values, plus hand-made extremes); the two index reads cannot raise, because
  `unpack_fields` pads to `RECORD_FIELD_COUNT` fields. A blanket `except Exception` would turn a
  programming error in the function's own body into the silent line
  `already complete (0 entities).` (review C5); a test pins the narrow form.

What keeps `F_INTERPRETATION` true: extend the existing test
`test_record_field_count_is_the_codec_arity` (`archive/tests/
test_semantic_change_gate_storage.py`), which already asserts
`Record._fields[14] == "baseline_interpretation"`, to assert
`Record._fields[F_X] == "x"` for every `F_*` constant. Then no reader that indexes by
an `F_*` name can drift from `_decode` without a test failing; a bare number is outside
this check.

### 3.3 `Semantic_DB.iter_interpreted_keys`, beside `iter_entity_records`

```python
def _iter_entity_items(self) -> 'Iterator[tuple[bytes, bytes]]':
    """`iter_items()` restricted to entity keys (longer than 16 bytes): no
    theory-status key, no COUNTER_KEY."""
    for k, v in self.iter_items():
        if len(k) > 16:
            yield k, v

def iter_interpreted_keys(self, kinds: 'set | None' = None) -> 'Iterator[universal_key]':
    """Yield the key of every record that has an interpretation, as visible in
    the LAYERED store (user shadows system; tombstones yield nothing), in ONE
    read txn per layer.  `kinds` restricts to those EntityKinds."""
    wanted = None if kinds is None else {int(k) for k in kinds}
    for k, v in self._iter_entity_items():
        kind = self._interpreted_kind(v)
        if kind is not None and (wanted is None or kind in wanted):
            yield k
```

`len(k) > 16` is the rule the module's other store walkers already use for entity keys;
it keeps the 1-byte counter key out of `_interpreted_kind` instead of relying on that
function to reject its value (review C5). `iter_entity_records` is rewritten on
`_iter_entity_items` (so that rule is written once) and otherwise **stays as it is**.
It has callers outside this change:

- `contrib/isasearch-web/site/prototype/baseline/build_baseline.py` and
  `verify_baseline.py` (tracked files of another repository; they walk all records and
  read `Record` fields);
- `archive/tests/test_layered_db.py`;
- `ai-artifacts/similarity_measurement/analyze.py` and `analyze2.py`.

Scan command: `/usr/bin/grep -rnI "iter_entity_records" contrib evaluation
--include='*.py' --exclude-dir=.git --exclude-dir=node_modules
--exclude-dir=Isabelle2024 --exclude-dir=Isabelle2025-2 --exclude-dir='afp-*'
--exclude-dir=build`, run from the superproject root. (Revision 1 claimed "exactly one
caller" from a scan that excluded `archive/` and `ai-artifacts/` and did not cover
`contrib/isasearch-web`. That was wrong, and so was its proposal to delete the
function.)

### 3.4 `_collect_embed_candidates` returns keys

```python
def _collect_embed_candidates(kinds: 'set | None' = None) -> 'list[bytes]':
    return list(Semantic_DB.iter_interpreted_keys(kinds))
```

The keys come out in sorted key order, the order of `iter_items` (as today).

### 3.5 `Semantic_DB.get_many`: no intermediate list of raw values; an `undecodable` keyword

Today `get_many` calls `_get_raw_many`, which copies every requested value into one list
before any of them is decoded. When all 1.45 million records are fetched that list is
1.3 GB (reviewer). Two changes:

```python
def _raw_getter(self, stack: ExitStack) -> 'Callable[[universal_key], bytes | None]':
    """Batch counterpart of ``_get_raw``: the same layered point read as a
    per-key closure over ONE read transaction per layer, both entered on
    ``stack`` so the caller's ``with`` bounds them (the shape of
    ``Vector_Store._raw_getter``)."""
    # body: today's _get_raw_many without the list -- user layer first, a
    # tombstone reads as absent, otherwise the system layer; bytes(raw) or None

def contains(self, keys):
    with ExitStack() as stack:
        get = self._raw_getter(stack)
        return [get(k) is not None for k in keys]

_RAISE = object()

def get_many(self, keys, *, undecodable=_RAISE):
    """... (existing docstring) ...
    `undecodable`: when given, a value `_decode` rejects yields this object
    instead of raising."""
    out = []
    with ExitStack() as stack:
        get = self._raw_getter(stack)
        for k in keys:
            raw = get(k)
            if raw is None:
                out.append(None)
                continue
            try:
                out.append(self._decode(raw))
            except Exception:
                if undecodable is self._RAISE:
                    raise
                out.append(undecodable)
    return out
```

`_get_raw_many` is deleted; `_get_raw` (the single-key read) is untouched. The read
transactions are closed by the `with` block, on every exit path, by construction:
nothing is left for a caller to remember, and a getter used after its block raises
`lmdb.Error` instead of silently holding a snapshot. This is the idiom
`Vector_Store._raw_getter` already uses for the vector layer, so both layers now do
their layered batch read the same way, and `Semantic_DB.contains` has the same three
lines as `Vector_Store.contains`.

(Revision 2 prescribed a generator, `_iter_raw_many`, that held the transactions while
suspended and depended on a docstring rule plus a hand-written `close()` in `get_many`;
the review found that the one test meant to guard the `close()` passed without it
(C1, C2). The owner approved the getter shape on 2026-10-02, proposal P1 of §10.1.)

Every existing caller (`_auto_embed`, `embed_keys`, `interpret_file` in
`semantic_interpretation.py`) passes no keyword and sees today's behaviour, minus the
intermediate list. Scan command, from the package root:
`/usr/bin/grep -rn 'get_many(' Isabelle_Semantic_Embedding/*.py`.

Why a keyword and not a flag that returns `None`: the caller of §3.6 must tell a record
that was **deleted** since the scan (`None`) from a record that **does not decode**.

### 3.6 `complete_vector_store` takes keys and fetches only the records it will embed

Signature: `candidates: 'list[bytes]'` instead of `'list[tuple[bytes, object]]'`.

Only the head of the body changes:

```python
if force:
    todo_keys = candidates
else:
    present = store.contains(candidates)
    todo_keys = [k for k, p in zip(candidates, present) if not p]

if len(todo_keys) == 0:
    await report(f"{label}: already complete ({len(candidates)} entities).")
    return (0, 0, 0)

_UNDECODABLE = object()
chars, unrenderable, renderable = 0, [], []
for k, rec in zip(todo_keys, Semantic_DB.get_many(todo_keys, undecodable=_UNDECODABLE)):
    if rec is None:
        continue                       # deleted since the scan: no longer a record
    t = None if rec is _UNDECODABLE else document_text_of(rec)   # D1: listed in the warning
    if t is None:
        unrenderable.append(k)
    else:
        chars += len(t)
        renderable.append((k, rec))
todo, n = renderable, len(renderable)
```

Everything from the unrenderable warning onwards is unchanged: the warning, the
`nothing embeddable.` line, the `need vectors` line, `confirm`, the batches of 256
through `store.embed_records(todo[i:i + BATCH], force=True)`, the `done` line.

A record deleted since the scan is skipped without a message. That is what the two
existing keys-to-records paths do (`embed_keys`: `if rec is not None`; `_auto_embed`:
`if rec is not None and ...`).

There is no `await` between the presence check and the fetch, so no other task of the
same event loop can run between them.

### 3.7 The two callers, and the docstrings that become false

- `_embed_all_missing` (`semantics.py`): no textual change; `candidates` is now a list
  of keys.
- `_embed_models` (`isabelle_semantics.py`): no textual change. It computes `candidates`
  once and reuses the list for every model; each model then fetches only its own todo
  records.

Docstrings to correct: `_collect_embed_candidates` (first line "Every interpreted record
as (key, record)", "Records are handed to ...", the pointer to `iter_entity_records`);
`complete_vector_store` (the `candidates` annotation). The paragraph of
`_collect_embed_candidates` on WIP records being included stays (the earlier plan calls
it load-bearing history).

### 3.8 `Vector_Store.contains` without copying the vector values

```python
def contains(self, keys: list[key]) -> list[bool]:
    with contextlib.ExitStack() as stack:
        get = self._raw_getter(stack, buffers=True)
        return [get(k) is not None for k in keys]
```

`_raw_getter` already supports `buffers=True` and its docstring states that the
tombstone test `v if v else None` reads both `bytes` and `memoryview`. With
`buffers=False` every `get` copies the 8 KB vector only to compare it with `None`. The
buffers never leave the `with` block; only booleans do, and every caller of `contains`
(`embed_records`, `embed_keys`, the `Semantic_Embedding.contains` RPC, and tests)
receives only booleans.

Measured: 1.87 s → 1.11 s (author); 2.04 s → 0.79 s and 1.2 s in a fresh process
(reviewers). Inside a long-running RPC host, where the pages are already mapped, the
saving is about 0.75 s (reviewer).

This is independent of §3.2–§3.7 and is included by decision D3. It does **not** reduce
how much of the vector store file is touched: the py-lmdb build active here (the CPython C extension,
py-lmdb 2.2.1) touches the pages of every value it returns, with or without
`buffers=True` — 1.34 against 1.38 page faults per key (reviewer) — and a whole
presence check maps 16.73 GB of the 16.76 GB file either way. Even a key-only cursor
walk of the vector store maps that much.

## 4. Measured effect of the proposed order

Read-only against the user's database, 2026-10-02, warm page cache.

The usual case — few or no records lack a vector:

| Step | Author | Reviewer |
| --- | --- | --- |
| The scan with `_interpreted_kind` as in §3.2 | 3.2–3.3 s | 3.9–4.9 s (revision 1's rule plus kind test) |
| The presence check with `buffers=True` | 1.1 s | 1.2 s |
| The fetch of 2,464 records | 0.04 s | 0.08–0.09 s |
| **Total** | **≈ 5 s** (today ≈ 18 s) | **5.2–5.6 s** (today 21–24 s) |

Without §3.8 the presence check is 1.9 s and the total about 6 s.
Anonymous memory held through the embedding API calls: 0.19 GB (reviewer), against
3.78 GB today.

(The author's prototype run had 5 records lacking a vector; the 2,464-record fetch was
timed separately, on the first 2,464 candidate keys.)

The case where **every** candidate must be fetched — `force=True`, or a model whose
vector store is empty:

| | Today | Proposed |
| --- | --- | --- |
| Time before the first embedding batch | 16.9–17.3 s | 18.6–19.9 s (scan 3.5–3.8 s + fetch 15.1–16.1 s) |
| Anonymous memory | 3.96 GB | 3.88 GB |

So in that case the proposed order is 1.3–3 s **slower** than today and holds the same
memory. Such a run then embeds 1.45 million records through the API. With two models
and `--force` the fetch is paid once per model instead of once per run.

(Revision 1 claimed "no path is slower than today for a single model". The reviewers
refuted it: with revision 1's `get_many` the proposed order was 3–5 s slower and held
about 1 GB more, because of the intermediate list of raw values. §3.5 removes that
list; the figures in this table are for §3.5's fetch.)

Not measured: a cold page cache. Both orders must read the whole of `semantics.lmdb`
(1.8 GB) and map nearly the whole vector store file (§3.8), so a cold run is dominated
by disk reads under either order.

## 5. What this plan does not do

- It does not remove the remaining 3–4 s scan of `semantics.lmdb`. Removing it means
  either not scanning the whole DB (against L1) or keeping a durable list of keys that
  await a vector (a new store-level invariant). Neither is proposed.
- It does not move the scan off the RPC host's event loop. The scan still blocks the
  loop, for about 5 s instead of about 18 s.
- It adds no progress line during the scan (that would be new user-visible text).
- It does not change the retry behaviour of the embedding API calls.
- It does not close the window during the embedding API call (§6.3).

Alternatives considered and not proposed:

| Alternative | Why not |
| --- | --- |
| Compile `_decode` with Cython | Speeds up only the field conversion inside `_decode` (about 4 of 18 s; reviewer: about 4.5 s); `msgpack` and LMDB are already C; the garbage collector cost stays, because the objects are still Python objects; adds a compiled extension to the wheel and conda packages. |
| Disable the garbage collector around today's scan | 16.4 s → 8.5 s, but still decodes everything and still holds 3.8 GB for the whole phase. |
| Skip the interpretation test for keys that already have a vector | About 2 s total, but N would then be derived from "a key with a vector must belong to a record with an interpretation", a property no code states or checks. |
| A streaming `msgpack.Unpacker` that reads only the first four fields | About 1 s less (reviewer), but it is a third way of reading the codec. |
| Embed only the records written by this run | Against L1. |

## 6. Safety analysis

Each point says what could go wrong, why I believe it does not, and what that belief
rests on: something I ran, something a reviewer ran (§10), or reading only.

### 6.1 The set of candidates

Old rule: `_decode(raw)` succeeds and `rec.interpretation is not None` (and
`rec.kind in kinds` when `kinds` is given).
New rule: `_interpreted_kind(raw)` is not `None` (and is in `kinds`).

- **Ran (author, §3.2's rule):** on the user's database both rules give the identical
  set of keys, 1,451,030 at the time of the comparison.
- **Ran (reviewer, revision 1's rule with the kind test):** identical sets, also with
  `kinds={EXPERIENCE}` (6,768 keys under each rule, same order).
- **Ran (reviewer):** the database contains no record without an interpretation, and
  exactly one non-16-byte key whose value `_decode` rejects — the counter key, whose
  value is an integer. Both rules reject it.
- **Ran (reviewer):** 72 scenarios on a synthetic two-layer database (every kind; field
  counts 1–4, 8, 12, 13, 14, 15, 16; with, without and with an empty interpretation;
  experiences with patterns, without, with legacy JSON in `expr`, with corrupt JSON;
  user records shadowing system records, user tombstones over system records,
  system-only records; `kinds`, `force`, `confirm` crossed with vector presence) —
  identical returned triple, report and warning lines, embedded keys and exact document
  text. The same holds single-layer and on an empty database.
- **Ran (author, §3.2's rule, constructed values):** the two rules differ in one
  direction only. The new rule accepts, and the old rule rejects, a value that passes
  `_decode`'s first stage with a valid kind and a non-`None` interpretation field but
  on which `_decode` then fails: a field stored as msgpack `bin` holding bytes that are
  not UTF-8, a constituents field that is an integer, a position with two elements, a
  `bin` value of six bytes, an integer too large for `bytes()` in the digest field
  (`OverflowError`; likewise in deps or a constituent hash — so `get_many`'s own
  `except` must stay broad, §3.5). There is no value that the old rule accepts and §3.2's rule
  rejects among those tried (a float kind, a boolean kind, `bin` values of 4 and 5
  bytes, which `_decode` accepts today, are accepted by both).
  Such a key is counted in N. If it lacks a vector it reaches the fetch; what happens
  there is decision D1.
- **Not in the database:** the reviewers and I found no such value there, and `_encode`
  cannot write one.

(Revision 1's account of these values was wrong in three places, all found by running:
a msgpack `str` field with invalid UTF-8 is rejected by both rules, because
`msgpack.unpackb` itself raises; "a `bin` of at most 15 bytes" should have been "4 or 5
bytes"; and a float kind was a third, unstated difference. §3.2's rule removes the
second and third.)

### 6.2 N

N is `len(candidates)` under both orders. It is the same number except that a value of
the kind described in §6.1 is now counted, and a record deleted between the scan and
the fetch stays counted (today it stays counted too, and is embedded).

### 6.3 A record changes during the embed phase

This is where "safe" matters most, because the vector-layer self-sufficiency invariant
has no read-side backstop: a vector computed from an outdated text is served forever
unless something tombstones it.

A writer of a record first tombstones the key's vector in every model store and then
writes the record (`Semantic_DB.__setitem__`; rule 1 of `VECTOR_INVALIDATION_PLAN.md`
§5). For one key the embed phase performs, in order: the scan, the presence check, the
read of the record text, the embedding API call, the vector write. A wrong vector
results exactly when the vector write lands after the writer's vector tombstone while
the record text was read before the writer's record write.

Today the record text is read **during the scan**. Proposed: it is read **at the fetch**,
after the presence check.

The embed phase runs outside the interpretation lock (`interpret_with_parallel` wraps
only the interpretation in `with_interpretation_lock`; `embed_phase` is called after it
returns; on the "Nothing to interpret." path the lock is never taken). Writers that can
run during it: another interpretation run in this or another process, the point-fix
interpretation of `_auto_embed`, `put_experience` / `delete_experience`, and the CLI in
another process.

**The claim, as qualified by review:** for every key that both orders embed, the
proposed order never embeds an older text than today's order does.

What the reviewer established by deterministic tests on a throw-away database, with a
stub embedding provider that injects a write at a chosen moment, every scenario run
under both orders:

| A record is … | Today | Proposed |
| --- | --- | --- |
| rewritten between the scan and the presence check (`Semantic_DB[k] = rec`, `update_expr`, the semantic change gate's `put_interpretation`, a user rewrite over a system record) | vector from the OLD text, permanently | vector from the new text |
| the same, by another task on the same event loop: the handler awaits `connection.config_lookup` after the scan, so this needs no second process | vector from the OLD text | vector from the new text |
| rewritten by another process between the presence check and the fetch | vector from the OLD text | vector from the new text |
| deleted after the scan (`Semantic_DB.delete`, `delete_experience`, `clean_wip`, `_execute_removal`, a user tombstone over a system record) | a vector is written for a record that no longer exists | the key is skipped |
| rewritten during the embedding API call of model A, in a CLI run over models A and B | A and B both from the OLD text | A from the OLD text, B from the new text |
| rewritten during its own embedding API call | vector from the OLD text | vector from the OLD text |
| deleted during its own embedding API call | a vector for a record that no longer exists | the same |

The last two rows are the window this plan leaves open, identically under both orders.

**One corner in which the proposed order is worse** (found by the reviewer, reproduced
in two variants): a record that cannot be embedded at the time of the scan — an
experience with no `goal_patterns`, or a value of the kind described in §6.1 — is made
embeddable before the fetch, and is then rewritten again during the embedding API call.
Today the record is not embedded in this run and ends without a vector, which the next
run supplies. Under the proposed order it is embedded from the intermediate text, and
the second rewrite leaves that vector outdated. The cause is that the proposed order
embeds a record today's order would not embed in this run, and every record that is
embedded is exposed to the window of the last two table rows. It needs two rewrites of
one key within one embed phase, the first one repairing a record that could not be
embedded; on the user's database 0 of 6,768 interpreted experiences are in that state,
and an interpreted entity record always has document text.

### 6.4 What the user sees when a record is deleted or rewritten during the embed phase

- Deleted between the scan and the fetch: skipped without a message; it stays counted
  in N. If every todo key was deleted, the existing line `nothing embeddable.` is
  printed (today: the deleted records are embedded and `done` is printed).
- Rewritten so that it has no document text any more: it appears in the existing
  warning about records with no embeddable document text. No writer in the tree sets an
  interpretation to `None` (reviewer's search), so this is theoretical.

### 6.5 Layers and tombstones

The scan uses the same `iter_items` merge as today; the fetch uses the layered batch
read `_auto_embed` already relies on.

- **Ran (reviewers), synthetic two-layer stores:** §6.1's 72 scenarios; the concurrency
  scenarios of §6.3 that involve a system layer.
- **Not runnable on the user's database:** no system DB is installed on this machine
  (`validated_system_db()` returns `None`).

### 6.6 LMDB transactions

`iter_items` holds one read transaction per layer for the duration of the walk; the walk
is synchronous and finishes before the presence check and the fetch open theirs.
`_raw_getter` enters its transactions on the caller's `ExitStack`, so `get_many` and
`contains` close them when their `with` block exits, on every path including an
exception from `_decode`. Nothing nests beyond what `_get_raw_many` nested before (the
system transaction inside the user one).

- **Ran (reviewer):** the proposed scan and fetch on single-layer and two-layer stores.
- **Ran (author, implemented code):** the test of §8 item 6 records every read
  transaction `get_many` begins and, inside the `except` clause, while the exception
  still pins `get_many`'s frame, finds one per layer and none still open —
  single-layer and two-layer; against the user's database, §11.3.

### 6.7 `contains` with `buffers=True` (§3.8)

- **Ran (two reviewers):** key by key on the user's database, 1,451,030 keys, zero
  differences between the two variants. All of those keys had a vector at the time.
- **Ran (two reviewers), synthetic:** real vector, tombstone, absent key, system-only
  vector, user tombstone over a system vector, user vector over a system vector, an
  empty value in the system store — identical on both paths of `_raw_getter` (the
  single-layer shortcut and the two-layer path).

### 6.8 Tests

`archive/tests/test_complete_vector_store.py` (17 cases, all passing today; on disk and
deliberately not tracked by git) passes `(key, dict)` candidates and monkeypatches
`_collect_embed_candidates`. Under this plan those tests pass keys and stub
`Semantic_DB.get_many`. Today they are hermetic because the candidates carry the
records; after the change a test that forgets the stub would open the live
`semantics.lmdb`. Guard: an autouse fixture in that file that points `SEMANTIC_DB_DIR`
at a temporary directory.

## 7. Decisions (taken by the user, 2026-10-02)

**D1 — a todo key whose record does not decode at the fetch** (a value of the kind
described in §6.1; none exists in the user's database).

**Decided:** it is counted among the records with no embeddable document text. It
appears in the existing warning (text S4, wording unchanged) and is skipped.

The two variants not chosen: skipping it without a message (a counted candidate would
then have no vector and nothing would say so); letting the command fail (the embed
phase also runs when there is nothing to interpret, so every
`run_semantic_interpretation` would fail until the record is removed).

Today: such a record is skipped without a message and is not counted in N.

(Revision 1's D1 also covered a record deleted since the scan. That case is not a
decision: it follows the existing convention of `embed_keys` and `_auto_embed`, §3.6.
Revision 1's D2, deleting `iter_entity_records`, is withdrawn, §3.3.)

**D3 — `contains` without copying the vector values (§3.8).**

**Decided:** included.

## 8. Tests

In `archive/tests/` beside the existing ones, against a throw-away `SEMANTIC_DB_DIR`
(never the live cache directory):

1. Extend `test_record_field_count_is_the_codec_arity`:
   `Record._fields[F_X] == "x"` for every `F_*` constant, `F_INTERPRETATION` included.
2. `_interpreted_kind` against `_decode` on a corpus: every codec generation (8, 12, 13,
   14, 15 fields, and fewer than 4), every `EntityKind`, with and without an
   interpretation, a legacy experience with JSON in `expr`, a float and a boolean kind,
   `bin` values of 4, 5 and 6 bytes, the counter key's integer, a map, a truncated
   value, an invalid kind, a `str` field with invalid UTF-8 (both reject), a `bin` field
   with invalid UTF-8, a malformed constituents / position field and a digest that is
   an integer too large for `bytes()` (new rule accepts, `_decode` raises — the last
   with `OverflowError`). Asserted: `_interpreted_kind` never raises; whenever `_decode`
   succeeds with an interpretation, `_interpreted_kind` returns its kind.
3. `iter_interpreted_keys` on a two-layer store (a user record shadowing a system
   record in both directions of having an interpretation, a user tombstone over a
   system record, a system-only record, 16-byte status keys): the same keys, in the
   same order, as `iter_entity_records` filtered on `interpretation`.
4. `complete_vector_store`: the 17 existing cases adapted to keys, with the autouse
   fixture of §6.8; plus a todo key deleted before the fetch (skipped, no message) and
   a todo key holding each corpus value of item 2 that the new rule accepts and
   `_decode` rejects (listed in the warning and skipped, D1 — so narrowing `get_many`'s
   `except` to `(ValueError, TypeError)` fails a test; §11.2 names the narrowing that
   still passes).
5. A record rewritten after `_collect_embed_candidates()` returned and before
   `complete_vector_store` runs is embedded from its new text.
6. `get_many`, single-layer and two-layer: default keyword raises on an undecodable
   value as today; with the keyword it yields the given object; a deleted key yields
   `None` in both. When it raises, asserted INSIDE the `except` clause (after a
   `with pytest.raises` block the interpreter has already torn the frame down and any
   shape passes — review C1): every read transaction `get_many` began is recorded, one
   per layer and none still open (both layers — re-review R6), and exactly two values
   were read for `[good, bad, good]` — decoded as read, the third never read (review
   C7). Mutation-checked, §11.2.
7. `contains` with a real vector, a tombstone, an absent key, on the single-layer and
   the two-layer path.
8. The scan's `except` is narrow: with `_KIND_VALUES` removed from the class,
   `_collect_embed_candidates()` raises `AttributeError` instead of returning an empty
   list (review C5).

Differential check on the real database, read-only, before and after the change: the
set of candidate keys under `iter_entity_records` filtered on `interpretation` and
under `iter_interpreted_keys` is identical.

Manual: `run_semantic_interpretation` in jEdit on a theory with nothing to interpret;
the time between the opening line and `already complete` drops from about 18 s to about
5 s and the lines are unchanged. `isabelle-semantics embed` prints the same lines as
before.

## 9. Not verified by anyone

The user reviewed this list on 2026-10-02 and judged it not to be a blocker.

- A cold page cache (dropping it on a shared machine was ruled out).
- Two-layer behaviour on a real installed system DB (none on this machine; verified on
  synthetic two-layer stores only).
- Concurrency driven by a real Isabelle session: every interleaving of §6.3 was forced
  from Python.
- The real RPC handler end to end from a live Isabelle session under the implemented
  code (the handler was run with a stub connection only), and the multi-model CLI loop
  with `--force`. The RPC host of a running Isabelle keeps the old code until Isabelle
  is restarted.
- Why the run of 2026-10-01 waited 39 s rather than about 18 s.
- That a `True`/float kind reaches the `kinds` filter correctly (read only; such values
  do not exist in the database).

## 10. Independent verification (2026-10-02)

Four reviewers (Opus), one lens each, instructed to refute the plan and to run code
rather than read it. They modified no existing file; their scripts and outputs are in
`ai-artifacts/review_embed_scan/{equivalence,concurrency,contract,measurement}/`
(experiment scripts and results: not to be committed). The author's follow-up scripts
are in `ai-artifacts/review_embed_scan/author/`.

| Lens | Verdict | What it changed in this plan |
| --- | --- | --- |
| Equivalence of the candidates and of the output | Safe on every well-formed input it could construct; identical candidate sets on the real database. No blocker or major finding. | §6.1 rewritten (three inaccuracies about malformed values); §3.2's rule now shares `_decode`'s first stage and its kind test, which removes two of the differences; D1 narrowed. |
| Concurrency, the vector-layer self-sufficiency invariant, LMDB | Safe, and better than today in almost every interleaving; one corner in which it is worse. | §6.3: "never worse" replaced by the qualified claim, the table of tested interleavings, and the corner. §3.5: no intermediate list of raw values. |
| Callers, approved decisions, design | Core idea sound; not approvable as written in revision 1. | §3.3: `iter_entity_records` has five more users and is kept (D2 withdrawn). §3.2: named field positions, existing test extended instead of a new pinning test. §3.5/§3.6: deleted and undecodable records are told apart. §6.3: descriptive phrases instead of ad-hoc labels. |
| Measurements and memory | The claims for the usual case hold (21–24 s → 5.2–5.6 s; 3.78 GB → 0.19 GB); one claim refuted. | §4: the every-record-must-be-fetched case stated with numbers; §3.8: the py-lmdb statement now refers to the build actually in use, with the reviewer's page-fault measurement. |

No reviewer found a conflict with L1–L6, with the approved texts S1–S4, or with the
vector-layer self-sufficiency invariant, and none found something that
`VECTOR_INVALIDATION_PLAN.md` §12 had already rejected.

### Observations outside this plan

Things the review surfaced that exist today and that this plan does not touch:

1. A record rewritten or deleted during its own embedding API call ends with an
   outdated vector, or a vector without a record (§6.3, last two table rows).
2. A THEORY-kind record that has an interpretation makes the completion fail with
   `KeyError` from `pretty_print` (reproduced on a synthetic database; none on the real
   one).
3. The warning about records with no embeddable document text lists `k.hex()[:16]`,
   which is the theory part of the key: every key of one theory prints the same 16
   characters.
4. `iter_entity_records`' docstring says the environment "allows only one live read
   txn" per thread. A reviewer's probe opened several live read transactions in one
   thread and called `get_many` in the middle of an `iter_items` walk without error.
   The rule "do not re-enter the store while iterating" is harmless; its stated reason
   is not accurate.
5. During the embed phase, connection-level failures of the embedding API (timeouts,
   DNS) are retried without any output for up to about 17 minutes
   (`AUTO_EMBED_AFTER_INTERPRETATION_PLAN.md`, "Status-quo note").

### 10.1 Code review (2026-10-02, after implementation)

A two-round adversarial review of the implemented code, run as a workflow (Opus,
xhigh): five challengers (behaviour, resources and failure paths, elegance and design,
tests, conformance and documentation) raised 13 challenges, merged to 9; one fresh
defender per challenge; a judge. Records: `ai-artifacts/review_embed_scan_code/`
(`SCOPE.md`, `challenges.json`, `defenses.json`, `judge.json`; scratch under
`scratch/`). The judge found AC1–AC4 (behaviour, decided behaviour, no collateral
change, resource discipline) met and AC5 (tests) and AC6 (elegance) not met: readiness
ACCEPTABLE_AFTER_FIXES, re-review needed. Two challengers ran the HEAD code against the
working tree on identical throw-away two-layer databases, 17 and 20 scenarios, through
the real `_embed_models` and `_embed_all_missing`: byte-identical output, embedded
texts and vector-store contents, including the multi-model `--force` loop.

| Id | Challenge | Ruling | Route | Done |
| --- | --- | --- | --- | --- |
| C1 | The test meant to guard `get_many`'s `raws.close()` passed with the `close()` removed (the check ran after `pytest.raises` released the traceback) | fix, major | self-decide | §8 item 6 |
| C2 | `_iter_raw_many`, a transaction-holding generator, relied on a docstring rule and a hand-written `close()`, while `Vector_Store._raw_getter` already does the same read by construction | fix, major | owner (P1) | §3.5 |
| C3 | `_interpreted_kind`'s docstring ("LATER fields") was false | fix, minor | self-decide | §3.2 |
| C4 | `_interpreted_kind` and `_decode` each held a copy of the unpack-and-pad step; `unpack_fields` exists for it | fix, minor | owner | §3.2 |
| C5 | The blanket `except Exception` made a programming error read as `already complete (0 entities).`; the counter key reached it | fix, minor | self-decide | §3.2, §3.3, §8 item 8 |
| C6 | The docstring cited a plan file not under version control | fix, minor | owner | plan moved to `archive/plans/` |
| C7 | Nothing tested that `get_many` decodes as it reads | fix, minor | self-decide | §8 item 6 |
| C8 | The plan misdescribed the code in four places (two snippets with bare class-attribute names, a missing `get_many` caller, "17 of the 17" tests using `db`) | fix, minor | self-decide | §3.2, §3.5, §11.1 |
| C9 | A false return annotation, two mypy errors in new code, "presence test" beside "presence check", a stale "in one read txn" | fix, minor | owner (typing) | mechanical parts only |

Owner decisions (2026-10-02): P1 (the getter shape) adopted; C4 adopted; C6 resolved by
moving this plan to `archive/plans/`; C9: the mechanical parts only, the return
annotation stays approximate (no type checker is configured for the package). P2
(withdraw D1 and let an undecodable record raise) was not put to the owner: the judge
held that D1 had already weighed that trade-off.

Rejected by the judge, as hair-splitting or not a defect: that the `F_*` comment block
should list its users (a list goes stale; the proposed rule wording was false on
arrival); that `complete_vector_store`'s "text no older than the presence check" needs
a `force` caveat (the preceding clause already says `force` skips the check); that
`_collect_embed_candidates`' docstring does not say where the records come from (its
first paragraph does).

### 10.2 Re-review (2026-10-02, after the round-1 fixes)

Same shape, four challengers (fix conformance, behaviour and collateral change,
elegance, tests): 7 challenges merged to 6, one fresh defender each, a judge. Records:
`rereview_challenges.json`, `rereview_defenses.json`, `rereview_judge.json` in
`ai-artifacts/review_embed_scan_code/` (scratch under `scratch2/`). The judge ran its
own differential of HEAD against the working tree (30 scenarios, single- and two-layer,
byte-identical) and its own mutation plugin, and found AC1–AC4 met, AC5–AC7 not met:
ACCEPTABLE_AFTER_FIXES, with a one-reviewer conformance check to follow rather than a
third two-round review.

| Id | Challenge | Ruling | Route | Done |
| --- | --- | --- | --- | --- |
| R1 | The C4 edit turned the codec block's rule into the false claim "Nothing redeclares the pad or the indices" (four bare positional reads exist) and dropped the prohibition | fix, minor | self-decide | the block now says: index `unpack_fields`' result by the `F_*` names, never by a bare number; §3.2, §11.1 |
| R2 | §11.1 said the 12 `db` tests reach the fetch (11 do); §2 item 6 named the deleted `_get_raw_many` | fix, minor | self-decide | both corrected |
| R3 | `_Semantic_DB._raw_getter` duplicates `Vector_Store._raw_getter`; share one | rejected (refuted) | — | HEAD already had two layered batch reads; the change added none; the owner adopted this shape (P1); sharing would tie the record rule to the vector rule, which a different plan owns |
| R4 | `_interpreted_kind`'s `except` comment named the two index reads as raisers; they cannot raise (`unpack_fields` pads), the membership test does | fix, minor | self-decide | comment corrected; §3.2 |
| R5 | D1 was tested with one `TypeError` value only; narrowing `get_many`'s `except` passed every test although a stored value exists (an integer too large for `bytes()` in the digest field, `OverflowError`) on which the scan counts and `_decode` fails | fix, minor | self-decide | that value added to the corpus; the fetch test runs over every corpus value the scan accepts and `_decode` rejects; §6.1, §8 |
| R6 | The read-transaction check saw only the user layer (the system env has no reader table, `lock=False`); a leaked system transaction, or fresh transactions per key, passed | fix, minor | self-decide | the test records every transaction `get_many` begins and asserts one per layer, none open; §6.6, §8 |

One relaxation proposal (route `_get_raw`, the single-key read, through `_raw_getter`)
was not put to the owner: a measured slowdown on the most frequent read path for a
small gain.

## 11. Implementation record (2026-10-02)

Ordered by the user as "implement, do not commit". Nothing is committed.

### 11.1 What changed

Source — two files. (`git status` of the Semantic_Embedding repository also shows
`.gitignore` and `Tools/entity_position.ML` as modified; those changes were there
before this work and are not part of it.)

- `Isabelle_Semantic_Embedding/semantics.py`: `F_INTERPRETATION`; `_decode` starts
  with `unpack_fields` (its first stage was a bare copy of it); `_Semantic_DB._KIND_VALUES`,
  `_interpreted_kind` (narrow `except`); `_raw_getter` on the caller's `ExitStack`,
  replacing `_get_raw_many`; `Semantic_DB.contains` and `get_many` on it; `get_many`'s
  `undecodable` keyword; `_iter_entity_items` (entity keys: longer than 16 bytes);
  `iter_interpreted_keys`; `iter_entity_records` rewritten on `_iter_entity_items`;
  `_collect_embed_candidates` returns keys; `complete_vector_store` takes keys and
  fetches the records it will embed; the codec comment block names `unpack_fields` as
  `_decode`'s first stage and its rule now binds every reader of `unpack_fields`'
  result to the `F_*` names (the old wording pointed at `_decode`'s bare `15`s, which
  C4 removed, and at migration passes deleted in commit 8ab828f; re-review R1).
- `Isabelle_Semantic_Embedding/semantic_embedding.py`: `Vector_Store.contains` uses
  `buffers=True`.

`_embed_all_missing` and `_embed_models` are textually unchanged.

The §3.2 and §3.5 snippets were corrected after implementation (review C8): they used
the class attributes `_KIND_VALUES` and `_RAISE` by bare name, which the implemented
code never did.

Tests (`archive/tests/`, on disk and not tracked by git; the originals of the two
edited files are kept as `ai-artifacts/review_embed_scan/author/*.orig`):

- `test_complete_vector_store.py`: the 17 existing cases pass keys; the 12 of them that
  passed (key, record) candidates now pass those pairs to the fixture `db`, which
  returns the keys and serves the records through a stubbed `Semantic_DB.get_many`
  (11 reach the fetch; `test_already_complete_single_line` stops at "already
  complete"); the other 5 pass no candidates and never reach `get_many`, which the
  autouse fixture `no_live_db` enforces by failing any test that reaches it without
  that stub; 5 new cases (only todo records are fetched, and
  after the presence check; nothing is fetched when already complete; a record deleted
  since the scan; every todo record deleted; a record that does not decode).
- `test_semantic_change_gate_storage.py`: `test_record_field_count_is_the_codec_arity`
  asserts `Record._fields[F_X] == "x"` for every `F_*` constant of the module.
- `test_embed_completion_scan.py` (new, real LMDB in a temporary directory, reusing
  `test_layered_db`'s fixtures): `_interpreted_kind` against `_decode` for every kind,
  11 field counts and three interpretation values; experiences; 15 values that are not
  well-formed records; `iter_interpreted_keys` against `iter_entity_records` on a
  two-layer store, with `kinds`; the narrow `except` of the scan (§8 item 8);
  `get_many`'s keyword, its read transactions and its decode-as-read property, both
  asserted inside the `except` clause, single-layer and two-layer (§8 item 6); the
  completion end to end with a record rewritten after the scan, and with deleted and
  undecodable records at the fetch.

Not written: §8 item 7 (`contains` on real vector / tombstone / absent key). The
existing `test_layered_db.py` already asserts `store.contains` for a system-only
vector, a real vector that becomes a tombstone, and the single-layer shortcut, and it
passes with the change.

### 11.2 Test results

Run with `SEMANTIC_DB_DIR` pointing at an empty scratch directory (which stayed empty),
from `archive/tests/`:

| | Before the change | After the change | After the review fixes | After the re-review fixes |
| --- | --- | --- | --- | --- |
| The 12 test files that touch the record and vector stores | 212 passed, 8 failed | 217 passed, 8 failed | — | — |
| The 10 of those files without the two known-failing ones, plus `test_embed_completion_scan.py` | — | — | 265 passed | 271 passed |
| The 4 files of the review's test command | — | — | 146 passed | 152 passed |
| `test_embed_completion_scan.py` alone | — | 52 passed | 54 passed | 60 passed |

The 8 failures are the same before and after and are unrelated: 7 in
`test_migrate_from_collection.py` (`ModuleNotFoundError: migrate_from_collection`) and
`test_entity_position_backfill.py::test_the_completeness_scan_counts_the_right_things`.

Mutation checks of `test_embed_completion_scan.py` (§8 items 4, 6 and 8), by pytest
plugins that swap the implementation in memory and never touch a source file. The
author's plugin, `ai-artifacts/review_embed_scan/author/plugins/author_mut.py`, after
the review fixes: a `_raw_getter` that does not enter its user transaction on the stack
(and, as a side effect of how it was written, drops the system layer) — 2 tests of that
file fail; a `get_many` that reads every value before decoding — 2 fail; the scan's
`except` widened back to `Exception` — 1 fails; the code as written — all pass.
(Revision 2's mutation check of `raws.close()` was made in a scratch script, not in the
test, which is what review C1 found.)

The re-review judge's plugin,
`ai-artifacts/review_embed_scan_code/scratch2/judge/plugins/judge2_mut.py`, re-run on
that file after the re-review fixes (60 tests): user transaction not on the stack — 2
fail; system transaction not on the stack — 1 fails (re-review R6; passed before the
fix); fresh transactions per key — 2 fail (R6; passed before); eager read — 2 fail;
`get_many`'s `except` narrowed to `(ValueError, TypeError)` — 1 fails (R5; passed
before); the scan's `except` widened — 1 fails; the code as written — all pass. One
mutant still passes: `get_many`'s `except` narrowed to
`(ValueError, TypeError, OverflowError)`. Catching it would need a corpus value whose
decode fails with `MemoryError`, which depends on the platform's allocator; the judge
accepted leaving it out.

### 11.3 The implemented code against the user's database (read-only)

`confirm` declined in every run, so nothing was embedded and nothing was written.

- **Candidates:** `_collect_embed_candidates()` returns the same list, in the same
  order, as `iter_entity_records()` filtered on `interpretation` (1,451,030 keys); with
  `kinds={EXPERIENCE}` 6,768 keys under both.
- **The usual case** (nothing lacked a vector), scan plus `complete_vector_store`:
  5.45 s in a fresh process and 4.06 s on a second pass in the same process (scan
  3.3–3.8 s, presence check 0.7–1.6 s); output
  `Qwen/Qwen3-Embedding-8B: already complete (1451030 entities).`; anonymous memory
  0.18–0.20 GB.
- **The case where every record is fetched** (`force=True`), up to the confirmation
  prompt, which includes computing the document text of all 1,451,030 records:

  | | Today's bodies | Implemented |
  | --- | --- | --- |
  | Total, three runs each | 23.5, 25.5, 30.3 s | 23.8, 28.7, 32.9 s |
  | of which garbage collector (timed with `gc.callbacks`, two runs each) | 12.9, 16.8 s | 9.7, 11.1 s |

  The machine was busy and the runs scatter by several seconds; the two orders are not
  distinguishable at that noise. §4's "1.3–3 s slower" is therefore not confirmed and
  not refuted; what is established is that the implemented order is not markedly slower
  and that its output line is unchanged
  (`1451030 of 1451030 entities need vectors (657562039 chars).`).

After the review fixes (the getter shape, `unpack_fields` in both readers, the narrow
`except`), re-run read-only: the candidate lists are identical to the old rule's as
before (1,451,030; 6,768 with `kinds={EXPERIENCE}`); the usual case 4.9 s in a fresh
process and 4.1 s on a second pass (scan 3.4–3.7 s, presence check 0.7–1.2 s); the
every-record-fetched case 22.9 s with 9.3 s of garbage collection. One fresh-process run
of the usual case took 20.7 s because the presence check alone took 16.9 s: the vector
store's file pages had been evicted by the reviewers' processes, and the next pass took
1.2 s. That is the cold-page-cache cost §4 says it did not measure: about 17 s for the
presence check, under either order.

### 11.4 To take effect

The RPC host of a running Isabelle session imported the old module and keeps it; the
change takes effect in the next Isabelle session (a new RPC host). The CLI picks it up
on its next invocation.

