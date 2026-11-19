"""0.2.3: the quoted `ae` command matches the allow rules, the run budget, and the recat requeue."""
import io
import json
import os
import re
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402

PLUGIN = "/Users/x/.claude/plugins/cache/artifact-explorer/artifact-explorer/0.2.3"
DATA = "/Users/x/.claude/plugins/data/artifact-explorer-artifact-explorer"


def skill_ae():
    """The AE definition the refresh skill tells the model to use, with the variables filled in."""
    txt = open(os.path.join(common.ROOT, "skills", "refresh", "SKILL.md"), encoding="utf-8").read()
    m = re.search(r"`AE` means `([^`]+)`", txt)
    return m.group(1).replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN).replace("${CLAUDE_PLUGIN_DATA}", DATA)


def rule_matches(rule, command):
    """Claude Code's Bash(...) match as the tests need it: `*` is any characters, the rest literal, whole string."""
    m = re.fullmatch(r"Bash\((.*)\)", rule)
    if not m:
        return False
    pat = "".join(".*" if c == "*" else re.escape(c) for c in m.group(1))
    return re.fullmatch(pat, command, re.S) is not None


def rules_of(tools):
    return [t.strip() for t in re.split(r",(?![^()]*\))", tools) if t.strip()]


class Permission(unittest.TestCase):
    def test_skill_command_is_quoted(self):
        self.assertIn('"%s/bin/ae"' % PLUGIN, skill_ae())

    def test_quoted_and_plain_commands_match_the_background_tools(self):
        quoted = skill_ae() + " pending --owned-only --json"
        plain = quoted.replace('"%s/bin/ae"' % PLUGIN, PLUGIN + "/bin/ae")
        rules = rules_of(describe.allowed_tools())
        self.assertTrue(any(rule_matches(r, quoted) for r in rules), quoted)
        self.assertTrue(any(rule_matches(r, plain) for r in rules), plain)
        # and each form needs its own rule: neither of the old single rules covers the quoted one
        self.assertFalse(rule_matches("Bash(sh */bin/ae *)", quoted))
        self.assertTrue(rule_matches('Bash(sh "*/bin/ae" *)', quoted))

    def test_every_skill_allows_both_forms(self):
        quoted = skill_ae() + " status"
        plain = quoted.replace('"%s/bin/ae"' % PLUGIN, PLUGIN + "/bin/ae")
        sk = os.path.join(common.ROOT, "skills")
        for name in os.listdir(sk):
            txt = open(os.path.join(sk, name, "SKILL.md"), encoding="utf-8").read()
            rules = rules_of(re.search(r"^allowed-tools:\s*(.+)$", txt, re.M).group(1))
            self.assertTrue(any(rule_matches(r, quoted) for r in rules), name)
            self.assertTrue(any(rule_matches(r, plain) for r in rules), name)

    def test_allowed_tools_split_keeps_quoted_rules(self):
        tools = describe.allowed_tools().split(", ")
        self.assertIn('Bash(sh "*/bin/ae" *)', tools)
        self.assertIn("Bash(sh */bin/ae *)", tools)

    def test_setup_rules_match_the_quoted_and_plain_command(self):
        quoted = skill_ae() + " doctor"
        plain = quoted.replace('"%s/bin/ae"' % PLUGIN, PLUGIN + "/bin/ae")
        self.assertTrue(any(rule_matches(r, quoted) for r in common.ALLOW_RULES))
        self.assertTrue(rule_matches(common.ALLOW_RULE, plain))  # the old rule still covers the old form
        self.assertFalse(rule_matches(common.ALLOW_RULE, quoted))
        self.assertTrue(rule_matches(common.ALLOW_RULE_QUOTED, quoted))

    def test_allow_rule_present_accepts_old_or_new(self):
        for allow, present, missing in (([], False, 2), ([common.ALLOW_RULE], True, 1),
                                        ([common.ALLOW_RULE_QUOTED], True, 1), (list(common.ALLOW_RULES), True, 0)):
            cfg = helpers.tmp()
            with open(os.path.join(cfg, "settings.json"), "w") as f:
                json.dump({"permissions": {"allow": allow}}, f)
            with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfg}):
                self.assertEqual(common.allow_rule_present(), present)
                self.assertEqual(len(common.allow_rules_missing()), missing)


