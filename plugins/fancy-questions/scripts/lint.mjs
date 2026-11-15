// The data contract: load page.json + cards/*.json, normalize, and check every rule.
// This file IS the schema (one source of truth); reference/schema.md documents it.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

export const MAX_CARDS = 40;
export const KINDS = ['bars', 'split', 'flow', 'tree', 'beforeAfter', 'steps', 'table', 'image', 'pair', 'stack', 'svg'];
export const TONES = ['yes', 'no', 'discuss', 'neutral'];
const VTONES = ['yes', 'no', 'discuss', 'muted', 'accent', ''];
const PLAN_CODE = /\b(D-?\d{2,4}|Decision\s+\d+|wave\s+[A-Z]\b)/;
const ID = /^[a-z0-9][a-z0-9_.-]{0,60}$/i;
const LIMITS = { question: 240, recommend: 240, short: 60, name: 70, sub: 200 };

export function load(dir) {
  const errors = [];
  const read = f => { try { return JSON.parse(readFileSync(f, 'utf8')); } catch (e) { errors.push(`${f}: ${e.message}`); return null; } };
  const page = read(join(dir, 'page.json'));
  const cdir = join(dir, 'cards');
  const files = existsSync(cdir) ? readdirSync(cdir).filter(f => f.endsWith('.json')).sort() : [];
  if (!files.length) errors.push(`${cdir}: no card files (cards/*.json)`);
  const cards = [];
  for (const f of files) {
    const d = read(join(cdir, f));
    if (d == null) continue;
    const list = Array.isArray(d) ? d : d.cards;
    if (!Array.isArray(list)) { errors.push(`cards/${f}: expected an array of cards or {"cards": [...]}`); continue; }
    list.forEach(c => { if (c && typeof c === 'object') Object.defineProperty(c, '_file', { value: `cards/${f}` }); cards.push(c); });
  }
  return { page, cards, errors };
}

