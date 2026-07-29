"""Regression tests for the gates of ``Semantic_Vector_Store._auto_embed``
(CHECK_OUTDATE_PLAN §8, 段(1)) and the policy shell it delegates to.

The old gate-off warning branch (段(3)) is DELETED BY DESIGN: a gate the user
switched off must be silent -- the per-query nagging was the highest-frequency
annoyance the warning-discipline ruling removed.  What this file now guards:

  * gate off   -> no warning, no interpretation; already-ready keys still embed
  * field off  -> 段(1) skipped wholesale: not even the config gets read
  * field+gate -> the point fix delegates to update_interpretations with the
    missing entities' theory names -- the current theory NOT excluded (the old
    exclusion starved the entities the running proof needs most), skipped infra
    theories and unresolvable hashes dropped
  * the shell: small n interprets silently; big n with ask_user=False warns
    with the dry run's real entity count and does nothing
  * NEVER a theory mark (review R6): "fully embedded" may only be asserted by
    a path that covered a whole theory; _auto_embed sees only the query's
    keys, so every case asserts mark_thy_embedded was never called
"""
import asyncio

from Isabelle_RPC_Host.universal_key import EntityKind, xor_theory_prefix
import Isabelle_Semantic_Embedding.semantics as S


def _thy(n: int) -> bytes:
    return bytes([n]) + b"\x00" * 15


def _ent(th: bytes, name: str) -> bytes:
    return th + bytes([int(EntityKind.CONSTANT)]) + name.encode()


def _thm(ths: list) -> bytes:
    return xor_theory_prefix(ths) + bytes([int(EntityKind.THEOREM)]) + b"\x00" * 15


T_CUR, T_SKIP, T_UNK = _thy(1), _thy(2), _thy(3)
CUR_NAME = "Scratch.Current"


class _StubConn:
    """Minimal Connection: configurable gate, ML-Option-like callbacks,
    captured output.  ``dry`` is what the cone callback's dry run reports."""

    def __init__(self, names: dict, gate: bool, dry=((), 0)):
        self.names = names
        self.gate = gate
        self.dry = dry
        self.warnings: list = []
        self.tracings: list = []
        self.calls: list = []

    async def config_lookup(self, name, ctxt=None):
        assert name == "auto_interpret_for_embedding"
        self.calls.append(("config", name))
        return self.gate

    async def callback(self, name, arg):
        self.calls.append((name, arg))
        if name == "Theory_Hash.theory_name_of":
            return self.names.get(arg)      # None mirrors the ML NONE
        if name == "Theory_Hash.process_serial_of":
            return ("test-process", 1)
        if name == "Semantic_Store.interpret_theories":
            ctxt, names, force, dry_run, include_context = arg
            return [list(self.dry[0]), self.dry[1]] if dry_run else [[], -1]
        raise AssertionError(f"unexpected callback {name}")

    async def warning(self, msg):
        self.warnings.append(msg)

    async def tracing(self, msg):
        self.tracings.append(msg)

    async def dialogue(self, msg, options):
        raise AssertionError("_auto_embed must never ask at query time")


def _store(monkeypatch, names, gate, ready_key=None, field=True, dry=((), 0)):
    # monkeypatch, not assignment: a bare `S.Semantic_DB.get_many = ...` would
    # stay patched on the module singleton for every LATER test file in the
    # same pytest run (measured: it blinded test_incremental_criteria's scans).
    monkeypatch.setattr(S.Semantic_DB, "get_many", lambda ks: [
        ({"interpretation": "x"} if k == ready_key else None) for k in ks])
    monkeypatch.setattr(S, "document_text_of", lambda rec: "doc")
    store = object.__new__(S.Semantic_Vector_Store)
    store.connection = _StubConn(names, gate, dry)
    store.enable_interpret_in_auto_embed = field

    async def _embed(records, force=False):
        return 0
    store.embed_records = _embed
    # recording stub: _auto_embed must NEVER mark a theory (R6) -- every test
    # asserts this list stays empty
    store.marks = []
    store.mark_thy_embedded = \
        lambda th, tok=0, stamp=None: store.marks.append(th)
    return store


