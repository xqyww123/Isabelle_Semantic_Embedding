/**
 * What the committed inputs cannot express, on the JavaScript side.
 *
 * The 15,253 inputs prove that this port agrees with the Python one, because both
 * hash their output to the same committed number. They cannot prove that either port
 * reads the asset rather than asking JavaScript, because Python's `isalpha()` and
 * JavaScript's `\p{L}` agree on every character the corpus contains. `toy_asset.json`
 * proves that, by classifying ordinary characters contrary to every built-in.
 *
 *   node test_tokenizer.mjs
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { Tokenizer } from './isabelle_tokenizer.js';
import { check } from './emit.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const read = (name) => JSON.parse(readFileSync(join(HERE, name), 'utf8'));

let failures = 0;
const test = (name, body) => {
  try {
    body();
    console.log(`ok    ${name}`);
  } catch (err) {
    failures += 1;
    console.log(`FAIL  ${name}\n      ${err.message.split('\n')[0]}`);
  }
};

const quiet = (fn) => {
  const log = console.log;
  console.log = () => {};
  try {
    return fn();
  } finally {
    console.log = log;
  }
};

test('this port reproduces the committed digest', () => {
  assert.equal(quiet(() => check(HERE)), 0);
});

test('the asset is the only source', () => {
  const toy = read('toy_asset.json');
  const tok = new Tokenizer(toy.asset);
  for (const c of toy.cases) {
    assert.deepEqual(tok.run(c.input), c.subtokens, `${JSON.stringify(c.input)}: ${c.why}`);
  }
});

test('the toy asset contradicts the language in both directions', () => {
  // If it ever stops disagreeing with JavaScript, it stops proving anything.
  const toy = read('toy_asset.json').asset;
  const chars = (ranges) => ranges.flatMap(([lo, hi]) =>
    Array.from({ length: hi - lo + 1 }, (_, i) => String.fromCodePoint(lo + i)));
  assert.ok(chars(toy.letters).some((c) => !/\p{L}/u.test(c)));   // a letter \p{L} denies
  assert.ok(chars(toy.digits).some((c) => /\p{L}/u.test(c)));     // a digit it calls a letter
  assert.ok(chars(toy.spaces).some((c) => !/\s/u.test(c)));       // whitespace \s denies
  assert.ok(!chars(toy.spaces).includes(' '));                    // and the real space is not one
});

test('an unknown tokenizer_rule is refused rather than read', () => {
  const asset = read('asset.json');
  assert.throws(() => new Tokenizer({ ...asset, tokenizer_rule: asset.tokenizer_rule + 1000 }),
                /tokenizer_rule/);
});

test('unsorted code-point ranges are refused', () => {
  // Membership is a parity test over the range boundaries, so unsorted or overlapping
  // ranges do not raise on their own — they answer wrongly for every character.
  const asset = read('asset.json');
  assert.throws(() => new Tokenizer({ ...asset, letters: [[97, 98], [55, 55]] }),
                /ascending/);
});

test('a token with very many separators does not blow the stack', () => {
  // `subtokens` once spread one argument per part into `push`, which V8 caps at about
  // 125,000. `_` is a quasi-letter, so `a_a_a…` is ONE token and `parts` is unbounded.
  // No corpus record comes near it and D29 caps a query at 8,000 characters, so this
  // is robustness rather than a live defect -- but it is one line to be sure of.
  const tok = new Tokenizer(read('asset.json'));
  assert.equal(tok.run('a_'.repeat(150000)).length, 150000);
});

console.log(failures ? `${failures} failed` : 'all passed');
process.exit(failures ? 1 : 0);
