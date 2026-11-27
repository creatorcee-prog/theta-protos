"""Picking up where Theta left off, from Google Drive.

account.py backs Theta up to the "Theta backups" folder in Drive every few hours (dated and timed, in the user's
time zone). This module does the other half: when Drive is connected (at start, or the moment the user connects
Google again after a wipe), it looks at the newest backup and loads it if this copy of Theta is a fresh start:

- the backup holds more messages than this copy, and
- nothing here is older than the backup's newest message (an established copy is never overwritten by itself;
  the user can still restore any backup by hand in Settings > Data and storage).

Messages written here since the wipe (an intro, a first chat) are kept: they're added back after the restore. The
secrets of this copy (Google and bank sign-ins) are kept too, so Theta stays connected. A backup is loaded at most
once (setting "backup_restored"), and Theta says in the chat what it loaded. PROTOS_AUTO_RESTORE=0 turns it off.
"""
import os
import sqlite3
import tempfile
import threading
import time

from . import db

_seen = {"ready": False, "busy": False}


def _peek(blob):
    """{messages, newest} of a backup file."""
    fd, tmp = tempfile.mkstemp(suffix=".db", dir=db.data_dir())
    with os.fdopen(fd, "wb") as f:
        f.write(blob)
    try:
        c = sqlite3.connect(tmp)
        n, newest = c.execute("SELECT COUNT(*), MAX(t) FROM messages").fetchone()
        c.close()
        return {"messages": n or 0, "newest": newest or 0}
    except sqlite3.DatabaseError:
        return {"messages": 0, "newest": 0}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _local():
    n, oldest = db._conn().execute("SELECT COUNT(*), MIN(t) FROM messages").fetchone()
    return n or 0, oldest


def auto_restore(now=None):
    """Load the newest Drive backup if this copy is a fresh start. Returns what happened (a short dict)."""
    from . import account, google
    now = now or time.time()
    backups = account.drive_backups()
    if not backups:
        return {"done": False, "why": "no backups in Drive"}
    newest = backups[0]
    done = db.get_setting("backup_restored") or {}
    last = db.get_setting("backup_last") or {}
    if done.get("id") == newest["id"] or last.get("name") == newest["name"]:
        return {"done": False, "why": "already up to date with the newest backup"}
    blob = google.api("GET", f"https://www.googleapis.com/drive/v3/files/{newest['id']}", params={"alt": "media"},
                      raw=True)
    info = _peek(blob)
    n_here, oldest_here = _local()
    if info["messages"] <= n_here:
        return {"done": False, "why": "this copy has as much as the backup"}
    if oldest_here is not None and oldest_here < info["newest"] - 60:
        return {"done": False, "why": "this copy has its own history; restore by hand if you want the backup"}
    since = [dict(r) for r in db._conn().execute("SELECT bot, role, text, t, meta FROM messages ORDER BY id")]
    res = account.restore(blob)
    c = db._conn()
    for m in since:  # what was said here since the wipe goes back on top
        c.execute("INSERT INTO messages (bot, role, text, t, meta) VALUES (?, ?, ?, ?, ?)",
                  (m["bot"], m["role"], m["text"], m["t"], m["meta"]))
    c.commit()
    db.set_setting("backup_restored", {"id": newest["id"], "name": newest["name"], "t": now,
                                       "messages": res.get("messages"), "kept_since": len(since)})
    label = newest["name"].replace("Theta backup ", "").replace(".db", "")
    db.add_message("theta", "assistant",
                   f"I found my backup in your Google Drive (from {label}) and loaded it: our chats, your settings, "
                   "what I remember about you, and your chips are back."
                   + (f" The {len(since)} messages from since then are kept too." if since else ""),
                   {"proactive": True, "source": "backup"})
    return {"done": True, "name": newest["name"], "messages": res.get("messages"), "kept_since": len(since)}


def tick(now):
    """When Drive becomes reachable (start, or a fresh Google sign-in), check once for a backup to load."""
    from . import account
    if os.environ.get("PROTOS_AUTO_RESTORE", "1") == "0":
        return []
    ready = account._drive_ready()
    if ready and not _seen["ready"] and not _seen["busy"]:
        _seen["busy"] = True

        def run():
            try:
                db.set_setting("backup_check", {"t": time.time(), **auto_restore()})
            except Exception as e:  # noqa: BLE001  Drive down: try again next start or sign-in
                db.set_setting("backup_check", {"t": time.time(), "done": False, "why": f"{type(e).__name__}"})
            finally:
                _seen["busy"] = False
        threading.Thread(target=run, name="drive-restore", daemon=True).start()
    _seen["ready"] = ready
    return []


def context(bot, now):
    return ""
