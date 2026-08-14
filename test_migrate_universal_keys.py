#!/usr/bin/env python3
"""End-to-end test of migrate_universal_keys.py on a synthetic corpus.

Builds a dump, a store and a vector store covering every branch of B.6/B.6a,
runs the join, and checks what came out.
"""
import json, os, shutil, subprocess, sys
import lmdb, msgpack

MLML = "/home/qiyuan/Current/MLML"
SE = os.path.join(MLML, "contrib", "Semantic_Embedding")
sys.path.insert(0, SE)
sys.path.insert(0, os.path.join(MLML, "contrib", "Isabelle_RPC"))
from Isabelle_RPC_Host.universal_key import xor_theory_prefix
from Isabelle_Semantic_Embedding.semantics import _Semantic_DB
from Isabelle_RPC_Host.universal_key import EntityKind

Record = _Semantic_DB.Record
enc, dec = _Semantic_DB._encode, _Semantic_DB._decode

TMP = "/tmp/claude-1002/-home-qiyuan-Current-MLML/a32a489c-01df-4539-89b3-c3bd40f94354/scratchpad/joinlab"
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)

def thy(name, wip=False):
    h = bytearray(__import__("hashlib").sha256(name.encode()).digest()[:16])
    h[0] = (h[0] | 1) if wip else (h[0] & 0xFE)
    return bytes(h)

THY = {n: thy(n) for n in
       ["ZF.func", "ZF.ArithSimp", "HOL.List", "Zip.List", "HOL.HOL", "Pure", "A.Solo"]}
THY_WIP = thy("W.Wip", wip=True)

def key(consts, tag, payload15):
    return xor_theory_prefix([THY[c] for c in consts]) + bytes([tag]) + payload15

def named_key(theory, tag, name):
    return THY[theory] + bytes([tag]) + name.encode()

def drec(name, tag, pos, consts, prop, theory):
    return [name, tag, list(pos) if pos else None,
            [[c, THY[c]] for c in consts], prop, theory]

T = EntityKind.THEOREM  # 0x02
CONST = int(EntityKind.CONSTANT)

# ---------------------------------------------------------------- the dump
dump = {}
def put_dump(k, recs): dump[k] = recs

C1 = ["ZF.func", "Pure"]
# 1. Case A: one old, one new, one dump record.  Key MOVED (old prefix wrong).
kA = key(C1, T, b"A" * 15)
put_dump(kA, [drec("func.a_thm", T, ("f.thy", 10, 1), C1, "PROP A", "ZF.func")])

# 2. Multi-record key, name matches exactly one -> that one supplies name/position
kM = key(C1, T, b"M" * 15)
put_dump(kM, [drec("ArithSimp.div_rls(7)", T, ("arith.thy", 147, 8), C1, "PROP M", "ZF.ArithSimp"),
              drec("func.apply_funtype", T, ("f.thy", 96, 7), C1, "PROP M", "ZF.func")])

# 3. Multi-record key, no name match -> sorted by (theory, name), marked arbitrary
kX = key(C1, T, b"X" * 15)
put_dump(kX, [drec("z.later", T, ("z.thy", 5, 1), C1, "PROP X", "ZF.func"),
              drec("a.earlier", T, ("a.thy", 6, 1), C1, "PROP X", "ZF.ArithSimp")])

# 4. B.0 exact key + B.3 fan-out: tail carries one old record and two new keys,
#    one of which is byte-identical to the old key.
C2 = ["HOL.List", "Pure"]
C3 = ["Zip.List", "Pure"]
tailF = bytes([int(T)]) + b"F" * 15
kF1 = xor_theory_prefix([THY[c] for c in C2]) + tailF
kF2 = xor_theory_prefix([THY[c] for c in C3]) + tailF
put_dump(kF1, [drec("List.f_thm", T, ("list.thy", 1, 1), C2, "PROP F", "HOL.List")])
put_dump(kF2, [drec("List.f_thm", T, ("ziplist.thy", 1, 1), C3, "PROP F", "Zip.List")])

# 5. Case C: a new key whose tail carries no old record at all
kC = key(["A.Solo", "Pure"], T, b"C" * 15)
put_dump(kC, [drec("Solo.c_thm", T, ("solo.thy", 3, 1), ["A.Solo", "Pure"], "PROP C", "A.Solo")])

# 6. name-addressed, present in the store -> verbatim
kN = named_key("ZF.func", CONST, "ZF.func.plus")
put_dump(kN, [drec("ZF.func.plus", CONST, ("f.thy", 2, 0), [], "", "ZF.func")])
# 7. name-addressed, absent, no old key on the tail -> new entity, gap
kNnew = named_key("ZF.func", CONST, "ZF.func.brand_new")
put_dump(kNnew, [drec("ZF.func.brand_new", CONST, ("f.thy", 3, 0), [], "", "ZF.func")])
# 8. name-addressed, absent, an old key shares its tail -> moved, gap
kNmoved = named_key("ZF.ArithSimp", CONST, "ZF.moved.c")
kNmoved_old = named_key("ZF.func", CONST, "ZF.moved.c")
put_dump(kNmoved, [drec("ZF.moved.c", CONST, ("a.thy", 4, 0), [], "", "ZF.ArithSimp")])

