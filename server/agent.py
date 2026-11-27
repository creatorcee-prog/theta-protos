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

import re
import threading
import time

from . import activity, db, models, persona, tools

MAX_STEPS = 10
TOOL_SECONDS = 20
TOOL_TIMEOUT_AWARE = True  # a tool with its own "timeout" gets that long (see _run_tools)
TURN_SECONDS = 90
MAX_TOKENS = 1200
MAX_SENDS = 10         # approval cards per turn (each card carries its own Approve / Discard)
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


_NEEDS = {"send_email_draft": "google", "calendar_invite": "google", "call_someone": "twilio", "send_text": "twilio",
          "gmail_trash": "google", "gmail_unsubscribe": "google", "calendar_delete": "google", "calendar_move": "google",
          "drive_trash": "gdrive", "drive_share": "gdrive"}


def _service_ready(service):
    try:
        if service == "google":
            from . import google
            return bool(google.connected("gmail"))
        if service == "gdrive":
            from . import google
            return bool(google.connected("drive_full"))
        if service == "gsettings":
            from . import google
            return bool(google.connected("gmail_settings"))
        if service == "twilio":
            import os
            from . import telco
            return telco.configured()
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
            cards.attach(ctx, cards.connect("google" if needs == "gdrive" else needs))
        except Exception:  # noqa: BLE001
            pass
        try:
            from . import resume
            resume.record(ctx, needs, aid)  # once it's connected, Theta texts them that it can go
        except Exception:  # noqa: BLE001
            pass
        return True, ("Not sent, and it can't be yet: " + needs.title() + " isn't connected. The user sees the "
                      "approval card and a card to connect it. Tell them plainly it goes out only after it's connected "
                      "AND they tap Approve, and that you'll text them the moment it's connected so they can "
                      "approve it then. Never say it'll send by itself.")
    return True, ("Not sent. The user now sees an approval card with the exact content and Approve / Discard "
                  "buttons; it runs only if they tap Approve (it expires in 24 h). Tell them briefly that it's "
                  "waiting for their OK. Don't say it was sent.")


def _auto_run(call, ctx, emit, info):
    """Run a send action without a tap when the user's approval setting allows it here (server/approvals.py).
    Returns (ok, text) when it ran, None for the usual approval card (with why in ctx["auto_note"])."""
    try:
        from . import approvals
        ok_here, why = approvals.allowed(call["name"], ctx, info, call.get("args") or {})
    except Exception:  # noqa: BLE001
        return None
    if not ok_here:
        if why and isinstance(ctx, dict):
            ctx["auto_note"] = why
        return None
    needs = _NEEDS.get(call["name"])
    if needs and not _service_ready(needs):
        return None  # not connected: the approval card and connect card, picked up later
    try:
        preview = tools.preview(call["name"], call.get("args") or {})
    except tools.ToolError as e:
        return False, f"Error: {e}"
    emit("tool", {"id": call["id"], "name": call["name"], "state": "running"})
    ok, text = tools.run_approved({"tool": call["name"], "args": call.get("args") or {},
                                   "bot": (ctx or {}).get("bot") or "theta"})
    emit("tool", {"id": call["id"], "name": call["name"], "state": "done", "ok": ok})
    info["side_effects"] = info["side_effects"] or ok
    try:
        from . import cards
        from . import approvals as A
        receipt = {"type": "approval", "id": None, "tool": call["name"], "preview": preview,
                   "state": "auto" if ok else "failed", "result": str(text)[:300]}
        comm = A.comm_of(call["name"], call.get("args"))
        if comm:
            receipt["comm"] = comm
        cards.attach(ctx, receipt)
    except Exception:  # noqa: BLE001
        pass
    if not ok:
        return False, f"Error: {text}"
    return True, (f"Done without asking (the user allows this one): {text} A card shows exactly what was done. "
                  "Tell them in one line.")


