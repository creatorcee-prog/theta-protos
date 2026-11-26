"""The live view (server/live.py + browser.live_*) against a fake browser on the real browser worker thread:
sign-in, state, frames (JPEG, phone viewport, the 4 fps cap, 429), coordinate mapping for taps, and the refusals
(submit-looking taps, password fields, Enter in a form, private URLs). No network, no real browser.
Run: python3 tests/test_live.py"""
import http.client
import json
import os
import sys
import tempfile
import threading
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp())
os.environ.pop("THETA_BROWSER", None)
from server import app as appmod, browser, db, ext, live, tools  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail!r}"[:500]))
    if not cond:
        FAILED.append(name)


db.init()
ext.reset()
tools._ext_reset()

DNS = {"example.com": ["93.184.215.14"], "www.iana.org": ["192.0.43.8"], "shop.example": ["93.184.215.20"]}


def resolve(host, port):
    if host in DNS:
        return DNS[host]
    import ipaddress
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        raise OSError("no such host")


browser._resolve = resolve
browser._host_ok.clear()

# pages: elements with a box in relative coordinates (x0, y0, x1, y1) of the viewport
SITE = {
    "https://example.com/": ("Example Domain", [
        {"tag": "a", "label": "Learn more", "href": "https://www.iana.org/help/example-domains", "box": (0, .30, 1, .35)},
        {"tag": "button", "type": "submit", "label": "Place order", "inForm": True, "form": 0, "box": (0, .50, 1, .55)},
        {"tag": "input", "type": "password", "name": "pw", "label": "Password", "inForm": True, "form": 0,
         "editable": True, "box": (0, .60, 1, .65)},
        {"tag": "input", "type": "text", "name": "fullname", "label": "Full name", "inForm": True, "form": 0,
         "editable": True, "box": (0, .70, 1, .75)},
        {"tag": "input", "type": "search", "name": "q", "label": "Search", "inForm": True, "form": 1, "search": True,
         "editable": True, "box": (0, .80, 1, .85)},
        {"tag": "a", "label": "Delete my account", "href": "https://shop.example/delete", "box": (0, .90, 1, .95)}]),
    "https://www.iana.org/help/example-domains": ("Example Domains", []),
}
LOG = {"shots": [], "clicks": [], "typed": [], "keys": [], "wheel": [], "viewports": []}


class Req:
    def __init__(self, url):
        self.url, self.redirected_from = url, None


class Resp:
    def __init__(self, url):
        self.request = Req(url)


class Mouse:
    def __init__(self, page):
        self.page = page

    def click(self, x, y):
        LOG["clicks"].append((round(x, 2), round(y, 2)))
        e = self.page.at(x, y)
        if e and e["tag"] == "a":
            self.page.history.append(self.page.url)
            self.page.url = e["href"]
        self.page.focus = e if e and e.get("editable") else None

    def wheel(self, dx, dy):
        LOG["wheel"].append(dy)


class Keyboard:
    def __init__(self, page):
        self.page = page

    def type(self, text):
        LOG["typed"].append(((self.page.focus or {}).get("name"), text))

    def press(self, key):
        LOG["keys"].append(key)


