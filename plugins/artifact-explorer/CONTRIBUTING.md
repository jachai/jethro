# Contributing

Issues and pull requests are welcome. Artifact Explorer uses only the Python 3.9+ standard library
(TOML is read with the vendored `scripts/vendor/tomli`). Please add no runtime dependencies.

## Tests

```sh
python -m unittest discover -s tests -v
sh bin/ae --version
claude plugin validate .
```

Every test builds its own data folder in a temp dir. Nothing may read your real `~/.claude` or call
a real model. New tests should do the same.

## Privacy

Never commit real artifact ids, titles, history, transcripts or paths from your own machine. Use made-up fixtures.

## Releases

1. Move the notes in `CHANGELOG.md` under a new version heading.
2. Bump `VERSION` in `scripts/ae.py` and `version` in `.claude-plugin/plugin.json`.
3. Push a `vX.Y.Z` tag. The release workflow runs the tests, checks the versions match and creates a GitHub release.
