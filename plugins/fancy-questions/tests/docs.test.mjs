import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { check, KINDS } from '../scripts/lint.mjs';
const root = new URL('..', import.meta.url).pathname;
const ex = join(root, 'skills/build/examples/minimal');
const page = JSON.parse(readFileSync(join(ex, 'page.json'), 'utf8'));
const md = readFileSync(join(root, 'skills/build/reference/visuals.md'), 'utf8');
const blocks = [...md.matchAll(/```json\n([\s\S]*?)```/g)].map(m => JSON.parse(m[1]));

test('every visual kind has a documented example', () => {
  assert.deepEqual([...new Set(blocks.map(b => b.kind))].sort(), [...KINDS].filter(k => k !== 'stack').sort());
});
test('every example in visuals.md passes lint', () => {
  blocks.forEach((visual, i) => {
    const c = JSON.parse(readFileSync(join(ex, 'cards/01-money.json'), 'utf8'))[0];
    c.visual = visual; c.id = 'v' + i;
    const r = check(page, [c]);
    assert.deepEqual(r.errors, [], `${visual.kind}: ${r.errors.join('; ')}`);
  });
});
