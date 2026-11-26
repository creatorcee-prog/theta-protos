"""Images: generate_image makes a picture with Google's Gemini image model and attaches it to the reply.

    generate_image {prompt, size?}   (tool, risk "write": it only makes a file of the user's own)

- REST: POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent with the header
  x-goog-api-key: GEMINI_API_KEY, responseModalities ["IMAGE"], and imageConfig.aspectRatio from `size`.
  The model is GEMINI_IMAGE_MODEL, default DEFAULT_MODEL (not verified live from here; override it if Google
  has renamed or retired it).
- Saved as <data_dir>/media/<id>.png (id = 32 hex chars) and served signed-in at GET /api/media/<id>.png.
  Only ids that match ID_RE are ever turned into a path.
- At most setting "image_daily_cap" (default 10) a day, the user's day.
- The tool output carries the marker [image:<id>] and asks the model to keep it in the reply;
  web/features/media.js swaps the marker for the picture.
"""
import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid

from . import db

DEFAULT_MODEL = "gemini-2.5-flash-image"
DEFAULT_CAP = 10
TIMEOUT = 55          # the tool asks agent.py for 60 s (its "timeout" below)
MAX_BYTES = 12 * 1024 * 1024
ID_RE = re.compile(r"^[0-9a-f]{32}$")
SIZES = {"square": "1:1", "portrait": "3:4", "landscape": "4:3", "wide": "16:9", "tall": "9:16",
         "1:1": "1:1", "3:4": "3:4", "4:3": "4:3", "16:9": "16:9", "9:16": "9:16", "2:3": "2:3", "3:2": "3:2",
         "4:5": "4:5", "5:4": "5:4", "21:9": "21:9"}
_lock = threading.Lock()


def _err(msg):
    from . import tools
    return tools.ToolError(msg)


def media_dir():
    d = os.path.join(db.data_dir(), "media")
    os.makedirs(d, exist_ok=True)
    return d


def path_for(image_id):
    """The file for an id, or None if the id isn't a safe one."""
    s = str(image_id or "")
    if not ID_RE.match(s):
        return None
    base = os.path.realpath(media_dir())
    full = os.path.realpath(os.path.join(base, s + ".png"))
    return full if os.path.dirname(full) == base else None


def model():
    return (os.environ.get("GEMINI_IMAGE_MODEL") or "").strip() or DEFAULT_MODEL


def _day(now):
    from . import tools
    return tools.local_time(now).strftime("%Y-%m-%d")


def daily_cap():
    try:
        return int(db.get_setting("image_daily_cap", DEFAULT_CAP))
    except (TypeError, ValueError):
        return DEFAULT_CAP


def made_today(now=None):
    now = time.time() if now is None else now
    s = db.get_setting("image_count") or {}
    return int(s.get("n") or 0) if s.get("day") == _day(now) else 0


def _take(now):
    with _lock:
        day, cap = _day(now), daily_cap()
        s = db.get_setting("image_count") or {}
        n = int(s.get("n") or 0) if s.get("day") == day else 0
        if n >= cap:
            return False
        db.set_setting("image_count", {"day": day, "n": n + 1})
        return True


def _give_back(now):
    with _lock:
        s = db.get_setting("image_count") or {}
        if s.get("day") == _day(now) and int(s.get("n") or 0) > 0:
            db.set_setting("image_count", {"day": s["day"], "n": int(s["n"]) - 1})


def generate(prompt, size=None, timeout=TIMEOUT):
    """Call Gemini; returns (png_or_image_bytes, mime, text_note). Raises ToolError with a fix hint."""
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        try:
            from . import cards
            cards.connect_card(None, "gemini")
        except Exception:  # noqa: BLE001
            pass
        raise _err("image generation isn't set up (no GEMINI_API_KEY), so no image was made. Tell the user.")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]}}
    if size:
        body["generationConfig"]["imageConfig"] = {"aspectRatio": SIZES[size]}
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{urllib.request.quote(model(), safe='-._')}:generateContent")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key,
                                          "User-Agent": "theta-protos/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read(800).decode("utf-8", "replace")).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            detail = ""
        hint = " (the model id may be wrong: set GEMINI_IMAGE_MODEL)" if e.code == 404 else ""
        raise _err(f"the image service said HTTP {e.code}{hint}: {str(detail)[:160]}") from None
    except (urllib.error.URLError, OSError) as e:
        raise _err(f"couldn't reach the image service ({getattr(e, 'reason', e)}); try once more later") from None
    if len(raw) > MAX_BYTES:
        raise _err("the image came back too large")
    try:
        j = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise _err("the image service sent something that isn't JSON") from None
    note = []
    for cand in j.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            data = part.get("inlineData") or part.get("inline_data")
            if data and data.get("data"):
                try:
                    blob = base64.b64decode(data["data"])
                except ValueError:
                    continue
                return blob, data.get("mimeType") or data.get("mime_type") or "image/png", " ".join(note)
            if part.get("text"):
                note.append(part["text"][:200])
    reason = (j.get("promptFeedback") or {}).get("blockReason") or \
        next((c.get("finishReason") for c in j.get("candidates") or [] if c.get("finishReason")), None)
    raise _err("no image came back" + (f" ({reason})" if reason else "") +
               (f": {' '.join(note)[:200]}" if note else "") + ". Try different wording.")


