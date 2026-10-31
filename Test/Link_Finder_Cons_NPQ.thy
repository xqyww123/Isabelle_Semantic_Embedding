(*
  Link finder construction (LINK_LAYER_PLAN.md §7, walk_team_synthesis_final.md
  §9.4) N/P/Q, copied from the round-1 critic of "tee": the dual ordering is
  declared by N, which has no note, and reached from P and Q; each locale's
  report in both edge orders, with links into ordering and its two ancestors.
*)
theory Link_Finder_Cons_NPQ
  imports Link_Finder_Test_Base
begin

locale N = ordering "\<lambda>x y. le y x" "\<lambda>x y. lt y x" for le :: "'a \<Rightarrow> 'a \<Rightarrow> bool" and lt

locale P = ordering le lt for le :: "'a \<Rightarrow> 'a \<Rightarrow> bool" and lt
begin
sublocale rev: N le lt
  unfolding N_def by (rule ordering_dualI) (rule ordering_axioms)
end

locale Q = rv: ordering "\<lambda>x y. le y x" "\<lambda>x y. lt y x" + P le lt
  for le :: "'a \<Rightarrow> 'a \<Rightarrow> bool" and lt

ML \<open>
local
  open Link_Finder_Test
  val thy = \<^theory>
in
  val _ = ["N", "P", "Q"] |> List.app (fn loc =>
    linked thy loc ["ordering", "preordering", "partial_preordering"])
end
\<close>

end
