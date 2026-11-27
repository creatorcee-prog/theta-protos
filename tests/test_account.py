"""Your account (server/account.py): the profile and personalization feeding the system prompt, the memory switch,
whether storage survives a deploy (Railway volume or not), backups that leave secrets out, restores that keep the
current connections and a safety copy, Drive backups (faked Google), usage from the turns table, and the routes."""
import re, io, json, os, sqlite3, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = tempfile.mkdtemp()
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=DATA)
for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_VOLUME_MOUNT_PATH"):
    os.environ.pop(k, None)
from server import account, app, db, ext, memory, persona, tools


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


db.init()
ext.reset(); tools._ext_reset(); tools._ext()


def call(method, path, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    path, _, qs = path.partition("?")
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(data)),
           "CONTENT_TYPE": ctype, "wsgi.input": io.BytesIO(data), "HTTP_X_PROTOS_KEY": "k", "wsgi.url_scheme": "https"}
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]), h=h)))
    return got["s"], out, dict(got["h"])


# ---------------------------------------------------------------- profile and personalization
check("no profile: nothing about the user in the prompt", account.prompt_block() == "")
account.save_profile({"name": "Cee Example", "nickname": "Cee", "email": "cee@example.com", "phone": "(435) 555-0101",
                      "occupation": "Builder", "home": "St. George, UT", "tz": "America/Denver",
                      "about": "Training for a half marathon.", "instructions": "Disagree with me when I'm wrong."})
p = account.profile()
check("the phone is stored in one form, and shared with calls (the 'phone' setting)", p["phone"] == "+14355550101"
      and db.get_setting("phone") == "+14355550101" and db.get_setting("call_name") == "Cee Example")
sp = persona.system_prompt()
check("the system prompt calls them by nickname, with their work, home, words and instructions",
      "Call them Cee. Their full name is Cee Example." in sp and "Builder" in sp and "St. George, UT" in sp
      and "half marathon" in sp and "Disagree with me" in sp)
for bad, why in (({"phone": "12"}, "phone"), ({"email": "nope"}, "email"), ({"tz": "Mars/Base"}, "time zone"),
                 ({"photo": "https://evil.example/x.png"}, "photo")):
    try:
        account.save_profile(bad); ok = False
    except ValueError as e:
        ok = why in str(e)
    check(f"a bad {why} is refused plainly", ok)
account.save_personalize({"style": "concise", "warmth": "more", "emoji": "less"})
check("personalization shapes how Theta talks", "especially short" in persona.system_prompt()
      and "warm and caring" in persona.system_prompt() and "Don't use emoji" in persona.system_prompt())
try:
    account.save_personalize({"warmth": "maximum"}); ok = False
except ValueError:
    ok = True
check("only known levels", ok)

# ---------------------------------------------------------------- memory switch
memory.edit("add", "Has a dog named Juniper")
check("memory on: what Theta remembers is in the prompt", "Juniper" in persona.system_prompt())
account.save_personalize({"memory": False})
ok, out = tools.execute("memory_edit", {"op": "add", "text": "Likes tea"}, {"bot": "theta"})
check("memory off: not read into the prompt, and memory_edit saves nothing", "Juniper" not in persona.system_prompt()
      and "Memory is off" in out and "tea" not in memory.block())
account.save_personalize({"memory": True})
check("back on: it was never deleted", "Juniper" in persona.system_prompt())

# ---------------------------------------------------------------- storage: does it survive a deploy?
check("local disk: persistent", account.storage()["persistent"] is True)
os.environ["RAILWAY_ENVIRONMENT"] = "production"
st = account.storage()
check("Railway with no volume: flagged, with the fix", st["persistent"] is False and "Volumes > Add" in st["why"])
os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = "/data"
st = account.storage()
check("a volume elsewhere than where Theta saves: flagged", st["persistent"] is False and "PROTOS_DATA" in st["why"])
os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = DATA
check("saving on the volume: safe", account.storage()["persistent"] is True)
for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_VOLUME_MOUNT_PATH"):
    os.environ.pop(k)
check("starts are counted and the first start kept", account.storage()["starts"] >= 1 and db.get_setting("first_start"))

