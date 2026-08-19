# -*- coding: utf-8 -*-
"""§16.6's gate, the half of it that runs in Python. The JavaScript port runs the
same file and must reach the same verdict.

Four assertions, and the third is the one that exists because of how this can be
cheated:

1. The `.jsonl`'s bytes hash to what the meta says, and there are as many lines as it
   says. A vector file that has drifted from its own header is not evidence.
2. The Python implementation reproduces every triple.
3. **The digest may not change while the count stays the same** unless the history's
   newest line says a rule changed and why. Changing a tokenizer rule alters the
   expected output of thousands of existing vectors and leaves the count where it was
   — which is exactly the shape of a file quietly regenerated to match a broken
   implementation. A real rule change adds the cases the new rule needs (§16.5), so it
   moves the count anyway; if it genuinely does not, say so in the history line.
4. Every feature §16.5 names by hand is present. Sampling real expressions cannot
   reach pipeline steps 1, 2 and 3 at all, so a sample size is not coverage.
"""
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, '..', '..', '..')))

# The features §16.5 requires by name. A vector file missing any of them is not a
# gate, whatever its size.
REQUIRED_FEATURES = (
    '16.2', '5.3', 'nfd', 'u007f', 'subsup_without_a_fold_entry', 'separator_only',
    'boundary_character', 'fallback_clause', 'private_use_escape',
    'escape_against_ascii_symbolic', 'astral_symbol', 'adjacent_fold_markers',
    'escape_scanning', 'numeric_class', 'empty', 'real_expression', 'real_name',
)


def parse_history(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        fields = dict(part.split('=', 1) for part in line.split() if '=' in part)
        out.append({'count': int(fields['count']), 'sha256': fields['sha256'],
                    'rule_change': 'rule-change:' in line, 'line': line})
    return out


def main(directory=_HERE, tokenizer=None):
    meta = json.load(open(os.path.join(directory, 'test_vectors.meta.json'), encoding='utf-8'))
    body = open(os.path.join(directory, 'test_vectors.jsonl'), 'rb').read()
    problems = []

    digest = hashlib.sha256(body).hexdigest()
    if digest != meta['sha256']:
        problems.append('the .jsonl hashes to %s, the meta says %s' % (digest, meta['sha256']))

    # Split on LF and nothing else: str.splitlines also breaks at U+0085, U+2028 and
    # U+2029, which real Isabelle text contains. The generator escapes those three for
    # the same reason, so a file that still splits differently under the two readings
    # is a malformed file and this catches it.
    text = body.decode('utf-8')
    vectors = [json.loads(line) for line in text.split('\n') if line]
    if len(text.split('\n')) - 1 != len(text.splitlines()):
        problems.append('a line contains a character some line readers treat as a break')
    if len(vectors) != meta['count']:
        problems.append('%d lines, the meta says %d' % (len(vectors), meta['count']))

    if tokenizer is None:
        from Isabelle_Semantic_Embedding.isabelle_tokenizer import Tokenizer
        from Isabelle_Semantic_Embedding import tokenizer_asset
        tokenizer = Tokenizer(tokenizer_asset.build_asset())
    mismatched = 0
    for v in vectors:
        if tokenizer.tokenize(v['input']) != v['tokens'] or tokenizer(v['input']) != v['subtokens']:
            mismatched += 1
            if mismatched <= 5:
                problems.append('%s: %r -> %s / %s, expected %s / %s'
                                % (v['id'], v['input'], tokenizer.tokenize(v['input']),
                                   tokenizer(v['input']), v['tokens'], v['subtokens']))
    if mismatched > 5:
        problems.append('... and %d more mismatches' % (mismatched - 5))

    history = parse_history(open(os.path.join(directory, 'test_vectors.history'),
                                 encoding='utf-8').read())
    if not history:
        problems.append('the history is empty')
    else:
        last = history[-1]
        if (last['count'], last['sha256']) != (meta['count'], meta['sha256']):
            problems.append('the newest history line does not describe this file: %s'
                            % last['line'])
        if len(history) >= 2:
            prev = history[-2]
            if last['sha256'] != prev['sha256'] and last['count'] == prev['count'] \
                    and not last['rule_change']:
                problems.append(
                    'the digest changed while the count did not, and the history line '
                    'does not say a rule changed: %s' % last['line'])

    present = {v['feature'] for v in vectors}
    for feature in REQUIRED_FEATURES:
        if feature not in present:
            problems.append('no vector covers the feature %r' % feature)

    for p in problems:
        print('FAIL  %s' % p)
    print('%d vectors, %d features, %d problems'
          % (len(vectors), len(present), len(problems)))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
