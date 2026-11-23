#!/usr/bin/env python3
"""Tests for skills/session-guide/scripts/guide_finished.py and its wiring in guide_title.py (the `finished` command,
the hook paragraph "session-guide finished:" and `sweep --defaults`). Every test uses its own temp CLAUDE_CONFIG_DIR."""
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
sys.path.insert(0, SCRIPTS)
import guide_finished as gf  # noqa: E402

SCRIPT = os.path.join(SCRIPTS, "guide_title.py")
FINISHED_SCRIPT = os.path.join(SCRIPTS, "guide_finished.py")
GUIDE = "c0ffee12-3456-4789-8abc-def012345678"
ME = "e1e1e1e1-3456-4789-8abc-def012345678"
HOUR = 3600
LEDGER = """# orchid-2026-11-02 — guide ledger
Guide: 'orchid guide' [c0ffee12] since 11-02 09:00

## Sessions
| Title [id6] | Level | Role / stream | Address |
|---|---|---|---|
| orchid guide [c0ffee] | MANAGED | the guide itself | uds |

## Waiting on the user
| Session [id6] | What the user needs to do | Asked | Remind at |
|---|---|---|---|

## Open items
| Item | Owner | Next action | Status |
|---|---|---|---|
"""


def sid_of(n):
    """A session id whose first 8 characters are unique per n."""
    return "%02x%02x%02x%02x-0000-4000-8000-0000000000%02x" % (n, n + 1, n + 2, n + 3, n)


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def user(text, at, entrypoint="cli", cwd="/tmp/repo"):
    return {"type": "user", "entrypoint": entrypoint, "cwd": cwd, "timestamp": iso(at),
            "message": {"role": "user", "content": text}}


def say(text, at, **extra):
    return dict({"type": "assistant", "timestamp": iso(at), "message": {"content": [{"type": "text", "text": text}]}},
                **extra)


def call(at, tid="toolu_1"):
    return {"type": "assistant", "timestamp": iso(at), "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": "ls"}}]}}


