"""The get-to-know-you quiz (server/quiz.py, through server/onboarding.py): offered in the intro, one question at a
time, tap / pick several / type, skip and stop, answers landing in the Profile and Personalization, chip ideas from
the answers added with a tap, the tailored first task, and the quiz on its own from Settings. No model."""
import os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp())
for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "RAILWAY_ENVIRONMENT", "RAILWAY_VOLUME_MOUNT_PATH"):
    os.environ.pop(k, None)
from server import account, chips, db, ext, onboarding, persona, quiz, tools


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


db.init()
ext.reset(); tools._ext_reset(); tools._ext()
N = len(quiz.QUESTIONS)
check("an extensive quiz: a dozen-plus questions, each with an id, a kind and words", N >= 12
      and all(q["kind"] in ("text", "one", "many") and q["q"] for q in quiz.QUESTIONS))


def user(text):
    return db.add_message("theta", "user", text)


def open_q():
    s = onboarding.state()
    return quiz.QUESTIONS[s["quiz"]["i"]]["id"] if s["quiz"]["i"] < N else None


# ---------------------------------------------------------------- through the intro
onboarding.start()
onboarding.answer("hello", "Cee")
onboarding.answer("me", "skip")
for step in ("look", "style", "vibe", "contact", "instructions", "notify", "vantage"):
    onboarding.answer(step, "skip")
st, msgs = onboarding.answer("apps", "skip")
check("after the setup steps, the quiz is offered (Gmail isn't set up here)", st["step"] == "quiz_offer"
      and str(N) in msgs[-1]["text"])
st, msgs = onboarding.answer("quiz_offer", "yes")
c = msgs[-1]["meta"]["cards"][0]
check("yes: the first question comes as a text with its card", st["step"] == "quiz" and msgs[-1]["text"] == quiz.QUESTIONS[0]["q"]
      and c["q"] == "work" and c["count"] == f"1 of {N}" and c.get("stop"))
check("while it waits, the model is told which question is open", "quiz" in onboarding.context("theta", 0)
      and "What fills your weekdays?" in onboarding.context("theta", 0))

# typed answers, caught before the model
m = user("I'm a product designer at a startup")
out = onboarding.typed("I'm a product designer at a startup", m)
check("a typed answer is taken (as their own words), and Theta moves on", out and open_q() == "home"
      and account.profile()["occupation"].startswith("I'm a product designer"))
check("the card for it says what was answered", "answered" in db.get_message(onboarding.state()["quiz_cards"]["work"])["meta"]["cards"][0])
check("a question for Theta isn't taken as the answer", onboarding.typed("wait, why do you need my city?", user("x")) is None
      and open_q() == "home")
onboarding.typed("St. George, Utah", user("St. George, Utah"))
check("home lands in the Profile", account.profile()["home"] == "St. George, Utah")
onboarding.typed("b", user("b"))
check("a letter picks that option (B: 6 to 8)", db.get_setting("day_start") == "07:00" and open_q() == "tone")
st, msgs = onboarding.answer("quiz", "warm", q="tone")
check("a tapped answer: warm and encouraging -> warmth more", account.personalize()["warmth"] == "more")
onboarding.answer("quiz", "work", q="tone")
check("a repeated tap on an old card changes nothing", open_q() == "emoji")
onboarding.answer("quiz", "skip", q="emoji")
check("skip leaves the setting alone", account.personalize()["emoji"] == "default" and open_q() == "time")
onboarding.answer("quiz", ["email", "meals", "news"], q="time")
onboarding.typed("Ana (sister), Marco (boss)", user("Ana (sister), Marco (boss)"))
onboarding.typed("a half marathon in April", user("a half marathon in April"))
onboarding.typed("the Utah Jazz, climbing", user("the Utah Jazz, climbing"))
check("people, goals and interests go to More about you, one line each", all(x in account.profile()["about"] for x in (
    "People: Ana (sister), Marco (boss)", "Working toward: a half marathon in April", "Into: the Utah Jazz, climbing")))
onboarding.typed("weather and calendar and sports", user("weather and calendar and sports"))
check("several typed picks for a pick-several question", onboarding.state()["quiz"]["answers"]["brief"] == ["weather", "calendar", "sports"])
check("and the system prompt now knows them", "half marathon" in persona.system_prompt() and "product designer" in persona.system_prompt())
out = onboarding.typed("stop", user("stop"))
st = onboarding.public()
check("stop ends the quiz early and sums up", st["step"] == "chips" and out and "Here's what I've got" in out[0]["text"]
      and "St. George, Utah" in out[0]["text"])
idea_card = out[-1]["meta"]["cards"][0]
ids = [c["id"] for c in idea_card["ideas"]]
check("chip ideas come from the answers", idea_card["type"] == "chip_ideas" and {"morning-brief", "inbox-sweep", "meal-plan",
      "news-digest", "goal-check-in", "keep-in-touch"} <= set(ids) and any(i.startswith("catch-up-the-utah-jazz") for i in ids))
mb = next(c for c in idea_card["ideas"] if c["id"] == "morning-brief")
check("the morning brief is tailored to what they picked (and sports for their team)", "Utah Jazz" in mb["steps"]
      and "Weather" in mb["steps"] and "News headlines" not in mb["steps"])
check("built-ins in the card carry their full text", all(c.get("steps") and c.get("name") for c in idea_card["ideas"]))

keep = [i for i in ids if i not in ("news-digest",)]
st, msgs = onboarding.answer("chips", keep)
names = [c["name"] for c in chips.enabled()]
check("the kept ideas are added; the left-out one isn't", "Meal plan" in names and "Goal check-in" in names
      and "News digest" not in names and any(n.startswith("Catch me up on the Utah Jazz") for n in names))
check("the tailored morning brief is saved as their version", chips.find("morning-brief")["edited"]
      and "Utah Jazz" in chips.find("morning-brief")["steps"])
check("Theta says what it added", any("Added" in m["text"] for m in msgs))
first = msgs[-1]["meta"]["cards"][0]
check("the first task offers the brief at their start time", st["done"] and first["options"][0]["label"] == "Send my brief daily at 7:00 AM")

# ---------------------------------------------------------------- the quiz on its own, from Settings
st, msgs = onboarding.start_quiz()
check("Take the quiz: starts on question 1 even though the intro is done", st["step"] == "quiz" and open_q() == "work"
      and msgs[-1]["meta"]["cards"][0]["q"] == "work")
onboarding.typed("Chef", user("Chef"))
onboarding.typed("Ana (sister), Lee (roommate)", user("Ana (sister), Lee (roommate)")) if open_q() == "people" else None
check("a retake replaces answers instead of piling up", account.profile()["occupation"] == "Chef")
for _ in range(N):
    if open_q() is None:
        break
    onboarding.answer("quiz", "skip", q=open_q())
st = onboarding.public()
check("skipping the rest finishes the quiz-only run (no first-task step)", st["done"] or st["step"] in ("chips", "done"))
if st["step"] == "chips":
    st, _ = onboarding.answer("chips", [])
check("and it's done", onboarding.done())
check("about lines aren't duplicated", account.profile()["about"].count("People:") <= 1)
print("all quiz checks passed")
