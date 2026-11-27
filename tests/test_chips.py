"""Chips (server/chips.py): the five built-ins, the list Theta sees each turn, chip_open and chip_save, turning one
off, editing and resetting a built-in, your own chips, and the /api/chips route."""
import io, json, os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp())
from server import app, chips, db, ext, tools


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


db.init()
ext.reset(); tools._ext_reset(); tools._ext()
CTX = {"bot": "theta"}


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else b""
    path, _, qs = path.partition("?")
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(data)),
           "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(data), "HTTP_X_PROTOS_KEY": "k"}
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]))))
    return got["s"], json.loads(out or b"{}")


names = [c["name"] for c in chips.all_chips()]
check("five built-in chips, all on", names == ["Morning brief", "Inbox sweep", "Plan my day", "Best price", "Money check"]
      and all(c["on"] and c["builtin"] and not c["edited"] for c in chips.all_chips()))
check("every built-in has when, a prompt and numbered steps", all(c["when"] and c["prompt"] and c["steps"].startswith("1.")
                                                                  for c in chips.all_chips()))
ctxt = tools.context_block("theta")
check("Theta sees the chips that are on, with when to use them", "Chips (" in ctxt and "Morning brief (" in ctxt
      and "call chip_open first" in ctxt)
ok, out = tools.execute("chip_open", {"name": "morning brief"}, CTX)
check("chip_open gives the steps (any capitalization)", ok and "Weather where they are" in out and "still need their OK" in out)
ok, out = tools.execute("chip_open", {"name": "nope"}, CTX)
check("an unknown chip lists the ones that are on", not ok and "Inbox sweep" in out)
check("the tools: chip_open reads, chip_save writes", tools.BY_NAME["chip_open"]["risk"] == "read"
      and tools.BY_NAME["chip_save"]["risk"] == "write")

chips.set_on("best-price", False)
check("a chip turned off leaves Theta's list", "Best price" not in tools.context_block("theta"))
ok, out = tools.execute("chip_open", {"name": "Best price"}, CTX)
check("and opening it says it's off", ok and "turned off" in out)

ok, out = tools.execute("chip_save", {"name": "Gym check-in", "icon": "🏋️", "when": "They mention the gym",
                                      "prompt": "Check me in", "steps": "1. Open the gym's site.\n2. Book the next class."}, CTX)
mine = chips.find("gym check-in")
check("chip_save makes a new chip, on, with an id from its name", ok and mine and mine["id"] == "gym-check-in"
      and mine["on"] and not mine["builtin"])
tools.execute("chip_save", {"name": "Gym check-in", "steps": "1. Book the 6am class."}, CTX)
check("saving the same name again updates it", chips.find("gym check-in")["steps"] == "1. Book the 6am class."
      and len([c for c in chips.all_chips() if c["name"] == "Gym check-in"]) == 1)

chips.save({"id": "morning-brief", "name": "Morning brief", "icon": "🌅", "when": "x", "prompt": "Brief me", "steps": "1. Only weather."})
mb = chips.find("morning-brief")
check("a built-in can be edited, and says so", mb["edited"] and mb["steps"] == "1. Only weather." and mb["icon"] == "🌅")
chips.remove("morning-brief")
mb = chips.find("morning-brief")
check("Reset brings Theta's version back", not mb["edited"] and mb["steps"].startswith("1. Weather"))
chips.remove("gym-check-in")
check("your own chip can be deleted", chips.find("gym-check-in") is None)
for bad in ({"name": "", "steps": "x"}, {"name": "x", "steps": ""}):
    try:
        chips.save(bad); ok = False
    except ValueError:
        ok = True
    check("a chip needs a name and steps", ok)

s, j = call("GET", "/api/chips")
check("GET /api/chips", s == 200 and len(j["chips"]) == 5)
s, j = call("POST", "/api/chips", {"chip": {"name": "Water plants", "icon": "🪴", "steps": "1. Remind me Sunday 9am."}})
check("POST a new chip", s == 200 and any(c["name"] == "Water plants" for c in j["chips"]))
s, j = call("POST", "/api/chips", {"id": "money-check", "on": False})
check("POST {id, on} turns one off", s == 200 and not next(c for c in j["chips"] if c["id"] == "money-check")["on"])
s, j = call("DELETE", "/api/chips?id=water-plants")
check("DELETE removes it", s == 200 and not any(c["name"] == "Water plants" for c in j["chips"]))
s, j = call("DELETE", "/api/chips?id=nope")
check("an unknown id is a 400", s == 400)
print("all chips checks passed")
