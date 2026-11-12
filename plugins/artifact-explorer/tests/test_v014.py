"""0.1.4: typed artifacts (Docs, Dashboard, Slides) get real descriptions from their own source, rows with no
readable source fall back to the title, and only a recent window of rows is described and captured."""
import io
import json
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import ae  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402

A, B, C, D = "AAAAAAAAAAAAAAAAAAAAAA", "BBBBBBBBBBBBBBBBBBBBBB", "CCCCCCCCCCCCCCCCCCCCCC", "DDDDDDDDDDDDDDDDDDDDDD"
DAY = 86400


def run(d, *args):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = ae.main(["--data", d] + list(args))
    return rc, out.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        self.con = db.connect(self.d)

    def tearDown(self):
        self.con.close()

    def row(self, aid):
        self.con.close()
        self.con = db.connect(self.d)
        return db.get(self.con, aid)

    def write(self, name, text):
        p = os.path.join(self.d, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p


class KindTest(Base):
    def test_norm_kind(self):
        for raw, want in (("Data", "Dashboard"), ("dashboard", "Dashboard"), ("Slides", "Slides"), ("docs", "Docs"),
                          ("Page", "Page"), ("HTML", "Page"), (" Data ", "Dashboard")):
            self.assertEqual(db.norm_kind(raw), want, raw)
        self.assertIsNone(db.norm_kind(""))
        self.assertIsNone(db.norm_kind(None))

    def test_set_kind_cli(self):
        db.upsert_artifact(self.con, A, title="Burndown", owned=1, desc_status="pending")
        self.con.commit()
        self.assertEqual(run(self.d, "set-kind", A, "Data")[0], 0)
        self.assertEqual(self.row(A)["kind"], "Dashboard")
        run(self.d, "set-kind", A, "Slides")
        self.assertEqual(self.row(A)["kind"], "Slides")

    def test_set_kind_never_invents_a_row(self):
        run(self.d, "set-kind", B, "Docs")
        self.assertIsNone(self.row(B))

    def test_excerpt_type_records_normalised_kind_and_typed_text_is_described(self):
        db.upsert_artifact(self.con, A, title="Deck", owned=1, desc_status="pending")
        self.con.commit()
        long = "Section one covers the quarterly plan for the monitor fixes, owners and dates. " * 2
        out = os.path.join(self.d, "excerpt.txt")
        text, skipped = describe.excerpt_for(self.d, self.write("deck.txt", long), out, A, "Data")
        self.assertFalse(skipped)  # a typed artifact's own source is text worth describing
        self.assertEqual(self.row(A)["kind"], "Dashboard")
        self.assertEqual(self.row(A)["desc_status"], "pending")

    def test_pending_json_has_kind(self):
        db.upsert_artifact(self.con, A, title="T", owned=1, kind="Docs", desc_status="pending")
        self.con.commit()
        rows = json.loads(run(self.d, "pending", "--json")[1])
        self.assertEqual(rows[0]["kind"], "Docs")


class TmpdirTest(Base):
    def test_tmpdir_is_an_empty_folder_outside_the_data_folder(self):
        rc, out = run(self.d, "tmpdir", A)
        path = out.strip()
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isdir(path))
        self.assertEqual(os.path.basename(path), A)
        self.assertFalse(os.path.abspath(path).startswith(os.path.abspath(self.d)))
        open(os.path.join(path, "stale.json"), "w").close()
        self.assertEqual(os.listdir(run(self.d, "tmpdir", A)[1].strip()), [])

    def test_tmpdir_refuses_a_path_like_id(self):
        self.assertEqual(run(self.d, "tmpdir", "../x")[0], 2)


