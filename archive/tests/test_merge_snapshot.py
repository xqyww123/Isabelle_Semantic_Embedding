"""Tests for merge_snapshot.py's theory-hash registry branch: the merge rule of
THEORY_HASH_REGISTRY_PLAN.md §14.6, all five branches, plus the properties the
plan requires of it -- idempotent, undo-recorded, never deleting.

The planner works on plain LMDB directories, so these tests build tiny stores
directly and never touch the package singletons.
"""
from __future__ import annotations

import lmdb
import msgpack

import merge_snapshot as MS

# Persistent keys (LSB of byte 0 clear) and one WIP key (LSB set).
PA = bytes.fromhex("22" * 16)
PB = bytes.fromhex("44" * 16)
PC = bytes.fromhex("66" * 16)
PD = bytes.fromhex("88" * 16)
WIP = bytes([PA[0] | 1]) + PA[1:]


def _reg(name: str, ts: int) -> bytes:
    return msgpack.packb([name, ts])


def _mk(path, entries: dict[bytes, bytes]) -> str:
    env = lmdb.open(str(path), map_size=1 << 22)
    with env.begin(write=True) as txn:
        for k, v in entries.items():
            txn.put(k, v)
    env.close()
    return str(path)


def _dump(path) -> dict[bytes, bytes]:
    env = lmdb.open(str(path), readonly=True, lock=False)
    with env.begin() as txn:
        out = {bytes(k): bytes(v) for k, v in txn.cursor()}
    env.close()
    return out


def test_merge_rule_all_five_branches(tmp_path):
    incoming = _mk(tmp_path / "inc", {
        WIP: _reg("Wip.W", 999),          # 1: WIP never crosses a machine
        PA: _reg("New.A", 100),           # 2: new key -> put
        PB: _reg("Same.B", 200),          # 3: same name, newer ts -> put
        PC: _reg("Same.C", 100),          # 4: same name, older ts -> no-op
        PD: _reg("Other.D", 999),         # 5: two names on one key -> sentinel
    })
    local = _mk(tmp_path / "loc", {
        PB: _reg("Same.B", 100),
        PC: _reg("Same.C", 200),
        PD: _reg("Local.D", 100),
    })

    writes, conflicts, stats = MS.plan_registry(incoming, local)

    assert dict(writes) == {PA: _reg("New.A", 100), PB: _reg("Same.B", 200)}
    assert conflicts == [(PD, "Local.D", "Other.D")]
    assert stats == dict(identical_or_older=1, added=1, refreshed=1,
                         wip_skipped=1)

    MS.apply_writes(local, writes, "registry")
    after = _dump(local)
    assert after[PD] == _reg("Local.D", 100)   # the sentinel kept the local value
    assert WIP not in after
    assert set(after) == {PA, PB, PC, PD}      # never deletes


def test_merge_rule_is_idempotent(tmp_path):
    incoming = _mk(tmp_path / "inc", {PA: _reg("A", 100), PB: _reg("B", 200)})
    local = _mk(tmp_path / "loc", {PB: _reg("B", 100)})

    writes, _, _ = MS.plan_registry(incoming, local)
    MS.apply_writes(local, writes, "registry")

    again, conflicts, _ = MS.plan_registry(incoming, local)
    assert again == [] and conflicts == []     # a second run plans zero writes


def test_merge_rule_undo_restores_the_pre_merge_state(tmp_path):
    incoming = _mk(tmp_path / "inc", {PA: _reg("A", 100), PB: _reg("B", 200)})
    local = _mk(tmp_path / "loc", {PB: _reg("B", 100)})
    before = _dump(local)

    writes, _, _ = MS.plan_registry(incoming, local)
    undo = {local: MS.capture_undo(local, writes)}
    MS.apply_writes(local, writes, "registry")
    assert _dump(local) != before

    import pickle
    undo_file = tmp_path / "undo.pkl"
    undo_file.write_bytes(pickle.dumps(undo, protocol=4))
    MS.restore(str(undo_file))
    assert _dump(local) == before              # PA (absent before) deleted again


def test_merge_into_a_missing_local_store(tmp_path):
    """§14.7's case on a machine whose post-move registry does not exist yet:
    an absent local store reads as empty, and applying creates it."""
    incoming = _mk(tmp_path / "inc", {PA: _reg("A", 100), WIP: _reg("W", 1)})
    local = str(tmp_path / "loc")              # never created

    writes, conflicts, stats = MS.plan_registry(incoming, local)
    assert dict(writes) == {PA: _reg("A", 100)} and not conflicts
    assert stats["wip_skipped"] == 1
    assert MS.capture_undo(local, writes) == [(PA, None)]

    MS.apply_writes(local, writes, "registry")
    assert _dump(local) == {PA: _reg("A", 100)}


def test_merge_rule_incoming_wins_over_a_local_tombstone(tmp_path):
    """As in plan_semantics: an incoming published entry overwrites a local
    tombstone rather than crashing the decoder or keeping the deletion."""
    incoming = _mk(tmp_path / "inc", {PA: _reg("A", 100)})
    local = _mk(tmp_path / "loc", {PA: b""})

    writes, conflicts, _ = MS.plan_registry(incoming, local)
    assert dict(writes) == {PA: _reg("A", 100)} and not conflicts
