"""Test relay: receives a term, calls desugar_and_explain callback, returns result."""

from Isabelle_RPC_Host import isabelle_remote_procedure, Connection


@isabelle_remote_procedure("test.desugar_roundtrip")
async def test_desugar_roundtrip(arg, connection: Connection):
    pos_opt, term_string = arg
    result = await connection.callback(
        "explain_term.desugar_and_explain", (pos_opt, term_string))
    return result
