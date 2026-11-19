#!/usr/bin/env python3
"""Tests for skills/session-guide/scripts/guide_claims.py. Every test uses its own temp CLAUDE_CONFIG_DIR and ledger;
gh is never called: guide_gh's subprocess.run and shutil.which are mocked, or gh is switched off."""
import argparse
import contextlib
import io
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
SCRIPT = os.path.join(SCRIPTS, "guide_claims.py")
sys.path.insert(0, SCRIPTS)
import guide_claims as gc  # noqa: E402
import guide_gh  # noqa: E402

HOUR = 3600
NOW = time.mktime(time.localtime())  # the ledger's dates below are today's, so the 3-day window holds them
TODAY = time.strftime("%m-%d", time.localtime(NOW))
OLD = time.strftime("%m-%d", time.localtime(NOW - 10 * 86400))
LEDGER = """# widgets-2026 — guide ledger
Guide: 'release guide' [c0ffee12] since {today} 09:00

## Sessions
| Title [id6] | Level | Role / stream | Worktree @ sha | Address | Ctx | Last seen |
|---|---|---|---|---|---|---|
| widgets lead [3fa9c1] | MANAGED | widgets | worktrees/widgets @a1b2c3d | uds | 80k | 12:35 |

## Open items
| Item | Owner | Next action | Status |
|---|---|---|---|
| {today} Orders backfill after the deploy: `! make backfill-orders` | the user | run it | ASK {today} 13:05 |

## Verifications
| Thing | Where | Result | Checked | Evidence / session | Re-check |
|---|---|---|---|---|---|
| #31 export retry | staging | verified | 2026-11-19 10:00 | 'verify #31' [9a8b7c]: ok | — |

## Log (last ~15)
- {today} 12:40 widgets lead: MERGE READY #12 (acme/widgets), asked the user to merge
- {today} 12:50 Dana tells the ops team to turn the export flag on
- {today} 12:55 MERGE READY #31; #20 merged, MERGE READY #20 earlier
- {old} 09:00 MERGE READY #7, asked the user
- ~~{today} 12:58 MERGE READY #44~~
""".format(today=TODAY, old=OLD)


def gh_answer(state, merged_at=None):
    body = '{"state":"%s","mergedAt":%s}' % (state, '"%s"' % merged_at if merged_at else "null")
    return subprocess.CompletedProcess(args=["gh"], returncode=0, stdout=body, stderr="")


class ClaimsBase(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="guide-claims-")
        self.ledger = os.path.join(self.cfg, "session-guide", "widgets-2026", "ledger.md")
        self.cache = os.path.join(self.cfg, "gh-cache.json")
        os.makedirs(os.path.dirname(self.ledger))
        with open(self.ledger, "w") as f:
            f.write(LEDGER)
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.cfg})
        env.start()
        for name in ("SESSION_GUIDE_GH", "SESSION_GUIDE_CLAIM_HOURS", "SESSION_GUIDE_CLAIM_DAYS",
                     "CLAUDE_CODE_SESSION_ID"):
            os.environ.pop(name, None)
        self.addCleanup(env.stop)
        which = mock.patch.object(guide_gh.shutil, "which", return_value="/usr/local/bin/gh")
        which.start()
        self.addCleanup(which.stop)

    def tearDown(self):
        shutil.rmtree(self.cfg)

    def gh(self, *answers):
        return mock.patch.object(guide_gh.subprocess, "run", side_effect=list(answers))

    def text(self):
        with open(self.ledger) as f:
            return f.read()

    def run_script(self, *args):
        env = dict(os.environ, SESSION_GUIDE_GH="0")
        return subprocess.run([sys.executable, SCRIPT, "claim"] + list(args) + ["--ledger", self.ledger],
                              capture_output=True, text=True, env=env)


