"""0.2.11: the background run's allowed tools are exactly what it uses, so it is never refused a tool."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import common  # noqa: E402
import describe  # noqa: E402
from test_v023_describe import PLUGIN, skill_ae, rule_matches, rules_of  # noqa: E402


def skill_text():
    return open(os.path.join(common.ROOT, "skills", "refresh", "SKILL.md"), encoding="utf-8").read()


class BackgroundTools(unittest.TestCase):
    def test_background_run_is_not_given_artifactdata(self):
        rules = rules_of(describe.allowed_tools())
        self.assertNotIn("ArtifactData", rules)
        self.assertIn("Artifact", rules)  # reads still allowed

    def test_session_refresh_keeps_artifactdata(self):
        self.assertIn("ArtifactData", rules_of(describe._skill_tools()))

    def test_background_branch_makes_no_artifactdata_call(self):
        txt = skill_text()
        m = re.search(r"\*\*Dashboard\*\*[^\n]*", txt)
        self.assertIn("In the background mode, do not take this branch", m.group(0))
        self.assertIn("no ArtifactData call", m.group(0))

    def test_every_ae_command_the_skill_names_matches_a_rule(self):
        rules = rules_of(describe.allowed_tools())
        subs = set(re.findall(r"`AE ((?:batch )?[a-z][a-z-]*)", skill_text()))
        self.assertIn("excerpt", subs)
        self.assertIn("batch excerpt", subs)
        for sub in subs:
            for cmd in (skill_ae() + " " + sub + ' "x" --out "y"',
                        (skill_ae() + " " + sub + ' "x" --out "y"').replace('"%s/bin/ae"' % PLUGIN, PLUGIN + "/bin/ae")):
                self.assertTrue(any(rule_matches(r, cmd) for r in rules), cmd)


if __name__ == "__main__":
    unittest.main()
