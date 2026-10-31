"""The Python half of the link layer (ai-artifacts/LINK_LAYER_PLAN.md §4.2, §4.5).

A local fact of a proof context with a link is shown by its display record: the
fact's live name, its own statement and, as interpretation, the composed copy
(the template's interpretation framed by the fixed wording of §4.5).  It is
ranked by its derived vector, embedded from the display record's document text
(which appends the entities block, never displayed) and kept in the embedding
provider's text cache, never in a ``vector_*`` store.

The links come from the ML callback ``Semantic_Store.links`` of the retrieval
closure, the callback set of the one request a connection serves, fetched only
when needed: by a listing with a theorem or rule among its candidates (hiding
templates needs every candidate's links), or for one theorem or rule key
without a stored record; they and the derived vectors fetched for them live in
``connection.request_state`` and die with the request.
"""

from __future__ import annotations

import asyncio
from enum import Enum, IntEnum
from typing import Any, Awaitable, Callable, NamedTuple

import numpy as np

from Isabelle_RPC_Host.unicode import pretty_unicode
from Isabelle_RPC_Host.universal_key import (EntityKind, RULE_ONLY_TAG_BYTES, destruct_key,
                                             is_thm_rule_key, universal_key, theorem_sibling_key)

from ._vecarith import encode_q15
from .semantic_embedding import DERIVED_VECTOR_TTL, Embedding_Provider
from .semantics import Semantic_DB, SemanticRecord

LINKS_CALLBACK = "Semantic_Store.links"
_REQUEST_STATE_KEY = "Semantic_Embedding.retrieval_closure"


class Link_Kind(Enum):
    """The kind of a link's composed instantiation (§2), a function of its verdicts."""
    IDENTITY = "identity"
    RENAMING = "renaming"
    PROPER = "proper"


class Param_Verdict(IntEnum):
    """What the instantiation does to a parameter of S (D41), as Link_Finder.verdict;
    its value is the wire code, and rev 4's code 2 is refused."""
    UNCHANGED = 0
    RENAMED = 1
    INSTANTIATED = 3


class Param(NamedTuple):
    """A parameter of S in a link: ML's verdict, the name and the instance's text."""
    verdict: Param_Verdict
    name: str
    text: str


class Link(NamedTuple):
    """The link of §2, as Semantic_Store.pack_link sends it; texts in Unicode."""
    template: universal_key
    statement: str
    source: str                          # S's full name; "" for an unnamed block
    note: tuple[str, int]                # the template note's name and index (0: singleton)
    params: list[Param]                  # in Locale.params_of order
    rewrites: list[tuple[str, str]]      # (template term, context term), applied by Level 3 exact
    entities: list[tuple[str, universal_key]]  # the dictionary's (printed name, key)


def kind_of(link: Link) -> Link_Kind:
    """§2: proper iff some parameter is Instantiated, identity iff every one is
    Unchanged, renaming otherwise (Link_Finder.kind_of)."""
    verdicts = [p.verdict for p in link.params]
    if all(v is Param_Verdict.UNCHANGED for v in verdicts):
        return Link_Kind.IDENTITY
    if Param_Verdict.INSTANTIATED in verdicts:
        return Link_Kind.PROPER
    return Link_Kind.RENAMING


def link_of_wire(raw: Any) -> Link:
    template, statement, source, (note, index), params, rewrites, entities = raw
    u = pretty_unicode
    return Link(bytes(template), u(statement), source, (u(note), int(index)),
                [Param(Param_Verdict(v), u(p), u(t)) for v, p, t in params],
                [(u(t), u(c)) for t, c in rewrites],
                [(u(n), bytes(k)) for n, k in entities])


def links_of_wire(raw: Any) -> dict[universal_key, list[Link]]:
    """Every link of a key, in the order ML sends them (§4.2's shared keys, B6)."""
    links: dict[universal_key, list[Link]] = {}
    for uk, link in raw:
        links.setdefault(bytes(uk), []).append(link_of_wire(link))
    return links


def _template_name(link: Link) -> str:
    name, index = link.note
    return name if index == 0 else f"{name}({index})"


def composed_copy(link: Link, template_interpretation: str | None) -> str | None:
    """§4.5's text for a linked fact, assembled from ML's verdicts on its
    parameters (D34, D41), or None while the template has no interpretation."""
    if template_interpretation is None:
        return None
    kind = kind_of(link)
    if kind is Link_Kind.IDENTITY and not link.rewrites:
        return template_interpretation
    template = f"the template `{_template_name(link)}` of the locale `{link.source}`"
    clauses = [f"with `{t}` rewritten into `{c}`" for t, c in link.rewrites]
    rewrites = "".join(", and " + c for c in clauses)
    if kind is Link_Kind.IDENTITY:
        head = f"This entry is {template} " + ", and ".join(clauses) + "."
    elif kind is Link_Kind.RENAMING:
        head = (f"This entry is {template} with its parameters renamed: "
                + ", ".join(f"{p.name} is renamed to `{p.text}`"
                            for p in link.params if p.verdict is Param_Verdict.RENAMED)
                + rewrites + ".")
    else:
        head = (f"This entry is instantiated from {template}, with "
                + ", ".join(f"{p.name} = `{p.text}`" for p in link.params) + rewrites + ".")
    return f"{head}\nThis template means: {template_interpretation}"


def _interpretation(key: universal_key) -> str | None:
    rec = Semantic_DB[key]
    return rec.interpretation if rec is not None else None


ENTITIES_HEADING = "The entities appearing in the instantiation:"


def _full_name(key: universal_key) -> str:
    """An entity's full name, read from its key in Unicode: the entities are
    constants (D51), whose keys carry their names."""
    name = destruct_key(key).name
    assert isinstance(name, str), key.hex()
    return pretty_unicode(name)


