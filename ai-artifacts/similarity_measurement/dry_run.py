"""Dry run of the semantic-interpretation work set for the scratch theories.

Loads a scratch theory into the running Isa-REPL and asks
``Semantic_Store.dry_run`` which theories and how many entities a real
interpretation run would send to the LLM.  No LLM is invoked, and per
CHECK_OUTDATE_PLAN.md's write-back discipline a dry run marks nothing.
"""
import asyncio
import sys

sys.path.insert(0, "/home/qiyuan/Current/MLML/contrib/Isa-REPL")

from IsaREPL import Client

REPL_ADDR = "127.0.0.1:6701"
THY_DIR = "/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/ai-artifacts/similarity_measurement"
OUT = "/var/tmp/qiyuan/sim_measure_logs/dryrun.txt"

ML_TEMPLATE = '''
let
  val thy = Thy_Info.get_theory "{thy}"
  val _ = Theory_Hash.store_theory_hash thy
  val _ = Remote_Procedure_Calling.load ["Isabelle_Semantic_Embedding"]
  val (work, n) = Semantic_Store.dry_run false [Context.Theory thy]
in
  File.write (Path.explode "{out}")
    ("WORK_NAMES:\\n" ^ cat_lines work ^ "\\nN=" ^ string_of_int n ^ "\\n")
end
'''


async def main(target: str) -> None:
    async with Client(REPL_ADDR, "HOL", timeout=None) as c:
        await c.set_register_thy(False)
        names = await c.load_theory(
            [f"{THY_DIR}/{target}", "Semantic_Embedding.Semantic_Collection_App"])
        print("loaded:", names, flush=True)
        src = ML_TEMPLATE.format(thy=names[0], out=OUT)
        await c.run_ML("Semantic_Embedding.Semantic_Collection_App", src)
        with open(OUT) as f:
            print(f.read())


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "Sim_Measure_A1"))
