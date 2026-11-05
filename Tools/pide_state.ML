(*  Title:      Tools/pide_state.ML
    Author:     Qiyuan Xu

Access PIDE document state via Scala functions:
  - save_thy_files: collect theory sources from PIDE state, write to backup files (path~)
  - absolutize_id_based_pos: resolve ID-based positions to file/line/offset positions
  - goto_definition: resolve entity reference at a position to its definition position
  - hover_message: extract tooltip information at a position
  - entity_at_position: return (kind, fully_qualified_name) of entity at a position
  - command_at_position: return source code of the command at a position, in a context
  - commands_at_positions: the same for a whole batch, one round trip for the resolution
  - make_command_at_position_callback: command_at_position as an RPC callback with a
    fixed context
The cut of a file on disk needs a context: its keyword table comes from the theories the
context sees, then from Build's registry.
*)

signature PIDE_STATE =
sig
  val save_thy_files: unit -> string list

  (* Convert ID-based positions (containing only a command id and a relative offset)
     to absolute file-based positions (with file path, line number, and absolute offset).
     Positions that already have file/line information are returned unchanged.
     When write_to_temp_file is true, the PIDE source is saved to a backup file (path~)
     and the returned positions use the backup file path. *)
  val absolutize_id_based_pos: {write_to_temp_file: bool} -> Position.T list -> Position.T list

  (* Given a position (file + offset), return the definition position of the entity
     at that location. Tries live PIDE state first, falls back to session export DB. *)
  val goto_definition: Position.T -> Position.T option

  (* Given a position (file + offset), return the hover tooltip text.
     Tries live PIDE state first, falls back to session export DB. *)
  val hover_message: Position.T -> string option

  (* Given a position (file + offset), return the (kind, name) of the entity
     at that location, where name is the fully qualified name.
     Tries live PIDE state first, falls back to session export DB. *)
  val entity_at_position: Position.T -> (string * string) option

  (* Given a position (file + offset), return the source code of the command
     at that location together with its span (start_offset, end_offset) in the file.
     Tries live PIDE state first (nodes PIDE parsed; a heap theory file is answered from
     its session DB even while an editor has it open), then the session export DB, then
     the cut of the file on disk under the context's keywords. *)
  val command_at_position: Context.generic -> Position.T -> (string * int * int) option

  (* The same for a whole batch: ONE absolutize round trip for the list, then per
     position the same live-PIDE / export-DB resolution, and every cut of a file
     -- the fallback reading it from disk, or the re-cut of a whole-file dump
     Scala returned -- made at most once per call.  The result is parallel to
     the argument; command_at_position is the singleton case.  A position with
     no file or offset (Position.none) is answered NONE without any Scala call,
     so a caller may use it as the "no lookup here" slot.  A Scala round trip
     costs a few ms of fixed overhead per call whatever the payload (measured:
     about 4 ms for the position resolution, 1-2 ms for the source lookup, on a
     transport floor of about 0.6 ms), so a caller with many positions batches. *)
  val commands_at_positions: Context.generic -> Position.T list ->
    (string * int * int) option list

  (* command_at_position as the RPC callback pide_state.command_at_position, wire
     (file, offset), cutting under the context it was built with.  Per call, not global:
     its answer depends on a context (see the rule at the global registrations below). *)
  val make_command_at_position_callback: Context.generic -> Remote_Procedure_Calling.callback'

  (* Cut a (possibly WIP) theory file into its command spans (source, start, end),
     1-based file-global symbol offsets, with local Outer_Syntax under the context's
     keywords.  This backs commands_at_positions for files no live PIDE state or export
     DB answers for; a file that is not a .thy has no command spans and yields [] without
     a parse. *)
  val command_spans_of_file: Context.generic -> string -> (string * int * int) list

  (* The re-cut of a whole-file dump (source, start s) into the single command
     containing the file-global symbol `offset`: NONE on a miss, never the dump itself.
     Exposed for testing the whole-theory-leak guard: that branch cannot be driven from a
     batch build, so it is unit-tested on a synthetic dump. *)
  val recut_dump_source: Context.generic -> string -> string -> int -> int ->
    (string * int * int) option

  (* expand_path, then the PLATFORM form: the path a Python receiver can open *)
  val rpc_path: string -> string

  (* Convert between symbol offset and line:column via Python RPC.
     Requires the Isabelle_RPC Python host to be running. *)
  val offset_to_line_column: string -> int -> int * int
  val line_column_to_offset: string -> int -> int -> int

  (* Return all ancestor sessions (whose heaps are loaded) with their export database paths.
     Each entry is (session_name, db_path). *)
  val get_session_databases: unit -> (string * string) list

  (* The live PIDE node holding the file, by the name PIDE gave it (the key
     Document.command_exec needs), and the id of its command at the symbol offset.
     NONE if no live node holds the file or no command covers the offset; heap
     theories have none. *)
  val command_id_at_position: string -> int -> (string * int) option

  (* Given a file path and symbol offset, attempt to extract the Toplevel.state
     of the command at that position via Document.command_exec.
     Returns NONE for heap-image theories or if the command hasn't been evaluated. *)
  val toplevel_state_at_position: string -> int -> Toplevel.state option

  type context_at_position_cfg = {re_eval_cache: bool}

  (* Given a file path and symbol offset, attempt to extract the Context.generic
     at that position.
     Fallback chain: live PIDE -> (if re_eval_cache) re-evaluation cache -> NONE.
     The re-evaluation replays the file's theory, found as theory_of_file finds it with
     the context given. *)
  val context_at_position: context_at_position_cfg -> Context.generic -> string -> int ->
    Context.generic option

  (* The finished theory whose master .thy file is the given file (same base name, then
     the same OS file): among those the context sees, then in Build's registry of
     session-build and heap theories.  The context's own unfinished theory is not
     answered, so a replay never re-runs the command that asked. *)
  val theory_of_file: Context.generic -> string -> theory option

  (* Msgpack unpacker that reads an optional (file, offset) pair from the wire.
     NONE -> returns the fallback context.
     SOME (file, offset) -> calls context_at_position, falls back on failure. *)
  val position_context_unpacker: Context.generic ->
    Context.generic MessagePackBinIO.Unpack.unpacker
end;

structure PIDE_State: PIDE_STATE =
struct

fun save_thy_files () =
  let
    val yxml = \<^scala>\<open>pide_state.save_thy_files\<close> "";
  in
    YXML.parse_body yxml |> XML.Decode.list XML.Decode.string
  end;

fun absolutize_id_based_pos {write_to_temp_file} positions =
  let
    val _ = if write_to_temp_file then (save_thy_files (); ()) else ();

    fun needs_resolution pos =
      is_some (Position.parse_id pos) andalso
      (is_none (Position.file_of pos) orelse is_none (Position.line_of pos));

    val to_resolve =
      positions |> map_filter (fn pos =>
        if needs_resolution pos then
          SOME (the (Position.parse_id pos), the_default 1 (Position.offset_of pos))
        else NONE);

    val resolved =
      if null to_resolve then []
      else
        let
          val input_body =
            XML.Encode.list (XML.Encode.pair XML.Encode.int XML.Encode.int) to_resolve;
          val yxml = \<^scala>\<open>pide_state.resolve_positions\<close>
            (YXML.string_of_body input_body);
          val answers =
            YXML.parse_body yxml
            |> XML.Decode.list (XML.Decode.pair XML.Decode.string
                 (XML.Decode.pair XML.Decode.int XML.Decode.int));
          (* One answer per id, in order (pide_state.scala maps the input).  The
             walk below pairs them positionally, so a reply of any other length
             would silently leave a tail of positions unresolved -- and, through
             the callers, their entities without a source line or a source. *)
          val _ =
            length answers = length to_resolve orelse
              error (String.concat ["PIDE_State.absolutize_id_based_pos protocol error: sent ",
                string_of_int (length to_resolve), " positions, got ",
                string_of_int (length answers), " answers"]);
        in answers end;

    val results = Unsynchronized.ref resolved;
    fun pop () = case ! results of
        x :: xs => (results := xs; x)
      | [] => raise ListPair.UnequalLengths;  (* unreachable: the reply is length-checked above *)
  in
    positions |> map (fn pos =>
      if needs_resolution pos then
        let
          val (file, (line, preceding_symbols)) = pop ()
          val file' = if write_to_temp_file then file ^ "~" else file
        in if file = "" then pos
           else Position.make0 line
             (case Position.offset_of pos of SOME off => preceding_symbols + off | NONE => 0)
             (case Position.end_offset_of pos of SOME off => preceding_symbols + off | NONE => 0)
             (the_default "" (Position.label_of pos))
             file'
             (the_default "" (Position.id_of pos)) end
      else pos)
  end;

(* Expand Isabelle path variables and make absolute.
   Fast path: skip if already an absolute path without variables. *)
(* NORMALISE FIRST.  `s` reaches here from outside ML -- Position.file_of, or a path
   Python sent back after receiving it from Theory_Structure.get_theory_file_path, which
   is deliberately a PLATFORM path because Python does native file I/O.  On Windows that
   is `C:\...`, which fails the `isPrefix "/"` test, falls through to Path.explode, and
   raises: Path.check_elem rejects `:` and `\`.  Four SCALA callbacks reach this --
   hover_message, goto_definition, entity_at_position, command_at_position -- so on
   Windows they threw rather than degraded.  Scala itself accepts any spelling and never
   raises: PIDE_Query.live_node matches the exact node name, then the same file, and the
   DB route goes through PIDE_Query.node_path.  The INTERNAL form this returns is what ML
   needs: the key of the per-call cut table, and File.read.

   The two RPC consumers are NOT these: offset_to_line_column and line_column_to_offset
   send the string over MessagePack to position.py, which does `os.path.realpath` and
   `open` in NATIVE Python.  Internal form is exactly wrong there, so those two go through
   rpc_path, which composes this function with a conversion back to platform form.

   ML_System.standard_path is the sanctioned normalisation for a string from outside
   Isabelle's path world (Isabelle uses it that way at Pure/General/path.ML:242-245 in
   val absolute for the OS cwd, and Pure/ML/exn_properties.ML:27 for PolyML's
   messages).  It is shape-agnostic -- C:\x, C:/x and /cygdrive/c/x all normalise,
   `~~/...` passes through untouched -- and on non-Windows it is `fn path => path`, so
   every line below behaves exactly as before on Linux and macOS.

   Note the fast path is applied to the NORMALISED string, which is the point: a Windows
   platform path becomes /cygdrive/c/... and then takes the fast path, as it should. *)
fun expand_path s =
  if s = "" then ""
  else
    let val s = ML_System.standard_path s in
      if String.isPrefix "/" s andalso not (Char.contains s #"$")
        andalso not (String.isSubstring "./" s)
      then s
      else File.absolute_path (Path.explode s)
    end;

(* File path and offset of a position that has been through absolutize_id_based_pos.
   Total: a file expand_path cannot expand (an undefined variable, a character Path.explode
   rejects) maps to "", which every caller answers NONE, instead of raising for the whole
   batch it belongs to. *)
fun file_offset_of pos =
  (the_default "" (try expand_path (the_default "" (Position.file_of pos))),
   the_default 0 (Position.offset_of pos));

(* Extract file path and offset from a Position.T, absolutizing if needed *)
fun pos_file_offset pos =
  file_offset_of (singleton (absolutize_id_based_pos {write_to_temp_file = false}) pos);

(* PIDE live queries via Scala *)

fun goto_definition_pide file_path symbol_offset =
  let
    val input_body =
      XML.Encode.pair XML.Encode.string XML.Encode.int
        (file_path, symbol_offset);
    val yxml = \<^scala>\<open>pide_state.goto_definition\<close>
      (YXML.string_of_body input_body);
    val (def_file, (def_line, (def_offset, def_end_offset))) =
      YXML.parse_body yxml
      |> XML.Decode.pair XML.Decode.string
           (XML.Decode.pair XML.Decode.int
             (XML.Decode.pair XML.Decode.int XML.Decode.int));
  in
    if def_file = "" then NONE
    else SOME (Position.make0 def_line def_offset def_end_offset "" (expand_path def_file) "")
  end;

fun hover_message_pide file_path symbol_offset =
  let
    val input_body =
      XML.Encode.pair XML.Encode.string XML.Encode.int
        (file_path, symbol_offset);
    val yxml = \<^scala>\<open>pide_state.hover_message\<close>
      (YXML.string_of_body input_body);
    val msg = if YXML.detect yxml
      then (warning "hover_message: unexpected YXML markup in result";
            XML.content_of (YXML.parse_body yxml))
      else yxml;
  in
    if msg = "" then NONE
    else SOME msg
  end;

(* Position conversion via Python RPC *)

local open MessagePackBinIO.Pack MessagePackBinIO.Unpack in

val offset_to_line_column_cmd :
    (string * int, (int * int)) Remote_Procedure_Calling.command = {
  name = \<^unchecked_name>\<open>position.offset_to_line_column\<close>,
  arg_schema = packPair (packString, packInt),
  ret_schema = unpackPair (unpackInt, unpackInt),
  callback = [],
  timeout = NONE
}

val line_column_to_offset_cmd :
    (string * int * int, int) Remote_Procedure_Calling.command = {
  name = \<^unchecked_name>\<open>position.line_column_to_offset\<close>,
  arg_schema = packTuple3 (packString, packInt, packInt),
  ret_schema = unpackInt,
  callback = [],
  timeout = NONE
}

end (*local MessagePack*)

(* PLATFORM path, not expand_path's internal form.  The receiver is position.py, which
   does os.path.realpath + open in native Python, so on Windows expand_path's
   /cygdrive/c/... would be a guaranteed FileNotFoundError.  Composing over expand_path
   keeps the variable-expansion and absolutisation it does, then converts at the boundary.

   ML_System.platform_path, NOT File.platform_path.  The latter takes a Path.T, which
   would mean exploding expand_path's result -- but expand_path's fast path deliberately
   returns the string WITHOUT exploding it, and Path.check_elem rejects ' ? * < > | " ,
   every one of which is a legal POSIX filename character.  Routing through Path.T would
   therefore turn working Linux calls into hard errors (neither caller has a \<^try>).
   ML_System.platform_path is string -> string and is `fn path => path` off Windows, so
   this really is a no-op there. *)
fun rpc_path file_path = ML_System.platform_path (expand_path file_path);

fun offset_to_line_column file_path offset =
  Remote_Procedure_Calling.call_command offset_to_line_column_cmd (rpc_path file_path, offset);

fun line_column_to_offset file_path line column =
  Remote_Procedure_Calling.call_command line_column_to_offset_cmd (rpc_path file_path, line, column);

(* Goto definition and hover message: Scala handles both live PIDE + DB fallback *)

fun goto_definition pos =
  let
    val (file, offset) = pos_file_offset pos
    val _ = warning ("goto_definition: file=" ^ file ^ " offset=" ^ string_of_int offset)
  in
    if file = "" orelse offset = 0 then (warning "goto_definition: empty file or zero offset"; NONE)
    else
      let val _ = warning "goto_definition: calling Scala..."
          val result = goto_definition_pide file offset
          val _ = warning ("goto_definition: Scala returned " ^
            (case result of NONE => "NONE" | SOME _ => "SOME(...)"))
      in result end
  end;

fun hover_message pos =
  let val (file, offset) = pos_file_offset pos
  in
    if file = "" orelse offset = 0 then NONE
    else hover_message_pide file offset
  end;

fun entity_at_position_pide file_path symbol_offset =
  let
    val input_body =
      XML.Encode.pair XML.Encode.string XML.Encode.int
        (file_path, symbol_offset);
    val yxml = \<^scala>\<open>pide_state.entity_at_position\<close>
      (YXML.string_of_body input_body);
    val (kind, name) =
      YXML.parse_body yxml
      |> XML.Decode.pair XML.Decode.string XML.Decode.string;
  in
    if kind = "" andalso name = "" then NONE
    else SOME (kind, name)
  end;

fun entity_at_position pos =
  let val (file, offset) = pos_file_offset pos
  in
    if file = "" orelse offset = 0 then NONE
    else entity_at_position_pide file offset
  end;

fun command_at_position_pide file_path symbol_offset =
  let
    val input_body =
      XML.Encode.pair XML.Encode.string XML.Encode.int
        (file_path, symbol_offset);
    val yxml = \<^scala>\<open>pide_state.command_at_position\<close>
      (YXML.string_of_body input_body);
    val (source, (start_offset, end_offset)) =
      YXML.parse_body yxml
      |> XML.Decode.pair XML.Decode.string
           (XML.Decode.pair XML.Decode.int XML.Decode.int);
  in
    if source = "" then NONE
    else SOME (source, start_offset, end_offset)
  end;

(* commands_at_positions, and command_at_position as its singleton case, are
   defined further below, after theory_of_file, so that they can fall back to
   cutting the file with local Outer_Syntax. *)

val get_session_databases : unit -> (string * string) list =
  let
    val cache = Synchronized.cache (fn () =>
      \<^scala>\<open>pide_state.get_session_databases\<close> ""
      |> YXML.parse_body
      |> XML.Decode.list (XML.Decode.pair XML.Decode.string XML.Decode.string));
  in fn () => Synchronized.cache_eval {persistent = false} cache end;

(* The Scala call stays outside any \<^try>: a jar/ML mismatch of the reply fails loudly. *)
fun command_id_at_position file_path symbol_offset =
  \<^scala>\<open>pide_state.command_id_at_position\<close>
    (YXML.string_of_body (XML.Encode.pair XML.Encode.string XML.Encode.int
      (file_path, symbol_offset)))
  |> YXML.parse_body
  |> XML.Decode.option (XML.Decode.pair XML.Decode.string XML.Decode.int);

(* Takes the node name Scala matched, never the caller's spelling of the file:
   Document.command_exec knows a node only by the name PIDE gave it. *)
fun command_state (node_name, cmd_id) =
  \<^try>\<open>
    Document.command_exec (Document.state ()) node_name cmd_id
    |> Option.map (Command.eval_result_state o #1)
    catch _ => NONE\<close>;

fun toplevel_state_at_position file_path symbol_offset =
  Option.mapPartial command_state (command_id_at_position file_path symbol_offset);


(* --- Re-evaluation cache for finished theories --- *)

(* The FILE PROPERTY Position.file sets (position.ML:149 in file_props -- `label` is a
   separate field, read elsewhere in this file via Position.label_of).

   Isabelle has TWO conventions for it, and this picks one deliberately.  A file read
   uses the symbolic form (`~~/src/...`): Build/resources.ML:386 in read_file_node and
   ML/ml_context.ML:277 in eval_file spell it `Position.file (File.symbolic_path path)`.
   A document node instead labels with its node name: PIDE/document.ML:797 in
   presentation_context, PIDE/command.ML:66 in blob_file, Build/resources.ML:392 in
   read_file_node.  Since these positions are produced by re-lexing a file we just read
   from disk -- a file read, not a document node -- the symbolic form is the closer fit,
   and it is what makes messages readable (File.symbolic_path folds prefixes listed in
   ISABELLE_DIRECTORIES, file.ML:51).
   Either way this is cosmetic: the offsets are independent of the name, verified.

   FALLS BACK to the raw string, deliberately.  This value is display text -- it reaches
   error messages and PIDE markup, and callers here only ever read Position.offset_of
   back out -- while Path.explode rejects ' ? * < > | " (path.ML:73 in val illegal_char),
   every one of them legal in a POSIX filename.  A strict version would turn a cosmetic
   improvement into a hard failure on Linux for such a file.  So: nicer name when it is
   derivable, the raw string when it is not.  (Not *exactly* the previous behaviour in
   every case -- where explode succeeds on a degenerate input the string is rewritten,
   e.g. "" becomes "." and "./Foo.thy" becomes "Foo.thy".  None of these reach here:
   File.read rejects them first.) *)
fun file_label file_path =
  the_default file_path
    (try (File.symbolic_path o Path.explode o ML_System.standard_path) file_path);

(* Cache: file_path -> the theory value replayed (its identifier) and the sorted list of
   (symbol_offset, Toplevel.state) it gave.  An entry serves only the theory value it was
   replayed from; another value of the same file (a reload, another context's view) is
   replayed again and replaces it.

   KEYED ON THE NORMALISED PATH.  The same file arrives from the wire spelled either way
   on Windows (`C:\...` as Python sends it, `/cygdrive/c/...` after normalisation), and a
   raw key would file those as two distinct theories -- not a correctness bug, but
   build_reeval_cache replays an entire theory, so a spurious miss costs minutes.
   Identity on Linux and macOS, where the two spellings coincide. *)
fun cache_key file_path = ML_System.standard_path file_path;
val reeval_cache :
    {theory: Context.id, entries: (int * Toplevel.state) list} Symtab.table Synchronized.var =
  Synchronized.var \<^unchecked_name>\<open>PIDE_State.reeval_cache\<close> Symtab.empty;

(* The theories a file lookup searches, in tiers: those the context sees (its own theory
   included), then Build's registry, which holds only theories committed at the end of a
   session build or loaded from a heap -- it misses those the context sees from the session
   being built, from PIDE, or from Isa-REPL.  The first tier with a hit answers. *)
fun known_theories context =
  [Theory.nodes_of (Context.theory_of context),
   map_filter Build.lookup_theory (Build.all_theories ())];

(* Context.get_theory refuses a theory's own name while it is unfinished *)
fun finished thy = can (Context.get_theory {long = true} thy) (Context.theory_long_name thy);

(* The theory in `tiers` whose master file is the given file.

   `file_path` arrives from OUTSIDE ML: Python sends it back as the `context_at` hint,
   having received it from us as Theory_Structure.get_theory_file_path, which is
   deliberately a PLATFORM path because Python does native file I/O.  On Windows that is
   `C:\...`, and Path.explode rejects `:` and `\` (Path.check_elem).  On Linux and macOS
   ML_System.standard_path is the identity, so the round trip was invisible.

   SCOPE, precisely: this covers every caller of file_theory -- theory_of_file (the
   position_context_unpacker / context_at_position route, and reeval_entries) and
   keywords_of_wip_file (the cut of a file on disk behind command_at_position).  The
   Scala lookups of hover_message, goto_definition, entity_at_position and
   command_at_position reach the same platform string through `expand_path`, which was
   fixed separately (see its own comment above).

   Why ML_System.standard_path is the right tool for a string from outside Isabelle's
   path world, and why it is a no-op on Linux and macOS: see expand_path's comment above.
   The reasoning is identical and is not repeated here. *)
(* NONE, not an exception, when the path will not explode or names no file ("/", a bare
   undefined $VAR).  Path.explode rejects ' * ? < > | " and a mid-element $ (path.ML:73
   in val illegal_char) -- all legal in a POSIX filename, and Isabelle itself opens such
   files happily (verified: a theory under a directory named Don't_Touch loads clean).
   standard_path only removes the WINDOWS-specific offenders `:` and `\`; it does nothing
   about these, on any platform.

   This used to raise, and reeval_entries calls it OUTSIDE any \<^try> (below), so
   the error escaped to the RPC boundary as an unexplained "Illegal character" for anyone
   whose project sat under such a directory.  The return type was already an option
   and every caller already handles NONE, so NONE is both the honest and the cheap
   answer.

   SAME FILE, not the same spelling: the master directory is stored folded
   (Resources.begin_theory keeps File.symbolic_path: ~~/src/HOL, ~/..., $AFP/...), the
   target arrives expanded, and either may run through a symlink.  So a candidate must
   have the target's file name (base name ^ ".thy", which also keeps the cost to the few
   theories of that name) and then be the same OS file (File.eq, which is total). *)
fun file_theory tiers file_path =
  let
    fun target_and_name s =
      let val target = Path.explode (ML_System.standard_path s)
      in (target, Path.file_name target) end
    fun theory_file thy =
      Path.append (Resources.master_directory thy)
        (Path.basic (Context.theory_base_name thy ^ ".thy"))
    fun same_file (target, name) thy =
      Context.theory_base_name thy ^ ".thy" = name andalso
        (case try theory_file thy of SOME file => File.eq (file, target) | NONE => false)
  in
    (case try target_and_name file_path of
      NONE => NONE
    | SOME target => get_first (find_first (same_file target)) tiers)
  end;

fun theory_of_file context = file_theory (map (filter finished) (known_theories context));


(* --- WIP command-span path (B1 cross-line completion) ---

   For a "work in progress" .thy file that is NOT covered by a live PIDE node
   nor by a session export DB, Scala's command_at_position returns NONE and the
   Python side degrades to single-line spans.  Here we re-cut the command spans
   locally with Outer_Syntax, so command_at_position can return a full,
   possibly multi-line, command span.

   Coordinate contract: the returned (start, end) are 1-based, file-global
   *symbol* offsets, matching the live branch (src/scala/pide_state.scala:104
   uses var pos = 1).  We obtain this by lexing with Position.file, whose offset starts
   at 1 (Pure/General/position.ML:166 in fun file) -- independently of the name it is
   given, so file_label's fallback cannot affect the coordinate contract. *)

(* Keywords for lexing the WIP file:
     1. preferred: the theory file_theory finds for the file in the context's tiers,
        unfiltered (the context's own unfinished theory included), via
        Thy_Header.get_keywords;
     2. fallback: read the file header, merge the keywords of its known import
        theories with the header's own keyword declarations
        (cf. Pure/Build/build.ML:204-206 in eval_thy). *)
fun keywords_of_wip_file context file_path text =
  let val tiers = known_theories context in
  case file_theory tiers file_path of
    SOME thy => Thy_Header.get_keywords thy
  | NONE =>
      let
        val text_pos = Position.file (file_label file_path)
        val header = Thy_Header.read text_pos text
        (* An import by its exact long name, the first tier that has it; only when no tier
           has it, by base name, in the first tier with any candidate -- one candidate is
           used, several mean we cannot tell which one is meant, so we skip (warning)
           rather than pick one and merge the wrong keywords.  The lookup never falls
           through past an ambiguity. *)
        fun resolve_import (imp, _) =
          (case get_first (find_first (fn thy => Context.theory_long_name thy = imp)) tiers of
            SOME thy => SOME thy
          | NONE =>
              let
                (* a path import ("~~/src/HOL/Nat", "../A") names its theory by the file *)
                val base = Long_Name.base_name (the_default imp (try Thy_Header.import_name imp))
                fun candidates tier =
                  filter (fn thy => Context.theory_base_name thy = base) tier
              in
                (case find_first (not o null) (map candidates tiers) of
                  NONE => NONE
                | SOME [thy] => SOME thy
                | SOME thys =>
                    (warning ("PIDE_State.keywords_of_wip_file: ambiguous import " ^
                      quote imp ^ " matches multiple known theories " ^
                      commas_quote (map Context.theory_long_name thys) ^ "; skipping"); NONE))
              end)
        val parents = map_filter resolve_import (#imports header)
        val base_kws =
          fold (curry Keyword.merge_keywords o Thy_Header.get_keywords) parents
            Keyword.empty_keywords
      in
        Keyword.add_keywords (#keywords header) base_kws
      end
  end;

(* Cut the command spans of a WIP file.
   Returns (source, start_sym_off, end_sym_off) for each real Command_Span,
   where start/end are 1-based file-global symbol offsets.
   Malformed_Span and Ignored_Span are dropped: a half-typed WIP file produces
   Malformed_Span frequently, and matching by kind avoids mis-hitting them.
   NOTE: this differs from the live PIDE path, which builds a Command for every
   span (Ignored ones too).  An offset landing in inter-command whitespace thus
   resolves to that Ignored command under live, but yields NONE here (the caller
   then degrades to a single-line search).  Harmless in practice: query offsets
   land inside commands and hover/definition never probe whitespace. *)
(* Cut a theory source TEXT into command spans (source, start_sym_off,
   end_sym_off) via local Outer_Syntax.  file_path only seeds the lexing Position
   and, with the context, the keyword resolution. *)
fun command_spans_of_text context file_path text : (string * int * int) list =
  \<^try>\<open>
    let
      val tpos = Position.file (file_label file_path)
      val kws = keywords_of_wip_file context file_path text
      val toks = Token.explode kws tpos text
      val spans = Outer_Syntax.parse_spans (Keyword.command_kind kws) toks
      fun is_command span =
        case Command_Span.kind span of Command_Span.Command_Span _ => true | _ => false
      fun span_entry span =
        let
          val span_toks = Command_Span.content span
          val (p1, p2) = Token.range_of span_toks
          val start_off = the_default 0 (Position.offset_of p1)
          (* end uses the span's own token range (Command_Span.range); the
             Python consumer currently keys off start only, so trailing
             whitespace from Command_Span.command_ranges is not needed here. *)
          val end_off = the_default 0 (Position.offset_of p2)
          (* unparse, NOT source_of: source_of yields Isabelle's INTERNAL form, in
             which each consumed delimiter symbol of a string, alt-string, cartouche
             or comment is replaced by Symbol_Pos.DEL (U+007F) as position padding.
             That padding reached the semantic DB as literal U+007F in 238 records
             (SEMANTIC_SEARCH_SITE_PLAN_DONE.md D11/D12).  unparse re-emits the real
             delimiters, one symbol per DEL, so the result stays symbol-aligned with
             the file -- Isabelle_Semantic_Embedding/hover.py relies on that when it
             adds start_off to an index found inside this string.  Whitespace and
             comments are themselves tokens of the span content, so concatenation
             restores the original slice. *)
          val source =
            implode (map Token.unparse span_toks)
        in
          if start_off > 0 then SOME (source, start_off, end_off) else NONE
        end
    in
      map_filter (fn span => if is_command span then span_entry span else NONE) spans
    end
    catch exn =>
      (warning ("PIDE_State.command_spans_of_text: " ^ Runtime.exn_message exn); [])
  \<close>;

(* Only .thy files have Isar command spans.  Entities registered from ML files
   (Method.setup with \<^binding> in an ML_file) carry a position in the .ML file;
   cutting that with Outer_Syntax fails on the theory header and would emit one
   warning per entity, so such files are answered [] without a parse. *)
fun is_thy_file file = String.isSuffix ".thy" file;

(* A whole-file dump: Scala answering the WHOLE theory file as one command's source,
   with start s <= 1.  The cause (measured 2026-11-03) is a heap theory opened in an
   editor: PIDE keeps such a loaded-theory node as one Command.unparsed of the whole file
   and never parses it (Isabelle2026 thy_syntax.scala:150-200, 407-422), and the live
   branch answered from it -- not a degenerate export-DB snapshot, as this comment used to
   say (184k sampled export-DB answers held no dump).  The Scala lookup now skips
   loaded-theory nodes, so this guard should no longer fire; it stays until its removal is
   measured.  Cutting a dump is the disk cut of the file from symbol s on, so the two
   share one cutter: `text` is `file` from `base` on, and the spans come back in
   file-global offsets. *)
fun command_spans_of_text_from context file base text =
  map (fn (src, s, e) => (src, base + s - 1, base + e - 1))
    (command_spans_of_text context file text);

fun command_spans_of_file context file_path : (string * int * int) list =
  if not (is_thy_file file_path) then []
  else
    (* standard_path: file_path arrives from the wire and is a PLATFORM path on Windows.
       Without it Path.explode raises and the \<^try> below turns that into [] plus a
       warning naming this function -- so command spans degrade to nothing there, with the
       cause visible only to whoever reads the warnings. *)
    \<^try>\<open>command_spans_of_text_from context file_path 1
        (File.read (Path.explode (ML_System.standard_path file_path)))
      catch exn =>
        (warning ("PIDE_State.command_spans_of_file: " ^ Runtime.exn_message exn); [])\<close>;

fun find_span off = List.find (fn (_, s, e) => off >= s andalso off < e);

(* The one rule for the command at `offset`: in the cut of the dump Scala returned,
   if any, else in the cut of the file on disk (made only then).  A miss is NONE,
   never the dump: returning it would leak the whole theory as one entity's
   declaring command, the bug this rule exists for. *)
fun span_at offset dump_spans disk_spans =
  (case Option.mapPartial (find_span offset) dump_spans of
    SOME r => SOME r
  | NONE => find_span offset (disk_spans ()));

fun recut_dump_source context file source s offset =
  span_at offset (SOME (command_spans_of_text_from context file s source))
    (fn () => command_spans_of_file context file);

(* What one position still needs after the live-PIDE / export-DB answer: nothing,
   or span_at over the cuts of `file` and of the dump Scala returned, if any. *)
datatype outcome =
    Settled of (string * int * int) option
  | Needs_Cut of {file: string, dump: (string * int) option, offset: int};

fun commands_at_positions context positions =
  let
    fun outcome (file, offset) =
      if file = "" orelse offset = 0 then Settled NONE
      else
        (case command_at_position_pide file offset of
          (* Every real entity command sits after `theory .. begin`, so s > 1 is
             trusted as is; an s <= 1 answer is (or may be) a whole-file dump. *)
          SOME (r as (source, s, _)) =>
            if s > 1 then Settled (SOME r)
            else Needs_Cut {file = file, dump = SOME (source, s), offset = offset}
        | NONE => Needs_Cut {file = file, dump = NONE, offset = offset})
    val outcomes =
      absolutize_id_based_pos {write_to_temp_file = false} positions
      |> map (outcome o file_offset_of)
    (* Every cut this call may need -- per file, the file on disk and each distinct
       dump -- made at most once, and only when span_at asks for it. *)
    val cuts =
      fold (fn Settled _ => I
             | Needs_Cut {file, dump, ...} =>
                Symtab.map_default
                  (file,
                    {disk = Lazy.lazy (fn () => command_spans_of_file context file), dumps = []})
                  (fn (cs as {disk, dumps}) =>
                    (case dump of
                      NONE => cs
                    | SOME (text, base) =>
                        if AList.defined (op =) dumps text then cs
                        else {disk = disk, dumps =
                          (text, Lazy.lazy (fn () =>
                            command_spans_of_text_from context file base text)) :: dumps})))
        outcomes Symtab.empty
    fun lookup {file, dump, offset} =
      let val {disk, dumps} = the (Symtab.lookup cuts file) in
        span_at offset
          (Option.mapPartial (fn (text, _) => Option.map Lazy.force (AList.lookup (op =) dumps text)) dump)
          (fn () => Lazy.force disk)
      end
  in
    outcomes |> map (fn Settled r => r | Needs_Cut c => lookup c)
  end;

fun command_at_position context = singleton (commands_at_positions context);

fun make_command_at_position_callback context : Remote_Procedure_Calling.callback' =
  let open MessagePackBinIO.Pack MessagePackBinIO.Unpack in
    Remote_Procedure_Calling.mk_callback {
      name = \<^unchecked_name>\<open>pide_state.command_at_position\<close>,
      on_interrupt = Remote_Procedure_Calling.Reraise,
      arg_schema = unpackPair (unpackString, unpackInt),
      ret_schema = packOption (packTuple3 (packString, packInt, packInt)),
      function = fn (file, offset) =>
        command_at_position context (Position.make0 0 offset 0 "" file ""),
      (* none, as make_links_callback: cutting a large file takes its time *)
      timeout = NONE
    }
  end;


(* Replay `thy` from its file and its parents: the (offset, state) entries of its commands.
   Recorded in reeval_cache for this theory value only. *)
fun build_reeval_cache thy file_path =
  \<^try>\<open>
    let
      (* standard_path for the same reason as command_spans_of_file above: a raw
         platform path raises here, and this function's \<^try> turns that into []
         plus a warning -- the re-eval cache just stops working on Windows. *)
      val path = Path.explode (ML_System.standard_path file_path)
      val text = File.read path
      (* No try around symbolic_path here -- but NOT because holding a Path.T makes it
         total.  It is not: symbolic_path runs Path.expand, which calls getenv_strict and
         errors on an unset variable (path.ML:232-240 in eval and expand), so a filename
         containing `$` would raise.  It is safe only because File.read on the line above
         runs the same Path.expand and raises first.  Reordering these two lines would
         make that live; file_label exists for the sites that have no such predecessor. *)
      val node = File.symbolic_path path
      val text_pos = Position.file node
      val header = Thy_Header.read text_pos text
      (* As Build's loader does (build.ML:280 in load_thy, 220-222 in eval_thy), with the
         header read here and the parents and long name of the theory being replayed: the
         header holds only the base name, and Universal_Key and Theory_Hash read the
         theory's name, so the replay's keys match those of the real theory. *)
      val fresh_thy =
        Resources.begin_theory
         {name = {node = node, master_dir = Resources.master_directory thy,
            theory = Context.theory_long_name thy},
          pos = #2 (#name header), imports = [], options = #options header,
          keywords = #keywords header, condition_bad = (false, ""), errors = [],
          initiators = []}
          (Theory.parents_of thy)
      val trs =
        Outer_Syntax.parse_text fresh_thy (K {skip_theory = false, theory = fresh_thy})
          text_pos text

      fun step tr (st, acc) =
        let val st' = Toplevel.command_exception tr st
            val offset = the_default 0 (Position.offset_of (Toplevel.pos_of tr))
        in if offset > 0 andalso not (Toplevel.is_ignored tr)
           then (st', (offset, st') :: acc)
           else (st', acc)
        end
      (* Under the header's options (build.ML:278-298 in load_thy) and in interactive
         mode, as 2025-2's `Toplevel.command_exception true` was (toplevel.ML:650 in
         begin_proof spells that `Interactive.setmp true`): a quick_and_dirty `sorry`
         replays instead of failing the whole replay. *)
      val (_, entries_rev) =
        Options.strict_thread_update (Options.update_no_pos (#options header))
          (Interactive.setmp true (fold step trs)) (Toplevel.make_state NONE, [])
      val entries = rev entries_rev
      val _ = writeln ("PIDE_State: cached " ^ string_of_int (length entries) ^
        " states for " ^ Context.theory_long_name thy)
    in
      Synchronized.change reeval_cache (Symtab.update (cache_key file_path,
        {theory = Context.theory_identifier thy, entries = entries}));
      entries
    end
    catch exn => (warning ("PIDE_State.build_reeval_cache: " ^ Runtime.exn_message exn); [])
  \<close>;

(* The replay of the theory the context finds for the file: the cached entries when they
   were replayed from this very theory value, else a fresh replay (passed the theory found,
   not looked up again). *)
fun reeval_entries context file_path =
  (case theory_of_file context file_path of
    NONE => (warning ("PIDE_State.reeval_entries: no loaded theory for " ^ file_path); [])
  | SOME thy =>
      (case Symtab.lookup (Synchronized.value reeval_cache) (cache_key file_path) of
        SOME {theory, entries} =>
          if theory = Context.theory_identifier thy then entries
          else build_reeval_cache thy file_path
      | NONE => build_reeval_cache thy file_path));

fun reeval_context_at_position context file_path symbol_offset =
  let
    val entries = reeval_entries context file_path
  in
    case entries of [] => NONE | _ =>
      let fun find [] = NONE
            | find [(off, st)] = if symbol_offset >= off then SOME st else NONE
            | find ((off1, st1) :: (rest as (off2, _) :: _)) =
                if symbol_offset >= off1 andalso symbol_offset < off2 then SOME st1
                else find rest
      in
        case find entries of
          NONE => NONE
        | SOME st =>
            \<^try>\<open>SOME (Context.Proof (Toplevel.context_of st)) catch _ => NONE\<close>
      end
  end;


type context_at_position_cfg = {re_eval_cache: bool};

fun context_at_position (cfg : context_at_position_cfg) context file_path symbol_offset =
  case toplevel_state_at_position file_path symbol_offset of
    SOME st =>
      \<^try>\<open>SOME (Context.Proof (Toplevel.context_of st)) catch _ => NONE\<close>
  | NONE =>
      if #re_eval_cache cfg
      then reeval_context_at_position context file_path symbol_offset
      else NONE;

fun position_context_unpacker (fallback : Context.generic)
    : Context.generic MessagePackBinIO.Unpack.unpacker =
  let open MessagePackBinIO.Unpack
  in fn src =>
    let val (pos_opt, src') =
      unpackOption (unpackPair (unpackString, unpackInt)) src
    in case pos_opt of
        NONE => (fallback, src')
      | SOME (file, offset) =>
          (case context_at_position {re_eval_cache = true} fallback file offset of
            SOME ctx => (ctx, src')
          | NONE => (fallback, src'))
    end
  end;

end;

(* Register RPC callbacks so Python can call the auto functions.  The rule: a callback is
   global only if its answer reads Scala state alone and looks up no theory.  So
   pide_state.command_at_position, which cuts files under a context's keywords, is per call
   (PIDE_State.make_command_at_position_callback), installed by whoever has the context. *)
local open MessagePackBinIO.Pack MessagePackBinIO.Unpack in

val _ = Theory.setup (Context.theory_map (
  Remote_Procedure_Calling.register_global_callback {
      name = \<^unchecked_name>\<open>pide_state.goto_definition\<close>,
      on_interrupt = Remote_Procedure_Calling.Reraise,
      arg_schema = unpackPair (unpackString, unpackInt),
      ret_schema = packOption (packTuple4 (packString, packInt, packInt, packInt)),
      function = fn (file, offset) =>
        let val pos = Position.make0 0 offset 0 "" file ""
        in PIDE_State.goto_definition pos
           |> Option.map (fn p =>
                (the_default "" (Position.file_of p),
                 the_default 0 (Position.line_of p),
                 the_default 0 (Position.offset_of p),
                 the_default 0 (Position.end_offset_of p)))
        end,
      timeout = SOME (Time.fromSeconds 10)
    }
  #> Remote_Procedure_Calling.register_global_callback {
      name = \<^unchecked_name>\<open>pide_state.hover_message\<close>,
      on_interrupt = Remote_Procedure_Calling.Reraise,
      arg_schema = unpackPair (unpackString, unpackInt),
      ret_schema = packOption packString,
      function = fn (file, offset) =>
        PIDE_State.hover_message (Position.make0 0 offset 0 "" file ""),
      timeout = SOME (Time.fromSeconds 10)
    }
  #> Remote_Procedure_Calling.register_global_callback {
      name = \<^unchecked_name>\<open>pide_state.entity_at_position\<close>,
      on_interrupt = Remote_Procedure_Calling.Reraise,
      arg_schema = unpackPair (unpackString, unpackInt),
      ret_schema = packOption (packPair (packString, packString)),
      function = fn (file, offset) =>
        PIDE_State.entity_at_position (Position.make0 0 offset 0 "" file ""),
      timeout = SOME (Time.fromSeconds 10)
    }
  #> Remote_Procedure_Calling.register_global_callback {
      name = \<^unchecked_name>\<open>pide_state.get_session_databases\<close>,
      on_interrupt = Remote_Procedure_Calling.Reraise,
      arg_schema = unpackUnit,
      ret_schema = packList (packPair (packString, packString)),
      function = fn () => PIDE_State.get_session_databases (),
      timeout = NONE
    }
))

end
