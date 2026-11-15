"""Is a newer release out? At most one GitHub request a day, cached in DATA/update.json. See docs/design.md (Update check).

Offline, rate-limited or any other failure means "no news": the page shows no badge and nothing logs an error
to the user. The request is a plain unauthenticated GET of the public releases API; it sends nothing about the
catalog or the user beyond what any HTTPS request does (an IP address and a generic User-Agent)."""
import json
import os
import re
import threading
import time
import urllib.request

REPO = "jachai/artifact-explorer"
URL = "https://api.github.com/repos/%s/releases/latest" % REPO
CACHE = "update.json"
EVERY = 86400  # seconds between checks, also after a failed one
TIMEOUT = 3
BUDGET = 3  # total seconds a check may take (DNS and slow reads are not bounded by the socket timeout)
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
    """The latest release tag from GitHub, or None. Never raises."""
    req = urllib.request.Request(URL, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "artifact-explorer/%s" % version})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            tag = json.loads(r.read(200_000).decode("utf-8")).get("tag_name")
        return tag if parse(tag) else None
    except Exception:  # offline, DNS, 403 rate limit, bad JSON: all mean "no news"
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
