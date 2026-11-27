"""Theta's browser in real Chromium, doing what a person does on the web, against a local site (tests/site/):
cookie walls, search, links that open new tabs, popups that close themselves, hover menus, web components (shadow
DOM), iframes from another site, a booking form with a date, radios, a checkbox, a custom dropdown and an
autocomplete box, infinite scroll, a page that loads slowly, alerts and "Are you sure?" dialogs, photo uploads, a
rich-text box, a two-step sign-in with an authenticator code that stays signed in, and Theta's screen (live.py):
pictures, the user's own taps and typing.

Every step goes through the same tools the model calls (browse_open, browse_act, browse_submit, browse_sign_in),
so the checks read the same text the model reads. The private-address guard stays on: the site's hosts (*.test)
resolve to a public address for Theta's check, and Chromium maps them to this machine. Skips when Playwright or
Chromium isn't installed."""
import http.cookies, http.server, json, os, re, socketserver, sys, tempfile, threading, time
import urllib.parse
sys.dont_write_bytecode = True
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_DATA=tempfile.mkdtemp())
os.environ.pop("THETA_BROWSER", None)
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP: Playwright for Python isn't installed (pip install playwright)")
    sys.exit(0)
from server import bitwarden, browser, db, ext, live, tools, uploads, vault

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
SECRET_PW, SEED = "lamp-club-correct-horse-77", "JBSWY3DPEHPK3PXP"
HITS = {"private": 0, "book": None}


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        g = sys._getframe(1).f_globals  # what the model would have read at that step
        for k in ("out", "out2"):
            if isinstance(g.get(k), str):
                print(f"--- {k}:\n{g[k][:1500]}")
        sys.exit(1)


# ---------------------------------------------------------------- the local site

class Site(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cookies(self):
        c = http.cookies.SimpleCookie(self.headers.get("Cookie") or "")
        return {k: v.value for k, v in c.items()}

    def _form(self):
        n = int(self.headers.get("Content-Length") or 0)
        return {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode(), keep_blank_values=True).items()}

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/private.png":
            HITS["private"] += 1
            return self._send(200, b"", "image/png")
        if u.path == "/search":
            q = urllib.parse.parse_qs(u.query).get("q", [""])[0]
            items = [n for n in ("Arc floor lamp", "Halo desk lamp", "Tripod lamp") if q in ("all", "") or q.lower() in n.lower()]
            lis = "".join(f'<li><a href="/item?n={urllib.parse.quote(n)}">{n}</a></li>' for n in items)
            return self._send(200, f"<!doctype html><title>Results for {q}</title><h1>{len(items)} results for {q}</h1><ul>{lis}</ul>".encode())
        if u.path == "/bing":  # shaped like Bing's results page
            q = urllib.parse.parse_qs(u.query).get("q", [""])[0]
            items = "".join(f'<li class="b_algo"><h2><a href="https://lamps.test/{i}">{q} result {i}</a></h2>'
                            f'<div class="b_caption"><p>Snippet {i} about {q}.</p></div></li>' for i in range(1, 8))
            items += '<li class="b_algo"><h2><a href="http://127.0.0.1/x">private</a></h2></li>'
            return self._send(200, f"<!doctype html><title>{q} - Search</title><ol id=b_results>{items}</ol>".encode())
        if u.path == "/account":
            if self._cookies().get("sid") == "good":
                return self._send(200, b"<!doctype html><title>Your account</title><h1>Welcome back, Sam</h1><p>Lamp Club points: 120</p>")
            return self._send(303, headers=[("Location", "/login.html")])
        name = u.path.strip("/") or "index.html"
        path = os.path.realpath(os.path.join(SITE, name))
        if not path.startswith(os.path.realpath(SITE)) or not os.path.isfile(path):
            return self._send(404, b"not found")
        with open(path, "rb") as f:
            body = f.read().replace(b"PORT", str(PORT).encode())
        return self._send(200, body)

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        f = self._form()
        if u.path == "/book":
            HITS["book"] = f
            return self._send(200, ("Booked. " + "; ".join(f"{k}={v}" for k, v in sorted(f.items()))).encode(), "text/plain")
        if u.path == "/signin":
            if f.get("pw") != SECRET_PW:
                return self._send(303, headers=[("Location", "/password.html?wrong=1")])
            return self._send(303, headers=[("Location", "/otp.html"), ("Set-Cookie", "pend=1; Path=/")])
        if u.path == "/verify":
            if self._cookies().get("pend") == "1" and f.get("code") == bitwarden.totp(SEED):
                return self._send(303, headers=[("Location", "/account"),
                                                ("Set-Cookie", "sid=good; Path=/; Max-Age=3600; HttpOnly")])
            return self._send(303, headers=[("Location", "/otp.html?wrong=1")])
        return self._send(404, b"not found")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


