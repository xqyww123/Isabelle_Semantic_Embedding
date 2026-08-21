r"""The source-page upload pass (SEMANTIC_SEARCH_SITE_PLAN.md §17): the rendered
tree becomes the published tree, and every namespace row gains its finished
source link.

Five steps, run as subcommands, on the machines §17.1 assigns them to:

* **scan** — the corpus scan, on the machine with the semantic DB: walks exactly
  the record set the site export publishes (`site_export.iter_shippable`, one
  filter chain for both) and writes the needed-lines table plus the per-record
  position list the resolver, the gate and the patch consume.
* **map** — on cslh19, beside the rendered tree and the authoritative registry:
  builds the file→page map with §17.3's three-step resolver and resolves every
  record's link.  Map, table and links ship onward as **one artefact whose
  content hash every later step re-checks**, so no step ever reads "whichever
  registry or table this machine happens to have".
* **publish** — the pass itself (§17.4), on cslh19: one walk that relocates the
  kept pages, rewrites every reference per file type, injects the needed line
  marks, merges the conflicting auxiliary copies by id-union (D49 ruling 6),
  and generates the index and the one stylesheet — all into a fresh directory
  that is atomically renamed into place.  It never deletes or writes into a
  directory it was handed, so a partially transformed tree is unrepresentable.
* **gate** — the link-check gate (§17.5) over the published tree: zero misses
  on marks and references, every fragment checked, no anchor trusted.
* **patch** — on the machine with the turbopuffer key: one `patch_rows` run
  writing `source_link` onto every row of the live namespace (§17.6, D49
  ruling 3).  turbopuffer ignores a patch to an id that does not exist
  ("patches will not create any missing documents"), and the run counts the
  namespace before and after to prove it.
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
# §17.1 — the corpus scan
# ---------------------------------------------------------------------------

SCAN_FORMAT = 1


def run_scan(*, isabelle_home: str, afp_dir: str, out: str) -> None:
    """The corpus scan: the needed-lines table and the per-record position list,
    from exactly the record set the export publishes.

    The output's `records` carry every published document id — a record with no
    linkable position rides with file index -1, because the patch writes
    `source_link` onto every row (D49 ruling 3), empty string included.
    `declaring_theory_hashes` is §17.3 step 1's input: per `.thy` position file,
    the declaring-theory hashes of the name-addressed records positioned there —
    an XOR-prefixed key's 16-byte prefix is a pseudo-theory (D13) and never
    enters."""
    from Isabelle_RPC_Host.universal_key import is_xor_prefixed_key
    from .site_export import declared_sessions, document_id, iter_shippable, theory_registry

    sessions = declared_sessions(isabelle_home, afp_dir)
    _log(f"{len(sessions)} declared session(s) in scope (D24)")
    registry = theory_registry()
    _log(f"{len(registry)} theory-hash registry entr(ies)")

    counts: 'dict[str, int]' = dict.fromkeys(
        ("records", "undecodable", "wip", "experience", "out of scope"), 0)
    file_index: 'dict[str, int]' = {}
    needed: 'dict[str, set[int]]' = {}
    declaring: 'dict[str, set[str]]' = {}
    records: 'list[list]' = []
    for key, rec, _theories in iter_shippable(sessions, registry, counts):
        pos = rec.position
        if pos and linkable(pos[0]):
            file, line = pos[0], pos[1]
            fi = file_index.setdefault(file, len(file_index))
            needed.setdefault(file, set()).add(line)
            if file.endswith(".thy") and not is_xor_prefixed_key(key):
                declaring.setdefault(file, set()).add(key[:16].hex())
            records.append([document_id(key), fi, line])
        else:
            records.append([document_id(key), -1, 0])

    files = list(file_index)          # insertion-ordered, so index i is files[i]
    pairs = sum(len(lines) for lines in needed.values())
    body = {
        "format": SCAN_FORMAT,
        "files": files,
        "needed_lines": {f: sorted(lines) for f, lines in needed.items()},
        "declaring_theory_hashes": {f: sorted(h) for f, h in declaring.items()},
        "records": records,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, separators=(",", ":"))
    for what, n in counts.items():
        _log(f"  {what:<14} {n}")
    _log(f"wrote {out}: {len(records)} record(s), {len(files)} linkable "
         f"position file(s), {pairs} needed (file, line) pair(s)")


# ---------------------------------------------------------------------------
# The artefact — one file, self-hashed, every later step re-checks it (§17.1)
# ---------------------------------------------------------------------------

ARTEFACT_FORMAT = 1


def _canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def write_artefact(path: str, body: dict) -> str:
    """Writes `{"content_hash": …, "body": …}` and returns the hash."""
    digest = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"content_hash": digest, "body": body}, f,
                  ensure_ascii=False, separators=(",", ":"))
    return digest


def load_artefact(path: str) -> dict:
    """The artefact's body, refused unless its content hash still holds — the
    "one versioned artefact" clause of §17.1, applied at every read."""
    with open(path, encoding="utf-8") as f:
        stored = json.load(f)
    body = stored.get("body")
    digest = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    if digest != stored.get("content_hash"):
        raise SourcePagesError(
            f"{path} does not match its own content hash — a truncated copy or "
            f"a hand edit; re-ship it from the machine that built it")
    if body.get("format") != ARTEFACT_FORMAT:
        raise SourcePagesError(
            f"{path} has artefact format {body.get('format')!r}, this code "
            f"reads {ARTEFACT_FORMAT}")
    return body


# ---------------------------------------------------------------------------
# The rendered tree, classified (§17.2's declared classes)
# ---------------------------------------------------------------------------

class RenderedTree:
    """One walk's worth of classification: which rendered file is which
    published class.  `dropped` counts what §17.2 declares out — the renderer's
    indexes, the session graphs, the per-directory stylesheet copies, the gif,
    the `.browser_info/` bookkeeping — plus anything unclassifiable, which the
    report surfaces rather than the walk refusing (D49 ruling 4: absence of a
    *referenced* file is the gate's hard error; unreferenced presence is a
    dropped count)."""

    def __init__(self) -> None:
        self.theory_pages: 'dict[str, str]' = {}      # stem -> tree-relative path
        self.aux_copies: 'dict[str, list[str]]' = {}  # symbolic position -> paths
        self.css_copies: 'list[str]' = []
        self.fonts: 'list[str]' = []
        self.dropped: 'dict[str, int]' = {}
        self.unclassified: 'list[str]' = []

    def _drop(self, what: str) -> None:
        self.dropped[what] = self.dropped.get(what, 0) + 1


def classify_rendered_tree(root: str) -> RenderedTree:
    tree = RenderedTree()
    for dirpath, _dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        for name in filenames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}".replace(os.sep, "/")
            parts = rel.split("/")
            if ".browser_info" in parts:
                tree._drop(".browser_info bookkeeping")
            elif name == "isabelle.css":
                tree.css_copies.append(rel)
            elif name == "index.html" and len(parts) <= 3:
                tree._drop("renderer index page")      # root, chapter or session
            elif parts[0] == "fonts":
                tree.fonts.append(rel)
            elif name == "session_graph.pdf":
                tree._drop("session graph")
            elif name == "isabelle.gif":
                tree._drop("isabelle.gif")
            elif len(parts) == 3 and name.endswith(".html"):
                stem = name[:-len(".html")]
                if stem in tree.theory_pages:
                    raise SourcePagesError(
                        f"theory page stem {stem!r} is not unique: "
                        f"{tree.theory_pages[stem]} and {rel} — §17.2's flat "
                        f"layout rests on all stems being distinct")
                tree.theory_pages[stem] = rel
            elif len(parts) >= 4 and (sym := aux_symbolic("/".join(parts[2:]))):
                tree.aux_copies.setdefault(sym, []).append(rel)
            else:
                tree._drop("unclassified")
                tree.unclassified.append(rel)
    for copies in tree.aux_copies.values():
        copies.sort()
    return tree


# ---------------------------------------------------------------------------
# §17.3 — the file→page map and the resolver
# ---------------------------------------------------------------------------

def page_for_name(name: str, theory_pages: 'dict[str, str]') -> 'str | None':
    """The published stem serving theory `name` — §17.3's page choice: when the
    bare and the session-qualified page both render the same file (the three
    bare/qualified twins, `HOLCF` vs `HOLCF.HOLCF` and kin), the
    session-qualified page wins."""
    if "." not in name and f"{name}.{name}" in theory_pages:
        return f"{name}.{name}"
    return name if name in theory_pages else None


def resolve_thy(file: str, declaring: 'list[str]', registry_by_hash: 'dict[str, str]',
                registry_names: 'set[str]', by_base: 'dict[str, list[str]]',
                theory_pages: 'dict[str, str]') -> 'tuple[str | None, str]':
    """§17.3's steps for one `.thy` position file: `(published page stem, how)`
    or `(None, why)` — the latter being residue, not an error.  The page stem
    comes through `page_for_name`, so a resolved bare name still lands on the
    session-qualified twin page when one exists.

    Step 1 is exact: a name-addressed record's declaring theory, by key hash.
    When several theories' records sit in one file (the two known multi-theory
    files), the theory whose base name is the file stem wins; anything still
    ambiguous is a hard error, because the review measured no such case and a
    silent pick would link a file to a page showing some other file's source.

    Step 2 is the stem lookup: an exact whole-name hit beats base-name
    candidates (the bare/qualified twins), and several base-name candidates
    resolve nothing — guessing between two unrelated theories that share a
    base name is what step 2 must not do."""
    stem = file.rsplit("/", 1)[-1][:-len(".thy")]
    named = sorted({registry_by_hash[h] for h in declaring if h in registry_by_hash})
    candidates = [n for n in named if page_for_name(n, theory_pages)]
    if candidates:
        if len(candidates) > 1:
            by_stem = [n for n in candidates if n.rsplit(".", 1)[-1] == stem]
            if len(by_stem) != 1:
                raise SourcePagesError(
                    f"{file} carries records of several theories "
                    f"({', '.join(candidates)}) and the file stem settles "
                    f"nothing — §17.3 step 1 has no rule for this")
            candidates = by_stem
        return page_for_name(candidates[0], theory_pages), "declaring theory"
    if stem in registry_names and page_for_name(stem, theory_pages):
        return page_for_name(stem, theory_pages), "stem, whole name"
    base = sorted({n for n in by_base.get(stem, ()) if page_for_name(n, theory_pages)})
    if len(base) == 1:
        return page_for_name(base[0], theory_pages), "stem, base name"
    if base:
        return None, f"several registry names share the stem: {', '.join(base)}"
    return None, "no registry name matches the stem"


def build_file_page_map(scan: dict, theory_pages: 'dict[str, str]',
                        aux_copies: 'dict[str, list[str]]',
                        registry_by_hash: 'dict[str, str]',
                        ) -> 'tuple[dict[str, str], dict[str, str], dict[str, int]]':
    """The file→page map over the scan's linkable files: `(map, residue, how)`,
    where `how` counts which of §17.3's routes resolved each file.  Includes
    the collision guard (§17.7): two position files on one page would fuse two
    files' line numbering into one mark space."""
    registry_names = set(registry_by_hash.values())
    by_base: 'dict[str, list[str]]' = {}
    for name in registry_names:
        by_base.setdefault(name.rsplit(".", 1)[-1], []).append(name)

    file_page_map: 'dict[str, str]' = {}
    residue: 'dict[str, str]' = {}
    how_counts: 'dict[str, int]' = {}
    declaring = scan["declaring_theory_hashes"]
    for file in scan["files"]:
        if file.endswith(".thy"):
            chosen, how = resolve_thy(file, declaring.get(file, []),
                                      registry_by_hash, registry_names, by_base,
                                      theory_pages)
            if chosen is None:
                residue[file] = how
                continue
            file_page_map[file] = f"{SITE_PREFIX}{chosen}.html"
        else:
            page = aux_page(file)
            if file not in aux_copies:
                residue[file] = "no rendered auxiliary copy"
                continue
            file_page_map[file] = page
            how = "auxiliary path function"
        how_counts[how] = how_counts.get(how, 0) + 1

    page_of: 'dict[str, str]' = {}
    for file, page in file_page_map.items():
        if page in page_of:
            raise SourcePagesError(
                f"{page_of[page]} and {file} both map to {page} — two files "
                f"cannot share one page's line marks")
        page_of[page] = file
    return file_page_map, residue, how_counts


