r"""The site export (SEMANTIC_SEARCH_SITE_PLAN.md §8): the semantic DB becomes a
turbopuffer namespace.

One run does §8.1's steps in their order, and each of the four guards below stops it
loudly rather than let it publish something wrong:

* **the component guard (D46)** — the asset this machine builds is compared with the
  committed asset of the previous export, and a changed symbol-file list, a changed
  `tokenizer_rule` or a changed digest stops the run.  Registering an unrelated
  Isabelle component moves the asset digest, and the digest names the namespace
  (§8.2), so without this the export would quietly build a differently-named index;
* **the completeness gate (§8.1 step 1)** — every shippable record must have a
  vector.  The vector store is a lazy cache and a missing vector is legal in normal
  operation, which is exactly why the export cannot treat it as normal;
* **the separator probe (§8.1 step 0b)** — one upsert into a test namespace,
  checking that turbopuffer stores and indexes the whitespace-only element that
  keeps a `ContainsTokenSequence` from straddling two theory names (§6.3).  It runs
  on every export rather than once by hand, because §8.2 makes every export a fresh
  namespace and a wrong separator is only visible as a theory filter that matches a
  name no theory has;
* **the fresh-namespace guard (§8.2)** — a namespace that already exists is refused
  unless this run is continuing from its own checkpoint.  turbopuffer cannot drop
  what a batch omits, so an upsert into a live namespace leaves every deleted entity
  behind forever.

Nothing here holds the corpus in memory: records stream out of the store in key
order and go up in batches, so a re-run resumes where the last one stopped.
"""
from __future__ import annotations

import argparse
import base64
import glob
import hashlib
import itertools
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator

import numpy as np

from ._paths import semantic_DB_dir


class ExportError(RuntimeError):
    """Anything that must stop the export."""


def _log(msg: str) -> None:
    print(f"[site-export] {msg}", flush=True)


# ---------------------------------------------------------------------------
# §8.1 step 0 — scope (D24)
# ---------------------------------------------------------------------------

# Isabelle's four prefix-less base logics, which genuinely have no session and are
# members by D24's own clause.
BASE_LOGICS = frozenset({"Pure", "FOL", "IFOL", "ZF"})

# `session NAME …` or `session "NAME" …` opening a ROOT entry.  The quoted
# alternative is not decoration: `session "CoreC++"` is a real AFP session whose
# name contains a character an unquoted name cannot, and a reader that misses it
# puts 2,915 published records out of scope with no error anywhere.
_SESSION = re.compile(r'^\s*session\s+(?:"([^"]*)"|([^\s"(]+))')


def _uncommented(text: str) -> str:
    """ROOT text with `(* … *)` removed, nesting honoured.  A commented-out session
    is not a declared session; six of them sit in the two trees."""
    out, depth, i = [], 0, 0
    while i < len(text):
        if text.startswith("(*", i):
            depth += 1
            i += 2
        elif text.startswith("*)", i) and depth:
            depth -= 1
            i += 2
        else:
            if not depth:
                out.append(text[i])
            i += 1
    return "".join(out)


def declared_sessions(*trees: str) -> set[str]:
    """D24's declared-session set: every session declared by a ROOT file anywhere
    under these directory trees, plus the base logics.

    Read from the ROOT files rather than from `isabelle sessions`, which answers a
    different question: it enumerates what is *registered* on this machine, so it
    also returns this repository's own sessions — 861 of them here — and D24's scope
    is the two trees and nothing else."""
    found = set()
    for tree in trees:
        for root in glob.glob(os.path.join(tree, "**", "ROOT"), recursive=True):
            with open(root, encoding="utf-8", errors="replace") as f:
                text = _uncommented(f.read())
            for line in text.splitlines():
                m = _SESSION.match(line)
                if m:
                    found.add(m.group(1) or m.group(2))
    if not found:
        raise ExportError(f"no ROOT file under any of {trees} declares a session")
    return found | set(BASE_LOGICS)


def session_of(theory: str) -> str:
    """The session a theory long name belongs to.  A base logic has no prefix, so a
    name with no dot is its own session."""
    return theory.split(".", 1)[0]


