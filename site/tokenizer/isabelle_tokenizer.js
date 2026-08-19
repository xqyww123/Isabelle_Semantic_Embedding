/**
 * The JavaScript half of §5's tokenizer — the one the Worker runs against a query,
 * where the Python half (`Isabelle_Semantic_Embedding/isabelle_tokenizer.py`) built
 * the index. They must agree byte for byte or the site returns silently wrong
 * results with no error anywhere, so this file is written to be read beside that one:
 * same order, same names, same algorithm, not a second reading of the same prose.
 *
 * Two prohibitions from §5.5, both of which fail silently when broken:
 *
 * - **No table and no character class of its own.** Everything it classifies by comes
 *   from the asset. In particular it never asks JavaScript: `\p{L}` is not
 *   `isalpha()` (145,672 code points against 136,104 under Unicode 15), `\p{Nd}`
 *   rejects `²` where `isdigit()` accepts it, and `\s` disagrees with `isspace()` in
 *   both directions — `\s` takes U+FEFF, `isspace()` takes U+001C to U+001F and
 *   U+0085. All four appear in the corpus (§16.4).
 * - **It refuses an asset whose `tokenizer_rule` it does not implement**, rather than
 *   reading its tables and applying different rules to them.
 *
 * And one hazard peculiar to this side: a **character** is a Unicode code point,
 * never a UTF-16 code unit. 4.15 % of the corpus's expressions carry a character
 * above U+FFFF, so a port that indexes by code unit emits unpaired surrogates that
 * JSON transports intact and no query can ever match. Every loop here iterates code
 * points, and the fold scan works over an array of them rather than over the string.
 */

/** The rules this file implements. An asset built by any other version is refused. */
export const SUPPORTED_TOKENIZER_RULES = new Set([1]);

/**
 * Isabelle's own rule for what names a symbol (`Pure/General/symbol.scala`): `\<`, an
 * optional `^`, a letter, then letters, digits, `_` or `'`, then `>`. Text that does
 * not match is not an escape and reaches token formation as ordinary characters —
 * since D43 removed the `symbol_explode` step this is the only place an escape is
 * recognised at all (§5.1 step 3a). ASCII only, so no Unicode property is involved.
 */
const ESCAPE = /\\<\^?[A-Za-z][A-Za-z0-9_']*>/g;

/** Membership over the inclusive [lo, hi] pairs the asset ships. */
class CodePointSet {
  constructor(ranges) {
    this.bounds = [];
    for (const [lo, hi] of ranges) {
      this.bounds.push(lo, hi + 1);
    }
  }

  has(codePoint) {
    let lo = 0;
    let hi = this.bounds.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.bounds[mid] <= codePoint) lo = mid + 1;
      else hi = mid;
    }
    return (lo & 1) === 1;
  }
}

const charSet = (s) => new Set(Array.from(s));

export class Tokenizer {
  constructor(asset) {
    const rule = asset.tokenizer_rule;
    if (!SUPPORTED_TOKENIZER_RULES.has(rule)) {
      throw new Error(
        `tokenizer asset declares tokenizer_rule ${JSON.stringify(rule)}, which this ` +
        `implementation does not implement (it implements ` +
        `${[...SUPPORTED_TOKENIZER_RULES].join(', ')}). Refusing to read its tables ` +
        `and apply different rules to them (§5.5).`);
    }
    this.asset = asset;
    // Maps rather than plain objects: an asset is data from a file, and a key such as
    // `__proto__` must be a key and not a way of reaching the prototype.
    this.symbols = new Map(Object.entries(asset.symbols));
    this.fold = new Map(Object.entries(asset.fold));
    // U+21E9, U+21E7, U+2759 — read off the fold table's own keys rather than named
    // here, so a new marker in the table needs no code change.
    this.markers = new Set([...this.fold.keys()].map((k) => Array.from(k)[0]));
    this.letters = new CodePointSet(asset.letters);
    this.digits = new CodePointSet(asset.digits);
    this.spaces = new CodePointSet(asset.spaces);
    this.quasi = charSet(asset.quasi_letters);
    this.discarded = charSet(asset.discarded);
    this.asciiSymbolic = charSet(asset.ascii_symbolic);
    this.rendered = charSet(asset.rendered_subsup);
    this.renderedDigits = charSet(asset.rendered_digits);
    this.separators = charSet(asset.separators);
  }

