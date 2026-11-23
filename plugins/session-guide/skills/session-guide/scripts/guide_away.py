#!/usr/bin/env python3
"""guide_away: away mode. While the user is away the guide takes the recommended option itself, inside a boundary,
records every such choice, and puts them in front of the user, with how to reverse each, once they are back.

    guide_title.py away --hours N | --until "YYYY-MM-DD HH:MM"    start (or move) the window
    guide_title.py away end                                       the user is back now
    guide_title.py away status
    guide_title.py away decide "<item>" "<option taken>" --reverse "<how>"
                                                                  a row, and a Decision "auto: user away"
    guide_title.py away hold "<item>" "<why>" "<exact action>"    a row the guide could not decide
    guide_title.py away reverse <#>… [--note "<text>"]            the user ticked these: Decisions that strike the
                                                                  auto ones
    guide_title.py away done <#>…                                 these held rows are settled
    guide_title.py away clear                                     after the return round: the block goes, open held
                                                                  rows become `waiting ask` rows

The state is `away.json` next to the ledger (like streams.json), so it survives a guide handoff:

    {"since": <epoch>, "until": <epoch>, "ended": null | <epoch>, "ended_by": "window" | "prompt" | "end",
     "decided": [{"n", "at", "item", "option", "reverse", "decision", "reversed_by"}],
     "held": [{"n", "at", "item", "why", "action", "done"}]}

The ledger's `## AWAY MODE` block (two tables: "Decided while you were away", "Waiting for you") is rewritten from it
on every change. The hook (guide_title.py) reads it on every guide prompt: away, back, or a phrase in the prompt that
says the user is leaving. Python 3 stdlib only.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guide_title as gt  # noqa: E402
import guide_streams as gs  # noqa: E402

SECTION = "## AWAY MODE"
DECIDED = "### Decided while you were away"
HELD = "### Waiting for you"
DECIDED_TABLE = ["| # | Time | Item | Option taken | How to reverse |\n", "|---|---|---|---|---|\n"]
HELD_TABLE = ["| # | Time | Item | Why held | Exact action |\n", "|---|---|---|---|---|\n"]
BEFORE = ("## Handoff", "## Streams", "## Order", "## Sessions")  # the block goes before the first of these
SHORT = "%m-%d %H:%M"  # Decisions and the block's Time cells
CLOCK = "%H:%M"
SLEEP_ICON = "\U0001f4a4"
AUTO = "auto: user away"
# A prompt the user did not type: a wake, a cron, a worker's message, a task notice. Anything else ends the window.
MACHINE = re.compile(r"^\s*(?:guide wake\b|<cross-session-message|<task-notification|<<autonomous-loop|"
                     r"\[cross-session|<scheduled-task|<system-reminder)", re.I)
HOURS = r"(\d+(?:\.\d+)?)\s*(?:h\b|hrs?\b|hours?\b)"
LEAVING = re.compile(r"\b(?:going to (?:sleep|bed)|off to (?:sleep|bed)|heading to bed|good ?night|"
                     r"(?:i'?m|i am|going|will be|i'?ll be) (?:away|afk|out(?!\s+of\b)|offline|off)\b|\bafk\b|"
                     r"stepping (?:away|out)|(?:be|i'?ll be|i will be) back\b|back in the morning|back tomorrow)", re.I)
RETURNING = re.compile(r"\b(?:(?:i'?m|i am|we'?re) back\b|back now\b|just got back)", re.I)
FOR_HOURS = re.compile(r"\b(?:for|in|next|another)\s+(?:about\s+|~)?" + HOURS, re.I)
MORNING = re.compile(r"\b(?:sleep|bed|good ?night|morning|tomorrow)\b", re.I)
MAX_HOURS = 72  # a window is bounded: at most three days
MORNING_AT = 9  # "back in the morning", "going to sleep": the suggested window ends at 09:00


def path_of(ledger):
    return os.path.join(os.path.dirname(os.path.abspath(os.path.expanduser(ledger))), "away.json")


def empty():
    return {"since": None, "until": None, "ended": None, "ended_by": None, "decided": [], "held": []}


def load(path):
    """The state in `path`; ValueError when it is there but isn't one (a writer must not replace it)."""
    try:
        with open(path, encoding="utf-8") as f:
            found = json.load(f)
    except FileNotFoundError:
        return empty()
    if not isinstance(found, dict) or not all(isinstance(found.get(k, []), list) for k in ("decided", "held")):
        raise ValueError("not an away-mode state")
    return dict(empty(), **found)


