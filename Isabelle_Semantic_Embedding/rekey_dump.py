"""The entity dump of the universal-key migration
(BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md §B.3).

``Semantic_Store.dump_entities`` on the Isabelle side re-enumerates a theory cone
with the REPAIRED universal keys and sends one batch per theory here.  This module
appends each batch to a scratch LMDB of its own -- ``semantics.rekey-dump.lmdb``,
beside the live store but never it.  Nothing here reads or writes ``semantics.lmdb``,
any vector store, or ``experience_index.lmdb``; the join (§B.5-B.7) is what brings
the two together, and this dump is the only source it is allowed to trust for the
new keys.

Store layout
------------

Two record shapes, told apart by key length exactly as the live store tells them
apart: a universal key of an entity is at least 17 bytes (16-byte prefix, 1-byte kind
tag, payload), a theory key is exactly the 16-byte theory hash.

* **entity**, key = the new universal key::

      [ [name, kind, position, constituents, prop, theory_longname], ... ]

  A LIST because two theories can produce one key: ``enumerate_entries`` deduplicates
  within a theory only, and the cone's theories run as parallel futures, so which of
  them wrote first is a scheduling accident.  Both records are kept and the collision
  counted; such a key is ambiguous and the join must not fill from it (§B.3).
  ``position`` is ``[file, line, byte column]`` or ``None``; ``constituents`` is the
  sorted ``[theory long name, 16-byte theory hash]`` list the key's prefix was XORed
  from; ``prop`` is the proposition, which §B.6 compares against a candidate old
  record's ``expr``.

  ``name`` and ``prop`` are stored in **Unicode**, converted here by
  ``pretty_unicode`` exactly as the collection path converts them
  (``semantic_interpretation.py:1249-1250``) before they become ``Record.name`` /
  ``Record.expr``.  Without it the join would compare ASCII symbol notation against
  the store's Unicode: measured over the whole corpus, 87.0 % of records have a
  non-ASCII ``expr`` and 4.2 % a non-ASCII ``name``, so §B.6's divergence rule would
  rewrite nearly every ``expr`` and drop nearly every vector, and the divergence
  count it designates as the leak detector for the one-to-one rule would saturate and
  carry no signal.  ``position`` is deliberately NOT converted, for the reason
  ``semantic_interpretation.py:1251-1253`` states: it is a filesystem path, and a
  literal ``\\<...>`` inside one would be rewritten into a symbol.

  This gives the dump the symbol table as a precondition **in the RPC host's own
  environment**: ``pretty_unicode`` reads ``$ISABELLE_HOME/etc/symbols`` and refuses
  to fall back to identity, so a host started without ``ISABELLE_HOME`` and without
  ``isabelle`` on ``PATH`` kills the sweep on its first theory.  That is the right
  failure -- silently storing ASCII is the defect above -- and it is not a new
  dependency for a host that has ever served collection, which converts the same two
  fields.

* **theory completion**, key = the theory's own 16-byte key::

      [theory_longname, enumerated, theory_file, tie_break_degraded, line_mismatch]

  Written LAST in the same transaction as the theory's entities, so a theory whose
  transaction did not commit leaves no completion record and the join sees the dump
  is short (§B.3: without them a short dump is undetectable, since leftovers are
  *defined* as whatever the dump did not map).  ``theory_file`` is the theory's own
  source path, folded by ``Entity_Position.portable_path`` -- the same function that
  wrote the file component of every stored position, so §B.6's discriminator compares
  like with like.  The last two fields say how far this theory's positions can be
  trusted; its entities are dumped either way.

Not idempotent, and there is no resume (D17).  Running the dump twice over one scratch
store appends every record a second time and makes every key look ambiguous, so
``dump_preflight`` refuses to start against a store that already exists, and the
handler refuses a theory it has already seen.

**The guard lives here, not in the driver.** The driver is not the process that
writes: an externally launched RPC host outlives it (``RPC.ML``'s contract -- with
``RPC_Host`` set "Isabelle only connects", and with it unset Isabelle forks an
ephemeral host of its own, a third process).  A path test in the driver therefore
cannot see this module's cached environment, and cannot even name the directory it
opened, since ``semantic_DB_dir()`` is re-read per process.  Measured: after the
documented "move it aside and start over" recovery a rerun against a live host writes
into the moved-aside directory, and after "delete it" into an unlinked inode -- while
a fresh driver process reports an empty dump and exits 0.  Hence ``dump_preflight``
and ``dump_scan``: both run where the environment is, and the driver only prints what
they return.

Everything in this module is scaffolding for one migration and is to be deleted when
Part B completes, together with the ML that calls it.
"""

