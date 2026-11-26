"""Cards: typed, structured pieces of a reply (weather, a stock, a link, a place, an event...) that the app draws
as small iOS-style panels under Theta's text. Prose stays the answer; a card shows what reads better as a card.

    show_card {type, card}            (tool, risk "read") validates one card and attaches it to the reply
    validate(type, data) -> card      the cleaned card, or raises tools.ToolError saying how to fix it
    TYPES                             {type: {"doc", "check"}}; the docs are part of show_card's description
    connect(service) -> card          a "connect" card for a service that isn't connected or set up
    connect_card(ctx, service)        the same card, also attached to the turn (ctx["cards"], no repeats)
    from_tool_error(name, text)       a connect card when a tool's error text says it isn't connected, else None
    note_result(ctx, name, ok, text)  from_tool_error + attach; for the agent loop, after every tool result
    POST /api/cards/checklist         {message_id, card, item, done}: ticks an item, saved into that message

How cards travel: a tool appends to ctx["cards"]; app._agent_turn copies them into the reply's meta.cards; the
app renders each with the renderer web/features/cards.js registered for its type (Theta.card). A card is data
only: text, numbers, https links and same-origin image paths. Nothing in it is HTML.

Connect cards are how Theta stays honest about missing setup. Every place that refuses because something isn't
connected (Google, Twilio, Gemini, Tavily, GIPHY, the browser) attaches one, through connect_card() where the
error is raised, and tools.execute() runs from_tool_error() on every error as a fallback, so the user always
gets a Connect button or the exact setup steps, and the model is told to say plainly that nothing happened.
"""
import contextvars
import datetime
import json
import os
import re
import secrets
import urllib.parse

from . import db

MAX_PER_TURN = 6
_current = contextvars.ContextVar("theta_card_ctx", default=None)


def _err(msg):
    from .tools import ToolError
    return ToolError(msg)


# ---------------------------------------------------------------- small cleaners

def _s(v, n=200):
    """One line of plain text, at most n chars ('' for None)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        v = "yes" if v else "no"
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _p(v, n=600):
    """A short paragraph: newlines kept (at most 2 in a row), other whitespace squeezed."""
    if v is None:
        return ""
    s = re.sub(r"[ \t\r\f\v]+", " ", str(v))
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _req(d, key, n=200, what=None):
    s = _s(d.get(key), n)
    if not s:
        raise _err(f"{key} is required" + (f": {what}" if what else ""))
    return s


def _num(d, key, required=False, lo=None, hi=None):
    v = d.get(key)
    if v is None or v == "":
        if required:
            raise _err(f"{key} is required (a number)")
        return None
    if isinstance(v, bool):
        raise _err(f"{key} must be a number")
    if isinstance(v, str):
        try:
            v = float(v.replace(",", "").replace("%", "").replace("$", "").strip())
        except ValueError:
            raise _err(f"{key} must be a number, got {v[:30]!r}") from None
    if not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        raise _err(f"{key} must be a number")
    if lo is not None and v < lo or hi is not None and v > hi:
        raise _err(f"{key} must be between {lo} and {hi}")
    return int(v) if float(v).is_integer() and abs(v) < 1e15 else round(float(v), 6)


def _list(d, key, lo=0, hi=50, required=False):
    v = d.get(key)
    if v is None:
        if required or lo:
            raise _err(f"{key} is required (a list)")
        return []
    if not isinstance(v, list):
        raise _err(f"{key} must be a list")
    if len(v) < lo:
        raise _err(f"{key} needs at least {lo} entries")
    return v[:hi]


def https_url(v, required=False, key="url"):
    """An https:// URL with a host, or '' (raises if required or if it isn't https)."""
    s = str(v or "").strip()
    if not s:
        if required:
            raise _err(f"{key} is required (an https:// link)")
        return ""
    try:
        u = urllib.parse.urlsplit(s)
    except ValueError:
        raise _err(f"{key} isn't a link") from None
    if u.scheme != "https" or not u.hostname or u.username or u.password or len(s) > 2000:
        raise _err(f"{key} must be an https:// link (got {s[:60]!r}); other links aren't shown")
    return s


_SAME = re.compile(r"^/api/(media|uploads)/[A-Za-z0-9._-]{1,80}$")
_DATA_IMG = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$")


def image_src(v):
    """A picture the app's CSP allows: a same-origin /api/media or /api/uploads path, or a data:image URL.
    Anything else (another site's image) is dropped, because the page couldn't load it anyway."""
    s = str(v or "").strip()
    if _SAME.match(s) and ".." not in s:
        return s
    if len(s) <= 300_000 and _DATA_IMG.match(s):
        return s
    return ""


def _site(url):
    try:
        h = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def maps_url(query):
    return "https://www.google.com/maps/dir/?api=1&destination=" + urllib.parse.quote(query)


# ---------------------------------------------------------------- the types

