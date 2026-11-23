#!/usr/bin/env python3
"""guide_streams: one icon and one short name per stream (project), shared by every session that works on it.

    guide_title.py stream add <key> "<name>" [--icon 🏠]      a new stream (or reopen an ended key); no --icon: the next free one
    guide_title.py stream rename <key> [--name "<name>"] [--icon 🏠]
    guide_title.py stream end <key>                          finished: its icon is free again after 7 days
    guide_title.py stream list [--all]                       the open streams and their sessions (--all: the ended ones too)
    guide_title.py stream suggest [<n>]                      free icons
    guide_title.py stream assign <key> <id>… [--active-ok]   these sessions work on it; --active-ok: the user said yes to
                                                             an icon on a session of their own (not managed or watched)
    guide_title.py stream strip <id>… | --all                take the icon off titles again
    guide_title.py stream table [--end-unlisted]             refresh the ledger's ## Streams table (its Icon column)
    guide_title.py launch --stream <key> | --successor-of <id> -- <claude args…>

The registry is `streams.json` next to the ledger, written only by this script (a lock, then an atomic replace):

    {"billing": {"icon": "🏠", "name": "Billing export", "state": "open", "since": "2026-11-22", "ended": null,
              "sessions": ["<session id>", …]}}

`assign` also writes `$CLAUDE_CONFIG_DIR/session-guide/streams/<session id>` ({"icon", "key", "old"}), so a worker's
hook finds its icon with one small read. The marker file keeps holding the level alone: other tools read its exact text.

The icon goes right after the level prefix ("🟧🟧 (g) 🏠 billing lead"), never before it, and comes back after a rename.
A session with no stream keeps exactly the title it would have without this file. An icon is one wide character that
is no level mark (or, out of icons, a tag such as [TW]), and belongs to one open stream per machine. A stream that
ended keeps its icon on its sessions' titles. Icons are added when a row is shown (the hook's lines, settle, STATE.md);
they are never stored in a Results or owed-question row, whose key is made from its text.

SESSION_GUIDE_STREAM_ICONS=0 turns every icon off (what a title already shows then counts as its name; `strip` takes
it off). Python 3 stdlib only.
"""
import contextlib
import glob
import json
import os
import re
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guide_title as gt  # noqa: E402

# Told apart by shape, not only by color; one code point each, two cells wide.
ICONS = ("\U0001f3e0\U0001f6a2\U0001f4b0\U0001f9ed\U0001f50d\U0001f9f0\U0001f30a\U0001f3b4\U0001f50c\U0001f4ce\U0001f9ea"
         "\U0001f4e6\U0001f3af\U0001f41d\U0001f34b\U0001f680\U0001fa99\U0001f9f2\U0001f511\U0001f388\U0001f333\U0001f4da"
         "\U0001f3b8\U0001f514")
LEVEL_MARKS = "⬜\U0001f7e6✅\U0001f7e5\U0001f7e7\U0001f39f"
TAG = re.compile(r"\[[A-Z0-9]{2}\]$")
KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,23}$")
NAME_MAX = 24
FREE_AFTER_DAYS = 7  # an ended stream's icon stays taken this long
QUIET_DAYS = 7  # an open stream nobody worked on this long is named to the guide, to end it
SECTION = "## Streams"
TABLE = ["| Icon | Stream | Where now | Next step | Owner | Blocked on |\n", "|---|---|---|---|---|---|\n"]
DAY = "%Y-%m-%d"


def enabled():
    return (os.environ.get("SESSION_GUIDE_STREAM_ICONS") or "1").strip().lower() not in ("0", "off", "false", "no")


# --- the registry

def registry_path(ledger):
    return os.path.join(os.path.dirname(os.path.abspath(os.path.expanduser(ledger))), "streams.json")


def load(path):
    """The registry in `path`; ValueError when it is there but isn't one (a writer must not replace it)."""
    try:
        with open(path, encoding="utf-8") as f:
            found = json.load(f)
    except FileNotFoundError:
        return {}
    if not isinstance(found, dict) or not all(
            isinstance(s, dict) and isinstance(s.get("icon"), str) and isinstance(s.get("name"), str)
            for s in found.values()):
        raise ValueError("not a stream registry")
    for s in found.values():
        s.setdefault("state", "open")
        s["sessions"] = [i for i in s.get("sessions") or [] if isinstance(i, str)]
    return found


