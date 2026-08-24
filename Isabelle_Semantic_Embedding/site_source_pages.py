r"""The source-page upload pass (SEMANTIC_SEARCH_SITE_PLAN.md §17): the rendered
tree becomes the published tree, and every namespace row gains its finished
source link.

Five steps, run as subcommands, on the machines §17.1 assigns them to:

* **scan** — the corpus scan, on the machine with the semantic DB: walks exactly
  the record set the site export publishes (`site_export.iter_shippable`, one
  filter chain for both) and writes the per-record position triples plus the
  declaring-theory evidence the map's cross-check consumes.
* **map** — on cslh19, beside the rendered tree, the authoritative registry and
  the source trees: derives every rendered page's theory long name (D52),
  builds the file→page map by one lookup over `data/theories.json` (D53, with
  the three staleness gates and the declaring-hash zero-conflict cross-check),
  and seals classification, map and positions into **one artefact whose
  content hash every later step re-checks** — no step ever reads "whichever
  table this machine happens to have".
* **publish** — the pass itself (§17.4), on cslh19: relocates the kept pages
  under their long names, rewrites every site-internal reference, passes
  site-external references through byte-identically (D50), strips
  input-dangling anchors with a WARNING each (D51), injects the needed line
  marks, merges the conflicting auxiliary copies by id-union (D49 ruling 6),
  and generates the index and the one stylesheet — all into a fresh directory
  atomically renamed into place, removed again if the pass fails, and never a
  directory it was handed.
* **gate** — the link-check gate (§17.5) over the published tree: zero misses
  on marks and references, every fragment checked, no anchor trusted;
  site-external references exempt and counted (D50).  The report's two
  standing counters — stripped input-dangling references and exempted
  site-external references — are the alarm every future data update is
  checked by.
* **patch** — on the machine with the turbopuffer key: one `patch_rows` run
  writing `source_link` onto every row of the live namespace (§17.6, D49
  ruling 3).  turbopuffer ignores a patch to an id that does not exist, and
  the run counts the namespace before and after to prove no row was created.

The artefact carries the recipe, not the string (Q4, 2026-08-23): per-record
`(document id, file index, line)` triples ride beside the file→page map, and
`source_links` composes each finished href at use time — one function, so a
row's link can never disagree with the map it came from.  `needed_lines` is
likewise derived from the same triples, so the marks the publisher injects and
the lines the links point at are the same set by construction.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import posixpath
import re
import shutil
import sys


class SourcePagesError(RuntimeError):
    """Anything that must stop the step it happens in."""


def _log(msg: str) -> None:
    print(f"[source-pages] {msg}", flush=True)


# Every published path and every emitted href lives under this prefix; the
# link-check gate compares the literal strings (§17.5), so the prefix is stated
# once and never reconstructed ad hoc.
SITE_PREFIX = "/source/"

# The auxiliary pages' subtree (§17.2): a pure function of the symbolic
# position, so the two sides below must stay each other's inverses.
_AUX_SUBDIRS = (("$AFP/", "AFP/"), ("~~/", "ISABELLE_HOME/"))

# D50's site-external predicate: a URI scheme, or a protocol-relative `//`.
# Applied to the WHOLE reference value, before any fragment split.  Sound by
# construction: `:` is illegal in every Isabelle path element
# (`Path.illegal_char`), so no site-internal reference can ever match.
_EXTERNAL = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*:|//)")


def is_external(ref: str) -> bool:
    return bool(_EXTERNAL.match(ref))


def linkable(file: str) -> bool:
    """D42: a link exists iff the position is symbolic — `$AFP/…` or `~~/…`.
    An absolute path is machine-local and is never shown, never linked."""
    return file.startswith("$AFP/") or file.startswith("~~/")


def aux_page(file: str) -> str:
    """The published page of a non-`.thy` position file (§17.2): `$AFP/x` →
    `/source/_aux/AFP/x.html`, `~~/x` → `/source/_aux/ISABELLE_HOME/x.html`."""
    for prefix, sub in _AUX_SUBDIRS:
        if file.startswith(prefix):
            return f"{SITE_PREFIX}_aux/{sub}{file[len(prefix):]}.html"
    raise SourcePagesError(
        f"{file!r} is not a symbolic position, so no auxiliary page serves it")


def aux_symbolic(session_rel: str) -> 'str | None':
    """The symbolic position a rendered auxiliary copy renders, from its path
    below the session directory: `AFP/<rest>.html` → `$AFP/<rest>`,
    `ISABELLE_HOME/<rest>.html` → `~~/<rest>`; None for anything else."""
    for prefix, sub in _AUX_SUBDIRS:
        if session_rel.startswith(sub) and session_rel.endswith(".html"):
            return prefix + session_rel[len(sub):-len(".html")]
    return None


# ---------------------------------------------------------------------------
# The two shipped files — self-hashed envelopes (§17.1), and the recipe (Q4)
# ---------------------------------------------------------------------------

SCAN_FORMAT = 2
ARTEFACT_FORMAT = 2


def _canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def write_artefact(path: str, body: dict) -> str:
    """Writes `{"content_hash": …, "body": …}` and returns the hash.  Both the
    scan output and the map artefact use this envelope — one shape for
    anything that ships between machines (§17.1)."""
    digest = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"content_hash": digest, "body": body}, f,
                  ensure_ascii=False, separators=(",", ":"))
    return digest


def load_artefact(path: str, kind: str, fmt: int) -> 'tuple[dict, str]':
    """`(body, content hash)`, refused unless the hash still holds and the
    body is the expected kind and format — the "one versioned artefact"
    clause of §17.1, applied at every read."""
    with open(path, encoding="utf-8") as f:
        stored = json.load(f)
    body = stored.get("body")
    digest = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    if digest != stored.get("content_hash"):
        raise SourcePagesError(
            f"{path} does not match its own content hash — a truncated copy or "
            f"a hand edit; re-ship it from the machine that built it")
    if body.get("kind") != kind or body.get("format") != fmt:
        raise SourcePagesError(
            f"{path} is kind {body.get('kind')!r} format {body.get('format')!r}; "
            f"this step reads kind {kind!r} format {fmt}")
    if kind == "map":
        _validate_map_body(path, body)
    return body, digest


_MAP_FIELDS = ("files", "records", "file_page_map", "residue", "source_lines",
               "classification", "tree_fingerprint", "theories_sha256",
               "registry_fingerprint")


def _validate_map_body(path: str, body: dict) -> None:
    """The structural facts the composer relies on, enforced at load rather
    than remembered: every field present, `file_page_map` and `residue`
    partition `files`, and every record's file index is in range."""
    missing = [f for f in _MAP_FIELDS if f not in body]
    if missing:
        raise SourcePagesError(f"{path}: map body lacks {missing}")
    files = body["files"]
    mapped, residue = set(body["file_page_map"]), set(body["residue"])
    if set(files) != mapped | residue or mapped & residue:
        raise SourcePagesError(
            f"{path}: file_page_map and residue do not partition files")
    n = len(files)
    if any(not (-1 <= fi < n) for _id, fi, _line in body["records"]):
        raise SourcePagesError(f"{path}: a record's file index is out of range")


def source_links(body: dict) -> 'dict[str, str]':
    """Every record's finished link (D49 ruling 2), composed from the
    artefact's own map: `page#L<line>` for a mapped position, the empty
    string — D42's absent form — for no position and for residue alike.  THE
    one place a source link is built (Q4), so the string a row carries can
    never disagree with the map it came from."""
    fpm = body["file_page_map"]
    pages = [fpm.get(f) for f in body["files"]]
    links = {doc_id: (f"{pages[fi]}#{line_fragment(line)}"
                      if fi >= 0 and pages[fi] else "")
             for doc_id, fi, line in body["records"]}
    if len(links) != len(body["records"]):
        raise SourcePagesError(
            f"{len(body['records'])} record(s) yielded {len(links)} link(s) — "
            f"duplicate document ids")
    return links


def needed_lines_by_page(body: dict) -> 'dict[str, list[int]]':
    """The marks each published page needs, derived from the same triples the
    links compose from (Q4) — the injected marks and the lines the links point
    at are the same set by construction, not by a checked coincidence."""
    fpm = body["file_page_map"]
    pages = [fpm.get(f) for f in body["files"]]
    needed: 'dict[str, set[int]]' = {}
    for _doc_id, fi, line in body["records"]:
        if fi >= 0 and pages[fi]:
            needed.setdefault(pages[fi], set()).add(line)
    return {page: sorted(lines) for page, lines in needed.items()}


