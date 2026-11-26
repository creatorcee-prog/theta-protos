"""Settings > General > Models: which models Theta can use right now, and a check that each one really answers.

    GET  /api/models/status   {providers: [{id, name, key}], tiers: [{tier, what, models: [{provider, model}]}],
                               search: bool}  (from the keys present; no calls made)
    POST /api/models/check    sends each usable model a one-word prompt in parallel (and one web search when
                               TAVILY_API_KEY is set): {results: [{provider, model, tiers, ok, ms, error}]}

Errors are shortened to the provider's own reason ("model not found", "invalid key", "quota"), never key material.
"""
import os
import re
import threading
import time

NAMES = {"deepseek": "DeepSeek", "anthropic": "Anthropic (Claude)", "gemini": "Google Gemini", "groq": "Groq",
         "local": "Local model"}
WHAT = {"quick": "everyday chat and tool use", "think": "decisions and planning", "code": "code and errors",
        "search": "live facts (with web results)", "vision": "photos you send", "local": "private, on your own box"}
LIMIT = 25


def status():
    from . import models, router
    have = set(models.available())
    providers = [{"id": p, "name": NAMES.get(p, p), "key": p in have} for p in models.PROVIDERS]
    tiers = [{"tier": t, "what": WHAT.get(t, ""), "models": [{"provider": p, "model": m} for p, m in router.candidates(t)]}
             for t in router.TIERS]
    return {"providers": providers, "tiers": tiers, "search": bool((os.environ.get("TAVILY_API_KEY") or "").strip())}


def _short(err):
    t = re.sub(r"\s+", " ", str(err or "")).strip()
    t = re.sub(r"(sk|key|Bearer)[-_A-Za-z0-9]{8,}", "[key]", t)
    for pat, say in ((r"40[13]|unauthori|invalid.{0,12}key|api key", "the key was refused (check it on Railway)"),
                     (r"404|not.found|does not exist|unknown model|model_not_found", "this model name isn't available to your key"),
                     (r"429|quota|rate.?limit|exceeded|billing|credit", "out of quota or rate-limited (check billing)"),
                     (r"timed? ?out|timeout", "it didn't answer in time")):
        if re.search(pat, t, re.I):
            return say + f" ({t[:90]})"
    return t[:160] or "no answer"


def _one(provider, model, out):
    from . import models
    t0 = time.monotonic()
    try:
        # room to think: reasoning models spend their first tokens thinking before they answer
        text = models.complete(provider, model, [{"role": "user", "content": "Reply with the single word OK."}], max_tokens=300)
        ok = bool((text or "").strip())
        out.update(ok=ok, ms=int((time.monotonic() - t0) * 1000), error="" if ok else "it answered with nothing")
    except Exception as e:  # noqa: BLE001
        out.update(ok=False, ms=int((time.monotonic() - t0) * 1000), error=_short(e))


# ---------------------------------------------------------------- a model name that doesn't exist: find one that does

def _get_json(url, headers):
    import json
    import urllib.request
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read(2_000_000).decode())


