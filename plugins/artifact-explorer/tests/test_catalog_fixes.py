"""v0.1.1 fixes found on a real install: sort fallback, thumb status, uuid title twins, override re-keying,
blank titles, cards metadata, unknown creator."""
import json
import os
import sqlite3
import unittest
from unittest import mock

import helpers
import build
import common
import db
import describe
import history
import thumbs

UU = "5e1f0c3a-7b2d-4c8e-9a10-3d4e5f607182"
SHORT = "DemoShortId00000000001"
TS = 1_790_000_000
TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "page", "template.html")


def payload(path):
    s = open(path, encoding="utf-8").read()
    a = s.index("const DATA = ") + len("const DATA = ")
    return json.JSONDecoder().raw_decode(s[a:])[0]


def chromium(path, rows):
    c = sqlite3.connect(path)
    c.executescript("create table urls(id integer primary key, url text, title text);"
                    "create table visits(id integer primary key, url integer, visit_time integer);")
    for i, (url, title, ts) in enumerate(rows, 1):
        c.execute("insert into urls values(?,?,?)", (i, url, title))
        c.execute("insert into visits(url, visit_time) values(?,?)", (i, int((ts + history.EPOCH_1601) * 1e6)))
    c.commit()
    c.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        self.con = db.connect(self.d)
        cfgdir = helpers.tmp()
        p = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfgdir})
        p.start()
        self.addCleanup(p.stop)

    def rows(self):
        self.con.commit()
        return {r["id"]: r for r in payload(build.build(self.d))["rows"]}


class SortTest(Base):
    def test_recent_falls_back_to_accessed_then_created(self):  # B1
        db.upsert_artifact(self.con, "aaaaaaaaaa", title="mine", owned=1, modified=100, last_accessed=900)
        db.upsert_artifact(self.con, "bbbbbbbbbb", title="shared", owned=0, last_accessed=500, created=50)
        db.upsert_artifact(self.con, "cccccccccc", title="old", owned=0, created=70)
        r = self.rows()
        self.assertEqual((r["aaaaaaaaaa"]["recent"], r["bbbbbbbbbb"]["recent"], r["cccccccccc"]["recent"]), (100, 500, 70))
        self.assertIsNone(r["bbbbbbbbbb"]["modified"])  # the Modified cell itself stays honest
        tpl = open(TPL, encoding="utf-8").read()
        self.assertIn('modified:{h:"Modified",k:r=>r.recent||0', tpl)


class ThumbStatusTest(Base):
    def test_new_rows_wait_for_a_thumbnail(self):  # B2
        db.upsert_artifact(self.con, "aaaaaaaaaa", title="x")
        self.assertEqual(db.get(self.con, "aaaaaaaaaa")["thumb_status"], "pending")

    def test_null_status_counts_and_is_captured(self):  # B2
        self.con.execute("INSERT INTO artifacts(id, title) VALUES('nnnnnnnnnn', 'legacy')")
        self.con.execute("INSERT INTO artifacts(id, title, thumb_status) VALUES('ffffffffff', 'f', 'failed')")
        self.con.commit()
        with mock.patch("builtins.print") as pr:
            describe.status(self.d, as_json=True)
        self.assertEqual(json.loads(pr.call_args[0][0])["thumbs_missing"], 2)
        with mock.patch.object(thumbs, "find_browser", lambda: None):
            thumbs.run(self.d)
        self.assertEqual(db.get(db.connect(self.d), "nnnnnnnnnn")["thumb_status"], "none")  # no local file

    def test_open_backfills_null_status(self):  # B2 migration
        self.con.execute("INSERT INTO artifacts(id, title) VALUES('nnnnnnnnnn', 'legacy')")
        self.con.execute("PRAGMA user_version=0")
        self.con.commit()
        self.con.close()
        self.assertEqual(db.get(db.connect(self.d), "nnnnnnnnnn")["thumb_status"], "pending")


