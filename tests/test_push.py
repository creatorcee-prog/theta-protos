"""server/push.py: VAPID keys, subscriptions, quiet hours vs urgent, dropping dead subscriptions. Stdlib only, no
network: pywebpush, py_vapid and the P-256 maths are stubbed, so this runs without them installed."""
import json
import os
import sys
import types
from datetime import datetime, timezone

sys.dont_write_bytecode = True
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
for k in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT", "PROTOS_TZ"):
    os.environ.pop(k, None)

from server import push  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


class FakeDB:
    def __init__(self):
        self.settings, self.subs = {}, {}

    def get_setting(self, key, default=None):
        return json.loads(json.dumps(self.settings[key])) if key in self.settings else default

    def set_setting(self, key, value):
        self.settings[key] = json.loads(json.dumps(value))

    def add_push_sub(self, sub):
        self.subs[sub["endpoint"]] = sub

    def push_subs(self):
        return list(self.subs.values())

    def drop_push_sub(self, endpoint):
        self.subs.pop(endpoint, None)


push.db = FakeDB()
push.db.set_setting("tz", "UTC")
PUB = push._b64(b"\x04" + b"P" * 64)      # a 65-byte uncompressed point
PRIV = push._b64(b"k" * 32)               # a 32-byte private value
GEN = []


def fake_generate():
    GEN.append(1)
    return {"public": PUB, "private": PRIV}


push._generate = fake_generate
push._derive_public = lambda priv: push._unb64(PUB) if priv == PRIV else b"\x04" + b"Q" * 64


def at(hour):
    return datetime(2026, 11, 25, hour, 15, tzinfo=timezone.utc).timestamp()


NOON, NIGHT = at(12), at(3)

# ---- keys
check("no env keys: a pair is generated once and kept in db settings",
      push.public_key() == PUB and push.db.get_setting("vapid") == {"public": PUB, "private": PRIV} and GEN == [1])
push.public_key()
check("and not generated again", GEN == [1])
check("without pywebpush installed, problem() says how to fix it", push.problem() == push._NO_LIBRARY and "pip install pywebpush" in push.problem())
push.db.subs["https://web.push.apple.com/x"] = {"endpoint": "https://web.push.apple.com/x", "keys": {"p256dh": "p", "auth": "a"}}
check("and notify() sends nothing (0) with that reason saved", push.notify("Theta", "hi", now=NOON) == 0
      and push.db.get_setting("push_error") == push._NO_LIBRARY)
push.db.subs.clear()

# ---- a fake pywebpush and py_vapid
SENT = []


class WebPushException(Exception):
    def __init__(self, msg, response=None):
        super().__init__(msg)
        self.response = response


class R:
    def __init__(self, code):
        self.status_code = code


STATUS = {}


def webpush(sub, data, vapid_private_key=None, vapid_claims=None, ttl=None, timeout=None, headers=None):
    SENT.append({"endpoint": sub["endpoint"], "data": json.loads(data), "vapid": vapid_private_key, "claims": vapid_claims,
                 "ttl": ttl, "headers": headers, "keys": sub["keys"]})
    code = STATUS.get(sub["endpoint"], 201)
    if code >= 400:
        raise WebPushException(f"Push failed: {code}", response=R(code))
    return R(code)


pw = types.ModuleType("pywebpush")
pw.webpush, pw.WebPushException = webpush, WebPushException
pv = types.ModuleType("py_vapid")
pv.Vapid02 = type("Vapid02", (), {"from_raw": staticmethod(lambda raw: ("vapid", raw))})
sys.modules["pywebpush"], sys.modules["py_vapid"] = pw, pv
check("with the library and a matching pair, no problem", push.problem() is None)

# ---- env keys win, and bad ones are explained
os.environ.update(VAPID_PUBLIC_KEY=f' "{PUB}"\n', VAPID_PRIVATE_KEY=PRIV)
check("env keys are used, forgiving quotes and line breaks from a paste", push.keys() == (PUB, PRIV, "env") and push.problem() is None)
os.environ.update(VAPID_PUBLIC_KEY=PRIV, VAPID_PRIVATE_KEY=PUB)
check("swapped keys are spotted", "swapped" in push.problem() and push.public_key() == "")
os.environ.update(VAPID_PUBLIC_KEY=PUB, VAPID_PRIVATE_KEY="")
check("half a pair names the missing one", "VAPID_PRIVATE_KEY is missing" in push.problem())
os.environ.update(VAPID_PUBLIC_KEY=PUB, VAPID_PRIVATE_KEY=push._b64(b"z" * 32))
check("two keys that aren't a pair are spotted", "aren't a pair" in push.problem())
os.environ.update(VAPID_PUBLIC_KEY=PUB, VAPID_PRIVATE_KEY=PRIV, VAPID_SUBJECT="mailto:me@example.org")
check("problem() never shows key material", PRIV not in (push.problem() or "") and push.problem() is None)

