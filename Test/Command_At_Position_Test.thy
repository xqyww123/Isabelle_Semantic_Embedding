theory Command_At_Position_Test
  imports Semantic_Embedding.Semantic_Embedding Link_Finder_Test_Base Command_At_Position_Fixture
begin

section \<open>Test targets\<close>

definition Cmd_Test_A :: bool where \<open>Cmd_Test_A = True\<close>

definition Cmd_Test_B :: bool where \<open>Cmd_Test_B = False\<close>

lemma Cmd_Test_Lemma: \<open>Cmd_Test_A \<or> \<not> Cmd_Test_A\<close>
  by (simp add: Cmd_Test_A_def)

text \<open>One declaration per kind whose expr is the source of its declaring command
  (Test 14): a type, a class, a locale, a theorem collection, a method.\<close>

type_synonym cmd_test_syn = nat

class cmd_test_cls =
  fixes cmd_test_op :: \<open>'a \<Rightarrow> 'a\<close>

locale Cmd_Test_Loc =
  fixes cmd_x :: nat
  assumes cmd_x_pos: \<open>cmd_x > 0\<close>

named_theorems cmd_test_coll \<open>a collection for Test 14\<close>

method_setup cmd_test_meth = \<open>Scan.succeed (fn _ => SIMPLE_METHOD all_tac)\<close>
  \<open>a method for Test 14\<close>

text \<open>T1, T4, T7(b): a definition, then a command whose keyword only a context importing
  Command_At_Position_Fixture knows.\<close>

definition cap_before :: bool where \<open>cap_before = True\<close>

cap_fixture_cmd cap_arg

section \<open>Tests\<close>

