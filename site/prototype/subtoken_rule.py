"""The RECOMMENDED revised subtoken rule, self-contained and derived from
etc/symbols — nothing hard-coded but the six symbol names and `_` `.`."""
import re
from Isabelle_RPC_Host.unicode import get_SYMBOLS_AND_REVERSED, SUBSUP_TRANS_TABLE

_SYMS = get_SYMBOLS_AND_REVERSED()[0]

# (b) the control characters: a sub/superscript or bold marker never survives on
#     its own, or it would sit between two subtokens and break their adjacency.
CONTROL_SEPARATORS = ''.join(_SYMS[s] for s in (
    r'\<^sub>', r'\<^sup>', r'\<^bsub>', r'\<^esub>', r'\<^bsup>', r'\<^esup>',
    r'\<^bold>'))                                   # ⇩ ⇧ ⇘ ⇙ ⇗ ⇖ ❙

# (c) the rendered characters the folding produces from a ⇩ or ⇧ marker.
RENDERED_SEPARATORS = ''.join(sorted(
    {v for k, v in SUBSUP_TRANS_TABLE.items() if k[0] in CONTROL_SEPARATORS[:2]}))

# (a) + (b) + (c)
SUBTOK_SPLIT = re.compile('[' + re.escape('_.' + CONTROL_SEPARATORS + RENDERED_SEPARATORS) + ']+')
_RENDERED = frozenset(RENDERED_SEPARATORS)


def subtokens(toks):
    """Split each token on the separator class and drop the empty fragments.
    A token that yields no fragment disappears — unless every one of its
    characters is a rendered sub/superscript, in which case it survives whole."""
    out = []
    for t in toks:
        parts = [p for p in SUBTOK_SPLIT.split(t) if p]
        if parts:
            out.extend(parts)
        elif t and all(c in _RENDERED for c in t):
            out.append(t)
    return out


if __name__ == '__main__':
    import os, sys
    sys.path.insert(0, '/home/qiyuan/Current/MLML/contrib/Isabelle_RPC')
    os.environ.setdefault('ISABELLE_HOME', '/home/qiyuan/Current/MLML/contrib/Isabelle2025-2')
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from tokenize_prototype import tokenize
    print("CONTROL_SEPARATORS  (%d) %s" % (len(CONTROL_SEPARATORS), CONTROL_SEPARATORS))
    print("RENDERED_SEPARATORS (%d) %s" % (len(RENDERED_SEPARATORS), RENDERED_SEPARATORS))
    print("class size          %d characters" % (2 + len(CONTROL_SEPARATORS) + len(RENDERED_SEPARATORS)))
    for s in ['sorted_wrt R ?xs', r'?F\<^sub>o ?Obj\<^sub>A', 'Kelly_1_39 ?C ?T ?a',
              'Stirling_Formula.c = ln (2*pi)/2', 'f x + y', 'x y', '_wrt', 'F',
              r'\<Longrightarrow>', '::', '-->', r'x\<^sub>i + y\<^sup>T',
              r'f\<^bsub>i\<^esub> = g', r'\<^bold>x \<^bold>(', r'[x]\<^sup>c\<^sup>e']:
        t = tokenize(s)
        print("  %-36s tokens=%-42s subtokens=%s" % (repr(s), t, subtokens(t)))
