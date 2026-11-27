"""Does Theta get better on its own? A live experiment for server/selfcheck.py + server/improve.py.

Runs real turns through the app (real models, a fresh data folder) in rounds. After every reply, Theta's
self-check grades it (as in production). A simulated user rates only a few replies (1 in USER_EVERY, and only the
bad ones), so the user guides but doesn't drive. Between rounds nothing is changed by hand: any change in behaviour
comes from the lessons Theta wrote itself.

Measured by an independent judge (a separate prompt and rubric, blind to the round), on two task sets:
- train: the tasks Theta practises on every round
- held-out: different tasks, only scored in the first and last round, to see if lessons carry over

Each task runs in an empty chat (history cleared), so a later round can't copy earlier replies.

    DEEPSEEK_API_KEY=... python3 evals/selfimprove.py [--rounds 4] [--out results.json]

Optional: ANSWER=provider/model and JUDGE=provider/model to pick the models.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PROTOS_DATA", tempfile.mkdtemp())
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1")

from server import app, db, ext, improve, models, persona, router, selfcheck, tools  # noqa: E402

TRAIN = [
    "What's a good weeknight dinner I can make in 20 minutes?",
    "Remind me to call my mom at 6pm today.",
    "Write a text to my landlord saying the kitchen sink is leaking.",
    "Plan my Saturday: gym in the morning, groceries, and a movie at night.",
    "How many ounces are in a cup?",
    "Should I get an EV or a hybrid? I drive about 40 miles a day.",
    "Remember that my gym is Vasa on 33rd South.",
    "I'm stressed about my exam tomorrow.",
    "Explain what an index fund is.",
    "Give me a packing list for a 3-day work trip to Chicago in December.",
]
HELD_OUT = [
    "What's a quick healthy lunch I can bring to work?",
    "Remind me to take out the trash tomorrow at 7am.",
    "Write a short note to my boss saying I'll be 15 minutes late.",
    "How many teaspoons are in a tablespoon?",
    "What's the difference between a Roth IRA and a traditional IRA?",
    "Plan my Sunday: laundry, meal prep, and calling my sister.",
]
USER = ("A busy person who wants Theta to just get things done. Likes short, direct answers with the key point "
        "first. Hates padding, gushing, being asked permission for small things that can be undone, and made-up "
        "facts.")
USER_EVERY = 4

JUDGE_PROMPT = """You are an impartial judge scoring an AI assistant's reply for this user:
{user}

What the assistant knows about them and can do (not made up if it uses these):
{known}

Score 1-10 for how well the reply serves this user: did it do/answer the actual thing, correctly, with no invented
facts, at the right length, in a fitting tone, without needless questions? Judge only the reply.

User's message: {ask}
What the assistant did (its tool steps): {tools}
Reply:
<<<
{reply}
>>>
Answer with JSON only: {{"score": <1-10>, "worst": "<the biggest problem in under 12 words, or none>"}}"""


def pick(spec, default):
    if not spec:
        return default
    p, m = spec.split("/", 1)
    return p, m


def call_json(provider, model, prompt, max_tokens=3000):
    res = models.call(provider, model, [{"role": "user", "content": prompt}], None, max_tokens, tool_choice="none",
                      timeout=120)
    m = re.search(r"\{.*\}", res.get("text") or "", re.S)
    return json.loads(m.group(0)) if m else {}


def turn(text):
    """One real turn in an empty chat. Returns the reply message."""
    old = [m["id"] for m in db.messages("theta", limit=500)]
    if old:
        db.delete_messages(old)
    got = {}
    app._chat_worker("theta", text, [], None, lambda e, d: got.update({e: d}))
    return got.get("done"), got.get("error")


def judge(jp, jm, ask, reply):
    try:
        d = call_json(jp, jm, JUDGE_PROMPT.format(user=USER, known=selfcheck.known(), ask=ask, tools=selfcheck._steps(reply.get("meta") or {}),
                                                  reply=reply["text"][:6000]))
        return max(1, min(10, int(d.get("score")))), str(d.get("worst") or "")[:100]
    except Exception as e:  # noqa: BLE001
        return None, f"judge failed: {type(e).__name__}"


def simulated_user(i, reply, score, worst):
    """Rates 1 in USER_EVERY replies, and only says something when it's poor: a nudge, not the driver."""
    if i % USER_EVERY or score is None or score > 6:
        return None
    low = worst.lower()
    reason = ("too long" if re.search(r"long|verbose|padding|wordy", low) else
              "wrong" if re.search(r"wrong|incorrect|invent|made.up|fact", low) else
              "not what i asked" if re.search(r"didn.t|instead|ask|permission|question|off", low) else "tone")
    db.set_feedback(reply["id"], -1, reason)
    return reason