# ---------------------------------------------------------------------------
# §17.1 — the corpus scan
# ---------------------------------------------------------------------------

def run_scan(*, isabelle_home: str, afp_dir: str, out: str) -> None:
    """The corpus scan: the per-record position triples and the
    declaring-theory evidence, from exactly the record set the export
    publishes.

    Every published document id rides in `records` — a record with no linkable
    position with file index -1, because the patch writes `source_link` onto
    every row (D49 ruling 3), empty string included.  `records` is sorted by
    document id, so the scan's content hash does not depend on the store's
    enumeration order.  `declaring_theory_hashes` feeds §17.3's cross-check:
    per `.thy` position file, the declaring-theory hashes of the
    name-addressed records positioned there — an XOR-prefixed key's 16-byte
    prefix is a pseudo-theory (D13) and never enters."""
    from Isabelle_RPC_Host.universal_key import is_xor_prefixed_key
    from .site_export import declared_sessions, document_id, iter_shippable, theory_registry

    sessions = declared_sessions(isabelle_home, afp_dir)
    _log(f"{len(sessions)} declared session(s) in scope (D24)")
    registry = theory_registry()
    _log(f"{len(registry)} theory-hash registry entr(ies)")

    counts: 'dict[str, int]' = dict.fromkeys(
        ("records", "undecodable", "wip", "experience", "out of scope"), 0)
    file_index: 'dict[str, int]' = {}
    declaring: 'dict[str, set[str]]' = {}
    records: 'list[list]' = []
    pairs: 'set[tuple[int, int]]' = set()
    for key, rec, _theories in iter_shippable(sessions, registry, counts):
        pos = rec.position
        if pos and linkable(pos[0]):
            file, line = pos[0], pos[1]
            fi = file_index.setdefault(file, len(file_index))
            pairs.add((fi, line))
            if file.endswith(".thy") and not is_xor_prefixed_key(key):
                declaring.setdefault(file, set()).add(key[:16].hex())
            records.append([document_id(key), fi, line])
        else:
            records.append([document_id(key), -1, 0])
    records.sort()

    body = {
        "kind": "scan",
        "format": SCAN_FORMAT,
        "files": list(file_index),      # insertion-ordered: index i is files[i]
        "declaring_theory_hashes": {f: sorted(h) for f, h in declaring.items()},
        "records": records,
    }
    digest = write_artefact(out, body)
    for what, n in counts.items():
        _log(f"  {what:<14} {n}")
    _log(f"wrote {out} (content hash {digest[:12]}): {len(records)} record(s), "
         f"{len(file_index)} linkable position file(s), {len(pairs)} needed "
         f"(file, line) pair(s)")


# ---------------------------------------------------------------------------
# The rendered tree, classified (§17.2), and D52's long-name derivation
# ---------------------------------------------------------------------------

class RenderedTree:
    """One walk's worth of classification.  `raw_theory` holds each depth-3
    theory page as `(session dir, stem, tree-relative path)` — the long name
    is derived from it later, against the registry (D52).  `dropped` counts
    what §17.2 declares out; anything unclassifiable is dropped and named in
    the report rather than refused (D49 ruling 4)."""

    def __init__(self) -> None:
        self.raw_theory: 'list[tuple[str, str, str]]' = []
        self.aux_copies: 'dict[str, list[str]]' = {}  # symbolic position -> paths
        self.css_copies: 'list[str]' = []
        self.fonts: 'list[str]' = []
        self.dropped: 'dict[str, int]' = {}
        self.unclassified: 'list[str]' = []
        # EVERY file the walk saw, kept and dropped alike, with its size (Q3):
        # the sealed set D51's dangling decision reads instead of the live
        # filesystem, and what the tree fingerprint derives from.
        self.inventory: 'dict[str, int]' = {}

    def _drop(self, what: str) -> None:
        self.dropped[what] = self.dropped.get(what, 0) + 1


def classify_rendered_tree(root: str) -> RenderedTree:
    tree = RenderedTree()
    for dirpath, _dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        for name in filenames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}".replace(os.sep, "/")
            tree.inventory[rel] = os.path.getsize(os.path.join(dirpath, name))
            parts = rel.split("/")
            if ".browser_info" in parts:
                tree._drop(".browser_info bookkeeping")
            elif name == "isabelle.css":
                tree.css_copies.append(rel)
            elif name == "index.html" and len(parts) <= 3:
                tree._drop("renderer index page")      # root, chapter or session
            elif parts[0] == "fonts" and len(parts) == 2:
                tree.fonts.append(rel)
            elif name == "session_graph.pdf":
                tree._drop("session graph")
            elif name == "isabelle.gif":
                tree._drop("isabelle.gif")
            elif len(parts) == 3 and name.endswith(".html"):
                tree.raw_theory.append((parts[1], name[:-len(".html")], rel))
            elif len(parts) >= 4 and (sym := aux_symbolic("/".join(parts[2:]))):
                tree.aux_copies.setdefault(sym, []).append(rel)
            else:
                tree._drop("unclassified")
                tree.unclassified.append(rel)
    for copies in tree.aux_copies.values():
        copies.sort()
    tree.raw_theory.sort(key=lambda t: t[2])
    return tree


def derive_theory_pages(raw_theory: 'list[tuple[str, str, str]]',
                        registry_names: 'set[str]',
                        ) -> 'tuple[dict[str, str], list[str]]':
    """D52's verified derivation: `(long name → tree-relative path, dropped
    page paths)`.

    A stem containing `.` IS the long name — a theorem, not a heuristic:
    `Long_Name` makes a dot in a base name impossible, so a dotted stem proves
    foreign-session presentation and `print_short` = the full name.  A dotless
    stem resolves to `<session dir>.<stem>` when the registry holds that name,
    else to the bare stem (the global theories); a page resolving to neither
    is dropped and reported (measured: the four Pure bootstrap/example pages,
    zero entity ids, nothing pointing at them)."""
    pages: 'dict[str, str]' = {}
    dropped: 'list[str]' = []
    for session_dir, stem, rel in raw_theory:
        if "." in stem:
            long_name = stem
        elif f"{session_dir}.{stem}" in registry_names:
            long_name = f"{session_dir}.{stem}"
        elif stem in registry_names:
            long_name = stem
        else:
            dropped.append(rel)
            continue
        if long_name in pages:
            raise SourcePagesError(
                f"pages {pages[long_name]} and {rel} both derive the long name "
                f"{long_name!r} — long names are unique, so the derivation or "
                f"the tree is broken")
        pages[long_name] = rel
    return pages, dropped


def page_for_name(name: str, theory_pages: 'dict[str, str]') -> 'str | None':
    """The published page key serving theory `name` (§17.3's page choice):
    the name itself; for a bare name, the session-qualified twin page wins
    when both exist; for an `X.X` name with no page, the bare page `X` — the
    global-theory presentation of the same theory (D52's amendment,
    `HOL-CSP.HOL-CSP` being the one such name today)."""
    if "." not in name and f"{name}.{name}" in theory_pages:
        return f"{name}.{name}"
    if name in theory_pages:
        return name
    base = name.rsplit(".", 1)[-1]
    if name == f"{base}.{base}" and base in theory_pages:
        return base
    return None


# ---------------------------------------------------------------------------
# §17.3 — the file→page map: one lookup over data/theories.json (D53)
# ---------------------------------------------------------------------------

