# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-10-26

### Fixed

- A session whose first prompt said nothing about the work (`ok`, `continue`, `guard ok`, a bare slash
  command, anything under 3 words and 20 characters) was named after it, giving titles like `ok`. The
  hook now names the session from the first real request in the transcript, or waits for one and
  leaves Claude Code's own name in place until then.

### Added

- README "Good to know" section: running sessions keep their hooks until restarted, install one way
  only, first titles can take a prompt or two.

## [0.1.0] - 2026-10-26

### Added

- Two-part session titles, `<origin> · <focus>`, set through the documented `sessionTitle` output of a
  UserPromptSubmit hook. The origin is the name the session started with, a name you set, or a name a
  small model writes from the first prompt. The focus is a few plain words rewritten on every prompt.
- A focus that only repeats the origin is dropped, the focus is trimmed at a word boundary with no
  ellipsis, and the previous focus is kept when the model call fails.
- `fresh` mode (default: wait for the model on every prompt) and `fast` mode (apply the previous focus
  instantly, refresh in a detached worker).
- A SessionStart hook that restores the last title on resume and prunes state older than 30 days.
- `claude -p` runs and the hook's own model calls are skipped. A message relayed from another session is
  unwrapped before the focus call.
- Options: `mode`, `model`, `separator`, `max_focus_chars`, `focus_style` and `skip_print_mode`, as
  plugin options, in `config.json`, or as `SESSION_TITLES_*` environment variables.
- The `session-titles` CLI: `status`, `show`, `log`, `set-origin`, `off`, `on` and `doctor`.
- The `session-titles` skill, the Claude Code plugin and marketplace manifests, and `install.sh` for a
  plain-hook install (idempotent, backs up `settings.json`, `--uninstall` and `--purge`).
- A unittest suite with a fake `claude`, CI on Ubuntu and macOS with Python 3.9 and 3.14,
  `claude plugin validate --strict` in CI, `scripts/demo.py`, docs, examples and issue templates.
