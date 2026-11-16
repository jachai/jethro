---
name: build
description: Turn a set of open questions for Ops, a PM, a customer or any one decider into a one-card-at-a-time claude.ai artifact (recommendation first, a visual per question, answers saved in the artifact's shared db). Use for "turn these questions into a walkthrough", "question walkthrough", "fancy questions", "make a decisions page for Ops", "interview page", or a new round after collecting answers.
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
7. **Pre-share check: can a reader's answer reach you?** A reader whose share level is too low can open the
   page but every save is refused (the page now says so in a red banner, but the answers still never reach
   you). Run ONE write as a Contributor-level reader, then remove it. Load `ArtifactData` if it is deferred:
   ```
   ArtifactData action:"set" url:<url> collection:"answers" doc_id:"qw-preshare-check" as_level:"interact"
     data:{"qid":"qw-preshare-check","note":"pre-share check; safe to delete"}
   ArtifactData action:"delete" url:<url> collection:"answers" doc_id:"qw-preshare-check" if_version:<version from the set>
   ```
   The set must succeed. If it reads as "not found" or is refused, the page was published without the `db`
   capability or with rules that need more than `interact`: republish to the same url with the step 6
   capabilities and run the check again. Write `preshare: ok <ISO time>` into `state.md`. If you cannot make
   this call yourself (a guided session, no claude.ai access), hand the author the two calls above verbatim.
8. **Check before done.** Hand the URL and the data dir to the `walkthrough-checker` agent. It returns at most
   10 lines. Fix what it reports in the data, rebuild, and republish to the SAME url only while nobody has
   opened the page yet (otherwise publish a new one and say why). Don't call the page ready until the checker
   passes.
9. **Report** the link, the card count and minutes (from `qw stats`), what is not verified, the pre-share
   result, and this one line for the author, word for word with the reader's name filled in:
   **How to share:** open the page, click Share, add <reader> as **Contributor** (not Viewer or Commenter),
   then send the link; Viewers and Commenters can open it but their answers never reach you.
   Then: write `shared: <ISO time>` into `state.md` once the author says it is sent, and
   `/fancy-questions:collect <url>` once the answers are in.

## Who can save answers (the platform's sharing levels; do not guess other names)

| Share menu level | db level | Saves answers? |
|---|---|---|
| Owner, Editor | admin | yes |
| **Contributor** (on the person, or on general access) | interact | **yes**: share at this level |
| Commenter, Viewer | view | no: the page opens, every save is refused |
| Anyone signed in from outside your organization (link or email invite) | view | no, whatever level you pick |
| Signed out | none | no |

A reader outside the organization cannot save on this page at any level: ask them for the "Copy all my
answers" text instead (every card and the summary have the button), or have the author invite them by email
as Editor while the page has no share link (an outside Editor holds `admin` only then).

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
