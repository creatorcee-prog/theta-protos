"""Activity events (docs/STAGE5.md, Builder B): the tool -> plain-words mapping, no secrets or bodies in the text,
activity start/done events from the agent loop, and meta.timing / meta.activity on the plain path, the tool path
and edits. No network: models.call / models.stream are fakes. Run: python3 tests/test_activity.py"""
import json
import os
import sys
import tempfile
import threading
import http.client

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="protos-activity-")
os.environ.update(PROTOS_DATA=TMP, PROTOS_WEB=os.path.join(TMP, "web-empty"), PROTOS_TICK="0", PROTOS_QUIET="1",
                  PROTOS_COMPACT="0", DEEPSEEK_API_KEY="sk-test")
for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "LOCAL_LLM_URL", "TAVILY_API_KEY", "PROTOS_KEY",
          "PROTOS_LOCAL_FIRST", "VANTAGE_URL", "VANTAGE_DIR"):
    os.environ.pop(k, None)

from server import agent, app as appmod, db, models, router, tools  # noqa: E402

router.CLASSIFIER = None
FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail!r}"[:600]))
    if not cond:
        FAILED.append(name)


db.init()

# ---------------------------------------------------------------- the mapping
D = agent.describe
cases = [
    (("web_search", {"query": "denver weather"}), ("Searching the web for denver weather", "search")),
    (("gmail_search", {"query": "from:boss is:unread"}), ("Reading your inbox", "read")),
    (("gmail_read", {"message_id": "18c2f"}), ("Reading an email", "read")),
    (("browse_open", {"url": "https://example.com/account/reset?token=abc123"}), ("Opening example.com", "browse")),
    (("browse_open", {"url": "www.example.org"}), ("Opening example.org", "browse")),
    (("research", {"question": "q", "angles": ["a", "b", "c"]}), ("Waking 3 helpers", "helpers")),
    (("send_email_draft", {"to": "sam@example.com", "subject": "Hi", "body": "x"}), ("Drafting the email", "write")),
    (("generate_image", {"prompt": "a cat"}), ("Making the image", "image")),
    (("memory_edit", {"op": "add", "text": "Vegetarian"}), ("Saving that to memory", "write")),
    (("memory_edit", {"op": "remove", "old": "Vegetarian"}), ("Forgetting that", "write")),
    (("calendar_list", {}), ("Checking your calendar", "read")),
    (("remind_me", {"text": "stretch", "in_minutes": 2}), ("Setting the reminder", "write")),
    (("call_me", {}), ("Calling you", "call")),
    (("some_new_tool", {"x": 1}), ("Using some new tool", "read")),
    (("web_search", {}), ("Searching the web", "search")),
    (("browse_open", {"url": "javascript:alert(1)"}), ("Opening the page", "browse")),
]
for (name, args), want in cases:
    got = D(name, args)
    check(f"describe {name} {json.dumps(args)[:50]} -> {want[0]!r}", got == want, got)
check("every kind is from the contract", all(D(n, a)[1] in agent.KINDS for (n, a), _ in cases))
check("a broken args value falls back safely", D("research", {"angles": None})[0] == "Waking a helper"
      and D("web_search", "nonsense")[0] == "Searching the web")

# browser refs become the element's label (never typed text)
from server import browser  # noqa: E402


class _S:
    els = {"e3": {"ref": "e3", "label": "Learn more"}, "e4": {"ref": "e4", "label": "Email"}}
    url = "https://example.com/"


browser._engine.sessions["theta"] = _S()
check("browse_act click names the link", D("browse_act", {"actions": [{"do": "click", "ref": "e3"}]},
                                            {"bot": "theta"}) == ("Clicking Learn more", "browse"))
typed = D("browse_act", {"actions": [{"do": "type", "ref": "e4", "text": "hunter2-secret"}]}, {"bot": "theta"})
check("browse_act type names the field, not the text", typed[0] == "Typing into Email" and "hunter2" not in typed[0],
      typed)
check("browse_act unknown ref still honest", D("browse_act", {"actions": [{"do": "click", "ref": "e99"}]},
                                                 {"bot": "theta"})[0] == "Clicking on the page")
browser._engine.sessions.pop("theta", None)

