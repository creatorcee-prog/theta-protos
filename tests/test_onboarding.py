"""The in-chat intro: hello -> their name (typed) -> Theta's name (tap or type) -> notifications -> Gmail (only when
the server has Google sign-in) -> a first task. Typed answers are taken before the model; anything else goes to
the model as usual. No network: a model call would fail the test."""
import os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_TZ="America/Denver", PROTOS_TICK="0", PROTOS_QUIET="1")
for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
          "GROQ_API_KEY", "LOCAL_LLM_URL", "TAVILY_API_KEY"):
    os.environ.pop(k, None)
from server import app, db, ext, models, onboarding, persona


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
ext.reset()
MODEL_CALLS = []


def no_model(*a, **k):
    MODEL_CALLS.append(a)
    raise models.ModelError("no model in this test")


models.call = no_model
models.stream = no_model if hasattr(models, "stream") else None


def chat(text, show=None):
    ev = []
    app._chat_worker("theta", text, [], None, lambda e, d: ev.append((e, d)), show=show)
    return ev


st = onboarding.public()
check("a new install needs the intro", st["needed"] and st["step"] == "hello" and st["bot_name"] == "Theta")
st, msgs = onboarding.start(tz="America/Phoenix")
check("start posts the hello and asks their name", len(msgs) == 2 and "I'm Theta" in msgs[0]["text"]
      and msgs[0]["meta"].get("proactive") and "call you" in msgs[1]["text"], [m["text"] for m in msgs])
check("the phone's time zone is saved when none was set", db.get_setting("tz") == "America/Phoenix")
st, again = onboarding.start()
check("start again posts nothing new (resumes)", again == [] and st["step"] == "hello")

ev = chat("I'm Cee")
names = [e for e, _ in ev]
done = [d for e, d in ev if e == "done"][-1]
check("a typed name is taken by the intro, not the model", not MODEL_CALLS and names[-1] == "done", names)
check("Theta asks what to call it, with a question card", "call me" in done["text"]
      and done["meta"]["cards"][0]["type"] == "onboarding" and len(done["meta"]["cards"][0]["options"]) == 3, done)
users = [d for e, d in ev if e == "user"]
check("Theta reacts to their answer with a party popper", (users[-1]["meta"].get("reactions") or {}).get("theta") == "🎉", users[-1])
check("their name is remembered", "Name: Cee" in __import__("server.memory", fromlist=["x"]).block())
check("the next text greets them by name", "Nice to meet you, Cee!" in done["text"], done["text"])

ev = chat("let's go with Pip")
acks = [d for e, d in ev if e == "ack"]
done = [d for e, d in ev if e == "done"][-1]
check("a typed name for Theta renames it", db.get_setting("bot_name") == "Pip" and onboarding.bot_name() == "Pip")
check("'Pip it is!' with a Renamed to line", acks and acks[0]["text"].startswith("Pip it is!")
      and acks[0]["meta"]["cards"][0] == {"type": "onboarding_event", "text": "Renamed to Pip", "icon": "pencil"}, acks[:1])
check("then make it yours: color, globe style, dots and opening, as live previews", "make me yours" in done["text"]
      and done["meta"]["cards"][0]["kind"] == "choices" and [r["key"] for r in done["meta"]["cards"][0]["rows"]] == ["accent", "style", "dot", "opening"]
      and all(r.get("preview") for r in done["meta"]["cards"][0]["rows"]),
      [a["text"][:30] for a in acks] + [done["text"][:40]])
st, msgs = onboarding.answer("look", {"accent": "#a78bfa", "style": "lumen", "dot": "star", "opening": "signal", "bogus": "x"})
check("the look is saved for every device (unknown keys ignored)",
      db.get_setting("look") == {"accent": "#a78bfa", "style": "lumen", "dot": "star", "opening": "signal"})
check("then how Theta should talk, with style options", "How should I talk to you?" in msgs[-1]["text"]
      and msgs[-1]["meta"]["cards"][0]["step"] == "style" and len(msgs[-1]["meta"]["cards"][0]["options"]) == 4)
st, msgs = onboarding.answer("style", "concise")
check("the style is saved to Personalization", __import__("server.account", fromlist=["x"]).personalize()["style"] == "concise")
check("then the feel: warmth, enthusiasm, emoji", [r["key"] for r in msgs[-1]["meta"]["cards"][0]["rows"]] == ["warmth", "enthusiasm", "emoji"])
st, msgs = onboarding.answer("vibe", {"warmth": "more", "emoji": "less"})
acc = __import__("server.account", fromlist=["x"])
check("saved to Personalization", acc.personalize()["warmth"] == "more" and acc.personalize()["emoji"] == "less")
check("then phone and email, as fields", [f["key"] for f in msgs[-1]["meta"]["cards"][0]["fields"]] == ["phone", "email"])
out = onboarding.typed("it's (435) 555-0101 and cee@example.com", db.add_message("theta", "user", "x"))
check("typed contact details are understood and saved", out is not None and acc.profile()["phone"] == "+14355550101"
      and acc.profile()["email"] == "cee@example.com")
