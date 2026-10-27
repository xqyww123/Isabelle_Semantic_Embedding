"""
End-to-end test of the by-name resolver: `Context.entries_of_names`
(`Context_Callbacks.entry_of_name`) and the definitions show_defs reads
through it (`_definition_of_name`).

1. Differential: for each `(kind, name)` of a corpus, every resolver SOME
   agrees with `universal_key_and_name_of` on the uk and the name, and every
   success of `universal_key_and_name_of` is SOME, except a fixed variable
   asked as a constant. Each item also states its expected fields.
2. `_definition_of_name` through `interpret_file_callbacks`' actual list, for
   a constant, a theorem and a theorem collection.

This script hosts the RPC host itself on 127.0.0.1:27182. Prerequisite: a REPL
server on 127.0.0.1:6666 that loads Semantic_Embedding, started with
RPC_Host=127.0.0.1:27182.

Usage:
  python Test/test_entries_of_names_e2e.py
"""

import asyncio
import sys
import threading
import time
sys.path.insert(0, "/home/qiyuan/Current/MLML/contrib/Isa-REPL")
sys.path.insert(0, "/home/qiyuan/Current/MLML/contrib/Semantic_Embedding")

import Isabelle_RPC_Host
from Isabelle_RPC_Host import isabelle_remote_procedure
from Isabelle_RPC_Host.rpc import IsabelleError
from Isabelle_RPC_Host.universal_key import EntityKind as K, UndefinedEntity, universal_key_and_name_of
from IsaREPL import Client

RPC_ADDR = "127.0.0.1:27182"
THY = "Entries_Of_Names_Test"

# (kind, name, ctxt, expected): expected is None for NONE, else the fields
# to check: "name" (exact), "pos" (True: known, False: ("", 0, 0)), "local".
CORPUS = [
    (K.THEOREM, "rp_single", None, {"name": f"{THY}.rp_single", "pos": True, "local": False}),
    (K.THEOREM, "rp_single(5)", None, {"name": f"{THY}.rp_single", "pos": True}),
    (K.THEOREM, "rp_multi(2)", None, {"name": f"{THY}.rp_multi(2)", "pos": True}),
    (K.THEOREM, "rp_coll(1)", None, {"pos": False}),
    (K.THEOREM_COLLECTION, "rp_coll", None, {"name": f"{THY}.rp_coll", "pos": True}),
    (K.THEOREM, "rp_local", "local", {"name": "local.rp_local", "local": True}),
    (K.THEOREM, "HOL.refl", None, {"name": "HOL.refl", "pos": True, "local": False}),
    (K.INTRODUCTION_RULE, "conjI", None, {"name": "HOL.conjI", "pos": True}),
    (K.INDUCTION_RULE, "nat.induct", None, {"pos": True}),
    (K.CONSTANT, "rp_def", None, {"name": f"{THY}.rp_def", "pos": True, "local": False}),
    (K.CONSTANT, "HOL.All", None, {"name": "HOL.All", "pos": True}),
    (K.TYPE, "nat", None, {"name": "Nat.nat", "pos": True}),
    (K.CLASS, "order", None, {"name": "Orderings.order", "pos": True}),
    (K.LOCALE, "semilattice", None, {"name": "Lattices.semilattice", "pos": True}),
    (K.METHOD, "simp", None, {"pos": True}),
    (K.THEOREM, "rp_multi", None, None),
    (K.THEOREM, "rp_empty", "empty", None),
    (K.THEOREM, "rp_multi(7)", None, None),
    (K.CONSTANT, "rp_fixed", "fixed", None),
    (K.TYPE, "no_such_type", None, None),
    (K.CLASS, "no_such_class", None, None),
    (K.LOCALE, "no_such_locale", None, None),
    (K.METHOD, "no_such_method", None, None),
    (K.THEOREM, "no_such_fact", None, None),
]
FIXED = {(K.CONSTANT, "rp_fixed", "fixed")}   # resolves by universal_key_of, NONE here

# (kind, name, a substring of the defining command's source)
DEFINITIONS = [
    (K.CONSTANT, "Fun.id", "definition id"),
    (K.THEOREM, "Fun.monoI", "lemma monoI"),
    (K.THEOREM_COLLECTION, "Groups.ac_simps", "named_theorems ac_simps"),
]

failures: list[str] = []
ran: set[str] = set()


