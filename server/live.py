"""The live view of Theta's own screen (docs/STAGE5.md, Builder B). Today that's the headless browser in
server/browser.py; a full desktop can plug in here later.

    GET  /api/live              {active, url, title, ts} for the current browser session (never waits on it)
    GET  /api/live/frame.jpg    a fresh JPEG of the page (quality ~60, phone viewport 390x844), at most 4 a second:
                                a request inside FRAME_MIN of the last screenshot gets that same picture again
    POST /api/live/act          {type: "tap", x, y} | {type: "type", text} | {type: "key", key} |
                                {type: "scroll", dy} | {type: "back"} | {type: "reload"} | {type: "goto", url}
                                x, y are 0..1 of the frame; dy is a fraction of its height (-3..3)

All three are ext ROUTES, so only the signed-in user reaches them. The user's own taps are the user's action, but
the browse_act rules still hold, since the model may have navigated to a hostile page: no typing into password
fields, a tap or key on something that submits, buys, sends or deletes is refused with "Use Approve in chat for
that." (403), and goto is URL-checked like browse_open. Everything runs on browser.py's one Playwright thread.
"""
import threading
import time

from . import browser

FRAME_MIN = 0.25          # 4 frames a second at most
QUALITY = 60
MAX_TEXT = 500
MAX_REQS = 12             # frame requests a second before 429 (cached repeats included)

_lock = threading.Lock()
_last = {}                # bot -> (monotonic t, jpeg bytes, viewport)
_hits = {}                # bot -> [monotonic t of recent frame requests]


def _bot(req):
    bot = req.query.get("bot") or "theta"
    from . import app
    if bot not in app.BOT_IDS:
        raise app.HTTPError(404, "unknown bot")
    return bot


def state_route(req, start):
    from . import app
    if req.method != "GET":
        raise app.HTTPError(405, "method not allowed")
    return app.respond_json(start, browser.live_state(_bot(req)))


def _frame(bot, now=None):
    """(jpeg, viewport, cached) with the 4 fps cap: a fresh screenshot at most every FRAME_MIN seconds."""
    from . import app
    now = time.monotonic() if now is None else now
    with _lock:
        hits = [t for t in _hits.get(bot, []) if now - t < 1.0]
        if len(hits) >= MAX_REQS:
            _hits[bot] = hits
            raise app.HTTPError(429, "too many frames; at most 4 a second")
        hits.append(now)
        _hits[bot] = hits
        last = _last.get(bot)
        if last and now - last[0] < FRAME_MIN:
            return last[1], last[2], True
    data, vp = browser.live_frame(bot, quality=QUALITY)
    with _lock:
        _last[bot] = (time.monotonic(), data, vp)
    return data, vp, False


def frame_route(req, start):
    from . import app
    if req.method not in ("GET", "HEAD"):
        raise app.HTTPError(405, "method not allowed")
    bot = _bot(req)
    try:
        data, vp, cached = _frame(bot)
    except browser.NoSession as e:
        with _lock:
            _last.pop(bot, None)
        raise app.HTTPError(404, str(e)) from None
    except browser.ToolError as e:
        raise app.HTTPError(503, str(e)) from None
    start("200 OK", app._headers("image/jpeg", [
        ("Content-Length", str(len(data))), ("Cache-Control", "no-store"),
        ("X-Frame-Width", str(vp.get("width", ""))), ("X-Frame-Height", str(vp.get("height", ""))),
        ("X-Frame-Cached", "1" if cached else "0")]))
    return [data] if req.method == "GET" else [b""]


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
    kind = body.get("type")
    if kind == "tap":
        return {"type": "tap", "x": _num(body.get("x"), 0, 1, "x"), "y": _num(body.get("y"), 0, 1, "y")}
    if kind == "type":
        text = body.get("text")
        if not isinstance(text, str) or not text:
            raise app.HTTPError(400, "text is required")
        if len(text) > MAX_TEXT:
            raise app.HTTPError(400, f"at most {MAX_TEXT} characters at a time")
        return {"type": "type", "text": text}
    if kind == "key":
        key = body.get("key")
        if key not in browser.LIVE_KEYS:
            raise app.HTTPError(400, "key must be one of " + ", ".join(browser.LIVE_KEYS))
        return {"type": "key", "key": key}
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


def act_route(req, start):
    from . import app
    if req.method != "POST":
        raise app.HTTPError(405, "method not allowed")
    bot = _bot(req)
    act = clean_act(req.json())
    try:
        out = browser.live_act(bot, act)
    except browser.Refused as e:
        return app.respond_json(start, {"ok": False, "refused": True, "error": str(e)}, 403)
    except browser.NoSession as e:
        return app.respond_json(start, {"ok": False, "error": str(e)}, 404)
    except browser.ToolError as e:
        return app.respond_json(start, {"ok": False, "error": str(e)}, 400)
    with _lock:
        _last.pop(bot, None)  # the next frame shows what the action did
    return app.respond_json(start, out)


ROUTES = {"/api/live": state_route, "/api/live/frame.jpg": frame_route, "/api/live/act": act_route}


def reset():
    """Forget cached frames (tests)."""
    with _lock:
        _last.clear()
        _hits.clear()

