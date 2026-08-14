#!/usr/bin/env python3
"""Join the repaired-key entity dump onto the semantic store.

BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md Part B, steps B.5a / B.6 / B.6a / B.7.
Read that plan before changing anything here; every rule below is stated there
and several of them are counter-intuitive on purpose.

WHAT THIS IS FOR
----------------
``Universal_Key.compute_constituents`` used to resolve a constant's defining
theory through a process-global, first-writer-wins memo keyed on the theory's
BASE name, so when two theories share a base name (``HOL.List`` and
``Zip_Benchmarks.List``) the winner depended on load order.  A theorem-alike
universal key is ``XOR(constituent theory hashes) ++ kind tag ++ thm128[0:15]``,
so the damage landed in the 16-byte prefix and in the stored constituent list --
and nowhere else.  The English ``interpretation`` on a record was never wrong.

Part A fixed the computation.  ``Semantic_Store.dump_entities`` then re-enumerated
the whole theory cone with REPAIRED keys into ``semantics.rekey-dump.lmdb``.  This
script is the join: it decides, for every new key, which old record's
interpretation it inherits, and writes a new store and a new vector store into a
staging directory.  It does not promote them; §B.9 does that, after the gates.

THE UNIT IS THE TAIL
--------------------
``tail = key[16:]`` -- the kind byte plus the content payload.  The fix does not
move it, so it is the only thing that identifies "the same fact" across the
repair.  Everything in phase 2 is decided per tail, with both sides in hand,
because the decisive ambiguity is invisible from one side alone.

Two populations stay outside the tail machinery: name-addressed keys, whose tail
is the kind byte plus the entity NAME, so a tail match across theories would be a
match on a name -- the very inference this migration exists to remove (§B.6a) --
and EXPERIENCE records, which §B.10's own pass owns and which this script does not
write at all.

NO ISABELLE, NO REPL, NO RPC HOST
---------------------------------
Every input is already on disk.  That property is worth keeping: the step that
needed Isabelle was the dump, and it has run.  Inputs are opened
``readonly=True, lock=False`` -- the dump is held read-write by a live RPC host,
and ``lock=False`` is what makes reading it safe -- and never through
``Semantic_DB``, whose ``_get_raw``/``iter_items`` are layered over a system DB and
would copy system-resident records into the new user layer (§B.5).

Scaffolding for one migration; delete with the rest of Part B (see the plan's
"To delete when Part B completes").
"""

import argparse
import collections
import json
import os
import sys
import time
from typing import Any, NamedTuple

import lmdb
import msgpack

HERE = os.path.dirname(os.path.abspath(__file__))
MLML = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
# `xor_theory_prefix` is imported from the live implementation, not reimplemented:
# §B.7 gate 8 is only meaningful if the check and the running Isabelle agree.
sys.path.insert(0, os.environ.get("ISABELLE_RPC_PATH",
                                  os.path.join(MLML, "contrib", "Isabelle_RPC")))

from Isabelle_Semantic_Embedding.semantics import (      # noqa: E402
    SEMANTICS_MAP_SIZE, _Semantic_DB, is_tombstone)
from Isabelle_Semantic_Embedding.semantic_embedding import VECTOR_MAP_SIZE  # noqa: E402

Record = _Semantic_DB.Record
decode = _Semantic_DB._decode
encode = _Semantic_DB._encode

# ---------------------------------------------------------------------------
# Key shapes
# ---------------------------------------------------------------------------

# Theorem-alike: THEOREM, INTRODUCTION_RULE, ELIMINATION_RULE, INDUCTION_RULE,
# CASE_SPLIT_RULE.  Written out rather than taken from `is_xor_prefixed_key`,
# which also admits EXPERIENCE (0x08) and must not be used here (§B.6).
THM_TAGS = frozenset({0x02, 0x12, 0x22, 0x32, 0x42})
NAME_ADDRESSED_TAGS = frozenset({0x01, 0x03, 0x04, 0x05, 0x06, 0x07})
EXPERIENCE_TAG = 0x08
COUNTER_KEY = b"\xf0"

# Dump record layout, as rekey_dump.py writes it.
D_NAME, D_KIND, D_POS, D_CONSTS, D_PROP, D_THEORY = 0, 1, 2, 3, 4, 5
# Store record layout (positional tail-append; see _Semantic_DB._decode).
F_KIND, F_NAME, F_EXPR, F_INTERP, F_CONSTS, F_POSITION = 0, 1, 2, 3, 5, 12


def is_thm_alike(key: bytes) -> bool:
    return len(key) == 32 and key[16] in THM_TAGS


def is_name_addressed(key: bytes) -> bool:
    return len(key) > 16 and key[16] in NAME_ADDRESSED_TAGS


def is_wip(key: bytes) -> bool:
    """WIP theory hashes have bit 0 of byte 0 set.  For an XOR prefix it is the
    OR of the constituents', so this is "any constituent theory is WIP"."""
    return bool(key[0] & 1)


def dec(v: Any) -> Any:
    return v.decode() if isinstance(v, bytes) else v


