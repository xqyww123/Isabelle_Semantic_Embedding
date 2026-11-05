signature EXPLAIN_TERM = sig
  (* The one-line plain-text printers of a stored record's expr; a link's
     texts (Link_Finder) use the same printer. *)
  val string_of_term : Proof.context -> term -> string
  val string_of_typ : Proof.context -> typ -> string
  val raw_lambda_printer : Proof.context -> term -> string
  (* the constants of the terms that the filter keeps, in order of first
     occurrence, each once: the first occurrence and its universal key *)
  val collect_constants : (string -> bool) -> Context.generic -> term list ->
    (term * Universal_Key.universal_key) list
  val make_desugar_callback : Context.generic -> Remote_Procedure_Calling.callback'
  val make_resolve_notation_callback : Context.generic -> Remote_Procedure_Calling.callback'
end

structure Explain_Term : EXPLAIN_TERM = struct

(* --- Plain-text printers --- *)

(* plain text: embedded/serialized strings carry no markup and no line breaks *)
val string_of_pretty = RPC_Pretty.plain_string

(* the name, eta-contraction and abbreviation options at their defaults, so that
   a context's `declare [[names_long]]` does not reach a text (LINK_LAYER_PLAN.md
   §4.2, D54) *)
fun string_of_term ctxt =
    let val ctxt' = ctxt
              |> Config.put Printer.show_types false
              |> Config.put Printer.show_sorts false
              |> Config.put Printer.show_markup false
              |> Config.put Printer.show_structs false
              |> Config.put Printer.show_question_marks true
              |> Config.put Name_Space.names_long false
              |> Config.put Name_Space.names_short false
              |> Config.put Name_Space.names_unique true
              |> Config.put Syntax_Trans.eta_contract true
              |> Config.put Proof_Context.show_abbrevs true
     in Syntax.pretty_term ctxt' #> string_of_pretty
    end

fun string_of_typ ctxt =
    let val ctxt' = ctxt
              |> Config.put Printer.show_sorts true
              |> Config.put Printer.show_markup false
     in Syntax.pretty_typ ctxt' #> string_of_pretty
    end

(* --- Compact term printer --- *)

fun try_dest_numeral t =
  try HOLogic.dest_number t |> Option.map snd

fun strip_app (f $ x) = let val (head, args) = strip_app f in (head, args @ [x]) end
  | strip_app t = (t, [])

fun resolve_bound env i =
  if i < length env then nth env i else "?b" ^ string_of_int i

fun is_atom (Const _) = true | is_atom (Free _) = true
  | is_atom (Var _) = true | is_atom (Bound _) = true
  | is_atom t = is_some (try_dest_numeral t)

fun is_binder ctxt t =
  (can Term.type_of t andalso is_some (Case_Translation.strip_case ctxt false t))
  orelse (case t of Const(\<^const_name>\<open>Let\<close>, _) $ _ $ Abs _ => true
                  | Abs _ => true | _ => false)

fun pt ctxt env parens t : string list =
  case try_dest_numeral t of
    SOME n => [string_of_int n]
  | NONE =>
  case (if can Term.type_of t then Case_Translation.strip_case ctxt false t else NONE) of
    SOME (scrutinee, clauses) =>
      let
        fun pt_rhs rhs = pt ctxt env (is_binder ctxt rhs) rhs
        fun print_clause (pat, rhs) =
          pt ctxt env false pat @ [" \<Rightarrow> "] @ pt_rhs rhs
        val inner = ["case "] @ pt ctxt env (is_binder ctxt scrutinee) scrutinee
          @ [" of "]
          @ flat (Library.separate [" | "] (map print_clause clauses))
      in if parens then ["("] @ inner @ [")"] else inner end
  | NONE =>
  case t of
    Const(\<^const_name>\<open>Let\<close>, _) $ value $ Abs(name, T, body) =>
      let
        val body' = Term.subst_bound (Free(name, T), body)
        val inner = ["let ", name, " = "] @ pt ctxt env (is_binder ctxt value) value
          @ [" in "] @ pt ctxt (name :: env) false body'
      in if parens then ["("] @ inner @ [")"] else inner end
  |
    Const(name, _) => [Long_Name.base_name name]
  | Free(name, _) => [name]
  | Var((name, i), _) =>
      [if i = 0 then "?" ^ name else "?" ^ name ^ "." ^ string_of_int i]
  | Bound i => [resolve_bound env i]
  | Abs(name, T, body) =>
      let val body' = Term.subst_bound (Free(name, T), body)
          val inner = ["\<lambda>", name, ". "] @ pt ctxt (name :: env) false body'
      in if parens then ["("] @ inner @ [")"] else inner end
  | _ $ _ =>
      let val (head, args) = strip_app t
          fun needs_parens a = not (is_atom a)
          val parts = pt ctxt env (needs_parens head) head
            @ maps (fn a => [" "] @ pt ctxt env (needs_parens a) a) args
      in if parens then ["("] @ parts @ [")"] else parts end

