"""The source-page upload pass's rules (SEMANTIC_SEARCH_SITE_PLAN.md §17,
D50-D53), tested on fixture trees — no cslh19, no database, no network
(§17.7's list).

What is left to the real runs — the corpus scan's census, the map over the
real registry and the real `data/theories.json`, the gate over the real
published tree, the patch — is what §17.7's acceptance clause measures
instead.
"""
import json
import os

import pytest

from Isabelle_Semantic_Embedding import site_source_pages as sp


# --- the path functions and D50's predicate ---------------------------------

def test_a_link_exists_iff_the_position_is_symbolic():
    assert sp.linkable("$AFP/Foo/Bar.thy")
    assert sp.linkable("~~/src/HOL/List.thy")
    assert not sp.linkable("/home/who/private.thy")


def test_the_auxiliary_page_is_a_pure_function_of_the_position():
    assert sp.aux_page("$AFP/E/u.ML") == "/source/_aux/AFP/E/u.ML.html"
    assert sp.aux_page("~~/src/Tools/misc.ML") \
        == "/source/_aux/ISABELLE_HOME/src/Tools/misc.ML.html"
    with pytest.raises(sp.SourcePagesError):
        sp.aux_page("/abs/path.ML")


def test_the_rendered_copy_and_the_published_page_agree_on_the_position():
    sym = sp.aux_symbolic("AFP/E/u.ML.html")
    assert sym == "$AFP/E/u.ML"
    assert sp.aux_page(sym) == "/source/_aux/AFP/E/u.ML.html"
    assert sp.aux_symbolic("ISABELLE_HOME/src/x.ML.html") == "~~/src/x.ML"
    assert sp.aux_symbolic("Something/else.html") is None


def test_a_reference_with_a_uri_scheme_is_site_external():
    """D50: the predicate reads the whole value, before any fragment split."""
    assert sp.is_external("https://en.wikipedia.org/wiki/Binary_heap#Building_a_heap")
    assert sp.is_external("http://www.mathworld.com")
    assert sp.is_external("mailto:someone@example.org")
    assert sp.is_external("//cdn.example.org/x.js")


def test_no_site_internal_shape_matches_the_external_predicate():
    """Sound by construction — `:` is illegal in every Isabelle path element —
    and the colon-bearing entity anchors live after `#`, where the anchored
    regex cannot reach."""
    assert not sp.is_external("A.B.html")
    assert not sp.is_external("../../HOL/HOL/List.html#Lattices.x")
    assert not sp.is_external("AOT.AOT_PLM.html#AOT_PLM.cqt:2[lambda]|method")
    assert not sp.is_external("#L3")
    assert not sp.is_external("isabelle.css")


# --- the shipped envelopes and the composer (§17.1, Q4) ----------------------

def _map_body(**kw):
    body = {"kind": "map", "format": sp.ARTEFACT_FORMAT,
            "files": [], "records": [], "file_page_map": {}, "residue": {},
            "no_evidence": [], "source_lines": {}, "classification": {
                "theory_pages": {}, "aux_pages": {}, "css": [], "fonts": [],
                "dropped": {}, "underived": [], "unclassified": [],
                "inventory": {}},
            "tree_fingerprint": "", "theories_sha256": "",
            "registry_fingerprint": {"entries": 0, "names_sha256": ""}}
    body.update(kw)
    return body


def test_the_envelope_survives_its_own_round_trip(tmp_path):
    path = str(tmp_path / "artefact.json")
    body = _map_body(files=["$AFP/E/A.thy"],
                     records=[["id1", 0, 3]],
                     file_page_map={"$AFP/E/A.thy": "/source/A.A.html"})
    digest = sp.write_artefact(path, body)
    got, got_digest = sp.load_artefact(path, "map", sp.ARTEFACT_FORMAT)
    assert got == body and got_digest == digest


def test_a_tampered_envelope_is_refused(tmp_path):
    """§17.1: no step ever reads "whichever table this machine happens to
    have" — a hand edit or a truncated copy must be loud."""
    path = str(tmp_path / "artefact.json")
    sp.write_artefact(path, _map_body())
    with open(path, encoding="utf-8") as f:
        stored = json.load(f)
    stored["body"]["file_page_map"]["x"] = "/source/edited.html"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stored, f)
    with pytest.raises(sp.SourcePagesError):
        sp.load_artefact(path, "map", sp.ARTEFACT_FORMAT)


def test_the_wrong_kind_or_format_is_refused(tmp_path):
    path = str(tmp_path / "artefact.json")
    sp.write_artefact(path, _map_body(kind="scan"))
    with pytest.raises(sp.SourcePagesError):
        sp.load_artefact(path, "map", sp.ARTEFACT_FORMAT)
    sp.write_artefact(path, _map_body(format=1))
    with pytest.raises(sp.SourcePagesError):
        sp.load_artefact(path, "map", sp.ARTEFACT_FORMAT)


def test_links_compose_from_the_map_and_the_absent_form_is_the_empty_string():
    """Q4: THE one place a link is built — `page#L<line>` for a mapped
    position, the empty string for no position and for residue alike."""
    body = _map_body(files=["$AFP/E/A.thy", "$AFP/E/gone.ML"],
                     records=[["id1", 0, 3], ["id2", -1, 0], ["id3", 1, 7]],
                     file_page_map={"$AFP/E/A.thy": "/source/A.A.html"},
                     residue={"$AFP/E/gone.ML": "no rendered auxiliary copy"})
    assert sp.source_links(body) == {"id1": "/source/A.A.html#L3",
                                     "id2": "", "id3": ""}


def test_duplicate_document_ids_stop_the_composition():
    body = _map_body(files=["$AFP/E/A.thy"],
                     records=[["id1", 0, 3], ["id1", 0, 4]],
                     file_page_map={"$AFP/E/A.thy": "/source/A.A.html"})
    with pytest.raises(sp.SourcePagesError):
        sp.source_links(body)


def test_needed_lines_derive_from_the_same_triples_the_links_compose_from():
    """Q4's second half: the marks the publisher injects and the lines the
    links point at are the same set by construction."""
    body = _map_body(files=["$AFP/E/A.thy"],
                     records=[["id1", 0, 3], ["id2", 0, 1], ["id3", 0, 3],
                              ["id4", -1, 0]],
                     file_page_map={"$AFP/E/A.thy": "/source/A.A.html"})
    assert sp.needed_lines_by_page(body) == {"/source/A.A.html": [1, 3]}