# ---------------------------------------------------------------- backups
db.add_message("theta", "user", "hello from before")
db.set_setting("google", {"refresh_token": "SECRET-REFRESH"})
db.set_setting("bank_simplefin", {"access_url": "https://u:SECRETPW@bridge.example/simplefin"})
blob = account.snapshot()
check("a backup is a SQLite file", blob.startswith(b"SQLite format 3\x00"))
check("and has no Google or bank secrets in it, not even in free pages", b"SECRET-REFRESH" not in blob and b"SECRETPW" not in blob)
db.add_message("theta", "user", "after the backup")
db.set_setting("google", {"refresh_token": "NEWER-TOKEN"})
res = account.restore(blob)
n = db._conn().execute("SELECT COUNT(*) FROM messages WHERE text = 'after the backup'").fetchone()[0]
check("restore brings the backup back", res["ok"] and n == 0)
check("and keeps the connections you have now", (db.get_setting("google") or {}).get("refresh_token") == "NEWER-TOKEN")
check("what was there is kept as a copy first", os.path.isfile(os.path.join(DATA, res["kept_copy"])))
for junk in (b"", b"not a database", b"SQLite format 3\x00" + b"\x00" * 50):
    try:
        account.restore(junk); ok = False
    except ValueError:
        ok = True
    check(f"junk isn't restored ({len(junk)} bytes)", ok)
other = os.path.join(tempfile.mkdtemp(), "x.db")
c = sqlite3.connect(other); c.execute("CREATE TABLE t (a)"); c.commit(); c.close()
try:
    account.restore(open(other, "rb").read()); ok = False
except ValueError as e:
    ok = "isn't a Theta backup" in str(e)
check("another app's database isn't restored", ok)
# a file with the right table names but the wrong columns (what wiped the database before) changes nothing
before = db._conn().execute("SELECT COUNT(*) FROM messages").fetchone()[0]
wrong = os.path.join(tempfile.mkdtemp(), "w.db")
c = sqlite3.connect(wrong); c.execute("CREATE TABLE messages (x)"); c.execute("CREATE TABLE settings (y)"); c.commit(); c.close()
try:
    account.restore(open(wrong, "rb").read()); ok = False
except ValueError:
    ok = True
check("a look-alike file is refused before anything is overwritten", ok
      and db._conn().execute("SELECT COUNT(*) FROM messages").fetchone()[0] == before and db.get_setting("google"))
db.add_message("theta", "user", "still works after a refused restore")
check("and the database still works", db.messages("theta")[-1]["text"].startswith("still works"))

# ---------------------------------------------------------------- Drive backups (Google faked)
from server import google
FILES = []


def fake_api(method, url, body=None, params=None, raw=False, headers=None):
    if "upload/drive" in url:
        nm = re.search(rb'"name": "(Theta backup (\d{4}-\d\d-\d\d) (\d\d)\.(\d\d)\.db)"', body)
        FILES.insert(0, {"id": f"file{len(FILES):04d}abcdef", "name": nm.group(1).decode(),
                         "createdTime": f"{nm.group(2).decode()}T{nm.group(3).decode()}:{nm.group(4).decode()}:00Z",
                         "blob": body})
        return {"id": FILES[0]["id"], "name": FILES[0]["name"]}
    if method == "GET" and params and "alt" in params:
        f = next(f for f in FILES if f["id"] in url)
        data = f["blob"]
        start = data.index(b"application/x-sqlite3\r\n\r\n") + len(b"application/x-sqlite3\r\n\r\n")
        return data[start:data.rindex(b"\r\n--")]
    if method == "GET" and "mimeType" in (params or {}).get("q", ""):
        return {"files": [{"id": "folder123456789"}]}
    if method == "GET":
        return {"files": [{k: v for k, v in f.items() if k != "blob"} for f in FILES if not f.get("trashed")]}
    if method == "PATCH":
        for f in FILES:
            if f["id"] in url:
                f["trashed"] = True
        return {}
    raise AssertionError(url)


