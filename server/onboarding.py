"""Onboarding: the first time someone signs in, Theta texts them in the chat itself, one step at a time, and sets
things up as they answer. Every step can be skipped, progress is saved, and Settings can run it again.

    GET  /api/onboarding                  {needed, done, step, index, steps, answers, skipped}
    POST /api/onboarding {start: true, tz?}        posts the current step's texts (once); resumes where they left
    POST /api/onboarding {step, answer}            answers the current step ("skip" skips it); posts the next one
    POST /api/onboarding {skip_all: true}          ends the intro now
    POST /api/onboarding {reset: true, tz?}        Settings > Run the intro again: starts over from the hello

Steps (STEPS): hello, name, tz, notify, faceid, location, google, routine, tour, done.
- name: {name, call?} saved to memory ("Name: ...; call them ...") and as the name on Theta's calls if unset.
- tz: {tz} an IANA zone (the phone detects it; the user confirms), saved as the "tz" setting.
- notify / faceid: the app does the work (push subscribe, Settings > Sign-in); the answer says how it went.
- location: {lat, lon}, rounded here to 1 decimal (about 10 km), saved as "loc" for Vantage. Optional.
- google: carries a connect card; "continue" or "skip". It moves on by itself once Google is connected.
- routine: one of ROUTINES (made with routines.create) or "none".

Each Theta text is an assistant message with meta {source: "onboarding", onboarding: <step>, cards: [...]}. The
card {type: "onboarding", step, buttons, input?, answered?} is drawn by web/features/onboarding.js, and its
buttons answer through this route, not through chat, so nothing reaches the model. The user's answer is echoed
as their own text, iMessage-style, and the step's card is marked answered. Setting "onboarding_done" (a time)
means it's finished; while it's missing the app starts or resumes the intro on open.
"""
import re
import threading
import time

from . import db

STATE = "onboarding"
DONE = "onboarding_done"
STEPS = ("hello", "name", "tz", "notify", "faceid", "location", "google", "routine", "tour", "done")

ROUTINES = {
    "morning": {"label": "Morning brief at 7:00", "name": "Morning brief", "when": "every day at 7am",
                "prompt": "Give me a short morning brief: today's calendar, the weather where I am, and anything "
                          "urgent in my inbox. Three to five lines.",
                "echo": "The morning brief, please."},
    "evening": {"label": "Evening wrap-up at 21:00", "name": "Evening wrap-up", "when": "every day at 9pm",
                "prompt": "Wrap up my day: what's left on my plan, tomorrow's first event, and anything I asked you "
                          "to remember. Keep it short.",
                "echo": "The evening wrap-up, please."},
    "weekly": {"label": "Weekly review on Sundays", "name": "Weekly review", "when": "every Sunday at 6pm",
               "prompt": "Weekly review: what's coming up this week, email threads still waiting on me, and loose "
                         "ends from last week.",
               "echo": "The weekly review, please."},
}

_lock = threading.Lock()


# ---------------------------------------------------------------- state

def _fresh(now=None):
    return {"step": STEPS[0], "answers": {}, "skipped": [], "posted": {}, "cards": {}, "started": now or time.time()}


def state():
    s = db.get_setting(STATE)
    if not isinstance(s, dict) or s.get("step") not in STEPS:
        s = _fresh()
    for k, d in (("answers", {}), ("skipped", []), ("posted", {}), ("cards", {})):
        if not isinstance(s.get(k), type(d)):
            s[k] = d
    return s


def done():
    return db.get_setting(DONE) is not None


def public(s=None):
    s = s or state()
    fin = done()
    step = "done" if fin else s["step"]
    return {"needed": not fin, "done": fin, "step": step, "index": STEPS.index(step), "steps": list(STEPS),
            "answers": s["answers"], "skipped": s["skipped"]}


def _save(s):
    db.set_setting(STATE, s)


# ---------------------------------------------------------------- what Theta says

def _name(s):
    a = s["answers"].get("name") or {}
    return a.get("call") or a.get("name") or ""


def _google():
    try:
        from . import google
        return google
    except Exception:  # noqa: BLE001
        return None


