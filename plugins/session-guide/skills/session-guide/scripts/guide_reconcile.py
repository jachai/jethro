#!/usr/bin/env python3
"""guide_reconcile: the ledger's open Sessions rows against the real state of their sessions.

    python3 guide_reconcile.py --ledger <ledger.md> [--grace-minutes 3]   what needs the guide now; never writes
    (the same as `guide_title.py reconcile`)

The ledger says MANAGED; the session may have ended minutes ago. Nothing but the guide's memory used to join the two,
so a worker that handed off, got blocked or finished could sit unseen until the user asked. reconcile() joins them
on every guide prompt (the title hook), in `settle`, `mark` and `retire`, and returns one flag per row that needs the
guide:

    handoff      a MANAGED or WATCHED row whose job ended with a result line that says HANDED OFF, and no Sessions row
                 is its successor ("successor of [id6]" in any cell, or the same title with the next "(n)"): start the
                 successor now, from the resume prompt or state file its final text names.
    successor    a handoff whose worker already started its own successor (`launch --successor-of` run by the worker
                 leaves <ledger dir>/successors/<new id8>.json) and no Sessions row names the new session yet: record
                 the row and set this one to HANDED OFF; do not start another.
    blocked      its result says blocked / needs / waiting (or the job is blocked on input), and the Waiting table has
                 no row for it: answer it, or ask the user.
    ended        a MANAGED row whose job ended any other way: record the result and close it.
    undelivered  one of the above on a MANAGED row whose last report never reached the guide: no SendMessage since its
                 last prompt (and no earlier one with the same report word), a SendMessage to something that is not a
                 `uds:` socket (a session title fails), or one whose tool result says it failed.
    inbox        <ledger dir>/inbox/<id8>.md: a report a worker wrote there because its SendMessage failed. It stays
                 listed until the guide deletes the file.

A row is classified by its job's result line (state.json output.result, else its detail), never by a loose
"handoff" in free text: "handed off to the guide" passes a deliverable on and is no handoff. A job counts as running
while its state is `working` and a process holds the session; a job that ended less than the grace ago
(SESSION_GUIDE_GRACE_MINUTES, default 3) is left alone, since the guide may be reading its report right now. A flag
has no memory: it comes back on every prompt until the row changes (a successor row, a Waiting row, DONE or HANDED
OFF in Level, the inbox file gone).

It is cheap enough for every prompt: per open row it reads the job folder ($CLAUDE_CONFIG_DIR/jobs/<id8>/state.json
and the tail of timeline.jsonl) and the live process list ($CLAUDE_CONFIG_DIR/sessions/*.json); only a flagged
MANAGED row costs a transcript read, its last 300 KB. Rows with no job folder (interactive or old sessions) are left
to `settle`. job_facts(<id>) gives the same facts for one session. Python 3 stdlib only.
"""
import argparse
import calendar
import datetime
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guide_title as gt  # noqa: E402

GRACE_MINUTES = 3  # a job that ended this recently is left alone (SESSION_GUIDE_GRACE_MINUTES)
TRANSCRIPT_TAIL = 300 * 1024  # how much of an ended worker's transcript is read for its last SendMessage
TIMELINE_TAIL = 64 * 1024
OPEN_LEVELS = ("MANAGED", "WATCHED")
ICON_TAG = r"\[[A-Z0-9]{2}\]"  # a stream's tag when it has no icon
# A result line's first token, past markdown, a stream's icon and a "result:" label.
FIRST = r"^[\W_]*(?:%s[\W_]*)?(?:result:[\W_]*)?(?:%s[\W_]*)?" % (ICON_TAG, ICON_TAG)
# The protocol word, upper case anywhere in the result line, or any case as its first token.
HANDED = re.compile(r"\bHAND(?:ED|ING)[ -]?OFF\b")
HANDED_FIRST = re.compile(FIRST + r"HAND(?:ED|ING)[ -]?OFF\b")
HANDED_LEAD = re.compile(FIRST + r"hand(?:ed|ing)[ -]?off\b", re.I)
# "... handed off to the guide" passes a deliverable on, unless the line also names a resume prompt.
HANDED_TO = re.compile(r"hand(?:ed|ing)[ -]?off\s+(?:\S+\s+){0,3}?to\s+(?:the\s+)?(?:guide|user|you)\b", re.I)
RESUME = re.compile(r"(?:~|/)[\w.@+-]*(?:/[\w.@+-]+)*/[\w.@+-]*(?:resume|prompt|handoff)[\w.@+-]*"
                    r"|\bresume\b\W{0,3}(?:prompt\W{0,3})?(?:at|in|from)?\W{0,3}(?:~|/)\S+", re.I)
