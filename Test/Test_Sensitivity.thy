theory Test_Sensitivity
  imports HOL.Record Isabelle_RPC.Remote_Procedure_Calling
begin

ML_file \<open>/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/Tools/semantic_digest.ML\<close>

text \<open>SENSITIVITY suite.  Determinism and resolution-coverage tests both pass
  trivially on a digest that ignores content; only these assertions catch a
  digest that is stable because it is BLIND.  Each case names content that MUST
  reach the digest or the dependency edges.

  Two rules learned the hard way:
  (a) an assertion must not be satisfiable through an unrelated path -- an
      earlier "Set.member has some dependency beyond its own type" passed purely
      via Set.set in the TYPE and hid a real defect for a full round;
  (b) the SUBJECT must actually discriminate -- Orderings.order has 3 supers in
      every env and passed while the superclass bug was live.\<close>

ML \<open>
val env = Semantic_Digest.make_env \<^theory>;

val failures = Unsynchronized.ref ([] : string list);
fun check name ok =
  (writeln ((if ok then "PASS  " else "FAIL  ") ^ name);
   if ok then () else failures := name :: !failures);

fun deps_of e =
  case Semantic_Digest.semantics_of env e of SOME (_, ds) => ds | NONE => [];
fun mentions e target = exists (fn (_, m) => m = target) (deps_of e);
fun mentions_kind e (tk, target) =
  exists (fn (k, m) => k = tk andalso m = target) (deps_of e);
\<close>

subsection \<open>S1 constant: an abbreviation's right-hand side\<close>

ML \<open>
check "S1a  Set.range depends on Set.image (its rhs)"
  (mentions (Universal_Key.Constant "Set.range") "Set.image");
check "S1b  HOL.not_equal depends on HOL.eq (its rhs)"
  (mentions (Universal_Key.Constant "HOL.not_equal") "HOL.eq");
\<close>

subsection \<open>S2 constant: axioms of an axiomatized constant\<close>

ML \<open>
(* mem_Collect_eq relates member and Collect, so each must reach the other. *)
check "S2a  Set.member depends on Set.Collect (via mem_Collect_eq)"
  (mentions (Universal_Key.Constant "Set.member") "Set.Collect");
check "S2b  Set.Collect depends on Set.member (via Collect_mem_eq)"
  (mentions (Universal_Key.Constant "Set.Collect") "Set.member");
(* HOL.The is DECLARED at HOL.thy:92-94 and axiomatised separately at :229, so
   its spec item carries no terms and never enters the Item_Net index --
   retrieve_global cannot see it; only a get_global scan can. *)
check "S2c  HOL.The reaches its separately-stated axiom"
  (length (Semantic_Digest.own_defining_axioms env "HOL.The") > 0);
(* ...and the axiom source must NOT drag in downstream instances. *)
check "S2d  plus picks up no downstream instance rule"
  (null (Semantic_Digest.own_defining_axioms env "Groups.plus_class.plus"));
check "S2e  less_eq picks up no downstream instance rule"
  (null (Semantic_Digest.own_defining_axioms env "Orderings.ord_class.less_eq"));
\<close>

subsection \<open>S3 locale: assumes, defines, parents, parameters\<close>

locale sens_parent = fixes p :: "nat \<Rightarrow> bool" assumes p0: "p 0"
locale sens_child = sens_parent + assumes p1: "p 1"
locale sens_def = fixes q :: "nat \<Rightarrow> nat" defines qd: "q \<equiv> \<lambda>n. n + 1"

ML \<open>
(* NB: `env` above was built at the top of the file, BEFORE these locales were
   declared, so it cannot see them -- locale-local subjects need a fresh env. *)
let
  val env2 = Semantic_Digest.make_env \<^theory>
  fun deps2 n =
    case Semantic_Digest.semantics_of env2 (Universal_Key.Locale n) of
      SOME (_, ds) => ds | NONE => []
in
  check "S3a  Groups.semigroup depends on something from its assumes"
    (length (deps_of (Universal_Key.Locale "Groups.semigroup")) > 1);
  (* parent edge: abel_semigroup has a predicate parent AND its own assumes --
     the exact shape that lost its parent edge when hyp_spec_of replaced
     axioms_of *)
  check "S3b  Groups.abel_semigroup has a LocaleK edge to its parent"
    (exists (fn (k, _) => k = Universal_Key.LocaleK)
       (deps_of (Universal_Key.Locale "Groups.abel_semigroup")));
  check "S3c  sens_child has a LocaleK edge to sens_parent"
    (exists (fn (k, m) => k = Universal_Key.LocaleK andalso
                          m = "Test_Sensitivity.sens_parent")
       (deps2 "Test_Sensitivity.sens_child"));
  (* defines: Element.Defines is part of hyp_spec and must not be dropped *)
  check "S3d  sens_def reaches its defines body (depends on Groups.plus)"
    (exists (fn (_, m) => m = "Groups.plus_class.plus")
       (deps2 "Test_Sensitivity.sens_def"))
