"""Full-duplex calls (server/livecall.py, server/asgi.py): the audio conversions, the TeXML that opens the stream,
and a whole call through uvicorn: a fake Telnyx on the WebSocket, a fake Gemini Live session. Checks that only a
live call's secret id gets a stream, audio flows both ways (16 kHz to Telnyx), a barge-in sends "clear", both
sides land in the transcript, and Theta's goodbye ends the call. The HTTP app works the same through ASGI.
Skipped when uvicorn / starlette / a2wsgi / websockets / google-genai aren't installed."""
import asyncio, base64, contextlib, importlib.util, json, math, os, socket, struct, sys, tempfile, threading, time, types, urllib.error, urllib.request
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
NEEDS = ("uvicorn", "starlette", "a2wsgi", "websockets", "google.genai")
if not all(importlib.util.find_spec(m) for m in NEEDS):
    print("SKIP live calls: " + ", ".join(m for m in NEEDS if not importlib.util.find_spec(m)) + " not installed")
    sys.exit(0)
os.environ.update(PROTOS_KEY="", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_SELFCHECK="0", PROTOS_DATA=tempfile.mkdtemp(),
                  TELNYX_API_KEY="KEY", TELNYX_FROM="+15550001111", GEMINI_API_KEY="g-test", PROTOS_PUBLIC_URL="https://theta.example")
from server import calls, db, livecall  # noqa: E402


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


def tone(n, rate=16000, hz=220, amp=8000):
    return [int(amp * math.sin(2 * math.pi * hz * i / rate)) for i in range(n)]


def pcm(samples, order="little"):
    return struct.pack(("<" if order == "little" else ">") + f"{len(samples)}h", *samples)


# ---- audio
s = tone(16000)
check("byte order is read from speech-like audio, both ways", livecall.guess_order(pcm(s, "little")) == "little"
      and livecall.guess_order(pcm(s, "big")) == "big")
check("silence doesn't decide it", livecall.guess_order(pcm([0] * 16000)) is None)
check("big-endian L16 becomes little-endian for Gemini", livecall.to_le(pcm(s[:10], "big"), "big") == pcm(s[:10]))
out = livecall.resample_24k_to_16k(pcm(tone(2400, rate=24000)))
back = struct.unpack(f"<{len(out) // 2}h", out)
check("24 kHz becomes 16 kHz: 2 samples for every 3, same tone", len(back) == 1600
      and max(abs(a - b) for a, b in zip(back, tone(1600))) < 400)

# ---- TeXML
db.init()
calls._c()
xml = livecall.stream_xml("abc", "https://theta.example")
check("the stream opens bidirectional L16 at 16 kHz on wss", 'url="wss://theta.example/api/calls/stream/abc"' in xml
      and 'bidirectionalCodec="L16"' in xml and 'bidirectionalSamplingRate="16000"' in xml and 'bidirectionalMode="rtp"' in xml)


def new_call(cid, kind="other"):
    db._conn().execute("INSERT INTO calls (id, kind, to_number, name, purpose, conversation, state, t, bot) VALUES "
                       "(?, ?, '+15551230000', 'Shop', 'ask if they have the lamp in stock', 1, 'ringing', ?, 'theta')",
                       (cid, kind, time.time()))
    return calls.get_call(cid)


livecall.ASGI = False
x1 = calls.twiml_for(new_call("c1"), {})
livecall.ASGI = True
x2 = calls.twiml_for(new_call("c2"), {})
check("without ASGI it's the turn-by-turn call", "<Gather" in x1 and "<Stream" not in x1, x1)
check("with it, the call goes straight to the stream (Gemini says the opening, one voice), then a hang-up",
      "<Say" not in x2 and x2.index("<Connect>") < x2.index("<Hangup/>"), x2)
op = calls._opening(calls.get_call("c2"))
check("the opening counts as said when Gemini's transcript has it, punctuation and case aside",
      livecall.disclosed(op.upper().replace(",", "").replace(".", " uh."), op))
