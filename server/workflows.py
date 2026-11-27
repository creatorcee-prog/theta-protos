"""Saved workflows: recipes for things that worked, so Theta can do them the same way next time.

A workflow is {name, goal, steps: [{tool, args_template, note}], created, uses}, in its own `workflows` table.

    maybe_offer(turn_info) -> [{"label": "Save as a workflow", "value": "save workflow: <name>"}] or []
        turn_info: {"text": the user's words, "tools": [names in order] (agent info["tools"]),
                    "error": info.get("error"), "approvals": [...], "bot": "theta"}
        Offers when 2+ real tool steps ran, nothing failed, nothing is waiting for approval, the user wasn't
        pushing back, and the same tool sequence isn't saved already. At most once per OFFER_GAP seconds.
    save(name, goal, steps, bot) / list_all() / get(name) / delete(name) / recipe(wf)

What is recorded: agent.run reports tool *names* only (info["tools"], stored on the reply's meta.tools and the
turn log's `tools`); arguments aren't kept anywhere. So workflow_save takes the steps the model passes (with
args templates and notes, since it can see its own calls in the turn it saves from), and otherwise rebuilds
them from the last tool turn's meta.tools, with the user's message before it as the goal.

workflow_run doesn't replay anything: it returns the recipe as guidance for the model to follow now.
"""
import json
import re
import time

from . import db

MAX_WORKFLOWS = 50
MAX_STEPS = 12
OFFER_GAP = 600
# tools that are about workflows/routines themselves, or too trivial to make a recipe from
_META_TOOLS = {"workflow_save", "workflow_list", "workflow_run", "routine_list", "routine_create",
               "routine_delete", "routine_run_now", "plan_update", "memory_edit"}
_PUSHBACK = re.compile(r"^\s*(no\b|nope\b|wrong\b|stop\b|don'?t\b|that'?s not\b|not what\b|you didn'?t\b|"
                       r"why did you\b|undo\b|try again\b|that'?s wrong\b)|\b(didn'?t work|not right|you got it wrong|"
                       r"that was wrong|mistake)\b", re.I)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    bot     TEXT NOT NULL DEFAULT 'theta',
    name    TEXT NOT NULL UNIQUE,
    goal    TEXT NOT NULL,
    steps   TEXT NOT NULL,
    created REAL NOT NULL,
    uses    INTEGER NOT NULL DEFAULT 0,
    last_used REAL
);
"""
_ready = None


def _c():
    global _ready
    key = (getattr(db, "_path", None), getattr(db, "_gen", None))
    c = db._conn()
    if _ready != key:
        c.executescript(_SCHEMA)
        _ready = key
    return c


def _row(r):
    try:
        steps = json.loads(r["steps"] or "[]")
    except ValueError:
        steps = []
    return {"id": r["id"], "name": r["name"], "goal": r["goal"], "steps": steps, "created": r["created"],
            "uses": r["uses"], "last_used": r["last_used"], "bot": r["bot"]}


def clean_name(name):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s'&/-]", " ", str(name or ""))).strip()[:60]


_FILLER = re.compile(r"^(?:(?:please|pls|hey theta|theta|ok(?:ay)?|so|can you|could you|would you|will you|"
                     r"i need you to|i want you to|i'd like you to|go ahead and|help me)[,\s]+)+", re.I)
_TRAIL = {"the", "a", "an", "to", "at", "for", "of", "in", "on", "my", "me", "and", "or", "with", "from", "near", "by"}


def name_for(text):
    """A short name for the kind of job, from the user's words: 'Can you book me a showroom visit (pick Gift) at
    http://x, Sam Lee, Friday' -> 'Book a showroom visit'. The model may rename it when it saves (workflow_save)."""
    t = str(text or "").strip()
    t = re.sub(r"https?://\S+|www\.\S+|\S+@\S+|\([^)]*\)|\[[^\]]*\]|\d[\d:/.,-]*\s*(?:am|pm)?", " ", t, flags=re.I)
    t = _FILLER.sub("", t.strip())
    t = re.split(r"[,.;:!?\n]|\s+(?:and then|then|and)\s+|\s+(?:at|for|on|by|from)\s+", t, maxsplit=1)[0]
    words = clean_name(t).split()
    if len(words) > 2 and words[1].lower() in ("me", "us"):  # "Book me a visit" -> "Book a visit"
        words.pop(1)
    words = words[:6]
    while words and words[-1].lower() in _TRAIL:
        words.pop()
    name = " ".join(words) or "Workflow"
    return name[:1].upper() + name[1:]


def list_all(bot=None):
    if bot:
        rows = _c().execute("SELECT * FROM workflows WHERE bot = ? ORDER BY uses DESC, id DESC", (bot,)).fetchall()
    else:
        rows = _c().execute("SELECT * FROM workflows ORDER BY uses DESC, id DESC").fetchall()
    return [_row(r) for r in rows]


