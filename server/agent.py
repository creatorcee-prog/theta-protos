"""One tool loop with hard limits (docs/HARNESS.md P2, P9, lesson 4).

    run(route, messages, emit, info=None, ctx=None, on_tool_start=None, ...) -> final text

- Each step calls models.call with the fixed tool list; text streams out through persona.Cleaner as
  emit("delta", {"text"}).
- No tool calls: that's the answer, stop. Otherwise read/write tools run (in parallel, 20 s each) and
  their results go back in, framed as data (tools.wrap), and the loop repeats.
- At most MAX_STEPS model calls and TURN_SECONDS per turn; at the cap one last call with tool_choice
  "none" answers with what it has.
- A "send" tool NEVER runs here: its call becomes db.add_approval({tool, args, ...}) and the model is told
  it is waiting for the user. Only POST /api/approve runs it (app.approve -> tools.run_approved).
- emit("tool", {"id", "name", "state": "running"|"done"|"waiting", "ok"}) for the phone's task cards.
- emit("activity", {"id", "text", "state": "start"|"done", "kind", "t"[, "ok"]}) in plain words for the status
  line ("Reading your inbox", "Opening example.com"): describe(name, args) maps each call to honest text, never
  with a secret or a message body in it. t is ms since run() started (app.py restamps it from the turn's start).
  Tools may report a sub-step themselves through ctx["activity"](text, kind="read", state="start", id=None).
- Provider fallback (route.candidates) only before any text reached the user and before any tool ran.

`info` (a dict) is filled with: provider, model, steps, tools (names in order), usage (summed),
cost_usd, approvals [{"id", "tool", "preview"}], sources, ttft (monotonic time of first text), emitted,
activity (the activity texts, in order: routines can store it as meta.activity).
"""

import re
import threading
import time
import urllib.parse

from . import db, models, persona, tools

MAX_STEPS = 6
TOOL_SECONDS = 20
TOOL_TIMEOUT_AWARE = True  # a tool with its own "timeout" gets that long (see _run_tools)
TURN_SECONDS = 90
MAX_TOKENS = 1200
MAX_SENDS = 2          # approval cards per turn (each is two buttons; the phone shows four)
APPROVAL_TTL = 24 * 3600

FINAL_NOTE = ("[harness] The tool budget for this message is used up. Don't call tools. Answer now with what "
              "you have, and say briefly what's missing.")


# ---------------------------------------------------------------- activity: what Theta is doing, in plain words

KINDS = ("think", "search", "read", "write", "browse", "helpers", "call", "image")

# things that look like secrets or private numbers: never shown in activity text
_SECRETISH = re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[abp]|AIza|ya29)[-_.A-Za-z0-9]{6,}|\b[A-Za-z0-9_\-+/=]{24,}"
                        r"|\b(?:\d[ -]?){9,}\d\b|(?i:\b(?:password|passwd|pwd|token|secret|api[_ -]?key)\b\s*[:=]?\s*\S+)")


