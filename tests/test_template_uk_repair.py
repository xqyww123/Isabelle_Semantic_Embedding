"""The one-off repair of stored `template_uk` / `locale_uk` pointers
(repair_template_uk.py; ai-artifacts/TEMPLATE_UK_MIGRATION_PLAN.md §3.2, §3.3): E5's
rule by theory base name (E15) for both pointers (E16), its classes, the dry run, the
backup, the verification, the guard against a system layer, and vectors left alone.
A temporary DB without a system layer; no Isabelle, no API.
Run with  python -m pytest contrib/Semantic_Embedding/tests/test_template_uk_repair.py
"""
import json
import pathlib
import sys

import lmdb
import pytest

import Isabelle_Semantic_Embedding.semantic_embedding as SE
import Isabelle_Semantic_Embedding.semantics as S
import layered_db
from Isabelle_RPC_Host.universal_key import EntityKind
from layered_db import STORE, cache, mk_system, reset_singletons, state, write_user  # noqa: F401

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import repair_template_uk as R  # noqa: E402

# Theory A at three generations; theories X and C that never change; theory Y, at three
# generations, that no holder lists; two theories of base name T in two sessions.
A0, A1, A2 = (bytes.fromhex(b * 16) for b in ("22", "24", "26"))
X, C = bytes.fromhex("44" * 16), bytes.fromhex("66" * 16)
Y0, Y1, Y2 = (bytes.fromhex(b * 16) for b in ("50", "52", "54"))
T_S1, T_S2 = bytes.fromhex("30" * 16), bytes.fromhex("32" * 16)
# Every theorem also lists Pure, which never changes, as every real record does.
P0 = bytes.fromhex("10" * 16)
a1, a2, x, c = ("Tst.A", A1), ("Tst.A", A2), ("Tst.X", X), ("Tst.C", C)
t_s1, t_s2 = ("S1.T", T_S1), ("S2.T", T_S2)


def thm(hashes: list[bytes], suffix: bytes) -> bytes:
    return layered_db.thm([*hashes, P0], suffix)


def record(name: str, consts: 'list | None', template: 'bytes | None' = None,
           locale: 'bytes | None' = None, kind: EntityKind = EntityKind.THEOREM) -> bytes:
    return layered_db.record(name, None if consts is None else [*consts, ("Pure", P0)],
                             template, locale, kind, qualifier="q")


def loc(h: bytes, name: bytes) -> bytes:
    """A locale's key: its theory's hash, the tag, its name qualified by that theory's
    base name."""
    return h + bytes([int(EntityKind.LOCALE)]) + name


H1, T1 = thm([A1, X], b"h1"), thm([A1], b"t1")                # one candidate agrees
H2 = thm([A1], b"h2")                                        # two candidates agree
H3, T3 = thm([A1], b"h3"), thm([A2], b"t3")                   # its one candidate disagrees
H4 = thm([A1], b"h4")                                        # no candidate
HA, TA_OLD, TA = thm([A1], b"ha"), thm([A2], b"ta"), thm([A1], b"ta")  # (a)
HB, TB = thm([A1], b"hb"), thm([A1, X], b"tb")                # (b)
HC1, HC2 = thm([A1], b"hc1"), thm([A1], b"hc2")               # (c)
L1 = loc(A1, b"A.l1")
L2, L2b = loc(Y1, b"Y.l2"), loc(Y2, b"Y.l2")
HT, TT_OLD, TT = thm([A1], b"ht"), thm([A0], b"tt"), thm([A1], b"tt")  # a deleted target
HS = thm([A1], b"hs")                                        # its own only candidate
HH, TH = thm([T_S1], b"hh"), thm([T_S2], b"th")               # a homonymous session's candidate
HL, LT_S1, LT_S2 = thm([T_S1], b"hl"), loc(T_S1, b"T.lt"), loc(T_S2, b"T.lt")


def build(cache) -> None:
    write_user({
        T1: record("Tst.t1", [a1]),
        H1: record("H.h1", [a1, x], thm([A0], b"t1"), L1),
        thm([A1, X], b"t2"): record("Tst.t2", [a1, x]),
        thm([A1, C], b"t2"): record("Tst.t2", [a1, c]),
        H2: record("H.h2", [a1], thm([A0], b"t2")),
        T3: record("Tst.t3", [a2]),
        H3: record("H.h3", [a1], thm([A0], b"t3")),
        H4: record("H.h4", [a1], thm([A0], b"t4")),
        TA_OLD: record("Tst.ta", [a2]), TA: record("Tst.ta", [a1]),
        HA: record("H.ha", [a1], TA_OLD),
        TB: record("Tst.tb", [a1, x]), thm([A1, C], b"tb"): record("Tst.tb", [a1, c]),
        HB: record("H.hb", [a1], TB),
        L1: record("A.l1", None, kind=EntityKind.LOCALE),
        L2: record("Y.l2", None, kind=EntityKind.LOCALE),
        L2b: record("Y.l2", None, kind=EntityKind.LOCALE),
        HC1: record("H.hc1", [a1], thm([A0], b"t1"), loc(A0, b"A.l1")),
        HC2: record("H.hc2", [a1], None, loc(Y0, b"Y.l2")),
        TT_OLD: S.TOMBSTONE, TT: record("Tst.tt", [a1]),
        HT: record("H.ht", [a1], TT_OLD),
        HS: record("H.hs", [a1], thm([A0], b"hs")),
        TH: record("S2.th", [t_s2]),
        HH: record("S1.hh", [t_s1], thm([A0], b"th")),
        LT_S1: record("T.lt", None, kind=EntityKind.LOCALE),
        LT_S2: record("T.lt", None, kind=EntityKind.LOCALE),
        HL: record("S1.hl", [t_s1], None, LT_S2),
    })
    with SE._get_lmdb_env(str(cache / STORE)).begin(write=True) as txn:
        txn.put(H1, b"\x01\x02" * 64)