fun raw_lambda_printer ctxt t =
  let val ctxt' = Config.put Case_Translation.show_cases false ctxt
      val [t'] = Syntax.uncheck_terms ctxt' [t]
  in String.concat (pt ctxt' [] false t') end


(* --- Constant extraction and filtering --- *)

fun collect_constants keep context ts =
  let
    val seen = Strhashtab.empty 64
    fun add (c as Const (name, _)) acc =
          if Strhashtab.defined seen name orelse not (keep name) then acc
          else
            let val _ = Strhashtab.update seen (name, ())
            in (c, Universal_Key.key_of NONE context (Universal_Key.Constant name)) :: acc end
      | add _ acc = acc
  in rev (fold (Term.fold_aterms add) ts []) end

(* Collect the constants worth ANNOTATING for the interpretation agent:
   infrastructure constants and Isabelle standard-library constants
   (declared in Main or its ancestors) are dropped — the agent knows the
   base vocabulary, and the semantic DB does not record it. Do NOT use
   this for resolution questions ("which constant does this notation
   denote") — see make_resolve_notation_callback. *)
fun extract_nontrivial_constants (ctxt : Proof.context) (checked_term : term)
    : (string * Word8Vector.vector) list =
  let
    val context = Context.Proof ctxt
    val const_space = Consts.space_of (Proof_Context.consts_of ctxt)
    val {is_uninterpreted_const, ...} = Infra_Filter.gen_infra_filters context

    val main_thy_ancestors =
      let val main_thy = Build.get_theory "Main"
      in Strhashtab.make_set
           (Context.theory_long_name main_thy ::
            map Context.theory_long_name (Theory.ancestors_of main_thy))
      end

    fun is_base_const name =
      case try (Name_Space.the_entry const_space) name of
        NONE => false
      | SOME entry => Strhashtab.defined main_thy_ancestors (#theory_long_name entry)

  in
    collect_constants (fn name => not (is_uninterpreted_const name orelse is_base_const name))
      context [checked_term]
    |> map (fn (c, uk) => (#1 (dest_Const c), uk))
  end


(* --- RPC callback factories --- *)

fun context_at pos_opt (fallback : Context.generic) : Context.generic =
  case pos_opt of
    NONE => fallback
  | SOME (file, offset) =>
      (case PIDE_State.context_at_position
              {re_eval_cache = true} fallback file offset of
         SOME ctx => ctx
       | NONE => fallback)

fun make_desugar_callback (fallback : Context.generic)
    : Remote_Procedure_Calling.callback' =
  let open MessagePackBinIO.Pack MessagePackBinIO.Unpack in
  Remote_Procedure_Calling.mk_callback {
    name = \<^unchecked_name>\<open>explain_term.desugar_and_explain\<close>,
    on_interrupt = Remote_Procedure_Calling.Reraise,
    arg_schema = unpackPair (
      unpackOption (unpackPair (unpackString, unpackInt)),
      unpackString),
    ret_schema = packPair (
      packString,
      packList (packPair (packString, packBytes))),
    function = fn (pos_opt, term_string) =>
      let
        val context = context_at pos_opt fallback
        val ctxt = Context.proof_of context
        (* mode_abbrev: type-check WITHOUT expanding abbreviations, so an
           abbreviation resolves to its own constant, not its expansion *)
        val checked = Proof_Context.read_term_abbrev ctxt term_string
        val compact = raw_lambda_printer ctxt checked
        val constants = extract_nontrivial_constants ctxt checked
      in (compact, constants) end,
    timeout = SOME (Time.fromSeconds 30)
  }
  end

(* Resolve a notation probe (e.g. "x \<le> y") to the constant it denotes.
   This answers a parsing-fact question — "which constant does this
   notation stand for" — so the head constant is reported with NO
   nontrivial filtering (unlike the annotation-oriented desugar callback).
   Returns NONE when the probe's head is not a constant. *)
fun make_resolve_notation_callback (fallback : Context.generic)
    : Remote_Procedure_Calling.callback' =
  let open MessagePackBinIO.Pack MessagePackBinIO.Unpack in
  Remote_Procedure_Calling.mk_callback {
    name = \<^unchecked_name>\<open>explain_term.resolve_notation\<close>,
    on_interrupt = Remote_Procedure_Calling.Reraise,
    arg_schema = unpackPair (
      unpackOption (unpackPair (unpackString, unpackInt)),
      unpackString),
    ret_schema = packOption (packTuple3 (packString, packBytes, packString)),
    function = fn (pos_opt, probe_string) =>
      let
        val context = context_at pos_opt fallback
        val ctxt = Context.proof_of context
        val checked = Proof_Context.read_term_abbrev ctxt probe_string
      in
        case Term.head_of checked of
          Const (name, _) =>
            let val uk = Universal_Key.key_of NONE context (Universal_Key.Constant name)
            in SOME (name, uk, raw_lambda_printer ctxt checked) end
        | _ => NONE
      end,
    timeout = SOME (Time.fromSeconds 30)
  }
  end

end
