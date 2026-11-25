#!/usr/bin/env python3
"""Render the session-guide story GIF and stills from scripted, invented data.

    python3 scripts/dev/story_gif.py [OUTDIR]     (default: docs/screenshots)

Every session, stream, PR number and question below is made up (an online bookshop). Nothing is read from your
machine. The frames copy the layout of `claude agents`, claude-top and a guide session's chat. Needs Google Chrome
(headless, for the PNGs) and ffmpeg (for the GIF). Writes story.gif plus the stills named in STILLS.
"""
import html
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata

COLS, ROWS = 132, 31
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

# ------------------------------------------------------------------------------------------------ cell widths

def cw(ch):
    o = ord(ch)
    if ch in "️‍" or unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in "WF" or 0x1F300 <= o <= 0x1FAFF or ch in "✅⛔":
        return 2
    return 1


def width(s):
    return sum(cw(c) for c in s)


def fit(s, w, right=False):
    """Cut to w cells with an ellipsis, then pad to w."""
    if width(s) > w:
        out = ""
        for c in s:
            if width(out + c) > w - 1:
                break
            out += c
        s = out.rstrip(" ·") + "…"
    pad = " " * (w - width(s))
    return pad + s if right else s + pad


# ------------------------------------------------------------------------------------------------ line building
# A line is a list of (text, css classes). Classes: d default, g gray, o orange, l lavender, a amber, gr green,
# y yellow, c cyan, r red, bl blue, b bold, i italic, inv reverse video, sel selected row background.

def L(*segs):
    return [s if isinstance(s, tuple) else (s, "d") for s in segs]


def blank():
    return [("", "d")]


def rule(cls="g"):
    return [("─" * COLS, cls)]


# ------------------------------------------------------------------------------------------------ claude agents

NAME_W, ACT_W, PR_W, AGE_W = 56, 58, 6, 4


def agent_row(mark, name, act, age, pr="", mark_cls="g", cls="g", sel=False):
    segs = [("  ", "d"), (mark, mark_cls), (" ", "d"), (fit(name, NAME_W), cls), ("  ", "d"),
            (fit(act, ACT_W), cls), (" ", "d"), (fit(pr, PR_W, right=True), "g"), (" ", "d"),
            (fit(age, AGE_W, right=True), "g")]
    if sel:
        segs = [(t, c + " sel") for t, c in segs]
    return segs


def agents_view(counts, sections, prompt=None, cwd="~/code/bookshop"):
    lines = [
        L(("  ▐▛███▜▌  ", "o"), ("Claude Code", "b"), (" v2.1.332", "g")),
        L(("  ▝▜█████▛▘ ", "o"), (f"New sessions: Opus 5.5 · high effort · {cwd}", "g")),
        L(("    ▘▘ ▝▝   ", "o"), (counts, "g")),
        blank(),
    ]
    first = True
    for title, rows in sections:
        if first:
            lines.append(L(("❯ ", "l"), (title, "l b")))
            first = False
        else:
            lines.append(L(("  " + title, "b")))
        lines += rows
        lines.append(blank())
    while len(lines) < ROWS - 5:
        lines.append(blank())
    lines = lines[: ROWS - 5]
    lines.append(rule())
    if prompt:
        lines.append(L(("❯ ", "d"), (prompt, "d"), ("▌", "d")))
    else:
        lines.append(L(("❯ ", "g"), ("describe a task for a new session", "g")))
    lines.append(rule())
    lines.append(L(("  enter to open · ctrl+x to remove · ? for shortcuts", "g")))
    return lines


OLD_DONE = [
    agent_row("·", "✅ flaky test triage · fixed the timing test", "flaky test triage closed", "18h"),
    agent_row("·", "dependency bumps · PR merged", "Bumped 14 packages; all tests pass", "20h", "#198"),
    agent_row("·", "✅ onboarding emails · welcome series v2 live", "onboarding emails closed", "1d"),
    agent_row("·", "✅ image cdn migration · cut over, old bucket kept", "image cdn migration closed", "1d"),
    agent_row("·", "a11y audit · 6 of 7 contrast fixes merged", "Opened the last fix as a draft PR", "2d", "#191"),
]