# ---------------------------------------------------------------------------
# §B.7's constants
# ---------------------------------------------------------------------------
#
# A gate is a comparison against a number fixed BEFORE the run.  A constant left
# None here has not been fixed yet: the gate then reports its value and does not
# fail, and `--dry-run` is how the number is obtained in the first place.  Filling
# one in is a deliberate act -- never paste in whatever the last run printed
# without checking it against the plan.
GATES: dict[str, 'int | None'] = {
    "dump_theories": 10570,          # §B.7 gate 1
    "theory_keys_shared": 10550,     # gate 2
    "entity_records": None,          # gate 3 (†, moved by B.6's rewrite)
    "theory_status_records": 11417,  # gate 3 / gate 6
    "pruned_keys": None,             # gate 4 (†)
    "fill_sources": None,            # gate 5 (†)
    "fanout_copies": None,           # gate 5 (†)
    "wip_theory_status": 867,        # gate 7
    "prefix_checked": None,          # gate 8 (†)
    "position_none": None,           # gate 9 (†)
    "zero_length_values": 0,         # gate 10
    "vectors_without_record": 693,   # gate 11
    "experience_records": 6768,      # gate 12 -- §B.10's pass, not this one
    "gap_keys": None,                # gate 13 (†)
}


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------

class OldDetail(NamedTuple):
    """What a contested tail needs to know about one old record.

    Digests, not text: §B.5a's memory budget.  A key-only reconstruction of
    phases 1 and 2 peaked at 3.6 GiB RSS against 16.2 GiB available on the box
    that runs this, so the corpus must not become Python objects.  Values are
    re-read from LMDB when they are written."""
    name: str
    position: 'tuple[str, int, int] | None'


class DumpDetail(NamedTuple):
    name: str
    position: 'tuple[str, int, int] | None'
    theory: str


class Tables:
    """Phase 1: both sides of every tail, and nothing else.

    Two passes over the dump and one over the store, in two stages.  Stage A
    builds only the tail -> keys maps, which is all Case A needs and Case A is
    the overwhelming majority; stage B re-reads values for the contested tails
    only.  Holding names and positions for all 1.3 M records instead would cost
    several GiB for a decision that ~36 k tails actually make."""

    def __init__(self, dump_path: str, store_path: str):
        self.dump_path = dump_path
        self.store_path = store_path

        # --- stage A: keys only ---
        self.dump_tails: dict[bytes, list[bytes]] = collections.defaultdict(list)
        self.dump_multi: set[bytes] = set()          # keys carrying >1 dump record
        self.dump_named: set[bytes] = set()          # name-addressed dump keys
        self.dump_theory_keys: set[bytes] = set()    # 16-byte theory-completion keys
        self.dump_theory_names: dict[str, bytes] = {}   # long name -> theory key
        self.dump_records_total = 0
        self.dump_other: list[bytes] = []            # unknown tags, never dropped silently

        self.store_tails: dict[bytes, list[bytes]] = collections.defaultdict(list)
        self.store_named: dict[bytes, list[bytes]] = collections.defaultdict(list)
        self.store_named_keys: set[bytes] = set()
        self.store_short: set[bytes] = set()         # theory-status keys and the counter
        self.store_wip_entities = 0
        self.store_experiences = 0
        self.store_other: list[bytes] = []

        # --- stage B: details, contested tails only ---
        self.old_detail: dict[bytes, OldDetail] = {}
        self.dump_detail: dict[bytes, list[DumpDetail]] = {}

    # -- stage A ------------------------------------------------------------

    def scan_dump(self) -> None:
        env = lmdb.open(self.dump_path, readonly=True, lock=False)
        try:
            with env.begin() as txn:
                for k, v in txn.cursor():
                    k = bytes(k)
                    if len(k) <= 16:
                        self.dump_theory_keys.add(k)
                        rec = msgpack.unpackb(bytes(v))
                        self.dump_theory_names[dec(rec[0])] = k
                        continue
                    recs = msgpack.unpackb(bytes(v))
                    self.dump_records_total += len(recs)
                    if len(recs) > 1:
                        self.dump_multi.add(k)
                    if is_thm_alike(k):
                        self.dump_tails[k[16:]].append(k)
                    elif is_name_addressed(k):
                        self.dump_named.add(k)
                    else:
                        self.dump_other.append(k)
        finally:
            env.close()

    def scan_store(self) -> None:
        env = lmdb.open(self.store_path, readonly=True, lock=False)
        try:
            with env.begin() as txn:
                # Keys only: nothing in stage A needs a value, and decoding 1.3 M
                # records here is exactly the resident copy of the corpus §B.5a's
                # memory budget forbids.
                for k in txn.cursor().iternext(keys=True, values=False):
                    k = bytes(k)
                    if len(k) <= 16:
                        self.store_short.add(k)
                        continue
                    if k[16] == EXPERIENCE_TAG:
                        self.store_experiences += 1
                        continue
                    if is_wip(k):
                        # §B.6: WIP records do not enter the tail table.  A WIP
                        # record and the persistent record of the same fact share
                        # a tail -- the WIP bit lives in key[0], inside the prefix
                        # -- so without this they arrive as claimants, and 804 new
                        # persistent keys were measured taking a WIP interpretation,
                        # 578 of them dragging in semantic_digest / deps / version /
                        # interpreted_at, four fields a content-addressed persistent
                        # key must never carry.  Costs nothing: the dump produced
                        # zero WIP keys, so no WIP key can exist in the new store.
                        self.store_wip_entities += 1
                        continue
                    if is_thm_alike(k):
                        self.store_tails[k[16:]].append(k)
                    elif is_name_addressed(k):
                        self.store_named[k[16:]].append(k)
                        self.store_named_keys.add(k)
                    else:
                        self.store_other.append(k)
        finally:
            env.close()

    # -- stage B ------------------------------------------------------------

    def load_details(self, tails: 'set[bytes]', keys: 'set[bytes]') -> None:
        """Names and positions for the old records and dump records that phase 2
        actually consults: the contested tails, plus every multi-record key."""
        want_old = set()
        for t in tails:
            want_old.update(self.store_tails.get(t, ()))
        env = lmdb.open(self.store_path, readonly=True, lock=False)
        try:
            with env.begin() as txn:
                for k in want_old:
                    raw = txn.get(k)
                    if raw is None or is_tombstone(raw):
                        continue
                    vals = list(msgpack.unpackb(bytes(raw)))
                    vals += [None] * (13 - len(vals))
                    pos = vals[F_POSITION]
                    if pos is not None:
                        pos = (dec(pos[0]), pos[1], pos[2])
                    self.old_detail[k] = OldDetail(dec(vals[F_NAME]), pos)
        finally:
            env.close()

        env = lmdb.open(self.dump_path, readonly=True, lock=False)
        try:
            with env.begin() as txn:
                for k in keys:
                    raw = txn.get(k)
                    if raw is None:
                        continue
                    out = []
                    for r in msgpack.unpackb(bytes(raw)):
                        pos = r[D_POS]
                        if pos is not None:
                            pos = (dec(pos[0]), pos[1], pos[2])
                        out.append(DumpDetail(dec(r[D_NAME]), pos, dec(r[D_THEORY])))
                    self.dump_detail[k] = out
        finally:
            env.close()


