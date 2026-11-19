#!/usr/bin/env bash
# Undo fresh-install-reset.sh: put the backed-up data folder and the allow rule back, and (re)install the plugin.
#
#   scripts/dev/fresh-install-restore.sh BACKUP_DIR [--dry-run]
#
# BACKUP_DIR is the artifact-explorer-backup-<timestamp> folder the reset printed. A data folder made by the
# fresh install is kept beside it as artifact-explorer-fresh-<timestamp>. Paths follow CLAUDE_CONFIG_DIR;
# CLAUDE_BIN overrides the `claude` command. --dry-run changes nothing.
set -euo pipefail

BACKUP="${1:-}"
DRY=0
[ "${2:-}" = "--dry-run" ] && DRY=1
if [ -z "$BACKUP" ] || [ ! -d "$BACKUP" ]; then
  echo "usage: $0 BACKUP_DIR [--dry-run]   (BACKUP_DIR must exist)" >&2
  exit 2
fi
CONFIG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CLAUDE="${CLAUDE_BIN:-claude}"
DATA="$CONFIG/plugins/data/artifact-explorer-jethro"
SETTINGS="$CONFIG/settings.json"
STAMP="$(date +%Y%m%d-%H%M%S)"
HERE="$(cd "$(dirname "$0")" && pwd)"

run() {
  if [ "$DRY" = 1 ]; then echo "  would run: $*"; else echo "  running: $*"; "$@"; fi
}

echo "Artifact Explorer restore from $BACKUP$([ "$DRY" = 1 ] && echo ' (dry run: nothing is changed)')"

. "$HERE/watchers.sh"
WATCHERS="$(ae_watchers | sort -u -k1,1)"
if [ -n "$WATCHERS" ]; then
  echo "Refusing: a watcher is running on $DATA (pids: $(echo "$WATCHERS" | awk '{print $1}' | tr '\n' ' '))."
  echo "Type /exit in the Claude Code windows (or \`claude stop <id>\` for background sessions), then run this again."
  [ "$DRY" = 1 ] || exit 1
  echo "  (dry run: continuing to show the remaining steps)"
fi

# Check settings.json can be changed before anything moves (a file we cannot parse stops here).
NEW=""
trap '[ -z "$NEW" ] || rm -f "$NEW"' EXIT
if [ -f "$SETTINGS" ]; then
  NEW="$(mktemp)"
  if ! python3 "$HERE/settings_rule.py" add "$SETTINGS" "$NEW"; then
    echo "Refusing: could not read $SETTINGS (fix it, then run this again). Nothing was changed." >&2
    exit 1
  fi
fi

echo
if [ -d "$DATA" ]; then
  echo "Data made by the fresh install: $DATA -> $CONFIG/plugins/data/artifact-explorer-fresh-$STAMP"
  run mv "$DATA" "$CONFIG/plugins/data/artifact-explorer-fresh-$STAMP"
fi
echo "Data: $BACKUP -> $DATA"
run mv "$BACKUP" "$DATA"

echo
if [ -n "$NEW" ] && [ -f "$SETTINGS" ]; then
  python3 "$HERE/settings_rule.py" add "$SETTINGS" "$NEW"  # again: a claude plugin step may have edited it
  echo "Settings: adding the Artifact Explorer allow rule back to $SETTINGS"
  diff -u "$SETTINGS" "$NEW" | sed 's/^/  /' || true
  if [ "$DRY" = 1 ]; then
    echo "  would back up to $SETTINGS.ae-backup-$STAMP and write the change"
  else
    cp -p "$SETTINGS" "$SETTINGS.ae-backup-$STAMP"
    cat "$NEW" > "$SETTINGS"
  fi
fi

echo
echo "Plugin:"
run "$CLAUDE" plugin marketplace add jachai/jethro || echo "  (marketplace already added; continuing)"
run "$CLAUDE" plugin install artifact-explorer@jethro || echo "  (already installed; continuing)"

cat <<EOF

Done$([ "$DRY" = 1 ] && echo ' (dry run)'). Open a new Claude Code window (or /exit and \`claude --resume <id>\`),
then run \`ae build\` (or /artifact-explorer:open) to check the restored catalog.
EOF
