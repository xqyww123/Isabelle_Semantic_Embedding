"""The link layer, Python side (LINK_LAYER_PLAN.md §4.2, §4.5, §7 P2/P3, §8 steps 3-4):
the link codec, the composed copy of each tier, the entities block, the display
record and its document text, the display owner function, and `lookup` with
links (every link of a key, the first shown, every template named hidden): derived
vectors through the provider's cache (7-day expiry) kept in the closure's
memory, scored with topk's cosine and merged, the template hidden, a local fact
with a record of its own using it, one without link or record taking the
default score, rule-kind keys through the theorem sibling, the reranker seeing
the composed document text, links fetched once per request, and no derived key
in any vector_* store.  An isolated SEMANTIC_DB_DIR, a fake connection and a
fake provider; no Isabelle, no API.
Run with  python -m pytest contrib/Semantic_Embedding/tests/test_link_layer.py
"""
import asyncio
import contextlib
import hashlib
import os

import diskcache
import numpy as np
import pytest

from Isabelle_RPC_Host.universal_key import EntityKind

D = 64   # a multiple of every SIMD width: the kernel's masked tail load can fault at the end of an mmap


@pytest.fixture(scope="module", autouse=True)
def isolated_db(tmp_path_factory):
    dbdir = tmp_path_factory.mktemp("semdb")
    prior = os.environ.get("SEMANTIC_DB_DIR")
    os.environ["SEMANTIC_DB_DIR"] = str(dbdir)
    import Isabelle_Semantic_Embedding.semantics as S
    S.Semantic_DB._close()
    yield str(dbdir)
    S.Semantic_DB._close()
    if prior is None:
        os.environ.pop("SEMANTIC_DB_DIR", None)
    else:
        os.environ["SEMANTIC_DB_DIR"] = prior


def key(tag: int, n: int) -> bytes:
    return bytes([0x40 + n] + [n] * 15) + bytes([tag]) + bytes([n] * 15)


THM, INTRO = int(EntityKind.THEOREM), int(EntityKind.INTRODUCTION_RULE)

# templates
T_ANTISYM, T_INSERT, T_ASSOC, T_BARE = key(THM, 1), key(THM, 2), key(THM, 3), key(THM, 4)
T_ORDER_ANTISYM = key(THM, 5)
G_OTHER = key(THM, 6)


def const_key(name: str) -> bytes:
    return bytes([0x20] * 16) + bytes([int(EntityKind.CONSTANT)]) + name.encode()


# the entities of the dictionaries: max and Max have records with an interpretation,
# Bare.none's has none, Bare.q has no record; Foo.\<phi>G's name holds a symbol
C_MAX, C_BIG_MAX, C_NONE, C_Q = (const_key("Orderings.ord_class.max"),
                                 const_key("Lattices_Big.linorder_class.Max"),
                                 const_key("Bare.none"), const_key("Bare.q"))
C_PHI = const_key("Foo.\\<phi>G")
# local facts
L_ANTISYM, L_INSERT, L_ASSOC, L_BARE = key(THM, 11), key(THM, 12), key(THM, 13), key(THM, 14)
L_OWN, L_NONE = key(THM, 15), key(THM, 16)
R_ANTISYM = L_ANTISYM[:16] + bytes([INTRO]) + L_ANTISYM[17:]


def wire_link(template, statement, source, note, params=(), rewrites=(), entities=()):
    return (template, statement, source, note, list(params), list(rewrites), list(entities))


