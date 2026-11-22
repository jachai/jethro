#!/usr/bin/env python3
"""guide_title: keep the guide session's title pinned, with live counts from its ledger, and mark guided workers.

    python3 guide_title.py mark <ledger.md> [--session <id>]   this session is a guide
    python3 guide_title.py unmark [--session <id>]             it no longer is
    python3 guide_title.py retire [<id>] [--to <uds:socket>] [--force | --check]
                                                               it handed over: faded red title, never red again
    python3 guide_title.py guided [<id>]                       a MANAGED worker: orange blocks + "(g) " first
    python3 guide_title.py launch [--watched] -- <claude args…>
                                                               start a worker with `claude --bg`, marked guided at once
                                     [--stream <key> | --successor-of <id>] its stream (project) icon, or the one its
                                                               predecessor had
    python3 guide_title.py stream add | assign | end | list …  streams and their icons (guide_streams.py)
    python3 guide_title.py reconcile [--ledger <ledger.md>]    open rows whose session ended, blocked or handed off
    python3 guide_title.py watched [<id>]                      a WATCHED session: light gray blocks first
    python3 guide_title.py active [<id>]                       running, not managed or watched: blue blocks first
    python3 guide_title.py unguided [<id>]                     no longer managed or watched: the prefix comes off
    python3 guide_title.py unwatched [<id>]                    the same as unguided
    python3 guide_title.py done [<id>]                         closed: "✅ " before its title, never orange again
    python3 guide_title.py sweep [<ledger>] [--hours 12]       list recently active sessions the ledger doesn't have
    python3 guide_title.py settle [<ledger>] [--idle-hours 2]  which sessions aren't settled, which reminders are due
    python3 guide_title.py waiting <id> "<what the user does>" it waits on the user: a reminder, due now
    python3 guide_title.py waiting ask "<question>" [--hours N | --at "YYYY-MM-DD HH:MM"]
                                                               the guide owes the user a question: a reminder row
                                     [--closes pr:#N | result:<artifact id> | ticket:<ID> | session:<id8>] ...
                                                               (either form) the reminder closes itself when it happens
    python3 guide_title.py claim merge | run | done | list ... merges and commands asked of someone (guide_claims.py)
    python3 guide_title.py sleep <id> <hours>                  put that reminder off
    python3 guide_title.py unwait <id>                         it no longer waits on the user: the reminder goes
    python3 guide_title.py result "<deliverable>" <link> [--from "<title [id6]>"]
                                                               a finished deliverable for the user: asks for a verdict
    python3 guide_title.py result-answer "<deliverable>" <satisfied | change | drop | not-looked> [--note "…"]
                                                               [--every <hours>]   the user's verdict (not-looked: ask again)
    python3 guide_title.py followups [<ledger>] [--days 3] [--reviewed]   recent fixes/deployments with no verification
    python3 guide_title.py verification <thing> <result> ["<evidence>"]   record one: proposed, running, verified,
                                                               not-exercised (re-check in 24 h), broken or skipped
    python3 guide_title.py hook                                UserPromptSubmit / SessionStart hook (JSON on stdin)

A marked session gets this title on every prompt and every start, so a rename (by hand or by another titling hook)
is undone on the next turn:

    🟥🟥 Sessions Manager · release-guide (2 managed · 1 watched · 3 active · 1 new) 🟥🟥

managed, watched and active count those rows in the ledger's `## Sessions` table; new is the live count of sessions
active in the last 12 hours with no row there (see sweep). To pick your own format, set SESSION_GUIDE_TITLE (for
hooks: in settings.json "env") with {managed}, {watched}, {active}, {new} and {tracked} (managed + watched)
placeholders, {idle_note} (" · 15 idle 4d" when the last audit found decided work with no worker, else empty; or
{idle} and {oldest} on their own), plus {slug} (the ledger's folder name) and {host} (this machine's short host name), which tell two
guides apart when Remote Control shows another machine's sessions too. A format without them still works. Avoid `*`: some title tools strip markdown. Keep
the "🟥🟥 Sessions Manager" start if you use claude-top: it falls back to it for a session without a marker. The
marker is
$CLAUDE_CONFIG_DIR/session-guide/guides/<session id> (default ~/.claude), holding the ledger path. The hook fails
open: an unmarked session, a missing or unreadable ledger, or bad input prints nothing and exits 0.

Every title kind has its own color, so the agents view reads at a glance:

    🟥🟥 Sessions Manager (...) 🟥🟥              the active guide
    🎟️🎟️ Sessions Manager (retired) 🎟️🎟️         a retired guide (no pale red square exists; closest)
    ⬜⬜ design spike · Reading the diff          a WATCHED session: not managed, only watched
    🟦🟦 notes cleanup · Tidying the index        an ACTIVE session: running, not managed or watched
    🟧🟧 (g) billing lead · Waiting on CI         a MANAGED (guided) session

A retired guide (one that handed over to a new guide) gets RETIRED_TITLE instead, on its next prompt and from then on
(override: SESSION_GUIDE_RETIRED_TITLE). Its marker holds `retired`, so the hook can't turn it red again, and on every
prompt the hook tells it that it is retired: forward each message it gets to the new guide's socket (`--to`, else the
caller's own socket when the new guide retires the old one, else the live guide of the same ledger) and do not act.
`retire` is a gate: it runs reconcile (guide_reconcile.py) on the guide's ledger and exits 1, retiring nothing, while
any open row needs the guide (a handoff with no successor, an ended or blocked worker, an undelivered or inbox
report). `--force` retires anyway and writes those rows into the ledger's `## Handoff` table for the next guide;
`--check` only runs the gate. Either way it prints GUIDE_CHANGE, the one line to send each MANAGED worker.

`launch` starts a worker so that its marker is in place before its first tool call (agent-guard reads the marker to
tell a guide-managed session from any other). `claude --bg` picks its own session id (it ignores --session-id, and
--resume of an unknown id fails), so for a new session the marker is written the moment `claude --bg` prints the id,
while the worker's first model call is still in flight; with `--resume <id>` it is written before the command runs.

Every prompt of a live guide starts with "Now: <local date, time and zone>": a guide's own guess of the time drifts.

A guided worker (marker `guided`) keeps its own title with GUIDED_PREFIX in front (override:
SESSION_GUIDE_GUIDED_PREFIX), so the user can tell at a glance which sessions don't need them. The hook prefixes the
title the session has now and prints nothing once it is prefixed. Repeated prefixes collapse to one, and a title
still carrying the bare "(g) " of older versions is upgraded. A watched session (marker `watched`) gets WATCHED_PREFIX
the same way (override: SESSION_GUIDE_WATCHED_PREFIX), and so does an active one (marker `active`, ACTIVE_PREFIX,
override: SESSION_GUIDE_ACTIVE_PREFIX); `guided`, `watched` and `active` swap one prefix for another. `unguided`
(marker `unguided`) takes any of them off on the next prompt, after which the hook drops the marker. A guide or a
retired guide is never prefixed: all three refuse them, and `mark` replaces their markers.

sweep lists sessions whose transcript changed in the window and that have no row in the ledger's `## Sessions` table,
leaving out this session, closed sessions, guides and `claude -p` runs. On every prompt the hook gives a guide that
list as additionalContext, until each session has a row, so a new session can't slip by unasked.

A closed session (marker `done`, from `done <id>`: the guide closed a finished or obsolete worker) gets DONE_PREFIX in
place of the guided prefix (override: SESSION_GUIDE_DONE_PREFIX), the same way. `guided`, `watched`, `active` and `mark`
refuse it, so it is never orange, gray, blue or red again; `done` refuses a guide or a retired guide (retire a guide instead).
A session on a stream (`stream assign`, `launch --stream`; guide_streams.py, its docstring is the spec) has the stream's
icon right after its prefix: "🟧🟧 (g) 🏠 billing lead". A session on no stream keeps the same title as without streams.
The session-titles plugin answers the same hook events later and its title wins, so the prefix also goes into its
stored origin ($CLAUDE_CONFIG_DIR/session-titles/<session id>.json), whenever a marker is written and on every prompt:
then both hooks give the same title. Guides and retired guides get its `off` flag instead. No state file, no change.

Every MANAGED or WATCHED session has to settle: either it waits on the user (a row in the ledger's `## Waiting on ...`
table, whose Remind at says when to ask again; `sleep` moves it) or it is closed (`done`, which also removes that row).
settle lists the sessions quiet for --idle-hours that are neither, and the reminders that are due; the hook gives a guide
both on every prompt. A running session, and one whose reminder sleeps, is left alone. Quiet is the slow signal; the
fast one is reconcile (guide_reconcile.py, its docstring is the spec): a MANAGED or WATCHED row whose job ended more
than 3 minutes ago handed off with no successor row, is blocked with no Waiting row, or (MANAGED) just ended, and the
reports workers left in the ledger's inbox/ folder. The hook, `settle`, `mark` (first, before the audit) and `retire`
print it; `reconcile --ledger <path>` prints it for any ledger and never writes.

Decided work must not sit idle either: guide_audit.py (next to this script; its docstring is the spec) lists the Open
items and queue rows with no worker, the landings nobody verified and the sessions that never finished, ranked, 10
rows at a time. `mark` runs its full audit and prints the table, `settle` ends with it, `retire` refreshes its
STATE.md, the title shows its idle count, and the hook nags a guide whose idle items got no question to the user.

A question the guide owes the user ("ask this afternoon") is a reminder too: `waiting ask "<question>"` writes a row
keyed "owed question [<6 hex chars of the question>]" in the same table, due now or at --hours / --at, so a new guide's
`settle` finds it after a handoff. `sleep` and `unwait` take that key like a session id. `--closes <event>` (either
form, repeatable) appends a "· closes: …" tag that guide_audit.close_tagged() reads: once every event has happened
(the PR merged, the Results row satisfied, the ticket closed in a Decision or Results row, the session DONE) the next
audit removes the reminder and the hook says so. A due reminder that later rows already cover is listed as "likely
done" (the audit's covered() check) in place of the ask, in the hook and in `settle` alike. Whenever this script
writes a Waiting or Results row, or closes a Sessions row, it prints the open rows that share an id with it ("open
rows sharing ids: … Does this replace them?").

results: a finished deliverable the user asked for (a doc, a deck or slide, a review, a report, a release, a PR ready
for them) goes in the ledger's `## Results for you` table with `result`, and stays unanswered until `result-answer`
records the user's verdict: satisfied, change (the worker gets the change; a repeat `result` resets the row), drop, or
not-looked (asked again every --every hours, default 1, until answered). settle and the hook list the unanswered ones
like due reminders. `done` on the worker never removes the row: the deliverable, not the session, waits for the answer.

followups reads the ledger's dated lines from the last --days (a bullet takes the date above it) and what the ledger's
sessions said in their transcripts since then, and lists every PR (#N, or a /pull/N link) and version (vX.Y.Z) a clause
says is ON PROD, on staging, deployed, merged, or (versions only) tagged, released or pushed, unless a "not yet", "once",
"asked" or the like comes just before. Anything with a row in the ledger's `## Verifications` table is left out, except
a "not-exercised" row whose Re-check time has come, which is listed to re-check. The review's cadence is
SESSION_GUIDE_FOLLOWUP_HOURS (default 24, 0 turns it off): `followups --reviewed` writes "Last review:" in that
section, and until the next one is due the hook stays quiet; when it is due and the ledger alone shows something, the
hook tells the guide. `verification` writes or updates the row for a thing (keyed by its first PR or version).

--session (and the <id> of retire / guided / watched / unguided) defaults to $CLAUDE_CODE_SESSION_ID and may be an id
prefix.
Python 3 stdlib only.
"""
import argparse
import calendar
import glob
import json
import os
import re
import socket
import sys
import time

TITLE = ("\U0001f7e5\U0001f7e5 Sessions Manager \u00b7 {slug} ({managed} managed \u00b7 {watched} watched"
         " \u00b7 {active} active \u00b7 {new} new{idle_note}) \U0001f7e5\U0001f7e5")
RETIRED_TITLE = ("\U0001f39f\ufe0f\U0001f39f\ufe0f Sessions Manager (retired)"
                 " \U0001f39f\ufe0f\U0001f39f\ufe0f")
