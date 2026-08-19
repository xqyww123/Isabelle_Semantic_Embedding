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

import pytest

from Isabelle_Semantic_Embedding import tokenizer_asset
from Isabelle_Semantic_Embedding.isabelle_tokenizer import Tokenizer


@pytest.fixture(scope="module")
def asset():
    return tokenizer_asset.build_asset()


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
    from Isabelle_RPC_Host.unicode import is_private_use
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

    here = os.path.dirname(os.path.abspath(tokenizer_asset.__file__))
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
