#!/usr/bin/env python3
"""Tests for skills/session-guide/scripts/guide_gh.py. subprocess.run and shutil.which are mocked: no test calls gh."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "session-guide", "scripts"))
import guide_gh  # noqa: E402

NOW = 1795000000.0


def done(stdout, code=0):
    return subprocess.CompletedProcess(args=["gh"], returncode=code, stdout=stdout, stderr="")


class GhBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="guide-gh-")
        self.cache = os.path.join(self.dir, "gh-cache.json")
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.dir})
        env.start()
        os.environ.pop(guide_gh.SWITCH, None)
        self.addCleanup(env.stop)
        which = mock.patch.object(guide_gh.shutil, "which", return_value="/usr/local/bin/gh")
        self.which = which.start()
        self.addCleanup(which.stop)
        guide_gh.clear_budget()
        self.addCleanup(guide_gh.clear_budget)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def run_gh(self, *answers):
        return mock.patch.object(guide_gh.subprocess, "run", side_effect=list(answers))


class PrStateTest(GhBase):

    def test_open_pr_with_repo(self):
        with self.run_gh(done('{"state":"OPEN","mergedAt":null}')) as run:
            got = guide_gh.pr_state("#12", "acme/widgets", cache=self.cache, now=NOW)
        self.assertEqual(got, {"state": "OPEN", "mergedAt": None})
        cmd, kwargs = run.call_args[0][0], run.call_args[1]
        self.assertEqual(cmd, ["gh", "pr", "view", "12", "--repo", "acme/widgets", "--json", "state,mergedAt"])
        self.assertEqual(kwargs["timeout"], 5)

    def test_merged_pr(self):
        with self.run_gh(done('{"state":"MERGED","mergedAt":"2026-11-19T12:00:00Z"}')):
            got = guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW)
        self.assertEqual(got, {"state": "MERGED", "mergedAt": "2026-11-19T12:00:00Z"})

    def test_no_repo_never_runs_gh(self):
        """Without a repo gh answers for the current directory's repository: another repo's PR #12."""
        with self.run_gh() as run:
            for repo in (None, "", "  ", "widgets", "acme/", "../x"):
                self.assertIsNone(guide_gh.pr_state(12, repo, cache=self.cache, now=NOW), repo)
            run.assert_not_called()
        self.assertFalse(os.path.exists(self.cache))

    def test_answer_cached_ten_minutes(self):
        with self.run_gh(done('{"state":"OPEN","mergedAt":null}'),
                         done('{"state":"MERGED","mergedAt":"2026-11-19T12:00:00Z"}')) as run:
            first = guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW)
            again = guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW + 599)
            self.assertEqual(run.call_count, 1)
            later = guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW + 601)
            self.assertEqual(run.call_count, 2)
        self.assertEqual(first, again)
        self.assertEqual(later["state"], "MERGED")
        with open(self.cache) as f:
            self.assertEqual(len(json.load(f)), 1)

    def test_other_repo_is_another_entry(self):
        with self.run_gh(done('{"state":"OPEN","mergedAt":null}'), done('{"state":"CLOSED","mergedAt":null}')) as run:
            guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW)
            got = guide_gh.pr_state(12, "acme/gadgets", cache=self.cache, now=NOW)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(got["state"], "CLOSED")

    def test_switch_off(self):
        for value in ("0", "off", "no", "false"):
            with mock.patch.dict(os.environ, {guide_gh.SWITCH: value}), self.run_gh() as run:
                self.assertIsNone(guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW))
                run.assert_not_called()

    def test_not_installed(self):
        self.which.return_value = None
        with self.run_gh() as run:
            self.assertIsNone(guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW))
            run.assert_not_called()
        self.assertFalse(os.path.exists(self.cache))

    def test_failures_are_none_and_cached(self):
        cases = [done("", code=1), done("not json"), done('{"state":"DRAFT"}'), done("[]"),
                 subprocess.TimeoutExpired(cmd="gh", timeout=5), OSError("exec format error")]
        for i, case in enumerate(cases):
            with self.run_gh(case) as run:
                self.assertIsNone(guide_gh.pr_state(100 + i, "acme/widgets", cache=self.cache, now=NOW), case)
                self.assertIsNone(guide_gh.pr_state(100 + i, "acme/widgets", cache=self.cache, now=NOW + 60), case)
                self.assertEqual(run.call_count, 1, case)

    def test_bad_number(self):
        with self.run_gh() as run:
            for bad in ("", "abc", None, 0, "#-3"):
                self.assertIsNone(guide_gh.pr_state(bad, "acme/widgets", cache=self.cache, now=NOW))
            run.assert_not_called()

    def test_unreadable_cache_is_ignored(self):
        with open(self.cache, "w") as f:
            f.write("{broken")
        with self.run_gh(done('{"state":"OPEN","mergedAt":null}')):
            self.assertEqual(guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW)["state"], "OPEN")

    def test_unwritable_cache_still_answers(self):
        path = os.path.join(self.dir, "no-such-dir", "x", "gh-cache.json")
        os.makedirs(os.path.dirname(os.path.dirname(path)))
        open(os.path.dirname(path), "w").close()  # a file where the folder should be
        with self.run_gh(done('{"state":"OPEN","mergedAt":null}')):
            self.assertEqual(guide_gh.pr_state(12, "acme/widgets", cache=path, now=NOW)["state"], "OPEN")

    def test_default_cache_beside_guide_state(self):
        with self.run_gh(done('{"state":"OPEN","mergedAt":null}')):
            guide_gh.pr_state(12, "acme/widgets", now=NOW)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "session-guide", "gh-cache.json")))

    def test_any_error_fails_open(self):
        with mock.patch.object(guide_gh, "load_cache", side_effect=RuntimeError("boom")):
            self.assertIsNone(guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW))


