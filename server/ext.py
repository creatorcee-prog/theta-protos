"""Features as plug-ins. Each feature is one module in server/ listed in FEATURES. It may define any of:

    TOOLS = [tool, ...]            same shape as tools.TOOLS: name, risk ("read"|"write"|"send"), description,
                                   params, run(args, ctx), optional preview(args) for "send" tools, optional
                                   untrusted=True when its output is outside text (web, email, files)
    RELEVANT = r"regex"            words that mean a message probably needs one of its tools
    ROUTES = {"/api/x": fn}        fn(req, start) -> WSGI body; exact path, or a prefix ending in "/"
                                   (signed-in callers only)
    PUBLIC_ROUTES = {...}          same, but reachable without signing in. The handler MUST verify the caller
                                   itself (an OAuth state, a webhook signature).
    JOB_KINDS = {"kind": fn}       fn(job, now) -> a sent Message or None; runs due jobs of that kind (db.add_job)
    def tick(now) -> list          runs every ~30 s with the jobs; returns messages it sent (may be [])
    def connections() -> list      [{id, name, connected, what, ...}] merged into /api/connections by id
    def context(bot, now) -> str   a short line or two for the per-turn context block ("" for nothing)
    def intercept(bot, text, user_msg) -> list | None   claims a chat message before the model sees it
                                   (the intro's typed answers); returns the assistant messages it sent

A feature that is missing, or fails to import, is skipped with one log line; the rest of Theta is unaffected.
"""
import importlib
import re
import sys
import threading

FEATURES = ("google", "gcal", "routines", "workflows", "subagents", "media", "browser", "calls", "passkeys")
FEATURES += ("reactions", "uploads", "gifs")  # stage 5, builder A: tapbacks, photos, GIFs
FEATURES += ("live",)  # Theta's screen: watch its browser work and take over (server/live.py)
FEATURES += ("account", "chips", "files", "runtime", "home", "chiphub", "drivesync", "progress")  # Settings: profile, personalization, storage and backups; chips (skills)
FEATURES += ("cards",)  # the card kit, connect cards, weather
FEATURES += ("onboarding",)  # the first-run intro, in the chat
FEATURES += ("contacts", "texts", "resume", "gactions", "gdrive", "approvals", "recordings", "modelcheck", "bank", "vault")  # saved contacts, texting, picking requests back up once connected

_lock = threading.Lock()
_mods = None
_errors = {}


def modules():
    global _mods
    if _mods is not None:
        return _mods
    with _lock:
        if _mods is None:
            out = []
            for name in FEATURES:
                try:
                    out.append(importlib.import_module(f"{__package__}.{name}"))
                except ModuleNotFoundError as e:
                    if e.name != f"{__package__}.{name}":
                        _errors[name] = f"{type(e).__name__}: {e}"
                        print(f"[protos] feature {name} failed to load: {e}", file=sys.stderr, flush=True)
                except Exception as e:  # noqa: BLE001  one broken feature never takes Theta down
                    _errors[name] = f"{type(e).__name__}: {e}"
                    print(f"[protos] feature {name} failed to load: {e!r}", file=sys.stderr, flush=True)
            _mods = out
    return _mods


def reset():
    """Forget loaded features (tests)."""
    global _mods
    with _lock:
        _mods = None
        _errors.clear()


def errors():
    return dict(_errors)


def tools():
    out = []
    for m in modules():
        out.extend(getattr(m, "TOOLS", None) or [])
    return out


def relevant_tools(text):
    """Names of the tools whose feature's RELEVANT words appear in text (for loading just those)."""
    out = []
    for m in modules():
        pat = getattr(m, "RELEVANT", None)
        if pat and re.search(pat, text or "", re.I):
            out += [t["name"] for t in getattr(m, "TOOLS", None) or []]
    return out


def relevant(text):
    for m in modules():
        pat = getattr(m, "RELEVANT", None)
        if pat and re.search(pat, text or "", re.I):
            return True
    return False


def _match(table, path):
    if not table:
        return None
    if path in table:
        return table[path]
    best = None
    for k, fn in table.items():
        if k.endswith("/") and path.startswith(k) and (best is None or len(k) > len(best[0])):
            best = (k, fn)
    return best[1] if best else None


def route(path, public=False):
    """The handler for this path from any feature, or None."""
    for m in modules():
        fn = _match(getattr(m, "PUBLIC_ROUTES" if public else "ROUTES", None), path)
        if fn:
            return fn
    return None


def job_handler(kind):
    for m in modules():
        fn = (getattr(m, "JOB_KINDS", None) or {}).get(kind)
        if fn:
            return fn
    return None


def tick(now):
    sent = []
    for m in modules():
        fn = getattr(m, "tick", None)
        if callable(fn):
            try:
                sent.extend(fn(now) or [])
            except Exception as e:  # noqa: BLE001
                print(f"[protos] {m.__name__}.tick failed: {e!r}", file=sys.stderr, flush=True)
    return sent


def connections(base):
    by_id = {c["id"]: dict(c) for c in base}
    order = [c["id"] for c in base]
    for m in modules():
        fn = getattr(m, "connections", None)
        if not callable(fn):
            continue
        try:
            for c in fn() or []:
                if c.get("id") not in by_id:
                    order.append(c["id"])
                by_id[c["id"]] = {**by_id.get(c["id"], {}), **c}
        except Exception as e:  # noqa: BLE001
            print(f"[protos] {m.__name__}.connections failed: {e!r}", file=sys.stderr, flush=True)
    return [by_id[i] for i in order]


def intercept(bot, text, user_msg):
    """The first feature that claims this chat message: its messages, or None (the model handles it)."""
    for m in modules():
        fn = getattr(m, "intercept", None)
        if not callable(fn):
            continue
        try:
            out = fn(bot, text, user_msg)
        except Exception as e:  # noqa: BLE001
            print(f"[protos] {m.__name__}.intercept failed: {e!r}", file=sys.stderr, flush=True)
            continue
        if out:
            return out
    return None


def context(bot, now):
    lines = []
    for m in modules():
        fn = getattr(m, "context", None)
        if callable(fn):
            try:
                s = fn(bot, now)
                if s:
                    lines.append(str(s).strip())
            except Exception:  # noqa: BLE001
                pass
    return "\n".join(lines)
