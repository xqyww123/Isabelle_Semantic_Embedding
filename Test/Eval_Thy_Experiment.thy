theory Eval_Thy_Experiment
  imports "../Semantic_Embedding"
begin

text \<open>
  Test the re-evaluation cache in PIDE_State.context_at_position
  for finished/heap theories.
\<close>

section \<open>Test 1: context_at_position for heap theory (Lattices.thy)\<close>

ML \<open>
let
  val thy = \<^theory>\<open>Lattices\<close>
  val thy_path = Resources.master_directory thy
  val file = Path.implode (Path.append thy_path (Path.basic "Lattices.thy"))
  val _ = writeln "=== Test 1: context_at_position for heap Lattices.thy ==="
  val _ = writeln ("  file = " ^ file)

  val timer = Timer.startRealTimer ()

  (* First call triggers re-evaluation + cache build *)
  val ctx1 = PIDE_State.context_at_position {re_eval_cache = true} file 100
  val elapsed1 = Timer.checkRealTimer timer
  val _ = writeln ("  first call (offset=100): " ^ Time.toString elapsed1 ^ "s -> " ^
    (case ctx1 of NONE => "NONE" | SOME c =>
      Context.theory_long_name (Context.theory_of c)))

  (* Second call should be instant (cached) *)
  val timer2 = Timer.startRealTimer ()
  val ctx2 = PIDE_State.context_at_position {re_eval_cache = true} file 5000
  val elapsed2 = Timer.checkRealTimer timer2
  val _ = writeln ("  second call (offset=5000): " ^ Time.toString elapsed2 ^ "s -> " ^
    (case ctx2 of NONE => "NONE" | SOME c =>
      Context.theory_long_name (Context.theory_of c)))
in () end
\<close>

section \<open>Test 2: Locale context in heap theory via re-eval cache\<close>

ML \<open>
let
  (* Groups.thy defines locale "group" with local operations *)
  val thy = \<^theory>\<open>Groups\<close>
  val thy_path = Resources.master_directory thy
  val file = Path.implode (Path.append thy_path (Path.basic "Groups.thy"))
  val _ = writeln "=== Test 2: Groups.thy locale context ==="

  val text = File.read (Path.explode file)

  (* Find the byte position of "locale semigroup" *)
  fun find_substr s text =
    let val n = size s
        fun search i = if i + n > size text then NONE
          else if String.substring (text, i, n) = s then SOME i
          else search (i + 1)
    in search 0 end

  val _ = case find_substr "locale semigroup" text of
      NONE => writeln "  'locale semigroup' not found in text"
    | SOME byte_off => writeln ("  'locale semigroup' at byte ~" ^ string_of_int byte_off)

  (* Try a range of offsets to find where locale context is active *)
  fun try_name ctxt name =
    let val space = Proof_Context.const_space ctxt
        val fq = Name_Space.intern space name
    in if String.isPrefix "??" fq then NONE else SOME fq end

  fun probe off =
    case PIDE_State.context_at_position {re_eval_cache = true} file off of
      NONE => writeln ("  offset=" ^ string_of_int off ^ " -> NONE")
    | SOME (Context.Theory _) =>
        writeln ("  offset=" ^ string_of_int off ^ " -> Theory")
    | SOME (Context.Proof ctxt) =>
        let val mult = try_name ctxt "local.mult"
            val add = try_name ctxt "local.plus"
        in writeln ("  offset=" ^ string_of_int off ^ " -> Proof" ^
             (case mult of NONE => "" | SOME fq => " mult=" ^ fq) ^
             (case add of NONE => "" | SOME fq => " plus=" ^ fq))
        end

  val _ = List.app probe [100, 500, 1000, 1500, 2000, 2500, 3000,
    3500, 4000, 4500, 5000, 6000, 7000, 8000, 9000, 10000,
    12000, 14000, 16000, 18000, 20000]
in () end
\<close>

section \<open>Test 3: Current live theory still works via PIDE\<close>

locale test_locale =
  fixes z :: nat
begin

definition test_g :: "nat \<Rightarrow> nat" where
  "test_g x = z + x"

ML \<open>
let
  val file = "/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/Test/Eval_Thy_Experiment.thy"
  val _ = writeln "=== Test 3: Live theory via PIDE ==="

  (* This should use live PIDE, not re-eval cache *)
  fun probe off =
    case PIDE_State.context_at_position {re_eval_cache = true} file off of
      NONE => writeln ("  offset=" ^ string_of_int off ^ " -> NONE")
    | SOME (Context.Theory _) =>
        writeln ("  offset=" ^ string_of_int off ^ " -> Theory")
    | SOME (Context.Proof ctxt) =>
        let val space = Proof_Context.const_space ctxt
            val fq = Name_Space.intern space "local.test_g"
        in writeln ("  offset=" ^ string_of_int off ^ " -> Proof" ^
             (if String.isPrefix "??" fq then "" else " test_g=" ^ fq))
        end

  val _ = List.app probe [100, 500, 1000, 1500, 2000, 2500, 3000, 3500]
in () end
\<close>

end

end