# ---------------------------------------------------------------------------
# Phase 2
# ---------------------------------------------------------------------------

class Plan:
    """The decision for every new key, built completely before anything is written.

    A later tail cannot change an earlier decision, but the artefacts must be
    complete before the store is opened for writing, so a crash leaves no
    half-written store (§B.5a)."""

    def __init__(self) -> None:
        self.source: dict[bytes, bytes] = {}        # new key -> old key it took
        self.mark: dict[bytes, str] = {}            # new key -> why
        self.pick: dict[bytes, int] = {}            # new key -> index of its dump record
        self.pick_mark: dict[bytes, str] = {}       # new key -> 'arbitrary' when the pick was
        self.gap: list[bytes] = []                  # new keys with no source
        self.suspect_tails: dict[bytes, str] = {}   # tail -> dominant mark
        self.case_a = 0


def decide(tab: Tables) -> Plan:
    """§B.6 phase 2, per tail, in the plan's order.

    Two decisions run here and their ORDER IS FIXED (§B.6): first the tail-level
    assignment picks which old record each new key takes, and only then does
    `choose_dump_record` pick which dump record on that key supplies name and
    position.  B.1 compares a claimant's dumped position against the old record's,
    and a key carrying several dump records has several claimants -- so a
    multi-record new key contributes NO B.1 witness.  Letting B.1 fire on "any
    dump record on the key matches" instead was measured to change 78 tails, 33 of
    them genuinely mutually dependent: the tail-level branch would be reading a
    value this function has not chosen yet."""
    plan = Plan()
    all_tails = sorted(set(tab.dump_tails) | set(tab.store_tails))

    for tail in all_tails:
        news = sorted(tab.dump_tails.get(tail, ()))
        olds = sorted(tab.store_tails.get(tail, ()))
        if not news:
            continue                       # old records with no new key: pruned leftovers
        if not olds:
            plan.gap.extend(news)          # Case C
            continue

        # Case A -- one old record, one new key, one dump record.  The only shape
        # with no ambiguity of any kind, and the overwhelming majority.
        if len(olds) == 1 and len(news) == 1 and news[0] not in tab.dump_multi:
            plan.source[news[0]] = olds[0]
            plan.case_a += 1
            continue

        # Every other tail is contested: filled, and recorded on the suspect list.
        old_set = set(olds)
        claimed: set[bytes] = set()
        marks: list[str] = []

        # B.0 -- an unchanged key keeps its own record, before anything else is
        # tried.  Its key did not move, so no evidence stronger than this exists.
        # Omitting the step was measured to hand 7,711 such keys another record's
        # interpretation.
        for nk in news:
            if nk in old_set:
                plan.source[nk] = nk
                plan.mark[nk] = "exact"
                claimed.add(nk)
                marks.append("exact")

        # B.1 -- positional match on file AND line AND name.  Both halves are
        # load-bearing: file alone is not enough (a stored position can point at a
        # same-base-name sibling's file), and position alone is not enough
        # (backfill_positions writes only the position, so it witnesses which
        # sibling the position sweep reached last, not whose interpretation is
        # stored).  Multi-record keys are skipped -- see this function's docstring.
        for nk in news:
            if nk in plan.source or nk in tab.dump_multi:
                continue
            det = tab.dump_detail.get(nk)
            if not det or det[0].position is None:
                continue
            want = det[0].position[:2]

            def matches(ok: bytes, want=want, det=det) -> bool:
                o = tab.old_detail.get(ok)
                return (o is not None and o.position is not None
                        and o.position[:2] == want and o.name == det[0].name)

            cands = [ok for ok in olds if ok not in claimed and matches(ok)]
            if len(cands) == 1:
                plan.source[nk] = cands[0]
                plan.mark[nk] = "matched"
                claimed.add(cands[0])
                marks.append("matched")

        # B.2 -- only-candidate.  Phrased over the UNCLAIMED set, deliberately, and
        # that is not the reading B.3 takes.  Dominant shape: one old record, one
        # new key, two dump records on it -- 12,602 tails, where the pairing is
        # forced but which dump record supplies name and position is not.
        unassigned = [nk for nk in news if nk not in plan.source]
        unclaimed = [ok for ok in olds if ok not in claimed]
        if len(unassigned) == 1 and len(unclaimed) == 1:
            plan.source[unassigned[0]] = unclaimed[0]
            plan.mark[unassigned[0]] = "forced-pairing"
            claimed.add(unclaimed[0])
            marks.append("forced-pairing")
        else:
            # B.3 -- one text, several keys.  READ OVER THE TAIL'S SHAPE, not over
            # what is still unclaimed (§B.6): under the unclaimed reading, B.0 has
            # already consumed the tail's only old record and the remaining new
            # keys reach no branch at all -- and they are not Case C either, since
            # their tail does carry an old record, so they would leave the store
            # silently.  11,856 keys under that reading against 280 under this one.
            if len(olds) == 1 and len(news) > 1:
                for nk in unassigned:
                    plan.source[nk] = olds[0]
                    plan.mark[nk] = "copied"
                    marks.append("copied")
            else:
                # B.4 -- several texts, no positional evidence.  Assign in a stated
                # deterministic order so the outcome is reproducible rather than
                # dependent on thread scheduling.
                for nk, ok in zip(unassigned, unclaimed):
                    plan.source[nk] = ok
                    plan.mark[nk] = "arbitrary"
                    claimed.add(ok)
                    marks.append("arbitrary")

        # The catch-all.  Under the tail-shape reading this should be nearly empty;
        # it exists so that the difference is reportable rather than invisible.
        for nk in news:
            if nk not in plan.source:
                plan.gap.append(nk)
                marks.append("unfilled")

        plan.suspect_tails[tail] = _dominant(marks)

    return plan