def _card(step, buttons, **extra):
    return {"type": "onboarding", "step": step, "buttons": buttons, **extra}


def _btn(label, answer, primary=False, do=None):
    b = {"label": label, "answer": answer}
    if primary:
        b["primary"] = True
    if do:
        b["do"] = do
    return b


SKIP = _btn("Skip", "skip")


def script(step, s):
    """[(text, cards)] Theta sends for a step."""
    who = _name(s)
    if step == "hello":
        return [("Hi, I'm Theta. I keep track of your day, look things up, draft emails for your OK, set "
                 "reminders, and text you first when something matters.", []),
                ("Let's get you set up. It takes about a minute, one thing at a time, and you can skip anything.",
                 [_card("hello", [_btn("Let's go", "go", True), _btn("Skip the intro", "skip_all")])])]
    if step == "name":
        return [("First, what's your name, and what should I call you?",
                 [_card("name", [_btn("Save", "save", True), SKIP], kind="name",
                        fields=[{"key": "name", "label": "Your name", "placeholder": "Sam Rivera"},
                                {"key": "call", "label": "Call me", "placeholder": "Sam (optional)"}])])]
    if step == "tz":
        return [((f"Nice to meet you, {who}. " if who else "") + "Which time zone are you in? Reminders and briefs "
                 "follow it.", [_card("tz", [_btn("That's right", "confirm", True, do="tz"),
                                             _btn("Pick another", "pick", do="tz-pick"), SKIP], kind="tz")])]
    if step == "notify":
        return [("Want a notification when I text you first? I only do it for things that matter: reminders, "
                 "alerts near you and your briefs. Quiet hours are on from 22:00 to 7:00.",
                 [_card("notify", [_btn("Turn on notifications", "on", True, do="push"), _btn("Not now", "skip")],
                        kind="notify", icon="bell")])]
    if step == "faceid":
        return [("You can sign in with Face ID instead of typing your key. Your face never leaves the phone; I "
                 "only check a signature.",
                 [_card("faceid", [_btn("Set up Face ID", "opened", True, do="faceid"), _btn("Later", "skip")],
                        kind="faceid", icon="face")])]
    if step == "location":
        return [("For alerts near you (quakes, storms, official warnings from Vantage), I can use your rough "
                 "location, rounded to about 10 km. This one's optional.",
                 [_card("location", [_btn("Share rough location", "share", True, do="location"),
                                     _btn("No thanks", "skip")], kind="location", icon="pin")])]
    if step == "google":
        g = _google()
        if g and g.connected():
            acct = g.account()
            return [(f"Google is already connected{' as ' + acct if acct else ''}, so I can check your calendar, "
                     "find emails and files, and draft replies for your OK.",
                     [_card("google", [_btn("Continue", "continue", True)])])]
        try:
            from . import cards
            conn = [cards.connect("google")]
        except Exception:  # noqa: BLE001
            conn = []
        return [("Connect Google and I can check your calendar, find emails and files, and draft replies for your "
                 "OK. Nothing is ever sent without your tap.",
                 conn + [_card("google", [_btn("Continue", "continue"), _btn("Skip for now", "skip")])])]
    if step == "routine":
        return [("Pick a first routine. I'll set it up now; you can change or delete it any time.",
                 [_card("routine", [_btn(r["label"], rid) for rid, r in ROUTINES.items()] + [_btn("None for now", "skip")],
                        kind="chips")])]
    if step == "tour":
        return [("Three small things before you go:",
                 [_card("tour", [_btn("Got it", "ok", True)], kind="tour", tips=[
                     {"icon": "hold", "title": "Long-press a message",
                      "text": "Copy it, like or dislike it, edit what you said, or see which model answered."},
                     {"icon": "react", "title": "React like a text",
                      "text": "Double-tap or long-press a reply to send a heart or a haha. I react too, sometimes."},
                     {"icon": "clock", "title": "“Took 6s · read 3 emails”",
                      "text": "The line under a reply says what I actually did. Tap it to see the steps."}])])]
    if step == "done":
        return [(f"You're set{', ' + who if who else ''}. Ask me anything, or just say hi. You can run this intro "
                 "again from Settings.", [])]
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