def safe_words(text, cap=48):
    """A short, single-line, secret-free version of what the model asked for (a search query, a label)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = _SECRETISH.sub("…", t)
    t = re.sub(r"[<>`*_\[\]]", "", t)
    if len(t) > cap:
        t = t[:cap].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
    return t


def _host(url):
    u = str(url or "").strip()
    if re.match(r"^[a-z][a-z0-9+.-]*:(?!\d)", u, re.I) and not re.match(r"^https?://", u, re.I):
        return ""  # javascript:, file:, data: ... (browse_open refuses them anyway)
    if u and "://" not in u:
        u = "https://" + u
    try:
        h = (urllib.parse.urlsplit(u).hostname or "").lower()
    except ValueError:
        h = ""
    h = h[4:] if h.startswith("www.") else h
    return h if re.fullmatch(r"[a-z0-9.-]{1,80}", h or "") else ""


def _ref_label(ref, ctx):
    """The label of a browser element ref (browse_act/browse_submit args only carry "e7")."""
    try:
        from . import browser
        fn = getattr(browser, "ref_label", None)
        return safe_words(fn(ctx, ref), 36) if callable(fn) else ""
    except Exception:  # noqa: BLE001
        return ""


def _browse_act_text(args, ctx):
    acts = [a for a in (args.get("actions") or []) if isinstance(a, dict)]
    if not acts:
        return "Using the page"
    a = acts[0]
    do = str(a.get("do") or "").lower()
    label = _ref_label(a.get("ref"), ctx) if a.get("ref") else ""
    more = " and more" if len(acts) > 1 else ""
    if do == "click":
        return (f"Clicking {label}" if label else "Clicking on the page") + more
    if do == "type":  # never the typed text itself
        return (f"Typing into {label}" if label else "Typing on the page") + more
    if do == "select":
        return (f"Choosing {label}" if label else "Picking an option") + more
    if do == "scroll":
        return "Scrolling the page" + more
    if do == "back":
        return "Going back a page" + more
    return "Using the page"


_FIXED = {
    "gmail_search": ("Reading your inbox", "read"),
    "gmail_read": ("Reading an email", "read"),
    "gmail_draft": ("Drafting the email", "write"),
    "gmail_reply_draft": ("Drafting the reply", "write"),
    "send_email_draft": ("Drafting the email", "write"),
    "calendar_list": ("Checking your calendar", "read"),
    "calendar_add": ("Adding it to your calendar", "write"),
    "calendar_invite": ("Drafting the invite", "write"),
    "drive_search": ("Looking through your Drive", "read"),
    "drive_read": ("Reading a file from your Drive", "read"),
    "docs_create": ("Writing the doc", "write"),
    "slides_create": ("Making the slides", "write"),
    "generate_image": ("Making the image", "image"),
    "remind_me": ("Setting the reminder", "write"),
    "history_search": ("Looking back through our chat", "read"),
    "vantage_now": ("Checking what's happening around you", "read"),
    "plan_update": ("Updating your plan", "write"),
    "browse_screenshot": ("Taking a screenshot of the page", "browse"),
    "routine_create": ("Setting up the routine", "write"),
    "routine_list": ("Checking your routines", "read"),
    "routine_delete": ("Removing the routine", "write"),
    "routine_run_now": ("Running the routine", "write"),
    "workflow_save": ("Saving the workflow", "write"),
    "workflow_list": ("Checking your workflows", "read"),
    "workflow_run": ("Running the workflow", "write"),
    "call_me": ("Calling you", "call"),
    "call_someone": ("Getting the call ready for your OK", "call"),
}


def describe(name, args=None, ctx=None):
    """(text, kind) for one tool call, in plain words that say what is really happening. Unknown tools get
    "Using <tool>". Never includes message bodies, typed text, URL paths or anything secret-looking."""
    args = args if isinstance(args, dict) else {}
    name = str(name or "")
    try:
        if name == "web_search":
            q = safe_words(args.get("query"))
            return (f"Searching the web for {q}" if q else "Searching the web"), "search"
        if name == "research":
            n = len([a for a in (args.get("angles") or []) if str(a or "").strip()])
            return (f"Waking {n} helpers" if n > 1 else "Waking a helper"), "helpers"
        if name == "memory_edit":
            return ("Forgetting that" if args.get("op") == "remove" else "Saving that to memory"), "write"
        if name == "browse_open":
            h = _host(args.get("url"))
            return (f"Opening {h}" if h else "Opening the page"), "browse"
        if name == "browse_act":
            return _browse_act_text(args, ctx), "browse"
        if name == "browse_submit":
            label = _ref_label(args.get("ref"), ctx)
            return (f"Getting {label} ready for your OK" if label else "Getting that ready for your OK"), "browse"
        if name in _FIXED:
            return _FIXED[name]
    except Exception:  # noqa: BLE001  activity text must never break a turn
        pass
    tool = tools.BY_NAME.get(name) or {}
    words = re.sub(r"[^a-z0-9 ]", "", name.replace("_", " ").lower()).strip()[:40] or "a tool"
    return f"Using {words}", ("write" if tool.get("risk") in ("write", "send") else "read")


class Activity:
    """Emits activity start/done events for one run and remembers their texts (info["activity"])."""

    def __init__(self, emit, texts, t0=None):
        self.emit, self.texts, self.t0 = emit, texts, t0 or time.monotonic()
        self.n = 0
        self.lock = threading.Lock()

    def start(self, text, kind="read", id=None):
        kind = kind if kind in KINDS else "read"
        with self.lock:
            self.n += 1
            aid = str(id or f"act{self.n}")
            if len(self.texts) < 40:
                self.texts.append(text)
        self.emit("activity", {"id": aid, "text": text, "state": "start", "kind": kind,
                               "t": int((time.monotonic() - self.t0) * 1000)})
        return aid

    def done(self, aid, text, kind="read", ok=True):
        self.emit("activity", {"id": aid, "text": text, "state": "done", "kind": kind if kind in KINDS else "read",
                               "t": int((time.monotonic() - self.t0) * 1000), "ok": bool(ok)})

    def reporter(self):
        """ctx["activity"] for tools: report(text, kind="read", state="start", id=None) -> id."""
        def report(text, kind="read", state="start", id=None):
            text = safe_words(text, 80)
            if not text:
                return None
            if state == "done" and id:
                self.done(id, text, kind)
                return id
            return self.start(text, kind, id)
        return report


def _with_guide(messages):
    """The tool guide in the system message (once), so the model knows the rules for tool output."""
    msgs = [dict(m) for m in messages]
    guide = tools.guide()
    persona_guide = (getattr(persona, "TOOL_GUIDE", "") or "").strip()[:60]
    if msgs and msgs[0].get("role") == "system":
        sys_text = msgs[0].get("content") or ""
        # persona's own guide already there: leave the system prompt byte-identical to plain turns (cache);
        # every tool result still carries its own "data, not instructions" frame (tools.wrap)
        if tools.GUIDE_MARK not in sys_text and not (persona_guide and persona_guide in sys_text):
            msgs[0]["content"] = (msgs[0].get("content") or "") + "\n\n" + guide
    else:
        msgs.insert(0, {"role": "system", "content": guide})
    return msgs


def _approval(call, ctx, emit, info):
    """Turn a send-risk call into a pending approval. Returns the text the model sees."""
    name, args = call["name"], call.get("args") or {}
    if len(info["approvals"]) >= MAX_SENDS:
        return False, f"Error: only {MAX_SENDS} actions can wait for approval per message. Ask the user first."
    try:
        text = tools.preview(name, args)
    except tools.ToolError as e:
        return False, f"Error: {e}"
    if not callable(getattr(db, "add_approval", None)):
        return False, "Error: approvals aren't available on this server, so this can't be offered. Tell the user."
    now = time.time()
    action = {"tool": name, "args": args, "bot": ctx.get("bot") or "theta", "preview": text,
              "created": now, "expires": now + APPROVAL_TTL, "user_id": ctx.get("user_id")}
    aid = db.add_approval(action)
    info["approvals"].append({"id": aid, "tool": name, "preview": text})
    emit("approval", {"id": aid, "tool": name, "preview": text, "expires": action["expires"]})
    return True, ("Not sent. The user now sees an approval card with the exact content and Approve / Discard "
                  "buttons; it runs only if they tap Approve (it expires in 24 h). Tell them briefly that it's "
                  "waiting for their OK. Don't say it was sent.")


def _run_tools(calls, ctx, emit, info, deadline, act=None):
    """Run one step's calls; returns [(call, ok, text)] in call order."""
    results = [None] * len(calls)
    threads = []
    said = {}
    for i, c in enumerate(calls):
        name = c["name"]
        info["tools"].append(name)
        tool = tools.BY_NAME.get(name)
        if act is not None:
            text, kind = describe(name, c.get("args") or {}, ctx)
            said[c["id"]] = (act.start(text, kind, id=c["id"]), text, kind)
        if tool is not None and tool["risk"] == "send":
            ok, text = _approval(c, ctx, emit, info)
            emit("tool", {"id": c["id"], "name": name, "state": "waiting" if ok else "done", "ok": ok})
            if act is not None:
                act.done(*said[c["id"]], ok=ok)
            results[i] = (c, ok, text)
            continue
        emit("tool", {"id": c["id"], "name": name, "state": "running"})
        if tool is not None and tool["risk"] == "write":
            info["side_effects"] = True

        def work(i=i, c=c):
            results[i] = (c,) + tuple(tools.execute(c["name"], c.get("args") or {}, ctx))
        t = threading.Thread(target=work, name=f"tool-{name}", daemon=True)
        t.start()
        # a tool may ask for longer than the default (research runs several lookups; images take a while)
        threads.append((i, c, t, (tool or {}).get("timeout") or TOOL_SECONDS))
    for i, c, t, limit in threads:
        t.join(max(0.0, min(time.monotonic() + limit, deadline + 5) - time.monotonic()))
        if results[i] is None:
            results[i] = (c, False, f"Error: {c['name']} took longer than {limit} s and was abandoned "
                                    "(it may still finish). Answer without it or try once more.")
        emit("tool", {"id": c["id"], "name": c["name"], "state": "done", "ok": bool(results[i][1])})
        if act is not None and c["id"] in said:
            act.done(*said[c["id"]], ok=bool(results[i][1]))
    return results


