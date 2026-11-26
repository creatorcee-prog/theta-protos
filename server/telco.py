"""The phone company behind calls, texts and recordings: Telnyx (preferred) or Twilio.

Telnyx is used when TELNYX_API_KEY is set; otherwise Twilio, as before. Calls use Telnyx TeXML, which takes the same
<Say>/<Gather>/<Hangup> markup server/calls.py writes, so the call logic is shared and only the plumbing differs.

Telnyx env (Railway variables):
    TELNYX_API_KEY          the API key (Bearer)
    TELNYX_FROM             your Telnyx number, +1...
    TELNYX_TEXML_APP_ID     the TeXML Application's id (calls are placed through it)
    TELNYX_PUBLIC_KEY       the account's Ed25519 public key (Mission Control > Keys & Credentials > Public Key), to
                            check that webhooks really come from Telnyx
    TELNYX_MESSAGING_PROFILE_ID   optional; texts go from TELNYX_FROM's profile otherwise

Webhooks: Telnyx signs them with Ed25519 (headers telnyx-signature-ed25519 and telnyx-timestamp, over
"<timestamp>|<raw body>"). When those headers are there they must verify, within 5 minutes. Telnyx doesn't document
signing for TeXML's own instruction fetches, so an unsigned request is accepted only on a call URL, whose id is
an unguessable 144-bit token only Telnyx was given; an unsigned incoming text is refused when TELNYX_PUBLIC_KEY is set.

Field names: TeXML follows TwiML's (CallSid, CallStatus, SpeechResult, CallDuration, AnsweredBy, RecordingUrl,
RecordingSid). Telnyx doesn't list every callback's fields, so read() also accepts JSON bodies and snake_case.
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import db
from .tools import ToolError

TELNYX = "https://api.telnyx.com/v2"
TOLERANCE = 300


def _env(name):
    return (os.environ.get(name) or "").strip()


def provider():
    if _env("TELNYX_API_KEY"):
        return "telnyx"
    if _env("TWILIO_ACCOUNT_SID") and _env("TWILIO_AUTH_TOKEN"):
        return "twilio"
    return None


def name():
    return {"telnyx": "Telnyx", "twilio": "Twilio"}.get(provider(), "a phone provider")


def from_number():
    return _env("TELNYX_FROM") if provider() == "telnyx" else _env("TWILIO_FROM")


def configured():
    p = provider()
    if p == "telnyx":
        return bool(_env("TELNYX_FROM") and _env("TELNYX_TEXML_APP_ID"))
    if p == "twilio":
        return bool(_env("TWILIO_FROM"))
    return False


def can_text():
    p = provider()
    return bool(p and from_number())


def missing():
    """What to set, in words, when it isn't set up."""
    if provider() == "telnyx":
        need = [k for k in ("TELNYX_FROM", "TELNYX_TEXML_APP_ID") if not _env(k)]
        return "set " + " and ".join(need) + " on the server" if need else ""
    return "set TELNYX_API_KEY, TELNYX_FROM and TELNYX_TEXML_APP_ID on the server"


# ---------------------------------------------------------------- Telnyx REST

