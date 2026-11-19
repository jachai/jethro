"""0.2.3: the update check falls back to the marketplace clone; a watcher exits once its code was updated away."""
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import build  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import update  # noqa: E402
import watch  # noqa: E402

GIT = shutil.which("git")
KEY = common.PLUGIN_KEY


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "-c", "commit.gpgsign=false"] + list(args), check=True, capture_output=True)


def commit_version(repo, version):
    os.makedirs(os.path.join(repo, ".claude-plugin"), exist_ok=True)
    with open(os.path.join(repo, ".claude-plugin", "plugin.json"), "w") as f:
        json.dump({"name": "artifact-explorer", "version": version}, f)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", version)


def origin_and_clone(first, later=None):
    """A local "GitHub" (bare repo) at `first`, a marketplace clone of it, then `later` pushed to the origin only."""
    root = helpers.tmp()
    origin, work, clone = (os.path.join(root, n) for n in ("origin.git", "work", "clone"))
    subprocess.run(["git", "init", "-q", "--bare", origin], check=True)
    subprocess.run(["git", "init", "-q", work], check=True)
    git(work, "checkout", "-q", "-b", "main")
    commit_version(work, first)
    git(work, "push", "-q", origin, "main")
    subprocess.run(["git", "--git-dir", origin, "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
    subprocess.run(["git", "clone", "-q", origin, clone], check=True)
    if later:
        commit_version(work, later)
        git(work, "push", "-q", origin, "main")
    return clone


def config_dir(installed=(), market=None):
    """A CLAUDE_CONFIG_DIR: installed_plugins.json entries [(version, installPath)], known_marketplaces -> market."""
    cfg = helpers.tmp()
    plugins = os.path.join(cfg, "plugins")
    os.makedirs(plugins)
    ents = [{"scope": "user", "version": v, "installPath": p} for v, p in installed]
    json.dump({"version": 2, "plugins": {KEY: ents} if ents else {}},
              open(os.path.join(plugins, "installed_plugins.json"), "w"))
    json.dump({"artifact-explorer": {"installLocation": market}} if market else {},
              open(os.path.join(plugins, "known_marketplaces.json"), "w"))
    return cfg


class Env(unittest.TestCase):
    def use(self, **env):
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)


@unittest.skipUnless(GIT, "needs git")
class CloneFallback(Env):
    def test_reads_the_origin_default_branch_and_leaves_the_clone_alone(self):
        clone = origin_and_clone("0.2.2", later="0.2.3")
        head = subprocess.run(["git", "-C", clone, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        self.assertEqual(update.fetch_clone(clone), "v0.2.3")
        after = subprocess.run(["git", "-C", clone, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        self.assertEqual(head, after)  # no branch moved, nothing checked out
        on_disk = json.load(open(os.path.join(clone, ".claude-plugin", "plugin.json")))["version"]
        self.assertEqual(on_disk, "0.2.2")

    def test_finds_the_clone_through_known_marketplaces(self):
        clone = origin_and_clone("0.2.2", later="0.3.0")
        self.use(CLAUDE_CONFIG_DIR=config_dir(market=clone))
        self.assertEqual(update.fetch_clone(), "v0.3.0")

    def test_no_marketplace_or_not_a_repo_is_no_news(self):
        self.use(CLAUDE_CONFIG_DIR=config_dir())
        self.assertIsNone(update.fetch_clone())
        self.assertIsNone(update.fetch_clone(helpers.tmp()))

    def test_api_answer_wins_and_the_clone_is_only_asked_when_it_has_none(self):
        with mock.patch.object(update, "fetch_release", return_value="v0.4.0"), \
                mock.patch.object(update, "fetch_clone", return_value="v0.3.0") as clone:
            self.assertEqual(update.fetch("0.2.2"), "v0.4.0")
        clone.assert_not_called()
        with mock.patch.object(update, "fetch_release", return_value=None), \
                mock.patch.object(update, "fetch_clone", return_value="v0.3.0"):
            self.assertEqual(update.fetch("0.2.2"), "v0.3.0")

    def test_private_repo_page_shows_the_badge(self):
        """The 0.2.2 bug: the API answers 404 for a private repo, so the badge never showed."""
        clone = origin_and_clone("0.2.2", later="9.1.0")
        self.use(CLAUDE_CONFIG_DIR=config_dir(market=clone), AE_UPDATE_CHECK="1")
        d = helpers.tmp()
        con = db.connect(d)
        db.upsert_artifact(con, "aaaaaaaaaa", title="t", owned=1)
        con.commit()
        con.close()
        with mock.patch.object(update, "fetch_release", return_value=None):
            html = open(build.build(d, max_age=0), encoding="utf-8").read()
        self.assertIn('"latest": "v9.1.0"', html)
        self.assertIn("/plugin update artifact-explorer@artifact-explorer", html)
        self.assertEqual(json.load(open(os.path.join(d, "update.json")))["latest"], "v9.1.0")


class Superseded(Env):
    def setUp(self):
        self.root = helpers.tmp()  # this watcher's code folder

    def test_updated_away_to_a_newer_version(self):
        self.use(CLAUDE_CONFIG_DIR=config_dir([("0.2.3", os.path.join(helpers.tmp(), "0.2.3"))]))
        self.assertEqual(watch.superseded(self.root, "0.2.0"), "0.2.3")

    def test_still_installed_here_keeps_running(self):
        """Another scope may have the newer version; this one still points at this code."""
        self.use(CLAUDE_CONFIG_DIR=config_dir([("0.2.3", os.path.join(helpers.tmp(), "0.2.3")),
                                               ("0.2.0", self.root)]))
        self.assertIsNone(watch.superseded(self.root, "0.2.0"))

    def test_not_newer_or_not_installed_keeps_running(self):
        self.use(CLAUDE_CONFIG_DIR=config_dir([("0.1.9", os.path.join(helpers.tmp(), "0.1.9"))]))
        self.assertIsNone(watch.superseded(self.root, "0.2.0"))
        self.use(CLAUDE_CONFIG_DIR=config_dir())
        self.assertIsNone(watch.superseded(self.root, "0.2.0"))  # a dev checkout run by hand

    def test_loop_exits_before_any_pass_and_logs_why(self):
        self.use(CLAUDE_CONFIG_DIR=config_dir([("99.0.0", os.path.join(helpers.tmp(), "99.0.0"))]))
        data = helpers.tmp()
        with mock.patch.object(watch, "tick") as tick:
            self.assertEqual(watch.loop(data, tick_seconds=0, max_ticks=5), 0)
        tick.assert_not_called()
        self.assertIn("99.0.0 is installed", open(os.path.join(data, "watch.log")).read())

    def test_loop_runs_when_current(self):
        self.use(CLAUDE_CONFIG_DIR=config_dir([(common.own_version(), common.ROOT)]))
        with mock.patch.object(watch, "tick") as tick:
            watch.loop(helpers.tmp(), tick_seconds=0, max_ticks=2)
        self.assertEqual(tick.call_count, 2)


if __name__ == "__main__":
    unittest.main()
