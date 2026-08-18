# Entity positions in the semantic DB

Status: **done.** Steps 1–4 implemented, the L9 rework and the review fixes
applied, and step 5 executed on `cslh19` on 2026-08-12: 9,955 theories swept,
1,062,951 records now carry an entity position, zero line mismatches, zero vector
tombstones. §18 has the numbers and the four corrections the run forced.
§16 records what landed; §17 records the round-2 code review, the L9 rework, and
the round-3 review of the edit itself.
Draft 4, 2026-08-11. Draft 1 was reviewed adversarially (two turns, four lenses)
as a *design*; draft 2 folded in the surviving findings and the user's decisions;
draft 3 added the implementation handover (§15) and corrected §8.1 after reading
the scheduling code properly. Draft 4 records the second adversarial review — of
the *code* this time, five lenses — the user's L9 decision that came out of it,
and then a third review of that very edit (§17.4), which corrected §8.4's
acceptance criterion and a contradiction between §8.3 and §8.5.

Orientation for a reader arriving with no other context: §2 is the settled
decisions (do not reopen), §16 is what was built, §17 is the review that followed
and the outstanding work, §15 is the build order the implementation followed, §14
is what was already argued and rejected. The two things still requiring a human
are the kill-and-restart on `cslh19` (§15.5) and §8.5's hit-rate floor, which is
chosen from the canary's histogram rather than guessed.

Every "LOCKED" item in §2 is an explicit user decision — do not re-litigate them,
ask before deviating. §14 lists what the review raised and what was rejected; do
not re-raise those either.

**This document is written to be self-contained.** A reader who has only this
file and the repository should be able to implement the whole thing. Citations
name **functions, not line numbers** — this is a shared working tree and line
numbers move (the same convention `VECTOR_INVALIDATION_PLAN.md` adopted after
three commits shifted every reference during its own review).

## 0. Summary

The semantic DB records what an Isabelle entity *means* but not *where it is
written*. This plan adds an **entity position** — `file`, `line`, `column` — to
every entity record, on both the live collection path and, by a backfill pass,
to the ~1.35 M records already collected from the AFP.

Three independent pieces:

1. **Produce** the position in Isabelle/ML (§5). The `Position.T` is already
   carried end-to-end by the collection pipeline; today only its line survives,
   and only into an LLM prompt.
2. **Store** it as a 13th field of the record codec (§4, §7).
3. **Backfill** the existing AFP data by composing the exported scheduling
   primitives with no LLM involved (§8), on `cslh19` under the `AFP-ALL-4`
   session image (§9).

## 1. Glossary — canonical names, never paraphrased

| Term | Meaning |
|---|---|
| **entity position** | The triple (`file`, `line`, `column`) locating where an entity is declared in Isabelle source. The record field is named `position`. Never "location", "site", "source ref". |
| **`file`** | The **portable symbolic file path** (below). |
| **`line`** | 1-based line number, the number `Position.line_of` reports. |
| **`column`** | 1-based **byte column** (below). |
| **portable symbolic file path** | A path rooted at `$AFP` or `~~` (Isabelle's own spelling of `$ISABELLE_HOME`), e.g. `$AFP/Shadow_DOM/Shadow_DOM.thy`, `~~/src/HOL/Nat.thy`. These two roots are the only ones whose contents are the same on every machine. Every other path is stored absolute (L1'). |
| **byte column** | Count of UTF-8 bytes from the start of the line to the position, plus 1. `\<forall>` on disk is 9 bytes and therefore 9 columns; a literal `∀` is 3. |
| **symbol offset** | Isabelle's own coordinate: 1-based count of Isabelle symbols from the start of the file, what `Position.offset_of` returns. `\<forall>` is **one** symbol. |
| **position backfill** | The one-off pass that adds entity positions to already-collected records (§8). |
| **completeness scan** | One cursor pass over `semantics.lmdb` counting entity records by codec length, and among 13-field ones how many carry a position. It answers "what has the backfill not reached" **from the data**, never from a bookkeeping flag (L9). Measured on the 1.7 GB store: **3.2 s**, msgpack-decoding every value. |

**Measured, not assumed** (`isabelle ML_process -l HOL`, 2026-08-09): a
heap-resident entity's position already carries a symbolic path.

```
HOL.refl         ||| file=~~/src/HOL/HOL.thy  ||| line=220 ||| offset=7044
List.list.induct ||| file=~~/src/HOL/List.thy ||| line=11  ||| offset=178
```

Draft 1's glossary claimed the spelling would be `$ISABELLE_HOME/src/HOL/Nat.thy`.
That string is never produced by anything in Isabelle; `~~/src/HOL/Nat.thy` is.

## 2. LOCKED decisions

All taken by the user on 2026-08-09.

- **L1** — `file` is stored as a symbolic path, not an absolute path. The DB is
  published (conda `isabelle-semantic-data`, Hugging Face tarball); an absolute
  path from the collecting machine is a dead string everywhere else.
- **L1'** — **only `$AFP` and `~~` are folded.** `File.symbolic_path` folds
  against `ISABELLE_DIRECTORIES = ~:$ISABELLE_HOME_USER:~~:$ISABELLE_COMPONENTS_BASE:$AFP_BASE:$AFP`,
  which includes `~` — so a user's own project under `$HOME` would fold to
  `~/Current/MLML/Foo.thy`, a string that *looks* portable and silently resolves
  to a different file on a consumer's machine. Everything outside `$AFP` and
  `~~` is stored as the absolute path instead: knowingly non-portable, but
  honestly so.
- **L2** — `column` is a **byte column**. Not the Isabelle symbol column, not
  the rendered-Unicode column.
- **L3** — the position lives in the **entity record, as a 13th field**, not in
  a separate store.
- **L4** — the backfill **recomputes universal keys** (route A), rather than
  matching records by name.
- **L5** — the backfill runs on **`cslh19`**, under the `AFP-ALL-4` session image.
  It gets its own REPL server: **kill and restart** the one in byobu window 1
  rather than sharing it. The embedding job in window 2 is **not** to be touched.
- **L6** — **the backfill does not honour the vector-layer self-sufficiency
  invariant, and writes no vector tombstones.** It writes records with a raw
  `txn.put`, bypassing `Semantic_DB.__setitem__`. This is an explicit,
  user-approved exception (§8.3 gives the full reasoning).
  `VECTOR_INVALIDATION_PLAN.md` is **not** amended — by user decision, the
  exception is recorded here and only here.
- **L7** — **premise given by the user**: on `cslh19` the theory sources have
  not been modified since they were compiled into the heaps. The file a heap
  entity's position refers to is byte-identical to the file on disk now. §5.2,
  §8.5 and §11 all rest on this.
- **L8** — no public read API for the position for now; it is an internal field.
- **L9** (2026-08-11, supersedes the original §8.4) — **the backfill keeps no
  bookkeeping flag. There is no `positions_done`, no per-theory skip, and
  nothing is written to any theory-status record.** Resuming an interrupted
  sweep means *running it again*: the write is idempotent, so a second pass over
  a theory produces byte-identical records. Progress is a question asked of the
  data, by the **completeness scan**, not of a flag.

  The user's reasoning, which is the same principle as the vector-layer
  self-sufficiency invariant: a flag is a **second source of truth**, and it can
  disagree with the data. That disagreement is not hypothetical — the round-2
  code review found exactly it (a theory marked done while zero records were
  written, §17.1). Removing the flag removes that whole class of defect by
  construction, rather than guarding against it.

  What is given up: an interrupted sweep re-pays the enumeration. §11.2
  extrapolates ~2 CPU-hours for the full AFP, which at the REPL's `-o threads=12`
  is tens of minutes of wall clock — acceptable. **If §8.7's canary measures it
  much worse, the fallback is a done-list file owned by
  `migrate_entity_positions.py`** — local to the sweep, never in the shared store
  and never in the published payload. The flag does not come back.

## 3. What already exists (reuse inventory)

Nothing here needs inventing. Draft 1's inventory was incomplete; the review
found more, marked **[R]**.

**Isabelle/ML — `Tools/theory_structure.ML`**

- `get_constants_with_positions`, `get_theorems_with_positions`, and the same
  for types, classes, locales, theorem collections, methods and the four rule
  kinds. Each returns a `Position.T` alongside the name, filtered to entities
  whose `#theory_long_name` is the theory being scanned.
- `get_theory_file_path` — the theory's own `.thy`, absolute.

**Isabelle/ML — `Tools/semantic_store.ML`**