def get(name):
    s = str(name or "").strip()
    if s.isdigit():
        r = _c().execute("SELECT * FROM workflows WHERE id = ?", (int(s),)).fetchone()
        if r:
            return _row(r)
    r = _c().execute("SELECT * FROM workflows WHERE lower(name) = lower(?)", (clean_name(s),)).fetchone()
    if r:
        return _row(r)
    hits = [w for w in list_all() if s and s.lower() in w["name"].lower()]
    return hits[0] if len(hits) == 1 else None


def delete(name):
    w = get(name)
    if not w:
        return False
    return _c().execute("DELETE FROM workflows WHERE id = ?", (w["id"],)).rowcount > 0


def _clean_steps(steps):
    out = []
    for i, s in enumerate(steps or []):
        if isinstance(s, str):
            s = {"tool": s}
        if not isinstance(s, dict):
            raise ValueError(f"step {i + 1} must be an object like {{\"tool\": \"web_search\", \"note\": \"...\"}}")
        tool = re.sub(r"[^\w.-]", "", str(s.get("tool") or ""))[:60]
        if not tool:
            raise ValueError(f"step {i + 1} has no tool name")
        tmpl = s.get("args_template")
        if isinstance(tmpl, str):
            try:
                tmpl = json.loads(tmpl)
            except ValueError:
                tmpl = {"hint": tmpl[:300]}
        if not isinstance(tmpl, dict):
            tmpl = {}
        tmpl = json.loads(json.dumps(tmpl, ensure_ascii=False)[:600]) if len(json.dumps(tmpl)) <= 600 else \
            {"hint": json.dumps(tmpl, ensure_ascii=False)[:300]}
        out.append({"tool": tool, "args_template": tmpl, "note": re.sub(r"\s+", " ", str(s.get("note") or ""))[:240]})
    if len(out) > MAX_STEPS:
        raise ValueError(f"keep a workflow to {MAX_STEPS} steps or fewer")
    return out


def save(name, goal, steps, bot="theta", now=None):
    """Store (or replace, by name) a workflow; returns it. Raises ValueError saying how to fix the call."""
    now = time.time() if now is None else float(now)
    name = clean_name(name)
    if not name:
        raise ValueError("name is empty: give it a short name, e.g. 'Weekly grocery order'")
    steps = _clean_steps(steps)
    if not steps:
        raise ValueError("there are no steps to save: no tool turn was found to learn from")
    goal = re.sub(r"\s+", " ", str(goal or "")).strip()[:400] or name
    c = _c()
    old = c.execute("SELECT id, uses FROM workflows WHERE lower(name) = lower(?)", (name,)).fetchone()
    if old:
        c.execute("UPDATE workflows SET goal = ?, steps = ?, bot = ? WHERE id = ?",
                  (goal, json.dumps(steps, ensure_ascii=False), bot, old["id"]))
    else:
        if c.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] >= MAX_WORKFLOWS:
            raise ValueError(f"there are already {MAX_WORKFLOWS} saved workflows; delete one first")
        c.execute("INSERT INTO workflows (bot, name, goal, steps, created) VALUES (?, ?, ?, ?, ?)",
                  (bot, name, goal, json.dumps(steps, ensure_ascii=False), now))
    return get(name)


def last_tool_turn(bot="theta", limit=40):
    """(goal, [tool names]) from the newest assistant reply that used real tools, with the user's message
    before it as the goal; (None, []) if there is none."""
    msgs = db.messages(bot, limit=limit)
    for i in range(len(msgs) - 1, -1, -1):
        m = msgs[i]
        names = [t for t in ((m.get("meta") or {}).get("tools") or []) if t not in _META_TOOLS]
        if m.get("role") != "assistant" or not names:
            continue
        goal = next((p.get("text") for p in reversed(msgs[:i]) if p.get("role") == "user"
                     and not re.match(r"^\s*save (that|this|it|workflow)", p.get("text") or "", re.I)), None)
        return goal, names
    return None, []


def recipe(w):
    lines = [f"Saved workflow “{w['name']}”. Goal: {w['goal']}", "Steps that worked last time:"]
    for i, s in enumerate(w["steps"], 1):
        tmpl = json.dumps(s.get("args_template") or {}, ensure_ascii=False)
        lines.append(f"{i}. {s['tool']}" + (f" with args like {tmpl}" if tmpl != "{}" else "") +
                     (f": {s['note']}" if s.get("note") else ""))
    lines.append("Follow this as a guide, not a script: fill in today's details, skip steps that don't apply, "
                 "and anything that sends still needs the user's approval.")
    return "\n".join(lines)


def _signature(names):
    return [n for n in names if n not in _META_TOOLS]


