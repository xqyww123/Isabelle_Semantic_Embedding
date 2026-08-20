r"""Build the tokenizer asset: the one file both implementations read (D45).

§5.5 forbids either implementation from carrying a table of its own or from asking
its language for a character class, because Python's `isalpha`/`isdigit`/`isspace`
and JavaScript's `\p{L}`/`\p{Nd}`/`\s` disagree on characters the corpus actually
contains (§16.4). So everything the tokenizer classifies by is emitted here, as
explicit code points, and `isabelle_tokenizer` reads only this.

Two emission rules are worth stating because they move work out of the consumers:

* A symbol whose code point is private-use is dropped from the table rather than
  shipped. D44 leaves such a symbol as its literal `\\<name>`, which is exactly what
  an undefined symbol does, so dropping it makes the two cases one case and spares
  the JavaScript port a private-use range check of its own.
* The three classes a consumer would otherwise derive — the 99 separators, the 90
  rendered sub/superscripts the fallback clause needs, and the 20 rendered digits
  §5.2 excludes from a numeric run — are each emitted outright. §5.4 warns that an
  implementation deriving one from another will drift the moment the fold table
  gains an entry; deriving all of them here, once, from the fold table, is that
  warning obeyed.
"""
import hashlib
import json
import os
import sys
import unicodedata

from Isabelle_RPC_Host.unicode import (SUBSUP_TRANS_TABLE, get_SYMBOL_FILES,
                                       get_SYMBOLS_AND_REVERSED, is_private_use)

# The rules of §5.1, §5.2 and §5.4 that produced this asset. Bump by hand in the
# same commit as a rule change: the namespace name embeds the asset digest, and a
# rule change that touches no table would otherwise leave the digest — and so the
# namespace — unchanged (§16.4). Both implementations refuse a version they do not
# implement (§5.5).
TOKENIZER_RULE = 1

QUASI_LETTERS = "_'"
DISCARDED = "?"                                  # D4; whitespace is discarded too
ASCII_SYMBOLIC = "!#$%&*+-/:<=>@\\^|~"           # D8

# The control symbols that must never survive alone as a subtoken (§5.4).
CONTROL_SEPARATOR_SYMBOLS = (r'\<^sub>', r'\<^sup>', r'\<^bsub>', r'\<^esub>',
                             r'\<^bsup>', r'\<^esup>', r'\<^bold>')


def _ranges(predicate):
    """The code points satisfying `predicate`, as inclusive [lo, hi] pairs."""
    out, start = [], None
    for cp in range(0x110000):
        if predicate(chr(cp)):
            if start is None:
                start = cp
        elif start is not None:
            out.append([start, cp - 1])
            start = None
    if start is not None:
        out.append([start, 0x10FFFF])
    return out


def _symbol_file_provenance():
    """What identifies each symbol file, rather than where it happened to sit.

    §5.5 requires the asset to record the files it was built from, because two
    machines can load different tables from identical code. Recording absolute paths
    satisfied the letter and not the purpose: they are machine-specific, so the only
    check anyone can make against them is equality with this machine's, and they put
    a home directory into a committed artefact. A basename and a digest identify the
    file wherever it lives, so a contributor with a differently-rooted Isabelle can
    still be told whether their table is the one the asset was built from.
    """
    out = []
    for path in get_SYMBOL_FILES():
        name = os.path.basename(os.path.dirname(path)) + '/' + os.path.basename(path)
        # ISABELLE_SYMBOLS names the user overlay whether or not it exists, so a null
        # digest is a fact about the table and not an error: it says the file was on
        # the list and contributed nothing.
        try:
            with open(path, 'rb') as f:
                digest = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            digest = None
        out.append({'name': name, 'sha256': digest})
    return out


def _is_digit(ch):
    """§5.2's *digit*. The two readings were measured to agree on every record."""
    return ch.isdigit() or ch.isnumeric()


def build_asset():
    symbols = get_SYMBOLS_AND_REVERSED()[0]
    sub, sup = symbols[r'\<^sub>'], symbols[r'\<^sup>']

    convertible, private_use = {}, []
    for name, char in symbols.items():
        if is_private_use(char):
            private_use.append(name)
        else:
            convertible[name] = char
    private_use.sort()

    controls = ''.join(symbols[s] for s in CONTROL_SEPARATOR_SYMBOLS)
    rendered = ''.join(sorted({v for k, v in SUBSUP_TRANS_TABLE.items()
                               if k[0] in (sub, sup)}))
    separators = '_.' + controls + rendered
    assert len(set(separators)) == len(separators)

    return {
        'tokenizer_rule': TOKENIZER_RULE,
        'unicode_version': unicodedata.unidata_version,
        'symbol_files': _symbol_file_provenance(),
        'symbols': convertible,
        'symbols_private_use': private_use,
        'fold': dict(SUBSUP_TRANS_TABLE),
        'letters': _ranges(str.isalpha),
        'digits': _ranges(_is_digit),
        'spaces': _ranges(str.isspace),
        'quasi_letters': QUASI_LETTERS,
        'discarded': DISCARDED,
        'ascii_symbolic': ASCII_SYMBOLIC,
        'separators': separators,
        'rendered_subsup': rendered,
        'rendered_digits': ''.join(c for c in rendered if _is_digit(c)),
    }


def serialize(asset):
    """THE asset's bytes. The namespace name carries their SHA-256 (§8.2), so the
    export and this script must serialise identically or the digest moves for no
    reason; there is one spelling of it and this is it."""
    return json.dumps(asset, ensure_ascii=False, sort_keys=True, indent=1) + '\n'


def main(argv):
    asset = build_asset()
    text = serialize(asset)
    if len(argv) > 1:
        with open(argv[1], 'w', encoding='utf-8') as f:
            f.write(text)
    else:
        sys.stdout.write(text)


if __name__ == '__main__':
    main(sys.argv)