def resolve_links(scan: dict, file_page_map: 'dict[str, str]',
                  residue: 'dict[str, str]') -> 'tuple[dict[str, str], int]':
    """Every record's finished link (D49 ruling 2): `page#L<line>` for a mapped
    position, the empty string — D42's absent form — for no position and for
    residue alike.  `(links, how many are non-empty)`."""
    files = scan["files"]
    links: 'dict[str, str]' = {}
    linked = 0
    for doc_id, fi, line in scan["records"]:
        if fi < 0 or files[fi] in residue:
            links[doc_id] = ""
        else:
            links[doc_id] = f"{file_page_map[files[fi]]}#L{line}"
            linked += 1
    if len(links) != len(scan["records"]):
        raise SourcePagesError(
            f"{len(scan['records'])} record(s) yielded {len(links)} link(s) — "
            f"duplicate document ids in the scan")
    return links, linked


def run_map(*, scan_path: str, rendered: str, out: str) -> None:
    """Builds the file→page map, resolves every record's link, writes the
    artefact.  Runs beside the rendered tree and the **authoritative** registry
    (§17.1: cslh19's copy — the workstation's carries 38 private extra names
    that must never feed a public mapping)."""
    from .site_export import theory_registry

    with open(scan_path, encoding="utf-8") as f:
        scan = json.load(f)
    if scan.get("format") != SCAN_FORMAT:
        raise SourcePagesError(
            f"{scan_path} has scan format {scan.get('format')!r}, this code "
            f"reads {SCAN_FORMAT}")
    tree = classify_rendered_tree(rendered)
    _log(f"rendered tree: {len(tree.theory_pages)} theory page(s), "
         f"{sum(len(c) for c in tree.aux_copies.values())} auxiliary cop(ies) of "
         f"{len(tree.aux_copies)} symbolic path(s)")
    registry_by_hash = {k.hex(): name for k, name in theory_registry().items()}
    _log(f"{len(registry_by_hash)} registry entr(ies), "
         f"{len(set(registry_by_hash.values()))} distinct name(s)")

    file_page_map, residue, how_counts = build_file_page_map(
        scan, tree.theory_pages, tree.aux_copies, registry_by_hash)
    links, linked = resolve_links(scan, file_page_map, residue)

    files = scan["files"]
    needed_lines = scan["needed_lines"]
    residue_records = sum(1 for _id, fi, _l in scan["records"]
                          if fi >= 0 and files[fi] in residue)
    residue_lines = sum(len(needed_lines[f]) for f in residue)
    body = {
        "format": ARTEFACT_FORMAT,
        "registry_entries": len(registry_by_hash),
        "file_page_map": file_page_map,
        "residue": residue,
        "needed_lines": needed_lines,
        "links": links,
    }
    digest = write_artefact(out, body)
    for how, n in sorted(how_counts.items()):
        _log(f"  resolved by {how:<24} {n}")
    _log(f"  residue: {len(residue)} file(s), {residue_records} record(s), "
         f"{residue_lines} needed line(s)")
    for file, why in sorted(residue.items()):
        _log(f"    {file}: {why}")
    _log(f"  linked {linked} of {len(links)} record(s) "
         f"({linked / len(links):.2%})")
    _log(f"wrote {out} (content hash {digest[:12]})")


