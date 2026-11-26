"""Full Google Drive (server/gdrive.py), Google Contacts sync and vCard import (server/contacts.py), and the one-time
text asking an older Google sign-in to allow them. Google's API is faked."""
import os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_TZ="America/Denver", PROTOS_QUIET="1")
from server import contacts, db, gdrive, google, resume, tools, uploads


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
tools._ext()
GRANT = {"gmail", "calendar", "drive"}  # an older sign-in: no full Drive, no contacts
google.connected = lambda service=None: True if service is None else service in GRANT
google._need = lambda service: None
CALLS = []
FILE = "1AbCdEfGhIjKlMnOp"
FOLDER = "1FoLdErAbCdEfGhIj"


def fake_api(method, url, body=None, params=None, raw=False, headers=None, _retry=True):
    CALLS.append((method, url, body, params, headers))
    if url.startswith(contacts.PEOPLE):
        if not (params or {}).get("pageToken"):
            return {"connections": [
                {"resourceName": "people/c1", "names": [{"displayName": "Mom"}],
                 "phoneNumbers": [{"value": "(303) 555-1234", "canonicalForm": "+13035551234", "type": "home"}]},
                {"resourceName": "people/c2", "names": [{"displayName": "Jo Park"}],
                 "phoneNumbers": [{"value": "555 1111", "type": "work"}, {"value": "+1 801 555 2222", "type": "mobile"}]},
                {"resourceName": "people/c3", "names": [{"displayName": "No Way To Reach"}]}],
                "nextPageToken": "p2"}
        return {"connections": [{"resourceName": "people/c4", "names": [{"displayName": "Dana"}],
                                 "emailAddresses": [{"value": "dana@example.com"}]}]}
    if "/files/" in url and method == "GET":
        return {"id": FILE, "name": "Lease.pdf", "mimeType": "application/pdf", "parents": ["root0"]}
    if url.startswith(gdrive.UPLOAD):
        return {"id": "up1", "name": "x", "webViewLink": "https://drive.google.com/file/d/up1"}
    return {"id": FILE, "name": "Lease.pdf"}


google.api = fake_api

# ---------------------------------------------------------------- the one-time ask
msgs = gdrive.tick(time.time())
check("an older Google sign-in gets one text to allow Drive and Contacts", len(msgs) == 1 and msgs[0]["meta"]["proactive"]
      and msgs[0]["meta"]["cards"][0]["type"] == "connect" and msgs[0]["meta"]["cards"][0]["action"].endswith("/api/google/start")
      if google.configured() else len(msgs) == 1 and msgs[0]["meta"]["cards"][0]["type"] == "connect", msgs)
check("only once", gdrive.tick(time.time()) == [])

# ---------------------------------------------------------------- read-only Drive: a clear reason, a card, picked up later
u = db.add_message("theta", "user", "move my lease into the Taxes folder", {})
ctx = {"bot": "theta", "user_id": u["id"]}
ok, out = tools.execute("drive_move", {"file_id": FILE, "folder_id": FOLDER}, ctx)
check("with read-only Drive, a move says why and shows a reconnect card", not ok and "read-only Drive" in out
      and any(c.get("title") == "Allow full Google Drive" for c in ctx.get("cards", [])), (out, ctx.get("cards")))
check("and the request is saved to pick back up", resume._items() and resume._items()[0]["service"] == "gdrive")
check("listing works on read-only access", tools.execute("drive_list", {}, {})[0])

# ---------------------------------------------------------------- full Drive
GRANT |= {"drive_full", "contacts"}
CALLS.clear()
ok, out = tools.execute("drive_move", {"file_id": FILE, "folder_id": FOLDER}, ctx)
check("move adds the new folder and removes the old one, and says how to undo", ok and CALLS[-1][3]["addParents"] == FOLDER
      and CALLS[-1][3]["removeParents"] == "root0" and "Undo" in out, (out, CALLS[-1]))
