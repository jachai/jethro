# fancy-questions

A Claude Code plugin that turns a set of open questions for someone (Ops, a PM, a customer) into a
claude.ai artifact they walk through one card at a time: the recommendation first, a visual per question,
options plus free text, answers saved in the artifact's shared db, a summary to copy out.

The page is a shipped template. A session writes only question data (`cards/*.json`), and `qw build`
checks it and produces the page.

## Install

```
/plugin marketplace add jachai/jethro
/plugin install fancy-questions@jethro
```

fancy-questions is part of the [jethro](../../README.md) suite. Installed it earlier as
`fancy-questions@fancy-questions`? Uninstall that first, then install `fancy-questions@jethro`.
While the jethro repo is private, the clone uses your own git credentials: run `gh auth login` and
`gh auth setup-git` (or use SSH). `GITHUB_TOKEN` alone is not enough.

## Use

- `/fancy-questions:build` (or "turn these questions into a walkthrough for Ops"): asks only what it
  can't work out, has one helper gather the facts into `facts.md`, writes `walkthrough/<slug>/page.json` and
  `cards/*.json`, runs `qw build`, publishes a NEW artifact (shared db + viewer profile), and has the
  `walkthrough-checker` agent look at it in Chrome before calling it ready.
- `/fancy-questions:collect <artifact url>`: reads the saved answers into `answers.md` and
  `decided.json`, which seeds "decided last round" on the next page.

The CLI works on its own too (Node 20+, no dependencies):

```
bin/qw new walkthrough/my-round     # start from the minimal example
bin/qw lint walkthrough/my-round    # check only
bin/qw stats walkthrough/my-round   # cards, minutes, urgent, visuals per kind
bin/qw build walkthrough/my-round   # check + write walkthrough/my-round/index.html
```

- Data contract: `skills/build/reference/schema.md` (enforced by `scripts/lint.mjs`).
- Visual kinds with one example each: `skills/build/reference/visuals.md`.
- Examples: `skills/build/examples/minimal` (2 cards) and `synthetic-30` (30 cards, every visual kind).
- Limits: 40 cards per page (split into rounds), 150 KB page warning.

## Develop

`node --test` and `claude plugin validate . --strict` before every commit. The suite CI (`.github/scripts/ci.py test fancy-questions`) runs
them on macOS and Ubuntu.
