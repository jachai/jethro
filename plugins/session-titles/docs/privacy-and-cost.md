# Privacy and cost

## What is sent, and where

For each prompt after a session's first, one model call gets:

- the session's origin (a few words);
- the last few assistant text blocks of the main thread, about 6,000 characters at most. Tool calls,
  tool results and subagent messages are not included;
- your new prompt, cut at 2,000 characters.

On an unnamed session's first prompt, one call gets just that prompt (2,000 characters at most) to
name the session.

The call goes through your own `claude` CLI and login, to the same place your sessions already go.
session-titles itself has no server, no telemetry and no network code. The CLAUDE.md and memory
files Claude Code loads for any `claude -p` run are part of the request too, as they are for every
other call you make.

Locally it stores origins, focus labels, recent titles and a log of title changes in
`~/.claude/session-titles/`. It doesn't keep prompts or transcript text. The one exception is fast
mode: it writes the new prompt to `pending/<session id>.json` for its background worker, and the
worker deletes that file as soon as it reads it.

## Cost

One call with the default `haiku` model, measured on Claude Code 2.1:

| | Per call |
|---|---|
| Cost | about $0.0003 to $0.0015 (more on the first call of a cache window) |
| Time | about 1 to 3 s |

That's roughly 10 to 50 cents per 1,000 prompts. On a subscription the calls count toward your plan
usage like any other `claude -p` run. `--max-budget-usd 0.05` caps any single call.

To spend less:

- leave `skip_print_mode` on, so scripted `claude -p` runs make no calls;
- turn busy sessions off with `session-titles off <id>`;
- use the smallest model you have access to.

## Turning it off

- One session: `session-titles off <id>` (or `current` from inside it).
- Everywhere, plugin: `/plugin disable session-titles`, or uninstall it.
- Everywhere, plain hook: `./install.sh --uninstall`. Add `--purge` to delete the state and the log
  as well.
