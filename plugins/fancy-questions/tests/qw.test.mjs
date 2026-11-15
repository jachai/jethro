import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, cpSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { check } from '../scripts/lint.mjs';
const root = new URL('..', import.meta.url).pathname;
const ex = join(root, 'skills/build/examples/minimal');
const qw = (...a) => spawnSync(process.execPath, [join(root, 'scripts/qw.mjs'), ...a], { encoding: 'utf8' });
const fresh = () => { const d = mkdtempSync(join(tmpdir(), 'qw-')); cpSync(ex, d, { recursive: true }); return d; };
const page = () => JSON.parse(readFileSync(join(ex, 'page.json'), 'utf8'));
const card = () => JSON.parse(readFileSync(join(ex, 'cards/01-money.json'), 'utf8'))[0];
const errs = (c, p = page()) => check(p, [c]).errors.join('\n');

test('minimal example builds and the page script parses', () => {
  const d = fresh(); const r = qw('build', d);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /2 cards \(\+1 parts\)/);
  const html = readFileSync(join(d, 'index.html'), 'utf8');
  assert.match(html, /<title>Example Questions Walkthrough<\/title>/);
  assert.ok(!html.includes('/*QW_'), 'markers replaced');
  const js = html.slice(html.lastIndexOf('<script>') + 8, html.lastIndexOf('</script>'));
  writeFileSync(join(d, 'x.js'), js); execFileSync(process.execPath, ['--check', join(d, 'x.js')]);
});
test('data cannot close the script tag', () => {
  const d = fresh(); const p = page(); p.lead = 'x </script><script>alert(1)</script>'; writeFileSync(join(d, 'page.json'), JSON.stringify(p));
  assert.equal(qw('build', d).status, 0);
  const html = readFileSync(join(d, 'index.html'), 'utf8');
  assert.equal(html.split('</script>').length, 2);
});
test('exactly one recommended option, first', () => {
  const c = card(); c.options[0].recommended = false; assert.match(errs(c), /exactly one option/);
  const c2 = card(); c2.options[0].recommended = false; c2.options[1].recommended = true; assert.match(errs(c2), /must come first/);
});
test('plan codes are rejected, ticket ids allowed', () => {
  const c = card(); c.recommend = 'As in D-584, yes.'; assert.match(errs(c), /plan code/);
  const c2 = card(); c2.recommend = 'Yes, see T-101.'; assert.equal(errs(c2), '');
});
test('numbers in the example need facts', () => { const c = card(); c.facts = []; assert.match(errs(c), /no facts/); });
test('picks min defaults to 1', () => { const c = JSON.parse(readFileSync(join(ex, 'cards/02-ops.json'), 'utf8'))[0]; check(page(), [c]); assert.equal(c.options[1].picks.min, 1); });
test('discuss option is filled in with the owner', () => { const c = card(); check(page(), [c]); assert.equal(c.options[2].sub, 'Park it for a call with Sam.'); });
test('duplicate ids across parts fail', () => { const c = card(); c.parts = [Object.assign(card(), { id: 'q-fee', short: undefined, section: undefined, tickets: undefined })]; delete c.parts[0].parts; assert.match(errs(c), /duplicate id q-fee/); });
test('more than 40 cards is refused', () => { const cs = Array.from({ length: 41 }, (_, i) => Object.assign(card(), { id: 'q' + i })); assert.match(check(page(), cs).errors.join('\n'), /at most 40/); });
test('raw svg is sanitized', () => {
  const v = s => { const c = card(); c.visual = { kind: 'svg', svg: s }; return errs(c); };
  assert.equal(v('<svg viewBox="0 0 380 100"><rect class="g" x="0" y="0" width="10" height="10"/></svg>'), '');
  assert.match(v('<svg viewBox="0 0 800 100"></svg>'), /800 wide/);
  assert.match(v('<svg viewBox="0 0 380 100"><script>x</script></svg>'), /<script>/);
  assert.match(v('<svg viewBox="0 0 380 100" onload="x"></svg>'), /event handler/);
  assert.match(v('<svg viewBox="0 0 380 100"><image href="https://x"/></svg>'), /not allowed|links outside/);
  assert.match(v('<svg viewBox="0 0 380 100"><rect fill="#fff"/></svg>'), /raw colour/);
});
test('impact allows only simple tags', () => { const c = card(); c.options[0].impact = '<a href="x">y</a>'; assert.match(errs(c), /impact may only/); });
test('urls must be https and on allowed hosts', () => {
  const c = card(); c.links = [{ label: 'x', url: 'http://a.com' }]; assert.match(errs(c), /https URL/);
  const p = page(); p.allowedHosts = ['linear.app', 'claude.ai']; const c2 = card(); c2.links = [{ label: 'x', url: 'https://evil.com/a' }]; assert.match(errs(c2, p), /not in page.allowedHosts/);
});
test('lint and stats commands', () => { const d = fresh(); assert.match(qw('lint', d).stdout, /^ok · 2 cards/); assert.match(qw('stats', d).stdout, /1 urgent/); });
test('new refuses to overwrite', () => { const d = fresh(); assert.equal(qw('new', d).status, 1); const d2 = join(mkdtempSync(join(tmpdir(), 'qw-')), 'n'); assert.equal(qw('new', d2).status, 0); assert.equal(qw('build', d2).status, 0); });
test('a part without a visual builds without a warning, and draws no empty figure', () => {
  const c = card(); c.parts = [{ id: 'q-fee-2', question: 'And the second half?', recommend: 'Yes.', options: [{ id: 'y', tone: 'yes', recommended: true, name: 'Yes', sub: 'Do it.' }, { tone: 'discuss' }] }];
  const r = check(page(), [c]); assert.deepEqual(r.errors, []); assert.deepEqual(r.warnings, []);
  const c2 = card(); delete c2.visual; assert.match(check(page(), [c2]).warnings.join('\n'), /no visual/);
  assert.match(readFileSync(join(root, 'page/app.js'), 'utf8'), /\$\{q\.visual\|\|q\.example\|\|facts\.length/);
});
