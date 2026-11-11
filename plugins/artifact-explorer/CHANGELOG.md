# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.1] - 2026-11-11

### Fixed

- "Modified, newest" no longer drops shared and owner-unknown rows to the bottom: rows without a modified time sort by their last access, then their created time.
- New rows start with thumbnail status `pending`, so `ae status` counts missing thumbnails and `ae thumbs` captures them; rows written by 0.1.0 with no status are treated as pending and backfilled when the catalog opens.
- A `claude.ai/code/artifact/<uuid>` visit and the short-id row of the same artifact from the artifact list are now one row: a uuid-keyed row folds into the only short-id row with the same title (on history scans, on `ae ingest-list`, and once when a 0.1.0 catalog opens). Events are kept.
- `config.toml` overrides keyed by a uuid follow the row when it merges into its short id.
- A row first seen as "Page not found" gets its title from a later browser visit (also " – Claude" titles); a 0.1.0 catalog rescans browser history once to fill them.
- Cards show who created the artifact and its sharing.
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
