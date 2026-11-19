#!/usr/bin/env python3
"""guide_claims: merges and commands someone said they would do, tracked in the ledger until there is evidence.

    python3 guide_claims.py claim merge <#N | N | PR link> [--repo owner/name] [--by <who>] [--ledger <path>]
    python3 guide_claims.py claim run "<command>" --by <who> [--ledger <path>]
    python3 guide_claims.py claim done <key | #N> "<evidence>" [--ledger <path>]
    python3 guide_claims.py claim list [--all] [--days 3] [--ledger <path>]

The same commands run as `guide_title.py claim …` once that script mounts this one (add_parser / cmd_claim).
Without --ledger they use the guide's ledger (the one in this session's guide marker).

A claim is a row in the ledger's `## Claims` table:

    | Claim [key] | What | By | Claimed | Evidence |
    |---|---|---|---|---|
    | merge [5c2e1a] | acme/widgets#12 | the user | 2026-11-19 14:05 | — |
    | run [9f0b3d] | `make backfill-orders` | Dana | 2026-11-19 14:10 | done 2026-11-19 15:02: 4,210 rows, log in #ops |

The first cell is the kind and a key of 6 hex characters made from the PR (repo and number) or the command, like an
owed question's key in the waiting table, so the same PR or command always gives the same row. Claimed is local time
(YYYY-MM-DD HH:MM). Evidence is `—` while the claim is open, then "done <time>: <evidence>" (`claim done`) or
"merged <mergedAt> (gh, checked <time>)" when gh says the PR is merged. Closed rows stay, like Verifications rows.

hook_lines(ledger) is what the guide's hook prints on every prompt:
- every open merge claim, re-checked with guide_gh.pr_state (gh, cached 10 minutes, 5 s timeout, fails open). A merged
  PR closes its own claim with the evidence and the hook says so once; an open, closed-unmerged or unchecked one stays
  listed until it is merged or `claim done`;
- every run claim with no evidence after SESSION_GUIDE_CLAIM_HOURS (default 4) hours;
- one line counting the ledger lines from the last SESSION_GUIDE_CLAIM_DAYS (default 3; 0 = the whole ledger) days
  that ask for a merge or a command and have no claim row (unclaimed()).

unclaimed(ledger) finds lines that say "MERGE READY #N", "<someone> runs / tells …" or hold a `! command`, with no
claim row for that PR or command. A dated line counts by its own date; a bullet with none takes the date above it.

Python 3 stdlib only.
"""
import argparse
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SECTION = "## Claims"
TABLE = ["| Claim [key] | What | By | Claimed | Evidence |\n", "|---|---|---|---|---|\n"]
KINDS = ("merge", "run")
OPEN = "—"  # the Evidence cell of an open claim
RUN_HOURS = 4  # a run claim with no evidence this long is listed (SESSION_GUIDE_CLAIM_HOURS)
CLAIM_DAYS = 3  # how far back unclaimed() looks for the hook (SESSION_GUIDE_CLAIM_DAYS, 0 = the whole ledger)
BEFORE = ("## Open items", "## Verifications", "## Log")  # where a new Claims section goes
USER = "the user"

PR = re.compile(r"(?:github\.com/([\w.-]+/[\w.-]+)/pull/|(?<![\w/#])(?:([\w.-]+/[\w.-]+))?#)(\d{1,6})\b")
MERGE_READY = re.compile(r"\bMERGE[ -]READY\b[^#\n]{0,80}?(?:([\w.-]+/[\w.-]+))?#(\d{1,6})\b"
                         r"(?:\s*\(([\w.-]+/[\w.-]+)\))?", re.I)
# Someone asked to run or tell: "the user runs …", "Dana tells …", "ask Dana to run …". Capitalized words that are not
# people ("CI runs nightly") are left out.
ASKED = re.compile(r"\b(?:(?:the )?user|you|[A-Z][a-z]+)\s+(?:runs|will run|should run|to run|tells|will tell|to tell)\b"
                   r"|\bask(?:ed|s)?\s+(?:the user|[A-Z][a-z]+)\s+to\s+(?:run|tell)\b")
NOT_PEOPLE = {"CI", "It", "This", "That", "Which", "What", "Who", "Guide", "Worker", "Workers", "Lead", "Session",
              "Sessions", "Script", "Hook", "Job", "Cron", "Audit", "Deploy", "Test", "Tests", "Pipeline", "Build",
              "Battery", "Check", "Migration", "Task", "Agent", "Helper", "Then", "Next", "Also", "Nobody", "Nothing"}
