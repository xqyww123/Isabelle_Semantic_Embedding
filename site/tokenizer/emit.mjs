/**
 * Tokenize `inputs.jsonl` with the production JavaScript implementation and check the
 * result against the one committed digest (§16.6) — the same number `emit.py` checks.
 *
 * There is no committed expectations file. An expectations file is a recording of what
 * the code currently does, so it can always be re-recorded to agree with a broken
 * tokenizer; a digest of the output cannot be talked into agreeing with anything. If
 * the two implementations diverge, exactly one digest moves. If a rule changes, both
 * move — and that is the signal, because it is what catches a rule change that forgot
 * to bump `tokenizer_rule`.
 *
 *   node emit.mjs            write the output to stdout, for diffing against emit.py
 *   node emit.mjs --check    recompute and compare with expected.json
 *
 * `--update` is deliberately absent: `expected.json` is written from the Python side,
 * which is the one that builds the index, and this side only ever agrees or fails.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { Tokenizer } from './isabelle_tokenizer.js';

const HERE = dirname(fileURLToPath(import.meta.url));

// JSON escapes every character below U+0020 but leaves U+0085, U+2028 and U+2029 raw,
// and all three terminate lines for Python's str.splitlines and for other readers.
// Escaping them keeps "split on LF" the only reading of either file.
const LINE_TERMINATORS = [['\u0085', '\\u0085'], ['\u2028', '\\u2028'],
                          ['\u2029', '\\u2029']];

const oneLine = (text) =>
  LINE_TERMINATORS.reduce((s, [raw, escaped]) => s.replaceAll(raw, escaped), text);

const sha256 = (data) => createHash('sha256').update(data).digest('hex');

export function emit(directory = HERE) {
  const assetText = readFileSync(join(directory, 'asset.json'), 'utf8');
  const inputsBody = readFileSync(join(directory, 'inputs.jsonl'));
  const asset = JSON.parse(assetText);
  const tok = new Tokenizer(asset);

  const lines = [];
  for (const line of inputsBody.toString('utf8').split('\n')) {
    if (!line) continue;
    const v = JSON.parse(line);
    // Key order and separators must match Python's json.dumps(..., ensure_ascii=False,
    // separators=(',',':')) byte for byte. Nothing asserts that in prose — the digest
    // asserts it, which is the point.
    lines.push(oneLine(JSON.stringify(
      { id: v.id, tokens: tok.tokenize(v.input), subtokens: tok.run(v.input) })));
  }
  const body = Buffer.from(`${lines.join('\n')}\n`, 'utf8');
  return {
    body,
    got: {
      tokenizer_rule: asset.tokenizer_rule,
      asset_sha256: sha256(Buffer.from(assetText, 'utf8')),
      inputs_sha256: sha256(inputsBody),
      inputs_count: lines.length,
      output_sha256: sha256(body),
    },
  };
}

export function check(directory = HERE) {
  const { got } = emit(directory);
  const want = JSON.parse(readFileSync(join(directory, 'expected.json'), 'utf8'));
  const problems = [];
  for (const field of ['asset_sha256', 'inputs_sha256', 'inputs_count', 'tokenizer_rule']) {
    if (got[field] !== want[field]) {
      problems.push(`${field} is ${JSON.stringify(got[field])}, `
                    + `expected.json says ${JSON.stringify(want[field])}`);
    }
  }
  if (got.output_sha256 !== want.output_sha256) {
    problems.push(
      `this implementation's output over the committed inputs hashes to `
      + `${got.output_sha256}, expected.json says ${want.output_sha256}.\n`
      + `      Either this port diverged from the Python one, or a rule changed and `
      + `expected.json was not updated. Run \`python3 emit.py > /tmp/py.out; `
      + `node emit.mjs > /tmp/js.out; diff /tmp/py.out /tmp/js.out\` — an empty diff `
      + `means the rule changed and expected.json is stale; a non-empty one names `
      + `every input the two implementations disagree on.`);
  }
  for (const p of problems) console.log(`FAIL  ${p}`);
  console.log(`${got.inputs_count} inputs, ${problems.length} problems`);
  return problems.length ? 1 : 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  if (process.argv.includes('--check')) process.exit(check());
  process.stdout.write(emit().body);
}