def _weather(d):
    unit = _s(d.get("unit") or "F", 2).upper().lstrip("°")
    if unit not in ("F", "C"):
        raise _err("unit must be F or C")
    hourly = []
    for i, h in enumerate(_list(d, "hourly", hi=8)):
        if not isinstance(h, dict):
            raise _err(f"hourly[{i}] must be an object like {{\"time\": \"3 PM\", \"temp\": 41, \"condition\": \"cloudy\"}}")
        hourly.append({"time": _req(h, "time", 12, "a short label like '3 PM'"), "temp": _num(h, "temp", True, -100, 150),
                       "condition": _s(h.get("condition"), 40)})
    return {"place": _req(d, "place", 80), "temp": _num(d, "temp", True, -100, 150),
            "condition": _s(d.get("condition"), 60), "hi": _num(d, "hi", lo=-100, hi=150),
            "lo": _num(d, "lo", lo=-100, hi=150), "unit": unit, "hourly": hourly, "as_of": _s(d.get("as_of"), 40)}


_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=:]{0,14}$")


def _stock(d):
    sym = _s(d.get("symbol"), 16).upper()
    if not _SYMBOL.match(sym):
        raise _err("symbol must be a ticker like AAPL, BRK.B or ^GSPC")
    pts = []
    for i, p in enumerate(_list(d, "points", hi=200)):
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            raise _err(f"points[{i}] must be a number (prices, oldest first)")
        pts.append(round(float(p), 6))
    if len(pts) == 1:
        pts = []
    return {"symbol": sym, "name": _s(d.get("name"), 60), "price": _num(d, "price", True),
            "change_pct": _num(d, "change_pct", lo=-100, hi=10000), "change": _num(d, "change"),
            "currency": _s(d.get("currency") or "USD", 6).upper(), "points": pts, "as_of": _s(d.get("as_of"), 40)}


def _link(d):
    url = https_url(d.get("url"), required=True)
    return {"url": url, "title": _req(d, "title", 140), "site": _s(d.get("site"), 60) or _site(url),
            "summary": _p(d.get("summary"), 300), "image": image_src(d.get("image"))}


def _place(d):
    name = _req(d, "name", 100)
    addr = _s(d.get("address"), 200)
    lat, lon = _num(d, "lat", lo=-90, hi=90), _num(d, "lon", lo=-180, hi=180)
    dest = f"{lat},{lon}" if lat is not None and lon is not None else (f"{name}, {addr}" if addr else name)
    return {"name": name, "address": addr, "category": _s(d.get("category"), 40), "rating": _num(d, "rating", lo=0, hi=5),
            "hours": _s(d.get("hours"), 80), "phone": _s(d.get("phone"), 30), "url": https_url(d.get("url")),
            "directions": maps_url(dest)}


def _when(s, key):
    s = _s(s, 40)
    if not s:
        return None
    try:
        if "T" in s or " " in s.strip():
            return datetime.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
        return datetime.date.fromisoformat(s)
    except ValueError:
        raise _err(f"{key}={s!r} isn't ISO 8601; use 2026-11-27T15:00:00-07:00, or 2026-11-27 for all day") from None


