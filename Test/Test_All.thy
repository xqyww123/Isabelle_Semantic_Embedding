theory Test_All
  imports Semantic_Embedding.Semantic_Embedding Main
begin

text \<open>Whole-pass digest coverage, cost and determinism over the Main cone.

  The digest library's own enumeration layer was deleted when invalidation.ML
  became semantic_digest.ML (CHECK_OUTDATE_PLAN.md §7): production entities come
  from the interpretation pipeline's enumeration.  This pass therefore draws its
  entities the same way the pipeline does -- Theory_Structure's constant and
  theorem getters under each cone node's own context, with the same Infra_Filter
  predicates -- and runs Semantic_Digest.semantics_of over all of them.  The
  name-addressed kinds beyond constants (types, classes, locales) are covered by
  the targeted probes in Test_Sensitivity; this file is about volume: nothing
  crashes, resolution coverage holds, the pass is deterministic, and the cost
  stays in budget.\<close>

ML \<open>
val main_thy = Thy_Info.get_theory "Main";

(* Mirror of semantic_store.ML enumerate_entries steps 1-2 for the two dominant
   kinds: per cone node, constants (theory-attributed) and static theorems, both
   through Infra_Filter. *)
fun entities_of thy =
  let
    val context = Context.Theory thy
    val {is_infra_const, is_infra_thm, ...} = Infra_Filter.gen_infra_filters context
    val consts =
      Theory_Structure.get_constants_with_positions context
      |> map_filter (fn (n, _) =>
           if is_infra_const n then NONE else SOME (Universal_Key.Constant n))
    val thms =
      Theory_Structure.get_theorems_with_positions context
      |> filter (fn (name, _, _, thm, _) => not (is_infra_thm (name, thm)))
      |> map (fn (_, _, _, thm, _) => Universal_Key.Theorem thm)
  in consts @ thms end;

val t0 = Timing.start ();
val cone = Semantic_Store.collect_cone [main_thy];
val all = maps entities_of cone;
val _ = writeln ("enumeration (pipeline getters): " ^ Timing.message (Timing.result t0) ^
                 ", " ^ string_of_int (length cone) ^ " theories, " ^
                 string_of_int (length all) ^ " entities");

val t1 = Timing.start ();
val env = Semantic_Digest.make_env main_thy;
val _ = writeln ("make_env: " ^ Timing.message (Timing.result t1));
\<close>

subsection \<open>WIP boundary: Resources.loaded_theory is the definition\<close>

