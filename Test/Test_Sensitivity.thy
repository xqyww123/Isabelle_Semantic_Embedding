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
locale sens_swapA = fixes f g :: "nat \<Rightarrow> nat" assumes "f 0 = 0"
locale sens_swapB = fixes f g :: "nat \<Rightarrow> nat" assumes "g 0 = 0"

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

ML \<open>
(* Replicate sem_locale's payload construction EXACTLY but WITHOUT the locale
   name, then normalise the whole thing in ONE pass.  Both details matter:
   - omit the name, or two differently-named locales always differ and the
     check passes vacuously (the self-deceiving shape);
   - normalise params and props TOGETHER, or each prop's Free independently
     takes z0 and the very desynchronisation under test is reproduced in the
     test itself -- an earlier version of this check did exactly that and
     reported a failure the code did not have. *)
let
  val thy = \<^theory>
  fun hyp_props n =
    Locale.hyp_spec_of thy n
    |> maps (fn Element.Assumes asms => maps (fn (_, ts) => maps (op ::) ts) asms
              | Element.Defines defs => map (fn (_, (t, _)) => t) defs
              | _ => [])
  val nil_p = Const ("Semantic_Digest.nil", dummyT)
  fun shape n =
    let
      val params = Locale.params_of thy n
      val pp = fold (fn ((nm, T), _) => fn acc => Free (nm, T) $ acc) params nil_p
      val ap = fold (fn p => fn acc => Const ("Semantic_Digest.kind.ax", dummyT) $ p $ acc)
                 (hyp_props n) nil_p
    in Semantic_Digest.normalize (pp $ ap) end
in
  check "S3e  swapping which same-typed parameter is constrained is visible"
    (shape "Test_Sensitivity.sens_swapA" <> shape "Test_Sensitivity.sens_swapB")
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

subsection \<open>S8 type_synonym: parameters share the body's canonicalisation\<close>

type_synonym ('a, 'b) sens_perm_A = "'a \<Rightarrow> 'b"
type_synonym ('a, 'b) sens_perm_B = "'b \<Rightarrow> 'a"
type_synonym 'a sens_ren_A = "'a list"
type_synonym 'b sens_ren_B = "'b list"

ML \<open>
let
  fun body n =
    case Type.the_decl (Sign.tsig_of \<^theory>) (n, Position.none) of
      Type.Abbreviation (vs, b, _) =>
        Semantic_Digest.normalize
          (fold (fn v => fn acc => Const ("Semantic_Digest.typ", TFree (v, [])) $ acc) vs
             (Const ("Semantic_Digest.typ", b)))
    | _ => Const ("<not an abbreviation>", dummyT)
in
  check "S8a  ('a,'b) 'a=>'b  distinct from  'b=>'a"
    (body "Test_Sensitivity.sens_perm_A" <> body "Test_Sensitivity.sens_perm_B");
  check "S8b  'a list  same as  'b list under renaming"
    (body "Test_Sensitivity.sens_ren_A" = body "Test_Sensitivity.sens_ren_B")
end
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
