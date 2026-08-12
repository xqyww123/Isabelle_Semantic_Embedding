from __future__ import annotations
from abc import ABC, abstractmethod
import asyncio
import contextlib
import contextvars
import importlib.util
import json
import os
import pathlib
import tempfile
import time
from urllib.parse import urlsplit
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, Awaitable, Callable, ClassVar, NamedTuple, cast
if TYPE_CHECKING:
    from Isabelle_RPC_Host.rpc import Connection
import httpx
import numpy as np
import lmdb
import diskcache
from ._paths import semantic_DB_dir
from .base import logger_of as _logger_of

from ._vecarith import encode_q15, gather_addrs, top_k_q15_gather, Q15_SCALE

_EMBED_CACHE_TTL = 3 * 86400  # 3 days

_MAX_ERROR_BODY = 500  # chars of provider response body kept in a warning

# Internal transport for the Semantic_Store_verbose gate (Tools/semantic_store.ML):
# while set, the embed machinery's per-batch tracing (_log lines, embed_records'
# count line in semantics.py) is suppressed, so a whole-DB completion run cannot
# overflow Isabelle's editor_tracing_messages cap (1000; overflow pops a BLOCKING
# "Tracing paused" dialog).  Set only by complete_vector_store for its own dynamic
# extent; _warn is never gated.  A ContextVar, not a plain global: the RPC host
# runs concurrent handler tasks on one event loop, and the gate must not leak into
# a concurrent _auto_embed.
_embed_tracing_gated: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_embed_tracing_gated", default=False)


def settings_file_path() -> str:
    """Absolute path of the user's Isabelle settings file, or "" if unobtainable.

    Resolved at runtime, never hardcoded: two Isabelle installations on one machine
    have different ISABELLE_HOME_USER directories (a stock one and a conda-provided
    one, say), so a fixed path would send half the users to a file Isabelle never
    reads.

    Uses Isabelle_RPC_Host.paths.resolve_isabelle_var rather than an env lookup,
    because it does not stop at the environment: when ISABELLE_HOME_USER is unset --
    routine for an RPC host launched by hand from a plain shell -- it asks Isabelle
    itself via `isabelle getenv -b`, which is authoritative and available by
    construction wherever these messages can appear.

    Deliberately NOT Isabelle_RPC_Host.rpc.isabelle_home_user(), the wrapper one level up:
    that one calls sys.exit(1) when the variable cannot be resolved. Every caller
    here is composing a diagnostic, so taking the whole (shared, single-process) host
    down because the advice line could not name a file would be far worse than the
    problem being reported. Returning "" and letting the caller word around it is the
    point. unicode.py calls the same lower layer for the same kind of reason.
    """
    from Isabelle_RPC_Host.paths import resolve_isabelle_var
    try:
        home = resolve_isabelle_var("ISABELLE_HOME_USER")
    except Exception:
        return ""
    return os.path.join(home, "etc", "settings") if home else ""


def _is_version_segment(seg: str) -> bool:
    """``v1``, ``v1beta``, ``v4``, ... -- an API version path segment."""
    return len(seg) > 1 and seg[0] == "v" and seg[1].isdigit()


def _endpoint_domain(base_url: str) -> str:
    """The YAML ``providers:`` key for a base_url: lowercase host, scheme-default
    port stripped. An explicit non-default port is kept, so a hypothetical
    ``myhost:8080`` key still matches. Raw netloc would miss the lookup for
    ``API.FIREWORKS.AI`` or ``...:443`` spellings."""
    p = urlsplit(base_url)
    host = p.hostname or ""
    default = {"https": 443, "http": 80}.get(p.scheme)
    return host if p.port in (None, default) else f"{host}:{p.port}"


def _redacted_url(resp) -> str:
    """The endpoint a response came from, with the query string stripped, or "".

    ALWAYS use this instead of str(request.url) when a URL is about to be shown to
    a user or written to a log. Gemini_Embedding passes the API key as
    params={"key": ...} and httpx's str(URL) does not redact it, so the raw form
    would put a live credential into Isabelle's warning channel and into the RPC
    host's log file on disk. No driver here puts anything diagnostic in the query
    string, so nothing is lost by dropping it.
    """
    url = getattr(getattr(resp, "request", None), "url", None)
    if url is None:
        return ""
    try:
        return str(url.copy_with(query=None) if url.query else url)
    except Exception:
        return ""


def _http_error_detail(e: BaseException) -> str | None:
    """Human-readable detail for any HTTP status error, or None for everything else.

    Every 4xx AND 5xx is reported. Only connection-layer failures (DNS, refused,
    timeout) stay on the quiet tracing channel: those are the ones where "it will
    probably fix itself" actually holds, and where there is nothing for the user to
    act on anyway.

    429 is included deliberately. Fireworks returns 429 for BOTH ordinary rate
    limiting and `quota_exceeded`, and does not distinguish them by status code
    (docs.fireworks.ai/guides/quotas_usage/rate-limits), so excluding it would make
    quota exhaustion silent -- the exact failure mode this reporting exists for.

    5xx is included even though it is nominally transient, because "5xx = transient"
    is a heuristic, not a fact: a 500 provoked deterministically by our own payload
    (a text the provider cannot parse, an over-long input, an empty string in the
    batch) fails all 10 attempts identically, and the user is the only one who can
    recognise that from the message. 502/503/504/529 really are capacity blips and
    will look noisy -- that is the accepted cost of not hiding the other case.

    httpx's HTTPStatusError message carries only the status line and an MDN link; the
    provider's own text (e.g. "You must provide an API key. See https://docs...") is
    in the body and is the only actionable part, so it is spliced in here.
    """
    if not isinstance(e, httpx.HTTPStatusError):
        return None
    resp = getattr(e, "response", None)
    if resp is None:
        return None
    try:
        body = (resp.text or "").strip()
    except Exception:          # body already consumed / undecodable
        body = ""
    if len(body) > _MAX_ERROR_BODY:
        body = body[:_MAX_ERROR_BODY] + " ...(truncated)"
    detail = f"HTTP {resp.status_code}"
    url = _redacted_url(resp)
    if url:
        detail += f" from {url}"
    return detail + (f": {body}" if body else "")


