"""0.2.8: the background mode never makes an ArtifactData call; Dashboard/Data rows get --needs-interactive
and the rest of the batch is still saved."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import common  # noqa: E402
import describe  # noqa: E402
import db  # noqa: E402
from test_describer_v012 import Base, A, B, C  # noqa: E402

SKILL = os.path.join(common.ROOT, "skills", "refresh", "SKILL.md")


def section(txt, start, end):
    i = txt.index(start)
    return txt[i:txt.index(end, i)]


class SkillText(unittest.TestCase):
    def setUp(self):
        self.txt = open(SKILL, encoding="utf-8").read()

    def test_dashboard_branch_skipped_in_background(self):
        dash = section(self.txt, "**Dashboard** (type `Data` or `Dashboard`)", "**Slides.**")
        bg, full = dash.split("In the full mode:")
        self.assertIn("In the background mode, do not take this branch", bg)
        self.assertIn("no ArtifactData call", bg)
        self.assertIn("AE set-desc ID --needs-interactive", bg)
        self.assertIn("the batch is still described and saved", bg)
        self.assertNotIn("AE tmpdir ID`:", bg)
        self.assertIn("AE tmpdir ID", full)
        self.assertIn("ArtifactData, action `list`", full)

    def test_background_section_marks_dashboard_rows(self):
        bg = section(self.txt, "## Background mode", "## Full mode")
        self.assertIn("A Dashboard row", bg)
        self.assertIn("without any ArtifactData call", bg)
        self.assertIn("AE set-desc ID --needs-interactive", bg)
        self.assertIn("the rest of its batch is still described and saved", bg)
        self.assertNotIn("ArtifactData, action", bg)

    def test_out_dir_rule_full_mode_only(self):
        self.assertIn("(full mode only; the background mode makes no ArtifactData call)", self.txt)


class NeedsInteractive(Base):
    def test_dashboard_row_marked_others_stay_pending(self):
        con = self.con()
        db.upsert_artifact(con, A, kind="Dashboard")
        con.commit()
        con.close()
        self.assertEqual(describe.set_needs_interactive(self.d, A), 0)
        con = self.con()
        self.assertEqual(db.get(con, A)["desc_note"], describe.NEEDS_INTERACTIVE)
        for x in (B, C):  # the rest of the batch is untouched and still to be described
            self.assertNotEqual(db.get(con, x)["desc_note"], describe.NEEDS_INTERACTIVE)
            self.assertEqual(db.get(con, x)["desc_status"], "pending")

if __name__ == "__main__":
    unittest.main()
