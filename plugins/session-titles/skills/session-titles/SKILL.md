---
name: session-titles
description: Explain or change this session's two-part title ("<origin> · <focus>") set by the session-titles hook — rename the origin, turn retitling off or on for a session, show why a title says what it says, read the title log, or check the install. Use when asked "why is my session called X", "rename the origin", "change the session title", "stop retitling this session", "turn session titles off here", "session titles aren't updating", or "check session-titles".
---

# Session titles

The session-titles hook keeps every session titled `<origin> · <focus>`:

- **origin**: the name the session started with. That's the name you gave it (`--name`, or `/rename`
  at any time) or, for an unnamed session, a short name a small model wrote from its first prompt.
  It only changes when you rename the session.
- **focus**: a few plain words for what the session is doing now, rewritten on every prompt by a small
  model from the latest assistant messages and the new prompt.

Below, `st` means the `session-titles` command. If it isn't on PATH, use
`python3 <this skill's base directory>/../../scripts/session_titles.py`. Inside a session, the
session id is `$CLAUDE_CODE_SESSION_ID`, and the CLI accepts `current` for it.

## What the user can ask

**"Why is this session called X?"** Run `st show current`. Report the origin, the focus and the last
few titles in one or two lines. If the origin came from the first prompt, say so; the user can
replace it.

**"Rename the origin" / "call this session Y".** The quickest way is for the user to type
`/rename Y`: the hook takes a name the user sets as the new origin and keeps adding the focus after it.
If the user wants it done for them, run `st set-origin current Y` and tell them it shows on the next
prompt. You can't apply a title mid-turn; Claude Code only accepts a new title when a prompt is
submitted.

**"Stop retitling this session" / "turn it back on".** `st off current` or `st on current`. Off
leaves the title as it is now. To stop it everywhere, the user disables the plugin
(`/plugin disable session-titles`) or runs `./install.sh --uninstall` for a plain install.

**"Titles aren't updating" / "check it".** Run `st doctor` and `st log -n 20 current`, then match what
you see to the table below. Don't run `doctor` more than once per question; it makes one real model
call.

| What you see | Meaning and fix |
|---|---|
| `doctor` says hook not registered | Not installed for this config dir. Install the plugin, or run `./install.sh`. Sessions started before the install keep the hooks they started with; restart them. |
| `installed twice` | Plugin and plain hook both active, so every prompt runs twice. Run `./install.sh --uninstall` and keep the plugin. |
| `model call failed` or `timed out` in the log | The title model call failed. The title keeps its last focus. Check `claude -p "hi"` works; set the `model` option to an alias the user has access to. |
| No log lines for the session at all | The session is a `claude -p` run (skipped on purpose), or it is turned off (`st show` says `retitle off`). |
| The focus lags one prompt behind | The `mode` option is `fast`. That is the trade-off for no wait; `fresh` (the default) waits about 2 to 5 seconds per prompt for a current focus. |
| The focus just repeats the origin | It's dropped on purpose and the previous focus is kept. Nothing to fix. |

## Settings

Plugin installs: `/plugin` → session-titles → configure, or pipe a JSON object of values to
`claude plugin configure session-titles --values-stdin` (without the flag it shows the current values).
Plain installs: `~/.claude/session-titles/config.json`. Environment variables `SESSION_TITLES_<NAME>`
override both. The options are `mode` (`fresh` or `fast`), `model` (default `haiku`), `separator`
(default `·`, always spaced), `max_focus_chars` (default 40), `focus_style` (one extra instruction, for example
"always name the PR number") and `skip_print_mode` (default true).

## Rules for you

- Never edit Claude Code's own session files to change a title. The hook output is the only path.
- Don't paste the user's prompts or transcripts into an issue or anywhere outside the machine when
  debugging; `st log` lines are enough.
