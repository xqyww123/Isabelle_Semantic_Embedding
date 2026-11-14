theory Test_Sensitivity
  imports HOL.Record Isabelle_RPC.Remote_Procedure_Calling
begin

ML_file \<open>../Tools/semantic_digest.ML\<close>

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
  (mentions (Universal_Key.Constant \<^const_abbrev>\<open>Set.range\<close>)
    \<^const_name>\<open>Set.image\<close>);
check "S1b  HOL.not_equal depends on HOL.eq (its rhs)"
  (mentions (Universal_Key.Constant \<^const_abbrev>\<open>HOL.not_equal\<close>)
    \<^const_name>\<open>HOL.eq\<close>);
\<close>

subsection \<open>S2 constant: axioms of an axiomatized constant\<close>

ML \<open>
(* mem_Collect_eq relates member and Collect, so each must reach the other. *)
check "S2a  Set.member depends on Set.Collect (via mem_Collect_eq)"
  (mentions (Universal_Key.Constant \<^const_name>\<open>Set.member\<close>)
    \<^const_name>\<open>Set.Collect\<close>);
check "S2b  Set.Collect depends on Set.member (via Collect_mem_eq)"
  (mentions (Universal_Key.Constant \<^const_name>\<open>Set.Collect\<close>)
    \<^const_name>\<open>Set.member\<close>);
(* HOL.The is DECLARED at HOL.thy:92-94 and axiomatised separately at :229, so
   its spec item carries no terms and never enters the Item_Net index --
   retrieve_global cannot see it; only a get_global scan can. *)
check "S2c  HOL.The reaches its separately-stated axiom"
  (length (Semantic_Digest.own_defining_axioms env \<^const_name>\<open>HOL.The\<close>) > 0);
(* ...and the axiom source must NOT drag in downstream instances. *)
check "S2d  plus picks up no downstream instance rule"
  (null (Semantic_Digest.own_defining_axioms env \<^const_name>\<open>Groups.plus_class.plus\<close>));
check "S2e  less_eq picks up no downstream instance rule"
  (null (Semantic_Digest.own_defining_axioms env \<^const_name>\<open>Orderings.ord_class.less_eq\<close>));
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
    (length (deps_of (Universal_Key.Locale \<^locale>\<open>Groups.semigroup\<close>)) > 1);
  (* parent edge: abel_semigroup has a predicate parent AND its own assumes --
     the exact shape that lost its parent edge when hyp_spec_of replaced
     axioms_of *)
  check "S3b  Groups.abel_semigroup has a LocaleK edge to its parent"
    (exists (fn (k, _) => k = Universal_Key.LocaleK)
       (deps_of (Universal_Key.Locale \<^locale>\<open>Groups.abel_semigroup\<close>)));
  check "S3c  sens_child has a LocaleK edge to sens_parent"
    (exists (fn (k, m) => k = Universal_Key.LocaleK andalso
                          m = \<^locale>\<open>Test_Sensitivity.sens_parent\<close>)
       (deps2 \<^locale>\<open>Test_Sensitivity.sens_child\<close>));
  (* defines: Element.Defines is part of hyp_spec and must not be dropped *)
  check "S3d  sens_def reaches its defines body (depends on Groups.plus)"
    (exists (fn (_, m) => m = \<^const_name>\<open>Groups.plus_class.plus\<close>)
       (deps2 \<^locale>\<open>Test_Sensitivity.sens_def\<close>))
end
\<close>

subsection \<open>S3, continued: a locale's declared imports are part of its digest\<close>

locale sens_shift = sens_parent "\<lambda>n. p (n + 1)" for p :: "nat \<Rightarrow> bool" + assumes "p 5"
locale sens_twice = A: sens_parent p + B: sens_parent q for p q
locale sens_swap = sens_twice q p for p q
locale sens_plain0 = sens_parent p for p
locale sens_fixes = fixes f :: "nat \<Rightarrow> nat"
(* two parameters and two assumptions, declared against the order of Term_Ord.term_ord *)
locale sens_two = fixes b :: "nat \<Rightarrow> bool" and a :: "nat \<Rightarrow> bool" assumes "b 0" and "a 1"
locale sens_late = sens_parent p for p + assumes p1: "p 1"
(* registered AFTER the declaration, with an argument no declared import has *)
sublocale sens_late \<subseteq> X: sens_parent "\<lambda>n. p (n + 1)" by unfold_locales (simp only: add_0_left p1)

