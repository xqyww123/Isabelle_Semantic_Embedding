theory Command_At_Position_Test
  imports Semantic_Embedding.Semantic_Embedding
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

section \<open>Tests\<close>

ML \<open>
let
  (* ---- helpers ---- *)
  val const_space = Proof_Context.consts_of \<^context> |> Consts.space_of
  val pos_A = Name_Space.the_entry const_space @{const_name Cmd_Test_A} |> #pos
  val pos_B = Name_Space.the_entry const_space @{const_name Cmd_Test_B} |> #pos

  (* ---- Test 1: basic lookup returns SOME ---- *)
  val result_A = PIDE_State.command_at_position pos_A
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
  val result_B = PIDE_State.command_at_position pos_B
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
  val _ = @{assert} (is_none (PIDE_State.command_at_position Position.none))
  val _ = writeln ("Test 6 - Position.none returns NONE: OK")

  (* ---- Test 7: lemma command ---- *)
  val fact_space = Proof_Context.facts_of \<^context> |> Facts.space_of
  val pos_lemma = Name_Space.the_entry fact_space "Command_At_Position_Test.Cmd_Test_Lemma" |> #pos
  val result_lemma = PIDE_State.command_at_position pos_lemma
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
  val direct_result = PIDE_State.command_at_position abs_A
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
    List.find (fn (_, s, e) => off >= s andalso off < e) (PIDE_State.command_spans_of_file file_B)
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
  val _ = @{assert} (PIDE_State.commands_at_positions [past_eof] = [NONE])
  val _ = writeln ("Test 10 - a lookup past EOF is NONE (no whole-file leak): OK")

  (* ---- Test 11: recut_dump_source -- the re-cut of a degenerate whole-file
     dump, the branch the whole-theory-leak fix changed: PIDE_State.span_at, the
     one rule commands_at_positions also runs, over a cut of the dump with the
     disk cut as the fallback.  Tests 1-10 never enter it (it needs an s <= 1
     export-DB snapshot, which no live theory produces), so drive it with a
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
  val hit = PIDE_State.recut_dump_source dump_file dump_src 1 (off_of "synth_beta = False")
  val _ = @{assert} (is_some hit)
  val (hit_src, _, _) = the hit
  val _ = @{assert} (String.isSubstring "synth_beta" hit_src)
  val _ = @{assert} (not (String.isSubstring "synth_alpha" hit_src))
  val _ = @{assert} (not (String.isSubstring "theory Synthetic_Dump" hit_src))
  val _ = @{assert} (hit_src <> dump_src)
  val _ = writeln ("Test 11a - recut_dump_source hit returns only the single command: OK")
  (* (b) a re-cut miss must NOT return the whole source *)
  val miss = PIDE_State.recut_dump_source dump_file dump_src 1 (size dump_src + 50)
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
  val _ = @{assert} (null (PIDE_State.command_spans_of_file ml_file))
  val ml_pos = Position.make0 0 100 0 "" ml_file ""
  val _ = @{assert} (PIDE_State.commands_at_positions [ml_pos] = [NONE])
  val _ = writeln ("Test 12 - a .ML file is answered NONE without a parse: OK")

  (* ---- Test 13: the batch form agrees with the singleton form, keeps the
     argument order, and answers a Position.none slot and a .ML slot NONE in
     place, leaving their neighbours alone.  build_entries resolves a whole
     theory's command sources through commands_at_positions and sends
     Position.none for every entry whose expr it computes itself, so those slots
     must come back NONE without disturbing the others; the .ML slot puts a
     second file into the per-call cut table. *)
  val batch_in = [pos_A, Position.none, pos_lemma, ml_pos, pos_B, Position.none]
  val batch_out = PIDE_State.commands_at_positions batch_in
  val _ = @{assert} (batch_out = map PIDE_State.command_at_position batch_in)
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
    (entity, Semantic_Store.Declared name, #pos (Name_Space.the_entry space name),
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
    Semantic_Store.strip_trailing_begin (#1 (the (PIDE_State.command_at_position pos)))
  val _ = @{assert} (e_const = "bool")
  val _ = @{assert} (String.isSubstring "Cmd_Test_A" e_thm andalso not (String.isSubstring "lemma" e_thm))
  val _ = @{assert} (e_type = source_of (nth raw 1) andalso String.isSubstring "type_synonym cmd_test_syn" e_type)
  val _ = @{assert} (e_class = source_of (nth raw 3) andalso String.isSubstring "class cmd_test_cls" e_class)
  val _ = @{assert} (e_loc = source_of (nth raw 4) andalso String.isSubstring "locale Cmd_Test_Loc" e_loc
                     andalso String.isSubstring "cmd_x_pos" e_loc)
  val _ = @{assert} (e_coll = source_of (nth raw 5) andalso String.isSubstring "named_theorems cmd_test_coll" e_coll)
  val _ = @{assert} (e_meth = source_of (nth raw 6) andalso String.isSubstring "method_setup cmd_test_meth" e_meth)
  val _ = writeln ("Test 14 - build_entries: every source-carrying kind = its command source, computed kinds untouched: OK")

in
  writeln "\n=== All PIDE_State.command_at_position tests passed ==="
end
\<close>

end
