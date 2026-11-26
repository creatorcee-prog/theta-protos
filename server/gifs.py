"""GIFs: search GIPHY from the composer's + sheet and send one as an image message.

    GET  /api/gifs?q=<words>      {"configured": true, "gifs": [{id, title, w, h, preview}]}  (no q: trending)
                                  without GIPHY_API_KEY: {"configured": false, "error", "fix"}  (the app says so)
    GET  /api/gifs/media?u=<url>  a GIPHY preview, fetched by Theta (the app's CSP keeps images same-origin, and
                                  this way GIPHY never sees the phone). Only https://media*.giphy.com / i.giphy.com.
    POST /api/gifs/pick {id}      Theta fetches that GIF from GIPHY, stores it as an upload (server/uploads.py)
                                  and returns {"ok", "url": "/api/uploads/<id>", "w", "h", "title"}

The key stays on the server. Results are rated pg-13 at most (GIPHY_RATING to change).
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

API = "https://api.giphy.com/v1/gifs"
MEDIA_HOST = re.compile(r"^(media[0-9]?\.giphy\.com|i\.giphy\.com)$")
MAX_GIF = 6 * 1024 * 1024
TIMEOUT = 8
_cache = {}  # (q) -> (t, result): a few minutes, so typing doesn't spend the key's quota


def key():
    return (os.environ.get("GIPHY_API_KEY") or "").strip()


def configured():
    return bool(key())


NOT_SET = {"configured": False, "error": "GIFs need a GIPHY key",
           "fix": "Get a free API key at developers.giphy.com, then set GIPHY_API_KEY in Theta's environment "
                  "(Railway: Variables) and redeploy."}


def _get(url, limit=2 * 1024 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": "theta-protos", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("too large")
    return data


def _media_ok(u):
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return False
    return p.scheme == "https" and bool(MEDIA_HOST.match(p.hostname or "")) and not p.username and p.port in (None, 443)


def _pick_rendition(images, *names):
    for n in names:
        r = (images or {}).get(n) or {}
        if r.get("url") and _media_ok(r["url"]):
            return r
    return None


def _shape(g):
    imgs = g.get("images") or {}
    prev = _pick_rendition(imgs, "fixed_width_small", "fixed_width", "fixed_height_small", "downsized")
    if not prev or not re.match(r"^[A-Za-z0-9]{1,40}$", str(g.get("id") or "")):
        return None
    return {"id": g["id"], "title": str(g.get("title") or "GIF")[:120],
            "w": int(prev.get("width") or 0) or 200, "h": int(prev.get("height") or 0) or 150,
            "preview": "/api/gifs/media?u=" + urllib.parse.quote(prev["url"], safe="")}


def search(q, limit=24):
    if not configured():
        return dict(NOT_SET)
    q = re.sub(r"\s+", " ", str(q or "")).strip()[:50]
    hit = _cache.get(q)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    params = {"api_key": key(), "limit": str(limit), "rating": os.environ.get("GIPHY_RATING") or "pg-13"}
    if q:
        params.update(q=q, lang="en")
    url = f"{API}/{'search' if q else 'trending'}?" + urllib.parse.urlencode(params)
    try:
        j = json.loads(_get(url).decode("utf-8"))
    except Exception as e:  # noqa: BLE001  say so plainly; never make up results
        return {"configured": True, "gifs": [], "error": f"GIPHY didn't answer ({type(e).__name__}). Try again."}
    gifs = [s for s in (_shape(g) for g in (j.get("data") or []) if isinstance(g, dict)) if s]
    out = {"configured": True, "gifs": gifs}
    if len(_cache) > 200:
        _cache.clear()
    _cache[q] = (time.time(), out)
    return out


def pick(gif_id):
    """Fetch one GIF by id from GIPHY and store it as an upload. Raises ValueError."""
    from . import uploads
    if not configured():
        raise ValueError(NOT_SET["error"])
    if not re.match(r"^[A-Za-z0-9]{1,40}$", str(gif_id or "")):
        raise ValueError("bad GIF id")
    j = json.loads(_get(f"{API}/{gif_id}?" + urllib.parse.urlencode({"api_key": key()})).decode("utf-8"))
    g = j.get("data") or {}
    r = _pick_rendition(g.get("images"), "fixed_height", "downsized_medium", "downsized", "fixed_width")
    if not r:
        raise ValueError("that GIF isn't available")
    info = uploads.save(_get(r["url"], MAX_GIF))
    return dict(info, title=str(g.get("title") or "GIF")[:120])


# ---- routes

def route(req, start):
    from . import app
    if req.method != "GET":
        raise app.HTTPError(405, "method not allowed")
    return app.respond_json(start, search(req.query.get("q") or ""))


def media(req, start):
    from . import app
    u = req.query.get("u") or ""
    if req.method != "GET" or not _media_ok(u):
        raise app.HTTPError(400, "not a GIPHY image")
    try:
        data = _get(u, MAX_GIF)
    except Exception:  # noqa: BLE001
        raise app.HTTPError(502, "GIPHY didn't send it") from None
    from .uploads import sniff
    kind = sniff(data)
    if kind not in ("image/gif", "image/webp"):
        raise app.HTTPError(502, "that isn't a GIF")
    start("200 OK", app._headers(kind, [("Content-Length", str(len(data))), ("Cache-Control", "private, max-age=86400")]))
    return [data]


def pick_route(req, start):
    from . import app, uploads
    if req.method != "POST":
        raise app.HTTPError(405, "method not allowed")
    try:
        info = pick(req.json().get("id"))
    except uploads.BadImage as e:
        raise app.HTTPError(502, f"GIPHY sent something that isn't an image ({e})") from None
    except ValueError as e:
        raise app.HTTPError(400 if configured() else 503, str(e)) from None
    except Exception as e:  # noqa: BLE001
        raise app.HTTPError(502, f"GIPHY didn't answer ({type(e).__name__})") from None
    return app.respond_json(start, dict(info, ok=True))


def connections():
    return [{"id": "giphy", "name": "GIPHY", "connected": configured(),
             "what": "GIFs in the chat: search from the + button.",
             **({} if configured() else {"note": NOT_SET["fix"]})}]


ROUTES = {"/api/gifs": route, "/api/gifs/media": media, "/api/gifs/pick": pick_route}
