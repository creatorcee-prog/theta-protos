"""Memory the model can edit, plus the running summary of old turns (docs/HARNESS.md P6, P7).

    block() -> str                       the memory block for the system prompt (cap CAP chars)
    edit(op, text, old=None) -> dict     op: add | replace | remove; {"ok", "block"} (+ "error" when refused)
    summary(bot) -> str                  the running summary of turns older than the last KEEP
    compact(bot, summarize=fn) -> bool   fold old turns into the summary once >= MIN_NEW have piled up
    search(query, limit=5) -> list       LIKE search over the full message history
    summarizer() -> fn | None            a summarize(text)->str on the quick model (for app.py / evals)

The memory block is one short text of "- fact" lines, stored in db (get_memory /
set_memory), always in the system prompt, and edited by the model through the
memory_edit tool. It changes rarely, so the prompt prefix stays cacheable.

Before anything is written through edit(), block() falls back to the v0 notes
(db setting "memory" and $PROTOS_DATA/memory.md); the first edit() copies those
into the block.

The summary covers messages older than the last KEEP (the ones persona.build
no longer sends). It is only rewritten when at least MIN_NEW messages have
aged out since the last fold, so it too stays stable for many turns.
"""

import os
import re
import threading

from . import db

CAP = 2000          # memory block, characters
LINE_CAP = 300      # one fact, characters
KEEP = 20           # recent messages persona.build sends as turns; older ones belong to the summary
MIN_NEW = 10        # aged-out messages needed before compact() rewrites the summary
SUMMARY_CAP = 2500  # characters
TRANSCRIPT_CAP = 14000  # characters of old turns sent to the summarizer in one fold

SUMMARY_PROMPT = """You keep the running summary of a long chat between the user and their assistant, Theta.
Fold the new messages below into the summary. Write for recall: keep facts about the user, decisions, \
plans, numbers, names, dates, open questions and any promise Theta made ("I'll remind you...", "I'll check..."). \
Drop small talk. Plain short lines, newest facts last, at most 250 words. Reply with the summary only.

Summary so far:
{summary}

New messages (oldest first):
{transcript}"""

_compact_lock = threading.Lock()
_edit_lock = threading.Lock()
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


# ---- the memory block

def _legacy_notes():
    """v0 notes: db setting "memory" (strings or {"text"}) and $PROTOS_DATA/memory.md."""
    notes = []
    try:
        stored = db.get_setting("memory")
        if stored is None:
            stored = (db.get_setting("settings") or {}).get("memory")
    except Exception:
        stored = None
    if isinstance(stored, list):
        for n in stored:
            t = n.get("text") if isinstance(n, dict) else n
            if isinstance(t, str) and t.strip():
                notes.append(t.strip())
    data = os.environ.get("PROTOS_DATA") or os.path.join(os.getcwd(), "data")
    try:
        with open(os.path.join(data, "memory.md"), encoding="utf-8") as f:
            notes += [ln.strip().lstrip("-* ").strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except OSError:
        pass
    return [n[:LINE_CAP] for n in notes if n]


def _fit(lines):
    """Newest lines that fit in CAP."""
    out, size = [], 0
    for ln in reversed(lines):
        if size + len(ln) + 1 > CAP:
            break
        out.append(ln)
        size += len(ln) + 1
    return "\n".join(reversed(out))


def _stored():
    try:
        return db.get_memory() or ""
    except Exception:
        return ""


def block():
    """The current memory block ("" if nothing is remembered), at most CAP chars."""
    text = _stored().strip()
    if text:
        return text[:CAP]
    return _fit([f"- {n}" for n in _legacy_notes()])


def _one_line(text):
    s = _CTRL.sub(" ", str(text or "")).replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"^[-*•]\s*", "", s)


def _refuse(error, cur):
    return {"ok": False, "error": error, "block": cur}


