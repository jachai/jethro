#!/usr/bin/env python3
"""Tests for skills/session-guide/scripts/guide_audit.py and its wiring in guide_title.py.

Every test builds its own small ledger in a temp CLAUDE_CONFIG_DIR. `audit(..., now=NOW)` is deterministic; the tests
that go through run(), set or the hooks read the real clock, so their dates are relative to today."""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "session-guide", "scripts")
sys.path.insert(0, SCRIPTS)
import guide_audit as ga  # noqa: E402
import guide_title as gt  # noqa: E402

TITLE_SCRIPT = os.path.join(SCRIPTS, "guide_title.py")
GUIDE = "c0ffee12-3456-4789-8abc-def012345678"
NOW = time.mktime((2026, 11, 19, 12, 0, 0, 0, 0, -1))
DAY = 86400
OPEN_HEAD = ["| Item | Owner | Status |", "|---|---|---|"]
SESSIONS_HEAD = [
    "| Title [id6] | Level | Role | Worktree | Address | Ctx | Last seen |", "|---|---|---|---|---|---|---|"]
WAITING_HEAD = ["| Session [id6] | What the user needs to do | Asked | Remind at |", "|---|---|---|---|"]
VERIF_HEAD = ["| Thing | Where | Result | Checked | Evidence / session | Re-check |", "|---|---|---|---|---|---|"]
PEOPLE = ["Alice", "Bruno", "Carla", "Dmitri", "Elena", "Farid", "Greta", "Hugo", "Imani", "Jun", "Kofi", "Lena"]


def fake_gh(answers):
    """A stand-in for guide_gh: pr_state answers from `answers` ({PR number: {"state", "mergedAt"}}), else None."""
    module = types.ModuleType("guide_gh")
    module.pr_state = lambda number, repo=None, cache=None, now=None: answers.get(int(str(number).lstrip("#")))
    return module


def day(n):
    """MM-DD, n days before the real today."""
    return time.strftime("%m-%d", time.localtime(time.time() - n * DAY))


def stamp(hours_ago, now=None):
    return time.strftime(gt.TIME_FORMAT, time.localtime((now or NOW) - hours_ago * 3600))


def session_row(name, rid, level="MANAGED"):
    return "| %s [%s] | %s | role | wt | uds | 1k | 12:00 |" % (name, rid, level)


def verif_row(thing, result, evidence="no evidence", recheck="—", where="prod", checked="2026-11-17 10:00"):
    return "| %s | %s | %s | %s | %s | %s |" % (thing, where, result, checked, evidence, recheck)