GUIDE = "🟥🟥 Sessions Manager · bookshop-2-4"


def guide_title(managed, active, extra=""):
    return f"{GUIDE} ({managed} managed · 0 watched · {active} active · 0 new) 🟥🟥{extra}"


# ------------------------------------------------------------------------------------------------ claude-top

TOP_NAME_W = 38


def top_row(last, ago, age, state, sid, model, effort, ctx, pct, name, note, state_cls):
    bars = round(pct / 100 * 6)
    bar_cls = "r" if pct >= 75 else ("y" if pct >= 50 else "gr")
    return [
        (f"{last}  {ago:<5} {age:<5} ", "d"), (f"{state:<9} ", state_cls + " b"),
        (f"{sid}  {model:<11} {effort:<7} {ctx:<6} ", "d"),
        ("█" * bars + "·" * (6 - bars), bar_cls), (f" {pct:>2}%  ", "d"),
        (fit(name, TOP_NAME_W), "d"), (" ", "d"), (fit(note, COLS - 84 - TOP_NAME_W), "g"),
    ]


def top_view(clock, counts, week, pace, pace_cls, sections, foot):
    head = f" claude-top 0.6.4 {clock} every 2s │ {counts}"
    lines = [
        [(fit(head, COLS), "inv b")],
        [(fit(" agents now 4 (4 sess + 0 sub) │ spawned 6 (4 live) │ bg 4", COLS), "inv")],
        L(),
        L((" week ", "b"), (week, pace_cls + " b"), (f"  {pace}", "d")),
        L((" sort: last active   state: all   filter: -   folded: done (enter/click a section)", "g")),
        [(fit("LAST ACTIVE   AGO   AGE   STATE     ID      MODEL       EFFORT  CTX    CTX %       " + fit("NAME", TOP_NAME_W) + " NOTE", COLS),
          "c b")],
    ]
    for (label, label_cls, summary), rows in sections:
        lines.append(L((" ▾ ", "b"), (f"{label:<12}", label_cls + " b"), (summary, "b")))
        lines += rows
    while len(lines) < ROWS - 2:
        lines.append(blank())
    lines = lines[: ROWS - 2]
    lines.append(L((f" {foot}", "g")))
    lines.append([(fit(" enter attach/open  c copy  o sort  f state  / filter  ? help  i how-to  q quit", COLS), "inv")])
    return lines


# ------------------------------------------------------------------------------------------------ guide chat

def chat_view(body, status="Opus 5.5 · ~/code/bookshop · guide context 31k (hands off at 120k)"):
    lines = list(body)
    while len(lines) < ROWS - 4:
        lines.append(blank())
    lines = lines[: ROWS - 4]
    lines += [rule(), L(("> ", "d"), ("▌", "d")), rule(), L(("  " + status, "g"))]
    return lines


def say(text, first_cls="d"):
    """An assistant paragraph: ⏺ then text wrapped to the window."""
    out, words, cur = [], text.split(" "), ""
    for w in words:
        if width(cur) + width(w) + 1 > COLS - 4:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w) if cur else w
    out.append(cur)
    return [L(("⏺ ", first_cls), (out[0], "d"))] + [L(("  " + o, "d")) for o in out[1:]]


def tool(name, arg, result):
    return [L(("⏺ ", "gr"), (name, "b"), (f"({arg})", "d")), L(("  ⎿  ", "g"), (result, "g"))]


# ------------------------------------------------------------------------------------------------ the story

FRAMES = []


def frame(view, clock, title, caption, lines):
    FRAMES.append(dict(view=view, clock=clock, title=title, caption=caption, lines=lines))


# 1. Start the guide from `claude agents`
frame("claude agents", "9:02 AM", "claude agents",
      "Start one session as the guide and name the work streams",
      agents_view("0 working · 5 completed", [("Completed", OLD_DONE)],
                  prompt="/session-guide guide me through bookshop 2.4: search, checkout, the mobile menu, then release notes"))

