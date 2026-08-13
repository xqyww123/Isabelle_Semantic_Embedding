#!/usr/bin/env python3
"""Re-key the semantic store after the theory long name entered the theory hash.

WHAT CHANGED
------------
A persistent theory's hash used to be ``xxh128(file bytes ++ parent hashes)``,
which gave one identity to two theories whose ``.thy`` files happen to be byte
identical -- and to one ``.thy`` file loaded under two long names.  It is now

    clear_lsb( xxh128( long_name ++ 0x00 ++ file bytes ++ parent hashes ) )

with parents contributing their own NEW hashes, so the name propagates down the
ancestor DAG.  ``Isabelle_RPC_Host.theory_hash.theory_xxhash128`` is that
function and this script imports it: the live code and the migration cannot
disagree by a byte.  The retired algorithm is reimplemented here, as ``_old``,
because nothing computes it any more and G1 needs it.

The WIP hash (FNV-128 of the long name, LSB set) is untouched.  That does NOT
mean WIP records stay put: a theorem key's 16-byte prefix is the XOR of ALL its
constituents' hashes and only bit 0 of byte 0 carries the WIP flag, so a record
mixing WIP and persistent constituents moves with the persistent ones.

WHAT THIS TOUCHES
-----------------
``semantics.lmdb``, the vector store, and ``theory_hash.lmdb``.  Not
``experience_index.lmdb``: it is a pure derived view of the EXPERIENCE records,
so ``isabelle-semantics reindex`` after the swap is simpler and safer than
rewriting it.

Inside a record, four value fields carry universal keys or theory hashes, and
the rewrite order is what keeps key and value consistent by construction -- the
one property ``fsck`` actually checks:

  1. the hashes in ``theory_constituents``;
  2. the key's XOR prefix, recomputed FROM THAT REWRITTEN LIST;
  3. the 16-byte prefix of ``locale_uk`` and of every ``deps`` entry (measured:
     all such targets are name-addressed, so a prefix substitution is exact);
  4. ``template_uk``, which is XOR-shaped and so admits no prefix substitution:
     a value that resolves to a live record is replaced by that record's new
     key, and a value that already dangles is left byte for byte.

Nothing else in a record is touched, and msgpack round-trips these values byte
for byte (measured over all 1,369,025 of them), so an untouched field really is
untouched on disk.

WHAT IS DROPPED, AND WHAT IS RESCUED
------------------------------------
A record dies when a persistent theory hash it stands on cannot be carried
forward -- either the hash is not reproducible from today's sources (the
theory's content has changed since, or the image does not hold the theory at
all), or two theories share it.

But a shared hash is only ambiguous when the hash is all the record has.  An
XOR-prefixed record stores its constituents as (long name, hash) pairs, so the
long name is on record and resolves the collision exactly.  Those are rescued
unconditionally.  A name-addressed key and a theory-status key carry the hash
alone, and are dropped.

For a hash that is not reproducible the name (where recoverable) points at a
DIFFERENT CONTENT GENERATION of the same theory, which is a weaker thing
entirely, so those are governed by ``--rescue-superseded``:

  * ``experiences`` (the default) revives EXPERIENCE records only.  They are
    agent-authored -- written during proof search, not by theory interpretation
    -- so no re-interpretation can recreate them, and reviving them also makes
    them reachable for the first time since the content changed.
  * ``none`` revives nothing.
  * ``all`` additionally revives ordinary records.  Read the report before
    using it: a revived record that lands on a key some live record already
    holds is a duplicate and is dropped either way, while one that lands on a
    fresh key is asserting an entity that the theory's current content no
    longer has.

Theory-status records are never revived: the flag says "this theory is fully
interpreted", and carrying it from a superseded generation to the current one
would assert that while the generation's entity records are gone.

USAGE
-----
    python migrate_theory_hash_rekey.py plan  --deps deps.tsv
    python migrate_theory_hash_rekey.py apply --deps deps.tsv --dest DIR
    python migrate_theory_hash_rekey.py gates --deps deps.tsv --dest DIR
    python migrate_theory_hash_rekey.py verify-live --deps deps.tsv --hashes FILE

``plan`` opens every store read-only and writes nothing.  ``apply`` writes ONLY
under ``--dest``; the source stores are opened read-only, which is what makes
the untouched original the backup and re-running from it idempotent.
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
import time

import lmdb
import msgpack
import xxhash

HERE = os.path.dirname(os.path.abspath(__file__))
MLML = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
# Where to import the live hash function from.  Override with ISABELLE_RPC_PATH
# when running on a machine whose checkout is not the one carrying the change --
# the whole point is that this script and the running Isabelle share one
# implementation, so which copy is in use must be visible, not implicit.
sys.path.insert(0, os.environ.get("ISABELLE_RPC_PATH",
                                  os.path.join(MLML, "contrib", "Isabelle_RPC")))

from Isabelle_RPC_Host.theory_hash import theory_xxhash128       # noqa: E402
from Isabelle_RPC_Host.universal_key import xor_theory_prefix    # noqa: E402

# Tags whose key prefix is an XOR of constituent theory hashes rather than one
# theory's hash.  Mirrors EntityKind: THEOREM, INTRODUCTION_RULE,
# ELIMINATION_RULE, INDUCTION_RULE, CASE_SPLIT_RULE, EXPERIENCE.
XOR_TAGS = {0x02, 0x12, 0x22, 0x32, 0x42, 0x08}
EXPERIENCE_TAG = 0x08

# Record field positions in the stored msgpack array.  The codec is positional
# tail-append (Semantic_DB._decode), so a short record simply lacks the tail.
F_KIND, F_NAME = 0, 1
F_PROV, F_CONSTS = 4, 5
F_DEPS = 9

SEMANTICS_MAP_SIZE = 1 << 32     # 4 GiB, matching semantics.SEMANTICS_MAP_SIZE
VECTOR_MAP_SIZE = 1 << 36        # 64 GiB, matching semantic_embedding.VECTOR_MAP_SIZE
THEORY_HASH_MAP_SIZE = 1 << 30   # 1 GiB, matching open_theory_hash_store


def default_semantic_dir() -> str:
    from Isabelle_Semantic_Embedding._paths import semantic_DB_dir
    return semantic_DB_dir()


def default_theory_hash_dir() -> str:
    # Same expression as open_theory_hash_store.  NB a DIFFERENT platformdirs
    # root from the semantic databases, with no environment override, so
    # SEMANTIC_DB_DIR does NOT move theory_hash.lmdb -- hence --src-theory-hash.
    import platformdirs
    return platformdirs.user_cache_dir("Isabelle_Theory_Hash", "Qiyuan")


def is_persistent(h: bytes) -> bool:
    return h[0] & 1 == 0


# --------------------------------------------------------------------------
# the two theory-hash tables
# --------------------------------------------------------------------------

class Tables:
    """Old and new hash for every theory the dependency table holds.

    ``old`` exists only so G1 can prove the table's file paths, parent sets and
    parent ORDER reconstruct today's stored hashes.  It says nothing about the
    long name, which today's digest does not contain -- that is G4's job.
    """

    def __init__(self, deps_path: str):
        self.info: dict[str, tuple[str, list[str]]] = {}
        self.order: list[str] = []
        self.wip: set[str] = set()
        for line in open(deps_path, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if not p or p[0] != "DEP":
                continue
            if len(p) != 5:
                raise SystemExit(f"malformed dependency row (want 5 fields): {line!r}")
            name, loaded, path, parents = p[1], p[2], p[3], p[4]
            if name in self.info:
                raise SystemExit(f"duplicate theory long name in the table: {name}")
            if loaded != "L":
                self.wip.add(name)
                continue
            if not path:
                raise SystemExit(f"no .thy path for {name}")
            self.info[name] = (path, parents.split(",") if parents else [])
            self.order.append(name)

        self.old: dict[str, bytes] = {}
        self.new: dict[str, bytes] = {}
        sys.setrecursionlimit(100_000)
        for n in self.order:
            self._compute(n)

        self.by_old: dict[bytes, list[str]] = collections.defaultdict(list)
        for n, h in self.old.items():
            self.by_old[h].append(n)
        # A hash two theories share: reproducible, but on its own it does not
        # say which theory, so a record that carries nothing else dies on it.
        self.shared: set[bytes] = {h for h, ns in self.by_old.items() if len(ns) > 1}
        self.reproducible: set[bytes] = set(self.old.values())

    def _compute(self, n: str) -> bytes:
        if n in self.old:
            return self.old[n]
        if n not in self.info:
            raise SystemExit(
                f"{n} is a parent in the dependency table but has no row of its own"
                + (" (it is marked not loaded)" if n in self.wip else ""))
        path, parents = self.info[n]
        parent_old = [self._compute(p) for p in parents]
        with open(path, "rb") as f:
            body = f.read()
        # The retired algorithm: no name, and the LSB cleared by the caller.
        h = xxhash.xxh128()
        h.update(body)
        for ph in parent_old:
            h.update(ph)
        d = bytearray(h.digest())
        d[0] &= 0xFE
        self.old[n] = bytes(d)
        self.new[n] = theory_xxhash128(n, path, [self.new[p] for p in parents])
        return self.old[n]

    def name_of_old(self, h: bytes) -> str | None:
        """The single theory this old hash belongs to, or None when it is not
        reproducible or two theories share it."""
        ns = self.by_old.get(h)
        return ns[0] if ns is not None and len(ns) == 1 else None


# --------------------------------------------------------------------------
# gates that need only the tables
# --------------------------------------------------------------------------

def gate_g2(tab: Tables) -> int:
    """New hashes are injective, and no new hash collides with an old one still
    in use.  Either failure silently merges two theories."""
    problems = 0
    by_new: dict[bytes, list[str]] = collections.defaultdict(list)
    for n, h in tab.new.items():
        by_new[h].append(n)
    dup = {h: ns for h, ns in by_new.items() if len(ns) > 1}
    print(f"  G2  new-hash collisions              {len(dup)}")
    for h, ns in list(dup.items())[:10]:
        print(f"        {h.hex()}  {ns}")
    overlap = set(tab.new.values()) & tab.reproducible
    print(f"  G2  new hash equal to an old hash    {len(overlap)}")
    for h in list(overlap)[:10]:
        print(f"        {h.hex()}  new={by_new[h]}  old={tab.by_old[h]}")
    problems += len(dup) + len(overlap)
    return problems


def gate_g1(tab: Tables, stored: dict[bytes, str | None]) -> int:
    """Recomputing today's hash must reproduce the stored one, for every theory
    the store references and the image holds.

    This is what establishes that the dependency table's file paths, parent
    sets and parent ORDER are faithful.  It says nothing about the long name,
    which today's digest does not contain -- that is G4's job.

    Driven by NAME, not by hash: a theory whose content has changed since some
    records were written is referenced under BOTH generations, and the
    superseded hash cannot equal today's recomputation by construction.  What
    must hold is that today's hash is among the ones the store references.  The
    superseded hashes are counted, not treated as failures -- they are exactly
    the population §4's drop set is built from.

    Exhaustive over the referenced hashes, not over the constituent lists
    alone: thousands of theory names occur only as a name-addressed key prefix
    or a theory-status key.
    """
    by_name: dict[str, set[bytes]] = collections.defaultdict(set)
    unnamed = not_held = 0
    for h, name in stored.items():
        if not is_persistent(h):
            continue
        if name is None:
            unnamed += 1
            continue
        if name not in tab.old:
            not_held += 1
            continue
        by_name[name].add(h)
    checked = missing = superseded = 0
    for name, hs in by_name.items():
        checked += 1
        if tab.old[name] in hs:
            superseded += len(hs) - 1
        else:
            missing += 1
            if missing <= 10:
                print(f"        NOT REPRODUCED {name}: recomputed "
                      f"{tab.old[name].hex()}, store has "
                      f"{', '.join(sorted(x.hex() for x in hs))}")
    print(f"  G1  theories checked                 {checked}")
    print(f"  G1  today's hash not reproduced      {missing}")
    print(f"  G1  superseded generations referenced {superseded}")
    print(f"  G1  hashes with no name recoverable  {unnamed}")
    print(f"  G1  theory not held by the image     {not_held}")
    return missing


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------

class Classification:
    """Every key of semantics.lmdb, with the new key it takes or the reason it
    dies.  Built in two rounds because a rescue may only take a key that no
    ordinarily-migrated record already holds."""

    def __init__(self, tab: Tables, rescue_superseded: str):
        self.tab = tab
        self.rescue_superseded = rescue_superseded
        self.newkey: dict[bytes, bytes] = {}
        self.drop: dict[bytes, str] = {}
        self.rescued: dict[bytes, str] = {}
        self.stats: collections.Counter = collections.Counter()
        self.collisions: list[tuple[bytes, bytes, bytes]] = []
        self.copy_verbatim: list[bytes] = []
        # theory hash -> long name, for hashes the store references
        self.hash_names: dict[bytes, str | None] = {}

    # -- hash mapping ------------------------------------------------------

    def _map_hash(self, h: bytes, name: str | None) -> tuple[bytes | None, str]:
        """New hash for a constituent, plus why it failed.

        ``name`` is the long name the record itself carries for this hash, or
        None when the record carries no name (name-addressed and theory-status
        keys).  A name resolves a shared hash exactly; for a non-reproducible
        hash it identifies a superseded content generation.
        """
        if not is_persistent(h):
            return h, "wip"                      # WIP hashes are name-addressed already
        if h in self.tab.reproducible:
            if h not in self.tab.shared:
                return self.tab.new[self.tab.by_old[h][0]], "ok"
            if name is not None and name in self.tab.new:
                return self.tab.new[name], "rescued-shared"
            return None, "shared"
        if name is not None and name in self.tab.new:
            return self.tab.new[name], "superseded"
        return None, "unreproducible"

    # -- one entry ---------------------------------------------------------

    def classify(self, key: bytes, val: bytes) -> None:
        if len(key) < 16:
            self.copy_verbatim.append(key)       # the global counter, not a record
            self.stats["counter"] += 1
            return
        if len(key) == 16:
            self.hash_names.setdefault(key, None)
            # Theory-status records are never revived: see the module docstring.
            self._simple(key, key, b"", "theory-status", allow_rescue=False)
            return
        if key[16] in XOR_TAGS:
            self._xor(key, val)
            return
        self.hash_names.setdefault(key[:16], None)
        # A name-addressed key can never be an EXPERIENCE, so only `all` revives
        # it.  Reading the flag here is what makes `none` mean what it says.
        self._simple(key, key[:16], key[16:], "name-addressed",
                     allow_rescue=self.rescue_superseded == "all")

    def _simple(self, key: bytes, h: bytes, tail: bytes, what: str,
                allow_rescue: bool) -> None:
        """A key whose prefix IS one theory's hash and which carries no name."""
        new_h, why = self._map_hash(h, None)
        if new_h is not None:
            self.newkey[key] = new_h + tail
            self.stats[f"{what}: migrated"] += 1
            return
        if why == "unreproducible" and allow_rescue:
            # No name on the key itself; theory_hash.lmdb may still know one.
            name = self.hash_names.get(h)
            if name is not None and name in self.tab.new:
                self.rescued[key] = f"{what}: superseded generation, name from theory_hash.lmdb"
                self.stats[f"{what}: rescue candidate (superseded)"] += 1
                return
        self.drop[key] = f"{what}: {why}"
        self.stats[f"{what}: dropped ({why})"] += 1

    def _xor(self, key: bytes, val: bytes) -> None:
        vals = msgpack.unpackb(val)
        consts = vals[F_CONSTS] if len(vals) > F_CONSTS else None
        if consts is None:
            # A legacy record, predating the constituent list: nothing to
            # rewrite and no way to recompute the prefix.  Measured: none exist
            # in the authoritative store.
            self.drop[key] = "xor: no constituent list"
            self.stats["xor: dropped (no constituent list)"] += 1
            return
        # An EMPTY list is a different thing entirely and is legitimate: a few
        # experiences name no theory at all, their prefix is the all-zero
        # xor_theory_prefix([]), and the experience index files them under its
        # _GLOBAL sentinel bucket.  Such a record has no theory hash to carry
        # forward, so it keeps its exact key.
        names = [n if isinstance(n, str) else n.decode() for n, _ in consts]
        hashes = [bytes(h) for _, h in consts]
        for n, h in zip(names, hashes):
            if is_persistent(h):
                self.hash_names.setdefault(h, n)
        new_hashes: list[bytes] = []
        superseded = False
        for n, h in zip(names, hashes):
            new_h, why = self._map_hash(h, n)
            if new_h is None:
                self.drop[key] = f"xor: constituent {n} {why}"
                self.stats[f"xor: dropped ({why})"] += 1
                return
            if why == "rescued-shared":
                self.stats["xor: constituent rescued by its recorded name (shared hash)"] += 1
            elif why == "superseded":
                superseded = True
            new_hashes.append(new_h)
        new = xor_theory_prefix(new_hashes) + key[16:]
        if not superseded:
            self.newkey[key] = new
            self.stats["xor: migrated"] += 1
            return
        is_exp = key[16] == EXPERIENCE_TAG
        want = (self.rescue_superseded == "all"
                or (self.rescue_superseded == "experiences" and is_exp))
        kind = "experience" if is_exp else "ordinary record"
        if want:
            self.rescued[key] = f"xor: superseded generation re-pointed by name ({kind})"
            self.stats[f"xor: rescue candidate (superseded, {kind})"] += 1
        else:
            self.drop[key] = f"xor: constituent from a superseded generation ({kind})"
            self.stats[f"xor: dropped (superseded, {kind})"] += 1

    # -- round two ---------------------------------------------------------

    def settle_rescues(self, src_txn) -> None:
        """A rescue may only take a key no ordinarily-migrated record holds.

        A revived record that lands on an occupied key is a duplicate of the
        theory's CURRENT generation -- exactly the case D5 was narrowed to
        avoid -- and is dropped.  One that lands on a free key is asserting an
        entity the current content may no longer have; the report says how many
        of each there are, so the choice is made on numbers, not on a guess.
        """
        taken = set(self.newkey.values())
        for key, why in self.rescued.items():
            new = self._rescue_key(key, src_txn)
            if new is None:
                self.drop[key] = why + " -- but no name resolved after all"
                self.stats["rescue abandoned (no name)"] += 1
                continue
            if new in taken:
                self.drop[key] = why + " -- duplicate of a live record"
                self.stats["rescue dropped (duplicate of a live record)"] += 1
                continue
            self.newkey[key] = new
            taken.add(new)
            self.stats["rescue applied (fresh key)"] += 1

    def _rescue_key(self, key: bytes, src_txn) -> bytes | None:
        if len(key) > 16 and key[16] in XOR_TAGS:
            vals = msgpack.unpackb(src_txn.get(key))
            consts = vals[F_CONSTS]
            new_hashes = []
            for n, h in consts:
                n = n if isinstance(n, str) else n.decode()
                new_h, _ = self._map_hash(bytes(h), n)
                if new_h is None:
                    return None
                new_hashes.append(new_h)
            return xor_theory_prefix(new_hashes) + key[16:]
        name = self.hash_names.get(key[:16] if len(key) > 16 else key)
        if name is None or name not in self.tab.new:
            return None
        return self.tab.new[name] + (key[16:] if len(key) > 16 else b"")

    def detect_collisions(self) -> None:
        """Two old keys landing on one new key would silently lose a record."""
        seen: dict[bytes, bytes] = {}
        for old, new in self.newkey.items():
            if new in seen:
                self.collisions.append((seen[new], old, new))
            else:
                seen[new] = old


