"""Photos you send Theta (and GIFs you pick): stored on Theta's disk, shown in the chat.

    POST /api/uploads              the image's bytes (Content-Type image/jpeg|png|gif|webp), or JSON {"data": a
                                   data:image/... URL}. Signed-in only, images only, at most 8 MB.
                                   -> {"ok": true, "id", "url": "/api/uploads/<id>", "type", "w", "h", "bytes"}
    GET  /api/uploads/<id>         the image (private, cached for good: an id never changes)
    POST /api/uploads/attach       {"message_id", "urls": ["/api/uploads/<id>", ...]}: puts them in that user
                                   message's meta.uploads, so the photo shows in its bubble after a reload

The bytes are validated, not trusted: the magic number must be PNG, JPEG, GIF or WebP, the header must parse
to a sane size, and the type served is the sniffed one (never what the phone said). A JPEG's metadata
segments (EXIF, with its GPS position, XMP, IPTC) are dropped before it's saved. SVG and anything else is refused.

The chat request itself still carries the image as a data: URL (what app._images reads, so the vision model
sees it); data_url() turns a stored upload back into one for code that only has the /api/uploads/ path.
"""
import base64
import binascii
import os
import re
import struct
import uuid

from . import db

MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE = 16384
ID_RE = re.compile(r"^[0-9a-f]{32}$")
URL_RE = re.compile(r"^/api/uploads/([0-9a-f]{32})$")
EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


class BadImage(ValueError):
    pass


def folder():
    d = os.path.join(db.data_dir(), "uploads")
    os.makedirs(d, exist_ok=True)
    return d


