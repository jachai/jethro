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


if __name__ == "__main__":
    unittest.main()
