"""Telnyx as the phone provider (server/telco.py): calls through TeXML, the call's voice, texts out and in, Ed25519
webhook signatures, and recordings. Telnyx's API is faked with urlopen; a real Ed25519 key signs the webhooks."""
import base64, io, json, os, sys, tempfile, time, urllib.parse, urllib.request
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

KEY = Ed25519PrivateKey.generate()
PUB = base64.b64encode(KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"):
    os.environ.pop(k, None)
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_TZ="America/Denver", PROTOS_QUIET="1", PROTOS_PUBLIC_URL="https://theta.example",
                  TELNYX_API_KEY="KEYtest", TELNYX_FROM="+14355550000", TELNYX_TEXML_APP_ID="1293384261075731499", TELNYX_PUBLIC_KEY=PUB)
from server import calls, contacts, db, recordings, telco, texts, tools


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
tools._ext()
SENT = []


class Resp(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(req, timeout=None):
    body = json.loads(req.data.decode()) if req.data and req.get_header("Content-type") == "application/json" else (
        dict(urllib.parse.parse_qsl(req.data.decode())) if req.data else None)
    SENT.append((req.get_method(), req.full_url, body, req.get_header("Authorization")))
    if "/texml/calls/" in req.full_url:
        return Resp(json.dumps({"from": "+14355550000", "to": "+13035551234", "status": "queued", "call_sid": "v3:abc123"}).encode())
    if req.full_url.endswith("/messages"):
        return Resp(json.dumps({"data": {"id": "msg-1", "record_type": "message"}}).encode())
    if req.full_url.endswith(".mp3") and req.get_method() == "GET":
        return Resp(b"ID3fake-mp3")
    return Resp(b"{}")


urllib.request.urlopen = fake_urlopen

check("Telnyx is the provider once its key is set", telco.provider() == "telnyx" and calls.configured() and texts.configured())

# ---------------------------------------------------------------- placing a call
call = calls._dial("other", "+13035551234", name="Luigi's", purpose="book a table")
m, url, body, auth = SENT[-1]
check("a call goes to Telnyx TeXML through the TeXML app, with the key as Bearer", m == "POST"
      and url == "https://api.telnyx.com/v2/texml/calls/1293384261075731499" and auth == "Bearer KEYtest", (url, auth))
check("with the call's own URLs, from Theta's number, recorded both sides", body["To"] == "+13035551234" and body["From"] == "+14355550000"
      and body["Url"] == f"https://theta.example/api/calls/twiml/{call['id']}" and body["StatusCallback"].endswith(f"/status/{call['id']}")
      and body["Record"] is True and body["RecordingChannels"] == "dual" and body["StatusCallbackEvent"] == "answered completed", body)
check("the call's id from Telnyx is kept", calls.get_call(call["id"])["sid"] == "v3:abc123")

# ---------------------------------------------------------------- the voice
check("calls speak in a natural voice by default", 'voice="Polly.Joanna-Neural"' in calls._say("Hello"))
db.set_setting("call_voice", {"id": "natural-m"})
check("a picked voice is used", 'voice="Polly.Matthew-Neural"' in calls._say("Hello"))
db.set_setting("call_voice", {"kind": "elevenlabs", "voice_id": "21m00Tcm4TlvDq8ikWAM", "model": "eleven_turbo_v2_5", "key_ref": "elevenlabs_key"})
say = calls._say("Hello")
check("your own ElevenLabs voice, with Telnyx's secret name for the key", 'voice="ElevenLabs.eleven_turbo_v2_5.21m00Tcm4TlvDq8ikWAM"' in say
      and 'api_key_ref="elevenlabs_key"' in say, say)
g = calls._gather(call["id"], 2, "Anything else?")
check("speech is gathered in Telnyx's dialect (no Twilio-only attributes)", '<Gather input="speech"' in g and "actionOnEmptyResult" not in g
      and 'speechTimeout="2"' in g and "ElevenLabs." in g, g)
try:
    calls._clean_voice({"kind": "elevenlabs", "voice_id": "bad id!"}); bad = False
except Exception:  # noqa: BLE001
    bad = True
check("a malformed voice id is refused", bad)
db.set_setting("call_voice", {"id": "natural-f"})


# ---------------------------------------------------------------- webhooks: signed by Telnyx
class Req:
    def __init__(self, path, raw, ctype="application/x-www-form-urlencoded", signed=True, ts=None, method="POST", query=""):
        self.method, self.path, self.query = method, path, dict(urllib.parse.parse_qsl(query))
        self.env = {"wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)), "CONTENT_TYPE": ctype, "QUERY_STRING": query}
        ts = str(ts or int(time.time()))
        self._h = {"telnyx-timestamp": ts, "telnyx-signature-ed25519": base64.b64encode(KEY.sign(ts.encode() + b"|" + raw)).decode()} if signed else {}

    def header(self, name):
        return self._h.get(name)


form = urllib.parse.urlencode({"CallSid": "v3:abc123", "AccountSid": "f5586561-8ff0-4291-a51b-c7dfe4139ff9", "AnsweredBy": "human"}).encode()
r = Req(f"/api/calls/twiml/{call['id']}", form)
c2, params = calls._webhook(r, "/api/calls/twiml/")
check("a signed TeXML request is accepted and read", c2["id"] == call["id"] and params["AnsweredBy"] == "human")
check("Telnyx's account id is learned from it (for recordings)", db.get_setting("telnyx_account_sid") == "f5586561-8ff0-4291-a51b-c7dfe4139ff9")
r = Req(f"/api/calls/twiml/{call['id']}", form)
r._h["telnyx-signature-ed25519"] = base64.b64encode(b"x" * 64).decode()
try:
    calls._webhook(r, "/api/calls/twiml/"); forged = "accepted"
except Exception as e:  # noqa: BLE001
    forged = str(e)
check("a forged signature is refused", "signature" in forged, forged)
try:
    calls._webhook(Req(f"/api/calls/twiml/{call['id']}", form, ts=int(time.time()) - 900), "/api/calls/twiml/"); old = "accepted"
except Exception as e:  # noqa: BLE001
    old = str(e)
check("a replayed (15-minute-old) request is refused", "signature" in old, old)
c3, p3 = calls._webhook(Req(f"/api/calls/twiml/{call['id']}", form, signed=False), "/api/calls/twiml/")
check("an unsigned TeXML fetch on the call's secret URL still works (Telnyx doesn't document signing those)", c3["id"] == call["id"])
calls._update(call["id"], state="live", t_answer=time.time())
twiml = calls.twiml_for(calls.get_call(call["id"]), {"turn": "1", "SpeechResult": "please don't record this"})
check("an objection on a Telnyx call stops the recording there, and Theta says so", "stopped recording" in twiml
      and SENT[-1][1].endswith("/texml/Accounts/f5586561-8ff0-4291-a51b-c7dfe4139ff9/Calls/v3%3Aabc123/Recordings/Twilio.CURRENT.json")
      and SENT[-1][2] == {"Status": "stopped"}, (twiml, SENT[-1]))

# ---------------------------------------------------------------- recordings
call2 = calls._dial("me", "+14355550100", message="test")
rec_form = urllib.parse.urlencode({"RecordingStatus": "completed", "RecordingSid": "rec-123", "RecordingUrl": "https://storage.telnyx.com/rec-123.mp3"}).encode()
recordings.recorded_route(Req(f"/api/calls/recorded/{call2['id']}", rec_form), lambda s, h: None)
check("a recording is downloaded from Telnyx and kept here", recordings.has(call2["id"]) and open(recordings.path_for(call2["id"]), "rb").read() == b"ID3fake-mp3")
check("then Telnyx's copy is deleted", SENT[-1][0] == "DELETE" and SENT[-1][1].endswith("/Recordings/rec-123.json"), SENT[-1])

# ---------------------------------------------------------------- texts
contacts.upsert({"name": "Mom", "phone": "3035551234"})
ok, out = tools.run_approved({"tool": "send_text", "args": {"to": "Mom", "message": "On my way"}})
m, url, body, auth = SENT[-1]
check("a text goes through Telnyx's messages API", ok and url == "https://api.telnyx.com/v2/messages"
      and body == {"from": "+14355550000", "to": "+13035551234", "text": "On my way"}, (out, SENT[-1]))
inbound = json.dumps({"data": {"event_type": "message.received", "id": "ev1", "payload": {
    "from": {"phone_number": "+13035551234"}, "to": [{"phone_number": "+14355550000"}], "text": "Drive safe!"}}}).encode()
texts.inbound(Req("/api/texts/inbound", inbound, "application/json"), lambda s, h: None)
last = db.messages("theta", limit=1)[-1]
check("an incoming Telnyx text shows in the chat, framed, from the contact", last["meta"].get("source") == "text_in"
      and last["meta"]["comm"] == {"kind": "text_in", "to": "Mom", "number": "+13035551234", "body": "Drive safe!"}, last)
n = len(db.messages("theta", limit=500))
try:
    texts.inbound(Req("/api/texts/inbound", inbound, "application/json", signed=False), lambda s, h: None); unsigned = "accepted"
except Exception as e:  # noqa: BLE001
    unsigned = str(e)
check("an unsigned incoming text is refused", "signature" in unsigned and len(db.messages("theta", limit=500)) == n, unsigned)
receipt = json.dumps({"data": {"event_type": "message.finalized", "payload": {"from": {"phone_number": "+14355550000"}, "text": "On my way"}}}).encode()
texts.inbound(Req("/api/texts/inbound", receipt, "application/json"), lambda s, h: None)
check("delivery receipts don't show up as texts", len(db.messages("theta", limit=500)) == n)
print("all telnyx checks passed")
