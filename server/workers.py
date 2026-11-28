"""Workers: background jobs that an agent (Theta or one the user made, server/agents.py) starts, and messages one
agent sends another by address. After OpenRig's seats (github.com/mvschwarz/openrig): every agent has a stable
address like an email, `job-hunter@home`, and each job it starts runs as a worker at its own address,
`w3.job-hunter@home`, that the user can watch, stop, and read the result of.

    start_job {title, goal}        a worker takes the job off the agent's hands and runs it in the background
    agent_send {to, message}       hands a job to another agent by address; its answer comes back to both chats
    jobs {stop?}                   what's running and what finished (and stops one)

Every worker runs on DeepSeek, and all of them share one budget: setting "subagent_daily_usd" (default 0.05, five
cents a day), the same pool the research helpers draw on (server/subagents.py). A worker stops before any step
that could take the day's total past it; what it found so far is still posted. The day is the user's local day.

A worker is an unattended turn, like a routine: its agent's apps only, and anything that sends, buys or deletes
waits as an approval card, never runs on its own. Jobs live in the setting "worker_jobs" (last 40); a restart
marks a running one as stopped.
"""
import re
import threading
import time
import traceback

from . import agents, db

RIG = "home"
KEEP = 40
MAX_RUNNING = 3
STEP_EST_USD = 0.0015   # what one DeepSeek step of a worker costs at most, about (a 4k-token prompt and a short reply)
MAX_STEPS = 10

_lock = threading.Lock()
_live = {}      # job id -> {"cost": usd so far, "stop": bool}


def log(*a):
    try:
        from .app import log as _l
        _l("workers: " + " ".join(str(x) for x in a))
    except Exception:  # noqa: BLE001
        pass


def _err(msg):
    from . import tools
    return tools.ToolError(msg)


# ---------------------------------------------------------------- addresses
def address(agent_id):
    return f"{agent_id}@{RIG}"


def resolve(addr):
    """'job-hunter@home', 'job-hunter', or 'Job hunter' -> the agent, or None."""
    a = str(addr or "").strip().lower()
    a = a[:-len("@" + RIG)] if a.endswith("@" + RIG) else a
    a = a.split(".", 1)[1] if re.match(r"^w\d+\.", a) else a  # a worker's address reaches its agent
    for ag in agents.all_agents():
        if a in (ag["id"], ag["name"].lower()):
            return ag
    return None


def directory(bot):
    """Who else is on the team, for the system prompt: name, address, what it's for."""
    rows = [a for a in agents.all_agents() if a["id"] != bot]
    if not rows:
        return ""
    lines = [f"- {a['name']}: {address(a['id'])}" + (f" ({a.get('about')})" if a.get("about") else "") for a in rows]
    return (f"Your address is {address(bot)}. The others on the user's team (hand one a job with agent_send when "
            "it's theirs; its answer comes back to you):\n" + "\n".join(lines))


# ---------------------------------------------------------------- the budget (shared with the research helpers)
def cap():
    from . import subagents
    return subagents.daily_cap()


def spent(now=None):
    from . import subagents
    return subagents.spent_today(now) + sum(v["cost"] for v in _live.values())


def left(now=None):
    return max(0.0, cap() - spent(now))


def _route():
    """DeepSeek, always: the workers' one model."""
    from . import models, router
    if "deepseek" not in models.available():
        raise _err("workers run on DeepSeek, and this server has no DeepSeek key; do the job yourself in this reply")
    m = models.default_model("deepseek")
    return router.Route("quick", m, "deepseek", "worker", (("deepseek", m),), time.time())


# ---------------------------------------------------------------- jobs
def _jobs():
    v = db.get_setting("worker_jobs")
    return v if isinstance(v, list) else []


def _save(job):
    with _lock:
        js = [j for j in _jobs() if j.get("id") != job["id"]] + [job]
        db.set_setting("worker_jobs", js[-KEEP:])


def all_jobs(bot=None):
    js = _jobs()
    return [dict(j, cost=round(_live[j["id"]]["cost"], 6) if j["id"] in _live else j.get("cost", 0)) for j in js
            if bot is None or j.get("agent") == bot]


def _next_n(agent_id):
    return 1 + sum(1 for j in _jobs() if j.get("agent") == agent_id)


_NOTE = ("[Background job, worker {addr}. Nobody is watching this run and nobody can answer questions.] "
         "{origin}The job: {goal}\n\nDo it with your tools, as fully as a few steps allow. Then write the result "
         "for the user: what you found or did, with links, and anything that needs their decision, plainly at the "
         "end. Don't ask questions. Anything that sends, buys or deletes waits for their tap, so set it up and say so.")


