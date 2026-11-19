#!/usr/bin/env python3
"""guide_gh: ask GitHub (through the `gh` CLI) what state a PR is in, cached, and never in the way.

    pr_state(number, repo, cache=None, now=None)
        -> {"state": "OPEN" | "MERGED" | "CLOSED", "mergedAt": "<ISO time>" or None}, or None
    repo_for(ledger, text="", number=None) -> "owner/name" or None
    set_budget(seconds=None)                  one overall deadline for every gh call this process makes

pr_state runs `gh pr view <number> --repo <owner/name> --json state,mergedAt`, 5 s at most. It needs the repo: with
none it returns None and never runs gh, because gh would answer for whatever repository the current directory is in,
and a "merged" from another repo's PR #N would close the wrong row. repo_for finds the repo: from `text` itself
(`owner/name#N`, a PR link, a github.com/owner/name link), else from the ledger's Scope (its `Scope:` line and any
`## Scope` section) when that names exactly one repo, as `owner/name` or a github.com link. Anything else is None:
the caller treats the PR as unchecked ("repo unknown"), never as the current directory's.

Each answer is cached for CACHE_SECONDS (10 minutes) in a JSON file: `cache`, by default
$CLAUDE_CONFIG_DIR/session-guide/gh-cache.json (default ~/.claude), next to the guide markers. A failed or timed-out
call is cached for the same 10 minutes as "no answer", so a hook that asks on every prompt waits at most once in
that time, not once per prompt.

The budget: a hook has a hard timeout (10 s), so the hook calls set_budget() first: from then on all gh calls of the
process share one deadline (`seconds`, else SESSION_GUIDE_GH_BUDGET, default 3 s). Each call gets min(5 s, the time
left), and once the budget is spent pr_state returns None at once without running gh. A call cut short by the
budget, or skipped, is not cached as a failure: it is unchecked, and the next prompt asks again. Without set_budget
(the command line) each call has its own 5 s.

It fails open: None, never an exception and never a hang, when gh is switched off (SESSION_GUIDE_GH=0, or off / no /
false), not installed, errors (not logged in, no such PR, no network), times out or prints something it can't read.
Callers treat None as "not checked". Python 3 stdlib only.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

CACHE_SECONDS = 600  # an answer (or a failure) is reused this long
TIMEOUT = 5  # seconds gh gets before the call counts as failed
BUDGET = 3.0  # seconds all gh calls of one hook run share (SESSION_GUIDE_GH_BUDGET)
STATES = ("OPEN", "MERGED", "CLOSED")
SWITCH = "SESSION_GUIDE_GH"  # 0 / off / no / false turns every gh call off
CUT = object()  # ask_gh's answer when the budget, not gh, ended the call: unchecked, never cached

NAME = r"[A-Za-z0-9][\w.-]*/[\w.-]*[A-Za-z0-9_]"
REF = re.compile(r"(?<![\w./~@:-])(%s)#(\d{1,6})\b" % NAME)  # owner/name#12
LINK = re.compile(r"github\.com/(%s?)(?:\.git)?(?:/pull/(\d{1,6}))?(?![\w.-])" % r"[A-Za-z0-9][\w.-]*/[\w.-]+")
BARE = re.compile(r"(?<![\w./~@:-])(%s)(?![\w/-])" % NAME)  # owner/name, in the Scope only

_deadline = None  # monotonic time the budget ends, or None: no budget


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def cache_path():
    return os.path.join(config_dir(), "session-guide", "gh-cache.json")


def enabled():
    return os.environ.get(SWITCH, "1").strip().lower() not in ("0", "off", "no", "false")


def set_budget(seconds=None):
    """Start one deadline for every later gh call of this process: `seconds`, else SESSION_GUIDE_GH_BUDGET, else 3."""
    global _deadline
    if seconds is None:
        try:
            seconds = float(os.environ.get("SESSION_GUIDE_GH_BUDGET", BUDGET))
        except ValueError:
            seconds = BUDGET
    _deadline = time.monotonic() + max(0.0, float(seconds))
    return seconds


def clear_budget():
    """Back to one 5 s timeout per call (the command line's behaviour)."""
    global _deadline
    _deadline = None


def budget_left():
    """Seconds left in the budget, or None when there is no budget."""
    return None if _deadline is None else max(0.0, _deadline - time.monotonic())


def pr_number(number):
    """The PR number in `number` (12, "12", "#12"), or None."""
    try:
        n = int(str(number).strip().lstrip("#"))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def repos_in(text, number=None):
    """(repos named for PR `number`, every repo the text names), in order, from owner/name#N refs and github links."""
    mine, every = [], []
    for found in REF.finditer(text or ""):
        every.append(found.group(1))
        if number is not None and int(found.group(2)) == number:
            mine.append(found.group(1))
    for found in LINK.finditer(text or ""):
        every.append(found.group(1))
        if number is not None and found.group(2) and int(found.group(2)) == number:
            mine.append(found.group(1))
    return mine, every


def unique(repos):
    seen = {}
    for repo in repos:
        seen.setdefault(repo.lower(), repo)
    return list(seen.values())


def scope_repos(ledger):
    """The repos a ledger's Scope names: its `Scope:` line(s) before the first section, and a `## Scope` section."""
    try:
        with open(ledger, errors="replace") as f:
            lines = f.read().splitlines()
    except (OSError, TypeError, ValueError):
        return []
    found, head, inside = [], True, False
    for line in lines:
        if line.startswith("## "):
            head, inside = False, line.strip().lower().startswith("## scope")
            continue
        if inside or head and line.lstrip().lower().startswith("scope:"):
            found += [m.group(1) for m in LINK.finditer(line)]
            found += [m.group(1) for m in BARE.finditer(LINK.sub(" ", line))]
    return unique(found)


def repo_for(ledger, text="", number=None):
    """The "owner/name" PR `number` (or the PRs in `text`) belongs to, or None when it can't be told.

    A ref for that very number in the text wins (`owner/name#N`, a PR link); else the one repo the text names; else,
    when the text names none, the one repo the ledger's Scope names. Two candidates, or none, is None."""
    try:
        n = pr_number(number) if number is not None else None
        mine, every = repos_in(text, n)
        if unique(mine):
            return unique(mine)[0] if len(unique(mine)) == 1 else None
        if every:
            return unique(every)[0] if len(unique(every)) == 1 else None
        scoped = scope_repos(ledger) if ledger else []
        return scoped[0] if len(scoped) == 1 else None
    except Exception:
        return None


def cache_key(number, repo):
    return "%s#%d" % (repo.strip().lower(), number)


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


def ask_gh(number, repo, timeout=TIMEOUT):
    """gh's answer for one PR; None on a failure; CUT when a timeout shorter than TIMEOUT (the budget) ran out."""
    if shutil.which("gh") is None:
        return None
    cmd = ["gh", "pr", "view", str(number), "--repo", repo, "--json", "state,mergedAt"]
    env = dict(os.environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return CUT if timeout < TIMEOUT else None
    except (OSError, ValueError):
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
    """{"state": "OPEN" | "MERGED" | "CLOSED", "mergedAt": str or None} for PR `number` in `repo` ("owner/name"), or
    None when there is no repo, gh is off, missing, fails or times out, or the budget is spent."""
    try:
        if not enabled():
            return None
        n = pr_number(number)
        repo = (repo or "").strip()
        if n is None or not re.match(r"^%s$" % NAME, repo):
            return None  # never the current directory's repository
        now = time.time() if now is None else float(now)
        path = cache or cache_path()
        key = cache_key(n, repo)
        data = load_cache(path)
        hit = data.get(key)
        if isinstance(hit, dict) and 0 <= now - float(hit.get("at", 0)) < CACHE_SECONDS:
            answer = hit.get("answer")
            return dict(answer) if isinstance(answer, dict) and answer.get("state") in STATES else None
        left = budget_left()
        if left is not None and left <= 0.05:
            return None  # budget spent: unchecked, not a failure
        answer = ask_gh(n, repo, TIMEOUT if left is None else min(TIMEOUT, left))
        if answer is CUT:
            return None
        if answer is None and shutil.which("gh") is None:
            return None  # not installed: nothing to wait for, so nothing to cache
        data[key] = {"at": now, "answer": answer}
        save_cache(path, data, now)
        return answer
    except Exception:  # fail open
        return None


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2 or args[0] in ("-h", "--help"):
        print("usage: guide_gh.py <PR number> <owner/name>")
        sys.exit(0)
    print(json.dumps(pr_state(args[0], args[1])))
