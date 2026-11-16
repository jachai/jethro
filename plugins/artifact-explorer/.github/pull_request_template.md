## What and why

<!-- One or two sentences. Link the issue or decision if there is one. -->

## Checklist

- [ ] Tests pass: `python3 -m unittest discover -s tests`
- [ ] User-visible change? Note it under the next version in `CHANGELOG.md`
- [ ] Version bump PR only: `VERSION` in `scripts/ae.py` and `version` in `.claude-plugin/plugin.json` match, and `tests/test_v020.py` expects the new version
- [ ] Page change? Checked in light and dark themes and at 390px wide
- [ ] No personal data (names, emails, catalog contents) in code, tests or screenshots

## After merge (maintainer only)

- [ ] Version bump: tag the merge commit `vX.Y.Z` and push the tag (see CONTRIBUTING, Releases). Contributors and agents do not tag or release.