# ---------------------------------------------------------------------------
# §8.1 steps 2 to 5 — one record becomes one document
# ---------------------------------------------------------------------------

# §6.3.  The tokenizer discards whitespace and can therefore never emit this, so no
# query can contain it, and it is injected here rather than produced by the
# tokenizer so subtoken formation never sees it.  The user chose it on 2026-08-09;
# `check_theory_separator` is what tests that turbopuffer keeps it.
THEORY_SEPARATOR = "\n"


def _hash128(*parts: bytes) -> bytes:
    """A deterministic 128-bit hash of a sequence of byte strings.  Each part is
    length-prefixed, so no two different sequences hash alike by running together."""
    h = hashlib.blake2b(digest_size=16)
    for part in parts:
        h.update(len(part).to_bytes(8, "big"))
        h.update(part)
    return h.digest()


def document_id(key: bytes) -> str:
    """§6.2.  The universal key runs to 308 bytes and 6.34 % of them exceed
    turbopuffer's 64-byte string-id limit once encoded, so the id is a 128-bit hash
    of the key rendered as a UUID and the key itself rides as an attribute.
    Deterministic, so a re-export upserts in place instead of duplicating."""
    return str(uuid.UUID(bytes=_hash128(key)))


def group_of(name: str, expr: str) -> str:
    """§6.1's `group`: the identity of the entity page (§9.4) and the key the
    response collapses on (D5).  One `(name, entity expression)` pair, one group."""
    return _hash128(name.encode("utf-8"), expr.encode("utf-8")).hex()


def clean_for_display(expr: str) -> str:
    r"""§8.3.  What a card shows, not what matches: `\r` satisfies §5.2's whitespace
    test and is discarded before token formation either way.

    §8.3 opens with `repair_del`, which no longer exists anywhere — §10 finished, the
    238 affected records were repaired one at a time and D11 closed the route that
    wrote the character, so what is left of that pipeline is this one line."""
    return expr.replace("\r\n", "\n").replace("\r", "\n")


def theory_subtokens(theories: 'list[str]', tokenize) -> 'list[str]':
    """§6.3.  The subtokens of every theory name, one separator element between
    names, so a `ContainsTokenSequence` cannot match a sequence that straddles two of
    them — `[HOL.List, Affine_Arithmetic.Foo]` must not answer to `List
    Affine_Arithmetic`, which is no theory's name."""
    out: 'list[str]' = []
    for theory in theories:
        if out:
            out.append(THEORY_SEPARATOR)
        out.extend(tokenize(theory))
    return out


# §6.1, in its order.  The schema and the document builder below are two halves of
# one statement and must be read together.
def namespace_schema(dimension: int) -> dict:
    pre_tokenized = {"type": "[]string",
                     "full_text_search": {"tokenizer": "pre_tokenized_array",
                                          "case_sensitive": True,
                                          "stemming": False,
                                          "remove_stopwords": False}}
    return {
        "id": "uuid",
        "group": {"type": "string", "filterable": True},
        "vector": {"type": f"[{dimension}]f16", "ann": True},
        # display
        "key": {"type": "string", "filterable": False},
        "name": {"type": "string", "filterable": False},
        "expr": {"type": "string", "filterable": False},
        "theories": {"type": "[]string", "filterable": False},
        "kind": {"type": "string", "filterable": True},
        "position": {"type": "string", "filterable": False},
        "from_collection": {"type": "string", "filterable": False},
        # filtering — one declaration for all three, which is D23: the `All` panel
        # Ors one typed string across them, so a field that tokenised differently
        # would make the same string mean different things inside one condition.
        "expr_subtokens": pre_tokenized,
        "name_subtokens": pre_tokenized,
        "theory_subtokens": pre_tokenized,
        # ranking
        "interpretation": {"type": "string",
                           "full_text_search": {"case_sensitive": False,
                                                "stemming": True,
                                                "remove_stopwords": True}},
    }