- `enumerate_entries : Context.generic -> {file_path, theory_longname,
  theory_key, entries}` — the enumerate half of the pipeline
  (`CHECK_OUTDATE_PLAN.md` §8's two-piece split), shared verbatim by the live
  path (`interpret'`) and the dry run (`dry_run'`).
- `build_entries` — where the position is discarded down to
  `the_default ~1 (Position.line_of pos)`.
- The theorem dedup inside `enumerate_entries` — keeps the occurrence whose fact
  name appears earliest in the source file, using the offsets
  `check_theorem_name_in_file` returns. **The surviving occurrence's `pos`
  becomes the entity position**, so reusing `enumerate_entries` is what makes
  the backfill agree with a live run on which occurrence wins —
  *conditionally*, see §8.6.
- **[R] `collect_cone : theory list -> theory list`** — the whole ancestor cone
  in topological order, deduped, walking *through* excluded theories rather than
  stopping at them. Already in the `SEMANTIC_STORE` signature.
- **[R] `schedule_dag : string -> (theory -> unit -> 'a) -> theory list -> 'a list`**
  — one `Future` per cone node under Isabelle's own DAG scheduler
  (`Thy_Info.schedule_theories` specialised to per-node deps), bounded by the
  REPL's `-o threads=N`, hard-crash failure policy. Already in the signature,
  and its own comment says `body` is a parameter *precisely so* another driver
  can supply a different body.
- `interpret_cone` — the shape to mirror: `schedule_dag` over a cone with a body
  that skips already-done theories and marks them when done.
- `is_interpreted` / `mark_interpreted` — the ML side of the per-theory status
  flag, each a single RPC.

**Isabelle/ML — elsewhere**

- **[R] `File.symbolic_path`** (`Pure/General/file.ML`) — folds an absolute path
  onto an `ISABELLE_DIRECTORIES` root, returns the path unchanged on no match.
  Draft 1 proposed hand-rolling this.
- `PIDE_State.absolutize_id_based_pos` — resolves the ID-based positions the
  interactive path produces into file/line/offset positions.
- `Symbol.explode`, `File.read` — Pure's own symbol splitting and file reading.
  Isabelle/ML strings are byte strings, so a symbol's `size` **is** its byte
  width; `Pure/General/symbol_explode.ML` groups a UTF-8 sequence into one
  symbol. The byte column is a running `size` sum over Pure's own walker.
- **[R] `Tools/semantic_interpretation_app.ML`** — the Isa-REPL socket protocol,
  the `Private_Output` channel hijack that streams progress over the socket, and
  the `ERROR:` framing. §8.2 extracts these rather than copying them.

**Python**

- `Isabelle_RPC_Host/position.py` — `symbol_explode` (a hand port of Pure's),
  `FileIndex` with `sym_ascii_offsets` / `sym_unicode_offsets` /
  `ascii_line_offsets`, six conversions, a watchdog-invalidated per-file cache
  (`get_file_index`), and `IsabellePosition` / `AsciiPosition` / `UnicodePosition`.
- **[R] `PIDE_State.offset_to_line_column` / `line_column_to_offset` →
  `position.offset_to_line_column` / `position.line_column_to_offset`** — an
  ML→`FileIndex` RPC bridge that already exists. It returns the
  *source-character* column, not the byte column L2 requires, so it is not
  directly usable; §5.3 argues against extending it rather than pretending it is
  absent.
- `semantics.py` `_Semantic_DB.Record` / `_decode` / `_encode` — the positional
  msgpack tuple codec, currently 12 fields, grown by tail-append (8 → 12).
- `semantics.py` `unpack_thy_status` / `mark_interpreted` — the per-theory status
  record: a msgpack dict with `bytes` keys, read-modify-written with
  copy-up-then-modify semantics.
- `semantic_interpretation.py` `_entries_of_wire`, `Entry`,
  `InterpretationTask.write_answer` — the wire decoder, the per-entity record and
  the record write.
- `isabelle_semantics.py` `cmd_collect` — how a batch pass drives the REPL app.
- The `migrate_*.py` family — the house pattern for a one-off store rewrite.

## 4. Storage format

`_Semantic_DB.Record` gains a 13th and last field:

```python
    # Where this entity is declared in Isabelle source, as
    # (portable symbolic file path, line, byte column) -- ENTITY_POSITION_PLAN.md §1.
    #
    # NB TWO COLUMN CONVENTIONS COEXIST IN THIS PACKAGE.  This column counts
    # UTF-8 BYTES from the start of the line.  hover.py renders entity locations
    # through IsabellePosition.to_ascii_position(), whose column counts SOURCE
    # CHARACTERS -- a different number on any line containing literal non-ASCII
    # bytes (1,501 of 10,297 AFP and 665 of 2,266 Isabelle .thy files contain
    # some).  Never feed this column to a position.py API without converting.
    #
    # ADVISORY, not authoritative (ENTITY_POSITION_PLAN.md §11.1): recorded on
    # the publisher's AFP snapshot; a consumer's sources may differ, and a
    # content-preserving edit moves the line without changing the key.
    #
    # None when the entity has no source position (§10), and on every record
    # written before this field existed.
    position: 'tuple[str, int, int] | None' = None
```

- `_decode`: `vals += [None] * (13 - len(vals))`, destructure 13, pass through,
  file `str`-decoded via the existing `_dec`. msgpack returns the triple as a
  list — rebuild it as a `tuple`.
- `_encode`: append `record.position`.
- The codec docstring gains the warning the 8 → 12 growth already carries: code
  built before the 13-field codec truncates and would **drop `position` on its
  next write**.

Size: 1,353,574 records × roughly 40 bytes ≈ 55 MB on a 1.7 GB store (~3 %).

Deliberately **not** stored: the end position, the symbol offset, any second
coordinate system.

## 5. Isabelle/ML side

### 5.1 A new module `Tools/entity_position.ML`

One structure, `Entity_Position`, added to `Semantic_Embedding.thy`'s `ML_file`
list **after `pide_state.ML`** (it uses `absolutize_id_based_pos`) and **before
`theory_structure.ML`**:

```sml
signature ENTITY_POSITION = sig
  (* (portable symbolic file path, line, byte column); NONE per §10. *)
  type entity_position = string * int * int
  type report = {no_file: int, unreadable: int, line_mismatch: int}
  (* Batch: absolutizes once, builds each file's index once. *)
  val of_positions : Position.T list -> entity_position option list * report
end
```

**No hand-rolled path folding.** Draft 1 proposed a `symbolic_path` with its own
getenv table; that duplicates `File.symbolic_path`, and less completely (draft
1's table omitted `~` and `$AFP_BASE`). The file is normalised as:

1. `File.symbolic_path (Path.explode f)` — idempotent on the `~~/...` and
   `$AFP/...` strings heap entities already carry, and folds the live PIDE
   path's absolute string to the *identical* result;
2. keep it only if it starts with `"$AFP/"` or `"~~/"` (L1'); otherwise store
   `File.standard_path (Path.explode f)`, i.e. absolute.

Step 2 is what stops a `~/...` fold from entering a published store.

`of_positions` takes a **list** so it can run `absolutize_id_based_pos` once per
batch (that call is a Scala round trip) and build each file's index once.

### 5.2 The byte-column index, the line assertion, and the read guard

For one file: `File.read`, `Symbol.explode`, walk once accumulating a byte
offset, emitting the byte offset of each line start and of each symbol. Then

- `column` = (symbol's byte offset) − (its line's start byte offset) + 1;
- `line` = `Position.line_of`.

**The line assertion.** Isabelle advances `line` and `offset` over one and the
same symbol stream in a single fold (`Pure/General/position.ML`), both seeded at
1 for a file position. So for any position carrying both, `line` **must** equal
1 + the number of `"\n"` symbols before `offset` in the file. The index needed
to check that is the one just built, so the check is one lookup per entity.

Under L7 this is not a drift detector — it is a **self-check on this module's
own symbol walk, CRLF handling and byte arithmetic**, and it must be **zero**.
A nonzero count is a bug here, not an environment problem: count it in `report`,
surface it per theory (§8.5), and **stop the sweep**. No automatic degradation
is designed for it, because under L7 the case cannot legitimately arise.

**`File.read` must not be allowed to raise.** Measured on the built HOL heap: of
101 distinct position files in `Main`'s fact space, 4 fail `File.read` — they are
bare non-rooted names left by Pure's bootstrap (`drule.ML`, `pure_thy.ML`,
`conjunction.ML`, `Isar/method.ML`), and some carry a positive offset, so a
"file present and offset present" gate does not exclude them. Unhandled, the
exception aborts the whole theory's `build_entries`, which in a 9,600-theory
unattended sweep is a stopped run. Wrap the per-file index build in `\<^try>`:
on failure every position in that file degrades to `NONE` and is counted under
`unreadable`. Key the index by the **expanded absolute path**, so a bare relative
name can never be resolved against the process working directory.

CR folding: `Symbol.explode` maps `\r\n` and bare `\r` to `\n`. This shifts
nothing within a line and changes no line number.

### 5.3 Why the column is computed in ML — the honest version

Draft 1 gave three reasons against extending `FileIndex` in
`Isabelle_RPC_Host/position.py`. The review showed **two of them are false**:

- ~~Volume~~ — **withdrawn.** `enumerate_entries` already issues exactly one RPC
  per theory (`Semantic_Store.check_theorem_name_in_file`) carrying every
  theorem short name of that theory. The batched shape draft 1 called too
  expensive is already borne on the collection path today.
- ~~LRU thrashing~~ — **withdrawn.** `position.py` evicts by *directory*
  recency with a cap of 64 (`_MAX_WATCHED_DIRS`), and a theory-at-a-time sweep is
  sequential and never re-references an evicted directory. That is a bounded
  working set.
- **Co-location — this is the reason, and it stands alone.** Python-side
  conversion requires the RPC host process to `open()` the theory file. That
  holds for the `cslh19` collection (RPC host on `127.0.0.1:27182`) but is not
  guaranteed in general. The asymmetry that matters: when
  `check_theorem_name_in_file` fails it only perturbs a tie-break heuristic and
  warns, whereas a failing position RPC would lose the payload outright.

And the route is **not unexplored**: `pide_state.ML` already bridges ML to
`FileIndex` over RPC (§3 **[R]**). It returns a source-character column, not the
byte column, so it is not directly usable — but the plan must say so rather than
describe the alternative as absent.

The duplication objection does not hold in the direction it was raised:
`File.read` and `Symbol.explode` are Pure's own, whereas `position.py`'s
`symbol_explode` is a hand port that already diverges from Pure (it does not
implement the pseudo-UTF8 `\192`+control case). Drift risk runs the other way.

### 5.4 `build_entries`

`the_default ~1 (Position.line_of pos)` becomes the entity position, computed
for the whole batch by `Entity_Position.of_positions`. The prompt's `[line N]`
uses the position's `line` (staying `-1` when there is none), so
`semantic_interpretation.py`'s `line_number > 0` prompt guard is untouched.

## 6. Wire format

`interpret_file` and `interpret_file_dry_run` share one `pack_arg` on the ML
side and one decoder (`_entries_of_wire`) on the Python side. Field 4 of each
entry, today `line : int`, becomes the entity position as an option of a triple.

**Before** (ML `make_interpret_file_cmd` / `interpret_file_dry_run_cmd`):

```
entries: (Universal_Key.entity * string * string * int * Word8Vector.vector * string
          * (Word8Vector.vector option * Word8Vector.vector option * string) option
          * Universal_Key.constituent list
          * Word8Vector.vector option * Word8Vector.vector list) list
                                  ^^^ field 4 = line
```

**After**:

```
          ... * string * string * (string * int * int) option * Word8Vector.vector * ...
                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^ field 4 = entity position
```

Python `_entries_of_wire`'s destructuring changes from

```python
for kind, name, prop, lineno, uk, hint, prov, consts, digest, deps in raw_entries
```

to bind `position` in place of `lineno`, decode its file with `pretty_unicode`
(it is a byte string on the wire), and pass `position=...` to `Entry`.

Both commands change together, in one commit, on both sides: an ML build newer
than the installed Python package (or the reverse) fails to decode.

## 7. Python side

- `semantics.py` — §4's codec change.
- `semantic_interpretation.py` — `Entry` gains
  `position: 'tuple[str, int, int] | None' = None` and `line_number` becomes a
  **derived property** (`self.position[1] if self.position else -1`) so
  `format_entries` and `_pretty_print_entry` are untouched. `write_answer`'s
  `SemanticRecord(...)` call gains `position=entry.position`.
- `Isabelle_RPC_Host/position.py` — **unchanged** (§5.3, L8). The byte column has
  no consumer yet and no inverse conversion is written; the coexistence of two
  column conventions is recorded in §4's codec comment so the next reader cannot
  miss it.

`Entry` is a `NamedTuple`, so `line_number` cannot literally become a property
on it without changing the class; the mechanical form is to **drop the
`line_number` field**, add `position`, and add a `line_number` **property** to
the class body (a `NamedTuple` subclass may carry ordinary properties, as long
as the name is not also a field). Every existing read of `e.line_number`
continues to work.

## 8. The position backfill

### 8.1 Shape — compose the exported primitives, do not touch `dry_run`

Draft 1 proposed a second Isa-REPL app with its own protocol. Draft 2 over-
corrected and proposed parameterising `dry_run`. **Both are wrong**; reading the
scheduling code settles it:

- `dry_run` must **not** be parameterised. Its own comment states the contract:
  *"One dry_run is ONE metering (the quote must equal the live work,
  CHECK_OUTDATE_PLAN.md §8)"* — including the R2 proof-channel dedup that
  `Test/Test_All.thy` asserts. Threading a second mode through it puts a
  load-bearing contract at risk for no gain.
- `plan_interpretation` is private and hardwires `skip_interpreted`, which is
  the wrong predicate here.
- The genuinely reusable primitives are **already exported** in
  `SEMANTIC_STORE`: `collect_cone`, `schedule_dag`, `enumerate_entries` — and
  `schedule_dag`'s comment says in as many words that `body` is a parameter so a
  different driver can supply a different body.

So the backfill is `schedule_dag` over a cone, with a body that enumerates and
writes — and, under L9, **no skip and no mark**:

```sml
fun backfill_cone (roots : theory list) : backfill_report =
  let
    fun body thy () =
      let val payload = enumerate_entries (Context.Theory thy)
      in backfill_payload payload end
  in
    fold add_backfill (schedule_dag "Semantic_Store.backfill_positions" body
                         (collect_cone roots)) no_backfill
  end
```

It is still shaped like `interpret_cone`, minus the skip-and-mark: that half was
`interpret_cone`'s answer to "this costs money, never pay twice", and it does not
transfer to a pass whose repeat cost is CPU only.

Nothing in `dry_run`, `plan_interpretation`, `interpret_cone` or
`interpret_with_parallel` is modified.

A **non-persistent theory is still skipped** — but that is a precondition, not
bookkeeping: a WIP theory's records are a disposable cache (`clean_wip` deletes
them), so backfilling them is meaningless. It is decided from the theory value
in hand, `Theory_Hash.is_persistent (Theory_Hash.hash_of thy)`, with no store
access at all.

### 8.2 The Isa-REPL app — extract the framing, register a second name

`cmd_collect` writes exactly two values to the socket (`targets`, `reinterpret`),
so adding a third read to `Semantic_Store.collect`'s protocol would break it.
Register a **second app**, `Semantic_Store.backfill_positions`, whose protocol is
one value (`theory_names`).

M6's real objection was copy-pasting the framing, not having two registrations.
So **extract** from `Tools/semantic_interpretation_app.ML` the parts both apps
need — the `send` / `done` pair under a `Synchronized.var`, the
`Private_Output` channel hijack and its restore, and the `ERROR: ` framing — into
one local helper, and register both apps over it. That is reuse by extraction,
which is what the project rule asks for.

### 8.3 The write path, and the approved vector exception (L6)

Python-side, per theory, in **one** `env.begin(write=True)`: for each `uk` that
has a record, re-encode it with `position` set and every other field
byte-identical, via a raw `txn.put`. That is the whole write.

Under L9 there is no second step. **No theory-status record is written or
created** — which also means the backfill leaves no trace in the published
payload beyond the positions themselves.

It is not "reads nothing": §8.5's surviving stop condition reads one theory's
`finished` flag, per theory, outside this transaction. Reading is fine; the
point of L9 is that the backfill maintains no state of its own.

Explicitly untouched: `interpretation`, `semantic_digest`, `deps`, `version`,
`interpreted_at`, every theory-status record, the global counter, and every
vector store.

The one transaction per theory is still the right granularity: it makes a
theory's positions land together or not at all, and it bounds the dirty-page
footprint of a 9,621-theory sweep.

**Why this bypasses `Semantic_DB.__setitem__`, and why that is approved.**
`__setitem__` begins with an unconditional `invalidate_vectors([key])`, which
writes a tombstone for the key in every vector store. Routing 1,353,574 record
writes through it would tombstone every vector: 110,329 on this machine's
`vector_Qwen__Qwen3-Embedding-8B.lmdb`, and the ~280 k accumulated so far on
`cslh19`. Nothing incremental refills them — `contains` reads a tombstone as
absent, while `embed_all_entities_in_theories` skips any theory already marked
embedded — so recovery would mean re-running the whole 8B embedding pass. The
`migrate_*.py` backup pattern copies `semantics.lmdb` only and would not save
them.

The invalidation would also be **gratuitous**: `position` does not feed
`entity_document_text`, which is `pretty_print + "\n" + interpretation`. The
text handed to the embedding model does not change, so no vector goes stale.

`VECTOR_INVALIDATION_PLAN.md` §6 justified unconditional invalidation by
enumerating the setter's production callers — `write_answer` (which by
construction just received a fresh LLM answer) and `put_experience` (which
embeds explicitly). The backfill is a caller of a kind that enumeration did not
contemplate: it writes 1.35 M records and changes no text at all.

