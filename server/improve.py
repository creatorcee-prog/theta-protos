"""Theta's self-improvement log: did each lesson it taught itself actually help?

After "Self-Improvement Memory Enables Continual Recursive Self-Improvement" (Yu et al., arXiv 2611.18856, Nov 2026):
an improver does better when it keeps a structured memory of its own edits (the root cause, the edit and why, the
outcome it predicted before the change, the outcome observed after, and where it happened), groups edits by root
cause, keeps regressions instead of dropping them, and carries the memory across a change of model.

Theta's "edits" are its lessons (persona.lessons(): short rules made from your likes and dislikes, added to its
instructions). For each lesson this log keeps, in the "sim" setting:

    cause      the lesson's key (a dislike reason or a liked style): the root cause the edit answers
    edits      [{text, t, model, predicted, base: {rated, hits}, observed?: {rated, hits, verdict}}], appended, never
               rewritten; a lesson that comes back after a change is a new edit under the same cause
    status     "early" (fewer than CHECK_AFTER newer rated replies), "helping", "not helping", or "recheck" (made
               with another model than the one answering now)

check() compares how often the cause came back (dislikes with that reason) among replies rated after the edit with
the rate before it. prompt_notes() turns the verdicts into the instructions: a lesson that isn't helping is stated
more strictly. The log is shown under Settings > General > What Theta learned.
"""
import time

from . import db

KEY = "sim"
CHECK_AFTER = 8       # newer rated replies before a verdict
MIN_BASE = 3          # rated replies before the edit, for a baseline


def _load():
    v = db.get_setting(KEY)
    return v if isinstance(v, dict) else {}


