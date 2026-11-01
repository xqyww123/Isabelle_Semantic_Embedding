"""A migration moves the stored `template_uk` / `locale_uk` pointers with the
records they name, warns once per migrated theory about re-keyed records whose
pointer names no record, and writes the theory-status record last
(ai-artifacts/TEMPLATE_UK_MIGRATION_PLAN.md §3.1, §3.3).  Every pin runs through
`_try_migrate` (the crash pin through the `is_interpreted` RPC) in a temporary DB
with a system layer; no Isabelle, no API.  A migration never targets a WIP hash (E13).
Run with  python -m pytest contrib/Semantic_Embedding/tests/test_template_uk_migration.py
"""
import asyncio
import re
import sys

import msgpack
import pytest

import Isabelle_Semantic_Embedding.semantic_embedding as SE
import Isabelle_Semantic_Embedding.semantics as S
from Isabelle_RPC_Host.universal_key import EntityKind, xor_theory_prefix
from layered_db import (  # noqa: F401
    STORE, cache, mk_system, record, reg, reset_singletons, state, thm, write_user,
    write_user_registry)

# Theory hashes; byte 0's LSB is the WIP bit.
A0, A1 = bytes.fromhex("22" * 16), bytes.fromhex("24" * 16)   # theory A, migrated
B0, B1 = bytes.fromhex("88" * 16), bytes.fromhex("8b" * 16)   # theory B, given a WIP hash
D0, D1 = bytes.fromhex("aa" * 16), bytes.fromhex("ac" * 16)   # theory D, only a locale moves
X, C = bytes.fromhex("44" * 16), bytes.fromhex("66" * 16)    # theories that do not move


def moved(key: bytes, hashes: list[bytes]) -> bytes:
    return xor_theory_prefix(hashes) + key[16:]


LOC = A0 + bytes([int(EntityKind.LOCALE)]) + b"Tst.loc"      # a locale of A
LOCD = D0 + bytes([int(EntityKind.LOCALE)]) + b"Tst.locd"    # a locale of D
NOLOC = X + bytes([int(EntityKind.LOCALE)]) + b"Tst.gone"    # no record
T = thm([A0], b"T")             # a template re-keyed with A
T3 = thm([X], b"T3")            # a template that does not move
GONE = thm([A0], b"gone")       # no record
SYS = thm([A0], b"sys")         # a template held only in the system layer
TOMB = thm([A0, X], b"tomb")    # a deleted template
H1 = thm([A0, X], b"h1")
H2 = thm([C], b"h2")
H3 = thm([A0], b"h3")
H4 = thm([A0], b"h4")
H4b = thm([A0, C], b"h4b")
H5 = thm([A0], b"h5")
H6 = thm([C], b"h6")
H7 = thm([C], b"h7")
HD = thm([C], b"hd")
TB = thm([B0], b"TB")
HB = thm([B0, X], b"hb")


def build(cache) -> None:
    a, b, x, c = ("Tst.A", A0), ("Tst.B", B0), ("Tst.X", X), ("Tst.C", C)
    mk_system(cache, records={SYS: record("Sys.t", [a])})
    write_user_registry({A0: reg("Tst.A", 100), A1: reg("Tst.A", 200),
                         B0: reg("Tst.B", 100), B1: reg("Tst.B", 200),
                         D0: reg("Tst.D", 100), D1: reg("Tst.D", 200)})
    write_user({
        LOC: record("Tst.loc", None, kind=EntityKind.LOCALE),
        T: record("TA.t", [a]), T3: record("TX.t3", [x]),
        H1: record("H1thy.h1", [a, x], T, LOC),
        H2: record("H2thy.h2", [c], T, LOC),
        H3: record("H3thy.h3", [a], T3),
        H4: record("H4thy.h4", [a], GONE, NOLOC),
        H4b: record("H4bthy.h4b", [a, c], T, NOLOC),
        H5: record("H5thy.h5", [a], SYS),
        H6: record("H6thy.h6", [c], GONE),
        TOMB: S.TOMBSTONE,
        H7: record("H7thy.h7", [c], TOMB),
        LOCD: record("Tst.locd", None, kind=EntityKind.LOCALE),
        HD: record("HDthy.hd", [c], None, LOCD),
        TB: record("TB.tb", [b]),
        HB: record("HBthy.hb", [b, x], TB),
    })
    for h in (A0, B0, D0):
        S.Semantic_DB.mark_interpreted(h)
    with SE._get_lmdb_env(str(cache / STORE)).begin(write=True) as txn:
        txn.put(H1, b"\x01\x02" * 64)
        txn.put(H2, b"\x03\x04" * 64)
        txn.put(A0, msgpack.packb({b"finished": True, b"total_tokens": 77}))  # type: ignore


def user(key: bytes) -> 'bytes | None':
    with S.Semantic_DB._ensure_env().begin() as txn:
        raw = txn.get(key)
    return bytes(raw) if raw is not None else None


def pointers(key: bytes) -> 'tuple[bytes | None, bytes | None]':
    raw = user(key)
    assert raw is not None
    prov = S.Semantic_DB._decode(raw).locale_provenance
    assert prov is not None
    return prov.template_uk, prov.locale_uk


def vector(cache, key: bytes) -> 'bytes | None':
    with SE._get_lmdb_env(str(cache / STORE)).begin() as txn:
        raw = txn.get(key)
    return bytes(raw) if raw is not None else None


WARNING = re.compile(r"Warning: (\d+) records migrated for (\S+) point to a template or locale "
                     r"that has no record \(their theories: (.*)\)")


