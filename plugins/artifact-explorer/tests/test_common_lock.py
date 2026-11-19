import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import helpers  # noqa: E402
import common  # noqa: E402


class LockTest(unittest.TestCase):
    def test_exit_keeps_foreign_lock(self):
        p = os.path.join(helpers.tmp(), "l")
        with common.Lock(p, 60) as ok:
            self.assertTrue(ok)
            with open(p, "w") as f:
                json.dump({"pid": os.getpid(), "t": 1.5}, f)  # someone took over
        self.assertTrue(os.path.exists(p))

    def test_exit_removes_own_lock(self):
        p = os.path.join(helpers.tmp(), "l")
        with common.Lock(p, 60):
            pass
        self.assertFalse(os.path.exists(p))

    def test_stale_takeover(self):
        p = os.path.join(helpers.tmp(), "l")
        with open(p, "w") as f:
            json.dump({"pid": 0, "t": 0}, f)
        with common.Lock(p, 60) as ok:
            self.assertTrue(ok)
            with common.Lock(p, 60) as ok2:
                self.assertFalse(ok2)
        self.assertEqual(os.listdir(os.path.dirname(p)).count("l"), 0)
        self.assertEqual([n for n in os.listdir(os.path.dirname(p)) if n.endswith(".tmp")], [])

    def test_no_version_log_option(self):
        self.assertNotIn("version_log", common.DEFAULT_OPTIONS)


if __name__ == "__main__":
    unittest.main()
