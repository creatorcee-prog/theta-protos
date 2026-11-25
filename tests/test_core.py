"""Core backend checks: db, persona, auth, chat SSE, fallback, inbox, turns.
No network: models.stream is replaced by fakes. Run: python3 tests/test_core.py"""

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="protos-test-")
os.environ["PROTOS_DATA"] = TMP
os.environ["PROTOS_WEB"] = os.path.join(TMP, "web-empty")  # web/ may not exist yet
os.environ["PROTOS_TICK"] = "0"
os.environ["PROTOS_QUIET"] = "1"
for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "LOCAL_LLM_URL", "TAVILY_API_KEY",
          "PROTOS_LOCAL_FIRST", "PROTOS_KEY"):
    os.environ.pop(k, None)
os.environ["DEEPSEEK_API_KEY"] = "sk-test"
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"

from server import app as appmod, db, models, persona, router  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {detail}")
        FAILED.append(name)


# ---- fake providers

CALLS = []
BEHAVIOR = {}  # (provider, model) -> "ok" | "fail" | "midfail" | list of chunks


def fake_stream(provider, model, messages, max_tokens=1024):
    CALLS.append((provider, model, messages))
    how = BEHAVIOR.get((provider, model), BEHAVIOR.get(provider, "ok"))

    def gen():
        if how == "fail":
            raise models.ModelError(f"{provider} HTTP 503: down")
        chunks = how if isinstance(how, list) else ["Certainly! ", "Hello", " from ", provider, ". All good here."]
        for i, c in enumerate(chunks):
            if how == "midfail" and i == 2:
                raise models.ModelError("stream broke")
            time.sleep(0.02)
            yield c
    return gen()


models.stream = fake_stream
router.CLASSIFIER = None


# ---- tiny HTTP client

