"""Does Theta get better on its own? A live experiment for server/selfcheck.py + server/improve.py.

Design (after the papers in docs/RESEARCH.md, "Testing self-improvement"):

1. Learn: Theta answers the SEEN tasks for LEARN_ROUNDS rounds. After each reply its self-check grades it, as in
   production; a simulated user rates only 1 in USER_EVERY replies, and only the poor ones (a nudge, not the driver).
   Lessons form from that alone.
2. Test: every task, SEEN and UNSEEN (never practised), is answered SAMPLES times with what Theta learned turned on
   and SAMPLES times with it off, interleaved, same model, same moment. Comparing on/off at the same time removes
   drift between rounds (Miller 2024: paired differences).
3. Score two ways:
   - checks that need no judge: the reminder was really set, the note really saved, the plan really made, the
     conversion right (verifiable outcomes first; Pombal et al. 2026 on judges favouring their own side's work)
   - a blind pairwise judge: on vs off for the same task, asked in both orders, so position bias cancels and a
     flip counts as a tie (Zheng et al. 2023; Yagubyan 2026: preferences flip about 13.6% of the time).
4. Report seen and unseen separately (repair vs transfer: Zhao et al. 2026 found failure-derived lessons repair seen
   tasks but rarely transfer), with 95% intervals from per-task paired differences, and list the lessons so they
   can be read for correctness (agents "often misinterpret failures").

Each turn starts clean (no reminders, plans or notes from earlier turns, an empty chat); only what Theta learned
(self-reviews, the lesson log, ratings) and the profile carry over.

    DEEPSEEK_API_KEY=... python3 evals/selfimprove.py [--out results.json]
    JUDGE=anthropic/claude-sonnet-5-5   use a judge from another model family (recommended when there's a key)
"""
import argparse
import concurrent.futures as cf
import json
import math
import os
import re
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PROTOS_DATA", tempfile.mkdtemp())
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1")

from server import app, db, ext, improve, models, persona, selfcheck, tools  # noqa: E402

LEARN_ROUNDS = 3
SAMPLES = 2
USER_EVERY = 4


def used(*names):
    return lambda r: any(n in ((r.get("meta") or {}).get("tools") or []) for n in names)


def says(pattern):
    return lambda r: re.search(pattern, r["text"], re.I) is not None


# (task, check or None): a check is a fact about the outcome, not a matter of taste
SEEN = [
    ("What's a good weeknight dinner I can make in 20 minutes?", None),
    ("Remind me to call my mom at 6pm today.", used("remind_me")),
    ("Write a text to my landlord saying the kitchen sink is leaking.", None),
    ("Plan my Saturday: gym in the morning, groceries, and a movie at night.", used("plan_update", "remind_me")),
    ("How many ounces are in a cup?", says(r"\b8\b")),
    ("Should I get an EV or a hybrid? I drive about 40 miles a day.", None),
    ("Remember that my gym is Vasa on 33rd South.", used("memory_edit")),
    ("I'm stressed about my exam tomorrow.", None),
    ("Explain what an index fund is.", None),
    ("Give me a packing list for a 3-day work trip to Chicago in December.", None),
]
UNSEEN = [
    ("What's a quick healthy lunch I can bring to work?", None),
    ("Remind me to take out the trash tomorrow at 7am.", used("remind_me")),
    ("Write a short note to my boss saying I'll be 15 minutes late.", None),
    ("How many teaspoons are in a tablespoon?", says(r"\b3\b|three")),
    ("What's the difference between a Roth IRA and a traditional IRA?", None),
    ("Plan my Sunday: laundry, meal prep, and calling my sister.", used("plan_update", "remind_me")),
    ("Remind me to pay rent on the 1st at 9am.", used("remind_me")),
    ("Remember that I'm allergic to shellfish.", used("memory_edit")),
    ("How many minutes are in 3.5 hours?", says(r"\b210\b")),
    ("How many grams are in a pound?", says(r"\b45[34]")),
    ("Text my neighbor that their package was left at my door.", None),
    ("What can I cook with chicken, rice and broccoli?", None),
    ("Explain compound interest simply.", None),
    ("I can't sleep. Any quick tips?", None),
    ("Give me a checklist for moving apartments.", None),
    ("Plan my Monday: dentist at 10, groceries, and a run after work.", used("plan_update", "remind_me")),
]
USER = ("A busy person who wants Theta to just get things done. Likes short, direct answers with the key point "
        "first. Hates padding, gushing, being asked permission for small things that can be undone, and made-up "
        "facts.")

