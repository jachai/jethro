#!/usr/bin/env python3
"""guide_audit: the guide's look back over its whole body of work: what was decided, did it land, was it verified.

    python3 guide_audit.py audit [<ledger>] [--days 5] [--quick] [--limit 10] [--all] [--group <key>] [--queue <file.md>]...
    python3 guide_audit.py audit [<ledger>] --open-batch   the rows still open, grouped, for one keep / start / drop question
    python3 guide_audit.py set <key>[,<key>...] <asked | started | parked | done | dropped> ["<evidence>"] [--session <id>] [--hours N] [--note "…"]
    python3 guide_audit.py strike --from <verdicts file> [--ledger <ledger>]   apply a strike sweep's verdicts
    python3 guide_audit.py state [<ledger>]        print the live-state file (STATE.md), refreshed first

audit reads the ledger's tables (never its log) and, unless --quick, the transcripts of the ledger's sessions from the
last --days, and prints the 10 rows most worth the guide's attention among the work that is NOT done or NOT verified,
each with one next action:

- idle      an Open items row, or a row of a queue file, that is still open with no live worker and no question to
            the user. A queue file is any markdown table of approved work (a fix queue): name it on a `Queues:` line
            in the ledger's first lines (comma-separated paths), in SESSION_GUIDE_QUEUES, or with --queue.
- person    an Open items row whose Owner cell names a person (or says ASK), not a session, a guide or a worker, with
            no reminder in the Waiting table: it waits on someone nobody is asking.
- quiet     the same as idle, but its worker (the `[id6]` in its Owner cell, a `set <key> started` session, or a live
            Sessions row naming the same ticket or PR) has gone quiet for 2 h or is closed.
- unverified  what `guide_title.py followups` lists (landed, no Verifications row; "not-exercised" past its re-check),
            plus Verifications rows left proposed, broken, or running for over a day.
- waiting   a reminder asked over a day ago that is still open: the gate may never open by itself.
- decision  a decision of the last 3 days that nothing else in the ledger refers to (no Sessions row, Open item,
            reminder or later note names "D<N>" / "Decision <N>"), unless its words say it was an answer, not work.
- session   (full audit only; a quick one repeats the last full audit's) a session of the last --days that ended
            with no `result:` line, with a result that says it isn't finished (blocked, waiting, draft, needs …), or
            naming a PR the ledger never says was merged. Of a relay ('build', 'build 2', 'build (3)') only the last
            session counts.
- backlog   Open items rows with no date, or older than twice --days: one row, for one bulk question to the user.
- check     an idle, quiet, person or asked row, or a reminder in the Waiting table, that later ledger rows show as
            likely done: before anything is put to the user, `covered()` takes the row's ids (tickets and monitor ids
            "ABC-123", PRs "#123", 22-character artifact ids) and looks for LATER evidence: a satisfied Results row
            naming the id, or naming a session whose Title / Role cell or brief file (a .md path in the Role cell, else
            <ledger dir>/*/<session title as a slug>/brief.md) names it; a DONE Sessions row that names it; a Decision
            naming it with a closing word; a verified Verifications row; another open reminder with the same id (the
            same ask twice); for a PR, gh saying merged (guide_gh.py, cached, fails open). A check row leaves the ask
            list and the hook's counts; its next action is "likely done: <evidence>. Confirm, then `set <key> done
            "<evidence>"`". It never strikes a row by itself. A row that stays on the ask list says "checked <date>:
            still open because <no later evidence | no id to match>".

Tags. A row (Open items, or a reminder) may say `closes: pr:#N`, `result:<artifact id>`, `ticket:<ID>` or
`session:<id8>` (several: all of them). When that has happened (gh says the PR merged; a satisfied Results row names
the id; a satisfied Results row or a closing Decision names the ticket; the session's Sessions row is DONE), the
audit closes the row itself (an Open items row's Status says DONE, a reminder leaves the Waiting table) and the next
hook line says so. `shared_ids(ledger, text)` lists the open rows that share an id with `text`.

Strike sweep. The full audit also writes strike-candidates.md next to the ledger: the check rows and the rows idle
over 3 days not checked in the last week. When the last sweep is over a day old the hook asks the guide for ONE
read-only helper, 'strike sweep', that returns `<key> | DONE / SUPERSEDED / OPEN | <evidence>` lines; `strike --from
<file>` marks the DONE and SUPERSEDED rows ("DONE <date>: <evidence>" in the row), stamps the OPEN ones "checked
<date>", writes one Log line and prints one line for the user. `audit --open-batch` then lists what is really open,
grouped by stream, for one keep / start / drop question per group.

Clock. Ledger lines whose first date is after now (past the Waiting, Results and Verifications tables, whose times
are the scripts') are flagged: the guide's own written times drift ahead of the wall clock.

Ranking. Each row scores value x age. Value: 6 for a broken verification or a reminder open over a day, 3 for idle or
quiet approved work, 2 for work waiting on a person, an unverified landing or an unfinished session, 1 for a re-check,
an untraced decision, a session with no result line or the backlog; half again when the row's words name prod, an
outage, a customer, money or a gate, half when they call it a glance, an idea or cosmetic. Age is in days, capped at 7.

Collapsing. Rows that share one next action print as one row, its key ending "+N": the rows of one queue file, the
items of one owner ("new session"), the items waiting on one person, the items whose worker is gone, the landed PRs
with no verification, the re-checks that are due, the untraced decisions, the sessions with no result line, the
backlog. `--group <key>` lists what is inside one; `--limit N` prints more rows; `--all` prints every item, not
collapsed, with the ones counted but not listed: moving (a live worker), asked (a pending question, or
`set <key> asked`) and parked (`set <key> parked`, or the row's own words: "later", "not now", "at cutover").

set records what the guide did about a row, so the next audit doesn't list it again: `started --session <id>` (it is
moving while that session is), `asked` (for 12 h, or --hours), `parked` (for --hours, or until un-set), `done` and
`dropped`. A key is the table's first column, several of them comma-separated, a collapsed key ("3fa9c1+5": every
item in that row), or a ticket / PR when only one item names it. It works on every kind of row.

Every run writes two files next to the ledger: STATE.md, a few KB of live state (guide, open sessions, reminders,
results with no verdict, the top 20 rows), which a takeover reads instead of the ledger's log; and audit.json, the
`set` marks and the counts the title hook shows ({idle} and {oldest}). The hook refreshes the quick audit on a guide's
prompt (at most every 10 minutes), nags with the top rows when an idle item is older than SESSION_GUIDE_IDLE_HOURS
(default 12) with no question to the user, and says when the full audit is due (SESSION_GUIDE_AUDIT_HOURS, default 12;
0 turns both off). `guide_title.py mark` (a takeover) runs the full audit; `retire` and `settle` refresh the quick one.

Python 3 stdlib only.
"""
import argparse
import calendar
import glob
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guide_title as gt  # noqa: E402

__version__ = "0.1.20"
IDLE_HOURS = 12  # an idle item older than this with no question to the user is nagged about
AUDIT_HOURS = 12  # the full audit (transcripts too) is due this often
QUICK_MINUTES = 10  # the hook recomputes the quick audit at most this often
ASKED_HOURS = 12  # `set <key> asked` holds this long, then the item is idle again
QUIET_HOURS = 2  # a worker quiet this long isn't moving its item
DAYS = 5  # how far back the full audit reads transcripts
DECISION_DAYS = 3
WAITING_HOURS = 24
TOP = 10  # rows the audit prints; the rest are counted
AGE_CAP = 7  # days: older than this ranks no higher
# What a row is worth, by what it is. Its rank is this value x its age in days (capped), half again when its words
# name prod, an outage, a customer, money or a gate, and half when they call it a glance, an idea or cosmetic.
VALUE = {"broken": 6, "waiting": 6, "idle": 3, "quiet": 3, "person": 2, "unverified": 2, "unfinished": 2, "check": 2,
         "recheck": 1, "proposed": 1, "decision": 1, "noresult": 1, "backlog": 1}
ASK_STATES = ("idle", "quiet", "person", "asked")  # what `covered()` checks before the row is put to anyone
SWEEP_HOURS = 24  # the hook asks for a strike sweep when the last one is older than this
STRIKE_DAYS = 3  # a row idle this long is a strike candidate
CHECKED_DAYS = 7  # a row a sweep found still open isn't a candidate again for this long
GH_LOOKUPS = 8  # PRs one audit may ask gh about (each is cached 10 minutes)
FUTURE_SLACK = 15 * 60  # a written time this far past now is a clock error
# The ids a row is matched on: tickets and monitor ids ("ABC-123", "P-401"), PRs ("#5835"), artifact ids (22 letters and
# digits, with an upper-case letter, a lower-case one and a digit).
WORK_ID = re.compile(r"(?<![\w-])[A-Z][A-Z0-9]{0,9}-\d{2,6}(?![\w-])|(?<![\w&])#\d{2,6}(?![\w-])")
REPO_PR = re.compile(r"(?:(?<![\w./~@:-])[A-Za-z0-9][\w.-]*/[\w.-]*[A-Za-z0-9_]#|github\.com/[\w.-]+/[\w.-]+/pull/)"
                     r"(\d{2,6})(?![\w-])")
ARTIFACT = re.compile(r"(?<![\w-])[A-Za-z0-9]{22}(?![\w-])")
CLOSING = re.compile(r"\b(?:done|closed?|merged|dropped|superseded|shipped|satisfied|already|moot|resolved|answered)\b",
                     re.I)
CLOSES = re.compile(r"\bcloses:?\s+((?:pr|result|ticket|session):.*)", re.I)
TAG = re.compile(r"\b(pr|result|ticket|session):\s*([^\s,;|)]+)", re.I)
CHECKED = re.compile(r"\s*(?:·\s*)?\bchecked ((?:20\d\d-)?\d\d-\d\d)\b")  # a sweep's stamp in a row still open
VERDICT = re.compile(r"^[\s|*-]*([0-9a-fA-F]{6}|D\d{1,5}|[A-Z][A-Z0-9]{0,9}-\d{1,6}|#\d{1,6})\s*\|\s*"
                     r"(DONE|SUPERSEDED|OPEN)\b\W*\|?\s*(.*?)[\s|]*$", re.I)