google.api = fake_api
google.connected = lambda service=None: True
now = time.time()
account.tick(now)
check("with full Drive access, a backup goes to Drive, named with its date and time", len(FILES) == 1
      and (db.get_setting("backup_last") or {}).get("where") == "drive" and re.fullmatch(r"Theta backup \d{4}-\d\d-\d\d \d\d\.\d\d\.db", FILES[0]["name"]))
account.tick(now + 3600)
check("not again within 3 hours", len(FILES) == 1)
account.tick(now + 3 * 3600 + 5)
check("again after 3 hours", len(FILES) == 2)
for i in range(60):  # 7.5 days of backups every 3 hours
    account.backup_to_drive(now + 3 * 3600 * (i + 2))
live = [f for f in FILES if not f.get("trashed")]
days = {f["createdTime"][:10] for f in FILES}
check("the newest 16 are kept, plus one from each earlier day", len(live) < len(FILES)
      and all(not f.get("trashed") for f in FILES[:account.BACKUPS_KEPT])
      and {f["createdTime"][:10] for f in live} == days)
db.add_message("theta", "user", "only in the live db")
res = account.restore_from_drive(FILES[0]["id"])
check("restore from a Drive backup", res["ok"] and db._conn().execute(
    "SELECT COUNT(*) FROM messages WHERE text = 'only in the live db'").fetchone()[0] == 0)
try:
    account.restore_from_drive("someoneelsesfile123"); ok = False
except ValueError:
    ok = True
check("only files in the Theta backups folder", ok)
db.set_setting("backup_drive", False)
account.tick(now + 86400 * 30)
check("Drive backups can be turned off", len(FILES) == 62)

# ---------------------------------------------------------------- usage
c = db._conn()
for i, (prov, model, cost) in enumerate([("deepseek", "deepseek-chat", 0.002), ("deepseek", "deepseek-chat", 0.003),
                                          ("anthropic", "claude-x", 0.05)]):
    c.execute("INSERT INTO turns (t, bot, provider, model, tokens_in, tokens_out, cost_usd) VALUES (?, 'theta', ?, ?, 1000, 100, ?)",
              (time.time() - i * 60, prov, model, cost))
c.execute("INSERT INTO turns (t, bot, provider, model, tokens_in, tokens_out, cost_usd) VALUES (?, 'theta', 'deepseek', 'deepseek-chat', 10, 1, 1.0)",
          (time.time() - 40 * 86400,))
u = account.usage()
check("usage: today and 30 days count real replies, tokens and cost (old turns left out)", u["today"]["replies"] == 3
      and u["month"]["tokens_in"] == 3000 and abs(u["month"]["cost_usd"] - 0.055) < 1e-9)
check("by model, priciest first, and 14 days of bars", u["models"][0]["model"] == "claude-x" and len(u["days"]) == 14)

# ---------------------------------------------------------------- routes
s, out, h = call("GET", "/api/account")
j = json.loads(out)
check("GET /api/account", s == 200 and j["profile"]["nickname"] == "Cee" and "persistent" in j["storage"])
s, out, h = call("POST", "/api/account", {"profile": {"occupation": "Founder"}, "personalize": {"style": "casual"}})
j = json.loads(out)
check("POST saves only what's sent", s == 200 and j["profile"]["occupation"] == "Founder" and j["profile"]["home"] == "St. George, UT"
      and j["personalize"]["style"] == "casual")
s, out, h = call("POST", "/api/account", {"profile": {"email": "bad"}})
check("a bad field is a 400 with the reason", s == 400 and b"email" in out)
s, out, h = call("GET", "/api/account/backup")
check("download a backup", s == 200 and out.startswith(b"SQLite format 3") and "attachment" in h.get("Content-Disposition", ""))
s, out2, h = call("POST", "/api/account/restore", raw=out, ctype="application/octet-stream")
check("and restore it", s == 200 and json.loads(out2)["ok"])
s, out, h = call("GET", "/api/account/usage")
check("GET usage", s == 200 and "month" in json.loads(out))
s, out, h = call("POST", "/api/logout", {})
check("logout clears this device's sign-in", s == 200 and "Max-Age=0" in h.get("Set-Cookie", ""))
print("all account checks passed")