GUIDED_PREFIX = "\U0001f7e7\U0001f7e7 (g) "
WATCHED_PREFIX = "\u2b1c\u2b1c "
ACTIVE_PREFIX = "\U0001f7e6\U0001f7e6 "
DONE_PREFIX = "\u2705 "
RETIRED = "retired"  # marker content for a retired guide, in place of a ledger path
GUIDED, UNGUIDED = "guided", "unguided"  # marker content for a MANAGED worker, and for one that just left
WATCHED, ACTIVE = "watched", "active"  # marker content for a WATCHED session and for an ACTIVE one
WORKER_MARKERS = (GUIDED, WATCHED, ACTIVE, UNGUIDED)
DONE = "done"  # marker content for a session the guide closed
IDLE_HOURS = 2  # a MANAGED or WATCHED session quiet this long has to settle
SLEEP_HOURS = (1, 2, 8, 12, 24, 48)  # the periods the guide offers; `sleep` takes any positive number
TIME_FORMAT = "%Y-%m-%d %H:%M"  # Asked and Remind at: local time
WAITING_TABLE = ["| Session [id6] | What the user needs to do | Asked | Remind at |\n", "|---|---|---|---|\n"]
OWED = "owed question"  # first cell of a waiting row for a question the guide owes the user, then "[<hash6>]"
RESULTS_SECTION = "## Results for you"
RESULTS_TABLE = ["| Deliverable | Link | Delivered | Asked | Answer |\n", "|---|---|---|---|---|\n"]
ANSWERS = ("satisfied", "change", "drop", "not-looked")
RESULT_HOURS = 1  # "haven't looked yet": ask again this often, unless the user picks another cadence
UNANSWERED = "\u2014"  # the Answer cell until the user answers
ASK_AGAIN = re.compile(r"ask again (\d{4}-\d\d-\d\d \d\d:\d\d)(?: \(every ([\d.]+) h\))?")
# What the outgoing guide sends each MANAGED worker, word for word: reports never stop going to the socket.
GUIDE_CHANGE = "Guide changing. Keep sending to this socket; the old guide forwards until the new one introduces itself."
HANDOFF_SECTION = "## Handoff"
HANDOFF_TABLE = ["| Session [id6] | Kind | What is open | Written |\n", "|---|---|---|---|\n"]


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def marker(session_id):
    return os.path.join(config_dir(), "session-guide", "guides", session_id)


def resolve_session(given):
    """A full session id from `given` (an id or id prefix), or this session's own id when no id was passed at all.

    An empty id (say, from a failed lookup) is an error, never this session. A prefix is looked up in every project
    folder, worktree folders included, since a worker that ran EnterWorktree keeps its transcript there.
    """
    sid = (os.environ.get("CLAUDE_CODE_SESSION_ID", "") if given is None else given).strip()
    if not sid:
        raise SystemExit("empty session id" if given is not None else "no session id: pass one")
    if len(sid) == 36:
        return sid
    hits = {os.path.basename(p)[:-6] for p in glob.glob(os.path.join(config_dir(), "projects", "*", sid + "*.jsonl"))}
    if len(hits) != 1:
        raise SystemExit("session %s matches %d sessions; pass the full id" % (sid, len(hits)))
    return hits.pop()


def row_id(cell):
    """The id6 (or longer) in a Sessions row's first cell, as `[3fa9c1]`: its first 6 characters, or None."""
    ids = re.findall(r"\[([0-9a-fA-F]{6,36})\]", cell)
    return ids[-1][:6].lower() if ids else None


def closed_ids():
    """The first 6 characters of every session whose marker says `done`."""
    found = set()
    for path in glob.glob(os.path.join(config_dir(), "session-guide", "guides", "*")):
        try:
            if open(path).read().strip() == DONE:
                found.add(os.path.basename(path)[:6].lower())
        except OSError:
            pass
    return found


def counts(ledger, session_id=""):
    """{managed, watched, active, new, tracked} from the ledger, or None when it has no ## Sessions table.

    managed / watched / active count the Sessions table's rows by Level; new is the live count from untracked();
    tracked is managed + watched. A row whose session is closed (marker `done`) doesn't count, and a session named by
    several rows counts once, at the topmost row's Level. A row with no [id] always counts.
    """
    managed = watched = active = 0
    in_sessions, seen = False, False
    closed, named = closed_ids(), set()
    for line in open(ledger, errors="replace"):
        if line.startswith("## "):
            in_sessions = line.strip() == "## Sessions"
            continue
        if not in_sessions or not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        seen = True
        rid = row_id(cells[0])
        if rid and (rid in closed or rid in named):
            continue
        named.add(rid)
        level = cells[1].split()[0] if cells[1] else ""
        managed += level == "MANAGED"
        watched += level == "WATCHED"
        active += level == "ACTIVE"
    if not seen:
        return None
    idle, oldest = idle_counts(ledger)
    return dict(managed=managed, watched=watched, active=active, new=len(untracked(ledger, session_id)),
                tracked=managed + watched, idle=idle, oldest=oldest,
                idle_note=" \u00b7 %d idle %s" % (idle, oldest) if idle else "")


def audit_module():
    """guide_audit, which lives next to this script and imports it back; None when it can't be loaded."""
    try:
        sys.modules.setdefault("guide_title", sys.modules[__name__])
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import guide_audit
        return guide_audit
    except Exception:
        return None


def reconcile_module():
    """guide_reconcile, which lives next to this script and imports it back; None when it can't be loaded."""
    try:
        sys.modules.setdefault("guide_title", sys.modules[__name__])
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import guide_reconcile
        return guide_reconcile
    except Exception:
        return None


def claims_module():
    """guide_claims (merge and run claims), next to this script; None when it can't be loaded."""
    try:
        sys.modules.setdefault("guide_title", sys.modules[__name__])
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import guide_claims
        return guide_claims
    except Exception:
        return None


def streams_module():
    """guide_streams (streams and their icons), next to this script; None when it can't be loaded."""
    try:
        sys.modules.setdefault("guide_title", sys.modules[__name__])
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import guide_streams
        return guide_streams
    except Exception:
        return None


def with_icon(ledger, text, *more):
    """`text` with its stream's icon in front, for a line that is shown (never for a cell that is stored)."""
    try:
        return streams_module().shown(ledger, text, *more)
    except Exception:  # an icon is never worth an error
        return text


def without_icon(ledger, text):
    """`text` without a stream icon in front, for a cell whose key is made from its text."""
    try:
        return streams_module().unmarked(ledger, text)
    except Exception:
        return text


def streams_context(ledger):
    try:
        return streams_module().context(ledger)
    except Exception:  # fail open
        return None


def stream_lines(ledger):
    """STATE.md's Streams section, or []."""
    try:
        return streams_module().state_lines(ledger)
    except Exception:
        return []


def claims_context(ledger):
    try:
        lines = claims_module().hook_lines(ledger)
    except Exception:  # fail open, like the rest of the hook
        return None
    return "session-guide claims:\n%s" % "\n".join("- " + l for l in lines) if lines else None


def reminder_notes(ledger):
    """{id6: note} from the last audit for the due reminders: "likely done: …" (later rows cover it: confirm, don't
    ask) or "checked <date>: still open because …" (ask, with this). {} when there is no audit."""
    try:
        return audit_module().reminder_checks(ledger) or {}
    except Exception:
        return {}


def split_due(rows, notes):
    """(to ask, likely done) of the due reminders; each row gets its audit note as `note`."""
    ask, covered = [], []
    for row in rows:
        note = (notes.get(row["id"]) or "").strip()
        (covered if note.startswith("likely done") else ask).append(dict(row, note=note))
    return ask, covered


def shared_note(ledger, text, key=None):
    """Print which open rows share an id with a row just written, so the guide closes the ones it replaces."""
    try:
        keys = audit_module().shared_ids(ledger, text, exclude=tuple(k for k in (key,) if k))
    except Exception:
        return
    if keys:
        print("open rows sharing ids: %s. Does this replace them?" % ", ".join(keys))


CLOSES_VALUE = re.compile(r"^(?:pr:#?\d{1,6}|result:[\w-]{6,64}|ticket:[A-Za-z][A-Za-z0-9]{0,9}-\d{1,6}|"
                          r"session:[0-9a-fA-F]{6,36})$")


def closes_tag(values):
    """The ` · closes: …` tag guide_audit.close_tagged() reads, from --closes values; "" for none."""
    values = [v.strip() for v in values or [] if v.strip()]
    bad = [v for v in values if not CLOSES_VALUE.match(v)]
    if bad:
        raise SystemExit("--closes takes pr:#N, result:<artifact id>, ticket:<ID> or session:<id8>, not %s"
                         % ", ".join(map(repr, bad)))
    return " · closes: " + " ".join(values) if values else ""


def reconcile_lines(ledger, me="", strict=False):
    """(flags, one line each) from reconcile. ([], []) when it fails, since it must never break a prompt; `strict`
    (the retire gate) raises instead, so a failure never reads as "nothing open"."""
    try:
        module = reconcile_module()
        if module is None:
            raise RuntimeError("guide_reconcile.py could not be loaded from %s" % os.path.dirname(os.path.abspath(__file__)))
        flags = module.reconcile(ledger, me=me)
        return flags, [module.describe(f, "python3 " + os.path.abspath(__file__)) for f in flags]
    except Exception:
        if strict:
            raise
        return [], []


def reconcile_context(ledger, me=""):
    flags, lines = reconcile_lines(ledger, me)
    if not lines:
        return None
    return ("session-guide reconcile: %d ledger row(s) disagree with their sessions' real state. Act on these first, "
            "in this turn; each line comes back on every prompt until its row changes:\n%s"
            % (len(lines), "\n".join("- " + l for l in lines)))


def now_line():
    return time.strftime("Now: %a %Y-%m-%d %H:%M %Z (UTC%z). Use this, never a guess, for every time you write.")


def idle_counts(ledger):
    """(how many decided items sit idle, the oldest one's age as "9h" / "4d") from the last audit; (0, "") with none."""
    try:
        found = audit_module().cached(ledger)
        age = found.get("oldest")
        return found.get("idle", 0), "" if age is None else "%dh" % (age // 3600) if age < 36 * 3600 else "%dd" % (age // 86400)
    except Exception:
        return 0, ""


def audit_context(ledger):
    try:
        return audit_module().hook_context(ledger)
    except Exception:  # fail open, like the rest of the hook
        return None


def refresh_audit(ledger, full=False):
    """Run the audit (quick unless `full`), which rewrites STATE.md, and return its one-line summary, or None."""
    try:
        module = audit_module()
        queues = (module.load_state(ledger).get("quick") or {}).get("queues") or ()
        found = module.run(ledger, full=full, queues=queues)
        if not found["rows"] and not found["counts"]["stale"]:
            return None  # nothing idle, unverified or stuck: say nothing
        return module.summary(found), module.render(found), module.state_paths(ledger)[1]
    except Exception:
        return None


def transcript_facts(path):
    """(entrypoint, latest title) of a transcript, from its first lines and its last 256 KB."""
    entrypoint, title = "", ""
    with open(path, "rb") as f:
        for _ in range(40):
            found = re.search(rb'"entrypoint":\s*"([^"]+)"', f.readline())
            if found:
                entrypoint = found.group(1).decode(errors="replace")
                break
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 256 * 1024))
        for line in f.read().splitlines():
            if b'"customTitle"' in line:
                try:
                    title = json.loads(line).get("customTitle") or title
                except ValueError:  # the cut-off first line of the tail
                    pass
    return entrypoint, title


