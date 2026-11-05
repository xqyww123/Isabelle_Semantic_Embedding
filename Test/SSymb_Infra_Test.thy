(* The theory marking of Performant_Isabelle_HOL.SSymb as uninterpreted: its constants
   get no record and do not cascade, its own facts get no record, and a downstream
   theorem mentioning a symbol is kept. *)
theory SSymb_Infra_Test
  imports Semantic_Embedding.Semantic_Embedding Performant_Isabelle_HOL.SSymb
begin

lemma sym_lemma: \<open>SYMBOL(foo) \<noteq> SYMBOL(bar)\<close> by simp

ML \<open>
  val {infra_const_rule, infra_thm_rule, is_uninterpreted_const, is_infra_type, ...} =
    Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val uninterpreted = Infra_Filter.Uninterpreted "uninterpreted_theory"
  val _ = \<^assert> (forall (fn c => infra_const_rule c = uninterpreted)
                    [\<^const_name>\<open>SSymb.Z\<close>, \<^const_name>\<open>SSymb.A\<close>,
                     \<^const_name>\<open>SSymb.B\<close>, \<^const_name>\<open>SSymb.C\<close>,
                     \<^const_name>\<open>SSymb.D\<close>, \<^const_name>\<open>SSymb.E\<close>,
                     \<^const_name>\<open>SSymb.F\<close>, \<^const_name>\<open>SSymb.symbol.mk_symbol\<close>])
  val _ = \<^assert> (is_uninterpreted_const \<^const_name>\<open>SSymb.Z\<close>)
  val _ = \<^assert> (is_infra_type \<^type_name>\<open>SSymb.symbol\<close>)
  (* SSymb's own facts: no record, by the theory marking (the bucket name covers both
     markings; the assertion also pins that no earlier rule fires first) *)
  val _ = \<^assert> (infra_thm_rule (\<^unchecked_name>\<open>SSymb.symbol_digit_inject\<close>,
                       @{thm SSymb.symbol_digit_inject(1)}) = SOME "infra_theory")
  (* a downstream theorem mentioning symbols: kept, no cascade *)
  val _ = \<^assert> (is_none (infra_thm_rule (\<^unchecked_name>\<open>SSymb_Infra_Test.sym_lemma\<close>, @{thm sym_lemma})))
\<close>

end