def listed(provider):
    """The model ids this key can use, from the provider's own list (empty if it can't be read)."""
    key = (os.environ.get({"deepseek": "DEEPSEEK_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY",
                           "groq": "GROQ_API_KEY"}.get(provider, "") or "") or "").strip()
    if not key:
        return []
    try:
        if provider == "gemini":
            j = _get_json(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=200", {})
            return [m["name"].split("/", 1)[-1] for m in j.get("models") or []
                    if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        if provider == "anthropic":
            j = _get_json("https://api.anthropic.com/v1/models?limit=100", {"x-api-key": key, "anthropic-version": "2023-06-01"})
            return [m["id"] for m in j.get("data") or []]
        base = {"deepseek": "https://api.deepseek.com/models", "groq": "https://api.groq.com/openai/v1/models"}[provider]
        j = _get_json(base, {"Authorization": "Bearer " + key})
        return [m["id"] for m in j.get("data") or []]
    except Exception:  # noqa: BLE001
        return []


FAMILIES = ("flash-lite", "flash", "pro", "haiku", "sonnet", "opus", "reasoner", "chat", "llama", "gpt-oss", "70b", "8b")


def suggest(provider, missing, available):
    """The closest available model to a missing one: same family word, newest-looking first."""
    fam = next((f for f in FAMILIES if f in missing.lower()), None)
    pool = [m for m in available if fam and fam in m.lower() and not re.search(r"(?i)embed|tts|image|audio|vision-only|guard", m)]
    if fam == "flash":
        pool = [m for m in pool if "flash-lite" not in m.lower()] or pool
    if not pool:
        return None
    def ver(m):
        nums = [int(x) for x in re.findall(r"\d+", m)]
        return (nums, "preview" not in m.lower() and "exp" not in m.lower())
    return sorted(pool, key=lambda m: (ver(m)[1], ver(m)[0]), reverse=True)[0]


def _repair(row):
    """For a model name the key can't use: find, test and keep a replacement. Updates the row."""
    from . import db
    if row["ok"] or "isn't available" not in (row.get("error") or ""):
        return
    pick = suggest(row["provider"], row["model"], listed(row["provider"]))
    if not pick:
        row["error"] += ". No close replacement was found in your account's model list."
        return
    trial = {}
    _one(row["provider"], pick, trial)
    if not trial.get("ok"):
        row["error"] += f". Tried {pick} instead, but it didn't answer either."
        return
    fixes = db.get_setting("model_fixes") or {}
    fixes[f"{row['provider']}:{row['model']}"] = pick
    db.set_setting("model_fixes", fixes)
    row.update(ok=True, ms=trial.get("ms"), fixed=pick,
               error="", note=f"{row['model']} doesn't exist for your key, so Theta now uses {pick} (it answered).")


def check():
    from . import router
    st = status()
    seen = {}
    for t in st["tiers"]:
        for m in t["models"]:
            key = (m["provider"], m["model"])
            seen.setdefault(key, {"provider": m["provider"], "model": m["model"], "tiers": [], "ok": None, "ms": None, "error": ""})
            seen[key]["tiers"].append(t["tier"])
    threads = []
    for key, row in seen.items():
        th = threading.Thread(target=_one, args=(key[0], key[1], row), daemon=True)
        th.start(); threads.append(th)
    search = None
    if st["search"]:
        search = {"provider": "tavily", "model": "web search", "tiers": ["search"], "ok": None, "ms": None, "error": ""}

        def s():
            t0 = time.monotonic()
            try:
                ctx = router.search_context("weather in Denver today", max_results=1)
                search.update(ok=bool(ctx), ms=int((time.monotonic() - t0) * 1000), error="" if ctx else "no results came back")
            except Exception as e:  # noqa: BLE001
                search.update(ok=False, ms=int((time.monotonic() - t0) * 1000), error=_short(e))
        th = threading.Thread(target=s, daemon=True)
        th.start(); threads.append(th)
    deadline = time.monotonic() + LIMIT
    for th in threads:
        th.join(max(0.0, deadline - time.monotonic()))
    rows = list(seen.values()) + ([search] if search else [])
    for r in rows:
        if r["ok"] is None:
            r.update(ok=False, error="it didn't answer in time")
    for r in rows:
        if r["provider"] != "tavily":
            _repair(r)
    return {"results": rows, "status": status()}


def route_status(req, start_response):
    from .app import HTTPError, respond_json
    if req.method != "GET":
        raise HTTPError(405, "method not allowed")
    return respond_json(start_response, status())


def route_check(req, start_response):
    from .app import HTTPError, respond_json
    if req.method != "POST":
        raise HTTPError(405, "method not allowed")
    return respond_json(start_response, check())


ROUTES = {"/api/models/status": route_status, "/api/models/check": route_check}