export function check(page, cards) {
  const errors = [], warnings = [];
  const E = (where, msg) => errors.push(`${where}: ${msg}`);
  const W = (where, msg) => warnings.push(`${where}: ${msg}`);
  const str = (v, where, field, req = true) => {
    if (v == null || v === '') { if (req) E(where, `${field} is required`); return false; }
    if (typeof v !== 'string') { E(where, `${field} must be a string`); return false; }
    if (LIMITS[field] && v.length > LIMITS[field]) E(where, `${field} is ${v.length} chars (max ${LIMITS[field]})`);
    if (PLAN_CODE.test(v)) E(where, `${field} contains a plan code ("${v.match(PLAN_CODE)[0]}"); use plain words or a ticket id`);
    return true;
  };
  const url = (u, where, field) => {
    if (typeof u !== 'string' || !/^https:\/\/[^\s"'<>]+$/.test(u)) { E(where, `${field} must be an https URL`); return; }
    const hosts = page && page.allowedHosts;
    if (Array.isArray(hosts) && hosts.length) { const h = new URL(u).host; if (!hosts.some(x => h === x || h.endsWith('.' + x))) E(where, `${field} host ${h} is not in page.allowedHosts`); }
  };

  // page
  if (!page || typeof page !== 'object') { E('page.json', 'missing or not an object'); return { errors, warnings }; }
  if (!/^[a-z0-9][a-z0-9-]{1,40}$/.test(page.slug || '')) E('page.json', 'slug must be lowercase letters, digits and dashes (it keys saved answers)');
  str(page.title, 'page.json', 'title');
  ['eyebrow', 'lead', 'audience', 'heading', 'whyline', 'thanks', 'notePrompt', 'discussWith', 'author'].forEach(f => str(page[f], 'page.json', f, false));
  if (!Array.isArray(page.sections) || !page.sections.length) E('page.json', 'sections must list at least one {id, label}');
  const secIds = new Set((page.sections || []).map(s => s && s.id));
  (page.sections || []).forEach((s, i) => { if (!s || !ID.test(s.id || '') || !s.label) E('page.json', `sections[${i}] needs id and label`); });
  if (page.lastRound) { if (page.lastRound.url) url(page.lastRound.url, 'page.json', 'lastRound.url'); if (page.lastRound.decided != null && !(Number.isInteger(page.lastRound.decided) && page.lastRound.decided >= 0)) E('page.json', 'lastRound.decided must be a whole number'); }
  (page.stats || []).forEach((s, i) => { if (!s || typeof s.value !== 'number' || !s.what) E('page.json', `stats[${i}] needs a numeric value and what`); });
  if (page.minutesPerCard != null && !(page.minutesPerCard > 0 && page.minutesPerCard <= 10)) E('page.json', 'minutesPerCard must be between 0 and 10');

  // cards
  if (cards.length > MAX_CARDS) E('cards', `${cards.length} cards; one page holds at most ${MAX_CARDS}. Split into rounds (one page per round).`);
  if (!cards.length) E('cards', 'no cards');
  const seen = new Map();
  const checkQ = (q, where, isPart) => {
    if (!q || typeof q !== 'object') { E(where, 'not an object'); return; }
    if (!ID.test(q.id || '')) E(where, 'id is required (letters, digits, - _ .); it is the saved-answer key, never reuse it for another question');
    else if (seen.has(q.id)) E(where, `duplicate id ${q.id} (also in ${seen.get(q.id)})`); else seen.set(q.id, where);
    if (!isPart) {
      str(q.short, where, 'short');
      if (!secIds.has(q.section)) E(where, `section "${q.section}" is not in page.sections`);
      if (!Array.isArray(q.tickets)) q.tickets = [];
      q.tickets.forEach((t, i) => { if (!t || !t.id) E(where, `tickets[${i}] needs id`); else if (t.url) url(t.url, where, `tickets[${i}].url`); });
      str(q.badge, where, 'badge', false);
      if (q.urgent != null && typeof q.urgent !== 'boolean') E(where, 'urgent must be true or false');
    } else if (q.parts) E(where, 'a part cannot have parts');
    str(q.question, where, 'question');
    str(q.recommend, where, 'recommend');
    for (const f of ['today', 'after']) if (q[f] != null) { if (typeof q[f] === 'string') q[f] = { text: q[f] }; str(q[f].text, where, `${f}.text`); str(q[f].label, where, `${f}.label`, false); }
    str(q.example, where, 'example', false);
    str(q.notePrompt, where, 'notePrompt', false);
    q.facts = q.facts || [];
    q.facts.forEach((f, i) => { if (!f || !str(f.text, where, `facts[${i}].text`)) return; if (typeof f.verified !== 'boolean') E(where, `facts[${i}].verified must be true or false`); });
    if (q.example && /\$\s?\d|\d{2,}/.test(q.example) && !q.facts.length) E(where, 'example has numbers but no facts[] entry saying where they came from (use verified:false for anything not read from the source)');
    (q.links || []).forEach((l, i) => { if (!l || !l.label) E(where, `links[${i}] needs label`); url(l && l.url, where, `links[${i}].url`); });
    if (!q.visual) W(where, 'no visual; every approved card had one');
    else checkVisual(q.visual, where, E, url);
    // options
    if (!Array.isArray(q.options) || q.options.length < 2 || q.options.length > 6) { E(where, 'options must have 2 to 6 entries'); return; }
    q.options = q.options.map((o, i) => normalizeOption(o, i, page));
    const ids = new Set();
    q.options.forEach((o, i) => {
      const ow = `${where} options[${i}]`;
      if (!ID.test(o.id || '')) E(ow, 'id is required'); else if (ids.has(o.id)) E(ow, `duplicate option id ${o.id}`); else ids.add(o.id);
      if (!TONES.includes(o.tone)) E(ow, `tone must be one of ${TONES.join(', ')}`);
      str(o.name, ow, 'name'); str(o.sub, ow, 'sub');
      if (o.impact != null) { if (typeof o.impact !== 'string') E(ow, 'impact must be a string'); else { if (/<(?!\/?(b|i|em|strong)>)/i.test(o.impact)) E(ow, 'impact may only use <b> <i> <em> <strong>'); str(o.impact.replace(/<[^>]+>/g, ''), ow, 'impact'); } }
      if (o.picks) {
        const p = o.picks; if (!p.label) E(ow, 'picks.label is required');
        const items = p.groups ? p.groups.flatMap(g => { if (!g.name || !Array.isArray(g.items)) E(ow, 'picks.groups need name and items'); return g.items || []; }) : p.items;
        if (!Array.isArray(items) || !items.length) E(ow, 'picks needs items or groups');
        const vals = (items || []).map(it => typeof it === 'string' ? it : it && it.value);
        if (vals.some(v => !v)) E(ow, 'every pick item needs a value');
        if (new Set(vals).size !== vals.length) E(ow, 'pick values must be unique');
        p.min = p.min == null ? 1 : p.min;
        if (!(Number.isInteger(p.min) && p.min >= 0 && p.min <= vals.length)) E(ow, 'picks.min must be a whole number up to the item count');
      }
    });
    const recs = q.options.filter(o => o.recommended);
    if (recs.length !== 1) E(where, `exactly one option needs recommended:true (found ${recs.length})`);
    else if (!q.options[0].recommended) E(where, 'the recommended option must come first');
    if (q.options.filter(o => o.picks && o.picks.always).length > 1) E(where, 'only one option per question can have always-shown picks');
  };
  cards.forEach((c, i) => {
    const where = `${c && c._file || 'cards'}#${c && c.id || i}`;
    checkQ(c, where, false);
    if (c && c.parts != null) {
      if (!Array.isArray(c.parts) || c.parts.length > 3) E(where, 'parts must be an array of at most 3 extra questions');
      else c.parts.forEach((p, j) => checkQ(p, `${where} parts[${j}]`, true));
    }
  });
  const urg = cards.filter(c => c && c.urgent).length;
  if (urg && urg === cards.length && cards.length > 1) W('cards', 'every card is urgent; mark only the ones that block something');
  return { errors, warnings };
}

function normalizeOption(o, i, page) {
  if (!o || typeof o !== 'object') return { id: '', tone: '' };
  if (o.tone === 'discuss' && !o.name) {
    const who = page.discussWith ? ` with ${page.discussWith}` : '';
    return Object.assign({ id: o.id || 'discuss', name: 'Let’s discuss', sub: `Park it for a call${who}.`, impact: 'Nothing changes until we talk.' }, o);
  }
  return o;
}

function checkVisual(v, where, E, url) {
  const w = `${where} visual`;
  if (!v || !KINDS.includes(v.kind)) { E(w, `kind must be one of ${KINDS.join(', ')}`); return; }
  const arr = (a, f, min, max) => { if (!Array.isArray(a) || a.length < min || a.length > max) { E(w, `${v.kind}.${f} needs ${min}-${max} entries`); return false; } return true; };
  const tone = (t, f) => { if (t != null && !VTONES.includes(t)) E(w, `${f} tone must be one of ${VTONES.filter(Boolean).join(', ')}`); };
  switch (v.kind) {
    case 'bars': if (arr(v.rows, 'rows', 1, 10)) v.rows.forEach((r, i) => { if (!r || !r.label || typeof r.value !== 'number' || r.value < 0) E(w, `rows[${i}] needs label and a value ≥ 0`); else tone(r.tone, `rows[${i}]`); if (r && r.label && r.label.length > 18) E(w, `rows[${i}].label is ${r.label.length} chars; bars labels fit 18 at phone width (use table for longer)`); }); break;
    case 'split': if (arr(v.parts, 'parts', 2, 6)) v.parts.forEach((p, i) => { if (!p || !p.label || typeof p.value !== 'number') E(w, `parts[${i}] needs label and value`); else tone(p.tone, `parts[${i}]`); }); break;
    case 'flow': if (arr(v.steps, 'steps', 2, 8)) v.steps.forEach((s, i) => { if (!s || !s.label) E(w, `steps[${i}] needs label`); else tone(s.tone, `steps[${i}]`); }); break;
    case 'steps': if (arr(v.items, 'items', 2, 10)) v.items.forEach((s, i) => { if (!s || !s.label) E(w, `items[${i}] needs label`); else tone(s.tone, `items[${i}]`); }); break;
    case 'tree': {
      const node = (n, d) => { if (typeof n === 'string') return; if (!n || (!n.ask && !n.label)) { E(w, 'tree nodes need ask (with branches) or label'); return; }
        if (n.ask) { if (d > 3) E(w, 'tree is deeper than 3'); if (!Array.isArray(n.branches) || n.branches.length < 2 || n.branches.length > 4) E(w, 'each ask needs 2-4 branches'); else n.branches.forEach(b => { if (!b || !b.when) E(w, 'each branch needs when'); else node(b.then, d + 1); }); } else tone(n.tone, 'leaf'); };
      node(v.root, 1); break; }
    case 'beforeAfter': for (const s of ['before', 'after']) { const c = v[s]; if (!c || !c.label || !Array.isArray(c.lines) || !c.lines.length) E(w, `${s} needs label and lines`); } break;
    case 'table': if (arr(v.cols, 'cols', 1, 5) && arr(v.rows, 'rows', 1, 12)) v.rows.forEach((r, i) => { if (!Array.isArray(r) || r.length !== v.cols.length) E(w, `rows[${i}] must have ${v.cols.length} cells`); }); break;
    case 'image': if (!v.alt) E(w, 'image needs alt text'); if (!/^(https:\/\/|data:image\/(png|jpeg|webp|gif);base64,)/.test(v.src || '')) E(w, 'image src must be https or a base64 data:image URI'); else if (v.src.startsWith('https')) url(v.src, w, 'src'); break;
    case 'pair': if (!v.a || !v.b) E(w, 'pair needs a and b'); else { checkVisual(v.a, where, E, url); checkVisual(v.b, where, E, url); } break;
    case 'stack': if (arr(v.items, 'items', 2, 3)) v.items.forEach(x => checkVisual(x, where, E, url)); break;
    case 'svg': checkSvg(v, w, E); break;
  }
}

// Raw SVG escape hatch: allow only drawing elements, no script, no event handlers, no external refs.
const SVG_TAGS = new Set(['svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'text', 'tspan', 'title', 'desc', 'defs', 'marker', 'lineargradient', 'stop', 'use', 'clippath']);
export function checkSvg(v, w, E) {
  const s = v.svg;
  if (typeof s !== 'string' || !/^\s*<svg[\s>]/.test(s)) { E(w, 'svg must start with <svg'); return; }
  const vb = s.match(/viewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)\s*"/);
  if (!vb) E(w, 'svg needs a viewBox'); else if (+vb[1] > 420) E(w, `svg viewBox is ${vb[1]} wide; keep it ≤ 420 so 13px text stays readable on a phone`);
  for (const m of s.matchAll(/<\/?\s*([a-zA-Z][\w:-]*)/g)) if (!SVG_TAGS.has(m[1].toLowerCase())) { E(w, `svg uses <${m[1]}>, which is not allowed`); break; }
  if (/\son\w+\s*=/i.test(s)) E(w, 'svg has an event handler attribute');
  if (/(href|src)\s*=\s*"(?!#)/i.test(s)) E(w, 'svg links outside itself (only href="#id" is allowed)');
  if (/javascript:|<!\[CDATA|<!--|url\((?!#)/i.test(s)) E(w, 'svg has script, comments or an external url()');
  if (/fill="#|stroke="#|fill:\s*#|stroke:\s*#/i.test(s)) E(w, 'svg uses a raw colour; use var(--fg), var(--muted), var(--accent), var(--yes), var(--no), var(--line) or the .ico classes so both themes work');
}
