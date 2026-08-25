signature INFRA_FILTER = sig
  val smart_size_of_term : term -> int
  (* True if the theory is marked as infrastructure: a member of the enumerated
     set of theory long names (infra_theory_long_names below).  Whole-theory
     predicate for callers that want to exclude a theory outright (e.g. the
     AoA-learning target scope), complementing the per-entity filters. *)
  val is_infra_theory : theory -> bool
  val gen_infra_filters : Context.generic ->
    {is_infra_const: string -> bool,
     is_infra_thm: string * thm -> bool,
     is_infra_induct_thm: string * thm -> bool,
     is_infra_type: string -> bool,
     is_infra_class: string -> bool,
     is_infra_locale: string -> bool,
     is_infra_dynamic_fact: string -> bool,
     is_infra_method: string -> bool,
     is_declared_infra_thm: string * thm -> bool,
     (* Which rule rejected this entity, or NONE if it was kept.  `is_infra_*`
        is `is_some` of these, so there is one disjunction, not two that must
        be kept in agreement.  A cascade rejection reads "const:<name>" -- ask
        `infra_const_rule` again to learn why that constant is infrastructure. *)
     infra_const_rule: string -> typ option -> string option,
     infra_thm_rule: string * thm -> string option,
     has_infra_decls: bool}
end

structure Infra_Filter : INFRA_FILTER = struct

val smart_size_of_term = smart_size_of_term (* from Performant_Isabelle_ML *)