def invert_theories(theories: dict) -> 'tuple[dict[str, str], dict[str, str]]':
    """`(path → long name, the two tree prefixes)` from `data/theories.json`.

    Folds the `(global)`-alias twins first — `X.X` beside `X` with the same
    path is the session-qualified alias of a global theory (the same fold
    `data/isabelle.py` applies at load; stated twice because this module must
    run from a bare checkout on cslh19).  The inversion must be injective:
    two long names on one path after the fold is a hard error, not a pick.

    The prefixes are detected from the table itself: every path sits under
    exactly one of two roots — the AFP snapshot (the one containing `/thys/`)
    and the distribution."""
    aliases = set()
    for a in theories:
        if "." in a:
            b = a.rsplit(".", 1)[-1]
            if (a == f"{b}.{b}" and b in theories
                    and theories[b]["path"] == theories[a]["path"]):
                aliases.add(a)
    inverted: 'dict[str, str]' = {}
    for name, info in theories.items():
        if name in aliases:
            continue
        path = info["path"]
        if path in inverted:
            raise SourcePagesError(
                f"theories.json maps both {inverted[path]!r} and {name!r} to "
                f"{path!r} — the inversion must be injective")
        inverted[path] = name

    # The AFP root is the prefix up to `/thys/` (no distribution path contains
    # that segment — measured); the distribution root is the literal common
    # string prefix of everything else, cut at its last `/` — NOT
    # `posixpath.commonpath`, which normalises the leading `./` away.  The
    # check below is the invariant `normalize_position` actually needs, not a
    # proxy: every path must start with exactly one of the two prefixes.
    # (Distribution components live under `contrib/`, not `src/` — the four
    # Naproche theories are the measured case a `/src/` split would break.)
    afp_set = {p[:p.index("/thys/") + len("/thys/")]
               for p in inverted if "/thys/" in p}
    if len(afp_set) != 1:
        raise SourcePagesError(
            f"theories.json's AFP paths sit under {len(afp_set)} roots: "
            f"{sorted(afp_set)}")
    afp = afp_set.pop()
    home_paths = [p for p in inverted if "/thys/" not in p]
    common = os.path.commonprefix(home_paths)
    home = common[:common.rindex("/") + 1] if "/" in common else ""
    bad = [p for p in inverted
           if p.startswith(afp) == p.startswith(home) or not (
               p.startswith(afp) or p.startswith(home))]
    if not home or bad:
        raise SourcePagesError(
            f"theories.json paths do not partition under two roots "
            f"(afp={afp!r}, home={home!r}); offending: {bad[:5]}")
    return inverted, {"$AFP/": afp, "~~/": home}


def normalize_position(file: str, prefixes: 'dict[str, str]') -> str:
    """A symbolic position as `theories.json` spells the same file."""
    for sym, real in prefixes.items():
        if file.startswith(sym):
            return real + file[len(sym):]
    raise SourcePagesError(f"{file!r} is not a symbolic position")


def build_file_page_map(scan: dict, inverted: 'dict[str, str]',
                        prefixes: 'dict[str, str]',
                        registry_by_hash: 'dict[str, str]',
                        theory_pages: 'dict[str, str]', aux_copies: 'dict[str, list[str]]',
                        ) -> 'tuple[dict[str, str], dict[str, str], list[str]]':
    """D53's resolver, `(file → published page, residue)`.  For a `.thy` file
    the answer is one table lookup, and each of the three staleness gates is a
    hard error, not residue: a position file the table misses (coverage is
    100 % by construction), a table name contradicting the file's
    declaring-hash evidence (zero-conflict cross-check), a resolved name
    without a page.  Residue exists only for auxiliary files with no rendered
    copy."""
    declaring = scan["declaring_theory_hashes"]
    file_page_map: 'dict[str, str]' = {}
    residue: 'dict[str, str]' = {}
    no_evidence: 'list[str]' = []
    for file in scan["files"]:
        if file.endswith(".thy"):
            name = inverted.get(normalize_position(file, prefixes))
            if name is None:
                raise SourcePagesError(
                    f"{file} is not in theories.json — the table is stale for "
                    f"this corpus generation; regenerate it (D53)")
            hashes = declaring.get(file)
            if hashes:
                named = {registry_by_hash[h] for h in hashes if h in registry_by_hash}
                # No resolvable hash is absence of evidence, not contradicting
                # evidence — this registry may simply not know the file.
                if not named:
                    no_evidence.append(file)
                elif name not in named:
                    raise SourcePagesError(
                        f"{file}: theories.json says {name!r} but the file's "
                        f"name-addressed records name {sorted(named)} — the two "
                        f"evidence chains disagree (D53's cross-check)")
            page = page_for_name(name, theory_pages)
            if page is None:
                raise SourcePagesError(
                    f"{file} resolves to {name!r}, which derives no published "
                    f"page — the table and the rendered tree are not the same "
                    f"generation (D53)")
            file_page_map[file] = f"{SITE_PREFIX}{page}.html"
        elif file in aux_copies:
            file_page_map[file] = aux_page(file)
        else:
            residue[file] = "no rendered auxiliary copy"

    page_of: 'dict[str, str]' = {}
    for file, page in file_page_map.items():
        if page in page_of:
            raise SourcePagesError(
                f"{page_of[page]} and {file} both map to {page} — two files "
                f"cannot share one page's line marks")
        page_of[page] = file
    return file_page_map, residue, no_evidence


def tree_fingerprint(inventory: 'dict[str, int]') -> str:
    """sha256 over `rel\\0size` of the whole sealed inventory, sorted (Q3) —
    a value derived from the inventory, never a second source of truth."""
    h = hashlib.sha256()
    for rel in sorted(inventory):
        h.update(f"{rel}\0{inventory[rel]}\n".encode("utf-8"))
    return h.hexdigest()


# The two generated files claim their published paths before any relocated
# file can (the collision guard pre-seeds them).
GENERATED_PAGES = (f"{SITE_PREFIX}index.html", f"{SITE_PREFIX}isabelle.css")


def build_relocation(classification: dict) -> 'dict[str, str]':
    """THE map from every kept rendered file to its published path — built
    once from the classification and used for the rewrite, the walk and the
    fingerprint alike, so the set publish transforms and the set the seal
    covers cannot diverge.  Collisions are checked per class: theory pages
    and fonts are one-to-one, the auxiliary copies and the stylesheet copies
    are many-to-one **by construction** (keyed by symbolic path / collapsing
    to the one generated stylesheet), and the generated pages' paths are
    pre-claimed."""
    relocation: 'dict[str, str]' = {}
    claimed: 'dict[str, str]' = {page: "<generated>" for page in GENERATED_PAGES}

    def claim(rel: str, page: str) -> None:
        if page in claimed:
            raise SourcePagesError(
                f"{claimed[page]} and {rel} both publish to {page}")
        claimed[page] = rel
        relocation[rel] = page

    for name, rel in classification["theory_pages"].items():
        claim(rel, f"{SITE_PREFIX}{name}.html")
    for sym, rels in classification["aux_pages"].items():
        page = aux_page(sym)
        claim(rels[0], page)
        for rel in rels[1:]:
            relocation[rel] = page        # many-to-one by construction
    for rel in classification["fonts"]:
        claim(rel, f"{SITE_PREFIX}fonts/{rel.rsplit('/', 1)[-1]}")
    for rel in classification["css"]:
        relocation[rel] = f"{SITE_PREFIX}isabelle.css"   # collapses by design
    return relocation