def test_a_map_body_whose_partition_is_broken_is_refused_at_load(tmp_path):
    path = str(tmp_path / "artefact.json")
    sp.write_artefact(path, _map_body(files=["$AFP/E/A.thy"]))   # in neither
    with pytest.raises(sp.SourcePagesError):
        sp.load_artefact(path, "map", sp.ARTEFACT_FORMAT)


def test_a_record_with_an_out_of_range_file_index_is_refused_at_load(tmp_path):
    path = str(tmp_path / "artefact.json")
    sp.write_artefact(path, _map_body(
        files=["$AFP/E/A.thy"], records=[["id1", 5, 3]],
        file_page_map={"$AFP/E/A.thy": "/source/A.A.html"}))
    with pytest.raises(sp.SourcePagesError):
        sp.load_artefact(path, "map", sp.ARTEFACT_FORMAT)


# --- D53's table (theories.json) ---------------------------------------------

_THEORIES = {
    "A.A": {"path": "./contrib/afp-2026-05-13/thys/E/A.thy", "deps": []},
    "A.B": {"path": "./contrib/afp-2026-05-13/thys/E/B.thy", "deps": []},
    "HOL.List": {"path": "./contrib/Isabelle2025-2/src/HOL/List.thy", "deps": []},
    # a distribution COMPONENT theory, not under src/ — the measured Naproche
    # shape that broke the old "/src/" root inference
    "Naproche.Build": {"path": "./contrib/Isabelle2025-2/contrib/naproche-1/Isabelle/Main/Build.thy",
                       "deps": []},
    "G": {"path": "./contrib/afp-2026-05-13/thys/G/G.thy", "deps": []},
    # the (global)-alias twin: same path under the qualified spelling
    "G.G": {"path": "./contrib/afp-2026-05-13/thys/G/G.thy", "deps": []},
}


def test_the_inversion_folds_the_global_alias_and_detects_the_prefixes():
    inverted, prefixes = sp.invert_theories(_THEORIES)
    assert inverted["./contrib/afp-2026-05-13/thys/G/G.thy"] == "G"
    assert "G.G" not in inverted.values()
    assert prefixes == {"$AFP/": "./contrib/afp-2026-05-13/thys/",
                        "~~/": "./contrib/Isabelle2025-2/"}


def test_two_theories_on_one_path_after_the_fold_stop_the_inversion():
    bad = dict(_THEORIES)
    bad["Other.A"] = {"path": "./contrib/afp-2026-05-13/thys/E/A.thy", "deps": []}
    with pytest.raises(sp.SourcePagesError):
        sp.invert_theories(bad)


def test_a_position_normalises_to_the_tables_own_spelling():
    _, prefixes = sp.invert_theories(_THEORIES)
    assert sp.normalize_position("$AFP/E/A.thy", prefixes) \
        == "./contrib/afp-2026-05-13/thys/E/A.thy"
    assert sp.normalize_position("~~/src/HOL/List.thy", prefixes) \
        == "./contrib/Isabelle2025-2/src/HOL/List.thy"


# --- D52's long-name derivation ----------------------------------------------

_REGISTRY_NAMES = {"A.A", "A.B", "HOL.List", "G", "HOLCF", "HOLCF.HOLCF",
                   "HOL-CSP", "HOL-CSP.HOL-CSP"}


def test_a_dotted_stem_is_the_long_name():
    pages, dropped = sp.derive_theory_pages(
        [("S1", "A.A", "Unsorted/S1/A.A.html")], _REGISTRY_NAMES)
    assert pages == {"A.A": "Unsorted/S1/A.A.html"} and not dropped


def test_a_dotless_stem_resolves_through_its_session_directory():
    """The renderer names a home-session page by the base name; the long name
    is the directory's session plus the stem (D52, 261 real pages)."""
    pages, _ = sp.derive_theory_pages(
        [("HOL", "List", "HOL/HOL/List.html")], _REGISTRY_NAMES)
    assert pages == {"HOL.List": "HOL/HOL/List.html"}


def test_a_global_theorys_bare_page_resolves_to_the_bare_name():
    """FOL.html inside an umbrella directory: `AFP-DEP1-0.FOL` is no registry
    name, the bare `FOL` is (the 17 global theories)."""
    pages, _ = sp.derive_theory_pages(
        [("AFP-DEP1-0", "G", "Unsorted/AFP-DEP1-0/G.html")], _REGISTRY_NAMES)
    assert pages == {"G": "Unsorted/AFP-DEP1-0/G.html"}


def test_a_page_resolving_to_no_registry_name_is_dropped_and_named():
    pages, dropped = sp.derive_theory_pages(
        [("Pure", "Sessions", "Pure/Pure/Sessions.html")], _REGISTRY_NAMES)
    assert not pages and dropped == ["Pure/Pure/Sessions.html"]


def test_two_pages_deriving_one_long_name_stop_the_derivation():
    with pytest.raises(sp.SourcePagesError):
        sp.derive_theory_pages(
            [("S1", "A.A", "Unsorted/S1/A.A.html"),
             ("S2", "A.A", "Unsorted/S2/A.A.html")], _REGISTRY_NAMES)


def test_the_twin_pages_derive_two_distinct_names():
    pages, _ = sp.derive_theory_pages(
        [("AFP-DEP1-13", "HOLCF", "Unsorted/AFP-DEP1-13/HOLCF.html"),
         ("AFP-ALL-2", "HOLCF.HOLCF", "Unsorted/AFP-ALL-2/HOLCF.HOLCF.html")],
        _REGISTRY_NAMES)
    assert set(pages) == {"HOLCF", "HOLCF.HOLCF"}


def test_page_for_name_prefers_the_qualified_twin_and_falls_back_to_bare():
    pages = {"HOLCF": "a", "HOLCF.HOLCF": "b", "HOL-CSP": "c", "A.A": "d"}
    assert sp.page_for_name("HOLCF", pages) == "HOLCF.HOLCF"
    assert sp.page_for_name("A.A", pages) == "A.A"
    # D52's amendment: an X.X registry name with no page of its own lands on
    # the bare page — HOL-CSP.HOL-CSP is the one such name today.
    assert sp.page_for_name("HOL-CSP.HOL-CSP", pages) == "HOL-CSP"
    assert sp.page_for_name("Ghost.Ghost2", pages) is None


# --- D53's resolver and its three staleness gates ----------------------------

def _resolver_inputs():
    inverted, prefixes = sp.invert_theories(_THEORIES)
    theory_pages = {"A.A": "Unsorted/S1/A.A.html",
                    "A.B": "Unsorted/S1/A.B.html",
                    "HOL.List": "HOL/HOL/List.html"}
    aux = {"$AFP/E/u.ML": ["Unsorted/S1/AFP/E/u.ML.html"]}
    return inverted, prefixes, theory_pages, aux


