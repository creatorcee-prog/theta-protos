"""Your account: who you are to Theta, how Theta talks to you, and keeping all of it safe.

    GET  /api/account                {profile, personalize, storage}
    POST /api/account                {profile?: {...}, personalize?: {...}}: saves what's sent
    GET  /api/account/usage          replies, tokens and cost: today, 7 and 30 days, by model (from the turns table)
    GET  /api/account/backup         a copy of Theta's database to keep (sign-in tokens left out)
    POST /api/account/restore        that file back (raw bytes); the current one is kept beside it first
    POST /api/logout                 forget this device's sign-in

Profile: full name, nickname (what Theta calls you), photo, email, phone, occupation, home, time zone, more about
you, and instructions. Name, phone and time zone are the same values calls.py and persona.py already read
("call_name", "phone", "tz"), so there is one place for each. Personalization: style, warmth, enthusiasm, emoji,
and whether Theta uses its memory. prompt_block() turns both into a stable part of the system prompt.

Storage: Theta lives in one SQLite file. On Railway it survives a deploy only on a volume; storage() says whether
it is on one, how far back Theta's memory goes and how often the server started, so a wipe is visible in Settings
instead of silent. Backups leave out the secrets (Google and bank sign-ins, the push key): a restored copy needs
those apps connected again. With full Google Drive access, a backup goes to "Theta backups" in Drive every 3 hours,
named with the date and time ("Theta backup 2026-11-27 21.30.db"); the newest BACKUPS_KEPT are kept, plus one a day
for KEEP_DAILY days. Settings can restore any of them, and drivesync.py loads the newest one by itself on a fresh
start.
"""
import json
import os
import re
import sqlite3
import tempfile
import time

from . import db

PROFILE_FIELDS = {"name": 60, "nickname": 40, "photo": 80, "email": 120, "phone": 24, "occupation": 80,
                  "home": 80, "tz": 64, "about": 1500, "instructions": 1500}
STYLES = ("default", "concise", "detailed", "casual", "professional")
LEVELS = ("less", "default", "more")
SECRET_SETTINGS = ("google", "google_oauth_states", "bank_simplefin", "bank_cache", "vapid", "telnyx_account_sid", "sessions")
BACKUP_EVERY = 3 * 3600   # a backup to Drive this often
BACKUPS_KEPT = 16          # the newest kept, plus one a day for KEEP_DAILY days
KEEP_DAILY = 14
DRIVE_FOLDER = "Theta backups"
MAX_RESTORE = 512 * 1024 * 1024


# ---------------------------------------------------------------- profile and personalization

def _clean(v, cap):
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(v or "")).strip()[:cap]


def profile():
    p = db.get_setting("profile")
    p = dict(p) if isinstance(p, dict) else {}
    # the values other features already keep are the source of truth for them
    p["name"] = db.get_setting("call_name") or p.get("name") or ""
    p["phone"] = db.get_setting("phone") or p.get("phone") or ""
    p["tz"] = db.get_setting("tz") or p.get("tz") or ""
    if not p.get("nickname"):
        try:
            from . import onboarding
            p["nickname"] = onboarding.state()["answers"].get("name") or ""
        except Exception:  # noqa: BLE001
            p["nickname"] = ""
    return {k: (p.get(k) or "") for k in PROFILE_FIELDS}


def save_profile(body):
    cur = profile()
    for k, cap in PROFILE_FIELDS.items():
        if k in body:
            cur[k] = _clean(body[k], cap)
    if cur["phone"]:
        from . import contacts
        ph = contacts.phone(cur["phone"])
        if not ph:
            raise ValueError("that phone number doesn't look right (use +1 303 555 0142)")
        cur["phone"] = ph
    if cur["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", cur["email"]):
        raise ValueError("that email doesn't look right")
    if cur["tz"]:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(cur["tz"])
        except Exception:  # noqa: BLE001
            raise ValueError("that time zone isn't one Theta knows (e.g. America/Denver)") from None
    if cur["photo"] and not re.fullmatch(r"/api/uploads/[0-9a-f]{32}", cur["photo"]):
        raise ValueError("the photo must be one uploaded to Theta")
    db.set_setting("call_name", cur["name"])
    db.set_setting("phone", cur["phone"])
    if cur["tz"]:
        db.set_setting("tz", cur["tz"])
    db.set_setting("profile", cur)
    return cur