ANTISYM = "x \\<sqsubseteq> y \\<Longrightarrow> y \\<sqsubseteq> x \\<Longrightarrow> x = y"
WIRE = [
    (L_ANTISYM, wire_link(T_ANTISYM, ANTISYM, "Orderings.ordering", ("antisym", 0),
                          [(1, "less_eq", "le"), (0, "less", "less")])),
    # a second link of the same key (B6): never shown, its template hidden all the same
    (L_ANTISYM, wire_link(T_ORDER_ANTISYM, ANTISYM, "Orderings.order", ("antisym", 0),
                          [(1, "less_eq", "le"), (1, "less", "lt")])),
    (L_INSERT, wire_link(T_INSERT, "Max (insert x A) = max x (Max A)", "Lattices_Big.semilattice_set",
                         ("insert", 0), [(3, "f", "max")], [("semilattice_set.F max", "Max")],
                         [("max", C_MAX), ("none", C_NONE), ("Max", C_BIG_MAX)])),
    (L_ASSOC, wire_link(T_ASSOC, "a * b * c = a * (b * c)", "Groups.semigroup", ("assoc", 0),
                        [(0, "f", "f")])),
    (L_BARE, wire_link(T_BARE, "P x", "Foo.bare", ("bare", 2), [(1, "p", "q")], [], [("q", C_Q)])),
    (L_OWN, wire_link(T_ASSOC, "a * b * c = a * (b * c)", "Groups.semigroup", ("assoc", 0))),
]
NAMES = {L_ANTISYM: "local.antisym", L_INSERT: "local.Max.insert", L_ASSOC: "local.assoc",
         L_BARE: "local.bare", L_OWN: "local.own", L_NONE: "local.prems",
         T_ANTISYM: "Orderings.ordering.antisym", T_ORDER_ANTISYM: "Orderings.order.antisym",
         G_OTHER: "HOL.refl", R_ANTISYM: "local.antisym"}
LOCAL = {L_ANTISYM, L_INSERT, L_ASSOC, L_BARE, L_OWN, L_NONE, R_ANTISYM}


# --- the codec and the composed copy ----------------------------------------

def test_codec_decodes_the_wire_value_with_unicode_texts():
    from Isabelle_Semantic_Embedding.links import Link, Link_Kind, Param, Param_Verdict, kind_of, links_of_wire
    links = links_of_wire([(bytearray(k), l) for k, l in WIRE])
    assert [link.template for link in links[L_ANTISYM]] == [T_ANTISYM, T_ORDER_ANTISYM]
    a = links[L_ANTISYM][0]
    assert a == Link(T_ANTISYM, "x ⊑ y ⟹ y ⊑ x ⟹ x = y", "Orderings.ordering", ("antisym", 0),
                     [Param(Param_Verdict.RENAMED, "less_eq", "le"),
                      Param(Param_Verdict.UNCHANGED, "less", "less")], [], [])
    assert kind_of(a) is Link_Kind.RENAMING
    [ins] = links[L_INSERT]
    assert kind_of(ins) is Link_Kind.PROPER
    assert ins.params == [Param(Param_Verdict.INSTANTIATED, "f", "max")]
    assert ins.rewrites == [("semilattice_set.F max", "Max")]
    assert ins.entities == [("max", C_MAX), ("none", C_NONE), ("Max", C_BIG_MAX)]
    assert all(type(k) is bytes for k in links) and type(ins.entities[0][1]) is bytes
    assert kind_of(links[L_ASSOC][0]) is Link_Kind.IDENTITY
    # the printed names in Unicode
    [[u]] = links_of_wire([(L_BARE, wire_link(T_BARE, "s", "S", ("n", 0), [(3, "f", "(\\<le>)")], [],
                                                [("(\\<le>)", C_MAX)]))]).values()
    assert u.params[0].text == "(≤)" and u.entities == [("(≤)", C_MAX)]


@pytest.mark.parametrize("param", [(2, "f", "f"), (2, "f", "f", "real measure"), (1, "f", "g", None)])
def test_codec_refuses_rev_4s_parameters(param):
    """Rev 4's 4-tuple parameters and its code 2 (Type_Fixed) are refused (§7)."""
    from Isabelle_Semantic_Embedding.links import links_of_wire
    with pytest.raises((ValueError, TypeError)):
        links_of_wire([(L_BARE, wire_link(T_BARE, "s", "S", ("n", 0), [param]))])


def test_codec_refuses_rev_4s_link():
    """Rev 4's link carried the kind in the fifth slot and no entities."""
    from Isabelle_Semantic_Embedding.links import links_of_wire
    with pytest.raises((ValueError, TypeError)):
        links_of_wire([(L_BARE, (T_BARE, "s", "S", ("n", 0), 1, [(1, "p", "q", None)], []))])


def test_codec_refuses_the_operation_name_rewrites():
    """D65: a rewrite is (template term, context term); the triple led by the
    operation name, which the wire carried until D65, is refused."""
    from Isabelle_Semantic_Embedding.links import links_of_wire
    with pytest.raises((ValueError, TypeError)):
        links_of_wire([(L_BARE, wire_link(T_BARE, "s", "S", ("n", 0), [], [("F", "a", "b")]))])


