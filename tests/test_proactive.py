"""server/proactive.py: Theta texts first. Dedupe, the daily cap, quiet hours vs Red, "proactive": false, world kinds
once a day, the 7:00 and 18:00 briefs, and how the texts read. Stdlib only, no network: the Vantage picture and the
push are stubbed (the real rules in server/vantage.py and the real quiet-hours logic in server/push.py are used)."""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

sys.dont_write_bytecode = True
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
for k in ("VANTAGE_URL", "VANTAGE_KEY", "VANTAGE_DIR", "PROTOS_TZ", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
          "GROQ_API_KEY", "LOCAL_LLM_URL", "PROTOS_LOCAL_FIRST"):
    os.environ.pop(k, None)

from server import proactive as p, push, vantage  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


class FakeDB:
    def __init__(self):
        self.msgs, self.settings, self.marks = [], {}, {}

    def add_message(self, bot, role, text, meta=None):
        m = {"id": len(self.msgs) + 1, "bot": bot, "role": role, "text": text, "t": int(time.time()), "meta": dict(meta or {})}
        self.msgs.append(m)
        return dict(m)

    def get_setting(self, key, default=None):
        return json.loads(json.dumps(self.settings[key])) if key in self.settings else default

    def set_setting(self, key, value):
        self.settings[key] = json.loads(json.dumps(value))

    def seen(self, key):
        return key in self.marks

    def mark(self, key, ttl_days=7):
        self.marks[key] = ttl_days


PUSHED = []


def fresh(**settings):
    d = FakeDB()
    d.settings.update({"tz": "UTC", "quiet": [22, 7], "loc": {"lat": 35.7, "lon": 139.8}})
    d.settings.update(settings)
    p.db = push.db = vantage.db = d
    PUSHED.clear()
    return d


def fake_notify(title, body, url="/", urgent=False, now=None):
    PUSHED.append((title, body, url, urgent))
    return 1


p.push, p.vantage = push, vantage
push.notify = fake_notify
PIC = {"s": None, "nws": []}
vantage.get_state = lambda now=None: (PIC["s"], None if PIC["s"] else "Vantage is not configured")
vantage.nws_alerts = lambda loc, now=None: list(PIC["nws"])


def at(day, hour, minute=5):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc).timestamp()


def state(now, **kw):
    s = {"t": now, "quakes": [], "stories": [], "theaters": [], "tiles": [], "tsunami": [], "fear": [], "weather": {"hazards": []},
         "odd_trades": {"flags": []}, "attention": None, "world": {"level": "green", "why": []}}
    s.update(kw)
    return s


def quake(id_, now, mag, lat, lon, ago_min, place="10 km SW of Hachioji, Japan"):
    return {"id": id_, "lat": lat, "lon": lon, "mag": mag, "t": now - ago_min * 60, "title": f"M{mag:.1f} {place}",
            "note": "Natural earthquake per USGS."}


def story(id_, now, title, n=6):
    return {"id": id_, "title": title, "conf": "confirmed", "independent": n, "t": now - 3600, "mil": False, "links": [{"url": "https://x/" + id_}]}


# ---- Red wakes you; Orange waits out quiet hours
NIGHT = at(25, 3)
d = fresh()
PIC["s"] = state(NIGHT, quakes=[quake("q:red", NIGHT, 6.4, 35.4, 139.6, 4), quake("q:orange", NIGHT, 5.4, 36.4, 139.8, 12)])
sent = p.run(NIGHT)
check("3 AM, quiet hours: Red near you goes out at once", [m["meta"]["level"] for m in sent] == [4])
check("as a stored assistant message marked proactive, from Vantage",
      d.msgs[0]["bot"] == "theta" and d.msgs[0]["role"] == "assistant" and d.msgs[0]["meta"] == {"proactive": True, "source": "vantage", "level": 4})
check("and an urgent push linking to the message", PUSHED == [("Theta", d.msgs[0]["text"], "/?m=1", True)])
check("Red reads like a friend texting, short first",
      d.msgs[0]["text"].startswith("Heads up: M6.4 quake 38 km from you, 4 min ago") and "aftershocks" in d.msgs[0]["text"]
      and "Natural earthquake per USGS" not in d.msgs[0]["text"])