class TableTest(ClaimsBase):
    def test_merge_claim_row_and_header(self):
        row = gc.add_merge(self.ledger, "#12", "acme/widgets", now=NOW)
        text = self.text()
        self.assertIn("## Claims\n| Claim [key] | What | By | Claimed | Evidence |\n|---|---|---|---|---|\n", text)
        self.assertIn("| merge [%s] | acme/widgets#12 | the user | %s | — |" % (row["key"], gc.stamp(NOW)), text)
        self.assertLess(text.index("## Claims"), text.index("## Open items"))
        self.assertEqual(gc.add_merge(self.ledger, "https://github.com/acme/widgets/pull/12")["key"], row["key"])
        self.assertEqual(self.text().count("acme/widgets#12"), 1)

    def test_run_claim_keeps_pipes_and_first_time(self):
        first = gc.add_run(self.ledger, "! psql -c 'select 1' | tee out.txt", "Dana", now=NOW - 2 * HOUR)
        again = gc.add_run(self.ledger, "psql -c 'select 1' | tee out.txt", "Dana", now=NOW)
        self.assertEqual(first["key"], again["key"])
        rows = gc.claim_rows(self.ledger)
        self.assertEqual(rows[first["key"]]["command"], "psql -c 'select 1' | tee out.txt")
        self.assertEqual(rows[first["key"]]["claimed"], gc.stamp(NOW - 2 * HOUR))

    def test_done_by_key_and_by_number(self):
        merge = gc.add_merge(self.ledger, "#12", "acme/widgets", now=NOW)
        run = gc.add_run(self.ledger, "make backfill-orders", "the user", now=NOW)
        gc.close_claim(self.ledger, "#12", "merged @d4e5f6a", now=NOW)
        gc.close_claim(self.ledger, run["key"], "4,210 rows", now=NOW)
        rows = gc.claim_rows(self.ledger)
        self.assertFalse(rows[merge["key"]]["open"])
        self.assertEqual(rows[run["key"]]["evidence"], "done %s: 4,210 rows" % gc.stamp(NOW))
        with self.assertRaises(SystemExit):
            gc.close_claim(self.ledger, "abcdef", "x")
        with self.assertRaises(SystemExit):
            gc.close_claim(self.ledger, run["key"], "  ")

    def test_run_needs_who(self):
        with self.assertRaises(SystemExit):
            gc.add_run(self.ledger, "make x", "")


class HookTest(ClaimsBase):
    def test_open_pr_stays_listed(self):
        row = gc.add_merge(self.ledger, "#12", "acme/widgets", now=NOW - HOUR)
        with self.gh(gh_answer("OPEN")) as run:
            lines = gc.hook_lines(self.ledger, now=NOW, cache=self.cache)
            again = gc.hook_lines(self.ledger, now=NOW + 60, cache=self.cache)  # cached: no second gh call
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args[0][0][:6], ["gh", "pr", "view", "12", "--repo", "acme/widgets"])
        mine = [l for l in lines if row["key"] in l]
        self.assertEqual(len(mine), 1)
        self.assertIn("still OPEN", mine[0])
        self.assertIn("#12", mine[0])
        self.assertEqual(lines, again)
        self.assertTrue(gc.claim_rows(self.ledger)[row["key"]]["open"])

    def test_merged_pr_closes_itself_once(self):
        row = gc.add_merge(self.ledger, "#12", "acme/widgets", now=NOW - HOUR)
        with self.gh(gh_answer("MERGED", "2026-11-19T11:30:00Z")):
            lines = gc.hook_lines(self.ledger, now=NOW, cache=self.cache)
            later = gc.hook_lines(self.ledger, now=NOW + 60, cache=self.cache)
        said = [l for l in lines if row["key"] in l]
        self.assertEqual(len(said), 1)
        self.assertIn("merged", said[0])
        self.assertIn("2026-11-19T11:30:00Z", said[0])
        self.assertFalse([l for l in later if row["key"] in l])
        closed = gc.claim_rows(self.ledger)[row["key"]]
        self.assertFalse(closed["open"])
        self.assertTrue(closed["evidence"].startswith("merged 2026-11-19T11:30:00Z (gh, checked "))

    def test_closed_unmerged_and_gh_off_stay_listed(self):
        gc.add_merge(self.ledger, "#12", "acme/widgets", now=NOW)
        with self.gh(gh_answer("CLOSED")):
            self.assertTrue(any("closed without merging" in l for l in gc.hook_lines(self.ledger, NOW, self.cache)))
        os.environ["SESSION_GUIDE_GH"] = "0"
        with self.gh() as run:
            lines = gc.hook_lines(self.ledger, NOW + 3600, self.cache + ".2")
            run.assert_not_called()
        self.assertTrue(any("not checked" in l and "#12" in l for l in lines))

    def test_run_claim_with_no_evidence_after_hours(self):
        row = gc.add_run(self.ledger, "make backfill-orders", "Dana", now=NOW - 5 * HOUR)
        listed = [l for l in gc.hook_lines(self.ledger, now=NOW, cache=self.cache) if row["key"] in l]
        self.assertEqual(len(listed), 1)
        self.assertIn("no evidence after 4 h", listed[0])
        self.assertFalse([l for l in gc.hook_lines(self.ledger, now=NOW - 2 * HOUR, cache=self.cache)
                          if row["key"] in l])
        os.environ["SESSION_GUIDE_CLAIM_HOURS"] = "8"
        self.assertFalse([l for l in gc.hook_lines(self.ledger, now=NOW, cache=self.cache) if row["key"] in l])

    def test_run_claim_with_evidence_not_listed(self):
        row = gc.add_run(self.ledger, "make backfill-orders", "the user", now=NOW - 9 * HOUR)
        gc.close_claim(self.ledger, row["key"], "4,210 rows backfilled", now=NOW - 8 * HOUR)
        self.assertFalse([l for l in gc.hook_lines(self.ledger, now=NOW, cache=self.cache) if row["key"] in l])
        self.assertFalse([u for u in gc.unclaimed(self.ledger, days=3, now=NOW) if "backfill-orders" in u["ref"]])

    def test_hook_counts_unclaimed_and_fails_open(self):
        lines = gc.hook_lines(self.ledger, now=NOW, cache=self.cache)
        self.assertTrue(any(l.startswith("Unclaimed: 3 ledger lines from the last 3 days") for l in lines), lines)
        with mock.patch.object(gc, "claim_rows", side_effect=RuntimeError("boom")):
            self.assertEqual(gc.hook_lines(self.ledger, now=NOW, cache=self.cache), [])


