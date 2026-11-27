"""Saved workflows (server/workflows.py): the "Save as a workflow" offer, workflow_save (from the model's steps or
from the last tool turn), workflow_list, workflow_run (a recipe, not a replay), context and /api/workflows.
No network. Run: python3 tests/test_workflows.py"""
import io
import json
import os
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_DATA=tempfile.mkdtemp(prefix="protos-wf-"))

from server import app, db, ext, tools, workflows  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILED.append(name)


ext.FEATURES = ("workflows",)
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


T = 1_800_000_000.0
good = {"text": "Find a vegetarian place near the office and put it in my plan", "tools": ["web_search", "web_search", "plan_update"],
        "now": T}
chips = workflows.maybe_offer(good)
check("offer: 2+ tool steps that went well -> one chip",
      chips == [{"label": "Save as a workflow", "value": "save workflow: Find a vegetarian place"}], chips)
check("names are for the kind of job, not this request's details",
      workflows.name_for("Can you book me a showroom visit (pick Gift) at http://x.test/b, Sam Lee, sam@x.com, Fri 1pm")
      == "Book a showroom visit" and workflows.name_for("please clean up my inbox") == "Clean up my inbox"
      and workflows.name_for("2+2") == "Workflow")
check("offer: not again within 10 minutes", workflows.maybe_offer(dict(good, now=T + 60)) == [])
check("offer: after the gap, yes", workflows.maybe_offer(dict(good, now=T + 700)) != [])
check("offer: a single tool step -> none", workflows.maybe_offer({"text": "x", "tools": ["web_search"], "now": T + 9999}) == [])
check("offer: an error -> none", workflows.maybe_offer(dict(good, error="boom", now=T + 9999)) == [])
check("offer: waiting for approval -> none", workflows.maybe_offer(dict(good, approvals=[{"id": 1}], now=T + 9999)) == [])
check("offer: the user pushed back -> none", all(workflows.maybe_offer(dict(good, text=t, now=T + 9999)) == [] for t in (
    "No, that's wrong, try again with Thai food", "that's not what I asked", "you didn't check the hours")))
check("offer: memory/plan tools don't count as steps",
      workflows.maybe_offer({"text": "remember this", "tools": ["memory_edit", "plan_update"], "now": T + 9999}) == [])
check("offer: never raises on junk", workflows.maybe_offer(None) == [] and workflows.maybe_offer({"tools": 5}) == [])

# the last tool turn, as app.py records it (meta.tools on the reply)
db.add_message("theta", "user", "What's the weather in Lisbon this weekend and what should I pack?")
db.add_message("theta", "assistant", "Sunny, 22°C. Pack light layers.", {"tools": ["web_search", "web_search", "plan_update"]})
db.add_message("theta", "user", "save workflow: Weekend trip weather")
ok, out = tools.execute("workflow_save", {"name": "Weekend trip weather"}, {"bot": "theta"})
w = workflows.get("weekend trip weather")
check("save without steps: rebuilt from the last tool turn", ok and w and [s["tool"] for s in w["steps"]] ==
      ["web_search", "web_search"] and "Lisbon" in w["goal"], (out, w))
check("offer: the same tool sequence already saved -> none",
      workflows.maybe_offer({"text": "weather in Rome", "tools": ["web_search", "web_search"], "now": T + 99999}) == [])
ok, out = tools.execute("workflow_save", {
    "name": "Dinner spot", "goal": "Pick a dinner place and book it",
    "steps": [{"tool": "web_search", "args_template": {"query": "<cuisine> restaurants near <area> open tonight"},
               "note": "prefer places with 4.5+ ratings"},
              {"tool": "send_email_draft", "args_template": {"to": "<restaurant email>"}, "note": "ask for a table"}]},
    {"bot": "theta"})
check("save with the model's steps (args templates + notes)", ok and workflows.get("Dinner spot")["steps"][0]["args_template"]
      == {"query": "<cuisine> restaurants near <area> open tonight"})
ok, out = tools.execute("workflow_save", {"name": "", "steps": [{"tool": "x"}]}, {"bot": "theta"})
check("save: empty name refused with a hint", not ok and "name" in out)
ok, out = tools.execute("workflow_save", {"name": "Bad", "steps": [{"note": "no tool"}]}, {"bot": "theta"})
check("save: a step with no tool refused", not ok and "no tool" in out, out)
ok, out = tools.execute("workflow_save", {"name": "Dinner spot", "goal": "Better goal", "steps": [{"tool": "web_search"}]},
                        {"bot": "theta"})
check("save: same name replaces", ok and workflows.get("Dinner spot")["goal"] == "Better goal"
      and len(workflows.list_all()) == 2)

ok, out = tools.execute("workflow_list", {}, {"bot": "theta"})
check("workflow_list", ok and "Weekend trip weather" in out and "Dinner spot" in out, out)
ok, out = tools.execute("workflow_run", {"name": "Weekend trip weather"}, {"bot": "theta"})
check("workflow_run: returns the recipe as guidance (no replay)", ok and "Steps that worked last time" in out
      and "1. web_search" in out and "guide, not a script" in out, out)
check("workflow_run: counts a use", workflows.get("Weekend trip weather")["uses"] == 1)
ok, out = tools.execute("workflow_run", {"name": "nope"}, {"bot": "theta"})
check("workflow_run: unknown name lists the saved ones", not ok and "Dinner spot" in out)
check("workflow_run is a write tool, workflow_list read", tools.BY_NAME["workflow_run"]["risk"] == "write"
      and tools.BY_NAME["workflow_list"]["risk"] == "read" and tools.BY_NAME["workflow_save"]["risk"] == "write")
ctx = workflows.context("theta", T)
check("context: names of saved workflows (up to 10)", "Weekend trip weather" in ctx and "Dinner spot" in ctx)
for i in range(12):
    workflows.save(f"Extra {i}", "g", [{"tool": "web_search"}])
check("context: at most 10 names", workflows.context("theta", T).count(",") == 9)
check("context reaches tool turns", "Saved workflows" in tools.context_block())
check("RELEVANT: 'save that' / 'remember how you did that' use tools",
      tools.relevant("save that") and tools.relevant("remember how you did that") and tools.relevant("save workflow: X"))

check("GET /api/workflows needs sign-in", call("/api/workflows", key=None)[0] == 401)
st, body = call("/api/workflows")
check("GET /api/workflows lists", st == 200 and len(body["workflows"]) == 14)
check("DELETE signed out -> 401", call("/api/workflows", "DELETE", {"name": "Dinner spot"}, key=None)[0] == 401)
check("DELETE by name", call("/api/workflows", "DELETE", {"name": "Dinner spot"})[0] == 200 and not workflows.get("Dinner spot"))
wid = workflows.get("Extra 1")["id"]
check("DELETE by id", call("/api/workflows", "DELETE", {"id": wid})[0] == 200 and not workflows.get("Extra 1"))
check("DELETE unknown -> 404", call("/api/workflows", "DELETE", {"name": "zzz"})[0] == 404)
check("POST -> 405", call("/api/workflows", "POST", {})[0] == 405)

if FAILED:
    print(f"{len(FAILED)} failed: {FAILED}")
    sys.exit(1)
print("all workflows tests passed")
