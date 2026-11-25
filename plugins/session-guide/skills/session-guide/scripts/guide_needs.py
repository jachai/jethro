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
which the item was listed and not answered. The counts live in <ledger dir>/needs-input.json, by Waiting row key:
an item that is answered (`unwait`), put off (`sleep`, so not due) or decided is dropped, and counts from zero if it
comes due again. Readers fail open: an unreadable file counts as empty. Python 3 stdlib only.
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


def number(name, default):
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except ValueError:
        return float(default)


def limits():
    """(turns, minutes): SESSION_GUIDE_INTERVIEW_TURNS and SESSION_GUIDE_INTERVIEW_MINUTES; 0 turns one off."""
    return number("SESSION_GUIDE_INTERVIEW_TURNS", INTERVIEW_TURNS), number("SESSION_GUIDE_INTERVIEW_MINUTES",
                                                                           INTERVIEW_MINUTES)


def path_of(ledger):
    return os.path.join(os.path.dirname(os.path.abspath(os.path.expanduser(ledger))), "needs-input.json")


def read(ledger):
    """{key: {first, turns}}; {} when the file is missing or isn't one."""
    try:
        with open(path_of(ledger), encoding="utf-8") as f:
            found = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(found, dict):
        return {}
    return {k: v for k, v in found.items() if isinstance(v, dict) and isinstance(v.get("first"), (int, float))
            and isinstance(v.get("turns"), int)}


def due_items(ledger, now):
    """{key: what} of the Waiting rows that are due now: the needs-input items the guide lists in its text."""
    return {key: row["what"] for key, row in gt.waiting_rows(ledger).items() if gt.read_time(row["remind"]) <= now}


def asked_for(prompt):
    """True when a typed prompt asks the guide to interview the user now."""
    if not prompt:
        return False
    machine = getattr(gt.away_module(), "MACHINE", None)
    return not (machine and machine.match(prompt)) and bool(ASK_ME.search(prompt))


def is_overdue(entry, turns, minutes, now):
    return bool((turns and entry["turns"] >= turns) or (minutes and now - entry["first"] >= minutes * 60))


def tick(ledger, now=None):
    """One guide turn while workers work: count every due item, forget the ones no longer due, and return
    [(key, what)] of the overdue ones, oldest first. Nothing is written when the rule is off or nothing changes."""
    now = time.time() if now is None else now
    turns, minutes = limits()
    if not turns and not minutes:
        return []
    due = due_items(ledger, now)
    path = path_of(ledger)
    if not due and not os.path.exists(path):
        return []
    with gs.locked(path):
        old = read(ledger)
        seen = {key: ({"first": old[key]["first"], "turns": old[key]["turns"] + 1} if key in old
                      else {"first": int(now), "turns": 0}) for key in due}
        gs.save(path, json.dumps(seen, indent=1, sort_keys=True) + "\n")
    late = [key for key in due if is_overdue(seen[key], turns, minutes, now)]
    return [(key, due[key]) for key in sorted(late, key=lambda k: seen[k]["first"])]


def overdue(ledger, now=None):
    """[(key, what)] of the overdue items, without counting a turn (`guide_title.py working`)."""
    now = time.time() if now is None else now
    turns, minutes = limits()
    if not turns and not minutes:
        return []
    due, seen = due_items(ledger, now), read(ledger)
    late = [key for key in due if key in seen and is_overdue(seen[key], turns, minutes, now)]
    return [(key, due[key]) for key in sorted(late, key=lambda k: seen[k]["first"])]


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
