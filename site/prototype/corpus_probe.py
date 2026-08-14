"""Count how many entities a syntactic condition would match, on the real corpus.

This is the harness behind every match count quoted in SEMANTIC_SEARCH_SITE_PLAN.md
§15.1 and site/COPY.md. It reproduces D21's semantics exactly: tokenize, take
subtokens, and require the condition's subtokens to appear as an adjacent ordered
run in the document's subtoken array — which is what turbopuffer's
`ContainsTokenSequence` does (§6.3).

    python3 corpus_probe.py '?n + ?m = ?m + ?n' '?a + ?b = ?b + ?a'
    python3 corpus_probe.py --field name 'Path_Connected'

One full pass over ~1.36 M records costs about 60 s plus ~10 s per extra
condition. The substring pre-filter is sound: every subtoken of a matching
document is a substring of its normalised text, so nothing that could match is
skipped.
"""
import argparse, os, sys, time, unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, '..', '..')))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, '..', '..', '..', 'Isabelle_RPC')))
os.environ.setdefault('ISABELLE_HOME', os.path.normpath(
    os.path.join(_HERE, '..', '..', '..', 'Isabelle2025-2')))

import lmdb
from Isabelle_RPC_Host.unicode import unicode_of_ascii
from Isabelle_Semantic_Embedding.semantics import _Semantic_DB
from tokenize_prototype import tokenize
from subtoken_rule import subtokens

DEFAULT_DB = os.path.expanduser('~/.cache/Isabelle_Semantic_Embedding/semantics.lmdb')


def contains_seq(haystack, needle):
    """turbopuffer ContainsTokenSequence: adjacent, ordered, anywhere."""
    n = len(needle)
    if n == 0:
        return False
    first = needle[0]
    for i in range(len(haystack) - n + 1):
        if haystack[i] == first and haystack[i:i + n] == needle:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('conditions', nargs='+')
    ap.add_argument('--field', default='expr', choices=('expr', 'name'))
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--examples', type=int, default=4)
    args = ap.parse_args()

    conds = [(c, subtokens(tokenize(c))) for c in args.conditions]
    for c, st in conds:
        print('%-34s -> %s' % (repr(c), st))
    print()

    env = lmdb.open(args.db, readonly=True, lock=False)
    hits = {c: [] for c, _ in conds}
    counts = {c: 0 for c, _ in conds}
    total = 0
    t0 = time.time()
    with env.begin() as txn:
        for k, v in txn.cursor():
            if len(k) < 17:
                continue
            try:
                r = _Semantic_DB._decode(v)
            except Exception:
                continue
            text = getattr(r, args.field, None)
            if not isinstance(text, str) or not text:
                continue
            total += 1
            norm = unicode_of_ascii(
                unicodedata.normalize('NFC', text).replace('\x7f', ' '))
            cached = None
            for c, st in conds:
                if not all(p in norm for p in st):
                    continue
                if cached is None:
                    cached = subtokens(tokenize(text))
                if contains_seq(cached, st):
                    counts[c] += 1
                    if len(hits[c]) < args.examples:
                        hits[c].append(getattr(r, 'name', '?'))
    env.close()

    print('scanned %d records with a %s in %.0f s\n' % (total, args.field, time.time() - t0))
    for c, st in conds:
        print('%-34s %7d  %s' % (repr(c), counts[c], hits[c]))


if __name__ == '__main__':
    main()
