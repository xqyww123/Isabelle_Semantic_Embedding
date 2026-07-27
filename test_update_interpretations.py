"""Unit tests for the interpretation policy shell ``update_interpretations``
(CHECK_OUTDATE_PLAN §8): gate, dry run, threshold, the three-option question
and the per-host don't-ask flag.  Driven with a stub Connection; the cone
callback is answered locally, so no Isabelle and no LLM.
"""
import asyncio

import Isabelle_Semantic_Embedding.semantics as S


class _Conn:
    def __init__(self, gate=True, dry=((), 0), answer="Yes"):
        self.gate = gate
        self.dry = dry
        self.answer = answer
        self.calls: list = []
        self.warnings: list = []
        self.tracings: list = []
        self.dialogues: list = []

    async def config_lookup(self, name, ctxt=None):
        self.calls.append(("config", name))
        return self.gate

    async def callback(self, name, arg):
        assert name == "Semantic_Store.interpret_theories"
        self.calls.append((name, arg))
        ctxt, names, force, dry_run, include_context = arg
        return [list(self.dry[0]), self.dry[1]] if dry_run else [[], -1]

    async def warning(self, msg):
        self.warnings.append(msg)

    async def tracing(self, msg):
        self.tracings.append(msg)

    async def dialogue(self, msg, options):
        self.dialogues.append((msg, options))
        return self.answer


def _live_calls(conn):
    return [a for n, a in conn.calls if n != "config" and not a[3]]


def _run(conn, **kw):
    asyncio.run(S.update_interpretations(conn, **kw))


def setup_function(_):
    S._dont_ask_this_session = False


def test_gate_off_returns_silently():
    conn = _Conn(gate=False)
    _run(conn)
    assert conn.calls == [("config", "auto_interpret_for_embedding")]
    assert conn.warnings == [] and conn.dialogues == []


def test_n_zero_does_nothing():
    conn = _Conn(dry=((), 0))
    _run(conn)
    assert _live_calls(conn) == [] and conn.warnings == []


def test_small_n_interprets_silently_with_context_root():
    conn = _Conn(dry=(("HOL.A",), 5))
    _run(conn, ask_user=True)
    (live,) = _live_calls(conn)
    assert live[4] is True          # include_context default: the startup sweep
    assert conn.dialogues == [] and conn.warnings == []


def test_big_n_asks_and_yes_runs():
    conn = _Conn(dry=(("HOL.A", "HOL.B"), 250), answer="Yes")
    _run(conn, ask_user=True)
    ((msg, options),) = conn.dialogues
    assert "250" in msg
    assert options == ["Yes", "No", "No, don't ask again in this session"]
    assert len(_live_calls(conn)) == 1


def test_big_n_no_declines_once():
    conn = _Conn(dry=(("HOL.A",), 250), answer="No")
    _run(conn, ask_user=True)
    assert _live_calls(conn) == []
    assert S._dont_ask_this_session is False        # plain No: ask again next time


def test_third_option_sets_the_host_flag_and_later_calls_stay_silent():
    conn = _Conn(dry=(("HOL.A",), 250), answer="No, don't ask again in this session")
    _run(conn, ask_user=True)
    assert _live_calls(conn) == []
    assert S._dont_ask_this_session is True
    # a later big-n startup check: no dialog, no warning, no run -- but the
    # check itself and the small-update path stay alive
    conn2 = _Conn(dry=(("HOL.A",), 250))
    _run(conn2, ask_user=True)
    assert conn2.dialogues == [] and conn2.warnings == [] and _live_calls(conn2) == []
    conn3 = _Conn(dry=(("HOL.A",), 3))
    _run(conn3, ask_user=True)
    assert len(_live_calls(conn3)) == 1             # the flag suppresses asking only


def test_not_asked_warns_with_the_real_count():
    conn = _Conn(dry=(("HOL.A",), 250))
    _run(conn, ask_user=False, theory_names=["HOL.A"], include_context=False)
    (warn,) = conn.warnings
    assert "250" in warn and "run_semantic_interpretation" in warn
    assert _live_calls(conn) == []
    # and the dry call carried the point-fix shape
    dry = [a for n, a in conn.calls if n != "config"][0]
    assert dry[1] == ["HOL.A"] and dry[4] is False
