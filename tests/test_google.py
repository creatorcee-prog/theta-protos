"""Google sign-in, Gmail, Calendar, Drive, Docs and Slides (server/google.py). No network: urllib.request.urlopen
is stubbed with a fake Google. Run: python3 tests/test_google.py"""
import base64
import contextlib
import email
import email.policy
import io
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_DATA=tempfile.mkdtemp(prefix="protos-google-"),
                  PROTOS_TZ="America/Denver", PROTOS_QUIET="1")
for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "PROTOS_PUBLIC_URL"):
    os.environ.pop(k, None)

from server import app, db, ext, google, tools  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILED.append(name)


# ---- a fake Google

CALLS = []
ROUTES = []  # (method, url prefix, fn(req) -> (status, obj|bytes))


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_urlopen(req, timeout=None):
    url, method = req.full_url, req.get_method()
    body = req.data.decode() if req.data else ""
    CALLS.append({"method": method, "url": url, "body": body, "headers": {k.lower(): v for k, v in req.header_items()}})
    for m, prefix, fn in reversed(ROUTES):
        if m == method and url.startswith(prefix):
            status, obj = fn(CALLS[-1])
            data = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
            if status >= 400:
                raise urllib.error.HTTPError(url, status, "err", {}, io.BytesIO(data))
            return Resp(data)
    raise AssertionError(f"unexpected request {method} {url}")


urllib.request.urlopen = fake_urlopen


def on(method, prefix, fn):
    ROUTES.append((method, prefix, fn if callable(fn) else (lambda req, v=fn: (200, v))))


def form(c):
    return {k: v[0] for k, v in urllib.parse.parse_qs(c["body"]).items()}


def q(c):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(c["url"]).query)


def last(prefix, method=None):
    for c in reversed(CALLS):
        if c["url"].startswith(prefix) and (method is None or c["method"] == method):
            return c
    return None


def call(path, method="GET", body=None, key="k", headers=None):
    raw = json.dumps(body).encode() if body is not None else b""
    p, _, qs = path.partition("?")
    env = {"REQUEST_METHOD": method, "PATH_INFO": p, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http", "REMOTE_ADDR": "1.2.3.4"}
    if key:
        env["HTTP_X_PROTOS_KEY"] = key
    for k, v in (headers or {}).items():
        env["HTTP_" + k.upper().replace("-", "_")] = v
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]), h=dict(h))))
    try:
        j = json.loads(out or b"{}")
    except ValueError:
        j = {}
    return got["s"], j, got["h"]


def jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return enc({"alg": "none"}) + "." + enc(claims) + ".sig"


def b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def mime_of(raw):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), policy=email.policy.default)


db.init()
ext.reset()
tools._ext_reset()
ctx = {"bot": "theta", "now": time.time()}

# ---- before set-up
cons = {c["id"]: c for c in google.connections()}
check("not configured: gmail/calendar/drive say what to set, with a connect_url",
      all(not cons[i]["connected"] and cons[i]["connect_url"] == "/api/google/start" and "GOOGLE_CLIENT_ID" in cons[i]["note"]
          for i in ("gmail", "calendar", "drive")), cons)
cons = {c["id"]: c for c in call("/api/connections")[1]}
check("/api/connections carries the merged Google rows", cons["gmail"]["connect_url"] == "/api/google/start"
      and cons["calendar"]["connected"] is False, cons.get("gmail"))
ok, out = tools.execute("gmail_search", {"query": "is:unread"}, ctx)
check("a tool without Google says how to connect", not ok and "Connect" in out, out)
check("context line says how to connect", "not connected" in google.context("theta", 0) and "Connect" in google.context("theta", 0))
ok, out = tools.run_approved({"tool": "send_email_draft", "args": {"to": "sam@example.com", "subject": "s", "body": "b"}})
check("send_email_draft without Gmail keeps the 'not connected' message", not ok and "isn't connected" in out, out)

# ---- routes' auth
check("start needs sign-in", call("/api/google/start", key=None)[0] == 401)
check("disconnect needs sign-in", call("/api/google/disconnect", "POST", key=None)[0] == 401)
s, j, h = call("/api/google/start")
check("start without client id redirects back with an error", s == 302 and "google_error=not_configured" in h["Location"], h)

