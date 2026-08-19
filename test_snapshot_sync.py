"""Tests for the snapshot artifact: the manual installer (`isabelle-semantics
pull`), the exporter, the gates, and the layered emptiness probes.

Nothing here touches the network: the conda channel is a stubbed `_http`
serving an in-test repodata.json and a real `.conda` file built with
zipfile+zstandard+tarfile — the same libraries the extractor uses, so the
format round-trips end to end.  The install is where a bug is expensive: the
swap must never leave a partial store on the live path, and every crash state
must heal on the next attempt (§9.6 of SEMANTIC_DB_LAYERED_PLAN.md).

Store fixtures and the singleton-reset discipline are shared with
test_layered_db (same repo root), which owns the read-facade tests.
"""
from __future__ import annotations

import argparse
import errno
import io
import json
import os
import subprocess
import tarfile
import zipfile

import lmdb
import msgpack
import pytest
import zstandard as zstd

import Isabelle_Semantic_Embedding.isabelle_semantics as CLI
import Isabelle_Semantic_Embedding.semantics as S
from Isabelle_Semantic_Embedding import snapshot_sync
from Isabelle_Semantic_Embedding._user_config import env_bool
from Isabelle_RPC_Host.universal_key import xor_theory_prefix

from test_layered_db import (
    CONST, EXP, HA, HB, STORE, _basis, _key, _mk_system, _q15, _record,
    _reset_singletons, _user_raw, _write_user, cache)   # noqa: F401  (cache is a fixture)

CREATED_AT = "2026-07-22T14:30:00Z"
VERSION = "2026.07.22.1430"


# ---------------------------------------------------------------------------
# version derivation / plain helpers
# ---------------------------------------------------------------------------

def test_version_of_created_at_is_zero_padded_utc():
    assert snapshot_sync.version_of_created_at(CREATED_AT) == VERSION
    assert snapshot_sync.version_of_created_at("2026-01-02T03:04:00Z") == "2026.01.02.0304"


def test_env_bool_distinguishes_unset_from_empty():
    assert env_bool("_SNAP_TEST_ABSENT") is None     # fall through to the config
    os.environ["_SNAP_TEST_EMPTY"] = ""
    try:
        assert env_bool("_SNAP_TEST_EMPTY") is False  # an explicit "off"
    finally:
        del os.environ["_SNAP_TEST_EMPTY"]


# ---------------------------------------------------------------------------
# the gates
# ---------------------------------------------------------------------------

def test_a_manifest_from_a_future_client_is_refused():
    with pytest.raises(snapshot_sync.SnapshotError, match="schema_version"):
        snapshot_sync._check_manifest({"schema_version": "99"})
    with pytest.raises(snapshot_sync.SnapshotError, match="vector_format"):
        snapshot_sync._check_manifest({"schema_version": snapshot_sync.SCHEMA_VERSION,
                                       "vector_format": "float32"})
    snapshot_sync._check_manifest({"schema_version": snapshot_sync.SCHEMA_VERSION})


