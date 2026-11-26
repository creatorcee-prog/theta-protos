"""Face ID sign-in (server/passkeys.py). A real P-256 key plays the phone: it makes valid WebAuthn registration and
assertion data, and each check breaks one thing. No network. Run: python3 tests/test_passkeys.py"""
import base64
import hashlib
import io
import json
import os
import sys
import tempfile
from http.cookies import SimpleCookie

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_DATA=tempfile.mkdtemp(prefix="protos-passkeys-"),
                  PROTOS_QUIET="1")
os.environ.pop("PROTOS_PUBLIC_URL", None)

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

from server import app, ext, passkeys  # noqa: E402

passkeys.FAIL_DELAY = 0
FAILED = []
HOST, ORIGIN = "theta.example", "https://theta.example"


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILED.append(name)


def call(path, method="GET", body=None, key="k", headers=None, cookie=None):
    raw = json.dumps(body).encode() if body is not None else b""
    p, _, qs = path.partition("?")
    env = {"REQUEST_METHOD": method, "PATH_INFO": p, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http", "REMOTE_ADDR": "1.2.3.4",
           "HTTP_HOST": HOST, "HTTP_X_FORWARDED_PROTO": "https"}
    if key:
        env["HTTP_X_PROTOS_KEY"] = key
    if cookie:
        env["HTTP_COOKIE"] = cookie
    for k, v in (headers or {}).items():
        env["HTTP_" + k.upper().replace("-", "_")] = v
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]), h=h)))
    try:
        j = json.loads(out or b"{}")
    except ValueError:
        j = {}
    return got["s"], j, got["h"]


# ---- a tiny CBOR encoder (the phone's side)

def _head(major, n):
    if n < 24:
        return bytes([major << 5 | n])
    for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if n < 1 << (8 * size):
            return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    raise ValueError(n)


