"""0.2.9: suggested topics used on >= min_uses artifacts are promoted; near-duplicates merge first."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import build  # noqa: E402
import db  # noqa: E402
import promote  # noqa: E402


def sug(*names):
    return json.dumps(list(names))


class Merge(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(promote.key_of("Change  Orders"), promote.key_of("change order"))
        self.assertEqual(promote.key_of("Pricing"), "pricing")
        self.assertNotEqual(promote.key_of("class"), "clas")
        self.assertEqual(promote.key_of("Test-Suite"), "test suite")

    def test_prefix_rule_only_when_longer_has_fewer(self):
        rows = [sug("change orders")] * 3 + [sug("change order backlog")]
        t, _, c = promote.groups(rows)
        self.assertEqual(t["change order backlog"], "change order")
        self.assertEqual(c["change order"], 4)
        rows = [sug("change orders")] + [sug("change order backlog")] * 3
        t, _, c = promote.groups(rows)
        self.assertEqual(t["change order backlog"], "change order backlog")
        rows = [sug("change orders"), sug("change order backlog")]  # tie: no merge
        self.assertEqual(promote.groups(rows)[0]["change order backlog"], "change order backlog")

    def test_not_word_prefix(self):
        rows = [sug("price")] * 3 + [sug("pricing model")]
        self.assertEqual(promote.groups(rows)[0]["pricing model"], "pricing model")


class Promote(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = db.connect(self.d)

    def add(self, i, topics=None, suggest=None, title="T"):
        db.upsert_artifact(self.con, "a%d" % i, title=title, kind="Page", owned=1)
        self.con.execute("UPDATE artifacts SET topics=?, topic_suggest=? WHERE id=?",
                         (json.dumps(topics) if topics is not None else None, suggest, "a%d" % i))
        self.con.commit()

    def test_promote_at_two_and_sticks(self):
        self.add(1, [], sug("Pricing", "Solo"))
        self.add(2, [], sug("pricing"))
        auto, alias = promote.resolve(self.con, {})
        self.assertEqual(auto, ["Pricing"])
        self.assertEqual(alias["pricing"], "Pricing")
        self.con.execute("UPDATE artifacts SET topic_suggest=NULL WHERE id='a2'")
        self.con.commit()
        self.assertEqual(promote.resolve(self.con, {})[0], ["Pricing"])  # recorded, stays
        self.assertEqual(db.state_get(self.con, promote.STATE_KEY), {"pricing": "Pricing"})

    def test_min_uses_option_and_off(self):
        self.add(1, [], sug("A")); self.add(2, [], sug("A"))
        self.assertEqual(promote.resolve(self.con, {"topic_promote": {"min_uses": 3}})[0], [])
        self.assertEqual(promote.resolve(self.con, {"topic_promote": {"min_uses": 0}})[0], [])
        self.assertEqual(promote.resolve(self.con, {"topic_promote": {"min_uses": 1}})[0], ["A"])

    def test_demote_and_rename_stick(self):
        self.add(1, [], sug("Pricing", "Staging Verification")); self.add(2, [], sug("Pricing", "Staging Verification"))
        cfg = {"topic_promote": {"demote": ["staging verification"], "rename": {"Pricing": "Pricing Model"}}}
        auto, alias = promote.resolve(self.con, cfg)
        self.assertEqual(auto, ["Pricing Model"])
        self.assertEqual(alias["pricing"], "Pricing Model")
        self.assertNotIn("staging verification", alias)
        self.assertEqual(promote.resolve(self.con, cfg)[0], ["Pricing Model"])

    def test_configured_topic_untouched_and_absorbs_variant(self):
        self.add(1, [], sug("change order")); self.add(2, [], sug("change order"))
        cfg = {"topics": [{"name": "Change Orders"}]}
        auto, alias = promote.resolve(self.con, cfg)
        self.assertEqual(auto, [])
        self.assertEqual(alias["change order"], "Change Orders")


class Build(unittest.TestCase):
    def test_collect_applies_promoted_and_pinned_untouched(self):
        d = tempfile.mkdtemp()
        con = db.connect(d)
        for i, (t, s) in enumerate([("one", sug("Pricing")), ("two", sug("pricing", "Rare")), ("three", None)]):
            db.upsert_artifact(con, "a%d" % i, title=t, kind="Page", owned=1)
            con.execute("UPDATE artifacts SET topics=?, topic_suggest=? WHERE id=?", ("[]" if s else None, s, "a%d" % i))
        con.commit(); con.close()
        cfg = {"topics": [{"name": "Pinned", "keywords": ["three"]}]}
        rows = {r["title"]: r for r in build.collect(d, cfg)[0]}
        self.assertEqual(rows["one"]["topics"], ["Pricing"])
        self.assertEqual(rows["two"]["topics"], ["Pricing"])
        self.assertEqual(rows["two"]["suggested"], ["Rare"])
        self.assertEqual(rows["three"]["topics"], ["Pinned"])
        self.assertEqual(rows["one"]["suggested"], [])

    def test_untagged_rows_get_promoted_topic(self):  # 0.2.10: topics column NULL
        d = tempfile.mkdtemp()
        con = db.connect(d)
        for i in range(2):
            db.upsert_artifact(con, "a%d" % i, title="t%d" % i, kind="Page", owned=1)
            con.execute("UPDATE artifacts SET topic_suggest=? WHERE id=?", (sug("Pricing"), "a%d" % i))
        con.commit(); con.close()
        rows = build.collect(d, {})[0]
        self.assertEqual([r["topics"] for r in rows], [["Pricing"], ["Pricing"]])


if __name__ == "__main__":
    unittest.main()
