# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.2.12] - 2026-11-19

### Changed
- Moved into the [jethro](https://github.com/jachai/jethro) suite. Install with `/plugin marketplace add jachai/jethro` and `/plugin install artifact-explorer@jethro`. The old `artifact-explorer@artifact-explorer` id keeps working.
- Every lookup of the install (`installed_plugins.json`, the options in `settings.json`, the doctor, the marketplace clone) accepts any `artifact-explorer@*` id: the one whose install path is the running code, else `artifact-explorer@jethro`, else any. Options under the old id are still read when there are none under the new one.
- The update check reads the `artifact-explorer--v*` tags of `jachai/jethro` (newest version wins) instead of the releases of `jachai/artifact-explorer`. The update commands name the marketplace of the install.
- The data folder follows the install id (`artifact-explorer-jethro`). On first run under a new id the catalog is copied from an `artifact-explorer-*` folder that has one, when the new folder has no `explorer.db`. The old folder is left in place.
- The README doctor command finds any `artifact-explorer@*` entry. Own marketplace, LICENSE and workflows removed (the suite has them).

## [0.2.11] - 2026-11-16

Chosen as 0.2.11, not 0.3.0: no config breaks; only defaults change.

### Changed
- Card: only the thumbnail is a link, so the title and text can be selected and copied. The table has an Open button on every row again.
- Every artifact link has its own window name (`ae-<id>`). claude.ai's cross-origin opener policy clears the name, so the tab cannot be reused and each click opens a new tab.
- Topic chips in the filter row carry the same color as that topic's marks on cards and rows, in both themes.
- Everything is automatic: a suggested topic is applied as a normal topic (no "suggested" state or tooltip). Setup asks for every permission once, up front. The first load is capped at the newest 100 artifacts (`[window] first_load`; `ae window --widen` lifts it).
- Topic promotion counts uses per title family (first two title words), so a one-off is no longer promoted; a one-time recheck drops old one-family promotions.
- The background describer is no longer allowed ArtifactData (it never calls it there; an unattended run was refused it and backed off for an hour). A test checks that every tool and `ae` form the background mode uses is allowed.

### Added
- `ae topics --hide NAME` / `--unhide NAME` to hide a topic from the page.

### Fixed
- A reachable artifact was marked "No longer shared": other-organization rows are now marked gone only when the list includes other-organization rows.
- Many cards sat on "description pending": a productive run that reached the budget ceiling no longer backs off, and shared rows the describer cannot read show "shared with you, not read" instead of pending.

## [0.2.10] - 2026-11-16

### Fixed
- Promoted (and configured) topics were not applied to rows the describer had not tagged yet (topics never stored), so a promoted topic showed only 0-2 rows. A suggestion that matches a configured or promoted topic now applies to those rows too.

## [0.2.9] - 2026-11-16

### Added
- Suggested topics are promoted automatically. A describer suggestion used on at least `min_uses` artifacts (`[topic_promote] min_uses`, default 2, 0 = off) becomes a topic: it applies to those rows and shows in the Topic filter. Promotion re-runs on every build and watcher pass. Promoted topics are recorded in the state table, so they stay; `[topic_promote] demote = [...]` drops one and `[topic_promote.rename]` renames one. Topics in `[[topics]]` and row overrides are never changed.
- Near-duplicate suggestions are merged before counting: case, spacing, simple plural ('change order' = 'change orders'), and a word-prefix rule ('change order backlog' folds into 'change orders' only when the longer one has fewer uses).

## [0.2.8] - 2026-11-16

### Fixed
- A background describer run was refused at its first Dashboard row (`stopped: refused ArtifactData`): an unattended `claude -p` run is refused any ArtifactData call with a custom `out_dir`, including the TMP from `ae tmpdir ID`, so the whole 8-row batch went unsaved. In the background mode the refresh skill no longer takes the Dashboard branch: a Dashboard or Data row makes no `ae tmpdir` or ArtifactData call, gets `ae set-desc ID --needs-interactive` and is left out of the batch, and the other rows of the batch are still described and saved. The in-session `/artifact-explorer:refresh` describes those rows as before.

## [0.2.7] - 2026-11-16

### Fixed
- A background describer run spent $0.146 preparing one batch of 18 rows (54 turns, one read per turn, three Docs reads per Docs row) and ran out of budget before the describer step, so it saved nothing; the watcher then started the same run again every 10 minutes. The refresh skill now works in batches of at most 8 rows (Describe rows, `batch recat --limit`, `batch local --limit`, older recat; the describer agent takes up to 8 items). Each batch is prepared, described by the describer agent and saved with `AE batch save` before the next one starts, and a run stops after the save when the budget is low. A Docs row is described from its title and outline headings only (the lead-paragraph read is gone). The independent reads of a batch go in parallel in one turn: all Artifact reads, then all Docs project reads, then all outline reads.
- Back-off (one hour, one `describer back-off: REASON, next try after HH:MM:SS` line in `watch.log`) now also follows a run that saved 0 rows, a run whose cost reached 90% of its $0.15 limit, and a run whose cost per saved row was above `STOP_LOSS_PER_ROW` ($0.01, the new `describe_stop_loss` option). The refusal case stays. A run with no cost report behaves as before.

### Added
- `describe-only N` (N 1..60) for the background mode: describe at most N rows. `describe-only` alone stays at most 60 rows.
- `ae launch-describer --rows N`: a manual launch like `--test` (ignores the interval and back-off, prints what happened) that passes `describe-only N`. `--test` is `--rows 1`.
- `describer.json` records `pending_at_launch`. When a run ends, rows saved = that count minus the current pending count (at least 0); `describer.log` and the `describer finished` line in `watch.log` show the saved count and the cost per saved row.

## [0.2.6] - 2026-11-16

### Fixed
- The background describer was refused twice in 0.2.5. The model chained many `ae` calls into one Bash command that began with shell variables (`AE=...; D=...; sh ...`), which matches no permission rule, so the whole command was refused; and it called the Artifact tool with `out_dir` set to the scratch folder, which a read refuses. The refresh skill now says `AE` is written out in full, every `AE` command is its own Bash call starting with `sh`, with no shell variables, chaining, pipes, redirects or `cd`, and that SCRATCH is only for files written with the Write tool (Artifact reads take no `out_dir`; ArtifactData only the TMP from `AE tmpdir ID`).
- Only one watcher runs per data folder: a second `ae watch` prints a line and exits 0 when `watcher.json` names a live pid whose command line is an `ae.py ... watch` process. A zombie process now counts as finished, so an ended describer that was not reaped no longer looks alive.
- A describer run that ends with a refusal (`stopped: refused TOOL`) puts the watcher on a one-hour back-off: no new describer is launched for 3600 s and `watch.log` gets one line (`describer back-off: last run refused TOOL, next try after HH:MM:SS`). `ae launch-describer --test` is not blocked.

### Added
- `ae batch excerpt FOLDER ID=SAVED_FILE [ID=SAVED_FILE ...]` does `ae excerpt SAVED_FILE --out FOLDER/ID.txt --id ID` for each pair, prints an error line for a pair that fails and goes on, then `excerpted N, failed K`.
- `ae set-kind ID=KIND [ID=KIND ...]` takes several pairs (the old `ae set-kind ID KIND` still works).
- `describer.log` in the data folder: one line per finished describer run with time, pid, cost, result text and, for each permission denial, the tool name and its input (cut at 2000 characters). `describer.out` still holds the latest raw output.

## [0.2.5] - 2026-11-16

### Fixed
- The background describer still saved nothing: an unattended `claude -p` run may not use the Write tool under `~/.claude`, where the data folder is, so writing the describer's reply (`result.jsonl`) was refused and the run stopped. Every file the refresh skill writes (the reply, Docs/Slides/Dashboard sources, the artifact list) now goes to a scratch folder from `ae tmpdir` in the system temp folder. `ae batch save --folder FOLDER` reads the batch's manifest from the batch folder.

## [0.2.4] - 2026-11-16

### Fixed
- The background describer described nothing: `claude -p` withholds the Artifact tools unless `CLAUDE_CODE_ARTIFACT` is set, so the run could not read a single page. The watcher now launches it with `CLAUDE_CODE_ARTIFACT=1` (checked on Claude Code 2.1.325).
- The background run now categorizes rows from their existing descriptions (recat, topics) first, which needs no page read, so it is done even when no source can be read.
- When the background run has no Artifact tool anyway (a CLI that ignores the variable, an admin policy), it describes own rows from their local source file where one exists (`ae batch local`) and marks the rest "needs interactive refresh" instead of retrying. A row whose read errors in the background gets the same mark (`ae set-desc ID --needs-interactive`). Marked rows no longer count as waiting for the background run, so the watcher stops relaunching for them every interval.

### Added
- `ae status` and the SessionStart reminder name the own rows that need an in-session `/artifact-explorer:refresh`; that refresh describes them and clears the mark.

## [0.2.3] - 2026-11-16

### Fixed
- Background descriptions never ran: the skills write the `ae` path in quotes, and the background run's permission rule only matched the unquoted form, so every run was refused at its first call. Both forms are now allowed in the skills, the background run and the setup rule (`Bash(sh "*/artifact-explorer/*/bin/ae" *)` added next to the old rule; existing installs with the old rule keep working, and setup offers the new one).
- Rows described before 0.2.0 never got a category or topics. Schema version 2 makes every owned row missing a category or topics eligible again, and the background run now fills them (recat) after describing new rows.
- The update badge falls back to the marketplace clone when GitHub cannot be reached.
- A watcher replaced by a newer one now exits.

### Changed
- Describer batches are up to 20 artifacts per call and 60 per run (was 8 and 10).
- A background run books $0.02 against the daily cap at launch instead of $0.25; the real cost still replaces the booking when it ends. Each run's hard ceiling is $0.15.

### Added
- Every topic has a stable color, with a pill on each card and row in light and dark themes; clicking a pill filters by that topic.
- Rows without a category get one derived from kind, URL, title and description keywords instead of showing as Uncategorized (marked "guessed", never written to the catalog).
- CONTRIBUTING release steps (tag the merged bump commit) and a pull request template.

## [0.2.2] - 2026-11-15

### Changed

- Ownership is shown by color, not text: every card and row has a colored left edge, the accent color for your artifacts and a neutral gray-blue for everyone else's (light and dark). All "from <name>", "from another organization" and "your organization" text is gone, and so is the "other org" sharing badge and the `created_by` ("From") column; a `created_by` entry in your `columns` is ignored.
- Created and Modified always show a date. When the artifact has none (shared artifacts carry no dates in the list), the page shows "first seen" (when this explorer first saw it) or "last accessed", labelled as such, instead of "unknown".
- The describer may propose up to 3 new topics per artifact (`new_topics`), told to name broad recurring themes rather than phrases from one title, so suggestions cover more of the catalog. A 0.2.0-style single `new_topic` reply is still accepted.

## [0.2.1] - 2026-11-15

### Fixed

- The upgrade instructions ran `ae doctor` through a version glob (`.../artifact-explorer/*/bin/ae`). With 0.1.x still in the plugin cache the glob expanded to an old version first, so `doctor` reported 0.1.2. The README command now reads the `installPath` of the artifact-explorer entry in `~/.claude/plugins/installed_plugins.json`, and prints a clear error when there is none. It still matches the setup allow rule `Bash(sh */artifact-explorer/*/bin/ae *)`. Skills, hooks and the watcher already used `${CLAUDE_PLUGIN_ROOT}` and are unchanged.

## [0.2.0] - 2026-11-15

### Added

- Categories have colors. The pill shows on every card and row. A default palette (light and dark) is assigned by position in the category list; set `color` and `color_dark` on a `[[categories]]` entry to change one. "Uncategorised" is now "Uncategorized".
- The describer picks one category for each artifact in the same call as its sentence, so categories cost nothing extra. Rows with no description fall back to their kind, then to keywords.
- Topics: `[[topics]]` entries in your `config.toml` (`name`, optional `keywords` matched on the title; keyword matches are added to the describer's picks). The describer tags up to three and may suggest a new one; the page shows suggestions apart from accepted topics, and topic pills filter the page. `ae topics` lists topics and suggestions with counts, `ae topics --accept NAME` adds one to your config, `--reject NAME` drops it. Setup mentions it after the first refresh.
- Someone else's artifacts show "from <name>" (or "from another organization" or "your organization" when that is known, else nothing). Your own show nothing.
- Shared artifacts show an access badge (view, comment or edit). A row that was in an earlier shared list and is missing from the latest complete one shows "No longer shared".
- Local copies: each time a refresh reads an artifact someone else made, its page is kept in `copies/` in the data folder (never your own artifacts, never published). A "No longer shared" row with a copy gets "Save local copy".
- Clicking a card or a table row opens the artifact; Cmd/Ctrl-click and middle-click open a new tab; rows and cards take the keyboard.
- Cards show both dates, labelled: "Created" and "Modified" (hover either for the full date). The title column is always shown, since it carries the row link.
- An artifact with no thumbnail gets a tile with its initials on a gradient that stays the same for that artifact.
- The header shows the exact build time and a live "N min ago", and the version that built the page.
- Update check: at most once a day the build asks GitHub for the latest release, caches the answer in `update.json`, and shows "update vX available" with the update commands. Offline or rate-limited shows nothing. Turn it off with `update_check = false` under `[page]`.
- Favicon: a four-card grid in the accent color, inline in the page and as `favicon.ico` next to `explorer.html`.
- A one-off pass categorizes artifacts that were described before 0.2.0 (`ae batch recat`, run by the full refresh, at most 40 rows a run) from their title and description, with no re-describe.
- Database: new columns for category, topics, suggestions, access, other organization, shared seen/gone and local copy. They are added automatically the first time the database is opened.

### Changed

- Describing works in batches: up to 8 artifacts per describer call from one manifest file, and up to 3 batches in flight in one message. Describing five rows used to take five turns and about 40k tokens of context. New commands: `ae batch start|manifest|recat|save`.
- The describer agent takes a manifest path and answers one JSON line per artifact (sentence, category, topics, new topic).
- `ae ingest-list` reads `access` and `other_org`, and with `--shared-complete` marks shared rows that dropped out of a complete list.

### Fixed

- The refresh skill told the describer call to use `run_in_background: false`, which this Claude Code does not have, so every call ran async, one row at a time. The skill no longer sets it.
- `AE` stored in a shell variable failed under zsh (`$AE pending`: no word splitting). The skills now say to write each command out in full.

### Removed

- The Open column and button. Click the card or row instead.

## [0.1.5] - 2026-11-15

### Fixed

- The background describer could book the whole daily cap without describing anything: a run older than 30 minutes, or one that ended without a result, kept its $0.25 booking, and four of those used up the $1.00 cap. Now a run that ends without a cost report gives its booking back (at most two such runs a day, then the describer waits for the next day), a live run older than 30 minutes is waited on only while its command line is still the describer's, and one older than two hours is stopped. A new run's output file is cleared first, so an older report is never read as its cost.
- The background describer is given `Bash(sh */bin/ae *)` by name next to the refresh skill's tools. A headless run on 11-14 was refused `ae pending`.
- The page shows "unknown" for a missing date and "Untitled" for an empty title (it showed nothing, or the id). Each watcher pass marks rows with a publish event as yours and takes their last publish as the modified time when those were missing.

### Added

- `ae doctor` prints the version that runs and from where, the version in `installed_plugins.json`, the marketplace clone's version (MISMATCH, with the `claude plugin update` command, when they differ), whether the data folder is empty, whether the permission rule is present, and a check of a freshly built page (status line, stale banner, placeholder thumbnails). `--expect fresh|installed` makes it exit 1 when that is not so. It never creates the data folder.
- `/artifact-explorer:setup` starts with `ae doctor`, stops on a version mismatch, and says "not a fresh install" when the data folder already has a catalog. It says whether the permission rule was already present or added (checked with the new `ae allow-rule`), and offers a one-row describer test (`ae launch-describer --test`).
- `ae status` shows the last describer run's result. `ae pending --limit N`.
- README: how to update (a marketplace update does not move the installed plugin) and what describing costs.
- Developer scripts (`scripts/dev/`, not used by the plugin): the fresh-install reset ends by checking each step from the files themselves (data folder gone, plugin not in `installed_plugins.json`, marketplace removed, rule removed, no watcher) and exits 1 when one failed. `fresh-install-check.sh` runs after install and exits 1 unless the installed version is the marketplace one and the data folder is still empty.
- `.gitignore` leaves out `.claude/` (local worktrees and handoff notes).

## [0.1.4] - 2026-11-12

### Changed

- Descriptions cover a recent window: `[window] days = 60, key = "modified"` in config.toml (a row's date is its modified time, else created, else first seen; `days = 0` covers everything). The pending queue, the background describer, thumbnails and the SessionStart count only look at rows inside it. `ae status` adds "window: 60 days: X rows, Y described, Z waiting" and "older: M not described (run /artifact-explorer:refresh older)".
- Docs, Slides and Dashboard artifacts are described from their own source instead of being skipped: a Dashboard from its ArtifactData `files` page and `datasets` titles, a Slides deck from `project/deck.json` and its cover slide, a Doc from its title, outline and lead paragraph through the Claude Docs connector. Only pages with under 50 characters of text are still skipped; a typed artifact whose own source comes back empty shows its title instead (`retry` tries again). Several sources share the 3000-character excerpt, so a long dashboard page cannot push out its dataset titles, and typed rows are no longer queued last.
- The page shows rows older than the window in a collapsed "N older artifacts" group (cards and table). It is drawn only when opened (button or `#older`), without thumbnail images.

### Added

- `ae set-kind ID KIND` records the type an Artifact read reports ("Data" and "Dashboard" are one kind, "HTML" is Page). Pending and rows JSON carry `kind`.
- `ae set-desc ID --no-source`: when a typed artifact's source cannot be read, the title stands in (status `no-source`); a later describer sentence still replaces it. `ae pending --retry-no-source` queues those rows again, and also the 0.1.2-era "no text: typed artifact" skips.
- `ae window [--widen N]` shows the window and widens it by N days (kept in the catalog). `/artifact-explorer:refresh older` widens it by 30 days and describes; the page's "Describe older" button copies that command.
- `ae excerpt` takes several files, joined in order, and `--json-field F` reads that field of a `.json` file as HTML or text.
- `ae tmpdir ID` prints an empty per-row folder in a private per-user folder of the system temp dir (it refuses a symlinked or foreign one). A Dashboard's files are saved there, because ArtifactData refuses an `out_dir` inside the plugin data folder.
- `/artifact-explorer:refresh retry` runs `ae pending --retry-no-source` first.

### Not built (follow-up)

- Widen the window by itself when the page's "Show older" link (`explorer.html#older`) shows up in the browser history the watcher reads. It needs a probe that fragment visits reach the History database.

## [0.1.3] - 2026-11-11

### Fixed

- `ae status` tells the truth about thumbnails: "thumbnails: N ok, N waiting or failed", then "no thumbnail: N (no local file: turn on chrome_screenshots to capture them)". Status `none` means there is no local file to capture headlessly; 0.1.2 counted only pending and failed rows, so 168 rows with no thumbnail showed as "missing: 0".
- A row marked `none` is captured once its local file exists (it was never retried).
- The count of thumbnails `ae import --thumbs-only` can copy counts each row once and skips unusable previews, so it reaches 0 after an import. A damaged older catalog no longer breaks `ae status`.
- A watcher counts as running if its heartbeat is less than 10 minutes old. A long pass no longer shows as "no watcher". On Windows, a heartbeat that cannot be written no longer leaves a `.tmp` file behind.

### Added

- `ae import --thumbs-only` copies the pre-plugin version's Chrome screenshots (its `shots` folder) into rows that have no thumbnail and changes nothing else. `ae status` says how many can be copied.
- A status line at the top of the page: when it was built (relative, refreshing while the page is open), when the watcher last checked, and whether a watcher was running, all "as of build". A page more than an hour plus two watcher intervals old says "Page may be stale". The watcher rewrites an unchanged page once an hour (and records a heartbeat in `watcher.json`), so the build time shows it is alive; `ae build` always writes.
- Rows without a thumbnail get a generated picture: an abstract composition seeded by the artifact id (the same on every build), its hue family set by the category, colours from the page theme (light and dark), with the title's first letter. Inline SVG, no library, no network. The table shows a small picture beside each title.
- `scripts/dev/fresh-install-reset.sh` and `fresh-install-restore.sh` (with `--dry-run`): back up the data folder, uninstall, remove only the plugin's allow rule, print fresh-install steps; and put it all back. Both refuse while a watcher uses the data folder: they match the path with or without a trailing slash and with symlinks resolved, and they also check the watcher heartbeat. Both stop before changing anything if settings.json cannot be read.

## [0.1.2] - 2026-11-11

### Fixed

- Only one background describer runs at a time. The launch records its pid in `describer.json`; while it is alive (and under 30 minutes old) the watcher starts no other run and logs "still running".
- The background describer never waits for input. It is now a `claude -p` run that exits when done, with stdin closed, `--permission-mode dontAsk` and only the refresh skill's tools, so a tool outside them is refused, never asked; the skill then stops with `stopped: TOOL refused`. It calls the describer agent in the foreground. 0.1.1 used `claude --bg`, whose sessions stayed open "waiting" after the last reply.
- Docs, Slides and Data artifacts (their saved page is only the viewer shell) and pages with under 50 characters of text are marked `skipped` ("no text: typed artifact") by `ae excerpt --id --type`. They are no longer picked again or counted as pending; `ae status` counts them apart and the page shows "no description (typed)". Rows of a known typed kind go to the end of the queue.
- The daily cap is never overshot: a run starts only when today's spend plus its $0.25 limit (`--max-budget-usd`) fits under `describe_daily_cap`. The $0.25 is booked at launch (the run's own limit is $0.20, since claude checks it between turns) and corrected to the run's real cost once it ends. The watch log records each run's result, cost and any refused tools.

## [0.1.1] - 2026-11-11

### Fixed

- "Modified, newest" no longer drops shared and owner-unknown rows to the bottom: rows without a modified time sort by their last access, then their created time.
- New rows start with thumbnail status `pending`, so `ae status` counts missing thumbnails and `ae thumbs` captures them; rows written by 0.1.0 with no status are treated as pending and backfilled when the catalog opens.
- A `claude.ai/code/artifact/<uuid>` visit and the short-id row of the same artifact from the artifact list are now one row: a uuid-keyed row folds into the only short-id row with the same title (on history scans, on `ae ingest-list`, and once when a 0.1.0 catalog opens). Events are kept.
- `config.toml` overrides keyed by a uuid follow the row when it merges into its short id.
- A row first seen as "Page not found" gets its title from a later browser visit (also " – Claude" titles); a 0.1.0 catalog rescans browser history once to fill them.
- Cards show who created the artifact and its sharing; a shared row without a harvested sharing label shows "Shared with me".
- Rows with an unknown owner show "unknown" under Created by.

## [0.1.0] - 2026-11-10

### Added

- A local catalog of your claude.ai artifacts: SQLite db, `config.toml` and one static `explorer.html`.
- A PostToolUse(Artifact) hook that records publishes, reads and opens, and a SessionStart reminder when shared artifacts wait for a description.
- A silent background watcher (a plugin monitor) that scans browser history and session transcripts, makes thumbnails and rebuilds the page.
- Browser history support for Chrome, Chromium, Edge, Brave, Arc, Vivaldi and Firefox on macOS, Linux and Windows.
- Skills: `setup`, `refresh`, `open`, `screenshots` and `sharing`, and a `describer` agent.
- Options: `watch_interval`, `browser_history`, `transcript_reads`, `chrome_screenshots`, `share_harvest`, `describe_model` and `describe_daily_cap`.
- `ae import` to read a catalog made by the pre-plugin version of Artifact Explorer.
- The hook never opens the database: it spools each payload to `DATA/inbox/hooks` and a detached `ae ingest-hooks` records it, so a long watcher pass can't make the hook time out.
- The background describer reads each page to a file and sends only `ae excerpt` (at most 3000 visible characters) to the `describer` agent.
- Sharing labels "Private" and "Shared with me"; the page shows cards by default on screens under 600px.
- The background describer starts only when the setup allow rule `Bash(sh */artifact-explorer/*/bin/ae *)` is in `~/.claude/settings.json`; otherwise rows wait for the in-session refresh.