def run_map(*, scan_path: str, rendered: str, theories_path: str, out: str,
            repo_root: 'str | None' = None) -> None:
    """Builds the classification, the file→page map and the per-file source
    line counts, and seals them — with the scan's triples, the table's and
    the registry's identity, and the whole tree inventory — into the
    artefact.  Runs on the host that holds the rendered tree, the registry
    and the two source trees (the pipeline is host-generic: every input is a
    path, and the seals below are what make the artefact trustworthy
    wherever it was built)."""
    from .site_export import theory_registry

    scan, _ = load_artefact(scan_path, "scan", SCAN_FORMAT)
    with open(theories_path, "rb") as f:
        theories_bytes = f.read()
    inverted, prefixes = invert_theories(json.loads(theories_bytes))
    _log(f"theories.json: {len(inverted)} path(s); prefixes {prefixes}")

    tree = classify_rendered_tree(rendered)
    registry_by_hash = {k.hex(): name for k, name in theory_registry().items()}
    registry_names = set(registry_by_hash.values())
    _log(f"{len(registry_by_hash)} registry entr(ies), "
         f"{len(registry_names)} distinct name(s)")
    theory_pages, underived = derive_theory_pages(tree.raw_theory, registry_names)
    _log(f"rendered tree: {len(theory_pages)} theory page(s) "
         f"({len(underived)} underived, dropped), "
         f"{sum(len(c) for c in tree.aux_copies.values())} auxiliary cop(ies) of "
         f"{len(tree.aux_copies)} symbolic path(s)")

    file_page_map, residue, no_evidence = build_file_page_map(
        scan, inverted, prefixes, registry_by_hash, theory_pages, tree.aux_copies)
    if no_evidence:
        _log(f"  {len(no_evidence)} file(s) whose declaring hashes this "
             f"registry cannot resolve — cross-check had no evidence there")

    # B3: the real source files' line counts, read where they exist — the one
    # check that catches a wrong file→page pick AND validates the
    # line-fidelity assumption the whole injection rests on.
    if repo_root is None:
        repo_root = os.path.dirname(os.path.dirname(theories_path)) or "."
    source_lines: 'dict[str, int]' = {}
    for file in file_page_map:
        real = os.path.join(repo_root, normalize_position(file, prefixes))
        try:
            with open(real, "rb") as f:
                source_lines[file] = f.read().count(b"\n") + 1
        except OSError as e:
            raise SourcePagesError(f"cannot read {real} for {file}: {e}") from None

    classification = {
        "theory_pages": theory_pages,
        "aux_pages": tree.aux_copies,
        "css": sorted(tree.css_copies),
        "fonts": sorted(tree.fonts),
        "dropped": tree.dropped,
        "underived": underived,
        "unclassified": tree.unclassified,
        "inventory": tree.inventory,
    }
    registry_names_sorted = "\n".join(sorted(registry_names))
    body = {
        "kind": "map",
        "format": ARTEFACT_FORMAT,
        "files": scan["files"],
        "records": scan["records"],
        "file_page_map": file_page_map,
        "residue": residue,
        "no_evidence": sorted(no_evidence),
        "source_lines": source_lines,
        "classification": classification,
        "tree_fingerprint": tree_fingerprint(tree.inventory),
        # The identity seals (the review's chain): which table and which
        # registry produced this mapping — §17.3's "the table ships inside
        # the artefact's content hash", made literal.
        "theories_sha256": hashlib.sha256(theories_bytes).hexdigest(),
        "registry_fingerprint": {
            "entries": len(registry_by_hash),
            "names_sha256": hashlib.sha256(
                registry_names_sorted.encode("utf-8")).hexdigest(),
        },
    }
    links = source_links(body)          # the duplicate-id check fires here too
    linked = sum(1 for v in links.values() if v)
    digest = write_artefact(out, body)
    _log(f"  residue: {len(residue)} auxiliary file(s) with no rendered copy")
    for file, why in sorted(residue.items()):
        _log(f"    {file}: {why}")
    _log(f"  linked {linked} of {len(links)} record(s) "
         f"({linked / len(links):.2%})" if links else "  no records")
    _log(f"wrote {out} (content hash {digest[:12]})")


# ---------------------------------------------------------------------------
# §17.4 — the transforms
# ---------------------------------------------------------------------------

# Tags never contain a newline (asserted per page below), and text never
# contains a raw `<`, so tags are exactly these spans — which is what lets
# reference rewriting touch attributes without ever touching displayed source
# code that happens to say `href="…"`.
_TAG = re.compile(r"<[^>]*>")
_REF_ATTR = re.compile(r'\b(href|src)="([^"]*)"')
_CSS_URL = re.compile(r"url\('([^']*)'\)")
_NEWLINE_IN_TAG = re.compile(r"<[^>]*\n")
_LINE_MARK = re.compile(r'id="L\d+"')   # \d+ and nothing looser: bare `id="L`
                                        # matches 555 innocent pages (§17.4)
_PRE_OPEN = '<pre class="source">'
_PRE_CLOSE = "</pre>"


def line_fragment(n: int) -> str:
    """The fragment a line mark answers to — THE one spelling of the `L<n>`
    convention; the composer, the injector and the gate all call here."""
    return f"L{n}"


def line_mark(n: int) -> str:
    return f'<a id="{line_fragment(n)}"></a>'


def classify_reference(ref: str, page_dir: str):
    """One reading of a reference value for the stripper, the rewriter and
    the gate alike: `("external", None)` (D50), `("samepage", fragment)`, or
    `("internal", (rendered-tree-relative target, fragment))` — resolved
    against the page's rendered location."""
    if is_external(ref):
        return "external", None
    target, _, fragment = ref.partition("#")
    if not target:
        return "samepage", fragment
    resolved = posixpath.normpath(posixpath.join(page_dir, target))
    return "internal", (resolved, fragment)


def assert_page_structure(page: str, page_rel: str) -> None:
    """The structural facts §17.4 asserts per page — every page, not only the
    marked ones, because "no newline inside a tag" is what licenses the tag
    regex the reference rewrite runs on everywhere: exactly one
    `<pre class="source">`, no newline inside any tag, and no pre-existing
    `id="L<digits>"` the injected marks could collide with."""
    if page.count(_PRE_OPEN) != 1:
        raise SourcePagesError(
            f"{page_rel} has {page.count(_PRE_OPEN)} '{_PRE_OPEN}' elements, "
            f"not exactly one")
    if _NEWLINE_IN_TAG.search(page):
        raise SourcePagesError(f"{page_rel} has a newline inside a tag")
    if _LINE_MARK.search(page):
        raise SourcePagesError(
            f'{page_rel} already carries an id="L<digits>" anchor, which the '
            f"injected marks would collide with (§17.4)")


class RefCounters:
    """The report's standing alarm (D50/D51): exempted site-external
    references, and stripped input-dangling anchors with their names."""

    def __init__(self) -> None:
        self.external = 0
        self.stripped: 'list[tuple[str, str]]' = []   # (page rel, target)


def strip_dangling_anchors(content: str, page_dir: str,
                           relocation: 'dict[str, str]', page_rel: str,
                           inventory: 'set[str]', counters: RefCounters) -> str:
    """D51: an `<a>` whose site-internal `href` target does not exist in the
    rendered tree — by the artefact's **sealed inventory**, never the live
    filesystem (Q3) — is input-dangling: the renderer emitted a link to a
    page it never wrote.  The anchor is stripped, its text kept (the page
    reads identically, those words just stop being clickable), one WARNING
    per target with the strip count, and the alarm counter counts **anchors**
    (a page linking one dead blob five times counts five).  A target that
    exists in the rendered tree but is missing from the relocation map stays
    for `rewrite_html_refs` to refuse (broken-by-us is never papered over),
    and a dangling `src=` is not stripped — it too falls through to the
    rewriter's hard error, since D51 rules anchors only."""
    dangling: 'set[str]' = set()
    for tag in _TAG.finditer(content):
        for m in _REF_ATTR.finditer(tag.group(0)):
            if m.group(1) != "href":
                continue
            kind, payload = classify_reference(m.group(2), page_dir)
            if kind == "internal" and payload[0] not in relocation \
                    and payload[0] not in inventory:
                dangling.add(m.group(2))
    for ref in sorted(dangling):
        pattern = re.compile(
            r'<a\b[^>]*href="' + re.escape(ref) + r'"[^>]*>((?:(?!</?a\b).)*?)</a>',
            re.DOTALL)
        content, n = pattern.subn(r"\1", content)
        if n == 0:
            raise SourcePagesError(
                f"{page_rel}: the dangling reference {ref!r} sits in a shape "
                f"the anchor-stripper cannot cut (nested or unclosed <a>)")
        counters.stripped.extend([(page_rel, ref)] * n)
        _log(f"WARNING: stripped {n} dangling anchor(s) to {ref!r} on "
             f"{page_rel} — the rendered tree never wrote that target (D51)")
    return content


def rewrite_html_refs(content: str, page_dir: str,
                      relocation: 'dict[str, str]', page_rel: str,
                      counters: RefCounters) -> str:
    """§17.4's reference rewrite for a page: a site-external reference (D50)
    is emitted byte-identically — not split at `#`, not resolved, not looked
    up — and counted; every other `href`/`src` is split from its fragment,
    resolved against the page's rendered location, mapped, re-emitted absolute
    under `/source/`, fragment re-attached unchanged.  A reference the map
    cannot name is a hard error naming the page and the reference."""
    def fix_ref(m: 're.Match') -> str:
        attr, ref = m.group(1), m.group(2)
        kind, payload = classify_reference(ref, page_dir)
        if kind == "external":
            counters.external += 1
            return m.group(0)
        if kind == "samepage":
            return m.group(0)             # a same-page fragment does not move
        resolved, fragment = payload
        published = relocation.get(resolved)
        if published is None:
            raise SourcePagesError(
                f"{page_rel} references {ref!r} ({resolved}), which maps to no "
                f"published file")
        suffix = f"#{fragment}" if fragment else ""
        return f'{attr}="{published}{suffix}"'

    return _TAG.sub(lambda tag: _REF_ATTR.sub(fix_ref, tag.group(0)), content)


