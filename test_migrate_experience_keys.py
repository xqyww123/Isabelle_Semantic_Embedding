#!/usr/bin/env python3
"""Test of migrate_experience_keys.py on a synthetic corpus.

The Isa-REPL app is not run: its results are injected as the EXPMIG lines the
app would stream, so the parsing, the outcome decisions, the key moves and the
write phase are all exercised without Isabelle.  What the app itself computes
is checked on cslh19 by the dry run.
"""
import collections
import hashlib
import os
import shutil
import sys

import lmdb
import msgpack

MLML = "/home/qiyuan/Current/MLML"
SE = os.path.join(MLML, "contrib", "Semantic_Embedding")
sys.path.insert(0, SE)
sys.path.insert(0, os.path.join(MLML, "contrib", "Isabelle_RPC"))
from Isabelle_RPC_Host.universal_key import xor_theory_prefix  # noqa: E402

import migrate_experience_keys as M  # noqa: E402

TMP = ("/tmp/claude-1002/-home-qiyuan-Current-MLML/"
       "a32a489c-01df-4539-89b3-c3bd40f94354/scratchpad/explab")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(("  ok  " if cond else "  FAIL") + " " + name)


def thy(name, wip=False):
    h = bytearray(hashlib.sha256(name.encode()).digest()[:16])
    h[0] = (h[0] | 1) if wip else (h[0] & 0xFE)
    return bytes(h)


# Unique.A / Unique.B have corpus-unique base names; Shared.List and Other.List
# share the base name "List"; Absent.Missing is not in the dump census.
THY = {n: thy(n) for n in
       ["Unique.A", "Unique.B", "Shared.List", "Other.List", "Ghost.C"]}
THY["Absent.Missing"] = thy("Absent.Missing")
DUMP_THEORIES = ["Unique.A", "Unique.B", "Shared.List", "Other.List", "Ghost.C"]

EXP = 0x08


def exp_key(consts, payload15, wip=False):
    hashes = [THY[c] for c in consts]
    if wip:
        hashes = hashes + [thy("W.Wip", wip=True)]
    return xor_theory_prefix(hashes) + bytes([EXP]) + payload15


def exp_record(name, consts, patterns):
    # The 8-field experience layout: kind, name, expr, interpretation,
    # locale_provenance, theory_constituents, experience, goal_patterns.
    return msgpack.packb([EXP, name, None, f"when to use {name}", None,
                          [[c, THY[c]] for c in consts],
                          f"how to prove {name}", patterns])


# ---------------------------------------------------------------- the stores
src_records = {}

# 1. verbatim: unique base names, hashes current -> key unchanged
kV = exp_key(["Unique.A", "Unique.B"], b"V" * 15)
src_records[kV] = exp_record("verbatim_exp", ["Unique.A", "Unique.B"], ["?a = ?a"])

# 2. global: empty constituent list, all-zero prefix
kG = bytes(16) + bytes([EXP]) + b"G" * 15
src_records[kG] = exp_record("global_exp", [], ["?P"])

# 3. recompute -> unchanged: names Shared.List, recomputation returns the same list
kU = exp_key(["Shared.List"], b"U" * 15)
src_records[kU] = exp_record("unchanged_exp", ["Shared.List"], ["rev (rev ?xs) = ?xs"])

# 4. recompute -> repaired: stored Shared.List, recomputation says Other.List
kR = exp_key(["Shared.List"], b"R" * 15)
src_records[kR] = exp_record("repaired_exp", ["Shared.List"], ["zip ?xs ?ys = ?zs"])

# 5. recompute -> cleared: names a theory absent from the dump; the app FAILs
kC = exp_key(["Absent.Missing"], b"C" * 15)
src_records[kC] = exp_record("cleared_exp", ["Absent.Missing"], ["broken ("])

# 6. WIP record: skipped entirely
kW = exp_key(["Unique.A"], b"W" * 15, wip=True)
src_records[kW] = exp_record("wip_exp", ["Unique.A"], ["?x"])

# 7. a non-experience key: ignored by the scan
kT = THY["Unique.A"] + bytes([0x02]) + b"T" * 15
src_records[kT] = msgpack.packb([2, "some_thm", "prop", "text", None,
                                 [["Unique.A", THY["Unique.A"]]]])

src = os.path.join(TMP, "source.lmdb")
env = lmdb.open(src, map_size=1 << 24)
with env.begin(write=True) as txn:
    for k, v in src_records.items():
        txn.put(k, v)
env.close()

# vectors for all experiences except the cleared one (missing-vector path)
srcvec = os.path.join(TMP, "source_vectors.lmdb")
env = lmdb.open(srcvec, map_size=1 << 24)
with env.begin(write=True) as txn:
    for k in (kV, kG, kU, kR, kW):
        txn.put(k, b"VEC" + k[:4])
env.close()

dump = os.path.join(TMP, "dump.lmdb")
env = lmdb.open(dump, map_size=1 << 24)
with env.begin(write=True) as txn:
    for n in DUMP_THEORIES:
        txn.put(THY[n], msgpack.packb([n, 0, f"/src/{n}.thy"]))
env.close()

