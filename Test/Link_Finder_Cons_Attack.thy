(*
  Link finder constructions (LINK_LAYER_PLAN.md §7, walk_team_synthesis_final.md
  §9.4), copied from the round-2 designer "attack": eta-different routes into
  one node (EB/EB2), an ancestor whose only named note is concealed (HC) or that
  has no note (HC0), one locale imported twice (D2-D5), self-sublocales by a
  permutation (PM, PU); each locale's report in both edge orders, with the
  locales its links must reach.
*)
theory Link_Finder_Cons_Attack
  imports Link_Finder_Test_Base
begin

definition neg :: "('a \<Rightarrow> 'a) \<Rightarrow> ('a \<Rightarrow> 'a)" where "neg h = h"

locale EA = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma eafoo: "f = f" by (rule refl)
lemma eabar: "f x = f x" by (rule refl)
end

locale EX1 = fixes h :: "'a \<Rightarrow> 'a"
sublocale EX1 \<subseteq> EA "\<lambda>x. h x" .

locale EX2 = fixes h :: "'a \<Rightarrow> 'a"
sublocale EX2 \<subseteq> EA h .

locale EB = EX1 g + EX2 g for g :: "'a \<Rightarrow> 'a"
locale EB2 = EX2 g + EX1 g for g :: "'a \<Rightarrow> 'a"

locale HS = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma hsfoo: "f x = f x" by simp
end

locale H = fixes g :: "'a \<Rightarrow> 'a"

context H
begin
local_setup \<open>fn lthy =>
  snd (Local_Theory.note ((Binding.concealed (Binding.name "hid"), []), [Drule.reflexive_thm]) lthy)\<close>
end

sublocale H \<subseteq> HS "neg g" .

locale HC = HS "neg g" + q: H g for g :: "'a \<Rightarrow> 'a"
locale HC2 = q: H g + HS "neg g" for g :: "'a \<Rightarrow> 'a"

locale H0 = fixes g :: "'a \<Rightarrow> 'a"
sublocale H0 \<subseteq> HS "neg (neg g)" .
locale HC0 = HS "neg (neg g)" + q: H0 g for g :: "'a \<Rightarrow> 'a"

locale D2 = a: ordering le lt + b: ordering le lt for le :: "'a \<Rightarrow> 'a \<Rightarrow> bool" and lt
locale D3 = a: ordering le lt + b: ordering "\<lambda>x y. le y x" "\<lambda>x y. lt y x"
  for le :: "'a \<Rightarrow> 'a \<Rightarrow> bool" and lt
locale D4 = D3 le lt for le :: "'a \<Rightarrow> 'a \<Rightarrow> bool" and lt
locale D5 = c: ordering "\<lambda>x y. le y x" "\<lambda>x y. lt y x" + D3 le lt
  for le :: "'a \<Rightarrow> 'a \<Rightarrow> bool" and lt

locale PM = fixes a :: 'a and b :: 'a
begin
lemma pmfoo: "a = a \<or> b = b" by simp
end
sublocale PM \<subseteq> sw: PM b a .

locale PU = fixes a :: 'a and b :: 'a
begin
lemma pufoo: "a = a \<or> b = b" by simp
end
sublocale PU \<subseteq> PU b a .

ML \<open>
local
  open Link_Finder_Test
  val thy = \<^theory>
in
  (*the eta half of Level 2*)
  val _ = ["EB", "EB2"] |> List.app (fn loc =>
    let val (_, _, r) = report thy loc
    in check (loc ^ ": eafoo at Level 2")
      (#outcome (the_element (#elements r) \<^unchecked_name>\<open>local.eafoo\<close> 0) = Link_Finder.Linked Link_Finder.Level2) end)
  val _ = List.app (fn loc => linked thy loc ["HS"]) ["H", "HC", "HC2", "H0", "HC0"]
  val _ = report thy "D2"
  val _ = List.app (fn loc => linked thy loc ["ordering"]) ["D3", "D4", "D5"]
  val (ctxt, _, r) = report thy "PM"
  val _ = check_element ctxt "PM" (#elements r) \<^unchecked_name>\<open>local.sw.pmfoo\<close> 0
    "local.sw.pmfoo#0: Level 2 PM::pmfoo#0 @[sw] [b, a]"
  val (ctxt, _, r) = report thy "PU"
  val _ = check_element ctxt "PU" (#elements r) \<^unchecked_name>\<open>local.pufoo\<close> 0
    "local.pufoo#0: Level 2 PU::pufoo#0 @[] [a, b]"
end
\<close>

end
