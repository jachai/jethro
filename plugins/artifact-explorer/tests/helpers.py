import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import db  # noqa: E402


def tmp():
    return tempfile.mkdtemp(prefix="ae-test-")


def con_for(data):
    return db.connect(data)
