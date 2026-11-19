import os
import time
import unittest
from unittest import mock

import helpers
import common
import db
import watch


def stubs():
    m = {n: mock.Mock() for n in ("history", "transcripts", "thumbs", "build", "describe")}
    m["history"].scan.return_value = 0
    m["transcripts"].scan.return_value = 2
    return m


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.data = helpers.tmp()

    def test_pass_order_and_last_pass(self):
        m = stubs()
        order = mock.Mock()
        for n, mm in m.items():
            order.attach_mock(mm, n)
        with mock.patch.dict("sys.modules", m):
            self.assertEqual(watch.run_pass(self.data, force=True), 0)
        names = [c[0] for c in order.mock_calls]
        self.assertEqual(names, ["history.scan", "transcripts.scan", "thumbs.run", "describe.launch", "build.build"])
        m["thumbs"].run.assert_called_once_with(self.data, limit=5)
        con = db.connect(self.data)
        self.assertGreater(db.state_get(con, "last_pass"), time.time() - 5)
        self.assertFalse(os.path.exists(os.path.join(self.data, "watch.lock")))

    def test_not_due_skips_and_build_is_left_to_its_heartbeat(self):
        con = db.connect(self.data)
        db.state_set(con, "last_pass", time.time())
        con.commit()
        con.close()
        m = stubs()
        with mock.patch.dict("sys.modules", m):
            watch.run_pass(self.data)
        m["history"].scan.assert_not_called()
        m["transcripts"].scan.return_value = 0
        with mock.patch.dict("sys.modules", m):
            watch.run_pass(self.data, force=True)
        # 0.1.3: every pass asks for a build; build skips an unchanged page until it is PAGE_HEARTBEAT old
        m["build"].build.assert_called_once_with(self.data, max_age=common.PAGE_HEARTBEAT)

    def test_options_off(self):
        m = stubs()
        with mock.patch.dict("sys.modules", m), mock.patch("common.options", lambda: dict(
                watch_interval=10, browser_history=False, transcript_reads=False)):
            watch.run_pass(self.data, force=True)
        m["history"].scan.assert_not_called()
        m["transcripts"].scan.assert_not_called()

    def test_held_lock_skips(self):
        open(os.path.join(self.data, "watch.lock"), "w").write('{"pid": %d, "t": %f}' % (os.getpid(), time.time()))
        m = stubs()
        with mock.patch.dict("sys.modules", m):
            watch.run_pass(self.data, force=True)
        m["transcripts"].scan.assert_not_called()

    def test_loop_survives_errors_and_prints_nothing(self):
        m = stubs()
        m["transcripts"].scan.side_effect = RuntimeError("boom")
        with mock.patch.dict("sys.modules", m), mock.patch("sys.stdout") as out, \
                mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": helpers.tmp()}):  # never the real ~/.claude
            self.assertEqual(watch.loop(self.data, tick_seconds=0, max_ticks=2), 0)
        out.write.assert_not_called()
        self.assertIn("boom", open(os.path.join(self.data, "watch.log")).read())


if __name__ == "__main__":
    unittest.main()
