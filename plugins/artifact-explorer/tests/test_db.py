import unittest

import helpers
import db

U = "24033f82-1111-2222-3333-444455556666"


class DbTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(helpers.tmp())

    def test_id_from_url_is_anchored(self):
        self.assertEqual(db.id_from_url("https://claude.ai/artifact/AAAAAAAAAA"), "AAAAAAAAAA")
        self.assertEqual(db.id_from_url("https://claude.ai/artifact/AAAAAAAAAA?x=1#y"), "AAAAAAAAAA")
        self.assertEqual(db.id_from_url("https://claude.ai/code/artifact/" + U), U)
        for bad in ("javascript:alert(1)//claude.ai/artifact/AAAAAAAAAA",
                    "https://evil.example/?u=https://claude.ai/artifact/AAAAAAAAAA",
                    "http://claude.ai/artifact/AAAAAAAAAA", "https://claude.ai.evil/artifact/AAAAAAAAAA",
                    "https://claude.ai/artifact/AAAAAAAAAA\"onload=x", None, ""):
            self.assertIsNone(db.id_from_url(bad), bad)

    def test_resolve_and_merge(self):
        c = self.con
        db.upsert_artifact(c, U, url="https://claude.ai/code/artifact/" + U, kind="Page", created=50.0,
                           description="old", desc_source="describer", desc_status="ok", modified=10.0, version="v1")
        db.add_event(c, U, 100.0, "visit", "browser:chrome")
        db.add_event(c, U, 200.0, "visit", "browser:chrome")
        db.upsert_artifact(c, "S" * 22, url="https://claude.ai/artifact/" + "S" * 22, title="T", created=80.0,
                           description="pub", desc_source="publish", desc_status="ok", modified=20.0, version="v2")
        db.add_event(c, "S" * 22, 200.0, "visit", "browser:chrome")  # the same visit, seen under both ids
        self.assertEqual(db.resolve(c, "S" * 22, U), "S" * 22)
        self.assertIsNone(db.get(c, U))
        r = db.get(c, "S" * 22)
        self.assertEqual((r["uuid"], r["url"], r["title"], r["kind"], r["created"], r["version"], r["modified"],
                          r["description"], r["last_accessed"]),
                         (U, "https://claude.ai/artifact/" + "S" * 22, "T", "Page", 50.0, "v2", 20.0, "old", 200.0))
        self.assertEqual(c.execute("select count(*) from events where artifact_id=?", ("S" * 22,)).fetchone()[0], 2)
        self.assertEqual(db.resolve(c, U), "S" * 22)
        self.assertEqual(db.resolve(c, "S" * 22, U), "S" * 22)  # nothing left to fold

    def test_resolve_renames_lone_uuid_row(self):
        db.upsert_artifact(self.con, U, kind="Page")
        db.add_event(self.con, U, 1.0, "visit", "browser:chrome")
        self.assertEqual(db.resolve(self.con, "S" * 22, U), "S" * 22)
        r = db.get(self.con, "S" * 22)
        self.assertEqual((r["uuid"], r["kind"]), (U, "Page"))
        self.assertEqual(self.con.execute("select artifact_id from events").fetchone()[0], "S" * 22)
        self.assertEqual(db.resolve(self.con, "x" * 12), "x" * 12)  # unknown ids pass through


if __name__ == "__main__":
    unittest.main()