def edit(op, text, old=None):
    """Change the memory block.
      add:     text = one new fact (a short line; "people: Sam is my brother" style labels are fine)
      replace: old = words copied from the block, text = what to put there instead
      remove:  old (or text) = words copied from the line to drop; the whole line goes
    Returns {"ok": True, "block": new} or {"ok": False, "error": how to fix the call, "block": current}.
    Refuses anything that would push the block over CAP chars."""
    op = str(op or "").strip().lower()
    with _edit_lock:
        cur = block()
        lines = [ln for ln in cur.split("\n") if ln.strip()]
        if op == "add":
            fact = _one_line(text)
            if not fact:
                return _refuse("text is empty: pass the fact to remember, e.g. text='Gym at 6am on weekdays'", cur)
            if len(fact) > LINE_CAP:
                return _refuse(f"that fact is {len(fact)} chars; keep one fact under {LINE_CAP}", cur)
            if any(fact.lower() == ln.lstrip("-* ").strip().lower() for ln in lines):
                return {"ok": True, "block": cur, "note": "already remembered"}
            new_lines = lines + [f"- {fact}"]
        elif op == "replace":
            target, fact = str(old or "").strip(), _one_line(text)
            if not target:
                return _refuse("replace needs old= (words copied exactly from the memory block) and text=", cur)
            if not fact:
                return _refuse("replace needs text= (the new wording); to delete a line use op='remove'", cur)
            if len(fact) > LINE_CAP:
                return _refuse(f"the new text is {len(fact)} chars; keep one fact under {LINE_CAP}", cur)
            idx = _find(lines, target)
            if idx is None:
                return _refuse(f"couldn't find {target[:80]!r} in the memory block; copy the exact words from it", cur)
            ln = lines[idx]
            if target.lower() == ln.lstrip("-* ").strip().lower() or target.lower() == ln.strip().lower():
                lines[idx] = f"- {fact}"
            else:
                pos = ln.lower().find(target.lower())
                lines[idx] = ln[:pos] + fact + ln[pos + len(target):]
            new_lines = lines
        elif op == "remove":
            target = str(old or text or "").strip()
            if not target:
                return _refuse("remove needs old= (words copied from the line to forget)", cur)
            idx = _find(lines, target)
            if idx is None:
                return _refuse(f"couldn't find {target[:80]!r} in the memory block; copy the exact words from it", cur)
            new_lines = lines[:idx] + lines[idx + 1:]
        else:
            return _refuse(f"unknown op {op!r}: use add, replace or remove", cur)
        new = "\n".join(new_lines)
        if len(new) > CAP:
            return _refuse(f"memory is full ({len(new)}/{CAP} chars with this change): replace or remove "
                           "an old fact first", cur)
        db.set_memory(new)
        return {"ok": True, "block": new}


def _find(lines, target):
    t = target.lower().lstrip("-* ").strip()
    for i, ln in enumerate(lines):
        if t and t in ln.lower():
            return i
    return None


# ---- running summary

def summary(bot="theta"):
    """The running summary of turns older than the last KEEP ("" if none)."""
    try:
        return db.get_summary(bot)[0] or ""
    except Exception:
        return ""


def _aged_out(bot, upto, keep):
    """Messages after id `upto` that are older than the last `keep`, oldest first."""
    recent = db.messages(bot, limit=keep)
    if len(recent) < keep:
        return []
    cutoff = recent[0]["id"]
    out = []
    after = upto
    while True:
        batch = db.since(after, bot=bot, limit=500)
        if not batch:
            break
        for m in batch:
            if m["id"] >= cutoff:
                return out
            out.append(m)
        after = batch[-1]["id"]
    return out


def compact(bot="theta", summarize=None, keep=None, min_new=None):
    """Fold messages older than the last KEEP into the summary, once at least
    MIN_NEW of them are new since the last fold. `summarize(prompt) -> str` is the
    quick model (injected). Returns True if the summary changed. Never raises."""
    if summarize is None:
        return False
    if not _compact_lock.acquire(blocking=False):
        return False  # another fold is running
    try:
        prev, upto = db.get_summary(bot)
        old = _aged_out(bot, upto, int(keep or KEEP))
        talk = {m["id"] for m in old if not (m.get("meta") or {}).get("ack") and (m.get("text") or "").strip()}
        if len(old) < (MIN_NEW if min_new is None else int(min_new)) or not talk:
            return False
        lines, size, last_id = [], 0, upto
        for m in old:
            if m["id"] in talk:
                who = "User" if m["role"] == "user" else "Theta"
                ln = who + ": " + re.sub(r"\s+", " ", m["text"]).strip()[:600]
                if lines and size + len(ln) > TRANSCRIPT_CAP:
                    break  # the rest waits for the next fold
                lines.append(ln)
                size += len(ln) + 1
            last_id = m["id"]
        prompt = SUMMARY_PROMPT.format(summary=prev.strip() or "(none yet)", transcript="\n".join(lines))
        try:
            out = summarize(prompt)
        except Exception:
            return False
        out = _CTRL.sub("", str(out or "")).strip()
        if not out:
            return False
        if len(out) > SUMMARY_CAP:
            out = out[:SUMMARY_CAP].rsplit("\n", 1)[0].strip() or out[:SUMMARY_CAP]
        db.set_summary(bot, out, last_id)
        return True
    except Exception:
        return False
    finally:
        _compact_lock.release()


def summarizer(max_tokens=600):
    """summarize(prompt) -> str on the first quick-tier model, or None if none is configured."""
    from . import models, router
    cands = router.candidates("quick")
    if not cands:
        return None
    provider, model = cands[0]

    def summarize(prompt):
        return models.complete(provider, model, [{"role": "user", "content": prompt}], max_tokens=max_tokens)
    return summarize


# ---- history search

def search(query, limit=5, bot=None, before=None):
    """Up to `limit` past messages matching `query` (phrase, else every word), newest
    first, as {"id", "role", "text" (trimmed), "t"}. `before` skips ids >= it
    (e.g. the turn that's asking)."""
    try:
        rows = db.search_messages(query, bot=bot, limit=int(limit or 5) + (5 if before else 0))
    except Exception:
        return []
    out = []
    for m in rows:
        if before and m["id"] >= int(before):
            continue
        if (m.get("meta") or {}).get("ack"):
            continue
        text = m["text"] if len(m["text"]) <= 500 else m["text"][:500] + "..."
        out.append({"id": m["id"], "role": m["role"], "text": text, "t": m["t"]})
        if len(out) >= int(limit or 5):
            break
    return out
