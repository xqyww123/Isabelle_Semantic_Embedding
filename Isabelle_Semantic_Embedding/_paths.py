"""Resolve where the semantic-embedding databases live.

`semantics.lmdb`, the `vector_*.lmdb` stores, `experience_index.lmdb`,
`theory_hash.lmdb`, `embed_cache/`, and `AoA_Collected/` all live under one
directory. It defaults to platformdirs' per-user cache
(`~/.cache/Isabelle_Semantic_Embedding`) but can be redirected with the
``SEMANTIC_DB_DIR`` environment variable.

Why the override exists: LMDB uses `mmap` plus POSIX file locking, whose semantics
are unreliable on networked filesystems (NFS / lustre) and can silently corrupt a
store (``MDB_CORRUPTED: Located page was wrong type``). Point ``SEMANTIC_DB_DIR`` at
a LOCAL disk (e.g. ``/var/tmp/<user>/Isabelle_Semantic_Embedding``) to avoid that.
The databases are a rebuildable cache (restorable from the published snapshot), so a
node-local, non-shared location is fine — the only writer is the single RPC host.

`semantic_DB_dir()` is defined in `Isabelle_RPC_Host.paths` and re-exported here.
It belongs there because `Isabelle_RPC_Host.theory_hash` opens `theory_hash.lmdb`
in this directory and that package does not import this one; both import names
reach the one implementation.

Every cache-path site in BOTH packages routes through it — including the offline
tools `isabelle_semantics.py`, `snapshot_sync` and the `migrate_*` scripts — so the
override moves the whole database set together. Nothing in either package may call
`platformdirs.user_cache_dir("Isabelle_Semantic_Embedding", ...)` directly.
"""

from Isabelle_RPC_Host.paths import semantic_DB_dir

__all__ = ["semantic_DB_dir"]
