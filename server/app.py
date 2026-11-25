"""WSGI app + threaded dev server for theta-protos (see docs/SPEC.md).

    python -m server            # PORT (default 8780), HOST (default 0.0.0.0)

Serves the phone app from web/ and the JSON API under /api/. POST /api/chat
streams Server-Sent Events. push.py and proactive.py are optional modules
imported lazily; their routes answer 501 until they exist.

Tool turns (docs/HARNESS-PLAN.md, Builder B): when a message looks like it needs a tool
(tools.relevant), the chat handler runs agent.run instead of a plain stream. "send"-risk tools
only ever create a pending approval; POST /api/approve {id, decision} (or tapping the reply's
"approve:<id>" / "deny:<id>" chip, which arrives as that exact chat text) runs the stored action
exactly as stored, without asking the model again. Approvals expire after 24 h. Jobs ("remind me
in 10 minutes") are run by the ticker every JOB_SECONDS.
"""

import hmac
import inspect
import json
import mimetypes
import os
import queue
import re
import socketserver
import sys
import threading
import time
import traceback
import urllib.parse
from http.cookies import SimpleCookie
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from . import __version__, agent, db, models, persona, router, tools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_BODY = 12 * 1024 * 1024  # images can be attached to chat
MAX_TOKENS = int(os.environ.get("PROTOS_MAX_TOKENS", "1200"))
TICK_SECONDS = 300
JOB_SECONDS = 30   # due reminders are checked this often (a "remind me in 2 minutes" can't wait 5)
PING_SECONDS = 15
APPROVAL_TTL = agent.APPROVAL_TTL  # 24 h
TOOL_ACK = "On it."
_APPROVE_TEXT = re.compile(r"^\s*(approve|deny):(\d{1,12})\s*$", re.I)

BOTS = [{"id": "theta", "name": "Theta",
         "avatar": {"kind": "dot-globe", "theme": "theta", "color": "#7cc4ff"}}]
BOT_IDS = {b["id"] for b in BOTS}

SETTINGS_DEFAULTS = {"proactive": True, "quiet": [22, 7], "tz": persona.DEFAULT_TZ, "loc": None}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; manifest-src 'self'; worker-src 'self'; media-src 'self' blob:; "
       "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
SECURITY_HEADERS = [
    ("Content-Security-Policy", CSP),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Permissions-Policy", "geolocation=(self), camera=(self), microphone=(self)"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
]

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("image/svg+xml", ".svg")


class HTTPError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


_STATUS = {200: "200 OK", 204: "204 No Content", 400: "400 Bad Request", 401: "401 Unauthorized",
           403: "403 Forbidden", 404: "404 Not Found", 405: "405 Method Not Allowed", 409: "409 Conflict",
           413: "413 Payload Too Large", 500: "500 Internal Server Error", 501: "501 Not Implemented",
           502: "502 Bad Gateway", 503: "503 Service Unavailable"}


def web_dir():
    return os.environ.get("PROTOS_WEB") or os.path.join(ROOT, "web")


def log(*a):
    print("[protos]", *a, file=sys.stderr, flush=True)


# ---- request helpers

class Req:
    def __init__(self, environ):
        self.env = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = environ.get("PATH_INFO", "/") or "/"
        self.query = {k: v[-1] for k, v in urllib.parse.parse_qs(environ.get("QUERY_STRING", "")).items()}
        self._body = None

    def header(self, name):
        return self.env.get("HTTP_" + name.upper().replace("-", "_"))

    def cookie(self, name):
        raw = self.env.get("HTTP_COOKIE")
        if not raw:
            return None
        try:
            c = SimpleCookie()
            c.load(raw)
        except Exception:
            return None
        return c[name].value if name in c else None

    def json(self):
        if self._body is None:
            try:
                n = int(self.env.get("CONTENT_LENGTH") or 0)
            except ValueError:
                n = 0
            if n > MAX_BODY:
                raise HTTPError(413, "request too large")
            raw = self.env["wsgi.input"].read(n) if n > 0 else b""
            if not raw.strip():
                self._body = {}
            else:
                try:
                    self._body = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    raise HTTPError(400, "body must be JSON") from None
            if not isinstance(self._body, dict):
                raise HTTPError(400, "body must be a JSON object")
        return self._body

    def https(self):
        return (self.env.get("wsgi.url_scheme") == "https" or
                (self.header("X-Forwarded-Proto") or "").lower() == "https")

    def int_arg(self, name, default=None, lo=None, hi=None):
        v = self.query.get(name)
        if v in (None, ""):
            return default
        try:
            n = int(v)
        except ValueError:
            raise HTTPError(400, f"{name} must be an integer") from None
        if lo is not None:
            n = max(lo, n)
        if hi is not None:
            n = min(hi, n)
        return n


