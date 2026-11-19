"""0.2.2: ownership mark, no "from" text, labelled fallback dates, several new topics per item."""
import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import build  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TPL = os.path.join(ROOT, "page", "template.html")
NODE = shutil.which("node")


def tpl():
    return open(TPL, encoding="utf-8").read()


class Payload(unittest.TestCase):
    def test_mine_seen_and_no_from(self):
        d = helpers.tmp()
        con = db.connect(d)
        db.upsert_artifact(con, "aaaaaaaaaa", title="Mine", owned=1)
        db.upsert_artifact(con, "bbbbbbbbbb", title="Theirs", owned=0, creator="Sam", last_accessed=300)
        con.execute("UPDATE artifacts SET first_seen=100 WHERE id='aaaaaaaaaa'")
        con.execute("UPDATE artifacts SET first_seen=200 WHERE id='bbbbbbbbbb'")
        con.commit()
        con.close()
        r = {x["id"]: x for x in build.collect(d, common.load_config(d))[0]}
        a, b = r["aaaaaaaaaa"], r["bbbbbbbbbb"]
        self.assertEqual((a["mine"], b["mine"]), (True, False))
        self.assertTrue("from" not in a and "from" not in b)
        self.assertEqual((b["seen"], b["accessed"], b["created"], b["modified"]), (200, 300, None, None))
        self.assertEqual(b["recent"], 300)
        self.assertEqual(a["recent"], 100)  # no date at all still sorts by first seen


class Template(unittest.TestCase):
    def test_strings(self):
        t = tpl()
        for s in ("from " + "<", 'el("span", "fm"', "fromNode", "r.from"):
            self.assertNotIn(s, t)
        self.assertNotIn("other org", t)  # no organization text either
        self.assertIn(".card.mine{border-left-color:var(--mine)}", t)
        self.assertIn("tbody tr.mine>td:first-child", t)
        self.assertIn("--other:#7b8da3", t)  # light
        self.assertIn("--other:#8fa2b8", t)  # dark

    @unittest.skipUnless(NODE, "node not installed")
    def test_date_fallback_is_labelled_and_never_unknown(self):
        t = tpl()
        code = t[t.index("function dateOf"):t.index("function when")] + """
const rows = [{created:5,modified:6,seen:1,accessed:2}, {seen:1,accessed:2}, {seen:1}, {}];
console.log(JSON.stringify(rows.map(r => [dateOf(r,"created"), dateOf(r,"modified")])));"""
        out = json.loads(subprocess.run([NODE], input=code, capture_output=True, encoding="utf-8", check=True).stdout)
        self.assertEqual(out[0], [[5, ""], [6, ""]])
        self.assertEqual(out[1], [[1, "first seen"], [2, "last accessed"]])
        self.assertEqual(out[2], [[1, "first seen"], [1, "first seen"]])
        self.assertEqual(out[3], [[0, ""], [0, ""]])


class Describer(unittest.TestCase):
    def test_prompt_asks_for_several_broad_topics(self):
        a = open(os.path.join(ROOT, "agents", "describer.md"), encoding="utf-8").read()
        self.assertIn('"new_topics":[]', a)
        self.assertIn("up to 3 short topic names", a)
        import describe
        d = helpers.tmp()
        f = os.path.join(d, "b")
        os.makedirs(f)
        describe.write_manifest(d, f, [("aaaaaaaaaa", "text", "t")])
        self.assertIn("up to 3 new broad topics", open(os.path.join(f, "manifest.txt"), encoding="utf-8").read())
