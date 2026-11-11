"""0.1.2: one describer at a time, typed rows skipped, a describer that never waits on input, a cap never overshot."""
import json
import os
import re
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import build  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402

U = "https://claude.ai/artifact/"
A, B, C = "AAAAAAAAAAAA", "BBBBBBBBBBBB", "CCCCCCCCCCCC"


class Base(unittest.TestCase):
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
            json.dump([{"url": U + x, "title": x, "scope": "mine"} for x in (A, B, C)], fh)
        describe.ingest_list(self.d, f)
        for k, v in (("which", mock.patch("shutil.which", return_value="/bin/claude")),
                     ("det", mock.patch.object(common, "detach", return_value=4242)),
                     ("alive", mock.patch.object(common, "_pid_alive", return_value=True))):
            setattr(self, k, v.start())
            self.addCleanup(v.stop)

    def con(self):
        return db.connect(self.d)

    def next_tick(self):
        """The watch interval has passed (the old gate alone would launch again)."""
        con = self.con()
        db.state_set(con, "describer_last", time.time() - 3600)
        con.commit()

    def log(self):
        p = os.path.join(self.d, "watch.log")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


class SingleFlight(Base):
    def test_no_second_launch_while_one_runs(self):
        for _ in range(3):
            describe.launch(self.d)
            self.next_tick()
        self.assertEqual(self.det.call_count, 1)
        rec = json.load(open(os.path.join(self.d, "describer.json")))
        self.assertEqual(rec["pid"], 4242)
        self.assertIn("still running", self.log())

    def test_launch_again_once_it_ended(self):
        describe.launch(self.d)
        self.next_tick()
        self.alive.return_value = False
        describe.launch(self.d)
        self.assertEqual(self.det.call_count, 2)

    def test_max_age(self):
        describe.launch(self.d)
        self.next_tick()
        path = os.path.join(self.d, "describer.json")
        rec = json.load(open(path))
        rec["t"] -= describe.MAX_AGE + 1
        json.dump(rec, open(path, "w"))
        describe.launch(self.d)  # pid still "alive" but older than the max age: not trusted
        self.assertEqual(self.det.call_count, 2)
        self.assertIn("older than", self.log())


class SkipTyped(Base):
    def save(self, text):
        p = os.path.join(self.d, "page.html")
        with open(p, "w") as f:
            f.write("<html><body>%s</body></html>" % text)
        return p

    def test_shell_and_typed_rows_skipped(self):
        out = os.path.join(self.d, "excerpt.txt")
        long = "Quarterly plan for the monitor fixes with owners, dates and the open questions for ops. " * 2
        self.assertTrue(describe.excerpt_for(self.d, self.save("Claude Docs"), out, A, None)[1])
        self.assertTrue(describe.excerpt_for(self.d, self.save(long), out, B, "Slides")[1])
        text, skipped = describe.excerpt_for(self.d, self.save(long), out, C, "HTML")
        self.assertFalse(skipped)
        self.assertEqual(open(out).read(), text)
        con = self.con()
        a, b = db.get(con, A), db.get(con, B)
        self.assertEqual((a["desc_status"], a["desc_note"]), ("skipped", "no text: under 50 characters"))
        self.assertEqual((b["desc_status"], b["desc_note"], b["kind"]), ("skipped", "no text: typed artifact", "Slides"))
        self.assertEqual([r["id"] for r in describe.pending_rows(con, True)], [C])
        with mock.patch("builtins.print") as pr:
            describe.status(self.d, as_json=True)
        s = json.loads(pr.call_args[0][0])
        self.assertEqual((s["pending_descriptions"], s["skipped_descriptions"]), (1, 2))
        f = os.path.join(self.d, "list.json")  # a later list refresh never puts them back in the queue
        describe.ingest_list(self.d, f)
        self.assertEqual([r["id"] for r in describe.pending_rows(self.con(), True)], [C])
        rows = {r["id"]: r for r in build.collect(self.d, {})[0]}
        self.assertEqual((rows[B]["skipped"], rows[B]["pending"]), ("no text: typed artifact", False))
        tpl = open(os.path.join(common.ROOT, "page", "template.html"), encoding="utf-8").read()
        self.assertIn("no description (typed)", tpl)

    def test_cli_excerpt_skip(self):
        import ae
        out = os.path.join(self.d, "excerpt.txt")
        with mock.patch("builtins.print") as pr:
            ae.main(["--data", self.d, "excerpt", self.save("Slides"), "--out", out, "--id", A, "--type", "Slides"])
        self.assertTrue(pr.call_args[0][0].startswith("skipped"))
        self.assertEqual(db.get(self.con(), A)["desc_status"], "skipped")

    def test_describable_rows_first(self):
        con = self.con()
        db.upsert_artifact(con, A, kind="Docs", modified=time.time())  # newest, but a typed shell
        db.upsert_artifact(con, B, modified=time.time() - 10)
        con.commit()
        self.assertEqual([r["id"] for r in describe.pending_rows(con, True)][-1], A)


