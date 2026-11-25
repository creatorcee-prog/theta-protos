"""server/vantage.py: the event rules (ported from theta-app tests/test_vantage_theta.py), getting the picture over
HTTP or from a local checkout, and the NWS reader. Stdlib only, no network: urlopen is stubbed."""
import io
import json
import os
import sys
import tempfile
import time
import urllib.error

sys.dont_write_bytecode = True
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
for k in ("VANTAGE_URL", "VANTAGE_KEY", "VANTAGE_DIR", "VANTAGE_DATA"):
    os.environ.pop(k, None)

from server import vantage as v  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


class FakeDB:
    def __init__(self):
        self.settings = {}

    def get_setting(self, key, default=None):
        return json.loads(json.dumps(self.settings[key])) if key in self.settings else default

    def set_setting(self, key, value):
        self.settings[key] = json.loads(json.dumps(value))


v.db = FakeDB()
NOW = time.time()


def state(**kw):
    s = {"t": NOW, "quakes": [], "stories": [], "theaters": [], "tiles": [], "tsunami": [], "fear": [], "weather": {"hazards": []},
         "odd_trades": {"flags": []}, "attention": None, "world": {"level": "green", "why": []}}
    s.update(kw)
    return s


LOC = {"lat": 35.7, "lon": 139.8}   # what theta-app saves for Tokyo (rounded to 0.1)
q_near = {"id": "q:near", "lat": 35.1, "lon": 139.1, "mag": 6.3, "t": NOW - 600, "title": "M6.3 near Tokyo", "note": "Natural earthquake per USGS."}
q_far = dict(q_near, id="q:far", lat=-40.0, lon=-70.0, mag=5.2, title="M5.2 Chile")

# ---- the rules (the same cases as theta-app)
check("_km: Tokyo to Osaka is about 400 km", 390 < v._km(35.68, 139.77, 34.69, 135.50) < 410)
check("no saved area: nothing near you can fire", v.vantage_events(state(quakes=[q_near]), None, (), NOW) == [])
evs = v.vantage_events(state(quakes=[q_near, q_far]), LOC, (), NOW)
check("a strong quake close to you is Red; a far one is not near you", [(e["id"], e["level"]) for e in evs if e["group"] == "near"] == [("q:near", 4)])
check("the near quake says how far, like theta-app", evs[0]["body"].startswith("M6.3 near Tokyo, about 9") and evs[0]["info"]["km"] == 92)
mid = dict(q_near, id="q:mid", mag=5.4, lat=36.4, lon=139.8, t=NOW - 3 * 3600)
check("M5+ within 150 km in the last day is Orange", [(e["id"], e["level"]) for e in v.vantage_events(state(quakes=[mid]), LOC, (), NOW)] == [("q:mid", 3)])
old_red = dict(q_near, id="q:old", t=NOW - 7 * 3600)
check("a strong close quake 7 h old drops from Red to Orange", [e["level"] for e in v.vantage_events(state(quakes=[old_red]), LOC, (), NOW)] == [3])
NWS = [{"id": "urn:1", "event": "Tornado Warning", "severity": "Extreme", "urgency": "Immediate", "certainty": "Observed", "headline": "Take shelter now"},
       {"id": "urn:2", "event": "Frost Advisory", "severity": "Minor", "urgency": "Expected", "certainty": "Likely", "headline": "x"},
       {"id": "urn:3", "event": "Flood Warning", "severity": "Severe", "urgency": "Expected", "certainty": "Likely", "headline": "Rivers rising"}]
evs = v.vantage_events(state(), LOC, NWS, NOW)
check("an official Extreme and Immediate alert is Red, Severe is Orange, a minor one is not pushed",
      [(e["id"], e["level"]) for e in evs] == [("nws:urn:1", 4), ("nws:urn:3", 3)])
ts_ev = {"id": "tsu:1", "category": "Warning", "level": 3, "title": "Off the coast of Japan", "note": "Hazardous waves.", "lat": 36.0, "lon": 142.0, "t": NOW - 300}
evs = v.vantage_events(state(tsunami=[ts_ev]), LOC, (), NOW)
check("a tsunami warning for your coast is Red, and is also a world event", {(e["group"], e["level"]) for e in evs} == {("near", 4), ("world", 0)})
check("the world tsunami id is stable and distinct from the near one", sorted(e["id"] for e in evs) == ["tsu:1", "wtsu:1"])
adv = dict(ts_ev, id="tsu:2", category="Advisory", level=2)
check("a tsunami advisory near you is Orange and not a world event", [(e["group"], e["level"]) for e in v.vantage_events(state(tsunami=[adv]), LOC, (), NOW)] == [("near", 3)])
storm = {"id": "wx:TC1", "hazard": "TC", "danger": "high", "label": "Tropical cyclone", "title": "Typhoon X", "detail": "176 km/h", "lat": 35.0, "lon": 140.0, "radius_km": 350}
check("being inside a dangerous storm's ring is Orange",
      [(e["kind"], e["level"]) for e in v.vantage_events(state(weather={"hazards": [storm]}), LOC, (), NOW)] == [("hazard", 3)])