class HTTP_Provider(ABC):
    """Shared diagnostics for anything that talks to a hosted model over HTTP.

    Both provider hierarchies inherit this: embedding providers and rerankers hit
    the same endpoints with the same credentials and fail the same ways, so the
    classification and the advice belong in one place rather than being written
    twice and drifting.
    """
    model: str
    base_url: str = ""
    api_key: str | None = None
    # Environment variables this provider accepts a key from, in the order it
    # consults them. Per-provider because it is NOT uniform -- Gemini takes a
    # second one, the reranker uses an entirely different one -- and naming the
    # wrong variable in an error message sends the user to edit a setting that
    # has no effect. Subclass __init__ must implement the same order.
    API_KEY_ENV_VARS: ClassVar[tuple[str, ...]] = ("EMBEDDING_API_KEY",)

    def _is_auth_error(self, resp) -> bool:
        """Whether *resp* means "you are not authenticated", not "your request was bad".

        The four OpenAI-compatible endpoints served here (Fireworks, OpenAI,
        Mistral, DashScope) all answer 401 for BOTH a missing and an invalid key --
        measured against the live APIs, not assumed. Gemini does not, which is why
        this is a method rather than a constant; see the override there.
        """
        return getattr(resp, "status_code", None) in (401, 403)

    def _set_api_key_hint(self) -> str:
        """Where to put the key, naming the file rather than just the variable.

        An `export` in a shell profile is not reliably visible to Isabelle -- a
        desktop-launched jEdit inherits a different environment -- so the settings
        file, which Isabelle always reads, is the answer that actually works.
        """
        var = self.API_KEY_ENV_VARS[0]
        alt = self.API_KEY_ENV_VARS[1:]
        path = settings_file_path()
        where = path or "etc/settings in the directory `isabelle getenv ISABELLE_HOME_USER` prints"
        hint = f"  Add  {var}=<your-key>  in {where}, then restart Isabelle."
        if alt:
            hint += ("\n  (" + " / ".join(alt) + " also works, but only while "
                     f"{var} is unset.)")
        return hint

    def _http_error_hint(self, e: BaseException) -> str:
        """What the user can do about this status, when there is anything."""
        resp = getattr(e, "response", None)
        status = getattr(resp, "status_code", None)
        # Auth is tested FIRST, and by predicate rather than by status: Gemini
        # reports an invalid key as 400, the same status as an unknown model, so a
        # status-ordered check would hand that user the "check your model name"
        # advice while the body right above it says the key is invalid.
        if resp is not None and self._is_auth_error(resp):
            if not self.api_key:
                return "\n  No API key is configured.\n" + self._set_api_key_hint()
            return ("\n  The endpoint rejected the configured API key. Check that it "
                    "is current, was copied in full, and belongs to this endpoint.")
        if status in (400, 404, 422):
            # The endpoint actually contacted, not self.base_url: Gemini_Embedding
            # requests against _endpoint_base, which falls back to the Google host
            # whenever base_url lacks "generativelanguage" -- and the default
            # base_url is the Fireworks one, so it ALWAYS falls back. Interpolating
            # the configured field would name a host that was never contacted.
            endpoint = _redacted_url(resp) or self.base_url
            hint = (f"\n  Check that model {self.model!r} is served by {endpoint} "
                    "(Isabelle config Semantic_Embedding.embedding_model / embedding_base_url).")
            # A 404 against a URL with no version segment anywhere in its path is
            # the signature of a base_url still written in the pre-2026-07 style
            # (version-less). Only a suggestion -- a root-hosted server that
            # genuinely serves /embeddings gets one extra sentence on a 404, never
            # a rejection.
            if status == 404 and not any(
                    _is_version_segment(s) for s in urlsplit(endpoint).path.split("/")):
                hint += ("\n  The URL contains no API version segment; if the "
                         "endpoint follows the OpenAI convention, base_url should "
                         "end with `/v1`.")
            return hint
        if status == 429:
            # The "will wait and retry" sentence is the point of this branch, not a
            # detail: without it a user watching a stalled proof concludes it has
            # hung and kills the process, when waiting would have got them through.
            # Hence no exact figure -- the backoff is 2**attempt (1s, 2s, ... 512s),
            # so any single number would be wrong most of the time.
            #
            # TODO(reranker): this sentence is currently FALSE on the reranker path.
            # OpenAI_Reranker_Provider.rerank has no retry loop at all -- it raises on
            # the first failure and Semantic_Vector_Store.lookup degrades to embedding
            # scores. Give the reranker the same retry treatment as _embed_cached, or
            # make this sentence conditional on the caller actually retrying.
            return ("\n  You have hit either a rate limit or an exhausted quota. The "
                    "system will wait several seconds and retry, so there is no need "
                    "to interrupt it. This provider reports both the same way, so if "
                    "it never clears, check your account balance.")
        # No 5xx branch on purpose. Every hint here earns its place by telling the
        # user something they could not work out from the warning itself -- which
        # file the key goes in, which config names the model, that 429 is ambiguous.
        # For a 5xx the status line and the provider's own body already say all we
        # know; anything further would be speculation about their infrastructure.
        return ""


class EmbedResult(NamedTuple):
    """Result of an embedding call: vectors + total tokens used."""
    vectors: np.ndarray
    total_tokens: int = 0


