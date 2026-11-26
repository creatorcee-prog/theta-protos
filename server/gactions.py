"""Gmail and Calendar actions beyond reading and drafting: trash, archive, restore, unsubscribe, delete and move
events. Built on server/google.py (its api(), headers and connection checks).

Risk, by the rule that anything that deletes or reaches other people waits for the user's tap:
- gmail_archive, gmail_mark_read, gmail_restore: write (undoable; Theta says how to undo)
- gmail_trash: send (approval card listing each message; Gmail empties Trash after 30 days)
- gmail_unsubscribe: send (approval card naming the sender and how: one-click link or an unsubscribe email)
- calendar_delete, calendar_move: send (guests get Google's update email when there are any)

Unsubscribe follows the sender's List-Unsubscribe header: an https one-click link (RFC 8058, a POST of
"List-Unsubscribe=One-Click") or a mailto address. A plain web link isn't followed, since a GET to an unknown page
can do anything; the user gets the link instead. The link must pass gcal.check_url (https, public host).
"""
import datetime
import re
import urllib.parse
import urllib.request

from . import tools
from .tools import ToolError

MAX_IDS = 25


def _g():
    from . import google
    return google


def _ids(args):
    ids = args.get("message_ids")
    if isinstance(ids, str):
        ids = [i for i in re.split(r"[\s,]+", ids) if i]
    ids = [str(i).strip() for i in ids or [] if str(i).strip()]
    if not ids:
        raise ToolError("message_ids is empty: pass the ids from gmail_search")
    if len(ids) > MAX_IDS:
        raise ToolError(f"at most {MAX_IDS} messages at a time")
    bad = [i for i in ids if not re.fullmatch(r"[0-9a-fA-F]{6,40}", i)]
    if bad:
        raise ToolError(f"not a Gmail message id: {', '.join(bad[:3])}. Use the ids from gmail_search")
    return list(dict.fromkeys(ids))


def _modify(ids, add=(), remove=()):
    g = _g()
    g._need("gmail")
    g.api("POST", f"{g.GMAIL}/messages/batchModify", {"ids": ids, "addLabelIds": list(add), "removeLabelIds": list(remove)})


def _list(ids):
    g = _g()
    out = []
    for mid in ids:
        r = g._msg_row(g._meta(mid))
        out.append(f"- {g._oneline(r['from'], 60)}: {g._oneline(r['subject'], 90) or '(no subject)'}")
    return out


# ---------------------------------------------------------------- Gmail

def _archive(args, ctx):
    ids = _ids(args)
    _modify(ids, remove=["INBOX"])
    return f"Archived {len(ids)} message(s): out of the inbox, still in All Mail. Undo: move them back with gmail_restore."


def _mark_read(args, ctx):
    ids = _ids(args)
    _modify(ids, remove=["UNREAD"])
    return f"Marked {len(ids)} message(s) read."


def _restore(args, ctx):
    ids = _ids(args)
    g = _g()
    g._need("gmail")
    for mid in ids:
        g.api("POST", f"{g.GMAIL}/messages/{urllib.parse.quote(mid)}/untrash")
    _modify(ids, add=["INBOX"])
    return f"Moved {len(ids)} message(s) back to the inbox."


def _trash_preview(args):
    ids = _ids(args)
    _g()._need("gmail")
    return "\n".join([f"**Move {len(ids)} email{'s' if len(ids) != 1 else ''} to Trash**"] + _list(ids) +
                     ["Gmail deletes Trash for good after 30 days. Until then I can put them back."])


def _trash(args, ctx):
    ids = _ids(args)
    _modify(ids, add=["TRASH"], remove=["INBOX"])
    return f"Moved {len(ids)} message(s) to Trash. They can come back for 30 days (gmail_restore)."


