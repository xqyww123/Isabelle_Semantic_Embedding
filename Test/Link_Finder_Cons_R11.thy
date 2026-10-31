(*
  Link finder construction R11 (LINK_LAYER_PLAN.md §9): over Binary_Relations,
  whose sym sublocales rewrite sympartp (sympartp r) to sympartp r, a block
  interpretation of preorder under the reversed order in a locale with an
  order sublocale.  Read through the registration's mixins, the sym child of
  a (source, instance) folded back into it, an arc on which a composed
  instance grew without end; instances below a root registration are now
  composed from own tables, and the nodes below it are keyed by it (M06).
  Counts in both edge orders.
*)
theory Link_Finder_Cons_R11
  imports Link_Finder_Test_Base Complete_Non_Orders.Binary_Relations
begin

locale LIS_measured = fixes m :: "'a \<Rightarrow> nat" assumes inj: "inj m"

sublocale LIS_measured \<subseteq> by_measure: order "\<lambda>x y. m x \<le> m y" "\<lambda>x y. m x < m y"
  apply unfold_locales
     apply (rule less_le_not_le)
    apply (rule order_refl)
   apply (erule (1) order_trans)
  apply (rule injD[OF inj])
  apply (erule (1) Nat.le_antisym)
  done

context LIS_measured
begin

interpretation p: preorder "\<lambda>x y. m y \<le> m x" "\<lambda>x y. m y < m x"
  apply unfold_locales
    apply (rule less_le_not_le)
   apply (rule order_refl)
  apply (erule (1) order_trans[rotated])
  done

text \<open>Nodes, back arcs, D22 cuts, root registrations entering the walk, levels (Level 0, no
  candidate, Level 2, Level 3 exact, approximate, no link), links; the same elements in both
  orders.\<close>

ML \<open>
local
  open Link_Finder_Test
  val ctxt = \<^context>
  val edges = Locale.dest_dependencies [] (Proof_Context.theory_of ctxt)
  fun run order es =
    let
      val F = Link_Finder.find {bottom = Named_Target.bottom_locale_of ctxt, edges = es} ctxt
      val r = Link_Finder.report F
      val found =
        [#nodes r, #back_arcs r, #cuts r, #roots r] @ levels (#elements r) @
        [length (Link_Finder.links_of F)]
      val expected = [143, 0, 0, 2, 0, 0, 643, 0, 72, 220, 629]
      val _ = check (String.concat ["R11, ", order, " order: counts ", commas (map string_of_int found),
        ", expected ", commas (map string_of_int expected)]) (found = expected)
    in #elements r end
  val elements = run "serial" edges
  val elements' = run "reverse" (rev edges)
in
  val _ = check "R11: serial and reverse edge order agree" (elements = elements')
  (*the links of rev 4's code, measured 2026-10-26 on a scratch copy with rev 4's finder; their
    62 links with rewrites (65 rewrites) were all positional and went with D62 (2026-10-27,
    step3_review/probes/d62/)*)
  val _ = check_links_digest "R11"
    (Link_Finder.find {bottom = Named_Target.bottom_locale_of ctxt, edges = edges} ctxt)
    (629, "0968058c072017cd26557ca3c77d14162274ad69", 0, 0, "e9d8e13020257c697e1030e615fe133c4eb3d89b")
end
\<close>

end

end