def _run_tools(calls, ctx, emit, info, deadline):
    """Run one step's calls; returns [(call, ok, text)] in call order."""
    results = [None] * len(calls)
    threads = []
    act = info.get("_act")
    for i, c in enumerate(calls):
        name = c["name"]
        info["tools"].append(name)
        if act is not None:
            try:
                act.call(c, ctx)
            except Exception:  # noqa: BLE001  status text never breaks a turn
                pass
        tool = tools.BY_NAME.get(name)
        if tool is not None and tool["risk"] == "send" and not callable(tool.get("auto")):
            done = _auto_run(c, ctx, emit, info)  # the user set this action to run without a tap
            if done is not None:
                results[i] = (c, done[0], done[1])
                continue
        if tool is not None and tool["risk"] == "send" and callable(tool.get("auto")):
            # a send with its own check (reviewed texts to saved contacts): the tool decides; anything it doesn't
            # clear falls back to the approval card below
            emit("tool", {"id": c["id"], "name": name, "state": "running"})
            try:
                done = tool["auto"](c.get("args") or {}, ctx, info)
            except Exception as e:  # noqa: BLE001
                done = None
                ctx["auto_note"] = f"the automatic check failed ({type(e).__name__})"
            if done is not None:
                ok, text = done
                info["side_effects"] = info["side_effects"] or ok
                emit("tool", {"id": c["id"], "name": name, "state": "done", "ok": ok})
                results[i] = (c, ok, text)
                continue
        if tool is not None and tool["risk"] == "send":
            ok, text = _approval(c, ctx, emit, info)
            note = ctx.pop("auto_note", None) if isinstance(ctx, dict) else None
            if ok and note:
                text += f" It wasn't sent automatically because {note}; say that in a few words."
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


NOTE_MAX = 160  # longest note kept from the text before tool calls
HOLD_MAX = 700  # text held back while it might turn out to come before tool calls
MAX_NOTES = 2   # progress texts per turn: "On it, I'll..." and at most one update


_CLAIM = re.compile(r"(?i)\b(done|set|all set|finished|sent|added|saved|created|booked|scheduled|fixed|archived|"
                    r"deleted|trashed|moved|filled|submitted|signed in|waiting (?:on|for) your)\b(?!\s+(?:it|that|this|them|up|you)\b)")  # a result, before it happened


_DOING = re.compile(r"(?i)^(\w+ing\b|i'?ll\b|i will\b|i'?m\b|let me\b|going to\b|on it\b|now\b)")  # progress, not a result


def _claims(sentence):
    return bool(_CLAIM.search(sentence)) and not _DOING.match(sentence.strip())


def _note_of(text):
    """The note from text written before the tools ran: its first sentence, plus the second when the first is
    just "On it." and the second doesn't already claim a result. "" when even the first is too long."""
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.split("\n\n")[0].strip()) if p]
    if not parts or len(parts[0]) > NOTE_MAX or _claims(parts[0]):
        return ""
    out = parts[0]
    if len(out) < 25 and len(parts) > 1 and not _claims(parts[1]) and len(out) + len(parts[1]) < NOTE_MAX:
        out += " " + parts[1]
    return out


def run(route, messages, emit, info=None, ctx=None, on_tool_start=None, max_steps=MAX_STEPS,
        turn_seconds=TURN_SECONDS, max_tokens=MAX_TOKENS, on_note=None):
    """Run the loop for one chat turn and return the final (cleaned) text. Raises models.ModelError if
    no candidate could answer before anything happened (no text sent, no write tool run, no approval).
    A failure after that returns what there is, with info["error"] set."""
    info = info if info is not None else {}
    info.update(steps=0, tools=[], usage={}, approvals=[], sources=[], emitted=False, side_effects=False,
                ttft=None, cost_usd=0.0, tried=[], activity=[])
    ctx = ctx if isinstance(ctx, dict) else {}  # shared with the caller: tools add cards and images to it
    act = activity.Activity(emit, info["activity"])  # "Drafting an email to Sam" under the working globe
    ctx["activity"] = act.reporter()
    info["_act"] = act
    act.start(activity.THINKING, "think", keep=False)  # until the first step or words; not kept for the reply
    ctx.setdefault("sources", info["sources"])
    info["sources"] = ctx["sources"]
    specs = tools.specs()
    msgs = _with_guide(messages)
    deadline = time.monotonic() + turn_seconds
    cands = list(getattr(route, "candidates", ()) or [(route.provider, route.model)])
    cands = [c for c in cands if models.supports_tools(c[0])] or cands
    ci = 0
    cleaner = persona.Cleaner()
    state = {"sep": False, "hold": "", "held": on_note is not None, "notes": 0}

    def on_text(chunk):
        if not chunk:
            return
        # A step's opening words are held while short: if tool calls follow, they're a note of their own
        # ("On it. I'll pull your job alerts..."), shown as a separate message by on_note; if not, or once
        # they grow past a short line, they stream as the reply.
        if state["held"]:
            state["hold"] += chunk
            if len(state["hold"]) <= HOLD_MAX:
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
            # only the opening sentence or two is a note; anything after it was written before the tools ran (a
            # premature "Done: ..." the reply will say properly once they have), so it's dropped
            note = _note_of(persona.clean(held).strip())
            if note and state["notes"] < MAX_NOTES:  # the opening line, and one update; more is just chatter
                state["notes"] += 1
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
    info.pop("_act", None)
    return cleaner.text()
