"""Description queue: ingest Artifact-list rows, set descriptions, launch the background describer, status."""
import json
from html.parser import HTMLParser
import os
import shutil
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import db  # noqa: E402

PENDING = "desc_status='pending' AND (description IS NULL OR description='')"  # status counts only


def first(row, *keys):
    for k in keys:
        if row.get(k) not in (None, ""):
            return row[k]
    return None


def to_ts(v):
    """Unix seconds from a number (seconds or ms) or an ISO-8601 string; None when unknown."""
    if isinstance(v, (int, float)):
        return v / 1000.0 if v > 1e11 else float(v)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    return None


def owned_of(row):
    scope = str(first(row, "scope") or "").lower()
    if scope in ("mine", "own", "owned"):
        return 1
    if scope in ("shared", "shared_with_me"):
        return 0
    o = row.get("owned")
    return None if o is None else int(bool(o))


def ingest_list(data, file):
    with open(file, encoding="utf-8") as f:
        rows = json.load(f)
    if isinstance(rows, dict):
        rows = first(rows, "artifacts", "items", "rows") or []
    con = db.connect(data)
    n = 0
    for r in rows:
        aid = db.resolve(con, db.id_from_url(first(r, "url", "link")) or first(r, "id"))
        if not aid:
            continue
        old = db.get(con, aid)
        modified = to_ts(first(r, "updated", "modified", "updatedAt"))
        if modified is not None and old is not None and (old["modified"] or 0) >= modified:
            modified = None  # the list gives a date only; never replace a more precise time with midnight
        desc = first(r, "description", "desc", "summary")
        sharing = first(r, "sharing")
        if desc:
            status = "ok"
        else:  # no new text: a row without a description (and not skipped) waits for one
            status = "pending" if old is None or (not old["description"] and old["desc_status"] in (None, "pending")) else None
        db.upsert_artifact(
            con, aid, url=first(r, "url", "link"), title=first(r, "title", "name"), kind=first(r, "kind", "type"),
            owned=owned_of(r), size=first(r, "size"), created=to_ts(first(r, "created", "createdAt")),
            modified=modified,
            sharing=sharing if sharing is None or isinstance(sharing, str) else json.dumps(sharing),
            creator=first(r, "creator", "owner", "author") if owned_of(r) == 0 else None,
            description=desc, desc_source="publish" if desc else None,
            desc_status=status)
        n += 1
    con.commit()
    print("ingested %d rows" % n)
    return 0


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, s):
        if not self.skip and s.strip():
            self.out.append(s.strip())


def excerpt(path, chars=3000):
    """Visible text of a saved artifact file (HTML or plain text), whitespace-collapsed and capped."""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read(2_000_000)
    if "<" in raw and ">" in raw:
        p = _Text()
        p.feed(raw)
        raw = " ".join(p.out)
    return " ".join(raw.split())[:chars]


def set_desc(data, aid, text):
    con = db.connect(data)
    db.upsert_artifact(con, aid, description=text.strip()[:200], desc_source="describer", desc_status="ok")
    con.commit()
    return 0


def set_sharing(data, aid, text):
    con = db.connect(data)
    db.upsert_artifact(con, aid, sharing=" ".join(text.split())[:80])
    con.commit()
    return 0


COLS = "id,url,title,owned,thumb_status,desc_status,modified,local_path"


def list_rows(con, owned=False, desc_status=None, thumb_status=None, limit=None, need_desc=False):
    """The one row query: `ae rows`, `ae pending` and the describer launch all come through here."""
    where, args = [], []
    if owned:
        where.append("owned=1")
    if desc_status:
        where.append("desc_status=?")
        args.append(desc_status)
    if thumb_status:
        where.append("thumb_status=?")
        args.append(thumb_status)
    if need_desc:
        where.append("(description IS NULL OR description='')")
    sql = "SELECT %s FROM artifacts%s ORDER BY owned DESC, modified DESC, id" % (
        COLS, " WHERE " + " AND ".join(where) if where else "")
    if limit is not None:
        sql += " LIMIT %d" % limit
    return [dict(r) for r in con.execute(sql, args)]


def rows(data, **kw):
    print(json.dumps(list_rows(db.connect(data), **kw)))
    return 0


def pending_rows(con, owned_only):
    return list_rows(con, owned=owned_only, desc_status="pending", need_desc=True)


def pending(data, owned_only=False, as_json=False):
    rs = pending_rows(db.connect(data), owned_only)
    if as_json:
        print(json.dumps(rs))
    else:
        for r in rs:
            print("%s\t%s\t%s" % (r["id"], r["title"] or "", r["url"] or ""))
    return 0


def launch(data):
    """Start one background describer run when it is due. Prints nothing."""
    opts = common.options()
    con = db.connect(data)
    rows = pending_rows(con, owned_only=True)
    if not rows or db.spend_today(con) >= opts["describe_daily_cap"]:
        return 0
    now = time.time()
    claude = shutil.which("claude")
    if now - db.state_get(con, "describer_last", 0) < opts["watch_interval"] * 60 or not claude:
        return 0
    argv = [claude, "--bg", "--model", opts["describe_model"], "--name", "artifact-explorer describer"]
    if os.path.basename(os.path.normpath(data)).endswith("-inline"):
        # loaded with --plugin-dir (development): the new session must load it the same way
        argv += ["--plugin-dir", common.ROOT]
    argv.append("/artifact-explorer:refresh describe-only")
    if common.detach(argv, cwd=data):
        db.state_set(con, "describer_last", now)
        db.add_spend(con, 0.05 + 0.01 * min(len(rows), 10))
        con.commit()
        common.log(data, "describer launched for %d pending rows" % len(rows))
    else:
        common.log(data, "describer launch failed")
    return 0


def status(data, as_json=False):
    con = db.connect(data)
    one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    out = {
        "total": one("SELECT COUNT(*) FROM artifacts"),
        "mine": one("SELECT COUNT(*) FROM artifacts WHERE owned=1"),
        "shared": one("SELECT COUNT(*) FROM artifacts WHERE owned=0"),
        "unknown": one("SELECT COUNT(*) FROM artifacts WHERE owned IS NULL"),
        "pending_descriptions": one("SELECT COUNT(*) FROM artifacts WHERE " + PENDING),
        "thumbs_missing": one("SELECT COUNT(*) FROM artifacts WHERE thumb_status IN ('pending','failed')"),
        "last_pass": db.state_get(con, "last_pass"),
        "spend_today": round(db.spend_today(con), 2),
        "spend_cap": common.options()["describe_daily_cap"]}
    if as_json:
        print(json.dumps(out))
        return 0
    lp = out["last_pass"]
    print("artifacts: %(total)d (mine %(mine)d, shared %(shared)d, unknown %(unknown)d)" % out)
    print("descriptions pending: %(pending_descriptions)d, thumbnails missing: %(thumbs_missing)d" % out)
    print("last pass: %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(lp)) if lp else "never"))
    print("describer spend today: $%(spend_today).2f of $%(spend_cap).2f" % out)
    return 0
