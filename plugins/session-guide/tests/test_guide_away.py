#!/usr/bin/env python3
"""Tests for guide_away.py: away mode, its ledger block and Decisions, and the hook's lines and title. Every test uses
its own temp CLAUDE_CONFIG_DIR, and no network."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "session-guide", "scripts")
SCRIPT = os.path.join(SCRIPTS, "guide_title.py")
sys.path.insert(0, SCRIPTS)
import guide_away as ga  # noqa: E402
import guide_title as gt  # noqa: E402

GUIDE = "c0ffee12-3456-4789-8abc-def012345678"
LEDGER = """# release — guide ledger
Guide: 'release guide' [c0ffee12] since 10-27 09:00

## Sessions
| Title [id6] | Level | Role / stream | Worktree @ sha | Address | Ctx | Last seen |
|---|---|---|---|---|---|---|

## Decisions (FINAL unless struck)
1. (10-26 10:10, user in guide) Test battery: only NEW failures block a prod merge.
   Example: 3 old failures, 0 new: merge.

## Waiting on the user
| Session [id6] | What the user needs to do | Asked | Remind at |
|---|---|---|---|

## Open items
| Item | Next action | Owner | Status |
|---|---|---|---|
"""


class Case(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="guide-away-")
        self.addCleanup(shutil.rmtree, self.cfg)
        self.ledger = os.path.join(self.cfg, "session-guide", "release", "ledger.md")
        os.makedirs(os.path.dirname(self.ledger))
        with open(self.ledger, "w", encoding="utf-8") as f:
            f.write(LEDGER)
        guides = os.path.join(self.cfg, "session-guide", "guides")
        os.makedirs(guides)
        with open(os.path.join(guides, GUIDE), "w") as f:
            f.write(self.ledger + "\n")
        patch = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.cfg, "SESSION_GUIDE_GH": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        for name in [n for n in os.environ if n.startswith("SESSION_GUIDE_") and n != "SESSION_GUIDE_GH"] + [
                "CLAUDE_CODE_SESSION_ID"]:
            os.environ.pop(name, None)

    def text(self):
        with open(self.ledger, encoding="utf-8") as f:
            return f.read()

    def run_script(self, *args, stdin="", **extra_env):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SESSION_GUIDE_")}
        env.update(CLAUDE_CONFIG_DIR=self.cfg, HOME=self.cfg, SESSION_GUIDE_GH="0", SESSION_GUIDE_FINISHED_HOURS="0")
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        env.update(extra_env)
        return subprocess.run([sys.executable, SCRIPT] + list(args), input=stdin, capture_output=True, text=True,
                              env=env)

    def away(self, *args, **extra_env):
        r = self.run_script("away", *(list(args) + ["--ledger", self.ledger]), **extra_env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def hook(self, prompt="", event="UserPromptSubmit", **extra_env):
        """(title, additionalContext) the hook gives the guide on this prompt."""
        r = self.run_script("hook", stdin=json.dumps({"session_id": GUIDE, "hook_event_name": event,
                                                      "prompt": prompt}), **extra_env)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        out = json.loads(r.stdout)["hookSpecificOutput"]
        return out.get("sessionTitle"), out.get("additionalContext", "")

    def state(self):
        return ga.read(self.ledger)

    def set_state(self, **kw):
        state = self.state()
        state.update(kw)
        ga.save(self.ledger, state)


class StartAndEnd(Case):
    def test_start_writes_the_state_and_the_block(self):
        self.away("--hours", "8")
        state = self.state()
        self.assertTrue(ga.away_now(state))
        self.assertAlmostEqual(state["until"] - state["since"], 8 * 3600, delta=5)
        text = self.text()
        self.assertIn("## AWAY MODE (away since", text)
        self.assertIn(ga.DECIDED, text)
        self.assertIn(ga.HELD, text)
        self.assertLess(text.index("## AWAY MODE"), text.index("## Sessions"))
        self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(self.ledger), "away.json")))

    def test_until_and_moving_the_window_keep_the_start(self):
        until = time.strftime(gt.TIME_FORMAT, time.localtime(time.time() + 3 * 3600))
        self.away("--until", until)
        since = self.state()["since"]
        out = self.away("--hours", "5")
        self.assertIn("moved", out)
        self.assertEqual(self.state()["since"], since)
        self.assertAlmostEqual(self.state()["until"], time.time() + 5 * 3600, delta=5)

    def test_bad_starts_are_refused(self):
        for args in ((), ("--hours", "0"), ("--until", "tomorrow"), ("--until", "2020-01-01 10:00"),
                     ("--hours", "2", "--until", "2099-01-01 10:00"), ("end", "--hours", "2")):
            r = self.run_script("away", *(list(args) + ["--ledger", self.ledger]))
            self.assertNotEqual(r.returncode, 0, args)
        self.assertFalse(ga.away_now(self.state()))

    def test_end_and_status(self):
        self.assertIn("not away", self.away("status"))
        self.assertIn("not away", self.away("end"))
        self.away("--hours", "2")
        self.assertIn("away since", self.away("status"))
        self.assertIn("back:", self.away("end"))
        state = self.state()
        self.assertEqual(state["ended_by"], "end")
        self.assertIn("back since", self.away("status"))
        self.assertNotIn("## AWAY MODE", self.text())  # no rows: nothing to review, so no block


class DecideAndHold(Case):
    def setUp(self):
        super().setUp()
        self.away("--hours", "8")

    def test_decide_writes_a_row_and_an_auto_decision(self):
        out = self.away("decide", "model for the spike", "sonnet/medium", "--reverse", "relaunch it on opus")
        self.assertIn("away #1 decided, Decision 2", out)
        text = self.text()
        self.assertIn("| 1 | ", text)
        self.assertIn("| model for the spike | sonnet/medium | relaunch it on opus (Decision 2) |", text)
        lines = text.splitlines()
        at = lines.index("   Example: 3 old failures, 0 new: merge.")
        self.assertRegex(lines[at + 1], r"^2\. \(\d\d-\d\d \d\d:\d\d, auto: user away\) model for the spike: "
                                        r"sonnet/medium\. To reverse: relaunch it on opus \(away #1\)$")
        self.assertEqual(lines[at + 2], "")

    def test_decide_needs_how_to_reverse_and_twice_is_once(self):
        r = self.run_script("away", "decide", "x", "y", "--ledger", self.ledger)
        self.assertNotEqual(r.returncode, 0)
        self.away("decide", "x", "y", "--reverse", "z")
        self.assertIn("already decided as #1", self.away("decide", "X ", "other", "--reverse", "z"))
        self.assertEqual(len(self.state()["decided"]), 1)

    def test_hold_writes_a_waiting_row_and_a_later_decide_settles_it(self):
        self.assertIn("away #1 held", self.away("hold", "merge #12", "merges are held", "gh pr merge 12"))
        self.assertIn("away #1 updated", self.away("hold", "merge #12", "still held", "gh pr merge 12 --squash"))
        self.assertIn("| 1 | ", self.text())
        self.assertIn("| merge #12 | still held | gh pr merge 12 --squash |", self.text())
        self.away("decide", "merge #12", "wait for CI", "--reverse", "merge it")
        self.assertTrue(self.state()["held"][0]["done"])
        self.assertIn("~~merge #12~~ done", self.text())

    def test_reverse_strikes_the_auto_decision(self):
        self.away("decide", "model for the spike", "sonnet/medium", "--reverse", "relaunch it on opus")
        out = self.away("reverse", "1", "--note", "user wants opus")
        self.assertIn("Decision 3 strikes Decision 2. Now do it: relaunch it on opus", out)
        text = self.text()
        self.assertRegex(text, r"\n2\. ~~\(.*auto: user away\) model for the spike: .*\(away #1\)~~ reversed by 3\n")
        self.assertRegex(text, r"\n3\. \(.*, user on return\) Reverse away #1 \(Decision 2, model for the spike\): "
                               r"relaunch it on opus; user wants opus\n")
        self.assertIn("~~model for the spike~~ reversed by Decision 3", text)
        self.away("reverse", "1")  # twice changes nothing
        self.assertEqual(text, self.text())
        r = self.run_script("away", "reverse", "7", "--ledger", self.ledger)
        self.assertIn("no decided row #7", r.stderr)

    def test_clear_moves_open_held_rows_to_waiting_ask(self):
        self.away("decide", "a", "b", "--reverse", "c")
        self.away("hold", "merge #12", "merges are held", "gh pr merge 12")
        self.away("hold", "publish deck", "sharing is held", "publish it")
        self.away("done", "3")
        r = self.run_script("away", "clear", "--ledger", self.ledger)
        self.assertIn("still away", r.stderr)
        self.away("end")
        out = self.away("clear")
        self.assertIn("1 decided row(s) stay as Decisions, 1 waiting row(s) moved", out)
        text = self.text()
        self.assertNotIn("## AWAY MODE", text)
        self.assertIn("auto: user away) a: b.", text)
        owed = [r for r in gt.waiting_rows(self.ledger).values() if r["owed"]]
        self.assertEqual([r["what"] for r in owed], ["merge #12: gh pr merge 12"])
        self.assertEqual(self.state(), ga.empty())

    def test_decisions_section_is_added_when_missing(self):
        with open(self.ledger, "w") as f:
            f.write(LEDGER.replace("## Decisions (FINAL unless struck)\n1. (10-26 10:10, user in guide) Test "
                                   "battery: only NEW failures block a prod merge.\n   Example: 3 old failures, "
                                   "0 new: merge.\n\n", ""))
        self.assertIn("Decision 1", self.away("decide", "a", "b", "--reverse", "c"))
        self.assertRegex(self.text(), r"## Decisions \(FINAL unless struck\)\n1\. \(.*auto: user away\) a: b\. "
                                      r"To reverse: c \(away #1\)\n\n## Waiting on the user")


class Boundaries(Case):
    def test_decide_outside_a_window_is_refused(self):
        r = self.run_script("away", "decide", "a", "b", "--reverse", "c", "--ledger", self.ledger)
        self.assertIn("not away", r.stderr)
        self.away("--hours", "1")
        self.set_state(since=time.time() - 7200, until=time.time() - 60)  # the window has passed
        r = self.run_script("away", "decide", "a", "b", "--reverse", "c", "--ledger", self.ledger)
        self.assertIn("not away", r.stderr)
        r = self.run_script("away", "decide", "a", "b", "--reverse", "c", "--timed-out", "--ledger", self.ledger)
        self.assertIn("not away", r.stderr)  # --timed-out only with SESSION_GUIDE_AWAY_ASK_MINUTES on
        self.assertEqual(self.state()["decided"], [])
        self.assertNotIn("auto: user away", self.text())

    def test_a_ledger_that_is_not_utf8_is_never_rewritten(self):
        self.away("--hours", "1")
        with open(self.ledger, "ab") as f:
            f.write(b"\xff\xfe broken\n")
        before = open(self.ledger, "rb").read()
        state = open(ga.path_of(self.ledger), "rb").read()
        for args in (("decide", "a", "b", "--reverse", "c"), ("hold", "a", "b", "c"), ("end",), ("clear",)):
            r = self.run_script("away", *(list(args) + ["--ledger", self.ledger]))
            self.assertIn("isn't valid UTF-8", r.stderr, args)
        self.assertEqual(open(self.ledger, "rb").read(), before)
        self.assertEqual(open(ga.path_of(self.ledger), "rb").read(), state)
        moved = dict(self.state(), since=time.time() - 7200, until=time.time() - 60)
        with open(ga.path_of(self.ledger), "w") as f:  # the window has passed; the hook can't end it: it fails open
            json.dump(moved, f)
        title, _ = self.hook("Guide wake")
        self.assertIn("Sessions Manager", title)


class Hook(Case):
    def test_a_leaving_phrase_prints_the_command_and_enters_nothing(self):
        title, context = self.hook("ok, going to sleep, back in the morning")
        self.assertIn("session-guide away: the user's prompt says they are leaving", context)
        self.assertIn('away --until "', context)
        self.assertFalse(ga.away_now(self.state()))
        self.assertNotIn("\U0001f4a4", title)
        _, context = self.hook("afk for 2 hours")
        self.assertIn("away --hours 2", context)
        _, context = self.hook("I'm out of ideas, what next?")
        self.assertNotIn("session-guide away", context)

    def test_back_in_the_office_brings_the_user_back(self):
        self.away("--hours", "8")
        _, context = self.hook("I'm back in the office, let's review")
        self.assertEqual(self.state()["ended_by"], "prompt")
        self.assertNotIn("is away until", context)

    def test_suggest(self):
        noon = time.mktime((2026, 11, 24, 12, 0, 0, 0, 0, -1))
        night = time.mktime((2026, 11, 24, 1, 0, 0, 0, 0, -1))
        self.assertEqual(ga.suggest("going to bed", noon), 'away --until "2026-11-25 09:00"')
        self.assertEqual(ga.suggest("good night", night), 'away --until "2026-11-24 09:00"')
        self.assertEqual(ga.suggest("I am away for 3h"), "away --hours 3")
        self.assertEqual(ga.suggest("stepping out"), "away --hours <N from their words>")
        self.assertEqual(ga.suggest("I'll be back in 2 hours"), "away --hours 2")
        for prompt in ("I'm back", "I'm back in the office", "back in the repo, run tests", "", None,
                       "Guide wake: going to sleep", "<cross-session-message>afk</x>"):
            self.assertIsNone(ga.suggest(prompt), prompt)

    def test_while_away_no_interview_and_the_title_shows_it(self):
        self.away("--hours", "8")
        title, context = self.hook("Guide wake: read ledger")
        self.assertTrue(title.startswith("\U0001f7e5\U0001f7e5 \U0001f4a4 until %s \u00b7 Sessions Manager"
                                         % time.strftime("%H:%M", time.localtime(self.state()["until"]))), title)
        self.assertIn("session-guide away: the user is away until", context)
        self.assertIn("no AskUserQuestion", context)
        self.assertIn("away hold", context)
        self.assertIn("merges, prod/staging writes", context)
        self.assertIn("The user is away: act on every worker message and relay first, and ask nothing.", context)
        self.assertNotIn("full interview", context)
        self.assertTrue(ga.away_now(self.state()))  # a wake is not the user

    def test_machine_prompts_keep_the_window(self):
        self.away("--hours", "8")
        for prompt in ("<cross-session-message from=\"x\">DONE</cross-session-message>",
                       "<task-notification>done</task-notification>", "<<autonomous-loop-dynamic>>", ""):
            self.hook(prompt)
        self.hook("", event="SessionStart")
        self.assertTrue(ga.away_now(self.state()))

    def test_a_typed_prompt_brings_the_user_back_with_the_tables(self):
        self.away("--hours", "8")
        self.away("decide", "model for the spike", "sonnet/medium", "--reverse", "relaunch it on opus")
        self.away("hold", "merge #12", "merges are held", "gh pr merge 12")
        title, context = self.hook("morning, what happened?")
        self.assertNotIn("\U0001f4a4", title)
        self.assertEqual(self.state()["ended_by"], "prompt")
        self.assertIn("the user is back (they typed a prompt", context)
        self.assertIn("Tick any to reverse", context)
        self.assertIn("- #1 ", context)
        self.assertIn("model for the spike -> sonnet/medium; to reverse: relaunch it on opus", context)
        self.assertIn("Waiting for you:\n- #2 ", context)
        self.assertIn("## AWAY MODE (back since", self.text())
        _, again = self.hook("and?")  # until `away clear`, every prompt says so
        self.assertIn("the user is back", again)
        self.away("clear")
        _, after = self.hook("ok")
        self.assertNotIn("session-guide away", after)

    def test_the_window_ends_at_its_time(self):
        self.away("--hours", "1")
        self.away("decide", "a", "b", "--reverse", "c")
        self.set_state(since=time.time() - 7200, until=time.time() - 60)
        _, context = self.hook("Guide wake: read ledger")
        self.assertIn("the user is back (the window ended", context)
        self.assertEqual(self.state()["ended_by"], "window")

    def test_ask_minutes_treats_an_old_owed_question_as_away(self):
        r = self.run_script("waiting", "ask", "Which icon for billing?", CLAUDE_CODE_SESSION_ID=GUIDE)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.text().replace(time.strftime(gt.TIME_FORMAT), "2026-01-01 10:00")
        with open(self.ledger, "w") as f:
            f.write(text)
        _, off = self.hook("hello")
        self.assertNotIn("session-guide away", off)
        _, on = self.hook("hello", SESSION_GUIDE_AWAY_ASK_MINUTES="30")
        self.assertIn("1 owed question(s) unanswered for over 30 min", on)
        self.assertIn("Which icon for billing?", on)
        self.assertIn("--timed-out", on)
        r = self.run_script("away", "decide", "Which icon for billing?", "\U0001f3e0", "--reverse", "rename the "
                            "stream", "--timed-out", "--ledger", self.ledger, SESSION_GUIDE_AWAY_ASK_MINUTES="30")
        self.assertIn("on a question that timed out", r.stdout)
        _, wake = self.hook("Guide wake: read ledger")  # not on a wake: the user may still be away
        self.assertNotIn("the user is back", wake)
        _, back = self.hook("hello")  # no window was open: the decision still comes up for keep / reverse
        self.assertIn("the user is back (questions decided after SESSION_GUIDE_AWAY_ASK_MINUTES)", back)
        self.assertIn("Which icon for billing?", back)

    def test_ask_minutes_skips_a_question_deferred_to_later(self):
        later = time.strftime(gt.TIME_FORMAT, time.localtime(time.time() + 3600))
        r = self.run_script("waiting", "ask", "Which icon for billing?", "--at", later, CLAUDE_CODE_SESSION_ID=GUIDE)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.text().replace(time.strftime(gt.TIME_FORMAT), "2026-01-01 10:00", 1)  # asked long ago
        with open(self.ledger, "w") as f:
            f.write(text)
        _, on = self.hook("hello", SESSION_GUIDE_AWAY_ASK_MINUTES="30")
        self.assertNotIn("session-guide away", on)
        r = self.run_script("away", "decide", "Which icon for billing?", "x", "--reverse", "y", "--timed-out",
                            "--ledger", self.ledger, SESSION_GUIDE_AWAY_ASK_MINUTES="30")
        self.assertIn("not away", r.stderr)  # deferred, so not timed out
        r = self.run_script("away", "decide", "no such question", "x", "--reverse", "y", "--timed-out",
                            "--ledger", self.ledger, SESSION_GUIDE_AWAY_ASK_MINUTES="30")
        self.assertIn("not away", r.stderr)

    def test_state_md_lists_the_block_while_it_has_rows(self):
        self.assertEqual(ga.state_lines(self.ledger), [])
        self.away("--hours", "2")
        self.away("hold", "merge #12", "merges are held", "gh pr merge 12")
        lines = ga.state_lines(self.ledger)
        self.assertRegex(lines[1], r"^## Away mode \(away until .*; 0 decided, 1 waiting\)$")
        self.assertIn("merge #12", lines[2])
        self.assertEqual(gt.away_lines(self.ledger), lines)
        self.away("done", "1")
        self.away("end")
        lines = ga.state_lines(self.ledger)  # settled, but still in the block until `away clear`
        self.assertRegex(lines[1], r"`away clear` not run yet; 0 decided, 0 waiting")
        self.assertEqual(lines[2:], ["- #1 merge #12: done"])
        self.away("clear")
        self.assertEqual(ga.state_lines(self.ledger), [])

    def test_a_broken_state_file_fails_open_and_writers_refuse(self):
        with open(ga.path_of(self.ledger), "w") as f:
            f.write("[1, 2]")
        _, context = self.hook("hello")
        self.assertNotIn("session-guide away", context)
        r = self.run_script("away", "--hours", "2", "--ledger", self.ledger)
        self.assertIn("can't be read", r.stderr)


if __name__ == "__main__":
    unittest.main()