check("but not when it's missing or changed", not livecall.disclosed("Hi there, I'm calling about a lamp.", op)
      and not livecall.disclosed(op.replace("an AI assistant", "a person"), op))


# ---- a whole call through uvicorn
class FakeSession:
    """Gemini Live: once it has heard about a second of audio, it talks, gets cut off, then says goodbye."""
    def __init__(self, opening_ok=True):
        self.audio, self.notes, self.q, self.opening_ok = 0, [], asyncio.Queue(), opening_ok

    async def send_realtime_input(self, audio=None, **k):
        self.audio += len(audio.data)
        if self.audio >= 32000 and not getattr(self, "spoke", False):
            self.spoke = True
            NS = types.SimpleNamespace
            say = lambda text, data: NS(go_away=None, server_content=NS(input_transcription=None, interrupted=False, turn_complete=False,
                model_turn=NS(parts=[NS(inline_data=NS(data=data))]), output_transcription=NS(text=text)))
            heard = NS(go_away=None, server_content=NS(input_transcription=NS(text="Do you have the arc lamp?"), interrupted=False,
                       model_turn=None, output_transcription=None, turn_complete=False))
            await self.q.put([heard, say("Let me check that for", pcm(tone(4800, rate=24000))),
                              NS(go_away=None, server_content=NS(input_transcription=None, interrupted=True, model_turn=None,
                                                                 output_transcription=None, turn_complete=False)),
                              say("Thanks, that's all I needed. Goodbye!", pcm(tone(2400, rate=24000))),
                              NS(go_away=None, server_content=NS(input_transcription=None, interrupted=False, model_turn=None,
                                                                 output_transcription=None, turn_complete=True))])

    async def send_client_content(self, **k):
        self.notes.append(k)
        if "Say your opening" in str(k):  # it says the opening it was given (or, in the bad case, something else)
            NS = types.SimpleNamespace
            text = calls._opening(calls.get_call(self.cid)) if self.opening_ok else "Hey, what's up? Quick question about a lamp."
            await self.q.put([NS(go_away=None, server_content=NS(input_transcription=None, interrupted=False, turn_complete=False,
                                 model_turn=NS(parts=[NS(inline_data=NS(data=pcm(tone(2400, rate=24000))))]), output_transcription=NS(text=text))),
                              NS(go_away=None, server_content=NS(input_transcription=None, interrupted=False, model_turn=None,
                                                                 output_transcription=None, turn_complete=True))])

    async def receive(self):
        for m in await self.q.get():
            yield m


FAKE = FakeSession()


@contextlib.asynccontextmanager
async def fake_connect(instruction, voice_name="Puck", affective=False):
    FAKE.instruction, FAKE.voice = instruction, voice_name
    yield FAKE
livecall.connect = fake_connect
livecall._drain = None
livecall.Bridge._drain = lambda self: asyncio.sleep(0)

