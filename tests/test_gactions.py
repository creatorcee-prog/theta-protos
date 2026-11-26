"""Gmail and Calendar actions (server/gactions.py): archive, trash, restore, unsubscribe, delete and move events.
Google's API is faked; nothing leaves the machine."""
import os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_TZ="America/Denver", PROTOS_QUIET="1")
from server import db, gactions, gcal, google, tools
from server.tools import ToolError


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
tools._ext()
CALLS = []
HEADERS = {}
EVENTS = {
    "solo123": {"id": "solo123", "summary": "Dentist", "start": {"dateTime": "2026-12-01T09:00:00-07:00"},
                "end": {"dateTime": "2026-12-01T10:00:00-07:00"}},
    "team456": {"id": "team456", "summary": "Standup", "start": {"dateTime": "2026-12-02T09:00:00-07:00"},
                "end": {"dateTime": "2026-12-02T09:30:00-07:00"},
                "attendees": [{"email": "me@example.com"}, {"email": "sam@example.com"}]},
}


def fake_api(method, url, body=None, params=None, raw=False, headers=None, _retry=True):
    CALLS.append((method, url, body, params))
    if "/messages/" in url and method == "GET":
        mid = url.rsplit("/", 1)[-1]
        hs = [{"name": "From", "value": f"Deals <deals@shop{mid[:2]}.example>"}, {"name": "Subject", "value": f"Sale {mid}"}]
        hs += [{"name": k, "value": v} for k, v in HEADERS.items()]
        return {"id": mid, "payload": {"headers": hs}, "snippet": "", "labelIds": ["INBOX"]}
    if "/events/" in url and method == "GET":
        return EVENTS[url.rsplit("/", 1)[-1]]
    return {}


google.api = fake_api
google._need = lambda service: None
google.account = lambda: "me@example.com"
IDS = ["18c2f0a1b2c3d4e5", "28c2f0a1b2c3d4e6"]

ok, out = tools.execute("gmail_archive", {"message_ids": IDS}, {})
check("archive takes them out of the inbox in one call", ok and CALLS[-1][1].endswith("/messages/batchModify")
      and CALLS[-1][2] == {"ids": IDS, "addLabelIds": [], "removeLabelIds": ["INBOX"]} and "Undo" in out, (out, CALLS[-1]))
ok, out = tools.execute("gmail_archive", {"message_ids": ["not an id!"]}, {})
check("a bad id is refused before any call", not ok and "gmail_search" in out)
check("trash is a send tool: it only proposes", tools.BY_NAME["gmail_trash"]["risk"] == "send")
pv = tools.preview("gmail_trash", {"message_ids": IDS})
check("the trash card lists each sender and subject", "Move 2 emails to Trash" in pv and "Sale 18c2f0a1b2c3d4e5" in pv and "30 days" in pv, pv)
ok, out = tools.run_approved({"tool": "gmail_trash", "args": {"message_ids": IDS}})
check("approved trash moves them to Trash", ok and CALLS[-1][2]["addLabelIds"] == ["TRASH"], (out, CALLS[-1]))
ok, out = tools.execute("gmail_restore", {"message_ids": IDS[:1]}, {})
check("restore untrashes and puts it back in the inbox", ok and any(c[1].endswith("/untrash") for c in CALLS[-3:])
      and CALLS[-1][2]["addLabelIds"] == ["INBOX"])

# unsubscribe: one-click, mailto, web page only, nothing
HEADERS.update({"List-Unsubscribe": "<https://shop.example/u/abc>, <mailto:unsub@shop.example?subject=stop>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
gcal.check_url = lambda u: u
posted = []


class R:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


gcal._open = lambda req, timeout=15: posted.append((req.full_url, req.data, req.get_method())) or R()
pv = tools.preview("gmail_unsubscribe", {"message_id": IDS[0]})
check("the unsubscribe card names the sender and the one-click way", "Unsubscribe from Deals" in pv and "shop.example" in pv, pv)
ok, out = tools.run_approved({"tool": "gmail_unsubscribe", "args": {"message_id": IDS[0]}})
check("one-click unsubscribe POSTs List-Unsubscribe=One-Click", ok and posted[-1] == ("https://shop.example/u/abc", b"List-Unsubscribe=One-Click", "POST"), (out, posted))
HEADERS.pop("List-Unsubscribe-Post")
mails = []
google.send = lambda to, subject, body: mails.append((to, subject)) or "sent"
ok, out = tools.run_approved({"tool": "gmail_unsubscribe", "args": {"message_id": IDS[0]}})
check("without one-click, it emails the mailto address", ok and mails[-1] == ("unsub@shop.example", "stop"), (out, mails))
HEADERS["List-Unsubscribe"] = "<https://shop.example/prefs>"
try:
    tools.preview("gmail_unsubscribe", {"message_id": IDS[0]})
    err = ""
except ToolError as e:
    err = str(e)
check("a web-page-only unsubscribe isn't opened blind; the user gets the link", "won't open blind" in err and "shop.example/prefs" in err, err)
HEADERS.pop("List-Unsubscribe")
try:
    tools.preview("gmail_unsubscribe", {"message_id": IDS[0]})
    err = ""
except ToolError as e:
    err = str(e)
check("no unsubscribe header: offer archive or a filter instead", "doesn't list a way" in err, err)

# calendar
pv = tools.preview("calendar_delete", {"event_id": "solo123"})
check("delete card: the event and its time, no guest line when there are none", "Dentist" in pv and "Dec 1" in pv and "cancellation" not in pv, pv)
pv = tools.preview("calendar_delete", {"event_id": "team456"})
check("delete card says guests get a cancellation (not the user themself)", "cancellation to sam@example.com" in pv and "me@example.com" not in pv, pv)
ok, out = tools.run_approved({"tool": "calendar_delete", "args": {"event_id": "team456"}})
check("approved delete tells guests", ok and CALLS[-1][0] == "DELETE" and CALLS[-1][3] == {"sendUpdates": "all"}, CALLS[-1])
pv = tools.preview("calendar_move", {"event_id": "solo123", "start": "2026-12-01T15:00"})
check("move card shows from and to", "From Tue Dec 1, 9:00 AM to Tue Dec 1, 3:00 PM" in pv, pv)
ok, out = tools.run_approved({"tool": "calendar_move", "args": {"event_id": "solo123", "start": "2026-12-01T15:00"}})
body = CALLS[-1][2]
check("a move keeps the event's length", ok and body["start"]["dateTime"].startswith("2026-12-01T15:00")
      and body["end"]["dateTime"].startswith("2026-12-01T16:00") and CALLS[-1][3] == {"sendUpdates": "none"}, CALLS[-1])

print("all gactions checks passed")
