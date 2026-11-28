"""Agents: assistants the user makes beside Theta, each with a name, a globe color, what it's for, the user's own
instructions, and the apps it may use. Each has its own chat (messages are already kept per bot) and sees the
same memory of the user as Theta does. Theta itself is always there and can't be removed or limited.

Stored as the setting "agents": [{id, name, color, about, instructions, apps, created}], newest last.
`apps` is None for every app, or a list of APP keys; the tools for apps it may not use are never offered.
"""
import re
import time

from . import db

THETA = {"id": "theta", "name": "Theta", "builtin": True, "color": None, "about": "Your main assistant", "apps": None,
         "avatar": {"kind": "dot-globe", "theme": "theta", "color": "#7cc4ff"}}
MAX = 12

# app key -> (label, tool-name pattern). Tools matching no app (memory, reminders, cards, web search...) are always
# available: they're how any agent works at all.
APPS = {
    "email": ("Email", r"^(gmail_|send_email)"),
    "calendar": ("Calendar", r"^calendar_"),
    "drive": ("Drive and docs", r"^(drive_|docs_|slides_)"),
    "texts": ("Texts and contacts", r"^(send_text|save_contact)$"),
    "calls": ("Phone calls", r"^call_"),
    "browser": ("Browser", r"^(browse_|vault_)"),
    "money": ("Bank", r"^bank_"),
    "routines": ("Routines", r"^(routine_|workflow_)"),
    "images": ("Images", r"^generate_image$"),
}
COLORS = ("#4fd3ff", "#a78bfa", "#ff7ab6", "#ffb35c", "#4cd07d", "#ff6a5c", "#5b7cff", "#ffd54a")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .'&-]{0,23}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class AgentError(ValueError):
    pass


def _stored():
    v = db.get_setting("agents")
    return [a for a in v if isinstance(a, dict) and a.get("id")] if isinstance(v, list) else []


def all_agents():
    """Theta first, then the user's agents in the order they were made."""
    return [dict(THETA)] + [dict(a, builtin=False) for a in _stored()]


def ids():
    return {a["id"] for a in all_agents()}


def get(agent_id):
    return next((a for a in all_agents() if a["id"] == agent_id), None)


def _clean(body, partial=False, current=None):
    out = {}
    if "name" in body or not partial:
        name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()
        if not _NAME.match(name):
            raise AgentError("A name is 1 to 24 letters, numbers, spaces or . ' & -")
        if name.lower() == "theta" or any(a["name"].lower() == name.lower() and a["id"] != (current or {}).get("id")
                                          for a in all_agents()):
            raise AgentError("There's already an agent called that")
        out["name"] = name
    if "color" in body or not partial:
        c = str(body.get("color") or "")
        out["color"] = c if _HEX.match(c) else COLORS[len(_stored()) % len(COLORS)]
    if "about" in body or not partial:
        out["about"] = re.sub(r"\s+", " ", str(body.get("about") or "")).strip()[:140]
    if "instructions" in body or not partial:
        out["instructions"] = str(body.get("instructions") or "").strip()[:2000]
    if "apps" in body or not partial:
        apps = body.get("apps")
        out["apps"] = None if apps is None else [a for a in dict.fromkeys(str(x) for x in apps) if a in APPS]
    return out


def create(body):
    have = _stored()
    if len(have) >= MAX:
        raise AgentError(f"Up to {MAX} agents")
    a = dict(_clean(body or {}), created=int(time.time()))
    base = re.sub(r"[^a-z0-9]+", "-", a["name"].lower()).strip("-")[:20] or "agent"
    aid, n = base, 2
    while aid in ids() or aid in ("theta", "all"):
        aid, n = f"{base}-{n}", n + 1
    a["id"] = aid
    db.set_setting("agents", have + [a])
    return dict(a, builtin=False)


def update(agent_id, body):
    if agent_id == "theta":
        raise AgentError("Theta's name is set in Settings > Personalization")
    have = _stored()
    cur = next((a for a in have if a["id"] == agent_id), None)
    if not cur:
        raise AgentError("No such agent")
    cur.update(_clean(body or {}, partial=True, current=cur))
    db.set_setting("agents", have)
    return dict(cur, builtin=False)


def delete(agent_id):
    """Removes the agent. Its messages stay in the database (nothing is erased by surprise) but nothing shows them."""
    if agent_id == "theta":
        raise AgentError("Theta can't be removed")
    have = _stored()
    if not any(a["id"] == agent_id for a in have):
        raise AgentError("No such agent")
    db.set_setting("agents", [a for a in have if a["id"] != agent_id])


def allows(agent_id, tool_name):
    """May this agent use this tool? Theta, and agents with every app, may use all of them."""
    a = get(agent_id)
    if not a or a.get("apps") is None:
        return True
    for key, (_, pat) in APPS.items():
        if re.search(pat, tool_name):
            return key in a["apps"]
    return True


def prompt_block(agent_id):
    """Who this agent is, for the system prompt (stable across turns). Empty for Theta."""
    a = get(agent_id)
    if not a or a.get("builtin"):
        return ""
    lines = [f"You are {a['name']}, one of the user's agents in the Theta app. Wherever these instructions say "
             f"Theta, they mean you, {a['name']}. Theta is their main assistant and other agents exist beside you; "
             "you share what you remember about the user, not your chats."]
    if a.get("about"):
        lines.append(f"What you're for: {a['about']}.")
    if a.get("instructions"):
        lines.append("Their instructions for you (follow them over the general style above where they differ):\n"
                     + a["instructions"])
    if a.get("apps") is not None:
        names = [APPS[k][0] for k in a["apps"]]
        lines.append("Apps you may use: " + (", ".join(names) if names else "none beyond search, memory and "
                     "reminders") + ". For anything else, say it's a job for Theta (they can ask Theta in its chat).")
    return "\n\n".join(lines)
