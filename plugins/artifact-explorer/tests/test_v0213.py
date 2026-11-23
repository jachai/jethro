"""0.2.13: link-only stubs (no title, no owner) are not shown; Remove from list on the page."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
import io

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import build  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402

TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "page", "template.html")
NODE = shutil.which("node")
A, B, C = "DemoStubId000000000001", "DemoStubId000000000002", "DemoStubId000000000003"


def tpl():
    return open(TPL, encoding="utf-8").read()


def url(aid):
    return "https://claude.ai/artifact/" + aid


class StubTest(unittest.TestCase):
    def ids(self, d):
        return {r["id"] for r in build.collect(d, {})[0]}

    def test_history_only_row_without_title_is_hidden(self):
        d = helpers.tmp()
        con = db.connect(d)
        db.upsert_artifact(con, A, url=url(A), desc_status="pending")  # history visit titled "Page not found"
        db.add_event(con, A, 100.0, "visit", "browser:chrome")
        db.upsert_artifact(con, B, url=url(B), title="Shared plan", desc_status="pending")  # a titled visit
        db.upsert_artifact(con, C, url=url(C), title=" ", owned=1)  # own row with a blank title
        con.commit()
        con.close()
        self.assertEqual(self.ids(d), {B, C})

    def test_list_fills_it_in_and_it_appears(self):
        d = helpers.tmp()
        con = db.connect(d)
        db.upsert_artifact(con, A, url=url(A), desc_status="pending")
        con.commit()
        con.close()
        self.assertEqual(self.ids(d), set())
        f = os.path.join(tempfile.mkdtemp(dir=d), "list.json")
        json.dump([{"url": url(A), "title": "Back again", "owned": True}], open(f, "w"))
        with redirect_stdout(io.StringIO()):
            describe.ingest_list(d, f)
        rows = build.collect(d, {})[0]
        self.assertEqual([(r["id"], r["title"]) for r in rows], [(A, "Back again")])

    def test_known_owner_still_shows_untitled(self):
        d = helpers.tmp()
        con = db.connect(d)
        db.upsert_artifact(con, A, url=url(A), owned=0)
        con.commit()
        con.close()
        self.assertEqual([r["title"] for r in build.collect(d, {})[0]], ["Untitled"])


@unittest.skipUnless(NODE, "node not installed")
class RemoveJsTest(unittest.TestCase):
    def run_js(self, body):
        t = tpl()
        code = t[t.index("/*REMOVE-START*/"):t.index("/*REMOVE-END*/")] + "\n" + body
        return json.loads(subprocess.run([NODE], input=code, capture_output=True, encoding="utf-8", check=True).stdout)

    def test_load_save_pool(self):
        out = self.run_js("""
const mem = {}, store = {getItem: k => k in mem ? mem[k] : null, setItem: (k, v) => { mem[k] = v; }};
const empty = loadRemoved(store).size;
const s = new Set(["a"]); saveRemoved(store, s);
const back = Array.from(loadRemoved(store));
mem[RM_KEY] = '["b", 3, null, "c"]'; const filtered = Array.from(loadRemoved(store));
mem[RM_KEY] = "{bad json"; const bad = loadRemoved(store).size;
mem[RM_KEY] = '{"a": 1}'; const obj = loadRemoved(store).size;
const none = loadRemoved(null).size; saveRemoved(null, s);
const throwing = {getItem(){ throw new Error("denied"); }, setItem(){ throw new Error("denied"); }};
const thrown = loadRemoved(throwing).size; saveRemoved(throwing, s);
const rows = [{id: "a"}, {id: "b"}, {id: "c"}], rm = new Set(["b"]);
console.log(JSON.stringify({empty, back, filtered, bad, obj, none, thrown, key: RM_KEY,
  list: pool(rows, rm, false).map(r => r.id), removed: pool(rows, rm, true).map(r => r.id)}));
""")
        self.assertEqual(out["key"], "ae-removed")
        self.assertEqual((out["empty"], out["bad"], out["obj"], out["none"], out["thrown"]), (0, 0, 0, 0, 0))
        self.assertEqual(out["back"], ["a"])
        self.assertEqual(out["filtered"], ["b", "c"])
        self.assertEqual(out["list"], ["a", "c"])
        self.assertEqual(out["removed"], ["b"])


class RemoveTemplateTest(unittest.TestCase):
    def test_wired_into_cards_table_chips_and_toolbar(self):
        t = tpl()
        self.assertIn('td.appendChild(rmBtn(r))', t)  # table: next to Open
        self.assertIn('c.appendChild(rmBtn(r))', t)  # cards
        self.assertIn('pool(rows, removed, showRm).filter(r => match(r, q))', t)  # chip counts skip removed rows
        self.assertIn('id="rmtog"', t)
        self.assertIn('id="rmnote"', t)
        self.assertIn('"Undo"', t)
        self.assertIn('"Restore"', t)
        # the view state ("ae-view") never carries the removed list or the Removed toggle
        self.assertNotIn("st.showRm", t)