os.environ.update(GOOGLE_CLIENT_ID="cid.apps.googleusercontent.com", GOOGLE_CLIENT_SECRET="csecret")
s, j, h = call("/api/google/start", headers={"Host": "theta.example.app", "X-Forwarded-Proto": "https"})
loc = urllib.parse.urlsplit(h.get("Location", ""))
aq = {k: v[0] for k, v in urllib.parse.parse_qs(loc.query).items()}
check("start 302s to Google's consent screen", s == 302 and loc.netloc == "accounts.google.com", h)
check("offline access, forced consent, incremental scopes", aq.get("access_type") == "offline"
      and aq.get("prompt") == "consent" and aq.get("include_granted_scopes") == "true" and aq.get("response_type") == "code", aq)
want = {"gmail.modify", "gmail.send", "calendar.events", "calendar.readonly", "drive.file", "drive.readonly",
        "documents", "presentations"}
got_scopes = aq.get("scope", "").split()
check("all the scopes are asked for", {x.rsplit("/", 1)[-1] for x in got_scopes} >= want | {"openid", "email"}, got_scopes)
check("redirect URI from Host + X-Forwarded-Proto", aq.get("redirect_uri") == "https://theta.example.app/api/google/callback", aq)
state1 = aq.get("state", "")
check("state is random and long", len(state1) >= 24)
os.environ["PROTOS_PUBLIC_URL"] = "https://theta.up.railway.app/"
s, j, h = call("/api/google/start", headers={"Host": "evil.example"})
aq2 = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(h["Location"]).query).items()}
check("PROTOS_PUBLIC_URL wins over the Host header", aq2["redirect_uri"] == "https://theta.up.railway.app/api/google/callback", aq2)
check("each start makes a new state", aq2["state"] != state1)
for slip in ("theta.up.railway.app", "https://theta.up.railway.app/api/google/callback", " HTTPS://Theta.up.railway.app// "):
    os.environ["PROTOS_PUBLIC_URL"] = slip
    s, j, h = call("/api/google/start", headers={"Host": "evil.example"})
    aq3 = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(h["Location"]).query).items()}
    check("a slip in PROTOS_PUBLIC_URL still gives the exact redirect URI: " + repr(slip),
          aq3["redirect_uri"] == "https://theta.up.railway.app/api/google/callback", aq3)
os.environ["PROTOS_PUBLIC_URL"] = "https://theta.up.railway.app/"

# ---- callback: state checks
TOKENS = {"access_token": "ya29.ACCESS-1", "refresh_token": "1//REFRESH-1", "expires_in": 3599,
          "scope": " ".join(google.SCOPES), "token_type": "Bearer", "id_token": jwt({"email": "me@example.com"})}
on("POST", google.TOKEN_URL, lambda c: (200, TOKENS) if form(c).get("grant_type") == "authorization_code"
   else (200, {"access_token": "ya29.ACCESS-2", "expires_in": 3599}))
n0 = len(CALLS)
s, j, h = call("/api/google/callback?state=forged&code=abc", key=None)
check("a wrong state is refused, and no code is exchanged", s == 403 and len(CALLS) == n0, (s, j))
s, j, h = call("/api/google/callback?code=abc", key=None)
check("a missing state is refused", s == 403)
err = io.StringIO()
with contextlib.redirect_stderr(err):
    s, j, h = call(f"/api/google/callback?state={urllib.parse.quote(state1)}&code=the-code", key=None)
check("the right state (signed out: it's a public route) exchanges the code and goes home",
      s == 302 and h["Location"] == "/?connected=google", (s, j, h))
ex = form(last(google.TOKEN_URL))
check("code exchange request shape", ex == {"code": "the-code", "client_id": "cid.apps.googleusercontent.com",
                                            "client_secret": "csecret", "grant_type": "authorization_code",
                                            "redirect_uri": "https://theta.example.app/api/google/callback"}, ex)
rec = db.get_setting("google")
check("tokens stored in settings, with the account email", rec["access_token"] == "ya29.ACCESS-1"
      and rec["refresh_token"] == "1//REFRESH-1" and rec["email"] == "me@example.com", rec)
