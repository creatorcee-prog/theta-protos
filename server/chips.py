"""Chips: Theta's skills. A chip is a short playbook for one kind of job ("Morning brief", "Inbox sweep"): when
it fits, and the steps Theta follows. Theta sees the list of chips that are on (name and when) in every tool turn,
and opens one with chip_open when a request fits, the way a person pulls up their checklist. Tapping a chip in the
chat (the row above the box) runs it now.

    GET    /api/chips                  {chips: [{id, name, icon, when, prompt, steps, builtin, edited, on}]}
    POST   /api/chips {chip: {...}}    add or edit one (an edited built-in keeps its id; Reset brings it back)
    POST   /api/chips {id, on}         turn one on or off
    DELETE /api/chips?id=...           delete yours, or reset a built-in

Tools: chip_open (read) gives a chip's steps; chip_save (write) makes or updates one when the user asks ("make that
a chip"). Chips are the user's own words: steps never grant anything the rules don't (sending still asks, etc.).
"""
import re
import time

from . import db

MAX_CHIPS = 40
LIMITS = {"name": 40, "icon": 8, "when": 240, "prompt": 400, "steps": 3000}

DEFAULTS = [
    {"id": "morning-brief", "name": "Morning brief", "icon": "☀️",
     "when": "They ask for a brief, a rundown of the day, or 'what's going on today'.",
     "prompt": "Give me my morning brief.",
     "steps": (
         "1. Weather where they are today: the high, the low and anything to plan around (rain, wind, snow).\n"
         "2. Today's calendar: each event with its time, and the first thing they need to leave for.\n"
         "3. Email that needs them: at most 3, each in one line, skipping newsletters and receipts.\n"
         "4. Reminders due today and anything on their saved plan.\n"
         "5. One line at the end only if something needs a decision.\n"
         "Keep it scannable: bold the times. Skip any part that has nothing in it rather than saying 'nothing'. "
         "If an app isn't connected, leave that part out and mention it once at the end.")},
    {"id": "inbox-sweep", "name": "Inbox sweep", "icon": "📥",
     "when": "They want their inbox cleaned up, triaged or brought to zero.",
     "prompt": "Sweep my inbox.",
     "steps": (
         "1. Read the last 7 days of inbox (gmail_search 'in:inbox newer_than:7d').\n"
         "2. Archive newsletters, promotions, receipts and notifications they've had for over 2 days (gmail_archive "
         "by query, so it's all of them, not a sample). Archiving can be undone: just do it.\n"
         "3. Unsubscribe from senders that are plainly marketing and that they never open (gmail_unsubscribe).\n"
         "4. For mail from real people that needs an answer, draft a reply in their voice (gmail_reply_draft).\n"
         "5. Report: how many archived, who they're unsubscribed from, and the drafts waiting, each in one line, "
         "with how to undo ('say restore and I'll put them back').")},
    {"id": "plan-my-day", "name": "Plan my day", "icon": "🗓️",
     "when": "They ask to plan their day, organize their time, or figure out what to do first.",
     "prompt": "Plan my day.",
     "steps": (
         "1. Check today's calendar, reminders and their saved plan.\n"
         "2. Pick the 3 things that matter most, from what's due, what's waiting on them in email and what they "
         "said earlier in chat.\n"
         "3. Fit them around the fixed events in realistic blocks, with a break, and the time to leave for anything "
         "away from home.\n"
         "4. Save it with plan_update (steps in order) and set reminders for anything time-bound (remind_me).\n"
         "5. Reply with the plan as a short list with times in bold. Don't ask first: they can change it.")},
    {"id": "best-price", "name": "Best price", "icon": "🏷️",
     "when": "They want to buy something and want the best deal, or ask where something is cheapest.",
     "prompt": "Find me the best price on ",
     "steps": (
         "1. Pin down the exact item (model, size, color). If it's vague, pick the most popular match and say so.\n"
         "2. Search the web for it, then open the stores in Theta's browser (at least 3: e.g. Amazon, the maker's "
         "own store, Walmart, Best Buy, Target) and read the real price on each page.\n"
         "3. For each: price, shipping, delivery date, return window, and whether it's sold by the store or a third "
         "party.\n"
         "4. Reply with the best total price first, then a short comparison. Link each store.\n"
         "5. Save the best one to their Home with home_post (kind deal, with the price and link).\n"
         "Never buy or add a card: buying waits for their OK, every time.")},
    {"id": "money-check", "name": "Money check", "icon": "💸",
     "when": "They ask how their spending is going, about subscriptions, or about money this month.",
     "prompt": "How's my money looking this month?",
     "steps": (
         "1. Balances (bank_accounts).\n"
         "2. The last 30 days of transactions (bank_transactions days=30): total spent, total in, and the top 5 "
         "places money went, grouped sensibly (groceries, eating out, subscriptions...).\n"
         "3. Subscriptions: charges that repeat (look at 60 days); flag any that went up or look unused.\n"
         "4. Anything unusual: a big or duplicate charge, a fee.\n"
         "5. Reply short, amounts in bold, and end with the one thing worth doing (if any). Read-only: Theta can't "
         "move money. If no bank is connected, say how to connect one (Settings > Apps > Bank accounts).")},
]
_BY_ID = {c["id"]: c for c in DEFAULTS}


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:40]
    return s or "chip-" + str(int(time.time()))