# ---------------------------------------------------------------- no secrets in the text
SECRETS = ["sk-live-abcdef1234567890", "ghp_ABCDEFGHIJKLMNOPqrstuvwx", "4111 1111 1111 1111", "hunter2",
           "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "SUPERSECRETBODY"]
q = "weather sk-live-abcdef1234567890 token=hunter2 4111 1111 1111 1111 eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
txt = D("web_search", {"query": q})[0]
check("search text drops keys, tokens, card numbers", not any(s in txt for s in SECRETS) and txt.startswith(
    "Searching the web for weather"), txt)
mail = D("send_email_draft", {"to": "a@b.c", "subject": "x", "body": "SUPERSECRETBODY " * 20})[0]
draft = D("gmail_draft", {"to": "a@b.c", "subject": "x", "body": "SUPERSECRETBODY"})[0]
check("email bodies never appear", "SUPERSECRET" not in mail + draft, (mail, draft))
check("activity text is short and one line", len(D("web_search", {"query": "word " * 100})[0]) < 80
      and "\n" not in D("web_search", {"query": "a\nb\nc"})[0])
check("markup characters are dropped", "<" not in D("web_search", {"query": "<script>x</script> [link](y)"})[0])

# ---------------------------------------------------------------- the agent loop emits activity
SCRIPT = []


def fake_call(provider, model, messages, specs, max_tokens, on_text=None, tool_choice="auto", timeout=None, **kw):
    step = SCRIPT.pop(0) if SCRIPT else {"text": "ok"}
    if step.get("text") and on_text:
        on_text(step["text"])
    return {"text": step.get("text") or "", "tool_calls": step.get("tool_calls") or [],
            "usage": {"tokens_in": 10, "tokens_out": 2}}


models.call = fake_call


def route(tier="quick"):
    return router.Route(tier=tier, model="deepseek-chat", provider="deepseek", why="test",
                        candidates=(("deepseek", "deepseek-chat"),))


ev = []
SCRIPT[:] = [{"tool_calls": [{"id": "c1", "name": "remind_me", "args": {"text": "stretch", "in_minutes": 2}},
                             {"id": "c2", "name": "send_email_draft",
                              "args": {"to": "sam@example.com", "subject": "Hi", "body": "SUPERSECRETBODY"}}]},
             {"text": "Done, and the email is waiting for your OK."}]
info = {}
agent.run(route(), [{"role": "system", "content": "S"}, {"role": "user", "content": "x"}],
          lambda e, d: ev.append((e, d)), info=info, ctx={"bot": "theta"})
acts = [d for e, d in ev if e == "activity"]
check("agent: start then done for each call, keyed by the call id",
      [(a["id"], a["state"]) for a in acts] == [("c1", "start"), ("c2", "start"), ("c2", "done"), ("c1", "done")],
      acts)
check("agent: activity texts + kinds", acts[0]["text"] == "Setting the reminder" and acts[1]["text"] ==
      "Drafting the email" and acts[0]["kind"] == "write" and all(isinstance(a["t"], int) for a in acts), acts)
check("agent: activity comes before the tool runs", [e for e, _ in ev].index("activity") <
      [e for e, _ in ev].index("tool"))
check("agent: info['activity'] lists the texts", info["activity"] == ["Setting the reminder", "Drafting the email"])
check("agent: no body in any event", "SUPERSECRET" not in json.dumps([d for e, d in ev if e == "activity"]))

# a tool can report its own sub-steps through ctx["activity"]
got_ctx = {}


def probe(args, ctx):
    rep = ctx.get("activity")
    got_ctx["ok"] = callable(rep)
    i = rep("Helper 1 is checking prices token=hunter2", "helpers")
    rep("Helper 1 is checking prices", "helpers", state="done", id=i)
    return "fine"


tools.TOOLS.append({"name": "probe_tool", "risk": "read", "run": probe, "description": "test",
                    "params": {"type": "object", "properties": {}}})
tools.BY_NAME["probe_tool"] = tools.TOOLS[-1]
ev.clear()
SCRIPT[:] = [{"tool_calls": [{"id": "p1", "name": "probe_tool", "args": {}}]}, {"text": "ok"}]
agent.run(route(), [{"role": "user", "content": "x"}], lambda e, d: ev.append((e, d)), info={}, ctx={"bot": "theta"})
texts = [(d["text"], d["state"]) for e, d in ev if e == "activity"]
check("ctx['activity'] lets a tool report (sanitized)", got_ctx.get("ok") and ("Using probe tool", "start") in texts
      and any(t.startswith("Helper 1 is checking prices") and "hunter2" not in t for t, _ in texts), texts)
tools.TOOLS.pop()
tools.BY_NAME.pop("probe_tool", None)

# ---------------------------------------------------------------- the app: timing on every path
STREAM = {"chunks": ["Hey. ", "What's up?"]}


def fake_stream(provider, model, messages, max_tokens=1024, usage=None):
    for c in STREAM["chunks"]:
        yield c


models.stream = fake_stream


def turn(text, edit=None):
    out = []
    appmod._chat_worker("theta", text, [], None, lambda e, d: out.append((e, d)), edit=edit)
    return out


# the plain path: keep other features' RELEVANT words (weather, compare...) from sending these down the tool path
real_relevant = tools.relevant
tools.relevant = lambda text: False
evs = turn("hey there")
done = evs[-1][1]
names = [e for e, _ in evs]
tm = done["meta"].get("timing") or {}
check("plain: no activity for quick chat (nothing to report)", "activity" not in names, names)
check("plain: meta.timing {total_ms, first_ms}", evs[-1][0] == "done" and isinstance(tm.get("total_ms"), int)
      and isinstance(tm.get("first_ms"), int) and 0 <= tm["first_ms"] <= tm["total_ms"], done["meta"])
check("plain: timing is stored with the message", (db.get_message(done["id"])["meta"].get("timing") or {}).get(
    "total_ms") == tm["total_ms"])

evs = turn("why should I compare these two plans step by step")
acts = [d for e, d in evs if e == "activity"]
done = evs[-1][1]
check("think tier: 'Thinking it through' start, then done when text arrives",
      [(a["text"], a["state"], a["kind"]) for a in acts] == [("Thinking it through", "start", "think"),
                                                              ("Thinking it through", "done", "think")]
      and [e for e, _ in evs].index("activity") < [e for e, _ in evs].index("delta"), acts)
check("think tier: meta.activity", done["meta"].get("activity") == ["Thinking it through"]
      and done["meta"]["timing"]["first_ms"] is not None, done["meta"])

# search tier with a live key: says it's searching only because it really does
os.environ["TAVILY_API_KEY"] = "tv-test"
real_sc = router.search_context
router.search_context = lambda text, **kw: ("results block", [{"title": "Weather", "url": "https://w.example/"}])
try:
    evs = turn("what's the weather in denver today")
finally:
    router.search_context = real_sc
    os.environ.pop("TAVILY_API_KEY", None)
acts = [d for e, d in evs if e == "activity"]
check("search tier: routed as search", evs[1][1].get("tier") == "search", evs[1][1])
check("search tier: 'Searching the web for ...' with done ok",
      acts and acts[0]["text"].startswith("Searching the web for") and acts[-1]["state"] == "done"
      and acts[-1]["ok"] is True and evs[-1][1]["meta"]["activity"][0].startswith("Searching the web"), acts)

tools.relevant = real_relevant

# tool path
SCRIPT[:] = [{"tool_calls": [{"id": "r1", "name": "remind_me", "args": {"text": "stretch", "in_minutes": 2}}]},
             {"text": "Done. I'll ping you to stretch in 2 minutes."}]
evs = turn("remind me in 2 minutes to stretch")
done = evs[-1][1]
acts = [d for e, d in evs if e == "activity"]
check("tool path: activity events in the stream", [(a["text"], a["state"]) for a in acts] ==
      [("Setting the reminder", "start"), ("Setting the reminder", "done")], acts)
check("tool path: t restamped from the turn's start", all(isinstance(a["t"], int) and a["t"] >= 0 for a in acts))
check("tool path: meta.timing + meta.activity", done["meta"].get("activity") == ["Setting the reminder"]
      and isinstance(done["meta"]["timing"]["total_ms"], int) and done["meta"]["timing"]["first_ms"] is not None
      and "live" not in done["meta"], done["meta"])

# browser use marks meta.live
real_exec = tools.execute
tools.execute = lambda name, args, ctx=None: (True, "Page: Example Domain") if name == "browse_open" else real_exec(
    name, args, ctx)
SCRIPT[:] = [{"tool_calls": [{"id": "b1", "name": "browse_open", "args": {"url": "https://example.com"}}]},
             {"text": "It says Example Domain."}]
try:
    evs = turn("open example.com and tell me what it says")
finally:
    tools.execute = real_exec
done = evs[-1][1]
check("browser turn: 'Opening example.com' and meta.live", done["meta"].get("activity") == ["Opening example.com"]
      and done["meta"].get("live") is True, done["meta"])

# edits regenerate with timing too (through the real HTTP route)
httpd = appmod.make("127.0.0.1", 0)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
last = db.last_user_message("theta")
SCRIPT[:] = [{"tool_calls": [{"id": "r2", "name": "remind_me", "args": {"text": "drink water", "in_minutes": 5}}]},
             {"text": "Done. Water in 5."}]
c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
c.request("POST", "/api/messages/edit?stream=0", body=json.dumps({"id": last["id"], "text":
          "remind me in 5 minutes to drink water"}), headers={"Content-Type": "application/json"})
r = c.getresponse()
body = json.loads(r.read())
meta = (body.get("reply") or {}).get("meta") or {}
check("edit: the regenerated reply has meta.timing + meta.activity", r.status == 200 and meta.get("edited") is True
      and meta.get("activity") == ["Setting the reminder"] and isinstance(meta["timing"]["total_ms"], int), body)
httpd.shutdown()

print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all activity checks passed'}")
sys.exit(1 if FAILED else 0)
