"""Bank accounts through SimpleFIN (server/bank.py): claiming a setup token, read-only balances and transactions,
caching (SimpleFIN allows ~24 calls a day), plain errors, and the access link never reaching the model. Faked."""
import base64, io, json, os, sys, tempfile, time, urllib.error, urllib.request
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_QUIET="1")
os.environ.pop("SIMPLEFIN_ACCESS_URL", None)
from server import bank, db, gcal, tools


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
tools._ext()
gcal.check_url = lambda u: u if u.startswith("https://") else (_ for _ in ()).throw(ValueError("not https"))
NOW = time.time()
ACCESS = "https://user123:pass456@bridge.simplefin.org/simplefin"
CALLS = []
CLAIMED = set()
DATA = {"errors": [], "accounts": [
    {"org": {"name": "Chase", "domain": "chase.com"}, "id": "a1", "name": "Total Checking", "currency": "USD",
     "balance": "1523.40", "available-balance": "1500.00", "balance-date": int(NOW - 3600), "transactions": [
         {"id": "t1", "posted": int(NOW - 86400 * 2), "amount": "-15.49", "description": "NETFLIX.COM", "pending": False},
         {"id": "t2", "posted": int(NOW - 86400 * 5), "amount": "-62.10", "description": "SAFEWAY #123"},
         {"id": "t3", "posted": int(NOW - 86400 * 10), "amount": "2100.00", "description": "PAYROLL ACME"},
         {"id": "t4", "posted": int(NOW - 86400 * 32), "amount": "-15.49", "description": "NETFLIX.COM"}]},
    {"org": {"name": "Discover"}, "id": "a2", "name": "It Card", "currency": "USD", "balance": "-320.55",
     "balance-date": int(NOW - 7200), "transactions": []}]}


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake(req, timeout=None):
    CALLS.append((req.get_method(), req.full_url, req.get_header("Authorization")))
    if req.full_url.startswith("https://bridge.simplefin.org/simplefin/claim/"):
        if req.full_url in CLAIMED:
            raise urllib.error.HTTPError(req.full_url, 403, "used", {}, io.BytesIO(b""))
        CLAIMED.add(req.full_url)
        return Resp(ACCESS.encode())
    if "/accounts?" in req.full_url:
        return Resp(json.dumps(DATA).encode())
    raise AssertionError(req.full_url)


urllib.request.urlopen = fake
check("not connected at first; the tool says how to connect", not bank.connected()
      and "Settings > Apps > Bank accounts" in tools.execute("bank_accounts", {}, {})[1])
token = base64.b64encode(b"https://bridge.simplefin.org/simplefin/claim/abc123").decode()
check("a setup token is claimed for the access link", bank.claim(token) and bank.connected() and CALLS[-1][0] == "POST")
try:
    bank.claim(token); again = ""
except ValueError as e:
    again = str(e)
check("a used token says to make a new one", "already used" in again, again)
try:
    bank.claim("not base64 at all!!"); junk = ""
except ValueError as e:
    junk = str(e)
check("junk is refused plainly", "isn't a SimpleFIN setup token" in junk or "doesn't point" in junk, junk)

ok, out = tools.execute("bank_accounts", {}, {})
check("balances, per bank and account", ok and "Chase Total Checking: $1,523.40, available $1,500.00" in out and "Discover It Card: -$320.55" in out, out)
get = [c for c in CALLS if c[0] == "GET"][-1]
check("the access link's login goes in a header, never in the URL", "user123" not in get[1] and get[2] == "Basic " + base64.b64encode(b"user123:pass456").decode(), get)
check("and it never reaches the model", "pass456" not in out and "user123" not in out)
ok, out = tools.execute("bank_transactions", {"days": 30, "search": "netflix"}, {})
check("transactions: search, totals, newest first, only the window asked for", ok and "1 transaction(s)" in out and "spent $15.49" in out, out)
ok, out = tools.execute("bank_transactions", {"days": 60}, {})
check("a wider window finds the repeat (a subscription)", out.count("NETFLIX.COM") == 2 and "came in $2,100.00" in out, out)
n = len([c for c in CALLS if c[0] == "GET"])
tools.execute("bank_accounts", {}, {}); tools.execute("bank_transactions", {"days": 20}, {})
check("cached: no extra SimpleFIN calls within half an hour for a window already fetched", len([c for c in CALLS if c[0] == "GET"]) == n)
check("bank tools are read-only and outside text", tools.BY_NAME["bank_transactions"]["risk"] == "read" and tools.BY_NAME["bank_transactions"]["untrusted"])
bank.disconnect()
check("disconnect forgets it", not bank.connected())
print("all bank checks passed")