def _interpret_calls(conn):
    return [a for n, a in conn.calls if n == "Semantic_Store.interpret_theories"]


def test_gate_off_is_silent_and_still_embeds_ready_keys(monkeypatch):
    """The user switched the gate off: no warning, no live interpretation --
    and the already-interpreted key still gets its vector."""
    plain = [_thy(10 + i) for i in range(3)]
    names = {T_CUR: CUR_NAME, T_SKIP: "Pure", T_UNK: None}
    names.update({t: f"HOL.Thy{i}" for i, t in enumerate(plain)})
    ready_key = _ent(plain[0], "already_ready")
    missing = [_ent(t, f"c{i}") for i, t in enumerate(plain)] + [ready_key]
    store = _store(monkeypatch, names, gate=False, ready_key=ready_key)

    assert asyncio.run(store._auto_embed(missing)) == [ready_key]
    conn = store.connection
    assert conn.warnings == []                       # silence, by ruling
    # the shell was consulted (dry run) but its gate stopped everything:
    # only never a LIVE interpretation call
    assert all(a[3] for a in _interpret_calls(conn)), "no live run may happen"
    assert store.marks == []                         # R6: never a theory mark


def test_field_off_skips_paragraph_one_entirely(monkeypatch):
    """AoA's store: not even the config gets read, no callbacks fire."""
    missing = [_ent(_thy(10), "c0")]
    store = _store(monkeypatch, {_thy(10): "HOL.Thy0"}, gate=True, field=False)
    assert asyncio.run(store._auto_embed(missing)) == []
    assert store.connection.calls == []
    assert store.marks == []                         # R6: never a theory mark


def test_point_fix_passes_theory_names_including_the_current_theory(monkeypatch):
    """The name list is the point fix; the current theory is NOT excluded, the
    skipped/unresolvable ones are.  A small n runs silently (no warning)."""
    plain = _thy(10)
    names = {T_CUR: CUR_NAME, T_SKIP: "Pure", T_UNK: None, plain: "HOL.Thy0"}
    missing = [_ent(T_CUR, "cur"), _ent(T_SKIP, "skip"), _ent(T_UNK, "unk"),
               _ent(plain, "c0"), _thm([plain])]
    store = _store(monkeypatch, names, gate=True, dry=(("HOL.Thy0",), 2))

    asyncio.run(store._auto_embed(missing))
    conn = store.connection
    dry_calls = _interpret_calls(conn)
    assert dry_calls, "the point fix must reach the cone callback"
    ctxt, passed_names, force, dry_run, include_context = dry_calls[0]
    assert CUR_NAME in passed_names                  # the old exclusion is the fixed defect
    assert "Pure" not in passed_names and None not in passed_names
    assert include_context is False                  # point fix, not the startup sweep
    # n = 2 < threshold: interpreted silently, warning-free
    assert any(not a[3] for a in dry_calls), "small n must run live silently"
    assert conn.warnings == []
    assert store.marks == []                         # R6: never a theory mark


def test_shell_warns_with_the_real_count_when_nobody_was_asked(monkeypatch):
    """n >= threshold and ask_user=False: one warning quoting the dry run's n,
    and no live interpretation."""
    plain = _thy(10)
    names = {plain: "HOL.Thy0"}
    missing = [_ent(plain, "c0")]
    store = _store(monkeypatch, names, gate=True, dry=(("HOL.Thy0", "HOL.Thy1"), 150))

    asyncio.run(store._auto_embed(missing))
    conn = store.connection
    (warn,) = conn.warnings
    assert "150" in warn and "run_semantic_interpretation" in warn
    assert all(a[3] for a in _interpret_calls(conn)), "no live run may happen"
    assert store.marks == []                         # R6: never a theory mark
