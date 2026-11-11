"""explorer.db: schema and the only write helpers. See docs/design.md#schema."""
import json
import os
import re
import sqlite3
import time

import common

SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts(
  id TEXT PRIMARY KEY, uuid TEXT, url TEXT, title TEXT, kind TEXT, owned INTEGER,
  creator TEXT, sharing TEXT, size INTEGER,
  created REAL, modified REAL, last_accessed REAL, last_access_by TEXT,
  version TEXT, seq INTEGER, local_path TEXT,
  description TEXT, desc_source TEXT, desc_status TEXT,
  thumb TEXT, thumb_source TEXT, thumb_status TEXT,
  first_seen REAL, updated REAL);
CREATE TABLE IF NOT EXISTS events(
  artifact_id TEXT, ts REAL, kind TEXT, source TEXT, session_id TEXT, cwd TEXT, repo TEXT, detail TEXT,
  UNIQUE(artifact_id, ts, kind, source));
CREATE INDEX IF NOT EXISTS events_by_artifact ON events(artifact_id);
CREATE TABLE IF NOT EXISTS spend(day TEXT PRIMARY KEY, usd REAL, runs INTEGER);
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
"""

FIELDS = ("uuid url title kind owned creator sharing size created modified last_accessed last_access_by "
          "version seq local_path description desc_source desc_status thumb thumb_source thumb_status").split()
DESC_RANK = {None: 0, "title": 1, "publish": 2, "describer": 3, "import": 4}
URL_ID = re.compile(r"^https://claude\.ai/(?:code/)?artifact/([A-Za-z0-9-]{10,})(?=$|[/?#])")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def connect(data, timeout=30):
    con = sqlite3.connect(os.path.join(data, "explorer.db"), timeout=timeout)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")  # readers (SessionStart) never wait on a long watcher pass
    con.executescript(SCHEMA)
    _migrate(con, data)
    return con


SCHEMA_VERSION = 1  # PRAGMA user_version once the one-off fixes below have run


def _migrate(con, data):
    """One-off fixes for catalogs written by 0.1.0. A busy database skips them until the next open."""
    if con.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
        return
    try:
        con.execute("UPDATE artifacts SET thumb_status='pending' WHERE thumb_status IS NULL")
        # rescan browser history once: 0.1.0 kept a row's first title only, often "Page not found"
        state_set(con, "history_cursors", {})
        fold_twins(con)
        common.rekey_overrides(data, {r[0]: r[1] for r in con.execute(
            "SELECT uuid, id FROM artifacts WHERE uuid IS NOT NULL AND uuid<>id")})
        con.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
        con.commit()
    except sqlite3.OperationalError:
        con.rollback()


def _data_of(con):
    path = con.execute("PRAGMA database_list").fetchone()[2]
    return os.path.dirname(path) if path else None


def id_from_url(url):
    m = URL_ID.match(url or "")
    return m.group(1) if m else None


def resolve(con, aid, uuid=None):
    """The one row id for an artifact. A row is keyed by its short id once known, else by its uuid.
    A uuid-form id maps to the row that carries that uuid; learning (short id, uuid) folds a uuid-keyed
    row into the short-id row. Returns the id to use."""
    if not aid:
        return None
    if UUID.match(aid):
        r = con.execute("SELECT id FROM artifacts WHERE uuid=? AND id<>?", (aid, aid)).fetchone()
        if r is None:
            return aid
        merge(con, aid, r[0])
        return r[0]
    if uuid and uuid != aid and UUID.match(uuid):
        merge(con, uuid, aid)
    return aid


def fold_twins(con):
    """Fold a uuid-keyed row into the short-id row of the same title when that title names exactly one of
    each and the short-id row has no other uuid. A claude.ai/code/artifact/<uuid> visit is the only place a
    uuid row comes from, and the artifact list gives short ids without uuids, so the title is the one link.
    Returns the number folded."""
    by_title = {}
    for r in con.execute("SELECT id, uuid, title FROM artifacts WHERE title IS NOT NULL AND title<>''"):
        by_title.setdefault(r["title"], ([], []))[0 if UUID.match(r["id"]) else 1].append(r)
    n = 0
    for uu, short in by_title.values():
        if len(uu) == 1 and len(short) == 1 and short[0]["uuid"] in (None, uu[0]["id"]):
            merge(con, uu[0]["id"], short[0]["id"])
            n += 1
    return n


def merge(con, src, dst):
    """Fold row `src` (and its events) into row `dst`, keeping the non-null and most precise fields; delete `src`."""
    s = get(con, src)
    if s is None:
        return
    data = _data_of(con)
    if data:  # config.toml overrides keyed by the old id follow the row
        common.rekey_overrides(data, {src: dst})
    con.execute("UPDATE OR IGNORE events SET artifact_id=? WHERE artifact_id=?", (dst, src))
    con.execute("DELETE FROM events WHERE artifact_id=?", (src,))
    d = get(con, dst)
    if d is None:
        con.execute("UPDATE artifacts SET id=?, uuid=COALESCE(uuid, ?) WHERE id=?",
                    (dst, src if UUID.match(src) else None, src))
        return
    con.execute("DELETE FROM artifacts WHERE id=?", (src,))
    f = {k: s[k] for k in FIELDS if d[k] is None and s[k] is not None}
    groups = (("description", "desc_source", "desc_status"), ("thumb", "thumb_source", "thumb_status"),
              ("modified", "version", "seq", "local_path"), ("last_accessed", "last_access_by"))
    wins = (DESC_RANK.get(s["desc_source"], 0) > DESC_RANK.get(d["desc_source"], 0),
            s["thumb"] is not None and d["thumb"] is None,
            s["modified"] is not None and (d["modified"] is None or s["modified"] > d["modified"]),
            s["last_accessed"] is not None and (d["last_accessed"] is None or s["last_accessed"] > d["last_accessed"]))
    for keys, win in zip(groups, wins):
        for k in keys:
            if win:
                f[k] = s[k]
            elif d[k] is not None:
                f.pop(k, None)
    for k in ("created", "first_seen"):
        if s[k] is not None and (d[k] is None or s[k] < d[k]):
            f[k] = s[k]
    if UUID.match(src) and d["uuid"] is None:
        f["uuid"] = src
    f["updated"] = time.time()
    con.execute("UPDATE artifacts SET %s WHERE id=?" % ",".join(k + "=?" for k in f), list(f.values()) + [dst])


def get(con, aid):
    return con.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone()


def upsert_artifact(con, aid, **fields):
    """Insert or update one artifact. A None value never overwrites; a description only replaces one of
    equal or lower source rank. Returns True when the row changed."""
    bad = set(fields) - set(FIELDS)
    if bad:
        raise ValueError("unknown fields: %s" % sorted(bad))
    now = time.time()
    row = get(con, aid)
    vals = {k: v for k, v in fields.items() if v is not None}
    if row is not None and "description" in vals:
        if DESC_RANK.get(vals.get("desc_source"), 0) < DESC_RANK.get(row["desc_source"], 0):
            for k in ("description", "desc_source", "desc_status"):
                vals.pop(k, None)
    if row is None:
        vals.setdefault("thumb_status", "pending")  # every new row waits for a thumbnail (or "none")
        vals.update(first_seen=now, updated=now)
        cols = ["id"] + list(vals)
        con.execute("INSERT INTO artifacts(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))),
                    [aid] + list(vals.values()))
        return True
    changed = {k: v for k, v in vals.items() if row[k] != v}
    if not changed:
        return False
    changed["updated"] = now
    con.execute("UPDATE artifacts SET %s WHERE id=?" % ",".join(k + "=?" for k in changed),
                list(changed.values()) + [aid])
    return True


def add_event(con, aid, ts, kind, source, session_id=None, cwd=None, repo=None, detail=None):
    """Record one event (duplicates ignored); keeps last_accessed current. Returns True when new."""
    cur = con.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?)",
                      (aid, ts, kind, source, session_id, cwd, repo,
                       json.dumps(detail) if detail is not None else None))
    if cur.rowcount and kind in ("visit", "agent_read", "agent_open"):
        con.execute("UPDATE artifacts SET last_accessed=?, last_access_by=? WHERE id=? AND "
                    "(last_accessed IS NULL OR last_accessed<?)",
                    (ts, "browser" if kind == "visit" else "agent", aid, ts))
    return bool(cur.rowcount)


def state_get(con, key, default=None):
    r = con.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else default


def state_set(con, key, value):
    con.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, json.dumps(value)))


def today():
    return time.strftime("%Y-%m-%d")


def spend_today(con):
    r = con.execute("SELECT usd FROM spend WHERE day=?", (today(),)).fetchone()
    return r[0] if r else 0.0


def add_spend(con, usd):
    con.execute("INSERT INTO spend VALUES(?,?,1) ON CONFLICT(day) DO UPDATE SET usd=usd+excluded.usd, runs=runs+1",
                (today(), usd))
