"""Tests for session_titles.py.

Every test gets its own temp config dir (CLAUDE_CONFIG_DIR) and points SESSION_TITLES_CLAUDE at a fake
`claude` that answers from a queue file, so nothing reads your real ~/.claude or calls a real model.
"""
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "session_titles.py"

spec = importlib.util.spec_from_file_location("session_titles", SCRIPT)
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)

SID = "11111111-2222-3333-4444-555555555555"

FAKE_CLAUDE = textwrap.dedent("""\
    #!{python}
    import json, os, sys
    from pathlib import Path
    base = Path(os.environ["FAKE_CLAUDE_DIR"])
    stdin = sys.stdin.read()
    args = sys.argv[1:]
    with open(base / "calls.jsonl", "a") as f:
        f.write(json.dumps({{"args": args, "stdin": stdin}}) + "\\n")
    if "--version" in args:
        print("9.9.9 (Claude Code)")
        sys.exit(0)
    queue = base / "replies.json"
    replies = json.loads(queue.read_text()) if queue.exists() else []
    reply = replies.pop(0) if replies else "generic label"
    queue.write_text(json.dumps(replies))
    if reply == "__FAIL__":
        print("boom", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({{"type": "result", "result": reply}}))
""")


def assistant_line(text, sidechain=False):
    return json.dumps({"type": "assistant", "isSidechain": sidechain,
                       "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.config = self.dir / "claude-config"
        self.config.mkdir()
        self.fake_dir = self.dir / "fake"
        self.fake_dir.mkdir()
        fake = self.fake_dir / "claude"
        fake.write_text(FAKE_CLAUDE.format(python=sys.executable))
        fake.chmod(0o755)
        self.env = mock.patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": str(self.config),
            "SESSION_TITLES_CLAUDE": str(fake),
            "FAKE_CLAUDE_DIR": str(self.fake_dir),
        })
        self.env.start()
        for k in [k for k in os.environ if k.startswith(("CLAUDE_PLUGIN_OPTION_", "SESSION_TITLES_MODE",
                                                          "SESSION_TITLES_MODEL", "SESSION_TITLES_FOCUS_STYLE", st.GUARD_ENV))]:
            if k not in ("SESSION_TITLES_CLAUDE",):
                os.environ.pop(k, None)
        self.transcript = self.dir / "t.jsonl"
        self.transcript.write_text("")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    # helpers
    def replies(self, *texts):
        (self.fake_dir / "replies.json").write_text(json.dumps(list(texts)))

    def calls(self):
        p = self.fake_dir / "calls.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def add_assistant(self, *texts):
        with self.transcript.open("a") as f:
            for t in texts:
                f.write(assistant_line(t) + "\n")

    def prompt(self, text="do the thing", title=None, sid=SID):
        hook_in = {"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": text,
                   "transcript_path": str(self.transcript), "cwd": str(self.dir)}
        if title is not None:
            hook_in["session_title"] = title
        return self.run_hook(hook_in)

    def run_hook(self, hook_in):
        buf = io.StringIO()
        with redirect_stdout(buf):
            st.run_hook(json.dumps(hook_in), lookup=lambda pid: (0, ""))
        out = buf.getvalue().strip()
        return json.loads(out)["hookSpecificOutput"]["sessionTitle"] if out else None

    def state(self, sid=SID):
        return st.read_state(sid)