# --------------------------------------------------------------------------
# value rewriting
# --------------------------------------------------------------------------

def rewrite_value(val: bytes, cls: Classification) -> bytes:
    """Rewrite the four fields that carry universal keys or theory hashes.

    Field order is the point: the constituent list is rewritten first and the
    key's new XOR prefix is computed from the rewritten list (in the caller),
    never from a separately maintained copy.  Everything else is left as it
    came off disk, and msgpack round-trips byte for byte, so an untouched field
    really is untouched.
    """
    vals = list(msgpack.unpackb(val))
    changed = False

    if len(vals) > F_CONSTS and vals[F_CONSTS]:
        out = []
        for n, h in vals[F_CONSTS]:
            name = n if isinstance(n, str) else n.decode()
            new_h, _ = cls._map_hash(bytes(h), name)
            assert new_h is not None, f"constituent {name} unmappable at rewrite time"
            out.append([n, new_h])
        vals[F_CONSTS] = out
        changed = True

    if len(vals) > F_PROV and isinstance(vals[F_PROV], dict):
        prov = dict(vals[F_PROV])
        luk = prov.get("locale_uk")
        if luk is not None:
            new_h, _ = cls._map_hash(bytes(luk[:16]), None)
            if new_h is not None:
                prov["locale_uk"] = new_h + bytes(luk[16:])
        tuk = prov.get("template_uk")
        if tuk is not None:
            # XOR-shaped, so no prefix substitution is possible.  A value that
            # resolves to a live record follows that record; one that already
            # dangles is left exactly as it is, to be repaired later from
            # Isabelle rather than by reverse-engineering names here.
            new_t = cls.newkey.get(bytes(tuk))
            if new_t is not None:
                prov["template_uk"] = new_t
        vals[F_PROV] = prov
        changed = True

    if len(vals) > F_DEPS and vals[F_DEPS]:
        out = []
        for d in vals[F_DEPS]:
            d = bytes(d)
            new_h, _ = cls._map_hash(d[:16], None) if len(d) >= 16 else (None, "")
            out.append(new_h + d[16:] if new_h is not None else d)
        vals[F_DEPS] = out
        changed = True

    if not changed:
        return val
    out_val = msgpack.packb(vals)
    assert out_val is not None
    return out_val


