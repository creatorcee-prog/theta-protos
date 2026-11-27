"""Theta checks its own work (server/selfcheck.py): each reply is graded, a problem that keeps coming back becomes a
lesson without the user rating anything, the user's ratings override the self-check, and the lesson log
(server/improve.py) judges lessons on the self-reviews too, so a verdict comes quickly. The grader is faked."""
import os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp())
from server import db, improve, persona, selfcheck


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


db.init()
T0 = time.time() - 100000
N = [0]


def reply(text="Sure! Here is a very long answer...", model="deepseek-chat"):
    db.add_message("theta", "user", "what's 2+2?")
    return db.add_message("theta", "assistant", text, {"model": model, "tools": []})


def grader(*issues, score=2):
    body = ", ".join('{"key": "%s", "why": "x"}' % k for k in issues)
    return lambda msgs: 'Review: {"score": %d, "issues": [%s]}' % (score, body)


def review(r, g):
    N[0] += 1
    return selfcheck.review(r["id"], call=g, now=T0 + N[0] * 60)


check("off unless the server turns it on", selfcheck.ENABLED is False)
row = review(reply(), grader("too-long", "made-up-key"))
check("a reply is graded: known problems kept, unknown keys dropped", row["causes"] == ["too-long"] and row["score"] == 2)
seen = {}
selfcheck.review(reply("ok")["id"], call=lambda m: seen.update(p=m[0]["content"]) or '{"score": 5, "issues": []}', now=T0 + 30)
check("the prompt holds the question, as data, and the rubric", "what's 2+2?" in seen["p"] and "asked-instead" in seen["p"])
check("one bad reply isn't a pattern", not selfcheck.lessons())
review(reply(), grader("too-long"))
v0 = db.feedback_version()
review(reply(), grader("too-long"))
les = persona.lessons()
check("the same problem 3 times in the last 20 makes a lesson, no rating needed",
      any(x["id"] == "s:too-long" for x in les) and db.feedback_version() > v0)
check("and it reaches the prompt", "keep replies shorter" in persona.feedback_block())

# the user steers: a like clears the flags on that reply; two likes mute the cause
r1, r2 = reply(), reply()
review(r1, grader("asked-instead")); review(r2, grader("asked-instead")); review(reply(), grader("asked-instead"))
check("asked-instead found 3 times becomes a lesson", any(x["id"] == "s:asked-instead" for x in selfcheck.lessons()))
db.set_feedback(r1["id"], 1); db.set_feedback(r2["id"], 1)
check("the user liked replies flagged for it: their word wins, the lesson goes",
      "asked-instead" in selfcheck.muted() and not any(x["id"] == "s:asked-instead" for x in selfcheck.lessons()))
r3 = reply()
db.set_feedback(r3["id"], -1, "too long")
check("a user's own lesson for the same thing isn't doubled", [x["id"] for x in persona.lessons()].count("d:too-long") == 1
      and not any(x["id"] == "s:too-long" for x in persona.lessons()))
db.set_feedback(r3["id"], 0)

# the lesson log judges self lessons on self-reviews
improve.record(persona.lessons(), now=T0 + N[0] * 60 + 1)
ent = improve._load().get("s:too-long")
check("a self lesson is logged with its baseline from the self-reviews", ent and ent["edits"][-1]["base"]["rated"] >= 3
      and ent["edits"][-1]["base"]["hits"] >= 3)
T0 = max(e["t"] for e in ent["edits"]) + 5 - N[0] * 60  # later reviews come after the lesson was logged
for _ in range(improve.CHECK_AFTER):
    review(reply("4."), grader(score=5))
check("after enough clean replies, the log says the lesson is helping, with no user ratings",
      improve.check()["s:too-long"] == "helping")
for _ in range(improve.CHECK_AFTER):
    review(reply(), grader("too-long"))
check("if the problem keeps happening, it says not helping", improve.check()["s:too-long"] == "not helping")
check("and the prompt states it strictly", "apply it strictly" in persona.feedback_block())

stats = selfcheck.stats()
check("stats: reviews, average score and problems found", stats["reviews"] == selfcheck.SELF_WINDOW and stats["avg_score"]
      and stats["causes"].get("too-long"))
check("acks and proactive texts aren't reviewed", selfcheck.review(db.add_message("theta", "assistant", "On it", {"ack": True})["id"],
                                                                   call=grader()) is None)
print("all selfcheck checks passed")
