"""Google Drive, all of it: browse folders, make folders, move, rename, copy, restore, save a photo from the chat,
and (after the user's tap) trash and share. Reading and searching stay in server/google.py.

Risk: anything undoable runs directly and says how to undo (move back, rename back, restore); trash and share wait
for Approve, since sharing reaches other people and trash empties after 30 days.

Full Drive needs the "drive" scope (and Google Contacts the "contacts.readonly" scope), added after the first
sign-ins. A Google sign-in from before lacks them, so once, Theta texts first with a one-tap card to allow them;
a Drive request that needed them is picked back up by server/resume.py after the reconnect.
"""
import json
import re
import time
import urllib.parse

from . import db
from .tools import ToolError

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink"
FIELDS = "id,name,mimeType,parents,webViewLink,modifiedTime,trashed,owners(emailAddress)"
FOLDER = "application/vnd.google-apps.folder"
ASKED = "google_upgrade_asked"


def _g():
    from . import google
    return google


def _full(ctx=None):
    """Raise (with a reconnect card, and the request saved for after) unless full Drive access is granted."""
    g = _g()
    g._need("drive")
    if not g.connected("drive_full"):
        try:
            from . import cards, resume
            cards.attach(ctx, dict(cards.connect("google"), title="Allow full Google Drive",
                                   why="Your Google sign-in only lets me read Drive. One tap to reconnect and allow "
                                       "everything, and I'll do this right after."))
            resume.record(ctx, "gdrive")
        except Exception:  # noqa: BLE001
            pass
        raise ToolError("Google is connected with read-only Drive access, so this can't be done yet. The user sees a "
                        "card to reconnect Google and allow full Drive; you'll pick this back up once they do. Say so.")


def _id(v, what="file_id"):
    v = str(v or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", v):
        raise ToolError(f"{what} must be an id from drive_search or drive_list")
    return v


def _get(fid):
    g = _g()
    return g.api("GET", f"{API}/files/{fid}", params={"fields": FIELDS, "supportsAllDrives": "true"})


def _kind(f):
    return "folder" if f.get("mimeType") == FOLDER else (_g()._KIND.get(f.get("mimeType")) or "file")


def _row(f):
    return f"- {f.get('name')} ({_kind(f)}, id={f.get('id')})"


# ---------------------------------------------------------------- read

def _list(args, ctx):
    g = _g()
    g._need("drive")
    folder = _id(args["folder_id"], "folder_id") if args.get("folder_id") else "root"
    q = f"'{folder}' in parents and trashed = false"
    got = g.api("GET", f"{API}/files", params={"q": q, "fields": "files(id,name,mimeType)", "pageSize": 50,
                                                "orderBy": "folder,modifiedTime desc"})
    files = got.get("files") or []
    if not files:
        return "That folder is empty."
    return f"{len(files)} item(s) in {'My Drive' if folder == 'root' else 'that folder'}:\n" + "\n".join(_row(f) for f in files)


# ---------------------------------------------------------------- write (undoable)

def _mkdir(args, ctx):
    _full(ctx)
    name = str(args.get("name") or "").strip()[:200]
    if not name:
        raise ToolError("name is empty")
    body = {"name": name, "mimeType": FOLDER}
    if args.get("parent_id"):
        body["parents"] = [_id(args["parent_id"], "parent_id")]
    f = _g().api("POST", f"{API}/files", body, params={"fields": FIELDS})
    return f"Made the folder {name!r} (id={f.get('id')}): {f.get('webViewLink', '')}"


def _move(args, ctx):
    _full(ctx)
    fid, to = _id(args.get("file_id")), _id(args.get("folder_id"), "folder_id")
    f = _get(fid)
    old = ",".join(f.get("parents") or [])
    _g().api("PATCH", f"{API}/files/{fid}", {}, params={"addParents": to, "removeParents": old, "fields": "id,parents"})
    return f"Moved {f.get('name')!r} into the folder {to}. Undo: move it back to {old or 'My Drive'}."


def _rename(args, ctx):
    _full(ctx)
    fid = _id(args.get("file_id"))
    name = str(args.get("name") or "").strip()[:200]
    if not name:
        raise ToolError("name is empty")
    f = _get(fid)
    _g().api("PATCH", f"{API}/files/{fid}", {"name": name}, params={"fields": "id,name"})
    return f"Renamed {f.get('name')!r} to {name!r}. Undo: rename it back."


def _copy(args, ctx):
    _full(ctx)
    fid = _id(args.get("file_id"))
    body = {}
    if args.get("name"):
        body["name"] = str(args["name"]).strip()[:200]
    c = _g().api("POST", f"{API}/files/{fid}/copy", body, params={"fields": FIELDS})
    return f"Copied it as {c.get('name')!r}: {c.get('webViewLink', '')}"


def _restore(args, ctx):
    _full(ctx)
    fid = _id(args.get("file_id"))
    f = _g().api("PATCH", f"{API}/files/{fid}", {"trashed": False}, params={"fields": "id,name"})
    return f"Restored {f.get('name')!r} from the trash."


def _latest_upload():
    """The newest photo the user sent in the chat: (bytes, mime)."""
    from . import uploads
    for m in reversed(db.messages("theta", limit=60)):
        ups = (m.get("meta") or {}).get("uploads") if m.get("role") == "user" else None
        if ups:
            ref = ups[-1]
            mm = uploads.URL_RE.match(str(ref))
            if mm:
                path = uploads.path_for(mm.group(1))
                if path:
                    with open(path, "rb") as fh:
                        blob = fh.read()
                    return blob, uploads.sniff(blob)
    raise ToolError("there's no photo in the chat to save. Ask the user to send it first")


def _save_photo(args, ctx):
    _full(ctx)
    blob, mime = _latest_upload()
    name = str(args.get("name") or "").strip()[:200] or time.strftime("Photo %Y-%m-%d %H.%M")
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}.get(mime, "")
    if ext and not name.lower().endswith(ext):
        name += ext
    meta = {"name": name}
    if args.get("folder_id"):
        meta["parents"] = [_id(args["folder_id"], "folder_id")]
    boundary = "theta" + str(int(time.time() * 1000))
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Type: {mime}\r\n\r\n").encode() + blob + f"\r\n--{boundary}--".encode()
    f = _g().api("POST", UPLOAD, body, headers={"Content-Type": f"multipart/related; boundary={boundary}"})
    return f"Saved the photo to Drive as {f.get('name')!r}: {f.get('webViewLink', '')}"


