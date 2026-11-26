"""The in-app calendar (server/gcal.py): ICS parsing with RRULE and TZID, the private-host refusal, the merged
/api/calendar list, adding events, and leave-by heads-ups. No network: the ICS fetch, DNS and Google are stubbed.
Run: python3 tests/test_gcal.py"""
import datetime
import io
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_DATA=tempfile.mkdtemp(prefix="protos-gcal-"),
                  PROTOS_TZ="America/Denver", PROTOS_QUIET="1")
for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "PROTOS_PUBLIC_URL"):
    os.environ.pop(k, None)

from zoneinfo import ZoneInfo  # noqa: E402

from server import app, db, ext, gcal, google, push, tools  # noqa: E402

FAILED = []
DEN, UTC = ZoneInfo("America/Denver"), datetime.timezone.utc


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILED.append(name)


def urlopen_forbidden(*a, **k):
    raise AssertionError("no real network in tests")


urllib.request.urlopen = urlopen_forbidden

# DNS: public names resolve to a public address, the rest as listed
DNS = {"cal.example.com": ["93.184.216.34"], "feeds.example.org": ["2606:2800:220:1::248"],
       "sneaky.example.com": ["10.0.0.5"], "mixed.example.com": ["93.184.216.34", "127.0.0.1"],
       "metadata.example.com": ["169.254.169.254"], "mapped.example.com": ["::ffff:127.0.0.1"]}
gcal._resolve = lambda host: DNS[host] if host in DNS else (_ for _ in ()).throw(OSError("nx"))

FEEDS, FETCHES = {}, []


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_open(req, timeout=15):
    FETCHES.append(req.full_url)
    v = FEEDS.get(req.full_url)
    if v is None:
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b""))
    if isinstance(v, tuple):  # a redirect
        raise urllib.error.HTTPError(req.full_url, 302, "moved", {"Location": v[1]}, io.BytesIO(b""))
    return Resp(v.encode())


gcal._open = fake_open

PUSHES = []
push.notify = lambda title, body, url="/", urgent=False, now=None: PUSHES.append((title, body, url)) or 1


def call(path, method="GET", body=None, key="k"):
    raw = json.dumps(body).encode() if body is not None else b""
    p, _, qs = path.partition("?")
    env = {"REQUEST_METHOD": method, "PATH_INFO": p, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http", "REMOTE_ADDR": "1.2.3.4"}
    if key:
        env["HTTP_X_PROTOS_KEY"] = key
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]))))
    return got["s"], json.loads(out or b"{}")


db.init()
ext.reset()
tools._ext_reset()


def win(d0, d1):
    return (datetime.datetime.combine(d0, datetime.time(), DEN), datetime.datetime.combine(d1, datetime.time(), DEN))


def starts(text, d0, d1):
    lo, hi = win(d0, d1)
    return [(e["summary"], s) for e, s, _en in gcal.expand(gcal.parse_ics(text), lo, hi)]


D = datetime.date

# ---- parsing
ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VTIMEZONE\r
TZID:Europe/Paris\r
END:VTIMEZONE\r
BEGIN:VEVENT\r
UID:one@x\r
DTSTART;TZID=Europe/Paris:20261127T090000\r
DTEND;TZID=Europe/Paris:20261127T100000\r
SUMMARY:Standup\\, team\\; daily\r
LOCATION:Room 4\\nFloor 2\r
DESCRIPTION:a long description that is folded across\r
  two lines\r
BEGIN:VALARM\r
TRIGGER:-PT15M\r
SUMMARY:alarm summary must not win\r
END:VALARM\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:two@x\r
DTSTART;VALUE=DATE:20261128\r
DTEND;VALUE=DATE:20261129\r
SUMMARY:Holiday\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:three@x\r
DTSTART:20261127T180000Z\r
DURATION:PT1H30M\r
SUMMARY:Call with Lon\r
 don office\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:four@x\r
