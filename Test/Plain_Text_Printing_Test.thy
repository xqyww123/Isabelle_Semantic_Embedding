(*
  Plain-text printing (LINK_LAYER_PLAN.md §9 R13, §8 step 4a): the record printer
  writes no markup, and every markup stripper keeps only visible text.  Loaded
  from a file (PIDE print mode), the old hand-written strippers kept the hidden
  body of a typing element, so the class parameter 0 printed as 'a0.  And the
  record printer fixes the print options a context may set (§4.2, §8 step 4).
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
in
  val _ = check ("the record printer gives " ^ quote (Explain_Term.string_of_term ctxt t))
    (Explain_Term.string_of_term ctxt t = "0 + x = x")
  val T = Syntax.read_typ ctxt "'b::order \<Rightarrow> nat"
  val _ = check ("the type printer gives " ^ quote (Explain_Term.string_of_typ ctxt T))
    (Explain_Term.string_of_typ ctxt T = "'b::order \<Rightarrow> nat")
  val _ = ["natural", "pretty"] |> List.app (fn f =>
    let val s = RPC_Pretty.string_of_term f (Context.Proof ctxt) t
    in check ("RPC_Pretty.string_of_term " ^ quote f ^ " gives " ^ quote s) (s = "0 + x = x") end)
  val long = Syntax.read_term ctxt
    "(0 + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x) = x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x + x"
  val _ = check "a long term is printed on one line"
    (not (exists (fn c => c = #"\n") (String.explode (RPC_Pretty.plain_string (Syntax.pretty_term ctxt long)))))
  val _ = check "no markup character in the printed text"
    (not (exists (fn c => c = #"\005" orelse c = #"\006")
      (String.explode (Explain_Term.string_of_term ctxt t))))
end
\<close>

end

section \<open>The print options the record printer fixes\<close>

text \<open>\<open>Explain_Term.string_of_term\<close> sets five print options to their defaults, so that a
  context's setting does not reach a text.  One row per option: at another value the option
  changes the stock printer's text of the row's term, so the row is not vacuous, and leaves the
  record printer's text as at the defaults.\<close>

consts map :: nat  \<comment> \<open>its base name is \<open>List.map\<close>'s, so its short name is not unique\<close>

ML \<open>
local
  fun check msg b = if b then () else error ("Plain_Text_Printing_Test: " ^ msg)
  val ctxt = \<^context>
  fun stock ctxt t = RPC_Pretty.plain_string (Syntax.pretty_term ctxt t)
  val f = Abs ("x", \<^typ>\<open>nat\<close>, Free ("f", \<^typ>\<open>nat \<Rightarrow> nat\<close>) $ Bound 0)
  val rows =
   [("names_long", Config.put Name_Space.names_long true, \<^term>\<open>Suc 0\<close>),
    ("names_short", Config.put Name_Space.names_short true, \<^term>\<open>Set.filter P A\<close>),
    ("names_unique", Config.put Name_Space.names_unique false,
      \<^term>\<open>Plain_Text_Printing_Test.map\<close>),
    ("eta_contract", Config.put Syntax_Trans.eta_contract false, f),
    ("show_abbrevs", Config.put Proof_Context.show_abbrevs false, \<^term>\<open>(x::nat) \<noteq> y\<close>)]
in
  val _ = rows |> List.app (fn (name, set, t) =>
    let val ctxt' = set ctxt in
      check (name ^ ": the stock printer shows the option: " ^
          quote (stock ctxt t) ^ " and " ^ quote (stock ctxt' t))
        (stock ctxt' t <> stock ctxt t);
      check (name ^ ": the record printer does not: " ^ quote (Explain_Term.string_of_term ctxt' t))
        (Explain_Term.string_of_term ctxt' t = Explain_Term.string_of_term ctxt t)
    end)
end
\<close>

end
