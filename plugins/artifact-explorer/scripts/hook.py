"""PostToolUse(Artifact) and SessionStart hook. Also holds record(), the one place an Artifact call becomes rows."""
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import db  # noqa: E402

DUP_WINDOW = 120  # the hook and the transcript scan both see a read/open; same session within this many seconds = one event


def _dict(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return {}
    return v if isinstance(v, dict) else {}


def _inside(path, root):
    p, r = (os.path.normcase(os.path.realpath(x)) for x in (path, root))
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _seen(con, aid, kind, session_id, ts, detail):
    """True when this call is already recorded. A publish is identified by its (version, seq); a read/open by
    the same session within DUP_WINDOW seconds."""
    if kind == "publish":
        key = (detail["version"], detail["seq"])
        return key != (None, None) and any(
            (d.get("version"), d.get("seq")) == key
            for d in (json.loads(r[0]) for r in con.execute(
                "SELECT detail FROM events WHERE artifact_id=? AND kind='publish' AND detail IS NOT NULL", (aid,))))
    return con.execute("SELECT 1 FROM events WHERE artifact_id=? AND kind=? AND session_id IS ? AND ts BETWEEN ? AND ?",
                       (aid, kind, session_id, ts - DUP_WINDOW, ts + DUP_WINDOW)).fetchone() is not None


def record(con, data, tin, tresp, ts, source, session_id=None, cwd=None):
    """Store one Artifact tool call (tool_input, tool_response). Calls made from inside the data dir (the
    plugin's own describer) are not recorded. Returns (artifact id, event kind) when a new event was added, else None."""
    tin, tresp = _dict(tin), _dict(tresp)
    if cwd and _inside(cwd, data):
        return None
    action = tin.get("action") or "publish"
    url = tresp.get("url") or tin.get("url")
    publish = action == "publish" and not tin.get("asset") and not tin.get("asset_ids") and tresp.get("url")
    if not publish and action not in ("read", "open"):
        return None
    aid = db.resolve(con, db.id_from_url(url) or tresp.get("artifact_id"), tresp.get("artifact_id"))
    if not aid:
        return None
    kind = "publish" if publish else "agent_" + action
    detail = {"version": tresp.get("version"), "seq": tresp.get("seq"), "label": tin.get("label")} if publish else None
    if _seen(con, aid, kind, session_id, ts, detail):
        return None
    row = db.get(con, aid)
    if row is None:  # the row exists before its first event, so add_event keeps last_accessed
        db.upsert_artifact(con, aid, desc_status="pending")
    if not db.add_event(con, aid, ts, kind, source, session_id, cwd, common.repo_of(cwd), detail):
        return None
    owned = tresp.get("owned")
    f = dict(url=url, uuid=tresp.get("artifact_id"), title=tresp.get("title"),
             owned=int(owned) if isinstance(owned, bool) else None)
    if publish:
        latest = con.execute("SELECT MAX(ts) FROM events WHERE artifact_id=? AND kind='publish'", (aid,)).fetchone()[0]
        old = row["created"] if row else None
        f["created"] = ts if old is None or ts < old else None
        if ts >= latest:  # an older replayed publish must not roll back the newer fields
            fp = tin.get("file_path")
            f.update(local_path=os.path.normpath(os.path.join(cwd or "", fp)) if fp else None,
                     version=tresp.get("version"), seq=tresp.get("seq"), modified=ts, thumb_status="pending")
            if tin.get("description"):
                f.update(description=tin["description"], desc_source="publish", desc_status="ok")
        else:
            for k in ("url", "uuid", "title", "owned"):
                f.pop(k)
    db.upsert_artifact(con, aid, **f)
    return aid, kind


def _start(data):
    con = db.connect(data, timeout=3)
    cond, args = db.window_sql(db.window(con, common.load_config(data)))
    n = con.execute("SELECT COUNT(*) FROM artifacts WHERE owned=0 AND desc_status='pending' AND " + cond, args).fetchone()[0]
    con.close()
    if n:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext":
              "Artifact Explorer: %d shared artifacts are waiting for a description. "
              "Run /artifact-explorer:refresh to describe them." % n}}))


def spool_dir(data):
    return os.path.join(data, "inbox", "hooks")


def _post(data, p):
    """Never touch the database here: a watcher pass can hold it longer than the hook timeout.
    Spool the payload and let a detached `ae ingest-hooks` record it."""
    if p.get("tool_name") != "Artifact":
        return
    d = spool_dir(data)
    os.makedirs(d, exist_ok=True)
    name = "%d-%d.json" % (time.time_ns(), os.getpid())
    tmp = os.path.join(d, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "tool_input": p.get("tool_input"), "tool_response": p.get("tool_response"),
                   "session_id": p.get("session_id"), "cwd": p.get("cwd")}, f)
    os.replace(tmp, os.path.join(d, name))
    common.detach(common.ae_argv("--data", data, "ingest-hooks"))


def ingest(data):
    """Record every spooled hook payload (oldest first), then thumbnail new publishes and rebuild.
    Run by the detached hook child and at the start of every watcher pass."""
    d = spool_dir(data)
    if not os.path.isdir(d):
        return 0
    published = []
    with common.Lock(os.path.join(data, "ingest.lock"), 120) as ok:
        if not ok:
            return 0
        con = db.connect(data)
        try:
            while True:
                names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
                if not names:
                    break
                for n in names:
                    path = os.path.join(d, n)
                    try:
                        with open(path, encoding="utf-8") as f:
                            p = json.load(f)
                        r = record(con, data, p.get("tool_input"), p.get("tool_response"), p.get("ts") or time.time(),
                                   "hook", p.get("session_id"), p.get("cwd"))
                        if r and r[1] == "publish":
                            published.append(r[0])
                        con.commit()
                    except (OSError, ValueError):
                        common.log(data, "ingest-hooks: bad spool file " + n)
                    os.remove(path)
        finally:
            con.close()
    if published:
        import thumbs
        import build
        for aid in dict.fromkeys(published):
            thumbs.run(data, aid=aid)
        build.build(data)
    return 0


def main(data):
    try:
        p = json.loads(sys.stdin.read() or "{}")
        ev = p.get("hook_event_name")
        if ev == "PostToolUse":
            _post(data, p)
        elif ev == "SessionStart":
            _start(data)
    except Exception:
        common.log(data, "hook: " + traceback.format_exc())
    return 0
