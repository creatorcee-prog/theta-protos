"""Live-call voices: one of Gemini's preset voices for the whole call (server/livecall.py), picked in Settings >
Phone calls > Live call voice (setting "call_voice_live"; default Puck, Google's own default). GET
/api/calls/voice_sample?voice=Kore plays a short sample in that voice, made by the same model the calls use (made
once per voice, then kept in the data folder).
"""
import asyncio
import io
import os
import wave

from . import db
from .livecall import connect

# Gemini's 30 preset voices, with Google's one-word description of each (Live API docs, "Configure language and voice")
VOICES = [("Zephyr", "Bright"), ("Puck", "Upbeat"), ("Charon", "Informative"), ("Kore", "Firm"), ("Fenrir", "Excitable"),
          ("Leda", "Youthful"), ("Orus", "Firm"), ("Aoede", "Breezy"), ("Callirrhoe", "Easy-going"), ("Autonoe", "Bright"),
          ("Enceladus", "Breathy"), ("Iapetus", "Clear"), ("Umbriel", "Easy-going"), ("Algieba", "Smooth"),
          ("Despina", "Smooth"), ("Erinome", "Clear"), ("Algenib", "Gravelly"), ("Rasalgethi", "Informative"),
          ("Laomedeia", "Upbeat"), ("Achernar", "Soft"), ("Alnilam", "Firm"), ("Schedar", "Even"), ("Gacrux", "Mature"),
          ("Pulcherrima", "Forward"), ("Achird", "Friendly"), ("Zubenelgenubi", "Casual"), ("Vindemiatrix", "Gentle"),
          ("Sadachbia", "Lively"), ("Sadaltager", "Knowledgeable"), ("Sulafat", "Warm")]
DEFAULT_VOICE = "Puck"
SAMPLE_LINE = "Hi, this is Theta, an AI assistant. This is how I'll sound when I call for you."


def voice():
    v = db.get_setting("call_voice_live")
    return v if v in dict(VOICES) else DEFAULT_VOICE


def set_voice(name):
    if name not in dict(VOICES):
        raise ValueError("unknown voice")
    db.set_setting("call_voice_live", name)
    return name


async def sample_pcm(name):
    """A few seconds of `name` saying SAMPLE_LINE: 24 kHz 16-bit mono PCM."""
    audio = b""
    async with connect("You read lines aloud exactly as written, nothing else.", name) as session:
        await session.send_client_content(turns={"role": "user", "parts": [{"text": f"Say exactly: {SAMPLE_LINE}"}]},
                                          turn_complete=True)
        async for m in session.receive():
            sc = m.server_content
            if sc and sc.model_turn:
                for part in sc.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        audio += part.inline_data.data
            if sc and sc.turn_complete:
                break
    return audio


def wav(pcm, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def sample_route(req, start):
    """GET /api/calls/voice_sample?voice=Kore: a short WAV of that voice (made once, then kept)."""
    from .app import HTTPError
    name = req.query.get("voice") or ""
    if name not in dict(VOICES):
        raise HTTPError(404, "no such voice")
    path = os.path.join(db.data_dir(), "voice_samples", f"{name}.wav")
    if not os.path.isfile(path):
        if not os.environ.get("GEMINI_API_KEY"):
            raise HTTPError(503, "voice samples need GEMINI_API_KEY on the server")
        try:
            pcm = asyncio.run(asyncio.wait_for(sample_pcm(name), 25))
        except Exception as e:  # noqa: BLE001
            raise HTTPError(502, f"couldn't make a sample ({type(e).__name__})") from None
        if not pcm:
            raise HTTPError(502, "the voice service sent no audio")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(wav(pcm))
    with open(path, "rb") as f:
        body = f.read()
    start("200 OK", [("Content-Type", "audio/wav"), ("Content-Length", str(len(body))),
                     ("Cache-Control", "private, max-age=86400")])
    return [body]
