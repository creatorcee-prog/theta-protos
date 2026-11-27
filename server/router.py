"""Picks the model for each message ("picks the model, answers the same").

    pick(text, history=(), attachments=(), last=None) -> Route(tier, model, provider, why, candidates, t)

1. Fast heuristics (regexes + length) decide most messages with no model call.
2. Only ambiguous ones go to a tiny classifier call on the quick model
   (`CLASSIFIER`; set it to None to turn it off, e.g. in tests, or
   PROTOS_CLASSIFIER=0).
3. Each tier has a candidate list filtered by models.available(); an empty
   tier falls back to quick. `Route.candidates` is the ordered fallback list
   the chat handler walks when a provider errors before any text was sent.

PROTOS_LOCAL_FIRST=1 puts the local model first in every tier.

Stickiness (docs/HARNESS.md P5): provider caches are per model, so with
`last` (the previous turn's route) less than STICKY_SECONDS old, a turn whose
tier is "close enough" reuses that model. Only a real tier change switches:
quick <-> think <-> code, an image (vision), live facts (search), private (local).
A weak decision (a heuristic default or the classifier) after a think/code
turn keeps that tier. `last` may be a Route, a stored assistant Message
({"meta": {tier, provider, model}, "t"}), a turns row, or a dict with
tier/provider/model/t; last_route(history) finds one in the history.

Search tier: `search_context(text)` calls Tavily when TAVILY_API_KEY is set and
returns a context block with numbered sources for the system prompt.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import NamedTuple

from . import models

TIERS = ("quick", "think", "code", "search", "vision", "local")


class Route(NamedTuple):
    tier: str
    model: str
    provider: str
    why: str
    candidates: tuple = ()  # ((provider, model), ...) in try order, starting with this one
    t: float = 0.0          # unix time it was picked (for stickiness on the next turn)


def _m(provider, env=None, default=None):
    def get():
        name = (os.environ.get(env) if env else None) or default or models.default_model(provider)
        return fixed(provider, name)
    return provider, get


def fixed(provider, name):
    """A model name the check found missing for this key gets the working replacement it chose
    (server/modelcheck.py, the "model_fixes" setting). A name set in the env is left as the user wrote it only
    when it works; a missing one is replaced the same way."""
    try:
        from . import db
        fixes = db.get_setting("model_fixes") or {}
        return fixes.get(f"{provider}:{name}") or name
    except Exception:  # noqa: BLE001
        return name


# Per-tier candidates, best first. Models are resolved at call time so env
# overrides (ANTHROPIC_MODEL, GEMINI_MODEL, ...) apply without a restart.
TIER_CANDIDATES = {
    "quick": [_m("deepseek", None, "deepseek-chat"),
              _m("groq"),
              _m("gemini"),
              _m("anthropic", "ANTHROPIC_QUICK_MODEL", "claude-haiku-5-5"),
              _m("local")],
    "think": [_m("deepseek", None, "deepseek-reasoner"),
              _m("anthropic"),
              _m("gemini", "GEMINI_THINK_MODEL"),
              _m("groq", "GROQ_THINK_MODEL", "openai/gpt-oss-120b")],
    "code": [_m("anthropic"),
             _m("deepseek", None, "deepseek-chat"),
             _m("gemini", "GEMINI_THINK_MODEL"),
             _m("groq", "GROQ_THINK_MODEL", "openai/gpt-oss-120b")],
    "search": [],  # the quick list (plus web results in the prompt)
    "vision": [_m("gemini"),
               _m("anthropic")],
    "local": [_m("local")],
}

WHY = {"quick": "short chat", "think": "needs reasoning", "code": "code or errors",
       "search": "live facts", "vision": "image attached", "local": "private"}

# ---- heuristics

_CODE = re.compile(
    r"```|Traceback \(most recent call last\)|\bstack ?trace\b|\b[A-Z][a-zA-Z]+(Error|Exception)\b"
    r"|\bsegfault\b|\bnull pointer\b|\bundefined is not\b|\bsyntax error\b|^\s*(def|class|import|from \S+ import|"
    r"function|const|let|var|public|private|#include|SELECT|INSERT|UPDATE)\b|=>|;\s*$|\{\s*$"
    r"|\b(python|javascript|typescript|bash|regex|sql|json|yaml|dockerfile|kotlin|rust|golang|java|c\+\+|html|css)\b"
    r"|\b(compile|compiler|debug|refactor|function|variable|npm|pip install|git (push|pull|merge|rebase)|api endpoint)\b",
    re.I | re.M)
_SEARCH = re.compile(
    r"\b(?:today(?!\s+(?:was|has|had|went|felt|sucked|i\b|i'm|i've|we\b|is (?:a|so|been)\b)))\b"
    r"|\b(news|headlines?|latest|today's|tonight|this (week|morning|weekend)|right now|currently|current(ly)?"
    r"|price of|stock price|stock market|bitcoin|btc|exchange rate|weather|forecast|score|who won|election"
    r"|open now|hours for|traffic|release date|just (happened|announced)|breaking)\b"
    r"|\b(20[2-9]\d)\b", re.I)
_THINK = re.compile(
    r"\b(why|compare|comparison|versus|vs\.?|should i|pros and cons|trade-?offs?|plan|planning|strategy"
    r"|step[- ]by[- ]step|explain how|how does|analy[sz]e|prove|derive|calculate|solve|estimate"
    r"|budget|decide|decision|which is better|what if|figure out)\b"
    r"|\d+\s*[-+*/^%]\s*\d+", re.I)
_QUICK = re.compile(
    r"^\s*(hi|hey|hello|yo|sup|morning|good (morning|night|evening)|thanks|thank you|thx|ok(ay)?|cool|nice"
    r"|lol|haha|yes|no|yep|nope|sure|got it|bye|night|gm|gn|how are you|how's it going|what's up|wyd)\b", re.I)
_CLOCK = re.compile(  # the time/date is in every turn's context block: no live search needed
    r"^\s*(?:what(?:'s| is)? (?:the )?(?:time|date|day)(?: is it)?(?: (?:today|now|right now))?"
    r"|what day is (?:it|today)(?: today)?|what's today's date|what is today's date|what's the date today)\s*[?.!]*\s*$",
    re.I)
_PRIVATE = re.compile(
    r"\b(password|passcode|ssn|social security|bank account|routing number|credit card|pin code|diagnos(is|ed)"
    r"|my therapist|medical record|private|confidential|off the record)\b", re.I)


def _signals(text):
    s = set()
    if _CODE.search(text):
        s.add("code")
    if _SEARCH.search(text):
        s.add("search")
    if _THINK.search(text):
        s.add("think")
    return s


def _local_first():
    return os.environ.get("PROTOS_LOCAL_FIRST", "").strip() in ("1", "true", "yes", "on")


def candidates(tier):
    """(provider, model) pairs for `tier` with keys, in try order, ending with
    the quick tier as the fallback."""
    avail = set(models.available())
    order = list(TIER_CANDIDATES.get(tier) or [])
    if tier == "search":
        order = []
    if tier not in ("quick", "search", "local", "vision"):  # vision can't fall back to a blind model
        order = order + [c for c in TIER_CANDIDATES["quick"] if c not in order]
    elif tier in ("quick", "search"):
        order = list(TIER_CANDIDATES["quick"])
    if _local_first() and tier != "local":
        order = TIER_CANDIDATES["local"] + [c for c in order if c[0] != "local"]
    out = []
    for provider, get in order:
        if provider in avail:
            pair = (provider, get())
            if pair not in out:
                out.append(pair)
    if not out and tier == "local":
        return candidates("quick")
    return out


def _classify_with_model(text):
    """Tiny classifier on the quick model: one word back."""
    cands = candidates("quick")
    if not cands:
        return None
    provider, model = cands[0]
    prompt = [{"role": "system", "content": "Classify the user's message for routing. Answer with ONE word: "
                                            "quick (chat, simple fact), think (reasoning, planning, math, advice), "
                                            "code (programming), or search (needs live/current info)."},
              {"role": "user", "content": text[:1500]}]
    try:
        word = models.complete(provider, model, prompt, max_tokens=5).strip().lower()
    except models.ModelError:
        return None
    m = re.search(r"quick|think|code|search", word)
    return m.group(0) if m else None


# Injectable: a callable text -> tier|None, or None to skip the model call.
CLASSIFIER = None if os.environ.get("PROTOS_CLASSIFIER", "1") == "0" else _classify_with_model


def _has_image(attachments):
    for a in attachments or ():
        if isinstance(a, dict):
            kind = str(a.get("type") or a.get("mime") or "")
            url = str(a.get("url") or a.get("data") or "")
            if kind.startswith("image") or url.startswith("data:image"):
                return True
        elif isinstance(a, str) and a.startswith("data:image"):
            return True
    return False


def decide(text, history=(), attachments=()):
    """(tier, why) from heuristics, then the classifier if still ambiguous."""
    text = (text or "").strip()
    if _has_image(attachments):
        return "vision", WHY["vision"]
    if _PRIVATE.search(text) and "local" in models.available():
        return "local", "private, kept on your machine"
    if _CLOCK.match(text):
        return "quick", "time or date (already in context)"
    sig = _signals(text)
    n = len(text)
    if "code" in sig:
        return "code", WHY["code"]
    if len(sig) == 1:
        tier = next(iter(sig))
        if n < 40 and _QUICK.match(text):
            return "quick", WHY["quick"]
        return tier, WHY[tier]
    if not sig:
        if n <= 80 or _QUICK.match(text):
            last = next((m for m in reversed(list(history or ())) if isinstance(m, dict)
                         and m.get("role") == "assistant"), None)
            prev = ((last or {}).get("meta") or {}).get("tier")
            if prev in ("code", "think") and n <= 80 and not _QUICK.match(text):
                return prev, "follow-up"
            return "quick", WHY["quick"]
        if n > 600:
            return "think", "long message"
    # ambiguous: several signals, or medium length with none
    if CLASSIFIER is not None:
        try:
            got = CLASSIFIER(text)
        except Exception:
            got = None
        if got in ("quick", "think", "code", "search"):
            return got, f"classifier: {WHY[got]}"
    if "search" in sig:
        return "search", WHY["search"]
    if "think" in sig:
        return "think", WHY["think"]
    return "quick", "default chat"


STICKY_SECONDS = 600
_WEAK = ("default chat", "classifier", "follow-up")  # decisions too soft to justify a model switch


def _as_last(last):
    """(tier, provider, model, t) from a Route / Message / turn row / dict, or None."""
    if last is None:
        return None
    if isinstance(last, Route):
        return last.tier, last.provider, last.model, float(last.t or 0)
    if isinstance(last, dict):
        meta = last.get("meta") if isinstance(last.get("meta"), dict) else {}
        tier = meta.get("tier") or last.get("tier")
        provider = meta.get("provider") or last.get("provider")
        model = meta.get("model") or last.get("model")
        try:
            t = float(last.get("t") or meta.get("t") or 0)
        except (TypeError, ValueError):
            t = 0.0
        if tier and provider and model:
            return str(tier), str(provider), str(model), t
    return None


def last_route(history):
    """The newest assistant reply in `history` that records a route (skips acks
    and proactive messages), as a dict for pick(last=...); None if there is none."""
    for m in reversed(list(history or ())):
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        meta = m.get("meta") or {}
        if meta.get("ack") or meta.get("proactive"):
            continue
        if meta.get("tier") and meta.get("provider") and meta.get("model"):
            return {"tier": meta["tier"], "provider": meta["provider"], "model": meta["model"], "t": m.get("t") or 0}
        return None
    return None


def _sticky(tier, why, last, now):
    """The (tier, why) to use given the previous route, or None to keep the fresh decision."""
    lt, lp, lm, t = last
    if not t or now - t > STICKY_SECONDS or now < t - 60:
        return None
    if lt == tier:
        return tier, why
    weak = any(why.startswith(w) for w in _WEAK)
    if weak and lt in ("think", "code") and tier == "quick":
        return lt, f"{why}; sticky {lt}"
    return None


def pick(text, history=(), attachments=(), last=None, now=None):
    """Route for this message. Raises models.ModelError if no provider is configured.
    `last`: the previous turn's route (see the module doc); within STICKY_SECONDS
    and a close-enough tier, its model goes first so the provider cache stays warm."""
    now = time.time() if now is None else float(now)
    tier, why = decide(text, history, attachments)
    if tier == "local" and "local" not in models.available():
        tier, why = "quick", WHY["quick"]
    prev = _as_last(last)
    stuck = _sticky(tier, why, prev, now) if prev else None
    if stuck:
        tier, why = stuck
    cands = candidates(tier)
    if not cands and tier != "quick":
        why = f"{why}; no {tier} model, using quick"
        tier = "quick"
        cands = candidates("quick")
        stuck = None
    if not cands:
        raise models.ModelError("no model provider is configured (set DEEPSEEK_API_KEY or another key)",
                                retryable=False)
    if stuck and prev and (prev[1], prev[2]) in cands and cands[0] != (prev[1], prev[2]):
        pair = (prev[1], prev[2])
        cands = [pair] + [c for c in cands if c != pair]
        why = f"{why}; sticky model"
    provider, model = cands[0]
    return Route(tier=tier, model=model, provider=provider, why=why, candidates=tuple(cands), t=now)


# ---- web search for the search tier

NO_LIVE = ("Live search isn't available right now. Answer from what you know, and say briefly that "
           "you couldn't check live sources, so the user knows it may be out of date.")
RESULTS_HEAD = ("Live web results (fetched just now). Use them, and cite each one you use as [n] right after the "
                "claim it supports (the app turns [n] into a link). No list of links at the end. Don't invent sources "
                "beyond these.")


def search_context(text, max_results=5, timeout=12):
    """Live results as a prompt block: Tavily, or when it isn't set up or fails, a search in Theta's own browser.
    Returns (block, sources) where sources is [{"title", "url"}]; (NO_LIVE, []) when neither works."""
    block, sources = _tavily(text, max_results, timeout)
    if sources:
        return block, sources
    return _browser_search(text, max_results)


def search_live():
    """True when some live search can run (a Tavily key, or Theta's browser)."""
    if (os.environ.get("TAVILY_API_KEY") or "").strip():
        return True
    try:
        from . import browser
        return browser.available()
    except Exception:  # noqa: BLE001
        return False


def _browser_search(text, max_results):
    try:
        from . import browser
        rows = browser.web_results(text, max_results)
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return NO_LIVE, []
    lines, sources = [RESULTS_HEAD], []
    for i, x in enumerate(rows, 1):
        lines.append(f"[{i}] {x['title'] or x['url']} ({x['url']})\n{x.get('snippet') or ''}")
        sources.append({"title": x["title"] or x["url"], "url": x["url"]})
    return "\n\n".join(lines), sources


def _tavily(text, max_results=5, timeout=12):
    key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    no_live = NO_LIVE
    if not key:
        return no_live, []
    body = json.dumps({"api_key": key, "query": text[:400], "max_results": max_results,
                       "search_depth": "basic", "include_answer": False}).encode()
    req = urllib.request.Request("https://api.tavily.com/search", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                          "User-Agent": models.UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return no_live, []
    results = [x for x in (data.get("results") or []) if isinstance(x, dict) and x.get("url")][:max_results]
    if not results:
        return no_live, []
    lines = [RESULTS_HEAD]
    sources = []
    for i, x in enumerate(results, 1):
        title = (x.get("title") or x["url"]).strip()
        snippet = re.sub(r"\s+", " ", x.get("content") or "").strip()[:500]
        lines.append(f"[{i}] {title} ({x['url']})\n{snippet}")
        sources.append({"title": title, "url": x["url"]})
    return "\n\n".join(lines), sources