ML \<open>
(* CHECK_OUTDATE_PLAN.md §2 / step 5: Theory_Hash.hash_of forks on
   Resources.loaded_theory -- false means WIP (name hash, LSB = 1), and the
   incremental-invalidation fields exist exactly for that side.

   MEASURED BOUNDARY FACT (2026-07-28): under `isabelle build`, the session's
   OWN theories are already registered as loaded while they are being
   processed -- so a batch-built theory takes the PERSISTENT branch.  That is
   the wanted behavior (a build's output is heap content, content-addressed);
   the WIP side of the boundary appears only for interactively loaded
   theories (jEdit buffers, REPL scratch files), which is exercised at
   runtime by the Scratch_*Verify theories.  This probe therefore checks the
   heap-ancestor side unconditionally and the WIP bit only when this theory
   is actually on the WIP side (interactive evaluation) -- also because the
   persistent branch's hash would launch the Python host mid-build. *)
val _ =
  let
    val self = Context.theory_long_name \<^theory>
    val ok_loaded = Resources.loaded_theory (Context.theory_long_name main_thy)
    val self_loaded = Resources.loaded_theory self
    val ok_bit =
      self_loaded orelse
      not (Theory_Hash.is_persistent (Theory_Hash.hash_of \<^theory>))
  in
    if ok_loaded andalso ok_bit
    then writeln ("WIP boundary probe: OK (Main loaded; this theory " ^
                  (if self_loaded then "batch-loaded, persistent side"
                   else "interactive, WIP-keyed") ^ ")")
    else error ("WIP boundary probe failed (Main loaded: " ^
               Bool.toString ok_loaded ^ ", self loaded: " ^
               Bool.toString self_loaded ^ ", WIP bit ok: " ^
               Bool.toString ok_bit ^ "; self = " ^ self ^ ")")
  end
\<close>

subsection \<open>Send order: entry serials, not source lines (CHECK_OUTDATE_PLAN \<section>5)\<close>

ML \<open>
(* The acceptance pair from the plan: `rel_fun` (a constant) must sort before
   `rel_fun_def` (its defining fact).  Line order got this wrong -- generated
   bindings fall back to their command's first line -- which is why the send
   order's primary key is the Name_Space entry serial. *)
val _ =
  let
    val fact_space = Facts.space_of (Global_Theory.facts_of main_thy)
    val const_space = Consts.space_of (Sign.consts_of main_thy)
    fun serial_in space n = #serial (Name_Space.the_entry space n)
    val s_const = serial_in const_space "BNF_Def.rel_fun"
    val s_def = serial_in fact_space "BNF_Def.rel_fun_def"
  in
    if s_const < s_def
    then writeln ("send order: rel_fun (" ^ string_of_int s_const ^
                  ") < rel_fun_def (" ^ string_of_int s_def ^ ") OK")
    else error "send order violated: rel_fun_def would be sent before rel_fun"
  end
\<close>

subsection \<open>Whole pass: coverage, cost, determinism\<close>

ML \<open>
let
  fun run () = map (fn e => Semantic_Digest.semantics_of env e) all
  val t = Timing.start ()
  val r1 = run ()
  val res = Timing.result t
  val r2 = run ()
  val resolved = filter is_some r1
  val edges = fold (fn SOME (_, ds) => (fn a => a + length ds) | NONE => I) r1 0
  val with_digest = fold (fn SOME (SOME _, _) => (fn a => a + 1) | _ => I) r1 0
  val n = length all
  val n_res = length resolved
in
  writeln ("resolved: " ^ string_of_int n_res ^ " / " ^ string_of_int n ^
           "  (with digest: " ^ string_of_int with_digest ^ ")");
  writeln ("  " ^ Timing.message res);
  writeln ("  dep edges: " ^ string_of_int edges);
  if r1 = r2 then writeln "  determinism: OK"
  else error "Test_All: two identical passes produced different results";
  (* Theorem-alike entities resolve unconditionally (deps from the thm value
     itself), so coverage can only be lost on constants; anything under 95%
     means a resolution channel broke. *)
  if n_res * 100 >= n * 95 then ()
  else error ("Test_All: resolution coverage collapsed: " ^
              string_of_int n_res ^ " / " ^ string_of_int n);
  if edges > 0 andalso with_digest > 0 then ()
  else error "Test_All: no dependency edges or no digests at all"
end
\<close>

subsection \<open>Dry-run metering: a Proof root's uks are not double-counted (R2)\<close>

definition r2_dedup_probe :: nat where "r2_dedup_probe = 0"

ML \<open>
(* The dry run is the system's one workload metering (the quote must equal the
   live work).  A Proof root riding with its own background theory must not
   re-count that theory's entities: the proof-context enumeration is
   subtractive only for static theorems, so constants etc. re-enumerate with
   identical uks -- the live run pays once via the cache filter, and since R2
   the dry run's proof channel is filtered against the theory channel's
   enumerated uks.  r2_dedup_probe above is certainly uncached, so before the
   fix the two quotes below differed by at least one. *)
let
  val _ = Remote_Procedure_Calling.load ["Isabelle_Semantic_Embedding"]
  val thy = \<^theory>
  val ctxt = \<^context>
  (* Vacuity guard 3 -- the discriminator itself (round-2 implementation
     review): the dedup is only observable on an UNCACHED uk enumerated by
     both channels.  r2_dedup_probe is a constant of THIS theory, so both
     channels enumerate it; assert it is really absent from the store.
     NB the two quotes below are separate RPC rounds against the shared
     store: this probe follows the test-exclusivity discipline -- never run
     it concurrently with a live interpretation. *)
  val _ =
    (case Semantic_Store.query_semantics (Context.Theory thy)
            (Universal_Key.Constant "Test_All.r2_dedup_probe") false of
      NONE => ()
    | SOME _ => error "Test_All: probe vacuous -- r2_dedup_probe already cached")
  val (works, n_thy) = Semantic_Store.dry_run false [Context.Theory thy]
  val (_, n_both) =
    Semantic_Store.dry_run false [Context.Theory thy, Context.Proof ctxt]
in
  writeln ("dry-run metering: theory-only = " ^ string_of_int n_thy ^
           ", theory+proof = " ^ string_of_int n_both);
  (* Vacuity guards (the S-suite lesson: an assertion satisfiable through an
     unrelated path proves nothing).  The discriminating precondition is that
     the CURRENT theory is in the work set with something uncached in it. *)
  if member (op =) works (Context.theory_long_name thy) then ()
  else error "Test_All: probe vacuous -- current theory not in the work set";
  if n_thy > 0 then ()
  else error "Test_All: probe vacuous -- nothing uncached (r2_dedup_probe should be)";
  if n_both = n_thy then writeln "  proof-channel dedup: OK"
  else error ("Test_All: the quote drifts when the Proof root rides along: " ^
              string_of_int n_thy ^ " vs " ^ string_of_int n_both)
end
\<close>

end