end
\<close>

subsection \<open>S4 type: typedef representing set, also when ctr_sugar answers\<close>

ML \<open>
check "S4a  Int.int depends on Int.intrel (from its defining set)"
  (mentions (Universal_Key.Type "Int.int") "Int.intrel");
(* Nat.nat answers on BOTH channels (ctrs [0,Suc] AND a typedef over ind);
   short-circuiting on ctr_sugar used to discard the representing set. *)
check "S4b  Nat.nat reaches its typedef predicate despite having ctr_sugar"
  (mentions (Universal_Key.Type "Nat.nat") "Nat.Nat");
\<close>

subsection \<open>S5 class: parameters\<close>

ML \<open>
check "S5a  Orderings.ord depends on its parameter less_eq"
  (mentions (Universal_Key.Class "Orderings.ord") "Orderings.ord_class.less_eq");
check "S5b  Orderings.ord depends on its parameter less"
  (mentions (Universal_Key.Class "Orderings.ord") "Orderings.ord_class.less");
\<close>

subsection \<open>S6 theorem: sort constraints yield class edges\<close>

ML \<open>
check "S6  not_less has a ClassK edge for its linorder sort"
  (mentions_kind (Universal_Key.Named_Theorem "Orderings.linorder_class.not_less")
     (Universal_Key.ClassK, "Orderings.linorder"));
(* The same statement handed over as a THEOREM VALUE (the pipeline's own form:
   entries carry thms, not names) must yield the same edges.  Set comparison:
   the name-valued path merges per-thm lists through `unions`, which changes
   the ORDER, and dep lists are unordered sets by contract. *)
check "S6b  the thm-valued form agrees with the name-valued form"
  (eq_set (op =)
     (deps_of (Universal_Key.Theorem @{thm Orderings.linorder_class.not_less}),
      deps_of (Universal_Key.Named_Theorem "Orderings.linorder_class.not_less")));
\<close>

subsection \<open>S7 class: the digest must not depend on the enclosing env\<close>

ML \<open>
(* Rings.idom is widened downstream by Semiring_Normalization's
   `subclass (in idom) ...`, so its transitive super set differs between envs
   (43 under HOL.Rings, 48 under Main).  Orderings.order cannot discriminate. *)
let
  val env_rings = Semantic_Digest.make_env (Thy_Info.get_theory "HOL.Rings")
  fun d e n = Option.map fst (Semantic_Digest.semantics_of e (Universal_Key.Class n))
  fun supers e n = length (Sign.super_classes (Semantic_Digest.theory_of_env e) n)
  fun cmp n =
    (writeln ("      (supers: Rings=" ^ string_of_int (supers env_rings n) ^
              ", Main=" ^ string_of_int (supers env n) ^ ")");
     check ("S7  " ^ n ^ " digest is env-independent") (d env_rings n = d env n))
in map cmp ["Rings.idom", "Rings.comm_ring_1"] end
\<close>

subsection \<open>S9 datatype: constructor declaration order is semantic\<close>

datatype sens_ctrA = SA nat | SB nat
datatype sens_ctrB = TB nat | TA nat

ML \<open>
(* Sorting the constructor list erased declaration order, so `A | B` and
   `B | A` digested identically.  Compare the constructor TYPE sequence, since
   the digest also carries the type name. *)
let
  fun ctr_names n =
    case Ctr_Sugar.ctr_sugar_of_global \<^theory> n of
      SOME {ctrs, ...} => map (fn Const (c, _) => Long_Name.base_name c | _ => "?") ctrs
    | NONE => []
in
  writeln ("      sens_ctrA ctrs: " ^ commas (ctr_names "Test_Sensitivity.sens_ctrA"));
  writeln ("      sens_ctrB ctrs: " ^ commas (ctr_names "Test_Sensitivity.sens_ctrB"));
  check "S9  constructor order is preserved (not sorted away)"
    (ctr_names "Test_Sensitivity.sens_ctrA" = ["SA", "SB"] andalso
     ctr_names "Test_Sensitivity.sens_ctrB" = ["TB", "TA"])
end
\<close>

subsection \<open>S10 rule kinds resolve like their theorem\<close>