def read(ledger):
    """The ledger's streams by key; {} when the file is missing or can't be read (readers fail open)."""
    try:
        return load(registry_path(ledger))
    except (OSError, ValueError):
        return {}


def save(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "w") as lock:
        try:
            import fcntl  # not on Windows: no lock there, the replace is still atomic
            fcntl.flock(lock, fcntl.LOCK_EX)
        except ImportError:
            pass
        yield


@contextlib.contextmanager
def editing(ledger):
    """The registry to change under the lock; saved when the block ends without an error."""
    path = registry_path(ledger)
    with locked(path):
        try:
            found = load(path)
        except (OSError, ValueError) as error:
            raise SystemExit("%s can't be read (%s); fix or move it first, nothing was changed" % (path, error))
        yield found
        save(path, json.dumps(found, ensure_ascii=False, indent=1) + "\n")


def stream(streams, key):
    if key not in streams:
        raise SystemExit("no stream %r; there are: %s" % (key, ", ".join(sorted(streams)) or "none"))
    return streams[key]


# --- icons

def icon_problem(icon):
    """Why `icon` can't be a stream's icon, or None."""
    if TAG.match(icon):
        return None
    prefixes = gt.guided_prefix() + gt.watched_prefix() + gt.active_prefix() + gt.done_prefix()
    if any(c in LEVEL_MARKS for c in icon) or (len(icon) == 1 and icon in prefixes):
        return "it reads as a level mark"
    if len(icon) != 1 or unicodedata.east_asian_width(icon) != "W" or unicodedata.category(icon) not in ("So", "Cn"):
        return "use one wide emoji of a single code point (see `stream suggest`), or a tag such as [TW]"
    return None


def taken(ledger, but=None):
    """{icon: which stream has it}: the streams of every ledger on this machine that are open, or ended less than
    FREE_AFTER_DAYS ago. `but` is a key of this ledger to leave out."""
    mine, found = registry_path(ledger), {}
    others = glob.glob(os.path.join(gt.config_dir(), "session-guide", "*", "streams.json"))
    for path in [mine] + [p for p in others if os.path.realpath(p) != os.path.realpath(mine)]:
        try:
            streams = load(path)
        except (OSError, ValueError):
            continue
        for key, s in streams.items():
            if not (path == mine and key == but) and (s["state"] == "open" or days_since(s.get("ended")) < FREE_AFTER_DAYS):
                found.setdefault(s["icon"], "%s (%s, %s)" % (key, s["state"], path))
    return found


def days_since(day):
    try:
        return (time.time() - time.mktime(time.strptime(day or "", DAY))) / 86400
    except ValueError:
        return float("inf")


def suggest(ledger, but=None):
    used = taken(ledger, but)
    return [i for i in ICONS if i not in used and not icon_problem(i)]


def pick(ledger, icon, key):
    """`icon` when the stream `key` may have it, or the next free one when it is None; SystemExit otherwise."""
    if icon is None:
        free = suggest(ledger, key)
        if not free:
            raise SystemExit("no free icon left: pass --icon with a two-letter tag, such as --icon '[%s]'"
                             % key.replace("-", "")[:2].upper())
        return free[0]
    icon = icon.strip()
    problem = icon_problem(icon)
    if problem:
        raise SystemExit("%r can't be a stream icon: %s" % (icon, problem))
    owner = taken(ledger, key).get(icon)
    if owner:
        raise SystemExit("%s belongs to stream %s; free: %s" % (icon, owner, " ".join(suggest(ledger, key)[:8])))
    return icon


# --- a session's own icon

def session_path(session_id):
    return os.path.join(gt.config_dir(), "session-guide", "streams", session_id)