def _link(**kw):
    from Isabelle_Semantic_Embedding.links import Link
    base = dict(template=T_ASSOC, statement="s", source="Groups_Big.comm_monoid_set",
                note=("distrib", 0), params=[], rewrites=[], entities=[])
    base.update(kw)
    return Link(**base)


def _p(verdict, name, text):
    from Isabelle_Semantic_Embedding.links import Param, Param_Verdict
    return Param(Param_Verdict[verdict], name, text)


def test_composed_copy_renaming_is_the_plan_text():
    from Isabelle_Semantic_Embedding.links import composed_copy
    link = _link(params=[_p("RENAMED", "f", "plus"), _p("RENAMED", "z", "zero")],
                 rewrites=[("comm_monoid_set.F plus zero", "sum")])
    assert composed_copy(link, "TEMPLATE.") == (
        "This entry is the template `distrib` of the locale `Groups_Big.comm_monoid_set` with its parameters "
        "renamed: f is renamed to `plus`, z is renamed to `zero`, and with "
        "`comm_monoid_set.F plus zero` rewritten into `sum`.\n"
        "This template means: TEMPLATE.")
    # without rewrites; an unchanged parameter is left out
    assert composed_copy(_link(params=[_p("RENAMED", "f", "plus"), _p("UNCHANGED", "z", "z")]),
                         "TEMPLATE.") == (
        "This entry is the template `distrib` of the locale `Groups_Big.comm_monoid_set` with its parameters "
        "renamed: f is renamed to `plus`.\n"
        "This template means: TEMPLATE.")


def test_composed_copy_reads_the_verdicts_never_the_texts():
    """sum_list.Cons in linordered_field: the target is the printed text; whether a
    parameter is listed is ML's verdict, whatever its text says (D34)."""
    from Isabelle_Semantic_Embedding.links import composed_copy
    cons = _link(source="Groups_List.monoid_list", note=("Cons", 0),
                 params=[_p("RENAMED", "f", "(+)"), _p("RENAMED", "z", "0")],
                 rewrites=[("monoid_list.F (+) 0", "sum_list")])
    assert composed_copy(cons, "TEMPLATE.") == (
        "This entry is the template `Cons` of the locale `Groups_List.monoid_list` with its parameters "
        "renamed: f is renamed to `(+)`, z is renamed to `0`, and with "
        "`monoid_list.F (+) 0` rewritten into `sum_list`.\n"
        "This template means: TEMPLATE.")
    # an unchanged parameter whose text differs from its name stays out; a renamed
    # one whose text equals its name stays in
    assert composed_copy(_link(params=[_p("UNCHANGED", "less_eq", "(≤)"), _p("RENAMED", "f", "f")]),
                         "T.").splitlines()[0] == (
        "This entry is the template `distrib` of the locale `Groups_Big.comm_monoid_set` with its parameters "
        "renamed: f is renamed to `f`.")


def test_composed_copy_identity_with_rewrites_is_the_plan_text():
    """§4.5, D41, D65: a rewrite is a dictionary entry, so an identity link decided
    at Level 3 exact gets the rewrites-only line (a synthetic link)."""
    from Isabelle_Semantic_Embedding.links import composed_copy
    link = _link(source="Synthetic.L", note=("t", 0), params=[_p("UNCHANGED", "p", "p")],
                 rewrites=[("L.F p", "G")])
    assert composed_copy(link, "TEMPLATE.") == (
        "This entry is the template `t` of the locale `Synthetic.L` with `L.F p` rewritten into `G`.\n"
        "This template means: TEMPLATE.")
    # several rewrites repeat the clause
    two = link._replace(rewrites=[("a", "b"), ("c", "d")])
    assert composed_copy(two, "T.").splitlines()[0] == (
        "This entry is the template `t` of the locale `Synthetic.L` with `a` rewritten into `b`, "
        "and with `c` rewritten into `d`.")


def test_composed_copy_renaming_never_mentions_a_type():
    """D41: a parameter that keeps its name with another type is Unchanged and left
    out; one renamed with another type reads "M is renamed to `N`"."""
    from Isabelle_Semantic_Embedding.links import composed_copy
    link = _link(source="Link_Finder_Verdicts_Test.VT", note=("vt", 0),
                 params=[_p("RENAMED", "M", "N"), _p("UNCHANGED", "z", "z")])
    assert composed_copy(link, "TEMPLATE.") == (
        "This entry is the template `vt` of the locale `Link_Finder_Verdicts_Test.VT` with its parameters "
        "renamed: M is renamed to `N`.\n"
        "This template means: TEMPLATE.")