check("outside the ring it isn't", v.vantage_events(state(weather={"hazards": [dict(storm, radius_km=10)]}), LOC, (), NOW) == [])
big = {"id": "c:big", "title": "Major attack reported", "conf": "confirmed", "independent": 6, "t": NOW - 3600, "mil": True, "links": [{"url": "https://x/1"}]}
rumor = dict(big, id="c:rumor", conf="rumored", independent=0)
loud_rumor = dict(big, id="c:loud", conf="rumored", independent=9)
evs = v.vantage_events(state(stories=[big, rumor, loud_rumor]), None, (), NOW)
check("a story six outlets carry is a world event linking to the story; a rumor never is, however loud",
      [(e["id"], e["url"]) for e in evs] == [("c:big", "https://x/1")])
check("four outlets is not enough for the world", v.vantage_events(state(stories=[dict(big, independent=4)]), None, (), NOW) == [])
check("a market shock is a world event, with a stable per-day id",
      [(e["kind"], e["id"]) for e in v.vantage_events(state(fear=[{"sym": "^VIX", "label": "VIX", "d1": 31.0}]), None, (), NOW)]
      == [("market", "mkt:^VIX:" + time.strftime("%Y-%m-%d", time.gmtime(NOW)))])
check("a small VIX move is not", v.vantage_events(state(fear=[{"sym": "^VIX", "label": "VIX", "d1": 9.0}]), None, (), NOW) == [])
check("M7+ anywhere is a world event", [(e["group"], e["kind"]) for e in v.vantage_events(state(quakes=[dict(q_far, mag=7.4)]), None, (), NOW)] == [("world", "major")])
th = {"id": "eastmed", "name": "the Eastern Mediterranean", "state": "high", "lat": 34.0, "lon": 33.0, "z": 4.1}
evs = v.vantage_events(state(theaters=[th]), None, (), NOW)
check("a region far above normal is a world event", [(e["kind"], e["id"].startswith("high:eastmed:")) for e in evs] == [("region", True)])
cyprus = {"lat": 35.0, "lon": 33.4}
conf = dict(big, id="c:mil", region="eastmed", independent=3)
evs = v.vantage_events(state(theaters=[th], stories=[conf]), cyprus, (), NOW)
check("military activity near you needs the theater high AND 3+ outlets confirming",
      [e["kind"] for e in evs if e["group"] == "near"] == ["military"]
      and [e["kind"] for e in v.vantage_events(state(theaters=[th], stories=[dict(conf, independent=2)]), cyprus, (), NOW) if e["group"] == "near"] == [])
check("severe space weather is near-you Orange", [(e["kind"], e["level"]) for e in v.vantage_events(state(tiles=[{"id": "space", "state": "bad"}]), LOC, (), NOW)] == [("space", 3)])
check("an odd trade only reaches the noisy group",
      [e["group"] for e in v.vantage_events(state(odd_trades={"flags": [{"score": 6, "title": "Will X resign?", "outcome": "Yes", "cash": 90000, "t": 1, "url": "u"}]}), None, (), NOW)] == ["noisy"])
check("the rules are pure: the same picture gives the same ids", [e["id"] for e in v.vantage_events(state(quakes=[q_near], stories=[big]), LOC, NWS, NOW)]
      == [e["id"] for e in v.vantage_events(state(quakes=[q_near], stories=[big]), LOC, NWS, NOW)])

# ---- getting the picture
s, why = v.get_state(NOW)
check("neither VANTAGE_URL nor VANTAGE_DIR: None, with a reason", s is None and "not configured" in why)

CALLS = []


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=None):
    CALLS.append((req.full_url, {k.lower(): val for k, val in req.header_items()}, timeout))
    if "weather.gov" in req.full_url:
        return Resp(json.dumps({"features": [{"properties": {"id": "urn:9", "event": "Tornado Warning", "severity": "Extreme",
                                                              "urgency": "Immediate", "certainty": "Observed", "headline": "Take shelter"}}]}).encode())
    return Resp(json.dumps(dict(state(quakes=[q_near]), milair={"ac": list(range(5000))}, bases=[1] * 100)).encode())


