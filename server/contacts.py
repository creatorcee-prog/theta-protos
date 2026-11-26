"""Contacts: the people the user saves so Theta can text, call or email them by name ("text Mom I'm running
late"). The user manages them in Settings > General > Contacts; Theta can look them up, and save one when the
user asks it to.

    GET    /api/contacts                 [{id, name, phone, email, note}]
    POST   /api/contacts {name, phone?, email?, note?, id?}   add, or update the one with that id
    DELETE /api/contacts?id=<id>

Stored as the "contacts" setting. A phone number is kept in international form (+1...); a number typed
without a country code is taken as US/Canada (+1) when it has 10 digits.
"""
import re
import secrets
import threading

from . import db
from .tools import ToolError

SETTING = "contacts"
MAX = 200
_lock = threading.Lock()


def all_contacts():
    v = db.get_setting(SETTING)
    return [c for c in v if isinstance(c, dict) and c.get("id")] if isinstance(v, list) else []


def _save(items):
    db.set_setting(SETTING, items[:MAX])


def phone(raw):
    """A number in international form, or "" if it doesn't look like one."""
    n = re.sub(r"[\s().-]", "", str(raw or ""))
    if n.startswith("00"):
        n = "+" + n[2:]
    if re.fullmatch(r"\d{10}", n):
        n = "+1" + n
    elif re.fullmatch(r"1\d{10}", n):
        n = "+" + n
    return n if re.fullmatch(r"\+\d{8,15}", n) else ""


def _email(raw):
    e = str(raw or "").strip()
    return e if re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}", e) else ""


def clean(body):
    """A contact from user input. Raises ValueError saying what's wrong."""
    name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()[:60]
    if not name:
        raise ValueError("a contact needs a name")
    out = {"name": name, "phone": "", "email": "", "note": re.sub(r"\s+", " ", str(body.get("note") or "")).strip()[:80]}
    if body.get("phone"):
        out["phone"] = phone(body["phone"])
        if not out["phone"]:
            raise ValueError("that phone number doesn't look right; use the full number, like +1 303 555 1234")
    if body.get("email"):
        out["email"] = _email(body["email"])
        if not out["email"]:
            raise ValueError("that email address doesn't look right")
    if not out["phone"] and not out["email"]:
        raise ValueError("add a phone number or an email address")
    return out


def upsert(body):
    c = clean(body)
    with _lock:
        items = all_contacts()
        cid = str(body.get("id") or "")
        for i, old in enumerate(items):
            if old["id"] == cid or (not cid and old["name"].lower() == c["name"].lower()):
                if old["name"].lower() == c["name"].lower():
                    c["name"] = old["name"]  # "save mom's number" keeps the name as they first wrote it
                items[i] = dict(old, **c)
                _save(items)
                return items[i]
        if len(items) >= MAX:
            raise ValueError(f"that's the {MAX}-contact limit; remove one first")
        c["id"] = secrets.token_hex(4)
        items.append(c)
        _save(items)
        return c


def remove(cid):
    with _lock:
        items = all_contacts()
        keep = [c for c in items if c["id"] != cid]
        _save(keep)
        return len(keep) != len(items)


def find(query):
    """Contacts matching a name, relation note, number or email (best first)."""
    q = str(query or "").strip().lower()
    if not q:
        return []
    out = []
    for c in all_contacts():
        name, note = c["name"].lower(), (c.get("note") or "").lower()
        if q == name or q == note:
            rank = 0
        elif name.startswith(q) or q in name.split() or q == note.split(" ")[0]:
            rank = 1
        elif q in name or q in note or q in (c.get("email") or "").lower() or (phone(q) and phone(q) == c.get("phone")):
            rank = 2
        else:
            continue
        out.append((rank, c))
    return [c for _, c in sorted(out, key=lambda x: x[0])]