class Embedding_Provider(HTTP_Provider):
    type name = str
    canonical_model: str  # identity: HuggingFace name where one exists, else canonical id
    model: str            # model id actually sent to the API
    base_url: str
    api_key: str | None
    dimension: int
    max_request_size: int = 2048
    supports_batch: bool = False
    normalize: bool = False  # L2-normalize returned vectors
    # Fallback scores for entities with no embedding vector (no interpretation),
    # used by Semantic_Vector_Store.lookup in place of the old hardcoded 0.0. The
    # meaningful value depends on the model's score distribution (these sit on the
    # same axis as 1 - L2/2 ≈ cosine), so it is configured per model in the YAML
    # embedding config. Base 0.0 preserves the previous behavior when unset.
    default_score: float = 0.0        # no-embedding, non-local fallback
    default_local_score: float = 0.0  # no-embedding, proof-context-local fallback
    DRIVERS: dict[name, type['Embedding_Provider']] = {}
    _cache: diskcache.Cache | None = None

    def __init__(self, base_url: str, model: str, api_key: str | None = None) -> None:
        """Configure a provider from the three user parameters + the YAML config.

        ``model`` is the canonical (identity) name; per-model metadata
        (dimension, default scores, normalization, request size) is resolved
        from the embedding config keyed by it.
        """
        from . import embedding_config as cfg
        self.canonical_model = model
        self.base_url = base_url
        self.model = model
        self.api_key = api_key if api_key is not None else os.getenv("EMBEDDING_API_KEY")
        self.dimension = cfg.dimension(model)
        self.default_score, self.default_local_score = cfg.default_scores(model)
        self.normalize = cfg.normalize(model)
        self.max_request_size = cfg.max_request_size(model)

    @property
    def _cache_key_prefix(self) -> str:
        return self.canonical_model

    @abstractmethod
    async def _embed(self, text: list[str]) -> EmbedResult:
        """Embed a list of texts into vectors.

        Must return an ``EmbedResult`` where ``vectors`` is a 2D float32 matrix
        with shape ``(len(text), dimension)``.
        """
        ...

    async def _embed_batch(self, text: list[str]) -> EmbedResult:
        """Embed a large batch of texts. Defaults to ``_embed``.

        Override to implement chunked or rate-limited batching.
        """
        return await self._embed(text)

    @staticmethod
    def _get_cache() -> diskcache.Cache:
        if Embedding_Provider._cache is None:
            cache_dir = semantic_DB_dir()
            os.makedirs(cache_dir, exist_ok=True)
            Embedding_Provider._cache = diskcache.Cache(
                os.path.join(cache_dir, "embed_cache"),
                size_limit=2 * 1024 * 1024 * 1024)
        return Embedding_Provider._cache

    async def _embed_cached(self, text: list[str],
                      backend: 'Callable[[list[str]], Awaitable[EmbedResult]]') -> EmbedResult:
        """Per-string cache lookup, chunk misses, call backend with retry, cache incrementally."""
        cache = self._get_cache()
        results: list[np.ndarray | None] = [None] * len(text)
        misses: list[tuple[int, str]] = []
        for i, t in enumerate(text):
            cached = cache.get((self._cache_key_prefix, t))
            if cached is not None:
                results[i] = np.frombuffer(cast(bytes, cached), dtype=np.float32)
            else:
                misses.append((i, t))
        hits = len(text) - len(misses)
        if not misses:
            await self._log(f"[Embedding Cache] {self.model}: all {hits} texts cached")
            return EmbedResult(np.stack(results), 0)  # type: ignore
        if hits > 0:
            await self._log(f"[Embedding Cache] {self.model}: {hits} hits, {len(misses)} misses")
        total_tokens = 0
        chunk_size = self.max_request_size
        total_chunks = (len(misses) + chunk_size - 1) // chunk_size
        for ci in range(0, len(misses), chunk_size):
            chunk = misses[ci:ci + chunk_size]
            chunk_texts = [t for _, t in chunk]
            if total_chunks > 1:
                await self._log(f"[Embedding] {self.model}: chunk {ci // chunk_size + 1}/{total_chunks} "
                          f"({len(chunk)} texts)")
            last_err: Exception | None = None
            for attempt in range(10):
                try:
                    embed_result = await backend(chunk_texts)
                    break
                except Exception as e:
                    last_err = e
                    where = (f"[Embedding] {self.model}: chunk "
                             f"{ci // chunk_size + 1}/{total_chunks} attempt {attempt + 1}/10")
                    detail = _http_error_detail(e)
                    if detail is None:
                        await self._log(f"{where} failed: {e}")
                    else:
                        # We keep retrying regardless -- the point of the warning is
                        # that the user finds out NOW rather than after the full
                        # ~17min of backoff (1+2+...+512s) that precedes the raise.
                        await self._warn(f"{where} failed: {detail}"
                                         + self._http_error_hint(e))
                    await asyncio.sleep(2 ** attempt)
            else:
                raise RuntimeError(
                    f"Embedding chunk {ci // chunk_size + 1}/{total_chunks} "
                    f"failed after 10 retries") from last_err
            total_tokens += embed_result.total_tokens
            for (i, t), vec in zip(chunk, embed_result.vectors):
                cache.set((self._cache_key_prefix, t), vec.tobytes(), expire=_EMBED_CACHE_TTL)
                results[i] = vec
        return EmbedResult(np.stack(results), total_tokens)  # type: ignore

    def _normalize(self, result: EmbedResult) -> EmbedResult:
        if self.normalize:
            # numpy, not faiss.normalize_L2. This was the only faiss call left in the
            # project -- retrieval is the SIMD LMDB scan, not a faiss index -- and it
            # cost a dependency on faiss + libfaiss for one row-wise divide.
            #
            # Semantics match fvec_renorm_L2 exactly, including the part that is easy to
            # get wrong: faiss scales a row only when its norm is > 0, leaving an
            # all-zero row untouched rather than producing NaN. Hence `where=`.
            # In-place, like faiss: callers rely on result.vectors being mutated.
            v = result.vectors
            n = np.linalg.norm(v, axis=1, keepdims=True)
            np.divide(v, n, out=v, where=n != 0)
        return result

    def _apply_template(self, texts: list[str], role: str,
                        kinds_phrase: str | None = None,
                        task_override: str | None = None) -> list[str]:
        """Wrap each text in the model's query/document template before embedding.

        Uses literal str.replace (NOT str.format) so raw text containing '{' or
        '}' -- routine in Isabelle interpretation text -- is safe. A model with
        no template entry, or the identity template '{text}', leaves the text
        unchanged (fully backward-compatible). For role='query', ``kinds_phrase``
        fills the task_description's {kinds} slot (None -> the default phrase);
        ``task_override``, when given, REPLACES the whole task sentence (used by
        the experience-memory query pass, whose sentence has no {kinds} slot).
        """
        from . import embedding_config as cfg
        model = self.canonical_model
        if role == "document":
            tmpl = cfg.document_template(model)
            return [tmpl.replace("{text}", t) for t in texts]
        if role == "query":
            tmpl = cfg.query_template(model)
            if task_override is not None:
                task = task_override
            else:
                phrase = kinds_phrase if kinds_phrase is not None else cfg._DEFAULT_KINDS_PHRASE
                task = cfg.task_description().replace("{kinds}", phrase)
            # Enforce the config constraint AFTER {kinds} substitution: a
            # hand-edited task_description with a literal {text}/{task} would
            # otherwise be spliced by the .replace below (corrupting the query).
            # Fail fast rather than silently garble. (render_kinds' phrase is
            # brace-free, so it can never introduce {text}/{task}.)
            if "{text}" in task or "{task}" in task:
                raise ValueError(
                    "task_description must not contain '{text}' or '{task}': "
                    f"{task!r}")
            # {task} first, then {text}; the inserted t is never re-scanned, so
            # any braces inside t are inert.
            return [tmpl.replace("{task}", task).replace("{text}", t) for t in texts]
        raise ValueError(f"unknown embed role {role!r}")

    async def _log(self, msg: str) -> None:
        if _embed_tracing_gated.get():
            return
        from Isabelle_RPC_Host.rpc import Connection
        conn = Connection.current()
        if conn is not None:
            await conn.tracing(msg)

    async def _warn(self, msg: str) -> None:
        """Report to Isabelle's warning channel (yellow, uncapped).

        Deliberately `warning`, not an error channel: Isabelle_Log's wire enum is
        TRACING|WARNING|WRITELN (Isabelle_RPC/Tools/tracing.ML:2) with no ERROR, and
        adding one would need a lockstep upgrade of both sides of a separate repo --
        an old ML peer hits `raise Unpack` on an unknown tag. `warning` is also the
        right *semantics* here: ML's `error` raises and would abort the retry loop.
        """
        from Isabelle_RPC_Host.rpc import Connection
        conn = Connection.current()
        if conn is not None:
            await conn.warning(msg)


    async def embed(self, text: list[str], *, role: str = "document",
                    kinds_phrase: str | None = None,
                    task_override: str | None = None) -> EmbedResult:
        """Embed texts, always using cache. ``role`` ('document' for corpus text,
        'query' for a search query) selects the per-model template applied first;
        ``kinds_phrase`` fills a query template's {kinds} slot (ignored for documents);
        ``task_override`` replaces the whole query task sentence (experience pass)."""
        text = self._apply_template(text, role, kinds_phrase, task_override)
        total_chars = sum(len(t) for t in text)
        await self._log(f"[Embedding] {self.model}: embedding {len(text)} texts, {total_chars} chars")
        result = await self._embed_cached(text, self._embed)
        await self._log(f"[Embedding] {self.model}: done, total_tokens={result.total_tokens}")
        return self._normalize(result)

    async def _embed_batch_or_fallback(self, text: list[str]) -> EmbedResult:
        """Route to _embed_batch if supported, otherwise fall back to _embed."""
        if self.supports_batch:
            return await self._embed_batch(text)
        return await self._embed(text)

    async def embed_batch(self, text: list[str], *, role: str = "document",
                          kinds_phrase: str | None = None) -> EmbedResult:
        """Embed a large batch of texts, always using cache. See ``embed`` for ``role``/``kinds_phrase``."""
        text = self._apply_template(text, role, kinds_phrase)
        total_chars = sum(len(t) for t in text)
        await self._log(f"[Embedding Batch] {self.model}: embedding {len(text)} texts, {total_chars} chars")
        result = await self._embed_cached(text, self._embed_batch_or_fallback)
        await self._log(f"[Embedding Batch] {self.model}: done, total_tokens={result.total_tokens}")
        return self._normalize(result)

def sanitize_model(model: str) -> str:
    """Filesystem-safe form of a canonical model name (for LMDB store dirnames)."""
    return model.replace("/", "__")

def unsanitize_model(name: str) -> str:
    """Inverse of sanitize_model: recover the canonical model name from a dirname."""
    return name.replace("__", "/")

def register_embedding_driver(name: str):
    """Class decorator to register an Embedding_Provider driver class by name."""
    def decorator(cls: type[Embedding_Provider]) -> type[Embedding_Provider]:
        Embedding_Provider.DRIVERS[name] = cls
        return cls
    return decorator

def resolve_embedding_driver_class(driver: str) -> type[Embedding_Provider] | None:
    """Driver class by name: the DRIVERS registry, then drivers/{driver}.py
    (whose module must expose an ``Embedding_Provider`` driver class).

    Returns None for an *unknown* name (no registry entry, no file) so that key
    resolution can fall back to generic advice while make_embedding_provider
    keeps its hard ImportError at the construction site; genuine load failures
    (unreadable spec, module errors) still raise.

    A dynamically loaded class is memoized into DRIVERS: config resolution runs
    on every retrieval, before the per-connection store cache, so an unmemoized
    load would re-execute the driver module's top level per query.
    """
    cls = Embedding_Provider.DRIVERS.get(driver)
    if cls is not None:
        return cls
    path = pathlib.Path(__file__).parent / "drivers" / f"{driver}.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(driver, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load embedding driver {driver!r} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = mod.Embedding_Provider
    Embedding_Provider.DRIVERS[driver] = cls
    return cls


def make_embedding_provider(driver: str, base_url: str, model: str,
                            api_key: str | None = None) -> Embedding_Provider:
    """Instantiate an embedding driver class with the (base_url, model) parameters.

    api_key, when given, is assigned AFTER construction rather than passed
    positionally: out-of-tree drivers are written against the historical
    two-argument call shape, and the base __init__ only stores api_key anyway
    (no consumption during construction), so post-assignment is equivalent for
    in-tree classes and non-breaking for external ones. When api_key is None
    the constructor's own env fallbacks (EMBEDDING_API_KEY, Gemini's
    GEMINI_API_KEY) stay in charge, keeping connection-less scripts unchanged."""
    cls = resolve_embedding_driver_class(driver)
    if cls is None:
        path = pathlib.Path(__file__).parent / "drivers" / f"{driver}.py"
        raise ImportError(f"Embedding driver {driver!r} not found in DRIVERS or at {path}")
    provider = cls(base_url, model)
    if api_key:
        provider.api_key = api_key
    return provider

