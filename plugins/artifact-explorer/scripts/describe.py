"""Description queue: ingest Artifact-list rows, set descriptions, launch the background describer, status."""
import json
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


def ingest_list(data, file):
    with open(file, encoding="utf-8") as f:
        rows = json.load(f)
    if isinstance(rows, dict):
        rows = first(rows, "artifacts", "items", "rows") or []
    con = db.connect(data)
    n = 0
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
            desc_status=status)
        n += 1
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


def excerpt(path, chars=3000):
    """Visible text of a saved artifact file (HTML or plain text), whitespace-collapsed and capped."""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read(2_000_000)
    if "<" in raw and ">" in raw:
        p = _Text()
        p.feed(raw)
        raw = " ".join(p.out)
    return " ".join(raw.split())[:chars]


MIN_TEXT = 50  # fewer visible characters than this is a viewer shell, not something to describe
TYPED = {"docs", "slides", "data", "dashboard"}  # Artifact types whose saved index.html is only the viewer shell


def excerpt_for(data, path, out, aid=None, kind=None, chars=3000):
    """Write the excerpt of a saved artifact to `out` for the describer agent. A typed artifact or a page
    with almost no text marks the row 'skipped' (with the reason) so no run picks it again.
    Returns (text, skipped)."""
    text = excerpt(path, chars)
    typed = (kind or "").strip().lower() in TYPED
    skipped = typed or len(text) < MIN_TEXT
    with open(out, "w", encoding="utf-8") as f:
        f.write("" if skipped else text)
    if aid:
        con = db.connect(data)
        if db.get(con, aid) is None:  # the id comes from the run; never invent a row
            con.close()
            return text, skipped
        if skipped:
            db.upsert_artifact(con, aid, kind=kind or None, desc_status="skipped",
                               desc_note="no text: typed artifact" if typed else "no text: under %d characters" % MIN_TEXT)
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


def set_sharing(data, aid, text):
    con = db.connect(data)
    db.upsert_artifact(con, aid, sharing=" ".join(text.split())[:80])
    con.commit()
    return 0


COLS = "id,url,title,owned,thumb_status,desc_status,modified,local_path"


def list_rows(con, owned=False, desc_status=None, thumb_status=None, limit=None, need_desc=False):
    """The one row query: `ae rows`, `ae pending` and the describer launch all come through here."""
    where, args = [], []
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
    typed_last = "CASE WHEN lower(coalesce(kind,'')) IN (%s) THEN 1 ELSE 0 END" % ",".join("'%s'" % t for t in sorted(TYPED))
    sql = "SELECT %s FROM artifacts%s ORDER BY owned DESC, %s, modified DESC, id" % (
        COLS, " WHERE " + " AND ".join(where) if where else "", typed_last)
    if limit is not None:
        sql += " LIMIT %d" % limit
    return [dict(r) for r in con.execute(sql, args)]


def rows(data, **kw):
    print(json.dumps(list_rows(db.connect(data), **kw)))
    return 0


def pending_rows(con, owned_only):
    return list_rows(con, owned=owned_only, desc_status="pending", need_desc=True)


def pending(data, owned_only=False, as_json=False):
    rs = pending_rows(db.connect(data), owned_only)
    if as_json:
        print(json.dumps(rs))
    else:
        for r in rs:
            print("%s\t%s\t%s" % (r["id"], r["title"] or "", r["url"] or ""))
    return 0


RUN_BUDGET = 0.25  # one background run's worst case: booked at launch, checked against the daily cap
RUN_LIMIT = 0.20  # passed as --max-budget-usd; claude checks it between turns, so the last turn may go a little over
MAX_AGE = 30 * 60  # a describer record older than this is not trusted, even if its pid is alive (pid reuse)
RUN_FILE, OUT_FILE = "describer.json", "describer.out"


