"""Home: what the opening screen shows besides Theta itself (after theta-app's home: a smart stack, the crew's
finds, top stories).

    GET /api/home     {hello, date, stack: [...], found: [...], news: [...]}
    DELETE /api/home?id=<found id>   take a find off Home

- stack: the few things that matter right now, most important first (approvals waiting, reminders due, the next
  event, a text from Theta you haven't read, data that won't survive a deploy). Built from stored data only, so
  Home opens fast.
- found: what Theta found for you while working (deals, stories, places, ideas, things to watch), saved with the
  home_post tool. Chips like Best price and News digest post their best find here. Newest first; deals and news
  fade after a few days.
- news: top stories from public news feeds (refreshed in the background every NEWS_EVERY seconds), the ones that
  match your interests (Profile > More about you) first.
"""
import html
import re
import secrets
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

from . import db

FEEDS = [("NPR", "https://feeds.npr.org/1001/rss.xml"), ("BBC", "https://feeds.bbci.co.uk/news/rss.xml"),
         ("PBS", "https://www.pbs.org/newshour/feeds/rss/headlines"), ("CBS", "https://www.cbsnews.com/latest/rss/main")]
NEWS_EVERY = 1800
FOUND_MAX = 60
KEEP_DAYS = {"deal": 7, "news": 3, "watch": 14, "place": 30, "idea": 30, "update": 7}
KINDS = tuple(KEEP_DAYS)
_lock = threading.Lock()


# ---------------------------------------------------------------- found for you

def found(now=None):
    now = now or time.time()
    items = db.get_setting("home_found")
    items = items if isinstance(items, list) else []
    return [i for i in items if now - i.get("t", 0) < KEEP_DAYS.get(i.get("kind"), 7) * 86400]


def post(item, now=None):
    now = now or time.time()
    clean = lambda v, n: re.sub(r"\s+", " ", str(v or "")).strip()[:n]  # noqa: E731
    it = {"id": secrets.token_hex(6), "t": now, "kind": item.get("kind") if item.get("kind") in KINDS else "idea",
          "title": clean(item.get("title"), 120), "summary": clean(item.get("summary"), 240),
          "url": clean(item.get("url"), 600), "image": clean(item.get("image"), 600), "price": clean(item.get("price"), 40),
          "source": clean(item.get("source"), 60)}
    if not it["title"]:
        raise ValueError("a find needs a title")
    for k in ("url", "image"):
        if it[k] and not it[k].startswith("https://"):
            it[k] = ""
    with _lock:
        items = [i for i in found(now) if not (it["url"] and i.get("url") == it["url"]) and i.get("title") != it["title"]]
        db.set_setting("home_found", ([it] + items)[:FOUND_MAX])
    return it


def remove(fid):
    with _lock:
        db.set_setting("home_found", [i for i in found() if i.get("id") != fid])


def _t_post(args, ctx):
    from .tools import ToolError
    try:
        it = post(args)
    except ValueError as e:
        raise ToolError(str(e)) from None
    return f"Saved to their Home under Found for you: {it['title']}."


TOOLS = [
    {"name": "home_post", "risk": "write", "run": _t_post,
     "description": ("Save something you found for the user to their Home screen (Found for you): a deal, a story they'd "
                     "care about, a place, an idea, something to watch, or an update on a job. Use it when a find is "
                     "worth keeping past this chat (the best price you found, the one story that matters to them). Not "
                     "for everything: one or two per job. kind: deal | news | watch | place | idea | update. Example: "
                     "{\"kind\": \"deal\", \"title\": \"Arc floor lamp, $89 at Lamp Shop\", \"price\": \"$89\", \"url\": "
                     "\"https://...\", \"summary\": \"Lowest of 4 stores; free returns\"}."),
     "params": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": list(KINDS)}, "title": {"type": "string"}, "summary": {"type": "string"},
         "url": {"type": "string"}, "image": {"type": "string"}, "price": {"type": "string"}, "source": {"type": "string"}},
         "required": ["kind", "title"]}},
]
RELEVANT = r"\b(deals?|price|cheapest|news|found|save (it|this) (to|for)|home screen)\b"


