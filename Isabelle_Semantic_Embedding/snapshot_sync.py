"""The snapshot artifact: system-DB discovery, the manual installer, the exporter.

The semantic database is layered (see SEMANTIC_DB_LAYERED_PLAN.md): a writable
user DB under ``semantic_DB_dir()`` and a read-only **system DB** delivered as
the ``isabelle-semantic-data`` conda data package.  This module owns everything
about that artifact:

  * **discovery** -- ``find_system_db`` / ``validated_system_db``: where the
    installed system DB is (conda payload, or a pulled copy) and whether its
    manifest passes the compatibility gates;
  * **installation** -- ``install_system_db`` (the ``isabelle-semantics pull``
    engine): resolve the latest package from the conda channel's repodata,
    download the ``.conda``, extract its payload, validate, and atomically swap
    it into ``<cache>/system/``.  Manual and explicit: there is NO automatic
    download anywhere (L19);
  * **export** -- the artifact producer, executed by CI (L18): rewrite the
    input DB into a publishable payload with tombstones dropped, a freshly
    built system experience index, and a stamped manifest, then run the gates.

One data source, one artifact (L7/L18): Hugging Face holds the dev-synced
working DB (``manage_data.py update``); the release workflow turns it into the
conda package on conda.qiyuan.me; conda users install/update it through the
solver and everyone else through ``isabelle-semantics pull``.

Failure semantics: everything here raises ``SnapshotError`` (``SnapshotBusy``
when another installer holds the lock); ``isabelle_semantics.py`` exits
non-zero on it.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, NamedTuple

import lmdb
import zstandard as zstd
from ._paths import semantic_DB_dir
from filelock import FileLock, Timeout as _LockTimeout

# The snapshot format.  Bump when the tarball layout or a stored record's shape
# changes, so an older client refuses a snapshot it would silently misread.
#
# "2": an EXPERIENCE's goal patterns moved out of `expr` (where they were JSON-packed)
# into the real `goal_patterns` field, 8th in the record tuple.  msgpack tuples are
# positional and length-tolerant, so a pre-"2" client does not crash on such a record --
# it takes vals[:7], drops the patterns, reads expr=None, and ends up with an experience
# that has NO goal patterns: a pattern-less document text, hit_rate 0 for every
# experience (so they all vanish from retrieval), and an _auto_embed that would overwrite
# the vector with that wrong text.  Silent, and it propagates if that DB is pushed back.
# The manifest check is the only thing that turns that silent misread into a refusal.
SCHEMA_VERSION = "2"
VECTOR_FORMAT = "q15"

MANIFEST_NAME = "MANIFEST.json"

# The conda channel that publishes the data package, and the package itself.
# The payload path inside the package follows the package name (L3), matching
# the `share/isabelle-semantic-embedding` convention.
CHANNEL_URL = "https://conda.qiyuan.me"
DATA_PACKAGE = "isabelle-semantic-data"
PAYLOAD_PREFIX = "share/isabelle-semantic-data/"


class SnapshotError(RuntimeError):
    """Anything that should stop a sync: misconfiguration, an incompatible
    snapshot, a busy database, a full disk."""


class SnapshotBusy(SnapshotError):
    """Raised when another process already holds the pull lock.  A subclass so the
    manual CLI's `except SnapshotError` still catches it, while the auto path can tell
    'someone else is downloading' apart from a genuine failure."""


def _log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# System DB discovery (the read-only layer under the user DB)
# ---------------------------------------------------------------------------

class SystemDB(NamedTuple):
    """The read-only system layer of the semantic database.

    ``source`` records the delivery channel of the single active system DB
    ("conda" | "pulled") -- display/guard information only; the read facade
    treats both identically.  Location is identity: no conda-meta
    interrogation for the DB itself."""
    path: str
    source: str


def find_system_db() -> 'SystemDB | None':
    """Discover the system DB.  Precedence, first hit wins (a pulled copy under
    a conda payload is completely invisible):

      1. ``sys.prefix/share/isabelle-semantic-data`` -- the conda data package
         payload -- only with a readable manifest;
      2. ``semantic_DB_dir()/system`` -- installed by ``isabelle-semantics pull``.

    Pure discovery: content validation (schema/vector-format manifest gate)
    happens in ``validated_system_db``."""
    import sys
    for path, source in (
        (os.path.join(sys.prefix, "share", "isabelle-semantic-data"), "conda"),
        (os.path.join(semantic_DB_dir(), "system"), "pulled"),
    ):
        if os.path.isfile(os.path.join(path, MANIFEST_NAME)):
            return SystemDB(path, source)
    return None


# Cached validation verdict: _UNSET (not probed yet), None (absent/invalid), or
# the SystemDB.  Process-wide, like the LMDB environments that layer over it.
_SYSTEM_DB_UNSET: Any = object()
_system_db_cache: Any = _SYSTEM_DB_UNSET


def validated_system_db() -> 'SystemDB | None':
    """The system DB the read facades layer under the user DB, or None.

    ``find_system_db`` plus the manifest gate (``_check_manifest``) and a check
    that ``semantics.lmdb`` is actually present.  An incompatible or unreadable
    system DB is treated as absent, with ONE loud warning per process -- never a
    crash loop.  The verdict is cached for the life of the process."""
    global _system_db_cache
    if _system_db_cache is _SYSTEM_DB_UNSET:
        _system_db_cache = _validate_system_db(find_system_db())
    return _system_db_cache


def _validate_system_db(sysdb: 'SystemDB | None') -> 'SystemDB | None':
    import sys
    if sysdb is None:
        return None
    try:
        with open(os.path.join(sysdb.path, MANIFEST_NAME), encoding="utf-8") as f:
            _check_manifest(json.load(f))
        if not os.path.isdir(os.path.join(sysdb.path, "semantics.lmdb")):
            raise SnapshotError("it has no semantics.lmdb")
    except Exception as e:
        print(f"[Semantic_Embedding] WARNING: ignoring the system DB at "
              f"{sysdb.path}: {e}", file=sys.stderr, flush=True)
        return None
    return sysdb


def manage_script() -> str:
    """What to tell a user to run, in a form they can actually paste.

    Installed (wheel or conda), the ``isabelle-semantics`` console script is on
    PATH and is the right thing to print.  In a source checkout there is no such
    script, so fall back to the absolute path of the module -- runnable as
    ``python <path>``.  The old code printed a bare "semantics_manage.py" when the
    file was not beside the package, which was never runnable: the module ships
    INSIDE the package now, so that branch could not have helped anyway.
    """
    exe = shutil.which("isabelle-semantics")
    if exe:
        return exe
    return str(pathlib.Path(__file__).resolve().parent / "isabelle_semantics.py")


# Bounded, because urllib has no default timeout at all, which would hang forever.
_HTTP_TIMEOUT = 15

# Cloudflare answers 403 to urllib's default `Python-urllib/3.x` User-Agent, and
# 200 to anything else -- including no User-Agent at all. Measured against this
# very domain; without this header every anonymous read fails.
_USER_AGENT = "Isabelle_Semantic_Embedding/snapshot_sync"


def _http(url: str, method: str):
    """Open `url`, or return None on 404.  Anonymous; no signing, no credentials."""
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": _USER_AGENT})
    try:
        return urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT)
    except urllib.error.HTTPError as e:
        e.close()
        if e.code == 404:
            return None
        raise SnapshotError(f"{method} {url} -> HTTP {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        raise SnapshotError(f"{method} {url} -> {e.reason}") from e


# ---------------------------------------------------------------------------
# tar.zst plumbing (the HF dev-sync tarball is exactly this format)
# ---------------------------------------------------------------------------

_ZSTD_LEVEL = 3   # zstd's own default, and what `tar --zstd` used before this


def _write_tar_zst(out_path: str, base_dir: str, arcnames: 'list[str]',
                   exclude: 'str | None' = None) -> None:
    """Stream `arcnames` (each relative to `base_dir`) into a tar, zstd-compressed
    with a frame checksum, at `out_path`.  Pure Python -- no `tar`/`zstd` binary,
    so it behaves the same on Linux, macOS and Windows.  `exclude`, if given, drops
    every entry with a path component of that name (like `tar --exclude=NAME`; a
    dir dropped this way is not recursed into).  The result is an ordinary
    `.tar.zst`, interchangeable with one made by `tar --zstd`.
    """
    def _filter(ti: tarfile.TarInfo) -> 'tarfile.TarInfo | None':
        return None if exclude and exclude in ti.name.split("/") else ti

    cctx = zstd.ZstdCompressor(level=_ZSTD_LEVEL, write_checksum=True)
    with open(out_path, "wb") as fh, cctx.stream_writer(fh) as z:
        with tarfile.open(mode="w|", fileobj=z) as tar:
            for name in arcnames:
                tar.add(os.path.join(base_dir, name), arcname=name, filter=_filter)


def _extract_tar_zst(tarball: str, dest: str) -> None:
    """Extract a `.tar.zst` (ours, or one made by `tar --zstd`) into `dest`.  The
    zstd frame checksum makes a corrupt or truncated archive raise here rather than
    reach the merge -- the guarantee the old `tar --zstd` extraction gave us.  The
    `data` filter rejects absolute paths and `..` escapes, since extraction runs
    before the manifest is even read."""
    dctx = zstd.ZstdDecompressor()
    with open(tarball, "rb") as fh, dctx.stream_reader(fh) as z:
        with tarfile.open(mode="r|", fileobj=z) as tar:
            tar.extractall(dest, filter="data")


# The install file lock (renamed from the old `.r2_pull.lock`), beside the
# stores it guards.
INSTALL_LOCK_NAME = ".install_system_db.lock"


@contextmanager
def _install_lock():
    """Serialise every system-DB install -- same process or not -- against each
    other, so two never swap into `<cache>/system` at once.

    `filelock` is a cross-platform advisory lock (fcntl on POSIX, msvcrt on
    Windows); like flock it is an OS-held lock the kernel drops when the holder
    closes the handle OR dies, so a crashed installer never leaves a stale lock --
    no TTL, no manual recovery.  `timeout=0` is non-blocking: a second installer
    fails fast with SnapshotBusy rather than queueing.  Even two coroutines in one
    process exclude each other (verified: the default FileLock is not re-entrant
    across instances)."""
    cache = semantic_DB_dir()
    os.makedirs(cache, exist_ok=True)
    lock = FileLock(os.path.join(cache, INSTALL_LOCK_NAME), timeout=0)
    try:
        lock.acquire()
    except _LockTimeout:
        raise SnapshotBusy(
            f"another process is already installing (holds {INSTALL_LOCK_NAME})")
    try:
        yield
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Snapshot introspection
# ---------------------------------------------------------------------------

def _store_dirs(root: str) -> list[str]:
    """Names of the LMDB stores in a snapshot (or in the live cache)."""
    if not os.path.isdir(root):
        return []
    return [e for e in sorted(os.listdir(root))
            if e.endswith(".lmdb") and os.path.isdir(os.path.join(root, e))
            and (e == "semantics.lmdb" or e.startswith("vector_"))]


def _model_of(store: str) -> 'str | None':
    """Canonical embedding-model name encoded in a vector store's directory name."""
    if not store.startswith("vector_"):
        return None
    from .semantic_embedding import unsanitize_model
    return unsanitize_model(store[len("vector_"):-len(".lmdb")])