web = Server(("127.0.0.1", 0), Site)
PORT = web.server_address[1]
threading.Thread(target=web.serve_forever, daemon=True).start()

# The sign-in site is plain http here: this container's network resets TLS to made-up hostnames even on this machine.
# The https-only rule for sign-ins is vault.pick's, checked in test_browser.py; here pick is stubbed.
SHOP, NEWS, LOGIN = f"http://shop.test:{PORT}", f"http://news.test:{PORT}", f"http://login.test:{PORT}"

# ---------------------------------------------------------------- Theta's browser, pointed at it
real_resolve = browser._resolve
browser._resolve = lambda host, port: ["93.184.216.34"] if host.endswith(".test") else real_resolve(host, port)
browser._host_ok.clear()


def launch():
    pw = sync_playwright().start()
    args = ["--disable-dev-shm-usage", "--disable-gpu", "--host-resolver-rules=MAP *.test 127.0.0.1",
            "--no-proxy-server"]  # this machine's proxy settings would catch *.test
    try:
        b = pw.chromium.launch(headless=True, args=args)
    except Exception:  # noqa: BLE001  this container's own Chromium
        b = pw.chromium.launch(headless=True, args=args, executable_path="/opt/pw-browsers/chromium/chrome-linux/chrome"
                               if os.path.exists("/opt/pw-browsers/chromium/chrome-linux/chrome") else None)
    return pw, b


browser._launch = launch
db.init()
ext.reset(); tools._ext_reset()
CTX = {"bot": "theta"}


def run(name, args):
    return tools.execute(name, args, CTX)


def act(*actions):
    return run("browse_act", {"actions": list(actions)})


def ref(out, label, kind=None):
    """The ref of the element whose line shows this label (and kind: button, link, field...)."""
    for line in out.splitlines():
        m = re.match(r"\[(\w+)\] (.*)", line)
        if m and re.search('"' + re.escape(label) + '[^"]*"', m.group(2)) and (kind is None or m.group(2).startswith(kind)):
            return m.group(1)
    raise AssertionError(f"no {kind or 'element'} {label!r} in:\n{out}")


def approve(args):
    tools.preview("browse_submit", args)
    return tools.run_approved({"tool": "browse_submit", "args": args, "bot": "theta"})


t0 = time.time()
# ---------------------------------------------------------------- opening a page
ok, out = run("browse_open", {"url": SHOP + "/"})
check("opens a real page: title, text and its buttons and links", ok and "Page: Lamp Shop" in out
      and "Lamps for every room" in out and "Accept all" in out)
check("a request the page makes to a private address is blocked, and said so", "request(s) to private or local" in out
      and HITS["private"] == 0)
check("a web component's field and button (shadow DOM) are listed", '"Promo code"' in out and '"Apply code"' in out)
check("an iframe from another site is read too, with its own refs", "[inside a frame from news.test]" in out
      and re.search(r"\[f\d+e\d+\] email field \"Email\"", out) is not None)

# ---------------------------------------------------------------- the cookie wall
ok, out2 = act({"do": "click", "ref": ref(out, "Products", "link")})
check("a click under a cookie wall says what's in the way", not ok and "covering" in out2 and "cookie banner" in out2)
ok, out = act({"do": "click", "ref": ref(out, "Accept all")})
check("accepting cookies clears it", ok and '"Accept all"' not in out)
ok, out = act({"do": "click", "ref": ref(out, "Products", "link")})
check("then the link works", ok and "3 results for all" in out and "/search?q=all" in out)
ok, out = act({"do": "back"})
check("back returns to the shop", ok and "Page: Lamp Shop" in out)

