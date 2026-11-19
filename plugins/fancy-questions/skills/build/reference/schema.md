# Data contract

`scripts/lint.mjs` is the contract; this page documents it. `qw build` fails with a numbered list when a rule
breaks. A data dir holds `page.json` and `cards/*.json` (each file an array of cards, or `{"cards": [...]}`),
merged in file-name order.

## page.json

| field | | what |
|---|---|---|
| `slug` | required | `a-z 0-9 -`, 2-41 chars. Keys the reader's saved answers (`qw-<slug>-answers-v1`). New slug per round. |
| `title` | required | Page and tab title. |
| `sections` | required | `[{id, label}]`, at least one. Cards point at them with `section`. Chips appear when there are 2+. |
| `audience` | | First name of the reader; the opening says "Sam, 6 questions. About 5 minutes." |
| `eyebrow` | | Small line above the heading (defaults to the title). |
| `heading` | | Replaces the computed opening heading. Usually leave it out. |
| `lead` | | One or two sentences under the heading. |
| `whyline`, `thanks`, `notePrompt` | | Override the default help line, the all-done line, and the note placeholder. |
| `discussWith` | | Name used by the standard discuss option: "Park it for a call with Sam." |
| `author` | | Who the answers go to (a first name). The page names them when saving fails: "Your answers are NOT reaching Sam". Defaults to `discussWith`. |
| `lastRound` | | `{url, label, decided, decidedLabel}`: link to the last page and a "5 built · 6 for you" legend. `decided` is a whole number. |
| `stats` | | `[{value, what, how}]`: counters on the opening screen (`value` is a number). |
| `minutesPerCard` | | Default 0.75; 0-10. Drives "About N minutes". |
| `allowedHosts` | | If set, every URL on the page must be on one of these hosts (or a subdomain). |

## Card

| field | | rule |
|---|---|---|
| `id` | required | `[a-z0-9][a-z0-9_.-]{0,60}`, unique across all cards AND parts. It is the db doc id: never reuse an id for a different question. |
| `section` | required | One of `page.sections[].id`. |
| `short` | required | ≤ 60 chars; the list entry and summary row. |
| `question` | required | ≤ 240 chars, the reader's words. |
| `recommend` | required | ≤ 240 chars; shown as "We recommend: …". |
| `today`, `after` | | `{label?, text}` or a plain string. Labels default to "Today" / "After". |
| `example` | | Worked example. If it has `$` + digit or any 2+ digit number, `facts` must not be empty. |
| `facts` | | `[{text, verified: true\|false}]`. Unverified ones render as an amber "not checked" line. |
| `links` | | `[{label, url}]`, https only. |
| `tickets` | | `[{id, url?}]`. Ticket ids are allowed in text; plan codes are not. |
| `badge` | | Short label ("Needed before Friday") on the card and in the list. |
| `urgent` | | `true` for cards that block work. With > 8 cards the opening offers "Urgent first (n)". Not every card. |
| `visual` | warned | One visual (see visuals.md). A card with no visual builds with a warning. |
| `options` | required | 2-6 options (aim for 2-5), see below. |
| `notePrompt` | | Placeholder for the always-shown free-text box. |
| `parts` | | Up to 3 extra questions on the same screen ("Part 2 of 3"). Each has the question fields (`id, question, recommend, today, after, example, facts, links, visual, options, notePrompt`) but no `section`, `short` or `parts`. The card is done only when every part is answered; Next is blocked until then. |

## Option

| field | | rule |
|---|---|---|
| `id` | required | Unique in the question. Saved as `optionId`. |
| `tone` | required | `yes`, `no`, `discuss` or `neutral`. |
| `name` | required | ≤ 70 chars. |
| `sub` | required | ≤ 200 chars, what it means. |
| `impact` | | ≤ 200 chars of text; may use only `<b> <i> <em> <strong>`. |
| `recommended` | | Exactly one option per question, and it must be first. |
| `picks` | | "Tick some": `{label, items[] \| groups[{name, items[]}], min, hint?, always?}`. Items are strings or `{value, label?, detail?}`; values unique. `min` defaults to 1: picking the option with fewer ticks shows "Tick at least N" and does not save. `always: true` (one option per question) shows the switches without picking first; ticking one selects the option, unticking all deletes the answer. Use `groups` for long lists (collapsible, with counts). |

`{"tone": "discuss"}` alone expands to id `discuss`, "Let's discuss", "Park it for a call (with discussWith)",
"Nothing changes until we talk." Put it last.

## Text rules (every string)

- No plan codes: `D-12`, `D593`, `Decision 12`, `wave B` fail. Say what it is in plain words or use a ticket id.
- Length caps above; they keep a card to one phone screen.
- All text is escaped; HTML only in `impact` (the four tags).

## Limits

- At most 40 cards per page (`qw build` refuses more: split into rounds).
- Page over 150 KB builds with a warning (usually a large `data:image`).

## Saved answer (what `collect` reads)

Doc id = the question id (card or part), collection `answers`:
`{v:1, page, qid, card, part, section, tickets (ids joined with ", "), question, optionId, choice (the tone), label, picks[], note, by, at}`.
`card` is the card id, `part` is 0 for the card itself and 1-3 for parts.
