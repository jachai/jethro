#!/bin/sh
# Install session-titles as a plain Claude Code hook (no plugin system).
#   ./install.sh              copy the script to ~/.claude/session-titles/app and register the hooks
#   ./install.sh --link       register the hooks against this checkout instead (for working on the repo)
#   ./install.sh --uninstall  remove the hooks and the CLI link; titles state and the log are kept
#   ./install.sh --purge      uninstall and delete the state and the log too
# settings.json is backed up to settings.json.bak-session-titles before every change.
set -eu

case "${1:-}" in --uninstall|--purge) ;; *) echo "install.sh is deprecated: install the plugin instead (/plugin install session-titles@jethro)" >&2 ;; esac
ROOT="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
HOME_DIR="${SESSION_TITLES_HOME:-$CONFIG/session-titles}"
APP="$HOME_DIR/app"
BIN_DIR="$HOME/.local/bin"

register() {  # $1 = add|remove, $2 = script path
  python3 - "$CONFIG/settings.json" "$1" "${2:-}" <<'PY'
import json, os, shutil, sys
path, action, script = sys.argv[1], sys.argv[2], sys.argv[3]
settings = {}
if os.path.exists(path):
    with open(path) as f:
        settings = json.load(f)
    shutil.copy2(path, path + ".bak-session-titles")
hooks = settings.setdefault("hooks", {})
def ours(h):
    return "session_titles.py" in str(h.get("command", ""))
for event in ("UserPromptSubmit", "SessionStart"):
    groups = []
    for g in hooks.get(event, []):
        g = dict(g)
        g["hooks"] = [h for h in g.get("hooks", []) if not ours(h)]
        if g["hooks"]:
            groups.append(g)
    if action == "add":
        timeout = 45 if event == "UserPromptSubmit" else 15
        groups.append({"hooks": [{"type": "command", "command": f'python3 "{script}" hook', "timeout": timeout}]})
    if groups:
        hooks[event] = groups
    else:
        hooks.pop(event, None)
if not hooks:
    settings.pop("hooks")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
PY
}

link_cli() {  # $1 = the bin/session-titles to link
  if [ -d "$BIN_DIR" ]; then
    ln -sf "$1" "$BIN_DIR/session-titles"
    echo "linked the CLI: $BIN_DIR/session-titles"
  else
    echo "no $BIN_DIR, so no CLI link; run $1 directly"
  fi
}

case "${1:-}" in
  ""|--link)
    if [ "${1:-}" = "--link" ]; then
      SRC="$ROOT"
    else
      rm -rf "$APP"
      mkdir -p "$APP/scripts" "$APP/bin"
      cp "$ROOT/scripts/session_titles.py" "$APP/scripts/"
      cp "$ROOT/bin/session-titles" "$APP/bin/"
      SRC="$APP"
    fi
    register add "$SRC/scripts/session_titles.py"
    link_cli "$SRC/bin/session-titles"
    echo "registered the UserPromptSubmit and SessionStart hooks in $CONFIG/settings.json"
    echo "new sessions pick it up; running sessions keep the hooks they started with"
    echo "check it with: session-titles doctor"
    ;;
  --uninstall|--purge)
    register remove
    if [ -L "$BIN_DIR/session-titles" ]; then rm -f "$BIN_DIR/session-titles"; fi
    rm -rf "$APP"
    if [ "$1" = "--purge" ]; then rm -rf "$HOME_DIR"; echo "deleted $HOME_DIR"; fi
    echo "removed the hooks from $CONFIG/settings.json"
    ;;
  *)
    echo "usage: $0 [--link | --uninstall | --purge]" >&2
    exit 2
    ;;
esac