# Blocked: the job is blocked on input, or the result's first token is the upper-case protocol word. Loose words
# ("DONE: nothing needs you", "waiting for CI was slow") are not a block.
BLOCKED_FIRST = re.compile(FIRST + r"(?:BLOCKED|NEEDS|WAITING)\b")
SUCCESSOR = re.compile(r"successor (?:of|to)\b[^\[\]|]{0,60}\[([0-9a-fA-F]{6,36})\]", re.I)
REPORT_WORD = re.compile(r"\b(HAND(?:ED|ING)[ -]?OFF|BLOCKED|MERGE READY|DONE|READY|NEEDS?|WAITING)\b")
PATH = re.compile(r"(?:~|/)[\w.@+-]*(?:/[\w.@+-]+)+\.(?:md|txt)\b")


def default_grace():
    try:
        return float(os.environ.get("SESSION_GUIDE_GRACE_MINUTES", GRACE_MINUTES))
    except ValueError:
        return GRACE_MINUTES


def epoch(text):
    """Epoch of an ISO time as the job files write it (2026-11-19T15:59:55.617Z, UTC), or None."""
    try:
        return calendar.timegm(time.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return None


def tail_lines(path, size):
    """The whole lines in the last `size` bytes of a file; [] when it can't be read."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            f.seek(max(0, end - size))
            lines = f.read().splitlines()
    except OSError:
        return []
    return lines[1:] if end > size else lines  # the first one is cut off


def job_folder(session_id):
    """(folder, state) of the job whose session id starts with `session_id` (an id6, an id8 or a full id); the newest
    when an id6 matches more than one. None when there is no job, which is every interactive session."""
    want, found = session_id.strip().lower(), []
    for folder in glob.glob(os.path.join(gt.config_dir(), "jobs", want[:8] + "*")):
        try:
            with open(os.path.join(folder, "state.json")) as f:
                state = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(state, dict) and str(state.get("sessionId") or os.path.basename(folder)).lower().startswith(want):
            found.append((epoch(state.get("updatedAt")) or 0, folder, state))
    if not found:
        return None
    _, folder, state = max(found, key=lambda f: f[0])
    return folder, state


def job_facts(session_id):
    """What a session's job says right now, or None when it has no job folder:
    {state, result, detail, ended_at, alive, session_id, text, transcript}.

    state is the job's state (working, done, blocked, stopped, failed, ...); result its last result line (output.result,
    "" when there is none); detail its one-line status; text the final text of its last timeline entry that has one;
    alive whether a process holds the session. ended_at (an aware UTC datetime) is when its last run of non-working
    states began, or the last sign of life of a `working` job whose process is gone; None while it runs."""
    found = job_folder(session_id)
    if found is None:
        return None
    folder, state = found
    sid = str(state.get("sessionId") or os.path.basename(folder))
    timeline = []
    for raw in tail_lines(os.path.join(folder, "timeline.jsonl"), TIMELINE_TAIL):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if isinstance(entry, dict):
            timeline.append(entry)
    now_state = str(state.get("state") or "")
    alive = gt.session_alive(sid)
    ended = None
    if now_state != "working":
        for entry in reversed(timeline):
            if entry.get("state") == "working":
                break
            ended = epoch(entry.get("at")) or ended
        ended = ended or epoch(state.get("updatedAt")) or epoch(state.get("firstTerminalAt"))
    elif not alive:
        ended = epoch(state.get("updatedAt")) or (epoch(timeline[-1].get("at")) if timeline else None)
    text = next((str(e.get("text")) for e in reversed(timeline) if e.get("text")), "")
    return dict(state=now_state, result=str((state.get("output") or {}).get("result") or "").strip(),
                detail=str(state.get("detail") or "").strip(), alive=alive, session_id=sid, text=text,
                ended_at=datetime.datetime.fromtimestamp(ended, datetime.timezone.utc) if ended else None,
                transcript=str(state.get("linkScanPath") or ""))


def is_handoff(result):
    """True when a result line says the session HANDED OFF its work, so a successor is owed: the upper-case word as
    its first token always; otherwise the word (upper case anywhere, any case first) unless it passes something on
    "to the guide / user / you" and names no resume prompt."""
    if HANDED_FIRST.match(result):
        return True
    if HANDED_TO.search(result):
        return bool(RESUME.search(result))  # a pass-on, unless it names where the successor resumes
    return bool(HANDED.search(result) or HANDED_LEAD.match(result)
                or (re.search(r"hand(?:ed|ing)[ -]?off", result, re.I) and RESUME.search(result)))


def is_blocked(result, state=""):
    return state == "blocked" or bool(BLOCKED_FIRST.match(result))


def session_rows(ledger):
    """[{id, name, level, cells, text}] for every row of the ledger's ## Sessions table that names a session."""
    rows, inside = [], False
    for line in open(ledger, errors="replace"):
        if line.startswith("## "):
            inside = line.strip() == "## Sessions"
        elif inside and line.lstrip().startswith("|"):
            cells = gt.split_row(line)
            rid = own_id(cells[0]) if len(cells) > 1 else None
            if rid:
                rows.append(dict(id=rid, name=row_name(cells[0]), level=re.match(r"[A-Za-z]*", cells[1]).group(),
                                 cells=cells, text=line))
    return rows