_MARK_ORDER = ["unfilled", "arbitrary", "copied", "forced-pairing", "matched", "exact"]


def _dominant(marks: 'list[str]') -> str:
    """The weakest justification anywhere on the tail names the tail: a tail is
    only as trustworthy as its least-evidenced binding."""
    for m in _MARK_ORDER:
        if m in marks:
            return m
    return "none"


def choose_dump_record(tab: Tables, plan: Plan, key: bytes) -> None:
    """§B.6: which of a key's dump records supplies `name` and `position`.

    Decided by the old record's own name.  `Record.name` reaches disk through
    exactly one writer -- `write_answer`, which puts name, expr, interpretation,
    constituents and position in a single put -- and the defect lived in
    `compute_constituents`, which moved only the key prefix and the constituent
    list.  So the stored name is the one field that records which claimant the
    stored English was written about, and it is literally the string that was in
    front of the interpreting model.  `position` and `expr` are later writes by
    other passes (`backfill_positions` is keyed only by universal key and takes no
    theory at all; `semantic_interpretation.py:1075-1079` rewrites expr from a
    later theory's printing while keeping the earlier name and text), so on a
    multi-claimant key the old record is a chimera and only its name is bound to
    its interpretation.

    On all 16,356 multi-record keys the constituent lists are byte-identical, so
    neither the key prefix nor `theory_constituents` is ever at stake here -- only
    name and position -- and the claimants are one fact under several true names,
    not several facts.  §B.1a's mis-copy lives in Case B.3, not here."""
    det = tab.dump_detail.get(key)
    if det is None or len(det) == 1:
        plan.pick[key] = 0
        return
    old = tab.old_detail.get(plan.source.get(key, b""))
    if old is not None:
        hits = [i for i, d in enumerate(det) if d.name == old.name]
        if len(hits) == 1:
            plan.pick[key] = hits[0]
            return
    # Sorted by (theory long name, name), never by thread order.  Marked arbitrary
    # -- including the case where every record carries the SAME name, which is not
    # evidence: 1,469 of those 1,491 keys have claimants sharing a theory base name,
    # where fact names are byte-identical by construction and the name test is
    # structurally blind.  Only their position differs, and nothing reads position.
    plan.pick[key] = min(range(len(det)), key=lambda i: (det[i].theory, det[i].name, i))
    plan.pick_mark[key] = "arbitrary"


# ---------------------------------------------------------------------------
# §B.6a -- name-addressed keys
# ---------------------------------------------------------------------------

def decide_named(tab: Tables, plan: Plan) -> 'tuple[list[bytes], list[bytes]]':
    """Decided key by key, never by tail: a name-addressed tail is the kind byte
    plus the entity's NAME, so a tail match across theories is a match on a name,
    which is the inference this migration exists to remove.

    Three branches.  Present in the store -> copy verbatim, keeping its own
    `theory_constituents` (None for these kinds -- do NOT write the dump's []).
    Absent with no old key on its tail -> a genuinely new entity.  Absent but some
    old key shares its tail -> the key MOVED; report it and bill for it rather than
    filling it by a cross-theory name match.  That third branch is a tail read, not
    a tail join: it decides nothing, it only refuses to call a moved key new."""
    verbatim, moved, new = [], [], []
    for k in sorted(tab.dump_named):
        if k in tab.store_named_keys:
            verbatim.append(k)
        elif tab.store_named.get(k[16:]):
            moved.append(k)
            plan.gap.append(k)
        else:
            new.append(k)
            plan.gap.append(k)
    return verbatim, moved + new