def session_stream(session_id):
    """{icon, key, old} from the session's own small file, or None. An empty icon: stripped."""
    try:
        with open(session_path(session_id), encoding="utf-8") as f:
            found = json.load(f)
        return dict(icon=str(found["icon"]), key=str(found["key"]), old=[str(i) for i in found.get("old") or [] if i])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def title_icons(session_id):
    """(the icon its title carries, the ones to take off it). Icons turned off: only a stripped session has any."""
    found = session_stream(session_id)
    if not found or not enabled() and found["icon"]:
        return "", ()
    return found["icon"], tuple(i for i in found["old"] if i != found["icon"])


def set_session(session_id, key, icon):
    """Give the session `icon` (or take its icon off, icon ""), keeping the ones its title may still show."""
    was = session_stream(session_id) or dict(icon="", old=[])
    old = [i for i in dict.fromkeys(was["old"] + [was["icon"]]) if i and i != icon]
    save(session_path(session_id), json.dumps(dict(icon=icon, key=key, old=old), ensure_ascii=False) + "\n")
    gt.sync_session_titles(session_id, gt.marker_content(session_id))


def forget_stripped(session_id):
    """A stripped session's title is clean: nothing left to undo."""
    found = session_stream(session_id)
    if found and not found["icon"]:
        os.remove(session_path(session_id))


def assign(ledger, key, session_id, active_ok=False):
    """Put the session on the stream, and off any other; the line to print. SystemExit when it may not."""
    content = gt.marker_content(session_id)
    if content == gt.DONE:
        raise SystemExit("%s is closed; closed sessions keep the title they have" % session_id[:8])
    if content is not None and content not in gt.WORKER_MARKERS:
        raise SystemExit("%s is a guide%s; guides get no icon" % (session_id[:8], " (retired)" * (content == gt.RETIRED)))
    if content is None and not glob.glob(os.path.join(gt.config_dir(), "projects", "*", session_id + ".jsonl")):
        raise SystemExit("no session with id %s: check the id (peek.py lists them)" % session_id)
    if content not in (gt.GUIDED, gt.WATCHED) and not active_ok:
        raise SystemExit("%s is not managed or watched: it is the user's own window. Ask first; with a yes, pass "
                         "--active-ok" % session_id[:8])
    with editing(ledger) as streams:
        s = stream(streams, key)
        if s["state"] != "open":
            raise SystemExit("stream %s has ended; `stream add %s` reopens it" % (key, key))
        for other in streams.values():
            other["sessions"] = [i for i in other["sessions"] if i != session_id]
        s["sessions"].append(session_id)
        set_session(session_id, key, s["icon"])
    return "%s is on %s %s (%s); the icon goes into its title on its next prompt" % (session_id[:8], s["icon"], s["name"], key)


def stream_key_of(ledger, session_id):
    """The key of the stream the session is on, by the registry, else by its own file; None when it is on none."""
    streams = read(ledger)
    for key, s in streams.items():
        if session_id in s["sessions"]:
            return key
    found = session_stream(session_id)
    return found["key"] if found and found["key"] in streams else None


# --- where icons are shown

def icon_of(streams, text):
    """The icon of the first session id6 in `text` (as `[3fa9c1]`) that is on a stream, or ""."""
    for rid in re.findall(r"\[([0-9a-fA-F]{6,36})\]", text or ""):
        for s in streams.values():
            if any(i[:6].lower() == rid[:6].lower() for i in s["sessions"]):
                return s["icon"]
    return ""


def shown(ledger, text, *more):
    """`text` with its stream's icon in front, for display only: the icon of the first stream session named in it (or
    in `more`). A text that starts with an icon already, or names no such session, comes back as it is."""
    streams = read(ledger) if enabled() else {}
    if not streams or any(starts(text, s["icon"]) for s in streams.values()):
        return text
    icon = next(filter(None, (icon_of(streams, t) for t in (text,) + more)), "")
    return icon + " " + text if icon else text


def starts(text, icon):
    return bool(icon) and (text == icon or text.startswith(icon + " "))


def unmarked(ledger, text):
    """`text` without stream icons in front, for a cell whose key is made from its text."""
    icons = {s["icon"] for s in read(ledger).values()}
    while True:
        icon = next((i for i in icons if starts(text, i) and text != i), None)
        if not icon:
            return text
        text = text[len(icon):].lstrip()


