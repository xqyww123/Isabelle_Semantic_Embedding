"""The source-page upload pass's rules (SEMANTIC_SEARCH_SITE_PLAN.md §17), tested
on fixture pages — no cslh19, no database, no network (§17.7's list).

What is left to the real runs — the corpus scan's census, the map over the real
registry, the gate over the real published tree, the patch — is what §17.7's
acceptance clause measures instead.
"""
import json
import os

import pytest

from Isabelle_Semantic_Embedding import site_source_pages as sp


# --- the path functions (§17.2) ---------------------------------------------

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
    """`aux_symbolic` reads a rendered copy's path, `aux_page` writes the
    published one; a position must survive the round trip."""
    sym = sp.aux_symbolic("AFP/E/u.ML.html")
    assert sym == "$AFP/E/u.ML"
    assert sp.aux_page(sym) == "/source/_aux/AFP/E/u.ML.html"
    assert sp.aux_symbolic("ISABELLE_HOME/src/x.ML.html") == "~~/src/x.ML"
    assert sp.aux_symbolic("Something/else.html") is None


# --- the artefact (§17.1) ----------------------------------------------------

def _body(**kw):
    body = {"format": sp.ARTEFACT_FORMAT, "registry_entries": 1,
            "file_page_map": {}, "residue": {}, "needed_lines": {}, "links": {}}
    body.update(kw)
    return body


def test_the_artefact_survives_its_own_round_trip(tmp_path):
    path = str(tmp_path / "artefact.json")
    body = _body(links={"id1": "/source/A.html#L3"})
    sp.write_artefact(path, body)
    assert sp.load_artefact(path) == body


def test_a_tampered_artefact_is_refused(tmp_path):
    """§17.1: no step ever reads "whichever table this machine happens to have"
    — a hand edit or a truncated copy must be loud."""
    path = str(tmp_path / "artefact.json")
    sp.write_artefact(path, _body())
    with open(path, encoding="utf-8") as f:
        stored = json.load(f)
    stored["body"]["links"]["id1"] = "/source/edited.html#L1"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stored, f)
    with pytest.raises(sp.SourcePagesError):
        sp.load_artefact(path)


def test_an_artefact_of_another_format_is_refused(tmp_path):
    path = str(tmp_path / "artefact.json")
    sp.write_artefact(path, _body(format=999))
    with pytest.raises(sp.SourcePagesError):
        sp.load_artefact(path)


# --- the resolver (§17.3) ----------------------------------------------------

def _scan(files, declaring=None, needed=None, records=None):
    return {"format": sp.SCAN_FORMAT, "files": files,
            "needed_lines": needed or {},
            "declaring_theory_hashes": declaring or {},
            "records": records or []}


_PAGES = {"A.A": "Unsorted/S1/A.A.html", "X.Other": "Unsorted/S1/X.Other.html"}


def test_step_1_the_declaring_theory_is_exact_and_beats_the_stem():
    fmap, residue, how = sp.build_file_page_map(
        _scan(["$AFP/E/A.thy"], declaring={"$AFP/E/A.thy": ["aa"]}),
        _PAGES, {}, {"aa": "X.Other"})
    assert fmap == {"$AFP/E/A.thy": "/source/X.Other.html"} and not residue
    assert how == {"declaring theory": 1}


def test_step_1_a_multi_theory_file_is_settled_by_the_file_stem():
    """The two known multi-theory files: records of several theories in one
    file, and the theory named like the file is the one whose page shows it."""
    fmap, _, _ = sp.build_file_page_map(
        _scan(["$AFP/E/A.thy"], declaring={"$AFP/E/A.thy": ["aa", "bb"]}),
        _PAGES, {}, {"aa": "X.Other", "bb": "A.A"})
    assert fmap == {"$AFP/E/A.thy": "/source/A.A.html"}