# ---------------------------------------------------------------------------
# Phase 3 -- write
# ---------------------------------------------------------------------------

TXN_KEYS = 10_000


class Counts(dict):
    def bump(self, k: str, n: int = 1) -> None:
        self[k] = self.get(k, 0) + n


def build_store(tab: Tables, plan: Plan, verbatim: 'list[bytes]',
                out_dir: str, counts: Counts) -> 'set[bytes]':
    """Write the new semantics.lmdb.  Returns the keys whose vector must be dropped.

    A filled theorem-alike record takes the dump's name, entity position and
    CORRECTED constituents; interpretation and every remaining field come from the
    chosen old record.  Where the dump's proposition differs from that record's
    `expr`, or the dump's name from its name, the dump's is carried and the key's
    vector is dropped -- both, not expr alone, because the embedded document is
    `pretty_print + interpretation` and `pretty_print` renders the name, and
    `_auto_embed` fires only on ABSENT vectors, so a stale one is never refreshed.
    """
    drop_vec: set[bytes] = set()
    src = lmdb.open(tab.store_path, readonly=True, lock=False)
    dmp = lmdb.open(tab.dump_path, readonly=True, lock=False)
    dst = lmdb.open(os.path.join(out_dir, "semantics.lmdb"), map_size=SEMANTICS_MAP_SIZE)

    gap_theories = gap_theory_keys(tab, plan)

    st = src.begin()
    dt_dump = dmp.begin()
    wt = dst.begin(write=True)
    n = 0
    try:
        # -- theory-status records and the counter, verbatim.
        # NOT filtered out by `len(key) > 16`: that is the natural way to write the
        # entity loop and it silently drops all 11,417, after which
        # `is_thy_interpreted` reads false everywhere and the next collect
        # re-interprets the whole corpus at full price.  §B.7 gate 6 exists for it.
        for k in sorted(tab.store_short):
            raw = st.get(k)
            if raw is None:
                continue
            raw = bytes(raw)
            if k != COUNTER_KEY and k in gap_theories:
                # §B.8: clearing `finished` on exactly the gap theories is what lets
                # plan_interpretation see them again.
                d = msgpack.unpackb(raw)
                d = {(x.encode() if isinstance(x, str) else x): y for x, y in d.items()}
                d[b"finished"] = False
                raw = bytes(msgpack.packb(d) or b"")
                counts.bump("theory_status_finished_cleared")
            wt.put(k, raw)
            counts.bump("theory_status_written")

        # -- name-addressed keys present in the store: verbatim (§B.6a).
        for k in verbatim:
            raw = st.get(k)
            if raw is None or is_tombstone(raw):
                continue
            wt.put(k, bytes(raw))
            counts.bump("named_verbatim")
            n += 1
            if n % TXN_KEYS == 0:
                wt.commit(); wt = dst.begin(write=True)

        # -- theorem-alike fills.
        for nk in sorted(plan.source):
            if not is_thm_alike(nk):
                continue
            ok = plan.source[nk]
            oldraw = st.get(ok)
            dumpraw = dt_dump.get(nk)
            if oldraw is None or is_tombstone(oldraw) or dumpraw is None:
                counts.bump("fill_source_vanished")
                continue
            old = decode(bytes(oldraw))
            drec = msgpack.unpackb(bytes(dumpraw))[plan.pick.get(nk, 0)]
            dname, dprop = dec(drec[D_NAME]), dec(drec[D_PROP])
            dpos = drec[D_POS]
            if dpos is not None:
                dpos = (dec(dpos[0]), dpos[1], dpos[2])
            consts = [(dec(a), bytes(b)) for a, b in drec[D_CONSTS]]

            if dname != old.name:
                counts.bump("name_divergence")
                drop_vec.add(nk)
            if dprop != old.expr:
                counts.bump("expr_divergence")
                drop_vec.add(nk)

            wt.put(nk, encode(old._replace(
                name=dname, expr=dprop, theory_constituents=consts, position=dpos)))
            counts.bump("thm_filled")
            n += 1
            if n % TXN_KEYS == 0:
                wt.commit(); wt = dst.begin(write=True)

        wt.commit()
    except BaseException:
        wt.abort()
        raise
    finally:
        st.abort(); dt_dump.abort()
        dst.sync(); dst.close(); src.close(); dmp.close()
    return drop_vec


def gap_theory_keys(tab: Tables, plan: Plan) -> 'set[bytes]':
    """The 16-byte theory keys of every theory claiming a gap key.

    Grouped by EVERY claiming theory, not by one of them: a dump key's record
    order is scheduling-dependent (§B.3), so taking the first is taking an
    arbitrary one, and §B.8's bill is driven by the theory count."""
    out = set()
    for k in plan.gap:
        for d in tab.dump_detail.get(k, ()):
            h = tab.dump_theory_names.get(d.theory)
            if h is not None:
                out.add(h)
    return out


