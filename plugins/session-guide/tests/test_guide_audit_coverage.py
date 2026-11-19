#!/usr/bin/env python3
"""Tests for guide_audit.py's later-evidence check (covered, check rows), the strike sweep, `closes:` tags,
shared_ids, ledger lines dated after now, and the quiet-worker and handed-off fixes.

The fixtures are shaped like two real cases (an Open items row whose artifact had two later satisfied Results rows; an
owed question whose two tickets were in the brief of a later session with a satisfied Results row), with invented
names and ids. Every test builds its own ledger in a temp CLAUDE_CONFIG_DIR; gh is a fake module (AuditCase)."""
import contextlib
import io
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_guide_audit import DAY, NOW, OPEN_HEAD, SESSIONS_HEAD, WAITING_HEAD, AuditCase, day, ga, session_row  # noqa: E402

RESULTS_HEAD = ["| Deliverable | Link | Delivered | Asked | Answer |", "|---|---|---|---|---|"]
ART = "Zq7Lm2Pw9Xc4Rt6Yb8Nh3K"  # an invented 22-character artifact id
EVENING = time.mktime((2026, 11, 19, 17, 0, 0, 0, 0, -1))


def section(title, head, rows):
    return [title] + head + list(rows) + [""]


def text(*parts, log=()):
    out = ["# t — guide ledger", "Guide: 'g' [c0ffee12] since 11-01 09:00", ""]
    for part in parts:
        out += part
    return "\n".join(out + ["## Log (last ~15)"] + list(log)) + "\n"