env = lmdb.open(os.path.join(TMP, "dump.lmdb"), map_size=1 << 28)
with env.begin(write=True) as t:
    for k, v in dump.items():
        t.put(k, msgpack.packb(v))
    for n, h in THY.items():                     # theory-completion records
        t.put(h, msgpack.packb([n, 1, n + ".thy", False, 0]))
env.close()

# --------------------------------------------------------------- the store
def rec(name, expr, interp, consts, pos):
    return Record(kind=T, name=name, expr=expr, interpretation=interp,
                  theory_constituents=[(c, THY[c]) for c in consts], position=pos)

store = {}
oldA = key(["ZF.ArithSimp", "Pure"], T, b"A" * 15)     # wrong prefix: the defect
store[oldA] = enc(rec("func.a_thm", "PROP A", "the A text", ["ZF.ArithSimp", "Pure"],
                      ("f.thy", 10, 1)))
oldM = key(["ZF.ArithSimp", "Pure"], T, b"M" * 15)
store[oldM] = enc(rec("func.apply_funtype", "PROP M", "the M text",
                      ["ZF.ArithSimp", "Pure"], ("arith.thy", 147, 8)))
oldX = key(["ZF.ArithSimp", "Pure"], T, b"X" * 15)
store[oldX] = enc(rec("nobody.matches", "PROP X", "the X text",
                      ["ZF.ArithSimp", "Pure"], None))
store[kF1] = enc(rec("List.f_thm", "PROP F", "the F text", C2, ("list.thy", 1, 1)))
# a WIP record sharing tail A -- must not enter the tail table
wipA = bytes([xor_theory_prefix([THY["ZF.ArithSimp"], THY["Pure"]])[0] | 1]) \
    + key(["ZF.ArithSimp", "Pure"], T, b"A" * 15)[1:]
store[wipA] = enc(rec("func.a_thm", "PROP A", "the WIP text",
                      ["ZF.ArithSimp", "Pure"], None)._replace(version=7))
store[kN] = enc(Record(kind=EntityKind.CONSTANT, name="ZF.func.plus", expr="",
                       interpretation="the plus text"))
store[kNmoved_old] = enc(Record(kind=EntityKind.CONSTANT, name="ZF.moved.c", expr="",
                                interpretation="the moved text"))
# an old record with no new key at all -> pruned leftover
orphan = key(["ZF.func", "Pure"], T, b"O" * 15)
store[orphan] = enc(rec("gone.thm", "PROP O", "the O text", ["ZF.func", "Pure"], None))
# theory-status records and the counter
env = lmdb.open(os.path.join(TMP, "store.lmdb"), map_size=1 << 28)
with env.begin(write=True) as t:
    for k, v in store.items():
        t.put(k, v)
    for n, h in THY.items():
        t.put(h, msgpack.packb({b"finished": True, b"cost_usd": 1.0}))
    t.put(THY_WIP, msgpack.packb({b"finished": False}))
    t.put(b"\xf0", msgpack.packb(4242))
env.close()

# --------------------------------------------------------- the vector store
env = lmdb.open(os.path.join(TMP, "vector_Test.lmdb"), map_size=1 << 28)
with env.begin(write=True) as t:
    for k in store:
        t.put(k, b"VEC" + k[:4])
    for n, h in THY.items():
        t.put(h, b"embed-status")
    t.put(b"\x00__vector_format__", b"q15/v1")
    t.put(key(["ZF.func", "Pure"], T, b"Z" * 15), b"VECphantom")   # no entity record
env.close()

# ------------------------------------------------------------------- run it
out = os.path.join(TMP, "staging")
r = subprocess.run([sys.executable, os.path.join(SE, "migrate_universal_keys.py"),
                    "--dump", os.path.join(TMP, "dump.lmdb"),
                    "--store", os.path.join(TMP, "store.lmdb"),
                    "--vectors", os.path.join(TMP, "vector_Test.lmdb"),
                    "--out", out],
                   capture_output=True, text=True)
print(r.stdout)
if r.stderr:
    print("STDERR:", r.stderr[-4000:])

# ------------------------------------------------------------------ checks
fails = []
def check(what, got, want):
    if got != want:
        fails.append(f"{what}: got {got!r}, want {want!r}")
    else:
        print(f"  ok  {what} = {got!r}")