# --------------------------------------------------------------------------
# passes over the stores
# --------------------------------------------------------------------------

def load_theory_hash_names(path: str) -> dict[bytes, str]:
    """hash -> long name, from the diagnostic cache.  It is the only place a
    name-addressed key's theory name can come from."""
    if not os.path.isdir(path):
        print(f"  (no theory_hash.lmdb at {path}; name-addressed rescues disabled)")
        return {}
    env = lmdb.open(path, readonly=True, lock=False)
    out = {}
    with env.begin() as t:
        for k, v in t.cursor():
            k = bytes(k)
            if len(k) != 16 or not v:
                continue
            m = msgpack.unpackb(bytes(v))
            name = m[0] if isinstance(m, (list, tuple)) else m
            out[k] = name if isinstance(name, str) else name.decode()
    env.close()
    return out


def classify_store(sem_path: str, tab: Tables, rescue: str,
                   thy_names: dict[bytes, str]) -> Classification:
    cls = Classification(tab, rescue)
    env = lmdb.open(sem_path, readonly=True, lock=False)
    with env.begin() as t:
        # Round 0: learn every referenced theory hash and the name (if any) the
        # store knows for it, before any classification decision needs one.
        for k, v in t.cursor():
            k = bytes(k)
            if len(k) < 16 or not v:
                continue
            if len(k) == 16:
                cls.hash_names.setdefault(k, thy_names.get(k))
            elif k[16] in XOR_TAGS:
                consts = msgpack.unpackb(bytes(v))[F_CONSTS] or []
                for n, h in consts:
                    h = bytes(h)
                    if is_persistent(h):
                        cls.hash_names[h] = n if isinstance(n, str) else n.decode()
            else:
                cls.hash_names.setdefault(k[:16], thy_names.get(k[:16]))
        for h, n in list(cls.hash_names.items()):
            if n is None and h in thy_names:
                cls.hash_names[h] = thy_names[h]
        for k, v in t.cursor():
            cls.classify(bytes(k), bytes(v))
        cls.settle_rescues(t)
    cls.detect_collisions()
    env.close()
    return cls


