"""The get-to-know-you quiz (optional, part of the intro in server/onboarding.py, or on its own from Settings).

Questions come one at a time as cards: tap an answer (A, B, C...), pick several and tap Done, or type the answer in
the chat. Every one can be skipped, and "stop" ends the quiz. What Theta learns goes where Settings shows it:

  - occupation and home: the Profile fields
  - people, goals, interests, food, reminder habits, anything else: "More about you" (one line per topic, so a
    retake replaces a topic instead of piling up)
  - how to come across and emoji: Personalization
  - when the day starts, what eats their time, money and brief wishes: the chip ideas at the end

ideas(answers) turns the answers into suggested chips (built-ins to switch on, and new ones written for them, like
"Catch me up on the Jazz" or "Goal check-in"); the app shows them as a card to add with a tap.
"""
import re

from . import db

# kind: text (typed), one (tap one), many (tap several, then Done)
QUESTIONS = [
    {"id": "work", "kind": "one", "other": True, "q": "What fills your weekdays?",
     "opts": [("Student", "student"), ("A job", "employed"), ("My own business", "business"),
              ("Freelance or creative work", "freelance"), ("Between jobs", "between"), ("Retired", "retired")],
     "ph": "or type it, e.g. nurse, product designer"},
    {"id": "home", "kind": "text", "q": "Where's home? A city is plenty.", "ph": "e.g., St. George, Utah"},
    {"id": "start", "kind": "one", "q": "When does your day usually start?",
     "opts": [("Before 6", "05:30"), ("6 to 8", "07:00"), ("8 to 10", "09:00"), ("Later than that", "10:30")]},
    {"id": "tone", "kind": "one", "q": "How should I come across?",
     "opts": [("Warm and encouraging", "warm"), ("Straight to the point", "direct"), ("Playful", "playful"),
              ("Calm and even", "calm")]},
    {"id": "emoji", "kind": "one", "q": "Emoji in my texts?",
     "opts": [("Love them", "more"), ("Now and then", "default"), ("None, please", "less")]},
    {"id": "time", "kind": "many", "q": "What eats time you'd rather spend elsewhere? Pick any.",
     "opts": [("Email", "email"), ("Scheduling", "schedule"), ("Bills and money", "money"),
              ("Shopping and errands", "shopping"), ("Planning meals", "meals"), ("Keeping up with news", "news")]},
    {"id": "people", "kind": "many", "other": True, "q": "Who matters most day to day? Pick any, or type names.",
     "opts": [("Partner", "partner"), ("Kids", "kids"), ("Parents", "parents"), ("Siblings", "siblings"),
              ("Roommates", "roommates"), ("Coworkers", "coworkers"), ("Close friends", "friends")],
     "ph": "e.g., Ana (sister), Marco (boss)"},
    {"id": "goals", "kind": "many", "other": True, "q": "What are you working toward right now?",
     "opts": [("Getting fit", "fitness"), ("Saving money", "saving"), ("A career move", "career"),
              ("Learning something new", "learning"), ("Better habits", "habits"), ("A big project", "project"),
              ("Travel", "travel")],
     "ph": "e.g., a half marathon in April"},
    {"id": "interests", "kind": "many", "other": True, "q": "What do you follow or love?",
     "opts": [("Sports", "sports"), ("Music", "music"), ("Gaming", "gaming"), ("Tech and AI", "tech"),
              ("Cooking", "cooking"), ("The outdoors", "outdoors"), ("Movies and TV", "screen"), ("Reading", "reading"),
              ("Investing", "investing")],
     "ph": "add specifics, e.g. the Utah Jazz, climbing"},
    {"id": "brief", "kind": "many", "q": "If I sent you a morning brief, what should be in it?",
     "opts": [("Weather", "weather"), ("My calendar", "calendar"), ("Important email", "email"),
              ("News headlines", "news"), ("Scores for my teams", "sports"), ("No brief for me", "none")]},
    {"id": "reminders", "kind": "one", "q": "How do you like reminders?",
     "opts": [("A heads-up well before", "early"), ("Right on time", "ontime"), ("Only for important stuff", "few")]},
    {"id": "money", "kind": "one", "q": "Want help keeping an eye on money?",
     "opts": [("Yes, a weekly check-in", "weekly"), ("Just watch my subscriptions", "subs"), ("No thanks", "no")]},
    {"id": "food", "kind": "many", "other": True, "q": "Any food preferences or allergies?",
     "opts": [("No restrictions", "none"), ("Vegetarian", "vegetarian"), ("Vegan", "vegan"), ("Gluten-free", "gluten"),
              ("Dairy-free", "dairy"), ("Nut allergy", "nuts")],
     "ph": "or type, e.g. I hate cilantro"},
    {"id": "else", "kind": "text", "q": "Last one: anything else I should know about you?",
     "ph": "e.g., I'm a night owl, I have a dog named Juniper"},
]
BY_ID = {q["id"]: q for q in QUESTIONS}
ABOUT_KEYS = {"people": "People", "goals": "Working toward", "interests": "Into", "food": "Food",
              "reminders": "Reminders", "else": "Also", "start": "Day starts"}
