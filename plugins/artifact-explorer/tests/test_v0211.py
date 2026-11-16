"""0.2.11: Jonathan's page review (named windows, thumbnail-only card links, Open button, topic chip colors)."""
import json
import os
import shutil
import subprocess
import unittest

TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "page", "template.html")
NODE = shutil.which("node")


def tpl():
    return open(TPL, encoding="utf-8").read()


STUB = """
function el(tag, cls, text){ return {tag, className: cls || "", textContent: text || "", attrs: {},
  setAttribute(k, v){ this.attrs[k] = v; }}; }
"""


@unittest.skipUnless(NODE, "node not installed")
class LinkTest(unittest.TestCase):
    def run_js(self, body):
        t = tpl()
        code = STUB + t[t.index("/*LINK-START*/"):t.index("/*LINK-END*/")] + "\n" + body
        return json.loads(subprocess.run([NODE], input=code, capture_output=True, encoding="utf-8", check=True).stdout)

    def test_named_window_per_artifact(self):
        out = self.run_js("""
const a = {id: "DemoShortId00000000002", url: "https://claude.ai/artifact/DemoShortId00000000002"};
const b = {id: "other", url: "https://claude.ai/artifact/other"};
const o1 = openBtn(a), o2 = openBtn(a), o3 = openBtn(b);
console.log(JSON.stringify({t1: o1.target, t2: o2.target, t3: o3.target, href: o1.href, text: o1.textContent,
  bad: openBtn({id: "x", url: "javascript:alert(1)"}), none: openBtn({id: "y", url: ""}),
  odd: winName({id: "a b/c"})}));
""")
        self.assertEqual(out["t1"], "ae-DemoShortId00000000002")
        self.assertEqual(out["t1"], out["t2"])
        self.assertNotEqual(out["t1"], out["t3"])
        self.assertEqual(out["href"], "https://claude.ai/artifact/DemoShortId00000000002")
        self.assertEqual(out["text"], "Open")
        self.assertIsNone(out["bad"])
        self.assertIsNone(out["none"])
        self.assertEqual(out["odd"], "ae-a_b_c")


class TemplateTest(unittest.TestCase):
    def test_cards_link_only_thumbnail(self):
        t = tpl()
        self.assertNotIn("stretch", t)  # no link stretched over the whole card or row
        self.assertIn('b.appendChild(el("h3")).appendChild(titleText(r));', t)
        self.assertIn('el(link ? "a" : "div", cls)', t)  # the thumbnail is the link
        self.assertIn('if (cols.indexOf("open") < 0) cols.push("open");', t)

    def test_topic_chips_share_pill_colors(self):
        t = tpl()
        self.assertIn('b.classList.add("tpc"); topicTint(b, topic);', t)
        self.assertIn('function topicPill(t, tag){ return topicTint(el(tag, "tp", t), t); }', t)


if __name__ == "__main__":
    unittest.main()
