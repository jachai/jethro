import io
import json
import time
import sqlite3
import os
import unittest
from unittest import mock

import helpers
import common
import db
import hook

URL = "https://claude.ai/artifact/AbCdEfGhIjKlMn"
RESP = {"url": URL, "path": "/x/a.html", "artifact_id": "u-1", "title": "T", "seq": 2, "version": "v2", "owned": True}


UUID = "24033f82-1111-2222-3333-444455556666"
CWD = helpers.tmp()


def run(data, payload, thumbed=None):
    with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), mock.patch.object(common, "detach") as d:
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            rc = hook.main(data)
    with mock.patch("thumbs.run") as t, mock.patch("build.build"):
        hook.ingest(data)
    if thumbed is not None:
        thumbed += [c.kwargs["aid"] for c in t.call_args_list]
    return rc, out.getvalue(), d


class HookTest(unittest.TestCase):
    def setUp(self):
        self.data = helpers.tmp()

    def post(self, tin, resp, cwd=CWD, thumbed=None):
        return run(self.data, {"hook_event_name": "PostToolUse", "tool_name": "Artifact", "session_id": "s1",
                               "cwd": cwd, "tool_input": tin, "tool_response": resp}, thumbed)

    def test_publish(self):
        rc, _, d = self.post({"file_path": "/x/a.html", "description": "desc", "label": "L"}, RESP)
        self.assertEqual(rc, 0)
        self.assertEqual(d.call_count, 1)
        self.assertIn("ingest-hooks", d.call_args[0][0])
        self.assertEqual(os.listdir(hook.spool_dir(self.data)), [])
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

    def test_republish_after_edit(self):
        con = db.connect(self.data)
        v1 = dict(RESP, seq=1, version="v1")
        self.assertTrue(hook.record(con, self.data, {"file_path": "/x/a.html"}, v1, 1000.0, "hook", "s1", CWD))
        con.commit()
        thumbed = []
        with mock.patch.object(time, "time", return_value=1060.0):
            self.post({"file_path": "/x/a.html"}, RESP, thumbed=thumbed)
        con = db.connect(self.data)
        r = db.get(con, "AbCdEfGhIjKlMn")
        self.assertEqual((r["version"], r["seq"], r["modified"]), ("v2", 2, 1060.0))
        self.assertEqual(thumbed, ["AbCdEfGhIjKlMn"])
        self.assertEqual(con.execute("select count(*) from events where kind='publish'").fetchone()[0], 2)
        # the same v2 payload seen again (the transcript scan, minutes later) is one event
        self.assertIsNone(hook.record(con, self.data, {"file_path": "/x/a.html"}, RESP, 1400.0, "transcript", "s1", CWD))
        self.assertEqual(con.execute("select count(*) from events where kind='publish'").fetchone()[0], 2)

    def test_publish_without_file_path(self):
        con = db.connect(self.data)
        for tin in ({"type_url": "https://example.com"}, {"action": "publish", "files": {"index.html": "x"}}):
            self.assertEqual(hook.record(con, self.data, tin, RESP, 1000.0, "hook", "s1", CWD),
                             ("AbCdEfGhIjKlMn", "publish"))
            r = db.get(con, "AbCdEfGhIjKlMn")
            self.assertEqual((r["version"], r["local_path"], r["thumb_status"]), ("v2", None, "pending"))
            con.execute("delete from events")
            con.execute("delete from artifacts")

    def test_relative_file_path(self):
        con = db.connect(self.data)
        hook.record(con, self.data, {"file_path": os.path.join("out", "..", "a.html")}, RESP, 1000.0, "hook", "s1", CWD)
        self.assertEqual(db.get(con, "AbCdEfGhIjKlMn")["local_path"], os.path.join(CWD, "a.html"))

    def test_describer_calls_are_not_recorded(self):
        self.post({"action": "read", "url": URL}, RESP, cwd=self.data)
        sub = os.path.join(self.data, "inbox")
        self.post({"action": "open", "url": URL}, RESP, cwd=sub)
        con = db.connect(self.data)
        self.assertEqual(con.execute("select count(*) from events").fetchone()[0], 0)
        self.assertIsNone(db.get(con, "AbCdEfGhIjKlMn"))
        self.post({"action": "read", "url": URL}, RESP, cwd=self.data + "-other")  # a sibling folder is not inside
        self.assertEqual(db.connect(self.data).execute("select count(*) from events").fetchone()[0], 1)

    def test_uuid_row_folds_into_short_id_row(self):
        con = db.connect(self.data)
        code = "https://claude.ai/code/artifact/" + UUID
        hook.record(con, self.data, {"action": "read", "url": code}, {}, 900.0, "hook", "s0", CWD)
        db.upsert_artifact(con, UUID, kind="Page", size=5, thumb="thumbs/%s.png" % UUID, thumb_status="ok")
        resp = dict(RESP, artifact_id=UUID)
        hook.record(con, self.data, {"file_path": "/x/a.html"}, resp, 1000.0, "hook", "s1", CWD)
        self.assertIsNone(db.get(con, UUID))
        r = db.get(con, "AbCdEfGhIjKlMn")
        self.assertEqual((r["uuid"], r["kind"], r["size"], r["url"], r["version"], r["thumb"]),
                         (UUID, "Page", 5, URL, "v2", "thumbs/%s.png" % UUID))
        self.assertEqual(r["last_accessed"], 900.0)
        self.assertEqual(sorted(x[0] for x in con.execute("select artifact_id from events")), ["AbCdEfGhIjKlMn"] * 2)
        # a later uuid-form read lands on the short-id row
        self.assertEqual(hook.record(con, self.data, {"action": "read", "url": code}, {}, 2000.0, "hook", "s2", CWD),
                         ("AbCdEfGhIjKlMn", "agent_read"))
        self.assertEqual(con.execute("select count(*) from artifacts").fetchone()[0], 1)

    def test_hook_does_not_wait_for_a_busy_database(self):
        db.connect(self.data).close()
        holder = sqlite3.connect(os.path.join(self.data, "explorer.db"))
        holder.execute("BEGIN IMMEDIATE")  # a watcher pass in the middle of a long write
        p = {"hook_event_name": "PostToolUse", "tool_name": "Artifact", "session_id": "s1", "cwd": CWD,
             "tool_input": {"file_path": "/x/a.html"}, "tool_response": RESP}
        t0 = time.time()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(p))), mock.patch.object(common, "detach"):
            self.assertEqual(hook.main(self.data), 0)
        self.assertLess(time.time() - t0, 2)
        holder.rollback()
        holder.close()
        with mock.patch("thumbs.run"), mock.patch("build.build") as b:
            hook.ingest(self.data)
        self.assertEqual(db.get(db.connect(self.data), "AbCdEfGhIjKlMn")["title"], "T")
        b.assert_called_once()

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