PAIR_PROMPT = """You compare two replies an AI assistant could send this user, and pick the one that serves them
better. The user:
{user}

What the assistant knows about them and can do (not made up if it uses these):
{known}

The user's message: {ask}

Reply A (steps it took: {sa}):
<<<
{a}
>>>

Reply B (steps it took: {sb}):
<<<
{b}
>>>

Judge what each reply did and said for this user: done or answered, correct, nothing invented, right length, fitting
tone, no needless questions. Length alone is not quality. Answer with JSON only:
{{"better": "A" | "B" | "tie", "why": "<under 15 words>"}}"""


# ---------------------------------------------------------------- running turns

KEEP_SETTINGS = ("selfcheck", "sim", "feedback_version", "profile")
RESET_TABLES = ("jobs", "memory", "summary", "approvals", "plans", "routines", "workflows", "seen")
_real_block = persona.feedback_block


def reset():
    c = db._conn()
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in RESET_TABLES:
        if t in tables:
            c.execute(f"DELETE FROM {t}")
    c.execute(f"DELETE FROM settings WHERE key NOT IN ({','.join('?' * len(KEEP_SETTINGS))})", KEEP_SETTINGS)
    c.commit()


def turn(text, learned=True):
    """One real turn in a clean, empty chat, with what Theta learned on or off."""
    reset()
    old = [m["id"] for m in db.messages("theta", limit=500)]
    if old:
        db.delete_messages(old)
    persona.feedback_block = _real_block if learned else (lambda: "")
    got = {}
    try:
        app._chat_worker("theta", text, [], None, lambda e, d: got.update({e: d}))
    finally:
        persona.feedback_block = _real_block
    return got.get("done"), got.get("error")


def simulated_user(i, reply):
    """Rates 1 in USER_EVERY replies, and only the poor ones (by the self-check's own grade, so no third model)."""
    if i % USER_EVERY:
        return None
    rv = next((r for r in selfcheck.reviews() if r["reply_id"] == reply["id"]), None)
    if not rv or rv["score"] >= 4 or not rv.get("causes"):
        return None
    c = rv["causes"][0]
    reason = {"too-long": "too long", "wrong": "wrong", "tone": "tone"}.get(c, "not what i asked")
    db.set_feedback(reply["id"], -1, reason)
    return reason


# ---------------------------------------------------------------- judging

def pick(spec, default):
    if not spec:
        return default
    p, m = spec.split("/", 1)
    return p, m


def ask_judge(judge, prompt):
    res = models.call(judge[0], judge[1], [{"role": "user", "content": prompt}], None, 3000, tool_choice="none",
                      timeout=180)
    m = re.search(r"\{.*\}", res.get("text") or "", re.S)
    return json.loads(m.group(0)) if m else {}


def pairwise(judge, ask, on, off):
    """+1 on better, -1 off better, 0 tie or the verdict flipped with the order. Asked in both orders."""
    votes = []
    for first, second, sign in ((on, off, 1), (off, on, -1)):
        try:
            d = ask_judge(judge, PAIR_PROMPT.format(user=USER, known=selfcheck.known(), ask=ask,
                                                    sa=selfcheck._steps(first.get("meta") or {}), a=first["text"][:5000],
                                                    sb=selfcheck._steps(second.get("meta") or {}), b=second["text"][:5000]))
            b = str(d.get("better", "")).strip().upper()
            votes.append(sign if b == "A" else -sign if b == "B" else 0)
        except Exception:  # noqa: BLE001
            votes.append(None)
    v = [x for x in votes if x is not None]
    if len(v) < 2:
        return None, votes
    return (v[0] if v[0] == v[1] else 0), votes


# ---------------------------------------------------------------- statistics

def mean_ci(xs):
    """Mean and the half-width of a 95% interval (normal approximation over tasks)."""
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None, 0
    n = len(xs)
    m = sum(xs) / n
    if n < 2:
        return round(m, 3), None, n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return round(m, 3), round(1.96 * sd / math.sqrt(n), 3), n


# ---------------------------------------------------------------- the experiment

