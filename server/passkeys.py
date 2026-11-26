"""Face ID sign-in (passkeys / WebAuthn). Your phone checks your face itself; the server only ever sees a signature.

Add a device in Settings while signed in (Sign-in > Add Face ID on this device). After that the login screen shows
"Sign in with Face ID", which sets the same `protos_key` cookie /api/login sets. ES256 (P-256) passkeys only: the kind
iPhones, Macs and Android phones make. Ported from the old app's api/_parts/signin.py.

The site a passkey belongs to (rpId) and the origin the browser reports come from PROTOS_PUBLIC_URL when it is set,
otherwise from the request's Host / X-Forwarded-Host and X-Forwarded-Proto headers (as google.py does). A passkey
only works on the address it was added on.

Routes (signed in):
    GET    /api/passkeys                     {"passkeys": [{id, name, created, last_used}]}
    DELETE /api/passkeys?id=<credential id>  {"ok": true}
    POST   /api/passkeys/register/options    {challenge, rpId, rpName, userId, exclude}
    POST   /api/passkeys/register            {name, clientDataJSON, attestationObject} -> {"ok": true, "passkey"}
Public (the caller is checked here, by its signature):
    GET    /api/passkeys/login/options       {"available": bool}
    POST   /api/passkeys/login/options       {"available", "challenge", "rpId", "timeout"}
    POST   /api/passkeys/login               {id, clientDataJSON, authenticatorData, signature} -> {"ok": true}
A failed sign-in counts toward the wrong-key lockout (app._locked / app._failed), like a wrong key.
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse

from . import db
from .tools import public_url

CHALLENGE_SECONDS = 300
MAX_CHALLENGES = 200       # live challenges kept at once (the login one is public, so this caps a flood)
MAX_PASSKEYS = 20
FAIL_DELAY = 0.4           # seconds, to slow down guessing (as /api/login does)
USER_ID = "passkeys:user_id"

_lock = threading.Lock()
_ready = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS passkeys (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    x         TEXT NOT NULL,
    y         TEXT NOT NULL,
    sign_count INTEGER NOT NULL DEFAULT 0,
    rp_id     TEXT NOT NULL DEFAULT '',
    created   REAL NOT NULL,
    last_used REAL
);
CREATE TABLE IF NOT EXISTS passkey_challenges (
    challenge TEXT PRIMARY KEY,
    kind      TEXT NOT NULL,
    exp       REAL NOT NULL
);
"""


def _c():
    global _ready
    key = (getattr(db, "_path", None), getattr(db, "_gen", None))
    c = db._conn()
    if _ready != key:
        c.executescript(_SCHEMA)
        _ready = key
    return c


# ---- encoding

def _b64u_decode(s):
    if not isinstance(s, str):
        raise ValueError("expected base64url text")
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (ValueError, TypeError):
        raise ValueError("bad base64url") from None


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def cbor_decode(data):
    """Just enough CBOR for WebAuthn (maps, arrays, ints, bytes, text, true/false/null). Returns (value, end)."""
    def item(i):
        if i >= len(data):
            raise ValueError("truncated CBOR")
        ib = data[i]
        major, info = ib >> 5, ib & 31
        i += 1
        if info < 24:
            val = info
        elif info in (24, 25, 26, 27):
            n = 1 << (info - 24)
            if i + n > len(data):
                raise ValueError("truncated CBOR")
            val = int.from_bytes(data[i:i + n], "big")
            i += n
        else:
            raise ValueError("unsupported CBOR")
        if major == 0:
            return val, i
        if major == 1:
            return -1 - val, i
        if major in (2, 3):
            if i + val > len(data):
                raise ValueError("truncated CBOR")
            chunk = bytes(data[i:i + val])
            return (chunk if major == 2 else chunk.decode()), i + val
        if major == 4:
            out = []
            for _ in range(val):
                v, i = item(i)
                out.append(v)
            return out, i
        if major == 5:
            out = {}
            for _ in range(val):
                k, i = item(i)
                v, i = item(i)
                out[k] = v
            return out, i
        if major == 7 and info in (20, 21, 22):
            return {20: False, 21: True, 22: None}[info], i
        raise ValueError("unsupported CBOR")
    return item(0)


# ---- the site

def rp(req):
    """(rpId, origin) for this request: from PROTOS_PUBLIC_URL, else the Host and X-Forwarded-Proto headers."""
    base = public_url()
    if not base:
        host = req.header("X-Forwarded-Host") or req.header("Host") or req.env.get("SERVER_NAME") or "localhost"
        host = host.split(",")[0].strip()
        proto = (req.header("X-Forwarded-Proto") or req.env.get("wsgi.url_scheme") or "http").split(",")[0].strip()
        base = f"{proto}://{host}"
    u = urllib.parse.urlsplit(base)
    return (u.hostname or "localhost"), f"{u.scheme}://{u.netloc}"


# ---- storage

def _row(r):
    return {"id": r["id"], "name": r["name"], "created": r["created"], "last_used": r["last_used"],
            "site": r["rp_id"] or ""}


