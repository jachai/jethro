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
STATES = ("asked", "started", "parked", "done", "dropped")
TICKET = re.compile(r"(?<![\w-])(?:[A-Z]{1,6}-\d{1,6}|#\d{2,6}|v\d+\.\d+\.\d+)\b")
FINISHED = re.compile(r"^\W*(?:done|dropped|closed|resolved|superseded|moot|fixed|shipped|merged|verified|cancell?ed|n/a)\b",
                      re.I)
PARKED = re.compile(r"\b(?:later|parked|not now|at cutover|at step|backlog|someday)\b", re.I)
ANSWER = re.compile(r"\b(?:done|closed?|closes|dropped|drop|no port|stays?|not now|leave|skip|relayed|keep|let it run|"
                    r"backlog|no plan|declined|superseded)\b", re.I)
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
        if any(FINISHED.match(c) for c in cells[1:]):
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
    return "idle", "owner %s" % (item["owner"][:30] or "none")


def span(seconds):
    if seconds is None:
        return "undated"
    return "%.0f h" % (seconds / 3600) if seconds < 36 * 3600 else "%.1f d" % (seconds / 86400)


def unverified(ledger, tables, days, full, now):
    found = []
    follow = gt.followups(ledger, days, full, now)
    for t in follow["propose"]:
        found.append(dict(key=item_key(t["key"]), kind="unverified", what="%s %s: %s" % (t["key"], t["where"], t["evidence"]),
                          age=now - t["date"] if t["date"] else None, state="unverified", why="no verification",
                          next="start a read-only 'verify %s'" % t["key"]))
    due = {gt.thing_key(r["thing"]) for r in follow["recheck"]}
    for key, row in gt.verification_rows(ledger).items():
        result, age = row["result"].lower().replace(" ", "-"), age_of(row["checked"], now)
        stale = result == "running" and (age is None or age > 86400)
        if key in due or result in ("proposed", "broken") or stale:
            found.append(dict(key=item_key(key), kind="unverified", what="%s (%s): %s" % (row["thing"], row["where"], row["evidence"]),
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
            found.append(dict(key=rid, kind="waiting", what="%s: %s" % (row["session"], row["what"]), age=now - asked,
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
        out.append(dict(key="D" + number, kind="decision", what="Decision %s: %s" % (number, text.strip("* ")), age=age,
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


def session_rows(ledger, tables, days, now):
    """Sessions of the last `days` that didn't end cleanly: no result line, a result that says it isn't finished, or a
    result naming a PR the ledger never says was merged. Returns (rows, how many ended cleanly)."""
    levels, paths = gt.session_levels(ledger), transcripts(now - days * 86400)
    landed = {h["key"] for h in gt.ledger_hits(ledger, 0, now)}
    verified = gt.verification_rows(ledger)
    waiting, rows, clean = gt.waiting_rows(ledger), [], 0
    for rid, (path, at) in paths.items():
        level, cell = levels.get(rid, ("", ""))
        sid = os.path.basename(path)[:-6]
        content = gt.marker_content(sid)
        if not level or level in ("IGNORED", "RETIRED") or (content is not None and content not in gt.WORKER_MARKERS + (gt.DONE,)):
            continue
        idle = now - at
        if idle < QUIET_HOURS * 3600 or (gt.job_state(sid) == "working" and gt.session_alive(sid)) or rid in waiting:
            continue  # still running, or settled as waiting on the user: `settle` has it
        result, spoke = last_result(path)
        prs = [t for t in tickets(result) if t.startswith("#")]
        why = ("no result line" if not result else "result says not finished" if NOT_DONE.search(result) else
               "%s: no merge in the ledger" % ", ".join(prs) if prs and not set(prs) & landed else
               "%s landed, no verification" % ", ".join(prs) if prs and not any(p in verified for p in prs) else "")
        if not why or not spoke:
            clean += bool(spoke)
            continue
        name = re.sub(r"\s*\[[0-9a-fA-F]{6,36}\].*", "", cell).strip("' ") or "untitled"
        rows.append(dict(key=rid, kind="session", age=idle, state="session", why=why,
                         what="'%s' meant: %s; ended: %s" % (name[:40], first_prompt(path)[:70] or "?", result[:90] or "—"),
                         next="peek %s; finish it, hand it on, or note why not" % rid))
    return rows, clean


def audit(ledger, days=DAYS, full=True, queues=(), now=None):
    """The audit as a dict: rows (not done or not verified, oldest first), every item by state, and the counts."""
    now = now or time.time()
    tables, lines = sections(ledger)
    marks = load_state(ledger).get("items") or {}
    waiting = gt.waiting_rows(ledger)
    live = live_sessions(tables, now, transcripts(now - 30 * 86400))
    work, hidden = [], []
    for item in open_items(tables, now) + queue_items(queue_paths(lines, queues), now):
        state, why = classify(item, marks, live, waiting, now)
        if state is None:
            continue
        item.update(state=state, why=why, next={
            "idle": "ask now: start it / keep waiting / drop" if item["age"] is None or item["age"] > idle_hours() * 3600
            else "propose a start", "quiet": "peek the worker; restart it or start a successor"}.get(state, ""))
        if state in ("idle", "quiet") and item["kind"] == "open" and (item["age"] is None or item["age"] > days * 86400):
            item.update(state="stale", why="open %s, %s" % ("with no date" if item["age"] is None else "for " + span(item["age"]), why))
        (work if item["state"] in ("idle", "quiet") else hidden).append(item)
    rows = work + unverified(ledger, tables, min(days, gt.FOLLOWUP_DAYS), full, now) + long_waits(waiting, now)
    rows += decisions(lines, tables, now)
    clean = None
    if full:
        sessions, clean = session_rows(ledger, tables, days, now)
        rows += sessions
    order = ("open", "queue", "unverified", "waiting", "session", "decision")
    rows.sort(key=lambda r: (order.index(r["kind"]) if r["kind"] not in ("open", "queue") else 0,
                             -(r["age"] if r["age"] is not None else 1e12)))
    ages = [r["age"] for r in work if r["age"] is not None]
    nag = [r for r in work if r["age"] is None or r["age"] > idle_hours() * 3600]
    count = lambda kind: sum(r["kind"] == kind for r in rows)  # noqa: E731
    return dict(rows=rows, hidden=hidden, nag=nag, clean=clean, at=now, full=full, days=days,
                counts=dict(idle=len(work), oldest=max(ages) if ages else None, nag=len(nag),
                            unverified=count("unverified"), waiting=count("waiting"), decisions=count("decision"),
                            sessions=count("session"), **{s: sum(h["state"] == s for h in hidden)
                                                          for s in ("moving", "asked", "parked", "stale")}))


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
    text += "; not listed: %d moving, %d asked, %d parked" % (c["moving"], c["asked"], c["parked"])
    if c["stale"]:
        text += ". Backlog: %d Open items row(s) older than %g days are still open: one interview question to close, " \
                "drop or re-queue them in bulk (`audit --all` lists them)" % (c["stale"], found["days"])
    return text


def cell(text, width):
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= width else text[:width - 1] + "…"


def render(found, limit=40, everything=False):
    rows, more = [], []
    caps = {"open": limit // 2, "queue": limit // 2, "unverified": limit // 4, "session": limit // 4,
            "decision": limit // 5, "waiting": limit // 8}
    for r in found["rows"]:  # each kind gets its share of the table, so one long list can't push the others out
        group = "open" if r["kind"] == "queue" else r["kind"]
        caps[group] -= 1
        (rows if caps[group] >= 0 or everything else more).append(r)
    rows += found["hidden"] if everything else []
    out = ["| Key | Age | Kind | What | Why | Next action |", "|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| %s | %s | %s | %s | %s | %s |" % (r["key"], span(r["age"]), r["state"] if r["kind"] in ("open", "queue")
                                                       else r["kind"], cell(r["what"], 110), cell(r["why"], 40),
                                                       cell(r.get("next") or "—", 50)))
    if more:
        out.append("… and %d more (--all, or a higher --limit): %s" % (len(more), ", ".join(
            "%d %s" % (sum(r["kind"] == k for r in more), k) for k in sorted({r["kind"] for r in more}))))
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
    out += ["", "## Not done or not verified", summary(found), "", render(found, 40), ""]
    save(state_paths(ledger)[1], "\n".join(out))


def run(ledger, days=DAYS, full=True, queues=()):
    """Run the audit, write STATE.md and audit.json, and return what was found. The full audit keeps its session rows
    in the cache, so a quick refresh in between doesn't lose them."""
    found = audit(ledger, days, full, queues)
    state = load_state(ledger)
    if full:
        state["full_at"] = found["at"]
        state["sessions"] = [r for r in found["rows"] if r["kind"] == "session"]
    state["quick"] = dict(at=found["at"], counts=found["counts"], queues=list(queues) or (state.get("quick") or {}).get("queues") or [],
                          nag=["%s %s: %s (%s)" % (r["key"], span(r["age"]), cell(r["what"], 100), r["why"])
                               for r in sorted(found["nag"], key=lambda r: -(r["age"] or 1e12))[:6]])
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
                     "(%d idle in all, oldest %s):\n%s\nPut each in this turn's interview, recommended option first: "
                     "start it now / keep waiting for <what> / drop. Then record it: start a worker and `python3 %s set "
                     "<key> started --session <id>`, or `set <key> asked` / `parked --hours N` / `dropped`. `python3 %s "
                     "audit` prints the whole table." % (counts["nag"], idle_hours(), counts.get("idle", 0),
                                                         span(counts.get("oldest")), "\n".join("- " + l for l in quick.get("nag") or []), me, me))
    if now - state.get("full_at", 0) > hours * 3600:
        parts.append("session-guide audit: the look back over past sessions is due (last full audit %s). On this wake, or "
                     "the first one with nothing due, run `python3 %s audit` and put what it lists into the interview."
                     % (time.strftime(gt.TIME_FORMAT, time.localtime(state["full_at"])) if state.get("full_at") else "never", me))
    return "\n".join(parts) or None


def find_key(ledger, given):
    found = audit(ledger, full=False, queues=(load_state(ledger).get("quick") or {}).get("queues") or ())
    items = found["rows"] + found["hidden"]
    hits = [r for r in items if r["key"].lower() == given.lower()] or [r for r in items if given in r.get("names", ())]
    if len(hits) != 1:
        raise SystemExit("%r names %d audit items; use the 6-character key from `audit --all`" % (given, len(hits)))
    return hits[0]


def cmd_set(args):
    ledger = os.path.expanduser(args.ledger or gt.require_ledger())
    item = find_key(ledger, args.key)
    if args.state == "started" and not args.session:
        raise SystemExit("started needs --session <id>: the worker that has it")
    now = time.time()
    hours = args.hours if args.hours else ASKED_HOURS if args.state == "asked" else 0
    mark = dict(state=args.state, at=now, what=item["what"][:120], note=" ".join((args.note or "").split()))
    if hours:
        mark["until"] = now + hours * 3600
    if args.session:
        mark["session"] = gt.resolve_session(args.session)
    state = load_state(ledger)
    state.setdefault("items", {})[item["key"]] = mark
    save(state_paths(ledger)[0], json.dumps(state, indent=1))
    print("%s %s%s: %s" % (item["key"], args.state, " for %g h" % hours if hours else "", cell(item["what"], 100)))
    if args.state in ("done", "dropped") and item["kind"] == "open":
        print("Also set its Open items row's Status to %s, with how it was verified or why." % args.state.upper())
    run(ledger, full=False)
    return 0


def cmd_audit(args):
    ledger = os.path.expanduser(args.ledger or gt.require_ledger())
    found = run(ledger, args.days, not args.quick, args.queue or (load_state(ledger).get("quick") or {}).get("queues") or ())
    if args.quick:  # the last full audit's session rows still stand
        found["rows"] += [r for r in load_state(ledger).get("sessions") or [] if r not in found["rows"]]
    print("AUDIT %s, last %g days%s" % (time.strftime(gt.TIME_FORMAT, time.localtime(found["at"])), args.days,
                                        " (quick: ledger only)" if args.quick else ""))
    print(render(found, args.limit, args.all))
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
    a.add_argument("--all", action="store_true", help="also list items that are moving, asked or parked")
    a.add_argument("--limit", type=int, default=40)
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