  // ---- §5.1, steps 1 to 3 --------------------------------------------------

  /** Everything before token formation: NFC, U+007F, and the two symbol passes. */
  normalize(s) {
    const converted = s.normalize('NFC').replaceAll('\u007F', ' ')
      .replace(ESCAPE, (m) => this.symbols.get(m) ?? m);
    return this.foldMarkers(converted);
  }

  /**
   * Step 3b: left to right, two characters at a time, non-overlapping.
   *
   * A marker whose next character is itself a marker consumes it: the pair is not in
   * the fold table, neither character folds, and the second marker cannot begin a
   * pair of its own. So `x⇩1` gives `x₁`, `x⇩⇩1` stays as it is, and `x⇩⇩⇩1` gives
   * `x⇩⇩₁`. Rare enough that the user ruled it not worth fixing, and specified
   * anyway because a port folding each marker separately would diverge here and
   * nowhere else.
   */
  foldMarkers(s) {
    const chars = Array.from(s);
    const out = [];
    let i = 0;
    while (i < chars.length) {
      const pair = i + 1 < chars.length ? chars[i] + chars[i + 1] : null;
      const folded = pair === null ? undefined : this.fold.get(pair);
      if (folded !== undefined) {
        out.push(folded);
        i += 2;
      } else if (pair !== null && this.markers.has(chars[i])) {
        out.push(pair);
        i += 2;
      } else {
        out.push(chars[i]);
        i += 1;
      }
    }
    return out.join('');
  }

  // ---- §5.2 ----------------------------------------------------------------

  tokenize(s) {
    const out = [];
    let cur = [];
    let mode = null;
    const flush = () => {
      if (cur.length) {
        out.push(cur.join(''));
        cur = [];
      }
      mode = null;
    };

    for (const ch of this.normalize(s)) {
      const cp = ch.codePointAt(0);
      if (this.spaces.has(cp) || this.discarded.has(ch)) {
        flush();
      } else if (this.letters.has(cp)
                 || (mode === 'id' && (this.digits.has(cp) || this.quasi.has(ch)))) {
        // A digit continues an identifier in preference to starting a numeral:
        // `x1` is one token, not two.
        if (mode !== 'id') {
          flush();
          mode = 'id';
        }
        cur.push(ch);
      } else if (this.digits.has(cp) && !this.renderedDigits.has(ch)) {
        // A rendered sub/superscript digit is decoration, not content, so it falls
        // through to *anything else* and §5.4's fallback keeps it.
        if (mode !== 'num') {
          flush();
          mode = 'num';
        }
        cur.push(ch);
      } else if (this.asciiSymbolic.has(ch)) {
        if (mode !== 'sym') {
          flush();
          mode = 'sym';
        }
        cur.push(ch);
      } else {
        flush();
        out.push(ch);
      }
    }
    flush();
    return out;
  }

  // ---- §5.4 ----------------------------------------------------------------

  subtokens(tokens) {
    const out = [];
    for (const t of tokens) {
      // Split at every separator and drop what is empty.
      const parts = [];
      let cur = [];
      for (const ch of t) {
        if (this.separators.has(ch)) {
          if (cur.length) {
            parts.push(cur.join(''));
            cur = [];
          }
        } else {
          cur.push(ch);
        }
      }
      if (cur.length) parts.push(cur.join(''));
      if (parts.length) {
        out.push(...parts);
      } else if (t.length && Array.from(t).every((c) => this.rendered.has(c))) {
        // A token made entirely of rendered sub/superscripts is real content —
        // `ᶜᵉ`, `ₚₜᵣ`, `²` — and would otherwise vanish. Keeping any token that
        // splits to nothing instead would rescue `_` too and break the query `_wrt`.
        out.push(t);
      }
    }
    return out;
  }

  /** Subtokens, which under D21 is the only level that is indexed or queried. */
  run(s) {
    return this.subtokens(this.tokenize(s));
  }
}