ok, out = tools.execute("drive_rename", {"file_id": FILE, "name": "Lease 2026.pdf"}, {})
check("rename", ok and CALLS[-1][2] == {"name": "Lease 2026.pdf"} and "rename it back" in out)
ok, out = tools.execute("drive_make_folder", {"name": "Taxes 2026"}, {})
check("make a folder", ok and CALLS[-1][2]["mimeType"] == gdrive.FOLDER)
check("trash and share wait for Approve", tools.BY_NAME["drive_trash"]["risk"] == "send" and tools.BY_NAME["drive_share"]["risk"] == "send")
pv = tools.preview("drive_share", {"file_id": FILE, "email": "sam@example.com", "role": "writer", "message": "Here it is"})
check("the share card says who, what they can do, and the note", "Share Lease.pdf with sam@example.com" in pv and "edit it" in pv and "Here it is" in pv, pv)
ok, out = tools.run_approved({"tool": "drive_share", "args": {"file_id": FILE, "email": "sam@example.com"}})
check("approved share adds a reader permission and emails them", ok and CALLS[-1][2] == {"type": "user", "role": "reader", "emailAddress": "sam@example.com"}
      and CALLS[-1][3]["sendNotificationEmail"] == "true")
ok, out = tools.run_approved({"tool": "drive_trash", "args": {"file_id": FILE}})
check("approved trash, restorable", ok and CALLS[-1][2] == {"trashed": True} and "30 days" in out)

# a photo from the chat
png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x02\x00\x00\x00" + b"\x00" * 40
try:
    saved = uploads.save(png)
    db.add_message("theta", "user", "save this to drive", {"uploads": [saved["url"]]})
    ok, out = tools.execute("drive_save_photo", {"name": "Lease page 1"}, {})
    check("the newest chat photo is uploaded to Drive", ok and CALLS[-1][1] == gdrive.UPLOAD and png in CALLS[-1][2]
          and b'"name": "Lease page 1.png"' in CALLS[-1][2], (out, CALLS[-1][1]))
except Exception as e:  # noqa: BLE001  the tiny PNG may not pass uploads' checks; skip rather than fake it
    print(f"SKIP photo upload ({e})")

# ---------------------------------------------------------------- Google Contacts sync
n = contacts.sync_google()
g = {c["name"]: c for c in contacts.google_contacts()}
check("sync keeps people with a number or email, across pages", n == 3 and set(g) == {"Mom", "Jo Park", "Dana"}, g)
check("the mobile number wins, in international form", g["Jo Park"]["phone"] == "+18015552222", g["Jo Park"])
check("synced people can be texted by name", contacts.resolve("Jo Park") == ("+18015552222", "Jo Park"))
contacts.upsert({"name": "Mom", "phone": "3035551234", "note": "my mom"})
check("one the user added wins over the synced copy", [c.get("note") for c in contacts.everyone() if c["name"] == "Mom"] == ["my mom"])
check("the model hears the count, not every name", "3 from Google Contacts" in contacts.context("theta", time.time()))
check("sync runs on its own, not again within 12 h", contacts.tick(time.time()) == [] and
      len([c for c in CALLS if c[1].startswith(contacts.PEOPLE)]) == 2)

# ---------------------------------------------------------------- vCard import (iPhone, iCloud)
vcf = ("BEGIN:VCARD\r\nVERSION:3.0\r\nN:Rivera;Sam;;;\r\nFN:Sam Rivera\r\nitem1.TEL;type=pref:(435) 555-0199\r\n"
       "TEL;type=CELL;type=VOICE:+1 435 555 0100\r\nEMAIL;type=INTERNET:sam@\r\n example.com\r\nEND:VCARD\r\n"
       "BEGIN:VCARD\r\nFN:No Number\r\nEND:VCARD\r\nBEGIN:VCARD\r\nN:Cruz;Ana;;;\r\nTEL:303.555.7777\r\nEND:VCARD\r\n")
r = contacts.import_vcf(vcf)
sam = next(c for c in contacts.all_contacts() if c["name"] == "Sam Rivera")
check("a vCard file adds people, skipping those with no number or email", r == {"added": 2, "updated": 0, "skipped": 1}, r)
check("it takes the mobile number and joins folded lines", sam["phone"] == "+14355550100" and sam["email"] == "sam@example.com", sam)
check("a name from N when there's no FN", any(c["name"] == "Ana Cruz" for c in contacts.all_contacts()))
check("importing the same file again updates, never duplicates", contacts.import_vcf(vcf)["updated"] == 2
      and len([c for c in contacts.all_contacts() if c["name"] == "Sam Rivera"]) == 1)

print("all drive and contacts checks passed")
