<p align="center"><img src="docs/icon-256.png" width="96" alt=""></p>

# session-guide

One Claude Code session that keeps your parallel sessions, and you, on the same page. When three features are moving
toward production in five background sessions at once, session-guide turns one more session into the **guide**. It
reads what every worker last said, routes each worker's questions to you as one interview, relays your rulings back,
wakes itself while CI and deploys run, and tells you exactly which session needs you, and for what.

[![test](https://github.com/jachai/jethro/actions/workflows/test.yml/badge.svg)](https://github.com/jachai/jethro/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/jachai/jethro/blob/main/LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-d97757)

A typical answer when you ask the guide "what's next?":

```
**Needs you now**
1. Merge #142 (green, mergeable, no deploy running) — https://github.com/you/app/pull/142
2. 'search reindex worker' [b5c6d7]: one refund rule to decide (below)

**Results for you**
- Pricing deck, slide 4: https://claude.ai/artifact/abc123 — the new margin table renders, checked by 'deck lead' [7a8b9c]
- Billing export review: https://claude.ai/artifact/def456 — 3 findings, asked 13:05, no verdict yet

**Streams**
- Billing export: develop copy green → next: your merge, then the staging gate ('billing export lead' [3fa9c1])
- Search reindex: on staging → next: backfill after the refund rule ('search reindex worker' [b5c6d7])
- Docs refresh: DONE (deploy job green 11:47Z)

**Proposed actions**
1. Start a new session 'billing rounding fix' for the 0.01 rounding on split invoices the billing lead left
   out of scope: yes/no?
2. 'search reindex worker' [b5c6d7] runs the read-only prod audit after the backfill: yes/no?

**Running on its own**
- billing CI on main, next check ~14:20

Decision pending: refund the 5.00 restocking fee on a store-at-fault partial return?
```

## Why

Long multi-session efforts break down in predictable ways. Each of these happened in real use before session-guide
had a rule for it:

| What went wrong | What session-guide does |
|---|---|
| You answer a worker one way and the guide another. The worker builds the wrong one. | Workers never ask you directly. Every decision goes through the guide, is logged as **Decision N FINAL**, and is relayed verbatim. If you do answer a worker directly, the guide checks that answer against earlier decisions first. |
| Each fresh guide re-reads a growing pile of notes and gives advice from a stale picture. | One **ledger** per effort, rewritten in place and kept under ~6 KB. A new guide reads it and nothing older. |
| Status files lag. You get sent to answer a question you already answered. | Before every "what's next", `peek.py` reads the workers' own transcripts: last reply, unanswered questions, context size. |
| Two guides are running and give you conflicting advice. | Sole-guide check at start: the guide asks you which one stays and retires the other (faded red title, state done). |
| "be0f7c41 is waiting on you." Which one is that? | Sessions are always named by title, with the id in brackets. |
| The guide sits idle while a deploy finishes, or wakes every 10 minutes all night. | +5 min wakeups for imminent events and +10 for long runs. When only you can unblock things, it backs off to +30 and +60, then stops. |
| A guide runs out of context mid-relay. | It prints its own context size in every status reply and hands off at 120k: ledger current, wakeups cancelled, a one-line prompt for the next guide. |
| A worker's report says "not fixed, out of scope". Nobody picks it up, and the guide lists it as "open, whenever you want". | After every report the guide adds each loose end to an Open items table with an owner: a session, a new session it proposes, or you. Owner-less items go into the next interview, at most 4 at a time, each as a recommended owner + action you answer yes or no. |
| A worker hands off, gets blocked or finishes, and the guide doesn't notice until you ask. | Every guide prompt reconciles the ledger against the sessions' real job state: a worker that ended more than 3 minutes ago and still needs the guide is listed until the guide acts. A handoff means the successor starts now, without asking you. |
| A worker's report goes to a guide's title, or into its final message, and nobody reads it. | The worker contract sends every HANDED OFF, BLOCKED, DONE and MERGE READY by SendMessage to the guide's `uds:` socket, never a title, and a guide change never suspends that. A failed send goes to an inbox file next to the ledger, which the guide's next prompt lists. |
| The guide hands off with a worker's handoff still unanswered. | `retire` is a gate: it refuses while a row needs a guide, unless `--force` writes those rows into the ledger for the next guide. A retired guide is told on every prompt to forward, not act. |
| You get asked about work that was finished days ago. | Before a row is put to you, the audit looks for later evidence (a satisfied result, a DONE session, a merged PR). "Likely done" rows go to a daily read-only strike sweep, and you hear one line, not fourteen questions. |
| A merge or a command handed to you is never checked again. | Every merge or command asked of someone is a claim. The hook re-checks merge claims with `gh` and closes them when merged, and lists commands with no evidence after 4 hours. |
| New sessions pile up unclassified, and finished ones sit "waiting" forever. | Every prompt sweeps sessions active in the last 12 h, and the guide keeps interviewing you until each new one is managed, watched, left active or ignored. Finished or obsolete workers are closed: ✅ title, `result:` line, state done, or a `! claude stop` for you when they are stuck. |

## Install

As a Claude Code plugin:

```
/plugin marketplace add jachai/jethro
/plugin install session-guide@jethro
```

session-guide is part of the [jethro](../../README.md) suite. Installed it earlier as
`session-guide@session-guide`, or with `install.sh`? Remove that first (`/plugin uninstall
session-guide@session-guide`, or `./install.sh --uninstall` from the old clone), then install
`session-guide@jethro`: with two copies enabled, Claude Code drops one copy's hooks.

Or as a plain skill, without the plugin system (deprecated: use the plugin; `install.sh` stays so
`./install.sh --uninstall` keeps working):

```sh
git clone https://github.com/jachai/jethro
cd jethro/plugins/session-guide && ./install.sh          # copies the skill to ~/.claude/skills (--link to symlink instead)
```

You need Claude Code with background sessions and cross-session messaging (`SendMessage`, `ListAgents`), and Python
3.9+ for the transcript reader. There are no dependencies. [claude-top](https://github.com/jachai/claude-top) is
optional but makes the session list nicer.

## Use

In the session you want as the guide:

```
/session-guide
```

(`/session-guide:session-guide` when installed as a plugin.) Tell it what the streams are: "guide me through
releasing billing export, search reindex and the docs refresh". It creates the ledger, finds the live sessions,
classifies them, and answers in the shape above.

In each worker you want managed:

```
/session-guide join
```

The worker finds the live guide, adopts the [worker contract](skills/session-guide/references/worker-contract.md)
and registers. From then on it reports at step boundaries and sends its questions to the guide. `/session-guide
leave` opts it back out. Sessions the guide starts itself are managed automatically.

| Level | How a session gets it | What the guide does |
|---|---|---|
| **MANAGED** | `/session-guide join`, or started by the guide | Sends the contract, relays rulings and approvals, takes its questions. Its title starts with "🟧🟧 (g) " |
| **WATCHED** | You picked Watch in the interview | Reads it for status. Its only message from the guide is your answer to a question it asked. Its title starts with "⬜⬜ " |
| **ACTIVE** | Any other running session, and every new one until you answer | Keeps its row only: no reading, no messages. Its title starts with "🟦🟦 " |
| **IGNORED** | You said so | Leaves it alone |
| **RETIRED** | A guide that handed over to a new one | Nothing: faded red title, state done |
| **DONE** | A MANAGED session the guide closed (finished or obsolete) | Nothing: "✅ " title, state done |

Other commands: `/session-guide handoff` makes the guide hand off now. Say "take over as guide, ledger: <path>" in a
fresh session to continue.

## Titles

One color per kind of session, so the agents view reads at a glance:

| Title | Session |
|---|---|
| `🟥🟥 Sessions Manager · release-guide (2 managed · 1 watched · 3 active · 1 new) 🟥🟥` | The active guide |
| `🎟️🎟️ Sessions Manager (retired) 🎟️🎟️` | A retired guide |
| `⬜⬜ design spike · Reading the diff` | WATCHED: the guide reads it but doesn't manage it |
| `🟦🟦 notes cleanup · Tidying the index` | ACTIVE: running, neither managed nor watched |
| `🟧🟧 (g) billing export lead · Waiting on CI` | MANAGED: guided, you don't need to go in |
| `✅ search reindex lead · PR merged` | Closed by the guide |

Unicode has no pale red square, so the retired guide's 🎟️ is the closest match, a dusty pink-red block. Its look
varies by platform; override it with `SESSION_GUIDE_RETIRED_TITLE`.

### The guide's pinned title

The guide keeps one title, so you can always find it in the agents view:

```
🟥🟥 Sessions Manager · release-guide (2 managed · 1 watched · 3 active · 1 new · 15 idle 4d) 🟥🟥
```

`release-guide` is the ledger's slug (its folder name), so two guides, say one per machine over Remote Control, read
apart. managed, watched and active count the ledger's rows at those levels. new is the count of sessions active in the
last 12 h that have no ledger row yet, counted live on every prompt. "15 idle 4d" appears when the audit (below) finds
decided work with no worker: how many items, and the oldest one's age. At start the
guide runs
`scripts/guide_title.py mark <ledger>`. A `UserPromptSubmit` and `SessionStart` hook then re-applies the title on
every prompt, with fresh counts, so a rename (by hand or by another titling hook) lasts one turn at most. Every other
session is left alone: the hook prints nothing for it, and it prints nothing on any error too.

When a new guide takes over, the old one is retired with `guide_title.py retire <id>`. Its title turns to
`🎟️🎟️ Sessions Manager (retired) 🎟️🎟️` and never goes red again, and it ends with a `result:` line so its state shows
done rather than waiting on you. From then on its hook tells it on every prompt that it is retired: forward any worker
message to the new guide's socket, and do nothing else. `retire` refuses (exit 1) while reconcile lists a row that
needs a guide; `--check` only runs that gate, and `--force` retires anyway and writes the rows into the ledger's
`## Handoff` table for the next guide. It also prints the one line the guide sends its workers: "Guide changing. Keep
sending to this socket; the old guide forwards until the new one introduces itself."

A finished or obsolete worker is **closed** the same way: `guide_title.py done <id>` swaps its `🟧🟧 (g) ` for `✅ ` (at once when the session has ended, on its next prompt otherwise), the
guide asks it for a final `result:` line, and checks its state turned done. If the session is stuck on a question or
a guard prompt, the guide hands you `! claude stop <id>` instead.

### Guided and watched sessions

Every MANAGED session's title starts with `🟧🟧 (g) `, for example `🟧🟧 (g) billing export lead · Waiting on CI`. Those are
the sessions you don't need to go into; a session without it may need you. `/session-guide join` and the guide run
`guide_title.py guided <id>`, and the same hook puts the prefix in front of the session's own title. It never doubles
up, it survives renames and focus updates, and it stays through DONE until the guide closes the session.
`guide_title.py unguided <id>` (on `/session-guide leave`, or when the guide reclassifies a session IGNORED) takes
it off. The guide and a retired guide never get it. Override the prefix with `SESSION_GUIDE_GUIDED_PREFIX`.

Every WATCHED session's title starts with `⬜⬜ `, from `guide_title.py watched <id>`, with the same behavior:
`guided` and `watched` swap one prefix for the other when a session changes level. Override it with
`SESSION_GUIDE_WATCHED_PREFIX`. ACTIVE works the same way with `guide_title.py active <id>` and
`SESSION_GUIDE_ACTIVE_PREFIX`.

- The plugin install registers the hook for you. A plain-skill install prints the `settings.json` snippet to add
  ([examples/settings-snippet.json](examples/settings-snippet.json)).
- If you use [session-titles](https://github.com/jachai/session-titles), the guide also runs
  `session-titles off <its id>` so the two hooks don't take turns. Guided and watched sessions keep session-titles on: its hook's title
  overrides this one, so `guide_title.py` also puts the prefix into its stored origin, and both give the same title.
- To use your own format, set `SESSION_GUIDE_TITLE`, for example `"guide {managed}/{watched}/{new}"`, in the `env`
  block of `settings.json` (`{tracked}` is managed + watched, `{slug}` the ledger's slug, `{host}` this machine's
  short host name). Running a guide on two machines? See [two guides on two machines](docs/other-machine-setup.md).
  Avoid `*`, because some title tools strip markdown, and
  keep it short, because the agents view and claude-top cut long names. claude-top spots a guide by its marker file
  and falls back to the `🟥🟥 Sessions Manager` start. The closed prefix is `SESSION_GUIDE_DONE_PREFIX`.

### Stream icons

One icon and one short name per stream (project), shared by every session that works on it, so you can tell at a glance
which project a session, a question or a status line is about. The icon goes right after the prefix: `🟧🟧 (g) 🏠 billing
lead`. It comes back after a rename and stays through DONE. A session on no stream keeps exactly the title it has today.

| Command (`guide_title.py …`) | What it does |
|---|---|
| `stream add <key> "<name>" [--icon 🏠]` | A new stream, or an ended one reopened; without `--icon` it gets a free icon |
| `stream rename <key> [--name …] [--icon …]` | A new name or icon, which reaches its sessions' titles |
| `stream list [--all]`, `stream suggest [n]` | The streams, their sessions, and the sessions on none; free icons |
| `stream assign <key> <id>… [--active-ok]` | Put sessions on a stream; your own sessions only with `--active-ok`, after your yes |
| `stream end <key>` | Finished; its icon is free again after 7 days |
| `stream strip <id>… \| --all` | Take the icon off titles |
| `stream table [--end-unlisted]` | Refresh the ledger's Streams table; mark rows of unregistered streams ended |
| `finished [--ledger] [--hours 24] [--reviewed [<id> ...]]` | Lists sessions that ended in the last 24 h at levels the guide doesn't manage; `--reviewed` marks them |
| `launch --stream <key>`, `launch --successor-of <id>` | Start a session on a stream, or on its predecessor's (a worker starts its own successor this way, with `--ledger <path>`) |

The registry is `streams.json` next to the ledger. An icon belongs to one open stream on this machine; when the icons run
out, a stream gets a two-letter tag such as `[TW]`. Icons are added when a row is shown, never stored in an Open items,
Results, owed-question or Owner cell, whose rows are matched by their text. `SESSION_GUIDE_STREAM_ICONS=0` turns every
icon off.

## What the guide will and won't do

The guide is **advisory**. It never branches, commits, pushes, merges or edits code: merges stay with you, and
building stays with the workers. It may:

- read transcripts, `ListAgents`, and CI/PR/deploy state;
- message managed workers and relay your approvals;
- start fresh worker sessions (`guide_title.py launch`, which runs `claude --bg`, marks the session guided the
  moment it starts and denies it `AskUserQuestion`) on the model and effort the task needs; a worker near its context
  limit starts its own successor the same way, and the guide records it;
- write the ledger.

Browser checks, test batteries on shared environments, and database and log checks go to a worker or to you.

## Nothing gets forgotten

Every session the guide manages or watches has to settle in one of two states, and the guide checks on every wake:

- **Waiting on you.** It is still relevant and only you can move it. The guide records the exact action and reminds you
  until it is done. Each reminder first checks that it still applies, then offers: done it, nothing more to do (close it),
  or sleep (2 hours by default, `SESSION_GUIDE_SLEEP_HOURS`; a period you name wins). Due reminders and result verdicts
  come as one "Tick what is settled" question; an unanswered reminder sleeps the default period.
- **Done.** It is finished, with no follow-ups on the session or its subject. It is closed with a ✅ title.

A session that has gone quiet for 2 hours in neither state is flagged to the guide on its next prompt, and stays flagged.

Quiet is the slow signal. The fast one is **reconcile**: on every guide prompt (and in `settle`, first in `mark`, and
in `retire`) it reads each MANAGED and WATCHED row's job state, and lists the ones whose job ended more than 3
minutes ago (`SESSION_GUIDE_GRACE_MINUTES`) and still need the guide: SUCCESSOR STARTED (a worker started its own
successor: record it), HANDED OFF with no successor started (start it now), BLOCKED with no Waiting row (answer it or ask you), ENDED any other way (record it and close it), UNDELIVERED
(its last report never reached the guide), and INBOX (a report a worker wrote next to the ledger because its send
failed). A line stays until the row changes. `guide_title.py reconcile --ledger <path>` prints the same for any
ledger and never writes.

```
$ python3 skills/session-guide/scripts/guide_title.py reconcile
HANDED OFF: 'reindex lead' [d4e5f6a1] ended 6 min ago and no Sessions row is its successor. Start the successor now from ~/work/reindex/HANDOFF.md; give it a row saying "successor of [d4e5f6]" and set this row's Level to HANDED OFF.
1 to reconcile
```

Reconcile reads the rows the guide manages or watches. The prompt you fired and forgot has no row, or an ACTIVE one,
so the guide also takes **one look at every session that ended on its own** in the last 24 hours: its result line, a
question it left open, and wording such as "not done", "follow-up", "blocked" or "refused". You get them in the status
under "Finished on their own", each once; a loose end becomes an open item or a question for you. Scheduled
`claude -p` runs show as one line per job, and only when a run failed or was refused. The guide never messages these
sessions.

```
$ python3 skills/session-guide/scripts/guide_title.py finished
LOOSE END 'export retry spike' [9c1d2e3f] (no row), ended 14:05: tests pass locally | why: asks: Should I open the PR?
clean 'docs typo sweep' [7a8b9c0d] (ACTIVE row), ended 13:40: DONE: 4 typos fixed | https://github.com/acme/billing/pull/151
Finished on their own: 2 (1 with a loose end)
$ python3 skills/session-guide/scripts/guide_title.py finished --reviewed
Reviewed: clean 'docs typo sweep' [7a8b9c0d] (ACTIVE row), ended 13:40: DONE: 4 typos fixed | https://github.com/acme/billing/pull/151
```

Merges and commands asked of someone are tracked the same way, as **claims** in the ledger: `guide_title.py claim
merge #142 --repo acme/billing` or `claim run "make backfill-exports" --by Dana`. On every guide prompt the hook
re-checks open merge claims with `gh pr view` (cached 10 minutes, at most 3 s for all of a prompt's gh calls, never
in the way when gh is missing; the repo comes from the claim or the ledger's `Scope:` line, never the current folder)
and closes the merged ones itself, lists commands with no evidence after 4 hours, and counts ledger lines that say
"MERGE READY #N" or hold a `!` command with no claim. `claim done <key> "<evidence>"` closes one by hand.
`guide_title.py settle <ledger>` shows the same list, plus what is due and what is asleep. Reminders are a one-shot wake in
the guide session, so they fire only while a guide is running; a new guide picks them up from the ledger.

A question the guide owes you later ("ask this afternoon") is a reminder too, written the moment the guide says it:
`guide_title.py waiting ask "<question>" --hours 3`. It is a dated row in the same table, so it survives a guide
handoff instead of living in the old guide's head.

## Decided work doesn't sit idle

Reminders only cover what someone remembered to write a reminder for. A fix you approved on Monday that no session
picked up has no reminder, so a guide that only works its reminders reports "nothing due" while the work sits. The
audit closes that gap. It is a script, so it runs whether or not the guide remembers to:

```console
$ python3 skills/session-guide/scripts/guide_audit.py audit
AUDIT 2026-10-27 14:26, last 5 days
| Key | Age | Kind | What | Why | Next action |
|---|---|---|---|---|---|
| d21531 | 6.1 d | unverified | #131 (prod): split invoices still round 0.01 off on 12 orders | broken | start a fix |
| 788e4f+5 | 4.1 d | idle | 6 approved rows of fix-queue.md with no worker: BIL-208, BIL-213, BIL-219, … | oldest of 6 | ask now: start a fix wave for them / keep waiting / drop |
| 19feab | 26 h | waiting | owed question: #142 merge gate, the export wave waits on it | asleep until 10-28 00:25 | re-ask, or build around it |
| 473b7d+3 | 3.0 d | person | 4 items wait on Dana with no reminder: #135, BIL-201, … | oldest of 4 | one interview question listing them, then `waiting ask` |
… and 9 more row(s) holding 41 item(s), lower value x age: `audit --limit 13`, or `--all` for every item
23 idle decided item(s) (oldest 4.1 d), 19 over 12 h with no question to the user; 7 unverified; 1 reminder(s) open over a day; …
```

It reads the ledger's tables, any queue files the ledger names on a `Queues:` line (a fix queue another session
appends to), and the last 5 days of the guide's sessions' transcripts, and lists what is **not done or not verified**:
approved items with no live worker, items waiting on a person nobody is asking, landings nobody verified, reminders
open for over a day, recent decisions nothing refers to, and sessions that ended without a clean `result:`. Rows are
ranked by value x age and rows that share one next action are collapsed, so the guide gets 10 rows, not 300.

- **A quiet wake works the table.** `settle` ends with it, and with nothing else due the guide proposes a start for
  each row instead of going back to sleep.
- **The title and the hook keep count.** The title shows the idle count and the oldest age; the hook nags the guide
  when an idle item is over 12 h old with no question to you (`SESSION_GUIDE_IDLE_HOURS`).
- **Takeover and handoff run it.** `guide_title.py mark` runs the full audit and prints the table; every run rewrites
  `STATE.md` next to the ledger, a few KB of live state that a new guide reads instead of a ledger log that has
  grown to a megabyte.
- **Every row can be cleared.** `guide_audit.py set <key> started --session <id>`, `asked`, `parked --hours N`,
  `done "<evidence>"` or `dropped "<why>"` records what was decided, so the same row isn't raised twice.
- **Already covered? comes first.** A row with later evidence in the ledger (a satisfied Results row naming its id, a
  DONE session whose brief names it, a closing decision, a verification, the same ask twice, `gh` saying the PR
  merged) becomes kind `check`: "likely done: … Confirm, then `set <key> done "<evidence>"`. Do not ask the user."
  It leaves the ask list. A row that stays on it says when it was checked and why it is still open.
- **A strike sweep, once a day.** The full audit writes `strike-candidates.md` next to the ledger; when the last sweep
  is over 24 h old the hook asks the guide for one read-only helper that returns `<key> | DONE / SUPERSEDED / OPEN |
  <evidence>` per row, and `guide_audit.py strike --from <file>` applies it. The guide strikes only what the helper
  confirmed and tells you in one line. What is really open comes to you once, as one batch grouped by stream, keep /
  start / drop per group (`audit --open-batch`).
- **Rows say what closes them.** An Open items row or a reminder can carry `closes: pr:#N`, `result:<artifact id>`,
  `ticket:<ID>` or `session:<id8>`; when that happens the audit closes the row itself and says so.
- **The clock is the script's.** Every guide prompt starts with "Now: <local time and zone>", and the audit flags
  ledger lines dated in the future: a guide's own guess of the time drifts.

## Results you asked for get a verdict

A finished deliverable you asked for (a doc, a deck or slide, a review, a report, a release, a PR ready for you) is not
done when the worker says so. Two things happen first:

- **Look before done.** The worker opens it the way you will, rendered and at the exact link, and confirms the change
  shows. A report without that is "delivered, unchecked", and the guide sends the worker back to look before you hear
  of it.
- **Results for you.** Every status reply leads with what finished since the last one, each with its link, under a
  "Results for you" heading right after your own actions and before the streams. Each one is a question in the
  interview: tick Satisfied in one "Tick what is settled" question, or write "change <deliverable>: <what>" or drop it.
  Unticked is "haven't looked yet", asked again with no second question on the row's last cadence (hourly by default;
  `--every` when you name one). The stream isn't DONE, and its loose ends aren't closed, until you answer; the worker
  session may close in the meantime, the ledger row waits.

```
$ python3 skills/session-guide/scripts/guide_title.py result "pricing deck, slide 4" https://claude.ai/artifact/abc123 --from "deck lead [7a8b9c]"
$ python3 skills/session-guide/scripts/guide_title.py result-answer "pricing deck" not-looked --every 2
$ python3 skills/session-guide/scripts/guide_title.py result-answer "pricing deck" change --note "bigger font"
```

## Shipped isn't verified

About once a day the guide looks back over recent work for fixes and deployments that reached production or staging
(merged PRs, "ON PROD" and deploy lines in its ledger, and reports in the sessions' transcripts) with no verification
recorded, and proposes a follow-up for each in its interview:

> Start 'verify #142' to check the refund fee fix on prod? It reads the merged diff, states what should happen now (a
> store-fault return of 200.00 on a 600.00 order refunds 200.00 with the 15.00 fee waived), then counts refunds since the
> 11:17Z deploy in the read-only prod DB and searches the logs for errors on that path. (yes recommended)

A yes starts a read-only session from the [verify follow-up brief](skills/session-guide/references/verify-followup.md):
it reviews the merged code and the intended behaviour, states the expected behaviour with numbers, checks real data
(read-only queries, aggregates and ids) and the logs since the deploy, and reports **verified**, **not exercised yet**
(no traffic; the guide re-checks a day later) or **broken** (a fix goes first in the next interview), with evidence and
any new loose ends. The brief names tools by role ("your read-only prod DB tool", "your log search tool"); name your real
ones in `local.md`.

```
$ python3 skills/session-guide/scripts/guide_title.py followups
Follow-up: #142 on prod, seen 10-27 (ledger; 'refund fix lead' [3fa9c1]): 10-27 11:47 #142 ON PROD @a1b2c3d.
1 to propose, 0 to re-check; last review 2026-10-26 14:55; next review 2026-10-27 14:55
$ python3 skills/session-guide/scripts/guide_title.py verification "#142 refund fee fix" running "'verify #142' [9a8b7c]"
```

Results live in the ledger's Verifications table. `SESSION_GUIDE_FOLLOWUP_HOURS` sets the cadence (default 24; 0 turns
it off).

## The right model for each session

The guide picks a model and an effort for every session it starts, from a short
[table](skills/session-guide/references/model-choice.md) keyed on what the session does next: money and business-rule
fixes, release gates and design reviews get the top model at high effort; mechanical edits, CI reads, read-only data
checks and status reports get `sonnet` at low; verify follow-ups get `sonnet` at medium. It passes them as
`guide_title.py launch -- --model <alias> --effort <level>`, with aliases (`opus`, `sonnet`, `haiku`) so the table stays current, and
records the pick in the ledger. A worker's successor, which the worker starts itself, is picked again for its own next
step, not copied.

For a session it didn't start, the guide reads what it runs (claude-top's MODEL and EFFORT, or peek's first line) and,
when that doesn't fit the task, asks you:

> 'billing CI watcher' [3fa9c1] runs opus/high on CI reads and status reports; switch to sonnet/low? Open it from
> `claude agents` and type `/model sonnet`, then `/effort low`, in its window. (switch recommended)

It can't switch another session itself. Name a different top model (for example `fable`) in `local.md`.

## The ledger

`~/.claude/session-guide/<slug>/ledger.md` holds Streams, Order/gates, Sessions, Decisions (numbered, FINAL unless
struck), Results for you (each finished deliverable, its link and your verdict), Waiting on you (a table with the action and when to remind you, owed questions included), Claims (merges and commands someone was asked to do, until there is evidence), Open items (a table: Item | Owner | Next action | Status, where every row has an owner or
ASK), Verifications (each follow-up check and its verdict), and a 15-line log. After a forced guide handoff it also
has a Handoff table of the rows the old guide left open. Next to it the scripts keep `STATE.md`, `audit.json`,
`strike-candidates.md` and an `inbox/` folder for worker reports whose send failed. See the
[template](skills/session-guide/references/ledger-template.md). It's plain Markdown, so you can read and edit it
yourself.

## Make it yours

- **`~/.claude/session-guide/local.md`**: rules that override the skill where they conflict, such as your name, your
  cost-guard phrase, or "never defer work for usage limits without asking". It's read first in every mode.
- **`~/.claude/session-guide/playbooks/*.md`**: your release gates, commands and URLs. The guide loads the one that
  fits when a stream heads to staging or production, falling back to the
  [example playbook](skills/session-guide/references/release-playbook.md).

### Environment variables

Set them in the `env` block of `settings.json`, so the hooks see them too.

| Variable | Default | What it does |
|---|---|---|
| `SESSION_GUIDE_TITLE` | `🟥🟥 Sessions Manager · {slug} (…) 🟥🟥` | The guide's title format (see Titles) |
| `SESSION_GUIDE_RETIRED_TITLE` | `🎟️🎟️ Sessions Manager (retired) 🎟️🎟️` | A retired guide's title |
| `SESSION_GUIDE_GUIDED_PREFIX`, `_WATCHED_PREFIX`, `_ACTIVE_PREFIX`, `_DONE_PREFIX` | `🟧🟧 (g) `, `⬜⬜ `, `🟦🟦 `, `✅ ` | The title prefixes |
| `SESSION_GUIDE_STREAM_ICONS` | on | `0` turns every stream icon off (titles, hook lines, `STATE.md`); `stream strip --all` takes the ones already shown off |
| `SESSION_GUIDE_NEW_SESSION_MINUTES` | 15 | A session with no row this long gets its default level (MANAGED if guided, WATCHED if watched, else ACTIVE) with no question; 0 asks as before |
| `SESSION_GUIDE_SLEEP_HOURS` | 2 | The default snooze for `sleep <id>` and `sleep --due` |
| `SESSION_GUIDE_FINISHED_HOURS` | 24 | How far back the guide looks for sessions that ended with nobody managing them ("Finished on their own"); 0 turns the look off |
| `SESSION_GUIDE_FINISHED_QUIET_MINUTES` | 15 | An ended session is left alone this long before that look, so a conversation you are in the middle of is not listed |
| `SESSION_GUIDE_GRACE_MINUTES` | 3 | How long after a worker's job ends before reconcile lists it |
| `SESSION_GUIDE_IDLE_HOURS` | 12 | An idle decided item older than this, with no question to you, is nagged about |
| `SESSION_GUIDE_AUDIT_HOURS` | 12 | How often the full audit is due; 0 turns the audit off |
| `SESSION_GUIDE_FOLLOWUP_HOURS` | 24 | How often the follow-up review is due; 0 turns it off |
| `SESSION_GUIDE_QUEUES` | none | Extra queue files for the audit, separated like `PATH` |
| `SESSION_GUIDE_GH` | on | `0` turns every `gh` call off (claims and the audit's merged-PR check say "not checked") |
| `SESSION_GUIDE_GH_BUDGET` | 3 | Seconds all of one hook run's `gh` calls share; the rest wait for the next prompt |
| `SESSION_GUIDE_HOOK_SECONDS` | 7 | Seconds the hook's audit and claims blocks may take together; a block that runs over is skipped with one line, so the clock and reconcile lines always print |
| `SESSION_GUIDE_CLAIM_HOURS` | 4 | A run claim with no evidence this long is listed |
| `SESSION_GUIDE_CLAIM_DAYS` | 3 | How far back the hook looks for unclaimed merge and command lines; 0 = the whole ledger |
| `SESSION_GUIDE_CLAUDE` | `claude` | The binary `launch` runs (for tests) |

## peek.py

The transcript reader the guide uses. You can use it directly:

```
$ python3 skills/session-guide/scripts/peek.py b5c6d7e8
=== search reindex worker · Waiting on a refund rule [b5c6d7e8] · last write 10-27 14:05 · ctx 88k · claude-opus-5-5 / high
ASKED (WAITING ON AN ANSWER):
  - Partial refund on a 3-item order (600.00), customer returns 1 item (200.00), store at fault: refund the 5.00 restocking fee too?
LAST TEXT: The reindex is done on staging, but one rule needs a decision before I write the backfill. Details below.
```

It is read-only, stdlib only, and honors `CLAUDE_CONFIG_DIR`. `python3 scripts/demo.py` runs it on made-up sessions.

More detail: [how it works](docs/how-it-works.md).

## Notes

- Everything stays on your machine. The only network calls are `gh pr view` for merge claims and for the audit's
  merged-PR check (cached 10 minutes, 3 s per hook run in all, skipped when gh is missing or no repo is known;
  `SESSION_GUIDE_GH=0` turns them off).
  The only messages are between your own local sessions.
- If you run a cost guard that caps messages to the same agent, exempt messages to other top-level sessions. A guide
  relays many times per session by design.
- Contributions welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).
