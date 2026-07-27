(*  Title:      Tools/semantic_digest.ML
    Author:     Qiyuan Xu

Semantic digests and dependency extraction for the incremental invalidation of
semantic interpretations.  See CHECK_OUTDATE_PLAN.md (repository root) for the
full design, and doc/invalidation_limitations.md for the known coverage gaps.

THIS FILE IMPLEMENTS THE ML SIDE ONLY.  For one entity of the interpretation
pipeline's own enumeration (semantic_store.ML's enumerate_entries), it computes:

  * the SEMANTIC DIGEST -- only for the four WIP name-addressed kinds
    (constant, type, class, locale), whose universal keys do not move when
    their content changes and so need an explicit change signal;
  * the DEPENDENCY EDGES -- for those four kinds AND for theorem-alike
    entities.  A theorem's key already carries a content digest (thm128), so
    the key itself is its change signal, but its interpretation still goes
    stale when a constant it mentions changes meaning; the edges are what let
    the Python side track that.

Comparing against stored state, bumping versions, effective-version (eff)
evaluation and the todo-set filter all happen Python-side
(semantic_interpretation.py).

Dependency targets with no record in the store (infrastructure constants and
the like) contribute effective version 0 Python-side -- an explicit design
decision (CHECK_OUTDATE_PLAN.md §4.4): the mechanism detects when an ENGLISH
INTERPRETATION may be stale, it does not compute a logical closure; the
accepted-gap register is doc/invalidation_limitations.md #1/#2.
*)

signature SEMANTIC_DIGEST =
sig
  (* Per-pass precomputed state: the indexed axiom table and the locale-parent
     index.  Building these per entity would be quadratic. *)
  type env
  val make_env: theory -> env
  val theory_of_env: env -> theory

  (* A dependency edge target: its kind and fully-qualified name.  Only
     constants, types, classes and locales can ever be depended upon --
     theorems and the rule kinds are always leaves (a theorem's dependencies
     come from its statement, and statements mention constants and types,
     never other theorems). *)
  type dep = Universal_Key.entity_kind * string

  (* Alpha-canonical form: type variables, schematic variables and free
     variables renamed by first occurrence, Abs binder names erased. *)
  val normalize: term -> term

  (* The constants, type constructors and sort classes a term mentions. *)
  val deps_of_term: term -> dep list

  (* Digest and dependencies of one pipeline entity:
       SOME (SOME digest, deps) -- the four WIP name-addressed kinds;
       SOME (NONE, deps)        -- theorem-alike (key self-invalidates, so no
                                   digest; the edges still feed eff);
       NONE                     -- methods and collections (never expire,
                                   CHECK_OUTDATE_PLAN.md §2) and names that
                                   do not resolve. *)
  val semantics_of: env -> Universal_Key.entity -> (Term_Digest.digest128 option * dep list) option

  (* The defining axioms retained for a constant after the own-theory filter,
     exposed for the sensitivity suite. *)
  val own_defining_axioms: env -> string -> (string * term) list
end;

structure Semantic_Digest: SEMANTIC_DIGEST =
struct

(* --- per-pass environment --- *)

