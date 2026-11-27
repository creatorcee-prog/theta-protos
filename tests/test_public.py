"""Running on a public address (Railway): the wrong-key lockout, refusing to start without PROTOS_KEY, and the
database living on Railway's volume. Stdlib only, no network."""
import io, json, os, subprocess, sys, tempfile
sys.dont_write_bytecode = True
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(PROTOS_KEY="right-key", PROTOS_TICK="0", PROTOS_DATA=tempfile.mkdtemp())
from server import app, db


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def call(path, method="GET", body=None, headers=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http", "REMOTE_ADDR": "1.2.3.4"}
    for k, v in (headers or {}).items():
        env["HTTP_" + k.upper().replace("-", "_")] = v
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]))))
    return got["s"], out


db.init()
app.time.sleep = lambda s: None   # the 0.4 s slow-down, skipped in tests
check("the right key works", call("/api/messages", headers={"x-protos-key": "right-key"})[0] == 200)
phone = app.new_session()  # a device that signed in before the guessing started
for i in range(app.LOCK_FAILS):
    call("/api/login", "POST", {"key": "guess%d" % i})
check("after 20 wrong keys, logins are refused for a while", call("/api/login", "POST", {"key": "right-key"})[0] == 429)
check("and so is the right key in a header, so guessing can't continue that way", call("/api/messages", headers={"x-protos-key": "right-key"})[0] == 401)
check("but a signed-in phone isn't locked out by someone else's guessing",
      call("/api/messages", headers={"cookie": "protos_key=" + phone})[0] == 200)
check("and a made-up session token gets nothing", call("/api/messages", headers={"cookie": "protos_key=s.madeup"})[0] == 401)
app._fails[:] = [t - app.LOCK_WINDOW for t in app._fails]
check("once the window passes, the right key works again", call("/api/login", "POST", {"key": "right-key"})[0] == 200)
check("no key at all isn't counted as a guess", (call("/api/messages")[0], len([t for t in app._fails if t > 0 and app.time.time() - t < app.LOCK_WINDOW])) == (401, 0))

env = dict(os.environ, RAILWAY_ENVIRONMENT="production", PROTOS_KEY="", PORT="0")
r = subprocess.run([sys.executable, "-m", "server"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
check("on Railway without PROTOS_KEY the server refuses to start, and says why", r.returncode == 2 and "PROTOS_KEY is not set" in (r.stdout + r.stderr))

vol = tempfile.mkdtemp()
env = dict(os.environ, RAILWAY_VOLUME_MOUNT_PATH=vol)
env.pop("PROTOS_DATA", None)
out = subprocess.run([sys.executable, "-c", "from server import db; print(db._default_path())"], cwd=ROOT, env=env,
                     capture_output=True, text=True).stdout.strip()
check("the database lives on Railway's volume", out == os.path.join(vol, "protos.db"))
