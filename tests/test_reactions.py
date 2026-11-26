"""Tapbacks (server/reactions.py): POST/GET /api/messages/react, meta.reactions {user, theta}, reactions.set for
Theta, tapback names, bad input, signed-out callers, and the `react` tool. No network.
Run: python3 tests/test_reactions.py"""
import io
import json
import os
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_DATA=tempfile.mkdtemp(prefix="protos-react-"))

from server import app, db, ext, reactions, tools  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILED.append(name)


ext.FEATURES = ("reactions",)
ext.reset(); tools._ext_reset()
db.init()


def call(path, method="GET", body=None, key="k", query=""):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "CONTENT_LENGTH": str(len(raw)),
           "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http",
           "REMOTE_ADDR": "1.2.3.4"}
    if key:
        env["HTTP_X_PROTOS_KEY"] = key
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]))))
    return got["s"], json.loads(out or b"{}")


u = db.add_message("theta", "user", "I got the job!!")
a = db.add_message("theta", "assistant", "That's huge. Congrats.")

s, j = call("/api/messages/react", "POST", {"id": a["id"], "emoji": "❤️", "by": "user"})
check("you can react to Theta's reply", s == 200 and j["reactions"] == {"user": "❤️"}, (s, j))
check("it's stored in meta.reactions", db.get_message(a["id"])["meta"]["reactions"] == {"user": "❤️"})
s, j = call("/api/messages/react", "POST", {"id": a["id"], "emoji": "haha"})
check("a tapback name is stored as its emoji, and the newest wins", j["reactions"] == {"user": "😂"}, j)
s, j = call("/api/messages/react", "POST", {"id": a["id"], "emoji": "🎉"})
check("any single emoji works (the + picker)", j["reactions"] == {"user": "🎉"}, j)
s, j = call("/api/messages/react", "POST", {"id": a["id"], "emoji": "👍🏽"})
check("skin tones are fine", s == 200 and j["reactions"]["user"] == "👍🏽", (s, j))
s, j = call("/api/messages/react", "POST", {"id": a["id"], "emoji": ""})
check("an empty emoji removes yours", s == 200 and j["reactions"] == {}, j)
check("and meta.reactions goes away", "reactions" not in db.get_message(a["id"])["meta"])

for bad in ("<script>", "hello", "x" * 40, 5):
    s, _ = call("/api/messages/react", "POST", {"id": a["id"], "emoji": bad})
    check(f"not an emoji is refused: {str(bad)[:12]!r}", s == 400, s)
s, _ = call("/api/messages/react", "POST", {"id": a["id"], "emoji": "❤️", "by": "theta"})
check("the phone can't react as Theta", s == 400, s)
s, _ = call("/api/messages/react", "POST", {"id": 999999, "emoji": "❤️"})
check("an unknown message is a 404", s == 404, s)
s, _ = call("/api/messages/react", "POST", {"emoji": "❤️"})
check("an id is required", s == 400, s)
s, _ = call("/api/messages/react", "POST", {"id": a["id"], "emoji": "❤️"}, key=None)
check("signed out: 401", s == 401, s)

# Theta reacting, from Python (B's agent) and through the tool
r = reactions.set(u["id"], "theta", "‼️")
check("reactions.set stores Theta's side", r == {"theta": "‼️"} and db.get_message(u["id"])["meta"]["reactions"] == {"theta": "‼️"}, r)
call("/api/messages/react", "POST", {"id": u["id"], "emoji": "👍"})
s, j = call("/api/messages/react", "GET", query=f"id={u['id']}")
check("both sides live side by side, and GET reads them", s == 200 and j["reactions"] == {"theta": "‼️", "user": "👍"}, j)
try:
    reactions.set(u["id"], "someone", "❤️")
    check("who must be user or theta", False)
except ValueError:
    check("who must be user or theta", True)
check("set on a missing message returns None", reactions.set(424242, "theta", "❤️") is None)

spec = [t for t in tools.specs() if t["name"] == "react"]
check("the react tool is offered to the model", bool(spec))
tool = tools.BY_NAME.get("react")
check("and it's a write tool (runs freely, changes only your chat)", tool and tool["risk"] == "write")
check("its description says to use it sparingly", tool and "sparingly" in tool["description"])
u2 = db.add_message("theta", "user", "happy birthday to me")
ctx = {"bot": "theta", "user_id": u2["id"]}
ok, out = tools.execute("react", {"emoji": "heart"}, ctx)
check("the tool reacts to the user's message in this turn", ok and db.get_message(u2["id"])["meta"]["reactions"] == {"theta": "❤️"}, out)
check("and tells the app which message", ctx.get("reactions") == [{"id": u2["id"], "theta": "❤️"}], ctx)
ok, out = tools.execute("react", {"emoji": "not an emoji"}, {"bot": "theta", "user_id": u2["id"]})
check("a bad emoji is a fixable tool error", not ok and "emoji" in out, out)
ok, out = tools.execute("react", {"emoji": "😂"}, {"bot": "theta"})
latest = db.last_user_message("theta")
check("without a user_id it uses the user's last message", ok and db.get_message(latest["id"])["meta"]["reactions"]["theta"] == "😂", out)

if FAILED:
    print(f"\n{len(FAILED)} failed")
    sys.exit(1)
print("\nall passed")
