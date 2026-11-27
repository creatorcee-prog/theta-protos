"""The new agent loop (server/agent.py + server/runtime.py): a turn starts with a small toolset and loads more on
demand; a message sent mid-turn steers it; one sent after its last step gets a follow-up turn; old tool output is
trimmed in long turns; a stuck turn is told to change approach (and moves to a stronger model); a failed step is
said plainly; checkpoints let a turn cut off by a restart pick up where it was. The model is faked."""
import io, json, os, sys, tempfile, threading, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp(),
                  DEEPSEEK_API_KEY="sk-test", ANTHROPIC_API_KEY="sk-ant-test")
from server import agent, app, db, ext, models, router, runtime, tools


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


db.init()
ext.reset(); tools._ext_reset(); tools._ext()
router.CLASSIFIER = None
CALLS, SCRIPT = [], []


def fake_call(provider, model, messages, tools_=None, max_tokens=1024, on_text=None, tool_choice="auto", timeout=None):
    CALLS.append({"provider": provider, "model": model, "messages": [dict(m) for m in messages],
                  "tools": [t["name"] for t in (tools_ or [])]})
    step = SCRIPT.pop(0) if SCRIPT else {"text": "Done."}
    if callable(step):
        step = step(messages)
    if step.get("text") and on_text:
        on_text(step["text"])
    return {"text": step.get("text", ""), "tool_calls": step.get("tool_calls") or [], "reasoning": "",
            "usage": {"tokens_in": 10, "tokens_out": 2, "cache_read": 0, "cache_write": 0}}


models.call = fake_call
R = router.Route(tier="quick", model="deepseek-chat", provider="deepseek", why="t", candidates=(("deepseek", "deepseek-chat"),))
tc = lambda n, a, i=None: {"id": i or f"c{len(CALLS)}{n}", "name": n, "args": a}  # noqa: E731
msgs = lambda t: [{"role": "system", "content": "x"}, {"role": "user", "content": t}]  # noqa: E731

# ---------------------------------------------------------------- a small toolset, more on demand
SCRIPT[:] = [{"tool_calls": [tc("load_tools", {"names": ["bank_accounts"]})]}, {"tool_calls": [tc("bank_accounts", {})]}, {"text": "ok"}]
agent.run(R, msgs("hi, what's the weather like"), lambda e, d: None, info={}, ctx={"bot": "theta"})
first = CALLS[0]["tools"]
check("a turn starts with the core tools, not all of them", "web_search" in first and "browse_open" in first
      and len(first) < len(tools.TOOLS) / 2 and "gmail_trash" not in first)
check("load_tools adds a tool for the next step", "bank_accounts" not in first and "bank_accounts" in CALLS[1]["tools"])
check("the rest are listed by name in the instructions", "gmail_trash" in CALLS[0]["messages"][0]["content"])
CALLS.clear(); SCRIPT[:] = [{"text": "ok"}]
agent.run(R, msgs("clean up my inbox and archive the newsletters"), lambda e, d: None, info={}, ctx={"bot": "theta"})
check("words that call for a group bring it along (email)", "gmail_archive" in CALLS[0]["tools"])

# ---------------------------------------------------------------- browser tools get time
check("browser steps get time for slow pages (not the 20 s default)", tools.BY_NAME["browse_act"]["timeout"] >= 60
      and agent.TURN_SECONDS >= 300 and agent.MAX_STEPS >= 20)

# ---------------------------------------------------------------- steering mid-turn
CALLS.clear()
inbox = ["actually make it Friday instead"]
SCRIPT[:] = [{"tool_calls": [tc("history_search", {"query": "x"})]}, {"text": "Booked for Friday."}]
agent.run(R, msgs("book it for Thursday"), lambda e, d: None, info={},
          ctx={"bot": "theta", "inbox": lambda: [inbox.pop()] if inbox else []})
check("a message sent mid-turn reaches the model at the next step", any("make it Friday" in str(m.get("content"))
      for m in CALLS[-1]["messages"] if m["role"] == "user"))

# ---------------------------------------------------------------- stuck: change approach, stronger model
CALLS.clear()
SCRIPT[:] = [{"tool_calls": [tc("file_read", {"id": "nope"})]}] * 3 + [{"text": "I couldn't read that file."}]
ev = []
agent.run(R, msgs("read my file"), lambda e, d: ev.append((e, d)), info={}, ctx={"bot": "theta"})
check("two failed steps: told to change approach, not retry", any("Don't repeat them" in str(m.get("content"))
      for m in CALLS[-1]["messages"]))