def _local_dimension(model: str) -> 'int | None':
    """The dimension this machine expects for `model`, or None if unconfigured."""
    from .embedding_config import dimension
    try:
        return dimension(model)
    except KeyError:
        return None


def _human(n: float) -> str:
    return f"{n / 1024 ** 3:.2f} GiB" if n >= 1 << 30 else f"{n / 1024 ** 2:.1f} MiB"


def _progress(label: str, total: int,
              on_step: 'Callable[[int, int], None] | None' = None):
    """Per-chunk transfer accounting: the returned callback takes byte counts.

    `on_step(done, total)` fires on EVERY chunk -- it feeds a sampled display
    (the AoA heartbeat shows the latest value every 10s), where any throttling
    here would only leave stale numbers on screen.  The 5% throttle below is for
    the log lines alone, which append rather than overwrite."""
    state = {"done": 0, "pct": -5}

    def cb(n: int) -> None:
        state["done"] += n
        if on_step:
            on_step(state["done"], total)
        pct = int(100 * state["done"] / total) if total else 100
        if pct >= state["pct"] + 5:
            state["pct"] = pct - pct % 5
            _log(f"  {label}: {pct:3d}%  ({_human(state['done'])})")
    return cb


def _download(url: str, dest: str, expected: int,
              on_step: 'Callable[[int, int], None] | None' = None) -> None:
    """Fetch `url` to `dest` anonymously, with progress.

    One stream, deliberately.  The origin does serve `Range`, so ranged GETs in a
    thread pool look tempting; measured against it, they are slower (40 MB/s on
    one stream, 20 on four, 10 on eight — the link, not the client, is the
    bottleneck), and one eight-way run was answered with the *whole object* for
    some parts, having quietly ignored the Range header.  Do not "optimize" this.

    Throughput swings between roughly 3 and 40 MB/s minute to minute, so a slow
    pull is the network, not a regression: the snapshot is far past Cloudflare's
    512 MB cacheable-file limit, so every read goes to the origin, uncached.

    A short read means a truncated transfer, which `tar --zstd` would also catch
    (its XXH64 fails to extract) — but saying so here names the cause.
    """
    r = _http(url, "GET")
    if r is None:
        raise SnapshotError(f"GET {url} -> 404; the object vanished between HEAD and GET")
    cb = _progress("download", expected, on_step)
    got = 0
    with r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            got += len(chunk)
            cb(len(chunk))
    if expected and got != expected:
        raise SnapshotError(f"truncated download: got {got} of {expected} bytes")