def test_composed_copy_proper_is_the_plan_text():
    from Isabelle_Semantic_Embedding.links import composed_copy
    link = _link(source="Lattices_Big.semilattice_set", note=("insert", 0),
                 params=[_p("INSTANTIATED", "f", "max")],
                 rewrites=[("semilattice_set.F max", "Max")])
    assert composed_copy(link, "TEMPLATE.") == (
        "This entry is instantiated from the template `insert` of the locale `Lattices_Big.semilattice_set`, "
        "with f = `max`, and with `semilattice_set.F max` rewritten into `Max`.\n"
        "This template means: TEMPLATE.")
    # no rewrites clause without rewrites
    assert composed_copy(link._replace(rewrites=[]), "TEMPLATE.") == (
        "This entry is instantiated from the template `insert` of the locale `Lattices_Big.semilattice_set`, "
        "with f = `max`.\n"
        "This template means: TEMPLATE.")
    # every parameter is listed with its text, whatever its verdict (bounded_linear's module_hom)
    hom = _link(source="Modules.module_hom", note=("add", 0),
                params=[_p("INSTANTIATED", "s1", "(*⇩R)"), _p("INSTANTIATED", "s2", "(*⇩R)"),
                        _p("UNCHANGED", "f", "f")])
    assert composed_copy(hom, "T.").splitlines()[0] == (
        "This entry is instantiated from the template `add` of the locale `Modules.module_hom`, "
        "with s1 = `(*⇩R)`, s2 = `(*⇩R)`, f = `f`.")
    # A2: f ↦ r, g ↦ r is proper and prints both parameters
    a2 = _link(source="S.two", note=("n", 0), params=[_p("UNCHANGED", "f", "f"), _p("INSTANTIATED", "g", "f")])
    assert composed_copy(a2, "T.").splitlines()[0] == (
        "This entry is instantiated from the template `n` of the locale `S.two`, with f = `f`, g = `f`.")


def test_composed_copy_identity_unwritable_and_indexed():
    from Isabelle_Semantic_Embedding.links import composed_copy
    assert composed_copy(_link(params=[_p("UNCHANGED", "f", "f")]), "TEMPLATE.") == "TEMPLATE."
    assert composed_copy(_link(params=[]), "TEMPLATE.") == "TEMPLATE."
    assert composed_copy(_link(params=[_p("RENAMED", "f", "plus")]), None) is None
    assert composed_copy(_link(note=("distrib", 2), params=[_p("RENAMED", "f", "g")]),
                         "T.").startswith("This entry is the template `distrib(2)` of the locale")


# --- the retrieval closure and lookup ---------------------------------------

def vec(text: str) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")
    return np.random.default_rng(seed).standard_normal(D).astype(np.float32)


QUERY = "the query"


class FakeProvider:
    """An Embedding_Provider whose backend is `vec`, counting calls and texts."""

    def __init__(self, cache):
        from Isabelle_Semantic_Embedding import semantic_embedding as se

        class P(se.Embedding_Provider):
            def __init__(self):
                self.canonical_model = "fake-model"
                self.model = "fake-model"
                self.dimension = D
                self.normalize = False
                self.max_request_size = 100
                self.default_score, self.default_local_score = 0.1, 0.3
                self.embedded: list[str] = []

            async def _embed(self, text):
                self.embedded += text
                return se.EmbedResult(np.stack([vec(t) for t in text]), len(text))

            async def _log(self, msg):
                pass

        self.p = P()


class FakeConnection:
    def __init__(self):
        self.request_state = {}
        self.calls: dict[str, int] = {}

    def new_request(self):
        self.request_state = {}

    async def callback(self, name, arg):
        self.calls[name] = self.calls.get(name, 0) + 1
        if name == "Semantic_Store.links":
            assert arg is None
            return [(bytearray(k), l) for k, l in WIRE]
        if name == "Semantic_Store.excluded_theory_names":
            return []
        if name in ("Context.theorems", "Context.introduction_rules"):
            keys = ([L_ANTISYM, L_INSERT, L_ASSOC, L_BARE, L_OWN, L_NONE, T_ANTISYM, T_ORDER_ANTISYM, G_OTHER]
                    if name == "Context.theorems" else [R_ANTISYM])
            return self.enumeration_reply(arg, [(k, NAMES[k], k in LOCAL) for k in keys])
        if name == "Context.constants":
            return self.enumeration_reply(arg, [(C_MAX, "Orderings.ord_class.max", False),
                                                (C_Q, "Bare.q", False)])
        return [], []

    @staticmethod
    def enumeration_reply(arg, catalog):
        """The reply of a callback whose catalog is `catalog`, all of it this call's
        result: every index, and the entries from the request's synced_length on."""
        synced_length = arg[1][9]
        return (list(range(len(catalog))),
                [(*e, i) for i, e in enumerate(catalog)][synced_length:], [])

    async def config_lookup(self, name, ctxt=None):
        return None

    async def tracing(self, msg):
        pass

    async def warning(self, msg):
        pass


