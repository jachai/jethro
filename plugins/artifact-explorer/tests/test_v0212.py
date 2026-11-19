"""0.2.12: works under any artifact-explorer@* install id; data copied from the old id; tag-based update check."""
import json
import os
import sqlite3
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import common  # noqa: E402
import update  # noqa: E402

OLD, NEW = "artifact-explorer@artifact-explorer", "artifact-explorer@jethro"


def ents(path="/nowhere/0.0.0"):
    return [{"scope": "user", "version": "0.2.9", "installPath": path}]


def config(plugins=None, settings=None, market=None):
    cfg = helpers.tmp()
    os.makedirs(os.path.join(cfg, "plugins"))
    if plugins is not None:
        json.dump({"version": 2, "plugins": plugins}, open(os.path.join(cfg, "plugins", "installed_plugins.json"), "w"))
    if settings is not None:
        json.dump(settings, open(os.path.join(cfg, "settings.json"), "w"))
    if market:
        json.dump(market, open(os.path.join(cfg, "plugins", "known_marketplaces.json"), "w"))
    return cfg


class Env(unittest.TestCase):
    def use(self, cfg):
        p = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfg})
        p.start()
        self.addCleanup(p.stop)


class KeyLookup(Env):
    def test_old_only_new_only_both(self):
        self.assertEqual(common.find_plugin_key({OLD: ents()}), OLD)
        self.assertEqual(common.find_plugin_key({NEW: ents()}), NEW)
        self.assertEqual(common.find_plugin_key({OLD: ents(), NEW: ents()}), NEW)  # default id wins with no path match
        self.assertEqual(common.find_plugin_key({"artifact-explorer@zzz": ents(), "other@x": ents()}), "artifact-explorer@zzz")
        self.assertIsNone(common.find_plugin_key({"other@x": ents(), "artifact-explorer": ents()}))
        self.assertIsNone(common.find_plugin_key(None))

    def test_install_path_of_running_code_wins(self):
        mine = os.path.join(os.path.dirname(common.ROOT), "x-" + os.path.basename(common.ROOT))
        self.assertEqual(common.find_plugin_key({OLD: ents(common.ROOT), NEW: ents(mine)}), OLD)
        self.assertEqual(common.find_plugin_key({OLD: ents(os.path.dirname(common.ROOT)), NEW: ents()}), OLD)  # parent dir

    def test_installed_entries_and_key(self):
        self.use(config({OLD: ents("/a/0.2.9")}))
        self.assertEqual(common.installed_key(), OLD)
        self.assertEqual(common.installed_entries()[0]["installPath"], "/a/0.2.9")
        self.assertEqual(common.marketplace_name(), "artifact-explorer")
        self.use(config({NEW: ents("/b/0.2.12")}))
        self.assertEqual(common.installed_key(), NEW)
        self.use(config({}))
        self.assertEqual(common.installed_key(), common.DEFAULT_KEY)
        self.assertEqual(common.installed_entries(), [])

    def test_default_data_dir_follows_key(self):
        self.use(config({OLD: ents()}))
        self.assertTrue(common.default_data_dir().endswith(os.path.join("plugins", "data", "artifact-explorer-artifact-explorer")))
        self.use(config({"artifact-explorer@my.mkt": ents()}))
        self.assertTrue(common.default_data_dir().endswith("artifact-explorer-my-mkt"))
        self.use(config())
        self.assertTrue(common.default_data_dir().endswith("artifact-explorer-jethro"))


class OptionsFallback(Env):
    def test_old_block_read_when_no_new_one(self):
        self.use(config({OLD: ents()}, {"pluginConfigs": {OLD: {"options": {"watch_interval": 33}}}}))
        self.assertEqual(common.options()["watch_interval"], 33)
        self.use(config({NEW: ents()}, {"pluginConfigs": {OLD: {"options": {"watch_interval": 33}}}}))
        self.assertEqual(common.options()["watch_interval"], 33)

    def test_new_block_wins_over_old(self):
        both = {OLD: {"options": {"watch_interval": 33}}, NEW: {"options": {"watch_interval": 5}}}
        self.use(config({NEW: ents()}, {"pluginConfigs": both}))
        self.assertEqual(common.options()["watch_interval"], 5)

    def test_no_block_gives_defaults(self):
        self.use(config({NEW: ents()}, {"pluginConfigs": {"other@x": {"options": {"watch_interval": 1}}}}))
        self.assertEqual(common.options()["watch_interval"], common.DEFAULT_OPTIONS["watch_interval"])