def _event(d):
    title = _req(d, "title", 140)
    st, en = _when(d.get("start"), "start"), _when(d.get("end"), "end")
    if st is None:
        raise _err("start is required, e.g. start='2026-11-27T15:00:00-07:00'")
    loc = _s(d.get("location"), 200)
    add = {"title": title, "date": st.date().isoformat() if isinstance(st, datetime.datetime) else st.isoformat()}
    if loc:
        add["location"] = loc
    if isinstance(st, datetime.datetime):
        if st.tzinfo is not None:
            from . import tools
            st = st.astimezone(tools.local_time(st.timestamp()).tzinfo)
            if isinstance(en, datetime.datetime) and en.tzinfo is not None:
                en = en.astimezone(st.tzinfo)
        add["date"] = st.date().isoformat()
        add["time"] = st.strftime("%H:%M")
        mins = 60
        if isinstance(en, datetime.datetime):
            try:
                mins = int((en - st).total_seconds() // 60)
            except TypeError:
                mins = 60
            if mins < 5:
                raise _err("end must be after start")
        add["duration"] = max(5, min(1440, mins))
    return {"title": title, "start": st.isoformat(), "end": en.isoformat() if en else "",
            "all_day": not isinstance(st, datetime.datetime), "location": loc, "calendar": _s(d.get("calendar"), 60),
            "url": https_url(d.get("url")), "add": add}


def _email(d):
    return {"from": _s(d.get("from"), 120), "to": _s(d.get("to"), 160), "subject": _req(d, "subject", 160),
            "snippet": _p(d.get("snippet"), 280), "date": _s(d.get("date"), 40), "id": _s(d.get("id"), 64),
            "url": https_url(d.get("url")), "unread": bool(d.get("unread"))}


def _checklist(d):
    items = []
    for i, it in enumerate(_list(d, "items", lo=1, hi=30)):
        if isinstance(it, str):
            it = {"text": it}
        if not isinstance(it, dict):
            raise _err(f"items[{i}] must be {{\"text\": \"...\", \"done\": false}}")
        items.append({"text": _req(it, "text", 160), "done": bool(it.get("done"))})
    cid = _s(d.get("id"), 40)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", cid or ""):
        cid = "cl_" + secrets.token_hex(5)
    return {"id": cid, "title": _s(d.get("title"), 100), "items": items}


def _cell(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return v
    return _s(v, 120)


def _table(d):
    cols = [_s(c, 40) for c in _list(d, "columns", lo=1, hi=8)]
    if not all(cols[1:]) or (len(cols) == 1 and not cols[0]):  # the corner (first) header may be blank
        raise _err("every column needs a name")
    rows = []
    for i, r in enumerate(_list(d, "rows", lo=1, hi=60)):
        if not isinstance(r, list):
            raise _err(f"rows[{i}] must be a list of cells, one per column")
        r = [_cell(c) for c in r[:len(cols)]]
        rows.append(r + [""] * (len(cols) - len(r)))
    return {"title": _s(d.get("title"), 100), "columns": cols, "rows": rows, "caption": _s(d.get("caption"), 200)}


STEP_STATES = ("done", "active", "pending", "failed", "skipped")


def _steps(d):
    steps = []
    for i, s in enumerate(_list(d, "steps", lo=1, hi=12)):
        if isinstance(s, str):
            s = {"text": s}
        if not isinstance(s, dict):
            raise _err(f"steps[{i}] must be {{\"text\": \"...\", \"state\": \"done\"}}")
        st = _s(s.get("state") or "pending", 10).lower()
        if st not in STEP_STATES:
            raise _err(f"steps[{i}].state must be one of {', '.join(STEP_STATES)}")
        steps.append({"text": _req(s, "text", 140), "state": st, "detail": _s(s.get("detail"), 140)})
    return {"title": _req(d, "title", 100), "steps": steps, "note": _s(d.get("note"), 200)}


def _choice(d):
    opts = []
    for i, o in enumerate(_list(d, "options", lo=2, hi=6)):
        if isinstance(o, str):
            o = {"label": o}
        if not isinstance(o, dict):
            raise _err(f"options[{i}] must be {{\"label\": \"...\", \"value\": \"what to send\"}}")
        label = _req(o, "label", 60)
        opts.append({"label": label, "value": _s(o.get("value"), 300) or label, "detail": _s(o.get("detail"), 100)})
    return {"question": _req(d, "question", 200), "options": opts}


def _quote(d):
    return {"text": _p(d.get("text"), 800) or _req(d, "text"), "source": _s(d.get("source"), 120),
            "url": https_url(d.get("url"))}


def _gallery(d):
    imgs = []
    for i, im in enumerate(_list(d, "images", lo=1, hi=12)):
        if isinstance(im, str):
            im = {"src": im}
        if not isinstance(im, dict):
            raise _err(f"images[{i}] must be {{\"src\": \"/api/media/<id>.png\"}}")
        src = im.get("src")
        if not src and im.get("id"):
            iid = _s(im["id"], 80)
            src = f"/api/media/{iid}.png" if re.fullmatch(r"[0-9a-f]{32}", iid) else f"/api/uploads/{iid}"
        src = image_src(src)
        if not src or src.startswith("data:"):
            raise _err(f"images[{i}] must be a /api/media/<id>.png or /api/uploads/<id> path (other images "
                       "can't be shown)")
        imgs.append({"src": src, "alt": _s(im.get("alt"), 120)})
    return {"title": _s(d.get("title"), 100), "images": imgs}


def _file(d):
    url = str(d.get("url") or "").strip()
    if url.startswith("/"):
        if not re.fullmatch(r"/api/[A-Za-z0-9/._?=&-]{1,300}", url) or ".." in url:
            raise _err("url must be https:// or a same-site /api/ path")
    else:
        url = https_url(url, key="url")
    return {"name": _req(d, "name", 140), "size": _num(d, "size", lo=0), "kind": _s(d.get("kind"), 30),
            "url": url, "note": _s(d.get("note"), 140)}


def _connect_v(d):
    svc = _s(d.get("service"), 30).lower()
    if svc not in SERVICES:
        raise _err(f"service must be one of {', '.join(SERVICES)}")
    return connect(svc)


TYPES = {
    "weather": {"check": _weather, "doc": (
        "weather: the forecast for one place. Fields: place (required), temp (required, now), condition "
        "('sunny', 'partly cloudy', 'rain', 'snow', 'storm', 'fog', 'wind'...), hi, lo, unit ('F' default, or 'C'), "
        "hourly (up to 8 of {time: '3 PM', temp, condition}), as_of. Numbers only from a real source "
        "(web_search), never guessed.")},
    "stock": {"check": _stock, "doc": (
        "stock: one ticker. Fields: symbol (required, e.g. AAPL), name, price (required), change_pct (today's "
        "% change, e.g. -1.2), change (in currency), currency ('USD' default), points (recent prices, oldest "
        "first, for the sparkline; leave out if you don't have them), as_of.")},
    "link": {"check": _link, "doc": (
        "link: a page worth opening. Fields: url (required, https only), title (required), site, summary "
        "(one or two sentences), image (only a /api/media/... or /api/uploads/... path or a data: URL; other "
        "sites' images can't load).")},
    "place": {"check": _place, "doc": (
        "place: a restaurant, shop or address. Fields: name (required), address, category, rating (0-5), hours, "
        "phone, url (https), lat/lon. The app adds a Directions button (a maps link); there's no map.")},
    "event": {"check": _event, "doc": (
        "event: something on a calendar, or one you suggest adding. Fields: title (required), start (required, "
        "ISO with offset, or a date for all day), end, location, calendar (its name), url. The app shows 'Add "
        "to calendar', which adds it only when the user taps it.")},
    "email": {"check": _email, "doc": (
        "email: one message, e.g. from gmail_search. Fields: subject (required), from, to, snippet, date, id "
        "(the Gmail message id), url (https), unread. The app shows Open and Reply; Reply asks you in chat.")},
    "checklist": {"check": _checklist, "doc": (
        "checklist: items the user ticks off in the app (saved). Fields: title, items (required, up to 30 of "
        "{text, done}). For a plan you track across turns, use plan_update as well.")},
    "table": {"check": _table, "doc": (
        "table: a small comparison. Fields: columns (required, up to 8 names), rows (required, lists of cells "
        "in column order, up to 60), title, caption. Scrolls sideways on a phone.")},
    "steps": {"check": _steps, "doc": (
        "steps: a task's progress. Fields: title (required), steps (required, up to 12 of {text, state, "
        "detail}; state is done, active, pending, failed or skipped), note. Show only what really happened.")},
    "choice": {"check": _choice, "doc": (
        "choice: a question with 2-6 options the user taps; the tap sends that option's value (or label) to "
        "you as their message. Fields: question (required), options (required, {label, value, detail}).")},
    "quote": {"check": _quote, "doc": "quote: a passage worth setting apart. Fields: text (required), source, url (https)."},
    "gallery": {"check": _gallery, "doc": (
        "gallery: pictures Theta made or the user sent. Fields: images (required, up to 12 of {src: "
        "'/api/media/<id>.png' or '/api/uploads/<id>', alt}), title.")},
    "file": {"check": _file, "doc": (
        "file: a document to open. Fields: name (required), size (bytes), kind ('PDF', 'Google Doc'...), url "
        "(https, or a same-site /api/ path), note.")},
    "connect": {"check": _connect_v, "doc": (
        "connect: a service that isn't connected or set up. Fields: service (required: google, twilio, gemini, "
        "tavily, giphy or browser). The app adds the Connect button or the setup steps. Tools that refuse "
        "because of missing setup attach this card themselves.")},
}


def validate(kind, data):
    """The cleaned card {type, ...} for `kind`, or raises ToolError with how to fix it."""
    kind = str(kind or "").strip().lower()
    spec = TYPES.get(kind)
    if spec is None:
        raise _err(f"type must be one of {', '.join(TYPES)}")
    if not isinstance(data, dict):
        raise _err("card must be an object with that type's fields")
    out = spec["check"](data)
    out = {"type": kind, **{k: v for k, v in out.items() if v not in (None, "", []) and k != "type"}}
    if len(json.dumps(out)) > 400_000:
        raise _err("that card is too big; send fewer items")
    return out


def attach(ctx, card):
    """Add a card to this turn (ctx["cards"]), skipping an exact repeat and a second connect card for the same
    service. Returns True when it was added."""
    if not isinstance(ctx, dict) or not isinstance(card, dict):
        return False
    lst = ctx.get("cards")
    if not isinstance(lst, list):
        lst = ctx["cards"] = []
    for c in lst:
        if c == card or (card.get("type") == "connect" and c.get("type") == "connect"
                         and c.get("service") == card.get("service")):
            return False
    if len(lst) >= MAX_PER_TURN:
        return False
    lst.append(card)
    return True


def _show_card(args, ctx):
    card = validate(args.get("type"), args.get("card") or {})
    if card["type"] == "connect":
        attach(ctx, card)
        return (f"Connect card for {card['title']} attached. Say plainly that {card['name']} isn't set up, so "
                "nothing was done, and that the card shows how to fix it.")
    if not attach(ctx, card):
        return f"Not attached: that card is already on this reply, or the reply has {MAX_PER_TURN} cards."
    return (f"The {card['type']} card is attached below your reply. Keep your text short and don't repeat "
            "every field it shows.")


def _tool_doc():
    return ("Attach a card to your reply: a small panel the app draws under your text, for things that read "
            "better as a card than as prose (a forecast, a ticker, a place with directions, an event to add, a "
            "list to tick, a comparison table, a link). Your text still answers; the card supports it. Use "
            "it only with facts you got from a tool or the user in this conversation: never invent numbers, "
            "links or events to fill one. At most a few per reply. Pass type and card (that type's fields):\n"
            + "\n".join("- " + v["doc"] for v in TYPES.values())
            + "\nExample: {\"type\": \"weather\", \"card\": {\"place\": \"Denver\", \"temp\": 31, \"condition\": "
            "\"sunny\", \"hi\": 44, \"lo\": 22}}.\nWhen a tool says something isn't connected or set up, the app "
            "already shows a connect card: tell the user plainly that it isn't set up and nothing was done. Never "
            "say it worked.")


TOOLS = [
    {"name": "weather", "risk": "read", "run": lambda a, c: _t_weather(a, c),
     "description": ("Current weather and the next few hours for a place, from Open-Meteo (no key needed). Use it "
                     "for any weather question instead of web_search. It shows the user a weather card by itself, so "
                     "answer in a sentence and don't list every number. Example: {\"place\": \"Denver\"}; with no "
                     "place it uses the user's shared location."),
     "params": {"type": "object", "properties": {
         "place": {"type": "string", "description": "City, or 'City, State'. Empty means the user's location."},
         "unit": {"type": "string", "enum": ["F", "C"], "description": "Default F."}}, "required": []}},
    {"name": "show_card", "risk": "read", "run": _show_card, "description": _tool_doc(),
     "params": {"type": "object", "properties": {
         "type": {"type": "string", "enum": list(TYPES), "description": "Which card."},
         "card": {"type": "object", "description": "That type's fields (see the list above)."}},
         "required": ["type", "card"]}},
]

RELEVANT = (r"\b(weather|forecast|temperature|stocks?|ticker|share price|directions|address|checklist|"
            r"compare|comparison|table|itinerary|steps|step by step|how (?:do|can|should) i|how to|where is|"
            r"where's|recipe|packing|to-?do list|pros and cons|vs\.?|versus)\b")


# ---------------------------------------------------------------- connect cards

RAILWAY = "In Railway, open your Theta service, then the Variables tab"
DEPLOY = "Railway stages the change: tap Deploy to apply it. Theta restarts in about a minute."

SERVICES = {
    "google": {
        "name": "Google", "letter": "G", "title": "Connect Google",
        "why": "Gmail, Calendar and Drive need your Google sign-in. One sign-in covers all three."},
    "twilio": {
        "name": "Phone calls", "letter": "T", "title": "Set up phone calls",
        "why": "Calls go through Twilio, and this server has no Twilio account yet.",
        "steps": ["Make a Twilio account at twilio.com and buy a number with Voice (Phone Numbers > Manage > Buy a number).",
                  "On a trial account, add your own phone under Phone Numbers > Manage > Verified Caller IDs.",
                  f"{RAILWAY}, and add TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN (Twilio Console home, Account Info) "
                  "and TWILIO_FROM (the number you bought, like +15551234567).",
                  "Also add PROTOS_PUBLIC_URL=https://<your app>.up.railway.app if it isn't there.",
                  DEPLOY, "Then in Theta: Settings > Phone calls, add your number and tap Test call."]},
    "gemini": {
        "name": "Image making", "letter": "I", "title": "Set up image making",
        "why": "Pictures are made with Google's Gemini, and this server has no Gemini key.",
        "steps": ["Get a key at aistudio.google.com (Get API key). Give it a spending limit.",
                  f"{RAILWAY}, and add GEMINI_API_KEY=<your key>.", DEPLOY]},
    "tavily": {
        "name": "Live search", "letter": "S", "title": "Set up live search",
        "why": "Up-to-date answers (news, prices, hours) come from Tavily, and this server has no Tavily key.",
        "steps": ["Make a free account at tavily.com and copy your API key.",
                  f"{RAILWAY}, and add TAVILY_API_KEY=<your key>.", DEPLOY]},
    "giphy": {
        "name": "GIFs", "letter": "G", "title": "Set up GIFs",
        "why": "GIF search comes from GIPHY, and this server has no GIPHY key.",
        "steps": ["Make an app at developers.giphy.com (Create an App > API) and copy its key.",
                  f"{RAILWAY}, and add GIPHY_API_KEY=<your key>.", DEPLOY]},
    "browser": {
        "name": "Web browsing", "letter": "B", "title": "Turn on web browsing",
        "why": "Theta's own browser needs Playwright and Chromium on the server, and they aren't available here.",
        "steps": ["Railway must build the repo's Dockerfile (the deploy log says \"Using detected Dockerfile\"); "
                  "it installs Chromium. If the log says Nixpacks, check the Dockerfile is at the repo's root.",
                  f"{RAILWAY}, and remove THETA_BROWSER=0 if it's there.", DEPLOY,
                  "On your own computer instead: pip install playwright, then python -m playwright install chromium."]},
}

_GOOGLE_SETUP = [
    "In console.cloud.google.com, make a project and enable the Gmail, Calendar, Drive, Docs and Slides APIs.",
    "Under Google Auth Platform, set it to External and Testing, and add your own Google address as a test user.",
    "Clients > Create client > Web application, with the redirect URI "
    "https://<your app>.up.railway.app/api/google/callback. Copy the client ID and secret.",
    f"{RAILWAY}, and add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and PROTOS_PUBLIC_URL=https://<your app>.up.railway.app.",
    DEPLOY, "Then come back here and tap Connect.",
]


def _google_ready():
    return bool((os.environ.get("GOOGLE_CLIENT_ID") or "").strip() and (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip())


def connect(service):
    """The connect card for a service: {type, service, name, letter, title, why, action, steps?}.
    action is a same-site URL that starts the connection (Google: /api/google/start), or "settings" when the
    fix is on the server; then steps says exactly what to set, and where in Railway."""
    svc = str(service or "").lower()
    if svc in ("gmail", "calendar", "drive", "gcal"):
        svc = "google"
    s = SERVICES.get(svc)
    if s is None:
        raise ValueError(f"unknown service {service!r}")
    card = {"type": "connect", "service": svc, "name": s["name"], "letter": s["letter"], "title": s["title"],
            "why": s["why"]}
    if svc == "google":
        if _google_ready():
            card["action"] = "/api/google/start"
        else:
            card.update(action="settings", steps=list(_GOOGLE_SETUP),
                        why="Google sign-in isn't set up on this server yet. It's a one-time setup, about 15 minutes.")
    else:
        card.update(action="settings", steps=list(s["steps"]))
    return card


def connect_card(ctx, service):
    """The connect card for `service`, attached to this turn: to `ctx` when given, else to the tool call that is
    running now (tools.execute sets it). Call it right where the not-connected error is raised. Returns the card."""
    card = connect(service)
    attach(ctx if isinstance(ctx, dict) else _current.get(), card)
    return card


def auto(ctx, kind, data):
    """A card made by code from a tool's own structured result: it appears every time it applies, whatever the
    model decides. Never raises (a card is never worth failing the tool for). Returns the card or None."""
    try:
        card = validate(kind, data)
    except Exception:  # noqa: BLE001
        return None
    attach(ctx if isinstance(ctx, dict) else _current.get(), card)
    return card


_WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "fog", 48: "fog", 51: "light drizzle",
        53: "drizzle", 55: "drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
        67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "showers",
        81: "showers", 82: "heavy showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorm",
        96: "thunderstorm with hail", 99: "thunderstorm with hail"}


def _get_json(url, params, timeout=12):
    import urllib.parse
    import urllib.request
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "theta-protos"})
    import urllib.error
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _err("the weather service is busy right now (HTTP %s); try again in a minute, or use web_search"
                   % e.code) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise _err("couldn't reach the weather service; try again in a minute, or use web_search") from None