# ---------------------------------------------------------------------------
# Compatibility gates.  All of them read the unpacked snapshot: what a snapshot
# says about itself is written by whoever pushed it, but its bytes are not.
# ---------------------------------------------------------------------------

def _check_manifest(manifest: dict) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotError(f"tarball manifest has schema_version "
                      f"{manifest.get('schema_version')!r}, expected {SCHEMA_VERSION!r}")
    if manifest.get("vector_format", VECTOR_FORMAT) != VECTOR_FORMAT:
        raise SnapshotError(f"tarball manifest declares vector_format "
                      f"{manifest['vector_format']!r}, expected {VECTOR_FORMAT!r}")


def _check_no_legacy(semantics_path: str) -> None:
    """Refuse a snapshot carrying pre-XOR records.

    A record with no constituent list cannot be attributed to a theory, so
    `remove` cannot delete it and `list` only warns about it.  Publishing one
    would ship a defect every consumer inherits.
    """
    from Isabelle_RPC_Host.universal_key import is_xor_prefixed_key
    from .semantics import record_constituent_hashes
    if not os.path.isdir(semantics_path):
        raise SnapshotError("the snapshot has no semantics.lmdb.")
    env = lmdb.open(semantics_path, readonly=True, lock=False)
    try:
        legacy = 0
        with env.begin() as txn:
            for key, val in txn.cursor():
                if is_xor_prefixed_key(bytes(key)) and record_constituent_hashes(bytes(val)) is None:
                    legacy += 1
    finally:
        env.close()
    if legacy:
        raise SnapshotError(
            f"the snapshot holds {legacy} legacy theorem/rule record(s) with "
            f"no constituent list. Purge them on the source machine "
            f"(migrate_xor_thm_keys.py) and sync again.")


