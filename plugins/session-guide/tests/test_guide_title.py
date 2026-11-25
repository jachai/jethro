#!/usr/bin/env python3
"""Tests for skills/session-guide/scripts/guide_title.py. Every test uses its own temp CLAUDE_CONFIG_DIR."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "session-guide", "scripts", "guide_title.py")
sys.path.insert(0, os.path.dirname(SCRIPT))
import guide_title as gt  # noqa: E402
GUIDE = "c0ffee12-3456-4789-8abc-def012345678"
WORKER = "fa11ed00-1234-4567-89ab-cdef01234567"
TITLE = "🟥🟥 Sessions Manager · release-2026-10-27 (2 managed · 1 watched · 0 active · 0 new) 🟥🟥"
LEDGER = """# release-2026-10-27 — guide ledger
Guide: 'release guide' [c0ffee12] since 10-27 09:00

## Streams
| Stream | Where now | Next step | Owner | Blocked on |
|---|---|---|---|---|
| Billing export | on staging | prod | 'billing export lead' [3fa9c1] | — |

## Sessions
| Title [id6] | Level | Role / stream | Worktree @ sha | Address | Ctx | Last seen |
|---|---|---|---|---|---|---|
| billing export lead [3fa9c1] | MANAGED | billing lead | worktrees/billing @a1b2c3d | uds | 140k | 12:35 |
| search reindex [a1a1a1] | MANAGED | reindex | worktrees/search @b2c3d4e | uds | 40k | 12:30 |
| design spike [b5c6d7] | WATCHED | — | — | — | 90k | 12:02 |
| old lead [c1c1c1] | HANDED OFF | billing | — | — | 210k | 10:00 |
| personal notes [e8f9a0] | IGNORED | off path | | | | |

