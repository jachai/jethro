---
name: screenshots
description: Capture thumbnails with Claude in Chrome for artifacts that have no thumbnail (no local file, or the headless capture failed). Only when the chrome_screenshots option is on. Use when asked to "take artifact screenshots" or "fill in missing thumbnails".
allowed-tools: Bash(sh *bin/ae *), Bash(sh "*/bin/ae" *), Read, mcp__claude-in-chrome__*
---

# Screenshots

Below, `AE` means `sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" --data "${CLAUDE_PLUGIN_DATA}"`. Write each `AE` command out in full in every Bash call; never store it in a shell variable (zsh does not split `$AE` into words, so `$AE pending` fails).

1. Check the option. It is `chrome_screenshots` in `/config` (plugins). If it is off, say so and stop. Do not turn it on yourself.
2. Run `AE rows --json --thumb-status none` and `AE rows --json --thumb-status failed`. Together these are the rows without a thumbnail. If there are none, say so and stop. Take at most 10.
3. Make sure the Claude in Chrome tools are available. If not, say the extension is needed and stop.
4. Start the visit window, so the watcher does not count these page loads as your own visits: run `AE share-window start`. Open ONE new tab for the run. Remember its tab id. Do not touch tabs you did not open.
5. For each row: navigate your tab to the row's `url`, wait for the page to load, then take a screenshot with the Chrome tools.
6. Saving the image. The Chrome tools return a screenshot to you. They do not promise to write a file. A page cannot capture another origin's pixels (a canvas capture in `javascript_tool` is blocked cross-origin), so do not try it. Use only a Chrome tool that saves an image to disk (for example a `gif_creator` export or a screenshot with a save path), and save it as `${CLAUDE_PLUGIN_DATA}/thumbs/<id>.png`. After saving, check with `Read` that the file exists, then run `AE set-thumb ID thumbs/ID.png` so the page uses it.
7. If no available tool can save a file, say this plainly to the user: "Claude in Chrome can show me the screenshot but cannot save it to disk, so I could not make thumbnails." Do not invent a workaround. List the ids that still have no thumbnail. The page keeps drawing a title card for them.
8. When done, close the tab you opened (and every tab you opened). Then run `AE share-window end` and `AE build`.
9. Report: how many thumbnails saved, how many not.
