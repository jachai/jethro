"""artifact-explorer CLI. Every hook, the monitor and the skills enter here through bin/ae."""
import argparse
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

VERSION = "0.2.12"


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
    s = sub.add_parser("import", help="import a catalog from the pre-plugin Artifact Explorer (read only)")
    s.add_argument("--from", dest="src", help="its folder (default: ~/.claude/artifact-explorer, where the pre-plugin version kept it)")
    s.add_argument("--thumbs-only", action="store_true", help="only copy its screenshots into rows without a thumbnail")
    s = sub.add_parser("launch-describer", help="start a background describer run when one is due")
    s.add_argument("--test", action="store_true", help="setup's check: start one now for a single row and say what happened")
    s.add_argument("--rows", type=int, help="start one now for at most N rows (1..60), ignoring the interval and back-off, and say what happened")
    s = sub.add_parser("doctor", help="which plugin version runs, what is installed, the data folder, the permission rule, a page check")
    s.add_argument("--expect", choices=["fresh", "installed", "any"], default="any",
                   help="fresh: fail unless the data folder is empty; installed: fail unless the installed version is the marketplace one")
    s = sub.add_parser("allow-rule", help="say whether the setup permission rule is in ~/.claude/settings.json")
    s = sub.add_parser("ingest-list", help="record Artifact list rows from a JSON file")
    s.add_argument("file")
    s.add_argument("--shared-complete", action="store_true",
                   help="the file holds every page of the shared list: shared rows missing from it are marked no longer shared")
    s = sub.add_parser("set-desc", help="set a description written by the describer")
    s.add_argument("id")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--file", help="UTF-8 file holding the sentence (never pass artifact-derived text as an argument)")
    g.add_argument("--no-source", action="store_true", help="no readable source: show the title, retried by `pending --retry-no-source`")
    g.add_argument("--needs-interactive", action="store_true",
                   help="the background run could not read it: the background run skips it, the in-session refresh describes it")
    s = sub.add_parser("set-kind", help="record the Artifact type a read reported (Data and Dashboard are one kind)")
    s.add_argument("pairs", nargs="+", metavar="ID=KIND", help="one or more ID=KIND pairs (the old form `ID KIND` also works)")
    s = sub.add_parser("set-sharing", help="record an artifact's sharing state")
    s.add_argument("id")
    s.add_argument("--file", required=True, help="UTF-8 file holding the phrase (never pass page-derived text as an argument)")
    s = sub.add_parser("pending", help="rows waiting for a description")
    s.add_argument("--owned-only", action="store_true")
    s.add_argument("--json", action="store_true")
    s.add_argument("--retry-no-source", action="store_true", help="first put title-only and typed-skipped rows back in the queue")
    s.add_argument("--limit", type=int, help="at most this many rows")
    s = sub.add_parser("window", help="show the recent window rows are described in; --widen N adds N days")
    s.add_argument("--widen", type=int, default=0)
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
    s.add_argument("file", nargs="+", help="one or more saved source files, joined in order")
    s.add_argument("--json-field", help="for the .json files: use this field's string (HTML or text)")
    s.add_argument("--out", required=True, help="where the excerpt goes; the caller never reads it, the describer agent does")
    s.add_argument("--chars", type=int, default=3000)
    s.add_argument("--id", help="the row: a typed artifact or a page with almost no text is marked skipped")
    s.add_argument("--type", help='the Artifact type the read reported (e.g. "Docs", "Slides", "HTML")')
    s = sub.add_parser("batch", help="describe several artifacts in one describer call: start | manifest FOLDER | recat | save FILE")
    bs = s.add_subparsers(dest="bcmd", required=True)
    bs.add_parser("start", help="print a new empty batch folder")
    b = bs.add_parser("manifest", help="write FOLDER/manifest.txt from the excerpts in it")
    b.add_argument("folder")
    b = bs.add_parser("recat", help="new batch folder + manifest of described rows that lack a category or topics")
    b.add_argument("--limit", type=int, default=8)
    b.add_argument("--owned-only", action="store_true", help="only your own artifacts (the background run)")
    b = bs.add_parser("local", help="no Artifact tool (background run): batch of own pending rows with a local source; "
                      "the others are marked needs interactive refresh")
    b.add_argument("--limit", type=int, default=8)
    b = bs.add_parser("excerpt", help="excerpt several saved pages: FOLDER ID=SAVED_FILE ... (like `excerpt SAVED_FILE --out FOLDER/ID.txt --id ID` each)")
    b.add_argument("folder")
    b.add_argument("pairs", nargs="+", metavar="ID=SAVED_FILE")
    b = bs.add_parser("save", help="store the describer's JSON lines")
    b.add_argument("file")
    b.add_argument("--folder", help="the batch folder whose manifest the reply answers (when the reply is written elsewhere)")
    s = sub.add_parser("topics", help="list topics and the describer's suggestions; --accept NAME adds one to config.toml")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--accept", metavar="NAME")
    g.add_argument("--reject", metavar="NAME")
    g.add_argument("--hide", metavar="NAME", help="hide a topic from the filter, cards and table (promoted or suggested)")
    g.add_argument("--unhide", metavar="NAME")
    s = sub.add_parser("tmpdir", help="print an empty per-row folder in the system temp dir for ArtifactData out_dir (the data folder is refused there)")
    s.add_argument("id")
    a = p.parse_args(argv)
    if a.cmd == "doctor":  # never creates the data folder: an empty or missing one is what "fresh" means
        import doctor
        return doctor.run(a.data or os.environ.get("AE_DATA") or common.default_data_dir(), VERSION, a.expect)
    if a.cmd == "allow-rule":
        present = common.allow_rule_present()
        miss = common.allow_rules_missing()
        have = [r for r in common.ALLOW_RULES if r not in miss]
        print(("present: " + have[0]) if present else "missing: " + miss[0])
        for r in miss:  # what setup would still add (both forms: the skills quote the path)
            print("add: " + r)
        return 0 if present else 1
    data = common.data_dir(a.data)

    if a.cmd == "tmpdir":
        import re
        import shutil
        import tempfile
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", a.id):
            print("bad id", file=sys.stderr)
            return 2
        uid = getattr(os, "getuid", lambda: os.environ.get("USERNAME", "user"))()
        base = os.path.join(tempfile.gettempdir(), "artifact-explorer-%s" % uid)
        os.makedirs(base, mode=0o700, exist_ok=True)
        if os.path.islink(base) or (hasattr(os, "getuid") and os.stat(base).st_uid != os.getuid()):
            print("unsafe temp folder: " + base, file=sys.stderr)
            return 2
        path = os.path.join(base, a.id)
        if os.path.islink(path):
            os.unlink(path)
        shutil.rmtree(path, ignore_errors=True)
        os.makedirs(path, mode=0o700)
        print(path)
        return 0

    if a.cmd == "hook":
        import hook
        return hook.main(data)
    if a.cmd == "ingest-hooks":
        import hook
        return hook.ingest(data)
    if a.cmd == "excerpt":
        import describe
        text, skipped = describe.excerpt_for(data, a.file, a.out, a.id, a.type, a.chars, a.json_field)
        print("skipped: no text to describe" if skipped else "%d characters" % len(text))
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
        print(build.build(data, max_age=0))  # asked for: always written, so its status is current
        return 0
    if a.cmd == "import":
        import importer
        return (importer.run_thumbs if a.thumbs_only else importer.run)(data, a.src or importer.default_src())
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
        return describe.launch(data, test=a.test, rows=max(1, min(60, a.rows)) if a.rows else None)
    if a.cmd == "ingest-list":
        return describe.ingest_list(data, a.file, shared_complete=a.shared_complete)
    if a.cmd == "batch":
        return {"start": lambda: describe.batch_start(data), "manifest": lambda: describe.batch_manifest(data, getattr(a, "folder", None)),
                "recat": lambda: describe.batch_recat(data, getattr(a, "limit", 8), getattr(a, "owned_only", False)),
                "local": lambda: describe.batch_local(data, getattr(a, "limit", 8)),
                "excerpt": lambda: describe.batch_excerpt(data, getattr(a, "folder", None), getattr(a, "pairs", None)),
                "save": lambda: describe.batch_save(data, getattr(a, "file", None), getattr(a, "folder", None))}[a.bcmd]()
    if a.cmd == "topics":
        return describe.topics_cmd(data, accept=a.accept, reject=a.reject, hide=a.hide, unhide=a.unhide)
    if a.cmd == "set-kind":
        return describe.set_kinds(data, a.pairs)
    if a.cmd == "set-desc":
        if a.no_source:
            return describe.set_no_source(data, a.id)
        if a.needs_interactive:
            return describe.set_needs_interactive(data, a.id)
        with open(a.file, encoding="utf-8") as f:
            return describe.set_desc(data, a.id, f.read())
    if a.cmd == "rows":
        return describe.rows(data, owned=a.owned, desc_status=a.desc_status, thumb_status=a.thumb_status, limit=a.limit)
    if a.cmd == "set-sharing":
        with open(a.file, encoding="utf-8") as f:
            return describe.set_sharing(data, a.id, f.read())
    if a.cmd == "pending":
        return describe.pending(data, owned_only=a.owned_only, as_json=a.json, retry_no_source=a.retry_no_source, limit=a.limit)
    if a.cmd == "window":
        return describe.widen(data, a.widen)
    if a.cmd == "status":
        return describe.status(data, as_json=a.json)
    return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