import os
import threading
from typing import Any

import lmdb
import msgpack
from Isabelle_RPC_Host import Connection, isabelle_remote_procedure
from Isabelle_RPC_Host.unicode import pretty_unicode

from ._paths import semantic_DB_dir
from .semantics import SEMANTICS_MAP_SIZE

DUMP_NAME = "semantics.rekey-dump.lmdb"

_env: lmdb.Environment | None = None
# The inode the environment was opened on, so that a directory renamed or unlinked
# underneath a live host is caught on the next theory instead of swallowing the run.
_env_ino: int | None = None
_env_lock = threading.Lock()


def dump_path() -> str:
    """Where the scratch dump lives: beside the live store, under SEMANTIC_DB_DIR."""
    return os.path.join(semantic_DB_dir(), DUMP_NAME)


def _ensure_env() -> lmdb.Environment:
    """The scratch environment, opened once per process.

    py-lmdb refuses a second open of a path this process already holds, so the
    environment is a module singleton -- the same discipline ``_Semantic_DB._env``
    follows.  ``map_size`` is the live store's: that store holds every LLM
    interpretation in 44 % of it and this one holds none, carrying propositions and
    constituent lists instead (§B.3).  Measured by replaying the real corpus into this
    record shape: 1.085 GiB, 27 % of the ceiling.  Exceeding it raises
    ``MapFullError``, which aborts the transaction cleanly."""
    global _env, _env_ino
    if _env is None:
        with _env_lock:
            if _env is None:
                import atexit
                os.makedirs(semantic_DB_dir(), exist_ok=True)
                _env = lmdb.open(dump_path(), map_size=SEMANTICS_MAP_SIZE)
                _env_ino = os.stat(dump_path()).st_ino
                atexit.register(_close)
    return _env


def _close() -> None:
    global _env, _env_ino
    if _env is not None:
        _env.close()
        _env = None
        _env_ino = None


def _check_still_ours() -> None:
    """Refuse if the directory this host opened is no longer the one at the path.

    ``lmdb.open`` holds the data file by fd and mmap, which neither rename nor unlink
    disturbs, so without this a run that continues after the operator moved the
    directory aside lands somewhere nobody will look."""
    try:
        ino = os.stat(dump_path()).st_ino
    except OSError:
        ino = None
    if ino != _env_ino:
        raise RuntimeError(
            f"the dump directory {dump_path()} is no longer the one this RPC host has "
            f"open -- it was renamed or deleted underneath a running host, and every "
            f"write since then went to the old one.  Restart the RPC host, then start "
            f"the dump again from an empty scratch store")


