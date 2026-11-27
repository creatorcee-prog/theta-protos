"""Theta never gets to claim what didn't happen: a finished reply that says something was done when no tool did it
is taken back (a "reset" event) and sent back once to either do it or say plainly it didn't; a reply that says
something was removed while only an add ran is caught too; honest replies pass untouched."""
import os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp(), PROTOS_COMPACT="0",
                  DEEPSEEK_API_KEY="sk-test")
from server import agent, db, ext, models, router, tools


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
ext.reset(); tools._ext_reset(); tools._ext()
ROUTE = router.Route(tier="quick", model="deepseek-chat", provider="deepseek", why="test", candidates=(("deepseek", "deepseek-chat"),))


def run(script, text="drop the dentist"):
    steps, seen, ev = list(script), [], []

    def fake(provider, model, messages, specs=None, max_tokens=1024, on_text=None, tool_choice="auto", timeout=None):
        seen.append([dict(m) for m in messages])
        r = steps.pop(0)
        if r.get("text") and on_text:
            on_text(r["text"])
        return {"text": r.get("text", ""), "tool_calls": r.get("calls", []), "usage": {}}
    models.call = fake
    info = {}
    out = agent.run(ROUTE, [{"role": "system", "content": "You're Theta."}, {"role": "user", "content": text}],
                    lambda e, d: ev.append((e, d)), info=info, ctx={"bot": "theta"})
    return out, ev, seen, info


out, ev, seen, info = run([{"text": "Done, I've cancelled the dentist reminder."},
                           {"text": "I couldn't cancel it: nothing ran. Want me to try again?"}])
check("a reply claiming a change no tool made is taken back", ("reset", {"why": "check"}) in ev and out.startswith("I couldn't"), (ev, out))
check("and the model is told what really ran", "no tool changed anything" in seen[-1][-1]["content"], seen[-1][-1])

out, ev, seen, info = run([{"text": "Here's your week: nothing booked Friday."}], "what's on friday?")
check("an answer with no claim goes straight through (one model call)", len(seen) == 1 and not any(e == "reset" for e, _ in ev), ev)

out, ev, seen, info = run([{"text": "Who should I text?"}], "text someone")
check("a question isn't a claim", len(seen) == 1)

tools.BY_NAME["remind_me"]["run"] = lambda a, c: "Reminder set for 6 PM."
out, ev, seen, info = run([{"calls": [{"id": "1", "name": "remind_me", "args": {"text": "dentist", "when": "in 3 hours"}}]},
                           {"text": "Done: moved it to 6 PM and dropped the old one."},
                           {"text": "Set a new one for 6 PM. I can't remove the old 3 PM one yet."}], "make it 3 hours instead")
check("saying the old one is gone while only an add ran is caught", any(e == "reset" for e, _ in ev)
      and "removed, cancelled or replaced" in seen[-1][-1]["content"] and out.startswith("Set a new one"), (out, seen[-1][-1]))

out, ev, seen, info = run([{"calls": [{"id": "1", "name": "remind_me", "args": {"text": "stretch", "when": "in 2 minutes"}}]},
                           {"text": "Done, I'll remind you to stretch in 2 minutes."}], "remind me to stretch in 2 min")
check("a claim the tools back up passes", not any(e == "reset" for e, _ in ev) and out.startswith("Done"), ev)

out, ev, seen, info = run([{"text": "Done, I've cancelled it."}, {"text": "Done, I've cancelled it."}])
check("it's checked once per turn, never in a loop, and a repeat claim gets a plain correction from code",
      len(seen) == 2 and "nothing was actually changed" in out, out)

out, ev, seen, info = run([{"text": "Gmail isn't connected. Once it's connected I'll send it to your landlord."},
                           {"text": "Gmail isn't connected, so I couldn't save it."}], "email my landlord rent is late")
check("a promise to pick it up later with no tool call is caught too", any(e == "reset" for e, _ in ev)
      and "promises to pick this up" in seen[-1][-1]["content"], seen[-1][-1])

# ---- reminders can be seen, cancelled and moved (remind_me only ever added)
import time as _t
from server import app
R = tools.BY_NAME["reminders"]["run"]
j1 = db.add_job(_t.time() + 3600, "remind", {"text": "dentist", "bot": "theta"})
j2 = db.add_job(_t.time() + 7200, "remind", {"text": "trash", "bot": "theta"})
check("reminders are listed with their ids", f"id {j1}" in R({"action": "list"}, {"bot": "theta"}))
check("the context block shows ids too, so Theta can act on 'cancel that'", f"id {j1}" in tools.context_block("theta"))
R({"action": "move", "id": j1, "in_minutes": 180}, {"bot": "theta"})
check("move changes the time of the same reminder (no second one)", abs(db.get_job(j1)["due_t"] - (_t.time() + 10800)) < 5
      and len([j for j in db.jobs("pending") if j["kind"] == "remind"]) == 2)
