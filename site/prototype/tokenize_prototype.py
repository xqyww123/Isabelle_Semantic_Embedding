"""Revised tokenizer: ONE subtoken array, matched with ContainsTokenSequence.

Copy of isa_tok_final.py with subtokens() narrowed per the revised rule:
keep operator tokens, drop only the separators themselves.
tokenize() is byte-identical to isa_tok_final.tokenize.
"""
import os, re, sys, unicodedata
sys.path.insert(0, '/home/qiyuan/Current/MLML/contrib/Isabelle_RPC')
os.environ.setdefault('ISABELLE_HOME', '/home/qiyuan/Current/MLML/contrib/Isabelle2025-2')
from Isabelle_RPC_Host.unicode import unicode_of_ascii, get_SYMBOLS_AND_REVERSED, SUBSUP_TRANS_TABLE
from Isabelle_RPC_Host.position import symbol_explode

_SYMS, _REV, _TRANS, _LETTER_SYMS = get_SYMBOLS_AND_REVERSED()
_LETTER_CHARS = frozenset(_SYMS[s] for s in _LETTER_SYMS if s in _SYMS)

QUASI     = frozenset("_'")
DROP      = frozenset("?")
ASCII_SYM = frozenset("!#$%&*+-/:<=>@\\^|~")

# ---- the separator class, derived from etc/symbols, not hand-written ----------
# the control symbols that introduce a sub/superscript
SUBSUP_CONTROL = ''.join(_SYMS[s] for s in
                         ('\\<^sub>', '\\<^sup>', '\\<^bsub>', '\\<^esub>',
                          '\\<^bsup>', '\\<^esup>'))          # ⇩⇧⇘⇙⇗⇖
BOLD_CONTROL   = _SYMS['\\<^bold>']                            # ❙
# the rendered characters the SUBSUP folding produces from ⇩ / ⇧
SUBSUP_RENDERED = ''.join(sorted({v for k, v in SUBSUP_TRANS_TABLE.items()
                                  if k[0] in SUBSUP_CONTROL[:2]}))

OLD_CLASS  = "_.⁰-₟²³¹"                                        # isa_tok_final.py
MIN_CLASS  = OLD_CLASS + SUBSUP_CONTROL                        # variant A
FULL_CLASS = "_." + SUBSUP_CONTROL + BOLD_CONTROL + re.escape(SUBSUP_RENDERED)  # variant B

OLD_SPLIT  = re.compile("[" + OLD_CLASS + "]+")
MIN_SPLIT  = re.compile("[" + MIN_CLASS + "]+")
FULL_SPLIT = re.compile("[" + FULL_CLASS + "]+")


def _is_letter(sym):
    return (sym.isalpha() or sym in _LETTER_CHARS) if len(sym) == 1 else sym in _LETTER_SYMS


def _is_digit(sym):
    return len(sym) == 1 and (sym.isdigit() or sym.isnumeric())


def tokenize(s):
    s = unicodedata.normalize('NFC', s).replace('\x7f', ' ')
    out, cur, mode = [], [], None
    def flush():
        nonlocal cur, mode
        if cur: out.append(''.join(cur)); cur, mode = [], None
    for sym in symbol_explode(unicode_of_ascii(s)):
        if sym.isspace() or sym in DROP:
            flush(); continue
        if _is_letter(sym) or (mode == 'id' and (_is_digit(sym) or sym in QUASI)):
            if mode != 'id': flush(); mode = 'id'
            cur.append(sym); continue
        if len(sym) == 1 and sym in ASCII_SYM:
            if mode != 'sym': flush(); mode = 'sym'
            cur.append(sym); continue
        flush(); out.append(sym)
    flush()
    return out


def subtokens_old(toks):
    """§5.4 as implemented today: split, then drop every fragment with no alnum."""
    out = []
    for t in toks:
        parts = [p for p in OLD_SPLIT.split(t) if p]
        out.extend(parts if parts else [t])
    return [p for p in out if any(c.isalnum() for c in p)]


def _subtokens_revised(toks, split):
    """Revised rule: split on the separator class; keep everything that survives,
    including operator tokens; a token that is nothing but separators disappears."""
    out = []
    for t in toks:
        out.extend(p for p in split.split(t) if p)
    return out


def subtokens_rev_min(toks):
    return _subtokens_revised(toks, MIN_SPLIT)


def subtokens_rev(toks):
    return _subtokens_revised(toks, FULL_SPLIT)


if __name__ == '__main__':
    print("SUBSUP_CONTROL  :", SUBSUP_CONTROL, [hex(ord(c)) for c in SUBSUP_CONTROL])
    print("BOLD_CONTROL    :", BOLD_CONTROL, hex(ord(BOLD_CONTROL)))
    print("SUBSUP_RENDERED : %d chars: %s" % (len(SUBSUP_RENDERED), SUBSUP_RENDERED))
    for s in ['sorted_wrt R ?xs', '?F\\<^sub>o ?Obj\\<^sub>A', 'Kelly_1_39 ?C ?T ?\\<alpha>',
              'Stirling_Formula.c = ln (2*pi)/2', 'f x + y', 'x y', '_wrt', 'F',
              '\\<Longrightarrow>', '::', '-->', 'x + y', 'x\\<^sub>i + y\\<^sup>T',
              'f\\<^bsub>i\\<^esub> = g', '\\<^bold>x \\<^bold>(']:
        t = tokenize(s)
        print("%-34s tok=%-52s old=%-34s min=%-34s full=%s"
              % (repr(s), t, subtokens_old(t), subtokens_rev_min(t), subtokens_rev(t)))
