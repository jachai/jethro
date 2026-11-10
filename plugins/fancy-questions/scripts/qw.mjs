#!/usr/bin/env node
// question-walkthrough CLI. Zero dependencies.
export const VERSION = '0.1.0';
const [cmd] = process.argv.slice(2);
if (cmd === '--version' || cmd === 'version') { console.log('qw ' + VERSION); process.exit(0); }
console.error('usage: qw build|lint|stats|new <dir>');
process.exit(2);