check("tokens never reach the log", "ACCESS-1" not in err.getvalue() and "REFRESH-1" not in err.getvalue(), err.getvalue())
s, j, h = call(f"/api/google/callback?state={urllib.parse.quote(state1)}&code=again", key=None)
check("a replayed state is refused", s == 403, (s, j))
st = google._new_state("https://x/api/google/callback", now=time.time() - 601)
s, j, h = call(f"/api/google/callback?state={st}&code=c", key=None)
check("an expired state (over 10 min) is refused", s == 403)
check("the callback is GET only", call("/api/google/callback", "POST", key=None)[0] == 405)
s, j, h = call(f"/api/google/callback?state={urllib.parse.quote(aq2['state'])}&error=access_denied", key=None)
check("a declined consent goes home with the reason", s == 302 and "google_error=access_denied" in h["Location"])

cons = {c["id"]: c for c in google.connections()}
check("connections: gmail, calendar and drive connected", all(cons[i]["connected"] for i in ("gmail", "calendar", "drive"))
      and not cons["gmail"].get("note"), cons)
check("connected() helper, per service", google.connected() and google.connected("gmail") and google.connected("drive"))
ctxline = google.context("theta", 0)
check("context line: connected (Gmail, Calendar, Drive)", "connected (Gmail, Calendar, Drive)" in ctxline
      and "ya29" not in ctxline, ctxline)
check("the context block never carries a token", "ya29" not in tools.context_block() and "1//" not in tools.context_block())
check("settings API doesn't expose tokens", "ya29" not in json.dumps(call("/api/settings")[1]))

# ---- token refresh
rec = db.get_setting("google")
rec["expires_at"] = time.time() - 5
db.set_setting("google", rec)
on("GET", google.GMAIL + "/profile", {"historyId": "5000", "emailAddress": "me@example.com"})
cur = google.mail_cursor()
rf = last(google.TOKEN_URL)
check("an expired access token refreshes first", form(rf).get("grant_type") == "refresh_token"
      and form(rf).get("refresh_token") == "1//REFRESH-1", form(rf))
check("and the new token is used", last(google.GMAIL + "/profile")["headers"]["authorization"] == "Bearer ya29.ACCESS-2"
      and cur == "5000")
check("the refresh token is kept when Google doesn't send a new one", db.get_setting("google")["refresh_token"] == "1//REFRESH-1")
check("access_token() helper returns the fresh one without another refresh",
      google.access_token() == "ya29.ACCESS-2" and last(google.TOKEN_URL) is rf)

flip = {"n": 0}


def once_401(c):
    flip["n"] += 1
    return (401, {"error": {"message": "expired"}}) if flip["n"] == 1 else (200, {"historyId": "5001"})


on("GET", google.GMAIL + "/profile", once_401)
n_ref = sum(1 for c in CALLS if c["url"] == google.TOKEN_URL)
check("a 401 refreshes once and retries", google.mail_cursor() == "5001"
      and sum(1 for c in CALLS if c["url"] == google.TOKEN_URL) == n_ref + 1)

# ---- tools: request shapes
check("risk levels", {t["name"]: t["risk"] for t in google.TOOLS} == {
    "gmail_search": "read", "gmail_read": "read", "gmail_draft": "write", "gmail_reply_draft": "write",
    "calendar_list": "read", "calendar_add": "write", "calendar_invite": "send", "drive_search": "read",
    "drive_read": "read", "docs_create": "write", "slides_create": "write"})
check("untrusted where the output is mail, events or file text",
      all(google.TOOLS[i]["untrusted"] for i in range(len(google.TOOLS)) if google.TOOLS[i]["name"] in
          ("gmail_search", "gmail_read", "calendar_list", "drive_search", "drive_read")))
check("every tool has new-hire docs with an example", all("Example" in t["description"] and len(t["description"]) > 120
                                                          and t["params"]["type"] == "object" for t in google.TOOLS))
check("the tools reach the model through ext", {"gmail_search", "calendar_invite", "slides_create"} <= {s["name"] for s in tools.specs()})
check("RELEVANT catches mail, calendar, drive, doc and slides words",
      all(tools.relevant(x) for x in ("any new emails from Sam?", "what's on my calendar", "find it in drive",
                                      "make a google doc", "turn this into slides", "draft a reply")))