class OriginTests(Base):
    def test_first_prompt_without_title_generates_origin_and_no_focus(self):
        self.replies("billing export")
        self.assertEqual(self.prompt("Build the billing CSV export"), "billing export")
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.state()["origin"], "billing export")

    def test_named_session_keeps_its_name_as_origin(self):
        self.add_assistant("I read the code and found the bug.")
        self.replies("fixing the retry bug")
        self.assertEqual(self.prompt(title="stripe webhooks"), "stripe webhooks · fixing the retry bug")
        self.assertEqual(self.state()["origin"], "stripe webhooks")

    def test_origin_stays_fixed_across_prompts(self):
        self.replies("billing export")
        first = self.prompt("Build the billing CSV export")
        self.add_assistant("Wrote the exporter; tests pass.")
        self.replies("opening the PR")
        second = self.prompt("open a PR", title=first)
        self.add_assistant("PR 214 is open, CI running.")
        self.replies("PR 214 waiting on CI")
        third = self.prompt("watch CI", title=second)
        self.assertEqual(third, "billing export · PR 214 waiting on CI")
        self.assertEqual(self.state()["origin"], "billing export")

    def test_manual_rename_becomes_new_origin(self):
        self.replies("billing export")
        first = self.prompt("Build the billing CSV export")
        self.add_assistant("Done with the exporter.")
        self.replies("writing docs")
        self.assertEqual(self.prompt("now docs", title="docs sprint"), "docs sprint · writing docs")
        self.assertNotEqual(first, "docs sprint")
        self.assertEqual(self.state()["origin"], "docs sprint")

    def test_stale_title_we_set_earlier_is_not_a_rename(self):
        self.replies("billing export")
        first = self.prompt("Build the billing CSV export")
        self.add_assistant("step one done")
        self.replies("step two")
        self.prompt("next", title=first)
        self.add_assistant("step two done")
        self.replies("step three")
        # Claude Code hands us an older title we set ourselves (queued prompts)
        self.assertEqual(self.prompt("next", title=first), "billing export · step three")
        self.assertEqual(self.state()["origin"], "billing export")

    def test_a_bare_flip_that_is_in_history_is_not_adopted_as_a_rename(self):
        # a tool set a prefixed origin; `--name` then makes Claude Code show the bare name, which the tool recorded
        st.write_state(SID, {"origin": "[x] billing", "focus": "", "last_set": "[x] billing",
                             "history": ["[x] billing", "billing"]})
        self.add_assistant("step one done")
        self.replies("step two")
        self.assertEqual(self.prompt("next", title="billing"), "[x] billing · step two")
        self.assertEqual(self.state()["origin"], "[x] billing")

    def test_a_new_manual_rename_after_guide_sync_keeps_the_stream_icon(self):
        st.write_state(SID, {"origin": "🟧🟧 (g) billing", "focus": "", "last_set": "🟧🟧 (g) billing",
                             "history": ["billing", "🟧🟧 (g) billing"], "pinned": ["billing"]})
        self.add_assistant("step one done")
        self.replies("step two")
        self.assertEqual(self.prompt("next", title="docs sprint"), "🟧🟧 (g) docs sprint · step two")
        self.assertEqual(self.state()["origin"], "🟧🟧 (g) docs sprint")
        self.prompt("again", title="🟧🟧 (g) ops")
        self.assertEqual(self.state()["origin"], "🟧🟧 (g) ops")  # no icon twice

    def test_a_rename_with_no_pinned_bare_title_gets_no_decoration(self):
        st.write_state(SID, {"origin": "🟧🟧 (g) billing", "focus": "", "last_set": "🟧🟧 (g) billing",
                             "history": ["🟧🟧 (g) billing"]})
        self.add_assistant("step one done")
        self.replies("step two")
        self.assertEqual(self.prompt("next", title="docs sprint"), "docs sprint · step two")

    def test_pinned_bare_titles_survive_more_than_eight_prompts(self):
        st.write_state(SID, {"origin": "🟧🟧 (g) billing", "focus": "", "last_set": "🟧🟧 (g) billing",
                             "history": ["billing", "🟧🟧 (g) billing"], "pinned": ["billing"]})
        title = "🟧🟧 (g) billing"
        for n in range(10):
            self.add_assistant("step %d done" % n)
            self.replies("step %d" % n)
            title = self.prompt("next", title=title)
        self.assertNotIn("billing", self.state()["history"])
        self.assertEqual(self.state()["pinned"], ["billing"])
        self.prompt("flip", title="billing")  # still read as ours, not as a rename
        self.assertEqual(self.state()["origin"], "🟧🟧 (g) billing")

    def test_an_origin_changed_while_the_focus_was_generated_is_kept(self):
        st.write_state(SID, {"origin": "billing", "focus": "", "last_set": "billing", "history": ["billing"]})
        self.add_assistant("step one done")
        self.replies("step two")
        real = st.generate_focus

        def slow(origin, recent, prompt, cfg):
            focus = real(origin, recent, prompt, cfg)
            state = st.read_state(SID)  # session-guide's sync lands between the two locked writes
            state["origin"] = "[x] billing"
            st.write_state(SID, state)
            return focus

        with mock.patch.object(st, "generate_focus", slow):
            self.assertEqual(self.prompt("next", title="billing"), "[x] billing · step two")
        self.assertEqual(self.state()["origin"], "[x] billing")
        self.assertEqual(self.state()["last_set"], "[x] billing · step two")

    def test_manual_rename_containing_separator_keeps_left_part(self):
        self.add_assistant("hello")
        self.replies("checking logs")
        self.assertEqual(self.prompt(title="ops · old focus"), "ops · checking logs")

    def test_no_title_no_prompt_does_nothing(self):
        self.assertIsNone(self.prompt(""))
        self.assertEqual(self.calls(), [])

    def test_origin_model_failure_leaves_title_alone(self):
        self.replies("__FAIL__")
        self.assertIsNone(self.prompt("Build the billing CSV export"))
        self.assertIn("model call failed", (st.home_dir() / "hook.log").read_text())


