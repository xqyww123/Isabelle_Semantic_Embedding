# `run_semantic_interpretation` — auto-run whole-DB vector embedding — Implementation Plan

Status: **implemented (2026-07-21).**
All decision points are resolved (§9); the §7 user-facing strings (S1-S4, S6) were
explicitly approved by the user on 2026-07-21 and are now in code. Python unit tests
(`test_complete_vector_store.py`, 17 cases) pass; ML built incrementally. A 2-turn
adversarial code review (5 lenses, dedup, 2-skeptic rebuttal) found zero surviving
defects in the production code; its two surviving test-quality findings (handler
verbose pass-through untested; reset-on-exception assertions vacuous across
asyncio.run's context copy) were fixed and both new tests mutation-verified. The
jEdit manual pass (§8, ML/integration) remains to be done interactively.
Note: S6 was briefly inserted into the restructured README, then the user reset the
README (2026-07-21) — its new §4 already describes the command as "interpret and embed",
which the user judged sufficient. S6 is therefore NOT in the README, by user decision;
the README is not to be modified.

## 0. Goal and locked decisions

Today `run_semantic_interpretation` only *interprets* (LLM → English → `semantics.lmdb`);
vectors are left to be back-filled lazily by `Semantic_Vector_Store._auto_embed` at the
next semantic query. The user wants the command to behave like the batch script
`isabelle-semantics collect --embed-models` end to end: interpretation **followed by**
vector completion.

Locked by the user (2026-07-21):

| # | Decision |
|---|---|
| L1 | After the command's interpretation phase, run the **same whole-DB completion** the CLI's `_embed_models` performs: scan all of `semantics.lmdb`, embed every interpreted record that has no vector — NOT just the entities of the theories interpreted this run. |
| L2 | The model/provider comes from the **current context's config-option cascade**: `Semantic_Embedding.embedding_driver` / `embedding_base_url` / `embedding_model` config option → Isabelle env → host env → default, i.e. exactly `_resolve_embedding_config` (`semantics.py:1766`). Exactly **one** model per run. |
| L3 | `!` (force) re-interprets, but the embed phase stays **presence-based** — existing vectors of re-interpreted entities are NOT refreshed. This is the intended *forcing semantics* (user verdict, matching the CLI where `--re-embed` is deliberately a separate act from `--reinterpret`), not a defect. Whole-store forced re-embedding remains `isabelle-semantics embed` territory. |
| L4 | Embed-phase failure ⇒ the command **fails with `error`** (hard fail, one actionable line when recognisable — mechanism in §6). The interpretation phase's results are durable in LMDB either way. |
| L5 | The embed phase **also runs on the "Nothing to interpret." path**, so the command's postcondition is unconditional and re-running it heals a vector-incomplete DB. |
| L6 | The embed machinery's per-batch tracing is gated by the **existing `Semantic_Store_verbose` config option** — no new user-facing knob. Default (off) = silent on the completion path; opt-in = diagnostics flow. The internal ContextVar survives only as transport (§4.5). |

External assumption (user decision, 2026-07-21):

| # | Assumption |
|---|---|
| A1 | **The RPC host is per-Isabelle-process and auto-cleaned**: each Isabelle process starts its own fresh host (thus always running current code) and the host exits with the Isabelle process. Design under way in `RPC_EPHEMERAL_HOST_PLAN.md` (repo root). Consequence for THIS plan: a stale long-lived host can be assumed not to exist, so no "Unknown procedure" special-casing, no S7 remedy text, no README upgrade note. |

## 1. Verified current behavior (all file:line checked 2026-07-21)

- Command: `Tools/interpret_command.ML:39-101`. Flow: resolve roots → `Remote_Procedure_Calling.load` (:56) → `plan_interpretation` (:62) → `n = 0` ⇒ `writeln "Nothing to interpret."` and **stop** (:65) → else `Active.dialog_text` Yes/No (:81-87) → Yes ⇒ `Semantic_Store.interpret_with_parallel force roots` (:98). No embedding anywhere.
- `semantic_store.ML` contains **no** embedding call and no ML→Python embed RPC command; the three embedding config options (:163-176) are registered via `Config.register_rpc_option` for Python-side lookup only.
- Batch parity target: `semantics_manage.py cmd_collect` (:526) = interpret phase (REPL app → same `interpret_with_parallel`) **then** `_embed_models` (:731): `_collect_embed_candidates` (:694, whole-DB scan of interpreted records, WIP and EXPERIENCE included, one read txn) → per model: `store.contains` missing-filter (:755) → `document_text_of` renderability partition + skip-warning (:766-779) → confirmation (:785-793) → batches of 256 × `embed_records(force=True)` with a progress line per batch (:795-802) → done line.
- Per-connection store: `Connection.semantic_vector_store` (`semantics.py:1823-1845`) resolves (driver, base_url, model, api_key) via `_resolve_embedding_config` and caches the `Semantic_Vector_Store` on the connection (`_svs_lock`, :1136-1140); LMDB envs are additionally memoized globally by path (`semantic_embedding.py:960-978`), so no double-open hazard.
- RPC facts (from the `isabelle-rpc` skill): `log` (writeln/warning/tracing) and `getenv` are **global** callbacks; `Config.lookup` is **per-command** — any command whose Python handler calls `connection.config_lookup` MUST carry `Config.make_config_lookup_callback` in its `callback` list (`Isabelle_RPC/Tools/config.ML:12`).
- Python procedures register via `@isabelle_remote_procedure("name")` (`semantics.py:1850ff`); the module is imported into the host by `Remote_Procedure_Calling.load ["Isabelle_Semantic_Embedding"]`, which the command already runs before the dialog (`interpret_command.ML:56`).
- `Semantic_DB.__setitem__` (`semantics.py:373`) does **not** touch any vector store ⇒ after re-interpretation, completion (presence-based `contains`) will NOT refresh existing vectors. Intended forcing semantics per L3 (the CLI mirrors it: `--re-embed` is deliberately separate from, and mutually exclusive with, `--reinterpret`, :531).
- Progress-channel precedent: interpretation progress deliberately uses `writeln`, not `tracing` (`semantic_store.ML:1525-1531`, `semantic_interpretation.py:589-607`): `tracing` is capped by `editor_tracing_messages` (1000) and overflow raises a blocking "Tracing paused" dialog. Whole-DB completion can emit hundreds of per-batch lines (10⁵ missing / 256 ≈ 400), so the embed phase must use `writeln` too — **including the embedded machinery's own tracing** (review finding, verified): the handler's store is connection-bound, so each 256-batch fires `connection.tracing` inside `embed_records` (`semantics.py:1610-1612`) **plus** two provider `_log` tracing lines per `embed` call (`semantic_embedding.py:441-443` via `Connection.current()`, which handler tasks inherit, `rpc.py:295,328`). ≥3 tracing lines × ~400-600 batches blows the 1000 cap on exactly the flagship first-run scenario; the CLI never sees this (its store has `connection=None`). §4.5 specifies the quiet mechanism.

## 2. Design overview

One new ML→Python RPC command, `Semantic_Embedding.embed_all_missing`, whose Python handler
reuses the connection-resolved store and a **shared** completion routine extracted from
`_embed_models`. `interpret_command.ML` calls it after a successful interpretation run —
and also on the "Nothing to interpret." path (L5), so the command's postcondition is
uniformly "semantics DB interpreted for the cone AND vector store complete for the
configured model". The CLI keeps byte-identical behavior by calling the same shared
routine.

The `Semantic_Store.collect` REPL app stays interpret-only (its header contract), and
`cmd_collect` keeps its own separate embed phase — no double-embedding anywhere.

```
run_semantic_interpretation
  ├─ resolve roots, load Python module, plan cone            (unchanged)
  ├─ n = 0 ─ writeln "Nothing to interpret." ──────────────┐
  ├─ dialog Yes ─ interpret_with_parallel ─────────────────┤ (No ⇒ abort, no embed)
  └─                                                        ▼
                        Semantic_Store.embed_all_missing (ML wrapper, carries Config.lookup cb)
                          └─ RPC "Semantic_Embedding.embed_all_missing"
                               ├─ store = await connection.semantic_vector_store()   (L2)
                               ├─ candidates = _collect_embed_candidates()           (L1)
                               └─ complete_vector_store(store, candidates,
                                     force=False, report=writeln, warn=warning)
CLI: _embed_models = resolve env config → per model: make store → complete_vector_store(
                                     ..., report=print, warn=print(stderr), confirm=CLI hook)
```

## 3. Change list

| File | Change |
|---|---|
| `Isabelle_Semantic_Embedding/semantics.py` | move `_collect_embed_candidates` here (verbatim); add `complete_vector_store(...)` (extracted from `_embed_models`); add `@isabelle_remote_procedure("Semantic_Embedding.embed_all_missing")` handler (function-local `USER_ERROR_MARKER` import, §4.4); gate the `embed_records` tracing line on the internal ContextVar (§4.5) |
| `Isabelle_Semantic_Embedding/semantic_embedding.py` | add the internal `_embed_tracing_gated` ContextVar; consult it in `Embedding_Provider._log` (§4.5) |
| `Isabelle_Semantic_Embedding/semantics_manage.py` | `_collect_embed_candidates` becomes an import from `semantics`; `_embed_models` body shrinks to config-resolution + per-model store construction + CLI report/warn/confirm hooks around `complete_vector_store`. Behavior byte-identical (§5.2) |
| `Tools/semantic_store.ML` | add `val embed_all_missing : Context.generic -> unit` to signature + implementation (RPC wrapper carrying the `Config.lookup` callback); register `Semantic_Store_verbose` as an RPC option + update its SCOPE comment (§4.5) |
| `Tools/interpret_command.ML` | call the embed phase in the `n = 0` branch and after a successful `Yes` run; extend dialog text; extend header comment; error handling per §6 |
| `README.md` | §5.1: document the new embed phase (§7-S6) |
| new `test_complete_vector_store.py` | unit tests, stub-Connection style of `test_auto_embed_gate_off.py` (§8) |
| unchanged | `Tools/semantic_interpretation_app.ML` (stays interpret-only, header already says so), `cmd_collect` / `cmd_embed` CLI surfaces, `_auto_embed`, `Semantic_Collection_App.thy` |

## 4. Python side, detailed

### 4.1 `_collect_embed_candidates` moves to `semantics.py`

Moved **verbatim** (docstring included: the WIP-symmetry argument at
`semantics_manage.py:697-708` is load-bearing history). It only touches `Semantic_DB`, so
`semantics.py` is its natural home; `semantics_manage.py` does
`from Isabelle_Semantic_Embedding.semantics import _collect_embed_candidates` (it already
imports from that module). Keep the `kinds` parameter — `cmd_embed`'s experience-migration
path uses it.

### 4.2 New shared routine `complete_vector_store`

Extracted from `_embed_models:752-803`, placed next to `Semantic_Vector_Store` in
`semantics.py`:

```python
async def complete_vector_store(
        store: Semantic_Vector_Store,
        candidates: 'list[tuple[bytes, object]]',
        *,
        force: bool,
        label: str,                      # model name, prefixes every line
        report,                          # async (str) -> None
        warn,                            # async (str) -> None
        confirm=None,                    # async (n, total, chars) -> bool; None = proceed
) -> 'tuple[int, int, int]':             # (n_embedded, n_unrenderable, total_tokens)
```

Body = the exact current per-model logic, in order:

1. `force` ⇒ `todo = candidates`; else filter by one `store.contains` batch (:755-756).
2. `n == 0` ⇒ `report(f"{label}: already complete ({len(candidates)} entities).")`, return.
3. Renderability partition via `document_text_of` (:766-774); if any unrenderable ⇒
   `warn(...)` with the same text as :776-779; if nothing renderable ⇒
   `report(f"{label}: nothing embeddable.")`, return.
4. `report(f"{label}: {n} of {len(candidates)} entities need vectors ({chars} chars).")`.
5. If `confirm` is not None and `not await confirm(n, len(candidates), chars)` ⇒
   `report("Aborted.")`, return.
6. `BATCH = 256` loop calling `store.embed_records(chunk, force=True)`, after each batch
   `report(f"  {label}: embedded {min(i+BATCH,n)}/{n}")` (:795-802).
7. `report(f"{label}: done ({n} embedded, {total_tokens} tokens).")`.

The routine gains a `verbose: bool = False` keyword: unless verbose, the whole body runs
with the internal tracing gate set (§4.5) — set on entry, reset in a `finally` — so the
machinery's per-batch tracing is silenced exactly for this routine's dynamic extent (CLI
included, where it was a no-op anyway) and nowhere else. The RPC handler feeds it from
`Semantic_Store_verbose`; the CLI uses the default.

All strings identical to today's `_embed_models` output, so the CLI is unchanged
observationally (the CLI's `report`/`warn` are `print` / `print(file=sys.stderr)`
wrappers; `flush=True` preserved).

### 4.3 `_embed_models` becomes a thin caller

Keeps: `_resolve_embedding_config_env` fallback, the per-model
`make_embedding_provider` + `Semantic_Vector_Store(emb_provider=..., connection=None)`
construction, and the CLI confirmation **hook**:

```python
async def _cli_confirm(n, total, chars):
    if yes: return True
    if sys.stdin.isatty():
        return input("Proceed? [y/N] ").strip().lower() == "y"
    print(f"Refusing to embed {n} entities non-interactively; pass --yes "
          f"(or --yes-embed to `collect`).", file=sys.stderr)
    sys.exit(1)
```

`sys.exit(1)` stays a CLI-only concern inside the hook — `complete_vector_store` itself
never exits the process. Note the one intentional cosmetic delta: today's "Aborted."
prints via `print`; it now goes through `report` (still `print` in the CLI) — same output.

### 4.4 New RPC procedure

In the `# --- RPC wrappers ---` section of `semantics.py`:

```python
@isabelle_remote_procedure("Semantic_Embedding.embed_all_missing")
async def _embed_all_missing(arg: Any, connection: Connection) -> None:
    """Whole-DB vector completion for the connection's configured embedding model.
    Driven by run_semantic_interpretation; reporting goes through writeln (not
    tracing) for the same editor_tracing_messages reason as interpretation
    progress (semantic_store.ML:1525)."""
    # Function-local on purpose: a top-level import is a hard import cycle
    # (semantic_interpretation.py:42 imports from semantics at module level, and
    # USER_ERROR_MARKER is defined only at :699 — both package-import orders die).
    from .semantic_interpretation import USER_ERROR_MARKER
    try:
        store = await connection.semantic_vector_store()   # L2: full config cascade
    except (RuntimeError, ValueError, ImportError) as e:
        # All three are curated user-config messages: RuntimeError = unconfigured
        # provider (_resolve_embedding_config, already warned), ValueError = base_url
        # missing the /v1 segment (semantic_embedding.py:580-590), ImportError =
        # unknown embedding_driver (make_embedding_provider). Mark them so ML shows
        # one actionable line, no traceback.
        raise RuntimeError(USER_ERROR_MARKER + str(e)) from e
    candidates = _collect_embed_candidates()               # L1: whole DB
    verbose = bool(await connection.config_lookup("Semantic_Store_verbose"))  # §4.5
    async def report(m): await connection.writeln("[Semantic_Embedding] " + m)
    async def warn(m):   await connection.warning("[Semantic_Embedding] " + m)
    await complete_vector_store(
        store, candidates, force=False, label=store.model_name,
        report=report, warn=warn, verbose=verbose)
    return None
```

`USER_ERROR_MARKER` is the existing marker that `Semantic_Store.extract_user_error`
(`semantic_store.ML:1074`) strips on the ML side; command-agnostic (plain substring scan).

- `label=store.model_name` — the **canonical** model name (`semantics.py:1129-1134`,
  set from `emb_provider.canonical_model`), NOT `emb_provider.model`: the default
  OpenAI driver overwrites `.model` with the per-domain API wire id
  (`semantic_embedding.py:591`, e.g. `fireworks/qwen3-embedding-8b`), which would break
  §7-S3/CLI string parity (the CLI labels with the raw canonical loop variable).
- No confirmation hook (`confirm=None`): per the recorded rationale at
  `semantics.py:1294-1300`, prompts about *embedding* spend (cheap, on already-paid
  interpretations) are the wrong thing — a No just re-arms the same prompt forever. On
  the dialog path the §7-S1 text additionally discloses the phase up front; on the L5
  `n = 0` path there is no dialog at all, and the `semantics.py:1294` rationale is the
  operative (and sufficient) one.
- No `mark_thy_embedded` bookkeeping — exact parity with `_embed_models`, which does not
  mark either (L1 = "照搬"). `contains` prevents rework regardless.
- Return value `None`: all reporting is Python-side via `writeln`, single authority,
  same lines as the CLI.

### 4.5 Silencing the embed machinery's per-batch tracing on this path

Problem (§1 last bullet): with a connection-bound store, each 256-batch emits ≥3
`tracing` lines from *inside* the machinery — `embed_records`' own count line
(`semantics.py:1610-1612`) and the provider's start/done `_log` lines
(`semantic_embedding.py:441-443`, routed via `Connection.current()`) — overflowing
`editor_tracing_messages` (1000) at whole-DB scale and popping the blocking
"Tracing paused" dialog this plan exists to avoid.

**Policy: the existing `Semantic_Store_verbose` config option** (user decision,
2026-07-21 — no new user-facing knob). Its documented semantics fit exactly: "opt-in
internal diagnostics, off by default" (`semantic_store.ML:73-78,183-191`), and the
machinery lines are precisely internal diagnostics. Default (off) ⇒ the completion path
silences them (progress = its own per-batch `report` writeln lines, which stay
unconditional per the flag's own "run-level progress must not be gated" contract);
`declare [[Semantic_Store_verbose]]` ⇒ they flow — the user has explicitly opted into
diagnostics, accepting the tracing-cap risk on a huge run, same risk profile as the
flag's existing `vtracing` use.

Plumbing (three pieces):

1. `Semantic_Store.ML`: register the option for Python lookup —
   `Config.register_rpc_option "Semantic_Store_verbose" (Config.bool_value
   Semantic_Store_verbose)` (one line, mirrors :160-180's neighbors) — and update the
   flag's SCOPE comment (:187-189, "only one vtracing site remains") to name the
   Python-side embed-machinery gating as its second consumer.
2. Handler entry (`_embed_all_missing`): ONE
   `await connection.config_lookup("Semantic_Store_verbose")` (works because the
   command carries `Config.make_config_lookup_callback`, §5.1), passed as
   `verbose: bool` into `complete_vector_store`. The CLI passes nothing — its default
   (`verbose=False`) is observationally irrelevant there (`Connection.current()` is
   `None`, the `_log` lines were no-ops anyway; `embed_records`' line needs
   `store.connection`, also `None`).
3. Transport — an **internal, undocumented** module-level
   `ContextVar("_embed_tracing_gated", default=False)` in `semantic_embedding.py`,
   consulted by `Embedding_Provider._log` (`semantic_embedding.py:411`) and by the
   tracing site in `Semantic_Vector_Store.embed_records` (`semantics.py:1610`).
   `complete_vector_store` sets it iff `not verbose` (`token = var.set(...)` /
   `finally: var.reset(token)`). `_warn` (`semantic_embedding.py:417`) is **not**
   gated — retry/failure warnings always get through.

Why the ContextVar cannot be eliminated even with the config-option policy: the `_log`
sites sit deep in the provider and cannot do a per-line `config_lookup` — each would be
an RPC callback round-trip, and worse, `Config.lookup` is a per-command callback that
e.g. `interpret_file`'s callback list does not carry (`semantic_store.ML:1350-1354`), so
a per-line lookup would hard-fail during interpretation. The flag value is therefore read
once at the only entry point that owns a suitable command, and carried down ambiently.
ContextVar rather than a plain global because the RPC host runs concurrent handler tasks
on one event loop: a task-scoped flag cannot leak gating into a concurrent `_auto_embed`.

Scope guarantees (unchanged from before): query-path/`_auto_embed` tracing outside
`complete_vector_store` behaves exactly as today (the var is never set there), and the
CLI is byte-identical.

## 5. ML side, detailed

### 5.1 `semantic_store.ML`

Signature addition (after `plan_interpretation`):

```sml
(* Whole-DB vector completion: embed every interpreted record that has no vector in
   the store of the connection's configured embedding model (config option >
   Isabelle env > host env > default; see _resolve_embedding_config in semantics.py).
   Missing-only (presence-based); reporting is Python-side via writeln.  The context
   is needed only to serve the per-command Config.lookup callback. *)
val embed_all_missing : Context.generic -> unit
```

Implementation (near `interpret_with_parallel`; `local open MessagePackBinIO` as usual):

```sml
fun embed_all_missing (context : Context.generic) : unit =
  Remote_Procedure_Calling.call_command
    {name = "Semantic_Embedding.embed_all_missing",
     arg_schema = packUnit,
     ret_schema = unpackUnit,
     (* Config.lookup is per-command (NOT global): without this callback the
        Python handler's config_lookup calls fail. log/getenv are global. *)
     callback = [Config.make_config_lookup_callback
                   (Context_Callbacks.static_context_unpacker context)],
     timeout = NONE} ()
```

`timeout = NONE` matches `interpret_file` — a first-ever completion of a large DB takes
minutes.

### 5.2 `interpret_command.ML`

New local function inside `run`, after `roots` is computed (it closes over `ctxt`):

```sml
(* Phase 2: whole-DB vector completion (missing-only) for the configured embedding
   model.  Runs after a successful interpretation run AND on the nothing-to-
   interpret path (L5), so the command always leaves the vector store complete.
   Interrupting is safe: vectors are committed per 256-batch and the scan is
   presence-based, so a re-run resumes.  A failure here fails the command (L4);
   the interpretation phase's results are already durable in LMDB. *)
fun embed_phase () =
  (writeln "[Semantic_Embedding] Completing missing vector embeddings...";
   Semantic_Store.embed_all_missing (Context.Proof ctxt))
```

Wiring (three edits in the `if n = 0 ... else ...` expression, :65-100):

1. `n = 0` branch: `(writeln "[Semantic_Embedding] Nothing to interpret."; embed_phase ())`
   — L5.
2. `"Yes"` branch: `(Semantic_Store.interpret_with_parallel force (map Context.Theory roots);
   embed_phase ())`.
3. `"No"`/edit branch: unchanged — declining the dialog aborts everything.

Plus: dialog text extended (§7-S1), header comment gains one line noting the embed phase,
and the error handling of §6.

## 6. Error handling of the embed phase (L4: hard `error`)

How a Python-side failure is detected and surfaced, end to end:

1. **Python raises** — any exception escaping the `@isabelle_remote_procedure` handler
   makes the RPC host send the error frame `(1, str(error))` (traceback text) instead of
   a result (`Isabelle_RPC_Host/rpc.py:151-155` `write_error`).
2. **ML raises `Remote_Calling_Failure`** — `Remote_Procedure_Calling.call_command` turns
   that frame into `Remote_Calling_Failure {func_name, message}` (and closes the pooled
   connection). So detection on the ML side is an ordinary `handle` around the
   `embed_phase ()` call — nothing new is needed in the transport.
3. **Classification via the existing marker** — `Semantic_Store.extract_user_error`
   (`semantic_store.ML:1074`) looks for `USER_ERROR_MARKER`
   (`[SEMANTIC_INTERPRETATION_USER_ERROR] `, a plain substring scan, command-agnostic) in
   the message. The handler in `interpret_command.ML`:

   ```sml
   embed_phase ()
     handle Remote_Procedure_Calling.Remote_Calling_Failure {message, ...} =>
       (case Semantic_Store.extract_user_error message of
         SOME human => error human
       | NONE => error ("Vector embedding failed: " ^ message))
   ```

   `error` raises `ERROR`, which Toplevel reports as the command's failure in jEdit (red
   in the output panel) — the same path every failing Isabelle command uses.

   (A stale-host "Unknown procedure" special case was considered and DROPPED under
   assumption A1: with a per-Isabelle ephemeral host there is no stale host to detect.)

Failure modes feeding into this:

- **Misconfigured/unconfigured provider** — three curated cases, all raised inside
  `connection.semantic_vector_store()` and all marker-wrapped by the handler's
  `(RuntimeError, ValueError, ImportError)` net (§4.4): unconfigured default triple
  (`RuntimeError`, `semantics.py:1802-1808`, also pre-warned), base_url missing the API
  version segment (`ValueError`, `semantic_embedding.py:580-590`), unknown
  `embedding_driver` (`ImportError`, `make_embedding_provider`) ⇒ step 3 yields the one
  actionable line, no traceback.
- **Provider/network failure mid-run**: `_embed_cached` already retries 10× per chunk
  (`semantic_embedding.py:326-349`); a chunk that still fails raises unmarked ⇒ step 3's
  `NONE` arm keeps the full traceback (there is no honest one-liner for it — same policy
  as interpretation's B6). Progress up to the last committed 256-batch is kept; a re-run
  resumes (missing-only).

Interrupt (buffer edit in jEdit) behaves like the interpretation phase: the exec is
cancelled, committed batches persist, re-run resumes — covered by the existing
"Interrupting is safe" contract, whose comment gets the §5.2 extension.

## 7. User-facing strings (for approval)

- **S1** — dialog body (`interpret_command.ML:82-87`), appended after the cost line:

  > `This calls the LLM: it may take a long time and cost money.`
  > `Afterwards, missing vector embeddings are computed as well (embedding API; far cheaper).`

- **S2** — ML phase-opening line: `[Semantic_Embedding] Completing missing vector embeddings...`
- **S3** — Python progress lines: identical to today's CLI lines (§4.2 steps 2-7),
  each prefixed `[Semantic_Embedding] ` by the RPC report wrapper, e.g.
  `[Semantic_Embedding] Qwen/Qwen3-Embedding-8B: 1234 of 150000 entities need vectors (987654 chars).`
  `[Semantic_Embedding]   Qwen/Qwen3-Embedding-8B: embedded 256/1234`
  `[Semantic_Embedding] Qwen/Qwen3-Embedding-8B: done (1234 embedded, 45678 tokens).`
  `[Semantic_Embedding] Qwen/Qwen3-Embedding-8B: already complete (150000 entities).`
- **S4** — unrenderable-records warning: unchanged CLI text, `[Semantic_Embedding] ` prefix.
- **S5** — *(withdrawn — L4 chose the error variant; no warning trailer exists)*
- **S6** — README §5.1 addition (draft):

  > After interpretation finishes (or when nothing needs interpreting), the command also
  > completes the vector store: every interpreted entity in the whole database that has no
  > embedding under the configured embedding model (§4) is embedded, in batches, with
  > progress reported to the output panel. This is the same completion `isabelle-semantics
  > collect --embed-models` performs, restricted to the single configured model.
  > Interrupting is safe; a re-run resumes.

- **S7** — *(withdrawn — stale-host handling dropped under assumption A1)*

## 8. Testing

Python (new `test_complete_vector_store.py`, stub style of `test_auto_embed_gate_off.py`
— `object.__new__(Semantic_Vector_Store)`, stub `contains`/`embed_records`, recorder
report/warn):

1. missing-only filter: present keys skipped; `force=True` bypasses `contains`.
2. already-complete and nothing-embeddable early-outs produce exactly one report line.
3. unrenderable records: warned once, skipped, counted in the return triple.
4. batching: >256 renderable ⇒ multiple `embed_records` calls, one progress line each,
   token sum returned.
5. confirm hook: `False` ⇒ "Aborted.", zero `embed_records` calls; `None` ⇒ proceeds.
6. `_embed_all_missing` handler: stub Connection with `semantic_vector_store`,
   monkeypatched `_collect_embed_candidates` ⇒ lines arrive via `writeln` (not `tracing`),
   prefixed; each of RuntimeError / ValueError / ImportError from store resolution is
   re-raised with `USER_ERROR_MARKER`.
7. CLI regression: `_embed_models` with monkeypatched candidates + fake provider prints
   the same lines as before the refactor (golden-ish assertion on the sequence).
   MUST NOT touch the live DB dir: also monkeypatch
   `Isabelle_Semantic_Embedding.semantics.Semantic_Vector_Store` (the `_embed_models`
   import is call-time, so patching works) or redirect `semantic_DB_dir()` to a tmpdir —
   the real constructor would `makedirs` + lmdb-open a junk `vector_<model>.lmdb` under
   `~/.cache`, which the purge/enumeration paths then see (`semantics.py:1130-1133`,
   `semantic_embedding.py:972-978`).
8. Tracing gating (§4.5): `complete_vector_store(verbose=False)` ⇒ `embed_records` and
   provider `_log` emit no tracing while `_warn` still passes; `verbose=True` ⇒ they
   flow; the var is reset on exit (exception included); and the handler passes the
   value of the `Semantic_Store_verbose` config lookup through.

ML/integration (manual — the dialog is jEdit-only by design):

1. **Make sure the RPC host runs the edited Python.** Under A1 (per-Isabelle ephemeral
   host) a fresh Isabelle session suffices; until A1 lands, restart the legacy shared
   host manually. Restart/rebuild nothing else: `.ML` edits need only a fresh PIDE
   session (plain incremental `isabelle build Semantic_Embedding` if a stale heap gets
   in the way — never `-c`).
2. In jEdit on a small scratch theory: run the command; after the interpretation
   summary, S2 + S3 lines appear; `vector_<model>.lmdb` gains the vectors.
3. Run it again: "Nothing to interpret." followed by `already complete`.
4. Unset the API key (default triple): the phase fails with the one-line setup message,
   no traceback (L4).
5. `isabelle-semantics collect --embed-models ... --yes-embed` and plain `embed`: output
   unchanged.
6. `declare [[Semantic_Store_verbose]]` and re-run on a small delta: the machinery
   tracing lines reappear (L6 opt-in).

## 9. Resolved decision points (user verdicts, 2026-07-21)

- **Q1 — stale vectors after `run_semantic_interpretation!` (force).** Verdict: **accept
  as-is** — this is not a gap but the *existing, intended forcing semantics*: forcing
  re-interprets; embedding stays presence-based. No cone-scoped or whole-DB forced
  re-embed is added. Recorded as **L3**.
- **Q2 — embed-phase failure.** Verdict: **`error`** (hard fail). Detection/acceptance
  mechanism spelled out in §6: Python exception → RPC error frame →
  `Remote_Calling_Failure` → `handle` in `interpret_command.ML` → `extract_user_error`
  (marker) → `error`. Recorded as **L4**.
- **Q3 — embed on the "Nothing to interpret." path.** Verdict: **yes, always run**.
  Recorded as **L5**.
- **Q4 — machinery tracing during completion.** Verdict: gate on the existing
  `Semantic_Store_verbose` option, no new knob. Recorded as **L6**, mechanism §4.5.
- **Q5 — stale-host handling.** Verdict: **not needed** — superseded by assumption A1
  (per-Isabelle ephemeral RPC host, separate plan `RPC_EPHEMERAL_HOST_PLAN.md`). The
  special case, S7, and the README upgrade note are all withdrawn.

Status-quo note (no change, no decision needed): non-HTTP mid-run retry failures keep
logging via `_log` (`semantic_embedding.py:366`) and are thus invisible under default
(non-verbose) completion until the final 10-retry error; HTTP failures warn via `_warn`
immediately (`:371`) regardless. Upgrading `:366` to `_warn` remains an optional
follow-up requiring its own approval.

## 10. Out of scope

- `_auto_embed` and its gate (`auto_interpret_for_embedding`) — unchanged.
- Multi-model embedding from the command (CLI keeps that); reranker; experience stores'
  write paths.
- `Semantic_Store.collect` REPL app — stays interpret-only by contract.
- Any vector-invalidation-on-reinterpretation mechanism (L3 keeps forcing presence-based).
- Version bump / superproject submodule bump — after implementation lands, as usual.