# ---------------------------------------------------------------------------
# §17.4 — the transforms
# ---------------------------------------------------------------------------

# Tags never contain a newline (measured tree-wide, asserted per page), and text
# never contains a raw `<`, so tags are exactly these spans — which is what lets
# reference rewriting touch attributes without ever touching displayed source
# code that happens to say `href="…"`.
_TAG = re.compile(r"<[^>]*>")
_REF_ATTR = re.compile(r'\b(href|src)="([^"]*)"')
_CSS_URL = re.compile(r"url\('([^']*)'\)")
_NEWLINE_IN_TAG = re.compile(r"<[^>]*\n")
_LINE_MARK = re.compile(r'id="L\d+"')   # \d+ and nothing looser: bare `id="L`
                                        # matches 555 innocent pages (§17.4)


def rewrite_html_refs(content: str, page_dir: str,
                      relocation: 'dict[str, str]', page_rel: str) -> str:
    """§17.4's reference rewrite for a page: every `href`/`src`, split from its
    fragment, resolved against the page's rendered location, mapped, re-emitted
    absolute under `/source/`, fragment re-attached unchanged.  A reference the
    map cannot name is a hard error naming the page and the reference."""
    def fix_ref(m: 're.Match') -> str:
        attr, ref = m.group(1), m.group(2)
        target, _, fragment = ref.partition("#")
        if not target:
            return m.group(0)             # a same-page fragment does not move
        resolved = posixpath.normpath(posixpath.join(page_dir, target))
        published = relocation.get(resolved)
        if published is None:
            raise SourcePagesError(
                f"{page_rel} references {ref!r} ({resolved}), which maps to no "
                f"published file")
        suffix = f"#{fragment}" if fragment else ""
        return f'{attr}="{published}{suffix}"'

    return _TAG.sub(lambda tag: _REF_ATTR.sub(fix_ref, tag.group(0)), content)


