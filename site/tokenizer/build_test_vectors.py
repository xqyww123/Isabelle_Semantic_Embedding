# -*- coding: utf-8 -*-
r"""Build the shared test-vector file of §16.5 — the one artefact both implementations
must reproduce exactly (§5.5), and the thing §16.6's CI gate runs them against.

Two halves, and §16.5 is explicit that neither alone is enough.

**Real expressions**, sampled from the corpus, because no hand-written case has the
shape of real Isabelle text. But on the corpus that is actually published, pipeline
steps 1, 2 and 3 are all the identity — measured, 0 records of 1,336,979 — so a port
that omits NFC normalisation and escape conversion entirely passes a purely-real-data
gate byte for byte and then returns nothing for `\<Longrightarrow>`, one of the two
input routes §9.3 promises.

**Synthetic cases**, therefore, each carrying the name of the feature it covers, so
that §5.5's requirement can be checked as coverage of named features rather than as a
sample size. §16.5 lists the minimum; `SYNTHETIC` below is that list, and every entry
says which line of the plan put it there.

Real samples are drawn by a rule that decides each record on its own — the leading
four bytes of its key digest for an expression, the trailing four for a name, each
against a threshold — so the sample is reproducible from the store alone, with no
ordering pass and no random seed.

Output, into this directory:

  asset.json                the exact asset the vectors were produced with, because
                            the JavaScript port cannot build one
  test_vectors.jsonl        one JSON object per line, UTF-8, LF, `{"id","feature",
                            "input","tokens","subtokens"}` in that key order
  test_vectors.meta.json    the asset it was built against, the counts, the sampling
                            rule, and the SHA-256 of the .jsonl's bytes
  test_vectors.history      append-only: one line per generation, so §16.6's gate can
                            tell a legitimate rule change from a file quietly edited
                            to match a broken implementation
"""
import hashlib
import json
import os
import sys
import time
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, '..', '..', '..')))

from Isabelle_Semantic_Embedding.isabelle_tokenizer import Tokenizer
from Isabelle_Semantic_Embedding.semantics import Semantic_DB
from Isabelle_Semantic_Embedding import tokenizer_asset

STORE_DIGEST = 'a2dbbb874fe178867dd07bc05901fc96'      # §3's preamble
TARGET_EXPRESSIONS = 10000                             # §16.5's floor
TARGET_NAMES = 2000

# Every synthetic case §16.5 requires, plus the plan line that requires it. The
# feature name is what §5.5's "coverage of named features" is checked against, so a
# case may not be added without one.
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
    ('empty', ''),
]


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


# JSON escapes every character below U+0020, but leaves these three raw — and they
# are line terminators to Python's str.splitlines, to JavaScript's regard for U+2028
# and U+2029, and to plenty of other line readers. A line-oriented file that can
# contain a line terminator inside a line is not a contract, so escape exactly these
# three. They stay legal JSON and every language's line splitter now agrees.
_LINE_TERMINATORS = {'\u0085': '\\u0085', '\u2028': '\\u2028', '\u2029': '\\u2029'}


def _one_line(text):
    for raw, escaped in _LINE_TERMINATORS.items():
        text = text.replace(raw, escaped)
    return text


def main():
    asset = tokenizer_asset.build_asset()
    asset_text = json.dumps(asset, ensure_ascii=False, sort_keys=True, indent=1) + '\n'
    tok = Tokenizer(asset)

    vectors = []
    for i, (feature, text) in enumerate(SYNTHETIC):
        vectors.append(('synthetic/%03d' % i, feature, text))

    # Each record decides its own membership, so the sample needs no ordering pass and
    # no seed: reproducing it needs only the store whose digest the meta names.
    n_expr, n_name = 1336979, 1343793                      # §3.1, on the store above
    cut_expr = (TARGET_EXPRESSIONS << 32) // n_expr
    cut_name = (TARGET_NAMES << 32) // n_name
    for key, rec in Semantic_DB.iter_entity_records():
        kd = hashlib.blake2b(key, digest_size=8).digest()
        if rec.expr and int.from_bytes(kd[:4], 'big') < cut_expr:
            vectors.append(('expr/' + kd.hex(), 'real_expression', rec.expr))
        if rec.name and int.from_bytes(kd[4:], 'big') < cut_name:
            vectors.append(('name/' + kd.hex(), 'real_name', rec.name))

    lines = []
    for vid, feature, text in vectors:
        lines.append(_one_line(json.dumps(
            {'id': vid, 'feature': feature, 'input': text,
             'tokens': tok.tokenize(text), 'subtokens': tok(text)},
            ensure_ascii=False, separators=(',', ':'))))
    body = ('\n'.join(lines) + '\n').encode('utf-8')
    digest = _sha256(body)

    with open(os.path.join(_HERE, 'test_vectors.jsonl'), 'wb') as f:
        f.write(body)
    # Beside the vectors, so the directory is self-contained: the JavaScript port
    # cannot build an asset — it has no symbol table and no Isabelle — and a gate that
    # ran the two implementations against different assets would prove nothing.
    with open(os.path.join(_HERE, 'asset.json'), 'w', encoding='utf-8') as f:
        f.write(asset_text)

    by_feature = {}
    for _, feature, _ in vectors:
        by_feature[feature] = by_feature.get(feature, 0) + 1
    meta = {
        'generated': time.strftime('%Y-%m-%d'),
        'tokenizer_rule': asset['tokenizer_rule'],
        'asset_sha256': _sha256(asset_text.encode('utf-8')),
        'store_digest': STORE_DIGEST,
        'encoding': 'UTF-8, no byte order mark, LF line endings, one JSON object per '
                    'line, keys in the order id, feature, input, tokens, subtokens; '
                    'U+0085, U+2028 and U+2029 are escaped although JSON does not '
                    'require it, so that splitting on LF is the only reading',
        'ordering': 'the synthetic cases first, in the order §16.5 lists the features '
                    'they cover, then the real samples in store iteration order',
        'sampling': 'a record contributes its expression when the first four bytes of '
                    'blake2b(key, 8), read big-endian, are below %d, and its name when '
                    'the last four are below %d; each record decides on its own, so '
                    'the sample is reproducible from the store alone'
                    % (cut_expr, cut_name),
        'count': len(vectors),
        'count_by_feature': dict(sorted(by_feature.items())),
        'sha256': digest,
    }
    with open(os.path.join(_HERE, 'test_vectors.meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')

    history = os.path.join(_HERE, 'test_vectors.history')
    entry = '%s  count=%d  sha256=%s  tokenizer_rule=%d\n' % (
        meta['generated'], meta['count'], digest, asset['tokenizer_rule'])
    old = open(history, encoding='utf-8').read() if os.path.exists(history) else ''
    if entry not in old:
        with open(history, 'a', encoding='utf-8') as f:
            f.write(entry)

    print(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True))
    print('bytes: %d' % len(body))


if __name__ == '__main__':
    main()
