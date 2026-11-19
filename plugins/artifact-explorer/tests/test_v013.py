"""0.1.3: rows marked 'none' are retried when a file appears, old Chrome shots are importable, ae status tells the
truth about rows with no thumbnail, the page carries a build/watcher status, and rows without a thumbnail get a
generated placeholder."""
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import build  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402
import importer  # noqa: E402
import thumbs  # noqa: E402
import watch  # noqa: E402

TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "page", "template.html")
A, B, C = "AAAAAAAAAAAAAAAAAAAAAA", "BBBBBBBBBBBBBBBBBBBBBB", "CCCCCCCCCCCCCCCCCCCCCC"


def payload(path):
    s = open(path, encoding="utf-8").read()
    a = s.index("const DATA = ") + len("const DATA = ")
    return json.JSONDecoder().raw_decode(s[a:])[0]


def status_json(d):
    with mock.patch("builtins.print") as pr:
        describe.status(d, as_json=True)
    return json.loads(pr.call_args[0][0])


class Base(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        self.con = db.connect(self.d)

    def tearDown(self):
        self.con.close()


class NoneRetryTest(Base):
    def test_none_row_whose_file_appears_is_captured(self):
        f = os.path.join(self.d, "late.html")
        open(f, "w").write("<p>late</p>")
        db.upsert_artifact(self.con, A, local_path=f, thumb_status="none")
        db.upsert_artifact(self.con, B, local_path="/gone/x.html", thumb_status="none")
        db.upsert_artifact(self.con, C, thumb_status="none")
        self.con.commit()

        def fake(browser, src, out):
            open(out, "wb").write(b"png")
            return True
        with mock.patch.object(thumbs, "_shot", fake), mock.patch.object(thumbs, "find_browser", lambda: "b"), \
                mock.patch.dict("sys.modules", {"build": mock.Mock()}):
            thumbs.run(self.d)
        con = db.connect(self.d)
        self.assertEqual(db.get(con, A)["thumb_status"], "ok")
        self.assertEqual(db.get(con, B)["thumb_status"], "none")  # still nothing to capture, not 'failed'
        self.assertEqual(db.get(con, C)["thumb_status"], "none")
        con.close()


class ImportThumbsTest(Base):
    def setUp(self):
        super().setUp()
        self.src = helpers.tmp()
        os.makedirs(os.path.join(self.src, "shots"))
        for i in (A, B):
            open(os.path.join(self.src, "shots", i + ".jpg"), "wb").write(b"jpg-" + i.encode())
        json.dump([{"id": A, "title": "Old title"}, {"id": B, "uuid": "11111111-2222-3333-4444-555555555555"},
                   {"id": C}], open(os.path.join(self.src, "meta.json"), "w"))
        db.upsert_artifact(self.con, A, title="Live title", description="Mine", desc_source="describer", thumb_status="none")
        db.upsert_artifact(self.con, "Bshort0001", uuid="11111111-2222-3333-4444-555555555555", thumb_status="none")
        db.upsert_artifact(self.con, C, thumb_status="none")  # no old shot for C
        self.con.commit()

    def test_counts_importable_old_shots(self):
        self.assertEqual(importer.thumbs_available(self.con, self.src), 2)

    def test_thumbs_only_copies_shots_and_nothing_else(self):
        before = os.listdir(self.src)
        with mock.patch.dict("sys.modules", {"build": mock.Mock()}), mock.patch("builtins.print"):
            self.assertEqual(importer.run_thumbs(self.d, self.src), 0)
        con = db.connect(self.d)
        a, b, c = db.get(con, A), db.get(con, "Bshort0001"), db.get(con, C)
        self.assertEqual((a["thumb_status"], a["thumb_source"], a["title"], a["description"]), ("ok", "import", "Live title", "Mine"))
        self.assertTrue(os.path.isfile(os.path.join(self.d, a["thumb"])))
        self.assertEqual(b["thumb_status"], "ok")  # matched by uuid
        self.assertEqual(c["thumb_status"], "none")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.d, "config.toml")))
        self.assertEqual(os.listdir(self.src), before)
        self.assertEqual(importer.thumbs_available(con, self.src), 0)
        con.close()

    def test_row_with_a_thumbnail_is_left_alone(self):
        db.upsert_artifact(self.con, A, thumb="thumbs/x.png", thumb_source="headless", thumb_status="ok")
        self.con.commit()
        with mock.patch.dict("sys.modules", {"build": mock.Mock()}), mock.patch("builtins.print"):
            importer.run_thumbs(self.d, self.src)
        self.assertEqual(db.get(db.connect(self.d), A)["thumb_source"], "headless")


    def test_unusable_preview_duplicate_meta_and_bad_files_count_right(self):
        json.dump([{"id": A}, {"id": A}, {"id": C}, {"id": None}, "junk"], open(os.path.join(self.src, "meta.json"), "w"))
        json.dump({C: "no-comma-here"}, open(os.path.join(self.src, "previews.json"), "w"))
        self.assertEqual(importer.thumbs_available(self.con, self.src), 1)  # A once; C's preview is unusable
        json.dump([[1], [2]], open(os.path.join(self.src, "previews.json"), "w"))  # not a dict: ignored, no crash
        self.assertEqual(importer.thumbs_available(self.con, self.src), 1)
        self.assertEqual(importer.thumbs_available(self.con, os.path.join(self.src, "missing")), 0)

