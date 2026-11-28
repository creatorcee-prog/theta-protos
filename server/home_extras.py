"""Home's extras and layout (after the Home Lab, generation 1): what shows under Theta's globe, in what order, and how
Home is laid out.

    extras(now) -> {today, weather, recommended, order, why}     (sent with GET /api/home)
    GET/POST /api/home/layout {layout, size, off}                  the user's choice, the same on every device

Layouts: classic (the feed), dock, bento, sheet, satellites, today. Sizes: s, m, l. `off` lists extras the user
turned off. The extras: calendar, vantage (a greyed button until Vantage is ready), recommended (settings worth
finishing, from the account's real state), today (reminders due today), approvals, chips, found, stories, weather.

The order is personal and comes from the user's own data, most useful first: something waiting for their OK leads;
a busy day brings the calendar up; a new account gets "finish setting up" first and big; bad weather moves weather up;
an extra with nothing in it is hidden. `why` says, in one line, what drove the order.
"""
import time

from . import db

LAYOUTS = ("classic", "dock", "bento", "sheet", "satellites", "today")
SIZES = ("s", "m", "l")
EXTRAS = ("calendar", "vantage", "recommended", "today", "approvals", "chips", "found", "stories", "weather")
WEATHER_EVERY = 1800
_BAD = ("snow", "rain", "storm", "thunder", "sleet", "hail", "freezing", "drizzle", "shower", "fog")


def layout():
    v = db.get_setting("home_layout")
    v = v if isinstance(v, dict) else {}
    return {"layout": v.get("layout") if v.get("layout") in LAYOUTS else "classic",
            "size": v.get("size") if v.get("size") in SIZES else "m",
            "off": [x for x in (v.get("off") or []) if x in EXTRAS]}


def save_layout(body):
    cur = layout()
    if body.get("layout") in LAYOUTS:
        cur["layout"] = body["layout"]
    if body.get("size") in SIZES:
        cur["size"] = body["size"]
    if isinstance(body.get("off"), list):
        cur["off"] = sorted({x for x in body["off"] if x in EXTRAS})
    db.set_setting("home_layout", cur)
    return cur


# ---------------------------------------------------------------- recommended settings (from the real state)

def recommended():
    """{items: [{key, title, sub, action}], done, total}: what's worth finishing, most important first."""
    checks = []
    try:
        from . import account
        st = account.storage()
        checks.append(("storage", st["persistent"], "Keep Theta's memory safe", "It's wiped on each deploy until storage is fixed" if account.developer() else "Whoever runs your Theta can turn this on", "settings:data"))
        p = account.profile()
        checks.append(("profile", bool(p.get("name") and p.get("phone")), "Finish your profile", "Your name and number, so Theta can reach you", "settings:profile"))
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import google
        g, full = bool(google.connected()), bool(google.connected("drive_full"))
    except Exception:  # noqa: BLE001
        g = full = False
    checks.append(("google", g, "Connect Google", "Your calendar and email, here", "settings:connections"))
    checks.append(("backups", full, "Turn on Drive backups", "A copy every 3 hours, loaded back if anything's lost", "settings:connections"))
    checks.append(("push", bool(db.push_subs()), "Let Theta text you", "Reminders and heads-ups on your phone", "settings:notifications"))
    loc = db.get_setting("loc")
    checks.append(("location", isinstance(loc, dict) and loc.get("lat") is not None, "Share your location", "For weather, travel times and Vantage", "settings:general"))
    checks.append(("look", bool(db.get_setting("look")), "Make Theta yours", "A color and a globe you like", "settings:general"))
    items = [{"key": k, "title": t, "sub": s, "action": a} for k, ok, t, s, a in checks if not ok]
    return {"items": items, "done": len(checks) - len(items), "total": len(checks)}


# ---------------------------------------------------------------- today and weather (found in the background)

def today_events():
    v = db.get_setting("home_today")
    return v.get("events") if isinstance(v, dict) and time.strftime("%Y-%m-%d") == v.get("day") else []