check("then ground rules, as a checklist with your own words too", onboarding.state()["step"] == "instructions")
onboarding.answer("instructions", ["Disagree with me when I'm wrong, and say why."])
check("rules land in Profile > Instructions", "Disagree with me" in acc.profile()["instructions"])
msgs = db.messages("theta", limit=3)
check("then a little about me, with the notifications question in its card", "A little about me" in msgs[-1]["text"]
      and msgs[-1]["meta"]["cards"][0]["step"] == "notify" and "notification" in msgs[-1]["meta"]["cards"][0]["question"])
check("the system prompt uses the new name", "named you Pip" in persona.system_prompt())
check("the question card shows what was picked", "answered" in db.get_message(onboarding.state()["cards"]["me"])["meta"]["cards"][0])

st, msgs = onboarding.answer("notify", "skip")
check("then alerts near you (Vantage)", st["step"] == "vantage" and msgs[-1]["meta"]["cards"][0]["options"][0]["do"] == "location")
st, msgs = onboarding.answer("vantage", "on")
check("on: Theta may text first", db.get_setting("proactive") is True and st["step"] == "apps")
labels = [o["label"] for o in msgs[-1]["meta"]["cards"][0]["options"]]
check("then which apps to connect (no Google sign-in here, so no Google)", "Bank accounts (read-only)" in labels
      and not any(l.startswith("Google") for l in labels))
st, msgs = onboarding.answer("apps", ["tavily", "bank"])
check("each app picked shows its setup right there", any("bridge.simplefin.org" in m["text"] for m in msgs)
      and any((m["meta"].get("cards") or [{}])[0].get("service") == "tavily" for m in msgs))
check("no Google sign-in on the server: the Gmail step is skipped, and the quiz is offered", st["step"] == "quiz_offer"
      and "quick quiz" in msgs[-1]["text"] and msgs[-1]["meta"]["cards"][0]["step"] == "quiz_offer", [m["text"][:40] for m in msgs])
st, msgs = onboarding.answer("quiz_offer", "skip")
check("'Maybe later' goes straight to the first task", st["done"] and msgs and msgs[-1]["meta"]["cards"][0]["question"] == "Where should we start?",
      [m["text"][:40] for m in msgs])
opts = msgs[-1]["meta"]["cards"][0]["options"]
check("the first-task options send real chat prompts", len(opts) == 3 and all(o.get("chat") for o in opts), opts)
check("once offered, the intro is done and typing goes to the model", onboarding.typed("hello there", None) is None and onboarding.done())

# a tapped option: the chat stores the label, the model gets the prompt
ev = chat(opts[0]["chat"], show=opts[0]["label"])
u = [d for e, d in ev if e == "user"][0]
check("a tapped option shows its label in the chat and keeps the prompt", u["text"] == opts[0]["label"] and u["meta"]["prompt"] == opts[0]["chat"], u)
check("and the intro didn't claim it (it goes the model's way)", not any(e == "route" and d.get("why") == "the intro" for e, d in ev), ev[:3])

# run it again, with Google sign-in set up: the Gmail step appears with a connect card
os.environ.update(GOOGLE_CLIENT_ID="x.apps.googleusercontent.com", GOOGLE_CLIENT_SECRET="s")
MODEL_CALLS.clear()
st, msgs = onboarding.reset()
check("Run the intro again starts over", st["needed"] and st["step"] == "hello" and "I'm Pip" in msgs[0]["text"])
check("a question typed mid-intro goes to the model", onboarding.typed("what can you do?", None) is None)
onboarding.answer("hello", "Cee")
st, msgs = onboarding.answer("me", "skip")
check("skipping the name keeps the current one", onboarding.bot_name() == "Pip" and st["step"] == "look")
for step in ("look", "style", "vibe", "contact", "instructions"):
    onboarding.answer(step, "skip")
onboarding.answer("notify", "on")
onboarding.answer("vantage", "skip")
st, msgs = onboarding.answer("apps", ["google"])
card = msgs[-1]["meta"].get("cards", [{}])[0]
check("with Google sign-in set up: connect Gmail, with its card", st["step"] == "google" and "Connect Gmail" in msgs[-1]["text"]
      and card.get("type") == "connect" and card.get("action") == "/api/google/start", card)
onboarding.typed("just help me plan my week", None)
check("typing instead of connecting ends the intro (the model takes the message)", onboarding.done())

print("all onboarding checks passed")
