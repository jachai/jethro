# Changelog

## [0.2.0] - 2026-11-15
- More fun to answer. Answering a question pops the check mark and throws a small burst of confetti from the
  option; the last question gets a big two-sided burst (plain canvas, no library, stops itself in ~2 s,
  never blocks a tap).
- Visuals animate as a card opens: bars grow, split bars sweep in, flow / steps / tree items and table rows
  appear one by one, before/after columns slide in from each side, numbers count up (bars, split legends,
  opening stats).
- Cards slide and tilt between questions (the other way going back), options lift on hover (hover devices
  only, so no sticky lift on a phone), the progress bar moves with a small overshoot and bumps on each answer.
- Milestones: a badge at halfway ("3 of 6, halfway there") and at the end ("6 of 6, all done"); the summary
  rows and an all-done check animate in.
- No celebration or milestone for answers restored from this browser or arriving from the store; each
  milestone shows once per visit.
- Everything is off under `prefers-reduced-motion` (the reduce block now also zeroes transition delays) and
  with `#reduce-motion` on the URL (test toggle).
- Fix: the answers summary no longer overflows sideways at 390 px when long option names are answered (the
  answer column wraps).

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
