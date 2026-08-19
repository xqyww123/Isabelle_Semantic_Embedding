# -*- coding: utf-8 -*-
"""Freeze the prototype's tokenization of the whole corpus, once, as a stamped file.

Why this exists. §16.3 step 1 is accepted by comparing the production tokenizer
against `site/prototype/`, and the prototype reads a **live** symbol table through a
**live** `Isabelle_RPC_Host` import. So the target of that comparison moves whenever
anything underneath moves, and "the production tokenizer agrees with the prototype"
is a claim about the day it was run rather than a fact anyone can re-check. Freezing
the prototype's output turns "which machine, which symbol table, which day" from an
assumption into a stamped fact — the same reason D45 gives for stamping the asset.

What it writes, into this directory:

  asset.json          the exact asset the run used, so the comparison is self-contained
  baseline.json       provenance, whole-corpus digests, the counts, and every record
                      that is neither a pure refinement nor a pure merge, in full
  baseline.classes.zst  one byte per record per change per field, in the same key
                      order the digests use, so a later run can say *which* record
                      moved and not merely that one did

Run it with the semantic DB in the state `baseline.json` names — check that digest
first, and re-sync rather than measure if it does not match.
"""
import hashlib
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, '..')))               # the prototype
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, '..', '..', '..')))   # the package

import zstandard

from Isabelle_Semantic_Embedding.isabelle_tokenizer import Tokenizer
from Isabelle_Semantic_Embedding.semantics import Semantic_DB
from Isabelle_Semantic_Embedding import tokenizer_asset
import subtoken_rule
import tokenize_prototype as P
from Isabelle_RPC_Host import unicode as unicode_module


def _git_head(repo):
    done = subprocess.run(['git', '-C', repo, 'rev-parse', '--short', 'HEAD'],
                          capture_output=True, text=True)
    return done.stdout.strip() or None


def _sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def provenance():
    """Everything the run's output depends on that is not the store or the asset.

    Taken BEFORE the pass, never after: the pass is twenty minutes long and this is a
    shared working tree, so a revision read at the end can name a commit that landed
    while it ran. The file digests are the load-bearing half — they hold whether or
    not the change was committed."""
    rpc = os.path.dirname(os.path.dirname(os.path.abspath(unicode_module.__file__)))
    files = {
        'Isabelle_RPC_Host/unicode.py': os.path.join(rpc, 'Isabelle_RPC_Host', 'unicode.py'),
        'Isabelle_RPC_Host/position.py': os.path.join(rpc, 'Isabelle_RPC_Host', 'position.py'),
        'site/prototype/tokenize_prototype.py': os.path.abspath(P.__file__),
        'site/prototype/subtoken_rule.py': os.path.abspath(subtoken_rule.__file__),
    }
    return {'isabelle_rpc_commit': _git_head(rpc),
            'sha256': {k: _sha256(v) for k, v in sorted(files.items())}}

STORE_DIGEST = 'a2dbbb874fe178867dd07bc05901fc96'   # §3's preamble

# The five rules. `old` is the prototype; `new` is what ships; the other three exist
# only so that a difference can be attributed to one decision rather than counted.
#   mid        production with every digit barred from a numeric run — how digits
#              behaved before §5.2's numeric class, so old-against-mid isolates D43
#              and mid-against-new isolates the numeric class.
#   unqualified  production with *no* digit barred, i.e. the plain "maximal run of
#              digits" §5.2 rejected for losing content.
#   digit_only  production with *digit* read as `isdigit()` alone rather than
#              `isdigit() or isnumeric()` — §5.2 claims the two readings agree on
#              every record.
CLASSES = ('same', 'refinement', 'merge', 'mixed', 'content')
FIELDS = ('expr', 'name')


def _all_digits(asset):
    return ''.join(chr(cp) for lo, hi in asset['digits'] for cp in range(lo, hi + 1))


def _variants(asset):
    mid = dict(asset, rendered_digits=_all_digits(asset))
    unqualified = dict(asset, rendered_digits='')
    digit_only = dict(asset, digits=tokenizer_asset._ranges(str.isdigit))
    return (Tokenizer(asset), Tokenizer(mid), Tokenizer(unqualified), Tokenizer(digit_only))


def bounds(arr):
    out, at = {0}, 0
    for t in arr:
        at += len(t)
        out.add(at)
    return out


def classify(a, b):
    if a == b:
        return 0                                  # same
    if ''.join(a) != ''.join(b):
        return 4                                  # content: a character was lost or gained
    ba, bb = bounds(a), bounds(b)
    if ba <= bb:
        return 1                                  # refinement: every old subtoken kept or split
    if bb <= ba:
        return 2                                  # merge: adjacent old subtokens joined
    return 3                                      # mixed: some old subtoken neither kept nor split


