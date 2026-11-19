"""0.2.4: the background run gets the Artifact tool (env), recat comes first, and rows it cannot read are marked
'needs interactive refresh' (described from a local source when there is one) instead of relaunching forever."""
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
import common  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402
import hook  # noqa: E402

U = "https://claude.ai/artifact/"
A, B = "AAAAAAAAAAAA", "BBBBBBBBBBBB"


class V024Test(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        cfgdir = helpers.tmp()
        with open(os.path.join(cfgdir, "settings.json"), "w") as f:
            json.dump({"permissions": {"allow": [common.ALLOW_RULE]}}, f)
        p = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfgdir})
        p.start()
        self.addCleanup(p.stop)
        f = os.path.join(self.d, "list.json")
        with open(f, "w") as fh:
            json.dump([{"url": U + A, "title": "Local one", "scope": "mine"},
                       {"url": U + B, "title": "Remote only", "scope": "mine"}], fh)
        describe.ingest_list(self.d, f)
        self.html = os.path.join(self.d, "page.html")
        with open(self.html, "w") as fh:
            fh.write("<html><body><h1>Quarterly plan</h1><p>%s</p></body></html>" % ("Budget and hiring notes. " * 20))
        con = db.connect(self.d)
        db.upsert_artifact(con, A, local_path=self.html)
        con.commit()
        con.close()

    def out(self, fn, *a, **k):
        buf = io.StringIO()
        with redirect_stdout(buf):
            fn(*a, **k)
        return buf.getvalue()

    def test_launch_sets_artifact_env(self):
        with mock.patch("shutil.which", return_value="/bin/claude"), \
                mock.patch.object(common, "detach", return_value=4242) as det, \
                mock.patch.object(common, "_pid_alive", return_value=False):
            describe.launch(self.d)
        self.assertEqual(det.call_args[1]["env"], {"CLAUDE_CODE_ARTIFACT": "1"})

    def test_detach_env_adds_to_environment(self):
        out = os.path.join(self.d, "env.out")
        common.detach([sys.executable, "-c", "import os;print(os.environ.get('CLAUDE_CODE_ARTIFACT'),"
                             "bool(os.environ.get('PATH')))"], out=out, env={"CLAUDE_CODE_ARTIFACT": "1"})
        deadline = time.time() + 20  # a detached child: no portable wait, so poll for its output
        while time.time() < deadline and len(open(out).read().split()) < 2:
            time.sleep(0.1)
        self.assertEqual(open(out).read().split(), ["1", "True"])

    def test_batch_local_excerpts_local_and_marks_rest(self):
        text = self.out(describe.batch_local, self.d, 20)
        self.assertIn("marked needs interactive refresh: 1", text)
        self.assertIn("items: 1", text)
        folder = text.splitlines()[0]
        self.assertTrue(os.path.getsize(os.path.join(folder, A + ".txt")) > 0)
        con = db.connect(self.d)
        self.assertEqual(db.get(con, B)["desc_note"], describe.NEEDS_INTERACTIVE)
        self.assertEqual(db.get(con, B)["desc_status"], "pending")
        # the background view and the watcher no longer see B; the in-session view still does
        self.assertEqual([r["id"] for r in describe.pending_rows(con, True)], [A])
        self.assertIn(B, [r["id"] for r in describe.pending_rows(con, False)])
        self.assertEqual(describe.needs_interactive_count(con), 1)

    def test_watcher_does_not_relaunch_for_marked_rows(self):
        for aid in (A, B):
            describe.set_needs_interactive(self.d, aid)
        with mock.patch("shutil.which", return_value="/bin/claude"), \
                mock.patch.object(common, "detach", return_value=4242) as det:
            describe.launch(self.d)
        self.assertFalse(det.called)

    def test_description_clears_mark(self):
        describe.set_needs_interactive(self.d, B)
        res = os.path.join(self.d, "r.jsonl")
        with open(res, "w") as f:
            f.write(json.dumps({"id": B, "description": "A remote page.", "category": "x"}) + "\n")
        self.out(describe.batch_save, self.d, res)
        con = db.connect(self.d)
        self.assertIsNone(db.get(con, B)["desc_note"])
        self.assertEqual(db.get(con, B)["desc_status"], "ok")

    def test_mark_never_touches_described_rows(self):
        p = os.path.join(self.d, "s.txt")
        with open(p, "w") as f:
            f.write("Done already.")
        describe.set_desc(self.d, B, open(p).read())
        describe.set_needs_interactive(self.d, B)
        self.assertIsNone(db.get(db.connect(self.d), B)["desc_note"])

    def test_session_start_mentions_needs_interactive(self):
        describe.set_needs_interactive(self.d, B)
        text = self.out(hook._start, self.d)
        ctx = json.loads(text)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("1 of yours the background describer could not read", ctx)

    def test_status_line(self):
        describe.set_needs_interactive(self.d, B)
        self.assertIn("needs interactive refresh: 1", self.out(describe.status, self.d))

    def test_skill_recat_before_describe_and_fallback(self):
        txt = open(os.path.join(common.ROOT, "skills", "refresh", "SKILL.md"), encoding="utf-8").read()
        bg = txt[txt.index("## Background mode"):txt.index("## Full mode")]
        self.assertLess(bg.index("batch recat --owned-only"), bg.index("pending --owned-only"))
        self.assertIn("AE batch local", bg)
        self.assertIn("--needs-interactive", bg)


if __name__ == "__main__":
    unittest.main()
