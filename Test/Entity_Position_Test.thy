theory Entity_Position_Test
  imports Semantic_Embedding.Semantic_Embedding
begin

section \<open>Test targets\<close>

definition Pos_Test_A :: bool where \<open>Pos_Test_A = True\<close>

definition Pos_Test_B :: bool where \<open>Pos_Test_B = False\<close>

lemma Pos_Test_Lemma: \<open>Pos_Test_A \<or> \<not> Pos_Test_A\<close>
  by (simp add: Pos_Test_A_def)

text \<open>Two lemmas with ONE proposition: their universal key is content-addressed and
  therefore identical, so the enumeration dedups them and the survivor's position is
  the one that gets stored (ENTITY_POSITION_PLAN.md §8.6).

  The names are chosen so that ALPHABETICAL order is the REVERSE of source order.
  \<open>Facts.dest_static\<close> ends in \<open>sort_by #1\<close>, so when the source-order tie-break is
  degraded the dedup keeps the alphabetically-first entry -- \<open>..._A_Later\<close>.  With
  names whose alphabetical order agreed with source order the assertion below would
  pass either way and would test nothing.\<close>

lemma Pos_Test_Dup_Z_Earlier: \<open>Pos_Test_B \<or> \<not> Pos_Test_B\<close>
  by (simp add: Pos_Test_B_def)

lemma Pos_Test_Dup_A_Later: \<open>Pos_Test_B \<or> \<not> Pos_Test_B\<close>
  by (simp add: Pos_Test_B_def)

section \<open>Raw position plumbing\<close>

ML \<open>File.standard_path (Path.explode "~~")\<close>

ML \<open>Run_Python.run "return str(1 + 2)"\<close>

