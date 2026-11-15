# Artifact Explorer

A Claude Code plugin that keeps a catalog of your claude.ai artifacts on your own machine. You get one local page to search, sort and reopen everything you made or were sent.

It stores a SQLite db, a `config.toml` and a static `explorer.html`. It needs Python 3.9+ and nothing else.

## Install

```
/plugin marketplace add jachai/artifact-explorer
/plugin install artifact-explorer@artifact-explorer
/artifact-explorer:setup
```

Setup first prints the version it runs and whether your data folder is empty, then shows the options, writes `config.toml`, offers to import a catalog from the pre-plugin version, runs a first refresh, offers one permission rule (only written if you say yes; it says when the rule is already there), offers a one-row test of the background describer and opens the page. Run `/artifact-explorer:open` any time after.

## Update

```
claude plugin marketplace update artifact-explorer
claude plugin update artifact-explorer@artifact-explorer
```

Then open a new Claude Code window: a running session keeps the version it started with. Updating the marketplace alone does not move the installed plugin. `sh ~/.claude/plugins/cache/artifact-explorer/artifact-explorer/*/bin/ae doctor` (or the first step of `/artifact-explorer:setup`) prints the version this window runs, the installed version and the marketplace version, and says MISMATCH when they differ.

## Cost

Descriptions are written by a background `claude -p` run on `haiku` (the `describe_model` option). Each run is limited to $0.20, $0.25 is booked against the daily cap when it starts, and the real cost replaces the booking when it ends. The default cap is $1.00 a day (`describe_daily_cap`); `ae status` shows today's spend. A run that ends without reporting its cost gives its booking back, and after two such runs in a day the describer waits for the next day. Without the setup permission rule no background run starts and nothing is spent; `/artifact-explorer:refresh` in a session describes on your normal usage.

## Options

Change them in `/config` (plugins).

- `watch_interval`: minutes between watcher passes (default 10, 2 to 240).
- `browser_history`: read a copy of your browser history for claude.ai artifact URLs (default on).
- `transcript_reads`: scan `~/.claude/projects` for Artifact tool calls (default on).
- `chrome_screenshots`: let `/artifact-explorer:screenshots` use Claude in Chrome for thumbnails (default off).
- `share_harvest`: let `/artifact-explorer:sharing` read the Share dialog of your artifacts in Chrome (default off).
- `describe_model`: model of the background describer session (default `haiku`). The `describer` agent itself always runs on `haiku`.
- `describe_daily_cap`: USD per day for background describer runs (default 1.0). A run starts only when today's spend plus one run's $0.25 limit stays within it, and only one run goes at a time.

## Which artifacts get described

Only a recent window, 60 days by default (`[window] days` in config.toml; `0` covers everything). Older rows sit in a collapsed "N older artifacts" group on the page. `/artifact-explorer:refresh older` widens the window by 30 days and describes them. Docs, Slides and Dashboard artifacts are described from their own source (the Doc's lead paragraph, the deck outline, the dashboard page and datasets). When that source cannot be read the title stands in, and `/artifact-explorer:refresh retry` tries again. Artifacts shared with you have no date in the list, so they count from the day the catalog first saw them.

## What leaves the machine

Only Claude's own calls: the Artifact list and read calls against your claude.ai account (plus ArtifactData and Claude Docs reads for Dashboards and Docs), and the describer model that writes one sentence per artifact. There is no telemetry. Browser history and transcripts are read locally from copies, and only claude.ai artifact URLs and Artifact tool lines are kept.

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