def run(tmp_path, *args: str) -> dict:
    """The script, as from the command line, in a process that has not opened the
    store (backup_store's precondition); its JSON report."""
    reset_singletons()
    report = tmp_path / "report.json"
    R.main([*args, "--report", str(report)])
    reset_singletons()
    return json.loads(report.read_text())


def provenance(key: bytes) -> 'S.Provenance | None':
    rec = S.Semantic_DB[key]
    assert rec is not None
    return rec.locale_provenance


def P(template: 'bytes | None' = None, locale: 'bytes | None' = None) -> S.Provenance:
    return S.Provenance(template, locale, "q")


@pytest.fixture
def repaired(cache, tmp_path):
    build(cache)
    return run(tmp_path)


def test_one_agreeing_candidate_taken_vectors_kept(cache, tmp_path):
    build(cache)
    vec = state(cache)["vectors"][H1]
    run(tmp_path)
    assert provenance(H1) == P(T1, L1)
    assert state(cache)["vectors"][H1] == vec


def test_two_agreeing_candidates_left(repaired):
    assert provenance(H2) == P(thm([A0], b"t2"))


def test_disagreeing_candidate_refused(repaired):
    assert provenance(H3) == P(thm([A0], b"t3"))


def test_no_candidate_left(repaired):
    assert provenance(H4) == P(thm([A0], b"t4"))


def test_a_resolving_target_that_disagrees_rewritten(repaired):
    assert provenance(HA) == P(TA)


def test_b_resolving_target_that_agrees_kept_despite_a_second_agreeing_candidate(repaired):
    assert provenance(HB) == P(TB)


def test_c_stale_locale_uk_rewritten_when_one_record_passes_with_the_template_uk(repaired):
    assert provenance(HC1) == P(T1, L1)
    assert provenance(HC2) == P(locale=loc(Y0, b"Y.l2"))


def test_deleted_target_names_no_record(repaired):
    assert provenance(HT) == P(TT)


def test_homonymous_session_candidate_refused(repaired):
    """E15: S2.T is not S1.T, though both are T and give one suffix."""
    assert provenance(HH) == P(thm([A0], b"th"))


def test_locale_of_a_homonymous_session_rewritten(repaired):
    """E16: the locale's theory, read off its key, is compared like a constituent."""
    assert provenance(HL) == P(locale=LT_S1)


def test_class_counts(cache, tmp_path):
    build(cache)
    report = run(tmp_path, "--dry-run")
    zeros = {f"{g}: {c}": 0 for g in R.GROUPS for c in (R.TAKEN, R.SEVERAL, R.REFUSED, R.NONE)}
    assert report["holders"] == 12
    assert report["template_uk"] == {
        **zeros, "absent": 2, "resolves, its target passes": 1,
        "names no record: taken": 4,
        "names no record: several pass": 1,
        "names no record: refused, a shared theory's hash differs": 2,
        "names no record: none passes": 1,
        "resolves, its target fails the check: taken": 1}
    assert report["locale_uk"] == {
        **zeros, "absent": 8, "resolves, its target passes": 1,
        "names no record: taken": 1,
        "names no record: several pass": 1,
        "resolves, its target fails the check: taken": 1}
    assert report["of the taken, the holder itself"] == 1
    assert report["writes"] == 6
    assert ["H.hc1", "Tst.t1"] in report["examples"]["template_uk"]["names no record: taken"]


def test_verification_fails_when_the_write_does_not_land(cache, tmp_path, monkeypatch):
    build(cache)
    monkeypatch.setattr(S.Semantic_DB, "backfill_field", lambda field, writes: (len(writes), 0))
    with pytest.raises(SystemExit, match="verification FAILED"):
        run(tmp_path)
    assert json.loads((tmp_path / "report.json").read_text())["write"] == {
        "hit": 6, "missing": 0, "read back differently": 6, "taken by a second plan": 6}


def test_dry_run_writes_nothing(cache, tmp_path):
    build(cache)
    before = state(cache)
    report = run(tmp_path, "--dry-run")
    assert report["backup"] is None and "write" not in report
    assert state(cache) == before
    assert not list(cache.glob("semantics.lmdb.bak-*"))


def test_backup_holds_the_store_before_the_run(cache, tmp_path):
    build(cache)
    before = state(cache)["records"]
    report = run(tmp_path)
    assert report["write"] == {"hit": 6, "missing": 0, "read back differently": 0,
                               "taken by a second plan": 0}
    backups = list(cache.glob("semantics.lmdb.bak-*"))
    assert len(backups) == 1 and report["backup"] == str(backups[0])
    env = lmdb.open(str(backups[0]), readonly=True, lock=False)
    with env.begin() as txn:
        assert {bytes(k): bytes(v) for k, v in txn.cursor()} == before
    env.close()


def test_second_run_takes_nothing(repaired, cache, tmp_path):
    after = state(cache)
    report = run(tmp_path)
    assert report["writes"] == 0
    assert state(cache) == after


def test_refused_with_a_system_layer(cache, tmp_path):
    build(cache)
    mk_system(cache)
    before = state(cache)
    with pytest.raises(SystemExit, match="a system layer is installed"):
        run(tmp_path)
    assert state(cache) == before
    assert not list(cache.glob("semantics.lmdb.bak-*"))