## Decisions (FINAL unless struck)
1. (10-27 10:10, user in guide) A MANAGED | WATCHED table-looking line outside Sessions is not counted.
"""


NOW = re.compile(r"^Now: \w{3} \d{4}-\d\d-\d\d \d\d:\d\d .*\(UTC[+-]\d{4}\)\. .*$")


IDLE_WORKERS = ("session-guide workers: no MANAGED worker is working right now, so the full interview (up to 4 "
                "questions a call) holds nobody up.")


def without_now(context):
    """A guide's hook context minus the lines every guide prompt carries: the clock ("Now: ...") and, when no MANAGED
    worker is working, the workers line (tests of that line read the hook's text themselves)."""
    lines = context.split("\n")
    if lines and NOW.match(lines[0]):
        lines = lines[1:]
    return "\n".join(l for l in lines if l != IDLE_WORKERS)


class GuideTitleBase(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="guide-title-")
        self.ledger = os.path.join(self.cfg, "session-guide", "release-2026-10-27", "ledger.md")
        os.makedirs(os.path.dirname(self.ledger))
        with open(self.ledger, "w") as f:
            f.write(LEDGER)

    def tearDown(self):
        shutil.rmtree(self.cfg)

    def run_script(self, *args, stdin="", **extra_env):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_CODE_SESSION_ID", "SESSION_GUIDE_TITLE", "SESSION_GUIDE_GUIDED_PREFIX",
                            "SESSION_GUIDE_DONE_PREFIX", "SESSION_GUIDE_WATCHED_PREFIX", "SESSION_GUIDE_ACTIVE_PREFIX",
                            "SESSION_GUIDE_NEW_SESSION_MINUTES", "SESSION_GUIDE_SLEEP_HOURS")}
        env.update(CLAUDE_CONFIG_DIR=self.cfg, HOME=self.cfg, SESSION_GUIDE_GH="0",  # never the network, nor ~/.claude.json
                   SESSION_GUIDE_FINISHED_HOURS="0")  # the finished paragraph is tested in test_guide_finished
        env.update(extra_env)
        return subprocess.run([sys.executable, SCRIPT] + list(args), input=stdin, capture_output=True, text=True,
                              env=env)

    def run_ok(self, *args, **env):
        r = self.run_script(*args, **env)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def hook(self, session_id=GUIDE, event="UserPromptSubmit", title=None, **extra_env):
        event_in = {"session_id": session_id, "hook_event_name": event}
        if title is not None:
            event_in["session_title"] = title
        return self.run_script("hook", stdin=json.dumps(event_in), **extra_env)

    def extra_context(self, session_id=GUIDE, **extra_env):
        """The hook's additionalContext for a session, without the clock line; "" when it gives none."""
        out = self.hook(session_id, **extra_env).stdout
        return without_now(json.loads(out)["hookSpecificOutput"].get("additionalContext", "")) if out else ""

    def guide_title(self, **extra_env):
        r = self.hook(**extra_env)
        return json.loads(r.stdout)["hookSpecificOutput"]["sessionTitle"] if r.stdout else None

    def worker_title(self, title, event="UserPromptSubmit", **extra_env):
        """The title the hook sets on WORKER, or None when it prints nothing."""
        r = self.hook(WORKER, event, title, **extra_env)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return json.loads(r.stdout)["hookSpecificOutput"]["sessionTitle"] if r.stdout else None

    def transcript(self, session_id, title="", entrypoint="cli", age=0, started=None):
        """A transcript last written `age` s ago; its first line carries a timestamp when `started` (epoch) is given."""
        path = os.path.join(self.cfg, "projects", "-tmp-repo", session_id + ".jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        first = {"type": "user", "entrypoint": entrypoint}
        if started is not None:
            first["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(started))
        with open(path, "w") as f:
            f.write(json.dumps(first) + "\n")
            f.write(json.dumps({"type": "custom-title", "customTitle": title}) + "\n")
        os.utime(path, (time.time() - age, time.time() - age))

    def run_job(self, sid, state="working", alive=True):
        """A job state for sid and, when alive, a process file naming this very test process as its pid."""
        os.makedirs(os.path.join(self.cfg, "jobs", sid[:8]), exist_ok=True)
        with open(os.path.join(self.cfg, "jobs", sid[:8], "state.json"), "w") as f:
            json.dump({"state": state, "sessionId": sid}, f)
        if alive:
            os.makedirs(os.path.join(self.cfg, "sessions"), exist_ok=True)
            with open(os.path.join(self.cfg, "sessions", sid[:8] + ".json"), "w") as f:
                json.dump({"sessionId": sid, "pid": os.getpid()}, f)

    def keep_open_rows_alive(self):
        """Give LEDGER's MANAGED and WATCHED rows fresh transcripts, since a row with none has to settle."""
        for rid in ("3fa9c1", "a1a1a1", "b5c6d7"):
            self.transcript(rid + "00-0000-4000-8000-000000000000")


class GuideTitleTest(GuideTitleBase):
    def test_marked_session_gets_exact_title_with_counts(self):
        self.keep_open_rows_alive()
        self.assertEqual(self.run_script("mark", self.ledger, "--session", GUIDE).returncode, 0)
        for event in ("UserPromptSubmit", "SessionStart"):
            r = self.hook(event=event)
            self.assertEqual(r.returncode, 0)
            output = json.loads(r.stdout)
            self.assertEqual(without_now(output["hookSpecificOutput"].pop("additionalContext")), "")  # the clock only
            self.assertEqual(output, {"hookSpecificOutput": {
                "hookEventName": event,
                "sessionTitle": TITLE}})

    def test_counts_follow_the_ledger(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        with open(self.ledger, "w") as f:
            f.write(LEDGER.replace("| design spike [b5c6d7] | WATCHED", "| design spike [b5c6d7] | MANAGED"))
        self.assertEqual(self.guide_title(), "🟥🟥 Sessions Manager · release-2026-10-27 (3 managed · 0 watched · 0 active · 0 new) 🟥🟥")

    def test_title_format_can_be_overridden(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        stdin = json.dumps({"session_id": GUIDE, "hook_event_name": "UserPromptSubmit"})
        r = self.run_script("hook", stdin=stdin, SESSION_GUIDE_TITLE="guide {managed}/{tracked}")
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["sessionTitle"], "guide 2/3")
        r = self.run_script("hook", stdin=stdin, SESSION_GUIDE_TITLE="guide {oops}")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_unmarked_session_prints_nothing(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        r = self.hook(session_id="badc0de0-0000-4000-8000-000000000000")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_unmark_stops_the_title(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        self.assertEqual(self.run_script("unmark", "--session", GUIDE).returncode, 0)
        r = self.hook()
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_bad_ledger_prints_nothing(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        for content in ("no sessions table here\n", None):
            if content is None:
                os.remove(self.ledger)
            else:
                with open(self.ledger, "w") as f:
                    f.write(content)
            r = self.hook()
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_bad_input_prints_nothing(self):
        for stdin in ("", "not json", "{}"):
            r = self.run_script("hook", stdin=stdin)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_mark_refuses_a_ledger_without_sessions(self):
        other = os.path.join(self.cfg, "notes.md")
        with open(other, "w") as f:
            f.write("# notes\n")
        self.assertNotEqual(self.run_script("mark", other, "--session", GUIDE).returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.cfg, "session-guide", "guides", GUIDE)))

    def test_mark_resolves_an_id_prefix(self):
        proj = os.path.join(self.cfg, "projects", "-tmp-repo")
        os.makedirs(proj)
        open(os.path.join(proj, GUIDE + ".jsonl"), "w").close()
        self.assertEqual(self.run_script("mark", self.ledger, "--session", GUIDE[:8]).returncode, 0)
        self.assertEqual(self.guide_title(), TITLE)

    def test_retired_guide_gets_the_faded_red_title_and_never_red_again(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        self.assertEqual(self.run_script("retire", GUIDE).returncode, 0)
        for event in ("UserPromptSubmit", "SessionStart"):
            output = json.loads(self.hook(event=event).stdout)
            self.assertIn("you are a RETIRED guide", output["hookSpecificOutput"].pop("additionalContext"))
            self.assertEqual(output, {"hookSpecificOutput": {
                "hookEventName": event, "sessionTitle": "🎟️🎟️ Sessions Manager (retired) 🎟️🎟️"}})
        self.assertNotEqual(self.run_script("mark", self.ledger, "--session", GUIDE).returncode, 0)
        self.assertIn("(retired)", self.hook().stdout)

    def test_retire_works_on_an_unmarked_session_and_can_be_overridden(self):
        self.assertEqual(self.run_script("retire", GUIDE).returncode, 0)
        stdin = json.dumps({"session_id": GUIDE, "hook_event_name": "UserPromptSubmit"})
        r = self.run_script("hook", stdin=stdin, SESSION_GUIDE_RETIRED_TITLE="old guide")
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["sessionTitle"], "old guide")

    def test_guided_worker_gets_the_prefix_on_its_own_title(self):
        self.assertEqual(self.run_script("guided", WORKER).returncode, 0)
        title = "housing stage 0 PR A gate · Running e2e2 rows"
        for event in ("UserPromptSubmit", "SessionStart"):
            self.assertEqual(self.worker_title(title, event), "🟧🟧 (g) " + title)
        self.assertIsNone(self.worker_title(""))  # no title yet: nothing to prefix

    def test_guided_prefix_is_idempotent(self):
        self.run_script("guided", WORKER)
        self.run_script("guided", WORKER)
        self.assertIsNone(self.worker_title("🟧🟧 (g) billing lead · Waiting on CI"))  # focus updates keep it: no output
        self.assertEqual(self.worker_title("🟧🟧 (g) 🟧🟧 (g) billing lead"), "🟧🟧 (g) billing lead")
        self.assertEqual(self.worker_title("(g)billing lead"), "🟧🟧 (g) billing lead")

    def test_a_title_with_the_old_bare_g_is_upgraded(self):
        self.run_script("guided", WORKER)
        self.assertEqual(self.worker_title("(g) billing lead · Waiting on CI"), "🟧🟧 (g) billing lead · Waiting on CI")
        self.assertEqual(self.worker_title("(g) (g) billing lead"), "🟧🟧 (g) billing lead")
        self.assertEqual(self.worker_title("🟧🟧 billing lead"), "🟧🟧 (g) billing lead")

    def test_guided_prefix_can_be_overridden(self):
        self.run_script("guided", WORKER)
        self.assertEqual(self.worker_title("billing lead", SESSION_GUIDE_GUIDED_PREFIX="[g] "), "[g] billing lead")
        self.assertIsNone(self.worker_title("[g] billing lead", SESSION_GUIDE_GUIDED_PREFIX="[g] "))

    def test_unguided_takes_the_prefix_off_then_drops_the_marker(self):
        self.run_script("guided", WORKER)
        self.assertEqual(self.run_script("unguided", WORKER).returncode, 0)
        self.assertEqual(self.worker_title("🟧🟧 (g) billing lead · Waiting on CI"), "billing lead · Waiting on CI")
        self.assertIsNone(self.worker_title("billing lead · Waiting on CI"))
        self.assertFalse(os.path.exists(os.path.join(self.cfg, "session-guide", "guides", WORKER)))
        self.assertIsNone(self.worker_title("(g) renamed by hand"))  # unmanaged now: the hook leaves it alone

    def test_guides_and_retired_guides_never_get_the_prefix(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        self.assertNotEqual(self.run_script("guided", GUIDE).returncode, 0)
        self.assertEqual(json.loads(self.hook(title="anything").stdout)["hookSpecificOutput"]["sessionTitle"],
                         TITLE)
        self.run_script("retire", GUIDE)
        self.assertNotEqual(self.run_script("guided", GUIDE).returncode, 0)
        self.assertEqual(self.run_script("unguided", GUIDE).returncode, 0)  # left as it is
        self.assertIn("(retired)", self.hook(title="anything").stdout)
        self.assertNotIn("(g)", self.hook(title="anything").stdout)

    def test_watched_session_gets_the_gray_blocks_and_no_g(self):
        self.assertEqual(self.run_script("watched", WORKER).returncode, 0)
        title = "design spike · Reading the diff"
        for event in ("UserPromptSubmit", "SessionStart"):
            self.assertEqual(self.worker_title(title, event), "⬜⬜ " + title)
        self.assertIsNone(self.worker_title("⬜⬜ " + title))  # focus updates keep it: no output
        self.assertEqual(self.worker_title("⬜⬜ ⬜⬜ design spike"), "⬜⬜ design spike")
        self.assertIsNone(self.worker_title(""))  # no title yet: nothing to prefix
        self.assertEqual(self.worker_title("design spike", SESSION_GUIDE_WATCHED_PREFIX="[w] "), "[w] design spike")

    def test_guided_and_watched_swap_prefixes(self):
        self.run_script("guided", WORKER)
        self.run_script("watched", WORKER)
        self.assertEqual(self.worker_title("🟧🟧 (g) billing lead"), "⬜⬜ billing lead")
        self.assertEqual(self.worker_title("(g) billing lead"), "⬜⬜ billing lead")
        self.run_script("guided", WORKER)
        self.assertEqual(self.worker_title("⬜⬜ billing lead"), "🟧🟧 (g) billing lead")

    def test_unwatched_takes_the_prefix_off_then_drops_the_marker(self):
        self.run_script("watched", WORKER)
        self.assertEqual(self.run_script("unwatched", WORKER).returncode, 0)
        self.assertEqual(self.worker_title("⬜⬜ design spike"), "design spike")
        self.assertIsNone(self.worker_title("design spike"))
        self.assertFalse(os.path.exists(os.path.join(self.cfg, "session-guide", "guides", WORKER)))
        self.assertIsNone(self.worker_title("⬜⬜ renamed by hand"))  # unmanaged now: the hook leaves it alone

    def test_watched_refuses_guides_retired_guides_and_closed_sessions(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        self.assertNotEqual(self.run_script("watched", GUIDE).returncode, 0)
        self.assertEqual(self.guide_title(), TITLE)
        self.run_script("retire", GUIDE)
        self.assertNotEqual(self.run_script("watched", GUIDE).returncode, 0)
        self.assertIn("(retired)", self.hook().stdout)
        self.run_script("done", WORKER)
        self.assertNotEqual(self.run_script("watched", WORKER).returncode, 0)
        self.assertEqual(self.worker_title("billing lead"), "✅ billing lead")

    def test_a_watched_session_that_becomes_the_guide_loses_the_prefix(self):
        self.run_script("watched", WORKER)
        self.assertEqual(self.run_script("mark", self.ledger, "--session", WORKER).returncode, 0)
        self.assertEqual(self.worker_title("⬜⬜ billing lead"), TITLE)

    def titles_state(self, session_id=WORKER, **state):
        """Write a session-titles state file, the way that plugin does; returns a function that reads it back."""
        path = os.path.join(self.cfg, "session-titles", session_id + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f)
        return lambda: json.load(open(path))

    def test_guided_goes_into_the_session_titles_origin(self):
        read = self.titles_state(origin="billing lead", focus="Waiting on CI", last_set="billing lead · Waiting on CI",
                                 history=["billing lead · Waiting on CI"])
        self.run_script("guided", WORKER)
        state = read()
        self.assertEqual(state["origin"], "🟧🟧 (g) billing lead")
        self.assertEqual(state["focus"], "Waiting on CI")
        self.assertEqual(state["last_set"], "🟧🟧 (g) billing lead · Waiting on CI")
        self.assertIn("billing lead · Waiting on CI", state["history"])  # its title now still reads as its own

    def test_session_titles_origin_follows_every_level_change(self):
        read = self.titles_state(origin="(g) billing lead", last_set="(g) billing lead")
        self.run_script("guided", WORKER)
        self.assertEqual(read()["origin"], "🟧🟧 (g) billing lead")  # an origin adopted from the old prefix upgrades
        self.run_script("watched", WORKER)
        self.assertEqual(read()["origin"], "⬜⬜ billing lead")
        self.run_script("unwatched", WORKER)
        self.assertEqual(read()["origin"], "billing lead")
        self.run_script("guided", WORKER)
        self.run_script("done", WORKER)
        self.assertEqual(read()["origin"], "✅ billing lead")

    def test_the_hook_syncs_a_session_marked_before_this_version(self):
        self.run_script("guided", WORKER)
        read = self.titles_state(origin="billing lead", last_set="billing lead")
        self.assertEqual(self.worker_title("billing lead"), "🟧🟧 (g) billing lead")
        self.assertEqual(read()["origin"], "🟧🟧 (g) billing lead")

    def test_the_bare_names_are_known_to_session_titles_so_a_name_flip_is_not_a_rename(self):
        """`launch -- --name X` shows the bare name after our prefixed title; the plugin must read it as its own."""
        read = self.titles_state(origin="billing lead", focus="Waiting on CI", last_set="billing lead · Waiting on CI",
                                 history=["billing lead · Waiting on CI"])
        self.run_script("guided", WORKER)
        state = read()
        self.assertEqual(state["origin"], "🟧🟧 (g) billing lead")
        self.assertIn("billing lead", state["history"])
        self.assertIn("billing lead · Waiting on CI", state["history"])
        self.assertIn("🟧🟧 (g) billing lead · Waiting on CI", state["history"] + [state["last_set"]])
        self.assertIn("billing lead", state["pinned"])  # session-titles keeps these past its 8-title cap
        self.assertEqual(state["decoration"], "🟧🟧 (g) ")  # what a manual rename keeps in front of the new name
        self.assertEqual(len(state["history"]), len(set(state["history"])))
        self.assertNotIn("", state["history"])
        self.run_script("guided", WORKER)  # again: nothing is added twice
        self.assertEqual(read()["history"], state["history"])

    def test_guides_and_retired_guides_turn_session_titles_off(self):
        read = self.titles_state(GUIDE, origin="old name")
        self.run_script("mark", self.ledger, "--session", GUIDE)
        self.assertTrue(read()["off"])
        self.assertEqual(read()["origin"], "old name")
        read = self.titles_state(GUIDE, origin="old name")
        self.run_script("retire", GUIDE)
        self.assertTrue(read()["off"])

    def test_no_or_broken_session_titles_state_changes_nothing(self):
        self.assertEqual(self.run_script("guided", WORKER).returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.cfg, "session-titles")))
        path = os.path.join(self.cfg, "session-titles", WORKER + ".json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write("{broken")
        self.assertEqual(self.run_script("guided", WORKER).returncode, 0)
        self.assertEqual(self.worker_title("billing lead"), "🟧🟧 (g) billing lead")
        with open(path) as f:
            self.assertEqual(f.read(), "{broken")

    def test_an_empty_or_unknown_id_is_an_error_not_this_session(self):
        for cmd in ("guided", "unguided", "retire"):
            for sid in ("", "  ", "deadbeef"):
                r = self.run_script(cmd, sid, CLAUDE_CODE_SESSION_ID=WORKER)
                self.assertNotEqual(r.returncode, 0, (cmd, sid))
        self.assertNotEqual(self.run_script("mark", self.ledger, "--session", "", CLAUDE_CODE_SESSION_ID=WORKER)
                            .returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.cfg, "session-guide", "guides", WORKER)))
        self.assertEqual(self.run_script("guided", CLAUDE_CODE_SESSION_ID=WORKER).returncode, 0)  # no id: this one
        self.assertEqual(self.worker_title("billing lead"), "🟧🟧 (g) billing lead")

    def test_an_id_prefix_resolves_from_a_worktree_project_folder(self):
        for proj in ("-tmp-repo", "-tmp-repo--claude-worktrees-billing"):  # moved into a worktree mid-session
            os.makedirs(os.path.join(self.cfg, "projects", proj))
        open(os.path.join(self.cfg, "projects", "-tmp-repo--claude-worktrees-billing", WORKER + ".jsonl"), "w").close()
        self.assertEqual(self.run_script("guided", WORKER[:8]).returncode, 0)
        open(os.path.join(self.cfg, "projects", "-tmp-repo", WORKER + ".jsonl"), "w").close()  # in both: one session
        self.assertEqual(self.run_script("unguided", WORKER[:8]).returncode, 0)
        self.assertEqual(self.worker_title("(g) billing lead"), "billing lead")

    def test_a_guided_worker_that_becomes_the_guide_loses_the_prefix(self):
        self.run_script("guided", WORKER)
        self.assertEqual(self.run_script("mark", self.ledger, "--session", WORKER).returncode, 0)
        self.assertEqual(self.worker_title("(g) billing lead"), TITLE)

    def test_new_count_and_context_come_from_a_live_sweep(self):
        self.keep_open_rows_alive()
        self.run_script("mark", self.ledger, "--session", GUIDE)
        self.assertEqual(self.extra_context(), "")  # only the clock
        self.transcript(GUIDE, "the guide itself")
        self.transcript("3fa9c1d2-0000-4000-8000-000000000000", "has a row")
        self.transcript("b5c6d7e8-0000-4000-8000-000000000000", "watched row")
        self.transcript("11111111-0000-4000-8000-000000000000", "too old", age=13 * 3600)
        self.transcript("22222222-0000-4000-8000-000000000000", "a monitor tick", entrypoint="sdk-cli")
        self.transcript("33333333-0000-4000-8000-000000000000", "closed one")
        self.run_script("done", "33333333-0000-4000-8000-000000000000")
        self.transcript("44444444-0000-4000-8000-000000000000", "new one")
        self.assertEqual(self.guide_title(), "🟥🟥 Sessions Manager · release-2026-10-27 (2 managed · 1 watched · 0 active · 1 new) 🟥🟥")
        output = json.loads(self.hook(SESSION_GUIDE_NEW_SESSION_MINUTES="0").stdout)["hookSpecificOutput"]
        self.assertIn("'new one' [44444444]", output["additionalContext"])
        self.assertIn("AskUserQuestion", output["additionalContext"])  # no default: the guide asks, as before
        for hidden in ("has a row", "watched row", "too old", "a monitor tick", "closed one", "the guide itself"):
            self.assertNotIn(hidden, output["additionalContext"])
        r = self.run_script("sweep", self.ledger, "--hours", "24", CLAUDE_CODE_SESSION_ID=GUIDE)
        self.assertIn("'too old' [11111111]", r.stdout)
        self.assertIn("New: 2", r.stdout)

    def test_a_new_session_stays_new_until_it_has_a_row(self):
        new = "44444444-0000-4000-8000-000000000000"
        self.keep_open_rows_alive()
        self.run_script("mark", self.ledger, "--session", GUIDE)
        self.transcript(new, "new one")
        self.assertEqual(self.run_script("active", new).returncode, 0)  # blue already, still unanswered
        self.assertIn("[44444444]", self.hook().stdout)
        with open(self.ledger, "a") as f:
            f.write("\n## Sessions\n| new one [444444] | ACTIVE | | | | | |\n")
        self.assertEqual(self.extra_context(), "")
        self.assertIn("0 active · 0 new", self.guide_title())  # it has a row now, but no process runs it
        self.run_job(new, state="")  # a live process and no job: an interactive session
        self.assertIn("1 active · 0 new", self.guide_title())

    def test_an_unreadable_process_file_is_skipped_wherever_the_scan_meets_it(self):
        live, dead = "66666600-0000-4000-8000-000000000000", "77777700-0000-4000-8000-000000000000"
        self.run_job(live, state="")
        self.run_job(dead, state="")
        dead_file = os.path.join(self.cfg, "sessions", dead[:8] + ".json")
        with open(dead_file, "w") as f:
            json.dump({"sessionId": dead, "pid": 2 ** 22 + 12345}, f)
        unreadable = os.path.join(self.cfg, "sessions", "unreadable.json")
        with open(unreadable, "w") as f:
            json.dump({"sessionId": dead, "pid": os.getpid()}, f)
        os.chmod(unreadable, 0)
        live_file = os.path.join(self.cfg, "sessions", live[:8] + ".json")
        for order in ([unreadable, live_file, dead_file], [dead_file, unreadable, live_file]):
            with mock.patch.dict(os.environ, CLAUDE_CONFIG_DIR=self.cfg), mock.patch.object(gt.glob, "glob",
                                                                                         return_value=order):
                self.assertEqual(gt.live_session_ids(), {live})

    def test_an_active_row_counts_only_while_its_session_runs(self):
        self.keep_open_rows_alive()
        self.run_script("mark", self.ledger, "--session", GUIDE)
        ended, running, held = ("55555%d00-0000-4000-8000-000000000000" % n for n in range(3))
        rows = "".join("| %s [%s] | ACTIVE | | | | | |\n" % (n, sid[:6]) for n, sid in
                       (("ended", ended), ("running", running), ("held", held)))
        with open(self.ledger, "a") as f:
            f.write("\n## Sessions\n" + rows + "| no id here | ACTIVE | | | | | |\n")
        for sid in (ended, running, held):
            self.transcript(sid, age=20 * 3600)  # old enough that the sweep leaves them out of new
        self.run_job(running, state="blocked")
        self.run_job(held, state="done")
        self.run_job(ended, alive=False)
        # running (a waiting job still runs) and the row with no id; not ended (no process) nor held (its job is done)
        self.assertIn("2 managed · 1 watched · 2 active · 0 new", self.guide_title())

    def test_workers_and_retired_guides_get_no_sweep(self):
        self.transcript("44444444-0000-4000-8000-000000000000", "new one")
        self.run_script("guided", WORKER)
        self.assertNotIn("additionalContext", self.hook(WORKER, title="billing lead").stdout)
        self.run_script("retire", GUIDE)
        context = self.extra_context()
        self.assertNotIn("new one", context)
        self.assertIn("RETIRED guide", context)  # its only context: it is retired

    def test_active_session_gets_the_blue_blocks(self):
        self.assertEqual(self.run_script("active", WORKER).returncode, 0)
        self.assertEqual(self.worker_title("notes cleanup"), "🟦🟦 notes cleanup")
        self.assertIsNone(self.worker_title("🟦🟦 notes cleanup"))
        self.run_script("watched", WORKER)
        self.assertEqual(self.worker_title("🟦🟦 notes cleanup"), "⬜⬜ notes cleanup")
        self.run_script("active", WORKER)
        self.assertEqual(self.worker_title("🟧🟧 (g) notes cleanup"), "🟦🟦 notes cleanup")
        self.assertEqual(self.worker_title("notes", SESSION_GUIDE_ACTIVE_PREFIX="[a] "), "[a] notes")
        self.run_script("unguided", WORKER)
        self.assertEqual(self.worker_title("🟦🟦 notes cleanup"), "notes cleanup")

    def test_active_refuses_guides_retired_guides_and_closed_sessions(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        self.assertNotEqual(self.run_script("active", GUIDE).returncode, 0)
        self.run_script("retire", GUIDE)
        self.assertNotEqual(self.run_script("active", GUIDE).returncode, 0)
        self.run_script("done", WORKER)
        self.assertNotEqual(self.run_script("active", WORKER).returncode, 0)

    def test_title_placeholders(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        self.assertEqual(self.guide_title(SESSION_GUIDE_TITLE="{managed}/{watched}/{active}/{new} of {tracked}"),
                         "2/1/0/0 of 3")

    def test_title_names_the_ledger_slug_and_host(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        host = socket.gethostname().split(".")[0]
        self.assertEqual(self.guide_title(SESSION_GUIDE_TITLE="{slug} on {host}: {managed}"),
                         "release-2026-10-27 on %s: 2" % host)
        self.assertTrue(self.guide_title().startswith("🟥🟥 Sessions Manager · release-2026-10-27 ("))
        # a custom title from before {slug} and {host} existed still renders
        self.assertEqual(self.guide_title(SESSION_GUIDE_TITLE="🟥🟥 Sessions Manager · hub ({managed} managed) 🟥🟥"),
                         "🟥🟥 Sessions Manager · hub (2 managed) 🟥🟥")

    def test_done_session_gets_the_check_prefix_in_place_of_g(self):
        self.run_script("guided", WORKER)
        self.assertEqual(self.run_script("done", WORKER).returncode, 0)
        for event in ("UserPromptSubmit", "SessionStart"):
            self.assertEqual(self.worker_title("(g) billing lead · PR merged", event), "✅ billing lead · PR merged")
        self.assertIsNone(self.worker_title("✅ billing lead · PR merged"))  # already right: no output
        self.assertEqual(self.worker_title("✅ (g) ✅ billing lead"), "✅ billing lead")
        self.assertEqual(self.worker_title("🟧🟧 (g) billing lead"), "✅ billing lead")
        self.assertEqual(self.worker_title("⬜⬜ billing lead"), "✅ billing lead")
        self.assertEqual(self.worker_title("billing lead", SESSION_GUIDE_DONE_PREFIX="[done] "), "[done] billing lead")
        self.assertEqual(self.run_script("done", WORKER).returncode, 0)  # a repeat is harmless
        with open(os.path.join(self.cfg, "session-guide", "guides", WORKER)) as f:
            self.assertEqual(f.read(), "done\n")

    def test_done_is_never_g_or_red_again(self):
        self.run_script("done", WORKER)
        self.assertNotEqual(self.run_script("guided", WORKER).returncode, 0)
        self.assertNotEqual(self.run_script("mark", self.ledger, "--session", WORKER).returncode, 0)
        self.assertEqual(self.run_script("unguided", WORKER).returncode, 0)  # left as it is
        self.assertEqual(self.worker_title("billing lead"), "✅ billing lead")

    def test_done_refuses_guides_and_empty_ids(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        self.assertNotEqual(self.run_script("done", GUIDE).returncode, 0)
        self.assertEqual(self.guide_title(), TITLE)
        self.run_script("retire", GUIDE)
        self.assertNotEqual(self.run_script("done", GUIDE).returncode, 0)
        self.assertIn("(retired)", self.hook().stdout)
        self.assertNotEqual(self.run_script("done", "", CLAUDE_CODE_SESSION_ID=WORKER).returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.cfg, "session-guide", "guides", WORKER)))

    def test_closed_sessions_and_repeated_rows_do_not_count(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        with open(self.ledger, "w") as f:  # topmost row wins; a closed session's rows are skipped; no id counts
            f.write(LEDGER.replace("| old lead [c1c1c1] |", "| search reindex again [a1a1a1deadbeef] | DONE | x | | | | |\n"
                                   "| search reindex old [a1a1a1] | MANAGED | x | | | | |\n| old lead [c1c1c1] |")
                    .replace("| personal notes [e8f9a0] | IGNORED", "| no id here | MANAGED | x | | | | |\n| personal notes [e8f9a0] | IGNORED"))
        # billing, search reindex (its topmost row; the two rows below it are skipped) and the row with no id
        self.assertEqual(self.guide_title(), "🟥🟥 Sessions Manager · release-2026-10-27 (3 managed · 1 watched · 0 active · 0 new) 🟥🟥")
        os.makedirs(os.path.join(self.cfg, "session-guide", "guides"), exist_ok=True)
        self.run_script("done", "3fa9c100-0000-4000-8000-000000000000")
        self.assertEqual(self.guide_title(), "🟥🟥 Sessions Manager · release-2026-10-27 (2 managed · 1 watched · 0 active · 0 new) 🟥🟥")

    def test_newest_row_level_wins_when_two_rows_name_one_session(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        with open(self.ledger, "w") as f:
            f.write(LEDGER.replace("| billing export lead [3fa9c1] | MANAGED", "| billing export lead [3fa9c1] | DONE (merged)\n"
                                   "| billing export lead [3fa9c1] | MANAGED"))
        self.assertEqual(self.guide_title(), "🟥🟥 Sessions Manager · release-2026-10-27 (1 managed · 1 watched · 0 active · 0 new) 🟥🟥")

    def test_done_sets_the_row_level_in_the_guide_ledger(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        before = open(self.ledger).read()
        r = self.run_script("done", "3fa9c100-0000-4000-8000-000000000000", CLAUDE_CODE_SESSION_ID=GUIDE)
        self.assertEqual(r.returncode, 0)
        self.assertIn("1 row(s)", r.stdout)
        self.assertEqual(open(self.ledger).read(),
                         before.replace("[3fa9c1] | MANAGED | billing lead", "[3fa9c1] | DONE | billing lead"))
        self.assertIn("(1 managed", self.guide_title())

    def test_done_without_a_findable_ledger_still_closes_and_says_so(self):
        r = self.run_script("done", WORKER)
        self.assertEqual(r.returncode, 0)
        self.assertIn("yourself", r.stdout)
        with open(os.path.join(self.cfg, "session-guide", "guides", WORKER)) as f:
            self.assertEqual(f.read(), "done\n")

    def job(self, sid, name, alive=False):
        """A job state.json for sid, and a sessions/<pid>.json that is alive (this test process) or dead."""
        d = os.path.join(self.cfg, "jobs", sid[:8])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "state.json"), "w") as f:
            json.dump({"state": "done", "name": name, "sessionId": sid, "intent": "keep"}, f)
        os.makedirs(os.path.join(self.cfg, "sessions"), exist_ok=True)
        with open(os.path.join(self.cfg, "sessions", "1.json"), "w") as f:
            json.dump({"pid": os.getpid() if alive else 2 ** 22 + 12345, "sessionId": sid}, f)
        return os.path.join(d, "state.json")

    def test_done_retitles_the_job_of_a_session_with_no_process(self):
        path = self.job(WORKER, "🟧🟧 (g) billing lead · Waiting on CI")
        self.run_script("guided", WORKER)
        r = self.run_script("done", WORKER)
        self.assertIn("state.json", r.stdout)
        state = json.load(open(path))
        self.assertEqual((state["name"], state["state"], state["intent"]), ("✅ billing lead · Waiting on CI", "done", "keep"))
        self.assertEqual(self.run_script("done", WORKER).returncode, 0)  # a repeat changes nothing
        self.assertEqual(json.load(open(path))["name"], "✅ billing lead · Waiting on CI")

    def test_done_leaves_the_job_of_a_live_session_to_its_next_prompt(self):
        path = self.job(WORKER, "🟧🟧 (g) billing lead", alive=True)
        r = self.run_script("done", WORKER)
        self.assertIn("next prompt", r.stdout)
        self.assertEqual(json.load(open(path))["name"], "🟧🟧 (g) billing lead")
        self.assertEqual(self.worker_title("🟧🟧 (g) billing lead"), "✅ billing lead")  # resumed: follows the marker

    def test_guide_prompt_renames_a_closed_session_once_its_process_has_ended(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        path = self.job(WORKER, "🟧🟧 (g) billing lead", alive=True)
        self.run_script("done", WORKER)  # the process is alive: nothing renamed yet
        self.assertEqual(json.load(open(path))["name"], "🟧🟧 (g) billing lead")
        context = json.loads(self.hook().stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("CLOSE message: " + WORKER[:8], context)
        self.assertIn("Held: [%s]" % WORKER[:8], self.run_script("sweep", CLAUDE_CODE_SESSION_ID=GUIDE).stdout)
        self.assertEqual(json.load(open(path))["name"], "🟧🟧 (g) billing lead")  # a live process is never edited
        self.job(WORKER, "🟧🟧 (g) billing lead")  # the process ended
        self.assertNotIn("CLOSE message", self.hook().stdout)
        self.assertEqual(json.load(open(path))["name"], "✅ billing lead")

    def test_a_held_session_with_a_plain_title_is_not_worth_a_message(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        path = self.job(WORKER, "billing lead", alive=True)
        self.run_script("done", WORKER)
        self.assertNotIn("Held", self.run_script("sweep", CLAUDE_CODE_SESSION_ID=GUIDE).stdout)
        self.assertEqual(json.load(open(path))["name"], "billing lead")
        self.job(WORKER, "billing lead")  # the process ended
        self.run_script("sweep", CLAUDE_CODE_SESSION_ID=GUIDE)
        self.assertEqual(json.load(open(path))["name"], "✅ billing lead")

    def test_sweep_renames_sessions_closed_before_done_could_rename(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        path = self.job(WORKER, "🟧🟧 (g) billing lead")
        with open(os.path.join(self.cfg, "session-guide", "guides", WORKER), "w") as f:
            f.write("done\n")
        self.assertNotIn("Held", self.run_script("sweep", CLAUDE_CODE_SESSION_ID=GUIDE).stdout)
        self.assertEqual(json.load(open(path))["name"], "✅ billing lead")

    def test_a_worker_prompt_settles_nothing(self):
        path = self.job(WORKER, "🟧🟧 (g) billing lead")
        os.makedirs(os.path.join(self.cfg, "session-guide", "guides"), exist_ok=True)
        with open(os.path.join(self.cfg, "session-guide", "guides", WORKER), "w") as f:
            f.write("done\n")
        self.hook(session_id=GUIDE)  # GUIDE has no marker here: not a guide
        self.assertEqual(json.load(open(path))["name"], "🟧🟧 (g) billing lead")

    def test_a_job_that_is_only_done_is_not_closed(self):
        path = self.job(WORKER, "🟧🟧 (g) billing lead")
        self.run_script("guided", WORKER)
        self.assertEqual(open(os.path.join(self.cfg, "session-guide", "guides", WORKER)).read(), "guided\n")
        self.assertEqual(json.load(open(path))["name"], "🟧🟧 (g) billing lead")

    def test_sweep_offers_sessions_whose_rows_are_all_done_but_still_marked(self):
        self.run_script("mark", self.ledger, "--session", GUIDE)
        self.run_script("guided", "3fa9c100-0000-4000-8000-000000000000")
        self.run_script("guided", "a1a1a100-0000-4000-8000-000000000000")
        with open(self.ledger, "w") as f:
            f.write(LEDGER.replace("[3fa9c1] | MANAGED", "[3fa9c1] | DONE"))
        r = self.run_script("sweep", CLAUDE_CODE_SESSION_ID=GUIDE)
        self.assertIn("Closable: [3fa9c100]", r.stdout)
        self.assertNotIn("a1a1a100", r.stdout)
        self.assertIn("done <id>", json.loads(self.hook().stdout)["hookSpecificOutput"]["additionalContext"])
        self.run_script("done", "3fa9c100-0000-4000-8000-000000000000", CLAUDE_CODE_SESSION_ID=GUIDE)
        self.assertNotIn("Closable", self.run_script("sweep", CLAUDE_CODE_SESSION_ID=GUIDE).stdout)


class ThroughputTest(GuideTitleBase):
    """0.1.22: fewer dialogs while workers run, bookkeeping defaults, one-call closes."""
    BILLING = "3fa9c100-0000-4000-8000-000000000000"
    SEARCH = "a1a1a100-0000-4000-8000-000000000000"
    SPIKE = "b5c6d700-0000-4000-8000-000000000000"

    def setUp(self):
        super().setUp()
        self.keep_open_rows_alive()
        self.assertEqual(self.run_script("mark", self.ledger, "--session", GUIDE).returncode, 0)

    def hook_text(self, **env):
        out = self.hook(**env).stdout
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    # -- section 1: workers working right now
    def test_the_hook_says_who_is_working_and_how_to_ask_meanwhile(self):
        self.run_job(self.BILLING)
        self.run_job(self.SEARCH, alive=False)  # state working, but no process: not working
        self.run_job(self.SPIKE)  # WATCHED: its reports do not queue the guide
        text = self.hook_text()
        self.assertIn("session-guide workers: 1 MANAGED worker(s) working right now (billing export lead [3fa9c1]). "
                      "Their reports queue while a dialog is open.", text)
        self.assertIn("ONE question in the call", text)
        self.assertIn("**Needs you now**", text)
        self.assertIn("`needs input: <what>`", text)
        self.assertIn("`waiting ask` row", text)
        self.assertNotIn("search reindex", text.split("session-guide workers:")[1].split("\n")[0])
        self.assertNotIn("design spike", text.split("session-guide workers:")[1].split("\n")[0])
        self.assertNotIn("holds nobody up", text)

    def test_an_interactive_session_with_no_job_counts_while_its_transcript_moves(self):
        self.run_job(self.BILLING, state="")  # a live process, but no job state: an interactive session
        self.transcript(self.BILLING, age=10)
        self.assertIn("1 MANAGED worker(s) working right now (billing export lead [3fa9c1])", self.hook_text())
        self.transcript(self.BILLING, age=gt.WORKING_QUIET_SECONDS + 60)  # quiet for a while: not working
        self.assertIn(IDLE_WORKERS, self.hook_text())
        self.run_job(self.BILLING, state="done")  # an explicit state other than working stays out
        self.transcript(self.BILLING, age=10)
        self.assertIn(IDLE_WORKERS, self.hook_text())

    def test_with_nobody_working_the_full_interview_holds_nobody_up(self):
        self.run_job(self.BILLING, state="done")
        self.assertIn(IDLE_WORKERS, self.hook_text())
        self.assertNotIn("working right now (", self.hook_text())
        self.run_script("done", self.BILLING)  # a closed session never counts as working
        self.run_job(self.BILLING)
        self.assertIn(IDLE_WORKERS, self.hook_text())

    def test_the_working_command_prints_each_worker_and_the_hook_sentence(self):
        self.run_job(self.BILLING)
        self.run_job(self.SEARCH)
        out = self.run_ok("working", self.ledger)
        self.assertIn("Working: billing export lead [3fa9c1]\n", out)
        self.assertIn("Working: search reindex [a1a1a1]\n", out)
        self.assertIn("2 MANAGED worker(s) working right now (billing export lead [3fa9c1], search reindex [a1a1a1])", out)
        os.remove(os.path.join(self.cfg, "jobs", self.BILLING[:8], "state.json"))
        os.remove(os.path.join(self.cfg, "jobs", self.SEARCH[:8], "state.json"))
        for sid in (self.BILLING, self.SEARCH):  # and no process: neither is working
            os.remove(os.path.join(self.cfg, "sessions", sid[:8] + ".json"))
        self.assertEqual(self.run_ok("working", self.ledger), IDLE_WORKERS + "\n")

    def test_the_hook_names_six_workers_at_most(self):
        rows = "".join("| lead %d [%06x] | MANAGED | x | | | | |\n" % (n, 0xabc000 + n) for n in range(8))
        open(self.ledger, "w").write(LEDGER.replace("| old lead [c1c1c1]", rows + "| old lead [c1c1c1]"))
        for n in range(8):
            sid = "%06x00-0000-4000-8000-000000000000" % (0xabc000 + n)
            self.transcript(sid)
            self.run_job(sid)
        text = self.hook_text()
        self.assertIn("8 MANAGED worker(s) working right now", text)
        self.assertIn("lead 5 [abc005], and 2 more)", text)
        self.assertNotIn("lead 6 [abc006]", text)

    # -- section 2: bookkeeping defaults
    def sessions_rows(self):
        text = open(self.ledger).read().split("## Sessions\n")[1].split("\n\n")[0]
        return [l for l in text.splitlines() if l.startswith("|")]

    def test_sweep_defaults_levels_old_sessions_and_only_names_young_ones(self):
        old, guided, watched, young, nostamp = ("aa00%dee-0000-4000-8000-000000000000" % n for n in range(51, 56))
        for sid, title in ((old, "old one"), (guided, "guided one"), (watched, "watched one")):
            self.transcript(sid, title, started=time.time() - 40 * 60)
        self.transcript(young, "young one", started=time.time() - 60)
        self.transcript(nostamp, "no stamp")  # no timestamp: its file's birth, which is now
        self.run_script("guided", guided)
        self.run_script("watched", watched)
        out = self.run_ok("sweep", self.ledger, "--defaults", CLAUDE_CODE_SESSION_ID=GUIDE)
        self.assertIn("Defaulted: 'old one' [aa0051ee] -> ACTIVE\n", out)
        self.assertIn("Defaulted: 'guided one' [aa0052ee] -> MANAGED\n", out)
        self.assertIn("Defaulted: 'watched one' [aa0053ee] -> WATCHED\n", out)
        self.assertRegex(out, r"New: 'young one' \[aa0054ee\] defaults to ACTIVE at \d\d:\d\d\n")
        self.assertRegex(out, r"New: 'no stamp' \[aa0055ee\] defaults to ACTIVE at \d\d:\d\d\n")
        markers = {sid[:8]: open(os.path.join(self.cfg, "session-guide", "guides", sid)).read().strip()
                   for sid in (old, guided, watched)}
        self.assertEqual(markers, {"aa0051ee": "active", "aa0052ee": "guided", "aa0053ee": "watched"})
        self.assertFalse(os.path.exists(os.path.join(self.cfg, "session-guide", "guides", young)))
        rows = self.sessions_rows()
        header = rows[0].count("|")
        mine = {r.split("[")[1][:6]: r for r in rows if "[aa00" in r}
        self.assertEqual(sorted(mine), ["aa0051", "aa0052", "aa0053"])
        self.assertEqual({r.count("|") for r in rows}, {header})  # padded to the header's columns
        self.assertRegex(mine["aa0051"], r"^\| 'old one' \[aa0051\] \| ACTIVE \| default level \d{4}-\d\d-\d\d \d\d:\d\d "
                                         r"\(no word in 15 min\) \| +\| +\| +\| +\|$")
        self.assertIn("| MANAGED |", mine["aa0052"])
        self.assertIn("| WATCHED |", mine["aa0053"])
        self.assertIn("· 2 new", self.guide_title())  # only the young ones still count
        again = self.run_ok("sweep", self.ledger, "--defaults", CLAUDE_CODE_SESSION_ID=GUIDE)  # nothing left to default
        self.assertNotIn("Defaulted", again)
        self.assertEqual(len(self.sessions_rows()), len(rows))

    def test_describe_names_a_guided_or_watched_marker(self):
        found = dict(title="x", id="aa0051ee-0000", age=60)
        self.assertEqual(gt.describe(dict(found, marker=gt.GUIDED)), "'x' [aa0051ee], active 1m ago, marked guided")
        self.assertEqual(gt.describe(dict(found, marker=gt.WATCHED)), "'x' [aa0051ee], active 1m ago, marked watched")
        self.assertEqual(gt.describe(dict(found, marker="")), "'x' [aa0051ee], active 1m ago")

    def test_sweep_defaults_with_minutes_zero_keeps_the_plain_listing(self):
        self.transcript("aa0051ee-0000-4000-8000-000000000000", "old one", started=time.time() - 3600)
        out = self.run_ok("sweep", self.ledger, "--defaults", SESSION_GUIDE_NEW_SESSION_MINUTES="0",
                          CLAUDE_CODE_SESSION_ID=GUIDE)
        self.assertEqual(out, "'old one' [aa0051ee], active 0m ago\nNew: 1\n")
        self.assertNotIn("[aa0051]", open(self.ledger).read())
        self.assertEqual(self.run_ok("sweep", self.ledger, CLAUDE_CODE_SESSION_ID=GUIDE), out)  # plain sweep unchanged

    def test_the_hook_splits_new_sessions_at_the_default_and_asks_nothing(self):
        self.transcript("aa0051ee-0000-4000-8000-000000000000", "old one", started=time.time() - 3600)
        self.transcript("aa0054ee-0000-4000-8000-000000000000", "young one", started=time.time() - 60)
        text = self.hook_text()
        old, young = [p for p in text.split("session-guide sweep: ") if "session(s) active" in p]
        self.assertIn("'old one' [aa0051ee]", old)
        self.assertNotIn("young one", old)
        self.assertIn("sweep --defaults`: each gets its default level and a row; tell the user in ONE text line, ask "
                      "nothing. A level the user names wins.", old)
        self.assertIn("'young one' [aa0054ee]", young)
        self.assertRegex(young, r"ACTIVE at \d\d:\d\d")
        self.assertIn("takes its default level at the time shown unless the user says otherwise: name them in your "
                      "text, ask nothing.", young)
        self.assertNotIn("AskUserQuestion (Manage", text)
        off = self.hook_text(SESSION_GUIDE_NEW_SESSION_MINUTES="0")
        self.assertIn("AskUserQuestion (Manage / Watch / Leave active / Ignore)", off)
        self.assertNotIn("sweep --defaults", off)

    def test_sleep_takes_its_hours_from_the_env_or_two(self):
        self.run_ok("waiting", self.BILLING, "Merge #142")
        for env, hours in (({}, 2), ({"SESSION_GUIDE_SLEEP_HOURS": "5"}, 5)):
            out = self.run_ok("sleep", self.BILLING, **env)
            want = time.strftime("%Y-%m-%d %H", time.localtime(time.time() + hours * 3600))
            self.assertIn("3fa9c1 sleeps until " + want, out)
        self.assertNotEqual(self.run_script("sleep").returncode, 0)  # nothing named, no --due
        self.assertNotEqual(self.run_script("sleep", self.BILLING, "--due").returncode, 0)

    def test_sleep_due_puts_off_every_due_reminder_and_leaves_the_rest(self):
        self.run_ok("waiting", self.BILLING, "Merge #142")
        self.run_ok("waiting", "ask", "Which export format?")
        self.run_ok("waiting", self.SEARCH, "Review the index")
        self.run_ok("sleep", self.SEARCH, "24")  # asleep already: not due
        out = self.run_ok("sleep", "--due")
        want = time.strftime("%Y-%m-%d %H", time.localtime(time.time() + 2 * 3600))
        self.assertEqual(out.count("sleeps until " + want), 2)
        self.assertNotIn("a1a1a1 sleeps", out)
        self.assertEqual(self.hook_text().count("reminder(s) due"), 0)
        self.assertIn("Asleep until %s" % time.strftime("%Y-%m-%d %H", time.localtime(time.time() + 24 * 3600)),
                      self.run_ok("settle", self.ledger))
        self.assertIn("No reminder is due", self.run_ok("sleep", "--due", "3"))
        self.run_ok("waiting", self.BILLING, "Merge #143")  # a waiting row again: due now (keeps its old sleep)
        text = open(self.ledger).read()
        open(self.ledger, "w").write(text.replace(want[:13], "2020-01-01 09"))
        out = self.run_ok("sleep", "--due", "3")  # hours may follow --due
        self.assertIn("sleeps until " + time.strftime("%Y-%m-%d %H", time.localtime(time.time() + 3 * 3600)), out)

    def test_sleep_due_skips_a_reminder_the_audit_found_likely_done(self):
        self.run_ok("waiting", self.BILLING, "Merge #142")
        self.run_ok("waiting", self.SEARCH, "Review the index")
        with open(os.path.join(os.path.dirname(self.ledger), "audit.json"), "w") as f:
            json.dump({"quick": {"reminders": {"3fa9c1": "likely done: a later row covers it. Do not ask the user."}}}, f)
        out = self.run_ok("sleep", "--due")
        self.assertIn("a1a1a1 sleeps until", out)
        self.assertNotIn("3fa9c1 sleeps", out)
        text = open(self.ledger).read()
        self.assertIn("Merge #142", text)
        self.assertEqual(self.run_ok("sleep", "--due").count("sleeps until"), 0)  # the covered one is still not put off

    def test_the_due_reminder_text_asks_one_tick_question_and_defers_the_rest(self):
        self.run_ok("waiting", self.BILLING, "Merge #142")
        text = self.hook_text()
        self.assertIn('ONE multi-select question for the round ("Tick what is settled")', text)
        self.assertIn('"Done: <action>"', text)
        self.assertIn("sleep --due` puts every one of them off by the default, with no second question", text)
        self.assertIn("Change it / Drop it come as the user's own words", text)
        self.assertIn("While workers are working, this list goes in your text, not a dialog.", text)

    def test_results_defer_keeps_each_rows_cadence_and_never_writes_a_verdict(self):
        open(self.ledger, "a").write("\n## Open items\n| Item | Owner |\n|---|---|\n\n## Log (last ~15)\n- x\n")
        link = "https://claude.ai/artifact/abc123"
        for name in ("deck slide 4", "review doc", "release note", "closing note"):
            self.run_ok("result", name, link)
        self.run_ok("result-answer", "review doc", "not-looked", "--every", "4")
        self.run_ok("result-answer", "closing note", "satisfied")
        text = open(self.ledger).read()
        open(self.ledger, "w").write(text.replace(
            time.strftime("%Y-%m-%d %H", time.localtime(time.time() + 4 * 3600)), "2020-01-01 09"))  # review doc is due
        before = open(self.ledger).read()
        out = self.run_ok("results-defer")
        after = open(self.ledger).read()
        for name, every in (("deck slide 4", 1), ("review doc", 4), ("release note", 1)):
            at = time.strftime("%Y-%m-%d %H", time.localtime(time.time() + every * 3600))
            self.assertRegex(after, r"\| %s \| %s \| [^|]+ \| [^|]+ \| not looked yet; ask again %s:\d\d \(every %d h\) \|"
                             % (name, re.escape(link), at, every))
            self.assertIn(name + ": not looked yet; ask again " + at, out)
        self.assertIn("| satisfied 20", after)
        self.assertEqual([l for l in after.splitlines() if "closing note" in l], [l for l in before.splitlines() if "closing note" in l])
        for verdict in ("change it", "dropped"):
            self.assertNotIn(verdict, after)
        self.assertEqual(after.count("satisfied"), 1)  # only the user's own answer
        self.assertIn("No result is due", self.run_ok("results-defer"))

    def test_the_results_text_defers_what_is_not_ticked(self):
        open(self.ledger, "a").write("\n## Open items\n| Item | Owner |\n|---|---|\n\n## Log (last ~15)\n- x\n")
        self.run_ok("result", "deck slide 4", "https://claude.ai/artifact/abc123")
        text = self.hook_text()
        self.assertIn('"Satisfied: <deliverable>"', text)
        self.assertIn("results-defer` asks again at each row's own cadence", text)
        self.assertIn("only on the user's Satisfied", text)

    def test_done_closable_closes_every_session_with_only_done_rows(self):
        for sid in (self.BILLING, self.SEARCH):
            self.run_ok("guided", sid)
        self.assertIn("Nothing closable", self.run_ok("done", "--closable"))
        open(self.ledger, "w").write(LEDGER.replace("[3fa9c1] | MANAGED", "[3fa9c1] | DONE"))
        self.run_ok("waiting", "ask", "Which export format?")
        out = self.run_ok("done", "--closable")
        self.assertIn("Closing [3fa9c100]", out)
        self.assertIn("3fa9c100 is closed", out)
        self.assertNotIn("a1a1a100", out)
        self.assertEqual(open(os.path.join(self.cfg, "session-guide", "guides", self.BILLING)).read(), "done\n")
        self.assertEqual(open(os.path.join(self.cfg, "session-guide", "guides", self.SEARCH)).read(), "guided\n")
        self.assertIn("Nothing closable", self.run_ok("done", "--closable"))
        self.assertNotEqual(self.run_script("done", self.SEARCH, "--closable").returncode, 0)
        self.assertEqual(self.run_ok("done", self.SEARCH).count("is closed"), 1)  # plain done is unchanged

    def test_the_closable_text_names_done_closable(self):
        self.run_ok("guided", self.BILLING)
        open(self.ledger, "w").write(LEDGER.replace("[3fa9c1] | MANAGED", "[3fa9c1] | DONE"))
        self.assertIn("done --closable` to close them all: 3fa9c100", self.hook_text())


class SettleTest(GuideTitleBase):
    """Every MANAGED or WATCHED session ends waiting on the user or done, and a reminder can sleep."""
    QUIET = "3fa9c100-0000-4000-8000-000000000000"

    def setUp(self):
        super().setUp()
        self.keep_open_rows_alive()
        self.assertEqual(self.run_script("mark", self.ledger, "--session", GUIDE).returncode, 0)

    def settle(self):
        r = self.run_script("settle", self.ledger)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return r.stdout

    def context(self):
        out = self.hook().stdout
        return without_now(json.loads(out)["hookSpecificOutput"].get("additionalContext", "")) if out else ""

    def set_remind(self, value):
        lines = open(self.ledger).read().splitlines(True)
        at = next(i for i, l in enumerate(lines) if l.startswith("| billing export lead") and l.count("|") == 5)
        cells = lines[at].split(" | ")
        cells[-1] = value + " |\n"
        lines[at] = " | ".join(cells)
        open(self.ledger, "w").write("".join(lines))

    def test_quiet_session_is_unsettled_until_it_waits_or_closes(self):
        self.assertEqual(self.settle(), "0 unsettled, 0 due, 0 asleep\n")
        self.transcript(self.QUIET, age=3 * 3600)
        self.assertIn("Unsettled: billing export lead [3fa9c1], MANAGED: quiet 3 h", self.settle())
        self.assertIn("billing export lead [3fa9c1]", self.context())
        self.assertEqual(self.run_script("waiting", self.QUIET, "Merge #142").returncode, 0)
        self.assertNotIn("Unsettled", self.settle())
        self.assertIn("Due: billing export lead [3fa9c1]: Merge #142", self.settle())
        self.assertEqual(self.run_script("done", self.QUIET).returncode, 0)
        self.assertEqual(self.settle(), "0 unsettled, 0 due, 0 asleep\n")
        self.assertNotIn("Merge #142", open(self.ledger).read())

    def test_quiet_watched_counts_but_ignored_and_handed_off_do_not(self):
        self.transcript("b5c6d700-0000-4000-8000-000000000000", age=5 * 3600)
        self.transcript("e8f9a000-0000-4000-8000-000000000000", age=5 * 3600)
        self.transcript("c1c1c100-0000-4000-8000-000000000000", age=5 * 3600)
        out = self.settle()
        self.assertIn("design spike [b5c6d7], WATCHED", out)
        self.assertTrue(out.endswith("1 unsettled, 0 due, 0 asleep\n"), out)

    def test_running_session_is_not_unsettled_and_a_gone_one_is(self):
        self.transcript(self.QUIET, age=3 * 3600)
        os.makedirs(os.path.join(self.cfg, "sessions"))
        os.makedirs(os.path.join(self.cfg, "jobs", self.QUIET[:8]))
        with open(os.path.join(self.cfg, "sessions", "1.json"), "w") as f:
            json.dump({"sessionId": self.QUIET, "pid": os.getpid()}, f)
        with open(os.path.join(self.cfg, "jobs", self.QUIET[:8], "state.json"), "w") as f:
            json.dump({"state": "working"}, f)
        self.assertNotIn("Unsettled", self.settle())
        os.remove(os.path.join(self.cfg, "projects", "-tmp-repo", self.QUIET + ".jsonl"))
        self.assertIn("transcript is gone", self.settle())

    def test_every_offered_sleep_moves_the_reminder_and_silences_it(self):
        self.assertEqual(self.run_script("waiting", self.QUIET, "Merge #142").returncode, 0)
        self.assertIn("1 reminder(s) due", self.context())
        for hours in (1, 2, 8, 12, 24, 48):
            r = self.run_script("sleep", self.QUIET, str(hours))
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            want = time.strftime("%Y-%m-%d %H", time.localtime(time.time() + hours * 3600))
            self.assertIn("Asleep until " + want, self.settle())
            self.assertIn("Next reminder: " + want, self.settle())
        self.assertEqual(self.context(), "")

    def test_sleep_refuses_nonsense_and_sessions_with_no_reminder(self):
        self.assertNotEqual(self.run_script("sleep", self.QUIET, "2").returncode, 0)
        self.run_script("waiting", self.QUIET, "Merge #142")
        self.assertNotEqual(self.run_script("sleep", self.QUIET, "0").returncode, 0)

    def test_reminder_comes_due_again_and_an_unreadable_time_is_due(self):
        self.run_script("waiting", self.QUIET, "Merge #142")
        self.run_script("sleep", self.QUIET, "1")
        self.set_remind("2020-01-01 09:00")
        self.assertIn("Due: billing export lead", self.settle())
        self.set_remind("whenever")
        self.assertIn("Due: billing export lead", self.settle())

    def test_repeat_waiting_keeps_asked_and_a_sleeping_reminder(self):
        self.run_script("waiting", self.QUIET, "Merge #142")
        self.run_script("sleep", self.QUIET, "8")
        self.run_script("waiting", self.QUIET, "Merge #143 instead")
        out = self.settle()
        self.assertIn("Asleep until", out)
        self.assertIn("Merge #143 instead", out)

    def test_pipes_survive_the_table_and_a_sleep(self):
        command = "! for i in a b; do claude stop $i; done | tail -1"
        self.run_script("waiting", self.QUIET, command)
        self.assertIn("\\| tail -1", open(self.ledger).read())
        self.assertIn(command, self.context())
        self.run_script("sleep", self.QUIET, "1")
        self.assertIn(command, self.settle())
        self.assertEqual(open(self.ledger).read().count("\\\\|"), 0)

    def test_existing_bullets_stay_and_unwait_removes_only_the_row(self):
        text = open(self.ledger).read() + "\n## Waiting on Jonathan\n- File the ticket.\n\n## Open items\n| Item | Owner |\n"
        open(self.ledger, "w").write(text)
        self.run_script("waiting", self.QUIET, "Merge #142")
        ledger = open(self.ledger).read()
        self.assertEqual(ledger.count("## Waiting on"), 1)
        self.assertLess(ledger.index("Merge #142"), ledger.index("- File the ticket."))
        self.assertLess(ledger.index("- File the ticket."), ledger.index("## Open items"))
        self.assertEqual(self.run_script("unwait", self.QUIET).returncode, 0)
        ledger = open(self.ledger).read()
        self.assertNotIn("Merge #142", ledger)
        self.assertIn("- File the ticket.", ledger)

    def test_section_is_added_before_open_items_when_missing(self):
        open(self.ledger, "a").write("\n## Open items\n| Item | Owner |\n")
        self.run_script("waiting", self.QUIET, "Merge #142")
        ledger = open(self.ledger).read()
        self.assertLess(ledger.index("## Waiting on the user"), ledger.index("## Open items"))

    def test_a_row_quoting_another_ref_is_read_as_the_session_with_a_transcript(self):
        lines = open(self.ledger).read().replace("| design spike [b5c6d7] |", "| design spike [b5c6d7] (ListAgents [fa18dd]) |")
        open(self.ledger, "w").write(lines)
        self.assertEqual(self.settle(), "0 unsettled, 0 due, 0 asleep\n")
        session = "b5c6d700-0000-4000-8000-000000000000"
        self.transcript(session, age=3 * 3600)
        self.assertIn("quiet 3 h", self.settle())
        self.assertEqual(self.run_script("waiting", session, "Merge #142").returncode, 0)

    def test_waiting_refuses_a_session_with_no_open_row(self):
        self.transcript(WORKER)
        self.assertIn("no open row", self.run_script("waiting", WORKER, "Merge #142").stderr)

    def test_an_owed_question_is_a_reminder_that_survives_a_handoff(self):
        question = "twin plan link model + exterior areas (from 'twin plan' [a1b2c3])"
        r = self.run_script("waiting", "ask", question, "--hours", "3")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        key = re.search(r"owed question \[([0-9a-f]{6})\]", r.stdout).group(1)
        want = time.strftime("%Y-%m-%d %H", time.localtime(time.time() + 3 * 3600))
        out = self.settle()
        self.assertIn("Asleep until %s" % want, out)
        self.assertIn("owed question [%s]: %s" % (key, question), out)
        self.assertIn("Next reminder: " + want, out)
        self.assertEqual(self.context(), "")
        # a fresh guide reads the same ledger: once the time has come, the question is due on its prompt
        lines = open(self.ledger).read().replace(want, "2020-01-01 09")
        open(self.ledger, "w").write(lines)
        self.assertIn("Due: owed question [%s]: %s" % (key, question), self.settle())
        self.assertIn(question, self.context())
        self.assertEqual(self.run_script("sleep", key, "2").returncode, 0)
        self.assertNotIn("Due:", self.settle())
        self.assertEqual(self.run_script("unwait", key).returncode, 0)
        self.assertNotIn(question, open(self.ledger).read())

    def test_an_owed_question_is_due_now_by_default_or_at_a_time_and_keeps_one_row(self):
        self.assertEqual(self.run_script("waiting", "ask", "Ask: which twin plan link model?").returncode, 0)
        self.assertIn("Due: owed question", self.settle())
        r = self.run_script("waiting", "ask", "Ask: which twin plan link model?", "--at", "2031-05-06 14:00")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn("Asleep until 2031-05-06 14:00", self.settle())
        self.assertEqual(open(self.ledger).read().count("owed question ["), 1)
        self.assertNotEqual(self.run_script("waiting", "ask", "x", "--at", "tomorrow").returncode, 0)
        self.assertNotEqual(self.run_script("waiting", "ask", "x", "--hours", "0").returncode, 0)
        self.assertNotEqual(self.run_script("waiting", self.QUIET, "Merge #142", "--hours", "2").returncode, 0)
        self.assertNotEqual(self.run_script("sleep", "abcdef", "2").returncode, 0)


class ResultsTest(GuideTitleBase):
    """A finished deliverable waits for the user's verdict, and the guide is told until it has one."""
    DECK = "deck slide 4: pricing"
    LINK = "https://claude.ai/artifact/abc123"

    def setUp(self):
        super().setUp()
        self.keep_open_rows_alive()
        self.assertEqual(self.run_script("mark", self.ledger, "--session", GUIDE).returncode, 0)
        open(self.ledger, "a").write("\n## Open items\n| Item | Owner |\n|---|---|\n\n## Log (last ~15)\n- x\n")

    def settle(self):
        r = self.run_script("settle", self.ledger)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return r.stdout

    def context(self):
        out = self.hook().stdout
        return without_now(json.loads(out)["hookSpecificOutput"].get("additionalContext", "")) if out else ""

    def result(self, *args):
        r = self.run_script("result", *args)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return r.stdout

    def answer(self, *args):
        r = self.run_script("result-answer", *args)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return r.stdout

    def test_a_result_is_unanswered_until_the_user_answers_and_the_row_stays(self):
        self.result(self.DECK, self.LINK, "--from", "deck lead [3fa9c1]")
        ledger = open(self.ledger).read()
        self.assertIn("## Results for you\n| Deliverable | Link | Delivered | Asked | Answer |", ledger)
        self.assertLess(ledger.index("## Results for you"), ledger.index("## Open items"))
        self.assertIn("| deck slide 4: pricing (deck lead [3fa9c1]) | %s | " % self.LINK, ledger)
        out = self.settle()
        self.assertIn("Unanswered result: deck slide 4: pricing (deck lead [3fa9c1]) " + self.LINK, out)
        self.assertTrue(out.endswith("0 unsettled, 0 due, 0 asleep, 1 result(s) unanswered\n"), out)
        self.assertIn("1 finished deliverable(s) have no verdict", self.context())
        self.assertIn('ONE multi-select question ("Tick what is settled", option "Satisfied: <deliverable>")',
                      self.context())
        self.assertIn("results-defer", self.context())
        # closing the worker keeps the row: the deliverable, not the session, waits for the answer
        self.assertEqual(self.run_script("done", "3fa9c100-0000-4000-8000-000000000000").returncode, 0)
        self.assertIn("Unanswered result", self.settle())
        self.assertIn("satisfied", self.answer(self.DECK, "satisfied"))
        self.assertNotIn("result", self.settle())
        self.assertEqual(self.context(), "")
        self.assertIn("| satisfied 20", open(self.ledger).read())

    def test_every_answer_form_is_understood(self):
        self.result(self.DECK, self.LINK)
        for given, want in (("Change it", "change it"), ("drop-it", "dropped"), ("haven't looked", "not looked yet"),
                            ("satisfied", "satisfied")):
            self.answer(self.DECK, given)
            self.assertIn("| " + want, open(self.ledger).read())
        self.assertNotEqual(self.run_script("result-answer", self.DECK, "maybe").returncode, 0)
        self.assertNotEqual(self.run_script("result-answer", "no such thing", "satisfied").returncode, 0)
        self.assertNotEqual(self.run_script("result", "", self.LINK).returncode, 0)

    def test_not_looked_asks_again_on_the_cadence_the_user_picks(self):
        self.result(self.DECK, self.LINK)
        self.answer(self.DECK, "not-looked", "--every", "2")
        want = time.strftime("%Y-%m-%d %H", time.localtime(time.time() + 2 * 3600))
        out = self.settle()
        self.assertIn("Result asleep until %s" % want, out)
        self.assertIn("Next reminder: " + want, out)
        self.assertNotIn("Unanswered result", out)
        self.assertEqual(self.context(), "")
        lines = open(self.ledger).read().replace("ask again " + want, "ask again 2020-01-01 09")
        open(self.ledger, "w").write(lines)
        self.assertIn("Unanswered result", self.settle())
        self.assertIn("no verdict", self.context())
        self.answer(self.DECK, "not-looked")  # the cadence is remembered
        self.assertIn("(every 2 h)", open(self.ledger).read())
        self.assertIn("Result asleep until %s" % want, self.settle())
        self.assertNotEqual(self.run_script("result-answer", self.DECK, "not-looked", "--every", "0").returncode, 0)

    def test_a_change_then_a_repeat_result_asks_again_on_the_same_row(self):
        self.result(self.DECK, self.LINK, "--from", "deck lead [3fa9c1]")
        self.answer(self.DECK, "change", "--note", "bigger font")
        self.assertIn("| change it 20", open(self.ledger).read())
        self.assertIn(": bigger font |", open(self.ledger).read())
        self.assertNotIn("result", self.settle())
        self.result(self.DECK, self.LINK + "?v=2")
        ledger = open(self.ledger).read()
        self.assertEqual(ledger.count("deck slide 4"), 1)
        self.assertIn("(deck lead [3fa9c1]) | %s?v=2 | " % self.LINK, ledger)
        self.assertIn("Unanswered result", self.settle())
        self.result("deck slide 5: roadmap", self.LINK)
        self.assertNotEqual(self.run_script("result-answer", "deck slide", "satisfied").returncode, 0)
        self.assertIn("satisfied", self.answer("deck slide 5", "satisfied"))

    def test_a_link_with_a_pipe_survives(self):
        link = "https://example.com/a?x=1|2"
        self.result(self.DECK, link)
        self.assertIn(link, self.settle())
        self.answer(self.DECK, "drop")
        self.assertIn("dropped", open(self.ledger).read())


class FollowupsTest(GuideTitleBase):
    """The guide finds recent fixes and deployments with no verification and records each one it proposes or checks."""
    TODAY = time.strftime("%m-%d")
    OLD = time.strftime("%m-%d", time.localtime(time.time() - 10 * 86400))

    def setUp(self):
        super().setUp()
        self.keep_open_rows_alive()
        self.assertEqual(self.run_script("mark", self.ledger, "--session", GUIDE).returncode, 0)
        open(self.ledger, "a").write(
            "\n## Log (last ~15)\n"
            "- %s 10:0x #142 ON PROD: Deploy to cluster success 10:01Z @abc123.\n"
            "- 10:3x #143 MERGED 09:00Z; #144 not yet merged; asked Jonathan to merge #145.\n"
            "- 10:4x session-guide v1.2.3 tagged and pushed. Branch pushed for #150.\n"
            "- %s #99 ON PROD.\n"
            "| Search | on staging since %s (#160) | audit | — | — |\n" % (self.TODAY, self.OLD, self.TODAY))

    def followups(self, *args):
        r = self.run_script("followups", self.ledger, *args)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return r.stdout

    def verification(self, *args):
        return self.run_script("verification", *args, "--ledger", self.ledger)

    def context(self, **env):
        out = self.hook(**env).stdout
        return without_now(json.loads(out)["hookSpecificOutput"].get("additionalContext", "")) if out else ""

    def assistant_line(self, text, age=0, sidechain=False):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - age))
        return json.dumps({"type": "assistant", "timestamp": stamp, "isSidechain": sidechain,
                           "message": {"content": [{"type": "text", "text": text}]}}) + "\n"

    def test_lists_what_reached_prod_staging_a_merge_or_a_tag_and_skips_plans_and_old_lines(self):
        out = self.followups("--ledger-only")
        self.assertIn("Follow-up: #142 on prod, seen %s (ledger): %s 10:0x #142 ON PROD" % (self.TODAY, self.TODAY), out)
        self.assertIn("Follow-up: #143 merged", out)
        self.assertIn("Follow-up: v1.2.3 released", out)
        self.assertIn("Follow-up: #160 on staging", out)
        for absent in ("#144", "#145", "#150", "#99"):
            self.assertNotIn(absent, out)
        self.assertLess(out.index("#142"), out.index("#160"))
        self.assertLess(out.index("#160"), out.index("#143"))
        self.assertIn("4 to propose, 0 to re-check; last review never; next review now", out)
        self.assertIn("#99 on prod", self.followups("--ledger-only", "--days", "30"))

    def test_a_recorded_verification_hides_it_and_lands_in_its_own_section(self):
        r = self.verification("#142 billing fix", "verified", "'verify #142' [abcdef]: 7 orders, 0 refusals")
        self.assertEqual((r.returncode, r.stdout), (0, "#142 billing fix: verified (prod)\n"))
        self.assertNotIn("#142", self.followups("--ledger-only"))
        ledger = open(self.ledger).read()
        self.assertLess(ledger.index("## Verifications"), ledger.index("## Log"))
        self.assertIn("| #142 billing fix | prod | verified |", ledger)
        self.verification("#142", "broken")  # an update keeps one row and its evidence
        ledger = open(self.ledger).read()
        self.assertEqual(ledger.count("| #142"), 1)
        self.assertIn("| #142 | prod | broken |", ledger)
        self.assertIn("7 orders, 0 refusals", ledger)
        self.assertNotIn("#142", self.followups("--ledger-only"))

    def test_every_open_result_hides_it_until_a_not_exercised_one_is_due_again(self):
        for result in ("proposed", "running", "skipped"):
            self.assertEqual(self.verification("#143", result).returncode, 0)
            self.assertNotIn("#143", self.followups("--ledger-only"))
        self.verification("#143", "not exercised yet", "no orders since deploy")
        self.assertNotIn("#143", self.followups("--ledger-only"))
        self.verification("#143", "not-exercised", "--recheck-hours", "0")
        self.assertIn("Re-check: #143 on merged: not exercised yet at", self.followups("--ledger-only"))
        self.assertIn("no orders since deploy", self.followups("--ledger-only"))

    def test_verification_refuses_an_unknown_result_or_an_empty_thing(self):
        self.assertIn("result is one of", self.verification("#142", "looks fine").stderr)
        self.assertIn("say what was verified", self.verification("  ", "verified").stderr)
        self.assertNotIn("## Verifications", open(self.ledger).read())

    def test_the_hook_says_a_review_is_due_until_it_is_stamped_and_can_be_turned_off(self):
        self.assertIn("session-guide follow-ups: the review of recent fixes and deployments is due (last review never)",
                      self.context())
        self.assertNotIn("follow-ups", self.context(SESSION_GUIDE_FOLLOWUP_HOURS="0"))
        out = self.followups("--ledger-only", "--reviewed")
        self.assertIn("last review %s" % time.strftime("%Y-%m-%d"), out)
        self.assertRegex(open(self.ledger).read(), r"## Verifications\nLast review: \d{4}-\d\d-\d\d \d\d:\d\d\n")
        self.assertNotIn("follow-ups", self.context())
        self.assertIn("follow-ups", self.context(SESSION_GUIDE_FOLLOWUP_HOURS="0.0001"))
        self.verification("#142", "running")  # the table goes above the stamp
        ledger = open(self.ledger).read()
        self.assertLess(ledger.index("| #142"), ledger.index("Last review:"))
        self.assertEqual(ledger.count("Last review:"), 1)

    def test_a_ledger_with_nothing_deployed_never_asks_for_a_review(self):
        open(self.ledger, "w").write(LEDGER)
        self.assertNotIn("follow-ups", self.context())

    def test_recent_reports_in_the_sessions_transcripts_count_with_their_session(self):
        path = os.path.join(self.cfg, "projects", "-tmp-repo", "3fa9c100-0000-4000-8000-000000000000.jsonl")
        with open(path, "a") as f:
            f.write(self.assistant_line("PR #170 is merged and ON PROD since 10:05Z. Next I check #171 once merged."))
            f.write(self.assistant_line("#172 ON PROD", age=5 * 86400))
            f.write(self.assistant_line("#173 ON PROD", sidechain=True))
        out = self.followups()
        self.assertIn("Follow-up: #170 on prod", out)
        self.assertIn("('billing export lead' [3fa9c1]): PR #170 is merged and ON PROD", out)
        for absent in ("#171", "#172", "#173"):
            self.assertNotIn(absent, out)
        self.assertNotIn("#170", self.followups("--ledger-only"))


if __name__ == "__main__":
    unittest.main()