def build_document(key: bytes, rec, theories: 'list[str]', vector: np.ndarray,
                   tokenize) -> dict:
    """§8.1 steps 2 to 5 for one record.

    `name_subtokens` comes from the raw `name` and never from the displayed form: a
    member of a dynamic fact collection is displayed as `<from_collection>(_)`, but
    the Worker emits one filter for the whole namespace and cannot route a member row
    to a different field, so a pasted `coll(_)` matches nothing — intended, and ruled
    on 2026-08-19 (§8.1 step 5)."""
    name = rec.name or ""
    expr = rec.expr or ""
    return {
        "id": document_id(key),
        "group": group_of(name, expr),
        "vector": base64.b64encode(
            vector.astype("<f4", copy=False).tobytes()).decode("ascii"),
        "key": base64.urlsafe_b64encode(key).decode("ascii"),
        "name": name,
        "expr": clean_for_display(expr),
        "theories": theories,
        "kind": rec.kind.label,
        "position": (f"{rec.position[0]}:{rec.position[1]}" if rec.position else ""),
        "from_collection": rec.from_collection or "",
        "expr_subtokens": tokenize(expr),
        "name_subtokens": tokenize(name),
        "theory_subtokens": theory_subtokens(theories, tokenize),
        "interpretation": rec.interpretation or "",
    }


# ---------------------------------------------------------------------------
# §7 — the theories a record is filtered by, and §8.1 step 1's gate
# ---------------------------------------------------------------------------

def theory_registry() -> 'dict[bytes, str]':
    """The whole theory-hash registry in memory: 16-byte hash to theory long name
    (§7.3).  Ten thousand entries against two hundred thousand name-addressed
    records, so reading it once beats a point lookup per record.

    A hash does not determine one long name — byte-identical theory text vendored
    into a second session gets one hash under two names, measured at 2 cases of 9,214
    — and the registry keeps whichever was written last.  That caveat is
    THEORY_HASH_REGISTRY_PLAN.md's R9 and this plan honours it rather than fixing
    it."""
    from . import theory_hash_registry
    return {k: theory_hash_registry.decode_entry(v)[0]
            for k, v in theory_hash_registry.iter_items()}


def theories_of(key: bytes, rec, registry: 'dict[bytes, str]') -> 'list[str]':
    """D14: the constituent theories of a theorem-alike entity, the declaring theory
    of a name-addressed one.

    A theorem-alike key's 16-byte prefix is an XOR pseudo-theory and must never be
    looked up as a real theory (D13), which is why the two cases are told apart by
    the key's shape and not by whether the record happens to carry constituents."""
    from Isabelle_RPC_Host.universal_key import is_xor_prefixed_key
    if is_xor_prefixed_key(key):
        if rec.theory_constituents is None:
            raise ExportError(
                f"{rec.name!r} is content-addressed and carries no constituent "
                f"theories, so nothing can say which theories it lives in")
        return [name for name, _ in rec.theory_constituents]
    name = registry.get(key[:16])
    if name is None:
        raise ExportError(
            f"the declaring theory of {rec.name!r} (hash {key[:16].hex()}) is not in "
            f"the theory-hash registry, so D24's scope test cannot be applied to it")
    return [name]


def vector_store_path(explicit: 'str | None' = None) -> str:
    """The one vector store this export publishes from."""
    from .semantic_embedding import vector_store_names
    if explicit:
        return explicit
    names = vector_store_names()
    if len(names) != 1:
        raise ExportError(
            f"expected exactly one vector store, found {names}; name the one to "
            f"publish with --vector-store")
    return os.path.join(semantic_DB_dir(), names[0])


def vector_reader(stack, path: str):
    """`(get, dimension)`, where `get(key)` is the record's float32 vector or None.

    Reads the layered stores directly rather than through `Semantic_Vector_Store`,
    which would want an embedding provider and therefore an API key the export has
    no use for — the same shell `snapshot_sync.export` uses."""
    from .snapshot_sync import _model_of, _local_dimension
    from .semantic_embedding import Vector_Store, _decode_q15
    model = _model_of(os.path.basename(path))
    dimension = _local_dimension(model) if model else None
    if dimension is None:
        raise ExportError(f"no configured dimension for the model of {path}")
    shell = Vector_Store.__new__(Vector_Store)
    shell.path = path
    raw_get = shell._raw_getter(stack)

    def get(key: bytes):
        raw = raw_get(key)
        return None if raw is None else _decode_q15(raw, dimension, key)

    return get, dimension