def _check_vector_format(store_path: str, model: 'str | None') -> None:
    """Sample the store: every vector must be exactly D*2 bytes (Q1.15 int16).

    A D*4-byte value is a leftover float32 record; reinterpreting it as int16
    yields a plausible-looking but wrong vector, which is why this is fatal.
    """
    dim = _local_dimension(model) if model else None
    env = lmdb.open(store_path, readonly=True, lock=False)
    try:
        lengths, sampled = set(), 0
        with env.begin() as txn:
            for key, val in txn.cursor():
                if len(bytes(key)) == 16:
                    continue                       # theory embed-status, not a vector
                lengths.add(len(bytes(val)))
                sampled += 1
                if sampled >= 64:
                    break
    finally:
        env.close()
    if not sampled:
        return
    if len(lengths) > 1:
        raise SnapshotError(f"{os.path.basename(store_path)}: vectors have inconsistent "
                      f"lengths {sorted(lengths)}; the store is not uniformly encoded.")
    got = lengths.pop()
    if dim is None:
        _log(f"NOTE: {os.path.basename(store_path)}: {got}-byte vectors, "
             f"unverified (no local dimension for {model}).")
    elif got == dim * 4:
        raise SnapshotError(f"{os.path.basename(store_path)}: {got}-byte vectors are float32, "
                      f"not Q1.15. The pushing machine never ran the q15 migration.")
    elif got != dim * 2:
        raise SnapshotError(f"{os.path.basename(store_path)}: {got}-byte vectors, "
                      f"expected {dim * 2} for {model}.")


# ---------------------------------------------------------------------------
# The manual installer (the `isabelle-semantics pull` engine)
# ---------------------------------------------------------------------------

def version_of_created_at(created_at: str) -> str:
    """The data-package version derived from a manifest's ``created_at`` (L15):
    ``YYYY.MM.DD.HHMM``, UTC, zero-padded.  The SINGLE authority for the
    mapping -- the release derives the package version from it, and `pull`'s
    "Already current" comparison re-derives it from the installed manifest, so
    the two can never drift apart in format."""
    dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
    return f"{dt.year:04d}.{dt.month:02d}.{dt.day:02d}.{dt.hour:02d}{dt.minute:02d}"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


class ChannelEntry(NamedTuple):
    """One published build of the data package, as repodata describes it."""
    filename: str
    version: str
    build_number: int
    sha256: str
    size: int


def _resolve_latest(channel: str = CHANNEL_URL) -> ChannelEntry:
    """The newest `isabelle-semantic-data` build on the channel.

    Reads ``<channel>/noarch/repodata.json`` (the package is noarch); entries
    live under ``packages.conda`` (and legacy ``packages``).  Ordering is
    (version as an int tuple -- L15 guarantees pure numeric segments, matching
    conda's ``VersionOrder`` on such versions -- then ``build_number``)."""
    url = f"{channel.rstrip('/')}/noarch/repodata.json"
    r = _http(url, "GET")
    if r is None:
        raise SnapshotError(f"GET {url} -> 404; is {channel} a conda channel?")
    with r:
        data = json.load(r)
    entries: list[ChannelEntry] = []
    for section in ("packages.conda", "packages"):
        for filename, meta in (data.get(section) or {}).items():
            if meta.get("name") != DATA_PACKAGE:
                continue
            entries.append(ChannelEntry(
                filename=filename,
                version=str(meta.get("version") or ""),
                build_number=int(meta.get("build_number") or 0),
                sha256=str(meta.get("sha256") or ""),
                size=int(meta.get("size") or 0)))
    if not entries:
        raise SnapshotError(f"no {DATA_PACKAGE} package on {channel}")

    def order(e: ChannelEntry):
        try:
            return (tuple(int(s) for s in e.version.split(".")), e.build_number)
        except ValueError:
            # A non-numeric version violates L15; never pick it over a valid one.
            return ((), e.build_number)
    return max(entries, key=order)


