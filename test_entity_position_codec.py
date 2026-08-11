"""T7 of ENTITY_POSITION_PLAN.md §12: the record codec grows a 13th field.

Pure codec tests -- `_encode` / `_decode` are static methods, so nothing here
opens an LMDB environment (which would collide with the store singletons; see
the py-lmdb double-open note).
"""
import msgpack

from Isabelle_RPC_Host.universal_key import EntityKind
from Isabelle_Semantic_Embedding.semantics import _Semantic_DB

Record = _Semantic_DB.Record
_encode = _Semantic_DB._encode
_decode = _Semantic_DB._decode


def _pack_12(rec: Record) -> bytes:
    """The exact 12-field packing the pre-position codec produced."""
    return msgpack.packb((int(rec.kind), rec.name, rec.expr, rec.interpretation,
                          None, rec.theory_constituents, rec.experience,
                          rec.goal_patterns, rec.semantic_digest, rec.deps,
                          rec.version, rec.interpreted_at))  # type: ignore[return-value]


def _full_record(**kw) -> Record:
    """A record with every field before `position` set to something distinctive,
    so that a field silently shifting by one position cannot pass unnoticed."""
    return Record(kind=EntityKind.THEOREM,
                  name="Foo.bar",
                  expr="a = b",
                  interpretation="reflexivity of bar",
                  locale_provenance=None,
                  theory_constituents=[("Foo", b"\x01" * 16)],
                  experience=None,
                  goal_patterns=None,
                  semantic_digest=b"\x02" * 16,
                  deps=[b"\x03" * 17],
                  version=7,
                  interpreted_at=9,
                  **kw)


def test_legacy_12_field_record_reads_with_position_none():
    rec = _full_record()
    decoded = _decode(_pack_12(rec))
    assert decoded.position is None
    assert decoded == rec._replace(position=None)


def test_13_field_record_round_trips():
    rec = _full_record(position=("$AFP/Foo/Bar.thy", 42, 7))
    decoded = _decode(_encode(rec))
    assert decoded == rec
    assert decoded.position == ("$AFP/Foo/Bar.thy", 42, 7)
    # msgpack hands lists back; the field must still be a tuple.
    assert isinstance(decoded.position, tuple)


def test_position_none_round_trips():
    rec = _full_record(position=None)
    assert _decode(_encode(rec)) == rec


def test_replace_on_a_legacy_record_preserves_the_other_twelve_fields():
    """The backfill's write is exactly this: decode a 12-field record, _replace
    the position, encode.  Nothing else may move."""
    legacy = _decode(_pack_12(_full_record()))
    filled = legacy._replace(position=("~~/src/HOL/Nat.thy", 3, 1))
    decoded = _decode(_encode(filled))
    assert decoded.position == ("~~/src/HOL/Nat.thy", 3, 1)
    assert decoded._replace(position=None) == legacy


def test_the_symbolic_file_survives_as_str_not_bytes():
    """msgpack can hand a packed str back as bytes depending on the writer; the
    decoded file must be a str, like every other text field in the record."""
    packed: bytes = msgpack.packb(
        (int(EntityKind.CONSTANT), "Foo.c", None, "the c",
         None, None, None, None, None, None, None, None,
         (b"$AFP/Foo/Bar.thy", 5, 2)))  # type: ignore[assignment]
    decoded = _decode(packed)
    assert decoded.position is not None
    assert decoded.position == ("$AFP/Foo/Bar.thy", 5, 2)
    assert isinstance(decoded.position[0], str)


# --- the wire (ENTITY_POSITION_PLAN.md §6) ---

def _wire_entry(position):
    """One entry as `pack_arg` lays it out: field 4 is the entity position.
    The RPC host unpacks msgpack strings as `str`, so text fields arrive as str."""
    return (int(EntityKind.CONSTANT), "Foo.c", "nat", position,
            b"\x11" * 32, "", None, [], None, [])


def test_entries_of_wire_binds_field_4_as_the_position():
    from Isabelle_Semantic_Embedding.semantic_interpretation import _entries_of_wire
    [e] = _entries_of_wire([_wire_entry(("$AFP/Foo/Bar.thy", 12, 5))])
    assert e.position == ("$AFP/Foo/Bar.thy", 12, 5)
    assert e.line_number == 12                 # the derived property
    assert e.name == "Foo.c"                   # nothing shifted by one slot
    assert e.universal_key == b"\x11" * 32


def test_entries_of_wire_without_a_position():
    from Isabelle_Semantic_Embedding.semantic_interpretation import _entries_of_wire
    [e] = _entries_of_wire([_wire_entry(None)])
    assert e.position is None
    # -1 is what the agent prompt's `line_number > 0` guard expects to see.
    assert e.line_number == -1