META = {"m1": ("Sam <sam@example.com>", "Dinner Friday?", "Are we still on?"),
        "m2": ("Ana <ana@example.com>", "Invoice", "Attached")}


def meta(c):
    mid = urllib.parse.urlsplit(c["url"]).path.rsplit("/", 1)[-1]
    f, s, sn = META[mid]
    return 200, {"id": mid, "threadId": "t-" + mid, "snippet": sn, "labelIds": ["INBOX", "UNREAD"],
                 "internalDate": str(int(time.time() * 1000)), "historyId": "6001",
                 "payload": {"headers": [{"name": "From", "value": f}, {"name": "Subject", "value": s},
                                         {"name": "Date", "value": "Thu, 26 Nov 2026 10:00:00 -0700"},
                                         {"name": "Message-ID", "value": f"<{mid}@mail.example.com>"}]}}


def message(c):
    if q(c).get("format") == ["full"]:
        st, m = meta(c)
        m["payload"].update(mimeType="multipart/alternative", parts=[
            {"mimeType": "text/plain", "body": {"data": b64("Hi!\n\nAre we still on for 7?\n" + "x" * 3000)}},
            {"mimeType": "text/html", "body": {"data": b64("<p>html</p>")}}])
        return st, m
    return meta(c)


on("GET", google.GMAIL + "/messages?", {"messages": [{"id": "m1"}, {"id": "m2"}]})
on("GET", google.GMAIL + "/messages/", message)
ok, out = tools.execute("gmail_search", {"query": "from:sam newer_than:7d", "max_results": 5}, ctx)
sc = last(google.GMAIL + "/messages?")
check("gmail_search sends the Gmail query", ok and q(sc)["q"] == ["from:sam newer_than:7d"] and q(sc)["maxResults"] == ["5"], sc)
check("gmail_search returns id, from, subject, date and snippet", "id=m1" in out and "sam@example.com" in out
      and "Dinner Friday?" in out and "26 Nov 2026" in out and "Are we still on?" in out, out)
check("gmail_search asks only for metadata", q(last(google.GMAIL + "/messages/m2"))["format"] == ["metadata"])
ok, out = tools.execute("gmail_read", {"message_id": "m1"}, ctx)
check("gmail_read gives plain text, trimmed with an offset to continue", ok and "Are we still on for 7?" in out
      and "<p>" not in out and "offset=" in out and len(out) <= tools.OUTPUT_CAP + 200, out[-200:])
ok, out2 = tools.execute("gmail_read", {"message_id": "m1", "offset": 1500}, ctx)
check("gmail_read continues from the offset", ok and "Are we still on" not in out2.split("\n\n", 1)[1][:50], out2[:300])

on("POST", google.GMAIL + "/drafts", {"id": "d-1", "message": {"id": "x"}})
ok, out = tools.execute("gmail_draft", {"to": "sam@example.com", "subject": "Friday", "body": "Hi Sam, 7 works.",
                                        "cc": "ana@example.com"}, ctx)
dc = last(google.GMAIL + "/drafts")
m = mime_of(json.loads(dc["body"])["message"]["raw"])
check("gmail_draft creates a Gmail draft (write: runs freely, sends nothing)", ok and "d-1" in out and "Nothing was sent" in out
      and m["To"] == "sam@example.com" and m["Cc"] == "ana@example.com" and m["Subject"] == "Friday"
      and "7 works" in m.get_content(), (out, dict(m)))
ok, out = tools.execute("gmail_draft", {"to": "not-an-address", "subject": "x", "body": "y"}, ctx)
check("gmail_draft refuses a bad address", not ok and "not an email address" in out, out)
ok, out = tools.execute("gmail_reply_draft", {"message_id": "m1", "body": "Yes, see you at 7."}, ctx)
rc = json.loads(last(google.GMAIL + "/drafts")["body"])["message"]
rm = mime_of(rc["raw"])
check("gmail_reply_draft threads the reply", ok and rc["threadId"] == "t-m1" and rm["To"] == "Sam <sam@example.com>"
      and rm["Subject"] == "Re: Dinner Friday?" and rm["In-Reply-To"] == "<m1@mail.example.com>", (out, dict(rm)))