@register_embedding_driver("OpenAI_Embedding_Provider")
class OpenAI_Embedding_Provider(Embedding_Provider):
    """Generic provider for any OpenAI-compatible embeddings endpoint.

    ``base_url`` includes the API version segment, exactly as in the OpenAI SDK
    (e.g. ``https://api.openai.com/v1``); the provider posts to
    ``{base_url}/embeddings``. Batch endpoints are wire-protocol absolute paths
    and join onto the URL *origin* instead -- see ``_embed_batch``.

    All model/endpoint specifics come from the YAML embedding config: the API
    model id (per-domain normalization), the dimension/scores/normalize/request
    size (per model), and the optional Batch API shape (per domain). Batch is
    enabled iff the base_url's domain has a ``batch`` entry; ``dialect`` selects
    the request/response shape (``openai`` or ``mistral``).
    """
    max_batch_size: int = 50000

    def __init__(self, base_url: str, model: str, api_key: str | None = None) -> None:
        from . import embedding_config as cfg
        super().__init__(base_url, model, api_key)
        domain = _endpoint_domain(base_url)
        # base_url carries the API version segment (`.../v1`) since 2026-07. For a
        # domain listed under the YAML `providers:` section -- every hosted endpoint
        # we know of -- a version-less path can only be a pre-change value, so fail
        # at construction rather than let every request 404. Unlisted domains
        # (self-hosted server roots) are legitimately version-less and stay exempt.
        # A detector, not a shim: the URL is never rewritten.
        if (cfg.provider_listed(domain) and not _is_version_segment(
                urlsplit(base_url).path.rstrip("/").rsplit("/", 1)[-1])):
            path = settings_file_path()
            where = path or ("etc/settings in the directory "
                             "`isabelle getenv ISABELLE_HOME_USER` prints")
            raise ValueError(
                f"embedding base_url {base_url!r} has no API version segment. "
                f"base_url now includes it, as in the OpenAI SDK: use "
                f"{base_url.rstrip('/')}/v1 (or this endpoint's actual version). "
                f"Update EMBEDDING_BASE_URL in {where}, or the Isabelle option "
                f"Semantic_Embedding.embedding_base_url, then restart Isabelle.")
        self.model = cfg.api_model_name(domain, model)  # name sent to the API
        self._batch: dict = cfg.batch_config(domain) or {}
        self.supports_batch = bool(self._batch)
        if self._batch:
            self.max_batch_size = int(self._batch.get("max_batch_size", 50000))

    # --- Batch API hooks (shape selected by the per-domain `dialect`) ---

    @property
    def _batch_endpoint(self) -> str:
        return self._batch["endpoint"]

    @property
    def _batch_completed_status(self) -> str:
        return self._batch["completed"]

    @property
    def _batch_failed_statuses(self) -> set[str]:
        return set(self._batch["failed"])

    @property
    def _batch_output_file_key(self) -> str:
        return self._batch["output_file_key"]

    def _format_batch_line(self, i: int, text: str) -> dict:
        """One JSONL line for the batch input file."""
        if self._batch["dialect"] == "mistral":
            return {"custom_id": str(i),
                    "body": {"input": text, "encoding_format": "float"}}
        return {"custom_id": str(i), "method": "POST",
                "url": "/v1/embeddings",
                "body": {"model": self.model, "input": text,
                         "encoding_format": "float"}}

    def _create_batch_request(self, file_id: str) -> dict:
        """JSON body for the create-batch POST."""
        if self._batch["dialect"] == "mistral":
            return {"input_files": [file_id], "model": self.model,
                    "endpoint": "/v1/embeddings", "timeout_hours": 24}
        return {"input_file_id": file_id,
                "endpoint": "/v1/embeddings",
                "completion_window": "24h"}

    def _batch_progress(self, data: dict) -> tuple[int, int]:
        """Extract (completed, total) from poll response."""
        if self._batch["dialect"] == "mistral":
            return data.get("completed_requests", 0), data.get("total_requests", 0)
        counts = data.get("request_counts", {})
        return counts.get("completed", 0), counts.get("total", 0)

    async def _embed(self, text: list[str]) -> EmbedResult:
        url = self.base_url.rstrip("/") + "/embeddings"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={
                "input": text,
                "model": self.model,
                "encoding_format": "float",
            }, headers=headers, timeout=600)
            resp.raise_for_status()
            data = resp.json()
            vectors = np.asarray(
                [item["embedding"] for item in data["data"]],
                dtype=np.float32
            )
            usage = data.get("usage", {})
            return EmbedResult(vectors, usage.get("total_tokens", 0))

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _submit_one_batch(self, client: httpx.AsyncClient, texts: list[str],
                          url_base: str, auth_headers: dict[str, str]) -> str:
        """Write JSONL, upload, create batch. Returns batch_id."""
        with tempfile.NamedTemporaryFile(mode='w+b', suffix='.jsonl') as f:
            for i, t in enumerate(texts):
                f.write(json.dumps(self._format_batch_line(i, t)).encode())
                f.write(b'\n')
            f.seek(0)
            resp = await client.post(f"{url_base}/v1/files",
                headers=auth_headers,
                files={"file": f}, data={"purpose": "batch"})
        resp.raise_for_status()
        file_id = resp.json()["id"]
        resp = await client.post(f"{url_base}{self._batch_endpoint}",
            headers={"Content-Type": "application/json", **auth_headers},
            json=self._create_batch_request(file_id))
        resp.raise_for_status()
        return resp.json()["id"]

    async def _poll_and_download(self, client: httpx.AsyncClient, batch_id: str,
                           n: int, url_base: str, auth_headers: dict[str, str],
                           conn: Connection | None) -> tuple[np.ndarray, int]:
        """Poll until batch completes, download results. Returns (vectors, total_tokens)."""
        while True:
            resp = await client.get(f"{url_base}{self._batch_endpoint}/{batch_id}",
                headers=auth_headers)
            resp.raise_for_status()
            batch_data = resp.json()
            status = batch_data["status"]
            if status == self._batch_completed_status:
                output_file_id = batch_data[self._batch_output_file_key]
                if conn is not None:
                    await conn.tracing(
                        f"[Embedding Batch] batch {batch_id} completed, downloading results")
                break
            elif status in self._batch_failed_statuses:
                raise RuntimeError(f"Batch {batch_id} {status}: {batch_data}")
            if conn is not None:
                completed, total = self._batch_progress(batch_data)
                await conn.tracing(
                    f"[Embedding Batch] batch {batch_id}: status={status}, "
                    f"completed={completed}/{total}, "
                    f"waiting...")
            await asyncio.sleep(10)

        resp = await client.get(f"{url_base}/v1/files/{output_file_id}/content",
            headers=auth_headers)
        resp.raise_for_status()
        results: list[list[float] | None] = [None] * n
        total_tokens = 0
        for line in resp.text.strip().split('\n'):
            obj = json.loads(line)
            idx = int(obj["custom_id"])
            body = obj["response"]["body"]
            results[idx] = body["data"][0]["embedding"]
            total_tokens += body.get("usage", {}).get("total_tokens", 0)
        return np.asarray(results, dtype=np.float32), total_tokens

    async def _embed_batch(self, text: list[str]) -> EmbedResult:
        """Embed via Batch API (async, 50% cost). Splits into sub-batches if needed."""
        from Isabelle_RPC_Host.rpc import Connection
        conn = Connection.current()
        # Batch endpoints (`/v1/files`, the YAML `batch.endpoint` values) are
        # wire-protocol absolute paths -- the same family as the body constants in
        # _format_batch_line -- so they join onto the URL ORIGIN, not base_url.
        # This also keeps every already-seeded embedding_config (whose endpoints
        # read `/v1/batches` etc.) correct now that base_url carries `/v1`.
        # Limitation: a batch-enabled endpoint behind a reverse-proxy path prefix
        # is unsupported; no batch-enabled domain has one.
        parts = urlsplit(self.base_url)
        url_base = f"{parts.scheme}://{parts.netloc}"
        auth_headers = self._auth_headers()
        total_chars = sum(len(t) for t in text)

        chunks = [text[i:i + self.max_batch_size]
                  for i in range(0, len(text), self.max_batch_size)]
        if conn is not None:
            await conn.tracing(
                f"[Embedding Batch] submitting {len(text)} texts ({total_chars} chars) "
                f"to {self.model} via Batch API"
                + (f" in {len(chunks)} sub-batches" if len(chunks) > 1 else ""))

        async with httpx.AsyncClient() as client:
            # Submit all sub-batches
            batch_ids: list[str] = []
            for ci, chunk in enumerate(chunks):
                bid = await self._submit_one_batch(client, chunk, url_base, auth_headers)
                batch_ids.append(bid)
                if conn is not None:
                    await conn.tracing(
                        f"[Embedding Batch] sub-batch {ci+1}/{len(chunks)} submitted: {bid} "
                        f"({len(chunk)} texts)")

            # Poll and download all
            all_results: list[np.ndarray] = []
            grand_total_tokens = 0
            for ci, (bid, chunk) in enumerate(zip(batch_ids, chunks)):
                vectors, tokens = await self._poll_and_download(
                    client, bid, len(chunk), url_base, auth_headers, conn)
                all_results.append(vectors)
                grand_total_tokens += tokens

        if conn is not None:
            await conn.tracing(
                f"[Embedding Batch] all {len(chunks)} sub-batch(es) finished, "
                f"total_tokens={grand_total_tokens}")

        combined = np.concatenate(all_results) if len(all_results) > 1 else all_results[0]
        return EmbedResult(combined, grand_total_tokens)