# 2. The guide names the streams and starts one worker per stream
frame("guide session", "9:04 AM", guide_title(3, 4),
      "The guide gives each stream an icon and starts one worker per stream",
      chat_view([
          L(("> ", "g"), ("/session-guide guide me through bookshop 2.4: search, checkout, the mobile menu, then release notes", "g")),
          blank(),
          *say("I'm the guide for bookshop 2.4. Four streams, one icon each. Every session on a stream carries its icon:"),
          L(("    🔎 search     ", "d"), ("facet filters + typo tolerance            ", "g"), ("new worker: search facets lead", "d")),
          L(("    🛒 checkout   ", "d"), ("totals are 40¢ off when a coupon is used  ", "g"), ("new worker: checkout totals fix", "d")),
          L(("    🎨 design     ", "d"), ("the menu doesn't fit on 375px screens     ", "g"), ("new worker: mobile menu redesign", "d")),
          L(("    📚 docs       ", "d"), ("release notes                             ", "g"), ("starts when the other three land", "d")),
          blank(),
          *tool("Bash", 'guide_title.py launch --stream search -- "Add facet filters and typo tolerance…"',
                "started 7c41e9 · 🟧🟧 (g) 🔎 search facets lead"),
          *tool("Bash", 'guide_title.py launch --stream checkout -- "Fix coupon + tax totals…"',
                "started 2b90d3 · 🟧🟧 (g) 🛒 checkout totals fix"),
          *tool("Bash", 'guide_title.py launch --stream design -- "Make the menu fit small screens…"',
                "started e15a72 · 🟧🟧 (g) 🎨 mobile menu redesign"),
          blank(),
          *say("Three workers are running. I'll wake every 10 minutes while they work and bring you anything that needs "
               "your call as one interview."),
          blank(),
          L(("✻ ", "a"), ("Waiting on workers… next wake 9:14", "g")),
      ], status="Opus 5.5 · ~/code/bookshop · guide context 18k (hands off at 120k)"))

# 3. Workers in `claude agents`
WORKING_0920 = [
    agent_row("·", guide_title(3, 4), "Woke at 9:20: 3 workers busy, nothing for you yet", "18m"),
    agent_row("·", "🟧🟧 (g) 🔎 search facets lead", "Price and format facets done; 14 of 22 tests pass", "16m"),
    agent_row("·", "🟧🟧 (g) 🛒 checkout totals fix", "Reproduced the 40¢ gap with a $5 coupon on $50", "16m"),
    agent_row("·", "🟧🟧 (g) 🎨 mobile menu redesign", "Comparing two menu layouts at 375px", "16m"),
]
frame("claude agents", "9:20 AM", "claude agents",
      "Each worker carries its stream icon, so you can scan the list by project",
      agents_view("4 working · 5 completed", [("Working", WORKING_0920), ("Completed", OLD_DONE[:3])]))

# 4. claude-top: the same sessions, live
frame("claude-top", "9:41 AM", "claude-top",
      "claude-top: the same sessions live, with context used and your weekly pace",
      top_view("09:41:07", "sessions 9: 4 work · 0 wait · 5 done", "████─────────────── ",
               "21% used · 26% time · reset Mon 09:00 (4d23h) · 0.8x on pace", "gr",
               [(("working", "gr", "4 sessions · last active 2s ago"), [
                   top_row("Nov 25 09:41", "2s", "39m", "working", "a0c4f1", "opus 5.5", "high", "41k",
                           20, guide_title(3, 4), "Woke at 9:40: nothing new", "gr"),
                   top_row("Nov 25 09:41", "4s", "37m", "working", "7c41e9", "opus 5.5", "high", "88k",
                           44, "🟧🟧 (g) 🔎 search facets lead", "Typo tolerance: 19/22", "gr"),
                   top_row("Nov 25 09:40", "31s", "37m", "working", "2b90d3", "sonnet 5.5", "high", "61k",
                           30, "🟧🟧 (g) 🛒 checkout totals fix", "Writing the test", "gr"),
                   top_row("Nov 25 09:41", "9s", "37m", "working", "e15a72", "sonnet 5.5", "medium", "52k",
                           26, "🟧🟧 (g) 🎨 mobile menu redesign", "Layout B at 375px", "gr"),
               ]), (("done", "d", "5 sessions · last active 18h ago (folded)"), [])],
               "a0c4f1  ~/code/bookshop  session guide, ledger bookshop-2-4"))

