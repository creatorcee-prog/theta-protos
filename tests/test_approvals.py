"""Settings > Security > Approvals (server/approvals.py): each send action asks first or runs without a tap, and
outward ones (email, texts, calls, invites, sharing, websites) only run alone in a turn the user typed that read
no outside text. No network: tools and Google are faked."""
import os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_TZ="America/Denver", PROTOS_QUIET="1")
from server import agent, approvals, db, google, tools


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
tools._ext()
google.connected = lambda service=None: True
google._need = lambda service: None
ran = []
tools.BY_NAME["gmail_trash"]["run"] = lambda a, c: ran.append(("trash", a)) or "Moved 3 to Trash."
tools.BY_NAME["gmail_trash"]["preview"] = lambda a: "**Move 3 emails to Trash**"
tools.BY_NAME["send_email_draft"]["run"] = lambda a, c: ran.append(("email", a)) or "Sent."
EMAIL = {"to": "sam@example.com", "subject": "Hi", "body": "Hello"}


def turn(name, args, ctx, earlier=()):
    info = {"tools": list(earlier), "approvals": [], "side_effects": False}
    res = agent._run_tools([{"id": "c1", "name": name, "args": args}], ctx, lambda e, d: None, info, time.monotonic() + 30)
    return res[0], info


names = {p["tool"] for p in approvals.policy()}
check("every send tool has a setting", names == {n for n, t in tools.BY_NAME.items() if t["risk"] == "send"},
      names ^ {n for n, t in tools.BY_NAME.items() if t["risk"] == "send"})
check("everything asks by default, except reviewed texts", [p["tool"] for p in approvals.policy() if p["auto"]] == ["send_text"])

u = db.add_message("theta", "user", "trash the AliExpress mail", {})
ctx = {"bot": "theta", "user_id": u["id"]}
(c, ok, text), info = turn("gmail_trash", {"query": "from:aliexpress.com"}, ctx)
check("asking: an approval card, nothing run", info["approvals"] and not ran)

approvals.set_on("gmail_trash", True)
ctx = {"bot": "theta", "user_id": u["id"]}
(c, ok, text), info = turn("gmail_trash", {"query": "from:aliexpress.com"}, ctx)
check("allowed: it runs at once, no approval card", ok and ran and not info["approvals"] and "without asking" in text, text)
check("and a receipt card shows exactly what was done", any(cd.get("type") == "approval" and cd.get("state") == "auto"
      and "Trash" in cd.get("preview", "") for cd in ctx.get("cards", [])), ctx.get("cards"))
ran.clear()
(c, ok, text), info = turn("gmail_trash", {"query": "from:aliexpress.com"}, {"bot": "theta", "routine": 2}, earlier=["gmail_search"])
check("tidy actions also run from a routine, or after reading mail", ok and ran)

approvals.set_on("send_email_draft", True)
ran.clear()
(c, ok, text), info = turn("send_email_draft", EMAIL, {"bot": "theta", "user_id": u["id"]})
check("an allowed email sends at once in a turn the user typed", ok and ran == [("email", EMAIL)])
ran.clear()
ctx = {"bot": "theta", "user_id": u["id"]}
(c, ok, text), info = turn("send_email_draft", EMAIL, ctx, earlier=["gmail_read"])
check("but never after reading an email: approval card, with the reason", info["approvals"] and not ran
      and "outside text" in text, text)
(c, ok, text), info = turn("send_email_draft", EMAIL, {"bot": "theta", "routine": 1})
check("and never from a routine", info["approvals"] and not ran)

approvals.set_on("send_text", False)
check("the texts switch is the same setting as Contacts' one", db.get_setting("texts_auto") is False)
try:
    approvals.set_on("gmail_search", True)
    bad = False
except ValueError:
    bad = True
check("read tools aren't in the list", bad)
# a tap in a list of approvals is quiet: the row's mark says what happened, no chat bubble per tap
from server import app
aid = db.add_approval({"tool": "gmail_trash", "args": {"query": "from:x.com"}, "bot": "theta", "preview": "**Move 3 emails to Trash**",
                       "created": time.time(), "expires": time.time() + 86400})
holder = db.add_message("theta", "assistant", "Ready.", {"cards": app.approval_cards([{"id": aid, "tool": "gmail_trash", "preview": "x"}])})
n0 = len(db.messages("theta", limit=500))
res = app.decide_approval(aid, "deny", quiet=True)
check("a quiet tap adds no message, and the card shows the outcome", res["message"] is None and len(db.messages("theta", limit=500)) == n0
      and db.get_message(holder["id"])["meta"]["cards"][0]["state"] == "denied")
print("all approvals checks passed")