def _extract_conda_payload(conda_path: str, dest: str) -> None:
    """Extract a `.conda`'s payload subtree into ``dest``.

    A `.conda` is a ZIP holding ``metadata.json``, an ``info-*.tar.zst``
    (package metadata -- ignored), and a ``pkg-*.tar.zst`` -- the payload tree
    rooted at ``share/isabelle-semantic-data/...``.  The pkg member is opened
    as a stream (zipfile -> zstandard -> tarfile ``r|``), members outside the
    payload prefix are skipped, the prefix is stripped, and tarfile's ``data``
    filter rejects absolute or ``..`` member names."""
    with zipfile.ZipFile(conda_path) as zf:
        pkg = [n for n in zf.namelist()
               if n.startswith("pkg-") and n.endswith(".tar.zst")]
        if len(pkg) != 1:
            raise SnapshotError(
                f"{os.path.basename(conda_path)} holds {len(pkg)} pkg-*.tar.zst "
                f"members, expected exactly 1; not a valid .conda")
        with zf.open(pkg[0]) as member:
            dctx = zstd.ZstdDecompressor()
            with dctx.stream_reader(member) as z:
                with tarfile.open(mode="r|", fileobj=z) as tar:
                    for ti in tar:                 # stream mode: in-order access
                        if not ti.name.startswith(PAYLOAD_PREFIX):
                            continue
                        ti.name = ti.name[len(PAYLOAD_PREFIX):]
                        if not ti.name:
                            continue
                        tar.extract(ti, dest, filter="data")


def _installed_snapshot(sysdir: str) -> 'tuple[str, int] | None':
    """(version, build) of the system DB at ``sysdir``, or None.

    The version is re-derived from the manifest's ``created_at`` (the L15
    clock); ``build`` is the field `pull` records at install time -- written
    and read ONLY by `pull`, never by ``find_system_db`` or the facade.
    Absent build = 0."""
    try:
        with open(os.path.join(sysdir, MANIFEST_NAME), encoding="utf-8") as f:
            manifest = json.load(f)
        return (version_of_created_at(manifest["created_at"]),
                int(manifest.get("build", 0)))
    except Exception:
        return None


_IN_USE_ERROR = (
    "the current system DB is in use by another process (a running RPC host or "
    "REPL server) — stop it and retry. The previous system DB is untouched.")


