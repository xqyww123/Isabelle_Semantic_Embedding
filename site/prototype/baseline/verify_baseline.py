# -*- coding: utf-8 -*-
"""Ask whether the production tokenizer still agrees with the frozen baseline.

`build_baseline.py` runs the prototype as well and takes twenty minutes. This runs
only the production tokenizer and recomputes the two whole-corpus digests
`baseline.json` records, which is the question anyone actually has after touching
`isabelle_tokenizer.py`: did the output move? Four minutes, and it needs the store
whose digest `baseline.json` names — check that first.
"""
import hashlib
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, '..', '..', '..')))

from Isabelle_Semantic_Embedding.isabelle_tokenizer import Tokenizer
from Isabelle_Semantic_Embedding.semantics import Semantic_DB
from Isabelle_Semantic_Embedding import tokenizer_asset

FIELDS = ('expr', 'name')

# Exactly the fields `Tokenizer.__init__` reads. Everything else in the asset is
# provenance for a human.
TOKENIZING_FIELDS = ('tokenizer_rule', 'symbols', 'fold', 'letters', 'digits', 'spaces',
                     'quasi_letters', 'discarded', 'ascii_symbolic', 'separators',
                     'rendered_subsup', 'rendered_digits')


def tokenizing_digest(asset):
    return hashlib.sha256(json.dumps({k: asset[k] for k in TOKENIZING_FIELDS},
                                     ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def main():
    baseline = json.load(open(os.path.join(_HERE, 'baseline.json'), encoding='utf-8'))
    asset = tokenizer_asset.build_asset()
    asset_text = json.dumps(asset, ensure_ascii=False, sort_keys=True, indent=1) + '\n'
    asset_sha = hashlib.sha256(asset_text.encode('utf-8')).hexdigest()
    with open(os.path.join(_HERE, 'asset.json'), encoding='utf-8') as f:
        frozen_asset = json.load(f)
    tok = Tokenizer(asset)

    rows, t0, n = {}, time.time(), 0
    for key, rec in Semantic_DB.iter_entity_records():
        kd = hashlib.blake2b(key, digest_size=8).digest()
        rows[kd] = b''.join(
            hashlib.blake2b('\0'.join(tok(s)).encode('utf-8'), digest_size=8).digest()
            if (s := getattr(rec, f)) else b'\0' * 8 for f in FIELDS)
        n += 1
    order = sorted(rows)

    problems = []
    if n != baseline['records']:
        problems.append('%d records, the baseline was taken over %d — wrong store?'
                        % (n, baseline['records']))
    # Compare what the tokenizer READS, not the whole file. The asset also carries
    # provenance -- which symbol files, which Unicode version -- and a change there
    # cannot move a single subtoken, so making it fail here would leave this tool
    # permanently red after the first honest edit, with no way back short of a
    # twenty-minute rebuild.
    if tokenizing_digest(asset) != tokenizing_digest(frozen_asset):
        problems.append(
            'the asset\'s tokenizing tables have changed since the baseline was taken. '
            'Rebuild it with build_baseline.py -- the digests below cannot mean '
            'anything until then.')
    elif asset_sha != baseline['asset_sha256']:
        print('note: the asset file has changed since the baseline was taken (%s -> %s), '
              'but only in fields the tokenizer never reads, so the digests below still '
              'compare.' % (baseline['asset_sha256'][:12], asset_sha[:12]))
    for i, f in enumerate(FIELDS):
        buf = bytearray()
        for kd in order:
            buf += kd + rows[kd][i * 8:(i + 1) * 8]
        got = hashlib.blake2b(bytes(buf), digest_size=16).hexdigest()
        want = baseline['production_subtoken_digest'][f]
        print('%-5s %s  %s' % (f, got, 'matches' if got == want else 'DIFFERS from ' + want))
        if got != want:
            problems.append('the %s digest moved' % f)
    print('%d records, %.0fs, %d problems' % (n, time.time() - t0, len(problems)))
    for p in problems:
        print('FAIL  %s' % p)
    if any('digest moved' in p for p in problems):
        print('\nTo find out WHICH records moved, in increasing order of cost:\n'
              '  1. `python3 site/tokenizer/emit.py --check`, then diff its output '
              'against `node site/tokenizer/emit.mjs` -- 15,253 inputs including\n'
              '     12,061 real records, and it names every one that moved. Seconds.\n'
              '  2. If that passes, the change is confined to corpus records outside\n'
              '     that sample: `build_baseline.py` reclassifies all 1,343,793 against\n'
              '     the prototype and lists them. Twenty minutes.')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