def _headers(content_type, extra=None):
    h = [("Content-Type", content_type)] + SECURITY_HEADERS
    return h + list(extra or [])


def respond_json(start, obj, status=200, extra=None):
    body = json.dumps(obj, ensure_ascii=False).encode()
    start(_STATUS.get(status, f"{status} Error"),
          _headers("application/json; charset=utf-8",
                   [("Content-Length", str(len(body))), ("Cache-Control", "no-store")] + list(extra or [])))
    return [body]


def authed(req):
    key = os.environ.get("PROTOS_KEY", "")
    if not key:
        return True
    got = req.header("x-protos-key") or req.cookie("protos_key") or ""
    return hmac.compare_digest(got.encode(), key.encode())


# ---- optional modules

def _optional(name):
    """`from . import <name>`, or None if that module doesn't exist (or can't load) yet."""
    try:
        if name == "push":
            from . import push as mod
        elif name == "proactive":
            from . import proactive as mod
        elif name == "memory":
            from . import memory as mod
        else:
            return None
        return mod
    except ImportError as e:
        if getattr(e, "name", None) != f"server.{name}":
            log(f"{name}.py couldn't be imported: {e}")
        return None


def _first(mod, *names):
    for n in names:
        fn = getattr(mod, n, None)
        if callable(fn):
            return fn
    return None


def _jsonable(x):
    try:
        json.dumps(x)
        return x
    except (TypeError, ValueError):
        return str(x)


def run_proactive(now=None):
    """proactive.run() if the module exists; returns its result, or raises HTTPError(501)."""
    mod = _optional("proactive")
    fn = getattr(mod, "run", None) if mod else None
    if not callable(fn):
        raise HTTPError(501, "proactive isn't installed yet")
    try:
        required = [p for p in inspect.signature(fn).parameters.values()
                    if p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    except (TypeError, ValueError):
        required = []
    return fn(now if now is not None else time.time()) if required else fn()


# ---- chat

def _images(body):
    imgs = []
    for a in (body.get("images") or []) + (body.get("attachments") or []):
        u = a if isinstance(a, str) else (a.get("data") or a.get("url") if isinstance(a, dict) else None)
        if isinstance(u, str) and u.startswith("data:image/"):
            imgs.append(u)
    return imgs[:4]


def _accepts(fn, name):
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == name or p.kind == p.VAR_KEYWORD for p in params)


def _stream(provider, model, msgs, usage):
    """models.stream, passing the usage dict when this models.stream takes one (test fakes may not)."""
    if _accepts(models.stream, "usage"):
        return models.stream(provider, model, msgs, MAX_TOKENS, usage=usage)
    return models.stream(provider, model, msgs, MAX_TOKENS)


def _pick(text, history, attachments):
    last = None
    if callable(getattr(router, "last_route", None)):
        try:
            last = router.last_route(history)
        except Exception:
            last = None
    if last is not None and _accepts(router.pick, "last"):
        return router.pick(text, history, attachments, last=last)
    return router.pick(text, history, attachments)


def _build(history, text, bot, images=None, extra=None, context=None):
    """persona.build with the volatile tool context in the latest turn (older persona: in `extra`)."""
    if context and _accepts(persona.build, "context"):
        return persona.build(history, text, images=images, extra=extra, bot=bot, context=context)
    if context:
        extra = f"{extra}\n\n{context}" if extra else context
    return persona.build(history, text, images=images, extra=extra, bot=bot)


def _usage_row(log_row, usage, provider, model):
    if not usage:
        return
    for k in ("tokens_in", "tokens_out", "cache_read", "cache_write"):
        log_row[k] = int(usage.get(k) or 0)
    log_row["cost_usd"] = models.cost(model, usage, provider)


def _compact_later(bot):
    """memory.compact(bot, summarize=quick model) in the background, after the reply is out."""
    if os.environ.get("PROTOS_COMPACT", "1") == "0":
        return
    mem = _optional("memory")
    if mem is None or not callable(getattr(mem, "compact", None)):
        return

    def work():
        try:
            fn = mem.summarizer() if callable(getattr(mem, "summarizer", None)) else None
            if fn:
                mem.compact(bot, summarize=fn)
        except Exception:
            log("compaction failed:\n" + traceback.format_exc())
    threading.Thread(target=work, name="compact", daemon=True).start()


def _use_tools(text, images, route):
    if images or route.tier in ("vision", "local"):
        return False
    if not tools.relevant(text):
        return False
    return any(models.supports_tools(p) for p, _m in (route.candidates or [(route.provider, route.model)]))