class FocusTests(Base):
    def setUp(self):
        super().setUp()
        self.add_assistant("I changed the parser and the tests are green.")

    def test_focus_repeating_origin_is_dropped_for_previous(self):
        self.replies("parser rewrite")
        self.prompt("go", title="parser rewrite")
        self.replies("adding parser tests")  # sets a good focus first
        good = self.prompt("go", title="parser rewrite")
        self.replies("Parser rewrite")  # pure repeat
        self.assertEqual(self.prompt("go", title=good), good)

    def test_focus_with_origin_prefix_is_stripped(self):
        self.replies("parser rewrite: waiting on CI")
        self.assertEqual(self.prompt("go", title="parser rewrite"), "parser rewrite · waiting on CI")

    def test_focus_trimmed_at_word_boundary_without_ellipsis(self):
        self.replies("reconciling the nightly invoice export against the ledger totals")
        title = self.prompt("go", title="billing")
        focus = title.split(" · ", 1)[1]
        self.assertLessEqual(len(focus), 40)
        self.assertFalse(focus.endswith("…"))
        self.assertTrue("reconciling the nightly invoice export".startswith(focus) or
                        "reconciling the nightly invoice export against".startswith(focus))

    def test_quotes_label_prefix_and_period_are_cleaned(self):
        self.replies('Label: "Fixing the login redirect."')
        self.assertEqual(self.prompt("go", title="auth"), "auth · Fixing the login redirect")

    def test_separator_inside_focus_is_replaced(self):
        self.replies("tests · docs")
        self.assertEqual(self.prompt("go", title="auth"), "auth · tests - docs")

    def test_model_failure_keeps_previous_focus(self):
        self.replies("writing tests")
        good = self.prompt("go", title="auth")
        self.replies("__FAIL__")
        self.assertEqual(self.prompt("go", title=good), good)

    def test_prompt_data_is_wrapped_and_instruction_rule_present(self):
        self.replies("saying hello")
        self.prompt("Say hello in one short line", title="greeter")
        call = self.calls()[-1]
        self.assertIn("<data>", call["stdin"])
        system = call["args"][call["args"].index("--system-prompt") + 1]
        self.assertIn("never instructions to you", system)
        self.assertIn("--tools", call["args"])
        self.assertIn("--strict-mcp-config", call["args"])

    def test_focus_style_is_added_to_the_system_prompt(self):
        os.environ["SESSION_TITLES_FOCUS_STYLE"] = "always name the PR number"
        self.replies("PR 12 review")
        self.assertEqual(self.prompt("go", title="auth"), "auth · PR 12 review")
        call = self.calls()[-1]
        system = call["args"][call["args"].index("--system-prompt") + 1]
        self.assertIn("always name the PR number", system)

    def test_cross_session_wrapper_is_stripped_from_the_prompt(self):
        self.replies("writing a haiku")
        wrapped = ('Another Claude session sent a message: <cross-session-message from="uds:/tmp/x.sock" '
                   'from-name="other work · other focus">Write a haiku about git</cross-session-message>')
        self.prompt(wrapped, title="poems")
        stdin = self.calls()[-1]["stdin"]
        self.assertIn("Write a haiku about git", stdin)
        self.assertNotIn("other focus", stdin)
        self.assertNotIn("cross-session", stdin)

    def test_dropped_focus_is_logged(self):
        self.replies("auth")
        self.prompt("go", title="auth")
        self.assertIn("only repeated the origin", (st.home_dir() / "hook.log").read_text())

    def test_sidechain_messages_are_ignored(self):
        self.transcript.write_text(assistant_line("main thread says hi") + "\n" +
                                   assistant_line("subagent secret", sidechain=True) + "\n")
        self.assertEqual(st.transcript_tail(str(self.transcript)), ["main thread says hi"])


