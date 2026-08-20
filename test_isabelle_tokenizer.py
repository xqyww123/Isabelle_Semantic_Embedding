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


def _emit():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'emit', os.path.join(_vector_dir(), 'emit.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


Tokenizer = _emit().load_tokenizer_module().Tokenizer


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

    `site/tokenizer/asset.json` is what both implementations read. If the symbol table
    it was built from has moved — a new component registered, a distribution upgrade,
    an edit to `SUBSUP_TRANS_TABLE` — the committed asset is stale and the committed
    digest describes a tokenizer nobody runs any more.

    It skips when this machine's symbol files are not the ones the asset records. That
    skip is honest because the asset identifies each file by name and SHA-256 rather
    than by path: a contributor whose Isabelle sits elsewhere still gets the test, and
    only a genuinely different table skips it. An earlier version compared absolute
    paths, so it could not have passed on any machine but the author's.
    """
    import json
    import os
    live = _live_asset()
    with open(os.path.join(_vector_dir(), 'asset.json'), encoding='utf-8') as f:
        committed = json.load(f)
    if live['symbol_files'] != committed['symbol_files']:
        pytest.skip("this machine's symbol files are not the ones the asset records: "
                    '%s' % [f['name'] for f in live['symbol_files']])
    dump = lambda a: json.dumps(a, ensure_ascii=False, sort_keys=True, indent=1)
    assert dump(live) == dump(committed)


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
    # --- added 2026-08-20, each closing a hole the adversarial review measured ----
    # A marker set written out by hand instead of read off the fold table passes every
    # other case: ❙ is 52 of the 142 fold keys, and the four rows above only repeat ⇩.
    (r'\<^bold>\<^sub>1',         ['1']),
    (r'\<^bold>\<^sub>x',         ['x']),
    (r'\<^sup>\<^bold>a',         ['a']),
    # An escape name carrying a digit or `_`. The asset defines 18 such names and no
    # corpus record contains one, so narrowing the pattern to `[A-Za-z]*` passed
    # everything until these existed.
    (r'\<^theory_text>x',          ['⬚', 'x']),
    (r'\<half_bc2>',               ['◑']),
    # A private-use escape whose name carries a quasi-letter: D44 leaves it literal,
    # and `bool'` is one identifier token because `'` is a quasi-letter.
    (r"\<bool'>",                  [r'\<', "bool'", '>']),
    # NFKC folds these and NFC does not. The character must be LITERAL in the input:
    # one produced by the fold pass arrives long after step 1, which is why the row
    # `1 / 10\<^sup>2` above leaves an NFC-for-NFKC substitution undetected.
    ('x²y',                        ['x', 'y']),
    ('ﬁx',                         ['ﬁx']),
    ('½ + ½',                      ['½', '+', '½']),

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


# --- §16.5's inputs and §16.6's gate ------------------------------------------

def test_the_committed_digest_still_describes_this_implementation():
    """§16.6, the whole of it.

    No expectations are committed. This recomputes the digest of the Python
    implementation's output over the committed inputs and compares it with the one
    number in `expected.json`; `emit.mjs` checks the same number on the other side.
    A divergence between the two moves exactly one digest, and a rule change moves
    both -- which is what catches a rule change that forgot to bump `tokenizer_rule`.
    """
    assert _emit().check(_vector_dir()) == 0


def test_the_inputs_file_can_only_be_read_one_way():
    """A line-oriented file must not be able to hold a line break inside a line.

    JSON escapes everything below U+0020 but leaves U+0085, U+2028 and U+2029 raw,
    and all three end a line for `str.splitlines` and for other readers. Real corpus
    text contains them; the generator escapes them, and this asserts it did.
    """
    import re
    text = open(os.path.join(_vector_dir(), 'inputs.jsonl'), encoding='utf-8').read()
    assert not re.search('[\u0085\u2028\u2029\r]', text)
    assert len(text.split('\n')) - 1 == len(text.splitlines())


# --- §5.5: the asset is the only source ---------------------------------------

def _toy():
    import json
    with open(os.path.join(_vector_dir(), 'toy_asset.json'), encoding='utf-8') as f:
        return json.load(f)


def test_the_asset_is_the_only_source():
    """The one property no real corpus can prove.

    Python's `isalpha()` and JavaScript's `\\p{L}` agree on every character the
    corpus contains, so an implementation that asks its language passes every real
    input and is wrong only on characters no sample has. `toy_asset.json` settles it
    by construction: every class in it contradicts what a built-in would say, in both
    directions, so consulting one diverges on the first case. Measured: these cases
    catch all twelve single-field substitutions of the forbidden kinds.
    """
    toy = _toy()
    tok = Tokenizer(toy['asset'])
    wrong = [(c['input'], tok(c['input']), c['subtokens'])
             for c in toy['cases'] if tok(c['input']) != c['subtokens']]
    assert not wrong


def test_the_toy_asset_contradicts_the_language_in_both_directions():
    """If it ever stops disagreeing with Python, it stops proving anything."""
    toy = _toy()['asset']
    letters = {chr(cp) for lo, hi in toy['letters'] for cp in range(lo, hi + 1)}
    digits = {chr(cp) for lo, hi in toy['digits'] for cp in range(lo, hi + 1)}
    spaces = {chr(cp) for lo, hi in toy['spaces'] for cp in range(lo, hi + 1)}
    assert any(not c.isalpha() for c in letters)      # a letter the language denies
    assert any(c.isalpha() for c in digits)           # a digit the language calls a letter
    assert any(not c.isspace() for c in spaces)       # whitespace the language denies
    assert ' ' not in spaces                          # and the real space is not one
