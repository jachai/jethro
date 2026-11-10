import json
import os
import unittest
from unittest import mock

import helpers
import db
import hook
import transcripts

URL = "https://claude.ai/artifact/AbCdEfGhIjKlMn"
RESP = {"url": URL, "path": "/x/a.html", "artifact_id": "u-1", "title": "T", "seq": 1, "version": "v1", "owned": True}


def use(tid, tin, ts):
    return {"type": "assistant", "timestamp": ts, "sessionId": "s1", "cwd": "/tmp",
            "message": {"content": [{"type": "tool_use", "id": tid, "name": "Artifact", "input": tin}]}}


def result(tid, resp, ts):
    return {"type": "user", "timestamp": ts, "sessionId": "s1", "cwd": "/tmp", "toolUseResult": resp,
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}}


def write(path, objs, mode="a", partial=""):
    with open(path, mode) as f:
        for o in objs:
            f.write(json.dumps(o) + "\n")
        f.write(partial)


class TranscriptTest(unittest.TestCase):
    def setUp(self):
        self.data = helpers.tmp()
        self.root = helpers.tmp()
        os.makedirs(os.path.join(self.root, "proj"))
        self.f = os.path.join(self.root, "proj", "s.jsonl")
        self.con = db.connect(self.data)
        p = mock.patch.object(transcripts, "roots", lambda: [self.root])
        p.start()
        self.addCleanup(p.stop)

    def test_scan_and_incremental(self):
        write(self.f, [{"type": "user", "message": {"content": "hi"}},
                       use("t1", {"file_path": "/x/a.html", "description": "d"}, "2026-11-10T10:00:00.000Z"),
                       result("t1", RESP, "2026-11-10T10:00:02.000Z"),
                       use("t2", {"action": "read", "url": URL}, "2026-11-10T11:00:00.000Z")])
        self.assertEqual(transcripts.scan(self.con, self.data), 1)
        # result arrives in a later pass; a half-written line is not consumed until completed
        write(self.f, [result("t2", {"url": URL, "title": "T"}, "2026-11-10T11:00:01.000Z")], partial='{"type": "us')
        self.assertEqual(transcripts.scan(self.con, self.data), 1)
        with open(self.f, "a") as f:
            f.write('er"}\n')
        write(self.f, [use("t3", {"action": "open", "url": URL}, "2026-11-10T12:00:00.000Z"),
                       result("t3", "plain text", "2026-11-10T12:00:01.000Z")])
        self.assertEqual(transcripts.scan(self.con, self.data), 1)
        r = db.get(self.con, "AbCdEfGhIjKlMn")
        self.assertEqual((r["owned"], r["version"], r["local_path"], r["description"]), (1, "v1", "/x/a.html", "d"))
        self.assertIsNotNone(r["created"])
        kinds = sorted(x[0] for x in self.con.execute("select kind from events"))
        self.assertEqual(kinds, ["agent_open", "agent_read", "publish"])
        self.assertEqual(transcripts.scan(self.con, self.data), 0)

    def test_restart_on_truncate(self):
        write(self.f, [use("t1", {"file_path": "/x/a.html"}, "2026-11-10T10:00:00Z"),
                       result("t1", RESP, "2026-11-10T10:00:02Z")])
        self.assertEqual(transcripts.scan(self.con, self.data), 1)
        write(self.f, [use("t9", {"action": "read", "url": URL}, "2026-11-11T10:00:00Z"),
                       result("t9", {"url": URL}, "2026-11-11T10:00:01Z")], mode="w")
        self.assertEqual(transcripts.scan(self.con, self.data), 1)

    def test_older_publish_does_not_roll_back(self):
        newer = dict(RESP, version="v9")
        write(self.f, [use("a", {"file_path": "/x/b.html"}, "2026-11-10T10:00:00Z"), result("a", newer, "2026-11-10T10:00:01Z"),
                       use("b", {"file_path": "/x/a.html"}, "2026-11-09T10:00:00Z"), result("b", RESP, "2026-11-09T10:00:01Z")])
        self.assertEqual(transcripts.scan(self.con, self.data), 2)
        self.assertEqual(db.get(self.con, "AbCdEfGhIjKlMn")["version"], "v9")

    def test_hook_and_transcript_see_one_publish(self):
        hook.record(self.con, self.data, {"file_path": "/x/a.html"}, RESP, 1762768800.5, "hook", "s1", "/tmp")
        later = dict(RESP, seq=2, version="v2")
        write(self.f, [use("t1", {"file_path": "/x/a.html"}, "2026-11-10T10:00:00Z"), result("t1", RESP, "2026-11-10T10:00:02Z"),
                       use("t2", {"file_path": "/x/a.html"}, "2026-11-10T10:01:00Z"), result("t2", later, "2026-11-10T10:01:02Z")])
        self.assertEqual(transcripts.scan(self.con, self.data), 1)  # v1 already recorded by the hook; v2 is a republish
        self.assertEqual(self.con.execute("select count(*) from events where kind='publish'").fetchone()[0], 2)
        self.assertEqual(db.get(self.con, "AbCdEfGhIjKlMn")["version"], "v2")

    def test_publish_without_file_path_and_relative_path(self):
        write(self.f, [use("t1", {"type_url": "https://example.com"}, "2026-11-10T10:00:00Z"),
                       result("t1", RESP, "2026-11-10T10:00:02Z")])
        self.assertEqual(transcripts.scan(self.con, self.data), 1)
        self.assertIsNone(db.get(self.con, "AbCdEfGhIjKlMn")["local_path"])
        write(self.f, [use("t2", {"file_path": "a.html"}, "2026-11-10T11:00:00Z"),
                       result("t2", dict(RESP, seq=2, version="v2"), "2026-11-10T11:00:02Z")])
        self.assertEqual(transcripts.scan(self.con, self.data), 1)
        self.assertEqual(db.get(self.con, "AbCdEfGhIjKlMn")["local_path"], os.path.join(os.path.normpath("/tmp"), "a.html"))

    def test_skips_calls_made_in_the_data_dir(self):
        o = use("t1", {"action": "read", "url": URL}, "2026-11-10T10:00:00Z")
        r = result("t1", {"url": URL}, "2026-11-10T10:00:02Z")
        o["cwd"] = r["cwd"] = self.data
        write(self.f, [o, r])
        self.assertEqual(transcripts.scan(self.con, self.data), 0)
        self.assertIsNone(db.get(self.con, "AbCdEfGhIjKlMn"))


if __name__ == "__main__":
    unittest.main()
