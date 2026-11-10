import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import importer  # noqa: E402

A, B = "AAAAAAAAAAAAAAAAAAAAAA", "BBBBBBBBBBBBBBBBBBBBBB"


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.src, self.d = helpers.tmp(), helpers.tmp()

        def w(name, obj):
            with open(os.path.join(self.src, name), "w") as f:
                json.dump(obj, f)
        w("meta.json", [
            {"id": A, "title": "One", "type": "Page", "size": 10, "created": 1000, "visits": [2000.5], "repos": {"proj": 3},
             "desc": None, "cand": "Candidate text", "uuid": "u-1"},
            {"id": B, "title": "Two", "type": "Slides", "created": 1500, "visits": [], "repos": {}, "by": "Someone else"},
            {"id": "gone-one", "title": "Gone", "gone": True}])
        w("cats.json", {A: "Alpha", B: "Beta"})
        w("hand.json", {A: "Hand written"})
        w("previews.json", {B: "data:image/webp;base64," + base64.b64encode(b"webpbytes").decode()})
        w("local.json", {"visits": {"u-1": [3000]}, "agent": {A: [2500]}, "published": {A: {"ts": 1800, "n": 2}}})
        w("catalog.json", [{"u": "https://claude.ai/artifact/" + A, "by": "Me", "m": 1900, "sh": {"a": "private"}}])
        os.makedirs(os.path.join(self.src, "shots"))
        with open(os.path.join(self.src, "shots", A + ".jpg"), "wb") as f:
            f.write(b"jpg")
        with open(os.path.join(self.src, "build.py"), "w") as f:
            f.write("CATEGORIES=['Beta','Alpha','Uncategorised']\n")

    def test_import_and_rerun(self):
        importer.run(self.d, self.src)
        con = db.connect(self.d)
        a, b = db.get(con, A), db.get(con, B)
        self.assertEqual((a["owned"], b["owned"], a["sharing"], a["modified"]), (1, 0, "private", 1900))
        self.assertEqual((a["description"], a["desc_source"], b["desc_status"]), ("Candidate text", "import", "pending"))
        self.assertEqual((a["thumb"], b["thumb"], b["thumb_source"]), ("thumbs/%s.jpg" % A, "thumbs/%s.webp" % B, "import"))
        self.assertEqual(open(os.path.join(self.d, b["thumb"]), "rb").read(), b"webpbytes")
        self.assertEqual(a["last_accessed"], 3000)
        self.assertIsNone(db.get(con, "gone-one"))
        n = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(n, 5)  # 2 visits, 1 agent, 1 publish, 1 repo
        cfg = common.load_toml(os.path.join(self.d, "config.toml"))
        self.assertEqual([c["name"] for c in cfg["categories"]], ["Beta", "Alpha"])
        self.assertEqual(cfg["overrides"][A], {"category": "Alpha", "description": "Hand written"})
        before = open(os.path.join(self.d, "config.toml")).read()
        importer.run(self.d, self.src)
        self.assertEqual(open(os.path.join(self.d, "config.toml")).read(), before)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM events").fetchone()[0], n)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], 2)

    def test_folds_uuid_rows_into_imported_rows(self):
        u = "24033f82-1111-2222-3333-444455556666"
        meta = json.load(open(os.path.join(self.src, "meta.json")))
        meta[0]["uuid"] = u
        json.dump(meta, open(os.path.join(self.src, "meta.json"), "w"))
        json.dump([{"u": "https://claude.ai/code/artifact/" + u, "by": "Me", "m": 1900, "sh": {"a": "private"}}],
                  open(os.path.join(self.src, "catalog.json"), "w"))
        con = db.connect(self.d)
        db.upsert_artifact(con, u, url="https://claude.ai/code/artifact/" + u)  # a browser visit seen before the import
        db.add_event(con, u, 5000, "visit", "browser:chrome")
        con.commit()
        importer.run(self.d, self.src)
        con = db.connect(self.d)
        self.assertIsNone(db.get(con, u))
        a = db.get(con, A)
        self.assertEqual((a["uuid"], a["sharing"], a["modified"], a["last_accessed"]), (u, "private", 1900, 5000))

    def test_keeps_user_config(self):
        with open(os.path.join(self.d, "config.toml"), "w") as f:
            f.write('[page]\ntitle = "Mine"\n[[categories]]\nname = "Alpha"\n')
        importer.run(self.d, self.src)
        cfg = common.load_toml(os.path.join(self.d, "config.toml"))
        self.assertEqual(cfg["page"]["title"], "Mine")
        self.assertEqual([c["name"] for c in cfg["categories"]], ["Alpha", "Beta"])


if __name__ == "__main__":
    unittest.main()
