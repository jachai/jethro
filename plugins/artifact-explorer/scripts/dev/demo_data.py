#!/usr/bin/env python3
"""Write a fully invented demo catalog (explorer.db, config.toml, SVG thumbnails) for README screenshots.

    python3 scripts/dev/demo_data.py OUT_DIR   # writes the data and builds OUT_DIR/explorer.html

Everything is made up: generic hobby themes, fake people, fake ids. Nothing comes from a real catalog.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import db  # noqa: E402

DAY = 86400
# (title, kind, category, topics, description, days_ago, owned, creator, access)
ROWS = [
    ("Lisbon in five days", "Docs", "Plans", ["Travel"], "A day-by-day walking itinerary for Lisbon with cafe stops and a rainy-day fallback.", 2, 1, "", ""),
    ("Packing list: carry-on only", "Docs", "Docs", ["Travel"], "A checklist for a one-bag trip, sorted by weather and trip length.", 6, 1, "", ""),
    ("Trip budget tracker", "Dashboard", "Dashboards", ["Travel"], "Daily spend against budget for a two-week trip, with a currency converter.", 9, 1, "", ""),
    ("Train routes across Japan", "Slides", "Decks", ["Travel"], "A short deck comparing rail passes and the best scenic lines.", 21, 1, "", ""),
    ("Sourdough starter diary", "Docs", "Docs", ["Recipes"], "Feeding schedule and notes from fourteen days of a new starter.", 1, 1, "", ""),
    ("Weeknight dinners, autumn", "Docs", "Plans", ["Recipes"], "Ten easy dinners with a shared shopping list.", 4, 1, "", ""),
    ("Pantry inventory", "Dashboard", "Dashboards", ["Recipes"], "What is in the pantry, what is running low, and what expires first.", 11, 1, "", ""),
    ("Dumpling night menu", "Slides", "Decks", ["Recipes"], "A printable menu card for a dumpling dinner with six fillings.", 30, 1, "", ""),
    ("Book club: November pick", "Docs", "Docs", ["Book club"], "Discussion questions and a reading schedule for this month's novel.", 3, 1, "", ""),
    ("Reading list 2027", "Docs", "Plans", ["Book club"], "Twenty-four candidate books voted on by the club.", 8, 1, "", ""),
    ("Book club scoreboard", "Dashboard", "Dashboards", ["Book club"], "Who read what, ratings per book, and the all-time favorites.", 15, 1, "", ""),
    ("Meeting recap: October", "Docs", "Reports", ["Book club"], "Notes from the October meeting, including the argument about the ending.", 2, 0, "Priya Raman", "comment"),
    ("Tomato bed layout", "Docs", "Plans", ["Garden"], "A raised-bed plan with spacing, companion plants and a planting calendar.", 5, 1, "", ""),
    ("Garden watering log", "Dashboard", "Dashboards", ["Garden"], "Daily rainfall and watering minutes with a simple dry-spell warning.", 7, 1, "", ""),
    ("Seed order summary", "Docs", "Reports", ["Garden"], "What was ordered, what arrived, and what to reorder in spring.", 19, 1, "", ""),
    ("Compost guide for beginners", "Slides", "Decks", ["Garden"], "Six slides on what goes in, what stays out, and how long it takes.", 40, 0, "Tomas Eliade", "view"),
    ("Habit tracker app: roadmap", "Docs", "Plans", ["Side project"], "Three milestones for a small habit-tracking app, with the scope for each.", 2, 1, "", ""),
    ("Habit tracker: usage dashboard", "Dashboard", "Dashboards", ["Side project"], "Daily active testers, streak lengths and the most skipped habits.", 10, 1, "", ""),
    ("Launch checklist", "Docs", "Plans", ["Side project"], "Everything to finish before sharing the app with friends.", 13, 1, "", ""),
    ("Logo ideas", "Slides", "Decks", ["Side project"], "Eight logo directions with notes on what works at small sizes.", 24, 1, "", ""),
    ("Weekend hike planner", "Docs", "Plans", ["Travel", "Garden"], "Trail options near town ranked by length, shade and parking.", 12, 1, "", ""),
    ("Birthday party plan", "Docs", "Plans", [], "Guest list, menu and a timeline for a small backyard party.", 16, 1, "", ""),
    ("Monthly household budget", "Dashboard", "Dashboards", [], "Income against groceries, subscriptions and fun money for the year.", 18, 1, "", ""),
    ("Neighborhood swap shelf", "Docs", "Docs", [], "Ground rules and a sign-up sheet for the street's book and plant swap.", 5, 0, "Lena Okafor", "edit"),
]
# owned rows that are not private (index into ROWS), and invented repo names for some rows
SHARED = {0: "link", 3: "org", 8: "org", 16: "org", 18: "link", 21: "org"}
REPOS = {16: "habit-tracker", 17: "habit-tracker", 18: "habit-tracker", 19: "habit-tracker", 2: "trip-notes", 12: "garden-notes", 13: "garden-notes", 9: "club-lists"}
PALETTE = [("#2a9d8f", "#264653"), ("#e9c46a", "#f4a261"), ("#e76f51", "#b5838d"), ("#457b9d", "#1d3557"),
           ("#8ab17d", "#2d6a4f"), ("#b08968", "#7f5539"), ("#9d4edd", "#5a189a"), ("#f28482", "#f6bd60")]
TOPIC_COLORS = {"Travel": "#457b9d", "Recipes": "#e76f51", "Book club": "#9d4edd", "Garden": "#2d6a4f", "Side project": "#b08968"}


def aid(i):
    """A fake id: obviously not a real claude.ai id (starts DemoDemo, 22 chars)."""
    return "DemoDemo%014d" % (i + 1)


def thumb_svg(title, i):
    a, b = PALETTE[i % len(PALETTE)]
    words = [w for w in title.replace(":", "").split() if w[0].isalpha()]
    mark = "".join(w[0].upper() for w in words[:2])
    bars = "".join('<rect x="28" y="%d" width="%d" height="9" rx="4" fill="#fff" fill-opacity="0.55"/>' % (118 + 18 * k, 200 - 36 * k) for k in range(3))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200" width="320" height="200">'
            '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient></defs>'
            '<rect width="320" height="200" fill="url(#g)"/><circle cx="262" cy="52" r="26" fill="#fff" fill-opacity="0.25"/>'
            '<text x="28" y="86" font-family="Helvetica,Arial,sans-serif" font-size="44" font-weight="700" fill="#fff">%s</text>%s</svg>') % (a, b, mark, bars)


def main(out):
    os.makedirs(os.path.join(out, "thumbs"), exist_ok=True)
    for f in ("explorer.db", "explorer.db-wal", "explorer.db-shm"):
        if os.path.exists(os.path.join(out, f)):
            os.remove(os.path.join(out, f))
    con = db.connect(out)
    now = time.time()
    for i, (title, kind, cat, topics, desc, ago, owned, creator, access) in enumerate(ROWS):
        a = aid(i)
        rel = "thumbs/%s.svg" % a
        with open(os.path.join(out, rel), "w", encoding="utf-8") as f:
            f.write(thumb_svg(title, i))
        t = now - ago * DAY
        db.upsert_artifact(con, a, url="https://claude.ai/artifact/" + a, title=title, kind=kind, owned=owned,
                           creator=creator or None, sharing=SHARED.get(i, "private") if owned else None, size=int((9 + (i * 37) % 180) * 1024 + i * 211), created=t - DAY, modified=t,
                           last_accessed=t, description=desc, desc_source="describer", desc_status="ok",
                           thumb=rel, thumb_source="demo", thumb_status="ok", category=cat, cat_source="describer",
                           topics='["%s"]' % '","'.join(topics) if topics else "[]", access=access or None,
                           other_org=0)
        db.add_event(con, a, t, "publish", "demo", repo=REPOS.get(i))
    db.state_set(con, "last_pass", now - 4 * 60)  # "last checked 4 minutes ago"
    con.commit()
    con.close()
    topics = "\n".join('[[topics]]\nname = "%s"\n' % n for n in TOPIC_COLORS)
    with open(os.path.join(out, "config.toml"), "w", encoding="utf-8") as f:
        f.write('[page]\ntitle = "Artifact Explorer"\nupdate_check = false\n\n' + topics)


def build(out):
    """Build the page while this process stands in for a running watcher (the page shows it as of build)."""
    import json
    import subprocess
    with open(os.path.join(out, "watcher.json"), "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "t": time.time()}, f)
    env = dict(os.environ, AE_DATA=out, AE_UPDATE_CHECK="0")
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ae.py")
    subprocess.check_call([sys.executable, root, "build"], env=env)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
    build(sys.argv[1])