class RepoTest(ClaimsBase):
    def add_scope(self, line):
        text = self.text().replace("\n\n## Sessions", "\n%s\n\n## Sessions" % line, 1)
        with open(self.ledger, "w") as f:
            f.write(text)

    def test_merge_claim_with_no_repo_never_asks_gh(self):
        row = gc.add_merge(self.ledger, "#12", now=NOW)
        with self.gh(gh_answer("MERGED", "2026-11-19T11:30:00Z")) as run:
            lines = gc.hook_lines(self.ledger, now=NOW, cache=self.cache)
            run.assert_not_called()  # gh in the current directory would answer for some other repo's #12
        mine = [l for l in lines if row["key"] in l]
        self.assertEqual(len(mine), 1)
        self.assertIn("repo unknown: add --repo", mine[0])
        self.assertTrue(gc.claim_rows(self.ledger)[row["key"]]["open"])

    def test_scope_repo_is_used(self):
        self.add_scope("Scope: widgets-2026 · host1 · ~/.claude · uds:/tmp/cc-socks/1.sock · repo acme/widgets")
        row = gc.add_merge(self.ledger, "#12", now=NOW)
        self.assertEqual(row["what"], "acme/widgets#12")
        with self.gh(gh_answer("MERGED", "2026-11-19T11:30:00Z")) as run:
            gc.hook_lines(self.ledger, now=NOW, cache=self.cache)
        self.assertEqual(run.call_args[0][0][3:6], ["12", "--repo", "acme/widgets"])
        self.assertFalse(gc.claim_rows(self.ledger)[row["key"]]["open"])

    def test_adding_the_repo_replaces_the_bare_claim(self):
        bare = gc.add_merge(self.ledger, "#12", now=NOW - HOUR)
        full = gc.add_merge(self.ledger, "#12", "acme/widgets", now=NOW)
        rows = gc.claim_rows(self.ledger)
        self.assertNotIn(bare["key"], rows)
        self.assertEqual(rows[full["key"]]["claimed"], gc.stamp(NOW - HOUR))

    def test_unchecked_merge_stays_open_and_is_asked_again(self):
        row = gc.add_merge(self.ledger, "#12", "acme/widgets", now=NOW)
        with self.gh(subprocess.TimeoutExpired(cmd="gh", timeout=1), gh_answer("MERGED", "2026-11-19T11:30:00Z")):
            guide_gh.set_budget(1)
            try:
                first = gc.hook_lines(self.ledger, now=NOW, cache=self.cache)
            finally:
                guide_gh.clear_budget()
            self.assertTrue(any("not checked" in l for l in first if row["key"] in l))
            self.assertTrue(gc.claim_rows(self.ledger)[row["key"]]["open"])
            gc.hook_lines(self.ledger, now=NOW + 60, cache=self.cache)
        self.assertFalse(gc.claim_rows(self.ledger)[row["key"]]["open"])


