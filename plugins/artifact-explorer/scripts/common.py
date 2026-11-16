"""Shared helpers: paths, options, config, logging, locks, repo names, detached runs."""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))
import tomli  # noqa: E402  (vendored, works on Python 3.9+)

PLUGIN_KEY = "artifact-explorer@artifact-explorer"
PAGE_HEARTBEAT = 3600  # the watcher rewrites an unchanged page once it is this old, so its build time shows liveness
DEFAULT_OPTIONS = {
    "watch_interval": 10,
    "browser_history": True,
    "transcript_reads": True,
    "chrome_screenshots": False,
    "share_harvest": False,
    "describe_model": "haiku",
    "describe_daily_cap": 1.0,
}


def claude_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def own_version():
    """The version of the code that is running: .claude-plugin/plugin.json next to these scripts ("" if unreadable)."""
    d = _read_json(os.path.join(ROOT, ".claude-plugin", "plugin.json"))
    return str(d.get("version") or "") if isinstance(d, dict) else ""


def installed_entries():
    """This plugin's installed_plugins.json entries (one per scope), [] when it is not installed."""
    d = _read_json(os.path.join(claude_dir(), "plugins", "installed_plugins.json"))
    ent = ((d or {}).get("plugins") or {}).get(PLUGIN_KEY) if isinstance(d, dict) else None
    if isinstance(ent, dict):
        ent = [ent]
    return [e for e in ent if isinstance(e, dict)] if isinstance(ent, list) else []


def marketplace_dir():
    """The local clone of the artifact-explorer marketplace (known_marketplaces.json), or None."""
    d = _read_json(os.path.join(claude_dir(), "plugins", "known_marketplaces.json"))
    ent = d.get("artifact-explorer") if isinstance(d, dict) else None
    loc = ent.get("installLocation") if isinstance(ent, dict) else None
    return loc if isinstance(loc, str) and os.path.isdir(loc) else None


def default_data_dir():
    return os.path.join(claude_dir(), "plugins", "data", "artifact-explorer-artifact-explorer")


def data_dir(arg=None):
    d = arg or os.environ.get("AE_DATA") or default_data_dir()
    os.makedirs(d, exist_ok=True)
    return d


# The allow rule `/artifact-explorer:setup` offers. The background describer needs it (no one is there to approve).
# 0.2.3: the skills write the command with the path quoted (`sh "${CLAUDE_PLUGIN_ROOT}/bin/ae" ...`), which the
# old rule does not match. Setup writes both; an install that has only one of them still counts as present.
ALLOW_RULE = "Bash(sh */artifact-explorer/*/bin/ae *)"
ALLOW_RULE_QUOTED = 'Bash(sh "*/artifact-explorer/*/bin/ae" *)'
ALLOW_RULES = (ALLOW_RULE_QUOTED, ALLOW_RULE)


def user_settings():
    """~/.claude/settings.json as a dict ({} when missing or unreadable). The one place it is read."""
    try:
        with open(os.path.join(claude_dir(), "settings.json"), encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def allow_rule_present():
    allow = (user_settings().get("permissions") or {}).get("allow") or []
    return isinstance(allow, list) and any(r in allow for r in ALLOW_RULES)


def allow_rules_missing():
    """The rules of ALLOW_RULES that settings.json does not have yet (setup adds these)."""
    allow = (user_settings().get("permissions") or {}).get("allow") or []
    allow = allow if isinstance(allow, list) else []
    return [r for r in ALLOW_RULES if r not in allow]


def options():
    """Plugin options from settings.json pluginConfigs, over the defaults. The one place options are read."""
    opts = dict(DEFAULT_OPTIONS)
    s = user_settings()
    try:
        opts.update(((s.get("pluginConfigs") or {}).get(PLUGIN_KEY) or {}).get("options") or {})
    except (AttributeError, TypeError, ValueError):
        pass
    for k, v in DEFAULT_OPTIONS.items():  # coerce types (the settings UI may store strings)
        try:
            if isinstance(v, bool):
                opts[k] = opts[k] if isinstance(opts[k], bool) else str(opts[k]).lower() in ("1", "true", "yes", "on")
            elif isinstance(v, (int, float)):
                opts[k] = type(v)(float(opts[k]))
        except (TypeError, ValueError):
            opts[k] = v
    return opts


def _merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_toml(path):
    with open(path, "rb") as f:
        return tomli.load(f)


def load_config(data):
    """ROOT/config/default.toml deep-merged with DATA/config.toml (user's file wins; arrays replace)."""
    cfg = load_toml(os.path.join(ROOT, "config", "default.toml"))
    user = os.path.join(data, "config.toml")
    if os.path.exists(user):
        cfg = _merge(cfg, load_toml(user))
    return cfg


def rekey_overrides(data, pairs):
    """Rename `[overrides."<old>"]` tables in DATA/config.toml to the new id, for {old: new} in pairs, when the
    new id has no table of its own. Comments and layout are kept; the file is rewritten only when the result
    still parses. Returns the number renamed."""
    p = os.path.join(data, "config.toml")
    if not pairs or not os.path.exists(p):
        return 0
    try:
        with open(p, encoding="utf-8-sig") as f:
            text = f.read()
        have = tomli.loads(text).get("overrides") or {}
    except (OSError, tomli.TOMLDecodeError):
        return 0
    todo = {s: d for s, d in pairs.items() if s in have}
    if not todo:
        return 0
    new = text
    for src, dst in todo.items():
        if dst not in have:
            q = re.escape(src)
            pat = re.compile(r"""(?m)^(\s*\[\s*overrides\s*\.\s*)(?:"%s"|'%s'|%s)(?=\s*\])""" % (q, q, q))
            new = pat.sub(lambda m: m.group(1) + '"%s"' % dst, new)
    try:
        got = tomli.loads(new).get("overrides") or {} if new != text else have
    except tomli.TOMLDecodeError:
        got, new = have, text
    missed = sorted(s for s in todo if s in got)
    if missed:  # another table form, or the short id has its own table: the old one no longer applies
        log(data, "config.toml: overrides for %s apply to merged rows; move them by hand (%s)"
            % (", ".join(missed), ", ".join(todo[s] for s in missed)))
    if new == text:
        return 0
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, p)
    except OSError:
        return 0
    n = len(todo) - len(missed)
    log(data, "config.toml: %d override(s) re-keyed after a merge" % n)
    return n


