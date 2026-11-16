"""0.2.3 page: topic pill colors, pills on cards and rows, category fallback (categorize.py)."""
import colorsys  # noqa: F401
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import build  # noqa: E402
import categorize  # noqa: E402
import db  # noqa: E402
from test_build import payload  # noqa: E402

TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "page", "template.html")


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]


def contrast(a, b):
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + .05) / (y + .05)


class PaletteTest(unittest.TestCase):
    def test_twelve_hues_with_contrast_in_both_themes(self):
        self.assertEqual(len(build.TOPIC_PALETTE), 12)
        self.assertEqual(len(set(build.TOPIC_PALETTE)), 12)
        for lb, lf, db_, df in build.TOPIC_PALETTE:
            self.assertGreaterEqual(contrast(lb, lf), 4.5)
            self.assertGreaterEqual(contrast(db_, df), 4.5)

    def test_slot_stable_and_normalized(self):
        self.assertEqual(build.topic_slot("Garden plan"), build.topic_slot("  garden   PLAN "))
        self.assertEqual(build.topic_slot("Garden plan"), build.topic_slot("Garden plan"))
        self.assertEqual(build.topic_slot("Change Orders"), build.topic_slot("change orders"))
        slots = {build.topic_slot("t%d" % i) for i in range(200)}
        self.assertEqual(slots, set(range(12)))


class CategorizeTest(unittest.TestCase):
    def cat(self, **row):
        return categorize.derive_category(row)

    def test_kind_first(self):
        self.assertEqual(self.cat(kind="Slides", title="Budget plan"), "Decks")
        self.assertEqual(self.cat(kind="Dashboard", title="x"), "Dashboards")
        self.assertEqual(self.cat(kind="Docs", title="Plan"), "Docs")

    def test_titles(self):
        self.assertEqual(self.cat(title="Q3 Garden deck"), "Decks")
        self.assertEqual(self.cat(title="Sprint Burndown"), "Dashboards")
        self.assertEqual(self.cat(title="Root-Cause Fix Plan"), "Plans")
        self.assertEqual(self.cat(title="Contributor Review"), "Reports")
        self.assertEqual(self.cat(title="Release Guide"), "Docs")
        self.assertEqual(self.cat(title="Lisbon Family Trip"), "Personal")
        self.assertEqual(self.cat(title="Pixel Arcade game"), "Personal")

    def test_description_and_none(self):
        self.assertEqual(self.cat(title="Zorp", description="A summary of findings"), "Reports")
        self.assertIsNone(self.cat(title="", description=""))
        self.assertIsNone(self.cat(title="Misc"))
        self.assertEqual(self.cat(title="Misc", url="https://claude.ai/artifact/abc"), "Docs")

    def test_only_allowed(self):
        self.assertEqual(categorize.derive_category({"title": "Big deck", "url": "https://claude.ai/artifact/x"}, ["Plans", "Docs"]), "Docs")
        self.assertEqual(categorize.derive_category({"title": "Big deck"}, ["Slides stuff"]), None)


class PageTest(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        con = db.connect(self.d)
        db.upsert_artifact(con, "aaaaaaaaaa", title="Garden plan plan", owned=1, created=100, modified=200,
                           url="https://claude.ai/artifact/aaaaaaaaaa", description="d", topics='["Garden plan"]')
        db.upsert_artifact(con, "bbbbbbbbbb", title="Mystery", owned=1, created=100)
        con.commit()
        con.close()
        with open(os.path.join(self.d, "config.toml"), "w") as f:
            f.write('[[topics]]\nname = "Garden plan"\n')

    def test_builds_with_guessed_category_and_topic_slots(self):
        p = payload(build.build(self.d))
        rows = {r["id"]: r for r in p["rows"]}
        self.assertEqual(rows["aaaaaaaaaa"]["category"], "Plans")
        self.assertTrue(rows["aaaaaaaaaa"]["guessed"])
        self.assertEqual(rows["aaaaaaaaaa"]["topics"], ["Garden plan"])
        self.assertEqual(p["config"]["topic_slots"]["Garden plan"], build.topic_slot("Garden plan"))
        self.assertEqual(len(p["config"]["topic_palette"]), 12)
        con = db.connect(self.d)
        self.assertIsNone(con.execute("select category from artifacts where id='aaaaaaaaaa'").fetchone()[0])
        con.close()

    def test_pill_markup_in_cards_and_rows(self):
        t = open(TPL, encoding="utf-8").read()
        self.assertEqual(t.count("= topicPills(r)"), 2)  # table title cell and card
        self.assertIn('topicPill(t, "button")', t)
        self.assertIn("st.topics = on ?", t)
        self.assertIn('.tps{display:flex;flex-wrap:wrap', t)
        self.assertIn("max-width:100%", t[t.index(".tp{"):t.index(".tp{") + 200])
        self.assertIn('p.title = "guessed"', t)
        self.assertIn("--tbd", t)


if __name__ == "__main__":
    unittest.main()