def _t_weather(args, ctx):
    """Weather from Open-Meteo (free, no key): now, today's high and low, the next hours. Always shows a card."""
    from . import tools
    place = _s(args.get("place"), 80)
    lat = lon = None
    name = place
    if not place:
        loc = db.get_setting("loc")
        if isinstance(loc, dict) and loc.get("lat") is not None:
            lat, lon, name = loc["lat"], loc["lon"], "Near you"
        else:
            raise _err("say which place, e.g. place='Denver', or share a location in Settings")
    if lat is None:
        g = _get_json("https://geocoding-api.open-meteo.com/v1/search", {"name": place, "count": 1})
        hit = (g.get("results") or [None])[0]
        if not hit:
            raise _err(f"couldn't find a place called {place!r}; try 'City, State'")
        lat, lon = hit["latitude"], hit["longitude"]
        name = ", ".join(x for x in (hit.get("name"), hit.get("admin1")) if x)
    unit = "C" if str(args.get("unit") or "").upper().startswith("C") else "F"
    w = _get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code",
        "hourly": "temperature_2m,weather_code", "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit" if unit == "F" else "celsius", "timezone": "auto", "forecast_days": 2})
    cur, daily, hourly = w.get("current") or {}, w.get("daily") or {}, w.get("hourly") or {}
    now_t = str(cur.get("time") or "")
    hrs = []
    for t, temp, code in zip(hourly.get("time") or [], hourly.get("temperature_2m") or [], hourly.get("weather_code") or []):
        if t > now_t and len(hrs) < 6:
            h = int(t[11:13])
            hrs.append({"time": f"{(h % 12) or 12} {'AM' if h < 12 else 'PM'}", "temp": round(temp),
                        "condition": _WMO.get(code, "")})
    data = {"place": name, "temp": round(cur.get("temperature_2m", 0)), "condition": _WMO.get(cur.get("weather_code"), ""),
            "hi": round((daily.get("temperature_2m_max") or [0])[0]), "lo": round((daily.get("temperature_2m_min") or [0])[0]),
            "unit": unit, "hourly": hrs, "as_of": "now"}
    auto(ctx, "weather", data)
    nxt = ", ".join(f"{h['time']} {h['temp']}°" for h in hrs[:4])
    return (f"{name}: {data['temp']}°{unit} and {data['condition']} now; high {data['hi']}°, low {data['lo']}°. "
            f"Next hours: {nxt}. (Source: Open-Meteo.) A weather card is attached; don't repeat every number.")