BANG = re.compile(r"`!\s?([^`]+)`|(?:^|(?<=[\s(]))!\s?([a-z.~/$][^|`\n]*)")


def title_module():
    """guide_title, which this script builds on. When guide_title runs as the main script and has mounted this one, it
    registers itself as `guide_title` first (as it does for guide_audit), so no second copy is loaded."""
    mod = sys.modules.get("guide_title")
    if mod is None:
        main = sys.modules.get("__main__")
        if main is not None and os.path.basename(getattr(main, "__file__", "") or "") == "guide_title.py":
            mod = main
        else:
            if HERE not in sys.path:
                sys.path.insert(0, HERE)
            import guide_title as mod
        sys.modules.setdefault("guide_title", mod)
    return mod


def gh_module():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import guide_gh
    return guide_gh


def env_number(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def read_lines(ledger):
    with open(ledger, errors="replace") as f:
        return f.read().splitlines(True)


def stamp(now=None):
    return time.strftime(title_module().TIME_FORMAT, time.localtime(time.time() if now is None else now))


def norm(text):
    return " ".join((text or "").split())


def merge_key(number, repo=None):
    return title_module().owed_key("merge %s#%d" % ((repo or "").lower(), int(number)))


def run_key(command):
    return title_module().owed_key("run " + norm(command))


def parse_pr(text, repo=None):
    """(repo or None, number) from "#12", "12", "acme/widgets#12" or a PR link; repo from --repo wins. None if none."""
    text = (text or "").strip()
    if text.isdigit():
        return (repo or None, int(text))
    found = PR.search(text)
    if not found:
        return None
    return (repo or found.group(1) or found.group(2) or None, int(found.group(3)))


def what_of_merge(repo, number):
    return "%s#%d" % (repo or "", number)


def claim_rows(ledger):
    """{key: {key, kind, what, by, claimed, evidence, open, repo, number, command}} from the ledger's Claims table."""
    gt = title_module()
    found, inside = {}, False
    for line in read_lines(ledger):
        if line.startswith("## "):
            inside = line.startswith(SECTION)
        elif inside and line.lstrip().startswith("|"):
            cells = gt.split_row(line)
            key = gt.row_id(cells[0]) if cells else None
            kind = (re.match(r"[a-z]*", cells[0].lower()).group() if cells else "")
            if not key or len(cells) < 5 or kind not in KINDS:
                continue
            what = cells[1].replace("\\|", "|")
            evidence = cells[4].replace("\\|", "|")
            row = dict(key=key, kind=kind, what=what, by=cells[2], claimed=cells[3], evidence=evidence,
                       open=evidence.strip() in ("", OPEN, "-"), repo=None, number=None, command=None)
            if kind == "merge":
                pr = parse_pr(what)
                if pr:
                    row["repo"], row["number"] = pr
            else:
                row["command"] = what.strip().strip("`").strip()
            found[key] = row
    return found


def write_claim(ledger, key, cells):
    gt = title_module()
    return gt.write_row(ledger, SECTION, SECTION, TABLE, lambda c: gt.row_id(c[0]), key, cells, before=BEFORE)


def row_cells(row, evidence=None):
    return ["%s [%s]" % (row["kind"], row["key"]), row["what"], row["by"], row["claimed"],
            row["evidence"] if evidence is None else evidence]


def add_merge(ledger, pr, repo=None, by=USER, now=None):
    """Claim (or re-claim) a merge; returns its row. A re-claim keeps the first Claimed time and reopens the row."""
    parsed = parse_pr(str(pr), repo)
    if not parsed:
        raise SystemExit("say which PR: #N, N, owner/name#N or its link")
    repo, number = parsed
    key = merge_key(number, repo)
    old = claim_rows(ledger).get(key)
    row = dict(key=key, kind="merge", what=what_of_merge(repo, number), by=norm(by) or USER,
               claimed=old["claimed"] if old else stamp(now), evidence=OPEN)
    write_claim(ledger, key, row_cells(row))
    return dict(row, repo=repo, number=number, open=True, old=old)


def add_run(ledger, command, by, now=None):
    command = norm(command).strip("`").strip()
    if command.startswith("!"):
        command = command[1:].strip()
    if not command:
        raise SystemExit("say which command, exactly as it is to be run")
    if not norm(by):
        raise SystemExit("say who runs it: --by <who>")
    key = run_key(command)
    old = claim_rows(ledger).get(key)
    row = dict(key=key, kind="run", what="`%s`" % command.replace("`", "'"), by=norm(by),
               claimed=old["claimed"] if old else stamp(now), evidence=OPEN)
    write_claim(ledger, key, row_cells(row))
    return dict(row, command=command, open=True, old=old)


def find_claim(rows, given):
    """The row `given` names: its key (or a unique key prefix of 3+), "#N" / owner/name#N for a merge claim, or the
    exact command of a run claim. Raises SystemExit when it names none or several."""
    want = (given or "").strip().strip("[]")
    if want.lower() in rows:
        return rows[want.lower()]
    hits = [r for k, r in rows.items() if len(want) >= 3 and k.startswith(want.lower())]
    pr = None if hits else parse_pr(want) if (want.startswith("#") or "#" in want or "/pull/" in want) else None
    if pr:
        hits = [r for r in rows.values() if r["kind"] == "merge" and r["number"] == pr[1]
                and (not pr[0] or not r["repo"] or pr[0].lower() == r["repo"].lower())]
    if not hits and not pr:
        command = norm(want).lstrip("!").strip().strip("`").lower()
        hits = [r for r in rows.values() if r["kind"] == "run" and norm(r["command"]).lower() == command]
    if len(hits) != 1:
        raise SystemExit("%r names %s claim" % (given, "no" if not hits else "more than one") +
                         ("" if not hits else ": " + ", ".join(sorted(r["key"] for r in hits))))
    return hits[0]


def close_claim(ledger, given, evidence, now=None):
    evidence = norm(evidence)
    if not evidence:
        raise SystemExit("say what shows it happened: a merge sha, the command's output, a link")
    row = find_claim(claim_rows(ledger), given)
    text = "done %s: %s" % (stamp(now), evidence)
    write_claim(ledger, row["key"], row_cells(row, text))
    return dict(row, evidence=text, open=False)


def describe(row):
    if row["kind"] == "merge":
        thing = "merge PR #%s%s" % (row["number"], " (%s)" % row["repo"] if row["repo"] else "")
    else:
        thing = "run `%s`" % row["command"]
    return "[%s] %s, asked of %s at %s" % (row["key"], thing, row["by"], row["claimed"])


def check(ledger, now=None, cache=None):
    """Every open claim with its status: merge claims are re-checked with gh, and a merged PR's claim is closed here
    with gh's evidence. [dict(row, status=…, pr=gh answer or None)]; status is `merged` (closed just now), `open`,
    `closed` (closed without merging), `unknown` (gh off or failed) for merges, `stale` or `fresh` for runs."""
    now = time.time() if now is None else now
    hours = env_number("SESSION_GUIDE_CLAIM_HOURS", RUN_HOURS)
    gt, out = title_module(), []
    for row in claim_rows(ledger).values():
        if not row["open"]:
            continue
        if row["kind"] == "run":
            at = gt.read_time(row["claimed"])
            out.append(dict(row, status="stale" if now - at >= hours * 3600 else "fresh", pr=None, hours=hours))
            continue
        if row["number"] is None:
            out.append(dict(row, status="unknown", pr=None))
            continue
        pr = gh_module().pr_state(row["number"], row["repo"], cache=cache, now=now)
        status = "unknown" if not pr else {"MERGED": "merged", "CLOSED": "closed"}.get(pr["state"], "open")
        if status == "merged":
            text = "merged %s (gh, checked %s)" % (pr.get("mergedAt") or "", stamp(now))
            write_claim(ledger, row["key"], row_cells(row, " ".join(text.split())))
        out.append(dict(row, status=status, pr=pr))
    return out


def describe_check(row):
    key, what = row["key"], describe(row)
    if row["status"] == "merged":
        return "Claim closed: %s: gh says it is merged (%s); the claim is done." % (
            what, row["pr"].get("mergedAt") or "no time given")
    if row["status"] == "open":
        return ("Claim: %s: still OPEN on GitHub. Check with %s, or `claim done %s \"<evidence>\"` if it is settled "
                "another way." % (what, row["by"], key))
    if row["status"] == "closed":
        return ("Claim: %s: the PR was closed without merging. Find out why, then `claim done %s \"<what happened>\"`."
                % (what, key))
    if row["status"] == "unknown":
        return ("Claim: %s: not checked (gh off, missing or failing). Check it by hand, then `claim done %s "
                "\"<evidence>\"`." % (what, key))
    return ("Claim: %s: no evidence after %g h. Ask %s for the output, then `claim done %s \"<evidence>\"`."
            % (what, row["hours"], row["by"], key))


def unclaimed(ledger, days=None, now=None):
    """[{line, kind, ref, text}]: ledger lines that ask for a merge ("MERGE READY #N") or a command ("<someone> runs /
    tells …", a `! command`) with no claim row for that PR or command, one per PR or command (its newest line). A PR
    the ledger already says is merged or deployed, or that has a Verifications row, is left out. `days`
    (None or 0: the whole ledger) keeps lines dated in that window; undated lines then don't count. The Claims table
    itself is skipped, and so are struck lines."""
    gt = title_module()
    now = time.time() if now is None else now
    since = now - days * 86400 if days else None
    rows = list(claim_rows(ledger).values())
    merges = [(r["repo"], r["number"]) for r in rows if r["kind"] == "merge"]
    commands = [norm(r["command"]).lower() for r in rows if r["kind"] == "run" and r["command"]]
    keys = {r["key"] for r in rows}

    def merge_claimed(repo, number):
        return any(n == number and (not repo or not r or repo.lower() == r.lower()) for r, n in merges)

    def text_claimed(text, both=False):
        low = norm(text).lower()
        return (any(c and (c in low or both and low in c) for c in commands)
                or any("[%s]" % k in low for k in keys))

    try:  # a PR the ledger already says is merged or deployed, or that has a Verifications row, needs no claim
        landed = {h["key"] for h in gt.ledger_hits(ledger, 0, now)} | set(gt.verification_rows(ledger))
    except Exception:
        landed = set()

    found, skip, carried = {}, False, None
    for n, line in enumerate(read_lines(ledger), 1):
        if line.startswith("## "):
            skip, carried = line.startswith(SECTION), gt.line_date(line, now)
            continue
        body = line.strip()
        if skip or not body or body.lstrip("-*| ").startswith("~~"):
            continue
        own = gt.line_date(line, now)
        table = body.startswith("|")
        date = own if table else (own or carried)
        if own and not table:
            carried = own
        if since is not None and (date is None or date < since):
            continue
        text = norm(line.strip(" -*\n"))
        for m in MERGE_READY.finditer(line):
            repo, number = m.group(1) or m.group(3), int(m.group(2))
            if not merge_claimed(repo, number) and "#%d" % number not in landed:
                found[("merge", (repo or "").lower(), number)] = dict(
                    line=n, kind="merge", ref=what_of_merge(repo, number), text=text[:220])
        for m in BANG.finditer(line):
            command = norm(m.group(1) or m.group(2)).rstrip(".,;:)")
            if command and not text_claimed(command, both=True) and not text_claimed(text):
                found[("cmd", command.lower())] = dict(line=n, kind="cmd", ref=command, text=text[:220])
        for m in ASKED.finditer(line):
            who = re.match(r"(?:ask(?:ed|s)?\s+)?(\S+)", m.group()).group(1)
            if who in NOT_PEOPLE or BANG.search(line):
                continue
            if not text_claimed(text):
                found[("ask", text.lower())] = dict(line=n, kind="ask", ref=norm(m.group()), text=text[:220])
            break
    return sorted(found.values(), key=lambda u: u["line"])


def describe_unclaimed(u):
    what = {"merge": "merge " + u["ref"], "cmd": "command `%s`" % u["ref"], "ask": u["ref"]}[u["kind"]]
    return "L%d %s: %s" % (u["line"], what, u["text"])


def hook_lines(ledger, now=None, cache=None):
    """The lines the guide's hook prints about claims: open merge claims (gh re-checked; a merged one closes itself and
    is reported once), run claims with no evidence after SESSION_GUIDE_CLAIM_HOURS, and a count of unclaimed lines.
    [] on any error: the hook fails open."""
    try:
        lines = [describe_check(r) for r in check(ledger, now, cache) if r["status"] != "fresh"]
        days = env_number("SESSION_GUIDE_CLAIM_DAYS", CLAIM_DAYS)
        loose = unclaimed(ledger, days=days, now=now)
        if loose:
            lines.append("Unclaimed: %d ledger line%s %s ask for a merge or a command with no claim row (first: %s). "
                         "`guide_title.py claim list` shows them; claim each (`claim merge #N` / `claim run \"<cmd>\" "
                         "--by <who>`), then `claim done` the ones already done."
                         % (len(loose), "" if len(loose) == 1 else "s",
                            "from the last %g days" % days if days else "in the ledger", describe_unclaimed(loose[0])))
        return lines
    except Exception:
        return []


def ledger_of(args):
    path = getattr(args, "ledger", None)
    return os.path.expanduser(path) if path else title_module().require_ledger()


def cmd_claim(args):
    ledger = ledger_of(args)
    if not os.path.isfile(ledger):
        raise SystemExit("no ledger at %s" % ledger)
    sub = args.claim_cmd
    if sub == "merge":
        row = add_merge(ledger, args.pr, args.repo, args.by)
        print("claim [%s]: merge PR #%d%s, asked of %s at %s%s. The hook re-checks it with gh until it is merged; "
              "`claim done %s \"<evidence>\"` closes it by hand."
              % (row["key"], row["number"], " (%s)" % row["repo"] if row["repo"] else "", row["by"], row["claimed"],
                 " (reopened)" if row["old"] and not row["old"]["open"] else "", row["key"]))
    elif sub == "run":
        row = add_run(ledger, args.command, args.by)
        print("claim [%s]: %s runs `%s`, claimed %s. The hook lists it after %g h with no evidence; `claim done %s "
              "\"<output or link>\"` closes it." % (row["key"], row["by"], row["command"], row["claimed"],
                                                   env_number("SESSION_GUIDE_CLAIM_HOURS", RUN_HOURS), row["key"]))
    elif sub == "done":
        row = close_claim(ledger, args.key, args.evidence)
        print("claim [%s] closed: %s" % (row["key"], row["evidence"]))
    else:
        checked = {r["key"]: r for r in check(ledger)}
        rows = claim_rows(ledger)
        shown = 0
        for row in rows.values():
            if row["key"] in checked and checked[row["key"]]["status"] != "fresh":
                print(describe_check(checked[row["key"]]))
            elif row["open"]:
                print("Claim: %s: open, no evidence yet." % describe(row))
            elif args.all:
                print("Closed: %s: %s" % (describe(row), row["evidence"]))
            else:
                continue
            shown += 1
        loose = unclaimed(ledger, days=args.days, now=None)
        for u in loose:
            print("Unclaimed: " + describe_unclaimed(u))
        still = sum(1 for r in claim_rows(ledger).values() if r["open"])
        print("%d open claim%s, %d closed, %d unclaimed line%s%s"
              % (still, "" if still == 1 else "s", len(rows) - still, len(loose), "" if len(loose) == 1 else "s",
                 " (last %g days)" % args.days if args.days else ""))
    return 0


def add_parser(subparsers):
    """Mount `claim merge | run | done | list` on an argparse subparsers object (guide_title.py's, or this script's)."""
    claim = subparsers.add_parser("claim", help="a merge or command someone said they would do, tracked until there "
                                                "is evidence")
    sub = claim.add_subparsers(dest="claim_cmd", required=True)
    merge = sub.add_parser("merge", help="someone (default: the user) was asked to merge a PR; gh closes it once merged")
    merge.add_argument("pr", help="#N, N, owner/name#N or the PR link")
    merge.add_argument("--repo", help="owner/name (default: the link's, else the current directory's repository)")
    merge.add_argument("--by", default=USER, help="who merges it (default: %(default)s)")
    run = sub.add_parser("run", help="someone was asked to run a command; listed after %g h with no evidence" % RUN_HOURS)
    run.add_argument("command", help="the command, exactly as given to them")
    run.add_argument("--by", required=True, help="who runs it: the user, a person's name, or a session 'title [id6]'")
    done = sub.add_parser("done", help="close a claim with its evidence")
    done.add_argument("key", help="the claim's key, #N for a merge claim, or the exact command")
    done.add_argument("evidence", help="what shows it happened: a merge sha, the output, a link")
    show = sub.add_parser("list", help="open claims (merges re-checked with gh) and unclaimed ledger lines")
    show.add_argument("--all", action="store_true", help="closed claims too")
    show.add_argument("--days", type=float, default=CLAIM_DAYS,
                      help="unclaimed lines from this many days back (default %(default)s; 0 = the whole ledger)")
    for parser in (merge, run, done, show):
        parser.add_argument("--ledger", help="the ledger (default: the guide's)")
    return claim


def main(argv=None):
    p = argparse.ArgumentParser(description="Track merges and commands someone said they would do.")
    sub = p.add_subparsers(dest="cmd", required=True)
    add_parser(sub)
    args = p.parse_args(argv)
    return cmd_claim(args)


if __name__ == "__main__":
    sys.exit(main())
