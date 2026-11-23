#!/usr/bin/env python3
"""Tests for guide_streams.py: streams (projects), their icons, and where the icons go. Every test uses its own temp
CLAUDE_CONFIG_DIR, and no network."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "session-guide", "scripts")
SCRIPT = os.path.join(SCRIPTS, "guide_title.py")
TITLES = os.path.join(os.path.dirname(ROOT), "session-titles", "scripts", "session_titles.py")
sys.path.insert(0, SCRIPTS)
import guide_streams as gs  # noqa: E402
import guide_title as gt  # noqa: E402

GUIDE = "c0ffee12-3456-4789-8abc-def012345678"
LEAD = "3fa9c100-1234-4567-89ab-cdef01234567"
NEXT = "5eed0000-1234-4567-89ab-cdef01234567"
SPIKE = "b5c6d700-1234-4567-89ab-cdef01234567"
OWN = "f1a2b300-1234-4567-89ab-cdef01234567"
HOUSE, SHIP, MONEY = "\U0001f3e0", "\U0001f6a2", "\U0001f4b0"
LEDGER = """# release — guide ledger
Guide: 'release guide' [c0ffee12] since 10-27 09:00

## Streams
| Stream | Where now | Next step | Owner | Blocked on |
|---|---|---|---|---|
| Billing export | on staging | prod | 'billing export lead' [3fa9c1] | — |
| Old cleanup | paused | x \\| y | — | — |

Kept text.

## Sessions
| Title [id6] | Level | Role / stream | Worktree @ sha | Address | Ctx | Last seen |
|---|---|---|---|---|---|---|
| 'billing export lead' [3fa9c1] | MANAGED | billing lead | — | uds | 140k | 12:35 |
| 'design spike' [b5c6d7] | WATCHED | — | — | — | 90k | 12:02 |
| 'personal notes' [f1a2b3] | ACTIVE | — | — | — | — | — |