def test_a_corrupt_tar_zst_fails_to_extract(tmp_path):
    """The zstd frame carries an XXH64 content checksum (write_checksum=True), so
    a flipped byte fails to extract instead of yielding a silently corrupt tree."""
    payload = tmp_path / "d" / "blob"
    payload.parent.mkdir()
    payload.write_bytes(bytes(range(256)) * 4096)
    tar = tmp_path / "snap.tar.zst"
    snapshot_sync._write_tar_zst(str(tar), str(tmp_path), ["d"])

    raw = bytearray(tar.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    tar.write_bytes(raw)

    with pytest.raises(zstd.ZstdError):
        snapshot_sync._extract_tar_zst(str(tar), str(tmp_path / "out"))


def test_pack_and_extract_round_trip_excludes_and_interoperates_with_the_cli(tmp_path):
    """The pure-Python .tar.zst is byte-for-byte a normal one: `exclude` drops a
    named subtree, and the CLI `tar --zstd` can read what we wrote and vice versa
    (the HF dev-sync tarball is exactly this format)."""
    src = tmp_path / "src" / "sub"
    src.mkdir(parents=True)
    (tmp_path / "src" / "a.txt").write_text("alpha")
    (src / "b.txt").write_text("beta")
    (tmp_path / "src" / "embed_cache").mkdir()
    (tmp_path / "src" / "embed_cache" / "junk").write_text("drop me")

    tar = tmp_path / "s.tar.zst"
    snapshot_sync._write_tar_zst(str(tar), str(tmp_path), ["src"], exclude="embed_cache")

    out = tmp_path / "out"
    snapshot_sync._extract_tar_zst(str(tar), str(out))
    assert (out / "src" / "a.txt").read_text() == "alpha"
    assert (out / "src" / "sub" / "b.txt").read_text() == "beta"
    assert not (out / "src" / "embed_cache").exists(), "exclude did not drop the subtree"

    cli = tmp_path / "cli"
    cli.mkdir()
    rc = subprocess.run(["tar", "--zstd", "-xf", str(tar), "-C", str(cli)],
                        capture_output=True, text=True)
    assert rc.returncode == 0, f"CLI tar could not read our archive: {rc.stderr}"
    assert (cli / "src" / "a.txt").read_text() == "alpha"

    cli_tar = tmp_path / "cli.tar.zst"
    subprocess.run(["tar", "--zstd", "-cf", str(cli_tar), "-C", str(tmp_path), "src"],
                   check=True)
    from_cli = tmp_path / "from_cli"
    snapshot_sync._extract_tar_zst(str(cli_tar), str(from_cli))
    assert (from_cli / "src" / "a.txt").read_text() == "alpha"


# ---------------------------------------------------------------------------
# the install lock and the layered emptiness probes
# ---------------------------------------------------------------------------

def test_the_install_lock_serialises_and_raises_snapshotbusy(cache):
    with snapshot_sync._install_lock():
        with pytest.raises(snapshot_sync.SnapshotBusy):
            with snapshot_sync._install_lock():
                pass
    with snapshot_sync._install_lock():       # released after the block -> reacquirable
        pass


def test_snapshotbusy_is_a_snapshoterror_so_the_cli_still_catches_it():
    assert issubclass(snapshot_sync.SnapshotBusy, snapshot_sync.SnapshotError)


def test_layered_emptiness(cache):
    assert snapshot_sync.semantic_db_is_empty() is True
    assert snapshot_sync.semantic_db_record_count() == 0
    k = _key(HA, CONST, b"\x01")
    _mk_system(cache, records={k: _record(CONST, "k", "sys")})
    _reset_singletons()          # the pre-install probe cached "no system DB"
    assert snapshot_sync.semantic_db_is_empty() is False    # a system DB counts
    assert snapshot_sync.semantic_db_record_count() == 1


def test_user_records_alone_are_not_empty(cache):
    _write_user({_key(HA, CONST, b"\x01"): _record(CONST, "k", "usr")})
    assert snapshot_sync.semantic_db_is_empty() is False
    assert snapshot_sync.semantic_db_record_count() == 1


def test_progress_on_step_fires_every_chunk():
    steps = []
    cb = snapshot_sync._progress("download", 1000,
                                 on_step=lambda done, total: steps.append(done))
    cb(30)
    cb(30)   # within the same 5% log step -- the display still advances
    cb(30)
    assert steps == [30, 60, 90]


# ---------------------------------------------------------------------------
# §9.6  install_system_db / cmd_pull
# ---------------------------------------------------------------------------

def _mk_payload(tmp_path, created_at: str = CREATED_AT, n_records: int = 2):
    """A valid package payload tree: MANIFEST.json + semantics.lmdb."""
    payload = tmp_path / "payload_src"
    payload.mkdir(parents=True, exist_ok=True)
    env = lmdb.open(str(payload / "semantics.lmdb"), map_size=1 << 22)
    with env.begin(write=True) as txn:
        for i in range(n_records):
            txn.put(_key(HA, CONST, bytes([i + 1])), _record(CONST, f"c{i}", "sys"))
    env.close()
    (payload / snapshot_sync.MANIFEST_NAME).write_text(json.dumps({
        "schema_version": snapshot_sync.SCHEMA_VERSION,
        "vector_format": snapshot_sync.VECTOR_FORMAT,
        "created_at": created_at,
        "stores": {"semantics.lmdb": {"entries": n_records}},
    }))
    return payload


def _mk_conda(payload_dir, version: str = VERSION, build: int = 0) -> bytes:
    """A real `.conda`: ZIP(metadata.json, info-*.tar.zst, pkg-*.tar.zst), the
    pkg payload rooted at share/isabelle-semantic-data/."""
    stem = f"{snapshot_sync.DATA_PACKAGE}-{version}-{build}"
    tar_buf = io.BytesIO()
    with tarfile.open(mode="w", fileobj=tar_buf) as tar:
        tar.add(str(payload_dir), arcname="share/isabelle-semantic-data")
    cctx = zstd.ZstdCompressor()
    empty_tar = io.BytesIO()
    with tarfile.open(mode="w", fileobj=empty_tar):
        pass
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("metadata.json", "{}")
        zf.writestr(f"info-{stem}.tar.zst", cctx.compress(empty_tar.getvalue()))
        zf.writestr(f"pkg-{stem}.tar.zst", cctx.compress(tar_buf.getvalue()))
    return out.getvalue()


def _serve_channel(monkeypatch, condas: 'dict[tuple[str, int], bytes]'):
    """Stub `_http` as a channel publishing the given {(version, build): .conda}."""
    files: dict[str, bytes] = {}
    packages: dict[str, dict] = {}
    for (version, build), blob in condas.items():
        fn = f"{snapshot_sync.DATA_PACKAGE}-{version}-{build}.conda"
        files[fn] = blob
        packages[fn] = {
            "name": snapshot_sync.DATA_PACKAGE, "version": version,
            "build_number": build, "size": len(blob),
            "sha256": __import__("hashlib").sha256(blob).hexdigest(),
        }
    repodata = json.dumps({"packages.conda": packages}).encode()

    def fake_http(url, method):
        if url.endswith("/noarch/repodata.json"):
            return io.BytesIO(repodata)
        name = url.rsplit("/", 1)[1]
        return io.BytesIO(files[name]) if name in files else None
    monkeypatch.setattr(snapshot_sync, "_http", fake_http)
    return files


def _system_version(cache) -> 'tuple[str, int] | None':
    return snapshot_sync._installed_snapshot(str(cache / "system"))


def test_install_happy_path(cache, tmp_path, monkeypatch, capsys):
    payload = _mk_payload(tmp_path)
    _serve_channel(monkeypatch, {(VERSION, 0): _mk_conda(payload)})
    snapshot_sync.install_system_db()
    out = capsys.readouterr().out
    assert f"Found isabelle-semantic-data {VERSION}" in out
    assert "extracting..." in out and "installing..." in out
    assert f"Installed isabelle-semantic-data {VERSION} (2 records)" in out
    assert "Restart any running RPC host / REPL server" in out
    assert _system_version(cache) == (VERSION, 0)
    assert not (cache / "system.old").exists()
    assert not [e for e in os.listdir(cache) if e.startswith(".system_install_")]
    # and the facade actually reads it
    found = snapshot_sync.validated_system_db()
    assert found is not None and found.source == "pulled"
    assert S.Semantic_DB[_key(HA, CONST, b"\x01")] is not None


def test_resolution_orders_by_version_then_build(cache, tmp_path, monkeypatch):
    old = _mk_payload(tmp_path / "old", created_at="2026-07-20T10:00:00Z")
    new = _mk_payload(tmp_path / "new")
    _serve_channel(monkeypatch, {
        ("2026.07.20.1000", 5): _mk_conda(old, "2026.07.20.1000", 5),
        (VERSION, 0): _mk_conda(new),
        (VERSION, 1): _mk_conda(new, VERSION, 1),
    })
    snapshot_sync.install_system_db()
    assert _system_version(cache) == (VERSION, 1)   # highest (version, build)


def test_already_current_compares_version_and_build(cache, tmp_path, monkeypatch, capsys):
    payload = _mk_payload(tmp_path)
    _serve_channel(monkeypatch, {(VERSION, 0): _mk_conda(payload)})
    snapshot_sync.install_system_db()
    capsys.readouterr()
    snapshot_sync.install_system_db()               # same (version, build): short-circuit
    assert f"Already current: installed snapshot {VERSION} matches the channel." \
        in capsys.readouterr().out

    _serve_channel(monkeypatch, {(VERSION, 1): _mk_conda(payload, VERSION, 1)})
    snapshot_sync.install_system_db()               # same version, NEW build: reinstalls
    assert _system_version(cache) == (VERSION, 1)


def test_force_reinstalls_when_already_current(cache, tmp_path, monkeypatch, capsys):
    payload = _mk_payload(tmp_path)
    _serve_channel(monkeypatch, {(VERSION, 0): _mk_conda(payload)})
    snapshot_sync.install_system_db()
    capsys.readouterr()
    snapshot_sync.install_system_db(force=True)
    assert "Already current" not in capsys.readouterr().out


def test_sha256_mismatch_aborts_cleanly(cache, tmp_path, monkeypatch):
    payload = _mk_payload(tmp_path)
    files = _serve_channel(monkeypatch, {(VERSION, 0): _mk_conda(payload)})
    [fn] = files
    tampered = bytearray(files[fn])
    tampered[len(tampered) // 2] ^= 0xFF      # same length: past the size check
    files[fn] = bytes(tampered)
    with pytest.raises(snapshot_sync.SnapshotError, match="sha256 mismatch"):
        snapshot_sync.install_system_db()
    assert not (cache / "system").exists()          # live path never touched
    assert not [e for e in os.listdir(cache) if e.startswith(".system_install_")]


def test_invalid_payload_leaves_the_old_system_db(cache, tmp_path, monkeypatch):
    good = _mk_payload(tmp_path / "good")
    _serve_channel(monkeypatch, {(VERSION, 0): _mk_conda(good)})
    snapshot_sync.install_system_db()

    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / snapshot_sync.MANIFEST_NAME).write_text(json.dumps({"schema_version": "99"}))
    _serve_channel(monkeypatch, {("2026.07.23.0000", 0): _mk_conda(bad, "2026.07.23.0000")})
    with pytest.raises(snapshot_sync.SnapshotError, match="schema_version"):
        snapshot_sync.install_system_db()
    assert _system_version(cache) == (VERSION, 0)   # old DB fully intact


def test_crash_between_the_swap_renames_heals_on_retry(cache, tmp_path, monkeypatch):
    payload = _mk_payload(tmp_path)
    _serve_channel(monkeypatch, {(VERSION, 0): _mk_conda(payload)})
    snapshot_sync.install_system_db()

    newer = _mk_payload(tmp_path / "n2", created_at="2026-07-23T00:00:00Z")
    _serve_channel(monkeypatch, {("2026.07.23.0000", 0): _mk_conda(newer, "2026.07.23.0000")})
    real_rename = os.rename

    def crash_on_rename_in(src, dst):
        if dst.endswith(os.sep + "system") or dst.endswith("/system"):
            raise RuntimeError("simulated crash between the two swap renames")
        real_rename(src, dst)
    monkeypatch.setattr(os, "rename", crash_on_rename_in)
    with pytest.raises(RuntimeError, match="simulated crash"):
        snapshot_sync.install_system_db()
    # the "nothing" window: live path empty, system.old holds the sole copy
    assert not (cache / "system").exists()
    assert (cache / "system.old").exists()

    monkeypatch.setattr(os, "rename", real_rename)
    snapshot_sync.install_system_db()               # retry converges to the new DB
    assert _system_version(cache) == ("2026.07.23.0000", 0)
    assert not (cache / "system.old").exists()
    assert not [e for e in os.listdir(cache) if e.startswith(".system_install_")]


def test_leftover_system_old_beside_a_system_is_discarded(cache, tmp_path, monkeypatch, capsys):
    payload = _mk_payload(tmp_path)
    _serve_channel(monkeypatch, {(VERSION, 0): _mk_conda(payload)})
    snapshot_sync.install_system_db()
    (cache / "system.old").mkdir()                  # a crash after rename 2, before rmtree
    (cache / "system.old" / "junk").write_text("stale")
    capsys.readouterr()
    snapshot_sync.install_system_db()               # heals first, then "Already current"
    assert "Already current" in capsys.readouterr().out
    assert not (cache / "system.old").exists()
    assert _system_version(cache) == (VERSION, 0)


def test_a_live_handle_blocking_the_swap_reports_in_use(cache, tmp_path, monkeypatch):
    payload = _mk_payload(tmp_path)
    _serve_channel(monkeypatch, {(VERSION, 0): _mk_conda(payload)})
    snapshot_sync.install_system_db()
    newer = _mk_payload(tmp_path / "n2", created_at="2026-07-23T00:00:00Z")
    _serve_channel(monkeypatch, {("2026.07.23.0000", 0): _mk_conda(newer, "2026.07.23.0000")})

    real_rename = os.rename

    def windowsy_rename(src, dst):
        if src.endswith("system"):                  # the rename-out of the live dir
            raise PermissionError(13, "in use")
        real_rename(src, dst)
    monkeypatch.setattr(os, "rename", windowsy_rename)
    with pytest.raises(snapshot_sync.SnapshotError,
                       match="in use by another process"):
        snapshot_sync.install_system_db()
    assert _system_version(cache) == (VERSION, 0)   # old DB fully intact


def test_enospc_reports_retryable_and_leaves_the_live_path(cache, tmp_path, monkeypatch):
    payload = _mk_payload(tmp_path)
    _serve_channel(monkeypatch, {(VERSION, 0): _mk_conda(payload)})

    def full_disk(url, dest, expected, on_step=None):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(snapshot_sync, "_download", full_disk)
    with pytest.raises(snapshot_sync.SnapshotError, match="Free space and retry"):
        snapshot_sync.install_system_db()
    assert not (cache / "system").exists()


def test_conda_guard_refuses_when_the_payload_shadows(cache, tmp_path, monkeypatch):
    payload = tmp_path / "prefix" / "share" / "isabelle-semantic-data"
    payload.mkdir(parents=True)
    (payload / snapshot_sync.MANIFEST_NAME).write_text(json.dumps(
        {"schema_version": snapshot_sync.SCHEMA_VERSION,
         "vector_format": snapshot_sync.VECTOR_FORMAT}))
    with pytest.raises(snapshot_sync.SnapshotError,
                       match="conda-managed system DB"):
        snapshot_sync.install_system_db()


def test_conda_env_without_the_payload_proceeds_with_a_note(cache, tmp_path,
                                                            monkeypatch, capsys):
    os.makedirs(tmp_path / "prefix" / "conda-meta")
    payload = _mk_payload(tmp_path)
    _serve_channel(monkeypatch, {(VERSION, 0): _mk_conda(payload)})
    snapshot_sync.install_system_db()
    out = capsys.readouterr().out
    assert "this is a conda-managed environment" in out
    assert _system_version(cache) == (VERSION, 0)


def test_install_respects_the_lock(cache, tmp_path, monkeypatch):
    payload = _mk_payload(tmp_path)
    _serve_channel(monkeypatch, {(VERSION, 0): _mk_conda(payload)})
    from filelock import FileLock
    lock = FileLock(str(cache / snapshot_sync.INSTALL_LOCK_NAME), timeout=0)
    lock.acquire()
    try:
        with pytest.raises(snapshot_sync.SnapshotBusy):
            snapshot_sync.install_system_db()
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# §9.5  export
# ---------------------------------------------------------------------------

def test_export_drops_tombstones_and_builds_the_payload(cache, tmp_path):
    from Isabelle_Semantic_Embedding.semantic_embedding import _get_lmdb_env
    k_live = _key(HA, CONST, b"\x01")
    k_dead = _key(HA, CONST, b"\x02")
    uk = _key(xor_theory_prefix([HA]), EXP, b"\x03")
    _write_user({
        k_live: _record(CONST, "live", "keep me"),
        k_dead: b"",                                       # a tombstone
        uk: msgpack.packb((EXP, "e", None, "when", None, [("A", HA)], "how")),
        HA: msgpack.packb({b"finished": True}),
    })
    with _get_lmdb_env(str(cache / STORE)).begin(write=True) as txn:
        txn.put(k_live, _q15(_basis(0)))
        txn.put(k_dead, _q15(_basis(1)))                   # must NOT ship
        txn.put(HA, msgpack.packb({b"finished": True}))    # embed status rides along

    outdir = tmp_path / "out"
    manifest = snapshot_sync.export(str(outdir))

    env = lmdb.open(str(outdir / "semantics.lmdb"), readonly=True, lock=False)
    with env.begin() as txn:
        exported = {bytes(k): bytes(v) for k, v in txn.cursor()}
    env.close()
    assert set(exported) == {k_live, uk, HA}               # no k_dead, no tombstones
    assert all(v != b"" for v in exported.values())

    venv = lmdb.open(str(outdir / STORE), readonly=True, lock=False)
    with venv.begin() as txn:
        vec_keys = {bytes(k) for k, _ in txn.cursor()}
    venv.close()
    assert k_live in vec_keys and HA in vec_keys
    assert k_dead not in vec_keys                          # the tombstoned vector died

    ienv = lmdb.open(str(outdir / "experience_index.lmdb"), readonly=True, lock=False)
    with ienv.begin() as txn:
        bucket = msgpack.unpackb(txn.get(HA))
    ienv.close()
    assert [bytes(x) for x in bucket] == [uk]              # consistent with the output

    on_disk = json.loads((outdir / snapshot_sync.MANIFEST_NAME).read_text())
    assert on_disk["schema_version"] == snapshot_sync.SCHEMA_VERSION
    assert on_disk["vector_format"] == snapshot_sync.VECTOR_FORMAT
    assert on_disk["stores"]["semantics.lmdb"]["entries"] == 3
    assert manifest["created_at"] == on_disk["created_at"]

    # the export is itself installable: it validates as a system DB
    sysdir = cache / "system"
    os.rename(str(outdir), str(sysdir))
    _reset_singletons()
    found = snapshot_sync.validated_system_db()
    assert found is not None and found.path == str(sysdir)


def test_export_never_ships_a_vector_tombstone(cache, tmp_path):
    """The CI export runs SINGLE-LAYER, and its vector loop writes `if vec is not
    None`.  So if the read facade's single-layer shortcut ever stopped
    translating a `b""` tombstone to None, a 0-byte value would be published into
    the payload -- where every consumer would then read it as a present vector of
    the wrong length."""
    from Isabelle_Semantic_Embedding.semantic_embedding import _get_lmdb_env
    k = _key(HA, CONST, b"\x01")
    _write_user({k: _record(CONST, "live", "keep me"),
                 HA: msgpack.packb({b"finished": True})})
    with _get_lmdb_env(str(cache / STORE)).begin(write=True) as txn:
        txn.put(k, b"")                                    # a VECTOR tombstone

    snapshot_sync.export(str(tmp_path / "out"))

    venv = lmdb.open(str(tmp_path / "out" / STORE), readonly=True, lock=False)
    with venv.begin() as txn:
        shipped = {bytes(kk): bytes(vv) for kk, vv in txn.cursor()}
    venv.close()
    assert all(v != b"" for v in shipped.values())
    assert k not in shipped


def test_export_refuses_a_nonempty_outdir(cache, tmp_path):
    outdir = tmp_path / "out"
    outdir.mkdir()
    (outdir / "junk").write_text("x")
    with pytest.raises(snapshot_sync.SnapshotError, match="not empty"):
        snapshot_sync.export(str(outdir))


def test_export_publishes_the_layered_view(cache, tmp_path):
    """On a layered machine the export equals the read view: system records
    ship unless shadowed or tombstoned, with their L23-resolved vectors."""
    k_sys = _key(HA, CONST, b"\x01")
    k_masked = _key(HA, CONST, b"\x02")
    _mk_system(cache, records={k_sys: _record(CONST, "s", "sys"),
                               k_masked: _record(CONST, "m", "sys")},
               vectors={STORE: {k_sys: _q15(_basis(0))}})
    _write_user({k_masked: b""})                           # tombstone the system record

    outdir = tmp_path / "out"
    snapshot_sync.export(str(outdir))
    env = lmdb.open(str(outdir / "semantics.lmdb"), readonly=True, lock=False)
    with env.begin() as txn:
        keys = {bytes(k) for k, _ in txn.cursor()}
    env.close()
    assert k_sys in keys and k_masked not in keys
    venv = lmdb.open(str(outdir / STORE), readonly=True, lock=False)
    with venv.begin() as txn:
        assert txn.get(k_sys) == _q15(_basis(0))           # the system vector shipped
    venv.close()


# ---------------------------------------------------------------------------
# §9.7  remove (CLI): tombstoning, any residency
# ---------------------------------------------------------------------------

def _cli_paths(cache, monkeypatch):
    monkeypatch.setattr(CLI, "CACHE_DIR", str(cache))
    monkeypatch.setattr(CLI, "SEMANTICS_DB_PATH", str(cache / "semantics.lmdb"))
    # No registry seam needed: the layered theory-hash registry resolves
    # SEMANTIC_DB_DIR at open time, and the `cache` fixture already points it
    # at this test's fresh (hence registry-empty) dir.


def test_remove_tombstones_system_resident_records(cache, monkeypatch, capsys):
    k = _key(HA, CONST, b"\x01")
    _mk_system(cache, records={k: _record(CONST, "k", "sys"),
                               HA: msgpack.packb({b"finished": True})})
    _cli_paths(cache, monkeypatch)
    CLI.cmd_remove(argparse.Namespace(identifiers=[HA.hex()], force=True))
    out = capsys.readouterr().out
    assert "records, with their vectors and index entries" in out
    # A statement of fact about what is being removed, printed while the user is
    # still deciding.  "Tombstoned" and "the published snapshot" were both
    # implementation vocabulary that had leaked into user-facing text.
    assert "Some of these records come from the installed semantic database." in out
    assert "tombstoned" not in out and "snapshot" not in out
    assert _user_raw(k) == b""                             # the tombstone is on disk
    assert S.Semantic_DB[k] is None                        # absent through the facade
    assert S.Semantic_DB.is_thy_interpreted(HA) is False   # status tombstoned too


def test_remove_of_a_user_only_theory_prints_no_system_note(cache, monkeypatch, capsys):
    k = _key(HB, CONST, b"\x01")
    _write_user({k: _record(CONST, "k", "usr")})
    _reset_singletons()          # cmd_remove re-opens the path outside the singleton
    _cli_paths(cache, monkeypatch)
    CLI.cmd_remove(argparse.Namespace(identifiers=[HB.hex()], force=True))
    out = capsys.readouterr().out
    assert "records, with their vectors and index entries" in out
    assert "installed semantic database" not in out
    assert S.Semantic_DB[k] is None


def test_remove_drops_user_vectors_and_index_entries(cache, monkeypatch, capsys):
    from Isabelle_Semantic_Embedding.experience_index import Experience_Index
    from Isabelle_Semantic_Embedding.semantic_embedding import _get_lmdb_env
    uk = _key(xor_theory_prefix([HA]), EXP, b"\x01")
    _write_user({uk: msgpack.packb((EXP, "e", None, "when", None, [("A", HA)], "how"))})
    with _get_lmdb_env(str(cache / STORE)).begin(write=True) as txn:
        txn.put(uk, _q15(_basis(0)))
    Experience_Index.add(uk, [HA])
    _reset_singletons()
    _cli_paths(cache, monkeypatch)
    CLI.cmd_remove(argparse.Namespace(identifiers=[HA.hex()], force=True))
    capsys.readouterr()
    assert S.Semantic_DB[uk] is None
    from Isabelle_Semantic_Embedding.experience_index import Experience_Index as EI
    assert uk not in EI.all_keys()
    with _get_lmdb_env(str(cache / STORE)).begin() as txn:
        # Tombstoned, not really deleted: a real deletion would let a system
        # vector at this key show through for a record that no longer exists.
        assert txn.get(uk) == b""


# ---------------------------------------------------------------------------
# regressions from the 2026-07-26 adversarial code review
# ---------------------------------------------------------------------------

def test_fsck_is_clean_with_system_shipped_experiences(cache, monkeypatch, capsys):
    """A healthy layered install must pass fsck: the system index legitimately
    lists uks the user layer lacks (L17), so the user-vs-index comparison must
    scope BOTH sides to the user layer."""
    uk = _key(xor_theory_prefix([HA]), EXP, b"\x01")
    _mk_system(cache, records={uk: _record(EXP, "s", "when")}, index={HA: [uk]})
    _write_user({_key(HA, CONST, b"\x02"): _record(CONST, "c", "usr")})
    _cli_paths(cache, monkeypatch)
    CLI.cmd_fsck(argparse.Namespace(fix=False, system=False))   # must not exit 1
    out = capsys.readouterr().out
    assert "All checks passed" in out
    import re
    assert re.search(r"index key with no EXPERIENCE record\s+0\b", out)


def test_repair_xor_prefixes_tombstones_the_bad_key(cache):
    """Re-keying writes a TOMBSTONE at the bad key (L8), so a system copy at
    that key stays masked instead of resurfacing after the repair."""
    from Isabelle_RPC_Host.universal_key import xor_theory_prefix as xtp
    bad = _key(HB, EXP, b"\x01")                    # prefix disagrees with [HA]
    good = xtp([HA]) + bad[16:]
    rec = msgpack.packb((EXP, "e", None, "when", None, [("A", HA)], "how"))
    _mk_system(cache, records={bad: rec})           # the defective snapshot copy
    _write_user({bad: rec})                         # copied up (RMW etc.)
    cons = S.Semantic_DB.check_consistency()
    assert [b for b, _ in cons.xor_mismatches] == [bad]
    moved, conflicts = S.Semantic_DB.repair_xor_prefixes(cons.xor_mismatches)
    assert moved and not conflicts
    assert _user_raw(bad) == b""                    # tombstone, not a raw delete
    assert S.Semantic_DB[bad] is None               # the system copy stays masked
    assert S.Semantic_DB[good] is not None


def test_list_keeps_a_live_coconstituent_out_of_removed(cache, monkeypatch, capsys):
    """Removing theory A must not relabel live co-constituent B (which has a
    finished status and no direct-prefix entities) as `removed`."""
    thm = _key(xor_theory_prefix([HA, HB]), 2, b"\x01")     # THM mentions A and B
    _mk_system(cache, records={
        thm: msgpack.packb((2, "t", "P", "why", None, [("A", HA), ("B", HB)], None)),
        HA: msgpack.packb({b"finished": True}),
        HB: msgpack.packb({b"finished": True}),
    })
    _cli_paths(cache, monkeypatch)
    CLI.cmd_remove(argparse.Namespace(identifiers=[HA.hex()], force=True))
    capsys.readouterr()
    CLI.cmd_list(argparse.Namespace())
    out = capsys.readouterr().out
    [line_b] = [l for l in out.splitlines() if HB.hex() in l]
    assert "removed" not in line_b and "complete" in line_b
    [line_a] = [l for l in out.splitlines() if HA.hex() in l]
    assert "removed" in line_a