def rewrite_css_urls(content: str, css_dir: str,
                     relocation: 'dict[str, str]', css_rel: str) -> str:
    """The same rewrite for a stylesheet's `url()` references — per file type,
    not per HTML attribute (§17.4)."""
    def fix_url(m: 're.Match') -> str:
        resolved = posixpath.normpath(posixpath.join(css_dir, m.group(1)))
        published = relocation.get(resolved)
        if published is None:
            raise SourcePagesError(
                f"{css_rel} references url({m.group(1)!r}) ({resolved}), which "
                f"maps to no published file")
        return f"url('{published}')"

    return _CSS_URL.sub(fix_url, content)


_PRE_OPEN = '<pre class="source">'
_PRE_CLOSE = "</pre>"


def inject_line_marks(page: str, lines: 'list[int]', page_rel: str) -> str:
    """§17.4's injection: the window is the content of the page's single
    `<pre class="source">` element; split on newlines, piece *n* is line *n*
    (piece count is line count — measured line-for-line fidelity, EOF
    trailing-newline convention aside), and each needed line gets an
    `<a id="L<n>"></a>` prefix.

    The two structural facts that make this sound are asserted per page,
    because they are the whole correctness argument: exactly one
    `<pre class="source">`, and no newline inside any tag.  A page already
    carrying an `id="L<digits>"` would collide with the marks; a needed line
    with no piece to land on means the line-fidelity assumption broke."""
    if _LINE_MARK.search(page):
        raise SourcePagesError(
            f'{page_rel} already carries an id="L<digits>" anchor, which the '
            f"injected marks would collide with (§17.4)")
    if page.count(_PRE_OPEN) != 1:
        raise SourcePagesError(
            f"{page_rel} has {page.count(_PRE_OPEN)} '{_PRE_OPEN}' elements, "
            f"not exactly one — the injection window is undefined")
    if _NEWLINE_IN_TAG.search(page):
        raise SourcePagesError(
            f"{page_rel} has a newline inside a tag, so splitting the source "
            f"window on newlines would cut a tag in half")
    head, _, rest = page.partition(_PRE_OPEN)
    window, close, tail = rest.partition(_PRE_CLOSE)
    if not close or _PRE_CLOSE in tail:
        raise SourcePagesError(
            f"{page_rel} does not close its source element exactly once")
    pieces = window.split("\n")
    for n in sorted(lines):
        if not 1 <= n <= len(pieces):
            raise SourcePagesError(
                f"{page_rel} shows {len(pieces)} source line(s) but line {n} "
                f"is needed — the line-fidelity assumption broke (§17.4)")
        pieces[n - 1] = f'<a id="L{n}"></a>' + pieces[n - 1]
    return head + _PRE_OPEN + "\n".join(pieces) + close + tail


