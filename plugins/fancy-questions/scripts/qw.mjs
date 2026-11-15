#!/usr/bin/env node
// question-walkthrough CLI. Zero dependencies.
//   qw build <dir> [--out file]   check + produce the page (default <dir>/index.html)
//   qw lint <dir>                 check only
//   qw stats <dir>                card count, minutes, cards without a visual
//   qw new <dir>                  start a data dir from the minimal example
import { readFileSync, writeFileSync, mkdirSync, existsSync, cpSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { load, check } from './lint.mjs';

export const VERSION = '0.1.1';
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export function build(dir) {
  const { page, cards, errors: le } = load(dir);
  if (le.length) return { errors: le, warnings: [] };
  const { errors, warnings } = check(page, cards);
  if (errors.length) return { errors, warnings };
  const data = { page, cards };
  const json = JSON.stringify(data).replace(/</g, '\\u003c').split(String.fromCharCode(0x2028)).join('\\u2028').split(String.fromCharCode(0x2029)).join('\\u2029');
  const app = readFileSync(join(ROOT, 'page', 'app.js'), 'utf8').replace('/*QW_DATA*/null', () => json);
  const title = page.title.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const html = readFileSync(join(ROOT, 'page', 'template.html'), 'utf8').replace('/*QW_TITLE*/', () => title).replace('/*QW_APP*/', () => app);
  return { errors, warnings, html, app, data };
}

function stats(data) {
  const parts = data.cards.reduce((n, c) => n + (c.parts ? c.parts.length : 0), 0);
  const min = Math.max(1, Math.round(data.cards.length * (data.page.minutesPerCard || 0.75)));
  const novis = data.cards.filter(q => !q.visual).map(q => q.id); // a part shares its card's screen
  const kinds = {}; data.cards.flatMap(c => [c, ...(c.parts || []).filter(p => p.visual)]).forEach(q => { const k = q.visual ? q.visual.kind : 'none'; kinds[k] = (kinds[k] || 0) + 1; });
  return `${data.cards.length} cards (+${parts} parts), about ${min} min, ${data.cards.filter(c => c.urgent).length} urgent · visuals ${Object.entries(kinds).map(([k, n]) => k + ' ' + n).join(', ')}${novis.length ? ' · no visual: ' + novis.join(', ') : ''}`;
}

function report(r) {
  r.warnings.forEach(w => console.error('warn  ' + w));
  r.errors.forEach((e, i) => console.error(`${String(i + 1).padStart(3)}. ${e}`));
}

function main(argv) {
  const [cmd, dir, ...rest] = argv;
  if (cmd === '--version' || cmd === 'version') { console.log('qw ' + VERSION); return 0; }
  if (!dir || !['build', 'lint', 'stats', 'new'].includes(cmd)) { console.error('usage: qw build|lint|stats|new <dir> [--out file]'); return 2; }
  if (cmd === 'new') {
    if (existsSync(join(dir, 'page.json'))) { console.error(`${dir}/page.json already exists`); return 1; }
    mkdirSync(dir, { recursive: true });
    cpSync(join(ROOT, 'skills', 'build', 'examples', 'minimal'), dir, { recursive: true });
    console.log(`started ${dir}: edit page.json and cards/*.json, then qw build ${dir}`); return 0;
  }
  const r = build(dir);
  report(r);
  if (r.errors.length) { console.error(`${r.errors.length} error(s); nothing written`); return 1; }
  if (cmd === 'lint') { console.log(`ok · ${stats(r.data)}`); return 0; }
  if (cmd === 'stats') { console.log(stats(r.data)); return 0; }
  const oi = rest.indexOf('--out'); const out = oi >= 0 ? rest[oi + 1] : join(dir, 'index.html');
  const tmp = join(dir, '.qw-app.check.js');
  writeFileSync(tmp, r.app);
  try { execFileSync(process.execPath, ['--check', tmp], { stdio: 'pipe' }); }
  catch (e) { console.error('page script failed node --check:\n' + String(e.stderr || e.message).split('\n').slice(0, 6).join('\n')); return 1; }
  finally { try { execFileSync('rm', ['-f', tmp]); } catch {} }
  writeFileSync(out, r.html);
  const kb = Math.round(Buffer.byteLength(r.html) / 1024);
  if (kb > 150) console.error(`warn  page is ${kb} KB; over 150 KB loads slowly on phones (images as data URIs?)`);
  console.log(`built ${out} · ${kb} KB · ${stats(r.data)}`);
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exit(main(process.argv.slice(2)));
