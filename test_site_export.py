"""The site export's rules (SEMANTIC_SEARCH_SITE_PLAN.md §8), tested where they can
be tested without the database, the Isabelle installation or the network.

What is left to a run against the real store — the scope census, the completeness
gate, the separator probe — is recorded in §8.1 beside each step.
"""
import json
import os
from types import SimpleNamespace

import pytest

from Isabelle_Semantic_Embedding import site_export as se


# --- D24's scope ------------------------------------------------------------

def _tree(tmp_path, name, root_text):
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "ROOT").write_text(root_text, encoding="utf-8")
    return str(d)


def test_a_quoted_session_name_survives_its_own_punctuation(tmp_path):
    """`session "CoreC++"` is a real AFP entry, and a reader that stops at the `+`
    puts its 2,915 published records out of scope with no error anywhere."""
    tree = _tree(tmp_path, "afp", 'session "CoreC++" = "HOL-Library" +\n  theories A\n')
    assert "CoreC++" in se.declared_sessions(tree)


def test_an_unquoted_session_is_read_up_to_its_first_separator(tmp_path):
    tree = _tree(tmp_path, "d", "session HOL-Library (main) in Library = HOL +\n")
    assert "HOL-Library" in se.declared_sessions(tree)


def test_a_commented_out_session_is_not_declared(tmp_path):
    """Six of these sit in the two trees; a session nobody builds is not in scope."""
    tree = _tree(tmp_path, "d", 'session Real = HOL +\n(* session Ghost = HOL +\n *)\n')
    declared = se.declared_sessions(tree)
    assert "Real" in declared and "Ghost" not in declared


def test_root_comments_nest(tmp_path):
    tree = _tree(tmp_path, "d", "(* a (* b *) session Ghost = HOL + *)\nsession Real = HOL +\n")
    declared = se.declared_sessions(tree)
    assert "Real" in declared and "Ghost" not in declared


def test_the_four_base_logics_are_members(tmp_path):
    """D24's own clause: `Pure`, `FOL`, `IFOL` and `ZF` carry no session prefix
    because they genuinely have none."""
    tree = _tree(tmp_path, "d", "session Real = HOL +\n")
    assert se.BASE_LOGICS <= se.declared_sessions(tree)


def test_a_tree_declaring_nothing_is_refused(tmp_path):
    """Silently exporting nothing is the failure this prevents."""
    tree = _tree(tmp_path, "d", "chapter AFP\n")
    with pytest.raises(se.ExportError):
        se.declared_sessions(tree)


def test_the_session_of_a_theory_long_name():
    assert se.session_of("HOL-Library.Sorted_Sort") == "HOL-Library"
    assert se.session_of("Pure") == "Pure"
    assert se.session_of("Restriction_Spaces-HOLCF.Restriction_Spaces-HOLCF") \
        == "Restriction_Spaces-HOLCF"


# --- §6.2's id and §6.1's group --------------------------------------------

def test_the_document_id_is_a_uuid_and_deterministic():
    assert se.document_id(b"k") == se.document_id(b"k")
    assert len(se.document_id(b"k")) == 36
    assert se.document_id(b"k") != se.document_id(b"l")


def test_the_group_does_not_confuse_a_name_with_an_expression():
    """Length-prefixed, so a name that ends where an expression begins cannot hash
    like the pair with the boundary one character over."""
    assert se.group_of("ab", "c") != se.group_of("a", "bc")


def test_the_group_is_the_identity_of_a_name_and_an_expression():
    """D5 as reversed: two records of different kinds sharing both collapse into one
    card, which is only possible if they share a group."""
    assert se.group_of("f", "x = y") == se.group_of("f", "x = y")


# --- §8.3 -------------------------------------------------------------------

def test_display_cleaning_normalises_line_endings():
    assert se.clean_for_display("a\r\nb\rc") == "a\nb\nc"


# --- §6.3's separator -------------------------------------------------------

