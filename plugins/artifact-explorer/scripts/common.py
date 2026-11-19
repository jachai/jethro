"""Shared helpers: paths, options, config, logging, locks, repo names, detached runs."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))
import tomli  # noqa: E402  (vendored, works on Python 3.9+)

PLUGIN_NAME = "artifact-explorer"
DEFAULT_KEY = PLUGIN_NAME + "@jethro"  # the install id in the jethro marketplace
PLUGIN_KEY = DEFAULT_KEY  # kept for callers; lookups go through find_plugin_key (any artifact-explorer@* id)
PAGE_HEARTBEAT = 3600  # the watcher rewrites an unchanged page once it is this old, so its build time shows liveness
DEFAULT_OPTIONS = {
    "watch_interval": 10,
    "browser_history": True,
    "transcript_reads": True,
    "chrome_screenshots": False,
    "share_harvest": False,
    "describe_model": "haiku",
    "describe_daily_cap": 1.0,
    "describe_stop_loss": 0.01,
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


def plugin_keys(mapping):
    """The keys of `mapping` (installed_plugins.json "plugins" or settings.json "pluginConfigs") that are this
    plugin under any marketplace: artifact-explorer@*."""
    return [k for k in (mapping if isinstance(mapping, dict) else {}) if isinstance(k, str) and k.startswith(PLUGIN_NAME + "@")]


def _entry_list(ent):
    if isinstance(ent, dict):
        ent = [ent]
    return [e for e in ent if isinstance(e, dict)] if isinstance(ent, list) else []


def find_plugin_key(mapping, root=None):
    """Which artifact-explorer@* key of `mapping` is this install: the one whose installPath is the running code's
    ROOT (or a folder above it), else artifact-explorer@jethro, else any. None when there is no such key."""
    keys = plugin_keys(mapping)
    if not keys:
        return None
    root = os.path.realpath(root or ROOT)
    for k in sorted(keys):
        for e in _entry_list(mapping[k]):
            ip = e.get("installPath")
            if isinstance(ip, str) and ip:
                ip = os.path.realpath(ip)
                if root == ip or root.startswith(ip.rstrip(os.sep) + os.sep):
                    return k
    return DEFAULT_KEY if DEFAULT_KEY in keys else sorted(keys)[0]


def _installed_plugins():
    d = _read_json(os.path.join(claude_dir(), "plugins", "installed_plugins.json"))
    p = d.get("plugins") if isinstance(d, dict) else None
    return p if isinstance(p, dict) else {}


def installed_key():
    """The install id of this plugin: the key found in installed_plugins.json, else artifact-explorer@jethro."""
    return find_plugin_key(_installed_plugins()) or DEFAULT_KEY


def marketplace_name(key=None):
    return (key or installed_key()).split("@", 1)[1] or "jethro"


def installed_entries():
    """This plugin's installed_plugins.json entries (one per scope), [] when it is not installed."""
    plugins = _installed_plugins()
    k = find_plugin_key(plugins)
    return _entry_list(plugins.get(k)) if k else []


def marketplace_dir():
    """The local clone of this plugin's marketplace (known_marketplaces.json), or None."""
    d = _read_json(os.path.join(claude_dir(), "plugins", "known_marketplaces.json"))
    ent = d.get(marketplace_name()) if isinstance(d, dict) else None
    loc = ent.get("installLocation") if isinstance(ent, dict) else None
    return loc if isinstance(loc, str) and os.path.isdir(loc) else None


def marketplace_plugin_root(loc):
    """Where the plugin lives in a marketplace clone: the clone itself (a one-plugin marketplace) or plugins/<name>."""
    if loc and not os.path.isfile(os.path.join(loc, ".claude-plugin", "plugin.json")):
        sub = os.path.join(loc, "plugins", PLUGIN_NAME)
        if os.path.isfile(os.path.join(sub, ".claude-plugin", "plugin.json")):
            return sub
    return loc


def data_folder_name(key):
    """The folder Claude Code makes for CLAUDE_PLUGIN_DATA: <plugin>-<marketplace>, other characters as -."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", key.replace("@", "-", 1))


def default_data_dir():
    return os.path.join(claude_dir(), "plugins", "data", data_folder_name(installed_key()))


def _skip_copy(name):
    n = name.lower()
    return n.endswith(("-wal", "-shm", ".lock", ".pid")) or n in ("lock", "pid", "watcher.json")


def _copy_db(src, dst):
    """Copy a SQLite file with the backup API, so committed rows still in its -wal are included."""
    a = sqlite3.connect("file:%s?mode=ro" % src.replace("?", "%3f"), uri=True, timeout=10)
    try:
        tmp = "%s.tmp%d" % (dst, os.getpid())  # two first-run processes must not share a temp file
        b = sqlite3.connect(tmp)
        try:
            a.backup(b)
        finally:
            b.close()
    finally:
        a.close()
    os.replace(tmp, dst)


def migrate_data(d):
    """First run under a new install id: when `d` has no explorer.db and a sibling plugins/data/artifact-explorer-*
    folder has one, copy that folder's files in (never move; no wal/shm/lock/pid). Idempotent, cheap when idle."""
    try:
        if os.path.exists(os.path.join(d, "explorer.db")):
            return None
        parent = os.path.dirname(os.path.abspath(d))
        if os.path.basename(parent) != "data" or os.path.basename(os.path.dirname(parent)) != "plugins":
            return None
        me = os.path.basename(os.path.abspath(d))
        src = [os.path.join(parent, n) for n in os.listdir(parent)
               if n.startswith(PLUGIN_NAME + "-") and n != me and os.path.exists(os.path.join(parent, n, "explorer.db"))]
        if not src:
            return None
        src = max(src, key=lambda p: os.path.getmtime(os.path.join(p, "explorer.db")))
        shutil.copytree(src, d, dirs_exist_ok=True,
                        ignore=lambda _dir, names: [n for n in names if _skip_copy(n) or n == "explorer.db"])
        _copy_db(os.path.join(src, "explorer.db"), os.path.join(d, "explorer.db"))
        log(d, "copied the catalog from %s (old install id); the old folder is untouched" % os.path.basename(src))
        return src
    except (OSError, sqlite3.Error):
        return None


def data_dir(arg=None):
    d = arg or os.environ.get("AE_DATA") or default_data_dir()
    os.makedirs(d, exist_ok=True)
    migrate_data(d)
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
        cfgs = s.get("pluginConfigs") or {}
        mine = installed_key()  # the found id first, then the default, then any other artifact-explorer@* block
        for k in [mine, DEFAULT_KEY] + sorted(plugin_keys(cfgs)):
            got = (cfgs.get(k) or {}).get("options")
            if isinstance(got, dict) and got:
                opts.update(got)
                break
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
    return not _zombie(pid)


def _zombie(pid):
    """True when ps says the pid is a zombie (ended, not reaped yet): that counts as finished. False when ps fails."""
    try:
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(int(pid))], capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return out.startswith("Z")


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