def cbor(v):
    if isinstance(v, bool):
        return bytes([0xf5 if v else 0xf4])
    if isinstance(v, int):
        return _head(0, v) if v >= 0 else _head(1, -1 - v)
    if isinstance(v, bytes):
        return _head(2, len(v)) + v
    if isinstance(v, str):
        b = v.encode()
        return _head(3, len(b)) + b
    if isinstance(v, list):
        return _head(4, len(v)) + b"".join(cbor(x) for x in v)
    if isinstance(v, dict):
        return _head(5, len(v)) + b"".join(cbor(k) + cbor(x) for k, x in v.items())
    raise TypeError(v)


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Phone:
    """One passkey on one device."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(32)
        self.count = 0

    def cose(self):
        n = self.key.public_key().public_numbers()
        return cbor({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def register(self, challenge, rp_id=HOST, origin=ORIGIN, flags=0x45, name="iPhone"):
        client = json.dumps({"type": "webauthn.create", "challenge": challenge, "origin": origin}).encode()
        auth = (hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + self.count.to_bytes(4, "big")
                + bytes(16) + len(self.cred_id).to_bytes(2, "big") + self.cred_id + self.cose())
        att = cbor({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"name": name, "clientDataJSON": b64u(client), "attestationObject": b64u(att)}

    def assert_(self, challenge, rp_id=HOST, origin=ORIGIN, flags=0x05, count=None, ceremony="webauthn.get",
                bad_sig=False):
        if count is None:
            self.count += 1
            count = self.count
        client = json.dumps({"type": ceremony, "challenge": challenge, "origin": origin}).encode()
        auth = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + count.to_bytes(4, "big")
        sig = self.key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        if bad_sig:
            sig = ec.generate_private_key(ec.SECP256R1()).sign(auth + hashlib.sha256(client).digest(),
                                                               ec.ECDSA(hashes.SHA256()))
        return {"id": b64u(self.cred_id), "clientDataJSON": b64u(client), "authenticatorData": b64u(auth),
                "signature": b64u(sig)}


def reg_challenge():
    s, j, _ = call("/api/passkeys/register/options", "POST", {})
    assert s == 200, (s, j)
    return j


def login_challenge():
    s, j, _ = call("/api/passkeys/login/options", "POST", {}, key=None)
    assert s == 200, (s, j)
    return j.get("challenge")


def fails():
    with app._fails_lock:
        return len(app._fails)


def reset_fails():
    with app._fails_lock:
        app._fails.clear()


def login(data):
    return call("/api/passkeys/login", "POST", data, key=None)


def main():
    ext.reset()
    check("loaded as a feature", "passkeys" in ext.FEATURES and ext.route("/api/passkeys/login", public=True)
          is passkeys.login and ext.route("/api/passkeys") is passkeys.list_route, ext.errors())

    # nothing registered yet
    s, j, _ = call("/api/passkeys/login/options", key=None)
    check("login options: not available before any passkey", s == 200 and j == {"available": False}, (s, j))

    # registering needs sign-in
    s, _, _ = call("/api/passkeys/register/options", "POST", {}, key=None)
    s2, _, _ = call("/api/passkeys/register", "POST", {}, key=None)
    s3, _, _ = call("/api/passkeys", key=None)
    check("register and list need sign-in", s == 401 and s2 == 401 and s3 == 401, (s, s2, s3))

    phone = Phone()
    o = reg_challenge()
    check("register options name the site", o["rpId"] == HOST and o["challenge"] and o["userId"] and o["exclude"] == [], o)
    s, j, _ = call("/api/passkeys/register", "POST", phone.register(o["challenge"]))
    check("register: saved", s == 200 and j.get("ok") and j["passkey"]["name"] == "iPhone", (s, j))
    s, j, _ = call("/api/passkeys/register", "POST", phone.register(o["challenge"]))
    check("register: challenge works once", s == 400 and "challenge" in j.get("error", ""), (s, j))

    other = Phone()
    s, j, _ = call("/api/passkeys/register", "POST", other.register(reg_challenge()["challenge"], origin="https://evil.example"))
    check("register: wrong origin refused", s == 400 and "origin" in j.get("error", ""), (s, j))
    s, j, _ = call("/api/passkeys/register", "POST", other.register(reg_challenge()["challenge"], flags=0x41))
    check("register: no user verification refused", s == 400 and "verify" in j.get("error", ""), (s, j))

    s, j, _ = call("/api/passkeys")
    check("list shows the passkey", s == 200 and len(j["passkeys"]) == 1 and
          set(j["passkeys"][0]) == {"id", "name", "created", "last_used"} and j["passkeys"][0]["last_used"] is None, j)
    s, j, _ = call("/api/passkeys/login/options", key=None)
    check("login options: available", j == {"available": True}, j)

    # happy path
    reset_fails()
    s, j, h = login(phone.assert_(login_challenge()))
    cookies = [v for k, v in h if k == "Set-Cookie"]
    ok = s == 200 and j == {"ok": True} and len(cookies) == 1
    check("login: signs in", ok, (s, j, h))
    if ok:
        raw = cookies[0]
        c = SimpleCookie()
        c.load(raw)
        m = c["protos_key"]
        lower = raw.lower()
        check("login: same cookie as /api/login", m.value == "k" and m["path"] == "/" and "httponly" in lower and
              "samesite=lax" in lower and "secure" in lower and m["max-age"] == str(400 * 86400), raw)
        s, j, _ = call("/api/passkeys", key=None, cookie="protos_key=" + m.value)
        check("login: cookie is accepted by app.authed", s == 200 and "passkeys" in j, (s, j))
        # and it's the very same as what login() gives for the right key
        s2, _, h2 = call("/api/login", "POST", {"key": "k"}, key=None)
        ref = [v for k, v in h2 if k == "Set-Cookie"][0]
        check("login: cookie attributes identical to login()", sorted(raw.split("; ")) == sorted(ref.split("; ")), (raw, ref))
    s, j, _ = call("/api/passkeys")
    check("login: last used recorded", j["passkeys"][0]["last_used"], j)

    # every failure is a wrong key
    def bad(name, data, needle):
        before = fails()
        s, j, h = login(data)
        check(name, s == 401 and needle in j.get("error", "") and not [v for k, v in h if k == "Set-Cookie"]
              and fails() == before + 1, (s, j, fails() - before))

    bad("wrong challenge", phone.assert_(b64u(os.urandom(32))), "challenge")
    ch = login_challenge()
    s, _, _ = login(phone.assert_(ch))
    check("replay: first use works", s == 200, s)
    bad("replayed challenge", phone.assert_(ch), "challenge")
    bad("wrong origin", phone.assert_(login_challenge(), origin="https://evil.example"), "origin")
    bad("wrong rpId", phone.assert_(login_challenge(), rp_id="evil.example"), "another site")
    bad("wrong ceremony type", phone.assert_(login_challenge(), ceremony="webauthn.create"), "ceremony")
    bad("bad signature counts toward the lockout", phone.assert_(login_challenge(), bad_sig=True), "signature")
    bad("sign-count regression", phone.assert_(login_challenge(), count=1), "counter")
    bad("missing UV flag", phone.assert_(login_challenge(), flags=0x01), "verify")
    bad("missing UP flag", phone.assert_(login_challenge(), flags=0x04), "there")
    bad("unknown device", Phone().assert_(login_challenge()), "registered")

    # an expired challenge
    ch = login_challenge()
    passkeys._c().execute("UPDATE passkey_challenges SET exp = 1 WHERE challenge = ?", (ch,))
    bad("expired challenge", phone.assert_(ch), "challenge")

    # zero counters (iCloud Keychain) are fine
    p0 = Phone()
    call("/api/passkeys/register", "POST", p0.register(reg_challenge()["challenge"], name="Mac"))
    s1, _, _ = login(p0.assert_(login_challenge(), count=0))
    s2, _, _ = login(p0.assert_(login_challenge(), count=0))
    check("zero sign counts are accepted", s1 == 200 and s2 == 200, (s1, s2))

    # the lockout: once locked, even a good passkey is refused
    reset_fails()
    for _ in range(app.LOCK_FAILS):
        app._failed()
    s, j, h = login(phone.assert_(login_challenge()))
    check("locked: good passkey refused with 429", s == 429 and not [v for k, v in h if k == "Set-Cookie"], (s, j))
    reset_fails()
    s, _, _ = login(phone.assert_(login_challenge()))
    check("unlocked: signs in again", s == 200, s)

    # PROTOS_PUBLIC_URL wins over the Host header
    os.environ["PROTOS_PUBLIC_URL"] = "https://theta-protos-production.up.railway.app/"
    try:
        s, j, _ = call("/api/passkeys/register/options", "POST", {})
        check("public URL sets rpId", j.get("rpId") == "theta-protos-production.up.railway.app", j)
        rpid, origin = "theta-protos-production.up.railway.app", "https://theta-protos-production.up.railway.app"
        bad("public URL: Host-based origin refused", phone.assert_(login_challenge()), "origin")
        pp = Phone()
        s, j, _ = call("/api/passkeys/register", "POST", pp.register(reg_challenge()["challenge"], rp_id=rpid, origin=origin))
        s2, _, _ = login(pp.assert_(login_challenge(), rp_id=rpid, origin=origin))
        check("public URL: register and sign in", s == 200 and s2 == 200, (s, j, s2))
    finally:
        os.environ.pop("PROTOS_PUBLIC_URL", None)
    reset_fails()

    # deleting
    s, j, _ = call("/api/passkeys")
    n = len(j["passkeys"])
    s, _, _ = call("/api/passkeys?id=" + b64u(phone.cred_id), "DELETE", key=None)
    check("delete needs sign-in", s == 401, s)
    s, j, _ = call("/api/passkeys?id=" + b64u(phone.cred_id), "DELETE")
    s2, j2, _ = call("/api/passkeys")
    check("delete removes it", s == 200 and j == {"ok": True} and len(j2["passkeys"]) == n - 1 and
          b64u(phone.cred_id) not in [p["id"] for p in j2["passkeys"]], (s, j, j2))
    s, _, _ = call("/api/passkeys?id=nope", "DELETE")
    check("delete unknown is 404", s == 404, s)
    bad("deleted passkey can't sign in", phone.assert_(login_challenge()), "registered")

    # no passkeys -> no challenge handed out
    for p in passkeys.passkeys():
        passkeys.remove(p["id"])
    s, j, _ = call("/api/passkeys/login/options", "POST", {}, key=None)
    check("no passkeys: options say unavailable", s == 200 and j.get("available") is False and "challenge" not in j, j)

    check("no connections, no context", passkeys.connections() == [] and passkeys.context("theta", 0) == "")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        FAILED.append(f"crashed: {e!r}")
    if FAILED:
        print(f"\n{len(FAILED)} failed: {', '.join(FAILED)}")
        sys.exit(1)
    print("\nall passed")