env = lmdb.open(os.path.join(out, "semantics.lmdb"), readonly=True, lock=False)
with env.begin() as t:
    def R(k):
        raw = t.get(k)
        return dec(bytes(raw)) if raw is not None else None

    print("\n-- store --")
    a = R(kA)
    check("A filled, moved key present", a is not None, True)
    check("A keeps the old interpretation", a.interpretation, "the A text")
    check("A takes the dump's corrected constituents",
          sorted(n for n, _ in a.theory_constituents), ["Pure", "ZF.func"])
    check("A's old key is gone", R(oldA), None)
    check("A did not take the WIP text", a.interpretation != "the WIP text", True)
    check("A carries no WIP-only field", a.version, None)

    m = R(kM)
    check("M name comes from the name-matching dump record", m.name, "func.apply_funtype")
    check("M position comes from the same record", m.position, ("f.thy", 96, 7))
    check("M keeps its interpretation", m.interpretation, "the M text")

    x = R(kX)
    check("X falls back to sorted (theory, name)", x.name, "a.earlier")

    check("F.1 exact key kept its own record", R(kF1).interpretation, "the F text")
    check("F.2 got the fan-out copy", R(kF2).interpretation, "the F text")
    check("F.2 has Zip.List constituents",
          sorted(n for n, _ in R(kF2).theory_constituents), ["Pure", "Zip.List"])

    check("Case C key is not written", R(kC), None)
    check("name-addressed present -> verbatim", R(kN).interpretation, "the plus text")
    check("name-addressed keeps theory_constituents None", R(kN).theory_constituents, None)
    check("name-addressed new key not written", R(kNnew), None)
    check("name-addressed moved key not written", R(kNmoved), None)
    check("orphan old record pruned", R(orphan), None)
    check("counter copied", msgpack.unpackb(bytes(t.get(b"\xf0"))), 4242)
    check("theory-status count", sum(1 for k in t.cursor().iternext(values=False)
                                     if len(bytes(k)) == 16), len(THY) + 1)
    fin = msgpack.unpackb(bytes(t.get(THY["A.Solo"])))
    check("gap theory's finished cleared", fin[b"finished"], False)
    fin2 = msgpack.unpackb(bytes(t.get(THY["Pure"])))
    check("non-gap theory keeps finished", fin2[b"finished"], True)
env.close()

print("\n-- vectors --")
env = lmdb.open(os.path.join(out, "vector_Test.lmdb"), readonly=True, lock=False)
with env.begin() as t:
    check("A's vector followed its old key", bytes(t.get(kA)), b"VEC" + oldA[:4])
    # M diverges on nothing: the name rule picked the record whose name equals the
    # old record's, and its prop equals the old expr.  Keeping the vector is the
    # whole point of the rule.
    check("M's vector kept (the name rule agreed)", bytes(t.get(kM)), b"VEC" + oldM[:4])
    check("X's vector dropped (name diverged)", t.get(kX), None)
    check("F.2 inherited F.1's vector", bytes(t.get(kF2)), b"VEC" + kF1[:4])
    check("phantom vector not carried",
          t.get(key(["ZF.func", "Pure"], T, b"Z" * 15)), None)
    check("format stamp copied", bytes(t.get(b"\x00__vector_format__")), b"q15/v1")
    check("embed status copied", bytes(t.get(THY["Pure"])), b"embed-status")
env.close()

print("\n-- artefacts --")
gap = json.load(open(os.path.join(out, "gap_list.json")))
check("gap keys", gap["keys"], 3)
counts = json.load(open(os.path.join(out, "counts.json")))
check("Case A tails", counts["case_a_tails"], 1)
check("fan-out copies", counts["fanout_copies"], 1)
check("pick marked arbitrary", counts["pick_arbitrary"], 1)
pruned = open(os.path.join(out, "pruned_keys.txt")).read().split()
# "Pruned" is an old record whose interpretation fed NO new key -- a lost text,
# which is what gate 4 counts.  oldA/oldM/oldX each fed a moved key and are not lost.
check("pruned keys", sorted(pruned), sorted([orphan.hex(), kNmoved_old.hex()]))
susp = [json.loads(l) for l in open(os.path.join(out, "suspect_list.jsonl"))]
check("suspect tails", len(susp), 3)   # M, X, F; A is Case A and C has no old record
marks = {s["mark"] for s in susp}
# A tail is named by its WEAKEST binding: F has an exact hit and a fan-out copy,
# and it is the copy that makes the tail worth revisiting.
check("suspect marks", marks, {"forced-pairing", "copied"})
mrow = [s for s in susp if s["tail"] == (bytes([int(T)]) + b"M" * 15).hex()][0]
check("suspect row carries every claimant",
      sorted(c["theory"] for c in mrow["new"][0]["claimants"]), ["ZF.ArithSimp", "ZF.func"])

print()
if fails:
    print(f"{len(fails)} FAILURE(S):")
    for f in fails:
        print("  ✘", f)
    sys.exit(1)
print("all checks passed")
