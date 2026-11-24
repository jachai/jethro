# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.24] - 2026-11-24

### Added

- Away mode: `guide_title.py away --hours N | --until "<time>"`, `away end | status`, `away decide "<item>"
  "<option>" --reverse "<how>"`, `away hold "<item>" "<why>" "<action>"`, `away reverse <#>…`, `away done <#>…` and
  `away clear` (`scripts/guide_away.py`). While the user is away the guide asks nothing: it takes the recommended
  option for reversible choices (a row and a Decision "auto: user away") and holds the rest (merges, prod/staging
  writes, publishing, deletes, messages to people, money or business rules on real data, what only the user can type).
  State is `away.json` next to the ledger and a `## AWAY MODE` block in it (two tables), so it survives a handoff.
- The hook spots "going to sleep", "afk for N hours", "back in the morning" and prints the `away` command for the
  guide to run; while away its workers line drops the interview and a `session-guide away:` line gives the rules; the
  window ends at its time or on the user's first typed prompt, and the hook then lists both tables for the return
  round ("Tick any to reverse"). The guide's title shows "💤 until HH:MM"; `STATE.md` gets an Away mode section.
- `SESSION_GUIDE_AWAY_ASK_MINUTES` (off by default): an owed question unanswered that long is treated as away.
- SKILL §10 Away mode, and a first step in §4 The interview.

## [0.1.23] - 2026-11-23

### Fixed

- `stream table --end-unlisted` no longer stamps today's date on rows already marked "✅ DONE".
- `stream assign` says "no session with id / starting with" for an id that matches no session, instead of calling it the user's own window or "matches 0 sessions".

## [0.1.22] - 2026-11-23

Across 52 guides and 920 workers, 61% of worker reports reached the guide while its dialog was open (median wait 203 s,
p90 49 min), about 36% of 2,305 interview questions were bookkeeping, and workers waited a median 4 min (p90 97) for a
successor after a handoff. Dialogs now wait for workers, bookkeeping takes defaults, and workers start their own
successor. And a prompt you fired and forgot is no longer missed: the guide looks once at every session that ended
with nobody managing it.

### Added

- `guide_title.py working`, and a `session-guide workers:` line in the hook: which MANAGED workers are working now.
- `sweep --defaults` (`SESSION_GUIDE_NEW_SESSION_MINUTES`, default 15; 0 asks as before), `done --closable`,
  `results-defer`, `sleep --due`, and `sleep <id>` with no hours (`SESSION_GUIDE_SLEEP_HOURS`, default 2).
- `guide_title.py finished` (`scripts/guide_finished.py`) and a `session-guide finished:` paragraph in the hook:
  every session that ended in the last 24 h (`SESSION_GUIDE_FINISHED_HOURS`) with no row or an ACTIVE row gets one
  look at its final message (result line, open question, "not done / follow-up / blocked / refused" wording) and a
  line in the status under "Finished on their own". Loose ends become an Open items row or a question; `finished
  --reviewed` marks what was looked at, so nothing shows twice. `claude -p` and launchd runs come as one line per
  job, only when a run failed or was refused. ACTIVE sessions are still never messaged.
- `launch --successor-of <id> --ledger <path>` for a worker's own successor, a note under `successors/`, reconcile's
  SUCCESSOR STARTED line, and two warnings (no `uds:` socket in the prompt, untrusted folder). `launch --lean` also
  denies Artifact, Workflow, SendFeedback and ReportFindings.

### Changed

- While a MANAGED worker is working, a dialog is only for a blocking question, one per call; the rest goes in the text
  under "Needs you now" with a `needs input:` line.
- New sessions, closes, snoozes and "haven't looked yet" take defaults with no question; result verdicts and due
  reminders come as one multi-select "Tick what is settled". A deliverable is still DONE only on your Satisfied.
- Worker contract rule 4: a worker near its limit starts its own successor and reports HANDED OFF with the new id; the
  guide starts one only when the launch failed.