def own_id(cell):
    """A Sessions row's own id6: the first [id] in its first cell that is not a "successor of [x]" reference. ("'build
    2' [bbbbbb] successor of [aaaaaa]" is bbbbbb, the successor of aaaaaa.)"""
    ids = re.findall(r"\[([0-9a-fA-F]{6,36})\]", SUCCESSOR.sub("", cell))
    return ids[0][:6].lower() if ids else None


def row_name(cell):
    """A Sessions row's title, without its [id], quotes, level prefixes and the stream icon outside the quotes, lower
    case and single spaced."""
    name = SUCCESSOR.sub("", cell)
    name = re.sub(r"\s*\[[0-9a-fA-F]{6,36}\].*", "", name)
    name = re.sub(r"^(?:%s\s*)?" % ICON_TAG, "", name)
    tagged = r"%s\s*(?:[^\w('\[]+)?(?:%s\s*)?" % (gt.GUIDED_TAG.pattern, ICON_TAG)
    name = re.sub(r"^(?:[^\w(']+)?(?:%s)?" % tagged, "", name).strip("'\" ")
    return " ".join(name.lower().split())


def next_name(name):
    """The title a relay's successor gets: "x" -> "x (2)", "x (2)" -> "x (3)"."""
    found = re.match(r"^(.*?)\s*\((\d+)\)$", name)
    return "%s (%d)" % (found.group(1), int(found.group(2)) + 1) if found else name + " (2)"


def successor(row, rows):
    """The Sessions row that continues `row`'s work, or None."""
    want = next_name(row["name"]) if row["name"] else None
    for other in rows:
        if other["id"] == row["id"]:
            continue
        if any(ref[:6].lower() == row["id"] for ref in SUCCESSOR.findall(other["text"])):
            return other
        if want and other["name"] == want:
            return other
    return None


def successor_note(ledger, rid):
    """The note `launch --successor-of` left in <ledger dir>/successors/ for a session whose id starts with `rid`, or
    None."""
    for path in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(ledger)), "successors", "*.json"))):
        try:
            with open(path) as f:
                note = json.load(f)
            if str(note["of"]).lower().startswith(rid) and note.get("id"):
                return note
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return None


def resume_paths(text):
    """Up to 2 files a final message names, resume prompts and state files first."""
    found = []
    for path in PATH.findall(text or ""):
        if path not in found:
            found.append(path)
    found.sort(key=lambda p: not re.search(r"resume|prompt|handoff|state", os.path.basename(p), re.I))
    return found[:2]


def send_ok(block, line):
    """False when a SendMessage tool result says it failed, else True."""
    if block.get("is_error"):
        return False
    result = line.get("toolUseResult")
    if isinstance(result, dict) and "success" in result:
        return bool(result["success"])
    return not re.search(r"success\W{0,6}false", json.dumps(block.get("content")), re.I)


