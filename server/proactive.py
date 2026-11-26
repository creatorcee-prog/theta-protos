"""Theta texts first. `run(now)` runs every 5 minutes (app.py's ticker, or a systemd timer) and returns the
messages it sent.

Candidates:
  - Vantage events (vantage.py). near you: Red (4) wakes you, Orange (3) waits for quiet hours to end.
    world: each kind at most once a day, never wakes you. The noisy group is never texted. Rumors never get here.
  - The morning brief (7:00) and the evening brief (18:00) in your time zone: one short line, "all quiet" or what
    moved. Phrased by the quick model in Theta's voice when models/persona are there; a plain template otherwise.

Each one that passes becomes db.add_message("theta", "assistant", text, {"proactive": True, "source", "level"}) and
is pushed as push.notify("Theta", body, "/?m=<id>", urgent=level == 4).

Rules:
  - each event goes out once (db.seen / db.mark);
  - quiet hours (settings "quiet"): everything but Red waits, unmarked, and goes out on the first run after;
  - at most "proactive_cap" (default 6) a day, your day; Red is exempt and isn't counted. Over the cap an event
    is dropped (marked), so tomorrow doesn't start with yesterday's backlog;
  - settings "proactive": false turns it all off except Red (what it skips is dropped the same way)."""
import threading
import time

db = push = vantage = None   # server modules, loaded on first use; tests put fakes here
BOT = "theta"
DEFAULT_CAP = 6
SEEN_DAYS = 7
BRIEF_HOURS = {7: "morning", 18: "evening"}
LAST = {}   # what the last run decided, for /api/health-style debugging


def _mods():
    global db, push, vantage
    if db is None:
        from server import db as d
        db = d
    if push is None:
        from server import push as p
        push = p
    if vantage is None:
        from server import vantage as v
        vantage = v


def _local(now):
    return push.user_now(now)


# ---------------------------------------------------------------- how it sounds
def _ago(t, now):
    m = max(0, int((now - t) / 60))
    if m < 2:
        return "just now"
    if m < 60:
        return f"{m} min ago"
    h = round(m / 60)
    return f"{h} h ago"


def _place(title):
    """'M6.3 10 km SW of Hachioji, Japan' -> '10 km SW of Hachioji, Japan'."""
    parts = (title or "").split(" ", 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].startswith("M") else ""


def _sentence(s):
    s = (s or "").strip()
    return s if not s or s[-1] in ".!?" else s + "."


def phrase(e, now):
    """A Vantage event as a text from a friend: the point first, then what it means for you. Never raw data."""
    i, lvl, kind = e.get("info") or {}, e["level"], e["kind"]
    if e["group"] == "near":
        if kind == "quake":
            where = _place(i.get("place", ""))
            head = f"Heads up: M{i['mag']:.1f} quake {i['km']} km from you, {_ago(i['t'], now)}"
            head += f" ({where})." if where else "."
            if lvl == 4:
                return head + " If you felt it, check around you and expect aftershocks."
            return head + " You're fine where you are, but expect aftershocks."
        if kind == "tsunami":
            if lvl == 4:
                return f"Tsunami warning for your coast: {i.get('where', '')}. Get away from the shore and follow local officials."
            return f"Tsunami {i.get('category', 'advisory')} near you: {i.get('where', '')}. Stay off the beach for now and listen to local officials."
        if kind == "official":
            head = f"{'Urgent: ' if lvl == 4 else ''}{i.get('event', 'Official alert')} for your area."
            return (head + " " + _sentence(i.get("headline", ""))).strip()
        if kind == "hazard":
            return f"Heads up: you're inside the danger zone of {i.get('name', 'a storm')} ({i.get('detail', '')}). Worth keeping an eye on it."
        if kind == "military":
            return (f"Military air activity over {i.get('name', 'your region')} is way above normal, and several outlets "
                    "confirm something's going on. Nothing to do yet, just so you know.")
        if kind == "space":
            return "Big geomagnetic storm going on (Kp 7+). GPS and power can act up for a while."
    else:
        if kind == "major" and "story" in i:
            return f"Big one: {_sentence(i['story'])} {i['outlets']} outlets are carrying it."
        if kind == "major":
            return f"Big quake: {i.get('place', e['title'])}, {_ago(i.get('t', now), now)}. Not near you."
        if kind == "region":
            return f"Military air activity over {i.get('name', 'a region')} is far above normal today. Far from you, just so you know."
        if kind == "tsunami":
            return f"Tsunami warning out: {i.get('where', '')}."
        if kind == "market":
            return f"Markets are spooked: {i.get('label', 'a fear gauge')} is up {i.get('d1', 0):.0f}% today."
    return e["body"]


