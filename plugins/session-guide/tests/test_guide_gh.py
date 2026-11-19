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


class PrStateTest(unittest.TestCase):
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

    def tearDown(self):
        shutil.rmtree(self.dir)

    def run_gh(self, *answers):
        return mock.patch.object(guide_gh.subprocess, "run", side_effect=list(answers))

    def test_open_pr_with_repo(self):
        with self.run_gh(done('{"state":"OPEN","mergedAt":null}')) as run:
            got = guide_gh.pr_state("#12", "acme/widgets", cache=self.cache, now=NOW)
        self.assertEqual(got, {"state": "OPEN", "mergedAt": None})
        cmd, kwargs = run.call_args[0][0], run.call_args[1]
        self.assertEqual(cmd, ["gh", "pr", "view", "12", "--repo", "acme/widgets", "--json", "state,mergedAt"])
        self.assertEqual(kwargs["timeout"], 5)

    def test_merged_pr_without_repo(self):
        with self.run_gh(done('{"state":"MERGED","mergedAt":"2026-11-19T12:00:00Z"}')) as run:
            got = guide_gh.pr_state(12, cache=self.cache, now=NOW)
        self.assertEqual(got, {"state": "MERGED", "mergedAt": "2026-11-19T12:00:00Z"})
        self.assertNotIn("--repo", run.call_args[0][0])

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
                self.assertIsNone(guide_gh.pr_state(12, cache=self.cache, now=NOW))
                run.assert_not_called()

    def test_not_installed(self):
        self.which.return_value = None
        with self.run_gh() as run:
            self.assertIsNone(guide_gh.pr_state(12, cache=self.cache, now=NOW))
            run.assert_not_called()
        self.assertFalse(os.path.exists(self.cache))

    def test_failures_are_none_and_cached(self):
        cases = [done("", code=1), done("not json"), done('{"state":"DRAFT"}'), done("[]"),
                 subprocess.TimeoutExpired(cmd="gh", timeout=5), OSError("exec format error")]
        for i, case in enumerate(cases):
            with self.run_gh(case) as run:
                self.assertIsNone(guide_gh.pr_state(100 + i, cache=self.cache, now=NOW), case)
                self.assertIsNone(guide_gh.pr_state(100 + i, cache=self.cache, now=NOW + 60), case)
                self.assertEqual(run.call_count, 1, case)

    def test_bad_number(self):
        with self.run_gh() as run:
            for bad in ("", "abc", None, 0, "#-3"):
                self.assertIsNone(guide_gh.pr_state(bad, cache=self.cache, now=NOW))
            run.assert_not_called()

    def test_unreadable_cache_is_ignored(self):
        with open(self.cache, "w") as f:
            f.write("{broken")
        with self.run_gh(done('{"state":"OPEN","mergedAt":null}')):
            self.assertEqual(guide_gh.pr_state(12, cache=self.cache, now=NOW)["state"], "OPEN")

    def test_unwritable_cache_still_answers(self):
        path = os.path.join(self.dir, "no-such-dir", "x", "gh-cache.json")
        os.makedirs(os.path.dirname(os.path.dirname(path)))
        open(os.path.dirname(path), "w").close()  # a file where the folder should be
        with self.run_gh(done('{"state":"OPEN","mergedAt":null}')):
            self.assertEqual(guide_gh.pr_state(12, cache=path, now=NOW)["state"], "OPEN")

    def test_default_cache_beside_guide_state(self):
        with self.run_gh(done('{"state":"OPEN","mergedAt":null}')):
            guide_gh.pr_state(12, "acme/widgets", now=NOW)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "session-guide", "gh-cache.json")))

    def test_any_error_fails_open(self):
        with mock.patch.object(guide_gh, "load_cache", side_effect=RuntimeError("boom")):
            self.assertIsNone(guide_gh.pr_state(12, cache=self.cache, now=NOW))


if __name__ == "__main__":
    unittest.main()