ML \<open>
(* A locale's name is in its payload, so the digests of two fixtures always
   differ and prove nothing.  locale_digest_with_imports varies the imports of
   ONE locale; the production digest must be that function at the imports of
   the declaration. *)
let
  val thy = \<^theory>
  val env3 = Semantic_Digest.make_env thy
  val parent = \<^locale>\<open>Test_Sensitivity.sens_parent\<close>
  val child = \<^locale>\<open>Test_Sensitivity.sens_child\<close>
  val def = \<^locale>\<open>Test_Sensitivity.sens_def\<close>
  val shifted = \<^locale>\<open>Test_Sensitivity.sens_shift\<close>
  val twice = \<^locale>\<open>Test_Sensitivity.sens_twice\<close>
  val swap = \<^locale>\<open>Test_Sensitivity.sens_swap\<close>
  val plain0 = \<^locale>\<open>Test_Sensitivity.sens_plain0\<close>
  val fixes = \<^locale>\<open>Test_Sensitivity.sens_fixes\<close>
  val two = \<^locale>\<open>Test_Sensitivity.sens_two\<close>
  val late = \<^locale>\<open>Test_Sensitivity.sens_late\<close>
  fun sem n = Semantic_Digest.semantics_of env3 (Universal_Key.Locale n)
  fun digest n = (case sem n of SOME (SOME d, _) => d | _ => error ("no digest: " ^ n))
  fun deps n = (case sem n of SOME (_, ds) => ds | NONE => [])
  val with_imports = Semantic_Digest.locale_digest_with_imports env3
  val P = Free ("p", \<^typ>\<open>nat \<Rightarrow> bool\<close>)
  val Q = Free ("q", \<^typ>\<open>nat \<Rightarrow> bool\<close>)
  val shift = \<^term>\<open>\<lambda>n. (p :: nat \<Rightarrow> bool) (n + 1)\<close>
  val declared = [(parent, [P])]
  (* payloads rebuilt by hand from the literal names in semantic_digest.ML *)
  val nilP = Const ("Semantic_Digest.nil", dummyT)
  fun tag s t = Const ("Semantic_Digest.kind." ^ s, dummyT) $ t
  fun hand n params hyps = Const (n, dummyT) $ params $ hyps
  val twice_own = hand twice (Q $ (P $ nilP)) nilP