def read(ledger):
    """The ledger's away state; empty when the file is missing or can't be read (readers fail open)."""
    try:
        return load(path_of(ledger))
    except (OSError, ValueError):
        return empty()


def away_now(state, now=None):
    """True while the window is open: started, not ended, and its end not passed."""
    now = time.time() if now is None else now
    return bool(state.get("since") and not state.get("ended") and (state.get("until") or 0) > now)


def open_rows(state):
    return ([r for r in state["decided"] if not r.get("reversed_by")] + [r for r in state["held"] if not r.get("done")])


def save(ledger, state):
    ledger_lines(ledger)  # an unreadable ledger stops the write before either file changes
    gs.save(path_of(ledger), json.dumps(state, ensure_ascii=False, indent=1) + "\n")
    write_block(ledger, state)


def editing(ledger):
    """The lock to hold while changing the state; `save` inside it."""
    return gs.locked(path_of(ledger))


def load_for_write(ledger):
    try:
        return load(path_of(ledger))
    except (OSError, ValueError) as error:
        raise SystemExit("%s can't be read (%s); fix or move it first, nothing was changed" % (path_of(ledger), error))


def stamp(at, fmt=SHORT):
    return time.strftime(fmt, time.localtime(at))


def cell(text):
    return (text or "").replace("\n", " ").replace("|", "\\|").strip()


# --- the ledger block

def ledger_lines(ledger):
    """The ledger's lines, read strictly: a ledger that isn't valid UTF-8 is never rewritten."""
    try:
        with open(ledger, encoding="utf-8") as f:
            return f.read().splitlines(True)
    except UnicodeDecodeError as error:
        raise SystemExit("%s isn't valid UTF-8 (%s); fix it first, nothing was changed" % (ledger, error))


def block(state):
    """The `## AWAY MODE` block's lines; [] when there is nothing to show (not away, no rows)."""
    away = away_now(state)
    if not away and not state["decided"] and not state["held"]:
        return []
    if away:
        head = "%s (away since %s, until %s)" % (SECTION, stamp(state["since"]), stamp(state["until"]))
    else:
        head = "%s (back since %s; review the rows with the user, then `away clear`)" % (
            SECTION, stamp(state.get("ended") or state.get("until") or time.time()))
    out = [head + "\n", "\n", DECIDED + "\n"]
    rows = []
    for r in state["decided"]:
        text = [str(r["n"]), stamp(r["at"]), cell(r["item"]), cell(r["option"]),
                cell(r["reverse"]) + (" (Decision %s)" % r["decision"] if r.get("decision") else "")]
        if r.get("reversed_by"):
            text[2] = "~~%s~~ reversed by Decision %s" % (text[2], r["reversed_by"])
        rows.append("| %s |\n" % " | ".join(text))
    out += DECIDED_TABLE + rows + ["\n", HELD + "\n"]
    rows = []
    for r in state["held"]:
        text = [str(r["n"]), stamp(r["at"]), cell(r["item"]), cell(r["why"]), cell(r["action"])]
        if r.get("done"):
            text[2] = "~~%s~~ done %s" % (text[2], stamp(r["done"]))
        rows.append("| %s |\n" % " | ".join(text))
    return out + HELD_TABLE + rows + ["\n"]