def build_semantics(src: str, dest: str, cls: Classification) -> int:
    written = 0
    src_env = lmdb.open(src, readonly=True, lock=False)
    dst_env = lmdb.open(dest, map_size=SEMANTICS_MAP_SIZE)
    with src_env.begin() as st, dst_env.begin(write=True) as dt:
        for k, v in st.cursor():
            k = bytes(k); v = bytes(v)
            if len(k) < 16:
                dt.put(k, v)
                written += 1
                continue
            new = cls.newkey.get(k)
            if new is None:
                continue
            out = v if len(k) == 16 or not v else rewrite_value(v, cls)
            if not dt.put(new, out, overwrite=False):
                raise SystemExit(f"new key already occupied: {new.hex()} (from {k.hex()})")
            written += 1
    dst_env.sync()
    dst_env.close()
    src_env.close()
    return written


def build_vectors(src: str, dest: str, cls: Classification) -> tuple[int, int]:
    """Keys only; values -- including the empty-value vector tombstones -- are
    copied verbatim.  Entity keys ride the per-record map, since their prefixes
    are XORs and not theory hashes; the 16-byte embed-status keys are theory
    hashes and ride the theory table, which the record map already covers."""
    written = dropped = 0
    src_env = lmdb.open(src, readonly=True, lock=False)
    dst_env = lmdb.open(dest, map_size=VECTOR_MAP_SIZE)
    src_txn = src_env.begin()
    dt = dst_env.begin(write=True)
    n = 0
    for k, v in src_txn.cursor():
        k = bytes(k); v = bytes(v)
        new = cls.newkey.get(k)
        if new is None:
            dropped += 1
            continue
        if not dt.put(new, v, overwrite=False):
            raise SystemExit(f"vector key already occupied: {new.hex()}")
        written += 1
        n += 1
        if n % 200_000 == 0:
            dt.commit()
            dt = dst_env.begin(write=True)
            print(f"    ... {n} vectors", flush=True)
    dt.commit()
    src_txn.abort()
    dst_env.sync()
    dst_env.close()
    src_env.close()
    return written, dropped


