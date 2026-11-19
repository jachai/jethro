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
import { build } from '../scripts/qw.mjs';
test('minimal and synthetic-30 build clean under 150 KB', () => {
  for (const [d, n] of [['minimal', 2], ['synthetic-30', 30]]) {
    const r = build(join(root, 'skills/build/examples', d));
    assert.deepEqual(r.errors, [], d); assert.deepEqual(r.warnings, [], d);
    assert.equal(r.data.cards.length, n, d);
    assert.ok(Buffer.byteLength(r.html) < 150 * 1024, d);
  }
});
const skill = n => readFileSync(join(root, 'skills', n, 'SKILL.md'), 'utf8');
test('build skill: pre-share check writes at as_level interact, then deletes', () => {
  const s = skill('build');
  const step = s.slice(s.indexOf('Pre-share check'), s.indexOf('Check before done'));
  assert.match(step, /action:"set"[^\n]*collection:"answers"[^\n]*as_level:"interact"/);
  assert.match(step, /action:"delete"[^\n]*doc_id:"qw-preshare-check"[^\n]*if_version/);
});
test('build skill: share at Contributor, using only the share menu level names', () => {
  const s = skill('build');
  assert.match(s, /\*\*How to share:\*\*.*\*\*Contributor\*\* \(not Viewer or Commenter\)/);
  const named = new Set([...s.matchAll(/\b(Owner|Editor|Contributor|Commenter|Viewer|Member|Collaborator|Participant|Reader|Writer)s?\b/g)].map(m => m[1]));
  assert.deepEqual([...named].filter(n => !['Owner', 'Editor', 'Contributor', 'Commenter', 'Viewer'].includes(n)), []);
});
test('collect skill: zero answers after sharing asks for the Copy all my answers text', () => {
  const s = skill('collect');
  assert.match(s, /\*\*Zero answers:\*\*[\s\S]*hours after sharing[\s\S]*Copy all my answers/);
  assert.match(s, /qw-preshare-check/);
  assert.match(s, /Never write pasted answers into\s+the artifact's db/);
});