def open_streams(streams):
    return [(k, s) for k, s in sorted(streams.items()) if s["state"] == "open"]


def quiet(streams, days=QUIET_DAYS):
    """[(key, stream)] of the open streams no session wrote in for `days`."""
    now, found = time.time(), []
    for key, s in open_streams(streams):
        if days_since(s.get("since")) < days:
            continue
        if not any(now - os.path.getmtime(p) < days * 86400 for sid in reversed(s["sessions"])
                   for p in glob.glob(os.path.join(gt.config_dir(), "projects", "*", sid + ".jsonl"))):
            found.append((key, s))
    return found


def context(ledger):
    """What the guide hears about streams on a prompt, or None: the icons to use, and the streams to end."""
    streams = read(ledger) if enabled() else {}
    live = open_streams(streams)
    if not live:
        return None
    parts = ["session-guide streams: start every question, status line and message about a stream with its icon "
             "(SKILL §5): " + " · ".join("%s %s (%s)" % (s["icon"], s["name"], k) for k, s in live)]
    idle = quiet(streams)
    if idle:
        parts.append("No activity for %d days: %s. Finished: `python3 %s stream end <key>`."
                     % (QUIET_DAYS, ", ".join("%s %s" % (s["icon"], k) for k, s in idle), os.path.abspath(gt.__file__)))
    return "\n".join(parts)


def state_lines(ledger):
    """STATE.md's Streams section; [] when there are no open streams."""
    live = open_streams(read(ledger)) if enabled() else []
    return live and ["", "## Streams (%d open)" % len(live)] + [
        "- %s %s (%s), since %s: %s" % (s["icon"], s["name"], k, s.get("since") or "?",
                                         ", ".join(i[:6] for i in s["sessions"][-8:]) or "no sessions") for k, s in live]


def refresh_table(ledger, end_unlisted=False):
    """Give the ledger's Streams table its Icon column and one row per stream; never deletes a row. With `end_unlisted`
    a row of no registered stream, not DONE yet, gets "ended <today>" before what its Where now cell says. Returns how
    many rows changed."""
    streams = read(ledger)
    lines = open(ledger, encoding="utf-8", errors="replace").read().splitlines(True)
    if not streams and not end_unlisted:
        return 0
    before = list(lines)
    start, end = gt.section_span(lines, SECTION, SECTION, ("## Order", "## Sessions"))
    at = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
    if not at:
        lines[start + 1:start + 1] = TABLE + ([] if lines[start + 1:start + 2] == ["\n"] else ["\n"])
        at = [start + 1, start + 2]
    first, last = at[0], at[0]
    while last + 1 < len(lines) and lines[last + 1].lstrip().startswith("|"):  # one table; what is below it stays
        last += 1
    written = lines[first:last + 1]
    rows = [table_cells(l) for l in written]
    was = [list(r) for r in rows]
    head = [c.lower() for c in rows[0]]
    if "icon" not in head:
        rows = [(["Icon"] if n == 0 else ["---"] if n == 1 and set("".join(r)) <= set("-: ") else [""]) + r
                for n, r in enumerate(rows)]
        head = ["icon"] + head
    icon_at, name_at = head.index("icon"), head.index("stream") if "stream" in head else 1
    where_at = head.index("where now") if "where now" in head else None
    body = [r + [""] * (len(head) - len(r)) for r in rows[2:]]
    today, listed = time.strftime(DAY), set()
    for key, s in sorted(streams.items(), key=lambda kv: kv[1].get("since") or ""):
        same = [r for r in body if r[name_at].lower() in (s["name"].lower(), key)]
        if not same and s["state"] == "open":
            row = ["—"] * len(head)
            row[icon_at], row[name_at] = s["icon"], s["name"]
            body.append(row)
            same = [row]
        for row in same:
            listed.add(id(row))
            row[icon_at], row[name_at] = s["icon"], s["name"]
            if s["state"] == "ended":
                end_row(row, where_at, s.get("ended") or today)
    if end_unlisted:
        for row in body:
            if id(row) not in listed:
                end_row(row, where_at, today)
    out = rows[:2] + body
    lines[first:last + 1] = [written[n] if n < len(was) and r[:len(was[n])] == was[n] and not any(r[len(was[n]):])
                             else "| %s |\n" % " | ".join(r) for n, r in enumerate(out)]
    if lines == before:
        return 0
    gt.write_ledger(ledger, lines)
    return len([l for l in lines if l not in before])