def build_theory_hash(src: str, dest: str, tab: Tables) -> tuple[int, int, int, int]:
    """Re-key the hash -> name diagnostic cache.

    Two ways entries merge, and both are counted rather than left silent.  A
    collapsed group is two theories under one hash, so the single entry can
    only follow one successor.  Superseded content generations are the reverse
    -- one name under several hashes, all of which now key to that name's one
    new hash; measured, this is over a quarter of the store.  The destination
    key comes from the NAME, so the merge is inherent; what must not happen is
    the run reporting more entries than it wrote, which is why this writes with
    overwrite=False and counts the refusals.
    """
    mapped = dropped = collapsed = 0
    src_env = lmdb.open(src, readonly=True, lock=False)
    dst_env = lmdb.open(dest, map_size=THEORY_HASH_MAP_SIZE)
    with src_env.begin() as st, dst_env.begin(write=True) as dt:
        for k, v in st.cursor():
            k = bytes(k); v = bytes(v)
            if len(k) != 16 or not is_persistent(k):
                dt.put(k, v)
                mapped += 1
                continue
            m = msgpack.unpackb(v)
            name = m[0] if isinstance(m, (list, tuple)) else m
            name = name if isinstance(name, str) else name.decode()
            if name not in tab.new:
                dropped += 1
                continue
            if k in tab.shared:
                collapsed += 1
            # The current generation must win over a superseded one, so it
            # overwrites and the others only fill a gap.
            dt.put(tab.new[name], v, overwrite=(k == tab.old.get(name)))
            mapped += 1
    written = dst_env.stat()["entries"]
    dst_env.sync()
    dst_env.close()
    src_env.close()
    return written, dropped, collapsed, mapped - written


# --------------------------------------------------------------------------
# gates over the built store
# --------------------------------------------------------------------------

def reference_census(sem_path: str, drop_keys: 'set[bytes]') -> tuple[
        collections.Counter, collections.Counter]:
    """Dangling references in a store, and references into a set of keys.

    Run over the SOURCE, this is G6's baseline.  The second counter is what
    makes the baseline usable: a reference whose target is about to be dropped
    necessarily dangles afterwards, so the destination's dangling count MUST
    exceed the source's by that much.  Comparing the two raw numbers, as an
    earlier revision of the plan specified, would fail every correct run.
    """
    env = lmdb.open(sem_path, readonly=True, lock=False)
    dangling: collections.Counter = collections.Counter()
    into_drop: collections.Counter = collections.Counter()
    with env.begin() as t:
        live = {bytes(k) for k, _ in t.cursor()}
        for k, v in t.cursor():
            k = bytes(k); v = bytes(v)
            if len(k) <= 16 or not v:
                continue
            vals = msgpack.unpackb(v)
            targets = []
            if len(vals) > F_PROV and isinstance(vals[F_PROV], dict):
                for field in ("locale_uk", "template_uk"):
                    u = vals[F_PROV].get(field)
                    if u is not None:
                        targets.append((field, bytes(u)))
            if len(vals) > F_DEPS and vals[F_DEPS]:
                targets += [("deps", bytes(d)) for d in vals[F_DEPS]]
            for field, u in targets:
                if u not in live:
                    dangling[field] += 1
                elif u in drop_keys:
                    into_drop[field] += 1
    env.close()
    return dangling, into_drop


