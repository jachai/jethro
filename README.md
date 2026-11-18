# jethro

[![test](https://github.com/jachai/jethro/actions/workflows/test.yml/badge.svg)](https://github.com/jachai/jethro/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Claude Code plugins for running many sessions at once. One repo, one marketplace, one plugin per folder.
Named after Jethro, who told Moses to stop judging every case himself and hand the work to others
(Exodus 18).

## Install

```
/plugin marketplace add jachai/jethro
/plugin install jethro@jethro             # the whole suite
/plugin install session-titles@jethro     # or any one plugin
```

| Plugin | What it does | Folder |
|---|---|---|
| session-titles | Titles each session `<origin> · <focus>`: where it started, plus a few words for what it is doing now | [plugins/session-titles](plugins/session-titles) |
| session-sweep | Closes background sessions that are done, handed off or abandoned, after asking about the unclear ones | [plugins/session-sweep](plugins/session-sweep) |
| session-guide | Makes one session the guide across parallel sessions: one ledger, relayed decisions, handoffs | [plugins/session-guide](plugins/session-guide) |
| jethro | Installs the three plugins above | [plugins/jethro](plugins/jethro) |

[claude-top](https://github.com/jachai/claude-top) (`uv tool install claude-agents-top`), a live list of your
sessions, stays in its own repo.

## Moving from the old repos

Each plugin used to have its own marketplace (`session-titles@session-titles` and so on). Those installs keep
working. To move, uninstall the old one first, then install `<plugin>@jethro`: with both enabled, Claude Code
drops one copy's hooks. Options are stored under the full id, so set them again after the move. If you used a
plugin's `install.sh`, run `./install.sh --uninstall` from that clone first.

## Updates

Marketplaces other than Anthropic's do not auto-update unless you turn that on. Run
`/plugin marketplace update jethro` to pick up new versions. Each plugin has its own version and
`CHANGELOG.md`, and its own release tags (`<plugin>--v<version>`).

## Requirements

Claude Code with background sessions, Python 3.9+ on macOS or Linux. No other dependencies. These are terminal
tools: plugins with a `bin/` folder are not installed by claude.ai or Cowork.