class Page:
    def __init__(self, ctx):
        self.ctx, self.url, self.focus = ctx, "about:blank", None
        self.viewport_size = dict(ctx.viewport)
        self.mouse, self.keyboard = Mouse(self), Keyboard(self)
        self.history = []

    def at(self, x, y):
        vw, vh = self.viewport_size["width"], self.viewport_size["height"]
        for e in SITE.get(self.url, ("", []))[1]:
            x0, y0, x1, y1 = e["box"]
            if x0 * vw <= x <= x1 * vw and y0 * vh <= y <= y1 * vh:
                return {k: v for k, v in e.items() if k != "box"}
        return None

    def goto(self, url, wait_until=None, timeout=None):
        if url not in SITE and url != "about:blank":
            raise Exception("net::ERR_NAME_NOT_RESOLVED")
        if self.url.startswith("http"):
            self.history.append(self.url)
        self.url, self.focus = url, None
        return Resp(url)

    def go_back(self, timeout=None):
        if self.history:
            self.url = self.history.pop()

    def wait_for_load_state(self, *a, **k):
        pass

    def evaluate(self, js, arg=None):
        if js == browser.POINT_JS:
            return self.at(*arg)
        if js == browser.FOCUS_JS:
            return dict(self.focus) if self.focus else {"tag": "body", "type": "", "editable": False}
        if js == browser.UNTARGET_JS:
            return None
        if js == browser.SNAPSHOT_JS:
            t, els = SITE.get(self.url, ("", []))
            return {"title": t, "text": t, "els": []}
        return None

    def title(self):
        return SITE.get(self.url, ("", []))[0]

    def set_viewport_size(self, vp):
        LOG["viewports"].append(dict(vp))
        self.viewport_size = dict(vp)

    def screenshot(self, **kw):
        LOG["shots"].append(kw)
        return b"\xff\xd8\xff\xe0FAKEJPEG" + self.url.encode() + b"\xff\xd9"


class Context:
    def __init__(self, viewport):
        self.viewport = viewport
        self.pages = []

    def route(self, pattern, fn):
        pass

    def new_page(self):
        p = Page(self)
        self.pages.append(p)
        return p

    def close(self):
        pass


class Browser:
    def new_context(self, viewport=None, **kw):
        return Context(viewport)

    def close(self):
        pass


class PW:
    def stop(self):
        pass


browser._launch = lambda: (PW(), Browser())
live.reset()

# ---------------------------------------------------------------- over HTTP
httpd = appmod.make("127.0.0.1", 0)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
KEY = {"x-protos-key": "k"}


def call(method, path, body=None, headers=KEY):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    h = dict(headers or {})
    if body is not None:
        h["Content-Type"] = "application/json"
    c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
    r = c.getresponse()
    raw = r.read()
    out = (r.status, r.getheader("Content-Type") or "", raw, {k.lower(): v for k, v in r.getheaders()})
    c.close()
    return out