def tool_result(at, tid="toolu_1"):
    return {"type": "user", "timestamp": iso(at), "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}}


class FinishedBase(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="guide-finished-")
        self.ledger = os.path.join(self.cfg, "session-guide", "orchid-2026-11-02", "ledger.md")
        os.makedirs(os.path.dirname(self.ledger))
        self.write_ledger(LEDGER)
        drop = ("CLAUDE_CODE_SESSION_ID", "SESSION_GUIDE_GRACE_MINUTES", "SESSION_GUIDE_CLAUDE",
                "SESSION_GUIDE_FINISHED_HOURS", "SESSION_GUIDE_FINISHED_QUIET_MINUTES",
                "SESSION_GUIDE_NEW_SESSION_MINUTES")
        env = {k: v for k, v in os.environ.items() if k not in drop}
        env.update(CLAUDE_CONFIG_DIR=self.cfg, HOME=self.cfg, SESSION_GUIDE_AUDIT_HOURS="0",
                   SESSION_GUIDE_FOLLOWUP_HOURS="0", SESSION_GUIDE_GH="0")
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.cfg)

    def write_ledger(self, text):
        with open(self.ledger, "w") as f:
            f.write(text)

    def add_row(self, sid, level, title="some worker"):
        with open(self.ledger) as f:
            text = f.read()
        row = "| %s [%s] | %s | role | uds |\n" % (title, sid[:6], level)
        self.write_ledger(text.replace("| orchid guide [c0ffee] | MANAGED | the guide itself | uds |\n",
                                       "| orchid guide [c0ffee] | MANAGED | the guide itself | uds |\n" + row))

    def transcript(self, sid, lines, ago=2 * HOUR):
        """Write sid's transcript and set its mtime to `ago` seconds back."""
        path = os.path.join(self.cfg, "projects", "-tmp-repo", sid + ".jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("".join(json.dumps(l) + "\n" for l in lines))
        self.age(path, ago)
        return path

    def age(self, path, ago):
        stamp = time.time() - ago
        os.utime(path, (stamp, stamp))

    def convo(self, sid, final, ago=2 * HOUR, prompt="do x", entrypoint="cli", cwd="/tmp/repo", title=None):
        """A prompt and a final message `ago` seconds ago; a custom title when given."""
        now = time.time()
        lines = [user(prompt, now - ago - 60, entrypoint, cwd), say(final, now - ago)]
        if title:
            lines.append({"type": "custom-title", "customTitle": title})
        return self.transcript(sid, lines, ago)

    def cut(self, sid, ago=2 * HOUR, entrypoint="cli", prompt="do x", cwd="/tmp/repo"):
        """A session that stopped on a tool call, with no final message."""
        now = time.time()
        return self.transcript(sid, [user(prompt, now - ago - 60, entrypoint, cwd), call(now - ago)], ago)

    def job(self, sid, state="done", result="", ago=2 * HOUR, alive=False):
        now = time.time()
        folder = os.path.join(self.cfg, "jobs", sid[:8])
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "state.json"), "w") as f:
            json.dump({"state": state, "detail": result, "output": {"result": result or None}, "sessionId": sid,
                       "name": "worker", "createdAt": iso(now - ago - HOUR), "updatedAt": iso(now - ago),
                       "firstTerminalAt": None}, f)
        with open(os.path.join(folder, "timeline.jsonl"), "w") as f:
            f.write(json.dumps({"at": iso(now - ago), "state": state, "detail": result, "text": ""}) + "\n")
        self.process(sid, alive)

    def process(self, sid, alive):
        os.makedirs(os.path.join(self.cfg, "sessions"), exist_ok=True)
        with open(os.path.join(self.cfg, "sessions", sid[:8] + ".json"), "w") as f:
            json.dump({"pid": os.getpid() if alive else 2 ** 22 + 12345, "sessionId": sid}, f)

    def marker(self, sid, content):
        path = os.path.join(self.cfg, "session-guide", "guides", sid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content + "\n")

    def scan(self, **kw):
        return gf.scan(self.ledger, **kw)

    def ids(self, **kw):
        found = self.scan(**kw)
        return [s["id"] for s in found["sessions"]]

    def only(self, **kw):
        sessions = self.scan(**kw)["sessions"]
        self.assertEqual(len(sessions), 1, sessions)
        return sessions[0]

    def script(self, *args, program=SCRIPT, **env):
        return subprocess.run([sys.executable, program] + list(args), capture_output=True, text=True,
                              env=dict(os.environ, **env), input="")

    def hook(self, session_id=GUIDE):
        r = subprocess.run([sys.executable, SCRIPT, "hook"], capture_output=True, text=True, env=dict(os.environ),
                           input=json.dumps({"session_id": session_id, "hook_event_name": "UserPromptSubmit"}))
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return json.loads(r.stdout)["hookSpecificOutput"].get("additionalContext", "") if r.stdout else ""

    def reviewed_file(self):
        with open(os.path.join(os.path.dirname(self.ledger), "finished.json")) as f:
            return json.load(f)


class SessionFinishTest(FinishedBase):
    def test_no_row_session_with_result_and_link_is_clean(self):
        sid = sid_of(0x10)
        self.convo(sid, "Wrote the page.\nresult: page is live https://example.com/page/1\nbye", title="page worker")
        found = self.only()
        self.assertEqual((found["kind"], found["why"], found["level"]), ("clean", [], ""))
        self.assertEqual(found["result"], "page is live https://example.com/page/1")
        self.assertEqual(found["link"], "https://example.com/page/1")
        line = gf.describe(found)
        self.assertIn("clean 'page worker'", line)
        self.assertIn("no row", line)
        self.assertIn("https://example.com/page/1", line)

    def test_active_row_is_listed_and_other_levels_are_not(self):
        active = sid_of(0x20)
        others = {level: sid_of(0x30 + i * 4) for i, level in enumerate(["MANAGED", "WATCHED", "DONE", "HANDED OFF"])}
        self.convo(active, "result: all good")
        self.add_row(active, "ACTIVE")
        for level, sid in others.items():
            self.convo(sid, "result: all good")
            self.add_row(sid, level)
        found = self.scan()["sessions"]
        self.assertEqual([(s["id"], s["level"]) for s in found], [(active, "ACTIVE")])
        self.assertIn("ACTIVE row", gf.describe(found[0]))