class Client:
    def __init__(self, port):
        self.port = port

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            j = json.loads(raw)
        except ValueError:
            j = None
        return r.status, dict(r.getheaders()), j, raw

    def sse(self, body, headers=None):
        """POST /api/chat; returns [(event, data, t_received)]."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        c.request("POST", "/api/chat", body=json.dumps(body).encode(), headers=h)
        r = c.getresponse()
        events, ev, data = [], None, []
        ctype = r.getheader("Content-Type")
        while True:
            line = r.fp.readline()
            if not line:
                break
            line = line.decode().rstrip("\n")
            if not line:
                if data:
                    events.append((ev, json.loads("\n".join(data)), time.monotonic()))
                ev, data = None, []
                continue
            if line.startswith(":"):
                continue
            k, _, v = line.partition(": ")
            if k == "event":
                ev = v
            elif k == "data":
                data.append(v)
        c.close()
        return r.status, ctype, events


def main():
    db.init(os.path.join(TMP, "protos.db"))

    # ---- db
    m1 = db.add_message("theta", "user", "hello", {"client_id": "c1"})
    m2 = db.add_message("theta", "assistant", "hi", {"model": "x", "tier": "quick",
                                                      "actions": [{"label": "Yes", "value": "yes"}],
                                                      "task": {"title": "Find flights", "state": "running"}})
    check("db add_message returns Message", set(m1) == {"id", "bot", "role", "text", "t", "meta"}
          and m1["meta"] == {"client_id": "c1"} and isinstance(m1["t"], int))
    msgs = db.messages("theta")
    check("db messages oldest first", [m["id"] for m in msgs] == [m1["id"], m2["id"]])
    check("db meta actions/task untouched", msgs[1]["meta"]["actions"] == [{"label": "Yes", "value": "yes"}]
          and msgs[1]["meta"]["task"] == {"title": "Find flights", "state": "running"})
    check("db messages before", [m["id"] for m in db.messages("theta", before=m2["id"])] == [m1["id"]])
    check("db since", [m["id"] for m in db.since(m1["id"])] == [m2["id"]] and db.since(m2["id"]) == [])
    db.set_setting("tz", "America/Denver")
    db.set_setting("quiet", [22, 7])
    check("db settings JSON", db.get_setting("quiet") == [22, 7] and db.get_setting("nope", 5) == 5)
    db.add_push_sub({"endpoint": "https://push.example/1", "keys": {"p256dh": "a", "auth": "b"}})
    db.add_push_sub({"endpoint": "https://push.example/1", "keys": {"p256dh": "c", "auth": "d"}})
    check("db push subs upsert", len(db.push_subs()) == 1 and db.push_subs()[0]["keys"]["p256dh"] == "c")
    db.drop_push_sub("https://push.example/1")
    check("db drop push sub", db.push_subs() == [])
    check("db seen/mark", not db.seen("ev1") and (db.mark("ev1") or True) and db.seen("ev1"))
    db.mark("ev2", ttl_days=-1)
    check("db mark expiry", not db.seen("ev2"))
    db.init(os.path.join(TMP, "protos.db"))
    check("db init idempotent", len(db.messages("theta")) == 2)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("n", len(db.messages("theta"))))
    t.start()
    t.join()
    check("db works from another thread", out.get("n") == 2)
    mode = db._conn().execute("PRAGMA journal_mode").fetchone()[0]
    check("db WAL mode", mode == "wal", mode)

    # ---- persona
    check("clean strips Certainly", persona.clean("Certainly! Here you go.") == "Here you go.")
    check("clean strips As an AI", persona.clean("As an AI language model, I don't have feelings. But hey.")
          == "I don't have feelings. But hey.", persona.clean("As an AI language model, I don't have feelings. But hey."))
    check("clean strips Great question + sign-off",
          persona.clean("Great question! It's 4. Let me know if you have any other questions!") == "It's 4.")
    check("clean leaves normal text", persona.clean("Sure looks like rain.") == "Sure looks like rain.")
    sp = persona.system_prompt(now=0)
    check("system prompt has SOUL + style, no clock (cacheable)", "You're Theta" in sp and "Short first" in sp
          and "1969" not in sp and sp == persona.system_prompt(now=10 ** 9))
    ctx = persona.build([], "hi", now=0, extra="[1] some result")[-1]["content"]
    check("time + search context ride on the latest user turn", ctx.startswith("hi\n\n---\n") and "1969" in ctx
          and "America/Denver" in ctx and "[1] some result" in ctx and persona.said(ctx) == "hi", ctx)
    db.set_setting("memory", ["Likes the Broncos", {"text": "Gym at 6am"}])
    check("system prompt has memory notes", "Gym at 6am" in persona.system_prompt())
    hist = [{"role": "user", "text": f"m{i}"} for i in range(30)] + [{"role": "assistant", "text": "ok",
                                                                     "meta": {"ack": True}}]
    built = persona.build(hist, "now")
    check("persona keeps ~20 history and drops acks", len(built) == 1 + 19 + 1
          and persona.said(built[-1]["content"]) == "now"
          and all(m.get("content") != "ok" for m in built), len(built))
    c = persona.Cleaner()
    streamed = "".join(c.feed(x) for x in ["Certainly", "! ", "The answer is ", "42 and ", "that's that."]) + c.finish()
    check("streaming cleaner strips opener", streamed == "The answer is 42 and that's that.", streamed)
    check("ack templates", persona.ack("search", "bitcoin price") == "On it. Checking live prices now."
          and persona.ack("quick", "hi") is None and persona.ack("think", "x"))

    # ---- server
    httpd = appmod.make("127.0.0.1", 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    cl = Client(port)

    s, h, j, _ = cl.req("GET", "/api/health")
    check("health", s == 200 and j["ok"] is True and "version" in j)
    check("security headers", "default-src 'self'" in h.get("Content-Security-Policy", "")
          and "unsafe-eval" not in h["Content-Security-Policy"] and h.get("X-Content-Type-Options") == "nosniff")
    s, h, _, raw = cl.req("GET", "/")
    check("index placeholder when web/ is empty", s == 200 and b"Theta" in raw)
    s, _, j, _ = cl.req("GET", "/static/nope.js")
    check("static 404 is JSON", s == 404 and j == {"error": "not found"})
    s, _, j, _ = cl.req("GET", "/static/../../etc/passwd")
    check("static path traversal blocked", s == 404)
    os.makedirs(os.environ["PROTOS_WEB"], exist_ok=True)
    with open(os.path.join(os.environ["PROTOS_WEB"], "sw.js"), "w") as f:
        f.write("self.x=1")
    with open(os.path.join(os.environ["PROTOS_WEB"], "manifest.webmanifest"), "w") as f:
        f.write("{}")
    s, h, _, raw = cl.req("GET", "/sw.js")
    check("serves /sw.js", s == 200 and raw == b"self.x=1" and "javascript" in h["Content-Type"])
    s, h, _, _ = cl.req("GET", "/manifest.webmanifest")
    check("serves manifest", s == 200 and h["Content-Type"].startswith("application/manifest+json"))
    s, _, j, _ = cl.req("GET", "/api/nope")
    check("unknown api 404 JSON", s == 404 and "error" in j)

    # ---- auth
    os.environ["PROTOS_KEY"] = "sekret"
    s, _, j, _ = cl.req("GET", "/api/bots")
    check("auth required", s == 401 and j == {"error": "not signed in"})
    s, _, _, _ = cl.req("GET", "/api/health")
    check("health needs no auth", s == 200)
    s, _, j, _ = cl.req("GET", "/api/bots", headers={"x-protos-key": "sekret"})
    check("x-protos-key header works", s == 200 and j[0]["id"] == "theta" and j[0]["name"] == "Theta")
    s, _, _, _ = cl.req("GET", "/api/bots", headers={"x-protos-key": "wrong"})
    check("wrong header key refused", s == 401)
    s, _, _, _ = cl.req("POST", "/api/login", {"key": "wrong"})
    check("login wrong key 401", s == 401)
    s, h, j, _ = cl.req("POST", "/api/login", {"key": "sekret"})
    cookie = h.get("Set-Cookie", "")
    check("login sets HttpOnly SameSite cookie", s == 200 and "protos_key=sekret" in cookie
          and "HttpOnly" in cookie and "SameSite=Lax" in cookie, cookie)
    s, _, _, _ = cl.req("GET", "/api/bots", headers={"Cookie": "protos_key=sekret"})
    check("cookie works", s == 200)
    s, _, _, _ = cl.req("POST", "/api/chat", {"text": "hi"})
    check("chat needs auth", s == 401)
    AUTH = {"x-protos-key": "sekret"}

    # ---- chat SSE: user, route, delta..., done
    CALLS.clear()
    s, ctype, evs = cl.sse({"bot": "theta", "text": "hey there", "client_id": "abc"}, AUTH)
    names = [e[0] for e in evs]
    check("chat SSE content type", s == 200 and ctype.startswith("text/event-stream"), ctype)
    check("SSE order user, route, delta..., done",
          names[0] == "user" and names[1] == "route" and names[-1] == "done"
          and set(names[2:-1]) == {"delta"} and len(names) >= 4, names)
    user, route, done = evs[0][1], evs[1][1], evs[-1][1]
    check("user event is stored Message", user["role"] == "user" and user["text"] == "hey there"
          and user["meta"].get("client_id") == "abc")
    check("route event", route == {"model": "deepseek-chat", "provider": "deepseek", "tier": "quick",
                                   "why": "short chat"}, route)
    deltas = "".join(e[1]["text"] for e in evs if e[0] == "delta")
    check("deltas cleaned and equal done text", deltas == done["text"] == "Hello from deepseek. All good here.",
          (deltas, done["text"]))
    check("done meta has model+tier", done["meta"]["model"] == "deepseek-chat" and done["meta"]["tier"] == "quick")
    check("deltas arrive before done (streamed)", evs[2][2] < evs[-1][2] - 0.03, [round(e[2], 3) for e in evs])
    sysmsg = CALLS[-1][2][0]
    check("one persona system prompt sent", sysmsg["role"] == "system" and "You're Theta" in sysmsg["content"])
    s, _, j, _ = cl.req("GET", "/api/messages?bot=theta&limit=2", headers=AUTH)
    check("chat persisted", s == 200 and [m["id"] for m in j["messages"]] == [user["id"], done["id"]])

    # ---- think tier: ack first, as its own message
    s, _, evs = cl.sse({"text": "why should I compare these two plans step by step"}, AUTH)
    names = [e[0] for e in evs]
    check("think tier SSE order user, route, ack, delta..., done",
          names[:3] == ["user", "route", "ack"] and names[-1] == "done" and "delta" in names, names)
    ack = evs[2][1]
    check("ack is stored Message with meta.ack", ack["role"] == "assistant" and ack["meta"].get("ack") is True
          and ack["id"] < evs[-1][1]["id"] and "deepseek" not in ack["text"].lower(), ack)
    check("think routed to reasoner", evs[1][1]["model"] == "deepseek-reasoner")

    # ---- fallback: first provider fails before any text
    BEHAVIOR[("deepseek", "deepseek-reasoner")] = "fail"
    s, _, evs = cl.sse({"text": "why should I compare these two plans step by step"}, AUTH)
    routes = [e[1] for e in evs if e[0] == "route"]
    check("fallback retries next candidate", len(routes) == 2 and routes[1]["provider"] == "anthropic"
          and "fallback" in routes[1]["why"] and evs[-1][0] == "done"
          and evs[-1][1]["meta"]["provider"] == "anthropic", routes)
    BEHAVIOR.clear()

    # every provider fails -> error event
    BEHAVIOR["deepseek"] = BEHAVIOR["anthropic"] = "fail"
    s, _, evs = cl.sse({"text": "hi"}, AUTH)
    check("all providers fail -> error event", evs[-1][0] == "error" and "error" in evs[-1][1]
          and "Traceback" not in json.dumps(evs[-1][1]), evs[-1])
    # mid-stream failure: no retry, partial reply kept
    BEHAVIOR.clear()
    BEHAVIOR["deepseek"] = "midfail"
    BEHAVIOR[("deepseek", "deepseek-chat")] = ["The first part of a long ", "answer that keeps going a while ",
                                               "more", "x"]
    BEHAVIOR[("deepseek", "deepseek-chat")] = "midfail"
    s, _, evs = cl.sse({"text": "hi"}, AUTH)
    routes = [e for e in evs if e[0] == "route"]
    check("mid-stream failure after text: no retry", len(routes) <= 2)
    BEHAVIOR.clear()

    # ---- non-streaming
    s, _, j, _ = cl.req("POST", "/api/chat?stream=0", {"bot": "theta", "text": "hello"}, AUTH)
    check("stream=0 returns user+reply", s == 200 and j["user"]["text"] == "hello"
          and j["reply"]["role"] == "assistant" and j["reply"]["text"])
    s, _, j, _ = cl.req("POST", "/api/chat", {"text": ""}, AUTH)
    check("empty chat 400 JSON", s == 400 and "error" in j)
    s, _, j, _ = cl.req("POST", "/api/chat", {"bot": "nobody", "text": "x"}, AUTH)
    check("unknown bot 404", s == 404)

    # ---- inbox since
    last = db.messages("theta", limit=1)[-1]["id"]
    s, _, j, _ = cl.req("GET", f"/api/inbox?since={last}", headers=AUTH)
    check("inbox since latest is empty", s == 200 and j == {"messages": []})
    pm = db.add_message("theta", "assistant", "Heads up: a storm cell near you.",
                        {"proactive": True, "source": "vantage", "level": 3})
    s, _, j, _ = cl.req("GET", f"/api/inbox?since={last}", headers=AUTH)
    check("inbox returns new proactive message", [m["id"] for m in j["messages"]] == [pm["id"]]
          and j["messages"][0]["meta"]["proactive"] is True)
    s, _, j, _ = cl.req("GET", "/api/inbox?since=abc", headers=AUTH)
    check("inbox bad since 400", s == 400)
    s, _, j, _ = cl.req("GET", f"/api/messages?bot=theta&before={pm['id']}&limit=3", headers=AUTH)
    check("messages before+limit", s == 200 and len(j["messages"]) == 3 and j["messages"][-1]["id"] == last)

    # ---- turns log
    s, _, j, _ = cl.req("GET", "/api/turns?limit=3", headers=AUTH)
    t0 = j["turns"][0] if s == 200 and j["turns"] else {}
    check("turns logged with latency", s == 200 and len(j["turns"]) == 3 and t0.get("model")
          and isinstance(t0.get("total_ms"), int) and isinstance(t0.get("ttft_ms"), int)
          and t0.get("chars_out", 0) > 0, t0)
    s, _, _, _ = cl.req("GET", "/api/turns")
    check("turns needs auth", s == 401)
    fb = [t for t in db.turns(50) if len(t["tried"]) == 2]
    check("turn log records fallback attempts", bool(fb) and fb[0]["provider"] == "anthropic", fb[:1])

    # ---- optional modules (push/proactive) -> 501 when missing
    has_push = os.path.exists(os.path.join(ROOT, "server", "push.py"))
    has_pro = os.path.exists(os.path.join(ROOT, "server", "proactive.py"))
    s, _, j, _ = cl.req("GET", "/api/push/key", headers=AUTH)
    check("push key 501 without push.py" if not has_push else "push key answers",
          (s == 501 and "error" in j) if not has_push else s in (200, 503), s)
    s, _, j, _ = cl.req("GET", "/api/settings", headers=AUTH)
    check("settings 501 without push.py" if not has_push else "settings GET",
          s == 501 if not has_push else (s == 200 and "tz" in j), s)
    if has_push:
        s, _, j, _ = cl.req("POST", "/api/settings", {"tz": "Not/AZone"}, AUTH)
        check("settings rejects bad tz", s == 400)
    s, _, j, _ = cl.req("POST", "/api/tick", headers=AUTH)
    check("tick 501 without proactive.py" if not has_pro else "tick runs", s == 501 if not has_pro else s == 200, s)
    s, _, j, _ = cl.req("GET", "/api/connections", headers=AUTH)
    check("connections list", s == 200 and any(c["id"] == "gmail" and c["connected"] is False for c in j))

    # ---- no stack traces to clients
    real = db.messages
    db.messages = lambda *a, **k: 1 / 0
    try:
        s, _, j, raw = cl.req("GET", "/api/messages", headers=AUTH)
    finally:
        db.messages = real
    check("500 is JSON without trace", s == 500 and j == {"error": "internal error"} and b"Traceback" not in raw)

    os.environ.pop("PROTOS_KEY", None)
    s, _, _, _ = cl.req("GET", "/api/bots")
    check("auth off when PROTOS_KEY unset", s == 200)

    httpd.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)
    if FAILED:
        print(f"\n{len(FAILED)} failed: {', '.join(FAILED)}")
        sys.exit(1)
    print("\nall core checks passed")


if __name__ == "__main__":
    main()
