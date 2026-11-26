"""Picking a request back up once the app it needed is connected.

When a request can't be done because something isn't connected (a tool fails with "Gmail isn't connected", or
a text or email waits for approval while Twilio or Google isn't set up), the request is saved here. Once that
service is connected, Theta texts first (with a push) and carries on:
- a draft already waiting for approval: "Gmail's connected, so your email to Sam can go now" with Approve /
  Discard (nothing is re-drafted, nothing sends without the tap)
- anything else: the original request runs again as a real tool turn, and the result is posted.

Saved as the "pending_connect" setting: [{service, text, bot, user_id, t, approvals}]. Requests older than
MAX_AGE are dropped. Only requests the user typed are saved (not routines).
"""
import os
import threading
import time
import traceback

from . import db

SETTING = "pending_connect"
MAX_AGE = 3 * 86400
MAX_ITEMS = 10
NAMES = {"google": "Gmail", "twilio": "Twilio", "tavily": "Web search", "gemini": "Image generation",
         "giphy": "GIFs"}
_lock = threading.Lock()


def _items():
    v = db.get_setting(SETTING)
    return [p for p in v if isinstance(p, dict)] if isinstance(v, list) else []


def _ready(service):
    if service in ("google", "twilio"):
        from . import agent
        return agent._service_ready(service)
    env = {"tavily": "TAVILY_API_KEY", "gemini": "GEMINI_API_KEY", "giphy": "GIPHY_API_KEY"}.get(service)
    return bool(env and (os.environ.get(env) or "").strip())


def record(ctx, service, approval_id=None):
    """Save the request behind this turn so it's picked up once `service` is connected."""
    ctx = ctx if isinstance(ctx, dict) else {}
    uid = ctx.get("user_id")
    if not uid or ctx.get("routine") or service not in NAMES or _ready(service):
        return
    m = db.get_message(uid)
    if not m or m.get("role") != "user":
        return
    text = (m.get("meta") or {}).get("prompt") or m.get("text") or ""
    if not text.strip():
        return
    with _lock:
        items = [p for p in _items() if time.time() - float(p.get("t") or 0) < MAX_AGE]
        hit = next((p for p in items if p.get("user_id") == uid and p.get("service") == service), None)
        if hit is None:
            hit = {"service": service, "text": text[:2000], "bot": ctx.get("bot") or "theta", "user_id": uid,
                   "t": time.time(), "approvals": []}
            items.append(hit)
        if approval_id and approval_id not in hit["approvals"]:
            hit["approvals"].append(approval_id)
        db.set_setting(SETTING, items[-MAX_ITEMS:])


def _take_ready(now):
    with _lock:
        items = _items()
        keep, ready = [], []
        for p in items:
            if now - float(p.get("t") or 0) >= MAX_AGE:
                continue
            (ready if _ready(p.get("service")) else keep).append(p)
        if ready or len(keep) != len(items):
            db.set_setting(SETTING, keep)
        return ready


def _actions(ids):
    acts = []
    for aid in ids:
        acts += [{"label": "Approve", "value": f"approve:{aid}"}, {"label": "Discard", "value": f"deny:{aid}"}]
    return acts[:4]


def _waiting(p):
    """The approvals from this request that are still waiting for a tap."""
    out = []
    for aid in p.get("approvals") or []:
        a = db.get_approval(aid) if callable(getattr(db, "get_approval", None)) else None
        exp = float(((a or {}).get("action") or {}).get("expires") or 0)
        if a and a.get("state") == "pending" and exp > time.time():
            out.append(a)
    return out


def _post(bot, text, meta, now, title):
    msg = db.add_message(bot, "assistant", text, dict(meta, proactive=True, source="resume"))
    try:
        from . import routines
        routines._push(msg, title, now)
    except Exception:  # noqa: BLE001
        pass
    return msg


def _rerun(p, now):
    """The original request again, as a real tool turn, now that the service is there."""
    from . import agent, models, persona, routines, tools
    bot, svc = p.get("bot") or "theta", NAMES.get(p["service"], p["service"])
    note = (f"(Picking this back up: {svc} is connected now, so do what they asked earlier. Start with one short "
            f"line saying it's connected and what you're doing.)\n\n")
    info, t0 = {}, time.monotonic()
    log_row = {"bot": bot, "chars_in": len(p["text"]), "ok": False, "tier": "resume", "why": f"{svc} connected"}
    try:
        route = routines._quick_route(now)
        history = db.messages(bot, before=p.get("user_id"), limit=persona.HISTORY) if p.get("user_id") else []
        msgs = persona.build(history, note + p["text"], bot=bot, context=tools.context_block(bot, now))
        final = agent.run(route, msgs, lambda ev, data: None, info=info, ctx={"bot": bot, "resume": True},
                          max_steps=agent.MAX_STEPS)
    except models.ModelError as e:
        log_row["error"] = str(e)[:300]
        routines._turn(log_row, info, t0)
        return _post(bot, f"{svc} is connected now, but I couldn't pick your request back up ({str(e)[:80]}). "
                          "Ask me again and I'll do it.", {"reply_to": p.get("user_id")}, now, svc + " is connected")
    out = (final or "").strip() or "Done."
    meta = {"reply_to": p.get("user_id"), "model": info.get("model"), "provider": info.get("provider"),
            "tier": "resume", "steps": info.get("steps") or 0}
    if info.get("tools"):
        meta["tools"] = info["tools"]
    if info.get("approvals"):
        meta["approvals"] = [a["id"] for a in info["approvals"]]
        meta["actions"] = _actions(meta["approvals"])
    if info.get("sources"):
        meta["sources"] = info["sources"]
    msg = _post(bot, out, meta, now, svc + " is connected")
    log_row.update(reply_id=msg["id"], chars_out=len(out), ok=not info.get("error"))
    routines._turn(log_row, info, t0)
    return msg


def run_ready(now=None):
    now = time.time() if now is None else float(now)
    out = []
    for p in _take_ready(now):
        try:
            svc = NAMES.get(p["service"], p["service"])
            waiting = _waiting(p)
            if waiting:
                what = "it" if len(waiting) == 1 else "they"
                out.append(_post(p.get("bot") or "theta",
                                 f"{svc} is connected, so the one I drafted can go now. Nothing goes out until you "
                                 f"tap Approve, and {what} expire{'s' if what == 'it' else ''} in a day.",
                                 {"reply_to": p.get("user_id"), "approvals": [a["id"] for a in waiting],
                                  "actions": _actions([a["id"] for a in waiting])}, now, svc + " is connected"))
            elif not p.get("approvals"):
                out.append(_rerun(p, now))
        except Exception:  # noqa: BLE001
            print("[protos] resume failed:\n" + traceback.format_exc(), flush=True)
    return out


def tick(now):
    return run_ready(now)