def _approval_actions(approvals):
    out = []
    for a in approvals:
        out += [{"label": "Approve", "value": f"approve:{a['id']}"}, {"label": "Discard", "value": f"deny:{a['id']}"}]
    return out[:4]


def _agent_turn(bot, text, history, user, route, ack_text, emit, log_row, t0):
    """A tool turn: agent.run, then the stored reply (with approval chips if a send is waiting)."""
    cands = list(route.candidates) or [(route.provider, route.model)]
    provider, model = cands[0]
    emit("route", {"model": model, "provider": provider, "tier": route.tier, "why": route.why})
    acked = {"done": False}
    if ack_text:
        emit("ack", db.add_message(bot, "assistant", ack_text, {"ack": True, "tier": route.tier}))
        acked["done"] = True

    def on_tool_start(_calls):  # ack-then-result for tool turns: the first step called a tool
        if not acked["done"]:
            acked["done"] = True
            emit("ack", db.add_message(bot, "assistant", TOOL_ACK, {"ack": True, "tier": route.tier, "tool": True}))

    msgs = _build(history, text, bot, context=tools.context_block(bot))
    info = {}
    try:
        final = agent.run(route, msgs, emit, info=info, ctx={"bot": bot, "user_id": user["id"]},
                          on_tool_start=on_tool_start, max_tokens=MAX_TOKENS)
    finally:
        log_row["tried"] = info.get("tried") or [f"{provider}/{model}"]
        log_row.update(provider=info.get("provider") or provider, model=info.get("model") or model,
                       steps=info.get("steps"), tools=info.get("tools") or [])
        _usage_row(log_row, info.get("usage"), log_row["provider"], log_row["model"])
        if info.get("ttft"):
            log_row["ttft_ms"] = int((info["ttft"] - t0) * 1000)
    out = (final or "").strip()
    approvals = info.get("approvals") or []
    if approvals:  # the exact action, written by code (never the model's description of it)
        card = "\n\n".join(f"Waiting for your OK (expires in 24 h):\n{a['preview']}" for a in approvals)
        add = ("\n\n" if out else "") + card
        emit("delta", {"text": add})
        out += add
    if not out:
        out = "Done." if info.get("tools") and not info.get("error") else "Sorry, that didn't work. Try again?"
        emit("delta", {"text": out})
    rmeta = {"model": log_row["model"], "provider": log_row["provider"], "tier": route.tier,
             "steps": info.get("steps") or 0}
    if info.get("tools"):
        rmeta["tools"] = info["tools"]
    if approvals:
        rmeta["approvals"] = [a["id"] for a in approvals]
        rmeta["actions"] = _approval_actions(approvals)
    if info.get("sources"):
        rmeta["sources"] = info["sources"]
    if info.get("error"):
        rmeta.update(partial=True, error="the model stopped mid-reply")
        log_row["error"] = info["error"]
    reply = db.add_message(bot, "assistant", out, rmeta)
    log_row.update(reply_id=reply["id"], chars_out=len(out), ok=not info.get("error"))
    emit("done", reply)
    return reply