@isabelle_remote_procedure("test.entries_of_names_differential")
async def differential(arg, connection):
    ran.add("differential")
    for kind, name, ctxt, expected in CORPUS:
        label = f"{kind.name} {name!r} @{ctxt}"
        [entry] = await connection.callback("Context.entries_of_names", (ctxt, [(int(kind), name)]))
        try:
            reference = await universal_key_and_name_of(connection, kind, name, ctxt=ctxt)
        except (UndefinedEntity, IsabelleError):
            reference = None
        if entry is None:
            if reference is not None and (kind, name, ctxt) not in FIXED:
                failures.append(f"{label}: resolver NONE but reference {reference[1]!r}")
            if expected is not None:
                failures.append(f"{label}: expected SOME, got NONE")
            continue
        uk, got_name, pos, is_local = bytes(entry[0]), entry[1], tuple(entry[2]), entry[3]
        if reference != (uk, got_name):
            failures.append(f"{label}: resolver {(uk.hex(), got_name)} vs reference {reference}")
        if expected is None:
            failures.append(f"{label}: expected NONE, got {got_name!r}")
            continue
        if "name" in expected and got_name != expected["name"]:
            failures.append(f"{label}: name {got_name!r}, expected {expected['name']!r}")
        if "pos" in expected and (pos[0] != "" and pos[2] != 0) != expected["pos"]:
            failures.append(f"{label}: pos {pos}, expected known={expected['pos']}")
        if "local" in expected and bool(is_local) != expected["local"]:
            failures.append(f"{label}: is_local {is_local}, expected {expected['local']}")
    return len(CORPUS)


@isabelle_remote_procedure("test.definition_of_name")
async def definition_of_name(arg, connection):
    from Isabelle_Semantic_Embedding.semantics import _definition_of_name
    ran.add("definition_of_name")
    for kind, name, needle in DEFINITIONS:
        result = await _definition_of_name(connection, kind, name)
        if result is None:
            failures.append(f"definition of {kind.name} {name!r}: None")
        elif needle not in result[0]:
            failures.append(f"definition of {kind.name} {name!r}: {result[0][:120]!r} lacks {needle!r}")
    return len(DEFINITIONS)


ML_TEST = rf"""
theory {THY} imports Main Semantic_Embedding.Semantic_Embedding begin

lemma rp_single: "(0::nat) \<le> 0" by simp
lemmas rp_multi = rp_single le_refl
named_theorems rp_coll "a dynamic collection"
lemma [rp_coll]: "(1::nat) \<le> 1" by simp
definition rp_def :: "nat \<Rightarrow> nat" where "rp_def n = n"

ML \<open>
let
  open MessagePackBinIO.Pack MessagePackBinIO.Unpack
  open Remote_Procedure_Calling
  val base = \<^context>
  (* ctxt on the wire: nil = base, a string = one of these contexts *)
  val (assumed, assumed_ctxt) = base
    |> Assumption.add_assumes [Thm.cterm_of base (Syntax.read_prop base "rp_def 3 = 3")]
  val contexts =
    [("local", assumed_ctxt
        |> Proof_Context.note_thmss "" [((Binding.name "rp_local", []), [(assumed, [])])] |> snd),
     ("empty", base
        |> Proof_Context.note_thmss "" [((Binding.name "rp_empty", []), [([], [])])] |> snd),
     ("fixed", base |> Variable.add_fixes ["rp_fixed"] |> snd)]
  fun unpack src =
    let val (name, src') = unpackOption unpackString src
    in (Context.Proof (case name of NONE => base | SOME s => the (AList.lookup (op =) contexts s)),
        src') end
  val differential : (unit, int) command = {{
    name = "test.entries_of_names_differential",
    arg_schema = packUnit, ret_schema = unpackInt,
    callback = [Universal_Key.make_universal_key_callback unpack,
                Context_Callbacks.make_entries_of_names_callback unpack],
    timeout = SOME (Time.fromSeconds 300)
  }}
  val config_cb = Config.make_config_lookup_callback
    (Context_Callbacks.static_context_unpacker (Context.Proof base))
  val definitions : (unit, int) command = {{
    name = "test.definition_of_name",
    arg_schema = packUnit, ret_schema = unpackInt,
    callback = Semantic_Store.interpret_file_callbacks config_cb (Context.Proof base),
    timeout = SOME (Time.fromSeconds 300)
  }}
  val _ = call_command differential ()
  val _ = call_command definitions ()
in () end
\<close>

end
"""


async def main():
    async with Client("127.0.0.1:6666", "Draft", timeout=1800) as c:
        results = await c.eval(ML_TEST, timeout=1_800_000)
    errors = [(r.command[:60], r.errors) for r in results or [] if r.errors]
    if results is None or errors:
        sys.exit(f"ERROR: {errors or 'eval returned None'}")
    if ran != {"differential", "definition_of_name"}:
        sys.exit(f"FAILED: relays run: {sorted(ran)}")
    if failures:
        sys.exit("FAILED:\n" + "\n".join(failures))
    print(f"SUCCESS: {len(CORPUS)} names resolved, {len(DEFINITIONS)} definitions read")


if __name__ == "__main__":
    logger = Isabelle_RPC_Host.mk_logger_(RPC_ADDR, None)
    threading.Thread(target=lambda: Isabelle_RPC_Host.launch_server_(RPC_ADDR, logger),
                     daemon=True).start()
    time.sleep(1)
    asyncio.run(main())
