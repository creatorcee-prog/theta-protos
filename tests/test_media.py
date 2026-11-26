"""Images (server/media.py, web/features/media.js): generate_image over Gemini REST (stubbed urlopen), the saved PNG and
its [image:<id>] marker, the daily cap, path safety and the signed-in /api/media/ route. No network.
Run: python3 tests/test_media.py"""
import base64
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_DATA=tempfile.mkdtemp(prefix="protos-media-"),
                  GEMINI_API_KEY="g-test")
os.environ.pop("GEMINI_IMAGE_MODEL", None)

from server import app, db, ext, media, tools  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILED.append(name)


ext.FEATURES = ("media",)
ext.reset(); tools._ext_reset()
db.init()

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
SENT = []
REPLY = {"mode": "ok"}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=None):
    SENT.append({"url": req.full_url, "headers": dict(req.header_items()), "body": json.loads(req.data), "timeout": timeout})
    if REPLY["mode"] == "404":
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b'{"error": {"message": "model not found"}}'))
    if REPLY["mode"] == "blocked":
        return Resp(json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}).encode())
    if REPLY["mode"] == "notimage":
        return Resp(json.dumps({"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "image/png", "data": base64.b64encode(b"hello").decode()}}]}}]}).encode())
    return Resp(json.dumps({"candidates": [{"content": {"parts": [
        {"text": "Here you go."}, {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(PNG).decode()}}]}}]}).encode())


urllib.request.urlopen = fake_urlopen


def call(path, method="GET", key="k"):
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_LENGTH": "0",
           "wsgi.input": io.BytesIO(b""), "wsgi.url_scheme": "http", "REMOTE_ADDR": "1.2.3.4"}
    if key:
        env["HTTP_X_PROTOS_KEY"] = key
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]), h=dict(h))))
    return got["s"], got["h"], out


ok, out = tools.execute("generate_image", {"prompt": "a fox reading a map, watercolor", "size": "landscape"}, {"bot": "theta"})
import re  # noqa: E402
m = re.search(r"\[image:([0-9a-f]{32})\]", out)
check("generate_image: ok, with the [image:<id>] marker for the reply", ok and m, out)
iid = m.group(1) if m else ""
path = os.path.join(db.data_dir(), "media", iid + ".png")
check("saved under data_dir/media/<id>.png", os.path.isfile(path) and open(path, "rb").read() == PNG)
s = SENT[-1]
check("Gemini REST: generateContent on the default model, key in the header (not the URL)",
      s["url"].endswith(f"/models/{media.DEFAULT_MODEL}:generateContent") and "key=" not in s["url"]
      and s["headers"].get("X-goog-api-key") == "g-test", s)
check("asks for an image, with the aspect ratio from size", s["body"]["generationConfig"]["responseModalities"] == ["IMAGE"]
      and s["body"]["generationConfig"]["imageConfig"] == {"aspectRatio": "4:3"}
      and s["body"]["contents"][0]["parts"][0]["text"].startswith("a fox"))
tool = [t for t in media.TOOLS if t["name"] == "generate_image"][0]
check("the call fits inside the 60 s the tool asks agent for", s["timeout"] < tool["timeout"] <= 60)
os.environ["GEMINI_IMAGE_MODEL"] = "my-image-model-2"
tools.execute("generate_image", {"prompt": "x"}, {"bot": "theta"})
check("GEMINI_IMAGE_MODEL overrides the model, no size -> no imageConfig",
      "/models/my-image-model-2:generateContent" in SENT[-1]["url"] and "imageConfig" not in SENT[-1]["body"]["generationConfig"])
os.environ.pop("GEMINI_IMAGE_MODEL")

st, h, body = call(f"/api/media/{iid}.png")
check("GET /api/media/<id>.png serves the PNG", st == 200 and body == PNG and h["Content-Type"] == "image/png")
check("signed out -> 401", call(f"/api/media/{iid}.png", key=None)[0] == 401)
for bad in ("../protos.db", "..%2Fprotos.db", iid.upper() + ".png", iid + ".jpg", iid[:-1] + ".png", iid + ".png/x",
            "%2e%2e/" + iid + ".png", "", iid):
    check(f"path safety: {bad!r} -> 404", call("/api/media/" + bad)[0] == 404)
check("path_for refuses unsafe ids", media.path_for("../x") is None and media.path_for("a" * 31) is None
      and media.path_for("A" * 32) is None and media.path_for(iid))
check("POST -> 405", call(f"/api/media/{iid}.png", "POST")[0] == 405)

# failures give the slot back and say how to fix it
before = media.made_today()
REPLY["mode"] = "404"
ok, out = tools.execute("generate_image", {"prompt": "x"}, {"bot": "theta"})
check("a 404 hints at GEMINI_IMAGE_MODEL", not ok and "GEMINI_IMAGE_MODEL" in out, out)
REPLY["mode"] = "blocked"
ok, out = tools.execute("generate_image", {"prompt": "x"}, {"bot": "theta"})
check("a blocked prompt says why", not ok and "SAFETY" in out, out)
REPLY["mode"] = "notimage"
ok, out = tools.execute("generate_image", {"prompt": "x"}, {"bot": "theta"})
check("bytes that aren't an image are refused", not ok and "isn't an image" in out)
check("failures don't use up the day's images", media.made_today() == before)
REPLY["mode"] = "ok"
ok, out = tools.execute("generate_image", {"prompt": "x", "size": "huge"}, {"bot": "theta"})
check("bad size refused with the choices", not ok and "square" in out)
os.environ.pop("GEMINI_API_KEY")
ok, out = tools.execute("generate_image", {"prompt": "x"}, {"bot": "theta"})
check("no GEMINI_API_KEY: says it isn't set up", not ok and "GEMINI_API_KEY" in out)
os.environ["GEMINI_API_KEY"] = "g-test"

# the daily cap
db.set_setting("image_daily_cap", 3)
db.set_setting("image_count", {})
res = [tools.execute("generate_image", {"prompt": f"p{i}"}, {"bot": "theta"})[0] for i in range(4)]
check("daily cap: 3 made, the 4th refused", res == [True, True, True, False])
ok, out = tools.execute("generate_image", {"prompt": "p"}, {"bot": "theta"})
check("cap message says when it resets", not ok and "tomorrow" in out)
db.set_setting("image_daily_cap", None)
check("default cap is 10", media.daily_cap() == 10)
check("generate_image is a write tool; RELEVANT words match",
      tools.BY_NAME["generate_image"]["risk"] == "write" and tools.relevant("draw me a cat")
      and tools.relevant("make an image of a sunset") and tools.relevant("generate a logo for my bakery"))

js = open(os.path.join(ROOT, "web", "features", "media.js"), encoding="utf-8").read()
check("media.js: decorates replies, builds an <img> for the marker, no innerHTML",
      "Theta.decorate" in js.replace("T.decorate", "Theta.decorate") and "/api/media/" in js
      and 'createElement("img")' in js and ".innerHTML" not in js and ".outerHTML" not in js and ".insertAdjacentHTML" not in js)
rjs = open(os.path.join(ROOT, "web", "features", "routines.js"), encoding="utf-8").read()
check("routines.js: menu + sheet, posts /api/routines, demo data, no innerHTML",
      'T.menu("Routines"' in rjs and 'T.sheet("routines", "Routines & workflows"' in rjs and "/api/routines" in rjs
      and "/api/workflows" in rjs and "T.state.demo" in rjs and ".innerHTML" not in rjs and ".insertAdjacentHTML" not in rjs)

if FAILED:
    print(f"{len(FAILED)} failed: {FAILED}")
    sys.exit(1)
print("all media tests passed")
