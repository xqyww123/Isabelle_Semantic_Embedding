(*
  Link finder constructions (LINK_LAYER_PLAN.md §7, walk_team_synthesis_final.md
  §9.3): the qualified diamond UB/UB2, the diamond cX/cXr, the converse
  vConv/vConv2 (round-3 critics and judge), and C2a/C3a (round-3 critic of
  "fix"); each locale's report in both edge orders, with the locales its links
  must reach; a self-sublocale whose instance collapses by beta (§7's route
  pins).
*)
theory Link_Finder_Cons_Paths
  imports Link_Finder_Test_Base
begin

locale S0 = fixes f :: "'a \<Rightarrow> 'a \<Rightarrow> 'a" assumes comm: "f x y = f y x"
begin
lemma comm_twice: "f (f x y) z = f z (f x y)" by (rule comm)
end
locale Ub = fixes g :: "'a \<Rightarrow> 'a \<Rightarrow> 'a" assumes gcomm: "g x y = g y x"
locale Ua = fixes g :: "'a \<Rightarrow> 'a \<Rightarrow> 'a" assumes gcomm: "g x y = g y x"
sublocale Ub \<subseteq> rb: S0 "\<lambda>x y. g y x" by unfold_locales (rule gcomm)
sublocale Ua \<subseteq> ra: S0 "\<lambda>x y. g y x" by unfold_locales (rule gcomm)
locale UB = Ub g + Ua g for g :: "'a \<Rightarrow> 'a \<Rightarrow> 'a"
locale UB2 = Ua g + Ub g for g :: "'a \<Rightarrow> 'a \<Rightarrow> 'a"

locale cS = fixes f :: "'a \<Rightarrow> 'a" assumes cs_ax: "f (f x) = f (f x)"
begin
lemma cs_note: "f x = f x" by simp
end
locale cTa = fixes g :: "'a \<Rightarrow> 'a"
sublocale cTa \<subseteq> qa: cS "g \<circ> g" by unfold_locales simp
locale cTb = fixes g :: "'a \<Rightarrow> 'a"
sublocale cTb \<subseteq> qb: cS "g \<circ> g" by unfold_locales simp
locale cX = cTb g + cTa g for g :: "'a \<Rightarrow> 'a"
locale cXr = cTa g + cTb g for g :: "'a \<Rightarrow> 'a"

locale vS = fixes h :: "'a \<Rightarrow> 'a" assumes vs_ax: "h x = h x"
begin
lemma vs_note: "h (h x) = h (h x)" by simp
end
locale vP = fixes f :: "'a \<Rightarrow> 'a" and g :: "'a \<Rightarrow> 'a"
sublocale vP \<subseteq> GF: vS "g \<circ> f" by unfold_locales simp
sublocale vP \<subseteq> FG: vS "f \<circ> g" by unfold_locales simp
locale vConv = E: vP f g for f g :: "'a \<Rightarrow> 'a"
sublocale vConv \<subseteq> vP g f .
locale vConv2 = E: vP g f for f g :: "'a \<Rightarrow> 'a"
sublocale vConv2 \<subseteq> vP f g .

locale CS = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma csfoo: "f x = f x" by (rule refl)
end
locale CW = fixes h :: "'a \<Rightarrow> 'a"
begin
lemma cwfoo: "h x = h x" by (rule refl)
end
locale Zb = fixes g :: "'a \<Rightarrow> 'a"
sublocale Zb \<subseteq> CS "\<lambda>x. g (g x)" .
locale Aq = fixes g :: "'a \<Rightarrow> 'a"
sublocale Aq \<subseteq> q: CS "\<lambda>x. g (g x)" .
locale Aq2 = fixes g :: "'a \<Rightarrow> 'a"
sublocale Aq2 \<subseteq> q: CS "\<lambda>x. g (g x)" .
sublocale Aq2 \<subseteq> q: CW g .
locale C2a = Zb g + Aq2 g for g :: "'a \<Rightarrow> 'a"
locale C2b = Aq2 g + Zb g for g :: "'a \<Rightarrow> 'a"
locale C3a = Zb g + Aq g for g :: "'a \<Rightarrow> 'a"
locale C3b = Aq g + Zb g for g :: "'a \<Rightarrow> 'a"

ML \<open>
local
  open Link_Finder_Test
  val thy = \<^theory>
  fun E loc name expected =
    let val (ctxt, _, r) = report thy loc in check_element ctxt loc (#elements r) name 0 expected end
in
  val _ = [("UB", "S0"), ("UB2", "S0"), ("cX", "cS"), ("cXr", "cS")]
    |> List.app (fn (loc, S) => linked thy loc [S])
  val _ = E "vConv" "local.E.GF.vs_note"
    "local.E.GF.vs_note#0: Level 2 vS::vs_note#2 @[E.GF] [g \<circ> f]"
  val _ = E "vConv" "local.E.FG.vs_note"
    "local.E.FG.vs_note#0: Level 2 vS::vs_note#2 @[E.FG] [f \<circ> g]"
  val _ = List.app (fn loc => linked thy loc ["CS"]) ["Zb", "C2a", "C3a", "C2b", "C3b"]
end
\<close>

text \<open>A self-sublocale whose instance collapses by beta (the R11 brainstorm's construction):
  under \<open>f := \<lambda>x. x\<close> the edge \<open>BC \<subseteq> BC f "f z"\<close> leads from \<open>(\<lambda>x. x, z)\<close> back to itself.  The
  qualified edge lengthens the chain, which no fact carries, so the walk does not follow it;
  unqualified, the arrival is a back arc, counted and not recorded.  \<open>find\<close> returns and links
  every fact at Level 2 either way.\<close>

locale BC = fixes f :: "'a \<Rightarrow> 'a" and z :: 'a assumes idem: "f (f x) = f x"
begin
lemma bc_note: "f (f (f x)) = f x" by (simp add: idem)
end
sublocale BC \<subseteq> s: BC f "f z" rewrites "f (f z) = f z" by unfold_locales (simp_all add: idem)
locale BM = fixes z :: 'a
sublocale BM \<subseteq> l: BC "\<lambda>x. x" z by unfold_locales simp

locale BCU = fixes f :: "'a \<Rightarrow> 'a" and z :: 'a assumes idem: "f (f x) = f x"
begin
lemma bcu_note: "f (f (f x)) = f x" by (simp add: idem)
end
sublocale BCU \<subseteq> BCU f "f z" rewrites "f (f z) = f z" by unfold_locales (simp_all add: idem)
locale BMU = fixes z :: 'a
sublocale BMU \<subseteq> l: BCU "\<lambda>x. x" z by unfold_locales simp

ML \<open>
local
  open Link_Finder_Test
  fun shape loc = let val (_, _, r) = report \<^theory> loc in (#nodes r, #back_arcs r, levels (#elements r)) end
in
  val _ = check "beta collapse, qualified: 2 nodes, no back arc, 3 facts at Level 2"
    (shape "BM" = (2, 0, [0, 0, 3, 0, 0, 0]))
  val _ = check "beta collapse, unqualified: 2 nodes, one back arc, 3 facts at Level 2"
    (shape "BMU" = (2, 1, [0, 0, 3, 0, 0, 0]))
end
\<close>

end