def undelivered(facts, result):
    """Why this ended session's last report never reached the guide, or None when it did, or when the transcript can't
    tell. Reads the last TRANSCRIPT_TAIL bytes only. Any successful send to a uds: socket after the last prompt (a new
    turn) counts as delivered; when that prompt is not inside the bytes read, nothing is flagged."""
    path = facts.get("transcript")
    if not path or not os.path.isfile(path):
        hits = glob.glob(os.path.join(gt.config_dir(), "projects", "*", facts["session_id"] + ".jsonl"))
        path = max(hits, key=os.path.getmtime) if hits else None
    if not path:
        return None
    try:
        cut = os.path.getsize(path) > TRANSCRIPT_TAIL
    except OSError:
        return None
    prompt, sends, results = -1, [], {}
    for n, raw in enumerate(tail_lines(path, TRANSCRIPT_TAIL)):
        if b'"user"' not in raw and b"SendMessage" not in raw:
            continue
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(line, dict) or line.get("isSidechain"):
            continue
        content = (line.get("message") or {}).get("content")
        blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
        if line.get("type") == "user":
            tools = [b for b in blocks if b.get("type") == "tool_result"]
            if not tools and not line.get("isMeta"):
                prompt = n  # a prompt, a message from another session or a task notification: a new turn
            for b in tools:
                results[b.get("tool_use_id")] = send_ok(b, line)
        elif line.get("type") == "assistant":
            sends += [(n, b.get("id"), b.get("input") or {}) for b in blocks
                      if b.get("type") == "tool_use" and b.get("name") == "SendMessage"]

    def reached(send):
        return str(send[2].get("to") or "").startswith("uds:") and results.get(send[1]) is True

    after = [s for s in sends if s[0] > prompt]
    if any(reached(s) for s in after):
        return None
    if prompt < 0 and cut:
        return None  # its last prompt is older than the tail read: no evidence either way
    last = after[-1] if after else None
    if last is None:
        word = REPORT_WORD.search(result)
        earlier = sends[-1] if sends else None
        if earlier and word and reached(earlier) and word.group(1).upper() in json.dumps(earlier[2]).upper():
            return None  # the same report went out earlier; this turn only repeated it
        return "no SendMessage since its last prompt"
    to = str(last[2].get("to") or "")
    if not to.startswith("uds:"):
        return "its last SendMessage went to %r, which is not a uds: socket" % to[:60]
    if results.get(last[1]) is not True:
        return "its last SendMessage, to %s, failed" % to
    return None


def inbox_flags(ledger, rows):
    """A flag for every report a worker left in <ledger dir>/inbox/<id8>.md, with its first lines."""
    flags, names = [], {r["id"]: r for r in rows}
    for path in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(ledger)), "inbox", "*.md"))):
        id8 = os.path.basename(path)[:-3]
        try:
            with open(path, errors="replace") as f:
                lines = [" ".join(l.split()) for l in f.read(4096).splitlines() if l.strip()]
        except OSError:
            continue
        row = names.get(id8[:6].lower())
        flags.append(dict(kind="inbox", id=id8[:6].lower(), id8=id8, name=row["name"] if row else "",
                          session=row["cells"][0] if row else "[%s]" % id8, level=row["level"] if row else "",
                          result=" / ".join(lines[:3])[:300], state="", ago=None, prompts=[], why=path))
    return flags


def reconcile(ledger, now=None, grace_minutes=None, me=""):
    """[flag]: the ledger's MANAGED and WATCHED rows whose job is not running and that need the guide, then the inbox.

    A flag is {kind, id, id8, name, session, level, result, state, ago, prompts, why}; kind is handoff, blocked, ended,
    undelivered or inbox (see the module docstring). `now` is an epoch or a datetime (default: now); grace_minutes
    defaults to SESSION_GUIDE_GRACE_MINUTES or 3; `me` is the calling guide's session id, whose own row is skipped.
    Reads only: never writes a file."""
    if isinstance(now, datetime.datetime):
        now = now.timestamp()
    now = time.time() if now is None else now
    grace = (default_grace() if grace_minutes is None else grace_minutes) * 60
    rows = session_rows(ledger)
    waiting, closed, flags, seen = gt.waiting_rows(ledger), gt.closed_ids(), [], set()
    for row in rows:
        rid = row["id"]
        if rid in seen:
            continue
        seen.add(rid)  # a session on several rows takes its topmost row
        if row["level"] not in OPEN_LEVELS or rid in closed or (me and rid == me[:6].lower()):
            continue
        facts = job_facts(rid)
        if facts is None or (facts["state"] == "working" and facts["alive"]):
            continue
        content = gt.marker_content(facts["session_id"])
        if content is not None and content not in gt.WORKER_MARKERS:  # a guide: guides settle by handing over
            continue
        ended = facts["ended_at"].timestamp() if facts["ended_at"] else now
        if now - ended < grace:
            continue
        said = facts["result"] or facts["detail"]
        if is_handoff(said):
            if successor(row, rows):
                continue
            kind = "handoff"
            started = successor_note(ledger, rid)
            if started:
                if any(other["id"] == str(started["id"])[:6].lower() for other in rows):
                    continue  # its successor has a row
                kind = "successor"
        elif is_blocked(said, facts["state"]):
            if rid in waiting:
                continue
            kind = "blocked"
        elif row["level"] == "MANAGED":
            if rid in waiting:  # it waits on the user: `settle` asks, and `done` would drop that reminder
                continue
            kind = "ended"
        else:
            continue
        flag = dict(kind=kind, id=rid, id8=facts["session_id"][:8], name=row["name"], session=row["cells"][0],
                    level=row["level"], result=" ".join(said.split()), ago=max(0, now - ended),
                    state=facts["state"] if facts["alive"] or facts["state"] != "working" else "working, no process",
                    prompts=resume_paths(facts["text"]) if kind == "handoff" else [], why="")
        if kind == "successor":
            flag["started"] = started
        flags.append(flag)
        why = undelivered(facts, said) if row["level"] == "MANAGED" else None
        if why:
            flags.append(dict(flag, kind="undelivered", why=why, prompts=[]))
    return flags + inbox_flags(ledger, rows)