def log(data, msg):
    p = os.path.join(data, "watch.log")
    try:
        if os.path.exists(p) and os.path.getsize(p) > 1_000_000:
            os.replace(p, p + ".1")
        with open(p, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg.rstrip() + "\n")
    except OSError:
        pass


def _pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pid_cmdline(pid):
    """The command line of a live pid, or None (not found, or no `ps` here: Windows)."""
    if os.name == "nt":
        return None
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(int(pid))], capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return out or None


def stop_pid(pid):
    """Ask a process to end (SIGTERM; taskkill on Windows). Never raises."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(int(pid))], capture_output=True, timeout=10)
        else:
            import signal
            os.kill(int(pid), signal.SIGTERM)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


class Lock:
    """Exclusive lock file. `with Lock(path, stale_after) as ok:`; ok is False when another live holder has it."""

    def __init__(self, path, stale_after):
        self.path, self.stale_after, self.held = path, stale_after, False
        self.mine = None

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def __enter__(self):
        self.mine = {"pid": os.getpid(), "t": time.time()}
        body = json.dumps(self.mine).encode()
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, body)
            os.close(fd)
            self.held = True
            return True
        except FileExistsError:
            pass
        info = self._read() or {"pid": 0, "t": 0}
        try:
            if _pid_alive(int(info.get("pid", 0))) and time.time() - float(info.get("t", 0)) < self.stale_after:
                return False
        except (TypeError, ValueError):
            pass
        # stale: replace atomically through a unique tmp file, then re-read to confirm we won the race
        tmp = "%s.%d.%d.tmp" % (self.path, os.getpid(), time.time_ns())
        try:
            with open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        self.held = self._read() == self.mine
        return self.held

    def __exit__(self, *exc):
        if self.held:
            if self._read() == self.mine:
                try:
                    os.remove(self.path)
                except OSError:
                    pass
            self.held = False


def repo_of(cwd):
    """Folder name of the git repo that holds cwd; a .claude/worktrees/<x> checkout maps to its main repo."""
    if not cwd:
        return None
    p = os.path.abspath(cwd)
    marker = os.sep + os.path.join(".claude", "worktrees") + os.sep
    if marker in p + os.sep:
        p = p[: (p + os.sep).index(marker)]
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return os.path.basename(p)
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def ae_argv(*args):
    """argv that runs this plugin's CLI with the current interpreter."""
    return [sys.executable, os.path.join(HERE, "ae.py")] + [str(a) for a in args]


def detach(argv, cwd=None, out=None, env=None):
    """Start argv in the background, detached from this process, stdin closed; stdout to the file `out` when
    given; `env` adds to (never replaces) this process's environment. Returns the child's pid, or None when it
    could not start. Never raises."""
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=cwd,
              env=dict(os.environ, **env) if env else None)
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    f = None
    try:
        if out:
            f = kw["stdout"] = open(out, "wb")
        return subprocess.Popen(argv, **kw).pid
    except OSError:
        return None
    finally:
        if f:
            f.close()