def gate_g5_g6(dest_sem: str, src_sem: str, cls: Classification, tab: Tables) -> int:
    """G5: no old hash survives anywhere -- not as a key prefix, not as a
    16-byte key, not inside theory_constituents / locale_uk / deps -- and every
    persistent constituent's recorded hash is the one its recorded NAME maps to.

    That last check is the only non-circular thing here.  Recomputing the XOR
    prefix from the constituent list proves nothing on its own: the list and
    the key came out of the same `_map_hash` calls, so they agree even when the
    hash is wrong.  Constituents are stored as (long name, hash) pairs, so the
    record's own name can cross-examine its own hash for free -- and it catches
    a real hole, since `_map_hash` resolves through the hash and discards the
    name the record carries.

    Two exemptions, both listed rather than passed silently.  The dangling
    template_uk values are left byte for byte by design.  And a locale_uk or
    deps entry whose target theory was itself dropped has nowhere to point: the
    reference dangles either way, so its stale prefix is reported separately
    from the failures that must be zero.

    G6: dangling-reference counts must not grow beyond what dropping records
    forces.  G5 proves nothing stale survived; G6 proves nothing was pointed
    somewhere new and wrong.
    """
    old_hashes = tab.reproducible
    new_hashes = set(tab.new.values())
    # A reproducible old hash that still maps to nothing is one two theories
    # share: its records are gone, so a reference carrying it dangles whatever
    # we do.  (A hash that was never reproducible is not in old_hashes at all;
    # references to those are the pre-existing dangling population G6 counts.)
    unmapped = tab.shared
    env = lmdb.open(dest_sem, readonly=True, lock=False)
    bad = collections.Counter()
    expected = collections.Counter()
    dangling = collections.Counter()
    live: set[bytes] = set()
    with env.begin() as t:
        for k, _v in t.cursor():
            live.add(bytes(k))
        for k, v in t.cursor():
            k = bytes(k); v = bytes(v)
            if len(k) < 16:
                continue
            if len(k) == 16:
                if k in old_hashes and k not in new_hashes:
                    bad["theory-status key is an old hash"] += 1
                continue
            if k[16] not in XOR_TAGS and k[:16] in old_hashes and k[:16] not in new_hashes:
                bad["name-addressed key prefix is an old hash"] += 1
            if not v:
                continue
            vals = msgpack.unpackb(v)
            if len(vals) > F_CONSTS and vals[F_CONSTS]:
                for n, h in vals[F_CONSTS]:
                    h = bytes(h)
                    name = n if isinstance(n, str) else n.decode()
                    if h in old_hashes and h not in new_hashes:
                        bad["theory_constituents holds an old hash"] += 1
                    if is_persistent(h) and tab.new.get(name) != h:
                        bad["constituent's name and hash are different theories"] += 1
                if k[16] in XOR_TAGS:
                    want = xor_theory_prefix([bytes(h) for _n, h in vals[F_CONSTS]])
                    if want != k[:16]:
                        bad["XOR prefix disagrees with its constituents"] += 1
            if len(vals) > F_PROV and isinstance(vals[F_PROV], dict):
                luk = vals[F_PROV].get("locale_uk")
                if luk is not None:
                    luk = bytes(luk)
                    if luk[:16] in old_hashes and luk[:16] not in new_hashes:
                        (expected if luk[:16] in unmapped else bad)[
                            "locale_uk prefix is an old hash"] += 1
                    if luk not in live:
                        dangling["locale_uk"] += 1
                tuk = vals[F_PROV].get("template_uk")
                if tuk is not None and bytes(tuk) not in live:
                    dangling["template_uk"] += 1
            if len(vals) > F_DEPS and vals[F_DEPS]:
                for d in vals[F_DEPS]:
                    d = bytes(d)
                    if d[:16] in old_hashes and d[:16] not in new_hashes:
                        (expected if d[:16] in unmapped else bad)[
                            "deps prefix is an old hash"] += 1
                    if d not in live:
                        dangling["deps"] += 1
    env.close()
    print("  G5  old hashes surviving in the new store:")
    if not bad:
        print("        none")
    for kk, n in bad.most_common():
        print(f"        {kk:<45} {n}")
    if expected:
        print("  G5  stale prefixes on references whose target theory was dropped"
              " (expected, they dangle either way):")
        for kk, n in expected.most_common():
            print(f"        {kk:<45} {n}")
    print("  G6  measuring the source's dangling references ...", flush=True)
    src_dangling, into_drop = reference_census(src_sem, set(cls.drop))
    print("  G6  dangling references          source  + into the drop set "
          "=  allowed   actual")
    grew = 0
    for kk in ("locale_uk", "deps", "template_uk"):
        allowed = src_dangling[kk] + into_drop[kk]
        over = max(0, dangling[kk] - allowed)
        grew += over
        print(f"        {kk:<20} {src_dangling[kk]:>8} {into_drop[kk]:>16} "
              f"{allowed:>10} {dangling[kk]:>8}"
              f"{'   !! GREW BY ' + str(over) if over else ''}")
    print("        (a reference into a dropped record must dangle afterwards,"
          " which is why the allowance is not the source count alone)")
    return sum(bad.values()) + grew