def test_step_1_ambiguity_the_stem_cannot_settle_is_a_hard_error():
    """A silent pick would link the file to a page showing some other file's
    source — the first of §17.7's two resolver hard errors."""
    with pytest.raises(sp.SourcePagesError):
        sp.build_file_page_map(
            _scan(["$AFP/E/Z.thy"], declaring={"$AFP/E/Z.thy": ["aa", "bb"]}),
            _PAGES, {}, {"aa": "X.Other", "bb": "A.A"})


def test_step_2_an_exact_whole_name_hit_beats_base_name_candidates():
    """The bare/qualified twins: the stem `HOLCF` is itself a registry name, so
    it wins over `HOLCF.HOLCF` — and the page choice then prefers the
    session-qualified twin (both pages render the same file)."""
    pages = {"HOLCF": "Unsorted/S1/HOLCF.html",
             "HOLCF.HOLCF": "Unsorted/S2/HOLCF.HOLCF.html"}
    fmap, _, how = sp.build_file_page_map(
        _scan(["~~/src/HOL/HOLCF/HOLCF.thy"]), pages, {},
        {"01": "HOLCF", "02": "HOLCF.HOLCF"})
    assert fmap == {"~~/src/HOL/HOLCF/HOLCF.thy": "/source/HOLCF.HOLCF.html"}
    assert how == {"stem, whole name": 1}


def test_without_a_qualified_twin_the_bare_page_serves():
    pages = {"HOLCF": "Unsorted/S1/HOLCF.html"}
    fmap, _, _ = sp.build_file_page_map(
        _scan(["~~/src/HOL/HOLCF/HOLCF.thy"]), pages, {}, {"01": "HOLCF"})
    assert fmap == {"~~/src/HOL/HOLCF/HOLCF.thy": "/source/HOLCF.html"}


def test_step_2_a_single_base_name_candidate_resolves():
    fmap, _, how = sp.build_file_page_map(
        _scan(["$AFP/S/B.thy"]), {"S.B": "Unsorted/S1/S.B.html"}, {},
        {"01": "S.B"})
    assert fmap == {"$AFP/S/B.thy": "/source/S.B.html"}
    assert how == {"stem, base name": 1}


def test_step_2_never_guesses_between_theories_sharing_a_base_name():
    pages = {"S.B": "Unsorted/S1/S.B.html", "T.B": "Unsorted/S2/T.B.html"}
    _, residue, _ = sp.build_file_page_map(
        _scan(["$AFP/S/B.thy"]), pages, {}, {"01": "S.B", "02": "T.B"})
    assert list(residue) == ["$AFP/S/B.thy"]


def test_a_file_no_step_resolves_is_residue_not_an_error():
    """§17.3 step 3: the rows' links stay empty and the gate reports the
    count — D42's absent form covers the cards."""
    _, residue, _ = sp.build_file_page_map(
        _scan(["$AFP/S/Nowhere.thy"]), _PAGES, {}, {})
    assert list(residue) == ["$AFP/S/Nowhere.thy"]


def test_an_unrendered_auxiliary_file_is_residue():
    _, residue, _ = sp.build_file_page_map(
        _scan(["$AFP/E/u.ML"]), {}, {}, {})
    assert residue == {"$AFP/E/u.ML": "no rendered auxiliary copy"}


def test_two_files_on_one_page_stop_the_map():
    """The collision guard — the second of §17.7's resolver hard errors: two
    files' line numbering fused into one mark space."""
    with pytest.raises(sp.SourcePagesError):
        sp.build_file_page_map(
            _scan(["$AFP/E/A.thy", "$AFP/F/A.thy"],
                  declaring={"$AFP/E/A.thy": ["aa"], "$AFP/F/A.thy": ["aa"]}),
            _PAGES, {}, {"aa": "A.A"})


def test_every_record_gets_a_link_and_the_absent_form_is_the_empty_string():
    scan = _scan(["$AFP/E/A.thy", "$AFP/E/gone.thy"],
                 records=[["id1", 0, 3], ["id2", -1, 0], ["id3", 1, 7]])
    links, linked = sp.resolve_links(
        scan, {"$AFP/E/A.thy": "/source/A.A.html"},
        {"$AFP/E/gone.thy": "why"})
    assert links == {"id1": "/source/A.A.html#L3", "id2": "", "id3": ""}
    assert linked == 1


