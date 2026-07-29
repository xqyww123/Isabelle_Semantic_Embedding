"""Experience-memory write/delete as one transaction across the three stores an
experience lives in: its record (``Semantic_DB``), its per-model vectors
(``Semantic_Vector_Store``), and the availability inverted index
(``Experience_Index``).

An experience is ONE logical entity spread over these three.  Keeping the ordering
(embed-first) and the multi-store fan-out here -- not inlined in AoA's write_memory
handler -- is what the layering refactor buys.  These functions need no connection:
embedding uses the store's bound (model, provider); the two indexes are process-wide
singletons.  Text is produced only by ``document_text_of`` (via ``embed_records``),
so write and any later re-embed are byte-identical by construction.

See ``Isa-Mini/AoA/docs/EXPERIENCE_MEMORY.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .semantics import Semantic_DB
from .semantic_embedding import invalidate_vectors
from .experience_index import Experience_Index
from .document_text import document_text_of

if TYPE_CHECKING:
    from Isabelle_RPC_Host.universal_key import universal_key
    from .semantics import Semantic_Vector_Store, SemanticRecord


async def put_experience(store: 'Semantic_Vector_Store', key: 'universal_key',
                         rec: 'SemanticRecord') -> None:
    """Create or overwrite the experience ``rec`` under ``key``.

    RECORD, then INDEX, then EMBED (ordering rule 2).  The fallible/remote step
    goes LAST, so that when it fails everything durable is already in place.

    Embed-first, which this used to do, is now self-defeating: ``Semantic_DB``'s
    setter tombstones the key's vectors, so a vector written first would be
    tombstoned by the record write one line later.  And record-first is not
    merely forced, it is better:

    - a record+index entry with no vector is NOT the "silent, unretrievable
      orphan" this docstring used to claim.  The experience retrieval domain is
      Experience_Index-driven -- ``lookup`` runs ``topk`` over the keys the index
      returned, not over the keys the vector store holds -- so a vector-less key
      still enters the domain, is reported missing, and ``_auto_embed`` rebuilds
      it from the record (its EXPERIENCE pass ignores the interpretation gates).
    - ``delete_experience`` below already states the priority: the record holds
      the whole experience and nothing can rebuild it; the index and the vectors
      are derived.  Under a provider outage, embed-first DISCARDS agent-authored
      content that cannot be regenerated; record-first keeps it and fills the
      vector in later.
    - the index must precede the embed for the same reason it follows the
      record: ``_experience_hits`` is index-driven, so a failure before the index
      write would make the experience permanently invisible.

    Embeds into the ACTIVE model's store only; other models backfill lazily.
    Text comes from ``document_text_of`` inside ``embed_records``, i.e.
    reconstructed from ``rec`` itself.

    Raises ValueError when ``rec`` has no embeddable document text (no
    interpretation, or no ``goal_patterns``).  Kept from the embed-first design,
    and still right under the new order: a record that can NEVER be embedded is a
    different case from one whose embedding is merely pending, and should still
    be refused.  (Do NOT test embed_records' return value instead: that is a
    token count, and a provider may legitimately report 0.)"""
    if document_text_of(rec) is None:
        raise ValueError(
            f"refusing to store experience {rec.name!r}: it has no embeddable document "
            f"text (no interpretation, or no goal_patterns)")
    Semantic_DB[key] = rec
    Experience_Index.add(key, [h for _, h in (rec.theory_constituents or [])])
    await store.embed_records([(key, rec)], force=True)


def delete_experience(key: 'universal_key') -> None:
    """Remove the experience ``key`` from EVERY store: its record, its vector in each
    model's ``vector_*.lmdb``, and its availability-index entry.

    Vectors are purged from all models (not just the active one): experience keys are
    content-addressed, so an overwrite with changed content mints a NEW key and the
    old key's vectors would otherwise linger as orphans in inactive models.  Deletion
    is cheap and dimension-agnostic, so purging everywhere is both easy and correct --
    the deliberate counterpart to ``put_experience`` embedding into one model only.

    ORDER MATTERS, and it is the exact dual of put_experience's embed-first: the
    authoritative record dies LAST.  The record holds the whole experience (patterns,
    description, the how-to-prove payload) and nothing can rebuild it; the index and the
    vectors are derived (Experience_Index.rebuild / a re-embed restore them).  So we
    stop advertising it, then drop the derived caches, and only then delete the content.
    Any failure partway -- an unopenable vector store, a killed process -- then leaves at
    worst an un-indexed, un-embedded record: recoverable, and the delete is idempotently
    retryable.  Deleting the record first (as the old inline _delete_uk did) would
    destroy agent-authored content forever if the vector loop raised."""
    old = Semantic_DB[key]
    consts = old.theory_constituents if old is not None else None
    # 1. stop advertising it (derived: rebuildable from the records)
    if consts:
        Experience_Index.remove(key, [h for _, h in consts])
    else:
        Experience_Index.remove_scanning(key)
    # 2. drop the derived vectors, in every model's store.  Through the one
    #    invalidation helper (this loop is where its single-key form came from),
    #    so this key gets a vector TOMBSTONE rather than a real deletion: a
    #    deleted user vector would let the system layer's copy show through for a
    #    record that no longer exists.
    invalidate_vectors([key])
    # 3. the authoritative content dies last
    Semantic_DB.delete(key)
