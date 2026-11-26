"""The in-app calendar: Google Calendar (when connected), calendar subscriptions (ICS links, read-only) and
events added in Theta while Google isn't connected, merged into one list for the phone.

    GET    /api/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD   {events: [{id, title, start, end, all_day, location,
                                                           source, color}], sources: [...], google: bool}
    GET    /api/calendar/subscriptions                   {subscriptions: [{id, name, url, color}]}
    POST   /api/calendar/subscriptions {url, name}       https only; private and loopback hosts are refused
    DELETE /api/calendar/subscriptions?id=
    POST   /api/calendar/events {title, date, time, duration, location}   to Google when connected, else kept here
    DELETE /api/calendar/events?id=                      (events kept here only)
    GET/POST /api/calendar/settings {calendar_nudges}

tick(): every 5 minutes, looks 2 hours ahead; for an event with a location that starts within ~35 minutes,
texts one "leave by" heads-up plus a push (deduped with db.seen/mark), unless setting calendar_nudges is off.
"""
import datetime
import hashlib
import ipaddress
import re
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import db, tools

SUBS, LOCAL, NUDGES = "calendar_subs", "calendar_local", "calendar_nudges"
CACHE_TTL = 900
ICS_MAX = 3_000_000
MAX_SUBS = 20
TICK_EVERY = 300
LOOKAHEAD = 2 * 3600
LEAD = 35 * 60          # a heads-up goes out once an event is this close
GOOGLE_COLOR, LOCAL_COLOR = "#4fd3ff", "#b18cff"
PALETTE = ["#ffb35c", "#7be08a", "#ff7aa8", "#ffd84f", "#5b7cff", "#5ce1c9", "#ff8f6b"]

_cache = {}
_cache_lock = threading.Lock()
_last_tick = [0.0]


def log(*a):
    print("[protos] calendar:", *a, file=sys.stderr, flush=True)


def _tz():
    return tools._tz()


def _google():
    try:
        from . import google
        return google
    except Exception:  # noqa: BLE001
        return None


def _gconnected():
    g = _google()
    return bool(g and g.connected("calendar"))


# ---- URL safety (subscriptions are fetched by the server, so they must not reach private addresses)

class UnsafeURL(Exception):
    pass


def _resolve(host):
    return [ai[4][0] for ai in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]


def _ip_ok(ip):
    a = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_global and not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast
                                or a.is_reserved or a.is_unspecified)


def check_url(url):
    """The https URL to fetch (webcal:// becomes https://). Raises UnsafeURL with a reason."""
    url = str(url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        raise UnsafeURL("that isn't a link") from None
    if u.scheme.lower() != "https":
        raise UnsafeURL("only https:// (or webcal://) calendar links work")
    host = (u.hostname or "").lower()
    if not host or u.username or u.password:
        raise UnsafeURL("that link has no host, or has a login in it")
    if u.port not in (None, 443):
        raise UnsafeURL("only the standard https port works")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        raise UnsafeURL("that's a private address")
    try:
        ips = [host] if re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host) else _resolve(host)
    except (socket.gaierror, UnicodeError, OSError):
        raise UnsafeURL("that host can't be found") from None
    try:
        if not ips or not all(_ip_ok(ip.strip("[]")) for ip in ips):
            raise UnsafeURL("that's a private or local address")
    except ValueError:
        raise UnsafeURL("that host's address isn't valid") from None
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _open(req, timeout=15):
    return _opener.open(req, timeout=timeout)


