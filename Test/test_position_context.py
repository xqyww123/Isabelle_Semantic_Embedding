"""Test position-based context resolution via Isabelle REPL."""

import asyncio
import sys
sys.path.insert(0, "/home/qiyuan/Current/MLML/contrib/Isa-REPL")
sys.path.insert(0, "/home/qiyuan/Current/MLML/contrib/Semantic_Embedding")

from IsaREPL import Client

LOG = "/tmp/pide_state_test.log"


async def main():
    async with Client("127.0.0.1:6666", "Draft", timeout=120) as c:
        print("Connected to REPL")

        results = await c.eval(r"""
theory Test imports Semantic_Embedding.Semantic_Embedding begin

ML \<open>
let
  val log = Unsynchronized.ref ([] : string list)
  fun L s = log := s :: !log
  fun flush () = File.write (Path.explode "/tmp/pide_state_test.log")
    (String.concat (rev (!log)))

  val _ = L "=== Test 1: position_context_unpacker type-check ===\n"
  val _ = PIDE_State.position_context_unpacker
    : Context.generic -> Context.generic MessagePackBinIO.Unpack.unpacker
  val _ = L "  PASS\n"

  val _ = L "\n=== Test 2: context_at_position for heap Lattices.thy ===\n"
  val thy = Thy_Info.get_theory "HOL.Lattices"
  val dir = Resources.master_directory thy
  val file = Path.implode (Path.append dir (Path.basic "Lattices.thy"))
  val timer = Timer.startRealTimer ()
  val ctx = PIDE_State.context_at_position {re_eval_cache = true} file 3000
  val elapsed = Timer.checkRealTimer timer
  val _ = case ctx of
      NONE => L "  RESULT: NONE\n"
    | SOME (Context.Theory _) => L "  RESULT: Theory\n"
    | SOME (Context.Proof ctxt) =>
        L ("  RESULT: Proof, theory=" ^
          Context.theory_long_name (Proof_Context.theory_of ctxt) ^
          " (" ^ Time.toString elapsed ^ "s)\n")

  val _ = L "\n=== Test 3: re_eval_cache=false for heap ===\n"
  val ctx3 = PIDE_State.context_at_position {re_eval_cache = false} file 3000
  val _ = L (case ctx3 of
      NONE => "  RESULT: NONE (expected)\n"
    | SOME _ => "  RESULT: SOME (unexpected!)\n")

  val _ = L "\n=== Test 4: Cached lookup (should be fast) ===\n"
  val timer2 = Timer.startRealTimer ()
  val ctx4 = PIDE_State.context_at_position {re_eval_cache = true} file 5000
  val elapsed2 = Timer.checkRealTimer timer2
  val _ = L ("  " ^ Time.toString elapsed2 ^ "s -> " ^
    (case ctx4 of NONE => "NONE" | SOME _ => "SOME") ^ "\n")

  val _ = L "\n=== Test 5: Locale context in Groups.thy ===\n"
  val thy5 = Thy_Info.get_theory "HOL.Groups"
  val dir5 = Resources.master_directory thy5
  val file5 = Path.implode (Path.append dir5 (Path.basic "Groups.thy"))
  fun probe off =
    case PIDE_State.context_at_position {re_eval_cache = true} file5 off of
      NONE => "NONE"
    | SOME (Context.Theory _) => "Theory"
    | SOME (Context.Proof ctxt) =>
        let val space = Proof_Context.const_space ctxt
            val fq = Name_Space.intern space "local.mult"
        in if String.isPrefix "??" fq then "Proof(no local.mult)"
           else "Proof(mult=" ^ fq ^ ")"
        end
  val _ = List.app (fn off =>
    L ("  offset=" ^ string_of_int off ^ " -> " ^ probe off ^ "\n"))
    [500, 2000, 4000, 8000, 12000, 16000]

  val _ = flush ()
in () end
\<close>

end
        """, timeout=120_000)

        if results:
            for r in results:
                if r.errors:
                    print(f"ERROR in {r.command[:50]!r}: {r.errors}")

        with open(LOG) as f:
            print(f.read())


if __name__ == "__main__":
    asyncio.run(main())