# 5. A worker needs a decision: it goes to the guide, and the guide asks you
WORKING_1005 = [
    agent_row("·", "🟧🟧 (g) 🔎 search facets lead", "Typo tolerance done; running the full suite", "1h"),
    agent_row("·", "🟧🟧 (g) 🛒 checkout totals fix", "Waiting on the guide: tax before or after the coupon?", "1h"),
    agent_row("·", "🟧🟧 (g) 🎨 mobile menu redesign", "Layout B fits; checking the 320px case", "1h"),
]
frame("claude agents", "10:05 AM", "claude agents",
      "A worker needs a decision: it asks the guide, and the guide asks you",
      agents_view("1 awaiting input · 3 working · 5 completed", [
          ("Needs input", [agent_row("✻", guide_title(3, 4), "answer: 2 questions (🛒 coupon tax, 🔎 facet counts)",
                                     "1h", mark_cls="a", cls="d", sel=True)]),
          ("Working", WORKING_1005), ("Completed", OLD_DONE[:3])]))

# 6. The interview
OPT = [
    ("1. On $45, after the coupon (Recommended)",
     "The customer pays $48.60. Matches the receipts the store already sends; one line changes in totals.py."),
    ("2. On $50, before the coupon",
     "The customer pays $49.00, 40¢ more. No code change, but receipts and totals keep disagreeing."),
    ("3. A setting per store",
     "Both rules, default $45. About one more day of work before the PR."),
    ("4. Type something.", None),
]
interview = [
    L(("> ", "g"), ("what's next?", "g")),
    blank(),
    *say("One worker is waiting on you, and one more question came in. Both are below."),
    blank(),
    rule("l"),
    L((" ←  ", "g"), (" ☐ 🛒 Coupon tax ", "inv"), ("  ☐ 🔎 Facet counts  ", "d"), (" ✔ Submit ", "g"), ("  →", "g")),
    blank(),
    L((" 🛒 checkout totals fix [2b90d3] asks: a $5 coupon on a $50 cart. Is the 8% sales tax charged on $45 or on $50?", "b")),
    blank(),
]
for i, (label, desc) in enumerate(OPT):
    cur = i == 0
    interview.append(L((" ❯ " if cur else "   ", "l"), (label, "l b" if cur else "d")))
    if desc:
        interview.append(L(("      " + desc, "g")))
interview += [blank(), L((" Enter to select · Tab/Arrow keys to navigate · Esc to cancel", "g"))]
frame("guide session", "10:06 AM", guide_title(3, 4),
      "The interview: every option, the recommendation first, and what each does",
      chat_view(interview))

# 7. Rulings become decisions and go back to the workers
frame("guide session", "10:08 AM", guide_title(3, 4),
      "Your answers become ledger decisions, relayed to each worker",
      chat_view([
          L(("⏺ ", "d"), ("User answered: ", "d"), ("🛒 Coupon tax → On $45, after the coupon", "b"), ("  ·  ", "g"),
            ("🔎 Facet counts → Hide out-of-stock books", "b")),
          blank(),
          *tool("Update", "~/.claude/session-guide/bookshop-2-4/ledger.md",
                "Decisions: + 7 FINAL tax is charged after the coupon · + 8 FINAL facet counts skip out-of-stock books"),
          *tool("SendMessage", "2b90d3 · 🛒 checkout totals fix",
                "delivered: 🛒 Decision 7 FINAL: charge the 8% tax on the price after the coupon"),
          *tool("SendMessage", "7c41e9 · 🔎 search facets lead",
                "delivered: 🔎 Decision 8 FINAL: facet counts leave out out-of-stock books"),
          blank(),
          *say("Both workers have their answers. 🛒 checkout expects a PR within the hour; 🔎 search is at 72% context "
               "and will hand off to a successor when the suite is green."),
          blank(),
          L(("✻ ", "a"), ("Waiting on workers… next wake 10:18", "g")),
      ], status="Opus 5.5 · ~/code/bookshop · guide context 47k (hands off at 120k)"))

