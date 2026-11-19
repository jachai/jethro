#!/usr/bin/env python3
"""guide_audit: the guide's look back over its whole body of work: what was decided, did it land, was it verified.

    python3 guide_audit.py audit [<ledger>] [--days 5] [--quick] [--all] [--queue <file.md>]...
    python3 guide_audit.py set <key> <asked | started | parked | done | dropped> [--session <id>] [--hours N] [--note "…"]
    python3 guide_audit.py state [<ledger>]        print the live-state file (STATE.md), refreshed first

audit reads the ledger's tables (never its log) and, unless --quick, the transcripts of the ledger's sessions from the
last --days, and prints a short table of work that is NOT done or NOT verified, oldest first, each with a next action:

- idle      an Open items row, or a row of a queue file, that is still open with no live worker and no question to
            the user. A queue file is any markdown table of approved work (a fix queue): name it on a `Queues:` line
            in the ledger's first lines (comma-separated paths), in SESSION_GUIDE_QUEUES, or with --queue.
- quiet     the same, but its worker (the `[id6]` in its Owner cell, a `set <key> started` session, or a live Sessions
            row naming the same ticket or PR) has gone quiet for 2 h or is closed.
- unverified  what `guide_title.py followups` lists (landed, no Verifications row; "not-exercised" past its re-check),
            plus Verifications rows left proposed, broken, or running for over a day.
- waiting   a reminder asked over a day ago that is still open: the gate may never open by itself.
- decision  a decision of the last 3 days that nothing else in the ledger refers to (no Sessions row, Open item,
            reminder or later note names "D<N>" / "Decision <N>"), unless its words say it was an answer, not work.
- session   (full audit only) a session of the last --days that ended with no `result:` line, with a result that says
            it isn't finished (blocked, waiting, draft, needs …), or naming a PR the ledger never says was merged.

Rows the audit counts as moving (a live worker), asked (a pending question, or `set <key> asked`) or parked
(`set <key> parked`, or the row's own words: "later", "not now", "at cutover") are counted, and listed only with --all.

Every run writes two files next to the ledger: STATE.md, a few KB of live state (guide, open sessions, reminders,
results with no verdict, this table), which a takeover reads instead of the ledger's log; and audit.json, the `set`
marks and the counts the title hook shows ({idle} and {oldest}). The hook refreshes the quick audit on a guide's
prompt (at most every 10 minutes), nags when an idle item is older than SESSION_GUIDE_IDLE_HOURS (default 12) with no
question to the user, and says when the full audit is due (SESSION_GUIDE_AUDIT_HOURS, default 12; 0 turns both off).
`guide_title.py mark` (a takeover) runs the full audit; `retire` and `settle` refresh the quick one.

A key is the 6 hex characters in the table's first column (a hash of the item's words), or a ticket / PR in the item
when only one item names it. Python 3 stdlib only.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guide_title as gt  # noqa: E402

__version__ = "0.1.19"
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
VALUE = {"broken": 6, "waiting": 6, "idle": 3, "quiet": 3, "person": 2, "unverified": 2, "unfinished": 2,
         "recheck": 1, "proposed": 1, "decision": 1, "noresult": 1, "backlog": 1}
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
NOT_DONE = re.compile(r"\b(?:blocked|waiting|waits|needs?|pending|partial|handed off|push ready|publish ready|draft|"
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
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


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
        owner, status = cells[1], cells[-1] if len(cells) > 2 else ""
        if any(FINISHED.match(c) for c in cells[1:]) or STRUCK.match(cells[0]):
            continue
        if age is None:
            age = age_of(status, now)
        if age is None:
            age = age_of(" ".join(cells), now)
        found.append(dict(key=item_key(cells[0]), kind="open", what=cells[0], owner=owner, age=age,
                          names=names(cells[0]), keys=set(re.findall(r"\[([0-9a-f]{6})\]", " ".join(cells[1:]))),
                          parked=bool(PARKED.search(" ".join(cells[1:])))))
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
            found.append(dict(key=item_key(what), kind="queue", what=what, owner=os.path.basename(path),
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
    """{id6: {cell, level, idle, moving, tickets}} for the Sessions rows at MANAGED, WATCHED or ACTIVE, not closed."""
    closed, found = gt.closed_ids(), {}
    for cells in table(tables, "## Sessions"):
        rid = gt.row_id(cells[0]) if len(cells) > 1 else None
        level = re.match(r"[A-Za-z]*", cells[1]).group() if rid else ""
        if not rid or rid in found or rid in closed or level not in ("MANAGED", "WATCHED", "ACTIVE"):
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
    if not worker:
        worker = next((rid for rid, s in live.items() if named_in(refs, s["text"])), None)
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
    """The name an Owner cell starts with: "Jonathan (glance)" and "Jonathan, after the merge" are both Jonathan."""
    name = re.split(r"\s*[(\[,;:/+]|\s+(?:after|then|when|tells?|to)\b|\s+\d", owner.strip("' "))[0].strip()[:24]
    return "the user" if name.lower() in ("ask", "user", "the user") else name or "its owner"


def owner_head(owner):
    """What Owner cells share when they mean one worker: "new session (proposed), sonnet" is "new session"."""
    return " ".join(re.split(r"\s*[(\[,;]|:\s", owner.strip("' "))[0].lower().split())[:40] or "nobody"


def span(seconds):
    if seconds is None:
        return "undated"
    return "%.0f h" % (seconds / 3600) if seconds < 36 * 3600 else "%.1f d" % (seconds / 86400)


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
            same = re.match(r"\W*see (\S+)", row["evidence"])  # "see #5555 (same verification)": one break, one row
            found.append(dict(key=item_key(key), kind="unverified", label=row["thing"].split()[0] if row["thing"] else key,
                              tier=result if result in ("proposed", "broken") else "recheck" if key in due else "unverified",
                              same=item_key(gt.thing_key(same.group(1))) if same else None,
                              what="%s (%s): %s" % (row["thing"], row["where"], row["evidence"]),
                              age=age, state="unverified", why=result + (" (re-check due)" if key in due else ""),
                              next={"broken": "start a fix", "proposed": "ask, then start its verify session"}
                              .get(result, "re-check on real data")))
    return found


def long_waits(waiting, now):
    found = []
    for rid, row in waiting.items():
        asked = gt.read_time(row["asked"])
        if asked and now - asked > WAITING_HOURS * 3600:
            at = gt.read_time(row["remind"])
            found.append(dict(key=rid, kind="waiting", tier="waiting", what="%s: %s" % (row["session"], row["what"]), age=now - asked,
                              state="waiting", why="due now" if at <= now else "asleep until " + row["remind"],
                              next="re-ask, or build around it"))
    return found


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
    work, hidden = [], []
    for item in open_items(tables, now) + queue_items(queue_paths(lines, queues), now):
        found, why = classify(item, marks, live, waiting, now)
        if found is None:
            continue
        late = item["age"] is None or item["age"] > idle_hours() * 3600
        item.update(state=found, why=why, tier=found, next={
            "idle": "ask now: start it / keep waiting / drop" if late else "propose a start",
            "person": "ask %s in this turn's interview, then `waiting ask`" % person(item["owner"]),
            "quiet": "peek the worker; restart it or start a successor"}.get(found, ""))
        if found in ("idle", "quiet", "person") and item["kind"] == "open" and (
                item["age"] is None or item["age"] > 2 * days * 86400):
            item.update(state="stale", tier="backlog", was=found, why="open %s, %s" % (
                "with no date" if item["age"] is None else "for " + span(item["age"]), why))
        (work if item["state"] in ("idle", "quiet", "person") else hidden).append(item)
    other = unverified(ledger, tables, min(days, gt.FOLLOWUP_DAYS), full, now) + long_waits(waiting, now)
    other += decisions(lines, tables, now)
    clean = None
    if full:
        sessions, clean = session_rows(ledger, tables, days, now)
    else:  # the last full audit's session rows still stand
        sessions = [dict(r, age=now - r["ended"]) for r in state.get("sessions") or [] if r.get("ended")]
    checked = {t for r in other if r["kind"] == "unverified" for t in tickets(r["what"])}
    other += [r for r in sessions if not (r.get("prs") and set(r["prs"]) <= checked)]  # those PRs are rows already
    rows = list(work)
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
    count = lambda kind: sum(r["kind"] == kind for r in rows)  # noqa: E731
    found = dict(rows=rows, hidden=hidden, nag=nag, clean=clean, at=now, full=full, days=days,
                 counts=dict(idle=len(work), oldest=max(ages) if ages else None, nag=len(nag),
                             unverified=count("unverified"), waiting=count("waiting"), decisions=count("decision"),
                             sessions=count("session"), **{s: sum(h["state"] == s for h in hidden)
                                                           for s in ("moving", "asked", "parked", "stale")}))
    found["top"] = collapse(found)
    return found


def group_of(row):
    """What a row collapses with: rows that share one next action become one row of the table."""
    if row["state"] == "stale":
        return ("backlog",)
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
}


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
        title, action = GROUPS[group[0]]
        title %= dict(old=2 * found["days"], owner=first.get("owner", "") if first["kind"] == "queue" else
                      owner_head(first.get("owner", "")), person=person(first.get("owner", "")),
                      gone=first["why"] if group[-1] != "gone" else "worker is closed or gone")
        names = []
        for r in rows:
            names += [label(r)] if label(r) not in names else []
        out.append(dict(key="%s+%d" % (first["key"], len(rows) - 1), kind=first["kind"], state=first["state"],
                        age=max(dated) if dated else None, members=rows, next=action,
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
    return text + "; not listed: %d moving, %d asked, %d parked" % (c["moving"], c["asked"], c["parked"])


def cell(text, width):
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= width else text[:width - 1] + "…"


def line(r, wide=110):
    return "| %s | %s | %s | %s | %s | %s |" % (
        r["key"], span(r["age"]), "backlog" if r["state"] == "stale" else r["kind"] if r["state"] in (
            "unverified", "waiting", "decision", "session") else r["state"],
        cell(r["what"], wide if len(r.get("members") or ()) < 2 else wide + 60), cell(r["why"], 40), cell(r.get("next") or "—", 64))


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


def state_file(ledger, found):
    """STATE.md: the live state a takeover reads instead of the ledger's log."""
    now = found["at"]
    tables, lines = sections(ledger)
    head = [l for l in lines[:8] if l.startswith(("# ", "Guide:", "Scope:", "Other guides:", "Queues:"))]
    out = head + ["", "Generated %s by guide_audit.py (%s audit); do not edit, it is rewritten on every guide prompt. "
                  "The ledger's tables hold the detail." % (time.strftime(gt.TIME_FORMAT, time.localtime(now)),
                                                           "full" if found["full"] else "quick"), ""]
    live = live_sessions(tables, now, transcripts(now - 30 * 86400))
    out += ["## Open sessions (%d)" % len(live)]
    out += ["- %s %s, %s" % (cell(s["cell"], 70), s["level"], "running" if s["moving"] else
                             "quiet " + span(s["idle"]) if s["idle"] is not None else "no transcript")
            for s in list(live.values())[:25]] + ["- and %d more" % (len(live) - 25)] * (len(live) > 25)
    settle = gt.settle_status(ledger, os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    results = gt.results_status(ledger)["due"]
    out += ["", "## Reminders (%d due, %d asleep)" % (len(settle["due"]), len(settle["asleep"]))]
    out += ["- %s %s: %s" % ("DUE" if r in settle["due"] else "until " + r["remind"], cell(r["session"], 40),
                             cell(r["what"], 150)) for r in (settle["due"] + settle["asleep"])[:20]]
    out += ["", "## Results with no verdict (%d)" % len(results)]
    out += ["- " + cell(gt.describe_result(r), 200) for r in results[:12]]
    out += ["", "## Not done or not verified (top %d by value x age)" % (2 * TOP), summary(found), "", render(found, 2 * TOP), ""]
    save(state_paths(ledger)[1], "\n".join(out))


def run(ledger, days=DAYS, full=True, queues=()):
    """Run the audit, write STATE.md and audit.json, and return what was found. The full audit keeps its session rows
    in the cache, so a quick refresh in between doesn't lose them."""
    found = audit(ledger, days, full, queues)
    state = load_state(ledger)
    if full:
        state["full_at"] = found["at"]
        state["sessions"] = [dict(r, names=None) for r in found["rows"] + found["hidden"] if r["kind"] == "session"]
    late = {r["key"] for r in found["nag"]}
    state["quick"] = dict(at=found["at"], counts=found["counts"], queues=list(queues) or (state.get("quick") or {}).get("queues") or [],
                          nag=["%s %s: %s -> %s" % (r["key"], span(r["age"]), cell(r["what"], 130), r.get("next") or "ask")
                               for r in found["top"] if any(m["key"] in late for m in r["members"])][:5])
    try:
        save(state_paths(ledger)[0], json.dumps(state, indent=1))
        state_file(ledger, found)
    except OSError:
        pass
    return found


def cached(ledger):
    """The counts of the last audit ({idle, oldest, nag, ...}), or {} when none ran. Reads one small file."""
    return (load_state(ledger).get("quick") or {}).get("counts") or {}


def hook_context(ledger):
    """What the guide hears on its prompt: the idle items it owes the user a question about, and a due full audit."""
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
    if counts.get("nag"):
        parts.append("session-guide audit: %d decided item(s) have no worker and no question to the user for over %g h "
                     "(%d idle in all, oldest %s). The top ones by value x age:\n%s\nPut each in this turn's interview, "
                     "recommended option first: start it now / keep waiting for <what> / drop. Then record it: start a "
                     "worker and `python3 %s set <key> started --session <id>`, or `set <key> asked` / `parked --hours N` "
                     "/ `dropped`. `python3 %s audit` prints the top 10 of everything." % (counts["nag"], idle_hours(), counts.get("idle", 0),
                                                         span(counts.get("oldest")), "\n".join("- " + l for l in quick.get("nag") or []), me, me))
    if now - state.get("full_at", 0) > hours * 3600:
        parts.append("session-guide audit: the look back over past sessions is due (last full audit %s). On this wake, or "
                     "the first one with nothing due, run `python3 %s audit` and put what it lists into the interview."
                     % (time.strftime(gt.TIME_FORMAT, time.localtime(state["full_at"])) if state.get("full_at") else "never", me))
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
    for item in items:
        mark = dict(state=args.state, at=now, what=item["what"][:120], note=" ".join((args.note or "").split()))
        if hours:
            mark["until"] = now + hours * 3600
        if args.session:
            mark["session"] = gt.resolve_session(args.session)
        state.setdefault("items", {})[item["key"]] = mark
        print("%s %s%s: %s" % (item["key"], args.state, " for %g h" % hours if hours else "", cell(item["what"], 100)))
    save(state_paths(ledger)[0], json.dumps(state, indent=1))
    if args.state in ("done", "dropped") and any(item["kind"] == "open" for item in items):
        print("Also set the Status of each Open items row to %s, with how it was verified or why." % args.state.upper())
    run(ledger, full=False, queues=(state.get("quick") or {}).get("queues") or ())
    return 0


def cmd_audit(args):
    ledger = os.path.expanduser(args.ledger or gt.require_ledger())
    found = run(ledger, args.days, not args.quick, args.queue or (load_state(ledger).get("quick") or {}).get("queues") or ())
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
    s = sub.add_parser("set", help="mark an audit item: asked, started, parked, done or dropped")
    s.add_argument("key")
    s.add_argument("state", choices=STATES)
    s.add_argument("--session", help="started: the worker that has it")
    s.add_argument("--hours", type=float, help="asked / parked: for this long (asked: default %d)" % ASKED_HOURS)
    s.add_argument("--note")
    s.add_argument("--ledger")
    st = sub.add_parser("state", help="refresh and print STATE.md")
    st.add_argument("ledger", nargs="?")
    args = p.parse_args(argv)
    return {"audit": cmd_audit, "set": cmd_set, "state": cmd_state}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
