#!/usr/bin/env python3
"""The suspect list's surgical repairs, applied to the staging store.

BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md §B.6, "The adjudication".  Four teams
worked through the join's 16,935 suspect rows and found 90 keys that need a fix
plus 274 that were sent to the gap list although a verbatim-applicable text was
sitting on their tail.  This applies all four repairs to the store the join built,
BEFORE §B.9 promotes it, so that the whole correction lands in one generation
rather than as an after-the-fact edit to a live store.

It is deliberately NOT a change to §B.6's rules and the join was not re-run.  Every
one of these is a named, enumerated population; a rule general enough to catch them
would have to be sound about semantic divergence, and the adjudication showed it
cannot be (two `PosRat.thy` files score 0.645 on any textual metric and differ by
one character).  Surgery on a fixed list is the honest shape for this.

THE FOUR REPAIRS
----------------
**fill (274)** — a new key that reached no branch of §B.6's Phase 2 and went to the
gap list, although an old record on its tail carries a byte-identical fact name.
Cause: three or four sibling sessions state one fact, every old record's key
survived byte-identically, so B.0 consumed them all and the extra sibling had
nothing left.  Nothing wrong was written; the cost was paying to re-interpret
English already in the store.

**delete (61)** — the record's English is factually false of the entity it landed
on, over four mechanisms (`'a ref` payload-carrying versus phantom-parameter,
`prat` non-negative versus strictly positive, `'a tree` binary versus rose,
`standard_borel` Polish-space versus measurable-encoding).  The record and its
vector go and the claiming theories' `finished` flags are cleared, so §B.8's
collection re-interprets them.  Deleted rather than blanked: **zero** records in
either store have `interpretation is None`, so blanking would mint a shape the
corpus has never held, while "no record at this key" is what every un-interpreted
entity already looks like.

**swap (56 keys / 28 tails)** — Jinja against JinjaDCI, where §B.6's B.4 paired the
two texts the wrong way round.  Both texts describe the same proposition, so
nothing became false; what is crossed is the name/text pairing and the vector.

**rename (1)** — `?A ⊆ ?A`.  Sorted order wrote `Relators.relator_props(29)`, an
`(n)`-indexed dynamic-collection member, over `Set.subset_refl` from `HOL.Set`,
which is a constituent of the key itself.  The name enters the embedded document.

WHAT IT WRITES
--------------
The staging `semantics.lmdb` and vector store, in place, plus a corrected
`gap_list.json` and a `patch_report.json` beside them.  It never touches the live
store, and `~/rekey-staging-20260814` — the join's first, byte-identical output — is
the untouched twin to fall back on.

Scaffolding for one migration; delete with the rest of Part B.
"""

import argparse
import collections
import json
import os
import sys
from typing import Any

import lmdb
import msgpack

HERE = os.path.dirname(os.path.abspath(__file__))
MLML = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.environ.get("ISABELLE_RPC_PATH",
                                  os.path.join(MLML, "contrib", "Isabelle_RPC")))

from migrate_universal_keys import (      # noqa: E402
    D_CONSTS, D_NAME, D_POS, D_PROP, D_THEORY, dec, decode, encode)


def dump_records(txn, key: bytes) -> 'list[Any]':
    raw = txn.get(key)
    return msgpack.unpackb(bytes(raw)) if raw is not None else []


def unpack_dump(rec: 'list[Any]') -> 'tuple[str, str, Any, Any, str]':
    pos = rec[D_POS]
    if pos is not None:
        pos = (dec(pos[0]), pos[1], pos[2])
    return (dec(rec[D_NAME]), dec(rec[D_PROP]), pos,
            [(dec(a), bytes(b)) for a, b in rec[D_CONSTS]], dec(rec[D_THEORY]))


