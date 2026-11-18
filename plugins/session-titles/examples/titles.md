# Example titles

Made-up sessions, in the shapes the hook sees most. Each row is the title after that prompt.

## A feature, from an unnamed session

| Prompt | Title |
|---|---|
| Add rate limiting to the public search API | `search api rate limiting` |
| use a token bucket per API key, 60/min | `search api rate limiting · token bucket per API key` |
| tests are flaky on the refill timing, look | `search api rate limiting · fixing flaky refill tests` |
| ok open a PR | `search api rate limiting · PR 88 waiting on CI` |

The first prompt only sets the origin: nothing has happened yet, so a focus would just repeat it.

## A named background session that drifts

Started with `claude --bg --name "nightly report emails"`.

| Prompt | Title |
|---|---|
| The nightly report email went out empty for two tenants | `nightly report emails` |
| check the job logs from last night | `nightly report emails · reading last night's job logs` |
| looks like the tenant query times out, why? | `nightly report emails · slow tenant query` |
| add the missing index and backfill | `nightly report emails · adding index and backfill` |

The name you gave it never changes. The focus follows the work as it drifts.

## A rename in the middle

| Prompt | Title |
|---|---|
| (after `/rename db index fix`) let's also fix the other slow query | `db index fix · second slow query` |

A name you set is the new origin. The old origin is gone, and the focus carries on after the new one.

## A long-running guide session

| Prompt | Title |
|---|---|
| Coordinate the release: three PRs, staging check, then prod | `release coordination` |
| what's the state of the staging deploy? | `release coordination · staging deploy check` |
| PR 2 merged, start the staging checks | `release coordination · staging checks running` |
| all green, promote to prod | `release coordination · promoting to production` |

## A question, not a task

| Prompt | Title |
|---|---|
| How do I make a hook run only for one project? | `project-scoped hooks question` |
| and can a plugin ship a hook too? | `project-scoped hooks question · plugin hooks` |

## A prompt that is an instruction

| Prompt | Title |
|---|---|
| Say hello in one short line | `greeting test` |

The prompt is passed to the model as data to describe, never as an instruction, so the title model
labels the request instead of answering it.