# ---------------------------------------------------------------- top stories

def _text(el, tag, ns=None):
    n = el.find(tag, ns or {})
    return (n.text or "").strip() if n is not None and n.text else ""


def parse_feed(xml_bytes, source):
    """[{title, url, summary, image, source, t}] from RSS or Atom."""
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    ns = {"media": "http://search.yahoo.com/mrss/", "atom": "http://www.w3.org/2005/Atom"}
    for it in root.iter("item"):
        img = ""
        for tag in ("media:content", "media:thumbnail"):
            m = it.find(tag, ns)
            if m is not None and (m.get("url") or "").startswith("https://"):
                img = m.get("url")
                break
        enc = it.find("enclosure")
        if not img and enc is not None and (enc.get("type") or "").startswith("image") and (enc.get("url") or "").startswith("https://"):
            img = enc.get("url")
        summary = re.sub(r"<[^>]+>", " ", html.unescape(_text(it, "description")))
        out.append({"title": html.unescape(_text(it, "title"))[:200], "url": _text(it, "link"), "image": img,
                    "summary": re.sub(r"\s+", " ", summary).strip()[:280], "source": source})
    for e in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link = e.find("atom:link", ns)
        out.append({"title": _text(e, "atom:title", ns)[:200], "url": link.get("href") if link is not None else "",
                    "image": "", "summary": _text(e, "atom:summary", ns)[:280], "source": source})
    return [o for o in out if o["title"] and o["url"].startswith("https://")]


def refresh_news(now=None):
    items = []
    for name, url in FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Theta/1.0 (personal assistant)"})
            with urllib.request.urlopen(req, timeout=10) as r:
                items += parse_feed(r.read(3_000_000), name)[:8]
        except Exception:  # noqa: BLE001  one outlet down: the others still show
            continue
    if items:
        db.set_setting("home_news", {"t": now or time.time(), "items": items})
    return items