# ---------------------------------------------------------------- send (after Approve)

def _trash_preview(args):
    _g()._need("drive")
    f = _get(_id(args.get("file_id")))
    return (f"**Move to Drive's trash:** {f.get('name')} ({_kind(f)})\n"
            "Drive empties its trash after 30 days. Until then I can put it back.")


def _trash(args, ctx):
    _full(ctx)
    fid = _id(args.get("file_id"))
    f = _g().api("PATCH", f"{API}/files/{fid}", {"trashed": True}, params={"fields": "id,name"})
    return f"Moved {f.get('name')!r} to Drive's trash (drive_restore brings it back for 30 days)."


ROLES = {"reader": "view", "commenter": "comment on", "writer": "edit"}


def _share_args(args):
    from . import tools
    email = str(args.get("email") or "").strip()
    if not tools._EMAIL.match(email):
        raise ToolError("email must be the person's address; look it up with find_contact if you have a name")
    role = str(args.get("role") or "reader")
    if role not in ROLES:
        raise ToolError("role must be reader, commenter or writer")
    return _id(args.get("file_id")), email, role


def _share_preview(args):
    fid, email, role = _share_args(args)
    _g()._need("drive")
    f = _get(fid)
    note = str(args.get("message") or "").strip()
    return (f"**Share {f.get('name')} with {email}**\nThey can {ROLES[role]} it. Google emails them a link"
            + (f" with your note:\n> {note[:400]}" if note else ".") )


def _share(args, ctx):
    _full(ctx)
    fid, email, role = _share_args(args)
    params = {"sendNotificationEmail": "true", "fields": "id"}
    if args.get("message"):
        params["emailMessage"] = str(args["message"])[:1000]
    _g().api("POST", f"{API}/files/{fid}/permissions", {"type": "user", "role": role, "emailAddress": email}, params=params)
    return f"Shared it with {email} ({ROLES[role]} access). Google emailed them the link."


# ---------------------------------------------------------------- the one-time ask for the newer access