@pytest.fixture(scope="module")
def world(isolated_db, tmp_path_factory):
    """Records for the templates and two other keys; vectors for the template,
    the global key and the local fact with its own record."""
    from Isabelle_Semantic_Embedding import semantic_embedding as se
    from Isabelle_Semantic_Embedding import semantics as S
    from Isabelle_Semantic_Embedding._vecarith import encode_q15
    R = S.SemanticRecord
    S.Semantic_DB[T_ANTISYM] = R(EntityKind.THEOREM, "Orderings.ordering.antisym", "x ≤ y", "Antisymmetry.")
    S.Semantic_DB[T_INSERT] = R(EntityKind.THEOREM, "Lattices_Big.semilattice_set.insert", "F", "Insert.")
    S.Semantic_DB[T_ASSOC] = R(EntityKind.THEOREM, "Groups.semigroup.assoc", "a", "Associativity.")
    S.Semantic_DB[G_OTHER] = R(EntityKind.THEOREM, "HOL.refl", "t = t", "Reflexivity.")
    S.Semantic_DB[L_OWN] = R(EntityKind.THEOREM, "local.own", "a", "Its own record.")
    S.Semantic_DB[C_MAX] = R(EntityKind.CONSTANT, "Orderings.ord_class.max", "'a ⇒ 'a ⇒ 'a", "The maximum.")
    S.Semantic_DB[C_BIG_MAX] = R(EntityKind.CONSTANT, "Lattices_Big.linorder_class.Max", "'a set ⇒ 'a",
                                 "The greatest element.")
    S.Semantic_DB[C_NONE] = R(EntityKind.CONSTANT, "Bare.none", "'a", None)
    S.Semantic_DB[C_PHI] = R(EntityKind.CONSTANT, "Foo.φG", "'a", "Phi.")
    cache = diskcache.Cache(str(tmp_path_factory.mktemp("cache") / "embed_cache"), size_limit=1 << 24)
    se.Embedding_Provider._cache = cache
    provider = FakeProvider(cache).p
    conn = FakeConnection()
    store = S.Semantic_Vector_Store(emb_provider=provider, connection=conn)
    with store._env.begin(write=True) as txn:
        for k in (T_ANTISYM, G_OTHER, L_OWN):
            txn.put(k, encode_q15(vec(f"stored {k.hex()}")).tobytes())
    yield store, conn, provider, cache
    se.Embedding_Provider._cache = None
    cache.close()


def snapshot_vector_stores(dbdir):
    """Every vector_* store's content (through the process's one env per path)."""
    from Isabelle_Semantic_Embedding.semantic_embedding import _get_lmdb_env
    out = {}
    for name in sorted(os.listdir(dbdir)):
        if name.startswith("vector_") and name.endswith(".lmdb"):
            with _get_lmdb_env(os.path.join(dbdir, name)).begin() as txn:
                out[name] = {bytes(k): bytes(v) for k, v in txn.cursor()}
    return out


def run(coro):
    return asyncio.run(coro)


def lookup(store, kinds=(EntityKind.THEOREM,), k=20):
    return run(store.lookup(QUERY, k, list(kinds), interpret_in_auto_embed=False))


def by_name(results):
    return {rec.name: (score, rec) for score, rec in results}


def expected_text(name, statement, copy):
    return f"lemma {name}: {statement}\n{copy}"


INSERT_BLOCK = ("The entities appearing in the instantiation:\n"
                "  - constant `max` (`Orderings.ord_class.max`): The maximum.\n"
                "  - constant `Max` (`Lattices_Big.linorder_class.Max`): The greatest element.")