## Open items
| Item | Next action | Owner | Status |
|---|---|---|---|
"""


class Case(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="guide-streams-")
        self.addCleanup(shutil.rmtree, self.cfg)
        self.ledger = os.path.join(self.cfg, "session-guide", "release", "ledger.md")
        self.put(self.ledger, LEDGER)
        for sid, level in ((GUIDE, self.ledger), (LEAD, "guided"), (SPIKE, "watched"), (OWN, "active")):
            self.put(os.path.join(self.cfg, "session-guide", "guides", sid), level + "\n")
        for sid in (GUIDE, LEAD, SPIKE, OWN):
            self.transcript(sid)
        patch = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.cfg, "SESSION_GUIDE_GH": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        for name in [n for n in os.environ if n.startswith("SESSION_GUIDE_") and n != "SESSION_GUIDE_GH"] + [
                "CLAUDE_CODE_SESSION_ID"]:
            os.environ.pop(name, None)

    def put(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def get(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def transcript(self, sid, age=0):
        path = os.path.join(self.cfg, "projects", "p", sid + ".jsonl")
        self.put(path, "{}\n")
        os.utime(path, (time.time() - age,) * 2)

    def run_script(self, *args, stdin="", **env):
        return subprocess.run([sys.executable, SCRIPT] + list(args), input=stdin, capture_output=True, encoding="utf-8",
                              env=dict(os.environ, CLAUDE_CODE_SESSION_ID=GUIDE, PYTHONIOENCODING="utf-8", **env))

    def stream(self, *args, **env):
        r = self.run_script("stream", *args, **env)
        self.assertEqual((r.returncode, r.stderr), (0, ""), args)
        return r.stdout

    def refused(self, *args):
        r = self.run_script("stream", *args)
        self.assertNotEqual(r.returncode, 0, args)
        return r.stderr

    def registry(self):
        return json.loads(self.get(gs.registry_path(self.ledger)))

    def hook(self, sid, title="", **env):
        out = self.run_script("hook", stdin=json.dumps({"session_id": sid, "hook_event_name": "UserPromptSubmit",
                                                        "session_title": title}), **env).stdout
        return json.loads(out)["hookSpecificOutput"] if out else {}

    def title(self, sid, title, **env):
        return self.hook(sid, title, **env).get("sessionTitle")

    def billing(self):
        self.stream("add", "billing", "Billing export", "--icon", HOUSE)
        self.stream("assign", "billing", LEAD)


class RegistryTest(Case):
    def test_add_list_rename_end(self):
        self.assertIn("no open streams", self.stream("list"))
        self.assertEqual(self.stream("add", "billing", "Billing export", "--icon", HOUSE),
                         HOUSE + " Billing export (billing) is open\n")
        self.assertEqual(self.registry()["billing"], dict(icon=HOUSE, name="Billing export", state="open", ended=None,
                                                          since=time.strftime("%Y-%m-%d"), sessions=[]))
        self.assertIn(HOUSE + " Billing export (billing)", self.stream("list"))
        self.stream("rename", "billing", "--name", "Billing")
        self.assertEqual(self.registry()["billing"]["name"], "Billing")
        self.stream("end", "billing")
        self.assertNotIn("(billing)", self.stream("list"))
        self.assertIn("(billing), ended", self.stream("list", "--all"))
        self.assertIn("ended on", self.refused("end", "billing"))

    def test_an_ended_key_reopens_with_its_icon_and_sessions(self):
        self.billing()
        self.stream("end", "billing")
        self.stream("add", "billing")
        self.assertEqual((self.registry()["billing"]["icon"], self.registry()["billing"]["sessions"]), (HOUSE, [LEAD]))

    def test_bad_keys_names_and_icons(self):
        for key in ("", "Two words", "-x", "a" * 25):
            self.refused("add", "--", key, "Name")
        for name in ("", "a|b", "x" * 25):
            self.refused("add", "ok", name)
        for icon in ("⬜", "🟦", "✅", "🟥", "🟧", "🎟️", "🎟", "👩‍💻", "🏳️", "xy", "漢", "→", "[tw]", "🏠🏠"):
            self.refused("add", "ok", "Name", "--icon", icon)
        self.assertEqual(gs.read(self.ledger), {})

    def test_a_tag_is_fine(self):
        self.stream("add", "two", "Two", "--icon", "[TW]")
        self.stream("assign", "two", LEAD)
        self.assertEqual(self.title(LEAD, "lead"), "🟧🟧 (g) [TW] lead")

    def test_one_icon_per_open_stream_on_this_machine(self):
        self.billing()
        self.assertIn("belongs to stream billing", self.refused("add", "ship", "Ship", "--icon", HOUSE))
        self.assertIn("is open already", self.refused("add", "billing", "Again"))
        self.put(os.path.join(self.cfg, "session-guide", "other", "streams.json"),
                 json.dumps({"x": {"icon": SHIP, "name": "X", "state": "open"}}))
        self.assertIn("belongs to stream x", self.refused("add", "ship", "Ship", "--icon", SHIP))
        self.assertNotIn(SHIP, self.stream("suggest", "30"))

    def test_an_ended_streams_icon_is_free_after_seven_days(self):
        self.billing()
        self.stream("end", "billing")
        self.assertIn("belongs to", self.refused("add", "ship", "Ship", "--icon", HOUSE))
        found = self.registry()
        found["billing"]["ended"] = time.strftime("%Y-%m-%d", time.localtime(time.time() - 8 * 86400))
        self.put(gs.registry_path(self.ledger), json.dumps(found))
        self.stream("add", "ship", "Ship", "--icon", HOUSE)
        self.assertEqual(self.title(LEAD, "lead"), "🟧🟧 (g) 🏠 lead")  # its old session keeps it

    def test_suggest_and_the_default_icon(self):
        self.assertEqual(self.stream("suggest", "2").split(), [HOUSE, SHIP])
        self.stream("add", "one", "One")
        self.stream("add", "two", "Two")
        self.assertEqual([self.registry()[k]["icon"] for k in ("one", "two")], [HOUSE, SHIP])
        self.assertEqual(len(set(gs.ICONS)), len(gs.ICONS))
        self.assertEqual([i for i in gs.ICONS if gs.icon_problem(i)], [])

    def test_out_of_icons(self):
        self.put(gs.registry_path(self.ledger), json.dumps(
            {"s%d" % n: {"icon": i, "name": "S"} for n, i in enumerate(gs.ICONS)}))
        self.assertIn("two-letter tag", self.stream("suggest"))
        self.assertIn("[TW]", self.refused("add", "two", "Two"))

    def test_concurrent_writers_lose_nothing(self):
        def add(n):
            with gs.editing(self.ledger) as streams:
                before = dict(streams)
                time.sleep(0.02)
                streams.update(before, **{"s%d" % n: {"icon": "[S%d]" % n, "name": "S"}})
        threads = [threading.Thread(target=add, args=(n,)) for n in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(self.registry()), 6)

    def test_a_bad_file_is_read_as_empty_and_never_replaced(self):
        for bad in ("{", "[]", '{"a": 1}', '{"a": {"icon": 5, "name": "x"}}'):
            self.put(gs.registry_path(self.ledger), bad)
            self.assertEqual(gs.read(self.ledger), {})
            self.assertIn("nothing was changed", self.refused("add", "ship", "Ship"))
            self.assertEqual(self.get(gs.registry_path(self.ledger)), bad)
            self.assertIsNone(self.title(LEAD, "🟧🟧 (g) lead"))


class AssignTest(Case):
    def test_assign_moves_a_session_between_streams(self):
        self.billing()
        self.stream("add", "ship", "Ship", "--icon", SHIP)
        self.assertEqual(self.title(LEAD, "lead"), "🟧🟧 (g) 🏠 lead")
        self.stream("assign", "ship", LEAD)
        self.assertEqual([self.registry()[k]["sessions"] for k in ("billing", "ship")], [[], [LEAD]])
        self.assertEqual(self.title(LEAD, "🟧🟧 (g) 🏠 lead"), "🟧🟧 (g) 🚢 lead")
        self.assertEqual(gt.marker_content(LEAD), "guided")  # the marker's exact text is read by other tools

    def test_the_users_own_window_needs_a_yes(self):
        self.billing()
        self.assertIn("--active-ok", self.refused("assign", "billing", OWN))
        self.assertIsNone(gs.session_stream(OWN))
        self.stream("assign", "billing", OWN, "--active-ok")
        self.assertEqual(self.title(OWN, "notes"), "🟦🟦 🏠 notes")

    def test_an_unknown_session_id_is_said_so(self):
        self.billing()
        self.assertIn("no session with id", self.refused("assign", "billing", "99999999-1234-4567-89ab-cdef01234567"))
        self.assertIn("no session starts with 9999", self.refused("assign", "billing", "9999"))

    def test_guides_closed_sessions_and_ended_streams_refuse(self):
        self.billing()
        self.assertIn("is a guide", self.refused("assign", "billing", GUIDE, "--active-ok"))
        self.put(gt.marker(SPIKE), "done\n")
        self.assertIn("is closed", self.refused("assign", "billing", SPIKE))
        self.stream("end", "billing")
        self.assertIn("has ended", self.refused("assign", "billing", LEAD))
        self.assertIn("no stream", self.refused("assign", "nope", LEAD))

    def test_a_new_icon_reaches_the_streams_sessions(self):
        self.billing()
        self.stream("rename", "billing", "--icon", MONEY)
        self.assertEqual(self.title(LEAD, "🟧🟧 (g) 🏠 lead"), "🟧🟧 (g) 💰 lead")

    def test_strip_and_put_back(self):
        self.billing()
        self.stream("strip", LEAD)
        self.assertEqual(self.title(LEAD, "🟧🟧 (g) 🏠 lead"), "🟧🟧 (g) lead")
        self.assertIsNone(self.title(LEAD, "🟧🟧 (g) lead"))
        self.assertFalse(os.path.exists(gs.session_path(LEAD)))  # clean: an icon typed later is the user's own
        self.assertIsNone(self.title(LEAD, "🟧🟧 (g) 🏠 lead"))
        self.stream("assign", "billing", LEAD)
        self.assertEqual(self.title(LEAD, "🟧🟧 (g) lead"), "🟧🟧 (g) 🏠 lead")
        self.refused("strip")
        self.refused("strip", LEAD, "--all")
        self.assertIn("is on no stream", self.stream("strip", SPIKE))

    def test_strip_all_reaches_a_stopped_job(self):
        self.billing()
        path = os.path.join(self.cfg, "jobs", LEAD[:8], "state.json")
        self.put(path, json.dumps(dict(sessionId=LEAD, name="🟧🟧 (g) 🏠 lead")))
        self.assertIn("1 session(s) stripped", self.stream("strip", "--all"))
        self.assertEqual(json.loads(self.get(path))["name"], "🟧🟧 (g) lead")


class LaunchTest(Case):
    def launch(self, *args):
        fake = os.path.join(self.cfg, "fake_claude.py")
        self.put(fake, "print('backgrounded · %s')\n" % NEXT[:8])
        self.put(os.path.join(self.cfg, "jobs", NEXT[:8], "state.json"), json.dumps(dict(sessionId=NEXT, name="next")))
        return self.run_script("launch", *(args + ("--", "brief")), SESSION_GUIDE_CLAUDE="%s %s" % (sys.executable, fake))

    def test_stream(self):
        self.billing()
        self.assertEqual(self.launch("--stream", "billing").returncode, 0)
        self.assertEqual(self.registry()["billing"]["sessions"], [LEAD, NEXT])
        self.assertEqual(self.title(NEXT, "lead (2)"), "🟧🟧 (g) 🏠 lead (2)")

    def test_a_successor_keeps_the_stream_of_a_closed_predecessor(self):
        self.billing()
        self.put(gt.marker(LEAD), "done\n")
        self.assertEqual(self.launch("--successor-of", LEAD[:8]).returncode, 0)
        self.assertEqual(gs.session_stream(NEXT)["icon"], HOUSE)

    def test_a_predecessor_on_no_stream_launches_without_an_icon(self):
        r = self.launch("--successor-of", SPIKE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("on no open stream", r.stdout)
        self.assertEqual(self.title(NEXT, "x"), "🟧🟧 (g) x")

    def test_a_wrong_key_starts_nothing(self):
        self.assertNotEqual(self.launch("--stream", "nope").returncode, 0)
        self.assertIsNone(gt.marker_content(NEXT))


class TitleTest(Case):
    TITLES = ("x", "🟧🟧 (g) x", "⬜⬜ x", "🟦🟦 x", "✅ x", "🚀 x", "(g) x", "🟧🟧 x", "y" * 200, "🏠", "", "✅ 🟧🟧 (g) x")

    def test_levels(self):
        for content, prefix in ((gt.GUIDED, "🟧🟧 (g) "), (gt.WATCHED, "⬜⬜ "), (gt.ACTIVE, "🟦🟦 "), (gt.DONE, "✅ "),
                                (gt.UNGUIDED, ""), (None, "")):
            want = prefix + "🏠 x"
            for now in ("x", "🏠 x", "🏠 🏠 x", want) + (
                    "🟧🟧 (g) 🏠 x", "🟧🟧 (g) x", "🏠 🟧🟧 (g) 🏠 x", "⬜⬜ 🏠 x", "🟦🟦 x"):
                got = gt.worker_title(content, now, HOUSE)
                self.assertEqual(now if got is None else got, want, (content, now))

    def test_a_rename_gets_the_icon_back(self):
        self.billing()
        self.assertEqual(self.title(LEAD, "new name"), "🟧🟧 (g) 🏠 new name")
        self.assertIsNone(self.title(LEAD, "🟧🟧 (g) 🏠 new name"))
        self.assertEqual(self.title(LEAD, "🚀 new name"), "🟧🟧 (g) 🏠 🚀 new name")  # the user's own emoji stays
        self.assertEqual(self.title(LEAD, "🏠new"), "🟧🟧 (g) 🏠 🏠new")  # and so does one that is part of a word

    def test_long_and_icon_only_titles(self):
        self.assertEqual(gt.worker_title(gt.GUIDED, "y" * 200, HOUSE), "🟧🟧 (g) 🏠 " + "y" * 200)
        for empty in ("", "🏠", "🟧🟧 (g) 🏠", "🟧🟧 (g)"):
            self.assertIsNone(gt.worker_title(gt.GUIDED, empty, HOUSE))

    def test_no_stream_is_byte_identical(self):
        self.billing()  # a stream exists; SPIKE is on none
        for level in ("guided", "watched", "active", "unguided", "done"):
            for now in self.TITLES:
                self.assertEqual(gt.worker_title(level, now), reference(level, now), (level, now))
                self.put(gt.marker(SPIKE), level + "\n")
                self.assertEqual(gt.title_for(SPIKE, now), reference(level, now), (level, now))
        os.remove(gt.marker(SPIKE))
        self.assertEqual([gt.title_for(SPIKE, t) for t in self.TITLES], [None] * len(self.TITLES))

    def test_switch_off_is_byte_identical(self):
        self.billing()
        self.assertEqual(self.title(LEAD, "lead", SESSION_GUIDE_STREAM_ICONS="0"), "🟧🟧 (g) lead")
        self.assertIsNone(self.title(LEAD, "🟧🟧 (g) 🏠 lead", SESSION_GUIDE_STREAM_ICONS="0"))  # part of its name now
        self.stream("strip", LEAD, SESSION_GUIDE_STREAM_ICONS="0")
        self.assertEqual(self.title(LEAD, "🟧🟧 (g) 🏠 lead", SESSION_GUIDE_STREAM_ICONS="0"), "🟧🟧 (g) lead")
        with mock.patch.dict(os.environ, SESSION_GUIDE_STREAM_ICONS="0"):
            self.assertIsNone(gs.context(self.ledger))
            self.assertEqual((gs.state_lines(self.ledger), gs.shown(self.ledger, "x [3fa9c1]")), ([], "x [3fa9c1]"))

    def test_a_scoped_tag_is_a_level_mark(self):
        for now in ("🟧🟧 (g·hub) x", "(g·hub) x", "✅ 🟧🟧 (g·hub) x"):
            self.assertEqual(gt.worker_title(gt.DONE, now), None if now == "✅ x" else "✅ x")
        self.assertEqual(gt.worker_title(gt.WATCHED, "🟧🟧 (g·hub) 🏠 x", HOUSE), "⬜⬜ 🏠 x")
        self.assertEqual(gt.worker_title(gt.UNGUIDED, "🟧🟧 (g·hub) x"), "x")
        self.assertEqual(gt.worker_title(gt.DONE, "(gamma) x"), "✅ (gamma) x")
        os.environ["SESSION_GUIDE_GUIDED_PREFIX"] = "🟧🟧 (g·hub) "
        self.assertEqual(gt.worker_title(gt.GUIDED, "🟧🟧 (g) x", HOUSE), "🟧🟧 (g·hub) 🏠 x")
        self.assertIsNone(gt.worker_title(gt.GUIDED, "🟧🟧 (g·hub) 🏠 x", HOUSE))

    def test_done_keeps_the_icon(self):
        self.billing()
        path = os.path.join(self.cfg, "jobs", LEAD[:8], "state.json")
        self.put(path, json.dumps(dict(sessionId=LEAD, name="🟧🟧 (g) 🏠 lead")))
        self.assertEqual(self.run_script("done", LEAD).returncode, 0)
        self.assertEqual(json.loads(self.get(path))["name"], "✅ 🏠 lead")
        self.assertEqual(self.title(LEAD, "🟧🟧 (g) 🏠 lead"), "✅ 🏠 lead")

    def test_an_unguided_session_keeps_the_icon(self):
        self.billing()
        self.run_script("unguided", LEAD)
        self.assertEqual(self.title(LEAD, "🟧🟧 (g) 🏠 lead"), "🏠 lead")
        self.assertIsNone(self.title(LEAD, "🏠 lead"))
        self.assertIsNone(gt.marker_content(LEAD))
        self.assertEqual(self.title(LEAD, "renamed"), "🏠 renamed")

    def test_a_guides_own_title_has_no_icon(self):
        gs.set_session(GUIDE, "billing", HOUSE)
        self.assertNotIn(HOUSE, self.title(GUIDE, "x"))


def reference(content, current):
    """worker_title before streams existed."""
    marks = ["🟧🟧 (g)", "⬜⬜", "🟦🟦", "🟧🟧", "(g)"] + ["✅"] * (content == "done")
    bare = current
    while any(bare.startswith(m) for m in marks):
        bare = bare[len(next(m for m in marks if bare.startswith(m))):].lstrip()
    want = {"guided": "🟧🟧 (g) ", "watched": "⬜⬜ ", "active": "🟦🟦 ", "done": "✅ "}.get(content, "") + bare
    return want if bare and want != current else None


class SessionTitlesTest(Case):
    def state(self, **kw):
        path = os.path.join(self.cfg, "session-titles", LEAD + ".json")
        if kw:
            self.put(path, json.dumps(kw))
        return json.loads(self.get(path))

    def test_the_icon_goes_into_its_origin_and_comes_off(self):
        self.state(origin="🟧🟧 (g) lead", last_set="🟧🟧 (g) lead · CI", history=["🟧🟧 (g) lead · CI"])
        self.billing()
        self.assertEqual(self.state()["origin"], "🟧🟧 (g) 🏠 lead")
        self.assertEqual(self.state()["last_set"], "🟧🟧 (g) 🏠 lead · CI")
        self.assertIn("🟧🟧 (g) lead · CI", self.state()["history"])
        self.hook(LEAD, "🟧🟧 (g) 🏠 lead · CI")
        self.assertEqual(self.state()["origin"], "🟧🟧 (g) 🏠 lead")
        self.stream("strip", LEAD)
        self.assertEqual((self.state()["origin"], "off" in self.state()), ("🟧🟧 (g) lead", False))

    def test_with_no_marker_it_is_not_turned_off(self):
        self.state(origin="lead", last_set="lead")
        self.billing()
        os.remove(gt.marker(LEAD))
        self.hook(LEAD, "lead")
        self.assertEqual((self.state()["origin"], "off" in self.state()), ("🏠 lead", False))

    @unittest.skipUnless(os.path.isfile(TITLES), "session-titles is not next to this plugin")
    def test_the_icon_survives_its_48_character_cut(self):
        spec = importlib.util.spec_from_file_location("session_titles_for_streams", TITLES)
        titles = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "dont_write_bytecode", True):
            spec.loader.exec_module(titles)
        for name in ("billing export stage one lead with a very long title (sync 5)", "y" * 200):
            full = gt.worker_title(gt.GUIDED, name, HOUSE)
            cut = titles.fit(full, 48)
            self.assertTrue(cut.startswith("🟧🟧 (g) 🏠 ") and len(cut) <= 48, cut)
            self.assertIsNone(gt.worker_title(gt.GUIDED, cut, HOUSE))


class ShownTest(Case):
    def test_lines_show_the_icon_and_cells_do_not(self):
        self.billing()
        self.assertEqual(gs.shown(self.ledger, "'lead' [3fa9c1]"), "🏠 'lead' [3fa9c1]")
        self.assertEqual(gs.shown(self.ledger, "🏠 'lead' [3fa9c1]"), "🏠 'lead' [3fa9c1]")
        self.assertEqual(gs.shown(self.ledger, "'other' [aaaaaa]"), "'other' [aaaaaa]")
        self.run_script("waiting", LEAD, "Merge #142")
        out = self.run_script("settle").stdout
        self.assertIn("Due: 🏠 'billing export lead' [3fa9c1]: Merge #142", out)
        self.assertNotIn(HOUSE, self.get(self.ledger).split("## Waiting on")[1].split("## Open items")[0])

    def test_a_results_key_is_the_same_with_and_without_the_icon(self):
        self.billing()
        self.run_script("result", "report one", "https://x.test/1", "--from", "🏠 'lead' [3fa9c1]")
        self.run_script("result", "🏠 report one", "https://x.test/2")
        rows = gt.results_rows(self.ledger)
        self.assertEqual(list(rows), ["report one ('lead' [3fa9c1])"])
        self.assertIn("Unanswered result: 🏠 report one", self.run_script("settle").stdout)

    def test_an_owed_question_key_is_the_same_with_and_without_the_icon(self):
        self.billing()
        for question in ("Merge it now? [3fa9c1]", "🏠 Merge it now? [3fa9c1]"):
            self.run_script("waiting", "ask", question)
        owed = [r for r in gt.waiting_rows(self.ledger).values() if r["owed"]]
        self.assertEqual(len(owed), 1)
        self.assertIn("Due: 🏠 owed question", self.run_script("settle").stdout)

    def test_the_guide_hears_its_streams_and_the_quiet_ones(self):
        self.assertNotIn("session-guide streams", self.hook(GUIDE).get("additionalContext", ""))
        self.billing()
        context = self.hook(GUIDE)["additionalContext"]
        self.assertIn("🏠 Billing export (billing)", context)
        self.assertNotIn("No activity", context)
        found = self.registry()
        found["billing"]["since"] = "2026-01-01"
        self.put(gs.registry_path(self.ledger), json.dumps(found))
        self.assertNotIn("No activity", self.hook(GUIDE)["additionalContext"])  # LEAD wrote just now
        self.transcript(LEAD, age=8 * 86400)
        self.assertIn("No activity for 7 days: 🏠 billing", self.hook(GUIDE)["additionalContext"])
        self.assertIn("no activity for 7 days: 🏠 billing", self.stream("list"))

    def test_state_md_and_list(self):
        self.billing()
        self.run_script("settle")
        state = self.get(os.path.join(os.path.dirname(self.ledger), "STATE.md"))
        self.assertIn("## Streams (1 open)\n- 🏠 Billing export (billing)", state)
        self.assertIn("- 🏠 'billing export lead' [3fa9c1] MANAGED", state)
        self.assertIn("on no stream: 'design spike' [b5c6d7]", self.stream("list"))

    def test_without_a_registry_nothing_is_added(self):
        self.run_script("settle")
        self.assertNotIn("## Streams", self.get(os.path.join(os.path.dirname(self.ledger), "STATE.md")))
        self.assertFalse(os.path.exists(gs.registry_path(self.ledger)))
        self.assertEqual(self.get(self.ledger), LEDGER)


class TableTest(Case):
    def table(self):
        return self.get(self.ledger).split("## Streams\n")[1].split("## Sessions")[0]

    def test_icon_column_rows_and_end(self):
        self.stream("add", "billing", "Billing export", "--icon", HOUSE)
        self.stream("add", "ship", "Release train", "--icon", SHIP)
        self.assertTrue(self.table().startswith("| Icon | Stream | Where now | Next step | Owner | Blocked on |\n| --- |"))
        self.assertIn("| 🏠 | Billing export | on staging | prod |", self.table())
        self.assertIn("|  | Old cleanup | paused | x \\| y | — | — |", self.table())
        self.assertIn("| 🚢 | Release train | — | — | — | — |\n\nKept text.", self.table())
        self.stream("rename", "ship", "--name", "Releases")
        self.assertEqual(self.table().count("🚢"), 1)
        self.assertIn("| 🚢 | Releases |", self.table())
        self.stream("end", "billing")
        self.assertIn("| ended %s; was: on staging |" % time.strftime("%Y-%m-%d"), self.table())
        before = self.get(self.ledger)
        self.assertIn("0 line(s)", self.stream("table"))
        self.assertEqual(self.get(self.ledger), before)

    def test_end_unlisted_marks_old_rows_and_deletes_none(self):
        self.stream("add", "billing", "Billing export", "--icon", HOUSE)
        self.stream("table", "--end-unlisted")
        self.assertIn("| Old cleanup | ended %s; was: paused |" % time.strftime("%Y-%m-%d"), self.table())
        self.assertIn("| Billing export | on staging |", self.table())
        before = self.get(self.ledger)
        self.stream("table", "--end-unlisted")
        self.assertEqual(self.get(self.ledger), before)

    def test_end_unlisted_leaves_a_done_row_with_an_icon_alone(self):
        self.put(self.ledger, LEDGER.replace("| paused |", "| \u2705 DONE 10-29: shipped |", 1))
        self.stream("add", "billing", "Billing export", "--icon", HOUSE)
        self.stream("table", "--end-unlisted")
        self.assertIn("| Old cleanup | \u2705 DONE 10-29: shipped |", self.table())
        self.assertNotIn("ended %s; was: \u2705" % time.strftime("%Y-%m-%d"), self.table())

    def test_a_ledger_with_no_table(self):
        self.put(self.ledger, "# x\n\n" + LEDGER[LEDGER.index("## Sessions"):])
        self.stream("add", "billing", "Billing export", "--icon", HOUSE)
        self.assertIn("| 🏠 | Billing export |", self.table())
        self.assertIn("## Sessions", self.get(self.ledger))

    def test_a_row_with_no_closing_pipe_keeps_its_last_cell(self):
        self.put(self.ledger, LEDGER.replace("[3fa9c1] | — |\n", "[3fa9c1] | traffic\n", 1))
        self.stream("add", "ship", "Ship", "--icon", SHIP)
        self.assertIn("[3fa9c1] | traffic |\n", self.table())


if __name__ == "__main__":
    unittest.main()