class LooseEndTest(FinishedBase):
    def loose(self, final, **kw):
        sid = sid_of(0x40)
        self.convo(sid, final, **kw)
        found = self.only()
        self.assertEqual(found["kind"], "loose")
        self.assertTrue(found["why"])
        self.assertTrue(all(found["why"]))
        return found

    def test_final_message_ending_with_a_question_is_a_loose_end(self):
        found = self.loose("Both options work.\nWhich one should I use?")
        self.assertIn("Which one should I use?", " ".join(found["why"]))

    def test_needs_input_line_is_a_loose_end(self):
        found = self.loose("Drafted it.\nneeds input: the final title\n")
        self.assertIn("needs input: the final title", " ".join(found["why"]))

    def test_not_done_wording_is_a_loose_end(self):
        self.loose("Tests pass but the deploy is not done yet.")

    def test_follow_up_wording_is_a_loose_end(self):
        self.loose("Merged. There is a follow-up for the docs.")

    def test_blocked_wording_is_a_loose_end(self):
        self.loose("Could not continue, the build is blocked on a key.")

    def test_refused_wording_is_a_loose_end(self):
        self.loose("The gate refused the push.")

    def test_stopped_job_is_a_loose_end(self):
        sid = sid_of(0x40)
        self.convo(sid, "result: all good")
        self.job(sid, state="stopped", result="all good")
        found = self.only()
        self.assertEqual(found["kind"], "loose")
        self.assertIn("stopped", " ".join(found["why"]))

    def test_ending_on_a_tool_call_is_a_cut_loose_end(self):
        self.cut(sid_of(0x40))
        found = self.only()
        self.assertEqual(found["kind"], "loose")
        self.assertIn("no final message", " ".join(found["why"]))

    def test_api_error_entry_is_a_loose_end(self):
        sid = sid_of(0x40)
        now = time.time()
        self.transcript(sid, [user("do x", now - 2 * HOUR - 60),
                              say("API Error: 500 overloaded", now - 2 * HOUR, isApiErrorMessage=True)])
        found = self.only()
        self.assertEqual(found["kind"], "loose")
        self.assertIn("API error", " ".join(found["why"]))

    def test_loose_ends_sort_before_clean_ones(self):
        newest_clean, old_loose = sid_of(0x50), sid_of(0x54)
        self.convo(newest_clean, "result: fine", ago=HOUR)
        self.convo(old_loose, "Is this what you wanted?", ago=5 * HOUR)
        self.assertEqual(self.ids(), [old_loose, newest_clean])

    def test_negated_wording_is_clean(self):
        for n, text in enumerate(["Done. There are no follow-ups.", "All merged; nothing is blocked.",
                                  "Run finished with 0 failed."]):
            with self.subTest(text=text):
                self.convo(sid_of(0x60 + n * 4), text)
        found = self.scan()["sessions"]
        self.assertEqual(len(found), 3)
        self.assertEqual([(s["kind"], s["why"]) for s in found], [("clean", [])] * 3)


class StillRunningTest(FinishedBase):
    def test_working_job_with_live_process_is_left_out(self):
        sid = sid_of(0x40)
        self.convo(sid, "result: halfway")
        self.job(sid, state="working", alive=True)
        self.assertEqual(self.ids(), [])

    def test_session_without_job_but_live_process_is_left_out(self):
        sid = sid_of(0x40)
        self.convo(sid, "result: waiting for the user")
        self.process(sid, alive=True)
        self.assertEqual(self.ids(), [])
        self.process(sid, alive=False)
        self.assertEqual(self.ids(), [sid])

    def test_session_ended_under_quiet_minutes_ago_is_left_out(self):
        sid = sid_of(0x40)
        self.convo(sid, "result: just now", ago=5 * 60)
        self.assertEqual(self.ids(), [])

    def test_quiet_and_grace_zero_list_a_just_ended_session(self):
        sid = sid_of(0x40)
        self.convo(sid, "result: just now", ago=5 * 60)
        with mock.patch.dict(os.environ, SESSION_GUIDE_FINISHED_QUIET_MINUTES="0", SESSION_GUIDE_GRACE_MINUTES="0"):
            self.assertEqual(self.ids(), [sid])