ML \<open>
(* Theorem-alike entities carry no digest by design (the key's thm128 is the
   change signal), so what must agree across the rule kinds is the DEPS. *)
let
  fun d e = Option.map snd (Semantic_Digest.semantics_of env e)
in
  check "S10  Named_Introduction_Rule resolves for HOL.conjI"
    (is_some (d (Universal_Key.Named_Introduction_Rule "HOL.conjI")));
  check "S10b Named_Introduction_Rule deps agree with Named_Theorem"
    (d (Universal_Key.Named_Introduction_Rule "HOL.conjI") =
     d (Universal_Key.Named_Theorem "HOL.conjI"));
  check "S10c theorem-alike entities carry no digest"
    (Option.map fst (Semantic_Digest.semantics_of env
       (Universal_Key.Named_Theorem "HOL.conjI")) = SOME NONE)
end
\<close>

subsection \<open>S11 class: super deps are the DECLARED direct supers (§3.2, A5)\<close>

ML \<open>
(* Test-only def-parse extraction: the OFCLASS conjuncts on the RHS of
   Axclass.get_info's `def` are the supers AS DECLARED, frozen by
   Axclass.define_class at definition time -- registration-immune by
   construction.  "HOL.type" appears there iff the declared super sort is
   empty (it is the implicit top, not a declared super), so it is dropped. *)
fun def_parse_supers thy c =
  case try (Axclass.get_info thy) c of
    NONE => NONE
  | SOME {def, ...} =>
      SOME (Thm.prop_of def
        |> Logic.dest_equals |> snd
        |> Logic.dest_conjunctions
        |> map_filter (fn t => try (snd o Logic.dest_of_class) t)
        |> filter_out (fn s => s = "HOL.type")
        |> sort_strings);
\<close>

ML \<open>
let
  val thy = \<^theory>
  val env_rings = Semantic_Digest.make_env (Thy_Info.get_theory "HOL.Rings")
  val idom_direct = these (def_parse_supers thy "Rings.idom")
  fun full_deps e n =
    case Semantic_Digest.semantics_of e (Universal_Key.Class n) of
      SOME (_, ds) => ds | NONE => []
in
  writeln ("      idom direct supers: " ^ commas idom_direct);
  check "S11a Rings.idom declares exactly 2 direct supers (A5 census)"
    (length idom_direct = 2);
  check "S11b idom's production super component == def-parse (direct, not transitive)"
    (eq_set (op =) (Semantic_Digest.class_parents env "Rings.idom", idom_direct));
  (* Discriminating TODAY: idom's transitive super set is 43 under HOL.Rings
     and 48 under Main-scale envs (post-hoc `subclass` widenings), so an
     extraction that leaks transitivity cannot pass this. *)
  check "S11c idom's full dep set is env-independent (Rings env vs this env)"
    (eq_set (op =) (full_deps env_rings "Rings.idom", full_deps env "Rings.idom"))
end
\<close>

subsection \<open>S12 class: production extraction == def-parse, every class in scope\<close>

ML \<open>
let
  val thy = \<^theory>
  val classes = Sign.all_classes thy
  val bad = classes |> map_filter (fn c =>
    let val prod = Semantic_Digest.class_parents env c in
      case def_parse_supers thy c of
        NONE =>
          (* axiomatic class without axclass info (HOL.type etc.): the
             production extraction must yield no parents at all *)
          if null prod then NONE
          else SOME (c ^ ": no axclass info but parents [" ^ commas prod ^ "]")
      | SOME direct =>
          if eq_set (op =) (prod, direct) then NONE
          else SOME (c ^ ": production=[" ^ commas prod ^ "] def-parse=[" ^
                     commas direct ^ "]")
    end)
in
  writeln ("      " ^ string_of_int (length classes) ^ " classes in scope, " ^
           string_of_int (length bad) ^ " mismatches");
  app (writeln o prefix "      MISMATCH ") (take 10 bad);
  check "S12  production extraction == def-parse over all classes in scope"
    (null bad)
end
\<close>

subsection \<open>S13 constant: function-package equations reach the digest\<close>

(* The function package writes only `f == f_sumC` to Defs; the equations must
   arrive from its registry.  The body mentions Orderings.ord_class.less, which
   a nat => nat type cannot supply. *)
fun sens_fun :: "nat \<Rightarrow> nat" where
  "sens_fun n = (if n < 2 then n else sens_fun (n - 1) + sens_fun (n - 2))"

(* No `termination`: the registry holds psimps only, each guarded by the
   `accp sens_pfun_rel` premise. *)
