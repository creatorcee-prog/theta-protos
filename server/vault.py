"""Password managers: Theta's browser signs in to the user's accounts with logins from 1Password or Bitwarden
(server/bitwarden.py), and the model never sees a password or a one-time code. Either one, or both, can be connected;
their logins are merged and each keeps a `src` saying where it came from.

1Password setup: a 1Password service account (developer.1password.com > Service accounts) with read access to one vault, e.g.
"Theta", holding only the logins the user wants Theta to use. Its token goes on Railway as OP_SERVICE_ACCOUNT_TOKEN.
The Python SDK (`onepassword-sdk`, async) does the rest.

Bitwarden setup: see server/bitwarden.py (an API key and the master password, for the bw CLI).

What the model gets: login titles and their sites (vault_logins), and browse_sign_in, which fills the page's
username, password and one-time-code fields in Theta's own browser from here. Values never pass through a tool
result, a log or the chat.

Guard: a login is only used on a page whose host matches one of the item's saved websites (same host, or a
subdomain of it), over https. A look-alike site gets nothing.
"""
import asyncio
import os
import re
import threading
import time
import urllib.parse

from .tools import ToolError

INDEX_S = 600
_cache = {"t": 0.0, "items": []}
_lock = threading.Lock()


def _token():
    return (os.environ.get("OP_SERVICE_ACCOUNT_TOKEN") or "").strip()


def op_available():
    if not _token():
        return False
    try:
        import onepassword  # noqa: F401
        return True
    except ImportError:
        return False


def _bw():
    from . import bitwarden
    return bitwarden


def available():
    """True when at least one password manager is connected."""
    return op_available() or _bw().available()


def names():
    return [n for n, ok in (("1Password", op_available()), ("Bitwarden", _bw().available())) if ok]


NOT_CONNECTED = ("no password manager is connected (1Password or Bitwarden), so nothing was filled. Ask the user to "
                 "connect one in Settings > Apps (1Password or Bitwarden)")


def _run(coro_fn):
    """Run one async SDK job to completion on its own event loop (the server is threaded, not async)."""
    async def go():
        from onepassword import Client
        client = await Client.authenticate(auth=_token(), integration_name="Theta", integration_version="1.0")
        return await coro_fn(client)
    try:
        return asyncio.run(go())
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001  never echo anything that could hold a secret
        raise ToolError(f"1Password didn't answer ({type(e).__name__}); check OP_SERVICE_ACCOUNT_TOKEN") from None


def _host(url):
    try:
        return (urllib.parse.urlsplit(url if "://" in url else "https://" + url).hostname or "").lower().lstrip(".")
    except ValueError:
        return ""


def index(force=False):
    """[{title, id, hosts, src, ...}] for login items from every connected manager, cached INDEX_S. No secrets.
    One manager failing doesn't hide the other's logins; if every one fails, its error is raised."""
    with _lock:
        if not force and time.time() - _cache["t"] < INDEX_S:
            return _cache["items"]
    items, errs = [], []
    for ok, fn in ((op_available(), _op_index), (_bw().available(), _bw().index)):
        if not ok:
            continue
        try:
            items += fn()
        except ToolError as e:
            errs.append(e)
    if errs and not items:
        raise errs[0]
    with _lock:
        _cache.update(t=time.time(), items=items)
    return items


def _op_index():
    async def job(client):
        out = []
        for v in await client.vaults.list():
            for it in await client.items.list(v.id):
                cat = str(getattr(getattr(it, "category", None), "value", getattr(it, "category", "")))
                if cat not in ("Login", "Password"):
                    continue
                hosts = sorted({_host(w.url) for w in (getattr(it, "websites", None) or []) if getattr(w, "url", "")} - {""})
                out.append({"title": it.title, "vault_id": v.id, "id": it.id, "hosts": hosts, "src": "1password"})
        return out
    return _run(job)


def _matches(page_host, item_hosts):
    return any(page_host == h or page_host.endswith("." + h) for h in item_hosts)