class LeftOutTest(FinishedBase):
    def test_calling_session_is_left_out(self):
        self.convo(ME, "result: fine")
        self.assertEqual(self.ids(me=ME), [])
        self.assertEqual(self.ids(), [ME])

    def test_guide_is_left_out(self):
        self.convo(GUIDE, "result: handed over")
        self.marker(GUIDE, self.ledger)
        self.assertEqual(self.ids(), [])

    def test_closed_session_is_left_out(self):
        sid = sid_of(0x40)
        self.convo(sid, "result: fine")
        self.marker(sid, "done")
        self.assertEqual(self.ids(), [])

    def test_transcript_older_than_a_day_is_left_out(self):
        self.convo(sid_of(0x40), "result: old", ago=25 * HOUR)
        self.assertEqual(self.ids(), [])

    def test_hours_zero_turns_the_look_off(self):
        self.convo(sid_of(0x40), "result: fine")
        self.cut(sid_of(0x44), prompt="other 1")
        with mock.patch.dict(os.environ, SESSION_GUIDE_FINISHED_HOURS="0"):
            self.assertEqual(self.scan(), dict(sessions=[], jobs=[]))
        self.assertEqual(len(self.scan()["sessions"]), 2)


class ScriptRunTest(FinishedBase):
    def run_final(self, n, prompt, final, cwd="/tmp/repo", ago=2 * HOUR):
        self.convo(sid_of(n), final, ago=ago, prompt=prompt, entrypoint="sdk-cli", cwd=cwd)
        return sid_of(n)

    def test_runs_that_ended_well_are_hidden_and_remembered_at_once(self):
        ok = self.run_final(0x40, "nightly sync 7", "Synced everything.\nresult: 12 rows")
        self.assertEqual(self.scan(), dict(sessions=[], jobs=[]))
        marks = self.reviewed_file()
        self.assertEqual(marks[ok]["as"], "job-ok")

    def test_failed_runs_of_one_prompt_but_for_digits_are_one_job(self):
        a = self.run_final(0x40, "sync batch 17", "I can't help with that.", ago=3 * HOUR)
        b = self.run_final(0x44, "sync batch 18", "I can't help with that.", ago=2 * HOUR)
        found = self.scan()
        self.assertEqual(found["sessions"], [])
        self.assertEqual(len(found["jobs"]), 1)
        job = found["jobs"][0]
        self.assertEqual(sorted(r["id"] for r in job["runs"]), sorted([a, b]))
        self.assertEqual(job["id"], b)  # the latest run names the job
        self.assertIn("2 run(s)", gf.describe(job))

    def test_refused_run_counts_as_failed(self):
        sid = self.run_final(0x40, "audit repo", "I can't help with that.")
        job = self.scan()["jobs"][0]
        self.assertEqual(job["id"], sid)
        self.assertTrue(job["why"].startswith("refused"), job["why"])

    def test_run_with_no_final_message_counts_as_failed(self):
        self.cut(sid_of(0x40), entrypoint="sdk-cli", prompt="build report")
        job = self.scan()["jobs"][0]
        self.assertIn("no final message", job["why"])

    def test_runs_of_a_different_prompt_form_a_second_job(self):
        self.run_final(0x40, "sync batch 17", "I can't help with that.")
        self.run_final(0x44, "weekly digest", "I can't help with that.")
        found = self.scan()
        self.assertEqual(len(found["jobs"]), 2)
        self.assertEqual(sorted(len(j["runs"]) for j in found["jobs"]), [1, 1])

    def test_same_prompt_in_another_folder_is_another_job(self):
        self.run_final(0x40, "sync batch 17", "I can't help with that.", cwd="/tmp/repo-a")
        self.run_final(0x44, "sync batch 18", "I can't help with that.", cwd="/tmp/repo-b")
        self.assertEqual(len(self.scan()["jobs"]), 2)


