# Artifact Explorer

A Claude Code plugin that keeps a catalog of your claude.ai artifacts on your own machine. You get one local page to search, sort and reopen everything you made or were sent.

It stores a SQLite db, a `config.toml` and a static `explorer.html`. It needs Python 3.9+ and nothing else.

## Install

```
/plugin marketplace add jachai/artifact-explorer
/plugin install artifact-explorer@artifact-explorer
/artifact-explorer:setup
```

Setup shows the options, writes `config.toml`, offers to import an older catalog, runs a first refresh, offers one permission rule (only written if you say yes) and opens the page. Run `/artifact-explorer:open` any time after.

## Options

Change them in `/config` (plugins).

- `watch_interval`: minutes between watcher passes (default 10, 2 to 240).
- `browser_history`: read a copy of your browser history for claude.ai artifact URLs (default on).
- `transcript_reads`: scan `~/.claude/projects` for Artifact tool calls (default on).
- `version_log`: record each publish, read and open as an event (default on).
- `chrome_screenshots`: let `/artifact-explorer:screenshots` use Claude in Chrome for thumbnails (default off).
- `share_harvest`: let `/artifact-explorer:sharing` read the Share dialog of your artifacts in Chrome (default off).
- `describe_model`: model of the background describer session (default `haiku`). The `describer` agent itself always runs on `haiku`.
- `describe_daily_cap`: USD per day after which no background describer run starts (default 1.0).

## What leaves the machine

Only Claude's own calls: the Artifact list and read calls against your claude.ai account, and the describer model that writes one sentence per artifact. There is no telemetry. Browser history and transcripts are read locally from copies, and only claude.ai artifact URLs and Artifact tool lines are kept.

## How it stays fresh

- A hook records every publish, read and open the moment it happens.
- A silent watcher (a plugin monitor) wakes every 30 seconds and runs one pass per `watch_interval` across all your sessions: history, transcripts, thumbnails, page rebuild, and a background describer run when something needs a description.
- `/artifact-explorer:refresh` reads your full artifact list and describes what is missing.

## Limits

- The watcher only runs while a Claude Code session is open (interactive or `claude --bg`, not `claude -p`).
- Reading an artifact someone else made always asks for consent. So background runs describe only your own artifacts. Shared ones wait for an interactive `/artifact-explorer:refresh`; SessionStart tells you when some are waiting.
- Browser history works on macOS, Linux and Windows for Chrome, Chromium, Edge, Brave, Arc, Vivaldi and Firefox.
- Thumbnails are made with a headless Chrome-family browser. Without one, the page draws a title card.
- Claude in Chrome may not be able to save screenshots to disk. The screenshots skill says so when it cannot.

## config.toml

It lives in the plugin data folder (`~/.claude/plugins/data/artifact-explorer-artifact-explorer/`). It sets the page title and accent, the columns, the category rules, a filter (for example show only some repos) and per-artifact overrides (category, description, hidden). See [docs/design.md](docs/design.md) and the samples in [examples/](examples/), such as `examples/filter-by-repo.toml`.

## License

MIT. See [LICENSE](LICENSE).
