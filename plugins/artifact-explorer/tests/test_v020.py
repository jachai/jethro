"""0.2.0 backend: categorize, topics, batches, revoked shares, local copies, update check, favicon, colors."""
import io
import json
import os
import struct
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import ae  # noqa: E402
import build  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402
import update  # noqa: E402

RULES = build.compile_rules(".", [
    {"name": "Reports", "keywords": ["report"]},
    {"name": "Plans", "keywords": ["plan"]},
    {"name": "Decks", "keywords": ["deck"], "kinds": ["Slides"]},
])


class Base(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        self.con = db.connect(self.d)

    def cfg(self, text):
        with open(os.path.join(self.d, "config.toml"), "a", encoding="utf-8") as f:
            f.write(text)

    def rows(self):
        self.con.commit()
        return {r["id"]: r for r in build.collect(self.d, common.load_config(self.d))[0]}

    def ae(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = ae.main(["--data", self.d] + list(argv))
        return rc, out.getvalue()


class CategorizeTest(Base):
    def test_fallback_order(self):
        c = build.categorize
        self.assertEqual(c(RULES, "x", "", None, stored="plans"), "Plans")  # stored beats keywords, config spelling
        self.assertEqual(c(RULES, "A report", "", None, stored="Nonsense"), "Reports")  # unknown stored ignored
        self.assertEqual(c(RULES, "The report", "", "Slides", stored=None), "Decks")  # kind beats an earlier category's keywords
        self.assertEqual(c(RULES, "x", "a plan here", None), "Plans")  # description counts
        self.assertEqual(c(RULES, "nothing", "", "Page"), "Uncategorized")
        self.assertEqual(build.FALLBACK, "Uncategorized")

    def test_override_beats_stored(self):
        self.cfg('[overrides."aaaaaaaaaa"]\ncategory="Docs"\n')
        db.upsert_artifact(self.con, "aaaaaaaaaa", title="t", category="Plans")
        self.assertEqual(self.rows()["aaaaaaaaaa"]["category"], "Docs")

    def test_stored_beats_kind_in_payload(self):
        db.upsert_artifact(self.con, "aaaaaaaaaa", title="t", kind="Docs", category="Plans")
        db.upsert_artifact(self.con, "bbbbbbbbbb", title="t", kind="Slides")
        r = self.rows()
        self.assertEqual((r["aaaaaaaaaa"]["category"], r["bbbbbbbbbb"]["category"]), ("Plans", "Decks"))


class TopicsTest(Base):
    TR = build.compile_topics(".", [{"name": "Garden plan"}, {"name": "Monitors", "keywords": ["monitor", "triage"]}])

    def test_title_keywords_when_never_tagged(self):
        self.assertEqual(build.tag_topics(self.TR, "Garden plan v2 triage", None, None), (["Garden plan", "Monitors"], []))
        self.assertEqual(build.tag_topics(self.TR, "Other", None, None), ([], []))

    def test_stored_list_wins_and_is_filtered(self):
        t = build.tag_topics(self.TR, "Garden plan", ["monitors", "Gone"], json.dumps(["New One"]))
        self.assertEqual(t, (["Monitors", "Garden plan"], ["New One"]))  # plus the title keyword match
        self.assertEqual(build.tag_topics(self.TR, "Garden plan", [], None)[1], [])

    def test_suggestion_becomes_topic_once_configured(self):
        self.assertEqual(build.tag_topics(self.TR, "x", [], ["monitors"]), (["Monitors"], []))


class BatchTest(Base):
    def setUp(self):
        super().setUp()
        self.cfg('[[topics]]\nname = "Garden plan"\n[[topics]]\nname = "Monitors"\n')
        for i in "ab":
            db.upsert_artifact(self.con, i * 10, title="Row " + i, owned=1, description="old" if i == "b" else None,
                               desc_source="describer" if i == "b" else None)
        self.con.commit()

    def folder(self):
        rc, out = self.ae("batch", "start")
        return out.strip()

    def test_start_numbers_folders(self):
        a, b = self.folder(), self.folder()
        self.assertEqual((os.path.basename(a), os.path.basename(b)), ("1", "2"))
        self.assertTrue(os.path.isdir(b))
        self.assertFalse(os.path.exists(a))  # a new batch removes the older folders

    def test_manifest_lists_nonempty_files_only(self):
        f = self.folder()
        open(os.path.join(f, "aaaaaaaaaa.txt"), "w").write("some text")
        open(os.path.join(f, "bbbbbbbbbb.txt"), "w").write("")
        rc, out = self.ae("batch", "manifest", f)
        txt = open(os.path.join(f, "manifest.txt"), encoding="utf-8").read()
        self.assertIn("items: 1", out)
        self.assertIn("Categories (pick exactly one): Reports, Plans, Dashboards, Decks, Docs, Personal", txt)
        self.assertIn("Garden plan, Monitors", txt)
        self.assertIn("## ITEM aaaaaaaaaa\nfile: " + os.path.join(f, "aaaaaaaaaa.txt"), txt)
        self.assertNotIn("bbbbbbbbbb", txt)
        self.assertNotIn("Uncategorized", txt)

    def test_save_parses_and_filters(self):
        f = self.folder()
        open(os.path.join(f, "aaaaaaaaaa.txt"), "w").write("some text")
        self.ae("batch", "manifest", f)
        res = os.path.join(f, "result.jsonl")
        with open(res, "w", encoding="utf-8") as fh:
            fh.write("```json\n")
            fh.write(json.dumps({"id": "aaaaaaaaaa", "description": "A report on things.", "category": "reports",
                                 "topics": ["monitors", "Nope", "Garden plan", "Monitors"], "new_topic": "Cost Tools"}) + "\n")
            fh.write("garbage line\n{not json}\n")
            fh.write(json.dumps({"id": "zzzzzzzzzz", "description": "x", "category": "Plans"}) + "\n")
            fh.write(json.dumps({"id": "bbbbbbbbbb", "category": "Made Up", "topics": ["Nope"]}) + "\n```\n")
        rc, out = self.ae("batch", "save", res)
        self.assertIn("saved 1, skipped 3, suggested 1", out)
        a, b = db.get(self.con, "aaaaaaaaaa"), db.get(self.con, "bbbbbbbbbb")
        self.assertEqual((a["description"], a["desc_source"], a["category"], a["cat_source"]),
                         ("A report on things.", "describer", "Reports", "describer"))
        self.assertEqual(json.loads(a["topics"]), ["Monitors", "Garden plan"])
        self.assertEqual(json.loads(a["topic_suggest"]), ["Cost Tools"])
        self.assertEqual((b["category"], b["topics"], b["description"]), (None, None, "old"))  # unknown category dropped, no topics stays NULL

    def test_new_topic_not_a_configured_one(self):
        f = self.folder()
        res = os.path.join(f, "r.jsonl")
        open(res, "w").write(json.dumps({"id": "aaaaaaaaaa", "new_topic": "monitors"}) + "\n")
        self.ae("batch", "save", res)
        self.assertIsNone(db.get(self.con, "aaaaaaaaaa")["topic_suggest"])

    def test_recat_and_save_marks_recat(self):
        rc, out = self.ae("batch", "recat")
        folder = out.splitlines()[0].rsplit(os.sep, 1)[0]
        txt = open(os.path.join(folder, "manifest.txt"), encoding="utf-8").read()
        self.assertIn("items: 1", out)
        self.assertIn("## ITEM bbbbbbbbbb\ntext: Row b — old", txt)
        self.assertNotIn("## ITEM aaaaaaaaaa", txt)  # not described yet
        res = os.path.join(folder, "result.jsonl")
        open(res, "w").write(json.dumps({"id": "bbbbbbbbbb", "description": "ignored for text items", "category": "Plans",
                                         "topics": ["Monitors"]}) + "\n")
        self.ae("batch", "save", res)
        b = db.get(self.con, "bbbbbbbbbb")
        self.assertEqual((b["category"], b["cat_source"], b["description"]), ("Plans", "recat", "old"))
        rc, out = self.ae("batch", "recat")
        self.assertIn("items: 0", out)

    def test_topics_command(self):
        db.upsert_artifact(self.con, "aaaaaaaaaa", topics='["Monitors"]', topic_suggest='["Cost Tools"]')
        self.con.commit()
        rc, out = self.ae("topics")
        self.assertIn("Monitors (1)", out)
        self.assertIn("Cost Tools (1)", out)
        self.ae("topics", "--accept", "Cost Tools")
        self.assertIn({"name": "Cost Tools"}, common.load_config(self.d)["topics"])
        self.ae("topics", "--reject", "cost tools")
        self.assertIsNone(db.get(db.connect(self.d), "aaaaaaaaaa")["topic_suggest"])

    def test_status_categorized_line(self):
        rc, out = self.ae("status")
        self.assertIn("categorized: 0 of 1 described", out)


def write_rows(d, rows):
    p = os.path.join(d, "list.json")
    json.dump(rows, open(p, "w"))
    return p


class RevokedTest(Base):
    def ingest(self, rows, complete=True):
        describe.ingest_list(self.d, write_rows(self.d, rows), shared_complete=complete)
        self.con.commit()

    def sh(self, i, **kw):
        return dict({"url": "https://claude.ai/artifact/" + i * 10, "title": i, "scope": "shared"}, **kw)

    def gone(self, i):
        return db.get(db.connect(self.d), i * 10)["shared_gone"]

    def test_seen_then_missing_is_revoked_and_back_clears(self):
        self.ingest([self.sh("a", access="edit", other_org=True), self.sh("b")])
        r = db.get(self.con, "a" * 10)
        self.assertEqual((r["access"], r["other_org"], r["owned"]), ("edit", 1, 0))
        self.assertIsNotNone(r["shared_seen"])
        self.ingest([self.sh("b"), self.sh("c", other_org=True)])  # 0.2.11: the list must carry other-org rows
        self.assertIsNotNone(self.gone("a"))
        self.assertIsNone(self.gone("b"))
        self.assertTrue(self.rows()["a" * 10]["revoked"])
        self.ingest([self.sh("a"), self.sh("b")])
        self.assertIsNone(self.gone("a"))
        self.assertFalse(self.rows()["a" * 10]["revoked"])

    def test_same_org_only_list_keeps_other_org_rows(self):  # 0.2.11 (Plant Shelf Explorer)
        self.ingest([self.sh("a", other_org=True, access="comment"), self.sh("b"), self.sh("c")])
        self.ingest([self.sh("b")])  # complete, but no other-org row in it
        self.assertIsNone(self.gone("a"))
        self.assertIsNotNone(self.gone("c"))  # a same-org row missing from it is still marked
        self.assertFalse(self.rows()["a" * 10]["revoked"])

    def test_shared_pending_row_is_unread_not_pending(self):  # 0.2.11
        self.ingest([self.sh("a")])
        r = self.rows()["a" * 10]
        self.assertFalse(r["pending"])
        self.assertTrue(r["unread"])

    def test_zero_shared_rows_never_revokes(self):
        self.ingest([self.sh("a")])
        self.ingest([{"url": "https://claude.ai/artifact/" + "m" * 10, "title": "m", "scope": "mine"}])
        self.assertIsNone(self.gone("a"))

    def test_not_complete_never_revokes(self):
        self.ingest([self.sh("a"), self.sh("b")])
        self.ingest([self.sh("b")], complete=False)
        self.assertIsNone(self.gone("a"))

    def test_never_seen_rows_not_revoked(self):
        db.upsert_artifact(self.con, "n" * 10, title="n", owned=0, other_org=1)  # from history, never in a shared list
        self.con.commit()
        self.ingest([self.sh("b")])
        self.assertIsNone(self.gone("n"))

    def test_mark_revoked_helper(self):
        db.upsert_artifact(self.con, "a" * 10, owned=0, shared_seen=1.0)
        db.upsert_artifact(self.con, "b" * 10, owned=1, shared_seen=1.0)
        self.assertEqual(describe.mark_revoked(self.con, [], 5.0), 1)
        self.assertEqual(db.get(self.con, "a" * 10)["shared_gone"], 5.0)
        self.assertIsNone(db.get(self.con, "b" * 10)["shared_gone"])

    def test_payload_from_access(self):
        self.ingest([self.sh("a", access="can comment", other_org=True, creator="Sam"), self.sh("b", other_org=False)])
        r = self.rows()
        self.assertEqual((r["a" * 10]["mine"], r["a" * 10]["access"], r["a" * 10]["other_org"]), (False, "comment", True))
        self.assertEqual((r["b" * 10]["mine"], r["b" * 10]["access"]), (False, ""))


class LocalCopyTest(Base):
    def excerpt(self, aid, owned):
        db.upsert_artifact(self.con, aid, title="t", owned=owned, url="https://claude.ai/artifact/" + aid)
        self.con.commit()
        src = os.path.join(self.d, aid + ".html")
        open(src, "w", encoding="utf-8").write("<html><body>" + "words " * 40 + "</body></html>")
        describe.excerpt_for(self.d, src, os.path.join(self.d, "out.txt"), aid=aid)
        return db.get(db.connect(self.d), aid)

    def test_copy_only_for_others(self):
        o = self.excerpt("o" * 10, 0)
        self.assertEqual(o["local_copy"], "copies/%s.html" % ("o" * 10))
        self.assertTrue(os.path.exists(os.path.join(self.d, o["local_copy"])))
        m = self.excerpt("m" * 10, 1)
        self.assertIsNone(m["local_copy"])
        self.assertFalse(os.path.exists(os.path.join(self.d, "copies", "m" * 10 + ".html")))
        r = self.rows()
        self.assertEqual((r["o" * 10]["copy"], r["m" * 10]["copy"]), ("copies/%s.html" % ("o" * 10), ""))

    def test_missing_file_gives_empty_copy(self):
        o = self.excerpt("o" * 10, 0)
        os.remove(os.path.join(self.d, o["local_copy"]))
        self.assertEqual(self.rows()["o" * 10]["copy"], "")


class UpdateCheckTest(Base):
    def test_fresh_cache_makes_no_request(self):
        get = mock.Mock(return_value="v0.3.0")
        update.latest(self.d, "0.2.0", now=1000, get=get)
        update.latest(self.d, "0.2.0", now=1000 + 3600, get=get)
        self.assertEqual(get.call_count, 1)

    def test_stale_cache_one_request(self):
        get = mock.Mock(return_value="v0.3.0")
        update.latest(self.d, "0.2.0", now=1000, get=get)
        update.latest(self.d, "0.2.0", now=1000 + 86401, get=get)
        self.assertEqual(get.call_count, 2)

    def test_failure_is_cached_and_keeps_last_good(self):
        good = mock.Mock(return_value="v0.3.0")
        update.latest(self.d, "0.2.0", now=1000, get=good)
        bad = mock.Mock(return_value=None)
        self.assertEqual(update.latest(self.d, "0.2.0", now=1000 + 90000, get=bad), "v0.3.0")
        update.latest(self.d, "0.2.0", now=1000 + 90100, get=bad)
        self.assertEqual(bad.call_count, 1)  # the failure was cached for a day too

    def test_failure_with_no_history_is_no_badge(self):
        self.assertIsNone(update.badge(self.d, "0.2.0", {}, now=1, get=lambda v: None))

    @mock.patch.dict(os.environ, {"AE_UPDATE_CHECK": "1"})
    def test_newer_and_not_newer(self):
        self.assertEqual(update.badge(self.d, "0.2.0", {}, now=1, get=lambda v: "v0.2.1")["latest"], "v0.2.1")
        d2 = helpers.tmp()
        self.assertIsNone(update.badge(d2, "0.2.0", {}, now=1, get=lambda v: "v0.2.0"))
        self.assertIsNone(update.badge(helpers.tmp(), "0.2.0", {}, now=1, get=lambda v: "v0.1.9"))

    def test_disabled_by_env_and_config(self):
        get = mock.Mock(return_value="v9.9.9")
        self.assertIsNone(update.badge(self.d, "0.2.0", {}, now=1, get=get))  # helpers sets AE_UPDATE_CHECK=0
        with mock.patch.dict(os.environ, {"AE_UPDATE_CHECK": "1"}):
            self.assertIsNone(update.badge(self.d, "0.2.0", {"page": {"update_check": False}}, now=1, get=get))
            self.assertIsNotNone(update.badge(self.d, "0.2.0", {"page": {"update_check": True}}, now=1, get=get))
        self.assertEqual(get.call_count, 1)

    def test_build_bakes_badge_and_version(self):
        db.upsert_artifact(self.con, "aaaaaaaaaa", title="t", owned=1)
        self.con.commit()
        with mock.patch.dict(os.environ, {"AE_UPDATE_CHECK": "1"}), \
                mock.patch.object(update, "fetch", lambda v: "v9.0.0"):
            html = open(build.build(self.d, max_age=0), encoding="utf-8").read()
            off = open(build.build(self.d, max_age=0, update_check=False), encoding="utf-8").read()
        self.assertIn('"latest": "v9.0.0"', html)
        self.assertNotIn("v9.0.0", off)
        self.assertIn('"version": "0.2.12"', html)


class FaviconTest(Base):
    def test_ico_written_and_valid(self):
        build.build(self.d, max_age=0, update_check=False)
        blob = open(os.path.join(self.d, "favicon.ico"), "rb").read()
        self.assertEqual(struct.unpack("<HHH", blob[:6]), (0, 1, 2))
        sizes = []
        for i in range(2):
            w, h, _, _, planes, bpp, ln, off = struct.unpack("<BBBBHHII", blob[6 + 16 * i:22 + 16 * i])
            sizes.append((w, h, bpp))
            self.assertEqual(struct.unpack("<I", blob[off:off + 4])[0], 40)
            self.assertLessEqual(off + ln, len(blob))
        self.assertEqual(sizes, [(16, 16, 32), (32, 32, 32)])
        # opaque pixel inside a card carries the accent (BGRA), the gap between cards is transparent
        off = struct.unpack("<I", blob[6 + 16 + 12:6 + 16 + 16])[0]
        px = lambda x, y: blob[off + 40 + ((31 - y) * 32 + x) * 4:][:4]  # noqa: E731
        self.assertEqual(px(9, 9), bytes((0x5c, 0x6b, 0x0f, 255)))
        self.assertEqual(px(16, 16)[3], 0)

    def test_svg_uri_in_page_and_accent_validated(self):
        self.cfg('[page]\naccent = "red; evil"\n')
        html = open(build.build(self.d, max_age=0, update_check=False), encoding="utf-8").read()
        self.assertNotIn("__FAVICON_SVG__", html)
        self.assertIn("data:image/svg+xml,", html)
        self.assertIn("%230f6b5c", html)
        self.assertNotIn("evil", html)

    def test_rewritten_when_accent_changes(self):
        build.build(self.d, max_age=0, update_check=False)
        a = open(os.path.join(self.d, "favicon.ico"), "rb").read()
        self.cfg('[page]\naccent = "#123456"\n')
        build.build(self.d, max_age=0, update_check=False)
        self.assertNotEqual(a, open(os.path.join(self.d, "favicon.ico"), "rb").read())


class ColorsTest(Base):
    def payload(self):
        html = open(build.build(self.d, max_age=0, update_check=False), encoding="utf-8").read()
        line = html[html.index("const DATA = ") + 13:]
        return json.loads(line[:line.index("\n")].rstrip(";"))

    def test_slots_override_and_neutral(self):
        self.cfg('[[categories]]\nname = "Extra"\ncolor = "#112233"\n')
        cfg = common.load_config(self.d)
        cats = cfg["categories"]  # arrays replace: user list is just Extra
        self.assertEqual([c["name"] for c in cats], ["Extra"])
        out = build.category_colors(cats)
        self.assertEqual(out[0], {"name": "Extra", "color": "#112233", "dark": "#112233"})
        self.assertEqual(out[-1], {"name": "Uncategorized", "color": "#898781", "dark": "#898781"})

    def test_default_slot_order_and_ninth_neutral(self):
        out = build.category_colors([{"name": "c%d" % i} for i in range(10)])
        self.assertEqual((out[0]["color"], out[0]["dark"]), ("#2a78d6", "#3987e5"))
        self.assertEqual((out[7]["color"], out[7]["dark"]), ("#e34948", "#e66767"))
        self.assertEqual(out[8]["color"], "#898781")
        self.assertEqual(out[9]["color"], "#898781")

    def test_payload_config(self):
        db.upsert_artifact(self.con, "aaaaaaaaaa", title="t", owned=1, category="Gone")
        self.con.commit()
        self.cfg('[[topics]]\nname = "T1"\n')
        p = self.payload()["config"]
        self.assertEqual([c["name"] for c in p["categories"]][:3], ["Reports", "Plans", "Dashboards"])
        self.assertEqual(p["categories"][0]["color"], "#2a78d6")
        self.assertEqual(p["categories"][-1]["name"], "Uncategorized")
        self.assertEqual((p["topics"], p["version"], p["accent"]), (["T1"], "0.2.12", "#0f6b5c"))


if __name__ == "__main__":
    unittest.main()
