(* Regression test for WHERE the interpretation driver is read.

   `Semantic_Embedding.interpretation_driver` names the agent backend (and
   optionally its model) for a semantic-interpretation run.  It is read exactly
   once, by Semantic_Store.interpret_with_parallel, from a context the CALLER
   supplies -- never per cone node.  The reason is the third assertion below: a
   `declare` flows only parent->child through the theory graph, so a lookup made
   while interpreting an ancestor (interpret_cone rebuilds a context from each
   node's own theory) reads the empty default instead of what the user declared.
   The whole cone would then run on the default backend, silently, with the
   theory records faithfully recording that default -- the cost saving the
   option exists for, quietly undone.

   A build failure here = a regression. *)
theory Interpretation_Driver_Config_Test
  imports Semantic_Embedding.Semantic_Embedding
begin

ML \<open>
  fun driver_in context = Config.get_generic context Semantic_Store.interpretation_driver
\<close>

(* Undeclared reads as the empty string, which is this package's one spelling of
   "not set here": Python then falls through to INTERPRETATION_DRIVER and
   finally to ClaudeCode. *)
ML \<open>
  val _ = \<^assert> (driver_in (Context.Proof \<^context>) = "")
  val _ = \<^assert> (driver_in (Context.Theory \<^theory>) = "")
\<close>

declare [[Semantic_Embedding.interpretation_driver = "Codex.gpt-5.5"]]

(* Visible from here on, in this theory. *)
ML \<open>
  val _ = \<^assert> (driver_in (Context.Proof \<^context>) = "Codex.gpt-5.5")
  val _ = \<^assert> (driver_in (Context.Theory \<^theory>) = "Codex.gpt-5.5")
\<close>

(* ...and NOT visible from an ancestor.  This is the reproduction: every parent
   of this theory is a cone node of a run rooted here, and reading the option
   from such a node -- as a per-node lookup would -- yields the default. *)
ML \<open>
  val _ = \<^assert> (not (null (Theory.parents_of \<^theory>)))
  val _ = List.app (fn parent => \<^assert> (driver_in (Context.Theory parent) = ""))
            (Theory.parents_of \<^theory>)
\<close>

(* The model half is optional; the driver name alone is a legal value and leaves
   the model to that backend's own default. *)
declare [[Semantic_Embedding.interpretation_driver = "ClaudeCode"]]
ML \<open>
  val _ = \<^assert> (driver_in (Context.Proof \<^context>) = "ClaudeCode")
\<close>

(* The prefilter's embedding model takes the same road (SEMANTIC_CHANGE_GATE_PLAN.md
   §5.6, D5): interpret_with_parallel makes the run's Config.lookup callback from the
   user's context and threads the callback VALUE down, so a cone node's context cannot
   serve it.  What is left to assert is the list itself: the callback is on it, and
   once -- the RPC layer resolves a duplicated name by list order, so a second
   Config.lookup among the entity callbacks would decide the answer silently.  No
   Python, no LLM. *)
ML \<open>
  val config_cb =
    Config.make_config_lookup_callback
      (Context_Callbacks.static_context_unpacker (Context.Proof \<^context>))
  val names =
    map #name (Semantic_Store.interpret_file_callbacks config_cb (Context.Proof \<^context>))
  val _ = \<^assert> (length (filter (fn n => n = "Config.lookup") names) = 1)
\<close>

end