def _scan_body(files, declaring=None, records=None):
    return {"kind": "scan", "format": sp.SCAN_FORMAT, "files": files,
            "declaring_theory_hashes": declaring or {}, "records": records or []}


def test_the_resolver_is_one_table_lookup():
    inverted, prefixes, pages, aux = _resolver_inputs()
    fmap, residue, _noev = sp.build_file_page_map(
        _scan_body(["$AFP/E/A.thy", "~~/src/HOL/List.thy", "$AFP/E/u.ML"]),
        inverted, prefixes, {}, pages, aux)
    assert fmap == {"$AFP/E/A.thy": "/source/A.A.html",
                    "~~/src/HOL/List.thy": "/source/HOL.List.html",
                    "$AFP/E/u.ML": "/source/_aux/AFP/E/u.ML.html"}
    assert not residue


def test_a_file_the_table_misses_is_a_hard_error_not_residue():
    """D53 gate 1: coverage is 100% by construction, so one miss means the
    table is stale for this corpus generation."""
    inverted, prefixes, pages, aux = _resolver_inputs()
    with pytest.raises(sp.SourcePagesError):
        sp.build_file_page_map(_scan_body(["$AFP/E/Nowhere.thy"]),
                               inverted, prefixes, {}, pages, aux)


def test_a_table_name_contradicting_the_declaring_hashes_is_a_hard_error():
    """D53 gate 2: two independent evidence chains watch each other."""
    inverted, prefixes, pages, aux = _resolver_inputs()
    with pytest.raises(sp.SourcePagesError):
        sp.build_file_page_map(
            _scan_body(["$AFP/E/A.thy"],
                       declaring={"$AFP/E/A.thy": ["aa"]}),
            inverted, prefixes, {"aa": "Somewhere.Else"}, pages, aux)


def test_unresolvable_declaring_hashes_are_no_evidence_not_a_conflict():
    """A registry gap is absence of evidence: the file resolves normally and
    is reported, never failed on."""
    inverted, prefixes, pages, aux = _resolver_inputs()
    fmap, _res, noev = sp.build_file_page_map(
        _scan_body(["$AFP/E/A.thy"], declaring={"$AFP/E/A.thy": ["ff" * 16]}),
        inverted, prefixes, {}, pages, aux)
    assert fmap["$AFP/E/A.thy"] == "/source/A.A.html"
    assert noev == ["$AFP/E/A.thy"]


def test_agreeing_declaring_hashes_pass_the_cross_check():
    inverted, prefixes, pages, aux = _resolver_inputs()
    fmap, _res, _noev = sp.build_file_page_map(
        _scan_body(["$AFP/E/A.thy"], declaring={"$AFP/E/A.thy": ["aa"]}),
        inverted, prefixes, {"aa": "A.A"}, pages, aux)
    assert fmap["$AFP/E/A.thy"] == "/source/A.A.html"


def test_a_resolved_name_without_a_page_is_a_hard_error():
    """D53 gate 3: the table and the rendered tree are not the same
    generation."""
    inverted, prefixes, pages, aux = _resolver_inputs()
    del pages["HOL.List"]
    with pytest.raises(sp.SourcePagesError):
        sp.build_file_page_map(_scan_body(["~~/src/HOL/List.thy"]),
                               inverted, prefixes, {}, pages, aux)


def test_an_unrendered_auxiliary_file_is_residue_not_an_error():
    inverted, prefixes, pages, aux = _resolver_inputs()
    fmap, residue, _noev = sp.build_file_page_map(
        _scan_body(["$AFP/E/other.ML"]), inverted, prefixes, {}, pages, aux)
    assert not fmap and residue == {"$AFP/E/other.ML": "no rendered auxiliary copy"}


def test_two_files_on_one_page_stop_the_map():
    inverted, prefixes, pages, aux = _resolver_inputs()
    inverted["./contrib/afp-2026-05-13/thys/E2/A2.thy"] = "A.A"
    with pytest.raises(sp.SourcePagesError):
        sp.build_file_page_map(
            _scan_body(["$AFP/E/A.thy", "$AFP/E2/A2.thy"]),
            inverted, prefixes, {}, pages, aux)


# --- reference rewriting, D50 exemption, D51 strips (§17.4) -------------------

_RELOC = {"Unsorted/S1/A.B.html": "/source/A.B.html",
          "Unsorted/S1/isabelle.css": "/source/isabelle.css",
          "HOL/HOL/List.html": "/source/HOL.List.html",
          "Unsorted/S1/AFP/E/u.ML.html": "/source/_aux/AFP/E/u.ML.html",
          "fonts/TestFont.ttf": "/source/fonts/TestFont.ttf"}


def test_the_three_measured_link_shapes_rewrite_to_absolute_hrefs():
    page = ('<a href="A.B.html">same session</a>'
            '<a href="../../HOL/HOL/List.html#Lattices.x">cross session</a>'
            '<a href="AFP/E/u.ML.html#mldef">auxiliary</a>')
    out = sp.rewrite_html_refs(page, "Unsorted/S1", _RELOC,
                               "Unsorted/S1/A.A.html", sp.RefCounters())
    assert 'href="/source/A.B.html"' in out
    assert 'href="/source/HOL.List.html#Lattices.x"' in out
    assert 'href="/source/_aux/AFP/E/u.ML.html#mldef"' in out


def test_a_site_external_reference_is_emitted_byte_identically_and_counted():
    """D50: not split at `#`, not resolved, not looked up — and the counter is
    the standing alarm's second half."""
    page = ('<a href="https://en.wikipedia.org/wiki/Merge_sort#Analysis">w</a>'
            '<a href="http://a.org/x?v=1&amp;t=2">q</a>')
    counters = sp.RefCounters()
    out = sp.rewrite_html_refs(page, "Unsorted/S1", _RELOC,
                               "Unsorted/S1/A.A.html", counters)
    assert out == page
    assert counters.external == 2


def test_a_reference_the_map_cannot_name_is_a_hard_error():
    with pytest.raises(sp.SourcePagesError):
        sp.rewrite_html_refs('<a href="ghost.html">', "Unsorted/S1", _RELOC,
                             "Unsorted/S1/A.A.html", sp.RefCounters())


def test_displayed_source_that_says_href_is_not_a_reference():
    page = '<span>writeln ‹href="lost.html"›</span>'
    assert sp.rewrite_html_refs(page, "Unsorted/S1", _RELOC,
                                "Unsorted/S1/A.A.html",
                                sp.RefCounters()) == page


