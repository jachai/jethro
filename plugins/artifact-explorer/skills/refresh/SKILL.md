---
name: refresh
description: Refresh the Artifact Explorer catalog from your claude.ai artifact list, describe artifacts that have no description, then rebuild the page. Takes "describe-only" (background run, own artifacts only) or nothing for a full refresh. Use when asked to "refresh my artifacts", "describe my artifacts", or when SessionStart says artifacts are waiting for a description.
argument-hint: "[describe-only]"
allowed-tools: Artifact, Agent, Read, Write, Bash(sh *bin/ae *)
---

# Refresh

Argument: `$ARGUMENTS`. If it is `describe-only`, this is the background mode. Anything else is the full mode.

Below, `AE` means `sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" --data "${CLAUDE_PLUGIN_DATA}"`.

## Background mode (`describe-only`)

You run unattended. Do not ask questions. Do not read any artifact owned by someone else: reading one always asks for consent and nobody is there to answer. End quietly, with one short line.

1. Run `AE pending --owned-only --json`. It prints the rows that need a description. If there are none, say "nothing to describe" and stop.
2. Take at most 10 rows. For each row:
   1. Read the artifact with the Artifact tool, action `read`, using the row's `url` (or `id`). Never pass `out_dir`; the default is right.
   2. If the read is refused or fails, skip the row and go on.
   3. Call the `describer` agent with the read text as its whole prompt. It returns one sentence.
   4. If the sentence is `unreadable` or empty, skip the row.
   5. Run `AE set-desc ID "SENTENCE"`. Escape double quotes in the sentence, or drop them.
3. Run `AE build`.
4. Reply with one line: `described N of M`.

## Full mode

1. Own list. Call the Artifact tool, action `list`, scope `mine`. Follow every page until none is left. Keep each row's fields as the tool returned them (id, title, kind, size, created, modified, sharing, url).
2. Shared list. Call the same action with scope `shared`, all pages.
3. Write the rows with the Write tool to `${CLAUDE_PLUGIN_DATA}/inbox/list.json`, as a JSON array. Add `"scope": "mine"` or `"scope": "shared"` to each row. If the tool returned no rows, write `[]`.
4. Run `AE ingest-list "${CLAUDE_PLUGIN_DATA}/inbox/list.json"`. It sets owned, title, kind, size, dates and sharing.
5. Run `AE pending --json`. These rows need a description.
6. Own rows (`owned` is not 0): read, call the `describer` agent, run `AE set-desc ID "SENTENCE"`, exactly as in background mode steps 2.1 to 2.5. No limit of 10 here, but stop after 40 and say how many are left.
7. Shared rows (`owned` is 0): tell the user once that each read of a shared artifact asks for consent, and how many there are. Then read and describe them the same way. If the user refuses a read, skip that row and do not ask again for it.
8. Run `AE thumbs` and then `AE build`.
9. Run `AE status` and report in three lines or fewer: rows in the catalog, rows described this run, rows still waiting.

Reads never pass a custom `out_dir`. Never run `AE` commands other than the ones above.