# ---------------------------------------------------------------- search
ok, out = act({"do": "type", "ref": ref(out, "Search lamps"), "text": "arc", "enter": True})
check("typing into a search box and pressing Enter searches", ok and "1 results for arc" in out and "Arc floor lamp" in out)
ok, out = act({"do": "click", "ref": ref(out, "Arc floor lamp", "link")})
check("a result opens (a 404 here, read as the page says)", ok and "/item?n=Arc" in out)
run("browse_open", {"url": SHOP + "/"})
ok, out = act({"do": "click", "ref": ref(run("browse_open", {"url": SHOP + "/"})[1], "Accept all")})

# ---------------------------------------------------------------- new tabs and popups
ok, out = act({"do": "click", "ref": ref(out, "Deals", "link")})
check("a link that opens a new tab opens in Theta's one tab", ok and "Today's deals" in out and "tabs are open" not in out)
act({"do": "back"})
ok, out = run("browse_open", {"url": SHOP + "/"})
act({"do": "click", "ref": ref(out, "Accept all")})
ok, out = act({"do": "click", "ref": ref(out, "Open help")})
check("a popup window becomes the page, and the result says two tabs are open", ok and "Help center" in out
      and "Returns are free for 30 days" in out and "2 tabs are open" in out)
ok, out = act({"do": "click", "ref": ref(out, "Close help")})
check("when the popup closes itself, Theta is back on the page that opened it", ok and "Page: Lamp Shop" in out
      and "tabs are open" not in out)

# ---------------------------------------------------------------- hover menus
check("a menu's links are hidden until hovered", '"Order history"' not in out)
ok, out = act({"do": "hover", "ref": ref(out, "Account")})
check("hovering opens the menu", ok and '"Order history"' in out)
ok, out = act({"do": "hover", "ref": ref(out, "Account")}, {"do": "click", "ref": ref(out, "Order history", "link")})
check("and its link can be followed", ok and "Order 1042: Arc floor lamp" in out)
act({"do": "back"})

# ---------------------------------------------------------------- shadow DOM and iframes
ok, out = run("browse_open", {"url": SHOP + "/"})
act({"do": "click", "ref": ref(out, "Accept all")})
ok, out = act({"do": "type", "ref": ref(out, "Promo code"), "text": "SAVE10"}, {"do": "click", "ref": ref(out, "Apply code")})
check("typing and clicking inside a web component work", ok and "Code SAVE10 applied" in out)
email = ref(out, "Email", "email field")
ok, out = act({"do": "type", "ref": email, "text": "sam@example.com"})
check("typing into a field inside the iframe works", ok and re.search(r'email field "Email" = \'sam@example.com\'', out) is not None)
sub = ref(out, "Subscribe")
ok, out2 = act({"do": "click", "ref": sub})
check("the iframe's Subscribe submits, so it needs browse_submit", not ok and "browse_submit" in out2)
ok, out2 = approve({"url": SHOP + "/", "ref": sub, "fields": [{"ref": email, "text": "sam@example.com"}]})
print("   ", out2[:300]) if not ok else None
ok_, out = act({"do": "scroll", "text": "down"})
check("approved, it subscribes inside the frame", ok and "Subscribed sam@example.com" in out)

# ---------------------------------------------------------------- a full form
ok, out = run("browse_open", {"url": SHOP + "/book.html"})
f = {k: ref(out, k) for k in ("Full name", "Email", "Date", "Time", "Notes", "City")}
ok, out = act({"do": "type", "ref": f["Full name"], "text": "Sam Lee"},
              {"do": "type", "ref": f["Email"], "text": "sam@example.com"},
              {"do": "type", "ref": f["Date"], "text": "2026-12-04"},
              {"do": "select", "ref": f["Time"], "text": "13:00"},
              {"do": "select", "ref": ref(out, "Airport"), "text": "on"},
              {"do": "select", "ref": ref(out, "I need parking"), "text": "on"},
              {"do": "type", "ref": f["Notes"], "text": "Looking for a reading lamp"})
check("text, email, a date, a dropdown, a radio, a checkbox and a textarea all take their values", ok
      and "= '2026-12-04'" in out and "= '13:00'" in out and re.search(r'radio "Airport" \[x\]', out)
      and re.search(r'checkbox "I need parking" \[x\]', out))