def completeness_gate(get_vector) -> int:
    """§8.1 step 1: every **shippable** record has a vector, or the export stops.

    Shippable is `snapshot_sync._ships_predicate()` — imported, never restated: it
    drops WIP keys, and a restatement of it is what produced the 8,908 figure the
    user rejected on 2026-08-12.  The vector store is a lazy cache and a missing
    vector is legal in normal operation, so publishing around one would quietly ship
    a corpus with holes."""
    from .semantics import Semantic_DB
    from .snapshot_sync import _ships_predicate
    ships = _ships_predicate()
    shippable = missing = 0
    examples: 'list[str]' = []
    for key, raw in Semantic_DB.iter_items():
        if len(key) == 16 or not ships(key, raw):
            continue
        shippable += 1
        if get_vector(key) is None:
            missing += 1
            if len(examples) < 5:
                examples.append(key.hex())
    if missing:
        raise ExportError(
            f"{missing} of {shippable} shippable records have no vector "
            f"(e.g. {', '.join(examples)}); embed them before exporting")
    return shippable


# ---------------------------------------------------------------------------
# §8.1 step 6 and §8.2 — the asset, the component guard, the namespace name
# ---------------------------------------------------------------------------

def committed_asset_path() -> str:
    """Where the previous export's asset is, which is also where the CI gate and the
    JavaScript port read theirs (§16.6).  One file, so the invariant that makes the
    comparison meaningful — the committed asset is the deployed asset — needs no
    second declaration to keep in step."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "site", "tokenizer", "asset.json")


def asset_differences(committed_text: str, asset: dict, digest: str) -> 'list[str]':
    """The three counts D46's guard compares, in words: the `ISABELLE_SYMBOLS` file
    list, the `tokenizer_rule` version and the digest.

    All three, not the digest alone: the digest catches a table change but says
    nothing about *what* changed, and the file list is the thing D46 names as the
    declaration.  The `tokenizer_rule` comparison is what sees a rule change at all —
    a rule that touches no table leaves the other two untouched."""
    committed = json.loads(committed_text)
    committed_digest = hashlib.sha256(committed_text.encode("utf-8")).hexdigest()
    changes = []
    if committed.get("symbol_files") != asset["symbol_files"]:
        changes.append("the symbol files changed:\n"
                       f"  committed {json.dumps(committed.get('symbol_files'))}\n"
                       f"  this run  {json.dumps(asset['symbol_files'])}")
    if committed.get("tokenizer_rule") != asset["tokenizer_rule"]:
        changes.append(f"tokenizer_rule went from {committed.get('tokenizer_rule')!r} "
                       f"to {asset['tokenizer_rule']!r}")
    if committed_digest != digest:
        changes.append(f"the asset digest went from {committed_digest[:12]} to "
                       f"{digest[:12]}")
    return changes


def emit_asset(path: str, *, change_intended: bool) -> 'tuple[dict, str, str]':
    """§8.1 step 6 and D46's guard.  Returns `(asset, text, sha256)`, and does NOT
    write: the committed asset is the *deployed* asset, so it is replaced only once
    the namespace it names exists (`commit_asset`).

    Builds the asset from this installation's symbol table and compares it with the
    committed one on three counts: the `ISABELLE_SYMBOLS` file list, the
    `tokenizer_rule` version and the digest.  Any of the three moving means the
    namespace name moves (§8.2), so an unannounced change stops the export instead of
    quietly building a differently-named index — registering an unrelated Isabelle
    component is exactly that case, and changes not one published document.

    The `tokenizer_rule` comparison is the one that catches a rule change: a rule
    that touches no table leaves the file list and the digest alone."""
    from . import tokenizer_asset
    asset = tokenizer_asset.build_asset()
    text = tokenizer_asset.serialize(asset)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    if not os.path.isdir(os.path.dirname(path)):
        raise ExportError(
            f"{os.path.dirname(path)} does not exist, so there is nowhere to compare "
            f"this export's asset against the last one's (D46); pass "
            f"--committed-asset to say where it lives")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            changes = asset_differences(f.read(), asset, digest)
        if changes and not change_intended:
            raise ExportError(
                "this export's tokenizer asset is not the committed one (D46):\n  "
                + "\n  ".join(changes)
                + "\nRe-run with --asset-change-intended if that is meant; the "
                  "namespace name carries the digest, so this writes a new index.")
        if changes:
            _log("the asset changed and the change was declared intended:")
            for change in changes:
                _log("  " + change.replace("\n", "\n  "))
    else:
        _log(f"no committed asset at {path}: this export writes the baseline")

    return asset, text, digest


def commit_asset(path: str, text: str) -> None:
    """Record this export's asset as the one the next export compares against."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def namespace_name(isabelle_home: str, afp_dir: str, asset_digest: str) -> str:
    """§8.2: `isasearch-<isabelle release>-<afp snapshot>-<asset digest, 12 hex>`.

    The digest is in the name so that "new index, old asset" is unconstructible: a
    Worker holding an older asset addresses the namespace that asset built and simply
    finds the old index."""
    release = os.path.basename(os.path.normpath(isabelle_home))
    if release.startswith("Isabelle"):
        release = release[len("Isabelle"):]
    snapshot = os.path.basename(os.path.normpath(afp_dir))
    return f"isasearch-{release}-{snapshot}-{asset_digest[:12]}"


