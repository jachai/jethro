# Design (v1)

A Claude Code plugin that keeps a catalog of your claude.ai artifacts on your own machine:
SQLite db + `config.toml` + a static `explorer.html`. Python 3.9+ standard library only
(TOML is read with the vendored `scripts/vendor/tomli`). No zsh, gh, launchd, gist or server.

## Paths

- `ROOT` = `${CLAUDE_PLUGIN_ROOT}` (changes on every update; never write here).
- `DATA` = `${CLAUDE_PLUGIN_DATA}` = `~/.claude/plugins/data/artifact-explorer-artifact-explorer/`.
  Every script takes `--data DIR`. When it is not given, use env `AE_DATA`, then that default path.
- Files in DATA: `explorer.db`, `config.toml`, `explorer.html`, `thumbs/<id>.png|.webp|.jpg`,
  `watch.lock`, `ingest.lock`, `watch.log` (kept under 1 MB, one rotation), `inbox/`.
- Entry point: `bin/ae` (POSIX sh) runs the first of `python3`, `python`, `py -3` that is ≥3.9 with
  `scripts/ae.py "$@"`. Hooks, the monitor and skills all call `sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" <cmd>`.
  On Windows, Claude Code runs commands through Git Bash, so `sh` exists.

## Options (plugin `userConfig`)

