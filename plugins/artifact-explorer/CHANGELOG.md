# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-11-15

### Added

- Categories have colors. The pill shows on every card and row. A default palette (light and dark) is assigned by position in the category list; set `color` and `color_dark` on a `[[categories]]` entry to change one. "Uncategorised" is now "Uncategorized".
- The describer picks one category for each artifact in the same call as its sentence, so categories cost nothing extra. Rows with no description fall back to their kind, then to keywords.
- Topics: `[[topics]]` entries in your `config.toml` (`name`, optional `keywords` matched on the title). The describer tags up to three and may suggest a new one; the page shows suggestions apart from accepted topics, and topic pills filter the page. `ae topics` lists topics and suggestions with counts, `ae topics --accept NAME` adds one to your config, `--reject NAME` drops it. Setup mentions it after the first refresh.
- Someone else's artifacts show "from <name>" (or "from another organization"). Your own show nothing.
- Shared artifacts show an access badge (view, comment or edit). A row that was in an earlier shared list and is missing from the latest complete one shows "No longer shared".
- Local copies: each time a refresh reads an artifact someone else made, its page is kept in `copies/` in the data folder (never your own artifacts, never published). A "No longer shared" row with a copy gets "Save local copy".
- Clicking a card or a table row opens the artifact; Cmd/Ctrl-click and middle-click open a new tab; rows and cards take the keyboard.
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