R({"action": "cancel", "id": j2}, {"bot": "theta"})
check("cancel really cancels", db.get_job(j2)["state"] == "cancelled")
try:
    R({"action": "cancel", "id": 99999}, {"bot": "theta"}); ok = False
except tools.ToolError:
    ok = True
check("an unknown id is an error the model sees, not a fake success", ok)
check("reminders is a tool Theta always has", "reminders" in tools.CORE)
import io, json as _j
raw = _j.dumps({"action": "cancel"}).encode()
env = {"REQUEST_METHOD": "POST", "PATH_INFO": f"/api/jobs/{j1}", "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
       "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(raw)}
got = {}
b"".join(app.app(env, lambda st, h: got.update(s=int(st.split()[0]))))
check("the app can cancel one too (POST /api/jobs/<id>)", got["s"] == 200 and db.get_job(j1)["state"] == "cancelled", got)

# ---- Stop: the stream is cut at once and nothing new starts
flag = {"stop": False}
def streams(provider, model, messages, specs=None, max_tokens=1024, on_text=None, tool_choice="auto", timeout=None):
    on_text("Looking at ramen spots ")
    flag["stop"] = True
    on_text("and more words that never show")
    return {"text": "x", "tool_calls": [{"id": "9", "name": "remind_me", "args": {"text": "x", "in_minutes": 5}}], "usage": {}}
models.call = streams
ev = []
out = agent.run(ROUTE, [{"role": "user", "content": "find ramen"}], lambda e, d: ev.append((e, d)), info={},
                ctx={"bot": "theta", "stopped": lambda: flag["stop"]})
check("Stop cuts the reply where it was and says nothing was changed", "never show" not in out and "Stopped" in out
      and "Nothing was changed" in out and not any(e == "tool" for e, _ in ev), out)
from server import runtime
r = runtime.begin("theta", 1)
check("POST /api/chat/stop marks the running turn stopped", runtime.stop("theta") and r.stopped)
runtime.end("theta", r)
check("and with nothing running, there's nothing to stop", runtime.stop("theta") is False)

# ---- a reply stream that just stops is an error (kept as partial), not a finished reply; brief 429/5xx are retried
import importlib
M = importlib.reload(models)
class _R:
    def __init__(s, lines): s.lines = lines
    def __iter__(s): return iter(s.lines)
    def close(s): pass
real_post, real_events = M._post, M._events
M._post = lambda *a, **k: _R([b'data: {"choices":[{"delta":{"content":"Here is half"}}]}\n', b"\n"])
M._events = lambda p, r: M.sse_events(iter(r))
try:
    list(M._openai_gen("deepseek", "deepseek-chat", [{"role": "user", "content": "hi"}], 100, usage={})); ok = False
except M.ModelError as e:
    ok = "cut off" in str(e)
check("a stream cut mid-reply is an error, not a complete reply", ok)
M._post = lambda *a, **k: _R([b'data: {"choices":[{"delta":{"content":"All of it."},"finish_reason":"stop"}]}\n', b"\n"])
check("a finished stream is fine", [v for k, v in M._openai_gen("deepseek", "deepseek-chat", [], 100, usage={})] == ["All of it."])
M._post, M._events = real_post, real_events
tries = []
def flaky(*a, **k):
    tries.append(1)
    if len(tries) < 3:
        raise M.ModelError("deepseek HTTP 503: busy", status=503)
    return "opened"
M._post_once, M.time.sleep = flaky, (lambda s: None)
check("a brief 503 is tried again on the same provider", M._post("deepseek", "u", {}, {}) == "opened" and len(tries) == 3)
tries.clear()
def bad(*a, **k):
    tries.append(1); raise M.ModelError("deepseek HTTP 400: bad", status=400)
M._post_once = bad
try:
    M._post("deepseek", "u", {}, {})
except M.ModelError:
    pass
check("a real error (400) isn't retried", len(tries) == 1)
models = importlib.reload(M)

# ---- the same send twice runs once
calls = []
def one(provider, model, messages, specs=None, max_tokens=1024, on_text=None, tool_choice="auto", timeout=None):
    calls.append(1)
    if on_text: on_text("Hi there.")
    return {"text": "Hi there.", "tool_calls": [], "usage": {}}
models.call = one
models.stream = lambda *a, **k: iter([]) 
def chat(cid):
    raw = _j.dumps({"bot": "theta", "text": "plan my week please", "client_id": cid}).encode()
    env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/chat", "QUERY_STRING": "stream=0", "CONTENT_LENGTH": str(len(raw)),
           "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(raw)}
    got = {}
    out = b"".join(app.app(env, lambda st, h: got.update(s=int(st.split()[0]))))
    return got["s"], _j.loads(out)
s1, a = chat("c-same")
n_users = len([m for m in db.messages("theta") if m["role"] == "user"])
s2, b = chat("c-same")
check("the same client_id sent twice runs once and gets the same reply", s1 == s2 == 200 and a["reply"]["id"] == b["reply"]["id"]
      and len([m for m in db.messages("theta") if m["role"] == "user"]) == n_users, (a, b))
print("all honesty checks passed")
