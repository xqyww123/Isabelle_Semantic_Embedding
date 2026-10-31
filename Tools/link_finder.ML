(*  Title:      Tools/link_finder.ML
    Author:     Qiyuan Xu

The link finder (ai-artifacts/LINK_LAYER_PLAN.md §4.1-§4.3): for every local
fact of a proof context, the template, i.e. the stored note that Locale.init
pushed through a morphism to produce the fact, and the instantiation of the
source locale S under which it did.

The walk lists the (source locale, qualifier chain, instance, root
registration) nodes the context can have activated.  A lookup by computed
full name, narrowed by the fact's name-space position, gives each fact its
candidates.  Levels 2 and 3 are decided by exact searches that replay
theorems one declaration at a time over the arcs the walk recorded, which
form an acyclic graph.  Stock Pure interfaces only.
*)

signature LINK_FINDER =
sig
  (*the template's global name, from a note's binding and first theorem: the
    theorem's name hint, else <defining theory>.<locale base name>.<note>*)
  val template_name: string -> binding -> thm -> string
  (*D36, the one look-up of a template's global fact, by its global name, never
    interned: a static fact that is accessible (neither concealed nor hidden,
    the enumeration's test), else NONE*)
  val template_global_fact: theory -> string -> thm list option
  (*the locales with a named note whose base name is in the set*)
  val candidate_locales: theory -> Symtab.set -> string list
  (*the images of a locale's parameters under a morphism, in Locale.params_of order*)
  val parameter_images: theory -> string -> morphism -> ((string * typ) * term) list
  (*a locale's named notes with theorems, in note order, replayed through a
    morphism with Morphism.fact: the binding, the template's global name, the
    images*)
  val replay_notes: theory -> string -> morphism ->
    {binding: binding, template_name: string, replayed: thm list} list

  datatype kind = Identity | Renaming | Proper
  (*D41: what the instantiation does to a parameter of S, decided on the terms
    alone; name is the parameter's, text the printed instance*)
  datatype verdict = Unchanged | Renamed | Instantiated
  type param = {verdict: verdict, name: string, text: string}
  (*§2: the kind of a link, a function of its verdicts*)
  val kind_of: verdict list -> kind
  (*D65: Level3_Exact carries the definitional equations, (definiens, folded),
    that its pre-check applied, in the table's order*)
  datatype level = Level2 | Level3_Exact of (term * term) list | Level3_Approximate
  (*the link of §2; source is empty for a lemma of an unnamed block; note is
    the note's name and the theorem's index (0 in a singleton note); params
    in Locale.params_of order; rewrites are the printed (template term,
    context term) of the level's equations; entities are the dictionary's
    (printed name, key); level is the ladder's, which the wire leaves out*)
  type link =
    {template: Universal_Key.universal_key,
     statement: string,
     source: string,
     note: string * int,
     params: param list,
     rewrites: (string * string) list,
     entities: (string * Universal_Key.universal_key) list,
     level: level}

  (*the retrieval closure's links, keyed as the closure keys its rows: every
    link of a key, in §4.2's order for shared keys (B6); the texts and keys from
    the context's linking cache*)
  val links: Proof.context -> (Universal_Key.universal_key * link) list
  (*the test hook (§8 step 4): the texts the linking caches have printed, the
    propositions they have keyed, and the entries of either table calls have found
    unfinished, each then computed or awaited; process-wide, read only by tests*)
  val counters: unit -> {printed: int, keyed: int, unfinished: int}

  (*one run of the finder with explicit inputs: the bottom locale and the
    dependency edges, in any order*)
  type finding
  val find: {bottom: string option, edges: Locale.locale_dependency list} ->
    Proof.context -> finding
  (*one link per linked element*)
  val links_of: finding -> (Universal_Key.universal_key * link) list
  (*the ladder's outcome for one theorem of a local fact*)
  datatype outcome = Rebound | No_Candidate | Linked of level | No_Link
  (*the walk's counts, its recorded arcs as (node, parent node), the facts the
    registration predicate recognised, the base names Level 5 looked up, and
    every element's outcome and template (tests, measurements)*)
  val report: finding ->
    {nodes: int, back_arcs: int, cuts: int, roots: int, arcs: (int * int) list,
     name_hits: int, name_hit_theorems: int, facts_with_candidate: int, candidates: int,
     narrowed: int, recognised: string list, level5_base_names: string list,
     elements:
      {name: string, index: int, outcome: outcome,
       template: {source: string, note: string, index: int, chain: string list,
         instance: term list} option} list}
end;

structure Link_Finder: LINK_FINDER =
struct


(*** Terms ***)

type subst = typ TFrees.table * term Frees.table;

val empty_subst: subst = (TFrees.empty, Frees.empty);

fun subst_term ((instT, inst): subst) t =
  if TFrees.is_empty instT andalso Frees.is_empty inst then t
  else Envir.beta_norm (Term_Subst.instantiate_frees (instT, inst) t);

fun subst_typ ((instT, _): subst) = Term_Subst.instantiateT_frees instT;

fun has_schematic t =
  Term.exists_subterm is_Var t orelse Term.exists_type (Term.exists_subtype is_TVar) t;

fun size_of_terms ts = fold (fn t => fn n => n + size_of_term t) ts 0;

fun is_variable t = is_Free t orelse is_Var t;

(*schematic variables, term and type, renamed in order of first occurrence*)
fun canonical_vars t =
  let
    val tvars = rev (Term.add_tvars t []);
    val vars = rev (Term.add_vars t []);
    val tren = map_index (fn (i, (xi, S)) => ((xi, S), TVar (("'c", i), S))) tvars;
    fun rename_typ (T as TVar v) = the_default T (AList.lookup (op =) tren v)
      | rename_typ (Type (a, Ts)) = Type (a, map rename_typ Ts)
      | rename_typ T = T;
    val ren = map_index (fn (i, (xi, T)) => ((xi, T), Var (("c", i), T))) vars;
  in
    Term.map_aterms (fn v as Var (xi, T) => the_default v (AList.lookup (op =) ren (xi, T))
      | a => a) t
    |> Term.map_types rename_typ
  end;

(*the same over a list, occurrences counted across it*)
fun canonical_list ts =
  if forall (not o has_schematic) ts then ts
  else snd (strip_comb (canonical_vars (list_comb (Free ("", dummyT), ts))));

(*structural equality in which any two schematic variables match*)
fun eq_skeleton (Var _, Var _) = true
  | eq_skeleton (Const (a, _), Const (b, _)) = a = b
  | eq_skeleton (Free (a, _), Free (b, _)) = a = b
  | eq_skeleton (Bound i, Bound j) = i = j
  | eq_skeleton (Abs (_, _, t), Abs (_, _, u)) = eq_skeleton (t, u)
  | eq_skeleton (t1 $ u1, t2 $ u2) = eq_skeleton (t1, t2) andalso eq_skeleton (u1, u2)
  | eq_skeleton _ = false;

fun eq_upto_var_names (t, u) =
  eq_skeleton (t, u) andalso canonical_vars t aconv canonical_vars u;

(*equal up to the names of schematic variables, or up to them after eta:
  two walk paths into one node can give the fact and the replayed note
  eta-different shapes*)
fun eq_upto_names (t, u) =
  eq_upto_var_names (t, u) orelse
  eq_upto_var_names (Envir.eta_contract t, Envir.eta_contract u);

fun eq_hyps (hs1, hs2) = subset (op aconv) (hs1, hs2) andalso subset (op aconv) (hs2, hs1);

fun same_thm (th, th') =
  Thm.prop_of th aconv Thm.prop_of th' andalso eq_hyps (Thm.hyps_of th, Thm.hyps_of th');

fun sorted_hyps hs = sort_distinct Term_Ord.fast_term_ord hs;

fun constants_of t = rev (Term.fold_aterms (fn Const (c, _) => cons c | _ => I) t []);

(*C24: a memo whose key is a function of its argument, coarser than it: the
  value of the first thunk given for the key; a memo keyed by its argument is
  stock apply_unsynchronized_cache*)
fun memo (empty, lookup, update) =
  let val cache = Unsynchronized.ref empty in
    fn key => fn thunk =>
      (case lookup (! cache) key of
        SOME v => v
      | NONE => let val v = thunk () in cache := update (key, v) (! cache); v end)
  end;



(*** Verdicts and kinds ***)

datatype kind = Identity | Renaming | Proper;

datatype verdict = Unchanged | Renamed | Instantiated;

type param = {verdict: verdict, name: string, text: string};

(*D41: a Free is identified by its name, a Var by its indexname; types are
  never read*)
fun same_variable (Free (x, _), Free (y, _)) = x = y
  | same_variable (Var (xi, _), Var (yi, _)) = xi = yi
  | same_variable _ = false;

(*the verdict of each parameter ps (Frees) receiving the terms ts, the first
  that applies: the Free of its own name; a non-variable, or a variable another
  parameter also receives (A2); any other variable*)
fun changes ps ts =
  let
    fun shared t = length (filter (fn u => same_variable (u, t)) ts) > 1;
    fun verdict (p as Free _) t =
          if same_variable (p, t) then Unchanged
          else if not (is_variable t) orelse shared t then Instantiated
          else Renamed
      | verdict p _ = raise TERM ("Link_Finder.changes: not a parameter", [p]);
  in map2 verdict ps ts end;

fun kind_of vs =
  if forall (fn v => v = Unchanged) vs then Identity
  else if member (op =) vs Instantiated then Proper
  else Renaming;

(*the verdicts with the parameters' names and the instances*)
fun params_of ps ts vs =
  map2 (fn (Free (name, _), t) => (fn v => (v, name, t))
    | (p, _) => raise TERM ("Link_Finder.params_of: not a parameter", [p])) (ps ~~ ts) vs;

fun param_frees thy loc = map (Free o #1) (Locale.params_of thy loc);



(*** Declarations: dependency edges and root registrations ***)

type edge = Locale.locale_dependency;

datatype declaration =
  Dependency_Edge of edge |
  Root_Registration of {locale: string, morphism: morphism, number: int};

fun source_of (Dependency_Edge e) = #source e
  | source_of (Root_Registration r) = #locale r;

fun prefix_of (Dependency_Edge e) = #prefix e
  | prefix_of (Root_Registration r) = Morphism.binding_prefix (#morphism r);

fun morphism_of (Dependency_Edge e) = #morphism e
  | morphism_of (Root_Registration r) = #morphism r;

(*serials for edges, negative numbers for root registrations*)
fun id_of (Dependency_Edge e) = #serial e
  | id_of (Root_Registration r) = ~1 - #number r;

fun chain_of d = maps (Long_Name.explode o #1) (prefix_of d);

(*own table: images of the source's type parameters and parameters*)
type table = ((string * sort) * typ) list * ((string * typ) * term) list;

(*schematic: the own table holds a schematic variable; the instances below
  the declaration are read through the composed morphism, never composed
  substitutions (the composition would merge ?V with ?Va)*)
type info = {morphism: morphism, table: table, schematic: bool};

fun table_of thy loc phi : table =
  let
    val m = Morphism.set_context thy phi;
    val (tps, ps) = Locale.parameters_of thy loc;
    val tvs = fold (fn ((_, T), _) => Term.add_tfreesT T) ps (rev tps) |> rev;
  in
    (map (fn v => (v, Morphism.typ m (TFree v))) tvs,
     map (fn ((x, T), _) => ((x, T), Morphism.term m (Free (x, T)))) ps)
  end;

fun child_subst parent ((tys, ts): table) : subst =
  let
    val instT = TFrees.make (map (fn (v, T) => (v, subst_typ parent T)) tys);
    val inst = Frees.make (map (fn ((x, T), t) =>
      ((x, Term_Subst.instantiateT_frees instT T), subst_term parent t)) ts);
  in (instT, inst) end;

(*the substitution read off a composed morphism, as Locale.instance_of reads an instance*)
fun morphism_subst thy loc phi : subst =
  let val (tys, ts) = table_of thy loc phi
  in child_subst empty_subst (tys, ts) end;

fun instance_of_subst (sub: subst) ((_, ts): table) =
  ts |> map (fn ((x, T), _) =>
    Envir.beta_eta_contract (the (Frees.lookup (#2 sub) (x, subst_typ sub T))));

(*a root registration's own table as a substitution morphism on types and
  terms; the argument's schematic variables are first raised above the
  table's maxidx, by one offset for every argument, so that they stay apart
  from the table's own schematic variables (B19)*)
fun subst_morphism (table as (tys, ts): table) =
  let
    val own = child_subst empty_subst table;
    val k = fold (Term.maxidx_typ o #2) tys (fold (Term.maxidx_term o #2) ts ~1) + 1;
  in
    Morphism.morphism "Link_Finder.subst"
      {binding = [], typ = [K (subst_typ own o Logic.incr_tvar k)],
       term = [K (subst_term own o Logic.incr_indexes ([], k))], fact = []}
  end;

fun make_info thy =
  let
    val cache = memo (Inttab.empty, Inttab.lookup, Inttab.update);
    fun get d = cache (id_of d) (fn () =>
      let val table = table_of thy (source_of d) (morphism_of d) in
        {morphism = Morphism.set_context thy (morphism_of d), table = table,
         schematic =
          exists (fn (_, T) => Term.exists_subtype is_TVar T) (#1 table) orelse
          exists (has_schematic o #2) (#2 table)}
      end);
  in get end;

(*the edges into a locale in content order: source, prefix with its marks,
  own instance; never serials*)
fun make_edges_into (info: declaration -> info) (edges: edge list) =
  let
    val into = fold_rev (fn e => Symtab.cons_list (#target e, e)) edges Symtab.empty;
    fun key e =
      (#source e, (map (fn (q, m) => if m then q else q ^ "?") (#prefix e),
        map (Envir.beta_eta_contract o #2) (#2 (#table (info (Dependency_Edge e))))));
    val ord = prod_ord string_ord (prod_ord (list_ord string_ord) (list_ord Term_Ord.term_ord));
  in
    Symtab.apply_unsynchronized_cache (fn loc =>
      Symtab.lookup_list into loc
      |> map (fn e => (key e, e)) |> sort (ord o apply2 #1) |> map (Dependency_Edge o #2))
  end;



(*** Notes ***)

(*the named notes of a locale in note order: (index among all its notes, binding, theorems)*)
fun named_notes thy loc =
  Locale.locale_notes thy loc |> maps #2 |> map_index I
  |> map_filter (fn (k, ((b, _), gs)) =>
      if Binding.is_empty b then NONE else SOME (k, b, maps #1 gs));

(*the named notes of a locale by binding long name: (index, binding, theorems)*)
fun make_notes thy =
  Symtab.apply_unsynchronized_cache (fn loc =>
    if loc = "" orelse not (Locale.defined thy loc) then Symtab.empty
    else
      fold (fn n as (_, b, _) => Symtab.cons_list (Binding.long_name_of b, n))
        (named_notes thy loc) Symtab.empty);

fun template_name locale b th =
  if Thm.has_name_hint th then #1 (Thm.get_name_hint th)
  else
    Long_Name.implode
      [Thm.theory_base_name th, Long_Name.base_name locale, Binding.long_name_of b];

fun template_global_fact thy name =
  let val facts = Global_Theory.facts_of thy in
    (case Context_Callbacks.accessible_entry_of_fact facts name of
      NONE => NONE
    | SOME _ =>
        (case Facts.lookup (Context.Theory thy) facts name of
          SOME {dynamic = false, thms} => SOME thms
        | _ => NONE))
  end;

fun parameter_images thy loc phi = #2 (table_of thy loc phi);

fun replay_notes thy loc phi =
  let val phi' = Morphism.set_context thy phi in
    named_notes thy loc |> map_filter (fn (_, _, []) => NONE | (_, b, ths as th :: _) =>
      SOME {binding = b, template_name = template_name loc b th,
        replayed = Morphism.fact phi' ths})
  end;

fun candidate_locales thy base_set =
  Name_Space.get_names (Locale.locale_space thy)
  |> filter (fn locale =>
       named_notes thy locale
       |> exists (fn (_, b, _) => Symtab.defined base_set (Binding.name_of b)));

(*a <c>_def note: one theorem c x1 ... xn = t (or \<equiv>), c a constant, the xi Frees*)
fun is_definition b th =
  let
    val lhs =
      (case Thm.prop_of th of
        Const (\<^const_name>\<open>Pure.eq\<close>, _) $ l $ _ => SOME l
      | Const (\<^const_name>\<open>Trueprop\<close>, _) $
          (Const (\<^const_name>\<open>HOL.eq\<close>, _) $ l $ _) => SOME l
      | _ => NONE);
  in
    (case lhs of
      NONE => false
    | SOME l =>
        let val (c, xs) = strip_comb l in
          is_Const c andalso forall is_Free xs andalso
          Binding.name_of b = Long_Name.base_name (#1 (dest_Const c)) ^ "_def"
        end)
  end;

(*a definitional note in meta form, through abs_def, reversed: definiens \<equiv> folded*)
fun reversed eq_reflection th =
  let
    val meta =
      if can Logic.dest_equals (Thm.prop_of th) then SOME th
      else (case eq_reflection of SOME r => try (fn th => th RS r) th | NONE => NONE);
  in Option.mapPartial (try (Thm.symmetric o Drule.abs_def)) meta end;



(*** The walk ***)

(*(source, chain), (root registration's number or ~1, instance)*)
structure Node_Table = Table
(
  type key = (string * string list) * (int * term list);
  val ord = prod_ord (prod_ord fast_string_ord (list_ord fast_string_ord))
    (prod_ord int_ord (list_ord Term_Ord.fast_term_ord));
);

structure Int_Pair_Table = Table
(
  type key = int * int;
  val ord = prod_ord int_ord int_ord;
);

(*a node is keyed by (source, chain, instance, root), the chain a prefix of
  some local fact's qualifier chain and root the root registration whose arc
  begins the node's path, none for a node reached by dependency edges only
  (M06); subst and schematic are those of the path that created it;
  instance_morphism: the composed morphism with a root registration's own
  table in place of its morphism, so that its mixins act on that table only*)
type node =
  {source: string, chain: string list, instance: term list, root: int option,
   morphism: morphism, instance_morphism: morphism, subst: subst, schematic: bool,
   size: int};

(*incoming: node -> (parent node, declaration), the recorded arcs; an arrival
  at a node on the depth-first path is a back arc, counted and not recorded,
  so the recorded arcs form an acyclic graph (D42)*)
type walk =
  {nodes: node vector,
   incoming: (int * declaration) list Inttab.table,
   back_arcs: int,
   cuts: (string * int * string list) list};

fun node_key ({source, chain, instance, root, ...}: node) =
  ((source, chain), (the_default ~1 root, canonical_list instance));

(*the node's propositions are read through its composed morphism: in the
  schematic case, and below a root registration, whose morphism carries the
  mixins*)
fun by_morphism (n: node) = #schematic n orelse is_some (#root n);

fun strictly_growing (a :: (rest as b :: _)) = a < b andalso strictly_growing rest
  | strictly_growing _ = true;

(*§4.3 Level 1: content order, own tables, D22, node keys; an edge is followed
  when its composed chain is an allowed chain.  Every instance is composed from
  own tables (through the morphism in the schematic case); a root
  registration's mixins enter its own table only: below it they would fold an
  instance back into its parent's, an arc on which the instance grows without
  end.  Returns the walk over the dependency edges and the function that
  continues it from the bottom node over root registrations (Level 5)*)
fun walk {thy, info, edges_into, bottom, allowed} =
  let
    val nodes = Unsynchronized.ref (Inttab.empty : node Inttab.table);
    val count = Unsynchronized.ref 0;
    val seen = Unsynchronized.ref (Node_Table.empty : int Node_Table.table);
    val incoming = Unsynchronized.ref (Inttab.empty : (int * declaration) list Inttab.table);
    val back_arcs = Unsynchronized.ref 0;
    val cuts = Unsynchronized.ref ([] : (string * int * string list) list);
    fun new (n: node) =
      let val i = ! count in
        count := i + 1;
        nodes := Inttab.update (i, n) (! nodes);
        seen := Node_Table.update (node_key n, i) (! seen); i
      end;
    fun child (n: node) d : node =
      let
        val inf = info d;
        val schematic = #schematic n orelse #schematic inf;
        val subst =
          if schematic then
            morphism_subst thy (source_of d) (morphism_of d $> #instance_morphism n)
          else child_subst (#subst n) (#table inf);
        val instance = instance_of_subst subst (#table inf);
        val (root, instance_morphism) =
          (case d of
            Root_Registration {number, ...} => (SOME number, subst_morphism (#table inf))
          | Dependency_Edge _ => (#root n, morphism_of d $> #instance_morphism n));
      in
        {source = source_of d, chain = #chain n @ chain_of d, instance = instance, root = root,
         morphism = morphism_of d $> #morphism n, instance_morphism = instance_morphism,
         subst = subst, schematic = schematic, size = size_of_terms instance}
      end;
    (*path: (node, source, instance size) from the current node up to the bottom*)
    fun expand path (i, n: node) ds =
      ds |> List.app (fn d =>
        if not (allowed (#chain n @ chain_of d)) then ()
        else
          let val c = child n d in
            (case Node_Table.lookup (! seen) (node_key c) of
              SOME j =>
                if exists (fn (k, _, _) => k = j) path then back_arcs := ! back_arcs + 1
                else incoming := Inttab.cons_list (j, (i, d)) (! incoming)
            | NONE =>
                let
                  val prev = path |> filter (fn (_, l, _) => l = #source c) |> map #3;
                  val r = length prev;
                in
                  if r > 30 orelse (r > 10 andalso strictly_growing (rev prev @ [#size c])) then
                    cuts := (#source c, r, #chain c) :: ! cuts
                  else
                    let val j = new c in
                      incoming := Inttab.cons_list (j, (i, d)) (! incoming);
                      expand ((j, #source c, #size c) :: path) (j, c) (edges_into (#source c))
                    end
                end)
          end);
    val instance0 =
      if bottom = "" then [] else map Envir.beta_eta_contract (param_frees thy bottom);
    val n0 =
      {source = bottom, chain = [], instance = instance0, root = NONE,
       morphism = Morphism.identity, instance_morphism = Morphism.identity, subst = empty_subst,
       schematic = false, size = size_of_terms instance0};
    val i0 = new n0;
    val path0 = [(i0, bottom, #size n0)];
    fun result () : walk =
      {nodes = Vector.fromList (map #2 (Inttab.dest (! nodes))),
       incoming = Inttab.map (K rev) (! incoming), back_arcs = ! back_arcs, cuts = rev (! cuts)};
    val _ = expand path0 (i0, n0) (edges_into bottom);
  in (result (), fn roots => (expand path0 (i0, n0) roots; result ())) end;

(*the order of nodes: instance size, source, chain, instance, root (none first)*)
fun node_ord (a: node, b: node) =
  (case int_ord (#size a, #size b) of
    EQUAL =>
      (case string_ord (#source a, #source b) of
        EQUAL =>
          (case list_ord string_ord (#chain a, #chain b) of
            EQUAL =>
              (case list_ord Term_Ord.term_ord (#instance a, #instance b) of
                EQUAL => option_ord int_ord (#root a, #root b)
              | ord => ord)
          | ord => ord)
      | ord => ord)
  | ord => ord);



(*** Level 1: names, the position rule and the registration predicate ***)

(*a name hit: a named note at a node*)
type candidate = {node: int, k: int, binding: binding, thms: thm list, pos: Position.T};

(*full names and binding positions once per (source, chain); names are never
  split*)
fun make_names ctxt notes =
  let
    val cache = memo (Symtab.empty, Symtab.lookup, Symtab.update);
    fun names_of ({source, chain, morphism, ...}: node) =
      cache (space_implode "." (source :: "\000" :: chain)) (fn () =>
        Symtab.fold (fn (_, ns) => fold (fn (k, b, ths) =>
          let val b' = Morphism.binding morphism b
          in cons (k, b, ths, Proof_Context.full_name ctxt b', Binding.pos_of b') end) ns)
          (notes source) []);
  in names_of end;

(*the name hits of a walk by full name*)
fun name_table names_of (W: walk) =
  Vector.foldri (fn (j, n: node, tab) =>
      fold (fn (k, b, ths, full, pos) =>
        Symtab.cons_list (full, {node = j, k = k, binding = b, thms = ths, pos = pos}))
        (names_of n) tab)
    Symtab.empty (#nodes W);

(*the order of trial: the nodes' order, then the note index*)
fun trial_ord (W: walk) (c1: candidate, c2: candidate) =
  (case node_ord (Vector.sub (#nodes W, #node c1), Vector.sub (#nodes W, #node c2)) of
    EQUAL => int_ord (#k c1, #k c2)
  | ord => ord);

(*a name hit at the fact's name-space position: its binding position is a real
  one and equals the position of the fact's entry, which the activation that
  wrote the fact last stored*)
fun at_position fpos (c: candidate) = #pos c <> Position.none andalso #pos c = fpos;

fun fact_position ctxt =
  let val space = Facts.space_of (Proof_Context.facts_of ctxt)
  in fn name => the_default Position.none (try (#pos o Name_Space.the_entry space) name) end;

(*the registration predicate (D52): no name hit is at the fact's position while
  some hit has a binding position, so a registration command, which sets every
  binding it activates to its own position, wrote the fact*)
fun written_by_registration fpos hits =
  not (exists (at_position fpos) hits) andalso
  exists (fn c: candidate => #pos c <> Position.none) hits;

(*the position rule, in the order of trial: the name hits at the position when
  there are any; for a fact written by a registration command, the hits at
  nodes keyed by a root registration; else all of them*)
fun candidates (W: walk) fpos hits =
  let
    val at = filter (at_position fpos) hits;
    fun under_root (c: candidate) = is_some (#root (Vector.sub (#nodes W, #node c)));
  in
    sort (trial_ord W)
      (if not (null at) then at
       else if written_by_registration fpos hits then filter under_root hits
       else hits)
  end;



(*** The ladder ***)

datatype level = Level2 | Level3_Exact of (term * term) list | Level3_Approximate;

datatype outcome = Rebound | No_Candidate | Linked of level | No_Link;

(*thm: the theorem compared, exported to the block's target for a lemma of a
  nested block*)
type element = {name: string, index: int, fact: thm, thm: thm, candidates: candidate list};

(*Level 0: the proof stated the fact; Facts.could_unify finds one of its
  theorems under the fact's own name and index*)
fun rebound ctxt (name, ths) =
  let val facts = Proof_Context.facts_of ctxt in
    exists (fn (i, th) =>
      exists (fn (th', _) => Thm.has_name_hint th' andalso
          Thm.get_name_hint th' = (name, if length ths = 1 then 0 else i + 1))
        (Facts.could_unify facts (Thm.prop_of th))) (map_index I ths)
  end;

structure Int_Terms_Table = Table
(
  type key = int * term list;
  val ord = prod_ord int_ord (list_ord Term_Ord.fast_term_ord);
);

(*(node, (note, index))*)
structure Prop_Table = Table
(
  type key = int * (int * int);
  val ord = prod_ord int_ord (prod_ord int_ord int_ord);
);

(*a definitional equation of a node at term level, definiens \<equiv> folded*)
type equation = {folded: term, definiens: term};

(*terms compared for relevance: eta-contracted, types, bound names and
  schematic names erased*)
fun erase t =
  Envir.eta_contract t |> Term.map_types (K dummyT) |> Term.map_abs_vars (K "")
  |> Term.map_aterms (fn Var _ => Var (("x", 0), dummyT) | a => a);

fun subterms t acc =
  (case t of
    f $ u => subterms f (subterms u (t :: acc))
  | Abs (_, _, b) => subterms b (t :: acc)
  | _ => t :: acc);

(*the edit distance when at most k, else k + 1: the band |i - j| <= k*)
fun edit_distance_upto k (xs: string list) (ys: string list) =
  let
    val a = Vector.fromList xs and b = Vector.fromList ys;
    val n = Vector.length a and m = Vector.length b;
    val inf = k + 1;
  in
    if abs (n - m) > k then inf
    else
      let
        val prev = Array.tabulate (m + 1, fn j => if j <= k then j else inf);
        val cur = Array.array (m + 1, inf);
        fun row i =
          if i > n then ()
          else
            let
              val lo = Int.max (1, i - k) and hi = Int.min (m, i + k);
              val _ = Array.update (cur, 0, if i <= k then i else inf);
              val _ = if lo - 1 >= 1 then Array.update (cur, lo - 1, inf) else ();
              fun col j =
                if j > hi then ()
                else
                  let
                    val cost = if Vector.sub (a, i - 1) = Vector.sub (b, j - 1) then 0 else 1;
                    val v = Int.min (Int.min (Array.sub (prev, j) + 1, Array.sub (cur, j - 1) + 1),
                      Array.sub (prev, j - 1) + cost);
                  in Array.update (cur, j, Int.min (v, inf)); col (j + 1) end;
              val _ = col lo;
              val _ = if hi + 1 <= m then Array.update (cur, hi + 1, inf) else ();
              val _ = Array.copy {src = cur, dst = prev, di = 0};
            in row (i + 1) end;
      in row 1; Int.min (Array.sub (prev, m), inf) end
  end;

(*§4.3 Levels 2 and 3 per element, over its candidates in the order of trial;
  Level 2 for every element before any Level 3 (D23).  The searches step over
  the recorded arcs only, which are acyclic, so every search is finite*)
fun ladder {thy, ctxt, notes, info: declaration -> info, W: walk, elements: element list}
    : (outcome * candidate option) list =
  let
    fun node j = Vector.sub (#nodes W, j);
    val incoming = Inttab.lookup_list (#incoming W);
    fun morph d = #morphism (info d);

    (*propositions: under the node's substitution, or through its composed
      morphism when read by morphism*)
    val props = memo (Prop_Table.empty, Prop_Table.lookup, Prop_Table.update);
    fun prop_at ({node = j, k, thms, ...}: candidate) i = props (j, (k, i)) (fn () =>
      let val n = node j; val t0 = Thm.prop_of (nth thms i) in
        if by_morphism n then Morphism.term (Morphism.set_context thy (#morphism n)) t0
        else subst_term (#subst n) t0
      end);

    (*the hyps search: states (node, hyp set), each with the first theorem
      that reached it; steps over every incoming arc with the single
      declaration's morphism, memoised per (declaration, hyp set); the bottom
      node ends a route*)
    val state_ids = Unsynchronized.ref (Int_Terms_Table.empty : int Int_Terms_Table.table);
    val states = Unsynchronized.ref (Inttab.empty : (int * term list * thm) Inttab.table);
    val nstates = Unsynchronized.ref 0;
    val transitions = memo (Int_Terms_Table.empty, Int_Terms_Table.lookup, Int_Terms_Table.update);
    fun intern (j, hs, th) =
      (case Int_Terms_Table.lookup (! state_ids) (j, hs) of
        SOME s => s
      | NONE =>
          let val s = ! nstates in
            nstates := s + 1;
            state_ids := Int_Terms_Table.update ((j, hs), s) (! state_ids);
            states := Inttab.update (s, (j, hs, th)) (! states); s
          end);
    fun transition d (hs, th) = transitions (id_of d, hs) (fn () =>
      let val th' = Morphism.thm (morph d) th in (sorted_hyps (Thm.hyps_of th'), th') end);
    val succs = Inttab.apply_unsynchronized_cache (fn s =>
      let val (j, hs, th) = the (Inttab.lookup (! states) s) in
        if j = 0 then []
        else incoming j |> map (fn (p, d) =>
          let val (hs', th') = transition d (hs, th) in intern (p, hs', th') end)
      end);
    val answers = memo (Int_Terms_Table.empty, Int_Terms_Table.lookup, Int_Terms_Table.update);
    (*does some route from node j carry the hyps of th to a hyp set H at the
      bottom with H plus extra equal to target as sets?*)
    fun hyps_reach j th (target, extra) =
      let
        val s0 = intern (j, sorted_hyps (Thm.hyps_of th), th);
        val tg = sorted_hyps target and ex = sorted_hyps extra;
      in
        answers (s0, tg @ [Term.dummy] @ ex) (fn () =>
          let
            val visited = Unsynchronized.ref (Inttab.make [(s0, ())]);
            fun accept s =
              let val (j', hs, _) = the (Inttab.lookup (! states) s)
              in j' = 0 andalso eq_hyps (union (op aconv) ex hs, tg) end;
            fun go [] = false
              | go (s :: rest) =
                  accept s orelse
                    let
                      val next =
                        succs s |> filter_out (Inttab.defined (! visited)) |> distinct (op =);
                      val _ = visited := fold (fn s' => Inttab.update (s', ())) next (! visited);
                    in go (next @ rest) end;
          in go [s0] end)
      end;

    (*the theorem-list search: the whole note through every incoming arc with
      Morphism.fact, as activation applies it; states keyed by (node, props,
      hyps, maxidx); the lists reaching the bottom node are computed once per
      (node, note) and shared by the note's elements and by Level 3*)
    val bottom_lists = memo (Int_Pair_Table.empty, Int_Pair_Table.lookup, Int_Pair_Table.update);
    fun list_key j ths = (j, ths |> maps (fn t =>
      Free (string_of_int (Thm.maxidx_of t), dummyT) :: Thm.prop_of t ::
        sorted_hyps (Thm.hyps_of t)));
    fun lists_at_bottom ({node = j, k, thms, ...}: candidate) = bottom_lists (j, k) (fn () =>
      let
        val visited = Unsynchronized.ref (Int_Terms_Table.make [(list_key j thms, ())]);
        fun go [] acc = rev acc
          | go ((a, xs) :: rest) acc =
              if a = 0 then go rest (xs :: acc)
              else
                let
                  val next = incoming a |> map_filter (fn (p, d) =>
                    let val xs' = Morphism.fact (morph d) xs; val key = list_key p xs' in
                      if Int_Terms_Table.defined (! visited) key then NONE
                      else
                        (visited := Int_Terms_Table.update (key, ()) (! visited);
                         SOME (p, xs'))
                    end);
                in go (next @ rest) acc end;
      in go [(j, thms)] [] end);
    fun list_reach c accept = exists accept (lists_at_bottom c);

    (*Level 2*)
    fun level2 (c as {node = j, thms, ...}: candidate) i th =
      let val p = Thm.prop_of th and t = prop_at c i in
        if t aconv p then hyps_reach j (nth thms i) (Thm.hyps_of th, [])
        else if eq_upto_names (t, p) then list_reach c (fn xs => same_thm (th, nth xs i))
        else false
      end;
    val after2 = elements |> map (fn el as {index = i, thm, candidates, ...} =>
      if null candidates then (el, SOME (No_Candidate, NONE))
      else
        (case find_first (fn c => level2 c i thm) candidates of
          SOME c => (el, SOME (Linked Level2, SOME c))
        | NONE => (el, NONE)));

    (*Level 3: the <c>_def notes of every walked node, nodes in their order*)
    val eq_reflection = try (Global_Theory.get_thm thy) "HOL.eq_reflection";
    val stored_equations = Symtab.apply_unsynchronized_cache (fn src =>
      Symtab.fold (fn (_, ns) => fold (fn (k, b, ths) =>
          (case ths of
            [th] =>
              if is_definition b th then
                (case reversed eq_reflection th of
                  SOME eq => cons (k, th, Thm.prop_of eq)
                | NONE => I)
              else I
          | _ => I)) ns) (notes src) []
      |> sort (int_ord o apply2 #1));
    val node_order = sort (node_ord o apply2 node) (0 upto Vector.length (#nodes W) - 1);
    fun real_equation j th =
      reversed eq_reflection (Morphism.thm (Morphism.set_context thy (#morphism (node j))) th);
    val equations = Lazy.lazy (fn () =>
      node_order |> maps (fn j =>
        let val n as {source, subst, ...} = node j in
          stored_equations source |> map_filter (fn (_, th, eq) =>
            (case
              (if by_morphism n then Option.map Thm.prop_of (real_equation j th)
               else SOME (subst_term subst eq)) of
              SOME (Const (\<^const_name>\<open>Pure.eq\<close>, _) $ d $ f) =>
                SOME {folded = f, definiens = d}
            | _ => NONE))
        end)
      |> (fn eqs => fold (fn e: equation => fn (seen, acc) =>
            let val key = Logic.mk_equals (#definiens e, #folded e) in
              if Termtab.defined seen key then (seen, acc)
              else (Termtab.update (key, ()) seen, e :: acc)
            end) eqs (Termtab.empty, []) |> #2 |> rev));
    fun side_index side eqv =
      Vector.foldri (fn (i, e: equation, tab) => Termtab.cons_list (erase (side e), i) tab)
        Termtab.empty eqv;
    fun hits tab t = subterms (erase t) [] |> maps (Termtab.lookup_list tab) |> distinct (op =);
    (*relevance: the equations whose folded side occurs in the proposition,
      closed under nesting; a candidate must contain a relevant definiens,
      tested first by the definiens' first constant*)
    val relevance = Lazy.lazy (fn () =>
      let
        val eqv = Vector.fromList (Lazy.force equations);
        val folded_tab = side_index #folded eqv;
        val definiens_tab = side_index #definiens eqv;
        val nested = Vector.map (hits folded_tab o #definiens) eqv;
        fun relevant prop =
          let
            fun close acc [] = acc
              | close acc (i :: todo) =
                  let val new = Vector.sub (nested, i) |> filter_out (member (op =) acc)
                  in close (new @ acc) (new @ todo) end;
            val direct = hits folded_tab prop;
          in if null direct then [] else sort_distinct int_ord (close direct direct) end;
        val first_constant =
          eqv |> Vector.map (fn e: equation =>
            (case constants_of (#definiens e) of c :: _ => SOME c | [] => NONE));
        fun can_fire idx t =
          (let val cs = map (fn i => Vector.sub (first_constant, i)) idx in
            exists is_none cs orelse
              let val tab = fold (fn SOME c => Symtab.update (c, ()) | NONE => I) cs Symtab.empty
              in Term.exists_Const (fn (c, _) => Symtab.defined tab c) t end
           end) andalso
          exists (member (op =) idx) (hits definiens_tab t);
      in (eqv, relevant, can_fire) end);
    fun rules_of idx =
      let val (eqv, _, _) = Lazy.force relevance
      in
        idx |> map (fn k =>
          let val {folded, definiens, ...} = Vector.sub (eqv, k) in (definiens, folded) end)
      end;
    (*the pre-check's rewriting, the term part of Element.eq_morphism: the
      equations as procs in their order rewrite as the same rules would
      (more_pattern.ML: rules, then procs, each by get_first), each noting
      itself when it fires (D65); the result and the equations that fired*)
    fun rewrite_recording idx t =
      let
        val fired = Unsynchronized.ref [];
        fun proc (k, rule) u =
          Pattern.match_rew thy u rule
          |> Option.map (fn (v, _) => (fired := insert (op =) k (! fired); v));
        val u = Pattern.rewrite_term thy [] (map proc (idx ~~ rules_of idx)) t;
      in (u, sort int_ord (! fired)) end;
    (*the fact part of Element.eq_morphism over all the walk's real
      equations, built on the first passing pre-check*)
    val real = Lazy.lazy (fn () =>
      let
        val eqs =
          node_order |> maps (fn j =>
            stored_equations (#source (node j)) |> map_filter (real_equation j o #2))
          |> distinct (fn (a, b) => Thm.prop_of a aconv Thm.prop_of b);
        val sctxt = Proof_Context.init_global thy |> Raw_Simplifier.put_simpset
          (Raw_Simplifier.simpset_of (Raw_Simplifier.init_simpset eqs ctxt));
      in (sctxt, Element.eq_morphism ctxt eqs |> Option.map (Morphism.set_context thy)) end);
    (*the equations the pre-check applied, when the candidate passes*)
    fun level3 idx p th i (c as {node = j, thms, ...}: candidate) =
      let
        val (_, _, can_fire) = Lazy.force relevance;
        val t = prop_at c i;
        fun decision () =
          let
            val (sctxt, eqm) = Lazy.force real;
            val eq = Raw_Simplifier.rewrite0 sctxt true (Thm.global_cterm_of thy t);
            val r = Thm.term_of (Thm.rhs_of eq);
          in
            if r aconv p then hyps_reach j (nth thms i) (Thm.hyps_of th, Thm.hyps_of eq)
            else if eq_upto_names (r, p) then
              (case eqm of
                SOME m => list_reach c (fn xs =>
                  (case try (Morphism.thm m) (nth xs i) of
                    SOME x => same_thm (th, x)
                  | NONE => false))
              | NONE => false)
            else false
          end;
      in
        if not (can_fire idx t) then NONE
        else
          let val (u, fired) = rewrite_recording idx t in
            if eq_upto_names (u, p) andalso decision () then SOME (rules_of fired) else NONE
          end
      end;
    fun exact3 ({index = i, thm, candidates, ...}: element) =
      let
        val p = Thm.prop_of thm;
        val (_, relevant, _) = Lazy.force relevance;
        val idx = relevant p;
      in
        if null idx then NONE
        else get_first (fn c => Option.map (pair c) (level3 idx p thm i c)) candidates
      end;

    (*Level 3 approximate: constant sequences, each context-defined constant
      replaced by the constants of its definition first in the nodes' order;
      accepted within edit distance 2, the closest first in the order of
      trial*)
    val definitions = Lazy.lazy (fn () =>
      fold (fn {folded, definiens, ...} =>
          (case head_of folded of
            Const (c, _) => Symtab.default (c, constants_of definiens)
          | _ => I))
        (Lazy.force equations) Symtab.empty);
    fun replaced tab t = constants_of t |> maps (fn c => the_default [c] (Symtab.lookup tab c));
    fun approximate ({index = i, thm, candidates, ...}: element) =
      let
        val tab = Lazy.force definitions;
        val q = replaced tab (Thm.prop_of thm);
        fun scan [] best = best
          | scan (c :: rest) best =
              let
                val x = edit_distance_upto 2 q (replaced tab (prop_at c i));
                val best' =
                  (case best of
                    NONE => if x <= 2 then SOME (c, x) else NONE
                  | SOME (_, x0) => if x < x0 then SOME (c, x) else best);
              in (case best' of SOME (_, 0) => best' | _ => scan rest best') end;
      in Option.map #1 (scan candidates NONE) end;

    val outcomes = after2 |> map (fn (el, v) =>
      (case v of
        SOME r => r
      | NONE =>
          (case exact3 el of
            SOME (c, rws) => (Linked (Level3_Exact rws), SOME c)
          | NONE =>
              (case approximate el of
                SOME c => (Linked Level3_Approximate, SOME c)
              | NONE => (No_Link, NONE)))));
  in outcomes end;



(*** Level 5: block registrations and root registrations ***)

fun instance_key thy loc phi = map Envir.beta_eta_contract (Locale.instance_of thy loc phi);

(*root registrations of the locales noting the unmatched base names: block
  registrations (the proof context's minus the theory's, by instance) that no
  dependency edge yields, with the same instance and prefix, from another
  block registration*)
fun root_registrations_for thy ctxt (edges: edge list) base_set =
  let
    val from = fold_rev (fn e => Symtab.cons_list (#source e, e)) edges Symtab.empty;
    val block = Symtab.apply_unsynchronized_cache (fn loc =>
      let
        val old =
          Locale.registrations_of (Context.Theory thy) loc |> map (instance_key thy loc o #2);
      in
        Locale.registrations_of (Context.Proof ctxt) loc
        |> filter_out (fn (_, phi) => member (eq_list (op aconv)) old (instance_key thy loc phi))
      end);
    fun key (loc, phi) = (loc, (Morphism.binding_prefix phi, instance_key thy loc phi));
    fun eq_key ((l1, (p1, i1)), (l2, (p2, i2))) =
      l1 = l2 andalso p1 = p2 andalso eq_list (op aconv) (i1, i2);
    fun parents (loc, phi) =
      Symtab.lookup_list from loc |> maps (fn e =>
        block (#target e) |> map_filter (fn (_, psi) =>
          let val phi' = #morphism e $> psi in
            if eq_key (key (loc, phi'), key (loc, phi)) then SOME (#target e, psi) else NONE
          end));
    fun roots [] _ acc = acc
      | roots (r :: todo) visited acc =
          if member eq_key visited (key r) then roots todo visited acc
          else
            (case parents r of
              [] => roots todo (key r :: visited) (r :: acc)
            | ps => roots (ps @ todo) (key r :: visited) acc);
    val start = candidate_locales thy base_set |> maps block;
    val ord =
      prod_ord string_ord
        (prod_ord (list_ord (prod_ord string_ord bool_ord)) (list_ord Term_Ord.term_ord));
  in
    roots start [] []
    |> sort (ord o apply2 key)
    |> map_index (fn (i, (loc, phi)) =>
      Root_Registration {locale = loc, morphism = phi, number = i})
  end;



(*** One run ***)

datatype template =
  Note of candidate |
  Block_Lemma of {name: string, thms: thm list};

(*facts: the local facts Level 0 left*)
type finding =
  {thy: theory, ctxt: Proof.context, facts: (string * thm list) list,
   W: walk, roots: declaration list, names: candidate list Symtab.table,
   fpos: string -> Position.T, recognised: string list, level5_base_names: string list,
   results: (element * outcome * template option) list};

fun name_parts name = (case Long_Name.explode name of "local" :: xs => xs | xs => xs);

fun allowed_chains facts =
  let
    val tab = fold (fn (name, _) => fn tab =>
        let val xs = name_parts name
        in
          fold (fn k => Symtab.update (space_implode "." (take k xs), ()))
            (0 upto length xs - 1) tab
        end)
      facts Symtab.empty;
  in fn chain => Symtab.defined tab (space_implode "." chain) end;

(*the target of a nested block and the export into it*)
fun nested_target ctxt =
  if Local_Theory.level ctxt >= 2 then
    let val target = Local_Theory.target_of ctxt
    in SOME (target, Proof_Context.export_morphism ctxt target) end
  else NONE;

(*§4.3's evaluation order*)
fun find {bottom, edges} ctxt : finding =
  let
    val thy = Proof_Context.theory_of ctxt;
    val bottom = the_default "" bottom;
    (*(1) the local facts and the allowed chains, over all of them*)
    val all_facts =
      Facts.dest_static false [Global_Theory.facts_of thy] (Proof_Context.facts_of ctxt);
    val allowed = allowed_chains all_facts;
    (*(2) Level 0: no later stage sees the facts the proof stated*)
    val (rebound_facts, facts) = List.partition (rebound ctxt) all_facts;
    (*(3) the walk*)
    val notes = make_notes thy;
    val info = make_info thy;
    val edges_into = make_edges_into info edges;
    val (W1, continue) =
      walk {thy = thy, info = info, edges_into = edges_into, bottom = bottom, allowed = allowed};
    (*(4) names, binding positions, the registration predicate*)
    val names_of = make_names ctxt notes;
    val names1 = name_table names_of W1;
    val fpos = fact_position ctxt;
    val recognised =
      facts |> filter (fn (name, _) =>
        written_by_registration (fpos name) (Symtab.lookup_list names1 name))
      |> map #1;
    (*(5) Level 5: the root registrations for the facts with no name hit and the
      recognised ones, the walk continued over their arcs*)
    val level5_base_names =
      facts |> filter (fn (name, _) =>
        null (Symtab.lookup_list names1 name) orelse member (op =) recognised name)
      |> map (Long_Name.base_name o #1) |> distinct (op =);
    val roots =
      if null level5_base_names then []
      else root_registrations_for thy ctxt edges (Symtab.make_set level5_base_names);
    val (W, names) =
      if null roots then (W1, names1)
      else let val W = continue roots in (W, name_table names_of W) end;
    (*(6) Levels 2 and 3*)
    val nested = nested_target ctxt;
    fun compared (name, ths) =
      (case nested of
        NONE => ths
      | SOME (target, export) =>
          (case Facts.lookup (Context.Proof target) (Proof_Context.facts_of target) name of
            SOME {thms, ...} =>
              if eq_list Thm.eq_thm_prop (ths, thms) then ths else map (Morphism.thm export) ths
          | NONE => map (Morphism.thm export) ths));
    val elements = facts |> maps (fn (fact as (name, ths)) =>
      let val cs = candidates W (fpos name) (Symtab.lookup_list names name) in
        map_index (fn (i, (th, th')) =>
          {name = name, index = i, fact = th, thm = th',
           candidates = filter (fn c => i < length (#thms c)) cs}) (ths ~~ compared fact)
      end);
    val outcomes = ladder {thy = thy, ctxt = ctxt, notes = notes, info = info, W = W,
      elements = elements};
    (*a lemma of an unnamed block: its exported copy named by Local_Theory.full_name*)
    fun block_lemma ({name, index = i, fact, thm, ...}: element) =
      if bottom <> "" orelse is_none nested orelse Thm.eq_thm_prop (fact, thm) then NONE
      else
        let
          val binding = Binding.qualified_name (Long_Name.implode (name_parts name));
          val full = Local_Theory.full_name ctxt binding;
        in
          (case template_global_fact thy full of
            SOME gths =>
              if i < length gths andalso
                eq_upto_names (Thm.prop_of (nth gths i), Thm.prop_of thm) andalso
                eq_hyps (Thm.hyps_of (nth gths i), Thm.hyps_of thm)
              then SOME (Block_Lemma {name = full, thms = gths}) else NONE
          | NONE => NONE)
        end;
    val rebound_results =
      rebound_facts |> maps (fn (name, ths) =>
        map_index (fn (i, th) =>
          ({name = name, index = i, fact = th, thm = th, candidates = []}, Rebound, NONE)) ths);
    val results = (elements ~~ outcomes) |> map (fn (el, (v, c)) =>
      (case (v, c) of
        (Linked _, SOME c) => (el, v, SOME (Note c))
      | (No_Candidate, _) =>
          (case block_lemma el of
            SOME t => (el, Linked Level2, SOME t)
          | NONE => (el, v, NONE))
      | _ => (el, v, NONE)));
  in
    {thy = thy, ctxt = ctxt, facts = facts,
     W = W, roots = roots, names = names, fpos = fpos, recognised = recognised,
     level5_base_names = level5_base_names, results = rebound_results @ results}
  end;



(*** The linking cache (§4.2; D44 as revised by D48, D54, D68) ***)

(*terms matched exactly, bound-variable names included (D68): syntax_term_ord is
  EQUAL iff the terms are =; the instance Pure keeps local in term_sharing.ML*)
structure Syntax_Termtab = Table(type key = term val ord = Term_Ord.syntax_term_ord);

(*one per lineage, keyed by the exact term: the text table, each term's text
  printed in the context of the first caller that needed it (D54), and the key
  table, each proposition's theorem key*)
structure Cache = Proof_Data
(
  type T =
    {texts: string lazy Syntax_Termtab.table,
     keys: Universal_Key.universal_key lazy Syntax_Termtab.table} Synchronized.var;
  fun init _ : T =
    Synchronized.var "Link_Finder.cache"
      {texts = Syntax_Termtab.empty, keys = Syntax_Termtab.empty};
);

val counts = Synchronized.var "Link_Finder.counters" {printed = 0, keyed = 0, unfinished = 0};
fun counters () = Synchronized.value counts;
fun count {printed = p, keyed = k, unfinished = u} =
  Synchronized.change counts (fn {printed, keyed, unfinished} =>
    {printed = printed + p, keyed = keyed + k, unfinished = unfinished + u});

(*one table's entries for the requests, each a term with the computation of its
  value: looked up, or installed when absent or failed; nothing is computed here*)
fun install requests tab =
  Syntax_Termtab.fold (fn (t, e) => fn (xs, tab) =>
    let
      fun fresh () = let val x = Lazy.lazy e in (x, Syntax_Termtab.update (t, x) tab) end;
      val (x, tab') =
        (case Syntax_Termtab.lookup tab t of
          SOME x => (case Lazy.peek x of SOME (Exn.Exn _) => fresh () | _ => (x, tab))
        | NONE => fresh ());
    in (Syntax_Termtab.update (t, x) xs, tab') end) requests (Syntax_Termtab.empty, tab);

(*a call's text and key entries: installed under one lock operation on the cell,
  then forced together outside it; Lazy.map_finished makes a finished entry a
  value, so a call whose entries are all cached forks nothing (lazy.ML:131-146)*)
fun entries ctxt (text_requests, key_requests) =
  let
    val (ts, ks) =
      Synchronized.change_result (Cache.get ctxt) (fn {texts, keys} =>
        let
          val (ts, texts') = install text_requests texts;
          val (ks, keys') = install key_requests keys;
        in ((ts, ks), {texts = texts', keys = keys'}) end);
    fun units tab = Syntax_Termtab.fold (cons o Lazy.map_finished ignore o #2) tab;
    val us = units ts (units ks []);
    val _ = count {printed = 0, keyed = 0, unfinished = length (filter_out Lazy.is_finished us)};
    val _ = Lazy.consolidate us;
  in (ts, ks) end;

fun requests f xs = Syntax_Termtab.make_distinct (map f xs);
fun value tab t = Lazy.force (the (Syntax_Termtab.lookup tab t));

(*a term with the computation of its text, printed in ctxt*)
fun text_request ctxt t =
  (t, fn () =>
    Explain_Term.string_of_term ctxt t before count {printed = 1, keyed = 0, unfinished = 0});

(*a theorem's proposition with the computation of its theorem key, read in context*)
fun key_request (context, th) =
  (Thm.prop_of th, fn () =>
    Universal_Key.key_of_theorem' NONE context th
      before count {printed = 0, keyed = 1, unfinished = 0});



(*** Links ***)

type link =
  {template: Universal_Key.universal_key,
   statement: string,
   source: string,
   note: string * int,
   params: param list,
   rewrites: (string * string) list,
   entities: (string * Universal_Key.universal_key) list,
   level: level};

fun note_index n i = if n = 1 then 0 else i + 1;

(*the instances the dictionary line prints (§4.5): every one in the proper
  tier, the Renamed ones in the renaming tier, none for an identity*)
fun dictionary_instances ts vs =
  (case kind_of vs of
    Proper => ts
  | Renaming => map_filter (fn (t, v) => if v = Renamed then SOME t else NONE) (ts ~~ vs)
  | Identity => []);

(*the links of the linked elements, each with its name, index, level, the terms
  whose texts it carries and the theorems whose keys it carries, and given those
  texts and keys the link and its key: printing and keying are left to assemble*)
fun unprinted_links (F: finding) =
  let
    val {thy, ctxt, W, results, ...} = F;
    (*§2's entities of the dictionary: the constants of the context-side terms
      read after the context's uncheck with cases off and abbreviations not
      contracted (contracted, a locale's definition applied to its parameters
      becomes a local abbreviation, which has no record), those declared in
      Pure and HOL.HOL left out*)
    val uncheck =
      Syntax.uncheck_terms (ctxt
        |> Config.put Proof_Context.show_abbrevs false
        |> Config.put Case_Translation.show_cases false);
    val const_space = Consts.space_of (Proof_Context.consts_of ctxt);
    fun keep c =
      (case try (Name_Space.theory_name {long = true} const_space) c of
        SOME thy_name => not (member (op =) ["Pure", "HOL.HOL"] thy_name)
      | NONE => true);
    fun constants ts = Explain_Term.collect_constants keep (Context.Proof ctxt) (uncheck ts);
    val folded_constants = Syntax_Termtab.apply_unsynchronized_cache (constants o single);
    (*the constants of the dictionary's terms, in order: each once, with its key*)
    fun entities cs = distinct (op = o apply2 #2) (flat cs);
    (*what depends on the node only: the parameters and the constants of the
      instances the dictionary prints, from one computation of the verdicts*)
    val node_texts = Inttab.apply_unsynchronized_cache (fn j =>
      let
        val n = Vector.sub (#nodes W, j);
        val ps = param_frees thy (#source n);
        val vs = changes ps (#instance n);
      in
        (params_of ps (#instance n) vs, constants (dictionary_instances (#instance n) vs))
      end);
    (*the theorems a link is keyed by, each with the context it is read in: the
      fact in the context, as the closure keys it, the template in the theory, as
      the DB keys it*)
    fun named ({name, fact, index, ...}: element) level terms template link =
      let val prop = Thm.prop_of fact in
        {name = name, index = index, level = level, terms = prop :: terms,
         theorems = [(Context.Proof ctxt, Thm.transfer thy fact), (Context.Theory thy, template)],
         link = fn {text, key} => (key prop, link text (key (Thm.prop_of template)) (text prop))}
      end;
    fun link (el as {index = i, ...}: element) level
          (Note {node = j, binding, thms, ...}) =
          let val S = #source (Vector.sub (#nodes W, j)) in
            (case template_global_fact thy (template_name S binding (hd thms)) of
              SOME gths =>
                if length gths <> length thms then NONE
                else
                  let
                    val (params, instance_constants) = node_texts j;
                    (*D65: the equations Level 3 exact's pre-check applied*)
                    val rws = (case level of Level3_Exact rws => rws | _ => []);
                    val ents = entities (instance_constants :: map (folded_constants o #2) rws);
                    val terms = map #3 params @ maps (fn (t, u) => [t, u]) rws @ map #1 ents;
                  in
                    SOME (named el level terms (nth gths i)
                      (fn text => fn template => fn statement =>
                        {template = template,
                         statement = statement,
                         source = S,
                         note = (Binding.long_name_of binding, note_index (length thms) i),
                         params =
                           map (fn (v, name, t) => {verdict = v, name = name, text = text t})
                             params,
                         rewrites = map (apply2 text) rws,
                         entities = map (apfst text) ents,
                         level = level} : link))
                  end
            | NONE => NONE)
          end
      | link (el as {index = i, ...}: element) level (Block_Lemma {name, thms}) =
          SOME (named el level [] (nth thms i) (fn _ => fn template => fn statement =>
            {template = template,
             statement = statement,
             source = "",
             note = (Long_Name.base_name name, note_index (length thms) i),
             params = [], rewrites = [], entities = [], level = level}));
  in
    results |> map_filter (fn (el, Linked level, SOME t) => link el level t | _ => NONE)
  end;

(*the links with their texts and keys from the context's linking cache*)
fun assemble ctxt unprinted =
  let
    val (ts, ks) =
      entries ctxt
        (requests (text_request ctxt) (maps #terms unprinted),
         requests key_request (maps #theorems unprinted));
    val read = {text = value ts, key = value ks};
  in map (fn {link, ...} => link read) unprinted end;

fun links_of (F: finding) = assemble (#ctxt F) (unprinted_links F);

fun find_in ctxt =
  find {bottom = Named_Target.bottom_locale_of ctxt,
    edges = Locale.dest_dependencies [] (Proof_Context.theory_of ctxt)} ctxt;

(*§4.2's shared keys (B6): the links of a key, the first shown, ordered by
  Level 2, Level 3 exact and block lemmas before Level 3 approximate links,
  then the fewest qualifiers, the smallest name, the index*)
fun links ctxt =
  let
    fun rank {name, index, level, ...} =
      (((case level of Level3_Approximate => 1 | _ => 0), length (Long_Name.explode name)),
        (name, index));
    val order = prod_ord (prod_ord int_ord int_ord) (prod_ord string_ord int_ord) o apply2 rank;
  in unprinted_links (find_in ctxt) |> sort order |> assemble ctxt end;



(*** Inspection ***)

fun report (F: finding) =
  let
    val {W, names, facts, fpos, results, ...} = F;
    val hits = facts |> map (fn (name, _) => Symtab.lookup_list names name);
    val narrowed =
      facts |> filter (fn (name, _) =>
        let val hs = Symtab.lookup_list names name; val at = filter (at_position (fpos name)) hs
        in not (null at) andalso length at < length hs end) |> length;
    fun template (Note c) =
          let val n = Vector.sub (#nodes W, #node c) in
            SOME {source = #source n, note = Binding.long_name_of (#binding c), index = #k c,
              chain = #chain n, instance = #instance n}
          end
      | template (Block_Lemma {name, ...}) =
          SOME {source = "", note = name, index = 0, chain = [], instance = []};
  in
    {nodes = Vector.length (#nodes W), back_arcs = #back_arcs W,
     cuts = length (#cuts W), roots = length (#roots F),
     arcs = Inttab.dest (#incoming W) |> maps (fn (j, ps) => map (fn (p, _) => (j, p)) ps),
     name_hits = fold (fn hs => fn n => n + length hs) hits 0,
     name_hit_theorems =
       fold (fn hs => fn n => fold (fn c: candidate => fn m => m + length (#thms c)) hs n) hits 0,
     facts_with_candidate =
       results |> filter (fn ({candidates, ...}: element, _, _) => not (null candidates))
       |> map (#name o #1) |> distinct (op =) |> length,
     candidates =
       fold (fn ({candidates, ...}: element, _, _) => fn n => n + length candidates) results 0,
     narrowed = narrowed, recognised = #recognised F,
     level5_base_names = #level5_base_names F,
     elements = results |> map (fn ({name, index, ...}: element, v, t) =>
       {name = name, index = index, outcome = v,
        template = Option.mapPartial template t})}
  end;

end;