import uvicorn  # noqa: E402
from server import asgi  # noqa: E402
sock = socket.socket(); sock.bind(("127.0.0.1", 0)); PORT = sock.getsockname()[1]; sock.close()
srv = uvicorn.Server(uvicorn.Config(asgi.asgi_app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
threading.Thread(target=srv.run, daemon=True).start()
for _ in range(100):
    if srv.started:
        break
    time.sleep(0.05)
h = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health").read())
check("the HTTP app works the same through ASGI", h.get("ok") is True)

import websockets  # noqa: E402


async def telnyx(cid, frames=60):
    got = []
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/api/calls/stream/{cid}") as ws:
        await ws.send(json.dumps({"event": "connected"}))
        await ws.send(json.dumps({"event": "start", "start": {"media_format": {"encoding": "L16", "sample_rate": 16000}}}))
        await asyncio.sleep(0.6)  # the opening plays first
        audio = pcm(tone(16000 * 2), "little")
        try:  # the server may hang up first (a call that fails its opening check)
            for i in range(frames):
                await ws.send(json.dumps({"event": "media", "media": {"track": "inbound", "payload": base64.b64encode(audio[i * 640:(i + 1) * 640]).decode()}}))
        except websockets.ConnectionClosed:
            return got
        try:
            while True:
                got.append(json.loads(await asyncio.wait_for(ws.recv(), 5)))
        except (websockets.ConnectionClosed, asyncio.TimeoutError):
            pass
    return got


async def refused(cid):
    try:
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/api/calls/stream/{cid}") as ws:
            await asyncio.wait_for(ws.recv(), 3)
        return False
    except (websockets.ConnectionClosed, websockets.InvalidStatus, websockets.InvalidHandshake):
        return True

check("an unknown call id gets no stream", asyncio.run(refused("not-a-call")))
c3 = new_call("c3")
check("nor a call that isn't live yet", asyncio.run(refused("c3")))
calls._update("c3", state="live", t_answer=time.time())
from server import livevoice  # noqa: E402
livevoice.set_voice("Kore")
FAKE.cid = "c3"
events = asyncio.run(telnyx("c3"))
media = [e for e in events if e.get("event") == "media"]
check("Theta's audio comes back as Telnyx media frames at 16 kHz (20 ms each)", media and
      all(len(base64.b64decode(e["media"]["payload"])) <= 640 for e in media)
      and sum(len(base64.b64decode(e["media"]["payload"])) for e in media) == (1600 + 3200 + 1600) * 2, len(media))
check("the call uses the voice picked in Settings", FAKE.voice == "Kore")
T3 = calls.get_call("c3")["turns"]
check("Theta's first words on the call are the opening, word for word, recorded once", T3[0]["who"] == "theta"
      and livecall.disclosed(T3[0]["text"], calls._opening(calls.get_call("c3")))
      and sum(1 for t in T3 if "on behalf of" in t["text"]) == 1, T3[:2])
check("being talked over sends Telnyx a clear", {"event": "clear"} in events)
turns = calls.get_call("c3")["turns"]
check("both sides land in the call's transcript", any(t["who"] == "them" and "arc lamp" in t["text"] for t in turns)
      and any(t["who"] == "theta" and "Goodbye" in t["text"] for t in turns), turns)
check("and Theta's goodbye ended the call (the socket closed by itself)", events and not livecall._open)
check("the model is told to sound like a person, not a script", "not a call center" in FAKE.instruction
      and "How can I assist you" in FAKE.instruction)
check("the model is told to open with the exact disclosure and has no tools", "word for word" in FAKE.instruction
      and calls._opening(calls.get_call("c3")) in FAKE.instruction and "no tools" in FAKE.instruction)
FAKE = FakeSession(opening_ok=False)
FAKE.cid = "c4"
new_call("c4"); calls._update("c4", state="live", t_answer=time.time())
events = asyncio.run(telnyx("c4", frames=10))
check("if Gemini doesn't say the disclosure, the call ends before anything else", "opening" in (calls.get_call("c4")["outcome"] or "")
      and not FAKE.audio, calls.get_call("c4")["outcome"])

# ---- the voice setting and samples
check("30 voices, Puck by default", len(livevoice.VOICES) == 30 and livevoice.DEFAULT_VOICE == "Puck")
try:
    livevoice.set_voice("Siri"); ok = False
except ValueError:
    ok = True
check("only Gemini's own voices can be picked", ok and livevoice.voice() == "Kore")


async def fake_sample(name):
    return pcm(tone(2400, rate=24000))
livevoice.sample_pcm = fake_sample
r = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/calls/voice_sample?voice=Kore")
body = r.read()
check("a voice sample comes back as a WAV", r.headers["Content-Type"] == "audio/wav" and body[:4] == b"RIFF" and body[8:12] == b"WAVE")
try:
    urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/calls/voice_sample?voice=Nope"); ok = False
except urllib.error.HTTPError as e:
    ok = e.code == 404
check("an unknown voice gets no sample", ok)
st = json.loads(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/api/calls/settings", data=b'{"live_voice": "Sulafat"}',
                                                              headers={"content-type": "application/json"})).read())
check("Settings saves the live call voice and lists all 30", st["live_voice"] == "Sulafat" and len(st["live_voices"]) == 30)
srv.should_exit = True
print("all live call checks passed")