_GEMINI_DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"

@register_embedding_driver("Gemini_Embedding")
class Gemini_Embedding(Embedding_Provider):
    """Native Google Gemini embeddings (``batchEmbedContents``), not OpenAI-shaped.

    ``base_url`` overrides the Gemini endpoint base only when it looks like a
    Gemini URL (contains ``generativelanguage``); otherwise the standard
    endpoint is used (the default base_url is the OpenAI-compatible one, which
    does not apply here). api_key falls back to ``GEMINI_API_KEY``.
    """
    # EMBEDDING_API_KEY still wins -- __init__ only consults GEMINI_API_KEY when the
    # base class found nothing. Order matters in the message: a user who has both set
    # (EMBEDDING_API_KEY for some OpenAI-compatible endpoint, GEMINI_API_KEY for this
    # one) and switches driver sends the WRONG key to Google, and would otherwise be
    # told to check the variable that is not being used.
    API_KEY_ENV_VARS: ClassVar[tuple[str, ...]] = ("EMBEDDING_API_KEY", "GEMINI_API_KEY")

    def __init__(self, base_url: str, model: str, api_key: str | None = None) -> None:
        super().__init__(base_url, model, api_key)
        if self.api_key is None:
            self.api_key = os.getenv("GEMINI_API_KEY")
        self._endpoint_base = (base_url if base_url and "generativelanguage" in base_url
                               else _GEMINI_DEFAULT_ENDPOINT)

    def _is_auth_error(self, resp) -> bool:
        """Google does not use 401 for a rejected key. Measured against the live API:

            no key at all   -> 403 PERMISSION_DENIED ("unregistered callers")
            invalid key     -> 400 INVALID_ARGUMENT, reason API_KEY_INVALID

        That 400 collides with the status for an unknown model, so the status alone
        cannot separate the two cases and the body has to be consulted. Matching on
        the machine-readable `reason` rather than the prose keeps this stable across
        message rewording.
        """
        if super()._is_auth_error(resp):
            return True
        if getattr(resp, "status_code", None) != 400:
            return False
        try:
            return "API_KEY_INVALID" in (resp.text or "")
        except Exception:
            return False

    async def _embed(self, text: list[str]) -> EmbedResult:
        url = f"{self._endpoint_base.rstrip('/')}/models/{self.model}:batchEmbedContents"
        requests = [{"model": f"models/{self.model}",
                     "content": {"parts": [{"text": t}]}}
                    for t in text]
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, params={"key": self.api_key},
                json={"requests": requests}, timeout=600)
            resp.raise_for_status()
            data = resp.json()
            vectors = np.asarray(
                [emb["values"] for emb in data["embeddings"]],
                dtype=np.float32)
            return EmbedResult(vectors, 0)


# --- Reranker Provider ---

class RerankResult(NamedTuple):
    """Reranker output: document indices and their relevance scores, sorted by relevance."""
    indices: list[int]
    scores: list[float]


class Reranker_Provider(HTTP_Provider):
    type name = str
    _registration_name: ClassVar[str]
    model: str
    max_documents: int = 200
    PROVIDERS: dict[name, type['Reranker_Provider']] = {}

    @abstractmethod
    async def rerank(self, query: str, documents: list[str], top_n: int) -> RerankResult:
        """Rerank documents by relevance to query. Returns top_n results sorted by relevance."""
        ...


def register_reranker_provider(name: str):
    """Class decorator to register a Reranker_Provider subclass by name."""
    def decorator(cls: type[Reranker_Provider]) -> type[Reranker_Provider]:
        cls._registration_name = name
        Reranker_Provider.PROVIDERS[name] = cls
        return cls
    return decorator


def reranker_provider(name: Reranker_Provider.name) -> Reranker_Provider:
    """Instantiate a Reranker_Provider by name.
    Checks PROVIDERS registry first, then dynamically loads from drivers/{name}.py."""
    if name in Reranker_Provider.PROVIDERS:
        return Reranker_Provider.PROVIDERS[name]()
    path = pathlib.Path(__file__).parent / "drivers" / f"{name}.py"
    if not path.exists():
        raise ImportError(f"Reranker driver {name!r} not found in PROVIDERS or at {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load reranker driver {name!r} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Reranker_Provider()


class OpenAI_Reranker_Provider(Reranker_Provider):
    """Reranker using an OpenAI-compatible rerank endpoint.

    Same base_url convention as OpenAI_Embedding_Provider: base_url includes the
    API version segment; the provider posts to ``{base_url}/rerank``.
    """
    base_url: str
    api_key: str | None = None

    async def rerank(self, query: str, documents: list[str], top_n: int) -> RerankResult:
        url = self.base_url.rstrip("/") + "/rerank"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={
                "model": self.model,
                "query": query,
                "documents": documents,
                "top_n": top_n,
            }, headers=headers, timeout=600)
            resp.raise_for_status()
            data = resp.json()
        results = sorted(data["results"], key=lambda r: r["relevance_score"], reverse=True)
        return RerankResult(
            [r["index"] for r in results[:top_n]],
            [r["relevance_score"] for r in results[:top_n]],
        )


    # NOT the embedding key: this provider reads its own variable, so a user who set
    # only EMBEDDING_API_KEY has a working embedder and a 401 reranker. Naming the
    # embedding variable here would send them to edit a setting that changes nothing.
    API_KEY_ENV_VARS: ClassVar[tuple[str, ...]] = ("QWEN3_RERANKER_API_KEY",)


@register_reranker_provider("qwen3-reranker-8b")
class Qwen3_Reranker_8B(OpenAI_Reranker_Provider):
    base_url = os.getenv("QWEN3_RERANKER_BASE_URL", "https://api.fireworks.ai/inference/v1")
    api_key: str | None = os.getenv("QWEN3_RERANKER_API_KEY")
    model = os.getenv("QWEN3_RERANKER_MODEL", "fireworks/qwen3-reranker-8b")
    max_documents = 200


type key = bytes

import threading
import atexit

_lmdb_envs: dict[str, lmdb.Environment] = {}
_lmdb_lock = threading.Lock()

# Write ceiling for a vector_<model>.lmdb store.  LMDB does not preallocate: the
# value only reserves virtual address space, and the one passed at open() is the
# hard limit on *writes* by that process (past it, MapFullError).  Read-only
# openers adopt the file's real size and ignore it.  Lives here rather than in
# semantics.py because semantics imports this module, not the other way round.
# Every writer of a vector store must open with this one value.
VECTOR_MAP_SIZE: int = 1 << 36      # 64 GiB