STAMP = re.compile(r"(?<![\d-])(?:(20\d\d)-)?(0[1-9]|1[0-2])-([0-2]\d|3[01])(?![\d-])(?:[ T]+([01]?\d|2[0-3]):([0-5])([\dx]))?")
LATER_WORDS = re.compile(r"\b(?:until|again|due|remind\w*|by|before|re-?check\w*|next|eta|deadline|at|on|for|till?)\W*$",
                         re.I)  # "sleep until 11-20 09:00" is a plan, not a written time
URGENT = re.compile(r"\b(?:prod|production|outage|customers?|money|blocks?|blocked|gate|security|data loss)\b|\$\d", re.I)
MINOR = re.compile(r"\b(?:glance|nice to have|cosmetic|typo|idea|proposal|maybe|loose ends?|low)\b", re.I)
# An Owner cell that names no session and none of these words names a person: the item waits on them, not on a worker.
WORKER_OWNER = re.compile(r"\b(?:guide|sessions?|workers?|agents?|leads?|waves?|queue|triage|row|nobody|none|tbd)\b"
                          r"|\[[0-9a-f]{6}\]|^[\W\d]*$", re.I)
STATES = ("asked", "started", "parked", "done", "dropped")
TICKET = re.compile(r"(?<![\w-])(?:[A-Z]{1,6}-\d{1,6}|#\d{2,6}|v\d+\.\d+\.\d+)\b")
FINISHED = re.compile(r"^\W*(?:done|dropped|closed|resolved|superseded|moot|fixed|shipped|merged|verified|cancell?ed|n/a)\b",
                      re.I)
STRUCK = re.compile(r"^\W*(?:DONE|DROPPED|CLOSED|RESOLVED|SUPERSEDED|MOOT|SHIPPED|CANCELL?ED)\b")  # in the Item cell itself
PARKED = re.compile(r"\b(?:later|parked|not now|at cutover|at step|backlog|someday)\b", re.I)
ANSWER = re.compile(r"\b(?:done|closed?|closes|dropped|drop|no port|stays?|not now|leave|skip|relayed|keep|let it run|"
                    r"backlog|no plan|declined|superseded|satisfied|as is|accepted)\b", re.I)
# "handed off" is a relay that needs a successor; "handed off to the guide" is a deliverable passed on, a clean end.
NOT_DONE = re.compile(r"\b(?:blocked|waiting|waits|needs?|pending|partial|push ready|publish ready|draft|"
                      r"handed off(?!\s+(?:it\s+|them\s+)?(?:to|for)\s+(?:the\s+)?(?:guide|user|you)\b)|"
                      r"fail(?:ed|ing|s)?|stopped|not (?:done|verified|merged|deployed|pushed|finished|landed))\b", re.I)
DECISION = re.compile(r"^(?:[-*]\s*)?\**(?:Decision\s+)?(\d{1,5})(?:\.|\b)\s*\(([^)]*)\)\s*(?:FINAL)?\s*(?:\*\*)?:?\s*(.*)")
CLOCK = re.compile(r"\s+(\d\d):(\d)[\dx]")


def state_paths(ledger):
    folder = os.path.dirname(os.path.abspath(ledger))
    return os.path.join(folder, "audit.json"), os.path.join(folder, "STATE.md")


def load_state(ledger):
    try:
        with open(state_paths(ledger)[0]) as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, text):
    with open(path + ".tmp", "w", newline="") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def strike_path(ledger):
    return os.path.join(os.path.dirname(os.path.abspath(ledger)), "strike-candidates.md")


def item_key(text):
    return hashlib.sha1(" ".join(text.lower().split()).encode()).hexdigest()[:6]


def tickets(text):
    return set(TICKET.findall(text))


def sections(ledger):
    """{heading start: [table rows as cells]} and the ledger's lines, read once."""
    lines = open(ledger, errors="replace").read().splitlines()
    tables, name = {}, ""
    for line in lines:
        if line.startswith("## "):
            name = line
        elif line.lstrip().startswith("|"):
            cells = gt.split_row(line)
            if cells and not all(set(c) <= set("-: ") for c in cells):
                tables.setdefault(name, []).append(cells)
    return tables, lines


def table(tables, start):
    """The rows of the first section whose heading starts with `start`, its header row left out."""
    rows = next((r for name, r in tables.items() if name.strip() == start), None)
    if rows is None:  # "## Open items (every row has an owner)"; never "## Sessions added at takeover"
        rows = next((r for name, r in tables.items() if name.startswith(start + " (")), [])
    return rows[1:] if rows else []


def queue_paths(lines, extra=()):
    found = list(extra) + [p for p in os.environ.get("SESSION_GUIDE_QUEUES", "").split(os.pathsep) if p]
    for line in lines[:15]:
        if line.startswith("Queues:"):
            found += [p.strip() for p in line[7:].split(",") if p.strip()]
    seen = []
    for path in (os.path.abspath(os.path.expanduser(p)) for p in found):
        if path not in seen:
            seen.append(path)
    return seen


def age_of(text, now):
    """Seconds since the first date in `text` ("11-18 12:4x", "2026-11-18 12:40", or a bare date: noon), or None."""
    at, found = gt.line_date(text, now), gt.DATE.search(text)
    if at is None:
        return None
    clock = CLOCK.match(text, found.end())
    if clock:
        at += (int(clock.group(1)) - 12) * 3600 + int(clock.group(2)) * 600
    return max(0.0, now - at)


def names(text, cells=()):
    """What an item can be matched by: its tickets and PRs, plus a queue row's short id cells ("G2")."""
    return tickets(text) | {c for c in cells if 2 <= len(c) <= 12 and " " not in c and re.search(r"\d", c)}


def named_in(found, text):
    return any(re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(n), text) for n in found)


def open_items(tables, now):
    """Open items rows that are still open: {key, kind, what, owner, age, parked}. A leading date cell is the row's
    date; else the first date in its Status cell, else in the row."""
    found = []
    for cells in table(tables, "## Open items"):
        age = None
        if re.match(r"\s*(?:20\d\d-)?\d\d-\d\d\b", cells[0]) and len(cells) > 2:
            age, cells = age_of(cells[0], now), cells[1:]
        if len(cells) < 2 or cells[0] in ("Item", "") or cells[0].startswith("~~"):
            continue
        owner = cells[1]
        if any(FINISHED.match(c) for c in cells[1:]) or STRUCK.match(cells[0]):
            continue
        stamp = CHECKED.search(" ".join(cells[1:]))  # a sweep's "checked <date>" is not the row's date
        bare = [CHECKED.sub("", c) for c in cells]
        if age is None:
            age = age_of(bare[-1] if len(cells) > 2 else "", now)
        if age is None:
            age = age_of(" ".join(bare), now)
        found.append(dict(key=item_key(cells[0]), kind="open", what=cells[0], owner=owner, age=age,
                          text=" ".join(cells), stamped=gt.line_date(stamp.group(1), now) if stamp else None,
                          names=names(cells[0]), keys=set(re.findall(r"\[([0-9a-f]{6})\]", " ".join(cells[1:]))),
                          parked=bool(PARKED.search(" ".join(bare[1:])))))
    return found


def queue_items(paths, now):
    found = []
    for path in paths:
        try:
            lines = open(path, errors="replace").read().splitlines()
        except OSError:
            continue
        head = True
        for line in lines:
            if not line.lstrip().startswith("|"):
                head = True
                continue
            cells = gt.split_row(line)
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if head:  # the first row of each table is its header
                head = False
                continue
            what = " · ".join(c for c in cells[:3] if c and c != "—")
            if what.startswith("~~") or any(FINISHED.match(c) for c in cells[1:]):
                continue
            found.append(dict(key=item_key(what), kind="queue", what=what, owner=os.path.basename(path), text=" ".join(cells),
                              names=names(" ".join(cells[:2]), cells[:2]), keys=set(),
                              age=age_of(" ".join(reversed(cells)), now), parked=False))
    return found


def transcripts(since=0):
    """{id6: path} of this machine's transcripts changed since `since`, the newest for each id."""
    found = {}
    for path in glob.glob(os.path.join(gt.config_dir(), "projects", "*", "*.jsonl")):
        try:
            at = os.path.getmtime(path)
        except OSError:
            continue
        rid = os.path.basename(path)[:6].lower()
        if at >= since and at > found.get(rid, ("", 0))[1]:
            found[rid] = (path, at)
    return found


def live_sessions(tables, now, paths):
    """{id6: {cell, level, idle, moving, tickets}} for the Sessions rows at MANAGED, WATCHED or ACTIVE, not closed. A
    session on several rows is at its topmost row's Level, as in session_levels: an older MANAGED row of a session
    whose top row says DONE is history, not a live worker."""
    closed, found, topmost = gt.closed_ids(), {}, set()
    for cells in table(tables, "## Sessions"):
        rid = gt.row_id(cells[0]) if len(cells) > 1 else None
        level = re.match(r"[A-Za-z]*", cells[1]).group() if rid else ""
        if not rid or rid in topmost:
            continue
        topmost.add(rid)
        if rid in closed or level not in ("MANAGED", "WATCHED", "ACTIVE"):
            continue
        seen = paths.get(rid)
        idle = now - seen[1] if seen else None
        sid = os.path.basename(seen[0])[:-6] if seen else ""
        working = bool(sid) and gt.job_state(sid) == "working" and gt.session_alive(sid)
        found[rid] = dict(cell=cells[0], level=level, idle=idle, text=" ".join(cells),
                          moving=working or (idle is not None and idle < QUIET_HOURS * 3600))
    return found


def classify(item, marks, live, waiting, now):
    """Set the item's state (idle, quiet, moving, asked, parked, or None when it is finished) and a note on why."""
    mark = marks.get(item["key"]) or {}
    state, refs = mark.get("state"), item["names"]
    if state in ("done", "dropped"):
        return None, ""
    if state == "parked" and (not mark.get("until") or mark["until"] > now):
        return "parked", mark.get("note") or "parked"
    owner = gt.row_id(item["owner"]) if item["kind"] == "open" else None
    worker = (mark.get("session") or "")[:6].lower() if state == "started" else owner
    if not worker:  # a version ("v1.2.0") names a release, not a piece of work: two workers can share one
        work = {n for n in refs if not re.match(r"v\d", n)}
        worker = next((rid for rid, s in live.items() if named_in(work, s["text"])), None)
    if worker:
        seen = live.get(worker)
        if seen and seen["moving"]:
            return "moving", "worker [%s]" % worker
        return "quiet", "worker [%s] %s" % (worker, "quiet %s" % span(seen["idle"]) if seen and seen["idle"] is not None
                                            else "closed or gone")
    if state == "asked" and mark.get("until", 0) > now:
        return "asked", "asked %s" % time.strftime("%m-%d %H:%M", time.localtime(mark.get("at", now)))
    asked = next((r for rid, r in waiting.items() if rid in item["keys"] or named_in(refs, r["what"])), None)
    if asked:
        return "asked", "reminder %s" % asked["remind"]
    if item.get("parked"):
        return "parked", "its row says later"
    if item["kind"] == "open" and (re.match(r"\W*ask\b", item["owner"], re.I) or not WORKER_OWNER.search(item["owner"])):
        return "person", "waits on %s, no reminder" % person(item["owner"])
    return "idle", "owner %s" % (item["owner"][:30] or "none")