def _chat_worker(bot, text, images, client_id, emit):
    """Runs one chat turn, calling emit(event, data) for
    user, route, [ack], [tool..., approval...], delta..., done | error.
    Think and search turns first get a short templated acknowledgement (its own
    stored Message with meta.ack, no model call); so does a tool turn whose first
    step calls a tool. A message that looks like it needs a tool runs through
    agent.run; quick chat streams straight from the model. The text
    "approve:<id>" / "deny:<id>" (the approval chips) is handled in code, with no
    model. The worker runs to completion even if the client goes away, so the
    reply is stored (and shows up in /api/inbox). Every turn is logged to `turns`."""
    t0 = time.monotonic()
    log_row = {"bot": bot, "chars_in": len(text), "ok": False, "tried": []}
    ttft = None
    replied = False
    try:
        history = db.messages(bot, limit=persona.HISTORY)
        meta = {}
        if client_id:
            meta["client_id"] = str(client_id)[:80]
        if images:
            meta["images"] = len(images)
        user = db.add_message(bot, "user", text, meta)
        log_row["user_id"] = user["id"]
        emit("user", user)
        tap = _APPROVE_TEXT.match(text) if not images else None
        if tap:
            emit("route", {"model": "none", "provider": "theta", "tier": "action", "why": "your tap"})
            res = decide_approval(int(tap.group(2)), tap.group(1).lower(), bot=bot)
            reply = res["message"]
            emit("delta", {"text": reply["text"]})
            log_row.update(tier="action", why="approval tap", reply_id=reply["id"], chars_out=len(reply["text"]),
                           ok=True, steps=0, tools=[])
            emit("done", reply)
            return
        try:
            route = _pick(text, history, [{"type": "image", "data": u} for u in images])
        except models.ModelError as e:
            log_row["error"] = str(e)[:300]
            emit("error", {"error": str(e)})
            return
        log_row.update(tier=route.tier, why=route.why)
        live = bool(os.environ.get("TAVILY_API_KEY"))
        ack_text = persona.ack(route.tier, text, live=live, seed=user["id"])
        if _use_tools(text, images, route):
            try:
                _agent_turn(bot, text, history, user, route, ack_text, emit, log_row, t0)
                replied = True
            except models.ModelError as e:
                log_row["error"] = str(e)[:300]
                emit("error", {"error": f"no model could answer ({str(e)[:160]})"})
            return
        cands = list(route.candidates) or [(route.provider, route.model)]
        last_err = None
        for i, (provider, model) in enumerate(cands):
            why = route.why if i == 0 else f"{route.why}; fallback after: {last_err}"[:200]
            emit("route", {"model": model, "provider": provider, "tier": route.tier, "why": why})
            if i == 0:
                if ack_text:
                    emit("ack", db.add_message(bot, "assistant", ack_text, {"ack": True, "tier": route.tier}))
                extra, sources = None, []
                if route.tier == "search":
                    extra, sources = router.search_context(text)
                if images and route.tier != "vision":  # no model that can see is configured
                    note = "The user attached an image, but no image-capable model is set up, so say you can't see it."
                    extra = f"{extra}\n\n{note}" if extra else note
                msgs = _build(history, text, bot, images=images if route.tier == "vision" else None, extra=extra)
            log_row["tried"].append(f"{provider}/{model}")
            log_row.update(provider=provider, model=model, steps=1)
            cleaner = persona.Cleaner()
            sent = False
            usage = {}
            try:
                for chunk in _stream(provider, model, msgs, usage):
                    if not chunk:
                        continue
                    if ttft is None:
                        ttft = time.monotonic()
                    out = cleaner.feed(chunk)
                    if out:
                        sent = True
                        emit("delta", {"text": out})
                tail = cleaner.finish()
                if tail:
                    sent = True
                    emit("delta", {"text": tail})
            except models.ModelError as e:
                last_err = str(e)[:160]
                log(f"chat: {provider}/{model} failed: {last_err}")
                if not sent:
                    ttft = None
                    continue  # nothing reached the user: try the next candidate
                reply = db.add_message(bot, "assistant", cleaner.text(),
                                       {"model": model, "provider": provider, "tier": route.tier,
                                        "partial": True, "error": "the model stopped mid-reply"})
                log_row.update(reply_id=reply["id"], chars_out=len(reply["text"]), error=last_err)
                _usage_row(log_row, usage, provider, model)
                emit("done", reply)
                return
            full = cleaner.text()
            if not full.strip():
                last_err = f"{provider} sent an empty reply"
                ttft = None
                continue
            rmeta = {"model": model, "provider": provider, "tier": route.tier}
            if sources:
                rmeta["sources"] = sources
            reply = db.add_message(bot, "assistant", full, rmeta)
            log_row.update(reply_id=reply["id"], chars_out=len(full), ok=True)
            _usage_row(log_row, usage, provider, model)
            emit("done", reply)
            replied = True
            return
        log_row["error"] = (last_err or "none available")[:300]
        emit("error", {"error": f"no model could answer ({last_err or 'none available'})"})
    except Exception:
        log("chat worker crashed:\n" + traceback.format_exc())
        log_row["error"] = "internal error"
        emit("error", {"error": "internal error"})
    finally:
        now = time.monotonic()
        log_row["total_ms"] = int((now - t0) * 1000)
        if ttft is not None:
            log_row["ttft_ms"] = int((ttft - t0) * 1000)
        try:
            db.add_turn(**log_row)
        except Exception:
            log("turn log failed:\n" + traceback.format_exc())
        if replied:
            _compact_later(bot)


# ---- approvals (send-risk actions wait for the user's tap) and jobs

_approve_lock = threading.Lock()


