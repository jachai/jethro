"""Description queue: ingest Artifact-list rows, set descriptions, launch the background describer, status."""
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import db  # noqa: E402

PENDING = "desc_status='pending' AND (description IS NULL OR description='')"


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
        aid = db.id_from_url(first(r, "url", "link")) or first(r, "id")
        if not aid:
            continue
        old = db.get(con, aid)
        desc = first(r, "description", "desc", "summary")
        sharing = first(r, "sharing")
        if desc:
            status = "ok"
        else:  # no new text: a row without a description (and not skipped) waits for one
            status = "pending" if old is None or (not old["description"] and old["desc_status"] in (None, "pending")) else None
        db.upsert_artifact(
            con, aid, url=first(r, "url", "link"), title=first(r, "title", "name"), kind=first(r, "kind", "type"),
            owned=owned_of(r), size=first(r, "size"), created=to_ts(first(r, "created", "createdAt")),
            modified=to_ts(first(r, "updated", "modified", "updatedAt")),
            sharing=sharing if sharing is None or isinstance(sharing, str) else json.dumps(sharing),
            creator=first(r, "creator", "owner", "author") if owned_of(r) == 0 else None,
            description=desc, desc_source="publish" if desc else None,
            desc_status=status)
        n += 1
    con.commit()
    print("ingested %d rows" % n)
    return 0


def set_desc(data, aid, text):
    con = db.connect(data)
    db.upsert_artifact(con, aid, description=text.strip()[:200], desc_source="describer", desc_status="ok")
    con.commit()
    return 0


def set_sharing(data, aid, text):
    con = db.connect(data)
    db.upsert_artifact(con, aid, sharing=text.strip())
    con.commit()
    return 0


def pending_rows(con, owned_only):
    sql = "SELECT id,url,title,kind,owned FROM artifacts WHERE %s%s ORDER BY owned DESC, modified DESC, id" % (
        PENDING, " AND (owned IS NULL OR owned<>0)" if owned_only else "")
    return [dict(r) for r in con.execute(sql)]


def pending(data, owned_only=False, as_json=False):
    rows = pending_rows(db.connect(data), owned_only)
    if as_json:
        print(json.dumps(rows))
    else:
        for r in rows:
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
    if now - db.state_get(con, "describer_last", 0) < opts["watch_interval"] * 60 or not shutil.which("claude"):
        return 0
    argv = ["claude", "--bg", "--model", opts["describe_model"], "--name", "artifact-explorer describer",
            "/artifact-explorer:refresh describe-only"]
    if common.detach(argv, cwd=os.getcwd()):
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