def test_entities_block_is_the_plan_text(world):
    """§4.5, D40, D50: the kind word and the full name from the key; an entity
    without a record or without an interpretation is left out; no line, no block."""
    from Isabelle_Semantic_Embedding.links import entities_block, links_of_wire
    links = links_of_wire(WIRE)
    assert entities_block(links[L_INSERT][0]) == INSERT_BLOCK
    assert entities_block(links[L_BARE][0]) is None          # Bare.q has no record
    assert entities_block(links[L_ASSOC][0]) is None         # an identity with an empty dictionary
    assert entities_block(_link(entities=[("none", C_NONE)])) is None
    # the full name in Unicode, as every text of a link
    assert entities_block(_link(entities=[("φG", C_PHI)])) == (
        "The entities appearing in the instantiation:\n  - constant `φG` (`Foo.φG`): Phi.")


def test_listing_hides_named_templates_and_keeps_linked_candidates():
    """B6: every template that any link of any candidate key names is hidden; a
    candidate that has a link of its own stays, even when a link names it."""
    from Isabelle_Semantic_Embedding.links import Listing
    k_self, k_a, k_b, k_t = key(THM, 40), key(THM, 41), key(THM, 42), key(THM, 43)
    links = {k_self: [_link(template=k_self)], k_a: [_link(template=k_b)], k_b: [_link(template=k_t)]}
    assert Listing(links, [k_self, k_a, k_b, k_t]).candidates == [k_self, k_a, k_b]
    assert Listing(links, [k_t, k_a]).candidates == [k_t, k_a]   # k_b, which names k_t, is not listed


def test_display_record_carries_the_block_for_the_document_text_only(world):
    """D50: the composed document text appends the block; the record's displayed
    fields (interpretation, pretty print) never contain it, and it is never stored."""
    from Isabelle_Semantic_Embedding import semantics as S
    from Isabelle_Semantic_Embedding.document_text import document_text_of
    from Isabelle_Semantic_Embedding.links import display_record, links_of_wire
    rec = display_record(links_of_wire(WIRE)[L_INSERT][0], EntityKind.THEOREM, "local.Max.insert")
    assert rec.entities_block == INSERT_BLOCK
    copy = ("This entry is instantiated from the template `insert` of the locale `Lattices_Big.semilattice_set`, "
            "with f = `max`, and with `semilattice_set.F max` rewritten into `Max`.\n"
            "This template means: Insert.")
    assert rec.interpretation == copy
    assert document_text_of(rec) == expected_text("local.Max.insert", "Max (insert x A) = max x (Max A)",
                                                  copy) + "\n" + INSERT_BLOCK
    assert "entities appearing" not in rec.pretty_print + rec.interpretation
    # without entities with an interpretation, the document text has no block
    bare = display_record(links_of_wire(WIRE)[L_ASSOC][0], EntityKind.THEOREM, "local.assoc")
    assert bare.entities_block is None and document_text_of(bare) == "lemma local.assoc: a * b * c = a * (b * c)\nAssociativity."
    with pytest.raises(AssertionError):
        S.Semantic_DB[key(THM, 30)] = rec
    assert S.Semantic_DB[key(THM, 30)] is None


def test_lookup_with_links(world, isolated_db):
    from Isabelle_Semantic_Embedding._vecarith import encode_q15, recover_cos
    from Isabelle_Semantic_Embedding.document_text import document_text_of
    store, conn, provider, cache = world
    conn.new_request()
    results, _, total = lookup(store)
    got = by_name(results)
    # the templates are hidden: a local fact linked to them is a candidate, the
    # second through the key's second link, which is never shown (B6)
    assert "Orderings.ordering.antisym" not in got and "Orderings.order.antisym" not in got
    assert total == 7
    # the renaming link: display record, composed document text, derived score
    score, rec = got["local.antisym"]
    copy = ("This entry is the template `antisym` of the locale `Orderings.ordering` with its parameters "
            "renamed: less_eq is renamed to `le`.\nThis template means: Antisymmetry.")
    assert (rec.kind, rec.expr, rec.interpretation) == (
        EntityKind.THEOREM, "x ⊑ y ⟹ y ⊑ x ⟹ x = y", copy)
    text = document_text_of(rec)
    assert text == expected_text("local.antisym", "x ⊑ y ⟹ y ⊑ x ⟹ x = y", copy)
    q = encode_q15(vec(QUERY)).astype(np.float64)

    def derived_score(rec):
        text = document_text_of(rec)
        return recover_cos(np.array([np.rint(encode_q15(vec(text)).astype(np.float64) @ q / 32768)]), D)[0]
    # each linked fact is ranked by the vector of its composed document text, the
    # entities block included (Max.insert's)
    for name in ("local.antisym", "local.Max.insert", "local.assoc"):
        assert got[name][0] == pytest.approx(derived_score(got[name][1]), abs=2e-3), name
    # the proper link ends with the template's text, and its document text with the
    # entities block; identity is the template's text
    assert got["local.Max.insert"][1].interpretation.splitlines()[1] == "This template means: Insert."
    assert document_text_of(got["local.Max.insert"][1]).endswith("\n" + INSERT_BLOCK)
    assert got["local.assoc"][1].interpretation == "Associativity."
    # a template without a record: display record, no text, the local default score
    assert got["local.bare"] == (0.3, got["local.bare"][1])
    assert got["local.bare"][1].interpretation is None and got["local.bare"][1].expr == "P x"
    # own record wins; no link and no record: placeholder with the local default
    assert got["local.own"][1].interpretation == "Its own record."
    assert got["local.prems"][0] == 0.3 and got["local.prems"][1].interpretation is None
    assert "HOL.refl" in got


