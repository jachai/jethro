"""0.2.6: the background run refused chained/variable Bash commands and Artifact reads with a SCRATCH out_dir.
Skill rules, `ae batch excerpt`, multi-pair `ae set-kind`, zombie = finished, one watcher, one-hour back-off after a refusal,
describer.log."""
import io
import json
import os
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402
import watch  # noqa: E402
from test_describer_v012 import Base, A, B, C, U  # noqa: E402

SKILL = os.path.join(common.ROOT, "skills", "refresh", "SKILL.md")


class SkillRules(unittest.TestCase):
    def setUp(self):
        self.txt = open(SKILL, encoding="utf-8").read()

    def test_no_variables_no_chaining(self):
        self.assertIn("Never set or use shell variables", self.txt)
        self.assertIn("Never chain commands: no `;`, `&&`, `||`, newlines, pipes or redirects. Never `cd`.", self.txt)
        self.assertIn("Run each `AE` command as its own Bash call, and start the command with `sh`.", self.txt)
        self.assertIn("AE batch excerpt", self.txt)

    def test_out_dir_rule(self):
        self.assertIn("Artifact and ArtifactData reads never get SCRATCH as `out_dir`", self.txt)
        self.assertIn("SCRATCH is only for files you write with the Write tool", self.txt)
        self.assertIn("Reads never pass a custom `out_dir`", self.txt)

    def test_allowed_tools_keep_both_ae_forms(self):
        tools = describe.allowed_tools()
        for t in describe.AE_TOOLS:
            self.assertIn(t, tools)


def page(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("<html><body><p>%s</p></body></html>" % text)
    return p


def make_rows(d, ids):
    f = os.path.join(d, "list.json")
    with open(f, "w") as fh:
        json.dump([{"url": U + x, "title": x, "scope": "mine"} for x in ids], fh)
    describe.ingest_list(d, f)


class BatchExcerpt(unittest.TestCase):
    def test_pairs_and_failing_pair(self):
        d = helpers.tmp()
        make_rows(d, [A, B, C])
        src = helpers.tmp()
        long = "A long enough paragraph of visible text for the excerpt to keep. " * 3
        pa, pb = page(src, "a.html", long), page(src, "b.html", long + "more")
        out = helpers.tmp()
        buf = io.StringIO()
        with redirect_stdout(buf):
            describe.batch_excerpt(d, out, ["%s=%s" % (A, pa), "%s=%s" % (B, os.path.join(src, "missing.html")), "%s=%s" % (C, pb)])
        lines = buf.getvalue().splitlines()
        self.assertEqual(lines[-1], "excerpted 2, failed 1")
        self.assertTrue(any(l.startswith("error: " + B) for l in lines))
        self.assertTrue(os.path.getsize(os.path.join(out, A + ".txt")) > 0)
        self.assertTrue(os.path.getsize(os.path.join(out, C + ".txt")) > 0)
        self.assertFalse(os.path.exists(os.path.join(out, B + ".txt")))

    def test_same_as_single_excerpt(self):
        d = helpers.tmp()
        make_rows(d, [A])
        src = helpers.tmp()
        p = page(src, "a.html", "Plenty of text here to describe, more than fifty characters for sure, yes.")
        o1, o2 = helpers.tmp(), helpers.tmp()
        describe.excerpt_for(d, p, os.path.join(o1, A + ".txt"), A)
        with redirect_stdout(io.StringIO()):
            describe.batch_excerpt(d, o2, ["%s=%s" % (A, p)])
        self.assertEqual(open(os.path.join(o1, A + ".txt")).read(), open(os.path.join(o2, A + ".txt")).read())

    def test_cli(self):
        d = helpers.tmp()
        make_rows(d, [A])
        p = page(helpers.tmp(), "a.html", "Plenty of text here to describe, more than fifty characters for sure, yes.")
        out = helpers.tmp()
        r = subprocess.run([sys.executable, os.path.join(common.ROOT, "scripts", "ae.py"), "--data", d, "batch", "excerpt", out,
                            "%s=%s" % (A, p)], capture_output=True, text=True, env=dict(os.environ, AE_UPDATE_CHECK="0"))
        self.assertEqual(r.stdout.strip(), "excerpted 1, failed 0", r.stderr)


class SetKind(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        make_rows(self.d, [A, B])

    def kind(self, i):
        return db.get(db.connect(self.d), i)["kind"]

    def test_multi_pair(self):
        describe.set_kinds(self.d, [A + "=Docs", B + "=Slides"])
        self.assertEqual((self.kind(A), self.kind(B)), ("Docs", "Slides"))

    def test_old_form(self):
        describe.set_kinds(self.d, [A, "Docs"])
        self.assertEqual(self.kind(A), "Docs")

    def test_cli_both_forms(self):
        ae = [sys.executable, os.path.join(common.ROOT, "scripts", "ae.py"), "--data", self.d, "set-kind"]
        env = dict(os.environ, AE_UPDATE_CHECK="0")
        self.assertEqual(subprocess.run(ae + [A, "Docs"], env=env).returncode, 0)
        self.assertEqual(subprocess.run(ae + [B + "=Slides", A + "=Data"], env=env).returncode, 0)
        self.assertEqual((self.kind(A), self.kind(B)), ("Dashboard", "Slides"))


class Zombie(unittest.TestCase):
    def ps(self, stat):
        return mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=stat + "\n"))

    @unittest.skipIf(os.name == "nt", "ps")
    def test_zombie_is_dead(self):
        with self.ps("Z+"):
            self.assertFalse(common._pid_alive(os.getpid()))

    @unittest.skipIf(os.name == "nt", "ps")
    def test_running_is_alive_and_ps_failure_falls_back(self):
        with self.ps("S"):
            self.assertTrue(common._pid_alive(os.getpid()))
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertTrue(common._pid_alive(os.getpid()))


