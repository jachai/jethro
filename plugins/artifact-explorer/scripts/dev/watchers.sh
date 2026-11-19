# Sourced by fresh-install-reset.sh and fresh-install-restore.sh: find a live watcher on $DATA.
# Matches the watcher command line under the path as given, without a trailing slash, and with symlinks
# resolved, and also trusts DATA/watcher.json (a pid that is alive and wrote it in the last 10 minutes).
ae_watchers() {
  local forms f pid
  forms="$(printf '%s\n' "$DATA" "${DATA%/}")"
  if [ -d "$DATA" ]; then forms="$forms
$(cd "$DATA" && pwd -L)
$(cd "$DATA" && pwd -P)"; fi
  while read -r f; do
    [ -n "$f" ] || continue
    ps -axo pid=,ppid=,command= | grep -F -- "$f" | grep -E '(^|[ /])ae(\.py)?"? .* watch' | grep -v grep || true
  done <<< "$(printf '%s\n' "$forms" | sort -u)"
  if [ -f "$DATA/watcher.json" ]; then
    pid="$(python3 -c 'import json,sys,time
try:
    d=json.load(open(sys.argv[1])); print(int(d["pid"]) if time.time()-float(d["t"])<600 else "")
except Exception: print("")' "$DATA/watcher.json")"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "$pid $(ps -o ppid= -p "$pid" | tr -d ' ') (from $DATA/watcher.json)"
    fi
  fi
}