# ---------------------------------------------------------------------------
# turbopuffer
# ---------------------------------------------------------------------------

# §6.4 and D18: every region-bearing component goes in North America, co-located
# with the Fireworks origin.  Which North American region is second-order and
# reversible — turbopuffer has `copy_from_namespace`.
DEFAULT_REGION = "aws-us-west-2"

# §12.1: no key lives in this repository, in any form.  The user's key sits in
# ~/Current/MLML/secret.sh, outside the tree, under a different name; bridge it with
#     source ~/Current/MLML/secret.sh && export TURBOPUFFER_API_KEY="$turbopuffer_DEV_KEY"
API_KEY_ENV = "TURBOPUFFER_API_KEY"

_RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def api_key() -> str:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise ExportError(
            f"{API_KEY_ENV} is not set. The key is not in this repository and must "
            f"not be put in it (§12.1); source secret.sh and export it under this "
            f"name.")
    return key


def request(method: str, path: str, body: 'dict | None' = None, *,
            region: str, key: str, attempts: int = 6) -> dict:
    """One turbopuffer API call, retried on the failures that are worth retrying.

    A full export is tens of gigabytes over thousands of requests, so a transient
    502 must not cost the run; a 4xx that is not a rate limit is a mistake in what we
    sent and is raised at once."""
    url = f"https://{region}.turbopuffer.com{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = resp.read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if e.code not in _RETRY_STATUS or attempt == attempts:
                raise ExportError(
                    f"{method} {path} -> HTTP {e.code}: {detail}") from None
            reason = f"HTTP {e.code}: {detail}"
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if attempt == attempts:
                raise ExportError(f"{method} {path} failed: {e}") from None
            reason = str(e)
        delay = min(2 ** attempt, 60)
        _log(f"{method} {path}: {reason}; retrying in {delay}s "
             f"({attempt}/{attempts - 1})")
        time.sleep(delay)
    raise AssertionError("unreachable")


def refuse_an_existing_namespace(namespace: str, *, region: str, key: str) -> None:
    """§8.2: every export writes into a **new** namespace, and this is what makes
    that true rather than intended.

    turbopuffer has no "delete everything absent from this batch" operation, so an
    upsert into a live namespace leaves every deleted entity behind forever, and the
    instant rollback §8.2 exists to give is gone with it.  The name is built from the
    Isabelle release, the AFP snapshot and the asset digest, so two exports of
    *different corpora* under one release and one asset ask for one name — this is
    where that collision surfaces, loudly, instead of becoming a silent upsert.

    A run that is continuing from a checkpoint does not come here: for it the
    namespace existing is the whole point."""
    try:
        request("GET", f"/v2/namespaces/{namespace}/metadata", region=region, key=key)
    except ExportError as e:
        # A bare 404 is not enough: a mistyped path answers 404 too, and reading that
        # as "the namespace is free" is how this guard would come to wave everything
        # through.  turbopuffer says which of the two it is.
        if "HTTP 404" in str(e) and "was not found" in str(e):
            return
        raise
    raise ExportError(
        f"the namespace {namespace} already exists. §8.2 writes every export into a "
        f"fresh one, because turbopuffer cannot drop what a batch omits and an "
        f"upsert would leave deleted entities behind forever. Either this export is "
        f"a re-run whose checkpoint was lost, or the data changed under an unchanged "
        f"Isabelle release, AFP snapshot and tokenizer asset — in which case the "
        f"name does not distinguish it and that is a question for the plan, not a "
        f"thing to override.")


