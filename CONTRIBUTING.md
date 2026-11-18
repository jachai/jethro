# Contributing

Each plugin lives in `plugins/<name>/` with its own `README.md`, `CHANGELOG.md` and tests. See the plugin's own
`CONTRIBUTING.md` for how it is built.

- **Bump the version** in `plugins/<name>/.claude-plugin/plugin.json` with every change under that folder (and the
  script's `__version__` where it has one). CI fails a change that does not, because users only get an update
  when that string changes.
- **Run the checks** for a plugin with `python3 .github/scripts/ci.py test <name>`, and the manifests with
  `claude plugin validate . --strict`.
- **Release** one plugin at a time: add its `CHANGELOG.md` section, then `claude plugin tag plugins/<name> --push`.
  The tag `<name>--v<version>` triggers the release workflow.
- **No plugin depends on another**, except the `jethro` bundle.
