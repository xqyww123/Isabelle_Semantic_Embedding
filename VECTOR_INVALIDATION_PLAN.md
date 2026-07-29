# Vector invalidation and the vector-layer self-sufficiency invariant

Revision 2 — rewritten after the four-lens adversarial review of 2026-07-29 and
the decisions taken on its findings. Supersedes `SEMANTIC_DB_LAYERED_PLAN.md`
L23 and rewrites its §3.2 lookup rule; amends L2 (§7) and touches
`Isabelle_RPC` (§10).

**The canonical name is "the vector-layer self-sufficiency invariant".** It
names the property the code gains: the vector stores answer every question
about vectors on their own, consulting no other store. Use this term verbatim
everywhere — never "authority", "binding", or any other paraphrase, and never
L23's "vector–record binding", which this replaces.

Every decision here is user-approved. §12 records what the review raised and
was rejected, so it is not re-derived.

## 1. The defect this fixes

`SEMANTIC_DB_LAYERED_PLAN.md` records, as a known residual (§3.2, "Residual
(pre-existing)"):

> a stale USER vector for a user-resident record is still governed by the
> existing text-changing-writers-refresh-their-vector discipline.

**For entity records that discipline does not exist in the code.**
`InterpretationTask.write_answer` (`semantic_interpretation.py`) overwrites a
record's interpretation and never touches vectors, and every refresh path
filters on *presence*, not on content: `complete_vector_store` and
`embed_records` / `embed_keys` all gate on `contains(...)`, and `_auto_embed`
only ever sees the keys `_topk_sync` reports missing. So a re-interpreted
entity keeps the vector computed from its OLD text and is counted complete by
every mechanism that could have fixed it. Reproduced against the real facade:
the old vector is still served and `contains()` returns `True`.

(For EXPERIENCE records the discipline does exist — `put_experience` embeds
before writing and `delete_experience` drops vectors in every store. The gap is
the entity path.)

Scope note: this is not layering-specific. A single-layer DB has the same
defect; layering adds the L14 stand-in case (§7) on top.

**Citations in this document name functions, not line numbers.** This is a
shared working tree — three commits landed in `semantics.py` during the review
alone, moving every line reference by 13–17 lines.

## 2. The vector-layer self-sufficiency invariant

**A vector question is answered by the vector stores alone.** For any key the
user vector layer has three states, and they fully determine the answer; the
system vector store is consulted only on the third, and no record store is
consulted at all.

```
real vector  -> serve it
tombstone    -> serve nothing (masks any system vector)
absent       -> fall through to the system vector
```

`Vector_Store._raw_getter` becomes, in full:

```python
v = user_vec.get(k)
if v is not None:
    return None if is_tombstone(v) else v
return system_vec.get(k)
```

Consequences:

- **No record-layer consultation.** `Vector_Store` no longer imports
  `Semantic_DB`, no longer opens the record environments, and no longer encodes
  record-layer semantics. The layering violation in today's `_raw_getter` is
  gone.
- **Hot path.** Up to 4 read transactions and 2–3 gets per key collapse to one
  get plus a fallback. Measured on the production store (97,626 keys, 4096-dim):
  the record-layer consultation costs **+43 ms** on the gather phase alone
  (67 → 110 ms), and that models the 2-get path; a system-resident-heavy domain
  does 3 gets and costs more.
- **On a machine with no system DB it is a small regression**, because today's
  bare `txn.get` shortcut must become a closure with a tombstone test.
  Measured: **+1 to +5 ms** per 100k-key gather (use `v if v else None`, not
  `len(v) == 0`; `bool(memoryview(b""))` is `False` and the truthiness form is
  the cheap one).
- **What replaces the read-side check** is write-side discipline (§3), and
  unlike today there is no backstop (§6).

L23's own caveat is what fails: it assumed "same-model-same-text determinism".
Re-interpretation breaks exactly that assumption.

## 3. The load-bearing write sites

Invalidation lives in `Semantic_DB`'s setter so it cannot be forgotten. **But
the setter only covers callers that go through `__setitem__`.** Several writers
open a write transaction directly and must each be handled.

| Site | File | Changes document text? | Obligation |
| --- | --- | --- | --- |
| `Semantic_DB.__setitem__` | `semantics.py` | yes | **unconditionally tombstone the key's vector in every model store** — the core of this plan |
| `Semantic_DB.delete` | `semantics.py` | yes (record vanishes) | today L8 requires callers to really-delete user vectors; becomes **write a vector tombstone** |
| `Semantic_DB.update_expr` | `semantics.py` | **yes** — `expr` feeds `pretty_print` feeds `entity_document_text` | writes via `txn.put` directly, **not through the setter**. Route it through the setter or invalidate explicitly |
| `Semantic_DB.repair_xor_prefixes` | `semantics.py` | yes (re-key) | moves vectors then really-deletes the old key; becomes **tombstone at the old key**. Bulk single-transaction — do not route per-key through the setter, it would break its atomicity |
| `Semantic_DB.clean_wip` | `semantics.py` | yes (records vanish) | already paired with `Semantic_Vector_Store.clean_all_wip_in_created_dbs` through the module-level `clean_wip()` wrapper; keep the pair intact |
| **`_execute_removal`** | **`isabelle_semantics.py`** | **yes** | **the engine behind `remove` and `prune`, in another file and another process.** It never calls `Semantic_DB.delete`: it writes record tombstones with a raw `txn.put` and **really deletes** user vectors. Under §2 that key then resolves to the SYSTEM vector, so a removed but still-loaded theory's entities keep scoring in `topk` (candidates come from live ML enumeration, which knows nothing about the DB). Must **write vector tombstones** |
| `Semantic_DB.mark_interpreted` | `semantics.py` | no — theory status | none |
| `Semantic_DB.rebuild_experience_index` | `semantics.py` | no — index only | none |

`update_expr` and `_execute_removal` are review findings. `update_expr` copies a
system-resident record up into the user layer with a changed `expr`, i.e. it
changes the embedding document text and touches no vector; today's defensive
read hides this. `_execute_removal` was missed because §3 originally enumerated
only `semantics.py`.

### 3.1 The enumerator must cover system-shipped models

`_iter_vector_store_envs()` lists `vector_*.lmdb` under the **user cache only**.
The system DB ships stores for zero or more models (L14), so a model whose user
store does not exist on disk would receive no tombstone — and after switching
`EMBEDDING_MODEL` to it, its stale system vector would be served for a
re-interpreted record, forever. The fresh-machine case is the same: the user
store directory is created lazily, so an interpretation pass that runs before
any embedding would tombstone nothing at all.

The fix pattern already exists in `snapshot_sync.export`, which unions user and
system store basenames. The invalidation helper must do the same and **create
the user store on demand** to hold the tombstone.

Verified safe: `Semantic_Vector_Store.created_embedding_models` — the one
function that could have mistaken an empty store for "the user uses this model"
— has **zero callers** repo-wide. The only visible effect of extra empty stores
is `cmd_remove`'s `Also cleaning N vector store(s).` count.

### 3.2 One helper, extracted not invented

All invalidation goes through **one shared helper**; no open-coded
`txn.delete` / `txn.put(b"")` on a vector store anywhere else. That helper is an
*extraction*: `delete_experience`'s loop is its single-key form, and
`_execute_removal`'s is its batch form. Generalize to a key list with a
tombstone-vs-delete mode, and collapse the **three** existing enumerators
(`_iter_vector_store_envs`, `_vector_store_paths`,
`created_embedding_models`) onto one — `_execute_removal` currently acquires
environments by a second mechanism (`lmdb.open` + `close`) instead of the
process-cached opener.

## 4. Storage and the pitfalls

1. **The tombstone value is `b""`**, reusing `TOMBSTONE` / `is_tombstone`
   (`semantics.py`). Do not invent a second representation. Real vectors are
   exactly `D*2` bytes, so an empty value is unambiguous.
2. **Tombstones must be translated to `None` on EVERY return path of
   `_raw_getter`** — the user branch, the system fall-through, **and the
   single-layer shortcut** (`if senv is None: return utxn.get`, which today
   returns the raw value bare). Missing the shortcut is not cosmetic: the CI
   export runs single-layer, and `export` writes `if vec is not None`, so an
   untranslated tombstone would be **shipped into the published payload**.
3. **A tombstone must never reach `gather_addrs`.** It classifies a length
   mismatch as *skipped*, which both mis-classifies it (the correct
   classification is *missing*, so `_auto_embed` refills it) and prints
   `topk skipped N record(s) whose size is not ... may not be migrated to Q1.15`
   on every query. Reporting a tombstone as *missing* is safe for deleted
   records too: `_auto_embed` looks the record up, finds none, and drops it.
   Pitfall 2 subsumes this: translate at the getter and nothing downstream sees
   `b""`.
4. **`__getitem__` must check for a tombstone before `_decode_q15`**, which
   raises on any length other than `D*2`. Redundant once pitfall 2 holds;
   defence in depth.

`_check_vector_format` needs **no change**: it has exactly one call site, over
the freshly written export payload, and `pull` never calls it. Once pitfall 2
holds, a tombstone cannot reach that payload.

No format version bump, no migration, no republished system DB: an existing
store simply has no tombstones yet, which reads as "absent" — today's
behaviour.

**Known and accepted:** an older package version sharing the same per-machine
cache dir will treat a tombstone as a present vector (`contains()` → True,
`gather_addrs` → *skipped*, `__getitem__` → `ValueError`, plus a misleading
migration warning on every query). Not corruption, no data loss, and
self-repairing the moment new code runs. The remedy is the one the installer
already prints: restart long-lived RPC hosts / REPL servers after upgrading.
Say so in the release notes.

## 5. Ordering rules

**Cross-store atomicity is impossible.** LMDB transactions are per-environment,
and `semantics.lmdb` and each `vector_<model>.lmdb` are different environments.
What is available is atomicity *within* each store plus a fixed order between
them.

**Rule 1 — invalidate before writing the record.**

- crash between the two: vector tombstoned, record still old → the next pass
  re-embeds from the old text. Wasted work, self-healing.
- reverse order, crash between: record new, vector old, and under §2 nothing
  will ever notice. Permanent staleness.

**Rule 2 — `put_experience` becomes record → index → embed** (today: embed →
record → index). The fallible/remote step goes **last**, so that when it fails
everything durable is already in place.

Why the current embed-first order must go: with §3 in place the setter
tombstones the key's vectors, so embedding first would tombstone the vector
written one line earlier — embed-first is self-defeating. That shows it is
broken; the following shows record-first is *safe*:

- `put_experience`'s docstring calls a record+index entry with no vector "a
  silent, unretrievable orphan". **It is not unretrievable.** The experience
  retrieval domain is `Experience_Index`-driven — `lookup` runs
  `topk(exp_qvec, list(exp_hit.keys()), ...)` where `exp_hit` comes from the
  index, not from the vector store — so a vector-less key still enters the
  domain, is reported missing, and `_auto_embed` rebuilds it from the record
  (its step 2 embeds every EXPERIENCE regardless of the interpretation gates).
- The module already states the opposite priority: `delete_experience` deletes
  the record **last** because it "holds the whole experience ... and nothing can
  rebuild it; the index and the vectors are derived".
- Under a provider outage, embed-first **discards** agent-authored content that
  cannot be regenerated; record-first keeps it and fills the vector later.
- Index must precede embed: `_experience_hits` is index-driven, so a failure
  before the index write would make the experience permanently invisible.

Keep the existing precondition that raises `ValueError` when
`document_text_of(rec)` is `None` — a record that can *never* be embedded is a
different case and should still be refused.

**Rule 3 — batch granularity is one interpreter answer.** The batch interface
takes a list, writes it atomically within each store, and obeys Rule 1. The
interpretation module calls it per answer, matching the existing durability
granularity (`Tools/interpret_command.ML`: "answers are written to LMDB as they
arrive ... so a re-run resumes"). Measured cost: **457 µs per write-transaction
commit** on ext4/NVMe (fsync-bound), so ~1.4 ms per answer across three model
stores, ~1.4 s for a 1000-entity theory — noise against LLM latency.

The list form is not for that call site — there the batch is always a singleton.
It is for the genuinely bulk sites (`repair_xor_prefixes`, `_execute_removal`,
`clean_all_wip_in_created_dbs`), where in-transaction deletion at ~0.4 µs per
key against a 457 µs commit is a 1000× difference.

## 6. The cost, stated plainly

**The read path loses its backstop.** Today a writer that forgets to invalidate
is still corrected at read time, because `_raw_getter` consults the record
layer. After this change there is nothing behind the writers: one missed site
serves a stale vector forever.

This is taken knowingly, because the write sites are enumerable (§3) while the
read sites are the whole system. The precedent argues for caution: the
discipline in §1 was *documented as existing* and never implemented, and the
review found two more sites (`update_expr`, `_execute_removal`) that the first
draft of §3 had missed.

Mitigations, both required:

1. **One shared invalidation helper** (§3.2).
2. **An `fsck` structural check**: for every key holding a real user vector,
   assert a **layered-visible** record exists — user *or* system. It must not
   be read as user-visible, which would flag every legitimate L14 stand-in and
   fire on a healthy DB. This catches the `delete`-site miss (a real user vector
   under a record tombstone) structurally; it cannot catch staleness, by design
   (there is no digest). Note that §7's predicate is deliberately the narrower
   "no non-tombstone **user-layer** record": the two differ on purpose.

**`_count_shadowed_user_vectors` and its `fsck` report line are deleted.** The
rule they describe — "vectors L23's binding rule does not serve" — no longer
exists under §2. Worse, the counter's branch for tombstoned records would count
every vector tombstone and label it `safe to ignore; disk only`, while §7 says
in as many words that deleting a vector tombstone unmasks a suppressed key:
user-visible advice becoming actively wrong. Its other branch is inverted under
§2 as well. Nothing replaces it.

**Known side effect.** `Semantic_DB[k] = rec` now opens every `vector_*.lmdb`
(and creates ones the system DB ships, §3.1). Paths that previously never
touched vectors acquire that dependency.

**On over-invalidation.** The setter does not compare texts before
invalidating; it always invalidates. This is not free — the provider's
`embed_cache` has a 3-day TTL and a 2 GiB cap, and was measured at 121 entries
/ 2.1 MB against a 110,423-key store — but it is right anyway: the only
production callers of the setter are `write_answer`, which by construction has
just received a *fresh* LLM answer, and `put_experience`, which embeds
explicitly. The unchanged-text case needs a re-interpretation returning a
byte-identical answer, and even then costs one embedding call beside the
interpretation call that just produced it.

## 7. The system-upgrade purge

Part of this plan. Amends L2 ("DELIBERATELY hook-less") in the
`isabelle-semantic-data` recipe.

**The case.** When the system DB is replaced — conda upgrade or
`isabelle-semantics pull` — and it ships **no vector store for the active
model** (the L14 stand-in), the user layer holds a vector computed from the OLD
system text. §2 cannot help and neither can tombstones: a legitimate stand-in
fill and a stale one are both ordinary positive values, and telling them apart
needs exactly the record layer §2 decoupled from. Nothing local was written, so
§3's write sites never fire.

**The rule.** Delete every **real** (non-tombstone) user-layer vector whose key
has **no non-tombstone user-layer record**, over **entity keys only**. A key the
user has interpreted locally has a user record and is untouched, so no
user-authored embedding is discarded.

Four details that are easy to get backwards:

- **Delete, do not tombstone.** This is the one place in this plan that really
  deletes. A tombstone would mask the vector the *new* system DB ships. The
  key's record is system-resident, so there is nothing to mask: after deletion
  the key reads "absent" and resolves to the new system vector, or is
  re-embedded from the visible system record.
- **Skip tombstoned vectors.** Deleting a vector tombstone would unmask a
  system vector for a deliberately suppressed key.
- **Skip keys whose record is a tombstone.** "No non-tombstone user record" is
  literally satisfied by a tombstoned record; deleting a real vector under one
  has the same unmasking effect.
- **Entity keys only.** Vector stores also hold the 16-byte theory embed-status
  records (`mark_thy_embedded` / `_thy_embed_status_raw`). Measured: 723 of them
  on the production store, one of which the unqualified predicate would already
  delete today. Losing them makes `is_thy_embedded` false across the board and
  discards the accumulated `total_tokens` ledger. Every other consumer —
  `_check_vector_format`, `export`, `_count_shadowed_user_vectors` — already
  special-cases `len(key) == 16`.

**The trigger is a conda post-link hook on the `isabelle-semantic-data`
package**, calling `isabelle-semantics post-install-system-db` (approved name),
plus an inline call from `install_system_db` for the `pull` path.
The hook fires exactly when the payload changes, before any process can read
it, which removes the alternative design entirely: no remembered `created_at`,
no comparison, no bootstrap case, no marker file, no per-process check, and
none of the deadlock hazard that a lazy trigger inside `validated_system_db()`
would have created (verified: `_ensure_system_env` holds a non-reentrant lock
that the purge would need again, and `_get_raw_many` reaches it in that order
on a fresh process).

The hook may call our own console script: the dependency edge is
`isabelle-semantic-data` → `isabelle-semantic-embedding >=0.3.0`, one-way and
cycle-free by design, so conda links the library **first** and
`$PREFIX/bin/isabelle-semantics` is guaranteed present. Calling it (rather than
`python -c`) keeps cache-directory resolution — including the
`SEMANTIC_DB_DIR` override — in one place.

Constraints, from this project's own measured packaging research
(`isabelle-packaging-ci/PACKAGING_DESIGN.md` §3.1):

- **The hook must exit 0 on every path.** A nonzero post-link makes conda roll
  the whole install back (measured, isabelle-packaging-ci run 29637825807).
- **Ship both `.sh` and `.bat`.** The data package is `noarch: generic`; conda
  picks by the running platform and returns success **in silence** when the
  file is absent, so a `.sh`-only package installs cleanly on Windows and does
  nothing. The `.bat` must be CRLF.
- **Output on success is not reliably displayed** (conda-build: do not write to
  stdout/stderr unless there is an error). Printing is best-effort; the log is
  the record.
- **No interaction is possible** (`stdin=None`), so no confirmation prompt.
  Accepted: not purging is the worse failure.
- The data recipe's own comment — "DELIBERATELY hook-less (plan L2) ... nothing
  to do at link time" — must be rewritten with the reason.

**Not covered, deliberately:** environments created without running hooks
(`conda create --clone`, conda-pack, some lockfile installs) never purge. No
fallback.

**Blast radius, measured** on the production store: the target set is **13.4%**
of real vectors (14,689 of 109,700), of which **14,688 resolve immediately from
the system vector store at zero cost** and one is a true orphan. It costs real
re-embedding only in the L14 case, which is the case it exists for.

**Nothing here writes to the system DB**, and nothing in this plan ever may. It
is opened `readonly=True, lock=False`; updates replace the directory wholesale;
conda hardlink-shares the payload files across environments (L4), so an
in-place write would mutate the shared package cache and every other
environment on the machine; and a locally-mutated system layer would destroy
the property that makes system records and system vectors consistent by
construction — the property that lets §2 skip freshness questions on that layer
entirely.

**Known limitation.** A long-lived process started before the upgrade keeps the
old payload through its mmap and its cached `validated_system_db()` verdict, so
it can re-fill purged keys from the OLD system text after the purge ran. The
resulting state is identical to today's (an L14 stand-in from old text), so it
is a hole in the fix rather than new damage. Restart long-lived hosts after an
upgrade — which the installer already tells you to do.

## 8. Opening a vector store: one entry point, one policy

`_get_lmdb_env` becomes **the** opener for user-layer vector stores;
`_execute_removal`'s second mechanism is deleted in favour of it. It gains
guarded behaviour modelled on `_try_system_store_env`, with exactly **two**
classes and no third path:

- **Corruption class** — `CorruptedError`, `InvalidError`,
  `VersionMismatchError`, `PanicError`: move the store aside to
  `<name>.bak-<timestamp>` (the tree's existing backup convention) and rebuild
  it empty.
- **Everything else** — log, warn, and **raise**. No degradation, no
  per-model special casing.

**Why "everything else" may simply raise.** The complete set of open-time
environment failures is small, and every member is a property of the machine,
not of the data: permissions (`OSError` EACCES/EPERM, or `LockError` on
`lock.mdb`), ENOSPC when *creating* a store (which §3.1 now does on demand),
a read-only filesystem (EROFS), file-descriptor exhaustion (EMFILE/ENFILE),
mmap/address-space failure (`lmdb.MemoryError`, ENOMEM), and network-filesystem
locking (`LockError` — `_paths.py` warns about exactly this). Every other
py-lmdb exception is transaction- or cursor-level and cannot surface at
`lmdb.open`.

All six are **directory-wide, not per-store**: `semantics.lmdb` lives in the
same directory on the same filesystem, so when one of them fires the record
store is equally unopenable and the subsystem cannot work at all. That is why
an earlier proposal to distinguish "the active model's store" from the others
was dropped — the distinction defends against a failure mode this set does not
contain. It is also why raising loses nothing: the answer that would have been
written was never going to be persisted, and with §8.2's ordering fix it is not
marked answered either, so the agent is told and can retry.

**Raise, do not `sys.exit`.** In the RPC host an unhandled exception comes back
to Isabelle as an error the user actually sees; `sys.exit` kills the host and
leaves only a corpse in the log.

**In both classes the actual cause is reported verbatim** — the `lmdb.Error` /
`OSError` text and the store path. A failure is never reframed as the normal
state "this model has no vector store"; that would disguise a fault as a
configuration.

**One exception, by entry point not by policy:** `post-install-system-db` must
`exit 0` whatever happens (a nonzero conda post-link rolls the install back),
so that command wraps the call and reports rather than propagates.

**Reporting** follows the convention already in the tree (`hover.py`,
`desugar.py`, `semantics.py`'s reranker path): always log, and additionally
report to Isabelle when a connection is available. `_get_lmdb_env` is a
synchronous module-level function with no connection in hand, so it logs
immediately and queues the message for the next connection-aware call to flush
via `connection.warning`. §10 is what makes the log half actually work.

**Invalidation failures are logged and never fatal.** A write failure in one
vector store (map full, ENOSPC, mid-write I/O error) must not propagate out of
`Semantic_DB.__setitem__`: `write_answer` has no error handling, so an
exception there destroys an LLM answer that cost money and cannot be
regenerated. The priority ordering is the one `delete_experience` already
states — derived data is rebuildable, authored content is not. The residual is
one stale vector with no read-side backstop, recorded in the log and
structurally visible to §6's fsck check.

This matters because the change **widens the failure surface** of that setter
from one transaction on one environment to N+1 transactions on N+1
environments.

### 8.1 Approved messages

Verbatim. Neither carries a literal `WARNING:` — the log level and Isabelle's
own rendering already say that three times over. `_try_system_store_env`'s
existing message is realigned to match.

Corruption class:

```
[Semantic_Embedding] The vector store for <model> could not be opened and
appears corrupt: <error>
  store:    <path>
  moved to: <path>.bak-<timestamp>
A new empty store has been created.  Every vector for this model is gone and
will be re-embedded on demand, which costs embedding API calls.
```

Environment class — the cause and the path, nothing more:

```
[Semantic_Embedding] The vector store for <model> could not be opened: <error>
  store: <path>
```

`MDB_MAP_FULL` must not be folded into the environment class. It is not a full
disk but the store hitting `VECTOR_MAP_SIZE` (16 GiB), and the remedy is to
raise that ceiling, not to free space; sending the user to clean their disk
would waste their time. It needs its own message.

### 8.2 `_answer_tool`: persist before marking, and per-item isolation

Two pre-existing defects in `semantic_interpretation._answer_tool`, both
approved for fixing. They are not caused by this plan, but this plan widens the
setter's failure surface from one transaction on one environment to N+1 on N+1,
so they become materially easier to hit.

Today the loop sets `task.results[key] = trans` **before** calling
`task.write_answer(...)`. The in-memory map is what decides `batch_remaining`,
which entries the next batch asks for, and which count as unanswered at the
end — so a failed persist leaves memory claiming an answer that is not on disk,
and the entry is never re-asked in that run. It is lost silently even though
the tool call itself returned an error to the agent (the MCP SDK turns any
handler exception into an `isError` result, so nothing crashes and nothing
reaches Isabelle). The code already documents this shape happening once before,
for lone UTF-16 surrogates.

1. **Persist first, mark in memory second.** "Answered" then means "durable".
2. **Wrap each item**, appending the failure to the `errors` list the handler
   already builds and returns. Today an exception on item 3 of 10 skips items
   4–10, which were fine.

Only `_answer_tool` is affected: of the five tools the driver registers, the
other four (`query_by_name`, `definition`, `hover`, `desugar`) write nothing.
The cost accumulator (`write_cost`) also lets memory lead disk, but that is
deliberate and affects only token accounting.

*Still open:* a circuit breaker. On a full disk the agent is told "failed" for
every answer and will retry into a wall, burning LLM tokens with nothing to
stop it. Proposal: abort the run after N consecutive persist failures with an
explicit reason. N and whether to do it at all are undecided.

## 9. `remove`'s output — approved wording

A warning about permanence was drafted and **rejected**: `remove` deletes what
the user asked it to delete, which is ordinary behaviour and does not warrant
an alarm. What remains is a statement of fact, and two pieces of implementation
vocabulary that had leaked into user-facing text.

Three changes to `cmd_remove`, approved verbatim:

1. **Add**, after the "Will remove:" listing and only when some target is
   system-resident, one line: `Some of these records come from the installed
   semantic database.` No `Warning:` prefix — it is a fact, not an alarm. One
   line, not a per-row tag: simpler.
2. **Delete** the post-action line `Note: system-resident records are now
   masked locally; they drop out of the published snapshot at the next
   release.` "Drops out of the published snapshot" concerns whoever publishes
   the data package, not the user running the command.
3. **Reword** the summary from `Removed N theories (M records tombstoned;
   vectors and index entries dropped).` to `Removed N theories (M records, with
   their vectors and index entries).` "Tombstoned" is the name of a storage
   technique.

## 10. Prerequisite: logging in `Isabelle_RPC`

§8's policy is "always log". Today that is not true in the deployment that
matters, so these changes land in the `Isabelle_RPC` package first. They are
listed here so they are not lost; they are not Semantic_Embedding changes.

Measured current behaviour: `mk_logger_` attaches its handler only to
`Isabelle_RPC_Host.rpc` with `propagate = False`, so a record from
`Isabelle_Semantic_Embedding.*` reaches the host's log **file** in none of the
three entry points. Under the console-script launcher it goes to root's stderr
handler only; under `run_attached__` root has no handler at all, so a WARNING
falls to `logging.lastResort` as a bare unformatted line (which `Tools/RPC.ML`
does redirect into the log file) and INFO/DEBUG are dropped; and under
`fork_and_launch__` — **the path long-lived hosts actually use** — stderr is
dup2'd to `/dev/null` and the record is destroyed outright.

1. **`mk_logger_` installs its handler on the root logger**
   (`basicConfig(handlers=[h], level=DEBUG, force=True)`) and leaves
   `Isabelle_RPC_Host.rpc` handler-less with `propagate` untouched. Every
   `server.logger` / `getChild` call site keeps working. Chosen over adding a
   second handler because it leaves `semantic_interpretation.py`'s
   handler-copying hack harmless (its guard tests for handlers on the rpc
   logger, which are then absent) instead of requiring its removal first.
2. **Remove `logging.basicConfig(...)` from `launcher.py`** — redundant once
   (1) lands, and a source of doubled stderr output.
3. **Damp the noisy third-party loggers** to WARNING: `httpx` (one INFO per
   HTTP request, i.e. per embedding call), `httpcore` (~10 DEBUG lines per
   request), `anthropic`, `mcp`, `uvicorn`, `asyncio`.
4. **Log format** gains the logger name and loses the redundant prefix:
   `%(asctime)s - Host {addr} - %(name)s - %(levelname)s - %(message)s`.
5. **`fork_and_launch__` points stderr at the log file** instead of
   `os.devnull`, matching what `_spawn_detached_nt__` already does on Windows
   and what `Tools/RPC.ML` does for the attached path.

And in Semantic_Embedding: **the bare `logging.getLogger(__name__)` in the
reranker-failure path of `semantics.py` must use
`connection.server.logger.getChild(...)`** when a connection is available,
falling back to the module logger only when it is not. That is the convention
already used by `hover.py`, `desugar.py` and `semantics.py`'s own
`getChild` call site; that one call site simply never followed it.

## 11. Tests

- re-interpretation invalidates: write a record, assert `contains()` is now
  `False` and the next embed pass rewrites the vector;
- a tombstone masks a system vector, for both a deleted record and a pending
  re-embed;
- absent (not tombstoned) falls through to the system vector — the L14
  stand-in path still works;
- a tombstone never reaches `gather_addrs`: no "skipped" warning, and the key
  is reported *missing*; assert this on the **single-layer** path too;
- export from a single-layer store containing tombstones ships no 0-byte value;
- `put_experience` with a failing embed leaves record + index + tombstone, and
  the next experience query recovers it;
- ordering: simulate a crash between the vector tombstone and the record write,
  assert the self-healing state, not the stale one;
- every write site in §3 invalidates, including `update_expr`,
  `repair_xor_prefixes` and `_execute_removal`;
- §3.1: with a system store for a model the user lacks, a re-interpretation
  creates that user store and puts a tombstone in it;
- an invalidation failure in one store is logged and does **not** propagate out
  of `__setitem__`;
- corruption-class open failure backs up and rebuilds; environment-class open
  failure touches nothing and degrades — both report the underlying cause;
- the §7 purge drops a stand-in vector whose key has no user record; **keeps**
  the vector of a locally interpreted key, **keeps** vector tombstones, **keeps**
  real vectors under record tombstones, and **keeps** 16-byte embed-status
  records;
- the §7 purge is idempotent.

## 12. Raised by the review and rejected

Recorded so it is not re-derived.

- **"Drop §2; a plain `txn.delete` suffices."** True that §4 and half of §6 are
  §2's price, and that §7 is independent of §2. Rejected on the merits after
  the remaining objections were each given a bounded fix (§3.1, §3.2, §4.2,
  §6): the trade is a handful of enumerable changes against −43 ms per query
  and a read path that no longer reaches into the record store.
- **"Back-compat is a blocker; bump the format or rename the stores."**
  Downgraded: degraded retrieval plus a misleading warning in old processes, no
  data loss, self-repairing. A store rename would make old code silently
  re-embed a whole library into the old directory — 1.3 GB doubled and a full
  round of API spend. See §4's accepted note.
- **"§7's purge deletes essentially the whole store."** Measured 13.4%, of
  which all but one entry restores at zero cost.
- **"Every other destructive operation prompts first."** `clean_wip` does not.
- **"The trigger stalls live queries."** Measured 0.22 s for the whole scan, on
  a worker thread. (The *deadlock* half was real and is why §7 does not use a
  lazy trigger.)
- **"§2 is a performance regression on single-layer machines."** Measured
  +1–5 ms, not the claimed +20–27 ms. Recorded in §2.
- **"`_check_vector_format` becomes a nondeterministic gate."** One call site,
  over the export output only; `pull` never calls it.
- **"§7's scan and trigger already exist."** `_count_shadowed_user_vectors`
  uses the *inverse* predicate — it counts only keys for which the system store
  ships a vector, while §7's whole population is the case where it does not.
  The trigger did not exist and could not have covered the conda path.
- **"§6 and §7 contradict each other on invalidation cost."** Different
  timescales, and the embed cache is keyed by text: §7's targets are exactly
  the keys whose text changed, so a hit was never possible for them.
- **"Rule 2's justification is deletable."** Its first bullet is load-bearing:
  it refutes the "unretrievable orphan" premise stated in the code today.
- **"§6's fsck check is deletable / reverses documented policy."** It is the
  opposite direction from the documented policy (which declines to check
  record → vector), and it catches the delete-site miss.
- **Terminology and migration-script findings.** "Purge" is already the tree's
  verb; retiring L23's name is already stated above; no migration script
  changes an entity's document text. Copy-edits at writing time, not review
  items.

## 13. Implementation

Everything above is approved. This section is the handoff: it is written so
implementation can start from this document alone.

### 13.0 Status: implemented 2026-07-29

All eight steps of §13.1 are in the tree. What the implementation added or
changed relative to the plan text:

- **`base.logger_of(connection, name)`** — a shared helper for the "prefer the
  RPC host's own logger, fall back to the module logger" convention §10's last
  paragraph describes, so `semantics.py`'s reranker path and
  `semantic_embedding.py`'s opener use one implementation rather than two.
- **`_log_format_(addr)`** in `Isabelle_RPC_Host.rpc` — the approved format
  string, in a function so both handler branches share it.
- **A fourth enumerator was found and collapsed too**: `_try_migrate`'s inline
  `vector_*.lmdb` scan, which §3.2's count of three had missed.
- **`repair_xor_prefixes` invalidates through the helper in a second pass**
  rather than tombstoning inline in its move loop, so no vector store is
  written with a bare `put(b"")` anywhere but the helper. The cost is one extra
  transaction per store; the window between them holds one correct vector under
  two keys.
- **§7's predicate is implemented as "the key has NO user-layer entry at all"**.
  That is what §7's two clauses jointly mean — "no non-tombstone user record"
  *and* "skip keys whose record is a tombstone" — but stating it as presence
  rather than content is what makes it hard to get backwards.
- **`_count_vectors_with_no_visible_record`** is §6 mitigation 2, reported by
  `fsck` only when nonzero.
- **`Vector_Store.delete` now writes a tombstone** (user decision, after
  implementation): it deletes from the LAYERED view of its own store, so the
  system layer's vector is masked too, and it returns whether a vector was being
  served rather than whether a user entry existed. It is scoped to one store on
  purpose — invalidating a record's vectors across every model is the record
  layer's job. `invalidate_vectors_in_store` was split out of
  `invalidate_vectors` to serve it, so "exactly one place writes `b""` into a
  vector store" stays literally true.
- **The back-compat release note (§4) is dropped** (user decision): not written.
  Note for whoever revisits it that the conda install path has **no** check for
  a running RPC host or REPL server — `_IN_USE_ERROR` and the "restart" hint
  both live in `install_system_db`, i.e. the manual `pull` path only, and
  `_IN_USE_ERROR` is a reaction to a Windows rename failure rather than a check
  (on POSIX the rename succeeds and nothing fires). This is the mechanism behind
  §7's "Known limitation".

### 13.1 Order

Each step is independently testable; do them in this order.

1. **`Isabelle_RPC` logging** (§10 items 1–5). Independent of everything else,
   and §8's "always log" is not true until it lands.
2. **`semantics.py`'s reranker-path logger** (§10, last paragraph) — one call
   site, follow the `getChild` convention.
3. **`_answer_tool`** (§8.2): persist-then-mark, per-item isolation. Small,
   zero-risk, and pre-existing.
4. **The unified opener and the invalidation helper** (§3.2, §8). Collapse the
   three enumerators, add the union over system-shipped stores (§3.1), add the
   two-class open policy.
5. **Read side** (§2, §4): the four-line `_raw_getter`, tombstone translation
   on *every* return path including the single-layer shortcut.
6. **Write sites** (§3), one at a time, each with its test.
7. **`post-install-system-db` and the purge** (§7), then the data-package
   recipe hook in `isabelle-packaging-ci`.
8. **CLI wording** (§9) and deleting `_count_shadowed_user_vectors` (§6).

### 13.2 Where things live (function names, not line numbers)

- `Isabelle_Semantic_Embedding/semantics.py` — `_Semantic_DB` (`__setitem__`,
  `delete`, `update_expr`, `repair_xor_prefixes`, `clean_wip`,
  `mark_interpreted`), `_iter_vector_store_envs`, `Semantic_Vector_Store`
  (`_auto_embed`, `embed_records`, `embed_keys`, `is_thy_embedded`,
  `mark_thy_embedded`, `clean_all_wip_in_created_dbs`,
  `created_embedding_models`), `complete_vector_store`,
  `_collect_embed_candidates`, `lookup`.
- `Isabelle_Semantic_Embedding/semantic_embedding.py` — `Vector_Store`
  (`_raw_getter`, `__getitem__`, `contains`, `embed`, `topk`, `_topk_sync`),
  `_get_lmdb_env`, `_try_system_store_env`, `_decode_q15`, `VECTOR_MAP_SIZE`.
- `Isabelle_Semantic_Embedding/isabelle_semantics.py` — `_execute_removal`
  (behind `cmd_remove` and `cmd_prune`), `_vector_store_paths`,
  `_count_shadowed_user_vectors`, `cmd_fsck`.
- `Isabelle_Semantic_Embedding/experience_store.py` — `put_experience`,
  `delete_experience`.
- `Isabelle_Semantic_Embedding/semantic_interpretation.py` —
  `InterpretationTask.write_answer`, `_answer_tool`.
- `Isabelle_Semantic_Embedding/snapshot_sync.py` — `export`,
  `_check_vector_format`, `validated_system_db`, `install_system_db`.
- `Isabelle_RPC/Isabelle_RPC_Host/rpc.py` — `mk_logger_`, `fork_and_launch__`,
  `_spawn_detached_nt__`; `launcher.py`.
- `isabelle-packaging-ci/conda/data/isabelle-semantic-data/recipe.yaml` — the
  data package (currently `noarch: generic`, deliberately hook-less);
  `Semantic_Embedding/conda/recipe.yaml` shows the both-`.sh`-and-`.bat` hook
  pattern to copy.

### 13.3 Measured numbers (do not re-measure)

- Production store: 110,423 entries / 1.3 GB / 4096-dim; 723 sixteen-byte
  embed-status keys; 97,626 entity keys in a full domain.
- Record-layer consultation in the gather: 67 → 110 ms (**+43 ms**) per 100k
  keys.
- Single-layer closure vs bare bound method: **+1 to +5 ms** per 100k keys.
- LMDB write-transaction commit on ext4/NVMe: **457 µs**; in-transaction delete
  **0.4 µs** per key.
- §7 purge target set: **13.4%** of real vectors (14,689 of 109,700), of which
  14,688 restore from the system vector store at zero cost.
- `embed_cache`: 3-day TTL, 2 GiB cap, measured at 121 entries / 2.1 MB.
- Purge scan over the whole store: 0.22 s.

### 13.4 Decided during implementation

All three were open at the end of the design; all three are now settled.

1. **Circuit breaker** (§8.2): **not added.** `_run_agent` already has one —
   `_MAX_STALLED_RETRIES = 10` gives up after ten consecutive retry rounds in
   which no entry became newly answered, and raises `FatalAgentError` naming the
   entities left uninterpreted. With §8.2's persist-then-mark ordering a failing
   disk lands squarely in that counter (nothing is ever marked answered), so a
   second counter would only duplicate the semantics.
2. **`MDB_MAP_FULL` message** (§8.1): approved verbatim, four lines, and it says
   outright that freeing disk space is not the remedy:

   ```
   [Semantic_Embedding] The vector store for <model> is full: <error>
     store: <path>
   The store has reached the size ceiling this package sets for it
   (VECTOR_MAP_SIZE, currently 16 GiB).  Raising that ceiling is what makes
   room; free disk space is not what is missing.
   ```
3. **The write/open split survives.** Invalidation *write* failures are logged
   and never propagate out of `Semantic_DB.__setitem__`; *open* failures raise.
   They defend different things: at open time the answer was never going to
   reach the record store either (same directory, same filesystem), so raising
   costs nothing and shows the user the fault; at write time raising would
   destroy an LLM answer that cost money and cannot be regenerated, to save one
   stale vector that the log records and §6's fsck check can see.
