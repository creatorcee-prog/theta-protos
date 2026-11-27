"""Theta's screen, live: the page in Theta's own browser (server/browser.py), streamed to the app as pictures so the
user can watch Theta work ("casting") and take over with their own taps and typing.

    GET  /api/live              {active, url, title, ts, busy} for the current browser session (never waits on it)
    GET  /api/live/frame.jpg    a fresh JPEG of the page (?w=360..1280 wide, default 720), at most 4 a second: a
                                request inside FRAME_MIN of the last picture gets that same picture again
    POST /api/live/act          {type: "tap", x, y} | {type: "type", text} | {type: "key", key} |
                                {type: "scroll", dy} | {type: "back"} | {type: "reload"} | {type: "goto", url}
                                x, y are 0..1 of the frame; dy is a fraction of its height (-3..3)
    DELETE /api/live/signins    forget every site Theta's browser is signed in to (its saved cookies)

All are ext ROUTES, so only the signed-in user reaches them. These taps and keys are the user's own, so unlike
browse_act they may press a submit button or type into a password field: that is the person doing it, which is what
the approval rule asks for. What stays the same: goto is URL-checked like browse_open, every request the page makes
still goes through the private-address guard, and what the user types is never logged or shown to the model.
Everything runs on browser.py's one Playwright thread.

snapshot(bot) keeps the last picture of a turn that used the browser, so the reply can show "Theta's screen" after
the page has closed.
"""
import base64
import os
import secrets
import threading
import time

from . import browser
from .tools import ToolError

FRAME_MIN = 0.25          # 4 frames a second at most
QUALITY = 55
MAX_TEXT = 500
MAX_REQS = 12             # frame requests a second before 429 (cached repeats included)
WIDTHS = (360, 1280)
KEYS = ("Enter", "Tab", "Backspace", "Delete", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
        "PageUp", "PageDown", "Home", "End", "Space")

_lock = threading.Lock()
_last = {}                # (bot, w) -> (monotonic t, jpeg bytes, size)
_hits = {}                # bot -> [monotonic t of recent frame requests]


class NoSession(ToolError):
    pass


def _session(eng, bot):
    s = eng.sessions.get(str(bot or "theta"))
    if s is None or not s.page.url.startswith("http"):
        raise NoSession("Theta isn't using its browser right now.")
    return s


def state(bot="theta"):
    """{active, url, title, ts, busy}; reads what the browser thread last recorded, so it never waits."""
    s = browser._engine.sessions.get(str(bot or "theta")) if browser.available() else None
    url = (s.url or "") if s is not None else ""
    if s is None or not url.startswith("http"):
        return {"active": False, "url": "", "title": "", "ts": None, "busy": False}
    return {"active": True, "url": url, "title": getattr(s, "title", "") or "", "ts": round(s.used, 3),
            "busy": not browser._engine.q.empty()}


def _shot(s, width, quality):
    """JPEG bytes of the visible page, scaled down to `width` (CDP when it's there, else Playwright's own)."""
    vp = s.page.viewport_size or {"width": 1280, "height": 900}
    scale = min(1.0, float(width) / vp["width"])
    try:
        cdp = getattr(s, "cdp", None)
        if cdp is None:
            cdp = s.cdp = s.context.new_cdp_session(s.page)
        m = cdp.send("Page.getLayoutMetrics")
        vv = m.get("cssVisualViewport") or m.get("visualViewport") or {}
        clip = {"x": vv.get("pageX", 0), "y": vv.get("pageY", 0), "width": vp["width"], "height": vp["height"],
                "scale": scale}
        r = cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": int(quality), "clip": clip,
                                                "fromSurface": True})
        data = base64.b64decode(r["data"])
    except Exception:  # noqa: BLE001  older Chromium, or not Chromium: full size is fine
        s.cdp = None
        data = s.page.screenshot(type="jpeg", quality=int(quality), timeout=8000)
        scale = 1.0
    return data, {"width": round(vp["width"] * scale), "height": round(vp["height"] * scale)}


def frame(bot="theta", width=720, quality=QUALITY, timeout=10):
    """(jpeg, size) of the page as it is now. Watching doesn't count as use, so it never keeps an idle page open."""
    browser._need()
    deadline = time.monotonic() + timeout

    def work(eng):
        if time.monotonic() > deadline:  # the caller gave up while the browser was busy
            return None
        s = _session(eng, bot)
        out = _shot(s, width, quality)
        s.url = s.page.url
        try:
            s.title = s.page.title() or getattr(s, "title", "")
        except Exception:  # noqa: BLE001
            pass
        return out
    out = browser._engine.call(work, timeout=timeout)
    if out is None:
        raise ToolError("the browser is busy; try again")
    return out


