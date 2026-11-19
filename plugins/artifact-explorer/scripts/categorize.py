"""Category fallback for rows the describer has not categorized: derive_category(row). Pure; never touches the db.

Order: the row's kind, then URL patterns, then title patterns, then description keywords. The result is always one
of the allowed category names (default: the shipped list), or None when nothing matches."""
import re

DEFAULT_ALLOWED = ("Reports", "Plans", "Dashboards", "Decks", "Docs", "Personal")

KINDS = {"deck": "Decks", "slides": "Decks", "slide": "Decks", "presentation": "Decks", "dashboard": "Dashboards",
         "docs": "Docs", "doc": "Docs", "document": "Docs", "report": "Reports", "plan": "Plans"}

URL_PATTERNS = [(r"docs\.google\.com/presentation|/slides?\b|/deck\b", "Decks"),
                (r"docs\.google\.com/(document|spreadsheets)|/docs?/|/wiki/", "Docs"),
                (r"/dashboard", "Dashboards")]

# Title patterns, strongest first. Each is (regex, category); first hit wins.
TITLE_PATTERNS = [(r"\b(additions?|pavilion|roof|glasshouse|massing|detour|keens|dinner|window|sintra)\b", "Personal"),
                  (r"\b(deck|slides?|presentation|pitch)\b", "Decks"),
                  (r"\b(dashboard|burn-?down|scorecard|tracker|watchlist|pulse|metrics|status board|leaderboard)\b",
                   "Dashboards"),
                  (r"\b(trip|travel|itinerary|flights?|layover|hotel|dinner|recipe|vacation|family|game|arcade|sprites?|"
                   r"stickers?|sound check|marketplace|shortlist|budget)\b", "Personal"),
                  (r"\b(plan|roadmap|proposal|strategy|milestones?|checklist|worklist|todo|design|options|"
                   r"approval|cutover|migration|decisions?|questions?)\b", "Plans"),
                  (r"\b(report|audit|review|post-?mortem|retrospective|summary|analysis|findings|casebook|"
                   r"dossier|research|compromise|breach|recap|highlights|verification|proof|coverage|gaps|"
                   r"evidence|what changed|changes|shipped|before and after|before & after|friction)\b", "Reports"),
                  (r"\b(guide|manual|docs?|how-?to|reference|readme|notes|runbook|explainer|walkthrough|tour|"
                   r"rules|workflow|handover|hand-?offs?|diagram|graph|explorer|model|landing|test|testing|qa|"
                   r"tests?|suite|answers|standup|ledger|flow|sheet|labels?|exemplar|mocking|typing|"
                   r"clones?|ladders|waterfall|band|tiers|prune|refactor|stabilization|stabilisation|"
                   r"release|gate|options|have vs)\b", "Docs")]

# Description/title keywords per category, the last resort.
KEYWORDS = [("Decks", r"\b(deck|slides?|presentation)\b"),
            ("Dashboards", r"\b(dashboard|burn-?down|tracker|metrics|live count)\b"),
            ("Plans", r"\b(plan|roadmap|proposal|strategy|decisions?|questions?|design)\b"),
            ("Reports", r"\b(report|audit|review|summary|analysis|findings|research|retrospective|verified|verification)\b"),
            ("Personal", r"\b(personal|travel|trip|family|home|game|budget)\b"),
            ("Docs", r"\b(guide|manual|docs?|reference|notes|walkthrough|explorer|page|table|comparison|test)\b")]

_T = [(re.compile(p, re.I), c) for p, c in TITLE_PATTERNS]
_U = [(re.compile(p, re.I), c) for p, c in URL_PATTERNS]
_K = [(c, re.compile(p, re.I)) for c, p in KEYWORDS]


def _get(row, key):
    try:
        v = row[key]
    except (KeyError, IndexError, TypeError):
        v = getattr(row, key, None)
    return v if isinstance(v, str) else ("" if v is None else str(v))


def derive_category(row, allowed=None):
    """Category name for a row (dict or sqlite3.Row with kind, title, url, description), or None."""
    names = {a.lower(): a for a in (allowed or DEFAULT_ALLOWED)}

    def pick(c):
        return names.get(c.lower()) if c else None

    kind = _get(row, "kind").strip().lower()
    if kind and pick(KINDS.get(kind)):
        return pick(KINDS[kind])
    if kind and kind in names:
        return names[kind]
    url = _get(row, "url")
    for rx, c in _U:
        if rx.search(url) and pick(c):
            return pick(c)
    title = _get(row, "title")
    for rx, c in _T:
        if rx.search(title) and pick(c):
            return pick(c)
    text = "%s %s" % (title, _get(row, "description"))
    for c, rx in _K:
        if rx.search(text) and pick(c):
            return pick(c)
    # nothing says what it is: a published page with a title is most likely a document
    if title.strip() and url.startswith("https://claude.ai/") and pick("Docs"):
        return pick("Docs")
    return None