def _ids_in_tags(line: str) -> 'set[str]':
    return {m.group(1) for tag in _TAG.finditer(line)
            for m in re.finditer(r'\bid="([^"]*)"', tag.group(0))}


def _without_tag_ids(line: str) -> str:
    return _TAG.sub(lambda tag: re.sub(r'\bid="[^"]*"', 'id=""', tag.group(0)),
                    line)


def merge_aux_copies(copies: 'list[tuple[str, str]]') -> 'tuple[str, bool]':
    """D49 ruling 6: one auxiliary page per symbolic path, and the conflicting
    copies — byte-identical except in their entity-anchor ids — publish the
    id-union, so every fragment reference into any copy keeps landing.
    `(merged content, whether copies conflicted)`.

    The merge is line-aligned: lines must agree once id attributes are blanked
    (anything more than an id difference is not the measured conflict and stops
    the pass), and an id another copy carries on a line the base lacks becomes
    an empty anchor at the front of that line — same line, same landing."""
    (base_rel, base), *rest = copies
    if all(content == base for _rel, content in rest):
        return base, False
    base_lines = base.split("\n")
    merged = list(base_lines)
    for rel, content in rest:
        lines = content.split("\n")
        if len(lines) != len(merged):
            raise SourcePagesError(
                f"{rel} and {base_rel} render one file with different line "
                f"counts — not the measured id-only conflict")
        for i, other in enumerate(lines):
            if other == base_lines[i]:
                continue
            if _without_tag_ids(other) != _without_tag_ids(base_lines[i]):
                raise SourcePagesError(
                    f"{rel} and {base_rel} differ beyond entity-anchor ids at "
                    f"line {i + 1} — not the measured id-only conflict")
            extra = _ids_in_tags(other) - _ids_in_tags(merged[i])
            if extra:
                anchors = "".join(f'<a id="{x}"></a>' for x in sorted(extra))
                merged[i] = anchors + merged[i]
    return "\n".join(merged), True


# What the generated index page says.  Ruling 5 fixed the shape — every
# published theory long name as a link, grouped by session, alphabetical, the
# same stylesheet — and this is the wording pending the user's verbatim
# approval (user-visible copy rule).
INDEX_TITLE = "Source pages"


def generate_index(theory_stems: 'list[str]') -> str:
    """D49 ruling 5's `/source/index.html`.  Grouping is by
    `site_export.session_of` — the same reading of a long name the export
    filters by, so the index cannot invent a second notion of session."""
    from .site_export import session_of
    groups: 'dict[str, list[str]]' = {}
    for stem in theory_stems:
        groups.setdefault(session_of(stem), []).append(stem)
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
        '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>'
        f'<link rel="stylesheet" type="text/css" href="{SITE_PREFIX}isabelle.css"/>\n'
        f"<title>{html.escape(INDEX_TITLE)}</title>\n</head>\n<body>\n"
        f'<div class="head"><h1>{html.escape(INDEX_TITLE)}</h1></div>\n'
    ]
    for session in sorted(groups):
        parts.append(f"<h2>{html.escape(session)}</h2>\n<ul>\n")
        for stem in sorted(groups[session]):
            parts.append(f'<li><a href="{SITE_PREFIX}{html.escape(stem)}.html">'
                         f"{html.escape(stem)}</a></li>\n")
        parts.append("</ul>\n")
    parts.append("</body>\n</html>\n")
    return "".join(parts)