def _frame_cached(bot, width, now=None):
    from . import app
    now = time.monotonic() if now is None else now
    with _lock:
        hits = [t for t in _hits.get(bot, []) if now - t < 1.0]
        if len(hits) >= MAX_REQS:
            _hits[bot] = hits
            raise app.HTTPError(429, "too many frames; at most 4 a second")
        hits.append(now)
        _hits[bot] = hits
        last = _last.get((bot, width))
        if last and now - last[0] < FRAME_MIN:
            return last[1], last[2], True
    data, size = frame(bot, width)
    with _lock:
        _last[(bot, width)] = (time.monotonic(), data, size)
    return data, size, False


def snapshot(bot="theta"):
    """Save the page as it looks now into media (served at /api/media/<id>.png) and return {id, url, title}, or
    None when no page is open. Used once at the end of a turn that browsed."""
    try:
        data, size = frame(bot, width=720, quality=60, timeout=8)
    except ToolError:
        return None
    from . import db
    sid = secrets.token_hex(16)
    folder = os.path.join(db.data_dir(), "media")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, sid + ".png"), "wb") as f:  # the name is the media id; the bytes are a JPEG
        f.write(data)
    st = state(bot)
    return {"id": sid, "url": st.get("url") or "", "title": st.get("title") or "", **size}


# ---------------------------------------------------------------- the user's own actions

def _settle(s, before, nav=False):
    """After a tap or key: give a navigation time to start, let it load, bring a popup into the one tab, and check
    the new address."""
    try:
        s.page.wait_for_url(lambda u: u != before, timeout=4000 if nav else 500)
    except Exception:  # noqa: BLE001  most taps don't navigate
        pass
    try:
        s.page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:  # noqa: BLE001
        pass
    browser._adopt_popup(s)
    if s.page.url != before:
        browser._after_nav(s)


def act(bot, a):
    """Do one of the user's own actions; a is validated by clean_act. Returns {ok, url, title}."""
    browser._need()
    kind = a["type"]
    url = ""
    if kind == "goto":
        url = a["url"] if "://" in a["url"] else "https://" + a["url"]
        why = browser.check_url(url)
        if why:
            raise ToolError(why)

    def work(eng):
        s = _session(eng, bot)
        s.used = time.time()
        vp = s.page.viewport_size or {"width": 1280, "height": 900}
        before = s.page.url
        s.dialogs.clear()
        s.accept_dialogs = bool(a.get("accept"))  # only after the person said OK to the page's own question
        try:
            _do_act(s, a, kind, vp, before, url)
        finally:
            s.accept_dialogs = False
        try:
            title, _t, _els = browser._snap(s)  # Theta's refs follow what the user did
        except Exception:  # noqa: BLE001
            title = getattr(s, "title", "")
        s.url, s.title = s.page.url, title or getattr(s, "title", "")
        dialogs = list(s.dialogs)
        s.dialogs.clear()
        browser.save_signins(eng)  # the user may just have signed in somewhere
        return {"ok": True, "url": s.url, "title": s.title, "dialogs": dialogs}
    return browser._engine.call(work, timeout=40)


def _do_act(s, a, kind, vp, before, url):
    if kind == "tap":
        x, y = a["x"] * vp["width"], a["y"] * vp["height"]
        href = s.page.evaluate("([x, y]) => { const e = document.elementFromPoint(x, y); const l = e && e.closest('a[href]');"
                               " return l ? l.href : ''; }", [x, y]) or ""
        s.page.mouse.click(x, y)
        _settle(s, before, nav=href.startswith("http"))
    elif kind == "type":
        s.page.keyboard.type(a["text"], delay=8)
    elif kind == "key":
        s.page.keyboard.press(" " if a["key"] == "Space" else a["key"])
        _settle(s, before)
    elif kind == "scroll":
        s.page.mouse.wheel(0, a["dy"] * vp["height"])
        s.page.wait_for_timeout(120)
    elif kind == "back":
        try:
            s.page.go_back(timeout=browser.NAV_TIMEOUT)
        except Exception:  # noqa: BLE001
            pass
        browser._after_nav(s)
    elif kind == "reload":
        browser._goto(s, s.page.url)  # a fresh GET: never re-posts a form
    elif kind == "goto":
        browser._goto(s, url)


