"""GIFs (server/gifs.py): the honest "needs a GIPHY key" answer, search over GIPHY (stubbed urlopen), the key never
leaving the server, the media proxy limited to GIPHY's hosts, and picking a GIF into an upload. No network.
Run: python3 tests/test_gifs.py"""
import io
import json
import os
import struct
import sys
import tempfile
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_DATA=tempfile.mkdtemp(prefix="protos-gifs-"))
os.environ.pop("GIPHY_API_KEY", None)

from server import app, db, ext, gifs, tools  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILED.append(name)


ext.FEATURES = ("uploads", "gifs")
ext.reset(); tools._ext_reset()
db.init()


def call(path, method="GET", body=None, query="", key="k"):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "CONTENT_LENGTH": str(len(raw)),
           "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http", "REMOTE_ADDR": "1.2.3.4"}
    if key:
        env["HTTP_X_PROTOS_KEY"] = key
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]), h=dict(h))))
    return got["s"], got["h"], out


GIF = b"GIF89a" + struct.pack("<HH", 200, 150) + b"\x00" * 30
SENT = []


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def rendition(name, w, h):
    return {"url": f"https://media1.giphy.com/media/abc123/{name}.gif?cid=x", "width": str(w), "height": str(h)}


def fake_urlopen(req, timeout=None):
    url = req.full_url if hasattr(req, "full_url") else req
    SENT.append(url)
    u = urllib.parse.urlsplit(url)
    if u.hostname == "api.giphy.com":
        imgs = {"fixed_width_small": rendition("100w", 100, 75), "fixed_height": rendition("200", 266, 200)}
        if u.path.endswith("/search") or u.path.endswith("/trending"):
            return Resp(json.dumps({"data": [
                {"id": "abc123", "title": "Happy Dance GIF", "images": imgs},
                {"id": "evil", "title": "x", "images": {"fixed_width_small": {"url": "https://evil.test/a.gif"}}},
            ]}).encode())
        return Resp(json.dumps({"data": {"id": "abc123", "title": "Happy Dance GIF", "images": imgs}}).encode())
    if u.hostname == "media1.giphy.com":
        return Resp(GIF)
    raise AssertionError("unexpected fetch " + url)


urllib.request.urlopen = fake_urlopen

s, _, out = call("/api/gifs", query="q=party")
j = json.loads(out)
check("without a key: an honest answer, not an error page", s == 200 and j == {"configured": False, **{k: gifs.NOT_SET[k] for k in ("error", "fix")}}, j)
check("it says what to set", "GIPHY_API_KEY" in j["fix"] and j["error"] == "GIFs need a GIPHY key")
check("and nothing was fetched", not SENT)
s, _, _ = call("/api/gifs/pick", "POST", {"id": "abc123"})
check("picking without a key is a 503", s == 503, s)
con = {c["id"]: c for c in gifs.connections()}
check("Connect apps shows GIPHY as not connected, with the fix", con["giphy"]["connected"] is False and "GIPHY_API_KEY" in con["giphy"]["note"])

os.environ["GIPHY_API_KEY"] = "gk-secret"
s, _, out = call("/api/gifs", query="q=happy+dance")
j = json.loads(out)
check("search works with a key", s == 200 and j["configured"] and [g["id"] for g in j["gifs"]] == ["abc123"], j)
check("a result whose image isn't on GIPHY's hosts is dropped", all(g["id"] != "evil" for g in j["gifs"]))
q = urllib.parse.parse_qs(urllib.parse.urlsplit(SENT[-1]).query)
check("it asks GIPHY's search API with the key and a rating", "/v1/gifs/search" in SENT[-1] and q["api_key"] == ["gk-secret"] and q["q"] == ["happy dance"] and q["rating"] == ["pg-13"], SENT[-1])
check("the key never reaches the phone", "gk-secret" not in out.decode())
g = j["gifs"][0]
check("previews come through Theta (same-origin)", g["preview"].startswith("/api/gifs/media?u=https%3A%2F%2Fmedia1.giphy.com"), g)
n = len(SENT)
call("/api/gifs", query="q=happy+dance")
check("the same search is cached for a few minutes", len(SENT) == n)
call("/api/gifs")
check("no words: trending", "/v1/gifs/trending" in SENT[-1])
s, _, _ = call("/api/gifs", query="q=x", key=None)
check("signed out: 401", s == 401, s)

s, h, body = call("/api/gifs/media", query="u=" + g["preview"].split("u=", 1)[1])
check("the media proxy serves a GIPHY image", s == 200 and body == GIF and h["Content-Type"] == "image/gif", (s, h.get("Content-Type")))
for bad in ("https://evil.test/a.gif", "http://media1.giphy.com/a.gif", "https://media1.giphy.com.evil.test/a.gif",
            "https://user@media1.giphy.com/a.gif", "file:///etc/passwd", "https://localhost/a.gif"):
    s, _, _ = call("/api/gifs/media", query="u=" + urllib.parse.quote(bad, safe=""))
    check(f"the proxy refuses {bad[:34]}", s == 400, s)

s, _, out = call("/api/gifs/pick", "POST", {"id": "abc123"})
j = json.loads(out)
check("picking a GIF stores it as an upload", s == 200 and j["url"].startswith("/api/uploads/") and j["type"] == "image/gif", (s, out[:200]))
s, h, body = call(j["url"])
check("and it's served like any photo", s == 200 and body == GIF, s)
s, _, _ = call("/api/gifs/pick", "POST", {"id": "../../x"})
check("a bad GIF id is refused", s == 400, s)

if FAILED:
    print(f"\n{len(FAILED)} failed")
    sys.exit(1)
print("\nall passed")