check("Orange waits (not sent, not marked)", len(d.msgs) == 1 and not d.seen("vantage:q:orange") and p.LAST["held"] == 1)
check("the same Red is never sent twice", p.run(NIGHT + 300) == [] and len(d.msgs) == 1)
SEVEN = at(25, 7, 2)
PIC["s"] = state(SEVEN, quakes=PIC["s"]["quakes"])
sent = p.run(SEVEN)
check("when quiet hours end, Orange goes out, as a plain (non-urgent) push",
      [m["meta"]["source"] for m in sent] == ["vantage", "brief"] and sent[0]["meta"]["level"] == 3 and PUSHED[1][3] is False)
check("Orange text: 'Heads up: M5.4 quake 78 km from you, ... You're fine where you are, but expect aftershocks.'",
      sent[0]["text"] == "Heads up: M5.4 quake 78 km from you, 4 h ago (10 km SW of Hachioji, Japan). You're fine where you are, but expect aftershocks.")

# ---- briefs at 7 and 18
check("the morning brief at 7: one short line, says what moved", sent[1]["text"].startswith("Morning. 2 things moved: M6.4 quake 38 km from you")
      and sent[1]["meta"] == {"proactive": True, "source": "brief", "level": 0} and len(sent[1]["text"]) < 200)
check("only once in that hour", p.run(SEVEN + 1800) == [])
d = fresh()
EVE = at(25, 18, 1)
PIC["s"] = state(EVE)
sent = p.run(EVE)
check("the evening brief at 18:00 on a calm day: all quiet", [m["text"] for m in sent] == ["Evening. All quiet: nothing moved outside its normal range."]
      and PUSHED[-1][2] == "/?m=1")
check("no brief at other hours", p.run(at(25, 9)) == [] and p.run(at(25, 19)) == [] and p.brief_slot(at(25, 12)) is None)
d = fresh(tz="America/Denver")   # 14:05 UTC is 07:05 in Denver
check("briefs follow your time zone", p.brief_slot(at(25, 14)) == "2026-11-25 morning" and p.brief_slot(at(25, 7)) is None)
d = fresh()
PIC["s"] = None
check("no Vantage picture: no brief (nothing honest to say) and no crash", p.run(at(26, 7)) == [] and "skipped" in p.LAST["brief"])

# ---- the brief in Theta's voice, when there's a model
from server import models, router  # noqa: E402
d = fresh()
PIC["s"] = state(at(26, 18))
real_cands, real_complete = router.candidates, models.complete
router.candidates = lambda tier: [("deepseek", "deepseek-chat")] if tier == "quick" else []
ASKED = []
models.complete = lambda provider, model, msgs, max_tokens=1024: ASKED.append((provider, msgs)) or "Evening! Quiet one out there, nothing moved."
sent = p.run(at(26, 18))
check("with a quick model, the brief is phrased in Theta's voice (persona system prompt)",
      sent[0]["text"] == "Evening! Quiet one out there, nothing moved." and ASKED[0][0] == "deepseek" and ASKED[0][1][0]["role"] == "system"
      and "All quiet" in ASKED[0][1][1]["content"])
models.complete = lambda *a, **k: (_ for _ in ()).throw(models.ModelError("down"))
d = fresh()
check("the model failing falls back to the plain line", p.run(at(26, 18))[0]["text"].startswith("Evening. All quiet"))
router.candidates, models.complete = real_cands, real_complete

# ---- world: each kind once a day; rumors never; the noisy group never
NOON = at(25, 12)
d = fresh(loc=None)
rumor = dict(story("c:rumor", NOON, "Unconfirmed claim", 9), conf="rumored")
PIC["s"] = state(NOON, stories=[story("c:a", NOON, "Talks collapse in Geneva"), story("c:b", NOON, "Second big story"), rumor],
                 fear=[{"sym": "^VIX", "label": "VIX", "d1": 31.0}],
                 odd_trades={"flags": [{"score": 9, "title": "Will X resign?", "outcome": "Yes", "cash": 90000, "t": 1, "url": "u"}]})
sent = p.run(NOON)
check("one big story and one market shock: each world kind once a day", [m["text"] for m in sent] ==
      ["Big one: Talks collapse in Geneva. 6 outlets are carrying it.", "Markets are spooked: VIX is up 31% today."])
check("world events never wake you: plain pushes", all(not x[3] for x in PUSHED))
check("the second story the same day waits for another day; the rumor and the odd trade never go",
      not d.seen("vantage:c:b") and p.run(NOON + 600) == [] and all("Unconfirmed" not in m["text"] and "resign" not in m["text"] for m in d.msgs))
