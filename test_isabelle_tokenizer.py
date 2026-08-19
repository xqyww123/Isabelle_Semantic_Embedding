r"""§16.2's acceptance table and §5.3's equivalences, run against the production
tokenizer of §5.

Needs the Isabelle symbol table (ISABELLE_HOME, or `isabelle` on PATH) because the
asset is built from it here; the tokenizer itself needs nothing but the asset.

One row of §16.2 is transcribed differently from the way the plan spells it, and the
difference is the plan's error rather than this file's licence. The plan gives

    '\<alpha>', unconverted      -> ['\<','alpha','>']

but `\<alpha>` is defined in every symbol table there is, so step 3a converts it and
no implementation can produce that array. The prototype the row claims to have been
measured with returns `['α']` too. The property the row exists to pin — that an
escape step 3a did **not** convert splits into `\<`, the name and `>` — is kept here
by naming an escape the distribution genuinely lacks: `\<binit>`, one of the four
AFP Shivers-CFA symbols §5.1 already cites as unconvertible by any asset.
"""

import copy
import os

import pytest

# By path, not by package, for the reason `check_test_vectors.load_tokenizer_module`
# gives: the tokenizer needs nothing but the standard library and the asset, and the
# gate has to run where the rest of the package cannot be installed.
def _vector_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'site', 'tokenizer')


