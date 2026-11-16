"""0.2.9: suggested topics used on enough artifacts are promoted to real topics.

The describer's suggestions sit in artifacts.topic_suggest. Before counting, near-duplicates are merged
(case, spacing, simple plural, and a word-prefix rule: 'change order backlog' folds into 'change orders' only when
the longer one has fewer uses). A merged suggestion used on >= min_uses artifacts is promoted: it is recorded in the
state table (key topics_promoted: {key: display name}) so it stays promoted, and `resolve` hands build.py the
names to add to the Topic filter plus an alias map (every raw spelling -> the topic it applies to).

Config (config.toml):  [topic_promote]  min_uses = 2  (0 turns promotion off);  demote = ["Name"];
[topic_promote.rename] "Old" = "New".  A configured [[topics]] entry always wins; it is never altered here."""
import json
import re

import db

STATE_KEY = "topics_promoted"
DEFAULT_MIN = 2


def norm(name):
    """Lowercase, one space between words, punctuation other than letters/digits dropped."""
    return " ".join(re.sub(r"[^\w\s]|_", " ", str(name).lower()).split())


def _sing(word):
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def key_of(name):
    """Merge key: normalized, last word singularized (change orders == change order)."""
    w = norm(name).split()
    if w:
        w[-1] = _sing(w[-1])
    return " ".join(w)


def _list(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return []
    return [x for x in v if isinstance(x, str) and x.strip()] if isinstance(v, list) else []


def groups(suggest_rows):
    """({key: canonical key after the prefix rule}, {key: {raw spelling: uses}}, {canonical key: n artifacts})
    for an iterable of topic_suggest column values."""
    per_row, raw = [], {}
    for v in suggest_rows:
        ks = set()
        for n in _list(v):
            k = key_of(n)
            if not k:
                continue
            ks.add(k)
            sp = " ".join(n.split())
            raw.setdefault(k, {})
            raw[k][sp] = raw[k].get(sp, 0) + 1
        per_row.append(ks)
    uses = {}
    for ks in per_row:
        for k in ks:
            uses[k] = uses.get(k, 0) + 1
    target = {k: k for k in uses}
    for k in uses:  # fold into the shortest word-prefix that has MORE uses (the longer one has fewer)
        w = k.split()
        best = None
        for i in range(1, len(w)):
            p = " ".join(w[:i])
            if p in uses and uses[p] > uses[k]:
                best = p if best is None else best  # shortest prefix first
        if best:
            target[k] = best
    for k in list(target):  # a target is itself never re-targeted past one hop of the fixpoint
        seen = 0
        while target[target[k]] != target[k] and seen < 10:
            target[k] = target[target[k]]
            seen += 1
    counts = {}
    for ks in per_row:
        for c in {target[k] for k in ks}:
            counts[c] = counts.get(c, 0) + 1
    return target, raw, counts


def _display(spellings):
    return sorted(spellings.items(), key=lambda x: (-x[1], len(x[0]), x[0]))[0][0]


def resolve(con, cfg, suggest_rows=None, save=True):
    """(auto, alias): auto = [topic names promoted, not configured]; alias = {lowercase raw spelling: topic name}
    covering configured topics too (so 'change order' applies to a configured 'Change Orders')."""
    opt = cfg.get("topic_promote") or {}
    try:
        min_uses = int(opt.get("min_uses", DEFAULT_MIN))
    except (TypeError, ValueError):
        min_uses = DEFAULT_MIN
    demote = {key_of(x) for x in (opt.get("demote") or []) if isinstance(x, str)}
    rename = {key_of(o): " ".join(str(n).split()) for o, n in (opt.get("rename") or {}).items() if str(n).strip()}
    configured = {key_of(t["name"]): str(t["name"]).strip() for t in cfg.get("topics", []) if str(t.get("name") or "").strip()}
    if suggest_rows is None:
        suggest_rows = [r[0] for r in con.execute("SELECT topic_suggest FROM artifacts WHERE topic_suggest IS NOT NULL")]
    target, raw, counts = groups(suggest_rows)
    old = db.state_get(con, STATE_KEY, {}) or {}
    promoted = {k: v for k, v in old.items() if isinstance(v, str) and k not in demote}
    if min_uses > 0:
        for k, n in counts.items():
            if n >= min_uses and k not in configured and k not in demote and k not in promoted:
                promoted[k] = _display(raw[k])
    if promoted != old and save:
        db.state_set(con, STATE_KEY, promoted)
        con.commit()
    names = {}  # key -> topic name
    for k, nm in promoted.items():
        if k in configured:
            continue
        names[k] = rename.get(k, nm)
    auto = sorted(set(names.values()), key=str.lower)
    alias = {}
    for k, spell in raw.items():
        t = target[k]
        dest = configured.get(t) or names.get(t) or configured.get(k) or names.get(k)
        if dest:
            for s in spell:
                alias[s.lower()] = dest
    for k, nm in promoted.items():  # a renamed topic still catches rows saved under the old name
        if k in names:
            alias[nm.lower()] = names[k]
    return auto, alias