D2 = at(26, 6)   # 06:05 the next day, still quiet hours: it waits; at 7 it goes, with the brief
PIC["s"] = state(D2 + 3600, stories=[story("c:a", D2 + 3600, "Talks collapse in Geneva"), story("c:b", D2 + 3600, "Second big story")])
check("quiet hours hold world events too", p.run(D2) == [])
sent = [m for m in p.run(D2 + 3600) if m["meta"]["source"] == "vantage"]
check("the next day, the next story of that kind can go", [m["text"] for m in sent] == ["Big one: Second big story. 6 outlets are carrying it."])

# ---- the daily cap
d = fresh(proactive_cap=2, loc={"lat": 35.7, "lon": 139.8})
PIC["s"] = state(NOON, stories=[story("c:a", NOON, "Story A")], fear=[{"sym": "^VIX", "label": "VIX", "d1": 31.0}],
                 quakes=[quake("q:o1", NOON, 5.2, 36.3, 139.8, 30), quake("q:big", NOON, 7.3, -20.0, -70.0, 60, "off Chile")])
sent = p.run(NOON)
check("cap 2: only two non-Red messages a day; the rest are dropped, not saved for tomorrow",
      [m["meta"]["level"] for m in sent] == [3, 0] and p.LAST["dropped"] == 1 and d.seen("vantage:mkt:^VIX:2026-11-25") and d.settings["proactive_count"]["n"] == 2)
PIC["s"]["quakes"].append(quake("q:red2", NOON, 6.6, 35.6, 139.7, 2))
sent = p.run(NOON + 300)
check("Red is exempt from the cap (and doesn't count toward it)", [m["meta"]["level"] for m in sent] == [4] and d.settings["proactive_count"]["n"] == 2)
d.settings["proactive_count"] = {"day": "2026-11-24", "n": 6}
check("the count is per day (yesterday's doesn't block today)", p._count(NOON) == ("2026-11-25", 0))
d = fresh()
PIC["s"] = state(NOON, quakes=[quake(f"q:{i}", NOON, 5.1, 36.3, 139.8, 10 + i) for i in range(8)])
check("the default cap is 6 a day", len(p.run(NOON)) == 6 and p.LAST["dropped"] == 2 and p.run(NOON + 300) == [])

# ---- "proactive": false turns it all off except Red
d = fresh(proactive=False)
PIC["s"] = state(SEVEN, stories=[story("c:a", SEVEN, "Story A")],
                 quakes=[quake("q:o", SEVEN, 5.2, 36.3, 139.8, 30), quake("q:r", SEVEN, 6.2, 35.6, 139.7, 3)])
sent = p.run(SEVEN)
check("proactive off: only Red goes out (no Orange, no world, no brief)", [m["meta"]["level"] for m in sent] == [4] and PUSHED[0][3] is True)
d.settings["proactive"] = True
check("turning it back on doesn't dump the backlog", p.run(SEVEN + 300) == [])

# ---- other near-you texts read like texts
NOW = at(25, 12)
ev = {"group": "near", "level": 4, "kind": "official", "title": "", "body": "", "info": {"event": "Tornado Warning", "headline": "Take shelter now"}}
check("official alert", p.phrase(ev, NOW) == "Urgent: Tornado Warning for your area. Take shelter now.")
ev = {"group": "near", "level": 4, "kind": "tsunami", "title": "", "body": "", "info": {"category": "warning", "where": "Off the coast of Japan"}}
check("tsunami warning", p.phrase(ev, NOW).startswith("Tsunami warning for your coast: Off the coast of Japan. Get away from the shore"))
check("push bodies are trimmed on a word", p.short("word " * 100).endswith("…") and len(p.short("word " * 100)) <= 180)

# ---- against the real server.db (the interface in docs/SPEC.md)
from server import db as realdb  # noqa: E402
tmp = tempfile.mkdtemp()
realdb.init(os.path.join(tmp, "protos.db"))
p.db = push.db = vantage.db = realdb
realdb.set_setting("tz", "UTC")
realdb.set_setting("loc", {"lat": 35.7, "lon": 139.8})
PUSHED.clear()
PIC["s"] = state(NIGHT, quakes=[quake("q:real", NIGHT, 6.4, 35.4, 139.6, 4)])
sent = p.run(NIGHT)
check("with the real db: stored, readable from the inbox, deduped", len(sent) == 1 and realdb.since(0)[-1]["meta"]["proactive"] is True
      and realdb.seen("vantage:q:real") and p.run(NIGHT + 60) == [] and PUSHED[0][2] == f"/?m={sent[0]['id']}")
print("all proactive tests passed")
