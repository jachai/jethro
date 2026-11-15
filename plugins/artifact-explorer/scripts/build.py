"""Build DATA/explorer.html from the db and config. See docs/design.md (Build)."""
import hashlib
import json
import os
import re
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import db  # noqa: E402

FALLBACK = "Uncategorised"
SQL = """
SELECT a.*,
 (SELECT group_concat(repo, char(10)) FROM (SELECT DISTINCT repo FROM events
    WHERE artifact_id=a.id AND repo IS NOT NULL AND repo<>'' ORDER BY repo)) AS repos,
 (SELECT MIN(ts) FROM events WHERE artifact_id=a.id AND kind='publish') AS first_pub,
 (SELECT MAX(ts) FROM events WHERE artifact_id=a.id AND kind='publish') AS last_pub
FROM artifacts a ORDER BY a.id"""


def created_by(r):
    if r["owned"] == 1:
        return "me"
    if r["owned"] == 0:
        return r["creator"] or "someone else"
    return "unknown"


def compile_rules(data, cats):
    rules = []
    for c in cats:
        pats = []
        for k in c.get("keywords", []):
            try:
                pats.append(re.compile(k, re.I))
            except re.error:
                common.log(data, "build: bad category regex %r in %s" % (k, c.get("name")))
        rules.append((c["name"], pats, [k.lower() for k in c.get("kinds", [])]))
    return rules


def categorise(rules, title, desc, kind):
    text = "%s %s" % (title or "", desc or "")
    for name, pats, kinds in rules:
        if (kind or "").lower() in kinds or any(p.search(text) for p in pats):
            return name
    return FALLBACK


SHARING = {"private": "Private", "withme": "Shared with me", "org": "Organization",
           "link": "Anyone with the link", "public": "Public"}


def sharing_label(v):
    return SHARING.get((v or "").strip().lower(), v or "")


def collect(data, cfg):
    flt, over = cfg.get("filter", {}), cfg.get("overrides", {})
    rules = compile_rules(data, cfg.get("categories", []))
    inc, exc = set(flt.get("include_repos", [])), set(flt.get("exclude_repos", []))
    exc_ids = set(flt.get("exclude_ids", []))
    con = db.connect(data)
    win = db.window(con, cfg)
    rows = []
    for r in con.execute(SQL):
        o = over.get(r["id"], {})
        repos = r["repos"].split("\n") if r["repos"] else []
        if (o.get("hidden") or r["id"] in exc_ids or (inc and not inc & set(repos)) or exc & set(repos)
                or (r["owned"] == 0 and not flt.get("include_shared", True))):
            continue
        desc = o.get("description") or r["description"] or ""
        created, modified = r["first_pub"] or r["created"], r["last_pub"] or r["modified"]
        thumb = r["thumb"] if r["thumb"] and os.path.exists(os.path.join(data, r["thumb"])) else ""
        rows.append({
            "id": r["id"], "title": (r["title"] or "").strip() or "Untitled", "kind": r["kind"] or "", "url": r["url"] or "",
            "category": o.get("category") or categorise(rules, r["title"], desc, r["kind"]),
            "created_by": created_by(r), "sharing": sharing_label(r["sharing"]) or ("Shared with me" if r["owned"] == 0 else ""),
            "created": created, "modified": modified,
            # sort key for "Modified": shared rows have no modified time, so use the last access, then created
            "recent": modified or r["last_accessed"] or created,
            "accessed": r["last_accessed"], "accessed_by": r["last_access_by"] or "",
            "size": r["size"], "description": desc, "pending": not desc and r["desc_status"] == "pending",
            "skipped": (r["desc_note"] or "no text") if not desc and r["desc_status"] == "skipped" else "",
            "repos": repos, "thumb": thumb.replace(os.sep, "/"), "older": not db.in_window(r, win)})
    state = db.state_get(con, "build_hash")
    con.close()
    # the cutoff is a day boundary in the payload, so an unchanged catalog still hashes the same within a day
    cut = win["cutoff"]
    return rows, state, {"days": win["days"] + win["extra"] if cut is not None else 0,
                         "cutoff": int(cut // 86400 * 86400) if cut is not None else None}


def status(data, now):
    """What the page shows in its status section, as of this build."""
    import watch
    con = db.connect(data)
    last_pass = db.state_get(con, "last_pass")
    con.close()
    interval = common.options()["watch_interval"]
    return {"built": now, "last_pass": last_pass, "watcher": watch.watcher_state(data), "interval": interval,
            "stale_after": common.PAGE_HEARTBEAT + 2 * interval * 60}


def build(data, max_age=None):
    """Write DATA/explorer.html. Skipped when the rows and template are unchanged, unless the page is
    older than max_age seconds (the watcher passes PAGE_HEARTBEAT; 0 always writes)."""
    con = db.connect(data)
    pairs = db.merged_ids(con)
    con.close()
    common.rekey_overrides(data, pairs)  # overrides keyed by a uuid follow the row it merged into
    cfg = common.load_config(data)
    rows, old_hash, window = collect(data, cfg)
    names = [c["name"] for c in cfg.get("categories", [])] + [FALLBACK]
    names += sorted({r["category"] for r in rows} - set(names))
    page = {k: cfg.get("page", {}).get(k) for k in ("title", "accent", "columns")}
    payload = {"config": dict(page, categories=names), "rows": rows, "window": window}
    with open(os.path.join(common.ROOT, "page", "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    digest = hashlib.sha256((json.dumps(payload, sort_keys=True) + tpl).encode()).hexdigest()
    out = os.path.join(data, "explorer.html")
    if digest == old_hash and os.path.exists(out) and (max_age is None or time.time() - os.path.getmtime(out) < max_age):
        return out
    payload["generated"] = time.time()
    payload["status"] = status(data, payload["generated"])
    blob = json.dumps(payload, sort_keys=True)
    for ch, esc in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        blob = blob.replace(ch, esc)  # inside a <script>, no raw < can open a comment or tag
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        # the template keeps `null` after the marker so it parses on its own
        f.write(tpl.replace("/*__DATA__*/null", blob, 1))
    os.replace(tmp, out)
    con = db.connect(data)
    db.state_set(con, "build_hash", digest)
    con.commit()
    con.close()
    return out