def _user():
    v = db.get_setting("chips")
    return [c for c in (v if isinstance(v, list) else []) if isinstance(c, dict) and c.get("id")]


def _state():
    v = db.get_setting("chips_state")
    return v if isinstance(v, dict) else {}


def all_chips():
    """Built-ins (or the user's edit of them) first, then the user's own; each with on/builtin/edited."""
    user = {c["id"]: c for c in _user()}
    st = _state()
    out = []
    for d in DEFAULTS:
        mine = user.pop(d["id"], None)
        out.append({**(mine or d), "builtin": True, "edited": mine is not None,
                    "on": (st.get(d["id"]) or {}).get("on", True)})
    for c in user.values():
        out.append({**c, "builtin": False, "edited": False, "on": (st.get(c["id"]) or {}).get("on", True)})
    return out


def enabled():
    return [c for c in all_chips() if c["on"]]


def find(name_or_id):
    q = str(name_or_id or "").strip().lower()
    if not q:
        return None
    chips = all_chips()
    return (next((c for c in chips if c["id"] == q or c["name"].lower() == q), None)
            or next((c for c in chips if q in c["name"].lower()), None))


def clean(body):
    c = {k: re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(body.get(k) or "")).strip()[:cap] for k, cap in LIMITS.items()}
    if not c["name"]:
        raise ValueError("a chip needs a name")
    if not c["steps"]:
        raise ValueError("a chip needs steps (what Theta should do)")
    c["icon"] = c["icon"] or "✨"
    c["prompt"] = c["prompt"] or c["name"]
    c["id"] = str(body.get("id") or "").strip()[:60] or _slug(c["name"])
    if not re.fullmatch(r"[a-z0-9-]{1,60}", c["id"]):
        raise ValueError("bad chip id")
    return c


def save(body):
    c = clean(body)
    user = [u for u in _user() if u["id"] != c["id"]]
    if c["id"] not in _BY_ID and not body.get("id"):
        taken = {x["id"] for x in all_chips()}
        base, n = c["id"], 2
        while c["id"] in taken:
            c["id"] = f"{base}-{n}"
            n += 1
    if len(user) >= MAX_CHIPS:
        raise ValueError(f"at most {MAX_CHIPS} chips; delete one first")
    db.set_setting("chips", user + [c])
    return c


def set_on(cid, on):
    if not any(c["id"] == cid for c in all_chips()):
        raise ValueError("no such chip")
    st = _state()
    st[cid] = {"on": bool(on)}
    db.set_setting("chips_state", st)