def write_block(ledger, state):
    """Rewrite (or add, or remove) the ledger's AWAY MODE block from `state`."""
    lines = ledger_lines(ledger)
    start = next((i for i, l in enumerate(lines) if l.startswith(SECTION)), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        del lines[start:end]
    else:
        start = next((i for i, l in enumerate(lines) if l.startswith(BEFORE)), len(lines))
        if start == len(lines) and lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
    lines[start:start] = block(state)
    gt.write_ledger(ledger, lines)


# --- Decisions

DECISION = re.compile(r"^(\d+)\. ")


def decisions_span(lines):
    """(start, end) of the ledger's Decisions section; when it is missing, it is added before the first of the
    sections that follow it in the ledger template."""
    before = next((h for h in ("## Results for you", "## Waiting on", "## Claims", "## Open items")
                   if any(l.startswith(h) for l in lines)), "## Open items")
    return gt.section_span(lines, "## Decisions", "## Decisions (FINAL unless struck)", before)


def add_decision(ledger, text, strike=None):
    """Append Decision N (the next number) with `text`; with `strike` (a Decision number), strike that one through as
    "reversed by N". Returns N."""
    lines = ledger_lines(ledger)
    start, end = decisions_span(lines)
    numbers = [int(m.group(1)) for m in (DECISION.match(l) for l in lines[start + 1:end]) if m]
    number = max(numbers, default=0) + 1
    at = end
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1
    lines[at:at] = ["%d. %s\n" % (number, text.replace("\n", " "))]
    if strike is not None:
        for i in range(start + 1, min(end + 1, len(lines))):
            m = DECISION.match(lines[i])
            if m and int(m.group(1)) == strike and not lines[i][m.end():].startswith("~~"):
                lines[i] = "%s~~%s~~ reversed by %d\n" % (lines[i][:m.end()], lines[i][m.end():].rstrip("\n"), number)
                break
    if lines[at + 1:at + 2] and lines[at + 1].startswith("## "):  # keep a blank line before the next section
        lines.insert(at + 1, "\n")
    gt.write_ledger(ledger, lines)
    return number


# --- commands

def parse_until(text):
    at = gt.read_time(text)
    if not at:
        raise SystemExit('--until is local time as "YYYY-MM-DD HH:MM"')
    return at


def cmd_start(args, ledger):
    now = time.time()
    if (args.hours is None) == (args.until is None):
        raise SystemExit("give --hours N or --until \"YYYY-MM-DD HH:MM\"")
    if args.hours is not None and not 0 < args.hours <= MAX_HOURS:
        raise SystemExit("--hours is a number of hours, more than 0 and at most %d" % MAX_HOURS)
    until = now + args.hours * 3600 if args.hours is not None else parse_until(args.until)
    if until <= now:
        raise SystemExit("--until is in the past")
    if until > now + MAX_HOURS * 3600:
        raise SystemExit("away for at most %d hours" % MAX_HOURS)
    with editing(ledger):
        state = load_for_write(ledger)
        moved = away_now(state, now)
        if not moved:
            state.update(since=now, ended=None, ended_by=None)
        state["until"] = until
        save(ledger, state)
    print("%s until %s: no AskUserQuestion; inside the boundary take the recommended option with `away decide`, "
          "outside it `away hold`%s" % ("away window moved, now" if moved else "away", stamp(until),
                                        "; %d row(s) from before are still in the block" % len(open_rows(state))
                                        if open_rows(state) and not moved else ""))
    return 0


def end_window(ledger, how, now=None):
    """Close the window (`how`: window, prompt or end). True when it was open (or had passed, not yet closed)."""
    now = time.time() if now is None else now
    with editing(ledger):
        state = load_for_write(ledger)
        if not state.get("since") or state.get("ended"):
            return False
        state.update(ended=min(now, state.get("until") or now), ended_by=how)
        save(ledger, state)
    return True


def cmd_end(args, ledger):
    if not end_window(ledger, "end"):
        print("not away; nothing changed")
        return 0
    state = read(ledger)
    print("back: %d decided, %d waiting. Lead the status with them, then ONE multi-select \"Tick any to reverse\""
          % (len(state["decided"]), len([r for r in state["held"] if not r.get("done")])))
    return 0


def cmd_status(args, ledger):
    state = read(ledger)
    if away_now(state):
        print("away since %s, until %s" % (stamp(state["since"]), stamp(state["until"])))
    elif state.get("since") and not state.get("ended"):
        print("the window ended at %s; the next guide prompt marks the user back" % stamp(state["until"]))
    elif state.get("ended"):
        print("back since %s (%s)" % (stamp(state["ended"]), state.get("ended_by") or "?"))
    else:
        print("not away")
    for r in state["decided"]:
        print("- decided #%d %s: %s -> %s%s" % (r["n"], stamp(r["at"]), r["item"], r["option"],
                                               " (reversed by Decision %s)" % r["reversed_by"] if r.get("reversed_by")
                                               else "; to reverse: " + r["reverse"]))
    for r in state["held"]:
        print("- waiting #%d %s: %s (%s) -> %s%s" % (r["n"], stamp(r["at"]), r["item"], r["why"], r["action"],
                                                    " (done)" if r.get("done") else ""))
    return 0


def next_number(state):
    return max([r["n"] for r in state["decided"] + state["held"]], default=0) + 1


def same(a, b):
    return " ".join(a.lower().split()) == " ".join(b.lower().split())


def cmd_decide(args, ledger):
    item, option = need(args.words, 2, 'away decide "<item>" "<option taken>" --reverse "<how>"')
    if not args.reverse:
        raise SystemExit('--reverse "<how to reverse it>" is required: the user gets it on return')
    now = time.time()
    with editing(ledger):
        state = load_for_write(ledger)
        if not away_now(state, now) and not (args.timed_out and timed_out(ledger, item, now)):
            raise SystemExit("not away (the window is over or was never opened): ask the user instead. Only an owed "
                             "question past SESSION_GUIDE_AWAY_ASK_MINUTES is decided outside it, with --timed-out "
                             "and the question's exact words")
        if not away_now(state, now) and not open_rows(state):  # a timed-out question: no window to inherit
            state.update(since=None, until=None, ended=None, ended_by=None)
        old = next((r for r in state["decided"] if same(r["item"], item) and not r.get("reversed_by")), None)
        if old:
            print("already decided as #%d (Decision %s): %s" % (old["n"], old["decision"], old["option"]))
            return 0
        n = next_number(state)
        decision = add_decision(ledger, "(%s, %s) %s: %s. To reverse: %s (away #%d)"
                                % (stamp(now), AUTO, item.rstrip("."), option.rstrip("."), args.reverse.rstrip("."), n))
        state["decided"].append(dict(n=n, at=now, item=item, option=option, reverse=args.reverse, decision=decision,
                                     reversed_by=None))
        for r in state["held"]:  # a held item decided later is no longer waiting
            if same(r["item"], item) and not r.get("done"):
                r["done"] = now
        save(ledger, state)
    print("away #%d decided, Decision %d (%s)%s" % (n, decision, AUTO, "" if away_now(state, now) else
                                                    ", on a question that timed out"))
    return 0


def cmd_hold(args, ledger):
    item, why, action = need(args.words, 3, 'away hold "<item>" "<why>" "<exact action>"')
    now = time.time()
    with editing(ledger):
        state = load_for_write(ledger)
        old = next((r for r in state["held"] if same(r["item"], item) and not r.get("done")), None)
        if old:
            old.update(why=why, action=action)
            n = old["n"]
        else:
            n = next_number(state)
            state["held"].append(dict(n=n, at=now, item=item, why=why, action=action, done=None))
        save(ledger, state)
    print("away #%d %s under Waiting for you" % (n, "updated" if old else "held"))
    return 0


def numbers(words):
    try:
        found = [int(w.lstrip("#")) for w in words]
    except ValueError:
        raise SystemExit("give row numbers, as the block's # column shows them")
    if not found:
        raise SystemExit("give at least one row number")
    return found


def cmd_reverse(args, ledger):
    wanted, now, done = numbers(args.words), time.time(), []
    with editing(ledger):
        state = load_for_write(ledger)
        rows = {r["n"]: r for r in state["decided"]}
        missing = [n for n in wanted if n not in rows]
        if missing:
            raise SystemExit("no decided row #%s; there are: %s" % (", #".join(map(str, missing)),
                                                                   ", ".join("#%d" % n for n in rows) or "none"))
        for n in wanted:
            r = rows[n]
            if r.get("reversed_by"):
                continue
            r["reversed_by"] = add_decision(
                ledger, "(%s, user on return) Reverse away #%d (Decision %s, %s): %s%s"
                % (stamp(now), n, r["decision"], r["item"].rstrip("."), r["reverse"].rstrip("."),
                   "; " + args.note if args.note else ""), strike=r["decision"])
            done.append(r)
        save(ledger, state)
    for r in done:
        print("away #%d reversed: Decision %d strikes Decision %s. Now do it: %s"
              % (r["n"], r["reversed_by"], r["decision"], r["reverse"]))
    return 0


def cmd_done(args, ledger):
    wanted, now = numbers(args.words), time.time()
    with editing(ledger):
        state = load_for_write(ledger)
        rows = {r["n"]: r for r in state["held"]}
        missing = [n for n in wanted if n not in rows]
        if missing:
            raise SystemExit("no waiting row #%s" % ", #".join(map(str, missing)))
        for n in wanted:
            rows[n]["done"] = rows[n].get("done") or now
        save(ledger, state)
    print("away #%s done" % ", #".join(map(str, wanted)))
    return 0


def cmd_clear(args, ledger):
    with editing(ledger):
        state = load_for_write(ledger)
        if away_now(state):
            raise SystemExit("still away until %s: `away end` first" % stamp(state["until"]))
        held = [r for r in state["held"] if not r.get("done")]
        owed = gt.waiting_rows(ledger)
        for r in held:  # still waiting: an owed question, due now, so it survives the block (once)
            if gt.owed_key(bare(r["item"])) in owed:
                continue
            gt.owed_question(ledger, "%s: %s" % (r["item"].rstrip("."), r["action"]),
                             argparse_ns(hours=None, at=None, closes=None))
        save(ledger, empty())
    print("away block cleared: %d decided row(s) stay as Decisions, %d waiting row(s) moved to `waiting ask`"
          % (len(state["decided"]), len(held)))
    return 0


def argparse_ns(**kw):
    import argparse
    return argparse.Namespace(**kw)


def need(words, n, usage):
    if len(words) != n or not all(w.strip() for w in words):
        raise SystemExit("usage: " + usage)
    return words


# --- the hook's lines

def suggest(prompt, now=None):
    """The `away` command a leaving phrase suggests, or None when the prompt says nothing about leaving."""
    if not prompt or MACHINE.match(prompt) or RETURNING.search(prompt) or not LEAVING.search(prompt):
        return None
    hours = FOR_HOURS.search(prompt)
    if hours:
        return "away --hours %g" % float(hours.group(1))
    if MORNING.search(prompt):
        now = time.time() if now is None else now
        t = time.localtime(now)
        at = time.mktime((t.tm_year, t.tm_mon, t.tm_mday + (t.tm_hour >= MORNING_AT - 3), MORNING_AT, 0, 0, 0, 0, -1))
        return 'away --until "%s"' % time.strftime(gt.TIME_FORMAT, time.localtime(at))
    return "away --hours <N from their words>"


def typed(prompt):
    """A prompt the user typed (not a wake, cron, worker message or task notice)."""
    return bool(prompt and prompt.strip()) and not MACHINE.match(prompt)


def late(row, now, minutes):
    """An owed question unanswered `minutes` after it came due (never one deferred to later)."""
    return row["owed"] and max(gt.read_time(row["asked"]), gt.read_time(row["remind"])) <= now - minutes * 60


def bare(question):
    """An owed question without the closes: tag its row may carry."""
    return re.sub(r"\s*\u00b7?\s*\bcloses:.*$", "", question)


def timed_out(ledger, question, now):
    """True when `question` is an owed question past SESSION_GUIDE_AWAY_ASK_MINUTES."""
    minutes = ask_minutes()
    row = gt.waiting_rows(ledger).get(gt.owed_key(bare(question)))
    return bool(minutes and row and late(row, now, minutes))


def ask_minutes():
    """SESSION_GUIDE_AWAY_ASK_MINUTES: an owed question unanswered this long is treated as away (0, the default,
    is off)."""
    try:
        return max(0.0, float(os.environ.get("SESSION_GUIDE_AWAY_ASK_MINUTES") or 0))
    except ValueError:
        return 0.0


def title_note(ledger):
    """"💤 until 09:16" while away, else ""."""
    state = read(ledger)
    return "%s until %s" % (SLEEP_ICON, stamp(state["until"], CLOCK)) if away_now(state) else ""


def summary(state):
    lines = ["- #%d %s %s -> %s; to reverse: %s" % (r["n"], stamp(r["at"]), r["item"], r["option"], r["reverse"])
             for r in state["decided"] if not r.get("reversed_by")]
    held = ["- #%d %s %s (%s): %s" % (r["n"], stamp(r["at"]), r["item"], r["why"], r["action"])
            for r in state["held"] if not r.get("done")]
    return lines, held


def context(ledger, prompt=None, event="UserPromptSubmit"):
    """(away line or None, away now). The window ends here when its time has passed or the user typed a prompt."""
    script = os.path.abspath(gt.__file__)
    state = read(ledger)
    now = time.time()
    if state.get("since") and not state.get("ended"):
        if not away_now(state, now):
            end_window(ledger, "window", now)
        elif event == "UserPromptSubmit" and typed(prompt) and not suggest(prompt):
            end_window(ledger, "prompt", now)
        state = read(ledger)
    if away_now(state, now):
        return ("session-guide away: the user is away until %s (since %s). This overrides every question and dialog "
                "rule below: no AskUserQuestion, and nothing waits on the user. Each question you would ask: inside "
                "the boundary (SKILL §10: reversible only), take its recommended option, run `python3 %s away "
                "decide \"<item>\" \"<option taken>\" --reverse \"<how>\"`, and act on it (relay it like any "
                "Decision); outside it (merges, prod/staging writes, publishing or sharing to others, deletes, "
                "messages to people, money or business rules that reach real data, anything only the user can "
                "type), `python3 %s away hold \"<item>\" \"<why>\" \"<exact action>\"` and tell the worker it is held. "
                "Reminders, Results verdicts and owed questions that come due: `away hold` each, never asked. Wakes "
                "keep their normal cadence. %d decided, %d waiting so far."
                % (stamp(state["until"]), stamp(state["since"]), script, script, len(state["decided"]),
                   len([r for r in state["held"] if not r.get("done")])), True)
    decided, held = summary(state)
    if (decided or held) and (state.get("ended") or (event == "UserPromptSubmit" and typed(prompt))):
        # timed-out decisions with no window come up on a prompt the user typed, never on a wake
        why = ({"window": "the window ended", "prompt": "they typed a prompt", "end": "`away end`"}.get(
            state.get("ended_by"), "the window ended") + ", " + stamp(state["ended"]) if state.get("ended")
            else "questions decided after SESSION_GUIDE_AWAY_ASK_MINUTES")
        return ("session-guide away: the user is back (%s). Your first status reply leads with **Decided while "
                "you were away** (each row with how to reverse it) and **Waiting for you** (each with its exact "
                "action), then, when something was decided, ONE AskUserQuestion, multi-select, \"Tick any to "
                "reverse\", one "
                "option per decided row "
                "(\"Reverse #N: <item>\"; over 4 rows, up to 4 such questions in the call; past 16, list the rest by "
                "number in your text and wait for the user's answer on them before `away clear`). Ticked: "
                "`python3 %s away reverse <#>…` (a Decision that strikes the auto one), then do what "
                "its row says. Settled waiting rows: `away done <#>…`. Then `python3 %s away clear`.\n"
                "Decided while you were away:\n%s\nWaiting for you:\n%s"
                % (why, script, script, "\n".join(decided) or "- none",
                   "\n".join(held) or "- none"), False)
    hint = suggest(prompt) if event == "UserPromptSubmit" else None
    if hint:
        return ("session-guide away: the user's prompt says they are leaving. Do not enter away mode silently: run "
                "`python3 %s %s` (the end from their words), and say in ONE text line until when, and that you "
                "will decide only reversible things and hold the rest." % (script, hint), False)
    minutes = ask_minutes()
    if minutes:
        overdue = [r for r in gt.waiting_rows(ledger).values() if late(r, now, minutes)]
        if overdue:
            return ("session-guide away: %d owed question(s) unanswered for over %g min "
                    "(SESSION_GUIDE_AWAY_ASK_MINUTES): treat the user as away for each. Inside the boundary: "
                    "`away decide \"<question>\" \"<recommended option>\" --reverse \"<how>\" --timed-out`, then "
                    "`unwait <key>`; "
                    "outside it, leave the row. They are listed on return:\n%s"
                    % (len(overdue), minutes, "\n".join("- [%s] %s" % (gt.row_id(r["session"]), bare(r["what"]))
                                                       for r in overdue[:8])), False)
    return None, False


def state_lines(ledger):
    """STATE.md's away section; [] while there is nothing in the block."""
    state = read(ledger)
    if not away_now(state) and not state["decided"] and not state["held"]:
        return []
    decided, held = summary(state)
    head = ("away until %s" % stamp(state["until"])) if away_now(state) else "user back, `away clear` not run yet"
    settled = ["- #%d %s: %s" % (r["n"], r["item"], "reversed by Decision %s" % r["reversed_by"]
                                 if r.get("reversed_by") else "done") for r in state["decided"] + state["held"]
               if r.get("reversed_by") or r.get("done")]
    title = "## Away mode (%s; %d decided, %d waiting)" % (head, len(decided), len(held))
    return ["", title] + decided + held + settled


def cmd_away(args):
    ledger = os.path.expanduser(args.ledger or gt.require_ledger())
    action = args.action or "start"
    if action != "start" and (args.hours is not None or args.until):
        raise SystemExit("--hours and --until go with `away` alone")
    if action in ("start", "end", "status", "clear") and args.words:
        raise SystemExit("`away %s` takes no words" % action)
    if action != "status":
        ledger_lines(ledger)  # a ledger that isn't UTF-8 stops every writer before it changes anything
    return {"start": cmd_start, "end": cmd_end, "status": cmd_status, "decide": cmd_decide, "hold": cmd_hold,
            "reverse": cmd_reverse, "done": cmd_done, "clear": cmd_clear}[action](args, ledger)


def add_parser(sub):
    p = sub.add_parser("away", help="away mode: the guide decides reversible things itself and holds the rest")
    p.add_argument("action", nargs="?", choices=("end", "status", "decide", "hold", "reverse", "done", "clear"),
                   help="none: start (or move) the window")
    p.add_argument("words", nargs="*",
                   help="decide: item, option; hold: item, why, action; reverse / done: row numbers")
    p.add_argument("--hours", type=float, help="away for this many hours")
    p.add_argument("--until", help="away until this local time, YYYY-MM-DD HH:MM")
    p.add_argument("--reverse", help="decide: how to reverse it")
    p.add_argument("--timed-out", action="store_true",
                   help="decide: an owed question past SESSION_GUIDE_AWAY_ASK_MINUTES, outside any window")
    p.add_argument("--note", help="reverse: what the user said")
    p.add_argument("--ledger", help="any ledger (default: this guide's)")