def check_theory_separator(*, region: str, key: str,
                           namespace: str = "isasearch-separator-probe") -> None:
    """§8.1 step 0b: does turbopuffer keep a whitespace-only element of a
    `pre_tokenized_array`?

    `theory_subtokens` puts one such element between two theory names so that a
    `ContainsTokenSequence` cannot match across them (§6.3).  If the element is
    dropped the straddle comes back, and the only symptom is a theory filter that
    matches a name no theory has.  So the export asks, every time, against a
    throwaway namespace: the negative query must find nothing and the positive one
    must find the document, the second being there so that a query that is simply
    broken cannot pass as a separator that works."""
    schema = {"id": "uuid",
              "vector": {"type": "[2]f32", "ann": True},
              "theory_subtokens": namespace_schema(2)["theory_subtokens"]}
    doc_id = str(uuid.UUID(bytes=_hash128(b"separator probe")))
    request("POST", f"/v2/namespaces/{namespace}", {
        "distance_metric": "cosine_distance",
        "schema": schema,
        "upsert_rows": [{"id": doc_id, "vector": [1.0, 0.0],
                         "theory_subtokens": ["HOL", "List", THEORY_SEPARATOR,
                                              "Affine_Arithmetic", "Foo"]}],
    }, region=region, key=key)
    try:
        def matches(sequence):
            got = request("POST", f"/v2/namespaces/{namespace}/query", {
                "rank_by": ["id", "asc"], "top_k": 2,
                "filters": ["theory_subtokens", "ContainsTokenSequence", sequence],
            }, region=region, key=key)
            return [row["id"] for row in got.get("rows", [])]

        if matches(["HOL", "List"]) != [doc_id]:
            raise ExportError(
                "the separator probe's positive query matched nothing, so the probe "
                "cannot say anything about the separator; fix the probe first")
        straddle = matches(["List", "Affine_Arithmetic"])
        if straddle:
            raise ExportError(
                f"turbopuffer dropped the whitespace-only separator element: a "
                f"sequence straddling two theory names matched {straddle}. "
                f"THEORY_SEPARATOR must become a non-whitespace character the "
                f"tokenizer cannot emit — and replacing it replaces the user's own "
                f"choice of 2026-08-09, so ask him (§6.3).")
    finally:
        request("DELETE", f"/v2/namespaces/{namespace}", region=region, key=key)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

# One request carries at most this many rows or this many bytes, whichever comes
# first.  turbopuffer allows 512 MB and 8 MiB per attribute; these are far below
# both, because a batch is also the unit a failure costs and the unit the
# checkpoint advances by.
BATCH_ROWS = 256
BATCH_BYTES = 24 << 20


