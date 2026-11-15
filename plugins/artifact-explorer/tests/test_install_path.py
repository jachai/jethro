"""0.2.1: the README doctor command resolves the CURRENT install from installed_plugins.json, not a version glob."""
import fnmatch
import json
import os
import re
import subprocess
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RULE = "sh */artifact-explorer/*/bin/ae *"


def _command():
    text = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    blocks = [b for b in re.findall(r"```sh\n(.*?)\n```", text, re.S) if "installed_plugins.json" in b]
    assert len(blocks) == 1
    return blocks[0]


class InstallPath(unittest.TestCase):
    def home(self, plugins):
        h = tempfile.mkdtemp()
        os.makedirs(os.path.join(h, ".claude", "plugins"))
        if plugins is not None:
            with open(os.path.join(h, ".claude", "plugins", "installed_plugins.json"), "w") as f:
                json.dump({"version": 2, "plugins": plugins}, f)
        return h

    def run_cmd(self, h, cmd):
        env = dict(os.environ, HOME=h)
        return subprocess.run(["sh", "-c", cmd], env=env, capture_output=True, text=True)

    def test_no_version_glob_anywhere_in_the_repo_docs_and_skills(self):
        bad = re.compile(r"artifact-explorer/\*/bin/ae")
        for base in ("README.md", "skills", "docs", "hooks", "monitors", "agents"):
            p = os.path.join(ROOT, base)
            files = [p] if os.path.isfile(p) else [os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs]
            for f in files:
                for n, line in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
                    # the permission rule itself is a pattern, not a command; commands never contain it outside a rule
                    if bad.search(line) and "Bash(" not in line and "allow rule" not in line:
                        self.fail("version glob in %s:%d" % (f, n))

    def test_resolves_current_not_old_glob_first(self):
        h = self.home({"artifact-explorer@artifact-explorer": [{"installPath": "/x/cache/artifact-explorer/artifact-explorer/0.2.1"}]})
        base = os.path.join(h, ".claude", "plugins", "cache", "artifact-explorer", "artifact-explorer")
        for v in ("0.1.2", "0.2.1"):
            os.makedirs(os.path.join(base, v, "bin"))
            with open(os.path.join(base, v, "bin", "ae"), "w") as f:
                f.write("echo ran %s\n" % v)
        r = self.run_cmd(h, _command())
        self.assertEqual(r.stdout.strip(), "ran 0.2.1", r.stderr)

    def test_missing_entry_or_file_gives_clear_error(self):
        for plugins in (None, {}, {"other@x": [{"installPath": "/a/b"}]}):
            r = self.run_cmd(self.home(plugins), _command())
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("artifact-explorer is not listed in", r.stderr)
            self.assertIn("claude plugin install", r.stderr)

    def test_command_still_matches_the_allow_rule(self):
        cmd = _command()
        flat = cmd.replace("\n", " ")
        # Claude Code's `*` matches any characters: the literal cache path gives /artifact-explorer/, then /bin/ae + space
        self.assertTrue(fnmatch.fnmatchcase(flat, RULE), flat)


if __name__ == "__main__":
    unittest.main()