def build_vectors(tab: Tables, plan: Plan, drop_vec: 'set[bytes]',
                  src_path: str, out_dir: str, counts: Counts) -> None:
    """Keys only; values are copied verbatim.

    Each filled new key inherits the vector of the old key it took, unless that
    key is on the divergence-drop list.  Vector keys with no entity record are NOT
    carried forward -- 693 of them today -- or `topk` goes on materialising
    placeholder records for them.  Store metadata (the `\\x00__vector_format__`
    stamp) and the 16-byte embed-status records are copied verbatim: an earlier
    migration dropped the metadata silently by dropping anything with no image in
    its key map, and nobody had asked the question of the vector store."""
    name = os.path.basename(src_path)
    src = lmdb.open(src_path, readonly=True, lock=False)
    dst = lmdb.open(os.path.join(out_dir, name), map_size=VECTOR_MAP_SIZE)
    st = src.begin()
    wt = dst.begin(write=True)
    n = 0
    try:
        for k in sorted(tab.store_short):
            raw = st.get(k)
            if raw is not None:
                wt.put(k, bytes(raw))
                counts.bump("vec_embed_status")

        with src.begin() as meta:
            for k, v in meta.cursor():
                k = bytes(k)
                if len(k) == 16 or is_thm_alike(k) or is_name_addressed(k) \
                        or (len(k) > 16 and k[16] == EXPERIENCE_TAG):
                    continue
                wt.put(k, bytes(v))
                counts.bump("vec_metadata")
                print(f"    vector-store metadata copied verbatim: {k!r}", flush=True)

        for nk in sorted(plan.source):
            if nk in drop_vec:
                counts.bump("vec_dropped_divergence")
                continue
            raw = st.get(plan.source[nk])
            if raw is None:
                counts.bump("vec_absent_at_source")
                continue
            wt.put(nk, bytes(raw))
            counts.bump("vec_written")
            n += 1
            if n % (TXN_KEYS * 20) == 0:
                wt.commit(); wt = dst.begin(write=True)

        for k in sorted(tab.store_named_keys & tab.dump_named):
            raw = st.get(k)
            if raw is not None:
                wt.put(k, bytes(raw))
                counts.bump("vec_named")

        wt.commit()
    except BaseException:
        wt.abort()
        raise
    finally:
        st.abort()
        dst.sync(); dst.close(); src.close()


# ---------------------------------------------------------------------------
# The four artefacts
# ---------------------------------------------------------------------------

def write_artefacts(tab: Tables, plan: Plan, drop_vec: 'set[bytes]',
                    out_dir: str, counts: Counts) -> None:
    # 1. the gap list, grouped by EVERY claiming theory (§B.8 bills per theory)
    by_theory: dict[str, list[str]] = collections.defaultdict(list)
    for k in plan.gap:
        det = tab.dump_detail.get(k, ())
        if not det:
            by_theory["<unknown>"].append(k.hex())
        for d in det:
            by_theory[d.theory].append(k.hex())
    with open(os.path.join(out_dir, "gap_list.json"), "w") as f:
        json.dump({"keys": len(plan.gap), "theories": len(by_theory),
                   "by_theory": {t: sorted(set(v)) for t, v in sorted(by_theory.items())}},
                  f, indent=1)

    # 2. the suspect list.  A row must carry, per claimant, the stating theory's
    #    long name, the dump position and the proposition digest -- without them two
    #    of §B.6's seed populations cannot be re-queried from the row at all, which
    #    defeats the point of keeping the list.
    with open(os.path.join(out_dir, "suspect_list.jsonl"), "w") as f:
        for tail, mark in sorted(plan.suspect_tails.items()):
            news = sorted(tab.dump_tails.get(tail, ()))
            olds = sorted(tab.store_tails.get(tail, ()))
            row = {
                "tail": tail.hex(),
                "mark": mark,
                "old": [{"key": ok.hex(),
                         "name": tab.old_detail[ok].name if ok in tab.old_detail else None,
                         "position": tab.old_detail[ok].position if ok in tab.old_detail else None}
                        for ok in olds],
                "new": [{"key": nk.hex(),
                         "took": plan.source[nk].hex() if nk in plan.source else None,
                         "mark": plan.mark.get(nk),
                         "picked": plan.pick.get(nk),
                         "pick_mark": plan.pick_mark.get(nk),
                         "vector_dropped": nk in drop_vec,
                         "claimants": [{"theory": d.theory, "name": d.name,
                                        "position": d.position}
                                       for d in tab.dump_detail.get(nk, ())]}
                        for nk in news],
            }
            f.write(json.dumps(row) + "\n")

    # 3. every old record whose interpretation fed NO new key -- a lost text, which
    #    is what gate 4 counts.  An old key that moved is NOT pruned: its record went
    #    to the new key, and only its address changed.
    used = set(plan.source.values())
    pruned = sorted(
        (k for ks in tab.store_tails.values() for k in ks if k not in used),
        key=bytes.hex)
    pruned += sorted(k for k in tab.store_named_keys if k not in tab.dump_named)
    with open(os.path.join(out_dir, "pruned_keys.txt"), "w") as f:
        for k in pruned:
            f.write(k.hex() + "\n")
    counts["pruned_keys"] = len(pruned)

    # 4. every constant §B.7 compares against, computed by the join itself
    counts["gap_keys"] = len(plan.gap)
    counts["gap_theories"] = len(by_theory)
    counts["suspect_tails"] = len(plan.suspect_tails)
    counts["case_a_tails"] = plan.case_a
    counts["fill_sources"] = len(used)
    counts["fanout_copies"] = len(plan.source) - len(used)
    counts["vectors_dropped"] = len(drop_vec)
    counts["dump_theories"] = len(tab.dump_theory_keys)
    counts["dump_records_total"] = tab.dump_records_total
    counts["dump_multi_record_keys"] = len(tab.dump_multi)
    counts["store_wip_entities"] = tab.store_wip_entities
    counts["store_experiences"] = tab.store_experiences
    counts["theory_keys_shared"] = len(tab.dump_theory_keys & tab.store_short)
    counts["pick_arbitrary"] = len(plan.pick_mark)
    for m in _MARK_ORDER:
        counts[f"mark_{m}"] = sum(1 for v in plan.mark.values() if v == m)
    with open(os.path.join(out_dir, "counts.json"), "w") as f:
        json.dump(dict(sorted(counts.items())), f, indent=1)


