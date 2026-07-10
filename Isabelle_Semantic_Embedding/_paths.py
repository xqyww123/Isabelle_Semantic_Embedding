"""Resolve where the semantic-embedding databases live.

`semantics.lmdb`, the `vector_*.lmdb` stores, `experience_index.lmdb`,
`embed_cache/`, and `AoA_Collected/` all live under one directory. It defaults to
platformdirs' per-user cache (`~/.cache/Isabelle_Semantic_Embedding`) but can be
redirected with the ``SEMANTIC_DB_DIR`` environment variable.

Why the override exists: LMDB uses `mmap` plus POSIX file locking, whose semantics
are unreliable on networked filesystems (NFS / lustre) and can silently corrupt a
store (``MDB_CORRUPTED: Located page was wrong type``). Point ``SEMANTIC_DB_DIR`` at
a LOCAL disk (e.g. ``/var/tmp/<user>/Isabelle_Semantic_Embedding``) to avoid that.
The databases are a rebuildable cache (restorable from the published snapshot), so a
node-local, non-shared location is fine — the only writer is the single RPC host.

Every cache-path site in this package (and the offline tools `semantics_manage.py`,
`r2_sync`, the `migrate_*` scripts) routes through `semantic_DB_dir()`, so the
override moves the whole database set together; nothing may call
`platformdirs.user_cache_dir("Isabelle_Semantic_Embedding", ...)` directly.
"""

import os

import platformdirs

_ENV_VAR = "SEMANTIC_DB_DIR"


def semantic_DB_dir() -> str:
    """The directory holding the semantic databases, honouring ``SEMANTIC_DB_DIR``.

    Returns the override verbatim when set (callers `os.makedirs(..., exist_ok=True)`
    before writing, as they already did for the platformdirs path), else the
    per-user cache dir."""
    override = os.getenv(_ENV_VAR)
    if override:
        return override
    return platformdirs.user_cache_dir("Isabelle_Semantic_Embedding", "Qiyuan")