def untracked(ledger, session_id="", hours=12):
    """[{id, age, title}], newest first: recently active sessions with no row in the ledger's ## Sessions table."""
    known, in_sessions = set(), False
    for line in open(ledger, errors="replace"):
        if line.startswith("## "):
            in_sessions = line.strip() == "## Sessions"
        elif in_sessions:
            known.update(re.findall(r"\b[0-9a-f]{6,8}\b", line))
    now, found = time.time(), []
    for path in glob.glob(os.path.join(config_dir(), "projects", "*", "*.jsonl")):
        try:
            age = now - os.path.getmtime(path)
            sid = os.path.basename(path)[:-6]
            if (age > hours * 3600 or sid == session_id or not os.path.getsize(path)
                    or any(sid.startswith(k) for k in known)):
                continue
            content = marker_content(sid)
            if content is not None and content not in WORKER_MARKERS:  # closed, retired or a guide
                continue
            entrypoint, title = transcript_facts(path)
            if not entrypoint.startswith("sdk"):  # `claude -p` runs are scripts, not sessions to manage
                found.append(dict(id=sid, age=age, title=title))
        except OSError:  # a transcript removed while we read
            continue
    return sorted(found, key=lambda s: s["age"])


def describe(session):
    return "'%s' [%s], active %dm ago" % (session["title"] or "no title yet", session["id"][:8], session["age"] // 60)


def guide_context(session_id):
    """What a guide should hear on this prompt: the sessions it hasn't asked about, the ones whose rows are DONE but
    are still marked, and the closed ones a running process keeps at their old title. None when there are none.

    Closed sessions whose process has ended are renamed here too, so a guide's prompts finish what `done` couldn't."""
    content = marker_content(session_id)
    if not content or content in WORKER_MARKERS + (RETIRED, DONE):
        return None
    ledger = os.path.expanduser(content)
    if not os.path.isfile(ledger) or not any(l.strip() == "## Sessions" for l in open(ledger, errors="replace")):
        return None  # no ledger to guide by: fail open, say nothing
    parts = [now_line()]  # the clock and reconcile first: nothing that can call gh comes before them
    reconciled = reconcile_context(ledger, session_id)
    if reconciled:
        parts.append(reconciled)
    streams = streams_context(ledger)  # small local files
    if streams:
        parts.append(streams)
    late = []
    # The audit closes rows whose closes: tag happened and checks the due reminders, so it runs before settle; it
    # (and claims, below) may ask gh, so each runs within what is left of the hook's time.
    audit = in_time(audit_context, ledger, late=late, name="audit")
    found, shut, held = untracked(ledger, session_id), closable(ledger), settle_closed()
    settling = settle_status(ledger, session_id)
    if held:
        parts.append("session-guide sweep: %d closed session(s) still have a running process, so their titles stay "
                     "orange until a prompt reaches them. SendMessage each the CLOSE message: %s"
                     % (len(held), ", ".join(s[:8] for s in held)))
    if found:
        lines = ["- " + describe(s) for s in found[:8]] + ["- and %d more" % (len(found) - 8)] * (len(found) > 8)
        parts.append("session-guide sweep: %d session(s) active in the last 12 h have no row in the ledger's Sessions "
                     "table:\n%s\n"
                     "Run `python3 %s active <id>` on each, then ask about them in this turn with AskUserQuestion (Manage / "
                     "Watch / Leave active / Ignore), and give each a row at the level the user picks."
                     % (len(found), "\n".join(lines), os.path.abspath(__file__)))
    if shut:
        parts.append("session-guide sweep: %d session(s) have only DONE rows in the ledger but are still marked, so "
                     "their titles stay orange. Run `python3 %s done <id>` on each: %s"
                     % (len(shut), os.path.abspath(__file__), ", ".join(s[:8] for s in shut)))
    if settling["unsettled"]:
        rows = settling["unsettled"]
        lines = ["- " + describe_unsettled(s, ledger) for s in rows[:8]] + ["- and %d more" % (len(rows) - 8)] * (len(rows) > 8)
        parts.append("session-guide settle: %d session(s) have gone quiet and aren't settled:\n%s\n"
                     "Peek each. Finished, nothing left on it or its subject: close it (`python3 %s done <id>`; ask the "
                     "user first if it is WATCHED or you aren't sure). Still needs the user: `python3 %s waiting <id> "
                     "\"<exact action, full link or command>\"`. More work for it: send it the next step."
                     % (len(rows), "\n".join(lines), os.path.abspath(__file__), os.path.abspath(__file__)))
    ask, covered = split_due(settling["due"], reminder_notes(ledger))
    if covered:
        lines = ["- %s: %s -> %s" % (with_icon(ledger, r["session"], r["what"]), r["what"], r["note"])
                 for r in covered[:8]]
        lines += ["- and %d more" % (len(covered) - 8)] * (len(covered) > 8)
        parts.append("session-guide settle: %d due reminder(s) look done already; later ledger rows cover them. Do not "
                     "ask the user: confirm each from its evidence, then close it as its line says:\n%s"
                     % (len(covered), "\n".join(lines)))
    if ask:
        rows = ask
        lines = ["- %s: %s (asked %s)%s" % (with_icon(ledger, r["session"], r["what"]), r["what"], r["asked"],
                                            "; " + r["note"] if r["note"] else "") for r in rows[:8]]
        lines += ["- and %d more" % (len(rows) - 8)] * (len(rows) > 8)
        parts.append("session-guide settle: %d reminder(s) due:\n%s\n"
                     "Check each still applies (peek, PR state), then ask with AskUserQuestion, one question each, "
                     "repeating the full action: Done it / Nothing more to do: close it / Sleep 1, 2 or 8 hours / Sleep 12, "
                     "24 or 48 hours. A sleep answer gets an immediate second question for the exact period, then `python3 "
                     "%s sleep <id> <hours>`. Afterwards keep a wake scheduled for the next reminder that `settle` prints: "
                     "over 60 minutes away, a one-shot CronCreate rather than chained wakeups."
                     % (len(rows), "\n".join(lines), os.path.abspath(__file__)))
    results = results_status(ledger)["due"]
    if results:
        lines = ["- " + describe_result(r, ledger) for r in results[:8]] + ["- and %d more" % (len(results) - 8)] * (len(results) > 8)
        parts.append("session-guide results: %d finished deliverable(s) have no verdict from the user:\n%s\n"
                     "List each under **Results for you** with its link and one line on the result, then ask with "
                     "AskUserQuestion, one question each: Satisfied / Change it / Drop it / Haven't looked yet. Record "
                     "the answer with `python3 %s result-answer \"<deliverable>\" <satisfied|change|drop|not-looked>` "
                     "(not-looked: ask the cadence, then `--every <hours>`). Its stream isn't DONE, and its loose ends "
                     "stay open, until the answer is in." % (len(results), "\n".join(lines), os.path.abspath(__file__)))
    due = followup_due(ledger)
    if due:
        last = last_review(ledger)
        parts.append("session-guide follow-ups: the review of recent fixes and deployments is due (last review %s), "
                     "and the ledger alone shows %d with no verification recorded. When nothing more urgent is in this "
                     "turn, run `python3 %s followups` and follow SKILL §7 Follow-ups: propose a read-only 'verify "
                     "<thing>' session for each in the interview, record each with `verification`, and stamp the "
                     "review with `followups --reviewed`."
                     % (time.strftime(TIME_FORMAT, time.localtime(last)) if last else "never", due,
                        os.path.abspath(__file__)))
    claims = in_time(claims_context, ledger, late=late, name="claims")
    if claims:
        parts.append(claims)
    if audit:
        parts.append(audit)
    if late:
        parts.append("session-guide: the %s check ran past this prompt's time budget (%g s) and was skipped; it runs "
                     "again on the next prompt." % (" and ".join(late), hook_seconds()))
    return "\n".join(parts)


HOOK_SECONDS = 7.0  # what the hook may spend in all (its timeout is 10 s): SESSION_GUIDE_HOOK_SECONDS
HOOK_STARTED = [None]  # when cmd_hook began; None outside the hook (no deadline)


def hook_seconds():
    try:
        return float(os.environ.get("SESSION_GUIDE_HOOK_SECONDS", HOOK_SECONDS))
    except ValueError:
        return HOOK_SECONDS


def in_time(fn, *args, **kw):
    """fn(*args) when it returns within what is left of the hook's time, else None (its name goes into `late`).
    Outside the hook it simply runs. An exception is None too: a slow or broken gh check never costs the prompt the
    lines already made."""
    late, name = kw.pop("late", None), kw.pop("name", getattr(fn, "__name__", "check"))
    if HOOK_STARTED[0] is None:
        try:
            return fn(*args)
        except Exception:
            return None
    left = HOOK_STARTED[0] + hook_seconds() - time.time()
    box = []

    def run():
        try:
            box.append(fn(*args))
        except Exception:
            box.append(None)
    import threading
    worker = threading.Thread(target=run)
    worker.daemon = True  # a check still running when the hook answers dies with the process
    worker.start()
    worker.join(max(0.0, left))
    if not box:
        if late is not None:
            late.append(name)
        return None
    return box[0]


def gh_budget():
    """Give this process one overall gh budget (guide_gh.set_budget: SESSION_GUIDE_GH_BUDGET, default 3 s), so the
    audit's and the claims' gh calls can't run the hook past its timeout. Ignored when guide_gh or set_budget is
    missing."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import guide_gh
        guide_gh.set_budget()
    except Exception:
        pass


def forward_path(session_id):
    """Where `retire` notes a retired guide's ledger and the new guide's socket. Not in guides/: agent-guard and the
    title read a marker's whole content, and a retired marker holds exactly `retired`."""
    return os.path.join(config_dir(), "session-guide", "retired", session_id + ".json")


def socket_of(session_id):
    """The `uds:` address of the live process that holds this session, or None."""
    for path in glob.glob(os.path.join(config_dir(), "sessions", "*.json")):
        try:
            with open(path) as f:
                info = json.load(f)
            if info.get("sessionId") == session_id and info.get("messagingSocketPath"):
                try:
                    os.kill(int(info["pid"]), 0)
                except PermissionError:
                    pass  # the process exists, it is just not ours
                return "uds:" + info["messagingSocketPath"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def live_guide(ledger, but=""):
    """The session id of the newest guide marker naming `ledger` (not `but`), or None."""
    found = []
    for path in glob.glob(os.path.join(config_dir(), "session-guide", "guides", "*")):
        sid = os.path.basename(path)
        content = marker_content(sid)
        if sid != but and content and content not in WORKER_MARKERS + (RETIRED, DONE) and \
                os.path.abspath(os.path.expanduser(content)) == os.path.abspath(ledger):
            found.append((os.path.getmtime(path), sid))
    return max(found)[1] if found else None


def retired_context(session_id):
    """What a retired guide hears on every prompt: it is retired, where to forward, and not to act."""
    try:
        with open(forward_path(session_id)) as f:
            note = json.load(f)
    except (OSError, ValueError):
        note = {}
    to, ledger = note.get("to"), note.get("ledger")
    if not to and ledger:
        new = live_guide(ledger, session_id)
        to = socket_of(new) if new else None
    where = to or ("the new guide's socket (the Scope line of %s)" % ledger if ledger else "the new guide's socket")
    return ("session-guide: you are a RETIRED guide%s. Do not act as guide: no relays, starts, closes, interviews or "
            "ledger edits. Forward every message a worker sends you, unchanged, to %s by SendMessage, and tell its "
            "sender to send there from now on; tell the user to talk to the new guide." % (" since %s" % note["at"] if note.get("at") else "", where))


def marker_content(session_id):
    path = marker(session_id)
    return open(path).read().strip() if os.path.isfile(path) else None


def guided_prefix():
    return os.environ.get("SESSION_GUIDE_GUIDED_PREFIX") or GUIDED_PREFIX


def watched_prefix():
    return os.environ.get("SESSION_GUIDE_WATCHED_PREFIX") or WATCHED_PREFIX


def done_prefix():
    return os.environ.get("SESSION_GUIDE_DONE_PREFIX") or DONE_PREFIX


def active_prefix():
    return os.environ.get("SESSION_GUIDE_ACTIVE_PREFIX") or ACTIVE_PREFIX


GUIDED_TAG = re.compile(r"\(g(?:\u00b7[^()\s]+)?\)")  # "(g)", or "(g·hub)" from a guide with a scope of its own


def worker_title(content, current, icon="", old=()):
    """The guided / watched / active / unguided / done title for `current`, or None when it is already right (or there is none
    yet). `icon` (its stream's) goes right after the prefix; it and the `old` ones come off wherever they are in front.
    With no level (content None) and no icons the title is left alone."""
    if content is None and not icon and not old:
        return None
    marks = [guided_prefix().strip(), watched_prefix().strip(), active_prefix().strip(), GUIDED_PREFIX.strip(),
             WATCHED_PREFIX.strip(), ACTIVE_PREFIX.strip(), "\U0001f7e7\U0001f7e7", "(g)"] + [done_prefix().strip()] * (content == DONE)
    icons = [i for i in (icon,) + tuple(old) if i]
    bare = current
    while True:
        tag = GUIDED_TAG.match(bare)
        mark = next((m for m in marks if m and bare.startswith(m)), None) or tag and tag.group()
        mark = mark or next((i for i in icons if bare == i or bare.startswith(i + " ")), None)
        if not mark:
            break
        bare = bare[len(mark):].lstrip()
    bare = icon + " " + bare if icon and bare else bare
    want = {GUIDED: guided_prefix() + bare, WATCHED: watched_prefix() + bare, ACTIVE: active_prefix() + bare,
            DONE: done_prefix() + bare}.get(content, bare)
    return want if bare and want != current else None


def title_icons(session_id):
    """(its stream's icon, the icons to take off its title); ("", ()) for a session on no stream, or on any error."""
    try:
        return streams_module().title_icons(session_id)
    except Exception:
        return "", ()


def title_for(session_id, current=""):
    content = marker_content(session_id)
    if content in WORKER_MARKERS + (DONE, None):
        return worker_title(content, current, *title_icons(session_id))
    if content == RETIRED:
        return os.environ.get("SESSION_GUIDE_RETIRED_TITLE") or RETIRED_TITLE
    ledger = os.path.expanduser(content)
    found = counts(ledger, session_id)
    if found is None:
        return None
    found = dict(found, slug=os.path.basename(os.path.dirname(os.path.abspath(ledger))),
                 host=socket.gethostname().split(".")[0])
    return (os.environ.get("SESSION_GUIDE_TITLE") or TITLE).format(**found)


def cmd_hook():
    try:
        event = json.load(sys.stdin)
        sid = event["session_id"]
        current = (event.get("session_title") or "").strip()
        HOOK_STARTED[0] = time.time()
        gh_budget()  # before the audit and the claims, which may call gh
        if marker_content(sid) or any(title_icons(sid)):
            sync_session_titles(sid, marker_content(sid))
        context = guide_context(sid)  # first: it refreshes the audit counts the title shows
        if marker_content(sid) == RETIRED:
            context = retired_context(sid)
        title = title_for(sid, current)
        if marker_content(sid) == UNGUIDED and current and not title:
            os.remove(marker(sid))  # the prefix is off: nothing left to undo
        if current and not title and any(title_icons(sid)):
            streams_module().forget_stripped(sid)
        output = {"hookEventName": event.get("hook_event_name", "UserPromptSubmit")}
        if title:
            output["sessionTitle"] = title
        if context:
            output["additionalContext"] = context
        if title or context:
            json.dump({"hookSpecificOutput": output}, sys.stdout)  # ASCII-escaped: any locale
    except Exception:  # fail open: a broken guide title must never block a prompt
        pass
    HOOK_STARTED[0] = None
    return 0


def cmd_mark(args):
    sid = resolve_session(args.session)
    ledger = os.path.abspath(os.path.expanduser(args.ledger))
    if counts(ledger) is None:
        raise SystemExit("%s has no ## Sessions table" % ledger)
    if marker_content(sid) in (RETIRED, DONE):
        raise SystemExit("%s is %s; a new guide needs a fresh session"
                         % (sid[:8], "a retired guide" if marker_content(sid) == RETIRED else "closed"))
    flags, lines = reconcile_lines(ledger, sid)  # first: what ended under the last guide outranks the whole audit
    for line in lines:
        print("Reconcile: " + line)
    if lines:
        print("Act on the %d reconcile line(s) above before the audit table: they are sessions that ended, handed off or "
              "wait on you right now." % len(lines))
    write_marker(sid, ledger)
    found = refresh_audit(ledger, full=True)  # a takeover starts from the whole body of work, not from the reminders
    print("%s is a guide; title from its next prompt: %s" % (sid[:8], title_for(sid)))
    if found:
        print("Audit: %s\n%s\nLive state (read this, not the ledger's log): %s\nPut the table into your first "
              "interview; `guide_audit.py audit` prints all of it." % found)
    return 0


def cmd_unmark(args):
    sid = resolve_session(args.session)
    if os.path.exists(marker(sid)):
        os.remove(marker(sid))
        print("%s is no longer a guide; its title is left as it is" % sid[:8])
    else:
        print("%s was not marked" % sid[:8])
    return 0


def cmd_retire(args):
    sid = resolve_session(args.session)
    old = marker_content(sid)
    caller = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    ledger = None
    if old and old not in WORKER_MARKERS + (RETIRED, DONE) and os.path.isfile(os.path.expanduser(old)):
        ledger = os.path.abspath(os.path.expanduser(old))
    elif old == RETIRED:
        try:
            with open(forward_path(sid)) as f:
                ledger = json.load(f).get("ledger")
        except (OSError, ValueError):
            pass
    try:
        found = zip(*reconcile_lines(ledger, caller, strict=True)) if ledger else ()
    except Exception as error:  # the gate can't see the rows: refuse, unless the user said --force
        print("Reconcile failed on %s: %s: %s" % (ledger, type(error).__name__, error))
        if args.check or not args.force:
            print("Not retired: the open rows could not be checked. Fix the error, or run `retire --force` to retire "
                  "without the check.")
            return 1
        found = ()
    pairs = [(flag, line) for flag, line in found if flag["id"] != sid[:6].lower()]  # never the guide's own row
    lines = [line for _, line in pairs]
    for line in lines:
        print("Reconcile: " + line)
    if lines and (args.check or not args.force):
        print("Not retired: %d open row(s) above need a guide. Act on each now (start the successor, answer or record "
              "the worker, close it), or run `retire --force` to hand them to the next guide in the ledger's %s table."
              % (len(lines), HANDOFF_SECTION))
    print("Send each MANAGED worker this line by SendMessage, word for word: \"%s\"" % GUIDE_CHANGE)
    if args.check or (lines and not args.force):
        return 1 if lines else 0
    if lines:
        now = time.strftime(TIME_FORMAT)
        for flag, line in pairs:
            write_row(ledger, HANDOFF_SECTION, HANDOFF_SECTION + " (open at the last guide change)", HANDOFF_TABLE,
                      lambda cells: (row_id(cells[0]), cells[1]) if cells else None, (flag["id"], flag["kind"]),
                      [flag["session"], flag["kind"], line, now], before=("## Streams", "## Sessions"))
        print("%d row(s) written to the %s table of %s for the next guide" % (len(lines), HANDOFF_SECTION, ledger))
    to = args.to or (socket_of(caller) if caller and caller != sid else None)
    if not to and ledger:
        new = live_guide(ledger, sid)
        to = socket_of(new) if new else None
    write_marker(sid, RETIRED)
    os.makedirs(os.path.dirname(forward_path(sid)), exist_ok=True)
    with open(forward_path(sid), "w") as f:
        json.dump(dict(ledger=ledger, to=to, at=time.strftime(TIME_FORMAT)), f)
    print("%s is retired; title from its next prompt: %s" % (sid[:8], title_for(sid)))
    print("Its prompts now say: you are retired, forward to %s, do not act." % (to or "the new guide's socket (pass "
                                                                                     "--to uds:<socket> to name it)"))
    if ledger:
        found = refresh_audit(ledger)  # the handoff leaves the live state current
        if found:
            print("Handed over: %s\nLive state for the next guide: %s" % (found[0], found[2]))
    return 0


def set_level(args, level, prefix):
    sid = resolve_session(args.session)
    content = marker_content(sid)
    if content == DONE:
        raise SystemExit("%s is closed; a closed session gets no new level" % sid[:8])
    if content is not None and content not in WORKER_MARKERS:
        raise SystemExit("%s is a guide%s; guides get no prefix" % (sid[:8], " (retired)" * (content == RETIRED)))
    write_marker(sid, level)
    print("%s is %s; %r goes before its title from its next prompt" % (sid[:8], level, prefix))
    return 0


def closable(ledger):
    """[(id, title)] of sessions still marked managed / watched / active whose every row in the ledger is DONE: the
    guide closed them in the ledger but never ran `done`. Their job state alone says nothing: a worker's state turns
    done at every final message and the guide can resume it, so only a DONE row counts."""
    levels, in_sessions = {}, False
    for line in open(ledger, errors="replace"):
        if line.startswith("## "):
            in_sessions = line.strip() == "## Sessions"
        elif in_sessions and line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rid = row_id(cells[0]) if len(cells) > 1 else None
            if rid:
                levels.setdefault(rid, []).append(cells[1].split()[0] if cells[1] else "")
    found = []
    for path in glob.glob(os.path.join(config_dir(), "session-guide", "guides", "*")):
        sid = os.path.basename(path)
        if marker_content(sid) in (GUIDED, WATCHED, ACTIVE) and levels.get(sid[:6].lower()) and \
                all(level == "DONE" for level in levels[sid[:6].lower()]):
            found.append(sid)
    return sorted(found)


def split_row(line):
    """The cells of a table row. `\\|` is a pipe inside a cell: reminders hold shell commands."""
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip()[1:-1])]