def pick(recs: 'list[Any]', old_name: 'str | None') -> 'list[Any]':
    """§B.6's rule, unchanged: the record whose name equals the old record's, else
    the first in sorted (theory long name, name) order."""
    if len(recs) == 1:
        return recs[0]
    hits = [r for r in recs if dec(r[D_NAME]) == old_name]
    if len(hits) == 1:
        return hits[0]
    return min(recs, key=lambda r: (dec(r[D_THEORY]), dec(r[D_NAME])))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", required=True, help="the join's output DIRECTORY")
    ap.add_argument("--old-store", required=True)
    ap.add_argument("--old-vectors", required=True)
    ap.add_argument("--dump", required=True)
    ap.add_argument("--patchlist", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    plist = json.load(open(args.patchlist))
    sem_path = os.path.join(args.staging, "semantics.lmdb")
    vec_name = next(d for d in sorted(os.listdir(args.staging))
                    if d.startswith("vector_") and d.endswith(".lmdb"))
    vec_path = os.path.join(args.staging, vec_name)
    rep: dict[str, Any] = {"vector_store": vec_name}
    counts: collections.Counter = collections.Counter()

    old = lmdb.open(args.old_store, readonly=True, lock=False)
    oldv = lmdb.open(args.old_vectors, readonly=True, lock=False)
    dmp = lmdb.open(args.dump, readonly=True, lock=False)
    if args.dry_run:
        sem = lmdb.open(sem_path, readonly=True, lock=False)
        vec = lmdb.open(vec_path, readonly=True, lock=False)
    else:
        sem = lmdb.open(sem_path, map_size=1 << 32)
        vec = lmdb.open(vec_path, map_size=1 << 36)

    ot = old.begin(); ovt = oldv.begin(); dt = dmp.begin()
    st = sem.begin(write=not args.dry_run)
    vt = vec.begin(write=not args.dry_run)
    problems: list[str] = []

    def put(txn, k: bytes, v: bytes) -> None:
        if not args.dry_run:
            txn.put(k, v)

    def rm(txn, k: bytes) -> None:
        if not args.dry_run:
            txn.delete(k)

    def bind(key: bytes, source: bytes, cls: str) -> None:
        """Write `key`'s record from the old record at `source`, keeping the dump's
        name / proposition / position / constituents, exactly as §B.6 specifies for
        a filled theorem-alike case."""
        oraw = ot.get(source)
        recs = dump_records(dt, key)
        if oraw is None or not recs:
            problems.append(f"{cls} {key.hex()}: source record or dump entry missing")
            return
        o = decode(bytes(oraw))
        name, prop, pos, consts, _ = unpack_dump(pick(recs, o.name))
        put(st, key, encode(o._replace(name=name, expr=prop,
                                       theory_constituents=consts, position=pos)))
        counts[f"{cls}_records"] += 1
        # The vector follows the record it inherited, and is dropped on any name or
        # proposition divergence: the embedded document is pretty_print +
        # interpretation, pretty_print renders the name, and _auto_embed only ever
        # fires on an ABSENT vector, so a stale one would never be refreshed.
        if name != o.name or prop != o.expr:
            rm(vt, key)
            counts[f"{cls}_vectors_dropped"] += 1
        else:
            v = ovt.get(source)
            if v is None:
                counts[f"{cls}_vectors_absent_at_source"] += 1
            else:
                put(vt, key, bytes(v))
                counts[f"{cls}_vectors"] += 1

    # -- fill: 274 keys the branch order sent to the gap list -----------------
    for r in plist["fill"]:
        key = bytes.fromhex(r["key"])
        if st.get(key) is not None:
            problems.append(f"fill {key.hex()}: already has a record")
            continue
        bind(key, bytes.fromhex(r["source"]), "fill")

    # -- swap: 56 keys whose two texts were paired the wrong way round --------
    for r in plist["swap"]:
        key = bytes.fromhex(r["key"])
        if st.get(key) is None:
            problems.append(f"swap {key.hex()}: no record to correct")
            continue
        bind(key, bytes.fromhex(r["source"]), "swap")

    # -- rename: one name to restore -----------------------------------------
    for r in plist["rename"]:
        key = bytes.fromhex(r["key"])
        raw = st.get(key)
        recs = dump_records(dt, key)
        want = [x for x in recs if dec(x[D_NAME]) == r["want_name"]]
        if raw is None or len(want) != 1:
            problems.append(f"rename {key.hex()}: record missing or "
                            f"{len(want)} dump records name {r['want_name']!r}")
            continue
        cur = decode(bytes(raw))
        name, prop, pos, consts, _ = unpack_dump(want[0])
        put(st, key, encode(cur._replace(name=name, expr=prop,
                                         theory_constituents=consts, position=pos)))
        # The name is the first line of the embedded document, so the vector
        # computed under the old name must not survive it.
        rm(vt, key)
        counts["rename_records"] += 1
        counts["rename_vectors_dropped"] += 1

    # -- delete: 61 records whose English is false of where they landed -------
    thy_key = {}
    for k, v in dt.cursor():
        k = bytes(k)
        if len(k) <= 16:
            thy_key[dec(msgpack.unpackb(bytes(v))[0])] = k
    clear_finished: set[bytes] = set()
    gap_added: dict[str, list[str]] = collections.defaultdict(list)
    for r in plist["delete"]:
        key = bytes.fromhex(r["key"])
        if st.get(key) is None:
            problems.append(f"delete {key.hex()}: no record present")
            continue
        rm(st, key)
        rm(vt, key)
        counts["delete_records"] += 1
        # Every claiming theory, not one of them: a dump key's record order is
        # scheduling-dependent and §B.8 bills per theory.
        for rec in dump_records(dt, key):
            thy = dec(rec[D_THEORY])
            gap_added[thy].append(key.hex())
            h = thy_key.get(thy)
            if h is not None:
                clear_finished.add(h)
            else:
                problems.append(f"delete {key.hex()}: theory {thy} has no dump key")
    for h in sorted(clear_finished):
        raw = st.get(h)
        if raw is None:
            problems.append(f"theory-status record {h.hex()} absent")
            continue
        d = msgpack.unpackb(bytes(raw))
        d = {(x.encode() if isinstance(x, str) else x): y for x, y in d.items()}
        d[b"finished"] = False
        put(st, h, bytes(msgpack.packb(d) or b""))
        counts["finished_cleared"] += 1

    if not args.dry_run:
        st.commit(); vt.commit()
    else:
        st.abort(); vt.abort()
    ot.abort(); ovt.abort(); dt.abort()

    # -- the corrected gap list ----------------------------------------------
    gpath = os.path.join(args.staging, "gap_list.json")
    gap = json.load(open(gpath))
    filled = {r["key"] for r in plist["fill"]}
    by_thy: dict[str, list[str]] = {}
    for thy, keys in gap["by_theory"].items():
        keep = sorted(set(keys) - filled)
        if keep:
            by_thy[thy] = keep
    for thy, keys in gap_added.items():
        by_thy[thy] = sorted(set(by_thy.get(thy, [])) | set(keys))
    allkeys = {k for v in by_thy.values() for k in v}
    rep["gap_before"] = {"keys": gap["keys"], "theories": gap["theories"]}
    rep["gap_after"] = {"keys": len(allkeys), "theories": len(by_thy)}
    if not args.dry_run:
        json.dump({"keys": len(allkeys), "theories": len(by_thy),
                   "by_theory": dict(sorted(by_thy.items()))},
                  open(gpath, "w"), indent=1)

    # -- read back what we claim to have done --------------------------------
    if not args.dry_run:
        with sem.begin() as rt, vec.begin() as rv, old.begin() as o2:
            for r in plist["fill"] + plist["swap"]:
                key = bytes.fromhex(r["key"])
                raw = rt.get(key)
                if raw is None:
                    problems.append(f"readback: {key.hex()} has no record")
                    continue
                sraw = o2.get(bytes.fromhex(r["source"]))
                if sraw is None:
                    problems.append(f"readback: {key.hex()}'s source vanished")
                    continue
                if decode(bytes(raw)).interpretation != decode(bytes(sraw)).interpretation:
                    problems.append(f"readback: {key.hex()} does not carry its "
                                    f"source's interpretation")
            for r in plist["delete"]:
                if rt.get(bytes.fromhex(r["key"])) is not None:
                    problems.append(f"readback: {r['key']} was not deleted")
                if rv.get(bytes.fromhex(r["key"])) is not None:
                    problems.append(f"readback: {r['key']}'s vector survived")
            for r in plist["rename"]:
                raw = rt.get(bytes.fromhex(r["key"]))
                got = decode(bytes(raw)).name if raw is not None else None
                if got != r["want_name"]:
                    problems.append(f"readback: {r['key']} is named {got!r}, "
                                    f"wanted {r['want_name']!r}")
            rep["entity_records"] = sum(
                1 for k in rt.cursor().iternext(keys=True, values=False)
                if len(bytes(k)) > 16)
            rep["vector_keys"] = rv.stat()["entries"]

    sem.close(); vec.close(); old.close(); oldv.close(); dmp.close()

    rep["counts"] = dict(sorted(counts.items()))
    rep["problems"] = problems
    if not args.dry_run:
        json.dump(rep, open(os.path.join(args.staging, "patch_report.json"), "w"),
                  indent=1)
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    print(f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