def _num(v, lo, hi, what):
    from . import app
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        raise app.HTTPError(400, f"{what} must be a number")
    if not lo <= v <= hi:
        raise app.HTTPError(400, f"{what} must be between {lo} and {hi}")
    return float(v)


def clean_act(body):
    """The validated action, or HTTPError(400)."""
    from . import app
    body = body if isinstance(body, dict) else {}
    kind = body.get("type")
    if kind == "tap":
        return {"type": "tap", "x": _num(body.get("x"), 0, 1, "x"), "y": _num(body.get("y"), 0, 1, "y"),
                "accept": body.get("accept") is True}
    if kind == "type":
        text = body.get("text")
        if not isinstance(text, str) or not text:
            raise app.HTTPError(400, "text is required")
        if len(text) > MAX_TEXT:
            raise app.HTTPError(400, f"at most {MAX_TEXT} characters at a time")
        return {"type": "type", "text": text}
    if kind == "key":
        if body.get("key") not in KEYS:
            raise app.HTTPError(400, "key must be one of " + ", ".join(KEYS))
        return {"type": "key", "key": body["key"], "accept": body.get("accept") is True}
    if kind == "scroll":
        return {"type": "scroll", "dy": _num(body.get("dy"), -3, 3, "dy")}
    if kind in ("back", "reload"):
        return {"type": kind}
    if kind == "goto":
        url = body.get("url")
        if not isinstance(url, str) or not url.strip() or len(url) > 2000:
            raise app.HTTPError(400, "url is required")
        return {"type": "goto", "url": url.strip()}
    raise app.HTTPError(400, "type must be tap, type, key, scroll, back, reload or goto")


# ---------------------------------------------------------------- routes

def _bot(req):
    from . import app
    bot = req.query.get("bot") or "theta"
    if bot not in app.BOT_IDS:
        raise app.HTTPError(404, "unknown bot")
    return bot


def state_route(req, start):
    from . import app
    if req.method != "GET":
        raise app.HTTPError(405, "method not allowed")
    return app.respond_json(start, state(_bot(req)))


def frame_route(req, start):
    from . import app
    if req.method not in ("GET", "HEAD"):
        raise app.HTTPError(405, "method not allowed")
    bot = _bot(req)
    try:
        w = int(req.query.get("w") or 720)
    except ValueError:
        w = 720
    w = max(WIDTHS[0], min(WIDTHS[1], w))
    try:
        data, size, cached = _frame_cached(bot, w)
    except NoSession as e:
        with _lock:
            for k in [k for k in _last if k[0] == bot]:
                _last.pop(k, None)
        raise app.HTTPError(404, str(e)) from None
    except ToolError as e:
        raise app.HTTPError(503, str(e)) from None
    start("200 OK", app._headers("image/jpeg", [
        ("Content-Length", str(len(data))), ("Cache-Control", "no-store"),
        ("X-Frame-Width", str(size.get("width", ""))), ("X-Frame-Height", str(size.get("height", ""))),
        ("X-Frame-Cached", "1" if cached else "0")]))
    return [data] if req.method == "GET" else [b""]


def act_route(req, start):
    from . import app
    if req.method != "POST":
        raise app.HTTPError(405, "method not allowed")
    bot = _bot(req)
    a = clean_act(req.json())
    try:
        out = act(bot, a)
    except NoSession as e:
        return app.respond_json(start, {"ok": False, "error": str(e)}, 404)
    except ToolError as e:
        return app.respond_json(start, {"ok": False, "error": str(e)}, 400)
    with _lock:
        for k in [k for k in _last if k[0] == bot]:
            _last.pop(k, None)  # the next frame shows what the action did
    return app.respond_json(start, out)


def signins_route(req, start):
    from . import app
    if req.method == "GET":
        return app.respond_json(start, {"sites": browser.signed_in_sites()})
    if req.method != "DELETE":
        raise app.HTTPError(405, "method not allowed")
    browser.forget_signins()
    return app.respond_json(start, {"ok": True, "sites": []})


ROUTES = {"/api/live": state_route, "/api/live/frame.jpg": frame_route, "/api/live/act": act_route,
          "/api/live/signins": signins_route}


def reset():
    """Forget cached frames (tests)."""
    with _lock:
        _last.clear()
        _hits.clear()
