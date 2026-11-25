"""The bridge to Vantage: its picture in, events out (near you / the world).

Vantage lives inside Theta (theta-app, vantage/). protos reads its state one of two ways:
  - over HTTP: GET {VANTAGE_URL}/api/state with the header x-dashboard-key: VANTAGE_KEY (Theta's dashboard key).
    VANTAGE_URL is e.g. https://<theta>/vantage. Cached 4 minutes in db settings.
  - locally: VANTAGE_DIR points at a theta-app checkout's vantage/ folder; it is imported and app.safe_state()
    is called in this process (its files go to $PROTOS_DATA/vantage unless VANTAGE_DATA says otherwise).
With neither, get_state() returns (None, reason).

`vantage_events()` is a faithful port of theta-app api/_parts/vantage.py vantage_events(): the same levels
(4 = Red, 3 = Orange, 0 = information), distances, world rules and ids. Rumors never get here. Each event also
carries `info` (magnitude, km, age...) so proactive.py can write a text like a friend would, not raw data."""
import json
import math
import os
import sys
import time
import urllib.request

db = None            # server.db, loaded on first use; tests put a fake here
STATE_TTL = 240      # seconds: the picture is cached 4 minutes
NWS_TTL = 300        # seconds: official alerts are cached 5 minutes
USER_AGENT = "theta-protos (personal)"   # api.weather.gov refuses requests without a User-Agent
REASON = None        # why the last get_state() returned None
_LOCAL = {}


def _db():
    global db
    if db is None:
        from server import db as real
        db = real
    return db


def _base():
    return os.environ.get("VANTAGE_URL", "").strip().rstrip("/")


def page_url():
    """Where an event links: the Vantage page, if we know it."""
    return (_base() or "/vantage") + "/"


def _km(a, b, c, d):
    p1, p2 = math.radians(a), math.radians(c)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(x)))


