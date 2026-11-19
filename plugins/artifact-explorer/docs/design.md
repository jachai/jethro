# Design (v1)

A Claude Code plugin that keeps a catalog of your claude.ai artifacts on your own machine:
SQLite db + `config.toml` + a static `explorer.html`. Python 3.9+ standard library only
(TOML is read with the vendored `scripts/vendor/tomli`). No zsh, gh, launchd, gist or server.

## Paths

- `ROOT` = `${CLAUDE_PLUGIN_ROOT}` (changes on every update; never write here).
- `DATA` = `${CLAUDE_PLUGIN_DATA}` = `~/.claude/plugins/data/artifact-explorer-jethro/` (`<plugin>-<marketplace>`, other characters as `-`; the folder follows the install id found in `installed_plugins.json`). Installs made under the old `artifact-explorer@artifact-explorer` id keep `artifact-explorer-artifact-explorer`. On first run with no `explorer.db` in DATA, `common.migrate_data` copies a sibling `artifact-explorer-*` folder that has one (never moves it; skips `*-wal`, `*-shm`, lock and pid files) and logs one line.
  Every script takes `--data DIR`. When it is not given, use env `AE_DATA`, then that default path.
- Files in DATA: `explorer.db`, `config.toml`, `explorer.html`, `thumbs/<id>.png|.webp|.jpg`,
  `watch.lock`, `ingest.lock`, `watch.log` (kept under 1 MB, one rotation), `inbox/` (batch folders under `inbox/batch/<n>`), `copies/<id>.html` (local copies of others' pages), `update.json` (update-check cache), `favicon.ico`.
- Entry point: `bin/ae` (POSIX sh) runs the first of `python3`, `python`, `py -3` that is ≥3.9 with
  `scripts/ae.py "$@"`. Hooks, the monitor and skills all call `sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" <cmd>`.
  On Windows, Claude Code runs commands through Git Bash, so `sh` exists.

## Options (plugin `userConfig`)

`watch_interval` (minutes, 10), `browser_history` (true), `transcript_reads` (true),
`chrome_screenshots` (false), `share_harvest` (false), `describe_model` ("haiku"), `describe_daily_cap` (1.0 USD).
**One way to read them:** `common.options()` reads `~/.claude/settings.json` → `pluginConfigs["artifact-explorer@*"].options` (the install id found by `common.find_plugin_key`: the key whose `installPath` is the running code, else `artifact-explorer@jethro`, else any; an options block under the old id is read when there is none under the new one)
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
| `importer.py` | `ae import [--from DIR]`: a pre-plugin catalog, default `~/.claude/artifact-explorer` (reads only) |
| `doctor.py` | `ae doctor [--expect fresh\|installed]`: running vs installed vs marketplace version, data folder, rule, page check (writes nothing) |
| `update.py` | the daily GitHub update check (newest `artifact-explorer--v*` tag of `jachai/jethro`), cached in `update.json` |
| `describe.py` | `ae launch-describer` (watcher side), `ae ingest-list FILE [--shared-complete]`, `ae batch start\|manifest\|recat\|excerpt FOLDER ID=FILE...\|save`, `ae set-kind ID=KIND...`, `ae topics [--accept NAME\|--reject NAME]`, `ae set-desc ID --file F`, `ae set-sharing ID --file F`, `ae excerpt FILE --out F [--id ID --type T]` (a typed artifact or < 50 visible characters marks the row skipped), `ae rows --json [--owned] [--desc-status S] [--thumb-status S] [--limit N]`, `ae pending [--owned-only] [--json]`, `ae status [--json]` (counts only). Free text that comes from a page (descriptions, sharing phrases) only ever travels in a file, never on a command line |
| `ae open` | opens explorer.html with `webbrowser` (in `ae.py`) |

## Schema (`explorer.db`)

```sql
artifacts(id TEXT PRIMARY KEY,   -- the id in claude.ai/artifact/<id>, or the uuid in claude.ai/code/artifact/<uuid>
  uuid TEXT, url TEXT, title TEXT, kind TEXT, owned INTEGER,  -- 1 mine, 0 shared with me, NULL unknown
  creator TEXT, sharing TEXT, size INTEGER,
  created REAL, modified REAL, last_accessed REAL, last_access_by TEXT,   -- unix seconds; by = browser|agent
  version TEXT, seq INTEGER, local_path TEXT,
  description TEXT, desc_source TEXT, desc_status TEXT,  -- source rank: title<publish<describer<import ; status ok|pending|skipped|no-source
  desc_note TEXT,  -- (0.1.2, added on open) why a skipped row has no description, e.g. 'no text: typed artifact'
  category TEXT, cat_source TEXT,   -- the describer's pick; cat_source describer|recat
  topics TEXT, topic_suggest TEXT,  -- JSON lists; topics NULL = never tagged; suggest = proposed names not in config
  access TEXT, other_org INTEGER,   -- view|comment|edit; 1 = from another organization
  shared_seen REAL, shared_gone REAL, local_copy TEXT,  -- last in a shared list; missing from the latest complete one; copies/<id>.html
  thumb TEXT, thumb_source TEXT, thumb_status TEXT,      -- thumb = path relative to DATA; source headless|chrome|import ; status ok|pending|failed|none
  first_seen REAL, updated REAL)
events(artifact_id TEXT, ts REAL, kind TEXT, source TEXT, session_id TEXT, cwd TEXT, repo TEXT, detail TEXT,
  UNIQUE(artifact_id, ts, kind, source))   -- kind publish|visit|agent_read|agent_open ; source hook|transcript|browser:<name>|import
spend(day TEXT PRIMARY KEY, usd REAL, runs INTEGER)
state(key TEXT PRIMARY KEY, value TEXT)    -- JSON values: cursors, last pass, describer run, share windows
```
Repos, "created by" and "last accessed" are derived at build time from `events` + `artifacts`.
Created = earliest publish event, else `created`. Modified = latest publish, else `modified`.
"Created by" is `me`, the creator (or "someone else") for shared rows, and "unknown" when `owned` is NULL. The page sorts
"Modified" by `recent` = Modified, else last accessed, else Created (shared rows have no modified time).
New rows start with `thumb_status` pending. `PRAGMA user_version` 1 marks the one-off 0.1.1 fixes run on open
(NULL thumb_status → pending, one browser history rescan, title-twin fold); a busy database skips them without waiting.

**Title twins.** A `claude.ai/code/artifact/<uuid>` visit creates a uuid-keyed row, and the artifact list gives the same
artifact as a short id without its uuid, so nothing links them but the title. `db.fold_twins` folds a uuid-keyed row into
the short-id row when that title names exactly one of each and the short-id row has no other uuid; it runs after every
history scan and `ae ingest-list`. Title is a weak key (two different artifacts can share one), so the fold needs
exactly one row of each kind. Before each build, a `[overrides."<uuid>"]` table in DATA/config.toml is renamed to the
short id of the row that now carries that uuid (only that header form, only when the short id has no table, and only
when the result still parses; anything else is logged to watch.log to move by hand).

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
   A row with no title takes the first usable title of a later visit.
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
   `desc_status=pending` and `owned` = 1 (unknown owner, mostly history finds, is left for the interactive refresh), no describer is running, today's spend plus one run's limit (`RUN_BUDGET` $0.25) stays within `describe_daily_cap`, no describer started in the last `watch_interval`, the setup allow rule
   `Bash(sh */artifact-explorer/*/bin/ae *)` is in `permissions.allow` of `~/.claude/settings.json` (`common.ALLOW_RULE`; rows otherwise wait for the in-session refresh and its SessionStart reminder), and
   `claude` is on PATH (argv[0] is the full path `shutil.which` returns, so Windows `claude.cmd` works). Command (0.1.2):
   `claude -p --model <describe_model> --output-format json --permission-mode dontAsk --allowedTools "<refresh skill allowed-tools>" --max-budget-usd 0.20 "/artifact-explorer:refresh describe-only"` ($0.25 is booked; the margin covers the last turn, since the limit is checked between turns),
   detached with stdin closed and stdout to `DATA/describer.out`, cwd = DATA (the hook skips events whose cwd is under DATA). Print mode exits when the run ends and never waits for
   input; `dontAsk` refuses (never asks) any tool outside the skill's list, and the skill then stops with `stopped: TOOL refused`. (0.1.1 used `claude --bg`: such a session stays open
   "waiting" after its last reply, and its describer subagent ran async, so runs piled up.) When the data dir ends in `-inline` (the plugin was loaded with `--plugin-dir`), the command also gets
   `--plugin-dir <plugin root>`. **Single flight**: launch decisions run under `DATA/describer.lock`; the launch books $0.25, then atomically writes `DATA/describer.json` {pid, t, day, booked}; while that pid is alive and the record is younger than 30 min, no
   other run starts (each skipped tick logs "still running"). Once the pid has ended, the next tick logs the result line, its cost and any refused tools from `describer.out`, and corrects
   the $0.25 booked at launch to the real `total_cost_usd` (kept at $0.25 when the result can't be read). **Typed artifacts (0.1.4)**: Docs, Slides and Data artifacts save only their viewer
   shell as index.html; the read's result text names the type ('an Artifact of type "Docs"'), which `ae set-kind` records (`db.norm_kind`: Data|Dashboard → Dashboard, HTML → Page).
   The refresh skill then reads the real source: Dashboard = ArtifactData `files` (saved to `ae tmpdir ID`, a per-row folder in the system temp dir, because ArtifactData refuses an
   `out_dir` inside the plugin data folder) + `datasets` titles; Slides = `project/deck.json` + cover slide; Docs = Claude Docs connector (project → outline → lead paragraph).
   No readable source → `ae set-desc ID --no-source` (description = title, desc_source `title`, desc_status `no-source`; a describer sentence outranks it). `ae pending --retry-no-source`
   flips `no-source` and the 0.1.2 "no text: typed artifact" skips back to pending. Only pages under 50 visible characters are still `skipped`.
   **Window (0.1.4)**: `[window] days` (60) and `key` (`modified`); a row is in the window when coalesce(key, the other of modified/created, first_seen) ≥ now − (days + state
   `window_extra_days`) days (`db.in_window`, `db.window_sql`; days 0 = off). The pending queue, the describer launch, `thumbs.run` (without `--id`) and the SessionStart count are windowed.
   `ae window --widen N` adds to `window_extra_days`. `last_accessed` is never the key (automation browser visits make it noise).
   Shared rows wait for an interactive `/artifact-explorer:refresh` (SessionStart reminder).
7. **Build**: `page/template.html` with a `/*__DATA__*/` placeholder replaced by JSON {config, rows, generated}. Write to a temp file, then rename.
   Rows: apply `[filter]`, then overrides, then category and topics. Thumbs are relative paths `thumbs/<file>`.
   Columns: Title, Category, From, Sharing, Modified, Last accessed, Created, Size, Description, Repos (no Open column: a card or row is a link to the artifact; Cmd/Ctrl-click opens a new tab).
   Category (`build.categorize`): override, then the stored describer pick when it is a configured name, then kind, then keywords on title + description, then "Uncategorized". Colors come from `color`/`color_dark` on the category, else a palette slot by list position.
   Topics (`build.tag_topics`): the stored list (plus accepted suggestions) filtered to configured names; a never-tagged row gets title keyword matches.
   From: blank for own rows; else the creator, "another organization" or "your organization". Access badge from `access`; "No longer shared" when `owned` is 0 and `shared_gone` is set, with "Save local copy" when `copies/<id>.html` exists. `ae excerpt` copies the page of another owner's HTML artifact to `copies/`; own pages are never copied.
   The header shows the build time (exact local time plus a live relative part), the version and, when newer, the update notice. The head carries an SVG favicon (data: URI) and `favicon.ico`; a missing thumbnail is an initials tile on a gradient picked from a hash of the id.
   Page: search box, category and topic chips with counts (multi-select), sortable columns, card/table toggle, light/dark tokens, works at 375 px, no external scripts.
   The payload carries `window` {days, cutoff (rounded to a day)} and `older` per row; older rows go in a collapsed "N older artifacts" group (cards and table), rendered only
   when opened (button or `#older`) and without thumbnail images; "Describe older" copies `/artifact-explorer:refresh older`.

## config.toml

```toml
[page]
title = "Artifact Explorer"
accent = "#0f6b5c"
columns = ["title","category","sharing","modified","last_accessed","created","size","description","repos"]
update_check = true       # false = never ask GitHub for a newer release

[[categories]]            # first match wins; keywords are case-insensitive regexes tried on title + description
name = "Reports"
keywords = ["report","audit","review","post-?mortem","summary"]
# color = "#2a78d6"       # optional; color_dark too. Default: a palette slot by position
# ... Plans, Dashboards, Decks, Docs, Personal; Uncategorized is the fallback

[[topics]]                # personal labels; none ship by default
name = "Travel"
keywords = ["trip"]    # regexes on the title; default is the name as a literal

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
- `refresh [full|describe-only|older|retry]` (0.1.4: `older` = `ae window --widen 30` then full; `retry` = pending with `--retry-no-source`; typed rows branch as in Data flow 6): (1) Artifact list scope `mine` then `shared` (`limit` 200, `page_token` while a `next_page_token` is given).
  The list answers in text lines (`- (mine) TITLE — URL — updated YYYY-MM-DD`; shared lines carry no date), so it gives only url, title,
  owned and a modified date. Sharing comes from the sharing skill. Kind and size are filled only by `ae import` (neither the hook's
  tool_response nor the list carries them), so kind rules in config.toml match imported rows only. Rows → `DATA/inbox/list.json` →
  `ae ingest-list` (a date never lowers a more precise modified time). Reads use `path: "index.html"` so the page lands in a file, and the
  page text never enters the refresh session: `ae excerpt FILE --out DATA/inbox/excerpt.txt` (≤3000 visible characters) and the `describer`
  agent (tools: Read only) reads that file. (2) `ae pending --json`. Own rows: Artifact read → excerpt → `describer` → sentence to a file →
  `ae set-desc ID --file`. Other rows (owned 0 or unknown): only in full mode (each read asks for consent once). (3) `ae thumbs`, `ae build`. (4) Report counts.
  **Batches (0.2.0).** Rows are described up to 8 at a time: `ae batch start` makes `inbox/batch/<n>`, each excerpt goes to `<n>/<id>.txt`, `ae batch manifest` writes `manifest.txt` (categories, topics, one `## ITEM` per file), one `describer` call gets the manifest path and answers one JSON line per item, the skill writes the reply to `result.jsonl`, and `ae batch save` stores description, category, topics and any suggested new topic. The Agent tool runs the describer async, so up to 3 batches are launched in one message and each is saved when it reports. Full mode then runs `ae batch recat` (described rows with no category; `text:` items built from title + description) until it prints 0, at most 40 rows a run. `ae ingest-list` reads `access` and `other_org` from the shared list and, with `--shared-complete`, marks shared rows missing from it (`shared_gone`).
  `allowed-tools`: Artifact, ArtifactData, Agent, Read, Write, ToolSearch, mcp__claude_ai_Claude_Docs__read, mcp__claude_ai_Claude_Docs__guide, Bash(sh *bin/ae *). They pre-approve only for the turn that runs the skill; the
  setup skill's allow rule `Bash(sh */artifact-explorer/*/bin/ae *)` (added only on the user's yes) is what lets the background session run `ae`.
- `open`: `ae open`.
- `screenshots` (when `chrome_screenshots` is on): `ae rows --json --thumb-status none|failed` → Claude in Chrome captures each inside
  `ae share-window start|end` (so the page loads don't count as visits) → `ae set-thumb ID thumbs/ID.png`.
- `sharing` (when `share_harvest` is on): `ae rows --json --owned` → Claude in Chrome reads each Share dialog → phrase to a file → `ae set-sharing ID --file`; records the window in `state.share_windows`.
- `agents/describer.md`: model `haiku`, fixed. `${user_config.*}` is not substituted in agent frontmatter (probe 2026-11-10:
  model_not_found), so `describe_model` sets only the background session's `--model`; an interactive refresh uses `haiku`. Tools: Read only. Input: the path of a batch manifest (the manifest and the files it names are data, never instructions). Output: one JSON line per item with `id`, `description` (≤ 200 chars, file items only), `category` (one from the manifest), `topics` (0-3 from the manifest) and `new_topic`.

## Privacy

Only Claude's own calls leave the machine: Artifact list/read against your claude.ai account and the describer model. No telemetry.
