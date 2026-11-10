"""artifact-explorer CLI. Every hook, the monitor and the skills enter here through bin/ae."""
import argparse
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

VERSION = "0.1.0"


def main(argv=None):
    p = argparse.ArgumentParser(prog="ae", description="Artifact Explorer")
    p.add_argument("--version", action="version", version="artifact-explorer " + VERSION)
    p.add_argument("--data", help="data folder (default: $AE_DATA or the plugin data folder)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hook", help="PostToolUse(Artifact) / SessionStart hook; JSON on stdin")
    sub.add_parser("watch", help="monitor loop: one pass per watch_interval across all sessions")
    sub.add_parser("pass", help="run one watcher pass now")
    s = sub.add_parser("thumbs", help="make headless thumbnails for rows that need one")
    s.add_argument("--id")
    s.add_argument("--limit", type=int)
    sub.add_parser("build", help="rebuild explorer.html")
    s = sub.add_parser("import", help="import an old ~/.claude/artifact-explorer folder (read only)")
    s.add_argument("--from", dest="src", default=os.path.join(os.path.expanduser("~"), ".claude", "artifact-explorer"))
    sub.add_parser("launch-describer", help="start a background describer run when one is due")
    s = sub.add_parser("ingest-list", help="record Artifact list rows from a JSON file")
    s.add_argument("file")
    s = sub.add_parser("set-desc", help="set a description written by the describer")
    s.add_argument("id")
    s.add_argument("--file", required=True, help="UTF-8 file holding the sentence (never pass artifact-derived text as an argument)")
    s = sub.add_parser("set-sharing", help="record an artifact's sharing state")
    s.add_argument("id")
    s.add_argument("--file", required=True, help="UTF-8 file holding the phrase (never pass page-derived text as an argument)")
    s = sub.add_parser("pending", help="rows waiting for a description")
    s.add_argument("--owned-only", action="store_true")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("rows", help="list artifacts as JSON")
    s.add_argument("--json", action="store_true", required=True)
    s.add_argument("--owned", action="store_true")
    s.add_argument("--desc-status")
    s.add_argument("--thumb-status")
    s.add_argument("--limit", type=int)
    s = sub.add_parser("status", help="counts, last pass, spend today")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("share-window", help="mark the start or end of a share-dialog harvest (its visits are ignored)")
    s.add_argument("edge", choices=["start", "end"])
    s = sub.add_parser("set-thumb", help="record a thumbnail file saved under DATA/thumbs, or mark a row failed")
    s.add_argument("id")
    s.add_argument("file", nargs="?", help="path relative to the data folder, e.g. thumbs/<id>.png; omit to mark failed")
    s.add_argument("--source", default="chrome")
    sub.add_parser("open", help="open explorer.html in the default browser")
    sub.add_parser("ingest-hooks", help="record spooled hook payloads (run by the hook and by each watcher pass)")
    s = sub.add_parser("excerpt", help="write the visible text of a saved artifact file, capped, to --out for the describer agent")
    s.add_argument("file")
    s.add_argument("--out", required=True, help="where the excerpt goes; the caller never reads it, the describer agent does")
    s.add_argument("--chars", type=int, default=3000)
    a = p.parse_args(argv)
    data = common.data_dir(a.data)

    if a.cmd == "hook":
        import hook
        return hook.main(data)
    if a.cmd == "ingest-hooks":
        import hook
        return hook.ingest(data)
    if a.cmd == "excerpt":
        import describe
        text = describe.excerpt(a.file, a.chars)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("%d characters" % len(text))
        return 0
    if a.cmd == "watch":
        import watch
        return watch.loop(data)
    if a.cmd == "pass":
        import watch
        return watch.run_pass(data, force=True)
    if a.cmd == "thumbs":
        import thumbs
        return thumbs.run(data, aid=a.id, limit=a.limit)
    if a.cmd == "build":
        import build
        print(build.build(data))
        return 0
    if a.cmd == "import":
        import importer
        return importer.run(data, a.src)
    if a.cmd in ("share-window", "set-thumb"):
        import time
        import db
        con = db.connect(data)
        with con:
            if a.cmd == "share-window":
                wins = db.state_get(con, "share_windows", [])
                if a.edge == "start":
                    wins.append([time.time(), None])
                elif wins and wins[-1][1] is None:
                    wins[-1][1] = time.time()
                db.state_set(con, "share_windows", wins[-50:])
            elif a.file and os.path.exists(os.path.join(data, a.file)):
                db.upsert_artifact(con, a.id, thumb=a.file.replace(os.sep, "/"), thumb_source=a.source, thumb_status="ok")
            else:
                db.upsert_artifact(con, a.id, thumb_status="failed")
        return 0
    if a.cmd == "open":
        import build
        import webbrowser
        path = os.path.join(data, "explorer.html")
        if not os.path.exists(path):
            build.build(data)
        webbrowser.open(pathlib.Path(path).resolve().as_uri())
        print(path)
        return 0
    import describe
    if a.cmd == "launch-describer":
        return describe.launch(data)
    if a.cmd == "ingest-list":
        return describe.ingest_list(data, a.file)
    if a.cmd == "set-desc":
        with open(a.file, encoding="utf-8") as f:
            return describe.set_desc(data, a.id, f.read())
    if a.cmd == "rows":
        return describe.rows(data, owned=a.owned, desc_status=a.desc_status, thumb_status=a.thumb_status, limit=a.limit)
    if a.cmd == "set-sharing":
        with open(a.file, encoding="utf-8") as f:
            return describe.set_sharing(data, a.id, f.read())
    if a.cmd == "pending":
        return describe.pending(data, owned_only=a.owned_only, as_json=a.json)
    if a.cmd == "status":
        return describe.status(data, as_json=a.json)
    return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