def _skill_tools():
    """The refresh skill's allowed-tools: the background run gets exactly these and nothing else."""
    with open(os.path.join(common.ROOT, "skills", "refresh", "SKILL.md"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("allowed-tools:"):
                return line.split(":", 1)[1].strip()
    raise RuntimeError("refresh skill has no allowed-tools")


def _running(data, con):
    """True while the last launched describer still runs. When it has ended: log its result, correct the
    worst-case booking to the real cost (kept when the result can't be read), drop the record."""
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
    if common._pid_alive(pid):
        if time.time() - t < MAX_AGE:
            common.log(data, "describer still running (pid %d), not launching another" % pid)
            return True
        # past the max age the pid may belong to another process now; the run's worst case stays booked
        common.log(data, "describer pid %d is older than %d min; not waiting on it (kept the $%.2f booked)"
                   % (pid, MAX_AGE // 60, float(rec.get("booked", RUN_BUDGET))))
    else:
        try:
            with open(os.path.join(data, OUT_FILE), encoding="utf-8") as f:
                res = json.load(f)
            cost = float(res["total_cost_usd"])
            db.add_spend(con, cost - float(rec.get("booked", RUN_BUDGET)), day=rec.get("day"), runs=0)
            denied = sorted({str(d.get("tool_name")) for d in res.get("permission_denials") or [] if isinstance(d, dict)})
            common.log(data, "describer finished: %s ($%.2f)%s" % (
                " ".join(str(res.get("result", "")).split())[:200], cost, "; refused: " + ", ".join(denied) if denied else ""))
        except (OSError, ValueError, KeyError, TypeError):
            common.log(data, "describer ended without a readable result; kept the $%.2f worst case" % RUN_BUDGET)
    con.commit()
    try:
        os.remove(path)
    except OSError:
        pass
    return False


def launch(data):
    """One launch decision at a time, also when `ae launch-describer` runs outside a watcher pass."""
    with common.Lock(os.path.join(data, "describer.lock"), 120) as ok:
        return _launch(data) if ok else 0


def _launch(data):
    """Start one background describer run when it is due and none is running. Prints nothing.
    The run is `claude -p`: it exits when done, has stdin closed, may only use the refresh skill's tools
    (dontAsk: anything else is refused, never asked) and is capped at RUN_BUDGET."""
    opts = common.options()
    con = db.connect(data)
    if _running(data, con):
        return 0
    rows = pending_rows(con, owned_only=True)
    if not rows:
        return 0
    now = time.time()
    claude = shutil.which("claude")
    if now - db.state_get(con, "describer_last", 0) < opts["watch_interval"] * 60 or not claude:
        return 0
    if not common.allow_rule_present():
        # without the setup allow rule every `ae` call in the unattended run would wait for approval;
        # the in-session refresh (SessionStart reminder) describes these rows instead
        return 0
    if db.spend_today(con) + RUN_BUDGET > opts["describe_daily_cap"] + 1e-9:
        if db.state_get(con, "cap_logged") != db.today():
            common.log(data, "describer not launched: $%.2f spent today + $%.2f for one run is over the $%.2f cap"
                       % (db.spend_today(con), RUN_BUDGET, opts["describe_daily_cap"]))
            db.state_set(con, "cap_logged", db.today())
            con.commit()
        return 0
    argv = [claude, "-p", "--model", opts["describe_model"], "--output-format", "json",
            "--permission-mode", "dontAsk", "--allowedTools", _skill_tools(),
            "--max-budget-usd", "%.2f" % RUN_LIMIT]
    if os.path.basename(os.path.normpath(data)).endswith("-inline"):
        # loaded with --plugin-dir (development): the new session must load it the same way
        argv += ["--plugin-dir", common.ROOT]
    argv.append("/artifact-explorer:refresh describe-only")
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
        common.log(data, "describer launched (pid %d) for %d pending rows" % (pid, len(rows)))
    else:
        common.log(data, "describer launch failed")
    return 0


def status(data, as_json=False):
    con = db.connect(data)
    one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    out = {
        "total": one("SELECT COUNT(*) FROM artifacts"),
        "mine": one("SELECT COUNT(*) FROM artifacts WHERE owned=1"),
        "shared": one("SELECT COUNT(*) FROM artifacts WHERE owned=0"),
        "unknown": one("SELECT COUNT(*) FROM artifacts WHERE owned IS NULL"),
        "pending_descriptions": one("SELECT COUNT(*) FROM artifacts WHERE " + PENDING),
        "skipped_descriptions": one("SELECT COUNT(*) FROM artifacts WHERE desc_status='skipped'"),
        "thumbs_ok": one("SELECT COUNT(*) FROM artifacts WHERE thumb_status='ok'"),
        # waiting for a headless capture (or failed it)
        "thumbs_missing": one("SELECT COUNT(*) FROM artifacts WHERE thumb_status IS NULL OR thumb_status IN ('pending','failed')"),
        # no local file to capture: only a Chrome screenshot (or an older catalog) can give these a thumbnail
        "thumbs_none": one("SELECT COUNT(*) FROM artifacts WHERE thumb_status='none'"),
        "thumbs_importable": importer.thumbs_available(con),
        "last_pass": db.state_get(con, "last_pass"),
        "spend_today": round(db.spend_today(con), 2),
        "spend_cap": common.options()["describe_daily_cap"]}
    if as_json:
        print(json.dumps(out))
        return 0
    lp = out["last_pass"]
    print("artifacts: %(total)d (mine %(mine)d, shared %(shared)d, unknown %(unknown)d)" % out)
    print("descriptions pending: %(pending_descriptions)d (no text, skipped: %(skipped_descriptions)d)" % out)
    print("thumbnails: %(thumbs_ok)d ok, %(thumbs_missing)d waiting or failed" % out)
    if out["thumbs_none"]:
        print("no thumbnail: %(thumbs_none)d (no local file: turn on chrome_screenshots to capture them)" % out)
    if out["thumbs_importable"]:
        print("older catalog: %(thumbs_importable)d thumbnails can be copied with `ae import --thumbs-only`" % out)
    print("last pass: %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(lp)) if lp else "never"))
    print("describer spend today: $%(spend_today).2f of $%(spend_cap).2f" % out)
    return 0