def rewrite_css_urls(content: str, css_dir: str,
                     relocation: 'dict[str, str]', css_rel: str,
                     counters: RefCounters) -> str:
    """The same rewrite for a stylesheet's `url()` references — per file type,
    not per HTML attribute (§17.4); D50's predicate applies here too, so there
    is one rule and not one per file type."""
    def fix_url(m: 're.Match') -> str:
        kind, payload = classify_reference(m.group(1), css_dir)
        if kind == "external":
            counters.external += 1
            return m.group(0)
        resolved = payload[0] if kind == "internal" else css_rel
        published = relocation.get(resolved)
        if published is None:
            raise SourcePagesError(
                f"{css_rel} references url({m.group(1)!r}) ({resolved}), which "
                f"maps to no published file")
        return f"url('{published}')"

    return _CSS_URL.sub(fix_url, content)


def inject_line_marks(page: str, lines: 'list[int]', page_rel: str,
                      source_line_count: 'int | None') -> str:
    """§17.4's injection: the window is the content of the page's single
    `<pre class="source">` element; split on newlines, piece *n* is line *n*,
    and each needed line gets an `<a id="Ln"></a>` prefix.

    `source_line_count` is the real source file's line count the map recorded
    (B3): the window must show the same number of lines, ±1 for the EOF
    trailing-newline convention — the one check that catches a file mapped to
    a page showing some other file's source, and any line-fidelity drift."""
    head, _, rest = page.partition(_PRE_OPEN)
    window, close, tail = rest.partition(_PRE_CLOSE)
    if not close or _PRE_CLOSE in tail:
        raise SourcePagesError(
            f"{page_rel} does not close its source element exactly once")
    pieces = window.split("\n")
    if source_line_count is not None and abs(len(pieces) - source_line_count) > 1:
        raise SourcePagesError(
            f"{page_rel} shows {len(pieces)} source line(s) but the mapped "
            f"file has {source_line_count} — wrong page, or the line-fidelity "
            f"assumption broke (§17.4)")
    for n in sorted(lines):
        if not 1 <= n <= len(pieces):
            raise SourcePagesError(
                f"{page_rel} shows {len(pieces)} source line(s) but line {n} "
                f"is needed — the line-fidelity assumption broke (§17.4)")
        pieces[n - 1] = line_mark(n) + pieces[n - 1]
    return head + _PRE_OPEN + "\n".join(pieces) + close + tail


def _ids_in_tags(text: str) -> 'set[str]':
    return {m.group(1) for tag in _TAG.finditer(text)
            for m in re.finditer(r'\bid="([^"]*)"', tag.group(0))}


_TITLE_OR_H1 = re.compile(r"<(title|h1)\b")


def merge_aux_copies(sym: str, copies: 'list[tuple[str, str]]',
                     ) -> 'tuple[str, str, bool]':
    """D49 ruling 6 as amended 2026-08-23: one auxiliary page per symbolic
    path, publishing the id-union of all copies so every fragment reference
    keeps landing.  `(base copy's rel, merged content, whether copies
    conflicted)` — the caller must rewrite the merged content in the BASE
    copy's directory context, since its reference strings are the base's.

    The amended tolerance — the invariant measured true on all 12 real
    conflicts: copies must agree **line-for-line in text once the title and
    heading are set aside** (tags erased, `<title>`/`<h1>` lines exempt).
    That admits the three measured conflict shapes the old byte-level test
    refused — differing title wording, an entity-anchor *element* present in
    one copy only, and reference strings resolved through different sessions
    — while still refusing any real content divergence.  The base copy is the
    one whose title names the symbolic path (ties broken by sorted rendered
    location); ids other copies carry on a line become empty anchors at the
    front of the base's line — same line, same landing."""
    def title_names_sym(content: str) -> bool:
        m = re.search(r"<title>([^<]*)</title>", content)
        return bool(m) and sym in m.group(1)

    ordered = sorted(copies, key=lambda c: (not title_names_sym(c[1]), c[0]))
    (base_rel, base), *rest = ordered
    if all(content == base for _rel, content in rest):
        return base_rel, base, False
    base_lines = base.split("\n")
    merged = list(base_lines)
    for rel, content in rest:
        lines = content.split("\n")
        if len(lines) != len(merged):
            raise SourcePagesError(
                f"{rel} and {base_rel} render one file with different line "
                f"counts — beyond D49 ruling 6's amended tolerance")
        for i, other in enumerate(lines):
            if other == base_lines[i]:
                continue
            if _TAG.sub("", other) != _TAG.sub("", base_lines[i]) and not (
                    _TITLE_OR_H1.search(other) or _TITLE_OR_H1.search(base_lines[i])):
                raise SourcePagesError(
                    f"{rel} and {base_rel} differ in text at line {i + 1} — "
                    f"beyond D49 ruling 6's amended tolerance")
            extra = _ids_in_tags(other) - _ids_in_tags(merged[i])
            if extra:
                anchors = "".join(f'<a id="{x}"></a>' for x in sorted(extra))
                merged[i] = anchors + merged[i]
    return base_rel, "\n".join(merged), True


# The generated index page's copy — approved verbatim by the user, 2026-08-23.
INDEX_TITLE = "Isabelle source pages"
INDEX_SUBTITLE = ("Every theory indexed by the search site, grouped by "
                  "session. Pages are rendered from Isabelle2025-2 and "
                  "AFP 2026-05-13.")


def generate_index(theory_names: 'list[str]') -> str:
    """D49 ruling 5's `/source/index.html`: every published theory long name,
    grouped by the long name's session prefix (ruled 2026-08-23 with D52 — a
    global theory's bare name heads its own small group, its name being its
    natural headword; the rendered session directories are umbrella build
    names and must never leak into anything public)."""
    from .site_export import session_of
    groups: 'dict[str, list[str]]' = {}
    for name in theory_names:
        groups.setdefault(session_of(name), []).append(name)
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
        '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>'
        f'<link rel="stylesheet" type="text/css" href="{SITE_PREFIX}isabelle.css"/>\n'
        f"<title>{html.escape(INDEX_TITLE)}</title>\n</head>\n<body>\n"
        f'<div class="head"><h1>{html.escape(INDEX_TITLE)}</h1>\n'
        f"<p>{html.escape(INDEX_SUBTITLE)}</p></div>\n"
    ]
    for session in sorted(groups):
        parts.append(f"<h2>{html.escape(session)}</h2>\n<ul>\n")
        for name in sorted(groups[session]):
            parts.append(f'<li><a href="{SITE_PREFIX}{html.escape(name)}.html">'
                         f"{html.escape(name)}</a></li>\n")
        parts.append("</ul>\n")
    parts.append("</body>\n</html>\n")
    return "".join(parts)


def published_to_rel(page: str) -> str:
    """A published path's location inside the published tree; raises rather
    than slice blindly."""
    if not page.startswith(SITE_PREFIX):
        raise SourcePagesError(f"{page!r} is not under {SITE_PREFIX}")
    return page[len(SITE_PREFIX):]


