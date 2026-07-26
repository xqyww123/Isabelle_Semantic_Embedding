# Layered Semantic DB: system/user layers, universal tombstones, conda-only distribution

Status: **fully approved design, ready for Phase 1** — plan last revised
2026-07-26; §13 is empty. Every "LOCKED" item below was an explicit user
decision — do not re-litigate them, ask before deviating.

## 0. Summary

The semantic database stops being one merged LMDB in `~/.cache` and becomes **two
read layers**:

| Layer | Location | Writable | Delivered by |
|---|---|---|---|
| **system DB** | `$PREFIX/share/isabelle-semantic-data/` (conda) or `<cache>/system/` (pulled) | read-only (`readonly=True, lock=False`) | the `isabelle-semantic-data` conda data package — via the solver for conda users, or installed manually with `isabelle-semantics pull` (§5) |
| **user DB** | `<cache>/` — the existing `semantics.lmdb`, `vector_*.lmdb`, `experience_index.lmdb` | yes (all writes go here, as today) | local work (collection, auto-embed, experiences) |

Reads consult **user first, then system** ("user wins"). Deletion — of any
record kind, resident in either layer — is a **tombstone**: the user DB holds
an empty value `b""` at the key, which the facade reads as "absent, do not
fall through" (L8/L17). There is **no merge step and no automatic download
anywhere on user machines** (L19); updating or installing the system DB is
always an explicit act. The publishing chain has ONE data source and ONE
artifact (L18):

```
dev machine:  manage_data.py update (HF)  →  isabelle-semantics release
                                              (soft sync check + gh workflow run)
GitHub CI  :  download HF cache → export (drop tombstones, build the system
              experience index, stamp the manifest) → validation gates →
              publish isabelle-semantic-data to conda.qiyuan.me
consumers  :  conda users: the solver installs/updates the package
              everyone else: `isabelle-semantics pull` installs the same
              package from the channel into <cache>/system/
```

The 30–60s merge, the post-link hook, `written_at` timestamps, the
`created_at` seed gate, `check_update`, the `push` CLI, the R2 snapshot
object on data.mlml.qiyuan.me, the experience-only suppression set, and the
in-proof automatic download (with its panel heartbeat) are all **cancelled**
(§10).

`<cache>` = `semantic_DB_dir()` (`_paths.py`), honouring `SEMANTIC_DB_DIR` as
before.

**Terminology is fixed (L11):** the two layers are called **system** and
**user** — in code identifiers, CLI output, comments, and docs. The words
"base", "overlay", and "local" must NOT be used as layer names anywhere.

## 1. Locked decisions