function sens_pfun :: "nat \<Rightarrow> nat" where
  "sens_pfun n = (if n < 2 then n else sens_pfun (n - 1) + sens_pfun (n - 2))"
  by pat_completeness auto

(* Under `context fixes`, the fixed variable becomes a parameter on export and
   the registry key is `sens_cfun ?sens_k`, not the bare constant. *)
context fixes sens_k :: nat begin
fun sens_cfun :: "nat \<Rightarrow> nat" where
  "sens_cfun 0 = sens_k"
| "sens_cfun (Suc n) = sens_cfun n + sens_k"
end

(* Controls: these packages carry the body in Defs and have no registry entry,
   so each must keep exactly its one Defs axiom. *)
primrec sens_prim :: "nat \<Rightarrow> nat" where
  "sens_prim 0 = 0"
| "sens_prim (Suc n) = sens_prim n"

definition sens_defn :: "nat \<Rightarrow> nat" where
  "sens_defn n = (if n < 2 then n else 0)"

partial_function (option) sens_part :: "nat \<Rightarrow> nat option" where
  "sens_part n = (if n < 2 then Some n else sens_part (n - 1))"

ML \<open>
(* Own env: the file-level env predates the subjects above. *)
let
  val env3 = Semantic_Digest.make_env \<^theory>
  fun own c = Semantic_Digest.own_defining_axioms env3 ("Test_Sensitivity." ^ c)
  fun mentions ps c = exists (fn (_, t) => exists_Const (fn (n, _) => n = c) t) ps
  (* MERGE pin: the Defs meta-equality survives AND an equation (a Trueprop)
     joins it.  Red under replace, red under any _sumC name filter. *)
  fun merged ps =
    exists (fn (_, t) => can Logic.dest_equals t) ps andalso
    exists (fn (_, t) => not (can Logic.dest_equals t)) ps
  fun show c = writeln ("      " ^ c ^ ": " ^ commas (map fst (own c)))
in
  app show ["sens_fun", "sens_pfun", "sens_cfun", "sens_prim", "sens_defn", "sens_part"];
  check "S13a sens_fun's props mention Orderings.ord_class.less (from its equation)"
    (mentions (own "sens_fun") "Orderings.ord_class.less");
  check "S13b sens_fun keeps its Defs axiom AND gains an equation (merge)"
    (merged (own "sens_fun"));
  check "S13c sens_pfun (no termination) reaches its equation via psimps"
    (mentions (own "sens_pfun") "Orderings.ord_class.less");
  check "S13d sens_pfun's psimps carry the accp premise"
    (mentions (own "sens_pfun") "Wellfounded.accp");
  check "S13e sens_pfun keeps its Defs axiom AND gains an equation (merge)"
    (merged (own "sens_pfun"));
  check "S13f primrec keeps exactly its Defs axiom"
    (map fst (own "sens_prim") = ["Test_Sensitivity.sens_prim_def"]);
  (* `definition` always records its Defs axiom as `_def_raw`
     (Specification.gen_def); `_def` is the derived fact *)
  check "S13g definition keeps exactly its Defs axiom"
    (map fst (own "sens_defn") = ["Test_Sensitivity.sens_defn_def_raw"]);
  check "S13h partial_function keeps exactly its Defs axiom"
    (map fst (own "sens_part") = ["Test_Sensitivity.sens_part_def"]);
  (* nat => nat => nat and the body-free Defs axiom cannot supply `plus` *)
  check "S13i fun under context-fixes reaches its equations (key `sens_cfun ?sens_k`)"
    (mentions (own "sens_cfun") "Groups.plus_class.plus")
end
\<close>

subsection \<open>S14 digest: nothing sits between a payload and its hash\<close>

ML \<open>
(* The witness carries an Abs with a binder name, a Free, TFrees and a
   schematic Var with a non-zero index: each of the transforms the removed
   alpha normaliser performed would change term128 of it. *)
let
  val t = Abs ("y", TFree ("'a", []),
            Free ("x", TFree ("'b", [])) $ Bound 0 $ Var (("v", 3), TFree ("'c", [])))
in
  check "S14  digest_term is Term_Digest.term128 itself"
    (Semantic_Digest.digest_term t = Term_Digest.term128 t)
end
\<close>

subsection \<open>Summary\<close>

ML \<open>
let val f = rev (!failures)
in
  if null f then writeln "ALL SENSITIVITY CHECKS PASSED"
  else error ("SENSITIVITY FAILURES (" ^ string_of_int (length f) ^ "):\n" ^
              cat_lines (map (prefix "    ") f))
end
\<close>

end