def decide_approval(aid, decision, bot=None):
    """Approve or deny a pending action. On approve, runs the stored action exactly as stored
    (tools.run_approved; no model call). Adds an assistant message saying what happened.
    Returns {"ok", "id", "state", "result", "message"}; raises HTTPError 404/400."""
    if decision not in ("approve", "deny"):
        raise HTTPError(400, "decision must be approve or deny")
    ap = db.get_approval(aid) if callable(getattr(db, "get_approval", None)) else None
    if not ap:
        msg = db.add_message(bot or "theta", "assistant", "I can't find that request, so nothing was done.",
                             {"approval": aid, "state": "missing"})
        return {"ok": False, "id": aid, "state": "missing", "result": None, "message": msg, "status": 404}
    action = ap.get("action") or {}
    bot = action.get("bot") if action.get("bot") in BOT_IDS else (bot or "theta")
    result, status = None, 200
    with _approve_lock:
        state = ap["state"]
        expires = float(action.get("expires") or (float(ap.get("t") or 0) + APPROVAL_TTL))
        if state != "pending":
            text = {"done": "That one already went through.", "denied": "That one was already discarded.",
                    "expired": "That request expired, so nothing was sent.",
                    "failed": "That one already failed; ask me again if you still want it."}.get(
                        state, f"That request is already {state}.")
            status = 409
        elif time.time() > expires:
            db.set_approval(aid, "expired", expect="pending")
            state, text = "expired", "That request expired (they last 24 h), so nothing was sent. Ask again if you still want it."
        elif decision == "deny":
            db.set_approval(aid, "denied", expect="pending")
            state, text = "denied", "Discarded. Nothing was sent."
        elif not db.set_approval(aid, "approved", expect="pending"):
            state, text, status = (db.get_approval(aid) or {}).get("state", "unknown"), "That one was already handled.", 409
        else:
            ok, result = tools.run_approved(action)
            state = "done" if ok else "failed"
            db.set_approval(aid, state)
            text = f"Done. {result}" if ok else f"That didn't go through: {result}"
    msg = db.add_message(bot, "assistant", text, {"approval": aid, "state": state, "source": "approval"})
    return {"ok": state in ("done", "denied"), "id": aid, "state": state, "result": result, "message": msg,
            "status": status}


def approve(req, start):
    body = req.json()
    try:
        aid = int(body.get("id"))
    except (TypeError, ValueError):
        raise HTTPError(400, "id (the approval id) is required") from None
    decision = str(body.get("decision") or "").lower()
    res = decide_approval(aid, decision)
    status = res.pop("status", 200)
    return respond_json(start, res, status)


_jobs_lock = threading.Lock()


def _deliver_reminder(job, now):
    p = job.get("payload") or {}
    bot = p.get("bot") if p.get("bot") in BOT_IDS else "theta"
    what = re.sub(r"\s+", " ", str(p.get("text") or "")).strip() or "you asked me to remind you about something"
    text = f"Reminder: {what}"
    if now - float(job.get("due_t") or now) > 600:
        text += f" (this was due {tools.fmt_time(float(job['due_t']), now)})"
    msg = db.add_message(bot, "assistant", text, {"proactive": True, "source": "reminder", "level": 3,
                                                  "job": job["id"]})
    push = _optional("push")
    notify = _first(push, "notify") if push else None
    if notify:
        try:  # the user asked for this one at this time, so quiet hours don't hold it
            notify(title="Theta", body=text[:240], url=f"/?m={msg['id']}", urgent=True)
        except Exception:
            log("reminder push failed:\n" + traceback.format_exc())
    return msg


def run_jobs(now=None):
    """Run every due job once (claimed first, so two ticks can't both run it). Returns the messages sent."""
    fn = getattr(db, "due_jobs", None)
    if not callable(fn):
        return []
    now = now or time.time()
    with _jobs_lock:
        try:
            due = fn(now, claim=True)
        except TypeError:
            due = fn(now)
    sent = []
    for j in due:
        try:
            if j.get("kind") == "remind":
                msg = _deliver_reminder(j, now)
                db.finish_job(j["id"], "done", {"message_id": msg["id"]})
                sent.append(msg)
            else:
                db.finish_job(j["id"], "failed", {"error": f"unknown job kind {j.get('kind')!r}"})
        except Exception as e:
            log(f"job {j.get('id')} failed:\n" + traceback.format_exc())
            try:
                db.finish_job(j["id"], "failed", {"error": f"{type(e).__name__}: {str(e)[:160]}"})
            except Exception:
                pass
    return sent


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def chat(req, start):
    body = req.json()
    bot = body.get("bot") or "theta"
    if bot not in BOT_IDS:
        raise HTTPError(404, "unknown bot")
    text = body.get("text")
    if text is not None and not isinstance(text, str):
        raise HTTPError(400, "text must be a string")
    text = (text or "").strip()
    images = _images(body)
    if not text and not images:
        raise HTTPError(400, "text is required")
    if len(text) > 20000:
        raise HTTPError(413, "message too long")
    client_id = body.get("client_id")

    if req.query.get("stream") == "0":
        got = {}

        def keep(ev, data):
            got[ev] = data
        _chat_worker(bot, text, images, client_id, keep)
        if "done" in got:
            out = {"user": got["user"], "reply": got["done"]}
            if "ack" in got:
                out["ack"] = got["ack"]
            return respond_json(start, out)
        return respond_json(start, {"error": got.get("error", {}).get("error", "no reply"),
                                    "user": got.get("user")}, 502)

    q = queue.Queue()
    threading.Thread(target=_chat_worker, args=(bot, text, images, client_id, lambda e, d: q.put((e, d))),
                     name="chat", daemon=True).start()

    def gen():
        yield b": stream open\n\n"
        while True:
            try:
                ev, data = q.get(timeout=PING_SECONDS)
            except queue.Empty:
                yield b": ping\n\n"
                continue
            yield _sse(ev, data)
            if ev in ("done", "error"):
                return

    start("200 OK", _headers("text/event-stream; charset=utf-8",
                             [("Cache-Control", "no-cache, no-transform"), ("X-Accel-Buffering", "no")]))
    return gen()


