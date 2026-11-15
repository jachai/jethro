import atexit
import os
import shutil
import sys
import tempfile

os.environ["AE_UPDATE_CHECK"] = "0"  # no test ever asks GitHub

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import db  # noqa: E402


def tmp():
    d = tempfile.mkdtemp(prefix="ae-test-")
    atexit.register(shutil.rmtree, d, True)
    return d


def con_for(data):
    return db.connect(data)
