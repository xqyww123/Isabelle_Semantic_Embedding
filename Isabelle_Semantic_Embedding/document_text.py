"""Single authority for "record -> embedding document text".

This module is the ONE place that decides, per ``Record.kind``, what string a
record is embedded as (its Stage-1 bi-encoder document, and the text the reranker
scores).  It is a pure, dependency-light module: it imports only the ASCII<->unicode
helper and ``EntityKind`` -- never ``semantics`` (that would cycle, since
``semantics`` imports this).  Keeping the convention here, keyed on ``kind``, is
what stops the EXPERIENCE and entity conventions from drifting apart across the
several call sites that turn records into vectors.

The defect this supersedes: the text used to be assembled by each caller, so an
EXPERIENCE embedded by AoA's write_memory (framing + goal patterns + description)
and the same key re-embedded by ``_auto_embed`` or the offline tool (which reached
for the kind-blind ``pretty_print + interpretation``) landed in one vector store
under two conventions -- silently mis-ranking experiences after any embedding-model
change.  Dispatching once, here, on the stored record is what makes write and
re-embed byte-identical by construction.

See ``Isa-Mini/AoA/docs/EXPERIENCE_MEMORY.md`` (§8.1) for the experience document text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from Isabelle_RPC_Host.unicode import pretty_unicode
from Isabelle_RPC_Host.universal_key import EntityKind

if TYPE_CHECKING:
    from .semantics import SemanticRecord


def experience_document_text(patterns: list[str], goal_description: str) -> str:
    """Text embedded for an experience memory (§8.1 of AoA docs/EXPERIENCE_MEMORY.md):
    the goal patterns it targets plus the WHEN-to-use description.  The how-to-prove
    payload is deliberately NOT embedded.  Moved down from AoA's ``mcp_http_server``
    so write and re-embed share one definition; the body is byte-for-byte the same."""
    lines = ["This is an experience that aims to help prove goals of the following forms:"]
    lines += [f"- {p}" for p in patterns]
    lines.append("The experience should be used in the following situation:")
    lines.append(goal_description)
    return "\n".join(lines)


def entity_document_text(rec: 'SemanticRecord') -> str:
    """Document text for a library entity (constant/type/theorem/rule/...): its
    pretty-printed ``kind name: expr`` plus its interpretation.  Precondition:
    ``rec.interpretation is not None`` (callers guard before dispatch)."""
    assert rec.interpretation is not None
    return rec.pretty_print + "\n" + rec.interpretation


def document_text_of(rec: 'SemanticRecord') -> str | None:
    """The single authority: the embedding document text for ``rec``, dispatched on
    ``rec.kind``.  Returns ``None`` when the record has no interpretation yet (not
    embeddable), or -- for an experience -- when its stored patterns fail to parse
    (a corrupt/legacy record whose patterns could not be recovered); either way the
    caller skips embedding it.

    Pure function of the record's fields: no DB, no connection.  It works on an
    in-memory record before it is stored, which is what lets ``write_memory`` embed
    with the very text that a later re-embed reconstructs -- byte-identical by
    construction."""
    if rec.interpretation is None:
        return None
    if rec.kind == EntityKind.EXPERIENCE:
        # goal_patterns is a real list field, stored in ASCII (the form Isabelle's inner
        # lexer re-parses); rebuild the unicode "semantic form" from it so write and
        # re-embed agree.  No parsing here: _decode unpacks legacy JSON-in-expr records
        # at the storage boundary, so a record either HAS its patterns or is corrupt.
        if not rec.goal_patterns:
            return None                      # no patterns (corrupt/legacy) -> not embeddable
        return experience_document_text(
            [pretty_unicode(p) for p in rec.goal_patterns], rec.interpretation)
    return entity_document_text(rec)