def personalize():
    p = db.get_setting("personalize")
    p = p if isinstance(p, dict) else {}
    return {"style": p.get("style") if p.get("style") in STYLES else "default",
            "warmth": p.get("warmth") if p.get("warmth") in LEVELS else "default",
            "enthusiasm": p.get("enthusiasm") if p.get("enthusiasm") in LEVELS else "default",
            "emoji": p.get("emoji") if p.get("emoji") in LEVELS else "default",
            "memory": p.get("memory") is not False}


def save_personalize(body):
    cur = personalize()
    for k, allowed in (("style", STYLES), ("warmth", LEVELS), ("enthusiasm", LEVELS), ("emoji", LEVELS)):
        if k in body:
            if body[k] not in allowed:
                raise ValueError(f"{k} must be one of {', '.join(allowed)}")
            cur[k] = body[k]
    if "memory" in body:
        cur["memory"] = bool(body["memory"])
    db.set_setting("personalize", cur)
    return cur


def memory_on():
    return personalize()["memory"]


_STYLE_WORDS = {
    "concise": "Keep replies especially short: the answer, then only what they need.",
    "detailed": "They like fuller answers: give the reasoning and the useful details, still well organized.",
    "casual": "Be casual and relaxed, like texting a close friend.",
    "professional": "Keep a polished, professional tone.",
}
_LEVEL_WORDS = {
    ("warmth", "more"): "Be warm and caring; notice how they're doing.",
    ("warmth", "less"): "Keep it matter-of-fact; skip the warm touches.",
    ("enthusiasm", "more"): "Bring energy and enthusiasm.",
    ("enthusiasm", "less"): "Stay calm and even; no exclamation points or hype.",
    ("emoji", "more"): "Use emoji now and then where they fit.",
    ("emoji", "less"): "Don't use emoji.",
}


def prompt_block():
    """The account part of the system prompt (stable until they change Settings)."""
    p, s = profile(), personalize()
    lines = []
    call = p["nickname"] or p["name"]
    if call:
        lines.append(f"Call them {call}." + (f" Their full name is {p['name']}." if p["name"] and p["name"] != call else ""))
    if p["occupation"]:
        lines.append(f"They work as: {p['occupation']}.")
    if p["home"]:
        lines.append(f"Home: {p['home']} (use it for weather, places and travel times unless they say otherwise).")
    if p["about"]:
        lines.append("More about them, in their words:\n" + p["about"])
    style = [_STYLE_WORDS[s["style"]]] if s["style"] in _STYLE_WORDS else []
    style += [_LEVEL_WORDS[(k, s[k])] for k in ("warmth", "enthusiasm", "emoji") if (k, s[k]) in _LEVEL_WORDS]
    if style:
        lines.append("How they like you to talk: " + " ".join(style))
    if p["instructions"]:
        lines.append("Their instructions for you (follow them unless they'd break a rule above):\n" + p["instructions"])
    return ("About the person you work for:\n" + "\n".join(lines)) if lines else ""


# ---------------------------------------------------------------- storage: is any of this going to last?

_booted = {"done": False}


def note_boot(now=None):
    """Once per process: remember when the server started (the last 20 times) and the first start ever."""
    if _booted["done"]:
        return
    _booted["done"] = True
    now = now or time.time()
    if not db.get_setting("first_start"):
        db.set_setting("first_start", now)
    boots = db.get_setting("boots")
    boots = [b for b in (boots if isinstance(boots, list) else []) if isinstance(b, (int, float))][-19:]
    db.set_setting("boots", boots + [now])