def iter_documents(sessions, registry, get_vector, tokenize,
                   counts) -> 'Iterator[tuple[bytes, dict]]':
    """§8.1 steps 0 and 2 to 5, one record at a time, in key order.

    Key order matters twice: it is what makes a re-run resumable from a checkpoint,
    and it is what makes two runs over the same store produce the same sequence."""
    from Isabelle_RPC_Host.universal_key import EntityKind
    from .semantics import Semantic_DB
    from .snapshot_sync import _ships_predicate
    ships = _ships_predicate()
    for key, raw in Semantic_DB.iter_items():
        if len(key) == 16:
            continue                              # a per-theory cost record
        if not ships(key, raw):
            # Also where the one-byte global version counter goes: `_ships` reads
            # a key shorter than a theory hash as something no artifact carries.
            counts["wip"] += 1
            continue
        counts["records"] += 1
        try:
            rec = Semantic_DB._decode(raw)
        except Exception:
            counts["undecodable"] += 1            # legacy, or not an entity at all
            continue
        if rec.kind == EntityKind.EXPERIENCE:
            counts["experience"] += 1             # step 0: never published (D24)
            continue
        theories = theories_of(key, rec, registry)
        if not all(session_of(t) in sessions for t in theories):
            counts["out of scope"] += 1
            continue
        vector = get_vector(key)
        if vector is None:
            raise ExportError(f"{rec.name!r} lost its vector between the "
                              f"completeness gate and the export")
        counts["exported"] += 1
        yield key, build_document(key, rec, theories, vector, tokenize)


def _batches(documents, rows: int, size: int):
    """Documents grouped into upsert batches, with the last key of each batch."""
    batch, batch_bytes, last = [], 0, None
    for key, doc in documents:
        batch.append(doc)
        batch_bytes += len(doc["vector"]) + len(doc["interpretation"]) + len(doc["expr"])
        last = key
        if len(batch) >= rows or batch_bytes >= size:
            yield batch, last
            batch, batch_bytes = [], 0
    if batch:
        yield batch, last


def _read_checkpoint(path: str, namespace: str) -> 'tuple[bytes, int] | None':
    """The last key the previous run got confirmation for and how many documents it
    had upserted by then, or None when there is nothing to resume."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    if state.get("namespace") != namespace:
        raise ExportError(
            f"{path} belongs to namespace {state.get('namespace')!r}, not "
            f"{namespace!r}; delete it or point --checkpoint elsewhere")
    _log(f"resuming after {state['documents']} document(s) already upserted")
    return bytes.fromhex(state["last_key"]), int(state["documents"])


def _write_checkpoint(path: str, namespace: str, last: bytes, done: int) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"namespace": namespace, "last_key": last.hex(),
                   "documents": done}, f)
    os.replace(tmp, path)


def run(*, isabelle_home: str, afp_dir: str, committed_asset: str,
        vector_store: 'str | None', region: str, dump: 'str | None',
        checkpoint: str, limit: 'int | None', change_intended: bool,
        skip_gate: bool) -> str:
    """§8.1 end to end.  Returns the namespace that was written."""
    import contextlib
    from . import isabelle_tokenizer

    asset, text, digest = emit_asset(committed_asset,
                                     change_intended=change_intended)
    namespace = namespace_name(isabelle_home, afp_dir, digest)
    _log(f"asset {digest[:12]} (tokenizer_rule {asset['tokenizer_rule']}), "
         f"namespace {namespace}")

    key = None if dump else api_key()
    if key:
        check_theory_separator(region=region, key=key)
        _log("the theory separator survives a round trip (step 0b)")

    sessions = declared_sessions(isabelle_home, afp_dir)
    _log(f"{len(sessions)} declared session(s) in scope (D24)")
    tokenize = isabelle_tokenizer.Tokenizer(asset)
    registry = theory_registry()
    _log(f"{len(registry)} theory-hash registry entr(ies)")

    path = vector_store_path(vector_store)
    with contextlib.ExitStack() as stack:
        get_vector, dimension = vector_reader(stack, path)
        if skip_gate:
            _log("SKIPPING the completeness gate at your request (§8.1 step 1)")
        else:
            _log(f"completeness gate over {os.path.basename(path)}...")
            _log(f"  {completeness_gate(get_vector)} shippable record(s), "
                 f"every one with a vector")

        counts: 'dict[str, int]' = dict.fromkeys(
            ("records", "undecodable", "wip", "experience", "out of scope",
             "exported"), 0)
        documents = iter_documents(sessions, registry, get_vector, tokenize, counts)
        resumed = None if dump else _read_checkpoint(checkpoint, namespace)
        if resumed is not None:
            resume_after, done = resumed
            documents = ((k, d) for k, d in documents if k > resume_after)
        else:
            done = 0
        if limit:
            documents = itertools.islice(documents, limit)

        if dump:
            with open(dump, "w", encoding="utf-8") as f:
                for _key, doc in documents:
                    f.write(json.dumps(doc, ensure_ascii=False) + "\n")
            _log(f"wrote {counts['exported']} document(s) to {dump}")
        else:
            if resumed is None:
                refuse_an_existing_namespace(namespace, region=region, key=key)
            schema = namespace_schema(dimension)
            for batch, last in _batches(documents, BATCH_ROWS, BATCH_BYTES):
                request("POST", f"/v2/namespaces/{namespace}",
                        {"distance_metric": "cosine_distance", "schema": schema,
                         "upsert_rows": batch}, region=region, key=key)
                done += len(batch)
                _write_checkpoint(checkpoint, namespace, last, done)
                if done % (BATCH_ROWS * 40) == 0:
                    _log(f"  {done} document(s) upserted")
            _log(f"upserted {done} document(s) into {namespace}")

    if not dump and not limit:
        # The committed asset declares what is DEPLOYED (D46), so only a run that
        # deployed the whole corpus may move it.
        commit_asset(committed_asset, text)
    for what, n in counts.items():
        _log(f"  {what:<14} {n}")
    return namespace


def _default_trees() -> 'tuple[str, str]':
    """The Isabelle distribution and the AFP snapshot, from Isabelle's own settings.

    `AFP` points at the snapshot's `thys` directory — it is what the stored entity
    positions abbreviate as `$AFP` — so D24's tree is its parent."""
    from Isabelle_RPC_Host.paths import resolve_isabelle_var
    home = resolve_isabelle_var("ISABELLE_HOME")
    afp = resolve_isabelle_var("AFP")
    if not home or not afp:
        raise ExportError(
            "cannot locate Isabelle and the AFP: ISABELLE_HOME and AFP are both "
            "needed, from the environment or from `isabelle getenv`")
    return home, os.path.dirname(os.path.normpath(afp))