def run_publish(*, rendered: str, artefact_path: str, out: str) -> None:
    """The pass (§17.4): one walk over the rendered tree into a fresh output
    directory, atomically renamed to `out` at the end.  It refuses to start if
    `out` or the staging directory exists — it never deletes a handed path, so
    a partially transformed tree is unrepresentable."""
    artefact = load_artefact(artefact_path)
    out = out.rstrip("/")
    staging = out + ".building"
    for path in (out, staging):
        if os.path.exists(path):
            raise SourcePagesError(
                f"{path} already exists; the pass never deletes a handed path — "
                f"move it aside yourself if it is stale")
    tree = classify_rendered_tree(rendered)

    relocation: 'dict[str, str]' = {}
    for stem, rel in tree.theory_pages.items():
        relocation[rel] = f"{SITE_PREFIX}{stem}.html"
    for sym, rels in tree.aux_copies.items():
        for rel in rels:
            relocation[rel] = aux_page(sym)
    for rel in tree.css_copies:
        relocation[rel] = f"{SITE_PREFIX}isabelle.css"
    for rel in tree.fonts:
        relocation[rel] = f"{SITE_PREFIX}fonts/{rel.rsplit('/', 1)[-1]}"

    # Needed lines, keyed by the published page each mapped file resolves to.
    # One file per page — the map's collision guard proved it; re-proved here
    # because the injection is where a collision would corrupt line numbering.
    needed_by_page: 'dict[str, list[int]]' = {}
    for file, page in artefact["file_page_map"].items():
        lines = artefact["needed_lines"].get(file)
        if not lines:
            continue
        if page in needed_by_page:
            raise SourcePagesError(
                f"two position files map to {page} — the artefact violates its "
                f"own collision guard")
        needed_by_page[page] = lines
    expected_marks = sum(len(lines) for lines in needed_by_page.values())

    def _dest(page: str) -> str:
        assert page.startswith(SITE_PREFIX)
        return os.path.join(staging, *page[len(SITE_PREFIX):].split("/"))

    def _write(page: str, content: str) -> None:
        dest = _dest(page)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)

    os.makedirs(staging)
    marks = 0
    merged_conflicts = 0

    def _transform(rel: str, content: str, page: str) -> str:
        nonlocal marks
        content = rewrite_html_refs(content, posixpath.dirname(rel),
                                    relocation, rel)
        lines = needed_by_page.get(page)
        if lines:
            content = inject_line_marks(content, lines, rel)
            marks += len(lines)
        return content

    for stem, rel in sorted(tree.theory_pages.items()):
        with open(os.path.join(rendered, rel), encoding="utf-8") as f:
            content = f.read()
        page = relocation[rel]
        _write(page, _transform(rel, content, page))

    for sym, rels in sorted(tree.aux_copies.items()):
        copies = []
        for rel in rels:
            with open(os.path.join(rendered, rel), encoding="utf-8") as f:
                copies.append((rel, f.read()))
        content, conflicted = merge_aux_copies(copies)
        merged_conflicts += conflicted
        page = aux_page(sym)
        _write(page, _transform(rels[0], content, page))

    # §17.2: exactly one generated stylesheet with absolute font URLs.  The 335
    # rendered copies come in 9 variants differing only in `@font-face` depth,
    # so after the rewrite they must all be one text — asserted, because a
    # second variant would mean the tree is not what was measured.
    rewritten_css = set()
    for rel in tree.css_copies:
        with open(os.path.join(rendered, rel), encoding="utf-8") as f:
            rewritten_css.add(rewrite_css_urls(f.read(), posixpath.dirname(rel),
                                               relocation, rel))
    if len(rewritten_css) != 1:
        raise SourcePagesError(
            f"the {len(tree.css_copies)} stylesheet copies rewrite to "
            f"{len(rewritten_css)} distinct texts, not one — they differ beyond "
            f"their font-URL depth")
    _write(f"{SITE_PREFIX}isabelle.css", rewritten_css.pop())

    for rel in tree.fonts:
        dest = _dest(relocation[rel])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(os.path.join(rendered, rel), dest)

    _write(f"{SITE_PREFIX}index.html", generate_index(sorted(tree.theory_pages)))

    if marks != expected_marks:
        raise SourcePagesError(
            f"injected {marks} line mark(s) but the artefact needs "
            f"{expected_marks} — some mapped page was never written")

    report = {
        "published": {
            "theory pages": len(tree.theory_pages),
            "auxiliary pages": len(tree.aux_copies),
            "fonts": len(tree.fonts),
            "generated": ["index.html", "isabelle.css"],
        },
        "marks injected": marks,
        "auxiliary conflicts merged": merged_conflicts,
        "dropped": tree.dropped,
        "unclassified": tree.unclassified,
    }
    os.rename(staging, out)
    with open(out + ".report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    _log(f"published {out}: {len(tree.theory_pages)} theory page(s), "
         f"{len(tree.aux_copies)} auxiliary page(s), {marks} mark(s), "
         f"{merged_conflicts} merged conflict(s)")
    for what, n in sorted(tree.dropped.items()):
        _log(f"  dropped {what:<28} {n}")
    if tree.unclassified:
        _log(f"  unclassified files (dropped): {tree.unclassified[:10]}"
             + (" …" if len(tree.unclassified) > 10 else ""))