# 8. claude-top: a handoff and a finished worker
frame("claude-top", "11:12 AM", "claude-top",
      "A worker near full context hands off; a successor takes over its stream",
      top_view("11:12:40", "sessions 11: 4 work · 0 wait · 7 done", "███████──────────── ",
               "34% used · 27% time · reset Mon 09:00 (4d21h) · 1.3x · → still lasts the week", "y",
               [(("working", "gr", "4 sessions · last active 1s ago"), [
                   top_row("Nov 25 11:12", "1s", "2h", "working", "a0c4f1", "opus 5.5", "high", "58k",
                           29, guide_title(3, 4), "Relayed the handoff", "gr"),
                   top_row("Nov 25 11:12", "3s", "4m", "working", "4f8a21", "opus 5.5", "high", "34k",
                           17, "🟧🟧 (g) 🔎 search facets lead (2)", "Read the handoff; on step 3", "gr"),
                   top_row("Nov 25 11:11", "48s", "2h", "working", "e15a72", "sonnet 5.5", "medium", "97k",
                           48, "🟧🟧 (g) 🎨 mobile menu redesign", "Screenshots for review", "gr"),
                   top_row("Nov 25 11:12", "6s", "9m", "working", "9d3f08", "sonnet 5.5", "medium", "22k",
                           11, "🟧🟧 (g) 📚 release notes 2.4", "Drafting from merged PRs", "gr"),
               ]), (("done", "d", "7 sessions · last active 4m ago"), [
                   top_row("Nov 25 11:08", "4m", "2h", "done", "7c41e9", "opus 5.5", "high", "161k",
                           81, "✅ 🔎 search facets lead", "Handed off to (2)", "d"),
                   top_row("Nov 25 10:51", "21m", "2h", "done", "2b90d3", "sonnet 5.5", "high", "104k",
                           52, "✅ 🛒 checkout totals fix", "PR #214 ready", "d"),
               ])],
               "7c41e9  ~/code/bookshop  handed off: 4f8a21 started from its handoff"))

# 9. claude agents: what finished
frame("claude agents", "11:30 AM", "claude agents",
      "Finished workers turn ✅; the docs stream starts once the others land",
      agents_view("4 working · 7 completed", [
          ("Working", [
              agent_row("·", guide_title(3, 4), "Status sent: 1 merge and 1 review for you", "2h"),
              agent_row("·", "🟧🟧 (g) 🔎 search facets lead (2)", "Suite green; opening the PR", "22m"),
              agent_row("·", "🟧🟧 (g) 🎨 mobile menu redesign", "Preview up for your review", "2h"),
              agent_row("·", "🟧🟧 (g) 📚 release notes 2.4", "Draft: 3 of 4 sections", "27m"),
          ]),
          ("Completed", [
              agent_row("·", "✅ 🛒 checkout totals fix · PR ready, CI green", "PR #214: tax after the coupon (Decision 7)",
                        "39m", "#214"),
              agent_row("·", "✅ 🔎 search facets lead · handed off", "HANDED OFF to (2) at step 3; tests 22/22", "22m"),
              *OLD_DONE[:3],
          ])]))

