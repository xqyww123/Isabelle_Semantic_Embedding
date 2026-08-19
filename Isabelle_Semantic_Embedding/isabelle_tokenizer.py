r"""The production tokenizer of §5 — the one the site export and the query path share.

Two properties make this file what it is, and both are stated as prohibitions in
§5.5 because a violation of either is silent:

* **It carries no table and no character class of its own.** Everything it
  classifies by comes from the asset (`tokenizer_asset`), so the JavaScript port
  can read the same file and cannot drift by consulting `\p{L}` where this
  consulted `isalpha`.
* **It refuses an asset whose `tokenizer_rule` it does not implement.** The
  namespace name embeds the asset's digest, so an index and its asset cannot come
  apart; this is the other half — that the *code* agrees with the file.

It differs from `site/prototype/tokenize_prototype.py`, which measures rather than
specifies, in exactly two ways: it iterates characters instead of Isabelle symbols
(D43), and it has §5.2's numeric token class, which the prototype lacks entirely.
"""
import bisect
import json
import re
import unicodedata

# The rules this file implements. An asset built by any other version is refused.
SUPPORTED_TOKENIZER_RULES = frozenset({1})

# Isabelle's own rule for what names a symbol (`Pure/General/symbol.scala`): `\<`,
# an optional `^`, a letter, then letters, digits, `_` or `'`, then `>`. Text that
# does not match is not an escape and reaches token formation as ordinary
# characters — since D43 removed the `symbol_explode` step, this is the only place
# an escape is recognised at all (§5.1 step 3a).
_ESCAPE = re.compile(r"\\<\^?[A-Za-z][A-Za-z0-9_']*>")


class _CodePointSet:
    """Membership over the inclusive [lo, hi] pairs the asset ships."""

    def __init__(self, ranges):
        self._bounds = []
        for lo, hi in ranges:
            self._bounds.append(lo)
            self._bounds.append(hi + 1)

    def __contains__(self, ch):
        return bisect.bisect_right(self._bounds, ord(ch)) % 2 == 1


class Tokenizer:
    def __init__(self, asset):
        rule = asset.get('tokenizer_rule')
        if rule not in SUPPORTED_TOKENIZER_RULES:
            raise ValueError(
                "tokenizer asset declares tokenizer_rule %r, which this implementation "
                "does not implement (it implements %s). Refusing to read its tables and "
                "apply different rules to them (\u00a75.5)."
                % (rule, sorted(SUPPORTED_TOKENIZER_RULES)))
        self.asset = asset
        self._symbols = asset['symbols']
        self._fold = asset['fold']
        # `\u21e9`, `\u21e7`, `\u2759` — read off the fold table's own keys rather
        # than named here, so a new marker in the table needs no code change.
        self._markers = frozenset(k[0] for k in self._fold)
        self._letters = _CodePointSet(asset['letters'])
        self._digits = _CodePointSet(asset['digits'])
        self._spaces = _CodePointSet(asset['spaces'])
        self._quasi = frozenset(asset['quasi_letters'])
        self._discarded = frozenset(asset['discarded'])
        self._ascii_symbolic = frozenset(asset['ascii_symbolic'])
        self._rendered = frozenset(asset['rendered_subsup'])
        self._rendered_digits = frozenset(asset['rendered_digits'])
        self._separator_split = re.compile(
            '[' + re.escape(asset['separators']) + ']+')

    # ---- §5.1, steps 1 to 3 -------------------------------------------------

    def normalize(self, s):
        """Everything before token formation: NFC, U+007F, and the two symbol passes."""
        s = unicodedata.normalize('NFC', s).replace('\x7f', ' ')
        s = _ESCAPE.sub(lambda m: self._symbols.get(m.group(0), m.group(0)), s)
        return self._fold_markers(s)

    def _fold_markers(self, s):
        """Step 3b: left to right, two characters at a time, non-overlapping.

        A marker whose next character is itself a marker consumes it: the pair is
        not in the fold table, neither character folds, and the second marker
        cannot begin a pair of its own. So `x⇩1` gives `x₁`, `x⇩⇩1` stays as it is,
        and `x⇩⇩⇩1` gives `x⇩⇩₁`. Rare enough that the user ruled it not worth
        fixing, and specified anyway because a port folding each marker separately
        would diverge here and nowhere else.
        """
        out, i, n = [], 0, len(s)
        while i < n:
            pair = s[i:i + 2]
            folded = self._fold.get(pair) if len(pair) == 2 else None
            if folded is not None:
                out.append(folded)
                i += 2
            elif len(pair) == 2 and pair[0] in self._markers:
                out.append(pair)
                i += 2
            else:
                out.append(s[i])
                i += 1
        return ''.join(out)

    # ---- §5.2 ---------------------------------------------------------------

    def tokenize(self, s):
        out, cur, mode = [], [], None

        def flush():
            nonlocal mode
            if cur:
                out.append(''.join(cur))
                del cur[:]
            mode = None

        for ch in self.normalize(s):
            if ch in self._spaces or ch in self._discarded:
                flush()
            elif (ch in self._letters
                  or (mode == 'id' and (ch in self._digits or ch in self._quasi))):
                # A digit continues an identifier in preference to starting a
                # numeral: `x1` is one token, not two.
                if mode != 'id':
                    flush()
                    mode = 'id'
                cur.append(ch)
            elif ch in self._digits and ch not in self._rendered_digits:
                # A rendered sub/superscript digit is decoration, not content, so
                # it falls through to *anything else* and §5.4's fallback keeps it.
                if mode != 'num':
                    flush()
                    mode = 'num'
                cur.append(ch)
            elif ch in self._ascii_symbolic:
                if mode != 'sym':
                    flush()
                    mode = 'sym'
                cur.append(ch)
            else:
                flush()
                out.append(ch)
        flush()
        return out

    # ---- §5.4 ---------------------------------------------------------------

    def subtokens(self, tokens):
        out = []
        for t in tokens:
            parts = [p for p in self._separator_split.split(t) if p]
            if parts:
                out.extend(parts)
            elif t and all(c in self._rendered for c in t):
                # A token made entirely of rendered sub/superscripts is real
                # content — `ᶜᵉ`, `ₚₜᵣ`, `²` — and would otherwise vanish. Keeping
                # any token that splits to nothing instead would rescue `_` too and
                # break the query `_wrt`.
                out.append(t)
        return out

    def __call__(self, s):
        return self.subtokens(self.tokenize(s))


def load(path):
    with open(path, encoding='utf-8') as f:
        return Tokenizer(json.load(f))