def j(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return {}


# signed-in only
for m, p in (("GET", "/api/live"), ("GET", "/api/live/frame.jpg"), ("POST", "/api/live/act")):
    s, *_ = call(m, p, {"type": "back"} if m == "POST" else None, headers={})
    check(f"{m} {p} needs sign-in", s == 401, s)
s, *_ = call("GET", "/api/live", headers={"x-protos-key": "wrong"})
check("a wrong key is refused", s == 401)

# no browser session yet
s, _, raw, _ = call("GET", "/api/live")
check("no session: {active: false}", s == 200 and j(raw) == {"active": False, "url": "", "title": "", "ts": None}, raw)
s, _, raw, _ = call("GET", "/api/live/frame.jpg")
check("no session: frame 404 with the plain message", s == 404 and
      j(raw).get("error") == "Theta isn't using its browser right now.", raw)
s, _, raw, _ = call("POST", "/api/live/act", {"type": "tap", "x": .5, "y": .5})
check("no session: act 404", s == 404 and "isn't using its browser" in j(raw).get("error", ""), raw)

# Theta opens a page (the model's tool), then the user watches
ok, out = tools.execute("browse_open", {"url": "https://example.com/"}, {"bot": "theta"})
check("setup: browse_open on the fake browser", ok and "Example Domain" in out, out)
s, _, raw, _ = call("GET", "/api/live")
st = j(raw)
check("GET /api/live: active, url, title, ts", s == 200 and st["active"] is True and st["url"] ==
      "https://example.com/" and st["title"] == "Example Domain" and isinstance(st["ts"], float), st)

s, ctype, raw, hd = call("GET", "/api/live/frame.jpg")
check("frame: a JPEG", s == 200 and ctype == "image/jpeg" and raw.startswith(b"\xff\xd8") and
      hd.get("cache-control") == "no-store", (s, ctype, raw[:10]))
check("frame: quality 60 JPEG, phone viewport", LOG["shots"][-1].get("type") == "jpeg"
      and LOG["shots"][-1].get("quality") == 60 and LOG["viewports"] == [{"width": 390, "height": 844}]
      and hd.get("x-frame-width") == "390" and hd.get("x-frame-height") == "844", (LOG["shots"], LOG["viewports"]))
check("frame: has the security headers", "default-src 'self'" in hd.get("content-security-policy", ""))

# the 4 fps cap: a request within 250 ms gets the same picture, no new screenshot
n = len(LOG["shots"])
s, _, raw2, hd2 = call("GET", "/api/live/frame.jpg")
check("rate limit: a second frame inside 250 ms is the cached one", s == 200 and raw2 == raw
      and hd2.get("x-frame-cached") == "1" and len(LOG["shots"]) == n, (hd2, len(LOG["shots"]), n))
time.sleep(0.27)
s, _, _, hd3 = call("GET", "/api/live/frame.jpg")
check("rate limit: after 250 ms a fresh screenshot", s == 200 and hd3.get("x-frame-cached") == "0"
      and len(LOG["shots"]) == n + 1)
# at most 4 screenshots a second however hard it's polled, and a flood gets 429
live.reset()
n = len(LOG["shots"])
statuses = []
t0 = time.monotonic()
while time.monotonic() - t0 < 0.9:
    statuses.append(call("GET", "/api/live/frame.jpg")[0])
check("rate limit: <= 4 screenshots in ~1 s of hammering", len(LOG["shots"]) - n <= 4, len(LOG["shots"]) - n)
check("rate limit: a flood of requests gets 429", 429 in statuses and 200 in statuses, statuses[:20])
live.reset()
# the unit: _frame with explicit times
live.reset()
d1 = live._frame("theta", now=100.0)
d2 = live._frame("theta", now=100.1)
check("_frame: cached inside FRAME_MIN", d2[2] is True and d1[2] is False)

# ---------------------------------------------------------------- acting
# a tap at relative (0.5, 0.32) is (195, 270.08) on a 390x844 screen: the "Learn more" link
s, _, raw, _ = call("POST", "/api/live/act", {"type": "tap", "x": 0.5, "y": 0.32})
res = j(raw)
check("tap: relative coordinates map to viewport pixels", LOG["clicks"][-1] == (195.0, 270.08), LOG["clicks"])
check("tap on 'Learn more' follows the link; the new URL comes back", s == 200 and res.get("ok") is True and
      res["url"] == "https://www.iana.org/help/example-domains" and res["title"] == "Example Domains", res)
s, _, raw, _ = call("GET", "/api/live")
check("state follows the user's tap", j(raw)["url"] == "https://www.iana.org/help/example-domains")
s, _, raw, _ = call("POST", "/api/live/act", {"type": "back"})
check("back", s == 200 and j(raw)["url"] == "https://example.com/", raw)

nclicks = len(LOG["clicks"])
s, _, raw, _ = call("POST", "/api/live/act", {"type": "tap", "x": 0.5, "y": 0.52})
check("tap on a submit button is refused: Use Approve in chat", s == 403 and j(raw).get("refused") is True
      and "Use Approve in chat for that." in j(raw)["error"] and len(LOG["clicks"]) == nclicks, raw)
s, _, raw, _ = call("POST", "/api/live/act", {"type": "tap", "x": 0.5, "y": 0.92})
check("tap on a 'Delete my account' link is refused", s == 403 and len(LOG["clicks"]) == nclicks, raw)

s, _, raw, _ = call("POST", "/api/live/act", {"type": "type", "text": "hello"})
check("type with no field focused: tap a field first", s == 403 and "Tap a text field first" in j(raw)["error"], raw)
call("POST", "/api/live/act", {"type": "tap", "x": 0.5, "y": 0.62})  # focus the password field
s, _, raw, _ = call("POST", "/api/live/act", {"type": "type", "text": "hunter2"})
check("typing into a password field is refused", s == 403 and "password" in j(raw)["error"].lower()
      and not any(t == "hunter2" for _, t in LOG["typed"]), raw)
call("POST", "/api/live/act", {"type": "tap", "x": 0.5, "y": 0.72})  # the name field
s, _, raw, _ = call("POST", "/api/live/act", {"type": "type", "text": "Sam Lee"})
check("typing into a text field works", s == 200 and LOG["typed"][-1] == ("fullname", "Sam Lee"), LOG["typed"])
s, _, raw, _ = call("POST", "/api/live/act", {"type": "key", "key": "Enter"})
check("Enter in a form field (would submit) is refused", s == 403 and "Use Approve in chat" in j(raw)["error"]
      and "Enter" not in LOG["keys"], raw)
call("POST", "/api/live/act", {"type": "tap", "x": 0.5, "y": 0.82})  # the search box
s, _, raw, _ = call("POST", "/api/live/act", {"type": "key", "key": "Enter"})
check("Enter in a search box is fine", s == 200 and LOG["keys"][-1] == "Enter", raw)
s, _, raw, _ = call("POST", "/api/live/act", {"type": "key", "key": "Tab"})
check("other keys pass through", s == 200 and LOG["keys"][-1] == "Tab")
s, _, raw, _ = call("POST", "/api/live/act", {"type": "scroll", "dy": 0.5})
check("scroll dy is a fraction of the screen height", s == 200 and LOG["wheel"][-1] == 422.0, LOG["wheel"])

for url in ("http://10.0.0.1/admin", "http://localhost:8780/api/turns", "javascript:alert(1)", "file:///etc/passwd",
            "http://169.254.169.254/latest/meta-data"):
    s, _, raw, _ = call("POST", "/api/live/act", {"type": "goto", "url": url})
    check(f"goto {url} is refused like browse_open", s == 403 and j(raw).get("refused") is True, (s, raw))
s, _, raw, _ = call("POST", "/api/live/act", {"type": "goto", "url": "www.iana.org/help/example-domains"})
check("goto a public URL (https:// added)", s == 200 and j(raw)["url"] == "https://www.iana.org/help/example-domains",
      raw)
s, _, raw, _ = call("POST", "/api/live/act", {"type": "reload"})
check("reload is a fresh GET of the same page", s == 200 and j(raw)["url"] == "https://www.iana.org/help/example-domains")

for body, why in (({"type": "tap", "x": 1.5, "y": 0.2}, "x out of range"), ({"type": "tap", "x": "0.5", "y": 0.2},
                  "x not a number"), ({"type": "tap", "x": True, "y": 0.2}, "x a bool"),
                  ({"type": "key", "key": "F12"}, "unknown key"), ({"type": "type", "text": ""}, "empty text"),
                  ({"type": "type", "text": "x" * 501}, "text too long"), ({"type": "scroll", "dy": 50}, "dy too big"),
                  ({"type": "dance"}, "unknown type"), ({"type": "goto"}, "no url")):
    s, _, raw, _ = call("POST", "/api/live/act", body)
    check(f"bad act refused with 400 ({why})", s == 400, (s, raw))
s, *_ = call("GET", "/api/live/act")
check("act is POST only", s == 405)
s, *_ = call("POST", "/api/live", {})
check("state is GET only", s == 405)
s, *_ = call("GET", "/api/live?bot=nobody")
check("unknown bot 404", s == 404)

# the clean_act unit
check("clean_act keeps only the known fields", live.clean_act({"type": "tap", "x": 0, "y": 1, "evil": 1}) ==
      {"type": "tap", "x": 0.0, "y": 1.0})

# closing the session: the live view says so
browser._engine.call(lambda eng: eng.close("theta"))
s, _, raw, _ = call("GET", "/api/live")
check("after the session closes: inactive again", j(raw)["active"] is False)
live.reset()
s, *_ = call("GET", "/api/live/frame.jpg")
check("after the session closes: frame 404", s == 404)

httpd.shutdown()
print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all live checks passed'}")
sys.exit(1 if FAILED else 0)
