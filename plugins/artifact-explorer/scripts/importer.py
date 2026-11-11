"""Import an old explorer folder (read only) into the db, thumbs/ and config.toml."""
import base64
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import db  # noqa: E402


def load(src, name, default):
    try:
        with open(os.path.join(src, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def url_for(aid):
    return "https://claude.ai/%sartifact/%s" % ("code/" if "-" in aid else "", aid)


def old_category_order(src):
    try:
        with open(os.path.join(src, "build.py"), encoding="utf-8") as f:
            m = re.search(r"^CATEGORIES\s*=\s*\[(.*?)\]", f.read(), re.M | re.S)
        return re.findall(r"'([^']*)'|\"([^\"]*)\"", m.group(1)) if m else []
    except OSError:
        return []


def toml_str(s):
    return json.dumps(s, ensure_ascii=False)


def write_config(data, cats, order, overrides):
    """Append [[categories]] and [overrides] that are not in config.toml yet; user lines stay untouched."""
    path = os.path.join(data, "config.toml")
    have = common.load_toml(path) if os.path.exists(path) else {}
    known = {c.get("name") for c in have.get("categories", [])}
    names = [n for n in order if n in cats] + sorted(cats - set(order))
    out = ["[[categories]]\nname = %s\n" % toml_str(n) for n in names if n not in known and n != "Uncategorised"]
    for aid, o in sorted(overrides.items()):
        if aid not in have.get("overrides", {}):
            out.append("[overrides.%s]\n%s\n" % (toml_str(aid), "\n".join("%s = %s" % (k, toml_str(v)) for k, v in o.items())))
    if out:
        with open(path, "a", encoding="utf-8") as f:
            f.write(("\n" if os.path.exists(path) and os.path.getsize(path) else "") + "\n".join(out))
    return sum(1 for o in out if o.startswith("[overrides"))


def import_thumb(data, src, aid, previews):
    """Copy shots/<id>.jpg, else decode the data-URI preview, into DATA/thumbs. Returns relative path or None."""
    for rel in ("thumbs/%s.webp" % aid, "thumbs/%s.jpg" % aid):
        if os.path.exists(os.path.join(data, rel)):
            return rel
    shot = os.path.join(src, "shots", aid + ".jpg")
    os.makedirs(os.path.join(data, "thumbs"), exist_ok=True)
    if os.path.exists(shot):
        rel = "thumbs/%s.jpg" % aid
        shutil.copyfile(shot, os.path.join(data, rel))
        return rel
    uri = previews.get(aid)
    if uri and "," in uri:
        rel = "thumbs/%s.webp" % aid
        with open(os.path.join(data, rel), "wb") as f:
            f.write(base64.b64decode(uri.split(",", 1)[1]))
        return rel
    return None


def default_src():
    """The 0.0.x explorer folder (AE_OLD_CATALOG overrides it, for tests)."""
    return os.environ.get("AE_OLD_CATALOG") or os.path.join(os.path.expanduser("~"), ".claude", "artifact-explorer")


def _old_thumbs(con, src):
    """(row id, old id) for rows with no thumbnail whose old folder has a shot or preview for them."""
    src = os.path.expanduser(src)
    shots = os.path.join(src, "shots")
    have = {f[:-4] for f in os.listdir(shots) if f.endswith(".jpg")} if os.path.isdir(shots) else set()
    have |= set(load(src, "previews.json", {}))
    out = []
    for m in load(src, "meta.json", []):
        mid = m.get("id") if isinstance(m, dict) else None
        if not mid or mid not in have:
            continue
        r = con.execute("SELECT id FROM artifacts WHERE (id=? OR (uuid=? AND uuid<>'')) AND "
                        "(thumb IS NULL OR thumb='' OR thumb_status IS NOT 'ok') LIMIT 1",
                        (mid, m.get("uuid") or "")).fetchone()
        if r:
            out.append((r[0], mid))
    return out


def thumbs_available(con, src=None):
    return len(_old_thumbs(con, src or default_src()))


def run_thumbs(data, src):
    """Copy the old folder's Chrome shots (or previews) into rows that have no thumbnail. Changes nothing else."""
    src = os.path.expanduser(src)
    previews = load(src, "previews.json", {})
    con = db.connect(data)
    n = 0
    try:
        for aid, mid in _old_thumbs(con, src):
            rel = import_thumb(data, src, mid, previews)
            if rel:
                db.upsert_artifact(con, aid, thumb=rel, thumb_source="import", thumb_status="ok")
                n += 1
        con.commit()
    finally:
        con.close()
    print("imported %d thumbnails" % n)
    if n:
        import build
        build.build(data)
    return 0


def run(data, src):
    src = os.path.expanduser(src)
    meta = [m for m in load(src, "meta.json", []) if not m.get("gone") and m.get("id")]
    cats, hand, previews = load(src, "cats.json", {}), load(src, "hand.json", {}), load(src, "previews.json", {})
    uuid_to_id = {m["uuid"]: m["id"] for m in meta if m.get("uuid")}
    local = load(src, "local.json", {})
    catalog = {}
    for c in load(src, "catalog.json", []):
        k = db.id_from_url(c.get("u"))
        catalog[uuid_to_id.get(k, k)] = c
    con = db.connect(data)
    n_rows = n_events = n_thumbs = 0
    for m in meta:
        mid = m["id"]  # the old folder's key; aid is the row it lands in
        aid, c = db.resolve(con, mid, m.get("uuid") or None), catalog.get(mid, {})
        by = c.get("by") or m.get("by")
        owned = 0 if by == "Someone else" else (1 if by else None)
        text = m.get("desc") or m.get("cand")
        thumb = import_thumb(data, src, mid, previews)
        db.upsert_artifact(
            con, aid, uuid=m.get("uuid") or None, url=url_for(aid), title=m.get("title"),
            kind=m.get("type") or c.get("k"), owned=owned, sharing=(c.get("sh") or m.get("share") or {}).get("a"),
            size=m.get("size") or c.get("s"), created=m.get("created") or c.get("c"), modified=c.get("m") or m.get("ver"),
            description=text or None, desc_source="import" if text else None, desc_status="ok" if text else "pending",
            thumb=thumb, thumb_source="import" if thumb else None, thumb_status="ok" if thumb else "none")
        n_rows += 1
        n_thumbs += bool(thumb)
        ts = {int(t) for t in m.get("visits", [])}
        ts |= {int(t) for t in local.get("visits", {}).get(m.get("uuid"), [])}
        for t in sorted(ts):
            n_events += db.add_event(con, aid, t, "visit", "import")
        for t in local.get("agent", {}).get(mid, []):
            n_events += db.add_event(con, aid, t, "agent_read", "import")
        pub = local.get("published", {}).get(mid)
        if pub:
            n_events += db.add_event(con, aid, pub["ts"], "publish", "import", detail={"n": pub.get("n"), "label": pub.get("label")})
        # repos only live on events: one agent_read per repo, placed at the earliest known access so
        # last_accessed and modified stay right (+1 ms steps keep the rows distinct)
        base = min(list(ts) + local.get("agent", {}).get(mid, []) + [m.get("created") or 0])
        for i, (repo, count) in enumerate(sorted((m.get("repos") or {}).items())):
            n_events += db.add_event(con, aid, base + (i + 1) / 1000.0, "agent_read", "import", repo=repo, detail={"count": count})
    con.commit()
    ids = {m["id"] for m in meta}
    overrides = {}
    for aid in sorted(ids & (set(cats) | set(hand))):
        o = {}
        if cats.get(aid):
            o["category"] = cats[aid]
        if hand.get(aid):
            o["description"] = hand[aid]
        overrides[aid] = o
    n_over = write_config(data, set(cats.values()), [a or b for a, b in old_category_order(src)], overrides)
    print("imported %d rows, %d events, %d thumbs, %d overrides" % (n_rows, n_events, n_thumbs, n_over))
    return 0
