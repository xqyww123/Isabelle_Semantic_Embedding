(*
  Link finder constructions (LINK_LAYER_PLAN.md §7, walk_team_synthesis_final.md
  §9.4), copied from the round-1 critic of "lazy": a declaration repeated by an
  ancestor (T1/Tp), the same-qualifier diamond (B/B2, a documented limit) and a
  re-declared edge (Tc); each locale's report in both edge orders, with links
  into S0.
*)
theory Link_Finder_Cons_Lazy
  imports Link_Finder_Test_Base
begin

locale S0 = fixes f :: "'a \<Rightarrow> 'a \<Rightarrow> 'a" assumes comm: "f x y = f y x"
begin
lemma comm_twice: "f (f x y) z = f z (f x y)" by (rule comm)
end

text \<open>T1's ancestor Tp declares the same (S0, instantiation); Isabelle activates it in T1
  through T1's own, older declaration.\<close>
locale Tp = fixes g :: "'a \<Rightarrow> 'a \<Rightarrow> 'a" assumes gcomm: "g x y = g y x"
locale T1 = fixes g :: "'a \<Rightarrow> 'a \<Rightarrow> 'a" assumes gcomm: "g x y = g y x"
sublocale T1 \<subseteq> q: S0 "\<lambda>x y. g y x" by unfold_locales (rule gcomm)
sublocale T1 \<subseteq> Tp g by unfold_locales (rule gcomm)
sublocale Tp \<subseteq> p: S0 "\<lambda>x y. g y x" by unfold_locales (rule gcomm)

text \<open>A diamond: Ta and Tb declare the same (S0, instantiation) with the same prefix.\<close>
locale Tb = fixes g :: "'a \<Rightarrow> 'a \<Rightarrow> 'a" assumes gcomm: "g x y = g y x"
locale Ta = fixes g :: "'a \<Rightarrow> 'a \<Rightarrow> 'a" assumes gcomm: "g x y = g y x"
sublocale Tb \<subseteq> r: S0 "\<lambda>x y. g y x" by unfold_locales (rule gcomm)
sublocale Ta \<subseteq> r: S0 "\<lambda>x y. g y x" by unfold_locales (rule gcomm)
locale B = Tb g + Ta g for g :: "'a \<Rightarrow> 'a \<Rightarrow> 'a"
locale B2 = Ta g + Tb g for g :: "'a \<Rightarrow> 'a \<Rightarrow> 'a"

text \<open>A re-declared edge: two edges with the same content.\<close>
locale Tc = fixes g :: "'a \<Rightarrow> 'a \<Rightarrow> 'a" assumes gcomm: "g x y = g y x"
sublocale Tc \<subseteq> s: S0 "\<lambda>x y. g y x" by unfold_locales (rule gcomm)
sublocale Tc \<subseteq> s: S0 "\<lambda>x y. g y x" by unfold_locales (rule gcomm)

ML \<open>
local
  open Link_Finder_Test
  val thy = \<^theory>
in
  val _ = List.app (fn loc => linked thy loc ["S0"]) ["T1", "Tp", "B", "B2", "Tb", "Ta", "Tc"]
  val (ctxt, _, r) = report thy "T1"
  val _ = check_element ctxt "T1" (#elements r) "local.q.comm_twice" 0
    "local.q.comm_twice#0: Level 2 S0::comm_twice#2 @[q] [\<lambda>x y. g y x]"
end
\<close>

end
