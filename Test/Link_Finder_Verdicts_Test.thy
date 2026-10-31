(*
  The parameters' verdicts (LINK_LAYER_PLAN.md §7, §3.28; D41): decided on the
  instance terms alone, a Free by its name and a Var by its indexname, types never
  read.  Identities whose types change, renamings, a permutation, a for-variable,
  and an identity link whose pure rewrites mixin is not shown, in constructed and
  real contexts.
*)
theory Link_Finder_Verdicts_Test
  imports Link_Finder_Test_Base HOL.Real_Vector_Spaces "HOL-Algebra.Algebra"
    Jacobson_Basic_Algebra.Ring_Theory
begin

text \<open>Identities whose types change: a renamed type variable (as \<open>C.arr_cod\<close> in Category3's
  \<open>diagram\<close>), a type instance (as \<open>M\<close> in \<open>real_distribution\<close>), \<open>bounded_linear = linear f\<close>,
  which only strengthens sorts, \<open>coset_notation\<close> in \<open>normal_subgroup\<close>, \<open>is_order_A\<close> in
  \<open>galois_connection\<close>, and \<open>module_hom_id\<close> in \<open>vector_space\<close>, an identity link whose pure
  rewrites mixin is not shown (D62);
  they fail under a verdict that compares variables with \<open>aconv\<close> or reads types.  Renamings:
  one with a new type, \<open>group_hom\<close>'s H side, \<open>Vector_Spaces.linear\<close>'s \<open>vs2\<close>, a permutation of
  S's own parameters (D16's exception lapsed), a \<open>for\<close>-variable, which is never unchanged.  The
  pins are evaluated together, so that one mutant run shows every pin it fails.\<close>

locale VT = fixes M :: "'a list"
begin
lemma M_refl: "M = M" by (rule refl)
end
locale VT_renamed_tvar = VT M for M :: "'b list"
locale VT_nat = VT M for M :: "nat list"
locale VT_renamed_nat = VT N for N :: "nat list"

locale VH = fixes h :: "nat \<Rightarrow> nat" assumes hh: "h 0 = h 0"
locale VH_for = fixes k :: nat
sublocale VH_for \<subseteq> q: VH h for h by unfold_locales (rule refl)

locale VP = fixes a b :: nat assumes ab: "a + b = b + a"
locale VP_swap = fixes a b :: nat
sublocale VP_swap \<subseteq> p: VP b a by unfold_locales simp

ML \<open>
local open Link_Finder_Test
  val U = Link_Finder.Unchanged and R = Link_Finder.Renamed
  val Identity = Link_Finder.Identity and Renaming = Link_Finder.Renaming
  (*the distinct (kind, parameters) of the links from S whose note satisfies the test*)
  fun shapes thy loc S note =
    let val (_, F, _) = report thy loc in
      Link_Finder.links_of F |> map #2
      |> filter (fn l: Link_Finder.link => #source l = S andalso note (#1 (#note l)))
      |> map (fn l => (kind l, #params l)) |> distinct (op =)
    end
  fun any _ = true
  val thy = \<^theory>
  val algebra = Thy_Info.get_theory "HOL-Algebra.Algebra"
  val jacobson = Thy_Info.get_theory "Jacobson_Basic_Algebra.Ring_Theory"
  val VT = "Link_Finder_Verdicts_Test.VT"
  fun unchanged name = [{verdict = U, name = name, text = name}]
in
  val _ = check_all "verdicts"
   [("a renamed type variable: identity", fn () =>
      shapes thy "Link_Finder_Verdicts_Test.VT_renamed_tvar" VT any = [(Identity, unchanged "M")]),
    ("a type instance: identity", fn () =>
      shapes thy "Link_Finder_Verdicts_Test.VT_nat" VT any = [(Identity, unchanged "M")]),
    ("bounded_linear: the links from linear are identities", fn () =>
      shapes thy "Real_Vector_Spaces.bounded_linear" "Real_Vector_Spaces.linear" any =
        [(Identity, unchanged "f")]),
    ("coset_notation in normal_subgroup: identity", fn () =>
      shapes jacobson "Group_Theory.normal_subgroup" "Group_Theory.coset_notation" any =
        [(Identity, [{verdict = U, name = "composition", text = "(\<cdot>)"}])]),
    ("is_order_A in galois_connection: identity", fn () =>
      shapes algebra "Galois_Connection.galois_connection" "Galois_Connection.connection"
        (fn n => n = "is_order_A") = [(Identity, unchanged "G")]),
    ("module_hom_id in vector_space: an identity link whose pure rewrites mixin is not shown (D62)", fn () =>
      let
        val (_, F, _) = report thy "Vector_Spaces.vector_space"
        val ls = Link_Finder.links_of F |> map #2
          |> filter (fn l: Link_Finder.link => #note l = ("module_hom_id", 0))
      in
        not (null ls) andalso forall (fn l => kind l = Identity andalso
          #level l = Link_Finder.Level3_Approximate andalso null (#rewrites l) andalso
          null (#entities l)) ls
      end),
    ("a renaming with a new type: M is renamed to N", fn () =>
      shapes thy "Link_Finder_Verdicts_Test.VT_renamed_nat" VT any =
        [(Renaming, [{verdict = R, name = "M", text = "N"}])]),
    ("group_hom: G is renamed to H on the H side", fn () =>
      member (op =) (shapes algebra "Group.group_hom" "Group.group" any)
        (Renaming, [{verdict = R, name = "G", text = "H"}])),
    ("Vector_Spaces.linear: scale is renamed to (*b)", fn () =>
      member (op =) (shapes thy "Vector_Spaces.linear" "Modules.module" any)
        (Renaming, [{verdict = R, name = "scale", text = "(*b)"}])),
    ("a permutation of S's own parameters is a renaming", fn () =>
      shapes thy "Link_Finder_Verdicts_Test.VP_swap" "Link_Finder_Verdicts_Test.VP" any =
        [(Renaming, [{verdict = R, name = "a", text = "b"}, {verdict = R, name = "b", text = "a"}])]),
    ("a for-variable: h is renamed to ?h", fn () =>
      shapes thy "Link_Finder_Verdicts_Test.VH_for" "Link_Finder_Verdicts_Test.VH" any =
        [(Renaming, [{verdict = R, name = "h", text = "?h"}])])]
end
\<close>

end