def passkeys():
    return [_row(r) for r in _c().execute("SELECT * FROM passkeys ORDER BY created").fetchall()]


def _get(cred_id):
    return _c().execute("SELECT * FROM passkeys WHERE id = ?", (cred_id,)).fetchone()


def remove(cred_id):
    return _c().execute("DELETE FROM passkeys WHERE id = ?", (cred_id,)).rowcount > 0


def _user_id():
    uid = db.get_setting(USER_ID)
    if not uid:
        uid = _b64u(secrets.token_bytes(16))
        db.set_setting(USER_ID, uid)
    return uid


def new_challenge(kind, now=None):
    now = time.time() if now is None else now
    ch = _b64u(secrets.token_bytes(32))
    with _lock:
        c = _c()
        c.execute("DELETE FROM passkey_challenges WHERE exp <= ?", (now,))
        c.execute("INSERT INTO passkey_challenges (challenge, kind, exp) VALUES (?, ?, ?)",
                  (ch, kind, now + CHALLENGE_SECONDS))
        c.execute("DELETE FROM passkey_challenges WHERE challenge NOT IN "
                  "(SELECT challenge FROM passkey_challenges ORDER BY exp DESC LIMIT ?)", (MAX_CHALLENGES,))
    return ch


def _take_challenge(ch, kind, now=None):
    """A challenge is good once, for its kind, for 5 minutes. Any use removes it."""
    now = time.time() if now is None else now
    if not isinstance(ch, str) or not ch:
        return False
    with _lock:
        c = _c()
        row = c.execute("SELECT kind, exp FROM passkey_challenges WHERE challenge = ?", (ch,)).fetchone()
        gone = c.execute("DELETE FROM passkey_challenges WHERE challenge = ?", (ch,)).rowcount
    return bool(row and gone and row["kind"] == kind and row["exp"] > now)


# ---- checks

def _check_client(client_json, kind, origin):
    try:
        cd = json.loads(client_json.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("bad clientDataJSON") from None
    if not isinstance(cd, dict) or cd.get("type") != f"webauthn.{kind}":
        raise ValueError("wrong ceremony")
    if cd.get("origin") != origin:
        raise ValueError(f"wrong origin {str(cd.get('origin'))[:80]}")
    if cd.get("crossOrigin") is True:
        raise ValueError("cross-origin request")
    if not _take_challenge(cd.get("challenge", ""), kind):
        raise ValueError("challenge expired or already used")


def _check_auth_data(auth, rp_id):
    if len(auth) < 37:
        raise ValueError("authenticator data too short")
    if auth[:32] != hashlib.sha256(rp_id.encode()).digest():
        raise ValueError("passkey is for another site")
    flags = auth[32]
    if not flags & 0x01:
        raise ValueError("the device didn't confirm you were there")
    if not flags & 0x04:
        raise ValueError("the device didn't verify you (Face ID, Touch ID or passcode)")
    return flags, int.from_bytes(auth[33:37], "big")


def register_passkey(data, rp_id, origin, name="iPhone", now=None):
    from cryptography.hazmat.primitives.asymmetric import ec
    now = time.time() if now is None else now
    if not isinstance(data, dict):
        raise ValueError("bad request")
    _check_client(_b64u_decode(data.get("clientDataJSON")), "create", origin)
    att, _ = cbor_decode(_b64u_decode(data.get("attestationObject")))
    auth = att.get("authData") if isinstance(att, dict) else None
    if not isinstance(auth, bytes):
        raise ValueError("no authenticator data")
    flags, count = _check_auth_data(auth, rp_id)
    if not flags & 0x40 or len(auth) < 55:
        raise ValueError("no credential in the response")
    n = int.from_bytes(auth[53:55], "big")
    if not 16 <= n <= 1023 or len(auth) < 55 + n:
        raise ValueError("bad credential id")
    cred_id = auth[55:55 + n]
    cose, _ = cbor_decode(auth[55 + n:])
    if not isinstance(cose, dict) or cose.get(3) != -7 or cose.get(1) != 2 or cose.get(-1) != 1:
        raise ValueError("only ES256 (P-256) passkeys are supported")
    x, y = cose.get(-2), cose.get(-3)
    if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
        raise ValueError("bad public key")
    ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"),
                                  ec.SECP256R1()).public_key()  # a real point on the curve, or this raises
    name = (str(name or "").strip()[:60]) or "iPhone"
    cid = _b64u(cred_id)
    with _lock:
        c = _c()
        if not _get(cid) and c.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0] >= MAX_PASSKEYS:
            raise ValueError(f"at most {MAX_PASSKEYS} passkeys; remove one first")
        c.execute("INSERT OR REPLACE INTO passkeys (id, name, x, y, sign_count, rp_id, created, last_used) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)", (cid, name, _b64u(x), _b64u(y), count, rp_id, now))
    return _row(_get(cid))