# ---- send through approval
on("POST", google.GMAIL + "/messages/send", {"id": "sent-1", "threadId": "t"})
ok, out = tools.execute("send_email_draft", {"to": "sam@example.com", "subject": "s", "body": "b"}, ctx)
check("send_email_draft never runs in the model loop", not ok and "approval" in out and last(google.GMAIL + "/messages/send") is None)
aid = db.add_approval({"tool": "send_email_draft", "args": {"to": "sam@example.com", "subject": "Dinner", "body": "On for 7?"},
                       "bot": "theta", "preview": "x", "expires": time.time() + 3600})
res = app.decide_approval(aid, "approve")
sc = last(google.GMAIL + "/messages/send")
sm = mime_of(json.loads(sc["body"])["raw"]) if sc else {}
check("an approved send_email_draft really sends through Gmail", res["state"] == "done" and sc is not None
      and sm["To"] == "sam@example.com" and sm["Subject"] == "Dinner" and "sent-1" in res["result"], res)

# ---- calendar
on("GET", google.CAL + "/calendars/primary/events", {"items": [
    {"id": "e1", "summary": "Dentist", "location": "12 Main St", "start": {"dateTime": "2026-11-27T15:00:00-07:00"},
     "end": {"dateTime": "2026-11-27T15:45:00-07:00"}},
    {"id": "e2", "summary": "Holiday", "start": {"date": "2026-11-28"}, "end": {"date": "2026-11-29"}}]})
ok, out = tools.execute("calendar_list", {"from": "2026-11-27", "to": "2026-11-28"}, ctx)
lc = q(last(google.CAL + "/calendars/primary/events", "GET"))
check("calendar_list asks for the range in the user's tz, single events in order",
      lc["timeMin"] == ["2026-11-27T00:00:00-07:00"] and lc["timeMax"] == ["2026-11-29T00:00:00-07:00"]
      and lc["singleEvents"] == ["true"] and lc["orderBy"] == ["startTime"], lc)
check("calendar_list lists times, places, all-day", ok and "Fri 27 Nov 15:00-15:45: Dentist @ 12 Main St" in out
      and "Holiday" in out and "all day" in out, out)
ok, out = tools.execute("calendar_list", {"from": "2026-11-27", "to": "2026-11-20"}, ctx)
check("calendar_list explains a backwards range", not ok and "before" in out)

on("POST", google.CAL + "/calendars/primary/events", lambda c: (200, dict(json.loads(c["body"]), id="new1",
                                                                         htmlLink="https://calendar.google.com/e/new1")))
ok, out = tools.execute("calendar_add", {"title": "Gym", "start": "2026-11-27T18:00:00-07:00", "duration_minutes": 45,
                                         "location": "Gym"}, ctx)
ac = last(google.CAL + "/calendars/primary/events", "POST")
ab = json.loads(ac["body"])
check("calendar_add: own calendar, no attendees, nobody emailed", ok and "attendees" not in ab and "sendUpdates" not in ac["url"]
      and ab["start"]["dateTime"] == "2026-11-27T18:00:00-07:00" and ab["end"]["dateTime"] == "2026-11-27T18:45:00-07:00"
      and ab["summary"] == "Gym" and "calendar.google.com" in out, (out, ab))
ok, out = tools.execute("calendar_add", {"title": "Trip", "start": "2026-12-01"}, ctx)
check("calendar_add all-day", ok and json.loads(last(google.CAL + "/calendars/primary/events", "POST")["body"])["end"] == {"date": "2026-12-02"})
check("calendar_add has no attendees param at all", "attendees" not in google.TOOLS[5]["params"]["properties"])

inv = {"title": "Coffee", "start": "2026-11-28T10:00:00-07:00", "duration_minutes": 30, "attendees": "sam@example.com, ana@example.com"}
n0 = len(CALLS)
ok, out = tools.execute("calendar_invite", inv, ctx)
check("calendar_invite is send-risk: never runs from the model", not ok and "approval" in out and len(CALLS) == n0)
pv = tools.preview("calendar_invite", inv)
check("calendar_invite's approval card shows guests, time and that they get email",
      "sam@example.com" in pv and "ana@example.com" in pv and "Coffee" in pv and "10:00-10:30" in pv and "email" in pv, pv)
