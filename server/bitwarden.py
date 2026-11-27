"""Bitwarden: the second place Theta's browser can take logins from (server/vault.py picks between this and
1Password). The model never sees a password or a code.

How it reaches the vault: the official Bitwarden CLI (`bw`, installed by the Dockerfile), with a personal API key to
log in and the master password to unlock:

    BW_CLIENTID, BW_CLIENTSECRET   Bitwarden web vault > Settings > Security > Keys > View API key
    BW_PASSWORD                    the master password (unlock only; never logged or passed on a command line)
    BW_SERVER                      optional: https://vault.bitwarden.eu or a self-hosted server
    BW_FOLDER                      optional, recommended: only logins in this folder (e.g. "Theta") are used

The master password on the server can open the whole vault, so the safest setup is a separate Bitwarden account (or
a folder, via BW_FOLDER) holding only the logins Theta should use. The CLI keeps its encrypted cache in
<data>/bitwarden.

One-time codes: Bitwarden stores the TOTP seed; Theta works out the current code here (RFC 6238), so it doesn't need
a premium-only CLI call and the seed never leaves this module.
"""
import base64
import hashlib
import hmac
import json
import os
import shutil
import struct
import subprocess
import threading
import time
import urllib.parse

from .tools import ToolError

TIMEOUT = 60
_lock = threading.Lock()
_state = {"session": "", "t": 0.0}
SESSION_S = 1800  # unlock again after this long


def _env(k):
    return (os.environ.get(k) or "").strip()


def binary():
    return _env("BW_BIN") or shutil.which("bw") or ""


def available():
    return bool(_env("BW_CLIENTID") and _env("BW_CLIENTSECRET") and _env("BW_PASSWORD") and binary())


def missing():
    need = [k for k in ("BW_CLIENTID", "BW_CLIENTSECRET", "BW_PASSWORD") if not _env(k)]
    if not binary():
        need.append("the bw program (the Dockerfile installs it)")
    return need


