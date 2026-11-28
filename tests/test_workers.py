"""Workers (server/workers.py): agents have addresses like email; a worker takes a job into the background and posts
its result in its agent's chat; agent_send hands a job to another agent by address and the answer comes back; every
worker runs on DeepSeek; all workers together stay under the day's cap (five cents by default) and one stops before
a step that would cross it. The model is faked."""
import io, json, os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp(),
                  DEEPSEEK_API_KEY="sk-test", ANTHROPIC_API_KEY="sk-ant-test")
from server import agents, app, db, ext, models, router, subagents, tools, workers


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


def wait(pred, s=10):
    end = time.time() + s
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


db.init()
ext.reset(); tools._ext_reset(); tools._ext()
router.CLASSIFIER = None
CALLS = []
MODE = {"loop": False, "tokens": 1000}


def fake_call(provider, model, messages, tools_=None, max_tokens=1024, on_text=None, tool_choice="auto", timeout=None):
    CALLS.append({"provider": provider, "model": model, "tools": [t["name"] for t in (tools_ or [])]})
    usage = {"tokens_in": MODE["tokens"], "tokens_out": 100, "cache_read": 0, "cache_write": 0}
    if MODE["loop"]:  # keeps working: one more search every step
        return {"text": "", "tool_calls": [{"id": f"s{len(CALLS)}", "name": "history_search", "args": {"query": "x"}}],
                "reasoning": "", "usage": usage}
    if on_text:
        on_text("Found three roles: A, B and C.")
    return {"text": "Found three roles: A, B and C.", "tool_calls": [], "reasoning": "", "usage": usage}


models.call = fake_call

# ---------------------------------------------------------------- addresses
s, ag = call("POST", "/api/bots", {"name": "Job hunter", "apps": ["email"]})
s, mo = call("POST", "/api/bots", {"name": "Money", "apps": ["money"]})
s, j = call("GET", "/api/bots")
check("every agent has an address like an email", {a["id"]: a["address"] for a in j} ==
      {"theta": "theta@home", "job-hunter": "job-hunter@home", "money": "money@home"}, j)
check("an address, a bare id or a name finds the agent", workers.resolve("money@home")["id"] == "money"
      and workers.resolve("Job hunter")["id"] == "job-hunter" and workers.resolve("w2.money@home")["id"] == "money"
      and workers.resolve("nobody@home") is None)
from server import persona  # noqa: E402
p = persona.system_prompt("job-hunter")
check("an agent's prompt gives its address and the team's", "Your address is job-hunter@home" in p
      and "money@home" in p and "theta@home" in p, p[-500:])
check("and Theta's prompt lists the team too, once there is one", "job-hunter@home" in persona.system_prompt("theta"))

# ---------------------------------------------------------------- a background job
check("the cap all workers share is five cents a day by default", abs(workers.cap() - 0.05) < 1e-9)
out = tools.execute("start_job", {"title": "Find roles", "goal": "Find 3 remote roles"}, {"bot": "job-hunter"})
check("start_job answers at once with the worker's address", "w1.job-hunter@home" in str(out), out)
check("the worker runs on DeepSeek", wait(lambda: CALLS) and all(c["provider"] == "deepseek" for c in CALLS), CALLS[:2])
check("and posts its result in its agent's chat", wait(lambda: any(m["meta"].get("source") == "worker" for m in db.messages("job-hunter"))))
m = [m for m in db.messages("job-hunter") if m["meta"].get("source") == "worker"][-1]
check("the result names the worker and the job", m["meta"]["worker"] == "w1.job-hunter@home" and m["meta"]["job_title"] == "Find roles"
      and "Found three roles" in m["text"], m)
check("the worker was offered only its agent's apps", all(not n.startswith("bank_") for c in CALLS for n in c["tools"]))
check("not in Theta's chat", not any(x["meta"].get("source") == "worker" for x in db.messages("theta")))
s, j = call("GET", "/api/workers")
check("GET /api/workers lists the job, done, with its cost and the day's total",
      s == 200 and j["jobs"][0]["state"] == "done" and j["jobs"][0]["cost"] > 0 and abs(j["spent_usd"] - j["jobs"][0]["cost"]) < 1e-6
      and j["cap_usd"] == 0.05, j)
check("the spend is the same pool the research helpers use", abs(subagents.spent_today() - j["spent_usd"]) < 1e-6)

# ---------------------------------------------------------------- one agent hands a job to another
CALLS.clear()
out = tools.execute("agent_send", {"to": "money@home", "message": "What did I spend on subscriptions in May?"}, {"bot": "job-hunter"})
check("agent_send hands the job to the agent at that address", "money@home" in str(out) and "w1.money@home" in str(out), out)
check("the request shows in that agent's chat, from the sender's address",
      any("From **Job hunter** (job-hunter@home)" in x["text"] for x in db.messages("money")))
check("and the answer comes back to the sender's chat", wait(lambda: any("**Money** (money@home) answered" in x["text"] for x in db.messages("job-hunter"))))
check("a bad address lists the team", "theta@home" in str(tools.execute("agent_send", {"to": "zed@home", "message": "x"}, {"bot": "theta"})))
r = str(tools.execute("start_job", {"title": "x", "goal": "y"}, {"bot": "theta", "worker": "j1"}))
check("a worker can't start more workers", "can't start more workers" in r, r)

# ---------------------------------------------------------------- the cap
db.set_setting("subagent_daily_usd", subagents.spent_today() + 0.004)   # room for only a few steps
MODE.update(loop=True, tokens=8000)   # each step about $0.0023
CALLS.clear()
before = subagents.spent_today()
tools.execute("start_job", {"title": "Long one", "goal": "Search forever"}, {"bot": "job-hunter"})
check("a worker that would go over the cap stops", wait(lambda: workers.all_jobs()[-1]["state"] != "running"))
last = workers.all_jobs()[-1]
check("it's marked stopped, and says the budget ran out", last["state"] == "stopped"
      and "workers share ran out" in (db.get_message(last["message"]) or {}).get("text", ""), last)
check("and the day's total never went past the cap", subagents.spent_today() <= workers.cap() + 1e-9,
      (subagents.spent_today(), workers.cap(), before))
r = str(tools.execute("start_job", {"title": "More", "goal": "z"}, {"bot": "job-hunter"}))
check("with the budget used up, no new worker starts", "budget" in r and "used up" in r, r)

# ---------------------------------------------------------------- stopping one, and DeepSeek only
db.set_setting("subagent_daily_usd", 5.0)
MODE.update(loop=True, tokens=100)
orig = models.call
models.call = lambda *a, **k: (time.sleep(0.2), fake_call(*a, **k))[1]
tools.execute("start_job", {"title": "Stop me", "goal": "loop"}, {"bot": "theta"})
jid = workers.all_jobs()[-1]["id"]
time.sleep(0.3)
s, j = call("POST", f"/api/workers/{jid}/stop", {})
check("POST /api/workers/<id>/stop stops a running job", s == 200 and wait(lambda: workers.all_jobs()[-1]["state"] == "stopped"), j)
models.call = orig
avail = models.available
models.available = lambda: ["anthropic"]
r = str(tools.execute("start_job", {"title": "x", "goal": "y"}, {"bot": "theta"}))
check("without a DeepSeek key no worker starts (workers are DeepSeek only)", "DeepSeek" in r, r)
models.available = avail
print("all workers tests passed")