def session_levels(ledger):
    """{id6: (level, first cell)} from the ## Sessions table; a session on several rows takes its topmost row's Level."""
    found, in_sessions = {}, False
    for line in open(ledger, errors="replace"):
        if line.startswith("## "):
            in_sessions = line.strip() == "## Sessions"
        elif in_sessions and line.lstrip().startswith("|"):
            cells = split_row(line)
            rid = row_id(cells[0]) if len(cells) > 1 else None
            ids = re.findall(r"\[([0-9a-fA-F]{6,36})\]", cells[0])
            if len(ids) > 1:  # a title can quote other refs, say "[065020] (ListAgents [fa18dd])": take the real session
                rid = next((i[:6].lower() for i in reversed(ids) if last_write(i[:6].lower())), rid)
            if rid:
                found.setdefault(rid, (re.match(r"[A-Za-z]*", cells[1]).group(), cells[0]))
    return found


def waiting_rows(ledger):
    """{id6: {session, what, asked, remind, owed}} from the table in the ledger's `## Waiting on ...` section. `owed`
    rows are questions the guide owes the user (`waiting ask`), keyed by a hash of the question, not a session."""
    found, inside = {}, False
    for line in open(ledger, errors="replace"):
        if line.startswith("## "):
            inside = line.startswith("## Waiting on")
        elif inside and line.lstrip().startswith("|"):
            cells = split_row(line)
            rid = row_id(cells[0])
            if rid and len(cells) >= 4:
                found[rid] = dict(session=cells[0], what=cells[1].replace("\\|", "|"), asked=cells[2], remind=cells[3],
                                  owed=cells[0].lower().startswith(OWED))
    return found


def owed_key(question):
    """The 6 hex characters that key an owed question's reminder row: the same question gives the same row."""
    import hashlib
    return hashlib.sha1(" ".join(question.lower().split()).encode()).hexdigest()[:6]


def reminder_key(given, ledger):
    """The id6 of a waiting row: an owed question's key when `given` is one, else the session `given` names."""
    key = (given or "").strip().lower()
    row = waiting_rows(ledger).get(key) if len(key) == 6 else None
    if row and row["owed"]:
        return key
    return resolve_session(given)[:6].lower()


def read_time(text):
    """Epoch of a `YYYY-MM-DD HH:MM` cell, or 0 (due) when it can't be read."""
    try:
        return time.mktime(time.strptime(text.strip(), TIME_FORMAT))
    except ValueError:
        return 0


def write_ledger(ledger, lines):
    with open(ledger + ".tmp", "w") as f:
        f.write("".join(lines))
    os.replace(ledger + ".tmp", ledger)


def section_span(lines, section, title, before):
    """(start, end) line indexes of the first section whose heading starts with `section`. When it is missing, adds it
    as `title` before the `before` heading (else at the end) and returns where it now is."""
    start = next((i for i, l in enumerate(lines) if l.startswith(section)), None)
    if start is None:
        at = next((i for i, l in enumerate(lines) if l.startswith(before)), len(lines))
        if at == len(lines) and lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines[at:at] = [title + "\n", "\n"]
        start = at
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, end