def person(owner):
    """The name an Owner cell starts with: "Dana (glance)" and "Dana, after the merge" are both Dana."""
    name = re.split(r"\s*[(\[,;:/+]|\s+(?:after|then|when|tells?|to)\b|\s+\d", owner.strip("' "))[0].strip()[:24]
    return "the user" if name.lower() in ("ask", "user", "the user") else name or "its owner"


def owner_head(owner):
    """What Owner cells share when they mean one worker: "new session (proposed), sonnet" is "new session"."""
    return " ".join(re.split(r"\s*[(\[,;]|:\s", owner.strip("' "))[0].lower().split())[:40] or "nobody"


def span(seconds):
    if seconds is None:
        return "undated"
    return "%.0f h" % (seconds / 3600) if seconds < 36 * 3600 else "%.1f d" % (seconds / 86400)


def work_ids(text):
    """The ids a row can be matched on to later rows: tickets, monitor ids, PRs and artifact ids."""
    found = set(WORK_ID.findall(text)) | {"#" + n for n in REPO_PR.findall(text)}  # owner/name#N and PR links name #N
    return found | {a for a in ARTIFACT.findall(text) if re.search(r"\d", a) and re.search(r"[a-z]", a)
                    and re.search(r"[A-Z]", a)}


def stamps(text, now):
    """[(epoch, has a clock, match)] of every date in `text`: "11-16", "2026-11-16 19:16", "11-19 17:5x" (a bare date
    is noon). A date without a year more than 2 days ahead is last year's, as in guide_title.line_date."""
    out = []
    for found in STAMP.finditer(text):
        year, month, mday, hour, tens, ones = found.groups()
        y = int(year or time.localtime(now).tm_year)
        minute = int(tens) * 10 + (int(ones) if ones and ones != "x" else 0) if hour else 0
        try:
            at = time.mktime((y, int(month), int(mday), int(hour) if hour else 12, minute, 0, 0, 0, -1))
            if not year and at > now + 2 * 86400:
                at = time.mktime((y - 1, int(month), int(mday), int(hour) if hour else 12, minute, 0, 0, 0, -1))
        except (OverflowError, ValueError):
            continue
        out.append((at, bool(hour), found))
    return out


def newest(text, now):
    found = [at for at, _, _ in stamps(text, now)]
    return max(found) if found else None


