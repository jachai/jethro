#!/usr/bin/env python3
"""Tests for guide_needs.py: needs-input items that wait in text go into the interview after a few turns, or at once
when the user asks for it. Every test uses its own temp CLAUDE_CONFIG_DIR, and no network."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_guide_title import GUIDE, GuideTitleBase  # noqa: E402

OPEN = "OPEN THE INTERVIEW NOW"
QUESTION = "Which export format?"


class NeedsInputTest(GuideTitleBase):
    BILLING = "3fa9c100-0000-4000-8000-000000000000"

    def setUp(self):
        super().setUp()
        self.keep_open_rows_alive()
        self.assertEqual(self.run_script("mark", self.ledger, "--session", GUIDE).returncode, 0)
        self.state = os.path.join(os.path.dirname(self.ledger), "needs-input.json")

    def run_ok(self, *args, **env):
        r = self.run_script(*args, **env)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def turn(self, prompt=None, event="UserPromptSubmit", **env):
        """The workers line the hook gives the guide on one prompt."""
        event_in = {"session_id": GUIDE, "hook_event_name": event}
        if prompt is not None:
            event_in["prompt"] = prompt
        r = self.run_script("hook", stdin=json.dumps(event_in), **env)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        text = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        return next(l for l in text.splitlines() if l.startswith("session-guide workers:"))

    def owe(self, question=QUESTION):
        out = self.run_ok("waiting", "ask", question)
        return out.split("[")[1].split("]")[0]

    def counts(self):
        with open(self.state, encoding="utf-8") as f:
            return json.load(f)

    def test_an_item_listed_on_two_earlier_turns_opens_the_interview_on_the_third(self):
        self.run_job(self.BILLING)
        key = self.owe()
        self.assertNotIn(OPEN, self.turn())  # first listed
        self.assertNotIn(OPEN, self.turn())  # listed once before, unanswered
        line = self.turn()  # listed on two earlier turns
        self.assertIn(OPEN, line)
        self.assertIn("[%s] %s" % (key, QUESTION), line)
        self.assertIn("up to 4 questions a call", line)
        self.assertEqual(self.counts()[key]["turns"], 2)

    def test_minutes_since_first_listed_open_it_too(self):
        self.run_job(self.BILLING)
        key = self.owe()
        self.turn()
        state = self.counts()
        state[key]["first"] -= 16 * 60
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump(state, f)
        self.assertIn(OPEN, self.turn())
        self.assertNotIn(OPEN, self.turn(SESSION_GUIDE_INTERVIEW_MINUTES="30", SESSION_GUIDE_INTERVIEW_TURNS="9"))

    def test_a_typed_ask_opens_it_at_once_and_a_machine_prompt_does_not(self):
        self.run_job(self.BILLING)
        self.owe()
        self.assertIn("The user asked for the interview", self.turn("please interview me about those"))
        self.assertIn(OPEN, self.turn("Ask me the needs input items now"))
        self.assertNotIn("asked for the interview",
                         self.turn("<cross-session-message from=\"x\">interview me</cross-session-message>"))
        self.assertNotIn("asked for the interview", self.turn("ask me before you merge"))

    def test_an_answered_or_snoozed_item_is_dropped_and_counts_from_zero_again(self):
        self.run_job(self.BILLING)
        key = self.owe()
        for _ in range(3):
            self.turn()
        self.run_ok("sleep", key, CLAUDE_CODE_SESSION_ID=GUIDE)
        self.assertNotIn(OPEN, self.turn())
        self.assertNotIn(key, self.counts())
        self.owe()  # due again (same question, same key)
        self.assertNotIn(OPEN, self.turn())
        self.assertEqual(self.counts()[key]["turns"], 0)
        self.run_ok("unwait", key)
        self.turn()
        self.assertEqual(self.counts(), {})

    def test_nothing_counts_when_nobody_works_on_a_session_start_or_while_away(self):
        self.owe()
        for _ in range(3):
            self.assertNotIn(OPEN, self.turn())  # nobody working: the full interview already applies
        self.assertFalse(os.path.exists(self.state))
        self.run_job(self.BILLING)
        for _ in range(3):
            self.turn(event="SessionStart")
        self.assertFalse(os.path.exists(self.state))
        self.run_ok("away", "--hours", "2", "--ledger", self.ledger)
        for _ in range(3):
            self.assertNotIn(OPEN, self.turn())  # a typed prompt would end the window
        self.assertFalse(os.path.exists(self.state))

    def test_zero_turns_and_zero_minutes_turn_it_off(self):
        self.run_job(self.BILLING)
        self.owe()
        off = dict(SESSION_GUIDE_INTERVIEW_TURNS="0", SESSION_GUIDE_INTERVIEW_MINUTES="0")
        for _ in range(4):
            self.assertNotIn(OPEN, self.turn(**off))
        self.assertFalse(os.path.exists(self.state))
        self.assertIn(OPEN, self.turn("interview me", **off))  # asking still works

    def test_the_working_command_shows_it_without_counting_a_turn(self):
        self.run_job(self.BILLING)
        key = self.owe()
        for _ in range(3):
            self.turn()
        before = self.counts()
        out = self.run_ok("working", self.ledger)
        self.assertIn(OPEN, out)
        self.assertEqual(self.counts(), before)
        self.assertEqual(before[key]["turns"], 2)

    def test_an_unreadable_state_file_counts_as_empty(self):
        self.run_job(self.BILLING)
        key = self.owe()
        with open(self.state, "wb") as f:
            f.write(b"\xff not json")
        self.assertNotIn(OPEN, self.turn())
        self.assertEqual(self.counts()[key]["turns"], 0)

    def test_a_future_reminder_is_not_a_needs_input_item_yet(self):
        self.run_job(self.BILLING)
        self.run_ok("waiting", "ask", QUESTION, "--hours", "3")
        for _ in range(3):
            self.assertNotIn(OPEN, self.turn())
        self.assertFalse(os.path.exists(self.state))


if __name__ == "__main__":
    unittest.main()