def write_row(ledger, section, title, head, key_of, key, row, before="## Open items"):
    """Set the row whose key_of(cells) is `key`, in the table of the first section whose heading starts with `section`,
    to `row` (its cells), or remove it when `row` is None. True when the ledger changed. Adds the section (`title`)
    and its table (`head`) when they are missing; the table goes first in the section, and anything else there stays."""
    lines = open(ledger, errors="replace").read().splitlines(True)
    if row is None and not any(l.startswith(section) for l in lines):
        return False
    text = row and "| %s |\n" % " | ".join(c.replace("\n", " ").replace("|", "\\|") for c in row)
    start, end = section_span(lines, section, title, before)
    table = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
    mine = [i for i in table if key_of(split_row(lines[i])) == key]
    if mine:
        lines[mine[0]:mine[0] + 1] = [text] if row else []
    elif row is None:
        return False
    elif table:
        lines.insert(table[-1] + 1, text)
    else:
        blank = [] if lines[start + 1:start + 2] == ["\n"] and end == start + 2 else ["\n"]
        lines[start + 1:start + 1] = head + [text] + blank
    write_ledger(ledger, lines)
    return True


def write_waiting(ledger, rid, row):
    """Set session `rid`'s row in the waiting table to `row` (its 4 cells), or remove it when `row` is None."""
    return write_row(ledger, "## Waiting on", "## Waiting on the user", WAITING_TABLE, lambda cells: row_id(cells[0]),
                     rid, row)


def last_write(rid):
    """(full session id, seconds since its transcript last changed), or None when it has no transcript any more."""
    paths = glob.glob(os.path.join(config_dir(), "projects", "*", rid + "*.jsonl"))
    if not paths:
        return None
    path = max(paths, key=os.path.getmtime)
    return os.path.basename(path)[:-6], time.time() - os.path.getmtime(path)


def job_state(session_id):
    try:
        with open(os.path.join(config_dir(), "jobs", session_id[:8], "state.json")) as f:
            return json.load(f).get("state") or ""
    except (OSError, ValueError):
        return ""


def settle_status(ledger, session_id="", idle_hours=IDLE_HOURS):
    """What is left to settle: {unsettled, due, asleep}.

    unsettled: MANAGED and WATCHED sessions, quiet for idle_hours and not running, with no waiting row and not closed.
    due / asleep: waiting rows of open sessions, by Remind at. A row whose time can't be read is due: never forgotten."""
    levels, rows, closed = session_levels(ledger), waiting_rows(ledger), closed_ids()
    unsettled, due, asleep = [], [], []
    for rid, (level, cell) in levels.items():
        if level not in ("MANAGED", "WATCHED") or rid in closed or rid in rows or rid == session_id[:6].lower():
            continue
        seen = last_write(rid)
        if seen is None:
            unsettled.append(dict(id=rid, session=cell, level=level, idle=None, state=""))
            continue
        sid, idle = seen
        content, state = marker_content(sid), job_state(sid)
        if content is not None and content not in WORKER_MARKERS:  # a guide: guides settle by handing over
            continue
        if idle >= idle_hours * 3600 and not (state == "working" and session_alive(sid)):
            unsettled.append(dict(id=rid, session=cell, level=level, idle=idle, state=state))
    for rid, row in rows.items():
        if not row["owed"] and (rid in closed or levels.get(rid, ("", ""))[0] not in ("MANAGED", "WATCHED", "ACTIVE")):
            continue
        at = read_time(row["remind"])
        (due if at <= time.time() else asleep).append(dict(row, id=rid, at=at))
    return dict(unsettled=unsettled, due=sorted(due, key=lambda r: r["at"]), asleep=sorted(asleep, key=lambda r: r["at"]))


def result_key(deliverable):
    return " ".join(deliverable.lower().split())


def results_rows(ledger):
    """{key: {deliverable, link, delivered, asked, answer}} from the ledger's Results for you table."""
    found, inside = {}, False
    for line in open(ledger, errors="replace"):
        if line.startswith("## "):
            inside = line.startswith(RESULTS_SECTION)
        elif inside and line.lstrip().startswith("|"):
            cells = split_row(line)
            if len(cells) >= 5 and not set(cells[0]) <= set("-: ") and cells[0] != "Deliverable":
                found[result_key(cells[0])] = dict(zip(("deliverable", "link", "delivered", "asked", "answer"),
                                                       (c.replace("\\|", "|") for c in cells)))
    return found


def find_result(rows, text):
    """(key, row) of the one Results row `text` names: its full name, else a unique prefix or part; else (None, None)."""
    want = result_key(text)
    keys = [want] if want in rows else [k for k in rows if k.startswith(want)] or [k for k in rows if want in k]
    if len(keys) > 1:
        raise SystemExit("%r matches more than one deliverable in Results for you: %s" % (text, "; ".join(sorted(keys))))
    return (keys[0], rows[keys[0]]) if keys else (None, None)


def write_result(ledger, key, row):
    return write_row(ledger, RESULTS_SECTION, RESULTS_SECTION, RESULTS_TABLE, lambda cells: result_key(cells[0]), key,
                     row, before=("## Waiting on", "## Open items", "## Verifications", "## Log"))


def results_status(ledger, now=None):
    """{due, asleep}: the Results rows with no answer yet (due), or "not looked yet" ones by their ask-again time."""
    now, due, asleep = now or time.time(), [], []
    for key, row in results_rows(ledger).items():
        answer = row["answer"].strip()
        if answer in ("", UNANSWERED):
            due.append(dict(row, key=key, at=0))
            continue
        again = ASK_AGAIN.search(answer)
        if answer.lower().startswith("not looked") or again:
            at = read_time(again.group(1)) if again else 0
            (due if at <= now else asleep).append(dict(row, key=key, at=at))
    return dict(due=sorted(due, key=lambda r: r["at"]), asleep=sorted(asleep, key=lambda r: r["at"]))


def describe_result(row, ledger=None):
    text = "%s %s (delivered %s, asked %s)" % (row["deliverable"], row["link"], row["delivered"], row["asked"])
    return with_icon(ledger, text) if ledger else text


def describe_unsettled(row, ledger=None):
    session = with_icon(ledger, row["session"]) if ledger else row["session"]
    if row["idle"] is None:
        return "%s, %s: its transcript is gone, so set its row's Level to DONE by hand" % (session, row["level"])
    return "%s, %s: quiet %.0f h%s" % (session, row["level"], row["idle"] / 3600,
                                       ", job state " + row["state"] if row["state"] else "")


def require_ledger():
    ledger = guide_ledger()
    if ledger is None:
        raise SystemExit("no single guide ledger found: run this from the guide")
    return ledger


def cmd_settle(args):
    ledger = os.path.expanduser(args.ledger or require_ledger())
    audit = refresh_audit(ledger)  # first: it closes rows whose closes: tag happened and checks the due reminders
    found = settle_status(ledger, os.environ.get("CLAUDE_CODE_SESSION_ID", ""), args.idle_hours)
    ask, covered = split_due(found["due"], reminder_notes(ledger))
    for line in reconcile_lines(ledger, os.environ.get("CLAUDE_CODE_SESSION_ID", ""))[1]:
        print("Reconcile: " + line)  # first: these ended minutes ago, not hours
    for row in found["unsettled"]:
        print("Unsettled: " + describe_unsettled(row, ledger))
    for row in covered:
        print("Likely done: %s: %s -> %s" % (with_icon(ledger, row["session"], row["what"]), row["what"], row["note"]))
    for row in ask:
        print("Due: %s: %s (asked %s)%s" % (with_icon(ledger, row["session"], row["what"]), row["what"], row["asked"],
                                             "; " + row["note"] if row["note"] else ""))
    for row in found["asleep"]:
        print("Asleep until %s: %s: %s" % (row["remind"], with_icon(ledger, row["session"], row["what"]), row["what"]))
    results = results_status(ledger)
    for row in results["due"]:
        print("Unanswered result: " + describe_result(row, ledger))
    for row in results["asleep"]:
        print("Result asleep until %s: %s %s" % (time.strftime(TIME_FORMAT, time.localtime(row["at"])),
                                                  row["deliverable"], row["link"]))
    print("%d unsettled, %d due, %d asleep" % (len(found["unsettled"]), len(ask), len(found["asleep"]))
          + (", %d likely done" % len(covered) if covered else "")
          + (", %d result(s) unanswered" % len(results["due"]) if results["due"] else ""))
    print_next_reminder(ledger, found, results)
    if audit:  # a wake with nothing due still has this to work on
        print("Audit: %s\n%s" % audit[:2])
        if not found["due"] and not found["unsettled"] and not results["due"]:
            print("Nothing is due, so this wake works the table above: propose a start for each idle item, and run "
                  "`guide_audit.py audit` when the full look back is due.")
    return 0


def print_next_reminder(ledger, found=None, results=None):
    """The earliest sleeping reminder or not-looked result, as "Next reminder: <time>", when there is one."""
    found, results = found or settle_status(ledger), results or results_status(ledger)
    times = [r["at"] for r in found["asleep"]] + [r["at"] for r in results["asleep"]]
    if times:
        print("Next reminder: " + time.strftime(TIME_FORMAT, time.localtime(min(times))))


def cmd_waiting(args):
    ledger = require_ledger()
    what = " ".join(args.what.split())
    if not what:
        raise SystemExit("say what the user needs to do")
    if args.at and args.hours:
        raise SystemExit("pass --hours or --at, not both")
    if args.session == "ask":
        return owed_question(ledger, without_icon(ledger, what), args)
    if args.at or args.hours:
        raise SystemExit("--hours and --at are for `waiting ask`; a session's reminder is due now, then `sleep` it")
    sid = resolve_session(args.session)
    level, cell = session_levels(ledger).get(sid[:6].lower(), ("", ""))
    if level not in ("MANAGED", "WATCHED", "ACTIVE") or marker_content(sid) == DONE:
        raise SystemExit("%s has no open row in ## Sessions (level %r); give it one first" % (sid[:8], level))
    now = time.strftime(TIME_FORMAT)
    old = waiting_rows(ledger).get(sid[:6].lower())
    what = tagged(what, args, old)
    write_waiting(ledger, sid[:6].lower(), [cell, what, old["asked"] if old else now, old["remind"] if old else now])
    print("%s waits on the user; reminder at %s" % (sid[:8], old["remind"] if old else now))
    shared_note(ledger, what, sid[:6].lower())
    return 0


def tagged(what, args, old=None):
    """`what` with the closes: tag of --closes, or the one its old row had when no --closes is given."""
    tag = closes_tag(getattr(args, "closes", None))
    if not tag and old:
        found = re.search(r"\s*\u00b7?\s*\bcloses:.*$", old["what"])
        tag = " \u00b7 " + found.group().strip(" \u00b7") if found else ""
    return what + tag


def owed_question(ledger, question, args):
    """A reminder row for a question the guide owes the user, due now, in --hours, or at --at."""
    if args.hours is not None and args.hours <= 0:
        raise SystemExit("--hours is a positive number of hours")
    if args.at and not read_time(args.at):
        raise SystemExit("--at is local time as %s" % TIME_FORMAT.replace("%Y", "YYYY").replace("%m", "MM")
                         .replace("%d", "DD").replace("%H", "HH").replace("%M", "MM"))
    now = time.time()
    remind = (time.strftime(TIME_FORMAT, time.localtime(read_time(args.at))) if args.at
              else time.strftime(TIME_FORMAT, time.localtime(now + (args.hours or 0) * 3600)))
    key = owed_key(question)
    old = waiting_rows(ledger).get(key)
    question = tagged(question, args, old)
    write_waiting(ledger, key, ["%s [%s]" % (OWED, key), question, old["asked"] if old else
                                time.strftime(TIME_FORMAT, time.localtime(now)), remind])
    print("owed question [%s] is in the waiting table; ask at %s (sleep / unwait it as `%s`)" % (key, remind, key))
    shared_note(ledger, question, key)
    return 0