def run(rounds, out_path):
    db.init()
    ext.reset(); tools._ext_reset(); tools._ext()
    db.set_setting("profile", {"name": "Sam"})
    jp, jm = pick(os.environ.get("JUDGE"), ("deepseek", "deepseek-reasoner"))
    if os.environ.get("ANSWER"):
        p, m = pick(os.environ["ANSWER"], None)
        router.TIER_CANDIDATES["quick"].insert(0, (p, lambda m=m: m))
    log = {"started": time.time(), "judge": f"{jp}/{jm}", "rounds": []}
    k = 0
    for rnd in range(rounds):
        sets = [("train", TRAIN)] + ([("held", HELD_OUT)] if rnd in (0, rounds - 1) else [])
        rows = []
        for kind, tasks in sets:
            for ask in tasks:
                t0 = time.time()
                reply, err = turn(ask)
                if not reply:
                    rows.append({"kind": kind, "ask": ask, "error": str(err)[:200]})
                    print(f"r{rnd} {kind} ERROR {ask[:40]}: {err}", flush=True)
                    continue
                if kind == "train":  # Theta checks its own work, as it does in production
                    try:
                        rv = selfcheck.review(reply["id"])
                    except Exception as e:  # noqa: BLE001
                        rv = {"error": str(e)[:100]}
                else:
                    rv = None
                score, worst = judge(jp, jm, ask, reply)
                fb = simulated_user(k, reply, score, worst) if kind == "train" else None
                k += 1
                row = {"kind": kind, "ask": ask, "reply": reply["text"], "chars": len(reply["text"]),
                       "tools": (reply.get("meta") or {}).get("tools") or [], "model": (reply.get("meta") or {}).get("model"),
                       "judge": score, "worst": worst, "self": rv and {k2: rv.get(k2) for k2 in ("score", "causes", "notes", "error")},
                       "user": fb, "secs": round(time.time() - t0, 1)}
                rows.append(row)
                print(f"r{rnd} {kind:5} judge={score} self={(rv or {}).get('score')} {(rv or {}).get('causes')} "
                      f"user={fb} {len(reply['text'])}ch  {ask[:45]}", flush=True)
        les = persona.lessons()
        status = improve.check()
        summary = {}
        for kind in ("train", "held"):
            sc = [r["judge"] for r in rows if r.get("kind") == kind and r.get("judge")]
            ch = [r["chars"] for r in rows if r.get("kind") == kind and r.get("chars")]
            if sc:
                summary[kind] = {"judge_avg": round(sum(sc) / len(sc), 2), "n": len(sc), "chars_avg": int(sum(ch) / len(ch))}
        log["rounds"].append({"round": rnd, "summary": summary, "lessons": [x["text"] for x in les],
                              "status": status, "selfstats": selfcheck.stats(), "rows": rows})
        print(f"== round {rnd}: {json.dumps(summary)}\n   lessons: {[x['id'] for x in les]}\n   status: {status}", flush=True)
        with open(out_path, "w") as f:
            json.dump(log, f, indent=1)
    return log


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "selfimprove.json"))
    a = ap.parse_args()
    run(a.rounds, a.out)
