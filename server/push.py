"""Phone notifications: Web Push with VAPID. Ported from theta-app api/_parts/push.py.

Encryption and signing are done by `pywebpush` (RFC 8291 aes128gcm payload encryption via `http_ece`, and the
VAPID JWT via `py_vapid`, all on top of `cryptography`), as in theta-app. It is optional: without it
problem() says so and notify() sends nothing (returns 0). Install with `pip install pywebpush`.

Keys: VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY from the environment (base64url: the 65-byte uncompressed public point
and the 32-byte private value, the same format theta-app uses, so its pair can be reused). Without them a pair is
generated once (needs `cryptography`) and kept in db settings ("vapid"). VAPID_SUBJECT is the contact the push
services see (mailto: or https:); Apple refuses a missing one.

Quiet hours come from settings ("quiet": [22, 7], "tz"): a non-urgent push waits (returns 0; the message is
still in the inbox), an urgent one (Red, the test push) goes through. Dead subscriptions (404/410) are dropped."""
import base64
import json
import os
import time
from datetime import datetime
from urllib.parse import urlparse

db = None   # server.db, loaded on first use; tests put a fake here
DEFAULT_SUBJECT = "mailto:theta-protos@example.com"
DEFAULT_TZ = "America/Denver"   # the same default as persona.py / app.py settings
TTL = 3600
_PUSH_HOSTS = (("push.apple.com", "iPhone"), ("fcm.googleapis.com", "Android/Chrome"),
               ("push.services.mozilla.com", "Firefox"), ("notify.windows.com", "Windows"))


def _db():
    global db
    if db is None:
        from server import db as real
        db = real
    return db


def _clean(value):
    """Forgive the usual paste slips: spaces, line breaks and quotes."""
    return "".join((value or "").split()).strip("\"'")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# ---------------------------------------------------------------- keys
def _generate():
    """A fresh VAPID pair (P-256) as {"public", "private"} base64url. Needs `cryptography`."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    return {"public": _b64(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)),
            "private": _b64(key.private_numbers().private_value.to_bytes(32, "big"))}


def _derive_public(private_b64):
    """The public point (65 bytes) that belongs to a raw private key. Needs `cryptography`."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.derive_private_key(int.from_bytes(_unb64(private_b64), "big"), ec.SECP256R1())
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def keys():
    """(public, private, where) where is 'env', 'db' or ''. Generates and saves a pair once if there is none."""
    pub, priv = _clean(os.environ.get("VAPID_PUBLIC_KEY")), _clean(os.environ.get("VAPID_PRIVATE_KEY"))
    if pub or priv:
        return pub, priv, "env"
    saved = _db().get_setting("vapid") or {}
    if saved.get("public") and saved.get("private"):
        return saved["public"], saved["private"], "db"
    try:
        pair = _generate()
    except ImportError:
        return "", "", ""
    _db().set_setting("vapid", pair)
    return pair["public"], pair["private"], "db"


def public_key():
    """The VAPID public key (base64url) the phone subscribes with, or "" if there can't be one."""
    pub, priv, _ = keys()
    return "" if _bad_keys(pub, priv) else pub


_NO_LIBRARY = "the push library isn't installed on the server: pip install pywebpush"


def _bad_keys(pub, priv):
    if not pub and not priv:
        return ("no VAPID keys, and they can't be generated without the `cryptography` package: "
                "pip install pywebpush (or set VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)")
    if not pub or not priv:
        missing = "VAPID_PUBLIC_KEY" if not pub else "VAPID_PRIVATE_KEY"
        return f"{missing} is missing: set both, or neither (then a pair is made for you)"
    try:
        p, k = _unb64(pub), _unb64(priv)
    except ValueError:
        return "a VAPID key isn't valid base64url: copy it again exactly"
    if len(p) == 32 and len(k) == 65:
        return "VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are swapped"
    if len(p) != 65 or p[0] != 4:
        return "VAPID_PUBLIC_KEY isn't a valid public key (want 65 bytes, base64url)"
    if len(k) != 32:
        return "VAPID_PRIVATE_KEY isn't a valid private key (want 32 bytes, base64url)"
    return None


def problem():
    """Why phone notifications can't work right now, in plain words, or None. Never includes key material."""
    pub, priv, _ = keys()
    bad = _bad_keys(pub, priv)
    if bad:
        return bad
    try:
        import pywebpush  # noqa: F401
        import py_vapid  # noqa: F401
    except ImportError:
        return _NO_LIBRARY
    try:
        derived = _derive_public(priv)
    except ImportError:
        return _NO_LIBRARY
    except Exception:  # noqa: BLE001
        return "VAPID_PRIVATE_KEY isn't a usable P-256 key: generate a new pair"
    if derived != _unb64(pub):
        return "the two VAPID keys aren't a pair (one came from another pair): replace both"
    return None