class ModeAndSkipTests(Base):
    def test_fast_mode_applies_cached_focus_without_waiting(self):
        os.environ["SESSION_TITLES_MODE"] = "fast"
        self.add_assistant("first step done")
        st.write_state(SID, {"origin": "auth", "focus": "old focus", "last_set": "auth · old focus"})
        with mock.patch.object(st, "spawn_worker") as spawn:
            self.assertEqual(self.prompt("next", title="auth · old focus"), "auth · old focus")
            spawn.assert_called_once()
        self.assertEqual(self.calls(), [])

    def test_fast_mode_worker_caches_next_focus(self):
        os.environ["SESSION_TITLES_MODE"] = "fast"
        self.add_assistant("first step done")
        st.write_state(SID, {"origin": "auth", "focus": "", "last_set": "auth"})
        pending = st.home_dir() / "pending"
        pending.mkdir(parents=True, exist_ok=True)
        (pending / f"{SID}.json").write_text(json.dumps({"transcript": str(self.transcript), "prompt": "next"}))
        self.replies("writing the session store")
        st.run_worker(SID)
        self.assertEqual(self.state()["focus"], "writing the session store")
        self.assertFalse((pending / f"{SID}.json").exists())
        with mock.patch.object(st, "spawn_worker"):
            self.assertEqual(self.prompt("go", title="auth"), "auth · writing the session store")

    def test_fast_mode_spawns_a_real_detached_worker(self):
        os.environ["SESSION_TITLES_MODE"] = "fast"
        self.add_assistant("first step done")
        st.write_state(SID, {"origin": "auth", "focus": "", "last_set": "auth"})
        self.replies("background focus")
        self.prompt("go", title="auth")
        for _ in range(50):
            if self.state().get("focus") == "background focus":
                break
            time.sleep(0.1)
        self.assertEqual(self.state().get("focus"), "background focus")
        log = st.home_dir() / "hook.log"
        for _ in range(50):  # let the worker finish logging before the temp dir goes away
            if "focus cached" in log.read_text():
                break
            time.sleep(0.1)

    def test_print_mode_parent_is_detected_through_shells(self):
        table = {100: (90, "/bin/zsh -c python3 hook"), 90: (80, "/usr/local/bin/claude -p --model x hi"),
                 80: (1, "launchd")}
        self.assertTrue(st.in_print_mode(100, lookup=lambda pid: table.get(pid, (0, ""))))
        table[90] = (80, "/Users/x/.local/share/claude/versions/2.1.310 --resume abc")
        self.assertFalse(st.in_print_mode(100, lookup=lambda pid: table.get(pid, (0, ""))))
        table[100] = (90, "/bin/zsh -c 'grep -p something'")
        table[90] = (80, "/usr/local/bin/claude")
        self.assertFalse(st.in_print_mode(100, lookup=lambda pid: table.get(pid, (0, ""))))

    def test_print_mode_sessions_are_skipped(self):
        hook_in = {"hook_event_name": "UserPromptSubmit", "session_id": SID, "prompt": "hi",
                   "transcript_path": str(self.transcript)}
        buf = io.StringIO()
        with redirect_stdout(buf):
            st.run_hook(json.dumps(hook_in), lookup=lambda pid: (1, "claude -p hi") if pid != 1 else (0, ""))
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(self.calls(), [])

    def test_nested_call_guard(self):
        os.environ[st.GUARD_ENV] = "1"
        self.replies("x")
        self.assertIsNone(self.prompt("Build the billing CSV export"))
        self.assertEqual(self.calls(), [])

    def test_off_session_is_left_alone(self):
        st.write_state(SID, {"origin": "auth", "off": True})
        self.add_assistant("x")
        self.assertIsNone(self.prompt("go", title="auth"))
        self.assertEqual(self.calls(), [])

    def test_plugin_options_and_env_override_config_file(self):
        st.home_dir().mkdir(parents=True, exist_ok=True)
        (st.home_dir() / "config.json").write_text(json.dumps({"model": "sonnet", "max_focus_chars": 30}))
        self.assertEqual(st.load_config()["model"], "sonnet")
        os.environ["CLAUDE_PLUGIN_OPTION_MODEL"] = "opus"
        os.environ["CLAUDE_PLUGIN_OPTION_SKIP_PRINT_MODE"] = "false"
        cfg = st.load_config()
        self.assertEqual((cfg["model"], cfg["max_focus_chars"], cfg["skip_print_mode"]), ("opus", 30, False))
        os.environ["CLAUDE_PLUGIN_OPTION_SEPARATOR"] = "|"  # Claude Code trims option strings
        self.assertEqual(st.load_config()["separator"], " | ")
        os.environ["CLAUDE_PLUGIN_OPTION_MODE"] = "bogus"
        self.assertEqual(st.load_config()["mode"], "fresh")