def build_parser(**kw) -> argparse.ArgumentParser:
    """THE option set, stated once.  `isabelle_semantics.py` adopts this parser as its
    `site-export` subparser's parent, so the two ways in cannot drift."""
    p = argparse.ArgumentParser(
        prog="isabelle-semantics site-export",
        description="Export the semantic DB into a turbopuffer namespace (§8).",
        **kw)
    p.add_argument("--isabelle-home", help="the distribution tree (default: $ISABELLE_HOME)")
    p.add_argument("--afp", help="the AFP snapshot tree (default: the parent of $AFP)")
    p.add_argument("--committed-asset", default=committed_asset_path(),
                   help="the previous export's asset, which D46 compares against")
    p.add_argument("--vector-store", help="the vector store to publish from")
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--dump", metavar="PATH",
                   help="write the documents as JSON lines instead of upserting; "
                        "touches no network and needs no key")
    p.add_argument("--checkpoint", default="site-export.checkpoint.json",
                   help="where to record upsert progress, so a re-run continues "
                        "instead of starting over")
    p.add_argument("--limit", type=int, help="stop after this many documents")
    p.add_argument("--asset-change-intended", action="store_true",
                   help="accept an asset that differs from the committed one (D46)")
    p.add_argument("--skip-completeness-gate", action="store_true",
                   help="do not check that every shippable record has a vector; "
                        "for a --limit run, never for a real export")
    return p


def run_from_args(args: argparse.Namespace) -> int:
    """The body both entry points share: locate the trees, run, report a failure."""
    try:
        home, afp = args.isabelle_home, args.afp
        if not (home and afp):
            found_home, found_afp = _default_trees()
            home, afp = home or found_home, afp or found_afp
        run(isabelle_home=home, afp_dir=afp,
            committed_asset=args.committed_asset, vector_store=args.vector_store,
            region=args.region, dump=args.dump,
            checkpoint=args.checkpoint,
            limit=args.limit, change_intended=args.asset_change_intended,
            skip_gate=args.skip_completeness_gate)
    except ExportError as e:
        print(f"[site-export] {e}", file=sys.stderr)
        return 1
    return 0


def main(argv: 'list[str] | None' = None) -> int:
    return run_from_args(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