# ---------------------------------------------------------------- subscriptions
def subscribe(sub):
    """Save a browser's PushSubscription ({endpoint, keys: {p256dh, auth}}). Returns {"ok": True} or {"ok": False, "error"}."""
    if isinstance(sub, dict) and isinstance(sub.get("subscription"), dict):
        sub = sub["subscription"]
    if not isinstance(sub, dict):
        return {"ok": False, "error": "a subscription object is needed"}
    endpoint, k = sub.get("endpoint") or "", sub.get("keys") or {}
    if not endpoint.startswith("https://") or not urlparse(endpoint).hostname:
        return {"ok": False, "error": "the subscription has no https endpoint"}
    if not k.get("p256dh") or not k.get("auth"):
        return {"ok": False, "error": "the subscription is missing its keys (p256dh, auth)"}
    clean = {"endpoint": endpoint, "keys": {"p256dh": k["p256dh"], "auth": k["auth"]}, "made": time.time()}
    for extra in ("device", "ua"):
        if sub.get(extra):
            clean[extra] = str(sub[extra])[:80]
    _db().drop_push_sub(endpoint)   # re-subscribing replaces, never duplicates
    _db().add_push_sub(clean)
    return {"ok": True}


def _name(sub):
    host = urlparse(sub.get("endpoint", "")).hostname or "?"
    return sub.get("device") or next((n for h, n in _PUSH_HOSTS if host.endswith(h)), host)


# ---------------------------------------------------------------- quiet hours
def user_tz():
    from zoneinfo import ZoneInfo
    for name in (_db().get_setting("tz"), os.environ.get("PROTOS_TZ"), DEFAULT_TZ):
        if name:
            try:
                return ZoneInfo(name)
            except Exception:  # noqa: BLE001  an unknown zone: try the next
                pass
    return datetime.now().astimezone().tzinfo


def user_now(now=None):
    return datetime.fromtimestamp(now if now is not None else time.time(), user_tz())


def quiet_now(now=None):
    """True inside quiet hours (settings "quiet": [start_hour, end_hour], e.g. [22, 7]; equal hours = none)."""
    q = _db().get_setting("quiet", [22, 7])
    try:
        a, b = int(q[0]), int(q[1])
    except (TypeError, ValueError, IndexError):
        return False
    if a == b:
        return False
    h = user_now(now).hour
    return a <= h < b if a < b else (h >= a or h < b)


# ---------------------------------------------------------------- sending
def notify(title, body, url="/", urgent=False, now=None):
    """Push to every subscribed device; returns how many got it. Non-urgent pushes wait out quiet hours (0).
    Quietly does nothing (0) until keys, the library and a subscription exist; the reason is in settings
    "push_error". Dead subscriptions (404/410) are dropped."""
    if not urgent and quiet_now(now):
        _db().set_setting("push_error", "quiet hours: held (not urgent)")
        return 0
    why = problem()
    if why:
        _db().set_setting("push_error", why)
        return 0
    subs = _db().push_subs()
    if not subs:
        _db().set_setting("push_error", "no device has subscribed yet")
        return 0
    try:
        from py_vapid import Vapid02
        from pywebpush import WebPushException, webpush
    except ImportError:
        _db().set_setting("push_error", _NO_LIBRARY)
        return 0
    _, priv, _ = keys()
    vapid = Vapid02.from_raw(priv.encode())
    subject = os.environ.get("VAPID_SUBJECT") or DEFAULT_SUBJECT
    payload = json.dumps({"title": title, "body": (body or "")[:240], "url": url})
    sent, error, results = 0, "", []
    for sub in subs:
        wire = {"endpoint": sub["endpoint"], "keys": sub["keys"]}
        try:
            # high urgency: phones in Low Power Mode otherwise hold pushes back (theta-app does the same)
            r = webpush(wire, payload, vapid_private_key=vapid, vapid_claims={"sub": subject}, ttl=TTL, timeout=10,
                        headers={"Urgency": "high"})
            sent += 1
            results.append({"device": _name(sub), "ok": True, "code": getattr(r, "status_code", None)})
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            gone = code in (404, 410)
            if gone:   # gone for good (app removed or re-added): drop it
                _db().drop_push_sub(sub["endpoint"])
            error = f"push service returned {code}: {str(e)[:120]}"
            results.append({"device": _name(sub), "ok": False, "code": code,
                            "why": "this sign-up no longer exists, so it was dropped" if gone else error})
        except Exception as e:  # noqa: BLE001  network trouble shouldn't break a round
            error = f"push failed: {e!r}"[:160]
            results.append({"device": _name(sub), "ok": False, "code": None, "why": error})
    _db().set_setting("push_error", error)
    _db().set_setting("push_last", {"at": time.time(), "results": results})
    return sent


def test():
    """Settings' test push: urgent, so quiet hours never hold it. {"ok", "sent", "error", "results"}."""
    why = problem()
    if why:
        return {"ok": False, "sent": 0, "error": why, "results": []}
    if not _db().push_subs():
        return {"ok": False, "sent": 0, "error": "no device has subscribed yet: tap Turn on in the app first", "results": []}
    n = notify("Theta", "Test: notifications from Theta work. Real ones look like this.", "/", urgent=True)
    last = _db().get_setting("push_last") or {}
    return {"ok": n > 0, "sent": n, "error": "" if n else (_db().get_setting("push_error") or "nothing was sent"),
            "results": last.get("results") or []}