def iso_time(text):
    """Epoch of gh's "2026-11-15T10:00:00Z", or None."""
    try:
        return calendar.timegm(time.strptime(text[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return None


def slug(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def brief_ids(path, cache):
    if path not in cache:
        try:
            with open(path, errors="replace") as f:
                cache[path] = work_ids(f.read(400000))
        except OSError:
            cache[path] = set()
    return cache[path]


def evidence_index(ledger, tables, lines, now):
    """What later evidence can come from, read once per audit: the DONE / CLOSED Sessions rows (with the ids of their
    Title, Role cell and brief file), the satisfied Results rows, the Decisions, the verified Verifications rows and
    the open reminders."""
    folder, cache = os.path.dirname(os.path.abspath(ledger)), {}
    briefs = {}  # a Sessions row that names no brief: <ledger dir>/*/<its title as a slug>/brief.md
    for path in glob.glob(os.path.join(folder, "*", "brief.md")) + glob.glob(os.path.join(folder, "*", "*", "brief.md")):
        briefs.setdefault(slug(os.path.basename(os.path.dirname(path))), path)
    sessions = []
    for cells in table(tables, "## Sessions"):
        rid = gt.row_id(cells[0]) if len(cells) > 1 else None
        if not rid:
            continue
        text = cells[0] + " " + (cells[2] if len(cells) > 2 else "")
        paths = [os.path.join(folder, os.path.expanduser(p)) for p in re.findall(r"[\w./~-]+\.md\b", text)]
        name = session_name(cells[0])
        paths = paths or ([briefs[slug(name)]] if slug(name) in briefs and len(slug(name)) >= 6 else [])
        named = set()
        for path in paths:
            named |= brief_ids(path, cache)
        sessions.append(dict(id=rid, name=name, level=re.match(r"[A-Za-z]*", cells[1]).group().upper(), ids=work_ids(text),
                             brief=named, briefs=[os.path.basename(os.path.dirname(p)) if os.path.basename(p) == "brief.md"
                                                  else os.path.basename(p) for p in paths],
                             at=newest(" ".join(cells), now)))
    results = []
    for cells in table(tables, "## Results for you"):
        if len(cells) >= 5 and cells[4].lower().startswith("satisfied"):
            results.append(dict(what=cells[0], line=" ".join(cells), ids=work_ids(" ".join(cells)), at=newest(cells[4], now) or newest(
                " ".join(cells[2:4]), now), sids={i[:6].lower() for i in re.findall(r"\[([0-9a-fA-F]{6,36})\]", cells[0])}))
    found, inside = [], False
    for line in lines:
        if line.startswith("## "):
            inside = line.startswith("## Decisions")
            continue
        decision = DECISION.match(line.strip()) if inside and not line.lstrip().startswith(("~~", "- ~~")) else None
        if decision:
            found.append(dict(number=decision.group(1), what=decision.group(3), ids=work_ids(line),
                              closing=bool(CLOSING.search(line)), at=newest(decision.group(2), now)))
    verified = [dict(what=cells[0], ids=work_ids(cells[0] + " " + " ".join(cells[4:5])), at=newest(cells[3], now))
                for cells in table(tables, "## Verifications") if len(cells) >= 5 and cells[2].lower().startswith("verified")]
    waiting = {rid: dict(row, ids=work_ids(row["what"])) for rid, row in gt.waiting_rows(ledger).items()}
    return dict(sessions=sessions, results=results, decisions=found, verified=verified, waiting=waiting,
                gh=[GH_LOOKUPS], ledger=ledger)


def pr_state(number, repo):
    """guide_gh's {"state", "mergedAt"} for a PR of `repo`, or None when gh can't say (no repo, no guide_gh, gh off,
    missing, slow or out of the hook's budget). None is "unchecked": no evidence now, asked again next audit."""
    try:
        import guide_gh
        return guide_gh.pr_state(number, repo=repo) if repo else None
    except Exception:  # an ImportError or a broken gh is "no evidence", never a failed audit
        return None


def pr_repo(ledger, text, number):
    """The repo PR `number` belongs to: the row's own owner/name#N or link, else the ledger Scope's one repo; None
    when it can't be told. Never the current directory's repo."""
    try:
        import guide_gh
        return guide_gh.repo_for(ledger, text, number)
    except Exception:
        return None


def merged(pr, text, index, since=0):
    """"gh: #N merged <date>" when gh says the PR merged after `since`, or None. At most GH_LOOKUPS asks per audit. A
    PR whose repo is unknown is never asked about: no evidence, and a `closes: pr:#N` tag on it doesn't fire."""
    number = int(pr.lstrip("#"))
    repo = pr_repo(index.get("ledger"), text, number)
    if not repo or index["gh"][0] <= 0:
        return None
    index["gh"][0] -= 1
    found = pr_state(number, repo)
    if not found or found.get("state") != "MERGED":
        return None
    at = iso_time(found.get("mergedAt"))
    return "gh: %s merged %s" % (pr, (found.get("mergedAt") or "")[:10] or "(no date)") if at is None or at > since else None


def evidence_for(ids, index, since=0, strict=False, exclude=None, text="", kinds="SRDVWG"):
    """Lines of LATER evidence (after `since`) that the work these ids name is done, best first. `strict` (the row was
    checked by a sweep) skips evidence with no date of its own, and reminders that ask the same."""
    later = lambda at: since <= 0 if at is None else at > since  # noqa: E731
    hits = []
    ids = set(ids)

    def which(found):
        return sorted(found & ids)[0]

    for s in index["sessions"] if "S" in kinds else ():
        if s["level"] in ("DONE", "CLOSED") and later(s["at"]) and (s["ids"] | s["brief"]) & ids:
            via = "its row" if s["ids"] & ids else "brief %s" % (s["briefs"][0] if s["briefs"] else "")
            hits.append((1, "Sessions '%s' [%s] DONE, %s names %s" % (s["name"][:50], s["id"], via, which(s["ids"] | s["brief"]))))
    for r in index["results"] if "R" in kinds else ():
        if not later(r["at"]):
            continue
        when = time.strftime("%m-%d %H:%M", time.localtime(r["at"])) if r["at"] else ""
        if r["ids"] & ids:
            hits.append((0, "Results '%s' satisfied %s, names %s" % (r["what"][:60], when, which(r["ids"]))))
            continue
        lower = r["what"].lower()
        by = next((s for s in index["sessions"] if (s["id"] in r["sids"] or len(s["name"]) >= 8 and s["name"].lower() in lower)
                   and (s["ids"] | s["brief"]) & ids), None)
        if by:
            hits.append((0, "Results '%s' satisfied %s, for '%s' [%s] whose %s names %s" % (
                r["what"][:60], when, by["name"][:40], by["id"], "row" if by["ids"] & ids else "brief", which(by["ids"] | by["brief"]))))
    for d in index["decisions"] if "D" in kinds else ():
        if d["closing"] and d["ids"] & ids and later(d["at"]):
            hits.append((2, "Decision %s: %s" % (d["number"], cell(d["what"], 70))))
    for v in index["verified"] if "V" in kinds else ():
        if v["ids"] & ids and (later(v["at"]) if v["at"] or strict else True):
            hits.append((3, "Verifications %s verified" % cell(v["what"], 50)))
    for rid, w in index["waiting"].items() if "W" in kinds and not strict else ():
        if rid != exclude and w["ids"] & ids:
            hits.append((4, "reminder [%s] asks the same: %s" % (rid, cell(w["what"], 60))))
    if not hits and "G" in kinds:
        for pr in sorted(i for i in ids if i.startswith("#")):
            found = merged(pr, text, index, since)
            if found:
                hits.append((5, found))
    out = []
    for _, said in sorted(hits, key=lambda h: h[0]):
        out += [said] if said not in out else []
    return out


def covered(item, index, now):
    """(evidence lines, why not): is this open row already covered by LATER ledger rows (or gh)? `item` has the row's
    `text` (or `what`), its `age` and `since` (when a sweep last checked it). The lines say what; the reason, when
    there are none, is "no later evidence" or "no id to match". It only stops an ask: it never strikes a row."""
    ids = work_ids(item.get("text") or item.get("what") or "")
    if not ids:
        return [], "no id to match"
    when = now - item["age"] if item.get("age") is not None else 0
    since = max(when, item.get("since") or 0)
    hits = evidence_for(ids, index, since, strict=bool(item.get("since")), exclude=item.get("rid"),
                        text=item.get("text") or "")
    return hits, "" if hits else "no later evidence"


def check_next(key, hits):
    return 'likely done: %s. Confirm, then `set %s done "<evidence>"`. Do not ask the user.' % ("; ".join(hits[:3]), key)


def closes_tags(text):
    """[(kind, value)] of a row's `closes:` tag: "closes: pr:#12", "closes result:<artifact id>", several at once."""
    found = CLOSES.search(text)
    return [(k.lower(), v) for k, v in TAG.findall(found.group(1))] if found else []


def happened(kind, value, index, levels, text=""):
    """The evidence that a `closes:` event has happened, or None."""
    if kind == "pr":
        number = re.search(r"#?(\d{1,6})$", value)
        return merged("#" + number.group(1), text + " " + value, index) if number else None
    if kind == "result":
        row = next((r for r in index["results"] if value in r["ids"] or named_in({value}, r["line"])), None)
        return "Results '%s' satisfied" % row["what"][:60] if row else None
    if kind == "ticket":
        found = evidence_for({value}, index, kinds="RD")
        return found[0] if found else None
    if kind == "session":
        level = next((lv for rid, (lv, _) in levels.items() if rid == value[:6].lower()), "")
        return "Sessions [%s] DONE" % value[:8] if level in ("DONE", "CLOSED") else None
    return None


def open_rows(ledger, now=None):
    """[(kind, key, text)] of the rows still open: Open items rows (keyed as the audit keys them) and reminders."""
    now = now or time.time()
    tables, _ = sections(ledger)
    rows = [("open", item["key"], item["text"]) for item in open_items(tables, now)]
    return rows + [("waiting", rid, row["what"]) for rid, row in gt.waiting_rows(ledger).items()]


def shared_ids(ledger, text, exclude=()):
    """The keys of open rows (Open items, reminders) that share an id (ticket, PR, artifact) with `text`: when a new
    row is written, these are the old rows it may replace."""
    ids = work_ids(text)
    if not ids:
        return []
    return sorted({key for _, key, row in open_rows(ledger) if key not in exclude and work_ids(row) & ids})


def close_tagged(ledger, now=None):
    """Close the open rows whose `closes:` event has happened; [one line per row closed]."""
    now = now or time.time()
    text = open(ledger, errors="replace").read()
    if not CLOSES.search(text):
        return []
    tables, lines = sections(ledger)
    index, levels, changes, said = evidence_index(ledger, tables, lines, now), gt.session_levels(ledger), {}, []
    for kind, key, row in open_rows(ledger, now):
        tags = closes_tags(row)
        proof = [happened(k, v, index, levels, row) for k, v in tags]
        if tags and all(proof):
            evidence = "closes %s: %s" % (", ".join("%s:%s" % t for t in tags), "; ".join(proof))
            changes[key] = ("DONE", evidence)
            said.append("%s %s: %s (%s)" % (key, "reminder" if kind == "waiting" else "Open item", cell(row, 90), evidence))
    if changes:
        edit_ledger(ledger, changes, "guide_audit closed %d row(s) whose closes: tag happened: %s"
                    % (len(changes), ", ".join(sorted(changes))), now)
    return said


def future_lines(lines, now):
    """[(line number, the date as written, the line)] of ledger lines whose first date is after now: the guide's
    written times drift ahead of the clock. The Waiting, Results and Verifications tables are skipped (the scripts
    write their times with the real clock, and Remind at is in the future on purpose), and so is a date after words
    like "until" or "by"."""
    found, skip = [], False
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    for n, line in enumerate(lines, 1):
        if line.startswith("## "):
            skip = line.startswith(("## Waiting on", "## Results for you", "## Verifications"))
            continue
        hits = [] if skip else stamps(line, now)
        if not hits:
            continue
        at, clock, match = hits[0]
        if LATER_WORDS.search(line[max(0, match.start() - 24):match.start()]):
            continue
        ahead = at > now + FUTURE_SLACK if clock else time.strftime("%Y-%m-%d", time.localtime(at)) > today
        if ahead:
            found.append((n, match.group(0), line.strip()))
    return found


def edit_ledger(ledger, changes, log, now):
    """Apply {key: (verdict, evidence)} to the ledger in one write, every other line left byte for byte: an Open items
    row's last cell becomes "<VERDICT> <date>: <evidence>; was: <what it said>" (verdict CHECKED stamps "checked
    <date>" instead), a reminder (Waiting row) is removed; then one Log line. Returns the keys it found."""
    with open(ledger, errors="replace", newline="") as f:
        lines = f.read().splitlines(True)
    day, section, done, out = time.strftime("%m-%d", time.localtime(now)), "", set(), []
    for raw in lines:
        if raw.startswith("## "):
            section = raw
        cells = gt.split_row(raw) if raw.lstrip().startswith("|") and not raw.startswith("## ") else None
        if cells and section.startswith("## Open items"):
            body = cells[1:] if re.match(r"\s*(?:20\d\d-)?\d\d-\d\d\b", cells[0]) and len(cells) > 2 else cells
            key = item_key(body[0]) if len(body) >= 2 and not body[0].startswith("~~") else None
            if key in changes and key not in done and not (any(FINISHED.match(c) for c in body[1:]) or STRUCK.match(body[0])):
                verdict, evidence = changes[key]
                last = CHECKED.sub("", cells[-1]).strip()
                cells[-1] = ("%s · checked %s" % (last, day) if last else "checked " + day) if verdict == "CHECKED" else (
                    "%s %s: %s" % (verdict, day, " ".join(evidence.split()).replace("|", "/")) + ("; was: " + last if last else ""))
                out.append("| %s |%s" % (" | ".join(cells), raw[len(raw.rstrip("\r\n")):]))
                done.add(key)
                continue
        if cells and section.startswith("## Waiting on") and len(cells) >= 4:
            rid = gt.row_id(cells[0])
            if rid in changes and changes[rid][0] != "CHECKED":
                done.add(rid)
                continue  # a reminder that is done leaves the table, as `unwait` does
        out.append(raw)
    if log:
        out = add_log(out, log, now)
    with open(ledger + ".tmp", "w", newline="") as f:
        f.write("".join(out))
    os.replace(ledger + ".tmp", ledger)
    return done


def add_log(lines, text, now):
    """`lines` with "- MM-DD HH:MM <text>" after the last line of the ## Log section (added at the end when missing)."""
    entry = "- %s %s" % (time.strftime("%m-%d %H:%M", time.localtime(now)), " ".join(text.split()))
    eol = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    start = next((i for i, l in enumerate(lines) if l.startswith("## Log")), None)
    if start is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += eol
        return lines + [eol] * bool(lines and lines[-1].strip()) + ["## Log (last ~15)" + eol, entry + eol]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    at = max([i for i in range(start, end) if lines[i].strip()] or [start]) + 1
    if not lines[at - 1].endswith("\n"):
        lines[at - 1] += eol
    return lines[:at] + [entry + eol] + lines[at:]


def unverified(ledger, tables, days, full, now):
    found = []
    follow = gt.followups(ledger, days, full, now)
    for t in follow["propose"]:
        found.append(dict(key=item_key(t["key"]), kind="unverified", tier="unverified", label=t["key"],
                          what="%s %s: %s" % (t["key"], t["where"], t["evidence"]),
                          age=now - t["date"] if t["date"] else None, state="unverified", why="no verification",
                          next="start a read-only 'verify %s'" % t["key"]))
    due = {gt.thing_key(r["thing"]) for r in follow["recheck"]}
    for key, row in gt.verification_rows(ledger).items():
        result, age = row["result"].lower().replace(" ", "-"), age_of(row["checked"], now)
        stale = result == "running" and (age is None or age > 86400)
        if key in due or result in ("proposed", "broken") or stale:
            same = re.match(r"\W*see (\S+)", row["evidence"])  # "see #131 (same verification)": one break, one row
            found.append(dict(key=item_key(key), kind="unverified", label=row["thing"].split()[0] if row["thing"] else key,
                              tier=result if result in ("proposed", "broken") else "recheck" if key in due else "unverified",
                              same=item_key(gt.thing_key(same.group(1))) if same else None,
                              what="%s (%s): %s" % (row["thing"], row["where"], row["evidence"]),
                              age=age, state="unverified", why=result + (" (re-check due)" if key in due else ""),
                              next={"broken": "start a fix", "proposed": "ask, then start its verify session"}
                              .get(result, "re-check on real data")))
    return found


def long_waits(waiting, now, index=None, marks=None):
    """(rows, notes). Every reminder is checked with covered() first: one with later evidence is a `check` row (and
    its note says "likely done: …"); one asked over a day ago with none is a `waiting` row; the rest only get a note,
    "checked <date>: still open because …". `notes` ({id6: line}) is what the hook says beside a due reminder."""
    found, notes, day = [], {}, time.strftime("%m-%d", time.localtime(now))
    for rid, row in waiting.items():
        asked, since = gt.read_time(row["asked"]), ((marks or {}).get(rid) or {}).get("checked")
        hits, reason = covered(dict(text=row["what"], rid=rid, age=now - asked if asked else None, since=since),
                               index, now) if index else ([], "")
        what = "%s: %s" % (row["session"], row["what"])
        if hits:
            notes[rid] = check_next(rid, hits)
            found.append(dict(key=rid, kind="waiting", tier="check", what=what, age=now - asked if asked else None,
                              state="check", why="likely done: " + hits[0], evidence=hits[:3], next=notes[rid],
                              since=since))
            continue
        notes[rid] = "checked %s: still open because %s" % (day, reason) if reason else ""
        if asked and now - asked > WAITING_HOURS * 3600:
            at = gt.read_time(row["remind"])
            found.append(dict(key=rid, kind="waiting", tier="waiting", what=what, age=now - asked, checked=notes[rid],
                              since=since,
                              state="waiting", why="due now" if at <= now else "asleep until " + row["remind"],
                              next="re-ask, or build around it"))
    return found, notes


def decisions(lines, tables, now, days=DECISION_DAYS):
    """Decisions of the last `days` that nothing else in the ledger refers to and whose words aren't an answer."""
    start = next((i for i, l in enumerate(lines) if l.startswith("## Decisions")), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    recent = []
    for line in lines[start + 1:end]:
        found = DECISION.match(line.strip())
        if not found or line.lstrip().startswith(("~~", "- ~~")):
            continue
        age = age_of(found.group(2), now)
        if age is not None and age <= days * 86400:
            recent.append((found.group(1), found.group(3), age, line))
    if not recent:
        return []
    rest = "\n".join(lines[:start] + lines[end:])
    out = []
    for number, text, age, line in recent:
        named = re.search(r"\bD(?:ecisions?)?\s?(?:[\d/, -]*[/, -])?%s\b" % number, rest) or any(
            re.search(r"\bD(?:ecisions?)?\s?(?:[\d/, -]*[/, -])?%s\b" % number, other) for _, _, _, other in recent if other != line)
        if named or ANSWER.search(text):
            continue
        out.append(dict(key="D" + number, kind="decision", tier="decision", label="D" + number,
                        what="Decision %s: %s" % (number, text.strip("* ")), age=age,
                        state="decision", why="no trace in the ledger", next="start it, or note why not"))
    return out


def first_prompt(path):
    """The first line of the first thing the user (or the guide's brief) said in a transcript."""
    try:
        with open(path, "rb") as f:
            for _ in range(60):
                raw = f.readline()
                if not raw:
                    break
                if b'"type":"user"' not in raw.replace(b" ", b""):
                    continue
                try:
                    content = (json.loads(raw).get("message") or {}).get("content")
                except ValueError:
                    continue
                if isinstance(content, list):
                    content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
                for line in (content or "").splitlines():
                    line = line.strip(" #*")
                    if line and not line.startswith("<"):
                        return line
    except OSError:
        pass
    return ""


def last_result(path):
    """(the `result:` line of the last assistant text, or "", and True when the transcript has assistant text)."""
    text = ""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 256 * 1024))
            for raw in f.read().splitlines():
                if b'"assistant"' not in raw or b'"text"' not in raw:
                    continue
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                if d.get("type") != "assistant" or d.get("isSidechain"):
                    continue
                said = [b.get("text") or "" for b in (d.get("message") or {}).get("content") or []
                        if isinstance(b, dict) and b.get("type") == "text"]
                text = "\n".join(said) or text
    except OSError:
        pass
    found = re.findall(r"(?im)^\W*result:\s*(.+)$", text)
    return (found[-1].strip() if found else ""), bool(text)


def session_name(cell):
    return re.sub(r"\s*\[[0-9a-fA-F]{6,36}\].*", "", cell).strip("' ") or "untitled"


def chain(name):
    """What a relay of sessions shares: 'wave E4 build', 'wave E4 build 2' and 'wave E4 build (3)' are one chain."""
    return re.sub(r"\s+\(?\d{1,2}\)?$", "", name).lower()


def session_rows(ledger, tables, days, now):
    """Sessions of the last `days` that didn't end cleanly: no result line, a result that says it isn't finished, or a
    result naming a PR the ledger never says was merged. Only the last session of a relay counts: the ones that
    handed on are its history. Returns (rows, how many ended cleanly or handed on)."""
    levels, every = gt.session_levels(ledger), transcripts(0)
    landed = {h["key"] for h in gt.ledger_hits(ledger, 0, now)}
    verified = gt.verification_rows(ledger)
    waiting, rows, clean, last = gt.waiting_rows(ledger), [], 0, {}
    for rid, (level, cell) in levels.items():
        base = chain(session_name(cell))
        if rid in every and base != "untitled" and every[rid][1] > last.get(base, ("", 0))[1]:
            last[base] = (rid, every[rid][1])
    for rid, (path, at) in every.items():
        level, cell = levels.get(rid, ("", ""))
        sid = os.path.basename(path)[:-6]
        if at < now - days * 86400 or not level or level in ("IGNORED", "RETIRED"):
            continue
        content = gt.marker_content(sid)
        if content is not None and content not in gt.WORKER_MARKERS + (gt.DONE,):
            continue
        idle, name = now - at, session_name(cell)
        if idle < QUIET_HOURS * 3600 or (gt.job_state(sid) == "working" and gt.session_alive(sid)) or rid in waiting:
            continue  # still running, or settled as waiting on the user: `settle` has it
        if last.get(chain(name), (rid,))[0] != rid:
            clean += 1  # a later session of the same relay carries its work
            continue
        result, spoke = last_result(path)
        prs = [t for t in tickets(result) if t.startswith("#")]
        why = ("no result line" if not result else "result says not finished" if NOT_DONE.search(result) else
               "%s: no merge in the ledger" % ", ".join(prs) if prs and not set(prs) & landed else
               "%s landed, no verification" % ", ".join(prs) if prs and not any(p in verified for p in prs) else "")
        if not why or not spoke:
            clean += bool(spoke)
            continue
        rows.append(dict(key=rid, kind="session", age=idle, ended=at, state="session", why=why, label="'%s'" % name[:40],
                         tier="noresult" if not result else "unfinished", prs=prs,
                         what="'%s' meant: %s; ended: %s" % (name[:40], first_prompt(path)[:70] or "?", result[:90] or "—"),
                         next="peek %s; finish it, hand it on, or `set %s done`" % (rid, rid)))
    return rows, clean


def score(row, days=DAYS):
    """value x age: how much an hour of the guide's attention is worth on this row."""
    age = min(row["age"], AGE_CAP * 86400) / 86400 if row.get("age") is not None else days / 2
    words = row.get("what", "") + " " + row.get("why", "")
    return VALUE.get(row.get("tier"), 1) * max(age, 0.25) * (1.5 if URGENT.search(words) else 1) * (
        0.5 if MINOR.search(words) else 1)


def label(row):
    """A row's short name inside a collapsed row: the first ticket or id its words name, else its first words."""
    if row.get("label"):
        return row["label"]
    found = [(row["what"].find(n), n) for n in row.get("names") or tickets(row["what"]) if n in row["what"]]
    return min(found)[1] if found else " ".join(row["what"].split()[:5])


def marked(row, marks, live, now):
    """A `set` mark on a row that isn't an Open item or a queue row: None when it is done or dropped, the state that
    hides it (asked, parked, moving), or "" when it stands."""
    mark = marks.get(row["key"]) or {}
    state = mark.get("state")
    if state in ("done", "dropped"):
        return None
    if state == "started":
        seen = live.get((mark.get("session") or "")[:6].lower())
        return "moving" if seen and seen["moving"] else ""
    return state if state in ("asked", "parked") and (not mark.get("until") or mark["until"] > now) else ""


def audit(ledger, days=DAYS, full=True, queues=(), now=None):
    """The audit as a dict: rows (not done or not verified, ranked), their collapsed top rows, every other item by
    state, and the counts."""
    now = now or time.time()
    tables, lines = sections(ledger)
    state = load_state(ledger)
    marks = state.get("items") or {}
    waiting = gt.waiting_rows(ledger)
    live = live_sessions(tables, now, transcripts(now - 30 * 86400))
    index = evidence_index(ledger, tables, lines, now)
    work, hidden, checks, day = [], [], [], time.strftime("%m-%d", time.localtime(now))
    for item in open_items(tables, now) + queue_items(queue_paths(lines, queues), now):
        found, why = classify(item, marks, live, waiting, now)
        if found is None:
            continue
        item["since"] = max((marks.get(item["key"]) or {}).get("checked") or 0, item.get("stamped") or 0) or None
        if found in ASK_STATES:  # before anything is put to the user: is it already done?
            hits, reason = covered(item, index, now)
            if hits:
                found, why, item["evidence"] = "check", "likely done: " + hits[0], hits[:3]
            elif found != "asked":
                item["checked"] = "checked %s: still open because %s" % (day, reason)
        late = item["age"] is None or item["age"] > idle_hours() * 3600
        item.update(state=found, why=why, tier=found, next={
            "idle": "ask now: start it / keep waiting / drop" if late else "propose a start",
            "person": "ask %s in this turn's interview, then `waiting ask`" % person(item["owner"]),
            "quiet": "peek the worker; restart it or start a successor",
            "check": check_next(item["key"], item.get("evidence") or [])}.get(found, ""))
        if found in ("idle", "quiet", "person") and item["kind"] == "open" and (
                item["age"] is None or item["age"] > 2 * days * 86400):
            item.update(state="stale", tier="backlog", was=found, was_why=why, why="open %s, %s" % (
                "with no date" if item["age"] is None else "for " + span(item["age"]), why))
        (work if item["state"] in ("idle", "quiet", "person") else checks if found == "check" else hidden).append(item)
    waits, notes = long_waits(waiting, now, index, marks)
    other = unverified(ledger, tables, min(days, gt.FOLLOWUP_DAYS), full, now) + waits
    other += decisions(lines, tables, now)
    clean = None
    if full:
        sessions, clean = session_rows(ledger, tables, days, now)
    else:  # the last full audit's session rows still stand
        sessions = [dict(r, age=now - r["ended"]) for r in state.get("sessions") or [] if r.get("ended")]
    checked = {t for r in other if r["kind"] == "unverified" for t in tickets(r["what"])}
    other += [r for r in sessions if not (r.get("prs") and set(r["prs"]) <= checked)]  # those PRs are rows already
    rows = work + checks
    for row in other:
        found = marked(row, marks, live, now)
        if found:
            hidden.append(dict(row, state=found))
        elif found is not None:
            rows.append(row)
    for row in rows + hidden:
        row["score"] = score(row, days)
    rows.sort(key=lambda r: -r["score"])
    ages = [r["age"] for r in work if r["age"] is not None]
    nag = [r for r in work if r["age"] is None or r["age"] > idle_hours() * 3600]
    count = lambda kind: sum(r["kind"] == kind and r["state"] != "check" for r in rows)  # noqa: E731
    found = dict(rows=rows, hidden=hidden, nag=nag, clean=clean, at=now, full=full, days=days, reminders=notes,
                 future=future_lines(lines, now),
                 counts=dict(idle=len(work), oldest=max(ages) if ages else None, nag=len(nag),
                             check=sum(r["state"] == "check" for r in rows),
                             unverified=count("unverified"), waiting=count("waiting"), decisions=count("decision"),
                             sessions=count("session"), **{s: sum(h["state"] == s for h in hidden)
                                                           for s in ("moving", "asked", "parked", "stale")}))
    found["counts"]["future"] = len(found["future"])
    found["top"] = collapse(found)
    return found


def group_of(row):
    """What a row collapses with: rows that share one next action become one row of the table."""
    if row["state"] == "stale":
        return ("backlog",)
    if row["state"] == "check":
        return ("check",)
    if row["kind"] in ("open", "queue"):
        if row["state"] == "quiet":
            return ("quiet", row["why"] if "quiet" in row["why"] else "gone")
        if row["state"] == "person":
            return ("person", person(row["owner"]).lower())
        return ("queue", row["owner"]) if row["kind"] == "queue" else ("owner", owner_head(row["owner"]))
    if row.get("tier") == "broken":
        return ("broken", row.get("same") or row["key"])
    if row["kind"] in ("unverified", "decision") or row.get("tier") == "noresult":
        return (row["tier"],)
    return (row["kind"], row["key"])


GROUPS = {  # what a collapsed row says, and its one next action
    "backlog": ("Open items rows that are undated or older than %(old)g days (the backlog)",
                "one interview question: close, drop or re-queue them in bulk"),
    "quiet": ("items whose %(gone)s", "peek the worker; restart it or start a successor, or drop"),
    "person": ("items wait on %(person)s with no reminder", "one interview question listing them, then `waiting ask`"),
    "queue": ("approved rows of %(owner)s with no worker", "ask now: start a fix wave for them / keep waiting / drop"),
    "owner": ("items for '%(owner)s' with no worker", "ask now: start that session / keep waiting / drop"),
    "unverified": ("landed with no verification", "start one read-only verify session for the batch"),
    "recheck": ("fixes not exercised yet, re-check due", "one read-only re-check on real data for the batch"),
    "proposed": ("verifications proposed and never started", "ask, then start one verify session for them"),
    "broken": ("verifications that found the same break", "start a fix"),
    "decision": ("recent decisions nothing in the ledger refers to", "skim; start what is still owed, `set` the rest done"),
    "noresult": ("sessions that ended with no result line", "peek each; hand its work on, or `set` it done"),
    "check": ("rows that later ledger rows show as likely done",
              "confirm each from its evidence (`audit --group <key>`), then `set <key> done \"<evidence>\"`; do not ask "
              "the user"),
}


def group_title(group, rows, days):
    """(what a collapsed row of `rows` says, its one next action)."""
    first = rows[0]
    title, action = GROUPS[group[0]]
    return title % dict(old=2 * days, owner=first.get("owner", "") if first["kind"] == "queue" else
                        owner_head(first.get("owner", "")), person=person(first.get("owner", "")),
                        gone=first["why"] if group[-1] != "gone" else "worker is closed or gone"), action


def checked_note(rows):
    """One "checked <date>: still open because …" for a collapsed row, counting each reason."""
    notes = [r["checked"] for r in rows if r.get("checked")]
    if not notes:
        return ""
    reasons = {}
    for note in notes:
        reason = note.split("because ", 1)[-1]
        reasons[reason] = reasons.get(reason, 0) + 1
    return "%s: still open because %s" % (notes[0].split(":")[0], ", ".join(
        "%s (%d)" % (r, n) if len(notes) > 1 else r for r, n in sorted(reasons.items())))


def collapse(found):
    """The table's rows: every row with the ones that share its next action, ranked by the best of each, the backlog
    as one row. A collapsed row's key is its best row's key plus "+N"; `audit --group <key>` lists what is in it."""
    groups = {}
    for row in found["rows"] + [h for h in found["hidden"] if h["state"] == "stale"]:
        groups.setdefault(group_of(row), []).append(row)
    out = []
    for group, rows in groups.items():
        rows.sort(key=lambda r: -r["score"])
        first, dated = rows[0], [r["age"] for r in rows if r["age"] is not None]
        if len(rows) == 1:
            out.append(dict(first, members=rows))
            continue
        title, action = group_title(group, rows, found["days"])
        names = []
        for r in rows:
            names += [label(r)] if label(r) not in names else []
        out.append(dict(key="%s+%d" % (first["key"], len(rows) - 1), kind=first["kind"], state=first["state"],
                        age=max(dated) if dated else None, members=rows, next=action, checked=checked_note(rows),
                        why="oldest of %d" % len(rows) if dated else "no dates",
                        score=first["score"] * (1 + 0.1 * min(len(rows) - 1, 5)),
                        what="%d %s: %s" % (len(rows), title, ", ".join(names))))
    return sorted(out, key=lambda r: -r["score"])


def idle_hours():
    try:
        return float(os.environ.get("SESSION_GUIDE_IDLE_HOURS", IDLE_HOURS))
    except ValueError:
        return IDLE_HOURS


def audit_hours():
    try:
        return float(os.environ.get("SESSION_GUIDE_AUDIT_HOURS", AUDIT_HOURS))
    except ValueError:
        return AUDIT_HOURS


def summary(found):
    c = found["counts"]
    text = "%d idle decided item(s)%s, %d over %g h with no question to the user; %d unverified; %d reminder(s) open over a day" % (
        c["idle"], " (oldest %s)" % span(c["oldest"]) if c["oldest"] is not None else "", c["nag"], idle_hours(),
        c["unverified"], c["waiting"])
    text += "; %d decision(s) with no trace" % c["decisions"] if c["decisions"] else ""
    if found["full"]:
        text += "; %d session(s) without a clean end (%d clean)" % (c["sessions"], found["clean"] or 0)
    elif c["sessions"]:
        text += "; %d session(s) without a clean end at the last full audit" % c["sessions"]
    text += "; %d Open items row(s) in the backlog" % c["stale"] if c["stale"] else ""
    text += "; %d row(s) likely done already (check, don't ask)" % c["check"] if c.get("check") else ""
    text += "; %d ledger line(s) dated after now" % c["future"] if c.get("future") else ""
    return text + "; not listed: %d moving, %d asked, %d parked" % (c["moving"], c["asked"], c["parked"])


def cell(text, width):
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= width else text[:width - 1] + "…"


def line(r, wide=110):
    """One table row. A check row's next action carries its evidence, and a row still to ask says when it was
    checked, so those two get a wider Next action cell."""
    after = (r.get("next") or "—") + ("; " + r["checked"] if r.get("checked") else "")
    return "| %s | %s | %s | %s | %s | %s |" % (
        r["key"], span(r["age"]), "backlog" if r["state"] == "stale" else r["kind"] if r["state"] in (
            "unverified", "waiting", "decision", "session") else r["state"],
        cell(r["what"], wide if len(r.get("members") or ()) < 2 else wide + 60), cell(r["why"], 40),
        cell(after, 240 if r["state"] == "check" else 130 if r.get("checked") else 64))


def render(found, limit=TOP, everything=False, group=None):
    """The table: the top `limit` collapsed rows by value x age; every single row with `everything`; the rows inside
    one collapsed row with `group` (its key, with or without the "+N")."""
    head = ["| Key | Age | Kind | What | Why | Next action |", "|---|---|---|---|---|---|"]
    if group:
        rows = next((r["members"] for r in found["top"] if group.split("+")[0].lower() in
                     [m["key"].lower() for m in r["members"]]), [])
        return "\n".join(head + [line(r) for r in rows]) if rows else "No row has the key %s." % group
    if everything:
        rows = found["rows"] + sorted(found["hidden"], key=lambda r: -r.get("score", 0))
        return "\n".join(head + [line(r) for r in rows]) if rows else "Nothing idle, unverified or stuck."
    rows, more = found["top"][:limit], found["top"][limit:]
    out = head + [line(r) for r in rows]
    if more:
        out.append("… and %d more row(s) holding %d item(s), lower value x age: `audit --limit %d`, or `--all` for every item"
                   % (len(more), sum(len(r["members"]) for r in more), limit + len(more)))
    if any(len(r["members"]) > 1 for r in rows):
        out.append("A key ending +N is a collapsed row: `audit --group <key>` lists its items, `set <key> <state>` marks them all.")
    return "\n".join(out) if rows else "Nothing idle, unverified or stuck."


def state_file(ledger, found, state=None):
    """STATE.md: the live state a takeover reads instead of the ledger's log."""
    now = found["at"]
    tables, lines = sections(ledger)
    head = [l for l in lines[:8] if l.startswith(("# ", "Guide:", "Scope:", "Other guides:", "Queues:"))]
    out = head + ["", "Generated %s by guide_audit.py (%s audit); do not edit, it is rewritten on every guide prompt. "
                  "The ledger's tables hold the detail." % (time.strftime(gt.TIME_FORMAT, time.localtime(now)),
                                                           "full" if found["full"] else "quick"), ""]
    live = live_sessions(tables, now, transcripts(now - 30 * 86400))
    out += ["## Open sessions (%d)" % len(live)]
    out += ["- %s %s, %s" % (cell(gt.with_icon(ledger, s["cell"]), 70), s["level"], session_state(rid, s, now))
            for rid, s in list(live.items())[:25]] + ["- and %d more" % (len(live) - 25)] * (len(live) > 25)
    settle = gt.settle_status(ledger, os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    results = gt.results_status(ledger)["due"]
    notes = found.get("reminders") or {}
    out += ["", "## Reminders (%d due, %d asleep)" % (len(settle["due"]), len(settle["asleep"]))]
    out += ["- %s %s: %s%s" % ("DUE" if r in settle["due"] else "until " + r["remind"],
                               cell(gt.with_icon(ledger, r["session"], r["what"]), 40),
                               cell(r["what"], 150), " (%s)" % cell(notes[r["id"]], 160) if notes.get(r["id"]) else "")
            for r in (settle["due"] + settle["asleep"])[:20]]
    out += ["", "## Results with no verdict (%d)" % len(results)]
    out += ["- " + cell(gt.describe_result(r, ledger), 200) for r in results[:12]]
    out += gt.stream_lines(ledger)
    if found.get("future"):
        out += ["", "## Ledger lines dated after now (%d): run `date` before writing a time" % len(found["future"])]
        out += ["- L%d %s: %s" % (n, written, cell(text, 120)) for n, written, text in found["future"][:10]]
    struck = (state or {}).get("struck") or {}
    if struck.get("rows"):
        out += ["", "## Last strike sweep (%s)" % time.strftime(gt.TIME_FORMAT, time.localtime(struck.get("at", now)))]
        out += ["- " + cell(r, 220) for r in struck["rows"][:40]]
    out += ["", "## Not done or not verified (top %d by value x age)" % (2 * TOP), summary(found), "", render(found, 2 * TOP), ""]
    save(state_paths(ledger)[1], "\n".join(out))


def reconcile_module():
    """guide_reconcile (the job folder's facts), next to this script; None when it can't be loaded."""
    try:
        import guide_reconcile
        return guide_reconcile
    except Exception:
        return None


def session_state(rid, live, now):
    """What an open session is really doing, for STATE.md: its job's state ("working", "ended 12 min ago (done),
    result: …"), not a guess from its transcript's age. A session with no job folder (interactive, or old) keeps the
    transcript wording: running, quiet <age>, no transcript."""
    try:
        facts = reconcile_module().job_facts(rid)
    except Exception:
        facts = None
    if facts is None:
        return ("running" if live["moving"] else "quiet " + span(live["idle"]) if live["idle"] is not None
                else "no transcript")
    if facts["state"] == "working" and facts["alive"]:
        return "working" + (": " + cell(facts["detail"], 80) if facts["detail"] else "")
    ended = facts["ended_at"].timestamp() if facts["ended_at"] else None
    ago = "%d min" % ((now - ended) // 60) if ended is not None and now - ended < 3600 else span(
        now - ended if ended is not None else None)
    result = facts["result"] or facts["detail"]
    return "ended %s ago (%s)%s" % (ago, facts["state"] if facts["state"] != "working" else "process gone",
                                     ", result: " + cell(result, 110) if result else "")


def candidates(found):
    """The rows a strike sweep looks at: the check rows, and the rows still to ask that are idle over STRIKE_DAYS (or
    undated), unless a sweep found them open in the last CHECKED_DAYS."""
    now, out = found["at"], []
    for r in found["rows"] + found["hidden"]:
        if r["kind"] not in ("open", "queue", "waiting") or r.get("since") and now - r["since"] < CHECKED_DAYS * 86400:
            continue
        old = r["age"] is None and r["state"] == "stale" or (r["age"] or 0) > STRIKE_DAYS * 86400
        if r["state"] == "check" or r["state"] in ("idle", "quiet", "person", "stale", "waiting") and old:
            out.append(r)
    return sorted(out, key=lambda r: (r["state"] != "check", -(r["age"] or 0)))


def write_candidates(ledger, found):
    """strike-candidates.md, for the 'strike sweep' helper; returns how many rows it holds."""
    rows, me = candidates(found), os.path.abspath(__file__)
    verdicts = os.path.join(os.path.dirname(os.path.abspath(ledger)), "strike-verdicts.md")
    out = ["# Strike candidates", "",
           "Written %s by guide_audit.py (full audit) for the guide's read-only 'strike sweep' helper. For each row, look "
           "for proof that it is finished or replaced: later rows of the ledger (%s), the brief and result of the "
           "session that did it, `gh pr view`. Change nothing. Write one line per key to %s:" % (
               time.strftime(gt.TIME_FORMAT, time.localtime(found["at"])), ledger, verdicts), "",
           "    <key> | DONE | <the proof: ledger line, PR state, result line>",
           "    <key> | SUPERSEDED | <what replaced it>",
           "    <key> | OPEN | <why it is still open>", "",
           "Then the guide runs `python3 %s strike --from %s`." % (me, verdicts), "",
           "| Key | Age | Kind | What | Evidence so far |", "|---|---|---|---|---|"]
    out += ["| %s | %s | %s | %s | %s |" % (r["key"], span(r["age"]), r.get("was") or r["state"], cell(r["what"], 200),
                                            cell("; ".join(r.get("evidence") or []) or r.get("checked") or "—", 200))
            for r in rows]
    save(strike_path(ledger), "\n".join(out) + "\n")
    return len(rows)


def run(ledger, days=DAYS, full=True, queues=()):
    """Run the audit, write STATE.md and audit.json, and return what was found. The full audit keeps its session rows
    in the cache, so a quick refresh in between doesn't lose them, and writes strike-candidates.md. Rows whose
    `closes:` event has happened are closed first; the next hook line says which."""
    try:
        closed = close_tagged(ledger)
    except OSError:
        closed = []
    found = audit(ledger, days, full, queues)
    state = load_state(ledger)
    if closed:
        state["closed"] = (state.get("closed") or []) + closed
    if full:
        state["full_at"] = found["at"]
        state["sessions"] = [dict(r, names=None) for r in found["rows"] + found["hidden"] if r["kind"] == "session"]
    late = {r["key"] for r in found["nag"]}
    state["quick"] = dict(at=found["at"], counts=found["counts"], queues=list(queues) or (state.get("quick") or {}).get("queues") or [],
                          nag=["%s %s: %s -> %s" % (r["key"], span(r["age"]), cell(r["what"], 130), (r.get("next") or "ask")
                                                    + ("; " + r["checked"] if r.get("checked") else ""))
                               for r in found["top"] if any(m["key"] in late for m in r["members"])][:5],
                          check=["%s %s: %s -> likely done: %s" % (r["key"], span(r["age"]), cell(r["what"], 100),
                                                                  "; ".join(r.get("evidence") or []))
                                 for r in found["rows"] if r["state"] == "check"][:5],
                          reminders=found["reminders"],
                          future=["L%d %s: %s" % (n, written, cell(text, 100)) for n, written, text in found["future"][:5]])
    try:
        if full:
            state["sweep"] = dict(at=found["at"], count=write_candidates(ledger, found))
        save(state_paths(ledger)[0], json.dumps(state, indent=1))
        state_file(ledger, found, state)
    except OSError:
        pass
    return found


def cached(ledger):
    """The counts of the last audit ({idle, oldest, nag, check, ...}), or {} when none ran. Reads one small file."""
    return (load_state(ledger).get("quick") or {}).get("counts") or {}


def reminder_checks(ledger):
    """{id6: line} from the last audit, for the hook's list of due reminders: "likely done: <evidence>. Confirm, then
    `set <id6> done "<evidence>"`. Do not ask the user." in place of the ask when later rows cover it, else "checked
    <date>: still open because …" to add to the ask. Reads one small file."""
    return (load_state(ledger).get("quick") or {}).get("reminders") or {}


def hook_context(ledger):
    """What the guide hears on its prompt: rows the audit closed by their tags, the idle items it owes the user a
    question about, the rows that look done already, a due strike sweep, a due full audit, and lines dated after now."""
    hours = audit_hours()
    if hours <= 0:
        return None
    state = load_state(ledger)
    quick = state.get("quick") or {}
    now = time.time()
    if now - quick.get("at", 0) > QUICK_MINUTES * 60 or os.path.getmtime(ledger) > quick.get("at", 0):
        run(ledger, full=False, queues=quick.get("queues") or ())
        state = load_state(ledger)
        quick = state.get("quick") or {}
    counts, parts, me = quick.get("counts") or {}, [], os.path.abspath(__file__)
    if state.get("closed"):
        parts.append("session-guide audit: closed %d row(s) whose `closes:` tag has happened (tell the user in one line):"
                     "\n%s" % (len(state["closed"]), "\n".join("- " + l for l in state["closed"][:8])))
        state.pop("closed")
        try:
            save(state_paths(ledger)[0], json.dumps(state, indent=1))
        except OSError:
            pass
    if counts.get("nag"):
        parts.append("session-guide audit: %d decided item(s) have no worker and no question to the user for over %g h "
                     "(%d idle in all, oldest %s). The top ones by value x age:\n%s\nPut each in this turn's interview, "
                     "recommended option first: start it now / keep waiting for <what> / drop. Then record it: start a "
                     "worker and `python3 %s set <key> started --session <id>`, or `set <key> asked` / `parked --hours N` "
                     "/ `dropped`. `python3 %s audit` prints the top 10 of everything." % (counts["nag"], idle_hours(), counts.get("idle", 0),
                                                         span(counts.get("oldest")), "\n".join("- " + l for l in quick.get("nag") or []), me, me))
    if counts.get("check"):
        parts.append("session-guide audit: %d open row(s) look done already: later ledger rows (or gh) cover them. Do "
                     "not ask the user about them. Confirm each from its evidence, then `python3 %s set <key> done "
                     "\"<evidence>\"`:\n%s" % (counts["check"], me, "\n".join("- " + l for l in quick.get("check") or [])))
    sweep = state.get("sweep") or {}
    if sweep.get("count") and now - state.get("sweep_at", 0) > SWEEP_HOURS * 3600:
        parts.append("session-guide strike sweep: %d row(s) in %s may be finished (last sweep %s). Start ONE read-only "
                     "helper named 'strike sweep' (sonnet/medium) on that file: it returns `<key> | DONE / SUPERSEDED / "
                     "OPEN | <evidence>` lines. Then run `python3 %s strike --from <its file>`, tell the user the one line "
                     "it prints, and put `python3 %s audit --open-batch` to the user once." % (
                         sweep["count"], strike_path(ledger), time.strftime(gt.TIME_FORMAT, time.localtime(
                             state["sweep_at"])) if state.get("sweep_at") else "never", me, me))
    if now - state.get("full_at", 0) > hours * 3600:
        parts.append("session-guide audit: the look back over past sessions is due (last full audit %s). On this wake, or "
                     "the first one with nothing due, run `python3 %s audit` and put what it lists into the interview."
                     % (time.strftime(gt.TIME_FORMAT, time.localtime(state["full_at"])) if state.get("full_at") else "never", me))
    if counts.get("future"):
        parts.append("session-guide clock: %d ledger line(s) carry a time after now (%s): your written times run ahead "
                     "of the clock. Run `date` before you write a time, and correct these:\n%s" % (
                         counts["future"], time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(now)),
                         "\n".join("- " + l for l in quick.get("future") or [])))
    return "\n".join(parts) or None


def find_keys(ledger, given):
    """The audit items `given` names: 6-character keys or tickets, comma-separated; a key ending "+N" is every item
    of that collapsed row."""
    found = audit(ledger, full=False, queues=(load_state(ledger).get("quick") or {}).get("queues") or ())
    items, out = found["rows"] + found["hidden"], []
    for one in [g.strip() for g in given.split(",") if g.strip()]:
        hits = [r for r in items if r["key"].lower() == one.lower()] or [r for r in items if one in (r.get("names") or ())]
        if re.search(r"\+\d+$", one):
            hits = next((r["members"] for r in found["top"] if r["key"].lower() == one.lower()), [])
        elif len(hits) != 1:
            hits = []
        if not hits:
            raise SystemExit("%r names %d audit items; use the key from `audit` (`audit --all` lists every item)"
                             % (one, len([r for r in items if one in (r.get("names") or ())])))
        out += [h for h in hits if h not in out]
    return out


def cmd_set(args):
    ledger = os.path.expanduser(args.ledger or gt.require_ledger())
    items = find_keys(ledger, args.key)
    if args.state == "started" and not args.session:
        raise SystemExit("started needs --session <id>: the worker that has it")
    now = time.time()
    hours = args.hours if args.hours else ASKED_HOURS if args.state == "asked" else 0
    state = load_state(ledger)
    evidence = " ".join((args.evidence or "").split())
    for item in items:
        mark = dict(state=args.state, at=now, what=item["what"][:120], note=" ".join((args.note or evidence).split()))
        if hours:
            mark["until"] = now + hours * 3600
        if args.session:
            mark["session"] = gt.resolve_session(args.session)
        state.setdefault("items", {})[item["key"]] = mark
        print("%s %s%s: %s" % (item["key"], args.state, " for %g h" % hours if hours else "", cell(item["what"], 100)))
    save(state_paths(ledger)[0], json.dumps(state, indent=1))
    rows = [item for item in items if item["kind"] in ("open", "waiting")]
    if args.state in ("done", "dropped") and evidence and rows:  # the row itself says so, as a strike sweep writes it
        done = edit_ledger(ledger, {item["key"]: (args.state.upper(), evidence) for item in rows}, None, now)
        print("The ledger says so: %d Open items row(s) now %s, %d reminder(s) removed." % (
            sum(item["key"] in done for item in rows if item["kind"] == "open"), args.state.upper(),
            sum(item["key"] in done for item in rows if item["kind"] == "waiting")))
    elif args.state in ("done", "dropped") and any(item["kind"] == "open" for item in items):
        print("Also set the Status of each Open items row to %s, with how it was verified or why." % args.state.upper())
    run(ledger, full=False, queues=(state.get("quick") or {}).get("queues") or ())
    return 0


def cmd_strike(args):
    """Apply a strike sweep's verdicts: `<key> | DONE / SUPERSEDED / OPEN | <evidence>`, one per line."""
    ledger = os.path.expanduser(args.ledger or gt.require_ledger())
    try:
        with open(os.path.expanduser(args.from_file), errors="replace") as f:
            verdicts = [m.groups() for m in map(VERDICT.match, f.read().splitlines()) if m]
    except OSError as e:
        raise SystemExit("can't read %s: %s" % (args.from_file, e))
    if not verdicts:
        raise SystemExit("%s has no `<key> | DONE / SUPERSEDED / OPEN | <evidence>` lines" % args.from_file)
    state = load_state(ledger)
    found = audit(ledger, full=False, queues=(state.get("quick") or {}).get("queues") or ())
    items, waiting, now = found["rows"] + found["hidden"], gt.waiting_rows(ledger), time.time()
    marks, changes, struck, still, unknown = state.setdefault("items", {}), {}, [], [], []
    for key, verdict, evidence in verdicts:
        verdict, evidence = verdict.upper(), " ".join(evidence.split()) or "(no evidence given)"
        hits = [r for r in items if r["key"].lower() == key.lower()] or [r for r in items if key in (r.get("names") or ())]
        item = hits[0] if len(hits) == 1 or hits and hits[0]["key"].lower() == key.lower() else None
        if item is None and key.lower() in waiting:
            item = dict(key=key.lower(), kind="waiting", what=waiting[key.lower()]["what"])
        if item is None:
            unknown.append(key)
            continue
        if verdict == "OPEN":
            mark = marks.get(item["key"]) or dict(what=item["what"][:120])
            mark["checked"] = now
            marks[item["key"]] = mark
            if item["kind"] == "open":
                changes.setdefault(item["key"], ("CHECKED", evidence))
            still.append("%s OPEN (checked): %s; %s" % (item["key"], cell(item["what"], 100), evidence))
            continue
        marks[item["key"]] = dict(state="done" if verdict == "DONE" else "dropped", at=now, what=item["what"][:120],
                                  note="%s: %s" % (verdict, evidence))
        if item["kind"] in ("open", "waiting"):
            changes[item["key"]] = (verdict, evidence)
        struck.append("%s %s: %s; %s" % (item["key"], verdict, cell(item["what"], 100), evidence))
    keys = lambda rows: ", ".join(r.split()[0] for r in rows) or "none"  # noqa: E731
    edit_ledger(ledger, changes, "guide_audit strike: struck %d stale row(s) (%s), %d checked and still open (%s); "
                "list in STATE.md" % (len(struck), keys(struck), len(still), keys(still)), now)
    state["sweep_at"], state["struck"] = now, dict(at=now, rows=struck + still)
    save(state_paths(ledger)[0], json.dumps(state, indent=1))
    run(ledger, full=False, queues=(state.get("quick") or {}).get("queues") or ())
    print("struck %d stale rows, list in STATE.md" % len(struck))
    print("Guide: tell the user the line above, and nothing more about those rows. %d row(s) are still open%s; put "
          "`python3 %s audit --open-batch` to the user once, as one batch." % (
              len(still), "" if not unknown else "; not audit rows (already closed?): " + ", ".join(unknown),
              os.path.abspath(__file__)))
    return 0


def open_batch(found):
    """The rows really still open, grouped by stream (the audit's grouping), for ONE keep / start / drop question per
    group: what the guide puts to the user once after a strike sweep."""
    groups = {}
    for r in found["rows"] + found["hidden"]:
        if r["kind"] in ("open", "queue") and r["state"] in ("idle", "quiet", "person", "stale"):
            r = dict(r, state=r.get("was") or r["state"], why=r.get("was_why") or r["why"]) if r["state"] == "stale" else r
            groups.setdefault(group_of(r), []).append(r)
    if not groups:
        return "Nothing is still open: no batch to put to the user."
    out = ["OPEN BATCH: %d row(s) still open, in %d group(s). Put them to the user ONCE, one question per group, "
           "recommended option first: keep (waiting for what) / start (one worker for the group) / drop."
           % (sum(len(g) for g in groups.values()), len(groups))]
    ranked = sorted(groups.items(), key=lambda g: -max(r.get("score", 0) for r in g[1]))
    for n, (group, rows) in enumerate(ranked, 1):
        rows.sort(key=lambda r: -(r["age"] or 0))
        out.append("%d. %d %s: keep / start / drop. Keys: %s" % (n, len(rows), group_title(group, rows, found["days"])[0],
                                                                  ",".join(r["key"] for r in rows)))
        out += ["   - %s %s: %s" % (r["key"], span(r["age"]), cell(r["what"], 110)) for r in rows[:12]]
        out += ["   - and %d more (`audit --all`)" % (len(rows) - 12)] * (len(rows) > 12)
    out.append("Record each answer for the whole group: start: start its worker, then `set <keys> started --session "
               "<id>`; keep: `set <keys> parked --hours <N>`; drop: `set <keys> dropped \"<why>\"`.")
    return "\n".join(out)


def cmd_audit(args):
    ledger = os.path.expanduser(args.ledger or gt.require_ledger())
    queues = args.queue or (load_state(ledger).get("quick") or {}).get("queues") or ()
    if args.open_batch:
        print(open_batch(run(ledger, args.days, False, queues)))
        return 0
    found = run(ledger, args.days, not args.quick, queues)
    print("AUDIT %s, last %g days%s" % (time.strftime(gt.TIME_FORMAT, time.localtime(found["at"])), args.days,
                                        " (quick: the ledger, and the last full audit's sessions)" if args.quick else ""))
    print(render(found, args.limit, args.all, args.group))
    print(summary(found))
    print("State file: %s" % state_paths(ledger)[1])
    return 0


def cmd_state(args):
    ledger = os.path.expanduser(args.ledger or gt.require_ledger())
    run(ledger, full=False, queues=(load_state(ledger).get("quick") or {}).get("queues") or ())
    print(open(state_paths(ledger)[1]).read())
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Audit the guide's work: decided, landed, verified.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="list work that is not done or not verified")
    a.add_argument("ledger", nargs="?")
    a.add_argument("--days", type=float, default=DAYS)
    a.add_argument("--quick", action="store_true", help="the ledger and queue files only, no transcripts")
    a.add_argument("--all", action="store_true", help="every item, not collapsed, with the moving, asked, parked and backlog ones")
    a.add_argument("--limit", type=int, default=TOP, help="how many rows of the table to print (default %d)" % TOP)
    a.add_argument("--group", metavar="KEY", help="list the items inside one collapsed row (a key ending +N)")
    a.add_argument("--queue", action="append", help="a markdown table of approved work; repeatable; remembered")
    a.add_argument("--open-batch", action="store_true",
                   help="the rows still open, grouped by stream, for one keep / start / drop question per group")
    s = sub.add_parser("set", help="mark an audit item: asked, started, parked, done or dropped")
    s.add_argument("key")
    s.add_argument("state", choices=STATES)
    s.add_argument("evidence", nargs="?", help="done / dropped: how it was verified or why; written into the row")
    s.add_argument("--session", help="started: the worker that has it")
    s.add_argument("--hours", type=float, help="asked / parked: for this long (asked: default %d)" % ASKED_HOURS)
    s.add_argument("--note")
    s.add_argument("--ledger")
    k = sub.add_parser("strike", help="apply a strike sweep's `<key> | DONE / SUPERSEDED / OPEN | <evidence>` lines")
    k.add_argument("--from", dest="from_file", required=True, metavar="FILE")
    k.add_argument("--ledger")
    st = sub.add_parser("state", help="refresh and print STATE.md")
    st.add_argument("ledger", nargs="?")
    args = p.parse_args(argv)
    return {"audit": cmd_audit, "set": cmd_set, "strike": cmd_strike, "state": cmd_state}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
