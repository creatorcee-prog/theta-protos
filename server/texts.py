"""Text messages: Theta texts a saved contact (or a number) for the user, from the Twilio number, only after the
user taps Approve. Uses the same Twilio account as phone calls (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
TWILIO_FROM); until those are set, the approval card comes with a card to set Twilio up, and the text goes
out once it is and they approve.

Rules: one text per approval, at most DAILY_CAP a day, never to emergency, short-code or premium numbers, and
the recipient sees it come from the Twilio number (so the preview says that).
"""
import time

from . import db
from .tools import ToolError

DAILY_CAP = 20
MAX_CHARS = 640  # about four SMS segments


def configured():
    from . import calls
    return calls.configured()


def _target(args):
    from . import calls, contacts
    raw = str(args.get("to") or "")
    why = calls.blocked(raw) if raw.strip().lstrip("+").replace(" ", "").isdigit() else None
    if why:
        raise ToolError(why.replace("calls", "texts") + ". Nothing was sent.")
    number, name = contacts.resolve(raw, "phone")
    why = calls.blocked(number)
    if why:
        raise ToolError(why.replace("calls", "texts") + ". Nothing was sent.")
    body = str(args.get("message") or "").strip()
    if not body:
        raise ToolError("the text is empty; write what to say")
    if len(body) > MAX_CHARS:
        raise ToolError(f"that's {len(body)} characters; keep a text under {MAX_CHARS}")
    return number, name, body


def _preview(args):
    number, name, body = _target(args)
    who = f"{name} ({number})" if name else number
    return (f"**Text to {who}**\n{body}\n\n"
            "It comes from Theta's number, not yours, so they may not know it's you unless the text says so.")


def _sent_today(now):
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    v = db.get_setting("texts_sent") or {}
    return int(v.get(day) or 0) if isinstance(v, dict) else 0


def _count(now):
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    db.set_setting("texts_sent", {day: _sent_today(now) + 1})


def _send(args, ctx):
    from . import calls
    number, name, body = _target(args)
    if not configured():
        raise ToolError("texting isn't set up yet (it uses the Twilio account: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN "
                        "and TWILIO_FROM). Nothing was sent.")
    now = float((ctx or {}).get("now") or time.time())
    if _sent_today(now) >= DAILY_CAP:
        raise ToolError(f"that's the {DAILY_CAP}-a-day text limit. Nothing was sent.")
    res = calls._twilio("Messages.json", {"To": number, "From": calls._env("TWILIO_FROM"), "Body": body})
    _count(now)
    return f"Text sent to {name or number}" + (f" (Twilio id {res.get('sid')})." if res.get("sid") else ".")


TOOLS = [
    {"name": "send_text", "risk": "send", "run": _send, "preview": _preview,
     "description": ("Propose a text message (SMS) to a saved contact or a number. It does NOT send: the user sees "
                     "who, the number and the exact words, with Approve and Discard, and it goes out only after "
                     "Approve. `to` can be a contact's name ('Mom') or a number. Write it the way the user would, "
                     "and say who it's from if they wouldn't know Theta's number. Example: {\"to\": \"Mom\", "
                     "\"message\": \"Running about 15 min late, see you at 7. - Cee\"}."),
     "params": {"type": "object", "properties": {
         "to": {"type": "string", "description": "A saved contact's name, or a phone number."},
         "message": {"type": "string", "description": "The exact text to send."}},
         "required": ["to", "message"]}},
]

RELEVANT = r"\b(text|txt|sms|message|msg)\b"


def connections():
    on = configured()
    c = {"id": "sms", "name": "Text messages", "cat": "Messaging", "connected": on,
         "what": "Text your saved contacts, with your OK each time"}
    if not on:
        c["note"] = "Texting uses the Twilio account that phone calls use. Once Twilio is set up, this turns on."
    return [c]
