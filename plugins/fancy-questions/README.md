# question-walkthrough

A Claude Code plugin that turns a set of open questions for someone (Ops, a PM, a customer) into a
claude.ai artifact they walk through one card at a time: the recommendation first, a visual per question,
options plus free text, answers saved in the artifact's shared db, a summary to copy out.

The page is a shipped template. A session writes only question data (`cards/*.json`), and `qw build`
checks it and produces the page.

## Install (private repo)

The repo is cloned with your own git credentials: run `gh auth login` and `gh auth setup-git` (or use SSH).
`GITHUB_TOKEN` alone is not enough.

```
/plugin marketplace add jachai/question-walkthrough
/plugin install question-walkthrough@question-walkthrough
```

## Use

- `/question-walkthrough:build`: interview, write cards, build, publish, check.
- `/question-walkthrough:collect <artifact url>`: read the answers back into `answers.md`.
