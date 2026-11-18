# Changing the focus style

The focus prompt asks for at most six plain words, no paths, no hashes and no ticket codes. To steer
it, add one instruction with the `focus_style` option. It's appended to the focus prompt and wins
over the built-in examples.

## Set it

Plugin install:

```sh
echo '{"focus_style": "When a pull request is open, always include its number, like PR 88."}' \
  | claude plugin configure session-titles --values-stdin
claude plugin configure session-titles     # shows the current values
```

`/plugin` → session-titles → configure does the same from inside a session.

Plain install, in `~/.claude/session-titles/config.json`:

```json
{
  "focus_style": "When a pull request is open, always include its number, like 'PR 88'."
}
```

For one shell only, set it as an environment variable: `export SESSION_TITLES_FOCUS_STYLE="..."`.

## Instructions that work well

| Goal | `focus_style` |
|---|---|
| Always see the PR | `When a pull request is open, always include its number, like 'PR 88'.` |
| Keep ticket ids | `Start with the ticket id when the work has one, like 'ABC-123 retry fix'.` |
| Say who you're waiting on | `When the session is waiting on a person or a check, start with 'waiting:'.` |
| Shorter titles | `Use at most 3 words.` (and lower `max_focus_chars` to 24) |
| Another language | `Write the label in Spanish.` |

Keep it to one sentence. The focus is still trimmed to `max_focus_chars` at a word boundary, and a
focus that only repeats the origin is still dropped.

## Other knobs

- `separator`: the mark between origin and focus, always with one space each side. The default is `·`;
  `|` and `—` work too.
- `max_focus_chars`: 16 to 80, default 40. The whole title stays readable in the agents view at about
  60 characters.
- `model`: any model alias or full name `claude -p --model` accepts. A small model is plenty; a large
  one costs more and adds seconds before every prompt in `fresh` mode.