def start(agent_id, title, goal, origin=None, reply_to=None, now=None):
    """Start a worker for this agent; returns the job (running in a thread)."""
    now = time.time() if now is None else now
    ag = agents.get(agent_id)
    if not ag:
        raise _err("no such agent")
    goal = str(goal or "").strip()[:1500]
    if not goal:
        raise _err("say what the job is in `goal`")
    if sum(1 for j in _jobs() if j.get("state") == "running") >= MAX_RUNNING:
        raise _err(f"{MAX_RUNNING} workers are already running; wait for one, or do this in your reply")
    if left(now) < STEP_EST_USD * 2:
        raise _err(f"today's worker budget (${cap():.2f} for all workers) is used up; do it in your reply, or "
                   "tell the user it can run tomorrow")
    route = _route()
    n = _next_n(agent_id)
    job = {"id": f"j{int(now * 1000) % 10**10}{n}", "agent": agent_id, "address": f"w{n}.{address(agent_id)}",
           "title": re.sub(r"\s+", " ", str(title or goal))[:80], "goal": goal, "state": "running",
           "started": int(now), "ended": None, "cost": 0.0, "steps": 0, "message": None,
           "from": origin, "reply_to": reply_to, "model": route.model}
    _live[job["id"]] = {"cost": 0.0, "stop": False}
    _save(job)
    threading.Thread(target=_run, args=(job, route), daemon=True, name="worker-" + job["id"]).start()
    return job


def _run(job, route):
    from . import agent, models, persona, subagents, tools
    jid, bot, live = job["id"], job["agent"], _live[job["id"]]
    info = {}
    origin = f"{job['from']} handed you this. " if job.get("from") else ""

    def stopped():  # before every model call: the user's stop, or a step that could take the day past the cap
        if live["stop"]:
            info["why_stopped"] = "stopped"
            return True
        live["cost"] = models.cost(info.get("model") or route.model, info.get("usage") or {}, "deepseek")
        last = live["cost"] / max(1, info.get("steps") or 1)
        if spent() + max(STEP_EST_USD, last * 1.3) > cap():
            info["why_stopped"] = "budget"
            return True
        return False

    out, state = "", "done"
    try:
        msgs = persona.build([], _NOTE.format(addr=job["address"], origin=origin, goal=job["goal"]), bot=bot,
                             context=tools.context_block(bot, time.time()))
        out = agent.run(route, msgs, lambda ev, data: None, info=info,
                        ctx={"bot": bot, "worker": jid, "stopped": stopped}, max_steps=MAX_STEPS) or ""
    except models.ModelError as e:
        state, out = "failed", ""
        info["error"] = str(e)[:200]
    except Exception:  # noqa: BLE001
        log(f"job {jid} crashed:\n" + traceback.format_exc())
        state = "failed"
    cost = models.cost(info.get("model") or route.model, info.get("usage") or {}, "deepseek")
    with _lock:
        _live.pop(jid, None)
    subagents._spend(cost, time.time())
    why = info.get("why_stopped")
    if why:
        state = "stopped"
    out = out.strip()
    note = {"budget": f"(Stopped: the ${cap():.2f} a day all workers share ran out.)",
            "stopped": "(Stopped, as you asked.)"}.get(why, "")
    if not out:
        out = {"failed": "That job didn't finish: the model didn't answer.", "stopped": "Nothing to report yet."}.get(state, "Done.")
    text = (out + ("\n\n" + note if note else "")).strip()
    meta = {"proactive": True, "source": "worker", "job": jid, "worker": job["address"], "job_title": job["title"],
            "model": info.get("model") or route.model, "provider": "deepseek", "tier": "worker",
            "steps": info.get("steps") or 0}
    approvals = info.get("approvals") or []
    if approvals:
        from .app import approval_cards
        meta["approvals"] = [a["id"] for a in approvals]
        meta["cards"] = approval_cards(approvals)
    if info.get("sources"):
        meta["sources"] = info["sources"]
    u = info.get("usage") or {}
    if u.get("tokens_in") or u.get("tokens_out"):
        meta["usage"] = {"in": int(u.get("tokens_in") or 0), "out": int(u.get("tokens_out") or 0),
                         "cached": int(u.get("cache_read") or 0), "model": meta["model"], "cost_usd": round(cost, 6)}
    msg = db.add_message(bot, "assistant", text, meta)
    if job.get("reply_to") and job["reply_to"] != bot:  # a job one agent handed another: the answer goes back too
        name = (agents.get(bot) or {}).get("name", bot)
        db.add_message(job["reply_to"], "assistant", f"**{name}** ({address(bot)}) answered:\n\n{text}",
                       {"proactive": True, "source": "worker", "job": jid, "worker": job["address"]})
    job.update(state=state, ended=int(time.time()), cost=round(cost, 6), steps=info.get("steps") or 0, message=msg["id"])
    _save(job)
    try:
        from . import push
        push.notify((agents.get(bot) or {}).get("name", "Theta"), f"{job['title']}: {text}"[:240], f"/?m={msg['id']}")
    except Exception:  # noqa: BLE001
        pass


def stop(jid):
    if jid in _live:
        _live[jid]["stop"] = True
        return True
    return False


def recover():
    """At start: a job marked running belongs to a process that's gone."""
    js = _jobs()
    if any(j.get("state") == "running" and j["id"] not in _live for j in js):
        for j in js:
            if j.get("state") == "running" and j["id"] not in _live:
                j.update(state="stopped", ended=int(time.time()), note="stopped by a restart")
        db.set_setting("worker_jobs", js)


# ---------------------------------------------------------------- tools
def _bot(ctx):
    return (ctx or {}).get("bot") or "theta"


