#!/usr/bin/env bash
# Put this machine in the state of someone who never installed Artifact Explorer, keeping a backup.
# Undo with scripts/dev/fresh-install-restore.sh <backup dir>.
#
#   scripts/dev/fresh-install-reset.sh [--dry-run]
#
# Paths follow CLAUDE_CONFIG_DIR (default ~/.claude). CLAUDE_BIN overrides the `claude` command.
# --dry-run changes nothing: it prints what it would do, including the settings.json diff.
set -euo pipefail

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
CONFIG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CLAUDE="${CLAUDE_BIN:-claude}"
DATA="$CONFIG/plugins/data/artifact-explorer-artifact-explorer"
SETTINGS="$CONFIG/settings.json"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$CONFIG/plugins/data/artifact-explorer-backup-$STAMP"
HERE="$(cd "$(dirname "$0")" && pwd)"

run() {  # run a command, or only show it in a dry run
  if [ "$DRY" = 1 ]; then echo "  would run: $*"; else echo "  running: $*"; "$@"; fi
}

echo "Artifact Explorer fresh-install reset$([ "$DRY" = 1 ] && echo ' (dry run: nothing is changed)')"
echo "  config dir: $CONFIG"

# 1. Refuse while a watcher uses this data folder: it would recreate files while we move them.
. "$HERE/watchers.sh"
WATCHERS="$(ae_watchers | sort -u -k1,1)"
if [ -n "$WATCHERS" ]; then
  echo
  echo "Refusing: an Artifact Explorer watcher is running on $DATA."
  echo "$WATCHERS" | while read -r pid ppid cmd; do
    # walk up to the claude session that started it
    p="$ppid"; owner=""
    while [ -n "$p" ] && [ "$p" -gt 1 ]; do
      case "$(ps -o comm= -p "$p" 2>/dev/null || true)" in
        claude*|*/claude*) owner="$p ($(ps -o command= -p "$p" | cut -c1-100))"; break ;;
      esac
      p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ' || true)"
    done
    echo "  watcher pid $pid, session process ${owner:-unknown}"
  done
  echo "Close those sessions first: type /exit in each window, or \`claude stop <id>\` for a background session"
  echo "(\`claude agents\` lists them). Then run this again."
  [ "$DRY" = 1 ] || exit 1
  echo "  (dry run: continuing to show the remaining steps)"
fi

# Check settings.json can be changed before anything moves (a file we cannot parse stops here).
NEW=""
trap '[ -z "$NEW" ] || rm -f "$NEW"' EXIT
if [ -f "$SETTINGS" ]; then
  NEW="$(mktemp)"
  if ! python3 "$HERE/settings_rule.py" remove "$SETTINGS" "$NEW"; then
    echo "Refusing: could not read $SETTINGS (fix it, then run this again). Nothing was changed." >&2
    exit 1
  fi
fi

# 2. Back up the data folder (catalog, page, thumbnails, config.toml).
echo
if [ -d "$DATA" ]; then
  echo "Data: $DATA -> $BACKUP"
  run mv "$DATA" "$BACKUP"
else
  echo "Data: none at $DATA (nothing to back up)"
  BACKUP=""
fi

# 3. Uninstall the plugin and remove its marketplace.
echo
echo "Plugin:"
run "$CLAUDE" plugin uninstall artifact-explorer@artifact-explorer || echo "  (uninstall failed or not installed; continuing)"
run "$CLAUDE" plugin marketplace remove artifact-explorer || echo "  (marketplace not present; continuing)"

# 4. Remove only the plugin's allow rule from settings.json (a backup copy is kept next to it).
echo
if [ -n "$NEW" ] && [ -f "$SETTINGS" ]; then
  python3 "$HERE/settings_rule.py" remove "$SETTINGS" "$NEW"  # again: a claude plugin step may have edited it
  echo "Settings: removing the Artifact Explorer allow rule from $SETTINGS"
  diff -u "$SETTINGS" "$NEW" | sed 's/^/  /' || true
  if [ "$DRY" = 1 ]; then
    echo "  would back up to $SETTINGS.ae-backup-$STAMP and write the change"
  else
    cp -p "$SETTINGS" "$SETTINGS.ae-backup-$STAMP"
    cat "$NEW" > "$SETTINGS"
    echo "  backup: $SETTINGS.ae-backup-$STAMP"
  fi
fi

cat <<EOF

Done$([ "$DRY" = 1 ] && echo ' (dry run)'). Backup: ${BACKUP:-none}
Undo later with: scripts/dev/fresh-install-restore.sh ${BACKUP:-<backup dir>}

Fresh install, as a new user would do it:
  1. claude plugin marketplace add jachai/artifact-explorer
  2. claude plugin install artifact-explorer@artifact-explorer
  3. Open a NEW Claude Code window (plugins, hooks and the watcher load at start).
  4. Run /artifact-explorer:setup and accept the defaults.
  5. Publish one test artifact (ask Claude for a small page artifact), then run /artifact-explorer:open
     and check that it is on the page.
EOF