def test_duplicate_document_ids_stop_the_link_resolution():
    scan = _scan(["$AFP/E/A.thy"], records=[["id1", 0, 3], ["id1", 0, 4]])
    with pytest.raises(sp.SourcePagesError):
        sp.resolve_links(scan, {"$AFP/E/A.thy": "/source/A.A.html"}, {})


# --- reference rewriting (§17.4) --------------------------------------------

_RELOC = {"Unsorted/S1/A.B.html": "/source/A.B.html",
          "Unsorted/S1/isabelle.css": "/source/isabelle.css",
          "HOL/HOL/HOL.html": "/source/HOL.html",
          "Unsorted/S1/AFP/E/u.ML.html": "/source/_aux/AFP/E/u.ML.html",
          "fonts/TestFont.ttf": "/source/fonts/TestFont.ttf"}


def test_the_three_measured_link_shapes_rewrite_to_absolute_hrefs():
    page = ('<a href="A.B.html">same session</a>'
            '<a href="../../HOL/HOL/HOL.html#Lattices.x">cross session</a>'
            '<a href="AFP/E/u.ML.html#mldef">auxiliary</a>')
    out = sp.rewrite_html_refs(page, "Unsorted/S1", _RELOC, "Unsorted/S1/A.A.html")
    assert 'href="/source/A.B.html"' in out
    assert 'href="/source/HOL.html#Lattices.x"' in out
    assert 'href="/source/_aux/AFP/E/u.ML.html#mldef"' in out


def test_the_stylesheet_reference_rewrites_like_any_other():
    out = sp.rewrite_html_refs('<link href="isabelle.css"/>', "Unsorted/S1",
                               _RELOC, "Unsorted/S1/A.A.html")
    assert out == '<link href="/source/isabelle.css"/>'


def test_a_reference_the_map_cannot_name_is_a_hard_error():
    with pytest.raises(sp.SourcePagesError):
        sp.rewrite_html_refs('<a href="ghost.html">', "Unsorted/S1", _RELOC,
                             "Unsorted/S1/A.A.html")


def test_displayed_source_that_says_href_is_not_a_reference():
    """Rendered source code may literally contain `href="…"` as text; only
    attributes inside tags move, because tags never contain a newline and text
    never contains a raw `<`."""
    page = '<span>writeln ‹href="lost.html"›</span>'
    assert sp.rewrite_html_refs(page, "Unsorted/S1", _RELOC,
                                "Unsorted/S1/A.A.html") == page


def test_a_bare_fragment_reference_stays_where_it_is():
    page = '<a href="#L3">same page</a>'
    assert sp.rewrite_html_refs(page, "Unsorted/S1", _RELOC,
                                "Unsorted/S1/A.A.html") == page


def test_css_urls_rewrite_per_file_type():
    css = "@font-face { src: url('../../fonts/TestFont.ttf'); }"
    out = sp.rewrite_css_urls(css, "Unsorted/S1", _RELOC,
                              "Unsorted/S1/isabelle.css")
    assert out == "@font-face { src: url('/source/fonts/TestFont.ttf'); }"


def test_a_css_url_the_map_cannot_name_is_a_hard_error():
    with pytest.raises(sp.SourcePagesError):
        sp.rewrite_css_urls("src: url('../gone.ttf');", "Unsorted/S1", _RELOC,
                            "Unsorted/S1/isabelle.css")


# --- the injector (§17.4) ----------------------------------------------------

def _page(pre: str) -> str:
    return f'<html><body><pre class="source">{pre}</pre></body></html>'


def test_marks_land_on_the_first_the_middle_and_the_last_line():
    out = sp.inject_line_marks(_page("one\ntwo\nthree"), [1, 2, 3], "p")
    assert '<a id="L1"></a>one' in out
    assert '<a id="L2"></a>two' in out
    assert '<a id="L3"></a>three' in out