- `launch` denies `AskUserQuestion` by default (`--allow-ask` to keep it).

### Fixed

- Stream icons no longer drop from session titles after a manual rename: `guide_title.py` sync now records the bare
  title variants in session-titles history, and session-titles 0.1.3 keeps an origin that changed since its first
  write.

## [0.1.21] - 2026-11-22

With many sessions on many projects, a title or a question did not say which project it was about. Now each stream has one
icon, and its sessions, questions and status lines carry it.

### Added

- Streams (`scripts/guide_streams.py`, `guide_title.py stream add | rename | end | list | suggest | assign | strip |
  table`): a registry, `streams.json` next to the ledger, of each stream's key, icon, name and sessions. An icon belongs
  to one open stream on a machine; an ended stream's icon is free again after 7 days; out of icons, a stream gets a
  two-letter tag (`[TW]`).
- A session's title has its stream's icon right after its level prefix ("🟧🟧 (g) 🏠 billing lead"), put back after a
  rename and kept through DONE. A session on no stream keeps the title it had.
- `launch --stream <key>` and `launch --successor-of <id>` start a session on a stream, or on its predecessor's.
- Icons on the hook's lines, `settle` and `STATE.md` (which has a Streams section), and an Icon column in the ledger's
  Streams table. They are added when a row is shown, never stored in an Open items, Results, owed-question or Owner cell.
- `SESSION_GUIDE_STREAM_ICONS=0` turns every icon off; `stream strip` takes the ones shown off titles.

### Changed

- Reconcile reads a Sessions row with the icon outside the quotes, a "(g·scope)" prefix, and a result line with the icon
  alone before its protocol word ("🏠 BLOCKED: …").
- The skill, the worker contract and the ledger template say where an icon goes and where it never does.

## [0.1.20] - 2026-11-19

Two failure modes with one cause: the ledger said one thing, the facts another, and only the guide's memory joined
them. A worker that handed off sat 29 minutes unseen across a guide change, and the audit asked the user about work
finished days before. Each fix below is a check a script runs, not a rule the guide has to remember.

### Added

- Reconcile (`scripts/guide_reconcile.py`, `guide_title.py reconcile [--ledger <path>] [--grace-minutes N]`): every
  MANAGED and WATCHED row against its job's real state (`jobs/<id8>/state.json`, `timeline.jsonl`, the live process
  list). A row whose job ended over 3 minutes ago (`SESSION_GUIDE_GRACE_MINUTES`) is listed as HANDED OFF (no
  successor row: start it now, without asking the user), BLOCKED (no Waiting row), ENDED, UNDELIVERED (its last report
  never reached the guide) or INBOX (a report in `<ledger dir>/inbox/<id8>.md`). The hook prints it on every guide
  prompt, `settle` and `retire` run it, and `mark` prints it first, before the audit table. It never writes.
- Already covered? (Decision 992): before an idle, quiet, person or asked row, or a due reminder, is put to the user,
  the audit looks for later evidence of the same ticket, PR, monitor or artifact id (a satisfied Results row, a DONE
  session whose role or brief names it, a closing Decision, a Verifications row, a duplicate reminder, gh saying the
  PR merged). Such a row becomes kind `check`: "likely done: … Confirm, then `set <key> done "<evidence>"`. Do not
  ask the user." It leaves the ask list and the hook's nag count; a row that stays carries "checked <date>: still
  open because …".
- Strike sweep: the full audit writes `strike-candidates.md` next to the ledger; when the last sweep is over 24 h old
  the hook asks the guide for ONE read-only 'strike sweep' helper, whose `<key> | DONE / SUPERSEDED / OPEN |
  <evidence>` lines `guide_audit.py strike --from <file>` applies (DONE rows marked with their evidence, OPEN ones
  stamped checked, one Log line, one line for the user). `audit --open-batch` lists what is really open, grouped by
  stream, for one keep / start / drop question per group.