# ---------------------------------------------------------------------------
# §B.7
# ---------------------------------------------------------------------------

def check_gates(out_dir: str, counts: Counts, dry: bool) -> int:
    """Evaluate §B.7 against the join's own artefacts and the new store.

    A gate whose constant is None in GATES has not been fixed yet: it reports and
    does not fail.  `--dry-run` is how those numbers are obtained."""
    problems = 0

    def gate(name: str, got: int) -> None:
        nonlocal problems
        want = GATES.get(name)
        if want is None:
            print(f"  [    ] {name}: {got}  (constant not fixed; reporting only)")
        elif want == got:
            print(f"  [ ok ] {name}: {got}")
        else:
            print(f"  [FAIL] {name}: got {got}, expected {want}")
            problems += 1

    print("\n§B.7 gates")
    gate("dump_theories", counts.get("dump_theories", 0))
    gate("theory_keys_shared", counts.get("theory_keys_shared", 0))
    gate("pruned_keys", counts.get("pruned_keys", 0))
    gate("fill_sources", counts.get("fill_sources", 0))
    gate("fanout_copies", counts.get("fanout_copies", 0))
    gate("gap_keys", counts.get("gap_keys", 0))
    if dry:
        print("  (--dry-run: the store-side gates 3, 6, 7, 8, 9, 10, 11 need a store)")
        return problems

    from Isabelle_RPC_Host.universal_key import xor_theory_prefix
    env = lmdb.open(os.path.join(out_dir, "semantics.lmdb"), readonly=True, lock=False)
    entities = short = wip = zero_len = pos_none = prefix_bad = 0
    try:
        with env.begin() as txn:
            for k, v in txn.cursor():
                k, v = bytes(k), bytes(v)
                if not v:
                    zero_len += 1
                if len(k) <= 16:
                    short += 1
                    if k != COUNTER_KEY and is_wip(k):
                        wip += 1
                    continue
                entities += 1
                if is_wip(k):
                    wip += 1
                rec = decode(v)
                if rec.position is None:
                    pos_none += 1
                if is_thm_alike(k):
                    if rec.theory_constituents is None or \
                            xor_theory_prefix([h for _, h in rec.theory_constituents]) != k[:16]:
                        prefix_bad += 1
    finally:
        env.close()

    gate("entity_records", entities)
    gate("theory_status_records", short - 1)      # less the counter
    gate("zero_length_values", zero_len)
    gate("position_none", pos_none)
    if prefix_bad:
        print(f"  [FAIL] prefix check: {prefix_bad} theorem-alike keys whose stored "
              f"constituents do not XOR to the key prefix")
        problems += 1
    else:
        print(f"  [ ok ] prefix check: 0 mismatches over {entities} entity records")
    # Gate 7 is exact: the dump produced zero WIP keys, so the only WIP keys in the
    # new store are the theory-status records copied verbatim.
    gate("wip_theory_status", wip)
    return problems


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--vectors", required=True)
    ap.add_argument("--out", required=True, help="staging DIRECTORY; §B.9 promotes it")
    ap.add_argument("--dry-run", action="store_true",
                    help="decide everything, write only the four artefacts")
    args = ap.parse_args()

    from Isabelle_Semantic_Embedding.snapshot_sync import validated_system_db
    if validated_system_db() is not None:
        raise SystemExit(
            "a system DB is configured.  Reading the store through a layered facade "
            "would copy system-resident records into the new user layer; this script "
            "reads the user environment directly and refuses to run with a system "
            "layer in play (§B.5).")

    # The staging store must carry its FINAL name.  `_store_dirs` keeps only names
    # ending `.lmdb` that are `semantics.lmdb` or start with `vector_`
    # (semantic_embedding.py:1101), so a `vector_….lmdb.building` directory is
    # invisible and `_get_lmdb_env` would create the real name empty.
    if os.path.isdir(args.out) and os.listdir(args.out):
        raise SystemExit(
            f"--out {args.out} is not empty.  Building into a populated directory can "
            "leave two generations of records side by side, each self-consistent, "
            "which every gate downstream would pass.")
    os.makedirs(args.out, exist_ok=True)

    counts = Counts()
    t0 = time.time()
    tab = Tables(args.dump, args.store)
    print("phase 1a: scanning the dump ...", flush=True)
    tab.scan_dump()
    print(f"  {len(tab.dump_theory_keys)} theories, {tab.dump_records_total} records on "
          f"{len(tab.dump_tails)} theorem-alike tails + {len(tab.dump_named)} "
          f"name-addressed keys, {len(tab.dump_multi)} keys carry several records, "
          f"{time.time() - t0:.1f}s", flush=True)
    if tab.dump_other:
        print(f"  WARNING: {len(tab.dump_other)} dump keys with an unknown kind tag")

    print("phase 1a: scanning the store ...", flush=True)
    tab.scan_store()
    print(f"  {len(tab.store_tails)} theorem-alike tails, {len(tab.store_named_keys)} "
          f"name-addressed, {len(tab.store_short)} short keys, "
          f"{tab.store_wip_entities} WIP entity records skipped, "
          f"{tab.store_experiences} experiences left to §B.10, "
          f"{time.time() - t0:.1f}s", flush=True)
    if tab.store_other:
        print(f"  WARNING: {len(tab.store_other)} store keys with an unknown kind tag")

    # Contested tails only: anything that is not "one old record, one new key, one
    # dump record".  Case A needs no detail at all, and it is most of the corpus.
    contested = set()
    for tail, news in tab.dump_tails.items():
        olds = tab.store_tails.get(tail, ())
        if not olds:
            continue
        if len(olds) > 1 or len(news) > 1 or news[0] in tab.dump_multi:
            contested.add(tail)
    want_keys = {k for t in contested for k in tab.dump_tails[t]} | set(plan_gap_keys(tab))
    print(f"phase 1b: loading details for {len(contested)} contested tails "
          f"({len(want_keys)} dump keys) ...", flush=True)
    tab.load_details(contested, want_keys)
    print(f"  {len(tab.old_detail)} old records, {len(tab.dump_detail)} dump keys, "
          f"{time.time() - t0:.1f}s", flush=True)

    print("phase 2: deciding ...", flush=True)
    plan = decide(tab)
    for nk in plan.source:
        if is_thm_alike(nk):
            choose_dump_record(tab, plan, nk)
    verbatim, named_gap = decide_named(tab, plan)
    print(f"  {plan.case_a} Case A tails, {len(plan.suspect_tails)} suspect tails, "
          f"{len(plan.source)} keys filled, {len(plan.gap)} on the gap list "
          f"({len(named_gap)} of them name-addressed), {len(verbatim)} name-addressed "
          f"copied verbatim, {time.time() - t0:.1f}s", flush=True)

    drop_vec: set[bytes] = set()
    if not args.dry_run:
        print("phase 3: writing the new semantics.lmdb ...", flush=True)
        drop_vec = build_store(tab, plan, verbatim, args.out, counts)
        print(f"  {counts.get('thm_filled', 0)} theorem-alike, "
              f"{counts.get('named_verbatim', 0)} name-addressed, "
              f"{counts.get('theory_status_written', 0)} theory-status, "
              f"{time.time() - t0:.1f}s", flush=True)
        print("phase 3: writing the new vector store ...", flush=True)
        build_vectors(tab, plan, drop_vec, args.vectors, args.out, counts)
        print(f"  {counts.get('vec_written', 0)} vectors, "
              f"{counts.get('vec_dropped_divergence', 0)} dropped on divergence, "
              f"{time.time() - t0:.1f}s", flush=True)
    else:
        # The divergence set is needed for the artefacts even in a dry run.
        drop_vec = dry_divergence(tab, plan, counts)

    write_artefacts(tab, plan, drop_vec, args.out, counts)
    problems = check_gates(args.out, counts, args.dry_run)
    print(f"\n{problems} gate problem(s); artefacts in {args.out}")
    sys.exit(1 if problems else 0)


