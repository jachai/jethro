#!/usr/bin/env python3
"""guide_finished: the sessions that ended on their own, with nobody managing them.

    python3 guide_finished.py --ledger <ledger.md> [--hours 24] [--reviewed [<id> ...]]
    (the same as `guide_title.py finished`)

A prompt fired and forgotten is the session nobody follows up: it has no row, or an ACTIVE one, so reconcile (which
reads MANAGED and WATCHED rows) never sees it end. scan() gives every such session that ended in the last 24 h
(SESSION_GUIDE_FINISHED_HOURS, 0 = off) one look at its final message:

    result       its last `result:` line, else the job's result line, else the last line it wrote
    loose ends   the job stopped, failed or waits on input; it ended on an API error or with no final message; the
                 result says BLOCKED or HANDED OFF; it ends on a question or a `needs input:` line; or its last words
                 say not done / follow-up / blocked / refused / failed (a "no", "not" or "0" just before doesn't count)
    link         the first link in the result line, else the last one in the final message

Looked at: sessions with no Sessions row or an ACTIVE one, whose job is not `working` with a live process (no job:
no live process), quiet for SESSION_GUIDE_FINISHED_QUIET_MINUTES (default 15, so a conversation the user is in the
middle of is left alone). Left out: this session, guides, closed sessions, and rows at any other level (MANAGED and
WATCHED belong to reconcile; DONE, HANDED OFF and the rest were already dealt with).

`claude -p` and launchd runs (entrypoint `sdk…`) are scripts: they are grouped by job (folder + the start of the
prompt) into one line, and only a job with a failed or refused run is shown. A run that ended well is remembered at
once, since it is never shown.

`--reviewed` marks every clean finish as looked at; `--reviewed <id> ...` marks those sessions (a loose end the guide
has recorded as an Open items row or a question; a job's latest run marks the whole job). Marks live in
<ledger dir>/finished.json, by session id and the time it ended: a reviewed session that is prompted again and ends
again gets a new look. A look never messages the session. Python 3 stdlib only.
"""
import argparse
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guide_reconcile as gr  # noqa: E402
import guide_title as gt  # noqa: E402

FINISHED_HOURS = 24  # how far back the look goes (SESSION_GUIDE_FINISHED_HOURS, 0 = off)
QUIET_MINUTES = 15  # an ended session is left alone this long (SESSION_GUIDE_FINISHED_QUIET_MINUTES)
KEEP_DAYS = 7  # how long a reviewed mark is kept
RESULT = re.compile(r"^[\W_]*result:\s*(.+)$", re.I | re.M)
NEEDS = re.compile(r"^[\W_]*needs input:\s*(.+)$", re.I)
LOOSE = re.compile(r"\b(?:not (?:yet )?(?:done|finished|completed?|verified|tested|pushed|merged|deployed|fixed)|"
                   r"unfinished|incomplete|follow[- ]?ups?|blocked|refus(?:ed|es|al)|declined|denied|could ?not|"
                   r"couldn['’]t|unable to|failed|left (?:open|undone)|still (?:open|owed|failing|broken)|todo)\b",
                   re.I)
FAILED = re.compile(r"\b(?:fail(?:ed|ure|ures)|errors?|crash(?:ed|es)|timed out|(?:could not|couldn['’]t|unable to)|"
                    r"abort(?:ed|s))\b", re.I)
REFUSED = re.compile(r"\b(?:I (?:can(?:no|['’])t|won['’]t|will not|am (?:not able|unable))|"
                     r"I['’]m (?:not able|unable)|refus(?:ed?|es|al|ing)|declin(?:ed?|es|ing)|"
                     r"not (?:allowed|permitted|authori[sz]ed)|permission (?:was )?denied)\b", re.I)
FAILED_FIRST = re.compile(gr.FIRST + r"(?:FAILED|FAILURE|ERROR|BLOCKED|REFUSED)\b")
NEGATED = re.compile(r"\b(?:no|not|nothing|none|never|without|zero|0)\W+(?:\w+\W+){0,2}$", re.I)
LINK = re.compile(r"https?://[^\s)>\]\"'`]+")


def number(name, default):
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except ValueError:
        return float(default)


def finished_hours():
    return number("SESSION_GUIDE_FINISHED_HOURS", FINISHED_HOURS)


def reviewed_path(ledger):
    return os.path.join(os.path.dirname(os.path.abspath(ledger)), "finished.json")