def test_a_separator_stands_between_theory_names_and_nowhere_else():
    """Without it `[HOL.List, Affine_Arithmetic.Foo]` answers to the sequence
    `List Affine_Arithmetic`, which is no theory's name."""
    tokens = se.theory_subtokens(["HOL.List", "Affine_Arithmetic.Foo"],
                                 lambda s: s.replace(".", " ").split())
    assert tokens == ["HOL", "List", se.THEORY_SEPARATOR, "Affine_Arithmetic", "Foo"]


def test_one_theory_name_gets_no_separator():
    assert se.theory_subtokens(["HOL.List"], lambda s: s.split(".")) == ["HOL", "List"]


def test_the_separator_is_something_the_tokenizer_cannot_emit():
    """The whole reason it is safe: no query can contain it, because §5.2 discards
    whitespace before token formation."""
    from Isabelle_Semantic_Embedding import isabelle_tokenizer
    asset = json.load(open(os.path.join(os.path.dirname(__file__), "site",
                                        "tokenizer", "asset.json"),
                           encoding="utf-8"))
    tokenize = isabelle_tokenizer.Tokenizer(asset)
    assert tokenize(se.THEORY_SEPARATOR) == []


# --- §8.2's namespace name --------------------------------------------------

def test_the_namespace_base_carries_the_release_and_the_snapshot():
    assert se.namespace_base("/x/Isabelle2025-2", "/y/afp-2026-05-13") \
        == "isasearch-2025-2-afp-2026-05-13"


def test_a_trailing_slash_does_not_change_the_namespace_base():
    assert se.namespace_base("/x/Isabelle2025-2/", "/y/afp-2026-05-13/") \
        == se.namespace_base("/x/Isabelle2025-2", "/y/afp-2026-05-13")


def test_the_first_generation_is_the_bare_base_and_the_next_ones_are_numbered(monkeypatch):
    """§8.2 writes every export into a namespace that does not yet exist, and nothing
    in the base moves when the corpus does, so the generation is what makes that
    true rather than merely intended."""
    existing = []
    monkeypatch.setattr(se, "list_namespaces", lambda p, **kw: list(existing))
    assert se.next_namespace("isasearch-x", region="r", key="k") == "isasearch-x"
    existing.append("isasearch-x")
    assert se.next_namespace("isasearch-x", region="r", key="k") == "isasearch-x-2"
    existing.append("isasearch-x-2")
    assert se.next_namespace("isasearch-x", region="r", key="k") == "isasearch-x-3"


def test_a_namespace_that_only_shares_the_prefix_does_not_spend_a_generation(monkeypatch):
    """The prefix filter is turbopuffer's, so it returns names the generation scheme
    knows nothing about; only the base itself and `base-<digits>` count."""
    monkeypatch.setattr(se, "list_namespaces",
                        lambda p, **kw: ["isasearch-x-scratch", "isasearch-xy"])
    assert se.next_namespace("isasearch-x", region="r", key="k") == "isasearch-x"


# --- D46's guard ------------------------------------------------------------

_ASSET = {"tokenizer_rule": 1, "symbol_files": [{"name": "etc/symbols", "sha256": "ab"}]}


def _committed(asset):
    from Isabelle_Semantic_Embedding import tokenizer_asset
    text = tokenizer_asset.serialize(asset)
    import hashlib
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_an_unchanged_asset_is_no_change():
    text, digest = _committed(_ASSET)
    assert se.asset_differences(text, _ASSET, digest) == []


def test_registering_a_component_is_a_loud_failure_and_not_a_new_namespace():
    """D46: the asset carries the export machine's whole symbol table, so an extra
    component moves the digest and therefore the namespace, though not one published
    document changes."""
    text, _ = _committed(_ASSET)
    changed = dict(_ASSET, symbol_files=_ASSET["symbol_files"]
                   + [{"name": "phi-system/symbols", "sha256": "cd"}])
    _, digest = _committed(changed)
    changes = se.asset_differences(text, changed, digest)
    assert len(changes) == 2 and "symbol files" in changes[0]