# The store's own bytes are unusable.  Distinguished from everything else
# because a vector store is a CACHE: rebuilding it empty costs re-embedding, and
# that is strictly better than refusing to work at all.
_CORRUPTION_ERRORS = (lmdb.CorruptedError, lmdb.InvalidError,
                      lmdb.VersionMismatchError, lmdb.PanicError)

# Messages already reported to the log but not yet in front of the user: this
# opener is a synchronous module-level function with no connection in hand, so
# it logs immediately and leaves the message here for the next connection-aware
# call to relay (flush_store_warnings, called by topk).
_pending_store_warnings: list[str] = []
_pending_warnings_lock = threading.Lock()


def _model_of_store_path(path: str) -> str:
    """The embedding-model name a ``vector_<model>.lmdb`` path names."""
    name = os.path.basename(path.rstrip(os.sep))
    if name.startswith("vector_") and name.endswith(".lmdb"):
        return unsanitize_model(name[len("vector_"):-len(".lmdb")])
    return name


def _store_problem_message(path: str, exc: BaseException,
                           moved_to: 'str | None' = None) -> str:
    """The user-facing text for a vector store that could not be used.

    Three shapes, and the caller never picks: which one applies follows from the
    exception.  None of them carries a literal "WARNING:" -- the log level and
    Isabelle's own rendering already say that.  The cause is always reported
    verbatim: a failure is never reframed as the normal state "the system DB
    ships no store for this model", which would disguise a fault as a
    configuration."""
    model = _model_of_store_path(path)
    if moved_to is not None:
        return (f"[Semantic_Embedding] The vector store for {model} could not be "
                f"opened and\nappears corrupt: {exc}\n"
                f"  store:    {path}\n"
                f"  moved to: {moved_to}\n"
                f"A new empty store has been created.  Every vector for this model "
                f"is gone and\nwill be re-embedded on demand, which costs embedding "
                f"API calls.")
    if isinstance(exc, lmdb.MapFullError):
        # NOT the environment class.  This is not a full disk but the store
        # hitting its own ceiling, and sending the user off to free disk space
        # would waste their time.
        gib = VECTOR_MAP_SIZE / (1 << 30)
        ceiling = f"{gib:.0f} GiB" if gib == int(gib) else f"{gib:.1f} GiB"
        return (f"[Semantic_Embedding] The vector store for {model} is full: {exc}\n"
                f"  store: {path}\n"
                f"The store has reached the size ceiling this package sets for it\n"
                f"(VECTOR_MAP_SIZE, currently {ceiling}).  Raising that ceiling is "
                f"what makes\nroom; free disk space is not what is missing.")
    return (f"[Semantic_Embedding] The vector store for {model} could not be "
            f"opened: {exc}\n"
            f"  store: {path}")


def _report_store_problem(msg: str) -> None:
    """Log the message now and queue it for the user (plan §8's "always log")."""
    _logger_of(None, "vector_store").warning("%s", msg)
    with _pending_warnings_lock:
        _pending_store_warnings.append(msg)


async def flush_store_warnings(connection: 'Connection | None') -> None:
    """Relay queued vector-store problems to Isabelle, once each."""
    if connection is None:
        return
    with _pending_warnings_lock:
        pending = list(_pending_store_warnings)
        _pending_store_warnings.clear()
    for msg in pending:
        try:
            await connection.warning(msg)
        except Exception:
            # Reporting must never fail the work it is reporting on; the log
            # copy already exists.
            _logger_of(None, "vector_store").exception(
                "could not forward a vector-store warning to Isabelle")


def _get_lmdb_env(path: str) -> lmdb.Environment:
    """THE opener for a user-layer vector store, creating it if absent.

    Two classes of failure and no third path (plan §8):

    - **corruption** (`_CORRUPTION_ERRORS`) -- move the store aside to
      ``<path>.bak-<timestamp>`` (the tree's backup convention, see
      migrate_xor_thm_keys.py) and rebuild it empty.  A vector store is derived
      data; every vector it held is re-embedded on demand.
    - **everything else** -- report and RAISE.  The complete set of open-time
      environment failures is small and every member is a property of the
      MACHINE rather than of the data: permissions (EACCES/EPERM, or LockError
      on lock.mdb), ENOSPC while creating the store, a read-only filesystem,
      file-descriptor exhaustion, mmap/address-space failure, and
      network-filesystem locking.  All of them are directory-wide -- semantics.lmdb
      lives in the same directory on the same filesystem -- so when one fires the
      record store is equally unopenable and the subsystem cannot work at all.
      Raising therefore loses nothing that was going to be persisted anyway, and
      it is what puts the fault in front of the user instead of degrading
      silently.

    RAISE, not sys.exit: in the RPC host an exception comes back to Isabelle as
    an error the user actually sees, whereas sys.exit kills the host and leaves
    only a corpse in the log.
    """
    with _lmdb_lock:
        env = _lmdb_envs.get(path)
        if env is None:
            try:
                env = lmdb.open(path, map_size=VECTOR_MAP_SIZE)
            except _CORRUPTION_ERRORS as e:
                env = _rebuild_corrupt_store(path, e)
            except (lmdb.Error, OSError) as e:
                _report_store_problem(_store_problem_message(path, e))
                raise
            try:
                # Reap dead readers at every open (attached RPC hosts die by
                # os._exit by design).  See RPC_EPHEMERAL_HOST_PLAN.md, H0.
                env.reader_check()
            except lmdb.Error:
                pass
            _lmdb_envs[path] = env
        return env


def _rebuild_corrupt_store(path: str, exc: BaseException) -> lmdb.Environment:
    """Move a corrupt vector store aside and open a fresh empty one in its place.

    ``os.rename``, not ``env.copy``: the store cannot be opened, so there is no
    environment to copy from.  A failure of the rename itself is an environment
    failure and propagates under the rule above -- silently discarding the
    corrupt data would be worse than not starting."""
    moved_to = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    os.rename(path, moved_to)
    env = lmdb.open(path, map_size=VECTOR_MAP_SIZE)
    _report_store_problem(_store_problem_message(path, exc, moved_to=moved_to))
    return env

def vector_store_names() -> list[str]:
    """Every ``vector_<model>.lmdb`` the layered world knows about.

    THE enumerator: the union of the user cache's stores and the system DB's
    (plan §3.1), replacing the three that used to list the user cache only
    (`semantics._iter_vector_store_envs`, `isabelle_semantics._vector_store_paths`,
    `Semantic_Vector_Store.created_embedding_models`).

    The union is what makes invalidation correct.  The system DB ships stores
    for zero or more models (plan L14), so a model whose USER store does not
    exist on disk would otherwise receive no tombstone -- and after switching
    EMBEDDING_MODEL to it, its stale system vector would be served for a
    re-interpreted record forever.  A fresh machine is the same case: the user
    store directory is created lazily, so an interpretation pass that runs
    before any embedding would tombstone nothing at all.

    The cost is that a user store may be created empty for a model this machine
    never embeds with.  Accepted: the only thing that notices is `remove`'s
    "Also cleaning N vector store(s)." count."""
    from .snapshot_sync import _store_dirs, validated_system_db
    names = {s for s in _store_dirs(semantic_DB_dir()) if s.startswith("vector_")}
    sysdb = validated_system_db()
    if sysdb is not None:
        names |= {s for s in _store_dirs(sysdb.path) if s.startswith("vector_")}
    return sorted(names)


def user_vector_store_paths() -> list[str]:
    """The USER-layer path of every store in `vector_store_names()`.

    A path here need not exist yet -- opening it through `_get_lmdb_env`
    creates it, which is exactly how a system-shipped model gets a user store to
    hold its tombstones."""
    cache = semantic_DB_dir()
    return [os.path.join(cache, name) for name in vector_store_names()]


def user_vector_store_envs() -> 'Iterator[lmdb.Environment]':
    """Writable environments for every store in `vector_store_names()`,
    creating the user-layer store on demand."""
    os.makedirs(semantic_DB_dir(), exist_ok=True)
    for path in user_vector_store_paths():
        yield _get_lmdb_env(path)