def read_reviewed(ledger):
    """{session id: {ended, mtime, at, as}}; {} when there is no readable file."""
    try:
        with open(reviewed_path(ledger)) as f:
            found = json.load(f)
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(ledger, entries, kind=None):
    """Mark `entries` (scan's sessions or runs) as looked at, and drop marks older than KEEP_DAYS."""
    if not entries:
        return
    marks, now = read_reviewed(ledger), time.time()
    for entry in entries:
        marks[entry["id"]] = {"ended": int(entry["ended"]), "mtime": int(entry["mtime"]),
                              "at": time.strftime(gt.TIME_FORMAT), "as": kind or entry["kind"]}
    marks = {sid: m for sid, m in marks.items() if isinstance(m, dict) and now - m.get("ended", 0) < KEEP_DAYS * 86400}
    path = reviewed_path(ledger)
    with open(path + ".tmp", "w") as f:
        json.dump(marks, f, indent=1, sort_keys=True)
    os.replace(path + ".tmp", path)


def blocks_of(entry):
    content = (entry.get("message") or {}).get("content")
    blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content or "")}]
    return [b for b in blocks if isinstance(b, dict)]


def head_facts(path):
    """(entrypoint, folder, first prompt) from a transcript's first lines."""
    entrypoint, folder, prompt = "", "", ""
    with open(path, "rb") as f:
        for _ in range(40):
            line = f.readline()
            if not line:
                break
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            entrypoint = entrypoint or str(entry.get("entrypoint") or "")
            folder = folder or str(entry.get("cwd") or "")
            if not prompt and entry.get("type") == "user" and not entry.get("isMeta"):
                texts = (b.get("text") or "" for b in blocks_of(entry) if b.get("type") == "text")
                prompt = " ".join(" ".join(texts).split())
            if entrypoint and folder and prompt:
                break
    return entrypoint, folder, prompt


def last_message(path):
    """{text, at, cut, error}: the last thing a session said (its text after the last tool result), when (an epoch or
    None), whether it stopped with no final message (on a tool call, a tool result or an unanswered prompt), and
    whether it ended on an API error. Reads the transcript's last 300 KB."""
    texts, at, cut, error, first = [], None, False, False, True
    for raw in reversed(gr.tail_lines(path, gr.TRANSCRIPT_TAIL)):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") not in ("assistant", "user") or entry.get("isSidechain") \
                or entry.get("isMeta"):
            continue
        blocks = blocks_of(entry)
        kinds = {b.get("type") for b in blocks}
        if first:
            at, first = gt.iso_epoch(str(entry.get("timestamp") or "")), False
            error = bool(entry.get("isApiErrorMessage"))
            cut = entry["type"] == "user" or "tool_use" in kinds
        if entry["type"] == "user":
            if "tool_result" in kinds and not texts:
                continue  # it stopped on a tool: look further back for the last thing it said
            break
        said = "\n".join(b.get("text") or "" for b in blocks if b.get("type") == "text").strip()
        if said:
            texts.insert(0, said)
    return dict(text="\n".join(texts), at=at, cut=cut, error=error)


def one_line(text, size=200):
    text = " ".join(str(text).split())
    return text if len(text) <= size else text[:size - 1].rstrip() + "…"


def result_line(text, job_result=""):
    """A final message's result: its last `result:` line, else the job's result line, else its last line."""
    found = RESULT.findall(text)
    if found:
        return found[-1].strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return job_result or (lines[-1] if lines else "")


def open_question(text):
    """The question a final message leaves open: a `needs input:` line, else one of its last three lines (the result
    line aside) that ends with a question mark. "" when there is none."""
    lines = [l.strip() for l in text.splitlines() if l.strip() and not RESULT.match(l)]
    for line in lines:
        found = NEEDS.match(line)
        if found:
            return "needs input: " + found.group(1).strip()
    return next((l for l in reversed(lines[-3:]) if l.rstrip("*_`)\"' ").endswith("?")), "")


def worded(pattern, text):
    """The line of `text` where `pattern` matches with no "no / not / 0" just before it, or ""."""
    for found in pattern.finditer(text):
        if NEGATED.search(text[max(0, found.start() - 30):found.start()]):
            continue
        start = text.rfind("\n", 0, found.start()) + 1
        end = text.find("\n", found.end())
        return text[start:end if end >= 0 else len(text)].strip()
    return ""


def loose_ends(last, result, state=""):
    """Why a finished session still needs someone, as short reasons; [] for a clean finish."""
    why, text = [], last["text"]
    if state in ("stopped", "failed", "blocked"):
        why.append("its job is %s" % state)
    if last["error"]:
        why.append("ended on an API error")
    elif last["cut"]:
        why.append("stopped with no final message")
    if gr.is_handoff(result):
        why.append("handed off, and nobody was told to continue")
    elif gr.is_blocked(result):
        why.append("its result says it is blocked")
    question = open_question(text)
    if question:
        why.append("asks: " + one_line(question, 160))
    said = worded(LOOSE, result) or worded(LOOSE, text[-1200:])
    if said and not question == said:
        why.append("says: " + one_line(said, 160))
    return why


