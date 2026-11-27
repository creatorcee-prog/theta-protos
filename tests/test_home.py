"""Home (server/home.py): finds Theta saves (home_post), top stories parsed from RSS with your interests first, and
the smart stack built from stored data. No network: feeds are parsed from a fixed sample."""
import io, json, os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp())
from server import app, db, ext, home, tools


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


db.init()
ext.reset(); tools._ext_reset(); tools._ext()

# ---------------------------------------------------------------- finds
check("home_post is a tool Theta always has", "home_post" in tools.BY_NAME and "home_post" in tools.CORE)
out = tools.BY_NAME["home_post"]["run"]({"kind": "deal", "title": "Arc lamp $89", "price": "$89",
                                          "url": "https://lamp.example/arc", "image": "http://insecure/x.png"}, {})
f = home.found()
check("a find is saved, newest first, with only https links kept", f and f[0]["title"] == "Arc lamp $89"
      and f[0]["url"].startswith("https://") and f[0]["image"] == "")
home.post({"kind": "deal", "title": "Arc lamp $85", "url": "https://lamp.example/arc"})
check("the same link again replaces the old find", len(home.found()) == 1 and home.found()[0]["title"] == "Arc lamp $85")
home.post({"kind": "news", "title": "Old story"}, now=time.time() - 5 * 86400)
check("news finds fade after a few days", all(i["title"] != "Old story" for i in home.found()))
try:
    home.post({"kind": "deal", "title": ""}); check("a find needs a title", False)
except ValueError:
    check("a find needs a title", True)

# ---------------------------------------------------------------- top stories
RSS = b"""<?xml version="1.0"?><rss xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title>Markets close higher</title><link>https://n.example/1</link><description>&lt;p&gt;Stocks up&lt;/p&gt;</description></item>
<item><title>New climbing gym opens downtown</title><link>https://n.example/2</link><description>Bouldering for all</description>
<media:content url="https://n.example/2.jpg"/></item>
<item><title>No link here</title><link>http://insecure/3</link></item>
</channel></rss>"""
items = home.parse_feed(RSS, "Test")
check("RSS is parsed: titles, https links, images, tags stripped", len(items) == 2 and items[1]["image"].endswith("2.jpg")
      and "<p>" not in items[0]["summary"])
db.set_setting("home_news", {"t": time.time(), "items": items})
db.set_setting("profile", {"name": "Sam", "about": "Into: climbing, coffee"})
home._interests = lambda: ["climbing", "coffee"]
n = home.news()
check("stories that match your interests come first", n[0]["title"].startswith("New climbing") and n[0]["match"])

# ---------------------------------------------------------------- the stack and the route
db.set_setting("home_next_event", {"title": "Dentist", "start_t": time.time() + 1800, "when": "3:30 PM"})
st = home.stack()
check("the stack shows the next event and the latest find", any(c["title"] == "Dentist" for c in st)
      and any(c["kind"] == "found" for c in st))
check("most important first", [c["score"] for c in st] == sorted((c["score"] for c in st), reverse=True))


def call(method, path, qs=""):
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": "0",
           "wsgi.input": io.BytesIO(b""), "HTTP_X_PROTOS_KEY": "k"}
    got = {}
    body = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]))))
    return got["s"], json.loads(body)


s, j = call("GET", "/api/home")
check("GET /api/home returns the greeting, stack, finds and stories", s == 200 and j["hello"].startswith("Good")
      and j["found"] and j["news"] and j["stack"])
s, j = call("DELETE", "/api/home", "id=" + j["found"][0]["id"])
check("DELETE takes a find off Home", s == 200 and not j["found"])
print("all home checks passed")
