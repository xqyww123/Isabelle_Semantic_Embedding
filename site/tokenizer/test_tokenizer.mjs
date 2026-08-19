/**
 * What the vector file cannot express, on the JavaScript side.
 *
 * The 12,171 triples cover the rules; these cover the two things that are not rules:
 * that an asset whose `tokenizer_rule` this implementation does not implement is
 * refused rather than read (§5.5), and that §16.6's guard refuses each way a vector
 * file can be doctored. The Python suite makes exactly these four assertions about
 * exactly these four tampered files — §16.6 requires both implementations to reach
 * the same verdict, and a guard that fires on one side only is worse than none.
 *
 *   node test_tokenizer.mjs
 */
import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { Tokenizer } from './isabelle_tokenizer.js';
import { main } from './check_test_vectors.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const ASSET = JSON.parse(readFileSync(join(HERE, 'asset.json'), 'utf8'));

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

/** A copy of the vector directory with one thing changed. */
const tampered = (edit) => {
  const dir = mkdtempSync(join(tmpdir(), 'isasearch-vectors-'));
  for (const name of ['asset.json', 'test_vectors.jsonl', 'test_vectors.meta.json',
                      'test_vectors.history']) {
    cpSync(join(HERE, name), join(dir, name));
  }
  edit(dir);
  return dir;
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

const historyWithAnOlderLine = (dir, suffix = '') => {
  const line = readFileSync(join(dir, 'test_vectors.history'), 'utf8').trim().split('\n').pop();
  const older = line.replace(/sha256=\w+/, `sha256=${'0'.repeat(64)}`);
  writeFileSync(join(dir, 'test_vectors.history'), `${older}\n${line}${suffix}\n`, 'utf8');
};

test('the committed vectors pass the gate', () => {
  assert.equal(quiet(() => main(HERE)), 0);
});

test('an unknown tokenizer_rule is refused rather than read', () => {
  assert.throws(() => new Tokenizer({ ...ASSET, tokenizer_rule: ASSET.tokenizer_rule + 1000 }),
                /tokenizer_rule/);
});

test('the gate fails when the body and its digest disagree', () => {
  const dir = tampered((d) => {
    const body = readFileSync(join(d, 'test_vectors.jsonl'));
    writeFileSync(join(d, 'test_vectors.jsonl'),
                  Buffer.from(body.toString('utf8').replace('"sorted"', '"sortd"'), 'utf8'));
  });
  assert.equal(quiet(() => main(dir)), 1);
});

test('the gate fails when the digest moves and the count does not', () => {
  assert.equal(quiet(() => main(tampered((d) => historyWithAnOlderLine(d)))), 1);
});

test('the gate accepts a declared rule change', () => {
  const dir = tampered((d) => historyWithAnOlderLine(
    d, '  rule-change: §5.2 gained a token class'));
  assert.equal(quiet(() => main(dir)), 0);
});

test('the gate fails on a missing feature', () => {
  const dir = tampered((d) => {
    const lines = readFileSync(join(d, 'test_vectors.jsonl'), 'utf8')
      .split('\n').filter((l) => l && !l.includes('"astral_symbol"'));
    const body = Buffer.from(`${lines.join('\n')}\n`, 'utf8');
    writeFileSync(join(d, 'test_vectors.jsonl'), body);
    const meta = JSON.parse(readFileSync(join(d, 'test_vectors.meta.json'), 'utf8'));
    meta.count = lines.length;
    meta.sha256 = createHash('sha256').update(body).digest('hex');
    writeFileSync(join(d, 'test_vectors.meta.json'), JSON.stringify(meta), 'utf8');
    writeFileSync(join(d, 'test_vectors.history'),
                  `2026-08-19  count=${meta.count}  sha256=${meta.sha256}  tokenizer_rule=1\n`,
                  'utf8');
  });
  assert.equal(quiet(() => main(dir)), 1);
});

console.log(failures ? `${failures} failed` : 'all passed');
process.exit(failures ? 1 : 0);