`watch_interval` (minutes, 10), `browser_history` (true), `transcript_reads` (true), `version_log` (true),
`chrome_screenshots` (false), `share_harvest` (false), `describe_model` ("haiku"), `describe_daily_cap` (1.0 USD).
**One way to read them:** `common.options()` reads `~/.claude/settings.json` → `pluginConfigs["artifact-explorer@artifact-explorer"].options`
(monitors don't get `CLAUDE_PLUGIN_OPTION_*`, so nothing uses env), merged over the defaults above.
`CLAUDE_CONFIG_DIR` overrides `~/.claude` when it is set.

## Modules (`scripts/`)

| module | owns |
|---|---|
| `common.py` | paths, `options()`, `load_config()` (ROOT/config/default.toml deep-merged with DATA/config.toml), `log()`, `lock()` (O_EXCL lock file with pid + time; stale if the pid is dead or older than 3× interval), `repo_of(cwd)` (walks up to `.git`; a `.claude/worktrees/<x>` path maps to the main repo; returns the folder name), `detach(argv)` (Popen with `start_new_session` / `DETACHED_PROCESS`, stdio to devnull) |
| `db.py` | schema, `connect(data)`, `upsert_artifact(con, id, **fields)` (only overwrites a field when the new value is not None; description only when the new `desc_source` ranks ≥ the old one), `add_event(...)` (INSERT OR IGNORE), queue helpers, `spend_today()`, `add_spend()` |
| `ae.py` | argparse CLI dispatching to the modules below |
| `hook.py` | `ae hook` — PostToolUse(Artifact) + SessionStart handler |
| `watch.py` | `ae watch` (monitor loop) and `ae pass` (one pass now) |
| `history.py` | browser history scan |
| `transcripts.py` | incremental transcript scan |
| `thumbs.py` | headless thumbnails (`ae thumbs [--id ID] [--limit N]`) |
| `build.py` | `ae build` → DATA/explorer.html |
| `importer.py` | `ae import [--from ~/.claude/artifact-explorer]` (reads only) |
| `describe.py` | `ae launch-describer` (watcher side), `ae ingest-list FILE`, `ae set-desc ID TEXT`, `ae pending [--owned-only] [--json]`, `ae status [--json]` |
| `ae open` | opens explorer.html with `webbrowser` (in `ae.py`) |

## Schema (`explorer.db`)

```sql
artifacts(id TEXT PRIMARY KEY,   -- the id in claude.ai/artifact/<id>, or the uuid in claude.ai/code/artifact/<uuid>
  uuid TEXT, url TEXT, title TEXT, kind TEXT, owned INTEGER,  -- 1 mine, 0 shared with me, NULL unknown
  creator TEXT, sharing TEXT, size INTEGER,
  created REAL, modified REAL, last_accessed REAL, last_access_by TEXT,   -- unix seconds; by = browser|agent
  version TEXT, seq INTEGER, local_path TEXT,
  description TEXT, desc_source TEXT, desc_status TEXT,  -- source rank: title<publish<describer<import ; status ok|pending|skipped
  thumb TEXT, thumb_source TEXT, thumb_status TEXT,      -- thumb = path relative to DATA; source headless|chrome|import ; status ok|pending|failed|none
  first_seen REAL, updated REAL)
events(artifact_id TEXT, ts REAL, kind TEXT, source TEXT, session_id TEXT, cwd TEXT, repo TEXT, detail TEXT,
  UNIQUE(artifact_id, ts, kind, source))   -- kind publish|visit|agent_read|agent_open ; source hook|transcript|browser:<name>|import
spend(day TEXT PRIMARY KEY, usd REAL, runs INTEGER)
state(key TEXT PRIMARY KEY, value TEXT)    -- JSON values: cursors, last pass, describer run, share windows
```
Repos, "created by" and "last accessed" are derived at build time from `events` + `artifacts`.
Created = earliest publish event, else `created`. Modified = latest publish, else `modified`.

## Data flow

1. **Publish hook** (`hooks.json`: PostToolUse matcher `Artifact`, and SessionStart). Payload (verified 2026-11-10):
   `tool_input` {action, url?, file_path, description?, label?}; `tool_response` {url, path, artifact_id (uuid), title, seq, version, owned, updated}.
   On publish: upsert (owned from response, title, url, uuid, local_path, version, seq, description from tool_input with
   source `publish`, thumb_status pending), add a `publish` event (session_id, cwd, repo). On read/open: an `agent_read`/`agent_open` event.
   The hook itself never opens the database (a watcher pass can hold the write lock longer than the 10 s hook timeout; seen in
   the 2026-11-10 end-to-end run): it writes the payload to `DATA/inbox/hooks/<ns>-<pid>.json` and detaches `ae ingest-hooks`,
   which records every spooled payload under `ingest.lock`, then thumbnails new publishes and rebuilds. Every watcher pass also
   runs `ingest-hooks` first, so a lost child only delays a row. It must finish in <1 s and print nothing. Exit 0 always.
   SessionStart: when shared rows have `desc_status=pending`, print one line of `additionalContext`:
   "Artifact Explorer: N shared artifacts are waiting for a description. Run /artifact-explorer:refresh to describe them."
2. **Watcher** (`monitors/monitors.json` → `sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" watch --data "${CLAUDE_PLUGIN_DATA}"`).
   It loops forever. Every 30 s it checks whether `now - state.last_pass ≥ watch_interval`. If so, it takes `watch.lock` (on failure it skips), runs
   one pass, and records `last_pass`. One pass runs: `ingest-hooks` → history (if on) → transcripts (if on) → `thumbs --limit 5` → `build` if anything changed
   → `launch-describer`. **It prints nothing to stdout, ever** (every stdout line would become a message to Claude). Errors go to watch.log.
   Many sessions each run a copy; the lock and `last_pass` make one pass per interval in total.
3. **History** (`browser_history`): Chromium-family `History` (Chrome, Chromium, Edge, Brave, Arc, Vivaldi; all profiles) and Firefox
   `places.sqlite`, on macOS, Linux and Windows. Copy the file and its `-wal` to a temp dir, then query urls like `https://claude.ai/%artifact/%`.
   Incremental per profile (cursor = max visit time). A `visit` event per visit, `source=browser:<name>`. Unknown ids are inserted
   with the page title (strip " - Claude"; ignore "Claude", "Claude Artifact" and "not found"), `owned` NULL and `desc_status` pending.
   Visits inside the share-harvest windows (`state.share_windows`) are skipped.
4. **Transcripts** (`transcript_reads`): `~/.claude/projects/*/*.jsonl`, incremental by (path → byte offset, inode). Pair `tool_use` name `Artifact`
   with its result line's `toolUseResult`. Publish gives a `publish` event (source `transcript`, fills created/version/local_path for
   publishes made before install). read/open gives `agent_read`/`agent_open`. It reads only lines containing `"Artifact"` or `toolUseResult`.
5. **Thumbnails**: find a browser (`AE_BROWSER` env, else known paths per OS for Chrome/Chromium/Edge/Brave, else PATH names).
   Wrap the local file in a skeleton when it is a fragment (no `<html`): doctype, charset, viewport, body margin 0, white bg.
   Run `--headless=new --disable-gpu --hide-scrollbars --mute-audio --no-first-run --user-data-dir=<tmp> --window-size=1280,800
   --force-device-scale-factor=0.5 --virtual-time-budget=4000 --screenshot=<out>`, with a 45 s timeout. Write to `thumbs/<id>.png`. No browser,
   or a failure, sets thumb_status `failed` and the page draws a title card. Rows without a local file get `none` (Chrome option later).
