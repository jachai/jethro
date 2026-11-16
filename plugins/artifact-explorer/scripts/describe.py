"""Description queue: ingest Artifact-list rows, set descriptions, launch the background describer, status."""
import json
import re
from html.parser import HTMLParser
import os
import shutil
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import db  # noqa: E402
import importer  # noqa: E402

PENDING = "desc_status='pending' AND (description IS NULL OR description='')"  # status counts only


def first(row, *keys):
    for k in keys:
        if row.get(k) not in (None, ""):
            return row[k]
    return None


def to_ts(v):
    """Unix seconds from a number (seconds or ms) or an ISO-8601 string; None when unknown."""
    if isinstance(v, (int, float)):
        return v / 1000.0 if v > 1e11 else float(v)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    return None


def owned_of(row):
    scope = str(first(row, "scope") or "").lower()
    if scope in ("mine", "own", "owned"):
        return 1
    if scope in ("shared", "shared_with_me"):
        return 0
    o = row.get("owned")
    return None if o is None else int(bool(o))


def access_of(row):
    """'view' | 'comment' | 'edit' from a list row's access ("can edit" counts), else None."""
    a = str(first(row, "access", "permission") or "").lower().replace("can ", "").strip()
    return a if a in ("view", "comment", "edit") else None


def mark_revoked(con, listed_ids, now):
    """Rows owned by someone else, seen in an earlier shared list, missing from this complete one: shared_gone
    = now. Returns the number marked. The caller guarantees the list had at least one shared row."""
    listed = set(listed_ids)
    n = 0
    for r in con.execute("SELECT id FROM artifacts WHERE owned=0 AND shared_seen IS NOT NULL AND shared_gone IS NULL").fetchall():
        if r["id"] not in listed:
            con.execute("UPDATE artifacts SET shared_gone=?, updated=? WHERE id=?", (now, now, r["id"]))
            n += 1
    return n


def ingest_list(data, file, shared_complete=False):
    with open(file, encoding="utf-8") as f:
        rows = json.load(f)
    if isinstance(rows, dict):
        rows = first(rows, "artifacts", "items", "rows") or []
    con = db.connect(data)
    n, now = 0, time.time()
    listed, shared = set(), 0
    for r in rows:
        aid = db.resolve(con, db.id_from_url(first(r, "url", "link")) or first(r, "id"))
        if not aid:
            continue
        old = db.get(con, aid)
        modified = to_ts(first(r, "updated", "modified", "updatedAt"))
        if modified is not None and old is not None and (old["modified"] or 0) >= modified:
            modified = None  # the list gives a date only; never replace a more precise time with midnight
        desc = first(r, "description", "desc", "summary")
        sharing = first(r, "sharing")
        if desc:
            status = "ok"
        else:  # no new text: a row without a description (and not skipped) waits for one
            status = "pending" if old is None or (not old["description"] and old["desc_status"] in (None, "pending")) else None
        db.upsert_artifact(
            con, aid, url=first(r, "url", "link"), title=first(r, "title", "name"), kind=first(r, "kind", "type"),
            owned=owned_of(r), size=first(r, "size"), created=to_ts(first(r, "created", "createdAt")),
            modified=modified,
            sharing=sharing if sharing is None or isinstance(sharing, str) else json.dumps(sharing),
            creator=first(r, "creator", "owner", "author") if owned_of(r) == 0 else None,
            description=desc, desc_source="publish" if desc else None,
            desc_status=status, access=access_of(r) if owned_of(r) == 0 else None,
            other_org=int(bool(r["other_org"])) if owned_of(r) == 0 and r.get("other_org") is not None else None)
        listed.add(aid)
        if owned_of(r) == 0:
            shared += 1
            con.execute("UPDATE artifacts SET shared_seen=?, shared_gone=NULL WHERE id=?", (now, aid))
        n += 1
    if shared_complete:
        if shared:
            gone = mark_revoked(con, listed, now)
            if gone:
                common.log(data, "ingest-list: %d shared rows no longer in the shared list" % gone)
        else:
            common.log(data, "ingest-list: --shared-complete with no shared rows: nothing marked revoked")
    db.fold_twins(con)
    con.commit()
    print("ingested %d rows" % n)
    return 0


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, s):
        if not self.skip and s.strip():
            self.out.append(s.strip())


