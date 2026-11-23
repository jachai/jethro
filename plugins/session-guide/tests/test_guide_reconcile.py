#!/usr/bin/env python3
"""Tests for skills/session-guide/scripts/guide_reconcile.py and its wiring in guide_title.py (hook, mark, retire,
settle, reconcile, launch). Every test uses its own temp CLAUDE_CONFIG_DIR: the job folders, process files,
transcripts and markers are all fixtures, never the real ~/.claude."""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "session-guide", "scripts")
sys.path.insert(0, SCRIPTS)
import guide_reconcile as gr  # noqa: E402
import guide_title as gt  # noqa: E402

SCRIPT = os.path.join(SCRIPTS, "guide_title.py")
GUIDE = "c0ffee12-3456-4789-8abc-def012345678"
NEW_GUIDE = "d0d0d0d0-3456-4789-8abc-def012345678"
RELAY = "a7a7a7a7-0000-4000-8000-000000000001"  # 'atlas plan rewrite (2)'
CLEANUP = "b8b8b8b8-0000-4000-8000-000000000002"
SPIKE = "c9c9c9c9-0000-4000-8000-000000000003"
LEDGER = """# atlas-2026-11-02 — guide ledger
Guide: 'atlas guide' [c0ffee12] since 11-02 09:00

## Streams
| Stream | Where now | Next step | Owner | Blocked on |
|---|---|---|---|---|
| Atlas plan | rewrite | review | 'atlas plan rewrite (2)' [a7a7a7] | — |

## Sessions
| Title [id6] | Level | Role / stream | Address |
|---|---|---|---|
| atlas plan rewrite (2) [a7a7a7] | MANAGED | plan rewrite | uds |
| ledger cleanup [b8b8b8] | MANAGED | cleanup | uds |
| search spike [c9c9c9] | WATCHED | — | — |
| atlas guide [c0ffee] | MANAGED | the guide itself | uds |

## Waiting on the user
| Session [id6] | What the user needs to do | Asked | Remind at |
|---|---|---|---|

## Open items
| Item | Owner | Next action | Status |
|---|---|---|---|
"""
OLD_SENTENCE = "keep reporting in your " + "final message"  # split, so this file is not a match itself


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


class ReconcileBase(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="guide-reconcile-")
        self.ledger = os.path.join(self.cfg, "session-guide", "atlas-2026-11-02", "ledger.md")
        os.makedirs(os.path.dirname(self.ledger))
        self.write_ledger(LEDGER)
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "SESSION_GUIDE_GRACE_MINUTES",
                                                                 "SESSION_GUIDE_CLAUDE")}
        env.update(CLAUDE_CONFIG_DIR=self.cfg, HOME=self.cfg, SESSION_GUIDE_AUDIT_HOURS="0", SESSION_GUIDE_FOLLOWUP_HOURS="0",
                   SESSION_GUIDE_GH="0")
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.cfg)

    def write_ledger(self, text):
        with open(self.ledger, "w") as f:
            f.write(text)

    def job(self, sid, state="done", result="", detail="", ago=600, text="", alive=False, transcript=None):
        """A job folder for sid, ended `ago` seconds ago (or still working), and its process file."""
        now = time.time()
        folder = os.path.join(self.cfg, "jobs", sid[:8])
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "state.json"), "w") as f:
            json.dump({"state": state, "detail": detail or result, "output": {"result": result or None},
                       "sessionId": sid, "name": "worker", "createdAt": iso(now - ago - 3600),
                       "updatedAt": iso(now - ago), "firstTerminalAt": None, "linkScanPath": transcript or ""}, f)
        with open(os.path.join(folder, "timeline.jsonl"), "w") as f:
            f.write(json.dumps({"at": iso(now - ago - 120), "state": "working", "detail": "working", "text": ""}) + "\n")
            f.write(json.dumps({"at": iso(now - ago), "state": state, "detail": detail or result, "text": text}) + "\n")
        os.makedirs(os.path.join(self.cfg, "sessions"), exist_ok=True)
        with open(os.path.join(self.cfg, "sessions", sid[:8] + ".json"), "w") as f:
            json.dump({"pid": os.getpid() if alive else 2 ** 22 + 12345, "sessionId": sid,
                       "messagingSocketPath": "/tmp/cc-socks/%s.sock" % sid[:4]}, f)

    def transcript(self, sid, lines):
        path = os.path.join(self.cfg, "projects", "-tmp-repo", sid + ".jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("".join(json.dumps(l) + "\n" for l in lines))
        return path

    def flags(self, **kw):
        return gr.reconcile(self.ledger, **kw)

    def kinds(self, **kw):
        return [(f["kind"], f["id"]) for f in self.flags(**kw)]

    def script(self, *args, stdin="", **env):
        full = dict(os.environ, **env)
        return subprocess.run([sys.executable, SCRIPT] + list(args), input=stdin, capture_output=True, text=True,
                              env=full)

    def hook(self, session_id=GUIDE):
        r = self.script("hook", stdin=json.dumps({"session_id": session_id, "hook_event_name": "UserPromptSubmit"}))
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return json.loads(r.stdout)["hookSpecificOutput"].get("additionalContext", "") if r.stdout else ""

    def handed_off_relay(self):
        """The 11-19 shape: MANAGED row, job done, result HANDED OFF, final text naming its resume prompt."""
        self.job(RELAY, result="HANDED OFF — fix wave done and logged; fact check still running",
                 text="**HANDED OFF** at 150k. Resume prompt: ~/work/atlas/resume-prompt.md; state in "
                      "~/work/atlas/STATE.md")


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def send(tid, to, message):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "SendMessage", "input": {"to": to, "message": message}}]}}


def sent(tid, ok=True):
    return {"type": "user", "toolUseResult": {"success": ok}, "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": [{"type": "text", "text": json.dumps({"success": ok})}]}]}}


