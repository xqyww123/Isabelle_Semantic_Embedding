# -*- coding: utf-8 -*-
r"""Build `inputs.jsonl` — the committed half of the tokenizer gate (§16.5).

**Only inputs are committed. Expected outputs are computed in CI, by each
implementation, and checked against one digest** (`expected.json`). That is the whole
shape of the gate, and it follows from one measured fact: an expectations file is a
recording of what the code currently does, so it can always be re-recorded to agree
with a broken tokenizer. A digest of the two implementations' output cannot — if they
disagree, one digest moves; if they agree wrongly, both move, and moving is itself the
signal (§16.6).

Three kinds of input, and each is here for a different reason.

**Hand-written.** §16.2's acceptance table, §5.3's relations, and one case per feature
§16.5 names. These are the only inputs whose expected output a human writes, in
`test_isabelle_tokenizer.py`; they are the only thing that validates Python against §5
rather than against itself.

**Asset-derived.** One input per symbol-table key, per fold-table key, and per ordered
marker pair — each in four forms: bare, and embedded between letters, between digits
and between separators. The embedding is load-bearing rather than decorative: a lone
non-letter tokenizes to itself either way, so a bare `\<G>` cannot detect `𝒢` being
dropped from the letter class, while `x\<G>y` can. Measured: without the embeddings,
70 of 275 single-code-point asset mutations that the real sample detects become
invisible; with them, 54 of those 70 come back. This half is generated from the
asset's own keys, so a symbol added to the asset automatically gains coverage and the
18 symbol names carrying a digit, `_` or `'` — which no corpus record contains — stop
being a hole nobody thought of.

**Real.** Sampled from the corpus, because no hand-written case has the shape of real
Isabelle text. The rule decides each record on its own — the leading four bytes of its
key digest for its expression, the trailing four for its name — so the sample
reproduces from the store alone, with no ordering pass and no seed.
"""
import hashlib
import json
import os
import sys
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, '..', '..')))

from Isabelle_Semantic_Embedding import tokenizer_asset
from Isabelle_Semantic_Embedding.semantics import Semantic_DB

STORE_DIGEST = 'a2dbbb874fe178867dd07bc05901fc96'      # §3's preamble
TARGET_EXPRESSIONS = 10000                             # §16.5's floor, unchanged
TARGET_NAMES = 2000

# JSON escapes every character below U+0020 but leaves these three raw, and all three
# terminate lines for Python's str.splitlines and for plenty of other readers. A
# line-oriented file that can hold a line break inside a line is not a contract.
_LINE_TERMINATORS = {'\u0085': '\\u0085', '\u2028': '\\u2028', '\u2029': '\\u2029'}


def one_line(text):
    for raw, escaped in _LINE_TERMINATORS.items():
        text = text.replace(raw, escaped)
    return text