# ---------------------------------------------------------------- structure in a reply -> cards (code, every time)

_NUM = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+?)\s*$")
_BUL = re.compile(r"^\s*[-*•]\s+(?:\[[ xX]\]\s*)?(.+?)\s*$")
_ROW = re.compile(r"^\s*\|.*\|\s*$")
_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _plain_md(s):
    return re.sub(r"\*\*(.+?)\*\*|__(.+?)__|`([^`]+)`", lambda m: m.group(1) or m.group(2) or m.group(3), s).strip()


def _title_before(lines, i):
    """The line just before a block, when it introduces it ("Here's what to pack:"), as the card's title."""
    j = i - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j >= 0 and lines[j].rstrip().endswith(":"):
        head = _plain_md(lines[j].rstrip()[:-1])
        # a short label ("Packing list:") becomes the title; a sentence stays in the text where it was
        if len(head) <= 48 and not re.search(r"[.!?]\s", head):
            return j, head
    return None, ""


def from_text(text, have=()):
    """Cards for the obvious structure in a reply, made by code so they appear every time:
    a markdown table -> table card; a numbered list of 3+ -> steps card; a bullet list of 3+ short items
    (things to do or bring, not explanations) -> checklist. Each block is taken out of the text (the card shows
    it). One card of each kind at most, and none of a kind the turn already has. Returns (cards, text)."""
    have = set(have or ())
    lines = str(text or "").split("\n")
    out, drop, i = [], set(), 0
    while i < len(lines):
        ln = lines[i]
        # table
        if "table" not in have and _ROW.match(ln) and i + 1 < len(lines) and _SEP.match(lines[i + 1]):
            j = i + 2
            while j < len(lines) and _ROW.match(lines[j]):
                j += 1
            cols = [_plain_md(x) or ("Item" if k == 0 else f"Column {k + 1}") for k, x in enumerate(ln.strip().strip("|").split("|"))]
            rows = [[_plain_md(x) for x in r.strip().strip("|").split("|")] for r in lines[i + 2:j]]
            ti, title = _title_before(lines, i)
            card = None
            try:
                if rows and all(cols):
                    card = validate("table", {"columns": cols[:8], "rows": [r[:8] for r in rows[:60]], "title": title})
            except Exception:  # noqa: BLE001
                card = None
            if card:
                out.append(card); have.add("table"); drop.update(range(i, j))
                if ti is not None:
                    drop.add(ti)
            i = j
            continue
        # numbered list -> steps
        if "steps" not in have and _NUM.match(ln):
            j, items = i, []
            while j < len(lines) and (_NUM.match(lines[j]) or (not lines[j].strip() and j + 1 < len(lines) and _NUM.match(lines[j + 1]))):
                m = _NUM.match(lines[j])
                if m:
                    items.append(_plain_md(m.group(2)))
                j += 1
            if 3 <= len(items) <= 12 and all(len(x) <= 140 for x in items):
                ti, title = _title_before(lines, i)
                try:
                    card = validate("steps", {"title": title or "Steps", "steps": [{"text": x} for x in items]})
                except Exception:  # noqa: BLE001
                    card = None
                if card:
                    out.append(card); have.add("steps"); drop.update(range(i, j))
                    if ti is not None:
                        drop.add(ti)
            i = max(j, i + 1)
            continue
        # short bullet items -> checklist
        if "checklist" not in have and _BUL.match(ln):
            j, items = i, []
            while j < len(lines) and _BUL.match(lines[j]):
                items.append(_plain_md(_BUL.match(lines[j]).group(1)))
                j += 1
            short = all(len(x) <= 80 for x in items) and sum(x.endswith(".") for x in items) <= len(items) // 3
            if 3 <= len(items) <= 30 and short:
                ti, title = _title_before(lines, i)
                try:
                    card = validate("checklist", {"title": title, "items": items})
                except Exception:  # noqa: BLE001
                    card = None
                if card:
                    out.append(card); have.add("checklist"); drop.update(range(i, j))
                    if ti is not None:
                        drop.add(ti)
            i = max(j, i + 1)
            continue
        i += 1
    if not out:
        return [], text
    rest = "\n".join(l for k, l in enumerate(lines) if k not in drop)
    rest = re.sub(r"\n{3,}", "\n\n", rest).strip()
    return out, rest