ML \<open>
let
  val ctxt = \<^context>
  val thy = Proof_Context.theory_of ctxt

  (* ---- helpers ---- *)
  fun pos_info pos =
    (the_default "" (Position.file_of pos),
     the_default 0 (Position.line_of pos),
     the_default 0 (Position.offset_of pos))

  val const_space = Proof_Context.consts_of ctxt |> Consts.space_of
  val fact_space = Proof_Context.facts_of ctxt |> Facts.space_of

  (* ==== Part A: Compiled-session entities (from HOL heap) ==== *)

  (* ---- Test 1: compiled constant has file + line + offset ---- *)
  val true_pos = #pos (Name_Space.the_entry const_space @{const_name True})
  val (true_file, true_line, true_off) = pos_info true_pos
  val _ = writeln ("Test 1 - HOL.True position:")
  val _ = writeln ("  file: " ^ true_file)
  val _ = writeln ("  line: " ^ string_of_int true_line)
  val _ = writeln ("  offset: " ^ string_of_int true_off)
  val _ = @{assert} (true_file <> "")
  val _ = @{assert} (true_line > 0)
  val _ = @{assert} (true_off > 0)
  val _ = @{assert} (String.isSuffix ".thy" true_file)
  val _ = writeln "Test 1: OK"

  (* ---- Test 2: compiled theorem has file + line + offset ---- *)
  val refl_pos = #pos (Name_Space.the_entry fact_space "HOL.refl")
  val (refl_file, refl_line, refl_off) = pos_info refl_pos
  val _ = writeln ("Test 2 - HOL.refl position:")
  val _ = writeln ("  file: " ^ refl_file)
  val _ = writeln ("  line: " ^ string_of_int refl_line)
  val _ = writeln ("  offset: " ^ string_of_int refl_off)
  val _ = @{assert} (refl_file <> "")
  val _ = @{assert} (refl_line > 0)
  val _ = @{assert} (refl_off > 0)
  val _ = writeln "Test 2: OK"

  (* ---- Test 3: two different constants have different offsets ---- *)
  val conj_pos = #pos (Name_Space.the_entry const_space @{const_name conj})
  val disj_pos = #pos (Name_Space.the_entry const_space @{const_name disj})
  val (_, _, conj_off) = pos_info conj_pos
  val (_, _, disj_off) = pos_info disj_pos
  val _ = @{assert} (conj_off <> disj_off)
  val _ = writeln "Test 3 - conj and disj have different offsets: OK"

  (* ==== Part B: Live PIDE entities ==== *)

  (* ---- Test 4: live constant position via absolutize ---- *)
  val test_pos = #pos (Name_Space.the_entry const_space @{const_name Pos_Test_A})
  val [abs_pos] = PIDE_State.absolutize_id_based_pos {write_to_temp_file = false} [test_pos]
  val (abs_file, abs_line, abs_off) = pos_info abs_pos
  val _ = writeln ("Test 4 - Pos_Test_A (absolutized):")
  val _ = writeln ("  file: " ^ abs_file)
  val _ = writeln ("  line: " ^ string_of_int abs_line)
  val _ = writeln ("  offset: " ^ string_of_int abs_off)
  val _ = @{assert} (abs_file <> "")
  val _ = @{assert} (abs_off > 0)
  val _ = @{assert} (String.isSuffix "Entity_Position_Test.thy" abs_file)
  val _ = writeln "Test 4: OK"

  (* ---- Test 5: live lemma position via absolutize ---- *)
  val lemma_pos = #pos (Name_Space.the_entry fact_space
                          "Entity_Position_Test.Pos_Test_Lemma")
  val [abs_lemma] = PIDE_State.absolutize_id_based_pos {write_to_temp_file = false} [lemma_pos]
  val (lf, ll, lo) = pos_info abs_lemma
  val _ = @{assert} (lf <> "")
  val _ = @{assert} (lo > 0)
  val _ = @{assert} (String.isSuffix "Entity_Position_Test.thy" lf)
  val _ = writeln "Test 5 - Pos_Test_Lemma absolutized position: OK"

  (* ---- Test 6: absolutized position → command_at_position works ---- *)
  val cmd_A = PIDE_State.command_at_position abs_pos
  val _ = @{assert} (is_some cmd_A)
  val (src_A, _, _) = the cmd_A
  val _ = @{assert} (String.isSubstring "definition" src_A)
  val _ = @{assert} (String.isSubstring "Pos_Test_A" src_A)
  val _ = writeln ("Test 6 - command_at_position for Pos_Test_A: OK")
  val _ = writeln ("  source: " ^ src_A)

  (* ---- Test 7: Pos_Test_B is at a different position than Pos_Test_A ---- *)
  val test_B_pos = #pos (Name_Space.the_entry const_space @{const_name Pos_Test_B})
  val [abs_B] = PIDE_State.absolutize_id_based_pos {write_to_temp_file = false} [test_B_pos]
  val (_, _, abs_B_off) = pos_info abs_B
  val _ = @{assert} (abs_B_off > abs_off)
  val cmd_B = PIDE_State.command_at_position abs_B
  val _ = @{assert} (is_some cmd_B)
  val (src_B, _, _) = the cmd_B
  val _ = @{assert} (String.isSubstring "Pos_Test_B" src_B)
  val _ = writeln "Test 7 - Pos_Test_B at different position: OK"

  (* ---- Test 8: lemma command source ---- *)
  val cmd_lemma = PIDE_State.command_at_position abs_lemma
  val _ = @{assert} (is_some cmd_lemma)
  val (src_lemma, _, _) = the cmd_lemma
  val _ = @{assert} (String.isSubstring "lemma" src_lemma)
  val _ = @{assert} (String.isSubstring "Pos_Test_Lemma" src_lemma)
  val _ = writeln ("Test 8 - lemma command source: OK")
  val _ = writeln ("  source: " ^ src_lemma)

in
  writeln "\n=== All raw position tests passed ==="
end
\<close>

section \<open>Entity_Position (ENTITY_POSITION_PLAN.md §5, tests T1--T6)\<close>

ML \<open>
(* Independent verification of a byte column: slice the raw bytes of the line
   off disk and look at what actually starts there.  Only used on LF files. *)
