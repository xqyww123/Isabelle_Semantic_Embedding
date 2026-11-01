(*
  INFRA_FILTER_CLASS_VARIANT_PLAN.md §4.9: the retrieval closure judges the
  theorem-like callbacks' LIVE pass (the facts the closure's build-time snapshot lacks
  and, in a rule callback, the whole classical / Induct net) and every name of the
  name-space callbacks with the infra filter of the query context, built once per
  context object; the build-time context keeps the filter the closure was built
  with.  Each query below is a request of its own, through the Python client, on a
  context registered by index.  The pins read a
  process-wide closure and build counter, so the commands must run one at a time:
  the checks in proofs are ML_prf (PIDE forks a diagnostic ML_val, not ML_prf), and
  Test/ROOT gives this theory a clause of its own with parallel_proofs = 0.
*)
theory Infra_Live_Pass_Test
  imports Link_Finder_Test_Base
begin

definition lp_c :: "nat \<Rightarrow> bool" where "lp_c n = True"

text \<open>A global classical rule whose name fails the rule-name test: no rule bucket of the
  closure holds it, so the classical net (Source-1) is the introduction-rule callback's
  only route to it.\<close>

lemma lp_g[intro]: "lp_c n \<Longrightarrow> P \<or> lp_c n" by simp

ML \<open>
structure Live_Pass_Test =
struct

open Link_Finder_Test

val contexts = Synchronized.var "Live_Pass_Test.contexts" ([] : Context.generic list)
fun register ctxt =
  Synchronized.change_result contexts (fn cs => (length cs, cs @ [Context.Proof ctxt]))
fun context_at i = nth (Synchronized.value contexts) i
val unpack : Context_Callbacks.context_unpacker = fn src =>
  let val (i, src') = MessagePackBinIO.Unpack.unpackInt src in (context_at i, src') end