def test_only_the_needed_lines_get_marks():
    """The user's amendment of 2026-08-21: only the lines some exported
    record's position names, not every line."""
    out = sp.inject_line_marks(_page("one\ntwo\nthree"), [2], "p")
    assert out.count('id="L') == 1 and '<a id="L2"></a>two' in out


def test_a_trailing_newline_at_eof_is_no_edge():
    """Piece count is line count; the EOF convention only adds an empty last
    piece nothing ever needs."""
    out = sp.inject_line_marks(_page("one\ntwo\n"), [2], "p")
    assert '<a id="L2"></a>two' in out


def test_a_needed_line_past_the_end_is_a_hard_error():
    with pytest.raises(sp.SourcePagesError):
        sp.inject_line_marks(_page("one\ntwo"), [3], "p")


def test_a_second_source_element_makes_the_window_undefined():
    page = _page("one") + '<pre class="source">two</pre>'
    with pytest.raises(sp.SourcePagesError):
        sp.inject_line_marks(page, [1], "p")


def test_a_newline_inside_a_tag_stops_the_injection():
    page = '<html><body><pre class="source"><span\nclass="x">one</span></pre></body></html>'
    with pytest.raises(sp.SourcePagesError):
        sp.inject_line_marks(page, [1], "p")


def test_a_page_already_carrying_a_line_mark_id_is_a_hard_error():
    page = _page('<a id="L7"></a>one')
    with pytest.raises(sp.SourcePagesError):
        sp.inject_line_marks(page, [1], "p")


def test_an_entity_anchor_starting_with_L_is_not_a_line_mark():
    """`id="L` alone matches 555 innocent pages (`List.…`, `Lattices.…`); the
    test is `id="L<digits>"` and nothing looser."""
    page = _page('<span id="List.append|const">one</span>')
    out = sp.inject_line_marks(page, [1], "p")
    assert '<a id="L1"></a><span id="List.append|const">one</span>' in out


# --- the id-union merge (D49 ruling 6) --------------------------------------

def test_identical_copies_merge_to_themselves():
    content = _page("one\ntwo")
    merged, conflicted = sp.merge_aux_copies([("a", content), ("b", content)])
    assert merged == content and not conflicted


def test_conflicting_copies_publish_the_id_union():
    """The 12 measured conflicts differ only in entity-anchor ids; one page per
    symbolic path must keep every fragment reference into any copy landing."""
    a = _page('<a id="mldef"></a>one\ntwo')
    b = _page('<a id="mldef2"></a>one\ntwo')
    merged, conflicted = sp.merge_aux_copies([("a", a), ("b", b)])
    assert conflicted
    assert 'id="mldef"' in merged and 'id="mldef2"' in merged
    line_one = merged.split("\n")[0]
    assert 'id="mldef"' in line_one and 'id="mldef2"' in line_one


def test_copies_differing_beyond_ids_stop_the_pass():
    with pytest.raises(sp.SourcePagesError):
        sp.merge_aux_copies([("a", _page("one\ntwo")), ("b", _page("eins\ntwo"))])


def test_copies_of_different_lengths_stop_the_pass():
    with pytest.raises(sp.SourcePagesError):
        sp.merge_aux_copies([("a", _page("one\ntwo")), ("b", _page("one"))])


# --- the index (D49 ruling 5) ------------------------------------------------

def test_the_index_lists_every_page_grouped_by_session_alphabetically():
    out = sp.generate_index(["B.Z", "B.A", "A.M", "HOL"])
    assert out.index("<h2>A</h2>") < out.index("<h2>B</h2>") < out.index("<h2>HOL</h2>")
    assert out.index('href="/source/B.A.html"') < out.index('href="/source/B.Z.html"')
    for stem in ("B.Z", "B.A", "A.M", "HOL"):
        assert f'href="/source/{stem}.html"' in out
    assert 'href="/source/isabelle.css"' in out


# --- the pass and the gate, end to end on a fixture tree ---------------------

_CSS = "@font-face {{ src: url('{}fonts/TestFont.ttf'); }}\n.source {{ color: black; }}"


