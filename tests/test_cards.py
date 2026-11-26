"""Cards: the kit validates, the weather tool always shows a weather card, tools add event/email/link cards
from their own results (code-made, every time), and 'not connected' errors carry a connect card."""
import io, json, os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_TZ="America/Denver")
from server import db, cards, tools


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
check("a valid link card passes", cards.validate("link", {"url": "https://example.com", "title": "Example"})["site"] == "example.com")
try:
    cards.validate("link", {"url": "http://example.com", "title": "x"}); bad = False
except Exception:
    bad = True
check("non-https links are refused", bad)

GEO = {"results": [{"name": "Denver", "admin1": "Colorado", "latitude": 39.7, "longitude": -105.0}]}
WX = {"current": {"time": "2026-11-26T10:00", "temperature_2m": 41.2, "weather_code": 2},
      "daily": {"temperature_2m_max": [48.4], "temperature_2m_min": [27.9]},
      "hourly": {"time": [f"2026-11-26T{h:02d}:00" for h in range(9, 18)], "temperature_2m": list(range(38, 47)),
                 "weather_code": [2] * 9}}
cards._get_json = lambda url, params, timeout=12: GEO if "geocoding" in url else WX
ctx = {}
out = cards._t_weather({"place": "Denver"}, ctx)
c = ctx["cards"][0]
check("weather always shows a weather card", c["type"] == "weather" and c["place"] == "Denver, Colorado" and c["temp"] == 41
      and c["hi"] == 48 and c["lo"] == 28 and len(c["hourly"]) == 6, c)
check("and the text tells the model not to repeat it", "card is attached" in out)
check("weather is offered to the model", "weather" in [t["name"] for t in tools.specs()])

ctx = {}
cards.auto(ctx, "event", {"title": "Dentist", "start": "2026-11-27T10:30:00-07:00", "end": "2026-11-27T11:30:00-07:00",
                          "location": "Main St"})
check("code-made event card", ctx["cards"][0]["type"] == "event" and ctx["cards"][0]["title"] == "Dentist", ctx)
check("a bad card is skipped, never an error", cards.auto({}, "event", {"title": ""}) is None)

ctx = {}
ok, out = tools.execute("send_email_draft", {"to": "a@b.co", "subject": "x", "body": "y"}, ctx)
card = cards.from_tool_error("send_email_draft", "Gmail isn't connected yet, so nothing was sent.")
check("a not-connected error becomes a connect card", card and card["type"] == "connect" and card.get("service") == "google", card)

import server.google as g
src = open(g.__file__).read()
check("gmail_read, calendar_list and calendar_add make their cards in code", src.count("_auto(ctx,") >= 3)
check("browse_open makes a link card in code", 'cards.auto(ctx, "link"' in open(os.path.join(os.path.dirname(g.__file__), "browser.py")).read())
