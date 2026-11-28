"""Static checks for the phone app (web/). Standard library only: python3 tests/test_web.py

The browser checks (screenshots, streaming, markdown safety, no console errors) are in tests/shots.js.
"""
import json
import os
import re
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")


def read(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as f:
        return f.read()


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path + " is not a PNG"
    return struct.unpack(">II", head[16:24])


class WebApp(unittest.TestCase):
    def test_files_exist(self):
        for name in ("index.html", "app.js", "style.css", "orb.js", "demo.js", "sw.js", "manifest.webmanifest",
                     "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png", "icons/badge-72.png"):
            self.assertTrue(os.path.isfile(os.path.join(WEB, name)), name)

    def test_icons_sizes(self):
        for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180), ("badge-72.png", 72)):
            self.assertEqual(png_size(os.path.join(WEB, "icons", name)), (size, size), name)

    def test_manifest(self):
        m = json.loads(read("manifest.webmanifest"))
        self.assertEqual(m["display"], "standalone")
        self.assertEqual(m["name"], "Theta")
        self.assertEqual(m["background_color"].lower(), "#141414")
        sizes = {i["sizes"] for i in m["icons"]}
        self.assertTrue({"192x192", "512x512"} <= sizes)
        for icon in m["icons"]:  # served from /static/ by server/app.py
            self.assertTrue(icon["src"].startswith("/static/icons/"), icon["src"])
            self.assertTrue(os.path.isfile(os.path.join(WEB, icon["src"][len("/static/"):])), icon["src"])

    def test_index_references_local_files_only(self):
        html = read("index.html")
        self.assertNotRegex(html, r"""(src|href)=["']https?://""", "no external CDNs")
        self.assertNotIn("<script>", html, "no inline scripts (the server's CSP is script-src 'self')")
        self.assertNotRegex(html, r"\son[a-z]+=", "no inline event handlers")
        for ref in re.findall(r"""(?:src|href)=["'](/static/[^"']+)["']""", html):
            self.assertTrue(os.path.isfile(os.path.join(WEB, ref[len("/static/"):])), ref)
        self.assertIn('href="/manifest.webmanifest"', html)
        self.assertIn("viewport-fit=cover", html)

    def test_no_external_urls_in_code(self):
        for name in ("app.js", "orb.js", "sw.js", "style.css"):
            src = read(name)
            self.assertNotRegex(src, r"""(import|url\(|fetch\()\s*["']?https?://""", name)
            self.assertNotIn("@import", src, name)

    def test_no_innerhtml(self):
        # model text is rendered by building DOM nodes; nothing assigns HTML strings
        for name in ("app.js", "orb.js", "demo.js"):
            src = read(name)
            for bad in (".innerHTML", ".outerHTML", ".insertAdjacentHTML", "document.write", "eval(", "new Function"):
                self.assertNotIn(bad, src, f"{name} uses {bad}")

    def test_links_are_https_only(self):
        src = read("app.js")
        self.assertIn('u.protocol === "https:"', src)

    def test_api_contract(self):
        src = read("app.js")
        for path in ("/api/health", "/api/messages?bot=", "/api/chat", "/api/inbox?since=", "/api/login", "/api/push/key",
                     "/api/push/subscribe", "/api/push/test", "/api/connections", "/api/settings"):
            self.assertIn(path, src, path)
        self.assertIn("getReader()", src, "SSE is read from a ReadableStream")
        for ev in ('"user"', '"route"', '"delta"', '"done"', '"error"'):
            self.assertIn(f"ev === {ev}", src, ev)
        self.assertIn("POLL_MS = 20000", src)
        self.assertIn("client_id", src)

    def test_service_worker(self):
        sw = read("sw.js")
        for needle in ('addEventListener("install"', 'addEventListener("fetch"', 'addEventListener("push"',
                       'addEventListener("notificationclick"', "showNotification", "openWindow", "focus()", "/?m=",
                       '"/api/"'):
            self.assertIn(needle, sw, needle)
        self.assertIn("visibilityState", sw, "no notification while the app is open and visible")

    def test_phone_first_css(self):
        css = read("style.css")
        for needle in ("env(safe-area-inset-top", "env(safe-area-inset-bottom", "100dvh", "prefers-reduced-motion", "#141414", "#222", "#f2f2f2"):
            self.assertIn(needle, css, needle)
        self.assertNotIn(".typing", css, "no three-dot typing indicator: the globe is the status")

    def test_orb(self):
        orb = read("orb.js")
        self.assertIn("dots: 520", orb)
        for needle in ('"converge"', '"signal"', '"thinking"', '"speaking"', '"waiting"', "ack()", "done()", "sort(", "star", "hexagon"):
            self.assertIn(needle, orb, needle)

    def test_no_foreign_brand(self):
        for name in ("index.html", "app.js", "demo.js", "style.css", "manifest.webmanifest"):
            src = read(name).lower()
            for word in ("chester", "grok", "upgrade"):
                self.assertNotIn(word, src, f"{name} mentions {word}")
            self.assertNotRegex(src.replace("/api/bots", ""), r"\bbots\b", name)  # the API path is the spec's

    def test_demo_backend(self):
        demo = read("demo.js")
        self.assertIn("text/event-stream", demo)
        self.assertIn("8000", demo, "one proactive message after about 8 s")
        self.assertIn("proactive: true", demo)


class VersionInStep(unittest.TestCase):
    def test_app_and_server_versions_match(self):
        import re as _re
        with open(os.path.join(WEB, "app.js")) as f:
            app = f.read()
        with open(os.path.join(WEB, "..", "server", "__init__.py")) as f:
            srv = f.read()
        a = _re.search(r'APP_VERSION = "([^"]+)"', app).group(1)
        s = _re.search(r'__version__ = "([^"]+)"', srv).group(1)
        self.assertEqual(a, s, "bump web/app.js APP_VERSION and server/__init__.py __version__ together")
        with open(os.path.join(WEB, "index.html")) as f:
            self.assertIn('id="login-ver"', f.read())


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
