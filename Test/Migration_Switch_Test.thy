(* The migration switch on the enumeration (ai-artifacts/CROSS_VERSION_MIGRATION_PLAN.md
   §3.1-3.2): with a migration context's handle, a persistent theory's entries carry
   their semantic digest and deps as a WIP theory's do, and the payload carries the
   handle; without one, a persistent theory's entries carry neither.  A WIP theory's
   payload never carries a handle.  Writes nothing to the database. *)
theory Migration_Switch_Test
  imports Semantic_Embedding.Semantic_Embedding
begin

definition mst_const :: nat where "mst_const = Suc 0"

ML \<open>
let
  val _ = Remote_Procedure_Calling.load ["Isabelle_Semantic_Embedding"]
  fun persistent thy = Theory_Hash.is_persistent (Theory_Hash.hash_of thy)
  fun has_digest (_, _, _, _, _, _, _, _, _, d, _) = is_some d
  fun has_deps (_, _, _, _, _, _, _, _, _, _, deps) = not (null deps)
  fun strip (_, nm, p, _, uk, _, _, _, _, _, _) = (nm, p, uk)

  (* a theory from the heap: persistent *)
  val heap = \<^theory>\<open>Product_Type\<close>
  val _ = \<^assert> (persistent heap)
  val off = Semantic_Store.enumerate_entries NONE (Context.Theory heap)
  val on = Semantic_Store.enumerate_entries (SOME 7) (Context.Theory heap)
  val _ = \<^assert> (is_none (#migration off))
  val _ = \<^assert> (not (exists has_digest (#entries off) orelse exists has_deps (#entries off)))
  val _ = \<^assert> (#migration on = SOME 7)
  val _ = \<^assert> (exists has_digest (#entries on) andalso exists has_deps (#entries on))
  (* the switch adds the two fields and changes neither the entries nor their keys *)
  val _ = \<^assert> (map strip (#entries off) = map strip (#entries on))

  (* this theory, still being loaded: WIP *)
  val _ = \<^assert> (not (persistent \<^theory>))
  val wip = Semantic_Store.enumerate_entries (SOME 7) (Context.Theory \<^theory>)
  val _ = \<^assert> (is_none (#migration wip))
  val _ = \<^assert> (exists has_digest (#entries wip))
in writeln "Migration_Switch_Test: OK" end
\<close>

end