DTSTART:20261127T120000\r
SUMMARY:Floating lunch\r
END:VEVENT\r
END:VCALENDAR\r
"""
evs = {e["uid"]: e for e in gcal.parse_ics(ICS)}
e1 = evs["one@x"]
check("TZID datetimes keep their zone", e1["start"] == datetime.datetime(2026, 11, 27, 9, 0, tzinfo=ZoneInfo("Europe/Paris"))
      and e1["start"].astimezone(DEN).hour == 1, e1["start"])
check("SUMMARY and LOCATION are unescaped; a VALARM inside doesn't leak", e1["summary"] == "Standup, team; daily"
      and e1["location"] == "Room 4\nFloor 2", e1)
check("VALUE=DATE is all-day", evs["two@x"]["all_day"] and evs["two@x"]["start"] == D(2026, 11, 28))
e3 = evs["three@x"]
check("Z is UTC, DURATION gives the end, folded lines join", e3["start"] == datetime.datetime(2026, 11, 27, 18, tzinfo=UTC)
      and e3["end"] - e3["start"] == datetime.timedelta(minutes=90) and e3["summary"] == "Call with London office", e3)
check("a floating time is in the user's zone", evs["four@x"]["start"].utcoffset() == datetime.timedelta(hours=-7))
check("Windows zone names map to IANA", gcal.parse_dt("20261127T090000", {"TZID": "Eastern Standard Time"})[0].utcoffset()
      == datetime.timedelta(hours=-5))
check("an unknown TZID falls back to the user's zone", gcal.parse_dt("20261127T090000", {"TZID": "Mars/Base"})[0].utcoffset()
      == datetime.timedelta(hours=-7))
got = starts(ICS, D(2026, 11, 27), D(2026, 11, 28))
check("a one-day window holds the day's events (Holiday is the next day)",
      sorted(n for n, _ in got) == ["Call with London office", "Floating lunch", "Standup, team; daily"], got)


def vev(uid, start, rrule="", extra=""):
    return (f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:{uid}\nDTSTART{start}\nSUMMARY:{uid}\n"
            + (f"RRULE:{rrule}\n" if rrule else "") + extra + "END:VEVENT\nEND:VCALENDAR\n")


# ---- RRULE
daily = vev("daily", ";TZID=America/Denver:20261120T080000", "FREQ=DAILY;COUNT=10")
got = starts(daily, D(2026, 11, 25), D(2026, 12, 10))
check("DAILY with COUNT stops after COUNT (20th..29th)", [s.day for _, s in got] == [25, 26, 27, 28, 29], got)
weekly = vev("gym", ";TZID=America/Denver:20261102T180000", "FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20261121T060000Z")
got = starts(weekly, D(2026, 11, 1), D(2026, 12, 31))
check("WEEKLY with BYDAY and UNTIL", [s.day for _, s in got] == [2, 4, 6, 9, 11, 13, 16, 18, 20], got)
check("occurrences keep their wall time", all(s.hour == 18 for _, s in got))
biweekly = vev("bi", ";TZID=America/Denver:20261103T090000", "FREQ=WEEKLY;INTERVAL=2;COUNT=3")
check("INTERVAL=2 weekly", [s.day for _, s in starts(biweekly, D(2026, 11, 1), D(2026, 12, 31))] == [3, 17, 1])
dst = vev("dst", ";TZID=America/Denver:20261030T090000", "FREQ=DAILY;COUNT=5")
got = starts(dst, D(2026, 10, 30), D(2026, 11, 5))
check("across a DST change the local time stays 09:00", [s.hour for _, s in got] == [9] * 5
      and got[0][1].utcoffset() != got[-1][1].utcoffset(), [(s.isoformat()) for _, s in got])
monthly = vev("rent", ";VALUE=DATE:20260131", "FREQ=MONTHLY;COUNT=4")
got = starts(monthly, D(2026, 1, 1), D(2026, 12, 31))
check("MONTHLY on the 31st skips short months (RFC 5545)", [s.isoformat() for _, s in got] == ["2026-01-31", "2026-03-31",
                                                                                                "2026-05-31", "2026-07-31"], got)
firstmon = vev("club", ";TZID=America/Denver:20260105T190000", "FREQ=MONTHLY;BYDAY=1MO")
got = starts(firstmon, D(2026, 11, 1), D(2027, 1, 31))
check("MONTHLY BYDAY=1MO (first Monday)", [s.date().isoformat() for _, s in got] == ["2026-11-02", "2026-12-07", "2027-01-04"], got)
lastfri = vev("pay", ";TZID=America/Denver:20260130T120000", "FREQ=MONTHLY;BYDAY=-1FR")
check("MONTHLY BYDAY=-1FR (last Friday)", [s.day for _, s in starts(lastfri, D(2026, 11, 1), D(2026, 12, 1))] == [27])
yearly = vev("bday", ";VALUE=DATE:19900315", "FREQ=YEARLY")
check("YEARLY from long ago lands on this year", [s.isoformat() for _, s in starts(yearly, D(2026, 1, 1), D(2027, 1, 1))] == ["2026-03-15"])
old = vev("old", ":20100104T150000Z", "FREQ=DAILY")
got = starts(old, D(2026, 11, 26), D(2026, 11, 28))
check("an endless DAILY from 2010 still reaches today (no walk from the start)", len(got) == 2 and got[0][1].day == 26, got)
oldm = vev("oldm", ";TZID=America/Denver:20100115T100000", "FREQ=MONTHLY")
check("an endless MONTHLY from 2010 hits this month exactly once",
      [s.date().isoformat() for _, s in starts(oldm, D(2026, 11, 1), D(2026, 12, 1))] == ["2026-11-15"])
ex = vev("ex", ";TZID=America/Denver:20261123T100000", "FREQ=DAILY;COUNT=4",
         "EXDATE;TZID=America/Denver:20261124T100000\n")
check("EXDATE removes an instance", [s.day for _, s in starts(ex, D(2026, 11, 23), D(2026, 11, 30))] == [23, 25, 26])
ovr = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:mv\nDTSTART;TZID=America/Denver:20261123T100000\nSUMMARY:Weekly 1:1\n"
       "RRULE:FREQ=WEEKLY;COUNT=3\nEND:VEVENT\nBEGIN:VEVENT\nUID:mv\nRECURRENCE-ID;TZID=America/Denver:20261130T100000\n"
       "DTSTART;TZID=America/Denver:20261130T140000\nSUMMARY:Weekly 1:1 (moved)\nEND:VEVENT\nEND:VCALENDAR\n")
got = starts(ovr, D(2026, 11, 23), D(2026, 12, 15))
check("a RECURRENCE-ID override replaces its instance", [(n, s.day, s.hour) for n, s in got] ==
      [("Weekly 1:1", 23, 10), ("Weekly 1:1 (moved)", 30, 14), ("Weekly 1:1", 7, 10)], got)
check("a malformed feed doesn't raise", gcal.parse_ics("garbage\nBEGIN:VEVENT\nDTSTART:nope\nEND:VEVENT") == [])

# ---- URL safety
refused = {}
for url in ("http://cal.example.com/a.ics", "https://127.0.0.1/a.ics", "https://10.1.2.3/a.ics", "https://localhost/a.ics",
            "https://[::1]/a.ics", "https://sneaky.example.com/a.ics", "https://mixed.example.com/a.ics",
            "https://metadata.example.com/latest", "https://mapped.example.com/a.ics", "https://cal.example.com:8443/a.ics",
            "https://user:pw@cal.example.com/a.ics", "https://nowhere.example.net/a.ics", "file:///etc/passwd",
            "https://printer.local/a.ics", "https://svc.railway.internal/a.ics"):
    try:
        gcal.check_url(url)
        refused[url] = False
    except gcal.UnsafeURL:
        refused[url] = True
check("http, private, loopback, link-local, mapped, odd ports, logins and unknown hosts are refused",
      all(refused.values()), [u for u, r in refused.items() if not r])
check("public https and webcal links pass", gcal.check_url("https://cal.example.com/a.ics") == "https://cal.example.com/a.ics"
      and gcal.check_url("webcal://feeds.example.org/x.ics") == "https://feeds.example.org/x.ics")
FEEDS["https://cal.example.com/redirect.ics"] = ("302", "https://sneaky.example.com/x.ics")
try:
    gcal.fetch_ics("https://cal.example.com/redirect.ics")
    redir = False
except gcal.UnsafeURL:
    redir = True
check("a redirect to a private host is refused too", redir and "https://sneaky.example.com/x.ics" not in FETCHES)

# ---- subscription routes
check("calendar routes need sign-in", all(call(p, key=None)[0] == 401 for p in
                                          ("/api/calendar", "/api/calendar/subscriptions", "/api/calendar/settings")))
check("adding events needs sign-in", call("/api/calendar/events", "POST", {"title": "x"}, key=None)[0] == 401)
s, j = call("/api/calendar/subscriptions", "POST", {"url": "https://10.0.0.1/x.ics", "name": "Bad"})
check("POST refuses a private host with a reason", s == 400 and "private" in j["error"], j)
s, j = call("/api/calendar/subscriptions", "POST", {"url": "http://cal.example.com/x.ics"})
check("POST refuses plain http", s == 400 and "https" in j["error"], j)
now = time.time()
soon = datetime.datetime.fromtimestamp(now + 30 * 60, UTC).replace(second=0, microsecond=0)
z = lambda t: t.strftime("%Y%m%dT%H%M%SZ")
today = datetime.datetime.fromtimestamp(now, DEN).date()
FEEDS["https://cal.example.com/team.ics"] = (
    "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:dentist\nDTSTART:" + z(soon) + "\nDTEND:" + z(soon + datetime.timedelta(hours=1))
    + "\nSUMMARY:Dentist\nLOCATION:12 Main St\\, Denver\nEND:VEVENT\n"
    "BEGIN:VEVENT\nUID:call\nDTSTART:" + z(soon + datetime.timedelta(minutes=5)) + "\nSUMMARY:Phone call\nEND:VEVENT\n"
    "BEGIN:VEVENT\nUID:later\nDTSTART:" + z(soon + datetime.timedelta(minutes=80)) + "\nSUMMARY:Later thing\nLOCATION:Cafe\nEND:VEVENT\n"
    "BEGIN:VEVENT\nUID:allday\nDTSTART;VALUE=DATE:" + today.strftime("%Y%m%d") + "\nSUMMARY:Day off\nLOCATION:Home\nEND:VEVENT\n"
    "END:VCALENDAR\n")
s, j = call("/api/calendar/subscriptions", "POST", {"url": "https://cal.example.com/team.ics", "name": "Team"})
check("POST adds a public https calendar with a color", s == 200 and j["subscription"]["name"] == "Team"
      and j["subscription"]["color"].startswith("#"), j)
sid = j["subscription"]["id"]
check("a duplicate is refused", call("/api/calendar/subscriptions", "POST", {"url": "https://cal.example.com/team.ics"})[0] == 409)
s, j = call("/api/calendar/subscriptions")
check("GET lists subscriptions", s == 200 and [x["id"] for x in j["subscriptions"]] == [sid])

# ---- the merged list
FETCHES.clear()
d = today.isoformat()
s, j = call(f"/api/calendar?from={d}&to={(today + datetime.timedelta(days=1)).isoformat()}")
titles = [e["title"] for e in j.get("events", [])]
check("/api/calendar lists the subscription's events", s == 200 and {"Dentist", "Phone call", "Day off"} <= set(titles), j)
ev = next(e for e in j["events"] if e["title"] == "Dentist")
check("event shape {id, title, start, end, all_day, location, source, color}",
      set(ev) >= {"id", "title", "start", "end", "all_day", "location", "source", "color"} and ev["source"] == "Team"
      and ev["location"] == "12 Main St, Denver" and ev["start"].endswith("-07:00") and ev["all_day"] is False, ev)
check("all-day events come first in their day", j["events"][0]["title"] == "Day off" and j["events"][0]["all_day"], titles)
n = len(FETCHES)
call(f"/api/calendar?from={d}&to={d}")
check("the ICS feed is cached (15 min)", len(FETCHES) == n == 1, FETCHES)
check("bad dates are a 400", call("/api/calendar?from=tomorrow")[0] == 400)
check("a backwards range is a 400", call(f"/api/calendar?from={d}&to=2000-01-01")[0] == 400)

# Google merged in when connected (google.list_events stubbed)
real = (google.connected, google.list_events, google.add_event)
GADD = []
google.connected = lambda service=None: True
google.list_events = lambda d0, d1, query=None, limit=100: [
    {"id": "g1", "summary": "Board meeting", "start": {"dateTime": (soon + datetime.timedelta(minutes=10)).isoformat()},
     "end": {"dateTime": (soon + datetime.timedelta(minutes=70)).isoformat()}, "location": "HQ"},
    {"id": "g2", "summary": "gone", "status": "cancelled", "start": {"date": d}, "end": {"date": d}}]
google.add_event = lambda args: GADD.append(args) or {"id": "new", "htmlLink": "https://calendar.google.com/x"}
s, j = call(f"/api/calendar?from={d}&to={d}")
srcs = {e["title"]: (e["source"], e["color"]) for e in j["events"]}
check("Google events merge in, colored by source; cancelled ones are dropped", j["google"] is True
      and srcs.get("Board meeting", ("",))[0] == "Google" and srcs["Board meeting"][1] != srcs["Dentist"][1]
      and "gone" not in srcs, srcs)
s, j = call("/api/calendar/events", "POST", {"title": "Lunch", "date": d, "time": "12:30", "duration": 45, "location": "Cafe"})
check("POST /api/calendar/events adds to Google when connected", s == 200 and j["where"] == "google" and GADD and
      GADD[-1]["start"].startswith(d + "T12:30:00") and GADD[-1]["duration_minutes"] == 45 and GADD[-1]["location"] == "Cafe", (j, GADD))
google.connected, google.list_events, google.add_event = real

s, j = call("/api/calendar/events", "POST", {"title": "Haircut", "date": d, "time": "16:00", "duration": 30})
check("without Google the event is kept in Theta", s == 200 and j["where"] == "theta")
s, j2 = call(f"/api/calendar?from={d}&to={d}")
hc = next((e for e in j2["events"] if e["title"] == "Haircut"), None)
check("and shows in the calendar", hc and hc["source"] == "Theta" and hc["start"].startswith(d + "T16:00")
      and hc["end"].startswith(d + "T16:30"), hc)
check("bad event input is a 400", call("/api/calendar/events", "POST", {"title": "x", "date": d, "time": "25:00"})[0] == 400
      and call("/api/calendar/events", "POST", {"date": d})[0] == 400)
s, j3 = call("/api/calendar/events?id=" + j["id"], "DELETE")
check("an event kept in Theta can be removed", s == 200 and not any(e["title"] == "Haircut" for e in call(f"/api/calendar?from={d}&to={d}")[1]["events"]))

# ---- leave-by heads-ups
check("nudges default on", call("/api/calendar/settings")[1] == {"calendar_nudges": True})
PUSHES.clear()
gcal._last_tick[0] = 0
sent = gcal.tick(now)
check("one heads-up for the event with a place ~30 min out (not the call, the all-day or the later one)",
      len(sent) == 1 and "Dentist" in sent[0]["text"] and "12 Main St, Denver" in sent[0]["text"]
      and "https://www.google.com/maps/dir/" in sent[0]["text"], [m["text"] for m in sent])
check("it's a proactive text plus a push that opens it", sent and sent[0]["meta"]["proactive"] and sent[0]["meta"]["source"] == "calendar"
      and PUSHES and PUSHES[0][2] == f"/?m={sent[0]['id']}", PUSHES)
check("tick waits 5 minutes between looks", gcal.tick(now + 60) == [])
gcal._last_tick[0] = 0
check("the heads-up is deduped (db.seen/mark)", gcal.tick(now + 120) == [] and len(PUSHES) == 1)
gcal._last_tick[0] = 0
sent = gcal.tick(now + 80 * 60)
check("the later event with a place gets its own heads-up when it's near", [m["text"].split(":")[1].strip()[:11] for m in sent] == ["Later thing"],
      [m["text"] for m in sent])
s, j = call("/api/calendar/settings", "POST", {"calendar_nudges": False})
check("the nudges setting turns off", s == 200 and j == {"calendar_nudges": False} and db.get_setting("calendar_nudges") is False)
FEEDS["https://cal.example.com/team.ics"] = FEEDS["https://cal.example.com/team.ics"].replace("UID:dentist", "UID:dentist2")
gcal._cache.clear()
gcal._last_tick[0] = 0
check("with nudges off nothing is sent", gcal.tick(now) == [])
call("/api/calendar/settings", "POST", {"calendar_nudges": True})

# ---- delete a subscription
s, j = call("/api/calendar/subscriptions?id=" + sid, "DELETE")
check("DELETE removes a subscription", s == 200 and call("/api/calendar/subscriptions")[1]["subscriptions"] == [])
check("DELETE of an unknown id is a 404", call("/api/calendar/subscriptions?id=nope", "DELETE")[0] == 404)
FEEDS.clear()
s, j = call("/api/calendar/subscriptions", "POST", {"url": "https://feeds.example.org/broken.ics", "name": "Broken"})
s, j = call(f"/api/calendar?from={d}&to={d}")
check("a feed that fails is reported, and the rest still loads", s == 200 and any("Broken" in p for p in j["problems"]), j)

if FAILED:
    print(f"\n{len(FAILED)} failed: {FAILED}")
    sys.exit(1)
print("\nall calendar checks passed")