# ---- subscriptions
check("subscribe: needs an https endpoint", push.subscribe({"endpoint": "http://x/y", "keys": {"p256dh": "p", "auth": "a"}})["ok"] is False)
check("subscribe: needs its keys", push.subscribe({"endpoint": "https://fcm.googleapis.com/a"})["ok"] is False)
APPLE, GOOGLE, GONE, BROKEN = ("https://web.push.apple.com/a", "https://fcm.googleapis.com/fcm/send/b",
                               "https://updates.push.services.mozilla.com/c", "https://web.push.apple.com/d")
check("subscribe: the app's {subscription: {...}} shape is accepted",
      push.subscribe({"subscription": {"endpoint": APPLE, "keys": {"p256dh": "P1", "auth": "A1"}, "expirationTime": None}}) == {"ok": True})
push.subscribe({"endpoint": APPLE, "keys": {"p256dh": "P1b", "auth": "A1b"}})
check("subscribing again replaces, never duplicates", len(push.db.push_subs()) == 1 and push.db.push_subs()[0]["keys"]["p256dh"] == "P1b")
for ep in (GOOGLE, GONE, BROKEN):
    push.subscribe({"endpoint": ep, "keys": {"p256dh": "P", "auth": "A"}})

# ---- sending
STATUS.update({GONE: 410, BROKEN: 500})
n = push.notify("Theta", "Heads up: quake nearby.", "/?m=7", now=NOON)
check("notify() sends to every device and counts the ones that got it", n == 2 and len(SENT) == 4)
check("the payload is {title, body, url}", SENT[0]["data"] == {"title": "Theta", "body": "Heads up: quake nearby.", "url": "/?m=7"})
check("signed with VAPID (raw private key, VAPID_SUBJECT), with a TTL and high urgency",
      SENT[0]["vapid"] == ("vapid", PRIV.encode()) and SENT[0]["claims"] == {"sub": "mailto:me@example.org"} and SENT[0]["ttl"] == 3600
      and SENT[0]["headers"] == {"Urgency": "high"} and SENT[0]["keys"] == {"p256dh": "P1b", "auth": "A1b"})
eps = [s["endpoint"] for s in push.db.push_subs()]
check("a dead subscription (410) is dropped; a push service error (500) keeps it", GONE not in eps and BROKEN in eps and APPLE in eps)
STATUS[BROKEN] = 404
push.notify("Theta", "again", now=NOON)
check("404 is dead too", BROKEN not in [s["endpoint"] for s in push.db.push_subs()])
last = push.db.get_setting("push_last")
check("the last round's results say why each failed", any(r["code"] == 404 and "dropped" in r["why"] for r in last["results"]))
check("the body is capped for the lock screen", (push.notify("Theta", "x" * 500, now=NOON) and len(SENT[-1]["data"]["body"]) == 240))

# ---- quiet hours
SENT.clear()
push.db.set_setting("quiet", [22, 7])
check("quiet hours (22-7, your tz): a non-urgent push waits (0, nothing sent)", push.notify("Theta", "Orange", now=NIGHT) == 0 and SENT == []
      and "quiet" in push.db.get_setting("push_error"))
check("an urgent one (Red) goes through", push.notify("Theta", "Red", urgent=True, now=NIGHT) == 2 and len(SENT) == 2)
check("22:00 is quiet, 7:00 is not", push.quiet_now(at(22)) and not push.quiet_now(at(7)) and push.quiet_now(at(6)))
push.db.set_setting("tz", "America/Denver")   # 12:15 UTC is 05:15 in Denver
check("quiet hours follow the tz setting", push.quiet_now(NOON) and not push.quiet_now(at(19)))
push.db.set_setting("tz", "UTC")
push.db.set_setting("quiet", [9, 17])
check("a daytime window works too", push.quiet_now(NOON) and not push.quiet_now(NIGHT))
push.db.set_setting("quiet", [0, 0])
check("equal hours mean no quiet hours", not push.quiet_now(NIGHT))
push.db.set_setting("quiet", [22, 7])

# ---- test()
SENT.clear()
t = push.test()
check("test(): urgent, so quiet hours never hold it, with per-device results", t["ok"] and t["sent"] == 2 and len(t["results"]) == 2)
push.db.subs.clear()
check("test() with no device says to turn it on first", push.test()["ok"] is False and "Turn on" in push.test()["error"])
print("all push tests passed")
