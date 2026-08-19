theory Entity_Position_Refusal_Test
  imports Semantic_Embedding.Semantic_Embedding
begin

text \<open>
  T9's refusal half (ENTITY_POSITION_PLAN.md \<section>12, \<section>16.4): when the
  check_theorem_name_in_file RPC fails, enumerate_entries degrades
  (tie_break_degraded = true), and backfill_theory must REFUSE the theory --
  warn, count it under `refused`, and never call the backfill_positions write
  RPC; backfill_cone then raises "backfill_positions stopped: ..." at the end.

  This theory MUST be evaluated in a process that has NEVER run
  Remote_Procedure_Calling.load ["Isabelle_Semantic_Embedding"].  In such a
  process the ephemeral RPC host auto-launched on first use serves only the
  base Isabelle_RPC_Host procedures: xxhash128_theory works (so
  Theory_Hash.is_persistent distinguishes heap theories from WIP ones), but
  every Semantic_Store.* procedure is unknown, so check_theorem_name_in_file
  raises Remote_Calling_Failure -- exactly the degraded state the refusal
  guard exists for.  The backfill_positions write RPC could not silently
  succeed either: if the guard failed to fire, the attempted write would
  surface as a raw Remote_Calling_Failure instead of the end-of-run ERROR,
  which is what the first check below discriminates.  No store is ever
  touched.  Do NOT merge this into Entity_Position_Test.thy: its earlier
  sections load the host package into the same process, and the RPC would
  then succeed.

  The refusal target cannot simply be a real heap theory: backfill_cone
  sweeps the whole ancestor cone (collect_cone), and every HOL-descended cone
  contains HOL.Try0 -- a theory with no theorem names at all, for which the
  degraded flag stays false ("no tie-break to get wrong"), so it proceeds to
  the write RPC by design; with the host package absent that legitimate
  attempt raises a raw Remote_Calling_Failure at the cone's leaf and cancels
  the DAG group before any refusal can fire.  The target is therefore a
  manufactured SINGLE-THEORY cone: a draft theory whose only parent is Pure
  (Pure is excluded from cones), carrying two stored probe theorems (so
  file_match_names is non-empty and the degraded tie-break fires), and named
  "HOL.Fun" with master directory ~~/src/HOL -- Theory_Hash's persistence
  fork is by design decided from Resources.loaded_theory on the LONG NAME
  plus the on-disk .thy file (theory_hash.ML documents this, "situation 2"),
  so the draft hashes as a persistent theory and reaches the refusal branch
  instead of the skip branch.

  The control is a fresh WIP draft over Pure: same singleton cone, but a
  non-persistent name, so the report comes back skipped = 1, refused = 0
  with no exception -- proving the skip path and the refusal path are
  distinguished.  A whole-cone run against the real HOL.Fun is logged as an
  observation (no assertion): it documents the Try0 leaf crash above.
\<close>

