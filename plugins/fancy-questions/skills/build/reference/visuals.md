# Visuals: one per card

Every card gets a `visual`. Pick the kind from what the question is about:

| the question is about | kind |
|---|---|
| amounts or counts side by side (pay, cost, jobs) | `bars` |
| how a total divides (share of jobs, split of a commission) | `split` |
| a process that happens in order | `flow` |
| a rule with conditions ("if X, then…") | `tree` |
| what changes (today vs after) | `beforeAfter` |
| things on a timeline (day 1, day 5, week 2) | `steps` |
| several items with 2-5 attributes | `table` |
| a screenshot or photo | `image` |
| two visuals that compare | `pair` (side by side) or `stack` (2-3 stacked) |
| none of the above | `svg` (raw, sanitized) |

Tones: `yes` (green), `no` (red), `discuss` (amber), `muted` (grey), `accent` (default). Use `yes` for the
recommended outcome and `no` for today's problem, so the colour already tells the story.

## bars
Rows 1-10; label ≤ 18 chars (use `table` for longer); `text` is what prints after the bar; optional `max`, `indent`.
```json
{"kind": "bars", "rows": [
  {"label": "Signed", "value": 10000, "text": "$10,000"},
  {"label": "Change order today", "value": 7500, "text": "$7,500", "tone": "no"},
  {"label": "Recommended", "value": 10000, "text": "$10,000", "tone": "yes"}]}
```

## split
Parts 2-6, values in any unit (the bar is the share of the total).
```json
{"kind": "split", "parts": [
  {"label": "rep", "value": 60, "text": "60%", "tone": "yes"},
  {"label": "manager", "value": 25, "text": "25%"},
  {"label": "company", "value": 15, "text": "15%", "tone": "muted"}]}
```

## flow
Steps 2-8, each `{label, note?, tone?}`.
```json
{"kind": "flow", "steps": [
  {"label": "Signed", "note": "rep paid on signing"},
  {"label": "Change order", "note": "adds a head", "tone": "discuss"},
  {"label": "Install", "tone": "yes"}]}
```

## tree
`root` is `{ask, branches[{when, then}]}` (2-4 branches, at most 3 asks deep); a leaf is `{label, tone?}` or a string.
```json
{"kind": "tree", "root": {"ask": "Head moved, not added?", "branches": [
  {"when": "yes", "then": {"label": "Counts as sold", "tone": "yes"}},
  {"when": "no", "then": {"ask": "Within heads signed?", "branches": [
    {"when": "yes", "then": {"label": "Counts", "tone": "yes"}}, {"when": "no", "then": {"label": "New sale", "tone": "muted"}}]}}]}}
```

## beforeAfter
Two columns, each `{label, lines[]}`; a line is a string or `{text, tone}`.
```json
{"kind": "beforeAfter",
 "before": {"label": "Today", "lines": [{"text": "$0 for the moved head", "tone": "no"}, "Ops fixes it by hand"]},
 "after": {"label": "Recommended", "lines": [{"text": "$2,500 for the head", "tone": "yes"}, "No manual fix"]}}
```

## steps
Items 2-10, each `{when?, label, note?, tone?}`.
```json
{"kind": "steps", "items": [
  {"when": "Day 0", "label": "Invoice sent"},
  {"when": "Day 5", "label": "Grace ends", "tone": "discuss"},
  {"when": "Day 6", "label": "$25 fee added", "tone": "yes"}]}
```

## table
1-5 `cols`, 1-12 `rows` (each exactly `cols.length` cells, strings); `highlight` lists row indexes to tint.
```json
{"kind": "table", "cols": ["Order", "Heads", "Paid today"],
 "rows": [["DNA Heating", "4", "$7,500"], ["Smith HVAC", "2", "$5,000"]], "highlight": [0]}
```

## image
`src` is https or a base64 `data:image/(png|jpeg|webp|gif)`; `alt` required. Keep data URIs small (page ≤ 150 KB).
```json
{"kind": "image", "src": "https://example.com/screenshot.png", "alt": "The change order screen with the head moved"}
```

## pair / stack
`pair` = `{a, b}` side by side (stacks on phones); `stack` = `items` of 2-3 visuals.
```json
{"kind": "pair",
 "a": {"kind": "bars", "rows": [{"label": "Today", "value": 0, "text": "$0", "tone": "no"}]},
 "b": {"kind": "bars", "rows": [{"label": "After", "value": 25, "text": "$25", "tone": "yes"}]}}
```

## svg (escape hatch)
Raw SVG for a drawing no typed kind covers. Rules lint enforces: starts with `<svg`, has a `viewBox` ≤ 420 wide,
only drawing tags (`g path rect circle ellipse line polyline polygon text tspan title desc defs marker
linearGradient stop use clipPath`), no event handlers, no links except `href="#id"`, no comments, and **no raw
colours**: use `class="ico"` on the svg and its classes (`soft ok warn bad nofill big sm redt greent acct`) or
`var(--fg) var(--muted) var(--accent) var(--yes) var(--no) var(--line)` so light and dark both work.
Keep all text inside the viewBox (the checker measures it). 13px text is the floor at phone width.
```json
{"kind": "svg", "svg": "<svg class=\"ico\" viewBox=\"0 0 320 90\" role=\"img\" aria-label=\"One outdoor unit, four heads\"><rect class=\"soft\" x=\"10\" y=\"25\" width=\"60\" height=\"40\" rx=\"6\"/><text x=\"16\" y=\"50\">Unit</text><path d=\"M70 45H300\"/><circle class=\"ok\" cx=\"130\" cy=\"45\" r=\"10\"/><circle class=\"ok\" cx=\"190\" cy=\"45\" r=\"10\"/><circle class=\"ok\" cx=\"250\" cy=\"45\" r=\"10\"/><circle class=\"bad\" cx=\"300\" cy=\"45\" r=\"10\"/></svg>"}
```
