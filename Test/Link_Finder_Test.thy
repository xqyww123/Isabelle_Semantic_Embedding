(*
  The link finder on the standard contexts (LINK_LAYER_PLAN.md §7,
  walk_team_synthesis_final.md §0, §9.4): the counts of the round-3 builds
  (walk_team_round3.md, design "fix" M1/M2) in serial and reverse edge order,
  each context built on its own theory as the round-3 builds did; Level 3's
  recoveries in linordered_field; the rewrites of Max.coboundedI; the dual
  order.
*)
theory Link_Finder_Test
  imports Link_Finder_Test_Base
    Complete_Non_Orders.Binary_Relations
    Jacobson_Basic_Algebra.Ring_Theory
    "HOL-Algebra.Algebra"
    Saturation_Framework.Given_Clause_Architectures
begin

ML \<open>
local
  open Link_Finder_Test
  val main = Thy_Info.get_theory "Main"
  val binrel = Thy_Info.get_theory "Complete_Non_Orders.Binary_Relations"
  val algebra = Thy_Info.get_theory "HOL-Algebra.Algebra"
  val jacobson = Thy_Info.get_theory "Jacobson_Basic_Algebra.Ring_Theory"
  val saturation = Thy_Info.get_theory "Saturation_Framework.Given_Clause_Architectures"

  (*nodes, back arcs, D22 cuts, name hits (node, note) / theorems, candidates
    after the position rule, facts narrowed by it, facts the registration
    predicate recognises, levels (Level 0, no candidate, Level 2, Level 3
    exact, approximate, no link)*)
  fun counts thy loc expected =
    let
      val (_, _, r) = report thy loc
      val found =
        [#nodes r, #back_arcs r, #cuts r, #name_hits r, #name_hit_theorems r, #candidates r,
          #narrowed r, length (#recognised r)] @
        levels (#elements r)
    in
      check (loc ^ ": counts " ^ commas (map string_of_int found) ^ ", expected " ^
        commas (map string_of_int expected)) (found = expected)
    end
in
  val _ = counts main "Fields.linordered_field" [180, 0, 0, 2361, 2599, 2592, 7, 0, 0, 0, 2248, 303, 17, 24]
  val _ = counts main "Orderings.order" [15, 0, 0, 273, 296, 296, 0, 0, 0, 0, 280, 0, 16, 0]
  val _ = counts main "Orderings.linorder" [42, 0, 0, 641, 676, 676, 0, 0, 0, 0, 594, 41, 17, 24]
  val _ = counts main "List.folding_insort_key" [44, 0, 0, 668, 705, 705, 0, 0, 0, 0, 617, 41, 17, 30]
  val _ = counts binrel "Orderings.order" [92, 0, 0, 705, 736, 726, 10, 0, 0, 0, 387, 0, 59, 220]
  val _ = counts binrel "Orderings.linorder" [136, 0, 0, 1147, 1190, 1179, 11, 0, 0, 0, 728, 41, 60, 290]
  val _ = counts binrel "Fields.linordered_field" [274, 0, 0, 2867, 3113, 3095, 18, 0, 0, 0, 2382, 303, 60, 290]
  val _ = counts binrel "Binary_Relations.reflexive" [8, 0, 0, 36, 36, 36, 0, 0, 0, 0, 36, 0, 0, 0]
  val _ = counts binrel "Binary_Relations.quasi_ordered_set" [24, 0, 0, 168, 172, 172, 0, 0, 0, 0, 136, 0, 36, 0]
  val _ = counts algebra "Module.algebra" [30, 0, 0, 2776, 3057, 3057, 0, 0, 0, 0, 2207, 0, 0, 850]
  val _ = counts algebra "Ring_Divisibility.factorial_domain" [31, 0, 0, 2036, 2212, 2207, 5, 0, 0, 0, 1497, 0, 94, 440]
  val _ = counts algebra "UnivPoly.UP_domain" [49, 0, 0, 3747, 4105, 4104, 1, 0, 0, 0, 3036, 0, 188, 880]
  val _ = counts algebra "RingHom.ring_hom_ring" [24, 0, 0, 2617, 2829, 2828, 1, 0, 0, 0, 1978, 0, 0, 850]
  val _ = counts algebra "Ring.field" [36, 0, 0, 2109, 2288, 2279, 8, 0, 0, 0, 1565, 0, 96, 442]
  val _ = counts algebra "UnivPoly.UP_univ_prop" [72, 0, 0, 5820, 6386, 6382, 3, 0, 0, 0, 3505, 0, 0, 1275]
  val _ = counts saturation "Given_Clause_Architectures.given_clause" [36, 2, 0, 434, 438, 430, 8, 0, 0, 0, 430, 0, 0, 0]
  val _ = counts jacobson "Set_Theory.partition" [44, 0, 1, 561, 561, 561, 0, 0, 0, 0, 25, 0, 0, 26]
  val _ = counts jacobson "Set_Theory.equivalence" [44, 0, 1, 561, 561, 561, 0, 0, 0, 0, 42, 0, 0, 9]
  val _ = counts jacobson "Ring_Theory.ring_homomorphism_fundamental"
    [1127, 0, 18, 11285, 11315, 11303, 9, 0, 0, 0, 1918, 0, 520, 105]
  val _ = counts jacobson "Ring_Theory.ideal_in_kernel" [1002, 0, 16, 9886, 9914, 9904, 8, 0, 0, 0, 1761, 0, 528, 96]
  val _ = counts jacobson "Ring_Theory.quotient_ring" [544, 0, 9, 5217, 5231, 5226, 4, 0, 0, 0, 1081, 0, 8, 48]
end
\<close>

text \<open>Level 3 exact recovers 303 of the 344 elements Level 2 leaves in linordered_field.  In
  linorder, \<open>Max.coboundedI\<close> links to \<open>semilattice_order_set.coboundedI\<close> at Level 3 exact and
  carries the \<open>Max\<close> rewrite: the definitional equation \<open>Max_def\<close> of linorder, which the
  pre-check applied (D65).  Locale.init sets up no class syntax, hence the printed forms.  Every
  linked element without a link is an \<open>_axioms\<close> note, which has no global fact (§4.7).\<close>

ML \<open>
local
  open Link_Finder_Test
  val main = Thy_Info.get_theory "Main"
  val (_, _, r) = report main "Fields.linordered_field"
  val ls = levels (#elements r)
  val _ = check "Level 3 exact: 303 of 344" (nth ls 3 = 303 andalso nth ls 3 + nth ls 4 + nth ls 5 = 344)
  val (ctxt, F, r) = report main "Orderings.linorder"
  val _ = check_element ctxt "linorder" (#elements r) "local.Max.coboundedI" 0
    "local.Max.coboundedI#0: Level 3 exact semilattice_order_set::coboundedI#4 @[Max] [ord.max less_eq, \<lambda>x y. less_eq y x, \<lambda>x y. less y x]"
  val links = Link_Finder.links_of F
  fun key th = Universal_Key.key_of_theorem' NONE (Context.Proof ctxt) th
  val cobounded = AList.lookup (op =) links (key (Proof_Context.get_thm ctxt "Max.coboundedI"))
  val _ =
    (case cobounded of
      SOME (l: Link_Finder.link) =>
        check "Max.coboundedI carries the Max rewrite"
          (#source l = "Lattices_Big.semilattice_order_set" andalso #note l = ("coboundedI", 0) andalso
           kind l = Link_Finder.Proper andalso
           #rewrites l = [("semilattice_set.F (ord.max less_eq)", "linorder.Max less_eq")])
    | NONE => fail "no link for Max.coboundedI")
  (*a link carries only the equations Level 3 exact's pre-check applied: monoid_add's
    add_0_left, an identity link, carries none*)
  val (_, F', _) = report main "Fields.linordered_field"
  val add_0_left =
    Link_Finder.links_of F' |> map #2
    |> filter (fn l: Link_Finder.link => #source l = "Groups.monoid_add" andalso #note l = ("add_0_left", 0))
  val _ = check "monoid_add.add_0_left is an identity link in linordered_field and carries no rewrite"
    (not (null add_0_left) andalso
      forall (fn l: Link_Finder.link => kind l = Link_Finder.Identity andalso null (#rewrites l)) add_0_left)
  (*325 before D62, when 17 Level 3 approximate links lost their positional rewrites; 308
    before D65, when 6 Level 2 _def links lost theirs and sorted_key_list_of_set_empty gained one*)
  val _ = check "303 links carry rewrites in linordered_field"
    (length (filter (fn (_, l: Link_Finder.link) => not (null (#rewrites l))) (Link_Finder.links_of F')) = 303)
  val unlinked =
    #elements r |> filter (fn e => (case #outcome e of Link_Finder.Linked _ => true | _ => false))
    |> filter (fn e => not (AList.defined (op =) links (key (nth (Proof_Context.get_thms ctxt (#name e)) (#index e)))))
  val _ = check "every linked element without a link is an _axioms note"
    (forall (fn e => String.isSuffix "_axioms" (#note (the (#template e)))) unlinked)
in end
\<close>

text \<open>The dual order (§2's example): \<open>dual_order\<close> facts in \<open>order\<close> link to \<open>ordering\<close>'s notes
  under the reversed order; links reach \<open>preordering\<close> in \<open>order\<close> and \<open>linordered_field\<close>,
  the four monoid locales of \<open>mult_of R\<close> and \<open>euclidean_domain\<close> in \<open>Ring.field\<close>, and
  \<open>consequence_relation\<close> in \<open>given_clause\<close>.\<close>

ML \<open>
local
  open Link_Finder_Test
  val main = Thy_Info.get_theory "Main"
  val algebra = Thy_Info.get_theory "HOL-Algebra.Algebra"
  val saturation = Thy_Info.get_theory "Saturation_Framework.Given_Clause_Architectures"
  val (ctxt, _, r) = report main "Orderings.order"
  val _ = check_element ctxt "order" (#elements r) "local.dual_order.antisym" 0
    "local.dual_order.antisym#0: Level 2 ordering::antisym#2 @[dual_order] [\<lambda>x y. less_eq y x, \<lambda>x y. less y x]"
  val _ = check_linked "order" (#elements r) "preordering"
  val _ = linked main "Fields.linordered_field" ["preordering"]
  val _ = linked algebra "Ring.field"
    ["divisor_chain_condition_monoid", "factorial_monoid", "gcd_condition_monoid",
     "primeness_condition_monoid", "euclidean_domain"]
  val _ = linked saturation "Given_Clause_Architectures.given_clause" ["consequence_relation"]
in end
\<close>

text \<open>Routes (D42): the walk records no back arc, so the recorded arcs form an acyclic graph.
  Jacobson's \<open>monoid_isomorphism\<close> has a real back arc (its dependency graph has the cycle
  \<open>monoid_isomorphism \<subseteq> monoid_isomorphism'\<close> and back); its arcs have a topological order,
  and its links are those of rev 4's code (the digests below).\<close>

ML \<open>
local
  open Link_Finder_Test
  val jacobson = Thy_Info.get_theory "Jacobson_Basic_Algebra.Ring_Theory"
  val (_, _, r) = report jacobson "Group_Theory.monoid_isomorphism"
  (*arcs (node, parent node) over nodes 0 .. n - 1 have a topological order*)
  fun acyclic n arcs =
    let
      val indegree = Array.array (n, 0)
      val _ = List.app (fn (j, _) => Array.update (indegree, j, Array.sub (indegree, j) + 1)) arcs
      val children = fold (fn (j, p) => Inttab.cons_list (p, j)) arcs Inttab.empty
      fun release j = (Array.update (indegree, j, Array.sub (indegree, j) - 1); Array.sub (indegree, j) = 0)
      fun go [] k = k
        | go (x :: xs) k = go (filter release (Inttab.lookup_list children x) @ xs) (k + 1)
    in go (filter (fn i => Array.sub (indegree, i) = 0) (0 upto n - 1)) 0 = n end
in
  val _ = check "monoid_isomorphism: one back arc" (#back_arcs r = 1)
  val _ = check "monoid_isomorphism: the recorded arcs have a topological order" (acyclic (#nodes r) (#arcs r))
  val _ = check "monoid_isomorphism: levels" (levels (#elements r) = [0, 0, 135, 0, 0, 0])
end
\<close>

text \<open>The links are those of rev 4's code (§7's rewrites pins; measured 2026-10-26 by running
  rev 4's finder on a scratch copy of the session and this step's on another, equal in every
  context below and in R11's \<open>p\<close>), and so were their rewrites until D62 removed the rewrites
  recovered by positional comparison (re-pinned 2026-10-27: every difference from the code before
  D62 is the removal of a Level 3 approximate link's positional rewrites,
  step3_review/probes/d62/) and D65 made them the equations Level 3 exact's pre-check applied
  (re-pinned 2026-10-28: the links unchanged, the 6 Level 2 _def links of linordered_field lose
  their rewrites and sorted_key_list_of_set_empty gains one, step3_review/probes/d65/): per
  context the number of links, the SHA1 of their sorted (fact,
  source, note, index, level) lines, the links carrying rewrites, the rewrites, and the SHA1 of
  the sorted (fact, source, note, index, rewrites) lines.  A fact is
  named by its key's 15-byte payload: the key's 16-byte prefix hashes theory long names and
  differs between environments.\<close>

ML \<open>
local
  open Link_Finder_Test
  val main = Thy_Info.get_theory "Main"
  val binrel = Thy_Info.get_theory "Complete_Non_Orders.Binary_Relations"
  val algebra = Thy_Info.get_theory "HOL-Algebra.Algebra"
  val jacobson = Thy_Info.get_theory "Jacobson_Basic_Algebra.Ring_Theory"
  val saturation = Thy_Info.get_theory "Saturation_Framework.Given_Clause_Architectures"
in
  val _ =
    [(main, "Fields.linordered_field", 2433, "e8c10d689a10d96a055fdf7d0127449812a39abe",
      303, 321, "f7dcd6ecb7ca1172c66f2de205f00fd812d7a781"),
     (main, "Orderings.order", 286, "142a97e07e5bc06d29954d1c5522d77e9c009b21",
      0, 0, "4cb4407582b7620210518f71a1d11e74eae49c36"),
     (main, "Orderings.linorder", 627, "a9436a7ffb5863eb8042007d158ded3b819f3354",
      41, 41, "296d4d1b126c34f41467d9957557b4841c4746d3"),
     (main, "List.folding_insort_key", 648, "9c37d261e87170b7e191c87e264951865e12eeb7",
      41, 41, "5ced88df020c968a9cb9d5fe653080bd6c4273ed"),
     (binrel, "Orderings.order", 375, "587ab42d2245f3927cec46ea10de916711bcd6fd",
      0, 0, "d5b4c80b665d11d2ba3359334f8ce20294a507e5"),
     (binrel, "Orderings.linorder", 726, "f6b157abe54d0434e0edc5bbbf02d8bf78807a79",
      41, 41, "6e593ca33f86737c312c9e8a8ec1f18177ab55db"),
     (binrel, "Fields.linordered_field", 2532, "91ab683c646e429764783dabb9e161fb15b79bd3",
      303, 321, "cfb61cd8eb90bfaeba734173a2c7a62340c7f748"),
     (binrel, "Binary_Relations.reflexive", 32, "a5c938b4a7190c6f3caa682c9b60be1fe6169c18",
      0, 0, "6d1ed210d53e55faa7286e65b618a4d015226a2d"),
     (binrel, "Binary_Relations.quasi_ordered_set", 152, "e05a3dc7a79756fde5090d948c7abd5c22df0be6",
      0, 0, "4662785c864ef2e9f83fea2f1fe62df8fd1f4f38"),
     (algebra, "Module.algebra", 2179, "4995694c55bf8ef2f061d5d3e440675f36e74d19",
      0, 0, "d2c26f8c5a691d23b96a5f8e9a6233cf484e0382"),
     (algebra, "Ring_Divisibility.factorial_domain", 1568, "f869af19b89d88a69cc7770e19a6efad58209623",
      0, 0, "cc57b9bc16277a21f761aac700bddb558f2a1fa0"),
     (algebra, "UnivPoly.UP_domain", 3183, "b64031348df05f06029369ba97a48a143542decc",
      0, 0, "ea51ce30e9223342dec0b4042546bd7a24ca684f"),
     (algebra, "RingHom.ring_hom_ring", 1954, "6e601df620a628fda93eb07f9c121a9a902c5830",
      0, 0, "9dfbd83f09581fd9e101165210498fd546e70064"),
     (algebra, "Ring.field", 1633, "f81cf12eb8239c9384e4794babb00f4eafe1e5be",
      0, 0, "3044f1b7a96a8b91b0ef95a384d84cb21e103f6e"),
     (algebra, "UnivPoly.UP_univ_prop", 3457, "fd28ad32da9c8889b9ea0b3d380b9518a4f53581",
      0, 0, "103554bfd862e306cdd1a941a7675c3a53a17ec8"),
     (saturation, "Given_Clause_Architectures.given_clause", 405, "93df1d5ec327d4e78f7332021dc08da6ed0b4365",
      0, 0, "987a2bd62bd6f385a623a387cd74fcd676feaed6"),
     (jacobson, "Set_Theory.partition", 23, "5f74c6f886af574b50608b4f45a729a9d3de6d36",
      0, 0, "2106ada53b85a97683ae971182da4d3c4eadcfba"),
     (jacobson, "Set_Theory.equivalence", 38, "04f068ff8e0e9247fba377ca2ed0454c453dcdf5",
      0, 0, "213ad7a62ba5d0c22fa2c26e2fbb9f246d3b46db"),
     (jacobson, "Ring_Theory.ring_homomorphism_fundamental", 2218, "f1affd113b1ecfcedcc570da3b3375dee750197a",
      0, 0, "bed5f00b5a43765618dc39a557d59685b7d364f3"),
     (jacobson, "Ring_Theory.ideal_in_kernel", 2086, "2aa5633d99b3353bcd7eba83cb11f29e8d1b180b",
      0, 0, "2b89751dff8c496189988001e0816f6337b101e9"),
     (jacobson, "Ring_Theory.quotient_ring", 990, "9eca68d1e0c70c0fef6913d5102ee90d4273e923",
      0, 0, "7259e3b5a08d41f2da2f7b5b598eaf10948e5b59"),
     (jacobson, "Group_Theory.monoid_isomorphism", 119, "0ea82e18ba5354fdc98dc0a7295fba1d61e5d237",
      0, 0, "eb366ca3f91d08d7d87eeb1e7074ac17518c6176")]
    |> List.app (fn (thy, loc, n, ld, nrw, nrws, rd) =>
      let val (_, F, _) = report thy loc in check_links_digest loc F (n, ld, nrw, nrws, rd) end)
end
\<close>

end