def invalidate_vectors(keys: 'Sequence[bytes]', *,
                       really_delete: bool = False) -> None:
    """Invalidate the stored vectors of `keys` in EVERY vector store.

    THE one place a vector store is invalidated; no open-coded ``txn.delete`` or
    ``txn.put(b"")`` on a vector store anywhere else (plan §3.2).  It is an
    extraction of the loops `experience_store.delete_experience` and
    `isabelle_semantics._execute_removal` had each grown separately.

    Two modes:

    - default -- write a **tombstone** (`b""`).  Under the vector-layer
      self-sufficiency invariant that is what masks a system vector; really
      deleting the user's copy would let the system's stale one show through.
    - ``really_delete`` -- drop the user entry so the system vector DOES show
      through again.  Correct only where the system copy is the wanted answer
      (the post-install purge) or where no system copy can exist (WIP keys,
      which the published payload never contains).

    One write transaction per store, so a batch is atomic within each store; the
    stores themselves have no cross-store atomicity (§5) and none is available.

    WRITE failures are logged and never propagate (plan §8): the caller is
    typically `Semantic_DB.__setitem__`, and an exception there destroys an LLM
    answer that cost money and cannot be regenerated, to save one stale vector
    that this log line records.  OPEN failures do propagate -- see
    `_get_lmdb_env`; at that point the record write was never going to succeed
    either."""
    if not keys:
        return
    os.makedirs(semantic_DB_dir(), exist_ok=True)
    for path in user_vector_store_paths():
        invalidate_vectors_in_store(path, keys, really_delete=really_delete)


def invalidate_vectors_in_store(path: str, keys: 'Sequence[bytes]', *,
                                really_delete: bool = False) -> None:
    """`invalidate_vectors` for ONE store -- and the only place in the package
    that writes a tombstone or a deletion into a vector store.

    Split out for the callers that legitimately mean one store rather than all
    of them (`Vector_Store.delete`), so that "one place writes `b\"\"`" stays
    literally true rather than nearly true.  All the reasoning is in
    `invalidate_vectors`; this half only owns the transaction."""
    from .semantics import TOMBSTONE
    env = _get_lmdb_env(path)                      # open failures RAISE
    try:
        with env.begin(write=True) as txn:
            for k in keys:
                if really_delete:
                    txn.delete(k)
                else:
                    txn.put(k, TOMBSTONE)
    except (lmdb.Error, OSError) as e:
        _report_store_problem(_store_problem_message(path, e))


# Read-only system-layer stores, cached separately from the writable user
# stores above: the same process never opens one path both ways (system store
# directories live under the system DB, user ones under the cache dir).
_lmdb_ro_envs: dict[str, lmdb.Environment] = {}

# System vector stores that failed to open: warned once, then treated as
# absent for the life of the process (cleared with the env caches).
_bad_system_stores: set[str] = set()


def _get_lmdb_env_readonly(path: str) -> lmdb.Environment:
    """Process-cached ``readonly=True, lock=False`` open (the system layer's
    discipline: the store is immutable for its whole installed life)."""
    with _lmdb_lock:
        env = _lmdb_ro_envs.get(path)
        if env is None:
            env = lmdb.open(path, readonly=True, lock=False)
            _lmdb_ro_envs[path] = env
        return env


def _try_system_store_env(path: str) -> 'lmdb.Environment | None':
    """THE guarded open for a system-layer vector store: None when the
    directory is absent or the store cannot be opened, with ONE warning per
    bad path per process (the §8 discipline — an unopenable system store
    degrades to "the system DB ships no store for this model", never a crash).
    Every system-vector-store consumer (the L23 resolver, fsck's shadowed
    count, export's embed-status merge) must come through here rather than
    calling _get_lmdb_env_readonly bare."""
    if path in _bad_system_stores or not os.path.isdir(path):
        return None
    try:
        return _get_lmdb_env_readonly(path)
    except lmdb.Error as e:
        import sys
        print(f"[Semantic_Embedding] WARNING: cannot open the system vector "
              f"store at {path}: {e}; running without it",
              file=sys.stderr, flush=True)
        _bad_system_stores.add(path)
        return None


def _close_all_lmdb_envs() -> None:
    with _lmdb_lock:
        for env in _lmdb_envs.values():
            env.close()
        _lmdb_envs.clear()
        for env in _lmdb_ro_envs.values():
            env.close()
        _lmdb_ro_envs.clear()
        _bad_system_stores.clear()

atexit.register(_close_all_lmdb_envs)


def _decode_q15(raw, D: int, k: key) -> np.ndarray:
    """Dequantize one stored Q1.15 value to float32.

    The value must be exactly D*2 bytes. A D*4 one is a leftover float32 record:
    reinterpreting it as int16 would yield a plausible-looking but wrong vector,
    so say what happened instead.
    """
    if len(raw) == D * 4:
        raise ValueError(
            f"vector for key {k.hex()[:16]}… is {D * 4} bytes (float32); this store "
            f"has not been migrated to Q1.15. Run the migration script first.")
    if len(raw) != D * 2:
        raise ValueError(
            f"vector for key {k.hex()[:16]}… is {len(raw)} bytes, expected {D * 2}")
    return np.frombuffer(bytes(raw), dtype="<i2").astype(np.float32) / Q15_SCALE


