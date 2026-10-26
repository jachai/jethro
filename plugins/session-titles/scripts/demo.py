#!/usr/bin/env python3
"""Run the real hook over made-up sessions and print how their titles change.

    python3 scripts/demo.py

Model replies come from a fake `claude` in a temp dir, so this makes no model calls and never
touches your real ~/.claude.
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "session_titles.py"

FAKE_CLAUDE = textwrap.dedent("""\
    #!{python}
    import json, os, sys
    from pathlib import Path
    sys.stdin.read()
    queue = Path(os.environ["DEMO_REPLIES"])
    replies = json.loads(queue.read_text())
    print(json.dumps({{"type": "result", "result": replies.pop(0) if replies else "working"}}))
    queue.write_text(json.dumps(replies))
""")

# name given by the user (None = unnamed), then (prompt, model reply, what the assistant said after)
SESSIONS = [
    (None, [
        ("Build a CSV export for the invoices page", "invoice csv export", "Wrote the exporter and its tests."),
        ("tests pass? then open a PR", "opening the pull request", "PR 214 is open; CI is running."),
        ("watch CI and tell me when it's green", "PR 214 waiting on CI", "CI is green on PR 214."),
    ]),
    ("stripe webhooks", [
        ("Retries are double-charging some customers, find out why", "tracing the double charge",
         "The retry handler doesn't check the idempotency key."),
        ("fix it and add a regression test", "fixing the retry idempotency check", "Fixed; the new test passes."),
        ("Stripe webhooks: all done?", "Stripe webhooks",  # a reply that only repeats the name is dropped
         "Done. One follow-up: the old events table needs a cleanup job."),
    ]),
    (None, [
        ("Say hello in one short line", "greeting test", "Hello!"),
        ("now explain what a UserPromptSubmit hook is", "explaining prompt hooks",
         "A UserPromptSubmit hook runs before Claude sees your prompt."),
    ]),
]


def assistant_line(text):
    return json.dumps({"type": "assistant", "message": {"role": "assistant",
                                                        "content": [{"type": "text", "text": text}]}})


def main():
    rows = []  # each session's final title
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fake = tmp / "claude"
        fake.write_text(FAKE_CLAUDE.format(python=sys.executable))
        fake.chmod(0o755)
        replies = tmp / "replies.json"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("SESSION_TITLES_", "CLAUDE_PLUGIN_OPTION_"))}
        env.update(CLAUDE_CONFIG_DIR=str(tmp / ".claude"), SESSION_TITLES_CLAUDE=str(fake),
                   SESSION_TITLES_SKIP_PRINT_MODE="false", DEMO_REPLIES=str(replies))
        for n, (name, turns) in enumerate(SESSIONS, 1):
            sid = f"{n:08d}-0000-4000-8000-000000000000"
            transcript = tmp / f"{sid}.jsonl"
            transcript.write_text("")
            title = name
            print(f"session {n}: " + (f"started with --name {name!r}" if name else "started without a name"))
            for prompt, reply, said in turns:
                first = not transcript.read_text()
                # an unnamed session's first prompt makes one call for the origin; later prompts one for the focus
                replies.write_text(json.dumps([reply]))
                hook_in = {"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": prompt,
                           "transcript_path": str(transcript)}
                if title:
                    hook_in["session_title"] = title
                out = subprocess.run([sys.executable, str(SCRIPT), "hook"], input=json.dumps(hook_in),
                                     capture_output=True, text=True, env=env, check=True).stdout
                if out.strip():
                    title = json.loads(out)["hookSpecificOutput"]["sessionTitle"]
                note = "  (first prompt: origin only)" if first else ""
                print(f"  > {prompt[:44]:<44}  {title}{note}")
                with transcript.open("a") as f:
                    f.write(assistant_line(said) + "\n")
            rows.append(title)
            print()
    print("what claude agents and /resume show now:")
    for title in rows:
        print(f"  {title}")


if __name__ == "__main__":
    main()