# ---- push + settings (push.py is optional)

def _push():
    mod = _optional("push")
    if mod is None:
        raise HTTPError(501, "push isn't installed yet")
    return mod


def push_routes(req, start):
    mod = _push()
    sub = req.path[len("/api/push/"):]
    if sub == "key" and req.method == "GET":
        fn = _first(mod, "public_key", "vapid_public_key", "get_public_key", "key")
        key = fn() if fn else getattr(mod, "VAPID_PUBLIC_KEY", None)
        if not key:
            raise HTTPError(503, "push has no VAPID key configured")
        return respond_json(start, {"key": key})
    if sub == "subscribe" and req.method == "POST":
        s = req.json().get("subscription")
        if not isinstance(s, dict) or not isinstance(s.get("endpoint"), str):
            raise HTTPError(400, "subscription with an endpoint is required")
        fn = _first(mod, "subscribe", "add_subscription")
        res = fn(s) if fn else db.add_push_sub(s)
        if isinstance(res, dict) and res.get("ok") is False:
            raise HTTPError(400, str(res.get("error") or "subscription refused"))
        return respond_json(start, {"ok": True})
    if sub == "test" and req.method == "POST":
        fn = _first(mod, "send_test", "test")
        if fn:
            res = fn()
        else:
            notify = _first(mod, "notify")
            if not notify:
                raise HTTPError(501, "push can't send yet")
            res = notify(title="Theta", body="Test notification from Theta.", url="/")
        out = {"ok": True}
        if isinstance(res, dict):
            out.update(res)
        elif res is not None:
            out["result"] = _jsonable(res)
        return respond_json(start, out)
    raise HTTPError(404 if sub not in ("key", "subscribe", "test") else 405, "not found")


def current_settings():
    out = {}
    for k, d in SETTINGS_DEFAULTS.items():
        v = db.get_setting(k)
        out[k] = d if v is None else v
    return out


def _clean_settings(body):
    out = {}
    if "proactive" in body:
        out["proactive"] = bool(body["proactive"])
    if "quiet" in body:
        q = body["quiet"]
        if q is not None and not (isinstance(q, list) and len(q) == 2 and
                                  all(isinstance(h, int) and not isinstance(h, bool) and 0 <= h <= 23 for h in q)):
            raise HTTPError(400, "quiet must be [start_hour, end_hour] (0-23) or null")
        out["quiet"] = q
    if "tz" in body:
        tz = body["tz"]
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(str(tz))
        except Exception:
            raise HTTPError(400, "unknown time zone") from None
        out["tz"] = str(tz)
    if "loc" in body:
        loc = body["loc"]
        if loc is not None:
            try:
                lat, lon = float(loc["lat"]), float(loc["lon"])
            except (TypeError, KeyError, ValueError):
                raise HTTPError(400, "loc must be {lat, lon} or null") from None
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise HTTPError(400, "loc out of range")
            loc = {"lat": round(lat, 4), "lon": round(lon, 4)}
        out["loc"] = loc
    return out


def settings(req, start):
    mod = _push()
    if req.method == "POST":
        changes = _clean_settings(req.json())
        fn = _first(mod, "set_settings", "save_settings")
        if fn:
            fn(changes)
        else:
            for k, v in changes.items():
                db.set_setting(k, v)
        hook = _first(mod, "settings_changed")
        if hook:
            hook(changes)
    elif req.method != "GET":
        raise HTTPError(405, "method not allowed")
    fn = _first(mod, "get_settings")
    s = current_settings()
    if fn:
        got = fn()
        if isinstance(got, dict):
            s.update(got)
    return respond_json(start, s)


# ---- other API