def test_a_rule_change_that_touches_no_table_is_still_seen():
    """The case `tokenizer_rule` exists for: §5.2's numeric class reuses the digit set
    the asset already ships, so without the version the digest would not move and
    'write into a new namespace' would become an upsert into the live one."""
    text, _ = _committed(_ASSET)
    bumped = dict(_ASSET, tokenizer_rule=2)
    _, digest = _committed(bumped)
    changes = se.asset_differences(text, bumped, digest)
    assert any("tokenizer_rule" in c for c in changes)


# --- §8.1 steps 2 to 5, on one record ---------------------------------------

class _Kind:
    label = "lemma"


def _record(**kw):
    fields = dict(kind=_Kind(), name="JoinTree.height", expr="0 < height ?t",
                  interpretation="A join tree.", position=("$AFP/Q/J.thy", 42, 1),
                  from_collection=None, theory_constituents=None)
    fields.update(kw)
    return SimpleNamespace(**fields)


def _vector():
    import numpy as np
    return np.zeros(4, dtype="float32")


def _split(s):
    return s.replace(".", " ").split()


def test_a_document_carries_exactly_the_fields_the_schema_declares():
    """Two halves of one statement: a field in one and not the other is either an
    attribute turbopuffer types by guesswork or a column nothing ever fills."""
    doc = se.build_document(b"k", _record(), ["HOL.List"], _vector(), _split, "")
    assert set(doc) == set(se.namespace_schema(4))


def test_the_position_is_a_symbolic_path_and_a_line():
    doc = se.build_document(b"k", _record(), ["HOL.List"], _vector(), _split, "")
    assert doc["position"] == "$AFP/Q/J.thy:42"


def test_a_record_without_a_position_says_so_with_an_empty_string():
    doc = se.build_document(b"k", _record(position=None), ["HOL.List"], _vector(),
                            _split, "")
    assert doc["position"] == ""


def test_the_source_link_is_carried_verbatim():
    """§17.6: resolution happened once, at map time (D49 ruling 2) — the export
    only carries the composed string; the empty string is D42's absent form.
    A document id the artefact does not name raises in `iter_documents`
    instead of shipping silently empty (the A3/B5 ruling)."""
    doc = se.build_document(b"k", _record(), ["HOL.List"], _vector(), _split,
                            "/source/HOL.List.html#L92")
    assert doc["source_link"] == "/source/HOL.List.html#L92"
    doc = se.build_document(b"k", _record(), ["HOL.List"], _vector(), _split, "")
    assert doc["source_link"] == ""


def test_a_collection_member_is_indexed_under_its_raw_name():
    """§8.1 step 5: `from_collection` is a display attribute, and the Worker emits one
    filter for the whole namespace, so a pasted `coll(_)` matches nothing — which the
    user ruled intended on 2026-08-19."""
    doc = se.build_document(b"k", _record(name="Foo.bar_1", from_collection="Foo.bars"),
                            ["HOL.List"], _vector(), _split, "")
    assert doc["name_subtokens"] == _split("Foo.bar_1")
    assert doc["from_collection"] == "Foo.bars"


def test_the_vector_goes_up_as_little_endian_float32():
    """turbopuffer's base64 encoding is always float32 on the wire, whatever the
    schema's element type."""
    import base64
    import numpy as np
    doc = se.build_document(b"k", _record(), ["HOL.List"],
                            np.array([1.0, 2.0, 3.0, 4.0], dtype="float32"), _split, "")
    back = np.frombuffer(base64.b64decode(doc["vector"]), dtype="<f4")
    assert list(back) == [1.0, 2.0, 3.0, 4.0]


# --- §7's theory resolution -------------------------------------------------

_XOR_KEY = bytes(16) + b"\x02" + bytes(15)          # 32 bytes, THEOREM tag
_NAMED_KEY = bytes(16) + b"\x01" + b"foo"


