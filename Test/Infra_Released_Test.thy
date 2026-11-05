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
       fn () => infra_const_rule \<^const_name>\<open>Orderings.ord.max\<close> = Infra_Filter.Kept),
    ("a note of a class's locale is not infrastructure",
       fn () => is_none (rule \<^unchecked_name>\<open>Lattices.linorder.le_max_iff_disj\<close>)),
    ("an interpretation fact is not infrastructure",
       fn () => is_none (rule \<^unchecked_name>\<open>Infra_Released_Test.lp_rev.le_max_iff_disj\<close>)),
    ("a partial_function fact (ccpo.fixp) is not infrastructure",
       fn () => is_none (rule \<^unchecked_name>\<open>Partial_Function.option.fixp_induct_uc\<close>)),
    ("a class-definition theorem is infrastructure",
       fn () => rule \<^unchecked_name>\<open>Orderings.ord_class.max_dict\<close> = SOME "class_definition"),
    ("a theorem named *_dict that is not one is kept",
       fn () => is_none (rule \<^unchecked_name>\<open>Infra_Released_Test.lp_max_dict\<close>)),
    ("a simplifier .cong is infrastructure",
       fn () => rule \<^unchecked_name>\<open>Orderings.ord.max.cong\<close> = SOME "simplifier_cong"),
    ("a congruence rule named cong is kept",
       fn () => is_none (rule \<^unchecked_name>\<open>Groups_Big.comm_monoid_add_class.sum.cong\<close>)),
    ("a reflexive theorem not named cong is kept",
       fn () => is_none (rule \<^unchecked_name>\<open>Infra_Released_Test.lp_self\<close>)),
    ("a locale-form _sumC constant falls to sumC_graph",
       fn () => infra_const_rule
                  \<^const_name>\<open>Bit_Operations.linordered_euclidean_semiring_bit_operations.or_num_sumC\<close> =
                Infra_Filter.Infra "sumC_graph")]
end
\<close>

end