def sniff(blob):
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if blob[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if blob[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    return None


def _jpeg_size_and_strip(blob):
    """(w, h, cleaned bytes): walks the segments up to the image data, dropping APP1 (EXIF/XMP) and APP13 (IPTC)."""
    out, i, n, size = [blob[:2]], 2, len(blob), None
    while i + 4 <= n:
        if blob[i] != 0xFF:
            raise BadImage("not a valid JPEG")
        marker = blob[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            out.append(blob[i:i + 2]); i += 2
            continue
        seg_len = struct.unpack(">H", blob[i + 2:i + 4])[0]
        if seg_len < 2 or i + 2 + seg_len > n:
            raise BadImage("not a valid JPEG")
        seg = blob[i:i + 2 + seg_len]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF) and seg_len >= 7:
            h, w = struct.unpack(">HH", blob[i + 5:i + 9])
            size = (w, h)
        if marker == 0xDA:  # start of scan: the rest is image data
            out.append(blob[i:])
            break
        if marker not in (0xE1, 0xED):
            out.append(seg)
        i += 2 + seg_len
    if not size:
        raise BadImage("not a valid JPEG")
    return size[0], size[1], b"".join(out)


def inspect(blob):
    """(type, w, h, bytes to store). Raises BadImage if it isn't a real PNG/JPEG/GIF/WebP of a sane size."""
    if not blob:
        raise BadImage("the upload is empty")
    if len(blob) > MAX_BYTES:
        raise BadImage("images can be at most 8 MB")
    kind = sniff(blob)
    if not kind:
        raise BadImage("only photos (JPEG, PNG, GIF or WebP) can be sent")
    w = h = 0
    if kind == "image/png":
        if len(blob) < 24 or blob[12:16] != b"IHDR":
            raise BadImage("not a valid PNG")
        w, h = struct.unpack(">II", blob[16:24])
    elif kind == "image/gif":
        if len(blob) < 10:
            raise BadImage("not a valid GIF")
        w, h = struct.unpack("<HH", blob[6:10])
    elif kind == "image/webp":
        chunk = blob[12:16]
        if chunk == b"VP8 " and len(blob) >= 30:
            w, h = (struct.unpack("<H", blob[26:28])[0] & 0x3FFF), (struct.unpack("<H", blob[28:30])[0] & 0x3FFF)
        elif chunk == b"VP8L" and len(blob) >= 25:
            b = blob[21:25]
            w = 1 + (((b[1] & 0x3F) << 8) | b[0])
            h = 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
        elif chunk == b"VP8X" and len(blob) >= 30:
            w = 1 + int.from_bytes(blob[24:27], "little")
            h = 1 + int.from_bytes(blob[27:30], "little")
        else:
            raise BadImage("not a valid WebP")
    else:
        w, h, blob = _jpeg_size_and_strip(blob)
    if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE):
        raise BadImage("that image's size doesn't look right")
    return kind, w, h, blob


def save(blob):
    """Validate and store an image. Returns {"id", "url", "type", "w", "h", "bytes"}; raises BadImage."""
    kind, w, h, clean = inspect(blob)
    image_id = uuid.uuid4().hex
    full = os.path.join(folder(), f"{image_id}.{EXT[kind]}")
    tmp = full + ".tmp"
    with open(tmp, "wb") as f:
        f.write(clean)
    os.replace(tmp, full)
    return {"id": image_id, "url": f"/api/uploads/{image_id}", "type": kind, "w": w, "h": h, "bytes": len(clean)}


def path_for(image_id):
    """The stored file for an id, or None."""
    s = str(image_id or "")
    if not ID_RE.match(s):
        return None
    base = os.path.realpath(folder())
    for ext in EXT.values():
        full = os.path.realpath(os.path.join(base, f"{s}.{ext}"))
        if full.startswith(base + os.sep) and os.path.isfile(full):
            return full
    return None


def data_url(ref):
    """A stored upload ("/api/uploads/<id>" or the id) as a data:image/... URL, or None."""
    m = URL_RE.match(str(ref or ""))
    full = path_for(m.group(1) if m else ref)
    if not full:
        return None
    with open(full, "rb") as f:
        blob = f.read()
    kind = sniff(blob)
    return f"data:{kind};base64,{base64.b64encode(blob).decode()}" if kind else None


def decode_data_url(s):
    m = re.match(r"^data:image/[a-z0-9.+-]+;base64,(.*)$", str(s or ""), re.S | re.I)
    if not m:
        raise BadImage("data must be a data:image/...;base64 URL")
    try:
        return base64.b64decode(m.group(1), validate=False)
    except (binascii.Error, ValueError):
        raise BadImage("that data URL isn't valid base64") from None


# ---- routes

def _read_body(req):
    from . import app
    try:
        n = int(req.env.get("CONTENT_LENGTH") or 0)
    except ValueError:
        n = 0
    # WSGI keeps Content-Type in CONTENT_TYPE, not HTTP_CONTENT_TYPE, so header() never sees it
    ctype = (req.env.get("CONTENT_TYPE") or req.header("content-type") or "").split(";")[0].strip().lower()
    if ctype == "application/json":
        if n > MAX_BYTES * 4 // 3 + 4096:
            raise app.HTTPError(413, "images can be at most 8 MB")
        return decode_data_url(req.json().get("data"))
    if n > MAX_BYTES:
        raise app.HTTPError(413, "images can be at most 8 MB")
    if ctype and not ctype.startswith("image/") and ctype != "application/octet-stream":
        raise app.HTTPError(415, "only images can be uploaded")
    return req.env["wsgi.input"].read(n) if n > 0 else b""


def upload(req, start):
    from . import app
    if req.method != "POST":
        raise app.HTTPError(405, "method not allowed")
    try:
        info = save(_read_body(req))
    except BadImage as e:
        raise app.HTTPError(415 if "only" in str(e) else 400, str(e)) from None
    return app.respond_json(start, dict(info, ok=True))


def attach(req, start):
    from . import app
    if req.method != "POST":
        raise app.HTTPError(405, "method not allowed")
    body = req.json()
    try:
        mid = int(body.get("message_id"))
    except (TypeError, ValueError):
        raise app.HTTPError(400, "message_id is required") from None
    urls = [u for u in (body.get("urls") or []) if isinstance(u, str)][:4]
    good = []
    for u in urls:
        m = URL_RE.match(u)
        if not m or not path_for(m.group(1)):
            raise app.HTTPError(400, f"not an upload: {u[:80]}")
        good.append(u)
    msg = db.get_message(mid)
    if msg is None or msg.get("role") != "user":
        raise app.HTTPError(404, "no such message of yours")
    have = list((msg.get("meta") or {}).get("uploads") or [])
    msg = db.update_message(mid, meta={"uploads": (have + [u for u in good if u not in have])[:8]})
    return app.respond_json(start, {"ok": True, "message": msg})


def serve(req, start):
    from . import app
    if req.method not in ("GET", "HEAD"):
        raise app.HTTPError(405, "method not allowed")
    full = path_for(req.path[len("/api/uploads/"):])
    if not full:
        raise app.HTTPError(404, "not found")
    with open(full, "rb") as f:
        data = f.read()
    start("200 OK", app._headers(sniff(data) or "application/octet-stream",
                                 [("Content-Length", str(len(data))),
                                  ("Cache-Control", "private, max-age=31536000, immutable")]))
    return [data] if req.method == "GET" else [b""]


ROUTES = {"/api/uploads": upload, "/api/uploads/attach": attach, "/api/uploads/": serve}
