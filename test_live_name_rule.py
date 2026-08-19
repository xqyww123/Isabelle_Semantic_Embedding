"""The two live-name substitution rules (DYNAMIC_MEMBER_NAMING_PLAN.md §2.1).

Pure functions over records -- no store is opened.  The caller table (which
site takes which function) lives in the plan; these tests pin the two
behaviours the table distinguishes, and the member condition's three limbs.
"""

from Isabelle_RPC_Host.universal_key import EntityKind
from Isabelle_Semantic_Embedding.semantics import (
    SemanticRecord, apply_live_name, apply_live_name_if_member, _carries_index)


def _member_rec() -> SemanticRecord:
    return SemanticRecord(EntityKind.THEOREM, "Thy.coll(3)", "a = b", "sem",
                          from_collection="Thy.coll")


def _declared_rec() -> SemanticRecord:
    return SemanticRecord(EntityKind.THEOREM, "Thy.foo", "a = b", "sem")


def test_apply_live_name_is_unconditional():
    assert apply_live_name(_declared_rec(), "Thy.coll(7)").name == "Thy.coll(7)"
    assert apply_live_name(_member_rec(), "Thy.coll(7)").name == "Thy.coll(7)"


def test_apply_live_name_keeps_the_record_without_a_live_name():
    rec = _declared_rec()
    assert apply_live_name(rec, None) is rec


def test_member_rule_substitutes_only_an_indexed_live_name():
    assert apply_live_name_if_member(_member_rec(), "Thy.coll(7)").name == "Thy.coll(7)"


def test_member_rule_rejects_an_index_free_live_name():
    """A collection holding exactly one member resolves from the bare `C`; the
    live name is then the bare collection name -- the one thing §2.3 rules out
    showing."""
    rec = _member_rec()
    assert apply_live_name_if_member(rec, "Thy.coll") is rec
    assert apply_live_name_if_member(rec, None) is rec


def test_member_rule_protects_records_with_real_names():
    """Without the from_collection condition, the §5-repaired records would be
    re-displayed as the manufactured coll(i)."""
    rec = _declared_rec()          # from_collection is None
    assert apply_live_name_if_member(rec, "Thy.coll(7)") is rec


def test_carries_index_tests_the_live_string_shape():
    assert _carries_index("Thy.coll(7)")
    assert _carries_index("disjoint_ℱ(12)")
    assert not _carries_index("Thy.coll")
    assert not _carries_index("Thy.coll(x)")
    assert not _carries_index("Thy.coll(7)x")