def tick(now):
    """Once: a Google sign-in from before full Drive and Contacts gets a text with a one-tap reconnect card."""
    g = _g()
    try:
        if not g.connected():
            return []
        asked = db.get_setting(ASKED)
        asked = asked if isinstance(asked, list) else (list(g.NEWER[:2]) if asked else [])  # v1 stored a time
        missing = [s for s in g.NEWER if not g.connected(s)]
        if not missing or set(missing) <= set(asked):
            return []  # nothing new to ask for since the last time
        db.set_setting(ASKED, sorted(set(asked) | set(missing)))
        from . import cards
        card = dict(cards.connect("google"), title="Allow the new Google access",
                    why="One tap, then Google asks you to allow it. Nothing else changes.")
        msg = db.add_message("theta", "assistant",
                             "I can do more with Google now: organize, share and clean up your Drive, know your "
                             "Google Contacts by name, and set up Gmail filters for you. Google needs you to allow "
                             "it once.", {"proactive": True, "source": "upgrade", "cards": [card]})
        return [msg]
    except Exception:  # noqa: BLE001
        return []


_F = {"file_id": {"type": "string", "description": "The id from drive_search or drive_list."}}
_NOT = " If Google isn't connected, or only with read-only Drive, the tool says so and a card to fix it shows."

TOOLS = [
    {"name": "drive_list", "risk": "read", "untrusted": True, "run": _list,
     "description": "List what's in a Drive folder (My Drive when folder_id is omitted), folders first." + _NOT,
     "params": {"type": "object", "properties": {"folder_id": {"type": "string"}}}},
    {"name": "drive_make_folder", "risk": "write", "run": _mkdir,
     "description": "Make a folder in Drive (in My Drive, or inside parent_id). Example: {\"name\": \"Taxes 2026\"}." + _NOT,
     "params": {"type": "object", "properties": {"name": {"type": "string"}, "parent_id": {"type": "string"}},
                "required": ["name"]}},
    {"name": "drive_move", "risk": "write", "run": _move,
     "description": "Move a Drive file or folder into a folder (undoable). Example: {\"file_id\": \"1AbC...\", \"folder_id\": \"1XyZ...\"}." + _NOT,
     "params": {"type": "object", "properties": dict(_F, folder_id={"type": "string"}), "required": ["file_id", "folder_id"]}},
    {"name": "drive_rename", "risk": "write", "run": _rename,
     "description": "Rename a Drive file or folder (undoable)." + _NOT,
     "params": {"type": "object", "properties": dict(_F, name={"type": "string"}), "required": ["file_id", "name"]}},
    {"name": "drive_copy", "risk": "write", "run": _copy,
     "description": "Make a copy of a Drive file, optionally with a new name." + _NOT,
     "params": {"type": "object", "properties": dict(_F, name={"type": "string"}), "required": ["file_id"]}},
    {"name": "drive_restore", "risk": "write", "run": _restore,
     "description": "Bring a Drive file back from the trash (the undo for drive_trash)." + _NOT,
     "params": {"type": "object", "properties": _F, "required": ["file_id"]}},
    {"name": "drive_save_photo", "risk": "write", "run": _save_photo,
     "description": ("Save the newest photo the user sent in this chat to their Drive (optionally named, optionally "
                     "into folder_id). Example: {\"name\": \"Lease page 1\"}." + _NOT),
     "params": {"type": "object", "properties": {"name": {"type": "string"}, "folder_id": {"type": "string"}}}},
    {"name": "drive_trash", "risk": "send", "run": _trash, "preview": _trash_preview,
     "description": "Propose moving a Drive file or folder to the trash; the user approves first." + _NOT,
     "params": {"type": "object", "properties": _F, "required": ["file_id"]}},
    {"name": "drive_share", "risk": "send", "run": _share, "preview": _share_preview,
     "description": ("Propose sharing a Drive file with someone by email (reader, commenter or writer, with an "
                     "optional note); the user approves first and Google emails them the link. Example: "
                     "{\"file_id\": \"1AbC...\", \"email\": \"sam@example.com\", \"role\": \"reader\"}." + _NOT),
     "params": {"type": "object", "properties": dict(_F, email={"type": "string"},
                                                     role={"type": "string", "enum": ["reader", "commenter", "writer"]},
                                                     message={"type": "string"}), "required": ["file_id", "email"]}},
]

RELEVANT = r"\b(drive|folder|file|files|doc|docs|pdf|share|shared|save (this|that|the) (photo|picture|pic))\b"