def test_a_bare_fragment_reference_stays_where_it_is():
    page = '<a href="#L3">same page</a>'
    assert sp.rewrite_html_refs(page, "Unsorted/S1", _RELOC,
                                "Unsorted/S1/A.A.html",
                                sp.RefCounters()) == page


def test_css_urls_rewrite_per_file_type_and_externals_are_exempt():
    css = ("@font-face { src: url('../../fonts/TestFont.ttf'); }"
           "@import url('https://cdn.example.org/x.css');")
    counters = sp.RefCounters()
    out = sp.rewrite_css_urls(css, "Unsorted/S1", _RELOC,
                              "Unsorted/S1/isabelle.css", counters)
    assert "url('/source/fonts/TestFont.ttf')" in out
    assert "url('https://cdn.example.org/x.css')" in out
    assert counters.external == 1


def test_a_dangling_input_anchor_is_stripped_text_kept_and_reported():
    """D51: the renderer emitted a link to a page it never wrote — by the
    SEALED inventory, not the live filesystem (Q3) — strip the anchor, keep
    the words, count each stripped anchor."""
    page = ('<a href="sat_data/x.grat.xz.html"><span>proof file</span></a>'
            ' and <a href="A.B.html">fine</a>'
            ' and <a href="sat_data/x.grat.xz.html">again</a>')
    counters = sp.RefCounters()
    out = sp.strip_dangling_anchors(page, "Unsorted/S1", _RELOC,
                                    "Unsorted/S1/A.A.html", set(_RELOC),
                                    counters)
    assert out == ('<span>proof file</span> and <a href="A.B.html">fine</a>'
                   ' and again')
    # the alarm counts ANCHORS: two anchors to one dead target count two
    assert counters.stripped == [("Unsorted/S1/A.A.html",
                                  "sat_data/x.grat.xz.html")] * 2


def test_a_target_present_in_the_sealed_inventory_is_not_stripped():
    """Broken-by-us is never papered over: the file exists in the input, so a
    missing relocation entry stays for the rewrite to refuse."""
    page = '<a href="present.html">p</a>'
    inventory = set(_RELOC) | {"Unsorted/S1/present.html"}
    counters = sp.RefCounters()
    out = sp.strip_dangling_anchors(page, "Unsorted/S1", _RELOC,
                                    "Unsorted/S1/A.A.html", inventory,
                                    counters)
    assert out == page and not counters.stripped
    with pytest.raises(sp.SourcePagesError):
        sp.rewrite_html_refs(out, "Unsorted/S1", _RELOC,
                             "Unsorted/S1/A.A.html", sp.RefCounters())


def test_a_dangling_src_is_not_stripped_but_refused_by_the_rewriter():
    """D51 rules anchors only: a dangling src falls through to the ordinary
    hard error, with the right diagnosis."""
    page = '<img src="gone.png"/>'
    counters = sp.RefCounters()
    out = sp.strip_dangling_anchors(page, "Unsorted/S1", _RELOC,
                                    "Unsorted/S1/A.A.html", set(_RELOC),
                                    counters)
    assert out == page and not counters.stripped
    with pytest.raises(sp.SourcePagesError):
        sp.rewrite_html_refs(out, "Unsorted/S1", _RELOC,
                             "Unsorted/S1/A.A.html", sp.RefCounters())


# --- the structural assertions and the injector (§17.4) -----------------------

def _page(pre: str) -> str:
    return f'<html><body><pre class="source">{pre}</pre></body></html>'


def test_the_structure_is_asserted_on_every_page_shape():
    sp.assert_page_structure(_page("one\ntwo"), "p")
    with pytest.raises(sp.SourcePagesError):
        sp.assert_page_structure(_page("one") + '<pre class="source">x</pre>', "p")
    with pytest.raises(sp.SourcePagesError):
        sp.assert_page_structure(
            '<html><body><pre class="source"><span\nclass="x">a</span></pre></body></html>', "p")
    with pytest.raises(sp.SourcePagesError):
        sp.assert_page_structure(_page('<a id="L7"></a>one'), "p")


def test_an_entity_anchor_starting_with_L_is_not_a_line_mark():
    """`id="L` alone matches 555 innocent pages; the test is `id="L<digits>"`
    and nothing looser."""
    sp.assert_page_structure(_page('<span id="List.append|const">one</span>'), "p")


def test_marks_land_on_the_first_the_middle_and_the_last_line():
    out = sp.inject_line_marks(_page("one\ntwo\nthree"), [1, 2, 3], "p", 3)
    assert '<a id="L1"></a>one' in out
    assert '<a id="L2"></a>two' in out
    assert '<a id="L3"></a>three' in out


def test_only_the_needed_lines_get_marks():
    out = sp.inject_line_marks(_page("one\ntwo\nthree"), [2], "p", 3)
    assert out.count('id="L') == 1 and '<a id="L2"></a>two' in out


def test_a_trailing_newline_at_eof_is_no_edge():
    out = sp.inject_line_marks(_page("one\ntwo\n"), [2], "p", 2)
    assert '<a id="L2"></a>two' in out


def test_a_needed_line_past_the_end_is_a_hard_error():
    with pytest.raises(sp.SourcePagesError):
        sp.inject_line_marks(_page("one\ntwo"), [3], "p", 2)


def test_a_page_showing_a_different_files_line_count_is_a_hard_error():
    """B3: the one check that catches a file mapped onto a page showing some
    other file's source — the window and the real file must agree ±1."""
    with pytest.raises(sp.SourcePagesError):
        sp.inject_line_marks(_page("one\ntwo\nthree\nfour\nfive"), [2], "p", 3)
    sp.inject_line_marks(_page("one\ntwo\nthree\nfour"), [2], "p", 3)  # ±1 ok


# --- the id-union merge (D49 ruling 6) ---------------------------------------

def test_identical_copies_merge_to_themselves():
    content = _page("one\ntwo")
    base, merged, conflicted = sp.merge_aux_copies("$AFP/E/u.ML",
                                                   [("a", content), ("b", content)])
    assert merged == content and not conflicted


def test_conflicting_copies_publish_the_id_union():
    a = _page('<a id="mldef"></a>one\ntwo')
    b = _page('<a id="mldef2"></a>one\ntwo')
    _base, merged, conflicted = sp.merge_aux_copies("$AFP/E/u.ML",
                                                    [("a", a), ("b", b)])
    assert conflicted
    line_one = merged.split("\n")[0]
    assert 'id="mldef"' in line_one and 'id="mldef2"' in line_one