class BudgetTest(GhBase):
    """set_budget(): one deadline for every gh call of a hook run; a spent budget is "unchecked", never cached."""

    def test_each_call_gets_the_time_left(self):
        clock = [100.0]
        with mock.patch.object(guide_gh.time, "monotonic", lambda: clock[0]):
            self.assertEqual(guide_gh.set_budget(3), 3)
            clock[0] = 101.0
            with self.run_gh(done('{"state":"OPEN","mergedAt":null}')) as run:
                guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW)
            self.assertAlmostEqual(run.call_args[1]["timeout"], 2.0)

    def test_spent_budget_skips_gh_and_caches_nothing(self):
        clock = [100.0]
        with mock.patch.object(guide_gh.time, "monotonic", lambda: clock[0]):
            guide_gh.set_budget(3)
            clock[0] = 104.0
            with self.run_gh() as run:
                self.assertIsNone(guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW))
                run.assert_not_called()
        self.assertFalse(os.path.exists(self.cache))
        guide_gh.clear_budget()  # the next prompt (no budget here) asks again at once
        with self.run_gh(done('{"state":"MERGED","mergedAt":"2026-11-19T12:00:00Z"}')) as run:
            self.assertEqual(guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW + 1)["state"], "MERGED")
            self.assertEqual(run.call_count, 1)

    def test_call_cut_by_the_budget_is_not_cached(self):
        guide_gh.set_budget(1)
        with self.run_gh(subprocess.TimeoutExpired(cmd="gh", timeout=1), done('{"state":"OPEN","mergedAt":null}')) as run:
            self.assertIsNone(guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW))
            guide_gh.clear_budget()
            self.assertEqual(guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW + 1)["state"], "OPEN")
            self.assertEqual(run.call_count, 2)

    def test_budget_from_env_default_three(self):
        with mock.patch.dict(os.environ, {"SESSION_GUIDE_GH_BUDGET": "1.5"}):
            self.assertEqual(guide_gh.set_budget(), 1.5)
        with mock.patch.dict(os.environ, {"SESSION_GUIDE_GH_BUDGET": "x"}):
            self.assertEqual(guide_gh.set_budget(), 3.0)
        os.environ.pop("SESSION_GUIDE_GH_BUDGET", None)
        self.assertEqual(guide_gh.set_budget(), 3.0)

    def test_cached_answer_still_served_when_spent(self):
        with self.run_gh(done('{"state":"OPEN","mergedAt":null}')):
            guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW)
        guide_gh.set_budget(0)
        with self.run_gh() as run:
            self.assertEqual(guide_gh.pr_state(12, "acme/widgets", cache=self.cache, now=NOW + 5)["state"], "OPEN")
            run.assert_not_called()


class RepoForTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="guide-gh-repo-")
        self.addCleanup(shutil.rmtree, self.dir)
        self.ledger = os.path.join(self.dir, "ledger.md")

    def scope(self, line, section=""):
        with open(self.ledger, "w") as f:
            f.write("# t — guide ledger\nGuide: 'g' [c0ffee12]\n%s\n\n## Sessions\n| a | b |\n%s" % (line, section))
        return self.ledger

    def test_text_ref_and_link(self):
        self.assertEqual(guide_gh.repo_for(None, "merge acme/widgets#12 today", 12), "acme/widgets")
        self.assertEqual(guide_gh.repo_for(None, "https://github.com/acme/gadgets/pull/7", 7), "acme/gadgets")
        self.assertEqual(guide_gh.repo_for(None, "acme/widgets#12 and acme/gadgets#7", 7), "acme/gadgets")
        self.assertEqual(guide_gh.repo_for(None, "after acme/widgets#12, #13 too", 13), "acme/widgets")
        self.assertIsNone(guide_gh.repo_for(None, "acme/widgets#12 and acme/gadgets#7", 9))

    def test_scope_names_one_repo(self):
        ledger = self.scope("Scope: t · host1 · ~/.claude · uds:/tmp/cc-socks/1.sock · repo acme/widgets")
        self.assertEqual(guide_gh.repo_for(ledger, "Merge #12 when green", 12), "acme/widgets")
        ledger = self.scope("Scope: t · host1 · /Users/someone/.claude · uds:/tmp/cc-socks/1.sock")
        self.assertIsNone(guide_gh.repo_for(ledger, "#12", 12))  # paths and sockets are not repos
        ledger = self.scope("Scope: t · host1 · https://github.com/acme/widgets")
        self.assertEqual(guide_gh.repo_for(ledger, "#12", 12), "acme/widgets")
        ledger = self.scope("Scope: t · acme/widgets, acme/gadgets")
        self.assertIsNone(guide_gh.repo_for(ledger, "#12", 12))  # two repos: can't tell
        ledger = self.scope("Scope: t · host1", "\n## Scope\n- repo: acme/widgets\n")
        self.assertEqual(guide_gh.repo_for(ledger, "#12", 12), "acme/widgets")

    def test_nothing_known(self):
        self.assertIsNone(guide_gh.repo_for(None, "Merge #12", 12))
        self.assertIsNone(guide_gh.repo_for(os.path.join(self.dir, "missing.md"), "#12", 12))
        self.assertIsNone(guide_gh.repo_for(None, "see docs/how-it-works.md for #12", 12))


if __name__ == "__main__":
    unittest.main()
