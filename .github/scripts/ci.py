#!/usr/bin/env python3
"""CI helper for the jethro suite (Python 3.9+, no dependencies).

  ci.py changed BASE            JSON list of plugins whose folder changed since BASE (all when BASE is empty)
  ci.py test PLUGIN             run one plugin's checks with this interpreter
  ci.py version-check BASE      fail when a changed plugin's plugin.json version was not bumped
  ci.py release-check TAG       TAG is <plugin>--v<version>; check it against plugin.json and the script
  ci.py notes TAG               print that version's CHANGELOG section
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Per-plugin checks, carried over from each plugin's old test.yml.
PLUGINS = {
    "session-titles": {
        "unittest": ["-X", "dev", "-W", "error::ResourceWarning"],
        "pyflakes": ["scripts", "tests"],
        "sh": ["install.sh", "bin/session-titles"],
        "json": ["hooks/hooks.json", "examples/settings-snippet.json"],
        "version": "scripts/session_titles.py",
    },
    "session-sweep": {
        "unittest": [],
        "pyflakes": ["skills", "scripts", "tests"],
        "sh": ["install.sh"],
        "json": [],
        "version": "skills/close-stale-sessions/scripts/session_sweep.py",
    },
    "session-guide": {
        "unittest": [],
        "pyflakes": ["skills", "scripts", "tests"],
        "sh": ["install.sh"],
        "json": ["hooks/hooks.json", "examples/settings-snippet.json"],
        "version": "skills/session-guide/scripts/peek.py",
        "install_roundtrip": "skills/session-guide/SKILL.md",
    },
}
BUNDLE = "jethro"  # plugin.json only; no checks beyond the version bump


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT)] + list(args), check=True, capture_output=True, text=True).stdout


def all_plugins():
    return sorted(p.name for p in (ROOT / "plugins").iterdir() if (p / ".claude-plugin/plugin.json").is_file())


def changed(base):
    if not base or set(base) == {"0"}:
        return all_plugins()
    names = set()
    for line in git("diff", "--name-only", base, "HEAD").splitlines():
        parts = line.split("/")
        if len(parts) > 2 and parts[0] == "plugins":
            names.add(parts[1])
    return sorted(n for n in names if (ROOT / "plugins" / n / ".claude-plugin/plugin.json").is_file())


def version_at(rev, name):
    try:
        return json.loads(git("show", "%s:plugins/%s/.claude-plugin/plugin.json" % (rev, name)))["version"]
    except subprocess.CalledProcessError:
        return None


def run(cmd, cwd, env=None):
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd), check=True, env=env)


def test(name):
    if name == BUNDLE:
        return
    cfg, d = PLUGINS[name], ROOT / "plugins" / name
    py = sys.executable
    run([py] + cfg["unittest"] + ["-m", "unittest", "discover", "-s", "tests", "-v"], d)
    if (d / "scripts/demo.py").is_file():
        run([py, "scripts/demo.py"], d)
    run(["uvx", "pyflakes"] + cfg["pyflakes"], d)
    for s in cfg["sh"]:
        run(["sh", "-n", s], d)
    for j in [".claude-plugin/plugin.json"] + cfg["json"]:
        json.loads((d / j).read_text())
    for skill in sorted((d / "skills").glob("*/SKILL.md")):
        head = skill.read_text().split("\n")
        assert head[0] == "---", skill
        front = head[1:head.index("---", 1)]
        assert "name: " + skill.parent.name in front, skill
        assert any(l.startswith("description: ") for l in front), skill
    if cfg.get("install_roundtrip"):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CLAUDE_CONFIG_DIR=tmp)
            run(["sh", "install.sh"], d, env)
            assert (Path(tmp) / cfg["install_roundtrip"]).is_file()
            run(["sh", "install.sh", "--uninstall"], d, env)
            assert not (Path(tmp) / Path(cfg["install_roundtrip"]).parent).exists()


def version_check(base):
    bad = []
    for name in changed(base):
        old, new = version_at(base, name), version_at("HEAD", name)
        print("%s: %s -> %s" % (name, old, new))
        if old is not None and old == new:
            bad.append(name)
    if bad:
        sys.exit("bump the version in plugins/<name>/.claude-plugin/plugin.json for: " + ", ".join(bad))


def split_tag(tag):
    m = re.fullmatch(r"(.+)--v(\d+\.\d+\.\d+)", tag)
    if not m:
        sys.exit("tag must look like <plugin>--v<version>: " + tag)
    return m.group(1), m.group(2)


def release_check(tag):
    name, version = split_tag(tag)
    d = ROOT / "plugins" / name
    plugin = json.loads((d / ".claude-plugin/plugin.json").read_text())["version"]
    script = PLUGINS.get(name, {}).get("version")
    found = subprocess.run([sys.executable, script, "--version"], cwd=str(d), check=True,
                           capture_output=True, text=True).stdout.split()[-1] if script else plugin
    print("tag=%s plugin=%s script=%s" % (version, plugin, found))
    if not version == plugin == found:
        sys.exit("tag, plugin.json and script versions differ")


def notes(tag):
    name, version = split_tag(tag)
    out, on = [], False
    for line in (ROOT / "plugins" / name / "CHANGELOG.md").read_text().splitlines():
        if line.startswith("## ["):
            on = line.startswith("## [%s]" % version)
            continue
        if on:
            out.append(line)
    text = "\n".join(out).strip()
    if not text:
        sys.exit("no CHANGELOG section for " + version)
    print(text)


if __name__ == "__main__":
    cmd, arg = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
    if cmd == "changed":
        print(json.dumps(changed(arg)))
    elif cmd == "test":
        test(arg)
    elif cmd == "version-check":
        version_check(arg)
    elif cmd == "release-check":
        release_check(arg)
    elif cmd == "notes":
        notes(arg)
    else:
        sys.exit(__doc__)
