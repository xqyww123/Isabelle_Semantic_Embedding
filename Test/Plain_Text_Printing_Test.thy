(*
  Plain-text printing: every markup stripper keeps only visible text, and the
  plain printers write no markup.  Loaded from a file (PIDE print mode), the old
  hand-written strippers kept the hidden body of a typing element, so the class
  parameter 0 printed as 'a0.
*)
theory Plain_Text_Printing_Test
  imports Semantic_Embedding.Semantic_Embedding
begin

ML \<open>
local
  fun check msg b = if b then () else error ("Plain_Text_Printing_Test: " ^ msg)
  (*0 wrapped in a typing element whose hidden body is the type 'a, as the printer
    writes it in PIDE mode*)
  val marked =
    YXML.string_of_body [XML.wrap_elem ((Markup.typing, [XML.Text "'a"]), [XML.Text "0"])]
in
  val _ = check "the test string carries the hidden body" (String.isSubstring "'a" marked)
  val _ = [("Remote_Procedure_Calling", Remote_Procedure_Calling.trim_markup),
           ("RPC_Pretty", RPC_Pretty.trim_markup),
           ("Premise_Embedding_Context_Info", Premise_Embedding_Context_Info.trim_markup)]
    |> List.app (fn (name, trim) =>
      check (name ^ ".trim_markup gives " ^ quote (trim marked)) (trim marked = "0"))
end
\<close>

context linordered_field begin

ML \<open>
local
  fun check msg b = if b then () else error ("Plain_Text_Printing_Test: " ^ msg)
  val ctxt = \<^context>
  val t = Syntax.read_term ctxt "0 + x = x"
  val printed = Premise_Embedding_Context_Info.string_of_term ctxt t
in
  val _ = check ("the plain printer gives " ^ quote printed) (printed = "0 + x = x")
  val _ = ["natural", "pretty"] |> List.app (fn f =>
    let val s = RPC_Pretty.string_of_term f (Context.Proof ctxt) t
    in check ("RPC_Pretty.string_of_term " ^ quote f ^ " gives " ^ quote s) (s = "0 + x = x") end)
  val long = Syntax.read_term ctxt
    "(0 + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x) = x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x"
  val _ = check "a long term is printed on one line"
    (not (exists (fn c => c = #"\n") (String.explode (RPC_Pretty.plain_string (Syntax.pretty_term ctxt long)))))
  val _ = check "no markup character in the printed text"
    (not (exists (fn c => c = #"\005" orelse c = #"\006") (String.explode printed)))
end
\<close>

end

end
