"""Review fixes after 0.2.0 rc: batch save on one connection, update check budget, topic union, from, recat, pending, favicon."""
import io
import json
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import build  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import describe  # noqa: E402
import update  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.d = helpers.tmp()
        self.con = db.connect(self.d)
        with open(os.path.join(self.d, "config.toml"), "w", encoding="utf-8") as f:
            f.write('[[categories]]\nname = "Reports"\n[[topics]]\nname = "Budget"\nkeywords = ["budget"]\n[[topics]]\nname = "Ops"\n')

    def save(self, lines, folder=None):
        folder = folder or os.path.join(self.d, "inbox", "batch", "1")
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, "reply.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        with redirect_stdout(io.StringIO()) as out:
            describe.batch_save(self.d, p)
        return out.getvalue()

    def row(self, aid):
        c = db.connect(self.d)
        r = db.get(c, aid)
        c.close()
        return r


class BatchSave(Base):
    def test_unreadable_does_not_lock_and_bad_line_is_skipped(self):
        for i in "abc":
            db.upsert_artifact(self.con, i, title="T" + i, owned=1)
        self.con.commit()
        out = self.save([json.dumps({"id": "a", "description": "A fine one.", "category": "Reports"}),
                         json.dumps({"id": "b", "description": "unreadable"}),
                         json.dumps({"id": "c", "description": "C fine.", "topics": 5, "new_topic": "X"}),
                         '{"id": "a", "topic_suggest": '])
        self.assertIn("saved 2, skipped 2", out)
        self.assertEqual(self.row("a")["description"], "A fine one.")
        self.assertEqual(self.row("b")["desc_source"], "title")
        self.assertEqual(self.row("b")["description"], "Tb")
        self.assertEqual(self.row("c")["description"], "C fine.")

    def test_exception_on_one_line_keeps_the_rest(self):
        db.upsert_artifact(self.con, "a", title="A", owned=1)
        db.upsert_artifact(self.con, "b", title="B", owned=1)
        self.con.commit()
        real = db.upsert_artifact

        def flaky(con, aid, **kw):
            if aid == "a":
                raise ValueError("boom")
            return real(con, aid, **kw)
        with mock.patch.object(db, "upsert_artifact", flaky):
            out = self.save([json.dumps({"id": "a", "description": "x"}), json.dumps({"id": "b", "description": "y"})])
        self.assertIn("saved 1, skipped 1", out)
        self.assertEqual(self.row("b")["description"], "y")

    def test_corrupt_topic_suggest_is_ignored(self):
        db.upsert_artifact(self.con, "a", title="A", owned=1, topic_suggest="{not json")
        self.con.commit()
        self.save([json.dumps({"id": "a", "new_topic": "Fresh"})])
        self.assertEqual(json.loads(self.row("a")["topic_suggest"]), ["Fresh"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(describe.topics_cmd(self.d), 0)

    def test_empty_topics_stored_as_null(self):
        db.upsert_artifact(self.con, "a", title="A", owned=1)
        self.con.commit()
        self.save([json.dumps({"id": "a", "description": "d", "topics": []})])
        self.assertIsNone(self.row("a")["topics"])


class TopicUnion(unittest.TestCase):
    def test_union(self):
        tr = build.compile_topics(".", [{"name": "Budget", "keywords": ["budget"]}, {"name": "Ops"}])
        t, _ = build.tag_topics(tr, "Budget plan", '["Ops"]', None)
        self.assertEqual(sorted(t), ["Budget", "Ops"])
        t, _ = build.tag_topics(tr, "Budget plan", "[]", None)
        self.assertEqual(t, ["Budget"])


class FromLabel(Base):
    def test_from(self):
        db.upsert_artifact(self.con, "a", title="A", owned=0, other_org=1)
        db.upsert_artifact(self.con, "b", title="B", owned=0, other_org=0)
        db.upsert_artifact(self.con, "c", title="C", owned=0)
        db.upsert_artifact(self.con, "d", title="D", owned=0, creator="Sam")
        self.con.commit()
        rows = {r["id"]: r for r in build.collect(self.d, common.load_config(self.d))[0]}
        self.assertEqual([rows[k]["mine"] for k in "abcd"], [False] * 4)
        self.assertTrue(all("from" not in rows[k] for k in "abcd"))


class Recat(Base):
    def test_no_empty_folder_and_none_not_reselected(self):
        with redirect_stdout(io.StringIO()):
            describe.batch_recat(self.d)
        self.assertFalse(os.path.exists(os.path.join(self.d, "inbox", "batch", "1")))
        db.upsert_artifact(self.con, "a", title="A", owned=1, description="d", desc_source="describer", desc_status="ok")
        self.con.commit()
        with redirect_stdout(io.StringIO()):
            describe.batch_recat(self.d)
        folder = os.path.join(self.d, "inbox", "batch", "1")
        self.assertTrue(os.path.exists(os.path.join(folder, "manifest.txt")))
        self.save([json.dumps({"id": "a", "category": "Nonsense"})], folder)
        self.assertEqual(self.row("a")["cat_source"], "none")
        shutil_before = os.listdir(os.path.join(self.d, "inbox", "batch"))
        with redirect_stdout(io.StringIO()):
            describe.batch_recat(self.d)
        self.assertEqual(os.listdir(os.path.join(self.d, "inbox", "batch")), shutil_before)

    def test_batch_start_clears_older(self):
        root = describe.batch_root(self.d)
        os.makedirs(os.path.join(root, "1"))
        with redirect_stdout(io.StringIO()):
            describe.batch_start(self.d)
        self.assertEqual(os.listdir(root), ["2"])


class Pending(Base):
    def test_gone_shared_not_pending(self):
        db.upsert_artifact(self.con, "a", title="A", owned=0, desc_status="pending")
        db.upsert_artifact(self.con, "b", title="B", owned=0, desc_status="pending", shared_gone=time.time())
        self.con.commit()
        ids = [r["id"] for r in describe.pending_rows(self.con, False)]
        self.assertEqual(ids, ["a"])


class UpdateBudget(unittest.TestCase):
    def test_hang_is_bounded_and_stamped(self):
        d = helpers.tmp()
        with mock.patch.object(update, "BUDGET", 0.2):
            t = time.time()
            self.assertIsNone(update.latest(d, "0.2.0", now=1000, get=lambda v: time.sleep(5)))
            self.assertLess(time.time() - t, 2)
        self.assertEqual(update._read(os.path.join(d, update.CACHE))["checked"], 1000)

    def test_raise_is_no_news(self):
        d = helpers.tmp()

        def bad(v):
            raise RuntimeError("x")
        self.assertIsNone(update.latest(d, "0.2.0", now=1000, get=bad))


class Favicon(unittest.TestCase):
    def test_oserror_does_not_raise(self):
        d = helpers.tmp()
        with mock.patch("os.replace", side_effect=OSError("ro")):
            build.write_favicon(d, "#336699")


if __name__ == "__main__":
    unittest.main()
