#!/usr/bin/env python3
"""The worker contract's text: end-of-work reports always go by SendMessage to the guide's socket, and the sentence
that once told workers to stop sending across a guide change is gone from every file in the plugin."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFS = os.path.join(ROOT, "skills", "session-guide", "references")
SKILL = os.path.join(ROOT, "skills", "session-guide", "SKILL.md")
# Built from parts so this file doesn't hold the sentence it looks for.
OLD = " ".join(["keep", "reporting", "in", "your", "final", "message"])
GUIDE_CHANGE = ("Guide changing. Keep sending to this socket; the old guide forwards until the new one introduces "
                "itself.")
KINDS = ("HANDED OFF", "BLOCKED", "DONE", "MERGE READY")


def flat(text):
    return " ".join(text.split())


def read(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8", "replace")


def contract_rule(n):
    """Rule `n` of the contract block in worker-contract.md, its lines joined."""
    block = read(os.path.join(REFS, "worker-contract.md")).split("```")[1]
    found = re.search(r"(?ms)^%d\. (.*?)(?=^\d+\. |\Z)" % n, block)
    return flat(found.group(1)) if found else ""


class OldSentenceGone(unittest.TestCase):
    def test_nowhere_in_the_plugin(self):
        hits = []
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for name in files:
                path = os.path.join(folder, name)
                if OLD in flat(read(path)).lower():
                    hits.append(os.path.relpath(path, ROOT))
        self.assertEqual(hits, [], "the old guide-change sentence is still in: %s" % ", ".join(hits))


class ContractSaysSocket(unittest.TestCase):
    def test_rule_4_all_reports_by_sendmessage_to_the_socket(self):
        rule = contract_rule(4)
        self.assertTrue(rule.startswith("End-of-work reports always go by SendMessage"), rule)
        for kind in KINDS:
            self.assertIn(kind, rule)
        self.assertIn("socket", rule)
        self.assertIn("uds:<socket path>", rule)
        self.assertRegex(rule, r"(?i)\bnever to the guide's session title\b")
        self.assertIn("a guide change never suspends this", rule.lower())
        self.assertIn("inbox/<id8>.md", rule)

    def test_contract_header_and_suffix_say_never_a_title(self):
        text = flat(read(os.path.join(REFS, "worker-contract.md")))
        self.assertIn("send to that socket, never a title", text)
        self.assertIn("by SendMessage to uds:<socket path>, exactly that address, never a title", text)
        self.assertIn("guide_title.py launch", text)
        self.assertIn("BEFORE its first prompt runs", text)

    def test_skill_guide_change_line_is_the_fixed_text(self):
        text = flat(read(SKILL))
        self.assertIn(GUIDE_CHANGE, text)
        self.assertIn("never suspends", text)
        self.assertIn("guide_title.py launch", text)


class StreamIconWording(unittest.TestCase):
    """The icon stands alone before the protocol word, which the guide's reconcile reads as the first word."""
    def test_the_contract_says_the_icon_alone(self):
        self.assertIn("the first line starts with the icon ALONE", contract_rule(2))
        self.assertIn("never with the stream's name", contract_rule(2))
        self.assertIn("\U0001f3e0 BLOCKED: \u2026", contract_rule(4))
        self.assertIn("start the first line of every report with it, alone",
                      flat(read(os.path.join(REFS, "worker-contract.md"))))

    def test_the_skill_says_where_an_icon_goes_and_where_it_does_not(self):
        text = flat(read(SKILL))
        self.assertIn("outside the quotes", text)
        self.assertIn("never in Open items, Results, owed-question or Owner cells", text)
        self.assertIn("\U0001f3e0 Decision 7 FINAL", text)
        self.assertIn("launch --stream <key>", text)
        self.assertIn("launch --successor-of <id>", text)
        self.assertIn("--active-ok", text)

    def test_the_question_header_in_the_skill_fits_twelve_characters(self):
        header = re.search(r"at most 8 characters \(\"([^\"]+)\"", flat(read(SKILL))).group(1)
        self.assertLessEqual(len(header) + 1, 12)  # an icon is two cells wide

    def test_the_ledger_template_has_the_icon_column_and_no_icon_in_owner(self):
        text = read(os.path.join(REFS, "ledger-template.md"))
        self.assertIn("| Icon | Stream | Where now | Next step | Owner | Blocked on |", text)
        table = text.split("\n## Open items")[1].split("\n## ")[0]
        self.assertNotRegex(table, "[\U0001f300-\U0001faff]")


if __name__ == "__main__":
    unittest.main()
