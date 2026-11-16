"""0.2.5: an unattended `claude -p` may not Write under ~/.claude, so every Write the refresh skill asks for goes to
the SCRATCH folder from `ae tmpdir` (system temp), and `ae batch save --folder` finds the manifest in the batch folder."""
import io
import json
import os
import re
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402

U = "https://claude.ai/artifact/"
SKILL = os.path.join(common.ROOT, "skills", "refresh", "SKILL.md")


def write_targets(txt):
    """Every path the skill tells the model to write with the Write tool."""
    return re.findall(r"with the Write tool to `([^`]+)`", txt)


class SkillWrites(unittest.TestCase):
    def setUp(self):
        self.txt = open(SKILL, encoding="utf-8").read()

    def test_every_write_goes_to_scratch(self):
        targets = write_targets(self.txt)
        self.assertGreaterEqual(len(targets), 4)  # result.jsonl, Slides/Docs/Dashboard source, list.json
        for t in targets:
            self.assertTrue(t.startswith("SCRATCH/"), t)

    def test_no_data_folder_paths_for_written_files(self):
        self.assertNotIn("INBOX", self.txt)
        self.assertNotIn("FOLDER/result.jsonl", self.txt)
        self.assertNotIn("CLAUDE_PLUGIN_DATA}/inbox", self.txt)

    def test_scratch_from_tmpdir_and_save_names_folder(self):
        self.assertIn("AE tmpdir scratch-bg", self.txt)
        self.assertIn('AE batch save "SCRATCH/result.jsonl" --folder "FOLDER"', self.txt)


class SaveFolder(unittest.TestCase):
    def test_save_with_folder_reads_manifest_there(self):
        d = helpers.tmp()
        f = os.path.join(d, "list.json")
        with open(f, "w") as fh:
            json.dump([{"url": U + "AAAAAAAAAAAA", "title": "Old", "scope": "mine"}], fh)
        describe.ingest_list(d, f)
        con = db.connect(d)
        db.upsert_artifact(con, "AAAAAAAAAAAA", description="A plan.", desc_source="describer", desc_status="ok")
        con.commit()
        con.close()
        buf = io.StringIO()
        with redirect_stdout(buf):
            describe.batch_recat(d, 20, True)
        folder = os.path.dirname(buf.getvalue().splitlines()[0])
        cat = common.load_config(d)["categories"][0]["name"]
        scratch = helpers.tmp()  # outside the data folder, as `ae tmpdir` gives
        reply = os.path.join(scratch, "result.jsonl")
        with open(reply, "w") as fh:
            fh.write(json.dumps({"id": "AAAAAAAAAAAA", "category": cat, "topics": []}) + "\n")
        with redirect_stdout(io.StringIO()):
            describe.batch_save(d, reply, folder)
        r = db.get(db.connect(d), "AAAAAAAAAAAA")
        self.assertEqual((r["category"], r["cat_source"]), (cat, "recat"))  # known as a recat via the manifest


if __name__ == "__main__":
    unittest.main()