class FindClaimTest(ClaimsBase):
    def test_done_with_a_bare_number(self):
        row = gc.add_merge(self.ledger, "#123", "acme/widgets", now=NOW)
        gc.close_claim(self.ledger, "123", "merged @d4e5f6a", now=NOW)
        self.assertFalse(gc.claim_rows(self.ledger)[row["key"]]["open"])

    def test_digits_never_prefix_match_a_key(self):
        rows = {"123abc": dict(key="123abc", kind="run", command="make x", number=None, repo=None),
                "9f0b3d": dict(key="9f0b3d", kind="merge", command=None, number=123, repo="acme/widgets")}
        self.assertEqual(gc.find_claim(rows, "123")["key"], "9f0b3d")
        self.assertEqual(gc.find_claim(rows, "123abc")["key"], "123abc")
        self.assertEqual(gc.find_claim(rows, "123a")["key"], "123abc")
        with self.assertRaises(SystemExit):
            gc.find_claim({"123abc": rows["123abc"]}, "123")


class UnclaimedTest(ClaimsBase):
    def refs(self, **kw):
        return {(u["kind"], u["ref"]) for u in gc.unclaimed(self.ledger, now=NOW, **kw)}

    def test_lines_with_no_claim_row(self):
        found = self.refs(days=3)
        self.assertIn(("cmd", "make backfill-orders"), found)  # a "! cmd" line with no claim row
        self.assertIn(("merge", "acme/widgets#12"), found)  # "#12 (acme/widgets)" names its repo
        self.assertIn(("ask", "Dana tells"), found)
        self.assertEqual(len(found), 3, found)  # #31 has a Verifications row, #20 is merged, #7 is old, #44 struck

    def test_whole_ledger(self):
        self.assertIn(("merge", "#7"), self.refs(days=0))

    def test_claimed_lines_drop_out(self):
        gc.add_merge(self.ledger, "#12", now=NOW)
        gc.add_run(self.ledger, "make backfill-orders", "the user", now=NOW)
        self.assertEqual(self.refs(days=3), {("ask", "Dana tells")})

    def test_bang_only_for_commands(self):
        with open(self.ledger, "a") as f:
            f.write("- %s 13:00 Great! the export works; use `color: red !important` and `!important` in the css\n"
                    "- %s 13:01 the user said hi !there\n" % (TODAY, TODAY))
            f.write("! make reindex-all\n- ! make reindex-one\n| %s | ! make reindex-cell | the user |\n" % TODAY)
        found = {r for k, r in self.refs(days=0) if k == "cmd"}
        self.assertNotIn("important", " ".join(found))
        self.assertFalse([r for r in found if "there" in r or "export" in r])
        self.assertTrue({"make reindex-all", "make reindex-one", "make reindex-cell"} <= found, found)

    def test_not_people(self):
        with open(self.ledger, "a") as f:
            f.write("- %s 13:00 CI runs the battery nightly; the guide runs settle\n" % TODAY)
        self.assertFalse([r for r in self.refs(days=3) if "CI" in r[1]])


class CliTest(ClaimsBase):
    def test_standalone_commands(self):
        out = self.run_script("merge", "#12", "--repo", "acme/widgets")
        self.assertEqual(out.returncode, 0, out.stderr)
        key = out.stdout.split("[", 1)[1][:6]
        out = self.run_script("run", "make backfill-orders", "--by", "the user")
        self.assertEqual(out.returncode, 0, out.stderr)
        out = self.run_script("list")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("not checked", out.stdout)
        self.assertIn("Unclaimed: L", out.stdout)
        self.assertIn("2 open claims, 0 closed, 1 unclaimed line", out.stdout)
        out = self.run_script("done", key, "merged @d4e5f6a")
        self.assertEqual(out.returncode, 0, out.stderr)
        out = self.run_script("list", "--all")
        self.assertIn("Closed: [%s]" % key, out.stdout)
        self.assertNotEqual(self.run_script("run", "make x").returncode, 0)  # --by is required

    def test_mounts_on_another_parser(self):
        p = argparse.ArgumentParser()
        sub = p.add_subparsers(dest="cmd", required=True)
        gc.add_parser(sub)
        args = p.parse_args(["claim", "run", "make x", "--by", "Dana", "--ledger", self.ledger])
        self.assertEqual((args.cmd, args.claim_cmd, args.command, args.by), ("claim", "run", "make x", "Dana"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(gc.cmd_claim(args), 0)
        self.assertIn("Dana runs `make x`", out.getvalue())
        self.assertEqual(len(gc.claim_rows(self.ledger)), 1)


if __name__ == "__main__":
    unittest.main()