class ReconcileTest(ReconcileBase):
    def test_a_handoff_with_no_successor_row_is_flagged_with_its_resume_prompt(self):
        self.handed_off_relay()
        flags = self.flags()
        self.assertEqual([(f["kind"], f["id"]) for f in flags], [("handoff", "a7a7a7")])
        self.assertEqual(flags[0]["prompts"][0], "~/work/atlas/resume-prompt.md")
        line = gr.describe(flags[0])
        self.assertIn("Start the successor now from ~/work/atlas/resume-prompt.md", line)
        self.assertIn("successor of [a7a7a7]", line)
        self.assertNotIn("ask the user", line.lower())  # a successor starts without asking first

    def test_a_successor_row_by_next_number_or_by_reference_clears_it(self):
        self.handed_off_relay()
        self.write_ledger(LEDGER.replace("| ledger cleanup [b8b8b8]",
                                         "| atlas plan rewrite (3) [e1e1e1] | MANAGED | plan rewrite | uds |\n"
                                         "| ledger cleanup [b8b8b8]"))
        self.assertEqual(self.kinds(), [])
        self.write_ledger(LEDGER.replace("| ledger cleanup [b8b8b8]",
                                         "| atlas relay [e1e1e1] | MANAGED | successor of [a7a7a7] | uds |\n"
                                         "| ledger cleanup [b8b8b8]"))
        self.assertEqual(self.kinds(), [])

    def test_a_row_no_longer_open_is_not_flagged(self):
        self.handed_off_relay()
        self.write_ledger(LEDGER.replace("[a7a7a7] | MANAGED", "[a7a7a7] | HANDED OFF"))
        self.assertEqual(self.kinds(), [])

    def test_handed_off_to_the_guide_is_a_deliverable_not_a_handoff(self):
        self.job(CLEANUP, result="DONE: cleanup notes handed off to the guide for the user")
        self.assertEqual(self.kinds(), [("ended", "b8b8b8")])
        for result in ("HANDED OFF at 140k; successor needed", "Handing off: context full", "**HANDED OFF** (fix 2)"):
            self.assertTrue(gr.is_handoff(result), result)
        for result in ("handed off to the guide", "all PRs handed off to you", "DONE; the guide handed off nothing",
                       "notes on handoff wording"):
            self.assertFalse(gr.is_handoff(result), result)

    def test_blocked_with_no_waiting_row_is_flagged_and_a_waiting_row_clears_it(self):
        self.job(CLEANUP, result="BLOCKED: needs a ruling on the export format")
        flags = self.flags()
        self.assertEqual([(f["kind"], f["id"]) for f in flags], [("blocked", "b8b8b8")])
        self.assertIn("ask the user", gr.describe(flags[0]))
        self.write_ledger(LEDGER.replace("|---|---|---|---|\n\n## Open items",
                                         "|---|---|---|---|\n| ledger cleanup [b8b8b8] | Rule on the export format | "
                                         "2026-11-02 10:00 | 2026-11-02 12:00 |\n\n## Open items"))
        self.assertEqual(self.kinds(), [])

    def test_a_job_blocked_on_input_or_waiting_on_the_guide_is_blocked(self):
        self.job(CLEANUP, state="blocked", result="", detail="reply `ok` to go ahead", alive=True)
        self.assertEqual(self.kinds(), [("blocked", "b8b8b8")])
        self.job(CLEANUP, result="BLOCKED on the guide's pick of the quote")
        self.assertEqual(self.kinds(), [("blocked", "b8b8b8")])
        self.job(CLEANUP, result="staging deploy green; the one quote is waiting on the guide")
        self.assertEqual(self.kinds(), [("ended", "b8b8b8")])  # loose words: still flagged, as an end to read

    def test_a_working_job_is_not_flagged_but_one_whose_process_is_gone_is(self):
        self.job(CLEANUP, state="working", detail="Reading the diff", alive=True, ago=7200)
        self.assertEqual(self.kinds(), [])
        self.job(CLEANUP, state="working", detail="Reading the diff", alive=False, ago=600)
        flags = self.flags()
        self.assertEqual([(f["kind"], f["state"]) for f in flags], [("ended", "working, no process")])

    def test_nothing_is_flagged_inside_the_grace(self):
        self.handed_off_relay()
        self.job(RELAY, result="HANDED OFF at 150k", ago=100)
        self.assertEqual(self.kinds(), [])
        self.assertEqual(self.kinds(grace_minutes=1), [("handoff", "a7a7a7")])
        with mock.patch.dict(os.environ, SESSION_GUIDE_GRACE_MINUTES="1"):
            self.assertEqual(self.kinds(), [("handoff", "a7a7a7")])
        self.assertEqual(self.kinds(now=time.time() - 3600, grace_minutes=0), [])  # it had not ended then
        later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
        self.assertEqual(self.kinds(now=later), [("handoff", "a7a7a7")])

    def test_watched_rows_flag_handoffs_and_blocks_but_not_a_plain_end(self):
        self.job(SPIKE, result="DONE: spike written up")
        self.assertEqual(self.kinds(), [])
        self.job(SPIKE, result="BLOCKED on the user's pick")
        self.assertEqual(self.kinds(), [("blocked", "c9c9c9")])

    def test_guides_closed_sessions_rows_without_jobs_and_the_caller_are_skipped(self):
        self.job(GUIDE, result="guide retired and handed over")
        self.assertEqual(self.kinds(), [("ended", "c0ffee")])
        self.assertEqual(self.kinds(me=GUIDE), [])
        os.makedirs(os.path.join(self.cfg, "session-guide", "guides"))
        with open(os.path.join(self.cfg, "session-guide", "guides", GUIDE), "w") as f:
            f.write(self.ledger + "\n")
        self.assertEqual(self.kinds(), [])  # a guide settles by handing over
        self.job(CLEANUP, result="DONE")
        with open(os.path.join(self.cfg, "session-guide", "guides", CLEANUP), "w") as f:
            f.write("done\n")
        self.assertEqual(self.kinds(), [])

    def test_job_facts(self):
        self.assertIsNone(gr.job_facts(CLEANUP))
        self.job(CLEANUP, result="BLOCKED: x", text="final words", ago=600)
        facts = gr.job_facts("b8b8b8")
        self.assertEqual({k: facts[k] for k in ("state", "result", "detail", "alive", "session_id", "text")},
                         dict(state="done", result="BLOCKED: x", detail="BLOCKED: x", alive=False, session_id=CLEANUP,
                              text="final words"))
        self.assertIsInstance(facts["ended_at"], datetime.datetime)
        self.assertAlmostEqual(facts["ended_at"].timestamp(), time.time() - 600, delta=5)
        self.job(CLEANUP, state="working", alive=True)
        self.assertEqual((gr.job_facts(CLEANUP[:8])["ended_at"], gr.job_facts(CLEANUP)["alive"]), (None, True))