class ResumeTests(Base):
    def resume(self, title=None):
        hook_in = {"hook_event_name": "SessionStart", "source": "resume", "session_id": SID}
        if title is not None:
            hook_in["session_title"] = title
        return self.run_hook(hook_in)

    def test_resume_restores_last_title(self):
        st.write_state(SID, {"origin": "auth", "focus": "tests", "last_set": "auth · tests",
                             "history": ["auth", "auth · tests"]})
        self.assertEqual(self.resume(title="auth"), "auth · tests")

    def test_resume_respects_a_newer_manual_rename(self):
        st.write_state(SID, {"origin": "auth", "last_set": "auth · tests", "history": ["auth · tests"]})
        self.assertIsNone(self.resume(title="something I typed"))

    def test_resume_into_a_new_session_id_keeps_the_inherited_focus(self):
        # `claude --bg --resume` can fork to a new id whose transcript isn't written yet at the first prompt
        self.assertEqual(self.prompt("Reply with ok.", title="auth · tests", sid="99999999-0000-4000-8000-000000000000"),
                         "auth · tests")
        self.assertEqual(self.calls(), [])
        self.assertEqual(st.read_state("99999999-0000-4000-8000-000000000000")["origin"], "auth")

    def test_startup_does_not_set_a_title(self):
        st.write_state(SID, {"origin": "auth", "last_set": "auth · tests"})
        self.assertIsNone(self.run_hook({"hook_event_name": "SessionStart", "source": "startup", "session_id": SID}))

    def test_old_state_is_pruned(self):
        st.write_state("old-session", {"origin": "x"})
        old = time.time() - 40 * 86400
        os.utime(st.state_path("old-session"), (old, old))
        self.resume()
        self.assertFalse(st.state_path("old-session").exists())


