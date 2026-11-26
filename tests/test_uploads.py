"""Photos (server/uploads.py): POST /api/uploads (raw bytes or a data URL), signed-in only, images only, 8 MB,
validated headers, JPEG metadata stripped, stored under db.data_dir()/uploads, served at /api/uploads/<id> with
the sniffed type, attached to a user message, and data_url() for the vision path. No network.
Run: python3 tests/test_uploads.py"""
import base64
import io
import json
import os
import struct
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = tempfile.mkdtemp(prefix="protos-uploads-")
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_DATA=DATA)

from server import app, db, ext, tools, uploads  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILED.append(name)


ext.FEATURES = ("uploads",)
ext.reset(); tools._ext_reset()
db.init()


def call(path, method="GET", raw=b"", ctype="application/json", key="k", length=None):
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw) if length is None else length),
           "CONTENT_TYPE": ctype, "HTTP_CONTENT_TYPE": ctype, "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http",
           "REMOTE_ADDR": "1.2.3.4"}
    if key:
        env["HTTP_X_PROTOS_KEY"] = key
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]), h=dict(h))))
    return got["s"], got["h"], out


def js(out):
    try:
        return json.loads(out)
    except ValueError:
        return {}


PNG = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 640, 480) + b"\x08\x02\x00\x00\x00" + b"\x00" * 40
GIF = b"GIF89a" + struct.pack("<HH", 200, 150) + b"\x00" * 30
EXIF = b"Exif\x00\x00GPS 40.0N 105.2W secret"
JPEG = (b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9 +
        b"\xff\xe1" + struct.pack(">H", 2 + len(EXIF)) + EXIF +
        b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", 1080, 1920) + b"\x03" + b"\x00" * 9 +
        b"\xff\xda" + struct.pack(">H", 8) + b"\x00" * 6 + b"imagedata" + b"\xff\xd9")

s, h, out = call("/api/uploads", "POST", PNG, "image/png")
j = js(out)
check("a PNG uploads", s == 200 and j.get("ok") and j["type"] == "image/png" and (j["w"], j["h"]) == (640, 480), (s, out[:200]))
check("it gets an /api/uploads/<id> url", j.get("url") == f"/api/uploads/{j.get('id')}", j)
check("stored under the data folder's uploads/", os.path.isfile(os.path.join(DATA, "uploads", j["id"] + ".png")))
s, h, body = call(j["url"])
check("served back exactly, as image/png", s == 200 and body == PNG and h["Content-Type"] == "image/png", (s, h.get("Content-Type")))
check("with nosniff and a private, immutable cache", h.get("X-Content-Type-Options") == "nosniff" and "private" in h.get("Cache-Control", ""), h)
png_url = j["url"]

s, h, out = call("/api/uploads", "POST", JPEG, "image/jpeg")
j = js(out)
check("a JPEG uploads, with its size read from the frame header", s == 200 and (j.get("w"), j.get("h")) == (1920, 1080), (s, out[:200]))
_, _, body = call(j["url"])
check("its EXIF (GPS) is dropped before it's saved", b"GPS" not in body and b"Exif" not in body and body.startswith(b"\xff\xd8") and b"imagedata" in body, body[:60])
check("but the rest of the file is kept", b"JFIF" in body and body.endswith(b"\xff\xd9"))

s, _, out = call("/api/uploads", "POST", json.dumps({"data": "data:image/gif;base64," + base64.b64encode(GIF).decode()}).encode())
j = js(out)
check("a data: URL in JSON works too (GIFs are images)", s == 200 and j.get("type") == "image/gif" and j.get("w") == 200, (s, out[:200]))
gif_url = j.get("url")

s, h, out = call("/api/uploads", "POST", PNG, "image/png", key=None)
check("signed out: 401", s == 401, s)
s, _, out = call("/api/uploads", "POST", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "image/svg+xml")
check("SVG is refused (only photos)", s == 415, (s, out))
s, _, out = call("/api/uploads", "POST", b"MZ\x90\x00 not an image at all", "image/png")
check("a lie about the type is caught by sniffing", s == 415, (s, out))
s, _, out = call("/api/uploads", "POST", b"\x89PNG\r\n\x1a\n" + b"\x00" * 30, "image/png")
check("a broken PNG header is refused", s == 400, (s, out))
s, _, out = call("/api/uploads", "POST", b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 0, 99999) + b"\x00" * 20, "image/png")
check("an absurd size is refused", s == 400, (s, out))
s, _, out = call("/api/uploads", "POST", b"\xff\xd8\xff\xe0\x00\x02", "image/jpeg")
check("a truncated JPEG is refused", s == 400, (s, out))
s, _, out = call("/api/uploads", "POST", b"x" * 10, "text/html")
check("a non-image content type is refused", s == 415, (s, out))
s, _, out = call("/api/uploads", "POST", PNG, "image/png", length=9 * 1024 * 1024)
check("over 8 MB is refused before reading it", s == 413, (s, out))
s, _, out = call("/api/uploads", "POST", b"")
check("an empty upload is refused", s == 400, (s, out))
s, _, _ = call("/api/uploads", "GET")
check("GET /api/uploads isn't a listing", s == 405, s)

for bad in ("/api/uploads/../protos.db", "/api/uploads/" + "0" * 32, "/api/uploads/abc", "/api/uploads/%2e%2e%2fprotos.db"):
    s, _, _ = call(bad)
    check(f"no file outside uploads, no guessing: {bad[13:30]}", s == 404, s)

# attaching to a user message, so the photo shows after a reload
u = db.add_message("theta", "user", "what's this plant?", {"images": 1})
a = db.add_message("theta", "assistant", "A pothos.")
s, _, out = call("/api/uploads/attach", "POST", json.dumps({"message_id": u["id"], "urls": [png_url, gif_url]}).encode())
check("uploads attach to your message", s == 200 and db.get_message(u["id"])["meta"]["uploads"] == [png_url, gif_url], (s, out[:200]))
check("its other meta stays", db.get_message(u["id"])["meta"]["images"] == 1)
s, _, out = call("/api/uploads/attach", "POST", json.dumps({"message_id": u["id"], "urls": [png_url]}).encode())
check("attaching again doesn't duplicate", db.get_message(u["id"])["meta"]["uploads"] == [png_url, gif_url])
s, _, _ = call("/api/uploads/attach", "POST", json.dumps({"message_id": a["id"], "urls": [png_url]}).encode())
check("only to your own messages", s == 404, s)
s, _, _ = call("/api/uploads/attach", "POST", json.dumps({"message_id": u["id"], "urls": ["https://evil.test/x.png"]}).encode())
check("only real uploads", s == 400, s)
s, _, _ = call("/api/uploads/attach", "POST", json.dumps({"message_id": u["id"], "urls": ["/api/uploads/" + "f" * 32]}).encode())
check("an id that doesn't exist is refused", s == 400, s)

d = uploads.data_url(png_url)
check("data_url() gives the vision path a data: URL", d and d.startswith("data:image/png;base64,") and base64.b64decode(d.split(",", 1)[1]) == PNG)
check("which app._images accepts", app._images({"images": [d]}) == [d])
check("data_url() of nonsense is None", uploads.data_url("/api/uploads/nope") is None and uploads.data_url("../../etc/passwd") is None)

if FAILED:
    print(f"\n{len(FAILED)} failed")
    sys.exit(1)
print("\nall passed")