def connections():
    vantage = bool(os.environ.get("VANTAGE_URL") or os.environ.get("VANTAGE_DIR"))
    return [
        {"id": "gmail", "name": "Gmail", "connected": False, "what": "Search, read, draft and send mail"},
        {"id": "calendar", "name": "Google Calendar", "connected": False, "what": "See and add events, reminders"},
        {"id": "drive", "name": "Google Drive", "connected": False, "what": "Find and read your files"},
        {"id": "vantage", "name": "Vantage", "connected": vantage, "what": "Events near you and in the world"},
        {"id": "search", "name": "Web search", "connected": bool(os.environ.get("TAVILY_API_KEY")),
         "what": "Live facts, news and prices, with sources"},
    ]


def memory_route(req, start):
    mod = _optional("memory")
    if mod is None:
        raise HTTPError(501, "memory isn't installed yet")
    if req.method == "POST":
        body = req.json()
        op = body.get("op")
        if op not in ("add", "replace", "remove"):
            raise HTTPError(400, "op must be add, replace or remove")
        for k in ("text", "old"):
            if body.get(k) is not None and not isinstance(body.get(k), str):
                raise HTTPError(400, f"{k} must be a string")
        res = mod.edit(op, body.get("text") or "", body.get("old"))
        return respond_json(start, {"ok": bool(res.get("ok")), "block": res.get("block", ""),
                                    **({"error": res["error"]} if res.get("error") else {})},
                            200 if res.get("ok") else 400)
    if req.method != "GET":
        raise HTTPError(405, "method not allowed")
    return respond_json(start, {"block": mod.block(), "cap": getattr(mod, "CAP", None)})


def login(req, start):
    body = req.json()
    key = os.environ.get("PROTOS_KEY", "")
    got = body.get("key")
    if not isinstance(got, str):
        raise HTTPError(400, "key is required")
    if key and not hmac.compare_digest(got.encode(), key.encode()):
        time.sleep(0.4)  # slow down guessing
        raise HTTPError(401, "wrong key")
    c = SimpleCookie()
    c["protos_key"] = got if key else ""
    c["protos_key"]["path"] = "/"
    c["protos_key"]["httponly"] = True
    c["protos_key"]["samesite"] = "Lax"
    c["protos_key"]["max-age"] = str(400 * 86400)
    if req.https():
        c["protos_key"]["secure"] = True
    return respond_json(start, {"ok": True, "auth": bool(key)},
                        extra=[("Set-Cookie", c["protos_key"].OutputString())])


def api(req, start):
    p, m = req.path, req.method
    if p == "/api/health":
        return respond_json(start, {"ok": True, "version": __version__})
    if p == "/api/login":
        if m != "POST":
            raise HTTPError(405, "method not allowed")
        return login(req, start)
    if not authed(req):
        raise HTTPError(401, "not signed in")
    if p == "/api/bots" and m == "GET":
        return respond_json(start, BOTS)
    if p == "/api/messages" and m == "GET":
        bot = req.query.get("bot") or "theta"
        msgs = db.messages(bot, before=req.int_arg("before"), limit=req.int_arg("limit", 50, 1, 200))
        return respond_json(start, {"messages": msgs})
    if p == "/api/chat" and m == "POST":
        return chat(req, start)
    if p == "/api/inbox" and m == "GET":
        return respond_json(start, {"messages": db.since(req.int_arg("since", 0, 0), bot=req.query.get("bot") or None,
                                                         limit=200)})
    if p.startswith("/api/push/"):
        return push_routes(req, start)
    if p == "/api/settings":
        return settings(req, start)
    if p == "/api/turns" and m == "GET":
        return respond_json(start, {"turns": db.turns(req.int_arg("limit", 50, 1, 1000))})
    if p == "/api/connections" and m == "GET":
        return respond_json(start, connections())
    if p == "/api/approve" and m == "POST":
        return approve(req, start)
    if p == "/api/memory":
        return memory_route(req, start)
    if p == "/api/plan" and m == "GET":
        bot = req.query.get("bot") or "theta"
        fn = getattr(db, "get_plan", None)
        return respond_json(start, {"plan": fn(bot) if callable(fn) else None})
    if p == "/api/jobs" and m == "GET":
        fn = getattr(db, "jobs", None)
        state = req.query.get("state") or None
        if state is not None and state not in getattr(db, "JOB_STATES", (state,)):
            raise HTTPError(400, "unknown job state")
        return respond_json(start, {"jobs": fn(state, req.int_arg("limit", 50, 1, 500)) if callable(fn) else []})
    if p == "/api/tick" and m == "POST":
        jobs_sent = run_jobs()
        res = run_proactive()
        out = {"ok": True, "jobs": [x["id"] for x in jobs_sent]}
        if isinstance(res, list):
            out["sent"] = [_jsonable(x) for x in res]
        elif isinstance(res, dict):
            out.update({k: _jsonable(v) for k, v in res.items()})
        elif res is not None:
            out["result"] = _jsonable(res)
        return respond_json(start, out)
    known = {"/api/bots", "/api/messages", "/api/chat", "/api/inbox", "/api/connections", "/api/tick", "/api/turns",
             "/api/approve", "/api/plan", "/api/jobs"}
    raise HTTPError(405 if p in known else 404, "method not allowed" if p in known else "not found")


