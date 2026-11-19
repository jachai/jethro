# Verify follow-up (worker brief)

The guide starts this read-only session when the user says yes to a follow-up (SKILL §7, Follow-ups). It checks that a
fix or deployment that reached production or staging does what it was meant to do, using the code, the intended
behaviour, the database and the logs. Fill in the `<...>` fields, then start it from the repository the change lives
in with `guide_title.py launch` at `sonnet` / `medium` (`model-choice.md`), which marks it guided before its first
prompt runs (SKILL §6). The title is `verify <thing>`, for example `verify #142`.

Tools are named by role. If `<config>/session-guide/local.md` names your real ones (your read-only production database
tool, your log search tool, your staging database tool), put those names into the brief.

## Brief (send as-is, fields filled)

```
VERIFY (read-only): check that <thing: PR #N / version> does what it was meant to do on <prod | staging>.

What shipped: <one line: the fix or feature, in plain words>
Where and when: <deploy line from the ledger: environment, deploy time with timezone, deployed sha>
Intended behaviour: <the PR body's summary and the guide's Decisions that apply, verbatim with their numbers,
  e.g. "Decision 245 FINAL: ...">
Tools: <your read-only prod DB tool> for data, <your log search tool> for logs. <anything local.md says about access>
Guide: '<guide title>' [<id6>], ledger <ledger path>, socket uds:<socket path>

Rules
- READ-ONLY. No writes anywhere: no INSERT, UPDATE, DELETE or DDL, no migrations, no deploys, no reruns of jobs, no
  merges, no pushes, no PR or ticket edits, no messages to people outside this session's guide. SELECT only, preferably
  aggregates (counts, sums, min/max) and ids. No personal data (names, emails, addresses, phone numbers) in your report:
  use ids.
- Never AskUserQuestion. Questions go to the guide in plain words with your recommendation.
- Keep queries cheap: always filter by time (since the deploy) and limit rows.

Steps
1. Code. Read the merged diff (`gh pr view <N> --json mergeCommit,body,files` and `gh pr diff <N>`, or
   `git log`/`git show` for a version). Name the code paths that changed: functions, endpoints, jobs, migrations.
2. Expected behaviour. Write down, in concrete terms, what should now happen and what should no longer happen. Use
   numbers wherever money is involved: a worked example with amounts before and after (e.g. "order 600.00, 1 of 3
   items returned at 200.00 → refund 200.00, fee 0.00; before the fix the fee was 15.00"). Say which rows or log
   lines would prove it, and which would show it broken.
3. Data. With the read-only database tool, find the records the changed paths touched since the deploy time. Report
   counts, the ids of a few examples, and for each whether it matches step 2 (recompute any money from the stored
   inputs and compare). Look for the old wrong behaviour too: rows created since the deploy that still show it.
4. Logs. With the log search tool, search since the deploy for errors, exceptions, refusals and warnings on the changed
   paths, and for the log lines that show the new code ran. Compare the error rate with the same span before the
   deploy if it is cheap.
5. Verdict, one of:
   - verified: the changed paths ran on real data since the deploy and every case checked matches step 2;
   - not exercised yet: no traffic reached the changed paths since the deploy (say what would exercise them, and when
     it is likely);
   - broken: at least one case contradicts step 2, or the change raises new errors. Give the ids, the expected and
     actual values, and the log lines.

Report to the guide in ONE SendMessage to uds:<socket path>, exactly that address, never the guide's title:
  first line "VERIFIED: <thing>" / "NOT EXERCISED YET: <thing>" / "BROKEN: <thing>", then
  - expected behaviour (step 2, with the worked example);
  - evidence: queries run (text), counts, example ids, log searches and their hit counts, time span covered;
  - anything you found but did not check or fix (loose ends: other failures in the logs, data that looks wrong for
    another reason, a test that should exist), each as one line the guide can give an owner;
  - context size.
If the send fails, write the same report to <ledger folder>/inbox/<your id8>.md (first line = the report's first
line); the guide reads it from there.
End your final message with a line `result: <thing> <verified | not exercised yet | broken>`.
```

## What the guide does with the report

- Records it: `guide_title.py verification "<thing> <short name>" <verified | not-exercised | broken> "<title [id6]>:
  <one-line evidence>"`. A not-exercised row comes back as a re-check after 24 hours (`--recheck-hours` to change).
- **Broken** becomes an Open items row for a fix, with the worker's evidence, and goes into the next interview first:
  something real may be wrong in production.
- Every loose end in the report becomes an Open items row (SKILL §4, Open items).
- Closes the session (SKILL §6) once the report is in and recorded.

## Claims: merges and commands someone said they would do

A follow-up can only check what really happened. A merge handed to the user, or a command the user, a colleague or a
worker was asked to run, is tracked in the ledger's `## Claims` table until there is evidence, so it can't be
forgotten across a guide handoff. Each row is written by `guide_title.py claim` (or `scripts/guide_claims.py claim
… --ledger <path>`):

```
| Claim [key] | What | By | Claimed | Evidence |
|---|---|---|---|---|
| merge [5c2e1a] | acme/widgets#12 | the user | 2026-11-19 14:05 | — |
| run [9f0b3d] | `make backfill-orders` | Dana | 2026-11-19 14:10 | done 2026-11-19 15:02: 4,210 rows, log linked in #ops |
```

The key is 6 hex characters made from the PR or the command, so the same PR or command always lands on the same row.
Evidence is `—` while the claim is open. Closed rows stay, like Verifications rows.

- `claim merge #N [--repo owner/name] [--by <who>]`: someone (default: the user) was asked to merge a PR. `#N`, `N`,
  `owner/name#N` or the PR link all work.
- `claim run "<command>" --by <who>`: someone was asked to run a command; give it exactly as given to them.
- `claim done <key | #N> "<evidence>"`: closes a claim with what shows it happened (a merge sha, the output, a link).
- `claim list [--all] [--days 3]`: the open claims (merge claims re-checked with gh), and the ledger lines from the
  last 3 days (0 = all) that ask for a merge or a command with no claim row; `--all` adds the closed claims.

On every prompt the hook re-checks each open merge claim with `gh pr view <N> --json state,mergedAt` (cached 10
minutes, 5 s timeout; it fails open and says "not checked" when gh is off with `SESSION_GUIDE_GH=0`, missing or
failing). A merged PR closes its own claim with gh's merge time as evidence, and the hook says so once. A PR still
open, or closed without merging, stays listed until it merges or you `claim done` it. A run claim with no evidence
after `SESSION_GUIDE_CLAIM_HOURS` (default 4) is listed until it has some: ask for the output. The hook also counts
the unclaimed lines: "MERGE READY #N", "<someone> runs / tells …" and `! command` lines from the last
`SESSION_GUIDE_CLAIM_DAYS` (default 3) days with no claim row. A PR the ledger already says is merged or deployed,
or that has a Verifications row, is not counted. Claim each one, then `claim done` the ones already done.

A merge claim closed by gh is evidence of the merge, not of the fix working: a fix that reached prod or staging still
gets its follow-up review above.