| # | Decision | Rationale (short) |
|---|---|---|
| L1 | User wins on key collision; **no per-record timestamps** | in a layered world local work is never destroyed; the residual failure mode ("a key you touched never receives upstream improvements") was explicitly accepted |
| L2 | No merge on user machines; **no post-link hook at all** in the data package | the package ships extracted LMDB stores; reads open them in place; nothing to do at link time |
| L3 | Data package name **`isabelle-semantic-data`** (revised 2026-07-26), payload at **`share/isabelle-semantic-data/`** (the directory follows the package name, matching the `share/isabelle-semantic-embedding` convention) | hard `run` dependency of the `isabelle-ai` metapackage; NOT a dependency of `isabelle-semantic-embedding` (the library stays lean) |
| L4 | Payload = **extracted** stores + `manifest.json` (not a tarball) | conda's own archive compression makes the download size the same; extracted stores are directly openable and hardlink-shared across envs |
| L5 | `r2_sync.py` → **`snapshot_sync.py`**; `R2Error`/`R2Busy` → **`SnapshotError`/`SnapshotBusy`**; `test_r2_sync.py` → `test_snapshot_sync.py` | scope outgrew R2. Clean break, no shim; AoA import sites updated in the same wave |
| L6 | `check_update` deleted, with its `auto_check` / `check_interval_hours` config and the `SEMANTIC_EMBEDDING_AUTO_UPDATE` env var | freshness is explicit: conda users update the package; others re-run `isabelle-semantics pull` |
| L7 | **Distribution topology:** Hugging Face is the ONLY data source (the existing dev-sync tarball via `manage_data.py`); the conda package on conda.qiyuan.me is the ONLY published artifact, consumed by every kind of user; the R2 snapshot object on data.mlml.qiyuan.me is **retired**, along with the entire local R2 client (settings, `r2:` config, `R2_*` env vars, marker, `remote_head`) | one source, one artifact; channel credentials live only in GitHub secrets; the release becomes a reproducible CI job |
| L8 | **Universal tombstones:** EVERY deletion — any record kind, resident in either layer — writes a tombstone: `user_semantics.put(key, b"")` (uniform; no residency check at delete time), plus dropping the key's user-layer vectors and user-index entries. `cmd_remove` therefore truly deletes system-resident records too. A tombstone rides the ordinary shadowing: point reads hit it first and report "absent"; the record-shadow rule sees a user record and hides system vectors for free; merged cursors emit nothing for the key | one mechanism for all kinds; `b""` is unambiguous (valid records are non-empty msgpack); the branch lives once, in the codec/facade |
| L9 | Existing machines keep their current `<cache>` stores as a **fat user DB** — no migration required | user-wins makes a fat user DB behave exactly like today |
| L10 | The backup machinery is deleted | nothing on the user path is destructive: the system DB is reproducible, the user DB is never bulk-written |
| L11 | Layer vocabulary fixed to **system / user** | one pair of words, everywhere |
| L12 | No override env var for the system-DB location | `SEMANTIC_DB_DIR` relocation + monkeypatching cover tests; adding an env var later is compatible, removing one is not |
| L13 | **CLI (revised 2026-07-26):** `push` stays deleted; `pull` is **revived as the manual system-DB installer** — resolve the latest `isabelle-semantic-data` from conda.qiyuan.me's `repodata.json`, download the `.conda`, extract (`zipfile`+`zstandard`), validate, atomically swap into `<cache>/system/`; terminal progress (the `_download` 5% lines), the install file lock (renamed from `.r2_pull.lock`), **no disk preflight** (revised 2026-07-26: `PUSH_MIN_FREE`/`PULL_MIN_FREE` deleted — the preflight guarded the dead merge-into-the-live-DB world; under the atomic swap an ENOSPC is a clean, retryable failure that never touches the live path, so the OS error is reported as-is with a "free space and retry" hint), no incomplete-sentinel (crash ⇒ live path holds old, new, or nothing — the "nothing" window sits between the two swap renames and heals on the next install, see §5; half-extracted temp dirs are cleaned on the next attempt). `release` is the only publish entry point: a SOFT local checklist (warn if the HF tarball looks out of date, allow the user to confirm and proceed) followed by `gh workflow run` | one artifact for everyone; the installer is explicit and terminal-facing, so no panel plumbing; the atomic-swap story guarantees the live path never holds a partial state |
| L14 | **No "canonical model" concept.** The system DB ships vector stores for zero or more models; a model store the system DB lacks runs user-only with on-demand `_auto_embed` fill | layering aligns store-by-store on directory name |
| L15 | Data package version = **`YYYY.MM.DD.HHMM`** (UTC) from `manifest.created_at`, which CI's export stamps at build time; build number defaults 0, bumped only to re-release the same snapshot with fixed packaging | 4-segment versions verified against conda's `VersionOrder`; UTC avoids inversions; the manifest is the single clock |
| L16 | The experience index is **two-layer**: an immutable system index built by CI's export and shipped inside the payload, plus the local user index maintained incrementally as today; queries union both (dedup by uk) | derived data travels with its immutable source; no identity tracking, no invalidation state, no rebuild-on-change |
| L17 | **Tombstones replace the experience suppression set:** `delete_experience` on any uk = the L8 tombstone write. No suppression set, no index-side subtraction: a tombstoned uk still listed by the system experience index dies at record read, which every consumer already checks | the suppression machinery is strictly subsumed by the general mechanism |
| L18 | **Release runs in CI:** the export (tombstone dropping, system-index build, manifest stamping, compacting rewrite) and every validation gate execute on the GitHub runner against the HF download; local machines never produce the published artifact | reproducible, credential-free locally; gates cannot be skipped |
| L19 | **No automatic installation (revised 2026-07-26):** when the layered DB is empty, AoA emits ONE warning per process (wording below, approved) and runs bare — it never downloads. The warning branches on whether the running environment is conda-managed (`os.path.isdir(os.path.join(sys.prefix, "conda-meta"))`): conda → suggest `conda install`; else → suggest `isabelle-semantics pull` | the population needing auto-install does not exist: conda users get the payload as a hard package dependency; dev machines sync via HF; the rest get a one-command manual path |
| L20 | **No local tombstone clearing — anywhere, ever:** no post-release purge, no `prune` command. CI's export is the only place tombstones are dropped | a local tombstone is either working (masking an old system layer) or inert (bounded, harmless) |
| L21 | Concurrent-publish protection = HF's git history | the marker/ETag stale-check died with the R2 client; every HF revision is recoverable; effectively a single-publisher project |
| L22 | **Module rename (2026-07-26):** `semantics_manage.py` → `isabelle_semantics.py` (a module name cannot contain a hyphen); the console command stays `isabelle-semantics` — already registered in `pyproject.toml [project.scripts]`, only the target string changes. Update `manage_script()`'s source-checkout fallback and every in-code mention of "semantics_manage.py"; the `sync-semantic-embedding-db` skill text references it too (user-owned doc, flag on landing) | the installed command and the dev-side file finally share one name |
| L23 | **The vector–record binding invariant (2026-07-26).** A vector served for key `k` must come from the SAME layer as the record currently visible for `k`. The user-layer lazy cache may stand in ONLY when the visible record's own layer ships no vector for the model (L14), and every such cache fill is computed from the visible record's text. All vector behavior — lookup, KNN gather, `_auto_embed`'s notion of "missing", embed-candidate collection, export resolution, and tombstone handling — derives from this invariant rather than restating it locally (§3.2) | the user's root principle ("vector provenance is bound to interpretation provenance"), codified once so every present and future vector consumer inherits it instead of re-deriving per-site rules; assumes same-model-same-text determinism, under which the residency-following order is strictly no-loss |

**Approved empty-DB warning wording (L19), verbatim:**

In a conda-managed environment:

```
No pre-built semantic database is installed on this machine — AoA will run without it. Install it into this environment with:
    conda install -c https://conda.qiyuan.me isabelle-semantic-data
```

Otherwise:

```
No pre-built semantic database is installed on this machine — AoA will run without it. Install it with:
    isabelle-semantics pull
```

## 2. System DB discovery

```python
class SystemDB(NamedTuple):
    path: str
    source: str        # "conda" | "pulled"

def find_system_db() -> 'SystemDB | None'
```

Two layers only; `source` records the delivery channel of the single active
system DB, for `cmd_status` display. **Location is identity** (no `conda-meta`
interrogation for the DB itself). Precedence, first hit wins (a `pulled` copy
under a conda payload is completely invisible):

1. `sys.prefix/share/isabelle-semantic-data` — only with a readable `manifest.json`.
2. `semantic_DB_dir()/system` — installed by `isabelle-semantics pull` (§5).

Validation at facade init: `manifest.json` must carry the expected
`schema_version` / `vector_format` (reuse `_check_manifest`); an incompatible
or unreadable system DB is treated as absent with ONE loud warning. No
identity tracking, no state files (L16 made them unnecessary).

## 3. The read facade

### 3.1 `Layered_Semantic_DB` (semantics.py)

