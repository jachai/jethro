---
name: setup
description: First-time setup for Artifact Explorer. Shows the options, creates the config file, offers to import an older catalog, runs a first refresh, offers a permission rule, and opens the page. Use when asked to "set up artifact explorer" or after installing the plugin.
allowed-tools: Artifact, Agent, Read, Write, Bash(sh *bin/ae *), Bash(test *), Bash(mkdir *), Bash(cp *), Bash(ls *)
---

# Setup

Below, `AE` means `sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" --data "${CLAUDE_PLUGIN_DATA}"`. Go in order. Keep each message short.

0. Check. Run `AE doctor` and show its output to the user as it is, in a code block. Then say in one line which version this window runs (the `running:` line).
   - If it prints `MISMATCH` or `NOTE`, stop setup here: tell the user to run the command it names (or open a new window), then run `/artifact-explorer:setup` again in a new Claude Code window.
   - If the `data folder:` line says `NOT a fresh install`, say so plainly: "This is not a fresh install: the catalog already has N artifacts, first seen DATE. Setup keeps them." Never call this setup fresh, new or first in that case.
   - If it says `fresh`, you may say this is a fresh install.
1. Options. Tell the user the plugin has these options, which they can change in `/config` (plugins): `watch_interval`, `browser_history`, `transcript_reads`, `chrome_screenshots`, `share_harvest`, `describe_model`, `describe_daily_cap`. Say that `chrome_screenshots` and `share_harvest` are off, and what each one does in one line. Do not change them.
2. Config file. Run `test -f "${CLAUDE_PLUGIN_DATA}/config.toml" && echo yes || echo no`. If no, run `mkdir -p "${CLAUDE_PLUGIN_DATA}"`, then read `${CLAUDE_PLUGIN_ROOT}/config/default.toml` and write its content to `${CLAUDE_PLUGIN_DATA}/config.toml`. Tell the user they can edit that file for categories, filters and overrides, and that `${CLAUDE_PLUGIN_ROOT}/examples/` has samples. If it exists, leave it alone.
3. Import. Run `test -f ~/.claude/artifact-explorer/meta.json && echo yes || echo no`. If yes, tell the user a catalog from the pre-plugin Artifact Explorer exists there, that `ae import` only reads that folder and never changes it, and ask whether to import it. Run `AE import` only if they say yes.
4. First refresh. Do the full mode of the `refresh` skill (follow `${CLAUDE_PLUGIN_ROOT}/skills/refresh/SKILL.md`, full mode).
5. Permission rule. Without it, each `ae` call asks for approval, and the background describer never starts (no one is there to approve it), so new artifacts get descriptions only when you run `/artifact-explorer:refresh` in a session. Run `AE allow-rule`.
   - If it prints `present:`, tell the user: "The permission rule is already in ~/.claude/settings.json; nothing added." Do not ask.
   - If it prints `missing:`, show this rule and where it goes:

     ```
     Bash(sh */artifact-explorer/*/bin/ae *)
     ```

     It goes in `permissions.allow` in `~/.claude/settings.json`. Ask: "Add this rule? (yes/no)". Only on a clear yes, read `~/.claude/settings.json`, add the rule to `permissions.allow` (create the keys if missing, keep everything else), and write the file back. Then run `AE allow-rule` again: on `present:` say "Added the rule (checked)"; on `missing:` say the rule did not take and the describer stays off. On anything but yes, do not touch the file and say the rule was not added.
6. Describer test. Only when the rule is present: ask "Run a one-row test of the background describer now? It books $0.25 of today's describer cap and usually costs a few cents. (yes/no)". On a clear yes, run `AE launch-describer --test` and show its one line. Tell the user that `AE status` shows a `last describer run:` line once it ends (a few minutes), and that a line with `refused:` means a permission is missing. On anything else, skip it.
7. Open the page: run `AE open`. Tell the user the watcher runs while a Claude Code session is open and keeps the page fresh.