def _telnyx(method, path, body=None, form=False, raw=False):
    url = path if path.startswith("http") else TELNYX + path
    data, headers = None, {"Authorization": "Bearer " + _env("TELNYX_API_KEY"), "Accept": "application/json"}
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            out = r.read(60 * 1024 * 1024)
            return out if raw else (json.loads(out.decode() or "{}") if out else {})
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode())
            msg = "; ".join(x.get("detail") or x.get("title") or "" for x in j.get("errors") or []) or str(e)
        except Exception:  # noqa: BLE001
            msg = str(e)
        raise ToolError(f"Telnyx refused it: {msg[:200]}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ToolError(f"couldn't reach Telnyx ({type(e).__name__})") from None


def _account_sid():
    """Telnyx's account id for TeXML REST paths: from the env, or learned from the first call webhook."""
    return _env("TELNYX_ACCOUNT_SID") or (db.get_setting("telnyx_account_sid") or "")


# ---------------------------------------------------------------- calls

def place_call(to, cid, base, record_params):
    """Dial `to`; Telnyx/Twilio then fetch the call's markup from base/api/calls/twiml/<cid>. Returns the call sid."""
    from . import calls
    common = {"To": to, "From": from_number(), "Url": f"{base}/api/calls/twiml/{cid}",
              "StatusCallback": f"{base}/api/calls/status/{cid}", "MachineDetection": "DetectMessageEnd",
              "TimeLimit": calls.MAX_SECONDS + 30, "Timeout": 30}
    if provider() == "telnyx":
        body = dict(common, UrlMethod="POST", StatusCallbackMethod="POST", StatusCallbackEvent="answered completed")
        for k, v in (record_params or {}).items():
            body[k] = (v == "true") if k == "Record" else v
        res = _telnyx("POST", f"/texml/calls/{urllib.parse.quote(_env('TELNYX_TEXML_APP_ID'))}", body)
        data = res.get("data") if isinstance(res.get("data"), dict) else res
        return str(data.get("call_sid") or data.get("sid") or data.get("CallSid") or "")
    params = dict(common, Method="POST", StatusCallbackMethod="POST", StatusCallbackEvent=["answered", "completed"],
                  TimeLimit=str(common["TimeLimit"]), Timeout=str(common["Timeout"]))
    params.update(record_params or {})
    res = calls._twilio("Calls.json", params)
    return str(res.get("sid") or "")


def stop_recording(call_sid):
    """Stop recording an in-progress call. True when the provider confirmed it."""
    from . import calls
    if not call_sid:
        return False
    try:
        if provider() == "telnyx":
            acct = _account_sid()
            if not acct:
                return False
            _telnyx("POST", f"/texml/Accounts/{acct}/Calls/{urllib.parse.quote(call_sid)}/Recordings/Twilio.CURRENT.json",
                    {"Status": "stopped"}, form=True)
            return True
        calls._twilio(f"Calls/{call_sid}/Recordings/Twilio.CURRENT.json", {"Status": "stopped"})
        return True
    except Exception:  # noqa: BLE001
        return False


def gather(action, prompt_xml):
    """The <Gather> for one turn of speech, in the provider's dialect."""
    from xml.sax.saxutils import escape
    if provider() == "telnyx":
        return (f'<Gather input="speech" timeout="6" speechTimeout="2" language="en-US" '
                f'action="{escape(action)}">{prompt_xml}</Gather>')
    return (f'<Gather input="speech" speechTimeout="auto" timeout="6" actionOnEmptyResult="true" '
            f'action="{escape(action)}" method="POST" language="en-US">{prompt_xml}</Gather>')


# ---------------------------------------------------------------- texts

def send_sms(to, body):
    """Send a text. Returns the provider's message id."""
    from . import calls
    if provider() == "telnyx":
        msg = {"from": from_number(), "to": to, "text": body}
        if _env("TELNYX_MESSAGING_PROFILE_ID"):
            msg["messaging_profile_id"] = _env("TELNYX_MESSAGING_PROFILE_ID")
        res = _telnyx("POST", "/messages", msg)
        return str((res.get("data") or {}).get("id") or "")
    res = calls._twilio("Messages.json", {"To": to, "From": from_number(), "Body": body})
    return str(res.get("sid") or "")


# ---------------------------------------------------------------- webhooks in

def _raw(req):
    if not hasattr(req, "_telco_raw"):
        try:
            n = int(req.env.get("CONTENT_LENGTH") or 0)
        except ValueError:
            n = 0
        req._telco_raw = req.env["wsgi.input"].read(min(n, 256 * 1024)) if n > 0 else b""
    return req._telco_raw


def read(req):
    """The webhook's fields as a flat dict (form, query or JSON; Telnyx's JSON {data: {payload}} is flattened)."""
    raw = _raw(req)
    out = {}
    ctype = (req.env.get("CONTENT_TYPE") or "").lower()
    if raw and ("json" in ctype or raw[:1] in (b"{", b"[")):
        try:
            j = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            j = {}
        d = j.get("data") if isinstance(j, dict) and isinstance(j.get("data"), dict) else j
        if isinstance(d, dict):
            out.update({k: v for k, v in d.items() if not isinstance(v, (dict, list))})
            if isinstance(d.get("payload"), dict):
                out.update(d["payload"])
    elif raw:
        out.update(urllib.parse.parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True))
    qs = urllib.parse.parse_qsl(req.env.get("QUERY_STRING") or "", keep_blank_values=True)
    for k, v in qs:
        out.setdefault(k, v)
    # snake_case (Telnyx JSON) -> the TwiML names the call code reads
    alias = {"call_sid": "CallSid", "call_status": "CallStatus", "speech_result": "SpeechResult",
             "call_duration": "CallDuration", "answered_by": "AnsweredBy", "recording_url": "RecordingUrl",
             "recording_sid": "RecordingSid", "recording_status": "RecordingStatus", "account_sid": "AccountSid",
             "duration": "CallDuration"}
    for a, b in alias.items():
        if a in out and b not in out:
            out[b] = out[a]
    return out


