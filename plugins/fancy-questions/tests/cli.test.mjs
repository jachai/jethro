import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
const root = new URL('..', import.meta.url).pathname;
test('version matches plugin.json', () => {
  const out = execFileSync('sh', [root + 'bin/qw', '--version']).toString().trim();
  const pj = JSON.parse(readFileSync(root + '.claude-plugin/plugin.json', 'utf8'));
  assert.equal(out, 'qw ' + pj.version);
});
