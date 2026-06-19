"""Offline tests for the parametrized embedding provider + YAML config refactor.

Run: EMBEDDING_CONFIG_PATH defaults here to the bundled template, so no user
config or network is needed.

    python3 test_embedding_provider_refactor.py
    # or: pytest test_embedding_provider_refactor.py
"""
import os

# Point the config loader at the bundled template before importing the module.
os.environ.setdefault(
    "EMBEDDING_CONFIG_PATH",
    os.path.join(os.path.dirname(__file__),
                 "Isabelle_Semantic_Embedding", "embedding_config_template.yaml"))
os.environ["EMBEDDING_API_KEY"] = "test-key-123"

from Isabelle_Semantic_Embedding import semantic_embedding as se  # noqa: E402

FIREWORKS = "https://api.fireworks.ai/inference"


def test_fireworks_qwen():
    p = se.make_embedding_provider("OpenAI_Embedding_Provider", FIREWORKS,
                                   "Qwen/Qwen3-Embedding-8B")
    assert p.canonical_model == "Qwen/Qwen3-Embedding-8B"
    assert p.model == "fireworks/qwen3-embedding-8b"   # domain normalization
    assert p.dimension == 4096
    assert (p.default_score, p.default_local_score) == (0.3, 0.5)
    assert p.normalize is True
    assert p.supports_batch is False                   # fireworks: no batch entry
    assert p.api_key == "test-key-123"                 # EMBEDDING_API_KEY only


def test_openai_batch():
    p = se.OpenAI_Embedding_Provider("https://api.openai.com", "text-embedding-3-large")
    assert p.model == "text-embedding-3-large"         # no normalization needed
    assert p.dimension == 3072
    assert (p.default_score, p.default_local_score) == (0.0, 0.0)
    assert p.normalize is False
    assert p.supports_batch is True
    assert p.max_batch_size == 50000
    assert p._batch_endpoint == "/v1/batches"
    line = p._format_batch_line(2, "hi")
    assert line["method"] == "POST" and line["body"]["model"] == "text-embedding-3-large"


def test_mistral_batch_dialect():
    p = se.OpenAI_Embedding_Provider("https://api.mistral.ai", "codestral-embed")
    assert p.dimension == 1536
    assert p.supports_batch is True
    assert p.max_batch_size == 1000000
    assert p._batch_endpoint == "/v1/batch/jobs"
    assert p._batch_completed_status == "SUCCESS"
    line = p._format_batch_line(0, "x")
    assert "method" not in line and line["body"]["input"] == "x"   # mistral shape
    req = p._create_batch_request("fid")
    assert req["input_files"] == ["fid"]


def test_aliyun_request_cap():
    p = se.make_embedding_provider(
        "OpenAI_Embedding_Provider",
        "https://dashscope-intl.aliyuncs.com/compatible-mode", "text-embedding-v4")
    assert p.dimension == 1024
    assert p.max_request_size == 10
    assert p.supports_batch is False


def test_gemini_native_driver():
    p = se.Gemini_Embedding(FIREWORKS, "gemini-embedding-2-preview")
    assert p.dimension == 3072
    # base_url is the (non-gemini) fireworks default -> falls back to gemini endpoint
    assert "generativelanguage" in p._endpoint_base


def test_sanitize_roundtrip():
    for m in ["Qwen/Qwen3-Embedding-8B", "text-embedding-3-large", "a/b/c"]:
        assert se.unsanitize_model(se.sanitize_model(m)) == m


def test_missing_dimension_errors():
    import pytest
    with pytest.raises(KeyError):
        se.make_embedding_provider("OpenAI_Embedding_Provider", FIREWORKS,
                                   "no-such-model-xyz")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        if fn.__name__ == "test_missing_dimension_errors":
            try:
                fn()
            except ImportError:
                # pytest not importable in this run; check KeyError directly
                try:
                    se.make_embedding_provider("OpenAI_Embedding_Provider", FIREWORKS,
                                               "no-such-model-xyz")
                    raise AssertionError("expected KeyError")
                except KeyError:
                    pass
        else:
            fn()
        print(f"ok: {fn.__name__}")
    print("ALL PASSED")
