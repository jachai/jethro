import os
import unittest
from unittest import mock

import helpers
import db
import thumbs


class ThumbsTest(unittest.TestCase):
    def test_wrap(self):
        self.assertIn("<!doctype html>", thumbs.wrap("<h1>x</h1>"))
        self.assertIn("<h1>x</h1>", thumbs.wrap("<h1>x</h1>"))
        full = "<HTML><body>x</body></HTML>"
        self.assertEqual(thumbs.wrap(full), full)

    def test_find_browser_env(self):
        with mock.patch.dict(os.environ, {"AE_BROWSER": "/some/chrome"}):
            self.assertEqual(thumbs.find_browser(), "/some/chrome")

    def test_row_selection(self):
        data = helpers.tmp()
        con = db.connect(data)
        f = os.path.join(data, "a.html")
        open(f, "w").write("<p>hi</p>")
        db.upsert_artifact(con, "a" * 12, local_path=f, thumb_status="pending")
        db.upsert_artifact(con, "b" * 12, local_path="/nope/missing.html", thumb_status="pending")
        db.upsert_artifact(con, "c" * 12, local_path=f, thumb_status="ok")
        con.commit()
        con.close()
        shots = []

        def fake(browser, src, out):
            shots.append(os.path.basename(out))
            open(out, "wb").write(b"png")
            return True

        build = mock.Mock()
        with mock.patch.object(thumbs, "_shot", fake), mock.patch.object(thumbs, "find_browser", lambda: "b"), \
                mock.patch.dict("sys.modules", {"build": build}):
            self.assertEqual(thumbs.run(data), 0)
        self.assertEqual(shots, ["a" * 12 + ".png"])
        build.build.assert_called_once_with(data)
        con = db.connect(data)
        st = {r["id"][0]: (r["thumb_status"], r["thumb"]) for r in con.execute("select * from artifacts")}
        self.assertEqual(st["a"], ("ok", "thumbs/%s.png" % ("a" * 12)))
        self.assertEqual(st["b"][0], "none")
        self.assertEqual(st["c"][0], "ok")

    def test_no_browser_fails(self):
        data = helpers.tmp()
        con = db.connect(data)
        f = os.path.join(data, "a.html")
        open(f, "w").write("<p>hi</p>")
        db.upsert_artifact(con, "a" * 12, local_path=f, thumb_status="pending")
        con.commit()
        con.close()
        with mock.patch.object(thumbs, "find_browser", lambda: None):
            thumbs.run(data)
        self.assertEqual(db.get(db.connect(data), "a" * 12)["thumb_status"], "failed")

    @unittest.skipUnless(thumbs.find_browser(), "no browser found")
    def test_real_render(self):
        data = helpers.tmp()
        con = db.connect(data)
        f = os.path.join(data, "a.html")
        open(f, "w").write("<h1>hello</h1>")
        db.upsert_artifact(con, "a" * 12, local_path=f, thumb_status="pending")
        con.commit()
        con.close()
        with mock.patch.dict("sys.modules", {"build": mock.Mock()}):
            thumbs.run(data, aid="a" * 12)
        self.assertTrue(os.path.getsize(os.path.join(data, "thumbs", "a" * 12 + ".png")) > 0)


if __name__ == "__main__":
    unittest.main()
