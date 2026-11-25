#!/usr/bin/env python3
"""guide_needs: when the needs-input items that wait in text go into the interview.

While MANAGED workers are working, the guide asks only blocking questions in a dialog and lists everything else in its
text under **Needs you now** with a `needs input:` line, each with a Waiting row behind it (SKILL.md §4, The interview,
rule 1). A text line is one the user can miss, so an item must not wait there for ever:

    overdue    a due Waiting row (an owed `waiting ask` question or a session's reminder) that the hook has already
               seen on SESSION_GUIDE_INTERVIEW_TURNS earlier guide turns (default 2) while workers were working, or
               that has been listed for SESSION_GUIDE_INTERVIEW_MINUTES (default 15) since the hook first saw it.
               0 turns off that half; both 0 turns the rule off.
    asked for  the user's typed prompt asks for the interview ("interview me", "ask me now", "open the interview").

Either one makes the hook's workers line say "open the interview now": drain and relay first, then AskUserQuestion
with the items, up to 4 questions a call, rounds until none is left, even though workers are working.

A turn is a UserPromptSubmit that reaches the guide (a typed prompt, a wake, a worker message): each one is a turn on
which the item was listed and not answered. Only the due rows the guide would ask about count: open
sessions' reminders and owed questions, not the ones a later ledger row already covers. The counts live in
<ledger dir>/needs-input.json, by Waiting row key with the row's Asked and Remind at: an item that is answered
(`unwait`), put off (`sleep`, so not due, and a new Remind at) or written again starts from zero. Readers fail open: an unreadable file counts as empty. Python 3 stdlib only.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guide_streams as gs  # noqa: E402
import guide_title as gt  # noqa: E402

INTERVIEW_TURNS = 2  # earlier turns an item was listed on before it goes in a dialog (SESSION_GUIDE_INTERVIEW_TURNS)
INTERVIEW_MINUTES = 15  # or minutes since it was first listed (SESSION_GUIDE_INTERVIEW_MINUTES)
ASK_ME = re.compile(r"\b(?:interview me|(?:open|start|run|do|begin) (?:the|an|your) interview|"
                    r"ask me (?:now|them|those|these|(?:about )?the (?:open|pending|needs[- ]?input|waiting) "
                    r"(?:items?|questions?))|ask me about (?:the )?needs[- ]?input)\b", re.I)


def limits():
    """(turns, minutes): SESSION_GUIDE_INTERVIEW_TURNS and SESSION_GUIDE_INTERVIEW_MINUTES; 0 turns one off."""
    return (gt.env_number("SESSION_GUIDE_INTERVIEW_TURNS", INTERVIEW_TURNS),
            gt.env_number("SESSION_GUIDE_INTERVIEW_MINUTES", INTERVIEW_MINUTES))


def path_of(ledger):
    return os.path.join(os.path.dirname(os.path.abspath(os.path.expanduser(ledger))), "needs-input.json")


def read(ledger):
    """{key: {first, turns, row}}; {} when the file is missing or isn't one."""
    try:
        with open(path_of(ledger), encoding="utf-8") as f:
            found = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(found, dict):
        return {}
    return {k: v for k, v in found.items() if isinstance(v, dict) and isinstance(v.get("first"), (int, float))
            and isinstance(v.get("turns"), int)}


def signature(row):
    """A row's Asked and Remind at: a snooze (new Remind at) or a row written again (new Asked) starts a new count."""
    return "%s|%s" % (row.get("asked", ""), row.get("remind", ""))


def asked_for(prompt):
    """True when a typed prompt asks the guide to interview the user now."""
    if not prompt:
        return False
    machine = getattr(gt.away_module(), "MACHINE", None)
    return not (machine and machine.match(prompt)) and bool(ASK_ME.search(prompt))


def is_overdue(entry, turns, minutes, now):
    return bool((turns and entry["turns"] >= turns) or (minutes and now - entry["first"] >= minutes * 60))


def late_items(rows, seen, now):
    """[(key, what)] of the `rows` whose counts in `seen` are overdue, oldest first."""
    turns, minutes = limits()
    late = [r for r in rows if r["id"] in seen and seen[r["id"]].get("row") == signature(r)
            and is_overdue(seen[r["id"]], turns, minutes, now)]
    return [(r["id"], r["what"]) for r in sorted(late, key=lambda r: seen[r["id"]]["first"])]


def tick(ledger, rows, now=None):
    """One guide turn while workers work. `rows` are the due Waiting rows the guide would ask about
    (guide_title.needs_rows): count each, forget the rest, and return [(key, what)] of the overdue ones. The file is
    written only when the rule is on and the counts change."""
    now = time.time() if now is None else now
    if not any(limits()):
        return []
    path = path_of(ledger)
    if not rows and not os.path.exists(path):
        return []
    with gs.locked(path):
        old = read(ledger)
        seen = {}
        for r in rows:
            before = old.get(r["id"])
            seen[r["id"]] = (dict(before, turns=before["turns"] + 1) if before and before.get("row") == signature(r)
                             else {"first": int(now), "turns": 0, "row": signature(r)})
        if seen != old:
            gs.save(path, json.dumps(seen, indent=1, sort_keys=True) + "\n")
    return late_items(rows, seen, now)


def overdue(ledger, rows, now=None):
    """[(key, what)] of the overdue `rows`, without counting a turn (`guide_title.py working`)."""
    now = time.time() if now is None else now
    return late_items(rows, read(ledger), now) if any(limits()) else []


def sentence(items, asked=False):
    """The 'open the interview now' part of the workers line, or "" when there is nothing to open it for."""
    if not items and not asked:
        return ""
    turns, minutes = limits()
    why = ("The user asked for the interview" if asked else "%d needs-input item(s) went unanswered in text for %s"
           % (len(items), " or ".join(p for p in (turns and "%g turns" % turns, minutes and "%g min" % minutes) if p)))
    shown = "; ".join("[%s] %s" % (key, what[:80]) for key, what in items[:6])
    shown += "; and %d more" % (len(items) - 6) if len(items) > 6 else ""
    return (" OPEN THE INTERVIEW NOW: %s%s. Act on every worker message and relay first, then AskUserQuestion with "
            "every open needs-input item (owed questions, due reminders, verdicts, model switches, open items), "
            "blocking ones first, up to 4 questions a call, and open the next round straight away until none is "
            "left, even though workers are working." % (why, " (%s)" % shown if shown else ""))