# 10. The guide's status: what needs you, what finished
frame("guide session", "11:31 AM", guide_title(3, 4),
      "One status: what needs you, what finished, where each stream stands",
      chat_view([
          L(("> ", "g"), ("where do we stand?", "g")),
          blank(),
          L(("⏺ ", "d"), ("Needs you now", "b")),
          L(("  1. Merge #214 🛒 tax after the coupon: green, both reviews clean, no deploy running", "d")),
          L(("  2. Look at 🎨 the new menu at 375px: preview link from 'mobile menu redesign' [e15a72]", "d")),
          blank(),
          L(("  ", "d"), ("Results for you", "b")),
          L(("  - 🛒 1,200 test carts re-priced: 0 off by a cent (was 312). Asked 11:02, no verdict yet", "d")),
          blank(),
          L(("  ", "d"), ("Streams", "b")),
          L(("  - 🔎 search: suite green → next: PR from 'search facets lead (2)' [4f8a21]", "d")),
          L(("  - 🛒 checkout: PR #214 ready → next: your merge", "d")),
          L(("  - 🎨 design: preview up → next: your look, then the PR", "d")),
          L(("  - 📚 docs: drafting from the merged PRs → next: review after #214 lands", "d")),
          blank(),
          L(("  ", "d"), ("Running on its own", "b")),
          L(("  - 4 workers; next wake 11:41", "d")),
          L(("  Guide context: 63k (hand off at 120k)", "g")),
      ], status="Opus 5.5 · ~/code/bookshop · guide context 63k (hands off at 120k)"))

# 11. Away mode
frame("claude agents", "6:10 PM", "claude agents",
      "Away mode: the guide makes the reversible calls and lists each one for you",
      agents_view("3 working · 9 completed", [
          ("Working", [
              agent_row("·", "🟥🟥 💤 until 09:00 · Sessions Manager · bookshop-2-4 (2 managed…",
                        "Away: 2 decided for you, 1 held (publishing the notes)", "9h"),
              agent_row("·", "🟧🟧 (g) 🎨 mobile menu redesign (2)", "Decided while away: keep the hamburger icon", "48m"),
              agent_row("·", "🟧🟧 (g) 📚 release notes 2.4", "Notes ready; held: publishing waits for you", "7h"),
          ]),
          ("Completed", [
              agent_row("·", "✅ 🔎 search facets lead (2) · merged", "PR #215 merged by you at 3:55; staging green", "2h", "#215"),
              agent_row("·", "✅ 🛒 checkout totals fix · merged", "PR #214 merged by you at 11:40", "6h", "#214"),
              agent_row("·", "✅ 🎨 mobile menu redesign · handed off", "HANDED OFF to (2) after your review", "4h"),
              *OLD_DONE[:2],
          ])]))


# ------------------------------------------------------------------------------------------------ rendering

COLORS = {"d": "#e8e6e3", "g": "#999999", "o": "#d77757", "l": "#b1b9f9", "a": "#ffc107", "gr": "#4eba65",
          "y": "#e5c07b", "c": "#56b6c2", "r": "#e06c75", "bl": "#61afef"}
VIEW_ICON = {"claude agents": "≡", "claude-top": "▤", "guide session": "🟥"}


def seg_html(text, classes):
    cls = classes.split()
    st = []
    for c in cls:
        if c in COLORS:
            st.append(f"color:{COLORS[c]}")
    if "b" in cls:
        st.append("font-weight:700")
    if "inv" in cls:
        st += ["background:#e8e6e3", "color:#181818"]
    if "sel" in cls:
        st.append("background:#2c2d3a")
    out = []
    for ch in text:
        w = cw(ch)
        if ord(ch) < 0x2500 or 0x2500 <= ord(ch) <= 0x259F:
            out.append(html.escape(ch))
        elif w == 0:
            out.append(ch)
        else:
            out.append(f'<span class=w style="width:{w}ch">{html.escape(ch)}</span>')
    return f'<span style="{";".join(st)}">{"".join(out)}</span>'


