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
// reduce: prefers-reduced-motion (true by default, so motion tests opt in); sound: the remembered 'qw-sound-v1' value
async function run({ db = 'ok', can = null, stored = null, docs = [], reduce = true, sound = null } = {}) {
  const els = {}, handlers = {}, writes = [], clip = [], ls = {};
  const document = {
    getElementById: id => (els[id] ||= el()), createElement: () => el(), activeElement: null, title: '',
    addEventListener: (t, fn) => { (handlers[t] ||= []).push(fn); },
  };
  const store = {
    collection: () => ({ onSnapshot: (ok, err) => { setTimeout(() => db === 'listenerError' ? err({ code: 'unavailable' }) : ok({ docs: docs.map(r => ({ id: r.qid, data: () => r })), metadata: { fromCache: false } }), 0); return () => {}; } }),
    doc: path => ({
      set: async r => { if (db === 'refuse') { const e = new Error('no'); e.code = 'invalid_argument'; throw e; } writes.push([path, r]); },
      delete: async () => {},
    }),
  };
  const user = { id: async () => 'u_test', can: async () => can, profiles: async () => ({}) };
  const T = {};
  const ctx = {
    document, window: { scrollTo() {} }, navigator: { clipboard: { writeText: async t => { clip.push(t); } } },
    localStorage: { getItem: k => (k === 'qw-sound-v1' ? sound : stored && /answers/.test(k) ? JSON.stringify(stored) : null), setItem: (k, v) => { ls[k] = v; } }, matchMedia: () => ({ matches: reduce }),
    requestAnimationFrame: f => f(), performance: { now: () => 0 }, setTimeout, clearTimeout, console: { warn() {} },
    claude: { use: async n => n === 'db' ? (db === 'null' ? null : store) : n === 'user' ? user : null },
    __QW_TEST__: T,
  };
  ctx.globalThis = ctx;
  vm.runInNewContext(app, ctx);
  await new Promise(r => setTimeout(r, 20));
  return { els, T: T.api, writes, clip, handlers, document, ls,
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
  assert.equal(p.toast(), '', 'no toast before the reader does anything');
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
  assert.doesNotMatch(p.text(), /only lets you view/, 'can() unknown: no definite view-only claim');
  assert.match(p.text(), /refused the save; if you were shared as Viewer or Commenter, ask Sam to make you a Contributor/);
});
test('a refused set when the platform said the viewer CAN write: a plain refused save, never view-only', async () => {
  const p = await run({ db: 'refuse', can: true });
  await pickFirst(p);
  assert.equal(p.banner(), true); assert.match(p.text(), /the last save was refused/); assert.doesNotMatch(p.text(), /view|Contributor/);
});
test('saveFailReason: invalid_argument is only a possible access problem when can() did not say yes', async () => {
  const { T } = await run();
  const ia = { code: 'invalid_argument' };
  assert.equal(T.saveFailReason(ia, null), 'refused'); assert.equal(T.saveFailReason(ia, true), 'write');
  assert.equal(T.saveFailReason({ code: 'unavailable' }, null), 'write'); assert.equal(T.saveFailReason(null, null), 'write');
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

// v0.2.0 motion: pure milestone / celebration logic, and no celebration for restored answers
test('milestones: halfway once the count crosses half (4+ cards), done at the last one', async () => {
  const { T } = await run();
  const m = T.milestoneAt;
  assert.equal(m(2, 3, 6), 'half'); assert.equal(m(3, 4, 6), null); assert.equal(m(5, 6, 6), 'done'); assert.equal(m(6, 6, 6), null);
  assert.equal(m(3, 4, 7), 'half'); assert.equal(m(2, 3, 7), null); assert.equal(m(1, 2, 3), null, 'no halfway under 4 cards');
  assert.equal(m(2, 3, 3), 'done'); assert.equal(m(4, 3, 6), null, 'un-answering is no milestone'); assert.equal(m(0, 0, 0), null);
  assert.equal(T.milestoneText('half', 3, 6), '3 of 6, halfway there');
  assert.equal(T.milestoneText('half', 4, 7), '4 of 7, past halfway');
  assert.equal(T.milestoneText('done', 6, 6), '6 of 6, all done');
});
test('celebrateKind: only a card going from open to done, bigger on the last', async () => {
  const { T } = await run();
  assert.equal(T.celebrateKind(false, true, 1, 6), 'card'); assert.equal(T.celebrateKind(false, true, 6, 6), 'final');
  assert.equal(T.celebrateKind(true, true, 3, 6), null, 'changing an answer'); assert.equal(T.celebrateKind(false, false, 2, 6), null, 'a part still open');
});
test('picks celebrate: a card, nothing for a half-done card, the final one at the end, plus the done badge', async () => {
  const p = await run();
  await pickFirst(p);
  assert.deepEqual([...p.T.celebrations], ['card']);
  p.T.go(2); p.T.pick(0, 0);
  assert.deepEqual([...p.T.celebrations], ['card'], 'part 2 still open');
  p.T.pick(0, 1);
  assert.deepEqual([...p.T.celebrations], ['card', 'final']);
  assert.equal(p.T.milestone(), '2 of 2, all done');
});
const restored = [
  { qid: 'q-fee', optionId: 'grace', at: '2026-11-15T10:00:00Z' },
  { qid: 'q-route', optionId: 'nearest', at: '2026-11-15T10:00:00Z' },
];
test('no celebration on load for answers restored from this browser', async () => {
  const p = await run({ stored: Object.fromEntries(restored.map(r => [r.qid, r])) });
  assert.equal(p.T.celebrations.length, 0); assert.equal(p.T.milestone(), '');
  p.T.go(1); p.T.pick(1, 0);
  assert.equal(p.T.celebrations.length, 0, 'changing a restored answer is not a new answer');
});
test('no celebration for answers arriving from the store (page load or another device)', async () => {
  const p = await run({ docs: restored.concat([{ qid: 'q-route-b', optionId: 'x', at: '2026-11-15T10:00:00Z' }]) });
  assert.equal(Object.keys(p.T.state().answers).length, 3);
  assert.equal(p.T.celebrations.length, 0); assert.equal(p.T.milestone(), '');
});

// v0.2.1: bigger fireworks with sound, a remembered mute, nothing under reduced motion
test('shellPlan: n shells launched one after another, bursting inside the top half of the screen', async () => {
  const { T } = await run();
  let k = 0; const rnd = () => [0, 0.5, 0.999][k++ % 3];
  const s = T.shellPlan(6, 390, 800, rnd);
  assert.equal(s.length, 6);
  s.forEach((x, i) => {
    assert.ok(x.x >= 390 * 0.12 - 1 && x.x <= 390 * 0.88 + 1, 'x on screen, off the edges');
    assert.ok(x.y >= 800 * 0.14 - 1 && x.y <= 800 * 0.4 + 1, 'bursts in the upper part');
    assert.ok(x.rise >= 620 && x.rise <= 880);
    if (i) assert.ok(x.at > s[i - 1].at, 'launches in order');
  });
  assert.ok(s[5].at + s[5].rise < 2600, 'the last shell bursts within about 2.6 s');
});
test('sound: a pop for a card, the fireworks for the last one', async () => {
  const p = await run({ reduce: false });
  await pickFirst(p);
  p.T.go(2); p.T.pick(0, 0); p.T.pick(0, 1);
  assert.deepEqual([...p.T.celebrations], ['card', 'final']);
  assert.deepEqual([...p.T.sounds], ['card', 'final']);
});
test('mute: the button silences the next answers and is remembered in this browser', async () => {
  const p = await run({ reduce: false });
  assert.equal(p.T.muted(), false);
  p.T.toggleSound();
  assert.equal(p.T.muted(), true); assert.equal(p.ls['qw-sound-v1'], 'off'); assert.equal(p.toast(), 'Sound off');
  await pickFirst(p);
  assert.deepEqual([...p.T.celebrations], ['card'], 'still celebrates'); assert.equal(p.T.sounds.length, 0, 'but silently');
  p.T.toggleSound();
  assert.equal(p.ls['qw-sound-v1'], 'on'); assert.deepEqual([...p.T.sounds], ['preview'], 'turning it on plays one pop');
  const again = await run({ reduce: false, sound: 'off' });
  assert.equal(again.T.muted(), true, 'muted on the next visit');
  await pickFirst(again); assert.equal(again.T.sounds.length, 0);
});
test('reduced motion: no fireworks sound, even with sound on', async () => {
  const p = await run({ reduce: true });
  await pickFirst(p);
  assert.deepEqual([...p.T.celebrations], ['card']); assert.equal(p.T.sounds.length, 0);
});