def run_failure(last, result):
    """Why a `claude -p` run failed or was refused, or "" when it ended well."""
    if last["error"]:
        return "ended on an API error"
    if last["cut"] or not last["text"].strip():
        return "stopped with no final message"
    if FAILED_FIRST.match(result):
        return "failed: " + one_line(result, 160)
    failed = worded(FAILED, result) or worded(FAILED, last["text"][-600:])
    if failed:
        return "failed: " + one_line(failed, 160)
    said = worded(REFUSED, result) or worded(REFUSED, last["text"][:600])
    return "refused: " + one_line(said, 160) if said else ""


def link_in(result, text):
    found = LINK.findall(result) or LINK.findall(text)[-1:]
    return found[0].rstrip(".,;:") if found else ""


def job_key(folder, prompt):
    """What makes two `claude -p` runs the same job: the folder and the start of the prompt, numbers aside."""
    return folder, re.sub(r"\d+", "#", prompt[:60]).strip().lower()


def scan(ledger, me="", hours=None, now=None, record=True):
    """{sessions, jobs}: the look described in the module docstring.

    sessions: [{id, title, level ("ACTIVE" or ""), ended, mtime, result, why ([] = clean), link, kind ("loose" or
    "clean")}], loose ends first, then newest first. jobs: [{id (the latest failed run), name, folder, runs (the
    failed ones, each {id, ended, mtime, why}), ended, why, kind "job-failed"}], only jobs with a failed or refused
    run. With `record`, runs that ended well are remembered at once (the only thing this writes)."""
    hours = finished_hours() if hours is None else hours
    now = time.time() if now is None else now
    out = dict(sessions=[], jobs=[])
    if hours <= 0:
        return out
    quiet = max(gr.default_grace(), number("SESSION_GUIDE_FINISHED_QUIET_MINUTES", QUIET_MINUTES)) * 60
    levels, marks, groups, fine = gt.session_levels(ledger), read_reviewed(ledger), {}, []
    for path in glob.glob(os.path.join(gt.config_dir(), "projects", "*", "*.jsonl")):
        try:
            mtime, sid = os.path.getmtime(path), os.path.basename(path)[:-6]
            mark = marks.get(sid) if isinstance(marks.get(sid), dict) else None
            if (now - mtime > hours * 3600 or sid == me or not os.path.getsize(path)
                    or (mark and mark.get("mtime") == int(mtime))):
                continue
            level = levels.get(sid[:6].lower(), ("",))[0]
            content = gt.marker_content(sid)
            if level not in ("", "ACTIVE") or (content is not None and content not in gt.WORKER_MARKERS):
                continue  # managed, watched or dealt with; closed, retired or a guide
            state = gt.job_state(sid)
            if gt.session_alive(sid) and state in ("", "working"):
                continue  # still running (a session with no job runs for as long as a process holds it)
            facts = gr.job_facts(sid) if state else None
            last = last_message(path)
            ended = (facts["ended_at"].timestamp() if facts and facts["ended_at"] else None) or last["at"] or mtime
            if now - ended < quiet or now - ended > hours * 3600 or (mark and ended <= mark.get("ended", 0) + 1):
                continue
            entrypoint, folder, prompt = head_facts(path)
            result = result_line(last["text"], facts["result"] if facts else "")
            if entrypoint.startswith("sdk"):
                why = run_failure(last, result)
                run = dict(id=sid, ended=ended, mtime=mtime, why=why, kind="job-failed" if why else "job-ok")
                if not why:
                    fine.append(run)
                    continue
                group = groups.setdefault(job_key(folder, prompt), dict(
                    name=one_line(prompt, 60) or "no prompt", folder=os.path.basename(folder.rstrip("/")), runs=[]))
                group["runs"].append(run)
                continue
            why = loose_ends(last, result, state)
            out["sessions"].append(dict(id=sid, title=gt.transcript_facts(path)[1], level=level, ended=ended,
                                        mtime=mtime, result=one_line(result), why=why, kind="loose" if why else "clean",
                                        link=link_in(result, last["text"])))
        except OSError:  # a transcript removed while we read
            continue
    for group in groups.values():
        group["runs"].sort(key=lambda r: -r["ended"])
        group.update(id=group["runs"][0]["id"], ended=group["runs"][0]["ended"], why=group["runs"][0]["why"],
                     kind="job-failed")
        out["jobs"].append(group)
    out["sessions"].sort(key=lambda s: (not s["why"], -s["ended"]))
    out["jobs"].sort(key=lambda g: -g["ended"])
    if record:
        remember(ledger, fine)
    return out