def gate_counts(dest: str, src: str, src_th: str, vec_name: str,
                cls: Classification) -> int:
    """G3: the destination must hold exactly what the classification says.

    This is the gate the whole `gates` subcommand rests on, because every other
    check over the destination is a predicate on whatever keys happen to be
    there rather than a comparison against the intended set.  Without it a
    truncated build passes: `build_vectors` is the one non-atomic builder --
    it commits every 200,000 entries over an hours-long run -- so a kill leaves
    a valid, self-consistent, incomplete environment, and a subset test over it
    only looks cleaner the more data is missing.  It also catches a second
    `apply` appending into a destination a previous run had already filled.
    """
    problems = 0

    def count(path: str) -> int | None:
        if not os.path.isdir(path):
            return None
        env = lmdb.open(path, readonly=True, lock=False)
        n = env.stat()["entries"]
        env.close()
        return n

    def check(label: str, path: str, want: int) -> None:
        nonlocal problems
        got = count(path)
        if got is None:
            print(f"  G3  {label:<30} MISSING at {path}")
            problems += 1
            return
        print(f"  G3  {label:<30} {got:>9} (expected {want})"
              f"{'   !! MISMATCH' if got != want else ''}")
        if got != want:
            problems += 1

    check("semantics.lmdb entries", os.path.join(dest, "semantics.lmdb"),
          len(cls.newkey) + len(cls.copy_verbatim))

    # Recomputed from the source rather than taken from build_vectors' return
    # value, so that `gates` can check a destination this process did not build.
    src_vec = lmdb.open(os.path.join(src, vec_name), readonly=True, lock=False)
    with src_vec.begin() as t:
        want_vec = sum(1 for k, _ in t.cursor() if bytes(k) in cls.newkey)
    src_vec.close()
    check("vector store entries", os.path.join(dest, vec_name), want_vec)

    dest_th = os.path.join(dest, "theory_hash.lmdb")
    if count(dest_th) is None:
        print(f"  G3  {'theory_hash.lmdb':<30} MISSING at {dest_th}")
        problems += 1
    else:
        print(f"  G3  {'theory_hash.lmdb entries':<30} {count(dest_th):>9}"
              f" (from {count(os.path.join(src_th, 'theory_hash.lmdb'))} source"
              f" entries; names merge, so fewer is expected)")
    return problems


def gate_vector_keys(dest_sem: str, dest_vec: str) -> int:
    """Every key in the migrated vector store must name a key in the migrated
    record store.

    Weak on its own -- both stores are keyed from the same map, so the subset
    holds mechanically for anything `apply` builds. It has teeth only over a
    destination this process did not build, e.g. a half-swapped pair. The
    counting gate above is what actually guards the vector store.
    """
    sem = lmdb.open(dest_sem, readonly=True, lock=False)
    keys = set()
    with sem.begin() as t:
        for k, _ in t.cursor():
            keys.add(bytes(k))
    sem.close()
    vec = lmdb.open(dest_vec, readonly=True, lock=False)
    orphan = 0
    with vec.begin() as t:
        for k, _ in t.cursor():
            if bytes(k) not in keys:
                orphan += 1
    vec.close()
    print(f"  G4b vector keys with no record       {orphan}")
    return orphan