target_cache = os.path.join(TMP, "cache")
os.makedirs(target_cache)
tsem = os.path.join(target_cache, "semantics.lmdb")
tvec = os.path.join(target_cache, "vector_Test.lmdb")
lmdb.open(tsem, map_size=1 << 24).close()
lmdb.open(tvec, map_size=1 << 24).close()

# ---------------------------------------------------------------- phases 1-2
records, wip = M.scan_source(src)
check("scan: 5 persistent", len(records) == 5)
check("scan: 1 WIP skipped", wip == 1)

name_hash, base_count = M.dump_census(dump)
check("census: List base name shared", base_count["List"] == 2)
M.partition(records, name_hash, base_count)

by_key = {r.key: r for r in records}
check("partition: verbatim", by_key[kV].cls == "verbatim")
check("partition: global", by_key[kG].cls == "global")
check("partition: shared base -> recompute", by_key[kU].cls == "recompute"
      and by_key[kR].cls == "recompute")
check("partition: dump-absent -> recompute", by_key[kC].cls == "recompute")

# Inject what the app would stream.
def hx(s):
    return s.encode().hex().upper()

msgs = [
    f"EXPMIG OK {kU.hex()} {hx('Shared.List')}:{THY['Shared.List'].hex().upper()}",
    f"EXPMIG OK {kR.hex()} {hx('Other.List')}:{THY['Other.List'].hex().upper()}",
    f"EXPMIG FAIL {kC.hex()} {hx('Could not parse pattern ' + chr(34) + 'broken (' + chr(34))}",
    "some unrelated tracing line",
]
got = {}
for m in msgs:
    M.parse_expmig(m, got)
check("parse: 3 results, tracing ignored", len(got) == 3)

todo = {r.key.hex(): r for r in records if r.cls == "recompute"}
M.apply_results(todo, got)
check("outcome: unchanged", by_key[kU].outcome == "unchanged")
check("outcome: repaired", by_key[kR].outcome == "repaired")
check("outcome: cleared, to [] not None",
      by_key[kC].outcome == "cleared" and by_key[kC].new_consts == [])
check("cleared message decoded",
      "Could not parse pattern" in (by_key[kC].message or ""))

diag = M.decide_keys(records)
check("no hash disagreements here", diag["hash_disagreements"] == 0)
check("unchanged key stays", by_key[kU].new_key == kU)
kR_new = xor_theory_prefix([THY["Other.List"]]) + kR[16:]
check("repaired key moves, tail fixed", by_key[kR].new_key == kR_new
      and by_key[kR].new_key != kR and by_key[kR].new_key[16:] == kR[16:])
check("cleared key gets the all-zero prefix",
      by_key[kC].new_key == bytes(16) + kC[16:])
check("verbatim/global keys stay",
      by_key[kV].new_key == kV and by_key[kG].new_key == kG)

# ---------------------------------------------------------------- phase 3
stats = M.write_phase(records, srcvec, tsem, tvec)
check("write: 5 records", stats["records_written"] == 5)
check("write: post-scan finds 5", stats["target_experience_keys_after"] == 5)
check("write: 4 vectors copied, 1 missing",
      stats["vectors_copied"] == 4 and stats["vectors_missing"] == 1)

env = lmdb.open(tsem, readonly=True, lock=False)
with env.begin() as txn:
    tv = bytes(txn.get(kV) or b"")
    tr = txn.get(kR_new)
    tc = txn.get(bytes(16) + kC[16:])
    told_r = txn.get(kR)
    tw = txn.get(kW)
env.close()
check("verbatim value byte-identical", tv == src_records[kV])
check("repaired record present under the new key only",
      tr is not None and told_r is None)
check("WIP record not carried", tw is None)
rvals = msgpack.unpackb(bytes(tr or b""))
check("repaired record's constituent list rewritten",
      [(M.dec(n), bytes(h)) for n, h in rvals[M.F_CONSTS]]
      == [("Other.List", THY["Other.List"])])
check("repaired record's other fields preserved",
      M.dec(rvals[1]) == "repaired_exp"
      and M.dec(rvals[M.F_PATTERNS][0]) == "zip ?xs ?ys = ?zs")
cvals = msgpack.unpackb(bytes(tc or b""))
check("cleared record stores [] (not None)", cvals[M.F_CONSTS] == [])

env = lmdb.open(tvec, readonly=True, lock=False)
with env.begin() as txn:
    check("repaired vector under the new key",
          bytes(txn.get(kR_new) or b"") == b"VEC" + kR[:4])
    check("unchanged vector carried", txn.get(kU) is not None)
    check("cleared record has no vector (was missing at the source)",
          txn.get(bytes(16) + kC[16:]) is None)
env.close()

# One-shot-ness: a second write must refuse on the occupied target.
try:
    M.write_phase(records, srcvec, tsem, tvec)
    check("second write refused", False)
except SystemExit:
    check("second write refused", True)

# ---------------------------------------------------------------- summary
outcomes = collections.Counter(r.outcome for r in records)
print(f"\noutcomes: {dict(outcomes)}")
bad = [n for n, ok in checks if not ok]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed")
if bad:
    sys.exit("FAILED: " + ", ".join(bad))
