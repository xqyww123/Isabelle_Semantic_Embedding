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


# --- Per-model query/document template refactor -----------------------------

QWEN = "Qwen/Qwen3-Embedding-8B"
NVEMBED = "llama-nv-embed-reasoning-3b"


def _task():
    from Isabelle_Semantic_Embedding import embedding_config as cfg
    return cfg.task_description()


def _qwen():
    return se.make_embedding_provider("OpenAI_Embedding_Provider", FIREWORKS, QWEN)


def _nvembed():
    return se.make_embedding_provider("OpenAI_Embedding_Provider", FIREWORKS, NVEMBED)


def test_template_accessors():
    from Isabelle_Semantic_Embedding import embedding_config as cfg
    assert cfg.query_template(QWEN) == "Instruct: {task}\nQuery: {text}"
    assert cfg.document_template(QWEN) == "{text}"
    assert cfg.query_template(NVEMBED) == "query: {text}"
    assert cfg.document_template(NVEMBED) == "passage: {text}"
    # unlisted model -> identity templates (raw, fully backward-compatible)
    assert cfg.query_template("text-embedding-3-large") == "{text}"
    assert cfg.document_template("text-embedding-3-large") == "{text}"
    # task_description is a static sentence (no {kinds} slot, no {text}/{task})
    td = cfg.task_description()
    assert "{kinds}" not in td and "{text}" not in td and "{task}" not in td
    assert "Isabelle/HOL" in td


def test_apply_template_query_and_document():
    p = _qwen()
    task = _task()
    assert p._apply_template(["find me a lemma"], "query") == \
        ["Instruct: " + task + "\nQuery: find me a lemma"]
    # Qwen3 document template is identity -> existing corpus vectors stay valid
    assert p._apply_template(["a theorem about lists"], "document") == \
        ["a theorem about lists"]


def test_apply_template_nvembed():
    p = _nvembed()
    # nv-embed: query and document get DISTINCT prefixes (docs cannot be raw)
    assert p._apply_template(["q"], "query") == ["query: q"]
    assert p._apply_template(["d"], "document") == ["passage: d"]


def test_apply_template_brace_safety():
    # Set-builder / record braces must pass through verbatim (no str.format).
    p = _qwen()
    task = _task()
    text = "{x. x > 0} and (| a = 1 |)"
    assert p._apply_template([text], "query") == \
        ["Instruct: " + task + "\nQuery: " + text]
    assert p._apply_template([text], "document") == [text]


def test_apply_template_unlisted_model_is_raw():
    p = se.make_embedding_provider("OpenAI_Embedding_Provider",
                                   "https://api.openai.com", "text-embedding-3-large")
    assert p._apply_template(["raw {q}"], "query") == ["raw {q}"]
    assert p._apply_template(["raw {q}"], "document") == ["raw {q}"]


def test_apply_template_bad_role():
    p = _qwen()
    raised = False
    try:
        p._apply_template(["x"], "neither")
    except ValueError:
        raised = True
    assert raised


def test_task_description_guard():
    # A hand-edited task_description with literal {text}/{task} must fail fast,
    # not silently splice the query into the instruction sentence.
    from Isabelle_Semantic_Embedding import embedding_config as cfg
    p = _qwen()
    orig = cfg.task_description
    cfg.task_description = lambda: "leak {text} into instruction"
    try:
        raised = False
        try:
            p._apply_template(["q"], "query")
        except ValueError:
            raised = True
        assert raised, "expected ValueError for {text} in task_description"
        # document role does not use task_description -> not guarded
        assert p._apply_template(["d"], "document") == ["d"]
    finally:
        cfg.task_description = orig


def test_embed_role_templates_before_cache():
    # embed(role=...) must apply the template BEFORE the per-string cache/backend,
    # so the cache key and HTTP body see the *templated* text.
    import asyncio
    import numpy as np
    p = _qwen()
    task = _task()
    captured = {}

    async def fake_cached(text, backend):
        captured["text"] = list(text)
        return se.EmbedResult(np.zeros((len(text), p.dimension), dtype=np.float32), 0)

    p._embed_cached = fake_cached  # bypass the real diskcache + network
    asyncio.run(p.embed(["hello {set}"], role="query"))
    assert captured["text"] == ["Instruct: " + task + "\nQuery: hello {set}"]
    asyncio.run(p.embed(["hello {set}"], role="document"))
    assert captured["text"] == ["hello {set}"]   # Qwen3 document = identity
    # default role is "document" (all existing corpus callers keep behaving raw)
    asyncio.run(p.embed(["plain"]))
    assert captured["text"] == ["plain"]


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
