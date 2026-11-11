# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.3] - 2026-11-11

### Fixed

- `ae status` tells the truth about thumbnails: "thumbnails: N ok, N waiting or failed", then "no thumbnail: N (no local file: turn on chrome_screenshots to capture them)". Status `none` means there is no local file to capture headlessly; 0.1.2 counted only pending and failed rows, so 168 rows with no thumbnail showed as "missing: 0".
- A row marked `none` is captured once its local file exists (it was never retried).

### Added

- `ae import --thumbs-only` copies the older explorer's Chrome screenshots (`~/.claude/artifact-explorer/shots`) into rows that have no thumbnail and changes nothing else. `ae status` says how many can be copied.
- A status line at the top of the page: when it was built (relative, refreshing while the page is open), when the watcher last checked, and whether a watcher was running, all "as of build". A page more than an hour plus two watcher intervals old says "Page may be stale". The watcher rewrites an unchanged page once an hour (and records a heartbeat in `watcher.json`), so the build time shows it is alive; `ae build` always writes.
- Rows without a thumbnail get a generated picture: an abstract composition seeded by the artifact id (the same on every build), its hue family set by the category, colours from the page theme (light and dark), with the title's first letter. Inline SVG, no library, no network. The table shows a small picture beside each title.
- `scripts/dev/fresh-install-reset.sh` and `fresh-install-restore.sh` (with `--dry-run`): back up the data folder, uninstall, remove only the plugin's allow rule, print fresh-install steps; and put it all back. Both refuse while a watcher uses the data folder.

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
- `ae import` to read an older `~/.claude/artifact-explorer` catalog.
- The hook never opens the database: it spools each payload to `DATA/inbox/hooks` and a detached `ae ingest-hooks` records it, so a long watcher pass can't make the hook time out.
- The background describer reads each page to a file and sends only `ae excerpt` (at most 3000 visible characters) to the `describer` agent.
- Sharing labels "Private" and "Shared with me"; the page shows cards by default on screens under 600px.
- The background describer starts only when the setup allow rule `Bash(sh */artifact-explorer/*/bin/ae *)` is in `~/.claude/settings.json`; otherwise rows wait for the in-session refresh.