SYNTHETIC = [
    # §16.2's acceptance table, every row.
    ('16.2', 'sorted_wrt R ?xs'),
    ('16.2', 'Kelly_1_39 ?C ?T ?a'),
    ('16.2', 'Stirling_Formula.c = ln (2*pi)/2'),
    ('16.2', 'f x + y'),
    ('16.2', 'x y'),
    ('16.2', '_wrt'),
    ('16.2', 'F'),
    ('16.2', r'\<Longrightarrow>'),
    ('16.2', '::'),
    ('16.2', '-->'),
    ('16.2', '==>'),
    ('16.2', r'x\<^sub>i + y\<^sup>T'),
    ('16.2', r'f\<^bsub>i\<^esub> = g'),
    ('16.2', r'\<^bold>x \<^bold>('),
    ('16.2', r'[x]\<^sup>c\<^sup>e'),
    ('16.2', r'f\<^sub>1'),
    ('16.2', 'a?b'),
    ('16.2', '?a + ?b'),
    ('16.2', '?a+?b'),
    ('16.2', 'a+b'),
    ('16.2', 'HOL-Analysis.Path_Connected.path_image_join'),
    ('16.2', 'Path_Connected.path_image_join'),
    ('16.2', "f'"),
    ('16.2', r'\<='),
    ('16.2', r'\<binit>'),
    ('16.2', r'\<alpha>'),
    ('16.2', r'\< \<alpha>'),
    ('16.2', r'\<\<alpha>'),
    ('16.2', 'x1'),
    ('16.2', 'f 100'),
    ('16.2', 'f 1000'),
    ('16.2', r'1 / 10\<^sup>2'),
    ('16.2', 'x-y'),
    ('16.2', '%x. x'),
    ('16.2', '_'),
    ('16.2', '.'),
    ('16.2', '?'),
    ('16.2', '   '),
    ('16.2', '???'),
    ('16.2', '_.'),
    ('16.2', r'\<^sub>'),

    # §5.3's verified equivalences and non-equivalences, both sides of each.
    ('5.3', 'x + y'), ('5.3', 'x+y'),
    ('5.3', '(- x)'), ('5.3', '(-x)'),
    ('5.3', r'A \<Longrightarrow> B \<Longrightarrow> C'),
    ('5.3', r'A\<Longrightarrow>B\<Longrightarrow>C'),
    ('5.3', r'\<lbrakk>?P; ?Q\<rbrakk>'), ('5.3', r'\<lbrakk>?P;?Q\<rbrakk>'),
    ('5.3', r'\<lambda>x. P x'), ('5.3', r'\<lambda>x.P x'),
    ('5.3', 'x :: nat'), ('5.3', 'x::nat'),
    ('5.3', r'x\<^sub>1 + y'), ('5.3', r'x\<^sub>1+y'),
    ('5.3', 'sorted_wrt R ?xs'), ('5.3', 'sorted_wrt R xs'),
    ('5.3', 'f x'), ('5.3', 'fx'),
    ('5.3', 'map f xs'), ('5.3', 'mapfxs'),
    ('5.3', 'size Č = 0'),

    # §16.5's named minimum.
    ('nfd', unicodedata.normalize('NFD', 'size Č = 0')),
    ('nfd', unicodedata.normalize('NFD', 'x⇩1 Č')),
    ('u007f', 'a\x7fb'),
    ('u007f', 'sorted\x7fwrt'),
    ('subsup_without_a_fold_entry', r'f\<^sub>,'),
    ('subsup_without_a_fold_entry', r'f\<^sup>('),
    ('subsup_without_a_fold_entry', '⇩,'),
    ('separator_only', '⇩⇧'),
    ('fallback_clause', '₁₂'),           # two rendered digits: two tokens, both kept
    ('separator_only', '..__..'),
    ('boundary_character', 'x²'),
    ('boundary_character', '²'),
    ('boundary_character', 'a\ufeffb'),          # inside JS \s, outside isspace()
    ('boundary_character', 'a\x1cb'),            # isspace(), outside JS \s
    ('boundary_character', 'a\x1fb'),
    ('boundary_character', 'a\x85b'),
    ('boundary_character', 'a\u2028b'),
    ('boundary_character', 'a\u2029b'),
    ('boundary_character', 'a\x0bb'),
    ('fallback_clause', r'(\<^sup>c\<^sup>e)'),
    ('fallback_clause', r'+\<^sub>p\<^sub>t\<^sub>r+'),
    ('fallback_clause', r'x\<^sub>p\<^sub>t\<^sub>r'),
    ('private_use_escape', r'\<Ptr>'),           # D44: survives as its literal escape
    ('private_use_escape', r'f \<Ptr> g'),
    ('escape_against_ascii_symbolic', r'|\<binit>|'),   # D43's 17-record loss pattern
    ('escape_against_ascii_symbolic', r'~\<^cite>'),
    ('escape_against_ascii_symbolic', r'\<param>:'),
    ('astral_symbol', r'\<S>'),                  # 𝒮 — catches a UTF-16 code-unit port
    ('astral_symbol', r'\<AA> \<S>x'),
    ('adjacent_fold_markers', 'x⇩⇩1'),
    ('adjacent_fold_markers', 'x⇩⇩⇩1'),
    ('adjacent_fold_markers', 'x⇩⇩⇩⇩1'),
    ('adjacent_fold_markers', r'x\<^sub>\<^sub>1'),
    ('escape_scanning', r'\<alpha \<beta>'),     # the loose pattern loses \<beta>
    ('escape_scanning', r'\<^sub>x'),
    ('escape_scanning', r'\<not_a_symbol>'),
    ('numeric_class', '2²'),
    ('numeric_class', '62\\<^sup>2 = 3844'),
    ('numeric_class', '一x'),                     # letter before digit, still discriminating
    ('numeric_class', '一二三'),
    ('numeric_class', r'1\<one>2'),               # astral digit between ASCII digits
    ('numeric_class', r'\<one>\<zero>'),
    ('numeric_class', 'nat1'),
    ('numeric_class', 'list2set'),
    ('numeric_class', 'sorted_wrt2'),
    ('numeric_class', '½'),                       # isnumeric(), not isdigit()
    ('numeric_class', '1½2'),

    # --- added 2026-08-20, from the adversarial review -----------------------
    # Each of these closes a hole that was measured, and each is HAND-WRITTEN on
    # purpose: a case generated from the implementation cannot validate the
    # implementation, so the cases that discriminate a Python rule must live here and
    # in `test_isabelle_tokenizer.py`, never only in the asset-derived half.

    # A marker set written out by hand instead of read off the fold table passes every
    # other vector: ❙ is 52 of the 142 fold keys, and the four cases above only ever
    # repeat ⇩.
    ('adjacent_fold_markers', r'\<^bold>\<^sub>1'),
    ('adjacent_fold_markers', r'\<^bold>\<^sub>x'),
    ('adjacent_fold_markers', r'\<^sup>\<^bold>a'),

    # An escape name carrying a digit, `_` or `'`. The asset defines 18; no corpus
    # record contains one, so narrowing the escape pattern to `[A-Za-z]*` passed
    # everything until these existed.
    ('escape_scanning', r'\<^theory_text>x'),
    ('escape_scanning', r'\<half_bc2>'),
    ('escape_scanning', r"\<bool'>"),

    # NFKC folds `²` to `2` and `ﬁ` to `fi`; NFC does not. The character must be
    # LITERAL in the input — one produced by the fold pass arrives long after step 1,
    # which is why `1 / 10\<^sup>2` above leaves the substitution undetected.
    ('nfkc_would_fold', 'x²y'),
    ('nfkc_would_fold', 'ﬁx'),
    ('nfkc_would_fold', '½ + ½'),

    ('empty', ''),
]