def _appdir():
    from . import db
    d = os.path.join(db.data_dir(), "bitwarden")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _run(args, session="", check=True):
    """Run one bw command; returns stdout. Secrets go through the environment, never argv."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": _appdir(), "BITWARDENCLI_APPDATA_DIR": _appdir(),
           "BW_CLIENTID": _env("BW_CLIENTID"), "BW_CLIENTSECRET": _env("BW_CLIENTSECRET"),
           "BW_PASSWORD": _env("BW_PASSWORD"), "BW_NOINTERACTION": "true", "NODE_OPTIONS": ""}
    if session:
        env["BW_SESSION"] = session
    try:
        p = subprocess.run([binary(), *args, "--nointeraction"], capture_output=True, text=True, timeout=TIMEOUT,
                           env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ToolError(f"Bitwarden didn't answer ({type(e).__name__})") from None
    if check and p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip().splitlines()
        first = err[0][:160] if err else f"exit {p.returncode}"
        for word in (_env("BW_PASSWORD"), _env("BW_CLIENTSECRET")):  # never echo a secret, even by accident
            if word:
                first = first.replace(word, "•••")
        raise ToolError(f"Bitwarden refused it: {first}")
    return p.stdout


def _status():
    try:
        return json.loads(_run(["status"], check=False) or "{}")
    except ValueError:
        return {}


def session(force=False):
    """A BW_SESSION key, logging in and unlocking as needed (kept in memory only, SESSION_S)."""
    if not available():
        raise ToolError("Bitwarden isn't connected (set " + ", ".join(missing()) + " on the server). Ask the user "
                        "to set it up in Settings > Apps > Bitwarden")
    with _lock:
        if not force and _state["session"] and time.time() - _state["t"] < SESSION_S:
            return _state["session"]
        st = _status()
        want = _env("BW_SERVER")
        if want and st.get("serverUrl", "").rstrip("/") != want.rstrip("/"):
            if st.get("status") not in (None, "unauthenticated"):
                _run(["logout"], check=False)
            _run(["config", "server", want])
            st = {"status": "unauthenticated"}
        if st.get("status") in (None, "unauthenticated"):
            _run(["login", "--apikey"])
        key = _run(["unlock", "--passwordenv", "BW_PASSWORD", "--raw"]).strip()
        if not key:
            raise ToolError("Bitwarden didn't unlock (check BW_PASSWORD)")
        _run(["sync"], session=key, check=False)
        _state.update(session=key, t=time.time())
        return key


def _host(url):
    try:
        return (urllib.parse.urlsplit(url if "://" in url else "https://" + url).hostname or "").lower().lstrip(".")
    except ValueError:
        return ""


def _folder_id(key):
    name = _env("BW_FOLDER")
    if not name:
        return None
    try:
        folders = json.loads(_run(["list", "folders", "--search", name], session=key) or "[]")
    except ValueError:
        folders = []
    hit = next((f for f in folders if (f.get("name") or "").strip().lower() == name.lower()), None)
    if not hit:
        raise ToolError(f"there's no Bitwarden folder named {name!r} (BW_FOLDER). Ask the user to make it and put the "
                        "logins Theta may use in it")
    return hit["id"]


def index():
    """[{title, id, hosts, src}] for login items. No secrets kept."""
    key = session()
    args = ["list", "items"]
    fid = _folder_id(key)
    if fid:
        args += ["--folderid", fid]
    try:
        items = json.loads(_run(args, session=key) or "[]")
    except ValueError:
        raise ToolError("Bitwarden answered with something that isn't a list of logins") from None
    out = []
    for it in items:
        if it.get("type") != 1 or not isinstance(it.get("login"), dict):
            continue
        hosts = sorted({_host(u.get("uri") or "") for u in it["login"].get("uris") or [] if u.get("uri")} - {""})
        out.append({"title": it.get("name") or "(no name)", "id": it.get("id"), "hosts": hosts, "src": "bitwarden"})
    del items
    return out


def secrets_for(item):
    """{"username", "password", "totp"} for one item (the current code, not the seed). Only browser.py uses it."""
    key = session()
    try:
        full = json.loads(_run(["get", "item", str(item["id"])], session=key) or "{}")
    except ValueError:
        raise ToolError("Bitwarden answered with something that isn't a login") from None
    login = full.get("login") or {}
    seed = login.get("totp") or ""
    out = {"username": login.get("username") or "", "password": login.get("password") or "",
           "totp": totp(seed) if seed else ""}
    full.clear()
    return out


# ---------------------------------------------------------------- one-time codes (RFC 6238)

def totp(seed, now=None):
    """The current code for a base32 seed or an otpauth:// URI. "" for formats Theta can't compute (e.g. steam://)."""
    seed = str(seed or "").strip()
    digits, period, algo = 6, 30, "sha1"
    if seed.lower().startswith("otpauth://"):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(seed).query)
        seed = (q.get("secret") or [""])[0]
        try:
            digits = int((q.get("digits") or ["6"])[0])
            period = int((q.get("period") or ["30"])[0]) or 30
        except ValueError:
            return ""
        algo = (q.get("algorithm") or ["sha1"])[0].lower()
    elif "://" in seed:
        return ""
    if algo not in ("sha1", "sha256", "sha512") or not 6 <= digits <= 10:
        return ""
    clean = seed.replace(" ", "").replace("-", "").upper()
    try:
        k = base64.b32decode(clean + "=" * (-len(clean) % 8))
    except (ValueError, TypeError):
        return ""
    counter = int((now if now is not None else time.time()) // period)
    mac = hmac.new(k, struct.pack(">Q", counter), getattr(hashlib, algo)).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def reset():
    """Forget the session key (tests, or after the user changes the variables)."""
    with _lock:
        _state.update(session="", t=0.0)