# ---------------------------------------------------------------- the rules (pure, no I/O)
def vantage_events(s, loc=None, nws=(), now=None):
    """Every event the picture `s` calls for right now: [{id, group, level, kind, title, body, url, info}].
    Pure (no I/O), so it can be tested; level 4 = Red, 3 = Orange, 0 = information. Rumors never get here."""
    now = now or time.time()
    url, out = page_url(), []

    def ev(id_, group, level, kind, title, body, link=None, **info):
        out.append({"id": id_, "group": group, "level": level, "kind": kind, "title": title[:120], "body": body[:220],
                    "url": link or url, "info": info})
    quakes, hz = s.get("quakes") or [], (s.get("weather") or {}).get("hazards") or []
    stories = [c for c in s.get("stories") or [] if c.get("conf") != "rumored"]
    # ---- near you
    if loc:
        la, lo = loc["lat"], loc["lon"]
        for q in quakes:
            d, age = _km(la, lo, q["lat"], q["lon"]), (now - q["t"]) / 3600
            lvl = 4 if q["mag"] >= 6 and d <= 100 and age <= 6 else 3 if q["mag"] >= 5 and d <= 150 and age <= 24 else 0
            if lvl:
                ev(q["id"], "near", lvl, "quake", q["title"], f"{q['title']}, about {round(d)} km from you. {q.get('note', '')}",
                   mag=q["mag"], km=round(d), t=q["t"], place=q["title"])
        for e in s.get("tsunami") or []:
            if e.get("level", 0) >= 2 and now - (e.get("t") or 0) < 24 * 3600 and _km(la, lo, e["lat"], e["lon"]) <= 1500:
                ev(e["id"], "near", 4 if e["level"] == 3 else 3, "tsunami", f"Tsunami {e['category'].lower()}",
                   f"Tsunami {e['category'].lower()}: {e['title']}. {e.get('note', '')} Follow local officials.",
                   category=e["category"].lower(), where=e["title"], km=round(_km(la, lo, e["lat"], e["lon"])))
        for a in nws:
            lvl = 4 if a["severity"] == "Extreme" and (a["urgency"] == "Immediate" or a["certainty"] == "Observed") else \
                3 if a["severity"] in ("Extreme", "Severe") else 0
            if lvl and a["id"]:
                ev("nws:" + a["id"], "near", lvl, "official", a["event"], f"Official alert at your area: {a['event']}. {a['headline']}",
                   event=a["event"], headline=a["headline"])
        for h_ in hz:
            if h_.get("danger") == "high" and h_.get("hazard") in ("TC", "VO") and _km(la, lo, h_["lat"], h_["lon"]) <= h_.get("radius_km", 0):
                ev(h_["id"], "near", 3, "hazard", f"{h_['label']}: {h_['title']}", f"You are inside the danger area of {h_['title']} ({h_['detail']}).",
                   label=h_["label"], name=h_["title"], detail=h_["detail"])
        for t in s.get("theaters") or []:
            if t.get("state") == "high" and _km(la, lo, t["lat"], t["lon"]) <= 1200 and any(
                    c.get("region") == t["id"] and c.get("mil") and c.get("independent", 0) >= 3 and now - c["t"] < 86400 for c in stories):
                ev("near-mil:%s:%s" % (t["id"], time.strftime("%Y-%m-%d", time.gmtime(now))), "near", 3, "military",
                   "Military activity in your region", f"Military air activity over {t['name']} is far above normal, and outlets confirm something there.",
                   name=t["name"])
        sp = next((x for x in s.get("tiles") or [] if x.get("id") == "space"), None)
        if sp and sp.get("state") == "bad":
            ev("near-space:" + time.strftime("%Y-%m-%d", time.gmtime(now)), "near", 3, "space", "Severe geomagnetic storm",
               "A severe geomagnetic storm (Kp 7+) is under way. GPS and power can be disturbed.")
    # ---- the world
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    for c in stories:
        if c.get("independent", 0) >= 5 and now - c["t"] < 24 * 3600:
            ev(c["id"], "world", 0, "major", "Widely reported", f"{c['title']} ({c['independent']} independent outlets)",
               (c.get("links") or [{}])[0].get("url"), story=c["title"], outlets=c["independent"])
    for q in quakes:
        if q["mag"] >= 7 and now - q["t"] < 24 * 3600:
            ev(q["id"], "world", 0, "major", q["title"], f"{q['title']}. {q.get('note', '')}", mag=q["mag"], t=q["t"], place=q["title"])
    for t in s.get("theaters") or []:
        if t.get("state") == "high":
            ev(f"high:{t['id']}:{day}", "world", 0, "region", "Far above normal",
               f"Military air activity over {t['name']} is far above its normal (z {t.get('z')}).", name=t["name"])
    for e in s.get("tsunami") or []:
        if e.get("level") == 3 and now - (e.get("t") or 0) < 24 * 3600:
            ev("w" + e["id"], "world", 0, "tsunami", "Tsunami warning", f"Tsunami warning: {e['title']}.", where=e["title"])
    for f in s.get("fear") or []:
        big = {"^VIX": 25, "CL=F": 8, "GC=F": 8}.get(f.get("sym"))
        if big and f.get("d1", 0) >= big:
            ev(f"mkt:{f['sym']}:{day}", "world", 0, "market", "Market shock", f"{f['label']} is up {f['d1']:.0f}% in a day. Markets are pricing in risk.",
               label=f["label"], d1=f["d1"])
    # ---- noisy (theta-app keeps this group off by default; protos never texts it, see proactive.py)
    for f in (s.get("odd_trades") or {}).get("flags") or []:
        if f.get("score", 0) >= 5:
            ev("odd:%s:%s" % (f["title"][:40], f.get("t")), "noisy", 0, "trade", "Unusual trade",
               f"${f['cash']:,} on “{f['outcome']}” in “{f['title']}”. Unusual, not proof of anything.", f.get("url"))
    cy = next((x for x in s.get("tiles") or [] if x.get("id") == "cyber"), None)
    if cy and cy.get("state") in ("warn", "bad"):
        ev(f"cyber:{day}", "noisy", 0, "cyber", "Cyber threat level up", f"The internet threat level is {cy.get('value')}.")
    for r in (s.get("attention") or {}).get("more") or []:
        if r.get("z", 0) >= 4:
            ev(f"press:{r['name']}:{day}", "noisy", 0, "press", "Press swing", f"{r['name']} is in {r['now']} stories today, against {r.get('usual')} usually.")
    return out


# ---------------------------------------------------------------- getting the picture
# Only what the rules and the brief read is cached (the full state is several hundred KB).
_KEEP = ("t", "world", "quakes", "stories", "theaters", "tiles", "tsunami", "fear", "weather", "odd_trades", "attention",
         "degraded", "feeds")


def _slim(s):
    out = {k: s.get(k) for k in _KEEP if k in s}
    if isinstance(out.get("weather"), dict):
        out["weather"] = {"hazards": out["weather"].get("hazards") or []}
    return out