def asset_derived(asset):
    """Every key of the asset's own two tables, bare and in three contexts.

    The contexts are what make this half detect a character being dropped from a
    class, rather than only detecting the table being unread.
    """
    keys = sorted(asset['symbols']) + sorted(asset['symbols_private_use']) \
        + sorted(asset['fold'])
    markers = sorted({k[0] for k in asset['fold']})
    out = []
    for k in keys:
        for form in (k, 'x%sy' % k, '1%s2' % k, '_%s_' % k):
            out.append(('asset_key', form))
    # The ordered marker cross-product, which is what discriminates a marker set read
    # off the fold table from one written out by hand. §16.5's four
    # adjacent_fold_markers cases only ever repeat one marker.
    for a in markers:
        for b in markers:
            out.append(('marker_pair', 'x%s%s1' % (a, b)))
    return out


def main():
    asset = tokenizer_asset.build_asset()
    asset_text = json.dumps(asset, ensure_ascii=False, sort_keys=True, indent=1) + '\n'
    with open(os.path.join(_HERE, 'asset.json'), 'w', encoding='utf-8') as f:
        f.write(asset_text)

    rows = [('synthetic/%03d' % i, feature, text)
            for i, (feature, text) in enumerate(SYNTHETIC)]
    for i, (feature, text) in enumerate(asset_derived(asset)):
        rows.append(('asset/%04d' % i, feature, text))

    n_expr, n_name = 1336979, 1343793                      # §3.1, on the store above
    cut_expr = (TARGET_EXPRESSIONS << 32) // n_expr
    cut_name = (TARGET_NAMES << 32) // n_name
    for key, rec in Semantic_DB.iter_entity_records():
        kd = hashlib.blake2b(key, digest_size=8).digest()
        if rec.expr and int.from_bytes(kd[:4], 'big') < cut_expr:
            rows.append(('expr/' + kd.hex(), 'real_expression', rec.expr))
        if rec.name and int.from_bytes(kd[4:], 'big') < cut_name:
            rows.append(('name/' + kd.hex(), 'real_name', rec.name))

    lines = [one_line(json.dumps({'id': i, 'feature': f, 'input': t},
                                 ensure_ascii=False, separators=(',', ':')))
             for i, f, t in rows]
    body = ('\n'.join(lines) + '\n').encode('utf-8')
    with open(os.path.join(_HERE, 'inputs.jsonl'), 'wb') as f:
        f.write(body)

    by_feature = {}
    for _, f, _ in rows:
        by_feature[f] = by_feature.get(f, 0) + 1
    print(json.dumps({'count': len(rows), 'bytes': len(body),
                      'store_digest': STORE_DIGEST,
                      'asset_sha256': hashlib.sha256(asset_text.encode('utf-8')).hexdigest(),
                      'count_by_feature': dict(sorted(by_feature.items()))},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
