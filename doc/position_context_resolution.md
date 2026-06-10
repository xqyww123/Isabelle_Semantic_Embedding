# Position-Based Context Resolution for `query`

**Commit**: `336808d` on `contrib/Semantic_Embedding`
**Date**: 2026-05-21

## Problem

The `query` MCP tool (internally `mk_query_by_name_tool`) used a static theory context captured at callback registration time. This means locale-local names like `local.f` (which only exist inside a locale block's proof context) could not be resolved. The tool could only resolve globally-visible names.

## Solution Overview

Added an optional `context_at` parameter to `query` that specifies a source position (line/column/file). The ML side resolves this position to a `Proof.context` via two fallback paths:

```
context_at_position(file, offset)
  ├─ Live PIDE theory? → Scala command_id → Document.command_exec → Toplevel.context_of
  ├─ Finished/heap theory? → re-evaluation cache (pure ML) → Toplevel.context_of
  └─ Both fail? → NONE → caller uses static theory context (backward-compatible)
```

## Files Changed

### 1. `Tools/pide_state.ML` — Core ML implementation

**Signature additions** (lines ~51-70):
- `command_id_at_position : string -> int -> int option` — Scala call to get PIDE command ID
- `toplevel_state_at_position : string -> int -> Toplevel.state option` — extracts Toplevel.state via `Document.command_exec`
- `context_at_position_cfg = {re_eval_cache: bool}` — config record controlling fallback
- `context_at_position : context_at_position_cfg -> string -> int -> Context.generic option` — main entry point
- `position_context_unpacker : Context.generic -> Context.generic MessagePackBinIO.Unpack.unpacker` — msgpack wire adapter

**Live PIDE path** (lines ~281-300):
- `command_id_at_position` calls Scala function `pide_state.command_id_at_position` via `Scala.function1`
- `toplevel_state_at_position` uses `Document.command_exec (Document.state()) file_path cmd_id` to get `Command.exec`, then `Command.eval_result_state eval` to get `Toplevel.state`
- Returns `NONE` if command hasn't been evaluated ("Unfinished lazy" for own command) or file not in live PIDE nodes

**Re-evaluation cache** (lines ~303-390):
- `reeval_cache : (int * Toplevel.state) list Symtab.table Synchronized.var` — file_path → sorted list of (symbol_offset, Toplevel.state)
- `theory_of_file : string -> string option` — searches `Thy_Info.get_names()` for loaded theory matching file path (compares `Path.T` directly using eqtype equality)
- `build_reeval_cache : string -> (int * Toplevel.state) list` — creates fresh theory via `Resources.begin_theory master_dir header parents`, parses with `Outer_Syntax.parse_text`, executes via `Toplevel.command_exception`, collects `(offset, state)` pairs for non-ignored transitions
- `reeval_context_at_position` — lookup: finds the largest cached offset ≤ target offset, extracts `Context.Proof (Toplevel.context_of st)`
- Performance: ~1s first call (full re-evaluation), 0.001s cached lookups

**`context_at_position`** (lines ~394-404):
- Tries `toplevel_state_at_position` (live PIDE) first
- If NONE and `re_eval_cache = true`, tries `reeval_context_at_position`
- Returns `Context.Proof (Toplevel.context_of st)` or NONE

**`position_context_unpacker`** (lines ~406-420):
- Reads `Option(string * int)` from msgpack wire using `unpackOption (unpackPair (unpackString, unpackInt))`
- `NONE` (msgpack nil) → returns fallback static context (backward-compatible with old Python sending `ctxt=None`)
- `SOME (file, offset)` → calls `context_at_position {re_eval_cache = true}`, falls back to static context on NONE

### 2. `src/scala/pide_state.scala` — Scala command ID lookup

**`Command_ID_At_Position`** object (added before `PIDE_State_Functions`):
- `Scala.Fun("pide_state.command_id_at_position", thread = true)`
- Input: `(file_path: String, symbol_offset: Int)` via YXML
- Iterates `node.commands` (same pattern as `command_at_position`) to find command containing offset
- Returns `command.id : Long` (or 0 if not found)
- Only searches live PIDE nodes (`version.nodes`), not DB snapshots
- Registered in `PIDE_State_Functions` class

### 3. `Tools/semantic_store.ML` — Wiring up the unpacker

Two interpretation sites (lines ~650 and ~775) changed:
```ml
(* Before *)
val su = Context_Callbacks.static_context_unpacker context
val uk_cb = Universal_Key.make_universal_key_callback su

(* After *)
val su = Context_Callbacks.static_context_unpacker context
val pu = PIDE_State.position_context_unpacker context
val uk_cb = Universal_Key.make_universal_key_callback pu
```

Only the `uk_cb` (universal_key_of callback, used by `query`) uses the position-aware unpacker. All entity enumeration callbacks remain static (`su`) — unchanged wire protocol.

Embedding-related sites (lines ~878, ~920) are NOT changed — they don't need position context.

### 4. `Isabelle_Semantic_Embedding/semantics.py` — Python MCP tool

**Schema** (`_mk_query_by_name_schema`, line ~255):
Added optional `context_at` object property:
```json
{
  "context_at": {
    "type": "object",
    "description": "Resolve the name under the proof context at this source position. Omit to use the theory's global context.",
    "properties": {
      "file": {"type": "string", "description": "Path to the theory file. Defaults to the current theory file."},
      "line": {"type": "integer", "description": "1-based line number."},
      "column": {"type": "integer", "description": "1-based column number. If omitted, uses the end of the line."}
    },
    "required": ["line"]
  }
}
```

**`_end_of_line_column`** (line ~296): Helper returning last column of a line (for when column is omitted).

**`mk_query_by_name_tool`** (line ~392): Now accepts `file_path: str | None = None` parameter for the default theory file.

**Handler position logic** (lines ~418-433): Reads `context_at` dict from args, extracts line/column/file, converts via `AsciiPosition(line, column, file).to_isabelle_position().raw_offset` to get symbol offset, passes as `ctxt=(file, offset)` tuple to `query_by_name_raw`.

### 5. `Isabelle_Semantic_Embedding/semantic_interpretation.py` — Call site

Line ~567: passes `file_path=file_path` to `mk_query_by_name_tool`.

## Wire Protocol

The `universal_key_of` callback argument changes from:
- Old: `(nil, (kind, name))` where nil is consumed by `unpackUnit`
- New: `(Option(file, offset), (kind, name))` where `unpackOption` reads nil as NONE (backward-compatible) or `[file, offset]` as SOME

Python `msgpack.packb(None)` → msgpack nil (0xc0) → `unpackOption` reads as NONE → same as `unpackUnit` reading nil. Wire-compatible.

## Test Files

- `Test/Document_State_Experiment.thy` — jEdit test: live PIDE context_at_position, locale name resolution, heap theory access
- `Test/Eval_Thy_Experiment.thy` — jEdit test: re-evaluation cache for heap theories, performance measurement
- `Test/test_position_context.py` — REPL-based automated test: type-check, heap theory caching, cached lookup speed

## Key Experimental Findings

1. **Live PIDE**: `Document.command_exec` works for **previous** commands (not the currently-executing one — "Unfinished lazy"). Command IDs are negative integers in PIDE.
2. **Heap theories**: No PIDE commands exist. DB snapshots have markup but no execution state. Re-evaluation via `Resources.begin_theory` + `Outer_Syntax.parse_text` + `Toplevel.command_exception` works (~1s for Lattices.thy/460 states, ~1.5s for Groups.thy/1205 states).
3. **`Thy_Info.eval_thy`** exists in Isabelle2024 but is NOT exported in the signature. We replicate its approach using exported APIs.
4. **Locale context**: `Toplevel.context_of` (not `Toplevel.generic_theory_of`) is needed to get locale bindings. `generic_theory_of` always returns `Context.Theory`, losing locale proof context.
5. **`Locale.init locale_name thy`** can reconstruct locale context from just theory + locale name (no PIDE needed), but requires knowing the locale name — not used in final implementation (generic approach preferred).

## Dependencies

- `Isabelle_RPC/Isabelle_RPC_Host/position.py`: `AsciiPosition`, `FileIndex`, `get_file_index` — for line/column → symbol offset conversion
- `Isabelle_RPC/Isabelle_RPC_Host/universal_key.py`: `universal_key_of` already passes `ctxt` parameter through to callback (line 104)
- `Isabelle_RPC/contrib/mlmsgpack/mlmsgpack.sml`: `unpackOption` (line 827) — tries inner unpacker first, falls back to `unpackUnit` (nil)

## Plan File

Full plan at: `/home/qiyuan/.claude/plans/query-by-name-uses-theory-jaunty-hare.md`