def run_publish(*, rendered: str, artefact_path: str, out: str) -> None:
    """The pass (§17.4): one walk driven by the artefact's classification —
    not a fresh tree walk, so publish transforms exactly what the map
    classified; the sealed inventory refuses a tree that moved since, and
    each file's size is verified again at the moment it is read.  Everything
    goes into a fresh staging directory atomically renamed to `out`; the
    pass removes its own staging on failure and never deletes a directory it
    was handed."""
    artefact, artefact_hash = load_artefact(artefact_path, "map", ARTEFACT_FORMAT)
    cls = artefact["classification"]
    inventory: 'dict[str, int]' = cls["inventory"]
    out = out.rstrip("/")
    staging = out + ".building"
    for path in (out, staging):
        if os.path.exists(path):
            raise SourcePagesError(
                f"{path} already exists; the pass never deletes a handed path — "
                f"move it aside yourself if it is stale")

    relocation = build_relocation(cls)
    for rel in relocation:
        try:
            size = os.path.getsize(os.path.join(rendered, rel))
        except OSError:
            raise SourcePagesError(
                f"{rel} vanished from the rendered tree — re-run map (D53's "
                f"freshness discipline)") from None
        if size != inventory.get(rel):
            raise SourcePagesError(
                f"{rel} is {size} byte(s), the sealed inventory says "
                f"{inventory.get(rel)} — the tree moved since the map; re-run "
                f"map")

    needed_by_page = needed_lines_by_page(artefact)
    source_lines = artefact["source_lines"]
    page_source_lines = {page: source_lines[file]
                         for file, page in artefact["file_page_map"].items()}
    expected_marks = sum(len(lines) for lines in needed_by_page.values())

    counters = RefCounters()
    marks = 0
    merged_conflicts = 0

    def _write(page: str, content: str) -> None:
        dest = os.path.join(staging, *published_to_rel(page).split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)

    inventory_set = set(inventory)

    def _transform(rel: str, content: str, page: str) -> str:
        nonlocal marks
        assert_page_structure(content, rel)
        content = strip_dangling_anchors(content, posixpath.dirname(rel),
                                         relocation, rel, inventory_set,
                                         counters)
        content = rewrite_html_refs(content, posixpath.dirname(rel),
                                    relocation, rel, counters)
        lines = needed_by_page.get(page)
        if lines:
            content = inject_line_marks(content, lines, rel,
                                        page_source_lines.get(page))
            marks += len(lines)
        return content

    try:
        os.makedirs(staging)
        for name, rel in sorted(cls["theory_pages"].items()):
            with open(os.path.join(rendered, rel), encoding="utf-8") as f:
                content = f.read()
            page = relocation[rel]
            _write(page, _transform(rel, content, page))

        for sym, rels in sorted(cls["aux_pages"].items()):
            copies = []
            for rel in rels:
                with open(os.path.join(rendered, rel), encoding="utf-8") as f:
                    copies.append((rel, f.read()))
            base_rel, content, conflicted = merge_aux_copies(sym, copies)
            merged_conflicts += conflicted
            page = aux_page(sym)
            # The merged content is the base copy's wholesale, so the rewrite
            # runs in the BASE copy's directory context.
            _write(page, _transform(base_rel, content, page))

        # §17.2: exactly one generated stylesheet with absolute font URLs.
        # Each rendered copy is rewritten in its own directory and the results
        # must agree; the D50 counter counts the ONE surviving stylesheet, not
        # all 335 rewrites — the copies are asserted identical, so any copy's
        # count is the published count.
        rewritten_css: 'set[str]' = set()
        css_counters = RefCounters()
        for rel in cls["css"]:
            per_copy = RefCounters()
            with open(os.path.join(rendered, rel), encoding="utf-8") as f:
                rewritten_css.add(rewrite_css_urls(
                    f.read(), posixpath.dirname(rel), relocation, rel, per_copy))
            css_counters = per_copy
        if len(rewritten_css) != 1:
            raise SourcePagesError(
                f"the {len(cls['css'])} stylesheet copies rewrite to "
                f"{len(rewritten_css)} distinct texts, not one")
        counters.external += css_counters.external
        _write(f"{SITE_PREFIX}isabelle.css", rewritten_css.pop())

        for rel in cls["fonts"]:
            dest = os.path.join(staging,
                                *published_to_rel(relocation[rel]).split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(os.path.join(rendered, rel), dest)

        # The generated index passes through the same external counting as
        # every page, so the report's number covers the whole published tree.
        index_content = generate_index(sorted(cls["theory_pages"]))
        counters.external += sum(
            1 for tag in _TAG.finditer(index_content)
            for m in _REF_ATTR.finditer(tag.group(0)) if is_external(m.group(2)))
        _write(f"{SITE_PREFIX}index.html", index_content)

        if marks != expected_marks:
            raise SourcePagesError(
                f"injected {marks} line mark(s) but the artefact needs "
                f"{expected_marks} — some mapped page was never written")

        # The report is part of the published output (B12): written into
        # staging, so a tree without its report is unrepresentable, and it
        # ships publicly with the tree — exempt, by the user's ruling of
        # 2026-08-23, from §17.2's umbrella-name prohibition, so its path
        # lists carry raw rendered paths.  Its two standing counters are
        # D50/D51's alarm, and `artefact_hash` is what lets the gate refuse
        # a (tree, artefact) pair that never belonged together.
        report = {
            "artefact_hash": artefact_hash,
            "published": {
                "theory pages": len(cls["theory_pages"]),
                "auxiliary pages": len(cls["aux_pages"]),
                "fonts": len(cls["fonts"]),
                "generated": ["index.html", "isabelle.css"],
            },
            "marks injected": marks,
            "auxiliary conflicts merged": merged_conflicts,
            "external references exempted (D50)": counters.external,
            "dangling anchors stripped (D51)": len(counters.stripped),
            "stripped": [{"page": p, "target": t} for p, t in counters.stripped],
            "dropped": cls["dropped"],
            "underived theory pages": cls["underived"],
            "unclassified": cls["unclassified"],
        }
        with open(os.path.join(staging, "publish-report.json"), "w",
                  encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)   # our own creation, not a
        raise                                        # handed path
    os.rename(staging, out)
    _log(f"published {out}: {len(cls['theory_pages'])} theory page(s), "
         f"{len(cls['aux_pages'])} auxiliary page(s), {marks} mark(s), "
         f"{merged_conflicts} merged conflict(s)")
    _log(f"  ALARM counters — external exempted: {counters.external}, "
         f"dangling stripped: {len(counters.stripped)}")
    for what, n in sorted(cls["dropped"].items()):
        _log(f"  dropped {what:<28} {n}")


# ---------------------------------------------------------------------------
# §17.5 — the link-check gate
# ---------------------------------------------------------------------------

def run_gate(*, published: str, artefact_path: str, namespace: 'str | None',
             region: str, sample: int) -> int:
    """The gate, over the published tree: every needed (file, line) has its
    mark, every site-internal reference in every published file resolves —
    fragments included, no anchor trusted — and every non-empty composed link
    is string-equal to a path the tree serves with the named mark present.
    Site-external references are exempt and counted (D50), and the count must
    equal the publish report's, or the alarm's two numbers were never
    comparable.  Fragments are checked by PROVENANCE (D54, 2026-08-23): a
    fragment this pipeline composed or injected — a row link's `#L<n>`, a
    needed mark — misses at zero tolerance; a fragment inherited from the
    rendered tree is still checked, but a miss is counted and reported (the
    alarm family's third number), because the renderer itself emits
    `offset_…` references it never anchors, and an inherited miss lands the
    reader at the top of the right page — D47's silent, harmless
    degradation.  Target-major two passes: references are collected first,
    then each *fragment-bearing* target is read once for its ids and dropped
    — memory is one page's ids (source pages are read once per pass, so a
    page that is also a target is read twice; that is the price of not
    holding every page's id set)."""
    artefact, artefact_hash = load_artefact(artefact_path, "map", ARTEFACT_FORMAT)
    links = source_links(artefact)
    needed_by_page = needed_lines_by_page(artefact)
    cls = artefact["classification"]

    files: 'set[str]' = set()
    for dirpath, _dirnames, filenames in os.walk(published):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), published)
            files.add(rel.replace(os.sep, "/"))

    failures = 0

    def fail(msg: str) -> None:
        nonlocal failures
        failures += 1
        if failures <= 50:
            _log(f"  FAIL {msg}")

    def _read(rel: str) -> str:
        with open(os.path.join(published, rel), encoding="utf-8") as f:
            return f.read()

    # Pass 1 — collect every reference, keyed by target page.  Two provenance
    # buckets (D54): fragments inherited from the rendered pages, and
    # fragments this pipeline composed (row links, needed marks).
    wanted: 'dict[str, set[str]]' = {}      # inherited: rel -> fragments (may hold "")
    wanted_own: 'dict[str, set[str]]' = {}  # ours: rel -> fragments, zero-miss
    external = 0
    checked_refs = 0
    for rel in sorted(files):
        if rel.endswith(".html"):
            content = _read(rel)
            refs = [m.group(2) for tag in _TAG.finditer(content)
                    for m in _REF_ATTR.finditer(tag.group(0))]
        elif rel.endswith(".css"):
            refs = [m.group(1) for m in _CSS_URL.finditer(_read(rel))]
        else:
            continue
        for ref in refs:
            checked_refs += 1
            if is_external(ref):
                external += 1
                continue
            target, _, fragment = ref.partition("#")
            if not target:
                target_rel = rel                       # a same-page fragment
            elif target.startswith(SITE_PREFIX):
                target_rel = target[len(SITE_PREFIX):]
            else:
                fail(f"{rel} references {ref!r}, which is neither external "
                     f"nor under {SITE_PREFIX}")
                continue
            if target_rel not in files:
                fail(f"{rel} references {ref!r}, which the tree does not serve")
                continue
            wanted.setdefault(target_rel, set()).add(fragment)

    # Every output the classification promises must be served — the generated
    # index is the one page nothing else references, so "the index links every
    # theory page" cannot cover the index itself.
    for page in list(GENERATED_PAGES) + [
            f"{SITE_PREFIX}{name}.html" for name in cls["theory_pages"]] + [
            aux_page(sym) for sym in cls["aux_pages"]] + [
            f"{SITE_PREFIX}fonts/{rel.rsplit('/', 1)[-1]}"
            for rel in cls["fonts"]]:
        if published_to_rel(page) not in files:
            fail(f"the classification promises {page} and the tree does not "
                 f"serve it")

    # The composed row links, checked literally (D49 ruling 2's end-to-end
    # clause: the string the site will emit is the string that must work), and
    # the needed marks — folded into the same target-major sweep.
    empty = 0
    for doc_id, link in links.items():
        if not link:
            empty += 1
            continue
        target, _, fragment = link.partition("#")
        rel = published_to_rel(target)
        if rel not in files:
            fail(f"link for {doc_id} names {target}, which the tree does not serve")
        elif not fragment:
            fail(f"link for {doc_id} is {link!r}, which carries no fragment")
        else:
            wanted_own.setdefault(rel, set()).add(fragment)
    for page, lines in needed_by_page.items():
        rel = published_to_rel(page)
        if rel not in files:
            fail(f"{page} is needed and the tree does not serve it")
            continue
        wanted_own.setdefault(rel, set()).update(line_fragment(n) for n in lines)

    # Pass 2 — visit each fragment-bearing target once.  A target wanted only
    # with the empty fragment was already proven to exist in pass 1 and is
    # never read: the 13 fonts are binary, and opening them as UTF-8 was the
    # review's third blocker.  A non-empty fragment against a non-markup
    # target is a failure, not a traceback.
    checked_fragments = 0
    inherited_misses: 'list[tuple[str, str]]' = []
    for rel in sorted(set(wanted) | set(wanted_own)):
        inherited = {f for f in wanted.get(rel, ()) if f}
        own = wanted_own.get(rel, set())
        if not inherited and not own:
            continue
        try:
            ids = _ids_in_tags(_read(rel))
        except UnicodeDecodeError:
            if own:
                fail(f"{rel} is not a markup file, yet {len(own)} composed "
                     f"link(s)/mark(s) name a fragment in it")
            inherited_misses.extend((rel, f) for f in sorted(inherited))
            continue
        for fragment in own:
            checked_fragments += 1
            if fragment not in ids:
                fail(f"{rel} carries no id for fragment {fragment!r}")
        for fragment in inherited:
            checked_fragments += 1
            if fragment not in ids:
                inherited_misses.append((rel, fragment))
    if inherited_misses:
        _log(f"  reported, not failed (D54): {len(inherited_misses)} "
             f"inherited fragment(s) the rendered tree never anchored — the "
             f"alarm family's third number (baseline 106, all offset_…)")
        for rel, fragment in inherited_misses[:5]:
            _log(f"    {rel}#{fragment}")

    total = len(links)
    positioned = sum(1 for _id, fi, _line in artefact["records"] if fi >= 0)
    _log(f"checked {checked_refs} reference(s); {external} site-external "
         f"exempted (D50); {checked_fragments} fragment(s) verified on "
         f"{sum(1 for r in wanted.values() if any(r))} page(s)")
    if total:
        _log(f"coverage: positioned {positioned / total:.2%}, linked "
             f"{(total - empty) / total:.2%} of {total} row link(s) "
             f"({empty} empty)")
    _log(f"reported, not failed: {len(artefact['residue'])} residue file(s)")
    report_path = os.path.join(published, "publish-report.json")
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        if report.get("artefact_hash") != artefact_hash:
            fail(f"the published tree was built from artefact "
                 f"{str(report.get('artefact_hash'))[:12]}…, not from this one "
                 f"({artefact_hash[:12]}…) — gate the pair that belongs "
                 f"together")
        if report.get("external references exempted (D50)") != external:
            fail(f"the publish report exempted "
                 f"{report.get('external references exempted (D50)')} external "
                 f"reference(s), the gate counted {external} — the alarm's two "
                 f"numbers must agree")
        _log(f"publish report: dropped {report.get('dropped')}, "
             f"external exempted {report.get('external references exempted (D50)')}, "
             f"dangling stripped {report.get('dangling anchors stripped (D51)')}")
    else:
        fail("the published tree carries no publish-report.json")

    if namespace:
        failures += _gate_namespace_sample(links, namespace, region, sample)

    if failures:
        _log(f"GATE FAILED: {failures} failure(s)")
    else:
        _log("gate passed: zero misses")
    return failures