def entities_block(link: Link) -> str | None:
    """§4.5's entities block (D40, D50, D51): one line per entity of the
    dictionary whose stored record has an interpretation, the kind word and the
    full name read from its key; None when no entity has one."""
    lines = [f"  - {EntityKind(key[16]).label} `{printed}` (`{_full_name(key)}`): {interpretation}"
             for printed, key in link.entities
             if (interpretation := _interpretation(key)) is not None]
    return "\n".join([ENTITIES_HEADING, *lines]) if lines else None


def display_record(link: Link, kind: EntityKind, name: str) -> SemanticRecord:
    """§2's display record: the fact's live name, its own statement, the composed
    copy as interpretation (None while the template has no interpretation), and
    the entities block, which ``document_text_of`` appends and no renderer prints."""
    return SemanticRecord(kind, name, link.statement,
                          composed_copy(link, _interpretation(link.template)),
                          entities_block=entities_block(link))


def theorem_face(uk: universal_key) -> universal_key:
    """A rule-kind key's theorem sibling, under which the links are keyed."""
    return theorem_sibling_key(uk) if len(uk) == 32 and uk[16] in RULE_ONLY_TAG_BYTES else uk


class Listing:
    """One listing of candidates as the retrieval closure shows it (B6): every
    template that any link of any candidate key names is hidden (where a linked
    local fact is a candidate, its local form is the one that applies in the
    context; a candidate with a link stays), and a key is shown by its stored
    record, else by the display record of its first link."""

    def __init__(self, links: dict[universal_key, list[Link]], candidates: list[universal_key]):
        self._links = links
        templates = {link.template for uk in candidates for link in links.get(theorem_face(uk), ())}
        self.candidates = [uk for uk in candidates
                           if theorem_face(uk) not in templates or self.link_of(uk) is not None]

    def link_of(self, uk: universal_key) -> Link | None:
        """The link a key is shown by: the first of its links."""
        ls = self._links.get(theorem_face(uk))
        return ls[0] if ls else None

    def record(self, uk: universal_key, name: str | None) -> SemanticRecord | None:
        """THE display owner function (§4.2): a key's stored record, else the
        display record when the key has a link (``name``: its live name), else None."""
        rec = Semantic_DB[uk]
        if rec is not None:
            return rec
        link = self.link_of(uk)
        if link is None:
            return None
        if name is None:
            raise ValueError(f"the linked key {uk.hex()} needs its live name to be displayed")
        return display_record(link, EntityKind(uk[16]), name)


class Retrieval_Closure:
    """What the Python side holds of one retrieval closure: its links (every link
    of a key, in ML's order: §4.2's shared keys), fetched only when needed (B6,
    D61: by ``listing`` when a candidate is a theorem or rule, by ``record`` for
    a theorem or rule key without a stored record), and the derived vectors
    fetched for it (Q1.15 rows by (model, composed document text)), so the
    provider's cache is read once per closure."""

    def __init__(self, fetch: Callable[[], Awaitable[Any]] | None):
        self._fetch = fetch
        self._pending: asyncio.Future | None = None
        self._derived: dict[tuple[str, str], np.ndarray] = {}

    async def _links(self) -> dict[universal_key, list[Link]]:
        """The links, fetched by the first call and kept for the closure's
        lifetime, a failure included (ML keeps its value, a finder failure as
        no links, and fails only on an interrupt, which ends the request);
        concurrent first calls share the one fetch, which a cancelled caller
        does not cancel."""
        if self._fetch is None:
            return {}
        if self._pending is None:
            fetch = self._fetch

            async def links() -> dict[universal_key, list[Link]]:
                return links_of_wire(await fetch())
            self._pending = asyncio.ensure_future(links())
        return await asyncio.shield(self._pending)

    async def listing(self, candidates: list[universal_key]) -> Listing:
        """The candidates as one listing shows them; the links are fetched when
        some candidate is a theorem or rule, stored record or not, since hiding
        needs the links of every candidate key."""
        return Listing(await self._links() if any(map(is_thm_rule_key, candidates)) else {},
                       candidates)

    async def record(self, uk: universal_key, name: str | None) -> SemanticRecord | None:
        """The display owner function for one key; the links are fetched only for
        a theorem or rule key without a stored record."""
        needs_links = is_thm_rule_key(uk) and Semantic_DB[uk] is None
        return Listing(await self._links() if needs_links else {}, [uk]).record(uk, name)

    async def derived_vectors(self, provider: Embedding_Provider, texts: list[str]) -> np.ndarray:
        """The derived vectors of ``texts`` as Q1.15 rows: from this closure's
        memory, else in one ``provider.embed`` call (its cache, then the API, its
        retry policy), written to the cache with ``DERIVED_VECTOR_TTL``."""
        model = provider.canonical_model
        missing = [t for t in dict.fromkeys(texts) if (model, t) not in self._derived]
        if missing:
            vectors = (await provider.embed(missing, expire=DERIVED_VECTOR_TTL)).vectors
            for t, v in zip(missing, vectors):
                self._derived[(model, t)] = encode_q15(v)
        return np.stack([self._derived[(model, t)] for t in texts])


NO_LINKS = Retrieval_Closure(None)


def retrieval_closure(connection: Any) -> Retrieval_Closure:
    """The closure of the request ``connection`` serves, one per request, its links
    not fetched until needed; ``NO_LINKS`` without a connection."""
    if connection is None:
        return NO_LINKS
    state = connection.request_state
    closure = state.get(_REQUEST_STATE_KEY)
    if closure is None:
        closure = state[_REQUEST_STATE_KEY] = Retrieval_Closure(
            lambda: connection.callback(LINKS_CALLBACK, None))
    return closure
