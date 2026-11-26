"""Contacts, texting (send_text through Twilio, only after Approve) and picking a request back up once the app it
needed is connected (server/resume.py). No network: Twilio and the model are faked."""
import os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_TZ="America/Denver", PROTOS_TICK="0", PROTOS_QUIET="1")
for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
    os.environ.pop(k, None)
from server import agent, calls, contacts, db, ext, resume, texts, tools
from server.tools import ToolError


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


def raises(fn, *a):
    try:
        fn(*a)
    except (ToolError, ValueError) as e:
        return str(e)
    return ""


db.init()
ext.reset()
tools._ext()

# ---------------------------------------------------------------- contacts
mom = contacts.upsert({"name": "Mom", "phone": "(303) 555-1234", "note": "mom"})
check("a US number without +1 is stored in international form", mom["phone"] == "+13035551234", mom)
sam = contacts.upsert({"name": "Sam Rivera", "phone": "+44 20 7946 0958", "email": "sam@example.com", "note": "landlord"})
check("saving the same name again updates it", contacts.upsert({"name": "mom", "phone": "3035551234", "note": "my mom"})["id"] == mom["id"]
      and len(contacts.all_contacts()) == 2)
check("a contact needs a phone or an email", "phone number or an email" in raises(contacts.upsert, {"name": "X"}))
check("a bad number is refused with how to fix it", "+1 303" in raises(contacts.upsert, {"name": "X", "phone": "12"}))
check("find by first name and by relation", contacts.find("sam")[0]["name"] == "Sam Rivera" and contacts.find("landlord")[0]["name"] == "Sam Rivera")
check("resolve a name to a number", contacts.resolve("Mom") == ("+13035551234", "Mom"))
check("resolve a number to the contact it belongs to", contacts.resolve("303-555-1234") == ("+13035551234", "Mom"))
check("an unknown name says to ask the user", "Ask the user" in raises(contacts.resolve, "Grandpa"))
contacts.upsert({"name": "Sam Lee", "phone": "+13035550000"})
check("a name that fits two contacts asks which one", "more than one" in raises(contacts.resolve, "Sam"))
check("the model sees contact names in its context", "Mom (my mom)" in contacts.context("theta", time.time()))

# ---------------------------------------------------------------- texting
check("send_text is a send tool: it only proposes", tools.BY_NAME["send_text"]["risk"] == "send")
pv = tools.preview("send_text", {"to": "Mom", "message": "Running 15 late. - Cee"})
check("the approval card shows who, the number and the exact words", "Text to Mom (+13035551234)" in pv and "Running 15 late" in pv, pv)
check("emergency numbers are refused", "emergency" in raises(tools.preview, "send_text", {"to": "911", "message": "hi"}))
check("Texts shows in Apps as not connected without Twilio", texts.connections()[0]["connected"] is False)
ok, out = tools.run_approved({"tool": "send_text", "args": {"to": "Mom", "message": "hi"}})
check("an approved text without Twilio fails honestly", not ok and "isn't set up" in out, out)

sent = []
calls._twilio = lambda path, params: sent.append((path, params)) or {"sid": "SM123"}
os.environ.update(TWILIO_ACCOUNT_SID="AC1", TWILIO_AUTH_TOKEN="t", TWILIO_FROM="+15550001111")
ok, out = tools.run_approved({"tool": "send_text", "args": {"to": "Mom", "message": "On my way"}})
check("an approved text goes through Twilio's Messages API", ok and sent and sent[0][0] == "Messages.json"
      and sent[0][1] == {"To": "+13035551234", "From": "+15550001111", "Body": "On my way"}, (ok, out, sent))
db.set_setting("texts_sent", {time.strftime("%Y-%m-%d"): texts.DAILY_CAP})
ok, out = tools.run_approved({"tool": "send_text", "args": {"to": "Mom", "message": "again"}})
check("the daily text limit holds", not ok and "limit" in out and len(sent) == 1, out)
for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"):
    os.environ.pop(k)

# ---------------------------------------------------------------- picking it back up once connected
u0 = db.add_message("theta", "user", "text mom I'm on my way", {})
info0 = {"approvals": []}
ok0, said = agent._approval({"name": "send_text", "args": {"to": "Mom", "message": "On my way"}},
                            {"bot": "theta", "user_id": u0["id"]}, lambda *a: None, info0)
check("a text drafted before Twilio is set up is saved to pick back up", ok0 and resume._items()
      and resume._items()[0]["approvals"] == [info0["approvals"][0]["id"]], resume._items())
check("and the model is told it never sends by itself", "Never say it'll send by itself" in said, said)
db.set_setting(resume.SETTING, [])
u = db.add_message("theta", "user", "text mom I'm running late", {})
ctx = {"bot": "theta", "user_id": u["id"]}
aid = db.add_approval({"tool": "send_text", "args": {"to": "Mom", "message": "Running late"}, "bot": "theta",
                       "preview": "Text to Mom", "created": time.time(), "expires": time.time() + 86400})
resume.record(ctx, "twilio", aid)
check("a text waiting on Twilio is saved to pick back up", len(resume._items()) == 1 and resume._items()[0]["approvals"] == [aid])
check("nothing happens while it's still not connected", resume.run_ready() == [] and len(resume._items()) == 1)
os.environ.update(TWILIO_ACCOUNT_SID="AC1", TWILIO_AUTH_TOKEN="t", TWILIO_FROM="+15550001111")
msgs = resume.run_ready()
check("once Twilio is set up, Theta texts first that the draft can go, with Approve", len(msgs) == 1
      and msgs[0]["meta"]["proactive"] and "can go now" in msgs[0]["text"]
      and msgs[0]["meta"]["actions"][0] == {"label": "Approve", "value": f"approve:{aid}"}, msgs)
check("and nothing was sent by itself", len(sent) == 1 and not resume._items())

u2 = db.add_message("theta", "user", "clean up my inbox", {})
resume.record({"bot": "theta", "user_id": u2["id"]}, "google")
check("a failed request is saved for when Gmail connects", resume._items()[0]["text"] == "clean up my inbox")
ran = []


def fake_run(route, msgs, emit, info=None, ctx=None, **k):
    ran.append(msgs[-1]["content"] if isinstance(msgs[-1]["content"], str) else str(msgs[-1]["content"]))
    info.update(model="deepseek-chat", provider="deepseek", steps=2, tools=["gmail_search"])
    return "Gmail's connected, so I went through your inbox. 3 newsletters flood you most."


agent.run = fake_run
from server import router, routines
routines._quick_route = lambda now: router.Route("quick", "deepseek-chat", "deepseek", "test", (("deepseek", "deepseek-chat"),))
real_ready = agent._service_ready
agent._service_ready = lambda s: True if s == "google" else real_ready(s)
msgs = resume.run_ready()
check("once Gmail connects, the request runs again as a real tool turn", ran and "clean up my inbox" in ran[0]
      and "connected now" in ran[0], ran)
check("and Theta posts the result as a text of its own", msgs and msgs[0]["meta"]["source"] == "resume"
      and msgs[0]["meta"]["proactive"] and "3 newsletters" in msgs[0]["text"], msgs)
check("it runs once", resume.run_ready() == [] and len(ran) == 1)
resume.record({"bot": "theta", "routine": 3, "user_id": u2["id"]}, "tavily")
check("routines aren't saved for later", not resume._items())

print("all messaging checks passed")
