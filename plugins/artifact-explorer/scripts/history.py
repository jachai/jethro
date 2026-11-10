"""Browser history scan: claude.ai artifact visits from Chromium-family and Firefox history files."""
import glob
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import db  # noqa: E402

EPOCH_1601 = 11644473600
LIKE = "https://claude.ai/%artifact/%"
IGNORED_TITLES = ("claude", "claude artifact")


def _chromium_bases():
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        r = os.path.join(home, "Library", "Application Support")
        return [("chrome", "Google/Chrome"), ("chromium", "Chromium"), ("edge", "Microsoft Edge"),
                ("brave", "BraveSoftware/Brave-Browser"), ("arc", "Arc/User Data"), ("vivaldi", "Vivaldi")], r
    if os.name == "nt":
        r = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return [("chrome", "Google/Chrome/User Data"), ("chromium", "Chromium/User Data"),
                ("edge", "Microsoft/Edge/User Data"), ("brave", "BraveSoftware/Brave-Browser/User Data"),
                ("vivaldi", "Vivaldi/User Data")], r
    return [("chrome", "google-chrome"), ("chromium", "chromium"), ("edge", "microsoft-edge"),
            ("brave", "BraveSoftware/Brave-Browser"), ("vivaldi", "vivaldi")], os.path.join(home, ".config")


def _firefox_glob():
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "Firefox", "Profiles", "*", "places.sqlite")
    if os.name == "nt":
        r = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return os.path.join(r, "Mozilla", "Firefox", "Profiles", "*", "places.sqlite")
    return os.path.join(home, ".mozilla", "firefox", "*", "places.sqlite")


def sources():
    """[(browser_name, path, kind)] for every history file found; kind is 'chromium' or 'firefox'."""
    out = []
    bases, root = _chromium_bases()
    for name, sub in bases:
        for p in sorted(glob.glob(os.path.join(root, *sub.split("/"), "*", "History"))):
            out.append((name, p, "chromium"))
    out += [("firefox", p, "firefox") for p in sorted(glob.glob(_firefox_glob()))]
    return out


def _stamp(path):
    st = [os.stat(p) for p in (path, path + "-wal") if os.path.exists(p)]
    return [[s.st_mtime, s.st_size] for s in st]


def _query(path, kind, after):
    """Copy the history file (and -wal) to a temp dir and return [(url, title, raw_time)] newer than `after`."""
    tmp = tempfile.mkdtemp(prefix="ae-hist-")
    try:
        dst = os.path.join(tmp, os.path.basename(path))
        shutil.copyfile(path, dst)
        if os.path.exists(path + "-wal"):
            shutil.copyfile(path + "-wal", dst + "-wal")
        con = sqlite3.connect(dst)
        try:
            if kind == "chromium":
                sql = ("SELECT u.url, u.title, v.visit_time FROM visits v JOIN urls u ON u.id=v.url "
                       "WHERE u.url LIKE ? AND v.visit_time>? ORDER BY v.visit_time")
            else:
                sql = ("SELECT p.url, p.title, v.visit_date FROM moz_historyvisits v JOIN moz_places p ON p.id=v.place_id "
                       "WHERE p.url LIKE ? AND v.visit_date>? ORDER BY v.visit_date")
            return con.execute(sql, (LIKE, after)).fetchall()
        finally:
            con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def clean_title(t):
    t = (t or "").strip()
    if t.endswith(" - Claude"):
        t = t[:-len(" - Claude")].strip()
    if not t or t.lower() in IGNORED_TITLES or "not found" in t.lower():
        return None
    return t


def scan(con, data):
    """Add visit events for artifact URLs found in browser history. Returns the number of new events."""
    cursors = db.state_get(con, "history_cursors", {})
    windows = db.state_get(con, "share_windows", [])
    new = 0
    for name, path, kind in sources():
        try:
            stamp = _stamp(path)
            cur = cursors.get(path) or {"t": 0, "stamp": None}
            if cur["stamp"] == stamp:
                continue
            rows = _query(path, kind, cur["t"])
        except (OSError, sqlite3.Error) as e:
            common.log(data, "history %s: %s" % (path, e))
            continue
        for url, title, raw in rows:
            ts = raw / 1e6 - (EPOCH_1601 if kind == "chromium" else 0)
            aid = db.resolve(con, db.id_from_url(url))
            if not aid or any(s <= ts <= (e if e is not None else s + 7200) for s, e in windows):
                continue
            if db.get(con, aid) is None:
                db.upsert_artifact(con, aid, url=url, title=clean_title(title), desc_status="pending")
            new += db.add_event(con, aid, ts, "visit", "browser:" + name)
        if rows:
            cur["t"] = rows[-1][2]
        cursors[path] = {"t": cur["t"], "stamp": stamp}
    db.state_set(con, "history_cursors", cursors)
    con.commit()
    return new
