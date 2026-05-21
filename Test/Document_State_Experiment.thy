theory Document_State_Experiment
  imports "../Semantic_Embedding"
begin

text \<open>
  Experiment: Test PIDE_State.context_at_position {re_eval_cache = true} and Document.command_exec.

  Key questions:
  1. Can we get context at a position in the CURRENT theory (live PIDE)?
  2. Can we get context at a position in a FINISHED theory (heap image)?
  3. Does locale context resolve local.f names?
  4. Does Locale.init work as fallback for heap theories?
\<close>

section \<open>Test 1: command_id_at_position for current theory\<close>

definition test_const :: nat where "test_const = 42"

ML \<open>
let
  val thy_file = "/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/Test/Document_State_Experiment.thy"
  val offset = 10 (* somewhere in the theory header *)
  val cmd_id = PIDE_State.command_id_at_position thy_file offset
  val _ = writeln "=== Test 1: command_id_at_position (current theory) ==="
  val _ = writeln ("  offset=10 -> cmd_id=" ^
    (case cmd_id of NONE => "NONE" | SOME id => string_of_int id))
in () end
\<close>

section \<open>Test 2: toplevel_state_at_position for current theory\<close>

ML \<open>
let
  val thy_file = "/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/Test/Document_State_Experiment.thy"
  val _ = writeln "=== Test 2: toplevel_state_at_position (current theory) ==="

  (* Try offset 10 — should be in the theory header region *)
  val st = PIDE_State.toplevel_state_at_position thy_file 10
  val _ = writeln ("  offset=10 -> " ^
    (case st of
      NONE => "NONE"
    | SOME s => "OK: is_theory=" ^ Bool.toString (Toplevel.is_theory s)
        ^ " thy=" ^ Context.theory_long_name (Toplevel.theory_of s)))
in () end
\<close>

section \<open>Test 3: context_at_position for current theory\<close>

ML \<open>
let
  val thy_file = "/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/Test/Document_State_Experiment.thy"
  val _ = writeln "=== Test 3: context_at_position (current theory) ==="
  val ctx = PIDE_State.context_at_position {re_eval_cache = true} thy_file 10
  val _ = writeln ("  offset=10 -> " ^
    (case ctx of
      NONE => "NONE"
    | SOME c => "OK: " ^ Context.theory_long_name (Context.theory_of c)))
in () end
\<close>

section \<open>Test 4: Finished theory (heap image)\<close>

ML \<open>
let
  val _ = writeln "=== Test 4: context_at_position for heap theory ==="
  val list_file = Path.implode (Path.explode "~~/src/HOL/List.thy")
  val _ = writeln ("  List.thy path = " ^ list_file)

  val cmd_id = PIDE_State.command_id_at_position list_file 100
  val _ = writeln ("  command_id_at_position(List.thy, 100) = " ^
    (case cmd_id of NONE => "NONE" | SOME id => string_of_int id))

  val ctx = PIDE_State.context_at_position {re_eval_cache = true} list_file 100
  val _ = writeln ("  context_at_position(List.thy, 100) = " ^
    (case ctx of NONE => "NONE" | SOME c => "OK: " ^ Context.theory_long_name (Context.theory_of c)))
in () end
\<close>

section \<open>Test 5: Locale context via context_at_position\<close>

locale my_test_locale =
  fixes y :: nat
begin

definition loc_f :: "nat \<Rightarrow> nat" where
  "loc_f x = y + x"

ML \<open>
let
  val _ = writeln "=== Test 5a: Locale context via context ==="
  val ctxt = \<^context>
  val const_space = Proof_Context.const_space ctxt
  val fq1 = Name_Space.intern const_space "local.loc_f"
  val _ = writeln ("  intern(local.loc_f) = " ^ fq1)
  val fq2 = Name_Space.intern const_space "loc_f"
  val _ = writeln ("  intern(loc_f) = " ^ fq2)
in () end
\<close>

end

text \<open>Now test: can context_at_position recover the locale context
  from a position INSIDE the locale block?\<close>

ML \<open>
let
  val thy_file = "/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/Test/Document_State_Experiment.thy"
  val _ = writeln "=== Test 5b: context_at_position inside locale block ==="

  (* We need an offset that falls inside the locale block.
     The loc_f definition is around line 42-43 of this file.
     At ~40 chars/line, that's roughly offset 1700.
     We'll try a range of offsets. *)
  fun try_offset off =
    let val ctx = PIDE_State.context_at_position {re_eval_cache = true} thy_file off
    in case ctx of
        NONE => writeln ("  offset=" ^ string_of_int off ^ " -> NONE")
      | SOME (Context.Theory _) =>
          writeln ("  offset=" ^ string_of_int off ^ " -> Theory context")
      | SOME (Context.Proof ctxt) =>
          let val const_space = Proof_Context.const_space ctxt
              val fq = Name_Space.intern const_space "local.loc_f"
          in writeln ("  offset=" ^ string_of_int off ^
               " -> Proof context, intern(local.loc_f) = " ^ fq)
          end
    end

  (* locale block is ~byte 2939-3439; symbol offsets are smaller.
     Try a wide range to cover before/inside/after the locale. *)
  val _ = List.app try_offset
    [10, 500, 1000, 1500, 2000, 2200, 2400, 2600, 2800,
     3000, 3200, 3400, 3600, 3800, 4000, 4500, 5000]
in () end
\<close>

section \<open>Test 6: Locale.init fallback (for heap theories)\<close>

ML \<open>
let
  val thy = \<^theory>
  val _ = writeln "=== Test 6: Locale.init fallback ==="

  (* Our own locale *)
  val ctxt1 = try (Locale.init "Document_State_Experiment.my_test_locale") thy
  val _ = case ctxt1 of
      NONE => writeln "  own locale: FAILED"
    | SOME c =>
        let val fq = Name_Space.intern (Proof_Context.const_space c) "local.loc_f"
        in writeln ("  own locale: intern(local.loc_f) = " ^ fq) end

  (* Heap theory locale *)
  val ctxt2 = try (Locale.init "Lattices.semilattice_inf") thy
  val _ = case ctxt2 of
      NONE => writeln "  heap locale (semilattice_inf): FAILED"
    | SOME c =>
        let val const_space = Proof_Context.const_space c
            val fq_inf = Name_Space.intern const_space "inf"
            val fq_le = Name_Space.intern const_space "less_eq"
        in writeln ("  heap locale: intern(inf) = " ^ fq_inf
             ^ ", intern(less_eq) = " ^ fq_le)
        end
in () end
\<close>

end