def fetch_state(now=None):
    """Vantage's picture over HTTP (cached 4 minutes in db settings), or None. REASON says why when None."""
    global REASON
    now = now or time.time()
    base = _base()
    if not base:
        REASON = "VANTAGE_URL is not set"
        return None
    hit = _db().get_setting("vantage_state") or {}
    if hit.get("at", 0) > now - STATE_TTL and hit.get("src") == base and hit.get("s"):
        return hit["s"]
    req = urllib.request.Request(base + "/api/state", headers={"x-dashboard-key": os.environ.get("VANTAGE_KEY", ""),
                                                               "Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            s = json.loads(r.read())
    except Exception as e:  # noqa: BLE001  Vantage down or the key is wrong: no events this round
        code = getattr(e, "code", None)
        REASON = ("Vantage refused the key (401): check VANTAGE_KEY" if code == 401 else
                  f"Vantage did not answer: {type(e).__name__}: {str(e)[:120]}")
        return None
    if not isinstance(s, dict):
        REASON = "Vantage answered with something that is not a state"
        return None
    s = _slim(s)
    _db().set_setting("vantage_state", {"at": now, "src": base, "s": s})
    REASON = None
    return s


def _local_mods():
    """Vantage's modules from VANTAGE_DIR, loaded once. Raises if they can't be loaded."""
    if _LOCAL:
        return _LOCAL
    import importlib
    vdir = os.path.abspath(os.path.expanduser(os.environ["VANTAGE_DIR"]))
    if vdir not in sys.path:
        sys.path.append(vdir)   # appended: none of Vantage's module names can shadow ours
    mods = {n: importlib.import_module(n) for n in ("core", "app")}
    try:
        mods["forecast"] = importlib.import_module("forecast")
    except Exception:  # noqa: BLE001
        pass
    if not os.environ.get("VANTAGE_DATA"):
        data = os.environ.get("PROTOS_DATA") or "data"
        mods["core"].set_store(mods["core"].Store(os.path.join(data, "vantage")))
    mods["app"].KEY = ""   # in-process: no sign-in
    _LOCAL.update(mods)
    return _LOCAL


def local_state(now=None):
    """Vantage's picture from a local checkout (VANTAGE_DIR): app.safe_state(), cached 4 minutes. Or None."""
    global REASON
    now = now or time.time()
    hit = _db().get_setting("vantage_state") or {}
    if hit.get("at", 0) > now - STATE_TTL and hit.get("src") == "local" and hit.get("s"):
        return hit["s"]
    try:
        mods = _local_mods()
        s = mods["app"].safe_state()
        if mods.get("forecast"):
            try:
                mods["forecast"].grade()   # keeps Vantage's scorecard and baselines growing, as Theta's tick does
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        REASON = f"local Vantage failed: {type(e).__name__}: {str(e)[:120]}"
        return None
    s = _slim(s)
    _db().set_setting("vantage_state", {"at": now, "src": "local", "s": s})
    REASON = None
    return s


def get_state(now=None):
    """(state, None), or (None, reason). VANTAGE_DIR (local) wins over VANTAGE_URL (HTTP)."""
    global REASON
    if os.environ.get("VANTAGE_DIR"):
        s = local_state(now)
    elif _base():
        s = fetch_state(now)
    else:
        REASON = "Vantage is not configured: set VANTAGE_URL (+ VANTAGE_KEY) or VANTAGE_DIR"
        s = None
    return s, (None if s else REASON)


# ---------------------------------------------------------------- official alerts (US only)
def nws_alerts(loc, now=None):
    """Official alerts at the saved point (US National Weather Service; empty elsewhere). Cached 5 minutes."""
    now = now or time.time()
    if not loc:
        return []
    where = [round(float(loc["lat"]), 4), round(float(loc["lon"]), 4)]
    hit = _db().get_setting("vantage_nws") or {}
    if hit.get("at", 0) > now - NWS_TTL and hit.get("where") == where:
        return hit.get("alerts") or []
    try:
        req = urllib.request.Request(f"https://api.weather.gov/alerts/active?point={where[0]},{where[1]}",
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        alerts = [{"id": str(f["properties"].get("id") or ""), "event": f["properties"].get("event") or "",
                   "severity": f["properties"].get("severity") or "", "urgency": f["properties"].get("urgency") or "",
                   "certainty": f["properties"].get("certainty") or "", "headline": (f["properties"].get("headline") or "")[:200]}
                  for f in d.get("features") or [] if f.get("properties")]
    except Exception:  # noqa: BLE001  outside the US, or the service is down: no official alerts, not an error
        alerts = []
    _db().set_setting("vantage_nws", {"at": now, "where": where, "alerts": alerts})
    return alerts


def events(now=None, loc=None):
    """Fetch the picture and official alerts and apply the rules: (events, state, reason)."""
    s, why = get_state(now)
    if not s:
        return [], None, why
    nws = nws_alerts(loc, now) if loc else []
    return vantage_events(s, loc, nws, now), s, None
