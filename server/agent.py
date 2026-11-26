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
- Provider fallback (route.candidates) only before any text reached the user and before any tool ran.

`info` (a dict) is filled with: provider, model, steps, tools (names in order), usage (summed),
cost_usd, approvals [{"id", "tool", "preview"}], sources, ttft (monotonic time of first text), emitted.
"""

import threading
import time

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


_NEEDS = {"send_email_draft": "google", "calendar_invite": "google", "call_someone": "twilio"}


def _service_ready(service):
    try:
        if service == "google":
            from . import google
            return bool(google.connected("gmail"))
        if service == "twilio":
            import os
            return bool(os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN"))
    except Exception:  # noqa: BLE001
        return True  # unsure: don't claim it's missing
    return True


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
    needs = _NEEDS.get(name)
    if needs and not _service_ready(needs):  # say so now, not when they tap Approve: the connect card comes too
        try:
            from . import cards
            cards.attach(ctx, cards.connect(needs))
        except Exception:  # noqa: BLE001
            pass
        return True, ("Not sent, and it can't be yet: " + needs.title() + " isn't connected. The user sees the "
                      "approval card and a card to connect it. Tell them plainly it'll only go out once they connect "
                      "it and tap Approve.")
    return True, ("Not sent. The user now sees an approval card with the exact content and Approve / Discard "
                  "buttons; it runs only if they tap Approve (it expires in 24 h). Tell them briefly that it's "
                  "waiting for their OK. Don't say it was sent.")


def _run_tools(calls, ctx, emit, info, deadline):
    """Run one step's calls; returns [(call, ok, text)] in call order."""
    results = [None] * len(calls)
    threads = []
    for i, c in enumerate(calls):
        name = c["name"]
        info["tools"].append(name)
        tool = tools.BY_NAME.get(name)
        if tool is not None and tool["risk"] == "send":
            ok, text = _approval(c, ctx, emit, info)
            emit("tool", {"id": c["id"], "name": name, "state": "waiting" if ok else "done", "ok": ok})
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
    return results


NOTE_MAX = 160  # longest opening line held back as a possible note before tool calls


def run(route, messages, emit, info=None, ctx=None, on_tool_start=None, max_steps=MAX_STEPS,
        turn_seconds=TURN_SECONDS, max_tokens=MAX_TOKENS, on_note=None):
    """Run the loop for one chat turn and return the final (cleaned) text. Raises models.ModelError if
    no candidate could answer before anything happened (no text sent, no write tool run, no approval).
    A failure after that returns what there is, with info["error"] set."""
    info = info if info is not None else {}
    info.update(steps=0, tools=[], usage={}, approvals=[], sources=[], emitted=False, side_effects=False,
                ttft=None, cost_usd=0.0, tried=[])
    ctx = ctx if isinstance(ctx, dict) else {}  # shared with the caller: tools add cards and images to it
    ctx.setdefault("sources", info["sources"])
    info["sources"] = ctx["sources"]
    specs = tools.specs()
    msgs = _with_guide(messages)
    deadline = time.monotonic() + turn_seconds
    cands = list(getattr(route, "candidates", ()) or [(route.provider, route.model)])
    cands = [c for c in cands if models.supports_tools(c[0])] or cands
    ci = 0
    cleaner = persona.Cleaner()
    state = {"sep": False, "hold": "", "held": on_note is not None}

    def on_text(chunk):
        if not chunk:
            return
        # A step's opening words are held while short: if tool calls follow, they're a note of their own
        # ("On it. I'll pull your job alerts..."), shown as a separate message by on_note; if not, or once
        # they grow past a short line, they stream as the reply.
        if state["held"]:
            state["hold"] += chunk
            if len(state["hold"]) <= NOTE_MAX and "\n\n" not in state["hold"]:
                return
            state["held"] = False
            chunk, state["hold"] = state["hold"], ""
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
        held, state["hold"] = state["hold"], ""
        if held.strip() and calls and not final:
            note = persona.clean(held).strip()
            if note:
                on_note(note)
        elif held:
            state["held"] = False
            on_text(held)
        state["held"] = on_note is not None
        if not calls or final:
            break
        if info["steps"] == 1 and not info["emitted"] and on_tool_start:
            on_tool_start(calls)
        if cleaner.full.strip():
            state["sep"] = True
        msgs.append({"role": "assistant", "content": res.get("text") or "", "tool_calls": calls,
                     "reasoning": res.get("reasoning") or ""})
        for c, ok, text in _run_tools(calls, ctx, emit, info, deadline):
            msgs.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                         "content": tools.wrap(c["name"], text, ok)})
    tail = cleaner.finish()
    if tail:
        info["emitted"] = True
        emit("delta", {"text": tail})
    info["cost_usd"] = models.cost(info.get("model"), info["usage"], info.get("provider"))
    return cleaner.text()