v.urllib.request.urlopen = fake_urlopen
os.environ.update(VANTAGE_URL="https://theta.example/vantage/", VANTAGE_KEY="dk")
s, why = v.get_state(NOW)
url, hdrs, timeout = CALLS[-1]
check("over HTTP: GET {VANTAGE_URL}/api/state", s is not None and why is None and url == "https://theta.example/vantage/api/state")
check("with x-dashboard-key: VANTAGE_KEY and a 20 s timeout", hdrs.get("x-dashboard-key") == "dk" and timeout == 20)
check("only what the rules need is kept (not the aircraft or bases)", "milair" not in s and "bases" not in s and s["quakes"][0]["id"] == "q:near")
n = len(CALLS)
v.get_state(NOW + 200)
check("cached for 4 minutes in db settings", len(CALLS) == n and v.db.get_setting("vantage_state")["src"] == "https://theta.example/vantage")
v.get_state(NOW + 250)
check("and fetched again after", len(CALLS) == n + 1)


def refuse(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))


v.urllib.request.urlopen = refuse
s, why = v.get_state(NOW + 1000)
check("a wrong key: None, and the reason names VANTAGE_KEY", s is None and "VANTAGE_KEY" in why)
v.urllib.request.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(OSError("down"))
check("Vantage down: None with a reason, never an exception", v.get_state(NOW + 2000)[0] is None and "did not answer" in v.REASON)

# ---- local checkout (VANTAGE_DIR)
tmp = tempfile.mkdtemp()
vdir = os.path.join(tmp, "vantage")
os.makedirs(vdir)
open(os.path.join(vdir, "core.py"), "w").write(
    "class Store:\n    def __init__(self, path=None):\n        self.path = path\n"
    "_S = None\ndef set_store(s):\n    global _S\n    _S = s\ndef store():\n    return _S\n")
open(os.path.join(vdir, "app.py"), "w").write(
    "import time\nKEY = 'secret'\nCALLS = []\n"
    "def safe_state():\n    CALLS.append(1)\n    return {'t': time.time(), 'quakes': [], 'stories': [], 'world': {'level': 'green'}, 'milair': {}}\n")
open(os.path.join(vdir, "forecast.py"), "w").write("GRADED = []\ndef grade():\n    GRADED.append(1)\n")
os.environ["VANTAGE_DIR"] = vdir
os.environ["PROTOS_DATA"] = os.path.join(tmp, "data")
v.db = FakeDB()
s, why = v.get_state(NOW)
check("VANTAGE_DIR: imports the checkout and calls app.safe_state() (it wins over VANTAGE_URL)",
      s is not None and why is None and v._LOCAL["app"].CALLS == [1] and "milair" not in s)
check("local Vantage keeps its files under $PROTOS_DATA/vantage, grades forecasts, and has no sign-in in-process",
      v._LOCAL["core"].store().path == os.path.join(tmp, "data", "vantage") and v._LOCAL["forecast"].GRADED == [1] and v._LOCAL["app"].KEY == "")
v.get_state(NOW + 60)
check("local picture is cached 4 minutes too", v._LOCAL["app"].CALLS == [1])
v._LOCAL["app"].safe_state = lambda: 1 / 0
check("a local failure: None with a reason", v.get_state(NOW + 600)[0] is None and "ZeroDivisionError" in v.REASON)
for k in ("VANTAGE_DIR", "VANTAGE_URL", "VANTAGE_KEY", "PROTOS_DATA"):
    os.environ.pop(k, None)

# ---- NWS alerts
v.urllib.request.urlopen = fake_urlopen
CALLS.clear()
al = v.nws_alerts({"lat": 39.74, "lon": -104.99}, NOW)
url, hdrs, timeout = CALLS[-1]
check("NWS: alerts/active?point=lat,lon", url == "https://api.weather.gov/alerts/active?point=39.74,-104.99")
check("NWS: sends a User-Agent (api.weather.gov refuses requests without one)", hdrs.get("user-agent") == "theta-protos (personal)")
check("NWS: parsed into the shape the rules read", al == [{"id": "urn:9", "event": "Tornado Warning", "severity": "Extreme", "urgency": "Immediate",
                                                           "certainty": "Observed", "headline": "Take shelter"}])
v.nws_alerts({"lat": 39.74, "lon": -104.99}, NOW + 100)
check("NWS: cached 5 minutes for the same point", len(CALLS) == 1)
v.urllib.request.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(OSError("outside the US"))
check("NWS down or outside the US: no alerts, not an error", v.nws_alerts({"lat": 1.0, "lon": 2.0}, NOW) == [])
check("no saved area: no NWS call at all", v.nws_alerts(None, NOW) == [])

# ---- events(): all together
v.get_state = lambda now=None: (state(quakes=[q_near]), None)
v.nws_alerts = lambda loc, now=None: NWS[:1]
evs, s, why = v.events(NOW, LOC)
check("events(): the picture and the official alerts through the rules", why is None and [e["id"] for e in evs] == ["q:near", "nws:urn:1"])
v.get_state = lambda now=None: (None, "Vantage is not configured")
check("events() without Vantage: no events, and the reason", v.events(NOW, LOC) == ([], None, "Vantage is not configured"))
print("all vantage bridge tests passed")
