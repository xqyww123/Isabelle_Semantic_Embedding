"""A locale record that meets the locale digest with imports
(Tools/semantic_digest.ML, sem_locale) with an equal digest all the same: the
locale had an import when it was interpreted and has none now, and it states
assumptions of its own (or none, its parents asserting nothing either), so its
digest is again the one of the three-component payload the record was written
with.  The scan must still make it a seed, by its test on the dependency keys.
No Isabelle, no API.
Run with  python -m pytest contrib/Semantic_Embedding/tests/test_locale_digest.py
"""
import asyncio
import logging

import pytest

import Isabelle_Semantic_Embedding.semantic_interpretation as SI
import Isabelle_Semantic_Embedding.semantics as S
from Isabelle_RPC_Host.universal_key import EntityKind
from layered_db import cache, write_user  # noqa: F401

# Every test runs on an isolated store: the scan reads it, and refreshes statements.
pytestmark = pytest.mark.usefixtures("cache")

WIP = bytes.fromhex("b5" + "00" * 15)     # a WIP theory hash (byte 0's LSB set)
DIGEST = b"d" * 16


def _key(name: str) -> bytes:
    return WIP + bytes([int(EntityKind.LOCALE)]) + name.encode()


CHILD, PARENT = _key("Tst.child"), _key("Tst.parent")


class _HostConnection:
    """What interpret_file's dry path touches of a connection."""

    class server:
        logger = logging.getLogger("test_locale_digest")


def _seeds(entry_deps: 'list[bytes]') -> int:
    """How many seeds the scan counts for the locale `Tst.child`, stored with an
    interpretation, DIGEST and a dependency on its parent, and arriving with
    DIGEST and `entry_deps`."""
    write_user({CHILD: S.Semantic_DB._encode(S.SemanticRecord(
        EntityKind.LOCALE, "Tst.child", "locale child", "meaning",
        semantic_digest=DIGEST, deps=[PARENT], version=1, interpreted_at=1))})
    entry = SI.Entry(int(EntityKind.LOCALE), "Tst.child", "locale child", None, CHILD,
                     semantic_digest=DIGEST, deps=entry_deps)
    n = asyncio.run(SI.interpret_file(
        _HostConnection(), "/tmp/Tst.thy", "Draft.Tst", WIP, [entry],  # type: ignore[arg-type]
        dry_run=True))
    assert isinstance(n, int)
    return n


def test_a_locale_that_lost_its_import_is_a_seed_though_its_digest_is_equal():
    assert _seeds([]) == 1


def test_a_locale_with_equal_digest_and_equal_dependencies_is_served_from_the_store():
    assert _seeds([PARENT]) == 0
