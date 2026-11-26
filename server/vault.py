"""1Password: Theta's browser signs in to the user's accounts with logins from 1Password, and the model never sees a
password or a one-time code.

Setup: a 1Password service account (developer.1password.com > Service accounts) with read access to one vault, e.g.
"Theta", holding only the logins the user wants Theta to use. Its token goes on Railway as OP_SERVICE_ACCOUNT_TOKEN.
The Python SDK (`onepassword-sdk`, async) does the rest.

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


def available():
    if not _token():
        return False
    try:
        import onepassword  # noqa: F401
        return True
    except ImportError:
        return False


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
    """[{title, vault_id, id, hosts}] for login items, cached INDEX_S. No secrets."""
    with _lock:
        if not force and time.time() - _cache["t"] < INDEX_S:
            return _cache["items"]

    async def job(client):
        out = []
        for v in await client.vaults.list():
            for it in await client.items.list(v.id):
                cat = str(getattr(getattr(it, "category", None), "value", getattr(it, "category", "")))
                if cat not in ("Login", "Password"):
                    continue
                hosts = sorted({_host(w.url) for w in (getattr(it, "websites", None) or []) if getattr(w, "url", "")} - {""})
                out.append({"title": it.title, "vault_id": v.id, "id": it.id, "hosts": hosts})
        return out
    items = _run(job)
    with _lock:
        _cache.update(t=time.time(), items=items)
    return items


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
        raise ToolError(f"there's no 1Password login saved for {host}. Ask the user to add one (with this site's "
                        "address) to the vault Theta can read")
    if len(fits) > 1:
        raise ToolError(f"more than one 1Password login fits {host}: " + ", ".join(i["title"] for i in fits[:6]) +
                        ". Call again with item set to one of those titles")
    return fits[0]


def secrets_for(item):
    """{"username", "password", "totp"} for one item. Only browser.py calls this; the values never leave the server."""
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
        raise ToolError("1Password isn't connected (OP_SERVICE_ACCOUNT_TOKEN on the server). Ask the user to set it up "
                        "in Settings > Apps > 1Password")
    items = index(force=bool(args.get("refresh")))
    site = _host(str(args.get("site") or ""))
    if site:
        items = [i for i in items if _matches(site, i["hosts"]) or any(site in h for h in i["hosts"])]
    if not items:
        return "No logins found" + (f" for {site}." if site else " in the vault Theta can read.")
    return "\n".join(f"- {i['title']}: {', '.join(i['hosts']) or '(no website saved)'}" for i in items[:60])


TOOLS = [
    {"name": "vault_logins", "risk": "read", "run": _t_logins,
     "description": ("List the logins Theta may use from the user's 1Password (titles and sites only; never "
                     "passwords). Use it to see whether a site can be signed in to, then browse_sign_in on that "
                     "site's sign-in page. Example: {\"site\": \"amazon.com\"}."),
     "params": {"type": "object", "properties": {"site": {"type": "string"}, "refresh": {"type": "boolean"}}}},
]

RELEVANT = r"\b(log ?in|sign ?in|password|1password|account|portal)\b"


def connections():
    return [{"id": "1password", "name": "1Password", "cat": "Passwords", "connected": available(),
             "what": "Theta's browser signs in with your saved logins; it never sees the passwords",
             **({} if available() else {"note": "Set OP_SERVICE_ACCOUNT_TOKEN on the server (a 1Password service account for one vault)."})}]


def context(bot, now):
    return ("1Password: connected. To sign in somewhere, open its sign-in page, then browse_sign_in." if available() else "")
