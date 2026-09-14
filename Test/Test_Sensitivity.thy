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

subsection \<open>S13 constant: the facts named after the constant are its definition\<close>

(* The function package writes only `f == f_sumC` to Defs; the equations are
   the facts f.simps.  The body mentions Orderings.ord_class.less, which a
   nat => nat type cannot supply. *)
fun sens_fun :: "nat \<Rightarrow> nat" where
  "sens_fun n = (if n < 2 then n else sens_fun (n - 1) + sens_fun (n - 2))"

(* No `termination`: only f.psimps exists, each guarded by the
   `accp sens_pfun_rel` premise. *)
function sens_pfun :: "nat \<Rightarrow> nat" where
  "sens_pfun n = (if n < 2 then n else sens_pfun (n - 1) + sens_pfun (n - 2))"
  by pat_completeness auto

(* Under `context fixes`, the fixed variable becomes a parameter on export. *)
context fixes sens_k :: nat begin
fun sens_cfun :: "nat \<Rightarrow> nat" where
  "sens_cfun 0 = sens_k"
| "sens_cfun (Suc n) = sens_cfun n + sens_k"
end

(* A locale target: the function package registers nothing the theory can see
   (the registry source of 2026-09-13 returned nothing), but the exported fact
   sens_loc.sens_lfun.psimps exists. *)
locale sens_loc = fixes sens_k' :: nat
begin
function sens_lfun :: "nat \<Rightarrow> nat" where
  "sens_lfun n = (if n < sens_k' then n else sens_lfun (n - 1))"
  by pat_completeness auto
end

(* Packages that carry the body in Defs too: each takes its named fact. *)
primrec sens_prim :: "nat \<Rightarrow> nat" where
  "sens_prim 0 = 0"
| "sens_prim (Suc n) = sens_prim n"

definition sens_defn :: "nat \<Rightarrow> nat" where
  "sens_defn n = (if n < 2 then n else 0)"

partial_function (option) sens_part :: "nat \<Rightarrow> nat option" where
  "sens_part n = (if n < 2 then Some n else sens_part (n - 1))"

