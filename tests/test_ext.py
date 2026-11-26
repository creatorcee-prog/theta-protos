"""The plug-in hookup (server/ext.py): a feature module's tools, routes, public routes, job kinds, tick,
connections and context all reach the app; a broken feature is skipped. Uses a fake feature, no network."""
import io, json, os, sys, tempfile, types
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_DATA=tempfile.mkdtemp())
from server import app, db, ext, tools


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


fake = types.ModuleType("server.fakefeat")
fake.TOOLS = [{"name": "fake_lookup", "risk": "read", "run": lambda a, c: "found " + a["q"],
               "description": "Look something up.", "params": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}]
fake.RELEVANT = r"\bzork\b"
fake.ROUTES = {"/api/fake/": lambda req, start: app.respond_json(start, {"private": req.path})}
fake.PUBLIC_ROUTES = {"/api/fake-hook": lambda req, start: app.respond_json(start, {"public": True})}
fake.JOB_KINDS = {"fakejob": lambda job, now: db.add_message("theta", "assistant", "job ran", {"proactive": True})}
fake.tick = lambda now: [{"id": -1, "text": "ticked"}]
fake.connections = lambda: [{"id": "gmail", "connected": True}, {"id": "fake", "name": "Fake", "connected": True, "what": "x"}]
fake.context = lambda bot, now: "Fake context line."
broken = types.ModuleType("server.broken")
sys.modules["server.fakefeat"] = fake
ext.FEATURES = ("fakefeat", "missingfeature")
ext.reset(); tools._ext_reset()
db.init()


def call(path, method="GET", body=None, key="k"):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http", "REMOTE_ADDR": "1.2.3.4"}
    if key:
        env["HTTP_X_PROTOS_KEY"] = key
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]))))
    return got["s"], json.loads(out or b"{}")


check("a feature's tool is offered to the model, after the core tools", tools.specs()[-1]["name"] == "fake_lookup")
check("and runs", tools.execute("fake_lookup", {"q": "x"}) == (True, "found x"))
check("its words make a message use tools", tools.relevant("open the zork thing"))
check("signed-in routes reach the feature (prefix match)", call("/api/fake/abc") == (200, {"private": "/api/fake/abc"}))
check("but not when signed out", call("/api/fake/abc", key=None)[0] == 401)
check("public routes work signed out (the feature checks the caller)", call("/api/fake-hook", key=None) == (200, {"public": True}))
cons = {c["id"]: c for c in call("/api/connections")[1]}
check("connections merge by id and add new ones", cons["gmail"]["connected"] is True and cons["gmail"]["name"] == "Gmail" and "fake" in cons)
check("the feature's context line goes into tool turns", "Fake context line." in tools.context_block())
db.add_job(0, "fakejob", {})
sent = app.run_jobs()
check("a feature's job kind runs when due", sent and sent[0]["text"] == "job ran")
check("feature ticks run", app.run_features() == [{"id": -1, "text": "ticked"}])
check("a missing feature is skipped quietly", [m.__name__ for m in ext.modules()] == ["server.fakefeat"])
