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


def main():
    baseline = json.load(open(os.path.join(_HERE, 'baseline.json'), encoding='utf-8'))
    asset = tokenizer_asset.build_asset()
    asset_text = json.dumps(asset, ensure_ascii=False, sort_keys=True, indent=1) + '\n'
    asset_sha = hashlib.sha256(asset_text.encode('utf-8')).hexdigest()
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
    if asset_sha != baseline['asset_sha256']:
        problems.append('the asset hashes to %s, the baseline was taken against %s'
                        % (asset_sha, baseline['asset_sha256']))
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
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