def _gate_namespace_sample(links: 'dict[str, str]', namespace: str, region: str,
                           sample: int) -> int:
    """§17.5's namespace clause: the live rows' `source_link` must equal the
    composed strings.  The sample is pinned to equidistant endpoints of the
    sorted id space — `ids[i*(n-1)//(sample-1)]` always probes both ends, where
    a stride-and-truncate slice leaves a blind tail exactly where a
    half-finished patch stopped — fetched by an `id In` filter, and fewer rows
    returned than asked for is itself a failure: a gate must not pass on
    missing evidence."""
    from .site_export import api_key, request
    if sample < 2:
        raise SourcePagesError(
            f"--sample {sample} cannot pin both endpoints of the id space; "
            f"use at least 2")
    key = api_key()
    failures = 0
    got = request("POST", f"/v2/namespaces/{namespace}/query",
                  {"aggregate_by": {"rows": ["Count", "id"]}},
                  region=region, key=key)
    count = got.get("aggregations", {}).get("rows")
    if count != len(links):
        failures += 1
        _log(f"  FAIL {namespace} holds {count} row(s), the artefact composes "
             f"{len(links)}")
    ids = sorted(links)
    n = len(ids)
    if n <= sample:
        chosen = ids
    else:
        chosen = [ids[i * (n - 1) // (sample - 1)] for i in range(sample)]
    rows = request("POST", f"/v2/namespaces/{namespace}/query",
                   {"rank_by": ["id", "asc"], "top_k": len(chosen),
                    "filters": ["id", "In", chosen],
                    "include_attributes": ["source_link"]},
                   region=region, key=key).get("rows", [])
    if len(rows) < len(chosen):
        failures += 1
        _log(f"  FAIL asked the namespace for {len(chosen)} row(s), got "
             f"{len(rows)} — missing evidence is not passing evidence")
    for row in rows:
        want = links.get(row["id"])
        have = row.get("source_link") or ""
        if want != have:
            failures += 1
            _log(f"  FAIL row {row['id']}: source_link {have!r}, composed "
                 f"{want!r}")
    _log(f"namespace sample: {len(rows)} row(s) compared, stratified")
    return failures


# ---------------------------------------------------------------------------
# §17.6 — the patch
# ---------------------------------------------------------------------------

# A patch row is ~120 bytes — request latency dominates, so batches run far
# larger than the export's vector-laden BATCH_ROWS.
PATCH_ROWS = 4096


def run_patch(*, artefact_path: str, namespace: str, region: str,
              checkpoint: str, limit: 'int | None',
              allow_count_mismatch: bool) -> None:
    """One `patch_rows` run over every composed id (§17.6, D49 ruling 3): only
    `source_link` is written, vectors are untouched, and turbopuffer ignores
    an id the namespace does not hold.  The namespace is counted before and
    after — an unchanged count is the proof no row was created.

    Ids go up in sorted order, `BATCH_WORKERS` batches at a time, and the
    checkpoint advances only after its whole group is confirmed — the export's
    resume story, reused.  The checkpoint pins the artefact's content hash: a
    resume against a different artefact would skip rows whose links changed."""
    from .site_export import (BATCH_WORKERS, SOURCE_LINK_SCHEMA, _groups,
                              api_key, request)

    artefact, artefact_hash = load_artefact(artefact_path, "map", ARTEFACT_FORMAT)
    links = source_links(artefact)
    key = api_key()
    # 1.3M rows against documented 429 backpressure past 1M unindexed writes:
    # the patch needs a far longer retry horizon than the export's default.
    attempts = 12

    def _count() -> int:
        got = request("POST", f"/v2/namespaces/{namespace}/query",
                      {"aggregate_by": {"rows": ["Count", "id"]}},
                      region=region, key=key, attempts=attempts)
        rows = got.get("aggregations", {}).get("rows")
        if not isinstance(rows, int) or isinstance(rows, bool):
            raise SourcePagesError(
                f"the namespace count query returned {rows!r}, not an "
                f"integer — the count guards prove nothing from missing "
                f"evidence, so the patch refuses to run on it")
        return rows

    before = _count()
    _log(f"{namespace}: {before} row(s); artefact composes {len(links)} link(s)")
    if before != len(links) and not allow_count_mismatch:
        raise SourcePagesError(
            f"the namespace holds {before} row(s) but the artefact composes "
            f"{len(links)} — the store moved since the export, or this is the "
            f"wrong namespace.  A patch to a missing id is ignored and a row "
            f"the artefact misses keeps a null source_link; pass "
            f"--allow-count-mismatch only once you know which case this is.")

    ids = sorted(links)
    done = 0
    if os.path.exists(checkpoint):
        with open(checkpoint, encoding="utf-8") as f:
            state = json.load(f)
        if state.get("namespace") != namespace:
            raise SourcePagesError(
                f"{checkpoint} belongs to {state.get('namespace')!r}, not "
                f"{namespace!r}; delete it or point --checkpoint elsewhere")
        if state.get("artefact_hash") != artefact_hash:
            raise SourcePagesError(
                f"{checkpoint} was written for a different artefact — a resume "
                f"would skip rows whose links the new artefact changed; delete "
                f"it to start over")
        done = int(state["done"])
        if done >= len(ids):
            _log(f"nothing to do: the checkpoint says all {done} row(s) were "
                 f"already patched")
            return
        _log(f"resuming after {done} patched row(s)")
    todo = ids[done:]
    if limit is not None:
        todo = todo[:limit]

    def _write_checkpoint(done: int) -> None:
        tmp = checkpoint + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"namespace": namespace, "done": done,
                       "artefact_hash": artefact_hash}, f)
        os.replace(tmp, checkpoint)

    # Written before the first batch: an unwritable checkpoint path must fail
    # here, not after a batch group has already landed on the live store.
    _write_checkpoint(done)

    schema = {"source_link": SOURCE_LINK_SCHEMA}

    def patch(batch: 'list[str]') -> None:
        request("POST", f"/v2/namespaces/{namespace}",
                {"patch_rows": [{"id": i, "source_link": links[i]}
                                for i in batch],
                 "schema": schema}, region=region, key=key, attempts=attempts)

    batches = _groups(todo, PATCH_ROWS)
    with concurrent.futures.ThreadPoolExecutor(BATCH_WORKERS) as pool:
        for group in _groups(batches, BATCH_WORKERS):
            list(pool.map(patch, group))
            done += sum(len(b) for b in group)
            _write_checkpoint(done)
            _log(f"  {done} row(s) patched")

    after = _count()
    if after != before:
        raise SourcePagesError(
            f"the namespace's row count changed from {before} to {after} "
            f"during the patch — patch_rows must never create or remove "
            f"rows; inspect before anything else touches it")
    _log(f"patched {done} row(s); {namespace} still holds {after} row(s)")


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def build_parser(**kw) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m Isabelle_Semantic_Embedding.site_source_pages",
        description="The source-page upload pass (SEMANTIC_SEARCH_SITE_PLAN.md "
                    "§17): scan the corpus, build the file→page map, publish "
                    "the tree, gate it, patch the namespace.", **kw)
    sub = p.add_subparsers(dest="step", required=True)

    scan = sub.add_parser("scan", help="the corpus scan (§17.1), on the machine "
                                       "with the semantic DB")
    scan.add_argument("--isabelle-home",
                      help="the distribution tree (default: $ISABELLE_HOME)")
    scan.add_argument("--afp",
                      help="the AFP snapshot tree (default: the parent of $AFP)")
    scan.add_argument("--out", required=True, help="where the scan output goes")

    mp = sub.add_parser("map", help="the file→page map and the classification "
                                    "(§17.3), beside the rendered tree, the "
                                    "authoritative registry and the source trees")
    mp.add_argument("--scan", required=True, help="the corpus scan's output")
    mp.add_argument("--rendered", required=True, help="the rendered tree's root")
    mp.add_argument("--theories", required=True,
                    help="data/theories.json — D53's file-path→long-name table")
    mp.add_argument("--repo-root",
                    help="the checkout root the table's relative paths resolve "
                         "against (default: two levels above --theories; pass "
                         "it when --theories points at a copy)")
    mp.add_argument("--out", required=True, help="where the artefact goes")

    pub = sub.add_parser("publish", help="the pass (§17.4): rendered tree → "
                                         "published tree")
    pub.add_argument("--rendered", required=True, help="the rendered tree's root")
    pub.add_argument("--artefact", required=True)
    pub.add_argument("--out", required=True,
                     help="the published tree; must not exist yet")

    gate = sub.add_parser("gate", help="the link-check gate (§17.5) over the "
                                       "published tree")
    gate.add_argument("--published", required=True)
    gate.add_argument("--artefact", required=True)
    gate.add_argument("--namespace",
                      help="also compare a stratified sample of this "
                           "namespace's source_link values (needs the API key)")
    gate.add_argument("--region", default=None)
    gate.add_argument("--sample", type=int, default=500)

    patch = sub.add_parser("patch", help="write source_link onto every row of "
                                         "the live namespace (§17.6)")
    patch.add_argument("--artefact", required=True)
    patch.add_argument("--namespace", required=True)
    patch.add_argument("--region", default=None)
    patch.add_argument("--checkpoint", default="source-link-patch.checkpoint.json")
    patch.add_argument("--limit", type=int,
                       help="stop after this many rows; for a smoke test")
    patch.add_argument("--allow-count-mismatch", action="store_true",
                       help="proceed although the namespace's row count is not "
                            "the artefact's record count")
    return p