def _sniff(blob):
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if blob[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    return None


def _t_generate(args, ctx):
    prompt = re.sub(r"\s+", " ", str(args.get("prompt") or "")).strip()
    if not prompt:
        raise _err("prompt is empty: describe the picture, e.g. prompt='a fox reading a map, watercolor'")
    size = (args.get("size") or "").strip().lower() or None
    if size and size not in SIZES:
        raise _err(f"size must be one of {', '.join(SIZES)}")
    now = time.time()
    if not _take(now):
        raise _err(f"today's image limit ({daily_cap()}) is used up; it resets tomorrow. Tell the user.")
    try:
        blob, _mime, note = generate(prompt[:2000], size)
    except Exception:
        _give_back(now)
        raise
    if not _sniff(blob):
        _give_back(now)
        raise _err("what came back isn't an image; try again")
    image_id = uuid.uuid4().hex
    full = path_for(image_id)
    tmp = full + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, full)
    if isinstance(ctx, dict):  # the app adds the marker itself if the model leaves it out
        ctx.setdefault("images", []).append(image_id)
    return (f"Image made and attached to your reply: [image:{image_id}] . Put that marker, exactly "
            f"[image:{image_id}], once in your reply where the picture should appear (the app shows the image "
            "there), plus a short line about it. Don't describe it as a link."
            + (f" The model noted: {note}" if note else ""))


TOOLS = [
    {"name": "generate_image", "risk": "write", "run": _t_generate, "timeout": 60,
     "description": ("Make a picture from a description (illustrations, mock-ups, a birthday card image) and "
                     "attach it to your reply. Use it only when the user asks for an image. Write a vivid, "
                     "specific prompt: subject, style, setting, colors. size is the shape: square (default), "
                     "portrait, landscape, wide, tall, or a ratio like 16:9. At most a few a day, so don't make "
                     "variations unless asked. Example: {\"prompt\": \"a red fox reading a paper map in a pine "
                     "forest, soft watercolor\", \"size\": \"landscape\"}."),
     "params": {"type": "object", "properties": {
         "prompt": {"type": "string", "description": "What the picture shows, in detail."},
         "size": {"type": "string", "description": "square | portrait | landscape | wide | tall | a ratio."}},
         "required": ["prompt"]}},
]

RELEVANT = (r"\b(draw|paint|sketch|illustrate)\b|\b(make|generate|create|design)\b.{0,30}\b(image|picture|"
            r"illustration|drawing|logo|poster|card|wallpaper|art)\b|\bimage of\b|\bpicture of\b")


def serve(req, start):
    """GET /api/media/<id>.png (signed-in: ext ROUTES are only reached after app.authed)."""
    from . import app
    if req.method not in ("GET", "HEAD"):
        raise app.HTTPError(405, "method not allowed")
    name = req.path[len("/api/media/"):]
    m = re.match(r"^([0-9a-f]{32})\.png$", name)
    full = path_for(m.group(1)) if m else None
    if not full or not os.path.isfile(full):
        raise app.HTTPError(404, "not found")
    with open(full, "rb") as f:
        data = f.read()
    ctype = _sniff(data) or "application/octet-stream"
    start("200 OK", app._headers(ctype, [("Content-Length", str(len(data))),
                                         ("Cache-Control", "private, max-age=31536000, immutable")]))
    return [data] if req.method == "GET" else [b""]


ROUTES = {"/api/media/": serve}