# ---------------------------------------------------------------------------
# §17.5 — the link-check gate
# ---------------------------------------------------------------------------

def run_gate(*, published: str, artefact_path: str, namespace: 'str | None',
             region: str, sample: int) -> int:
    """The gate, over the published tree: every needed (file, line) has its
    mark, every reference in every published file resolves — fragments
    included, no anchor trusted — and every non-empty link in the artefact is
    string-equal to a path the tree serves with the named mark present.
    Returns the number of failures; the counts §17.5 reports rather than fails
    on are logged."""
    artefact = load_artefact(artefact_path)
    files: 'set[str]' = set()
    for dirpath, _dirnames, filenames in os.walk(published):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), published)
            files.add(rel.replace(os.sep, "/"))

    id_cache: 'dict[str, set[str]]' = {}

    def _read(rel: str) -> str:
        with open(os.path.join(published, rel), encoding="utf-8") as f:
            return f.read()

    def ids_of(rel: str) -> 'set[str]':
        if rel not in id_cache:
            id_cache[rel] = _ids_in_tags(_read(rel))
        return id_cache[rel]

    failures = 0

    def fail(msg: str) -> None:
        nonlocal failures
        failures += 1
        if failures <= 50:
            _log(f"  FAIL {msg}")

    def _site_rel(target: str, base_rel: str) -> 'str | None':
        if target.startswith(SITE_PREFIX):
            return target[len(SITE_PREFIX):]
        if target.startswith("/") or "://" in target:
            return None
        return posixpath.normpath(posixpath.join(posixpath.dirname(base_rel),
                                                 target))

    # Every needed (file, line): the mapped page exists and carries its mark.
    checked_pairs = 0
    for file, page in sorted(artefact["file_page_map"].items()):
        lines = artefact["needed_lines"].get(file, [])
        if not lines:
            continue
        rel = page[len(SITE_PREFIX):]
        if rel not in files:
            fail(f"{file} maps to {page}, which the tree does not serve")
            continue
        page_ids = ids_of(rel)
        for line in lines:
            checked_pairs += 1
            if f"L{line}" not in page_ids:
                fail(f"{page} lacks the mark for {file} line {line}")
    _log(f"checked {checked_pairs} needed (file, line) pair(s)")

    # Every reference in every published file, fragments included.
    checked_refs = 0
    for rel in sorted(files):
        if rel.endswith(".html"):
            content = _read(rel)
            refs = [(m.group(2))
                    for tag in _TAG.finditer(content)
                    for m in _REF_ATTR.finditer(tag.group(0))]
        elif rel.endswith(".css"):
            refs = [m.group(1) for m in _CSS_URL.finditer(_read(rel))]
        else:
            continue
        for ref in refs:
            target, _, fragment = ref.partition("#")
            if not target:
                target_rel = rel              # a same-page fragment
            else:
                target_rel = _site_rel(target, rel)
            checked_refs += 1
            if target_rel is None or target_rel not in files:
                fail(f"{rel} references {ref!r}, which the tree does not serve")
                continue
            if fragment and fragment not in ids_of(target_rel):
                fail(f"{rel} references {ref!r}, whose fragment matches no id "
                     f"on {target_rel}")
    _log(f"checked {checked_refs} reference(s) across "
         f"{sum(1 for r in files if r.endswith(('.html', '.css')))} file(s)")

    # Every row's source link, literally — the end-to-end clause of D49
    # ruling 2: the string the site will emit is the string that works.
    empty = 0
    for doc_id, link in artefact["links"].items():
        if not link:
            empty += 1
            continue
        target, _, fragment = link.partition("#")
        if not target.startswith(SITE_PREFIX):
            fail(f"link for {doc_id} is {link!r}, not under {SITE_PREFIX}")
            continue
        rel = target[len(SITE_PREFIX):]
        if rel not in files:
            fail(f"link for {doc_id} names {target}, which the tree does not "
                 f"serve")
        elif not fragment or fragment not in ids_of(rel):
            fail(f"link for {doc_id} is {link!r}, whose fragment matches no id")
    total = len(artefact["links"])
    _log(f"checked {total} row link(s): {total - empty} linked, {empty} empty "
         f"({(total - empty) / total:.2%} linked)" if total else "no links")
    _log(f"reported, not failed: {len(artefact['residue'])} residue file(s)")

    if namespace:
        failures += _gate_namespace_sample(artefact, namespace, region, sample)

    if failures:
        _log(f"GATE FAILED: {failures} failure(s)")
    else:
        _log("gate passed: zero misses")
    return failures