class ReviewedTest(FinishedBase):
    def setUp(self):
        super().setUp()
        self.clean, self.clean2, self.loosed = sid_of(0x40), sid_of(0x44), sid_of(0x48)
        self.convo(self.clean, "result: fine", ago=3 * HOUR)
        self.convo(self.clean2, "result: also fine", ago=4 * HOUR)
        self.convo(self.loosed, "Should I go on?", ago=5 * HOUR)

    def test_reviewed_without_ids_marks_every_clean_finish_and_no_loose_end(self):
        lines = gf.mark_reviewed(self.ledger, [])
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(l.startswith("Reviewed: clean") for l in lines), lines)
        self.assertEqual(sorted(self.reviewed_file()), sorted([self.clean, self.clean2]))
        self.assertEqual(self.ids(), [self.loosed])

    def test_reviewed_with_an_id8_marks_that_loose_end(self):
        lines = gf.mark_reviewed(self.ledger, [self.loosed[:8]])
        self.assertEqual(len(lines), 1)
        self.assertIn("Reviewed: LOOSE END", lines[0])
        self.assertIn(self.loosed, self.reviewed_file())
        self.assertEqual(sorted(self.ids()), sorted([self.clean, self.clean2]))

    def test_unknown_id_says_not_marked(self):
        lines = gf.mark_reviewed(self.ledger, ["ffffffff"])
        self.assertEqual(len(lines), 1)
        self.assertIn("Not marked", lines[0])
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.ledger), "finished.json")))

    def test_nothing_clean_to_mark_when_only_loose_ends_are_left(self):
        gf.mark_reviewed(self.ledger, [])
        self.assertIn("Nothing clean to mark", gf.mark_reviewed(self.ledger, [])[0])

    def test_a_jobs_latest_run_id_marks_all_its_failed_runs(self):
        for n, ago in ((0x50, 3 * HOUR), (0x54, 2 * HOUR)):
            self.convo(sid_of(n), "I can't help with that.", ago=ago, prompt="sync batch %d" % n,
                       entrypoint="sdk-cli", cwd="/tmp/jobdir")
        job = self.scan()["jobs"][0]
        self.assertEqual(job["id"], sid_of(0x54))
        lines = gf.mark_reviewed(self.ledger, [job["id"][:8]])
        self.assertEqual(len(lines), 1)
        self.assertTrue({sid_of(0x50), sid_of(0x54)} <= set(self.reviewed_file()))
        self.assertEqual(self.scan()["jobs"], [])

    def test_reviewed_session_with_a_later_final_message_is_listed_again(self):
        gf.mark_reviewed(self.ledger, [])
        self.assertNotIn(self.clean, self.ids())
        path = os.path.join(self.cfg, "projects", "-tmp-repo", self.clean + ".jsonl")
        with open(path, "a") as f:
            f.write(json.dumps(user("one more thing", time.time() - 1500)) + "\n")
            f.write(json.dumps(say("result: the one more thing", time.time() - 1200)) + "\n")
        self.age(path, 1200)
        found = {s["id"]: s for s in self.scan()["sessions"]}
        self.assertIn(self.clean, found)
        self.assertEqual(found[self.clean]["result"], "the one more thing")

    def test_marks_older_than_seven_days_are_dropped_on_the_next_write(self):
        path = os.path.join(os.path.dirname(self.ledger), "finished.json")
        stale, recent = sid_of(0x70), sid_of(0x74)
        now = int(time.time())
        with open(path, "w") as f:
            json.dump({stale: {"ended": now - 8 * 86400, "mtime": now - 8 * 86400, "at": "x", "as": "clean"},
                       recent: {"ended": now - 6 * 86400, "mtime": now - 6 * 86400, "at": "x", "as": "clean"}}, f)
        gf.mark_reviewed(self.ledger, [])
        marks = self.reviewed_file()
        self.assertNotIn(stale, marks)
        self.assertIn(recent, marks)
        self.assertIn(self.clean, marks)


