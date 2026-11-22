# Changelog

## Unreleased
- Phone width, summary: the table no longer runs off the screen when cards carry ticket ids. Below 560px a row
  shows the id and the answer on one line with the question under them, and an id breaks only when it is wider
  than its own space.
- Phone width, `table` visual: numbers, dates and short ids stay on one line, and words no longer break in the
  middle. Only a token over 16 characters (a record id, a range) may break, after its own dash or slash first.
  A table too wide for the phone scrolls inside its box.

## [0.2.2] - 2026-11-19
- Moved into the [jethro](https://github.com/jachai/jethro) suite: install with `/plugin marketplace add jachai/jethro`
  and `/plugin install fancy-questions@jethro`. Its own marketplace.json and CI are gone; the suite's CI runs
  `node --test` for it. License is MIT, like the rest of the suite.
- The `ops-11-10` example (a real page) is removed; the build test now covers `minimal` and `synthetic-30`.

## [0.2.1] - 2026-11-16
- Renamed from question-walkthrough to fancy-questions: the repo (github.com/jachai/fancy-questions), the
  marketplace and the plugin. Install with `/plugin marketplace add jachai/fancy-questions` and
  `/plugin install fancy-questions@fancy-questions`; the skills are now `/fancy-questions:build` and
  `/fancy-questions:collect`. The `qw` CLI, the page and its saved data are unchanged.
- Bigger fireworks: a card's burst is about twice as large (70 pieces, faster, ~1.5 s); the last card adds six
  firework shells that rise and burst into rings of sparks over the two-sided confetti (~3.5 s in all).
- Sound, made in the browser (WebAudio, no files): a short pop for each answered card; a pop, then a whistle
  and a bang for each shell, timed to the fireworks, on the last one. It only plays after the reader's own tap.
- A mute button in the top bar (speaker icon); this browser remembers the choice (`qw-sound-v1`). No sound and
  no button under `prefers-reduced-motion` or `#reduce-motion`.
- Banner wording: a refused save (`invalid_argument`) no longer says for certain that the reader can only view
  the page, because the platform uses that code for malformed writes too. If the platform said the reader
  can write, the banner says "the last save was refused". If it said nothing, the banner says the page
  refused the save and that a Viewer or Commenter should ask the author for Contributor. "Only lets you view
  it" now appears only when `can("data.write")` is false.
- Build skill: the publish step points ahead to sharing at Contributor or higher.

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
