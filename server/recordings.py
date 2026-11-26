"""Call recordings: the audio of Theta's calls, kept with the transcript in Call history.

Consent, in code the model can't change:
- Calls to someone else open with the disclosure plus "This call is recorded." (calls.disclosure()). If they say
  they don't want that ("please don't record this"), recording stops right then, Theta says so, and the audio is
  deleted when Twilio hands it over: none of it is kept.
- Calls to the user are recorded only because the user turned recording on.
- Off entirely with the "record_calls" setting (Settings > Apps > Phone calls).

How: the call is placed with Twilio's Record=true (both sides, two channels). When Twilio's recording is ready it
POSTs to /api/calls/recorded/<call id> (signed, like every Twilio webhook). Theta downloads the MP3 into its own
storage (the data folder, recordings/<call id>.mp3) and deletes Twilio's copy, so the audio lives in one place.
Recordings older than KEEP_DAYS are deleted.

    GET /api/calls/audio/<call id>   the MP3 (signed-in only), with byte ranges so iPhone can play and seek it
"""
import base64
import os
import re
import threading
import time
import urllib.error
import urllib.request

from . import db

SETTING = "record_calls"
KEEP_DAYS = 90
NOTICE = "This call is recorded."
_OPT_OUT = re.compile(r"\b(don'?t|do not|please don'?t|stop|no|not okay with|not ok with|turn off|shouldn'?t)\b[^.?!]{0,30}"
                      r"\brecord", re.I)
_lock = threading.Lock()


def on():
    return db.get_setting(SETTING) is not False  # on unless the user turned it off


def folder():
    p = os.path.join(db.data_dir(), "recordings")
    os.makedirs(p, exist_ok=True)
    return p


def path_for(cid):
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", str(cid or "")):
        return None
    return os.path.join(folder(), f"{cid}.mp3")


def has(cid):
    p = path_for(cid)
    return bool(p and os.path.isfile(p))


def _declined():
    v = db.get_setting("recording_declined")
    return v if isinstance(v, dict) else {}


def declined(cid):
    return cid in _declined()


# ---------------------------------------------------------------- hooks from server/calls.py

def dial_params(cid, base):
    """Extra Twilio call parameters when recording is on."""
    if not on():
        return {}
    return {"Record": "true", "RecordingChannels": "dual",
            "RecordingStatusCallback": f"{base}/api/calls/recorded/{cid}", "RecordingStatusCallbackMethod": "POST",
            "RecordingStatusCallbackEvent": "completed"}


def objects(heard):
    """Did they say they don't want to be recorded?"""
    return bool(_OPT_OUT.search(heard or ""))


def stop(call):
    """They objected: stop recording now and remember to delete the audio. Returns what Theta says."""
    from . import calls
    with _lock:
        d = _declined()
        d[call["id"]] = time.time()
        db.set_setting("recording_declined", d)
    if call.get("sid"):
        try:
            calls._twilio(f"Calls/{call['sid']}/Recordings/Twilio.CURRENT.json", {"Status": "stopped"})
        except Exception:  # noqa: BLE001  the audio is deleted on arrival either way
            pass
    return "Of course. I've stopped recording, and none of it will be kept."


# ---------------------------------------------------------------- Twilio hands the recording over

def _auth():
    from . import calls
    sid, tok = calls._env("TWILIO_ACCOUNT_SID"), calls._env("TWILIO_AUTH_TOKEN")
    return "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()


def _twilio_media(url):
    """Twilio's recording URLs only; returns the MP3 bytes."""
    if not re.match(r"^https://api\.twilio\.com/2010-04-01/Accounts/AC[0-9a-f]{32}/Recordings/RE[0-9a-f]{32}$", url or ""):
        raise ValueError("not a Twilio recording URL")
    req = urllib.request.Request(url + ".mp3", headers={"Authorization": _auth()})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(60 * 1024 * 1024)


def _delete_at_twilio(rec_sid):
    from . import calls
    if not re.fullmatch(r"RE[0-9a-f]{32}", rec_sid or ""):
        return
    req = urllib.request.Request(f"{calls.API}/Accounts/{calls._env('TWILIO_ACCOUNT_SID')}/Recordings/{rec_sid}.json",
                                 method="DELETE", headers={"Authorization": _auth()})
    try:
        urllib.request.urlopen(req, timeout=20).close()
    except Exception:  # noqa: BLE001  Twilio keeps it then; nothing else to do
        pass


def recorded_route(req, start_response):
    from . import calls
    call, params = calls._webhook(req, "/api/calls/recorded/")
    if (params.get("RecordingStatus") or "").lower() == "completed":
        rec_sid, url = params.get("RecordingSid") or "", params.get("RecordingUrl") or ""
        if not declined(call["id"]):
            try:
                blob = _twilio_media(url)
                p = path_for(call["id"])
                with open(p + ".part", "wb") as f:
                    f.write(blob)
                os.replace(p + ".part", p)
            except Exception as e:  # noqa: BLE001  keep Twilio's copy so it isn't lost
                print(f"[protos] recording download failed for {call['id'][:6]}: {e!r}", flush=True)
                return calls._xml(start_response, "<Response></Response>")
        _delete_at_twilio(rec_sid)
    return calls._xml(start_response, "<Response></Response>")


# ---------------------------------------------------------------- playing it back

def audio_route(req, start_response):
    from .app import HTTPError
    if req.method != "GET":
        raise HTTPError(405, "method not allowed")
    cid = req.path[len("/api/calls/audio/"):].strip("/")
    p = path_for(cid)
    if not p or not os.path.isfile(p):
        raise HTTPError(404, "no recording for that call")
    size = os.path.getsize(p)
    lo, hi, status = 0, size - 1, "200 OK"
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (req.header("Range") or "").strip())
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            lo = int(m.group(1))
            hi = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        else:  # the last N bytes
            lo = max(0, size - int(m.group(2)))
        if lo > hi or lo >= size:
            start_response("416 Range Not Satisfiable", [("Content-Range", f"bytes */{size}")])
            return [b""]
        status = "206 Partial Content"
    with open(p, "rb") as f:
        f.seek(lo)
        data = f.read(hi - lo + 1)
    headers = [("Content-Type", "audio/mpeg"), ("Content-Length", str(len(data))), ("Accept-Ranges", "bytes"),
               ("Cache-Control", "private, max-age=3600")]
    if status.startswith("206"):
        headers.append(("Content-Range", f"bytes {lo}-{hi}/{size}"))
    start_response(status, headers)
    return [data]


def tick(now):
    """Delete recordings older than KEEP_DAYS."""
    try:
        for name in os.listdir(folder()):
            p = os.path.join(folder(), name)
            if name.endswith(".mp3") and now - os.path.getmtime(p) > KEEP_DAYS * 86400:
                os.remove(p)
    except OSError:
        pass
    return []


ROUTES = {"/api/calls/audio/": audio_route}
PUBLIC_ROUTES = {"/api/calls/recorded/": recorded_route}
