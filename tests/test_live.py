"""Theta's screen (server/live.py) without a browser: what the user's actions may be, the frame rate limit and its
cache, and plain answers when no page is open. The real browser side is in test_browser_real.py."""
import os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_DATA=tempfile.mkdtemp())
from server import app, browser, db, ext, live, tools


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


db.init()
ext.reset(); tools._ext_reset()


def bad(body):
    try:
        live.clean_act(body)
        return ""
    except app.HTTPError as e:
        return f"{e.status} {e}"


check("a tap is two numbers from 0 to 1", live.clean_act({"type": "tap", "x": 0.5, "y": 1})["x"] == 0.5
      and bad({"type": "tap", "x": 2, "y": 0.1}) and bad({"type": "tap", "x": "0.5", "y": 0.1})
      and bad({"type": "tap", "x": True, "y": 0.1}))
check("accept only when the person said OK (a real true, nothing else)",
      live.clean_act({"type": "tap", "x": 0, "y": 0, "accept": True})["accept"] is True
      and live.clean_act({"type": "tap", "x": 0, "y": 0, "accept": "yes"})["accept"] is False)
check("typing needs text, at most 500 characters", bad({"type": "type", "text": ""}) and bad({"type": "type", "text": "x" * 501})
      and live.clean_act({"type": "type", "text": "hi"})["text"] == "hi")
check("only listed keys", bad({"type": "key", "key": "F12"}) and live.clean_act({"type": "key", "key": "Tab"})["key"] == "Tab")
check("scroll is bounded", bad({"type": "scroll", "dy": 9}) and live.clean_act({"type": "scroll", "dy": -1.5})["dy"] == -1.5)
check("goto needs an address; unknown kinds are refused", bad({"type": "goto", "url": " "}) and bad({"type": "drag"})
      and bad("not a dict"))

check("no page open: state says inactive", live.state("theta")["active"] is False)
calls = []
live.frame = lambda bot, width=720, quality=55, timeout=10: (calls.append(width) or (b"\xff\xd8\xffjpg", {"width": width, "height": 900}))
d1, size, cached1 = live._frame_cached("theta", 720, now=100.0)
d2, size2, cached2 = live._frame_cached("theta", 720, now=100.1)
check("a second frame inside a quarter second is the same picture, not a new screenshot", not cached1 and cached2 and len(calls) == 1)
live.reset()
hit = None
for i in range(13):
    try:
        live._frame_cached("theta", 360, now=200.0 + i * 0.01)
    except app.HTTPError as e:
        hit = e
check("more than 12 frame requests a second gets 429", hit is not None and hit.status == 429)
live.reset()


def nos(*a, **k):
    raise live.NoSession("Theta isn't using its browser right now.")


live.frame = nos
try:
    live._frame_cached("theta", 720, now=300.0)
    said = ""
except live.NoSession as e:
    said = str(e)
check("no page: a plain answer the app shows as-is", "isn't using its browser" in said)
check("the routes are signed-in only (ROUTES, not PUBLIC_ROUTES)", "/api/live/act" in live.ROUTES
      and not getattr(live, "PUBLIC_ROUTES", None))
check("sign-ins: none saved yet", browser.signed_in_sites() == [])
print("all live checks passed")
