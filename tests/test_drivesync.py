"""Loading Theta's newest Drive backup by itself (server/drivesync.py): after a wipe, connecting Google brings
the chats, settings and memory back, keeps what was said since, and keeps the new sign-in; a copy with its own
history is never overwritten; a backup loads once. Google is faked."""
import os, re, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp())
from server import account, db, drivesync, google


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


FILES = []


def fake_api(method, url, body=None, params=None, raw=False, headers=None):
    if "upload/drive" in url:
        nm = re.search(rb'"name": "([^"]+)"', body).group(1).decode()
        FILES.insert(0, {"id": f"file{len(FILES):04d}abcdef", "name": nm, "createdTime": "2026-11-27T10:00:00Z", "blob": body})
        return {"id": FILES[0]["id"]}
    if method == "GET" and params and "alt" in params:
        data = next(f for f in FILES if f["id"] in url)["blob"]
        s = data.index(b"application/x-sqlite3\r\n\r\n") + len(b"application/x-sqlite3\r\n\r\n")
        return data[s:data.rindex(b"\r\n--")]
    if method == "GET" and "mimeType" in (params or {}).get("q", ""):
        return {"files": [{"id": "folder123456789"}]}
    if method == "GET":
        return {"files": [{k: v for k, v in f.items() if k != "blob"} for f in FILES]}
    return {}


google.api = fake_api
CONNECTED = [True]
google.connected = lambda service=None: CONNECTED[0]

# the old server: a history, a profile, then a backup to Drive
db.init()
t0 = time.time() - 86400
for i in range(30):
    db._conn().execute("INSERT INTO messages (bot, role, text, t, meta) VALUES ('theta', 'user', ?, ?, '{}')", (f"old {i}", t0 + i))
db._conn().commit()
db.set_setting("profile", {"name": "Sam"})
db.set_setting("google", {"token": "old-token"})
account.backup_to_drive(t0 + 100)
check("the backup in Drive is named with its date and time", re.fullmatch(r"Theta backup \d{4}-\d\d-\d\d \d\d\.\d\d\.db", FILES[0]["name"]))

# a deploy wipes everything: a new, empty database
os.environ["PROTOS_DATA"] = tempfile.mkdtemp()
db.init()
check("fresh start: nothing here", db._conn().execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0)
db.add_message("theta", "user", "hi, are you there?")
db.set_setting("google", {"token": "new-token"})  # they connect Google again
res = drivesync.auto_restore()
msgs = [m["text"] for m in db.messages("theta", limit=100)]
check("connecting Google loads the newest backup", res["done"] and "old 0" in msgs and "old 29" in msgs)
check("their settings come back", account.profile()["name"] == "Sam")
check("what was said since the wipe is kept", "hi, are you there?" in msgs)
check("the new sign-in is kept (the backup has none)", db.get_setting("google") == {"token": "new-token"})
check("Theta says in the chat what it loaded", any("found my backup in your Google Drive" in t for t in msgs))
check("a backup loads only once", not drivesync.auto_restore()["done"])

# an established copy with its own history is never overwritten by a backup
os.environ["PROTOS_DATA"] = tempfile.mkdtemp()
db.init()
db._conn().execute("INSERT INTO messages (bot, role, text, t, meta) VALUES ('theta', 'user', 'mine', ?, '{}')", (t0 - 5000,))
db._conn().commit()
r = drivesync.auto_restore()
check("a copy with its own older history is left alone", not r["done"] and db.messages("theta")[0]["text"] == "mine")

# tick: checks when Drive becomes reachable, in the background
os.environ["PROTOS_DATA"] = tempfile.mkdtemp()
db.init()
CONNECTED[0] = False
drivesync._seen.update(ready=False, busy=False)
drivesync.tick(time.time())
check("no Drive, no check", db.get_setting("backup_check") is None)
CONNECTED[0] = True
drivesync.tick(time.time())
for _ in range(50):
    if db.get_setting("backup_check"):
        break
    time.sleep(0.05)
check("the moment Drive is connected, Theta checks and loads", (db.get_setting("backup_check") or {}).get("done") is True)
print("all drivesync checks passed")