def verify_live(tab: Tables, hashes_path: str) -> int:
    """G4's live half: the hashes Isabelle mints under the new code must equal
    the ones this script computed, over the WHOLE table rather than a sample --
    this is the only check that the two implementations agree.

    `extra` is REPORTED, NOT RETURNED.  The G4 session is the dependency table's
    image plus `Isabelle_RPC`, so it necessarily holds theories the table does
    not -- `Performant_Isabelle_ML`, `Remote_Procedure_Calling` and the dump
    theory itself at minimum.  Counting those as failures would make the one
    gate that proves the live ML and this script agree cry wolf on a correct
    run, which is how an operator learns to ignore an exit code.
    """
    seen = mism = missing = extra = 0
    got: dict[str, str] = {}
    for line in open(hashes_path, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if not p or p[0] != "HASH":
            continue
        got[p[1]] = p[2]
    for n, h in tab.new.items():
        if n not in got:
            missing += 1
            continue
        seen += 1
        if got[n] != h.hex():
            mism += 1
            if mism <= 10:
                print(f"        MISMATCH {n}: live {got[n]} script {h.hex()}")
    for n in got:
        if n not in tab.new:
            extra += 1
    print(f"  G4  theories compared                {seen}")
    print(f"  G4  mismatches                       {mism}")
    print(f"  G4  in the table, absent from Isabelle {missing}")
    print(f"  G4  from Isabelle, absent in the table {extra}   (expected: the "
          f"dump's session holds Isabelle_RPC, the table's image does not)")
    return mism + missing


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def report(cls: Classification, total: int) -> int:
    """Print the classification, and return the problems in it.

    The count identity below is close to a tautology -- every source key lands
    in exactly one bucket by construction -- but `total` comes from a second,
    independent open of the store, so a disagreement means something wrote to
    the source between the two, which is the "no process holds semantics.lmdb"
    precondition being violated.  Worth an exit code for that alone.
    """
    print("\nclassification")
    for kk, n in sorted(cls.stats.items()):
        print(f"  {kk:<62} {n:>8}")
    migrated = len(cls.newkey) + len(cls.copy_verbatim)
    print(f"\n  migrated (records + counter)      {migrated:>8}")
    print(f"  dropped                           {len(cls.drop):>8} "
          f"({100.0 * len(cls.drop) / total:.3f}%)")
    print(f"  total                             {migrated + len(cls.drop):>8} "
          f"(store holds {total})")
    problems = 0
    if migrated + len(cls.drop) != total:
        print("  !! G3 FAILED: migrated + dropped does not equal the store's entry count")
        problems += 1
    print(f"  new-key collisions                {len(cls.collisions):>8}")
    for a, b, new in cls.collisions[:10]:
        print(f"        {a.hex()} and {b.hex()} both -> {new.hex()}")
    by_reason = collections.Counter(cls.drop.values())
    print("\ndropped, by reason")
    for kk, n in by_reason.most_common():
        print(f"  {kk:<62} {n:>8}")
    return problems


def write_drop_list(cls: Classification, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("# key\treason\n")
        for k, why in sorted(cls.drop.items()):
            f.write(f"{k.hex()}\t{why}\n")
    print(f"\nwrote the explicit drop-key list to {path} ({len(cls.drop)} keys)")


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["plan", "apply", "gates", "verify-live"])
    ap.add_argument("--deps", required=True, help="dependency table dumped from the image")
    ap.add_argument("--src", default=None, help="source semantic DB dir")
    ap.add_argument("--src-theory-hash", default=None)
    ap.add_argument("--dest", default=None, help="staging dir to build into")
    ap.add_argument("--hashes", default=None, help="verify-live: the (long name, hash) dump")
    ap.add_argument("--rescue-superseded", choices=["none", "experiences", "all"],
                    default="experiences")
    ap.add_argument("--drop-list", default=None)
    args = ap.parse_args()

    src = args.src or default_semantic_dir()
    src_th = args.src_theory_hash or default_theory_hash_dir()
    sem_src = os.path.join(src, "semantics.lmdb")

    t0 = time.time()
    print(f"building the theory-hash tables from {args.deps} ...", flush=True)
    tab = Tables(args.deps)
    print(f"  {len(tab.old)} loaded theories, {len(tab.wip)} not loaded, "
          f"{len(tab.shared)} shared old hashes, {time.time() - t0:.1f}s")

    if args.command == "verify-live":
        if not args.hashes:
            raise SystemExit("verify-live needs --hashes")
        sys.exit(1 if verify_live(tab, args.hashes) else 0)

    print("\ngates over the tables")
    problems = gate_g2(tab)

    thy_names = load_theory_hash_names(os.path.join(src_th, "theory_hash.lmdb"))
    print(f"  theory_hash.lmdb knows {len(thy_names)} hash -> name entries")

    print("\nclassifying the store ...", flush=True)
    cls = classify_store(sem_src, tab, args.rescue_superseded, thy_names)
    problems += gate_g1(tab, cls.hash_names)

    env = lmdb.open(sem_src, readonly=True, lock=False)
    total = env.stat()["entries"]
    env.close()
    problems += report(cls, total)
    if args.drop_list:
        write_drop_list(cls, args.drop_list)

    if args.command == "plan":
        print(f"\n{problems} gate problem(s) before any write.")
        sys.exit(1 if problems or cls.collisions else 0)

    if not args.dest:
        raise SystemExit("apply/gates need --dest")
    dest_sem = os.path.join(args.dest, "semantics.lmdb")
    if args.command == "gates" and not os.path.isdir(dest_sem):
        raise SystemExit(f"nothing to gate: no semantics.lmdb under {args.dest}")

    # Every vector store, not the first one os.listdir happens to yield.  The
    # package supports several models; migrating one and silently leaving the
    # rest old-keyed would orphan all of their entries after the swap.
    vec_names = sorted(d for d in os.listdir(src)
                       if d.startswith("vector_") and d.endswith(".lmdb"))
    if not vec_names:
        raise SystemExit(f"no vector_*.lmdb in {src}")
    if len(vec_names) > 1:
        raise SystemExit(
            f"{len(vec_names)} vector stores in {src} ({', '.join(vec_names)}). "
            "This script migrates one; extend it before running here, rather "
            "than leaving the others keyed to the old scheme.")
    vec_name = vec_names[0]

    if args.command == "apply":
        if problems or cls.collisions:
            raise SystemExit(f"refusing to write: {problems} gate problem(s), "
                             f"{len(cls.collisions)} collision(s)")
        if os.path.isdir(args.dest) and os.listdir(args.dest):
            raise SystemExit(
                f"--dest {args.dest} is not empty. Building into a populated "
                "directory can leave two generations of records side by side, "
                "each self-consistent, which every gate downstream would pass. "
                "Remove it and re-run from the untouched source.")
        os.makedirs(args.dest, exist_ok=True)
        if not args.drop_list:
            # Never leave a run with no record of what it decided to drop.  The
            # untouched source keeps the records themselves (D7); this keeps the
            # list of which ones, and why -- the input to any later top-up.
            write_drop_list(cls, os.path.join(args.dest, "dropped_keys.tsv"))
        print("\nbuilding the new semantics.lmdb ...", flush=True)
        n = build_semantics(sem_src, dest_sem, cls)
        print(f"  wrote {n} entries")
        print("building the new vector store ...", flush=True)
        w, d = build_vectors(os.path.join(src, vec_name),
                             os.path.join(args.dest, vec_name), cls)
        print(f"  wrote {w}, dropped {d}")
        print("building the new theory_hash.lmdb ...", flush=True)
        w, d, c, m = build_theory_hash(os.path.join(src_th, "theory_hash.lmdb"),
                                       os.path.join(args.dest, "theory_hash.lmdb"), tab)
        print(f"  wrote {w}, dropped {d}; {c} came from a collapsed group and could "
              f"only follow one of the two successors, and {m} more merged because "
              f"several content generations of one name now key to one hash")

    print("\ngates over the built store")
    problems += gate_counts(args.dest, src, src_th, vec_name, cls)
    problems += gate_g5_g6(dest_sem, sem_src, cls, tab)
    problems += gate_vector_keys(dest_sem, os.path.join(args.dest, vec_name))
    print(f"\n{problems} gate problem(s).")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