def short(text, n=180):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


# ---------------------------------------------------------------- the brief
def brief_slot(now):
    """'YYYY-MM-DD morning' at 7:00-7:59 and 'YYYY-MM-DD evening' at 18:00-18:59, your time zone; else None."""
    t = _local(now)
    part = BRIEF_HOURS.get(t.hour)
    return f"{t.date()} {part}" if part else None


def _moved(s, evs):
    """Short labels for what moved: what's near you first, then the world."""
    out = []
    for e in sorted(evs, key=lambda e: (e["group"] != "near", -e["level"])):
        if e["group"] == "noisy":
            continue
        i = e.get("info") or {}
        if e["kind"] == "quake" or (e["kind"] == "major" and "mag" in i):
            label = f"M{i['mag']:.1f} quake" + (f" {i['km']} km from you" if "km" in i else f" {_place(i.get('place', '')) or ''}".rstrip())
        elif e["kind"] == "major":
            label = i.get("story") or e["title"]
        elif e["kind"] == "market":
            label = f"{i.get('label')} up {i.get('d1', 0):.0f}%"
        elif e["kind"] in ("region", "military"):
            label = f"military air activity over {i.get('name')}"
        else:
            label = e["title"]
        label = label.strip()
        if label and label not in out:
            out.append(label)
    return out[:3]


def brief_text(part, s, evs):
    """The plain brief: one line, 'all quiet' or what moved."""
    hi = "Morning" if part == "morning" else "Evening"
    moved = _moved(s, evs)
    level = ((s or {}).get("world") or {}).get("level", "green")
    if not moved:
        return f"{hi}. All quiet: nothing moved outside its normal range." if level == "green" else \
            f"{hi}. Nothing near you. The world's a bit busier than usual, but nothing you need to do."
    near = any(e["group"] == "near" for e in evs)
    tail = "Worth keeping an eye on what's near you." if near else "None of it changes your day."
    n = len(moved)
    return f"{hi}. {n} thing{'s' if n > 1 else ''} moved: {'; '.join(moved)}. {tail}"


def voice(plain, now=None):
    """The brief in Theta's voice via the quick model; the plain template when there is no model or it fails."""
    try:
        from server import models, persona, router
        cands = router.candidates("quick")
        if not cands:
            return plain
        provider, model = cands[0]
        msgs = [{"role": "system", "content": persona.system_prompt(BOT, now)},
                {"role": "user", "content": "You're texting them first, unprompted, with your daily brief. Rewrite this "
                 "as ONE short text (under 35 words), friendly, same facts, add nothing, no greeting beyond the first "
                 "word, no lists, no emoji:\n\n" + plain}]
        out = persona.clean(models.complete(provider, model, msgs, max_tokens=120) or "").strip().strip('"')
        return out if 8 <= len(out) <= 300 else plain
    except Exception:  # noqa: BLE001  no models yet, no key, a timeout: the template is fine
        return plain


# ---------------------------------------------------------------- the run
def _count(now):
    day = str(_local(now).date())
    c = db.get_setting("proactive_count") or {}
    return day, (c.get("n", 0) if c.get("day") == day else 0)