(* Theories whose own entities are infrastructure: no records, not retrievable,
   and their constants cascade (any theorem whose statement mentions one is
   dropped too, via is_infra_thm).  The marking is an ENUMERATED set of theory
   LONG names:
   - long names, because a base name is not an identity — the AFP has its own
     `Cooper` and `Approximation`, both ordinary mathematics;
   - enumeration rather than "session default plus exceptions", because a
     theory added upstream then defaults to ordinary mathematics: machinery
     shows up as visible store noise, which is repairable, whereas a session
     default deletes mathematics silently (the Algebra_Aux incident).
   Composition (40 names):
   - 15 marked HOL-Decision_Procs theories — reflected-syntax machinery behind
     decision procedures.  The session's ordinary-mathematics theories
     (Algebra_Aux, Polynomial_List, DP_Library, Approximation,
     Approximation_Bounds, Rat_Pair) are deliberately NOT here; per-theory
     rationale in DECISION_PROCS_INFRA_THEORY_LIST.md.
   - 23 tool-support theories (Quickcheck/Nitpick/SMT internals, code-generator
     bridges, HOL-Real_Asymp's expansion engine), each vetted against AFP
     statement-level citations; evidence table in TOOL_THEORY_MARKING_LIST.md.
     `HOL.Random`, `HOL.Predicate_Compile` and `HOL.Code_Numeral` are
     deliberately absent — AFP entries state lemmas about their constants.
   - `Minilang.Minilang`: internal proof-language plumbing (TAG/GOAL/PROTECT/
     ISO_* constants + their _def lemmas); `hide_const (open)` only hides the
     short names, the fully-qualified names still leak.
   - `HOL.Code_Evaluation`: evaluation-oracle plumbing. *)
val infra_theory_long_names = Symtab.make_set [
  (* HOL-Decision_Procs, marked (15) *)
  "HOL-Decision_Procs.Commutative_Ring",
  "HOL-Decision_Procs.Commutative_Ring_Complete",
  "HOL-Decision_Procs.Reflective_Field",
  "HOL-Decision_Procs.Conversions",
  "HOL-Decision_Procs.Cooper",
  "HOL-Decision_Procs.Ferrack",
  "HOL-Decision_Procs.MIR",
  "HOL-Decision_Procs.Reflected_Multivariate_Polynomial",
  "HOL-Decision_Procs.Dense_Linear_Order",
  "HOL-Decision_Procs.Parametric_Ferrante_Rackoff",
  "HOL-Decision_Procs.Decision_Procs",
  "HOL-Decision_Procs.Commutative_Ring_Ex",
  "HOL-Decision_Procs.Approximation_Ex",
  "HOL-Decision_Procs.Approximation_Quickcheck_Ex",
  "HOL-Decision_Procs.Dense_Linear_Order_Ex",
  (* tool support (23) *)
  "HOL.Quickcheck_Exhaustive",
  "HOL.Quickcheck_Narrowing",
  "HOL.Quickcheck_Random",
  "HOL.Random_Pred",
  "HOL.Random_Sequence",
  "HOL.Lazy_Sequence",
  "HOL.Limited_Sequence",
  "HOL.Nitpick",
  "HOL.Nunchaku",
  "HOL.SMT",
  "HOL.Meson",
  "HOL.Metis",
  "HOL.Record",
  "HOL.Typerep",
  "HOL.Extraction",
  "HOL-Library.Code_Test",
  "HOL-Library.Code_Lazy",
  "HOL-Library.Code_Target_Nat",
  "HOL-Library.Code_Target_Int",
  "HOL-Library.Code_Cardinality",
  "Tools.Code_Generator",
  "HOL-Real_Asymp.Multiseries_Expansion",
  "HOL-Real_Asymp.Lazy_Eval",
  (* proof-language / evaluation plumbing (2) *)
  "Minilang.Minilang",
  "HOL.Code_Evaluation"]

fun is_infra_theory thy =
  Symtab.defined infra_theory_long_names (Context.theory_long_name thy)

(* User-declared infrastructure entities (via `declare [[infra_constant c ...]]`,
   `declare [[infra_type T ...]]`, `declare some_lemma[infra_thm]`), consulted by
   `gen_infra_filters` below.  Constants and types are name sets (single global entities).
   Theorems are stored as the *thm itself* in an `iNet` discrimination net keyed by
   proposition (NOT by name): a fact attribute receives the morphism-transformed thm at
   each locale interpretation, so storing the thm records the per-interpretation EXPORTED
   theorem `I.foo` — which a name (the stale `local.foo` hint, never re-stamped by the
   morphism) cannot.  Matching is by proposition (`Thm.eq_thm_prop`), exactly as Isabelle's
   own `named_theorems`.  A declared infra constant behaves identically to a built-in infra
   constant (e.g. `Minilang.*`): filtered AND cascading to every theorem whose statement
   mentions it (via `is_internal_constant` feeding `is_infra_thm`). *)
structure Infra_Decl = Generic_Data (
  type T = Symtab.set * thm iNet.net * Symtab.set   (* consts, thms, types *)
  val empty = (Symtab.empty, iNet.empty, Symtab.empty)
  fun merge ((c1,t1,y1),(c2,t2,y2)) =
    (Symtab.merge (K true) (c1,c2),
     iNet.merge Thm.eq_thm_prop (t1,t2),
     Symtab.merge (K true) (y1,y2))
)

(* `infra_constant`/`infra_type` are no-fact declarations (`declare [[infra_constant
   c ...]]`): constants/types cannot carry attributes, and `Args.const`/`Args.type_name`
   resolve the GLOBAL entity at parse time, closing over the interned name — immune to
   locale morphism replay.  `infra_thm`, by contrast, is an ordinary fact attribute
   (`declare some_lemma[infra_thm]`): the locale morphism transforms the *thm* (not its
   name tag), so storing the thm itself records the per-interpretation exported theorem and
   is locale-safe.  The declaration is always honoured; since matching is by proposition we
   additionally WARN on a trivially-shaped proposition (reflexivity / `True`), which would
   also suppress every same-statement lemma from retrieval.  (An earlier `[[infra_thm name]]`
   arg form stored a fact-name token that locale interpretation re-resolves globally and
   aborted on locale-local facts; and a name-hint variant silently recorded the stale
   `local.foo` and did nothing on interpretation.) *)
fun infra_decl_attr add = Thm.declaration_attribute (K (Infra_Decl.map add))

(* A proposition whose retrieval value is nil and which would over-match by proposition:
   `True`, reflexive HOL equality `t = t`, reflexive Pure `t \<equiv> t` / `A \<Longrightarrow> A`. *)
fun is_trivial_prop t =
  (case t of
     Const(\<^const_name>\<open>Trueprop\<close>, _) $ Const(\<^const_name>\<open>True\<close>, _) => true
   | Const(\<^const_name>\<open>Trueprop\<close>, _) $ (Const(\<^const_name>\<open>HOL.eq\<close>, _) $ a $ b) =>
       a aconv b
   | Const(\<^const_name>\<open>Pure.eq\<close>, _) $ a $ b => a aconv b
   | Const(\<^const_name>\<open>Pure.imp\<close>, _) $ a $ b => a aconv b
   | _ => false)

(* Each attribute accepts an optional leading `del` to UNdeclare (remove from the set/net)
   rather than add — mirroring `simp`/`simp del`. *)
val del_flag = Scan.lift (Scan.optional (Args.del >> K true) false)

val _ = Theory.setup (
  Attrib.setup \<^binding>\<open>infra_constant\<close>
    ((del_flag -- Scan.repeat1 (Args.const {proper = true, strict = false})) >>
      (fn (del, ns) => infra_decl_attr (fn (c,t,y) =>
         (fold (if del then Symtab.remove_set else Symtab.insert_set) ns c, t, y))))
    "declare (or, with `del`, undeclare) constants as semantic-retrieval infrastructure" #>
  Attrib.setup \<^binding>\<open>infra_type\<close>
    ((del_flag -- Scan.repeat1 (Args.type_name {proper = true, strict = false})) >>
      (fn (del, ns) => infra_decl_attr (fn (c,t,y) =>
         (c, t, fold (if del then Symtab.remove_set else Symtab.insert_set) ns y))))
    "declare (or, with `del`, undeclare) types as semantic-retrieval infrastructure" #>
  Attrib.setup \<^binding>\<open>infra_thm\<close>
    (del_flag >>
      (fn del => Thm.declaration_attribute (fn th => fn context =>
       let val th' = Thm.trim_context th
           (* honour the declaration either way; warn only when ADDING a trivially-shaped
              proposition, since matching is by proposition (it would also suppress every
              same-statement lemma from retrieval) *)
           val _ = if not del andalso is_trivial_prop (Thm.prop_of th')
                   then warning ("infra_thm on a trivially-shaped theorem " ^
                          quote (Syntax.string_of_term (Context.proof_of context)
                                   (Thm.prop_of th'))
                          ^ "; matching is by proposition, so this also suppresses every \
                            \same-statement lemma from retrieval")
                   else ()
       in Infra_Decl.map (fn (c,t,y) =>
            (c, (if del then iNet.delete_term_safe else iNet.insert_term_safe)
                  Thm.eq_thm_prop (Thm.full_prop_of th', th') t, y)) context
       end)))
    "declare (or, with `del`, undeclare) a theorem as semantic-retrieval infrastructure")

fun gen_infra_filters (context : Context.generic)
    : {is_infra_const: string -> bool,
       is_infra_thm: string * thm -> bool,
       is_infra_induct_thm: string * thm -> bool,
       is_infra_type: string -> bool, is_infra_class: string -> bool,
       is_infra_locale: string -> bool,
       is_infra_dynamic_fact: string -> bool, is_infra_method: string -> bool,
       is_declared_infra_thm: string * thm -> bool,
       infra_const_rule: string -> typ option -> string option,
       infra_thm_rule: string * thm -> string option,
       has_infra_decls: bool} =
  let
    (* User-declared infra entities (see `Infra_Decl` above). *)
    val (decl_consts, decl_thms, decl_types) = Infra_Decl.get context
    val has_thm_decls = not (iNet.is_empty decl_thms)
    val has_infra_decls =
      not (Symtab.is_empty decl_consts) orelse has_thm_decls
      orelse not (Symtab.is_empty decl_types)
    (* membership by proposition: structural candidates from the net, then exact aconv.
       Short-circuits to zero work (no full_prop_of / match) when nothing is declared. *)
    fun decl_infra_thm thm =
      has_thm_decls andalso
      exists (fn t => Thm.eq_thm_prop (t, thm))
        (iNet.match_term decl_thms (Thm.full_prop_of thm))
    val type_space = Context.cases Sign.type_space Proof_Context.type_space context
    val consts = Context.cases Sign.consts_of Proof_Context.consts_of context
    val const_space = Consts.space_of consts
    val facts = Context.cases Global_Theory.facts_of Proof_Context.facts_of context
    val fact_space = Facts.space_of facts
    val class_space = Context.cases Sign.class_space Proof_Context.class_space context
    val locale_space = Locale.locale_space (Context.theory_of context)
    fun is_hidden space name =
      Long_Name.is_hidden (Name_Space.intern space name)
    (* Entity → declaring-theory membership in the marking, via the name-space
       entry rather than the spelling of the name: instantiation-generated
       names are qualified by type, not by declaring theory (e.g.
       Set.typerep_set_inst.typerep_set is declared in HOL.List). *)
    fun is_from_infra_space space name =
      (case try (Name_Space.theory_name {long = true} space) name of
         SOME t => Symtab.defined infra_theory_long_names t
       | NONE => false)
    val all_type_names = Name_Space.get_names type_space
    val type_names = all_type_names
      |> filter (fn name =>
          name <> "fun"
          andalso not (Name_Space.is_concealed type_space name)
          andalso not (Long_Name.is_hidden (Name_Space.intern type_space name)))
    val type_name_prefixes = map (fn T => T ^ ".") type_names

    (* --- ADT/record infrastructure constants --- *)

    (* Preserved constant names: datatype constructors/selectors/case, BNF map/pred/rel/sets,
       record selectors/updaters/make/fields/extend/truncate *)
    (* BNF map/pred/rel/set (and ctr/case/co_rec) functions are NOT always bare
       Consts: a composed or custom-registered BNF -- e.g. the BNF_Operations /
       BNF_CC meta-theories (Compose.H, GFP.JF1/JF2, LFP.IF1/IF2, Lift.F',
       Permute.F', Subtypes.S) -- has a map that is a composition term, on which
       Term.dest_Const raises TERM.  So field extraction must tolerate non-Const
       terms, exactly like the guarded twin (safe_const_name) used for
       bnf_origin_pos_set below.  There is no const name to preserve for a
       non-Const field, so map_filter simply drops it. *)
    val safe_const_name = try (fst o Term.dest_Const)
    val thy = Context.theory_of context
    val (preserved_names, adt_record_prefixes) =
      let
        fun ctr_sugar_names T =
          case Context.cases Ctr_Sugar.ctr_sugar_of_global Ctr_Sugar.ctr_sugar_of context T of
            NONE => []
          | SOME cs =>
              map_filter safe_const_name (#ctrs cs)
              @ maps (map_filter safe_const_name) (#selss cs)
              @ map_filter safe_const_name [#casex cs]
              (* discriminators (isl, lnull, ...): user-facing interface cited
                 in AFP statements — whitelisted like the selectors *)
              @ map_filter safe_const_name (#discs cs)
        fun bnf_names T =
          case Context.cases BNF_Def.bnf_of_global BNF_Def.bnf_of context T of
            NONE => []
          | SOME bnf =>
              map_filter safe_const_name
                ([BNF_Def.map_of_bnf bnf, BNF_Def.pred_of_bnf bnf, BNF_Def.rel_of_bnf bnf]
                 @ BNF_Def.sets_of_bnf bnf)
        fun record_names T =
          case Record.get_info thy T of
            NONE => []
          | SOME info =>
              let val fields = map fst (#fields info)
                  val prefix = T ^ "."
              in
                fields
                @ map (fn f => f ^ Record.updateN) fields
                @ [prefix ^ "more", prefix ^ "more" ^ Record.updateN,
                   prefix ^ "make", prefix ^ "fields", prefix ^ "extend", prefix ^ "truncate"]
              end
        fun co_rec_names T =
          case Context.cases BNF_FP_Def_Sugar.fp_sugar_of_global BNF_FP_Def_Sugar.fp_sugar_of context T of
            NONE => []
          | SOME fp =>
              (case #fp_co_induct_sugar fp of
                NONE => []
              | SOME sugar => map_filter safe_const_name [#co_rec sugar])
        (* the size-plugin family (size_list, size_option, ...): user-facing
           (List.thy proves a lemma section about size_list; 78 AFP entries cite
           it).  The whole family, via the plugin's own registry. *)
        fun size_names T =
          case BNF_LFP_Size.size_of_global thy T of
            NONE => []
          | SOME (size_name, _) => [size_name]
        val (all_names, prefixes) = fold (fn T => fn (names, pfxs) =>
          let val ns = ctr_sugar_names T @ bnf_names T @ record_names T @ co_rec_names T
                       @ size_names T
          in (ns @ names, if null ns then pfxs else (T ^ ".") :: pfxs) end)
          type_names ([], [])
      in (all_names, prefixes) end
    val preserved_set = Strhashtab.make_set preserved_names

    (* BNF origin position set: positions (file, offset) where BNF-generated constants live.
       Used to distinguish auto-generated ADT constants from lift_definition/user constants. *)
    val bnf_origin_pos_set =
      let
        fun collect_bnf_names T =
          let
            val from_ctr = case Context.cases Ctr_Sugar.ctr_sugar_of_global Ctr_Sugar.ctr_sugar_of context T of
                NONE => []
              | SOME cs =>
                  map_filter safe_const_name (#ctrs cs)
                  @ maps (map_filter safe_const_name) (#selss cs)
                  @ map_filter safe_const_name [#casex cs]
                  @ map_filter safe_const_name (#discs cs)
            val from_bnf = case Context.cases BNF_Def.bnf_of_global BNF_Def.bnf_of context T of
                NONE => []
              | SOME bnf =>
                  map_filter safe_const_name
                    ([BNF_Def.map_of_bnf bnf, BNF_Def.pred_of_bnf bnf, BNF_Def.rel_of_bnf bnf]
                     @ BNF_Def.sets_of_bnf bnf)
            val from_fp = case Context.cases BNF_FP_Def_Sugar.fp_sugar_of_global BNF_FP_Def_Sugar.fp_sugar_of context T of
                NONE => []
              | SOME fp =>
                  let val res = #fp_res fp
                      val co_rec_names = case #fp_co_induct_sugar fp of
                          NONE => []
                        | SOME sugar => map_filter safe_const_name [#co_rec sugar]
                  in
                    map_filter safe_const_name
                      (#ctors res @ #dtors res @ #xtor_un_folds res @ #xtor_co_recs res)
                    @ co_rec_names
                  end
            val from_pre_bnf = case Context.cases BNF_FP_Def_Sugar.fp_sugar_of_global BNF_FP_Def_Sugar.fp_sugar_of context T of
                NONE => []
              | SOME fp =>
                  let val pre = #pre_bnf fp
                  in map_filter safe_const_name
                      ([BNF_Def.map_of_bnf pre] @ BNF_Def.sets_of_bnf pre)
                  end
          in from_ctr @ from_bnf @ from_fp @ from_pre_bnf end
        val all_bnf_names = maps collect_bnf_names type_names
        fun pos_key_of cname =
          case try (Name_Space.the_entry const_space) cname of
            NONE => NONE
          | SOME entry =>
              (case (Position.file_of (#pos entry), Position.offset_of (#pos entry)) of
                (SOME file, SOME offset) => SOME (String.concat [file, "\t", Int.toString offset])
              | _ => NONE)
      in Strhashtab.make_set (map_filter pos_key_of all_bnf_names) end

    fun on_bnf_origin_pos name =
      case try (Name_Space.the_entry const_space) name of
        NONE => false
      | SOME entry =>
          (case (Position.file_of (#pos entry), Position.offset_of (#pos entry)) of
            (SOME file, SOME offset) =>
              Strhashtab.defined bnf_origin_pos_set (String.concat [file, "\t", Int.toString offset])
          | _ => false)

    (* Quotient type infrastructure constants:
       - Abs_T/Rep_T (typedef-level; users work with quotient-level abs_T/rep_T instead)
       - pcr_T/cr_T (Lifting package correspondence relations) *)
    val quotient_typedef_infra = Strhashtab.make_set
      (maps (fn T =>
        case Quotient_Info.lookup_quotients_global thy T of
          NONE => []
        | SOME _ =>
            let val base = Long_Name.base_name T
                val qual = Long_Name.qualifier T
                fun mk name = if qual = "" then name else qual ^ "." ^ name
            in
              maps (fn ({Rep_name, Abs_name, ...}, _) => [Rep_name, Abs_name])
                (Typedef.get_info_global thy T)
              @ [mk ("pcr_" ^ base), mk ("cr_" ^ base)]
            end)
        type_names)

    (* Pre-BNF intermediate constant prefixes *)
    val pre_prefixes = map_filter (fn T =>
      case Context.cases BNF_FP_Def_Sugar.fp_sugar_of_global BNF_FP_Def_Sugar.fp_sugar_of context T of
        NONE => NONE
      | SOME fp =>
          (case safe_const_name (BNF_Def.map_of_bnf (#pre_bnf fp)) of
             SOME map_name => SOME (Long_Name.qualifier map_name ^ ".")
           | NONE => NONE))
      type_names

    (* Class instance constant infixes.  Deliberately over the UNFILTERED
       type-name list: `instantiation` machinery is also generated for the `fun`
       type (Sup_fun_inst.Sup_fun, ...) and for concealed types (Quickcheck's),
       and those instance constants are the same plumbing.  The other consumers
       of type names keep the filtered list. *)
    val inst_infixes = map (fn T => "_" ^ Long_Name.base_name T ^ "_inst.") all_type_names

    (* Constant-NAME prefixes of lifting/transfer plumbing, plus the HOL.equal
       constant itself.  These are name tests, not theory identities: rel_fun,
       bi_unique &c. are cited by thousands of transfer_rule lemmas yet are
       plumbing — kept rejected by design (ruled 08-24).  Theory-identity
       marking lives in infra_theory_long_names instead. *)
    val internal_prefixes = ["Lifting.", "BNF_Def.", "Transfer.",
          "HOL.equal", "ATP.", "Code_Evaluation."]

    (* Rule class_pred, authoritative form: the exact set of class-predicate
       constant names.  Logic.const_of_class appends "_class" to the class's
       full name, so this is a subset of the old string test (fail-closed), and
       it cannot produce a locale predicate (Sigma_Algebra.subset_class
       survives with no returns-prop guard). *)
    val class_pred_set =
      Strhashtab.make_set (map Logic.const_of_class (Sign.all_classes thy))

    (* Rule class_variant's kill set: the locale-level twins of type-class
       operations, enumerated from the class package's OWN operations registry
       (Class.these_operations).  Each entry's key is the class-namespace
       constant "A.B_class.c"; stripping the `_class` suffix off its qualifier
       gives the foundational locale twin "A.B.c".  The two are declared as a
       pair in one foundation step in the same theory, so the derived name can
       only denote that twin or no constant at all.  Only the `class` target
       machinery registers operations -- `interpretation P: L ...` copies never
       contribute -- so a human interpretation prefix colliding with a genuine
       class prefix (Algebra_Aux's `interpretation field_class: field ...`,
       AFP Elliptic_Locale's likewise) cannot condemn the interpreted locale's
       general constants.  The `_class` SUFFIX test on the qualifier is a
       correctness guard, not a heuristic: parameter entries conform, and
       extra-qualified keys ("A.B_class.q.c") must be skipped, matching the
       old gate's behaviour on them.  `Class.is_class` drops Axclass-only
       classes (e.g. HOL.type): they carry no Class data and would make
       these_operations raise. *)
    val has_class_variant_set =
      Strhashtab.make_set (map_filter (fn (key, _) =>
        let val qual = Long_Name.qualifier key
        in if String.isSuffix "_class" qual
           then SOME (String.concat [
                  String.substring (qual, 0, size qual - 6), ".",
                  Long_Name.base_name key])
           else NONE
        end)
        (Class.these_operations thy
          (filter (Class.is_class thy) (Sign.all_classes thy))))
    fun has_class_variant name = Strhashtab.defined has_class_variant_set name

    fun is_declared_const name = can (Consts.the_constraint consts) name

    (* First rule that fires, or NONE.  Thunks keep the short-circuit the plain
       `orelse` chain had: the later tests (on_bnf_origin_pos, the_constraint)
       are not cheap. *)
    fun first_rule tests =
      let fun go [] = NONE
            | go ((why, f) :: rest) = if f () then SOME why else go rest
      in go tests end

    val infra_const_cache : string option Strhashtab.table = Strhashtab.empty 4096
    (* The typ option argument is no longer consulted: every type-dependent rule
       reads the declared type via Consts.the_constraint itself, so the
       name-keyed cache cannot diverge across call sites that pass different
       types.  The argument stays for the callers' signature. *)
    fun infra_const_rule name (_ : typ option) =
      case Strhashtab.lookup infra_const_cache name of
        SOME result => result
      | NONE =>
          let val result =
            (* explicit declaration takes precedence over `preserved_set` *)
            if Symtab.defined decl_consts name then SOME "declared"
            (* The theory marking (rule infra_theory below) deliberately does NOT:
               it judges what a marked theory declares and stops at a type's public
               interface (constructors, selectors, ...).  Hoisted above this veto,
               the mentioned-constant cascade in is_infra_thm would erase every
               downstream development built on a marked theory's datatypes. *)
            else if Strhashtab.defined preserved_set name then NONE
            else first_rule
             [("concealed",       fn () => Name_Space.is_concealed const_space name),
              ("hidden",          fn () => is_hidden const_space name),
              ("infra_theory",    fn () => is_from_infra_space const_space name),
              ("internal_prefix", fn () => exists (fn pfx => String.isPrefix pfx name) internal_prefixes),
              ("pre_bnf_prefix",  fn () => exists (fn pfx => String.isPrefix pfx name) pre_prefixes),
              ("inst_infix",      fn () => exists (fn infix_ => String.isSubstring infix_ name) inst_infixes),
              ("class_variant",   fn () => has_class_variant name),
              ("quotient_typedef", fn () => Strhashtab.defined quotient_typedef_infra name),
              ("adt_record",      fn () => exists (fn pfx => String.isPrefix pfx name) adt_record_prefixes
                                           andalso on_bnf_origin_pos name),
              (* the .class. qualifier comes only from the `class` command's own
                 binding qualification; the _axioms companion is its
                 delta-introduction predicate, machinery.  The base predicate
                 class.X itself is human-cited (relativization lemmas) and KEPT. *)
              ("class_infix",     fn () => String.isSubstring ".class." name
                                           andalso String.isSuffix "_axioms" (Long_Name.base_name name)),
              ("class_pred",      fn () => Strhashtab.defined class_pred_set name),
              (* function-package pre-derivation combinator: humans cite f.simps,
                 never f_sumC.  The f_graph sibling is generated in the same
                 batch, so its existence makes a hand-written *_sumC name
                 structurally impossible to misjudge. *)
              ("sumC_graph",      fn () => String.isSuffix "_sumC" (Long_Name.base_name name)
                                           andalso is_declared_const
                                             (String.substring (name, 0, size name - 5) ^ "_graph")),
              (* Quickcheck's per-type random generators, defined via the
                 function package inside library theories — same _graph
                 existence guard as sumC_graph *)
              ("random_aux_graph", fn () => String.isPrefix "random_aux_" (Long_Name.base_name name)
                                            andalso is_declared_const (name ^ "_graph")),
              (* Quickcheck's valtermify_/valterm_ helpers: their declared type
                 mentions the reflection type Code_Evaluation.term, which a
                 mathematical constant's type never does *)
              ("valtermify_term", fn () =>
                 (String.isPrefix "valtermify_" (Long_Name.base_name name)
                  orelse String.isPrefix "valterm_" (Long_Name.base_name name))
                 andalso (case try (Consts.the_constraint consts) name of
                            SOME T => Term.exists_subtype
                                        (fn Type (\<^type_name>\<open>Code_Evaluation.term\<close>, _) => true
                                          | _ => false) T
                          | NONE => false))]
              val _ = Strhashtab.update infra_const_cache (name, result)
          in result end
    fun is_infra_const' name typ_opt = is_some (infra_const_rule name typ_opt)
    fun is_infra_const name = is_infra_const' name NONE

    (* --- ADT infrastructure theorem names --- *)

    fun is_ADT_infra_thm full_name =
      String.isSuffix "_def" full_name
      andalso exists (fn pfx => String.isPrefix pfx full_name) type_name_prefixes

    (* --- Inductive infrastructure theorem names --- *)

    val ctxt = Context.proof_of context
    (* Check if name or its predicate form (name ^ "p") is inductive.
       inductive_set registers the inductive info under the predicate form
       (e.g. "listsp"), not the set form ("lists").
       the_inductive_global stores locale names (e.g. "ccpo.iteratesp") but
       fact names use class names (e.g. "ccpo_class.iteratesp").
       We strip "_class" from qualifier segments to recover the locale name. *)
    val is_inductive = can (Inductive.the_inductive_global ctxt)
    fun declass name =
      let val segs = Long_Name.explode name
      in case segs of
           [] => NONE
         | _ => let val segs' = map (fn s =>
                      if String.isSuffix "_class" s
                      then String.substring (s, 0, size s - 6)
                      else s) segs
                    val name' = Long_Name.implode segs'
                in if name' = name then NONE else SOME name' end
      end
    fun check_inductive name =
      is_inductive name orelse is_inductive (name ^ "p")
      orelse (String.isSubstring "_class." name
              andalso case declass name of
                SOME name' => is_inductive name' orelse is_inductive (name' ^ "p")
              | NONE => false)

    fun is_inductive_infra_thm full_name =
      let val base = Long_Name.base_name full_name
      in
        if String.isSuffix "_def" base
        then check_inductive
               (String.substring (full_name, 0, size full_name - 4))
        else if base = "cong"
        then check_inductive (Long_Name.qualifier full_name)
        else false
      end

    (* --- Proposition content check --- *)

    fun is_internal_class (Const(name1, _) $ Const(\<^const_name>\<open>Pure.type\<close>, _)) =
          String.isSuffix "_class" name1
      | is_internal_class (Const(\<^const_name>\<open>Pure.eq\<close>, _) $ A $ B) =
          is_internal_class A orelse is_internal_class B
      | is_internal_class (Const(\<^const_name>\<open>Pure.imp\<close>, _) $ _ $ X) = is_internal_class X
      | is_internal_class (Const(\<^const_name>\<open>Pure.conjunction\<close>, _) $ A $ B) =
          is_internal_class A orelse is_internal_class B
      | is_internal_class _ = false
    fun is_internal_constant (name, T) = is_infra_const' name (SOME T)

    (* The first infrastructure constant a proposition mentions.  Term.exists_Const
       answers whether, not which, and the cascade bucket needs which. *)
    fun first_internal_const thm =
      Term.fold_aterms
        (fn Const c => (fn acc => if is_some acc then acc
                                  else if is_internal_constant c then SOME (fst c) else NONE)
          | _ => I)
        (Thm.prop_of thm) NONE

    fun infra_thm_rule (full_name, thm) =
      case first_rule
             [("declared",  fn () => decl_infra_thm thm),  (* matched by proposition *)
              ("concealed", fn () => Name_Space.is_concealed fact_space full_name),
              ("hidden",    fn () => is_hidden fact_space full_name),
              (* No accessible short name in this context (e.g. shadowed, or a
                 class-localized fact outside its locale): the agent cannot cite it
                 by name, so it is useless to surface. Facts.extern marks such
                 names with a "??." prefix (the exact string the agent would see). *)
              ("shadowed",  fn () => String.isPrefix "??." (Facts.extern ctxt facts full_name)),
              ("infra_theory",    fn () => is_from_infra_space fact_space full_name),
              ("adt_infra",       fn () => is_ADT_infra_thm full_name),
              ("inductive_infra", fn () => is_inductive_infra_thm full_name)] of
        SOME why => SOME why
      | NONE =>
          (case first_internal_const thm of
             SOME c => SOME ("const:" ^ c)
           | NONE =>
               first_rule
                 [("internal_class", fn () => is_internal_class (Thm.prop_of thm)),
                  ("too_big", fn () => smart_size_of_term (Thm.prop_of thm) > 1000)])
    fun is_infra_thm x = is_some (infra_thm_rule x)

    (* Stricter than is_infra_thm: also rejects induction rules from theory
       prefixes that emit too-generic auto-generated rules (e.g. Basic_BNFs's
       fsts.inducts / snds.inducts). *)
    val infra_induct_thy_prefixes = ["Basic_BNFs."]
    fun is_infra_induct_thm (full_name, thm) =
        is_infra_thm (full_name, thm)
        orelse exists (fn p => String.isPrefix p full_name) infra_induct_thy_prefixes

    (* --- Methods: drop any method defined in a Main-ancestor theory --- *)
    val main_anc_set =
      let val thy = Context.theory_of context
          val ancs = Theory.ancestors_of thy
      in case find_first (fn t => Context.theory_base_name t = "Main") ancs of
           SOME m => Symtab.make_set (map Context.theory_long_name (m :: Theory.ancestors_of m))
         (* current theory is Main or below it: filter everything inherited *)
         | NONE => Symtab.make_set (map Context.theory_long_name (thy :: ancs))
      end
    val method_space = Method.method_space context
    (* Same concealed/hidden/shadowed guards as is_infra_dynamic_fact:
       a method the agent cannot cite by name is useless to surface, and an
       inaccessible name crashes Universal_Key.key_of_method (intern yields the
       "??."-hidden form, the_entry then fails with "Inaccessible method"). *)
    fun is_infra_method name =
      (case try (Name_Space.the_entry method_space) name of
         SOME e => Symtab.defined main_anc_set (#theory_long_name e)
       | NONE => true)
      orelse Name_Space.is_concealed method_space name
      orelse is_hidden method_space name
      orelse String.isPrefix "??." (Name_Space.extern ctxt method_space name)

    (* --- Theorem collections (dynamic facts): tool-internal blacklist --- *)
    (* A theorem collection is any dynamic fact (named_theorems or raw
       add_thms_dynamic).  The blacklist keys by fact name; it covers known
       tool-internal collections regardless of which kind they are, so it can be
       extended with non-named_theorems names as needed. *)
    val dynamic_fact_blacklist = Symtab.make_set [
        "HOL.no_atp", "HOL.atomize_elim",
        "HOL.nitpick_simp", "HOL.nitpick_psimp", "HOL.nitpick_unfold", "HOL.nitpick_choice_spec",
        "HOL.code_pred_def", "HOL.code_pred_inline", "HOL.code_pred_simp",
        "SMT.smt_arith_combine", "SMT.smt_arith_multiplication", "SMT.smt_arith_simplify",
        "Quotient.quot_equiv", "Quotient.quot_preserve", "Quotient.quot_respect",
        "Quotient.quot_thm", "Quotient.id_simps",
        "Lifting.relator_eq_onp",
        "Fun_Def.measure_function", "Fun_Def_Base.termination_simp",
        "Partial_Function.partial_function_mono"]
    (* Theory prefixes whose dynamic facts are all tool-internal (Transfer/Lifting
       relators, SMT proof rules, Pure method_facts).  None of these four packages
       emits a dynamic collection worth retrieving, so filter the whole prefix
       rather than maintaining a per-name list.  NB: this is local to the
       dynamic-fact filter, NOT the shared is_from_infra_theory (which also gates
       constants/types/classes/locales). *)
    val infra_dynamic_thy_prefixes = ["Transfer.", "Lifting.", "SMT.", "Pure."]
    (* Codatatype packages auto-generate, per codatatype, coinduction-upto
       congruence collections (<codatatype>.cong_* and <codatatype>.coinduct_upto)
       as raw dynamic facts.  These are machinery, not user-facing rule sets, and
       recur for every codatatype, so match them structurally on the base name. *)
    fun is_codatatype_cong name =
      let val base = Long_Name.base_name name
      in String.isPrefix "cong_" base orelse base = "coinduct_upto" end
    (* Beyond the blacklist/prefixes, drop collections the agent cannot cite by
       name, mirroring the is_infra_thm checks above: concealed/private-scope
       entries (e.g. Eisbach `method ... uses` parameter slots, declared concealed
       in a private scope) and shadowed names ("??." extern).  Such names also
       crash Universal_Key.key_of_theorem_collection: Name_Space.intern yields the
       "??."-hidden form and Name_Space.the_entry then fails with
       "Inaccessible fact". *)
    fun is_infra_dynamic_fact name =
      Symtab.defined dynamic_fact_blacklist name
      orelse exists (fn pfx => String.isPrefix pfx name) infra_dynamic_thy_prefixes
      orelse is_codatatype_cong name
      orelse Name_Space.is_concealed fact_space name
      orelse is_hidden fact_space name
      orelse String.isPrefix "??." (Facts.extern ctxt facts name)

    (* Exactly the decl-driven drops `is_infra_thm` adds — thm membership (by proposition)
       + const-mention cascade — and nothing else.  Used by the caller
       (make_entity_callbacks) to drop declared-infra entries from the persistent thm/rule
       caches, which the live KNN CACHED pass does not re-filter.  (The name arg is unused
       now that membership is by proposition; kept for the caller's signature.) *)
    fun is_declared_infra_thm (_, thm) =
      decl_infra_thm thm
      orelse (not (Symtab.is_empty decl_consts)
              andalso Term.exists_Const
                        (fn (n,_) => Symtab.defined decl_consts n) (Thm.prop_of thm))
  in
    {is_infra_const = is_infra_const, is_infra_thm = is_infra_thm,
     is_infra_induct_thm = is_infra_induct_thm,
     is_infra_type = fn name => Symtab.defined decl_types name
                                orelse Name_Space.is_concealed type_space name
                                orelse is_hidden type_space name
                                orelse is_from_infra_space type_space name,
     is_infra_class = fn name => Name_Space.is_concealed class_space name
                                 orelse is_hidden class_space name
                                 orelse is_from_infra_space class_space name,
     is_infra_locale = fn name => Name_Space.is_concealed locale_space name
                                  orelse is_hidden locale_space name
                                  orelse is_from_infra_space locale_space name,
     is_infra_dynamic_fact = is_infra_dynamic_fact,
     is_infra_method = is_infra_method,
     is_declared_infra_thm = is_declared_infra_thm,
     infra_const_rule = infra_const_rule,
     infra_thm_rule = infra_thm_rule,
     has_infra_decls = has_infra_decls}
  end

end
