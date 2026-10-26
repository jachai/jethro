# session-titles

Claude Code session titles that say where a session started and what it's doing now. Every title
becomes `<origin> · <focus>`: the name the session started with, which stays put, and a few plain words
for the current work, refreshed on every prompt by a small model.

[![test](https://github.com/jachai/session-titles/actions/workflows/test.yml/badge.svg)](https://github.com/jachai/session-titles/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/jachai/session-titles/blob/main/LICENSE)

If you run several sessions at once, especially background ones in `claude agents`, their names stop
matching the work within an hour. "fix login bug" is now writing a migration, and the name doesn't say
so. session-titles keeps the name you or Claude gave it as the origin and adds what the session is
working on now, in the agents view, in `/resume` and in the terminal tab.

```
$ python3 scripts/demo.py
session 1: started without a name
  > Build a CSV export for the invoices page      invoice csv export  (first prompt: origin only)
  > tests pass? then open a PR                    invoice csv export · opening the pull request
  > watch CI and tell me when it's green          invoice csv export · PR 214 waiting on CI

session 2: started with --name 'stripe webhooks'
  > Retries are double-charging some customers,   stripe webhooks  (first prompt: origin only)
  > fix it and add a regression test              stripe webhooks · fixing the retry idempotency check
  > Stripe webhooks: all done?                    stripe webhooks · fixing the retry idempotency check
...
```

(Made-up sessions; the demo runs the real hook against a fake model.)

## Install

As a Claude Code plugin:

```
/plugin marketplace add jachai/session-titles
/plugin install session-titles@session-titles
```

Or as a plain hook, without the plugin system:

```sh
git clone https://github.com/jachai/session-titles
cd session-titles && ./install.sh     # copies the script to ~/.claude/session-titles/app (--link to use the clone)
```

`install.sh` backs up `settings.json`, adds one UserPromptSubmit and one SessionStart hook next to
your others, and links the `session-titles` command into `~/.local/bin` if that folder exists. Running
it again changes nothing. To add the hooks by hand, see
[examples/settings-snippet.json](examples/settings-snippet.json).

You need Claude Code and Python 3.9+ on macOS or Linux. There are no dependencies. New sessions pick it
up; sessions already running keep the hooks they started with.

## How it decides

**The origin** is the session's name, and it changes only when you rename the session:

- a name you set (`claude --name …`, or `/rename` at any time) becomes the origin;
- a session with no name gets one from its first prompt, at most 5 words, written by the small model;
- titles the hook set itself are recognized, so it never mistakes its own work for a rename.

**The focus** is rewritten on every prompt after the first. The model sees the origin, the last few
assistant messages and your new prompt, and returns at most 6 plain words: no paths, hashes or ticket
codes. A reply that only repeats the origin is dropped, and the previous focus stays. Long replies
are cut at a word boundary, never mid-word. If the call fails, the previous focus stays.

**Fresh or fast.** In `fresh` mode (the default) the hook waits for the model, about 1 to 3 seconds
before each prompt, so the focus matches what you just asked. In `fast` mode it applies the focus
computed after your previous prompt at once and refreshes it in the background, so the title lags one
prompt behind.

**Resume.** When you resume a session, the SessionStart hook puts back its last title. A resume that
starts a new session id (`claude --bg --resume …`) inherits the title, and the hook keeps both parts.

**Skipped.** `claude -p` runs are left alone, so scripts and scheduled jobs make no title calls.

More detail is in [docs/how-it-works.md](docs/how-it-works.md), and there are more sample titles in
[examples/titles.md](examples/titles.md).

## Configure

Plugin: `/plugin` → session-titles → configure. Plain install: `~/.claude/session-titles/config.json`.
`SESSION_TITLES_<OPTION>` environment variables override both.

| Option | Default | What it does |
|---|---|---|
| `mode` | `fresh` | `fresh` waits for a current focus; `fast` applies the previous one instantly |
| `model` | `haiku` | Model alias or name for the title calls |
| `separator` | `·` | Mark between origin and focus, always with one space each side |
| `max_focus_chars` | `40` | Longest focus, 16 to 80, trimmed at a word boundary |
| `focus_style` | (empty) | One extra instruction, e.g. "always include the PR number" ([examples](examples/custom-prompt.md)) |
| `skip_print_mode` | `true` | Leave `claude -p` runs alone |

## CLI

The plugin puts `session-titles` on PATH for Claude's Bash tool; `install.sh` links it into
`~/.local/bin`. IDs can be a prefix, or `current` inside a session.

```sh
session-titles status                # install, mode, model, titles set in the last 24 h
session-titles show [ID]             # origin, focus and recent titles of one session
session-titles log [-n N] [ID]       # the hook log, optionally for one session
session-titles set-origin ID TEXT    # replace a session's origin (shown on its next prompt)
session-titles off ID | on ID        # stop or resume retitling one session
session-titles doctor [--no-model]   # check python, claude, hook registration, state dir, one model call
```

The bundled skill answers questions like "why is this session called X?" or "stop retitling this
session" by running these for you.

## Privacy and cost

Each prompt after the first makes one small `claude -p` call through your own login. It sends the
origin, the last few assistant messages (about 6,000 characters at most) and your new prompt. It
runs with no tools and no MCP servers, and the call isn't saved as a session. With `haiku` a call costs
about $0.0003 to $0.0015, roughly 10 to 50 cents per 1,000 prompts. On a subscription the calls
count toward your plan usage. Nothing goes anywhere else; session-titles has no server or telemetry.
Details are in [docs/privacy-and-cost.md](docs/privacy-and-cost.md).

## Limitations

- The title changes only when a prompt is submitted. Claude Code has no way for a hook to rename a
  session mid-turn ([anthropics/claude-code#91468](https://github.com/anthropics/claude-code/issues/91468)).
- In `fresh` mode every prompt waits for one model call before Claude starts.
- Other sessions address a session by its title (cross-session messages, `ListAgents`). After a
  retitle, a message sent to the old bare name needs the session's ref, which the error shows.
- Keep titles short. Origins are capped at 48 characters and the focus at 40, so the agents view
  stays readable.
- It relies on the `session_title` hook input and the `sessionTitle` hook output, plus the transcript
  format. A Claude Code update could change them; [open an issue](https://github.com/jachai/session-titles/issues/new/choose)
  if titles stop updating.

## Uninstall

- Plugin: `/plugin uninstall session-titles@session-titles`.
- Plain hook: `./install.sh --uninstall`, or `./install.sh --purge` to delete the state and log too.

Titles already set stay as they are.

## Similar projects

- [claude-rename](https://github.com/sathwick-p/claude-rename) names a session once, from a Stop hook,
  by writing to the session file. session-titles keeps a fixed origin and a live focus instead, and
  uses only the documented hook output.
- Claude Code issues asking for programmatic renaming:
  [#33165](https://github.com/anthropics/claude-code/issues/33165),
  [#40346](https://github.com/anthropics/claude-code/issues/40346).

This is an independent project, not affiliated with Anthropic. See [CONTRIBUTING.md](CONTRIBUTING.md)
for tests and [CHANGELOG.md](CHANGELOG.md) for changes. MIT licensed.