def table_cells(line):
    line = line.strip()
    return gt.split_row(line if line.endswith("|") else line + "|")


def end_row(row, where_at, day):
    where = row[where_at] if where_at is not None else ""
    if where_at is not None and not re.match(r"[~*\s\u2705\ufe0f]*(?:ended|DONE)\b", where):
        row[where_at] = "ended %s%s" % (day, "; was: " + where if where not in ("", "—", "-") else "")


# --- commands

def clean_name(name):
    name = " ".join(name.split())
    if not name or len(name) > NAME_MAX or "|" in name:
        raise SystemExit("a stream's name is 1 to %d characters, without a pipe" % NAME_MAX)
    return name


def cmd_add(args, ledger):
    key = args.key.strip().lower()
    if not KEY.match(key):
        raise SystemExit("a key is 1 to 24 of a-z, 0-9 and -, for example `billing`")
    with editing(ledger) as streams:
        old = streams.get(key)
        if old and old["state"] == "open":
            raise SystemExit("stream %s is open already: %s %s" % (key, old["icon"], old["name"]))
        if not args.name and not old:
            raise SystemExit('give it a short name: stream add %s "<name>"' % key)
        name = clean_name(args.name or old["name"])
        icon = args.icon
        if icon is None and old and old["icon"] not in taken(ledger, key):
            icon = old["icon"]
        icon = pick(ledger, icon, key)
        streams[key] = dict(icon=icon, name=name, state="open", since=time.strftime(DAY), ended=None,
                            sessions=old["sessions"] if old else [])
        if old and old["icon"] != icon:
            carry(streams[key], key)
    print("%s %s (%s) is open" % (icon, name, key))


def carry(s, key):
    """The stream's icon changed: its sessions that still show the old one get the new one."""
    for sid in s["sessions"]:
        mine = session_stream(sid)
        if mine and mine["key"] == key and mine["icon"] and gt.marker_content(sid) != gt.DONE:
            set_session(sid, key, s["icon"])


def cmd_rename(args, ledger):
    if not args.name and not args.icon:
        raise SystemExit("pass --name, --icon or both")
    with editing(ledger) as streams:
        s = stream(streams, args.key)
        was = s["name"]
        if args.name:
            s["name"] = clean_name(args.name)
        if args.icon:
            s["icon"] = pick(ledger, args.icon, args.key)
            carry(s, args.key)
    if s["name"] != was:
        rename_row(ledger, was, s["name"])
    print("%s %s (%s)" % (s["icon"], s["name"], args.key))


def rename_row(ledger, was, name):
    """Rename the stream in the ledger's table, so the refresh finds its row."""
    lines = open(ledger, encoding="utf-8", errors="replace").read().splitlines(True)
    inside, before = False, list(lines)
    for n, line in enumerate(lines):
        if line.startswith("## "):
            inside = line.startswith(SECTION)
        elif inside and line.lstrip().startswith("|"):
            cells = table_cells(line)
            if was.lower() in [c.lower() for c in cells[:2]]:
                cells = [name if n < 2 and c.lower() == was.lower() else c for n, c in enumerate(cells)]
                lines[n] = "| %s |\n" % " | ".join(cells)
    if lines != before:
        gt.write_ledger(ledger, lines)


def cmd_end(args, ledger):
    with editing(ledger) as streams:
        s = stream(streams, args.key)
        if s["state"] == "ended":
            raise SystemExit("stream %s ended on %s" % (args.key, s.get("ended")))
        s.update(state="ended", ended=time.strftime(DAY))
    print("%s %s (%s) ended; its sessions keep the icon, and no new stream gets it for %d days"
          % (s["icon"], s["name"], args.key, FREE_AFTER_DAYS))