class ExcerptSourcesTest(Base):
    def test_json_field_is_read_as_html(self):
        p = self.write("index.html.json", json.dumps({"edit": 3, "text": "<html><body><h1>Sprint Burndown</h1>"
                       "<p>Open issues per week across the platform team with the trend line.</p></body></html>"}))
        out = os.path.join(self.d, "excerpt.txt")
        rc, msg = run(self.d, "excerpt", p, "--json-field", "text", "--out", out)
        self.assertEqual(rc, 0)
        got = open(out, encoding="utf-8").read()
        self.assertTrue(got.startswith("Sprint Burndown Open issues per week"), got)
        self.assertNotIn("<h1>", got)

    def test_several_files_are_joined_in_order(self):
        a = self.write("a.txt", "First part of the source text that is long enough to be described here.")
        b = self.write("b.txt", "Datasets: burndown by week; open issues by owner.")
        out = os.path.join(self.d, "excerpt.txt")
        run(self.d, "excerpt", a, b, "--out", out)
        got = open(out, encoding="utf-8").read()
        self.assertLess(got.index("First part"), got.index("Datasets:"))

    def test_json_field_applies_to_json_files_only(self):
        p = self.write("index.html.json", json.dumps({"text": "<p>Sprint Burndown: open issues per week, team trend.</p>"}))
        t = self.write("source.txt", "Datasets: burndown by week (issues closed per week).")
        out = os.path.join(self.d, "excerpt.txt")
        run(self.d, "excerpt", p, t, "--json-field", "text", "--out", out)
        got = open(out, encoding="utf-8").read()
        self.assertIn("Sprint Burndown", got)
        self.assertIn("Datasets: burndown", got)

    def test_skill_allows_the_typed_sources(self):
        tools = describe._skill_tools()
        for t in ("ArtifactData", "mcp__claude_ai_Claude_Docs__read", "mcp__claude_ai_Claude_Docs__guide"):
            self.assertIn(t, tools)
        skill = open(os.path.join(os.path.dirname(TPL), "..", "skills", "refresh", "SKILL.md"), encoding="utf-8").read()
        for s in ("set-kind", "--no-source", "--json-field text", "deck.json", "window --widen 30", "--retry-no-source"):
            self.assertTrue(s in skill, s)

    def test_missing_json_field_gives_no_text(self):
        p = self.write("x.json", json.dumps({"edit": 1}))
        out = os.path.join(self.d, "excerpt.txt")
        rc, msg = run(self.d, "excerpt", p, "--json-field", "text", "--out", out)
        self.assertEqual(rc, 0)
        self.assertTrue(msg.startswith("skipped"))


class NoSourceTest(Base):
    def setUp(self):
        super().setUp()
        db.upsert_artifact(self.con, A, title="Ops Notes", owned=1, kind="Docs", desc_status="pending")
        db.upsert_artifact(self.con, B, title="Shell", owned=1, kind="Slides", desc_status="skipped",
                           desc_note="no text: typed artifact")
        db.upsert_artifact(self.con, C, title="Tiny", owned=1, desc_status="skipped", desc_note="no text: under 50 characters")
        self.con.commit()

    def test_no_source_uses_title_and_leaves_the_queue(self):
        self.assertEqual(run(self.d, "set-desc", A, "--no-source")[0], 0)
        r = self.row(A)
        self.assertEqual((r["description"], r["desc_source"], r["desc_status"]), ("Ops Notes", "title", "no-source"))
        self.assertEqual(describe.pending_rows(self.con, True), [])

    def test_a_real_description_later_wins(self):
        run(self.d, "set-desc", A, "--no-source")
        f = self.write("desc.txt", "Running notes from the ops sync.")
        run(self.d, "set-desc", A, "--file", f)
        r = self.row(A)
        self.assertEqual((r["description"], r["desc_source"], r["desc_status"]),
                         ("Running notes from the ops sync.", "describer", "ok"))

    def test_no_source_never_replaces_a_description(self):
        f = self.write("desc.txt", "Running notes from the ops sync.")
        run(self.d, "set-desc", A, "--file", f)
        run(self.d, "set-desc", A, "--no-source")
        r = self.row(A)
        self.assertEqual((r["description"], r["desc_status"]), ("Running notes from the ops sync.", "ok"))

    def test_set_desc_needs_file_or_no_source(self):
        with self.assertRaises(SystemExit):
            run(self.d, "set-desc", A)

    def test_retry_flips_no_source_and_typed_skips_back(self):
        run(self.d, "set-desc", A, "--no-source")
        rows = json.loads(run(self.d, "pending", "--retry-no-source", "--json")[1])
        self.assertEqual(sorted(r["id"] for r in rows), [A, B])  # the tiny page stays skipped
        a = self.row(A)
        self.assertEqual((a["description"], a["desc_source"], a["desc_status"]), (None, None, "pending"))
        self.assertEqual(self.row(C)["desc_status"], "skipped")

    def test_status_counts_no_source(self):
        run(self.d, "set-desc", A, "--no-source")
        s = json.loads(run(self.d, "status", "--json")[1])
        self.assertEqual(s["no_source_descriptions"], 1)
        self.assertIn("no source: 1", run(self.d, "status")[1])