def cmd_sleep(args):
    ledger = require_ledger()
    key = reminder_key(args.session, ledger)
    if args.hours <= 0:
        raise SystemExit("sleep for a positive number of hours; the guide offers %s" % ", ".join(map(str, SLEEP_HOURS)))
    row = waiting_rows(ledger).get(key)
    if not row:
        raise SystemExit("%s has no reminder; run `waiting` first" % key)
    remind = time.strftime(TIME_FORMAT, time.localtime(time.time() + args.hours * 3600))
    write_waiting(ledger, key, [row["session"], row["what"], row["asked"], remind])
    print("%s sleeps until %s" % (key, remind))
    print_next_reminder(ledger)
    return 0


def cmd_unwait(args):
    ledger = require_ledger()
    key = reminder_key(args.session, ledger)
    gone = write_waiting(ledger, key, None)
    print("%s %s" % (key, "no longer waits on the user" if gone else "had no reminder"))
    return 0


def cmd_result(args):
    ledger = os.path.expanduser(args.ledger or require_ledger())
    deliverable, link = without_icon(ledger, " ".join(args.deliverable.split())), " ".join(args.link.split())
    if not deliverable or not link:
        raise SystemExit("say what was delivered and give its link, the exact one the user opens")
    rows = results_rows(ledger)
    key, old = find_result(rows, deliverable) if rows else (None, None)
    if old and not args.source:
        deliverable = old["deliverable"]  # the row keeps its name (and the session noted on it)
    elif args.source:
        deliverable += " (%s)" % without_icon(ledger, " ".join(args.source.split()))
    now = time.strftime(TIME_FORMAT)
    write_result(ledger, key or result_key(deliverable), [deliverable, link, now, now, UNANSWERED])
    shared_note(ledger, "%s %s" % (deliverable, link))
    print("%s: %s is in Results for you, unanswered%s; ask the user now: Satisfied / Change it / Drop it / Haven't "
          "looked yet" % (deliverable, link, " again (it was %s)" % old["answer"] if old else ""))
    return 0


def cmd_result_answer(args):
    ledger = os.path.expanduser(args.ledger or require_ledger())
    answer = args.answer.lower().replace("_", "-").replace(" ", "-")
    answer = {"change-it": "change", "drop-it": "drop", "haven't-looked": "not-looked", "havent-looked": "not-looked",
              "not-looked-yet": "not-looked", "later": "not-looked"}.get(answer, answer)
    if answer not in ANSWERS:
        raise SystemExit("answer is one of: %s" % ", ".join(ANSWERS))
    if args.every is not None and args.every <= 0:
        raise SystemExit("--every is a positive number of hours")
    key, row = find_result(results_rows(ledger), args.deliverable)
    if not row:
        raise SystemExit("no deliverable in Results for you matches %r" % args.deliverable)
    now = time.time()
    stamp = time.strftime(TIME_FORMAT, time.localtime(now))
    note = " ".join((args.note or "").split())
    asked = row["asked"]
    if answer == "not-looked":
        again = ASK_AGAIN.search(row["answer"])
        every = args.every or (float(again.group(2)) if again and again.group(2) else RESULT_HOURS)
        at = time.strftime(TIME_FORMAT, time.localtime(now + every * 3600))
        text, asked = "not looked yet; ask again %s (every %g h)" % (at, every), stamp
        said = "asleep until then"
    else:
        text = {"satisfied": "satisfied", "change": "change it", "drop": "dropped"}[answer] + " " + stamp
        text += ": " + note if note else ""
        said = {"satisfied": "the stream can close its loose ends", "change": "send the change to its worker; a repeat "
                "`result` asks again", "drop": "dropped"}[answer]
    write_result(ledger, key, [row["deliverable"], row["link"], row["delivered"], asked, text])
    print("%s: %s; %s" % (row["deliverable"], text, said))
    return 0


FOLLOWUP_HOURS = 24  # the guide reviews recent fixes and deployments this often (SESSION_GUIDE_FOLLOWUP_HOURS, 0 = off)
FOLLOWUP_DAYS = 3  # how far back a review looks
RECHECK_HOURS = 24  # a fix not exercised yet comes back for a re-check this much later
RESULTS = ("proposed", "running", "verified", "not-exercised", "broken", "skipped")
VERIFY_SECTION = "## Verifications"
VERIFY_TABLE = ["| Thing | Where | Result | Checked | Evidence / session | Re-check |\n", "|---|---|---|---|---|---|\n"]
REVIEW_STAMP = "Last review: "
REF = re.compile(r"(?<![\w#])#(\d{2,6})\b|/pull/(\d{1,6})\b|(?<![\w.])(v\d+\.\d+\.\d+)\b")
DATE = re.compile(r"(?<![\d-])(?:(20\d\d)-)?(0[1-9]|1[0-2])-([0-2]\d|3[01])(?![\d-])")
# Where a clause says a fix went, strongest first. "released" counts for versions only: a pushed branch isn't a deploy.
WHERE = [("prod", re.compile(r"\bon prod(?:uction)?\b|\b(?:deployed|released|live|shipped|promoted) (?:to|on|in) "
                             r"prod(?:uction)?\b|\bprod(?:uction)? deploy(?:ed)?\b|\bprod since\b|\bpromoted\b", re.I)),
         ("staging", re.compile(r"\bon staging\b|\b(?:deployed|live) (?:to|on) staging\b|\bstaging deploy(?:ed)?\b"
                                r"|\bstaging since\b", re.I)),
         ("deployed", re.compile(r"\bdeployed\b|\bdeploy to cluster\b", re.I)),
         ("released", re.compile(r"\breleased\b|\btag(?:ged)?\b|\bpushed\b", re.I)),
         ("merged", re.compile(r"\bmerged\b", re.I))]
RANK = {"merged": 1, "released": 2, "deployed": 2, "staging": 3, "prod": 4}
# Words just before a marker that make it a plan, a wish or a denial ("not yet merged", "once #12 is merged").
NOT_YET = re.compile(r"(?:\b(?:not|no|nothing|never|before|once|until|unless|if|when|will|wait(?:s|ing)?|ask(?:ed)?|"
                     r"after|to be)"
                     r"\b|n't\b)[^.;]*$", re.I)
CLAUSE = re.compile(r"(?<=[.;!?])\s+|\n|\s+[—–]\s+|\s+(?:->|→)\s+")


def ref_key(match):
    pr, pull, version = match.groups()
    return version or "#" + (pr or pull)


def thing_key(text):
    """What a Verifications row (or a `verification` argument) is about: its first PR (#N) or version, else its words."""
    found = REF.search(text)
    return ref_key(found) if found else " ".join(text.lower().split())


def line_date(text, now):
    """Epoch noon of the first MM-DD (or YYYY-MM-DD) in `text`, or None. A date without a year more than 2 days ahead
    is last year's."""
    found = DATE.search(text)
    if not found:
        return None
    year = int(found.group(1) or time.localtime(now).tm_year)
    at = time.mktime((year, int(found.group(2)), int(found.group(3)), 12, 0, 0, 0, 0, -1))
    if not found.group(1) and at > now + 2 * 86400:
        at = time.mktime((year - 1, int(found.group(2)), int(found.group(3)), 12, 0, 0, 0, 0, -1))
    return at


def clause_hits(text, date, source):
    """[{key, where, date, evidence, source}]: the PRs and versions each clause of `text` says reached somewhere."""
    hits = []
    for clause in CLAUSE.split(text):
        refs = list(REF.finditer(clause))
        if not refs:
            continue
        for where, pattern in WHERE:
            said = [m for m in pattern.finditer(clause) if not NOT_YET.search(clause[max(0, m.start() - 30):m.start()])]
            keys = [ref_key(r) for r in refs if where != "released" or r.group(3)]
            if said and keys:
                evidence = " ".join(clause.strip(" -|*").split())
                hits += [dict(key=k, where=where, date=date, evidence=evidence[:220], source=source) for k in keys]
                break
    return hits


def ledger_hits(ledger, since, now):
    """Deployment hits in the ledger's lines dated since `since`, Verifications left out. A bullet with no date of its
    own takes the last date above it in its section (a heading's date counts); a table row only its own. Undated lines
    don't count: there's no telling how old they are."""
    hits, carried, skip = [], None, False
    for line in open(ledger, errors="replace"):
        if line.startswith("## "):
            skip, carried = line.startswith(VERIFY_SECTION), line_date(line, now)
            continue
        if skip or not line.strip():
            continue
        own = line_date(line, now)
        date = own if line.lstrip().startswith("|") else (own or carried)
        if own and not line.lstrip().startswith("|"):
            carried = own
        if date is not None and date >= since:
            hits += clause_hits(line.rstrip("\n"), date, "ledger")
    return hits