def _railway():
    return any(os.environ.get(k) for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID"))


def storage():
    """{persistent, why, path, first_start, oldest_message, messages, starts, db_bytes, last_backup, drive_backup}"""
    note_boot()
    path = os.path.realpath(db.data_dir())
    vol = (os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or "").strip()
    if vol:
        on = path == os.path.realpath(vol) or path.startswith(os.path.realpath(vol).rstrip("/") + "/")
        why = ("Saved on your Railway volume, so it survives deploys." if on else
               f"Your Railway volume is at {vol}, but Theta saves to {path}: everything there is wiped on each "
               "deploy. Remove PROTOS_DATA from Railway's variables (or set it inside the volume).")
    elif _railway():
        on = False
        why = ("There's no Railway volume, so Theta's memory, chats and settings are wiped on every deploy. "
               "In Railway: your service > Settings > Volumes > Add, mount path /data, then redeploy.")
    else:
        on = True
        why = f"Saved on this computer's disk ({path})."
    c = db._conn()
    row = c.execute("SELECT COUNT(*) AS n, MIN(t) AS t FROM messages").fetchone()
    try:
        size = os.path.getsize(os.path.join(path, os.path.basename(db._path or "protos.db")))
    except OSError:
        size = None
    boots = db.get_setting("boots") or []
    return {"persistent": on, "why": why, "path": path, "first_start": db.get_setting("first_start"),
            "oldest_message": row["t"], "messages": row["n"], "starts": len(boots),
            "last_start": boots[-1] if boots else None, "db_bytes": size,
            "last_backup": db.get_setting("backup_last"), "drive_backup": _drive_ready(),
            "drive_backup_on": db.get_setting("backup_drive") is not False}


# ---------------------------------------------------------------- backups

def snapshot():
    """The database as bytes, consistent (SQLite's backup API), without the secret settings."""
    fd, tmp = tempfile.mkstemp(suffix=".db", dir=db.data_dir())
    os.close(fd)
    try:
        dst = sqlite3.connect(tmp)
        db._conn().backup(dst)
        dst.execute(f"DELETE FROM settings WHERE key IN ({','.join('?' * len(SECRET_SETTINGS))})", SECRET_SETTINGS)
        dst.commit()
        dst.execute("VACUUM")  # so deleted secrets don't linger in free pages
        dst.close()
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def restore(blob):
    """Replace Theta's data with a backup. The current database is copied beside it first, and the secrets it
    holds now (connections) are kept, so a restore never signs Theta out of anything still connected."""
    if not blob or len(blob) > MAX_RESTORE or not blob.startswith(b"SQLite format 3\x00"):
        raise ValueError("that isn't a Theta backup (it should be the .db file Theta made)")
    fd, tmp = tempfile.mkstemp(suffix=".db", dir=db.data_dir())
    with os.fdopen(fd, "wb") as f:
        f.write(blob)
    try:
        src = sqlite3.connect(tmp)
        tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"messages", "settings"} <= tables:
            raise ValueError("that file isn't a Theta backup (it has no messages)")
        if src.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("that backup is damaged")
        db.migrate(src)  # a backup from an older version gets this version's new columns, on the copy only
        bad = db.fits(src)
        if bad:  # the root cause of a wiped database: never copy over a file this version can't read
            raise ValueError("that file isn't a Theta backup this version can read (" + bad + ")")
        src.execute("SELECT id, bot, role, text, meta, t FROM messages LIMIT 1").fetchall()
        live = db._conn()
        keep = live.execute(f"SELECT key, value FROM settings WHERE key IN ({','.join('?' * len(SECRET_SETTINGS))})",
                            SECRET_SETTINGS).fetchall()
        safety = os.path.join(db.data_dir(), time.strftime("before-restore-%Y%m%d-%H%M%S.db"))
        out = sqlite3.connect(safety)
        live.backup(out)
        out.close()
        try:
            src.backup(live)
            src.close()
            for k, v in keep:
                live.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))
            n = live.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            db.migrate(live)
        except Exception:  # anything going wrong mid-restore puts the database back exactly as it was
            back = sqlite3.connect(safety)
            back.backup(live)
            back.close()
            raise
        olds = sorted(f for f in os.listdir(db.data_dir()) if f.startswith("before-restore-") and f.endswith(".db"))
        for f in olds[:-3]:  # keep the 3 newest safety copies
            try:
                os.remove(os.path.join(db.data_dir(), f))
            except OSError:
                pass
        return {"ok": True, "messages": n, "kept_copy": os.path.basename(safety)}
    except sqlite3.DatabaseError:
        raise ValueError("that file isn't a Theta backup") from None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _drive_ready():
    try:
        from . import google
        return bool(google.connected("drive_full"))
    except Exception:  # noqa: BLE001
        return False


def _drive_folder(g):
    q = (f"name = '{DRIVE_FOLDER}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false")
    got = g.api("GET", "https://www.googleapis.com/drive/v3/files", params={"q": q, "fields": "files(id)"})
    if got.get("files"):
        return got["files"][0]["id"]
    made = g.api("POST", "https://www.googleapis.com/drive/v3/files?fields=id",
                 json.dumps({"name": DRIVE_FOLDER, "mimeType": "application/vnd.google-apps.folder"}).encode(),
                 headers={"Content-Type": "application/json"})
    return made["id"]


