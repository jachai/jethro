# Contributing

Issues and pull requests are welcome. Artifact Explorer uses only the Python 3.9+ standard library
(TOML is read with the vendored `scripts/vendor/tomli`). Please add no runtime dependencies.

## Tests

```sh
python -m unittest discover -s tests -v
sh bin/ae --version
claude plugin validate ../..
```

Every test builds its own data folder in a temp dir. Nothing may read your real `~/.claude` or call
a real model. New tests should do the same.

## Privacy

Never commit real artifact ids, titles, history, transcripts or paths from your own machine. Use made-up fixtures.

## Releases

Artifact Explorer is released from the [jethro](https://github.com/jachai/jethro) suite repo, as the tag `artifact-explorer--vX.Y.Z`.

1. Move the notes in `CHANGELOG.md` under a new version heading.
2. Bump `VERSION` in `scripts/ae.py` and `version` in `.claude-plugin/plugin.json`.
3. Open the bump as a pull request to `main` of `jachai/jethro`.
4. After the bump PR is merged, the maintainer tags the merge commit (`artifact-explorer--vX.Y.Z`) and pushes the tag.

The maintainer tags and releases. Agents and other contributors open the PR and stop there: they never merge, tag or create a release.