def install_system_db(*, force: bool = False, channel: str = CHANNEL_URL) -> None:
    """Resolve, download, validate and atomically install the latest
    `isabelle-semantic-data` package into ``<cache>/system/`` (L13).

    Refuses when a conda-managed system DB is active: the pulled copy would be
    shadowed by the conda payload (§2 precedence), so the download could never
    be read.  The guard reuses the reader's own discovery probe
    (``find_system_db``), so it cannot disagree with what the facade selects.

    No disk preflight: under the atomic swap an ENOSPC is a clean, retryable
    failure that never touches the live path.

    Crash states are self-healing: a crash leaves the live path holding the
    old DB, the new DB, or nothing -- "nothing" only between the two swap
    renames -- and the next install first heals leftovers: a ``system.old``
    with no ``system`` is restored (it is the sole surviving copy); one beside
    a ``system`` is discarded.  Half-extracted temp dirs are removed on the
    next attempt."""
    import sys
    cache = semantic_DB_dir()
    sysdir = os.path.join(cache, "system")
    old_dir = sysdir + ".old"

    found = find_system_db()
    if found is not None and found.source == "conda":
        raise SnapshotError(
            f"a conda-managed system DB is installed at\n  {found.path}\n"
            f"and would shadow the pulled copy. Update it with:\n"
            f"    conda install -c {channel} isabelle-semantic-data")
    if os.path.isdir(os.path.join(sys.prefix, "conda-meta")):
        _log("Note: this is a conda-managed environment; installing the "
             "isabelle-semantic-data package is the recommended path. A package "
             "install will take precedence over this pulled copy.")

    with _install_lock():
        # Heal a crashed previous install (see the docstring).
        if os.path.isdir(old_dir):
            if not os.path.isdir(sysdir):
                os.rename(old_dir, sysdir)
            else:
                shutil.rmtree(old_dir)
        for entry in os.listdir(cache):
            if entry.startswith(".system_install_"):
                shutil.rmtree(os.path.join(cache, entry), ignore_errors=True)

        _log(f"Resolving the latest isabelle-semantic-data from {channel} ...")
        latest = _resolve_latest(channel)
        if not force and _installed_snapshot(sysdir) == (latest.version,
                                                         latest.build_number):
            _log(f"Already current: installed snapshot {latest.version} "
                 f"matches the channel.")
            return
        _log(f"Found isabelle-semantic-data {latest.version} "
             f"({_human(latest.size)}).")

        tmp = tempfile.mkdtemp(prefix=".system_install_", dir=cache)
        try:
            try:
                conda_file = os.path.join(tmp, latest.filename)
                _download(f"{channel.rstrip('/')}/noarch/{latest.filename}",
                          conda_file, latest.size)
                if latest.sha256 and _sha256(conda_file) != latest.sha256:
                    raise SnapshotError(
                        f"{latest.filename}: sha256 mismatch against repodata; "
                        f"corrupted download or channel — retry.")
                _log("  extracting...")
                payload = os.path.join(tmp, "payload")
                os.makedirs(payload)
                _extract_conda_payload(conda_file, payload)
                os.remove(conda_file)
            except OSError as e:
                import errno
                if e.errno == errno.ENOSPC:
                    raise SnapshotError(
                        f"{e}. Free space and retry — the previous system DB "
                        f"(if any) is untouched.") from e
                raise

            manifest_path = os.path.join(payload, MANIFEST_NAME)
            if not os.path.isfile(manifest_path):
                raise SnapshotError(f"the package payload has no {MANIFEST_NAME}")
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            _check_manifest(manifest)
            if not os.path.isdir(os.path.join(payload, "semantics.lmdb")):
                raise SnapshotError("the package payload has no semantics.lmdb")
            # Record the installed build number (see _installed_snapshot).
            manifest["build"] = latest.build_number
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, sort_keys=True)

            _log("  installing...")
            try:
                if os.path.isdir(sysdir):
                    os.rename(sysdir, old_dir)      # swap rename 1 (out)
                os.rename(payload, sysdir)          # swap rename 2 (in)
            except PermissionError as e:
                # Windows: a live RPC host's open LMDB handles block the
                # rename-out; POSIX proceeds (the mmap pins the old inode).
                raise SnapshotError(_IN_USE_ERROR) from e
            shutil.rmtree(old_dir, ignore_errors=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # The system DB just changed under this process: drop the cached discovery
    # verdict so a later status()/facade probe in the SAME process sees the new
    # copy.  (Already-open LMDB environments still pin the old inode -- hence
    # the restart line below.)
    global _system_db_cache
    _system_db_cache = _SYSTEM_DB_UNSET

    # The system-upgrade purge (VECTOR_INVALIDATION_PLAN §7).  The conda package
    # gets this from its post-link hook; `pull` is the other way the payload can
    # be replaced, so it calls the same function inline.  A failure here must not
    # fail the install, which has already succeeded and is what the user asked
    # for -- the cost of skipping is stale cached vectors, and the command below
    # runs the purge again.
    from .semantics import purge_vectors_without_a_user_record
    try:
        n_purged = purge_vectors_without_a_user_record()
        if n_purged:
            _log(f"  dropped {n_purged} cached vector(s) that the previous "
                 f"system DB supplied the text for")
    except Exception as e:
        _log(f"  could not clean the vector cache: {e}\n"
             f"  The database itself was installed correctly.  Re-run with:\n"
             f"      isabelle-semantics post-install-system-db")

    n = (manifest.get("stores", {}).get("semantics.lmdb", {}) or {}).get("entries")
    records = f" ({n:,} records)" if isinstance(n, int) else ""
    _log(f"Installed isabelle-semantic-data {latest.version}{records}\n"
         f"to {sysdir}.\n"
         f"Restart any running RPC host / REPL server to pick it up.")


# ---------------------------------------------------------------------------
# export -- the artifact producer, executed by CI (L18)
# ---------------------------------------------------------------------------

_EXPORT_BATCH = 10_000     # keys per write transaction of the compacting rewrite


def export(outdir: str) -> dict:
    """Rewrite the layered store at ``semantic_DB_dir()`` into a publishable
    system-DB payload at ``outdir``; returns the stamped manifest.

    On the CI runner the input is the HF cache's user DB (single-layer, so the
    facade reads it straight); the five jobs (§5 of the plan):

      ① omit tombstoned keys everywhere -- records AND their vectors; the
        tombstones themselves never ship (``iter_items`` and the L23 vector
        resolution give this for free);
      ② rebuild the experience index over the OUTPUT records (the input's live
        index is NOT shipped);
      ③ stamp ``MANIFEST.json`` (``created_at`` = build time, the L15 clock;
        store stats);
      ④ compacting rewrite -- the key-by-key copy into fresh stores drops free
        pages as a side effect;
      ⑤ run the gates over the output.
    """
    import contextlib
    from .semantics import SEMANTICS_MAP_SIZE, Semantic_DB
    from .semantic_embedding import VECTOR_MAP_SIZE, Vector_Store
    from .experience_index import Experience_Index

    outdir = os.path.abspath(outdir)
    if os.path.isdir(outdir) and os.listdir(outdir):
        raise SnapshotError(f"{outdir} exists and is not empty")
    os.makedirs(outdir, exist_ok=True)
    cache = semantic_DB_dir()

    # ①/④ records: the layered visible view, batched into fresh (hence
    # compacted) stores.
    _log("  exporting records...")

    # ②' (CHECK_OUTDATE_PLAN §9, the export filter job): the payload contains
    # PERSISTENT data only.  Drops the 0xF0 global version counter (the
    # publishing machine's counter value is meaningless and harmful elsewhere)
    # and every WIP key -- machine-local working state whose incremental fields
    # carry this machine's counter domain.  Prefix-addressed keys go by the
    # key's WIP bit; XOR-prefixed keys (thm/rule/experience) go by their
    # constituent list, because the XORed bit is a PARITY that two WIP
    # constituents cancel; a legacy record with no constituent list falls back
    # to the bit.  Applied to every copy loop below -- records, vectors,
    # embed-status -- one missed loop would be a release leak.
    from Isabelle_RPC_Host.theory_hash import is_persistent as _hash_persistent
    from Isabelle_RPC_Host.universal_key import is_xor_prefixed_key
    from .semantics import record_constituent_hashes as _consts_of

    def _ships(key: bytes, val: bytes) -> bool:
        if len(key) < 16:
            return False                 # the 0xF0 global version counter
        if is_xor_prefixed_key(key):
            consts = _consts_of(val)
            if consts is None:
                return _hash_persistent(key)
            return all(_hash_persistent(h) for h in consts)
        return _hash_persistent(key)

    out_sem = lmdb.open(os.path.join(outdir, "semantics.lmdb"),
                        map_size=SEMANTICS_MAP_SIZE)
    n_records = 0
    n_wip_dropped = 0
    batch: list[tuple[bytes, bytes]] = []

    def _flush(env: lmdb.Environment) -> None:
        nonlocal batch
        if batch:
            with env.begin(write=True) as txn:
                for k, v in batch:
                    txn.put(k, v)
            batch = []

    for k, v in Semantic_DB.iter_items():
        if not _ships(k, v):
            n_wip_dropped += 1
            continue
        batch.append((k, v))
        n_records += 1
        if len(batch) >= _EXPORT_BATCH:
            _flush(out_sem)
    _flush(out_sem)
    if n_wip_dropped:
        _log(f"  dropped {n_wip_dropped} WIP/counter key(s) from the payload")

    # ② the system experience index of the payload, built over the OUTPUT.
    _log("  building the experience index...")
    out_idx = lmdb.open(os.path.join(outdir, "experience_index.lmdb"),
                        map_size=1 << 27)
    with out_sem.begin() as txn:
        n_exp = Experience_Index.rebuild(
            Semantic_DB._scan_experiences(txn), env=out_idx)
    _log(f"  {n_exp} experience(s) indexed")

    # ① vectors: every store visible in the layered world (user cache stores
    # plus any system stores), resolved per key by the L23 binding rule, so the
    # published text-vector pairing equals the local read view.  The 16-byte
    # embed-status keys ride along, user layer winning.
    sysdb = validated_system_db()
    store_names = {s for s in _store_dirs(cache) if s != "semantics.lmdb"}
    if sysdb is not None:
        store_names |= {s for s in _store_dirs(sysdb.path) if s != "semantics.lmdb"}
    stores_meta: dict[str, dict] = {}
    for store in sorted(store_names):
        _log(f"  exporting {store}...")
        shell = Vector_Store.__new__(Vector_Store)
        shell.path = os.path.join(cache, store)
        out_vec = lmdb.open(os.path.join(outdir, store), map_size=VECTOR_MAP_SIZE)
        n_vecs = 0
        with contextlib.ExitStack() as stack:
            get = shell._raw_getter(stack)
            for k, _v in Semantic_DB.iter_items():
                if len(k) == 16:
                    continue                        # thy status, not an entity
                if not _ships(k, _v):
                    continue                        # ②': persistent data only
                vec = get(k)
                if vec is not None:
                    batch.append((k, bytes(vec)))
                    n_vecs += 1
                    if len(batch) >= _EXPORT_BATCH:
                        _flush(out_vec)
            _flush(out_vec)
        # embed-status keys (16-byte), user wins over system.  The system store
        # goes through the guarded process-wide read-only open: _raw_getter
        # above has already opened this very path (py-lmdb refuses a second
        # open), and an unopenable store degrades instead of crashing export.
        status: dict[bytes, bytes] = {}
        from .semantic_embedding import _try_system_store_env
        sys_env = (_try_system_store_env(os.path.join(sysdb.path, store))
                   if sysdb is not None else None)
        if sys_env is not None:
            with sys_env.begin() as txn:
                for k, v in txn.cursor():
                    if len(bytes(k)) == 16 and _hash_persistent(bytes(k)):
                        status[bytes(k)] = bytes(v)     # ②': no WIP embed status
        if os.path.isdir(shell.path):
            with shell._env.begin() as txn:
                for k, v in txn.cursor():
                    if len(bytes(k)) == 16 and _hash_persistent(bytes(k)):
                        status[bytes(k)] = bytes(v)     # ②': no WIP embed status
        with out_vec.begin(write=True) as txn:
            for k, v in status.items():
                txn.put(k, v)
        model = _model_of(store)
        stores_meta[store] = {
            "entries": out_vec.stat()["entries"],
            **({"model": model, "dimension": _local_dimension(model)}
               if model else {})}
        out_vec.close()

    stores_meta["semantics.lmdb"] = {"entries": out_sem.stat()["entries"]}
    stores_meta["experience_index.lmdb"] = {"entries": out_idx.stat()["entries"]}
    out_sem.close()
    out_idx.close()
    for store, meta in stores_meta.items():
        meta["bytes"] = os.path.getsize(os.path.join(outdir, store, "data.mdb"))

    # ③ the manifest: created_at is THE version clock (L15).
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "vector_format": VECTOR_FORMAT,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stores": stores_meta,
    }
    with open(os.path.join(outdir, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    # ⑤ the gates, over what was actually written.
    _log("  running the gates...")
    _check_manifest(manifest)
    _check_no_legacy(os.path.join(outdir, "semantics.lmdb"))
    for store in sorted(store_names):
        _check_vector_format(os.path.join(outdir, store), _model_of(store))
    _log(f"Exported {n_records} record(s) to {outdir} "
         f"(version {version_of_created_at(manifest['created_at'])}).")
    return manifest


# ---------------------------------------------------------------------------
# status / emptiness
# ---------------------------------------------------------------------------

def status() -> None:
    """Show the two layers: the system DB (source, path, snapshot, records) and
    the user DB (records, tombstones).  Wording per §14 of the plan."""
    from .semantics import Semantic_DB, is_tombstone

    sysdb = validated_system_db()
    if sysdb is None:
        _log("system : (none — install with the isabelle-semantic-data package "
             "or `isabelle-semantics pull`)")
    else:
        _log(f"system : {sysdb.source:<7}{sysdb.path}")
        try:
            with open(os.path.join(sysdb.path, MANIFEST_NAME), encoding="utf-8") as f:
                manifest = json.load(f)
            created = datetime.strptime(manifest["created_at"], "%Y-%m-%dT%H:%M:%SZ")
            version = version_of_created_at(manifest["created_at"])
            n = (manifest.get("stores", {}).get("semantics.lmdb", {}) or {}).get("entries")
            records = f", {n:,} records" if isinstance(n, int) else ""
            _log(f"         snapshot {version} "
                 f"(created {created:%Y-%m-%d %H:%M} UTC){records}")
        except Exception as e:
            _log(f"         (unreadable manifest: {e})")

    cache = semantic_DB_dir()
    _log(f"user   : {cache}")
    if not os.path.isdir(os.path.join(cache, "semantics.lmdb")):
        _log("         (no user store yet)")
        return
    tombstones = 0
    entries = 0
    with Semantic_DB._ensure_env().begin() as txn:
        for _k, v in txn.cursor():
            entries += 1
            if is_tombstone(v):
                tombstones += 1
    _log(f"         {entries - tombstones:,} records, {tombstones:,} tombstones")


def semantic_db_is_empty() -> bool:
    """True when the LAYERED semantic database is empty: no valid system DB
    installed, and the user `semantics.lmdb` is absent or holds zero records.
    Cheap -- an O(1) LMDB stat, never a scan -- so the AoA hook can call it
    every `by aoa`."""
    if validated_system_db() is not None:
        return False
    if not os.path.isdir(os.path.join(semantic_DB_dir(), "semantics.lmdb")):
        return True
    from .semantics import Semantic_DB
    return Semantic_DB._ensure_env().stat()["entries"] == 0


def semantic_db_record_count() -> int:
    """How many records the LAYERED store holds (0 if absent).

    An UPPER BOUND, deliberately: a key present in both layers counts twice and
    tombstones count as entries.  Fine for the print-only callers; nothing may
    branch on the exact number."""
    n = 0
    if os.path.isdir(os.path.join(semantic_DB_dir(), "semantics.lmdb")):
        from .semantics import Semantic_DB
        n += Semantic_DB._ensure_env().stat()["entries"]
    from .semantics import Semantic_DB
    sys_env = Semantic_DB._ensure_system_env()
    if sys_env is not None:
        n += sys_env.stat()["entries"]
    return n