- Claims (`scripts/guide_claims.py`, `guide_title.py claim merge #N [--repo o/r] [--by <who>]`, `claim run
  "<command>" --by <who>`, `claim done <key> "<evidence>"`, `claim list`): a `## Claims` table in the ledger. The hook
  re-checks open merge claims with `gh pr view --json state,mergedAt` (`scripts/guide_gh.py`: cached 10 minutes, 5 s
  timeout, fails open, `SESSION_GUIDE_GH=0` turns it off); a merged PR closes its own claim and the hook says so once.
  gh is asked only with a repo (the claim's own, or the one repo on the ledger's `Scope:` line; `guide_gh.repo_for`),
  never the current folder's; a claim or `closes: pr:#N` tag with no repo stays open as "repo unknown: add --repo".
  All of one hook run's gh calls share one budget (`guide_gh.set_budget`, `SESSION_GUIDE_GH_BUDGET`, default 3 s), so
  the hook can't be killed by its 10 s timeout; a call cut short is unchecked and asked again on the next prompt.
  Run claims with no evidence after `SESSION_GUIDE_CLAIM_HOURS` (default 4) are listed, and ledger lines that say
  "MERGE READY #N", "<someone> runs / tells …" or hold a `!` command with no claim row are counted
  (`SESSION_GUIDE_CLAIM_DAYS`, default 3).
- `closes:` tags: an Open items row or a reminder can say `closes: pr:#N`, `result:<artifact id>`, `ticket:<ID>` or
  `session:<id8>`, and `waiting` / `waiting ask` take `--closes`. When the event happens the audit closes the row
  itself and the next hook line says so. A script that writes a Waiting or Results row, or closes a Sessions row, prints
  the open rows that share an id with it, so the guide can close the old row while it still has the context.
- Clock: every guide prompt starts with "Now: <local date, time and zone>", and the audit flags ledger lines dated
  after now. A guide's own written times had drifted 2 hours ahead in 2 hours of work.
- `guide_title.py launch [--watched] -- <claude args>`: starts a worker with `claude --bg` and writes its guided
  marker the moment the session id is printed, while its first model call is still in flight (`--resume <id>` is
  marked before it runs). `claude --bg` ignores `--session-id`, so a new session can't be marked sooner. A worker
  marked a moment after a plain `claude --bg` had been stopped by a cost guard on its first tool call.
  `SESSION_GUIDE_CLAUDE` names another binary (tests).

### Changed

- Worker contract rule 4: HANDED OFF, BLOCKED, DONE and MERGE READY always go by SendMessage to the guide's socket,
  `uds:<socket>` exactly as the brief gives it, and a guide change never suspends this. A failed send goes to
  `<ledger dir>/inbox/<id8>.md`, which reconcile reads. The guide's handoff no longer tells workers to report in their
  final message (that line went out at 11 of 13 guide handoffs); `retire` prints the fixed line the guide sends
  instead: "Guide changing. Keep sending to this socket; the old guide forwards until the new one introduces itself."
