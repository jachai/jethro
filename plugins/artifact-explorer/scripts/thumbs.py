"""Headless-browser thumbnails for artifacts that have a local file."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import db  # noqa: E402

SKELETON = ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<style>html,body{margin:0;background:#fff}</style></head><body>%s</body></html>')
MAC_APPS = ["Google Chrome", "Chromium", "Microsoft Edge", "Brave Browser"]
WIN_EXES = [("Google", "Chrome", "chrome.exe"), ("Microsoft", "Edge", "msedge.exe"),
            ("BraveSoftware", "Brave-Browser", "brave.exe")]
PATH_NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"]
FLAGS = ["--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run",
         "--window-size=1280,800", "--force-device-scale-factor=0.5", "--virtual-time-budget=4000"]
TIMEOUT = 45


def find_browser():
    env = os.environ.get("AE_BROWSER")
    if env:
        return env
    if sys.platform == "darwin":
        cands = ["/Applications/%s.app/Contents/MacOS/%s" % (a, a) for a in MAC_APPS]
    elif os.name == "nt":
        pf = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        cands = [os.path.join(b, v, a, "Application", e) for v, a, e in WIN_EXES for b in pf if b]
    else:
        cands = [shutil.which(n) for n in PATH_NAMES]
    return next((c for c in cands if c and os.path.exists(c)), None)


def wrap(text):
    """Return a full HTML document: fragments (no <html tag) get the skeleton."""
    return text if "<html" in text.lower() else SKELETON % text


def _shot(browser, src, out):
    tmp = tempfile.mkdtemp(prefix="ae-thumb-")
    try:
        with open(src, encoding="utf-8", errors="replace") as f:
            text = f.read()
        page = os.path.join(tmp, "page.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(wrap(text))
        shot = os.path.join(tmp, "shot.png")
        cmd = [browser] + FLAGS + ["--user-data-dir=" + os.path.join(tmp, "profile"), "--screenshot=" + shot,
                                   Path(page).as_uri()]
        subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=TIMEOUT)
        if os.path.exists(shot) and os.path.getsize(shot) > 0:
            os.replace(shot, out)
            return True
        return False
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(data, aid=None, limit=None):
    con = db.connect(data)
    try:
        if aid:
            rows = con.execute("SELECT id, local_path, thumb_status FROM artifacts WHERE id=?", (aid,)).fetchall()
        else:
            # 'none' = nothing to capture headlessly (no local file); such a row is retried once its file exists.
            # Rows older than the window wait (the page shows them collapsed, without a picture).
            cond, args = db.window_sql(db.window(con, common.load_config(data)))
            rows = con.execute("SELECT id, local_path, thumb_status FROM artifacts WHERE (thumb_status IS NULL "
                               "OR thumb_status='pending' OR (thumb_status='none' AND local_path<>'')) AND " + cond +
                               " ORDER BY updated DESC", args).fetchall()
            rows = [r for r in rows if r["thumb_status"] != "none" or os.path.isfile(r["local_path"])]
        browser, made = None, 0
        os.makedirs(os.path.join(data, "thumbs"), exist_ok=True)
        for r in rows:
            if limit is not None and made >= limit:
                break
            if not r["local_path"] or not os.path.isfile(r["local_path"]):
                db.upsert_artifact(con, r["id"], thumb_status="none")
                continue
            browser = browser or find_browser()
            rel = "thumbs/%s.png" % r["id"]
            if browser and _shot(browser, r["local_path"], os.path.join(data, rel)):
                db.upsert_artifact(con, r["id"], thumb=rel, thumb_source="headless", thumb_status="ok")
                made += 1
            else:
                db.upsert_artifact(con, r["id"], thumb_status="failed")
            con.commit()
        con.commit()
    finally:
        con.close()
    if made:
        import build
        build.build(data)
    return 0