def drive_backups():
    """[{id, name, created}] newest first, from the Theta backups folder."""
    from . import google
    g = google
    fid = _drive_folder(g)
    got = g.api("GET", "https://www.googleapis.com/drive/v3/files",
                params={"q": f"'{fid}' in parents and trashed = false", "orderBy": "createdTime desc",
                        "fields": "files(id,name,createdTime,size)", "pageSize": 50})
    return [{"id": f["id"], "name": f["name"], "created": f.get("createdTime"), "size": f.get("size")}
            for f in got.get("files") or []]


def backup_to_drive(now=None):
    """Upload today's backup to Drive and trash the ones beyond BACKUPS_KEPT. Returns the file's name."""
    from . import google
    g = google
    now = now or time.time()
    fid = _drive_folder(g)
    try:
        from . import persona
        name = persona.local_now(now).strftime("Theta backup %Y-%m-%d %H.%M.db")  # the user's time zone
    except Exception:  # noqa: BLE001
        name = time.strftime("Theta backup %Y-%m-%d %H.%M.db", time.localtime(now))
    blob = snapshot()
    boundary = "thetabackup" + str(int(now * 1000))
    meta = {"name": name, "parents": [fid]}
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Type: application/x-sqlite3\r\n\r\n").encode() + blob + f"\r\n--{boundary}--".encode()
    g.api("POST", "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name", body,
          headers={"Content-Type": f"multipart/related; boundary={boundary}"})
    for old in prune(drive_backups()):
        try:
            g.api("PATCH", f"https://www.googleapis.com/drive/v3/files/{old['id']}", json.dumps({"trashed": True}).encode(),
                  headers={"Content-Type": "application/json"})
        except Exception:  # noqa: BLE001
            pass
    db.set_setting("backup_last", {"t": now, "where": "drive", "name": name})
    return name


def prune(backups):
    """The backups to trash: all but the newest BACKUPS_KEPT and the newest one of each of the last KEEP_DAILY
    days (so a problem nobody noticed for a few days doesn't push every good copy out)."""
    keep = {b["id"] for b in backups[:BACKUPS_KEPT]}
    days = []
    for b in backups:  # newest first
        day = (b.get("created") or "")[:10]
        if day and day not in days and len(days) < KEEP_DAILY:
            days.append(day)
            keep.add(b["id"])
    return [b for b in backups if b["id"] not in keep]


def restore_from_drive(file_id):
    from . import google
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", str(file_id or "")):
        raise ValueError("unknown backup")
    if file_id not in {b["id"] for b in drive_backups()}:
        raise ValueError("that file isn't in the Theta backups folder")
    blob = google.api("GET", f"https://www.googleapis.com/drive/v3/files/{file_id}", params={"alt": "media"}, raw=True)
    return restore(blob)


def tick(now):
    note_boot(now)
    if db.get_setting("backup_drive") is False or not _drive_ready():
        return []
    last = db.get_setting("backup_last") or {}
    if now - float(last.get("t") or 0) < BACKUP_EVERY:
        return []
    try:
        backup_to_drive(now)
    except Exception as e:  # noqa: BLE001  try again next time; say why in Settings
        db.set_setting("backup_last", {"t": now, "where": "drive", "error": f"{type(e).__name__}: {str(e)[:120]}"})
    return []


# ---------------------------------------------------------------- usage