**The user approved this exception explicitly, and decided that
`VECTOR_INVALIDATION_PLAN.md` is not to be amended** — the exception is recorded
here and only here (L6). The exception weakens neither of §6's two required
mitigations: the shared invalidation helper is simply not invoked, and the
`fsck` structural check ("every key holding a real user vector has a
layered-visible record") still passes, because the backfill deletes no record
and re-keys nothing.

### 8.4 Resuming, and the completeness scan (L9)

**Resuming is rerunning.** The write is idempotent — re-encoding a record whose
`position` is already the value being written produces the same bytes, and no
vector store is touched either way (L6) — so an interrupted sweep is restarted by
running it again over the same targets. The only cost is re-paying the
enumeration.

Nothing records progress. The earlier design put a `b"positions_done"` flag on
each theory-status record; L9 removed it, and §17.2 records why that mattered
rather than being merely tidier.

**The completeness scan answers the question the flag was pretending to answer,
and answers it better.** A flag says "I believe I finished"; the scan says what
is actually in the store. One cursor pass, **3.2 s measured** on the 1.7 GB
store (msgpack-decoding all 1,362,343 entity values), reporting:

- entity records by codec length;
- among 13-field records, how many carry a position and how many carry `None`.

Read it as: **records shorter than 13 fields have never been through a
13-field writer** (`_encode` always packs 13), i.e. the backfill has not reached
them.

**Scope the denominator first — two whole populations are unreachable by
construction, and both are decidable from the key alone, without decoding:**

| excluded | test | measured |
|---|---|---|
| WIP-prefixed records | `key[0]` LSB set — the WIP bit lives in byte 0 of the theory hash, and `backfill_theory` skips every non-persistent theory | 21,024 short |
| EXPERIENCE records | `key[16] == 8` — `enumerate_entries` never produces this kind; `put_experience` writes them | 87 short (persistent) |

**The criterion is a delta, not an absolute residue.** Compare the scan before
and after against the run's own report:

> the reachable short-record count must drop by **at most** the number of records
> the run reported writing, and by an amount consistent with it.

"At most", not "exactly": one universal key can be enumerated by two unrelated
theories (a theorem-alike key is content-addressed, so an identical proposition
over identical constituents collides), and the per-theory `hit` counters then
count it twice while the store holds one record.

**Do not predict the absolute residue.** An earlier draft did — "the DB covers
9,729 theories, `AFP-ALL-4` holds 9,621, so roughly a hundred theories' worth
should remain" — and it was wrong by more than a factor of two before the
disputed term was even counted. The store holds records from many theories no
`AFP-ALL-4` sweep can load (ZF, FOL, HOL-IMP, Why3STD, HOLCF, phi-system,
Minilang, …), and their number is **not cheaply computable**: two reviewers
armed with the store disagreed by 12,000 records on it. An absolute threshold
here manufactures false alarms on good runs and hides real losses in the noise.

**The scan cannot certify completeness, and is not asked to** (accepted by the
user, 2026-08-11). It certifies that a run wrote what it said it wrote.
Attribution of the remaining short records to theories comes from the **run
log** — `backfill_theory` already `writeln`s one line per theory, and §8.8 has
the driving script keep it — not from the store, which by trap 2 below cannot
say which theory a record belongs to.

**What the scan cannot do, and why it is not asked to.** It cannot drive a
per-theory skip, for two independent reasons, both measured on the live store:

1. **Length is not a "done" signal.** The store today holds records of length
   6 (114,982), 7 (880), 8 (128,507), 12 (1,109,130) and 13 (8,844)
   simultaneously — the tail-append codec leaves one stratum per growth — and any
   unrelated decode-modify-encode path silently lifts a record to 13 fields.
   Nor is `position = None` a "not done" signal: it is the permanent, correct
   value for every §10 case (538 of the 8,844 already carry it).
2. **A record cannot name the theory to re-enumerate.** For theorem-alike keys
   the 16-byte prefix is the **XOR of constituent theory hashes** — the theories
   the constants come from, not the theory that states the fact — so there is no
   way back from a record to the theory whose `enumerate_entries` would produce
   it. This is the same property that makes "theory done, 0 entities" a normal
   outcome elsewhere in this system.

So the scan is a completeness check over the whole store, not a work planner.
That is exactly the division of labour L9 wants: the sweep does the work
unconditionally, and the data is asked afterwards whether the work landed.

### 8.5 Reporting, and the stop conditions

Per theory and in a final total:

| Counter | Meaning |
|---|---|
| enumerated | entities `enumerate_entries` produced |
| hit | of those, entities whose `uk` has a record |
| missing | entities with no record (legitimate: never interpreted) |
| no position | entities with no position at all (§10) |
| unreadable | positions dropped because the file could not be read (§5.2) |
| **line mismatch** | positions where the derived line ≠ `Position.line_of` (§5.2) |
| **tie-break degraded** | theories whose `check_theorem_name_in_file` returned all `(0,-1)` (§8.6) |

Two of these are **stop conditions on a theory, not statistics** — they mean
"do not write this theory":

- **line mismatch > 0** — under L7 impossible unless this module is buggy (§5.2).
- **tie-break degraded > 0** — the theory's positions are wrong even though its
  hit rate is perfect (§8.6).

The hit rate is a third check but a softer one: an enumerated entity legitimately
has no record when it was never interpreted. The sharp form is **for a theory
whose status record says `finished`, essentially every enumerated entity should
hit**; a shortfall there means something is wrong and the sweep stops.

Draft 1 made the hit rate the headline on the theory that AFP drift would show up
there. Under L7 drift is excluded by premise, so the hit rate's job is now to
catch a *different* class of problem (a bug here, or a different Isabelle), which
is exactly when a number is worth reporting.

**Under L9 the hit rate is a report, not a data-integrity guard.** In the flag
design a total miss was destructive — the theory was marked done with nothing
written, and no rerun ever revisited it (§17.1). With no flag, a total miss costs
only the wasted pass: rerunning fixes it. So the sharp form stays as a **stop
condition on the run** (a shortfall means the recomputed keys are not the
collected keys, and continuing wastes hours), and no longer needs to be enforced
inside the write transaction.

**Its threshold is deliberately not fixed here.** "Essentially every" names no
number, and nobody has the distribution: how many of a normal theory's enumerated
entities lack a record is exactly what §8.7's canary measures. The canary
therefore reports a per-theory hit-rate histogram, and the floor is chosen from
it before the full sweep. Until then the sweep stops only on `hit = 0` for a
theory whose status says `finished` — the one case that needs no number.

Note the asymmetry a zero-threshold leaves open, so that the canary is read with
it in mind: a divergence confined to **theorem** keys (a changed `Term_Digest`)
leaves the name-addressed kinds — constants, types, classes, locales — hitting
normally, so the rate lands at 20–30 %, not 0. That is precisely the case a
measured floor has to catch.

The window is narrower still, which is why a measured floor matters rather than
being a nicety. `Theory_Hash.hash_of` is an xxhash128 of the theory's **own source
file plus its parents' hashes** — the session image is not an input — and
`key_of_ns_entity` builds a constant/type/class/locale key from that hash and the
name. So running the sweep under a different image does not move the
name-addressed keys at all, and `hit = 0` requires a divergence severe enough to
move every kind at once. (Measured on the live store: 11,468 theory-status
records, 10,601 carrying `finished`, so the guard's first conjunct is satisfied
for essentially the whole sweep.)

### 8.6 The failure the hit rate cannot see

`enumerate_entries` calls `check_theorem_name_in_file` to learn where each fact
name occurs in the source, and those offsets drive the dedup dominance test that
picks **which occurrence's position wins**. On RPC failure the ML side emits a
`warning` and substitutes `(0, ~1)` for every name; the dominance test then
reduces to `0 < 0` = false, i.e. keep-first in `Facts.dest_static` order rather
than source order.

Universal keys are content-addressed and unaffected, so **every record still
matches and the hit rate is perfect while the positions are systematically the
wrong occurrence**. This is a transient-RPC-failure hazard, entirely independent
of L7.

Therefore, in the backfill, a `check_theorem_name_in_file` failure is **fatal for
that theory**: write no positions, count it, and abort the sweep on a nonzero
count.

L9 softens the consequence without removing the need for the check. In the flag
design the wrong positions were permanent — the theory was marked done and never
revisited. With no flag, a rerun fixes them. But wrong positions committed to
1.35 M records are still wrong until someone notices, and this failure is
invisible in the hit rate by construction, so refusing remains the right call.

The degradation happens inside `enumerate_entries`, which the live path wants to
keep degrading (there it costs only a tie-break). So the backfill needs it
*visible*, and the concrete mechanism is fixed here so no one has to re-decide:
**`enumerate_entries`' result record gains a fifth field
`tie_break_degraded : bool`**, set when the RPC handler falls into its
`Remote_Calling_Failure` branch. A `Unsynchronized.ref` would not do — the
bodies run as parallel `Future`s under `schedule_dag`, so a shared ref is racy.
§15.6 lists the four call sites that must be updated for the new field.

### 8.7 Canary before the sweep

Run the backfill over `HOL` plus one AFP session first and read off: the seven
counters, wall clock per theory **broken down into enumeration vs key
computation** (§11.2), peak ML heap **per 1,000 theorems swept** (§11.3), and a
hand check of a dozen positions against the actual files. The canary must run
**under `AFP-ALL-4`**, not a small image: the dominant cost scales with the
image's name-space size, and a small image understates it (§11.2).

L9 adds two things the canary must now produce, because two later decisions hang
on them:

- **The per-theory hit-rate histogram**, from which §8.5's floor is chosen.
- **The enumeration wall clock**, which is what a resume costs when there is no
  skip. If it is tens of minutes for the full AFP, L9 stands as written; if it is
  hours, L9's fallback (a done-list file local to the driving script) is taken.

Then run the **completeness scan** (§8.4) before and after, and check the drop in
reachable short records against the run's report — **at most** the number of
records written, per §8.4.

### 8.8 The driving script

`migrate_entity_positions.py`, following the `migrate_*.py` house pattern:
timestamped `Environment.copy` backup of `semantics.lmdb` before any write,
idempotent, counts at the end. It drives the REPL the way `cmd_collect` does —
start (or reuse) the RPC host, open `IsaREPL.Client`, `set_register_thy(False)`,
`load_theory([...targets..., "Semantic_Embedding.Semantic_Collection_App"])`,
`run_app("Semantic_Store.backfill_positions")`, write the target list, then read
streamed messages until the terminating unit.

It also runs the **completeness scan** (§8.4) before and after the sweep and
prints both, so the run reports what actually landed rather than what it believes
it did. The scan is 3.2 s on a 1.7 GB store; there is no reason to make it
optional.

**The scan must go through `Semantic_DB.iter_items`, not `lmdb.open`.** By the
time the post-sweep scan runs, the RPC handlers have opened the store's singleton
environment *in this same process*, and py-lmdb refuses a second open of a path
it already holds — measured, and flag-independent. The one legitimate `lmdb.open`
in this script is `_backup()`, which works only because it runs (and closes)
before the RPC host starts. Follow the house idiom (`Semantic_DB.iter_items`,
which the fsck scan uses) and the trap disappears.

**Keep the run log.** `backfill_theory` already emits one line per theory
through the channel hijack, and `stream_app_messages` prints it. Tee it to a
timestamped file beside the backup: after the sweep it is the *only* way to
attribute leftover short records to theories, because the store cannot say which
theory a record belongs to (§8.4 trap 2).

One backup at the start is the right granularity: every write is additive, and
under L9 a rerun is the recovery path for anything short of corruption. Note the
backup covers `semantics.lmdb` only — which is sufficient **because** of L6: no
vector store is written.

## 9. Environment

Established by inspection on 2026-08-09. Draft 1 got two of these wrong.

- The DB covers **9,729 distinct theories**; `AFP-ALL-4` contains **9,621**
  (`tools/Build_AFP_Image/afp_all4_theories.txt`). The stored data was collected
  from this image.
- **This machine cannot run the backfill.** Its built heaps are `Pure`, `HOL`,
  `HOL-Analysis`, `HOL-Library`, `Automatic_Refinement`, `Auto_Sledgehammer`,
  `MathBench_Prover`, `Minilang`, `Minilang_AoA`, `Performant_Isabelle_ML`,
  `Phi_BI`, `Phi_Semantics_Framework`, `Probe` — no AFP-wide image. Route A must
  load each theory, and loading needs a heap.
- **`cslh19` can**: its distribution heap directory
  (`~/Current/MLML/contrib/Isabelle2025-2/heaps/polyml-5.9.2_x86_64-linux/`)
  holds `AFP-ALL-0..4` and the `AFP-DEP1-*` chain, and its `semantics.lmdb` is
  the same 1.7 GB store.
- **CORRECTION to draft 1: nothing is "rebuilding AFP-ALL-4".** `repl_server.sh`
  writes a temporary one-theory session `REPL<pid>` whose parent is the given
  base session and runs `isabelle build -D <tmp> REPL<pid>` on *that*, reusing
  the already-built `AFP-ALL-4` heap. The backfill needs no image rebuilt — it
  needs a live REPL server on `AFP-ALL-4`, which per L5 we start ourselves after
  killing window 1's.
- **CORRECTION to draft 1: the embedding pass does not write `semantics.lmdb`.**
  Theory embed status lives in the *vector* store, not the record store.
  Measured: `vector_Qwen__Qwen3-Embedding-8B.lmdb` holds 723 16-byte records
  (embed status) while `semantics.lmdb`'s 11,415 16-byte records are
  *interpretation* status. The embedding pass reads `semantics.lmdb` and writes
  `vector_<model>.lmdb`. There is therefore **no `semantics.lmdb` write-lock
  contention** between it and the backfill — draft 1's §11.4 was wrong.
- The two machines' heaps are built for different Poly/ML platforms
  (`x86_64_32` here, `x86_64` there); heaps are not transferable.

## 10. Entities with no position — degradation rules

A position is stored only when it is real. In each case the field is `None`;
nothing is guessed.

1. **Dynamic collection members.** They are given the literal position
   `("", 0, 0)` and have no declaration site of their own.
2. **Generated facts.** A `datatype`, a `fun`, or a locale interpretation gives
   its generated facts the position of the *generating command*. That is
   Isabelle's own semantics, recorded as-is. (Measured: `List.list.induct` sits
   at `~~/src/HOL/List.thy:11`, near the head of the file, not at any `lemma`.)
   Any prose describing this field must say so rather than imply the position
   points at a `lemma` keyword.
3. **Locale-instance facts** may carry a position in a theory other than the one
   whose hash the record's key is built from. Recorded as-is.
4. **Paths outside `$AFP` and `~~`** are stored absolute per L1' — not dropped.
   Draft 1 called this "files under no known root", which was wrong: `~` *is* a
   registered root, so a user project under `$HOME` would fold; L1' is what stops
   that fold, not the absence of a root.
5. **The position's file is not readable** — Pure bootstrap positions such as
   `Isar/method.ML`, or a file deleted since the heap was built (§5.2).

## 11. Risks and concerns

### 11.1 A position goes stale without any signal

A theorem's universal key is content-addressed (its `thm128` digest plus the XOR
of its constituent theory hashes). Move a lemma ten lines down without changing
it, and the key, the digest and every incremental-invalidation field are
unchanged while the stored `line` is now wrong. `CHECK_OUTDATE`'s machinery
cannot catch this, by construction.

**L7 does not rescue this.** L7 is about `cslh19` now; §11.1 is about the
*published* store on *consumers'* machines, whose AFP is a different snapshot,
and about the future, in which the AFP evolves.

