"""Scheduled calls and calls to Theta (server/calls.py): "call Mom at 6 and say I'm late" is approved once and then
dialed by Theta at 6 with nobody at the phone (a reminder never stands in for a call); scheduled calls show up with
reminders and can be cancelled; the calling hours are checked for the time the call will be made. Calling Theta's
number: the user (signed, from their saved number) gets a conversation, anyone else gets a message taken, and the
transcript lands in the chat. And Theta can't say "I'll call" when no call was set up. No network."""
import io, os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp(), PROTOS_TZ="America/Denver",
                  TELNYX_API_KEY="KEY", TELNYX_FROM="+15550001111", TELNYX_TEXML_APP_ID="app1", PROTOS_PUBLIC_URL="https://theta.example")
from server import agent, app, calls, db, ext, telco, tools  # noqa: E402


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
db.set_setting("tz", "America/Denver")
ext.reset(); tools._ext_reset(); tools._ext()
calls.SYNC = True
dialed = []
telco.place_call = lambda to, cid, base, rec: dialed.append((to, cid)) or "sid-" + cid[:4]
calls._llm = lambda messages, max_tokens=160: "Left the message."
db.set_setting("phone", "+13035550100")
db.set_setting("call_name", "Cee")

# a time today at 18:00 Denver, in the future relative to a fixed "now" of 14:00
import datetime
from zoneinfo import ZoneInfo
day = datetime.datetime.now(ZoneInfo("America/Denver")).replace(hour=14, minute=0, second=0, microsecond=0)
NOW = day.timestamp()
calls._now = lambda: NOW
tools._now = lambda ctx: NOW
six = day.replace(hour=18).isoformat()

# ---- a call to someone else, later
args = {"to": "+13035550142", "name": "Mom", "purpose": "tell her Cee is running about 20 minutes late", "at": six}
prev = tools.BY_NAME["call_someone"]["preview"](args)
check("the approval card says when the call will be made", "6:00 PM" in prev or "18:00" in prev, prev)
ok, text = tools.run_approved({"tool": "call_someone", "args": args, "bot": "theta"})
jobs = [j for j in db.jobs("pending") if j["kind"] == "call"]
check("approving it schedules the call, it doesn't dial now", ok and "Scheduled" in text and not dialed and len(jobs) == 1, text)
check("scheduled calls are listed with reminders, so they can be seen and cancelled",
      "[call]" in tools.BY_NAME["reminders"]["run"]({"action": "list"}, {"bot": "theta"}))
msgs = app.run_jobs(now=day.replace(hour=18, minute=1).timestamp())
check("at 6 Theta dials it by itself (no second approval) and says so in the chat", dialed and dialed[0][0] == "+13035550142"
      and msgs and "Making the call you scheduled" in msgs[0]["text"], (dialed, msgs))
try:
    tools.BY_NAME["call_someone"]["preview"](dict(args, at=day.replace(hour=23).isoformat())); ok = False
except tools.ToolError as e:
    ok = "8:00" in str(e) and "reminder can't make a call" in str(e)
check("the calling hours are checked for the time of the call, and a reminder is never the fallback", ok)

# ---- calling the user later
dialed.clear()
out = tools.BY_NAME["call_me"]["run"]({"message": "Time to leave for the airport", "in_minutes": 30}, {"bot": "theta"})
check("call_me with a time is scheduled too", "Scheduled" in out and not dialed, out)
jid = [j for j in db.jobs("pending") if j["kind"] == "call"][0]["id"]
tools.BY_NAME["reminders"]["run"]({"action": "cancel", "id": jid}, {"bot": "theta"})
check("and can be cancelled like a reminder", db.get_job(jid)["state"] == "cancelled")

# ---- honesty: "I'll call her at 6" with only a reminder set
info = {"ok_tools": ["remind_me"], "side_effects": True, "approvals": []}
check("saying it'll call when only a reminder was set is caught", agent.unbacked_claim("Done, I'll call her at 6 and let her know.", info))
info = {"ok_tools": [], "approvals": [{"tool": "call_someone"}]}
check("but not when the call was set up", not agent.unbacked_claim("I'll call her at 6 once you approve.", info))


# ---- calling Theta
def inbound(frm, signed=True):
    telco.signed = lambda req: signed
    raw = f"From={frm.replace('+', '%2B')}&CallSid=c{time.time()}".encode()
    env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/calls/inbound", "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
           "CONTENT_TYPE": "application/x-www-form-urlencoded", "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "https"}
    got = {}
    body = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0])))).decode()
    return got["s"], body


s, xml = inbound("+13035550100")
check("the user calling from their number gets Theta, talking (no 'doesn't take calls')", s == 200 and "<Gather" in xml
      and "it's Theta" in xml and "take calls" not in xml, xml)
s, xml2 = inbound("+13035550100", signed=False)
check("an unsigned call from 'their number' is treated as anyone (caller ID can be faked)", "take a message" in xml2, xml2)
s, xml3 = inbound("+12125550199")
check("anyone else gets a message taken, without the owner's details", "Can I take a message" in xml3 and "3035550100" not in xml3, xml3)
c = calls.get_call(xml3.split("/api/calls/twiml/")[1].split("?")[0])
calls._update(c["id"], turns=calls._add_turn(c, "them", "It's Sam from the shop, call me back at 555 0199 about the lamp."))
calls.finish(c["id"])
m = db.messages("theta")[-1]
check("the message lands in the chat as a missed call with what they said", m["text"].startswith("Missed call from +12125550199")
      and "Them: It's Sam" in m["text"], m["text"][:120])
# a stray request (not GET/POST) opens nothing, and a call to Theta where nobody spoke posts nothing
env = {"REQUEST_METHOD": "PUT", "PATH_INFO": "/api/calls/inbound", "QUERY_STRING": "", "CONTENT_LENGTH": "0",
       "CONTENT_TYPE": "", "wsgi.input": io.BytesIO(b""), "wsgi.url_scheme": "https"}
got = {}
b"".join(app.app(env, lambda st, h: got.update(s=int(st.split()[0]))))
check("only GET and POST reach the incoming-call line", got["s"] == 405)
n = len(db.messages("theta"))
s, xml4 = inbound("+12125550123")
c4 = calls.get_call(xml4.split("/api/calls/twiml/")[1].split("?")[0])
calls.finish(c4["id"])
check("a call to Theta where nobody spoke adds nothing to the chat", len(db.messages("theta")) == n)

# ---- the 10-minute wait can be turned off (testing)
dialed.clear()
tools.BY_NAME["call_me"]["run"]({"message": "test one"}, {"bot": "theta"})
try:
    tools.BY_NAME["call_me"]["run"]({"message": "test two"}, {"bot": "theta"}); ok = False
except tools.ToolError:
    ok = True
db.set_setting("calls_gap_off", True)
tools.BY_NAME["call_me"]["run"]({"message": "test three"}, {"bot": "theta"})
check("the 10-minute wait holds by default, and turning it off lets a second call through", ok and len(dialed) == 2, dialed)
print("all scheduled and incoming call checks passed")