check("and a stronger model takes over (once)", any(e == "route" and d.get("tier") == "think" for e, d in ev)
      and CALLS[-1]["model"] == router.candidates("think")[0][1])

# ---------------------------------------------------------------- a failed step is said plainly
CALLS.clear()
out_ev = []
SCRIPT[:] = [{"tool_calls": [tc("file_read", {"id": "missing"})]}, {"text": "All set!"}]
agent.run(R, msgs("read it"), lambda e, d: out_ev.append((e, d)), info={}, ctx={"bot": "theta"})
said = "".join(d.get("text", "") for e, d in out_ev if e == "delta")
check("a step that failed and was never redone is said in the reply", "One step didn't work" in said)

# ---------------------------------------------------------------- compaction
big = [{"role": "system", "content": "x"}, {"role": "user", "content": "go"}]
for i in range(30):
    big += [{"role": "assistant", "content": "", "tool_calls": [tc("web_search", {"query": str(i)}, f"k{i}")]},
            {"role": "tool", "tool_call_id": f"k{i}", "name": "web_search", "content": "r" * 5000}]
agent._compact(big)
tool_msgs = [m for m in big if m["role"] == "tool"]
check("a long turn's older tool output is trimmed; the newest stay whole", len(tool_msgs[0]["content"]) < 1000
      and all(len(m["content"]) == 5000 for m in tool_msgs[-agent.KEEP_RECENT:]))

# ---------------------------------------------------------------- steering through the app, and follow-ups
user = db.add_message("theta", "user", "plan my weekend")
run = runtime.begin("theta", user["id"])
m = runtime.steer("theta", "and keep Sunday free", None)
check("while a turn runs, a message is stored and handed to it", m and m["meta"]["steered"] and run.take() == ["and keep Sunday free"])
m2 = runtime.steer("theta", "oh and invite Ana", None)
done = threading.Event()
real = app._chat_worker
app._chat_worker = lambda bot, text, images, cid, emit, edit=None, **k: (FOLLOW.append((text, edit)), done.set())
FOLLOW = []
runtime.end("theta", run)
done.wait(3)
check("one sent after the last step gets its own follow-up turn", FOLLOW and FOLLOW[0][0] == "oh and invite Ana"
      and FOLLOW[0][1]["followup"])
app._chat_worker = real
check("with nothing running, steer says to send it normally", runtime.steer("theta", "hi", None) is None)


def call(method, path, body):
    data = json.dumps(body).encode()
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_LENGTH": str(len(data)),
           "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(data), "HTTP_X_PROTOS_KEY": "k"}
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]))))
    return got["s"], json.loads(out)


s, j = call("POST", "/api/chat/steer", {"bot": "theta", "text": "hello"})
check("POST /api/chat/steer: 'later' when nothing runs", s == 200 and j["mode"] == "later")

# ---------------------------------------------------------------- checkpoint, and resuming after a restart
CALLS.clear()
u = db.add_message("theta", "user", "find me a lamp")
saved = [{"role": "system", "content": "x"}, {"role": "user", "content": "find me a lamp"},
         {"role": "assistant", "content": "", "tool_calls": [tc("web_search", {"query": "lamp"}, "s1")]},
         {"role": "tool", "tool_call_id": "s1", "name": "web_search", "content": "Arc lamp $89 at Lamp Shop"}]
runtime.checkpoint("theta", u["id"], R, saved, {"steps": 1})
check("each step is checkpointed", db.get_setting("run:theta")["steps"] == 1)
SCRIPT[:] = [{"text": "The Arc lamp is $89 at Lamp Shop."}]
db.set_setting("run:theta", dict(db.get_setting("run:theta"), t=time.time() - 120))
runtime.tick(time.time())
for _ in range(50):
    if any(x.get("meta", {}).get("resumed") for x in db.messages("theta", limit=5)):
        break
    time.sleep(0.1)
rep = [x for x in db.messages("theta", limit=5) if (x.get("meta") or {}).get("resumed")]
check("a turn cut off by a restart resumes from its last step (no repeat of the search)", rep and "$89" in rep[-1]["text"]
      and not any(t == "web_search" for c in CALLS for t in []) and "Arc lamp $89" in str(CALLS[0]["messages"]))
check("and the checkpoint is cleared", db.get_setting("run:theta") is None)
print("all runtime checks passed")