(* Theory.all_axioms_of is a 3,451-entry list on Main; looking a name up in it
   per constant would be O(#constants * #axioms).  Index it once. *)
type env =
 {thy: theory,
  axioms: term Symtab.table,
  (* locale long name -> its parent locales.  Locale.dependencies_of is NOT
     exported (only its implementation is visible at locale.ML:259); the
     signature offers dest_dependencies, which yields every {source, target}
     edge in one traversal, so index it once here rather than per locale.
     pretty_locale_deps would also do but pretty-prints every locale body. *)
  locale_parents: string list Symtab.table}

fun make_env thy : env =
 {thy = thy,
  axioms = Symtab.make_distinct (Theory.all_axioms_of thy),
  locale_parents =
    fold (fn {source, target, ...} => Symtab.cons_list (target, source))
      (Locale.dest_dependencies [] thy) Symtab.empty}

fun theory_of_env ({thy, ...}: env) = thy


(* --- alpha normalisation --- *)

type dep = Universal_Key.entity_kind * string

(* Term_Digest.hash_term hashes Abs binder names, TFree/TVar names and Var
   indices, so term128 is NOT alpha-invariant -- stated outright at
   Term_Digest.ML:224+.  For theorem KEYS that is deliberate and must stay.  For
   staleness detection it is a false-positive source: renaming a bound variable
   would make an entity look changed and buy a needless LLM re-interpretation.

   So canonicalise the term first and hash the result with the existing hasher.
   Do NOT touch thm128 itself -- redefining it would move all 95,338 theorem
   keys in the store.

   Renaming is by first occurrence, threading one counter through types and
   terms alike.  Sharing one counter between the two makes the numbering
   interleave, which is harmless: all that matters is that the same input always
   yields the same output. *)

type norm_st = int Symtab.table * int

fun canon (tab, next) key =
  case Symtab.lookup tab key of
    SOME i => (i, (tab, next))
  | NONE => (next, (Symtab.update (key, next) tab, next + 1))

fun norm_typ (Type (n, Ts)) st =
      let val (Ts', st') = fold_map norm_typ Ts st
      in (Type (n, Ts'), st') end
  | norm_typ (TFree (a, S)) st =
      let val (i, st') = canon st ("tf " ^ a)
      in (TFree ("'z" ^ string_of_int i, S), st') end
  | norm_typ (TVar ((a, j), S)) st =
      let val (i, st') = canon st ("tv " ^ a ^ " " ^ string_of_int j)
      in (TVar (("'z" ^ string_of_int i, 0), S), st') end

fun norm_term (Const (n, T)) st =
      let val (T', st') = norm_typ T st in (Const (n, T'), st') end
  | norm_term (Free (a, T)) st =
      let
        val (T', st') = norm_typ T st
        val (i, st'') = canon st' ("f " ^ a)
      in (Free ("z" ^ string_of_int i, T'), st'') end
  | norm_term (Var ((a, j), T)) st =
      let
        val (T', st') = norm_typ T st
        val (i, st'') = canon st' ("v " ^ a ^ " " ^ string_of_int j)
      in (Var (("z" ^ string_of_int i, 0), T'), st'') end
  | norm_term (Bound i) st = (Bound i, st)
  | norm_term (Abs (_, T, body)) st =
      (* binder name erased: it is cosmetic, de Bruijn indices carry the binding *)
      let
        val (T', st') = norm_typ T st
        val (body', st'') = norm_term body st'
      in (Abs ("", T', body'), st'') end
  | norm_term (t1 $ t2) st =
      let
        val (t1', st') = norm_term t1 st
        val (t2', st'') = norm_term t2 st'
      in (t1' $ t2', st'') end

fun normalize t = #1 (norm_term t (Symtab.empty, 0))

fun digest_term t = Term_Digest.term128 (normalize t)


(* --- dependency extraction --- *)

(* fold_atyps does NOT visit a Type node that has arguments (it recurses into
   the arguments instead), so collecting type-constructor names needs its own
   traversal. *)
fun add_tycos (Type (n, Ts)) = insert (op =) n #> fold add_tycos Ts
  | add_tycos _ = I

(* The digest payloads below are built out of synthetic Const/typ nodes (tag
   markers, type carriers, list terminators, dummyT).  Those are encoding
   scaffolding, not real entities: left in, they would produce dependency edges
   pointing at names no entity ever has.

   NEVER CHANGE THIS PREFIX ONCE DIGESTS ARE PERSISTED.  It is hashed into
   every payload through the tag constants below, so a rename re-digests the
   entire store: every WIP name-addressed entity would look changed and be
   re-interpreted at LLM cost.  The name was fixed (from the pre-deployment
   working name "Invalidation.") when the file became semantic_digest.ML,
   while no digest had ever been written to disk. *)
val synthetic_prefix = "Semantic_Digest."

fun is_synthetic_const n = String.isPrefix synthetic_prefix n
fun is_synthetic_type n = n = "dummy"

(* Every scaffolding node MUST be built here, so that the invariant above holds
   by construction rather than by luck.  It previously held only because the
   call sites that used raw Consts -- `Const (Bool.toString syn, dummyT)` for an
   abbreviation's syntactic flag, `Const (string_of_int ar, dummyT)` for an
   arity -- happened to compute their dependencies from a sub-payload that
   excluded them.  Those nodes carry no prefix, so is_synthetic_const cannot see
   them, and the obvious tidy-up (deriving deps from the whole payload) would
   have silently produced edges to constants named "true" and "0". *)

(* Kind tag: two entity kinds can never collide on an identical payload. *)
fun tagged tag t = Const (synthetic_prefix ^ "kind." ^ tag, dummyT) $ t

(* List terminator. *)
val nil_payload = Const (synthetic_prefix ^ "nil", dummyT)

(* Carries a type into the term language, so that one alpha normaliser and one
   hasher serve both. *)
fun typ_payload T = Const (synthetic_prefix ^ "typ", T)

(* A non-term scalar (a flag, an arity) that must nevertheless reach the digest. *)
fun lit s = Const (synthetic_prefix ^ "lit." ^ s, dummyT)

(* Sort constraints are dependencies too, and they are easy to lose: fold_atyps
   would visit the TFree/TVar but its sort rides along in the second component,
   so only fold_atyps_sorts sees it.

   Without this, `not_less :: 'a::linorder => _` yields edges to less/less_eq but
   NONE to class linorder, and adding an axiom to linorder invalidates nothing:
   Term_Digest.hash_typ hashes only the class NAME inside the sort
   (Term_Digest.ML:92-96), which an added axiom does not change. *)
fun add_sort_classes T = fold_atyps_sorts (fn (_, S) => fold (insert (op =)) S) T

fun add_consts t = fold_aterms (fn Const (n, _) => insert (op =) n | _ => I) t

(* Dependency lists are unordered sets: every caller merges them with `unions`,
   and they never enter a payload, so no sorting is needed to make the digest
   deterministic.  (Payload content IS sorted where its order is not semantic --
   see sem_class.) *)
fun deps_of_term t =
  let
    val consts = add_consts t []
    val tycos = fold_types add_tycos t []
    val classes = fold_types add_sort_classes t []
  in
    map (pair Universal_Key.ConstantK) (filter_out is_synthetic_const consts) @
    map (pair Universal_Key.TypeK) (filter_out is_synthetic_type tycos) @
    map (pair Universal_Key.ClassK) classes
  end

(* Each kind draws its dependencies from several sources; merging them pairwise
   nested one source per review round to four levels deep. *)
fun unions xss = fold (union (op =)) xss []


(* --- the own-theory filter --- *)

(* Defs.specifications_of returns EVERY defining axiom of a constant, including
   one per type-class instance -- measured: Groups.plus_class.plus yields nine,
   living in Nat, Num, Int, Enum, Code_Numeral and String, all DESCENDANTS of
   Groups where the constant itself is declared.

   Admitting those would be wrong twice over: the digest of an entity in Groups
   would move whenever String.thy changed (mass false invalidation), and the
   dependency edge would point forward in the topological order that the sweep
   relies on.

   The plan phrases the filter as "axiom's theory subsumed by the constant's
   theory", but subsumption is over-general: a defining axiom can never sit in
   an ANCESTOR of the theory declaring the constant, since a definition may only
   follow the declaration.  Subsumption therefore collapses to EQUALITY, which
   is both simpler and exactly right. *)

fun theory_of_name space name =
  try (fn () => #theory_long_name (Name_Space.the_entry space name)) ()

(* Fall-back when a name is absent from its space -- measured: Fun.id_def_raw is
   in neither the fact space nor get_thm's reach.  Compare the leading name
   component, the same approximation Universal_Key.theory_short_of uses
   (Universal_Key.ML:464-467): "Fun.id_def_raw" and "Fun.id" agree on "Fun",
   while "Nat.plus_nat_def" and "Groups.plus_class.plus" do not.

   Do NOT "keep when the theory is unknown" instead.  It looks safer -- losing a
   definition is worse than admitting one -- but measured, the instance defs
   Nat.plus_nat_inst.plus_nat_def and String.plus_literal_inst.plus_literal_def
   are BOTH absent from the fact space, so keeping-when-unknown would hand
   plus back all nine of its downstream instance definitions.  They are excluded
   today precisely by this leading-component comparison.

   Known cost, 2 constants of Main's 2,191 (0.09%):
   typerep_itself_inst.typerep_itself and term_of_itself_inst.term_of_itself
   lose their definition content, because their `_raw` axioms carry no qualifier
   at all ("typerep_itself_def_raw") and so cannot match the constant's leading
   component ("typerep_itself_inst").  Both are internal code-generation
   constants; not worth extra machinery. *)
fun leading_component name =
  case Long_Name.explode name of [] => name | c :: _ => c

fun same_theory (env: env) {const_name, axiom_name} =
  let val thy = #thy env in
    case (theory_of_name (Consts.space_of (Sign.consts_of thy)) const_name,
          theory_of_name (Facts.space_of (Global_Theory.facts_of thy)) axiom_name) of
      (SOME a, SOME b) => a = b
    | _ => leading_component const_name = leading_component axiom_name
  end

(* Two resolution paths, both needed: get_thm reaches List.rev_def (concealed
   but present), while Fun.id_def_raw is reachable only through the axiom
   table. *)
fun resolve_prop (env: env) name =
  case try (Global_Theory.get_thm (#thy env)) name of
    SOME th => SOME (Thm.prop_of th)
  | NONE => Symtab.lookup (#axioms env) name

(* The same-theory filter is necessary but NOT sufficient, and the gap is the
   expensive kind.  Measured: Orderings.ord_class.less_eq has 16 defining
   axioms; the filter drops 14 cross-theory ones but keeps
   ord_bool_inst.less_eq_bool_def and ord_fun_inst.less_eq_fun_def, because the
   bool and fun instances happen to be declared in Orderings.thy itself, right
   beside the class parameter.

   Keeping them would make less_eq's digest move whenever anyone edited the bool
   instance -- and less_eq is mentioned by 13.3% of all theorems, so a cosmetic
   change to a bool instance would invalidate an eighth of the library, nearly
   all of it lemmas about nat/int/real that the bool instance cannot affect.

   The principled rule is not about theories at all: a type-class PARAMETER has
   no definition of its own in the first place.  Its instances are separate
   entities that belong to their own types.  So: if the constant is a class
   parameter, it keeps no defining axioms, wherever they were declared. *)
fun class_param_of (env: env) const_name =
  Axclass.class_of_param (#thy env) const_name

(* Defs knows nothing about `axiomatization`: Specification.gen_axioms goes
   through Thm.add_axiom_global and never touches it, so an axiomatized constant
   has a spec (the declaration marker) whose #def is NONE.  Measured:
   Set.member and Set.Collect both report specs=1 with #def=0, leaving their
   digest as name+type only -- yet mem_Collect_eq IS their entire meaning.

   Spec_Rules records those axioms (Set.member -> Set.Collect_member, giving
   `(?a : Collect ?P) = ?P ?a`).  It carries EXACTLY the same downstream
   contamination as Defs, though -- measured, retrieve_global returns 5 rules
   for Groups.plus_class.plus and 12 for Orderings.ord_class.less_eq, every one
   of them from Enum/Num/Predicate downstream -- so it gets the same
   same-theory filter.  In practice the class-parameter rule already excludes
   those two, but a non-parameter constant whose Defs axioms are all foreign
   would otherwise fall through to here and pick the foreign rules back up. *)
(* Scan get_global rather than calling retrieve_global.  Spec_Rules stores its
   items in an Item_Net, and Item_Net.cons indexes an item under `index x` --
   for spec rules, the declared TERMS (item_net.ML:63-65).  A command that
   declares constants without stating anything, or states axioms without
   declaring, produces an item whose index is empty; such an item lands in
   `content` but never in the net, and retrieve_generic is
   `Item_Net.retrieve (Data.get context)`, which consults only the net
   (spec_rules.ML:150-151).  So retrieve_global cannot see it.

   That is not hypothetical: HOL.thy:92-94 declares implies, eq and The bare,
   with their axioms following at :219/:229, leaving all three with a name+type
   digest.  Set.member escaped only because Set.thy:17-20 happens to put the
   declaration and its `where` in one command -- any user theory that separates
   them reopens the hole.  get_global reads `content` (spec_rules.ML:137,143)
   and so sees every item. *)
fun spec_rule_axioms (env: env) const_name =
  let
    (* NB not "head" constants: every constant the item mentions counts. *)
    fun mentions_const ({terms, rules, ...} : Spec_Rules.spec_rule) =
      member (op =) (unions (map (fn t => add_consts t []) terms)) const_name orelse
      member (op =) (unions (map (fn th => add_consts (Thm.prop_of th) []) rules)) const_name
  in
    Spec_Rules.get_global (#thy env)
    |> filter mentions_const
    |> filter (fn {name, ...} =>
         same_theory env {const_name = const_name, axiom_name = name})
    |> maps (fn {name, rules, ...} => map (fn th => (name, Thm.prop_of th)) rules)
    |> sort (fn ((a, s), (b, t)) =>
         (case string_ord (a, b) of EQUAL => Term_Ord.term_ord (s, t) | ord => ord))
  end

fun own_defining_axioms (env: env) const_name =
  if is_some (class_param_of env const_name) then []
  else
    let
      val from_defs =
        Defs.specifications_of (Theory.defs_of (#thy env)) (Defs.Const, const_name)
        |> map_filter #def
        |> filter (fn ax => same_theory env {const_name = const_name, axiom_name = ax})
        |> map_filter (fn ax => Option.map (pair ax) (resolve_prop env ax))
        |> sort (fn ((a, _), (b, _)) => string_ord (a, b))
    in
      if null from_defs then spec_rule_axioms env const_name else from_defs
    end


(* --- per-kind semantics --- *)

(* A constant's semantics is its declared type together with its OWN defining
   axioms (see the filter above).  The type alone is not enough: changing the
   body of rev leaves its type 'a list => 'a list untouched, so a type-only
   digest would miss the change entirely -- which is exactly what the existing
   `expr` field does for constants (semantic_store.ML's mk_prop_str).

   A constant with no own defining axiom digests to just its name and type.
   That is the correct answer for a type-class parameter such as
   Groups.plus_class.plus, which is declared but never defined in Groups. *)
fun sem_constant (env: env) name =
  case try (Consts.the_constraint (Sign.consts_of (#thy env))) name of
    NONE => NONE
  | SOME T =>
      let
        val axioms = own_defining_axioms env name
        val props = map snd axioms
        (* A class parameter carries no definition, but the class it
           parameterises IS part of what it means: if that class's axioms
           change, so does the parameter's reading.  Record the class both in
           the payload and as a dependency edge. *)
        val cls = class_param_of env name
        val cls_payload =
          case cls of
            NONE => nil_payload
          | SOME c => tagged "param_of" (Const (c, dummyT))
        (* An `abbreviation` writes nothing to Defs (Sign.add_abbrev bypasses it)
           and is not a class parameter, so both sources above come back empty
           and the payload would collapse to name+type -- rewriting the
           abbreviation's body would be invisible.  Measured on Main: 205 of the
           1,122 interpretable constants (18%) are abbreviations, e.g. Set.range,
           Set.union, HOL.not_equal. *)
        val abbrev =
          if null axioms then try (Consts.the_abbreviation (Sign.consts_of (#thy env))) name
          else NONE
        val abbrev_payload =
          case abbrev of
            NONE => nil_payload
          | SOME (_, rhs) => tagged "abbrev" rhs
        val payload =
          fold (fn p => fn acc => tagged "def" p $ acc) props
            (tagged "const" (Const (name, T)) $ cls_payload $ abbrev_payload)
        val cls_dep =
          case cls of NONE => [] | SOME c => [(Universal_Key.ClassK, c)]
        val abbrev_deps =
          case abbrev of NONE => [] | SOME (_, rhs) => deps_of_term rhs
      in
        SOME (digest_term payload,
              unions (cls_dep :: abbrev_deps :: deps_of_term (Const (name, T))
                      :: map deps_of_term props))
      end

(* A type's content comes from whichever of three channels declares it; they are
   mutually exclusive and tried in order.  Measured on Main:
     String.string -> Abbreviation, body "char list"
     List.list     -> ctr_sugar, ctrs [[], (#)], case case_list
     Int.int       -> typedef, rep (nat * nat) set
     Nat.nat       -> ctr_sugar [0, Suc] (and also a typedef over ind)
   NB the constructor is Logical_Type, not LogicalType, and Type.the_decl raises
   for an undeclared name (Fun.fun), hence the `try`. *)
fun sem_type (env: env) name =
  let
    val thy = #thy env
    val tsig = Sign.tsig_of thy
    fun from_decl () =
      case try (Type.the_decl tsig) (name, Position.none) of
        (* The parameter list must go through the SAME alpha canonicalisation as
           the body, or the two halves desynchronise and produce a matched pair
           of errors.  Encoding a parameter as `Const (v, dummyT)` leaves its
           name untouched by normalize (which rewrites types, not Const names)
           while the body's TFrees are renumbered, so:
             'a env = "'a list"  vs  'b env = "'b list"  ->  digests DIFFER
                 (false positive: a pure renaming forces a re-interpretation)
             ('a,'b) f = "'a => 'b"  vs  "'b => 'a"      ->  digests AGREE
                 (false negative: permuting the parameters is invisible)
           Carrying each parameter as a TFree instead puts it through canon, and
           because the fold places the parameters ahead of the body they claim
           the low numbers -- so the body's occurrences are numbered RELATIVE to
           the declared parameter order, which is exactly what distinguishes
           'a => 'b from 'b => 'a. *)
        SOME (Type.Abbreviation (vs, body, syn)) =>
          SOME (tagged "abbrev"
                  (fold (fn v => fn acc => typ_payload (TFree (v, [])) $ acc) vs
                     (typ_payload body $ lit (Bool.toString syn))),
                deps_of_term (typ_payload body))
      | SOME Type.Nonterminal => SOME (tagged "nonterm" nil_payload, [])
      | SOME (Type.Logical_Type ar) => from_ctrs ar
      | NONE => NONE
    (* REGRESSION: the three channels are NOT mutually exclusive -- Nat.nat
       answers on both (ctrs [0, Suc] AND a typedef over ind).  Short-circuiting
       on ctr_sugar dropped the representing set, so rewriting the
       representation predicate of a hand-written `typedef` that also carries
       `free_constructors` left the digest bit-identical.  Combine instead.

       Constructors are NOT sorted: their declaration order is semantic (it
       drives the case equations and the derived orders), so `datatype d = A | B`
       must digest differently from `B | A`.  ctr_sugar is theory data recorded
       at declaration, so the order is already deterministic and needs no sort
       to make it so. *)
    and from_ctrs ar =
      case try (Ctr_Sugar.ctr_sugar_of_global thy) name of
        SOME (SOME {ctrs, casex, ...}) =>
          let
            val ctr_payload = fold (fn c => fn acc => c $ acc) ctrs casex
            val ctr_deps = unions (map deps_of_term (casex :: ctrs))
          in
            case from_typedef ar of
              SOME (td_payload, td_deps) =>
                SOME (tagged "data" (ctr_payload $ td_payload), union (op =) ctr_deps td_deps)
            | NONE => SOME (tagged "data" ctr_payload, ctr_deps)
          end
      | _ => from_typedef ar
    and from_typedef ar =
      (* get_info_global yields a PAIR of records per entry; the first carries
         the type data, the second the derived theorems. *)
      (* REGRESSION: the SECOND record of the pair carries
         `type_definition Rep Abs A`, and A is the defining set -- the whole
         content of the typedef.  Without it, rep_type/abs_type/Rep_name/Abs_name
         are all unchanged when A is rewritten, so
         `typedef t = "{x::nat. x < 10}"` and `"{x::nat. x > 10}"` digest
         identically and never invalidate. *)
      case try (Typedef.get_info_global thy) name of
        SOME (({rep_type, abs_type, Rep_name, Abs_name, ...},
               {type_definition, ...}) :: _) =>
          let
            val td = Thm.prop_of type_definition
            val payload =
              tagged "typedef"
                (typ_payload rep_type $ typ_payload abs_type $
                 Const (Rep_name, dummyT) $ Const (Abs_name, dummyT) $
                 tagged "set" td)
          in SOME (payload,
                   unions [deps_of_term td, deps_of_term (typ_payload rep_type),
                           deps_of_term (typ_payload abs_type)])
          end
      | _ => SOME (tagged "logical" (lit (string_of_int ar)), [])
  in
    case from_decl () of
      NONE => NONE
    | SOME (payload, deps) =>
        SOME (digest_term (tagged "type" (Const (name, dummyT) $ payload)),
              deps)
  end

(* A class's content is the `def` theorem plus its axioms.  Measured:
     Orderings.order -> def: OFCLASS(?'a, order_class)
                             == (OFCLASS(?'a, preorder_class) &&& class.order_axioms (<=))
   so `def` alone already encodes the superclass structure AND the axioms, as of
   the moment of declaration.

   That is what makes the digest immune to the downstream-contamination problem:
   Sign.super_classes returns the TRANSITIVE closure, and a `subclass A < B`
   proved in a downstream theory grows it -- but it does not rewrite the class's
   own `def`, so the digest cannot move.  No filter needed.

   Superclasses still enter the DEPENDENCIES, transitively and unfiltered; a
   downstream-added one yields an edge pointing forward, which the Python-side
   evaluation tolerates (an over-approximation costing nothing).

   HOL.type has no axclass info (measured NONE) -- digest degrades to the name. *)
fun sem_class (env: env) name =
  let
    val thy = #thy env
    (* TRANSITIVE closure, and it GROWS when a downstream theory proves a new
       `subclass` relation -- Rings.thy declares class idom, and
       Semiring_Normalization.thy later widens it with `subclass (in idom) ...`.

       So supers must stay OUT of the payload.  Putting them in makes the digest
       a function of how far the enclosing env reaches: the same class hashes
       differently under make_env "HOL.Rings" and make_env "Main", and two
       scan runs from different top theories would each undo the other's
       refresh.  `def` already encodes the superclass structure AS DECLARED
       (frozen by Axclass.define_class), which is the stable thing.

       They do belong in the DEPENDENCIES. *)
    val supers = sort_strings (Sign.super_classes thy name)
    val super_deps = map (pair Universal_Key.ClassK) supers
  in
    case try (Axclass.get_info thy) name of
      SOME {def, axioms, params, ...} =>
        let
          val props = sort Term_Ord.term_ord (map Thm.prop_of axioms)
          (* Axclass.define_class builds `def` from `of_sort super @ axioms`
             only (axclass.ML:393-395), so the parameters never appear in it.
             For a class that states no axioms the parameters ARE the content:
             Orderings.ord has naxioms=0 and def
             `OFCLASS(?'a, ord_class) == OFCLASS(?'a, type_class)`, so without
             them, adding or retyping a parameter changes nothing. *)
          val param_payload =
            fold (fn (n, T) => fn acc => Const (n, T) $ acc) params nil_payload
          val param_deps =
            unions (map (fn (n, T) => deps_of_term (Const (n, T))) params)
          val payload =
            tagged "class"
              (Const (name, dummyT) $ param_payload $
               fold (fn p => fn acc => tagged "ax" p $ acc) props
                 (tagged "def" (Thm.prop_of def)))
        in
          SOME (digest_term payload,
                unions (super_deps :: param_deps
                        :: map deps_of_term (Thm.prop_of def :: props)))
        end
    | NONE =>
        SOME (digest_term (tagged "class" (Const (name, dummyT))), super_deps)
  end

(* Locale content: its parameters (name and type, in DECLARATION order, which is
   semantic here and so is not sorted) plus its axioms.
   NB Locale.params_of returns ((string * typ) * mixfix) list -- the parameter
   name is a plain string, not a binding. *)
fun sem_locale (env: env) name =
  let
    val thy = #thy env
    val params = Locale.params_of thy name
    (* Locale.axioms_of is NOT the `assumes`.  Pure keeps only b_axioms in the
       locale record, and expression.ML:762 sets b_axioms = [] whenever no
       import contributes an assertion predicate -- i.e. for every locale with
       no parent, and every class-generated locale whose parents assert nothing.
       Measured: Groups.semigroup, which literally states `assumes assoc`, has
       axioms_of = 0; Orderings.preorder likewise.  Digesting that list alone
       would leave `locale semigroup` unchanged when assoc becomes commutativity.

       hyp_spec_of returns the declared elements, from which the Assumes carry
       the real propositions. *)
    (* hyp_spec holds BOTH element kinds: Pure's own predicate is
       `is_hyp = fn Assumes _ => true | Defines _ => true | _ => false`
       (expression.ML:800).  Matching only Assumes silently drops every
       `locale ... defines ...`, and the axioms_of fall-back cannot recover them
       either -- eval_text passes a Defines through untouched
       (expression.ML:616), so the locale's axioms never contain the defining
       body.  Main declares no such locale; HOL-Algebra has roughly 33 (Sylow,
       UnivPoly, residues, ...). *)
    fun hyp_props () =
      Locale.hyp_spec_of thy name
      |> maps (fn Element.Assumes asms => maps (fn (_, ts) => maps (op ::) ts) asms
                | Element.Defines defs => map (fn (_, (t, _)) => t) defs
                | _ => [])
    val axiom_props =
      (case hyp_props () of
         [] => map Thm.prop_of (Locale.axioms_of thy name)
       | ts => ts)
    (* REGRESSION: parameters must be Free (not Const) and must be canonicalised
       BEFORE the propositions, where they also occur as Frees -- with Const the
       two halves fell out of step and `fixes f g assumes "f 0 = 0"` normalised
       identically to the same with `g`.  Same defect class as the abbreviation
       parameters in sem_type.  Free is additionally invisible to deps_of_term,
       which is wanted: a parameter is locale-local, not an entity to depend on.
       Its TYPE still contributes dependencies. *)
    val param_payload =
      fold (fn ((nm, T), _) => fn acc => Free (nm, T) $ acc) params nil_payload
    val payload =
      tagged "locale"
        (Const (name, dummyT) $ param_payload $
         fold (fn p => fn acc => tagged "ax" p $ acc) axiom_props nil_payload)
    val param_type_deps =
      unions (map (fn ((_, T), _) => deps_of_term (typ_payload T)) params)
    (* REGRESSION: parent locales are dependencies, exactly as superclasses are
       for a class -- ask for them explicitly rather than hoping a parent
       predicate shows up as a Const inside some proposition.  Locales with a
       predicate parent AND their own assumes (Groups.abel_semigroup,
       Groups.monoid, Orderings.ordering_top) otherwise get no path to it. *)
    val parent_deps =
      map (pair Universal_Key.LocaleK)
        (sort_strings (the_default [] (Symtab.lookup (#locale_parents env) name)))
  in
    SOME (digest_term payload,
          unions (parent_deps :: param_type_deps :: map deps_of_term axiom_props))
  end
  handle ERROR _ => NONE

(* Theorem-alike entities: no digest (thm128 in the key is the change signal),
   dependency edges from the statement.  The thm-valued constructors carry the
   theorem directly -- no name resolution, which is what lets dynamic-collection
   members (no name of their own) and multi-theorem facts through.  The Named_*
   variants resolve through Facts.lookup, the same lookup the query paths use. *)
fun thm_deps th = SOME (NONE, deps_of_term (Thm.prop_of th))

fun named_fact_deps (env: env) name =
  case Facts.lookup (Context.Theory (#thy env)) (Global_Theory.facts_of (#thy env)) name of
    NONE => NONE
  | SOME {thms, ...} =>
      SOME (NONE, unions (map (deps_of_term o Thm.prop_of) thms))

fun with_digest f env name =
  case f env name of
    NONE => NONE
  | SOME (d, deps) => SOME (SOME d, deps)

fun semantics_of env entity =
  case entity of
    Universal_Key.Constant n => with_digest sem_constant env n
  | Universal_Key.Type n => with_digest sem_type env n
  | Universal_Key.Class n => with_digest sem_class env n
  | Universal_Key.Locale n => with_digest sem_locale env n
  | Universal_Key.Theorem th => thm_deps th
  | Universal_Key.Introduction_Rule th => thm_deps th
  | Universal_Key.Elimination_Rule th => thm_deps th
  | Universal_Key.Induction_Rule th => thm_deps th
  | Universal_Key.Case_Split_Rule th => thm_deps th
  | Universal_Key.Named_Theorem n => named_fact_deps env n
  | Universal_Key.Named_Introduction_Rule n => named_fact_deps env n
  | Universal_Key.Named_Elimination_Rule n => named_fact_deps env n
  | Universal_Key.Named_Induction_Rule n => named_fact_deps env n
  | Universal_Key.Named_Case_Split_Rule n => named_fact_deps env n
  (* Collections and methods never expire (CHECK_OUTDATE_PLAN.md §2, locked
     decision: doc/invalidation_limitations.md #4/#5): no digest, no deps. *)
  | Universal_Key.Theorem_Collection _ => NONE
  | Universal_Key.Method _ => NONE

end;