6. **Describer** (`ae launch-describer`, called by the watcher). The probe (2026-11-10) showed that reading an artifact made by someone else always asks
   for consent, even with allow rules. So **the background run describes only own artifacts**. It launches only when all of these hold: some row has
   `desc_status=pending` and `owned` is not 0, today's spend is below `describe_daily_cap`, no describer started in the last `watch_interval`, and
   `claude` is on PATH. Command: `claude --bg --model <describe_model> --name "artifact-explorer describer" "/artifact-explorer:refresh describe-only"`
   with cwd = the watcher's cwd. When the data dir ends in `-inline` (the plugin was loaded with `--plugin-dir`), the command also gets
   `--plugin-dir <plugin root>`, or the new session would not know the skill. Its spend is recorded up front as an estimate: $0.05 a run + $0.01 per row it may describe (at most 10 rows a run).
   Shared rows wait for an interactive `/artifact-explorer:refresh` (SessionStart reminder).
7. **Build**: `page/template.html` with a `/*__DATA__*/` placeholder replaced by JSON {config, rows, generated}. Write to a temp file, then rename.
   Rows: apply `[filter]`, then overrides, then category rules. Thumbs are relative paths `thumbs/<file>`.
   Columns: Title, Category, Created by, Sharing, Modified, Last accessed, Created, Size, Description, Repos, Open.
   Page: search box, category chips with counts, sortable columns, card/table toggle, light/dark tokens, works at 375 px, no external scripts.

## config.toml

```toml
[page]
title = "Artifact Explorer"
accent = "#0f6b5c"
columns = ["title","category","created_by","sharing","modified","last_accessed","created","size","description","repos","open"]

[[categories]]            # first match wins; keywords are case-insensitive regexes tried on title + description
name = "Reports"
keywords = ["report","audit","review","post-?mortem","summary"]
# ... Plans, Dashboards, Decks, Docs, Personal; Uncategorised is the fallback

[filter]                  # empty = show everything
include_repos = []        # show only rows whose repos intersect this list (rows with no repo are hidden when it is set)
exclude_repos = []
exclude_ids = []
include_shared = true

[overrides."<id>"]        # per artifact
category = "Plans"
description = "..."
hidden = false
```
`examples/filter-by-repo.toml` shows `include_repos = ["artifact-explorer"]`.

## Skills

- `setup`: show the current options (from `/config`), write DATA/config.toml from defaults when it is missing (or offer `ae import` when
  `~/.claude/artifact-explorer/meta.json` exists), run the refresh skill in full mode, show allow rules for `Bash(sh */artifact-explorer/*/bin/ae *)`
  and write them to settings.json **only on yes**, then `ae open`.
- `refresh [full|describe-only]`: (1) Artifact list scope `mine` then `shared` (`limit` 200, `page_token` while a `next_page_token` is given).
  The list answers in text lines (`- (mine) TITLE — URL — updated YYYY-MM-DD`; shared lines carry no date), so it gives only url, title,
  owned and a modified date; kind, size and sharing come from the hook, transcripts and the sharing skill. Rows → `DATA/inbox/list.json` →
  `ae ingest-list` (a date never lowers a more precise modified time). Reads use `path: "index.html"` so the page lands in a file, and the
  describer gets `ae excerpt FILE` (≤3000 visible characters), never the whole page. (2) `ae pending --json`. Own rows: Artifact read → `describer` agent → `ae set-desc`.
  Shared rows: only in full mode (each read asks for consent once). (3) `ae thumbs`, `ae build`. (4) Report counts.
  `allowed-tools`: Artifact, Agent, Read, Write, Bash(sh *bin/ae *).
- `open`: `ae open`.
- `screenshots` (when `chrome_screenshots` is on): Claude in Chrome captures rows with thumb_status none/failed.
- `sharing` (when `share_harvest` is on): Claude in Chrome reads each owned artifact's Share dialog → `ae set-sharing`; records the window in `state.share_windows`.
- `agents/describer.md`: model `haiku`, fixed. `${user_config.*}` is not substituted in agent frontmatter (probe 2026-11-10:
  model_not_found), so `describe_model` sets only the background session's `--model`; an interactive refresh uses `haiku`. Input: the artifact read text. Output: one plain sentence, ≤ 200 chars.

## Privacy

Only Claude's own calls leave the machine: Artifact list/read against your claude.ai account and the describer model. No telemetry.
