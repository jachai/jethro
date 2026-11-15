#!/usr/bin/env bash
# After `claude plugin install`, before opening a new window: is the installed plugin the marketplace version,
# and is the data folder still empty? Prints both and exits 1 when either is wrong.
#
#   scripts/dev/fresh-install-check.sh [--any-data]
#
# --any-data skips the fresh data folder check (an update test on a machine that keeps its catalog).
# Paths follow CLAUDE_CONFIG_DIR (default ~/.claude).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
EXPECT=fresh
[ "${1:-}" = "--any-data" ] && EXPECT=installed

echo "Artifact Explorer post-install check"
INST="$(python3 -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
e=(d.get("plugins") or {}).get("artifact-explorer@artifact-explorer") or []
print(e[0].get("installPath","") if isinstance(e,list) and e else "")' "$CONFIG/plugins/installed_plugins.json")"
if [ -n "$INST" ] && [ -f "$INST/bin/ae" ]; then
  echo "  installed copy says: $(sh "$INST/bin/ae" --version 2>&1)"
fi
# the doctor from this checkout reads installed_plugins.json and the marketplace clone; it never writes
python3 "$HERE/../ae.py" doctor --expect "$EXPECT"
rc=$?
if [ -z "$INST" ]; then
  echo "  (not installed: run claude plugin install artifact-explorer@artifact-explorer first)"
  rc=1
fi
exit $rc
