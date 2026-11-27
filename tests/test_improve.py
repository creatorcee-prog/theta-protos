"""The self-improvement log (server/improve.py, after arXiv 2611.18856's Self-Improvement Memory): a lesson is
recorded as an edit with its prediction and a baseline; after enough newer rated replies it gets a verdict; one that
isn't helping is stated more strictly in the instructions; history is appended, never rewritten; a lesson learned
with another model is marked for a re-check."""
import os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp())
from server import db, improve, persona


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


db.init()
T = time.time() - 10000
n = [0]


def vote(v, reason="", dt=0.0):
    n[0] += 1
    m = db.add_message("theta", "assistant", f"reply {n[0]}")
    db.add_feedback(m["id"], v, reason) if hasattr(db, "add_feedback") else db.set_feedback(m["id"], v, reason)
    db._conn().execute("UPDATE feedback SET t = ?, model = 'deepseek-chat' WHERE message_id = ?", (T + dt, m["id"]))


def turn(model):
    db._conn().execute("INSERT INTO turns (t, bot, model) VALUES (?, 'theta', ?)", (time.time(), model))


turn("deepseek-chat")
reason = persona.REASONS[0][0]
for i in range(4):
    vote(1, "", i)
vote(-1, reason, 5)
vote(-1, reason, 6)
les = persona.lessons()
check("a dislike reason becomes a lesson", les and les[0]["id"].startswith("d:"))
sim = improve.record(les, now=T + 7)
e = sim[les[0]["id"]]["edits"][-1]
check("recorded as an edit: its text, a prediction made before, and a baseline", e["text"] == les[0]["text"]
      and "fewer" in e["predicted"] and e["base"] == {"rated": 6, "hits": 2} and e["model"] == "deepseek-chat")
check("too early to tell at first", improve.check()[les[0]["id"]] == "early")

for i in range(8):  # afterwards: the same complaint keeps coming
    vote(-1 if i % 2 else 1, reason if i % 2 else "", 10 + i)
st = improve.check(now=T + 30)
check("it came back as often: not helping", st[les[0]["id"]] == "not helping")
check("so the instructions state it more strictly", any("apply it strictly" in ln for ln in improve.prompt_notes(persona.lessons())))
check("the observed outcome is kept on the edit", improve._load()[les[0]["id"]]["edits"][-1]["observed"]["verdict"] == "not helping")

before = len(improve._load()[les[0]["id"]]["edits"])
improve.record([{"id": les[0]["id"], "text": les[0]["text"] + " (reworded)"}], now=T + 40)
check("a changed lesson is a new edit under the same cause; the old one stays", len(improve._load()[les[0]["id"]]["edits"]) == before + 1)

for i in range(9):  # after the new edit: no more complaints
    vote(1, "", 50 + i)
check("then the complaint stops: helping", improve.check(now=T + 70)[les[0]["id"]] == "helping")
turn("claude-x")
check("a different model answering now: marked for a re-check", improve.check()[les[0]["id"]] == "recheck")
check("Settings' lesson list carries the status", improve.summary()[les[0]["id"]]["status"] == "recheck")
print("all improve checks passed")
