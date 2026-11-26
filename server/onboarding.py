"""Onboarding: the first time someone opens the app, Theta introduces itself in the chat and sets things up as
they answer, like a person texting. Questions come as cards with tap answers (A, B, C), and most can also be
answered by just typing in the chat. Every step can be skipped, progress is saved, and Settings can run it again.

    GET  /api/onboarding                     {needed, done, step, bot_name}
    POST /api/onboarding {start: true, tz?}  posts the current step's texts once (resumes where they left off);
                                             tz (the phone's zone) is saved if no zone was ever set
    POST /api/onboarding {step, answer}      answers the current step ("skip" skips it); posts what comes next
    POST /api/onboarding {reset: true}       Settings > Run the intro again

Steps: hello (asks their name), me (what to call Theta), notify, google, first, done.
- hello: their name, typed in the chat. Saved to memory. Theta reacts to the answer with a party popper.
- me: a name for Theta (tap one or type one), saved as the "bot_name" setting; "Renamed to X" shows in the chat.
- notify: the app subscribes to push on the tap (the answer says how it went).
- google: a connect card. Once Google is connected it flips to "Added" and the intro moves on by itself.
  Skipped when the server has no Google sign-in set up.
- first: offers a first task. Tapping one sends it as a normal chat message, so the model does real work.
  Anything typed from the google step on ends the intro and goes to the model as usual.

Theta's texts are assistant messages with meta {source: "onboarding", onboarding: step, cards: [...]}. The
question card {type: "onboarding", step, question, options, hint, dismiss, answered} is drawn by
web/features/onboarding.js. Setting "onboarding_done" (a time) means it's finished.
"""
import re
import threading
import time

from . import db

STATE = "onboarding"
DONE = "onboarding_done"
STEPS = ("hello", "me", "notify", "google", "first", "done")
DEFAULT_NAME = "Theta"
NAME_IDEAS = ("Pip", "Finley")
HINT = "Or answer in the chat below"
_lock = threading.Lock()


# ---------------------------------------------------------------- state

def _fresh(now=None):
    return {"step": STEPS[0], "answers": {}, "posted": {}, "cards": {}, "started": now or time.time()}


def state():
    s = db.get_setting(STATE)
    if not isinstance(s, dict) or s.get("step") not in STEPS:
        s = _fresh()
    for k in ("answers", "posted", "cards"):
        if not isinstance(s.get(k), dict):
            s[k] = {}
    return s


def done():
    return db.get_setting(DONE) is not None


def bot_name():
    n = db.get_setting("bot_name")
    return n if isinstance(n, str) and n.strip() else DEFAULT_NAME


def public(s=None):
    s = s or state()
    fin = done()
    return {"needed": not fin, "done": fin, "step": "done" if fin else s["step"], "bot_name": bot_name()}


def _save(s):
    db.set_setting(STATE, s)


def _finish(s, now):
    s["step"] = "done"
    db.set_setting(DONE, now)


# ---------------------------------------------------------------- what Theta says

def _google():
    try:
        from . import google
        return google
    except Exception:  # noqa: BLE001
        return None


def _gmail_ready():
    g = _google()
    return bool(g and g.configured())


def _gmail_on():
    g = _google()
    return bool(g and g.connected("gmail"))


def _q(step, question, options, hint=HINT, dismiss=True):
    """A question card. options: [{label, answer}] answered through the route, or {label, chat} sent as a chat
    message (real work for the model), or {label, answer, do} where the app does something first (do: "push")."""
    return {"type": "onboarding", "step": step, "question": question, "options": options, "hint": hint,
            "dismiss": dismiss}


def _who(s):
    return (s["answers"].get("name") or "").strip()


FIRST_GMAIL = ("Look through my recent emails and suggest a few things you could take care of for me. "
               "Don't send, delete or change anything.")
FIRST_PLAIN = [
    {"label": "Set up a morning brief", "chat": "Set up a short morning brief for me every day at 7."},
    {"label": "Remind me about something", "chat": "I want you to remind me about something. Ask me what and when."},
    {"label": "Research something for me", "chat": "I want you to research something for me. Ask me what."},
]