def _gate_namespace_sample(artefact: dict, namespace: str, region: str,
                           sample: int) -> int:
    """§17.5's namespace clause, sampled: the patched rows' `source_link` must
    be string-equal to the artefact's, and the row count must be the link
    count."""
    from .site_export import api_key, request
    key = api_key()
    failures = 0
    got = request("POST", f"/v2/namespaces/{namespace}/query",
                  {"aggregate_by": {"rows": ["Count", "id"]}},
                  region=region, key=key)
    count = got.get("aggregations", {}).get("rows")
    if count != len(artefact["links"]):
        failures += 1
        _log(f"  FAIL {namespace} holds {count} row(s), the artefact links "
             f"{len(artefact['links'])}")
    rows = request("POST", f"/v2/namespaces/{namespace}/query",
                   {"rank_by": ["id", "asc"], "top_k": sample,
                    "include_attributes": ["source_link"]},
                   region=region, key=key).get("rows", [])
    for row in rows:
        want = artefact["links"].get(row["id"])
        have = row.get("source_link") or ""
        if want != have:
            failures += 1
            _log(f"  FAIL row {row['id']}: source_link {have!r}, artefact says "
                 f"{want!r}")
    _log(f"namespace sample: {len(rows)} row(s) compared")
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
    """One `patch_rows` run over every id in the artefact (§17.6, D49 ruling 3):
    only `source_link` is written, vectors are untouched, and turbopuffer
    ignores an id the namespace does not hold.  The namespace is counted before
    and after — an unchanged count is the proof no row was created.

    Ids go up in sorted order, `BATCH_WORKERS` batches at a time, and the
    checkpoint advances to a count only after its whole group is confirmed —
    the export's resume story, reused (site_export.BATCH_WORKERS/_groups)."""
    from .site_export import BATCH_WORKERS, _groups, api_key, request

    artefact = load_artefact(artefact_path)
    artefact_hash = hashlib.sha256(
        _canonical(artefact).encode("utf-8")).hexdigest()
    links = artefact["links"]
    key = api_key()

    def _count() -> int:
        got = request("POST", f"/v2/namespaces/{namespace}/query",
                      {"aggregate_by": {"rows": ["Count", "id"]}},
                      region=region, key=key)
        return got.get("aggregations", {}).get("rows")

    before = _count()
    _log(f"{namespace}: {before} row(s); artefact links {len(links)} id(s)")
    if before != len(links) and not allow_count_mismatch:
        raise SourcePagesError(
            f"the namespace holds {before} row(s) but the artefact links "
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
        _log(f"resuming after {done} patched row(s)")
    todo = ids[done:]
    if limit is not None:
        todo = todo[:limit]

    schema = {"source_link": {"type": "string", "filterable": False}}

    def patch(batch: 'list[str]') -> None:
        request("POST", f"/v2/namespaces/{namespace}",
                {"patch_rows": [{"id": i, "source_link": links[i]}
                                for i in batch],
                 "schema": schema}, region=region, key=key)

    batches = _groups(todo, PATCH_ROWS)
    with concurrent.futures.ThreadPoolExecutor(BATCH_WORKERS) as pool:
        for group in _groups(batches, BATCH_WORKERS):
            list(pool.map(patch, group))
            done += sum(len(b) for b in group)
            tmp = checkpoint + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"namespace": namespace, "done": done,
                           "artefact_hash": artefact_hash}, f)
            os.replace(tmp, checkpoint)
            _log(f"  {done} row(s) patched")

    after = _count()
    if after != before:
        raise SourcePagesError(
            f"the namespace grew from {before} to {after} row(s) during the "
            f"patch — patch_rows must never create rows; inspect before "
            f"anything else touches it")
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

    mp = sub.add_parser("map", help="the file→page map and the resolved links "
                                    "(§17.3), beside the rendered tree and the "
                                    "authoritative registry")
    mp.add_argument("--scan", required=True, help="the corpus scan's output")
    mp.add_argument("--rendered", required=True, help="the rendered tree's root")
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
                      help="also compare a sample of this namespace's "
                           "source_link values (needs the API key)")
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
                            "the artefact's link count")
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
            run_map(scan_path=args.scan, rendered=args.rendered, out=args.out)
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
