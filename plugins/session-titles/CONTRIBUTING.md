# Contributing

Issues and pull requests are welcome. session-titles is one script, `scripts/session_titles.py`,
using only the standard library and running on Python 3.9+. Please keep it that way: no runtime
dependencies and no new modules.

## Tests

The tests need [uv](https://docs.astral.sh/uv/), which fetches the Python versions for you. CI runs the
oldest and newest supported versions on Ubuntu and macOS:

```sh
uv run --no-project --python 3.9 python -X dev -W error::ResourceWarning -m unittest discover -s tests
uv run --no-project --python 3.14 python -X dev -W error::ResourceWarning -m unittest discover -s tests
uvx pyflakes scripts tests
python3 scripts/demo.py
claude plugin validate --strict .
```

Every test builds its own Claude config dir in a temp folder and points `SESSION_TITLES_CLAUDE` at a
fake `claude` that answers from a queue, so nothing reads your real `~/.claude` or calls a real model.
New tests should do the same.

## Changing the prompts or the shaping rules

The prompts are `FOCUS_SYSTEM` and `ORIGIN_SYSTEM`. The cleanup is in `clean_label()` and
`shape_focus()`, and the origin rules are in `resolve_origin()` and `on_prompt()`. A change needs a test
showing a reply or title that now comes out differently, and an update to
[docs/how-it-works.md](docs/how-it-works.md). When in doubt, keep the previous title: a stale focus
costs less than a wrong one.

To try a prompt change for real, use `--link` so the hooks run your clone:

```sh
./install.sh --link
session-titles log -n 20     # after a few prompts in a new session
```

## Privacy

Never commit real session data: no transcripts, state files, session names, prompts or paths from your
own machine. This applies to tests, issues and examples. Use `scripts/demo.py` or made-up fixtures
instead.

## Releases

1. Move the `Unreleased` notes in `CHANGELOG.md` under a new version heading.
2. Bump `__version__` in `scripts/session_titles.py` and `version` in `.claude-plugin/plugin.json`.
3. Push a `vX.Y.Z` tag. The release workflow runs the tests, checks the versions match and creates a
   GitHub release with that version's changelog notes. Plugin users get the update through
   `/plugin marketplace update`.