def test_an_entity_anchor_element_present_in_one_copy_only_merges():
    """The amended tolerance's second measured shape (splitter.ML:490): the
    anchor is a whole element, and the span run splits differently — the
    TEXT is identical, so the copies merge and the id-union lands."""
    a = _page('<span>‹</span><span class="entity_def" id="HOL.split|attribute">'
              '<span>split</span></span><span>›</span>\ntwo')
    b = _page('<span>‹split›</span>\ntwo')
    _base, merged, conflicted = sp.merge_aux_copies("~~/src/Provers/splitter.ML",
                                                    [("a", a), ("b", b)])
    assert conflicted and 'id="HOL.split|attribute"' in merged


def test_differing_titles_merge_and_the_symbolic_title_wins():
    """The amended tolerance's first measured shape: the renderer names the
    file relative to the presenting session; the base is the copy whose
    title carries the symbolic path."""
    qualified = ('<html><head><title>File ‹$AFP/E/util.ML›</title></head>'
                 '<body><pre class="source">one</pre></body></html>')
    bare = ('<html><head><title>File ‹util.ML›</title></head>'
            '<body><pre class="source">one</pre></body></html>')
    base, merged, conflicted = sp.merge_aux_copies(
        "$AFP/E/util.ML", [("z_sorted_last", qualified), ("a_sorted_first", bare)])
    assert conflicted
    assert base == "z_sorted_last" and "‹$AFP/E/util.ML›" in merged


def test_copies_differing_in_text_stop_the_pass():
    with pytest.raises(sp.SourcePagesError):
        sp.merge_aux_copies("$AFP/E/u.ML",
                            [("a", _page("one\ntwo")), ("b", _page("eins\ntwo"))])


def test_copies_of_different_lengths_stop_the_pass():
    with pytest.raises(sp.SourcePagesError):
        sp.merge_aux_copies("$AFP/E/u.ML",
                            [("a", _page("one\ntwo")), ("b", _page("one"))])


# --- the index (D49 ruling 5, copy approved 2026-08-23) -----------------------

def test_the_index_carries_the_approved_copy_and_groups_by_session_prefix():
    out = sp.generate_index(["B.Z", "B.A", "A.M", "HOL"])
    assert "<title>Isabelle source pages</title>" in out
    assert "Isabelle2025-2 and AFP 2026-05-13" in out
    assert out.index("<h2>A</h2>") < out.index("<h2>B</h2>") < out.index("<h2>HOL</h2>")
    assert out.index('href="/source/B.A.html"') < out.index('href="/source/B.Z.html"')
    for name in ("B.Z", "B.A", "A.M", "HOL"):
        assert f'href="/source/{name}.html"' in out
    assert 'href="/source/isabelle.css"' in out


# --- the pass and the gate, end to end on a fixture tree ----------------------

_CSS = ("@font-face {{ src: url('{}fonts/TestFont.ttf'); }}\n"
        "@import url('https://cdn.example.org/x.css');\n"
        ".source {{ color: black; }}")

_REG_HASH = "aa" * 16      # the stub registry's one declaring-theory hash


def _theory_page(title, pre):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<html>\n'
            '<head><link rel="stylesheet" type="text/css" href="isabelle.css"/>\n'
            f"<title>{title}</title>\n</head>\n<body>\n"
            f'<pre class="source">{pre}</pre>\n</body>\n</html>\n')


def _fixture(tmp_path, monkeypatch):
    """A repo root (theories.json + source files), a rendered tree with a
    base-named distribution page, an external link, a dangling link and a
    conflicting aux pair, and the registry stub — the whole §17 world in
    miniature."""
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    (repo / "data" / "theories.json").write_text(json.dumps({
        "A.A": {"path": "./contrib/afp-2026-05-13/thys/E/A.thy", "deps": []},
        "A.B": {"path": "./contrib/afp-2026-05-13/thys/E/B.thy", "deps": []},
        "HOL.List": {"path": "./contrib/Isabelle2025-2/src/HOL/List.thy",
                     "deps": []},
        "Nap.Build": {"path": "./contrib/Isabelle2025-2/contrib/nap-1/Build.thy",
                      "deps": []},
    }), encoding="utf-8")
    for rel, lines in (("contrib/afp-2026-05-13/thys/E/A.thy", 3),
                       ("contrib/afp-2026-05-13/thys/E/B.thy", 1),
                       ("contrib/Isabelle2025-2/src/HOL/List.thy", 4),
                       ("contrib/Isabelle2025-2/contrib/nap-1/Build.thy", 1),
                       ("contrib/afp-2026-05-13/thys/E/u.ML", 2)):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(f"line{i}" for i in range(1, lines + 1)) + "\n",
                      encoding="utf-8")

    rendered = tmp_path / "rendered"
    files = {
        "index.html": "<html/>",
        "isabelle.css": _CSS.format(""),
        "isabelle.gif": "GIF",

        "Unsorted/index.html": "<html/>",
        "Unsorted/S1/index.html": '<a href="session_graph.pdf">g</a>',
        "Unsorted/S1/session_graph.pdf": "PDF",
        "Unsorted/S1/isabelle.css": _CSS.format("../../"),
        "Unsorted/S1/.browser_info/build_uuid": "uuid",
        "Unsorted/S1/A.A.html": _theory_page("Theory A.A",
            '<span>lemma one</span> <a href="A.B.html#A.B.foo|fact">foo</a>\n'
            '<a href="../../HOL/HOL/List.html#Lattices.x">x</a> '
            '<a href="AFP/E/u.ML.html#mldef">u</a>\n'
            '<a href="https://en.wikipedia.org/wiki/Merge_sort#Analysis">w</a> '
            '<a href="sat_data/ghost.grat.xz.html">dangling</a>'),
        "Unsorted/S1/A.B.html": _theory_page("Theory A.B",
            '<span id="A.B.foo|fact">foo</span>'),
        "Unsorted/S1/AFP/E/u.ML.html": _theory_page("File u.ML",
            'line one\n<a id="mldef"></a>line two'),
        "Unsorted/S1/AFP/E/isabelle.css": _CSS.format("../../../../"),
        "Unsorted/S2/AFP/E/u.ML.html": _theory_page("File u.ML",
            'line one\n<a id="mldef2"></a>line two'),
        "HOL/index.html": "<html/>",
        "HOL/HOL/isabelle.css": _CSS.format("../../"),
        "HOL/HOL/List.html": _theory_page("Theory List",
            '<span id="Lattices.x">x</span>\ntwo\nthree\nfour'),
    }
    for rel, content in files.items():
        path = rendered / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    # a REAL binary font: opening it as UTF-8 must never happen (the review's
    # third blocker was the gate decoding the 13 real .ttf files)
    (rendered / "fonts").mkdir(exist_ok=True)
    (rendered / "fonts" / "TestFont.ttf").write_bytes(b"\x00\x01\x80\x99FONT\xff")

    from Isabelle_Semantic_Embedding import site_export
    monkeypatch.setattr(site_export, "theory_registry",
                        lambda: {bytes.fromhex(_REG_HASH): "A.A",
                                 bytes.fromhex("bb" * 16): "A.B",
                                 bytes.fromhex("cc" * 16): "HOL.List"})

    scan_path = str(tmp_path / "scan.json")
    sp.write_artefact(scan_path, {
        "kind": "scan", "format": sp.SCAN_FORMAT,
        "files": ["$AFP/E/A.thy", "$AFP/E/u.ML", "~~/src/HOL/List.thy"],
        "declaring_theory_hashes": {"$AFP/E/A.thy": [_REG_HASH]},
        "records": sorted([["id1", 0, 1], ["id2", 0, 3], ["id3", 1, 2],
                           ["id4", -1, 0], ["id5", 2, 2]]),
    })
    return repo, rendered, scan_path