def _theory(title, pre):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<html>\n'
            '<head><link rel="stylesheet" type="text/css" href="isabelle.css"/>\n'
            f"<title>{title}</title>\n</head>\n<body>\n"
            f'<pre class="source">{pre}</pre>\n</body>\n</html>\n')


def _fixture_tree(tmp_path):
    files = {
        "index.html": "<html/>",
        "isabelle.css": _CSS.format(""),
        "isabelle.gif": "GIF",
        "fonts/TestFont.ttf": "FONT",
        "Unsorted/index.html": "<html/>",
        "Unsorted/S1/index.html": '<a href="session_graph.pdf">g</a>',
        "Unsorted/S1/session_graph.pdf": "PDF",
        "Unsorted/S1/isabelle.css": _CSS.format("../../"),
        "Unsorted/S1/.browser_info/build_uuid": "uuid",
        "Unsorted/S1/A.A.html": _theory("Theory A.A",
            '<span>lemma one</span> <a href="A.B.html#A.B.foo|fact">foo</a>\n'
            '<a href="../../HOL/HOL/HOL.html#Lattices.x">x</a> '
            '<a href="AFP/E/u.ML.html#mldef">u</a>\nthree'),
        "Unsorted/S1/A.B.html": _theory("Theory A.B",
            '<span id="A.B.foo|fact">foo</span>'),
        "Unsorted/S1/AFP/E/u.ML.html": _theory("File u.ML",
            'line one\n<a id="mldef"></a>line two'),
        "Unsorted/S1/AFP/E/isabelle.css": _CSS.format("../../../../"),
        "Unsorted/S2/AFP/E/u.ML.html": _theory("File u.ML",
            'line one\n<a id="mldef2"></a>line two'),
        "HOL/index.html": "<html/>",
        "HOL/HOL/isabelle.css": _CSS.format("../../"),
        "HOL/HOL/HOL.html": _theory("Theory HOL",
            '<span id="Lattices.x">x</span>'),
    }
    root = tmp_path / "rendered"
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return str(root)


def _fixture_artefact(tmp_path):
    body = {
        "format": sp.ARTEFACT_FORMAT,
        "registry_entries": 3,
        "file_page_map": {"$AFP/E/A.thy": "/source/A.A.html",
                          "$AFP/E/u.ML": "/source/_aux/AFP/E/u.ML.html"},
        "residue": {"$AFP/E/lost.thy": "no registry name matches the stem"},
        "needed_lines": {"$AFP/E/A.thy": [1, 3], "$AFP/E/u.ML": [2],
                         "$AFP/E/lost.thy": [5]},
        "links": {"id1": "/source/A.A.html#L1",
                  "id2": "/source/A.A.html#L3",
                  "id3": "/source/_aux/AFP/E/u.ML.html#L2",
                  "id4": ""},
    }
    path = str(tmp_path / "artefact.json")
    sp.write_artefact(path, body)
    return path


def test_the_rendered_tree_classifies_into_the_declared_classes(tmp_path):
    tree = sp.classify_rendered_tree(_fixture_tree(tmp_path))
    assert set(tree.theory_pages) == {"A.A", "A.B", "HOL"}
    assert set(tree.aux_copies) == {"$AFP/E/u.ML"}
    assert len(tree.aux_copies["$AFP/E/u.ML"]) == 2
    assert len(tree.css_copies) == 4 and len(tree.fonts) == 1
    assert tree.dropped == {"renderer index page": 4, "session graph": 1,
                            "isabelle.gif": 1, ".browser_info bookkeeping": 1}
    assert not tree.unclassified


def test_a_duplicate_theory_page_stem_stops_the_classification(tmp_path):
    root = _fixture_tree(tmp_path)
    dup = os.path.join(root, "Unsorted", "S2", "A.A.html")
    with open(dup, "w", encoding="utf-8") as f:
        f.write("<html/>")
    with pytest.raises(sp.SourcePagesError):
        sp.classify_rendered_tree(root)


