import io
import json
import os
import unittest
from unittest import mock

import helpers
import common
import db
import hook

URL = "https://claude.ai/artifact/AbCdEfGhIjKlMn"
RESP = {"url": URL, "path": "/x/a.html", "artifact_id": "u-1", "title": "T", "seq": 2, "version": "v2", "owned": True}


def run(data, payload):
    with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), mock.patch.object(common, "detach") as d:
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            rc = hook.main(data)
    return rc, out.getvalue(), d


class HookTest(unittest.TestCase):
    def setUp(self):
        self.data = helpers.tmp()

    def post(self, tin, resp):
        return run(self.data, {"hook_event_name": "PostToolUse", "tool_name": "Artifact", "session_id": "s1",
                               "cwd": self.data, "tool_input": tin, "tool_response": resp})

    def test_publish(self):
        rc, _, d = self.post({"file_path": "/x/a.html", "description": "desc", "label": "L"}, RESP)
        self.assertEqual(rc, 0)
        self.assertEqual(d.call_count, 2)
        con = db.connect(self.data)
        r = db.get(con, "AbCdEfGhIjKlMn")
        self.assertEqual((r["owned"], r["title"], r["version"], r["thumb_status"], r["description"], r["desc_source"]),
                         (1, "T", "v2", "pending", "desc", "publish"))
        e = con.execute("select kind, source, session_id, detail from events").fetchall()
        self.assertEqual(len(e), 1)
        self.assertEqual(json.loads(e[0]["detail"]), {"version": "v2", "seq": 2, "label": "L"})

    def test_read_and_odd_responses(self):
        self.post({"action": "read", "url": URL}, RESP)
        self.post({"action": "list"}, [{"a": 1}])
        self.post({"action": "read", "url": URL}, "some text")
        self.post({"action": "open", "url": URL}, None)
        con = db.connect(self.data)
        self.assertEqual([r[0] for r in con.execute("select kind from events")], ["agent_read", "agent_open"])  # list ignored, repeat read deduped

    def test_garbage(self):
        with mock.patch("sys.stdin", io.StringIO("not json")):
            self.assertEqual(hook.main(self.data), 0)

    def test_session_start(self):
        con = db.connect(self.data)
        db.upsert_artifact(con, "x" * 12, owned=0, desc_status="pending")
        db.upsert_artifact(con, "y" * 12, owned=1, desc_status="pending")
        con.commit()
        _, out, _ = run(self.data, {"hook_event_name": "SessionStart"})
        self.assertIn("1 shared artifacts", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        con.execute("update artifacts set desc_status='ok'")
        con.commit()
        self.assertEqual(run(self.data, {"hook_event_name": "SessionStart"})[1], "")


if __name__ == "__main__":
    unittest.main()