def _interests():
    try:
        from . import account
        about = account.profile().get("about") or ""
    except Exception:  # noqa: BLE001
        return []
    words = []
    for ln in about.split("\n"):
        if ln.startswith(("Into:", "Working toward:")):
            words += [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", ln.split(":", 1)[1])]
    return [w for w in words if w not in {"with", "about", "that", "this", "their", "things"}]


def news(limit=12):
    """Top stories, the ones that match their interests first, one per headline across outlets."""
    cached = db.get_setting("home_news") or {}
    items = list(cached.get("items") or [])
    likes = _interests()
    seen, out = set(), []
    for it in items:
        key = re.sub(r"[^a-z0-9]+", " ", it["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        low = (it["title"] + " " + it["summary"]).lower()
        it = dict(it, match=any(w in low for w in likes))
        out.append(it)
    out.sort(key=lambda i: (not i["match"], 0 if i.get("image") else 1))
    return out[:limit]


def _next_event(now):
    from . import home_extras
    home_extras.refresh_today(now)  # today's whole list, for Home's calendar
    try:
        import datetime
        from . import gcal, persona
        today = persona.local_now(now).date()
        evs, _ = gcal.events_between(today, today + datetime.timedelta(days=1), now)
        for e in evs:
            if e.get("all_day"):
                continue
            st = datetime.datetime.fromisoformat(e["start"]).timestamp()
            if st > now - 1800:
                when = persona.local_now(st).strftime("%-I:%M %p")
                db.set_setting("home_next_event", {"title": e.get("title"), "start_t": st,
                                                   "when": when + (f" · {e['location']}" if e.get("location") else "")})
                return
        db.set_setting("home_next_event", None)
    except Exception:  # noqa: BLE001
        pass


def tick(now):
    cached = db.get_setting("home_news") or {}
    if now - float(cached.get("t") or 0) > NEWS_EVERY:
        threading.Thread(target=refresh_news, args=(now,), name="news", daemon=True).start()
    if now - float(db.get_setting("home_next_t") or 0) > 600:
        db.set_setting("home_next_t", now)
        threading.Thread(target=_next_event, args=(now,), name="next-event", daemon=True).start()
    return []


# ---------------------------------------------------------------- the smart stack

def stack(now=None):
    """[{score, kind, eyebrow, title, sub, action}] most important first. action: "chat:<msg id>", "settings:<page>",
    "approvals" or a URL."""
    now = now or time.time()
    out = []
    add = lambda score, kind, eyebrow, title, sub, action, tone="": out.append(  # noqa: E731
        {"score": score, "kind": kind, "eyebrow": eyebrow, "title": title, "sub": sub, "action": action, "tone": tone})
    try:
        from . import account
        st = account.storage()
        if not st["persistent"]:
            add(110, "warn", "Needs fixing", "Theta forgets everything on each deploy", "Tap to see how to fix it",
                "settings:data", "bad")
    except Exception:  # noqa: BLE001
        pass
    try:
        pend = [a for a in db.approvals("pending") if float((a.get("action") or {}).get("expires") or now + 1) > now]
        if pend:
            add(100, "approve", "Waiting for your OK", f"{len(pend)} thing{'s' if len(pend) != 1 else ''} ready to go",
                ((pend[0].get("action") or {}).get("preview") or "").split("\n")[0].strip("*")[:90], "chat:")
    except Exception:  # noqa: BLE001
        pass
    try:
        for j in db.jobs("pending", limit=20):
            if j.get("kind") == "remind" and float(j.get("due_t") or 0) <= now + 3600:
                p = j.get("payload") or {}
                late = float(j["due_t"]) <= now
                from .tools import fmt_time
                add(95, "remind", "Reminder", p.get("text") or "Reminder", "Due now" if late else fmt_time(j["due_t"], now),
                    "chat:", "warn")
                break
    except Exception:  # noqa: BLE001
        pass
    nxt = db.get_setting("home_next_event")  # found in the background (tick), so Home never waits on Google
    if isinstance(nxt, dict) and nxt.get("start_t", 0) > now - 1800:
        mins = (nxt["start_t"] - now) / 60
        add(90 if mins <= 120 else 60, "calendar", "Happening now" if mins <= 0 else "Up next", nxt.get("title") or "Event",
            nxt.get("when", "") + (f" · in {int(mins)} min" if 0 < mins < 60 else ""), "chat:")
    try:
        rows = db.messages("theta", limit=30)
        pro = [m for m in rows if m["role"] == "assistant" and (m.get("meta") or {}).get("proactive")]
        if pro and now - float(pro[-1].get("t") or 0) < 12 * 3600:
            m = pro[-1]
            add(70, "text", "Theta texted you", re.sub(r"[*_`#]", "", m["text"])[:120], "", f"chat:{m['id']}")
    except Exception:  # noqa: BLE001
        pass
    f = found(now)
    if f:
        add(40, "found", "Found for you", f[0]["title"], f[0].get("price") or f[0].get("summary", "")[:80],
            f[0].get("url") or "chat:")
    return sorted(out, key=lambda c: -c["score"])[:6]


# ---------------------------------------------------------------- route

def route(req, start):
    from .app import HTTPError, respond_json
    from . import persona
    if req.method == "DELETE":
        remove(str(req.query.get("id") or ""))
    elif req.method != "GET":
        raise HTTPError(405, "method not allowed")
    t = persona.local_now()
    hello = "Good morning" if 4 <= t.hour < 12 else "Good afternoon" if t.hour < 18 else "Good evening"
    name = ""
    try:
        from . import account
        p = account.profile()
        name = p.get("nickname") or (p.get("name") or "").split(" ")[0]
    except Exception:  # noqa: BLE001
        pass
    from . import home_extras
    stk, fnd, nws = stack(), found()[:12], news()
    return respond_json(start, {"hello": hello + (f", {name}" if name else ""), "date": t.strftime("%A, %B ") + str(t.day),
                                "stack": stk, "found": fnd, "news": nws, "layout": home_extras.layout(),
                                **home_extras.extras(stack=stk, found_=fnd, news_=nws)})


ROUTES = {"/api/home": route}


def context(bot, now):
    return ""