def ledger_text(open_=None, sessions=None, waiting=None, verif=None, decisions=None, head=(), open_head=OPEN_HEAD):
    out = ["# t — guide ledger", "Guide: 'g' [c0ffee12] since 11-01 09:00"] + list(head) + [""]
    parts = (("## Open items (every row has an owner)", open_head, open_), ("## Sessions", SESSIONS_HEAD, sessions),
             ("## Waiting on the user", WAITING_HEAD, waiting), ("## Verifications", VERIF_HEAD, verif))
    for title, top, rows in parts:
        if rows is not None:
            out += [title] + top + rows + [""]
    if decisions is not None:
        out += ["## Decisions (FINAL unless struck)"] + decisions + [""]
    return "\n".join(out) + "\n"


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="guide-audit-")
        self.addCleanup(shutil.rmtree, self.cfg, True)
        patcher = mock.patch.dict(os.environ, CLAUDE_CONFIG_DIR=self.cfg)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in [k for k in os.environ if k.startswith("SESSION_GUIDE_") or k == "CLAUDE_CODE_SESSION_ID"]:
            del os.environ[name]
        os.environ["SESSION_GUIDE_GH"] = "0"  # a script the tests run in a subprocess never asks the real gh
        self.gh = {}  # PR number -> {"state", "mergedAt"}: what the fake guide_gh answers
        modules = mock.patch.dict(sys.modules, guide_gh=fake_gh(self.gh))
        modules.start()
        self.addCleanup(modules.stop)
        self.ledger = os.path.join(self.cfg, "session-guide", "t", "ledger.md")
        os.makedirs(os.path.dirname(self.ledger))

    def make(self, **kw):
        with open(self.ledger, "w") as f:
            f.write(ledger_text(**kw))
        return self.ledger

    def audit(self, full=False, **kw):
        return ga.audit(self.ledger, full=full, now=NOW, **kw)

    def real(self, **kw):
        return ga.audit(self.ledger, full=False, **kw)

    def transcript(self, rid, ago=0, said=None, now=NOW):
        sid = rid + "00-0000-4000-8000-000000000000"
        path = os.path.join(self.cfg, "projects", "-tmp-repo", sid + ".jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lines = [{"type": "user", "message": {"role": "user", "content": "Build the thing"}}]
        if said is not None:
            lines.append({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
        with open(path, "w") as f:
            f.write("".join(json.dumps(line) + "\n" for line in lines))
        os.utime(path, (now - ago, now - ago))
        return sid

    def mark_state(self, key, **mark):
        path = ga.state_paths(self.ledger)[0]
        state = ga.load_state(self.ledger)
        state.setdefault("items", {})[key] = mark
        with open(path, "w") as f:
            json.dump(state, f)

    def rows(self, found, text):
        return [r for r in found["rows"] + found["hidden"] if text in r["what"]]

    def one(self, found, text):
        hits = self.rows(found, text)
        self.assertEqual(len(hits), 1, [r["what"] for r in found["rows"] + found["hidden"]])
        return hits[0]

    def whats(self, found):
        return {r["what"] for r in found["rows"] + found["hidden"] if r["kind"] == "open"}

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ga.main(list(args) + ["--ledger", self.ledger])
        self.assertEqual(code, 0)
        return out.getvalue()


class OpenItemsTest(AuditCase):
    def test_three_cells_date_in_status(self):
        self.make(open_=["| Alpha | new session | 11-17 |"])
        row = self.one(self.audit(), "Alpha")
        self.assertEqual(row["owner"], "new session")
        self.assertAlmostEqual(row["age"], 2 * DAY, delta=3600)

    def test_four_cells_date_last(self):
        self.make(open_=["| Beta | new session | see #12 | 11-16 |"])
        self.assertAlmostEqual(self.one(self.audit(), "Beta")["age"], 3 * DAY, delta=3600)

    def test_five_cells_leading_date(self):
        self.make(open_=["| 11-15 | Gamma | new session | a note | open |"])
        row = self.one(self.audit(), "Gamma")
        self.assertEqual(row["owner"], "new session")
        self.assertAlmostEqual(row["age"], 4 * DAY, delta=3600)

    def test_full_year_date_and_date_inside_item(self):
        self.make(open_=["| Eps 11-13 | new session | open |", "| Zed | new session | 2026-11-12 |"])
        found = self.audit()
        self.assertAlmostEqual(self.one(found, "Eps")["age"], 6 * DAY, delta=3600)
        self.assertAlmostEqual(self.one(found, "Zed")["age"], 7 * DAY, delta=3600)

    def test_struck_item_is_skipped(self):
        self.make(open_=["| ~~Struck~~ | new session | 11-17 |", "| Kept | new session | 11-17 |"])
        self.assertEqual(self.whats(self.audit()), {"Kept"})

    def test_finished_status_is_skipped(self):
        for status in ("DONE merged 11-17", "DROPPED: no need", "closed", "Resolved by #4"):
            with self.subTest(status=status):
                self.make(open_=["| Gone | new session | %s |" % status, "| Kept | new session | 11-17 |"])
                self.assertEqual(self.whats(self.audit()), {"Kept"})

    def test_finished_item_cell_is_skipped(self):
        self.make(open_=["| DONE (merged) fix | new session | 11-17 |", "| RESOLVED earlier | new session | 11-17 |",
                         "| Kept | new session | 11-17 |"])
        self.assertEqual(self.whats(self.audit()), {"Kept"})

    def test_header_row_is_skipped(self):
        self.make(open_=["| Kept | new session | 11-17 |"], open_head=["| Item | Owner | Status |", "|---|---|---|"])
        self.assertEqual(self.whats(self.audit()), {"Kept"})

    def test_open_items_heading_with_parenthesis_is_read(self):
        self.make(open_=["| Kept | new session | 11-17 |"])
        tables, _ = ga.sections(self.ledger)
        self.assertEqual([r[0] for r in ga.table(tables, "## Open items")], ["Kept"])

    def test_sessions_added_at_takeover_is_not_the_sessions_table(self):
        with open(self.make(), "a") as f:
            late = SESSIONS_HEAD + [session_row("late", "aaaaaa")]
            f.write("## Sessions added at takeover\n" + "\n".join(late) + "\n")
        tables, _ = ga.sections(self.ledger)
        self.assertEqual(ga.table(tables, "## Sessions"), [])
        with open(self.ledger, "a") as f:
            f.write("\n## Sessions\n" + "\n".join(SESSIONS_HEAD + [session_row("real", "bbbbbb")]) + "\n")
        tables, _ = ga.sections(self.ledger)
        self.assertEqual([ga.gt.row_id(r[0]) for r in ga.table(tables, "## Sessions")], ["bbbbbb"])


class QueueTest(AuditCase):
    def queue(self, name="fixes.md"):
        path = os.path.join(self.cfg, name)
        with open(path, "w") as f:
            f.write("| Ticket | Id | What |\n|---|---|---|\n| ABC-1 | G1 | fix the thing |\n"
                    "| (no ticket) | G2 | other thing |\n| ~~ABC-3~~ | G3 | struck |\n")
        return path

    def queue_whats(self, found):
        return sorted(r["what"] for r in found["rows"] + found["hidden"] if r["kind"] == "queue")

    def expected(self):
        return ["(no ticket) · G2 · other thing", "ABC-1 · G1 · fix the thing"]

    def test_queue_argument(self):
        self.make(open_=[])
        self.assertEqual(self.queue_whats(self.audit(queues=[self.queue()])), self.expected())

    def test_queues_line_in_ledger(self):
        self.make(open_=[], head=["Queues: " + self.queue()])
        self.assertEqual(self.queue_whats(self.audit()), self.expected())

    def test_env_variable(self):
        self.make(open_=[])
        with mock.patch.dict(os.environ, SESSION_GUIDE_QUEUES=self.queue()):
            self.assertEqual(self.queue_whats(self.audit()), self.expected())

    def test_no_queue_means_no_queue_rows(self):
        self.make(open_=[])
        self.assertEqual(self.queue_whats(self.audit()), [])

    def test_short_id_matches_a_reminder(self):
        self.assertIn("G2", ga.names("(no ticket) | G2", ["(no ticket)", "G2"]))
        waiting = ["| helper [dddddd] | Approve G2 before it ships | %s | %s |" % (stamp(2), stamp(-5))]
        self.make(open_=[], waiting=waiting)
        row = self.one(self.audit(queues=[self.queue()]), "other thing")
        self.assertEqual(row["state"], "asked")

    def test_ticket_in_a_live_moving_session_row_is_moving(self):
        self.make(open_=[], sessions=[session_row("fixer for ABC-1", "bbbbbb")])
        self.transcript("bbbbbb", ago=600)
        found = self.audit(queues=[self.queue()])
        self.assertEqual(self.one(found, "fix the thing")["state"], "moving")
        self.assertEqual(self.one(found, "other thing")["state"], "idle")


class ClassifyTest(AuditCase):
    def state(self, owner, status="11-17", item="Thing", **kw):
        self.make(open_=["| %s | %s | %s |" % (item, owner, status)], **kw)
        return self.one(self.audit(), item)["state"]

    def test_moving_with_fresh_transcript(self):
        self.transcript("abc123", ago=600)
        self.assertEqual(self.state("worker [abc123]", sessions=[session_row("w", "abc123")]), "moving")

    def test_quiet_with_old_transcript(self):
        self.transcript("abc123", ago=5 * 3600)
        self.assertEqual(self.state("worker [abc123]", sessions=[session_row("w", "abc123")]), "quiet")

    def test_quiet_when_session_closed(self):
        self.transcript("abc123", ago=600)
        marker = os.path.join(self.cfg, "session-guide", "guides", "abc12300-0000-4000-8000-000000000000")
        os.makedirs(os.path.dirname(marker))
        with open(marker, "w") as f:
            f.write("done\n")
        self.assertEqual(self.state("worker [abc123]", sessions=[session_row("w", "abc123")]), "quiet")

    def test_quiet_when_session_has_no_row(self):
        self.assertEqual(self.state("worker [abc123]", sessions=[]), "quiet")

    def test_asked_by_waiting_row_naming_the_ticket(self):
        waiting = ["| helper [dddddd] | Merge ABC-9 please | %s | %s |" % (stamp(2), stamp(-5))]
        self.assertEqual(self.state("new session", item="Ship ABC-9", waiting=waiting), "asked")

    def test_asked_by_set_then_idle_after_until(self):
        key = ga.item_key("Thing")
        self.make(open_=["| Thing | new session | 11-17 |"])
        self.mark_state(key, state="asked", at=NOW, until=NOW + 3600)
        self.assertEqual(self.one(self.audit(), "Thing")["state"], "asked")
        self.mark_state(key, state="asked", at=NOW - 7200, until=NOW - 3600)
        self.assertEqual(self.one(self.audit(), "Thing")["state"], "idle")

    def test_parked_by_set(self):
        self.make(open_=["| Thing | new session | 11-17 |"])
        self.mark_state(ga.item_key("Thing"), state="parked", at=NOW)
        self.assertEqual(self.one(self.audit(), "Thing")["state"], "parked")

    def test_parked_by_its_own_words(self):
        self.assertEqual(self.state("new session", status="later, after cutover 11-17"), "parked")

    def test_person_owner(self):
        self.assertEqual(self.state("Dana (glance)"), "person")
        self.assertEqual(self.state("ASK the user"), "person")

    def test_idle_owners(self):
        for owner in ("new session", "guide", ""):
            with self.subTest(owner=owner):
                self.assertEqual(self.state(owner), "idle")


class BacklogTest(AuditCase):
    def make_backlog(self):
        self.make(open_=["| Undated | new session | open |", "| Old | new session | 11-01 |",
                         "| Recent | new session | 11-10 |"])
        return self.audit()

    def test_undated_and_old_rows_are_stale(self):
        found = self.make_backlog()
        self.assertEqual(self.one(found, "Undated")["state"], "stale")
        self.assertEqual(self.one(found, "Old")["state"], "stale")
        self.assertEqual(self.one(found, "Recent")["state"], "idle")

    def test_counted_and_kept_out_of_rows(self):
        found = self.make_backlog()
        self.assertEqual(found["counts"]["stale"], 2)
        self.assertEqual([r["what"] for r in found["rows"]], ["Recent"])

    def test_shown_as_one_collapsed_row(self):
        found = self.make_backlog()
        backlog = [r for r in found["top"] if r["state"] == "stale"]
        self.assertEqual(len(backlog), 1)
        self.assertEqual(len(backlog[0]["members"]), 2)
        self.assertIn("backlog", backlog[0]["what"])
        self.assertIn("| backlog |", ga.render(found))


class UnverifiedTest(AuditCase):
    def tier(self, found, text):
        hits = [r for r in found["rows"] if r["kind"] == "unverified" and text in r["what"]]
        self.assertEqual(len(hits), 1, found["rows"])
        return hits[0]["tier"]

    def test_broken_proposed_and_due_recheck(self):
        self.make(verif=[verif_row("#101 export", "broken"), verif_row("#102 retry", "proposed"),
                         verif_row("#103 refund", "not-exercised", recheck="2026-11-18 10:00"),
                         verif_row("#104 later", "not-exercised", recheck="2026-11-25 10:00"),
                         verif_row("#105 fine", "verified")])
        found = self.audit()
        self.assertEqual(self.tier(found, "#101"), "broken")
        self.assertEqual(self.tier(found, "#102"), "proposed")
        self.assertEqual(self.tier(found, "#103"), "recheck")
        self.assertFalse([r for r in found["rows"] if "#104" in r["what"] or "#105" in r["what"]])

    def test_running_for_over_a_day(self):
        self.make(verif=[verif_row("#106 slow", "running", checked="2026-11-17 10:00"),
                         verif_row("#107 new", "running", checked="2026-11-19 09:00")])
        found = self.audit()
        self.assertEqual(self.tier(found, "#106"), "unverified")
        self.assertFalse([r for r in found["rows"] if "#107" in r["what"]])

    def test_same_verification_collapses_with_the_first(self):
        self.make(verif=[verif_row("#101 export", "broken"),
                         verif_row("#104 export again", "broken", evidence="see #101 (same verification)")])
        top = self.audit()["top"]
        self.assertEqual(len(top), 1)
        self.assertTrue(top[0]["key"].endswith("+1"))
        self.assertEqual(len(top[0]["members"]), 2)

    def test_unrelated_broken_rows_stay_apart(self):
        self.make(verif=[verif_row("#101 export", "broken"), verif_row("#108 other", "broken")])
        self.assertEqual(len(self.audit()["top"]), 2)


class LongWaitsTest(AuditCase):
    def test_wait_over_a_day_is_listed(self):
        self.make(waiting=["| helper [dddddd] | Merge #7 | %s | %s |" % (stamp(27), stamp(-3))])
        found = self.audit()
        waits = [r for r in found["rows"] if r["kind"] == "waiting"]
        self.assertEqual([r["key"] for r in waits], ["dddddd"])
        self.assertEqual(found["counts"]["waiting"], 1)

    def test_recent_wait_is_not_listed(self):
        self.make(waiting=["| helper [dddddd] | Merge #7 | %s | %s |" % (stamp(2), stamp(-3))])
        self.assertEqual([r for r in self.audit()["rows"] if r["kind"] == "waiting"], [])


class DecisionsTest(AuditCase):
    def listed(self, decisions, open_=()):
        self.make(open_=list(open_), decisions=decisions)
        return [r["key"] for r in self.audit()["rows"] if r["kind"] == "decision"]

    def test_recent_unreferenced_decision_is_listed(self):
        keys = self.listed(["1. (11-18 10:10, user in guide) Build the exporter.",
                            "2. (11-10 10:10, user in guide) Build the old importer."])
        self.assertEqual(keys, ["D1"])

    def test_decision_named_elsewhere_is_not_listed(self):
        keys = self.listed(["1. (11-18 10:10, user) Build the exporter.", "2. (11-18 10:20, user) Ship the importer.",
                            "3. (11-18 10:30, user) Add a CSV mode."],
                           open_=["| Build D2 importer | new session | 11-17 |",
                                  "| Per Decision 3: CSV | new session | 11-17 |"])
        self.assertEqual(keys, ["D1"])

    def test_decision_worded_as_an_answer_is_not_listed(self):
        keys = self.listed(["1. (11-18 10:10, user) Build the exporter.",
                            "2. (11-18 10:20, user) Dropped the importer.",
                            "3. (11-18 10:30, user) Not now: the mobile app.",
                            "4. (11-18 10:40, user) Rule SATISFIED by cron."])
        self.assertEqual(keys, ["D1"])

    def test_set_done_removes_it(self):
        self.make(decisions=["1. (%s 10:10, user in guide) Build the exporter." % day(1)])
        self.assertEqual([r["key"] for r in self.real()["rows"] if r["kind"] == "decision"], ["D1"])
        self.cli("set", "D1", "done")
        self.assertEqual([r["key"] for r in self.real()["rows"] if r["kind"] == "decision"], [])


class SessionRowsTest(AuditCase):
    def sessions(self, **said):
        """Sessions rows and transcripts 3 h old: {rid: name} -> said text (None: nothing said)."""
        rows = []
        for rid, (name, text) in said.items():
            rows.append(session_row(name, rid))
            self.transcript(rid, ago=3 * 3600, said=text)
        self.make(sessions=rows)
        return ga.audit(self.ledger, full=True, now=NOW)

    def listed(self, found):
        return {r["key"]: r["why"] for r in found["rows"] if r["kind"] == "session"}

    def test_no_result_line(self):
        found = self.sessions(aaaaaa=("reindex", "all finished here"))
        self.assertEqual(self.listed(found), {"aaaaaa": "no result line"})

    def test_result_says_not_finished(self):
        found = self.sessions(aaaaaa=("reindex", "work\nresult: blocked on review"))
        self.assertEqual(self.listed(found), {"aaaaaa": "result says not finished"})

    def test_clean_result_is_not_listed(self):
        found = self.sessions(aaaaaa=("reindex", "work\nresult: done, merged"))
        self.assertEqual((self.listed(found), found["clean"]), ({}, 1))

    def test_pr_without_merge_in_ledger(self):
        found = self.sessions(aaaaaa=("reindex", "result: opened #321 for review"))
        self.assertIn("#321", self.listed(found)["aaaaaa"])

    def test_relay_judges_only_the_newest(self):
        rows = [session_row("build", "a1a1a1"), session_row("build 2", "b2b2b2"), session_row("build (3)", "c3c3c3")]
        for rid, ago in (("a1a1a1", 8), ("b2b2b2", 6), ("c3c3c3", 4)):
            self.transcript(rid, ago=ago * 3600, said="no result here")
        self.make(sessions=rows)
        found = ga.audit(self.ledger, full=True, now=NOW)
        self.assertEqual(list(self.listed(found)), ["c3c3c3"])
        self.assertEqual(found["clean"], 2)

    def test_recent_transcript_is_not_judged_yet(self):
        rows = [session_row("busy", "aaaaaa")]
        self.transcript("aaaaaa", ago=600, said="working")
        self.make(sessions=rows)
        self.assertEqual(self.listed(ga.audit(self.ledger, full=True, now=NOW)), {})

    def test_quick_audit_keeps_the_last_full_audits_sessions(self):
        self.make(sessions=[session_row("reindex", "aaaaaa")])
        self.transcript("aaaaaa", ago=3 * 3600, said="no result here", now=time.time())
        self.assertEqual(ga.run(self.ledger)["counts"]["sessions"], 1)
        quick = ga.run(self.ledger, full=False)
        self.assertEqual(quick["counts"]["sessions"], 1)
        self.assertEqual([r["key"] for r in quick["rows"] if r["kind"] == "session"], ["aaaaaa"])
        self.assertEqual(self.real()["counts"]["sessions"], 1)


class RankingTest(AuditCase):
    def row(self, tier, days, what="x", why=""):
        return dict(tier=tier, age=days * DAY, what=what, why=why)

    def test_broken_outranks_idle_of_same_age(self):
        self.assertGreater(ga.score(self.row("broken", 2)), ga.score(self.row("idle", 2)))

    def test_older_idle_outranks_newer(self):
        self.assertGreater(ga.score(self.row("idle", 3)), ga.score(self.row("idle", 1)))

    def test_age_is_capped(self):
        self.assertEqual(ga.score(self.row("idle", ga.AGE_CAP)), ga.score(self.row("idle", 20)))
        self.assertGreater(ga.score(self.row("idle", ga.AGE_CAP)), ga.score(self.row("idle", ga.AGE_CAP - 1)))

    def test_urgent_words_rank_higher_and_minor_lower(self):
        base = ga.score(self.row("idle", 2, "fix the export"))
        self.assertAlmostEqual(ga.score(self.row("idle", 2, "fix the prod export")), base * 1.5)
        self.assertAlmostEqual(ga.score(self.row("idle", 2, "fix the export, a glance")), base * 0.5)

    def test_undated_row_takes_half_the_window(self):
        self.assertAlmostEqual(ga.score(dict(tier="idle", age=None, what="x", why="")), 3 * ga.DAYS / 2)


class CollapseTest(AuditCase):
    def three_owners(self):
        self.make(open_=["| Alpha | new session (a) | 11-17 |", "| Bravo | new session (b) | 11-17 |",
                         "| Charlie | new session | 11-17 |"])
        return self.audit()

    def test_same_owner_head_collapses(self):
        found = self.three_owners()
        self.assertEqual(len(found["top"]), 1)
        top = found["top"][0]
        self.assertRegex(top["key"], r"^[0-9a-f]{6}\+2$")
        self.assertEqual({m["what"] for m in top["members"]}, {"Alpha", "Bravo", "Charlie"})

    def test_queue_file_rows_collapse(self):
        path = os.path.join(self.cfg, "q.md")
        with open(path, "w") as f:
            f.write("| Id | What |\n|---|---|\n| G1 | one |\n| G2 | two |\n| G3 | three |\n")
        self.make(open_=[])
        top = self.audit(queues=[path])["top"]
        self.assertEqual(len(top), 1)
        self.assertTrue(top[0]["key"].endswith("+2"))

    def people(self):
        self.make(open_=["| Item %s | %s | 11-17 |" % (n, n) for n in PEOPLE])
        return self.audit()

    def data_lines(self, text):
        return [l for l in text.splitlines() if re.match(r"\| [0-9a-f]{6}(\+\d+)? \|", l)]

    def test_render_shows_top_rows_and_the_rest_as_a_count(self):
        text = ga.render(self.people())
        self.assertEqual(len(self.data_lines(text)), ga.TOP)
        self.assertIn("… and 2 more row(s)", text)

    def test_render_limit(self):
        text = ga.render(self.people(), limit=12)
        self.assertEqual(len(self.data_lines(text)), 12)
        self.assertNotIn("more row(s)", text)

    def test_render_group_lists_members(self):
        found = self.three_owners()
        key = found["top"][0]["key"]
        for given in (key, key.split("+")[0]):
            text = ga.render(found, group=given)
            self.assertEqual(len(self.data_lines(text)), 3)
            self.assertTrue(all(w in text for w in ("Alpha", "Bravo", "Charlie")))
        self.assertIn("No row has the key", ga.render(found, group="ffffff"))

    def test_render_everything_lists_every_item(self):
        self.assertEqual(len(self.data_lines(ga.render(self.people(), everything=True))), len(PEOPLE))

    def test_render_of_an_empty_audit(self):
        self.make(open_=[])
        self.assertEqual(ga.render(self.audit()), "Nothing idle, unverified or stuck.")


class SetTest(AuditCase):
    def items(self, *rows):
        self.make(open_=["| %s | new session | %s |" % (r, day(2)) for r in rows])

    def keys(self, *rows):
        return [ga.item_key(r) for r in rows]

    def test_by_key(self):
        self.items("Alpha", "Bravo")
        out = self.cli("set", self.keys("Alpha")[0], "done")
        self.assertIn("done", out)
        self.assertIn("Also set the Status of each Open items row to DONE", out)
        self.assertEqual(self.whats(self.real()), {"Bravo"})

    def test_by_ticket_when_one_item_names_it(self):
        self.items("Ship ABC-77 now", "Bravo")
        self.cli("set", "ABC-77", "parked")
        self.assertEqual(self.one(self.real(), "ABC-77")["state"], "parked")

    def test_ticket_named_by_two_items_is_an_error(self):
        self.items("Fix ABC-5 login", "Test ABC-5 export")
        with self.assertRaises(SystemExit) as caught:
            self.cli("set", "ABC-5", "done")
        self.assertIn("names 2 audit items", str(caught.exception))

    def test_unknown_key_is_an_error(self):
        self.items("Alpha")
        with self.assertRaises(SystemExit):
            self.cli("set", "ffffff", "done")

    def test_several_keys(self):
        self.items("Alpha", "Bravo", "Charlie")
        self.cli("set", ",".join(self.keys("Alpha", "Bravo")), "parked")
        found = self.real()
        self.assertEqual(found["counts"]["parked"], 2)
        self.assertEqual(self.whats(found) - {"Alpha", "Bravo"}, {"Charlie"})

    def test_collapsed_key_marks_every_member(self):
        self.make(open_=["| Alpha | new session (a) | %s |" % day(2), "| Bravo | new session (b) | %s |" % day(2),
                         "| Charlie | new session | %s |" % day(2)])
        key = self.real()["top"][0]["key"]
        self.assertTrue(key.endswith("+2"))
        self.cli("set", key, "parked")
        found = self.real()
        self.assertEqual((found["counts"]["parked"], found["rows"]), (3, []))

    def test_started_needs_a_session(self):
        self.items("Alpha")
        with self.assertRaises(SystemExit) as caught:
            self.cli("set", self.keys("Alpha")[0], "started")
        self.assertIn("--session", str(caught.exception))

    def test_started_with_a_live_session_is_moving(self):
        self.make(open_=["| Alpha | new session | %s |" % day(2)], sessions=[session_row("w", "bbbbbb")])
        sid = self.transcript("bbbbbb", ago=600, now=time.time())
        self.cli("set", self.keys("Alpha")[0], "started", "--session", sid)
        mark = ga.load_state(self.ledger)["items"][self.keys("Alpha")[0]]
        self.assertEqual((mark["state"], mark["session"]), ("started", sid))
        self.assertEqual(self.real()["counts"]["moving"], 1)

    def test_asked_holds_for_twelve_hours(self):
        self.items("Alpha")
        self.cli("set", self.keys("Alpha")[0], "asked", "--note", "in the interview")
        mark = ga.load_state(self.ledger)["items"][self.keys("Alpha")[0]]
        self.assertAlmostEqual(mark["until"] - mark["at"], ga.ASKED_HOURS * 3600)
        self.assertEqual(mark["note"], "in the interview")
        self.assertEqual(self.real()["counts"]["asked"], 1)

    def test_done_stays_out_of_the_next_audit(self):
        self.items("Alpha")
        self.cli("set", self.keys("Alpha")[0], "done")
        found = self.real()
        self.assertEqual((found["rows"], found["hidden"], found["counts"]["idle"]), ([], [], 0))


class FilesTest(AuditCase):
    def idle_ledger(self):
        return self.make(open_=["| Alpha | new session | %s |" % day(3)])

    def test_run_writes_state_and_audit_json(self):
        self.idle_ledger()
        ga.run(self.ledger)
        folder = os.path.dirname(self.ledger)
        self.assertTrue(os.path.isfile(os.path.join(folder, "STATE.md")))
        self.assertTrue(os.path.isfile(os.path.join(folder, "audit.json")))

    def test_state_file_headings(self):
        self.idle_ledger()
        ga.run(self.ledger)
        text = open(ga.state_paths(self.ledger)[1]).read()
        for heading in ("## Open sessions", "## Reminders", "## Results with no verdict",
                        "## Not done or not verified"):
            self.assertIn(heading, text)
        self.assertIn("Alpha", text)

    def test_audit_json_has_quick_counts(self):
        self.idle_ledger()
        ga.run(self.ledger)
        counts = json.load(open(ga.state_paths(self.ledger)[0]))["quick"]["counts"]
        self.assertEqual((counts["idle"], counts["nag"]), (1, 1))
        self.assertAlmostEqual(counts["oldest"], 3 * DAY, delta=DAY)

    def test_cached_returns_the_counts(self):
        self.idle_ledger()
        self.assertEqual(ga.cached(self.ledger), {})
        found = ga.run(self.ledger)
        self.assertEqual(ga.cached(self.ledger), json.loads(json.dumps(found["counts"])))

    def test_full_run_records_when_it_ran(self):
        self.idle_ledger()
        ga.run(self.ledger, full=False)
        self.assertNotIn("full_at", ga.load_state(self.ledger))
        ga.run(self.ledger)
        self.assertIn("full_at", ga.load_state(self.ledger))

    def test_state_command_prints_state_md(self):
        self.idle_ledger()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ga.main(["state", self.ledger])
        self.assertIn("## Not done or not verified", out.getvalue())

    def test_audit_command_prints_table_and_state_path(self):
        self.idle_ledger()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ga.main(["audit", self.ledger, "--quick"])
        self.assertIn("| Key | Age | Kind |", out.getvalue())
        self.assertIn("State file: " + ga.state_paths(self.ledger)[1], out.getvalue())


class HookTest(AuditCase):
    def test_nags_about_an_old_idle_item(self):
        self.make(open_=["| Alpha | new session | %s |" % day(3)])
        text = ga.hook_context(self.ledger)
        self.assertIn("1 idle in all", text)
        self.assertIn(ga.item_key("Alpha"), text)

    def test_idle_item_under_the_threshold_is_not_nagged(self):
        self.make(open_=["| Alpha | new session | %s |" % day(0)])
        with mock.patch.dict(os.environ, SESSION_GUIDE_IDLE_HOURS="100"):
            self.assertNotIn("decided item", ga.hook_context(self.ledger) or "")

    def test_says_the_look_back_is_due(self):
        self.make(open_=[])
        text = ga.hook_context(self.ledger)
        self.assertIn("look back", text)
        self.assertIn("is due", text)
        self.assertIn("never", text)

    def test_quiet_after_a_full_audit_with_nothing_idle(self):
        self.make(open_=[])
        ga.run(self.ledger)
        self.assertIsNone(ga.hook_context(self.ledger))

    def test_off_with_zero_hours(self):
        self.make(open_=["| Alpha | new session | %s |" % day(3)])
        with mock.patch.dict(os.environ, SESSION_GUIDE_AUDIT_HOURS="0"):
            self.assertIsNone(ga.hook_context(self.ledger))

    def test_idle_counts_after_a_run(self):
        self.make(open_=["| Alpha | new session | %s |" % day(3)])
        ga.run(self.ledger)
        count, age = gt.idle_counts(self.ledger)
        self.assertEqual(count, 1)
        self.assertRegex(age, r"^\d+[hd]$")

    def test_idle_counts_format(self):
        self.make(open_=[])
        for oldest, expected in ((9 * 3600 + 5, "9h"), (4 * DAY + 100, "4d")):
            with open(ga.state_paths(self.ledger)[0], "w") as f:
                json.dump({"quick": {"counts": {"idle": 2, "oldest": oldest}}}, f)
            self.assertEqual(gt.idle_counts(self.ledger), (2, expected))

    def test_idle_counts_without_a_run(self):
        self.make(open_=[])
        self.assertEqual(gt.idle_counts(self.ledger), (0, ""))


class TitleWiringTest(AuditCase):
    def script(self, *args, stdin=""):
        return subprocess.run([sys.executable, TITLE_SCRIPT] + list(args), input=stdin, capture_output=True, text=True,
                              env=dict(os.environ))

    def title(self):
        stdin = json.dumps({"session_id": GUIDE, "hook_event_name": "UserPromptSubmit"})
        return json.loads(self.script("hook", stdin=stdin).stdout)["hookSpecificOutput"]["sessionTitle"]

    def guide_ledger(self, idle):
        open_ = ["| Alpha | new session | %s |" % day(3)] if idle else []
        self.make(open_=open_, sessions=[session_row("billing lead", "3fa9c1")])
        self.transcript("3fa9c1", ago=60, now=time.time())

    def test_title_shows_idle_count(self):
        self.guide_ledger(idle=True)
        self.script("mark", self.ledger, "--session", GUIDE)
        self.assertRegex(self.title(), r"· 1 idle \d+[hd]\)")

    def test_title_has_no_idle_when_none_are(self):
        self.guide_ledger(idle=False)
        self.script("mark", self.ledger, "--session", GUIDE)
        self.assertNotIn("idle", self.title())

    def test_default_title_template_has_idle_note(self):
        self.assertIn("{idle_note}", gt.TITLE)

    def test_settle_prints_the_audit_when_something_is_idle(self):
        self.guide_ledger(idle=True)
        out = self.script("settle", self.ledger).stdout
        self.assertIn("Audit: ", out)
        self.assertIn("| Key | Age | Kind |", out)
        self.assertIn("Alpha", out)

    def test_settle_prints_no_audit_when_nothing_is_idle(self):
        self.guide_ledger(idle=False)
        self.assertNotIn("Audit:", self.script("settle", self.ledger).stdout)

    def test_mark_prints_the_audit_and_state_path(self):
        self.guide_ledger(idle=True)
        out = self.script("mark", self.ledger, "--session", GUIDE).stdout
        self.assertIn("Audit: ", out)
        self.assertIn(ga.state_paths(self.ledger)[1], out)
        self.assertTrue(os.path.isfile(ga.state_paths(self.ledger)[1]))

    def test_mark_prints_no_audit_when_nothing_is_idle(self):
        self.guide_ledger(idle=False)
        self.assertNotIn("Audit:", self.script("mark", self.ledger, "--session", GUIDE).stdout)

    def test_retire_refreshes_state_file(self):
        self.guide_ledger(idle=True)
        self.script("mark", self.ledger, "--session", GUIDE)
        os.remove(ga.state_paths(self.ledger)[1])
        self.script("retire", GUIDE)
        self.assertTrue(os.path.isfile(ga.state_paths(self.ledger)[1]))


if __name__ == "__main__":
    unittest.main()
