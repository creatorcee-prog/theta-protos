"""Call recordings (server/recordings.py): the notice in the opening line, Twilio's Record params, stopping when
the other person objects (and keeping none of it), downloading the audio and deleting Twilio's copy, and playing it
back with byte ranges. Twilio is faked; nothing leaves the machine."""
import io, os, sys, tempfile, time, urllib.parse, urllib.request
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_TZ="America/Denver", PROTOS_QUIET="1",
                  TWILIO_ACCOUNT_SID="AC" + "1" * 32, TWILIO_AUTH_TOKEN="tok-secret", TWILIO_FROM="+15005550006",
                  PROTOS_PUBLIC_URL="https://theta.example")
from server import calls, db, recordings


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
SENT = []
calls._twilio = lambda path, params: SENT.append((path, params)) or {"sid": "CA" + "2" * 32}

# ---------------------------------------------------------------- the notice, and asking Twilio to record
check("recording is on unless the user turns it off", recordings.on())
check("the opening says the call is recorded", calls.disclosure().endswith("This call is recorded."), calls.disclosure())
call = calls._dial("other", "+13035551234", name="Luigi's", purpose="book a table")
params = SENT[-1][1]
check("the call is placed with Record on, both sides, and a webhook for the audio", params.get("Record") == "true"
      and params.get("RecordingChannels") == "dual" and params["RecordingStatusCallback"].endswith(f"/api/calls/recorded/{call['id']}"), params)
db.set_setting("record_calls", False)
check("turned off: no notice and no recording", "recorded" not in calls.disclosure() and recordings.dial_params("x" * 20, "https://t") == {})
db.set_setting("record_calls", True)

# ---------------------------------------------------------------- they'd rather not
for heard, want in (("please don't record this", True), ("I don't want to be recorded", True), ("stop recording please", True),
                     ("no recording thanks", True), ("table for two at seven", False), ("I record music for a living", False)):
    check(f"objection heard right: {heard!r}", recordings.objects(heard) is want)
calls._update(call["id"], state="live", sid="CA" + "2" * 32, t_answer=time.time())
twiml = calls.twiml_for(calls.get_call(call["id"]), {"turn": "1", "SpeechResult": "Sure, but please don't record this"})
check("when they object, recording stops at once and Theta says so", "stopped recording" in twiml
      and SENT[-1] == (f"Calls/CA{'2' * 32}/Recordings/Twilio.CURRENT.json", {"Status": "stopped"}) and recordings.declined(call["id"]), (twiml, SENT[-1]))


# ---------------------------------------------------------------- Twilio hands the recording over
class Req:
    def __init__(self, path, form, method="POST", headers=None):
        self.method, self.path, self.query = method, path, {}
        body = urllib.parse.urlencode(form).encode()
        self.env = {"wsgi.input": io.BytesIO(body), "CONTENT_LENGTH": str(len(body)), "QUERY_STRING": ""}
        self._h = dict(headers or {})
        self._h.setdefault("X-Twilio-Signature", calls.signature("https://theta.example" + path, form, "tok-secret"))

    def header(self, name):
        return self._h.get(name)


def started(status, headers):
    started.status, started.headers = status, dict(headers)


MP3 = b"ID3" + bytes(range(256)) * 40
FETCHED, DELETED = [], []


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(req, timeout=None):
    if req.get_method() == "DELETE":
        DELETED.append(req.full_url); return Resp(b"")
    FETCHED.append(req.full_url); return Resp(MP3)


urllib.request.urlopen = fake_urlopen
url = f"https://api.twilio.com/2010-04-01/Accounts/AC{'1' * 32}/Recordings/RE{'a' * 32}"
form = {"RecordingStatus": "completed", "RecordingSid": "RE" + "a" * 32, "RecordingUrl": url, "RecordingDuration": "94"}
recordings.recorded_route(Req(f"/api/calls/recorded/{call['id']}", form), started)
check("a declined call's audio is never downloaded, and Twilio's copy is deleted", not FETCHED and DELETED and not recordings.has(call["id"]))

call2 = calls._dial("me", "+14355550100", message="test")
recordings.recorded_route(Req(f"/api/calls/recorded/{call2['id']}", form), started)
check("otherwise the MP3 is saved here, then deleted at Twilio", FETCHED == [url + ".mp3"] and len(DELETED) == 2 and recordings.has(call2["id"]))
check("call history links the recording", next(c for c in calls.history() if c["id"] == call2["id"])["audio"] == f"/api/calls/audio/{call2['id']}")
bad = Req(f"/api/calls/recorded/{call2['id']}", form, headers={"X-Twilio-Signature": "forged"})
try:
    recordings.recorded_route(bad, started); forged = "accepted"
except Exception as e:  # noqa: BLE001
    forged = str(e)
check("an unsigned webhook is refused", "signature" in forged, forged)

# ---------------------------------------------------------------- playing it back
body = b"".join(recordings.audio_route(Req(f"/api/calls/audio/{call2['id']}", {}, "GET", {"X-Twilio-Signature": ""}), started))
check("the whole MP3, as audio/mpeg with byte ranges offered", started.status == "200 OK" and body == MP3
      and started.headers["Content-Type"] == "audio/mpeg" and started.headers["Accept-Ranges"] == "bytes")
body = b"".join(recordings.audio_route(Req(f"/api/calls/audio/{call2['id']}", {}, "GET", {"Range": "bytes=100-199", "X-Twilio-Signature": ""}), started))
check("a byte range (how iPhone plays audio) gets 206 with just those bytes", started.status.startswith("206") and body == MP3[100:200]
      and started.headers["Content-Range"] == f"bytes 100-199/{len(MP3)}")
os.utime(recordings.path_for(call2["id"]), (time.time() - 91 * 86400,) * 2)
recordings.tick(time.time())
check("recordings older than 90 days are deleted", not recordings.has(call2["id"]))
print("all recordings checks passed")