def when(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


class CoverageCase(AuditCase):
    def write(self, *parts, log=()):
        with open(self.ledger, "w") as f:
            f.write(text(*parts, log=log))
        return self.ledger

    def at(self, now, **kw):
        return ga.audit(self.ledger, full=False, now=now, **kw)


class OpenItemCoveredTest(CoverageCase):
    def deck_ledger(self, answers=("satisfied 2026-11-16 19:16", "satisfied 2026-11-19 10:51")):
        self.write(section("## Open items", OPEN_HEAD, [
            "| Vendor deck: after the user and Sam walk the 7 decisions on review comments v5 (%s), update the deck and "
            "the plan tab | guide | ASK 11-16 13:00 |" % ART]),
            section("## Results for you", RESULTS_HEAD, [
                "| review comments v7 (deck lead [a1b2c3]) | https://claude.ai/artifact/%s | 2026-11-16 18:00 | "
                "2026-11-16 18:00 | %s |" % (ART, answers[0]),
                "| plan doc rev 705 (plan lead [b2c3d4]) | https://claude.ai/artifact/%s | 2026-11-19 10:00 | "
                "2026-11-19 10:00 | %s |" % (ART, answers[1])]))

    def test_artifact_with_two_later_satisfied_results_is_check_not_ask(self):
        self.deck_ledger()
        found = self.audit()
        row = self.one(found, "Vendor deck")
        self.assertEqual(row["state"], "check")
        self.assertEqual(len(row["evidence"]), 2)
        self.assertTrue(all(e.startswith("Results ") for e in row["evidence"]))
        self.assertTrue(row["next"].startswith("likely done: Results 'review comments v7"))
        self.assertIn('Confirm, then `set %s done "<evidence>"`. Do not ask the user.' % row["key"], row["next"])
        self.assertEqual((found["counts"]["idle"], found["counts"]["nag"], found["counts"]["check"]), (0, 0, 1))
        self.assertNotIn("ask now", ga.render(found))
        self.assertIn("| check |", ga.render(found))

    def test_unanswered_results_are_no_evidence(self):
        self.deck_ledger(answers=("—", "change it 2026-11-19 10:51: shorter"))
        row = self.one(self.audit(), "Vendor deck")
        self.assertEqual(row["state"], "idle")
        self.assertEqual(row["checked"], "checked 11-19: still open because no later evidence")

    def test_evidence_older_than_the_row_does_not_count(self):
        self.write(section("## Open items", OPEN_HEAD, ["| Rework the %s export | guide | ASK 11-17 10:00 |" % ART]),
                   section("## Results for you", RESULTS_HEAD, [
                       "| old export (x [a1b2c3]) | https://claude.ai/artifact/%s | 2026-11-10 10:00 | 2026-11-10 10:00 | "
                       "satisfied 2026-11-10 11:00 |" % ART]))
        self.assertEqual(self.one(self.audit(), "export")["state"], "idle")

    def test_row_with_no_later_evidence_stays_ask(self):
        self.write(section("## Open items", OPEN_HEAD, ["| Fix ABC-4400 rounding | guide | ASK 11-17 |",
                                                        "| Tidy the readme | guide | ASK 11-17 |"]))
        found = self.audit()
        with_id, no_id = self.one(found, "ABC-4400"), self.one(found, "readme")
        self.assertEqual((with_id["state"], no_id["state"]), ("idle", "idle"))
        self.assertEqual(with_id["checked"], "checked 11-19: still open because no later evidence")
        self.assertEqual(no_id["checked"], "checked 11-19: still open because no id to match")
        self.assertEqual(found["counts"]["nag"], 2)
        self.assertIn("still open because", ga.render(found, everything=True))

    def test_done_session_decision_verification_and_duplicate_reminder(self):
        self.write(section("## Open items", OPEN_HEAD, ["| Ship ABC-501 | guide | ASK 11-17 |",
                                                        "| Merge #4321 | ASK | ASK 11-17 |",
                                                        "| Check ABC-777 numbers | guide | ASK 11-17 |"]),
                   section("## Sessions", SESSIONS_HEAD, [
                       "| ABC-501 builder [d1d2d3] | DONE | closed 11-18 10:00 | wt | uds | 1k | 11-18 10:00 |"]),
                   section("## Verifications", ["| Thing | Where | Result | Checked | Evidence / session | Re-check |",
                                                "|---|---|---|---|---|---|"],
                           ["| #4321 export | prod | verified | 2026-11-18 09:00 | 40 exports | — |"]),
                   ["## Decisions (FINAL unless struck)", "7. (11-18 15:00, user in guide) ABC-777 is moot: dropped.", ""])
        found = self.audit()
        self.assertIn("Sessions 'ABC-501 builder' [d1d2d3] DONE", self.one(found, "ABC-501")["evidence"][0])
        self.assertIn("Verifications #4321 export verified", self.one(found, "#4321")["evidence"][0])
        self.assertIn("Decision 7", self.one(found, "ABC-777")["evidence"][0])

    def test_gh_merged_pr_is_evidence(self):
        self.write(section("## Open items", OPEN_HEAD, ["| Merge #4512 when CI is green | ASK | ASK 11-17 |"]))
        self.assertEqual(self.one(self.audit(), "#4512")["state"], "person")
        self.gh[4512] = {"state": "MERGED", "mergedAt": "2026-11-18T10:00:00Z"}
        row = self.one(self.audit(), "#4512")
        self.assertEqual((row["state"], row["evidence"]), ("check", ["gh: #4512 merged 2026-11-18"]))

    def test_gh_missing_is_no_evidence(self):
        self.write(section("## Open items", OPEN_HEAD, ["| Merge #4512 when CI is green | guide | ASK 11-17 |"]))
        sys.modules["guide_gh"] = None  # import guide_gh raises ImportError
        self.assertEqual(self.one(self.audit(), "#4512")["state"], "idle")

    def test_set_done_with_evidence_writes_the_row(self):
        self.write(section("## Open items", OPEN_HEAD, ["| Ship ABC-501 | guide | ASK %s |" % day(2)]))
        key = ga.item_key("Ship ABC-501")
        out = self.cli("set", key, "done", "merged as #4321, verified")
        self.assertNotIn("Also set the Status", out)
        self.assertIn("| Ship ABC-501 | guide | DONE %s: merged as #4321, verified; was: ASK %s |" % (day(0), day(2)),
                      open(self.ledger).read())
        self.assertEqual(self.whats(self.real()), set())


class ReminderCoveredTest(CoverageCase):
    QUESTION = "| owed question [4e5f60] | Did the user chase Sam on ABC-1201 + ABC-1302? | 2026-11-19 11:09 | 2026-11-19 15:09 |"

    def walkthrough(self, role="walkthrough cards", brief_dir="vendor-walkthrough-1119"):
        folder = os.path.join(os.path.dirname(self.ledger), "w9", brief_dir)
        os.makedirs(folder)
        with open(os.path.join(folder, "brief.md"), "w") as f:
            f.write("# Vendor walkthrough\n\nCard A: ABC-1201 export totals.\nCard B: ABC-1302 the retry.\n")
        self.write(section("## Sessions", SESSIONS_HEAD, [
            "| vendor walkthrough 11-19 [5a7c21] | DONE | %s | sonnet | — | 1k | 11-19 16:30 |" % role]),
            section("## Results for you", RESULTS_HEAD, [
                "| Vendor walkthrough 11-19 (14 cards) | https://claude.ai/artifact/x | 2026-11-19 16:10 | "
                "2026-11-19 16:10 | satisfied 2026-11-19 16:24 |"]),
            section("## Waiting on the user", WAITING_HEAD, [self.QUESTION]))

    def check(self, found):
        rows = [r for r in found["rows"] if r["key"] == "4e5f60"]
        self.assertEqual([r["state"] for r in rows], ["check"])
        self.assertTrue(found["reminders"]["4e5f60"].startswith("likely done: "))
        self.assertIn("Do not ask the user.", found["reminders"]["4e5f60"])
        return rows[0]

    def test_tickets_in_the_brief_of_a_later_satisfied_session_make_it_check(self):
        self.walkthrough()  # the Sessions row names no brief: its title's slug finds w9/vendor-walkthrough-1119
        row = self.check(self.at(EVENING))
        self.assertTrue(any("satisfied" in e and "brief" in e for e in row["evidence"]), row["evidence"])

    def test_brief_named_in_the_role_cell(self):
        self.walkthrough(role="cards from w9/cards-dir/brief.md", brief_dir="cards-dir")
        self.check(self.at(EVENING))

    def test_reminder_with_no_evidence_keeps_its_ask_with_a_note(self):
        self.write(section("## Waiting on the user", WAITING_HEAD, [self.QUESTION]))
        found = self.at(EVENING)
        self.assertEqual([r for r in found["rows"] if r["key"] == "4e5f60"], [])
        self.assertEqual(found["reminders"]["4e5f60"], "checked 11-19: still open because no later evidence")

    def test_set_done_on_a_covered_reminder_removes_it(self):
        self.write(section("## Sessions", SESSIONS_HEAD, [
            "| ABC-1201 export [5a7c21] | DONE | export | sonnet | — | 1k | %s |" % when(time.time() - 600)]),
            section("## Waiting on the user", WAITING_HEAD, [
                "| owed question [4e5f60] | Did the user chase Sam on ABC-1201? | %s | %s |" % (
                    when(time.time() - 3 * 3600), when(time.time() - 60))]))
        found = self.real()
        self.assertEqual([r["state"] for r in found["rows"] if r["key"] == "4e5f60"], ["check"])
        self.assertIn("1 open row(s) look done already", ga.hook_context(self.ledger))
        self.cli("set", "4e5f60", "done", "export session DONE")
        self.assertNotIn("4e5f60", open(self.ledger).read())

    def test_notes_reach_the_hook_cache(self):
        self.write(section("## Waiting on the user", WAITING_HEAD, [
            "| owed question [4e5f60] | Did the user chase Sam? | %s | %s |" % (when(time.time() - 3600),
                                                                              when(time.time() - 60))]))
        ga.run(self.ledger, full=False)
        self.assertIn("no id to match", ga.reminder_checks(self.ledger)["4e5f60"])


class StrikeTest(CoverageCase):
    def strike_ledger(self):
        return self.write(
            section("## Open items", OPEN_HEAD, ["| Ship ABC-501 | guide | ASK %s |" % day(5),
                                                 "| Tidy the readme | guide | ASK %s |" % day(4),
                                                 "| Price the vendor offer | Sam | ASK %s |" % day(4),
                                                 "| Keep this one | guide | ASK %s |" % day(4)]),
            section("## Waiting on the user", WAITING_HEAD, [
                "| owed question [4e5f60] | Did the user chase Sam? | %s | %s |" % (when(time.time() - 5 * DAY),
                                                                                  when(time.time() - DAY))]),
            log=["- %s 09:00 earlier line" % day(1)])

    def verdicts(self, *lines):
        path = os.path.join(self.cfg, "verdicts.md")
        with open(path, "w") as f:
            f.write("Strike sweep verdicts\n" + "\n".join(lines) + "\n")
        return path

    def test_strike_marks_exactly_the_listed_keys(self):
        self.strike_ledger()
        before = open(self.ledger).read().splitlines(True)
        ship, tidy, keep = (ga.item_key(t) for t in ("Ship ABC-501", "Tidy the readme", "Keep this one"))
        out = self.cli("strike", "--from", self.verdicts(
            "%s | DONE | merged as #4321 (Results row 12)" % ship, "- 4e5f60 | SUPERSEDED | asked again as ABC-9",
            "| %s | OPEN | nobody started it |" % tidy))
        self.assertEqual(out.splitlines()[0], "struck 2 stale rows, list in STATE.md")
        after = open(self.ledger).read().splitlines(True)
        expected = []
        for line in before:
            if line.startswith("| Ship ABC-501"):
                line = "| Ship ABC-501 | guide | DONE %s: merged as #4321 (Results row 12); was: ASK %s |\n" % (day(0), day(5))
            elif line.startswith("| Tidy the readme"):
                line = "| Tidy the readme | guide | ASK %s · checked %s |\n" % (day(4), day(0))
            elif line.startswith("| owed question [4e5f60]"):
                continue
            expected.append(line)
        self.assertEqual(after[:-1], expected)  # every other line byte for byte
        self.assertRegex(after[-1], r"^- \d\d-\d\d \d\d:\d\d guide_audit strike: struck 2 stale row\(s\) \(%s, 4e5f60\), "
                                    r"1 checked and still open \(%s\); list in STATE.md\n$" % (ship, tidy))
        found = self.real()
        listed = {r["key"] for r in found["rows"] + found["hidden"]}
        self.assertFalse({ship, "4e5f60"} & listed)
        self.assertTrue({tidy, keep} <= listed)
        self.assertEqual(self.one(found, "readme")["age"] // DAY, 4)  # the stamp is not the row's date
        self.assertIn("## Last strike sweep", open(ga.state_paths(self.ledger)[1]).read())
        self.assertIn(ship + " DONE", open(ga.state_paths(self.ledger)[1]).read())

    def test_open_rows_are_no_candidates_for_a_week(self):
        self.strike_ledger()
        tidy = ga.item_key("Tidy the readme")
        ga.run(self.ledger)
        self.assertIn(tidy, open(ga.strike_path(self.ledger)).read())
        self.cli("strike", "--from", self.verdicts("%s | OPEN | still wanted" % tidy))
        ga.run(self.ledger)
        candidates = open(ga.strike_path(self.ledger)).read()
        self.assertNotIn(tidy, candidates)
        self.assertIn(ga.item_key("Keep this one"), candidates)

    def test_unknown_key_is_reported_not_fatal(self):
        self.strike_ledger()
        out = self.cli("strike", "--from", self.verdicts("abcdef | DONE | gone"))
        self.assertIn("struck 0 stale rows", out)
        self.assertIn("abcdef", out)

    def test_file_with_no_verdicts_is_an_error(self):
        self.strike_ledger()
        with self.assertRaises(SystemExit):
            self.cli("strike", "--from", self.verdicts("nothing here"))

    def test_open_batch_groups_what_is_left(self):
        self.strike_ledger()
        ship = ga.item_key("Ship ABC-501")
        self.cli("strike", "--from", self.verdicts("%s | DONE | merged" % ship))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ga.main(["audit", self.ledger, "--open-batch"])
        out = out.getvalue()
        self.assertTrue(out.startswith("OPEN BATCH: 3 row(s) still open, in 2 group(s)."), out)
        self.assertIn("items for 'guide' with no worker: keep / start / drop. Keys: ", out)
        self.assertIn("items wait on Sam with no reminder: keep / start / drop", out)
        self.assertNotIn(ship, out)

    def test_hook_asks_for_a_sweep_when_the_last_is_over_a_day_old(self):
        self.strike_ledger()
        ga.run(self.ledger)
        self.assertIn("strike sweep", ga.hook_context(self.ledger))
        self.assertIn("(last sweep never)", ga.hook_context(self.ledger))
        for hours, asked in ((25, True), (1, False)):
            with self.subTest(hours=hours):
                state = ga.load_state(self.ledger)
                state["sweep_at"] = time.time() - hours * 3600
                ga.save(ga.state_paths(self.ledger)[0], ga.json.dumps(state))
                self.assertEqual("'strike sweep'" in (ga.hook_context(self.ledger) or ""), asked)


class ClosesTagTest(CoverageCase):
    def tagged(self, answer, level):
        return self.write(
            section("## Results for you", RESULTS_HEAD, [
                "| deck review (deck lead [a1b2c3]) | https://claude.ai/artifact/%s | %s | %s | %s |" % (
                    ART, when(time.time() - 3600), when(time.time() - 3600), answer)]),
            section("## Waiting on the user", WAITING_HEAD, [
                "| owed question [7a8b9c] | Ask the user about the deck review closes result:%s | %s | %s |" % (
                    ART, when(time.time() - 1800), when(time.time() + 3600))]),
            section("## Sessions", SESSIONS_HEAD, ["| exporter [5a7c21] | %s | closed | wt | uds | 1k | 12:00 |" % level]),
            section("## Open items", OPEN_HEAD, ["| Archive the exporter notes | guide | waiting; closes: session:5a7c21ab |"]))

    def test_reminder_closes_when_its_result_is_satisfied(self):
        self.tagged("—", "MANAGED")
        ga.run(self.ledger, full=False)
        self.assertIn("owed question [7a8b9c]", open(self.ledger).read())
        self.tagged("satisfied " + when(time.time()), "DONE")
        ga.run(self.ledger, full=False)
        ledger = open(self.ledger).read()
        self.assertNotIn("owed question [7a8b9c]", ledger)
        self.assertRegex(ledger, r"\| Archive the exporter notes \| guide \| DONE \d\d-\d\d: closes session:5a7c21ab: "
                                 r"Sessions \[5a7c21ab\] DONE; was: waiting; closes: session:5a7c21ab \|")
        text = ga.hook_context(self.ledger)
        self.assertIn("closed 2 row(s) whose `closes:` tag has happened", text)
        self.assertIn("7a8b9c reminder", text)
        self.assertNotIn("closes:` tag", ga.hook_context(self.ledger) or "")  # said once

    def test_pr_tag_closes_when_gh_says_merged(self):
        self.write(section("## Open items", OPEN_HEAD, ["| Follow the merge | guide | closes: pr:#4512 |"]))
        ga.run(self.ledger, full=False)
        self.assertIn("| Follow the merge | guide | closes: pr:#4512 |", open(self.ledger).read())
        self.gh[4512] = {"state": "MERGED", "mergedAt": "2026-11-18T10:00:00Z"}
        ga.run(self.ledger, full=False)
        self.assertIn("DONE", open(self.ledger).read().split("Follow the merge")[1].splitlines()[0])

    def test_shared_ids(self):
        self.write(section("## Open items", OPEN_HEAD, ["| Fix ABC-1201 totals | guide | ASK 11-17 |",
                                                        "| Unrelated | guide | ASK 11-17 |"]),
                   section("## Waiting on the user", WAITING_HEAD, [ReminderCoveredTest.QUESTION]))
        keys = ga.shared_ids(self.ledger, "walkthrough result for ABC-1201 and ABC-1302")
        self.assertEqual(keys, sorted([ga.item_key("Fix ABC-1201 totals"), "4e5f60"]))
        self.assertEqual(ga.shared_ids(self.ledger, "nothing to match"), [])
        self.assertEqual(ga.shared_ids(self.ledger, "ABC-1302", exclude=("4e5f60",)), [])


class FutureLinesTest(CoverageCase):
    def test_log_line_dated_tomorrow_is_flagged(self):
        self.write(section("## Waiting on the user", WAITING_HEAD, [
            "| owed question [4e5f60] | Ask | 2026-11-19 11:00 | 2026-11-20 09:00 |"]),
            ["## Decisions (FINAL unless struck)", "1. (11-19 10:00, user) Hold the release until 11-21.", ""],
            log=["- 11-19 11:50 deployed #12", "- 11-20 09:00 merged #13", "- 11-19 13:40 wrote the plan",
                 "- planned: the release goes out by 11-22"])
        found = self.audit()
        self.assertEqual([(n, written) for n, written, _ in found["future"]], [(14, "11-20 09:00"), (15, "11-19 13:40")])
        self.assertEqual(found["counts"]["future"], 2)
        self.assertIn("2 ledger line(s) dated after now", ga.summary(found))

    def test_hook_carries_the_clock_warning(self):
        tomorrow = time.strftime("%m-%d", time.localtime(time.time() + DAY))
        self.write(log=["- %s 09:00 merged #13" % tomorrow])
        text = ga.hook_context(self.ledger)
        self.assertIn("session-guide clock: 1 ledger line(s) carry a time after now", text)
        self.assertIn("%s 09:00" % tomorrow, text)


class WorkerMatchTest(CoverageCase):
    def test_older_managed_row_of_a_done_session_is_not_the_worker(self):
        self.write(section("## Open items", OPEN_HEAD, ["| Check the sweep job log for ABC-880 | guide | ASK 11-18 |"]),
                   section("## Sessions", SESSIONS_HEAD, [session_row("mailer sync", "9e8d7c", "DONE"),
                                                          "| mailer sync [9e8d7c] | MANAGED | mailer for ABC-880 | wt | uds | 1k | 12:00 |"]))
        row = self.one(self.audit(), "sweep job")
        self.assertEqual(row["state"], "idle", row["why"])

    def test_a_shared_version_is_not_a_worker_match(self):
        self.transcript("9e8d7c", ago=5 * 3600)
        self.write(section("## Open items", OPEN_HEAD, ["| Check the job log after the v2.1.0 install | guide | ASK 11-18 |",
                                                        "| Retry ABC-880 | guide | ASK 11-18 |"]),
                   section("## Sessions", SESSIONS_HEAD, [
                       "| mailer sync [9e8d7c] | MANAGED | mailer on v2.1.0, ABC-880 | wt | uds | 1k | 12:00 |"]))
        found = self.audit()
        self.assertEqual(self.one(found, "job log")["state"], "idle")
        self.assertEqual(self.one(found, "Retry")["state"], "quiet")  # a ticket still finds its worker


class HandedOffTest(CoverageCase):
    def listed(self, said):
        self.write(section("## Sessions", SESSIONS_HEAD, [session_row("plan", "aaaaaa")]))
        self.transcript("aaaaaa", ago=3 * 3600, said=said)
        return {r["key"]: r["why"] for r in ga.audit(self.ledger, full=True, now=NOW)["rows"] if r["kind"] == "session"}

    def test_deliverable_handed_off_to_the_guide_is_a_clean_end(self):
        self.assertEqual(self.listed("work\nresult: DONE, the plan doc is handed off to the guide"), {})

    def test_relay_handoff_is_not_finished(self):
        self.assertEqual(self.listed("work\nresult: HANDED OFF, context full; successor brief in STATE.md"),
                         {"aaaaaa": "result says not finished"})


if __name__ == "__main__":
    unittest.main()