class DataCopy(Env):
    def layout(self):
        base = os.path.join(helpers.tmp(), "plugins", "data")
        old, new = (os.path.join(base, n) for n in ("artifact-explorer-artifact-explorer", "artifact-explorer-jethro"))
        os.makedirs(os.path.join(old, "thumbs"))
        for name, text in (("explorer.db", ""), ("explorer.db-wal", "w"), ("explorer.db-shm", "s"), ("config.toml", "c"),
                           ("watch.lock", "1"), ("ingest.lock", "1"), ("thumbs/a.png", "p")):
            with open(os.path.join(old, name), "w") as f:
                f.write(text)
        return old, new

    def test_copies_when_new_is_empty_and_skips_wal_shm_locks(self):
        old, new = self.layout()
        got = common.data_dir(new)
        self.assertEqual(got, new)
        self.assertTrue(os.path.exists(os.path.join(new, "explorer.db")))
        self.assertTrue(os.path.exists(os.path.join(new, "thumbs", "a.png")))
        self.assertTrue(os.path.exists(os.path.join(new, "config.toml")))
        for skipped in ("explorer.db-wal", "explorer.db-shm", "watch.lock", "ingest.lock"):
            self.assertFalse(os.path.exists(os.path.join(new, skipped)), skipped)
        self.assertTrue(os.path.exists(os.path.join(old, "explorer.db")))  # copied, never moved
        self.assertIn("copied the catalog", open(os.path.join(new, "watch.log")).read())

    def test_db_copy_includes_uncheckpointed_wal_rows(self):
        old, new = self.layout()
        for n in ("explorer.db", "explorer.db-wal", "explorer.db-shm"):
            os.remove(os.path.join(old, n))
        live = sqlite3.connect(os.path.join(old, "explorer.db"))  # stays open: the row lives in the -wal
        live.execute("PRAGMA journal_mode=wal")
        live.execute("PRAGMA wal_autocheckpoint=0")
        live.execute("CREATE TABLE t(x)")
        live.execute("INSERT INTO t VALUES ('row')")
        live.commit()
        self.addCleanup(live.close)
        common.data_dir(new)
        con = sqlite3.connect(os.path.join(new, "explorer.db"))
        self.assertEqual(con.execute("SELECT x FROM t").fetchall(), [("row",)])
        con.close()
        self.assertFalse(os.path.exists(os.path.join(new, "explorer.db.tmp")))

    def test_noop_when_new_has_a_db(self):
        old, new = self.layout()
        os.makedirs(new)
        open(os.path.join(new, "explorer.db"), "w").write("MINE")
        common.data_dir(new)
        self.assertEqual(open(os.path.join(new, "explorer.db")).read(), "MINE")
        self.assertFalse(os.path.exists(os.path.join(new, "config.toml")))

    def test_second_call_changes_nothing_and_no_old_folder_is_fine(self):
        old, new = self.layout()
        common.data_dir(new)
        open(os.path.join(new, "config.toml"), "w").write("edited")
        common.data_dir(new)
        self.assertEqual(open(os.path.join(new, "config.toml")).read(), "edited")
        lone = os.path.join(helpers.tmp(), "plugins", "data", "artifact-explorer-jethro")
        common.data_dir(lone)
        self.assertEqual(os.listdir(lone), [])

    def test_other_places_are_left_alone(self):
        d = helpers.tmp()  # not under plugins/data: never looks at siblings
        os.makedirs(os.path.join(d, "artifact-explorer-x"))
        open(os.path.join(d, "artifact-explorer-x", "explorer.db"), "w").write("x")
        common.data_dir(os.path.join(d, "artifact-explorer-y"))
        self.assertEqual(os.listdir(os.path.join(d, "artifact-explorer-y")), [])


def api(refs=None, error=None):
    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            return json.dumps(refs).encode()
    if error:
        return mock.Mock(side_effect=error)
    return mock.Mock(return_value=R())


def ref(v):
    return {"ref": "refs/tags/artifact-explorer--v" + v, "object": {}}


class TagUpdateCheck(Env):
    def test_url_asks_for_the_tag_prefix(self):
        self.assertEqual(update.URL, "https://api.github.com/repos/jachai/jethro/git/matching-refs/tags/artifact-explorer--v")

    def test_newest_by_version_tuple_not_by_text(self):
        m = api([ref("0.2.9"), ref("0.2.12"), ref("0.2.10"), {"ref": "refs/tags/artifact-explorer--vjunk"}, "x"])
        with mock.patch.object(update.urllib.request, "urlopen", m):
            self.assertEqual(update.fetch_release("0.2.9"), "v0.2.12")
        self.assertIn("matching-refs/tags/artifact-explorer--v", m.call_args[0][0].full_url)

    def test_404_and_other_failures_are_quiet_no_news(self):
        err = urllib.error.HTTPError(update.URL, 404, "Not Found", {}, None)
        for e in (err, OSError("offline"), ValueError("bad")):
            with mock.patch.object(update.urllib.request, "urlopen", api(error=e)):
                self.assertIsNone(update.fetch_release("0.2.9"))
        with mock.patch.object(update.urllib.request, "urlopen", api([])):
            self.assertIsNone(update.fetch_release("0.2.9"))

    def test_404_gives_no_badge_and_prints_nothing(self):
        self.use(config())
        err = urllib.error.HTTPError(update.URL, 404, "Not Found", {}, None)
        d = helpers.tmp()
        with mock.patch.object(update.urllib.request, "urlopen", api(error=err)), \
                mock.patch.dict(os.environ, {"AE_UPDATE_CHECK": "1"}), mock.patch("sys.stderr") as se, \
                mock.patch("sys.stdout") as so:
            self.assertIsNone(update.badge(d, "0.2.9", {}))
        se.write.assert_not_called()
        so.write.assert_not_called()

    def test_badge_has_commands_and_release_url(self):
        self.use(config({OLD: ents()}))
        with mock.patch.dict(os.environ, {"AE_UPDATE_CHECK": "1"}):
            b = update.badge(helpers.tmp(), "0.2.9", {}, now=1, get=lambda v: "v0.2.12")
        self.assertEqual(b["latest"], "v0.2.12")
        self.assertEqual(b["cmds"], ["/plugin marketplace update artifact-explorer", "/plugin update artifact-explorer@artifact-explorer"])
        self.assertEqual(b["url"], "https://github.com/jachai/jethro/releases/tag/artifact-explorer--v0.2.12")
        self.use(config())
        self.assertEqual(update.update_cmds(), ["/plugin marketplace update jethro", "/plugin update artifact-explorer@jethro"])


if __name__ == "__main__":
    unittest.main()