class CliTests(Base):
    def cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = st.main(list(argv))
        return code, buf.getvalue()

    def test_show_set_origin_off_on(self):
        st.write_state(SID, {"origin": "auth", "focus": "tests", "last_set": "auth · tests",
                             "history": ["auth · tests"]})
        _, out = self.cli("show", SID[:6])
        self.assertIn("auth · tests", out)
        self.cli("set-origin", SID[:6], "login", "rework")
        self.assertEqual(self.state()["origin"], "login rework")
        self.add_assistant("x")
        self.replies("fixing redirects")
        self.assertEqual(self.prompt("go", title="auth · tests"), "login rework · fixing redirects")
        self.cli("off", SID[:6])
        self.assertIsNone(self.prompt("go", title="login rework · fixing redirects"))
        self.cli("on", SID[:6])
        self.replies("back on")
        self.assertEqual(self.prompt("go", title="login rework · fixing redirects"), "login rework · back on")

    def test_ambiguous_prefix_is_refused(self):
        st.write_state("abc1", {"origin": "a"})
        st.write_state("abc2", {"origin": "b"})
        with self.assertRaises(SystemExit):
            self.cli("show", "abc")

    def test_status_log_and_doctor(self):
        self.replies("billing export", "PR waiting on CI")
        self.prompt("Build the billing CSV export")
        code, out = self.cli("status")
        self.assertEqual(code, 0)
        self.assertIn("1 titles set", out)
        _, out = self.cli("log", "-n", "5")
        self.assertIn("title ->", out)
        code, out = self.cli("doctor")
        self.assertIn("claude found", out)
        self.assertIn("FAIL", out)  # no hook registered in the temp settings.json
        self.assertEqual(code, 1)

    def test_version(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--version"], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), f"session-titles {st.__version__}")


class InstallTests(Base):
    def run_install(self, *args):
        env = dict(os.environ, HOME=str(self.dir), CLAUDE_CONFIG_DIR=str(self.config))
        return subprocess.run(["sh", str(ROOT / "install.sh"), *args], capture_output=True, text=True, env=env)

    def settings(self):
        return json.loads((self.config / "settings.json").read_text())

    def test_install_is_idempotent_keeps_other_hooks_and_uninstalls_cleanly(self):
        other = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "other.sh"}]}]},
                 "model": "x"}
        (self.config / "settings.json").write_text(json.dumps(other))
        (self.dir / ".local" / "bin").mkdir(parents=True)
        for _ in range(2):
            r = self.run_install()
            self.assertEqual(r.returncode, 0, r.stderr)
        s = self.settings()
        cmds = [h["command"] for g in s["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
        self.assertEqual(sum("session_titles.py" in c for c in cmds), 1)
        self.assertIn("other.sh", cmds)
        self.assertEqual(len(s["hooks"]["SessionStart"]), 1)
        self.assertTrue((self.dir / ".local" / "bin" / "session-titles").is_symlink())
        self.assertTrue((self.config / "settings.json.bak-session-titles").exists())
        cli = subprocess.run([str(self.dir / ".local" / "bin" / "session-titles"), "--version"],
                             capture_output=True, text=True)
        self.assertIn(st.__version__, cli.stdout)
        r = self.run_install("--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.settings(), other)
        self.assertFalse((self.dir / ".local" / "bin" / "session-titles").exists())

    def test_install_without_settings_file(self):
        r = self.run_install()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("UserPromptSubmit", self.settings()["hooks"])


class TrivialFirstPromptTests(Base):
    def add_user(self, text):
        with self.transcript.open("a") as f:
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")

    def test_trivial_first_prompt_sets_no_title_and_makes_no_call(self):
        for text in ("ok", "guard ok", "Continue.", "/compact", "yes please", "thanks!"):
            with self.subTest(text=text):
                self.assertIsNone(self.prompt(text))
        self.assertEqual(self.calls(), [])
        self.assertIn("says nothing about the work", (st.home_dir() / "hook.log").read_text())

    def test_real_prompt_after_trivial_ones_names_the_session(self):
        self.assertIsNone(self.prompt("ok"))
        self.replies("billing export")
        self.assertEqual(self.prompt("Build the billing CSV export"), "billing export")
        self.assertIn("Build the billing CSV export", self.calls()[-1]["stdin"])

    def test_trivial_prompt_falls_back_to_first_real_request_in_transcript(self):
        self.add_user("ok")
        self.add_user("Migrate the invoices table to the new schema")
        self.add_assistant("Started on the migration.")
        self.replies("invoices schema migration", "writing the backfill")
        title = self.prompt("continue")
        self.assertEqual(title, "invoices schema migration · writing the backfill")
        self.assertIn("Migrate the invoices table", self.calls()[0]["stdin"])

    def test_named_session_with_trivial_prompt_still_gets_a_focus(self):
        self.add_assistant("PR 214 is open and CI is running.")
        self.replies("PR 214 waiting on CI")
        self.assertEqual(self.prompt("ok", title="billing export"), "billing export · PR 214 waiting on CI")

    def test_short_but_real_prompts_are_not_trivial(self):
        for text in ("review PR 214", "why is CI red?", "Build the billing CSV export"):
            with self.subTest(text=text):
                self.assertFalse(st.is_trivial(text))


if __name__ == "__main__":
    unittest.main()
