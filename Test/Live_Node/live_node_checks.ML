(*  The checks of the Headless live-node test (Isabelle2026 port, node-match test H and the
    design review's T5), run inside a theory that test_live_node_headless.py generates and
    loads through an Isabelle server session, so that every fixture theory is a live PIDE
    node.  For each target constant: its declaration position carries only a command id;
    every spelling of its file must find that node by the node's own name (H1), give the
    live context there (H2), and answer the raw Scala position queries as the node name does
    (H3); declaring_commands gives its definition (T5).  Odd paths answer nothing and raise
    nothing (H5).  A failure raises an error, which the driver reports.
*)

structure Live_Node_Checks =
struct

fun check msg b = if b then () else error ("Live_Node_Checks: " ^ msg)

fun scala f arg = f (YXML.string_of_body arg) |> YXML.parse_body
fun file_offset (file, offset) = XML.Encode.pair XML.Encode.string XML.Encode.int (file, offset)
fun raw_command f q =
  scala \<^scala>\<open>pide_state.command_at_position\<close> (file_offset (f, q))
  |> XML.Decode.pair XML.Decode.string (XML.Decode.pair XML.Decode.int XML.Decode.int)
fun raw_entity f q =
  scala \<^scala>\<open>pide_state.entity_at_position\<close> (file_offset (f, q))
  |> XML.Decode.pair XML.Decode.string XML.Decode.string
fun raw_hover f q =
  \<^scala>\<open>pide_state.hover_message\<close> (YXML.string_of_body (file_offset (f, q)))
fun raw_goto f q =
  scala \<^scala>\<open>pide_state.goto_definition\<close> (file_offset (f, q))
  |> XML.Decode.pair XML.Decode.string
      (XML.Decode.pair XML.Decode.int (XML.Decode.pair XML.Decode.int XML.Decode.int))

fun target ctxt (const, spellings) =
  let
    val raw = Name_Space.the_entry_pos (Consts.space_of (Proof_Context.consts_of ctxt)) const
    val id = (case Position.parse_id raw of SOME i => i | NONE => error ("no id: " ^ const))
    val abs = singleton (PIDE_State.absolutize_id_based_pos {write_to_temp_file = false}) raw
    val node = the_default "" (Position.file_of abs)
    val q = the_default 0 (Position.offset_of abs)
    val _ = writeln ("Live_Node_Checks: " ^ const ^ " node " ^ quote node ^ " offset " ^
      string_of_int q ^ " id " ^ string_of_int id)
    val _ = check ("a resolved position for " ^ const) (node <> "" andalso q > 0)
    fun spelling s =
      (check ("H1 " ^ quote s) (PIDE_State.command_id_at_position s q = SOME (node, id));
       check ("H2 " ^ quote s)
         (case PIDE_State.context_at_position {re_eval_cache = false}
                 (Context.Theory \<^theory>\<open>Pure\<close>) s q of
           SOME c => Sign.declared_const (Context.theory_of c) const
         | NONE => false);
       check ("H3 command " ^ quote s)
         (#1 (raw_command s q) <> "" andalso raw_command s q = raw_command node q);
       check ("H3 entity " ^ quote s)
         (raw_entity s q <> ("", "") andalso raw_entity s q = raw_entity node q);
       check ("H3 hover " ^ quote s) (raw_hover s q = raw_hover node q))
    val _ = List.app spelling spellings
    val _ =
      (case Semantic_Store.declaring_commands (Context.Proof ctxt) [(Universal_Key.ConstantK, const)] of
        [SOME (src, _, _)] =>
          check ("T5 declaring command of " ^ const ^ ": " ^ src)
            (String.isPrefix "definition" src andalso String.isSubstring (Long_Name.base_name const) src)
      | r => check ("T5 shape for " ^ const ^ ": " ^ \<^make_string> r) false)
  in () end

fun nothing bad =
  (check ("H5 command_id " ^ quote bad) (PIDE_State.command_id_at_position bad 1 = NONE);
   check ("H5 command " ^ quote bad) (raw_command bad 1 = ("", (0, 0)));
   check ("H5 entity " ^ quote bad) (raw_entity bad 1 = ("", ""));
   check ("H5 hover " ^ quote bad) (raw_hover bad 1 = "");
   check ("H5 goto " ^ quote bad) (raw_goto bad 1 = ("", (0, (0, 0)))))

fun run ctxt targets bads =
  (List.app (target ctxt) targets; List.app nothing bads;
   writeln "Live_Node_Checks: all checks passed")

end
