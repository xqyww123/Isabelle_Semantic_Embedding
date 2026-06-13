"""Test relays: resolve_notation round-trip and entities_of with a tuple ctxt."""

from Isabelle_RPC_Host import isabelle_remote_procedure, Connection


@isabelle_remote_procedure("test.resolve_notation_roundtrip")
async def test_resolve_notation_roundtrip(arg, connection: Connection):
    pos_opt, probe_string = arg
    result = await connection.callback(
        "explain_term.resolve_notation", (pos_opt, probe_string))
    return result


@isabelle_remote_procedure("test.entities_with_ctxt")
async def test_entities_with_ctxt(arg, connection: Connection):
    """Regression for the F1 unpacker mismatch: enumerate constants under a
    (file, offset) ctxt. With the static (nil-only) unpacker this raised a
    remote unpack failure; with position_context_unpacker it must succeed
    (an unresolvable position just falls back to the default context)."""
    from Isabelle_RPC_Host.context import entities_of
    from Isabelle_RPC_Host.universal_key import EntityKind
    ctxt = tuple(arg) if arg is not None else None
    entries, _is_local, _warnings = await entities_of(
        connection, [EntityKind.CONSTANT], limit=50, ctxt=ctxt)
    return len(entries)
