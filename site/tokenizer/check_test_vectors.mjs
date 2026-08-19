/**
 * §16.6's gate, the JavaScript half. It makes the same assertions as
 * `check_test_vectors.py` — deliberately, because the point of the gate is that both
 * implementations reach the same verdict about the same file, and a checker that
 * checked something else on this side would hide exactly the drift it exists to find.
 *
 *   node check_test_vectors.mjs [directory]
 *
 * Node is used only for reading files and exiting; the tokenizer itself imports
 * nothing and runs unchanged in a Worker.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { Tokenizer } from './isabelle_tokenizer.js';

const HERE = dirname(fileURLToPath(import.meta.url));

// The features §16.5 requires by name. A vector file missing any of them is not a
// gate, whatever its size.
const REQUIRED_FEATURES = [
  '16.2', '5.3', 'nfd', 'u007f', 'subsup_without_a_fold_entry', 'separator_only',
  'boundary_character', 'fallback_clause', 'private_use_escape',
  'escape_against_ascii_symbolic', 'astral_symbol', 'adjacent_fold_markers',
  'escape_scanning', 'numeric_class', 'empty', 'real_expression', 'real_name',
];

// U+0085, U+2028 and U+2029 terminate lines for Python's str.splitlines and for a
// good many other readers, and real Isabelle text contains them; the generator
// escapes them, and this asserts it did.
const STRAY_LINE_BREAK = /[\u0085\u2028\u2029\r]/;

const sha256 = (buffer) => createHash('sha256').update(buffer).digest('hex');

const parseHistory = (text) => text.split('\n')
  .map((line) => line.trim())
  .filter((line) => line && !line.startsWith('#'))
  .map((line) => {
    const fields = Object.fromEntries(line.split(/\s+/)
      .filter((part) => part.includes('='))
      .map((part) => [part.slice(0, part.indexOf('=')), part.slice(part.indexOf('=') + 1)]));
    return {
      count: Number(fields.count),
      sha256: fields.sha256,
      ruleChange: line.includes('rule-change:'),
      line,
    };
  });

const sameArray = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

export function main(directory = HERE) {
  const problems = [];
  const meta = JSON.parse(readFileSync(join(directory, 'test_vectors.meta.json'), 'utf8'));
  const body = readFileSync(join(directory, 'test_vectors.jsonl'));

  const digest = sha256(body);
  if (digest !== meta.sha256) {
    problems.push(`the .jsonl hashes to ${digest}, the meta says ${meta.sha256}`);
  }

  const text = body.toString('utf8');
  const vectors = text.split('\n').filter((line) => line).map((line) => JSON.parse(line));
  if (STRAY_LINE_BREAK.test(text)) {
    problems.push('a line contains a character some line readers treat as a break');
  }
  if (vectors.length !== meta.count) {
    problems.push(`${vectors.length} lines, the meta says ${meta.count}`);
  }

  const assetText = readFileSync(join(directory, 'asset.json'), 'utf8');
  const assetSha = sha256(Buffer.from(assetText, 'utf8'));
  if (assetSha !== meta.asset_sha256) {
    problems.push(`the asset beside the vectors hashes to ${assetSha}, `
                  + `the meta says ${meta.asset_sha256}`);
  }
  const tokenizer = new Tokenizer(JSON.parse(assetText));

  let mismatched = 0;
  for (const v of vectors) {
    if (!sameArray(tokenizer.tokenize(v.input), v.tokens)
        || !sameArray(tokenizer.run(v.input), v.subtokens)) {
      mismatched += 1;
      if (mismatched <= 5) {
        problems.push(`${v.id}: ${JSON.stringify(v.input)} -> `
          + `${JSON.stringify(tokenizer.tokenize(v.input))} / `
          + `${JSON.stringify(tokenizer.run(v.input))}, expected `
          + `${JSON.stringify(v.tokens)} / ${JSON.stringify(v.subtokens)}`);
      }
    }
  }
  if (mismatched > 5) problems.push(`... and ${mismatched - 5} more mismatches`);

  const history = parseHistory(readFileSync(join(directory, 'test_vectors.history'), 'utf8'));
  if (!history.length) {
    problems.push('the history is empty');
  } else {
    const last = history[history.length - 1];
    if (last.count !== meta.count || last.sha256 !== meta.sha256) {
      problems.push(`the newest history line does not describe this file: ${last.line}`);
    }
    if (history.length >= 2) {
      const prev = history[history.length - 2];
      if (last.sha256 !== prev.sha256 && last.count === prev.count && !last.ruleChange) {
        problems.push('the digest changed while the count did not, and the history '
                      + `line does not say a rule changed: ${last.line}`);
      }
    }
  }

  const present = new Set(vectors.map((v) => v.feature));
  for (const feature of REQUIRED_FEATURES) {
    if (!present.has(feature)) problems.push(`no vector covers the feature '${feature}'`);
  }

  for (const p of problems) console.log(`FAIL  ${p}`);
  console.log(`${vectors.length} vectors, ${present.size} features, ${problems.length} problems`);
  return problems.length ? 1 : 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv[2]));
}
