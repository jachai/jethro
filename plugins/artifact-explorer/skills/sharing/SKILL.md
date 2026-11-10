---
name: sharing
description: Read the sharing state of your own artifacts from the Share dialog with Claude in Chrome and record it. Only when the share_harvest option is on. Use when asked to "update artifact sharing" or "who can see my artifacts".
allowed-tools: Bash(sh *bin/ae *), mcp__claude-in-chrome__*
---

# Sharing

Below, `AE` means `sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" --data "${CLAUDE_PLUGIN_DATA}"`.

1. Check the option. It is `share_harvest` in `/config` (plugins). If it is off, say so and stop. Do not turn it on yourself.
2. Run `AE status --json`. Take the rows with `owned` of 1, at most 20, oldest `updated` first. If there are none, stop.
3. Make sure the Claude in Chrome tools are available. If not, say the extension is needed and stop.
4. Start the visit window, so the watcher does not count these page loads as your own visits: run `AE share-window start`.
5. Open ONE new tab. Remember its id. Do not touch other tabs.
6. For each row: navigate your tab to the row's `url`, open the Share dialog, and read it. Write one short plain phrase for who can see it, for example `private`, `anyone with the link can view`, `shared with 3 people`. Run `AE set-sharing ID "PHRASE"`. Do not change any sharing setting. Only read.
7. Close the tab you opened. Then run `AE share-window end` and `AE build`.
8. Report: how many rows updated, how many failed.