def clock(epoch):
    return time.strftime("%H:%M", time.localtime(epoch))


def describe(entry):
    """One line for a finished session or a failed job."""
    if entry["kind"] == "job-failed":
        return ("JOB '%s' (%s): %d run(s) failed or refused, latest [%s] %s: %s"
                % (entry["name"], entry["folder"] or "no folder", len(entry["runs"]), entry["id"][:8],
                   clock(entry["ended"]), entry["why"]))
    line = "%s '%s' [%s] (%s), ended %s: %s" % (
        "LOOSE END" if entry["why"] else "clean", (entry["title"] or "no title yet").replace("'", ""), entry["id"][:8],
        "ACTIVE row" if entry["level"] else "no row", clock(entry["ended"]), entry["result"] or "no result line")
    line += " | why: " + "; ".join(entry["why"]) if entry["why"] else ""
    return line + (" | " + entry["link"] if entry["link"] else "")


def context(ledger, me="", script="guide_title.py"):
    """The hook's paragraph, or None when nothing finished unseen."""
    found = scan(ledger, me)
    entries = found["sessions"] + found["jobs"]
    if not entries:
        return None
    loose = sum(1 for s in found["sessions"] if s["why"]) + len(found["jobs"])
    lines = ["- " + describe(e) for e in entries[:8]] + ["- and %d more" % (len(entries) - 8)] * (len(entries) > 8)
    more = " With more than 8, run `%s finished` for the rest." % script if len(entries) > 8 else ""
    return ("session-guide finished: %d session(s) or job(s) ended on their own in the last %g h with nobody managing "
            "them, %d with a loose end:\n%s\n"
            "List each in your status under **Finished on their own** (title [id6], one line of result, link). A "
            "loose end becomes an Open items row or a question in this round: read its final message first (`peek`), "
            "and never message an ACTIVE session. Then `%s finished --reviewed <id8> ...` with each one you listed "
            "(clean ones and recorded loose ends alike), so none is shown twice.%s"
            % (len(entries), finished_hours(), loose, "\n".join(lines), script, more))


def mark_reviewed(ledger, ids, me=""):
    """`--reviewed`: with no ids every clean finish, else the listed sessions (a job's latest run marks all its failed
    runs). Returns the lines to print."""
    found = scan(ledger, me)
    if not ids:
        clean = [s for s in found["sessions"] if not s["why"]]
        remember(ledger, clean)
        return ["Reviewed: " + describe(s) for s in clean] or ["Nothing clean to mark: no session finished unseen."]
    said, entries = [], found["sessions"] + found["jobs"]
    for given in ids:
        want = given.strip().lower()
        hits = [e for e in entries if e["id"].lower().startswith(want)
                or any(r["id"].lower().startswith(want) for r in e.get("runs", []))] if want else []
        if len(hits) != 1:
            said.append("Not marked: %s matches %d finished session(s); run `finished` for the list."
                        % (given, len(hits)))
            continue
        remember(ledger, hits[0].get("runs") or hits)
        said.append("Reviewed: " + describe(hits[0]))
    return said


def print_finished(ledger, hours=None, reviewed=None, me=""):
    if not os.path.isfile(ledger):
        raise SystemExit("no ledger at %s" % ledger)
    if reviewed is not None:
        print("\n".join(mark_reviewed(ledger, reviewed, me)))
        return 0
    found = scan(ledger, me, hours)
    entries = found["sessions"] + found["jobs"]
    for entry in entries:
        print(describe(entry))
    print("Finished on their own: %d (%d with a loose end)" % (
        len(entries), sum(1 for e in entries if e["why"])) if entries else "Nothing finished unseen.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Sessions that ended on their own, with nobody managing them.")
    p.add_argument("--ledger", required=True, help="the guide ledger")
    p.add_argument("--hours", type=float, default=None,
                   help="how far back (default SESSION_GUIDE_FINISHED_HOURS or 24)")
    p.add_argument("--reviewed", nargs="*", metavar="ID", default=None,
                   help="mark as looked at: every clean finish, or the listed sessions")
    args = p.parse_args(argv)
    return print_finished(os.path.expanduser(args.ledger), args.hours, args.reviewed,
                          os.environ.get("CLAUDE_CODE_SESSION_ID", ""))


if __name__ == "__main__":
    sys.exit(main())
