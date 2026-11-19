#!/usr/bin/env python3
"""guide_gh: ask GitHub (through the `gh` CLI) what state a PR is in, cached, and never in the way.

    pr_state(number, repo=None, cache=None, now=None)
        -> {"state": "OPEN" | "MERGED" | "CLOSED", "mergedAt": "<ISO time>" or None}, or None

It runs `gh pr view <number> [--repo <owner/repo>] --json state,mergedAt` with a 5 s timeout. Without --repo, gh
answers for the repository of the current directory, so the cache keys such an answer by that directory too.

Each answer is cached for CACHE_SECONDS (10 minutes) in a JSON file: `cache`, by default
$CLAUDE_CONFIG_DIR/session-guide/gh-cache.json (default ~/.claude), next to the guide markers. A failed or timed-out
call is cached for the same 10 minutes as "no answer", so a hook that asks on every prompt waits 5 s at most once in
that time, not once per prompt.

It fails open: None, never an exception and never a hang, when gh is switched off (SESSION_GUIDE_GH=0, or off / no /
false), not installed, errors (not logged in, no such PR, no network), times out or prints something it can't read.
Callers treat None as "not checked". Python 3 stdlib only.
"""
import json
import os
import shutil
import subprocess
import sys
import time

CACHE_SECONDS = 600  # an answer (or a failure) is reused this long
TIMEOUT = 5  # seconds gh gets before the call counts as failed
STATES = ("OPEN", "MERGED", "CLOSED")
SWITCH = "SESSION_GUIDE_GH"  # 0 / off / no / false turns every gh call off


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def cache_path():
    return os.path.join(config_dir(), "session-guide", "gh-cache.json")


def enabled():
    return os.environ.get(SWITCH, "1").strip().lower() not in ("0", "off", "no", "false")


def pr_number(number):
    """The PR number in `number` (12, "12", "#12"), or None."""
    try:
        n = int(str(number).strip().lstrip("#"))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def cache_key(number, repo):
    return "%s#%d" % (repo.strip().lower() if repo else "cwd:" + os.getcwd(), number)


def load_cache(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(path, data, now):
    """Write the cache, dropping entries past their time. Errors are ignored: a cache is never worth one."""
    try:
        data = {k: v for k, v in data.items()
                if isinstance(v, dict) and now - float(v.get("at", 0)) < CACHE_SECONDS}
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        pass


def ask_gh(number, repo):
    """gh's answer for one PR, or None on any failure."""
    if shutil.which("gh") is None:
        return None
    cmd = ["gh", "pr", "view", str(number)] + (["--repo", repo] if repo else []) + ["--json", "state,mergedAt"]
    env = dict(os.environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL, env=env)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if out.returncode != 0:
        return None
    try:
        got = json.loads(out.stdout or "")
    except ValueError:
        return None
    if not isinstance(got, dict):
        return None
    state = str(got.get("state") or "").upper()
    if state not in STATES:
        return None
    merged = got.get("mergedAt") or None
    return {"state": state, "mergedAt": str(merged) if merged else None}


def pr_state(number, repo=None, cache=None, now=None):
    """{"state": "OPEN" | "MERGED" | "CLOSED", "mergedAt": str or None} for PR `number` (in `repo`, "owner/name",
    else the current directory's repository), or None when gh is off, missing, fails or times out."""
    try:
        if not enabled():
            return None
        n = pr_number(number)
        if n is None:
            return None
        repo = (repo or "").strip() or None
        now = time.time() if now is None else float(now)
        path = cache or cache_path()
        key = cache_key(n, repo)
        data = load_cache(path)
        hit = data.get(key)
        if isinstance(hit, dict) and 0 <= now - float(hit.get("at", 0)) < CACHE_SECONDS:
            answer = hit.get("answer")
            return dict(answer) if isinstance(answer, dict) and answer.get("state") in STATES else None
        answer = ask_gh(n, repo)
        if answer is None and shutil.which("gh") is None:
            return None  # not installed: nothing to wait for, so nothing to cache
        data[key] = {"at": now, "answer": answer}
        save_cache(path, data, now)
        return answer
    except Exception:  # fail open
        return None


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("usage: guide_gh.py <PR number> [owner/repo]")
        sys.exit(0)
    print(json.dumps(pr_state(args[0], args[1] if len(args) > 1 else None)))