def remove(cid):
    """Delete a user's chip, or reset a built-in to Theta's version."""
    if not any(c["id"] == cid for c in all_chips()):
        raise ValueError("no such chip")
    db.set_setting("chips", [u for u in _user() if u["id"] != cid])
    if cid not in _BY_ID:
        st = _state()
        st.pop(cid, None)
        db.set_setting("chips_state", st)


# ---------------------------------------------------------------- tools

def _t_open(args, ctx):
    from .tools import ToolError
    c = find(args.get("name"))
    if not c:
        raise ToolError("no chip by that name. These are on: " + ", ".join(x["name"] for x in enabled()))
    if not c["on"]:
        return f"The {c['name']} chip is turned off in Settings > Chips; do the job your usual way."
    return (f"Chip: {c['name']}\nWhen: {c['when']}\nSteps (the user's playbook; follow them, within your rules: "
            f"sending, buying and anything that can't be undone still need their OK):\n{c['steps']}")


def _t_save(args, ctx):
    from .tools import ToolError
    body = dict(args)
    old = find(args.get("name"))
    if old and not args.get("new"):
        body["id"] = old["id"]
    try:
        c = save(body)
    except ValueError as e:
        raise ToolError(str(e)) from None
    return (f"Saved the chip {c['icon']} {c['name']}. It shows in the chip row above the chat box and in "
            "Settings > Chips, where they can edit it.")


TOOLS = [
    {"name": "chip_open", "risk": "read", "run": _t_open,
     "description": ("Open one of the user's chips (their playbooks for a kind of job, listed in your context): "
                     "returns its steps. Call it first whenever a request fits a chip, then follow the steps. "
                     "Example: {\"name\": \"Morning brief\"}."),
     "params": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "chip_save", "risk": "write", "run": _t_save,
     "description": ("Make or update a chip (a reusable playbook) when the user asks ('make that a chip', 'save "
                     "this as a skill'). Write steps as a short numbered list of what to do, in plain words, from "
                     "what you just did. when: the kind of request it fits. prompt: what tapping it sends. "
                     "Example: {\"name\": \"Gym check-in\", \"icon\": \"🏋️\", \"when\": \"They ask about the "
                     "gym\", \"prompt\": \"Check me into the gym\", \"steps\": \"1. ...\"}."),
     "params": {"type": "object", "properties": {
         "name": {"type": "string"}, "icon": {"type": "string", "description": "One emoji."},
         "when": {"type": "string"}, "prompt": {"type": "string"}, "steps": {"type": "string"},
         "new": {"type": "boolean", "description": "true to make a new chip even if one has this name."}},
         "required": ["name", "steps"]}},
]

RELEVANT = r"\b(chips?|skills?|playbooks?|brief|sweep|plan my day|best price|money check)\b"


def context(bot, now):
    on = enabled()
    if not on:
        return ""
    return ("Chips (the user's playbooks; when a request fits one, call chip_open first and follow it): "
            + "; ".join(f"{c['name']} ({c['when'][:90]})" for c in on[:20]) + ".")


# ---------------------------------------------------------------- route

def route(req, start):
    from .app import HTTPError, respond_json
    try:
        if req.method == "POST":
            body = req.json() or {}
            if "on" in body and body.get("id") and "chip" not in body:
                set_on(str(body["id"]), body["on"])
            elif isinstance(body.get("chip"), dict):
                save(body["chip"])
            else:
                raise HTTPError(400, "send {chip} or {id, on}")
        elif req.method == "DELETE":
            remove(str(req.query.get("id") or ""))
        elif req.method != "GET":
            raise HTTPError(405, "method not allowed")
    except ValueError as e:
        raise HTTPError(400, str(e)) from None
    return respond_json(start, {"chips": all_chips()})


ROUTES = {"/api/chips": route}