The `Semantic_DB` singleton owns `_user_env` (writable, today's stores) and
`_system_env` (read-only, from `find_system_db()`; None when absent).

- Point reads (`__getitem__`, `__contains__`, `contains` batch): probe user
  first. **A `b""` value is a tombstone → report absent, do NOT fall through
  to system** (L8). Otherwise decode as today; miss → system. This list is
  **exhaustive by audit** (adversarial review, 2026-07-26): every raw
  `txn.get` reader is routed through the facade or given the tombstone guard
  in Phase 1 — `is_thy_interpreted`, `get_many`, `mark_interpreted`,
  `_try_migrate` (semantics.py), `is_thy_embedded`/`embed_tokens_of`, and
  `Interpretation_Task.historical_cost`/`write_cost`
  (semantic_interpretation.py), which read `Semantic_DB`'s env directly.
- Thy-status reads are tombstone-aware too: `unpack_thy_status` treats `b""`
  as absent, and raw-read sites guard with `if not raw:` instead of
  `if raw is None:` — otherwise `remove T` followed by `collect T` (the
  regeneration flow §4 advertises) crashes on the tombstoned status key
  before interpretation starts.
- Iteration: the merged-cursor helper `iter_items(prefix)` — two-way sorted
  merge, user value wins on equal keys, and a user tombstone emits nothing.
  All merged-read call sites move onto it. Raw single-layer scans that must
  keep their own transactions do NOT move; they skip `b""` values before
  decoding instead — namely `_scan_experiences` (stays a USER-layer-only scan
  inside its existing write txn; skipping tombstones also correctly drops the
  uk from the rebuilt user index, per L16), `_migrate_constituent_records`
  (skip `b""` in its XOR scan), and `_try_migrate` (a `b""` thy-status reads
  as "not finished"; a tombstoned theory is never a migration source).
- Writes: unchanged, always user env. Deletions of any kind: tombstone (L8) —
  including the old-key clearance inside re-keying operations
  (`repair_xor_prefixes`): a raw `txn.delete` there would unmask a system copy
  at the old key (found by the 2026-07-26 code review, fixed).
- **Read-modify-write is a fifth operation category** (adversarial review,
  2026-07-26; policy A approved): `update_expr`, `mark_interpreted`,
  `write_cost`, `mark_thy_embedded` — and any future get-then-put — do
  **copy-up-then-modify**: the READ half goes through the layered facade
  (user first, tombstone = absent, then system); the WRITE half lands in the
  user env, **preserving every field the modification does not touch**.
  Concretely: `update_expr` on a system-resident record copies the full
  record up with the new expr (today's silent early-return on a user-env miss
  would drop the update); the thy-status writers merge into the layered
  status instead of starting from a zeroed template, so system-layer
  cost/tokens accumulate onward and `write_cost` must not default `finished`
  to False when the layered status says True. A tombstoned key reads as
  absent: `update_expr` no-ops, status writers start fresh.
- The tombstone branch lives in the codec/facade (plus the enumerated
  guarded sites above); `b""` cannot collide with valid data (records are
  msgpack tuples, thy-status are msgpack maps — both non-empty). `fsck`
  learns to recognise tombstones. Caveat (accepted): downgrading this
  machine to a pre-tombstone library would crash `_decode` on `b""` —
  downgrades are unsupported.
- `semantic_db_is_empty()` / `semantic_db_record_count()`: layered; a valid
  system DB counts as non-empty; counts are an upper bound (shadowed keys and
  tombstones both count — fine for the print-only callers, comment says so).

### 3.2 Vector stores (semantic_embedding.py)

`Vector_Store` gains `_user_env` / `_system_env` per store directory name
(zero or more system stores, L14). All vector behavior derives from the
**vector–record binding invariant (L23)**: a vector served for `k` comes from
the same layer as the record currently visible for `k`; the user-layer lazy
cache stands in only when that layer ships no vector for the model, and every
cache fill is computed from the visible record's text.

Lookup (corollary of L23; the residency-following order fixed after the
2026-07-26 adversarial review — the earlier user-vector-first order let lazy
cache fills permanently shadow shipped system vectors after upstream
re-interpretations):

```
vec(k) = user record visible?   → user_vec(k)   (missing ⇒ _auto_embed from user text)
       | tombstone?             → None          (no vector is served for an absent record)
       | system record visible? → system_vec(k) (store/vector absent ⇒ user cache /
                                                 _auto_embed from the facade text — L14)
```

Corollaries at the other vector touchpoints (same invariant, not restated
rules): `_auto_embed`'s "missing" is judged by this view and refills from the
facade-visible text; `embed` / `complete_vector_store` candidate collection
counts a system-resident key with a system vector as COMPLETE (no user-layer
re-embedding, no wasted API spend); `export` resolves vectors by the same
rule, so the published text–vector pairing equals the local read view; the
tombstone path also really-deletes the key's user-layer vectors. Deleting a
user `vector_*.lmdb` is a safe cache reset.

`topk` keeps its interface; `_topk_sync` opens two read txns (both outliving
the SIMD kernel) and resolves per key as above; the sorted-walk optimization
is preserved. Residual (pre-existing): a stale USER vector for a
user-resident record is still governed by the existing
text-changing-writers-refresh-their-vector discipline.

### 3.3 `Experience_Index` (experience_index.py) — two-layer

- **system index**: `experience_index.lmdb` inside the payload, built by CI's
  export (L16) — immutable, always consistent with the system records.
- **user index**: today's `<cache>/experience_index.lmdb`, incrementally
  maintained; `rebuild_experience_index()` / `cmd_reindex` cover the user
  index only.

Queries union both (dedup by uk); records are then read through the facade,
which yields the right version — or "absent" for a tombstoned uk, at which
point every existing consumer already drops the candidate. Hence **no
index-side deletion mechanism at all** (L17). Accepted imprecision: a
user-modified experience stays listed under its old patterns in the system
index — a false-positive candidate, filtered when its record is read.

Verified facts this rests on (from `_write_memory_tool_logic`): experience
uks are content-addressed (a modification derives a NEW uk); "update" = write
new key + `delete_experience(old)`; that delete is the only experience-update
mechanism (`hit_rate` is query-time computed, never stored). Under L8 the
delete tombstones the old uk regardless of residency, so the superseded
version disappears locally and (via the CI export) from the next published
snapshot.

## 4. Deletion semantics (v1) — per L8

`cmd_remove` tombstones every record of each requested theory (any
residency), drops user-layer vectors and user-index entries, and reports per
theory what happened. `[system]`-only and `[system+user]` theories are
genuinely removable — the deletion reaches the published world at the next
release. `list` reflects tombstoned theories. A removed theory can be collected
again — its interpretation status simply starts fresh (the regeneration flow
§3.1's guards keep working). (Output wording: §14.)

## 5. `snapshot_sync.py` (the `r2_sync.py` rework)

| Piece | Fate |
|---|---|
| R2 client layer: `settings()`, the `r2:` config section, `R2_*` env vars, marker (`.r2_snapshot.json`), `remote_head`, ETag logic, `push_snapshot` | **Deleted** (L7) |
| `export(outdir)` — **lives in `snapshot_sync.py`** (approved 2026-07-26: producer, consumer, format constants and gates of the snapshot artifact share one module; name `export` replaces the earlier "flatten", whose layer-collapse connotation was vacuous on the real input) | The artifact producer, executed BY CI (L18). Five jobs over the input DB (on the runner: the HF cache's user DB, single-layer — iteration goes through the facade, which simply reads it straight): ① omit tombstoned keys everywhere (records AND their vectors; tombstones themselves never ship); ② rebuild the experience index over the output (reusing the `rebuild_experience_index` core, parameterized by src/dst envs — the HF copy's live index is NOT shipped); ③ stamp `manifest.json` (`created_at` = build time, the L15 clock; store stats); ④ compacting rewrite (free pages dropped as a side effect of the key-by-key copy); ⑤ run the gates (`_check_manifest` self-check, `_check_no_legacy`, `_check_vector_format`). ~120–150 lines incl. plumbing. (CI invocation: the `export` subcommand, §15.3) |
| `install_system_db()` — the library function under `cmd_pull` (L13) | resolve the latest `isabelle-semantic-data` from conda.qiyuan.me repodata, **ordering by (conda `VersionOrder`, then `build_number`)**; sha256-verify the download against repodata → download the `.conda` (terminal progress via `_download`; phases `downloading` / `extracting` / `installing`) → extract the payload subtree in a temp dir beside `<cache>` (same filesystem, so the swap renames are atomic) → validate manifest → swap: `rename system → system.old` (if present), `rename temp → system`, `rmtree system.old` → **record the installed build number as a `build` field in the pulled copy's `manifest.json`** (written and read only by `pull`; never by `find_system_db`/the facade; the "Already current" short-circuit compares (version, build), absent build = 0, `--force` overrides). Under the install lock `.install_system_db.lock` (`filelock`, non-blocking; renamed from `.r2_pull.lock`, named after the function that holds it); no disk preflight (L13 — ENOSPC aborts cleanly, live path untouched, rerunnable). **Crash states are self-healing** (adversarial review 2026-07-26): crash ⇒ live path holds old, new, or nothing — "nothing" only between the two swap renames, an ordinary no-system state; `system.old` sits OUTSIDE the auto-cleaned temp namespace and is touched only by the next install, which first heals leftovers: `system.old` present + `system` absent ⇒ restore (`rename system.old → system` — it is the sole surviving copy); `system.old` present + `system` present ⇒ discard the leftover. Half-extracted temp dirs are rmtree'd on the next attempt. On Windows an open LMDB handle in a live RPC host blocks the rename-out: catch the `PermissionError` and emit the scripted §14 in-use error (old DB fully intact). `PUSH_MIN_FREE`/`PULL_MIN_FREE`/`_require_disk`/`_free_bytes` are deleted with the operations they served |
| `merge_env`, `_merge_snapshot`, `_keep_local_thy_status`, `MERGE_BATCH`, `_backup`, `.pull_incomplete` sentinel, `check_update` | **Deleted** (as previously locked) |
| `semantic_db_is_empty` / `semantic_db_record_count` | layered (§3.1) |
| `find_system_db`, `_check_manifest` et al. | as §2 |
| `R2Error` / `R2Busy` | renamed `SnapshotError` / `SnapshotBusy` (L5) |

**`isabelle_semantics.py`** (renamed from `semantics_manage.py`, L22; the
console command `isabelle-semantics` is unchanged). The system/user
distinction surfaces ONLY as display and guards (no `--repo` addressing):

- `pull`: the manual system-DB installer (L13, above). **Guard (approved
  2026-07-26):** refuse when `find_system_db().source == "conda"` — the
  pulled copy would be shadowed by the conda payload (§2 precedence), so the
  download could never be read; point the user at
  `conda install -c https://conda.qiyuan.me isabelle-semantic-data`. The
  guard reuses the reader's own discovery probe, so it cannot disagree with
  what the facade would actually select (no env-type heuristics). In a conda
  environment WITHOUT the payload, `pull` proceeds (nothing shadows it), with
  a one-line note that a future package install takes precedence;
- `release`: the soft checklist (L13) — warn when the local cache and the HF
  tarball look out of sync, user confirms to proceed — then `gh workflow run`
  (graceful fallback: print the manual dispatch command);
- `status`: system layer (source, path, `created_at`, records) + user layer
  (records, tombstones). The two user-layer numbers come from ONE cursor scan
  of the user semantics env (records = entries − tombstones) — distinct from
  `semantic_db_record_count()`'s cheap upper bound, which keeps its §3.1
  semantics;
- `list`: residency tags incl. tombstoned state (wording: §14);
- `remove`: per §4;
- `fsck`: user DB by default; `--system` read-only report; recognises
  tombstones; report-only lines for the user-DB tombstone count (same
  single-scan mechanism as `status`) and for user-layer lazy vectors that the
  L23 binding rule currently shadows (disk-usage diagnostics, approved
  2026-07-26);
- `export OUTDIR`: the CI/offline wrapper of `snapshot_sync.export`
  (approved subcommand form; terminal wording to be drafted for approval when
  Phase 2e wires it);
- `collect` / `reindex`: layer-unaware;
- `embed`: candidate collection follows L23 (§3.2) — system-covered keys are
  complete, not candidates.

## 6. The AoA hook

`_ensure_semantic_db` (AoA `toplevel.py`) simplifies to a pure check:

```
layered DB empty (no valid system DB, user DB empty)?
  → yes: emit the L19 warning (once per process), run bare
  → no:  proceed (zero work, zero output)
```

No download, no heartbeat, no blocking — the in-proof auto-install path
(including the previously shipped "Downloading it now (~0.7 GB…)" message and
the `_DB_PULL_HEARTBEAT_SECS` panel loop) is retired (§10). `check_update`
call site deleted; imports renamed (L5).

## 7. Packaging & CI (isabelle-packaging-ci + this repo)

- **New workflow `release-semantic-db.yml`** (isabelle-packaging-ci,
  `workflow_dispatch`): download the HF cache tarball (HF token in GitHub
  secrets) → run the library's `export` (L18) → rattler-build the
  `noarch: generic`, hook-less, dependency-less data package (version from
  the manifest, L15) → verify → publish to conda.qiyuan.me (`CONDA_R2_*`
  secrets, as every other package).
- `isabelle-ai`: add `- isabelle-semantic-data >=<first YYYY.MM.DD>` to
  `run:`, AND a payload-present assertion to its `tests:` (approved
  2026-07-26; end-to-end check of the dependency edge + payload path):
  `test -f "$PREFIX/share/isabelle-semantic-data/manifest.json"` (with the
  Windows equivalent) — cheap in frequency, since release-isabelle-ai is
  manual-dispatch only. In the same edit, raise
  `isabelle-minilang >=<first L19-warning version>` (adversarial review
  2026-07-26: the L5 rename makes minilang↔embedding version skew a hard
  `by aoa` ImportError in both directions; the metapackage's own doctrine —
  raise a floor only when the pair genuinely stops working below it — applies
  exactly here).
- `isabelle-semantic-embedding` recipe: delete the post-link R2 pull (keep
  the component registration), its `PULL_HINT`/`PULL_WARN` strings and the
  `SEMANTIC_EMBEDDING_SKIP_POSTLINK_PULL` escape hatch; update the recipe's
  in-script assert block (invert: die if the hook DOES fetch the DB). Plus
  four rename-coupled/stale surfaces the review found in the same file:
  (a) the `entry_points` line retargets to
  `Isabelle_Semantic_Embedding.isabelle_semantics:main` (the conda-generated
  wrapper is the ONLY live launcher in a conda install — the build script
  deletes pip's); (b) the `tests:` module-import command replaces `r2_sync`
  with `snapshot_sync` and drops `boto3` from the dependency-import command;
  (c) `- boto3` is deleted from the recipe run deps AND from pyproject.toml
  (every consumer dies with the R2 client); (d) `about.description`'s data
  paragraph is rewritten to the conda-package / `isabelle-semantics pull`
  story (no R2, no post-link fetch, no in-proof auto-fetch). The
  `release-conda.yml` CI edits ride along: drop the
  `SEMANTIC_EMBEDDING_SKIP_POSTLINK_PULL` settings and the verify job's
  "DB arrived" assertion.
- Isa-Mini's conda recipe (Phase 3): raise its floor to
  `isabelle-semantic-embedding >=<first snapshot_sync version>` (same skew
  argument, other direction).
- Release ordering (Phase 4): publish the new `isabelle-semantic-embedding`
  (conda + PyPI together, per the recipe's mandatory release discipline) and
  the new `isabelle-minilang` before or with the first `isabelle-semantic-data`
  release; the retired R2 object is not deleted until the floor-raised
  packages are on the channel (old deployed clients keep auto-pulling the
  frozen snapshot until they upgrade).
- Docs: `conda clean` reclaims superseded data-package versions; a data
  package upgrade needs the usual RPC-host restart (mmap pins the old inode).

## 8. Concurrency & failure notes

- System env: `readonly=True, lock=False`; user env: unchanged singleton
  discipline; the facade owns both as process-wide singletons.
- `pull`'s swap vs a live RPC host: on POSIX the mmap pins the old inode
  until restart and the swap proceeds; **on Windows** the live host's open
  LMDB handles block the rename-out — `install_system_db` catches the
  `PermissionError` and emits the scripted §14 in-use error (old DB fully
  intact; stop the host and retry). The swap runs under the install file
  lock either way.
- A system DB corrupt beyond the manifest gate degrades to user-only with one
  warning, never a crash loop.

## 9. Testing

`test_snapshot_sync.py` (renamed) + new `test_layered_db.py`; synthetic small
stores:

1. Facade: user shadows system; merged-cursor iteration; empty-user /
   no-system degenerate cases (no-system behavior byte-identical to today).
2. Tombstones: point read reports absent without falling through; iteration
   emits nothing; system vectors hidden; user vectors and user-index entries
   dropped; tombstoning a user-only key equals deletion; a tombstone whose
   key the system layer lacks is inert.
2b. Tombstones vs raw readers (adversarial review 2026-07-26): `remove T`
   then `collect T` runs to completion; with a tombstoned experience, a
   tombstoned theorem record, AND a tombstoned thy-status key in the user
   layer, `cmd_reindex`, `fsck --fix`, and collection with
   `migrate_on_hash_change` all complete, and the rebuilt user index omits
   the tombstoned uk.
2c. Read-modify-write on system-resident keys (policy A): `update_expr` on a
   system-only record lands the full modified record in the user layer;
   `mark_interpreted`/`write_cost` preserve and continue system cost/model
   fields (never a zeroed template, never finished=False over a layered
   True); both no-op/start-fresh on tombstoned keys.
3. `find_system_db` precedence + manifest gate (fixtures: `SEMANTIC_DB_DIR`
   relocation + `sys.prefix` monkeypatch).
4. Two-layer experience index: union + dedup; tombstoned uk dies at record
   read; `cmd_reindex` touches only the user index.
4b. L23 corollaries: a system-resident record with both a system vector and
   an older user cache-fill vector ⇒ `topk` serves the system vector;
   `embed`/`complete_vector_store` candidate collection excludes
   system-covered keys; export's published text–vector pairing equals the
   local read view.
5. export: output contains no tombstoned keys and no tombstones (records and
   vectors); system experience index present and consistent with the output
   records; manifest stamped; gates run.
6. `install_system_db` / `cmd_pull`: repodata resolution ordered by
   (VersionOrder, build_number); `.conda` extraction; injected failure at
   EACH step boundary (including between the two swap renames) ⇒ the live
   path holds the old DB, the new DB, or nothing — never a partial store;
   the user DB is unmodified; a retry converges to the new DB (incl. the two
   `system.old` healing rules) and leaves no stray dirs; "Already current"
   compares (version, build); lock exclusion.
7. `remove` (§4) incl. system-resident deletion visible as absent afterwards.
8. AoA `test_ensure_semantic_db.py`: rewritten — empty ⇒ one warning per
   process with the right variant (conda-meta probe), run bare; DB present ⇒
   silence.

## 10. Superseded designs (do not implement, do not resurrect)

From earlier rounds of this same conversation: per-record `written_at`
timestamps (+ newer-wins merge + vector winner-set); the `created_at` seed
gate and manifest peek; `find_bundled_snapshot`/`seed` (+ the data package's
post-link hook and its exit-0 discipline); `pull_snapshot(from_file=…)`; the
three drafted AoA seed-flow panel messages; the R2-merge `pull` and its
conda-guard; the `push` CLI and the R2 snapshot object / marker / ETag
machinery; the `SEMANTIC_DB_BASE` override env var; the whole-theory `remove`
refusal AND the revert-to-system remove (both superseded by universal
tombstones); the experience-only suppression set with its 32-byte
length-discriminated keys; the `.system_db_identity.json` identity file and
rebuild-on-change; base/overlay vocabulary; single-env LMDB consolidation
(named sub-DBs for everything — REJECTED; a main-DB-as-registry restructure
remains a candidate follow-up AFTER the facade lands, as a separate approved
phase); local tombstone purging and the `prune` command; **in-proof automatic
installation of the system DB** — both the already-shipped R2 auto-pull in
`_ensure_semantic_db` (its "Downloading it now (~0.7 GB…)" message and panel
heartbeat loop retire with it) and the briefly planned channel-sourced
bootstrap; the `"downloaded"` source tag (now `"pulled"`). The
`_progress`/`on_step` transfer-progress mechanism survives where it always
lived — `_download` — now serving `pull`'s terminal output.

## 11. Rollout order

1. **Phase 1 (this repo):** `git mv r2_sync.py snapshot_sync.py` + exception
   renames + imports (incl. `semantics_manage.py` → `isabelle_semantics.py`,
   L22 — the rename-coupled recipe pair rides this commit: the recipe
   `entry_points` retarget and the `tests:` module-import swap, §7, so the
   recipe is never internally inconsistent mid-rollout); the read facade (§3)
   including tombstone codec semantics, the raw-reader guards and
   single-layer-scan tombstone skips (§3.1), the RMW copy-up category
   (§3.1), and the L23 vector resolution (§3.2), with tests — behavior with
   no system DB and no tombstones must be byte-identical to today.
2. **Phase 2 (this repo):** `snapshot_sync` rework (§5): deletions (R2
   client, merge, backup, sentinel, check_update, push),
   `find_system_db`, `install_system_db` + `cmd_pull` (incl. the swap
   healing rules and build-number short-circuit), `export`, layered
   emptiness; `isabelle_semantics` surfaces (`release`, `status`, `list`,
   `remove`, `fsck`); full test suite.
3. **Phase 3 (Isa-Mini):** `_ensure_semantic_db` reduction to the L19
   warning + import renames + the Isa-Mini recipe floor raise
   (`isabelle-semantic-embedding >=<first snapshot_sync version>`, §7), one
   Bump-Semantic_Embedding commit.
4. **Phase 4 (isabelle-packaging-ci + conda/):** `release-semantic-db.yml`,
   `isabelle-ai` dependencies (data floor + minilang floor raise) and its
   payload test, the remaining embedding-recipe cleanup (hook surgery, boto3
   removal, about.description rewrite, release-conda.yml edits — §7), the
   release-ordering rule (§7).

## 12. Decision log

2026-07-22: system/user terminology; version encoding; L16 two-layer index;
record-shadow; backup deletion; exception renames; (superseded since:
remove-reverts, suppression set, R2-merge pull deletion).
2026-07-26: universal tombstones (L8/L17); HF sole source + CI-built artifact
(L7/L18); `push` deleted, `release` soft-checklist entry (L13); no local
tombstone clearing (L20); HF-history concurrency (L21); **automatic
installation cancelled — warning only, wording approved verbatim (L19)**;
**`pull` revived as the manual channel-sourced installer with the
atomic-swap/lock details (L13)**; **package renamed
`isabelle-semantic-data`, payload path follows (L3)**; **module renamed
`isabelle_semantics.py`, command name unchanged (L22)**; disk preflight
deleted (L13); recipe changes + L2 no-hooks finalized; `export` named,
scoped, and homed in `snapshot_sync.py`; `pull` conda-guard + L19
`conda-meta` probe approved.
2026-07-26, adversarial-review amendments (32-agent two-turn debate; 27
concerns, 16 killed, 7 survived — all fixed as plan amendments, none
reversing a locked decision): tombstone guards for raw readers and
single-layer scans (§3.1); RMW copy-up-then-modify with metadata
continuation, policy A approved (§3.1); L23 vector–record binding invariant
with residency-following lookup, embed-candidate and export corollaries, and
the fsck shadowed-vector diagnostic (§3.2, §5); version-floor raises and
release ordering (§7); swap crash-state completion, `system.old` healing
rules, Windows in-use error (§5, §8, §14); build-number-aware "Already
current" (§5); four rename-coupled recipe surfaces + boto3 removal (§7).
2026-07-26, reliability audit (SEMANTIC_DB_PLAN_AUDIT.md; seven-lens
cross-consistency review after implementation began): prune-user removed
(mentioned but never designed); 11 documentation defects fixed with zero code
rework — dead §13 references, the never-existing `INSTALL_MIN_FREE` name, the
conda-meta probe unified to `isdir`, the dispatch `-f version=` input dropped
(CI stamps the version), the `export` subcommand added to the CLI surface,
the §15.5 import-breakage sentence corrected, §4's re-collect sentence added,
the install lock named `.install_system_db.lock` (approved), the
status/fsck tombstone-count single-scan mechanism (approved), the
"(version, build)" short-circuit label, and the retired-domain mention.

## 13. Pending approvals

**EMPTY as of 2026-07-26.** Every design point in this plan — including the
seven adversarial-review amendments (§12) and all CLI wording (§14) — is
explicitly user-approved. The `*` non-persistent suffix in `list` stays
as-is (legend deferred, non-blocking). Implementation may begin at Phase 1
(§11). Interim approvals were logged here during review; the full record now
lives in §12.

## 14. Approved CLI wording (verbatim; approved 2026-07-26)

The L19 empty-DB warning is recorded in §1. Everything below is final — do
not rephrase while implementing.

### `release`

Out-of-sync soft check (dates are live values):

```
The local database looks NEWER than the last Hugging Face upload
(local last modified 2026-07-26 14:02; HF revision from 2026-07-25 09:31).
The release publishes the HF state — your local changes would NOT be included.
Run `manage_data.py update` first to include them.

Release the HF state anyway? [y/N]
```

In sync / confirmed, the real-or-dry question (approved 2026-07-26; the
workflow's `dry_run` input DEFAULTS TO TRUE, so the flag is explicit both ways):

```
Publish for real? [y/N]  (N = dry run: CI builds and validates, nothing is published)
```

y → `Dispatching the release workflow (release-semantic-db)...` then
`Dispatched.` (dispatched with `-f dry_run=false`); N →
`Dispatching the release workflow (release-semantic-db, dry run)...` then
`Dispatched (dry run; nothing will be published).`  Without `gh`:

```
`gh` is not available; dispatch manually:
    gh workflow run release-semantic-db --repo xqyww123/isabelle-packaging-ci -f dry_run=false
(dry_run=true builds and validates on CI without publishing)
```

### `status`

```
system : conda   /opt/conda/envs/isa/share/isabelle-semantic-data
         snapshot 2026.07.22.1430 (created 2026-07-22 14:30 UTC), 138,412 records
user   : /home/qiyuan/.cache/Isabelle_Semantic_Embedding
         3,214 records, 17 tombstones
```

No system layer: `system : (none — install with the isabelle-semantic-data
package or `isabelle-semantics pull`)`.

### `list`

New `Layer` column: `system` / `user` / `system+user` / `removed` (all
records tombstoned). The Status column values become **`complete` /
`partial`** (replacing done/WIP; same `b"finished"` flag underneath; a
`removed` theory shows `—`). The non-persistent `*` suffix is unchanged.
The same complete/partial vocabulary applies anywhere else this flag is
displayed.

### `remove`

Existing summary → confirm structure kept; result lines:

```
Removed 2 theories (124 records tombstoned; vectors and index entries dropped).
Note: system-resident records are now masked locally; they drop out of the
published snapshot at the next release.
```

The Note prints only when ≥1 target had system-resident records.

### `fsck`

Under `[report only]`:

```
  tombstones in the user DB                        17
  user-layer vectors shadowed by the system DB    142   (safe to ignore; disk only)
```

### `pull`

Normal flow:

```
Resolving the latest isabelle-semantic-data from https://conda.qiyuan.me ...
Found isabelle-semantic-data 2026.07.22.1430 (0.71 GiB).
  download:  45%  (0.32 GiB)
  extracting...
  installing...
Installed isabelle-semantic-data 2026.07.22.1430 (138,412 records)
to /home/qiyuan/.cache/Isabelle_Semantic_Embedding/system.
Restart any running RPC host / REPL server to pick it up.
```

Already current ((version, build) short-circuit, `--force` overrides):
`Already current: installed snapshot 2026.07.22.1430 matches the channel.`

Conda-guard refusal (L13):

```
Error: a conda-managed system DB is installed at
  /opt/conda/envs/isa/share/isabelle-semantic-data
and would shadow the pulled copy. Update it with:
    conda install -c https://conda.qiyuan.me isabelle-semantic-data
```

Conda environment without the payload (proceeds, one note):
`Note: this is a conda-managed environment; installing the
isabelle-semantic-data package is the recommended path. A package install
will take precedence over this pulled copy.`

Disk full:
`Error: [Errno 28] No space left on device. Free space and retry — the
previous system DB (if any) is untouched.`

System DB in use (Windows, live RPC host blocks the swap rename):

```
Error: the current system DB is in use by another process (a running RPC
host or REPL server) — stop it and retry. The previous system DB is
untouched.
```

## 15. Implementation dossier — facts a fresh session needs

Everything below was established (and where noted, EXECUTED/verified) during
the design conversation of 2026-07-22..26. Trust it; re-verify only what is
marked unverified.

### 15.1 Verified code facts

- `msgpack.unpackb(b"")` RAISES — verified by execution. This is why every
  raw reader needs the §3.1 guards.
- `_Semantic_DB._decode` pads short tuples to 8 with None and slices
  `vals[:8]` — length-tolerant both directions (why tombstones and any future
  trailing field need no SCHEMA_VERSION bump).
- Experience uks are content-addressed:
  `xor_theory_prefix(constituents) + bytes([EntityKind.EXPERIENCE]) + xxh128(name\0patterns\0desc\0body)[:15]`
  (`_write_memory_tool_logic`, mcp_http_server.py). An experience "update" =
  write NEW key + `delete_experience(old)`; that delete is the system's ONLY
  experience-update mechanism. `hit_rate` is computed at query time
  (`_experience_hits`), never stored.
- `topk(query, domain, k)` takes an explicit `domain: list[key]` — KNN is a
  per-key gather (`_topk_sync`: sorted keys, `txn.get` each, SIMD kernel over
  gathered addresses inside the live read txn), NOT a full-store scan.
- `experience_index.lmdb`: main DB only; keys = bare 16-byte theory hashes
  (or `_GLOBAL` = 16 zero bytes), values = msgpack list of 32-byte experience
  uks. Opened without `max_dbs`.
- Vector stores mix 16-byte embed-status keys with 32/33-byte vector keys;
  `_check_vector_format` skips `len(key)==16`.
- conda `VersionOrder`: 4-segment versions parse; segments compare
  numerically; missing segments pad 0; `07`==`7` — verified against the
  installed conda.
- `pyproject.toml [project.scripts]` already has
  `isabelle-semantics = "Isabelle_Semantic_Embedding.semantics_manage:main"`
  (L22 only retargets the string). The conda recipe duplicates it in
  `entry_points` and deletes pip's wrapper at build (§7).
- conda-env detection: `os.path.isdir(os.path.join(sys.prefix, "conda-meta"))`
  — filesystem truth, activation-independent (`CONDA_PREFIX` is unreliable
  for directly-spawned processes). A venv over conda python has no
  conda-meta at ITS sys.prefix — consistent with `find_system_db` probing
  the same sys.prefix.
- Cloudflare fronts conda.qiyuan.me: keep the `_USER_AGENT` header discipline
  from the old `_http` (bare `Python-urllib` UAs get 403).

### 15.2 Work ALREADY LANDED this session (do not redo; partly to be retired)

- `_ensure_semantic_db` (AoA toplevel.py) currently: takes `connection`,
  has `_warn`/`_writeln` best-effort panel helpers, auto-pulls from R2 with a
  10s heartbeat (`_DB_PULL_HEARTBEAT_SECS`) showing download progress.
  Phase 3 REPLACES all of it with the L19 warning-only check. Its tests
  (`test_ensure_semantic_db.py`, 8 passing, `_Conn` stub with
  (channel, msg) records) are REWRITTEN per §9.8.
- `r2_sync.py` currently has `_progress(label, total, on_step=None)` firing
  on_step per chunk, and `_download(..., on_step)`; `pull_snapshot` feeds
  phase strings like "downloading 46% (315.0 MiB of 717.2 MiB)".
  `_download`+`_progress` SURVIVE (terminal progress for the new pull);
  the on_phase plumbing dies with the auto-install.
- `test_r2_sync.py`: 35 passing today; the sha256/OnStep-related tests added
  this session ride the rename.

### 15.3 The HF source (for `release` and CI)

- Tool: `/home/qiyuan/Current/MLML/manage_data.py`; manifest
  `data/manifest.json`; HF dataset repo **`ANTPG/MLML-data`**; the semantic
  DB entry is `contrib/Semantic_Embedding/Isabelle_Semantic_Embedding.tar.zst`
  (~0.76 GB, group "optional") — a tar.zst of the whole cache dir (the fat
  user DB, tombstones and WIP included).
- CI (`release-semantic-db.yml`) downloads exactly that file with
  `huggingface_hub` + an `HF_TOKEN` GitHub secret, extracts it, points
  `SEMANTIC_DB_DIR` at the extraction, and runs
  `isabelle-semantics export <outdir>`.
- `release`'s soft sync check (mechanism, delegated): compare the HF file's
  `last_modified` (`HfApi().list_repo_files`/`repo_info` on ANTPG/MLML-data)
  against the max mtime of the local `<cache>` store files; local newer ⇒
  the §14 warning + confirm. Unverifiable (offline/API error) ⇒ say so and
  ask the same confirm. Then `gh workflow run release-semantic-db
  --repo xqyww123/isabelle-packaging-ci` — no inputs: the version is stamped
  by CI's export from `manifest.created_at` (L15), so dispatch has nothing to
  pass (§14 fallback line when `gh` is absent).

### 15.4 repodata / .conda mechanics (for `install_system_db`)

- Channel index: `GET https://conda.qiyuan.me/noarch/repodata.json`
  (anonymous; UA header per §15.1). Entries live under `"packages.conda"`
  (and legacy `"packages"`); filter `name == "isabelle-semantic-data"`,
  order by (version as int-tuple — L15 guarantees pure numeric segments —
  then `build_number`), take the max. Download URL =
  `https://conda.qiyuan.me/noarch/<filename>`; verify `sha256` from the
  entry.
- A `.conda` is a ZIP containing `metadata.json`,
  `info-<name>-<ver>-<build>.tar.zst` (ignore), and
  `pkg-<name>-<ver>-<build>.tar.zst` — the payload tree rooted at
  `share/isabelle-semantic-data/...`. Extract: `zipfile` → open the `pkg-*`
  member as a stream → `zstandard` stream decompressor → `tarfile` mode
  `"r|"` → extract members, stripping the `share/isabelle-semantic-data/`
  prefix, refusing absolute/`..` member names (tarfile data filter).
- Install sequence incl. healing and the `build` field: §5's
  `install_system_db` row is the authority.

### 15.5 Phase-1 checklist (expansion of §11.1)

1. `git mv Isabelle_Semantic_Embedding/r2_sync.py
   Isabelle_Semantic_Embedding/snapshot_sync.py`; `git mv
   Isabelle_Semantic_Embedding/semantics_manage.py
   Isabelle_Semantic_Embedding/isabelle_semantics.py`; `git mv
   test_r2_sync.py test_snapshot_sync.py`. Rename `R2Error → SnapshotError`,
   `R2Busy → SnapshotBusy`. Update importers: `isabelle_semantics.py`
   (`_r2()` helper), `toplevel.py` (AoA — Phase 3 repo, but the import
   string appears in ITS repo; Phase 1 touches only this repo),
   `pyproject.toml` scripts target, `conda/recipe.yaml` entry_points +
   tests import line (§7 items a+b), `manage_script()` fallback path,
   in-code "semantics_manage.py" mentions.
2. Facade (§3): `find_system_db` (in snapshot_sync), `_system_env`/
   `_user_env` in `_Semantic_DB` and `Vector_Store`, `iter_items`, tombstone
   codec (`b""`), raw-reader guards + single-layer-scan skips (§3.1 lists
   every site), RMW copy-up (§3.1), L23 vector resolution + `_topk_sync`
   dual-txn + `_auto_embed`/candidate corollaries (§3.2), two-layer
   experience-index union (§3.3).
3. Tests: `test_layered_db.py` per §9.1–9.4b. Gate: with no system DB and no
   tombstones, the full existing suite passes unmodified (byte-identical
   claim). AoA's `r2_sync` import BREAKS the moment Phase 1 lands in the SHARED
   checkout (no shim, by L5) — mitigate by updating Isa-Mini's import in the
   same wave, or holding the commit until Phase 3 is ready; the repos version
   together in practice, see §7 ordering.
4. Do NOT start §5 deletions (R2 client etc.) in Phase 1 — the old pull path
   must keep working until Phase 2 lands `install_system_db`.

### 15.6 Phase-2 checklist (expansion of §11.2)

Delete: `settings`/`_client`/`remote_head`/marker IO/`check_update` +
`auto_check` config keys/`push_snapshot`/`_pack_snapshot`(old)/`merge_env`/
`_merge_snapshot`/`_keep_local_thy_status`/`MERGE_BATCH`/`_backup`/
`.pull_incomplete` IO/`_require_idle`/`_open_handles`/`_require_disk`/
`_free_bytes`/`PUSH_MIN_FREE`/`PULL_MIN_FREE`/boto3 usage. Add:
`install_system_db` (§5, §15.4), `export` (§5), CLI surface changes
(`pull`/`release` new, `push` gone, `status`/`list`/`remove`/`fsck` per §14,
`embed` candidates per L23). `SnapshotError` remains the CLI's fail-fast
exception. Config template: drop the `r2:` section (config file may retain
stale keys on user machines — loader just ignores them).

### 15.7 Repo discipline reminders (from CLAUDE.md, apply while implementing)

Shared working tree: no stash/checkout/reset/clean; commit on main only.
Restart the REPL server after any `.ML` edit (none planned). Golden YAMLs
(`Tests/*.yml` in Isa-Mini) need explicit approval — Phase 3's AoA test
rewrite touches `test_ensure_semantic_db.py` only (pytest, not golden).
`test_AoA.py` runs are irrelevant to Phases 1–2. The
`sync-semantic-embedding-db` skill must be rewritten after Phase 2 — SKILL
edits need the user's separate approval (ask then).
