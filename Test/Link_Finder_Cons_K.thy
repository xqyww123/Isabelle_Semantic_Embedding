(*
  Link finder construction (LINK_LAYER_PLAN.md §4.3 Termination, §7, §9 R14):
  K1, unqualified rewrites-closed self-sublocales with branching b, copied from
  the round-2 critic of "fix".  D22 bounds the depth of such a cycle, not its
  breadth: the walk has (b^11 - 1) / (b - 1) nodes, 88,573 for b = 3 (the pin
  here).  The walk has no node bound (D42, D49): K1b4, 1,398,101 nodes, is
  walked only by the cslh19 probe of R14 (222 s and about 24 GB there), never
  in this suite.
*)
theory Link_Finder_Cons_K
  imports Link_Finder_Test_Base
begin

locale K1b3 = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma k_note: "f x = f x" by (rule refl)
end
sublocale K1b3 \<subseteq> K1b3 "id \<circ> f" rewrites "id \<circ> f = f" by simp
sublocale K1b3 \<subseteq> K1b3 "f \<circ> id" rewrites "f \<circ> id = f" by simp
sublocale K1b3 \<subseteq> K1b3 "(id \<circ> id) \<circ> f" rewrites "(id \<circ> id) \<circ> f = f" by simp

ML \<open>
local
  open Link_Finder_Test
  val thy = \<^theory>
  val loc3 = Locale.check_global thy ("K1b3", Position.none)
  val (_, F) = find_in thy loc3 false
  val r = Link_Finder.report F
in
  val _ = check ("K1b3: 88573 nodes, found " ^ string_of_int (#nodes r)) (#nodes r = 88573)
end
\<close>

end