# ---------------------------------------------------------------- when a card fits but none was made

_DAY = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*|tomorrow|tonight|today"
_FIT = (
    ("table", re.compile(r"\b(?:vs\.?|versus|compare|torn between|between (?:the )?\w[\w\s-]{1,30} and|or the)\b", re.I)),
    ("steps", re.compile(r"\b(?:how (?:do|to|can|should)|recipe|making|make|cook|cooking|bake|baking|fix|replace|install|"
                         r"set up|change (?:a|the|my))\b", re.I)),
    ("event", re.compile(r"\b(?:" + _DAY + r")\b[^.\n]{0,40}\b(?:at\s*)?\d{1,2}(?::\d\d)?\s*(?:am|pm)?\b", re.I)),
    ("checklist", re.compile(r"(?:[^,\n]+,){3,}[^,\n]+|\b(?:to-?do|errands|packing|pack|forget(?:ting)? (?:stuff|something|things))\b", re.I)),
)
_FILL = {
    "table": ("""{"title": "...", "columns": ["", <each option's real name>], "rows": [[<what is compared, """
              """e.g. "Price">, <a short value for each option>], ...]} with one column per option named in the """
              """exchange (at least two), 3 to 6 rows, and cells of a few words"""),
    "steps": '{"title": "...", "steps": [{"text": "..."}, ...]}',
    "event": '{"title": "...", "start": "YYYY-MM-DDTHH:MM:SS-07:00", "location": "...", "calendar": ""}',
    "checklist": '{"title": "...", "items": ["...", "..."]}',
}


