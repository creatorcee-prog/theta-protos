"""Progress cards (server/progress.py): Theta lists a job's phases and marks them done as it goes; the app gets a
live "progress" event each time, and the reply keeps the card, where a phase it never finished shows as not done.
The model is faked."""
import io, json, os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp(), DEEPSEEK_API_KEY="sk-test")
from server import agent, app, db, ext, models, progress, router, tools


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


db.init()
ext.reset(); tools._ext_reset(); tools._ext()
router.CLASSIFIER = None
check("progress_update is a tool Theta always has", "progress_update" in tools.CORE and "progress_update" in tools.BY_NAME)
check("states: done, in progress, to come", [s["state"] for s in progress.states(["a", "b", "c"], 1)] == ["done", "active", "pending"])
check("at the end, unfinished phases are not done (never claimed)",
      [s["state"] for s in progress.states(["a", "b", "c"], 1, final=True)] == ["done", "skipped", "skipped"])

STEPS = ["Find the lamp at 4 stores", "Compare prices", "Check delivery"]
SCRIPT = [{"tool_calls": [{"id": "p0", "name": "progress_update", "args": {"steps": STEPS, "done": 0}}]},
          {"tool_calls": [{"id": "s1", "name": "history_search", "args": {"query": "lamp"}},
                          {"id": "p1", "name": "progress_update", "args": {"steps": STEPS, "done": 2}}]},
          {"text": "The Arc lamp is cheapest at Lamp Shop."}]


def fake_call(provider, model, messages, tools_=None, max_tokens=1024, on_text=None, tool_choice="auto", timeout=None):
    step = SCRIPT.pop(0) if SCRIPT else {"text": "Done."}
    if step.get("text") and on_text:
        on_text(step["text"])
    return {"text": step.get("text", ""), "tool_calls": step.get("tool_calls") or [], "reasoning": "",
            "usage": {"tokens_in": 10, "tokens_out": 2, "cache_read": 0, "cache_write": 0}}


models.call = fake_call
env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/chat", "QUERY_STRING": "", "CONTENT_TYPE": "application/json",
       "HTTP_X_PROTOS_KEY": "k", "HTTP_ACCEPT": "text/event-stream"}
body = json.dumps({"bot": "theta", "text": "find me the cheapest arc floor lamp and when it'd arrive"}).encode()
env.update(CONTENT_LENGTH=str(len(body)), **{"wsgi.input": io.BytesIO(body)})
raw = b"".join(app.app(env, lambda s, h: None)).decode()
evs = []
for block in raw.split("\n\n"):
    ev = next((l[7:] for l in block.split("\n") if l.startswith("event: ")), None)
    data = next((l[6:] for l in block.split("\n") if l.startswith("data: ")), None)
    if ev:
        evs.append((ev, json.loads(data) if data else None))
prog = [d for e, d in evs if e == "progress"]
check("each update streams a live progress event", len(prog) == 2
      and [s["state"] for s in prog[0]["steps"]] == ["active", "pending", "pending"]
      and [s["state"] for s in prog[1]["steps"]] == ["done", "done", "active"])
done = next(d for e, d in evs if e == "done")
check("the reply keeps the card; the phase it never marked done shows as not done",
      [s["state"] for s in done["meta"]["progress"]] == ["done", "done", "skipped"]
      and done["meta"]["progress"][0]["text"] == STEPS[0])
try:
    tools.BY_NAME["progress_update"]["run"]({"steps": ["one"]}, {})
    check("one phase isn't a progress card", False)
except tools.ToolError:
    check("one phase isn't a progress card", True)
print("all progress checks passed")