def _mark(s, step, label):
    """Mark the step's card answered (the buttons show what was picked, after a reload too)."""
    mid = s["cards"].get(step)
    m = db.get_message(mid) if mid else None
    if not m:
        return
    cards = []
    for c in (m.get("meta") or {}).get("cards") or []:
        if isinstance(c, dict) and c.get("type") == "onboarding":
            c = dict(c, answered=label)
        cards.append(c)
    db.update_message(mid, meta={"cards": cards})


# ---------------------------------------------------------------- answers

class Bad(ValueError):
    """An answer that can't be used; the message says why."""


def _tz_ok(tz):
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(str(tz))
        return "/" in str(tz) or str(tz) == "UTC"
    except Exception:  # noqa: BLE001
        return False


def _city(tz):
    return str(tz).split("/")[-1].replace("_", " ")


def apply(step, answer, s, now=None):
    """Do what the answer asks. Returns (echo text for the user's side, short ack from Theta or "")."""
    if step == "hello":
        return "Let's go.", ""
    if step == "name":
        a = answer if isinstance(answer, dict) else {"name": answer}
        name = re.sub(r"\s+", " ", str(a.get("name") or "")).strip()[:60]
        call = re.sub(r"\s+", " ", str(a.get("call") or "")).strip()[:40]
        if not name and not call:
            raise Bad("type your name, or tap Skip")
        name = name or call
        fact = f"Name: {name}" + (f"; call them {call}" if call and call != name else "")
        try:
            from . import memory
            cur = memory.block()
            old = next((ln.lstrip("-* ").strip() for ln in cur.split("\n") if ln.lstrip("-* ").startswith("Name:")), None)
            res = memory.edit("replace", fact, old) if old else memory.edit("add", fact)
            if not res.get("ok"):
                raise Bad(res.get("error") or "memory refused that")
        except ImportError:
            pass
        if not db.get_setting("call_name"):
            db.set_setting("call_name", name)
        s["answers"]["name"] = {"name": name, "call": call}
        return (f"I'm {name}." + (f" Call me {call}." if call and call != name else "")), ""
    if step == "tz":
        tz = str((answer or {}).get("tz") if isinstance(answer, dict) else answer or "").strip()
        if not _tz_ok(tz):
            raise Bad("that isn't a time zone I know; pick one from the list")
        db.set_setting("tz", tz)
        s["answers"]["tz"] = tz
        return f"{_city(tz)} time ({tz}).", f"Got it, times are in {_city(tz)} time now."
    if step == "notify":
        ok = answer in ("on", True, "yes")
        s["answers"]["notify"] = "on" if ok else str(answer or "off")[:20]
        if ok:
            return "Turn them on.", "Notifications are on. I'll keep them for things that matter."
        return "Not now.", "No notifications for now; you can turn them on in Settings."
    if step == "faceid":
        s["answers"]["faceid"] = str(answer or "opened")[:20]
        return "Let me set up Face ID.", ""
    if step == "location":
        a = answer if isinstance(answer, dict) else {}
        try:
            lat, lon = float(a["lat"]), float(a["lon"])
        except (TypeError, KeyError, ValueError):
            raise Bad("location needs {lat, lon}, or tap No thanks") from None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise Bad("that location is out of range")
        loc = {"lat": round(lat, 1), "lon": round(lon, 1)}  # about 10 km: Theta never keeps the exact spot
        db.set_setting("loc", loc)
        s["answers"]["location"] = True
        return "Share my rough location.", "Saved, rounded to about 10 km. I'll only use it for alerts near you."
    if step == "google":
        g = _google()
        ok = bool(g and g.connected())
        s["answers"]["google"] = "connected" if ok else "later"
        return ("Done." if ok else "I'll do it later."), ("" if ok else "No problem. Connect apps in the ... menu has it.")
    if step == "routine":
        r = ROUTINES.get(str(answer))
        if r is None:
            raise Bad(f"pick one of {', '.join(ROUTINES)}, or skip")
        try:
            from . import routines
            made = routines.create(r["name"], r["prompt"], r["when"], now=now)
            s["answers"]["routine"] = {"id": made.get("id"), "kind": answer}
            return r["echo"], f"Done: {r['name']}, {made.get('when_words') or r['when']}. It's in Routines."
        except Exception as e:  # noqa: BLE001  say so plainly; never pretend it was made
            s["answers"]["routine"] = {"error": str(e)[:120]}
            return r["echo"], f"I couldn't set that up ({str(e)[:100]}). You can ask me for it any time."
    if step == "tour":
        return "Got it.", ""
    return "", ""


