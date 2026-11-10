import os
import sqlite3
import unittest
from unittest import mock

import helpers
import db
import history

U1 = "https://claude.ai/artifact/AbCdEfGhIjKlMn"
U2 = "https://claude.ai/code/artifact/11111111-2222-3333-4444-555555555555"
TS = 1_760_000_000


def chromium(path, rows):
    c = sqlite3.connect(path)
    c.executescript("create table urls(id integer primary key, url text, title text);"
                    "create table visits(id integer primary key, url integer, visit_time integer);")
    for i, (url, title, ts) in enumerate(rows, 1):
        c.execute("insert into urls values(?,?,?)", (i, url, title))
        c.execute("insert into visits(url, visit_time) values(?,?)", (i, int((ts + history.EPOCH_1601) * 1e6)))
    c.execute("insert into urls values(99,'https://example.com/artifact/x','x')")
    c.execute("insert into visits(url, visit_time) values(99, 1)")
    c.commit()
    c.close()


def firefox(path, rows):
    c = sqlite3.connect(path)
    c.executescript("create table moz_places(id integer primary key, url text, title text);"
                    "create table moz_historyvisits(id integer primary key, place_id integer, visit_date integer);")
    for i, (url, title, ts) in enumerate(rows, 1):
        c.execute("insert into moz_places values(?,?,?)", (i, url, title))
        c.execute("insert into moz_historyvisits(place_id, visit_date) values(?,?)", (i, int(ts * 1e6)))
    c.commit()
    c.close()


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.data = helpers.tmp()
        self.con = db.connect(self.data)
        self.ch = os.path.join(helpers.tmp(), "History")
        self.ff = os.path.join(helpers.tmp(), "places.sqlite")
        chromium(self.ch, [(U1, "My Report - Claude", TS), (U2, "Claude", TS + 10)])
        firefox(self.ff, [(U1, "My Report - Claude", TS + 5)])
        p = mock.patch.object(history, "sources", lambda: [("chrome", self.ch, "chromium"), ("firefox", self.ff, "firefox")])
        p.start()
        self.addCleanup(p.stop)

    def test_scan(self):
        self.assertEqual(history.scan(self.con, self.data), 3)
        r = db.get(self.con, "AbCdEfGhIjKlMn")
        self.assertEqual((r["title"], r["owned"], r["desc_status"], r["description"]), ("My Report", None, "pending", None))
        self.assertIsNone(db.get(self.con, "11111111-2222-3333-4444-555555555555")["title"])
        srcs = {x[0] for x in self.con.execute("select source from events")}
        self.assertEqual(srcs, {"browser:chrome", "browser:firefox"})
        self.assertAlmostEqual(r["last_accessed"], TS + 5, places=3)

    def test_incremental(self):
        history.scan(self.con, self.data)
        self.assertEqual(history.scan(self.con, self.data), 0)
        c = sqlite3.connect(self.ch)
        c.execute("insert into visits(url, visit_time) values(1,?)", (int((TS + 100 + history.EPOCH_1601) * 1e6),))
        c.commit()
        c.close()
        self.assertEqual(history.scan(self.con, self.data), 1)

    def test_share_windows(self):
        db.state_set(self.con, "share_windows", [[TS - 1, TS + 6], [TS + 8, None]])
        self.assertEqual(history.scan(self.con, self.data), 0)

    def test_clean_title(self):
        for t in ("Claude", "Claude Artifact", "Page not found - Claude", "", None):
            self.assertIsNone(history.clean_title(t))
        self.assertEqual(history.clean_title("A - Claude"), "A")


if __name__ == "__main__":
    unittest.main()