def _unsub_headers(mid):
    g = _g()
    m = g.api("GET", f"{g.GMAIL}/messages/{urllib.parse.quote(mid)}",
              params=[("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "List-Unsubscribe"),
                      ("metadataHeaders", "List-Unsubscribe-Post")])
    return g._hdr(m, "From"), g._hdr(m, "List-Unsubscribe"), g._hdr(m, "List-Unsubscribe-Post")


def _unsub_plan(args):
    """(sender, kind, target, extra) where kind is "post" (one-click https) or "mailto"."""
    mid = str(args.get("message_id") or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{6,40}", mid):
        raise ToolError("message_id must be an id from gmail_search (one email from that sender)")
    _g()._need("gmail")
    sender, lu, lup = _unsub_headers(mid)
    links = re.findall(r"<([^>]+)>", lu or "")
    https = [u for u in links if u.lower().startswith("https://")]
    mailto = [u for u in links if u.lower().startswith("mailto:")]
    if https and "one-click" in (lup or "").lower():
        from . import gcal
        try:
            url = gcal.check_url(https[0])
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"the sender's unsubscribe link isn't safe to open ({e}); tell the user to use Gmail's "
                            "own Unsubscribe button on that email") from None
        return sender, "post", url, ""
    if mailto:
        u = urllib.parse.urlsplit(mailto[0])
        to = urllib.parse.unquote(u.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if not tools._EMAIL.match(to):
            raise ToolError("the sender's unsubscribe address isn't a valid email")
        return sender, "mailto", to, q.get("subject") or "unsubscribe"
    if https:
        raise ToolError(f"{sender} only offers a web page to unsubscribe, which I won't open blind. Give the user the "
                        f"link to tap: {https[0][:300]}")
    raise ToolError(f"{sender} doesn't list a way to unsubscribe. Offer to archive or trash their mail, or to make a "
                    "Gmail filter instead")


def _unsub_preview(args):
    sender, kind, target, extra = _unsub_plan(args)
    how = (f"I tap their one-click unsubscribe link ({urllib.parse.urlsplit(target).hostname})." if kind == "post"
           else f"I send an unsubscribe email to {target} from your Gmail (subject: {extra[:80]}).")
    return f"**Unsubscribe from {sender}**\n{how}\nMail already in your inbox stays put."


def _unsubscribe(args, ctx):
    sender, kind, target, extra = _unsub_plan(args)
    if kind == "post":
        from . import gcal
        req = urllib.request.Request(target, data=b"List-Unsubscribe=One-Click", method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "User-Agent": "Theta/1 (unsubscribe)"})
        try:
            with gcal._open(req, timeout=15) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"couldn't reach the unsubscribe link ({type(e).__name__}). Try Gmail's own Unsubscribe "
                            "button on one of their emails") from None
        if code >= 400:
            raise ToolError(f"the sender's unsubscribe link answered {code}. Try Gmail's own Unsubscribe button")
        return f"Unsubscribed from {sender} (their one-click link answered {code}). It can take a few days to stop."
    _g().send(target, extra[:120], "Please unsubscribe me from this list.")
    return f"Sent an unsubscribe request to {target} for {sender}. It can take a few days to stop."


# ---------------------------------------------------------------- Calendar

def _event(eid):
    g = _g()
    g._need("calendar")
    if not re.fullmatch(r"[A-Za-z0-9_@.-]{4,200}", str(eid or "")):
        raise ToolError("event_id must be an id from calendar_list")
    return g.api("GET", f"{g.CAL}/calendars/primary/events/{urllib.parse.quote(str(eid))}")


def _when_text(e):
    g = _g()
    s, all_day = g._ev_time(e.get("start"))
    if s is None:
        return "(no time)"
    return s.strftime("%a %b %-d") + ("" if all_day else s.strftime(", %-I:%M %p"))


def _guests(e):
    me = (_g().account() or "").lower()
    return [a.get("email") for a in e.get("attendees") or [] if a.get("email") and a.get("email").lower() != me]


def _del_preview(args):
    e = _event(args.get("event_id"))
    lines = [f"**Delete from your calendar:** {e.get('summary') or '(no title)'}", _when_text(e)]
    gs = _guests(e)
    if gs:
        lines.append(f"Google emails a cancellation to {', '.join(gs[:6])}{' and others' if len(gs) > 6 else ''}.")
    return "\n".join(lines)


def _delete(args, ctx):
    g = _g()
    e = _event(args.get("event_id"))
    g.api("DELETE", f"{g.CAL}/calendars/primary/events/{urllib.parse.quote(e['id'])}",
          params={"sendUpdates": "all" if _guests(e) else "none"}, raw=True)
    return f"Deleted {e.get('summary') or 'the event'} ({_when_text(e)})."


def _move_body(args, e):
    g = _g()
    start = g._when(args.get("start"), "start")
    old_s, all_day = g._ev_time(e.get("start"))
    old_e, _ = g._ev_time(e.get("end"))
    if all_day or old_s is None or not isinstance(start, datetime.datetime):
        raise ToolError("only timed events can be moved this way; give start as YYYY-MM-DDTHH:MM")
    end = g._when(args.get("end"), "end") if args.get("end") else start + ((old_e - old_s) if old_e else datetime.timedelta(hours=1))
    if end <= start:
        raise ToolError("end must be after start")
    tz = str(g._tz())
    return {"start": {"dateTime": start.isoformat(), "timeZone": tz}, "end": {"dateTime": end.isoformat(), "timeZone": tz}}, start