def maybe_offer(turn_info):
    """The "Save as a workflow" chip for a turn that went well, or []. Never raises."""
    try:
        info = turn_info or {}
        names = _signature(list(info.get("tools") or []))
        if len(names) < 2 or info.get("error") or info.get("approvals") or info.get("partial"):
            return []
        if any(t in ("workflow_run", "workflow_save") for t in info.get("tools") or []):
            return []
        text = str(info.get("text") or "")
        if _PUSHBACK.search(text):
            return []
        for w in list_all():
            if [s["tool"] for s in w["steps"]] == names:
                return []
        now = float(info.get("now") or time.time())
        last = db.get_setting("workflow_offer_t") or 0
        if now - float(last) < OFFER_GAP:
            return []
        db.set_setting("workflow_offer_t", now)
        name = name_for(text)
        return [{"label": "Save as a workflow", "value": f"save workflow: {name}"}]
    except Exception:  # noqa: BLE001  an offer is a nicety; it never breaks a turn
        return []


def context(bot, now):
    ws = list_all()[:10]
    if not ws:
        return ""
    return "Saved workflows (workflow_run gives the recipe): " + ", ".join(w["name"] for w in ws) + "."


# ---------------------------------------------------------------- tools

def _err(msg):
    from . import tools
    return tools.ToolError(msg)


def _t_save(args, ctx):
    bot = (ctx or {}).get("bot") or "theta"
    steps = args.get("steps")
    goal = args.get("goal")
    if not steps:
        g, names = last_tool_turn(bot)
        if not names:
            raise _err("no recent tool turn to save. Pass steps=[{tool, args_template, note}] yourself, "
                       "or do the task first and then save it")
        steps = [{"tool": n} for n in names]
        goal = goal or g
    try:
        w = save(args["name"], goal, steps, bot=bot)
    except ValueError as e:
        raise _err(str(e)) from None
    return (f"Saved workflow “{w['name']}” ({len(w['steps'])} steps: "
            f"{', '.join(s['tool'] for s in w['steps'])}). Goal: {w['goal']}. "
            "Next time, workflow_run gives you the recipe.")


def _t_list(args, ctx):
    ws = list_all()
    if not ws:
        return "No saved workflows yet."
    return "\n".join(f"- {w['name']} ({len(w['steps'])} steps, used {w['uses']}x): {w['goal'][:120]}" for w in ws)


def _t_run(args, ctx):
    w = get(args["name"])
    if not w:
        names = ", ".join(x["name"] for x in list_all()[:10]) or "none saved"
        raise _err(f"no workflow named {args['name']!r}. Saved: {names}")
    _c().execute("UPDATE workflows SET uses = uses + 1, last_used = ? WHERE id = ?", (time.time(), w["id"]))
    return recipe(w)


TOOLS = [
    {"name": "workflow_save", "risk": "write", "run": _t_save,
     "description": ("Save how you just did something as a reusable workflow (a recipe of tool steps). Use it "
                     "when the user says 'save that', 'remember how you did that', or taps 'save workflow: "
                     "<name>'. Pass name (a short name for the kind of job, like \"Book a showroom visit\"; if the "
                     "tapped name reads like one request's details, shorten it that way); pass goal and "
                     "steps=[{tool, args_template, note}] when you can see "
                     "the calls you made (use placeholders like {\"query\": \"<city> weather\"} for parts that "
                     "change). Without steps, the last tool turn's steps are used. Example: "
                     "{\"name\": \"Weekend weather check\"}."),
     "params": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Short name, e.g. 'Weekend weather check'."},
         "goal": {"type": "string", "description": "What it achieves, in a sentence."},
         "steps": {"type": "array", "description": "The tool steps in order.", "items": {
             "type": "object", "properties": {
                 "tool": {"type": "string"},
                 "args_template": {"type": "object", "description": "Arguments, with <placeholders> for what changes."},
                 "note": {"type": "string", "description": "Why this step / what to look for."}},
             "required": ["tool"]}}},
         "required": ["name"]}},
    {"name": "workflow_list", "risk": "read", "run": _t_list,
     "description": "List the saved workflows: name, steps, how often used, goal. Example: {}.",
     "params": {"type": "object", "properties": {}}},
    {"name": "workflow_run", "risk": "write", "run": _t_run,
     "description": ("Get a saved workflow's recipe to follow now (it doesn't replay anything by itself: you "
                     "then make the calls, adapted to today). Use it when the user asks for something a saved "
                     "workflow covers. Example: {\"name\": \"Weekend weather check\"}."),
     "params": {"type": "object", "properties": {
         "name": {"type": "string", "description": "The workflow's name."}}, "required": ["name"]}},
]

RELEVANT = (r"\bsave (that|this|it)\b|\bsave workflow\b|\bworkflows?\b|\bremember how (you|to)\b|"
            r"\bdo (it|that) (the same way|again like)\b")


def api(req, start):
    from . import app
    if req.method == "GET":
        return app.respond_json(start, {"workflows": list_all()})
    if req.method == "DELETE":
        body = req.json()
        ref = body.get("id") or body.get("name") or req.query.get("id") or req.query.get("name")
        if not ref or not delete(str(ref)):
            raise app.HTTPError(404, "no such workflow")
        return app.respond_json(start, {"ok": True})
    raise app.HTTPError(405, "method not allowed")


ROUTES = {"/api/workflows": api}