aid = db.add_approval({"tool": "calendar_invite", "args": inv, "bot": "theta", "preview": pv, "expires": time.time() + 3600})
res = app.decide_approval(aid, "approve")
ic = last(google.CAL + "/calendars/primary/events", "POST")
ib = json.loads(ic["body"])
check("calendar_invite's approved run creates the event with guests and emails them", res["state"] == "done"
      and ib["attendees"] == [{"email": "sam@example.com"}, {"email": "ana@example.com"}] and q(ic)["sendUpdates"] == ["all"], (res, ib))
try:
    tools.preview("calendar_invite", dict(inv, attendees="nope"))
    bad = False
except tools.ToolError:
    bad = True
check("calendar_invite refuses a bad guest address before any card", bad)

# ---- drive, docs, slides
on("GET", google.DRIVE + "/files?", {"files": [{"id": "f1", "name": "Lease 2026", "mimeType": "application/vnd.google-apps.document",
                                                "modifiedTime": "2026-10-01T00:00:00Z", "webViewLink": "https://docs.google.com/document/d/f1"}]})
ok, out = tools.execute("drive_search", {"query": "lease's terms"}, ctx)
dq = q(last(google.DRIVE + "/files?"))["q"][0]
check("drive_search searches name and full text, escapes quotes, skips trash",
      ok and "name contains 'lease\\'s terms'" in dq and "fullText contains" in dq and "trashed = false" in dq
      and "id=f1" in out and "Doc" in out, (dq, out))
on("GET", google.DRIVE + "/files/f1?", {"id": "f1", "name": "Lease 2026", "mimeType": "application/vnd.google-apps.document"})
on("GET", google.DRIVE + "/files/f1/export", ("Lease terms. " * 400).encode())
ok, out = tools.execute("drive_read", {"file_id": "f1"}, ctx)
ec = last(google.DRIVE + "/files/f1/export")
check("drive_read exports a Doc as text, capped with an offset", ok and q(ec)["mimeType"] == ["text/plain"]
      and "Lease terms." in out and "offset=" in out and len(out) <= tools.OUTPUT_CAP + 200, out[-120:])
on("GET", google.DRIVE + "/files/p1?", {"id": "p1", "name": "scan.pdf", "mimeType": "application/pdf", "webViewLink": "https://x"})
ok, out = tools.execute("drive_read", {"file_id": "p1"}, ctx)
check("drive_read of a PDF gives the link instead", ok and "can't read" in out)

on("POST", google.DOCS, {"documentId": "doc1", "title": "Trip plan"})
on("POST", google.DOCS + "/doc1:batchUpdate", {"replies": []})
ok, out = tools.execute("docs_create", {"title": "Trip plan", "text": "# Day 1\n- Fly **out** 9:00\n1. Hotel\nPlain line"}, ctx)
reqs = json.loads(last(google.DOCS + "/doc1:batchUpdate")["body"])["requests"]
kinds = [list(r)[0] for r in reqs]
check("docs_create makes the doc and fills it", ok and json.loads(last(google.DOCS, "POST")["body"]) != {} and
      "https://docs.google.com/document/d/doc1/edit" in out, out)
check("docs_create: text, a heading, bullets, numbers and bold", reqs[0]["insertText"]["text"] == "Day 1\nFly out 9:00\nHotel\nPlain line\n"
      and kinds.count("createParagraphBullets") == 2 and reqs[1]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_1"
      and reqs[1]["updateParagraphStyle"]["range"] == {"startIndex": 1, "endIndex": 7}
      and any(r.get("updateTextStyle", {}).get("range") == {"startIndex": 11, "endIndex": 14} for r in reqs), reqs)

on("POST", google.SLIDES, {"presentationId": "pres1", "slides": [{"objectId": "p", "pageElements": [
    {"objectId": "ttl", "shape": {"placeholder": {"type": "CENTERED_TITLE"}}}]}]})
