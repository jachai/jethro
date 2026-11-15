# Changelog

## [0.1.1] - 2026-11-15
- Page fails loud: when answers cannot reach the author (no db, listener error, store silent 10 s, a refused
  set, or `user.can("data.write") === false`) a red banner names the author and says the answers are NOT
  reaching them; every failed save repeats it. New optional `page.author` (defaults to `discussWith`).
- "Copy all my answers" on every card, the opening (once answered) and the summary: plain text, one line per
  question and part, ready to paste in Slack or email.
- Build skill: pre-share check (one `ArtifactData set` at `as_level: "interact"`, then delete), a share-level
  table (share at Contributor; Viewer, Commenter and outside-org readers cannot save) and a "How to share" line.
- Collect skill: 0 answers some hours after sharing says so and asks for the "Copy all my answers" text; parses
  that text; skips the pre-share check doc.
- Fixes found building the Nov 15 Ops page: a part needs no visual of its own (no warning, no empty figure);
  the progress bar now really hides on the opening screen; no toast before the reader does anything.

## [0.1.0] - 2026-11-10
- Scaffold: plugin manifest, marketplace, `qw` CLI stub, CI.
- Page template (the approved 11-10 page made generic: `page/template.html` + `page/app.js`), visual kinds
  bars, split, flow, tree, beforeAfter, steps, table, image, pair, stack, svg (sanitized).
- `qw build|lint|stats|new` with the data contract in `scripts/lint.mjs`; minimal example; 15 tests.
- Skills `build` and `collect`; `walkthrough-checker` agent (sonnet); reference `schema.md` and
  `visuals.md` (examples linted by the tests).
- Examples `ops-11-10` (golden rebuild of the approved page) and `synthetic-30`.