def _ed25519_ok(req, raw):
    sig, ts = req.header("telnyx-signature-ed25519"), req.header("telnyx-timestamp")
    key = _env("TELNYX_PUBLIC_KEY")
    if not (sig and ts and key):
        return None  # nothing to check
    try:
        if abs(time.time() - int(ts)) > TOLERANCE:
            return False
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(base64.b64decode(sig), ts.encode() + b"|" + raw)
        return True
    except Exception:  # noqa: BLE001  (bad key, bad signature, bad base64)
        return False


def verify(req, kind="call"):
    """Did this webhook come from the provider? kind "call" (a URL with a secret call id) or "sms"."""
    from . import calls
    if provider() == "telnyx":
        ok = _ed25519_ok(req, _raw(req))
        if ok is not None:
            return ok
        # unsigned: a call URL is a capability (its id is a secret only Telnyx was given); a text needs a signature
        return kind == "call" or not _env("TELNYX_PUBLIC_KEY")
    pairs = urllib.parse.parse_qsl(_raw(req).decode("utf-8", "replace"), keep_blank_values=True)
    return calls.verify(req, pairs)


def learn(params):
    """Remember Telnyx's account id from a call webhook (TeXML always sends AccountSid)."""
    acct = str(params.get("AccountSid") or "")
    if provider() == "telnyx" and re.fullmatch(r"[0-9a-fA-F-]{20,64}", acct) and db.get_setting("telnyx_account_sid") != acct:
        db.set_setting("telnyx_account_sid", acct)


# ---------------------------------------------------------------- recordings

def fetch_recording(url):
    """The recording's audio bytes (MP3)."""
    from . import calls
    if provider() == "telnyx":
        if not re.match(r"^https://", url or ""):
            raise ValueError("not an https recording URL")
        host = urllib.parse.urlsplit(url).hostname or ""
        if host.endswith("telnyx.com"):
            return _telnyx("GET", url, raw=True)
        req = urllib.request.Request(url)  # a pre-signed storage link
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read(60 * 1024 * 1024)
    if not re.match(r"^https://api\.twilio\.com/2010-04-01/Accounts/AC[0-9a-f]{32}/Recordings/RE[0-9a-f]{32}$", url or ""):
        raise ValueError("not a Twilio recording URL")
    sid, tok = calls._env("TWILIO_ACCOUNT_SID"), calls._env("TWILIO_AUTH_TOKEN")
    req = urllib.request.Request(url + ".mp3", headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(60 * 1024 * 1024)


def delete_recording(rec_sid):
    """Delete the provider's copy once Theta has its own."""
    from . import calls
    try:
        if provider() == "telnyx":
            acct = _account_sid()
            if acct and re.fullmatch(r"[A-Za-z0-9_:-]{4,128}", rec_sid or ""):
                _telnyx("DELETE", f"/texml/Accounts/{acct}/Recordings/{urllib.parse.quote(rec_sid)}.json", raw=True)
            return
        if not re.fullmatch(r"RE[0-9a-f]{32}", rec_sid or ""):
            return
        sid, tok = calls._env("TWILIO_ACCOUNT_SID"), calls._env("TWILIO_AUTH_TOKEN")
        req = urllib.request.Request(f"{calls.API}/Accounts/{sid}/Recordings/{rec_sid}.json", method="DELETE",
                                     headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()})
        urllib.request.urlopen(req, timeout=20).close()
    except Exception:  # noqa: BLE001  the provider keeps it then
        pass


# ---------------------------------------------------------------- the voice

VOICES = [  # (id shown in Settings, label, the <Say voice> value)
    ("natural-f", "Natural, warm (female)", "Polly.Joanna-Neural"),
    ("natural-m", "Natural, calm (male)", "Polly.Matthew-Neural"),
    ("natural-f2", "Natural, bright (female)", "Polly.Ruth-Neural"),
    ("natural-m2", "Natural, friendly (male)", "Polly.Stephen-Neural"),
    ("kokoro", "Telnyx Kokoro (female)", "Telnyx.KokoroTTS.af_heart"),
]
DEFAULT_VOICE_ID = "natural-f"


def voice_attrs():
    """(voice, extra attributes) for <Say>: the user's pick, or their own ElevenLabs voice."""
    v = db.get_setting("call_voice")
    v = v if isinstance(v, dict) else {}
    if v.get("kind") == "elevenlabs" and v.get("voice_id"):
        model = v.get("model") or "eleven_turbo_v2_5"
        extra = {"api_key_ref": v["key_ref"]} if v.get("key_ref") else {}
        return f"ElevenLabs.{model}.{v['voice_id']}", extra
    if v.get("kind") == "custom" and v.get("value"):
        return v["value"], {}
    pick = dict((i, val) for i, _l, val in VOICES).get(v.get("id") or DEFAULT_VOICE_ID)
    env = _env("THETA_CALL_VOICE")
    return (pick or env or VOICES[0][2]), {}
