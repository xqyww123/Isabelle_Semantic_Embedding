(*
  The retrieval closure's links (LINK_LAYER_PLAN.md §4.2, §8 step 3): every link of
  a key, in §4.2's order for shared keys (B6: Level 2, Level 3 exact and block
  lemmas before Level 3 approximate links, then the fewest qualifiers, the
  smallest name, the index), each carrying its fact's own statement printed with
  the record printer, alpha-variant facts each under its own key (D68); the
  parameters' verdicts as the closure serves them (D34, D41); and a finder failure
  degrading the context to no links (A1, §8 step 5).
*)
theory Link_Layer_Closure_Test
  imports Link_Finder_Test_Base
begin

ML \<open>
structure Link_Layer_Closure_Test =
struct

open Link_Finder_Test

fun source_note (l: Link_Finder.link) = (#source l, #1 (#note l));

(*the links are the per-element links, those of a key in B6's order among the
  linked elements whose note has a global fact, each carrying its fact's
  statement; returns the number of keys whose links differ*)
fun check_shared_keys' links_of_context label ctxt =
  let
    val links = links_of_context ctxt;
    val (F, r) = report_in ctxt label;
    val key = Universal_Key.key_of_theorem' NONE (Context.Proof ctxt);
    val per_element = Link_Finder.links_of F;
    val _ = check (label ^ ": the links are the per-element links")
      (length links = length per_element andalso subset (op =) (links, per_element)
        andalso subset (op =) (per_element, links));
    val linked =
      #elements r |> map_filter (fn e =>
        (case (#outcome e, #template e) of
          (Link_Finder.Linked level, SOME {source, note, ...}) =>
            if String.isSuffix "_axioms" note then NONE
            else
              let val fact = nth (Proof_Context.get_thms ctxt (#name e)) (#index e)
              in SOME (key fact, (#name e, #index e, level, ((source, note),
                Explain_Term.string_of_term ctxt (Thm.prop_of fact))))
              end
        | _ => NONE));
    fun rank (n, i, level, _) =
      ((if level = Link_Finder.Level3_Approximate then 1 else 0, length (Long_Name.explode n)),
       (n, i));
    val order = prod_ord (prod_ord int_ord int_ord) (prod_ord string_ord int_ord) o apply2 rank;
    val keys = distinct (op =) (map #1 links);
    val _ = keys |> List.app (fn k =>
      let
        val ls = links |> filter (fn (k', _) => k' = k)
          |> map (fn (_, l: Link_Finder.link) => (source_note l, #statement l));
        val es = linked |> filter (fn (k', _) => k' = k) |> map #2 |> sort order;
      in
        check (label ^ ": the links of " ^ (case es of (n, _, _, _) :: _ => n | [] => "?") ^
          "'s key in B6's order, each with its statement")
          (ls = map #4 es)
      end);
  in
    keys |> filter (fn k =>
      length (distinct (op =) (map_filter (fn (k', l) => if k' = k then SOME (source_note l) else NONE) links)) > 1)
    |> length
  end;

val check_shared_keys = check_shared_keys' Link_Finder.links;

end;
\<close>

context linordered_field
begin

ML \<open>
local open Link_Layer_Closure_Test in
  val shared = check_shared_keys "linordered_field" \<^context>
  val _ = check ("linordered_field: some keys are shared by facts with different links (" ^
    string_of_int shared ^ ")") (shared > 0)
end
\<close>

end

text \<open>A user locale importing two locales whose facts share a key: the
  unqualified fact's link is shown first, and between equally qualified ones the
  smaller name's.\<close>

locale LLA = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma zfoo: "f x = f x" by (rule refl)
lemma ybar: "f (f x) = f (f x)" by (rule refl)
end

locale LLC = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma afoo: "f x = f x" by (rule refl)
lemma xbar: "f (f x) = f (f x)" by (rule refl)
end

locale LLD = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma bfoo: "f x = f x" by (rule refl)
end

locale LLB = LLA f + LLD f + c: LLC f for f :: "'a \<Rightarrow> 'a"

context LLB
begin

ML \<open>
local open Link_Layer_Closure_Test
  val ctxt = \<^context>
  val links = Link_Finder.links ctxt
  val key = Universal_Key.key_of_theorem' NONE (Context.Proof ctxt)
  fun first name = AList.lookup (op =) links (key (Proof_Context.get_thm ctxt name)) |> Option.map source_note
in
  val _ = check "zfoo and c.afoo share a key"
    (key (Proof_Context.get_thm ctxt "zfoo") = key (Proof_Context.get_thm ctxt "c.afoo"))
  val _ = check "LLB: two keys are shared by facts with different links" (check_shared_keys "LLB" ctxt = 2)
  val _ = check "bfoo comes first, before zfoo (the smaller name) and c.afoo (more qualifiers)"
    (first "zfoo" = SOME ("Link_Layer_Closure_Test.LLD", "bfoo"))
  val _ = check "ybar comes first, before c.xbar (fewer qualifiers before the smaller name)"
    (first "ybar" = SOME ("Link_Layer_Closure_Test.LLA", "ybar"))
end
\<close>

end

text \<open>Two facts with one statement \<open>k 0 = k 0\<close>: \<open>s.mfoo\<close>, written through a rewrites mixin
  the edge does not carry (D21), links at Level 3 approximate, \<open>t.zfoo\<close> at Level 2.  The smaller
  name is the approximate one's, so only B6's first clause puts the Level 2 link first.\<close>

locale LLM = fixes g :: "nat \<Rightarrow> nat"
begin
definition mh where "mh x = g x"
lemma mfoo: "mh 0 = g 0" by (simp add: mh_def)
end

locale LLN = fixes g :: "nat \<Rightarrow> nat"
begin
lemma zfoo: "g 0 = g 0" by (rule refl)
end

locale LLK = fixes k :: "nat \<Rightarrow> nat"
sublocale LLK \<subseteq> s: LLM k rewrites "LLM.mh k = k" by (rule ext) (simp add: LLM.mh_def)
sublocale LLK \<subseteq> t: LLN k .

context LLK
begin

ML \<open>
local open Link_Layer_Closure_Test
  val ctxt = \<^context>
  val (_, r) = report_in ctxt "LLK"
  val key = Universal_Key.key_of_theorem' NONE (Context.Proof ctxt)
in
  val _ = check_element ctxt "LLK, the approximate link" (#elements r) "local.s.mfoo" 0
    "local.s.mfoo#0: Level 3 approximate LLM::mfoo#3 @[s] [k]"
  val _ = check "s.mfoo and t.zfoo share a key"
    (key (Proof_Context.get_thm ctxt "s.mfoo") = key (Proof_Context.get_thm ctxt "t.zfoo"))
  val _ = check "LLK: the shared key's links differ" (check_shared_keys "LLK" ctxt = 1)
  val _ = check "t.zfoo's Level 2 link comes first, before s.mfoo's approximate one (the smaller name)"
    (Option.map source_note
      (AList.lookup (op =) (Link_Finder.links ctxt) (key (Proof_Context.get_thm ctxt "s.mfoo"))) =
      SOME ("Link_Layer_Closure_Test.LLN", "zfoo"))
end
\<close>

end

text \<open>Two notes that differ only in a bound-variable name (D68): each fact keeps its own key,
  so both keys are among those the check compares with the facts' own keys and statements.\<close>

locale LLV = fixes p :: "nat \<Rightarrow> bool" assumes allp: "\<forall>n. p n"
begin
lemma vx: "\<forall>x. p x" by (rule allp)
lemma vy: "\<forall>y. p y" by (rule allp)
end

ML \<open>
local open Link_Layer_Closure_Test
  val thy = \<^theory>
  val ctxt = Named_Target.init [] (Locale.check_global thy ("LLV", Position.none)) thy
  val key = Universal_Key.key_of_theorem' NONE (Context.Proof ctxt)
  val kx = key (Proof_Context.get_thm ctxt "vx") and ky = key (Proof_Context.get_thm ctxt "vy")
  val keys = map #1 (Link_Finder.links ctxt)
in
  val _ = check "vx and vy have keys of their own" (kx <> ky)
  val _ = check "and both are among the links' keys" (subset (op =) ([kx, ky], keys))
  val _ = check "LLV: no key's links differ" (check_shared_keys "LLV" ctxt = 0)
end
\<close>

section \<open>The parameters' verdicts through the closure's links (D34, D41)\<close>

text \<open>The verdicts and their texts as \<open>Link_Finder.links\<close> serves them in a class context; the
  verdict pins themselves are in Link_Finder_Verdicts_Test.\<close>

context linordered_field
begin

ML \<open>
local open Link_Layer_Closure_Test
  val params =
    AList.lookup (op =) (Link_Finder.links \<^context>)
      (Universal_Key.key_of_theorem' NONE (Context.Proof \<^context>)
        (Proof_Context.get_thm \<^context> "sum_list.Cons"))
    |> Option.map #params
in
  val _ = check "sum_list.Cons: f and z are renamed to (+) and 0"
    (params =
      SOME [{verdict = Link_Finder.Renamed, name = "f", text = "(+)"},
            {verdict = Link_Finder.Renamed, name = "z", text = "0"}])
end
\<close>

end

section \<open>A finder failure degrades the context to no links (A1, §8 step 5)\<close>

text \<open>The pins take the degrade function, so the catch-all and the bare-handle mutants are other
  degrade functions given to the same check.  Poly/ML reports stack or heap exhaustion as a raw
  \<open>Interrupt\<close> while the thread's break flag is unset; Isabelle_Thread's capture turns it into
  \<open>Interrupt_Breakdown\<close>, a failure.  A cancellation or a timeout sets the break flag before its
  raw \<open>Interrupt\<close> arrives, so the capture turns it into \<open>Interrupt_Break\<close>: the timeout pin
  delivers that form, which a function re-raising only an already converted \<open>Interrupt_Break\<close>
  would swallow.  The next-call pin builds a \<open>Lazy\<close> over the degrade function, as
  \<open>make_links_callback\<close> does: it checks that the degrade function keeps nothing across calls
  under stock \<open>Lazy\<close>'s reset, not the callback itself (pinned in Link_Finder_Cache_Test).  The
  \<open>Interrupt_Breakdown\<close> pins write event-log records (D69, pinned by \<open>check_record\<close>), so the
  section refuses to run unless ISABELLE_EVENT_LOG_DIR names a scratch directory.\<close>

ML \<open>
structure Link_Layer_Degrade_Test =
struct

open Link_Finder_Test

val event_log = scratch_event_log ()

type links = (Universal_Key.universal_key * Link_Finder.link) list

fun raising exn (_: Proof.context) : links = raise exn

fun check_degrade (degrade : (Proof.context -> links) -> Proof.context -> links) ctxt =
  let
    fun degrades label exn =
      check ("A1: a finder raising " ^ label ^ " degrades to no links")
        (case Exn.capture (degrade (raising exn)) ctxt of Exn.Res [] => true | _ => false)
    val _ = degrades "ERROR" (ERROR "a finder bug")
    val _ = degrades "Fail" (Fail "a broken invariant")
    val _ = degrades "Interrupt_Breakdown" Exn.Interrupt_Breakdown
    val _ = degrades "a raw Interrupt with the break flag unset" Thread.Thread.Interrupt
    val _ = check "A1: a finder raising Interrupt_Break propagates it"
      (case Exn.capture (degrade (raising Exn.Interrupt_Break)) ctxt of
        Exn.Exn exn => Exn.is_interrupt_break exn
      | Exn.Res _ => false)
    fun sleeping (_: Proof.context) : links = (OS.Process.sleep (seconds 30.0); [])
    val _ = check "A1: a finder stopped by a timeout propagates the timeout"
      (case Exn.capture (Timeout.apply (seconds 0.2) (degrade sleeping)) ctxt of
        Exn.Exn (Timeout.TIMEOUT _) => true
      | _ => false)
    val expected = Link_Finder.links ctxt
    val calls = Unsynchronized.ref 0
    fun interrupted_once ctxt =
      (calls := ! calls + 1;
       if ! calls = 1 then raise Exn.Interrupt_Break else Link_Finder.links ctxt)
    val links = Lazy.lazy (fn () => degrade interrupted_once ctxt)
    val _ = check "A1: after an interrupted first call, the next call returns the links"
      (Exn.is_interrupt_exn (Exn.capture Lazy.force links)
        andalso Lazy.force links = expected andalso not (null expected))
    val _ = check "A1: a finder that succeeds is unchanged"
      (degrade Link_Finder.links ctxt = expected)
  in () end

(*D69: the number of this thread's event-log records of the links callback*)
fun links_records () =
  let
    val category = Path.append event_log (Path.basic "exception")
    val suffix = "-" ^ string_of_int (ML_Pid.get ()) ^ ".xml"
    val files =
      if File.is_dir category then filter (String.isSuffix suffix) (File.read_dir category)
      else []
    val here = [("site", "Semantic_Store.links"),
      ("thread", Isabelle_Thread.print (Isabelle_Thread.self ()))]
    fun ours (XML.Elem (("record", props), _)) =
          forall (fn (k, v) => Properties.get props k = SOME v) here
      | ours _ = false
  in length (filter ours (maps (Event_Log.read_file o Path.append category o Path.basic) files)) end

fun check_record (degrade : (Proof.context -> links) -> Proof.context -> links) ctxt =
  let
    fun after exn = let val _ = Exn.capture (degrade (raising exn)) ctxt in links_records () end
    val n = links_records ()
    val _ = check "D69: a finder raising ERROR writes no event-log record"
      (after (ERROR "a finder bug") = n)
  in
    check "D69: a finder raising Interrupt_Breakdown writes one event-log record"
      (after Exn.Interrupt_Breakdown = n + 1)
  end

end
\<close>

context LLB
begin

ML \<open>Link_Layer_Degrade_Test.check_degrade Semantic_Store.degrade_links \<^context>\<close>
ML \<open>Link_Layer_Degrade_Test.check_record Semantic_Store.degrade_links \<^context>\<close>

end

end
