import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import ae  # noqa: E402
import db  # noqa: E402


def run(d, *args):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = ae.main(["--data", d] + list(args))
    return rc, out.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        con = db.connect(self.d)
        db.upsert_artifact(con, "aaaaaaaaaa", url="https://claude.ai/artifact/aaaaaaaaaa", title="A", owned=1,
                           desc_status="pending", thumb_status="ok")
        db.upsert_artifact(con, "bbbbbbbbbb", title="B", owned=0, desc_status="pending", thumb_status="pending")
        db.upsert_artifact(con, "cccccccccc", title="C", desc_status="pending", thumb_status="none")
        con.commit()

    def rows(self, *a):
        return json.loads(run(self.d, "rows", "--json", *a)[1])

    def test_rows(self):
        self.assertEqual(len(self.rows()), 3)
        r = self.rows("--owned")
        self.assertEqual([x["id"] for x in r], ["aaaaaaaaaa"])
        self.assertEqual(sorted(r[0]), sorted("id url title owned thumb_status desc_status modified local_path".split()))
        self.assertEqual([x["id"] for x in self.rows("--thumb-status", "pending")], ["bbbbbbbbbb"])
        self.assertEqual(len(self.rows("--desc-status", "pending", "--limit", "2")), 2)

    def test_pending_owned_only_excludes_unknown(self):
        out = json.loads(run(self.d, "pending", "--owned-only", "--json")[1])
        self.assertEqual([x["id"] for x in out], ["aaaaaaaaaa"])

    def test_set_desc_file(self):
        p = os.path.join(self.d, "t.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("  " + "é" * 300 + "\n")
        self.assertEqual(run(self.d, "set-desc", "aaaaaaaaaa", "--file", p)[0], 0)
        row = db.get(db.connect(self.d), "aaaaaaaaaa")
        self.assertEqual(row["description"], "é" * 200)
        with self.assertRaises(SystemExit):
            ae.main(["--data", self.d, "set-desc", "aaaaaaaaaa", "positional text"])

    def test_set_sharing_file(self):
        p = os.path.join(self.d, "s.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("  anyone with the link\n  can view $(x)\n")
        self.assertEqual(run(self.d, "set-sharing", "aaaaaaaaaa", "--file", p)[0], 0)
        self.assertEqual(db.get(db.connect(self.d), "aaaaaaaaaa")["sharing"], "anyone with the link can view $(x)")
        with self.assertRaises(SystemExit):
            ae.main(["--data", self.d, "set-sharing", "aaaaaaaaaa", "private"])

    def test_excerpt_out(self):
        src, out = os.path.join(self.d, "a.html"), os.path.join(self.d, "x.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("<h1>Plan</h1><script>no</script><p>two</p>")
        rc, printed = run(self.d, "excerpt", src, "--out", out)[:2]
        self.assertEqual(rc, 0)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(f.read(), "Plan two")
        self.assertNotIn("Plan", printed)


if __name__ == "__main__":
    unittest.main()