class StatusTruthTest(Base):
    def test_status_counts_rows_with_no_thumbnail(self):
        for i, s in enumerate(["ok", "none", "none", "pending", "failed"]):
            db.upsert_artifact(self.con, "row%07d" % i, thumb_status=s)
        self.con.commit()
        with mock.patch.dict(os.environ, {"AE_OLD_CATALOG": helpers.tmp()}):
            out = status_json(self.d)
        self.assertEqual((out["thumbs_ok"], out["thumbs_none"], out["thumbs_missing"], out["thumbs_importable"]), (1, 2, 2, 0))
        with mock.patch.dict(os.environ, {"AE_OLD_CATALOG": helpers.tmp()}), mock.patch("builtins.print") as pr:
            describe.status(self.d)
        text = "\n".join(c[0][0] for c in pr.call_args_list)
        self.assertIn("no thumbnail: 2", text)
        self.assertIn("chrome_screenshots", text)


class PageStatusTest(Base):
    def setUp(self):
        super().setUp()
        db.upsert_artifact(self.con, A, title="One")
        db.state_set(self.con, "last_pass", 1234.5)
        self.con.commit()

    def test_payload_has_build_and_watcher_status(self):
        watch.heartbeat(self.d)
        st = payload(build.build(self.d))["status"]
        self.assertAlmostEqual(st["built"], time.time(), delta=60)
        self.assertEqual(st["last_pass"], 1234.5)
        self.assertTrue(st["watcher"]["running"])
        self.assertEqual(st["watcher"]["pid"], os.getpid())
        self.assertGreater(st["stale_after"], 0)

    def test_dead_or_old_heartbeat_is_not_running(self):
        json.dump({"pid": 999999, "t": time.time()}, open(os.path.join(self.d, "watcher.json"), "w"))
        self.assertFalse(payload(build.build(self.d))["status"]["watcher"]["running"])
        json.dump({"pid": os.getpid(), "t": time.time() - 3600}, open(os.path.join(self.d, "watcher.json"), "w"))
        self.assertFalse(payload(build.build(self.d, max_age=0))["status"]["watcher"]["running"])

    def test_unchanged_page_is_rewritten_once_old(self):
        out = build.build(self.d)
        old = time.time() - 2 * common.PAGE_HEARTBEAT
        os.utime(out, (old, old))
        build.build(self.d)  # plain build: content unchanged, so no write
        self.assertLess(os.path.getmtime(out), time.time() - common.PAGE_HEARTBEAT)
        build.build(self.d, max_age=common.PAGE_HEARTBEAT)  # watcher heartbeat: rewritten
        self.assertGreater(os.path.getmtime(out), time.time() - 60)

    def test_pass_records_last_pass_before_it_builds(self):
        seen = {}

        def fake_build(data, max_age=None):
            con = db.connect(data)
            seen["lp"], seen["age"] = db.state_get(con, "last_pass"), max_age
            con.close()
        bmod = mock.Mock(build=fake_build)
        with mock.patch.dict("sys.modules", {"build": bmod}), mock.patch.object(thumbs, "run", lambda *a, **k: 0), \
                mock.patch.object(describe, "launch", lambda d: 0), \
                mock.patch("common.options", lambda: {"watch_interval": 10, "browser_history": False, "transcript_reads": False}):
            watch.run_pass(self.d, force=True)
        self.assertAlmostEqual(seen["lp"], time.time(), delta=60)
        self.assertEqual(seen["age"], common.PAGE_HEARTBEAT)

    def test_template_shows_status_section(self):
        tpl = open(TPL, encoding="utf-8").read()
        for s in ('id="status"', "as of build", "Page may be stale", "setInterval"):
            self.assertIn(s, tpl)


if __name__ == "__main__":
    unittest.main()