def to_html(fr, n, total):
    body = "\n".join("".join(seg_html(t, c) for t, c in line) for line in fr["lines"])
    dots = "".join(f'<i class="{"on" if k == n else ""}"></i>' for k in range(total))
    return f"""<!doctype html><meta charset=utf-8><style>
html,body{{margin:0;background:#101114}}
.page{{width:{PAGE_W}px;height:{PAGE_H}px;box-sizing:border-box;padding:18px 22px;background:#101114;
font:15px -apple-system,'Segoe UI',Helvetica,sans-serif;color:#e8e6e3}}
.cap{{display:flex;align-items:center;gap:12px;height:34px;margin-bottom:12px}}
.num{{background:#d77757;color:#101114;font-weight:700;border-radius:13px;min-width:26px;height:26px;display:flex;
align-items:center;justify-content:center;font-size:14px}}
.txt{{font-size:17px;font-weight:600;flex:1}}
.view{{font:13px Menlo,monospace;color:#b1b9f9;border:1px solid #3a3b4a;border-radius:6px;padding:3px 8px}}
.dots{{display:flex;gap:6px;margin-left:8px}} .dots i{{width:7px;height:7px;border-radius:4px;background:#3a3a3a}}
.dots i.on{{background:#d77757}}
.win{{width:calc({COLS}ch + 24px);font:13px/1.34 Menlo,'SF Mono',monospace;background:#181818;color:#e8e6e3;
border-radius:10px;overflow:hidden;box-shadow:0 0 0 1px #3a3a3a}}
.bar{{height:30px;background:#262626;display:flex;align-items:center;padding:0 12px;gap:8px;
font:12px -apple-system,Helvetica,sans-serif;color:#aaa;border-bottom:1px solid #333}}
.dot{{width:12px;height:12px;border-radius:6px}} .t{{flex:1;text-align:center;white-space:nowrap;overflow:hidden}}
.s{{color:#777;font-variant-numeric:tabular-nums}}
pre{{margin:0;padding:10px 12px;font:inherit;white-space:pre}}
.w{{display:inline-block;text-align:left;overflow:visible}}
</style><div class=page><div class=cap><div class=num>{n + 1}</div><div class=txt>{html.escape(fr["caption"])}</div>
<div class=view>{html.escape(fr["view"])}</div><div class=dots>{dots}</div></div>
<div class=win><div class=bar><span class=dot style="background:#ff5f57"></span>
<span class=dot style="background:#febc2e"></span><span class=dot style="background:#28c840"></span>
<span class=t>{html.escape(fr["title"])}</span><span class=s>{fr["clock"]}</span></div><pre>{body}</pre></div></div>"""


PAGE_W, PAGE_H = 1112, 676
STILLS = {5: "story-needs-input.png", 6: "story-interview.png", 8: "story-claude-top.png"}  # frame number → file


def shoot(html_path, png_path, prof):
    subprocess.run([CHROME, "--headless=new", f"--user-data-dir={prof}", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=2", f"--window-size={PAGE_W},{PAGE_H}",
                    f"--screenshot={png_path}", "file://" + html_path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    outdir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "docs", "screenshots"))
    os.makedirs(outdir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="sg-story-")
    frames_dir = os.path.join(work, "png")
    os.makedirs(frames_dir)
    try:
        pngs = []
        for n, fr in enumerate(FRAMES):
            hp = os.path.join(work, f"f{n:02d}.html")
            with open(hp, "w") as f:
                f.write(to_html(fr, n, len(FRAMES)))
            pp = os.path.join(frames_dir, f"{n + 1:02d}.png")
            shoot(hp, pp, os.path.join(work, "chrome"))
            pngs.append(pp)
        # 4.5 s a frame (the last one 7 s), 1x size, one shared palette.
        lst = os.path.join(work, "list.txt")
        with open(lst, "w") as f:
            for i, p in enumerate(pngs):
                f.write(f"file '{p}'\nduration {7 if i == len(pngs) - 1 else 4.5}\n")
            f.write(f"file '{pngs[-1]}'\n")
        gif = os.path.join(outdir, "story.gif")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-vf",
                        f"scale={PAGE_W}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=full[p];"
                        "[b][p]paletteuse=dither=none", "-loop", "0", gif], check=True)
        for num, name in STILLS.items():
            shutil.copy(pngs[num - 1], os.path.join(outdir, name))
        print(f"{len(pngs)} frames → {gif} ({os.path.getsize(gif) // 1024} KB) + {len(STILLS)} stills")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