# ---- static (web/)

_PLACEHOLDER = (b"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                b"<title>Theta</title></head><body style='font-family:system-ui;background:#0b0d12;color:#cfd6e4;"
                b"padding:24px'><p>Theta's server is running. The app (web/) isn't built yet.</p></body></html>")


def static(req, start):
    if req.method not in ("GET", "HEAD"):
        raise HTTPError(405, "method not allowed")
    base = os.path.realpath(web_dir())
    p = req.path
    if p in ("/", "/index.html"):
        rel = "index.html"
    elif p in ("/sw.js", "/manifest.webmanifest", "/favicon.ico", "/robots.txt"):
        rel = p[1:]
    elif p.startswith("/static/"):
        rel = urllib.parse.unquote(p[len("/static/"):])
    elif p.startswith("/icons/"):
        rel = urllib.parse.unquote(p[1:])
    else:
        raise HTTPError(404, "not found")
    full = os.path.realpath(os.path.join(base, rel))
    if not (full == base or full.startswith(base + os.sep)) or "\x00" in rel:
        raise HTTPError(404, "not found")
    if not os.path.isfile(full):
        if rel == "index.html":
            start("200 OK", _headers("text/html; charset=utf-8", [("Content-Length", str(len(_PLACEHOLDER)))]))
            return [_PLACEHOLDER] if req.method == "GET" else [b""]
        raise HTTPError(404, "not found")
    with open(full, "rb") as f:
        data = f.read()
    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/json", "application/manifest+json", "image/svg+xml"):
        ctype += "; charset=utf-8"
    extra = [("Content-Length", str(len(data))), ("Cache-Control", "no-cache")]
    if rel == "sw.js":
        extra.append(("Service-Worker-Allowed", "/"))
    start("200 OK", _headers(ctype, extra))
    return [data] if req.method == "GET" else [b""]


# ---- the WSGI app

def app(environ, start_response):
    req = Req(environ)
    try:
        if req.path.startswith("/api/"):
            return api(req, start_response)
        return static(req, start_response)
    except HTTPError as e:
        return respond_json(start_response, {"error": e.message}, e.status)
    except Exception:
        log(f"{req.method} {req.path} failed:\n" + traceback.format_exc())
        return respond_json(start_response, {"error": "internal error"}, 500)


application = app  # for WSGI servers that look for `application`


# ---- background tick + dev server

_ticker_started = False


def start_ticker(interval=TICK_SECONDS, first=20):
    """Run due jobs every JOB_SECONDS and proactive.run() every `interval` seconds (unless PROTOS_TICK=0)."""
    global _ticker_started
    if _ticker_started or os.environ.get("PROTOS_TICK", "1") == "0":
        return None
    _ticker_started = True

    def loop():
        time.sleep(min(first, JOB_SECONDS))
        next_pro = time.monotonic() + max(0, first - JOB_SECONDS)
        while True:
            try:
                run_jobs()
            except Exception:
                log("jobs tick failed:\n" + traceback.format_exc())
            if time.monotonic() >= next_pro:
                next_pro = time.monotonic() + interval
                try:
                    run_proactive()
                except HTTPError:
                    pass  # proactive.py not there yet
                except Exception:
                    log("proactive tick failed:\n" + traceback.format_exc())
            time.sleep(min(JOB_SECONDS, interval))
    t = threading.Thread(target=loop, name="proactive-tick", daemon=True)
    t.start()
    return t


class ThreadingWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        if os.environ.get("PROTOS_QUIET") != "1":
            sys.stderr.write("[http] %s %s\n" % (self.address_string(), fmt % args))


def make(host="0.0.0.0", port=8780):
    return make_server(host, port, app, server_class=ThreadingWSGIServer, handler_class=QuietHandler)


def serve():
    db.init()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8780"))
    if not os.environ.get("PROTOS_KEY"):
        log("WARNING: PROTOS_KEY is not set, so the API has no auth. Local dev only.")
    avail = models.available()
    log(f"models available: {', '.join(avail) or 'none (set DEEPSEEK_API_KEY or another key)'}")
    start_ticker()
    httpd = make(host, port)
    log(f"theta-protos {__version__} on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