def _advance(s, now, out):
    i = STEPS.index(s["step"]) + 1
    if i < len(STEPS):
        s["step"] = STEPS[i]
        out += _post(s["step"], s)
        if s["step"] == "done":
            db.set_setting(DONE, now)


def answer(step, ans, now=None):
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
        if not s["posted"].get(step):  # answered before its texts went out (shouldn't happen): post them first
            out += _post(step, s)
        if ans == "skip" or ans is None:
            if step not in s["skipped"]:
                s["skipped"].append(step)
            echo, ack = "Skip.", ""
        else:
            echo, ack = apply(step, ans, s, now)
        _mark(s, step, echo or "Skip.")
        if echo:
            out.append(db.add_message("theta", "user", echo, {"source": "onboarding", "onboarding": step}))
        if ack:
            out.append(db.add_message("theta", "assistant", ack, {"source": "onboarding", "onboarding": step,
                                                                  "ack": True}))
        _advance(s, now, out)
        _save(s)
        return public(s), out


def start(tz=None, now=None):
    """Post the current step's texts if they haven't gone out; returns (public state, new messages).
    `tz` (the phone's zone) is accepted for later use; the tz step's card shows the phone's zone itself."""
    now = now or time.time()
    with _lock:
        if done():
            return public(), []
        s = state()
        first = not s["posted"]
        out = []
        if not s["posted"].get(s["step"]):
            out += _post(s["step"], s, first=first)
        _save(s)
    if s["step"] == "google":  # came back from Google's sign-in: move on by itself
        g = _google()
        if g and g.connected():
            st, more = answer("google", "continue", now)
            return st, out + more
    return public(s), out


def skip_all(now=None):
    now = now or time.time()
    with _lock:
        s = state()
        if done():
            return public(s), []
        if s["cards"].get(s["step"]):
            _mark(s, s["step"], "Skip the intro.")
        out = [db.add_message("theta", "user", "Skip the intro.", {"source": "onboarding", "onboarding": s["step"]}),
               db.add_message("theta", "assistant", "No problem. Ask me anything, or just say hi. You can run the "
                              "intro any time from Settings.", {"source": "onboarding", "onboarding": "done"})]
        s["skipped"].append("all")
        s["step"] = "done"
        _save(s)
        db.set_setting(DONE, now)
        return public(s), out


def reset(tz=None, now=None):
    """Start over (Settings > Run the intro again). Earlier answers stay saved where they went (memory, tz...)."""
    with _lock:
        _save(_fresh(now))
        db.set_setting(DONE, None)  # done() means "set and not null"
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
        elif body.get("skip_all"):
            st, msgs = skip_all()
        elif body.get("start"):
            st, msgs = start(tz)
        elif body.get("step"):
            st, msgs = answer(str(body["step"]), body.get("answer"))
        else:
            raise HTTPError(400, "send {start: true}, {step, answer}, {skip_all: true} or {reset: true}")
    except Bad as e:
        raise HTTPError(400, str(e)) from None
    return respond_json(start_response, dict(st, messages=msgs))


ROUTES = {"/api/onboarding": route}


def context(bot, now):
    """While the intro runs, tell the model, so a typed answer ('I'm Sam') is handled naturally."""
    if done() or not state()["posted"]:
        return ""
    return (f"Onboarding: the in-chat intro is on step {state()['step']!r}. If the user answers it by typing "
            "(their name, a time zone), help them normally; the intro's buttons do the setup.")