class NeverWaits(Base):
    def skill_tools(self):
        txt = open(os.path.join(common.ROOT, "skills", "refresh", "SKILL.md"), encoding="utf-8").read()
        return re.search(r"^allowed-tools:\s*(.+)$", txt, re.M).group(1).strip(), txt

    def test_print_mode_no_prompts(self):
        describe.launch(self.d)
        argv, kw = self.det.call_args[0][0], self.det.call_args[1]
        self.assertIn("-p", argv)
        self.assertNotIn("--bg", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        tools, _ = self.skill_tools()
        self.assertEqual(argv[argv.index("--allowedTools") + 1], tools)
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(float(argv[argv.index("--max-budget-usd") + 1]), describe.RUN_BUDGET)
        self.assertEqual(kw["out"], os.path.join(self.d, "describer.out"))

    def test_skill_runs_describer_in_foreground_and_stops_on_refusal(self):
        _, txt = self.skill_tools()
        bg = txt.split("## Background mode", 1)[1].split("## Full mode", 1)[0]
        self.assertIn("run_in_background", bg)
        self.assertIn("refused", bg)
        self.assertIn("--id", bg)

    def test_result_logged(self):
        describe.launch(self.d)
        with open(os.path.join(self.d, "describer.out"), "w") as f:
            json.dump({"type": "result", "result": "stopped: Bash refused", "total_cost_usd": 0.04,
                       "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "ls"}}]}, f)
        self.alive.return_value = False
        describe.launch(self.d)
        self.assertIn("describer finished: stopped: Bash refused ($0.04); refused: Bash", self.log())


class Cap(Base):
    def test_cap_never_overshot(self):
        con = self.con()
        db.add_spend(con, 1.0 - describe.RUN_BUDGET + 0.01)
        con.commit()
        describe.launch(self.d)
        self.assertFalse(self.det.called)
        self.assertIn("cap", self.log())

    def test_worst_case_booked_then_corrected(self):
        con = self.con()
        db.add_spend(con, 1.0 - describe.RUN_BUDGET)
        con.commit()
        describe.launch(self.d)
        self.assertEqual(self.det.call_count, 1)
        self.assertAlmostEqual(db.spend_today(self.con()), 1.0)
        with open(os.path.join(self.d, "describer.out"), "w") as f:
            json.dump({"result": "described 2 of 3", "total_cost_usd": 0.05}, f)
        self.alive.return_value = False
        describe.launch(self.d)  # reconciles; 0.80 + 0.25 > 1.0 so no new run
        self.assertAlmostEqual(db.spend_today(self.con()), 1.0 - describe.RUN_BUDGET + 0.05)
        self.assertEqual(self.det.call_count, 1)

    def test_unreadable_result_keeps_worst_case(self):
        describe.launch(self.d)
        self.alive.return_value = False
        self.next_tick()
        describe.launch(self.d)
        self.assertAlmostEqual(db.spend_today(self.con()), 2 * describe.RUN_BUDGET)


if __name__ == "__main__":
    unittest.main()