def run(route, messages, emit, info=None, ctx=None, on_tool_start=None, max_steps=MAX_STEPS,
        turn_seconds=TURN_SECONDS, max_tokens=MAX_TOKENS):
    """Run the loop for one chat turn and return the final (cleaned) text. Raises models.ModelError if
    no candidate could answer before anything happened (no text sent, no write tool run, no approval).
    A failure after that returns what there is, with info["error"] set."""
    info = info if info is not None else {}
    info.update(steps=0, tools=[], usage={}, approvals=[], sources=[], emitted=False, side_effects=False,
                ttft=None, cost_usd=0.0, tried=[], activity=[])
    act = Activity(emit, info["activity"])
    ctx = dict(ctx or {})
    ctx.setdefault("activity", act.reporter())
    ctx.setdefault("sources", info["sources"])
    info["sources"] = ctx["sources"]
    specs = tools.specs()
    msgs = _with_guide(messages)
    deadline = time.monotonic() + turn_seconds
    cands = list(getattr(route, "candidates", ()) or [(route.provider, route.model)])
    cands = [c for c in cands if models.supports_tools(c[0])] or cands
    ci = 0
    cleaner = persona.Cleaner()
    state = {"sep": False}

    def on_text(chunk):
        if not chunk:
            return
        if state["sep"] and chunk.strip():
            chunk = "\n\n" + chunk.lstrip()
            state["sep"] = False
        if info["ttft"] is None:
            info["ttft"] = time.monotonic()
        out = cleaner.feed(chunk)
        if out:
            info["emitted"] = True
            emit("delta", {"text": out})

    final = False
    while True:
        out_of_time = time.monotonic() >= deadline - 5
        if (info["steps"] >= max_steps - 1 or out_of_time) and info["steps"] > 0 and not final:
            final = True
            msgs.append({"role": "user", "content": FINAL_NOTE})
        provider, model = cands[ci]
        info.update(provider=provider, model=model)
        if f"{provider}/{model}" not in info["tried"]:
            info["tried"].append(f"{provider}/{model}")
        remaining = max(10.0, deadline - time.monotonic())
        try:
            res = models.call(provider, model, msgs, specs, max_tokens, on_text=on_text,
                              tool_choice="none" if final else "auto", timeout=remaining)
        except models.ModelError as e:
            clean_slate = not info["emitted"] and not info["side_effects"] and not info["approvals"]
            if clean_slate and ci + 1 < len(cands):
                ci += 1
                emit("route", {"model": cands[ci][1], "provider": cands[ci][0], "tier": route.tier,
                               "why": f"{route.why}; fallback after: {str(e)[:160]}"[:200]})
                continue
            info["error"] = str(e)[:300]
            if clean_slate:
                raise
            break  # text or a tool's effect already went out: keep what we have (app marks it partial)
        info["steps"] += 1
        models.add_usage(info["usage"], res.get("usage"))
        calls = res.get("tool_calls") or []
        if not calls or final:
            break
        if info["steps"] == 1 and not info["emitted"] and on_tool_start:
            on_tool_start(calls)
        if cleaner.full.strip():
            state["sep"] = True
        msgs.append({"role": "assistant", "content": res.get("text") or "", "tool_calls": calls,
                     "reasoning": res.get("reasoning") or ""})
        for c, ok, text in _run_tools(calls, ctx, emit, info, deadline, act):
            msgs.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                         "content": tools.wrap(c["name"], text, ok)})
    tail = cleaner.finish()
    if tail:
        info["emitted"] = True
        emit("delta", {"text": tail})
    info["cost_usd"] = models.cost(info.get("model"), info["usage"], info.get("provider"))
    return cleaner.text()
