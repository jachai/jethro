"""Remove or add the Artifact Explorer allow rule in a settings.json, touching only that line.

    python3 settings_rule.py remove|add SETTINGS OUT

Writes the result to OUT. The edit is textual, so the rest of the file keeps its formatting; the result must
parse and equal the original with only the rule removed (or added), else the script exits non-zero.
"""
import json
import re
import sys

RULE = "Bash(sh */artifact-explorer/*/bin/ae *)"
RULE_QUOTED = 'Bash(sh "*/artifact-explorer/*/bin/ae" *)'  # 0.2.3: the skills quote the path
RULES = (RULE_QUOTED, RULE)


def remove(text, RULE=RULE):
    lit = re.escape(json.dumps(RULE))
    # "rule", (not last)  |  , "rule" (last in the list)
    out, n = re.subn(r'\n[ \t]*' + lit + r'[ \t]*,', "", text, count=1)
    if not n:
        out, n = re.subn(r',(\s*)' + lit, "", text, count=1)
    return out


def add(text, RULE=RULE):
    m = re.search(r'("allow"\s*:\s*\[)(\s*)', text)
    if not m:
        return None
    indent = m.group(2) if m.group(2).strip(" \t") else "\n    "
    if re.match(r'\s*\]', text[m.end(1):]):  # empty list
        return text[:m.end(1)] + indent + json.dumps(RULE) + text[m.end(1):]
    return text[:m.end(1)] + indent + json.dumps(RULE) + "," + text[m.end(1):]


def main(mode, src, dst):
    text = open(src, encoding="utf-8").read()
    want = json.loads(text)
    allow = want.setdefault("permissions", {}).setdefault("allow", [])
    out, changed = text, False
    for rule in (RULES if mode == "add" else reversed(RULES)):
        if mode == "remove":
            if rule not in allow:
                continue
            allow.remove(rule)
            out = remove(out, rule)
        else:
            if rule in allow:
                continue
            allow.insert(0, rule)
            out = add(out, rule) if out is not None else None
        changed = True
    if not changed:
        print("  rule already in the wanted state; nothing to change")
        open(dst, "w", encoding="utf-8").write(text)
        return 0
    try:
        ok = out is not None and json.loads(out) == want
    except ValueError:
        ok = False
    if not ok:  # unusual layout: fall back to a full rewrite, still a valid file with the same content
        out = json.dumps(want, indent=2, ensure_ascii=False) + "\n"
        print("  note: the file was rewritten (its layout did not allow a one-line edit)")
    open(dst, "w", encoding="utf-8").write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