def run_from_args(args: argparse.Namespace) -> int:
    from .site_export import DEFAULT_REGION, ExportError, _default_trees
    try:
        if args.step == "scan":
            home, afp = args.isabelle_home, args.afp
            if not (home and afp):
                found_home, found_afp = _default_trees()
                home, afp = home or found_home, afp or found_afp
            run_scan(isabelle_home=home, afp_dir=afp, out=args.out)
        elif args.step == "map":
            run_map(scan_path=args.scan, rendered=args.rendered,
                    theories_path=args.theories, out=args.out,
                    repo_root=args.repo_root)
        elif args.step == "publish":
            run_publish(rendered=args.rendered, artefact_path=args.artefact,
                        out=args.out)
        elif args.step == "gate":
            return 1 if run_gate(published=args.published,
                                 artefact_path=args.artefact,
                                 namespace=args.namespace,
                                 region=args.region or DEFAULT_REGION,
                                 sample=args.sample) else 0
        elif args.step == "patch":
            run_patch(artefact_path=args.artefact, namespace=args.namespace,
                      region=args.region or DEFAULT_REGION,
                      checkpoint=args.checkpoint, limit=args.limit,
                      allow_count_mismatch=args.allow_count_mismatch)
    except (SourcePagesError, ExportError) as e:
        print(f"[source-pages] {e}", file=sys.stderr)
        return 1
    return 0


def main(argv: 'list[str] | None' = None) -> int:
    return run_from_args(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
