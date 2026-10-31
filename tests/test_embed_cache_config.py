"""The embedding text cache under LINK_LAYER_PLAN.md D26: the size cap comes from
EMBEDDING_CACHE_SIZE_GIB (default 6 GiB, unparsable values refused) and a text
can be cached with its own expiry (DERIVED_VECTOR_TTL for derived vectors).
Run with  python -m pytest contrib/Semantic_Embedding/tests/test_embed_cache_config.py
"""
import asyncio
import os

import diskcache
import numpy as np
import pytest

from Isabelle_Semantic_Embedding import semantic_embedding as se


def test_cache_size_default_is_6_gib(monkeypatch):
    monkeypatch.delenv(se.EMBED_CACHE_SIZE_ENV, raising=False)
    assert se.embed_cache_size_bytes() == 6 * 1024 ** 3
    monkeypatch.setenv(se.EMBED_CACHE_SIZE_ENV, "")
    assert se.embed_cache_size_bytes() == 6 * 1024 ** 3


def test_cache_size_reads_decimal_gib(monkeypatch):
    monkeypatch.setenv(se.EMBED_CACHE_SIZE_ENV, "0.5")
    assert se.embed_cache_size_bytes() == 512 * 1024 ** 2
    monkeypatch.setenv(se.EMBED_CACHE_SIZE_ENV, " 12 ")
    assert se.embed_cache_size_bytes() == 12 * 1024 ** 3


@pytest.mark.parametrize("raw", ["six", "6GiB", "-1", "0"])
def test_cache_size_refuses_bad_values(monkeypatch, raw):
    monkeypatch.setenv(se.EMBED_CACHE_SIZE_ENV, raw)
    with pytest.raises(ValueError, match=se.EMBED_CACHE_SIZE_ENV):
        se.embed_cache_size_bytes()


class _Fake(se.Embedding_Provider):
    """A provider whose backend counts its calls; the YAML lookups are bypassed."""

    def __init__(self):
        self.canonical_model = "fake-model"
        self.model = "fake-model"
        self.dimension = 4
        self.normalize = False
        self.max_request_size = 100
        self.calls = 0

    async def _embed(self, text):
        self.calls += 1
        return se.EmbedResult(np.ones((len(text), 4), dtype=np.float32), len(text))

    async def _log(self, msg):
        pass


def test_expiry_is_per_call(tmp_path, monkeypatch):
    cache = diskcache.Cache(str(tmp_path / "embed_cache"), size_limit=1 << 20)
    monkeypatch.setattr(se.Embedding_Provider, "_cache", cache, raising=False)
    p = _Fake()
    try:
        asyncio.run(p.embed(["entity text"]))
        asyncio.run(p.embed(["derived text"], expire=se.DERIVED_VECTOR_TTL))
        assert p.calls == 2
        _, t_entity = cache.get(("fake-model", "entity text"), expire_time=True)
        _, t_derived = cache.get(("fake-model", "derived text"), expire_time=True)
        assert t_derived - t_entity == pytest.approx(
            se.DERIVED_VECTOR_TTL - se._EMBED_CACHE_TTL, abs=5)
        # A second embedding of either text is a cache hit.
        asyncio.run(p.embed(["entity text", "derived text"]))
        assert p.calls == 2
    finally:
        cache.close()