def resolve(to, need="phone"):
    """A number (or email) for `to`: a contact's name, or the number/address itself. Raises ToolError."""
    raw = str(to or "").strip()
    direct = phone(raw) if need == "phone" else _email(raw)
    if direct:
        hit = next((c for c in all_contacts() if c.get(need) == direct), None)
        return direct, (hit or {}).get("name") or ""
    hits = find(raw)
    if not hits:
        raise ToolError(f"there's no saved contact called {raw!r}. Ask the user for the {need} number" if need == "phone"
                        else f"there's no saved contact called {raw!r}. Ask the user for the email address")
    best = [c for c in hits if c.get(need)]
    if not best:
        raise ToolError(f"{hits[0]['name']} has no {'phone number' if need == 'phone' else 'email'} saved. Ask the user for it")
    if len(best) > 1 and best[0]["name"].lower() != raw.lower() and best[1]["name"].lower() != raw.lower():
        names = ", ".join(c["name"] for c in best[:4])
        raise ToolError(f"{raw!r} matches more than one contact ({names}). Ask the user which one")
    return best[0][need], best[0]["name"]


# ---------------------------------------------------------------- tools

def _t_find(args, ctx):
    hits = find(args.get("query"))
    if not hits:
        return f"No saved contact matches {args.get('query')!r}."
    return "\n".join(f"- {c['name']}" + (f" ({c['note']})" if c.get("note") else "") +
                     (f", phone {c['phone']}" if c.get("phone") else "") + (f", email {c['email']}" if c.get("email") else "")
                     for c in hits[:8])


def _t_save(args, ctx):
    try:
        c = upsert(args)
    except ValueError as e:
        raise ToolError(str(e)) from None
    return f"Saved {c['name']}" + (f" ({c['note']})" if c.get("note") else "") + ". They can edit it in Settings > General > Contacts."


TOOLS = [
    {"name": "find_contact", "risk": "read", "run": _t_find,
     "description": ("Look up the user's saved contacts by name, relation or number ('Mom', 'Sam', 'my landlord'). "
                     "Use it before texting, calling or emailing someone by name. Example: {\"query\": \"Mom\"}."),
     "params": {"type": "object", "properties": {"query": {"type": "string", "description": "A name, relation or number."}},
                "required": ["query"]}},
    {"name": "save_contact", "risk": "write", "run": _t_save,
     "description": ("Save or update a contact, only when the user asks you to ('save Sam's number, 303 555 1234'). "
                     "Example: {\"name\": \"Sam Rivera\", \"phone\": \"+13035551234\", \"note\": \"landlord\"}."),
     "params": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Their name."},
         "phone": {"type": "string", "description": "Phone number, international form if you know it."},
         "email": {"type": "string", "description": "Email address."},
         "note": {"type": "string", "description": "Who they are to the user: mom, landlord, boss."}},
         "required": ["name"]}},
]

RELEVANT = (r"\b(text|txt|message|msg|sms|call|ring|phone|email|e-mail)\b|\bcontacts?\b|\bnumber\b|\bsave\b.*\b(number|email)\b")


def context(bot, now):
    items = all_contacts()
    if not items:
        return ""
    names = ", ".join(c["name"] + (f" ({c['note']})" if c.get("note") else "") for c in items[:30])
    return f"Saved contacts (look one up with find_contact for the number): {names}."


# ---------------------------------------------------------------- route

def route(req, start_response):
    from .app import HTTPError, respond_json
    if req.method == "GET":
        return respond_json(start_response, all_contacts())
    if req.method == "POST":
        body = req.json()
        if not isinstance(body, dict):
            raise HTTPError(400, "send a JSON object")
        try:
            return respond_json(start_response, upsert(body))
        except ValueError as e:
            raise HTTPError(400, str(e)) from None
    if req.method == "DELETE":
        cid = str(req.query.get("id") or "")
        if not remove(cid):
            raise HTTPError(404, "no such contact")
        return respond_json(start_response, {"ok": True})
    raise HTTPError(405, "method not allowed")


ROUTES = {"/api/contacts": route}
