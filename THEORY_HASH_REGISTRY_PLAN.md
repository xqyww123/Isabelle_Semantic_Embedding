# Publishing the theory-hash registry

Draft 5, 2026-08-19. This document records the design agreed in conversation on
2026-08-12 and re-verified on 2026-08-19. **Nothing is implemented at the time
of writing; execution was authorized by the user on 2026-08-19**, under two
operating rules that bind the implementer:

- **Every outward publish stops and asks the user first** — the `isabelle-rpc`
  release closing §9 step 1, and the `isabelle-semantic-embedding` release
  after step 3. Code, version bumps and tests proceed without asking; the
  publish itself waits for an explicit go.
- **Commit as each §9 step completes and verifies** — directly on `main`
  (shared working tree, never branch), with the superproject bump, in this
  repository's usual rhythm.

Between those two dates the ground moved twice, and this draft carries the
consequences:

- **The persistent-hash scheme changed** (`Isabelle_RPC` commit `e234b74`,
  2026-08-13): the theory long name is now an input to the digest, so one
  persistent hash can no longer carry two theory long names. That removes the
  case R9 existed for; R9's write-path comparison is **withdrawn** (user
  decision, 2026-08-19), and what survives of it is one sentinel branch in the
  merge rule (§14.6). §3.5 records the old case; §2's R9 entry records the
  supersession.
- **`THEORY_HASH_REKEY_PLAN.md` was executed on `cslh19`** (2026-08-13/14):
  all stores, the registry included, were re-keyed to the new scheme. Every
  figure in §3 was re-measured on 2026-08-19 against the re-keyed stores, and
  the plan's load-bearing claims survived: the registry is complete, and R5's
  gate passes at exactly 100 %.

Draft 4 folded in an adversarial review (five lenses, a refutation turn, a
judge; 21 findings, 4 kept); the corrections it forced live in §7.1, §8.1 and
§9 step 1 and 3, each with its reasoning in place. Draft 5 was reviewed the
same way (26 findings, all refuted); the residue its refutation round exposed
was folded in with the user's approval on 2026-08-19 — §9's one-release rule
and its data-release ordering sentence, §8's kind-of-access wording, and
§14.4's deletion of the old path constants.

**All design questions are closed and the plan is approved.** One prerequisite
sits outside it: `cslh19` must publish its re-keyed database to Hugging Face
(the user is handling this in parallel). The published snapshot still predates
the re-key (§3.7), so its keys are the old scheme's — until the republish,
syncing from it would regress a machine to keys the current code never
computes. §9 steps 1–3 (code, tests, the paused publishes) do not depend on
that republish; only step 4 does.

**If you are here to implement, read §14 first** — it is the handover, written
to be sufficient on its own, and it points back at whichever section carries the
reasoning behind each item. §9 is the order of work; §14.9 lists which measured
numbers are point-in-time and must be re-measured rather than trusted.

Orientation for a reader arriving with no other context: §1 is the glossary,
§2 is the settled decisions (do not reopen), §3 is the measured evidence every
claim rests on, §4 is the problem statement, §5–§9 are the work, §10 is the
open questions, §11 is what was considered and rejected. Citations name
**functions and files, not line numbers** — this is a shared working tree and
line numbers move (the convention `VECTOR_INVALIDATION_PLAN.md`,
`ENTITY_POSITION_PLAN.md` and `SEMANTIC_SEARCH_SITE_PLAN.md` all adopted).

**Relationship to `SEMANTIC_SEARCH_SITE_PLAN.md`**: that plan needs a
hash-to-name table to resolve a name-addressed entity's declaring theory (its
§7.3), and its §12.2 names this plan as **its prerequisite B** — without the
registry, the site's `Theory Name` filter and its export-scope test both fail.
The table already exists and is already complete (§3); this plan publishes it.

## 1. Glossary — canonical names, never paraphrased