def plan_gap_keys(tab: Tables) -> 'list[bytes]':
    """Dump keys on a tail with no old record: their claimants are needed for the
    gap list's theory grouping even though phase 2 decides nothing about them."""
    return [k for tail, ks in tab.dump_tails.items()
            if not tab.store_tails.get(tail) for k in ks]


def dry_divergence(tab: Tables, plan: Plan, counts: Counts) -> 'set[bytes]':
    """The divergence-drop set, without writing a store."""
    drop: set[bytes] = set()
    src = lmdb.open(tab.store_path, readonly=True, lock=False)
    dmp = lmdb.open(tab.dump_path, readonly=True, lock=False)
    try:
        with src.begin() as st, dmp.begin() as dt:
            for nk, ok in plan.source.items():
                if not is_thm_alike(nk):
                    continue
                oldraw, dumpraw = st.get(ok), dt.get(nk)
                if oldraw is None or is_tombstone(oldraw) or dumpraw is None:
                    counts.bump("fill_source_vanished")
                    continue
                old = decode(bytes(oldraw))
                drec = msgpack.unpackb(bytes(dumpraw))[plan.pick.get(nk, 0)]
                if dec(drec[D_NAME]) != old.name:
                    counts.bump("name_divergence"); drop.add(nk)
                if dec(drec[D_PROP]) != old.expr:
                    counts.bump("expr_divergence"); drop.add(nk)
    finally:
        src.close(); dmp.close()
    return drop


if __name__ == "__main__":
    main()