class Vector_Store(ABC):
    emb_provider : Embedding_Provider

    def __init__(self, path: str, emb_provider: Embedding_Provider,
                 connection: Connection | None = None):
        self.path = path
        self.emb_provider = emb_provider
        self.dimension = self.emb_provider.dimension
        self.connection = connection

    @property
    def _env(self) -> lmdb.Environment:
        return _get_lmdb_env(self.path)

    @property
    def _system_env(self) -> 'lmdb.Environment | None':
        """The system layer's store for THIS model (same directory basename
        under the system DB), or None -- the system DB ships vector stores for
        zero or more models (plan L14); alignment is store-by-store on name.

        An unopenable system store degrades to "the system DB ships no store
        for this model" with ONE warning (the §8 discipline, mirroring
        _Semantic_DB._ensure_system_env) -- never a crash loop: this property
        fronts every read, so raising here would fail every single lookup."""
        from .snapshot_sync import validated_system_db
        sysdb = validated_system_db()
        if sysdb is None:
            return None
        return _try_system_store_env(
            os.path.join(sysdb.path, os.path.basename(self.path)))

    def _raw_getter(self, stack: contextlib.ExitStack, *,
                    buffers: bool = False) -> 'Callable[[key], bytes | memoryview | None]':
        """A per-key raw vector lookup obeying **the vector-layer
        self-sufficiency invariant**: a vector question is answered by the
        vector stores alone.

        The user vector store has three states for any key, and they fully
        determine the answer.  The system store is consulted only on the third,
        and NO record store is consulted at all:

            real vector -> serve it
            tombstone   -> serve nothing (it masks any system vector)
            absent      -> fall through to the system vector

        This replaces the vector-record binding invariant (plan L23), whose own
        caveat is what failed: it assumed same-model-same-text determinism, and
        re-interpreting an entry breaks exactly that assumption -- the record
        changed, the vector did not, and nothing noticed.  What replaces the
        read-side check is write-side discipline: every writer of a record
        invalidates its vectors first (`invalidate_vectors`).  Unlike before
        there is NO backstop here, which is why that discipline is enumerated.

        Every transaction is entered on ``stack``, so the caller's ``with``
        block bounds their lifetime -- gathered buffers stay valid inside it.

        ``v if v else None`` rather than ``len(v) == 0``: it is the cheaper form
        (measured +1 to +5 ms per 100k-key gather for the whole closure) and
        ``bool(memoryview(b""))`` is already False, so it reads both the bytes
        and the buffers case.  The translation happens on EVERY return path
        INCLUDING the single-layer shortcut below -- the CI export runs
        single-layer and writes ``if vec is not None``, so an untranslated
        tombstone would be shipped into the published payload."""
        utxn = stack.enter_context(self._env.begin(buffers=buffers))
        senv = self._system_env
        if senv is None:
            uget = utxn.get

            def get_user_only(k: key):
                v = uget(k)
                return v if v else None
            return get_user_only
        svtxn = stack.enter_context(senv.begin(buffers=buffers))

        def get(k: key):
            v = utxn.get(k)
            if v is not None:
                return v if v else None          # tombstone masks the system vector
            return svtxn.get(k)
        return get

    def __getitem__(self, k: key) -> np.ndarray | None:
        """Return the vector for key k, dequantized to float32, or None.

        What comes back is the Q1.15 round-trip: a unit vector scaled to
        TARGET_NORM, not the provider's raw output. Nothing reads magnitudes back
        out of the store today; a caller that needs the original must re-embed.
        """
        with contextlib.ExitStack() as stack:
            raw = self._raw_getter(stack, buffers=True)(k)
            # `not raw`, not `is None`: defence in depth against a tombstone the
            # getter somehow failed to translate, which _decode_q15 would report
            # as a bogus 0-byte-vs-D*2 length error.
            if not raw:
                return None
            return _decode_q15(raw, self.dimension, k)

    def __contains__(self, k: key) -> bool:
        """Check whether key k has a vector under the vector-layer
        self-sufficiency invariant (a tombstone counts as absent)."""
        with contextlib.ExitStack() as stack:
            return self._raw_getter(stack)(k) is not None

    def __setitem__(self, k: key, vector: np.ndarray) -> None:
        """Store a vector for key k, quantized to Q1.15."""
        with self._env.begin(write=True) as txn:
            txn.put(k, encode_q15(vector).tobytes())

    def put(self, k: key, vector: np.ndarray) -> None:
        """Store a vector for key k. Alias for __setitem__."""
        self[k] = vector

    def delete(self, k: key) -> bool:
        """Delete the vector for key k from the LAYERED view of this store.
        Returns True if a vector was being served beforehand.

        A tombstone in the user layer, not a real deletion, and that is what
        makes it reach the system layer too: under the vector-layer
        self-sufficiency invariant a tombstone is what masks a system vector,
        while a real deletion of the user entry would let the system's copy show
        through -- so "delete" would leave the key still answering.

        Scoped to THIS store, unlike `invalidate_vectors`, which is the whole
        point of the distinction: this is a method on one model's store.
        Invalidating a record's vectors in every model is the record layer's job
        (`Semantic_DB.__setitem__` / `.delete`)."""
        served = k in self
        invalidate_vectors_in_store(self.path, [k])
        return served

    def contains(self, keys: list[key]) -> list[bool]:
        """Check existence for a batch of keys in a single transaction per layer.
        Follows the vector-layer self-sufficiency invariant: a key with no user
        vector but a system one counts as present, so completion runs never
        re-embed what the system DB ships; a tombstoned key counts as absent, so
        a re-interpreted record IS re-embedded."""
        with contextlib.ExitStack() as stack:
            get = self._raw_getter(stack)
            return [get(k) is not None for k in keys]

    async def embed(self, kv_pairs: list[tuple[key, str]]) -> int:
        """Embed texts via emb_provider and store the resulting vectors. Returns total tokens used."""
        texts = [text for _, text in kv_pairs]
        result = await self.emb_provider.embed(texts)
        with self._env.begin(write=True) as txn:
            for (k, _), vec in zip(kv_pairs, result.vectors):
                txn.put(k, encode_q15(vec).tobytes())
        return result.total_tokens

    async def _auto_embed(self, missing: list[key], ctxt: 'Any' = None,
                          interpret_in_auto_embed: 'bool | None' = None
                          ) -> list[key]:
        """Override to obtain and persist vectors for keys absent from the store.

        Called by topk before it opens its read transaction, so implementations
        are free to await. Whatever they persist is picked up by the subsequent
        gather; they need not hand the vectors back.  `ctxt` is the caller's ML
        context handle (None = the ML side's current command context), threaded
        down the lookup -> topk -> _auto_embed chain for config reads and the
        interpretation callback.  `interpret_in_auto_embed` is threaded the
        same way (the ctxt precedent): a per-call override of the store-level
        switch of the same name, None = take the store's value -- so one
        caller's policy (AoA passes False) can never leak into other consumers
        of a connection-cached store (review R7).
        Returns the keys that are now stored. Default: none recovered."""
        return []

    async def topk(self, query: np.ndarray | str, domain: list[key], k: int,
                   *, kinds_phrase: str | None = None,
                   ctxt: Any = None,
                   interpret_in_auto_embed: 'bool | None' = None
                   ) -> list[tuple[key, float]]:
        """Return the top-k (key, cosine) pairs from domain most similar to query.

        If query is a string, it is embedded via emb_provider first (role="query",
        with ``kinds_phrase`` filling the instruction's {kinds} slot).
        Keys missing from LMDB are passed to _auto_embed for recovery.

        Split in two phases. Everything that awaits — embedding the query, and
        recovering missing vectors — happens here, on the event loop. The scan
        itself runs in a worker thread, because py-lmdb read transactions are
        bound to the thread that opened them and must not span an await.
        """
        # The one reliably connection-aware point every query passes through:
        # relay anything _get_lmdb_env logged with no connection in hand.
        await flush_store_warnings(self.connection)
        if isinstance(query, str):
            if self.connection is not None:
                await self.connection.tracing(f"[Semantic_Embedding] embedding query: {query!r}")
            # A string input to topk is a search query -> use the query template
            # (Instruct/query: prefix) with the caller's kinds_phrase. Corpus text
            # is embedded as role="document" elsewhere. lookup() keeps passing the
            # *string* here, so its reranker gate (isinstance(query, str)) is unaffected.
            query = (await self.emb_provider.embed(
                [query], role="query", kinds_phrase=kinds_phrase)).vectors[0]

        query_q15 = encode_q15(query)
        # The scan runs in a worker thread; ctypes releases the GIL for the kernel
        # call, so the event loop keeps running instead of freezing for the scan.
        # Missing keys fall out of the gather itself — probing for them up front
        # would mean a second pass over the whole domain on the event loop.
        results, missing = await asyncio.to_thread(self._topk_sync, query_q15, domain, k)
        if missing and await self._auto_embed(
                missing, ctxt=ctxt,
                interpret_in_auto_embed=interpret_in_auto_embed):
            results, _ = await asyncio.to_thread(self._topk_sync, query_q15, domain, k)
        return results

    def _topk_sync(self, query_q15: np.ndarray, domain: list[key],
                   k: int) -> tuple[list[tuple[key, float]], list[key]]:
        """Gather the domain's vectors straight out of the LMDB mmap and scan them.

        Nothing is copied: each address points at a value inside the transaction's
        MVCC snapshot, and the SIMD kernel reads it in place. Two consequences —
        the kernel must run before the transaction closes, and a value whose length
        is not exactly D*2 (a pre-migration float32 record, say) would be read as a
        truncated vector, so those are skipped rather than trusted.
        """
        D = self.dimension
        expected = D * 2
        # Sorting turns ~10^5 scattered b-tree lookups into a near-sequential walk
        # of the file; measured 2.9 -> 7.95 GB/s on the production store. Duplicates
        # then sit next to each other, so dropping them costs a comparison rather
        # than the ~48ms a set() of 10^5 keys takes.
        ordered = sorted(domain)
        keys = [dk for i, dk in enumerate(ordered) if i == 0 or dk != ordered[i - 1]]
        # Per-key resolution follows the vector-layer self-sufficiency invariant
        # (_raw_getter), which translates a tombstone to None -- so `b""` never
        # reaches gather_addrs, which would classify it as *skipped* (wrong: the
        # correct classification is *missing*, which sends it to _auto_embed) and
        # print the Q1.15-migration warning on every query.  The
        # ExitStack keeps every layer's read transaction open past the kernel
        # call: the memoryviews' addresses point into those transactions'
        # snapshots of the mmaps, and nothing is copied.
        with contextlib.ExitStack() as stack:
            get = self._raw_getter(stack, buffers=True)
            buffers = [get(dk) for dk in keys]
            addrs, kept, missing_at, skipped = gather_addrs(buffers, expected)
            if skipped:
                print(f"[Semantic_Embedding] topk skipped {skipped} record(s) whose size "
                      f"is not {expected} bytes; the store may not be migrated to Q1.15")
            missing = [keys[int(i)] for i in missing_at]
            if addrs.size == 0:
                return [], missing
            idx, cos = top_k_q15_gather(addrs, query_q15, D, min(k, int(addrs.size)))
            results = [(keys[int(kept[int(i)])], float(c)) for i, c in zip(idx, cos)]
        return results, missing