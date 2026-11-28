"""Agents beside Theta (server/agents.py): made, changed and removed through /api/bots; each has its own chat; the
system prompt says who it is, what it's for and the user's instructions; an agent limited to some apps never gets
the other apps' tools, and load_tools refuses them. The model is faked."""
import io, json, os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp(),
                  DEEPSEEK_API_KEY="sk-test", ANTHROPIC_API_KEY="sk-ant-test")
from server import agent, agents, app, db, ext, models, persona, router, tools


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or got is None else f": {got!r}"))
    if not cond:
        sys.exit(1)


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else b""
    path, _, qs = path.partition("?")
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(data)),
           "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(data), "HTTP_X_PROTOS_KEY": "k"}
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]))))
    return got["s"], json.loads(out)


db.init()
ext.reset(); tools._ext_reset(); tools._ext()
router.CLASSIFIER = None

# ---------------------------------------------------------------- making, changing, removing
s, j = call("GET", "/api/bots")
check("at first there's only Theta", s == 200 and [a["id"] for a in j] == ["theta"], j)
s, j = call("POST", "/api/bots", {"name": "Job hunter", "color": "#4cd07d", "about": "Finds jobs for me",
                                  "instructions": "Never apply without asking.", "apps": ["email", "calendar", "nope"]})
check("an agent is made, with an id from its name and only real apps kept", s == 200 and j["id"] == "job-hunter"
      and j["apps"] == ["email", "calendar"] and j["color"] == "#4cd07d", j)
s, j2 = call("POST", "/api/bots", {"name": "job HUNTER"})
check("two agents can't share a name", s == 400, j2)
s, j2 = call("POST", "/api/bots", {"name": "Theta"})
check("and none can be called Theta", s == 400, j2)
s, j2 = call("POST", "/api/bots", {"name": "<b>x</b>"})
check("a name with markup is refused", s == 400, j2)
s, j = call("GET", "/api/bots?full=1")
check("the full list also gives the apps an agent can be given, and the colors",
      [a["id"] for a in j["agents"]] == ["theta", "job-hunter"] and any(x["key"] == "email" for x in j["apps"]) and j["colors"], j)
s, j = call("POST", "/api/bots/job-hunter", {"about": "Finds roles that fit"})
check("an agent can be changed, keeping what wasn't sent", s == 200 and j["about"] == "Finds roles that fit"
      and j["instructions"] == "Never apply without asking.", j)
s, j = call("POST", "/api/bots/theta", {"name": "Other"})
check("Theta isn't changed here (its name is in Personalization)", s == 400, j)
s, j = call("DELETE", "/api/bots/theta")
check("and Theta can't be removed", s == 400, j)

# ---------------------------------------------------------------- its own chat
db.add_message("job-hunter", "user", "any new roles?")
s, j = call("GET", "/api/messages?bot=job-hunter")
check("an agent has its own chat", s == 200 and [m["text"] for m in j["messages"]] == ["any new roles?"], j)
s, j = call("GET", "/api/messages?bot=theta")
check("which Theta's chat doesn't show", s == 200 and not any(m["text"] == "any new roles?" for m in j["messages"]), j)
s, j = call("GET", "/api/messages?bot=ghost")
check("an agent that doesn't exist has no chat to read", s in (200, 404) and not (j.get("messages") or []), j)

# ---------------------------------------------------------------- who it is, in the prompt
p = persona.system_prompt("job-hunter")
check("its prompt names it, what it's for and the user's instructions", "You are Job hunter" in p
      and "Finds roles that fit" in p and "Never apply without asking." in p, p[:600])
check("and lists the apps it may use", "Apps you may use: Email, Calendar" in p)
check("Theta's prompt is unchanged by agents", "You are Job hunter" not in persona.system_prompt("theta"))

# ---------------------------------------------------------------- its apps
check("Theta may use every tool", agents.allows("theta", "bank_transactions") and agents.allows("theta", "send_text"))
check("the agent may use its apps' tools", agents.allows("job-hunter", "gmail_search") and agents.allows("job-hunter", "calendar_add"))
check("but not another app's", not agents.allows("job-hunter", "bank_transactions") and not agents.allows("job-hunter", "send_text")
      and not agents.allows("job-hunter", "browse_open"))
check("search, memory and reminders always work", agents.allows("job-hunter", "web_search") and agents.allows("job-hunter", "remind_me"))

CALLS, SCRIPT = [], []


def fake_call(provider, model, messages, tools_=None, max_tokens=1024, on_text=None, tool_choice="auto", timeout=None):
    CALLS.append([t["name"] for t in (tools_ or [])])
    step = SCRIPT.pop(0) if SCRIPT else {"text": "Done."}
    if step.get("text") and on_text:
        on_text(step["text"])
    return {"text": step.get("text", ""), "tool_calls": step.get("tool_calls") or [], "reasoning": "",
            "usage": {"tokens_in": 10, "tokens_out": 2, "cache_read": 0, "cache_write": 0}}


models.call = fake_call
R = router.Route(tier="quick", model="deepseek-chat", provider="deepseek", why="t", candidates=(("deepseek", "deepseek-chat"),))
msgs = [{"role": "system", "content": "x"}, {"role": "user", "content": "check my bank and my email and browse for jobs"}]
agent.run(R, msgs, lambda *a, **k: None, ctx={"bot": "job-hunter", "user_text": msgs[-1]["content"]})
offered = set(CALLS[0])
check("a turn offers the agent none of the other apps' tools", not any(n.startswith(("bank_", "browse_", "send_text")) for n in offered), sorted(offered))
CALLS.clear()
agent.run(R, msgs, lambda *a, **k: None, ctx={"bot": "theta", "user_text": msgs[-1]["content"]})
check("while Theta, asked the same, is offered them", any(n.startswith("browse_") for n in CALLS[0]), CALLS[0])

CALLS.clear()
SCRIPT[:] = [{"tool_calls": [{"id": "l1", "name": "load_tools", "args": {"names": ["bank_transactions"]}}]}, {"text": "That's one for Theta."}]
info = {}
agent.run(R, msgs, lambda *a, **k: None, info=info, ctx={"bot": "job-hunter", "user_text": "what did I spend?"})
check("load_tools won't bring in another app's tool", "bank_transactions" not in CALLS[-1], CALLS[-1])

s, j = call("DELETE", "/api/bots/job-hunter")
check("an agent can be removed", s == 200 and [a["id"] for a in call("GET", "/api/bots")[1]] == ["theta"])
check("its chat is kept in the database (nothing erased by surprise)", any(m["text"] == "any new roles?" for m in db.messages("job-hunter")))
s, j = call("POST", "/api/chat", {"bot": "job-hunter", "text": "hi"})
check("but it can't be chatted with any more", s == 404, j)
print("all agents tests passed")
