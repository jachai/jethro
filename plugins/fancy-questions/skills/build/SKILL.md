---
name: build
description: Turn a set of open questions for Ops, a PM, a customer or any one decider into a one-card-at-a-time claude.ai artifact (recommendation first, a visual per question, answers saved in the artifact's shared db). Use for "turn these questions into a walkthrough", "question walkthrough", "make a decisions page for Ops", "interview page", or a new round after collecting answers.
allowed-tools: Bash(sh *bin/qw *)
---

# Build a question walkthrough

You write small JSON files; the plugin's template draws the page. Never read or edit `page/template.html` or
`page/app.js`: they already follow the artifact design rules (themes, phone width, fonts), so you do NOT load
the artifact-design or artifact-capabilities skills for this page.

CLI (all commands print errors only, one line on success):
```
sh "${CLAUDE_PLUGIN_ROOT}/bin/qw" new   <dir>   # start a data dir from the minimal example
sh "${CLAUDE_PLUGIN_ROOT}/bin/qw" lint  <dir>   # check only
sh "${CLAUDE_PLUGIN_ROOT}/bin/qw" stats <dir>   # cards, minutes, urgent, visuals per kind
sh "${CLAUDE_PLUGIN_ROOT}/bin/qw" build <dir>   # check + write <dir>/index.html
```
Data dir: `walkthrough/<slug>/` in the current project unless the user names one.

## Steps

1. **Ask only what you can't work out.** Who answers (the audience, a first name), the page title, where the
   questions are (a doc, Linear tickets, a list in chat), and last round's link if there was one. Take the rest
   from the source. One short message; skip it if the request already says all this.
2. **Facts helper.** If the questions depend on numbers, records or tickets, spawn ONE helper (sonnet) to read
   the sources and write `<dir>/facts.md`: one line per number, each marked `verified` (read from prod, a
   dashboard or the ticket) or `not verified` (estimated, made up for the example). Ask it for a summary of at
   most 20 lines back. Read only the lines a card needs. Never put a number on a card that is not in facts.md.
3. **Read the contract once:** `reference/schema.md` (fields, rules, limits) and `reference/visuals.md`
   (one example per visual kind, and which kind fits which question).
4. **Write the data.** `qw new <dir>` if the dir does not exist, then replace the example:
   - `page.json`: slug (keys the saved answers; new slug per round), title, audience, eyebrow, lead, sections,
     lastRound, stats.
   - `cards/NN-<section>.json`: about 5 cards per file, files sorted in the order cards should appear.
   - Each card: the question in the reader's words (no plan codes, no internal jargon), the recommendation
     first, today vs after, one worked example with real numbers from facts.md, a visual, 2-5 options with the
     recommended one first, and `{"tone":"discuss"}` as the last option.
   - Card count: 1-15 is one page; 16-40 needs sections and `urgent` on the ones that block work; over 40
     `qw build` refuses, so split into rounds (one page per round, ask the user which go first).
5. **Build.** `qw build <dir>`. Fix every numbered error in the DATA (never the template) and rebuild until it
   prints `built ... · N KB · ...`. Warnings: fix "no visual"; a size warning over 150 KB usually means a big
   data:image, so link it or shrink it.
6. **Publish a NEW artifact** with the Artifact tool: `file_path: <dir>/index.html`, `icon: "checklist"`,
   `capabilities: {"db": {}, "user": {"scopes": ["profile"]}}`, a one-sentence description. Never republish
   over last round's page: its answers live in its own db. Write the URL into `<dir>/state.md`.
7. **Check before done.** Hand the URL and the data dir to the `walkthrough-checker` agent. It returns at most
   10 lines. Fix what it reports in the data, rebuild, and republish to the SAME url only while nobody has
   opened the page yet (otherwise publish a new one and say why). Don't call the page ready until the checker
   passes.
8. **Report** the link, the card count and minutes (from `qw stats`), what is not verified, and the next step:
   `/question-walkthrough:collect <url>` once the answers are in.

## Writing rules that made the approved pages work

- One screen per card on a phone: question ≤ 240 chars, recommend ≤ 240, option sub ≤ 200. Lint enforces them.
- The recommendation is a plain sentence a reader can say yes to ("Yes. A head that moves still counts as
  sold."), not "Option A".
- `today` says what happens now, in one or two sentences; `after` says what changes if they pick the
  recommendation.
- The example is a real case (customer, place, amounts) from facts.md, with a link when there is one.
- Mark anything not read from the source with `facts[].verified: false`: the page shows it as "not checked".
- A multi-part card (`parts`) is for questions that only make sense together; the reader cannot move on until
  every part is answered.
- "Tick some" options (`picks`) need `min` ≥ 1 unless an empty list is a valid answer.

## Handing off

The data files are the state. If context runs high, write `<dir>/state.md` (what is done, the URL, what is
left) and start a fresh session with: "Continue the question walkthrough in <dir>: read state.md, run qw stats".