REMIND_WORDS = {"early": "likes a heads-up well before", "ontime": "likes them right on time",
                "few": "only for important stuff"}
STOP = re.compile(r"^\s*(stop|enough|that'?s enough|later|maybe later|end( the)? quiz|no more|i'?m done|done)\W*$", re.I)
_STOPWORDS = {"than", "that", "with", "just", "please", "them", "your", "this", "well", "before", "only", "stuff",
              "want", "like", "some", "more", "none", "keep", "help", "time"}
SKIP = re.compile(r"^\s*(skip|pass|next|no|nope|none|n/a|nothing|-)\W*$", re.I)


def _clean(text, cap=300):
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(text or ""))).strip()[:cap]


def label(qid, value):
    """The words for a stored answer (an option's label, or the typed text)."""
    q = BY_ID.get(qid) or {}
    labels = dict((v, k) for k, v in q.get("opts") or [])
    one = lambda v: str(v)[7:] if str(v).startswith("other: ") else labels.get(v, str(v))  # noqa: E731
    if isinstance(value, list):
        return ", ".join(one(v) for v in value)
    return one(value)


def others(value):
    """The words they typed themselves ("other: ..."), joined."""
    vals = value if isinstance(value, list) else [value]
    return ", ".join(str(v)[7:] for v in vals if str(v).startswith("other: "))


def card(qid, n, total):
    """The question card for the app (step "quiz"; q says which question)."""
    q = BY_ID[qid]
    c = {"type": "onboarding", "step": "quiz", "q": qid, "question": q["q"], "count": f"{n} of {total}",
         "dismiss": True, "hint": "Or type your answer in the chat", "options": []}
    if q["kind"] == "text":
        c["placeholder"] = q.get("ph", "")
        c["hint"] = "Type your answer in the chat below, or skip"
    else:
        c["options"] = [{"label": k, "answer": v} for k, v in q["opts"]]
        c["multi"] = q["kind"] == "many"
        if q.get("other"):
            c["other"] = True
            c["placeholder"] = q.get("ph", "")
            c["hint"] = "Pick, or type your own in the chat"
    c["stop"] = True
    return c


def parse_typed(qid, text):
    """A typed answer for this question: the text, an option it names, or "skip"/"stop". None = not an answer."""
    t = str(text or "").strip()
    if STOP.match(t):
        return "stop"
    if SKIP.match(t):
        return "skip"
    q = BY_ID[qid]
    if q["kind"] == "text":
        if len(t) > 400 or t.endswith("?"):
            return None  # a question for Theta, not an answer: the model takes it, and the quiz waits
        return _clean(t)
    low = t.lower()
    words = set(re.findall(r"[a-z0-9']+", low))
    toks = [x for x in re.split(r"[\s,&.;]+|\band\b", low) if x]
    letters_only = bool(toks) and all(len(x) == 1 and x.isalpha() for x in toks)  # "b" or "a, c" or "a and d"
    picks = []
    for i, (k, v) in enumerate(q["opts"]):
        letter = chr(97 + i)
        keys = {w for w in re.findall(r"[a-z0-9']+", k.lower()) if len(w) > 3 and w not in _STOPWORDS} | {v.lower()}
        if (letters_only and letter in words) or k.lower() in low or keys & words:
            picks.append(v)
    if not picks:
        if not q.get("other") or len(t) > 300 or t.endswith("?"):
            return None
        return ["other: " + _clean(t)] if q["kind"] == "many" else "other: " + _clean(t, 80)
    if q.get("other") and q["kind"] == "many" and not letters_only and len(t.split()) > len(picks) * 3:
        picks.append("other: " + _clean(t))  # "my sister Ana and coworkers": keep their words too, names matter
    return picks if q["kind"] == "many" else picks[0]


