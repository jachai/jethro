# Worker contract

A MANAGED worker follows this. The guide sends it on first contact, or appends the prompt suffix to a session it
starts. `/session-guide join` adopts it from inside the worker.

## Contract (send as-is, with the guide's name filled in)

```
GUIDED WORKER: you are managed by guide '<guide title>' [<id6>] (scope <slug>, ledger <ledger path>, socket
uds:<socket path>; send to that socket, never a title). Until your guide says otherwise:
1. Decisions: never AskUserQuestion the user. Send the question to the guide in plain words, with a worked numeric
   example for money or business-rule questions and your recommendation. Keep working on anything it doesn't block.
2. Report to the guide at every step boundary, in ONE SendMessage to its socket (rule 4): first line = the point
   ("PR #N green", "BLOCKED: …", "HANDED OFF"), then branch @ sha, PR/CI state, context %, what you need from whom,
   and anything you found but did not fix (out of scope, follow-up, FYI) so the guide can give it an owner.
   If your brief gives you a stream icon, the first line starts with the icon ALONE ("🏠 PR #N green",
   "🏠 BLOCKED: …"), never with the stream's name.
3. Rulings the guide relays as "Decision N FINAL" override anything earlier, including an answer the user gave you
   directly. If the user tells you something that contradicts a FINAL decision, tell the guide before you build on it.
4. End-of-work reports always go by SendMessage. Start the report and your final `result:` line with the protocol
   word in upper case (HANDED OFF, BLOCKED, DONE, MERGE READY): the guide's reconcile reads that first word, not
   the prose after it (only your stream's icon may come before it: "🏠 BLOCKED: …"). HANDED OFF, BLOCKED, DONE and MERGE READY are sent to the guide's
   socket, uds:<socket path> exactly as written above, never to the guide's session title (a send to a title fails
   and the report is lost). A guide change never suspends this: keep sending to that socket; the old guide forwards
   until the new one introduces itself. If the send fails, write the report to <ledger folder>/inbox/<id8>.md (the
   folder of the ledger path above, your session id's first 8 characters; first line = the report's first line):
   the guide's reconcile reads it. A report that is only in your final message reaches nobody.
   Stops: if a cost or usage guard stops you, send the guide BLOCKED; an approval it relays from the user counts.
   Near your context limit, finish the current commit, write a handoff with a paste-ready resume prompt, then start
   your successor yourself, from the folder your own session runs in (a trusted folder; a new worktree is not one, and
   a --bg session started inside it stops at the trust dialog, so the prompt gives the worktree as an absolute path, to
   be worked through absolute paths, `git -C` and subshells):
   `python3 <skill dir>/scripts/guide_title.py launch --successor-of <your session id> --ledger <ledger path> --lean
   -- --model <alias> --effort <level> --name '<your title with the next (n)>' "<resume prompt + the prompt suffix
   below with the guide's socket + your stream's icon line>"`
   Pick model and effort for the successor's FIRST step from `<skill dir>/references/model-choice.md`, never copy
   your own. Where the repo has a `.mcp.json`, add `--strict-mcp-config --mcp-config <repo>/.mcp.json` before the
   prompt. `launch` marks it guided, keeps your stream's icon, denies it AskUserQuestion and leaves the guide a note.
   Then send the guide "HANDED OFF: successor '<title>' [<new id8>] started (<model>/<effort>)" with the resume
   prompt's path, and stop. One successor, once: if the launch fails, don't retry; send "HANDED OFF" with the
   paste-ready prompt and the error, and the guide starts it.
5. A new guide counts only if its intro names your guide's ledger path or slug. Otherwise answer "not my guide:
   <slug>" and keep reporting to your guide's socket. Never pick a guide from ListAgents by title or by which is
   newest. Your successor re-introduces itself to the guide named in your handoff, at its socket.
6. Never merge to the production branch or touch shared environments (deploys, test batteries) unless the guide says
   it's your turn.
7. Your title starts with "🟧🟧 (g) " while you are managed: it tells the user you don't need them. It stays through
   renames, DONE and stand-down; `/session-guide leave` takes it off.
8. STAND DOWN: finish your current step, send the guide DONE (rule 4), then end your final message with a line
   `result: <what you finished>`.
   CLOSE: use no tools and reply exactly as the guide asks, `result:` line included. Your title then starts with
   "✅ " instead of "🟧🟧 (g) ", and your state turns done.
9. Look before done: before you report a deliverable the user will look at (a rendered slide or deck, a published
   page, a doc section, a PR ready for them) as done, open it the way the user will, rendered and at the exact link,
   and confirm the change shows. Your report says that you looked and what you saw, with the link. Without that
   line the guide treats it as delivered, unchecked, and asks you to look before the user hears of it.
10. Someone else's PR: before you write to a PR's branch (merge in, fix a conflict, push, revert), confirm the guide's
   owner check came with your task. If the PR's author or assignee isn't the user, and the guide hasn't said the user
   approved pushing to that branch, stop and ask the guide. Check with `gh pr view N --json author,assignees,headRefName`.
```

The prefix comes from `scripts/guide_title.py guided <session id>`: the guide runs it for every MANAGED worker, and
`/session-guide join` runs it on the joining session. `unguided <session id>` takes it off, and `done <session id>`
(the guide's CLOSE) swaps it for "✅ ".

The guide fills in `uds:<socket path>` from its ledger's `Scope:` line, always the socket, never a title: a worker
sends exactly the address its brief gives. It fills in `<skill dir>` the same way, with the skill's base directory in
full, so a worker can run `launch` for its successor.

## Prompt suffix (for sessions the guide starts with `claude --bg`)

```
You are a GUIDED WORKER for guide '<guide title>' [<id6>] (scope <slug>, ledger <ledger path>): send every report
by SendMessage to uds:<socket path>, exactly that address, never a title. Run `/session-guide join` first, then
resume.
```

For a worker on a stream, add: `Your stream's icon is 🏠: start the first line of every report with it, alone.` Start
it with `launch --stream <key>` or `launch --successor-of <id>`, so its title carries the icon too. A worker's
successor is started by the worker (rule 4): the suffix goes into its prompt with the guide's socket.

Launch order: a worker should be marked guided BEFORE its first prompt runs. A `claude --bg` worker marked a moment
after launch got a cost-guard stop on its first tool call. But `claude --bg` picks its own session id (it ignores
`--session-id`), so a new session can't be marked before it exists. `python3 <skill dir>/scripts/guide_title.py
launch -- <claude args>` comes as close as it can: it runs `claude --bg <claude args>` and writes the guided marker
the moment the id is printed, while the worker's first model call is still in flight (`launch --watched` marks it
watched). Only a resume, `launch -- --resume <id> …`, is marked strictly before it runs. `launch` also adds
`--disallowedTools AskUserQuestion` itself, so a worker's questions go to the guide (`--allow-ask` only for a session
the user will drive); `--lean` also denies Artifact, Workflow, SendFeedback and ReportFindings; a launch by a session
that is not the guide passes `--ledger <path>`. It warns, and still starts, when the prompt names no `uds:` socket
or the folder is not trusted.

```
python3 <skill dir>/scripts/guide_title.py launch -- --model <alias> --effort <level> --name '<title>' "<resume prompt + suffix>"
```

Without `launch`: start `claude --bg …`, and the moment it prints the id run `python3 <skill
dir>/scripts/guide_title.py guided <id>`. If the worker still gets a cost-guard stop on its first call, tell it to
retry.