So the entity position is **advisory**: a good place to start looking, not a
sound machine-checked reference. Concretely, a consumer may use it to open a file
near the declaration and search for the name; it must not assume the file exists,
is readable, or holds that entity at that position, and must not use it as an
identity or cache key. Under L8 there is no public consumer yet, so this contract
lives in §4's codec comment and here; it must be written into user-facing prose
before any public accessor is added.

### 11.2 The dominant cost is enumeration, not digests

Draft 1 claimed recomputing `thm128` over 1.04 M theorems was the dominant cost.
Measured (`isabelle console -l HOL-Analysis`, 272 theories, 57,274 fact names):
traversing every proposition in the fact base (56,024 thms, 1,172,080 nodes)
takes **0.024 s**, and `thm128` is two FNV passes on top of that, with
`thm128_cache` and `constituents_cache` removing repeats — seconds of CPU over
the full sweep. Replaying `get_theorem_collections_with_positions` (a
`Symtab.make_set` over every parent's *full* fact space, then `Name_Space.get_names`
over the whole space) for those 272 theories takes **5.478 s** — 230× more.

That term scales as (#theories swept × name-space size of the image), which
extrapolates to roughly **2 hours** at 9,621 theories and an AFP-wide fact space,
versus minutes for the digests.

This changes the decision rule. Chunking cannot reduce digest work at all (it is
linear in entities, each digested once either way); it reduces the name-space
term, because a smaller image has a smaller fact space. Draft 1 would have
measured the wrong number and drawn the wrong conclusion.

### 11.3 Memory: the real ceiling and the real chunking axis

Draft 1 cited window 1's `java.lang.OutOfMemoryError` as evidence of a memory
ceiling. That is the **JVM** heap (`isabelle build`'s Scala side, governed by
`-Xmx`), a different heap from the Poly/ML one a sweep allocates in.

The real ML-side risk is three process-lifetime tables that grow unboundedly and
are never cleared: `Universal_Key`'s `constituents_cache` and
`constituents_registry` (one entry per distinct theorem — 1.04 M) and
`Term_Digest`'s `thm128_cache`. None is bounded by the theory being swept.

Draft 1's chunking fallback also does not work: `AFP-ALL-0..4` is a linear chain
(`AFP-ALL-0 = AFP-DEP1-21 + …`) whose five layers add only 456/536/551/626/457
theories, so the smallest `AFP-ALL` image already holds ~8,900 of 9,621 — chunking
across them saves ~7 %. **The real axis is the 27-image chain
`AFP-DEP1-0..21` + `AFP-ALL-0..4`**, sweeping each layer's own theories under the
smallest image containing them; §9 confirms those heaps exist on `cslh19`.

Consequently §8.7's memory criterion must be an **extrapolation** — peak ML heap
per 1,000 theorems swept — not a peak on one session, which touches ~1 % of the
theorems and will look comfortable regardless.

### 11.4 Concurrency on `cslh19`

Per §9 the embedding pass writes only the vector store, so there is no
`semantics.lmdb` write-lock contention with the backfill. What remains is disk
and CPU contention, and the fact that the embedding pass takes its record
snapshot once at start — so it will not observe backfilled positions, which is
harmless precisely because `position` does not feed `document_text_of`.

Per L5 we do not share window 1's REPL; we kill and restart it. Window 2's
embedding job is left alone.

### 11.5 Old builds truncate the new field

Anything built against the 12-field codec that reads a record and writes it back
drops `position`. The same hazard the 8 → 12 growth carries; mitigated by the
codec comment and by not running mixed builds against one store.

## 12. Tests

**Isabelle/ML tests** live in `Test/` as `.thy` files and are built by the
`Semantic_Embedding_Test` session, which is deliberately **kept out of the
top-level `ROOT`** (see `Test/ROOT`'s own comment) and run with an explicit
`-d`:

```
isabelle build -d . -d Test Semantic_Embedding_Test
```

`Test/Entity_Position_Test.thy` already exists and is tracked (commit `34da628`)
but is **not listed in `Test/ROOT`**, so nothing builds it today. Extend it and
**add it to the session's `theories` list**.

**Python tests** are top-level `test_*.py` files run with `pytest`.

- **T1** — `Entity_Position` on a heap-resident entity: assert the **exact
  expected string**, e.g. `HOL.refl → ("~~/src/HOL/HOL.thy", 220, _)`. Draft 1's
  "file is non-empty and symbolic" proves nothing, because Isabelle supplies the
  symbolic form regardless of what this module does.
- **T1'** — the same entity collected through the live PIDE path yields a
  **byte-identical** `file` string.
- **T2** — an entity declared in the theory being processed (the interactive
  path), exercising `absolutize_id_based_pos`.
- **T3** — a theory file containing literal non-ASCII bytes: the byte column
  differs from the symbol column and matches an independent byte count. Not
  exotic: 1,501 of 10,297 AFP and 665 of 2,266 Isabelle `.thy` files qualify.
- **T4** — a CRLF theory file: line numbers and byte columns unaffected.
- **T5** — the line assertion (§5.2) holds for every entity of a test theory,
  and a deliberately corrupted index makes it fire.
- **T6** — an unreadable position file degrades that file's positions to `None`
  and does not abort the theory (§5.2).
- **T7** — codec round-trip: a 12-field record reads with `position = None`; a
  13-field record round-trips; `_replace` on a legacy record preserves the other
  twelve fields.
- **T8** — L6: after backfilling a key's position, `contains([key])` is still
  `True` and the vector store is **byte-identical**. Under L9, also: **no
  theory-status record is created or modified** by the backfill.
- **T9** — a theory with two occurrences of one proposition gets the
  source-earliest position; with `check_theorem_name_in_file` stubbed to fail,
  the backfill **refuses** the theory rather than degrading (§8.6).
- **T10** — end-to-end: collect one small theory, assert the stored positions
  point at the right commands; run the backfill over the same theory and assert
  it is a no-op.
- **T11** — the backfill on a `uk` with no record counts it and creates nothing.
- **T12** (L9) — running the backfill over the same theory twice leaves the store
  byte-identical, since "resume" *is* "rerun" (§8.4). Already covered by
  `test_backfill_is_idempotent`; L9 promotes it from a nicety to the mechanism
  the whole resume story rests on.
- **T13** (L9) — the completeness scan reports a store with mixed codec lengths
  correctly, and a 13-field record with `position = None` is counted as reached,
  not as outstanding (§8.4's two traps).

## 13. Open questions

None. Every question drafts 1 and 2 raised is settled in §2.

## 14. Raised by the review and rejected

Recorded so they are not re-raised.

- **"A conflicting entity-position triple (`def_pos`) already exists and is
  shipped over RPC."** `Context_Callbacks.entry_def_pos` builds its third
  component from `Position.offset_of`, not a column; the claimed silent mix-up
  cannot occur.
- **"`positions_done` violates the copy-up rule and survives a hash change."**
  The mechanics cited are accurate but did not add up to the claimed consequence.
  **Moot since L9**: there is no `positions_done`. Recorded because the reviewer
  was circling the right smell — a bookkeeping flag that can disagree with the
  data — even though the specific mechanism argued was not the one that bit.
- **"§8.1 ignores layer residency: mass copy-up neuters the approved purge."**
  Citations accurate, but the consequence cannot occur on any machine this plan
  runs on — `validated_system_db()` returns `None` here and on the publisher, so
  there is no read-only layer to copy up from.
- **"§5.3 writes a second symbol walker, which the reuse rule forbids."**
  Rejected in that direction: `File.read` and `Symbol.explode` are Pure's own,
  while `position.py`'s `symbol_explode` is the hand port and already diverges
  from Pure. What survived is in §5.3 — two of draft 1's three reasons were
  false, and the existing RPC bridge had to be acknowledged.
- **"The stored byte column has no consumer, so add the inverse conversion."**
  Deferred by L8, not rejected: no public accessor is being added, so no inverse
  conversion is written. The coexistence of two column conventions is recorded in
  §4's codec comment.

## 15. Implementation handover

Order matters: each step is independently testable and leaves the tree working.

### 15.1 Step 1 — `Tools/entity_position.ML` (pure ML, touches no store)

New file; add its `ML_file` line to `Semantic_Embedding.thy` between
`pide_state.ML` and `theory_structure.ML`. Signature in §5.1, behaviour in
§5.1–5.2. Extend `Test/Entity_Position_Test.thy` with T1, T1', T2, T3, T4, T5,
T6 and **add it to `Test/ROOT`**'s theory list.

Run: `isabelle build -d . -d Test Semantic_Embedding_Test`.

Reminder from `CLAUDE.md`: after editing a `.ML`, **restart the REPL** — a fresh
REPL loads `.ML` from source. Do not rebuild the heap and do not add `-c`.

### 15.2 Step 2 — the codec (Python only)

`semantics.py`: `Record` gains `position` (§4); `_decode` goes 12 → 13;
`_encode` appends. Add T7 as a Python test. Nothing else reads the field yet, so
this step is safe to land alone: old records decode to `position = None`.

### 15.3 Step 3 — the wire and the live path

`semantic_store.ML`: `build_entries` produces the position (§5.4);
`make_interpret_file_cmd` and `interpret_file_dry_run_cmd` change field 4 (§6).
`semantic_interpretation.py`: `_entries_of_wire` binds `position`; `Entry` drops
`line_number` as a field, gains `position`, and gains a `line_number` property
(§7); `write_answer` passes `position=entry.position`.

**Land ML and Python in the same commit** — the wire format is not
backward-compatible.

Verify with T10's first half: collect one small theory and check the stored
positions point at the right commands.

### 15.4 Step 4 — the backfill

Superseded in part by L9 — §17.3 is the current work list. As originally written:

- `semantic_store.ML`: the `Semantic_Store.backfill_positions` RPC command and
  `backfill_cone` (§8.1). Make `enumerate_entries`' `check_theorem_name_in_file`
  degradation visible to its caller (§8.6). ~~`positions_done` /
  `mark_positions_done`~~ — dropped by L9.
- `semantic_interpretation_app.ML`: extract the framing, register the second app
  (§8.2).
- Python: the `Semantic_Store.backfill_positions` handler with the raw-`txn.put`
  write path (§8.3) and the seven counters (§8.5). ~~the inline status update~~ —
  dropped by L9.
- `migrate_entity_positions.py` (§8.8), including the completeness scan (§8.4).
- Tests T8, T9, T10 (second half), T11, T12, T13.

### 15.5 Step 5 — the canary, then the sweep, on `cslh19`

Per L5, the backfill gets its own REPL server; window 2's embedding job is not
touched.

Kill window 1's REPL and start one **without** the interpretation driver (no LLM
is involved). For reference, the command the user runs there is:

```
RPC_Host=127.0.0.1:27182 INTERPRETATION_DRIVER="Codex.gpt-5.6-sol" nice -n 20 \
  ./contrib/Isa-REPL/repl_server.sh 0.0.0.0:6666 AFP-ALL-4 /tmp/repl_outputs \
  -o threads=12 -o document=false
```

The backfill's form drops `INTERPRETATION_DRIVER`. **The user approved the
kill-and-restart of window 1's REPL on 2026-08-11**, on top of L5. Window 2's
embedding job is still not to be touched, and the approval covers this step, not
future ones.

Then §8.7's canary, read the seven counters and the two stop conditions, and only
then the full sweep.

### 15.6 Code-level anchors

Everything below was read off the tree on 2026-08-09. Functions, not line
numbers — but these are the exact names an implementer needs and would otherwise
have to rediscover.

**(a) The packer to change (`Tools/semantic_store.ML`, local `pack_arg`).**
One `pack_arg` serves both `interpret_file` and `interpret_file_dry_run`:

```sml
val pack_arg =
  packTuple5
    (... , packList (packTuple10
       (pack_entry_kind, packString, packString, packInt, packBytes, packString,
        packOption (packTuple3 (packOption packBytes, packOption packBytes, packString)),
        packList <constituent>, packOption packBytes, packList packBytes)))
                                ^^^^^^^^^ the 4th packer, `packInt`, is the line
```

Field 4's `packInt` becomes `packOption (packTuple3 (packString, packInt, packInt))`.
The two command records that name the entry type in full
(`make_interpret_file_cmd`, `interpret_file_dry_run_cmd`) change to match, as
does the `fn {file_path, theory_longname, theory_key, driver, entries} => ...`
adapter just above `pack_arg`.

**(b) The four sites that destructure `enumerate_entries`' result** — all must
gain the new `tie_break_degraded` field (§8.6). Names, in file order:

1. the record `enumerate_entries` itself builds and returns;
2. `send_for_interpretation`'s parameter pattern
   `{file_path, theory_longname, theory_key, entries}`;
3. `dry_run_payload`'s parameter pattern, identically shaped;
4. `dry_run`'s proof channel, which does
   `val {file_path, theory_longname, theory_key, entries} = enumerate_entries ctxt`.

Sites 2–4 do not use the flag; bind it and ignore it
(`{..., tie_break_degraded = _}`). Do not reach for a flexible record pattern —
these functions carry explicit type annotations and naming the field is clearer.

**(c) ~~The `positions_done` RPC skeleton~~ — dropped by L9.** There is one
backfill RPC, not two, and it **writes** no theory-status record. §8.5's stop
condition still reads one `finished` flag per theory, on the ML side, outside
the write transaction. The
persistent-only rule survives as a **precondition on the sweep**, decided from
the theory value with no store access: `Theory_Hash.is_persistent
(Theory_Hash.hash_of thy)`, skip if false. A WIP theory's records are a
disposable cache (`clean_wip` deletes them), so there is nothing to backfill.

(For the record, since it cost measurement: under `isabelle build` a session's
own theories are already registered as loaded and so take the persistent branch —
`Test/Test_All.thy`'s WIP-boundary probe. So on the sweep this precondition is
expected never to fire; it is there so that a WIP theory cannot slip through
silently.)

**(d) The new RPC's shapes.** ML → Python argument, and the return:

```
arg: (theory_key : bytes,
      theory_longname : string,
      entries : (uk : bytes, position : (string * int * int) option) list)
ret: (hit : int, missing : int)
```

`theory_key` no longer selects a status record to mark (L9); it stays in the
argument only as the theory's identity for a Python-side error message, next to
`theory_longname`. `ml_report` was dropped as implemented — see §16.2 item 3.

The ML-side counters (`no_file`, `unreadable`, `line_mismatch`) come from
`Entity_Position.of_positions`' `report`; the Python side can only count `hit`
and `missing`. ML merges the two and emits one `writeln` per theory, which the
app's channel hijack streams to the driving script:

```
[Semantic_Embedding] <theory>: enumerated N, hit H, missing M,
                     no-position P, unreadable U, line-mismatch L
```

`backfill_cone`'s body returns those counters so `schedule_dag`'s result list can
be folded into the run total, including the count of theories refused for
`tie_break_degraded`.

**(e) Registration trap — a new handler must be imported by
`Isabelle_Semantic_Embedding/__init__.py`.** The ML side does
`Remote_Procedure_Calling.load ["Isabelle_Semantic_Embedding"]`, which imports
the package; handlers register as an **import side effect** of the
`@isabelle_remote_procedure` decorator. `__init__.py` therefore imports them by
name today — `_interpret_file` from `.semantic_interpretation`, and
`_is_interpreted` / `_mark_interpreted` / `_clean_wip` from `.semantics`. A new
handler that is not added to that import list **will never register**, and ML
will fail at call time with an unknown-procedure error rather than at import.

Put the new handler (`_backfill_positions`; `_positions_done` is dropped by L9)
in `semantics.py`, next to `_is_interpreted` / `_mark_interpreted` — it is a store
operation, and unlike `interpret_file` it involves no wire entries, no agent and
no driver — and add it to `__init__.py`'s import list. **Removing a handler means
removing its import too**, or the package fails at import with an `ImportError`
that names a symbol nobody expects to be missing.

**(f) Reads and writes inside the one write transaction (§8.3).** Do the record
lookups with `txn.get(uk)` **inside** the backfill's own write transaction rather
than through `Semantic_DB._get_raw`, which opens its own read transaction; fall
back to `_system_get(uk)` only if a system layer exists. On both this machine and
`cslh19` `validated_system_db()` returns `None`, so the fallback is inert there —
it is written for correctness elsewhere, not for this run. Skip tombstones
(`is_tombstone`) exactly as the facade does: a tombstoned key has no record and
counts as `missing`.

**(g) The sweep's target list.** `tools/Build_AFP_Image/afp_all4_theories.txt`
(9,621 lines, `Session.Theory` form). `collect_cone` walks and dedups ancestors,
so passing the whole list is correct but means one very large `load_theory` call;
the canary (§8.7) should exercise the batching before the full sweep commits to
it.

**(h) Backup sizing.** `Environment.copy` of a 1.7 GB `semantics.lmdb` needs 1.7 GB
free next to it on `cslh19`; check before starting. Per L6 no vector store is
written, so none needs backing up — which is what makes a 1.7 GB backup, rather
than a 6+ GB one, sufficient.

## 16. Implementation record (2026-08-09)

Steps §15.1–§15.4 are implemented and green. Step §15.5 (the canary and the sweep
on `cslh19`) has not been started; per L5 it needs the user's go-ahead to kill and
restart window 1's REPL.

### 16.1 What landed

| File | What |
|---|---|
| `Tools/entity_position.ML` | **new** — `Entity_Position.of_positions`, §5.1–5.2 |
| `Semantic_Embedding.thy` | loads it between `pide_state.ML` and `theory_structure.ML` |
| `Tools/semantic_store.ML` | `build_entries` produces the position; wire field 4; `tie_break_degraded`; `backfill_positions_cmd`; `backfill_cone`; `positions_done` (landed, and **still in the tree** — L9 removes it, §17.3) |
| `Tools/semantic_interpretation_app.ML` | framing extracted into `register_streaming_app`; second app `Semantic_Store.backfill_positions` |
| `semantics.py` | 13th codec field; `_raw_for_update` / `_status_for_update`; `backfill_positions`; RPC handler; `positions_done` + its handler (landed, **still in the tree** — L9 removes them, §17.3) |
| `semantic_interpretation.py` | `Entry.position`, `line_number` as a property, `write_answer` |
| `isabelle_semantics.py` | `stream_app_messages` extracted out of `cmd_collect` |
| `__init__.py` | imports the two new handlers (the registration trap, §15.6(e)); one goes away with L9 |
| `migrate_entity_positions.py` | **new** — the driving script, §8.8 |
| `Test/Entity_Position_Test.thy`, `Test/ROOT` | T1, T1', T2, T3, T4, T5, T6, T9, and a `build_entries` check; the theory is now in the session |
| `test_entity_position_codec.py` | **new** — T7 and the wire decoder |
| `test_entity_position_backfill.py` | **new** — T8, T11, idempotence, `position = None` |

Verified: `isabelle build -d . -d Test Semantic_Embedding_Test`, the app ML compiled
in a throwaway session, and the Python tests above. A deliberate mutation of T1's
expected column was confirmed to fail the build, so the ML assertions really run.

### 16.2 Deviations from §15, and why

1. **`enumerate_entries`' record gained TWO fields, not one** —
   `tie_break_degraded` (§8.6) *and* `position_report`. §15.6(d) requires the
   `Entity_Position` counters at the backfill, and the result record is the same
   channel; the four call sites of §15.6(b) had to change either way.
2. **There is no `mark_positions_done` RPC.** As implemented: §15.4 asked for two
   RPCs, but §8.3 required the mark to commit in the same transaction as the
   records, so `Semantic_Store.backfill_positions` set the flag and only the query
   was its own RPC. **L9 then removed the flag entirely** — §17.3 has the removal,
   which is *not yet applied to the code*. Kept because it shows the design was
   already straining: the flag could not be a clean separate operation, and that
   was the hint.
3. **`ml_report` is not sent to Python.** §15.6(d) itself says ML merges the
   counters and emits the per-theory line, which leaves Python nothing to do with
   them. `theory_longname` still rides along, so a Python-side failure can name
   the theory it was working on.
4. **The position's file does not go through `pretty_unicode`.** §6 justified it
   with "it is a byte string on the wire", which is false — the RPC host unpacks
   msgpack strings as `str`. A filesystem path is not Isabelle source text, and
   rendering a literal `\<...>` inside one would corrupt it.
5. **`enumerate_entries` is now in `SEMANTIC_STORE`**, marked "exposed for tests" —
   T9 asserts on the deduplicated entry, which only it produces.
6. **Refusals are collected, then raised at the end of `backfill_cone`**, rather
   than aborting on the first one. §8.6 says "count it, and abort the sweep on a
   nonzero count"; a refused theory writes nothing, so the operator sees the full
   extent and a rerun covers exactly those theories.
7. **An offset past EOF counts as a line mismatch.** Under L7 it cannot happen,
   and it is the same class of failure: this module's arithmetic disagreeing with
   Isabelle's.

### 16.3 Measured while implementing

- **The pseudo-UTF8 case cannot arise.** `Symbol.explode` decodes a `\192`+control
  pair to one byte, which would shift a byte column. **Zero** `.thy` files in
  `Isabelle2025-2/src` or `afp-2026-05-13/thys` contain a `\192` byte at all, so
  Pure's own walker is used and its `size` is the disk width everywhere that
  matters. (CRLF shifts only the run-up to a line start, never a column.)
- `HOL.refl` is at `~~/src/HOL/HOL.thy`, line 220, **byte column 3** — T1 asserts
  the exact triple and independently checks that `refl` really starts at byte 3.
- `File.symbolic_path` folds this working tree to `~/Current/MLML/...`, so T2's
  L1' assertion (a path outside `$AFP`/`~~` stays absolute) is not vacuous.
- `enumerate_entries` needs `Remote_Procedure_Calling.load
  ["Isabelle_Semantic_Embedding"]` to have run, or `check_theorem_name_in_file`
  fails and `tie_break_degraded` comes out true. T9 caught this.

### 16.4 Not yet verified

- **T9's refusal half** — §12's T9 has two halves; only the positive one landed
  (the deduplicated occurrence's position is the source-earliest). The second —
  "with `check_theorem_name_in_file` stubbed to fail, the backfill **refuses** the
  theory" — is still untested: forcing that state needs a failing RPC, and a test
  that called `backfill_theory` would drive real RPCs against the developer's live
  store. The refusal branch is three visible lines in `backfill_theory`. What T9
  *does* now discriminate was proved by mutation: forcing `dominated = false`
  (exactly what a degraded tie-break produces) makes the assertion fail, which it
  did not before the duplicate lemmas were renamed so alphabetical order runs
  against source order.
- ~~**T10**~~ — **verified 2026-08-11, unplanned, on real data.** Another process
  in this shared tree restarted a REPL after the `.ML` edits and ran an ordinary
  collection, so the live path wrote **8,844 13-field records, 8,306 of them
  carrying a position**, into `~/.cache/Isabelle_Semantic_Embedding/semantics.lmdb`.
  Three were hand-checked against the raw bytes of
  `contrib/phi-system/Phi_BI/Algebras.thy`:

  | stored | line's bytes | at the byte column |
  |---|---|---|
  | `one_partial_map` 2618:7 | `lemma one_partial_map: ‹1 = Map.empty›` | `one_partial_map` ✓ |
  | `one_option_def` 1388:1 | `definition [simp]: "one_option = None"` | the generating command ✓ (§10 rule 2) |
  | `plus_option(1)` 1373:7 | `lemma plus_option[simp]:` | `plus_option` ✓ (collection member) |

  So the live path is confirmed end to end, including two of §10's degradation
  rules. What remains unverified is the backfill half of T10, which needs the
  canary. **Operational note**: the implementation was in production use while
  still uncommitted.
- **The sweep's cost.** §11.2 measured enumeration, but `build_entries` also
  pretty-prints every proposition and calls `PIDE_State.command_at_position` for
  each type/class/locale/collection/method entity. That is exactly what a live run
  pays, so it is known-feasible, but §8.7's canary should time it before the full
  sweep — a positions-only path through `build_entries` is available if it hurts.

## 17. Round-2 review, and the L9 rework (2026-08-11)

The implementation of §15.1–§15.4 was put through a second two-turn adversarial
debate — five lenses over the diff, each lens's findings handed to a separate
skeptic told to refute them, then an adjudication pass. Eight findings, seven
attacked down, one survived; three of the seven left residues that the refutation
did not touch and that are kept below.

**The byte-column arithmetic came back clean.** The lens aimed at
`entity_position.ML` — the symbol walk, the ascending-offset precondition, CRLF,
multi-byte symbols, the L1' path guard, exception safety — was told to hand-verify
against `Pure/General/symbol_explode.ML` and returned no findings. That was the
only hand-rolled arithmetic in the change.

### 17.1 The finding that survived, and what it really meant

*"`positions_done` is set even when zero records were written, and §8.5's
hit-rate stop is not implemented nor declared as omitted."*

Confirmed: `backfill_theory` refused only on `tie_break_degraded` or
`line_mismatch > 0`, and `Semantic_DB.backfill_positions` executed
`data[b"positions_done"] = True` unconditionally. A run in which every recomputed
key missed would have marked all 9,621 theories done with nothing written, and no
rerun would have revisited them.

The first response drafted was a guard: refuse inside the write transaction when
the theory is `finished` and `hit = 0`. **That was treating a symptom.** The
defect is not "the guard is missing"; it is that a flag and the data can disagree
at all. L9 removes the flag, and with it every member of this class. §8.5's
hit-rate check stays, but as a stop condition on the *run*, which is all it ever
needed to be.

### 17.2 What L9 costs and what it buys, measured

Measured on the live 1.7 GB store, 2026-08-11:

| | |
|---|---|
| entity records | 1,362,343 |
| theory-status records | 11,468 |
| full cursor pass, msgpack-decoding every value | **3.2 s** |
| records by codec length | 6: 114,982 · 7: 880 · 8: 128,507 · 12: 1,109,130 · 13: 8,844 |
| of the 13-field ones | 8,306 with a position, 538 with `None` |
| status records carrying `positions_done` | **0** |

Three things follow.

1. **The scan is free.** An earlier objection that a global scan would be a
   burden was simply wrong, and is withdrawn.
2. **Codec length cannot serve as a per-record "done" marker** — five strata
   coexist, any decode-modify-encode path lifts a record to 13 fields, and
   `position = None` is a permanent correct value (§8.4 states both traps).
3. **L9 is free retroactively.** No `positions_done` key exists anywhere on
   disk, because the flag is only written by the backfill and the backfill has
   never run. Nothing needs cleaning; the question of whether the key should ship
   in the published payload never arises.

### 17.3 The work list

**All applied, 2026-08-11**, and verified with
`isabelle build -d . -d Test Semantic_Embedding_Test` plus the Python suite (105
tests). Kept as the record of what the rework consisted of.

**From L9** — remove the flag:

- `Tools/semantic_store.ML`: delete `positions_done'` / `positions_done` and the
  skip branch in `backfill_theory`; keep the persistent-only precondition
  (§15.6(c)).
- `semantics.py`: delete `Semantic_DB.positions_done` and `_positions_done`;
  delete the status read-modify-write from `backfill_positions`. Keep
  `_raw_for_update` and `_status_for_update` — `mark_interpreted` now depends on
  them.
- `__init__.py`: drop `_positions_done` from the import list.
- `migrate_entity_positions.py`: add the completeness scan before and after **via
  `Semantic_DB.iter_items`, never `lmdb.open`** (§8.8); tee the per-theory run log
  to a timestamped file beside the backup; drop the "resumable via the flag" claim
  from the docstring in favour of "rerun".
- `test_entity_position_backfill.py`: drop the `positions_done` assertions, add
  T12/T13.

**From §8.5, and NOT covered by the two groups above** — the hit-rate stop, which
§17.1's surviving finding asked for and which nothing has implemented yet:

- `Tools/semantic_store.ML`: in `backfill_theory`, after the RPC returns, when
  `is_interpreted thy` holds and `entries` is non-empty and `hit = 0`, count it
  (a new `hit_shortfall` field on `backfill_report`) and let `backfill_cone`
  raise on a nonzero total, alongside `refused` and `line_mismatch`.
  `Semantic_Store.is_interpreted` already exists; this is the only new call.
  Under L9 this check does **not** belong inside the write transaction — with no
  flag, a wasted pass costs only time — so it stays on the ML side and the Python
  write path is untouched.
- The threshold stays at exactly zero until §8.7's canary produces the hit-rate
  histogram (§8.5). Do not invent a percentage before then.

**From the round-2 review** — four accepted findings:

- **Rename T9's duplicate lemmas** so alphabetical order is the *reverse* of
  source order (`Facts.dest_static` ends in `sort_by #1`, and
  `Pos_Test_Dup_First` < `Pos_Test_Dup_Second` happens to agree with source
  order, so the assertion cannot currently distinguish the two orders its own
  comment contrasts). Then mutation-check it.
- **Correct §16.1/§16.4**: only the positive half of §12's T9 landed; the
  refusal half is untested. Optionally add a cheap positive test that
  `enumerate_entries` on a `Context.Proof` reports `tie_break_degraded = true`
  (check first that its `file_match_names` is non-empty, or the test is vacuous).
- **`migrate_entity_positions.py::_backup`**: drop `lock=False`. Measured on
  py-lmdb 2.2.1 in this venv, the double-open refusal is flag-independent
  (`readonly+nolock`, `readonly`, and plain read-write are all refused while the
  env is open, and all succeed after `close()`), so the docstring's stated reason
  is false and the flag removes the copy from LMDB's reader table for nothing.
  The three sibling migrations open with locking.
- **Restore the app's read order**: the framing extraction moved
  `Thy_Info.get_theory` / `store_theory_hash` / `Remote_Procedure_Calling.load`
  ahead of the `force` read, so a failure there leaves an unconsumed value in the
  socket. Split `read_roots` into "read the values" and "resolve them", and drain
  the protocol first, as the original did.

**Refuted and not to be re-raised** (recorded with §14): bumping
`snapshot_sync.SCHEMA_VERSION` for the 13th field (the old decoder's `vals[:12]`
reads a 13-field record correctly, and §11.5 already chose the mitigation); the
`line_mismatch` refusal not landing in a theory-level bucket (`refused` is
defined narrowly and the run aborts anyway); "the §8.6 refusal branch is
untested" as a *defect* (it is a coverage argument — the residue is in §16.4);
the three-line `read` helper duplicated across the two app bodies (optional
cleanup: a top-level `fun read cin unpacker` is polymorphic and shareable).


### 17.4 Round-3 review — the draft-4 edit itself (2026-08-11)

The draft-3 → draft-4 edit was put through its own two-turn adversarial debate,
four lenses (new facts · "rerun is resume" · the scan's criterion · internal
consistency). Eleven findings, one survived the rebuttal round; four more were
kept after the maintainer re-checked the refutations and disagreed with them.
All six are applied above. What was raised and rejected, so it is not raised
again:

- **"§8.4's criterion cannot be evaluated in principle, because a record cannot
  name its theory."** Rejected: the criterion is scalar-against-scalar and needs
  no per-theory attribution. The real defect was that the scalar was wrong, which
  is fixed in §8.4.
- **"L9's idempotence claim is false: two theories can write different positions
  to one shared key."** Rejected as stated — L9's sentence is per-theory, and a
  second pass over one theory does emit identical bytes (`enumerate_entries`
  reads only that theory's own facts). The narrow residue is real and is now in
  §8.4/§8.7: `hit` summed over theories can exceed the number of distinct records
  changed, so the scan's delta check is "at most", not "exactly".
- **"§16.2 item 6's 'a rerun covers exactly those theories' is false."**
  Rejected: it describes the rerun's *effect* — only a refused theory's bytes
  change — which T12 states as a required property.

Three lenses independently raised the §8.3-vs-§8.5 contradiction and three
separate skeptics each refuted it as "the sentence is scoped". The sentence did
not say so; §8.3 now does. When independent readers trip on the same sentence,
the sentence is the defect.

## 18. The run on `cslh19` (2026-08-12)

Step 5 executed. The canary and then the full sweep, under `AFP-ALL-4`, on a REPL
restarted without `INTERPRETATION_DRIVER` (no LLM is involved).

### 18.1 Results

| | canary: `Main` | canary: `Gauss_Jordan` | **full sweep** |
|---|---|---|---|
| theories written | 96 | 219 | **9,955** (+22 skipped, all WIP) |
| wall clock | 62 s | 66 s | **~80 min** |
| enumerated | 18,584 | 37,610 | **1,303,856** |
| hit / missing | 18,584 / 0 | 37,603 / 7 | **1,096,883 / 206,973** |
| no-position | 37 | 1,275 | 17,334 |
| unreadable | 0 | 0 | **2** |
| **line mismatch** | **0** | **0** | **0** |
| refused | 0 | 0 | **0** |

Store afterwards, by the completeness scan and an independent pass:

```
1,362,343 entity records | interpretation intact 100 % | with a position 1,062,951 (78.0 %)
malformed positions 0
codec lengths  6:22,455 · 7:878 · 8:13,266 · 12:248,373 · 13:1,077,371
short and reachable 1,295,486 -> 263,861     (excluded: 21,024 WIP, 87 experience)
```

**L6 held, decisively.** `vector_Qwen__Qwen3-Embedding-8B.lmdb` holds 1,363,067
entries with **8,908 tombstones** — essentially the 8,844 records the *live* path
had already rewritten (where invalidation is correct). Had the backfill gone
through `__setitem__` there would be ~1.06 M tombstones.

**L9 held.** 315 canary theories in 128 s is 0.41 s/theory; the full sweep's
9,955 theories took ~80 min including two scans. A rerun — the entire resume
mechanism — costs about that. The fallback done-list file is not needed. ML heap
(poly RSS) was 15.3 GB before the second canary and 15.2 GB after: no growth,
so §11.3's three unbounded caches did not bite at this scale.

**§5.2's line assertion never fired**, over 1.3 M positions. Hand-checking 14
random HOL positions against the raw bytes: 14/14 columns inside their line, 10
landing on the first byte of the fact name, 4 at column 1 of a generating command
(`datatype`, `inductive_set`, `bnf`, `sublocale`) — §10 rule 2, exactly.

### 18.2 §8.5's threshold is settled: a percentage floor is NOT viable

The open question was where to put the hit-rate floor. The sweep answers it.

On `HOL` and `Gauss_Jordan` every theory hit 100 %, which suggested a floor
around 90 %. **The AFP at large looks nothing like that.** Legitimate per-theory
hit rates run all the way down: `CoSMeDis.Outer_Friend_Receiver_State_Indistinguishability`
5/97, `CoCon.Traceback_Properties` 44/303, `JinjaThreads.JVM_Execute2` 262/1,856.
A miss simply means that entity was never interpreted, and coverage across the
AFP is deeply uneven. **A 90 % floor would have aborted the sweep in its first
minutes.** Keep the zero threshold; do not add a percentage.

### 18.3 What the guard found — a pre-existing inconsistency, not a sweep fault

The run ended with `hit_shortfall = 135`: 135 theories whose status record says
`finished` while **not one** of their enumerated entities has a record. The guard
raises at the end of `backfill_cone`, after every theory is written, so the data
landed in full; the exit status is a report.

Concentrated in `HOL-CSP_PTick` (13), `JinjaThreads` (9), `HOL-CSP_RS` (9),
`LocalLexing` (8), `AODV` (6), `Iptables_Semantics` (5). Probed three of them —
`HOL-CSP.CSP_Monotonies`, `HOL-CSP_PTick.CSP_PTick_Laws`,
`Q0_Metatheory.Elementary_Logic` — and the store holds **zero** records naming
them anywhere, yet they are marked finished.

This is a property of the **collection**, not of the backfill: `interpret_cone`
marks a theory finished after `interpret'`, and `interpret'` returns early
without sending anything when its enumeration is empty. Whatever produced that
state, it predates this work. Recorded here as a finding for whoever owns the
collection pipeline; nothing in this plan acts on it.

### 18.4 Corrections this run forced

- **§15.6(g) named the wrong target list.** `tools/Build_AFP_Image/afp_all4_theories.txt`
  (9,621) is *wanted* theories; `afp_all4_roots.heap.txt` (10,614) is what the
  image actually holds. **468 of the wanted are not in the heap** — e.g.
  `AutoCorres2.AutoCorres_Main`, whose sibling theories load fine — and one
  unresolvable name aborts the whole `load_theory`. The correct target is the
  **intersection, 9,153**, which loads in one call with zero drops. A second
  failure shape lives in that difference too: `ISABELLE_CAKEML_HOME` undefined,
  reported with no theory name at all, only a path.
- **A bare TCP connect kills the Isa-REPL server.** Measured: with no probe it
  stays up; a `connect` + immediate `close` takes it down within 40 s. The
  mechanism is `repl_server.sh`'s theory — `Isabelle_Thread.join
  (REPL_Server.startup …); error "IGNORE THIS ERROR"` — so the join returning *is*
  the shutdown. Any port scan or health check will fell it. Check liveness with
  `ss`, never by connecting. (A defect in `contrib/Isa-REPL`, untouched here.)
- **`~~` is ambiguous on `cslh19`.** `isabelle` on the login PATH is
  **Isabelle2024** while the REPL, the image and the data are **Isabelle2025-2**.
  Resolving a stored `~~/src/HOL/...` against the wrong distribution silently
  yields wrong lines — it cost one round of false "position looks wrong" alarms.
  Concrete evidence for §11.1: the position is advisory, and `~~` means only
  "whatever the reader's ISABELLE_HOME is".
- **Seven sibling submodules on `cslh19` were behind** and `Semantic_Embedding`
  could not even load (`Structure (Dialogue) has not been declared`, from
  `Isabelle_RPC`, 5 commits behind). All fast-forwarded on the user's
  instruction. No ROOT file changed; `AutoCorrode` and `phi-system` are detached
  with no upstream and were left alone.

**The `AFP-ALL-4` heap was never touched**: last modified 2026-07-13, and nothing
was written anywhere in the heap directory during this work. `repl_server.sh`
builds a throwaway one-theory child session that *reuses* the image, which is
what §9 established.

### 18.5 Coverage: what has a position, and why the rest cannot

After a second pass over the 660 heap theories the first sweep's target list had
missed (`HOL-MicroJava`, `HOL-ex`, `HOL-Auth`, `HOL-IMP`, `HOL-UNITY`, `HOL-Bali`,
`IOA`, …; 2,137 theories once their cones are included):

| | records | |
|---|---|---|
| **carry a position** | **1,092,855** | **80.2 %** |
| reached, position legitimately `None` (§10) | ~14,000 | done — the answer *is* "no position" |
| WIP-prefixed | 21,024 | not applicable: a disposable cache, `clean_wip` deletes it |
| EXPERIENCE | 87 | not applicable: not an Isabelle entity, it has no declaration site |
| **never reached** | **234,398** | see below |

Every one of the 1,362,343 records still carries its interpretation.

By entity kind — the table that settles what "restored" means:

| kind | has a position | `None` (§10) | not reached | total | covered |
|---|---|---|---|---|---|
| theorem | 817,985 | 8,515 | 221,580 | 1,048,080 | **78.0 %** |
| constant | 176,940 | 0 | 5,144 | 182,084 | 97.2 % |
| locale | 10,038 | 0 | 22 | 10,060 | 99.8 % |
| class | 1,979 | 0 | 4 | 1,983 | 99.8 % |
| collection | 989 | 0 | 5 | 994 | 99.5 % |
| method | 836 | 2 | 6 | 844 | 99.1 % |
| type | 9,480 | 0 | 565 | 10,045 | 94.4 % |
| elim-rule | 21,992 | 90 | 6,932 | 29,014 | 75.8 % |
| induct-rule | 6,760 | 0 | 2,598 | 9,358 | 72.2 % |
| case-split-rule | 7,277 | 0 | 3,227 | 10,504 | 69.3 % |
| intro-rule | 38,579 | 5,372 | 15,246 | 59,197 | 65.2 % |

Theorem-alike overall: 892,593 of 1,156,153 (77.2 %).

**This table is itself the evidence for the diagnosis below.** The name-addressed
kinds — constant 97.2 %, locale and class 99.8 %, collection 99.5 %, method 99.1 %
— are essentially complete, and only the content-addressed kinds fall away. A
theory that had been missed would drag both down together; nothing here does.

**The 234,398 are not a sweeping gap, and no further pass will close them.**
99.7 % are theorem-alike (207,635 theorems + 26,160 rules); only **603** are
name-addressed (594 constants, 5 types, 2 locales, 1 collection, 1 method). If
whole theories had been missed, their constants would be missing too — they are
not. So the theories were swept; those theorems' **keys** were not produced.

A theorem-alike key is content-addressed: `thm128` of the statement, prefixed by
the XOR of its constituent theory hashes. Measured on the store: of 8,329 distinct
constituent theory names, **45 carry more than one hash**, and for **24 of them the
reached and the unreached records use completely disjoint hashes** —
`Abstract-Rewriting.Seq`, `Affine_Arithmetic.Counterclockwise`,
`Affine_Arithmetic.Intersection`, … So the store holds records from **two versions
of those theories**, and because the prefix XORs every constituent, one changed
constituent moves the key of every theorem that depends on it. That cascade is
what 207k unmatched theorem records are.

Those records describe theorems as they stood in an earlier snapshot. The current
sources cannot produce their keys, so nothing can position them; they are stale,
and the sweep's own `missing 206,973` is the same mismatch seen from the other
side. Deciding what to do with a dated stratum belongs to whoever owns the
collection, not here.

**Scope note.** All of this is `cslh19`'s copy of the store. The development
machine's copy is untouched by the backfill (8,844 positioned, from the live path
only) and would need either its own sweep or a snapshot sync.

## 19. Dynamic-collection members: the `coll(i)` name, and the position they never had (2026-08-17/18)

§10 rule 1 says a dynamic collection's members get the literal position `("", 0, 0)`
and have no declaration site of their own. That was recorded as a degradation rule and
never investigated. This section is the investigation, the repair already carried out,
and the design proposed for the rest. **§18.5's coverage tables are superseded** — see
"What the store holds now" below.

### 19.1 Why the members have no position — the mechanism

A `Facts.T` fact is `Static of thm list lazy | Dynamic of Context.generic -> thm list`
(`Pure/facts.ML:142`). `Facts.add_static` (`facts.ML:280-292`) registers one name-space
entry holding the theorem list; `Facts.add_dynamic` (`facts.ML:294-296`) registers one
entry whose value is a **function**. A name-space entry's position comes from
`Binding.pos_of` at `Name_Space.declare` (`General/name_space.ML:582-589`), so a fact has
exactly one position.

Hence: for a static multi-theorem fact every member shares that one position and
therefore HAS one; for a dynamic collection only the collection has an entry, and the
members are not in the fact name space at all. `named_theorems foo` goes through
`Named_Theorems.declare` → `Local_Theory.add_thms_dynamic`
(`Pure/Tools/named_theorems.ML:89-97`) and keeps its members in
`thm Item_Net.T Symtab.table` (`:25-29`), a structure with no positions in it.

Two apparent alternatives are closed. `Facts.dest_static` folds only `Static`
(`facts.ML:221-222,241`), so static enumerators never see these members. And the one
Isabelle table that does pair theorems with positions — `props: (thm * Position.T) Net.net`
(`facts.ML:146`) — is filled only when `index = true` (`facts.ML:288-291`), while
`Global_Theory.add_facts` passes `false` (`global_theory.ML:300`).

So our own code stamps the empty position: `process_dynamic_facts_into_cache`
(`Tools/semantic_store.ML:1022`) builds each member entry with
`name = Member_of_Dynamic coll, pos = ("", 0, 0)` at `:1108`, and
`Entity_Position.of_positions` counts an empty file as `no_file` and leaves the slot
`NONE` (`Tools/entity_position.ML:98-105`).

**Measured, and clean in both directions**: of the 334,284 records whose name has the
form `X(i)`, the 14,122 whose `X` is a collection have NO position (0 exceptions) and the
320,162 whose `X` is not — static multi-theorem bundles — ALL have one (0 exceptions).
The symptom is membership in a dynamic collection, not indexing.

### 19.2 Why `coll(i)` is a misleading name

`bare_name` (`Isabelle_RPC/Tools/context.ML:187-188`) maps `Member_of_Dynamic coll` to
the bare collection name, and its comment (`:69-71`) calls that "the DB-storable name …
(no live index)". But `build_entries` re-attaches the index at the record write —
`disp_name = name ^ "(" ^ i ^ ")"`, labelled A6 (`semantic_store.ML:852-856`) — so the
store holds the indexed form. **That comment is misleading and should be corrected**;
so should `_apply_live_name`'s docstring (`semantics.py:2046-2051`), which says it
overrides "the stored bare name".

A6 exists for a reason: `(entity_kind_int, name)` is asserted unique on the live
interpret path (`semantic_store.ML:1557-1590`; `:603` is only the comment naming it) and the interpretation answer is routed by the
`{kind, name}` label, which "is the ONLY handle the agent has to address an entry" and
must be identical in the prompt, the results key and the routing map
(`semantic_interpretation.py:205-211`). All members of one bin sharing the bare name
would trip the assert and make answer routing ambiguous.

The cost of that choice is that the stored index is **context-relative**: the member list
is whatever the swept theory's cone had contributed, so the same digits denote different
theorems in different sweeps. Measured 2026-08-18: `Topological_Spaces.tendsto_intros(123)` names
TWO different propositions in the store today and named EIGHT before §19.3's repair; `Deriv.derivative_intros(210)` exists while
`Complex_Main`'s bin has 106 members. And the form looks exactly like Isabelle's own
citable fact selection, so a reader takes it for a reference.

Also measured, so that the risk is not overstated: the **agent-facing retrieval path does
not show the stored name**. `Semantic_DB.lookup` replaces it with the live,
context-resolved name for every hit via `_apply_live_name` (`semantics.py:2046-2051`,
also on the reranker path at `:2114`), and the exact-name bundle path replaces it with
`ref_name` (`model.py:2198-2201`). The stored index nevertheless leaks in four places:
the embedded document (`document_text_of` = `pretty_print` + interpretation,
`document_text.py:50`, and `pretty_print` renders the stored name); a claim in
`semantics.py:2110-2111` that the reranker scores the same text that was embedded, which
for these records it may not; the pattern-only query branch (`model.py:2318-2322`), which
keeps `rec` although the live name is in the loop variable; and `_query_entity_core`
(`retrieval.py:911`, heading at `:937`), reachable with any kind through the
`IsaMini.query_by_name` remote procedure (`toplevel.py:64-72`).

### 19.3 What the store holds now, and the repair already done

The population splits by where a real name can be found. All figures measured on
`cslh19`'s promoted store.

**4,524 records: the real name was already in our own data, and they are now repaired.**
A theorem-alike key is `XOR(constituent hashes) ++ tag ++ thm128[:15]`, so records of one
proposition differ only in the tag byte, and a member yields both a Theorem entry and a
rule-kind entry (`semantic_store.ML:1113-1120`). Where the theorem face had been
enumerated statically in another theory's sweep it carries the real name and position
while the rule face kept the member name: 4,519 such (INTRO 4,439, ELIM 80). Five more
had a positioned record on the very same key in the dump, i.e. the join's pick rule
(§B.6 of BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md) chose the member-named candidate; that
rule never knew about static-versus-member and, measured over 2,557 contested keys, chose
the static name 2,547 times and the member name 10 times, five of which the sibling route
already covers.

Run 2026-08-18 by `rename_dynamic_members.py` after a reflink backup
(`semantics.lmdb.pre-rename-20260817-235750` and the vector store's twin, entry counts
verified equal): **4,524 renamed with their positions, 4,524 vectors dropped, 0 problems**,
every edit read back, then re-embedded (4,524 vectors, 744,481 tokens). Renaming is safe
because a theorem-alike key does not contain the name — unlike the name-addressed kinds,
where the name IS the key. The vector must be dropped with the rename because the name is
part of the embedded document and `_auto_embed` only fills ABSENT vectors.

The requested collision statistic: 118 renamed records land on a `(kind, name)` shared
with another record, over 59 distinct pairs — and in **all 59, every colliding record is
the same proposition** (0 pairs mixing propositions). So the rename makes two records of
one theorem agree on a name rather than disagree; for scale, 38,601 `(kind, name)` pairs
were already shared before the pass. Recorded as not-yet-examined: 127 groups whose
several positioned records disagree on the name, where the pick was the deterministic
`(kind, name)` minimum. Report: `~/rename_report.json` on `cslh19`.

**9,597 records over 137 collections: nothing in store or dump names them.** Verified
against the dump too: of the 14,122 keys, 14,112 hold only positionless dump records
(the 10 exceptions are the contested keys above). So the absence is not something the
join lost — it was absent at enumeration.

**Coverage after the repair** — the figures first written here (98.45 %, 20,892 without)
were a PRE-repair snapshot and reported this repair as having changed nothing; the correct
post-repair figures are in §19.4's closing paragraph (98.78 %, 16,368 without). §18.5's 80.2 % and its 234,398 "never reached" are gone: the
universal-key repair re-keyed the corpus and §B.6 took each record's name and position
from a fresh dump, which dissolved the stale stratum §18.5 blamed.

### 19.4 The recovery rate, measured three times, and what the third measurement settled

`Thm.get_name_hint` (`Pure/more_thm.ML:657`, returning a `Thm_Name.T` and defaulting
to `("??.unknown", 0)`) reads the member's ORIGINAL fact name off a `Markup.nameN` tag;
that name's own name-space entry carries the real proof site. Counted as a hit here only
when the name resolves to a real file position.

`Thm.derivation_name` (`thm.ML:1159`) is the wrong instrument, but **not for the reason
first written here**. It is not that `official2` renames unconditionally while the hint
survives — under `official2` (`post = true`) both clauses of `Global_Theory.name_thm`
fire (`global_theory.ML:263-266`), so that argument proves nothing. What actually saves
the hint is ordering inside `apply_facts` (`:318-341`): the attributes — the only route
into a bin — run within `app_facts` on the `official1` copy (`:330-333`), and the
`official2` pass at `:338` applies to that call's result, i.e. to the copy that enters
the fact table rather than the one the `Item_Net` keeps. Under `official1` the hint is
written only when the thm has none already, so a member of `lemmas foo [coll] = a b`
keeps the hint `a`.

**A caveat that the two-state wording must carry.** When a member had no prior hint —
`lemmas foo [coll] = a[of x]`, because `gen_instantiate` resets `tags = []`
(`thm.ML:1947`) — `official1` stamps `foo(1)`. That is a real name resolving to a real
entry, and the proposition at `foo(1)` IS the member's, so nothing is misattributed; but
the position is the `lemmas` command's, not the original `lemma`'s. So a recovered name
is "a name under which this proposition is recorded", which is weaker than "the theorem's
own declaration site".

**First estimate, ~57 %, measured on `Complex_Main`: superseded.** Not because it was
computed wrongly but because its sample cannot represent the population — only 17 of the
137 collections concerned are declared anywhere under HOL, covering at most 16.6 % of the
residue; the other 8,002 records belong to 120 AFP collections.

**Second measurement, per collection, in the theory of the collection's own session where
the bin is largest** (a bin is declared empty and filled downstream: `Record_Intf.icf_rec_unf`
has 0 members in its declaring theory and 1,327 in `Collections.Collections`). Two columns
matter and the first version of this section conflated them: *hint* is the name-hint route
alone, *either* also counts the proposition-matching Termtab described in §19.5.

| collection | residue records | members probed | hint | either |
|---|---|---|---|---|
| `Record_Intf.icf_rec_unf` | 1,354 | 1,327 | 0 | 0 |
| `Nominal2_Base.eqvts_raw` | 898 | 92 | 1 | 1 |
| `HeapLift.update_commute` | 884 | 884 | 0 | 0 |
| `Autoref_Id_Ops.autoref_itype` | 801 | 74 | 0 | 0 |
| `Deriv.derivative_eq_intros` | 674 | 94 | 0 | 0 |
| `Sepref_Translate.sepref_fr_rules` | 533 | 350 | 6 | 13 |
| `Topological_Spaces.tendsto_eq_intros` | 516 | 52 | 0 | 0 |
| `Refine_Mono_Prover.refine_mono` | 425 | 70 | 47 | 51 |
| `Topological_Spaces.continuous_intros` | 392 | 150 | 150 | 150 |
| `Bounded_Linear_Function.bounded_linear_intros` | 324 | 27 | 15 | 15 |
| `Autoref_Fix_Rel.autoref_rules_raw` | 298 | 94 | 86 | 87 |

Weighted by the residue counts: hint 1,148 = 16.17 %, either 1,187 = 16.72 %. **Neither
figure answers the question the section was asking**, because the rate is measured over a
bin's live members while the weight is residue records, and those are different sets:
§19.3's repair had already removed part of the population. Measured per collection, that
skim is `continuous_intros` 855 → 392 records (463 removed) and `bounded_linear_intros`
353 → 324 (29); for the other nine, zero.

**Third measurement, which settles it.** The probe was re-run emitting, per member, the
member's theorem-kind universal key (`Universal_Key.key_of_theorem'`) beside the hint
verdict; since records of one proposition differ only in the kind byte, every kind face is
derived from that key, and only members whose key is a RESIDUE key are counted. Of the
**7,099** residue records in the eleven collections, the probe's members covered **3,049**,
and **0** were named — while the same run produced **305** members with resolving names
(`continuous_intros` 150, `autoref_rules_raw` 86, `refine_mono` 47, `bounded_linear_intros`
15, `sepref_fr_rules` 6, `eqvts_raw` 1; e.g. `Param_HOL.param_takeWhile`). The 305 exist;
none of them is in the residue.

| collection | residue | residue covered by the probe | named |
|---|---|---|---|
| `Record_Intf.icf_rec_unf` | 1,354 | 1,327 | 0 |
| `Nominal2_Base.eqvts_raw` | 898 | 88 | 0 |
| `HeapLift.update_commute` | 884 | 884 | 0 |
| `Autoref_Id_Ops.autoref_itype` | 801 | 74 | 0 |
| `Deriv.derivative_eq_intros` | 674 | 188 | 0 |
| `Sepref_Translate.sepref_fr_rules` | 533 | 334 | 0 |
| `Topological_Spaces.tendsto_eq_intros` | 516 | 104 | 0 |
| `Refine_Mono_Prover.refine_mono` | 425 | 19 | 0 |
| `Bounded_Linear_Function.bounded_linear_intros` | 324 | 24 | 0 |
| `Autoref_Fix_Rel.autoref_rules_raw` | 298 | 7 | 0 |
| `Topological_Spaces.continuous_intros` | 392 | 0 | — |

**Why zero, structurally.** A hint resolves exactly when the theorem is also recorded
somewhere as a named static fact — which is the same condition under which §19.3's sibling
repair found a positioned record of the same proposition and renamed the member face. The
two criteria are one criterion seen from two sides, so the repair did not merely take some
of what the hint could take: **it took all of it.** `continuous_intros` is the clean
extreme — 150 of 150 members named, 0 residue records covered, because the 463 records the
repair removed were precisely its nameable half.

An independent bound reached the same conclusion from the other direction before the probe
ran: since a hint names a PROPOSITION while the residue counts RECORDS, the largest number
of residue records that `hit` propositions could possibly cover is 485 of 7,099 (6.83 %),
computed from the residue's record-per-proposition multiplicities. The measurement puts the
true figure at 0.

**The third measurement, corrected and strengthened by review.** The probe above chose,
per collection, the theory of its own SESSION where the bin is largest — and that missed the
largest bins, which are downstream and cross-session. A census over all 10,602 theories the
`AFP-ALL-4` image holds found `Topological_Spaces.continuous_intros` at 436 members in
`Kraus_Maps.Kraus_Families` against the 150 probed, `Autoref_Fix_Rel.autoref_rules_raw` at
817 against 94, `Refine_Mono_Prover.refine_mono` at 438 against 70. Re-probing 30 further
(collection, theory) pairs at the maximal bins — 14,467 more members — raises residue
coverage from 3,049 to **5,768 of 7,099 (81.3 %)** and leaves the result unchanged: **0 named,
in every collection**. `continuous_intros`, the row above had to leave blank, is now 368 of
392 covered and 0 named.

Four checks make the 0 an instrument reading rather than an artefact. The key-face splice is
exact: `key_of_rule` (`Universal_Key.ML:932-936`) is `build_thm_key`, which digests
`Term_Digest.thm128 thm` and writes the tag at byte 16 with no rule normalisation, and every
residue group carries a theorem face, for which the splice is the identity. The missing hints
are genuinely missing: of 14,467 members, **11,342 carry no `Markup.nameN` tag at all**, which
is not the same as a tag that resolves badly. The converse holds too — of the members whose
hint does resolve, 3,097 sit on records that already have a position, 27 are absent from the
store, and **0 are residue**. And `Thm.transfer` before the key computation changes nothing
(0 differences over 14,467 members). So §19.4's structural claim is now measured over 17,681
members rather than argued.

**Limits of the third measurement.** The eleven collections hold 7,099 of the 9,597
unnameable records (74 %); within them 1,331 residue keys (18.7 %) stay uncovered even at the
maximal bins, and 126 collections holding 2,498 records were never probed. The result is
nonetheless expected to hold for them, because the reason is structural rather than a
property of these bins — with the condition named: a hint resolves in the SWEEP's context
while the repair needs a positioned record in OUR STORE, and the two coincide because the
sweep was AFP-wide. Also recorded: 102 of the 17,681 probed members have keys absent from
the store altogether (27 of them named), a live-versus-store divergence worth its own look. Separately, the earlier claim that bins are "bimodal in origin,
nothing in between" is neither confirmed nor refuted here: the proxy used against it
measures sweep COVERAGE, not origin, so it cannot settle origin either way — and the
proposition §19.4 actually needed was never bimodality but "a bin's residue recovers at the
rate its live members do", which the third measurement refutes outright.

**Corrections to the figures elsewhere in this section.** Coverage after §19.3's repair is
**98.78 %, 16,368 records without a position** (the 98.45 % / 20,892 first written here was
the pre-repair snapshot, and reported the repair as having changed nothing). Of those,
6,768 are EXPERIENCE records, 9,598 carry a `coll(i)` name, and **2** are the methods
`Named_Simpsets.simp` and `Named_Simpsets.simp_all`. Of the 9,598, **9,597 have no name
available anywhere and one now does**: `Topological_Spaces.tendsto_intros(123)`, whose
theorem face `Limits.LIMSEQ_realpow_zero` (`~~/src/HOL/Limits.thy:2803`) was positioned by a
same-key rename during the pass itself — so **the repair is not a fixpoint, and a second run
of `rename_dynamic_members.py` would find one more target.** Finally,
`Deriv.derivative_eq_intros` is TWO collections, HOL's and a re-declaration in Zippy's
benchmark theory (12 collection names are duplicated this way), so its 674-record row pools
two bins from different sessions; this also gives an alternative explanation for
`derivative_intros(210)` in §19.2, whose evidential weight there now rests on
`tendsto_intros(104)` alone.

### 19.5 The design — MOVED

The forward plan lives in **`DYNAMIC_MEMBER_NAMING_PLAN.md`**, which is self-contained and
is the document to act on. What remains below §19.4 in this section is the record of how the
situation was found and what was already repaired; it is history, not instructions.

#### The design (superseded by DYNAMIC_MEMBER_NAMING_PLAN.md)

#### What problem this solves, and for whom

Not "some records have an ugly name". The specific harm is that **`coll(104)` is
CITABLE-LOOKING**: it is exactly the shape of Isabelle's own fact selection, so a reader —
human or agent — may lift it and use it, and in a different theory's context the same digits
select a different theorem. An ordinary shared name does not invite that; this one does. The
store contains many ambiguous names for unrelated reasons (16,714 `(kind, name)` pairs are
shared across different propositions), and none of them is being addressed here, because
none of them is citable-looking. That distinction is the whole justification.

Scale: 9,598 records of 1,343,793 (0.7 %), over 137 collections.

#### The design, in three pieces, each scoped

**Piece A — a field on the record recording that its stored name is a rendered member
form.**

*The predicate is about the NAME, not about the entity's origin.* It is true exactly when
`build_entries` rendered the name from a `member_idx` (`Tools/semantic_store.ML:852-856`) —
i.e. "the string we wrote ends in a synthetic `(i)`". It is NOT "this entity came from a
dynamic collection": the 4,524 records §19.3 repaired are dynamic-collection members that
now carry ordinary static names and positions, and they must NOT carry this field. Any
future member that acquires a real name (see the separate `get_name_hint` item) likewise
must not.

*Where it is set*: at the point above, carried to Python on the `interpret_file` wire
(`packTuple10` → `packTuple11`, `semantic_store.ML:378-383`), into `Entry`
(`Isabelle_Semantic_Embedding/semantic_interpretation.py:222`, built at `:1247`), and
stored as a 14th field by the record codec, whose positional tail-append makes it readable
by new code on older records (absent = "written before this field existed", not "false").

*Existing records*: one backfill, by the name criterion — the name matches
`^(.*)\((\d+)\)$` and the base names a `THEOREM_COLLECTION` record. Measured exact on the
current corpus in both directions, zero exceptions. It is corpus-dependent, which is why it
is used ONCE over records already written and never as a read-time test. Conditions: re-run
the zero-exception count immediately before, and abort on any exception; run after §19.6's
second `rename_dynamic_members.py` pass, or that pass will rename a record whose field is
already set.

**Piece B — the member form is rendered in ONE place: the semantic-search site's data
path.**

Concretely: the batch that produces the search site's data, or the layer that answers the
site's queries — `SEMANTIC_SEARCH_SITE_PLAN.md`'s export, feeding `site/`'s `{{ r.name }}`.
A reader there sees `tendsto_intros(_)`. That surface shows names for reading only, so it
has no uniqueness requirement and no resolution requirement, and ten hits from one bin may
all render alike: what distinguishes them is the proposition beside the name.

*It applies nowhere else, and the following are excluded by name because each would break
something specific.* **`Record.pretty_print` (`semantics.py:279-283`) and anything
`document_text_of` reaches (`document_text.py:50`)** — the stored name is the head of the
embedded document, so rewriting it there changes what a record's vector should be with no
record write to invalidate it, leaving vectors permanently stale and undetectable.
**Isa-Mini/AoA's retrieval and citation path** — there the displayed name is a HANDLE, not a
label: it is passed back to ML to resolve (`Isa-Mini/IsaMini/AoA/model.py:2347`), becomes
`FactByName(name=…)` "as the model writes it" (`:2443-2447`), and is re-resolved
(`retrieval.py:574`); a member form there is unresolvable, which is a functional regression.
**The exact-name lookup path** (`model.py:2198-2201`), for the same reason. **Any online
read path in `Semantic_DB`**, including `lookup`, whose `_apply_live_name`
(`semantics.py:2046-2051`) already replaces the stored name with a live one — two rewriting
rules on one string is a way to get an unpredictable result.

*Why one place and not a rule applied broadly*: the field says "this record's stored name is
a member form". It does NOT say "rewriting the name is safe here" — that is a property of
the call site, not of the record. Confining the rule to a surface that only ever displays
removes the question.

**Piece C — stop a stored name reaching an LLM where a live one is already in hand.**
Independent of A and B, no data change, no deploy. Two sites: the pattern-only query branch
(`model.py:2318-2322`) keeps `rec` although the live name sits in the loop header; and
`_query_entity_core` (`Isa-Mini/IsaMini/AoA/retrieval.py:937`) prints `rec.name` although
the caller passed a name, and is reachable with any kind through `IsaMini.query_by_name`
(`toplevel.py:65-73`). A third site is not fixed and is accepted: the embedded document's
head (see Piece B's exclusion of `pretty_print`).

#### What is deliberately not done

The stored name is not changed: `coll(104)` goes on being written. That keeps the
interpretation label and the stored name a single field, so no split, no second wire field
for a name, no ~1.6 M-token re-embed, and `rename_dynamic_members.py`'s member test keeps
working. It also means the interpreting agent goes on seeing the index; that risk is
accepted on the measurement that 0 of the 9,598 stored interpretations quote it — an
observation about these agents under this prompt, not a guarantee. No write-time check is
added.

#### Costs, stated so they are not discovered later

The backfill must not go through `Semantic_DB.__setitem__` (`semantics.py:601-621`), which
invalidates vectors unconditionally and would re-impose the ~1.6 M-token re-embed this
design avoids; it must use a raw put as `set_positions` does (`semantics.py:794-815`) under
an L6-style grant, which has to be asked for rather than assumed. It must refuse to run when
a system-layer DB is installed, or `_raw_for_update` (`semantics.py:694-703`) will copy 9,598
system records up into the user layer. The wire change is lockstep: conda ships both halves
in one package, but PyPI ships the Python half alone, so both must be released together.
A 14th codec field also changes what the completeness scan classifies as complete
(`migrate_entity_positions.py:107-116` keys on the field count), and several migration
scripts hard-code field counts.

#### Correction to an earlier claim in this section

An earlier version argued that the position half of this work has no consumer, since nothing
reads a stored record's `position`. **That is wrong and is withdrawn.**
`SEMANTIC_SEARCH_SITE_PLAN.md`'s **D42** (settled 2026-08-14) makes every result card carry
a source link that "resolves through the entity position", and lists `position` in the export
schema as a prerequisite. L8's "no public read API for the position for now" is a deferral,
not the absence of a reader. The same future surface is the consumer for both halves, and it
cannot be cited as a reason the position does not matter while also being the reason to build
this now.

### 19.6 Left open

1. **`resolve_name`'s memo as a `Termtab`** — a separate use, and untouched by §19.5's
   argument because it names nothing: it replaces the per-collection `thm list` memo
   (`context.ML:1243`) with a proposition→index table, so the per-member `find_index`
   linear scan (`:211`) becomes a lookup. `Termtab.default` preserves today's
   first-match-wins semantics exactly. Roughly 7 lines touched, net +6 to +8, one file,
   no signature change; on a 1,327-member bin a member's lookup goes from up to 1,327
   `aconv` comparisons to about 11 term comparisons — and the biggest bins are exactly
   the ones the name hint cannot help, so this is the one change whose benefit lands
   where the population is. **Awaiting a ruling**: the instruction to drop the Termtab
   was given about the naming use, and this one was not separately decided.
2. **Three misleading comments** to correct: `bare_name`'s (`context.ML:69-71`), which
   says the DB-storable name has no live index while A6 re-attaches a snapshot one;
   `_apply_live_name`'s docstring (`semantics.py:2046-2051`), which says it overrides
   "the stored bare name"; and the claim at `semantics.py:2110-2111` that the reranker
   scores the same text that was embedded, which for these records it need not.
3. **The 127 groups** whose several positioned records disagree on the name (§19.3):
   exactly 127 renamed records are affected, and a sample showed the disagreement is
   between a theorem-face `X.axioms(n)` and an elimination-face `XD(n)` naming the same
   proposition, so the deterministic `(kind, name)` minimum is defensible. Not examined
   in full.
4. **A second run of `rename_dynamic_members.py`** would find one further target
   (§19.4): the pass is not a fixpoint, because its scan completed before its own
   writes.
5. **The unmeasured tail of §19.4's third measurement** — 126 collections holding 2,498
   of the 9,597 unnameable records were not probed.
6. **The development machine's store** is still pre-re-key; §18.5's scope note stands,
   and catching it up is a snapshot sync, not a backfill.
7. **102 of 17,681 probed members have keys absent from the store** (27 of them carrying a
   resolving name) — the one place where "a sweep saw something we cannot match" is
   demonstrably real, and unexplained.
8. **The residue still uncovered by measurement**: 1,331 keys (18.7 %) inside the eleven
   probed collections even at their maximal bins, plus 126 collections holding 2,498
   records never probed.

### 19.7 Review record

**The third review round (four reviewers, 2026-08-18) was VOIDED at the user's instruction**,
because §19.5 as it then stood did not say WHERE its rendering rule applied, so the reviewers
were reviewing an ambiguous document and their verdicts cannot be read as judgements of the
design. §19.5 has since been rewritten to scope every rule, and is to be reviewed again.
Facts independently verified with tools during that round are kept, since they are
measurements rather than opinions, and are marked where they appear: `tendsto_intros(104)`
names one proposition today rather than three; D42 gives the position field a decided
consumer; `pretty_print` feeds the embedded document; §19.3's counts were pre-repair; and the
records §19.3 repaired are dynamic-collection members carrying static names, which is why
Piece A's predicate is about the stored name rather than the entity's origin.

Four adversarial reviewers over two rounds (mechanism and citations; measurements and
inference; the design decision; implementation risk), then a third measurement run to
settle what the debate could not. What the review changed is recorded above in place
rather than as a list of amendments, but the load-bearing reversals are worth naming so
they are not silently re-proposed: the recovery figure fell from ~57 % to 16.2 % to **0**
on today's store; `Fixed (nm, 0)` was wrong; "changing the enumeration repairs the store"
was wrong, since nothing rewrites an existing record's name; the reason for rejecting the
proposition-matching Termtab moved from the name to the position; the reason for
preferring the name hint over `derivation_name` moved from `official2` to `apply_facts`'s
ordering; the label-uniqueness assert was mis-cited to a comment; the coverage figures
were the pre-repair snapshot; and the two-state invariant was demoted from a justification
to an aspiration. Reviewers also verified as CORRECT the citation chain of §19.1, the
key-safety of renaming, the dichotomy and collision statistics of §19.3, and the
`rename_dynamic_members.py` pass itself under two independent attacks (regrouping by
digest alone finds no extra target; the borrowed `X(i)` names are genuine static bundles).
