(*
  Helpers shared by the link finder tests (LINK_LAYER_PLAN.md §7): the finder
  on Locale.init of a locale, run with the dependency edges in serial and in
  reverse order, the two runs required to agree, and lookups into its report.
*)
theory Link_Finder_Test_Base
  imports Semantic_Embedding.Semantic_Embedding
begin

ML \<open>
structure Link_Finder_Test =
struct

fun fail msg = error ("Link_Finder_Test: " ^ msg);
fun check msg b = if b then () else fail msg;

(*D69: pins that make the finder fail with Interrupt_Breakdown write event-log records,
  so they run only with ISABELLE_EVENT_LOG_DIR naming a scratch directory*)
fun scratch_event_log () =
  (case (OS.Process.getEnv "ISABELLE_EVENT_LOG_DIR", Event_Log.log_dir ()) of
    (SOME _, SOME dir) => dir
  | _ => fail "run with ISABELLE_EVENT_LOG_DIR set to a scratch directory (D69)");

val string_of_term = Explain_Term.string_of_term;

type element =
  {name: string, index: int, outcome: Link_Finder.outcome,
   template: {source: string, note: string, index: int, chain: string list, instance: term list} option};

fun find_in thy loc rev_order =
  let
    val ctxt = Locale.init loc thy;
    val edges = Locale.dest_dependencies [] thy |> rev_order ? rev;
  in (ctxt, Link_Finder.find {bottom = SOME loc, edges = edges} ctxt) end;

fun outcome_string Link_Finder.Rebound = "Level 0"
  | outcome_string Link_Finder.No_Candidate = "no candidate"
  | outcome_string (Link_Finder.Linked Link_Finder.Level2) = "Level 2"
  | outcome_string (Link_Finder.Linked (Link_Finder.Level3_Exact _)) = "Level 3 exact"
  | outcome_string (Link_Finder.Linked Link_Finder.Level3_Approximate) = "Level 3 approximate"
  | outcome_string Link_Finder.No_Link = "no link";

fun element_string ctxt ({name, index, outcome, template}: element) =
  String.concat [name, "#", string_of_int index, ": ", outcome_string outcome,
    (case template of
      SOME {source, note, index = k, chain, instance} =>
        String.concat [" ", Long_Name.base_name source, "::", note, "#", string_of_int k, " @[",
          space_implode "." chain, "] [", commas (map (string_of_term ctxt) instance), "]"]
    | NONE => "")];

(*the report of a context, with a check that both edge orders give the same
  nodes, back arcs, cuts and elements*)
