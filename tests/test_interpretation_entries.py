"""The interpreter's addressing of its entries: the agent answers an entry by
(kind title, name), the same name under two kinds is two addresses, a duplicate
address is refused, and the prompt shows the address the agent echoes back.
Run with  python -m pytest contrib/Semantic_Embedding/tests/test_interpretation_entries.py
"""
import pytest

from Isabelle_RPC_Host.universal_key import EntityKind
from Isabelle_Semantic_Embedding import semantic_interpretation as si


def _entry(kind, name, prop=""):
    return si.Entry(kind=int(kind), name=name, prop_str=prop, position=("f.thy", 57, 0),
                    universal_key=bytes([int(kind)]) * 32)


def test_answers_are_routed_by_kind_title_and_name():
    entries = [_entry(EntityKind.THEOREM, "ordering"), _entry(EntityKind.THEOREM, "ordering(2)"),
               _entry(EntityKind.LOCALE, "ordering")]
    task = si.AgentTask(None, "f.thy", "T", b"", entries)
    assert task._label_to_idx[("lemma", "ordering")] == 0
    assert task._label_to_idx[("lemma", "ordering(2)")] == 1
    assert task._label_to_idx[("locale", "ordering")] == 2


def test_a_duplicate_address_is_refused():
    entries = [_entry(EntityKind.THEOREM, "ordering"), _entry(EntityKind.THEOREM, "ordering")]
    with pytest.raises(ValueError, match="duplicate interpretation label"):
        si.AgentTask(None, "f.thy", "T", b"", entries)


def test_the_prompt_shows_the_address():
    thm = _entry(EntityKind.THEOREM, "Orderings.order.antisym", prop="x ≤ y ⟹ y ≤ x ⟹ x = y")
    assert si._label_key(thm) == ("lemma", "Orderings.order.antisym")
    assert si._entry_head(thm) == "lemma Orderings.order.antisym: x ≤ y ⟹ y ≤ x ⟹ x = y"
    assert si._entry_head(_entry(EntityKind.LOCALE, "ordering")) == "locale ordering"
