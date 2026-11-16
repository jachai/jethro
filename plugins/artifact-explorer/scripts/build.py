"""Build DATA/explorer.html from the db and config. See docs/design.md (Build)."""
import hashlib
import json
import os
import re
import struct
import time
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import categorize as cat_guess  # noqa: E402
import colorsys  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402

FALLBACK = "Uncategorized"
DEFAULT_ACCENT = "#0f6b5c"
# dataviz palette (validated light/dark); a category takes slot = its position in the config list
PALETTE = [("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70"), ("#eda100", "#c98500"),
           ("#e87ba4", "#d55181"), ("#008300", "#0ca30c"), ("#6250d6", "#9085e9"), ("#e34948", "#e66767")]
NEUTRAL = ("#898781", "#898781")
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
SHARE_LEVELS = ("view", "comment", "edit")
SQL = """
SELECT a.*,
 (SELECT group_concat(repo, char(10)) FROM (SELECT DISTINCT repo FROM events
    WHERE artifact_id=a.id AND repo IS NOT NULL AND repo<>'' ORDER BY repo)) AS repos,
 (SELECT MIN(ts) FROM events WHERE artifact_id=a.id AND kind='publish') AS first_pub,
 (SELECT MAX(ts) FROM events WHERE artifact_id=a.id AND kind='publish') AS last_pub
FROM artifacts a ORDER BY a.id"""


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


def _hex(h, s, l):
    return "#%02x%02x%02x" % tuple(round(255 * c) for c in colorsys.hls_to_rgb(h / 360.0, l, s))


# 12 topic hues. (light bg, light text, dark bg, dark text); every pair keeps text contrast above 4.5:1 (tested).
TOPIC_PALETTE = [(_hex(h, .70, .90), _hex(h, .75, .20), _hex(h, .38, .22), _hex(h, .80, .86)) for h in range(0, 360, 30)]


def topic_key(name):
    return " ".join(str(name or "").casefold().split())


def topic_slot(name):
    """Stable palette index for a topic: the same name (any case or spacing) always gets the same one."""
    return int(hashlib.sha256(topic_key(name).encode("utf-8")).hexdigest(), 16) % len(TOPIC_PALETTE)


def categorize(rules, title, desc, kind, stored=None, row=None):
    """Category by fallback order (a config override is applied by the caller, before this): the describer's
    stored pick when it is a configured name, then the first category whose kinds has the row's kind, then the
    first whose keywords match title + description, else FALLBACK."""
    if stored:
        for name, _, _ in rules:
            if name.lower() == str(stored).strip().lower():
                return name
    k = (kind or "").lower()
    if k:
        for name, _, kinds in rules:
            if k in kinds:
                return name
    if row is not None:  # title/url/description patterns (categorize.py), limited to the configured names
        g = cat_guess.derive_category(row, [n for n, _, _ in rules])
        if g:
            return g
    text = "%s %s" % (title or "", desc or "")
    for name, pats, _ in rules:
        if any(p.search(text) for p in pats):
            return name
    return FALLBACK


def _known(rules, name):
    return bool(name) and any(n.lower() == str(name).strip().lower() for n, _, _ in rules)


def _known_kind(rules, kind):
    return bool(kind) and any(str(kind).lower() in ks for _, _, ks in rules)


def compile_topics_cfg(cfg):
    return [t for t in cfg.get("topics", []) if str(t.get("name") or "").strip()]


def compile_topics(data, topics):
    rules = []
    for t in topics:
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        pats = []
        for k in t.get("keywords") or [re.escape(name)]:
            try:
                pats.append(re.compile(k, re.I))
            except re.error:
                common.log(data, "build: bad topic regex %r in %s" % (k, name))
        rules.append((name, pats))
    return rules