def _about_set(key, value):
    """Put one 'Label: value' line in the profile's More about you (replacing that label's old line)."""
    from . import account
    p = account.profile()
    lines = [ln for ln in (p.get("about") or "").split("\n") if ln.strip() and not ln.startswith(key + ":")]
    if value:
        lines.append(f"{key}: {value}")
    about = "\n".join(lines)[-1500:]
    account.save_profile({"about": about})


def apply(qid, value):
    """Store one answer where it belongs. value is the text, an option value, or a list of them."""
    from . import account
    if value in (None, "", "skip", []):
        return
    if qid == "work":
        account.save_profile({"occupation": _clean(label("work", value), 80)})
    elif qid == "home":
        account.save_profile({"home": _clean(value, 80)})
    elif qid in ("people", "goals", "interests", "food", "else"):
        _about_set(ABOUT_KEYS[qid], _clean(label(qid, value), 300))
    elif qid == "reminders":
        _about_set(ABOUT_KEYS[qid], REMIND_WORDS.get(value, _clean(value, 80)))
    elif qid == "start":
        db.set_setting("day_start", value if re.fullmatch(r"\d\d:\d\d", str(value)) else None)
        _about_set(ABOUT_KEYS[qid], label("start", value).lower())
    elif qid == "tone":
        account.save_personalize({"warm": {"warmth": "more"}, "direct": {"style": "concise", "warmth": "less"},
                                  "playful": {"enthusiasm": "more", "style": "casual"},
                                  "calm": {"enthusiasm": "less"}}.get(value, {}))
    elif qid == "emoji" and value in ("more", "default", "less"):
        account.save_personalize({"emoji": value})