ML \<open>
local
  (* the run's own temp dir -- the writeln log is the primary record; this
     file is for drivers that cannot capture writeln output *)
  val evidence_path =
    Path.append (Path.explode (getenv_strict "ISABELLE_TMP"))
      (Path.basic "t9_refusal_evidence.txt")

  val lines = Unsynchronized.ref ([] : string list)
  fun log s = (lines := s :: ! lines; writeln s)

  datatype outcome =
      Returned of Semantic_Store.backfill_report
    | Stopped of string        (* the ERROR backfill_cone raises at the end *)
    | Rpc_Escaped of string    (* raw RPC failure: the refusal guard did NOT fire *)
    | Other_Exn of string

  fun run thys =
    \<^try>\<open>Returned (Semantic_Store.backfill_cone thys)
      catch ERROR msg => Stopped msg
          | Remote_Procedure_Calling.Remote_Calling_Failure {func_name, message} =>
              Rpc_Escaped (String.concat
                [(case func_name of SOME f => f ^ ": " | NONE => ""), message])
          | exn => Other_Exn (Runtime.exn_message exn)\<close>

  fun describe outc =
    (case outc of
      Returned r =>
        "returned normally: " ^ Semantic_Store.string_of_backfill_report r
    | Stopped msg => "raised ERROR: " ^ msg
    | Rpc_Escaped msg => "raw Remote_Calling_Failure escaped: " ^ msg
    | Other_Exn msg => "unexpected exception: " ^ msg)

  val stop_prefix = "backfill_positions stopped: "

  (* First integer right after the first occurrence of `marker`. *)
  fun int_after (marker : string) (s : string) : int option =
    let val (_, rest) = Substring.position marker (Substring.full s) in
      if Substring.isEmpty rest then NONE
      else
        Int.fromString
          (Substring.string
            (Substring.takel Char.isDigit (Substring.triml (size marker) rest)))
    end

  (* ---- the refusal target: a persistent single-theory cone ---- *)
  val fixture0 =
    Resources.begin_theory (Path.explode "~~/src/HOL")
      (Thy_Header.make ("HOL.Fun", Position.none) [] [])
      [\<^theory>\<open>Pure\<close>]
  (* Global facts must be closed ("Illegal fixed variable" otherwise), hence
     the forall_intr: \<And>x. x \<equiv> x and \<And>A. PROP A \<Longrightarrow> PROP A. *)
  val cx = Thm.global_cterm_of fixture0 (Free ("x", propT))
  val cA = Thm.global_cterm_of fixture0 (Free ("A", propT))
  val probe_a = Thm.forall_intr cx (Thm.reflexive cx)
  val probe_b = Thm.forall_intr cA (Thm.trivial cA)
  val fixture =
    fixture0
    |> Global_Theory.store_thm (Binding.name "refusal_probe_a", probe_a) |> snd
    |> Global_Theory.store_thm (Binding.name "refusal_probe_b", probe_b) |> snd

  val fixture_persistent =
    \<^try>\<open>Theory_Hash.is_persistent (Theory_Hash.hash_of fixture)
      catch exn => (log ("fixture hash failed: " ^ Runtime.exn_message exn); false)\<close>
  val _ = log ("fixture \"HOL.Fun\" (draft over Pure, 2 probe thms) is_persistent = " ^
               Bool.toString fixture_persistent)

  val refusal_outcome = run [fixture]
  val _ = log ("[refusal] backfill_cone [fixture] " ^ describe refusal_outcome)
  val refusal_msg =
    (case refusal_outcome of Stopped msg => SOME msg | _ => NONE)

  (* ---- control: the skip path for a non-persistent (WIP) theory ---- *)
  val wip_thy =
    Theory.begin_theory ("Entity_Position_Refusal_Control", Position.none)
      [\<^theory>\<open>Pure\<close>]
  val control_outcome = run [wip_thy]
  val _ = log ("[control] backfill_cone [WIP draft over Pure] " ^ describe control_outcome)
  val control_report =
    (case control_outcome of Returned r => SOME r | _ => NONE)

  (* ---- observation only: the real HOL.Fun's whole cone (documents the
     Try0 leaf write-attempt crash; no assertion) ---- *)
  val real_fun = Theory.check {long = false} \<^context> ("Fun", Position.none)
  val _ = log ("[observation] backfill_cone [real HOL.Fun, whole cone] " ^
               describe (run [real_fun]))

  val checks =
    [("fixture hashes as persistent (Theory_Hash.is_persistent)",
      fixture_persistent),
     ("refusal: backfill_cone raised the end-of-run ERROR (no normal return, and " ^
      "no raw Remote_Calling_Failure -- so the write RPC was never attempted)",
      is_some refusal_msg),
     ("refusal: the message starts with \"" ^ stop_prefix ^ "\"",
      (case refusal_msg of SOME m => String.isPrefix stop_prefix m | NONE => false)),
     ("refusal: exactly 1 theory refused (head count)",
      (case refusal_msg of SOME m => int_after stop_prefix m = SOME 1 | NONE => false)),
     ("refusal: report says \", 1 refused,\"",
      (case refusal_msg of
        SOME m => String.isSubstring ", 1 refused," m | NONE => false)),
     ("refusal: nothing was written (report says \"-- 0 theories written\")",
      (case refusal_msg of
        SOME m => String.isSubstring "-- 0 theories written" m | NONE => false)),
     ("refusal: nothing was skipped (report says \", 0 skipped,\")",
      (case refusal_msg of
        SOME m => String.isSubstring ", 0 skipped," m | NONE => false)),
     ("refusal: at least one entry was enumerated before refusing",
      (case refusal_msg of
        SOME m => (case int_after "enumerated " m of SOME n => n >= 1 | NONE => false)
      | NONE => false)),
     ("control: backfill_cone returned normally (no exception)",
      is_some control_report),
     ("control: skipped = 1",
      (case control_report of SOME r => #skipped r = 1 | NONE => false)),
     ("control: refused = 0",
      (case control_report of SOME r => #refused r = 0 | NONE => false)),
     ("control: theories written = 0 and enumerated = 0",
      (case control_report of
        SOME r => #theories r = 0 andalso #enumerated r = 0 | NONE => false))]

  val _ = List.app (fn (d, ok) => log ((if ok then "OK   " else "FAIL ") ^ d)) checks
  val all_ok = forall snd checks
  val verdict = if all_ok then "PASS" else "FAIL"
  val _ =
    File.write evidence_path
      (String.concatWith "\n"
        (("T9 refusal half (Entity_Position_Refusal_Test) -- RESULT: " ^ verdict)
         :: rev (! lines)) ^ "\n")
in
  val _ = @{assert} all_ok
end
\<close>

end
