theory Induct_Rules_Test
  imports "../Semantic_Embedding"
begin

section \<open>Local definitions to test extraction\<close>

datatype color = Red | Green | Blue

fun color_to_nat :: "color \<Rightarrow> nat" where
  "color_to_nat Red = 0"
| "color_to_nat Green = 1"
| "color_to_nat Blue = 2"

inductive reachable :: "nat \<Rightarrow> nat \<Rightarrow> bool" where
  self: "reachable x x"
| step: "reachable x y \<Longrightarrow> reachable x (Suc y)"

section \<open>Test: extraction from Theory_Structure\<close>

ML \<open>
let
  val context = Context.Proof @{context}

  val induct_rules = Theory_Structure.get_induction_rules_with_positions context
  val case_rules  = Theory_Structure.get_case_split_rules_with_positions context

  val _ = writeln ("Induction rules extracted (this theory): " ^
                   string_of_int (length induct_rules))
  val _ = writeln ("Case-split rules extracted (this theory): " ^
                   string_of_int (length case_rules))

  (* All names should start with this theory's prefix *)
  val thy_prefix = "Induct_Rules_Test."
  val _ = List.app (fn (name, _, _) =>
    if String.isPrefix thy_prefix name then ()
    else error ("Induction rule not from this theory: " ^ name)
  ) induct_rules
  val _ = List.app (fn (name, _, _) =>
    if String.isPrefix thy_prefix name then ()
    else error ("Case-split rule not from this theory: " ^ name)
  ) case_rules

  (* Verify name = Thm.get_name_hint *)
  val _ = List.app (fn (name, _, thm) =>
    let val hint = Thm.get_name_hint thm
    in if name = hint then ()
       else error ("Name mismatch: entry=" ^ name ^ " hint=" ^ hint)
    end) induct_rules
  val _ = List.app (fn (name, _, thm) =>
    let val hint = Thm.get_name_hint thm
    in if name = hint then ()
       else error ("Name mismatch: entry=" ^ name ^ " hint=" ^ hint)
    end) case_rules

  (* Spot-check: known rules should be present in the extraction *)
  fun has_thm thm rules = exists (fn (_, _, t) => Thm.eq_thm (t, thm)) rules

  val _ = List.app (fn (thm, label) =>
    if has_thm thm induct_rules
    then writeln ("  [OK] " ^ label ^ " found in induction rules")
    else error (label ^ " NOT found in induction rules")
  ) [(@{thm color.induct}, "color.induct"),
     (@{thm reachable.inducts}, "reachable.inducts")]

  val _ = List.app (fn (thm, label) =>
    if has_thm thm case_rules
    then writeln ("  [OK] " ^ label ^ " found in case-split rules")
    else error (label ^ " NOT found in case-split rules")
  ) [(@{thm color.exhaust}, "color.exhaust"),
     (@{thm reachable.cases}, "reachable.cases")]

  (* Universal key construction: all 32 bytes *)
  val _ = List.app (fn (name, _, thm) =>
    let val uk = Universal_Key.key_of NONE context (Universal_Key.Induction_Rule thm)
    in if Word8Vector.length uk = 32 then ()
       else error ("Bad key length for " ^ name)
    end) induct_rules
  val _ = List.app (fn (name, _, thm) =>
    let val uk = Universal_Key.key_of NONE context (Universal_Key.Case_Split_Rule thm)
    in if Word8Vector.length uk = 32 then ()
       else error ("Bad key length for " ^ name)
    end) case_rules
  val _ = writeln "  [OK] All universal keys are 32 bytes"

  (* No duplicates *)
  val induct_names = map #1 induct_rules
  val _ = if length induct_names = length (distinct (op =) induct_names) then ()
          else error "Duplicate names in induction rules"
  val case_names = map #1 case_rules
  val _ = if length case_names = length (distinct (op =) case_names) then ()
          else error "Duplicate names in case-split rules"
  val _ = writeln "  [OK] No duplicate names"

  (* Test build_entries mk_prop_str: pretty-printing propositions must succeed
     and produce non-empty strings for all extracted rules *)
  val ctxt = Context.proof_of context
  val pp = Syntax.string_of_term ctxt
  val _ = List.app (fn (name, _, thm) =>
    let val prop_str = pp (Thm.prop_of thm)
    in if prop_str = "" then error ("Empty prop_str for induction rule " ^ name)
       else ()
    end) induct_rules
  val _ = List.app (fn (name, _, thm) =>
    let val prop_str = pp (Thm.prop_of thm)
    in if prop_str = "" then error ("Empty prop_str for case-split rule " ^ name)
       else ()
    end) case_rules
  (* Spot-check: color.induct prop should mention Red, Green, Blue *)
  val color_induct_prop = pp (Thm.prop_of @{thm color.induct})
  val _ = if String.isSubstring "Red" color_induct_prop
             andalso String.isSubstring "Green" color_induct_prop
             andalso String.isSubstring "Blue" color_induct_prop
          then writeln ("  [OK] color.induct prop mentions all constructors")
          else error ("color.induct prop missing constructors: " ^ color_induct_prop)
  val _ = writeln ("  [OK] All prop_str non-empty (" ^
                   string_of_int (length induct_rules + length case_rules) ^ " rules)")

  (* Print all extracted rules *)
  val _ = writeln "\nAll induction rules:"
  val _ = List.app (fn (name, _, thm) =>
    let val consumes = Rule_Cases.get_consumes thm
        val (info, _) = Rule_Cases.get thm
        val case_names = map (fst o fst) info
    in writeln ("  " ^ name ^
                "  consumes=" ^ string_of_int consumes ^
                "  cases=[" ^ commas case_names ^ "]")
    end) induct_rules

  val _ = writeln "\nAll case-split rules:"
  val _ = List.app (fn (name, _, thm) =>
    let val consumes = Rule_Cases.get_consumes thm
        val (info, _) = Rule_Cases.get thm
        val case_names = map (fst o fst) info
    in writeln ("  " ^ name ^
                "  consumes=" ^ string_of_int consumes ^
                "  cases=[" ^ commas case_names ^ "]")
    end) case_rules

in writeln "\nAll checks passed." end
\<close>

end