ok, out = act({"do": "click", "ref": ref(out, "Occasion")})
check("a custom dropdown opens and shows its options", ok and '"Gift"' in out)
ok, out = act({"do": "click", "ref": ref(out, "Gift")})
check("and picking one sets it", ok and re.search(r'"Occasion[^"]*Gift"', out) is not None)
ok, out = act({"do": "type", "ref": f["City"], "text": "D"}, {"do": "key", "text": "ArrowDown"},
              {"do": "key", "text": "ArrowDown"}, {"do": "key", "text": "Enter"})
check("an autocomplete box: type, arrow down to a suggestion, Enter picks it (and submits nothing)", ok
      and "= 'Dallas'" in out and HITS["book"] is None)
ok, out2 = act({"do": "click", "ref": ref(out, "Book visit")})
check("the booking button needs the user's OK", not ok and "browse_submit" in out2 and HITS["book"] is None)
ok, out2 = approve({"url": SHOP + "/book.html", "ref": ref(out, "Book visit")})
b = HITS["book"] or {}
check("approved, every field arrives exactly as set", ok and b.get("name") == "Sam Lee" and b.get("date") == "2026-12-04"
      and b.get("time") == "13:00" and b.get("where") == "airport" and b.get("parking") == "yes"
      and b.get("occasion") == "Gift" and b.get("city") == "Dallas" and b.get("notes") == "Looking for a reading lamp")

# ---------------------------------------------------------------- infinite scroll, slow pages, dialogs, uploads, rich text
ok, out = run("browse_open", {"url": SHOP + "/catalog.html"})
check("a long list starts with its first items", "Item 15" in out and "Item 45" not in out)
for _ in range(6):
    ok, out = act({"do": "scroll", "text": "down"})
    if "Item 45" in out:
        break
check("scrolling loads more until the one wanted shows", ok and "Item 45" in out)

ok, out = run("browse_open", {"url": SHOP + "/spa.html"})
ok, out = act({"do": "click", "ref": ref(out, "Floor")})
check("a tab in a single-page app switches without a page load", ok and "Loading floor lamps" in out)
ok, out = act({"do": "wait", "text": "Tripod"})
check("waiting for words lets a slow part load", ok and "Floor lamps: Arc, Tripod, Torchiere" in out and "waited for" in out)
ok, out = act({"do": "click", "ref": ref(out, "Show tip")})
check("an alert is read out to Theta", ok and "The page popped up: alert 'Tip: warm white is 2700K'" in out)
rm = ref(out, "Remove item")
ok, out2 = act({"do": "click", "ref": rm})
check("a Remove button needs the user's OK", not ok and "browse_submit" in out2)
ok, out2 = approve({"url": SHOP + "/spa.html", "ref": rm})
ok_, out = act({"do": "scroll", "text": "up"})
check("approved, the page's own 'Are you sure?' is answered yes, and it's removed", ok and "Removed" in out)

png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82")
saved = uploads.save(png)
up_id = saved["id"] if isinstance(saved, dict) else saved
ok, out = act({"do": "upload", "ref": ref(out, "Photo"), "text": f"/api/uploads/{up_id}"})
check("a photo the user sent can be attached to a file field", ok and f"Attached {len(png)} bytes" in out)
ok, out2 = act({"do": "upload", "ref": ref(out, "Photo"), "text": "/etc/passwd"})
check("only the user's own photos can be attached, never a file from the server", not ok and "photo or file the user sent" in out2)
ok, out = act({"do": "type", "ref": ref(out, "Message"), "text": "Hello from Theta"})
check("a rich-text box (contenteditable) takes typing", ok and "Hello from Theta" in out)
ok, out2 = act({"do": "key", "ref": ref(out, "Message"), "text": "Enter"})
check("Enter in a message box is refused (chat boxes send on Enter)", not ok and "browse_submit" in out2)

# ---------------------------------------------------------------- signing in, and staying signed in
vault.available = lambda: True
vault.pick = lambda url, title=None: {"title": "Lamp Club", "id": "x", "hosts": ["login.test"], "src": "bitwarden"} \
    if urllib.parse.urlsplit(url).hostname == "login.test" else (_ for _ in ()).throw(tools.ToolError("no login"))