def transcript_texts(path, since):
    """(epoch, text) of each assistant text and SendMessage report in a transcript, newer than `since`."""
    with open(path, "rb") as f:
        for raw in f:
            if b'"assistant"' not in raw or not re.search(rb"(?i)merged|prod|staging|deploy|releas|tag|pushed", raw):
                continue
            try:
                d = json.loads(raw)
                at = calendar.timegm(time.strptime(d.get("timestamp", "")[:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                continue
            if d.get("type") != "assistant" or d.get("isSidechain") or at < since:
                continue
            for b in (d.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    yield at, b.get("text") or ""
                elif b.get("type") == "tool_use" and b.get("name") == "SendMessage":
                    yield at, str((b.get("input") or {}).get("message") or "")


def transcript_hits(ledger, since):
    """Deployment hits in what the ledger's sessions (not ignored, not guides) said since `since`."""
    hits = []
    for rid, (level, cell) in session_levels(ledger).items():
        if level in ("IGNORED", "RETIRED"):
            continue
        paths = [p for p in glob.glob(os.path.join(config_dir(), "projects", "*", rid + "*.jsonl"))
                 if os.path.getmtime(p) >= since]
        for path in paths:
            content = marker_content(os.path.basename(path)[:-6])
            if content is not None and content not in WORKER_MARKERS + (DONE,):  # a guide: the ledger has its words
                continue
            name = re.sub(r"\s*\[[0-9a-fA-F]{6,36}\].*", "", cell)
            name = re.sub(r"^(?:[^\w(']+)?(?:\(g\)\s*)?", "", name).strip("' ") or "untitled"
            for at, text in transcript_texts(path, since):
                hits += clause_hits(text, at, "'%s' [%s]" % (name, rid))
    return hits


def verification_rows(ledger):
    """{key: {thing, where, result, checked, evidence, recheck}} from the ledger's Verifications table."""
    found, inside = {}, False
    for line in open(ledger, errors="replace"):
        if line.startswith("## "):
            inside = line.startswith(VERIFY_SECTION)
        elif inside and line.lstrip().startswith("|"):
            cells = split_row(line)
            if len(cells) >= 6 and not set(cells[0]) <= set("-: ") and cells[0] != "Thing":
                found[thing_key(cells[0])] = dict(zip(("thing", "where", "result", "checked", "evidence", "recheck"),
                                                      cells))
    return found


def last_review(ledger):
    inside = False
    for line in open(ledger, errors="replace"):
        if line.startswith("## "):
            inside = line.startswith(VERIFY_SECTION)
        elif inside and line.startswith(REVIEW_STAMP):
            try:
                return time.mktime(time.strptime(line[len(REVIEW_STAMP):].strip(), TIME_FORMAT))
            except ValueError:
                return None
    return None


def stamp_review(ledger):
    lines = open(ledger, errors="replace").read().splitlines(True)
    start, end = section_span(lines, VERIFY_SECTION, VERIFY_SECTION, "## Log")
    text = REVIEW_STAMP + time.strftime(TIME_FORMAT) + "\n"
    old = [i for i in range(start + 1, end) if lines[i].startswith(REVIEW_STAMP)]
    if old:
        lines[old[0]] = text
    else:
        at = end
        while at > start + 1 and not lines[at - 1].strip():
            at -= 1
        lines.insert(at, text)
    write_ledger(ledger, lines)


def followups(ledger, days=FOLLOWUP_DAYS, transcripts=True, now=None):
    """{propose, recheck}: things that reached prod, staging or a merge in the last `days` with no Verifications row,
    and rows left "not-exercised" whose Re-check time has come. Strongest place first, then newest."""
    now = now or time.time()
    since = now - days * 86400
    hits = ledger_hits(ledger, since, now) + (transcript_hits(ledger, since) if transcripts else [])
    things = {}
    for h in hits:
        t = things.setdefault(h["key"], dict(h, sources=[]))
        if (RANK[h["where"]], h["date"] or 0) > (RANK[t["where"]], t["date"] or 0):
            t.update(where=h["where"], date=h["date"], evidence=h["evidence"])
        if h["source"] not in t["sources"]:
            t["sources"].append(h["source"])
    rows, recheck = verification_rows(ledger), []
    for key, row in rows.items():
        if row["result"].lower().replace(" ", "-") not in ("not-exercised", "not-exercised-yet"):
            continue
        try:
            due = time.mktime(time.strptime(row["recheck"], TIME_FORMAT)) <= now
        except ValueError:
            due = True
        if due:
            recheck.append(row)
    propose = [t for key, t in things.items() if key not in rows]
    propose.sort(key=lambda t: (-RANK[t["where"]], -(t["date"] or 0)))
    return dict(propose=propose, recheck=recheck)


def followup_hours():
    try:
        return float(os.environ.get("SESSION_GUIDE_FOLLOWUP_HOURS", FOLLOWUP_HOURS))
    except ValueError:
        return FOLLOWUP_HOURS


def followup_due(ledger):
    """How many things a review would find in the ledger alone, when a review is due; else 0. Off at 0 hours."""
    hours, last = followup_hours(), last_review(ledger)
    if hours <= 0 or (last and time.time() - last < hours * 3600):
        return 0
    found = followups(ledger, transcripts=False)
    return len(found["propose"]) + len(found["recheck"])


def describe_followup(t):
    when = time.strftime("%m-%d", time.localtime(t["date"])) if t["date"] else "undated"
    return "%s %s, seen %s (%s): %s" % (t["key"], "on " + t["where"] if t["where"] in ("prod", "staging") else t["where"],
                                       when, "; ".join(t["sources"][:3]), t["evidence"][:180])


def cmd_followups(args):
    ledger = os.path.expanduser(args.ledger or require_ledger())
    found = followups(ledger, args.days, not args.ledger_only)
    for t in found["propose"][:args.limit]:
        print("Follow-up: " + describe_followup(t))
    if len(found["propose"]) > args.limit:
        print("... and %d more (--limit)" % (len(found["propose"]) - args.limit))
    for row in found["recheck"]:
        print("Re-check: %s on %s: not exercised yet at %s (%s)" % (row["thing"], row["where"], row["checked"],
                                                                   row["evidence"]))
    last = last_review(ledger)
    if args.reviewed:
        stamp_review(ledger)
        last = time.time()
    hours = followup_hours()
    nxt = ("off" if hours <= 0 else time.strftime(TIME_FORMAT, time.localtime(last + hours * 3600)) if last else "now")
    print("%d to propose, %d to re-check; last review %s; next review %s"
          % (len(found["propose"]), len(found["recheck"]),
             time.strftime(TIME_FORMAT, time.localtime(last)) if last else "never", nxt))
    return 0


def cmd_verification(args):
    ledger = os.path.expanduser(args.ledger or require_ledger())
    result = args.result.lower().replace(" ", "-").replace("_", "-")
    result = "not-exercised" if result == "not-exercised-yet" else result
    if result not in RESULTS:
        raise SystemExit("result is one of: %s" % ", ".join(RESULTS))
    thing = " ".join(args.thing.split())
    if not thing:
        raise SystemExit("say what was verified, for example '#5560 box default fix'")
    key, now = thing_key(thing), time.time()
    old = verification_rows(ledger).get(key, {})
    seen = [h for h in ledger_hits(ledger, 0, now) if h["key"] == key]
    where = args.where or old.get("where") or (max(seen, key=lambda h: RANK[h["where"]])["where"] if seen else "—")
    evidence = " ".join((args.evidence or "").split()) or old.get("evidence") or "—"
    recheck = (time.strftime(TIME_FORMAT, time.localtime(now + args.recheck_hours * 3600))
               if result == "not-exercised" else "—")
    write_row(ledger, VERIFY_SECTION, VERIFY_SECTION, VERIFY_TABLE, lambda cells: thing_key(cells[0]), key,
              [thing, where, result, time.strftime(TIME_FORMAT, time.localtime(now)), evidence, recheck], before="## Log")
    print("%s: %s (%s)%s" % (thing, result, where, "; re-check from " + recheck if result == "not-exercised" else ""))
    return 0


def cmd_sweep(args):
    ledger = args.ledger or marker_content(resolve_session(None))
    if not ledger or not os.path.isfile(os.path.expanduser(ledger)):
        raise SystemExit("no ledger: pass its path, or run this from the guide")
    found = untracked(os.path.expanduser(ledger), os.environ.get("CLAUDE_CODE_SESSION_ID", ""), args.hours)
    for session in found:
        print(describe(session))
    print("New: %d" % len(found))
    for sid in closable(os.path.expanduser(ledger)):
        print("Closable: [%s] has only DONE rows but is still marked; run `done %s`" % (sid[:8], sid))
    for sid in settle_closed():
        print("Held: [%s] is closed but a process still holds it; SendMessage it the CLOSE message" % sid[:8])
    return 0


def cmd_reconcile(args):
    """Print reconcile's flags for a ledger. Reads only, so it runs against any ledger without being its guide."""
    ledger = os.path.expanduser(args.ledger or require_ledger())
    module = reconcile_module()
    if module is None:
        raise SystemExit("guide_reconcile.py is missing next to %s" % os.path.abspath(__file__))
    if not os.path.isfile(ledger):
        raise SystemExit("no ledger at %s" % ledger)
    flags = module.reconcile(ledger, grace_minutes=args.grace_minutes, me=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    for flag in flags:
        print(module.describe(flag, "python3 " + os.path.abspath(__file__)))
    print("%d to reconcile" % len(flags) if flags else "Nothing to reconcile: every open row matches its session.")
    return 0


def full_id(id8, wait=5.0):
    """The full session id behind the short id `claude --bg` prints: its job's state.json, else its transcript's name.
    Waits up to `wait` seconds for either to appear; None when neither does."""
    end = time.time() + wait
    while True:
        try:
            with open(os.path.join(config_dir(), "jobs", id8, "state.json")) as f:
                sid = json.load(f).get("sessionId") or ""
            if sid.startswith(id8):
                return sid
        except (OSError, ValueError):
            pass
        hits = glob.glob(os.path.join(config_dir(), "projects", "*", id8 + "*.jsonl"))
        if len(hits) == 1:
            return os.path.basename(hits[0])[:-6]
        if time.time() >= end:
            return None
        time.sleep(0.05)


def cmd_launch(args):
    """Start a worker with `claude --bg <args>` and mark it guided (or watched) before its first tool call.

    `claude --bg` ignores --session-id, and --resume of an unknown id fails, so a new session's id is known only once
    the command prints it ("backgrounded · <id8>"); the marker is written right then, while the command may still run
    and the worker's first model call is in flight. With `--resume <id>` the id is known first, so the marker is
    written before the command runs. SESSION_GUIDE_CLAUDE names another binary (tests)."""
    import shlex
    import subprocess
    level = WATCHED if args.watched else GUIDED
    extra = list(args.claude_args)
    if extra[:1] == ["--"]:
        extra = extra[1:]
    if not extra:
        raise SystemExit("pass the claude arguments after --, for example: launch -- --model sonnet \"<brief>\"")
    stream = launch_stream(args)  # first: a wrong key starts nothing
    command = shlex.split(os.environ.get("SESSION_GUIDE_CLAUDE") or "claude")
    command += [] if "--bg" in extra or "--background" in extra else ["--bg"]
    command += extra
    sid = None
    if "--resume" in extra[:-1]:
        given = extra[extra.index("--resume") + 1]
        sid = given if len(given) == 36 else resolve_session(given)
        if marker_content(sid) not in (None,) + WORKER_MARKERS:
            raise SystemExit("%s is a guide or closed; it is not launched as a worker" % sid[:8])
        write_marker(sid, level)  # before the command: the resumed session's first tool call already sees it
        put_on_stream(stream, sid)
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    printed = None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        found = re.search(r"\bbackgrounded\W+([0-9a-f]{8})\b", line)
        if found and not printed:
            printed = found.group(1)
            if not (sid and sid.startswith(printed)):
                sid = full_id(printed)
                if sid:
                    write_marker(sid, level)  # now, while the worker's first model call is still in flight
                    put_on_stream(stream, sid)
    code = proc.wait()
    if code or not printed:
        print("claude exited %d%s; nothing marked for it" % (code, "" if printed else " without printing a session id"))
        return code or 1
    if not sid:
        print("launched [%s] but found no full session id for it in 5 s: run `python3 %s %s %s` now"
              % (printed, os.path.abspath(__file__), level, printed))
        return 1
    print("launched [%s] %s, marked %s the moment it started. Give it its Sessions row now: | <title> [%s] | %s | "
          "... |" % (sid[:8], sid, level, sid[:6], "WATCHED" if args.watched else "MANAGED"))
    return 0


def launch_stream(args):
    """(ledger, key) of the stream `launch` puts the worker on, or None. SystemExit when the stream can't be had: nothing
    has started yet. A predecessor on no stream (or on one that ended) gives none, with a line that says so."""
    if not args.stream and not args.successor_of:
        return None
    streams = streams_module()
    if streams is None:
        raise SystemExit("guide_streams.py can't be loaded; launch without --stream / --successor-of")
    ledger = os.path.expanduser(require_ledger())
    key = args.stream
    if not key:
        before = resolve_session(args.successor_of)
        key = streams.stream_key_of(ledger, before)
        found = streams.read(ledger).get(key) if key else None
        if not found or found["state"] != "open":
            print("%s is on no open stream, so its successor gets no icon" % before[:8])
            return None
    if streams.stream(streams.read(ledger), key)["state"] != "open":
        raise SystemExit("stream %s has ended; `stream add %s` reopens it" % (key, key))
    return ledger, key


def put_on_stream(stream, session_id):
    """Best effort: the worker runs already, so a failure is a line to act on, never a stop."""
    if stream:
        try:
            print(streams_module().assign(stream[0], stream[1], session_id))
        except (Exception, SystemExit) as error:
            print("no stream icon for %s: %s" % (session_id[:8], error))


def cmd_unguided(args):
    sid = resolve_session(args.session)
    content = marker_content(sid)
    if content is not None and content not in WORKER_MARKERS:
        print("%s is %s, not a guided or watched worker; left as it is"
              % (sid[:8], "closed" if content == DONE else "a guide"))
        return 0
    write_marker(sid, UNGUIDED)
    print("%s is unmanaged; the prefix comes off its title on its next prompt" % sid[:8])
    return 0


def guide_ledger():
    """The ledger in this session's guide marker, else the one ledger all guide markers name, else None."""
    own = marker(os.environ.get("CLAUDE_CODE_SESSION_ID") or "-")
    found = set()
    for path in [own] + glob.glob(os.path.join(config_dir(), "session-guide", "guides", "*")):
        content = open(path).read().strip() if os.path.isfile(path) else ""
        if content and content not in WORKER_MARKERS + (RETIRED, DONE) and os.path.isfile(os.path.expanduser(content)):
            if path == own:
                return os.path.expanduser(content)
            found.add(os.path.expanduser(content))
    return found.pop() if len(found) == 1 else None


def close_rows(ledger, session_id):
    """Set the Level of every Sessions row naming `session_id` to DONE; how many rows changed."""
    want, changed, in_sessions, out = session_id[:6].lower(), 0, False, []
    for line in open(ledger, errors="replace").read().splitlines(True):
        if line.startswith("## "):
            in_sessions = line.strip() == "## Sessions"
        elif in_sessions and line.lstrip().startswith("|"):
            parts = line.split("|")
            if len(parts) > 3 and row_id(parts[1]) == want and parts[2].split()[:1] not in ([], ["DONE"]):
                parts[2] = re.sub(r"\S+", "DONE", parts[2], count=1)
                line, changed = "|".join(parts), changed + 1
        out.append(line)
    if changed:
        with open(ledger + ".tmp", "w") as f:
            f.write("".join(out))
        os.replace(ledger + ".tmp", ledger)
    return changed


def session_alive(session_id):
    """True when a running Claude process holds this session (~/.claude/sessions/<pid>.json with a live pid)."""
    for path in glob.glob(os.path.join(config_dir(), "sessions", "*.json")):
        try:
            info = json.load(open(path))
            if info.get("sessionId") == session_id:
                os.kill(int(info["pid"]), 0)
                return True
        except PermissionError:
            return True  # the process exists, it is just not ours
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return False


def retitle_stopped_job(session_id, content=DONE):
    """Put the closed title (or the one for `content`) into the job's state.json `name`, which is what `claude agents` and claude-top show, when
    no process holds the session. Returns a line to print, or None when there is nothing to do.

    Claude Code has no command that renames a session without running a turn in it (the hook answer and /rename both
    need a live session), so for a session that is already over this one-key edit is the only way. A live session is
    never touched: its own process owns the file, and its next prompt applies the hook's title."""
    path = os.path.join(config_dir(), "jobs", session_id[:8], "state.json")
    try:
        with open(path) as f:
            state = json.load(f)
        if state.get("sessionId") != session_id or not state.get("name"):
            return None
        if session_alive(session_id):
            return ("its process is still running: its title changes on its next prompt (send it CLOSE), or at a guide's "
                    "next prompt after the process ends")
        name = worker_title(content, state["name"], *title_icons(session_id))
        if not name:
            return None
        state["name"] = name
        with open(path + ".tmp", "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(path + ".tmp", path)
        return "no process holds it, so its job name was set to %r (an edit of state.json's name; no command renames a finished session)" % name
    except (OSError, ValueError):
        return None


def settle_closed():
    """Finish `done` for every closed session whose job still has its old name: rename it if its process has ended.

    `done` can't rename a session a process still holds, and a closed session never gets another prompt on its own, so
    the rename has to be retried. Returns the ids a running process holds at a colored title; only a prompt can change
    those. One with a plain title isn't returned, since a check mark isn't worth a turn: it is renamed when it ends."""
    held = []
    for path in glob.glob(os.path.join(config_dir(), "session-guide", "guides", "*")):
        sid = os.path.basename(path)
        if marker_content(sid) != DONE:
            continue
        try:
            with open(os.path.join(config_dir(), "jobs", sid[:8], "state.json")) as f:
                state = json.load(f)
        except (OSError, ValueError):
            continue
        if state.get("sessionId") != sid or not worker_title(
                DONE, state.get("name") or "", *title_icons(sid)):
            continue
        if not session_alive(sid):
            retitle_stopped_job(sid)
        elif worker_title(UNGUIDED, state["name"]):  # it has a prefix to take off
            held.append(sid)
    return sorted(held)


def cmd_done(args):
    sid = resolve_session(args.session)
    content = marker_content(sid)
    if content is not None and content not in WORKER_MARKERS + (DONE,):
        raise SystemExit("%s is a %sguide; retire it instead" % (sid[:8], "retired " * (content == RETIRED)))
    write_marker(sid, DONE)
    print("%s is closed; %r goes before its title" % (sid[:8], done_prefix()))
    note = retitle_stopped_job(sid)
    print(note or "its title changes on its next prompt")
    ledger = guide_ledger()
    if ledger is None:
        print("no single guide ledger found: set its row's Level to DONE yourself")
    else:
        row = " ".join(l for l in open(ledger, errors="replace") if l.lstrip().startswith("|") and
                       row_id(split_row(l)[0]) == sid[:6].lower())
        print("%d row(s) in %s set to DONE" % (close_rows(ledger, sid), ledger))
        write_waiting(ledger, sid[:6].lower(), None)
        shared_note(ledger, row, sid[:6].lower())
    return 0


def write_marker(session_id, content):
    os.makedirs(os.path.dirname(marker(session_id)), exist_ok=True)
    with open(marker(session_id), "w") as f:
        f.write(content + "\n")
    sync_session_titles(session_id, content)


def sync_session_titles(session_id, content):
    """Make session-titles give the title we want, since its hook's answer overrides ours. Best effort."""
    home = os.path.join(config_dir(), "session-titles")
    path = os.path.join(home, session_id + ".json")
    if not os.path.isfile(path):
        return
    try:
        import fcntl  # not on Windows: the except below skips the sync there
        os.makedirs(os.path.join(home, "locks"), exist_ok=True)
        with open(os.path.join(home, "locks", session_id + ".lock"), "w") as lock:  # the one session-titles takes
            fcntl.flock(lock, fcntl.LOCK_EX)
            with open(path) as f:
                state = json.load(f)
            before = json.dumps(state)
            if content in WORKER_MARKERS + (DONE, None):
                icons = title_icons(session_id)
                state["origin"] = worker_title(content, state.get("origin") or "", *icons) or state.get("origin") or ""
                last_set = worker_title(content, state.get("last_set") or "", *icons)
                if last_set:  # a resume restores last_set; keep the old one known, so it isn't read as a rename
                    state["history"] = (state.get("history") or []) + [last_set]
                    state["last_set"] = last_set
            else:
                state["off"] = True
            if json.dumps(state) != before:
                with open(path + ".tmp", "w") as f:
                    json.dump(state, f, ensure_ascii=False, indent=1)
                os.replace(path + ".tmp", path)
    except Exception:  # fail open, like the hook: a title is never worth an error
        pass


def main(argv=None):
    p = argparse.ArgumentParser(description="Pin the guide session's title and mark guided workers.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hook", help="run as a UserPromptSubmit / SessionStart hook")
    mark = sub.add_parser("mark", help="mark a session as the guide of a ledger")
    mark.add_argument("ledger")
    mark.add_argument("--session")
    unmark = sub.add_parser("unmark", help="unmark a guide session")
    unmark.add_argument("--session")
    retire = sub.add_parser("retire", help="retire a guide that handed over (faded red title)")
    retire.add_argument("session", nargs="?")
    retire.add_argument("--to", help="the new guide's uds: socket, for the retired guide to forward to")
    retire.add_argument("--force", action="store_true",
                        help="retire although open rows need a guide; they go into the ledger's ## Handoff table")
    retire.add_argument("--check", action="store_true", help="only run the gate: exit 1 while open rows need a guide")
    launch = sub.add_parser("launch", help="start a worker with `claude --bg`, marked guided before its first tool call")
    launch.add_argument("--watched", action="store_true", help="mark it watched, not guided")
    launch.add_argument("--stream", metavar="KEY", help="the stream (project) it works on: its icon goes into the title")
    launch.add_argument("--successor-of", metavar="ID", help="it takes over from this session, and keeps its stream")
    launch.add_argument("claude_args", nargs=argparse.REMAINDER, help="-- then the claude arguments")
    rec = sub.add_parser("reconcile", help="open rows whose session ended, is blocked or handed off; never writes")
    rec.add_argument("--ledger", help="any ledger (default: this guide's)")
    rec.add_argument("--grace-minutes", type=float, default=None,
                     help="leave jobs that ended this recently alone (default SESSION_GUIDE_GRACE_MINUTES or 3)")
    guided = sub.add_parser("guided", help='a MANAGED worker: orange blocks and "(g) " before its title')
    guided.add_argument("session", nargs="?")
    watched = sub.add_parser("watched", help="a WATCHED session: light gray blocks before its title")
    watched.add_argument("session", nargs="?")
    active = sub.add_parser("active", help="running, not managed or watched: blue blocks before its title")
    active.add_argument("session", nargs="?")
    sweep = sub.add_parser("sweep", help="list recently active sessions the ledger has no row for")
    sweep.add_argument("ledger", nargs="?")
    sweep.add_argument("--hours", type=float, default=12)
    settle = sub.add_parser("settle", help="list sessions that aren't settled and reminders that are due")
    settle.add_argument("ledger", nargs="?")
    settle.add_argument("--idle-hours", type=float, default=IDLE_HOURS)
    waiting = sub.add_parser("waiting", help="this session waits on the user: a reminder, due now; or `ask`: a "
                                             "question the guide owes the user")
    waiting.add_argument("session", help="a session id, or `ask` for an owed question")
    waiting.add_argument("what")
    waiting.add_argument("--hours", type=float, help="`ask` only: ask in this many hours (default: now)")
    waiting.add_argument("--at", help="`ask` only: ask at this local time, YYYY-MM-DD HH:MM")
    waiting.add_argument("--closes", action="append", metavar="EVENT",
                         help="repeatable: pr:#N, result:<artifact id>, ticket:<ID> or session:<id8>; the audit closes "
                              "the reminder itself once every one has happened")
    sleep = sub.add_parser("sleep", help="put a session's reminder off")
    sleep.add_argument("session")
    sleep.add_argument("hours", type=float)
    unwait = sub.add_parser("unwait", help="it no longer waits on the user: the reminder goes")
    unwait.add_argument("session")
    unguided = sub.add_parser("unguided", help="no longer managed or watched: the prefix comes off")
    unguided.add_argument("session", nargs="?")
    unwatched = sub.add_parser("unwatched", help="the same as unguided")
    unwatched.add_argument("session", nargs="?")
    done = sub.add_parser("done", help='closed: "\u2705 " before its title, never orange, gray, blue or red again')
    done.add_argument("session", nargs="?")
    follow = sub.add_parser("followups", help="recent fixes and deployments with no verification recorded")
    follow.add_argument("ledger", nargs="?")
    follow.add_argument("--days", type=float, default=FOLLOWUP_DAYS)
    follow.add_argument("--ledger-only", action="store_true", help="skip the sessions' transcripts")
    follow.add_argument("--limit", type=int, default=12, help="print at most this many to propose")
    follow.add_argument("--reviewed", action="store_true", help="stamp the review as done now")
    verify = sub.add_parser("verification", help="record a verification of a fix or deployment")
    verify.add_argument("thing")
    verify.add_argument("result", help=" | ".join(RESULTS))
    verify.add_argument("evidence", nargs="?", default="")
    verify.add_argument("--where", help="prod, staging, merged, ... (default: what the ledger says)")
    verify.add_argument("--recheck-hours", type=float, default=RECHECK_HOURS)
    verify.add_argument("--ledger")
    result = sub.add_parser("result", help="a finished deliverable for the user, with its link: asks for a verdict")
    result.add_argument("deliverable", help='for example "deck slide 4: pricing"')
    result.add_argument("link", help="the exact link the user opens")
    result.add_argument("--from", dest="source", help="the session that delivered it, as 'title [id6]'")
    result.add_argument("--ledger")
    answer = sub.add_parser("result-answer", help="the user's verdict on a deliverable")
    answer.add_argument("deliverable")
    answer.add_argument("answer", help=" | ".join(ANSWERS))
    answer.add_argument("--note", help="what to change, or why it was dropped")
    answer.add_argument("--every", type=float, help="not-looked: ask again every this many hours (default %s)"
                                                    % RESULT_HOURS)
    answer.add_argument("--ledger")
    claims = claims_module()
    if claims is not None:
        claims.add_parser(sub)
    streams = streams_module()
    if streams is not None:
        streams.add_parser(sub)
    args = p.parse_args(argv)
    commands = {"hook": lambda a: cmd_hook(), "mark": cmd_mark, "unmark": cmd_unmark, "retire": cmd_retire,
                "guided": lambda a: set_level(a, GUIDED, guided_prefix()),
                "watched": lambda a: set_level(a, WATCHED, watched_prefix()),
                "active": lambda a: set_level(a, ACTIVE, active_prefix()),
                "unguided": cmd_unguided, "unwatched": cmd_unguided, "done": cmd_done, "sweep": cmd_sweep,
                "settle": cmd_settle, "waiting": cmd_waiting, "sleep": cmd_sleep, "unwait": cmd_unwait,
                "followups": cmd_followups, "verification": cmd_verification, "result": cmd_result,
                "result-answer": cmd_result_answer, "launch": cmd_launch, "reconcile": cmd_reconcile,
                "claim": lambda a: claims.cmd_claim(a), "stream": lambda a: streams.cmd_stream(a)}
    return commands[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
