"""Unit tests for the single "record -> embedding document text" authority.

These pin the invariant the single-authority layering exists to establish:

    the embedding document text is a PURE FUNCTION OF THE STORED RECORD

so the text write_memory embeds and the text a later re-embed (auto/offline)
reconstructs are byte-identical BY CONSTRUCTION -- the regression that must never
come back (the EXPERIENCE and entity conventions previously drifted apart).

Pure Python: no Isabelle session, no LMDB, no network.  (pretty_unicode does need the
Isabelle symbol table, i.e. ISABELLE_HOME or `isabelle` on PATH.)
"""

import json

import msgpack
import pytest

from Isabelle_RPC_Host.universal_key import EntityKind
from Isabelle_RPC_Host.unicode import pretty_unicode
from Isabelle_Semantic_Embedding.semantics import _Semantic_DB, SemanticRecord
from Isabelle_Semantic_Embedding.document_text import (
    document_text_of, entity_document_text, experience_document_text)


def _entity(name: str = "foo.bar", expr: str = "a = b",
            interp: 'str | None' = "the fact that a equals b"):
    return SemanticRecord(EntityKind.THEOREM, name, expr, interp)


def _experience(name: str = "exp1", pats: 'list[str] | None' = None,
                desc: 'str | None' = "When the goal is over a finite set"):
    pats = ["\\<forall>x. P x \\<longrightarrow> Q x", "finite S"] if pats is None else pats
    # expr is None: goal_patterns is a real list field (it used to be JSON-packed in expr)
    return SemanticRecord(EntityKind.EXPERIENCE, name, None, desc,
                          None, [("Some_Theory", b"h" * 16)], "how to prove it", pats)


# --- the two conventions -----------------------------------------------------

def test_entity_uses_the_entity_convention():
    rec = _entity()
    assert document_text_of(rec) == rec.pretty_print + "\n" + rec.interpretation
    assert entity_document_text(rec) == document_text_of(rec)


def test_experience_uses_the_framing_convention_with_unicode_patterns():
    pats = ["\\<forall>x. P x \\<longrightarrow> Q x", "finite S"]
    rec = _experience(pats=pats)
    # Patterns are STORED as ASCII (Isabelle's inner lexer needs it) but EMBEDDED as
    # the unicode "semantic form", reconstructed from rec.expr -- not from a separate
    # transient list that a re-embed could not see.
    assert document_text_of(rec) == experience_document_text(
        [pretty_unicode(p) for p in pats], rec.interpretation)
    assert "∀x. P x ⟶ Q x" in document_text_of(rec)


def test_the_two_conventions_differ():
    """The whole point: an experience must NOT be embedded with the entity template."""
    rec = _experience()
    assert document_text_of(rec) != entity_document_text(rec)


# --- the core invariant: pure function of the STORED record ------------------

@pytest.mark.parametrize("rec", [_entity(), _experience()])
def test_text_survives_a_store_roundtrip(rec):
    """Write path and re-embed path must agree byte-for-byte.

    write_memory computes the text from the in-memory record it is about to store;
    _auto_embed / the offline embed compute it from the record read back out of LMDB.
    Encoding and decoding the record must therefore not change the text at all.
    """
    decoded = _Semantic_DB._decode(_Semantic_DB._encode(rec))
    assert document_text_of(decoded) == document_text_of(rec)


# --- not-embeddable records --------------------------------------------------

def test_no_interpretation_is_not_embeddable():
    assert document_text_of(_entity(interp=None)) is None
    assert document_text_of(_experience(desc=None)) is None


def test_experience_without_patterns_is_skipped_not_raised():
    """A record whose patterns could not be recovered (a legacy expr that does not parse)
    must not abort a whole embed batch -- it is one record among thousands in the offline
    embed / the migration."""
    rec = SemanticRecord(EntityKind.EXPERIENCE, "bad", "not json{", "desc")
    assert rec.goal_patterns is None
    assert document_text_of(rec) is None


# --- legacy records: the JSON-in-expr packing is unpacked by the codec ---------

def test_legacy_json_in_expr_is_unpacked_by_the_decoder():
    """Experiences written before goal_patterns existed packed their patterns as JSON
    into `expr`. _decode must recover them AT THE STORAGE BOUNDARY, so no consumer ever
    parses a record -- and such a record must embed exactly like a migrated one."""
    pats = ["\\<forall>x. P x", "finite S"]
    legacy_blob = msgpack.packb((int(EntityKind.EXPERIENCE), "old", json.dumps(pats),
                                 "desc", None, None, "how-to"))   # 7 fields, no goal_patterns
    rec = _Semantic_DB._decode(legacy_blob)
    assert rec.goal_patterns == pats                      # recovered by the codec
    assert rec.expr is None                               # AND normalized: the stale
    # JSON must not survive in expr. Otherwise the record carries the same data twice,
    # and _migrate_constituent_records (_decode -> _replace -> _encode) writes that
    # hybrid back to disk -- so pretty_print goes on rendering the raw JSON.
    migrated = SemanticRecord(EntityKind.EXPERIENCE, "old", None, "desc",
                              None, None, "how-to", pats)
    assert document_text_of(rec) == document_text_of(migrated)   # identical document text


def test_legacy_corrupt_expr_decodes_without_raising():
    blob = msgpack.packb((int(EntityKind.EXPERIENCE), "bad", "not json{", "desc",
                          None, None, None))
    rec = _Semantic_DB._decode(blob)
    assert rec.goal_patterns is None
    assert document_text_of(rec) is None