def cmd_list(args, ledger):
    streams = read(ledger)
    for key, s in open_streams(streams):
        print("%s %s (%s), since %s: %s" % (s["icon"], s["name"], key, s.get("since"),
                                            ", ".join(i[:8] for i in s["sessions"]) or "no sessions"))
    if args.all:
        for key, s in sorted(streams.items()):
            if s["state"] != "open":
                print("%s %s (%s), ended %s" % (s["icon"], s["name"], key, s.get("ended")))
    if not open_streams(streams):
        print("no open streams; `stream add <key> \"<name>\"` makes one")
        return
    on = {i[:6].lower() for s in streams.values() for i in s["sessions"]}
    off = [c for rid, (level, c) in gt.session_levels(ledger).items() if level in ("MANAGED", "WATCHED") and rid not in on]
    if off:
        print("on no stream: " + "; ".join(off))
    for key, s in quiet(streams):
        print("no activity for %d days: %s %s" % (QUIET_DAYS, s["icon"], key))


def cmd_suggest(args, ledger):
    print(" ".join(suggest(ledger)[:args.n]) or "no free icon left: use a two-letter tag, such as [TW]")


def cmd_assign(args, ledger):
    for given in args.session:
        print(assign(ledger, args.key, gt.resolve_session(given), args.active_ok))


def cmd_strip(args, ledger):
    if bool(args.session) == args.all:
        raise SystemExit("name the sessions to strip, or pass --all")
    ids = [os.path.basename(p) for p in glob.glob(session_path("*")) if re.match(r"[0-9a-f-]{36}$", os.path.basename(p))]
    done = 0
    for sid in sorted(ids) if args.all else [gt.resolve_session(g) for g in args.session]:
        mine = session_stream(sid)
        if not mine:
            print("%s is on no stream" % sid[:8])
            continue
        set_session(sid, mine["key"], "")
        gt.retitle_stopped_job(sid, gt.marker_content(sid))
        done += 1
    print("%d session(s) stripped: a running one's title changes on its next prompt. `stream assign` puts it back" % done)


def cmd_table(args, ledger):
    print("%d line(s) of %s's Streams table changed" % (refresh_table(ledger, args.end_unlisted), ledger))


def cmd_stream(args):
    ledger = os.path.expanduser(args.ledger or gt.require_ledger())
    {"add": cmd_add, "rename": cmd_rename, "end": cmd_end, "list": cmd_list, "suggest": cmd_suggest,
     "assign": cmd_assign, "strip": cmd_strip, "table": cmd_table}[args.stream_cmd](args, ledger)
    if args.stream_cmd in ("add", "rename", "end"):
        refresh_table(ledger)
    return 0


def add_parser(sub):
    top = sub.add_parser("stream", help="streams (projects) and their icons")
    cmds = top.add_subparsers(dest="stream_cmd", required=True)

    def one(name, text):
        p = cmds.add_parser(name, help=text)
        p.add_argument("--ledger", help="any ledger (default: this guide's)")
        return p
    p = one("add", "a new stream, or reopen an ended one")
    p.add_argument("key")
    p.add_argument("name", nargs="?")
    p.add_argument("--icon", help="one wide emoji, or a tag such as [TW] (default: the next free icon)")
    p = one("rename", "another name or icon")
    p.add_argument("key")
    p.add_argument("--name")
    p.add_argument("--icon")
    one("end", "finished; its icon is free again after %d days" % FREE_AFTER_DAYS).add_argument("key")
    one("list", "the open streams, and the managed sessions on none").add_argument("--all", action="store_true")
    one("suggest", "free icons").add_argument("n", nargs="?", type=int, default=8)
    p = one("assign", "sessions that work on it")
    p.add_argument("key")
    p.add_argument("session", nargs="+")
    p.add_argument("--active-ok", action="store_true", help="the user said yes to an icon on a session of their own")
    p = one("strip", "take the icon off titles")
    p.add_argument("session", nargs="*")
    p.add_argument("--all", action="store_true")
    p = one("table", "refresh the ledger's Streams table")
    p.add_argument("--end-unlisted", action="store_true", help="mark the rows of no registered stream ended")
