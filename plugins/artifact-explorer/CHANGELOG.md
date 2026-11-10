# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - unreleased

### Added

- A local catalog of your claude.ai artifacts: SQLite db, `config.toml` and one static `explorer.html`.
- A PostToolUse(Artifact) hook that records publishes, reads and opens, and a SessionStart reminder when shared artifacts wait for a description.
- A silent background watcher (a plugin monitor) that scans browser history and session transcripts, makes thumbnails and rebuilds the page.
- Browser history support for Chrome, Chromium, Edge, Brave, Arc, Vivaldi and Firefox on macOS, Linux and Windows.
- Skills: `setup`, `refresh`, `open`, `screenshots` and `sharing`, and a `describer` agent.
- Options: `watch_interval`, `browser_history`, `transcript_reads`, `version_log`, `chrome_screenshots`, `share_harvest`, `describe_model` and `describe_daily_cap`.
- `ae import` to read an older `~/.claude/artifact-explorer` catalog.
