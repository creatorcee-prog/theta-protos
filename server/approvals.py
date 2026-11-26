"""Which actions wait for the user's Approve tap, and which Theta may just do (Settings > Security > Approvals).

Every "send" tool asks by default. The user can switch any of them to "just do it". Two kinds, with one guard:
- tidy actions (trash, unsubscribe, delete or move an event, Drive trash) work on the user's own stuff and can
  mostly be undone; when allowed, they run in any turn.
- outward actions (email, text, calls, invites, sharing, website submits) reach other people or spend money; when
  allowed, they still need a turn the user typed (not a routine, not a picked-back-up request) in which nothing
  read outside text (mail, web pages, files), so an email can never get Theta to send something on its own.
Texts keep their own reviewer on top (server/texts.py); their switch is the "texts_auto" setting.

    GET  /api/approvals/policy             [{tool, label, what, auto, outward}]
    POST /api/approvals/policy {tool, auto}
"""
from . import db

SETTING = "auto_approve"
POLICY = [  # (tool, label, what it does, outward)
    ("send_email_draft", "Send emails", "Emails you asked for, from your Gmail", True),
    ("send_text", "Send texts", "To saved contacts, after a second model reviews each one", True),
    ("call_someone", "Call people", "Calls to shops, offices and others for you", True),
    ("calendar_invite", "Send calendar invites", "Google emails each guest", True),
    ("drive_share", "Share Drive files", "Google emails them the link", True),
    ("browse_submit", "Submit on websites", "Buying, booking, paying, posting or signing up", True),
    ("gmail_trash", "Trash emails", "Gmail keeps Trash for 30 days", False),
    ("gmail_unsubscribe", "Unsubscribe", "From mailing lists you pick", False),
    ("calendar_delete", "Delete events", "Guests get Google's cancellation", False),
    ("calendar_move", "Move events", "Guests get the new time", False),
    ("drive_trash", "Trash Drive files", "Drive keeps its trash for 30 days", False),
]
OUTWARD = {t for t, _l, _w, o in POLICY if o}


def _all():
    v = db.get_setting(SETTING)
    return v if isinstance(v, dict) else {}


def on(tool):
    """Is `tool` set to run without a tap?"""
    if tool == "send_text":
        return db.get_setting("texts_auto") is not False
    return bool(_all().get(tool))


def set_on(tool, auto):
    if tool not in {t for t, *_ in POLICY}:
        raise ValueError("that isn't an action with an approval")
    if tool == "send_text":
        db.set_setting("texts_auto", bool(auto))
        return
    v = _all()
    v[tool] = bool(auto)
    db.set_setting(SETTING, v)


def tainted(info):
    """Did this turn read outside text (mail, web, files) before now?"""
    from . import tools
    return any((tools.BY_NAME.get(n) or {}).get("untrusted") for n in ((info or {}).get("tools") or [])[:-1])


def allowed(tool, ctx, info):
    """(True, "") when `tool` may run now without a tap, else (False, why not, or "" when it's simply set to ask)."""
    if not on(tool):
        return False, ""
    if tool not in OUTWARD:
        return True, ""
    ctx = ctx if isinstance(ctx, dict) else {}
    if not ctx.get("user_id") or ctx.get("routine") or ctx.get("resume"):
        return False, "it wasn't a message you typed just now"
    if tainted(info):
        return False, "this turn read outside text (mail, a web page or a file)"
    return True, ""


def policy():
    return [{"tool": t, "label": label, "what": what, "auto": on(t), "outward": out} for t, label, what, out in POLICY]


def route(req, start_response):
    from .app import HTTPError, respond_json
    if req.method == "POST":
        body = req.json()
        if not isinstance(body, dict):
            raise HTTPError(400, "send {tool, auto}")
        try:
            set_on(str(body.get("tool") or ""), bool(body.get("auto")))
        except ValueError as e:
            raise HTTPError(400, str(e)) from None
    elif req.method != "GET":
        raise HTTPError(405, "method not allowed")
    return respond_json(start_response, policy())


ROUTES = {"/api/approvals/policy": route}


def context(bot, now):
    autos = [label for t, label, _w, _o in POLICY if on(t)]
    if not autos:
        return ""
    return ("Allowed without a tap (the user's setting): " + ", ".join(autos) + ". Those run right away when the "
            "tool result says so; report what was done. Everything else waits for their Approve.")