def fits(user_text):
    """The card kind the user's message calls for, by its shape (code, not the model): two options weighed ->
    table, a how-to or a dish -> steps, a day and a time -> event, a run of errands -> checklist. Else None."""
    for kind, rx in _FIT:
        if rx.search(user_text or ""):
            return kind
    return None


def cardify(user_text, reply_text, kind, now_iso=""):
    """Fill the card `kind` from the conversation with one short, cheap model call (the quick tier), only using
    what the reply and the message already say. Returns a validated card or None (never raises)."""
    try:
        from . import models, router
        cands = [c for c in router.candidates("quick") if c[0] in models.available()]
        if not cands:
            return None
        prov, model = cands[0]
        prompt = (f"Make one '{kind}' card for a chat app from this exchange. Use only facts in the reply and "
                  f"the message; don't add new ones, and use the real names from the exchange, never placeholders. Write the title in sentence case (\"This week's errands\", not \"This Week's Errands\"). "
                  f"Answer with JSON only, shaped like: {_FILL[kind]}\n"
                  f"Now: {now_iso}\n\nUser: {user_text[:1200]}\n\nAssistant: {reply_text[:2400]}")
        raw = models.complete(prov, model, [{"role": "user", "content": prompt}], max_tokens=600)
        m = re.search(r"\{.*\}", raw or "", re.S)
        if not m:
            return None
        data = json.loads(m.group(0))
        if kind == "table":
            cols = data.get("columns") if isinstance(data.get("columns"), list) else []
            # a comparison needs at least two named options, and no template names
            if len(cols) < 3 or any(re.fullmatch(r"(?i)option [a-z]|item|\.\.\.", str(x).strip()) for x in cols[1:]):
                return None
        return validate(kind, data)
    except Exception:  # noqa: BLE001  no card beats a broken one
        return None