def excerpt(path, chars=3000, json_field=None):
    """Visible text of a saved artifact file (HTML or plain text), whitespace-collapsed and capped. With
    json_field the file is JSON and that field's string is the text (a Dashboard's files/index.html.json);
    excerpt_for passes it for .json files only."""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read(2_000_000)
    if json_field:
        try:
            raw = json.loads(raw).get(json_field)
        except (ValueError, AttributeError):
            raw = None
        raw = raw if isinstance(raw, str) else ""
    if "<" in raw and ">" in raw:
        p = _Text()
        p.feed(raw)
        raw = " ".join(p.out)
    return " ".join(raw.split())[:chars]


def share(texts, chars):
    """Cut several sources so all of them fit in `chars` together: short ones keep everything, the rest split
    what is left equally (a long dashboard page cannot push its dataset titles out). Order is kept."""
    budget = chars - max(len(texts) - 1, 0)  # the joining spaces
    caps, left = {}, [i for i, t in enumerate(texts) if t]
    while left:
        each = max(budget // len(left), 0)
        fits = [i for i in left if len(texts[i]) <= each]
        if not fits:
            for i in left:
                caps[i] = each
            break
        for i in fits:
            caps[i] = len(texts[i])
            budget -= len(texts[i])
            left.remove(i)
    return [t[:caps.get(i, 0)] for i, t in enumerate(texts)]


MIN_TEXT = 50  # fewer visible characters than this is a viewer shell, not something to describe
TYPED = {"docs", "slides", "data", "dashboard"}  # kinds whose index.html is only the viewer shell (their source is elsewhere)


def _keep_copy(data, r, paths):
    """Someone else's page: keep its HTML file in DATA/copies/<id>.html (for when the share is revoked).
    Own rows never get a copy. Returns the relative path or None."""
    if r["owned"] != 0 or not paths or not str(paths[0]).lower().endswith((".html", ".htm")):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", r["id"]):
        return None
    try:
        os.makedirs(os.path.join(data, "copies"), exist_ok=True)
        shutil.copyfile(paths[0], os.path.join(data, "copies", r["id"] + ".html"))
    except OSError:
        return None
    return "copies/%s.html" % r["id"]


def excerpt_for(data, paths, out, aid=None, kind=None, chars=3000, json_field=None):
    """Write the excerpt of one or more saved source files (joined in order) to `out` for the describer agent.
    A source with almost no text marks the row 'skipped' (with the reason) so no run picks it again.
    Returns (text, skipped)."""
    paths = [paths] if isinstance(paths, str) else list(paths)
    texts = [excerpt(p, chars, json_field if p.lower().endswith(".json") else None) for p in paths]
    text = " ".join(t for t in share(texts, chars) if t)
    kind = db.norm_kind(kind)
    skipped = len(text) < MIN_TEXT
    with open(out, "w", encoding="utf-8") as f:
        f.write("" if skipped else text)
    if aid:
        con = db.connect(data)
        if db.get(con, aid) is None:  # the id comes from the run; never invent a row
            con.close()
            return text, skipped
        r = db.get(con, aid)
        copy = _keep_copy(data, r, paths)
        if copy:
            db.upsert_artifact(con, aid, local_copy=copy)
        typed = (kind or r["kind"] or "").lower() in TYPED
        if skipped and typed:  # a typed artifact's own source came back empty: show the title, `retry` tries again
            if kind:
                db.upsert_artifact(con, aid, kind=kind)
            con.commit()
            con.close()
            set_no_source(data, aid)
            return text, skipped
        if skipped:
            db.upsert_artifact(con, aid, kind=kind, desc_status="skipped",
                               desc_note="no text: under %d characters" % MIN_TEXT)
        elif kind:
            db.upsert_artifact(con, aid, kind=kind)
        con.commit()
        con.close()
    return text, skipped


def set_desc(data, aid, text):
    con = db.connect(data)
    db.upsert_artifact(con, aid, description=text.strip()[:200], desc_source="describer", desc_status="ok")
    con.commit()
    return 0


def set_no_source(data, aid, con=None):
    """No readable source for this artifact (connector absent, read refused): its title stands in, ranked
    below any real description, so a later describer sentence still wins. With `con` the write goes on that
    connection and the caller commits (a second connection would hit the caller's write lock)."""
    own = con is None
    if own:
        con = db.connect(data)
    r = db.get(con, aid)
    if r is not None and not r["description"]:
        db.upsert_artifact(con, aid, description=(r["title"] or aid)[:200], desc_source="title", desc_status="no-source")
        if own:
            con.commit()
    if own:
        con.close()
    return 0


def set_kind(data, aid, kind):
    con = db.connect(data)
    if db.get(con, aid) is not None and db.norm_kind(kind):
        db.upsert_artifact(con, aid, kind=db.norm_kind(kind))
        con.commit()
    con.close()
    return 0


def requeue_no_source(con, win=None):
    """Put title-only rows and the typed rows 0.1.2-0.1.3 skipped back in the queue, inside the window only
    (an older row put back would show "pending" with nothing ever picking it). Returns the count."""
    cond, wargs = db.window_sql(win) if win is not None else ("1=1", [])
    n = con.execute("UPDATE artifacts SET description=NULL, desc_source=NULL, desc_status='pending', desc_note=NULL, "
                    "updated=? WHERE ((desc_status='no-source' AND desc_source='title') OR "
                    "(desc_status='skipped' AND desc_note='no text: typed artifact')) AND " + cond,
                    [time.time()] + list(wargs)).rowcount
    con.commit()
    return n


def set_sharing(data, aid, text):
    con = db.connect(data)
    db.upsert_artifact(con, aid, sharing=" ".join(text.split())[:80])
    con.commit()
    return 0


COLS = "id,url,title,kind,owned,thumb_status,desc_status,modified,local_path"


def list_rows(con, owned=False, desc_status=None, thumb_status=None, limit=None, need_desc=False, win=None):
    """The one row query: `ae rows`, `ae pending` and the describer launch all come through here.
    `win` (db.window) keeps only rows inside the window."""
    where, args = [], []
    if win is not None:
        cond, wargs = db.window_sql(win)
        where.append(cond)
        args += wargs
    if owned:
        where.append("owned=1")
    if desc_status:
        where.append("desc_status=?")
        args.append(desc_status)
    if thumb_status:
        where.append("thumb_status=?")
        args.append(thumb_status)
    if need_desc:
        where.append("(description IS NULL OR description='')")
    if desc_status == "pending" and need_desc:
        where.append("(owned=1 OR shared_gone IS NULL)")
    sql = "SELECT %s FROM artifacts%s ORDER BY owned DESC, modified DESC, id" % (
        COLS, " WHERE " + " AND ".join(where) if where else "")
    if limit is not None:
        sql += " LIMIT %d" % limit
    return [dict(r) for r in con.execute(sql, args)]


def rows(data, **kw):
    print(json.dumps(list_rows(db.connect(data), **kw)))
    return 0


def pending_rows(con, owned_only, win=None):
    return list_rows(con, owned=owned_only, desc_status="pending", need_desc=True, win=win)


def data_window(data, con):
    return db.window(con, common.load_config(data))


def pending(data, owned_only=False, as_json=False, retry_no_source=False, limit=None):
    con = db.connect(data)
    if retry_no_source:
        requeue_no_source(con, data_window(data, con))
    rs = pending_rows(con, owned_only, data_window(data, con))
    if limit is not None:
        rs = rs[:max(0, limit)]
    if as_json:
        print(json.dumps(rs))
    else:
        for r in rs:
            print("%s\t%s\t%s" % (r["id"], r["title"] or "", r["url"] or ""))
    return 0


RUN_BUDGET = 0.02  # booked at launch (a typical 60-row haiku run costs about this), checked against the daily cap; the real cost replaces it
RUN_CEILING = 0.15  # passed as --max-budget-usd, a hard stop for a runaway run; claude checks it between turns, so the last turn may go a little over
MAX_AGE = 30 * 60  # past this a live pid is trusted only when its command line is still our describer run
HARD_AGE = 2 * 3600  # a run of ours still alive past this is stopped (it is stuck) and treated as ended
MAX_UNREPORTED = 2  # runs a day that may end without a cost report; then no more launches that day
RUN_FILE, OUT_FILE = "describer.json", "describer.out"
RUN_MARK = "/artifact-explorer:refresh describe-only"
# The background run's own `ae` calls, named outright. The skills write `sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" ...` with
# the path quoted, and in dontAsk `Bash(sh */bin/ae *)` matches only the unquoted form: allow both (0.2.3).
AE_TOOLS = ('Bash(sh "*/bin/ae" *)', "Bash(sh */bin/ae *)")
AE_TOOL = AE_TOOLS[1]


def _skill_tools():
    """The refresh skill's allowed-tools: the background run gets exactly these and nothing else."""
    with open(os.path.join(common.ROOT, "skills", "refresh", "SKILL.md"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("allowed-tools:"):
                return line.split(":", 1)[1].strip()
    raise RuntimeError("refresh skill has no allowed-tools")


def allowed_tools():
    """--allowedTools for the background run: the skill's tools plus AE_TOOL, one comma-separated value as the skill writes it."""
    tools = [t.strip() for t in re.split(r",(?![^()]*\))", _skill_tools()) if t.strip()]
    for t in AE_TOOLS:
        if t not in tools:
            tools.append(t)
    return ", ".join(tools)


def _result(data):
    """(cost, result text, refused tools) from the run's JSON output, or None when it has none."""
    try:
        with open(os.path.join(data, OUT_FILE), encoding="utf-8") as f:
            res = json.load(f)
        cost = float(res["total_cost_usd"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    denied = sorted({str(d.get("tool_name")) for d in res.get("permission_denials") or [] if isinstance(d, dict)})
    return cost, " ".join(str(res.get("result", "")).split())[:200], denied


def _ours(pid):
    """True when pid's command line is a describer run (so a live pid past MAX_AGE is not a reused one)."""
    return RUN_MARK in (common.pid_cmdline(pid) or "")


def _running(data, con):
    """True while the last launched describer still runs. When it has ended: log its result, correct the
    worst-case booking to the real cost, drop the record. A run that ends without a cost report (killed,
    stuck, crashed) releases its booking instead, so runs that never report cannot eat the daily cap; at
    most MAX_UNREPORTED of those a day, then the describer waits for the next day."""
    path = os.path.join(data, RUN_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        pid, t = int(rec["pid"]), float(rec["t"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if os.name != "nt":
        try:  # our own child that has ended is a zombie until reaped, and a zombie looks alive to kill(pid, 0)
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass
    booked = float(rec.get("booked", RUN_BUDGET))
    age = time.time() - t
    if common._pid_alive(pid):
        if age < MAX_AGE:
            common.log(data, "describer still running (pid %d), not launching another" % pid)
            return True
        if _ours(pid):
            if age < HARD_AGE:
                common.log(data, "describer pid %d has run %d min; still ours, waiting" % (pid, age // 60))
                return True
            common.stop_pid(pid)
            common.log(data, "describer pid %d ran over %d min; stopped it" % (pid, HARD_AGE // 60))
        else:
            common.log(data, "describer pid %d is older than %d min and is no longer our run; not waiting on it"
                       % (pid, MAX_AGE // 60))
    res = _result(data)
    if res:
        cost, text, denied = res
        db.add_spend(con, cost - booked, day=rec.get("day"), runs=0)
        line = "finished: %s ($%.2f)%s" % (text, cost, "; refused: " + ", ".join(denied) if denied else "")
    else:
        day = rec.get("day") or db.today()
        n = int(db.state_get(con, "unreported_" + day, 0)) + 1
        db.state_set(con, "unreported_" + day, n)
        db.add_spend(con, -booked, day=day, runs=0)
        line = ("ended without a cost report; released the $%.2f booked (%d of %d such runs allowed today)"
                % (booked, n, MAX_UNREPORTED))
    common.log(data, "describer " + line)
    db.state_set(con, "describer_result", {"t": time.time(), "pid": pid, "line": line})
    con.commit()
    try:
        os.remove(path)
    except OSError:
        pass
    return False


def launch(data, test=False):
    """One launch decision at a time, also when `ae launch-describer` runs outside a watcher pass.
    test=True (setup's check): launch now for one row, whatever the interval, and print what happened."""
    with common.Lock(os.path.join(data, "describer.lock"), 120) as ok:
        if not ok:
            if test:
                print("describer test: another launch decision is in progress; try again in a minute")
            return 0
        return _launch(data, test)


def _launch(data, test=False):
    """Start one background describer run when it is due and none is running. Prints nothing.
    The run is `claude -p`: it exits when done, has stdin closed, may only use the refresh skill's tools
    (dontAsk: anything else is refused, never asked) and is capped at RUN_BUDGET."""
    say = print if test else (lambda *a: None)
    opts = common.options()
    con = db.connect(data)
    if _running(data, con):
        say("describer test: a describer run is already going (see `ae status`); not starting another")
        return 0
    rows = pending_rows(con, owned_only=True, win=data_window(data, con))
    n_recat = recat_count(con, owned_only=True)
    if not rows and not n_recat:
        say("describer test: nothing of yours is waiting for a description, so there is nothing to test on")
        return 0
    now = time.time()
    claude = shutil.which("claude")
    if not claude:
        say("describer test: no `claude` command on PATH; the background describer cannot start")
        return 0
    if not test and now - db.state_get(con, "describer_last", 0) < opts["watch_interval"] * 60:
        return 0
    if not common.allow_rule_present():
        # without the setup allow rule every `ae` call in the unattended run would wait for approval;
        # the in-session refresh (SessionStart reminder) describes these rows instead
        say("describer test: the permission rule is not in settings.json, so the describer stays off")
        return 0
    if int(db.state_get(con, "unreported_" + db.today(), 0)) >= MAX_UNREPORTED:
        if db.state_get(con, "unreported_logged") != db.today():
            common.log(data, "describer not launched: %d runs ended today without a cost report" % MAX_UNREPORTED)
            db.state_set(con, "unreported_logged", db.today())
            con.commit()
        say("describer test: %d runs ended today without a cost report; it waits for tomorrow" % MAX_UNREPORTED)
        return 0
    if db.spend_today(con) + RUN_BUDGET > opts["describe_daily_cap"] + 1e-9:
        if db.state_get(con, "cap_logged") != db.today():
            common.log(data, "describer not launched: $%.2f spent today + $%.2f for one run is over the $%.2f cap"
                       % (db.spend_today(con), RUN_BUDGET, opts["describe_daily_cap"]))
            db.state_set(con, "cap_logged", db.today())
            con.commit()
        say("describer test: $%.2f spent today + $%.2f for one run is over the $%.2f cap"
            % (db.spend_today(con), RUN_BUDGET, opts["describe_daily_cap"]))
        return 0
    argv = [claude, "-p", "--model", opts["describe_model"], "--output-format", "json",
            "--permission-mode", "dontAsk", "--allowedTools", allowed_tools(),
            "--max-budget-usd", "%.2f" % RUN_CEILING]
    if os.path.basename(os.path.normpath(data)).endswith("-inline"):
        # loaded with --plugin-dir (development): the new session must load it the same way
        argv += ["--plugin-dir", common.ROOT]
    argv.append(RUN_MARK + (" 1" if test else ""))
    try:
        os.remove(os.path.join(data, OUT_FILE))  # an older run's report must never be read as this run's
    except OSError:
        pass
    pid = common.detach(argv, cwd=data, out=os.path.join(data, OUT_FILE))
    if pid:
        day = db.today()
        db.state_set(con, "describer_last", now)
        db.add_spend(con, RUN_BUDGET, day=day)  # booked first: a failed record write never hides the spend
        con.commit()
        rec, tmp = os.path.join(data, RUN_FILE), os.path.join(data, RUN_FILE + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"pid": pid, "t": now, "day": day, "booked": RUN_BUDGET}, f)
            os.replace(tmp, rec)  # never half-written: a torn record would read as "no run"
        except OSError:
            common.log(data, "describer launched (pid %d) but its record could not be written" % pid)
            return 0
        common.log(data, "describer launched (pid %d) for %d pending rows, %d to categorize%s" % (pid, len(rows), n_recat, " (test: 1 row)" if test else ""))
        say("describer test: launched (pid %d) for 1 row, $%.2f booked; `ae status` shows its result in a few minutes"
            % (pid, RUN_BUDGET))
    else:
        common.log(data, "describer launch failed")
        say("describer test: launch failed (see watch.log)")
    return 0


def widen(data, days):
    """`ae window --widen N`: the window covers N more days from now on (the page's "Describe older")."""
    con = db.connect(data)
    if days:
        db.state_set(con, "window_extra_days", max(0, int(db.state_get(con, "window_extra_days", 0) or 0) + days))
        con.commit()
    w = data_window(data, con)
    con.close()
    print(window_label(w, total=True) if w["cutoff"] is not None else "window: off (every row is described)")
    return 0


def window_label(w, total=False):
    s = "window: %d days" % w["days"] + (" (+%d)" % w["extra"] if w["extra"] else "")
    return s + (" = %d days" % (w["days"] + w["extra"]) if total and w["extra"] else "")


def status(data, as_json=False):
    con = db.connect(data)
    win = data_window(data, con)
    cond, wargs = db.window_sql(win)
    one = lambda sql, a=(): con.execute(sql, a).fetchone()[0]  # noqa: E731
    inw = lambda sql: one(sql + " AND " + cond, wargs)  # noqa: E731
    outw = lambda sql: one(sql + " AND NOT " + cond, wargs)  # noqa: E731
    nodesc = "(description IS NULL OR description='')"
    out = {
        "total": one("SELECT COUNT(*) FROM artifacts"),
        "mine": one("SELECT COUNT(*) FROM artifacts WHERE owned=1"),
        "shared": one("SELECT COUNT(*) FROM artifacts WHERE owned=0"),
        "unknown": one("SELECT COUNT(*) FROM artifacts WHERE owned IS NULL"),
        "pending_descriptions": inw("SELECT COUNT(*) FROM artifacts WHERE " + PENDING),
        "window_days": win["days"] + win["extra"] if win["cutoff"] is not None else 0,
        "window_rows": inw("SELECT COUNT(*) FROM artifacts WHERE 1=1"),
        "window_described": inw("SELECT COUNT(*) FROM artifacts WHERE NOT " + nodesc + " AND coalesce(desc_status,'')<>'no-source'"),
        "older": outw("SELECT COUNT(*) FROM artifacts WHERE 1=1"),
        "older_pending": outw("SELECT COUNT(*) FROM artifacts WHERE " + nodesc + " AND coalesce(desc_status,'pending')='pending'"),
        "skipped_descriptions": one("SELECT COUNT(*) FROM artifacts WHERE desc_status='skipped'"),
        "no_source_descriptions": one("SELECT COUNT(*) FROM artifacts WHERE desc_status='no-source'"),
        "thumbs_ok": one("SELECT COUNT(*) FROM artifacts WHERE thumb_status='ok'"),
        # waiting for a headless capture (or failed it)
        "thumbs_missing": one("SELECT COUNT(*) FROM artifacts WHERE thumb_status IS NULL OR thumb_status IN ('pending','failed')"),
        # no local file to capture: only a Chrome screenshot (or an older catalog) can give these a thumbnail
        "thumbs_none": one("SELECT COUNT(*) FROM artifacts WHERE thumb_status='none'"),
        "thumbs_importable": importer.thumbs_available(con),
        "described": one("SELECT COUNT(*) FROM artifacts WHERE NOT " + nodesc + " AND coalesce(desc_source,'')<>'title'"),
        "categorized": one("SELECT COUNT(*) FROM artifacts WHERE NOT " + nodesc +
                           " AND coalesce(desc_source,'')<>'title' AND category IS NOT NULL "
                           "AND coalesce(cat_source,'')<>'none'"),
        "last_pass": db.state_get(con, "last_pass"),
        "spend_today": round(db.spend_today(con), 2),
        "spend_cap": common.options()["describe_daily_cap"],
        "describer_last_result": db.state_get(con, "describer_result")}
    if as_json:
        print(json.dumps(out))
        return 0
    lp = out["last_pass"]
    print("artifacts: %(total)d (mine %(mine)d, shared %(shared)d, unknown %(unknown)d)" % out)
    if win["cutoff"] is not None:
        print("%s: %d rows, %d described, %d waiting" % (window_label(win), out["window_rows"],
                                                        out["window_described"], out["pending_descriptions"]))
        if out["older"]:
            print("older: %(older_pending)d not described (run /artifact-explorer:refresh older)" % out)
    print("categorized: %(categorized)d of %(described)d described" % out)
    print("descriptions pending: %(pending_descriptions)d (no text, skipped: %(skipped_descriptions)d; "
          "no source: %(no_source_descriptions)d, title shown)" % out)
    print("thumbnails: %(thumbs_ok)d ok, %(thumbs_missing)d waiting or failed" % out)
    if out["thumbs_none"]:
        print("no thumbnail: %(thumbs_none)d (no local file: turn on chrome_screenshots to capture them)" % out)
    if out["thumbs_importable"]:
        print("older catalog: %(thumbs_importable)d thumbnails can be copied with `ae import --thumbs-only`" % out)
    print("last pass: %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(lp)) if lp else "never"))
    print("describer spend today: $%(spend_today).2f of $%(spend_cap).2f" % out)
    res = out["describer_last_result"]
    if isinstance(res, dict) and res.get("line"):
        print("last describer run: %s (%s)" % (res["line"], time.strftime("%Y-%m-%d %H:%M", time.localtime(res.get("t") or 0))))
    elif os.path.exists(os.path.join(data, RUN_FILE)):
        print("last describer run: still running")
    return 0


# ---- batches (0.2.0): one describer call over several excerpts, category + topics in the same reply ----

def batch_root(data):
    return os.path.join(data, "inbox", "batch")


def batch_start(data):
    """A new empty folder INBOX/batch/<n> (n = next free integer); prints its path."""
    root = batch_root(data)
    os.makedirs(root, exist_ok=True)
    used = [int(x) for x in os.listdir(root) if x.isdigit()]
    path = os.path.join(root, str(max(used, default=0) + 1))
    _clear_old(root)
    os.makedirs(path)
    print(path)
    return 0


def _clear_old(root):
    """Remove the older numbered batch folders (they are scratch; a new batch starts clean)."""
    for x in os.listdir(root):
        if x.isdigit() and os.path.isdir(os.path.join(root, x)):
            shutil.rmtree(os.path.join(root, x), ignore_errors=True)


def _json_list(v):
    try:
        c = json.loads(v) if v else []
    except (ValueError, TypeError):
        return []
    return [x for x in c if isinstance(x, str)] if isinstance(c, list) else []


def _one_line(s):
    return " ".join(str(s or "").split())


def write_manifest(data, folder, items):
    """FOLDER/manifest.txt for the describer. items = [(id, "file"|"text", value)]. Returns the item count."""
    cfg = common.load_config(data)
    cats = [c["name"] for c in cfg.get("categories", []) if c.get("name")]
    tops = [t["name"] for t in cfg.get("topics", []) if t.get("name")]
    lines = ["Categories (pick exactly one): " + ", ".join(cats),
             "Topics (pick 0-3 that fit; you may propose up to 3 new broad topics): " + (", ".join(tops) or "(none configured yet)")]
    for aid, how, val in items:
        lines += ["## ITEM " + aid, "%s: %s" % (how, _one_line(val) if how == "text" else val)]
    with open(os.path.join(folder, "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return len(items)


def _report(folder, n):
    print(os.path.join(folder, "manifest.txt"))
    print("items: %d" % n)
    return 0


def batch_manifest(data, folder):
    folder = os.path.abspath(folder)
    items = []
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if name.endswith(".txt") and name != "manifest.txt" and os.path.getsize(p) > 0:
            items.append((name[:-4], "file", p))
    return _report(folder, write_manifest(data, folder, items))


def recat_where(owned_only=False):
    """Described rows the describer has not yet given a category or topics (0.2.3). Whatever the window: they
    were described already. recat_tried is set once a reply came back for the row, so a row the describer
    cannot place is asked once, not forever."""
    return ("description IS NOT NULL AND description<>'' AND coalesce(desc_source,'')<>'title' "
            "AND coalesce(cat_source,'')<>'none' AND recat_tried IS NULL "
            "AND (cat_source IS NULL OR category IS NULL OR topics IS NULL OR topics IN ('', '[]'))"
            + (" AND owned=1" if owned_only else ""))


def recat_count(con, owned_only=False):
    return con.execute("SELECT count(*) FROM artifacts WHERE " + recat_where(owned_only)).fetchone()[0]


def batch_recat(data, limit=40, owned_only=False):
    """New folder + manifest of described rows that lack a category or topics (text items, nothing to read)."""
    con = db.connect(data)
    rs = con.execute("SELECT id, title, description FROM artifacts WHERE " + recat_where(owned_only) +
                     " ORDER BY owned DESC, modified DESC, id LIMIT ?", (max(0, limit),)).fetchall()
    con.close()
    if not rs:
        print("items: 0")
        return 0
    root = batch_root(data)
    os.makedirs(root, exist_ok=True)
    used = [int(x) for x in os.listdir(root) if x.isdigit()]
    folder = os.path.join(root, str(max(used, default=0) + 1))
    _clear_old(root)
    os.makedirs(folder)
    items = [(r["id"], "text", "%s \u2014 %s" % (_one_line(r["title"]) or r["id"], _one_line(r["description"]))) for r in rs]
    return _report(folder, write_manifest(data, folder, items))


def _text_items(folder):
    """Ids the manifest next to a reply listed as text: items (their category is a recat)."""
    out, cur = set(), None
    try:
        with open(os.path.join(folder, "manifest.txt"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("## ITEM "):
                    cur = line[8:].strip()
                elif cur and line.startswith("text:"):
                    out.add(cur)
                elif cur and line.startswith("file:"):
                    cur = None
    except OSError:
        pass
    return out


def _save_line(con, line, cats, tops, texts, done):
    """Store one reply line on `con`. Returns the number of new suggestions, or None when nothing was saved."""
    try:
        o = json.loads(line)
    except ValueError:
        return None
    aid = db.resolve(con, o.get("id")) if isinstance(o, dict) and isinstance(o.get("id"), str) else None
    if not aid or db.get(con, aid) is None:
        return None
    is_text = aid in texts
    fields = {}
    d = o.get("description")
    if not is_text and isinstance(d, str):
        d = " ".join(d.split())[:200]
        if d.lower().strip(". ") in ("", "unreadable"):
            set_no_source(None, aid, con)
        else:
            fields.update(description=d, desc_source="describer", desc_status="ok")
    cat = cats.get(str(o.get("category") or "").strip().lower())
    if cat:
        fields.update(category=cat, cat_source="recat" if is_text else "describer")
        done.add(aid)
    tl = o.get("topics")
    if isinstance(tl, list):
        keep = []
        for t in tl:
            c = tops.get(str(t).strip().lower()) if isinstance(t, (str, int)) else None
            if c and c not in keep:
                keep.append(c)
        if keep:  # none picked stays NULL, so the title keywords still decide
            fields["topics"] = json.dumps(keep[:3])
    sug = 0
    nts = o.get("new_topics")
    if not isinstance(nts, list):
        nts = [o.get("new_topic")]  # 0.2.0 replies carried one `new_topic`
    cur = _json_list(db.get(con, aid)["topic_suggest"])
    for nt in nts[:3]:
        nt = " ".join(str(nt or "").split())
        if nt and len(nt) <= 40 and nt.lower() not in tops and nt.lower() not in [x.lower() for x in cur]:
            cur.append(nt)
            fields["topic_suggest"] = json.dumps(cur)
            sug = 1
    if not fields:
        return None
    db.upsert_artifact(con, aid, **fields)
    return sug


def batch_save(data, file):
    """Parse the describer's reply (one JSON object per line; anything else is ignored) and store it."""
    cfg = common.load_config(data)
    cats = {c["name"].lower(): c["name"] for c in cfg.get("categories", []) if c.get("name")}
    tops = {t["name"].lower(): t["name"] for t in cfg.get("topics", []) if t.get("name")}
    texts = _text_items(os.path.dirname(os.path.abspath(file)))
    with open(file, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    con = db.connect(data)
    saved = skipped = sug = 0
    done = set()
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            r = _save_line(con, line, cats, tops, texts, done)
        except Exception as e:  # one bad line must not lose the others
            common.log(data, "batch save: skipped a line: %s" % e)
            r = None
        if r is None:
            skipped += 1
        else:
            saved += 1
            sug += r
    for aid in texts:  # asked once: never again (a reply with no pick for a row leaves it as it is)
        try:
            con.execute("UPDATE artifacts SET recat_tried=1 WHERE id=?", (aid,))
            if aid not in done:
                con.execute("UPDATE artifacts SET cat_source='none' WHERE id=? AND cat_source IS NULL", (aid,))
        except Exception:
            pass
    con.commit()
    con.close()
    print("saved %d, skipped %d, suggested %d" % (saved, skipped, sug))
    return 0


def topics_cmd(data, accept=None, reject=None):
    """List configured topics (with row counts) and the describer's suggestions; or accept / reject one suggestion."""
    cfg = common.load_config(data)
    names = [t["name"] for t in cfg.get("topics", []) if t.get("name")]
    con = db.connect(data)
    if accept is not None:
        name = " ".join(accept.split())
        if not name or len(name) > 40:
            print("bad topic name", file=sys.stderr)
            return 2
        if name.lower() in [n.lower() for n in names]:
            print("already a topic: " + name)
            return 0
        path = os.path.join(data, "config.toml")
        with open(path, "a", encoding="utf-8") as f:
            f.write(("\n" if os.path.exists(path) and os.path.getsize(path) else "") + "[[topics]]\nname = %s\n" % importer.toml_str(name))
        print("added topic: " + name)
        return 0
    if reject is not None:
        n = 0
        for r in con.execute("SELECT id, topic_suggest FROM artifacts WHERE topic_suggest IS NOT NULL").fetchall():
            cur = _json_list(r["topic_suggest"])
            new = [x for x in cur if x.lower() != reject.strip().lower()]
            if new != cur:
                con.execute("UPDATE artifacts SET topic_suggest=? WHERE id=?", (json.dumps(new) if new else None, r["id"]))
                n += 1
        con.commit()
        print("rejected %r on %d rows" % (reject, n))
        return 0
    count, sugg = {}, {}
    for r in con.execute("SELECT topics, topic_suggest FROM artifacts").fetchall():
        for t in _json_list(r["topics"]):
            count[t.lower()] = count.get(t.lower(), 0) + 1
        for t in _json_list(r["topic_suggest"]):
            sugg[t] = sugg.get(t, 0) + 1
    print("topics:")
    for n in names:
        print("  %s (%d)" % (n, count.get(n.lower(), 0)))
    if not names:
        print("  (none configured)")
    known = {n.lower() for n in names}
    print("suggested:")
    shown = [(t, c) for t, c in sorted(sugg.items(), key=lambda x: (-x[1], x[0])) if t.lower() not in known]
    for t, c in shown:
        print("  %s (%d)" % (t, c))
    if not shown:
        print("  (none)")
    return 0
