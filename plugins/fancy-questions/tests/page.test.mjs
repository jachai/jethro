// Runs the built page script against a stub DOM and a stub `claude` runtime, to check that a page
// whose answers cannot reach the author says so loudly (v0.1.1) and offers the answers as text.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { join } from 'node:path';
import { build } from '../scripts/qw.mjs';
const root = new URL('..', import.meta.url).pathname;
const { app } = build(join(root, 'skills/build/examples/minimal'));

function el() {
  const cls = new Set();
  return {
    hidden: false, textContent: '', innerHTML: '', value: '', style: {}, dataset: {},
    classList: { add: c => cls.add(c), remove: c => cls.delete(c), toggle: (c, on) => (on ?? !cls.has(c)) ? cls.add(c) : cls.delete(c), contains: c => cls.has(c) },
    set className(v) { cls.clear(); String(v).split(/\s+/).filter(Boolean).forEach(c => cls.add(c)); }, get className() { return [...cls].join(' '); },
    querySelector: () => el(), querySelectorAll: () => [], addEventListener() {}, appendChild() {}, setAttribute() {}, focus() {}, select() {}, remove() {}, scrollIntoView() {}, matches: () => false, closest: () => null,
  };
}

// db: {mode: 'null' | 'listenerError' | 'refuse' | 'ok'}; can: true|false|null
async function run({ db = 'ok', can = null } = {}) {
  const els = {}, handlers = {}, writes = [], clip = [];
  const document = {
    getElementById: id => (els[id] ||= el()), createElement: () => el(), activeElement: null, title: '',
    addEventListener: (t, fn) => { (handlers[t] ||= []).push(fn); },
  };
  const store = {
    collection: () => ({ onSnapshot: (ok, err) => { setTimeout(() => db === 'listenerError' ? err({ code: 'unavailable' }) : ok({ docs: [], metadata: { fromCache: false } }), 0); return () => {}; } }),
    doc: path => ({
      set: async r => { if (db === 'refuse') { const e = new Error('no'); e.code = 'invalid_argument'; throw e; } writes.push([path, r]); },
      delete: async () => {},
    }),
  };
  const user = { id: async () => 'u_test', can: async () => can, profiles: async () => ({}) };
  const T = {};
  const ctx = {
    document, window: { scrollTo() {} }, navigator: { clipboard: { writeText: async t => { clip.push(t); } } },
    localStorage: { getItem: () => null, setItem() {} }, matchMedia: () => ({ matches: true }),
    requestAnimationFrame: f => f(), performance: { now: () => 0 }, setTimeout, clearTimeout, console: { warn() {} },
    claude: { use: async n => n === 'db' ? (db === 'null' ? null : store) : n === 'user' ? user : null },
    __QW_TEST__: T,
  };
  ctx.globalThis = ctx;
  vm.runInNewContext(app, ctx);
  await new Promise(r => setTimeout(r, 20));
  return { els, T: T.api, writes, clip, handlers, document,
    banner: () => !els.nosave.hidden, text: () => els.nosavetxt.innerHTML, toast: () => els.toast.textContent, save: () => els.savetxt.textContent,
    click: async () => { handlers.click.forEach(h => h({ target: { closest: () => ({}) }, preventDefault() {} })); await new Promise(r => setTimeout(r, 5)); } };
}
const pickFirst = async p => { p.T.go(1); p.T.pick(0, 0); await new Promise(r => setTimeout(r, 10)); };

test('a working store: no banner, the pick is written to answers/<qid>', async () => {
  const p = await run({ db: 'ok', can: true });
  assert.equal(p.banner(), false);
  await pickFirst(p);
  assert.equal(p.banner(), false);
  assert.equal(p.writes.length, 1); assert.equal(p.writes[0][0], 'answers/q-fee');
  assert.match(p.save(), /^Saved/);
});
test('no db: the banner is up before any answer, names the author, and every save repeats it', async () => {
  const p = await run({ db: 'null' });
  assert.equal(p.banner(), true);
  assert.match(p.text(), /NOT reaching Sam/);
  assert.match(p.save(), /NOT sent to Sam/);
  await pickFirst(p);
  assert.match(p.toast(), /Not sent to Sam/);
});
test('listener error: banner', async () => {
  const p = await run({ db: 'listenerError' });
  assert.equal(p.banner(), true); assert.match(p.text(), /could not reach/);
});
test('view-only viewer (can data.write false): banner on the first card, before any pick', async () => {
  const p = await run({ db: 'ok', can: false });
  assert.equal(p.banner(), true); assert.match(p.text(), /only lets you view/);
});
test('a refused set (view-only, can() unknown): banner after the pick and nothing written', async () => {
  const p = await run({ db: 'refuse', can: null });
  assert.equal(p.banner(), false);
  await pickFirst(p);
  assert.equal(p.banner(), true); assert.equal(p.writes.length, 0);
  assert.match(p.toast(), /Not sent to Sam/);
});
test('Copy all my answers: plain text, one line per question and part, ready to paste', async () => {
  const p = await run({ db: 'refuse' });
  await pickFirst(p);
  await p.click();
  assert.equal(p.clip.length, 1);
  const lines = p.clip[0].split('\n');
  assert.match(lines[0], /^Example Questions Walkthrough: my answers \(1 of 2 answered/);
  assert.equal(lines.length, 1 + 3 + 1, 'title + 2 cards (+1 part) + page line');
  assert.match(lines[1], /^1\. .+: Yes/);
  assert.match(lines.at(-2), /not answered$/);
  assert.ok(!/[<>]/.test(p.clip[0]), 'no markup');
  // the line shape the collect skill parses
  lines.slice(1, -1).forEach(l => assert.match(l, /^\d+[a-z]?\. .+?( \[[^\]]+\])?: (.+?|not answered)(\. Ticked: .+)?(\. Note: .+)?$/));
  assert.equal(lines.at(-1), 'Page: example-questions');
});
test('every card and the summary carry the copy button', () => {
  const n = (app.match(/\$\{COPYROW\}/g) || []).length;
  assert.ok(n >= 1 && /data-copyall>Copy all my answers<\/button>"?/.test(app));
  assert.match(app, /class="btn primary" data-copyall>Copy all my answers/);
});
