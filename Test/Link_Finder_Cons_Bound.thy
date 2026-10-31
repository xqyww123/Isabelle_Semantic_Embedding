(*
  Link finder constructions (LINK_LAYER_PLAN.md §7, walk_team_synthesis_final.md
  §9.4), copied from the round-1 critic of "bound": declarations whose chain no
  fact carries (T1a/T1b/T2, T3/U), edge order and rewrites-closed cycles (B,
  B12, B12r, A12), and a tie-break over parameter-free statements (Bt); links
  into S0, S1 and Ac, and the outcomes of named elements.
*)
theory Link_Finder_Cons_Bound
  imports Link_Finder_Test_Base
begin

definition neg :: "('a \<Rightarrow> 'a) \<Rightarrow> ('a \<Rightarrow> 'a)" where "neg h = h"
definition rot :: "('a \<Rightarrow> 'a) \<Rightarrow> ('a \<Rightarrow> 'a)" where "rot h = h"

locale S0 = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma sfoo: "f x = f x" by simp
end

locale M0 = S0 h for h :: "'a \<Rightarrow> 'a"

locale T2 = fixes g :: "'a \<Rightarrow> 'a"
begin
lemma t2foo: "g x = g x" by simp
end

sublocale T2 \<subseteq> q2: M0 "neg g" .

locale T1a = T2 g + q1: S0 "neg g" for g :: "'a \<Rightarrow> 'a"
begin
lemma t1foo: "g y = g y" by simp
end

locale T1b = q1: S0 "neg g" + T2 g for g :: "'a \<Rightarrow> 'a"
begin
lemma t1foo: "g y = g y" by simp
end

locale Z = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma zfoo: "f x = f x" by simp
end

locale A = Z f for f :: "'a \<Rightarrow> 'a"
begin
lemma afoo: "f y = f y" by simp
end

sublocale A \<subseteq> A "neg f"
  rewrites "neg (neg f) = f"
  by (unfold_locales) (simp add: neg_def)

locale B = fixes g :: "'a \<Rightarrow> 'a"
begin
lemma bfoo: "g y = g y" by simp
end

sublocale B \<subseteq> A "neg g" .
sublocale B \<subseteq> A g .

text \<open>A cycle Isabelle closes only after 12 rounds; D22 cuts it at the eleventh re-entry.\<close>
locale Z12 = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma z12foo: "f x = f x" by simp
end

locale A12 = Z12 f for f :: "'a \<Rightarrow> 'a"

sublocale A12 \<subseteq> A12 "rot f"
  rewrites "rot (rot (rot (rot (rot (rot (rot (rot (rot (rot (rot (rot f))))))))))) = f"
  by (unfold_locales) (simp add: rot_def)

locale B12 = fixes g :: "'a \<Rightarrow> 'a"
begin
lemma b12foo: "g y = g y" by simp
end

sublocale B12 \<subseteq> A12 "rot g" .
sublocale B12 \<subseteq> A12 g .

locale S1 = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma s1foo: "f x = f x" by simp
end

locale T4 = fixes g :: "'a \<Rightarrow> 'a"
begin
lemma t4foo: "g x = g x" by simp
end

sublocale T4 \<subseteq> q2: S1 "neg g" .

locale T3 = q1: S1 "neg g" + T4 g for g :: "'a \<Rightarrow> 'a"
begin
lemma t3foo: "g y = g y" by simp
end

locale V = fixes k :: "'a \<Rightarrow> 'a"
begin
lemma vfoo: "k x = k x" by simp
end

locale U = T3 g + q2: V g for g :: "'a \<Rightarrow> 'a"

locale B12r = fixes g :: "'a \<Rightarrow> 'a"
begin
lemma b12rfoo: "g y = g y" by simp
end

sublocale B12r \<subseteq> A12 g .
sublocale B12r \<subseteq> A12 "rot g" .

locale Zc = fixes f :: "'a \<Rightarrow> 'a"

locale Ac = Zc f for f :: "'a \<Rightarrow> 'a"
begin
lemma acst: "(z::'b) = z" by simp
end

sublocale Ac \<subseteq> Ac "neg f"
  rewrites "neg (neg f) = f"
  by (unfold_locales) (simp add: neg_def)

locale Bt = fixes h :: "'a \<Rightarrow> 'a \<Rightarrow> 'a" and y :: 'a
begin
lemma btfoo: "h y = h y" by simp
end

sublocale Bt \<subseteq> Ac "neg (h y)" .
sublocale Bt \<subseteq> Ac "h y" .

ML \<open>
local
  open Link_Finder_Test
  val thy = \<^theory>
  fun V loc name v =
    let val (_, _, r) = report thy loc; val e = the_element (#elements r) name 0
    in check (loc ^ ": " ^ name ^ " " ^ outcome_string v) (#outcome e = v) end
in
  val _ = List.app (fn loc => linked thy loc ["S0"]) ["T2", "T1a", "T1b"]
  val _ = List.app (fn loc => linked thy loc ["S1"]) ["T4", "T3", "U"]
  val _ = linked thy "Bt" ["Ac"]
  val _ = V "B" "local.zfoo" (Link_Finder.Linked Link_Finder.Level2)
  val _ = V "B" "local.afoo" (Link_Finder.Linked Link_Finder.Level2)
  val _ = V "B12" "local.z12foo" (Link_Finder.Linked Link_Finder.Level2)
  val _ = V "B12r" "local.z12foo" (Link_Finder.Linked Link_Finder.Level3_Approximate)
  val _ = V "Bt" "local.acst" (Link_Finder.Linked Link_Finder.Level2)
  (*A12: D22 cuts a true round; the fact gets an approximate link (D22's accepted loss)*)
  val _ = V "A12" "local.z12foo" (Link_Finder.Linked Link_Finder.Level3_Approximate)
  val (_, _, r) = report thy "A12"
  val _ = check "A12: one D22 cut" (#cuts r = 1)
end
\<close>

end