class Singleton(unittest.TestCase):
    def write(self, d, pid):
        with open(os.path.join(d, "watcher.json"), "w") as f:
            json.dump({"pid": pid, "t": time.time()}, f)

    def test_stands_by_silently_when_other_watcher_alive(self):
        d = helpers.tmp()
        self.write(d, 99999)
        buf = io.StringIO()
        with mock.patch.object(common, "_pid_alive", return_value=True), \
                mock.patch.object(common, "pid_cmdline", return_value="/usr/bin/python3 /x/scripts/ae.py --data /d watch"), \
                mock.patch.object(watch, "tick") as tick, redirect_stdout(buf), \
                mock.patch.object(os, "getppid", return_value=os.getppid()):
            self.assertEqual(watch.loop(d, tick_seconds=0, max_ticks=3), 0)
        tick.assert_not_called()
        self.assertEqual(buf.getvalue(), "")  # any stdout line would be a Monitor event in the session
        self.assertEqual(json.load(open(os.path.join(d, "watcher.json")))["pid"], 99999)

    def test_takes_over_when_other_watcher_goes(self):
        d = helpers.tmp()
        self.write(d, 99999)
        alive = iter([True, False])
        with mock.patch.object(common, "_pid_alive", side_effect=lambda pid: next(alive, False)), \
                mock.patch.object(common, "pid_cmdline", return_value="/usr/bin/python3 /x/scripts/ae.py --data /d watch"), \
                mock.patch.object(watch, "tick") as tick, mock.patch.object(watch, "superseded", return_value=None), \
                mock.patch.object(os, "getppid", return_value=os.getppid()):
            watch.loop(d, tick_seconds=0, max_ticks=2)
        tick.assert_called_once()
        self.assertEqual(json.load(open(os.path.join(d, "watcher.json")))["pid"], os.getpid())

    def test_starts_when_pid_reused_or_dead(self):
        for alive, cmd in ((True, "/usr/bin/vim notes.txt"), (False, None)):
            d = helpers.tmp()
            self.write(d, 99999)
            with mock.patch.object(common, "_pid_alive", return_value=alive), \
                    mock.patch.object(common, "pid_cmdline", return_value=cmd), \
                    mock.patch.object(watch, "tick") as tick, mock.patch.object(watch, "superseded", return_value=None), \
                    mock.patch.object(os, "getppid", return_value=os.getppid()):
                watch.loop(d, tick_seconds=0, max_ticks=1)
            tick.assert_called_once()
            self.assertEqual(json.load(open(os.path.join(d, "watcher.json")))["pid"], os.getpid())


def write_out(d, result, denials=(), cost=0.01):
    with open(os.path.join(d, describe.OUT_FILE), "w") as f:
        json.dump({"total_cost_usd": cost, "result": result, "permission_denials": list(denials)}, f)


class BackOff(Base):
    def finished_run(self, result, denials=()):
        """A run was launched, then ended with this output."""
        describe.launch(self.d)
        self.alive.return_value = False
        write_out(self.d, result, denials)
        self.next_tick()

    def test_refused_run_blocks_an_hour(self):
        self.finished_run("stopped: refused Bash")
        self.det.reset_mock()
        describe.launch(self.d)
        self.assertEqual(self.det.call_count, 0)
        self.assertIn("describer back-off: last run refused Bash, next try after ", self.log())
        self.assertEqual(self.log().count("describer back-off"), 1)
        self.next_tick()
        describe.launch(self.d)
        self.assertEqual(self.det.call_count, 0)

    def test_after_an_hour_launches(self):
        self.finished_run("stopped: refused Bash")
        old = time.time() - 3700
        os.utime(os.path.join(self.d, describe.OUT_FILE), (old, old))
        con = self.con()
        db.state_set(con, "describer_backoff", {"until": old + 3600, "tool": "Bash"})
        con.commit()
        self.det.reset_mock()
        describe.launch(self.d)
        self.assertEqual(self.det.call_count, 1)

    def test_test_flag_ignores_backoff(self):
        self.finished_run("stopped: refused Bash")
        self.det.reset_mock()
        with redirect_stdout(io.StringIO()):
            describe.launch(self.d, test=True)
        self.assertEqual(self.det.call_count, 1)

    def test_normal_run_no_backoff(self):
        describe.launch(self.d)
        con = self.con()
        for aid in (A, B, C):
            db.upsert_artifact(con, aid, description="d", desc_status="done")
        con.commit()
        self.alive.return_value = False
        write_out(self.d, "described 3 of 3, skipped 0, no source 0, needs interactive 0, categorized 0")
        self.next_tick()
        db.upsert_artifact(con, "zzz", url=U + "zzz", title="z", owned=1)  # something still waits
        con.commit()
        self.det.reset_mock()
        describe.launch(self.d)
        self.assertEqual(self.det.call_count, 1)

    def test_describer_log_has_denial_input(self):
        den = [{"tool_name": "Bash", "tool_input": {"command": 'AE="sh x"; sh y ' + "z" * 3000}}]
        self.finished_run("stopped: refused Bash", den)
        describe.launch(self.d)
        lines = open(os.path.join(self.d, "describer.log"), encoding="utf-8").read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("pid 4242", lines[0])
        self.assertIn("$0.01", lines[0])
        self.assertIn("stopped: refused Bash", lines[0])
        self.assertIn("denied Bash {", lines[0])
        self.assertIn('AE=\\"sh x\\"; sh y', lines[0])
        self.assertLess(len(lines[0]), 2000 + 400)


if __name__ == "__main__":
    unittest.main()