class DeliveryTest(ReconcileBase):
    """An ended MANAGED worker whose last report never reached the guide, and reports left in the inbox."""
    def ended(self, lines):
        self.job(CLEANUP, result="DONE: cleanup merged", transcript=self.transcript(CLEANUP, lines))
        return self.kinds()

    def test_a_report_sent_to_the_socket_after_the_last_prompt_is_delivered(self):
        self.assertEqual(self.ended([user("go"), send("t1", "uds:/tmp/cc-socks/1.sock", "DONE: merged"), sent("t1")]),
                         [("ended", "b8b8b8")])

    def test_no_send_since_the_last_prompt_is_undelivered(self):
        kinds = self.ended([user("go"), send("t1", "uds:/tmp/cc-socks/1.sock", "progress: half"), sent("t1"),
                            user("Guide changing.")])
        self.assertEqual(kinds, [("ended", "b8b8b8"), ("undelivered", "b8b8b8")])
        line = gr.describe(self.flags()[1])
        self.assertIn("its last report never reached you", line)
        self.assertIn("peek b8b8b8b8", line)
        self.assertIn('Result: "DONE: cleanup merged"', line)

    def test_an_earlier_send_of_the_same_report_counts(self):
        self.assertEqual(self.ended([user("go"), send("t1", "uds:/tmp/cc-socks/1.sock", "DONE: cleanup merged"),
                                     sent("t1"), user("<task-notification>helper done</task-notification>")]),
                         [("ended", "b8b8b8")])

    def test_a_send_to_a_title_or_a_failed_send_is_undelivered(self):
        self.ended([user("go"), send("t1", "atlas guide", "DONE: merged"), sent("t1", ok=False)])
        self.assertIn("not a uds: socket", self.flags()[1]["why"])
        self.ended([user("go"), send("t1", "uds:/tmp/cc-socks/1.sock", "DONE: merged"), sent("t1", ok=False)])
        self.assertIn("failed", self.flags()[1]["why"])

    def test_a_handoff_never_sent_is_both_flags(self):
        self.job(RELAY, result="HANDED OFF at 150k", transcript=self.transcript(RELAY, [user("go")]))
        self.assertEqual(self.kinds(), [("handoff", "a7a7a7"), ("undelivered", "a7a7a7")])

    def test_inbox_reports_are_flagged_until_the_file_goes(self):
        inbox = os.path.join(os.path.dirname(self.ledger), "inbox")
        os.makedirs(inbox)
        with open(os.path.join(inbox, "b8b8b8b8.md"), "w") as f:
            f.write("\nBLOCKED: needs the export format\nSendMessage to uds:/tmp/x.sock failed\nmore\nand more\n")
        flags = self.flags()
        self.assertEqual([(f["kind"], f["id"], f["name"]) for f in flags], [("inbox", "b8b8b8", "ledger cleanup")])
        self.assertEqual(flags[0]["result"], "BLOCKED: needs the export format / SendMessage to uds:/tmp/x.sock failed / "
                                             "more")
        self.assertIn("then delete the file", gr.describe(flags[0]))
        os.remove(os.path.join(inbox, "b8b8b8b8.md"))
        self.assertEqual(self.flags(), [])


class WiringTest(ReconcileBase):
    """reconcile in the hook, settle, mark and retire; the reconcile and launch subcommands."""
    def mark(self, session=GUIDE):
        r = self.script("mark", self.ledger, "--session", session)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_hook_carries_the_clock_and_the_flags(self):
        self.mark()
        context = self.hook()
        self.assertRegex(context.split("\n")[0], r"^Now: \w{3} \d{4}-\d\d-\d\d \d\d:\d\d .*\(UTC[+-]\d{4}\)")
        self.assertNotIn("reconcile", context)
        self.handed_off_relay()
        for _ in range(2):  # it stays on every prompt until the row changes
            self.assertIn("HANDED OFF: 'atlas plan rewrite (2)' [a7a7a7a7]", self.hook())
        self.write_ledger(LEDGER.replace("[a7a7a7] | MANAGED", "[a7a7a7] | HANDED OFF"))
        self.assertNotIn("HANDED OFF:", self.hook())

    def test_mark_prints_the_reconcile_lines_first(self):
        self.handed_off_relay()
        out = self.mark(NEW_GUIDE)
        self.assertTrue(out.startswith("Reconcile: HANDED OFF: 'atlas plan rewrite (2)' [a7a7a7a7]"), out)
        self.assertLess(out.index("Reconcile:"), out.index("is a guide"))

    def test_settle_prints_the_reconcile_lines(self):
        self.job(CLEANUP, result="BLOCKED: needs a ruling")
        out = self.script("settle", self.ledger).stdout
        self.assertTrue(out.startswith("Reconcile: BLOCKED: 'ledger cleanup' [b8b8b8b8]"), out)

    def test_reconcile_subcommand_prints_and_never_writes(self):
        self.handed_off_relay()

        def tree():
            found = {}
            for top, _, files in os.walk(self.cfg):
                for name in files:
                    path = os.path.join(top, name)
                    found[path] = (os.path.getmtime(path), open(path, "rb").read())
            return found
        before = tree()
        for argv in (["reconcile", "--ledger", self.ledger],):
            r = self.script(*argv)
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            self.assertIn("HANDED OFF: 'atlas plan rewrite (2)' [a7a7a7a7]", r.stdout)
            self.assertIn("1 to reconcile", r.stdout)
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guide_reconcile.py"), "--ledger", self.ledger],
                           capture_output=True, text=True, env=dict(os.environ))
        self.assertIn("HANDED OFF:", r.stdout)
        self.assertEqual(tree(), before)
        self.assertIn("Nothing to reconcile", self.script("reconcile", "--ledger", self.ledger,
                                                          "--grace-minutes", "60").stdout)

    def test_retire_refuses_while_a_handoff_has_no_successor_then_force_hands_it_over(self):
        self.mark()
        self.handed_off_relay()
        r = self.script("retire", GUIDE)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Not retired", r.stdout)
        self.assertIn(gt.GUIDE_CHANGE, r.stdout)
        self.assertEqual(gt.marker_content(GUIDE), self.ledger)  # still the guide
        self.assertEqual(self.script("retire", GUIDE, "--check").returncode, 1)
        self.assertEqual(gt.marker_content(GUIDE), self.ledger)
        r = self.script("retire", GUIDE, "--force", "--to", "uds:/tmp/cc-socks/new.sock")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(gt.marker_content(GUIDE), "retired")
        text = open(self.ledger).read()
        block = text[text.index("## Handoff"):text.index("## Streams")]
        self.assertIn("| atlas plan rewrite (2) [a7a7a7] | handoff | HANDED OFF:", block)
        self.assertLess(text.index("## Handoff"), text.index("## Sessions"))
        context = self.hook()
        self.assertIn("you are a RETIRED guide", context)
        self.assertIn("uds:/tmp/cc-socks/new.sock", context)
        self.assertIn("Do not act as guide", context)

    def test_retire_with_nothing_open_retires_and_forwards_to_the_caller(self):
        self.mark()
        self.job(NEW_GUIDE, state="working", alive=True)  # the new guide's process and socket
        r = self.script("retire", GUIDE, CLAUDE_CODE_SESSION_ID=NEW_GUIDE)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn(gt.GUIDE_CHANGE, r.stdout)
        self.assertIn("uds:/tmp/cc-socks/d0d0.sock", self.hook())

    def test_the_old_guide_change_sentence_is_gone_from_the_plugin(self):
        for top, _, files in os.walk(ROOT):
            for name in files:
                if name.endswith((".md", ".py", ".json")) and name != "CHANGELOG.md" and "/tests" not in top:
                    with open(os.path.join(top, name), errors="replace") as f:
                        self.assertNotIn(OLD_SENTENCE, f.read().lower(), os.path.join(top, name))
        self.assertIn("Keep sending to this socket", gt.GUIDE_CHANGE)