on("POST", google.SLIDES + "/pres1:batchUpdate", {"replies": []})
ok, out = tools.execute("slides_create", {"title": "Q4 review", "slides": [{"title": "Wins", "bullets": ["Launched v2", "3 clients"]},
                                                                          {"title": "Next", "bullets": ["Hire"]}]}, ctx)
sreq = json.loads(last(google.SLIDES + "/pres1:batchUpdate")["body"])["requests"]
check("slides_create returns the link", ok and "https://docs.google.com/presentation/d/pres1/edit" in out, out)
check("slides_create: title slide text, then createSlide + text + bullets per item",
      sreq[0] == {"insertText": {"objectId": "ttl", "text": "Q4 review"}}
      and [list(r)[0] for r in sreq].count("createSlide") == 2
      and sreq[1]["createSlide"]["slideLayoutReference"]["predefinedLayout"] == "TITLE_AND_BODY"
      and {"insertText": {"objectId": "theta_s0_b", "text": "Launched v2\n3 clients"}} in sreq, sreq)
ok, out = tools.execute("slides_create", {"title": "x", "slides": []}, ctx)
check("slides_create explains an empty outline", not ok and "slides" in out)

# ---- mail_since (for routines)
on("GET", google.GMAIL + "/history", {"history": [{"messagesAdded": [{"message": {"id": "m2", "labelIds": ["INBOX"]}}]}]})
rows = google.mail_since("6000")
hc = q(last(google.GMAIL + "/history"))
check("mail_since(history id) uses the history API for new inbox mail", hc["startHistoryId"] == ["6000"]
      and hc["labelId"] == ["INBOX"] and [r["id"] for r in rows] == ["m2"] and rows[0]["from"].startswith("Ana")
      and set(rows[0]) >= {"id", "from", "subject", "snippet", "ts", "history_id"}, rows)
rows = google.mail_since(time.time() - 600)
mc = q(last(google.GMAIL + "/messages?"))
check("mail_since(ts) searches the inbox after that time", mc["q"][0].startswith("in:inbox after:") and len(rows) == 2, (mc, rows))

# ---- invalid_grant: signed out, with a note, easy to reconnect
rec = db.get_setting("google")
rec["expires_at"] = 0
db.set_setting("google", rec)
on("POST", google.TOKEN_URL, lambda c: (400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}))
ok, out = tools.execute("gmail_search", {}, ctx)
check("invalid_grant: the tool says to reconnect", not ok and "Connect" in out and "signed" in out, out)
rec = db.get_setting("google")
check("invalid_grant: tokens forgotten, marked signed out", not rec.get("refresh_token") and not rec.get("access_token")
      and rec.get("status") == "signed_out", rec)
cons = {c["id"]: c for c in google.connections()}
check("connections show it disconnected with a reconnect note", not cons["gmail"]["connected"] and "7 days" in cons["gmail"]["note"]
      and cons["gmail"]["connect_url"] == "/api/google/start", cons["gmail"])
check("the chat gets one heads-up about it", any(m.get("meta", {}).get("source") == "google" for m in db.messages("theta", limit=50)))
check("context says signed out", "signed out" in google.context("theta", 0))
check("mail_since is quiet while disconnected", google.mail_since("1") == [])

# reconnect works again, then disconnect revokes and forgets
on("POST", google.TOKEN_URL, lambda c: (200, TOKENS))
s, j, h = call("/api/google/start")
st = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(h["Location"]).query).items()}["state"]
s, j, h = call(f"/api/google/callback?state={st}&code=c2", key=None)
check("reconnecting after a sign-out works", s == 302 and google.connected("gmail") and not google.connections()[0].get("note"))
on("POST", google.REVOKE_URL, {})
check("disconnect is POST only", call("/api/google/disconnect")[0] == 405)
s, j, h = call("/api/google/disconnect", "POST", {})
check("disconnect revokes the token at Google and forgets it", s == 200 and j["revoked"] and
      form(last(google.REVOKE_URL))["token"] == "1//REFRESH-1" and not google.connected() and db.get_setting("google") == {}, j)

if FAILED:
    print(f"\n{len(FAILED)} failed: {FAILED}")
    sys.exit(1)
print("\nall google checks passed")