def _t_start(args, ctx):
    if (ctx or {}).get("worker"):
        raise _err("a worker can't start more workers; do the rest yourself")
    j = start(_bot(ctx), args.get("title"), args.get("goal"))
    return (f"Started worker {j['address']} on \"{j['title']}\". It runs in the background (on DeepSeek, within "
            f"the ${cap():.2f} a day all workers share; ${left():.3f} left today) and posts its result in this chat. "
            "Tell the user it's running; don't wait for it.")


def _t_send(args, ctx):
    if (ctx or {}).get("worker"):
        raise _err("a worker can't hand jobs to other agents")
    me = _bot(ctx)
    to = resolve(args.get("to"))
    if not to:
        names = ", ".join(address(a["id"]) for a in agents.all_agents())
        raise _err(f"no agent at {args.get('to')!r}; the team: {names}")
    if to["id"] == me:
        raise _err("that's you; do it yourself")
    msg = str(args.get("message") or "").strip()
    me_name = (agents.get(me) or {}).get("name", me)
    db.add_message(to["id"], "assistant", f"From **{me_name}** ({address(me)}): {msg}",
                   {"proactive": True, "source": "agent_send", "from": address(me)})
    j = start(to["id"], args.get("title") or msg, msg, origin=f"{me_name} ({address(me)})", reply_to=me)
    return (f"Handed to {to['name']} ({address(to['id'])}); its worker {j['address']} is on it and the answer "
            "will come back to this chat. Tell the user who has it; don't wait.")


def _t_jobs(args, ctx):
    if args.get("stop"):
        j = next((x for x in _jobs() if x["id"] == args["stop"] or x["address"] == args["stop"]), None)
        if not j or not stop(j["id"]):
            raise _err("that job isn't running")
        return f"Stopping {j['address']}; what it has so far will be posted."
    rows = all_jobs()[-10:]
    if not rows:
        return "No jobs yet."
    return "\n".join(f"- {j['address']} \"{j['title']}\": {j['state']}" for j in reversed(rows)) + \
        f"\nWorker budget today: ${spent():.3f} of ${cap():.2f} used."


TOOLS = [
    {"name": "start_job", "risk": "write", "run": _t_start, "timeout": 10,
     "description": ("Hand a long job to a background worker so the user isn't kept waiting: research across many "
                     "sources, going through a lot of email, comparing many options, a multi-step task in the browser. "
                     "It runs on its own with your apps and posts the result in this chat. For anything a reply can "
                     "do in a step or two, just do it. Example: {\"title\": \"Compare 5 standing desks\", \"goal\": "
                     "\"Find 5 well-reviewed standing desks under $500, with price, size and links\"}."),
     "params": {"type": "object", "properties": {
         "title": {"type": "string", "description": "A few words the user sees, e.g. 'Compare standing desks'."},
         "goal": {"type": "string", "description": "The whole job, with every detail the worker needs."}},
         "required": ["title", "goal"]}},
    {"name": "agent_send", "risk": "write", "run": _t_send, "timeout": 10,
     "description": ("Hand a job or a question to another agent on the user's team by its address (like an email "
                     "address, e.g. job-hunter@home; your instructions list the team). It works on it in the "
                     "background and its answer comes back to this chat. Use it when the job is clearly theirs."),
     "params": {"type": "object", "properties": {
         "to": {"type": "string", "description": "The agent's address, e.g. money@home."},
         "message": {"type": "string", "description": "What you need, with every detail."},
         "title": {"type": "string", "description": "A few words for the job list (optional)."}},
         "required": ["to", "message"]}},
    {"name": "jobs", "risk": "read", "run": _t_jobs,
     "description": "List background jobs (running and finished) and the day's worker budget; {\"stop\": id} stops one.",
     "params": {"type": "object", "properties": {"stop": {"type": "string", "description": "A job id or worker address to stop."}}}},
]

RELEVANT = r"\bin the background\b|\bworker\b|\bjobs?\b|@home\b|\bhand (it|this) to\b|\bask (my|the) \w+ agent\b"


def context(bot, now):
    run = [j for j in _jobs() if j.get("state") == "running"]
    return f"Background jobs running: {len(run)}." if run else ""


def _route_api(req, start_resp):
    from .app import HTTPError, respond_json
    p, m = req.path, req.method
    if p == "/api/workers" and m == "GET":
        return respond_json(start_resp, {"jobs": list(reversed(all_jobs())), "spent_usd": round(spent(), 6), "cap_usd": cap(),
                                         "left_usd": round(left(), 6), "rig": RIG,
                                         "addresses": {a["id"]: address(a["id"]) for a in agents.all_agents()}})
    if p.startswith("/api/workers/") and p.endswith("/stop") and m == "POST":
        jid = p[len("/api/workers/"):-len("/stop")]
        if not stop(jid):
            raise HTTPError(409, "that job isn't running")
        return respond_json(start_resp, {"ok": True})
    raise HTTPError(405 if p == "/api/workers" else 404, "not found")


ROUTES = {"/api/workers": _route_api, "/api/workers/": _route_api}

recover()
