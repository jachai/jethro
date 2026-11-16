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
3. Open the bump as a pull request to `main` and fill in the checklist from `.github/pull_request_template.md`.
4. After the bump PR is merged, tag the merge commit on `main` and push the tag:

   ```sh
   git fetch origin && git checkout main && git pull --ff-only
   git tag vX.Y.Z $(git rev-parse HEAD)   # the merge commit of the bump PR
   git push origin vX.Y.Z
   ```

   The release workflow runs the tests, checks the versions match and creates a GitHub release.

The maintainer tags and releases. Agents and other contributors open the PR and stop there: they never merge, tag or create a release.