def pick(page_url, title=None):
    """The login item for this page (and title, when several fit). Raises ToolError saying what to do."""
    if not page_url.startswith("https://"):
        raise ToolError("Theta only signs in over https")
    host = _host(page_url)
    fits = [i for i in index() if _matches(host, i["hosts"])]
    if title:
        fits = [i for i in fits if i["title"].lower() == str(title).strip().lower()] or \
               [i for i in fits if str(title).strip().lower() in i["title"].lower()]
    if not fits:
        raise ToolError(f"there's no saved login for {host} in {' or '.join(names()) or 'a password manager'}. Ask the "
                        "user to add one (with this site's address) where Theta can read it, or to sign in "
                        "themselves on Theta's screen")
    if len(fits) > 1:
        raise ToolError(f"more than one saved login fits {host}: " + ", ".join(i["title"] for i in fits[:6]) +
                        ". Call again with item set to one of those titles")
    return fits[0]


def secrets_for(item):
    """{"username", "password", "totp"} for one item. Only browser.py calls this; the values never leave the server."""
    if item.get("src") == "bitwarden":
        return _bw().secrets_for(item)

    async def job(client):
        full = await client.items.get(item["vault_id"], item["id"])
        user = pw = totp = ""
        for f in full.fields or []:
            kind = str(getattr(getattr(f, "field_type", None), "value", getattr(f, "field_type", "")))
            fid, title = (f.id or "").lower(), (f.title or "").lower()
            if not user and (fid == "username" or title in ("username", "email", "user name", "login")):
                user = f.value or ""
            elif not pw and (fid == "password" or (kind == "Concealed" and "password" in title)):
                pw = f.value or ""
            elif not totp and kind == "Totp":
                code = getattr(getattr(getattr(f, "details", None), "content", None), "code", None)
                totp = code or ""
        return {"username": user, "password": pw, "totp": totp}
    return _run(job)


# ---------------------------------------------------------------- tool

def _t_logins(args, ctx):
    if not available():
        raise ToolError(NOT_CONNECTED)
    items = index(force=bool(args.get("refresh")))
    site = _host(str(args.get("site") or ""))
    if site:
        items = [i for i in items if _matches(site, i["hosts"]) or any(site in h for h in i["hosts"])]
    if not items:
        return "No logins found" + (f" for {site}." if site else " in the vault Theta can read.")
    src = {"1password": "1Password", "bitwarden": "Bitwarden"}
    return "\n".join(f"- {i['title']} ({src.get(i.get('src'), '?')}): {', '.join(i['hosts']) or '(no website saved)'}"
                     for i in items[:60])


TOOLS = [
    {"name": "vault_logins", "risk": "read", "run": _t_logins,
     "description": ("List the logins Theta may use from the user's 1Password or Bitwarden (titles and sites only; never "
                     "passwords). Use it to see whether a site can be signed in to, then browse_sign_in on that "
                     "site's sign-in page. Example: {\"site\": \"amazon.com\"}."),
     "params": {"type": "object", "properties": {"site": {"type": "string"}, "refresh": {"type": "boolean"}}}},
]

RELEVANT = r"\b(log ?in|sign ?in|password|1password|bitwarden|account|portal)\b"


def connections():
    bw = _bw()
    return [{"id": "1password", "name": "1Password", "cat": "Passwords", "connected": op_available(),
             "what": "Theta's browser signs in with your saved logins; it never sees the passwords",
             **({} if op_available() else {"note": "Set OP_SERVICE_ACCOUNT_TOKEN on the server (a 1Password service account for one vault)."})},
            {"id": "bitwarden", "name": "Bitwarden", "cat": "Passwords", "connected": bw.available(),
             "what": "Theta's browser signs in with your Bitwarden logins; it never sees the passwords",
             **({} if bw.available() else {"note": "Set BW_CLIENTID, BW_CLIENTSECRET and BW_PASSWORD on the server "
                                           "(and BW_FOLDER to limit it to one folder)."})}]


def context(bot, now):
    if not available():
        return ""
    return (f"Passwords: {' and '.join(names())} connected. To sign in somewhere, open its sign-in page, then "
            "browse_sign_in.")
