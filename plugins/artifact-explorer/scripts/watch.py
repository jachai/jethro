"""The watcher: one pass per watch_interval across all sessions. Never prints to stdout."""
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import db  # noqa: E402

TICK = 30
HEARTBEAT_FILE = "watcher.json"
FRESH = 4 * TICK  # a heartbeat younger than this (from a live pid) means a watcher is running


def heartbeat(data):
    """Record that a watcher loop is alive: DATA/watcher.json {pid, t}, written atomically."""
    path = os.path.join(data, HEARTBEAT_FILE)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "t": time.time()}, f)
        os.replace(tmp, path)
    except OSError:
        pass


def watcher_state(data):
    """{running, pid, seen} from the heartbeat file, judged now (the page shows it as of build)."""
    try:
        with open(os.path.join(data, HEARTBEAT_FILE), encoding="utf-8") as f:
            info = json.load(f)
        pid, seen = int(info.get("pid", 0)), float(info.get("t", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return {"running": False, "pid": None, "seen": None}
    return {"running": time.time() - seen < FRESH and common._pid_alive(pid), "pid": pid, "seen": seen}


def _due(con, opts):
    last = db.state_get(con, "last_pass", 0)
    return time.time() - last >= opts["watch_interval"] * 60


def run_pass(data, force=False):
    """One pass under watch.lock; skipped when another holder has it or (unless force) when not due."""
    opts = common.options()
    with common.Lock(os.path.join(data, "watch.lock"), 3 * opts["watch_interval"] * 60) as ok:
        if not ok:
            return 0
        import hook
        hook.ingest(data)
        con = db.connect(data)
        try:
            if not force and not _due(con, opts):
                return 0
            import history
            import thumbs
            import transcripts
            changed = 0
            if opts["browser_history"]:
                changed += history.scan(con, data)
            if opts["transcript_reads"]:
                changed += transcripts.scan(con, data)
            con.close()
            thumbs.run(data, limit=5)
            import describe
            describe.launch(data)
            con = db.connect(data)
            db.state_set(con, "last_pass", time.time())
            con.commit()
            con.close()
            heartbeat(data)
            import build
            # rebuilt when anything changed (changed rows, a new thumbnail), else once the page is an hour old,
            # so the page's "built" time and "last checked" stay true while a watcher runs
            build.build(data, max_age=common.PAGE_HEARTBEAT)
            con = db.connect(data)
        finally:
            con.close()
    return 0


def tick(data):
    """Check due-ness (options re-read each time) and run a pass when due. Never raises."""
    try:
        con = db.connect(data)
        try:
            due = _due(con, common.options())
        finally:
            con.close()
        if due:
            run_pass(data)
    except Exception:
        common.log(data, "watch: " + traceback.format_exc())


def loop(data, tick_seconds=TICK, max_ticks=None):
    ppid = os.getppid()
    n = 0
    while max_ticks is None or n < max_ticks:
        if os.name != "nt" and (os.getppid() == 1 or os.getppid() != ppid):
            return 0
        heartbeat(data)
        tick(data)
        n += 1
        time.sleep(tick_seconds)
    return 0
