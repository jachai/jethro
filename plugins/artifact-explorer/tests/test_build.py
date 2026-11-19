import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import build  # noqa: E402
import db  # noqa: E402


def payload(path):
    s = open(path, encoding="utf-8").read()
    a = s.index("const DATA = ") + len("const DATA = ")
    return json.JSONDecoder().raw_decode(s[a:])[0]


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        self.con = db.connect(self.d)
        db.upsert_artifact(self.con, "aaaaaaaaaa", title="Q3 audit report", kind="Page", owned=1, created=100, modified=200,
                           url="https://claude.ai/artifact/aaaaaaaaaa", description="Checks things", desc_source="publish")
        db.upsert_artifact(self.con, "bbbbbbbbbb", title="Team slides", kind="Slides", owned=0, creator="Sam", created=50)
        db.upsert_artifact(self.con, "cccccccccc", title="Misc", kind="Page", desc_status="pending")
        db.add_event(self.con, "aaaaaaaaaa", 150, "publish", "hook", repo="proj")
        db.add_event(self.con, "aaaaaaaaaa", 300, "publish", "hook", repo="other")
        db.add_event(self.con, "aaaaaaaaaa", 400, "visit", "browser:chrome")
        self.con.commit()

    def rows(self):
        return {r["id"]: r for r in payload(build.build(self.d))["rows"]}

    def cfg(self, text):
        with open(os.path.join(self.d, "config.toml"), "w") as f:
            f.write(text)

    def test_data_blob_cannot_open_script_state(self):
        db.upsert_artifact(self.con, "dddddddddd", title="x <!--<script> y & \u2028 </script>")
        self.con.commit()
        path = build.build(self.d)
        s = open(path, encoding="utf-8").read()
        data = s[s.index("const DATA = "):]
        data = data[:data.index("\n")] if "\n" in data else data
        self.assertNotIn("<!--", data)
        self.assertNotIn("<script", data.lower())
        self.assertNotIn("\u2028", data)
        self.assertIn("x <!--<script> y & \u2028 </script>", [r["title"] for r in payload(path)["rows"]])

    def test_only_claude_urls_in_payload(self):
        db.upsert_artifact(self.con, "dddddddddd", title="x", url="javascript:alert(1)")
        self.con.commit()
        self.assertEqual(self.rows()["dddddddddd"]["url"], "")

    def test_derived_fields(self):
        r = self.rows()
        a = r["aaaaaaaaaa"]
        self.assertEqual((a["created"], a["modified"], a["accessed"], a["accessed_by"]), (150, 300, 400, "browser"))
        self.assertEqual(a["repos"], ["other", "proj"])
        self.assertEqual((a["mine"], a["category"]), (True, "Reports"))
        self.assertEqual((r["bbbbbbbbbb"]["mine"], r["bbbbbbbbbb"]["category"]), (False, "Decks"))
        # 0.2.11: owner unknown (found in history): not read in the background, so "unread", not pending
        self.assertEqual((r["cccccccccc"]["category"], r["cccccccccc"]["pending"], r["cccccccccc"]["unread"],
                          "from" in r["cccccccccc"]), ("Uncategorized", False, True, False))
        self.assertNotIn("created_by", a)

    def test_sharing_labels(self):
        db.upsert_artifact(self.con, "aaaaaaaaaa", sharing="private", owned=1)
        db.upsert_artifact(self.con, "bbbbbbbbbb", sharing="shared with 3 people")
        self.con.commit()
        r = self.rows()
        self.assertEqual((r["aaaaaaaaaa"]["sharing"], r["bbbbbbbbbb"]["sharing"], r["cccccccccc"]["sharing"]),
                         ("Private", "", ""))  # only own rows carry a sharing phrase

    def test_filter_and_overrides(self):
        self.cfg('[filter]\ninclude_repos=["proj"]\n[overrides."aaaaaaaaaa"]\ncategory="Plans"\ndescription="Mine"\n')
        r = self.rows()
        self.assertEqual(list(r), ["aaaaaaaaaa"])
        self.assertEqual((r["aaaaaaaaaa"]["category"], r["aaaaaaaaaa"]["description"]), ("Plans", "Mine"))
        self.cfg('[filter]\ninclude_shared=false\n[overrides."cccccccccc"]\nhidden=true\n')
        self.assertEqual(list(self.rows()), ["aaaaaaaaaa"])

    def test_deterministic_and_skips_unchanged(self):
        p = build.build(self.d)
        m = os.path.getmtime(p)
        os.utime(p, (m - 100, m - 100))
        self.assertEqual(build.build(self.d), p)
        self.assertEqual(os.path.getmtime(p), m - 100)  # not rewritten
        db.upsert_artifact(self.con, "cccccccccc", title="Changed")
        self.con.commit()
        build.build(self.d)
        self.assertNotEqual(os.path.getmtime(p), m - 100)

    def test_thumb_relative(self):
        os.makedirs(os.path.join(self.d, "thumbs"))
        open(os.path.join(self.d, "thumbs", "aaaaaaaaaa.jpg"), "w").close()
        db.upsert_artifact(self.con, "aaaaaaaaaa", thumb="thumbs/aaaaaaaaaa.jpg")
        self.con.commit()
        self.assertEqual(self.rows()["aaaaaaaaaa"]["thumb"], "thumbs/aaaaaaaaaa.jpg")


if __name__ == "__main__":
    unittest.main()
