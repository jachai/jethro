"""artifact-explorer CLI. Every hook, the monitor and the skills enter here through bin/ae."""
import argparse
import os
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
    s.add_argument("text")
    s = sub.add_parser("set-sharing", help="record an artifact's sharing state")
    s.add_argument("id")
    s.add_argument("text")
    s = sub.add_parser("pending", help="rows waiting for a description")
    s.add_argument("--owned-only", action="store_true")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("status", help="counts, last pass, spend today")
    s.add_argument("--json", action="store_true")
    sub.add_parser("open", help="open explorer.html in the default browser")
    a = p.parse_args(argv)
    data = common.data_dir(a.data)

    if a.cmd == "hook":
        import hook
        return hook.main(data)
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
    if a.cmd == "open":
        import build
        import webbrowser
        path = os.path.join(data, "explorer.html")
        if not os.path.exists(path):
            build.build(data)
        webbrowser.open("file://" + path.replace(os.sep, "/") if os.name != "nt" else path)
        print(path)
        return 0
    import describe
    if a.cmd == "launch-describer":
        return describe.launch(data)
    if a.cmd == "ingest-list":
        return describe.ingest_list(data, a.file)
    if a.cmd == "set-desc":
        return describe.set_desc(data, a.id, a.text)
    if a.cmd == "set-sharing":
        return describe.set_sharing(data, a.id, a.text)
    if a.cmd == "pending":
        return describe.pending(data, owned_only=a.owned_only, as_json=a.json)
    if a.cmd == "status":
        return describe.status(data, as_json=a.json)
    return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