def _bump(now):
    day, n = _count(now)
    db.set_setting("proactive_count", {"day": day, "n": n + 1})


def candidates(now):
    """Everything that might go out now, Red first: [{key, keys, source, level, text}]. Already-seen ones are left out."""
    loc = db.get_setting("loc")
    loc = loc if isinstance(loc, dict) and "lat" in loc and "lon" in loc else None
    out, state = [], None
    try:
        evs, state, why = vantage.events(now, loc)
    except Exception as e:  # noqa: BLE001  Vantage never breaks the run
        evs, why = [], f"vantage failed: {type(e).__name__}: {e}"[:160]
    LAST["vantage"] = why or "ok"
    utc_day = time.strftime("%Y-%m-%d", time.gmtime(now))
    kinds = set()
    for e in evs:
        if e["group"] not in ("near", "world"):
            continue                                        # the noisy group is never texted
        key = "vantage:" + e["id"]
        if db.seen(key):
            continue
        keys = [key]
        if e["group"] == "world":
            kind_key = f"vantage-kind:{e['kind']}:{utc_day}"   # each world kind once a day
            if db.seen(kind_key) or kind_key in kinds:
                continue
            kinds.add(kind_key)
            keys.append(kind_key)
        out.append({"key": key, "keys": keys, "source": "vantage", "level": e["level"], "text": None, "event": e})
    slot = brief_slot(now)
    if slot and not db.seen("brief:" + slot):
        if state is not None:
            out.append({"key": "brief:" + slot, "keys": ["brief:" + slot], "source": "brief", "level": 0, "text": None,
                        "brief": (slot.split()[-1], state, evs)})
        else:
            LAST["brief"] = "skipped: no Vantage picture, so nothing honest to say"
    out.sort(key=lambda c: -c["level"])
    return out


def _call_about(text):
    """Ring the user about a Red alert near them (server/calls.py checks the setting and Twilio). In the
    background, so the alert itself never waits on a phone call."""
    def go():
        try:
            from . import calls
            calls.call_user_alert(text)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=go, name="red-call", daemon=True).start()


def run(now=None):
    """One round: returns the messages sent (each a Message dict)."""
    _mods()
    now = now or time.time()
    LAST.clear()
    on = db.get_setting("proactive", True) is not False
    try:
        cap = int(db.get_setting("proactive_cap", DEFAULT_CAP))
    except (TypeError, ValueError):
        cap = DEFAULT_CAP
    quiet = push.quiet_now(now)
    sent, held, dropped, pushed = [], 0, 0, 0
    for c in candidates(now):
        red = c["level"] == 4
        if not red and quiet:
            held += 1
            continue                                        # waits for the end of quiet hours (not marked)
        if not red and (not on or _count(now)[1] >= cap):
            for k in c["keys"]:
                db.mark(k, SEEN_DAYS)                       # off or over the cap: dropped, not saved for later
            dropped += 1
            continue
        if c["source"] == "brief":
            part, s, evs = c["brief"]
            text = voice(brief_text(part, s, evs), now)
        else:
            text = phrase(c["event"], now)
        for k in c["keys"]:
            db.mark(k, SEEN_DAYS)                           # marked before the push, so a slow push can't send it twice
        msg = db.add_message(BOT, "assistant", text, {"proactive": True, "source": c["source"], "level": c["level"]})
        try:
            pushed += push.notify("Theta", short(text), f"/?m={msg['id']}", urgent=red)
        except Exception:  # noqa: BLE001  the message is in the inbox either way
            pass
        if red and c["source"] == "vantage" and (c.get("event") or {}).get("group") == "near":
            _call_about(text)                               # a phone call too, if "Call me on Red alerts" is on
        if not red:
            _bump(now)
        sent.append(msg)
    LAST.update(at=now, sent=len(sent), pushed=pushed, held=held, dropped=dropped, quiet=quiet, on=on)
    return sent