@isabelle_remote_procedure("Semantic_Store.dump_entities")
async def _dump_entities(arg: Any, connection: Connection) -> tuple[int, int]:
    """One theory's batch, in one write transaction.  Returns (written, duplicate).

    Synchronous throughout, deliberately: with no ``await`` in the body the event loop
    cannot start a second handler while this one holds LMDB's writer lock, which is
    what keeps concurrent calls from the cone's parallel futures out of each other's
    way -- the same property ``Semantic_DB``'s writers rely on."""
    (theory_longname, theory_key, theory_file, tie_break_degraded, line_mismatch,
     entries) = arg
    theory_key = bytes(theory_key)
    if len(theory_key) != 16:
        raise RuntimeError(
            f"dump_entities: {theory_longname} sent a {len(theory_key)}-byte theory "
            f"key; a theory key is the 16-byte theory hash")

    written = 0
    duplicate = 0
    try:
        _check_still_ours()
        with _ensure_env().begin(write=True) as txn:
            if txn.get(theory_key) is not None:
                # Two theories cannot share a persistent hash (the long name is in the
                # digest), so this is a rerun over a dump that already has the theory
                # -- and a rerun silently doubles every record.
                raise RuntimeError(
                    f"{theory_longname} is already in the dump; the dump is not "
                    f"idempotent, so start from an empty scratch store")
            for uk, name, kind, pos, consts, prop in entries:
                key = bytes(uk)
                # Unicode, as the collection path stores it; `pos` stays as sent (it is
                # a filesystem path).  See the module docstring.
                record = [pretty_unicode(name), kind,
                          list(pos) if pos is not None else None,
                          [[n, bytes(h)] for n, h in consts],
                          pretty_unicode(prop), theory_longname]
                old = txn.get(key)
                if old is None:
                    txn.put(key, msgpack.packb([record]))  # type: ignore
                else:
                    txn.put(key, msgpack.packb(msgpack.unpackb(old) + [record]))  # type: ignore
                    duplicate += 1
                written += 1
            txn.put(theory_key,  # type: ignore
                    msgpack.packb([theory_longname, len(entries), theory_file,
                                   bool(tie_break_degraded), int(line_mismatch)]))
    except Exception as e:
        raise RuntimeError(f"dump_entities failed for {theory_longname}: {e}") from e
    return written, duplicate


@isabelle_remote_procedure("Semantic_Store.dump_preflight")
async def _dump_preflight(arg: Any, connection: Connection) -> str:
    """Claim the scratch store, and return the path actually claimed.

    Called once before the sweep.  Both tests have to run here rather than in the
    driver: the second one is a path test the driver could also make, but the first
    one -- has THIS process already got an environment open? -- is invisible from
    anywhere else, and it is the one that fires after the operator performs D17's
    "move it aside and start over" against a host that outlives the driver."""
    if _env is not None:
        raise RuntimeError(
            f"this RPC host already has a dump environment open at {dump_path()}.  A "
            f"second sweep in one host would append to it and make every key look "
            f"ambiguous; restart the RPC host and start from an empty scratch store")
    path = dump_path()
    if os.path.exists(path):
        raise RuntimeError(
            f"{path} already exists.  The dump is not idempotent (D17): move it aside "
            f"or delete it, restart the RPC host so it cannot keep writing into the "
            f"old directory, and run again")
    _ensure_env()
    return path


@isabelle_remote_procedure("Semantic_Store.dump_scan")
async def _dump_scan(arg: Any, connection: Connection) -> tuple[int, int, int, int, int, int]:
    """Read the committed dump back: what is actually in the store this host wrote.

    Returns (theories, enumerated, untrustworthy, keys, records, ambiguous), where
    `enumerated` is the sum over completion records of what each theory said it
    enumerated, `records` the number of entity records that landed, and `ambiguous`
    the number of keys claimed by more than one theory.  ML composes the report line;
    the driver prints it."""
    theories = enumerated = untrustworthy = keys = records = ambiguous = 0
    with _ensure_env().begin() as txn:
        for k, v in txn.cursor():
            vals = msgpack.unpackb(v)
            if len(k) <= 16:
                theories += 1
                enumerated += vals[1]
                if vals[3] or vals[4]:
                    untrustworthy += 1
            else:
                keys += 1
                records += len(vals)
                if len(vals) > 1:
                    ambiguous += 1
    return theories, enumerated, untrustworthy, keys, records, ambiguous