def test_derived_vectors_once_per_closure_and_seven_days(world):
    from Isabelle_Semantic_Embedding import semantic_embedding as se
    store, conn, provider, cache = world
    conn.new_request()
    conn.calls.clear()
    reads: list = []
    real_get = cache.get

    def counting_get(k, *a, **kw):
        reads.append(k[1])
        return real_get(k, *a, **kw)

    cache.get = counting_get
    try:
        r1, _, _ = lookup(store)
        r2, _, _ = lookup(store)
    finally:
        del cache.get
    assert conn.calls["Semantic_Store.links"] == 1
    derived = [t for t in set(reads) if t.startswith("lemma local.")]
    assert len(derived) == 3                       # antisym, Max.insert, assoc
    assert all(reads.count(t) == 1 for t in derived)   # the cache is read once per closure
    assert [(s, r.name) for s, r in r1] == [(s, r.name) for s, r in r2]
    for t in derived:
        _, expire = real_get(("fake-model", t), expire_time=True)
        _, qexpire = real_get(("fake-model", QUERY), expire_time=True)
        assert expire - qexpire == pytest.approx(se.DERIVED_VECTOR_TTL - se._EMBED_CACHE_TTL, abs=600)
    # a new request is a new closure: links fetched again
    conn.new_request()
    lookup(store)
    assert conn.calls["Semantic_Store.links"] == 2


def test_no_derived_key_in_any_vector_store(world, isolated_db):
    store, conn, provider, cache = world
    before = snapshot_vector_stores(isolated_db)
    conn.new_request()
    lookup(store)
    after = snapshot_vector_stores(isolated_db)
    assert before == after
    for content in after.values():
        assert not ({L_ANTISYM, L_INSERT, L_ASSOC, L_BARE, R_ANTISYM} & set(content))


def test_rule_kind_key_goes_through_the_theorem_sibling(world):
    store, conn, provider, cache = world
    conn.new_request()
    results, _, _ = lookup(store, kinds=(EntityKind.INTRODUCTION_RULE,))
    [(score, rec)] = results
    assert rec.kind == EntityKind.INTRODUCTION_RULE and rec.name == "local.antisym"
    assert rec.interpretation.startswith("This entry is the template `antisym`")


def test_reranker_scores_the_composed_document_text(world, monkeypatch):
    from types import SimpleNamespace
    from Isabelle_Semantic_Embedding.document_text import document_text_of
    store, conn, provider, cache = world
    seen: list[str] = []

    class Rerank:
        async def rerank(self, query, docs, k):
            seen.extend(docs)
            order = sorted(range(len(docs)), key=lambda i: "local.antisym" not in docs[i])
            return SimpleNamespace(indices=order[:k], scores=[1.0 - 0.1 * j for j in range(k)])

    async def get_reranker():
        return Rerank()

    monkeypatch.setattr(store, "_get_reranker", get_reranker)
    conn.new_request()
    results, _, _ = lookup(store, k=3)
    assert results[0][1].name == "local.antisym"
    assert document_text_of(results[0][1]) in seen
    # the reranker reads the entities block with the rest of the composed document text
    assert any(d.startswith("lemma local.Max.insert:") and d.endswith(INSERT_BLOCK) for d in seen)