def test_a_theorem_alike_entity_is_filtered_by_its_constituents():
    rec = _record(theory_constituents=[("HOL.List", bytes(16)), ("Pure", bytes(16))])
    assert se.theories_of(_XOR_KEY, rec, {}) == ["HOL.List", "Pure"]


def test_a_theorem_alike_entity_with_no_constituents_stops_the_export():
    """Its key prefix is an XOR pseudo-theory (D13) and must never be looked up as a
    real theory, so there is nothing left to fall back on."""
    with pytest.raises(se.ExportError):
        se.theories_of(_XOR_KEY, _record(), {})


def test_a_name_addressed_entity_is_filtered_by_its_declaring_theory():
    assert se.theories_of(_NAMED_KEY, _record(), {bytes(16): "HOL.List"}) == ["HOL.List"]


def test_an_unresolvable_declaring_theory_stops_the_export():
    """D24's scope test cannot be applied to it, and guessing is what §7.1 forbids."""
    with pytest.raises(se.ExportError):
        se.theories_of(_NAMED_KEY, _record(), {})


# --- batching and the checkpoint -------------------------------------------

def _doc(n):
    return {"vector": "v", "interpretation": "i", "expr": "e", "n": n}


def test_batches_are_bounded_by_their_row_count():
    batches = list(se._batches(((bytes([i]), _doc(i)) for i in range(5)), 2, 1 << 30))
    assert [len(b) for b, _ in batches] == [2, 2, 1]
    assert [last for _, last in batches] == [bytes([1]), bytes([3]), bytes([4])]


def test_a_checkpoint_names_the_namespace_it_belongs_to(tmp_path):
    """Resuming into the wrong namespace would skip the first half of a fresh index
    and leave a hole nothing reports."""
    path = str(tmp_path / "cp.json")
    se._write_checkpoint(path, "isasearch-a-3", b"\x01\x02", 7, "dig")
    # An unfinished run resumes into its OWN generation, not a fresh one.
    assert se._read_checkpoint(path, "isasearch-a", "dig") \
        == ("isasearch-a-3", b"\x01\x02", 7)
    with pytest.raises(se.ExportError):
        se._read_checkpoint(path, "isasearch-b", "dig")


def test_a_checkpoint_pins_the_source_links_artefact(tmp_path):
    """B6: a resume under a re-generated artefact would leave every
    already-upserted row carrying the old artefact's links — refused."""
    path = str(tmp_path / "cp.json")
    se._write_checkpoint(path, "isasearch-a", b"\x01", 3, "old-digest")
    with pytest.raises(se.ExportError):
        se._read_checkpoint(path, "isasearch-a", "new-digest")
    # --no-source-links runs pin None, and mixing the two modes is refused too
    with pytest.raises(se.ExportError):
        se._read_checkpoint(path, "isasearch-a", None)


def test_no_checkpoint_means_start_from_the_beginning(tmp_path):
    assert se._read_checkpoint(str(tmp_path / "absent.json"), "isasearch-a",
                               None) is None


# --- §12.1's credential rule ------------------------------------------------

def test_no_key_is_read_from_anywhere_but_the_environment(monkeypatch):
    monkeypatch.delenv(se.API_KEY_ENV, raising=False)
    with pytest.raises(se.ExportError):
        se.api_key()


def test_batches_go_up_in_consecutive_groups():
    """A group is the unit the checkpoint advances by, so it must keep order and
    lose nothing: a resumed run re-sends at most the group that failed."""
    assert list(se._groups(range(7), 3)) == [[0, 1, 2], [3, 4, 5], [6]]
    assert list(se._groups([], 3)) == []


def test_a_group_checkpoints_on_its_last_batch_and_not_on_any_earlier_one():
    """Batches inside a group finish in any order, so no single one of them means
    'everything up to here has landed'."""
    batches = list(se._batches(((bytes([i]), _doc(i)) for i in range(9)), 1, 1 << 30))
    groups = list(se._groups(batches, 4))
    assert [g[-1][1] for g in groups] == [bytes([3]), bytes([7]), bytes([8])]