- `retire [<id>] [--to uds:<socket>] [--force | --check]` is a gate: it runs reconcile and exits 1, retiring nothing,
  while a row needs a guide. `--force` retires anyway and writes those rows into the ledger's `## Handoff (open at the
  last guide change)` table; `--check` only runs the gate. A retired guide's hook tells it on every prompt to forward
  every message to the new guide's socket and not act.
- The skill: the guide starts workers with `launch`, acts on reconcile lines on every prompt, never asks the user
  about a `check` row, strikes rows only after the sweep helper confirms each and tells the user in one line, puts
  the rows still open to the user as one batch grouped by stream after the first sweep, claims every merge and
  command it hands to someone, and runs `retire --check` before handing off.
- The ledger template has the Claims and Handoff tables, `closes:` tags and the `inbox/` folder; the README has a
  table of every environment variable.

### Fixed

- STATE.md "Open sessions" printed "running" for any session whose transcript had changed in the last two hours,
  so a worker that had handed off minutes earlier still read as running. It now prints the job's real state
  ("working: …", or "ended 12 min ago (done), result: …"); the old wording stays only for a session with no job
  folder.
- Worker reports sent to the guide's session title: the send fails and the report is lost (two workers on 11-19, one
  verdict never delivered). The worker contract, the prompt suffix, the join steps and the verify brief now say
  "send to uds:<socket>, never a title", and reconcile lists a report sent anywhere else as UNDELIVERED.
- A session result "handed off to the guide" (a deliverable passed on) no longer counts as an unfinished handoff;
  reconcile classifies a session by its result line, not by loose words in its text.
- A "quiet" audit row could name an unrelated worker that only shared a version number with it; versions no longer
  match a worker to a row.

## [0.1.19] - 2026-11-19

### Added

- `scripts/guide_audit.py`: the guide's look back over its whole body of work. `audit [<ledger>]` lists what is not
  done or not verified: Open items and queue-file rows with no live worker, items waiting on a person nobody is
  asking, landings with no verification, reminders open over a day, recent decisions nothing refers to, and sessions
  of the last 5 days that ended without a clean `result:` line. Rows are ranked by value x age, rows that share one
  next action are collapsed, and the top 10 print with one next action each (`--limit`, `--group <key>`, `--all`).
  `set <key> started | asked | parked | done | dropped` records what the guide did about a row. `--quick` skips the
  transcripts (about 2 s on a 1 MB ledger; the full audit takes about 6 s).
- Queue files: a `Queues:` line in the ledger's first lines (or `SESSION_GUIDE_QUEUES`, or `--queue`) names markdown
  tables of approved work outside the ledger, so a fix queue another session appends to is audited too.
- `STATE.md` next to the ledger: a few KB of live state (open sessions, reminders, results with no verdict, the
  audit's top 20 rows), rewritten on every audit. A takeover reads it instead of the ledger's log.
- The guide title shows the idle count and the oldest age (" · 15 idle 4d"; `{idle_note}`, `{idle}` and `{oldest}`
  in `SESSION_GUIDE_TITLE`). The hook nags a guide when an idle item is over `SESSION_GUIDE_IDLE_HOURS` (default 12)
  old with no question to the user, and says when the full audit is due (`SESSION_GUIDE_AUDIT_HOURS`, default 12;
  0 turns the audit off).

### Changed

- `guide_title.py mark` runs the full audit and prints its table, `settle` ends with the quick audit and, with nothing
  else due, tells the guide to work the table instead of sleeping, and `retire` refreshes `STATE.md`.
- The skill's status reply has a "Decided, not moving" heading, the takeover reads `STATE.md` first, and the handoff
  runs the audit.
- A custom `SESSION_GUIDE_TITLE` needs `{idle_note}` added to show the idle count.

### Fixed

- The skill told the user to run `guide_approve.py` from `~/.claude/skills/session-guide`, which doesn't exist on a
  plugin install. It now uses the skill's own base directory.

## [0.1.18] - 2026-11-18

### Changed

- Moved into the [jethro](https://github.com/jachai/jethro) suite. Install with
  `/plugin marketplace add jachai/jethro` and `/plugin install session-guide@jethro`. The hooks
  come from the plugin's `hooks/hooks.json`; remove any `guide_title.py` hook lines pasted into
  `settings.json` by hand.
- `install.sh` is deprecated; it prints a notice but still installs, and `--uninstall` works as before.

## [0.1.17] - 2026-11-09

### Added

- `scripts/guide_approve.py <id8> "<approval>"`: run in a plain terminal tab, it shows the one matching background
  session, copies the approval to the clipboard and runs `claude attach <id8>`; the user pastes and presses Enter. It
  refuses inside a Claude window or without a TTY (`!` cannot switch windows).

### Changed

- The guide tells the user to open a new terminal tab for approvals in a session's own window, never `! claude attach`.
- New rule: one Bash call per `claude stop <id8>`, never in a loop, heredoc or beside ledger edits, so the allow rule matches.

## [0.1.16] - 2026-11-08

### Changed

- **One guide per ledger, per machine.** Remote Control shows another machine's guide and its workers in `ListAgents`,
  and four rules reached across: the sole-guide rule retired any session titled like a guide, a guide retired itself
  on any RETIRE, workers reported to the newest guide that introduced itself, and the guide classified every session
  it saw. Now a rival guide is one on this machine (claude-top or a marker) whose marker or `Guide:` line names this
  ledger; a Remote Control guide, or one with another ledger, goes on the ledger's new `Other guides:` line and is
  never retired or messaged (unsure: ask the user, recommending "leave it"). A RETIRE counts only from the expected
  successor or when it quotes this ledger's path, else the guide replies "not my ledger". Only sweep sessions and
  non-Remote-Control rows are classified. Why: a guide sent RETIRE to another machine's guide.
- The guide's intro, the worker contract and the prompt suffix carry the slug, the ledger path and the guide's `uds:`
  socket. A worker accepts a new guide only when its intro names its guide's ledger path or slug, and answers
  "not my guide: <slug>" otherwise; it never picks a guide from `ListAgents` by title or by which is newest. Join mode
  reports to the socket on the ledger's new `Scope:` line (`<slug> · <host> · <config dir> · <uds socket>`).
- The default guide title names the ledger: "🟥🟥 Sessions Manager · <slug> (...)". `SESSION_GUIDE_TITLE` gets
  `{slug}` and `{host}` placeholders; a custom title without them works as before.

### Added

- [Two guides on two machines](docs/other-machine-setup.md): a scope name per machine in the title and worker prefix,
  and the `local.md` "Other guides" paragraph each guide needs.

## [0.1.15] - 2026-11-03

### Added

- **Not your PR, not your branch.** Before the guide sends any session to write to a PR's branch (merge another branch
  in, fix a conflict, push a fix, revert), it checks the PR's author and assignee with
  `gh pr view N --json author,assignees,headRefName,body`. If the PR isn't the user's own, it asks first in the
  interview, naming the owner ("PR #N is Max's (branch X); let a session push to his branch?"). A user ruling that
  names the PR in a merge order does not count as that permission. Worker prompts that touch a PR branch carry the
  owner check result, and the worker contract (rule 10) tells workers to stop and ask when it is missing. Why: a
  conflict-fix session was sent to a PR from a merge order without the check; it was a teammate's PR and our merge
  commit landed on their branch and had to be reverted.

## [0.1.14] - 2026-11-03

### Added

- **Results for you.** A finished deliverable the user asked for (a doc, a deck or slide, a review, a report, a
  release, a PR ready for them) is recorded with `guide_title.py result "<deliverable>" <link> --from "<title [id6]>"`
  in the ledger's new Results for you table (deliverable, link, delivered, asked, answer), listed under a new
  **Results for you** status heading between Needs you now and Streams, and asked about in the interview: Satisfied /
  Change it / Drop it / Haven't looked yet. `result-answer "<deliverable>" satisfied|change|drop|not-looked` records
  the verdict; not-looked is asked again on the cadence the user picks (`--every <hours>`, default 1). `settle` and the
  hook list unanswered results like due reminders. The stream is not DONE, and its loose ends stay open, until the user
  answers; the worker session may close, the row stays.
- **Look before done.** Before a worker reports a user-visible deliverable as done, it opens it the way the user will
  (rendered, at the exact link) and confirms the change shows; the worker contract (rule 9) and SKILL §3 say so. A
  report without that is "delivered, unchecked": the guide sends a CHECK before presenting it, and the DONE rule in §5
  needs both that look and the user's Satisfied.
- **Owed questions survive handoffs.** `guide_title.py waiting ask "<question>" --hours N` (or `--at "YYYY-MM-DD HH:MM"`)
  writes a dated "owed question [<key>]" row in the waiting table the moment the guide says it owes the user a
  question, so a successor's `settle` surfaces it; `sleep <key>` and `unwait <key>` move or clear it. The takeover
  steps read the waiting and results tables first, and the handoff step requires every owed question to be a row.
- Status replies lead with what finished since the last reply, each with its link, before the stream list.

## [0.1.13] - 2026-11-03

### Added

- The guide picks the model and effort for each session it starts. `references/model-choice.md` is a short table keyed on
  the task the session does next, with the cost reason for each row: money and business-rule fixes, migrations, release
  gates and design reviews get the top model at high effort; well-specified builds the top model at medium; verify
  follow-ups `sonnet` at medium; mechanical edits, CI reads, read-only data checks and status reports `sonnet` at low.
  The guide starts sessions with `claude --bg --model <alias> --effort <level>`, using aliases so the table stays
  current; `local.md` can name a different top model.
- On a takeover, and when the user picks Manage or Watch for a session, the guide reads its model and effort and, when
  they don't fit its task, asks the user to type `/model <alias>` and `/effort <level>` in its window (the guide can't
  switch another session). "Keep as is" is recorded, so it isn't asked again until the task changes.
- A worker's successor is picked again for the next step's task, not copied from its predecessor.
- The ledger's Sessions table has a Model / effort column.
- `peek.py` shows the model and effort of a session's last main-thread turn on its first line.

## [0.1.12] - 2026-11-03

### Added

- Follow-up verification of recent fixes and deployments. About once a day (`SESSION_GUIDE_FOLLOWUP_HOURS`, default 24,
  0 = off) the hook tells the guide a review is due. `guide_title.py followups` lists the PRs and versions that the
  ledger's last 3 days or the sessions' transcript reports say reached production, staging, a merge or a release, with
  no verification recorded; the guide weeds the list and proposes a read-only "verify <thing>" session for each through
  the Open items flow. `guide_title.py verification <thing> <result> "<evidence>"` records proposed, running, verified,
  not-exercised (listed again for a re-check after 24 hours), broken or skipped in the ledger's new Verifications table.
- `references/verify-followup.md`: the brief for that read-only session. It reviews the merged code and the intended
  behaviour, states the expected behaviour in concrete terms (numbers where money is involved), checks real data and
  logs since the deploy, and reports verified, not exercised yet or broken, with evidence and loose ends. Database and
  log tools are named by role, so `local.md` can name the real ones.

## [0.1.11] - 2026-11-02

### Added

- Every MANAGED or WATCHED session now has to settle as waiting on the user or done, so nothing the guide followed is
  forgotten. `guide_title.py settle` lists sessions quiet for 2 hours in neither state, and reminders that are due; the hook
  gives a guide both on every prompt. `waiting` records the exact action in the ledger's waiting table, `sleep` puts the
  reminder off (the guide offers 1, 2, 8, 12, 24 and 48 hours), `unwait` removes it, and `done` removes it too.

### Changed

- With no active session, the guide no longer stops waking while reminders exist: it keeps one one-shot cron at the next
  reminder, since a wakeup can't reach past 60 minutes.

## [0.1.10] - 2026-11-02

### Fixed

- Closed sessions could stay orange for good. `done` tried the rename once: a session whose process was still running
  (they linger for hours after finishing) was skipped with nothing to retry it, and sessions closed before 0.1.9 were
  never revisited, because the "Closable" list skips anything already marked `done`. Every guide prompt and every
  `sweep` now renames closed sessions whose process has ended, and tell the guide to send CLOSE to those a process
  still holds.

## [0.1.9] - 2026-11-02

### Fixed

- A closed session kept its orange "🟧🟧 (g)" name in `claude agents` and claude-top. `done` only changed the marker and
  session-titles' stored origin, and the name the agents view shows (the job's `state.json` `name`) changes only when
  the session's next prompt runs the hook, which a finished session never gets. `done` now writes the "✅ " name
  itself when no process holds the session. Claude Code has no command that renames a session without running a turn
  in it, so this one-key edit is the only route for a session that is over; a live session is left alone and changes on
  its next prompt, as before. If it resumes later, the hook follows its `done` marker.
- The sweep (and the guide's hook context) lists sessions that are still marked managed, watched or active although
  every ledger row naming them is DONE, and says to run `done` on them. A job state of done alone never closes a
  session: workers' state goes done at every final message and the guide can resume them.

## [0.1.8] - 2026-11-02

### Fixed

- The guide's title no longer counts sessions that are closed: a row whose session has a `done` marker is skipped, and
  a session named by several rows counts once, at its topmost row's Level (rows with no `[id]` count as before). A
  title could show "33 managed" with nothing running.
- `guide_title.py done <id>` now also sets that session's Level to DONE in the guide's ledger, or says it couldn't
  find the ledger and closes anyway.

## [0.1.7] - 2026-10-31

### Added

- An ACTIVE level for sessions that are running but neither managed nor watched: `guide_title.py active <id>` puts
  blue blocks, "🟦🟦 ", before the title (override: `SESSION_GUIDE_ACTIVE_PREFIX`). The guide's title counts them.
- `guide_title.py sweep`: lists recently active sessions with no ledger row, reading transcripts directly, so it
  needs neither claude-top nor ListAgents. `claude -p` runs are left out.

### Changed

- The guide interviews. Anything it needs from you ends its turn in `AskUserQuestion`: new sessions, decisions,
  approvals it can relay, and Done / Not yet for what only you can do. Text is the fallback only when the tool is
  refused or unavailable, and an unanswered question is asked again.
- The title hook gives the guide the list of new sessions on every prompt, until each has a row, instead of relying on
  a sweep at wake time. The title's `new` count is live, so the ledger's `New:` line is gone.
- The guide keeps a wake scheduled while any session was active in the last 2 h, instead of stopping after two idle
  hourly wakes. It falls back to `CronCreate` when `ScheduleWakeup` is unavailable.
- In `SESSION_GUIDE_TITLE`, `{active}` now counts ACTIVE rows. Use the new `{tracked}` for what it used to mean,
  managed + watched.

## [0.1.6] - 2026-10-30

### Fixed

- The guided, watched and closed prefixes now show up on sessions running the session-titles plugin. Its hook's title
  overrode this one on most prompts, so the prefix only appeared when it had nothing to say. `guide_title.py` now
  writes the prefix into its stored origin, so both hooks give the same title.
- Marking or retiring a guide turns session-titles off for that session, so nothing overrides its red or faded red
  title.

## [0.1.5] - 2026-10-30

### Added

- WATCHED sessions get a title too: `guide_title.py watched <id>` puts light gray blocks, "⬜⬜ ", before the title
  (override: `SESSION_GUIDE_WATCHED_PREFIX`). `unwatched` takes them off, and `guided` and `watched` swap one prefix
  for the other. The guide runs these whenever a session's level is set or changes.

### Changed

- One color per kind of session. MANAGED sessions now start with orange blocks in addition to the "(g)":
  "🟧🟧 (g) ". A title with the old bare "(g) " is upgraded on its next prompt.
- A retired guide's title is faded red instead of green: "🎟️🎟️ Sessions Manager (retired) 🎟️🎟️". Unicode has no pale red square, so 🎟️ is the
  closest match. The active guide stays 🟥🟥, and closed sessions stay ✅.

## [0.1.4] - 2026-10-29

### Added

- Open items have owners. The ledger's Open items section is a table, Item | Owner | Next action | Status. The
  owner is an existing session (title [id6]), "new session (proposed)", or the user; a row with no owner yet says
  ASK. Nothing is parked as "whenever you want" or FYI.
- After every worker report or handoff the guide re-reads it for loose ends ("not fixed", "out of scope", "FYI") and
  adds each one to the table. Workers list what they found but did not fix in their step reports.
- Every wake and every status reply puts the rows marked ASK, or proposing a new session not yet started, into the
  next ask: at most 4, each a recommended owner + action, with a worked example for money or business rules.
- A "Proposed actions" block in the status reply: actions on active sessions or new sessions to start, each
  answerable with yes or no.

### Changed

- Every "Streams" line in the status reply ends with "→ next: <action> (owner)".

## [0.1.3] - 2026-10-29

### Added

- Sweeps. Every wake runs `claude-top --once -n 30`; sessions active in the last 12 h with no ledger row are asked
  about in one batched "New sessions: … Manage, watch or ignore?" line, with a recommendation for each.
- Closing. `guide_title.py done <id>` (marker `done`) swaps a finished or obsolete worker's "(g) " for "✅ " (override:
  `SESSION_GUIDE_DONE_PREFIX`); `guided` and `mark` refuse it afterwards. The guide sends CLOSE, asks for a `result:`
  line, checks the state shows done, and lists `! claude stop <id>` for a session stuck on a dialog. Every STAND DOWN
  asks for the `result:` line too.
- A WATCHED session's unanswered question goes to the user; the answer is relayed in one message, the only one a
  WATCHED session gets.
- The guide prints its own context size in every status reply and hands off at 120k.

### Changed

- The guide title is "🟥🟥 Sessions Manager (2 managed · 1 watched · 3 new) 🟥🟥". new comes from a `New: <n>` line
  the guide writes into the ledger header on each sweep. `SESSION_GUIDE_TITLE` gains `{watched}` and `{new}`.

## [0.1.2] - 2026-10-28

### Added

- Guided prefix. Every MANAGED session's title starts with "(g) " so you can tell at a glance which sessions don't
  need you. `guide_title.py guided <id>` (run by `/session-guide join` and by the guide for sessions it starts or
  classifies MANAGED) adds it through the same hook; `unguided <id>` (on `/session-guide leave`, or a reclassify to
  WATCHED / IGNORED) takes it off. Never doubled, kept through renames and session-titles focus updates, never on a
  guide or a retired guide. Override: `SESSION_GUIDE_GUIDED_PREFIX`.

### Fixed

- `guide_title.py` refuses an empty session id (for example from a failed lookup) instead of acting on the current
  session. Id prefixes resolve from worktree project folders too.

## [0.1.1] - 2026-10-28

### Added

- Retired guides. When a guide takes over (or the user picks one of two guides), the old one is retired:
  `guide_title.py retire <id>` turns its title to "🟩🟩 Sessions Manager (retired) 🟩🟩" (override:
  `SESSION_GUIDE_RETIRED_TITLE`), and the hook never turns a retired id red again. The new guide asks it for a final
  message ending in a `result:` line so its state turns done, checks that, and marks it RETIRED in the ledger.
- An outgoing guide retires itself once its successor has introduced itself, instead of ending on a question.

## [0.1.0] - 2026-10-28

### Added

- The `session-guide` skill, packaged as a Claude Code plugin and marketplace, plus `install.sh` for a plain skill install.
- Guide mode:
  - advisory hard rules;
  - a sole-guide check;
  - MANAGED / WATCHED / IGNORED session levels;
  - batched relays;
  - numbered FINAL decisions with conflict checks;
  - the "Needs you now" status shape;
  - self-paced wakeups with back-off;
  - a ~120k guide handoff.
- Join and leave modes, so a worker can opt in with `/session-guide join` and out with `/session-guide leave`.
- `references/`: the worker contract, the ledger template and an example release playbook.
- `local.md` overrides and a `playbooks/` folder under `~/.claude/session-guide/`.
- `peek.py` (stdlib only, Python 3.9+): a session's title, context size, last reply, unanswered questions and last
  cross-session message.
- A pinned guide title, "🟥🟥 Sessions Manager (X of Y) 🟥🟥" with live MANAGED / WATCHED counts from the ledger:
  `guide_title.py mark|unmark|hook`, a `UserPromptSubmit` + `SessionStart` plugin hook that restores it after any
  rename, a `settings.json` snippet that `install.sh` prints for plain-skill installs, and a `SESSION_GUIDE_TITLE`
  override.
- A unittest suite on temp config dirs, CI on Ubuntu and macOS with Python 3.9 and 3.14, `scripts/demo.py`, issue
  templates, and a tag-driven release workflow.