def _run_map(tmp_path, repo, rendered, scan_path):
    artefact = str(tmp_path / "artefact.json")
    sp.run_map(scan_path=scan_path, rendered=str(rendered),
               theories_path=str(repo / "data" / "theories.json"),
               out=artefact)
    return artefact


def test_map_publish_and_gate_pass_end_to_end(tmp_path, monkeypatch, capsys):
    repo, rendered, scan_path = _fixture(tmp_path, monkeypatch)
    artefact = _run_map(tmp_path, repo, rendered, scan_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=str(rendered), artefact_path=artefact, out=out)

    def read(rel):
        with open(os.path.join(out, rel), encoding="utf-8") as f:
            return f.read()

    a = read("A.A.html")
    assert '<a id="L1"></a>' in a and '<a id="L3"></a>' in a
    assert 'href="/source/A.B.html#A.B.foo|fact"' in a
    assert 'href="/source/HOL.List.html#Lattices.x"' in a
    assert 'href="https://en.wikipedia.org/wiki/Merge_sort#Analysis"' in a
    assert "ghost.grat.xz.html" not in a
    assert "dangling</pre>" in a            # the anchor's text survives it
    lst = read("HOL.List.html")               # the base-named page, republished
    assert '<a id="L2"></a>' in lst           # under its derived long name
    u = read("_aux/AFP/E/u.ML.html")
    assert '<a id="L2"></a>' in u
    assert 'id="mldef"' in u and 'id="mldef2"' in u
    assert read("isabelle.css").count("url('/source/fonts/TestFont.ttf')") == 1
    idx = read("index.html")
    assert "Isabelle source pages" in idx and 'href="/source/A.B.html"' in idx
    report = json.loads(read("publish-report.json"))
    assert report["marks injected"] == 4
    # 1 wiki link + 1 css @import — the css external is counted ONCE although
    # the fixture renders four stylesheet copies (the ×335 defect's regression)
    assert report["external references exempted (D50)"] == 2
    assert report["dangling anchors stripped (D51)"] == 1
    assert report["auxiliary conflicts merged"] == 1

    assert sp.run_gate(published=out, artefact_path=artefact, namespace=None,
                       region="", sample=0) == 0


def test_publish_refuses_a_tree_that_moved_since_the_map(tmp_path, monkeypatch):
    repo, rendered, scan_path = _fixture(tmp_path, monkeypatch)
    artefact = _run_map(tmp_path, repo, rendered, scan_path)
    with open(rendered / "Unsorted/S1/A.B.html", "a", encoding="utf-8") as f:
        f.write("<!-- re-rendered -->")
    with pytest.raises(sp.SourcePagesError):
        sp.run_publish(rendered=str(rendered), artefact_path=artefact,
                       out=str(tmp_path / "published"))


def test_publish_never_writes_into_a_directory_it_was_handed(tmp_path, monkeypatch):
    repo, rendered, scan_path = _fixture(tmp_path, monkeypatch)
    artefact = _run_map(tmp_path, repo, rendered, scan_path)
    out = tmp_path / "published"
    out.mkdir()
    with pytest.raises(sp.SourcePagesError):
        sp.run_publish(rendered=str(rendered), artefact_path=artefact,
                       out=str(out))


def test_a_failed_publish_removes_its_own_staging(tmp_path, monkeypatch):
    repo, rendered, scan_path = _fixture(tmp_path, monkeypatch)
    artefact = _run_map(tmp_path, repo, rendered, scan_path)
    # Break line fidelity after the map: List.html loses a source line.
    lst = rendered / "HOL/HOL/List.html"
    content = lst.read_text(encoding="utf-8").replace("\ntwo\nthree", "\nthree")
    lst.write_text(content, encoding="utf-8")
    out = str(tmp_path / "published")
    with pytest.raises(sp.SourcePagesError):
        sp.run_publish(rendered=str(rendered), artefact_path=artefact, out=out)
    assert not os.path.exists(out + ".building")
    assert not os.path.exists(out)


def test_the_gate_counts_a_missing_mark(tmp_path, monkeypatch):
    repo, rendered, scan_path = _fixture(tmp_path, monkeypatch)
    artefact = _run_map(tmp_path, repo, rendered, scan_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=str(rendered), artefact_path=artefact, out=out)
    page = os.path.join(out, "A.A.html")
    with open(page, encoding="utf-8") as f:
        content = f.read()
    with open(page, "w", encoding="utf-8") as f:
        f.write(content.replace('<a id="L3"></a>', ""))
    assert sp.run_gate(published=out, artefact_path=artefact, namespace=None,
                       region="", sample=0) >= 1


def test_an_inherited_fragment_miss_is_reported_not_failed(tmp_path, monkeypatch,
                                                           capsys):
    """D54: every fragment is still checked, but one inherited from the
    rendered pages that misses is counted — the reader lands at the top of
    the right page — while the pipeline's own fragments stay zero-miss."""
    repo, rendered, scan_path = _fixture(tmp_path, monkeypatch)
    artefact = _run_map(tmp_path, repo, rendered, scan_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=str(rendered), artefact_path=artefact, out=out)
    target = os.path.join(out, "A.B.html")
    with open(target, encoding="utf-8") as f:
        content = f.read()
    with open(target, "w", encoding="utf-8") as f:
        f.write(content.replace('id="A.B.foo|fact"', 'id="renamed"'))
    assert sp.run_gate(published=out, artefact_path=artefact, namespace=None,
                       region="", sample=0) == 0
    assert "reported, not failed (D54): 1 inherited fragment(s)" \
        in capsys.readouterr().out