def verify_passkey(data, rp_id, origin, now=None):
    """The passkey when the signature is from one of your registered devices; ValueError otherwise."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    now = time.time() if now is None else now
    if not isinstance(data, dict):
        raise ValueError("bad request")
    key = _get(data.get("id")) if isinstance(data.get("id"), str) else None
    client = _b64u_decode(data.get("clientDataJSON"))
    _check_client(client, "get", origin)  # uses up the challenge even when the device is unknown
    if not key:
        raise ValueError("this device isn't registered")
    auth = _b64u_decode(data.get("authenticatorData"))
    _, count = _check_auth_data(auth, rp_id)
    pub = ec.EllipticCurvePublicNumbers(int.from_bytes(_b64u_decode(key["x"]), "big"),
                                        int.from_bytes(_b64u_decode(key["y"]), "big"), ec.SECP256R1()).public_key()
    try:
        pub.verify(_b64u_decode(data.get("signature")), auth + hashlib.sha256(client).digest(),
                   ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        raise ValueError("signature didn't match") from None
    stored = key["sign_count"] or 0
    if (count or stored) and count <= stored:  # devices that don't count (iCloud Keychain) always send 0
        raise ValueError("this passkey may have been copied (its counter went backwards)")
    with _lock:
        _c().execute("UPDATE passkeys SET sign_count = ?, last_used = ? WHERE id = ?", (count, now, key["id"]))
    return _row(_get(key["id"]))


# ---- routes

def _app():
    from . import app
    return app


def _ok_body(req):
    app = _app()
    body = req.json()
    if not isinstance(body, dict):
        raise app.HTTPError(400, "body must be a JSON object")
    return body


def list_route(req, start):
    app = _app()
    if req.method == "GET":
        return app.respond_json(start, {"passkeys": [{k: p[k] for k in ("id", "name", "created", "last_used")}
                                                     for p in passkeys()]})
    if req.method == "DELETE":
        cid = req.query.get("id") or ""
        if not cid:
            raise app.HTTPError(400, "id is required")
        if not remove(cid):
            raise app.HTTPError(404, "no such passkey")
        return app.respond_json(start, {"ok": True})
    raise app.HTTPError(405, "method not allowed")


def register_options(req, start):
    app = _app()
    if req.method != "POST":
        raise app.HTTPError(405, "method not allowed")
    rp_id, _ = rp(req)
    return app.respond_json(start, {"ok": True, "challenge": new_challenge("create"), "rpId": rp_id, "rpName": "Theta",
                                    "userId": _user_id(), "timeout": 60000,
                                    "exclude": [p["id"] for p in passkeys()]})


def register(req, start):
    app = _app()
    if req.method != "POST":
        raise app.HTTPError(405, "method not allowed")
    body = _ok_body(req)
    rp_id, origin = rp(req)
    try:
        pk = register_passkey(body, rp_id, origin, body.get("name") or "iPhone")
    except (ValueError, KeyError, TypeError) as e:
        return app.respond_json(start, {"ok": False, "error": str(e)}, 400)
    return app.respond_json(start, {"ok": True, "passkey": {k: pk[k] for k in ("id", "name", "created", "last_used")}})


def login_options(req, start):
    app = _app()
    available = bool(passkeys())
    if req.method == "GET":
        return app.respond_json(start, {"available": available})
    if req.method != "POST":
        raise app.HTTPError(405, "method not allowed")
    if not available:
        return app.respond_json(start, {"ok": True, "available": False})
    rp_id, _ = rp(req)
    return app.respond_json(start, {"ok": True, "available": True, "challenge": new_challenge("get"), "rpId": rp_id,
                                    "timeout": 60000})


def login(req, start):
    app = _app()
    if req.method != "POST":
        raise app.HTTPError(405, "method not allowed")
    key = os.environ.get("PROTOS_KEY", "")
    if key and app._locked():
        raise app.HTTPError(429, "Too many wrong keys. Try again in a few minutes.")
    body = _ok_body(req)
    rp_id, origin = rp(req)
    try:
        verify_passkey(body, rp_id, origin)
    except (ValueError, KeyError, TypeError) as e:
        app._failed()
        if FAIL_DELAY:
            time.sleep(FAIL_DELAY)
        return app.respond_json(start, {"ok": False, "error": str(e)}, 401)
    # the same cookie login() sets, with the same attributes
    from http.cookies import SimpleCookie
    c = SimpleCookie()
    c["protos_key"] = key
    c["protos_key"]["path"] = "/"
    c["protos_key"]["httponly"] = True
    c["protos_key"]["samesite"] = "Lax"
    c["protos_key"]["max-age"] = str(400 * 86400)
    if req.https():
        c["protos_key"]["secure"] = True
    return app.respond_json(start, {"ok": True}, extra=[("Set-Cookie", c["protos_key"].OutputString())])


ROUTES = {
    "/api/passkeys": list_route,
    "/api/passkeys/register/options": register_options,
    "/api/passkeys/register": register,
}

PUBLIC_ROUTES = {
    "/api/passkeys/login/options": login_options,
    "/api/passkeys/login": login,
}


def connections():
    return []


def context(bot, now):
    return ""
