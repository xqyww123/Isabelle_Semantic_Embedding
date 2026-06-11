"""
End-to-end test for the resolve_notation RPC callback round-trip, plus a
regression for entity enumeration under a (file, offset) context.

Exercises: ML -> Python RPC -> ML callback -> Python -> ML

Prerequisites:
  - REPL server on 127.0.0.1:6666 with Semantic_Embedding loaded
  - RPC server on 127.0.0.1:27182

Usage:
  python Test/test_resolve_notation_e2e.py
"""

import asyncio
import sys
sys.path.insert(0, "/home/qiyuan/Current/MLML/contrib/Isa-REPL")
sys.path.insert(0, "/home/qiyuan/Current/MLML/contrib/Semantic_Embedding")

from IsaREPL import Client

LOG = "/tmp/test_resolve_notation_e2e.log"

ML_TEST = r"""
theory Test imports Semantic_Embedding.Semantic_Embedding begin

abbreviation my_oplus :: "nat \<Rightarrow> nat \<Rightarrow> nat" (infixl "\<oplus>" 65)
  where "a \<oplus> b \<equiv> a + b * 2"

ML \<open>
let
  open MessagePackBinIO.Pack MessagePackBinIO.Unpack
  open Remote_Procedure_Calling

  val log = Unsynchronized.ref ([] : string list)
  fun L s = log := s :: !log
  fun flush () = File.write (Path.explode "/tmp/test_resolve_notation_e2e.log")
    (String.concat (rev (!log)))

  (* 1. Load the Python test relay module *)
  val _ = L "Loading Python test module...\n"
  val _ = load ["Isabelle_Semantic_Embedding.test_resolve_notation_callback"]
  val _ = L "  OK\n"

  (* 2. Create the callbacks under test *)
  val context = Context.Proof \<^context>
  val resolve_cb = Explain_Term.make_resolve_notation_callback context
  val pu = PIDE_State.position_context_unpacker context
  val constants_cb = Context_Callbacks.make_constants_callback NONE pu
  val _ = L "Created callbacks\n"

  (* 3. RPC commands targeting the Python relays *)
  val resolve_cmd : ((string * int) option * string,
                     (string * Word8Vector.vector * string) option) command = {
    name = "test.resolve_notation_roundtrip",
    arg_schema = packPair (
      packOption (packPair (packString, packInt)),
      packString),
    ret_schema = unpackOption (
      unpackTuple3 (unpackString, unpackBytes, unpackString)),
    callback = [resolve_cb],
    timeout = SOME (Time.fromSeconds 30)
  }
  val entities_cmd : ((string * int) option, int) command = {
    name = "test.entities_with_ctxt",
    arg_schema = packOption (packPair (packString, packInt)),
    ret_schema = unpackInt,
    callback = [constants_cb],
    timeout = SOME (Time.fromSeconds 60)
  }

  (* === Test 1: base-library notation resolves (no nontrivial filtering) === *)
  val _ = L "\n=== Test 1: (\<le>) ===\n"
  val r1 = call_command resolve_cmd (NONE, "(\<le>)")
  val _ = case r1 of
      SOME (name, uk, compact) =>
        (L ("  name=" ^ name ^ " uk_len=" ^ string_of_int (Word8Vector.length uk)
            ^ " compact=" ^ compact ^ "\n");
         if name <> "Orderings.ord_class.less_eq"
         then error ("Test 1 FAILED: unexpected name " ^ name)
         else if Word8Vector.length uk = 0
         then error "Test 1 FAILED: empty uk"
         else L "  PASS\n")
    | NONE => error "Test 1 FAILED: got NONE"

  (* === Test 2: abbreviation notation resolves to the abbreviation itself === *)
  val _ = L "\n=== Test 2: infix \<oplus> (abbreviation) ===\n"
  val r2 = call_command resolve_cmd (NONE, "syntax_probe_x \<oplus> syntax_probe_y")
  val _ = case r2 of
      SOME (name, _, compact) =>
        (L ("  name=" ^ name ^ " compact=" ^ compact ^ "\n");
         if not (String.isSuffix ".my_oplus" name)
         then error ("Test 2 FAILED: expected ...my_oplus, got " ^ name)
         else if compact <> "my_oplus syntax_probe_x syntax_probe_y"
         then error ("Test 2 FAILED: unexpected compact " ^ compact)
         else L "  PASS\n")
    | NONE => error "Test 2 FAILED: got NONE"

  (* === Test 3: non-constant head round-trips as NONE === *)
  val _ = L "\n=== Test 3: (syntax_probe_x) -> NONE ===\n"
  val _ = case call_command resolve_cmd (NONE, "(syntax_probe_x)") of
      NONE => L "  PASS\n"
    | SOME (name, _, _) => error ("Test 3 FAILED: expected NONE, got " ^ name)

  (* === Test 4: malformed probe raises; connection stays usable === *)
  val _ = L "\n=== Test 4: error handling ===\n"
  val passed4 = (call_command resolve_cmd (NONE, "f x +"); false)
    handle Remote_Calling_Failure _ => true
  val _ = if passed4 then L "  PASS: malformed probe raised\n"
          else error "Test 4 FAILED: malformed probe did not raise"
  val _ = case call_command resolve_cmd (NONE, "(\<le>)") of
      SOME _ => L "  PASS: connection still usable after error\n"
    | NONE => error "Test 4 FAILED: connection unusable after error"

  (* === Test 5: entities_of with a (file, offset) ctxt (F1 regression) ===
     An unresolvable position must fall back to the default context and
     enumerate normally — with the old nil-only unpacker this raised. *)
  val _ = L "\n=== Test 5: entities_of under tuple ctxt ===\n"
  val cnt = call_command entities_cmd (SOME ("/nonexistent_probe_file.thy", 1))
  val _ = L ("  count(tuple ctxt) = " ^ string_of_int cnt ^ "\n")
  val _ = if cnt > 0 then L "  PASS\n"
          else error "Test 5 FAILED: empty enumeration under tuple ctxt"
  val cnt' = call_command entities_cmd NONE
  val _ = L ("  count(nil ctxt) = " ^ string_of_int cnt' ^ "\n")
  val _ = if cnt' > 0 then L "  PASS\n"
          else error "Test 5 FAILED: empty enumeration under nil ctxt"

  val _ = L "\n=== ALL TESTS PASSED ===\n"
  val _ = flush ()
in () end
\<close>

end
"""


async def main():
    async with Client("127.0.0.1:6666", "Draft", timeout=120) as c:
        print("Connected to REPL")
        results = await c.eval(ML_TEST, timeout=300_000)

        if results is None:
            print("ERROR: eval returned None")
            sys.exit(1)

        has_error = False
        for r in results:
            if r.errors:
                print(f"ERROR in {r.command[:60]!r}: {r.errors}")
                has_error = True

        if has_error:
            sys.exit(1)

        try:
            with open(LOG) as f:
                output = f.read()
            print(output)
            if "ALL TESTS PASSED" in output:
                print("SUCCESS")
            else:
                print("FAILED: 'ALL TESTS PASSED' not found in output")
                sys.exit(1)
        except FileNotFoundError:
            print(f"ERROR: log file {LOG} not found (ML code may have failed before flush)")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