def _t(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def ideas(ans):
    """Suggested chips from the answers: [{id, name, icon, when, prompt, steps, builtin?}] (built-ins by id only)."""
    ans = {k: v for k, v in (ans or {}).items() if v not in ("skip", None, "", [])}
    out = []
    time_ = set(ans.get("time") or [])
    brief = [b for b in (ans.get("brief") or []) if b != "none"]
    start = ans.get("start") if re.fullmatch(r"\d\d:\d\d", str(ans.get("start") or "")) else None
    iv = ans.get("interests") or []
    interests = _clean(others(iv) or label("interests", iv) if iv else "", 120)
    teams = _clean(others(iv), 80) if iv else ""
    goals = _clean(label("goals", ans["goals"]), 160) if ans.get("goals") else ""
    people = _clean(label("people", ans["people"]), 200) if ans.get("people") else ""
    if brief:
        parts = {"weather": "Weather where they are: high, low, anything to plan around", "calendar": "Today's calendar, with times",
                 "email": "Email that needs them (at most 3, one line each)", "news": "3 news headlines that matter",
                 "sports": "Last night's scores and today's games for " + (teams or "their teams")}
        at = f" around {_t(start)}" if start else ""
        out.append({"id": "morning-brief", "name": "Morning brief", "icon": "☀️", "builtin": True,
                    "when": "They ask for their brief or a rundown of the day.",
                    "prompt": "Give me my morning brief.",
                    "steps": "Keep it short and scannable, bold the times. Include, in this order:\n" + "\n".join(
                        f"{i}. {parts[b]}." for i, b in enumerate(brief, 1)) +
                    f"\nThey'd like it{at} each morning: offer once to make it a daily routine if it isn't one."})
    if "email" in time_:
        out.append({"id": "inbox-sweep", "builtin": True})
    if "money" in time_ or ans.get("money") in ("weekly", "subs"):
        out.append({"id": "money-check", "builtin": True})
    if "shopping" in time_:
        out.append({"id": "best-price", "builtin": True})
    if "schedule" in time_:
        out.append({"id": "plan-my-day", "builtin": True})
        out.append({"id": "find-a-time", "name": "Find a time", "icon": "🕑",
                    "when": "They need to schedule something with someone or fit something in.",
                    "prompt": "Find a time for ",
                    "steps": ("1. Check their calendar for the next 7 days.\n2. Offer the 3 best open slots, "
                              "avoiding early mornings and late evenings unless they said otherwise.\n3. When they "
                              "pick one, add it to the calendar; if others are invited, draft the invite for their OK.")})
    if "meals" in time_:
        food = _clean(label("food", ans["food"]), 120) if ans.get("food") and ans["food"] != ["none"] else ""
        out.append({"id": "meal-plan", "name": "Meal plan", "icon": "🥘",
                    "when": "They ask what to cook, want a meal plan or a grocery list.",
                    "prompt": "Plan my dinners for this week.",
                    "steps": ("1. Plan 5 weeknight dinners, 30 minutes or less, reusing ingredients across days."
                              + (f" Respect this: {food}." if food else "") +
                              "\n2. One line per dinner.\n3. Then a grocery list grouped by store section.\n"
                              "4. Save the plan with plan_update so they can check things off.")})
    if "news" in time_ or "news" in brief:
        topic = interests or "the topics they care about"
        out.append({"id": "news-digest", "name": "News digest", "icon": "📰",
                    "when": "They ask what's going on in the world or want the news.",
                    "prompt": "What's the news today?",
                    "steps": (f"1. Search the last 24 hours of news, weighted to {topic}.\n2. Pick the 5 stories "
                              "that matter most, one or two lines each, with sources cited.\n3. Skip celebrity "
                              "gossip and repeats of yesterday's stories.")})
    if teams or (isinstance(iv, list) and "sports" in iv):
        first = re.split(r",| and |;", teams)[0].strip()[:40] if teams else "my teams"
        if first:
            out.append({"id": "catch-up-" + re.sub(r"[^a-z0-9]+", "-", first.lower()).strip("-")[:30],
                        "name": f"Catch me up on {first}", "icon": "⚡",
                        "when": f"They ask what's new with {first}.",
                        "prompt": f"Catch me up on {first}.",
                        "steps": (f"1. Search the latest on {first} (scores, results, news or releases, whatever "
                                  "fits).\n2. Give 3 to 5 bullets, newest first, with sources.\n3. End with "
                                  "what's coming up next, with the date.")})
    if goals:
        out.append({"id": "goal-check-in", "name": "Goal check-in", "icon": "🎯",
                    "when": "They ask how they're doing on their goals, or it's their weekly check-in.",
                    "prompt": "Let's do my goal check-in.",
                    "steps": (f"Their goal: {goals}\n1. Ask what they did toward it this week (one question, not "
                              "a list).\n2. Say honestly whether they're on track and the one next step that matters "
                              "most.\n3. Offer to set a reminder for that step.")})
    if people:
        out.append({"id": "keep-in-touch", "name": "Keep in touch", "icon": "💬",
                    "when": "They want to stay in touch with people, or ask who they haven't talked to.",
                    "prompt": "Who should I check in with this week?",
                    "steps": (f"The people who matter to them: {people}\n1. Pick 1 to 3 they haven't mentioned in a "
                              "while (search past chats).\n2. Suggest a short, natural message for each, in their "
                              "voice.\n3. If a contact is saved and they say yes, text it for them.")})
    seen, uniq = set(), []
    for c in out:
        if c["id"] not in seen:
            seen.add(c["id"])
            uniq.append(c)
    return uniq[:8]


def summary(ans):
    """What Theta learned, as a short message."""
    lines = []
    for qid in ("work", "home", "people", "goals", "interests", "food"):
        if ans.get(qid) and ans[qid] != "skip":
            name = {"work": "You do", "home": "Home", "people": "Your people", "goals": "Working toward",
                    "interests": "You're into", "food": "Food"}[qid]
            lines.append(f"- **{name}:** {label(qid, ans[qid])}")
    for qid, name in (("tone", "I'll come across"), ("emoji", "Emoji"), ("reminders", "Reminders")):
        if ans.get(qid) and ans[qid] != "skip":
            lines.append(f"- **{name}:** {label(qid, ans[qid]).lower()}")
    if not lines:
        return "No problem. You can tell me about yourself any time, or fill it in under Settings > Profile."
    return ("Here's what I've got:\n\n" + "\n".join(lines) +
            "\n\nIt's all in Settings > Profile and Personalization if you want to change anything.")
