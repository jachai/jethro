---
name: setup
description: First-time setup for Artifact Explorer. Shows the options, creates the config file, offers to import an older catalog, runs a first refresh, offers a permission rule, and opens the page. Use when asked to "set up artifact explorer" or after installing the plugin.
allowed-tools: Artifact, Agent, Read, Write, Bash(sh *bin/ae *), Bash(test *), Bash(mkdir *), Bash(cp *), Bash(ls *)
---

# Setup

Below, `AE` means `sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" --data "${CLAUDE_PLUGIN_DATA}"`. Go in order. Keep each message short.

1. Options. Tell the user the plugin has these options, which they can change in `/config` (plugins): `watch_interval`, `browser_history`, `transcript_reads`, `chrome_screenshots`, `share_harvest`, `describe_model`, `describe_daily_cap`. Say that `chrome_screenshots` and `share_harvest` are off, and what each one does in one line. Do not change them.
2. Config file. Run `test -f "${CLAUDE_PLUGIN_DATA}/config.toml" && echo yes || echo no`. If no, run `mkdir -p "${CLAUDE_PLUGIN_DATA}"`, then read `${CLAUDE_PLUGIN_ROOT}/config/default.toml` and write its content to `${CLAUDE_PLUGIN_DATA}/config.toml`. Tell the user they can edit that file for categories, filters and overrides, and that `${CLAUDE_PLUGIN_ROOT}/examples/` has samples. If it exists, leave it alone.
3. Import. Run `test -f ~/.claude/artifact-explorer/meta.json && echo yes || echo no`. If yes, tell the user an older catalog exists there, that `ae import` only reads that folder and never changes it, and ask whether to import it. Run `AE import` only if they say yes.
4. First refresh. Do the full mode of the `refresh` skill (follow `${CLAUDE_PLUGIN_ROOT}/skills/refresh/SKILL.md`, full mode).
5. Permission rule. Without it, each `ae` call asks for approval. Show this rule and where it goes:

   ```
   Bash(sh */artifact-explorer/*/bin/ae *)
   ```

   It goes in `permissions.allow` in `~/.claude/settings.json`. Ask: "Add this rule? (yes/no)". Only on a clear yes, read `~/.claude/settings.json`, add the rule to `permissions.allow` (create the keys if missing, keep everything else, skip it if already there), and write the file back. On anything else, do not touch the file.
6. Open the page: run `AE open`. Tell the user the watcher runs while a Claude Code session is open and keeps the page fresh.
