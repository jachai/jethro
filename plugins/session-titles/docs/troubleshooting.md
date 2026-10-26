# Troubleshooting

Start with these two commands. `doctor` makes one real model call, and `--no-model` skips it.

```sh
session-titles doctor
session-titles log -n 30          # or: session-titles log -n 30 <session id prefix>
```

## The title never changes

- **The session started before you installed.** A session keeps the hooks it started with. Send a
  prompt in a new session, or restart the old one.
- **Not registered.** `doctor` says `hook registered (neither plugin nor plain hook found)`. Install
  it with `/plugin install session-titles@session-titles`, or run `./install.sh` from a clone.
  `doctor` reads the `settings.json` of `$CLAUDE_CONFIG_DIR` (default `~/.claude`), so check it's
  pointed at the config you use.
- **It's a `claude -p` run.** Those are skipped on purpose. Set `skip_print_mode` to `false` to
  include them.
- **The session is turned off.** `session-titles show <id>` prints `retitle off`. Run
  `session-titles on <id>`.
- **The model call fails.** The log says `model call failed rc=…` with the error. Check that
  `claude -p --model haiku "hi"` works in a terminal. If your account can't use that alias, set the
  `model` option to one it can.

## The title is wrong

- **The origin is a bad guess from the first prompt.** Type `/rename <better name>` in the session.
  A name you set becomes the origin, and the focus keeps being added after it.
- **The focus is vague or off.** It only sees the last few assistant messages and your new prompt.
  Add a `focus_style` instruction (see [examples/custom-prompt.md](../examples/custom-prompt.md)) or
  try a bigger `model`.
- **The focus is one prompt behind.** You're in `fast` mode. Switch `mode` to `fresh`.
- **The focus didn't change after a prompt.** The model's reply only repeated the origin, or the call
  failed, so the previous focus was kept. The log shows which.
- **The title went back to the bare origin after a resume.** The SessionStart hook isn't registered.
  Reinstall; both hooks come with the plugin and with `install.sh`.

## Prompts feel slow to start

In `fresh` mode each prompt waits for one small model call, about 1 to 3 seconds (up to 25 seconds
before it gives up). Options:

- `mode: fast`: no wait, and the focus lags one prompt behind.
- A faster `model`. The default `haiku` is already the fastest alias.
- Check the log for `timed out`. Timeouts usually mean a network or login problem, not the hook.

## Everything runs twice

`status` and `doctor` warn `installed twice` when both the plugin and a plain hook are registered.
Keep one: run `./install.sh --uninstall` from the clone to remove the plain hook.

## Reading the log

```
2026-11-02 10:14:03 3f9a2c1d origin generated 'search api rate limiting'
2026-11-02 10:14:03 3f9a2c1d title -> 'search api rate limiting'
2026-11-02 10:19:47 3f9a2c1d title -> 'search api rate limiting · token bucket per API key'
2026-11-02 10:31:12 3f9a2c1d origin <- 'db index fix' (title was 'db index fix')
2026-11-02 10:40:55 3f9a2c1d model call timed out
```

Each line starts with the first 8 characters of the session id. `origin <-` means the hook adopted a
name you set. `focus cached` lines come from the fast-mode worker.

## Still stuck

Open an issue with the bug template. Include `session-titles doctor --no-model` output and the log
lines for the session, with prompts and names redacted.
