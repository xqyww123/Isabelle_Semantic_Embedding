(* Regression tests for the user-declared attributes
   `infra_constant` / `uninterpreted_constant` / `infra_type` / `infra_thm` (add + `del`),
   the constant cascade (and its absence for uninterpreted constants), the
   by-proposition theorem matching (incl. trivial-shape warn-but-store),
   and the locale G#4 case (a locale-body declaration filters the exported instance).
   Each ML block re-fetches the filters and asserts; a build failure here = a regression. *)
theory Infra_Decl_Test
  imports Semantic_Embedding.Semantic_Embedding
begin

lemma foo: "rev (rev xs) = xs" by simp

(* baseline: nothing declared *)
ML \<open>
  val {is_uninterpreted_const, is_infra_type, is_infra_thm, is_declared_infra_thm, ...} =
    Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (is_none is_declared_infra_thm)
  val _ = \<^assert> (not (is_uninterpreted_const "List.rev"))
  val _ = \<^assert> (not (is_infra_type "List.list"))
  val _ = \<^assert> (not (is_infra_thm ("Infra_Decl_Test.foo", @{thm foo})))
\<close>

(* infra_constant: marks the constant AND cascades to theorems mentioning it *)
declare [[infra_constant List.rev]]
ML \<open>
  val {is_uninterpreted_const, is_infra_thm, infra_const_rule, ...} =
    Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (is_uninterpreted_const "List.rev")
  val _ = \<^assert> (infra_const_rule "List.rev" = Infra_Filter.Infra "declared")
  val _ = \<^assert> (is_infra_thm ("Infra_Decl_Test.foo", @{thm foo}))   (* cascade: foo mentions rev *)
\<close>

(* infra_constant del: undoes both the constant and the cascade *)
declare [[infra_constant del List.rev]]
ML \<open>
  val {is_uninterpreted_const, is_infra_thm, is_declared_infra_thm, ...} =
    Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (not (is_uninterpreted_const "List.rev"))
  val _ = \<^assert> (not (is_infra_thm ("Infra_Decl_Test.foo", @{thm foo})))
  val _ = \<^assert> (is_none is_declared_infra_thm)
\<close>

(* uninterpreted_constant: no record for the constant, NO cascade; and it is not a
   declaration the persistent-cache re-filter needs to act on *)
declare [[uninterpreted_constant List.rev]]
ML \<open>
  val {is_uninterpreted_const, is_infra_thm, is_declared_infra_thm, infra_const_rule, ...} =
    Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (is_uninterpreted_const "List.rev")
  val _ = \<^assert> (infra_const_rule "List.rev" = Infra_Filter.Uninterpreted "declared")
  val _ = \<^assert> (not (is_infra_thm ("Infra_Decl_Test.foo", @{thm foo})))
  val _ = \<^assert> (is_none is_declared_infra_thm)
\<close>

(* a later declaration of the same constant replaces the earlier one (last wins) *)
declare [[infra_constant List.rev]]
ML \<open>
  val {is_infra_thm, is_declared_infra_thm, ...} = Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (is_infra_thm ("Infra_Decl_Test.foo", @{thm foo}))
  val _ = \<^assert> (the is_declared_infra_thm ("Infra_Decl_Test.foo", @{thm foo}))
\<close>
declare [[uninterpreted_constant List.rev]]
ML \<open>
  val {is_infra_thm, ...} = Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (not (is_infra_thm ("Infra_Decl_Test.foo", @{thm foo})))
\<close>

(* del of either attribute clears the verdict *)
declare [[infra_constant del List.rev]]
ML \<open>
  val {is_uninterpreted_const, ...} = Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (not (is_uninterpreted_const "List.rev"))
\<close>

(* infra_type + del *)
declare [[infra_type List.list]]
ML \<open>
  val {is_infra_type, ...} = Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (is_infra_type "List.list")
\<close>
declare [[infra_type del List.list]]
ML \<open>
  val {is_infra_type, ...} = Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (not (is_infra_type "List.list"))
\<close>

(* infra_thm (attached fact attribute) + del *)
declare foo[infra_thm]
ML \<open>
  val {is_infra_thm, ...} = Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (is_infra_thm ("Infra_Decl_Test.foo", @{thm foo}))
\<close>
declare foo[infra_thm del]
ML \<open>
  val {is_infra_thm, ...} = Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (not (is_infra_thm ("Infra_Decl_Test.foo", @{thm foo})))
\<close>

(* trivially-shaped theorem: warns but is still honoured (stored/matched) *)
lemma triv: "(x::nat) = x" by simp
declare triv[infra_thm]
ML \<open>
  val {is_infra_thm, ...} = Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val _ = \<^assert> (is_infra_thm ("Infra_Decl_Test.triv", @{thm triv}))
\<close>

(* the persistent-cache re-filter with its gate OPEN (a theorem is declared): an
   uninterpreted constant must not make it drop theorems mentioning that constant *)
declare [[uninterpreted_constant List.rev]]
ML \<open>
  val {is_declared_infra_thm, ...} = Infra_Filter.gen_infra_filters (Context.Proof \<^context>)
  val declared = the is_declared_infra_thm
  val _ = \<^assert> (declared ("Infra_Decl_Test.triv", @{thm triv}))
  val _ = \<^assert> (not (declared ("Infra_Decl_Test.foo", @{thm foo})))
\<close>
declare [[uninterpreted_constant del List.rev]]

(* G#4: a locale-body declaration filters the per-interpretation EXPORTED instance *)
locale L = fixes x :: nat assumes ax: "x = x + 0"
begin
  declare ax[infra_thm]
end

interpretation I: L 0 by unfold_locales simp

ML \<open>
  val ctxt = \<^context>
  val {is_infra_thm, ...} = Infra_Filter.gen_infra_filters (Context.Proof ctxt)
  (* the exported instance, both as antiquotation and as the collector enumerates it *)
  val _ = \<^assert> (is_infra_thm ("Infra_Decl_Test.I.ax", @{thm I.ax}))
  val i_ax = Facts.dest_static false [] (Proof_Context.facts_of ctxt)
        |> filter (fn (nm, _) => String.isSuffix "I.ax" nm)
  val _ = \<^assert> (not (null i_ax))
  val _ = \<^assert> (forall (fn (nm, ths) => forall (fn th => is_infra_thm (nm, th)) ths) i_ax)
\<close>

end