def running(ctx):
    """tools.execute: make `ctx` the turn connect_card(None, ...) attaches to. Returns a token for done()."""
    return _current.set(ctx if isinstance(ctx, dict) else None)


def done(token):
    try:
        _current.reset(token)
    except (ValueError, LookupError):
        pass


_PATTERNS = (
    ("google", r"google (isn't|is not) connected|google signed theta out|google isn't connected any more|"
               r"gmail isn't connected|google is connected but without|sign-in expired|google calendar isn't connected|"
               r"tap connect on gmail"),
    ("twilio", r"phone calls aren't set up|\btwilio_account_sid\b|no twilio"),
    ("gemini", r"image generation isn't set up|no gemini_api_key|\bgemini_api_key\b"),
    ("tavily", r"live search isn't set up|no search key|\btavily_api_key\b"),
    ("giphy", r"\bgiphy\b.*(isn't|not|no) (set up|key|configured)|\bgiphy_api_key\b|gifs? (aren't|isn't) set up"),
    ("browser", r"web browsing isn't set up|playwright isn't installed|browsing is (off|turned off|disabled)"),
)
_TOOL_SERVICE = {"generate_image": "gemini", "web_search": "tavily", "call_me": "twilio", "call_someone": "twilio"}


def from_tool_error(name, text):
    """A connect card when a tool's output says something isn't connected or set up, else None.
    Matches the wording the tools use (google.py, calls.py, media.py, browser.py, tools.py, gifs)."""
    low = str(text or "").lower()
    if not low:
        return None
    for svc, pat in _PATTERNS:
        if re.search(pat, low):
            return connect(svc)
    svc = _TOOL_SERVICE.get(str(name or ""))
    if svc and re.search(r"(isn't|aren't|not) set up|not configured|no api key", low):
        return connect(svc)
    return None


def note_result(ctx, name, ok, text):
    """For the agent loop: after each failed tool result, attach the connect card its text calls for (no
    repeats). Successful results are skipped, since they can quote outside text. Returns the card or None."""
    if ok:
        return None
    card = from_tool_error(name, text)
    if card:
        attach(ctx, card)
    return card


# ---------------------------------------------------------------- checklist state

def route_checklist(req, start):
    """POST /api/cards/checklist {message_id, card, item, done}: tick or untick one item of a checklist card;
    saved into that message's meta.cards, so it shows the same after a reload and on every device."""
    from .app import HTTPError, respond_json
    if req.method != "POST":
        raise HTTPError(405, "method not allowed")
    body = req.json()
    try:
        mid, ci, ii = int(body.get("message_id")), int(body.get("card", 0)), int(body.get("item"))
    except (TypeError, ValueError):
        raise HTTPError(400, "message_id, card and item must be numbers") from None
    m = db.get_message(mid)
    if not m or m.get("role") != "assistant":
        raise HTTPError(404, "no such message")
    cards = list((m.get("meta") or {}).get("cards") or [])
    if not 0 <= ci < len(cards) or (cards[ci] or {}).get("type") != "checklist":
        raise HTTPError(404, "that message has no checklist there")
    card = dict(cards[ci])
    items = [dict(x) for x in card.get("items") or []]
    if not 0 <= ii < len(items):
        raise HTTPError(400, "no such item")
    items[ii]["done"] = bool(body.get("done"))
    card["items"] = items
    cards[ci] = card
    db.update_message(mid, meta={"cards": cards})
    return respond_json(start, {"ok": True, "card": card,
                                "left": sum(1 for x in items if not x.get("done")), "total": len(items)})


ROUTES = {"/api/cards/checklist": route_checklist}