def old(con, aid, days, **kw):
    """A row last modified `days` ago."""
    db.upsert_artifact(con, aid, modified=time.time() - days * DAY, **kw)


class WindowTest(Base):
    CFG = {"window": {"days": 60, "key": "modified"}}

    def setUp(self):
        super().setUp()
        old(self.con, A, 5, title="new", owned=1, desc_status="pending")
        old(self.con, B, 75, title="old", owned=1, desc_status="pending")
        old(self.con, C, 200, title="ancient", owned=0, desc_status="pending")
        db.upsert_artifact(self.con, D, title="undated", owned=0, desc_status="pending")  # counts by first_seen
        self.con.commit()

    def test_default_config_has_a_60_day_window(self):
        import common
        self.assertEqual(common.load_config(self.d)["window"], {"days": 60, "key": "modified"})

    def test_in_window_and_cutoff(self):
        w = db.window(self.con, self.CFG)
        self.assertEqual((w["days"], w["extra"]), (60, 0))
        self.assertAlmostEqual(w["cutoff"], time.time() - 60 * DAY, delta=5)
        got = {r["id"]: db.in_window(r, w) for r in self.con.execute("SELECT * FROM artifacts")}
        self.assertEqual(got, {A: True, B: False, C: False, D: True})

    def test_created_and_first_seen_count_when_modified_is_unknown(self):
        db.upsert_artifact(self.con, "EEEEEEEEEEEE", created=time.time() - 90 * DAY)
        self.con.execute("UPDATE artifacts SET first_seen=? WHERE id='EEEEEEEEEEEE'", (time.time() - 90 * DAY,))
        w = db.window(self.con, self.CFG)
        self.assertFalse(db.in_window(db.get(self.con, "EEEEEEEEEEEE"), w))

    def test_zero_days_means_everything(self):
        w = db.window(self.con, {"window": {"days": 0}})
        self.assertIsNone(w["cutoff"])
        self.assertTrue(all(db.in_window(r, w) for r in self.con.execute("SELECT * FROM artifacts")))

    def test_pending_is_windowed(self):
        rows = json.loads(run(self.d, "pending", "--json")[1])
        self.assertEqual(sorted(r["id"] for r in rows), [A, D])

    def test_widen_persists_and_widens(self):
        rc, out = run(self.d, "window", "--widen", "30")
        self.assertEqual(rc, 0)
        self.assertIn("90 days", out)
        self.row(A)  # reopen: the CLI wrote through its own connection
        self.assertEqual(db.state_get(self.con, "window_extra_days"), 30)
        self.assertEqual(sorted(r["id"] for r in json.loads(run(self.d, "pending", "--json")[1])), [A, B, D])
        run(self.d, "window", "--widen", "30")
        self.assertIn("120 days", run(self.d, "window")[1])

    def test_status_window_lines_and_json(self):
        s = json.loads(run(self.d, "status", "--json")[1])
        self.assertEqual((s["window_days"], s["pending_descriptions"], s["older"], s["older_pending"]), (60, 2, 2, 2))
        text = run(self.d, "status")[1]
        self.assertIn("window: 60 days: 2 rows, 0 described, 2 waiting", text)
        self.assertIn("older: 2 not described (run /artifact-explorer:refresh older)", text)
        run(self.d, "window", "--widen", "30")
        self.assertIn("window: 60 days (+30): 3 rows", run(self.d, "status")[1])

    def test_describer_launch_queue_is_windowed(self):
        old(self.con, A, 5, desc_status="ok", description="done", desc_source="describer")
        self.con.commit()
        with mock.patch.object(describe.shutil, "which", return_value="/bin/claude"), \
                mock.patch.object(describe.common, "allow_rule_present", return_value=True), \
                mock.patch.object(describe.common, "detach") as det:
            describe.launch(self.d)
        det.assert_not_called()  # the only own pending row is older than the window

    def test_thumbs_only_in_window(self):
        import thumbs
        for aid in (A, B):
            f = self.write(aid + ".html", "<p>page</p>")
            db.upsert_artifact(self.con, aid, local_path=f, thumb_status="pending")
        self.con.commit()
        seen = []

        def fake(browser, src, out):
            seen.append(os.path.basename(src))
            open(out, "wb").write(b"png")
            return True
        with mock.patch.object(thumbs, "_shot", fake), mock.patch.object(thumbs, "find_browser", lambda: "b"), \
                mock.patch("build.build"):
            thumbs.run(self.d)
        self.assertEqual(seen, [A + ".html"])
        self.assertEqual(self.row(B)["thumb_status"], "pending")

    def test_session_start_count_is_windowed(self):
        import hook
        out = io.StringIO()
        with redirect_stdout(out):
            hook._start(self.d)
        self.assertIn("1 shared artifacts", out.getvalue())  # D (undated) is in, C (200 days) is not


TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "page", "template.html")


def payload(path):
    s = open(path, encoding="utf-8").read()
    a = s.index("const DATA = ") + len("const DATA = ")
    return json.JSONDecoder().raw_decode(s[a:])[0]


class PageTest(Base):
    def test_payload_has_window_and_older_flags(self):
        import build
        old(self.con, A, 5, title="new")
        old(self.con, B, 75, title="old")
        self.con.commit()
        p = payload(build.build(self.d, max_age=0))
        self.assertEqual(p["window"]["days"], 60)
        self.assertAlmostEqual(p["window"]["cutoff"], time.time() - 60 * DAY, delta=DAY)  # a day boundary
        self.assertEqual({r["id"]: r["older"] for r in p["rows"]}, {A: False, B: True})
        run(self.d, "window", "--widen", "30")
        p = payload(build.build(self.d, max_age=0))
        self.assertEqual((p["window"]["days"], {r["id"]: r["older"] for r in p["rows"]}[B]), (90, False))

    def test_template_has_older_group(self):
        tpl = open(TPL, encoding="utf-8").read()
        for s in ("older artifact", "Describe older", "/artifact-explorer:refresh older", "aria-expanded",
                  "navigator.clipboard", "#older"):
            self.assertTrue(s in tpl, s)


NODE = __import__("shutil").which("node")


@unittest.skipUnless(NODE, "node not installed")
class OlderGroupJsTest(unittest.TestCase):
    def run_js(self, body):
        import subprocess
        tpl = open(TPL, encoding="utf-8").read()
        a, b = tpl.index("/*OLD-START*/"), tpl.index("/*OLD-END*/")
        code = tpl[a:b] + "\n" + body
        return json.loads(subprocess.run([NODE, "-e", code], capture_output=True, text=True, check=True).stdout)

    def test_split_keeps_order_and_labels(self):
        out = self.run_js(
            'const l=[{id:"a",older:false},{id:"b",older:true},{id:"c"},{id:"d",older:true}];'
            'const s=splitOlder(l);'
            'console.log(JSON.stringify({recent:s.recent.map(r=>r.id),older:s.older.map(r=>r.id),'
            'one:olderLabel(1),many:olderLabel(46),days:windowNote({days:60})}))')
        self.assertEqual((out["recent"], out["older"]), (["a", "c"], ["b", "d"]))
        self.assertEqual((out["one"], out["many"]), ("1 older artifact", "46 older artifacts"))
        self.assertIn("60 days", out["days"])


if __name__ == "__main__":
    unittest.main()
