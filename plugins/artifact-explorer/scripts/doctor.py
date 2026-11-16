"""`ae doctor`: what runs, what is installed, what the marketplace has, the data folder, the rule, a page check.

Made so a fresh-install test verifies itself (0.1.5): the 0.1.4 test ran 0.1.2 for a day because a
marketplace update does not move an installed plugin, and nothing printed which version was running."""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

KEY = "artifact-explorer@artifact-explorer"
UPDATE_CMD = "claude plugin update " + KEY


def _json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _plugin_version(root):
    d = _json(os.path.join(root, ".claude-plugin", "plugin.json")) if root else None
    return d.get("version") if isinstance(d, dict) else None


def installed():
    """The installed_plugins.json entry for this plugin ({} when not installed), the first scope listed."""
    ents = common.installed_entries()
    return ents[0] if ents else {}


def marketplace():
    """(version, folder) of the marketplace clone, (None, None) when the marketplace is not added."""
    d = _json(os.path.join(common.claude_dir(), "plugins", "known_marketplaces.json"))
    ent = d.get("artifact-explorer") if isinstance(d, dict) else None
    loc = ent.get("installLocation") if isinstance(ent, dict) else None
    return (_plugin_version(loc), loc) if loc else (None, None)


def data_state(data):
    """{exists, artifacts, spend_days, first_seen, config} for the data folder; never creates anything."""
    out = {"exists": os.path.isdir(data), "artifacts": 0, "spend_days": 0, "first_seen": None,
           "config": os.path.exists(os.path.join(data, "config.toml"))}
    path = os.path.join(data, "explorer.db")
    if os.path.exists(path):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
            try:
                out["artifacts"], out["first_seen"] = con.execute(
                    "SELECT COUNT(*), MIN(first_seen) FROM artifacts").fetchone()
                out["spend_days"] = con.execute("SELECT COUNT(*) FROM spend").fetchone()[0]
            finally:
                con.close()
        except sqlite3.Error:
            out["artifacts"] = -1  # there is a catalog file, but it can't be read: not fresh either
    return out


def page_check():
    """Build a page in an empty temp folder with one row and no thumbnail; return [(check, ok)] for the 0.1.4
    page parts a fresh install shows first: status line, stale banner, initials tile."""
    import build
    import db
    tmp = tempfile.mkdtemp(prefix="ae-doctor-")
    try:
        con = db.connect(tmp)
        db.upsert_artifact(con, "doctorcheck0001", title="Doctor check", owned=1, desc_status="pending")
        con.commit()
        con.close()
        html = open(build.build(tmp, max_age=0, update_check=False), encoding="utf-8").read()
        payload = build.collect(tmp, {})[0]
        st = build.status(tmp, time.time())
        return [("status line", 'id="status"' in html and "stale_after" in st),
                ("stale banner", "Page may be stale" in html),
                ("initials tiles", "initialsTile(" in html and payload and payload[0]["thumb"] == "")]
    except Exception as e:  # a page that can't be built is a failed check, reported, not a crash
        return [("page build (%s)" % type(e).__name__, False)]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _day(t):
    return time.strftime("%Y-%m-%d", time.localtime(t)) if t else "?"


def run(data, version, expect="any"):
    """Print the report; return 1 when something the test relies on is wrong (see `expect`), else 0."""
    bad = []
    root = common.ROOT
    print("Artifact Explorer doctor")
    print("  running: %s from %s" % (version, root))
    ent, (mver, mloc) = installed(), marketplace()
    if ent:
        print("  installed (installed_plugins.json): %s at %s, updated %s" % (
            ent.get("version"), ent.get("installPath"), str(ent.get("lastUpdated") or "?")[:10]))
    else:
        print("  installed (installed_plugins.json): not installed")
    print("  marketplace clone: %s" % ("%s at %s" % (mver, mloc) if mloc else "not added"))
    if ent and mver and ent.get("version") != mver:
        print("  MISMATCH: the marketplace has %s but %s is installed. A marketplace update does not move the"
              " installed plugin. Run `%s`, then open a new Claude Code window." % (mver, ent.get("version"), UPDATE_CMD))
        bad.append("installed version is not the marketplace version")
    inst = ent.get("installPath")
    if inst and os.path.realpath(inst) != os.path.realpath(root):
        same = os.path.realpath(os.path.dirname(inst)) == os.path.realpath(os.path.dirname(root))
        if same:
            print("  NOTE: this window runs %s, not the installed %s: open a new window to load it."
                  % (os.path.basename(root), os.path.basename(inst)))
            bad.append("this window does not run the installed version")
    if expect == "installed" and not ent:
        bad.append("not installed")
    s = data_state(data)
    if not s["exists"]:
        print("  data folder: %s (none yet: fresh)" % data)
    elif s["artifacts"] == 0 and not s["spend_days"]:
        print("  data folder: %s (no artifacts yet: fresh%s)" % (data, ", config.toml present" if s["config"] else ""))
    else:
        print("  data folder: %s has %s artifacts (first seen %s), %d days of describer spend%s: NOT a fresh install"
              % (data, "unreadable" if s["artifacts"] < 0 else s["artifacts"], _day(s["first_seen"]),
                 s["spend_days"], ", config.toml" if s["config"] else ""))
        if expect == "fresh":
            bad.append("the data folder already has a catalog")
    print("  permission rule: %s (%s)" % ("present" if common.allow_rule_present() else "missing", " or ".join(common.ALLOW_RULES)))
    checks = page_check()
    print("  page check: " + ", ".join("%s %s" % (n, "ok" if ok else "FAILED") for n, ok in checks))
    bad += ["page check: " + n for n, ok in checks if not ok]
    if bad:
        print("RESULT: NOT OK: " + "; ".join(bad))
        return 1
    print("RESULT: OK")
    return 0
