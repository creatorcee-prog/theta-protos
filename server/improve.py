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


def _counts(rows, cause, after=None, before=None, last=None):
    """(rated, hits): replies with evidence in the window, and how many showed this cause. Evidence is the user's
    ratings plus Theta's own reviews (server/selfcheck.py) of every reply; on a reply the user rated, their word
    wins (a dislike for this cause is a hit, a like is not)."""
    key = cause.split(":", 1)[1] if cause.startswith(("d:", "s:")) and not cause.startswith("d:x:") else None
    ev = {}
    if key:
        try:
            from . import selfcheck
            for r in selfcheck.effective():
                ev[r["reply_id"]] = [r["t"], key in (r.get("causes") or [])]
        except Exception:  # noqa: BLE001
            pass
    for r in rows:
        rid = r.get("message_id") or f"fb{r['id']}"
        hit = r["vote"] < 0 and _cause_of(r) == "d:" + (key or cause[2:])
        ev[rid] = [ev.get(rid, [r["t"]])[0], hit]
    win = sorted(v for v in ev.values() if not ((after is not None and v[0] <= after) or (before is not None and v[0] > before)))
    if last:
        win = win[-last:]  # judge on the latest replies: a relapse shows even after a good start
    return len(win), sum(bool(h) for _, h in win)


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
        rated, hits = _counts(rows, cause, before=now)
        ent["edits"].append({"text": les["text"], "t": now, "model": _current_model(),
                             "predicted": ("fewer replies with this problem" if cause.startswith(("d:", "s:"))
                                           else "more replies like the ones liked"),
                             "base": {"rated": rated, "hits": hits}})
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
        rated, hits = _counts(rows, cause, after=e["t"], last=CHECK_AFTER)
        if cause.startswith(("d:", "s:")) and rated >= CHECK_AFTER and e["base"]["rated"] >= MIN_BASE:
            before = e["base"]["hits"] / max(1, e["base"]["rated"])
            after = hits / rated
            verdict = "helping" if after < before or hits == 0 else "not helping"
            if e.get("observed", {}).get("rated") != rated:
                e["observed"] = {"rated": rated, "hits": hits, "verdict": verdict, "t": now or time.time()}
                changed = True
            status = verdict
        elif cause.startswith(("d:", "s:")):
            status = "early"
        else:
            status = "helping" if rated else "early"  # liked styles: kept while likes keep coming
        if e.get("model") and model and e["model"] != model and status != "not helping":
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


def summary():
    """{cause: {status, edits}} for Settings."""
    check()
    return {c: {"status": e.get("status", "early"), "edits": len(e.get("edits") or []),
                "since": (e.get("edits") or [{}])[-1].get("t")} for c, e in _load().items()}