def test_the_pass_publishes_the_fixture_tree(tmp_path):
    rendered = _fixture_tree(tmp_path)
    artefact = _fixture_artefact(tmp_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=rendered, artefact_path=artefact, out=out)

    def read(rel):
        with open(os.path.join(out, rel), encoding="utf-8") as f:
            return f.read()

    a = read("A.A.html")
    assert '<a id="L1"></a>' in a and '<a id="L3"></a>' in a
    assert 'href="/source/A.B.html#A.B.foo|fact"' in a
    assert 'href="/source/HOL.html#Lattices.x"' in a
    assert 'href="/source/_aux/AFP/E/u.ML.html#mldef"' in a
    assert 'href="/source/isabelle.css"' in a
    u = read("_aux/AFP/E/u.ML.html")
    assert '<a id="L2"></a>' in u
    assert 'id="mldef"' in u and 'id="mldef2"' in u       # the id-union merge
    assert read("isabelle.css").count("url('/source/fonts/TestFont.ttf')") == 1
    assert read("fonts/TestFont.ttf") == "FONT"
    assert 'href="/source/A.B.html"' in read("index.html")
    assert not os.path.exists(os.path.join(out, "isabelle.gif"))
    with open(out + ".report.json", encoding="utf-8") as f:
        report = json.load(f)
    assert report["marks injected"] == 3
    assert report["auxiliary conflicts merged"] == 1


def test_the_pass_never_writes_into_a_directory_it_was_handed(tmp_path):
    rendered = _fixture_tree(tmp_path)
    artefact = _fixture_artefact(tmp_path)
    out = tmp_path / "published"
    out.mkdir()
    with pytest.raises(sp.SourcePagesError):
        sp.run_publish(rendered=rendered, artefact_path=artefact, out=str(out))


def test_the_gate_passes_the_published_fixture(tmp_path):
    rendered = _fixture_tree(tmp_path)
    artefact = _fixture_artefact(tmp_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=rendered, artefact_path=artefact, out=out)
    assert sp.run_gate(published=out, artefact_path=artefact, namespace=None,
                       region="", sample=0) == 0


def test_the_gate_counts_a_missing_mark(tmp_path):
    rendered = _fixture_tree(tmp_path)
    artefact = _fixture_artefact(tmp_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=rendered, artefact_path=artefact, out=out)
    page = os.path.join(out, "A.A.html")
    with open(page, encoding="utf-8") as f:
        content = f.read()
    with open(page, "w", encoding="utf-8") as f:
        f.write(content.replace('<a id="L3"></a>', ""))
    assert sp.run_gate(published=out, artefact_path=artefact, namespace=None,
                       region="", sample=0) >= 1


def test_the_gate_trusts_no_fragment(tmp_path):
    """D49 ruling 6 killed the trusted-anchors clause: a reference whose
    fragment matches no id on its target is a miss, entity anchors included."""
    rendered = _fixture_tree(tmp_path)
    artefact = _fixture_artefact(tmp_path)
    out = str(tmp_path / "published")
    sp.run_publish(rendered=rendered, artefact_path=artefact, out=out)
    target = os.path.join(out, "A.B.html")
    with open(target, encoding="utf-8") as f:
        content = f.read()
    with open(target, "w", encoding="utf-8") as f:
        f.write(content.replace('id="A.B.foo|fact"', 'id="renamed"'))
    assert sp.run_gate(published=out, artefact_path=artefact, namespace=None,
                       region="", sample=0) >= 1


def test_the_gate_checks_every_row_link_literally(tmp_path):
    """The end-to-end clause D49 ruling 2 bought: the string the site will emit
    is the string that must work."""
    rendered = _fixture_tree(tmp_path)
    out = str(tmp_path / "published")
    body = sp.load_artefact(_fixture_artefact(tmp_path))
    body["links"]["id9"] = "/source/Ghost.html#L1"
    bad = str(tmp_path / "artefact-bad.json")
    sp.write_artefact(bad, body)
    sp.run_publish(rendered=rendered, artefact_path=bad, out=out)
    assert sp.run_gate(published=out, artefact_path=bad, namespace=None,
                       region="", sample=0) >= 1
