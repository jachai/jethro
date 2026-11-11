import json
import os
import shutil
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402

U = "https://claude.ai/artifact/"


class DescribeTest(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        self.f = os.path.join(self.d, "list.json")
        self.cfgdir = cfgdir = helpers.tmp()  # settings.json holds only the setup allow rule: default options
        with open(os.path.join(cfgdir, "settings.json"), "w") as f:
            json.dump({"permissions": {"allow": [common.ALLOW_RULE]}}, f)
        p = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfgdir})
        p.start()
        self.addCleanup(p.stop)

    def ingest(self, rows):
        with open(self.f, "w") as f:
            json.dump(rows, f)
        describe.ingest_list(self.d, self.f)
        return db.connect(self.d)

    def test_ingest_liberal_keys(self):
        con = self.ingest([
            {"url": U + "AAAAAAAAAAAA", "title": "Mine", "type": "Page", "scope": "mine", "updated": "2026-11-01T10:00:00Z", "size": 5},
            {"url": U + "BBBBBBBBBBBB", "title": "Theirs", "kind": "Docs", "owned": False, "modified": 1700000000000,
             "description": "Has one"},
            {"title": "no url"}])
        a, b = db.get(con, "AAAAAAAAAAAA"), db.get(con, "BBBBBBBBBBBB")
        self.assertEqual((a["owned"], a["kind"], a["desc_status"], a["size"]), (1, "Page", "pending", 5))
        self.assertEqual(a["modified"], 1793527200.0)
        self.assertEqual((b["owned"], b["modified"], b["desc_status"], b["description"]), (0, 1700000000.0, "ok", "Has one"))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], 2)
        describe.set_desc(self.d, "AAAAAAAAAAAA", " Done. ")
        con = self.ingest([{"url": U + "AAAAAAAAAAAA", "title": "Mine"}])  # re-ingest keeps the description
        a = db.get(con, "AAAAAAAAAAAA")
        self.assertEqual((a["description"], a["desc_source"], a["desc_status"]), ("Done.", "describer", "ok"))

    def test_pending_and_status(self):
        self.ingest([{"url": U + "AAAAAAAAAAAA", "title": "Mine", "scope": "mine"},
                     {"url": U + "BBBBBBBBBBBB", "title": "Theirs", "scope": "shared"}])
        describe.set_sharing(self.d, "AAAAAAAAAAAA", "private")
        con = db.connect(self.d)
        self.assertEqual(db.get(con, "AAAAAAAAAAAA")["sharing"], "private")
        self.assertEqual(len(describe.pending_rows(con, False)), 2)
        self.assertEqual([r["id"] for r in describe.pending_rows(con, True)], ["AAAAAAAAAAAA"])
        with mock.patch("builtins.print") as pr:
            describe.status(self.d, as_json=True)
        s = json.loads(pr.call_args[0][0])
        self.assertEqual((s["total"], s["mine"], s["shared"], s["pending_descriptions"]), (2, 1, 1, 2))

    def test_list_date_never_lowers_modified(self):
        con = db.connect(self.d)
        db.upsert_artifact(con, "AAAAAAAAAAAA", modified=1793566800.0)  # 2026-11-01 21:00 UTC, from a hook
        con.commit()
        con = self.ingest([{"url": U + "AAAAAAAAAAAA", "scope": "mine", "updated": "2026-11-01"}])
        self.assertEqual(db.get(con, "AAAAAAAAAAAA")["modified"], 1793566800.0)
        con = self.ingest([{"url": U + "AAAAAAAAAAAA", "scope": "mine", "updated": "2026-11-03"}])
        self.assertEqual(db.get(con, "AAAAAAAAAAAA")["modified"], 1793664000.0)

    def test_excerpt(self):
        p = os.path.join(self.d, "a.html")
        with open(p, "w") as f:
            f.write("<html><head><style>.x{}</style><script>var a=1</script></head>"
                    "<body><h1>Plan &amp; notes</h1>\n\n<p>Second   line</p><svg><text>no</text></svg></body></html>")
        self.assertEqual(describe.excerpt(p), "Plan & notes Second line")
        self.assertEqual(describe.excerpt(p, 4), "Plan")

    def test_launch_inline_plugin_dir(self):
        d = os.path.join(helpers.tmp(), "artifact-explorer-inline")
        os.makedirs(d)
        with open(self.f, "w") as f:
            json.dump([{"url": U + "AAAAAAAAAAAA", "scope": "mine"}], f)
        describe.ingest_list(d, self.f)
        with mock.patch("shutil.which", return_value="/bin/claude"), mock.patch.object(common, "detach", return_value=4242) as det:
            describe.launch(d)
        argv = det.call_args[0][0]
        self.assertEqual(argv[argv.index("--plugin-dir") + 1], common.ROOT)
        self.assertEqual(argv[-1], "/artifact-explorer:refresh describe-only")

    def test_launch(self):
        self.ingest([{"url": U + "AAAAAAAAAAAA", "title": "Mine", "scope": "mine"}])
        with mock.patch("shutil.which", return_value=None), mock.patch.object(common, "detach") as det:
            describe.launch(self.d)
            self.assertFalse(det.called)
        with mock.patch("shutil.which", return_value="/bin/claude"), \
                mock.patch.object(common, "detach", return_value=4242) as det, \
                mock.patch.object(common, "_pid_alive", return_value=False):
            describe.launch(self.d)
            self.assertEqual(det.call_count, 1)
            argv = det.call_args[0][0]
            self.assertEqual(argv[:2], ["/bin/claude", "-p"])
            self.assertEqual(argv[-1], "/artifact-explorer:refresh describe-only")
            self.assertNotIn("--plugin-dir", argv)
            self.assertEqual(det.call_args[1]["cwd"], self.d)
            describe.launch(self.d)  # inside watch_interval
            self.assertEqual(det.call_count, 1)
            con = db.connect(self.d)
            self.assertAlmostEqual(db.spend_today(con), describe.RUN_BUDGET)
            db.state_set(con, "describer_last", time.time() - 3600)
            db.add_spend(con, 5)  # over the cap
            con.commit()
            describe.launch(self.d)
            self.assertEqual(det.call_count, 1)

    def test_launch_needs_allow_rule(self):
        self.ingest([{"url": U + "AAAAAAAAAAAA", "title": "Mine", "scope": "mine"}])
        with open(os.path.join(self.cfgdir, "settings.json"), "w") as f:
            json.dump({"permissions": {"allow": ["Bash(ls *)"]}}, f)
        with mock.patch("shutil.which", return_value="/bin/claude"), mock.patch.object(common, "detach", return_value=True) as det:
            describe.launch(self.d)
            self.assertFalse(det.called)
            os.remove(os.path.join(self.cfgdir, "settings.json"))
            describe.launch(self.d)
            self.assertFalse(det.called)

    def test_launch_skips_unknown_owner(self):
        self.ingest([{"url": U + "CCCCCCCCCCCC", "title": "History"}])
        with mock.patch("shutil.which", return_value="/bin/claude"), mock.patch.object(common, "detach") as det:
            describe.launch(self.d)
            self.assertFalse(det.called)

    def test_launch_skips_shared_only(self):
        self.ingest([{"url": U + "BBBBBBBBBBBB", "title": "Theirs", "scope": "shared"}])
        with mock.patch("shutil.which", return_value="/bin/claude"), mock.patch.object(common, "detach") as det:
            describe.launch(self.d)
            self.assertFalse(det.called)


if __name__ == "__main__":
    unittest.main()
