"""Theta's runtime: turns that keep going on their own, take your messages mid-turn, and survive a restart.

- begin/end: while a tool turn runs, RUNS[bot] holds it. steer() stores a message you send mid-turn and hands its
  text to the turn (agent.run reads ctx["inbox"] between steps), so Theta takes it into account right away. A
  message that arrives after the turn's last step gets its own follow-up turn as soon as this one ends.
- checkpoint(): after every step the turn's working messages are saved ("run:<bot>"), so a redeploy or crash in the
  middle of a job doesn't lose it: on the next start, tick() resumes it from the last finished step (steps already
  done aren't repeated) and the reply lands in the chat like any other. A turn is resumed at most once.
- recent_tools(): the tools the last few turns used, loaded up front (a follow-up usually needs the same ones).

Routes: POST /api/chat/steer {bot, text, show?} -> {mode: "steered", user} or {mode: "later"} (nothing running;
the app sends it as a normal message once the reply is done).
"""
import threading
import time

from . import db

RUNS = {}
_lock = threading.Lock()
RESUME_AFTER = 60          # seconds without a checkpoint before a turn counts as interrupted
MAX_CHECKPOINT = 3_000_000  # chars


class Run:
    def __init__(self, bot, user_id):
        self.bot, self.user_id = bot, user_id
        self.inbox, self.pending, self.closed = [], [], False
        self.lock = threading.Lock()

    def take(self):
        with self.lock:
            out, self.inbox = self.inbox, []
            self.pending = []  # taken into the running turn: no follow-up needed
            return out


def begin(bot, user_id, route=None):
    run = Run(bot, user_id)
    with _lock:
        RUNS[bot] = run
    return run


def end(bot, run):
    with run.lock:
        run.closed = True
        leftover = list(run.pending)
    with _lock:
        if RUNS.get(bot) is run:
            del RUNS[bot]
    clear(bot)
    if leftover:  # sent after the last step: answer it now, as its own turn
        threading.Thread(target=_follow_up, args=(bot, leftover[-1]), name="followup", daemon=True).start()


def _follow_up(bot, msg):
    from . import app
    try:
        app._chat_worker(bot, msg.get("meta", {}).get("prompt") or msg["text"], [], None, lambda e, d: None,
                         edit={"user": msg, "deleted": [], "note": None, "followup": True})
    except Exception:  # noqa: BLE001
        app.log("follow-up turn failed")


def steer(bot, text, show=None):
    """Store a message sent while Theta works and give it to the running turn. None if nothing is running."""
    with _lock:
        run = RUNS.get(bot)
    if run is None:
        return None
    with run.lock:
        if run.closed:
            return None
        meta = {"steered": True, "reply_to": run.user_id}
        if show:
            meta["prompt"] = text[:2000]
        msg = db.add_message(bot, "user", show or text, meta)
        run.inbox.append(text)
        run.pending.append(msg)
    return msg


def recent_tools(history, turns=4):
    out = []
    for m in reversed(list(history or [])):
        if m.get("role") != "assistant":
            continue
        for n in (m.get("meta") or {}).get("tools") or []:
            if n not in out:
                out.append(n)
        turns -= 1
        if turns <= 0:
            break
    return out[:12]


# ---------------------------------------------------------------- checkpoints and resuming

def checkpoint(bot, user_id, route, msgs, info):
    import json
    data = {"bot": bot, "user_id": user_id, "t": time.time(), "steps": info.get("steps"),
            "route": route._asdict() if hasattr(route, "_asdict") else {}, "msgs": msgs}
    try:
        if len(json.dumps(data, default=str)) > MAX_CHECKPOINT:
            return
    except (TypeError, ValueError):
        return
    db.set_setting("run:" + bot, data)


def clear(bot):
    db.set_setting("run:" + bot, None)


def tick(now):
    """Resume a turn a restart cut off (once)."""
    from . import app
    for bot in list(getattr(app, "BOT_IDS", ("theta",))):
        cp = db.get_setting("run:" + bot)
        if not isinstance(cp, dict) or bot in RUNS or now - float(cp.get("t") or 0) < RESUME_AFTER:
            continue
        clear(bot)
        if cp.get("resumed"):
            continue
        user = db.get_message(cp.get("user_id"))
        if not user or not cp.get("msgs"):
            continue
        cp["resumed"] = True
        threading.Thread(target=_resume, args=(bot, user, cp), name="resume", daemon=True).start()
    return []


def _resume(bot, user, cp):
    from . import app, router
    try:
        r = cp.get("route") or {}
        route = router.Route(tier=r.get("tier") or "quick", model=r.get("model") or "", provider=r.get("provider") or "",
                             why="picked up after a restart", candidates=tuple(tuple(c) for c in r.get("candidates") or ()))
        msgs = cp["msgs"] + [{"role": "user", "content": "[harness] The server restarted in the middle of this. Carry "
                                                         "on from where you were; don't redo steps that already worked."}]
        log_row = {"bot": bot, "chars_in": len(user.get("text") or ""), "ok": False, "tried": [], "user_id": user["id"]}
        app._agent_turn(bot, user.get("text") or "", [], user, route, None, lambda e, d: None, log_row,
                        time.monotonic(), tag={"reply_to": user["id"], "resumed": True}, resume=msgs)
    except Exception:  # noqa: BLE001
        app.log("resuming a turn failed")


# ---------------------------------------------------------------- route

def steer_route(req, start):
    from .app import BOT_IDS, HTTPError, respond_json
    if req.method != "POST":
        raise HTTPError(405, "method not allowed")
    body = req.json() or {}
    bot = body.get("bot") or "theta"
    if bot not in BOT_IDS:
        raise HTTPError(404, "unknown bot")
    text = str(body.get("text") or "").strip()[:20000]
    if not text:
        raise HTTPError(400, "text is required")
    show = body.get("show") if isinstance(body.get("show"), str) and body["show"].strip() else None
    msg = steer(bot, text, show[:80] if show else None)
    return respond_json(start, {"mode": "steered", "user": msg} if msg else {"mode": "later"})


ROUTES = {"/api/chat/steer": steer_route}