def warned_theories(out: str) -> set[str]:
    return {t for m in WARNING.finditer(out) for t in m.group(3).split(", ")}


@pytest.fixture
def migrated_a(cache, capsys):
    """The world of §3.3 with theory A migrated; the captured output."""
    build(cache)
    assert S.Semantic_DB._try_migrate(A1)
    return capsys.readouterr().out


def test_h1_rekeyed_with_its_template_carries_both_new_pointers(cache, capsys):
    build(cache)
    old = user(H1)
    assert S.Semantic_DB._try_migrate(A1)
    assert pointers(moved(H1, [A1, X])) == (moved(T, [A1]), A1 + LOC[16:])
    assert user(H1) == old


def test_h2_not_rekeyed_rewritten_in_place_vector_kept(cache, capsys):
    build(cache)
    vec = vector(cache, H2)
    assert S.Semantic_DB._try_migrate(A1)
    assert pointers(H2) == (moved(T, [A1]), A1 + LOC[16:])
    assert vector(cache, H2) == vec


def test_h3_pointer_to_an_unmoved_target_kept(migrated_a):
    assert pointers(moved(H3, [A1])) == (T3, None)
    assert "H3thy" not in warned_theories(migrated_a)


def test_h4_counted_once_per_holder_in_one_line(migrated_a):
    assert pointers(moved(H4, [A1])) == (GONE, NOLOC)
    assert [line for line in migrated_a.splitlines() if line.startswith("Warning")] == [
        "Warning: 2 records migrated for Tst.A point to a template or locale that has "
        "no record (their theories: H4bthy, H4thy)"]


def test_h4_list_shows_ten_theories_then_the_rest_counted(cache, capsys):
    """E12: past ten theories the list stops and says how many more."""
    build(cache)
    write_user({thm([A0], b"z%02d" % i): record(f"Z{i:02d}thy.z", [("Tst.A", A0)], GONE)
                 for i in range(10)})
    assert S.Semantic_DB._try_migrate(A1)
    assert [line for line in capsys.readouterr().out.splitlines()
            if line.startswith("Warning")] == [
        "Warning: 12 records migrated for Tst.A point to a template or locale that has no "
        "record (their theories: H4bthy, H4thy, Z00thy, Z01thy, Z02thy, Z03thy, Z04thy, "
        "Z05thy, Z06thy, Z07thy and 2 more)"]


def test_h5_target_only_in_the_system_layer_neither_moved_nor_counted(migrated_a):
    assert pointers(moved(H5, [A1])) == (SYS, None)
    assert "H5thy" not in warned_theories(migrated_a)


def test_h6_not_rekeyed_dangling_pointer_not_counted(cache, capsys):
    """H6 names no record, H7 a deleted one: neither moves nor is counted."""
    build(cache)
    old6, old7 = user(H6), user(H7)
    assert S.Semantic_DB._try_migrate(A1)
    assert (user(H6), user(H7)) == (old6, old7)
    assert not {"H6thy", "H7thy"} & warned_theories(capsys.readouterr().out)


def test_embed_status_record_copied_with_its_tokens(cache, capsys):
    build(cache)
    assert S.Semantic_DB._try_migrate(A1)
    assert vector(cache, A1) == vector(cache, A0)
    assert msgpack.unpackb(vector(cache, A1))[b"total_tokens"] == 77


def test_wip_target_refused_and_nothing_written(cache, capsys):
    """E13: a WIP new hash is not a migration target."""
    build(cache)
    before = state(cache)
    assert not S.Semantic_DB._try_migrate(B1)
    assert state(cache) == before
    assert capsys.readouterr().out == ""


def test_theory_d_only_an_in_place_rewrite(cache, capsys):
    """No record of D is re-keyed; HD's locale_uk is rewritten in place all the same."""
    build(cache)
    assert S.Semantic_DB._try_migrate(D1)
    assert pointers(HD) == (None, D1 + LOCD[16:])
    out = capsys.readouterr().out
    assert "Migrated" in out and "Warning" not in out


def test_crash_after_the_rewrites_is_retried_to_the_same_state(cache, tmp_path, monkeypatch,
                                                               capsys):
    """A fault after `_migrate_constituent_records`' write transaction commits and
    before its vector copies; the retry is the one `is_interpreted` makes."""
    monkeypatch.setattr(S, "migrate_on_hash_change", True)
    build(cache)
    real = S._iter_vector_store_envs
    fired = []

    def faulty():
        if not fired and sys._getframe(1).f_code.co_name == "_migrate_constituent_records":
            fired.append(True)
            raise RuntimeError("injected fault")
        return real()

    monkeypatch.setattr(S, "_iter_vector_store_envs", faulty)
    with pytest.raises(RuntimeError, match="injected fault"):
        S.Semantic_DB._try_migrate(A1)
    assert user(moved(H1, [A1, X])) is not None       # the rewrites committed,
    assert vector(cache, moved(H1, [A1, X])) is None  # the vectors not yet copied,
    assert not S.Semantic_DB.is_thy_interpreted(A1)   # the status not yet written
    # the RPC's body; it never reads its connection
    assert asyncio.run(S._is_interpreted((A1, None, None), None))  # type: ignore
    crashed = state(cache)

    reset_singletons()
    clean = tmp_path / "clean"
    clean.mkdir()
    monkeypatch.setenv("SEMANTIC_DB_DIR", str(clean))
    build(clean)
    assert S.Semantic_DB._try_migrate(A1)
    assert crashed == state(clean)