def learn(log):
    k = 0
    for rnd in range(LEARN_ROUNDS):
        for ask, _chk in SEEN:
            reply, err = turn(ask, learned=True)
            if not reply:
                print(f"learn r{rnd} ERROR {ask[:40]}: {err}", flush=True)
                continue
            try:
                rv = selfcheck.review(reply["id"])
            except Exception as e:  # noqa: BLE001
                rv = {"score": None, "causes": [], "error": str(e)[:80]}
            fb = simulated_user(k, reply)
            k += 1
            log["learn"].append({"round": rnd, "ask": ask, "reply": reply["text"], "self": rv and rv.get("score"),
                                 "causes": rv and rv.get("causes"), "notes": rv and rv.get("notes"), "user": fb})
            print(f"learn r{rnd} self={rv and rv.get('score')} {rv and rv.get('causes')} user={fb} "
                  f"{len(reply['text'])}ch  {ask[:45]}", flush=True)
        print(f"== after round {rnd}: lessons {[x['id'] for x in persona.lessons()]}  status {improve.check()}", flush=True)
    log["lessons"] = [{"id": x["id"], "text": x["text"]} for x in persona.lessons()]
    log["lesson_status"] = improve.check()
    log["selfstats"] = selfcheck.stats()


def test(log, judge):
    pairs = []
    for kind, tasks in (("seen", SEEN), ("unseen", UNSEEN)):
        for ask, chk in tasks:
            for s in range(SAMPLES):
                order = (True, False) if (s + len(pairs)) % 2 == 0 else (False, True)  # interleave on/off
                got = {}
                for learned in order:
                    reply, err = turn(ask, learned=learned)
                    got[learned] = reply
                    if reply is None:
                        print(f"test ERROR {ask[:40]}: {err}", flush=True)
                if got.get(True) and got.get(False):
                    p = {"kind": kind, "ask": ask, "sample": s, "on": got[True], "off": got[False],
                         "check_on": chk(got[True]) if chk else None, "check_off": chk(got[False]) if chk else None}
                    pairs.append(p)
                    print(f"test {kind:6} s{s} on={len(p['on']['text'])}ch off={len(p['off']['text'])}ch "
                          f"check on/off={p['check_on']}/{p['check_off']}  {ask[:40]}", flush=True)
    print(f"judging {len(pairs)} pairs, both orders...", flush=True)
    with cf.ThreadPoolExecutor(6) as pool:
        futs = {pool.submit(pairwise, judge, p["ask"], p["on"], p["off"]): p for p in pairs}
        for f in cf.as_completed(futs):
            futs[f]["verdict"], futs[f]["votes"] = f.result()
    for kind in ("seen", "unseen", "all"):
        ps = [p for p in pairs if kind == "all" or p["kind"] == kind]
        by_task = {}
        for p in ps:
            if p["verdict"] is not None:
                by_task.setdefault(p["ask"], []).append(p["verdict"])
        chk = [p for p in ps if p["check_on"] is not None]
        flips = [p for p in ps if p["votes"] and None not in p["votes"] and p["votes"][0] != p["votes"][1]]
        log["results"][kind] = {
            "pairs": len(ps),
            "judge_net": mean_ci([sum(v) / len(v) for v in by_task.values()]),  # +1: learned always better
            "wins": sum(1 for p in ps if p["verdict"] == 1), "losses": sum(1 for p in ps if p["verdict"] == -1),
            "ties_or_flips": sum(1 for p in ps if p["verdict"] == 0), "order_flips": len(flips),
            "checks_on": sum(bool(p["check_on"]) for p in chk), "checks_off": sum(bool(p["check_off"]) for p in chk),
            "checks_n": len(chk), "checks_diff": mean_ci([int(p["check_on"]) - int(p["check_off"]) for p in chk]),
            "chars_on": int(sum(len(p["on"]["text"]) for p in ps) / max(1, len(ps))),
            "chars_off": int(sum(len(p["off"]["text"]) for p in ps) / max(1, len(ps))),
        }
    log["pairs"] = [dict(p, on=p["on"]["text"], off=p["off"]["text"],
                         on_tools=(p["on"].get("meta") or {}).get("tools"), off_tools=(p["off"].get("meta") or {}).get("tools"))
                    for p in pairs]


def main(out):
    db.init()
    ext.reset(); tools._ext_reset(); tools._ext()
    db.set_setting("profile", {"name": "Sam"})
    judge = pick(os.environ.get("JUDGE"), ("deepseek", "deepseek-reasoner"))
    log = {"started": time.time(), "judge": "/".join(judge), "learn": [], "results": {}}
    learn(log)
    with open(out, "w") as f:
        json.dump(log, f, indent=1)
    test(log, judge)
    log["finished"] = time.time()
    with open(out, "w") as f:
        json.dump(log, f, indent=1, default=str)
    print(json.dumps({"lessons": log["lessons"], "status": log["lesson_status"], "results": log["results"]}, indent=1),
          flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "selfimprove.json"))
    main(ap.parse_args().out)