def main():
    stamp = provenance()
    asset = tokenizer_asset.build_asset()
    asset_text = json.dumps(asset, ensure_ascii=False, sort_keys=True, indent=1) + '\n'
    with open(os.path.join(_HERE, 'asset.json'), 'w', encoding='utf-8') as f:
        f.write(asset_text)

    new, mid, unqualified, digit_only = _variants(asset)
    rendered = frozenset(asset['rendered_subsup'])

    def old(s):
        return subtoken_rule.subtokens(P.tokenize(s))

    rows = {}                       # key digest -> per-field digests, for the whole-corpus digest
    classes = {}                    # key digest -> the four classification bytes
    count = {f: 0 for f in FIELDS}
    tally = {f: {'d43': [0] * 5, 'num': [0] * 5, 'all': [0] * 5,
                 'unqualified': [0] * 5, 'digit_only': [0] * 5, 'step3': 0}
             for f in FIELDS}
    exceptions = {f: [] for f in FIELDS}
    # §5.4's fallback clause, and §5.2's astral note, over the same pass.
    fallback_records, fallback_tokens = 0, {}
    astral = 0
    t0, n = time.time(), 0

    for key, rec in Semantic_DB.iter_entity_records():
        kd = hashlib.blake2b(key, digest_size=8).digest()
        digests, cls = [], []
        for f in FIELDS:
            s = getattr(rec, f)
            if not s:
                digests.append(b'\0' * 8)
                cls += [0, 0]
                continue
            t = tally[f]
            count[f] += 1
            if new.normalize(s) != s:
                t['step3'] += 1
            o, m, w = old(s), mid(s), new(s)
            c43, cnum, call = classify(o, m), classify(m, w), classify(o, w)
            t['d43'][c43] += 1
            t['num'][cnum] += 1
            t['all'][call] += 1
            t['unqualified'][classify(w, unqualified(s))] += 1
            t['digit_only'][classify(w, digit_only(s))] += 1
            if call in (3, 4) and len(exceptions[f]) < 64:
                exceptions[f].append({'name': rec.name, 'field': f,
                                      'd43': CLASSES[c43], 'numeric': CLASSES[cnum],
                                      'prototype': o, 'production': w})
            digests.append(hashlib.blake2b('\0'.join(w).encode('utf-8'), digest_size=8).digest())
            cls += [c43, cnum]
            if f == 'expr':
                if any(ord(c) > 0xFFFF for c in s):
                    astral += 1
                kept = [tok for tok in new.tokenize(s)
                        if tok and all(c in rendered for c in tok)]
                if kept:
                    fallback_records += 1
                    for tok in kept:
                        fallback_tokens[tok] = fallback_tokens.get(tok, 0) + 1
        rows[kd] = b''.join(digests)
        classes[kd] = bytes(cls)
        n += 1
        if n % 50000 == 0:
            sys.stderr.write('%d records, %.0fs\n' % (n, time.time() - t0))
            sys.stderr.flush()

    order = sorted(rows)
    per_field = {}
    for i, f in enumerate(FIELDS):
        buf = bytearray()
        for kd in order:
            buf += kd + rows[kd][i * 8:(i + 1) * 8]
        per_field[f] = hashlib.blake2b(bytes(buf), digest_size=16).hexdigest()

    blob = bytearray()
    for kd in order:
        blob += classes[kd]
    packed = zstandard.ZstdCompressor(level=19).compress(bytes(blob))
    with open(os.path.join(_HERE, 'baseline.classes.zst'), 'wb') as f:
        f.write(packed)

    def named(d):
        return dict(zip(CLASSES, d))

    baseline = {
        'generated': time.strftime('%Y-%m-%d'),
        'store_digest': STORE_DIGEST,
        'records': n,
        'records_with': count,
        'asset_sha256': hashlib.sha256(asset_text.encode('utf-8')).hexdigest(),
        'asset_tokenizer_rule': asset['tokenizer_rule'],
        'symbol_files': asset['symbol_files'],
        'unicode_version': asset['unicode_version'],
        'provenance': stamp,
        'production_subtoken_digest': per_field,
        'classes_order': list(CLASSES),
        'classes_layout': 'per record, in ascending key-digest order: '
                          'expr D43, expr numeric, name D43, name numeric',
        'classes_zst_sha256': hashlib.sha256(packed).hexdigest(),
        'tally': {f: {k: (named(v) if isinstance(v, list) else v)
                      for k, v in tally[f].items()} for f in FIELDS},
        'fallback_clause': {
            'records_with_a_token_of_only_rendered_subsup': fallback_records,
            'distinct_tokens': len(fallback_tokens),
            'occurrences_of_superscript_two': fallback_tokens.get('²', 0),
            'occurrences_of_subscript_one': fallback_tokens.get('₁', 0),
        },
        'expressions_with_an_astral_character': astral,
        'exceptions': exceptions,
        'seconds': round(time.time() - t0),
    }
    with open(os.path.join(_HERE, 'baseline.json'), 'w', encoding='utf-8') as f:
        json.dump(baseline, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')
    print(json.dumps({k: v for k, v in baseline.items() if k != 'exceptions'},
                     ensure_ascii=False, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