def fetch_ics(url):
    """GET an ICS feed, re-checking every redirect hop against private addresses."""
    for _hop in range(4):
        url = check_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": "Theta-calendar/1", "Accept": "text/calendar, */*"})
        try:
            with _open(req) as r:
                data = r.read(ICS_MAX + 1)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            raise
        if len(data) > ICS_MAX:
            raise ValueError("that calendar is too big (3 MB max)")
        return data.decode("utf-8", "replace")
    raise ValueError("too many redirects")


# ---- ICS parsing

def _unescape(v):
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def _lines(text):
    out = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        elif raw.strip():
            out.append(raw)
    return out


def _prop(line):
    """'DTSTART;TZID=Europe/Paris:20261127T090000' -> ('DTSTART', {'TZID': 'Europe/Paris'}, '20261127T090000')."""
    m = re.match(r'^((?:[^:";]|"[^"]*")+?)((?:;(?:[^:";]|"[^"]*")*)*):(.*)$', line)
    if not m:
        return None, {}, ""
    params = {}
    for p in re.findall(r';((?:[^;"]|"[^"]*")*)', m.group(2)):
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return m.group(1).upper(), params, m.group(3)


_WIN_TZ = {"Pacific Standard Time": "America/Los_Angeles", "Mountain Standard Time": "America/Denver",
           "Central Standard Time": "America/Chicago", "Eastern Standard Time": "America/New_York",
           "GMT Standard Time": "Europe/London", "W. Europe Standard Time": "Europe/Berlin",
           "Romance Standard Time": "Europe/Paris", "Central Europe Standard Time": "Europe/Budapest",
           "AUS Eastern Standard Time": "Australia/Sydney", "Tokyo Standard Time": "Asia/Tokyo",
           "India Standard Time": "Asia/Kolkata", "China Standard Time": "Asia/Shanghai", "UTC": "UTC"}


def _zone(tzid):
    from zoneinfo import ZoneInfo
    if not tzid:
        return _tz()
    for name in (tzid, _WIN_TZ.get(tzid), tzid.split("/", 1)[-1] if tzid.startswith("/") else None):
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001
            continue
    return _tz()


def parse_dt(value, params=None):
    """An ICS DATE or DATE-TIME -> (date | aware datetime, all_day)."""
    params = params or {}
    v = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", v):
        return datetime.date(int(v[:4]), int(v[4:6]), int(v[6:8])), True
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z?)", v)
    if not m:
        raise ValueError(f"bad date {v!r}")
    y, mo, d, h, mi, s, z = m.groups()
    naive = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    if z:
        return naive.replace(tzinfo=datetime.timezone.utc), False
    return naive.replace(tzinfo=_zone(params.get("TZID"))), False


def _duration(v):
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * datetime.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def parse_ics(text):
    """VEVENTs as dicts: uid, summary, location, start, end, all_day, rrule, exdates, recurrence_id, status."""
    events, cur, depth = [], None, 0
    for line in _lines(text):
        name, params, value = _prop(line)
        if name == "BEGIN":
            if value.upper() == "VEVENT" and cur is None:
                cur, depth = {"exdates": [], "_p": {}}, 0
            elif cur is not None:
                depth += 1
            continue
        if name == "END":
            if cur is not None and depth:
                depth -= 1
            elif cur is not None and value.upper() == "VEVENT":
                ev = _finish(cur)
                if ev:
                    events.append(ev)
                cur = None
            continue
        if cur is None or depth:
            continue
        if name == "EXDATE":
            for part in value.split(","):
                try:
                    cur["exdates"].append(parse_dt(part, params)[0])
                except ValueError:
                    pass
        else:
            cur["_p"].setdefault(name, (params, value))
    return events


def _finish(cur):
    p = cur["_p"]
    if "DTSTART" not in p:
        return None
    try:
        start, all_day = parse_dt(p["DTSTART"][1], p["DTSTART"][0])
    except ValueError:
        return None
    end = None
    if "DTEND" in p:
        try:
            end = parse_dt(p["DTEND"][1], p["DTEND"][0])[0]
        except ValueError:
            end = None
    elif "DURATION" in p:
        dur = _duration(p["DURATION"][1])
        end = start + dur if dur is not None else None
    if end is None or type(end) is not type(start) or end < start:
        end = start + (datetime.timedelta(days=1) if all_day else datetime.timedelta(0))
    rid = None
    if "RECURRENCE-ID" in p:
        try:
            rid = parse_dt(p["RECURRENCE-ID"][1], p["RECURRENCE-ID"][0])[0]
        except ValueError:
            rid = None
    return {"uid": p.get("UID", ({}, ""))[1].strip(), "summary": _unescape(p.get("SUMMARY", ({}, ""))[1]).strip(),
            "location": _unescape(p.get("LOCATION", ({}, ""))[1]).strip(), "start": start, "end": end,
            "all_day": all_day, "rrule": p.get("RRULE", ({}, ""))[1].strip() or None, "exdates": cur["exdates"],
            "recurrence_id": rid, "status": p.get("STATUS", ({}, ""))[1].strip().upper()}


_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _rule(s):
    r = {}
    for part in s.split(";"):
        k, _, v = part.partition("=")
        r[k.strip().upper()] = v.strip()
    return r


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return y + d.year, m + 1


def _key(t):
    """Comparable instant: a date as local midnight in the user's tz, a datetime as itself."""
    if isinstance(t, datetime.datetime):
        return t
    return datetime.datetime.combine(t, datetime.time(), _tz())


def _at(d, base):
    """Date d at the wall time (and zone) of base (a date or an aware datetime)."""
    if isinstance(base, datetime.datetime):
        return datetime.datetime.combine(d, base.timetz())
    return d


def _nth_weekday(y, m, wd, n):
    """The n-th (1..5, or -1..-5) weekday wd (0=Mon) of month y-m, or None."""
    first = datetime.date(y, m, 1)
    nxt = datetime.date(y + (m == 12), m % 12 + 1, 1)
    days = [first + datetime.timedelta(i) for i in range((nxt - first).days) if (first + datetime.timedelta(i)).weekday() == wd]
    try:
        return days[n - 1] if n > 0 else days[n]
    except IndexError:
        return None


MAX_OCC = 3000


def _overlaps(s, e, lo, hi):
    s, e = _key(s), _key(e)
    return (e > lo and s < hi) or (s == e and lo <= s < hi)


def occurrences(ev, lo, hi):
    """Start times of ev that overlap [lo, hi) (aware datetimes). Simple RRULE: DAILY, WEEKLY (+BYDAY),
    MONTHLY (+BYDAY like 1MO/-1FR, or BYMONTHDAY), YEARLY; INTERVAL, COUNT, UNTIL; EXDATE."""
    start, dur = ev["start"], ev["end"] - ev["start"]
    r = _rule(ev["rrule"]) if ev.get("rrule") else {}
    freq = r.get("FREQ", "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return [start] if _overlaps(start, start + dur, lo, hi) else []
    interval = max(1, int(r.get("INTERVAL") or 1))
    count = int(r["COUNT"]) if r.get("COUNT", "").isdigit() else None
    until = None
    if r.get("UNTIL"):
        try:
            u, u_all = parse_dt(r["UNTIL"])
            until = _key(u) + (datetime.timedelta(days=1) - datetime.timedelta(seconds=1) if u_all else datetime.timedelta(0))
        except ValueError:
            until = None
    byday = [x.strip().upper() for x in r.get("BYDAY", "").split(",") if x.strip()]
    exset = {_key(x) for x in ev.get("exdates") or []}
    d0 = start.date() if isinstance(start, datetime.datetime) else start

    # without COUNT, jump close to the window instead of walking from a start years ago
    skip = 0
    if count is None:
        gap = (lo.astimezone(_tz()).date() - d0).days
        if gap > 0:
            per = {"DAILY": interval, "WEEKLY": 7 * interval, "MONTHLY": 31 * interval, "YEARLY": 366 * interval}[freq]
            skip = max(0, gap // per - 2)

    def periods():
        k = skip
        while True:
            if freq == "DAILY":
                yield [d0 + datetime.timedelta(days=k * interval)]
            elif freq == "WEEKLY":
                wk = d0 - datetime.timedelta(days=d0.weekday()) + datetime.timedelta(weeks=k * interval)
                days = [_DAYS.index(b[-2:]) for b in byday if b[-2:] in _DAYS] or [d0.weekday()]
                yield [wk + datetime.timedelta(days=i) for i in sorted(set(days))]
            elif freq == "MONTHLY":
                y, m = _add_months(d0, k * interval)
                out = []
                if byday:
                    for b in byday:
                        mm = re.fullmatch(r"([+-]?\d)?(MO|TU|WE|TH|FR|SA|SU)", b)
                        if mm and mm.group(1):
                            x = _nth_weekday(y, m, _DAYS.index(mm.group(2)), int(mm.group(1)))
                            if x:
                                out.append(x)
                else:
                    days = [int(x) for x in r.get("BYMONTHDAY", "").split(",") if x.strip().lstrip("-").isdigit()] or [d0.day]
                    for md in days:
                        try:
                            out.append(datetime.date(y, m, md) if md > 0 else
                                       datetime.date(y + (m == 12), m % 12 + 1, 1) + datetime.timedelta(days=md))
                        except ValueError:
                            pass  # e.g. the 31st in a 30-day month is skipped, as RFC 5545 says
                yield sorted(out)
            else:
                try:
                    yield [datetime.date(d0.year + k * interval, d0.month, d0.day)]
                except ValueError:
                    yield []
            k += 1

    out, n, walked = [], 0, 0
    for days in periods():
        walked += 1
        if walked > MAX_OCC:
            break
        stop = False
        for d in days:
            if d < d0:
                continue
            t = _at(d, start)
            if until is not None and _key(t) > until:
                stop = True
                break
            n += 1
            if count is not None and n > count:
                stop = True
                break
            if _key(t) >= hi:
                stop = True
                break
            if _key(t) in exset:
                continue
            if _overlaps(t, t + dur, lo, hi):
                out.append(t)
        if stop:
            break
    return out


def expand(events, lo, hi):
    """Parsed VEVENTs -> [(ev, start, end)] inside [lo, hi), with RECURRENCE-ID overrides replacing their instance."""
    overrides = {(e["uid"], _key(e["recurrence_id"])) for e in events if e.get("recurrence_id") is not None}
    out = []
    for e in events:
        if e.get("status") == "CANCELLED" and e.get("recurrence_id") is None:
            continue
        dur = e["end"] - e["start"]
        for s in occurrences(e, lo, hi):
            if e.get("recurrence_id") is None and (e["uid"], _key(s)) in overrides:
                continue
            if e.get("status") == "CANCELLED":
                continue
            out.append((e, s, s + dur))
    out.sort(key=lambda x: _key(x[1]))
    return out


# ---- the merged list

def _iso(t):
    if isinstance(t, datetime.datetime):
        return t.astimezone(_tz()).isoformat(timespec="minutes")
    return t.isoformat()


def _short_id(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def subscriptions():
    v = db.get_setting(SUBS)
    return v if isinstance(v, list) else []


def _sub_events(sub, lo, hi, now=None):
    now = time.time() if now is None else now
    with _cache_lock:
        hit = _cache.get(sub["id"])
    if hit and now - hit[0] < CACHE_TTL:
        parsed = hit[1]
    else:
        try:
            parsed = parse_ics(fetch_ics(sub["url"]))
            with _cache_lock:
                _cache[sub["id"]] = (now, parsed)
        except Exception as e:  # noqa: BLE001  one bad feed never breaks the calendar
            log(f"subscription {sub.get('name')!r} failed: {type(e).__name__}: {str(e)[:120]}")
            if hit:
                parsed = hit[1]
            else:
                return [], f"{sub.get('name') or 'A calendar'} couldn't be loaded"
    out = []
    for e, s, en in expand(parsed, lo, hi):
        out.append({"id": "ics:" + _short_id(sub["id"], e["uid"], _iso(s)), "title": e["summary"] or "(no title)",
                    "start": _iso(s), "end": _iso(en), "all_day": e["all_day"], "location": e["location"],
                    "source": sub.get("name") or "Subscription", "color": sub.get("color") or PALETTE[0]})
    return out, None


def _google_events(d0, d1):
    g = _google()
    out = []
    for e in g.list_events(d0, d1, limit=250):
        if e.get("status") == "cancelled":
            continue
        s, all_day = g._ev_time(e.get("start"))
        en, _ = g._ev_time(e.get("end"))
        if s is None:
            continue
        out.append({"id": "g:" + str(e.get("id")), "title": e.get("summary") or "(no title)", "start": _iso(s),
                    "end": _iso(en or s), "all_day": all_day, "location": e.get("location") or "",
                    "source": "Google", "color": GOOGLE_COLOR, "link": e.get("htmlLink") or ""})
    return out


def _local_events(lo, hi):
    out = []
    for e in db.get_setting(LOCAL) or []:
        try:
            s = datetime.datetime.fromisoformat(e["start"]) if "T" in e["start"] else datetime.date.fromisoformat(e["start"])
            en = datetime.datetime.fromisoformat(e["end"]) if "T" in e["end"] else datetime.date.fromisoformat(e["end"])
        except (KeyError, ValueError, TypeError):
            continue
        if _key(en) > lo and _key(s) < hi:
            out.append(dict(e, source="Theta", color=LOCAL_COLOR, all_day=not isinstance(s, datetime.datetime)))
    return out


def events_between(d0, d1, now=None):
    """Every event from local midnight of d0 to the end of d1, sorted. Returns (events, problems)."""
    tz = _tz()
    lo = datetime.datetime.combine(d0, datetime.time(), tz)
    hi = datetime.datetime.combine(d1 + datetime.timedelta(days=1), datetime.time(), tz)
    out, problems = [], []
    if _gconnected():
        try:
            out += _google_events(d0, d1)
        except Exception as e:  # noqa: BLE001
            problems.append(f"Google Calendar: {str(e)[:160]}")
    for sub in subscriptions():
        evs, why = _sub_events(sub, lo, hi, now)
        out += evs
        if why:
            problems.append(why)
    out += _local_events(lo, hi)
    out.sort(key=lambda e: (e["start"][:10], not e["all_day"], _key(_parse_iso(e["start"])), e["title"]))
    return out, problems


def _parse_iso(s):
    return datetime.datetime.fromisoformat(s) if "T" in s else datetime.date.fromisoformat(s)


# ---- routes

def _http():
    from .app import HTTPError, respond_json
    return HTTPError, respond_json


def _day(s, name, default):
    HTTPError, _ = _http()
    if not s:
        return default
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        raise HTTPError(400, f"{name} must be a date like 2026-11-27") from None


def route_calendar(req, start):
    HTTPError, respond_json = _http()
    if req.method != "GET":
        raise HTTPError(405, "method not allowed")
    today = datetime.datetime.now(_tz()).date()
    d0 = _day(req.query.get("from"), "from", today)
    d1 = _day(req.query.get("to"), "to", d0 + datetime.timedelta(days=6))
    if d1 < d0:
        raise HTTPError(400, "to is before from")
    if (d1 - d0).days > 62:
        raise HTTPError(400, "ask for at most about two months at a time")
    evs, problems = events_between(d0, d1)
    g = _google()
    return respond_json(start, {"from": d0.isoformat(), "to": d1.isoformat(), "tz": str(_tz()), "events": evs,
                                "problems": problems, "google": _gconnected(),
                                "google_note": (g._note() if g else "") if not _gconnected() else "",
                                "sources": [{"name": "Google", "color": GOOGLE_COLOR}] * _gconnected()
                                + [{"name": s.get("name"), "color": s.get("color")} for s in subscriptions()]})


def route_subscriptions(req, start):
    HTTPError, respond_json = _http()
    subs = subscriptions()
    if req.method == "POST":
        body = req.json()
        try:
            url = check_url(body.get("url"))
        except UnsafeURL as e:
            raise HTTPError(400, f"That link can't be added: {e}.") from None
        if len(subs) >= MAX_SUBS:
            raise HTTPError(400, f"at most {MAX_SUBS} calendar links")
        if any(s["url"] == url for s in subs):
            raise HTTPError(409, "that calendar is already added")
        name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()[:60] or (urllib.parse.urlsplit(url).hostname or "Calendar")
        used = {s.get("color") for s in subs}
        color = next((c for c in PALETTE if c not in used), PALETTE[len(subs) % len(PALETTE)])
        sub = {"id": secrets.token_hex(6), "url": url, "name": name, "color": color, "t": time.time()}
        db.set_setting(SUBS, subs + [sub])
        return respond_json(start, {"ok": True, "subscription": sub})
    if req.method == "DELETE":
        sid = req.query.get("id") or ""
        left = [s for s in subs if s.get("id") != sid]
        if len(left) == len(subs):
            raise HTTPError(404, "no such calendar link")
        db.set_setting(SUBS, left)
        with _cache_lock:
            _cache.pop(sid, None)
        return respond_json(start, {"ok": True})
    if req.method != "GET":
        raise HTTPError(405, "method not allowed")
    return respond_json(start, {"subscriptions": subs})


def _event_args(body):
    """{title, date, time, duration, location} from the app -> calendar_add-style args. Raises HTTPError."""
    HTTPError, _ = _http()
    title = re.sub(r"\s+", " ", str(body.get("title") or "")).strip()[:200]
    if not title:
        raise HTTPError(400, "title is required")
    try:
        d = datetime.date.fromisoformat(str(body.get("date") or "")[:10])
    except ValueError:
        raise HTTPError(400, "date must be like 2026-11-27") from None
    args = {"title": title}
    if body.get("location"):
        args["location"] = str(body["location"])[:300]
    tm = str(body.get("time") or "").strip()
    if not tm:
        args["start"] = d.isoformat()
        return args
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", tm)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise HTTPError(400, "time must be like 14:30")
    try:
        dur = float(body.get("duration") or 60)
    except (TypeError, ValueError):
        raise HTTPError(400, "duration must be minutes") from None
    if not 5 <= dur <= 1440:
        raise HTTPError(400, "duration must be 5 to 1440 minutes")
    st = datetime.datetime.combine(d, datetime.time(int(m.group(1)), int(m.group(2))), _tz())
    args.update(start=st.isoformat(), duration_minutes=dur)
    return args


def route_events(req, start):
    HTTPError, respond_json = _http()
    if req.method == "DELETE":
        eid = req.query.get("id") or ""
        cur = db.get_setting(LOCAL) or []
        left = [e for e in cur if e.get("id") != eid]
        if len(left) == len(cur):
            raise HTTPError(404, "only events added in Theta (not Google's or a link's) can be removed here")
        db.set_setting(LOCAL, left)
        return respond_json(start, {"ok": True})
    if req.method != "POST":
        raise HTTPError(405, "method not allowed")
    args = _event_args(req.json())
    if _gconnected():
        try:
            e = _google().add_event(args)
        except tools.ToolError as e:
            raise HTTPError(502, str(e)) from None
        return respond_json(start, {"ok": True, "where": "google", "id": "g:" + str(e.get("id")),
                                    "link": e.get("htmlLink") or ""})
    st = _parse_iso(args["start"])
    if isinstance(st, datetime.datetime):
        en = st + datetime.timedelta(minutes=args["duration_minutes"])
    else:
        en = st + datetime.timedelta(days=1)
    ev = {"id": "t:" + secrets.token_hex(6), "title": args["title"], "start": _iso(st), "end": _iso(en),
          "location": args.get("location", "")}
    cur = db.get_setting(LOCAL) or []
    db.set_setting(LOCAL, (cur + [ev])[-500:])
    return respond_json(start, {"ok": True, "where": "theta", "id": ev["id"]})


def nudges_on():
    return db.get_setting(NUDGES) is not False


def route_settings(req, start):
    HTTPError, respond_json = _http()
    if req.method == "POST":
        body = req.json()
        if NUDGES in body:
            db.set_setting(NUDGES, bool(body[NUDGES]))
    elif req.method != "GET":
        raise HTTPError(405, "method not allowed")
    return respond_json(start, {NUDGES: nudges_on()})


ROUTES = {"/api/calendar": route_calendar, "/api/calendar/subscriptions": route_subscriptions,
          "/api/calendar/events": route_events, "/api/calendar/settings": route_settings}


# ---- leave-by heads-ups

def _maps(loc):
    return "https://www.google.com/maps/dir/?api=1&destination=" + urllib.parse.quote(loc)


def tick(now):
    """Every 5 minutes: one heads-up for each event with a place that starts within ~35 minutes."""
    if now - _last_tick[0] < TICK_EVERY - 5:
        return []
    _last_tick[0] = now
    if not nudges_on():
        return []
    tz = _tz()
    d0 = datetime.datetime.fromtimestamp(now, tz).date()
    d1 = datetime.datetime.fromtimestamp(now + LOOKAHEAD, tz).date()
    evs, _ = events_between(d0, d1, now)
    sent = []
    for e in evs:
        if e["all_day"] or not (e.get("location") or "").strip():
            continue
        st = datetime.datetime.fromisoformat(e["start"]).timestamp()
        if not (now < st <= now + LEAD):
            continue
        key = f"gcal:leave:{e['id']}:{int(st)}"
        if db.seen(key):
            continue
        db.mark(key, ttl_days=2)
        mins = max(1, int(round((st - now) / 60)))
        title = re.sub(r"\s+", " ", e["title"]).strip()[:120]
        loc = re.sub(r"\s+", " ", e["location"]).strip()[:200]
        hm = datetime.datetime.fromtimestamp(st, tz).strftime("%H:%M")
        text = (f"Leave-by heads-up: {title} starts at {hm} (in {mins} min) at {loc}. "
                f"Directions: {_maps(loc)}")
        m = db.add_message("theta", "assistant", text, {"proactive": True, "source": "calendar", "event": e["id"]})
        try:
            from . import push
            push.notify("Theta", f"{title} at {hm}: time to head out", f"/?m={m['id']}")
        except Exception as ex:  # noqa: BLE001
            log(f"push failed: {type(ex).__name__}")
        sent.append(m)
    return sent
