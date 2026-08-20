# -*- coding: utf-8 -*-
r"""Tokenize `inputs.jsonl` with the production Python implementation and check the
result against the one committed digest (§16.6).

There is no committed expectations file. `--check` recomputes the digest of this
implementation's output over the committed inputs and compares it with
`expected.json`; `emit.mjs` does the same on the JavaScript side against the same
number. So a divergence between the two implementations moves exactly one digest, and
a change that hits both moves both — and moving is itself the signal, which is what
catches a rule change that forgot to bump `tokenizer_rule` (§16.4: without the bump
the asset's bytes do not move, so the namespace name does not move, and §8.2's "write
into a new namespace" silently becomes an upsert into the live one).

    python3 emit.py            write the output to stdout, for diffing against emit.mjs
    python3 emit.py --check    recompute and compare with expected.json
    python3 emit.py --update   rewrite expected.json from the current implementation

Needs neither Isabelle nor the rest of this package: the tokenizer reads the committed
asset and nothing else, which is the property §5.5 exists to establish and this file
must not quietly undermine.
"""
import hashlib
import importlib.util
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

# JSON escapes every character below U+0020 but leaves U+0085, U+2028 and U+2029 raw,
# and all three terminate lines for Python's str.splitlines and for other readers.
# Escaping them keeps "split on LF" the only reading of either file.
LINE_TERMINATORS = {'\u0085': '\\u0085', '\u2028': '\\u2028', '\u2029': '\\u2029'}


def one_line(text):
    for raw, escaped in LINE_TERMINATORS.items():
        text = text.replace(raw, escaped)
    return text


def load_tokenizer_module():
    """By path, never by package name.

    `Isabelle_Semantic_Embedding/__init__.py` imports `premise_selection`, which needs
    `Isabelle_RPC_Host`, published to conda and not to PyPI — so a plain import is not
    available where this has to run. It was once a fallback after a `try:`, and that
    made the gate test the INSTALLED copy on a developer's machine and the working
    tree in CI: with a non-editable install, a broken working-tree tokenizer produced
    a green gate. One subject, always.
    """
    path = os.path.normpath(os.path.join(
        _HERE, '..', '..', 'Isabelle_Semantic_Embedding', 'isabelle_tokenizer.py'))
    spec = importlib.util.spec_from_file_location('isabelle_tokenizer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def emit(directory=_HERE):
    """The output whose digest is the gate, plus the digests of what produced it."""
    with open(os.path.join(directory, 'asset.json'), encoding='utf-8') as f:
        asset_text = f.read()
    with open(os.path.join(directory, 'inputs.jsonl'), 'rb') as f:
        inputs_body = f.read()
    asset = json.loads(asset_text)
    tok = load_tokenizer_module().Tokenizer(asset)

    lines = []
    for line in inputs_body.decode('utf-8').split('\n'):
        if not line:
            continue
        v = json.loads(line)
        lines.append(one_line(json.dumps(
            {'id': v['id'], 'tokens': tok.tokenize(v['input']),
             'subtokens': tok(v['input'])},
            ensure_ascii=False, separators=(',', ':'))))
    body = ('\n'.join(lines) + '\n').encode('utf-8')
    return body, {'tokenizer_rule': asset['tokenizer_rule'],
                  'asset_sha256': sha256(asset_text.encode('utf-8')),
                  'inputs_sha256': sha256(inputs_body),
                  'inputs_count': len(lines),
                  'output_sha256': sha256(body)}


def check(directory=_HERE):
    _, got = emit(directory)
    with open(os.path.join(directory, 'expected.json'), encoding='utf-8') as f:
        want = json.load(f)
    problems = []
    for field in ('asset_sha256', 'inputs_sha256', 'inputs_count', 'tokenizer_rule'):
        if got[field] != want.get(field):
            problems.append('%s is %r, expected.json says %r'
                            % (field, got[field], want.get(field)))
    if got['output_sha256'] != want.get('output_sha256'):
        problems.append(
            "the tokenizer's output over the committed inputs hashes to %s, "
            "expected.json says %s.\n"
            "      The behaviour moved. If a rule of §5.1, §5.2 or §5.4 changed, bump "
            "TOKENIZER_RULE in Isabelle_Semantic_Embedding/tokenizer_asset.py in the "
            "same commit and rebuild the asset -- without that bump the asset's bytes "
            "do not move, so the turbopuffer namespace name does not move, and "
            "§8.2's \"write into a new namespace\" becomes an upsert into the live "
            "one. Then run emit.py --update.\n"
            "      If nothing was meant to change, this is the regression the gate "
            "exists to catch: run `python3 emit.py > /tmp/py.out; node emit.mjs > "
            "/tmp/js.out; diff /tmp/py.out /tmp/js.out` to see which side moved."
            % (got['output_sha256'], want.get('output_sha256')))
    for p in problems:
        print('FAIL  %s' % p)
    print('%d inputs, %d problems' % (got['inputs_count'], len(problems)))
    return 1 if problems else 0


def update():
    _, got = emit()
    got['generated'] = time.strftime('%Y-%m-%d')
    with open(os.path.join(_HERE, 'expected.json'), 'w', encoding='utf-8') as f:
        json.dump(got, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')
    print(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == '__main__':
    if '--check' in sys.argv:
        sys.exit(check())
    if '--update' in sys.argv:
        sys.exit(update())
    sys.stdout.buffer.write(emit()[0])