def script(step, s):
    """[(text, cards)] Theta sends when a step starts."""
    me = bot_name()
    if step == "hello":
        return [(f"Hi! I'm {me}, your new personal assistant. I can help with your work and everyday life, and "
                 "take things off your plate.", []),
                ("First, what should I call you?", [_q("hello", None, [], hint="Answer in the chat below")])]
    if step == "me":
        who = _who(s)
        opts = [{"label": f"{DEFAULT_NAME} (keep it)", "answer": DEFAULT_NAME}] + \
               [{"label": n, "answer": n} for n in NAME_IDEAS]
        return [((f"Nice to meet you, {who}! " if who else "") + "And what would you like to call me?",
                 [_q("me", "What would you like to call me? You can always change this later.", opts)])]
    if step == "notify":
        return [("A little about me:\n\n"
                 "- I text you first when something matters: reminders, your briefs and alerts near you.\n"
                 "- I connect to your apps, like email and calendar, and use them the way you do. Anything that "
                 "sends, buys or deletes waits for your tap.",
                 [_q("notify", "Want a notification when I text you? I keep them for things that matter, and "
                               "quiet hours start at 10 PM.",
                     [{"label": "Turn on notifications", "answer": "on", "do": "push"},
                      {"label": "Not now", "answer": "skip"}], hint=None, dismiss=False)])]
    if step == "google":
        try:
            from . import cards
            conn = [dict(cards.connect("gmail"), onboarding="google")]
        except Exception:  # noqa: BLE001
            conn = []
        return [("Connect Gmail and I'll find something I can take care of for you right away. Nothing gets "
                 "sent without your approval. Or tell me what you need help with.", conn)]
    if step == "first":
        if _gmail_on():
            return [("Gmail is connected, and I'm ready to get to work. Here's some of what I can do with it:\n\n"
                     "- Draft replies and send them once you approve\n"
                     "- Clean up a cluttered inbox\n"
                     "- Unsubscribe you from newsletters you don't want\n"
                     "- Let you know when something important comes in",
                     [_q("first", "Want me to find a few things I can help with? I'll just read your recent "
                                  "emails for ideas. Nothing gets sent, deleted or changed.",
                         [{"label": "Suggest a first task", "chat": FIRST_GMAIL}])])]
        return [("Here's some of what I can do right now: set reminders and routines, look things up with "
                 "sources, plan your day, and draft things for your OK. Connect your apps any time in "
                 "Settings > Apps and I can do more.", [_q("first", "Where should we start?", FIRST_PLAIN)])]
    return []


def _post(step, s, first=False):
    out = []
    for i, (text, cards) in enumerate(script(step, s)):
        meta = {"source": "onboarding", "onboarding": step}
        if first and i == 0:
            meta["proactive"] = True
        if cards:
            meta["cards"] = cards
        m = db.add_message("theta", "assistant", text, meta)
        out.append(m)
        if cards:
            s["cards"][step] = m["id"]
    s["posted"][step] = [m["id"] for m in out]
    return out


def _mark(s, step, **fields):
    """Update the step's cards (answered: what was picked; connected: the connect card says Added)."""
    mid = s["cards"].get(step)
    m = db.get_message(mid) if mid else None
    if not m:
        return None
    cards = [dict(c, **fields) if isinstance(c, dict) and c.get("type") in ("onboarding", "connect") else c
             for c in (m.get("meta") or {}).get("cards") or []]
    return db.update_message(mid, meta={"cards": cards})


# ---------------------------------------------------------------- answers

class Bad(ValueError):
    """An answer that can't be used; the message says why."""


_LEAD = re.compile(r"^(?:(?:hi|hey|hello)[,!.\s]+)?(?:i'?m|i am|it'?s|my name is|call me|you can call me|"
                   r"let'?s go with|how about|name you|i'?ll call you|call you)\s+", re.I)


def _a_name(text):
    """A short name from what they typed ("I'm Cee" -> "Cee"), or "" if it doesn't look like one."""
    t = _LEAD.sub("", re.sub(r"\s+", " ", str(text or "")).strip()).strip(" .!?,\"'")
    if not t or len(t) > 32 or len(t.split()) > 3 or "?" in str(text) or not re.fullmatch(r"[\w .'-]+", t):
        return ""
    return t[:1].upper() + t[1:]


def _remember_name(name):
    try:
        from . import memory
        fact = f"Name: {name}"
        cur = memory.block()
        old = next((ln.lstrip("-* ").strip() for ln in cur.split("\n") if ln.lstrip("-* ").startswith("Name:")), None)
        memory.edit("replace", fact, old) if old else memory.edit("add", fact)
    except Exception:  # noqa: BLE001  memory is a nice-to-have here; the setting below still holds the name
        pass
    if not db.get_setting("call_name"):
        db.set_setting("call_name", name)


def _say(step, text, cards=None):
    meta = {"source": "onboarding", "onboarding": step}
    if cards:
        meta["cards"] = cards
    return db.add_message("theta", "assistant", text, meta)


def _apply(step, ans, s, now, typed_msg=None):
    """Do what the answer asks; returns the messages Theta sends back (before the next step's texts)."""
    out = []
    if step == "hello":
        name = _a_name(ans)
        if not name:
            raise Bad("type the name you'd like me to use, or skip")
        s["answers"]["name"] = name
        _remember_name(name)
        if typed_msg:
            try:
                from . import reactions
                reactions.set(typed_msg["id"], "theta", "🎉")
            except Exception:  # noqa: BLE001
                pass
    elif step == "me":
        name = _a_name(ans)
        if not name:
            raise Bad("pick a name or type one, up to three words")
        before = bot_name()
        db.set_setting("bot_name", name)
        s["answers"]["me"] = name
        who = _who(s)
        if name != before:
            out.append(_say("me", f"{name} it is!" + (f" Nice to meet you, {who}." if who else ""),
                            [{"type": "onboarding_event", "text": f"Renamed to {name}", "icon": "pencil"}]))
        else:
            out.append(_say("me", f"{name} it is." + (f" Good to meet you, {who}." if who else "")))
    elif step == "notify":
        on = ans in ("on", True, "yes")
        s["answers"]["notify"] = "on" if on else "off"
        if not on and ans not in ("skip", "off", None):
            out.append(_say("notify", "Notifications didn't turn on. You can try again in Settings > Alerts."))
    elif step == "google":
        s["answers"]["google"] = "connected" if _gmail_on() else "later"
    elif step == "first":
        s["answers"]["first"] = str(ans)[:80]
    return out