def describe(flag, script="guide_title.py"):
    """One line for a flag: what the row says, what the job says, and the one thing to do now."""
    who = "%s [%s]" % ("'%s'" % flag["name"] if flag["name"] else "session", flag["id8"])
    ago = " %d min ago" % (flag["ago"] // 60) if flag["ago"] is not None else ""
    result = ' Result: "%s"' % flag["result"][:220] if flag["result"] else ""
    if flag["kind"] == "handoff":
        start = (" from %s" % " or ".join(flag["prompts"]) if flag["prompts"]
                 else " (its final text has the resume prompt)")
        return ("HANDED OFF: %s ended%s and no Sessions row is its successor. Start the successor now%s; give it a row "
                "saying \"successor of [%s]\" and set this row's Level to HANDED OFF.%s"
                % (who, ago, start, flag["id"], result))
    if flag["kind"] == "successor":
        new = flag["started"]
        return ("SUCCESSOR STARTED: %s handed off and started its own successor '%s' [%s] (%s/%s). Record only: "
                "give it a Sessions row saying \"successor of [%s]\", Level MANAGED, and set this row's Level to "
                "HANDED OFF. Do not start another."
                % (who, new.get("name") or "", str(new["id"])[:8], new.get("model") or "default",
                                           new.get("effort") or "default", flag["id"]))
    if flag["kind"] == "blocked":
        return ("BLOCKED: %s ended%s waiting on something, and the Waiting table has no row for it. Answer it, or ask "
                "the user and record it (`%s waiting %s \"<exact action>\"`).%s"
                % (who, ago, script, flag["id8"], result))
    if flag["kind"] == "ended":
        return ("ENDED: %s ended%s (job %s) while its row still says MANAGED. Record the result and close it (`%s done "
                "%s`), or send it the next step.%s" % (who, ago, flag["state"], script, flag["id8"], result))
    if flag["kind"] == "undelivered":
        return ("UNDELIVERED: %s: its last report never reached you (%s). Read it (peek %s).%s"
                % (who, flag["why"], flag["id8"], result))
    return ("INBOX: %s left a report it could not send, %s: \"%s\". Act on it, then delete the file."
            % (who, flag["why"], flag["result"]))


def main(argv=None):
    p = argparse.ArgumentParser(description="The ledger's open Sessions rows against their sessions' real state.")
    p.add_argument("cmd", nargs="?", choices=["reconcile"], help=argparse.SUPPRESS)
    p.add_argument("--ledger", required=True, help="the guide ledger to read (it is never written)")
    p.add_argument("--grace-minutes", type=float, default=None,
                   help="leave jobs that ended this recently alone (default SESSION_GUIDE_GRACE_MINUTES or 3)")
    args = p.parse_args(argv)
    return print_flags(os.path.expanduser(args.ledger), args.grace_minutes)


def print_flags(ledger, grace=None, me=""):
    if not os.path.isfile(ledger):
        raise SystemExit("no ledger at %s" % ledger)
    flags = reconcile(ledger, grace_minutes=grace, me=me)
    for flag in flags:
        print(describe(flag))
    print("%d to reconcile" % len(flags) if flags else "Nothing to reconcile: every open row matches its session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
