---
name: setup
description: First-time setup for Artifact Explorer. Asks every permission it needs once, up front, then creates the config file, imports an older catalog when asked, runs a first refresh and a describer test, and opens the page. Use when asked to "set up artifact explorer" or after installing the plugin.
allowed-tools: Artifact, Agent, Read, Write, Bash(sh *bin/ae *), Bash(sh "*/bin/ae" *), Bash(test *), Bash(mkdir *), Bash(cp *), Bash(ls *)
---

# Setup

Below, `AE` means `sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" --data "${CLAUDE_PLUGIN_DATA}"`. Write each `AE` command out in full in every Bash call; never store it in a shell variable (zsh does not split `$AE` into words, so `$AE pending` fails). Go in order. Keep each message short.

0. Check. Run `AE doctor` and show its output to the user as it is, in a code block. Then say in one line which version this window runs (the `running:` line).
   - If it prints `MISMATCH` or `NOTE`, stop setup here: tell the user to run the command it names (or open a new window), then run `/artifact-explorer:setup` again in a new Claude Code window.
   - If the `data folder:` line says `NOT a fresh install`, say so plainly: "This is not a fresh install: the catalog already has N artifacts, first seen DATE. Setup keeps them." Never call this setup fresh, new or first in that case.
   - If it says `fresh`, you may say this is a fresh install.
1. Everything asked once (0.2.11). After this step setup asks nothing more and the plugin runs on its own: topics, descriptions, categories and thumbnails are applied automatically. Run `AE allow-rule` and `test -f ~/.claude/artifact-explorer/meta.json && echo yes || echo no` first. Then send ONE message that lists, as short bullets:
   - The permission rules, when `AE allow-rule` printed `missing:` or `add:` lines (when it printed only `present:`, say instead "The permission rules are already in ~/.claude/settings.json; nothing added."): the rules on its `add:` lines, which go in `permissions.allow` in `~/.claude/settings.json`. Without them each `ae` call asks for approval and the background describer never starts.
     ```
     Bash(sh "*/artifact-explorer/*/bin/ae" *)
     Bash(sh */artifact-explorer/*/bin/ae *)
     ```
   - The first refresh reads your claude.ai artifact list and your own artifacts with the Artifact tool (claude.ai may show its own consent prompt for those reads), describes the newest 100 (`[window] first_load` in config.toml), and starts a one-row background describer test that costs a few cents of the daily cap (`describe_daily_cap`, $1.00).
   - Artifacts shared with you by others are not read: claude.ai asks consent for each such read, so they show "shared with you, not read" until you run `/artifact-explorer:refresh` yourself.
   - The options, changed any time in `/config` (plugins): `watch_interval`, `browser_history` and `transcript_reads` (on: they read local Chrome history and Claude Code transcripts to find artifacts, nothing leaves the machine), `chrome_screenshots` and `share_harvest` (off), `describe_model`, `describe_daily_cap`.
   - Only when the meta.json check printed yes: a catalog from the pre-plugin Artifact Explorer exists in `~/.claude/artifact-explorer`; `ae import` only reads it.
   Ask: "OK to add the rules and go ahead? (yes/no)" (add "and import the old catalog" when there is one). Only on a clear yes, read `~/.claude/settings.json`, add the missing rules to `permissions.allow` (create the keys if missing, keep everything else), write it back and run `AE allow-rule` again: say "Added the rules (checked)" on `present:`, or that they did not take on `missing:`. On anything but yes, do not touch the file, say the describer stays off until the rules are added, and continue with the steps below.
2. Config file. Run `test -f "${CLAUDE_PLUGIN_DATA}/config.toml" && echo yes || echo no`. If no, run `mkdir -p "${CLAUDE_PLUGIN_DATA}"`, then read `${CLAUDE_PLUGIN_ROOT}/config/default.toml` and write its content to `${CLAUDE_PLUGIN_DATA}/config.toml`. Tell the user they can edit that file for categories, topics, filters and overrides, and that `${CLAUDE_PLUGIN_ROOT}/examples/` has samples. If it exists, leave it alone.
3. Import. Only when step 1 found the old catalog and the user said yes there: run `AE import`. Do not ask again.
4. First refresh. Do the full mode of the `refresh` skill (follow `${CLAUDE_PLUGIN_ROOT}/skills/refresh/SKILL.md`, full mode). Then run `AE topics` and show it. Tell the user in one line that topics are applied automatically (a topic used on artifacts with two different titles joins the Topic filter), and that they can change them: `[[topics]]` entries in `config.toml` for their own, `[topic_promote.rename]` to rename, and `ae topics --hide NAME` to hide one.
5. Describer test. Only when the rule is present: run `AE launch-describer --test` without asking (step 1 covered it) and show its one line. Tell the user that `AE status` shows a `last describer run:` line once it ends (a few minutes), and that a line with `refused:` means a permission is missing.
6. Open the page: run `AE open`. Tell the user the watcher runs while a Claude Code session is open and keeps the page fresh.