class TwinTest(Base):
    def make_twins(self):
        db.upsert_artifact(self.con, SHORT, url="https://claude.ai/artifact/" + SHORT, title="Pixel Arcade",
                           owned=0, modified=TS, size=10)
        db.upsert_artifact(self.con, UU, url="https://claude.ai/code/artifact/" + UU, title="Pixel Arcade")
        db.add_event(self.con, UU, TS + 50, "visit", "browser:chrome")

    def test_fold_unique_title_twin(self):  # B3
        self.make_twins()
        self.assertEqual(db.fold_twins(self.con), 1)
        self.assertIsNone(db.get(self.con, UU))
        r = db.get(self.con, SHORT)
        self.assertEqual((r["uuid"], r["owned"], r["modified"], r["size"], r["last_accessed"]), (UU, 0, TS, 10, TS + 50))
        self.assertEqual(self.con.execute("select artifact_id from events").fetchall()[0][0], SHORT)  # events kept

    def test_ambiguous_titles_are_left_alone(self):  # B3
        self.make_twins()
        db.upsert_artifact(self.con, "OtherShortId0000000000", title="Pixel Arcade")
        db.upsert_artifact(self.con, "2222aaaa-7b2d-4c8e-9a10-3d4e5f607182", title="Untitled")
        self.assertEqual(db.fold_twins(self.con), 0)
        self.assertIsNotNone(db.get(self.con, UU))

    def test_short_row_with_another_uuid_is_not_a_twin(self):  # B3
        self.make_twins()
        db.upsert_artifact(self.con, SHORT, uuid="99999999-7b2d-4c8e-9a10-3d4e5f607182")
        self.assertEqual(db.fold_twins(self.con), 0)

    def test_ingest_list_folds(self):  # B3 on refresh
        db.upsert_artifact(self.con, UU, title="Pixel Arcade")
        self.con.commit()
        f = os.path.join(self.d, "list.json")
        json.dump([{"url": "https://claude.ai/artifact/" + SHORT, "title": "Pixel Arcade", "scope": "shared"}], open(f, "w"))
        with mock.patch("builtins.print"):
            describe.ingest_list(self.d, f)
        con = db.connect(self.d)
        self.assertEqual([r[0] for r in con.execute("select id from artifacts")], [SHORT])

    def test_history_folds(self):  # B3 on the watcher pass
        db.upsert_artifact(self.con, SHORT, title="Pixel Arcade", owned=0)
        ch = os.path.join(helpers.tmp(), "History")
        chromium(ch, [("https://claude.ai/code/artifact/" + UU, "Pixel Arcade - Claude", TS)])
        with mock.patch.object(history, "sources", lambda: [("chrome", ch, "chromium")]):
            history.scan(self.con, self.d)
        self.assertEqual([r[0] for r in self.con.execute("select id from artifacts")], [SHORT])
        self.assertEqual(db.get(self.con, SHORT)["last_accessed"], TS)

    def test_open_folds_once(self):  # B3 one-off merge on open
        self.make_twins()
        self.con.execute("PRAGMA user_version=0")
        self.con.commit()
        self.con.close()
        con = db.connect(self.d)
        self.assertEqual([r[0] for r in con.execute("select id from artifacts")], [SHORT])


class OverrideTest(Base):  # D611
    def cfg(self, text):
        with open(os.path.join(self.d, "config.toml"), "w", encoding="utf-8") as f:
            f.write(text)

    def test_merge_rekeys_uuid_override(self):
        self.cfg('# mine\n[overrides."%s"]\ncategory = "Personal"\n\n[filter]\nexclude_ids = []\n' % UU)
        db.upsert_artifact(self.con, UU, title="Pixel Arcade")
        db.upsert_artifact(self.con, SHORT, title="Pixel Arcade", owned=0)
        db.fold_twins(self.con)
        self.assertEqual(self.rows()[SHORT]["category"], "Personal")  # build re-keys after the merge commits
        cfg = common.load_config(self.d)
        self.assertEqual(cfg["overrides"][SHORT]["category"], "Personal")
        self.assertNotIn(UU, cfg["overrides"])
        self.assertIn("# mine", open(os.path.join(self.d, "config.toml"), encoding="utf-8").read())

    def test_existing_short_override_wins(self):
        self.cfg('[overrides."%s"]\ncategory = "Personal"\n[overrides."%s"]\ncategory = "Plans"\n' % (UU, SHORT))
        db.upsert_artifact(self.con, UU, title="Pixel Arcade")
        db.upsert_artifact(self.con, SHORT, title="Pixel Arcade")
        db.fold_twins(self.con)
        self.assertEqual(self.rows()[SHORT]["category"], "Plans")
        self.assertEqual(common.load_config(self.d)["overrides"][SHORT]["category"], "Plans")  # still valid TOML
        self.assertIn("move them by hand", open(os.path.join(self.d, "watch.log"), encoding="utf-8").read())

    def test_build_rekeys_overrides_of_already_merged_rows(self):
        self.cfg("[overrides.'%s']\nhidden = true\n" % UU)
        db.upsert_artifact(self.con, SHORT, uuid=UU, title="x")
        self.con.commit()
        self.assertNotIn(SHORT, self.rows())  # hidden: the override now applies to the short id
        self.assertTrue(common.load_config(self.d)["overrides"][SHORT]["hidden"])

    def test_bom_config_is_read(self):
        with open(os.path.join(self.d, "config.toml"), "w", encoding="utf-8-sig") as f:
            f.write('[overrides."%s"]\ncategory = "Personal"\n' % UU)
        self.assertEqual(common.rekey_overrides(self.d, {UU: SHORT}), 1)


