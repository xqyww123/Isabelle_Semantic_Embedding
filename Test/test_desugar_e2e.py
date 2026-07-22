"""
End-to-end test for the desugar_and_explain RPC callback round-trip.

Exercises: ML -> Python RPC -> ML callback -> Python -> ML

Prerequisites:
  - REPL server on 127.0.0.1:6666 with Semantic_Embedding loaded
  - RPC server on 127.0.0.1:27182 (start it yourself AND export RPC_Host=127.0.0.1:27182
    to the Isabelle side -- since Isabelle_RPC 0.4.0 there is no shared default address;
    without the export, Isabelle silently talks to its own ephemeral host instead)

Usage:
  python Test/test_desugar_e2e.py
"""

import asyncio
import sys
sys.path.insert(0, "/home/qiyuan/Current/MLML/contrib/Isa-REPL")
sys.path.insert(0, "/home/qiyuan/Current/MLML/contrib/Semantic_Embedding")

from IsaREPL import Client

LOG = "/tmp/test_desugar_e2e.log"

ML_TEST = r"""
theory Test imports Semantic_Embedding.Semantic_Embedding begin

definition my_test_fun :: "nat \<Rightarrow> nat" where
  "my_test_fun x = x + 1"

ML \<open>
let
  open MessagePackBinIO.Pack MessagePackBinIO.Unpack
  open Remote_Procedure_Calling

  val log = Unsynchronized.ref ([] : string list)
  fun L s = log := s :: !log
  fun flush () = File.write (Path.explode "/tmp/test_desugar_e2e.log")
    (String.concat (rev (!log)))

  (* 1. Load the Python test relay module *)
  val _ = L "Loading Python test module...\n"
  val _ = load ["Isabelle_Semantic_Embedding.test_desugar_callback"]
  val _ = L "  OK\n"

  (* 2. Create the dynamic desugar callback *)
  val context = Context.Proof \<^context>
  val desugar_cb = Explain_Term.make_desugar_callback context
  val _ = L "Created desugar callback\n"

  (* 3. Define an RPC command targeting the Python relay *)
  val test_cmd : ((string * int) option * string,
                  string * (string * Word8Vector.vector) list) command = {
    name = "test.desugar_roundtrip",
    arg_schema = packPair (
      packOption (packPair (packString, packInt)),
      packString),
    ret_schema = unpackPair (
      unpackString,
      unpackList (unpackPair (unpackString, unpackBytes))),
    callback = [desugar_cb],
    timeout = SOME (Time.fromSeconds 30)
  }

  (* === Test 1: basic list application === *)
  val term1 = "map f [1::nat, 2, 3]"
  val _ = L ("\n=== Test 1: " ^ term1 ^ " ===\n")
  val (compact1, consts1) = call_command test_cmd (NONE, term1)
  val _ = L ("  compact: " ^ compact1 ^ "\n")
  val _ = L ("  constants (" ^ string_of_int (length consts1) ^ "):\n")
  val _ = List.app (fn (name, uk) =>
    L ("    " ^ name ^ " (uk_len=" ^ string_of_int (Word8Vector.length uk) ^ ")\n"))
    consts1

  val _ = if compact1 = ""
          then error "Test 1 FAILED: compact string is empty"
          else L "  PASS: compact string non-empty\n"
  val _ = List.app (fn (name, uk) =>
    if Word8Vector.length uk = 0
    then error ("Test 1 FAILED: uk_bytes empty for " ^ name)
    else ()) consts1
  val _ = L "  PASS: all uk_bytes non-empty\n"

  (* === Test 2: let binding === *)
  val term2 = "let x = (1::nat) + 2 in x * x"
  val _ = L ("\n=== Test 2: " ^ term2 ^ " ===\n")
  val (compact2, consts2) = call_command test_cmd (NONE, term2)
  val _ = L ("  compact: " ^ compact2 ^ "\n")
  val _ = L ("  constants (" ^ string_of_int (length consts2) ^ "):\n")
  val _ = List.app (fn (name, uk) =>
    L ("    " ^ name ^ " (uk_len=" ^ string_of_int (Word8Vector.length uk) ^ ")\n"))
    consts2

  val _ = if String.isSubstring "let" compact2
          then L "  PASS: 'let' found in compact output\n"
          else error ("Test 2 FAILED: 'let' not found in: " ^ compact2)

  (* === Test 3: lambda with filter === *)
  val term3 = "filter (\<lambda>x. x > (0::nat)) [1, 2, 3]"
  val _ = L ("\n=== Test 3: " ^ term3 ^ " ===\n")
  val (compact3, consts3) = call_command test_cmd (NONE, term3)
  val _ = L ("  compact: " ^ compact3 ^ "\n")
  val _ = L ("  constants (" ^ string_of_int (length consts3) ^ "):\n")
  val _ = List.app (fn (name, uk) =>
    L ("    " ^ name ^ " (uk_len=" ^ string_of_int (Word8Vector.length uk) ^ ")\n"))
    consts3

  val _ = if compact3 = ""
          then error "Test 3 FAILED: compact string is empty"
          else L "  PASS: compact string non-empty\n"

  (* === Test 3b: verify that Main constants ARE filtered === *)
  val _ = if length consts3 = 0
          then L "  PASS: all Main constants correctly filtered\n"
          else error ("Test 3b FAILED: expected 0 constants from Main, got "
                      ^ string_of_int (length consts3))

  (* === Test 3c: user-defined constant survives filter === *)
  val term3c = "map my_test_fun [1::nat, 2, 3]"
  val _ = L ("\n=== Test 3c: " ^ term3c ^ " ===\n")
  val (compact3c, consts3c) = call_command test_cmd (NONE, term3c)
  val _ = L ("  compact: " ^ compact3c ^ "\n")
  val _ = L ("  constants (" ^ string_of_int (length consts3c) ^ "):\n")
  val _ = List.app (fn (name, uk) =>
    L ("    " ^ name ^ " (uk_len=" ^ string_of_int (Word8Vector.length uk) ^ ")\n"))
    consts3c

  val _ = if exists (fn (name, _) => String.isSuffix "my_test_fun" name) consts3c
          then L "  PASS: user-defined my_test_fun found in constants\n"
          else error "Test 3c FAILED: my_test_fun not found in extracted constants"
  val _ = List.app (fn (name, uk) =>
    if Word8Vector.length uk = 0
    then error ("Test 3c FAILED: uk_bytes empty for " ^ name)
    else ()) consts3c
  val _ = L "  PASS: all uk_bytes non-empty\n"

  (* === Test 4: error handling — malformed term === *)
  val _ = L "\n=== Test 4: error handling ===\n"
  val passed4 = (call_command test_cmd (NONE, "f x +"); false)
    handle Remote_Calling_Failure _ => true
  val _ = if passed4
          then L "  PASS: malformed term raised exception\n"
          else error "Test 4 FAILED: malformed term did not raise"

  val _ = L "\n=== ALL TESTS PASSED ===\n"
  val _ = flush ()
in () end
\<close>

end
"""


async def main():
    async with Client("127.0.0.1:6666", "Draft", timeout=120) as c:
        print("Connected to REPL")
        results = await c.eval(ML_TEST, timeout=120_000)

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
