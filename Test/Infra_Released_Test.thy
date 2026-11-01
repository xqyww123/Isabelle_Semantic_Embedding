(*
  INFRA_FILTER_CLASS_VARIANT_PLAN.md §4.8: with the class_variant rule retired, a
  locale-form class operation and the theorems that mention one are judged like any
  other entity; two statement rules hide the class-definition theorems (§4.2) and the
  simplifier's `.cong` (§4.3), and nothing else of the same name or shape.
*)
theory Infra_Released_Test
  imports Link_Finder_Test_Base
begin

interpretation lp_rev: linorder "\<lambda>x y::nat. y \<le> x" "\<lambda>x y. y < x"
  by unfold_locales auto

lemma lp_max_dict: "max (x::nat) y = max y x"
  by (rule max.commute)

lemma lp_self: "(x::nat) \<equiv> x"
  by (rule reflexive)

ML \<open>
local
  open Link_Finder_Test
  val ctxt = \<^context>
  val {infra_const_rule, infra_thm_rule, ...} = Infra_Filter.gen_infra_filters (Context.Proof ctxt)
  fun rule name = infra_thm_rule (name, Proof_Context.get_thm ctxt name)
in
  val _ = check_all "the released entities and the two statement rules"
   [("a locale-form class operation is kept",
       fn () => infra_const_rule "Orderings.ord.max" = Infra_Filter.Kept),
    ("a note of a class's locale is not infrastructure",
       fn () => is_none (rule "Lattices.linorder.le_max_iff_disj")),
    ("an interpretation fact is not infrastructure",
       fn () => is_none (rule "Infra_Released_Test.lp_rev.le_max_iff_disj")),
    ("a partial_function fact (ccpo.fixp) is not infrastructure",
       fn () => is_none (rule "Partial_Function.option.fixp_induct_uc")),
    ("a class-definition theorem is infrastructure",
       fn () => rule "Orderings.ord_class.max_dict" = SOME "class_definition"),
    ("a theorem named *_dict that is not one is kept",
       fn () => is_none (rule "Infra_Released_Test.lp_max_dict")),
    ("a simplifier .cong is infrastructure",
       fn () => rule "Orderings.ord.max.cong" = SOME "simplifier_cong"),
    ("a congruence rule named cong is kept",
       fn () => is_none (rule "Groups_Big.comm_monoid_add_class.sum.cong")),
    ("a reflexive theorem not named cong is kept",
       fn () => is_none (rule "Infra_Released_Test.lp_self")),
    ("a locale-form _sumC constant falls to sumC_graph",
       fn () => infra_const_rule
                  "Bit_Operations.linordered_euclidean_semiring_bit_operations.or_num_sumC" =
                Infra_Filter.Infra "sumC_graph")]
end
\<close>

end