def test_owner_function_is_a_direct_read_without_a_link(world):
    from Isabelle_Semantic_Embedding import semantics as S
    from Isabelle_Semantic_Embedding.links import NO_LINKS, retrieval_closure
    store, conn, provider, cache = world
    conn.new_request()
    closure = retrieval_closure(conn)
    assert retrieval_closure(conn) is closure
    for k in (G_OTHER, T_ANTISYM, L_OWN, L_NONE):
        assert run(closure.record(k, NAMES.get(k))) == S.Semantic_DB[k]
    assert run(closure.record(L_ANTISYM, "x")).name == "x"
    assert run(NO_LINKS.record(L_ANTISYM, "x")) is None
    assert retrieval_closure(None) is NO_LINKS


def test_the_links_are_fetched_only_when_needed(world):
    """B6, D61: a constant's record, a key with a stored record and a listing with
    no theorem or rule candidate never start the finder; a listing with one does,
    stored record or not, since it hides the templates its candidates' links name;
    the links are fetched once per request."""
    from Isabelle_Semantic_Embedding.links import retrieval_closure
    store, conn, provider, cache = world
    conn.new_request()
    conn.calls.clear()
    closure = retrieval_closure(conn)
    assert run(closure.record(C_MAX, "max")).interpretation == "The maximum."
    assert run(closure.record(C_Q, "q")) is None
    assert run(closure.record(L_OWN, "local.own")).interpretation == "Its own record."
    listing = run(closure.listing([C_MAX, C_Q]))
    assert listing.candidates == [C_MAX, C_Q] and listing.record(C_MAX, "max").name.endswith("max")
    assert "Semantic_Store.links" not in conn.calls
    assert run(closure.record(L_ANTISYM, "local.antisym")).interpretation.startswith("This entry is")
    run(closure.listing([L_INSERT, C_MAX]))
    assert conn.calls["Semantic_Store.links"] == 1
    # a constant-only lookup over the closure's domain does not fetch either
    conn.new_request()
    conn.calls.clear()
    results, _, total = run(store.lookup(QUERY, 5, [EntityKind.CONSTANT], interpret_in_auto_embed=False))
    assert total == 2 and "Semantic_Store.links" not in conn.calls
    # a listing of a key with a stored record fetches, to hide the template its link names
    conn.new_request()
    conn.calls.clear()
    assert run(retrieval_closure(conn).listing([L_OWN, T_ASSOC])).candidates == [L_OWN]
    assert conn.calls["Semantic_Store.links"] == 1


def test_concurrent_first_calls_share_one_fetch_and_a_failure_is_kept(world):
    from Isabelle_Semantic_Embedding.links import retrieval_closure

    class Slow(FakeConnection):
        fail = True

        async def callback(self, name, arg):
            await asyncio.sleep(0.01)
            if name == "Semantic_Store.links" and self.fail:
                self.fail = False
                self.calls[name] = self.calls.get(name, 0) + 1
                raise RuntimeError("interrupted")
            return await super().callback(name, arg)

    conn = Slow()
    conn.fail = False
    closure = retrieval_closure(conn)

    async def go():
        return await asyncio.gather(closure.listing([L_ANTISYM]), closure.record(L_INSERT, "local.Max.insert"))

    a, rec = run(go())
    assert a.link_of(L_ANTISYM).template == T_ANTISYM and rec.expr == "Max (insert x A) = max x (Max A)"
    assert conn.calls["Semantic_Store.links"] == 1
    # a failed fetch is kept for the closure's lifetime: the next call re-raises it without
    # fetching again
    conn = Slow()
    closure = retrieval_closure(conn)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            run(closure.listing([L_ANTISYM]))
    assert conn.calls["Semantic_Store.links"] == 1
    # a caller cancelled during the first fetch does not cancel the shared fetch,
    # which would otherwise be kept as a CancelledError for the closure's lifetime
    conn = Slow()
    conn.fail = False
    closure = retrieval_closure(conn)

    async def cancelled_first():
        first = asyncio.ensure_future(closure.listing([L_ANTISYM]))
        await asyncio.sleep(0)
        first.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await first
        return await closure.listing([L_ANTISYM])

    assert run(cancelled_first()).link_of(L_ANTISYM).template == T_ANTISYM
    assert conn.calls["Semantic_Store.links"] == 1