| Term | Meaning |
|---|---|
| **the theory-hash registry** | The store mapping a 16-byte theory hash to `[theory long name, unix timestamp]`. Today `~/.cache/Isabelle_Theory_Hash/theory_hash.lmdb`. The name is the codebase's own (`isabelle_semantics.py`'s "not in the theory-hash registry", `_load_theory_generations`'s "the last-touched time the registry keeps per hash"). Never "the name table", "the hash map". |
| **theory hash** | The 16-byte value that prefixes a name-addressed universal key and appears in a theorem-alike record's constituent list. Two schemes, told apart by the low bit of byte 0 (`is_persistent`). |
| **persistent hash** | Low bit of byte 0 is 0. `theory_xxhash128`: clear_lsb of `xxhash128(long name ++ 0x00 ++ file bytes ++ parents' hashes)`, parents contributing under this same scheme. Every input is machine-independent, so every machine computes the same hash; and the long name is among the inputs, so one hash speaks for exactly one name (short of an xxhash128 collision). Publishable. Before 2026-08-13 the name was **not** an input — §3.5. |
| **WIP hash** | Low bit of byte 0 is 1. FNV-1a 128 of the theory's **long name**, minted in ML for a theory not in any heap image. Identifies "what that name refers to in this process", so it means nothing on another machine. Never publishable. |
| **theory-status record** | The value under a 16-byte key in `semantics.lmdb`: the per-theory interpretation ledger (`input_tokens`, `output_tokens`, `cache_creation_tokens`, `cache_read_tokens`, `cost_usd`, `model`, `driver`, and either `finished` or the `process_id`/`serial` pair). Decoded through `unpack_thy_status`. Never "theory record" (that would be confused with an entity record of kind `THEORY`). |
| **the user DB** | The writable database directory, `semantic_DB_dir()`. |
| **the system DB** | The read-only database the user DB layers over: `$PREFIX/share/isabelle-semantic-data/` from conda, or `semantic_DB_dir()/system` from `isabelle-semantics pull`. Located by `find_system_db`, gated by `validated_system_db`. |
| **generation** | One theory hash among several that the registry maps to the same theory long name. A theory acquires a new generation whenever its source (or an ancestor's) changes. `prune` deletes the records of every generation past `--keep`, ordered by the registry's timestamp. |

## 2. LOCKED decisions

All taken by the user on 2026-08-12; R9's supersession on 2026-08-19. Do not
re-litigate; ask before deviating.

- **R1** — **the theory-hash registry moves into the user DB directory**, i.e.
  `semantic_DB_dir()/theory_hash.lmdb`. This is what makes it travel with the
  database: everything that publishes, downloads or merges the database
  operates on that directory (§4).
- **R2** — **the file keeps the name `theory_hash.lmdb`.** The whole code chain
  around it is already spelled `theory_hash` (`Theory_Hash` in ML,
  `theory_hash.ML`, `theory_hash.py`, `open_theory_hash_store`); giving the file
  a different word would make the file and the functions that read it disagree.
  The objection that the name describes the key rather than the contents is
  noted and overruled.
- **R3** — **`semantic_DB_dir()` moves down into `Isabelle_RPC_Host.paths`**,
  and `Isabelle_Semantic_Embedding/_paths.py` becomes a re-export of it. The
  lower package can then resolve the path itself, which removes the need for
  any initialisation-order contract (§5, §11.1).
- **R4** — **the HF development snapshot carries the registry as-is, WIP
  entries included; the conda export filters WIP out.** This matches what the
  two channels already do with tombstones and WIP semantics records: the dev
  tarball ships everything and the export strips what must not ship (the
  `sync-semantic-embedding-db` skill states this for records; R4 extends it to
  the registry).
- **R5** — **the export gains a gate**: the published registry must resolve
  every persistent name-addressed key prefix in the exported `semantics.lmdb`,
  and the export fails loudly otherwise. This is the invariant that machine
  boundaries have been silently breaking (§3.3), so it is the one worth
  enforcing. It passes today at 100 %.
- **R6** — **the vector-completeness gate stays as it is.** The 271 shippable
  records with no vector will be filled before a real publish rather than
  weakening the gate.
- **R7** — **the registry is read layered, the same way `semantics.lmdb` is**:
  user layer first, then the system layer, with a user-layer tombstone reporting
  absent and stopping the fall-through (§8).
- **R8** — **a registry tombstone is the empty value**, reusing the existing
  convention exactly: `is_tombstone` in `semantics.py` is `len(raw) == 0`, and
  it already copes with the memoryviews a `buffers=True` transaction yields.
  The encoding is free of collisions because a legitimate registry value is the
  msgpack of `[theory long name, unix timestamp]`, which is never empty.
- **R9** — *(taken 2026-08-12, superseded 2026-08-19)* — originally: one name
  per hash, and when a persistent hash carried more than one theory long name,
  keep the lexicographically smallest, comparing in both the `Theory_Hash.store`
  write path and `merge_snapshot.py`'s registry branch. Taken when the
  persistent hash did not contain the name and one hash really could carry two
  names (§3.5). The scheme change of 2026-08-13 folded the long name into the
  digest, so that case is no longer constructible, and the user withdrew the
  write-path comparison on 2026-08-19. What stands now:

  **`Theory_Hash.store` stays a blind `put`.** This is safe under the new
  scheme: the key determines the name, so a same-key `put` can only refresh the
  timestamp.

  **The merge rule keeps one sentinel branch** (§14.6): two names on one hash is
  reported loudly and the existing value kept, never overwritten silently. It
  can only fire on an old-scheme leftover or an xxhash128 collision, and that it
  fires at all is the news.

  "One name per hash" — the value format `[long name, timestamp]` — is
  unchanged; it is now simply the truth rather than a resolution rule.
- **R10** — **`cslh19` is the authority.** It finishes its outstanding repairs,
  publishes to Hugging Face, and every machine we care about then syncs from
  there. Only this machine and `cslh19` are in scope; other hosts are not this
  plan's concern. This makes the migration a **single manual step on `cslh19`**
  (§7), not a mechanism.
- **R11** — **`SCHEMA_VERSION` is not bumped**, and — the coupled half, which
  must not be changed alone — **a missing system-layer registry degrades rather
  than failing.** Adding a store is not the silent-misread case the version gate
  exists for; §10 Q4's entry records the full analysis. If the registry ever
  becomes mandatory at read time, the bump becomes mandatory with it.
- **R12** — **the theory long name is NOT added to the theory-status record.**
  Proposed and provisionally agreed earlier on 2026-08-12, before §3.1 showed
  the registry already complete, and withdrawn now that R1 gives that data a
  carrier. A second carrier would be free to ship but not free to maintain: two
  copies eventually disagree — the registry's name is the hash's own (§1), the
  ledger's would be whatever was current when the theory was interpreted — and
  then an authority rule has to be written, implemented consistently in every
  reader, and tested. Redundancy is not worth that.
- **R13** — **this machine's registry is discarded; `cslh19`'s is the only
  source.** It is not migrated and not merged upward; the old file simply stays
  where it is, unread, so the decision is reversible. Measured before taking it
  (2026-08-12, read-only):

  ```
  this machine 3,198 entries (persistent 2,103, WIP 1,095) vs cslh19's 12,920

  persistent entries cslh19 does not have at all            1
      38a9ac7f…  Phi_Examples.Quicksort
  persistent entries cslh19 has under a different name      2
      the two HOL-Statespace / Phi_Statespace pairs of §3.5, where R9's rule
      selects cslh19's name anyway
  WIP entries cslh19 does not have                        207   (by design)

  records in the database prefixed by 38a9ac7f…             0
      no theory-status record, no name-addressed entity
  persistent name-addressed prefixes R5's gate cannot
  resolve from cslh19's registry alone                      0
  ```

  So the one unique entry names a theory that owns nothing in the database — it
  was registered only as an ancestor of something else — and discarding it costs
  nothing measurable. What this machine gains is larger than what it gives up:
  its own registry resolves **715 of its 10,601** persistent theory-status keys
  (6.7 %), `cslh19`'s resolves **10,601** (100 %).

  Re-measured 2026-08-19, after the re-key: this machine's registry has grown to
  **3,851 entries and now mixes old-scheme and new-scheme keys** — only
  `cslh19`'s copy was re-keyed. That strengthens the decision: the old-scheme
  majority no longer matches any key the current code computes. The user
  reaffirmed on 2026-08-18 that `cslh19`'s data is authoritative.

## 3. Measured evidence

Everything here was measured, not assumed: first on 2026-08-12, and again on
2026-08-19 after `cslh19`'s stores were re-keyed to the new hash scheme
(`THEORY_HASH_REKEY_PLAN.md`). Figures below are the 2026-08-19 ones unless a
date says otherwise. Treat any claim elsewhere in this document that is not
here as an assumption.

### 3.1 The registry is already complete — no Isabelle run is needed

`SEMANTIC_SEARCH_SITE_PLAN.md` §7.3 once concluded the table had to be rebuilt
by one enumeration run over Isabelle2025-2 and afp-2026-05-13. That conclusion
was drawn from **this** machine's copy and never checked against `cslh19`, the
machine that did the interpreting. Checked there — and re-checked after the
re-key — the table is complete:

```
cslh19, 2026-08-19 (read-only, post-re-key)

  registry                              11,504 entries; 10,594 persistent;
                                        11,487 distinct theory long names
  semantics.lmdb records walked          1,355,222
  persistent name-addressed prefixes         8,681
      unresolved by the registry                 0   ← R5's gate, at 100.0 %
  persistent theory-status keys             10,561
      in the registry                       10,561   (100.0 %)
```

The registry shrank in the re-key (12,920 → 11,504 entries): the re-key maps
old hashes to new ones by theory name, so several old content generations of
one name collapsed onto that name's one new hash. The completeness survived it
exactly.

This is not luck. `store_theory_hash` walks `Theory.nodes_of` (the root theory
plus every ancestor) at the start of every interpretation run, so the registry
accumulates exactly the theory cones that were interpreted — and the published
snapshot is what those same runs produced. The registry and the records are two
products of one run.

### 3.2 Interpreted implies registered, on the machine that interpreted

Measured on `cslh19` on 2026-08-19: all **10,561** persistent theory-status
keys are in the registry (100.0 %). (On 2026-08-12, before the re-key, the
same held: 10,601 of 10,601; the WIP half — then 817 of 867 — was not
re-measured, because WIP records never ship and `clean_wip` exists to delete
the strays.)

The 100 % is mechanical, not incidental: `store_theory_hash` runs before
interpretation begins (all three call sites — `semantic_interpretation_app.ML`'s
`resolve_roots`, `interpret_command.ML`, and `semantic_store.ML`'s
`make_interpret_theory_callback`), and `mark_interpreted` writes `finished`
after. The order cannot invert.

The correct invariant is **"interpreted ⊆ registered"**, not equality: the
registry also holds entries with no status record at all, which is what
registering a theory's ancestors without interpreting each of them looks like.

### 3.3 The invariant does not survive a machine boundary

The records travel; the registry does not. So the invariant of §3.2 holds only
where the interpreting machine is also the holding machine.

The receiving side, measured on this machine on 2026-08-19: since 18:33 that
day, this machine's `semantics.lmdb` is a copy of `cslh19`'s re-keyed store.
Of its **10,561** persistent theory-status keys, this machine's own registry
resolves **183** (1.7 %) — `cslh19`'s resolves all of them. The records
arrived with the copied store; the names stayed behind.

The defect used to be visible even on `cslh19` itself: on 2026-08-12 it was
missing 8 of its **own** finished theories (`Minilang.Minilang`,
`Semantic_Embedding.Semantic_Embedding`, `Minilang_AoA.Minilang_AoA`, and
others — all interpreted on **this** machine, their status records carried over
by the snapshot). The 2026-08-12 registry merge and the re-key erased that
instance, but the mechanism is untouched: nothing carries the registry across a
machine boundary (§3.4), so every receiving machine holds records it cannot
name.

### 3.4 Neither publication channel carries the registry

- **Hugging Face**: the packaging command is
  `tar --zstd -cf … -C ~/.cache Isabelle_Semantic_Embedding`, which names one
  directory. The registry is at `~/.cache/Isabelle_Theory_Hash/` — a sibling,
  not inside it. Its path comes from
  `platformdirs.user_cache_dir("Isabelle_Theory_Hash", "Qiyuan")`, a different
  application name entirely.
- **conda**: the data release runs `isabelle-semantics export` over that same
  tarball, so it cannot ship what the tarball lacks; and independently, the
  export writes only `semantics.lmdb`, `experience_index.lmdb`, the `vector_*`
  stores and `MANIFEST.json` into its output directory. The single mention of
  `theory_hash` anywhere in `snapshot_sync.py` is
  `from Isabelle_RPC_Host.theory_hash import is_persistent` — it borrows the
  persistence predicate and never touches the store.

### 3.5 One hash, two names — the case that existed until 2026-08-13

Under the pre-2026-08-13 scheme a persistent hash did **not** determine one
theory long name. Merging this machine's registry into `cslh19`'s (2026-08-12)
produced two name conflicts, and they were **not corruption**:

```
da5e1150…  cslh19: HOL-Statespace.StateFun           here: Phi_Statespace.StateFun
f64d5cd2…  cslh19: HOL-Statespace.DistinctTreeProver  here: Phi_Statespace.DistinctTreeProver
```

**Both hashes were persistent** (byte 0 is `0xda` and `0xf6`, low bit 0), so
restricting publication to persistent hashes did not avoid this — it confined
the problem to exactly the scheme that is published.

The cause was that `theory_xxhash128` hashed the file's bytes and its parents'
hashes and **nothing else**. The theory's long name was not an input — it is
the session qualifier from a ROOT file plus the theory's base name, and the
ROOT is not part of the theory file at all.

Verified end to end:

```
contrib/Isabelle2025-2/src/HOL/ROOT                     session "HOL-Statespace" in Statespace = HOL +
contrib/phi-system/…/Statespace/ROOT                    session Phi_Statespace = HOL +
```

Both sessions descend from `HOL`. Both copies of `DistinctTreeProver.thy` are
`imports Main` and byte-identical (`sha256sum`, `diff`); both copies of
`StateFun.thy` are `imports DistinctTreeProver` and byte-identical. So the hash
chain coincides at every step: `DistinctTreeProver` has the same content over
the same parent (`HOL.Main`), and `StateFun` then has the same content over the
same parent hash. Two names, one hash, by construction.

**Fixed at the source on 2026-08-13**: `Isabelle_RPC` commit `e234b74` folds
the long name into the digest (see §1's persistent-hash entry for the layout),
precisely so that one `.thy` loaded under two long names gets two identities,
and `THEORY_HASH_REKEY_PLAN.md`'s migration re-keyed `cslh19`'s stores
accordingly — the two Statespace pairs above now hash apart. R9, which resolved
the ambiguity by convention while it was real, is superseded (§2); what
survives is the sentinel branch of §14.6. This section is kept because the old
scheme's keys still exist in the wild: in this machine's discarded registry
(R13) and in the pre-re-key Hugging Face snapshot (§3.7).

### 3.6 The registry timestamp is load-bearing for a destructive operation

`prune` builds `name -> [(hash, timestamp)]` from the registry
(`_load_theory_generations`), keeps only generations that own records, sorts by
`-timestamp`, and **deletes the records of everything past `--keep`**. The
timestamp is therefore not decorative metadata.

This was checked before the merge of §3.5 was applied. Of the 17 theory names on
`cslh19` with more than one record-owning generation, the merge touched 2
(`Auto_Sledgehammer.Auto_Sledgehammer`, `Performant_Isabelle_ML.Performant_Isabelle_ML`)
and **changed neither one's ordering** — all timestamps shifted together.
`Auto_Sledgehammer` gained one generation. The merge was applied only after that
check.

### 3.7 What was already done, outside this plan

Not part of the plan; recorded so a reader does not redo it, and because the
last item is now this plan's one prerequisite.

- **2026-08-12** — this machine's 2,102 persistent registry entries were merged
  into `cslh19`'s (1,570 writes: 712 new hashes, 858 timestamps, 530 already
  current; the 2 conflicts of §3.5 skipped). `cslh19`: 12,208 → 12,920 entries.
  Undo at `cslh19:~/registry_merge_undo.pkl`. All figures pre-re-key.
- **2026-08-13/14** — `THEORY_HASH_REKEY_PLAN.md` was executed on `cslh19`:
  `semantics.lmdb`, the vector store, `experience_index.lmdb` and the registry
  were re-keyed to the name-folding scheme together, from one theory table. The
  registry went 12,920 → 11,504 entries (old content generations of one name
  collapse onto its one new hash) and stayed at the old path — R1 has **not**
  happened. The pre-re-key registry survives as
  `theory_hash.lmdb.pre-rekey-20260813-170504` beside it.
- **2026-08-18** — `ENTITY_POSITION_PLAN.md` and the key repair
  (`BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md`) completed on `cslh19`
  (`SEMANTIC_SEARCH_SITE_PLAN.md` §12.2, prerequisite A).
- **Still outstanding: the republish.** The Hugging Face snapshot was last
  uploaded 2026-08-11 (`data/manifest.json`), so it **predates the re-key**:
  its keys are the old scheme's. Until `cslh19` publishes, no machine may sync
  from it — the extraction would regress the receiver to keys the current code
  never computes.

## 4. The problem, stated once

The registry is the only place that maps a theory hash to a theory long name.
It is produced as a by-product of interpretation, on the machine doing the
interpreting, into a directory outside the database. The database is then
published, downloaded and merged — and the mapping is left behind every time.

So every machine that holds a database it did not itself interpret cannot name
the theories in it. That breaks three things:

1. the site's theory filter, which needs a name-addressed entity's declaring
   theory (`SEMANTIC_SEARCH_SITE_PLAN.md` D14);
2. `isabelle-semantics status` and anything else that prints a theory name;
3. `prune` and `_try_migrate`, which need the generation relation — the set of
   hashes sharing one theory long name — and can only see the part of it this
   machine happened to load.

R1 fixes the cause rather than the symptom: put the registry in the directory
that already travels.

## 5. Moving `semantic_DB_dir()` down (R3)

`open_theory_hash_store` lives in `Isabelle_RPC_Host`, the lower package
(`Isabelle_Semantic_Embedding` imports it throughout; the reverse never
happens). After R1 it must resolve the user DB directory, whose only correct
resolver is `semantic_DB_dir()` in the upper package — and that function is not
a bare path join: it honours `SEMANTIC_DB_DIR`, which exists because LMDB's
mmap plus POSIX locking corrupts stores on NFS and lustre, so cluster
deployments must redirect it to local disk.

The move:

- `semantic_DB_dir()` goes to **`Isabelle_RPC_Host/paths.py`**. That module's
  subject is already "where things are, in the form this platform wants", it
  imports only `os` and `subprocess` (so a caller can ask for a path without
  pulling LMDB in), and `platformdirs` is already a declared dependency of
  `isabelle-rpc` (`theory_hash.py` imports it today).
- `Isabelle_Semantic_Embedding/_paths.py` keeps its name, its docstring and its
  public function, and becomes a re-export. **Every existing call site keeps
  working unchanged** — the roughly 30 of them include `migrate_*.py`, several
  tests, `Tools/dump_keys.py`, and one inline `python -c` inside
  `.github/workflows/release-conda.yml`, which uses the fully qualified
  `from Isabelle_Semantic_Embedding._paths import semantic_DB_dir`.
- `open_theory_hash_store` then calls it directly. No new configuration point,
  no ordering contract, and no need to touch `resolve_roots`.

The cost, stated plainly: `isabelle-rpc` is separately published
(`pyproject.toml` declares `name = "isabelle-rpc"`, and it has its own conda
recipe), so it comes to own two strings that name a downstream project —
`SEMANTIC_DB_DIR` and `Isabelle_Semantic_Embedding`. Today the lower package
mentions Semantic_Embedding only in comments and one type stub, never
functionally. §11.1 records why this was preferred anyway.

The docstring rule in `_paths.py` — *"nothing may call
`platformdirs.user_cache_dir("Isabelle_Semantic_Embedding", ...)` directly"* —
must be restated to cover both packages. The approved replacement docstring is
§13.1; write it verbatim.

## 6. Publishing the registry

### 6.1 `_store_dirs` must not be extended — this is a trap

`_store_dirs` returns the store directory names of a snapshot, filtering
`e == "semantics.lmdb" or e.startswith("vector_")`. But the export then does:

```python
store_names = {s for s in _store_dirs(cache) if s != "semantics.lmdb"}
for store in sorted(store_names):
    shell = Vector_Store.__new__(Vector_Store)      # treated as a vector store
```

Everything `_store_dirs` returns except `semantics.lmdb` is treated as a vector
store. Adding `theory_hash.lmdb` to it would have the export decode the registry
as vectors — in the very loop whose comment warns that "one missed loop would be
a release leak". **The registry gets its own explicit branch.**

### 6.2 Hugging Face (R4)

Once the registry is inside the user DB directory, the existing packaging
command picks it up with no change, WIP entries and all. The corresponding
extraction and the `sync-semantic-embedding-db` skill's prose need updating to
say the registry now rides along and that a running RPC host must be restarted
afterwards for it too (the same mmap reason the skill already gives).

### 6.3 conda export (R4, R5)

`export` gains a registry branch that copies **persistent entries only** into
its output directory, and the gate of R5. The gate's predicate:

> for every key in the exported `semantics.lmdb` that is longer than 16 bytes,
> is not XOR-prefixed, and whose 16-byte prefix is persistent, that prefix has
> an entry in the exported registry.

Deliberately not in the predicate: WIP prefixes (they do not ship), constituent
hashes of theorem-alike records (worth reporting, but a theorem's associated
theories are its constituent list, which already carries long names inline, so a
missing registry entry there degrades nothing), and the 16-byte theory-status
keys themselves (they are ledger entries, not entities).

### 6.4 `merge_snapshot.py`

The tool that merges a published snapshot into a machine holding more data needs
a registry branch, or the defect of §3.3 simply reappears at merge time. The
rule, extending the one already exercised in §3.7:

- persistent entries only;
- a hash both sides know under the **same** name takes the later timestamp;
- a hash both sides know under **different** names is **reported and left as it
  is** — the sentinel branch of §14.6. Under the post-2026-08-13 scheme this
  cannot happen short of an xxhash128 collision or an old-scheme leftover, so
  it must never be resolved silently;
- undo recorded, as the tool already does for its other stores.

## 7. Migration of the existing stores (R10)

A registry at the old path is not reconstructible from the published database,
so it has to be read once rather than abandoned. Under R10 that is **one manual
step on `cslh19`**, not a mechanism.

### 7.1 Why one step is enough

Scope is this machine and `cslh19` (R10). Both were surveyed on 2026-08-12 and
re-surveyed on 2026-08-19:

```
cslh19        11,504 entries, re-keyed 2026-08-13        ← the authority
this machine   3,851 entries, old and new keys mixed     ← discarded (R13)
```

(This machine's count keeps growing — 3,197 → 3,198 within hours on
2026-08-12, 3,851 by 2026-08-19. A machine that is still being used keeps
producing registry entries, so any argument of the form "we already merged
everything upward" has a shelf life. R13 does not rely on such an argument; it
relies on `cslh19` resolving 100 % of what ships, re-verified post-re-key in
§3.1.)

`cslh19` needs its old-path registry moved into the user DB directory. **This
machine's registry is discarded** (R13), not migrated: everything in it that
matters is already on `cslh19`, and the one entry that is not names a theory
owning no records at all — R13 carries the measurement.

**The review corrected the reasoning here, and it is worth keeping the
correction visible.** Draft 3 said "this machine needs nothing" and argued it
from what this machine *owes* `cslh19` — its persistent entries were merged
upward, its WIP entries must not cross a machine boundary. That argument is
about publishing, and publishing is not the only thing the registry is for:
this machine also *reads* it, and R1 changes where that read looks. The
conclusion survives, but only because of R13's measurement, not because of the
draft-3 argument.

**One consequence to sequence around.** Between R1 landing here and this
machine's first sync of a registry-bearing snapshot, the registry at the new
path is empty. Concretely that is **183 of 10,561** persistent theory-status
keys resolvable today (2026-08-19), falling to **0**, then rising to **all of
them** after the sync — a temporary 1.7 % → 0 % → 100 %. Nothing errors: the
code treats an absent registry as normal. Do not run interpretation here during
that window, because `_try_migrate` would find no candidate for a changed
theory and re-interpret it at LLM cost. The simple discipline is to keep the
two events close together.

The survey also covered the `sg` VPS, which has no registry — and not merely no
store: the parent directory `~/.cache/Isabelle_Theory_Hash` does not exist, nor
does any semantic DB, nor any `*Isabelle*` path under `$HOME`. Recorded because
it shows the shape of the ordinary case: a machine that never interpreted
anything has nothing here, so any code that looks at the old path must treat
absence as normal rather than as an error.

Two hosts named in `~/.ssh/config` — the MBZUAI cluster and `qiyuan-V100` —
could not be reached (the GlobalProtect tunnel is down; the cluster's DNS name
returns NXDOMAIN and both `10.` addresses time out). **Out of scope per R10**,
recorded only so that a future reader knows they were never checked rather than
checked and found empty.

### 7.2 The step itself

On `cslh19`, once: dump the old-path registry, merge it into
`semantic_DB_dir()/theory_hash.lmdb` with the rule of §6.4, leave the old store
in place. The tooling already exists and was exercised on 2026-08-12 (§3.7):
idempotent, with an undo file.

Automatic migration inside the code was considered and is **not** built —
§11.6.

A sentence in the `sync-semantic-embedding-db` skill telling anyone outside this
scope to merge their old registry once was drafted and **dropped** (user
decision, 2026-08-12). Editing a skill needs its own approval in this repository
in any case; do not add it on this plan's authority.

## 8. The layered read (R7, R8)

The user DB layers over a read-only system DB: reads consult the user layer
first, where a tombstone means "absent" and stops the fall-through, then the
system layer (`_raw_for_update`, `_system_get`). After R1, a conda-installed
system DB contains a `theory_hash.lmdb` of its own, while
`open_theory_hash_store` returns exactly one environment with no layering at
all. R7 settles this: the registry is read layered, by the same rule.

What that means concretely, per kind of access (one consumer can perform more
than one kind — `_try_migrate` does both reads below):

- **A point read** (`_try_migrate`'s `txn.get(new_hash)`): user layer, then
  system layer; a user-layer tombstone (R8) answers "absent" without falling
  through.
- **A full scan** (`_load_theory_names`, `_load_theory_generations`, and
  `_try_migrate`'s walk for migration candidates): the union of both layers,
  with the user layer winning per key, and a user-layer tombstone removing that
  key from the result entirely. (A migration candidate found only in the system
  layer is harmless: `_try_migrate`'s migration-source check then reads the
  user-layer `semantics.lmdb` — deliberately, per its own comment, since
  migration copies within the user env — finds nothing, and skips it.)
- **Writes** go to the user layer only, as everywhere else.

One detail for the implementation, a consequence of R7 rather than an open
question: the scan must not yield a system entry whose key the user layer
tombstones.

### 8.1 Where the layered accessor lives

`open_theory_hash_store` returns a single environment and is no longer
sufficient as the only entry point; the layered read needs its own accessor.
Which package holds it is **forced, not free**: the system layer is reachable
only through `validated_system_db`, which lives in the upper package
(`semantics.py`'s `_ensure_system_env` does
`from .snapshot_sync import validated_system_db`), and R3 and §5 exist
precisely to keep the lower package from depending on the upper one. So **the
layered accessor lives in the upper package**, alongside the three readers that
need it (`_try_migrate`, `_load_theory_names`, `_load_theory_generations`), in
the shape `semantics.py` already uses.

The lower package never reads the registry at all: `Theory_Hash.store` stays a
blind `put` (R9's write-path comparison is withdrawn — §2). So R3, R7 and this
section are in no tension. An implementer who reaches for
`validated_system_db` from the lower package has reversed the dependency
direction §5 calls invariant — including by hiding it in a function-local
import.

## 9. Order of work

1. **The lower-package changes — both of them, one release.** In
   `Isabelle_RPC_Host`: move `semantic_DB_dir()` into `Isabelle_RPC_Host.paths`
   (R3), and repoint `open_theory_hash_store` at
   `semantic_DB_dir()/theory_hash.lmdb` (R1's half in this package — §14.4's
   "Where it opens"). Bump `contrib/Isabelle_RPC/VERSION` (it is `0.4.1`
   today) **once** and publish `isabelle-rpc` **once**, with both changes
   aboard.

   One release, not one per change: a floor admits anything at or above the
   version it names, so an `isabelle-rpc` published with only the `paths` move
   would satisfy the step-3 floors while still writing the registry at the
   **old** path — the upper package reads `semantic_DB_dir()/theory_hash.lmdb`,
   the lower one writes `~/.cache/Isabelle_Theory_Hash/`, and one machine holds
   two registries with no error anywhere. One version carrying both changes
   makes that state unrepresentable.

2. The upper-package code: `_paths.py` becomes the re-export with §13.1's
   docstring; the registry gains the layered accessor of §8.1 and the
   tombstone handling (R7 + R8). The write path stays a blind `put` (§8.1).

3. The registry branch in packaging, in `export` with the R5 gate, and in
   `merge_snapshot.py`. Also add `"theory_hash.lmdb"` to
   `_local_db_last_modified`'s whitelist — it selects by name
   (`semantics.lmdb`, `vector_*`, `experience_index.lmdb`) and the registry
   matches none of them, so `isabelle-semantics release`'s only local check
   would stop seeing a registry-only change. Concretely: `cslh19`'s §7.2
   migration writes the registry without touching `semantics.lmdb`, `release`
   sees nothing newer than the published revision, warns about nothing,
   dispatches — and CI then fails the R5 gate on a stale registry.

   **And raise the floors here**, to step 1's exact version, in **both**
   `contrib/Semantic_Embedding/pyproject.toml` and
   `contrib/Semantic_Embedding/conda/recipe.yaml` — they are maintained
   independently — with a comment naming `Isabelle_RPC_Host.paths.semantic_DB_dir`
   and the registry's new location as the reasons, in the style of the recipe's
   existing `Theory_Hash.process_id` comment.

   Why the floors are not optional: `_paths.py` re-exports a symbol that no
   `isabelle-rpc` below step 1's version contains, while both floors are pinned
   today at exactly the published `0.4.1`. The conda solver would satisfy the
   dependency with `0.4.1`, `__init__.py` imports `semantics.py` which does
   `from ._paths import semantic_DB_dir`, and the whole package becomes
   unimportable — every import smoke step in `release-conda.yml` fails on all
   five platforms. CI catches it, so nothing reaches users; the cost is a
   blocked release and a puzzled afternoon. The recipe already records this
   exact failure having shipped once, for `Theory_Hash.process_id`.

   **After this step, `isabelle-semantic-embedding` itself must be published to
   the conda channel before the next data release.** The `release-semantic-db`
   CI installs the channel's package and runs *its* `export`: with the channel
   package unchanged, the next data release would run the old `export` — no
   registry branch, no R5 gate — and `isabelle-semantic-data` would silently
   ship without the registry. This is the `sync-semantic-embedding-db` skill's
   standing ordering rule ("a new `isabelle-semantic-embedding` must be on the
   channel before the first data release that changes format expectations"),
   instantiated.

4. The one-off migration on `cslh19` (§7.2), then `cslh19` publishes, then this
   machine syncs (§7.1's window closes here).
5. Skill and documentation updates.

The release order in one line: publish `isabelle-rpc` (step 1) → raise the
floors and publish `isabelle-semantic-embedding` (step 3) → only then any data
release. Code can land on `main` in any order; releases cannot. Nothing is
blocked by an open question.

## 10. Decisions recorded here, and what remains

Every question draft 1 and draft 2 raised is now settled. Kept in place because
the reasoning is the record:

- ~~Q1~~ (how the registry is read when a system DB is present) — R7, R8, §8.
- ~~Q2~~ (one persistent hash, two theory long names) — first R9, then removed
  at the source by the 2026-08-13 scheme change; §3.5, §11.5.
- ~~Q3~~ (the migration) — R10, §7, §11.6.
- ~~Q5~~ — **`prune` is not changed.** §12.
- ~~Q6~~ — granted and applied on 2026-08-12: `SEMANTIC_SEARCH_SITE_PLAN.md`
  received three correction notes (§3.2, §7.3, D19) and §12.2's step changed
  from *build* to *publish*. That document has since evolved further on its
  own; its §12.2 now names this plan as its prerequisite B.
- ~~Q7~~ (a second carrier for the name) — R12, §11.7.

What genuinely remains is not a design question but a prerequisite: **`cslh19`
must republish** — the repairs themselves (entity positions, the key repair,
the re-key) finished by 2026-08-18, but the Hugging Face snapshot still
predates them all (§3.7). And the shippable records with no vector (271 on
2026-08-12; re-measure, §14.9) must be filled before a real publish (R6).

- ~~Q4~~ — **`SCHEMA_VERSION` is not bumped** (R11). The analysis, verified
  against the code, is kept because R11's coupled half depends on it:

  The version gate exists only on the conda channel. `MANIFEST.json` is written
  by `export` and lives in the system DB or a package payload — **not in the
  user cache**, so the HF development tarball has no manifest and no gate at
  all; an old client extracting a new tarball simply sees a directory it does
  not know.

  The criterion is the one the constant's own comment gives: bump so that "an
  older client refuses a snapshot it would silently misread". `"2"` was bumped
  because an EXPERIENCE's goal patterns moved field, and a pre-`"2"` client read
  a *plausible but wrong* record — patterns dropped, `hit_rate` 0, and
  `_auto_embed` overwriting the vector with the wrong text.

  Adding a store is not that. No existing record's shape changes, and no old
  reader can see the new directory: `_store_dirs` filters to `semantics.lmdb`
  and `vector_*`; `_validate_system_db` only additionally requires
  `semantics.lmdb`; `status` reads `stores["semantics.lmdb"]["entries"]` **by
  name** rather than iterating `stores`, so an extra entry there is invisible to
  it; `_installed_snapshot` reads only `created_at` and `build`.

  The reverse direction holds too: a new client meeting an old system DB with no
  registry falls back to the user layer, which is today's behaviour.

  Cost of bumping anyway: every installed client rejects the whole system DB —
  all ~1.35 M records, not just the registry — for the sake of one added store.

  **This decision is coupled to one other**: it is only sound while a missing
  system-layer registry *degrades*. If the registry ever becomes mandatory at
  read time, that becomes exactly the silent-misread case and the bump must
  happen then. Do not change one without the other. (No conflict with R5: R5 is
  strict about what **we publish**, this is tolerant of what **we receive**.)
## 11. Considered and rejected

### 11.0 Restricting publication to persistent hashes as a fix for §3.5

Proposed on the reasoning that the conda export ships persistent theories only,
and that a WIP hash — being FNV-1a of the long name — determines its name
anyway. Correct about WIP, but it did not help: both conflicting hashes of
§3.5 **were** persistent, so the restriction confined the ambiguity to the
published scheme rather than removing it. Recorded because the reasoning is
sound and someone will retrace it. (The ambiguity itself was later removed at
the source by the 2026-08-13 scheme change — §3.5.)

### 11.1 Injecting the path into `Isabelle_RPC_Host`

Instead of moving `semantic_DB_dir()` down, `Isabelle_RPC_Host.theory_hash`
would gain a `set_store_dir(path)` that `Isabelle_Semantic_Embedding`'s
`__init__` calls with `semantic_DB_dir()`. The dependency direction stays
strictly upper-imports-lower and the lower package never names the upper one.

Rejected because it buys that purity with an initialisation-order contract:
the path must be set before the first `open_theory_hash_store`. Two of the
three ML call sites satisfy it (`interpret_command.ML` and `semantic_store.ML`
both load the package first), but `semantic_interpretation_app.ML`'s
`resolve_roots` calls `store_theory_hash` **before**
`Remote_Procedure_Calling.load ["Isabelle_Semantic_Embedding"]`. An ordering
invariant that is already violated by one of its three call sites will be
violated again, and the failure is silent — a store opened at the wrong path,
data split across two files, no error anywhere. R3 removes the contract instead
of documenting it.

### 11.2 Moving the whole registry into `Isabelle_Semantic_Embedding`

Move `open_theory_hash_store`, the `Theory_Hash.store` RPC handler, and the ML
`store_theory_hash` up, so the lower package stops knowing about the registry
entirely. Cleanest in principle. Rejected on churn: it splits a module that is
currently coherent — `is_persistent` is used across Semantic_Embedding,
`theory_xxhash128` is the hash ML calls over RPC, `theory_name_of` queries the
live runtime, and none of those is about the store — and it moves an ML function
out of `Isabelle_RPC`'s `Tools/` for a benefit that R3 already obtains.

### 11.3 Rebuilding the table by an Isabelle enumeration run

`SEMANTIC_SEARCH_SITE_PLAN.md` §7.3's proposal, and correct as far as it went:
`theory_xxhash128` is a pure function and `Isabelle_RPC/list_theory_hash.py`
with `List_Theory_Hash_App.thy` already enumerates it. Unnecessary: §3.1 shows
`cslh19`'s registry already resolves 100 % of the persistent hashes that ship.
Keep the enumerator — it is the recovery path if a registry is ever lost — but
do not put it in the publication pipeline.

### 11.4 Re-deriving the path rule inside `Isabelle_RPC_Host`

Have the lower package read `SEMANTIC_DB_DIR` and fall back to
`platformdirs.user_cache_dir("Isabelle_Semantic_Embedding", "Qiyuan")` itself,
duplicating `semantic_DB_dir()`. Rejected: `_paths.py`'s docstring explicitly
forbids calling that `platformdirs` path directly, and a second copy of the rule
is free to drift — the failure being two processes on one machine opening two
different registry files, with no error from either.

### 11.5 Storing every name a hash is known by

Change the value from `[long name, timestamp]` to a list of names, so §3.5's
ambiguity is represented rather than resolved. Rejected by the user on rarity
(2 entries of 9,214 at the time), and then made moot by the 2026-08-13 scheme
change: with the name folded into the digest, the count can no longer grow, so
the trade-off will not need weighing again.

The reasoning is kept because it documents what the old scheme cost: set union
is commutative and idempotent, so a list converges with no rule at all, whereas
a pick-one rule (the original R9) had to be written identically in two places;
and `_load_theory_generations` groups a theory's generations **by name**, so
one content's generations recorded under two names were counted as two shorter
histories, which `prune --keep N` then miscounted.

### 11.6 Migrating the old registry automatically

Have the code merge the old path up on its own. The read-path-writes objection
has a clean answer — trigger it from **`Theory_Hash.store`**, which is already a
write transaction and already fires exactly when the registry is due to be
written — so this was the recommendation while the scope included machines that
might hold a registry and could not be reached.

Rejected once R10 narrowed the scope to this machine and `cslh19`. The argument
for automating was that a manual step has to be remembered on every machine;
with two machines, one of which needs nothing (§7.1), there is one step to
remember. A mechanism that runs forever, on every interpretation run, on every
installation, is a poor trade for that.

### 11.7 A second carrier for the theory long name

See R12. The theory-status record would carry the name for free — it covers
9,187 of the 9,189 name-addressed prefixes and already ships — but two carriers
require an authority rule, implemented consistently in every reader and tested,
and the registry alone now suffices.

## 12. `prune` is deliberately not changed

`prune` ranks a theory's generations by the registry timestamp and deletes the
records of everything past `--keep` (§3.6). Publishing the registry changes two
things for it.

First, it stops being half-inert on a receiving machine. Today `thy_hashes_in_db`
sees the system layer's records while `_load_theory_generations` reads only the
local registry, so on this machine `prune` answers "unknown theory (not in the
theory-hash registry, or no records)" for most of the corpus — it can see the
records but cannot name them. After this change it works everywhere, which is
wanted.

Second, on a machine that received the database, the timestamps are the
**publishing** machine's observations, not its own.

**Decision: no code change.** The hazard is not new. `cmd_prune`'s own comment
records it under the deliberately unimplemented `--current-from repl`, a user
decision of 2026-07-28: *"most recently touched" can lie about "current" — run
anything on an old checkout and the OLD content's hash gets a fresh registry
timestamp, so a subsequent store-mode prune would keep the old generation and
offer to delete the main line's.* It was accepted then because the failure needs
an inverted-recency workflow **and** an `--apply` without reading the dry-run
listing, **and** the damage is bounded.

All of those mitigations survive intact except one: the dry run by default, the
per-generation listing with hash/timestamp/verdict, the confirmation prompt, the
pre-apply rolling backup, and deletion being tombstones rather than hard removal.
The one weakened is the human's ability to sanity-check the listing — dates from
another machine's history cannot be judged. That was already the softest of the
three conditions.

Guards considered and not taken: marking entries that came from the **system
layer** is nearly free under R7, but does not help our own case, because the
development sync extracts wholesale into the **user** layer, where an inherited
entry is indistinguishable from a local one; recording the writing machine's
identity in the value is a format change, rejected on the same rarity grounds as
§11.5; and dropping timestamps on receipt would remove the only ordering signal
there is.

What is done instead: the dry-run output gains one sentence saying the
timestamps may be the publishing machine's rather than this machine's. The
approved wording and its placement are §13.2. And if this ever does bite, the fix
is already specified in full in `cmd_prune`'s comment — ask a live Isabelle
session which hash each theory is actually loaded under, and use that in place
of the newest-timestamp rule.

## 13. Approved wording

Both were approved by the user on 2026-08-12. Write them verbatim; changing them
needs the user, not the implementer.

### 13.1 `_paths.py`, replacing the whole module docstring

```python
"""Resolve where the semantic-embedding databases live.

`semantics.lmdb`, the `vector_*.lmdb` stores, `experience_index.lmdb`,
`theory_hash.lmdb`, `embed_cache/`, and `AoA_Collected/` all live under one
directory. It defaults to platformdirs' per-user cache
(`~/.cache/Isabelle_Semantic_Embedding`) but can be redirected with the
``SEMANTIC_DB_DIR`` environment variable.

Why the override exists: LMDB uses `mmap` plus POSIX file locking, whose semantics
are unreliable on networked filesystems (NFS / lustre) and can silently corrupt a
store (``MDB_CORRUPTED: Located page was wrong type``). Point ``SEMANTIC_DB_DIR`` at
a LOCAL disk (e.g. ``/var/tmp/<user>/Isabelle_Semantic_Embedding``) to avoid that.
The databases are a rebuildable cache (restorable from the published snapshot), so a
node-local, non-shared location is fine — the only writer is the single RPC host.

`semantic_DB_dir()` is defined in `Isabelle_RPC_Host.paths` and re-exported here.
It belongs there because `Isabelle_RPC_Host.theory_hash` opens `theory_hash.lmdb`
in this directory and that package does not import this one; both import names
reach the one implementation.

Every cache-path site in BOTH packages routes through it — including the offline
tools `isabelle_semantics.py`, `snapshot_sync` and the `migrate_*` scripts — so the
override moves the whole database set together. Nothing in either package may call
`platformdirs.user_cache_dir("Isabelle_Semantic_Embedding", ...)` directly.
"""
```

Note what it deliberately does not say: nothing about the function having moved,
or about which package used to own it. A reader opening the file needs the rule
and the reason, not the history.

### 13.2 `cmd_prune`, immediately after the generations header

The existing line is

```python
print("Generations (newest first; the newest "
      f"{args.keep} per theory survive):")
```

and the approved sentence follows it:

> (A timestamp is when some machine last loaded that theory. Once the registry
> travels with the database, that machine may be the one that published it
> rather than this one.)

## 14. Implementation handover

Written so that an implementer who has only this file and the repository can do
the work. It repeats a few things said above; that is deliberate.

### 14.1 Paths

```
repo root                 /home/qiyuan/Current/MLML
upper package             contrib/Semantic_Embedding/Isabelle_Semantic_Embedding/
lower package             contrib/Isabelle_RPC/Isabelle_RPC_Host/
lower package ML          contrib/Isabelle_RPC/Tools/theory_hash.ML
upper package ML          contrib/Semantic_Embedding/Tools/
conda recipe (upper)      contrib/Semantic_Embedding/conda/recipe.yaml
release workflow          contrib/Semantic_Embedding/.github/workflows/release-conda.yml
version file (lower)      contrib/Isabelle_RPC/VERSION
dev-sync skill            .claude/skills/sync-semantic-embedding-db/SKILL.md
```

Both packages are separate git submodules of the super-repo, published
separately (`isabelle-rpc` and `isabelle-semantic-embedding`). Commit directly on
`main`; this is a shared working tree used by other agents concurrently.

### 14.2 The registry's on-disk contract

One LMDB store. After R1 it is `semantic_DB_dir()/theory_hash.lmdb`.

```
key     exactly 16 bytes, a theory hash.
        persistent iff key[0] & 1 == 0  (Isabelle_RPC_Host.theory_hash.is_persistent)
value   msgpack of [theory long name : str, last-seen unix seconds : int]
        or b"" — a tombstone (R8), which reads as absent and stops fall-through
map_size  1 << 30, the value open_theory_hash_store uses today; keep it
```

Legacy note that still applies: some values were written with `str` msgpack keys
in other stores; that is a `semantics.py` concern, not this one. This store's
value is a list, not a dict, and needs no normalisation.

### 14.3 `semantic_DB_dir()` moves down, and the release it forces

**Code.** Move the function body from
`Isabelle_Semantic_Embedding/_paths.py` into `Isabelle_RPC_Host/paths.py`
(which today imports only `os` and `subprocess` and defines `platform_path` and
`resolve_isabelle_var`; `platformdirs` is already a declared dependency of
`isabelle-rpc`, imported by `Isabelle_RPC_Host/theory_hash.py`). Replace
`_paths.py`'s body with the re-export and the docstring of §13.1.

**Do not** let `Isabelle_RPC_Host/__init__.py` grow a heavy import for this;
callers should reach it as `from Isabelle_RPC_Host.paths import semantic_DB_dir`
so a caller wanting only a path does not pull LMDB in.

**Release.** One `isabelle-rpc` release carries **both** lower-package changes —
this move and §14.4's "Where it opens" repoint. Bump
`contrib/Isabelle_RPC/VERSION` once, publish once. The floors rise at §9 step 3,
to that exact version, in **both** `contrib/Semantic_Embedding/pyproject.toml`
and `contrib/Semantic_Embedding/conda/recipe.yaml`, with a comment naming
`Isabelle_RPC_Host.paths.semantic_DB_dir` and the registry's new location, in
the style of the recipe's existing `Theory_Hash.process_id` comment. §9 step 1
records why it must be one release and step 3 why the floors are not optional.

**Verify.** `python -c "from Isabelle_Semantic_Embedding._paths import
semantic_DB_dir; from Isabelle_RPC_Host.paths import semantic_DB_dir as g;
assert semantic_DB_dir is g; print(semantic_DB_dir())"`, then again with
`SEMANTIC_DB_DIR=/tmp/x` set. Run the upper package's test suite: the re-export
must keep every existing caller working, and any test that monkeypatches
`Isabelle_Semantic_Embedding._paths.semantic_DB_dir` will now fail to affect the
lower package's own callers — find those and repoint them at
`Isabelle_RPC_Host.paths.semantic_DB_dir`.

### 14.4 The registry moves, and is read layered

**Where it opens.** `Isabelle_RPC_Host/theory_hash.py::open_theory_hash_store`
resolves `semantic_DB_dir()` instead of
`platformdirs.user_cache_dir("Isabelle_Theory_Hash", "Qiyuan")`. Keep the
`reader_check()` call and the `atexit` close — attached RPC hosts die by
`os._exit`/SIGKILL by design and leave stale reader slots.

**The layered accessor** lives in the **upper package** (§8.1). Mirror what
`semantics.py` already does, function for function:

```
_ensure_system_env   opens the system store lazily, or None
_system_get          point read against the system layer
_get_raw             user layer first; a tombstone answers absent and stops
_raw_for_update      the same read inside a write transaction
iter_items           the layered scan
```

Three consumers switch to it, all in the upper package:
`isabelle_semantics.py::_load_theory_names`,
`isabelle_semantics.py::_load_theory_generations`,
`semantics.py::_try_migrate`.

With the switch, **delete** `isabelle_semantics.py`'s module constants
`THEORY_HASH_CACHE_DIR` and `THEORY_HASH_DB_PATH` — after R1 they would keep
naming the abandoned `~/.cache/Isabelle_Theory_Hash/` path, a second source of
truth of exactly the kind §11.4 rejects — and repoint
`test_snapshot_sync.py::_cli_paths`, which monkeypatches
`CLI.THEORY_HASH_DB_PATH` to a non-existent file to force the no-registry case,
at whatever the accessor's seam is instead.

**The write path** (`Isabelle_RPC_Host/theory_hash.py::_store_theory_hashes`)
changes only in where the store opens. It stays a blind `put` — do not add a
read-before-write: under the post-2026-08-13 scheme the key determines the
name, so a same-key `put` can only refresh the timestamp (§2 R9, §8.1).

**Verify.** With no system DB present, behaviour must equal today's except for
the path. With one present, a user-layer entry must shadow a system one, and a
user-layer tombstone must hide a system entry from both the point read and the
scan.

### 14.5 Publication

**Packaging (HF).** Nothing to change: the command tars the whole
`Isabelle_Semantic_Embedding` directory and the registry is now inside it, WIP
entries included (R4). Re-read the skill's exclusion list to confirm no new
exclusion is needed.

**`export`** (`snapshot_sync.py::export`) gains its own branch — **not** an entry
in `_store_dirs`, whose non-`semantics.lmdb` results are all treated as vector
stores (§6.1). The branch copies **persistent entries only** into `outdir`, and
adds `theory_hash.lmdb` to `stores_meta` alongside the others.

**The R5 gate** runs with `_check_no_legacy` and `_check_vector_format`, over
what was actually written. Predicate: for every key in the exported
`semantics.lmdb` that is longer than 16 bytes, is not XOR-prefixed
(`Isabelle_RPC_Host.universal_key.is_xor_prefixed_key`), and whose 16-byte prefix
is persistent, that prefix has an entry in the exported registry. Fail loudly
otherwise. Deliberately excluded: WIP prefixes, constituent hashes, and the
16-byte theory-status keys (§6.3).

**`merge_snapshot.py`** gains a registry branch using §14.6's rule, with undo
recorded as it already does for its other stores.

**`isabelle_semantics.py::_local_db_last_modified`** gains `"theory_hash.lmdb"`
in its name whitelist, or a registry-only change is invisible to
`isabelle-semantics release`'s only local check (§9 step 3).

### 14.6 The merge rule, as an algorithm

Stated in full because the throwaway script that implemented it on 2026-08-12
lives only under `/tmp` on both machines and will not survive. Reuse it for
`merge_snapshot.py`'s branch and for §7.2's one-off migration.

```
for each (key, value) in the incoming registry:
    if not is_persistent(key):            skip          # WIP never crosses a machine
    decode value as [name, ts]
    cur = target.get(key)
    if cur is None:                       put(key, [name, ts])
    else:
        [cur_name, cur_ts] = decode(cur)
        if cur_name != name:              REPORT the pair, keep cur      # sentinel; §2 R9
        elif ts > cur_ts:                 put(key, [name, ts])
        else:                             no-op
```

Properties it must keep: **idempotent** (a second run plans zero writes),
**undo-recorded** (store each key's pre-merge value, `None` for absent), and it
must never delete. The sentinel branch is unreachable under the post-2026-08-13
scheme short of an xxhash128 collision or an old-scheme leftover — that it fires
at all is the news, so the report must be loud, and the merge must not resolve
the pair itself.

For the LMDB read/write, dry-run and undo patterns, `migrate_theory_hash_rekey.py`
(this repository's top level) is the model that survived; the merge rule itself
is authoritative **here**, not there — that script re-keys, it does not merge.

### 14.7 The one-off migration on `cslh19`

On `cslh19` only (R13 discards this machine's): merge
`~/.cache/Isabelle_Theory_Hash/theory_hash.lmdb` into
`semantic_DB_dir()/theory_hash.lmdb` with §14.6's rule, leave the old store in
place, then let `cslh19` publish. This machine then syncs, which closes the
window §7.1 describes.

Nothing may be writing either store during the merge — the same rule as
packaging a snapshot. Stop the RPC host / REPL server first and restart after;
they mmap the stores and would keep serving the old inodes.

### 14.8 Tests

Two suites already cover this ground and are the models to extend rather than
duplicate:

```
contrib/Semantic_Embedding/test_layered_db.py     the layering rules
    test_user_shadows_system_on_point_reads, test_empty_user_reads_come_from_system,
    test_tombstone_masks_system_record, test_no_system_degenerate
contrib/Semantic_Embedding/test_snapshot_sync.py  packaging and export
    test_export_publishes_the_layered_view, test_export_drops_tombstones_and_builds_the_payload,
    test_export_never_ships_a_vector_tombstone
```

What to add, at minimum: the registry's three layered behaviours mirroring the
`test_layered_db.py` cases above; an export test that the registry is written,
carries persistent entries only, and appears in `stores_meta`; a test that the
R5 gate fails when a persistent name-addressed prefix has no registry entry; and
a test of §14.6's rule covering all five branches plus idempotence and undo.

### 14.9 Numbers in this document that are point-in-time

§3's figures were re-measured on 2026-08-19 against `cslh19`'s re-keyed stores.
They move whenever an interpretation run or a migration lands anywhere; before
relying on any of them, re-measure.

- `cslh19`'s registry: 11,504 entries, 10,594 persistent (2026-08-19). R5's
  gate predicate passed at exactly 100 % that day (8,681 persistent
  name-addressed prefixes, 0 unresolved).
- This machine's registry keeps growing (3,851 on 2026-08-19) and mixes
  old-scheme with new-scheme keys; it is discarded either way (R13). On
  2026-08-19 (late afternoon) this machine's `semantics.lmdb` became a copy
  of `cslh19`'s re-keyed store, which is why the "this machine" figures in
  §3.3 and §7.1 describe that copy.
- **The Hugging Face snapshot predates the re-key** (last upload 2026-08-11,
  §3.7). Nothing may sync from it until `cslh19` publishes; any figure about
  "what the snapshot holds" is dead until then.
- R6's vector-less shippable count was 271 on 2026-08-12, **before** the
  re-key and the naming migrations; re-measure it before the real publish
  rather than reusing it.