def _move_preview(args):
    e = _event(args.get("event_id"))
    body, start = _move_body(args, e)
    lines = [f"**Move {e.get('summary') or 'the event'}**", f"From {_when_text(e)} to {start.strftime('%a %b %-d, %-I:%M %p')}"]
    gs = _guests(e)
    if gs:
        lines.append(f"Google emails the new time to {', '.join(gs[:6])}.")
    return "\n".join(lines)


def _move(args, ctx):
    g = _g()
    e = _event(args.get("event_id"))
    body, start = _move_body(args, e)
    g.api("PATCH", f"{g.CAL}/calendars/primary/events/{urllib.parse.quote(e['id'])}", body,
          params={"sendUpdates": "all" if _guests(e) else "none"})
    return f"Moved {e.get('summary') or 'the event'} to {start.strftime('%a %b %-d, %-I:%M %p')}."


_IDS = {"message_ids": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_IDS,
                        "description": "Message ids from gmail_search."}}
_NOT = " If Google isn't connected the tool says so."

TOOLS = [
    {"name": "gmail_archive", "risk": "write", "run": _archive,
     "description": ("Archive emails: take them out of the inbox (they stay in All Mail, undoable). Use it for "
                     "inbox clean-ups once you've shown the user what goes. Example: {\"message_ids\": [\"18c2f0a1b2c3d4e5\"]}." + _NOT),
     "params": {"type": "object", "properties": _IDS, "required": ["message_ids"]}},
    {"name": "gmail_mark_read", "risk": "write", "run": _mark_read,
     "description": "Mark emails as read. Example: {\"message_ids\": [\"18c2f0a1b2c3d4e5\"]}." + _NOT,
     "params": {"type": "object", "properties": _IDS, "required": ["message_ids"]}},
    {"name": "gmail_restore", "risk": "write", "run": _restore,
     "description": "Bring emails back from Trash or the archive into the inbox (the undo for trash and archive)." + _NOT,
     "params": {"type": "object", "properties": _IDS, "required": ["message_ids"]}},
    {"name": "gmail_trash", "risk": "send", "run": _trash, "preview": _trash_preview,
     "description": ("Propose moving emails to Trash. It does NOT delete yet: the user sees each sender and subject "
                     "with Approve / Discard. Up to 25 at a time; Gmail empties Trash after 30 days. Prefer "
                     "gmail_archive when they just want a clean inbox. Example: {\"message_ids\": [\"18c2f0a1b2c3d4e5\"]}." + _NOT),
     "params": {"type": "object", "properties": _IDS, "required": ["message_ids"]}},
    {"name": "gmail_unsubscribe", "risk": "send", "run": _unsubscribe, "preview": _unsub_preview,
     "description": ("Propose unsubscribing from a sender's mailing list, using one email from them. It does NOT "
                     "unsubscribe yet: the user sees the sender and how (one-click link or an unsubscribe email) "
                     "with Approve / Discard. If the sender only has a web page, the tool says so and gives the "
                     "link for the user. Example: {\"message_id\": \"18c2f0a1b2c3d4e5\"}." + _NOT),
     "params": {"type": "object", "properties": {"message_id": {"type": "string", "description": "One email from that sender."}},
                "required": ["message_id"]}},
    {"name": "calendar_delete", "risk": "send", "run": _delete, "preview": _del_preview,
     "description": ("Propose deleting an event from the user's Google Calendar (the id from calendar_list). The "
                     "user approves first; guests, if any, get Google's cancellation email. Example: "
                     "{\"event_id\": \"abc123def456\"}." + _NOT),
     "params": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]}},
    {"name": "calendar_move", "risk": "send", "run": _move, "preview": _move_preview,
     "description": ("Propose moving a timed event to a new start (and optional end; it keeps its length by "
                     "default). The user approves first; guests get the new time. Example: {\"event_id\": "
                     "\"abc123def456\", \"start\": \"2026-11-28T15:00\"}." + _NOT),
     "params": {"type": "object", "properties": {
         "event_id": {"type": "string"},
         "start": {"type": "string", "description": "New start, YYYY-MM-DDTHH:MM in their time zone."},
         "end": {"type": "string", "description": "Optional new end."}},
         "required": ["event_id", "start"]}},
]

RELEVANT = (r"\b(delete|trash|remove|archive|unsubscribe|clean ?up|declutter|mark (as )?read|cancel|move|reschedule|"
            r"push (back|out)|restore|undelete)\b")