def usage(now=None):
    """Replies, tokens and cost from the turns table: today, last 7 and 30 days, and by model (30 days)."""
    now = now or time.time()
    from . import persona
    start_today = persona.local_now(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    c = db._conn()
    out = {}
    for key, since in (("today", start_today), ("week", now - 7 * 86400), ("month", now - 30 * 86400)):
        r = c.execute("SELECT COUNT(*) AS n, SUM(tokens_in) AS i, SUM(tokens_out) AS o, SUM(cost_usd) AS c "
                      "FROM turns WHERE t >= ?", (since,)).fetchone()
        out[key] = {"replies": r["n"] or 0, "tokens_in": r["i"] or 0, "tokens_out": r["o"] or 0,
                    "cost_usd": round(r["c"] or 0.0, 4)}
    rows = c.execute("SELECT provider, model, COUNT(*) AS n, SUM(tokens_in) + SUM(tokens_out) AS tok, "
                     "SUM(cost_usd) AS c FROM turns WHERE t >= ? AND model IS NOT NULL GROUP BY provider, model "
                     "ORDER BY c DESC, n DESC LIMIT 12", (now - 30 * 86400,)).fetchall()
    out["models"] = [{"provider": r["provider"], "model": r["model"], "replies": r["n"], "tokens": r["tok"] or 0,
                      "cost_usd": round(r["c"] or 0.0, 4)} for r in rows]
    days = []
    for d in range(13, -1, -1):
        a = start_today - d * 86400
        r = c.execute("SELECT COUNT(*) AS n, SUM(cost_usd) AS c FROM turns WHERE t >= ? AND t < ?", (a, a + 86400)).fetchone()
        days.append({"day": time.strftime("%Y-%m-%d", time.localtime(a)), "replies": r["n"] or 0,
                     "cost_usd": round(r["c"] or 0.0, 4)})
    out["days"] = days
    return out


# ---------------------------------------------------------------- routes

def route(req, start):
    from .app import HTTPError, respond_json
    if req.method == "POST":
        body = req.json() or {}
        try:
            if isinstance(body.get("profile"), dict):
                save_profile(body["profile"])
            if isinstance(body.get("personalize"), dict):
                save_personalize(body["personalize"])
            if "drive_backup" in body:
                db.set_setting("backup_drive", bool(body["drive_backup"]))
        except ValueError as e:
            raise HTTPError(400, str(e)) from None
    elif req.method != "GET":
        raise HTTPError(405, "method not allowed")
    return respond_json(start, {"profile": profile(), "personalize": personalize(), "storage": storage()})


def usage_route(req, start):
    from .app import HTTPError, respond_json
    if req.method != "GET":
        raise HTTPError(405, "method not allowed")
    return respond_json(start, usage())


def backup_route(req, start):
    from .app import HTTPError, _headers
    if req.method != "GET":
        raise HTTPError(405, "method not allowed")
    blob = snapshot()
    db.set_setting("backup_last", {"t": time.time(), "where": "download"})
    name = time.strftime("theta-backup-%Y-%m-%d.db")
    start("200 OK", _headers("application/x-sqlite3", [("Content-Length", str(len(blob))), ("Cache-Control", "no-store"),
                                                      ("Content-Disposition", f'attachment; filename="{name}"')]))
    return [blob]


def restore_route(req, start):
    from .app import HTTPError, respond_json
    if req.method != "POST":
        raise HTTPError(405, "method not allowed")
    try:
        if (req.query.get("drive") or "").strip():
            return respond_json(start, restore_from_drive(req.query["drive"]))
        n = int(req.env.get("CONTENT_LENGTH") or 0)
        if n <= 0 or n > MAX_RESTORE:
            raise ValueError("send the backup file (up to 512 MB)")
        return respond_json(start, restore(req.env["wsgi.input"].read(n)))
    except ValueError as e:
        raise HTTPError(400, str(e)) from None


def drive_list_route(req, start):
    from .app import HTTPError, respond_json
    if req.method == "POST":
        try:
            name = backup_to_drive()
        except Exception as e:  # noqa: BLE001
            raise HTTPError(502, f"Drive didn't take the backup ({type(e).__name__})") from None
        return respond_json(start, {"ok": True, "name": name, "backups": drive_backups()})
    if req.method != "GET":
        raise HTTPError(405, "method not allowed")
    if not _drive_ready():
        return respond_json(start, {"ready": False, "backups": []})
    try:
        return respond_json(start, {"ready": True, "backups": drive_backups()})
    except Exception as e:  # noqa: BLE001
        return respond_json(start, {"ready": True, "backups": [], "error": f"{type(e).__name__}"})


def logout_route(req, start):
    from .app import HTTPError, respond_json
    if req.method != "POST":
        raise HTTPError(405, "method not allowed")
    from .app import end_session
    end_session(req.cookie("protos_key") or "")
    gone = "protos_key=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" + ("; Secure" if req.https() else "")
    return respond_json(start, {"ok": True}, extra=[("Set-Cookie", gone)])


def look_route(req, start):
    """GET/POST /api/look {accent?, dot?, opening?}: Theta's look, the same on every device."""
    from . import intro_steps
    from .app import HTTPError, respond_json
    if req.method == "POST":
        intro_steps.save_look(req.json() or {})
    elif req.method != "GET":
        raise HTTPError(405, "method not allowed")
    return respond_json(start, intro_steps.look())


ROUTES = {"/api/look": look_route, "/api/account": route, "/api/account/usage": usage_route, "/api/account/backup": backup_route,
          "/api/account/restore": restore_route, "/api/account/drive-backups": drive_list_route,
          "/api/logout": logout_route}


def context(bot, now):
    return ""