class ReviewFixesTest(ReconcileBase):
    """The findings of the review of 0.1.20, each from its reproduction."""
    def test_loose_words_are_not_a_block(self):
        self.job(CLEANUP, result="DONE: nothing needs you")
        self.assertEqual(self.kinds(), [("ended", "b8b8b8")])
        for result in ("DONE: nothing needs you", "Waiting for CI was slow; DONE", "Needs no follow-up", "stopped early",
                       "DONE; blocked on nothing"):
            self.assertFalse(gr.is_blocked(result), result)
        for result in ("BLOCKED: needs a ruling", "**BLOCKED** on the export format", "NEEDS input: pick one",
                       "result: WAITING on the user's merge"):
            self.assertTrue(gr.is_blocked(result), result)
        self.assertTrue(gr.is_blocked("DONE", state="blocked"))

    def test_handed_off_to_the_guide_with_a_resume_prompt_is_a_handoff(self):
        self.job(RELAY, result="HANDED OFF to the guide at 150k; resume /x/resume.md")
        flags = self.flags()
        self.assertEqual([(f["kind"], f["id"]) for f in flags], [("handoff", "a7a7a7")])
        self.assertTrue(gr.is_handoff("plan handed off to the guide; resume prompt at ~/work/next.md"))
        self.assertFalse(gr.is_handoff("plan handed off to the guide"))

    def test_lowercase_handed_off_mid_sentence_with_a_resume_path_is_a_handoff(self):
        for result in ("Context full so I handed off; resume prompt at ~/Dev/x/resume-prompt.md for the next one",
                       "stopping here and handing off, resume prompt is /tmp/jj/resume.md"):
            self.assertTrue(gr.is_handoff(result), result)
        self.assertFalse(gr.is_handoff("DONE: the PR was handed off to Max"))

    def test_row_name_skips_a_leading_successor_reference(self):
        self.assertEqual(gr.row_name("successor of [12345678] 'other' [fedcba98]"), "other")

    def test_row_name_skips_levels_and_stream_icons(self):
        for cell in ("'Atlas Plan' [e1e1e1]", "\U0001f3e0 'Atlas Plan' [e1e1e1]", "\U0001f3e0 Atlas  plan [e1e1e1]",
                     "\U0001f7e7\U0001f7e7 (g) \U0001f3e0 atlas plan [e1e1e1]",
                     "\U0001f7e7\U0001f7e7 (g\u00b7hub) \U0001f3e0 atlas plan [e1e1e1]",
                     "\U0001f7e7\U0001f7e7 (g\u00b7hub) atlas plan [e1e1e1]", "[TW] 'atlas plan' [e1e1e1]",
                     "\U0001f7e7\U0001f7e7 (g) [TW] atlas plan [e1e1e1]"):
            self.assertEqual(gr.row_name(cell), "atlas plan", cell)
        self.assertEqual(gr.row_name("(gone) atlas [e1e1e1]"), "(gone) atlas")  # not a level tag

    def test_own_id_is_never_the_streams_tag(self):
        self.assertEqual(gr.own_id("[TW] 'atlas plan' [e1e1e1]"), "e1e1e1")

    def test_a_successor_row_with_an_icon_clears_the_handoff(self):
        self.handed_off_relay()
        for cell in ("\U0001f3e0 'atlas plan rewrite (3)' [e1e1e1]", "[TW] 'atlas plan rewrite (3)' [e1e1e1]",
                     "\U0001f3e0 'atlas relay' [e1e1e1] successor of [a7a7a7]"):
            self.write_ledger(LEDGER.replace("| ledger cleanup [b8b8b8]",
                                             "| %s | MANAGED | plan rewrite | uds |\n| ledger cleanup [b8b8b8]" % cell))
            self.assertEqual(self.kinds(), [], cell)
        # and a predecessor whose own row carries the icon
        self.write_ledger(LEDGER.replace("| atlas plan rewrite (2) [", "| \U0001f3e0 'atlas plan rewrite (2)' [")
                          .replace("| ledger cleanup [b8b8b8]", "| atlas plan rewrite (3) [e1e1e1] | MANAGED | plan | uds |\n"
                                                                "| ledger cleanup [b8b8b8]"))
        self.assertIn("\U0001f3e0 'atlas plan rewrite (2)' [", open(self.ledger).read())
        self.assertEqual(self.kinds(), [])

    def test_the_icon_alone_before_the_protocol_word(self):
        for result in ("\U0001f3e0 BLOCKED: needs a ruling", "[TW] BLOCKED: needs a ruling",
                       "result: \U0001f3e0 BLOCKED: x", "\U0001f3e0 result: BLOCKED x", "result: [TW] WAITING on x"):
            self.assertTrue(gr.is_blocked(result), result)
        for result in ("\U0001f3e0 Name \u00b7 BLOCKED", "\U0001f3e0 Billing export BLOCKED: x", "[TW] DONE: nothing needs you"):
            self.assertFalse(gr.is_blocked(result), result)
        for result in ("\U0001f3e0 HANDED OFF to the guide", "[TW] HANDED OFF: resume in x", "\U0001f3e0 handed off at 140k"):
            self.assertTrue(gr.is_handoff(result), result)

    def test_a_successor_named_in_the_title_cell_clears_the_handoff_and_keeps_its_own_id(self):
        self.mark_guide()
        self.handed_off_relay()
        self.write_ledger(LEDGER.replace("| ledger cleanup [b8b8b8]",
                                         "| 'build 2' [e1e1e1] successor of [a7a7a7] | MANAGED | plan rewrite | uds |\n"
                                         "| ledger cleanup [b8b8b8]"))
        self.assertEqual(gr.own_id("'build 2' [e1e1e1] successor of [a7a7a7]"), "e1e1e1")
        self.assertEqual(self.kinds(), [])
        self.assertEqual(self.script("retire", GUIDE, "--check").returncode, 0)  # the gate opens
        self.job("e1e1e1e1-0000-4000-8000-000000000009", result="DONE: rewrite merged")
        self.assertEqual(self.kinds(), [("ended", "e1e1e1")])  # the successor's own row, not its predecessor's

    def test_an_ended_row_with_a_waiting_row_is_left_to_settle(self):
        self.job(CLEANUP, result="DONE: merged, the user still has to deploy")
        self.assertEqual(self.kinds(), [("ended", "b8b8b8")])
        self.write_ledger(LEDGER.replace("|---|---|---|---|\n\n## Open items",
                                         "|---|---|---|---|\n| ledger cleanup [b8b8b8] | Deploy the cleanup | "
                                         "2026-11-02 10:00 | 2026-11-02 12:00 |\n\n## Open items"))
        self.assertEqual(self.kinds(), [])

    def test_the_retire_gate_refuses_when_reconcile_fails_and_the_hook_does_not(self):
        import contextlib
        import io
        self.mark_guide()
        with mock.patch.object(gr, "reconcile", side_effect=RuntimeError("job folder unreadable")):
            for argv, code in ((["retire", GUIDE], 1), (["retire", GUIDE, "--check"], 1)):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(gt.main(argv), code)
                self.assertIn("Reconcile failed", out.getvalue())
                self.assertIn("job folder unreadable", out.getvalue())
                self.assertEqual(gt.marker_content(GUIDE), self.ledger)  # not retired
            self.assertIsNone(gt.reconcile_context(self.ledger))  # the hook stays fail-open
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gt.main(["retire", GUIDE, "--force"]), 0)
        self.assertEqual(gt.marker_content(GUIDE), "retired")

    def test_any_delivered_send_after_the_last_prompt_counts(self):
        path = self.transcript(CLEANUP, [user("go"), send("t1", "uds:/tmp/cc-socks/1.sock", "DONE: merged"), sent("t1"),
                                         send("t2", "atlas guide", "and one more thing"), sent("t2", ok=False)])
        self.job(CLEANUP, result="DONE: merged", transcript=path)
        self.assertEqual(self.kinds(), [("ended", "b8b8b8")])

    def test_no_undelivered_flag_when_the_last_prompt_is_older_than_the_tail(self):
        filler = [{"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 500}]}}] * 12
        path = self.transcript(CLEANUP, [user("go")] + filler)
        self.job(CLEANUP, result="DONE: merged", transcript=path)
        with mock.patch.object(gr, "TRANSCRIPT_TAIL", 2048):
            self.assertEqual(self.kinds(), [("ended", "b8b8b8")])
        self.assertEqual(self.kinds(), [("ended", "b8b8b8"), ("undelivered", "b8b8b8")])  # the whole file: it can tell

    def mark_guide(self):
        r = self.script("mark", self.ledger, "--session", GUIDE)
        self.assertEqual(r.returncode, 0, r.stderr)

    def run_hook(self):
        import contextlib
        import io
        out = io.StringIO()
        stdin = io.StringIO(json.dumps({"session_id": GUIDE, "hook_event_name": "UserPromptSubmit"}))
        with mock.patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(out):
            self.assertEqual(gt.cmd_hook(), 0)
        return json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]

    def test_the_hook_sets_the_gh_budget_before_anything_that_can_call_gh(self):
        import types
        self.mark_guide()
        self.handed_off_relay()
        calls = []
        fake = types.ModuleType("guide_gh")
        fake.set_budget = lambda seconds=None: calls.append(("set_budget", seconds))

        def recorder(name, real):
            def wrapped(*args):
                calls.append((name,))
                return real(*args)
            return wrapped
        with mock.patch.dict(sys.modules, {"guide_gh": fake}), \
                mock.patch.object(gt, "reconcile_context", recorder("reconcile", gt.reconcile_context)), \
                mock.patch.object(gt, "audit_context", recorder("audit", gt.audit_context)), \
                mock.patch.object(gt, "claims_context", recorder("claims", gt.claims_context)):
            context = self.run_hook()
        self.assertEqual(calls, [("set_budget", None), ("reconcile",), ("audit",), ("claims",)])
        self.assertTrue(context.startswith("Now: "))
        self.assertIn("HANDED OFF: 'atlas plan rewrite (2)'", context)

    def test_a_slow_gh_check_cannot_lose_the_clock_or_reconcile(self):
        self.mark_guide()
        self.handed_off_relay()

        def slow(ledger):
            time.sleep(3)
            return "session-guide audit: too late"
        started = time.time()
        with mock.patch.object(gt, "audit_context", slow), \
                mock.patch.object(gt, "claims_context", side_effect=RuntimeError("gh broke")), \
                mock.patch.dict(os.environ, SESSION_GUIDE_HOOK_SECONDS="0.3"):
            context = self.run_hook()
        self.assertLess(time.time() - started, 2.5)
        self.assertTrue(context.startswith("Now: "))
        self.assertIn("HANDED OFF: 'atlas plan rewrite (2)'", context)
        self.assertNotIn("too late", context)
        self.assertIn("the audit check ran past this prompt's time budget", context)


ARTIFACT_ID = "AbCdEfGhIjKlMnOpQrStUv"  # 22 characters, as an artifact id is
COVERED_LEDGER = LEDGER.replace("## Waiting on the user", """## Results for you
| Deliverable | Link | Delivered | Asked | Answer |
|---|---|---|---|---|
| WID-4321 review (widget review [d1d1d1]) | https://example.test/r/1 | 2026-11-02 09:00 | 2026-11-02 09:00 | satisfied 2026-11-02 10:00 |

## Waiting on the user""").replace("|---|---|---|---|\n\n## Open items", """|---|---|---|---|
| owed question [018c07] | Did the user read the WID-4321 review? | 2026-11-01 10:00 | 2026-11-01 10:00 |

## Open items""").replace("| Item | Owner | Next action | Status |\n|---|---|---|---|\n", """| Item | Owner | Next action | Status |
|---|---|---|---|
| Chase WID-777 with the vendor | the user | chase | ASK 11-01 |
""")


class TitleWiringTest(ReconcileBase):
    """Claims, covered reminders, closes: tags, the shared-ids line and STATE.md's real session state, through the
    title script."""
    def setUp(self):
        super().setUp()
        os.environ.pop("SESSION_GUIDE_AUDIT_HOURS")  # the audit runs here, as on a real guide's prompt
        self.write_ledger(COVERED_LEDGER)
        r = self.script("mark", self.ledger, "--session", GUIDE)
        self.assertEqual(r.returncode, 0, r.stderr)

    def ok(self, *args):
        r = self.script(*args)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def test_a_claim_lands_in_the_ledger_and_its_hook_line_shows(self):
        out = self.ok("claim", "merge", "4242", "--repo", "acme/widgets")
        self.assertIn("merge PR #4242", out)
        self.assertIn("| acme/widgets#4242 | the user |", open(self.ledger).read())
        context = self.hook()
        self.assertIn("session-guide claims:", context)
        self.assertIn("merge PR #4242 (acme/widgets)", context)  # gh is off in tests: "not checked"

    def test_a_covered_due_reminder_is_likely_done_and_not_asked_in_hook_and_settle(self):
        context = self.hook()
        covered = context[context.index("look done already"):]
        self.assertIn("owed question [018c07]: Did the user read the WID-4321 review? -> likely done:", covered)
        self.assertNotIn("reminder(s) due:\n- owed question [018c07]", context)
        out = self.ok("settle", self.ledger)
        self.assertIn("Likely done: owed question [018c07]", out)
        self.assertNotIn("Due: owed question [018c07]", out)
        self.assertIn("0 due, 0 asleep, 1 likely done", out)

    def test_an_open_reminder_is_asked_with_its_checked_note(self):
        self.ok("waiting", "ask", "Did the vendor answer on WID-888?")
        out = self.ok("settle", self.ledger)
        self.assertRegex(out, r"Due: owed question \[\w{6}\]: Did the vendor answer on WID-888\? \(asked [\d: -]+\); "
                              r"checked \d\d-\d\d: still open because")

    def test_a_closes_result_reminder_closes_once_that_result_is_satisfied(self):
        out = self.ok("waiting", "ask", "Review the pricing deck", "--closes", "result:" + ARTIFACT_ID)
        key = re.search(r"owed question \[(\w{6})\]", out).group(1)
        self.assertIn("Review the pricing deck · closes: result:%s |" % ARTIFACT_ID, open(self.ledger).read())
        self.ok("settle", self.ledger)
        self.assertIn(key, gt.waiting_rows(self.ledger))  # not yet: no such result
        self.ok("result", "pricing deck", "https://claude.ai/artifact/" + ARTIFACT_ID)
        self.ok("result-answer", "pricing deck", "satisfied")
        self.ok("settle", self.ledger)
        self.assertNotIn(key, gt.waiting_rows(self.ledger))
        self.assertIn("closed 1 row(s) whose `closes:` tag has happened", self.hook())

    def test_closes_is_repeatable_checked_and_kept_on_a_repeat(self):
        self.ok("waiting", "ask", "Ship it", "--closes", "pr:#12", "--closes", "ticket:WID-9")
        self.assertIn("Ship it · closes: pr:#12 ticket:WID-9 |", open(self.ledger).read())
        self.ok("waiting", "ask", "Ship it", "--hours", "2")
        self.assertIn("Ship it · closes: pr:#12 ticket:WID-9 |", open(self.ledger).read())
        r = self.script("waiting", "ask", "Ship it", "--closes", "branch:main")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--closes takes", r.stderr)

    def test_a_new_row_sharing_an_id_names_the_open_rows(self):
        out = self.ok("waiting", "ask", "Did the vendor answer on WID-777?")
        self.assertRegex(out, r"open rows sharing ids: \w{6}\. Does this replace them\?")
        self.assertNotIn("sharing ids", self.ok("waiting", "ask", "Unrelated question"))

    def test_state_md_shows_the_real_session_state(self):
        self.job(CLEANUP, result="DONE: cleanup merged", ago=720)
        self.job(RELAY, state="working", detail="Reading the diff", alive=True)
        self.ok("settle", self.ledger)
        import guide_audit as ga
        state = open(ga.state_paths(self.ledger)[1]).read()
        self.assertIn("ledger cleanup [b8b8b8] MANAGED, ended 12 min ago (done), result: DONE: cleanup merged", state)
        self.assertIn("atlas plan rewrite (2) [a7a7a7] MANAGED, working: Reading the diff", state)
        self.assertIn("search spike [c9c9c9] WATCHED, no transcript", state)  # no job folder: the old wording

    def test_retire_prints_the_contract_text(self):
        out = self.script("retire", GUIDE, "--check").stdout
        self.assertIn('"Guide changing. Keep sending to this socket; the old guide forwards until the new one '
                      'introduces itself."', out)


FAKE_CLAUDE = r'''
import json, os, sys, time
cfg, sid = os.environ["CLAUDE_CONFIG_DIR"], os.environ["FAKE_SID"]
marker = os.path.join(cfg, "session-guide", "guides", sid)
def seen():
    return open(marker).read().strip() if os.path.isfile(marker) else None
log = {"argv": sys.argv[1:], "at_start": seen()}
if "--resume" not in sys.argv:
    os.makedirs(os.path.join(cfg, "jobs", sid[:8]), exist_ok=True)
    json.dump({"sessionId": sid, "state": "working"}, open(os.path.join(cfg, "jobs", sid[:8], "state.json"), "w"))
print("backgrounded \u00b7 " + sid[:8], flush=True)
end = time.time() + 5
while seen() is None and time.time() < end:  # the worker's first tool call: is the marker there yet?
    time.sleep(0.02)
log["while_running"] = seen()
json.dump(log, open(os.path.join(cfg, "fake-claude.json"), "w"))
'''


DENY_ASK = "--disallowedTools=AskUserQuestion"


class LaunchTest(ReconcileBase):
    SID = "e2e2e2e2-1111-4222-8333-444455556666"

    def launch(self, *args):
        fake = os.path.join(self.cfg, "fake_claude.py")
        with open(fake, "w") as f:
            f.write(FAKE_CLAUDE)
        r = self.script("launch", *args, SESSION_GUIDE_CLAUDE="%s %s" % (sys.executable, fake), FAKE_SID=self.SID)
        with open(os.path.join(self.cfg, "fake-claude.json")) as f:
            return r, json.load(f)

    def test_launch_marks_the_new_session_while_the_command_still_runs(self):
        r, log = self.launch("--", "--model", "sonnet", "brief: tidy the notes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(log["argv"], ["--bg", DENY_ASK, "--model", "sonnet", "brief: tidy the notes"])
        self.assertIsNone(log["at_start"])  # claude --bg picks the id: nothing to mark before it prints one
        self.assertEqual(log["while_running"], "guided")
        self.assertEqual(gt.marker_content(self.SID), "guided")
        self.assertIn("launched [e2e2e2e2] %s" % self.SID, r.stdout)
        self.assertIn("[e2e2e2] | MANAGED", r.stdout)

    def test_launch_watched(self):
        r, log = self.launch("--watched", "--", "--model", "haiku", "look")
        self.assertEqual((r.returncode, log["while_running"]), (0, "watched"))
        self.assertIn("| WATCHED |", r.stdout)

    def test_launch_with_resume_writes_the_marker_before_the_command_runs(self):
        r, log = self.launch("--", "--resume", self.SID, "next step")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(log["at_start"], "guided")
        self.assertEqual(log["argv"], ["--bg", DENY_ASK, "--resume", self.SID, "next step"])

    def argv(self, *args):
        r, log = self.launch("--", *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return log["argv"][1:]  # without --bg

    def test_launch_denies_asking_by_merging_into_the_flag_the_caller_has(self):
        self.assertEqual(self.argv("--model", "sonnet", "brief"), [DENY_ASK, "--model", "sonnet", "brief"])
        self.assertEqual(self.argv("--disallowedTools", "Bash", "brief"), ["--disallowedTools", "AskUserQuestion", "Bash", "brief"])
        self.assertEqual(self.argv("--disallowed-tools=Bash,Edit", "brief"), ["--disallowed-tools=AskUserQuestion,Bash,Edit", "brief"])
        self.assertEqual(self.argv("--disallowedTools", "Bash,Edit", "--model", "x", "brief"),
                         ["--disallowedTools", "AskUserQuestion", "Bash,Edit", "--model", "x", "brief"])
        for given in (["--disallowedTools", "Bash", "AskUserQuestion"], ["--disallowedTools=Bash,AskUserQuestion"],
                      ["--disallowedTools", "Bash,AskUserQuestion"]):  # already there: left alone, not duplicated
            self.assertEqual(self.argv(*given, "--model", "x", "brief"), given + ["--model", "x", "brief"])
        # the prompt is never a value: naming the tool in it does not count
        self.assertEqual(self.argv("--disallowedTools", "Bash", "never call AskUserQuestion"),
                         ["--disallowedTools", "AskUserQuestion", "Bash", "never call AskUserQuestion"])

    def test_launch_allow_ask_and_lean(self):
        r, log = self.launch("--allow-ask", "--", "--model", "x", "brief")
        self.assertEqual(log["argv"], ["--bg", "--model", "x", "brief"])
        r, log = self.launch("--lean", "--", "brief")
        self.assertEqual(log["argv"], ["--bg", DENY_ASK[:-len("AskUserQuestion")] +
                                       "AskUserQuestion,Artifact,Workflow,SendFeedback,ReportFindings", "brief"])
        r, log = self.launch("--lean", "--allow-ask", "--", "--disallowedTools=Artifact", "brief")
        self.assertEqual(log["argv"], ["--bg", "--disallowedTools=Workflow,SendFeedback,ReportFindings,Artifact", "brief"])

    def test_launch_refuses_a_guide_and_needs_arguments(self):
        os.makedirs(os.path.join(self.cfg, "session-guide", "guides"))
        with open(os.path.join(self.cfg, "session-guide", "guides", self.SID), "w") as f:
            f.write(self.ledger + "\n")
        self.assertNotEqual(self.script("launch", "--", "--resume", self.SID, "x").returncode, 0)
        self.assertEqual(gt.marker_content(self.SID), self.ledger)
        self.assertNotEqual(self.script("launch").returncode, 0)


class SuccessorTest(ReconcileBase):
    """A worker that starts its own successor leaves a note; the guide's reconcile shows it until the row exists."""
    SID = "e2e2e2e2-1111-4222-8333-444455556666"
    PROMPT = "resume from the state file; report to uds:/tmp/cc-socks/guide.sock"

    def launch(self, *args, **env):
        fake = os.path.join(self.cfg, "fake_claude.py")
        with open(fake, "w") as f:
            f.write(FAKE_CLAUDE)
        return self.script("launch", *args, SESSION_GUIDE_CLAUDE="%s %s" % (sys.executable, fake), FAKE_SID=self.SID,
                           **env)

    def note_path(self):
        return os.path.join(os.path.dirname(self.ledger), "successors", self.SID[:8] + ".json")

    def test_a_worker_launching_its_successor_writes_the_note_and_prints_the_line_for_its_guide(self):
        r = self.launch("--successor-of", RELAY, "--ledger", self.ledger, "--", "--name", "atlas plan rewrite (3)",
                        "--model", "opus", "--effort", "high", self.PROMPT, CLAUDE_CODE_SESSION_ID=RELAY)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        note = json.load(open(self.note_path()))
        self.assertEqual({k: note[k] for k in ("of", "id", "name", "model", "effort", "by")},
                         dict(of=RELAY, id=self.SID, name="atlas plan rewrite (3)", model="opus", effort="high", by=RELAY))
        self.assertRegex(note["at"], r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertEqual(r.stdout.splitlines()[-1], "Now send your guide: HANDED OFF: successor "
                         "'atlas plan rewrite (3)' [e2e2e2e2] started (opus/high)")
        self.assertNotIn("Give it its Sessions row", r.stdout)
        self.assertNotIn("warning", r.stdout)

    def test_the_guide_launching_a_successor_keeps_the_row_line(self):
        os.makedirs(os.path.join(self.cfg, "session-guide", "guides"))
        with open(os.path.join(self.cfg, "session-guide", "guides", GUIDE), "w") as f:
            f.write(self.ledger + "\n")
        r = self.launch("--successor-of", RELAY, "--", self.PROMPT, CLAUDE_CODE_SESSION_ID=GUIDE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Give it its Sessions row now: | <title> [e2e2e2] | MANAGED |", r.stdout)
        self.assertNotIn("Now send your guide", r.stdout)
        self.assertTrue(os.path.isfile(self.note_path()))

    def test_a_successor_with_no_ledger_to_find_says_what_to_pass(self):
        shutil.rmtree(os.path.join(self.cfg, "session-guide"))
        r = self.launch("--successor-of", RELAY, "--", self.PROMPT, CLAUDE_CODE_SESSION_ID=RELAY)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pass --ledger <the guide's ledger path from your contract>", r.stderr)

    def test_warnings_for_a_prompt_with_no_socket_and_an_untrusted_folder(self):
        with open(os.path.join(self.cfg, ".claude.json"), "w") as f:
            json.dump({"projects": {"/somewhere/else": {"hasTrustDialogAccepted": True}}}, f)
        r = self.launch("--successor-of", RELAY, "--ledger", self.ledger, "--", "no socket named here")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)  # warnings never stop the launch
        self.assertIn("warning: the prompt names no uds: socket, so the successor won't know where to report", r.stdout)
        self.assertIn("warning: %s is not a trusted folder; a --bg session started here stops at the trust dialog. "
                      "Launch from the folder your own session runs in and give the worktree as an absolute path."
                      % os.getcwd(), r.stdout)
        with open(os.path.join(self.cfg, ".claude.json"), "w") as f:  # a parent folder is trusted
            json.dump({"projects": {os.path.dirname(os.getcwd()): {"hasTrustDialogAccepted": True}}}, f)
        self.assertNotIn("trusted folder", self.launch("--", "x").stdout)
        os.remove(os.path.join(self.cfg, ".claude.json"))  # unreadable: say nothing
        self.assertNotIn("trusted folder", self.launch("--", "x").stdout)

    def started(self, **extra):
        os.makedirs(os.path.join(os.path.dirname(self.ledger), "successors"), exist_ok=True)
        with open(self.note_path(), "w") as f:
            json.dump(dict(of=RELAY, id=self.SID, name="atlas plan rewrite (3)", model="opus", effort="high", by=RELAY,
                           at="2026-11-02 10:00", **extra), f)

    def test_reconcile_flags_a_started_successor_until_its_row_exists(self):
        self.handed_off_relay()
        self.started()
        flags = self.flags()
        self.assertEqual([(f["kind"], f["id"]) for f in flags], [("successor", "a7a7a7")])
        self.assertEqual(gr.describe(flags[0]).split(" Result:")[0],
                         "SUCCESSOR STARTED: 'atlas plan rewrite (2)' [a7a7a7a7] handed off and started its own "
                         "successor 'atlas plan rewrite (3)' [e2e2e2e2] (opus/high). Record only: give it a Sessions "
                         "row saying \"successor of [a7a7a7]\", Level MANAGED, and set this row's Level to HANDED OFF. "
                         "Do not start another.")
        os.makedirs(os.path.join(self.cfg, "session-guide", "guides"))
        with open(os.path.join(self.cfg, "session-guide", "guides", GUIDE), "w") as f:
            f.write(self.ledger + "\n")
        gate = self.script("retire", "--check", GUIDE)
        self.assertEqual(gate.returncode, 1, gate.stdout)  # the gate treats it like any flag
        self.assertIn("Reconcile: SUCCESSOR STARTED", gate.stdout)
        self.assertIn("SUCCESSOR STARTED", self.hook())
        self.write_ledger(LEDGER.replace("| ledger cleanup [b8b8b8]",
                                         "| atlas relay [e2e2e2] | MANAGED | successor of [a7a7a7] | uds |\n"
                                         "| ledger cleanup [b8b8b8]"))
        self.assertEqual(self.kinds(), [])
        self.assertNotIn("SUCCESSOR STARTED", self.hook())
        self.write_ledger(LEDGER.replace("| ledger cleanup [b8b8b8]",  # a row with the new id6 alone also clears it
                                         "| something [e2e2e2] | MANAGED | x | uds |\n| ledger cleanup [b8b8b8]"))
        self.assertEqual(self.kinds(), [])

    def test_a_note_for_another_session_changes_nothing(self):
        self.handed_off_relay()
        self.started()
        note = json.load(open(self.note_path()))
        note["of"] = CLEANUP
        json.dump(note, open(self.note_path(), "w"))
        self.assertEqual(self.kinds(), [("handoff", "a7a7a7")])


if __name__ == "__main__":
    unittest.main()