fun report_of ctxt label F F' =
  let
    val r = Link_Finder.report F and r' = Link_Finder.report F';
    val lines = map (element_string ctxt) (#elements r);
    val _ = check (label ^ ": serial and reverse edge order agree")
      (lines = map (element_string ctxt) (#elements r') andalso
        #nodes r = #nodes r' andalso #back_arcs r = #back_arcs r' andalso #cuts r = #cuts r');
  in r end;

fun report thy loc0 =
  let
    val loc = Locale.check_global thy (loc0, Position.none);
    val (ctxt, F) = find_in thy loc false;
    val (_, F') = find_in thy loc true;
  in (ctxt, F, report_of ctxt loc F F') end;

(*the same for a block or proof context, its bottom locale read from it*)
fun report_in ctxt label =
  let
    val thy = Proof_Context.theory_of ctxt;
    val edges = Locale.dest_dependencies [] thy;
    fun run es = Link_Finder.find {bottom = Named_Target.bottom_locale_of ctxt, edges = es} ctxt;
    val F = run edges;
  in (F, report_of ctxt label F (run (rev edges))) end;

(*levels: Level 0, no candidate, Level 2, Level 3 exact, approximate, no link*)
fun levels (es: element list) =
  let
    fun slot Link_Finder.Rebound = 0
      | slot Link_Finder.No_Candidate = 1
      | slot (Link_Finder.Linked Link_Finder.Level2) = 2
      | slot (Link_Finder.Linked (Link_Finder.Level3_Exact _)) = 3
      | slot (Link_Finder.Linked Link_Finder.Level3_Approximate) = 4
      | slot Link_Finder.No_Link = 5;
  in map (fn k => length (filter (fn (e: element) => slot (#outcome e) = k) es)) (0 upto 5) end;

fun the_element (es: element list) name i =
  (case find_first (fn (e: element) => #name e = name andalso #index e = i) es of
    SOME e => e
  | NONE => fail ("no element " ^ name ^ "#" ^ string_of_int i));

(*some element is linked to a note of a locale with the base name S*)
fun check_linked label (es: element list) S =
  check (label ^ ": no element is linked to a note of " ^ S)
    (exists (fn ({outcome = Link_Finder.Linked _, template = SOME {source, ...}, ...}: element) =>
                  Long_Name.base_name source = S
              | _ => false) es);

(*a locale's report in both edge orders, and a link into each of the locales Ss*)
fun linked thy loc Ss =
  let val (_, _, r) = report thy loc in List.app (check_linked loc (#elements r)) Ss end;

(*a finding's links as sorted lines, (fact, source, note, index, level) and
  (fact, source, note, index, rewrites), the fact named by its key's 15-byte
  payload: the key's 16-byte prefix hashes theory long names and so differs
  between environments*)
fun link_lines links =
  let
    fun hex v =
      Word8Vector.foldr (fn (b, acc) =>
        let val s = Word8.toString b in (if size s = 1 then "0" ^ s else s) ^ acc end) "" v;
    fun level Link_Finder.Level2 = "2" | level (Link_Finder.Level3_Exact _) = "3e"
      | level Link_Finder.Level3_Approximate = "3a";
    fun note (k, l: Link_Finder.link) =
      [hex (the (Universal_Key.theorem_key_digest k)), #source l, #1 (#note l),
       string_of_int (#2 (#note l))];
  in
    (links |> map (fn kl => space_implode "\t" (note kl @ [level (#level (#2 kl))]))
     |> sort_strings,
     links |> map (fn kl => space_implode "\t" (note kl @
       [space_implode "|" (map (fn (a, b) => a ^ "^" ^ b) (#rewrites (#2 kl)))]))
     |> sort_strings)
  end;

(*the pins of the links and rewrites (since D65 the equations Level 3 exact applied):
  (links, SHA1 of the link lines, links carrying rewrites, rewrites, SHA1 of the rewrite
  lines)*)
fun links_digest F =
  let
    val links = Link_Finder.links_of F;
    val (link_text, rewrite_text) = link_lines links;
    val ls = map #2 links;
    fun digest lines = SHA1.rep (SHA1.digest (cat_lines lines));
  in
    (length ls, digest link_text, length (filter (fn l => not (null (#rewrites l))) ls),
     fold (fn l => fn n => n + length (#rewrites l)) ls 0, digest rewrite_text)
  end;

fun check_links_digest label F expected =
  let
    val found = links_digest F;
    fun show (n, d, m, k, e) =
      "(" ^ commas [string_of_int n, d, string_of_int m, string_of_int k, e] ^ ")";
  in
    check (label ^ ": the links and rewrites: found " ^ show found ^
      ", expected " ^ show expected) (found = expected)
  end;

(*pins evaluated together, an ERROR inside one counted as its failure, with its
  message: one error lists every pin that fails, so that one mutant run shows
  them all*)
fun check_all label (pins: (string * (unit -> bool)) list) =
  let
    fun failure (name, f) =
      (if f () then NONE else SOME name) handle ERROR msg => SOME (name ^ " (" ^ msg ^ ")");
    val results = map (fn pin => (#1 pin, failure pin)) pins;
    val fails = map_filter #2 results;
    val holds = results |> filter (is_none o #2) |> map #1;
  in check (label ^ ": FAILS " ^ commas fails ^ "; holds " ^ commas holds) (null fails) end;

(*a link's kind, a function of its verdicts (§2)*)
fun kind (l: Link_Finder.link) = Link_Finder.kind_of (map #verdict (#params l));

fun check_element ctxt label (es: element list) name i expected =
  let val s = element_string ctxt (the_element es name i)
  in check (label ^ ": expected " ^ quote expected ^ ", found " ^ quote s) (s = expected) end;

end;
\<close>

end
