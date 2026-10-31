(*
  Link finder cases in block and proof contexts (LINK_LAYER_PLAN.md §4.3, §4.1,
  §7): the two constructions of §3.4, block-level lemmas, a nested block's lemma
  exported to its target, a lemma of an unnamed block, Level 0, proof
  interpretations (Level 5), two parameters receiving the same variable (A2), and
  an inaccessible template (D36).
*)
theory Link_Finder_Cons_Blocks
  imports Link_Finder_Test_Base
begin

section \<open>Construction A: a block interpretation of another locale under an edge's prefix\<close>

text \<open>The interpretation wrote \<open>q.ax\<close> last, at its own position, which no note's binding
  carries: the registration predicate (D52) recognises the fact, Level 5 brings the root
  registration in, and its candidates are the name hits under it.\<close>

locale M6 = fixes c :: nat assumes ax: "c \<le> c"
locale N6 = fixes d :: nat assumes ax: "d \<le> d + 0"
locale L6 = fixes n :: nat

sublocale L6 \<subseteq> q: M6 n by unfold_locales simp

context L6 begin
interpretation q: N6 n by unfold_locales simp
ML \<open>
local open Link_Finder_Test
  val (_, r) = report_in \<^context> "construction A"
in
  val _ = check_element \<^context> "construction A" (#elements r) "local.q.ax" 0
    "local.q.ax#0: Level 2 N6::ax#1 @[q] [n]"
end
\<close>
end

text \<open>Without its assumption, \<open>N6'\<close> notes no \<open>N6'_axioms\<close>, so \<open>q.ax\<close> is the interpretation's
  only fact and has a name hit through the edge: here only the registration predicate brings
  the root registration in (a trigger on facts without a name hit leaves \<open>q.ax\<close> no candidate).
  In construction A the fact \<open>q.N6_axioms\<close>, which has no name hit, brings it in too.\<close>

locale N6' = fixes d :: nat
begin
lemma ax: "d \<le> d + 0" by simp
end
locale L6' = fixes n :: nat

sublocale L6' \<subseteq> q: M6 n by unfold_locales simp

context L6' begin
interpretation q: N6' n .
ML \<open>
local open Link_Finder_Test
  val (_, r) = report_in \<^context> "construction A, no axioms"
in
  val _ = check_element \<^context> "construction A, no axioms" (#elements r) "local.q.ax" 0
    "local.q.ax#0: Level 2 N6'::ax#0 @[q] [n]"
end
\<close>
end

section \<open>Construction B: two edges with one prefix, the true source carrying a rewrites mixin\<close>

locale A7 = fixes f :: "nat \<Rightarrow> nat" assumes foo: "f 0 = 0"
locale B7 = fixes g :: "nat \<Rightarrow> nat"
begin
definition h where "h x = g x"
lemma foo: "h 0 = g 0" by (simp add: h_def)
end
locale L7 = fixes k :: "nat \<Rightarrow> nat" assumes k0: "k 0 = 0"

sublocale L7 \<subseteq> r: A7 k by unfold_locales (rule k0)
sublocale L7 \<subseteq> r: B7 k rewrites "B7.h k = k"
  by (rule ext) (simp add: B7.h_def)

text \<open>Isabelle activates B7's edge last, so B7's note wrote \<open>r.foo\<close> (\<open>k 0 = k 0\<close>, after the
  mixin).  The position rule, a filter (D37), links the fact to its template B7.foo; ordered
  only by the order of trial, the approximate variant would take the closer A7.foo
  (\<open>k 0 = 0\<close>, distance 0 against 1).\<close>

ML \<open>
local open Link_Finder_Test
  val (ctxt, _, r) = report \<^theory> "L7"
in
  val _ = check_element ctxt "construction B" (#elements r) "local.r.foo" 0 "local.r.foo#0: Level 3 approximate B7::foo#3 @[r] [k]"
end
\<close>

section \<open>Block-level lemmas and a nested block's lemma\<close>

locale LB = fixes f :: "'a \<Rightarrow> 'a" assumes fid: "f (f x) = f (f x)"

context LB
begin

lemma blk: "f x = f x" by simp

ML \<open>
local open Link_Finder_Test
  val ctxt = \<^context>
  val (_, r) = report_in ctxt "block"
  val thy = Proof_Context.theory_of ctxt
  val lk = Link_Finder.links ctxt
  val key = Universal_Key.key_of_theorem' NONE (Context.Proof ctxt)
in
  val _ = check_element ctxt "block-level lemma" (#elements r) "local.blk" 0
    "local.blk#0: Level 2 LB::blk#2 @[] [f]"
  val _ =
    (case AList.lookup (op =) lk (key (Proof_Context.get_thm ctxt "blk")) of
      SOME (l: Link_Finder.link) =>
        (check "the block-level lemma's link has the template LB.blk"
          (#template l = Universal_Key.key_of_theorem' NONE (Context.Theory thy)
            (Global_Theory.get_thm thy "Link_Finder_Cons_Blocks.LB.blk"));
         check "the block-level lemma's link is an identity" (kind l = Link_Finder.Identity))
    | NONE => fail "no link for the block-level lemma")
end
\<close>

context
  fixes z :: 'a
  assumes zz: "f z = z"
begin

lemma zlem: "f (f z) = z" using zz by simp

ML \<open>
local open Link_Finder_Test
  val (_, r) = report_in \<^context> "nested block"
in
  val _ = check_element \<^context> "nested block's lemma, exported to its target" (#elements r) "local.zlem" 0
    "local.zlem#0: Level 2 LB::zlem#3 @[] [f]"
  val _ = check_element \<^context> "outer block's lemma" (#elements r) "local.blk" 0
    "local.blk#0: Level 2 LB::blk#2 @[] [f]"
end
\<close>

end

end

section \<open>A lemma of an unnamed theory-level block\<close>

context
  fixes u :: nat
  assumes ua: "0 < u"
begin

lemma ulem: "1 \<le> u" using ua by simp

ML \<open>
local open Link_Finder_Test
  val (_, r) = report_in \<^context> "unnamed block"
in
  val _ = check_element \<^context> "unnamed block's lemma" (#elements r) "local.ulem" 0
    "local.ulem#0: Level 2 ::Link_Finder_Cons_Blocks.ulem#0 @[] []"
end
\<close>

end

section \<open>Level 0\<close>

lemma (in LB)
  assumes blk: "f b = f b"
  shows True
proof -
  have fid: "f (f a) = f (f a)" by simp
  note other = blk
  ML_val \<open>
    local open Link_Finder_Test
      val (_, r) = report_in \<^context> "Level 0"
      fun V name = outcome_string (#outcome (the_element (#elements r) name 0))
    in
      val _ = check "a lemma's assumes, a have and a note rebinding names are Level 0"
        (map V ["local.blk", "local.fid", "local.other"] = ["Level 0", "Level 0", "Level 0"])
    end
  \<close>
  show ?thesis by simp
qed

lemma (in LB) True
proof -
  note again = fid
  ML_val \<open>
    local open Link_Finder_Test
      val (_, r) = report_in \<^context> "Level 0, re-noted"
      fun V name = outcome_string (#outcome (the_element (#elements r) name 0))
    in
      val _ = check "an activated fact the proof re-noted under another name passes Level 0"
        (map V ["local.fid", "local.again"] = ["Level 2", "Level 0"])
    end
  \<close>
  show ?thesis by simp
qed

section \<open>Proof interpretations: Level 5 and root registrations\<close>

locale LR = fixes r :: "'a \<Rightarrow> 'a \<Rightarrow> bool" assumes rr: "r x x"
begin
lemma lr_note: "r y y" by (rule rr)
end

lemma "True"
proof -
  interpret p: LR "\<lambda>x y. (x::nat) = y" by unfold_locales simp
  fix c :: nat
  interpret q: LR "\<lambda>x y. c = c" by unfold_locales simp
  ML_val \<open>
    local open Link_Finder_Test
      val ctxt = \<^context>
      val (_, r) = report_in ctxt "proof interpret"
      val links = Link_Finder.links ctxt
      fun link name = AList.lookup (op =) links
        (Universal_Key.key_of_theorem' NONE (Context.Proof ctxt) (Proof_Context.get_thm ctxt name))
    in
      val _ = check_element ctxt "proof interpret" (#elements r) "local.p.lr_note" 0
        "local.p.lr_note#0: Level 2 LR::lr_note#2 @[p] [(=)]"
      val _ = check_element ctxt "proof interpret over a fix" (#elements r) "local.q.lr_note" 0
        "local.q.lr_note#0: Level 2 LR::lr_note#2 @[q] [\<lambda>x y. c = c]"
      val _ =
        (case (link "p.lr_note", link "q.lr_note") of
          (SOME (lp: Link_Finder.link), SOME (lq: Link_Finder.link)) =>
            check "links of proof interpretations: proper"
              (kind lp = Link_Finder.Proper andalso kind lq = Link_Finder.Proper)
        | _ => fail "no link for a proof interpretation's fact")
    end
  \<close>
  show ?thesis by simp
qed

locale LQ = fixes s :: "'a \<Rightarrow> 'a \<Rightarrow> bool" assumes ss: "s x x"

context LQ
begin

interpretation p: LR "\<lambda>x y. s y x" by unfold_locales (rule ss)

ML \<open>
local open Link_Finder_Test
  val ctxt = \<^context>
  val (_, r) = report_in ctxt "block interpretation"
in
  val _ = check_element ctxt "block interpretation" (#elements r) "local.p.lr_note" 0
    "local.p.lr_note#0: Level 2 LR::lr_note#2 @[p] [\<lambda>x y. s y x]"
end
\<close>

end

section \<open>Two parameters receiving the same variable (A2)\<close>

text \<open>A parameter that receives a variable another parameter also receives is Instantiated,
  unless the variable is its own name's (D41, A2): \<open>a, b \<mapsto> c, c\<close> instantiates both;
  \<open>a, b \<mapsto> a, a\<close> keeps \<open>a\<close>, although its type changes from \<open>'a\<close> to \<open>nat\<close>, and instantiates
  \<open>b\<close>.  Both links are proper and print every parameter.\<close>

locale Two = fixes a b :: 'a
begin
lemma two: "a = a \<and> b = b" by simp
end

locale One = fixes c :: 'a
sublocale One \<subseteq> t: Two c c .

locale One_a = fixes a :: nat
sublocale One_a \<subseteq> u: Two a a .

ML \<open>
local open Link_Finder_Test
  fun params loc =
    let val (_, F, _) = report \<^theory> loc
    in map (fn (_, l: Link_Finder.link) => (kind l, #params l)) (Link_Finder.links_of F) end
  val I = Link_Finder.Instantiated and U = Link_Finder.Unchanged
in
  val _ = check_all "A2"
   [("c, c: a and b Instantiated, proper", fn () =>
      params "One" =
        [(Link_Finder.Proper, [{verdict = I, name = "a", text = "c"}, {verdict = I, name = "b", text = "c"}])]),
    ("a, a with a new type: a Unchanged, b Instantiated, proper", fn () =>
      params "One_a" =
        [(Link_Finder.Proper, [{verdict = U, name = "a", text = "a"}, {verdict = I, name = "b", text = "a"}])])]
end
\<close>

section \<open>The template's global name and Locale_Instance.detect on top of Link_Finder\<close>

text \<open>A definitional note carries no name hint; its global fact is named after the theory that
  defined it, which need not be the locale's (\<open>Orderings.ord\<close>'s \<open>arg_min_def\<close> is
  \<open>Lattices_Big.ord.arg_min_def\<close>).\<close>

locale LD = fixes d :: "nat \<Rightarrow> nat"
begin
definition dd where "dd x = d (d x)"
end

interpretation qd: LD Suc .

ML \<open>
local open Link_Finder_Test
  val thy = \<^theory>
  val ord = "Orderings.ord"
  val (b, th) =
    Locale.locale_notes thy ord |> maps #2
    |> get_first (fn ((b, _), gs) => if Binding.name_of b = "arg_min_def" then SOME (b, hd (maps #1 gs)) else NONE)
    |> the
  val name = Link_Finder.template_name ord b th
  val _ = check ("the template's global name of ord's arg_min_def: " ^ name)
    (name = "Lattices_Big.ord.arg_min_def" andalso can (Global_Theory.get_thms thy) name)
  val fact = "Link_Finder_Cons_Blocks.qd.dd_def"
  val uk = Universal_Key.key_of_theorem' NONE (Context.Theory thy) (Global_Theory.get_thm thy fact)
  val provenances = hd (Locale_Instance.detect thy [(fact, uk)])
in
  val _ = check "Locale_Instance.detect names the template LD.dd_def and finds it"
    (exists (fn (p: Locale_Instance.provenance) =>
      #template_name p = "Link_Finder_Cons_Blocks.LD.dd_def" andalso is_some (#template_thm p)) provenances)
end
\<close>

section \<open>D36: an inaccessible template is not a template\<close>

text \<open>A template whose global fact is hidden or concealed (the enumeration's test) gives the
  fact no link, though the ladder's outcome stands, and gives a provenance of
  Locale_Instance.detect no template theorem.  A concealed note's local facts are concealed too,
  so only the hidden case reaches the finder.\<close>

locale LH = fixes h :: "nat \<Rightarrow> nat"
begin
lemma lh_hidden: "h x = h x" by (rule refl)
lemma lh_shown: "h (h x) = h (h x)" by (rule refl)
local_setup \<open>snd o Local_Theory.note
  ((Binding.concealed \<^binding>\<open>lh_concealed\<close>, []), [@{thm refl[of "h (h (h 0))"]}])\<close>
end

hide_fact LH.lh_hidden

locale LHI = fixes k :: "nat \<Rightarrow> nat"
sublocale LHI \<subseteq> p: LH "\<lambda>x. k (k x)" .

interpretation qh: LH Suc .

ML \<open>
local open Link_Finder_Test
  val thy = \<^theory>
  fun template name = "Link_Finder_Cons_Blocks.LH." ^ name
  val exists_global = is_some o Facts.lookup (Context.Theory thy) (Global_Theory.facts_of thy) o template
  val _ = check "the three templates' global facts exist"
    (forall exists_global ["lh_hidden", "lh_shown", "lh_concealed"])
  val _ = check "template_global_fact: lh_hidden and lh_concealed are not accessible, lh_shown is"
    (map (is_some o Link_Finder.template_global_fact thy o template) ["lh_hidden", "lh_shown", "lh_concealed"] =
      [false, true, false])
  val (ctxt, F, r) = report thy "LHI"
  val _ = check_element ctxt "hidden template" (#elements r) "local.p.lh_hidden" 0
    "local.p.lh_hidden#0: Level 2 LH::lh_hidden#0 @[p] [\<lambda>x. k (k x)]"
  val _ = check "LHI: one link, from lh_shown"
    (map (#note o #2) (Link_Finder.links_of F) = [("lh_shown", 0)])
  fun detected name =
    let
      val fact = "Link_Finder_Cons_Blocks.qh." ^ name
      val uk = Universal_Key.key_of_theorem' NONE (Context.Theory thy) (Global_Theory.get_thm thy fact)
    in
      hd (Locale_Instance.detect thy [(fact, uk)])
      |> filter (fn (p: Locale_Instance.provenance) => #template_name p = template name)
    end
  fun template_thm name = map (is_some o #template_thm) (detected name)
in
  val _ = check "detect: no template theorem for the hidden template"
    (template_thm "lh_hidden" = [false])
  val _ = check "detect: no template theorem for the concealed template"
    (template_thm "lh_concealed" = [false])
  val _ = check "detect: a template theorem for the accessible template"
    (template_thm "lh_shown" = [true])
end
\<close>

end