def _next(step):
    i = STEPS.index(step) + 1
    nxt = STEPS[i] if i < len(STEPS) else "done"
    if nxt == "google" and (not _gmail_ready() or _gmail_on()):
        nxt = "first"  # nothing to connect (no Google sign-in on the server), or it's connected already
    return nxt


def _advance(s, now, out):
    s["step"] = _next(s["step"])
    if s["step"] == "done":
        _finish(s, now)
        return
    out += _post(s["step"], s)
    if s["step"] == "first":
        _finish(s, now)  # the first task is an ordinary chat message; the intro's work is done once it's offered


def answer(step, ans, now=None, typed_msg=None):
    """Answer the current step. Returns (public state, new messages). Raises Bad."""
    now = now or time.time()
    with _lock:
        s = state()
        if done():
            return public(s), []
        if step != s["step"]:
            if step in STEPS and STEPS.index(step) < STEPS.index(s["step"]):
                return public(s), []  # already answered (a double tap, another device): nothing changes
            raise Bad(f"the intro is on {s['step']!r}, not {step!r}")
        out = []
        skipped = ans in ("skip", None)
        if skipped:
            if step == "me":
                s["answers"]["me"] = bot_name()
            label = "Skipped"
        else:
            out += _apply(step, ans, s, now, typed_msg)
            label = str(ans)[:40]
        _mark(s, step, answered=label)
        _advance(s, now, out)
        _save(s)
        return public(s), out


def typed(text, user_msg, now=None):
    """A chat message while the intro waits: the answer to a typed question (their name, Theta's name), or None
    to let the model handle it like any message (anything typed at the google step ends the intro)."""
    if done():
        return None
    s = state()
    step = s["step"]
    if not s["posted"].get(step):
        return None
    if step in ("hello", "me"):
        if not _a_name(text):
            return None
        try:
            _, msgs = answer(step, text, now, typed_msg=user_msg)
        except Bad:
            return None
        return msgs
    if step in ("google", "notify"):
        with _lock:
            s = state()
            _mark(s, step, answered="Skipped")
            _finish(s, now or time.time())
            _save(s)
    return None


def start(tz=None, now=None):
    """Post the current step's texts if they haven't gone out; returns (public state, new messages)."""
    now = now or time.time()
    with _lock:
        if done():
            return public(), []
        s = state()
        if tz and db.get_setting("tz") is None:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(str(tz))
                db.set_setting("tz", str(tz))
            except Exception:  # noqa: BLE001
                pass
        first = not s["posted"]
        out = []
        if not s["posted"].get(s["step"]):
            out += _post(s["step"], s, first=first)
        _save(s)
    if s["step"] == "google" and _gmail_on():  # back from Google's sign-in: the card says Added, and on we go
        with _lock:
            _mark(s, "google", connected=True)
            _save(s)
        st, more = answer("google", "connected", now)
        return st, out + more
    return public(s), out


def reset(tz=None, now=None):
    """Start over (Settings > Run the intro again). Earlier answers stay where they went (memory, settings)."""
    with _lock:
        _save(_fresh(now))
        db.set_setting(DONE, None)
    return start(tz, now)


# ---------------------------------------------------------------- route

def route(req, start_response):
    from .app import HTTPError, respond_json
    if req.method == "GET":
        return respond_json(start_response, public())
    if req.method != "POST":
        raise HTTPError(405, "method not allowed")
    body = req.json()
    if not isinstance(body, dict):
        raise HTTPError(400, "send a JSON object")
    tz = body.get("tz") if isinstance(body.get("tz"), str) else None
    try:
        if body.get("reset"):
            st, msgs = reset(tz)
        elif body.get("start"):
            st, msgs = start(tz)
        elif body.get("step"):
            st, msgs = answer(str(body["step"]), body.get("answer"))
        else:
            raise HTTPError(400, "send {start: true}, {step, answer} or {reset: true}")
    except Bad as e:
        raise HTTPError(400, str(e)) from None
    return respond_json(start_response, dict(st, messages=msgs))


ROUTES = {"/api/onboarding": route}


def intercept(bot, text, user_msg):
    """ext hook: a typed answer to the intro's current question. Returns Theta's messages, or None."""
    if bot != "theta":
        return None
    return typed(text, user_msg)


def context(bot, now):
    """While the intro runs, tell the model, so other messages are handled naturally."""
    if done() or not state()["posted"]:
        return ""
    return (f"Onboarding: the in-chat intro is on step {state()['step']!r}. The intro's cards do the setup; "
            "help with anything else they ask as usual.")