def test_the_gate_ignores_external_references_and_counts_them(tmp_path, monkeypatch,
                                                              capsys):
    repo, rendered, scan_path = _fixture(tmp_path, monkeypatch)
    artefact = _run_map(tmp_path, repo, rendered, scan_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=str(rendered), artefact_path=artefact, out=out)
    assert sp.run_gate(published=out, artefact_path=artefact, namespace=None,
                       region="", sample=0) == 0
    logged = capsys.readouterr().out
    assert "2 site-external exempted (D50)" in logged   # wiki + css @import


def test_the_gate_refuses_a_tree_built_from_another_artefact(tmp_path, monkeypatch):
    """The identity chain: publish stamps the artefact hash into the report,
    and the gate refuses a (tree, artefact) pair that never belonged
    together."""
    repo, rendered, scan_path = _fixture(tmp_path, monkeypatch)
    artefact = _run_map(tmp_path, repo, rendered, scan_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=str(rendered), artefact_path=artefact, out=out)
    body, _ = sp.load_artefact(artefact, "map", sp.ARTEFACT_FORMAT)
    body["no_evidence"] = ["tweown_evidence"]
    other = str(tmp_path / "artefact-b.json")
    sp.write_artefact(other, body)
    assert sp.run_gate(published=out, artefact_path=other, namespace=None,
                       region="", sample=0) >= 1


def test_the_gate_fails_when_the_alarm_counters_disagree(tmp_path, monkeypatch):
    """The report's D50 number and the gate's own count must agree, or the
    alarm was never comparable."""
    repo, rendered, scan_path = _fixture(tmp_path, monkeypatch)
    artefact = _run_map(tmp_path, repo, rendered, scan_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=str(rendered), artefact_path=artefact, out=out)
    report_path = os.path.join(out, "publish-report.json")
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    report["external references exempted (D50)"] += 5
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f)
    assert sp.run_gate(published=out, artefact_path=artefact, namespace=None,
                       region="", sample=0) >= 1


def test_the_gate_misses_no_promised_page(tmp_path, monkeypatch):
    """The generated index is the one page nothing references — a publish
    that lost it must not gate green."""
    repo, rendered, scan_path = _fixture(tmp_path, monkeypatch)
    artefact = _run_map(tmp_path, repo, rendered, scan_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=str(rendered), artefact_path=artefact, out=out)
    os.remove(os.path.join(out, "index.html"))
    assert sp.run_gate(published=out, artefact_path=artefact, namespace=None,
                       region="", sample=0) >= 1


def test_a_fragment_into_a_binary_target_reports_instead_of_crashing(tmp_path,
                                                                     monkeypatch,
                                                                     capsys):
    """The review's third blocker, inverted: the gate never opens a
    fragment-less binary target, and a fragment INTO one is a failure, not a
    UnicodeDecodeError traceback."""
    repo, rendered, scan_path = _fixture(tmp_path, monkeypatch)
    artefact = _run_map(tmp_path, repo, rendered, scan_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=str(rendered), artefact_path=artefact, out=out)
    page = os.path.join(out, "A.B.html")
    with open(page, encoding="utf-8") as f:
        content = f.read()
    with open(page, "w", encoding="utf-8") as f:
        f.write(content.replace(
            "</body>", '<a href="/source/fonts/TestFont.ttf#x">f</a></body>'))
    # an INHERITED fragment into a binary target: never opened as UTF-8, and
    # under D54 the miss is counted, not failed — no crash either way
    assert sp.run_gate(published=out, artefact_path=artefact, namespace=None,
                       region="", sample=0) == 0
    assert "reported, not failed (D54)" in capsys.readouterr().out


# --- the patch (§17.6), with a stubbed API ------------------------------------

def _patch_world(tmp_path, rows_in_namespace):
    artefact = str(tmp_path / "artefact.json")
    body = _map_body(
        files=["$AFP/E/A.thy"],
        records=sorted([[f"id{i}", 0, i + 1] for i in range(6)]),
        file_page_map={"$AFP/E/A.thy": "/source/A.A.html"},
        source_lines={"$AFP/E/A.thy": 99})
    sp.write_artefact(artefact, body)
    calls = {"patched": [], "counts": 0}

    def fake_request(method, path, payload=None, *, region, key, attempts=6):
        if path.endswith("/query"):
            calls["counts"] += 1
            return {"aggregations": {"rows": rows_in_namespace}}
        assert set(payload) == {"patch_rows", "schema"}
        calls["patched"].extend(r["id"] for r in payload["patch_rows"])
        return {"status": "OK"}

    return artefact, calls, fake_request


def test_the_patch_writes_every_id_once_and_pins_the_artefact(tmp_path, monkeypatch):
    artefact, calls, fake_request = _patch_world(tmp_path, 6)
    from Isabelle_Semantic_Embedding import site_export
    monkeypatch.setattr(site_export, "request", fake_request)
    monkeypatch.setattr(site_export, "api_key", lambda: "k")
    checkpoint = str(tmp_path / "cp.json")
    sp.run_patch(artefact_path=artefact, namespace="ns", region="r",
                 checkpoint=checkpoint, limit=None, allow_count_mismatch=False)
    assert sorted(calls["patched"]) == [f"id{i}" for i in range(6)]
    with open(checkpoint, encoding="utf-8") as f:
        state = json.load(f)
    assert state["done"] == 6 and state["namespace"] == "ns"
    assert state["artefact_hash"]


def test_a_count_mismatch_is_refused_without_the_explicit_flag(tmp_path, monkeypatch):
    artefact, _calls, fake_request = _patch_world(tmp_path, 5)
    from Isabelle_Semantic_Embedding import site_export
    monkeypatch.setattr(site_export, "request", fake_request)
    monkeypatch.setattr(site_export, "api_key", lambda: "k")
    with pytest.raises(sp.SourcePagesError):
        sp.run_patch(artefact_path=artefact, namespace="ns", region="r",
                     checkpoint=str(tmp_path / "cp.json"), limit=None,
                     allow_count_mismatch=False)


