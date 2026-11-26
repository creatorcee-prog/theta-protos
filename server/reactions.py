"""Tapbacks: reactions on messages, like iMessage. Stored in a message's meta.reactions as {"user": "❤️",
"theta": "😂"}: one reaction per side per message, the newest wins, an empty one removes it.

    POST /api/messages/react  {id, emoji, by?: "user"}   -> {"ok": true, "id", "reactions": {...}}
    GET  /api/messages/react?id=<id>                     -> {"id", "reactions": {...}}
    set(msg_id, who, emoji)                              Python, for Theta reacting (who = "user" | "theta")

Theta reacts through the `react` tool (write): on the user's last message, sparingly. The app shows the
reaction in the bubble's corner. The tapback names iMessage uses (heart, like, dislike, haha, emphasize,
question) are accepted too and stored as their emoji.
"""
import re

from . import db

NAMES = {"heart": "❤️", "love": "❤️", "like": "👍", "thumbsup": "👍", "dislike": "👎", "thumbsdown": "👎",
         "haha": "😂", "laugh": "😂", "emphasize": "‼️", "exclaim": "‼️", "question": "❓"}
WHO = ("user", "theta")
_WORDY = re.compile(r"[A-Za-z0-9<>&\"'`\\/{}\[\]()=;:,.\s]")


def clean(emoji):
    """The emoji to store, "" to remove, or None if it isn't one emoji-ish token."""
    if emoji is None:
        return ""
    if not isinstance(emoji, str):
        return None
    e = emoji.strip()
    if not e:
        return ""
    if e.lower() in NAMES:
        return NAMES[e.lower()]
    # one emoji (possibly a ZWJ sequence or with a skin tone / variation selector): short, no letters or markup
    if len(e) > 16 or _WORDY.search(e) or not any(ord(ch) > 0x2000 for ch in e):
        return None
    return e


def get(msg_id):
    m = db.get_message(msg_id)
    if m is None:
        return None
    r = (m.get("meta") or {}).get("reactions")
    return dict(r) if isinstance(r, dict) else {}


def set(msg_id, who, emoji):  # noqa: A001  (the contract's name: reactions.set)
    """Set (or with "" / None, remove) who's reaction on a message. Returns the message's reactions dict, or
    None if there's no such message. Raises ValueError for a bad `who` or something that isn't an emoji."""
    if who not in WHO:
        raise ValueError("who must be 'user' or 'theta'")
    e = clean(emoji)
    if e is None:
        raise ValueError("emoji must be one emoji, or a tapback name: " + ", ".join(sorted(NAMES)))
    cur = get(msg_id)
    if cur is None:
        return None
    if e:
        cur[who] = e
    else:
        cur.pop(who, None)
    db.update_message(msg_id, meta={"reactions": cur or None})
    return cur


def route(req, start):
    from . import app
    if req.method == "GET":
        mid = req.int_arg("id")
        r = get(mid) if mid else None
        if r is None:
            raise app.HTTPError(404, "no such message")
        return app.respond_json(start, {"id": mid, "reactions": r})
    if req.method != "POST":
        raise app.HTTPError(405, "method not allowed")
    body = req.json()
    try:
        mid = int(body.get("id"))
    except (TypeError, ValueError):
        raise app.HTTPError(400, "id is required") from None
    who = body.get("by") or "user"
    if who != "user":  # the phone only ever reacts as you; Theta reacts through its tool
        raise app.HTTPError(400, "by must be 'user'")
    try:
        r = set(mid, who, body.get("emoji"))
    except ValueError as e:
        raise app.HTTPError(400, str(e)) from None
    if r is None:
        raise app.HTTPError(404, "no such message")
    return app.respond_json(start, {"ok": True, "id": mid, "reactions": r})


def _t_react(args, ctx):
    from .tools import ToolError
    ctx = ctx if isinstance(ctx, dict) else {}
    mid = ctx.get("user_id")
    if not mid:
        last = db.last_user_message(ctx.get("bot") or "theta")
        mid = last and last.get("id")
    if not mid:
        raise ToolError("there's no message from the user to react to")
    try:
        r = set(mid, "theta", args.get("emoji"))
    except ValueError as e:
        raise ToolError(str(e)) from None
    if r is None:
        raise ToolError("that message is gone")
    ctx.setdefault("reactions", []).append({"id": mid, "theta": r.get("theta")})
    return (f"Reacted {r.get('theta')} to the user's message. It shows on their bubble; don't mention it "
            "in your reply." if r.get("theta") else "Removed your reaction.")


TOOLS = [
    {"name": "react", "risk": "write", "run": _t_react,
     "description": ("React to the user's last message with an emoji, like a tapback in iMessage: sparingly, "
                     "when a reaction says it better than words (good news, a joke that landed, a thank-you). "
                     "Most messages get no reaction. A reply in words still follows as usual. emoji is one "
                     "emoji, or heart | like | dislike | haha | emphasize | question; \"\" removes yours."),
     "params": {"type": "object", "properties": {
         "emoji": {"type": "string", "description": "One emoji, e.g. \"❤️\" or \"😂\", or a tapback name."}},
         "required": ["emoji"]}},
]

ROUTES = {"/api/messages/react": route}