class Base(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        self.con = db.connect(self.d)
        with open(os.path.join(self.d, "config.toml"), "w", encoding="utf-8") as f:
            f.write('[[categories]]\nname = "Reports"\n[[topics]]\nname = "Budget"\n')
        cfg = helpers.tmp()
        with open(os.path.join(cfg, "settings.json"), "w") as f:
            json.dump({"permissions": {"allow": [common.ALLOW_RULE_QUOTED]}}, f)
        p = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfg})
        p.start()
        self.addCleanup(p.stop)

    def add(self, aid, **kw):
        kw.setdefault("owned", 1)
        kw.setdefault("modified", 1700000000.0)  # long outside the window
        db.upsert_artifact(self.con, aid, title=aid, description="d", desc_source="describer", desc_status="ok", **kw)
        self.con.commit()

    def recat_ids(self, owned_only=False):
        buf = io.StringIO()
        with redirect_stdout(buf):
            describe.batch_recat(self.d, 100, owned_only)
        if "items: 0" in buf.getvalue():
            return []
        p = os.path.join(self.d, "inbox", "batch")
        if not os.path.isdir(p) or not os.listdir(p):
            return []
        m = os.path.join(p, sorted(os.listdir(p), key=int)[-1], "manifest.txt")
        return re.findall(r"^## ITEM (.*)$", open(m).read(), re.M)


class Budget(Base):
    def test_values(self):
        self.assertEqual(describe.RUN_BUDGET, 0.02)
        self.assertEqual(describe.RUN_CEILING, 0.15)

    def test_launch_books_estimate_and_passes_ceiling(self):
        db.upsert_artifact(self.con, "p", title="P", owned=1, desc_status="pending", modified=__import__("time").time())
        self.con.commit()
        with mock.patch.object(describe.shutil, "which", return_value="/bin/claude"), \
                mock.patch.object(describe.common, "detach", return_value=77) as det:
            describe.launch(self.d)
        argv = det.call_args[0][0]
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.15")
        self.assertAlmostEqual(db.spend_today(db.connect(self.d)), 0.02)


class Requeue(Base):
    def test_schema_version(self):
        self.assertEqual(db.SCHEMA_VERSION, 2)
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_old_catalog_migrates_and_rows_become_eligible(self):
        self.add("a", category="Reports", cat_source="describer")  # topics NULL
        self.con.execute("PRAGMA user_version=1")
        self.con.commit()
        con = db.connect(self.d)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(describe.recat_count(con), 1)

    def test_eligibility(self):
        self.add("nocat")  # category NULL
        self.add("notop", category="Reports", cat_source="describer", topics="[]")
        self.add("full", category="Reports", cat_source="describer", topics='["Budget"]')
        self.add("theirs", owned=0)
        db.upsert_artifact(self.con, "undescribed", title="U", owned=1, desc_status="pending")
        self.con.commit()
        self.assertEqual(sorted(self.recat_ids()), ["nocat", "notop", "theirs"])
        with redirect_stdout(io.StringIO()):
            describe.batch_recat(self.d, 100, True)
        self.assertEqual(describe.recat_count(self.con, True), 2)
        self.assertEqual(describe.recat_count(self.con, False), 3)

    def test_saved_reply_fills_category_and_topics_and_is_not_asked_again(self):
        self.add("a")
        self.add("b")
        ids = self.recat_ids()
        folder = os.path.join(self.d, "inbox", "batch", "1")
        reply = os.path.join(folder, "r.jsonl")
        with open(reply, "w") as f:
            f.write(json.dumps({"id": "a", "category": "Reports", "topics": ["Budget"]}) + "\n")
            f.write(json.dumps({"id": "b", "category": "Reports", "topics": []}) + "\n")
        with redirect_stdout(io.StringIO()):
            describe.batch_save(self.d, reply)
        con = db.connect(self.d)
        a, b = db.get(con, "a"), db.get(con, "b")
        self.assertEqual((a["category"], json.loads(a["topics"])), ("Reports", ["Budget"]))
        self.assertEqual(b["category"], "Reports")
        self.assertEqual(sorted(ids), ["a", "b"])
        self.assertEqual(self.recat_ids(), [])  # b has no topics, but it was asked once

    def test_launch_for_recat_rows_only_ignores_window(self):
        self.add("a")  # old, described, no category: nothing pending, one to categorize
        with mock.patch.object(describe.shutil, "which", return_value="/bin/claude"), \
                mock.patch.object(describe.common, "detach", return_value=77) as det:
            describe.launch(self.d)
        det.assert_called_once()

    def test_no_launch_when_nothing_to_do(self):
        self.add("a", category="Reports", cat_source="describer", topics='["Budget"]')
        with mock.patch.object(describe.shutil, "which", return_value="/bin/claude"), \
                mock.patch.object(describe.common, "detach", return_value=77) as det:
            describe.launch(self.d)
        det.assert_not_called()


class Skill(unittest.TestCase):
    def test_batches_of_8_and_describe_only_recat(self):
        txt = open(os.path.join(common.ROOT, "skills", "refresh", "SKILL.md"), encoding="utf-8").read()
        self.assertNotIn("up to 8", txt)
        self.assertIn("batches of at most 8", txt)
        self.assertIn("Describe at most 60", txt)
        self.assertIn("AE batch recat --owned-only --limit 8", txt)
        self.assertNotIn("do not run `AE batch recat` here", txt)
        self.assertIn("8 items", open(os.path.join(common.ROOT, "agents", "describer.md"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