vault.secrets_for = lambda item: {"username": "sam@example.com", "password": SECRET_PW, "totp": bitwarden.totp(SEED)}
ok, out = run("browse_open", {"url": LOGIN + "/account"})
check("a page that needs an account sends Theta to sign in", ok and "Sign in to Lamp Club" in out)
ok, out = run("browse_sign_in", {})
check("browse_sign_in: email, Next, password, then an authenticator code, to the account", ok and "Welcome back, Sam" in out
      and "filled: username, password, code" in out)
check("and no password or code reaches the model", SECRET_PW not in out and bitwarden.totp(SEED) not in out)
browser._engine.call(lambda eng: eng.close("theta"))
check("the page closing keeps the sign-in (owner-only file)", "login.test" in browser.signed_in_sites()
      and oct(os.stat(browser._signins_path()).st_mode & 0o777) == "0o600")
ok, out = run("browse_open", {"url": LOGIN + "/account"})
check("the next time, Theta is still signed in", ok and "Welcome back, Sam" in out)
browser.forget_signins()
ok, out = run("browse_open", {"url": LOGIN + "/account"})
check("'Sign out everywhere' signs it out", ok and "Sign in to Lamp Club" in out and browser.signed_in_sites() == [])

# ---------------------------------------------------------------- searching without a search key
browser.SEARCH_URL = SHOP + "/bing?q="
rows = browser.web_results("arc lamp", 3)
check("a search in Theta's browser reads titles, links and snippets", len(rows) == 3
      and rows[0] == {"title": "arc lamp result 1", "url": "https://lamps.test/1", "snippet": "Snippet 1 about arc lamp."})
rows = browser.web_results("arc lamp", 10)
check("a result pointing at a private address is dropped", all("127.0.0.1" not in r["url"] for r in rows) and len(rows) == 7)
check("the search tab is private: not Theta's screen, never saved as sign-ins",
      browser._engine.sessions[browser.SEARCH_KEY].private and "/bing" not in live.state("theta")["url"])

# ---------------------------------------------------------------- Theta's screen (live.py)
ok, out = run("browse_open", {"url": SHOP + "/book.html"})
st = live.state("theta")
check("live state: a page is open, with its address and title", st["active"] and st["url"].endswith("/book.html")
      and st["title"] == "Book a visit")
jpg, size = live.frame("theta", width=512)
check("a frame is a JPEG, scaled to the width asked", jpg[:3] == b"\xff\xd8\xff" and size["width"] == 512
      and size["height"] == 640 and len(jpg) < 150_000)


def box(text):
    def work(eng):
        s = eng.sessions["theta"]
        b = s.page.get_by_text(text, exact=True).first.bounding_box() if text != "#name" else s.page.locator("#name").bounding_box()
        vp = s.page.viewport_size
        return (b["x"] + b["width"] / 2) / vp["width"], (b["y"] + b["height"] / 2) / vp["height"]
    return browser._engine.call(work)


x, y = box("#name")
live.act("theta", live.clean_act({"type": "tap", "x": x, "y": y}))
live.act("theta", live.clean_act({"type": "type", "text": "Ada"}))
ok, out = act({"do": "scroll", "text": "up"})
check("the user's own tap and typing land in the field, and Theta sees it", re.search(r'"Full name" = \'Ada\'', out) is not None)
run("browse_open", {"url": SHOP + "/spa.html"})
x, y = box("Remove item")
r = live.act("theta", live.clean_act({"type": "tap", "x": x, "y": y}))
check("a page's 'Are you sure?' is passed to the user, answered no until they say OK",
      any("Remove the Arc floor lamp?" in d and "dismissed" in d for d in r["dialogs"]))
r = live.act("theta", live.clean_act({"type": "tap", "x": x, "y": y, "accept": True}))
ok, out = act({"do": "scroll", "text": "up"})
check("their OK goes ahead", "Removed" in out and any("accepted" in d for d in r["dialogs"]))
try:
    live.act("theta", live.clean_act({"type": "goto", "url": "http://127.0.0.1:%d/private.png" % PORT}))
    went = True
except tools.ToolError:
    went = False
check("the user's address bar is held to the same private-address rule", not went)
shot = live.snapshot("theta")
check("the last picture of a browsing turn is kept for the reply", shot and os.path.isfile(
      os.path.join(db.data_dir(), "media", shot["id"] + ".png")) and shot["url"].endswith("/spa.html"))

browser._engine.call(lambda eng: eng.close("theta"))
print(f"all real-browser checks passed in {time.time() - t0:.1f}s")