(*the closure under test and the index of its build-time context*)
val closure = Synchronized.var "Live_Pass_Test.closure" ([] : Remote_Procedure_Calling.callback' list, ~1)
fun build_time () = #2 (Synchronized.value closure)

(*registers the context and builds the closure from it*)
fun start ctxt =
  let val b = register ctxt
  in Synchronized.change closure (K (Semantic_Store.make_entity_callbacks (context_at b) (K true) unpack, b)) end

(*the sorted (name, is_local) entries of one kind in context i whose names contain pat*)
fun query kind i pat =
  Run_Python.run_with (#1 (Synchronized.value closure)) (cat_lines
    ["from Isabelle_RPC_Host.context import entities_of",
     "from Isabelle_RPC_Host.universal_key import EntityKind",
     "es, _ = await entities_of(connection, [EntityKind." ^ kind ^ "], name_contains=[" ^
       quote pat ^ "], ctxt=" ^ string_of_int i ^ ")",
     "return '\\n'.join(f'{n}\\t{l}' for _, n, l in es)"])
  |> the_default "" |> split_lines |> filter_out (fn l => l = "")
  |> map (fn l => (case space_explode "\t" l of
        [n, b] => (n, b = "True")
      | _ => fail ("Live_Pass_Test: a reply line " ^ quote l)))
  |> sort (prod_ord string_ord bool_ord)

val theorems = query "THEOREM"
val intro_rules = query "INTRODUCTION_RULE"
fun constants i pat = map #1 (query "CONSTANT" i pat)

(*one invocation: the theorems, introduction-rule and constants callbacks*)
fun invoke i = (theorems i "local.lp_"; intro_rules i "local.lp_"; constants i "lp_c"; ())
fun builds f = let val n = Semantic_Store.query_filter_builds () in f (); Semantic_Store.query_filter_builds () - n end

end
\<close>

text \<open>A fact noted after the closure was built, with \<open>[intro]\<close>; its name fails the
  rule-name test, so Source-1 is the introduction-rule callback's only route to it.
  Then two successive contexts, each with a fact of its own.\<close>

notepad
begin
  ML_prf \<open>Live_Pass_Test.start \<^context>\<close>
  have lp_foo[intro]: "P \<Longrightarrow> P \<or> Q" "Q \<Longrightarrow> P \<or> Q" for P Q :: bool by simp_all
  ML_prf \<open>
    local open Live_Pass_Test val i = register \<^context> in
    val _ = check_all "a fact noted after the closure was built"
     [("the theorems callback returns both theorems, local",
         fn () => theorems i "lp_foo" = [("local.lp_foo(1)", true), ("local.lp_foo(2)", true)]),
      ("the introduction-rule callback returns both theorems, local",
         fn () => intro_rules i "lp_foo" = [("local.lp_foo(1)", true), ("local.lp_foo(2)", true)])]
    end\<close>
  have lp_one: "(1::nat) + 1 = 2" by simp
  ML_prf \<open>
    local open Live_Pass_Test in
    val _ = check "the first context returns its fact"
      (theorems (register \<^context>) "lp_one" = [("local.lp_one", true)])
    end\<close>
  have lp_two: "(2::nat) + 2 = 4" by simp
  ML_prf \<open>
    local open Live_Pass_Test in
    val _ = check "the second context returns its fact"
      (theorems (register \<^context>) "lp_two" = [("local.lp_two", true)])
    end\<close>
end

text \<open>A declaration seen only by the query context (V38, V39): \<open>lp_c\<close> declared
  infrastructure after the closure was built, then two fresh facts, one mentioning it.
  The global rule \<open>lp_g\<close>, defined in both fact spaces, mentions it too.\<close>

notepad
begin
  ML_prf \<open>
    local open Live_Pass_Test val _ = start \<^context> val b = build_time () in
    val _ = check_all "the build-time context"
     [("the build-time context lists lp_c",
         fn () => member (op =) (constants b "lp_c") "Infra_Live_Pass_Test.lp_c"),
      ("the build-time context lists the global rule lp_g, not local",
         fn () => intro_rules b "Infra_Live_Pass_Test.lp_g" = [("Infra_Live_Pass_Test.lp_g", false)])]
    end\<close>
  note [[infra_constant lp_c]]
  have lp_m[intro]: "lp_c n \<Longrightarrow> lp_c n \<or> P" for n P by simp
  have lp_n[intro]: "P \<Longrightarrow> P \<or> Q" for P Q :: bool by simp
  ML_prf \<open>
    local open Live_Pass_Test val i = register \<^context> in
    val _ = check_all "a declaration made after the closure was built"
     [("the theorems callback returns only the fact without lp_c",
         fn () => theorems i "local.lp_" = [("local.lp_n", true)]),
      ("the introduction-rule callback returns only the fact without lp_c",
         fn () => intro_rules i "local.lp_" = [("local.lp_n", true)]),
      ("the introduction-rule callback no longer lists the global rule lp_g",
         fn () => null (intro_rules i "Infra_Live_Pass_Test.lp_g")),
      ("the constants callback no longer lists lp_c",
         fn () => not (member (op =) (constants i "lp_c") "Infra_Live_Pass_Test.lp_c")),
      ("the build-time context still lists lp_c",
         fn () => member (op =) (constants (build_time ()) "lp_c") "Infra_Live_Pass_Test.lp_c")]
    end\<close>
end

text \<open>Builds (V30, V31): five invocations on one derived context build once, five more
  none, another context once; five on the build-time context none; a derived context,
  then the build-time context, then the same derived context once.  Every derived
  context holds a fresh \<open>[intro]\<close> fact.\<close>

notepad
begin
  ML_prf \<open>Live_Pass_Test.start \<^context>\<close>
  have lp_d1[intro]: "P \<Longrightarrow> P \<or> Q" for P Q :: bool by simp
  ML_prf \<open>
    local open Live_Pass_Test
      val d = register \<^context>
      val first = builds (fn () => funpow 5 (fn () => invoke d) ())
      val again = builds (fn () => funpow 5 (fn () => invoke d) ())
    in
    val _ = check_all "one derived context"
     [("five invocations build once (" ^ string_of_int first ^ ")", fn () => first = 1),
      ("five more build none (" ^ string_of_int again ^ ")", fn () => again = 0)]
    end\<close>
  have lp_d2[intro]: "Q \<Longrightarrow> P \<or> Q" for P Q :: bool by simp
  ML_prf \<open>
    local open Live_Pass_Test
      val d = register \<^context>
      val other = builds (fn () => invoke d)
      val on_b = builds (fn () => funpow 5 (fn () => invoke (build_time ())) ())
    in
    val _ = check_all "another context, and the build-time context"
     [("another context builds once (" ^ string_of_int other ^ ")", fn () => other = 1),
      ("five invocations on the build-time context build none (" ^
         string_of_int on_b ^ ")", fn () => on_b = 0)]
    end\<close>
  have lp_d3[intro]: "P \<Longrightarrow> Q \<Longrightarrow> P \<and> Q" for P Q :: bool by simp
  ML_prf \<open>
    local open Live_Pass_Test
      val d = register \<^context>
      val n = builds (fn () => (invoke d; invoke (build_time ()); invoke d))
    in
    val _ = check ("a derived context, the build-time context, the same derived context \
      \build once (" ^ string_of_int n ^ ")") (n = 1)
    end\<close>
end

end
