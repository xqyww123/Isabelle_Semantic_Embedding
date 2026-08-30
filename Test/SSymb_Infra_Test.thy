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
                    ["SSymb.Z", "SSymb.A", "SSymb.B", "SSymb.C", "SSymb.D", "SSymb.E", "SSymb.F",
                     "SSymb.symbol.mk_symbol"])
  val _ = \<^assert> (is_uninterpreted_const "SSymb.Z")
  val _ = \<^assert> (is_infra_type "SSymb.symbol")
  (* SSymb's own facts: no record, by the theory marking (the bucket name covers both
     markings; the assertion also pins that no earlier rule fires first) *)
  val _ = \<^assert> (infra_thm_rule ("SSymb.mk_symbol_cong", @{thm SSymb.mk_symbol_cong})
                    = SOME "infra_theory")
  (* a downstream theorem mentioning symbols: kept, no cascade *)
  val _ = \<^assert> (is_none (infra_thm_rule ("SSymb_Infra_Test.sym_lemma", @{thm sym_lemma})))
\<close>

end