def refresh_today(now):
    """Today's events, saved for Home (called from home.tick's background thread)."""
    try:
        import datetime
        from . import gcal, persona
        today = persona.local_now(now).date()
        evs, _ = gcal.events_between(today, today + datetime.timedelta(days=1), now)
        out = []
        for e in evs[:8]:
            ts = 0 if e.get("all_day") else datetime.datetime.fromisoformat(e["start"]).timestamp()
            when = "All day" if e.get("all_day") else persona.local_now(ts).strftime("%-I:%M %p")
            out.append({"title": e.get("title") or "Event", "when": when, "t": ts, "location": e.get("location") or ""})
        db.set_setting("home_today", {"day": time.strftime("%Y-%m-%d"), "events": out})
    except Exception:  # noqa: BLE001  no calendar connected, or it's down
        pass


def weather():
    v = db.get_setting("home_weather")
    return v if isinstance(v, dict) and v.get("temp") is not None else None


def refresh_weather(now):
    loc = db.get_setting("loc")
    if not (isinstance(loc, dict) and loc.get("lat") is not None):
        return
    try:
        from . import cards
        ctx = {}
        cards._t_weather({}, ctx)
        w = next((c for c in ctx.get("cards") or [] if c.get("type") == "weather"), None)
        if w:
            db.set_setting("home_weather", {k: w.get(k) for k in ("temp", "condition", "hi", "lo", "unit")} | {"t": now})
    except Exception:  # noqa: BLE001
        pass


def tick(now):
    import threading
    w = db.get_setting("home_weather") or {}
    if now - float((w if isinstance(w, dict) else {}).get("t") or 0) > WEATHER_EVERY and not _busy.get("w"):
        _busy["w"] = True
        threading.Thread(target=lambda: (refresh_weather(now), _busy.pop("w", None)), name="home-weather", daemon=True).start()


_busy = {}


# ---------------------------------------------------------------- the personal order

def reminders_today(now):
    import datetime
    out = []
    try:
        from . import persona
        end = persona.local_now(now).replace(hour=23, minute=59).timestamp()
        for j in db.jobs("pending", limit=50):
            if j.get("kind") == "remind" and float(j.get("due_t") or 0) <= end:
                when = persona.local_now(float(j["due_t"])).strftime("%-I:%M %p") if float(j["due_t"]) > now else "Due now"
                out.append({"text": (j.get("payload") or {}).get("text") or "Reminder", "when": when, "t": float(j["due_t"])})
    except Exception:  # noqa: BLE001
        pass
    return out[:5]


def order(have, rec, events, weather_, pending):
    """(ordered extras, why). `have`: the extras with something to show."""
    score, why = {}, []
    new = rec["total"] and rec["done"] / rec["total"] < 0.5
    score["approvals"] = 100 if pending else -1
    score["recommended"] = 95 if new else (40 if rec["items"] else -1)
    score["calendar"] = 80 if len(events) >= 2 else 55 if events else 30
    score["today"] = 75
    score["found"] = 60
    score["chips"] = 70 if new else 50
    bad = bool(weather_ and any(b in str(weather_.get("condition") or "").lower() for b in _BAD))
    score["weather"] = 72 if bad else 45
    score["stories"] = 35
    score["vantage"] = 10
    if pending:
        why.append("something is waiting for your OK")
    if new:
        why.append("setting up comes first while you're new")
    elif len(events) >= 2:
        why.append(f"you have {len(events)} events today")
    if bad:
        why.append(f"{weather_['condition'].lower()} today")
    ranked = sorted((k for k in EXTRAS if k in have and score.get(k, 0) >= 0), key=lambda k: -score[k])
    return ranked, ("First: " + "; ".join(why) + ".") if why else "Ordered by what's useful now."


def extras(now=None, stack=None, found_=None, news_=None):
    now = now or time.time()
    rec, events, w = recommended(), today_events(), weather()
    pending = [c for c in (stack or []) if c.get("kind") == "approve"]
    rems = reminders_today(now)
    have = {"calendar", "vantage", "chips", "stories" if news_ else None, "found" if found_ else None,
            "weather" if w else None, "approvals" if pending else None, "today" if (rems or events) else None,
            "recommended" if rec["items"] else None} - {None}
    off = set(layout()["off"])
    ranked, why = order(have - off, rec, events, w, pending)
    return {"today": {"events": events, "reminders": rems}, "weather": w, "recommended": rec, "order": ranked, "why": why}


def layout_route(req, start):
    from .app import HTTPError, respond_json
    if req.method == "POST":
        return respond_json(start, save_layout(req.json() or {}))
    if req.method != "GET":
        raise HTTPError(405, "method not allowed")
    return respond_json(start, layout())


ROUTES = {"/api/home/layout": layout_route}


def context(bot, now):
    return ""
