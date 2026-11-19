"""Is a newer release out? At most one check a day, cached in DATA/update.json. See docs/design.md (Update check).

Offline, rate-limited or any other failure means "no news": the page shows no badge and nothing logs an error
to the user. The check is a plain unauthenticated GET of the public releases API; it sends nothing about the
catalog or the user beyond what any HTTPS request does (an IP address and a generic User-Agent).

When the API gives no answer (a private repo answers 404, a repo with no release yet the same), the check asks
the marketplace clone Claude Code already keeps instead: `git fetch origin HEAD` there, with the user's own git
credentials and no prompt, then the version in .claude-plugin/plugin.json of what it fetched. That is the
version `/plugin update` would install. The fetch only moves FETCH_HEAD; branches and the checkout stay as
Claude Code left them."""
import json
import os
import re
import subprocess
import threading
import time
import urllib.request

import common

REPO = "jachai/artifact-explorer"
URL = "https://api.github.com/repos/%s/releases/latest" % REPO
CACHE = "update.json"
EVERY = 86400  # seconds between checks, also after a failed one
TIMEOUT = 3
GIT_TIMEOUT = 10  # seconds for each git call of the marketplace-clone fallback
BUDGET = TIMEOUT + 2 * GIT_TIMEOUT + 2  # total seconds a check may take (DNS and slow reads are not bounded by
# the socket timeout); a check runs at most once a day and the cache is stamped before it starts
UPDATE_CMDS = ["/plugin marketplace update artifact-explorer", "/plugin update artifact-explorer@artifact-explorer"]


def parse(v):
    """(major, minor, patch) from "v0.2.1" or "0.2.1"; None when it is not a version."""
    m = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)\s*$", str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def newer(latest, current):
    a, b = parse(latest), parse(current)
    return bool(a and b and a > b)


def enabled(cfg):
    if os.environ.get("AE_UPDATE_CHECK", "").strip().lower() in ("0", "false", "no", "off"):
        return False
    return (cfg.get("page") or {}).get("update_check", True) is not False


def fetch(version):
    """The latest version: the GitHub release API first, the marketplace clone when that has no answer. None
    when neither does. Never raises."""
    return fetch_release(version) or fetch_clone()


def fetch_release(version):
    """The latest release tag from GitHub, or None. Never raises."""
    req = urllib.request.Request(URL, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "artifact-explorer/%s" % version})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            tag = json.loads(r.read(200_000).decode("utf-8")).get("tag_name")
        return tag if parse(tag) else None
    except Exception:  # offline, DNS, 403 rate limit, 404 private repo, bad JSON: all mean "no news"
        return None


def _git(args, cwd):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")  # never wait on a password prompt
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return subprocess.run(["git", "-C", cwd] + args, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT, check=True).stdout


def fetch_clone(loc=None):
    """The plugin version on the default branch of the marketplace's origin, read through its local clone with
    the user's git credentials ("v0.2.3"), or None. Never raises."""
    try:
        loc = loc or common.marketplace_dir()
        if not loc:
            return None
        _git(["fetch", "--quiet", "--no-tags", "origin", "HEAD"], loc)
        raw = _git(["show", "FETCH_HEAD:.claude-plugin/plugin.json"], loc)
        v = parse(json.loads(raw.decode("utf-8")).get("version"))
        return "v%d.%d.%d" % v if v else None
    except Exception:  # no git, no network, no credentials, timeout, bad JSON: all mean "no news"
        return None


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        return c if isinstance(c, dict) and isinstance(c.get("checked"), (int, float)) else None
    except (OSError, ValueError):
        return None


def _write(path, now, tag):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"checked": now, "latest": tag}, f)
        os.replace(tmp, path)
    except OSError:
        pass


def latest(data, version, now=None, get=None):
    """The latest release tag: from the cache when it is under a day old, else one request (cached, also when
    it fails). `get` replaces the request in tests."""
    now = time.time() if now is None else now
    path = os.path.join(data, CACHE)
    c = _read(path)
    if c is not None and 0 <= now - c["checked"] < EVERY:
        return c.get("latest")
    keep = c.get("latest") if c is not None else None
    _write(path, now, keep)  # stamped first: a hang below cannot repeat on every pass
    box = []

    def run():
        try:
            box.append((get or fetch)(version))
        except Exception:
            pass
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(BUDGET)
    tag = box[0] if box else None
    if tag is None:
        return keep  # a failed check keeps the last good answer
    _write(path, now, tag)
    return tag


def badge(data, version, cfg, now=None, get=None):
    """What the page bakes in: {"latest", "cmds"} when a newer release is out, else None."""
    if not enabled(cfg):
        return None
    tag = latest(data, version, now, get)
    if not newer(tag, version):
        return None
    return {"latest": "v%d.%d.%d" % parse(tag), "cmds": UPDATE_CMDS}
