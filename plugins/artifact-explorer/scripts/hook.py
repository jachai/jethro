"""PostToolUse(Artifact) and SessionStart hook. Also holds record(), the one place an Artifact call becomes rows."""
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import db  # noqa: E402

DUP_WINDOW = 120  # the hook and the transcript scan both see a call; same session within this many seconds = one event


def _dict(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return {}
    return v if isinstance(v, dict) else {}


def record(con, tin, tresp, ts, source, session_id=None, cwd=None):
    """Store one Artifact tool call (tool_input, tool_response). Returns 1 when a new event was added, else 0."""
    tin, tresp = _dict(tin), _dict(tresp)
    action = tin.get("action") or "publish"
    url = tresp.get("url") or tin.get("url")
    aid = db.id_from_url(url) or tresp.get("artifact_id")
    if not aid:
        return 0
    publish = (action == "publish" and tin.get("file_path") and not tin.get("asset") and not tin.get("asset_ids")
               and tresp.get("url"))
    if not publish and action not in ("read", "open"):
        return 0
    kind = "publish" if publish else "agent_" + action
    if con.execute("SELECT 1 FROM events WHERE artifact_id=? AND kind=? AND session_id IS ? AND ts BETWEEN ? AND ?",
                   (aid, kind, session_id, ts - DUP_WINDOW, ts + DUP_WINDOW)).fetchone():
        return 0
    detail = {"version": tresp.get("version"), "seq": tresp.get("seq"), "label": tin.get("label")} if publish else None
    if not db.add_event(con, aid, ts, kind, source, session_id, cwd, common.repo_of(cwd), detail):
        return 0
    row = db.get(con, aid)
    fresh = row is None
    owned = tresp.get("owned")
    f = dict(url=url, uuid=tresp.get("artifact_id"), title=tresp.get("title"),
             owned=int(owned) if isinstance(owned, bool) else None)
    if fresh:
        f["desc_status"] = "pending"
    if publish:
        latest = con.execute("SELECT MAX(ts) FROM events WHERE artifact_id=? AND kind='publish'", (aid,)).fetchone()[0]
        old = row["created"] if row else None
        f["created"] = ts if old is None or ts < old else None
        if ts >= latest:  # an older replayed publish must not roll back the newer fields
            f.update(local_path=tresp.get("path") or tin.get("file_path"), version=tresp.get("version"),
                     seq=tresp.get("seq"), modified=ts, thumb_status="pending")
            if tin.get("description"):
                f.update(description=tin["description"], desc_source="publish", desc_status="ok")
        else:
            for k in ("url", "uuid", "title", "owned"):
                f.pop(k)
    db.upsert_artifact(con, aid, **f)
    return 1


def _start(data):
    con = db.connect(data)
    n = con.execute("SELECT COUNT(*) FROM artifacts WHERE owned=0 AND desc_status='pending'").fetchone()[0]
    con.close()
    if n:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext":
              "Artifact Explorer: %d shared artifacts are waiting for a description. "
              "Run /artifact-explorer:refresh to describe them." % n}}))


def _post(data, p):
    if p.get("tool_name") != "Artifact":
        return
    con = db.connect(data)
    try:
        n = record(con, p.get("tool_input"), p.get("tool_response"), time.time(), "hook",
                   p.get("session_id"), p.get("cwd"))
        con.commit()
        tin, tresp = _dict(p.get("tool_input")), _dict(p.get("tool_response"))
        aid = db.id_from_url(tresp.get("url") or tin.get("url")) or tresp.get("artifact_id")
    finally:
        con.close()
    if n and (tin.get("action") or "publish") == "publish":
        common.detach(common.ae_argv("--data", data, "thumbs", "--id", aid))
        common.detach(common.ae_argv("--data", data, "build"))


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
