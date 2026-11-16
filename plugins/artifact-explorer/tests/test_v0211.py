"""0.2.11: Jonathan's page review (named windows, thumbnail-only card links, Open button, topic chip colors)."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import db  # noqa: E402
import describe  # noqa: E402
import promote  # noqa: E402

TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "page", "template.html")
NODE = shutil.which("node")


def tpl():
    return open(TPL, encoding="utf-8").read()


STUB = """
function el(tag, cls, text){ return {tag, className: cls || "", textContent: text || "", attrs: {},
  setAttribute(k, v){ this.attrs[k] = v; }}; }
"""


@unittest.skipUnless(NODE, "node not installed")
class LinkTest(unittest.TestCase):
    def run_js(self, body):
        t = tpl()
        code = STUB + t[t.index("/*LINK-START*/"):t.index("/*LINK-END*/")] + "\n" + body
        return json.loads(subprocess.run([NODE], input=code, capture_output=True, encoding="utf-8", check=True).stdout)

    def test_named_window_per_artifact(self):
        out = self.run_js("""
const a = {id: "DemoShortId00000000002", url: "https://claude.ai/artifact/DemoShortId00000000002"};
const b = {id: "other", url: "https://claude.ai/artifact/other"};
const o1 = openBtn(a), o2 = openBtn(a), o3 = openBtn(b);
console.log(JSON.stringify({t1: o1.target, t2: o2.target, t3: o3.target, href: o1.href, text: o1.textContent,
  bad: openBtn({id: "x", url: "javascript:alert(1)"}), none: openBtn({id: "y", url: ""}),
  odd: winName({id: "a b/c"})}));
""")
        self.assertEqual(out["t1"], "ae-DemoShortId00000000002")
        self.assertEqual(out["t1"], out["t2"])
        self.assertNotEqual(out["t1"], out["t3"])
        self.assertEqual(out["href"], "https://claude.ai/artifact/DemoShortId00000000002")
        self.assertEqual(out["text"], "Open")
        self.assertIsNone(out["bad"])
        self.assertIsNone(out["none"])
        self.assertEqual(out["odd"], "ae-a_b_c")


class TemplateTest(unittest.TestCase):
    def test_cards_link_only_thumbnail(self):
        t = tpl()
        self.assertNotIn("stretch", t)  # no link stretched over the whole card or row
        self.assertIn('b.appendChild(el("h3")).appendChild(titleText(r));', t)
        self.assertIn('el(link ? "a" : "div", cls)', t)  # the thumbnail is the link
        self.assertIn('if (cols.indexOf("open") < 0) cols.push("open");', t)

    def test_topic_chips_share_pill_colors(self):
        t = tpl()
        self.assertIn('b.classList.add("tpc"); topicTint(b, topic);', t)
        self.assertIn('function topicPill(t, tag){ return topicTint(el(tag, "tp", t), t); }', t)


class TopicFamilyTest(unittest.TestCase):
    """Item 3: 'demo pipeline' was promoted from two versions of one diagram."""
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = db.connect(self.d)

    def add(self, i, title, suggest):
        db.upsert_artifact(self.con, "a%d" % i, title=title, kind="Page", owned=1)
        self.con.execute("UPDATE artifacts SET topic_suggest=? WHERE id=?", (json.dumps(suggest), "a%d" % i))
        self.con.commit()

    def test_one_title_family_is_not_promoted(self):
        self.add(1, "demo build-trace — full pipeline graph exemplar", ["demo pipeline"])
        self.add(2, "demo build-trace diagram — Garden Run v1", ["demo pipeline"])
        self.assertEqual(promote.resolve(self.con, {})[0], [])
        self.add(3, "Pipeline cost review", ["demo pipeline"])  # a second family promotes it
        self.assertEqual(promote.resolve(self.con, {})[0], ["demo pipeline"])

    def test_old_promotion_rechecked_once(self):
        self.add(1, "demo build-trace one", ["demo pipeline"])
        self.add(2, "demo build-trace two", ["demo pipeline"])
        db.state_set(self.con, promote.STATE_KEY, {"demo pipeline": "demo pipeline"})  # saved by 0.2.10
        self.con.commit()
        self.assertEqual(promote.resolve(self.con, {})[0], [])
        self.assertTrue(db.state_get(self.con, promote.RECHECK_KEY))
        db.state_set(self.con, promote.STATE_KEY, {"kept": "kept"})  # after the recheck, promotions stick again
        self.con.commit()
        self.assertEqual(promote.resolve(self.con, {})[0], ["kept"])

    def test_hide_and_unhide(self):
        self.add(1, "Alpha plan", ["Pricing"])
        self.add(2, "Beta notes", ["pricing"])
        self.assertEqual(promote.resolve(self.con, {})[0], ["Pricing"])
        with redirect_stdout(io.StringIO()):
            describe.topics_cmd(self.d, hide="Pricing")
        self.assertEqual(promote.resolve(db.connect(self.d), {})[0], [])
        with redirect_stdout(io.StringIO()):
            describe.topics_cmd(self.d, unhide="pricing")
        self.assertEqual(promote.resolve(db.connect(self.d), {})[0], ["Pricing"])


class FirstLoadCapTest(unittest.TestCase):
    """Item 6: the first load covers the newest 100 artifacts (configurable)."""
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def ingest(self, n, start=0):
        rows = [{"url": "https://claude.ai/artifact/%010d" % i, "title": "T%d" % i, "scope": "mine",
                 "updated": "2026-%02d-%02d" % (1 + (i // 28) % 12, 1 + i % 28)} for i in range(start, start + n)]
        p = os.path.join(self.d, "list.json")
        json.dump(rows, open(p, "w"))
        with redirect_stdout(io.StringIO()):
            describe.ingest_list(self.d, p)
        return db.connect(self.d)

    def in_window(self, con, cfg=None):
        win = db.window(con, cfg or {"window": {"days": 0}})
        cond, args = db.window_sql(win)
        return con.execute("SELECT count(*) FROM artifacts WHERE " + cond, args).fetchone()[0]

    def test_cap_on_first_load_only(self):
        con = self.ingest(150)
        self.assertEqual(self.in_window(con), 100)
        con = self.ingest(10, start=150)  # later loads are not capped again
        self.assertTrue(db.state_get(con, db.FIRST_LOAD_DONE))
        db.state_set(con, "window_extra_days", 30)  # refresh older lifts the cap
        con.commit()
        self.assertEqual(self.in_window(con), 160)

    def test_cap_configurable_and_off(self):
        open(os.path.join(self.d, "config.toml"), "w").write("[window]\nfirst_load = 0\n")
        con = self.ingest(150)
        self.assertIsNone(db.state_get(con, db.FIRST_LOAD_KEY))

    def test_existing_catalog_not_capped(self):
        con = db.connect(self.d)
        db.upsert_artifact(con, "x" * 10, title="old", description="described before 0.2.11", owned=1)
        con.commit()
        con = self.ingest(150)
        self.assertIsNone(db.state_get(con, db.FIRST_LOAD_KEY))


if __name__ == "__main__":
    unittest.main()