ML \<open>
let
  (* ---- helpers ---- *)
  val context = Context.Proof \<^context>
  val const_space = Proof_Context.consts_of \<^context> |> Consts.space_of
  val pos_A = Name_Space.the_entry_pos const_space @{const_name Cmd_Test_A}
  val pos_B = Name_Space.the_entry_pos const_space @{const_name Cmd_Test_B}

  (* ---- Test 1: basic lookup returns SOME ---- *)
  val result_A = PIDE_State.command_at_position context pos_A
  val _ = @{assert} (is_some result_A)
  val (src_A, start_A, end_A) = the result_A
  val _ = writeln ("Test 1 - command_at_position returns SOME for Cmd_Test_A: OK")
  val _ = writeln ("  source: " ^ src_A)
  val _ = writeln ("  span: [" ^ string_of_int start_A ^ ", " ^ string_of_int end_A ^ ")")

  (* ---- Test 2: source contains the definition keyword and name ---- *)
  val _ = @{assert} (String.isSubstring "definition" src_A)
  val _ = @{assert} (String.isSubstring "Cmd_Test_A" src_A)
  val _ = writeln ("Test 2 - source contains 'definition' and 'Cmd_Test_A': OK")

  (* ---- Test 3: second definition is at a different span ---- *)
  val result_B = PIDE_State.command_at_position context pos_B
  val _ = @{assert} (is_some result_B)
  val (src_B, start_B, end_B) = the result_B
  val _ = @{assert} (String.isSubstring "Cmd_Test_B" src_B)
  val _ = @{assert} (start_B > start_A)
  val _ = writeln ("Test 3 - Cmd_Test_B command is after Cmd_Test_A: OK")
  val _ = writeln ("  span A: [" ^ string_of_int start_A ^ ", " ^ string_of_int end_A ^ ")")
  val _ = writeln ("  span B: [" ^ string_of_int start_B ^ ", " ^ string_of_int end_B ^ ")")

  (* ---- Test 4: commands do not overlap ---- *)
  val _ = @{assert} (end_A <= start_B)
  val _ = writeln ("Test 4 - commands do not overlap (end_A <= start_B): OK")

  (* ---- Test 5: span is non-empty ---- *)
  val _ = @{assert} (end_A > start_A)
  val _ = @{assert} (end_B > start_B)
  val _ = writeln ("Test 5 - spans are non-empty: OK")

  (* ---- Test 6: Position.none returns NONE ---- *)
  val _ = @{assert} (is_none (PIDE_State.command_at_position context Position.none))
  val _ = writeln ("Test 6 - Position.none returns NONE: OK")

  (* ---- Test 7: lemma command ---- *)
  val fact_space = Proof_Context.facts_of \<^context> |> Facts.space_of
  val pos_lemma = Name_Space.the_entry_pos fact_space \<^unchecked_name>\<open>Command_At_Position_Test.Cmd_Test_Lemma\<close>
  val result_lemma = PIDE_State.command_at_position context pos_lemma
  val _ = @{assert} (is_some result_lemma)
  val (src_lemma, _, _) = the result_lemma
  val _ = @{assert} (String.isSubstring "lemma" src_lemma)
  val _ = @{assert} (String.isSubstring "Cmd_Test_Lemma" src_lemma)
  val _ = writeln ("Test 7 - lemma command source: OK")
  val _ = writeln ("  source: " ^ src_lemma)

  (* ---- Test 8: query via file + offset (the RPC path) ---- *)
  (* Resolve pos_A to get an absolute file + offset, then query again *)
  val [abs_A] = PIDE_State.absolutize_id_based_pos {write_to_temp_file = false} [pos_A]
  val file_A = the (Position.file_of abs_A)
  val off_A = the (Position.offset_of abs_A)
  val direct_result = PIDE_State.command_at_position context abs_A
  val _ = @{assert} (is_some direct_result)
  val (direct_src, _, _) = the direct_result
  val _ = @{assert} (String.isSubstring "Cmd_Test_A" direct_src)
  val _ = writeln ("Test 8 - query via absolute file+offset: OK")

  (* ---- Test 9: the disk cut returns a SINGLE command, never the whole file ----
     When neither live PIDE state nor an export DB answers (every lookup under
     Isa-REPL / isabelle build), commands_at_positions cuts the file on disk with
     local Outer_Syntax (command_spans_of_file).  A position inside Cmd_Test_B
     must cut to ONLY that command's source -- not the whole file (which would
     also carry Cmd_Test_A and Cmd_Test_Lemma). *)
  val [abs_B] = PIDE_State.absolutize_id_based_pos {write_to_temp_file = false} [pos_B]
  val file_B = the (Position.file_of abs_B)
  val off_B = the (Position.offset_of abs_B)
  fun disk_cut off =
    List.find (fn (_, s, e) => off >= s andalso off < e) (PIDE_State.command_spans_of_file context file_B)
  val wip_B = disk_cut off_B
  val _ = @{assert} (is_some wip_B)
  val (wip_src_B, _, _) = the wip_B
  val _ = @{assert} (String.isSubstring "Cmd_Test_B" wip_src_B)
  val _ = @{assert} (not (String.isSubstring "Cmd_Test_A" wip_src_B))
  val _ = @{assert} (not (String.isSubstring "Cmd_Test_Lemma" wip_src_B))
  val _ = writeln ("Test 9 - the disk cut returns only Cmd_Test_B, not the whole file: OK")

  (* ---- Test 10: a MISS is NONE, never the whole file ----
     An offset far past EOF finds no span in the disk cut, and the whole lookup
     -- through commands_at_positions, whichever path answers -- is NONE. *)
  val file_size = size (File.read (Path.explode file_B))
  val _ = @{assert} (is_none (disk_cut (file_size + 1000)))
  val past_eof = Position.make0 0 (file_size + 1000) 0 "" file_B ""
  val _ = @{assert} (PIDE_State.commands_at_positions context [past_eof] = [NONE])
  val _ = writeln ("Test 10 - a lookup past EOF is NONE (no whole-file leak): OK")

  (* ---- Test 11: recut_dump_source -- the re-cut of a degenerate whole-file
     dump, the branch the whole-theory-leak fix changed: PIDE_State.span_at, the
     one rule commands_at_positions also runs, over a cut of the dump with the
     disk cut as the fallback.  Tests 1-10 never enter it (it needs a whole-file
     dump, from a loaded-theory node: see the comment on the whole-file dump in
     Tools/pide_state.ML; the Scala lookup now skips such nodes), so drive it with a
     SYNTHETIC dump and assert it NEVER returns the whole `source`: (a) an
     offset inside the 2nd command returns ONLY that command; (b) an offset past
     the end (a re-cut miss) falls to the disk cut, which fails on the absent
     file and yields [] -- so NONE, not the source. *)
  val dump_src =
    "theory Synthetic_Dump\n" ^
    "  imports Main\n" ^
    "begin\n\n" ^
    "definition synth_alpha :: bool where \"synth_alpha = True\"\n\n" ^
    "definition synth_beta :: bool where \"synth_beta = False\"\n\n" ^
    "end\n"
  (* A path that does not exist: the re-cut works on `dump_src` itself and
     resolves keywords from its own header (imports Main); the disk fallback
     reads this absent file -> [] (with a warning) -> NONE. *)
  val dump_file = "/nonexistent/Synthetic_Dump.thy"
  fun off_of needle =  (* 1-based symbol offset of needle in dump_src (ASCII) *)
    Substring.size (#1 (Substring.position needle (Substring.full dump_src))) + 1
  (* (a) hit inside the 2nd command *)
  val hit = PIDE_State.recut_dump_source context dump_file dump_src 1 (off_of "synth_beta = False")
  val _ = @{assert} (is_some hit)
  val (hit_src, _, _) = the hit
  val _ = @{assert} (String.isSubstring "synth_beta" hit_src)
  val _ = @{assert} (not (String.isSubstring "synth_alpha" hit_src))
  val _ = @{assert} (not (String.isSubstring "theory Synthetic_Dump" hit_src))
  val _ = @{assert} (hit_src <> dump_src)
  val _ = writeln ("Test 11a - recut_dump_source hit returns only the single command: OK")
  (* (b) a re-cut miss must NOT return the whole source *)
  val miss = PIDE_State.recut_dump_source context dump_file dump_src 1 (size dump_src + 50)
  val _ = @{assert} (is_none miss)
  val _ = writeln ("Test 11b - recut_dump_source miss returns NONE, not the whole theory: OK")

  (* ---- Test 12: a non-.thy file is answered NONE without parsing ----
     Entities registered from ML (Method.setup with \<^binding> in an ML_file)
     carry a position in the .ML file.  Cutting that with Outer_Syntax fails on
     the theory header and used to emit one warning per entity; the disk cut now
     declines non-.thy files up front.  Use a real, readable .ML file so a
     regression would actually reach the parser (and its warning). *)
  val ml_file = File.platform_path (Path.explode "~~/src/Pure/General/position.ML")
  val _ = @{assert} (String.isSuffix ".ML" ml_file)
  val _ = @{assert} (null (PIDE_State.command_spans_of_file context ml_file))
  val ml_pos = Position.make0 0 100 0 "" ml_file ""
  val _ = @{assert} (PIDE_State.commands_at_positions context [ml_pos] = [NONE])
  val _ = writeln ("Test 12 - a .ML file is answered NONE without a parse: OK")

  (* ---- Test 13: the batch form agrees with the singleton form, keeps the
     argument order, and answers a Position.none slot and a .ML slot NONE in
     place, leaving their neighbours alone.  build_entries resolves a whole
     theory's command sources through commands_at_positions and sends
     Position.none for every entry whose expr it computes itself, so those slots
     must come back NONE without disturbing the others; the .ML slot puts a
     second file into the per-call cut table. *)
  val batch_in = [pos_A, Position.none, pos_lemma, ml_pos, pos_B, Position.none]
  val batch_out = PIDE_State.commands_at_positions context batch_in
  val _ = @{assert} (batch_out = map (PIDE_State.command_at_position context) batch_in)
  val _ = @{assert} (map is_some batch_out = [true, false, true, false, true, false])
  val _ = @{assert} (batch_out = [result_A, NONE, result_lemma, NONE, result_B, NONE])
  val _ = writeln ("Test 13 - commands_at_positions = map command_at_position, order kept, NONE slots in place: OK")

  (* ---- Test 14: build_entries, one entry per kind ----
     The kinds whose expr is their declaring command's source (type, class,
     locale, theorem collection, method) get exactly the singleton lookup's
     source; the kinds whose expr is computed (a constant's type, a theorem's
     statement) get that and never a command source.  A slot mix-up between the
     two groups, or a kind dropped from the source-carrying group, shows here. *)
  val ctx = Context.Proof \<^context>
  val thy = \<^theory>
  val q = Long_Name.qualify "Command_At_Position_Test"
  fun entry space entity name =
    (entity, Semantic_Store.Declared name, Name_Space.the_entry_pos space name,
     Universal_Key.key_of NONE ctx entity)
  val thm_entity = Universal_Key.Theorem @{thm Cmd_Test_Lemma}
  val raw =
    [entry const_space (Universal_Key.Constant @{const_name Cmd_Test_A}) @{const_name Cmd_Test_A},
     entry (Sign.type_space thy) (Universal_Key.Type (q "cmd_test_syn")) (q "cmd_test_syn"),
     (thm_entity, Semantic_Store.Declared (q "Cmd_Test_Lemma"), pos_lemma,
      Universal_Key.key_of NONE ctx thm_entity),
     entry (Sign.class_space thy) (Universal_Key.Class (q "cmd_test_cls")) (q "cmd_test_cls"),
     entry (Locale.locale_space thy) (Universal_Key.Locale (q "Cmd_Test_Loc")) (q "Cmd_Test_Loc"),
     entry fact_space (Universal_Key.Theorem_Collection (q "cmd_test_coll")) (q "cmd_test_coll"),
     entry (Method.method_space ctx) (Universal_Key.Method (q "cmd_test_meth")) (q "cmd_test_meth")]
  val (entries, _) = Semantic_Store.build_entries ctx raw
  val [e_const, e_type, e_thm, e_class, e_loc, e_coll, e_meth] = map #3 entries
  fun source_of (_, _, pos, _) =
    Semantic_Store.strip_trailing_begin (#1 (the (PIDE_State.command_at_position context pos)))
  val _ = @{assert} (e_const = "bool")
  val _ = @{assert} (String.isSubstring "Cmd_Test_A" e_thm andalso not (String.isSubstring "lemma" e_thm))
  val _ = @{assert} (e_type = source_of (nth raw 1) andalso String.isSubstring "type_synonym cmd_test_syn" e_type)
  val _ = @{assert} (e_class = source_of (nth raw 3) andalso String.isSubstring "class cmd_test_cls" e_class)
  val _ = @{assert} (e_loc = source_of (nth raw 4) andalso String.isSubstring "locale Cmd_Test_Loc" e_loc
                     andalso String.isSubstring "cmd_x_pos" e_loc)
  val _ = @{assert} (e_coll = source_of (nth raw 5) andalso String.isSubstring "named_theorems cmd_test_coll" e_coll)
  val _ = @{assert} (e_meth = source_of (nth raw 6) andalso String.isSubstring "method_setup cmd_test_meth" e_meth)
  (* T2: declaring_commands gives the same sources, resolving each name in the context *)
  val _ = @{assert}
    (map (Option.map #1) (Semantic_Store.declaring_commands ctx
       [(Universal_Key.TypeK, q "cmd_test_syn"), (Universal_Key.ClassK, q "cmd_test_cls"),
        (Universal_Key.LocaleK, q "Cmd_Test_Loc"), (Universal_Key.Theorem_CollectionK, q "cmd_test_coll"),
        (Universal_Key.MethodK, q "cmd_test_meth")])
     = map SOME [e_type, e_class, e_loc, e_coll, e_meth])
  val _ = writeln ("Test 14 - build_entries: every source-carrying kind = its command source, computed kinds untouched: OK")

in
  writeln "\n=== All PIDE_State.command_at_position tests passed ==="
end
\<close>

text \<open>Isabelle2026 port: the cut under a context (T1, T2), the replay (tests-3 a), hand-built
  theory values (T7), total lookups (B), the export-DB route (T6(ii)) and the Python callers
  (T4).  In a batch build no live node exists, so this file is answered by the cut of the file
  on disk, and a heap theory file by its session DB.\<close>

ML \<open>
local
  fun check msg b = if b then () else error ("Command_At_Position_Test (port): " ^ msg)
  val seeing = Context.Proof \<^context>
  val pure = Context.Theory \<^theory>\<open>Pure\<close>
  val const_space = Proof_Context.consts_of \<^context> |> Consts.space_of
  val pos_before = Name_Space.the_entry_pos const_space \<^const_name>\<open>cap_before\<close>
  val this_file = the (Position.file_of pos_before)
  val text = File.read (Path.explode this_file)
  (* 1-based symbol offset of the first occurrence of `needle` in `txt` *)
  fun offset_in txt needle =
    let val (prefix, rest) = Substring.position needle (Substring.full txt)
    in if Substring.isEmpty rest then error ("no " ^ quote needle)
       else length (Symbol.explode (Substring.string prefix)) + 1 end
       (* length, not Symbol.length: a position offset counts every symbol, and
          Symbol.length skips some (List.thy's \<^marker> etc.) *)
  val pos_use = Position.make0 0 (offset_in text "cap_fixture_cmd cap_arg") 0 "" this_file ""
  fun src (SOME (s, _, _)) = SOME s | src NONE = NONE

  (* T1: the seeing context cuts exactly; Pure, which does not see the fixture, does not *)
  val at_before = PIDE_State.command_at_position seeing pos_before
  val at_use = PIDE_State.command_at_position seeing pos_use
  val _ = check ("T1 cap_before exact: " ^ \<^make_string> at_before)
    (case src at_before of
      SOME s => String.isPrefix "definition cap_before" s andalso not (String.isSubstring "cap_fixture_cmd" s)
    | NONE => false)
  val _ = check ("T1 cap_fixture_cmd exact: " ^ \<^make_string> at_use)
    (case src at_use of SOME s => String.isPrefix "cap_fixture_cmd cap_arg" s | NONE => false)
  val _ = check "T1 Pure differs at cap_before" (PIDE_State.command_at_position pure pos_before <> at_before)
  val _ = check "T1 Pure differs at the use" (PIDE_State.command_at_position pure pos_use <> at_use)

  (* T2: declaring_commands resolves and cuts in one context *)
  val _ =
    (case Semantic_Store.declaring_commands seeing
        [(Universal_Key.ConstantK, \<^const_name>\<open>cap_before\<close>),
         (Universal_Key.TheoremK, \<^unchecked_name>\<open>HOL.refl\<close>),
         (Universal_Key.ConstantK, \<^unchecked_name>\<open>Command_At_Position_Test.no_such_constant\<close>)] of
      [SOME (s, f, _), SOME (s_refl, f_refl, _), NONE] =>
        (check "T2 cap_before = T1's cut"
           (SOME s = Option.map Semantic_Store.strip_trailing_begin (src at_before));
         check ("T2 its file: " ^ f) (String.isSuffix "/Command_At_Position_Test.thy" f);
         check ("T2 HOL.refl: " ^ s_refl) (String.isSubstring "refl" s_refl);
         check ("T2 HOL.refl's file: " ^ f_refl) (String.isSuffix "/src/HOL/HOL.thy" f_refl))
    | r => check ("T2 shape: " ^ \<^make_string> r) false)

  (* tests-3 a: the replay of a finished ancestor gives its context; this unfinished theory
     is never replayed *)
  val fixture = \<^theory>\<open>Command_At_Position_Fixture\<close>
  val fixture_file = Theory_Structure.get_theory_file_path fixture
  (* inside its ML command: the state after it, before `end` (which has no context) *)
  val replayed =
    PIDE_State.context_at_position {re_eval_cache = true} seeing fixture_file
      (offset_in (File.read (Path.explode fixture_file)) \<^unchecked_name>\<open>Outer_Syntax.command\<close>)
  val _ = check "tests-3 the fixture replays, its keyword in scope"
    (case replayed of
      SOME c => Keyword.is_command (Thy_Header.get_keywords (Context.theory_of c)) "cap_fixture_cmd"
    | NONE => false)
  val _ = check "ml-1 the replay carries the fixture's long name"
    (case replayed of
      SOME c => Context.theory_long_name (Context.theory_of c) = Context.theory_long_name fixture
    | NONE => false)
  val _ = check "tests-3 this unfinished theory is not replayed"
    (is_none (PIDE_State.context_at_position {re_eval_cache = true} seeing this_file
      (case at_before of SOME (_, s, _) => s | NONE => 1)))

  (* T7: hand-built theory values *)
  fun hand_built name node master parents keywords =
    Resources.begin_theory
      {name = {node = node, master_dir = master, theory = name}, pos = Position.none,
       imports = [], options = [], keywords = keywords, condition_bad = (false, ""), errors = [],
       initiators = []} parents
  val nat = \<^theory>\<open>Nat\<close>
  val fake_nat =
    hand_built \<^unchecked_name>\<open>Semantic_Embedding_Test.Nat\<close> (Theory_Structure.get_theory_file_path nat)
      (Resources.master_directory nat) [\<^theory>\<open>Pure\<close>] []
    |> Theory.end_theory
  val _ = check "T7a the context's own tier answers before the registry"
    (Option.map Context.theory_long_name
      (PIDE_State.theory_of_file (Context.Theory fake_nat) (Theory_Structure.get_theory_file_path nat))
     = SOME \<^unchecked_name>\<open>Semantic_Embedding_Test.Nat\<close>)
  val header =
    Thy_Header.read Position.none
      "theory Command_At_Position_Test imports Pure keywords \"cap_fixture_cmd\" :: thy_decl begin"
  val synthetic =
    hand_built \<^unchecked_name>\<open>Synthetic.Command_At_Position_Test\<close> this_file (Resources.master_directory \<^theory>)
      [\<^theory>\<open>Pure\<close>] (#keywords header)
  val _ = check "T7b the keyword pass sees an unfinished theory"
    (PIDE_State.command_at_position (Context.Theory synthetic) pos_before = at_before)

  (* B: odd paths give NONE and raise nothing *)
  val odd = Position.make0 0 1 0 "" "/tmp/it's/LN.thy" ""
  val undef = Position.make0 0 1 0 "" "$LN_UNDEFINED/A.thy" ""
  val _ = check "B1 it's"
    (is_none (PIDE_State.hover_message odd) andalso is_none (PIDE_State.goto_definition odd) andalso
     is_none (PIDE_State.entity_at_position odd) andalso
     is_none (PIDE_State.command_at_position seeing odd))
  val _ = check "B2 an undefined variable"
    (is_none (PIDE_State.command_id_at_position "$LN_UNDEFINED/A.thy" 1) andalso
     is_none (PIDE_State.toplevel_state_at_position "$LN_UNDEFINED/A.thy" 1) andalso
     is_none (PIDE_State.hover_message undef) andalso
     is_none (PIDE_State.command_at_position seeing undef))
  val _ = check "ml-3 a path that names no file"
    (is_none (PIDE_State.theory_of_file seeing "/") andalso
     is_none (PIDE_State.theory_of_file seeing "$LN_UNDEFINED"))

  (* ml-5: a file loaded nowhere that imports the fixture by a path gets its keyword *)
  val _ =
    Isabelle_System.with_tmp_dir "cap_path_import" (fn dir =>
      let
        val fixture_import = Path.implode (Path.drop_ext (Path.explode fixture_file))
        val path_text =
          "theory CAP_Path_Import\n  imports " ^ quote fixture_import ^ "\nbegin\n\n" ^
          "definition cap_p :: nat where \"cap_p = 0\"\n\ncap_fixture_cmd cap_arg\n\nend\n"
        val file = Path.append dir (Path.basic "CAP_Path_Import.thy")
        val _ = File.write file path_text
        val pos =
          Position.make0 0 (offset_in path_text "cap_fixture_cmd cap_arg") 0 ""
            (File.platform_path file) ""
        val at = PIDE_State.command_at_position seeing pos
      in
        check ("ml-5 a path import's keyword cuts its own span: " ^ \<^make_string> at)
          (case src at of SOME s => String.isPrefix "cap_fixture_cmd cap_arg" s | NONE => false)
      end)

  (* T6(ii): the export-DB route answers a heap theory file by the theory the heap loaded from it *)
  fun raw_cap file off =
    \<^scala>\<open>pide_state.command_at_position\<close>
      (YXML.string_of_body (XML.Encode.pair XML.Encode.string XML.Encode.int (file, off)))
    |> YXML.parse_body |> XML.Decode.pair XML.Decode.string (XML.Decode.pair XML.Decode.int XML.Decode.int)
  fun raw_entity file off =
    \<^scala>\<open>pide_state.entity_at_position\<close>
      (YXML.string_of_body (XML.Encode.pair XML.Encode.string XML.Encode.int (file, off)))
    |> YXML.parse_body |> XML.Decode.pair XML.Decode.string XML.Decode.string
  val expand = File.platform_path o Path.expand o Path.explode
  val lifting = expand "~~/src/HOL/Lifting.thy"
  val _ = check "T6(ii)-b Lifting.thy at 137" (raw_entity lifting 137 = ("command", "section"))
  val _ = check "T6(ii)-b Nat.thy at 500"
    (raw_cap (expand "~~/src/HOL/Nat.thy") 500 = ("text \<open>Type definition\<close>", (480, 502)))
  val list_file = expand "~~/src/HOL/List.thy"
  val list_syms = Symbol.explode (File.read (Path.explode list_file))
  val rotate_at = offset_in (File.read (Path.explode list_file)) "definition rotate"
  val _ =
    (case raw_cap list_file (rotate_at + 3) of
      (s, (b, e)) =>
        let val slice = implode (take (e - b) (drop (b - 1) list_syms)) in
          check ("T6(ii)-d List.rotate is the disk slice: " ^
              \<^make_string> {b = b, e = e, rotate_at = rotate_at, src = s, slice = slice})
            (b = rotate_at andalso s = slice andalso String.isSubstring "\<Rightarrow>" s)
        end)
  val rpc_file = Theory_Structure.get_theory_file_path \<^theory>\<open>Remote_Procedure_Calling\<close>
  val rpc_text = File.read (Path.explode rpc_file)
  val rpc_at =
    offset_in rpc_text "ML_file" + size "ML_file" + 2
  val _ =
    (case raw_cap rpc_file rpc_at of
      (s, (b, e)) =>
        check ("T6(ii)-e a theory compiled flat into the heap: " ^ s)
          (s <> "" andalso b > 1 andalso
           s = implode (take (e - b) (drop (b - 1) (Symbol.explode rpc_text)))))
in
  val _ = Isabelle_System.with_tmp_dir "cap_db" (fn dir =>
    let
      (* T6(ii)-a: a file named like a heap theory is not answered from that theory's DB *)
      val padding = implode (replicate 30 "padding ")
      val probe_text =
        "theory Lifting imports Pure begin\n\ntext \<open>" ^ padding ^ "\<close>\n\n" ^
        "definition lifting_probe :: prop where \"lifting_probe \<equiv> PROP A\"\n\nend\n"
      val d = Path.append dir (Path.basic "D")
      val _ = Isabelle_System.make_directory d
      val probe = Path.append d (Path.basic \<^unchecked_name>\<open>Lifting.thy\<close>)
      val _ = File.write probe probe_text
      val o' = offset_in probe_text "lifting_probe ::"
      val probe_file = File.platform_path probe
      val (heap_src, (heap_s, _)) = raw_cap lifting o'
      val _ = check "T6(ii)-a self-check: HOL Lifting answers there" (heap_src <> "" andalso heap_s > 1)
      val _ = check "T6(ii)-a the probe gets no DB answer" (raw_cap probe_file o' = ("", (0, 0)))
      val _ = check "T6(ii)-a the disk cut answers with the probe's own command"
        (case PIDE_State.command_at_position seeing (Position.make0 0 o' 0 "" probe_file "") of
          SOME (s, _, _) => String.isSubstring "definition lifting_probe" s andalso s <> heap_src
        | NONE => false)
      (* T6(ii)-c: a byte copy of a heap theory file is not answered from its DB *)
      val copy = Path.append d (Path.basic \<^unchecked_name>\<open>Lifting_Copy.thy\<close>)
      val _ = File.write copy (File.read (Path.explode lifting))
      val _ = check "T6(ii)-c the copy gets no DB answer"
        (raw_entity (File.platform_path copy) 137 = ("", ""))
      (* H-c: through a directory symlink, a heap theory file is still that file *)
      val hol_link = Path.append d (Path.basic \<^unchecked_name>\<open>hol\<close>)
      val _ = Isabelle_System.bash ("ln -s " ^ File.bash_path (Path.explode "~~/src/HOL") ^ " " ^
        File.bash_path hol_link)
      val nat_via_link = File.platform_path (Path.append hol_link (Path.basic \<^unchecked_name>\<open>Nat.thy\<close>))
      val _ = check "H-c Nat.thy through a symlinked directory"
        (raw_cap nat_via_link 500 = raw_cap (expand "~~/src/HOL/Nat.thy") 500)
    in () end)
  (* T4: the Python callers, through the per-call callbacks a hosting command installs *)
  val py =
    cat_lines
      ["from Isabelle_Semantic_Embedding.semantics import _definition_of_name",
       "from Isabelle_Semantic_Embedding.hover import command_at_position",
       "from Isabelle_RPC_Host.universal_key import EntityKind",
       "from Isabelle_RPC_Host.position import IsabellePosition",
       "use = 'cap_fixture_cmd cap_arg'",
       "d = await _definition_of_name(connection, EntityKind.CONSTANT, " ^
         quote \<^const_name>\<open>cap_before\<close> ^ ")",
       "c = await command_at_position(IsabellePosition(0, " ^
         string_of_int (the (Position.offset_of pos_use)) ^ ", " ^ quote this_file ^ "), connection)",
       "ds = 'None' if d is None else str('cap_before' in d[0] and 'cap_fixture_cmd' not in d[0])",
       "cs = 'None' if c is None else f'{c[1]}|{c[2]}|{c[0].startswith(use)}'",
       "return ds + '|' + cs"]
  val callbacks =
    [Semantic_Store.make_declaring_commands_callback (Context_Callbacks.static_context_unpacker seeing),
     PIDE_State.make_command_at_position_callback seeing]
  val expected_use =
    (case at_use of SOME (_, b, e) => string_of_int b ^ "|" ^ string_of_int e | NONE => "?")
  val _ = check "T4 through Python"
    (Run_Python.run_with callbacks py = SOME ("True|" ^ expected_use ^ "|True"))
  (* hover.command_at_position degrades to None when no hosting command installed it *)
  val py_hover_only =
    cat_lines
      ["from Isabelle_Semantic_Embedding.hover import command_at_position",
       "from Isabelle_RPC_Host.position import IsabellePosition",
       "c = await command_at_position(IsabellePosition(0, " ^
         string_of_int (the (Position.offset_of pos_use)) ^ ", " ^ quote this_file ^ "), connection)",
       "return 'None' if c is None else 'answered'"]
  val _ = check "T4 without the callback: None, and nothing raised"
    (Run_Python.run_with [] py_hover_only = SOME "None")
  val _ = writeln "Command_At_Position_Test (port): all checks passed"
end
\<close>

ML \<open>
(* theory_of_file resolves a file against the context first.  Link_Finder_Test_Base is
   loaded by this session build, so Build's registry holds it only once the session ends:
   a context that does not see it (Pure) finds nothing, while the registry alone answers
   for a heap theory (tests-3 b).  This theory itself is unfinished, so no lookup may
   replay it. *)
let
  val context = Context.Proof \<^context>
  val pure = Context.Theory \<^theory>\<open>Pure\<close>
  val base = \<^theory>\<open>Link_Finder_Test_Base\<close>
  fun found context thy =
    Option.map Context.theory_long_name
      (PIDE_State.theory_of_file context (Theory_Structure.get_theory_file_path thy))
in
  \<^assert> (found context base = SOME (Context.theory_long_name base));
  \<^assert> (is_none (found pure base));
  \<^assert> (is_none (found context \<^theory>));
  \<^assert> (found pure \<^theory>\<open>Semantic_Embedding\<close> = SOME (Context.theory_long_name \<^theory>\<open>Semantic_Embedding\<close>))
end
\<close>

end
