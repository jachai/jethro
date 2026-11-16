"""0.2.0 page: tile functions (run under node), and string checks on the template."""
import json
import os
import shutil
import subprocess
import unittest

TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "page", "template.html")
NODE = shutil.which("node")


def tpl():
    return open(TPL, encoding="utf-8").read()


@unittest.skipUnless(NODE, "node not installed")
class TileTest(unittest.TestCase):
    def run_js(self, body):
        t = tpl()
        code = t[t.index("/*TILE-START*/"):t.index("/*TILE-END*/")] + "\n" + body
        return json.loads(subprocess.run([NODE], input=code, capture_output=True, encoding="utf-8", check=True).stdout)

    def test_initials(self):
        titles = ["Garden plan", "x", "  change-orders  dashboard", "\U0001F680\U0001F680", "!!! ???", "", "日本語の資料",
                  "Бюджет 2026", "single"]
        out = self.run_js("console.log(JSON.stringify(%s.map(initials)))" % json.dumps(titles))
        self.assertEqual(out[0], "GP")
        self.assertEqual(out[1], "X")
        self.assertEqual(out[2], "CO")
        self.assertEqual(out[3:6], ["?", "?", "?"])
        self.assertEqual(out[6], "日本語の資料"[:2])
        self.assertEqual(out[7], "БР"[0] + "2")
        self.assertEqual(out[8], "SI")

    def test_colors_stable_and_distinct(self):
        out = self.run_js(
            'const ids=[];for(let i=0;i<300;i++)ids.push("id"+i+"zq");'
            'const c=ids.map(i=>tileColors(i).join("|"));'
            'console.log(JSON.stringify({same:tileColors("abc").join()===tileColors("abc").join(),distinct:new Set(c).size,'
            'svgSame:initialsTile("abc","T","red")===initialsTile("abc","T","red")}))')
        self.assertTrue(out["same"] and out["svgSame"])
        self.assertGreaterEqual(out["distinct"], 200)

    def test_markup_is_escaped(self):
        out = self.run_js('console.log(JSON.stringify(initialsTile("<id>","<script>&","\\"><b>")))')
        self.assertNotIn("<script>", out)
        self.assertNotIn("<b>", out)
        self.assertNotIn("&<", out)


class TemplateStringsTest(unittest.TestCase):
    def test_strings(self):
        t = tpl()
        self.assertNotIn("Shared with me", t)
        self.assertNotIn("PH-START", t)
        self.assertIn('<link rel="icon" href="favicon.ico" sizes="any">', t)
        self.assertIn('<link rel="icon" type="image/svg+xml" href="__FAVICON_SVG__">', t)
        self.assertIn('r.url.startsWith("https://claude.ai/") ? r.url : ""', t)
        self.assertIn('if (!t) return el("span", "dim", "unknown");', t)
        for s in ('id="status"', "as of build", "Page may be stale", "setInterval", "/*OLD-START*/", "older artifact",
                  "Describe older", "/artifact-explorer:refresh older", "aria-expanded", "navigator.clipboard", "#older",
                  "prefers-reduced-motion"):
            self.assertIn(s, t)


if __name__ == "__main__":
    unittest.main()