def _checker():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'check_test_vectors', os.path.join(_vector_dir(), 'check_test_vectors.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


Tokenizer = _checker().load_tokenizer_module().Tokenizer


@pytest.fixture(scope="module")
def asset():
    """The asset committed beside the test vectors.

    Not a freshly built one, so that the whole of this file runs where the gate runs:
    CI has no Isabelle distribution and no symbol table, and a gate that could only
    run on a machine with one would not be a gate. That the committed asset is still
    what the live table produces is a separate question, and
    `test_committed_asset_matches_the_live_symbol_table` is where it is asked.
    """
    import json
    import os
    with open(os.path.join(_vector_dir(), 'asset.json'), encoding='utf-8') as f:
        return json.load(f)


def _live_asset():
    try:
        from Isabelle_Semantic_Embedding import tokenizer_asset
        return tokenizer_asset.build_asset()
    except Exception as exc:                       # no ISABELLE_HOME, no symbol table
        pytest.skip('no live Isabelle symbol table here: %s' % exc)


def test_committed_asset_matches_the_live_symbol_table():
    """The one test that needs Isabelle, and the one reason to keep needing it.

    `site/tokenizer/asset.json` is what both implementations read and what the frozen
    vectors were produced against. If the symbol table it was built from has moved —
    a new component registered, a distribution upgrade, an edit to
    `SUBSUP_TRANS_TABLE` — then the committed asset is stale and the vectors are
    describing a tokenizer nobody runs any more.
    """
    import json
    import os
    live = json.dumps(_live_asset(), ensure_ascii=False, sort_keys=True, indent=1) + '\n'
    with open(os.path.join(_vector_dir(), 'asset.json'), encoding='utf-8') as f:
        assert f.read() == live


@pytest.fixture(scope="module")
def tok(asset):
    return Tokenizer(asset)


# --- §16.2 ------------------------------------------------------------------

CASES = [
    ('sorted_wrt R ?xs',            ['sorted', 'wrt', 'R', 'xs']),
    ('Kelly_1_39 ?C ?T ?a',         ['Kelly', '1', '39', 'C', 'T', 'a']),
    ('Stirling_Formula.c = ln (2*pi)/2',
     ['Stirling', 'Formula', 'c', '=', 'ln', '(', '2', '*', 'pi', ')', '/', '2']),
    ('f x + y',                     ['f', 'x', '+', 'y']),
    ('x y',                         ['x', 'y']),
    ('_wrt',                        ['wrt']),
    ('F',                           ['F']),
    (r'\<Longrightarrow>',          ['⟹']),
    ('::',                          ['::']),
    ('-->',                         ['-->']),
    ('==>',                         ['==>']),          # NOT ⟹; see §16.0
    (r'x\<^sub>i + y\<^sup>T',      ['x', '+', 'y']),
    (r'f\<^bsub>i\<^esub> = g',     ['f', 'i', '=', 'g']),
    (r'\<^bold>x \<^bold>(',        ['𝐱', '(']),
    (r'[x]\<^sup>c\<^sup>e',        ['[', 'x', ']', 'ᶜᵉ']),   # the fallback clause
    (r'f\<^sub>1',                  ['f']),
    ('a?b',                         ['a', 'b']),
    ('?a + ?b',                     ['a', '+', 'b']),
    ('?a+?b',                       ['a', '+', 'b']),
    ('a+b',                         ['a', '+', 'b']),
    ('HOL-Analysis.Path_Connected.path_image_join',
     ['HOL', '-', 'Analysis', 'Path', 'Connected', 'path', 'image', 'join']),
    ('Path_Connected.path_image_join',
     ['Path', 'Connected', 'path', 'image', 'join']),
    ("f'",                          ["f'"]),
    (r'\<=',                        [r'\<=']),
    (r'\<binit>',                   [r'\<', 'binit', '>']),   # see the module docstring
    (r'\<alpha>',                   ['α']),                   # and likewise
    (r'\< \<alpha>',                [r'\<', 'α']),
    (r'\<\<alpha>',                 [r'\<', 'α']),
    ('x1',                          ['x1']),
    ('f 100',                       ['f', '100']),
    ('f 1000',                      ['f', '1000']),
    (r'1 / 10\<^sup>2',             ['1', '/', '10', '²']),
    ('x-y',                         ['x', '-', 'y']),
    ('%x. x',                       ['%', 'x', 'x']),
    ('_', []), ('.', []), ('?', []), ('   ', []),
    ('???', []), ('_.', []), (r'\<^sub>', []),
]


@pytest.mark.parametrize("text,expected", CASES, ids=[repr(c[0]) for c in CASES])
def test_acceptance_table(tok, text, expected):
    assert tok(text) == expected


# --- §5.3 -------------------------------------------------------------------

EQUIVALENT = [
    ('x + y', 'x+y'),
    ('(- x)', '(-x)'),
    (r'A \<Longrightarrow> B \<Longrightarrow> C', r'A\<Longrightarrow>B\<Longrightarrow>C'),
    (r'\<lbrakk>?P; ?Q\<rbrakk>', r'\<lbrakk>?P;?Q\<rbrakk>'),
    (r'\<lambda>x. P x', r'\<lambda>x.P x'),
    ('x :: nat', 'x::nat'),
    (r'x\<^sub>1 + y', r'x\<^sub>1+y'),
    ('sorted_wrt R ?xs', 'sorted_wrt R xs'),
]

DIFFERENT = [('f x', 'fx'), ('map f xs', 'mapfxs')]


@pytest.mark.parametrize("a,b", EQUIVALENT)
def test_equivalences(tok, a, b):
    assert tok(a) == tok(b)


@pytest.mark.parametrize("a,b", DIFFERENT)
def test_whitespace_is_a_boundary(tok, a, b):
    assert tok(a) != tok(b)


def test_nfd_input_matches_nfc(tok):
    import unicodedata
    nfc = 'size Č = 0'
    assert tok(nfc) == tok(unicodedata.normalize('NFD', nfc))


# --- §5.1 step 3b: the non-overlapping fold scan ----------------------------

def test_adjacent_fold_markers(tok):
    """No stored record exercises this; a port folding each marker separately
    diverges here and nowhere else."""
    assert tok.normalize('x⇩1') == 'x₁'
    assert tok.normalize('x⇩⇩1') == 'x⇩⇩1'
    assert tok.normalize('x⇩⇩⇩1') == 'x⇩⇩₁'
    assert tok.normalize('x⇩⇩⇩⇩1') == 'x⇩⇩⇩⇩1'


# --- §5.5: the asset is the only source, and its version is honoured --------

def test_unknown_tokenizer_rule_is_refused(asset):
    bad = copy.deepcopy(asset)
    bad['tokenizer_rule'] = asset['tokenizer_rule'] + 1000
    with pytest.raises(ValueError, match='tokenizer_rule'):
        Tokenizer(bad)


def test_asset_class_sizes(asset):
    assert len(asset['separators']) == 99
    assert len(asset['rendered_subsup']) == 90
    assert len(asset['rendered_digits']) == 20
    assert set(asset['rendered_digits']) <= set(asset['rendered_subsup'])
    assert set(asset['rendered_subsup']) <= set(asset['separators'])


def test_private_use_symbols_are_not_shipped(asset):
    """D44 leaves such a symbol as its literal escape; dropping it from the table
    makes that identical to the undefined case, in both implementations."""
    def is_private_use(ch):
        c = ord(ch)
        return 0xE000 <= c <= 0xF8FF or 0xF0000 <= c <= 0xFFFFD or 0x100000 <= c <= 0x10FFFD
    assert not any(is_private_use(c) for c in asset['symbols'].values())
    assert asset['symbols_private_use']


def test_module_loads_with_no_isabelle_at_all(asset, tmp_path):
    """§16.3 step 2's acceptance, on the half of it that is step 1's to keep: the
    tokenizer module itself must import and run with `Isabelle_RPC_Host` and
    `ISABELLE_HOME` unavailable, or the CI gate cannot run it beside the port.

    Loaded by file rather than by name because the package's `__init__` imports
    `premise_selection`, which does need `Isabelle_RPC_Host`."""
    import importlib.abc
    import importlib.util
    import json
    import os
    import sys

    path = tmp_path / 'asset.json'
    path.write_text(json.dumps(asset), encoding='utf-8')

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split('.')[0] in ('Isabelle_RPC_Host', 'Isabelle_Semantic_Embedding'):
                raise ImportError('blocked for this test: ' + name)
            return None

    here = os.path.normpath(os.path.join(_vector_dir(), '..', '..',
                                         'Isabelle_Semantic_Embedding'))
    blocker = Block()
    sys.meta_path.insert(0, blocker)
    saved = {k: os.environ.pop(k) for k in
             ('ISABELLE_HOME', 'ISABELLE_HOME_USER', 'ISABELLE_SYMBOLS')
             if k in os.environ}
    try:
        spec = importlib.util.spec_from_file_location(
            'isabelle_tokenizer_standalone',
            os.path.join(here, 'isabelle_tokenizer.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.load(str(path))(r'\<Longrightarrow>') == ['⟹']
    finally:
        sys.meta_path.remove(blocker)
        os.environ.update(saved)


# --- §16.5's vector file and §16.6's gate -----------------------------------

def test_committed_vectors_pass_the_gate(tok):
    assert _checker().main(_vector_dir(), tok) == 0


def _tampered(tmp_path, edit):
    """A copy of the vector directory with one thing changed."""
    import json
    import os
    import shutil
    for name in ('asset.json', 'test_vectors.jsonl', 'test_vectors.meta.json',
                 'test_vectors.history'):
        shutil.copy(os.path.join(_vector_dir(), name), tmp_path / name)
    edit(tmp_path)
    return str(tmp_path)


def test_gate_fails_when_the_body_and_its_digest_disagree(tok, tmp_path, capsys):
    def edit(d):
        body = (d / 'test_vectors.jsonl').read_bytes()
        (d / 'test_vectors.jsonl').write_bytes(body.replace(b'"sorted"', b'"sortd"', 1))
    assert _checker().main(_tampered(tmp_path, edit), tok) == 1
    assert 'hashes to' in capsys.readouterr().out


def test_gate_fails_when_the_digest_moves_and_the_count_does_not(tok, tmp_path, capsys):
    """The shape of a vector file quietly regenerated to match a broken implementation."""
    def edit(d):
        history = (d / 'test_vectors.history').read_text(encoding='utf-8')
        line = history.strip().splitlines()[-1]
        older = line.replace(line.split('sha256=')[1].split()[0], '0' * 64)
        (d / 'test_vectors.history').write_text(older + '\n' + line + '\n', encoding='utf-8')
    assert _checker().main(_tampered(tmp_path, edit), tok) == 1
    assert 'the digest changed while the count did not' in capsys.readouterr().out


def test_gate_accepts_a_declared_rule_change(tok, tmp_path):
    def edit(d):
        history = (d / 'test_vectors.history').read_text(encoding='utf-8')
        line = history.strip().splitlines()[-1]
        older = line.replace(line.split('sha256=')[1].split()[0], '0' * 64)
        (d / 'test_vectors.history').write_text(
            older + '\n' + line + '  rule-change: §5.2 gained a token class\n',
            encoding='utf-8')
    assert _checker().main(_tampered(tmp_path, edit), tok) == 0


def test_gate_fails_on_a_missing_feature(tok, tmp_path, capsys):
    def edit(d):
        import hashlib
        import json
        lines = [l for l in (d / 'test_vectors.jsonl').read_text(encoding='utf-8').split('\n')
                 if l and '"astral_symbol"' not in l]
        body = ('\n'.join(lines) + '\n').encode('utf-8')
        (d / 'test_vectors.jsonl').write_bytes(body)
        meta = json.loads((d / 'test_vectors.meta.json').read_text(encoding='utf-8'))
        meta['count'] = len(lines)
        meta['sha256'] = hashlib.sha256(body).hexdigest()
        (d / 'test_vectors.meta.json').write_text(json.dumps(meta), encoding='utf-8')
        (d / 'test_vectors.history').write_text(
            '2026-08-19  count=%d  sha256=%s  tokenizer_rule=1\n'
            % (meta['count'], meta['sha256']), encoding='utf-8')
    assert _checker().main(_tampered(tmp_path, edit), tok) == 1
    assert "no vector covers the feature 'astral_symbol'" in capsys.readouterr().out
