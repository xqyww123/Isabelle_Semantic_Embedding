(* The interpretation lock, ML side (SEMANTIC_CHANGE_GATE_PLAN.md §8.2, D8, D17).

   One live interpretation run per semantic database: a run takes the lock
   through a connection of its own and releases it by closing that connection.
   This theory takes the lock briefly and writes NOTHING to the database: every
   locked body here is trivial, and the one live entry point it calls,
   `Semantic_Store.interpret`, is called only under a lock this theory itself
   holds -- checked before the call -- so it short-circuits with §12 #2.  The
   `.interpretation.lock` file, deleted on release, is the only artefact, under
   whatever SEMANTIC_DB_DIR the attached Python host has.  Test-exclusivity
   discipline, as for Test_All: do not build this session while a live
   interpretation run is in progress (the first assertion would fail
   spuriously), and while this theory holds the lock a concurrent automatic
   update is skipped with §12 #1.  Pointing SEMANTIC_DB_DIR at a scratch
   directory (how this theory was developed, through the REPL server) removes
   even that coupling. *)
theory Interpretation_Lock_Test
  imports Semantic_Embedding.Semantic_Embedding
begin

ML \<open>
  val _ = Remote_Procedure_Calling.load ["Isabelle_Semantic_Embedding"]
  (* The release is asynchronous to the ML caller: closing the lock connection
     returns at once, and the host runs the release when it sees the socket's
     EOF.  So every acquire that is EXPECTED to succeed goes through this
     bounded retry; the acquires expected to be refused stay single tries --
     they are the behaviour under test. *)
  fun lock_within secs body =
    let
      val deadline = Time.now () + Time.fromSeconds secs
      fun go () =
        (case Semantic_Store.with_interpretation_lock body of
          SOME r => SOME r
        | NONE =>
            if Time.now () < deadline
            then (OS.Process.sleep (Time.fromMilliseconds 50); go ())
            else NONE)
    in go () end
  fun free_within secs = is_some (lock_within secs (fn () => ()))
\<close>

(* A free lock is taken and given back: the primitive, twice in a row. *)
ML \<open>
  val _ = \<^assert> (lock_within 5 (fn () => 1) = SOME 1)
  val _ = \<^assert> (lock_within 5 (fn () => 2) = SOME 2)
\<close>

(* Held: a nested attempt is refused at once (NONE, no waiting) -- checked
   BEFORE the live entry point is called, so a broken lock aborts this theory
   instead of starting an interpretation run -- and then the exported
   `interpret` raises text §12 #2 (D17).  Once the holder's body returns the
   lock is free again. *)
ML \<open>
  val r =
    lock_within 5 (fn () =>
      (if Semantic_Store.with_interpretation_lock (fn () => ()) = NONE then ()
       else error "interpretation lock broken: a nested acquire succeeded -- \
                  \refusing to start a live interpretation run";
       (Semantic_Store.interpret false (Context.Proof \<^context>); NONE)
         handle ERROR msg => SOME msg))
  val _ = \<^assert> (r = SOME (SOME Semantic_Store.lock_busy_error))
  val _ = \<^assert> (free_within 5)
\<close>

(* An interrupted holder releases through its closed connection: the next
   acquire succeeds.  The body is interrupted from outside; the acquire round
   trip itself cannot be hit deterministically from here.  One state variable
   carries the holder's progress, and every wait on it is bounded, so a holder
   that never reaches the lock body -- refused, failed, or stuck in the acquire
   -- fails with a message naming what was seen instead of wedging this theory. *)
ML \<open>
  datatype holder_state = Not_started | Holding | Done of string
  val state = Synchronized.var "lock_test_holder" Not_started
  (* The deadline is computed here, once: timed_access re-evaluates its time
     limit on every wakeup, so a limit computed inside would renew the bound. *)
  fun await secs pred =
    let val deadline = Time.now () + Time.fromSeconds secs in
      Synchronized.timed_access state (K (SOME deadline))
        (fn s => if pred s then SOME (s, s) else NONE)
    end
  fun str_of (SOME Holding) = "holding"
    | str_of (SOME (Done s)) = "done: " ^ s
    | str_of (SOME Not_started) = "not started"
    | str_of NONE = "nothing within the bound"
  (* `interrupts`: Isabelle_Thread.params forks with interrupts OFF, and an
     uninterruptible holder would just sleep the 30 s out -- vacuous. *)
  val holder =
    Isabelle_Thread.fork (Isabelle_Thread.interrupts (Isabelle_Thread.params "lock_holder"))
      (fn () =>
        let
          val res =
            Exn.capture (fn () =>
              lock_within 5 (fn () =>
                (Synchronized.change state (K Holding);
                 OS.Process.sleep (Time.fromSeconds 30)))) ()
        in
          Synchronized.change state (K (Done
            (case res of
              Exn.Res (SOME ()) => "finished"
            | Exn.Res NONE => "refused"
            | Exn.Exn exn => if Exn.is_interrupt exn then "interrupted" else "failed")))
        end)
  val _ =
    (case await 20 (fn Not_started => false | _ => true) of
      SOME Holding => ()
    | other => error ("lock holder never reached the lock body: " ^ str_of other))
  val _ = \<^assert> (Semantic_Store.with_interpretation_lock (fn () => ()) = NONE)
  val _ = Isabelle_Thread.interrupt_thread holder
  val _ =
    (case await 10 (fn Done _ => true | _ => false) of
      SOME (Done "interrupted") => ()
    | other => error ("lock holder outcome after the interrupt: " ^ str_of other))
  val _ = Isabelle_Thread.join holder
  val _ = \<^assert> (free_within 5)
\<close>

end
