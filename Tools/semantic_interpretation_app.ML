(*
  Isa-REPL Apps over the semantic store.

  Interpret-only: embedding is done Python-side by semantics_manage.py (offline
  `embed`, or the `collect --embed-models` chain), never here.

  Semantic_Store.collect -- collect semantic interpretations.
    Client sends: theory_names (msgpack string list — the roots to interpret)
                  force (msgpack bool – when true, re-interpret already-finished theories)

  Semantic_Store.backfill_positions -- give already-collected records their entity
  positions (ENTITY_POSITION_PLAN.md §8.2).  No LLM is involved.
    Client sends: theory_names (msgpack string list — the roots to sweep)

  Both:
    Server streams: packString messages during the run (from tracing)
    Server sends:   packUnit when done successfully
    On error:       sends packString "ERROR: ..." then packUnit

  Concurrency width is the session's own -o threads=N, i.e. Multithreading.max_threads (),
  which is what Isabelle's future worker pool bounds itself by. There is no per-call override.
*)

local open MessagePackBinIO.Pack MessagePackBinIO.Unpack in

(* The framing both apps need, in one place: the send/done pair under a lock, the
   Private_Output channel hijack that streams progress over the socket, and the
   "ERROR: " wrapper.  `body` gets the input stream ref and builds its own reader --
   reading is polymorphic in the unpacker, which no single passed-in function could
   be. *)
fun register_streaming_app name body =
  REPL_Server.register_app name (fn (cin, cout, state) =>
    let
      (* Serialize output: under -o threads>1 several worker threads stream tracing
         concurrently through these channels; without the lock their msgpack frames
         would interleave and corrupt the socket stream. *)
      val send_lock = Synchronized.var (name ^ ".send") ()
      fun send msg =
        Synchronized.change send_lock (fn () =>
          (REPL_Server.output cout packString msg;
           BinIO.StreamIO.flushOut cout))
      fun done () =
        Synchronized.change send_lock (fn () =>
          (REPL_Server.output cout packUnit ();
           BinIO.StreamIO.flushOut cout))

      val old_writeln = !Private_Output.writeln_fn
      val old_state = !Private_Output.state_fn
      val old_information = !Private_Output.information_fn
      val old_tracing = !Private_Output.tracing_fn
      val old_warning = !Private_Output.warning_fn
      val old_legacy = !Private_Output.legacy_fn
      val old_error_message = !Private_Output.error_message_fn
      fun set_channels out_fn =
        (Private_Output.writeln_fn := out_fn;
         Private_Output.state_fn := out_fn;
         Private_Output.information_fn := out_fn;
         Private_Output.tracing_fn := out_fn;
         Private_Output.warning_fn := (fn msgs => List.app (fn m => send ("### " ^ m)) msgs);
         Private_Output.legacy_fn := (fn msgs => List.app (fn m => send ("legacy: " ^ m)) msgs);
         Private_Output.error_message_fn := (fn (_, msgs) => List.app (fn m => send ("*** " ^ m)) msgs))
      fun restore_channels () =
        (Private_Output.writeln_fn := old_writeln;
         Private_Output.state_fn := old_state;
         Private_Output.information_fn := old_information;
         Private_Output.tracing_fn := old_tracing;
         Private_Output.warning_fn := old_warning;
         Private_Output.legacy_fn := old_legacy;
         Private_Output.error_message_fn := old_error_message)
    in
      \<^try>\<open>
        let
          val _ = set_channels (fn msgs => List.app send msgs)
          val _ = \<^try>\<open>body cin catch exn => (restore_channels (); Exn.reraise exn)\<close>
          val _ = restore_channels ()
          val _ = done ()
        in state end
      catch exn =>
        (send ("ERROR: " ^ Runtime.exn_message exn);
         done ();
         state)\<close>
    end)

(* Resolve the root theory names: register their hashes (universal keys need them)
   and make the Python handlers available.

   Deliberately does NOT read the names itself.  Every app drains its whole protocol
   FIRST and only then does work that can fail, as the original collect app did: an
   exception raised here -- Thy_Info.get_theory on a bad name, or a wedged RPC host
   in `load` -- would otherwise leave the client's remaining msgpack values unread in
   the socket, and the next command on that connection would unpack them as itself. *)
fun resolve_roots thy_names =
  let
    val thys = map Thy_Info.get_theory thy_names
    val _ = List.app Theory_Hash.store_theory_hash thys
    val _ = Remote_Procedure_Calling.load ["Isabelle_Semantic_Embedding"]
  in thys end

val _ = register_streaming_app "Semantic_Store.collect" (fn cin =>
  let
    fun read unpacker =
      let val (ret, cin') = doUnpack unpacker (!cin)
      in cin := cin'; ret end
    val thy_names = read (unpackList unpackString)
    val force = read unpackBool
    val thys = resolve_roots thy_names
    (* Batch collection has no user context of its own, so the first root theory
       serves as the one whose `declare [[Semantic_Embedding.interpretation_driver]]`
       governs the run; with no roots there is nothing to interpret anyway.  In
       practice this path is driven by `semantics_manage collect --driver`, which
       outranks the declaration. *)
    val cfg_context = (case thys of thy :: _ => Context.Theory thy
                        | [] => Context.Theory (Thy_Info.get_theory "Pure"))
  in
    Semantic_Store.interpret_with_parallel cfg_context force (map Context.Theory thys)
  end)

val _ = register_streaming_app "Semantic_Store.backfill_positions" (fn cin =>
  let
    fun read unpacker =
      let val (ret, cin') = doUnpack unpacker (!cin)
      in cin := cin'; ret end
    val thy_names = read (unpackList unpackString)
    val thys = resolve_roots thy_names
    val total = Semantic_Store.backfill_cone thys
  in
    writeln ("[Semantic_Embedding] backfill_positions: " ^
             Semantic_Store.string_of_backfill_report total)
  end)

end