fun line_bytes path n = nth (split_lines (File.read path)) (n - 1)
fun at_column path (line, col) = String.extract (line_bytes path line, col - 1, NONE)

(* A synthetic file position, for cases no live entity can produce. *)
fun mk_pos file line offset = Position.make0 line offset 0 "" file ""

fun one_position pos =
  (case Entity_Position.of_positions [pos] of
    ([r], report) => (r, report)
  | _ => error "of_positions is not parallel to its argument")

fun clean_report {no_file, unreadable, line_mismatch} =
  no_file = 0 andalso unreadable = 0 andalso line_mismatch = 0

fun string_of_report {no_file, unreadable, line_mismatch} =
  "no_file=" ^ string_of_int no_file ^
  " unreadable=" ^ string_of_int unreadable ^
  " line_mismatch=" ^ string_of_int line_mismatch
\<close>

subsection \<open>T1, T1': a heap-resident entity, and the same file spelled absolutely\<close>

ML \<open>
let
  val fact_space = Proof_Context.facts_of \<^context> |> Facts.space_of
  val hol_thy = Path.explode "~~/src/HOL/HOL.thy"

  (* ---- T1 ---- *)
  val refl_pos = #pos (Name_Space.the_entry fact_space "HOL.refl")
  val (r1, rep1) = one_position refl_pos
  val _ = writeln ("T1 - HOL.refl -> " ^ @{make_string} r1 ^ " (" ^ string_of_report rep1 ^ ")")
  (* HOL.thy:220 is `  refl: "t = (t::'a)" and`, so `refl` starts at byte 3. *)
  val _ = @{assert} (r1 = SOME ("~~/src/HOL/HOL.thy", 220, 3))
  val _ = @{assert} (clean_report rep1)
  (* and the same column, verified against the bytes on disk rather than a constant *)
  val _ = @{assert} (String.isPrefix "refl:" (at_column hol_thy (220, 3)))
  val _ = writeln "T1: OK"

  (* ---- T1': the absolute spelling of the very same file folds identically ---- *)
  val abs_hol = File.standard_path hol_thy
  val _ = @{assert} (String.isPrefix "/" abs_hol)
  val (r1', rep1') = one_position (mk_pos abs_hol 220 (the (Position.offset_of refl_pos)))
  val _ = @{assert} (r1' = r1)
  val _ = @{assert} (clean_report rep1')
  val _ = writeln "T1': OK - absolute and symbolic spellings agree byte for byte"
in () end
\<close>

subsection \<open>T2: an entity of the theory being processed (the live path)\<close>

ML \<open>
let
  val const_space = Proof_Context.consts_of \<^context> |> Consts.space_of
  val a_pos = #pos (Name_Space.the_entry const_space @{const_name Pos_Test_A})
  val (r2, rep2) = one_position a_pos
  val _ = writeln ("T2 - Pos_Test_A -> " ^ @{make_string} r2 ^ " (" ^ string_of_report rep2 ^ ")")
  val (file, line, col) = the r2
  val _ = @{assert} (clean_report rep2)
  val _ = @{assert} (String.isSuffix "Test/Entity_Position_Test.thy" file)
  (* L1': this tree sits under $HOME, which File.symbolic_path would happily fold
     to "~/..." -- a string that looks portable and is not.  It must stay absolute. *)
  val _ = @{assert} (String.isPrefix "/" file)
  val _ = @{assert} (String.isPrefix "Pos_Test_A" (at_column (Path.explode file) (line, col)))
  val _ = writeln "T2: OK"
in () end
\<close>

subsection \<open>T3, T4: byte columns on non-ASCII and on CRLF sources\<close>

ML \<open>
let
  (* Three lines, built from explicit byte escapes so the expected numbers can be
     read off this text directly:

       line 1  "L1 x"            4 ASCII symbols
       line 2  "<forall> N"      a literal U+2200 (3 bytes, ONE symbol), space, N
       line 3  "\<forall> M"     the named symbol (9 bytes, ONE symbol), space, M

     Symbol offsets: 1..5 on line 1, 6..9 on line 2, 10..13 on line 3.
     Symbol 8 is the "N": 3 bytes of U+2200 + 1 space => byte column 5.
     Symbol 12 is the "M": 9 bytes of \<forall> + 1 space => byte column 11.
     The symbol columns would be 3 in both cases -- that is the whole point. *)
  val body_lf =
    "L1 x\n" ^ "\226\136\128 N\n" ^ "\092<forall> M\n"
  val body_crlf =
    "L1 x\013\n" ^ "\226\136\128 N\013\n" ^ "\092<forall> M\013\n"

  fun write_tmp name text =
    let val p = File.tmp_path (Path.basic name)
    in File.write p text; File.standard_path p end

  fun check what file =
    let
      val (rs, rep) = Entity_Position.of_positions
        [mk_pos file 1 4, mk_pos file 2 8, mk_pos file 3 12]
      val _ = writeln (what ^ " -> " ^ @{make_string} rs ^ " (" ^ string_of_report rep ^ ")")
      val _ = @{assert} (clean_report rep)
      val _ = @{assert} (rs = [SOME (file, 1, 4), SOME (file, 2, 5), SOME (file, 3, 11)])
    in () end

  (* ---- T3 ---- *)
  val _ = check "T3 (LF, non-ASCII)" (write_tmp "entity_position_lf.thy" body_lf)
  val _ = writeln "T3: OK"

  (* ---- T4: CRLF changes neither the line numbers nor the byte columns ---- *)
  val _ = check "T4 (CRLF)" (write_tmp "entity_position_crlf.thy" body_crlf)
  val _ = writeln "T4: OK"
in () end
\<close>

subsection \<open>T5: the line assertion\<close>

ML \<open>
let
  (* ---- the assertion holds for every entity declared in two real files ---- *)
  val fact_space = Proof_Context.facts_of \<^context> |> Facts.space_of
  val wanted = ["~~/src/HOL/HOL.thy", "~~/src/HOL/List.thy"]
  val positions =
    Name_Space.get_names fact_space
    |> map (fn n => #pos (Name_Space.the_entry fact_space n))
    |> filter (fn pos => member (op =) wanted (the_default "" (Position.file_of pos)))
  val (rs, rep) = Entity_Position.of_positions positions
  val _ = writeln ("T5 - " ^ string_of_int (length positions) ^ " entities in HOL.thy/List.thy: " ^
                   string_of_report rep)
  val _ = @{assert} (length positions > 100)
  val _ = @{assert} (clean_report rep)
  val _ = @{assert} (forall is_some rs)

  (* ---- and it fires when the claimed line does not match the offset ---- *)
  val file = File.standard_path (File.tmp_path (Path.basic "entity_position_lf.thy"))
  (* symbol offset 8 sits on line 2; claim line 3 instead *)
  val (r_bad, rep_bad) = one_position (mk_pos file 3 8)
  val _ = @{assert} (r_bad = NONE)
  val _ = @{assert} (#line_mismatch rep_bad = 1)
  (* an offset past the end of the file counts the same way *)
  val (r_eof, rep_eof) = one_position (mk_pos file 1 9999)
  val _ = @{assert} (r_eof = NONE)
  val _ = @{assert} (#line_mismatch rep_eof = 1)
  val _ = writeln "T5: OK"
in () end
\<close>

subsection \<open>T6: files that cannot be read, and entities with no position at all\<close>

ML \<open>
let
  (* Pure's bootstrap leaves bare, non-rooted names like these behind, some with a
     positive offset.  They must degrade quietly -- and must NOT be resolved
     against the process working directory. *)
  val (rs6, rep6) = Entity_Position.of_positions
    [mk_pos "drule.ML" 1 1,
     mk_pos "Isar/method.ML" 3 42,
     mk_pos "/nonexistent/definitely/missing.thy" 1 1]
  val _ = writeln ("T6 (unreadable) -> " ^ string_of_report rep6)
  val _ = @{assert} (rs6 = [NONE, NONE, NONE])
  val _ = @{assert} (#unreadable rep6 = 3 andalso #line_mismatch rep6 = 0)

  (* §10.1: dynamic collection members carry the literal position ("", 0, 0). *)
  val (rs6', rep6') = Entity_Position.of_positions [Position.none, mk_pos "" 0 0]
  val _ = writeln ("T6 (no position) -> " ^ string_of_report rep6')
  val _ = @{assert} (rs6' = [NONE, NONE])
  val _ = @{assert} (#no_file rep6' = 2)
  val _ = writeln "T6: OK"
in writeln "T6: OK" end
\<close>

subsection \<open>The collection path carries the position into the wire entry\<close>

ML \<open>
let
  val ctxt = \<^context>
  val ctx = Context.Proof ctxt
  val const_space = Proof_Context.consts_of ctxt |> Consts.space_of
  val name = "Entity_Position_Test.Pos_Test_A"
  val entity = Universal_Key.Constant name
  val pos = #pos (Name_Space.the_entry const_space @{const_name Pos_Test_A})
  val uk = Universal_Key.key_of NONE ctx entity
  (* build_entries is the ONLY producer of wire entries, shared by the live path
     and the dry run.  Field 4 is the entity position (plan §6). *)
  val (entries, rep) = Semantic_Store.build_entries ctx [(entity, name, pos, uk, NONE)]
  val [(_, entry_name, _, entry_pos, entry_uk, _, _, _)] = entries
  val ([direct], _) = Entity_Position.of_positions [pos]
  val _ = writeln ("build_entries -> " ^ @{make_string} entry_pos)
  val _ = @{assert} (entry_name = name andalso entry_uk = uk)
  val _ = @{assert} (entry_pos = direct andalso is_some entry_pos)
  val _ = @{assert} (clean_report rep)
in writeln "build_entries carries the entity position: OK" end
\<close>

subsection \<open>T9: the deduplicated occurrence's position is the source-earliest one\<close>

ML \<open>
let
  (* Without this the Python handlers are not registered and
     check_theorem_name_in_file fails -- which degrades the tie-break, exactly the
     condition asserted against below. *)
  val _ = Remote_Procedure_Calling.load ["Isabelle_Semantic_Embedding"]
  val ctx = Context.Theory \<^theory>
  val {entries, tie_break_degraded, position_report, ...} =
    Semantic_Store.enumerate_entries ctx

  (* The flag is what the backfill refuses on.  It must be false here: the theorem
     dedup below is only meaningful when check_theorem_name_in_file really ran. *)
  val _ = @{assert} (not tie_break_degraded)
  val _ = @{assert} (#line_mismatch position_report = 0)

  fun line_of_lemma nm =
    let
      val fact_space = Proof_Context.facts_of \<^context> |> Facts.space_of
      val pos = #pos (Name_Space.the_entry fact_space ("Entity_Position_Test." ^ nm))
    in the (Position.line_of pos) end
  val first_line = line_of_lemma "Pos_Test_Dup_Z_Earlier"
  val second_line = line_of_lemma "Pos_Test_Dup_A_Later"
  val _ = @{assert} (first_line < second_line)

  (* Exactly ONE entry survives for the shared proposition, and it sits at the
     EARLIER lemma's line.  Since the names make alphabetical order the reverse of
     source order, this discriminates: a degraded tie-break would keep
     Pos_Test_Dup_A_Later instead. *)
  val dup_entries = entries |> map_filter (fn (_, nm, _, epos, _, _, _, _, _, _) =>
        if String.isPrefix "Entity_Position_Test.Pos_Test_Dup_" nm
        then SOME (nm, epos) else NONE)
  val _ = writeln ("T9 - surviving duplicate entries: " ^ @{make_string} dup_entries)
  val _ = @{assert} (length dup_entries = 1)
  val (_, SOME (_, line, _)) = hd dup_entries
  val _ = @{assert} (line = first_line)
in writeln "T9: OK" end
\<close>

ML \<open>writeln "\n=== All Entity_Position tests passed ==="\<close>

end
