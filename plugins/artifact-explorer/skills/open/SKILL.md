---
name: open
description: Open the Artifact Explorer page in the default browser. Use when asked to "open the artifact explorer", "show my artifacts", or "open the artifact catalog".
allowed-tools: Bash(sh *bin/ae *)
---

# Open

Run:

```sh
sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" --data "${CLAUDE_PLUGIN_DATA}" open
```

It builds the page first if it does not exist, opens it, and prints its path. Tell the user the path in one line. If the command fails, show its last error line and suggest `/artifact-explorer:setup`.