class MigrationTest(Base):
    def test_busy_database_skips_without_waiting(self):  # review: a read-only opener must not wait on a writer
        self.con.execute("PRAGMA user_version=0")
        self.con.commit()
        other = sqlite3.connect(os.path.join(self.d, "explorer.db"))
        other.execute("BEGIN IMMEDIATE")
        import time
        t = time.time()
        con = db.connect(self.d, timeout=5)
        self.assertLess(time.time() - t, 2)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 0)
        other.rollback()
        other.close()
        con.close()
        self.assertEqual(db.connect(self.d).execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)


class TitleTest(Base):  # B5
    def test_later_visit_fills_a_blank_title(self):
        ch = os.path.join(helpers.tmp(), "History")
        u = "https://claude.ai/code/artifact/" + UU
        chromium(ch, [(u, "Page not found – Claude", TS), (u + "?x=1", "Line-Item Audit – Claude", TS + 5)])
        with mock.patch.object(history, "sources", lambda: [("chrome", ch, "chromium")]):
            history.scan(self.con, self.d)
        self.assertEqual(db.get(self.con, UU)["title"], "Line-Item Audit")

    def test_open_rescans_history_once(self):
        db.state_set(self.con, "history_cursors", {"/x/History": {"t": 5, "stamp": [[1, 2]]}})
        self.con.execute("PRAGMA user_version=0")
        self.con.commit()
        self.con.close()
        self.assertEqual(db.state_get(db.connect(self.d), "history_cursors"), {})

    def test_known_title_is_kept(self):
        db.upsert_artifact(self.con, UU, title="Mine")
        ch = os.path.join(helpers.tmp(), "History")
        chromium(ch, [("https://claude.ai/code/artifact/" + UU, "Other - Claude", TS)])
        with mock.patch.object(history, "sources", lambda: [("chrome", ch, "chromium")]):
            history.scan(self.con, self.d)
        self.assertEqual(db.get(self.con, UU)["title"], "Mine")


class CardsAndCreatorTest(Base):
    def test_unknown_owner_shows_no_from(self):  # B6 (0.2.0: own and unknown rows show nothing)
        db.upsert_artifact(self.con, "aaaaaaaaaa", title="x")
        self.assertEqual(self.rows()["aaaaaaaaaa"]["from"], "")

    def test_shared_rows_without_a_harvested_label_say_nothing(self):  # B4
        db.upsert_artifact(self.con, "aaaaaaaaaa", title="x", owned=0)
        db.upsert_artifact(self.con, "bbbbbbbbbb", title="y", owned=1)
        r = self.rows()
        self.assertEqual((r["aaaaaaaaaa"]["sharing"], r["bbbbbbbbbb"]["sharing"]), ("", ""))
        self.assertEqual((r["aaaaaaaaaa"]["from"], r["bbbbbbbbbb"]["from"]), ("", ""))

    def test_cards_show_creator_and_sharing(self):  # B4
        tpl = open(TPL, encoding="utf-8").read()
        body = tpl[tpl.index("function cards("):tpl.index("function render(")]
        self.assertTrue("r.from" in body or "fromNode(r" in body)  # the card shows the "from" part (own rows: none)
        self.assertIn("r.from", tpl)
        self.assertIn("r.access", tpl)


if __name__ == "__main__":
    unittest.main()