def _current_model():
    try:
        r = db._conn().execute("SELECT model FROM turns WHERE model IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        return (r["model"] if r else "") or ""
    except Exception:  # noqa: BLE001
        return ""


def _family(model):
    """deepseek-chat and deepseek-reasoner are one family (the router moves between them every few messages); a
    lesson needs a re-check only when another family (Claude, Gemini...) takes over."""
    import re
    return re.split(r"[-/:._]", str(model or "").lower().split("/")[-1])[0]


# the kind of task a reply was, from the tools it used and the route it took (the paper's "where it happened")
DOMAINS = [
    ("coding", ("code",), ()),
    ("email", (), ("gmail_", "send_email")),
    ("calendar & planning", (), ("calendar_", "plan_update", "remind_me", "routine_", "workflow_")),
    ("research & web", ("search",), ("web_search", "research", "browse_", "vantage_", "weather")),
    ("files & docs", (), ("drive_", "docs_", "slides_", "file_read")),
    ("money", (), ("bank_",)),
    ("texts & calls", (), ("send_text", "call_")),
    ("memory & contacts", (), ("memory_edit", "find_contact", "save_contact", "history_search")),
]


def domain_of(meta):
    meta = meta or {}
    tools, tier = meta.get("tools") or [], meta.get("tier")
    for name, tiers, prefixes in DOMAINS:
        if tier in tiers or any(str(t).startswith(prefixes) for t in tools if prefixes):
            return name
    return "conversation"


def _evidence(rows, cause, after=None, before=None, last=None):
    """[{t, hit, model, domain}]: replies with evidence in the window, oldest first. Evidence is the user's ratings
    plus Theta's own reviews (server/selfcheck.py) of every reply; on a reply the user rated, their word wins (a
    dislike for this cause is a hit, a like is not)."""
    key = cause.split(":", 1)[1] if cause.startswith(("d:", "s:")) and not cause.startswith("d:x:") else None
    ev = {}
    if key:
        try:
            from . import selfcheck
            for r in selfcheck.effective():
                ev[r["reply_id"]] = {"t": r["t"], "hit": key in (r.get("causes") or []), "model": r.get("model") or "", "rid": r["reply_id"]}
        except Exception:  # noqa: BLE001
            pass
    for r in rows:
        rid = r.get("message_id") or f"fb{r['id']}"
        hit = r["vote"] < 0 and _cause_of(r) == "d:" + (key or cause[2:])
        old = ev.get(rid) or {}
        ev[rid] = {"t": old.get("t", r["t"]), "hit": hit, "model": r.get("model") or old.get("model") or "", "rid": r.get("message_id")}
    win = sorted((v for v in ev.values() if not ((after is not None and v["t"] <= after) or (before is not None and v["t"] > before))),
                 key=lambda v: v["t"])
    if last:
        win = win[-last:]  # judge on the latest replies: a relapse shows even after a good start
    metas = {}
    for v in win:
        if v.get("rid") and v["rid"] not in metas:
            m = db.get_message(v["rid"]) if isinstance(v["rid"], int) else None
            metas[v["rid"]] = (m or {}).get("meta") or {}
        meta = metas.get(v.get("rid")) or {}
        v["domain"] = domain_of(meta)
        v["model"] = v["model"] or meta.get("model") or "unknown"
    return win


def _counts(rows, cause, after=None, before=None, last=None):
    """(rated, hits) in the window (see _evidence)."""
    win = _evidence(rows, cause, after, before, last)
    return len(win), sum(1 for v in win if v["hit"])


def _pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def _mix(win, key):
    """{value: % of the window}, largest first."""
    out = {}
    for v in win:
        out[v[key]] = out.get(v[key], 0) + 1
    return {k: _pct(n, len(win)) for k, n in sorted(out.items(), key=lambda kv: -kv[1])}


def _by_domain(win):
    """{domain: {n, pct}}: how often the problem showed in each kind of task."""
    out = {}
    for v in win:
        d = out.setdefault(v["domain"], [0, 0]); d[0] += 1; d[1] += bool(v["hit"])
    return {k: {"n": n, "pct": _pct(h, n)} for k, (n, h) in sorted(out.items(), key=lambda kv: -kv[1][0])}


def _rationale(les):
    """Why this fix should work, in words: the evidence behind it and what the lesson changes."""
    cause, n, text = les["id"], les.get("n") or 0, les.get("text") or ""
    fix = text.split("\u2192", 1)[1].strip() if "\u2192" in text else text
    if cause.startswith("s:"):
        note = ""
        try:
            from . import selfcheck
            what = selfcheck.RUBRIC.get(cause[2:], ("",))[0]
            notes = [r for r in selfcheck.reviews() if cause[2:] in (r.get("causes") or [])]
            if notes:
                i = notes[-1]["causes"].index(cause[2:])
                note = (notes[-1].get("notes") or [""] * (i + 1))[i]
        except Exception:  # noqa: BLE001
            what = ""
        return (f"Theta's self-check found this in {n} recent replies ({what.rstrip('.')})"
                + (f", most recently: \"{note}\"" if note else "") + f". The fix: {fix}.")
    if cause.startswith("d:"):
        return f"You disliked {n} {'reply' if n == 1 else 'replies'} for this. The fix: {fix}."
    return f"You liked {n} replies like this. The fix: {fix}."


def _cause_of(r):
    from . import persona
    low = (r.get("reason") or "").strip().lower()
    for label, key, _text in persona.REASONS:
        if low == label or low.startswith(label + ":") or low.startswith(label + " "):
            return "d:" + key
    return "d:x:" + persona._clip(r.get("reason") or "").lower()[:60] if low else ""


def record(lessons, now=None):
    """Note any lesson that's new (or changed wording) as an edit, with its prediction and baseline."""
    now = now or time.time()
    sim = _load()
    rows = db.feedback(limit=500)
    changed = False
    for les in lessons:
        cause = les["id"]
        ent = sim.setdefault(cause, {"cause": cause, "edits": []})
        last = ent["edits"][-1] if ent["edits"] else None
        if last and last["text"] == les["text"]:
            continue
        base = _evidence(rows, cause, before=now)
        rated, hits = len(base), sum(1 for v in base if v["hit"])
        problem = cause.startswith(("d:", "s:"))
        bpct = _pct(hits, rated)
        ent["edits"].append({"text": les["text"], "t": now, "model": _current_model(),
                             "rationale": _rationale(les),
                             "predicted": ("fewer replies with this problem" if problem else "more replies like the ones liked"),
                             "prediction": ({"base_pct": bpct, "target_pct": _pct(hits, 2 * rated),
                                             "says": "at most half as many replies with this problem"} if problem
                                            else {"says": "replies like these keep getting likes"}),
                             "base": {"rated": rated, "hits": hits, "pct": bpct, "models": _mix(base, "model"),
                                      "domains": _by_domain(base)}})
        ent["edits"] = ent["edits"][-12:]
        changed = True
    if changed:
        db.set_setting(KEY, sim)
    return sim


def check(now=None):
    """Fill in observed outcomes where enough newer replies were rated. Returns {cause: status}."""
    sim = _load()
    rows = db.feedback(limit=500)
    model = _current_model()
    out, changed = {}, False
    for cause, ent in sim.items():
        if not ent.get("edits"):
            continue
        e = ent["edits"][-1]
        win = _evidence(rows, cause, after=e["t"], last=CHECK_AFTER)
        rated, hits = len(win), sum(1 for v in win if v["hit"])
        if cause.startswith(("d:", "s:")) and rated >= CHECK_AFTER and e["base"]["rated"] >= MIN_BASE:
            before = e["base"]["hits"] / max(1, e["base"]["rated"])
            after = hits / rated
            verdict = "helping" if after < before or hits == 0 else "not helping"
            obs = {"rated": rated, "hits": hits, "pct": _pct(hits, rated), "verdict": verdict, "t": now or time.time(),
                   "models": _mix(win, "model"), "domains": _by_domain(win)}
            if {k: v for k, v in (e.get("observed") or {}).items() if k != "t"} != {k: v for k, v in obs.items() if k != "t"}:
                e["observed"] = obs
                changed = True
            status = verdict
        elif cause.startswith(("d:", "s:")):
            status = "early"
        else:
            status = "helping" if rated else "early"  # liked styles: kept while likes keep coming
        if e.get("model") and model and _family(e["model"]) != _family(model) and status != "not helping":
            status = "recheck"
        if ent.get("status") != status:
            ent["status"] = status
            changed = True
        out[cause] = status
    if changed:
        db.set_setting(KEY, sim)
    return out


def prompt_notes(lessons):
    """The lessons' lines for the instructions, with the log's verdicts: one that hasn't stuck is stated harder."""
    status = check()
    lines = []
    for les in lessons:
        s = status.get(les["id"])
        if s == "not helping":
            lines.append(f"{les['text']} (this has kept happening since it was added: apply it strictly)")
        else:
            lines.append(les["text"])
    return lines


def _label(cause):
    if cause.startswith("s:"):
        try:
            from . import selfcheck
            return "Found by Theta's self-check: " + selfcheck.RUBRIC[cause[2:]][0].split(":")[0].rstrip(".")
        except Exception:  # noqa: BLE001
            return "Found by Theta's self-check"
    if cause.startswith("d:x:"):
        return f'You said: "{cause[4:]}"'
    if cause.startswith("d:"):
        from . import persona
        return "You disliked: " + next((lbl for lbl, key, _ in persona.REASONS if key == cause[2:]), cause[2:])
    return "You liked a style of reply"


def summary():
    """{cause: the log in the owner's layout} for Settings: root cause, rationale, predicted, observed (%), the models
    behind the evidence (%), and the domains (kinds of task, with the problem's rate in each)."""
    check()
    out = {}
    for c, ent in _load().items():
        e = (ent.get("edits") or [{}])[-1]
        obs, base = e.get("observed") or {}, e.get("base") or {}
        out[c] = {"status": ent.get("status", "early"), "edits": len(ent.get("edits") or []), "since": e.get("t"),
                  "root_cause": _label(c), "rationale": e.get("rationale") or "",
                  "predicted": e.get("prediction") or {"says": e.get("predicted", "")},
                  "observed": {"pct": obs.get("pct"), "rated": obs.get("rated"), "base_pct": base.get("pct"),
                               "base_rated": base.get("rated"), "verdict": obs.get("verdict")},
                  "models": obs.get("models") or base.get("models") or {},
                  "domains": obs.get("domains") or base.get("domains") or {}}
    return out