def _names(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return []
    return [str(x) for x in v if isinstance(x, str)] if isinstance(v, list) else []


def tag_topics(trules, title, stored, suggest):
    """(topics, suggested) for a row. topics = the describer's stored list (None = never tagged; cut to configured
    names plus any suggestion configured by now) plus configured topics whose keywords match the title.
    suggested = the suggested names that are not configured."""
    canon = {n.lower(): n for n, _ in trules}
    sug = _names(suggest)
    topics = []
    for n in (_names(stored) if stored is not None else []) + (sug if stored is not None else []):
        c = canon.get(n.strip().lower())
        if c and c not in topics:
            topics.append(c)
    for n, pats in trules:  # title keywords always add to the describer's list
        if n not in topics and any(p.search(title or "") for p in pats):
            topics.append(n)
    suggested = []
    for n in sug:
        if n.strip().lower() not in canon and n not in suggested:
            suggested.append(n)
    return topics, suggested


def category_colors(cats, extra=()):
    """[{name, color, dark}] for every category: config color/color_dark, else palette slot by position
    (9th+ and FALLBACK get the neutral)."""
    out = []
    for i, c in enumerate(cats):
        slot = PALETTE[i] if i < len(PALETTE) else NEUTRAL
        col, dark = c.get("color"), c.get("color_dark")
        col = col if isinstance(col, str) and HEX.match(col) else None
        dark = dark if isinstance(dark, str) and HEX.match(dark) else None
        out.append({"name": c["name"], "color": col or slot[0], "dark": dark or col or slot[1]})
    for n in list(extra) + [FALLBACK]:
        if n not in {o["name"] for o in out}:
            out.append({"name": n, "color": NEUTRAL[0], "dark": NEUTRAL[1]})
    return out


SHARING = {"private": "Private", "org": "Organization",
           "link": "Anyone with the link", "public": "Public"}


def sharing_label(v):
    return SHARING.get((v or "").strip().lower(), v or "")


def _stored(v):
    """The describer's topic list from its column: None when never tagged."""
    if v is None:
        return None
    return _names(v)


def collect(data, cfg):
    flt, over = cfg.get("filter", {}), cfg.get("overrides", {})
    rules = compile_rules(data, cfg.get("categories", []))
    trules = compile_topics(data, cfg.get("topics", []))
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
        others = r["owned"] == 0
        topics, suggested = tag_topics(trules, r["title"], _stored(r["topics"]), r["topic_suggest"])
        copy = r["local_copy"] if others and r["local_copy"] and os.path.exists(os.path.join(data, r["local_copy"])) else ""
        access = (r["access"] or "").lower()
        rows.append({
            "id": r["id"], "title": (r["title"] or "").strip() or "Untitled", "kind": r["kind"] or "",
            "url": r["url"] if (r["url"] or "").startswith("https://claude.ai/") else "",
            "category": o.get("category") or categorize(
                rules, r["title"], desc, r["kind"], r["category"],
                {"kind": r["kind"], "title": r["title"], "url": r["url"], "description": desc}),
            "guessed": not (o.get("category") or _known(rules, r["category"]) or _known_kind(rules, r["kind"])),
            "topics": topics, "suggested": suggested,
            "mine": not others,
            "access": access if access in SHARE_LEVELS else "", "other_org": bool(r["other_org"]),
            "revoked": bool(others and r["shared_gone"] is not None), "copy": copy.replace(os.sep, "/"),
            "sharing": sharing_label(r["sharing"]) if r["owned"] == 1 else "",
            "created": created, "modified": modified, "seen": r["first_seen"],
            # sort key for "Modified": shared rows have no modified time, so use the last access, then created
            "recent": modified or r["last_accessed"] or created or r["first_seen"],
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


def version():
    return common.own_version()


def accent_of(cfg):
    a = (cfg.get("page") or {}).get("accent")
    return a if isinstance(a, str) and HEX.match(a) else DEFAULT_ACCENT


def _rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


CARDS = ((3, 3), (17, 3), (3, 17), (17, 17))  # four rounded cards, 2x2, on a 32 unit grid; each 12 x 12, radius 3


def favicon_svg(accent):
    rects = "".join('<rect x="%d" y="%d" width="12" height="12" rx="3"/>' % c for c in CARDS)
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="%s">%s</svg>' % (accent, rects)


def favicon_uri(accent):
    return "data:image/svg+xml," + urllib.parse.quote(favicon_svg(accent), safe="/:=")


def _cover(x, y):
    """Coverage 0..1 of the point (x, y) on the 32 grid by the four cards (rounded corners)."""
    for cx, cy in CARDS:
        if cx <= x <= cx + 12 and cy <= y <= cy + 12:
            dx = max(cx + 3 - x, x - (cx + 9), 0)
            dy = max(cy + 3 - y, y - (cy + 9), 0)
            if dx * dx + dy * dy <= 9:
                return 1
    return 0


def _bmp(size, rgb):
    """One BMP-in-ICO image: 32 bit BGRA bottom-up (supersampled edges) plus the empty AND mask."""
    ss, k = 4, 32.0 / size
    px = []
    for row in range(size - 1, -1, -1):
        for col in range(size):
            n = sum(_cover((col + (i + .5) / ss) * k, (row + (j + .5) / ss) * k) for i in range(ss) for j in range(ss))
            px.append(bytes((rgb[2], rgb[1], rgb[0], round(255 * n / (ss * ss)))))
    mask = b"\0" * (((size + 31) // 32 * 4) * size)
    head = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    return head + b"".join(px) + mask


def favicon_ico(accent):
    """DATA/favicon.ico bytes: 16 and 32 pixel images of the four-card icon in the accent color. Pure Python."""
    rgb = _rgb(accent)
    imgs = [_bmp(16, rgb), _bmp(32, rgb)]
    out, off = [struct.pack("<HHH", 0, 1, len(imgs))], 6 + 16 * len(imgs)
    for size, img in zip((16, 32), imgs):
        out.append(struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(img), off))
        off += len(img)
    return b"".join(out + imgs)


def write_favicon(data, accent):
    path, blob = os.path.join(data, "favicon.ico"), favicon_ico(accent)
    try:
        with open(path, "rb") as f:
            if f.read() == blob:
                return
    except OSError:
        pass
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)
    except OSError as e:  # the page is still written without it
        common.log(data, "build: favicon not written: %s" % e)


def build(data, max_age=None, update_check=True):
    """Write DATA/explorer.html. Skipped when the rows and template are unchanged, unless the page is
    older than max_age seconds (the watcher passes PAGE_HEARTBEAT; 0 always writes). update_check=False
    never asks GitHub (doctor)."""
    con = db.connect(data)
    pairs = db.merged_ids(con)
    con.close()
    common.rekey_overrides(data, pairs)  # overrides keyed by a uuid follow the row it merged into
    cfg = common.load_config(data)
    rows, old_hash, window = collect(data, cfg)
    cats = cfg.get("categories", [])
    accent, ver = accent_of(cfg), version()
    extra = sorted({r["category"] for r in rows} - {c["name"] for c in cats} - {FALLBACK})
    page = {k: cfg.get("page", {}).get(k) for k in ("title", "columns")}
    names = {t for r in rows for t in r["topics"] + r["suggested"]} | {t["name"] for t in compile_topics_cfg(cfg)}
    page.update(topic_palette=TOPIC_PALETTE, topic_slots={n: topic_slot(n) for n in sorted(names)}, accent=accent, categories=category_colors(cats, extra), version=ver,
                topics=[t["name"] for t in compile_topics_cfg(cfg)])
    upd = None
    if update_check:
        import update
        upd = update.badge(data, ver, cfg)
    payload = {"config": page, "rows": rows, "window": window, "update": upd}
    with open(os.path.join(common.ROOT, "page", "template.html"), encoding="utf-8") as f:
        tpl = f.read().replace("__FAVICON_SVG__", favicon_uri(accent))
    write_favicon(data, accent)
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
