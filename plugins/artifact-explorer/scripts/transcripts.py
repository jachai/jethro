"""Incremental scan of Claude Code transcripts for Artifact tool calls (publish, read, open)."""
import glob
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import db  # noqa: E402
import hook  # noqa: E402

MAX_PENDING = 200


def roots():
    return [os.path.join(common.claude_dir(), "projects")]


def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _blocks(obj):
    c = (obj.get("message") or {}).get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def _scan_file(con, path, off, pending):
    """Read complete lines from `off`; returns (new_events, new_offset)."""
    new = 0
    with open(path, "rb") as f:
        f.seek(off)
        for line in f:
            if not line.endswith(b"\n"):
                break
            off += len(line)
            if b'"Artifact"' in line and b'"tool_use"' in line:
                kind = "use"
            elif b"toolUseResult" in line and any(i in line for i in pending):
                kind = "result"
            else:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if kind == "use":
                for b in _blocks(obj):
                    if b.get("type") == "tool_use" and b.get("name") == "Artifact" and b.get("id"):
                        pending[b["id"].encode()] = b.get("input")
                continue
            ts = _ts(obj.get("timestamp"))
            for b in _blocks(obj):
                key = (b.get("tool_use_id") or "").encode()
                if b.get("type") == "tool_result" and key in pending and ts is not None:
                    new += hook.record(con, pending.pop(key), obj.get("toolUseResult"), ts, "transcript",
                                       obj.get("sessionId"), obj.get("cwd"))
    return new, off


def scan(con, data):
    """Returns the number of new events."""
    cursors = db.state_get(con, "transcript_cursors", {})
    pending = {k.encode(): v for k, v in db.state_get(con, "transcript_pending", {}).items()}
    seen, new = {}, 0
    for root in roots():
        for path in glob.glob(os.path.join(root, "*", "*.jsonl")):
            try:
                st = os.stat(path)
                ino, off = cursors.get(path, [None, 0])
                if ino != st.st_ino or st.st_size < off:
                    off = 0
                if st.st_size > off:
                    n, off = _scan_file(con, path, off, pending)
                    new += n
                seen[path] = [st.st_ino, off]
            except OSError as e:
                common.log(data, "transcripts %s: %s" % (path, e))
    keep = list(pending.items())[-MAX_PENDING:]
    db.state_set(con, "transcript_cursors", seen)
    db.state_set(con, "transcript_pending", {k.decode(): v for k, v in keep})
    con.commit()
    return new