in
  check "S3e  sens_child's digest is the one with its declared import"
    (digest child = with_imports child declared);
  check "S3f  sens_shift's digest is the one with its instantiated import"
    (digest shifted = with_imports shifted [(parent, [shift])]);
  check "S3g  sens_twice's digest is the one with both its imports"
    (digest twice = with_imports twice [(parent, [P]), (parent, [Q])]);

  check "S3h  dropping the import changes the digest"
    (with_imports child declared <> with_imports child []);
  check "S3i  importing another parent changes the digest"
    (with_imports child declared <> with_imports child [(def, [P])]);
  check "S3j  another instantiation of the parent changes the digest"
    (with_imports child declared <> with_imports child [(parent, [shift])]);
  check "S3k  importing the parent a second time changes the digest"
    (with_imports child declared <> with_imports child [(parent, [P]), (parent, [Q])]);

  check "S3l  the order of the imports does not change the digest"
    (with_imports child [(parent, [P]), (def, [Q])] =
     with_imports child [(def, [Q]), (parent, [P])]);
  check "S3m  a repeated identical import counts once"
    (with_imports child [(parent, [P]), (parent, [P])] = with_imports child declared);
  check "S3n  which argument goes to which parent changes the digest"
    (with_imports child [(parent, [P]), (def, [Q])] <>
     with_imports child [(parent, [Q]), (def, [P])]);

  (* A locale without imports keeps the three-component payload: its stored
     digests stay valid. *)
  check "S3o  sens_parent (no import) has the three-component payload"
    (let val d = Semantic_Digest.digest_term (tag "locale"
        (hand parent (P $ nilP)
          (tag "ax" (HOLogic.mk_Trueprop (P $ \<^term>\<open>0::nat\<close>)) $ nilP)))
     in digest parent = d andalso with_imports parent [] = d end);
  (* ...also where the removed fallback used to consult Locale.axioms_of: that
     list is empty for a locale without imports. *)
  check "S3p  sens_fixes (no import, no assumption): axioms_of is empty, payload unchanged"
    (null (Locale.axioms_of thy fixes) andalso
     digest fixes = Semantic_Digest.digest_term (tag "locale"
       (hand fixes (Free ("f", \<^typ>\<open>nat \<Rightarrow> nat\<close>) $ nilP) nilP)));

  (* The fallback is gone: Locale.axioms_of is not empty here, yet the
     assumptions component is, and no edge leads to the parent's predicate. *)
  check "S3q  sens_plain0 (an import, no assumption): empty assumptions, one import item"
    (not (null (Locale.axioms_of thy plain0)) andalso
     digest plain0 = Semantic_Digest.digest_term (tag "locale"
       (hand plain0 (P $ nilP) nilP $ (tag "import" (Const (parent, dummyT) $ P) $ nilP))));
  check "S3r  sens_plain0 has no ConstantK edge to the predicate constant sens_parent"
    (not (member (op =) (deps plain0)
       (Universal_Key.ConstantK, \<^const_name>\<open>Test_Sensitivity.sens_parent\<close>)));

  check "S3s  a sublocale registered later does not enter sens_late's digest"
    (length (filter (fn {target, ...} => target = late) (Locale.dest_dependencies [] thy)) = 2
     andalso digest late = with_imports late declared
     andalso digest late <> with_imports late [(parent, [P]), (parent, [shift])]);

  check "S3t  swapped arguments of one import change the digest"
    (with_imports child [(twice, [P, Q])] <> with_imports child [(twice, [Q, P])]);
  check "S3u  the type of an argument is part of the digest"
    (with_imports child declared <>
     with_imports child [(parent, [Free ("p", \<^typ>\<open>int \<Rightarrow> bool\<close>)])]);
  check "S3v  sens_swap's arguments are in the PARENT's parameter order"
    (digest swap = with_imports swap [(twice, [Q, P])] andalso
     digest swap <> with_imports swap [(twice, [P, Q])]);

  check "S3w  sens_shift depends on Groups.plus, which occurs only in an import's argument"
    (member (op =) (deps shifted)
       (Universal_Key.ConstantK, \<^const_name>\<open>Groups.plus_class.plus\<close>));
  check "S3x  sens_twice has exactly one LocaleK edge, to sens_parent"
    (filter (fn (k, _) => k = Universal_Key.LocaleK) (deps twice) =
       [(Universal_Key.LocaleK, parent)]);
  (* no import, no assumption: the parameter's type is the only source of deps *)
  check "S3y  sens_fixes depends on exactly the types of its parameter"
    (eq_set (op =) (deps fixes,
       [(Universal_Key.TypeK, \<^type_name>\<open>fun\<close>),
        (Universal_Key.TypeK, \<^type_name>\<open>nat\<close>)]));

  (* The ORDER inside the payload's lists: parameters and assumptions as declared,
     import items by Term_Ord.term_ord; in each list the last element is outermost.
     Stored digests depend on it. *)
  check "S3z  sens_two (no import): parameters and assumptions in declaration order"
    (let
       val A = Free ("a", \<^typ>\<open>nat \<Rightarrow> bool\<close>)
       val B = Free ("b", \<^typ>\<open>nat \<Rightarrow> bool\<close>)
     in
       digest two = Semantic_Digest.digest_term (tag "locale"
         (hand two (A $ (B $ nilP))
           (tag "ax" (HOLogic.mk_Trueprop (A $ \<^term>\<open>1::nat\<close>)) $
             (tag "ax" (HOLogic.mk_Trueprop (B $ \<^term>\<open>0::nat\<close>)) $ nilP))))
     end);
  check "S3aa sens_twice: the payload with its two import items"
    (digest twice = Semantic_Digest.digest_term (tag "locale"
       (twice_own $
         (tag "import" (Const (parent, dummyT) $ Q) $
           (tag "import" (Const (parent, dummyT) $ P) $ nilP)))));
  (* "aa" precedes "p" alphabetically (term_ord) and follows it by length (fast_term_ord) *)
  check "S3ab import items are ordered by Term_Ord.term_ord"
    (let val AA = Free ("aa", \<^typ>\<open>nat \<Rightarrow> bool\<close>) in
       with_imports twice [(parent, [P]), (parent, [AA])] =
       Semantic_Digest.digest_term (tag "locale"
         (twice_own $
           (tag "import" (Const (parent, dummyT) $ P) $
             (tag "import" (Const (parent, dummyT) $ AA) $ nilP))))
     end);
  (* the FIRST of the two is kept: the instance Isabelle activates *)
  check "S3ac imports equal up to bound-variable names are one item, the first"
    (with_imports child
       [(parent, [shift]), (parent, [\<^term>\<open>\<lambda>m. (p :: nat \<Rightarrow> bool) (m + 1)\<close>])] =
     with_imports child [(parent, [shift])])
end
\<close>

subsection \<open>S4 type: typedef representing set, also when ctr_sugar answers\<close>

ML \<open>
check "S4a  Int.int depends on Int.intrel (from its defining set)"
  (mentions (Universal_Key.Type \<^type_name>\<open>Int.int\<close>)
    \<^const_name>\<open>Int.intrel\<close>);
(* Nat.nat answers on BOTH channels (ctrs [0,Suc] AND a typedef over ind);
   short-circuiting on ctr_sugar used to discard the representing set. *)
check "S4b  Nat.nat reaches its typedef predicate despite having ctr_sugar"
  (mentions (Universal_Key.Type \<^type_name>\<open>Nat.nat\<close>)
    \<^const_name>\<open>Nat.Nat\<close>);
\<close>

subsection \<open>S5 class: parameters\<close>

ML \<open>
check "S5a  Orderings.ord depends on its parameter less_eq"
  (mentions (Universal_Key.Class \<^class>\<open>Orderings.ord\<close>)
    \<^const_name>\<open>Orderings.ord_class.less_eq\<close>);
check "S5b  Orderings.ord depends on its parameter less"
  (mentions (Universal_Key.Class \<^class>\<open>Orderings.ord\<close>)
    \<^const_name>\<open>Orderings.ord_class.less\<close>);
\<close>

subsection \<open>S6 theorem: sort constraints yield class edges\<close>

ML \<open>
check "S6  not_less has a ClassK edge for its linorder sort"
  (mentions_kind (Universal_Key.Named_Theorem \<^unchecked_name>\<open>Orderings.linorder_class.not_less\<close>)
     (Universal_Key.ClassK, \<^class>\<open>Orderings.linorder\<close>));
(* The same statement handed over as a THEOREM VALUE (the pipeline's own form:
   entries carry thms, not names) must yield the same edges.  Set comparison:
   the name-valued path merges per-thm lists through `unions`, which changes
   the ORDER, and dep lists are unordered sets by contract. *)
check "S6b  the thm-valued form agrees with the name-valued form"
  (eq_set (op =)
     (deps_of (Universal_Key.Theorem @{thm Orderings.linorder_class.not_less}),
      deps_of (Universal_Key.Named_Theorem \<^unchecked_name>\<open>Orderings.linorder_class.not_less\<close>)));
\<close>

subsection \<open>S7 class: the digest must not depend on the enclosing env\<close>

ML \<open>
(* Rings.idom is widened downstream by Semiring_Normalization's
   `subclass (in idom) ...`, so its transitive super set differs between envs
   (43 under HOL.Rings, 48 under Main).  Orderings.order cannot discriminate. *)
let
  val env_rings = Semantic_Digest.make_env (Context.get_theory {long = true} \<^theory> \<^unchecked_name>\<open>HOL.Rings\<close>)
  fun d e n = Option.map fst (Semantic_Digest.semantics_of e (Universal_Key.Class n))
  fun supers e n = length (Sign.super_classes (Semantic_Digest.theory_of_env e) n)
  fun cmp n =
    (writeln ("      (supers: Rings=" ^ string_of_int (supers env_rings n) ^
              ", Main=" ^ string_of_int (supers env n) ^ ")");
     check ("S7  " ^ n ^ " digest is env-independent") (d env_rings n = d env n))
in map cmp [\<^class>\<open>Rings.idom\<close>, \<^class>\<open>Rings.comm_ring_1\<close>] end
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
  writeln ("      sens_ctrA ctrs: " ^ commas (ctr_names \<^type_name>\<open>Test_Sensitivity.sens_ctrA\<close>));
  writeln ("      sens_ctrB ctrs: " ^ commas (ctr_names \<^type_name>\<open>Test_Sensitivity.sens_ctrB\<close>));
  check "S9  constructor order is preserved (not sorted away)"
    (ctr_names \<^type_name>\<open>Test_Sensitivity.sens_ctrA\<close> = ["SA", "SB"] andalso
     ctr_names \<^type_name>\<open>Test_Sensitivity.sens_ctrB\<close> = ["TB", "TA"])
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
    (is_some (d (Universal_Key.Named_Introduction_Rule \<^unchecked_name>\<open>HOL.conjI\<close>)));
  check "S10b Named_Introduction_Rule deps agree with Named_Theorem"
    (d (Universal_Key.Named_Introduction_Rule \<^unchecked_name>\<open>HOL.conjI\<close>) =
     d (Universal_Key.Named_Theorem \<^unchecked_name>\<open>HOL.conjI\<close>));
  check "S10c theorem-alike entities carry no digest"
    (Option.map fst (Semantic_Digest.semantics_of env
       (Universal_Key.Named_Theorem \<^unchecked_name>\<open>HOL.conjI\<close>)) = SOME NONE)
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
        |> filter_out (fn s => s = \<^class>\<open>HOL.type\<close>)
        |> sort_strings);
\<close>

ML \<open>
let
  val thy = \<^theory>
  val env_rings = Semantic_Digest.make_env (Context.get_theory {long = true} \<^theory> \<^unchecked_name>\<open>HOL.Rings\<close>)
  val idom_direct = these (def_parse_supers thy \<^class>\<open>Rings.idom\<close>)
  fun full_deps e n =
    case Semantic_Digest.semantics_of e (Universal_Key.Class n) of
      SOME (_, ds) => ds | NONE => []
in
  writeln ("      idom direct supers: " ^ commas idom_direct);
  check "S11a Rings.idom declares exactly 2 direct supers (A5 census)"
    (length idom_direct = 2);
  check "S11b idom's production super component == def-parse (direct, not transitive)"
    (eq_set (op =) (Semantic_Digest.class_parents env \<^class>\<open>Rings.idom\<close>, idom_direct));
  (* Discriminating TODAY: idom's transitive super set is 43 under HOL.Rings
     and 48 under Main-scale envs (post-hoc `subclass` widenings), so an
     extraction that leaks transitivity cannot pass this. *)
  check "S11c idom's full dep set is env-independent (Rings env vs this env)"
    (eq_set (op =)
      (full_deps env_rings \<^class>\<open>Rings.idom\<close>,
       full_deps env \<^class>\<open>Rings.idom\<close>))
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
  app show ["sens_fun", "sens_pfun", "sens_cfun", \<^unchecked_name>\<open>sens_loc.sens_lfun\<close>, "sens_prim",
            "sens_defn", "sens_part", "sens_col", "sens_iset", "sens_abb", "sens_sz"];
  check "S13a sens_fun takes exactly sens_fun.simps (one equation)"
    (labels "sens_fun" = [\<^unchecked_name>\<open>Test_Sensitivity.sens_fun.simps\<close>] andalso
     length (own "sens_fun") = 1);
  check "S13b sens_fun's props mention Orderings.ord_class.less (from its equation)"
    (props_mention (own "sens_fun") \<^const_name>\<open>Orderings.ord_class.less\<close>);
  (* .simps before .psimps: no accp premise once termination is proved *)
  check "S13c sens_fun's props do not carry the accp premise"
    (not (props_mention (own "sens_fun") \<^const_name>\<open>Wellfounded.accp\<close>));
  check "S13d sens_pfun (no termination) takes exactly sens_pfun.psimps"
    (labels "sens_pfun" = [\<^unchecked_name>\<open>Test_Sensitivity.sens_pfun.psimps\<close>]);
  check "S13e sens_pfun's psimps carry the equation and the accp premise"
    (props_mention (own "sens_pfun") \<^const_name>\<open>Orderings.ord_class.less\<close> andalso
     props_mention (own "sens_pfun") \<^const_name>\<open>Wellfounded.accp\<close>);
  (* nat => nat => nat cannot supply `plus`; both equations must survive the guard *)
  check "S13f fun under context-fixes takes its two simps (mentions plus)"
    (labels "sens_cfun" = [\<^unchecked_name>\<open>Test_Sensitivity.sens_cfun.simps\<close>] andalso
     length (own "sens_cfun") = 2 andalso
     props_mention (own "sens_cfun") \<^const_name>\<open>Groups.plus_class.plus\<close>);
  check "S13g locale-target function takes its exported psimps (mentions less)"
    (labels \<^unchecked_name>\<open>sens_loc.sens_lfun\<close> =
       [\<^unchecked_name>\<open>Test_Sensitivity.sens_loc.sens_lfun.psimps\<close>] andalso
     props_mention (own \<^unchecked_name>\<open>sens_loc.sens_lfun\<close>)
       \<^const_name>\<open>Orderings.ord_class.less\<close>);
  check "S13h primrec takes its two simps"
    (labels "sens_prim" = [\<^unchecked_name>\<open>Test_Sensitivity.sens_prim.simps\<close>] andalso
     length (own "sens_prim") = 2);
  check "S13i definition takes its _def"
    (labels "sens_defn" = [\<^unchecked_name>\<open>Test_Sensitivity.sens_defn_def\<close>]);
  check "S13j partial_function takes its simps"
    (labels "sens_part" = [\<^unchecked_name>\<open>Test_Sensitivity.sens_part.simps\<close>]);
  (* a `definition`'s Defs axiom is `_def_raw`, so a rule that stops at the
     guarded-to-nothing `sens_col.simps` and falls to Defs shows a different
     label: this is the pin of "an empty guarded answer moves on" *)
  check "S13k a constant named like a datatype takes its _def, not the type's simps"
    (labels "sens_col" = [\<^unchecked_name>\<open>Test_Sensitivity.sens_col_def\<close>] andalso
     not (props_mention (own "sens_col") \<^const_name>\<open>Test_Sensitivity.sens_col.Sens_A\<close>));
  (* inductive_set's Defs axiom is itself named `_def`, so this pins the
     guard (member-headed simps rejected), not the move-on *)
  check "S13l inductive_set: guarded simps empty, its _def answers"
    (labels "sens_iset" = [\<^unchecked_name>\<open>Test_Sensitivity.sens_iset_def\<close>]);
  check "S13m an author's X_def lemma is the abbreviation's definition"
    (labels "sens_abb" = [\<^unchecked_name>\<open>Test_Sensitivity.sens_abb_def\<close>] andalso
     props_mention (own "sens_abb") \<^const_name>\<open>Orderings.ord_class.less\<close>);
  (* three props: the sibling's Defs axiom and the fun's two equations; the
     body-free `_sumC` axiom is gone *)
  check "S13n fun inside overloading: the _sumC axiom unfolds to the local name's simps"
    (labels "sens_sz" =
       [\<^unchecked_name>\<open>Test_Sensitivity.sens_sz_hp_def_raw\<close>,
        \<^unchecked_name>\<open>Test_Sensitivity.sens_sz_hps.simps\<close>] andalso
     length (own "sens_sz") = 3 andalso
     props_mention (own "sens_sz") \<^const_name>\<open>Groups.plus_class.plus\<close> andalso
     not (props_mention (own "sens_sz") \<^const_name>\<open>Test_Sensitivity.sens_sz_hps_sumC\<close>))
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
  val c = \<^const_name>\<open>Test_Sensitivity.sens_cls_class.sens_op\<close>
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
