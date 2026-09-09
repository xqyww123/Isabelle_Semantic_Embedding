"""Dump each scratch theory's entities with the FORMAL comparator the pipeline
already computes: `Semantic_Digest`, the alpha-canonical 16-byte digest of an
entity's own semantic content (Tools/semantic_digest.ML), plus its universal key
and its printed statement.

This is candidate rule 5's non-embedding comparator: it costs no LLM call and no
embedding call, and it is exact.  Writes one TSV per theory under the log
directory; `stats2.py` reads them back.
"""
import asyncio
import os
import sys

sys.path.insert(0, "/home/qiyuan/Current/MLML/contrib/Isa-REPL")

from IsaREPL import Client

REPL_ADDR = "127.0.0.1:6701"
THY_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = "/var/tmp/qiyuan/sim_measure_logs/digests"

THEORIES = ["Sim_Measure_A1", "Sim_Measure_A2", "Sim_Measure_A3",
            "Sim_Measure_A4", "Sim_Measure_A5", "Sim_Measure_B",
            "Sim_Measure_B1b", "Sim_Measure_B1c", "Sim_Measure_B2",
            "Sim_Measure_B2b", "Sim_Measure_B3", "Sim_Measure_B4"]

ML = r'''
let
  val thy = Thy_Info.get_theory "{thy}"
  val {{entries, ...}} = Semantic_Store.enumerate_entries (Context.Theory thy)
  fun hex bs =
    Word8Vector.foldr (fn (w, acc) =>
      (if Word8.< (w, 0wx10) then "0" else "") ^ Word8.toString w ^ acc) "" bs
  fun flat s = space_implode " " (split_lines s)
  fun line (_, name, prop, _, uk, _, _, _, _, dg, _) =
    name ^ "\t" ^ (case dg of NONE => "-" | SOME d => hex d) ^ "\t" ^ hex uk
         ^ "\t" ^ flat prop
in
  File.write (Path.explode "{out}") (cat_lines (map line entries) ^ "\n")
end
'''


async def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    async with Client(REPL_ADDR, "HOL", timeout=None) as c:
        await c.set_register_thy(False)
        await c.load_theory([f"{THY_DIR}/{t}" for t in THEORIES]
                            + ["Semantic_Embedding.Semantic_Collection_App"])
        for t in THEORIES:
            out = os.path.join(OUT_DIR, f"{t}.tsv")
            await c.run_ML("Semantic_Embedding.Semantic_Collection_App",
                           ML.format(thy=t, out=out))
            with open(out) as f:
                n = sum(1 for _ in f)
            print(f"{t}: {n} entries -> {out}", flush=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