def test_a_checkpoint_for_another_namespace_or_artefact_is_refused(tmp_path,
                                                                   monkeypatch):
    artefact, _calls, fake_request = _patch_world(tmp_path, 6)
    from Isabelle_Semantic_Embedding import site_export
    monkeypatch.setattr(site_export, "request", fake_request)
    monkeypatch.setattr(site_export, "api_key", lambda: "k")
    checkpoint = str(tmp_path / "cp.json")
    with open(checkpoint, "w", encoding="utf-8") as f:
        json.dump({"namespace": "other", "done": 3, "artefact_hash": "x"}, f)
    with pytest.raises(sp.SourcePagesError):
        sp.run_patch(artefact_path=artefact, namespace="ns", region="r",
                     checkpoint=checkpoint, limit=None,
                     allow_count_mismatch=False)
    with open(checkpoint, "w", encoding="utf-8") as f:
        json.dump({"namespace": "ns", "done": 3, "artefact_hash": "stale"}, f)
    with pytest.raises(sp.SourcePagesError):
        sp.run_patch(artefact_path=artefact, namespace="ns", region="r",
                     checkpoint=checkpoint, limit=None,
                     allow_count_mismatch=False)


def test_a_resume_patches_only_the_remaining_ids(tmp_path, monkeypatch):
    artefact, calls, fake_request = _patch_world(tmp_path, 6)
    from Isabelle_Semantic_Embedding import site_export
    monkeypatch.setattr(site_export, "request", fake_request)
    monkeypatch.setattr(site_export, "api_key", lambda: "k")
    _body, digest = sp.load_artefact(artefact, "map", sp.ARTEFACT_FORMAT)
    checkpoint = str(tmp_path / "cp.json")
    with open(checkpoint, "w", encoding="utf-8") as f:
        json.dump({"namespace": "ns", "done": 4, "artefact_hash": digest}, f)
    sp.run_patch(artefact_path=artefact, namespace="ns", region="r",
                 checkpoint=checkpoint, limit=None, allow_count_mismatch=False)
    assert sorted(calls["patched"]) == ["id4", "id5"]


def test_a_completed_patch_rerun_does_nothing_and_says_so(tmp_path, monkeypatch,
                                                          capsys):
    artefact, calls, fake_request = _patch_world(tmp_path, 6)
    from Isabelle_Semantic_Embedding import site_export
    monkeypatch.setattr(site_export, "request", fake_request)
    monkeypatch.setattr(site_export, "api_key", lambda: "k")
    _body, digest = sp.load_artefact(artefact, "map", sp.ARTEFACT_FORMAT)
    checkpoint = str(tmp_path / "cp.json")
    with open(checkpoint, "w", encoding="utf-8") as f:
        json.dump({"namespace": "ns", "done": 6, "artefact_hash": digest}, f)
    sp.run_patch(artefact_path=artefact, namespace="ns", region="r",
                 checkpoint=checkpoint, limit=None, allow_count_mismatch=False)
    assert not calls["patched"]
    assert "nothing to do" in capsys.readouterr().out


def test_a_non_integer_count_refuses_the_patch_even_with_the_flag(tmp_path,
                                                                  monkeypatch):
    # a None count silently satisfied --allow-count-mismatch once; the guard
    # must prove nothing from missing evidence
    artefact, calls, fake_request = _patch_world(tmp_path, None)
    from Isabelle_Semantic_Embedding import site_export
    monkeypatch.setattr(site_export, "request", fake_request)
    monkeypatch.setattr(site_export, "api_key", lambda: "k")
    with pytest.raises(sp.SourcePagesError, match="not an\\s+integer"):
        sp.run_patch(artefact_path=artefact, namespace="ns", region="r",
                     checkpoint=str(tmp_path / "cp.json"), limit=None,
                     allow_count_mismatch=True)
    assert not calls["patched"]


def test_an_unwritable_checkpoint_fails_before_any_row_is_patched(tmp_path,
                                                                  monkeypatch):
    artefact, calls, fake_request = _patch_world(tmp_path, 6)
    from Isabelle_Semantic_Embedding import site_export
    monkeypatch.setattr(site_export, "request", fake_request)
    monkeypatch.setattr(site_export, "api_key", lambda: "k")
    with pytest.raises(OSError):
        sp.run_patch(artefact_path=artefact, namespace="ns", region="r",
                     checkpoint=str(tmp_path / "no_such_dir" / "cp.json"),
                     limit=None, allow_count_mismatch=False)
    assert not calls["patched"]


# --- the namespace sample (stubbed) -------------------------------------------

def test_the_namespace_sample_is_stratified_and_fails_on_short_return(monkeypatch):
    links = {f"id{i:02d}": f"/source/P.html#L{i}" for i in range(40)}

    def fake_request(method, path, payload=None, *, region, key, attempts=6):
        if "aggregate_by" in (payload or {}):
            return {"aggregations": {"rows": len(links)}}
        chosen = payload["filters"][2]
        assert len(chosen) <= 4
        ids = sorted(links)
        assert chosen != ids[:len(chosen)], "an ascending prefix is exactly " \
            "the slice a half-finished patch wrote first"
        return {"rows": [{"id": i, "source_link": links[i]} for i in chosen[:-1]]}

    from Isabelle_Semantic_Embedding import site_export
    monkeypatch.setattr(site_export, "request", fake_request)
    monkeypatch.setattr(site_export, "api_key", lambda: "k")
    failures = sp._gate_namespace_sample(links, "ns", "r", sample=4)
    assert failures == 1          # the short return, and nothing else


def test_the_namespace_sample_pins_both_endpoints(monkeypatch):
    links = {f"id{i:02d}": f"/source/P.html#L{i}" for i in range(40)}
    seen = {}

    def fake_request(method, path, payload=None, *, region, key, attempts=6):
        if "aggregate_by" in (payload or {}):
            return {"aggregations": {"rows": len(links)}}
        seen["chosen"] = payload["filters"][2]
        return {"rows": [{"id": i, "source_link": links[i]}
                         for i in seen["chosen"]]}

    from Isabelle_Semantic_Embedding import site_export
    monkeypatch.setattr(site_export, "request", fake_request)
    monkeypatch.setattr(site_export, "api_key", lambda: "k")
    assert sp._gate_namespace_sample(links, "ns", "r", sample=4) == 0
    ids = sorted(links)
    assert seen["chosen"][0] == ids[0] and seen["chosen"][-1] == ids[-1], \
        "a sample that skips an endpoint leaves a blind window there"
    assert len(seen["chosen"]) == 4
    with pytest.raises(sp.SourcePagesError):
        sp._gate_namespace_sample(links, "ns", "r", sample=1)