(* A constant sharing a datatype's name: sens_col.simps belongs to the type. *)
datatype sens_col = Sens_A | Sens_B
definition sens_col :: nat where "sens_col = 7"

(* inductive_set: sens_iset.simps is `(a : sens_iset) = ...`, headed by
   Set.member, so the guard rejects it and sens_iset_def answers. *)
inductive_set sens_iset :: "nat set" where
  "0 \<in> sens_iset"
| "n \<in> sens_iset \<Longrightarrow> Suc n \<in> sens_iset"

(* An author's X_def lemma on an abbreviation counts as its definition. *)
abbreviation sens_abb :: "nat \<Rightarrow> nat" where "sens_abb \<equiv> sens_defn"
lemma sens_abb_def: "sens_abb n = (if n < 2 then n else 0)"
  by (simp add: sens_defn_def)

(* A `fun` inside an `overloading` block (the AFP Pairing_Heap_List2_Analysis
   shape): its facts are sens_sz_hps.simps, named after the local binding,
   so only the body-free Defs axiom `sens_sz == sens_sz_hps_sumC` names the
   constant; the axiom is unfolded to those equations.  The sibling
   `definition` keeps its Defs axiom.  Only the `fun` mentions `plus`. *)
datatype sens_hp = Sens_Hp nat "sens_hp list"
consts sens_sz :: "'a \<Rightarrow> nat"
overloading
  sens_sz_hps \<equiv> "sens_sz :: sens_hp list \<Rightarrow> nat"
  sens_sz_hp \<equiv> "sens_sz :: sens_hp \<Rightarrow> nat"
begin
fun sens_sz_hps :: "sens_hp list \<Rightarrow> nat" where
  "sens_sz_hps (Sens_Hp x hsl # hsr) = sens_sz_hps hsl + sens_sz_hps hsr + 1"
| "sens_sz_hps [] = 0"
definition sens_sz_hp :: "sens_hp \<Rightarrow> nat" where
  "sens_sz_hp h = (case h of Sens_Hp x l \<Rightarrow> sens_sz l)"
end

ML \<open>
(* Own env: the file-level env predates the subjects above. *)
let
  val env3 = Semantic_Digest.make_env \<^theory>
  fun own c = Semantic_Digest.own_defining_axioms env3 ("Test_Sensitivity." ^ c)
  fun props_mention ps c = exists (fn (_, t) => exists_Const (fn (n, _) => n = c) t) ps
  (* one label per prop; a fact of several equations repeats its name *)
  fun labels c = distinct (op =) (map fst (own c))
  fun show c = writeln ("      " ^ c ^ ": " ^ commas (labels c))
in
  app show ["sens_fun", "sens_pfun", "sens_cfun", "sens_loc.sens_lfun", "sens_prim",
            "sens_defn", "sens_part", "sens_col", "sens_iset", "sens_abb", "sens_sz"];
  check "S13a sens_fun takes exactly sens_fun.simps (one equation)"
    (labels "sens_fun" = ["Test_Sensitivity.sens_fun.simps"] andalso
     length (own "sens_fun") = 1);
  check "S13b sens_fun's props mention Orderings.ord_class.less (from its equation)"
    (props_mention (own "sens_fun") "Orderings.ord_class.less");
  (* .simps before .psimps: no accp premise once termination is proved *)
  check "S13c sens_fun's props do not carry the accp premise"
    (not (props_mention (own "sens_fun") "Wellfounded.accp"));
  check "S13d sens_pfun (no termination) takes exactly sens_pfun.psimps"
    (labels "sens_pfun" = ["Test_Sensitivity.sens_pfun.psimps"]);
  check "S13e sens_pfun's psimps carry the equation and the accp premise"
    (props_mention (own "sens_pfun") "Orderings.ord_class.less" andalso
     props_mention (own "sens_pfun") "Wellfounded.accp");
  (* nat => nat => nat cannot supply `plus`; both equations must survive the guard *)
  check "S13f fun under context-fixes takes its two simps (mentions plus)"
    (labels "sens_cfun" = ["Test_Sensitivity.sens_cfun.simps"] andalso
     length (own "sens_cfun") = 2 andalso
     props_mention (own "sens_cfun") "Groups.plus_class.plus");
  check "S13g locale-target function takes its exported psimps (mentions less)"
    (labels "sens_loc.sens_lfun" = ["Test_Sensitivity.sens_loc.sens_lfun.psimps"] andalso
     props_mention (own "sens_loc.sens_lfun") "Orderings.ord_class.less");
  check "S13h primrec takes its two simps"
    (labels "sens_prim" = ["Test_Sensitivity.sens_prim.simps"] andalso
     length (own "sens_prim") = 2);
  check "S13i definition takes its _def"
    (labels "sens_defn" = ["Test_Sensitivity.sens_defn_def"]);
  check "S13j partial_function takes its simps"
    (labels "sens_part" = ["Test_Sensitivity.sens_part.simps"]);
  (* a `definition`'s Defs axiom is `_def_raw`, so a rule that stops at the
     guarded-to-nothing `sens_col.simps` and falls to Defs shows a different
     label: this is the pin of "an empty guarded answer moves on" *)
  check "S13k a constant named like a datatype takes its _def, not the type's simps"
    (labels "sens_col" = ["Test_Sensitivity.sens_col_def"] andalso
     not (props_mention (own "sens_col") "Test_Sensitivity.sens_col.Sens_A"));
  (* inductive_set's Defs axiom is itself named `_def`, so this pins the
     guard (member-headed simps rejected), not the move-on *)
  check "S13l inductive_set: guarded simps empty, its _def answers"
    (labels "sens_iset" = ["Test_Sensitivity.sens_iset_def"]);
  check "S13m an author's X_def lemma is the abbreviation's definition"
    (labels "sens_abb" = ["Test_Sensitivity.sens_abb_def"] andalso
     props_mention (own "sens_abb") "Orderings.ord_class.less");
  (* three props: the sibling's Defs axiom and the fun's two equations; the
     body-free `_sumC` axiom is gone *)
  check "S13n fun inside overloading: the _sumC axiom unfolds to the local name's simps"
    (labels "sens_sz" = ["Test_Sensitivity.sens_sz_hp_def_raw", "Test_Sensitivity.sens_sz_hps.simps"] andalso
     length (own "sens_sz") = 3 andalso
     props_mention (own "sens_sz") "Groups.plus_class.plus" andalso
     not (props_mention (own "sens_sz") "Test_Sensitivity.sens_sz_hps_sumC"))
end
\<close>

subsection \<open>S15 constant: a class parameter keeps no definition even when a fact bears its name\<close>

(* The class parameter sens_op OWNS a fact named sens_op_def (the class
   assumption), so the named-fact source would answer for it; rule (1) must
   come first.  S2d/S2e cannot pin this: their subjects own no such fact. *)
class sens_cls =
  fixes sens_op :: "'a \<Rightarrow> 'a"
  assumes sens_op_def: "sens_op x = x"

ML \<open>
let
  val env4 = Semantic_Digest.make_env \<^theory>
  val c = "Test_Sensitivity.sens_cls_class.sens_op"
  val fact_exists =
    is_some (Facts.lookup (Context.Theory \<^theory>) (Global_Theory.facts_of \<^theory>) (c ^ "_def"))
in
  check "S15a the subject discriminates: the parameter owns a fact named sens_op_def"
    fact_exists;
  check "S15b a class parameter keeps no definition (rule 1 precedes the named-fact source)"
    (is_some (Axclass.class_of_param \<^theory> c) andalso
     null (Semantic_Digest.own_defining_axioms env4 c))
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
