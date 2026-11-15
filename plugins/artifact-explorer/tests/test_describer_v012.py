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
REAL_PID_ALIVE = common._pid_alive


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

    def test_shell_rows_skipped_typed_source_described(self):
        out = os.path.join(self.d, "excerpt.txt")
        long = "Quarterly plan for the monitor fixes with owners, dates and the open questions for ops. " * 2
        self.assertTrue(describe.excerpt_for(self.d, self.save("Claude Docs"), out, A, None)[1])
        # 0.1.4: a typed artifact's own source (deck.json, Docs lead) is described, not skipped
        self.assertFalse(describe.excerpt_for(self.d, self.save(long), out, B, "Slides")[1])
        text, skipped = describe.excerpt_for(self.d, self.save(long), out, C, "HTML")
        self.assertFalse(skipped)
        self.assertEqual(open(out).read(), text)
        con = self.con()
        a, b, c = db.get(con, A), db.get(con, B), db.get(con, C)
        self.assertEqual((a["desc_status"], a["desc_note"]), ("skipped", "no text: under 50 characters"))
        self.assertEqual((b["kind"], c["kind"]), ("Slides", "Page"))
        self.assertEqual(sorted(r["id"] for r in describe.pending_rows(con, True)), [B, C])
        with mock.patch("builtins.print") as pr:
            describe.status(self.d, as_json=True)
        s = json.loads(pr.call_args[0][0])
        self.assertEqual((s["pending_descriptions"], s["skipped_descriptions"]), (2, 1))
        f = os.path.join(self.d, "list.json")  # a later list refresh never puts a skipped row back in the queue
        describe.ingest_list(self.d, f)
        self.assertEqual(sorted(r["id"] for r in describe.pending_rows(self.con(), True)), [B, C])
        rows = {r["id"]: r for r in build.collect(self.d, {})[0]}
        self.assertEqual((rows[A]["skipped"], rows[A]["pending"]), ("no text: under 50 characters", False))

    def test_cli_excerpt_skip(self):
        import ae
        out = os.path.join(self.d, "excerpt.txt")
        with mock.patch("builtins.print") as pr:
            ae.main(["--data", self.d, "excerpt", self.save("Slides"), "--out", out, "--id", A, "--type", "Slides"])
        self.assertTrue(pr.call_args[0][0].startswith("skipped"))
        # 0.1.4: a typed row whose source has no text shows its title (no-source) so `retry` can try again
        self.assertEqual(db.get(self.con(), A)["desc_status"], "no-source")

    def test_typed_rows_are_not_queued_last(self):
        con = self.con()
        db.upsert_artifact(con, A, kind="Docs", modified=time.time())  # newest; 0.1.4 describes typed rows from their source
        db.upsert_artifact(con, B, modified=time.time() - 10)
        con.commit()
        self.assertEqual([r["id"] for r in describe.pending_rows(con, True)][0], A)


class ReviewFixes(Base):
    def test_unknown_id_creates_no_row(self):
        p = os.path.join(self.d, "page.html")
        open(p, "w").write("<p>Slides</p>")
        describe.excerpt_for(self.d, p, os.path.join(self.d, "x.txt"), "ZZZZZZZZZZZZ", "Slides")
        self.assertIsNone(db.get(self.con(), "ZZZZZZZZZZZZ"))

    def test_launch_lock(self):
        with common.Lock(os.path.join(self.d, "describer.lock"), 120):
            describe.launch(self.d)  # another launch decision is in progress
        self.assertFalse(self.det.called)

    def test_ended_child_is_reaped(self):
        if os.name == "nt":
            self.skipTest("POSIX zombies")
        pid = os.fork()  # a child nobody reaps: a zombie for sure (a dropped Popen may get reaped by others)
        if pid == 0:
            os._exit(0)
        time.sleep(0.3)
        self.assertTrue(REAL_PID_ALIVE(pid))  # unreaped zombie: kill(pid, 0) still succeeds
        json.dump({"pid": pid, "t": time.time(), "day": db.today(), "booked": 0.25},
                  open(os.path.join(self.d, "describer.json"), "w"))
        with mock.patch.object(common, "_pid_alive", REAL_PID_ALIVE):
            self.assertFalse(describe._running(self.d, self.con()))

    def test_column_race(self):
        con = self.con()  # the column exists: a second ALTER (another process won the race) must not raise
        db._add_desc_note(con)
        self.assertIn("desc_note", {r[1] for r in con.execute("PRAGMA table_info(artifacts)")})


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
        self.assertEqual(argv[argv.index("--allowedTools") + 1], tools + ", " + describe.AE_TOOL)  # 0.1.5
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertLess(float(argv[argv.index("--max-budget-usd") + 1]), describe.RUN_BUDGET)
        self.assertEqual(kw["out"], os.path.join(self.d, "describer.out"))

    def test_skill_runs_describer_in_foreground_and_stops_on_refusal(self):
        _, txt = self.skill_tools()
        bg = txt.split("## Background mode", 1)[1].split("## Full mode", 1)[0]
        one = txt.split("## Describe one row", 1)[1].split("## Background mode", 1)[0]  # 0.1.4: shared by both modes
        self.assertIn("Describe one row", bg)
        self.assertIn("run_in_background: false", one)
        self.assertIn("refused", bg)
        self.assertIn("--id", one)

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

    def test_unreadable_result_releases_booking(self):
        """0.1.5: a run that ends without a cost report gives its booking back (0.1.4 kept it: runs that never
        reported ate the $1.00 cap); the next run is booked as usual."""
        describe.launch(self.d)
        self.alive.return_value = False
        self.next_tick()
        describe.launch(self.d)
        self.assertEqual(self.det.call_count, 2)
        self.assertAlmostEqual(db.spend_today(self.con()), describe.RUN_BUDGET)
        self.assertIn("released the $0.25 booked", self.log())


if __name__ == "__main__":
    unittest.main()
