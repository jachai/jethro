"""0.1.5: a fresh-install test verifies itself (doctor, reset checks, post-install check, setup's first step),
the describer cap is not eaten by runs that never report, the describer is given its `ae` tool, setup says
whether the rule was already there and test-runs one row, and the page says unknown for what it can't know."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import helpers  # noqa: E402
import ae  # noqa: E402
import build  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402
import doctor  # noqa: E402

U = "https://claude.ai/artifact/"
A, B = "AAAAAAAAAAAA", "BBBBBBBBBBBB"
KEY = "artifact-explorer@jethro"


def run(*args):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = ae.main(list(args))
    return rc, out.getvalue()


def fake_config(installed=None, market=None, rule=True):
    """A CLAUDE_CONFIG_DIR with installed_plugins.json at version `installed` and a marketplace clone at `market`."""
    cfg = helpers.tmp()
    with open(os.path.join(cfg, "settings.json"), "w") as f:
        json.dump({"permissions": {"allow": [common.ALLOW_RULE] if rule else []}}, f)
    plugins = os.path.join(cfg, "plugins")
    os.makedirs(plugins)
    inst = {"version": 2, "plugins": {}}
    if installed:
        path = os.path.join(plugins, "cache", "jethro", "artifact-explorer", installed)
        os.makedirs(os.path.join(path, ".claude-plugin"))
        json.dump({"version": installed}, open(os.path.join(path, ".claude-plugin", "plugin.json"), "w"))
        inst["plugins"][KEY] = [{"scope": "user", "installPath": path, "version": installed,
                                 "lastUpdated": "2026-11-15T10:00:00.000Z"}]
    json.dump(inst, open(os.path.join(plugins, "installed_plugins.json"), "w"))
    known = {}
    if market:
        loc = os.path.join(plugins, "marketplaces", "jethro")
        os.makedirs(os.path.join(loc, ".claude-plugin"))
        json.dump({"version": market}, open(os.path.join(loc, ".claude-plugin", "plugin.json"), "w"))
        known["jethro"] = {"installLocation": loc}
    json.dump(known, open(os.path.join(plugins, "known_marketplaces.json"), "w"))
    return cfg


class Env(unittest.TestCase):
    def use(self, cfg):
        p = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfg})
        p.start()
        self.addCleanup(p.stop)


class Doctor(Env):
    def test_mismatch_is_reported_with_the_update_command(self):
        """The 0.1.4 test: marketplace at 0.1.4, installed_plugins still at 0.1.2."""
        self.use(fake_config("0.1.2", "0.1.4"))
        d = os.path.join(helpers.tmp(), "data")
        rc, out = run("--data", d, "doctor")
        self.assertEqual(rc, 1)
        self.assertIn("running: %s" % ae.VERSION, out)
        self.assertIn("installed (installed_plugins.json): 0.1.2", out)
        self.assertIn("marketplace clone: 0.1.4", out)
        self.assertIn("MISMATCH", out)
        self.assertIn("claude plugin update " + KEY, out)
        self.assertFalse(os.path.exists(d), "doctor must never create the data folder")

    def test_fresh_and_matching_is_ok(self):
        self.use(fake_config("0.1.5", "0.1.5"))
        d = os.path.join(helpers.tmp(), "data")
        rc, out = run("--data", d, "doctor", "--expect", "fresh")
        self.assertEqual(rc, 0, out)
        self.assertIn("(none yet: fresh)", out)
        self.assertIn("permission rule: present", out)
        self.assertIn("page check: status line ok, stale banner ok, initials tiles ok", out)
        self.assertIn("RESULT: OK", out)

    def test_rows_are_not_fresh(self):
        self.use(fake_config("0.1.5", "0.1.5"))
        d = helpers.tmp()
        con = db.connect(d)
        db.upsert_artifact(con, A, title="x")
        db.add_spend(con, 0.25)
        con.commit()
        con.close()
        rc, out = run("--data", d, "doctor")
        self.assertEqual(rc, 0)  # --expect any: reported, not failed
        self.assertIn("has 1 artifacts", out)
        self.assertIn("NOT a fresh install", out)
        rc, out = run("--data", d, "doctor", "--expect", "fresh")
        self.assertEqual(rc, 1)
        self.assertIn("the data folder already has a catalog", out)

    def test_not_installed(self):
        self.use(fake_config(None, None))
        rc, out = run("--data", os.path.join(helpers.tmp(), "x"), "doctor", "--expect", "installed")
        self.assertEqual(rc, 1)
        self.assertIn("not installed", out)
        self.assertIn("marketplace clone: not added", out)

    def test_window_running_an_older_cached_version(self):
        cfg = fake_config("0.1.5", "0.1.5")
        self.use(cfg)
        old = os.path.join(cfg, "plugins", "cache", "jethro", "artifact-explorer", "0.1.2")
        os.makedirs(old)
        with mock.patch.object(common, "ROOT", old):
            rc, out = run("--data", os.path.join(helpers.tmp(), "x"), "doctor")
        self.assertEqual(rc, 1)
        self.assertIn("NOTE: this window runs 0.1.2, not the installed 0.1.5", out)

    def test_page_check_fails_loudly(self):
        with mock.patch.object(build, "build", side_effect=OSError("nope")):
            self.assertEqual(doctor.page_check(), [("page build (OSError)", False)])

    def test_allow_rule(self):
        self.use(fake_config(rule=True))
        self.assertEqual(run("allow-rule")[0], 0)
        self.assertIn("present: ", run("allow-rule")[1])
        self.use(fake_config(rule=False))
        rc, out = run("allow-rule")
        self.assertEqual((rc, out.split(":")[0]), (1, "missing"))


class DescBase(Env):
    def setUp(self):
        self.use(fake_config(rule=True))
        self.d = helpers.tmp()
        f = os.path.join(self.d, "list.json")
        json.dump([{"url": U + x, "title": x, "scope": "mine"} for x in (A, B)], open(f, "w"))
        describe.ingest_list(self.d, f)
        for k, v in (("which", mock.patch("shutil.which", return_value="/bin/claude")),
                     ("det", mock.patch.object(common, "detach", return_value=4242)),
                     ("alive", mock.patch.object(common, "_pid_alive", return_value=True)),
                     ("cmd", mock.patch.object(common, "pid_cmdline", return_value="claude -p " + describe.RUN_MARK)),
                     ("stop", mock.patch.object(common, "stop_pid"))):
            setattr(self, k, v.start())
            self.addCleanup(v.stop)

    def con(self):
        return db.connect(self.d)

    def next_tick(self):
        con = self.con()
        db.state_set(con, "describer_last", time.time() - 3600)
        con.commit()

    def age(self, secs):
        path = os.path.join(self.d, describe.RUN_FILE)
        rec = json.load(open(path))
        rec["t"] = time.time() - secs
        json.dump(rec, open(path, "w"))

    def log(self):
        p = os.path.join(self.d, "watch.log")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


class CapAccounting(DescBase):
    def test_runs_that_never_report_cannot_eat_the_cap(self):
        """0.1.4: four >30 min runs that never reported booked $1.00. Now each gives its booking back, and after
        MAX_UNREPORTED of them the describer waits for the next day."""
        self.alive.return_value = False
        for _ in range(describe.MAX_UNREPORTED + 2):
            describe.launch(self.d)
            self.next_tick()
        self.assertEqual(self.det.call_count, describe.MAX_UNREPORTED)
        self.assertAlmostEqual(db.spend_today(self.con()), 0)
        self.assertIn("runs ended today without a cost report", self.log())

    def test_live_run_of_ours_is_waited_on_then_stopped(self):
        describe.launch(self.d)
        self.next_tick()
        self.age(describe.MAX_AGE + 60)
        describe.launch(self.d)
        self.assertEqual(self.det.call_count, 1)  # still our run: no second one
        self.assertIn("still ours, waiting", self.log())
        self.age(describe.HARD_AGE + 60)
        describe.launch(self.d)
        self.stop.assert_called_once_with(4242)
        self.assertEqual(self.det.call_count, 2)
        self.assertIn("stopped it", self.log())

    def test_reused_pid_is_not_waited_on(self):
        describe.launch(self.d)
        self.next_tick()
        self.age(describe.MAX_AGE + 60)
        self.cmd.return_value = "/usr/bin/some-other-process"
        describe.launch(self.d)
        self.assertEqual(self.det.call_count, 2)
        self.assertIn("no longer our run", self.log())
        self.assertFalse(self.stop.called)

    def test_stale_run_with_a_report_counts_its_real_cost(self):
        describe.launch(self.d)
        json.dump({"result": "described 2", "total_cost_usd": 0.02},
                  open(os.path.join(self.d, describe.OUT_FILE), "w"))
        con = self.con()  # 2 rows saved at $0.01 each: no back-off (0.2.7)
        for aid in (A, B):
            db.upsert_artifact(con, aid, description="d", desc_status="done")
        con.commit()
        self.alive.return_value = False
        self.next_tick()
        describe.launch(self.d)
        self.assertAlmostEqual(db.spend_today(self.con()), 0.02 + describe.RUN_BUDGET)

    def test_an_older_report_is_not_read_as_the_new_run(self):
        json.dump({"result": "old", "total_cost_usd": 0.01}, open(os.path.join(self.d, describe.OUT_FILE), "w"))
        describe.launch(self.d)
        self.assertFalse(os.path.exists(os.path.join(self.d, describe.OUT_FILE)))

    def test_status_shows_last_result(self):
        self.alive.return_value = False
        describe.launch(self.d)
        self.next_tick()
        describe.launch(self.d)  # reaps the first (no report), launches the next
        rc, out = run("--data", self.d, "status")
        self.assertIn("last describer run: ended without a cost report", out)
        rc, out = run("--data", self.d, "status", "--json")
        self.assertIn("released", json.loads(out)["describer_last_result"]["line"])


class Permission(DescBase):
    def test_ae_tool_named_and_skill_tools_kept(self):
        describe.launch(self.d)
        argv = self.det.call_args[0][0]
        tools = argv[argv.index("--allowedTools") + 1]
        self.assertIn("Bash(sh */bin/ae *)", tools)
        self.assertTrue(tools.startswith(describe._skill_tools().replace("ArtifactData, ", "")))  # 0.2.11
        self.assertEqual(argv[argv.index("--allowedTools") + 2], "--max-budget-usd")  # one value, then a flag
        self.assertEqual(tools.count(describe.AE_TOOL), 1)


class TestRun(DescBase):
    def test_test_launch_ignores_interval_one_row_and_says_so(self):
        describe.launch(self.d)  # a normal run sets describer_last now
        self.alive.return_value = False
        self.det.reset_mock()
        rc, out = run("--data", self.d, "launch-describer", "--test")
        self.assertEqual(self.det.call_count, 1)
        self.assertEqual(self.det.call_args[0][0][-1], describe.RUN_MARK + " 1")
        self.assertIn("describer test: launched (pid 4242) for 1 row", out)

    def test_test_launch_explains_why_not(self):
        self.use(fake_config(rule=False))
        rc, out = run("--data", self.d, "launch-describer", "--test")
        self.assertFalse(self.det.called)
        self.assertIn("permission rule is not in settings.json", out)
        self.which.return_value = None
        rc, out = run("--data", self.d, "launch-describer", "--test")
        self.assertIn("no `claude` command", out)

    def test_normal_launch_prints_nothing(self):
        rc, out = run("--data", self.d, "launch-describer")
        self.assertEqual(out, "")

    def test_pending_limit(self):
        rc, out = run("--data", self.d, "pending", "--owned-only", "--json", "--limit", "1")
        self.assertEqual(len(json.loads(out)), 1)
        rc, out = run("--data", self.d, "pending", "--owned-only", "--json")
        self.assertEqual(len(json.loads(out)), 2)


class Unknowns(unittest.TestCase):
    def test_backfill_from_publish_events(self):
        d = helpers.tmp()
        con = db.connect(d)
        db.upsert_artifact(con, A, title="mine")
        db.upsert_artifact(con, B, title="seen in history")
        db.add_event(con, A, 1000.0, "publish", "hook")
        db.add_event(con, A, 2000.0, "publish", "hook")
        db.add_event(con, B, 1500.0, "visit", "history")
        self.assertEqual(db.backfill(con), 2)
        a, b = db.get(con, A), db.get(con, B)
        self.assertEqual((a["owned"], a["modified"]), (1, 2000.0))
        self.assertEqual((b["owned"], b["modified"]), (None, None))
        self.assertEqual(db.backfill(con), 0)  # nothing left to fill
        db.upsert_artifact(con, A, owned=0)  # a known owner is never overwritten
        con.commit()
        db.backfill(con)
        self.assertEqual(db.get(con, A)["owned"], 0)

    def test_page_says_unknown_and_untitled(self):
        d = helpers.tmp()
        con = db.connect(d)
        db.upsert_artifact(con, A, title="  ")
        con.commit()
        con.close()
        rows = build.collect(d, {})[0]
        self.assertEqual((rows[0]["title"], rows[0]["modified"]), ("Untitled", None))
        tpl = open(os.path.join(ROOT, "page", "template.html"), encoding="utf-8").read()
        self.assertIn('if (!t) return el("span", "dim", "unknown");', tpl)

    def test_watcher_pass_backfills(self):
        src = open(os.path.join(ROOT, "scripts", "watch.py"), encoding="utf-8").read()
        self.assertIn("db.backfill(con)", src)


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "the dev scripts are bash")
class DevScripts(unittest.TestCase):
    def fake_claude(self, cfg, removes=True):
        """A `claude` that removes the plugin from installed_plugins.json (or, removes=False, does nothing)."""
        b = os.path.join(helpers.tmp(), "claude")
        body = "import json,os,shutil,sys\n"
        body += ("p=os.path.join(%r,'plugins','installed_plugins.json')\n"
                "if sys.argv[1:3]==['plugin','uninstall']:\n d=json.load(open(p)); d['plugins'].pop(%r,None);"
                " json.dump(d,open(p,'w'))\n" % (cfg, KEY)) if removes else ""
        body += ("if sys.argv[1:4]==['plugin','marketplace','remove']:\n"
                 " shutil.rmtree(os.path.join(%r,'plugins','marketplaces','jethro'),True)\n" % cfg)
        with open(b, "w") as f:
            f.write("#!%s\n%s" % (sys.executable, body))
        os.chmod(b, 0o755)
        return b

    def reset(self, cfg, claude):
        data = os.path.join(cfg, "plugins", "data", "artifact-explorer-jethro")
        os.makedirs(data)
        con = db.connect(data)
        db.upsert_artifact(con, A, title="x")
        con.commit()
        con.close()
        env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg, CLAUDE_BIN=claude)
        return subprocess.run(["bash", os.path.join(ROOT, "scripts", "dev", "fresh-install-reset.sh")],
                              capture_output=True, text=True, env=env, timeout=120)

    def test_reset_prints_what_it_did(self):
        cfg = fake_config("0.1.4", "0.1.4")
        p = self.reset(cfg, self.fake_claude(cfg))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("What reset did:", p.stdout)
        for line in ("ok:     no data folder", "ok:     plugin not in installed_plugins.json",
                     "ok:     allow rule not in settings.json",
                     "ok:     no watcher running", "fresh-install-check.sh"):
            self.assertIn(line, p.stdout)
        self.assertNotIn("FAILED", p.stdout)

    def test_reset_refuses_to_go_on_when_a_step_did_not_take(self):
        cfg = fake_config("0.1.2", "0.1.4")
        p = self.reset(cfg, self.fake_claude(cfg, removes=False))
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("FAILED: plugin not in installed_plugins.json (still lists 0.1.2)", p.stdout)
        self.assertIn("Refusing to go on", p.stdout)
        self.assertNotIn("Fresh install, as a new user", p.stdout)

    def check(self, cfg, *args):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg)
        return subprocess.run(["bash", os.path.join(ROOT, "scripts", "dev", "fresh-install-check.sh")] + list(args),
                              capture_output=True, text=True, env=env, timeout=120)

    def test_post_install_check(self):
        p = self.check(fake_config("0.1.2", "0.1.4"))
        self.assertEqual(p.returncode, 1)
        self.assertIn("MISMATCH", p.stdout)
        p = self.check(fake_config("0.1.5", "0.1.5"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("RESULT: OK", p.stdout)
        p = self.check(fake_config(None, "0.1.5"))
        self.assertEqual(p.returncode, 1)


class Docs(unittest.TestCase):
    def read(self, *p):
        return open(os.path.join(ROOT, *p), encoding="utf-8").read()

    def test_setup_starts_with_doctor_and_checks_rule_and_test_runs(self):
        s = self.read("skills", "setup", "SKILL.md")
        self.assertLess(s.index("`AE doctor`"), s.index("1. Everything asked once"))
        self.assertIn("Never call this setup fresh", s)
        self.assertIn("already in ~/.claude/settings.json; nothing added", s)
        self.assertIn("Added the rules (checked)", s)
        self.assertIn("without asking (step 1 covered it)", s)  # 0.2.11: every question up front
        self.assertIn("`AE launch-describer --test`", s)
        self.assertIn("--limit N", self.read("skills", "refresh", "SKILL.md"))

    def test_readme_update_and_cost(self):
        r = self.read("README.md")
        self.assertIn("claude plugin update artifact-explorer@jethro", r)
        self.assertIn("## Cost", r)
        self.assertIn("$1.00 a day", r)

    def test_versions_agree(self):
        v = json.loads(self.read(".claude-plugin", "plugin.json"))["version"]
        self.assertEqual(v, ae.VERSION)
        self.assertTrue(re.search(r"^## \[%s\]" % re.escape(v), self.read("CHANGELOG.md"), re.M))

    def test_gitignore_leaves_out_local_claude_folder(self):
        self.assertIn(".claude/", self.read(".gitignore").split())

    def test_no_home_paths_in_tracked_text(self):
        for p in ("README.md", "CHANGELOG.md", os.path.join("skills", "setup", "SKILL.md")):
            self.assertNotIn("/Users/", self.read(p), p)


if __name__ == "__main__":
    unittest.main()
