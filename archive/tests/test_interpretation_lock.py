"""The interpretation lock (ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md §8.1,
D8, §15.8 "Run-scoped state", §13 step 7): one live interpretation run per
semantic database directory, tried once and never waited for, owned by the
RPC connection that acquired it and released when that connection closes;
while a run holds it, `current_run_state()` is that run's `RunState`.

The RPC shim `Semantic_Store.try_acquire_interpretation_lock` is driven with
a stub connection (an `on_close` list is all it touches); the real
`Isabelle_RPC_Host.rpc.Connection` is exercised for its `close()` contract.
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import time

import pytest
from filelock import FileLock

import Isabelle_Semantic_Embedding.semantic_interpretation as SI
from Isabelle_RPC_Host.rpc import Connection
from Isabelle_Semantic_Embedding.snapshot_sync import INTERPRETATION_LOCK_NAME


class _Connection:
    """What the lock touches on its connection."""

    def __init__(self):
        self.on_close = []

    def close(self):
        for release in self.on_close:
            release()


@pytest.fixture
def db_dir(tmp_path, monkeypatch):
    d = tmp_path / "db"          # not created: the acquire creates it
    monkeypatch.setenv("SEMANTIC_DB_DIR", str(d))
    monkeypatch.setattr(SI, "_locked_run", None)
    return d


def _acquire(conn) -> bool:
    """D8: tried once, never waited for -- a refusal comes back at once, and a
    refusal leaves the holder's run state exactly where it was (the state is
    published only after a successful acquire)."""
    held = SI._locked_run
    t0 = time.monotonic()
    got = asyncio.run(SI._try_acquire_interpretation_lock(None, conn))
    assert time.monotonic() - t0 < 0.5
    if not got:
        assert SI._locked_run is held
    return got


def test_two_instances_in_one_process_exclude_each_other_until_the_holder_closes(db_dir):
    a, b = _Connection(), _Connection()
    assert _acquire(a) is True
    assert os.path.isfile(db_dir / INTERPRETATION_LOCK_NAME)
    assert _acquire(b) is False and b.on_close == []      # nothing to release
    a.close()
    assert _acquire(b) is True
    b.close()


def test_the_lock_holder_s_run_state_is_the_current_one_until_release(db_dir):
    a = _Connection()
    fresh = SI.current_run_state()
    assert SI.current_run_state() is not fresh             # off the lock: fresh per call
    assert _acquire(a)
    run = SI.current_run_state()
    assert SI.current_run_state() is run                   # the holder's, every call
    a.close()
    assert SI.current_run_state() is not run
    assert SI._locked_run is None


def test_the_startup_check_s_flag_reaches_the_run_through_the_lock(db_dir, monkeypatch):
    """§15.8: the check (step 6) writes `current_run_state().prefilter_disabled`;
    with the lock held that is the run's own state, not a dropped fresh one."""
    for var in ("EMBEDDING_DRIVER", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL",
                "EMBEDDING_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    lock_conn = _Connection()
    assert _acquire(lock_conn)

    class _Check:
        class server:
            logger = logging.getLogger("test_interpretation_lock.stub")

        async def config_lookup(self, name, ctxt=None):
            return ""

        async def warning(self, msg):
            pass

    asyncio.run(SI._check_embedding_service(None, _Check()))   # type: ignore[arg-type]
    assert SI.current_run_state().prefilter_disabled is True
    lock_conn.close()
    assert SI.current_run_state().prefilter_disabled is False


def _hold_in_child(path: str, hold) -> None:
    lock = FileLock(path, timeout=0)
    lock.acquire()
    hold.send("held")
    hold.recv()                    # "release"
    lock.release()
    hold.send("released")


def _holder_process(path: str):
    """A child holding the FileLock at `path` until told to release; a daemon,
    so a failed assertion in the parent cannot leave it to block the exit."""
    parent, child = multiprocessing.Pipe()
    proc = multiprocessing.get_context("fork").Process(
        target=_hold_in_child, args=(path, child), daemon=True)
    proc.start()
    return parent, proc


def test_two_processes_on_one_directory_exclude_each_other(db_dir):
    db_dir.mkdir()
    path = str(db_dir / INTERPRETATION_LOCK_NAME)
    parent, proc = _holder_process(path)
    try:
        assert parent.recv() == "held"
        a = _Connection()
        assert _acquire(a) is False
        parent.send("release")
        assert parent.recv() == "released"
        assert _acquire(a) is True
        a.close()
    finally:
        proc.terminate()
        proc.join(5)


def test_a_dead_holder_leaves_no_stale_lock(db_dir):
    db_dir.mkdir()
    path = str(db_dir / INTERPRETATION_LOCK_NAME)
    parent, proc = _holder_process(path)
    assert parent.recv() == "held"
    proc.kill()
    proc.join(5)
    assert _acquire(_Connection()) is True


# --- Connection.close(): the on_close contract (Isabelle_RPC_Host.rpc) --------

class _Writer:
    def __init__(self):
        self.closed = 0

    def get_extra_info(self, name):
        return None

    def close(self):
        self.closed += 1


def _real_connection() -> tuple[Connection, _Writer]:
    class _Server:
        debugging = False
        logger = logging.getLogger("test_interpretation_lock.rpc")

    writer = _Writer()
    conn = Connection(None, writer, ("127.0.0.1", 0), _Server())   # type: ignore[arg-type]
    return conn, writer


def test_connection_close_runs_every_on_close_callback_once_then_closes_the_socket():
    conn, writer = _real_connection()
    ran = []
    conn.on_close.append(lambda: ran.append("a"))
    conn.on_close.append(lambda: 1 / 0)                    # a failing release does not stop the rest
    conn.on_close.append(lambda: ran.append("b"))
    conn.close()
    conn.close()                                            # __aexit__ after handle_client's finally
    assert ran == ["a", "b"] and writer.closed == 1


def test_connection_aexit_and_close_are_one_release():
    conn, writer = _real_connection()
    ran = []
    conn.on_close.append(lambda: ran.append(1))

    async def use():
        async with conn:
            pass
        conn.close()

    asyncio.run(use())
    assert ran == [1] and writer.closed == 1
