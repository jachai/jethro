"""0.2.7: batches of 8 saved before the next, Docs from the outline only, parallel reads, describe-only N,
`launch-describer --rows N`, pending_at_launch / saved rows, back-off after 0 saved / ceiling / over stop-loss."""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import common  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402
from test_describer_v012 import Base, A, B, C, U  # noqa: E402
from test_v026 import write_out  # noqa: E402

SKILL = os.path.join(common.ROOT, "skills", "refresh", "SKILL.md")


class SkillText(unittest.TestCase):
    def setUp(self):
        self.txt = open(SKILL, encoding="utf-8").read()

    def test_batches_of_8(self):
        self.assertIn("batches of at most 8", self.txt)
        self.assertIn("AE batch recat --owned-only --limit 8", self.txt)
        self.assertIn("AE batch local --limit 8", self.txt)
        self.assertIn("AE batch recat --limit 8", self.txt)
        self.assertNotIn("--limit 20", self.txt)
        self.assertNotIn("batches of 20", self.txt)
        self.assertIn("up to 8 items", open(os.path.join(common.ROOT, "agents", "describer.md"), encoding="utf-8").read())

    def test_save_before_next_batch(self):
        self.assertIn("never prepares a second batch before the first is saved", self.txt)
        self.assertIn("stop after the save when the budget is low", self.txt)
        self.assertNotIn("build up to 3 batches", self.txt)

    def test_docs_outline_only(self):
        self.assertIn("Do not read the lead paragraph", self.txt)
        self.assertNotIn('"kind":"view"', self.txt)
        self.assertIn('"projection":"outline"', self.txt)

    def test_parallel_reads(self):
        self.assertIn("in parallel", self.txt)
        self.assertIn("ONE turn", self.txt)
        self.assertIn("all the Artifact `read` calls of the batch", self.txt)
        self.assertIn("Never chain commands", self.txt)
        self.assertIn("Never set or use shell variables", self.txt)

    def test_describe_only_n(self):
        self.assertIn("`describe-only N` (N from 1 to 60)", self.txt)
        self.assertIn("`describe-only 1` is setup's test run", self.txt)
        self.assertIn("at most 60 rows", self.txt)
        self.assertIn("--limit N", self.txt)


class Rows(Base):
    def test_rows_argv_and_ignores_backoff(self):
        con = self.con()
        db.state_set(con, "describer_backoff", {"until": 9e12, "tool": "x"})
        con.commit()
        describe.launch(self.d)
        self.assertEqual(self.det.call_count, 0)
        with redirect_stdout(io.StringIO()) as out:
            describe.launch(self.d, rows=5)
        self.assertEqual(self.det.call_count, 1)
        self.assertEqual(self.det.call_args[0][0][-1], describe.RUN_MARK + " 5")
        self.assertIn("5 rows", out.getvalue())

    def test_test_is_one_row(self):
        with redirect_stdout(io.StringIO()):
            describe.launch(self.d, test=True)
        self.assertEqual(self.det.call_args[0][0][-1], describe.RUN_MARK + " 1")

    def test_plain_launch_is_plain(self):
        describe.launch(self.d)
        self.assertEqual(self.det.call_args[0][0][-1], describe.RUN_MARK)

    def test_cli_flag(self):
        import ae
        with mock.patch.object(describe, "launch", return_value=0) as m:
            ae.main(["--data", self.d, "launch-describer", "--rows", "7"])
        self.assertEqual(m.call_args[1]["rows"], 7)


class Saved(Base):
    def run_ended(self, cost, result="described", mark_described=0):
        describe.launch(self.d)
        con = self.con()
        for aid in (A, B, C)[:mark_described]:
            db.upsert_artifact(con, aid, description="d", desc_status="done")
        con.commit()
        self.alive.return_value = False
        write_out(self.d, result, cost=cost)
        self.next_tick()
        describe.launch(self.d)
        self.det.reset_mock()

    def test_pending_at_launch_recorded(self):
        describe.launch(self.d)
        rec = json.load(open(os.path.join(self.d, "describer.json")))
        self.assertEqual(rec["pending_at_launch"], 3)

    def test_saved_in_logs(self):
        self.run_ended(0.01, mark_described=2)
        self.assertIn("saved 2, $0.0050 per saved row", self.log())
        self.assertIn("saved 2, $0.0050 per saved row", open(os.path.join(self.d, "describer.log")).read())

    def test_saved_never_negative(self):
        self.run_ended(0.01, mark_described=0)
        self.assertIn("saved 0", self.log())


class BackOffV027(Base):
    def run_ended(self, cost, mark_described=0, result="described 3"):
        Saved.run_ended(self, cost, result, mark_described)

    def blocked(self):
        self.next_tick()
        describe.launch(self.d)
        return self.det.call_count == 0

    def test_zero_saved(self):
        self.run_ended(0.03)
        self.assertIn("describer back-off: last run saved 0 rows", self.log())
        self.assertTrue(self.blocked())

    def test_ceiling(self):
        self.run_ended(0.14, mark_described=3)
        self.assertIn("at the $0.15 ceiling", self.log())
        self.assertTrue(self.blocked())

    def test_over_stop_loss(self):
        self.run_ended(0.06, mark_described=3)  # 0.02 per row
        self.assertIn("per saved row, over $0.0100", self.log())
        self.assertTrue(self.blocked())

    def test_under_stop_loss_no_backoff(self):
        self.run_ended(0.02, mark_described=3)  # 0.0067 per row
        self.assertNotIn("back-off", self.log())
        self.assertFalse(self.blocked())

    def test_refusal_kept(self):
        self.run_ended(0.01, mark_described=3, result="stopped: refused Bash")
        self.assertIn("last run refused Bash", self.log())
        self.assertTrue(self.blocked())

    def test_no_cost_report_unchanged(self):
        describe.launch(self.d)
        self.alive.return_value = False
        self.next_tick()
        describe.launch(self.d)
        self.assertNotIn("back-off", self.log())

    def test_rows_ignores_backoff(self):
        self.run_ended(0.03)
        with redirect_stdout(io.StringIO()):
            describe.launch(self.d, rows=2)
        self.assertEqual(self.det.call_count, 1)

    def test_stop_loss_option_default(self):
        self.assertEqual(common.options()["describe_stop_loss"], describe.STOP_LOSS_PER_ROW)


if __name__ == "__main__":
    unittest.main()