class CommandLineTest(FinishedBase):
    def setUp(self):
        super().setUp()
        self.clean = sid_of(0x40)
        self.convo(self.clean, "result: fine https://example.com/ok", title="clean worker")

    def test_finished_command_prints_a_line_per_session_and_a_count(self):
        r = self.script("finished", "--ledger", self.ledger)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 2, r.stdout)
        self.assertIn("clean 'clean worker' [%s]" % self.clean[:8], lines[0])
        self.assertIn("https://example.com/ok", lines[0])
        self.assertEqual(lines[1], "Finished on their own: 1 (0 with a loose end)")

    def test_finished_reviewed_marks_and_then_nothing_is_left(self):
        r = self.script("finished", "--ledger", self.ledger, "--reviewed")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertTrue(r.stdout.startswith("Reviewed: clean 'clean worker'"), r.stdout)
        r = self.script("finished", "--ledger", self.ledger)
        self.assertEqual(r.stdout.strip(), "Nothing finished unseen.")

    def test_module_run_directly_prints_the_same(self):
        via_title = self.script("finished", "--ledger", self.ledger)
        direct = self.script("--ledger", self.ledger, program=FINISHED_SCRIPT)
        self.assertEqual((direct.returncode, direct.stderr), (0, ""))
        self.assertEqual(direct.stdout, via_title.stdout)
        done = self.script("--ledger", self.ledger, "--reviewed", program=FINISHED_SCRIPT)
        self.assertTrue(done.stdout.startswith("Reviewed: clean"), done.stdout)
        again = self.script("--ledger", self.ledger, program=FINISHED_SCRIPT)
        self.assertEqual(again.stdout.strip(), "Nothing finished unseen.")

    def test_missing_ledger_is_an_error(self):
        r = self.script("finished", "--ledger", os.path.join(self.cfg, "nope.md"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no ledger", r.stderr)


class HookTest(FinishedBase):
    def setUp(self):
        super().setUp()
        self.marker(GUIDE, self.ledger)
        self.convo(sid_of(0x40), "result: fine", title="hook worker")

    def test_hook_lists_finished_sessions_until_reviewed(self):
        context = self.hook()
        self.assertIn("session-guide finished:", context)
        self.assertIn("Finished on their own", context)
        self.assertIn("clean 'hook worker' [%s]" % sid_of(0x40)[:8], context)
        gf.mark_reviewed(self.ledger, [])
        self.assertNotIn("session-guide finished:", self.hook())

    def test_hook_says_nothing_when_the_look_is_off(self):
        with mock.patch.dict(os.environ, SESSION_GUIDE_FINISHED_HOURS="0"):
            self.assertNotIn("session-guide finished:", self.hook())


class SweepDefaultsTest(FinishedBase):
    def test_defaulted_session_is_still_listed_as_active_until_reviewed(self):
        sid = sid_of(0x40)
        self.convo(sid, "result: fine", ago=2 * HOUR, title="sweep worker")
        self.assertEqual(self.only()["level"], "")
        r = self.script("sweep", self.ledger, "--defaults")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn("Defaulted: 'sweep worker' [%s] -> ACTIVE" % sid[:8], r.stdout)
        with open(self.ledger) as f:
            self.assertIn("[%s] | ACTIVE" % sid[:6], f.read())
        found = self.only()
        self.assertEqual((found["id"], found["level"], found["kind"]), (sid, "ACTIVE", "clean"))
        gf.mark_reviewed(self.ledger, [])
        self.assertEqual(self.ids(), [])


if __name__ == "__main__":
    unittest.main()
