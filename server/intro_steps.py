"""The intro's setup steps that fill in Settings (server/onboarding.py runs them in order):

    look          Make it yours: accent color, the globe's dots, how Theta opens (a "choices" card; saved in the
                  "look" setting, which every device picks up)
    vibe          warmth, enthusiasm, emoji (a "choices" card) -> Settings > Personalization
    contact       your phone and email (a "fields" card, or type them) -> Settings > Profile
    instructions  ground rules for Theta, as a checklist plus your own words -> Profile > Instructions
    vantage       share your (rounded) location for alerts near you, and let Theta text first
    apps          which apps to connect: Google, bank, calls and texts, passwords, live search, images; each one
                  picked gets its connect card or its steps right there (Google then waits in its own step)

Each takes a card answer (a dict, a list or a word), or "skip".
"""
import re

from . import db

ACCENTS = [("Sky", "#4fd3ff"), ("Violet", "#a78bfa"), ("Mint", "#4ade80"), ("Amber", "#fbbf24"), ("Rose", "#fb7185"),
           ("White", "#f4f4f5")]
DOTS = [("Circles", "circle"), ("Stars", "star"), ("Diamonds", "diamond"), ("Hexagons", "hexagon"), ("Triangles", "triangle"),
        ("Squares", "square"), ("Pentagons", "pentagon")]
OPENINGS = [("Converge", "converge"), ("Signal", "signal")]
STYLES = [("Urchin", "urchin"), ("Precision", "precision"), ("Lumen", "lumen"), ("Flow", "flow"), ("Signal", "signal"),
          ("Rings", "rings"), ("Ribbons", "ribbons"), ("Horizon", "horizon"), ("Plasma", "plasma"), ("Liquid", "liquid"),
          ("Nebula", "nebula")]  # theta-app's avatar styles (web/orb.js draws them)
_LOOK = (("accent", ACCENTS), ("style", STYLES), ("dot", DOTS), ("opening", OPENINGS))
LEVELS = [("Less", "less"), ("Default", "default"), ("More", "more")]
RULES = [("Disagree with me when I'm wrong", "Disagree with me when I'm wrong, and say why."),
         ("Keep answers short", "Keep answers short unless I ask for more."),
         ("Show sources for facts", "Give sources for facts and numbers."),
         ("Ask before spending money", "Always ask before spending any money."),
         ("Don't text me at night", "Don't text me between 10 PM and 7 AM unless it's urgent."),
         ("Explain things simply", "Explain things simply, without jargon.")]
APPS = [("google", "Google: Gmail, Calendar, Drive"), ("bank", "Bank accounts (read-only)"),
        ("twilio", "Phone calls and texts"), ("passwords", "Passwords: 1Password or Bitwarden"),
        ("tavily", "Faster live search"), ("gemini", "Making images")]


def look():
    v = db.get_setting("look")
    v = v if isinstance(v, dict) else {}
    return {k: v.get(k) if v.get(k) in {val for _, val in opts} else None for k, opts in _LOOK}


def save_look(body):
    cur = look()
    for k, opts in _LOOK:
        if k in body and body[k] in {val for _, val in opts}:
            cur[k] = body[k]
    db.set_setting("look", cur)
    return cur


def _connected(svc):
    try:
        if svc == "google":
            from . import google
            return google.connected()
        if svc == "bank":
            from . import bank
            return bank.connected()
        if svc == "twilio":
            from . import telco
            return telco.configured()
        if svc == "passwords":
            from . import vault
            return vault.available()
        if svc == "tavily":
            import os
            return bool((os.environ.get("TAVILY_API_KEY") or "").strip())
        if svc == "gemini":
            import os
            return bool((os.environ.get("GEMINI_API_KEY") or "").strip())
    except Exception:  # noqa: BLE001
        return False
    return False


def card(step, s):
    """[(text, cards)] for one of these steps."""
    q = lambda **k: dict({"type": "onboarding", "step": step, "dismiss": True, "options": []}, **k)  # noqa: E731
    if step == "look":
        cur = look()
        return [("Let's make me yours. Swipe through each row and tap the one you like: you'll see it live. You can "
                 "change these any time in Settings > General.",
                 [q(kind="choices", rows=[  # preview: the app shows each option as a live globe to swipe through
                     {"key": k, "label": label, "preview": k, "swatch": k == "accent",
                      "value": cur[k] or opts[0][1], "options": [{"label": n, "value": v} for n, v in opts]}
                     for (k, opts), label in zip(_LOOK, ("Color", "Style", "Dots", "Opening"))], done="Looks good")])]
    if step == "vibe":
        from . import account
        p = account.personalize()
        return [("And the feel of how I talk:",
                 [q(kind="choices", rows=[
                     {"key": k, "label": label, "value": p[k], "options": [{"label": a, "value": b} for a, b in LEVELS]}
                     for k, label in (("warmth", "Warmth"), ("enthusiasm", "Enthusiasm"), ("emoji", "Emoji"))],
                    done="Done")])]
    if step == "contact":
        from . import account
        p = account.profile()
        return [("What's your phone number and email? I text and call you on that number (only you), and use the "
                 "email for things you ask me to send yourself. Type them, or fill these in.",
                 [q(kind="fields", fields=[
                     {"key": "phone", "label": "Phone", "type": "tel", "value": p.get("phone") or "",
                      "placeholder": "+1 435 555 0101", "autocomplete": "tel"},
                     {"key": "email", "label": "Email", "type": "email", "value": p.get("email") or "",
                      "placeholder": "you@example.com", "autocomplete": "email"}], done="Save")])]
    if step == "instructions":
        return [("Any ground rules for me? Pick any, or type your own.",
                 [q(options=[{"label": a, "answer": b} for a, b in RULES], multi=True, other=True,
                    hint="Or type your own rules in the chat")])]
    if step == "vantage":
        return [("I can keep an eye on what's happening around you (storms, emergencies, big events nearby) and "
                 "text you first when something matters. That uses your location, rounded to about 10 km.",
                 [q(question=None, options=[{"label": "Turn on alerts near me", "answer": "on", "do": "location"},
                                            {"label": "Not now", "answer": "skip"}], dismiss=False)])]
    if step == "apps":
        opts = [{"label": label + (" (connected)" if _connected(svc) else ""), "answer": svc}
                for svc, label in APPS if not (svc == "google" and not _google_ready())]
        return [("Which of these should I connect? Pick any. Each one shows its setup right here, and you can do "
                 "them later from Settings > Apps.", [q(options=opts, multi=True)])]
    return []


def _google_ready():
    try:
        from . import google
        return google.configured()
    except Exception:  # noqa: BLE001
        return False


_PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


def parse_contact(text):
    """{phone?, email?} found in what they typed."""
    out = {}
    m = _EMAIL.search(text or "")
    if m:
        out["email"] = m.group(0).strip(".,;")
    m = _PHONE.search(_EMAIL.sub(" ", text or ""))
    if m:
        out["phone"] = m.group(0)
    return out


def apply(step, ans, s):
    """Save one answer. Returns [(text, cards)] Theta says back (may be empty). Raises ValueError."""
    from . import account
    out = []
    if step == "look":
        if isinstance(ans, dict):
            save_look(ans)
    elif step == "vibe":
        if isinstance(ans, dict):
            account.save_personalize({k: v for k, v in ans.items() if k in ("warmth", "enthusiasm", "emoji")
                                      and v in ("less", "default", "more")})
    elif step == "contact":
        body = ans if isinstance(ans, dict) else parse_contact(str(ans))
        body = {k: str(v).strip() for k, v in body.items() if k in ("phone", "email") and str(v or "").strip()}
        if not body:
            raise ValueError("type your phone number or email (or both), or skip")
        account.save_profile(body)
    elif step == "instructions":
        rules = [str(a) for a in (ans if isinstance(ans, list) else [ans]) if a and a not in ("skip",)]
        if rules:
            cur = account.profile().get("instructions") or ""
            lines = [ln for ln in cur.split("\n") if ln.strip()]
            for r in rules:
                r = r[7:] if r.startswith("other: ") else r
                if r and r not in lines:
                    lines.append(r[:300])
            account.save_profile({"instructions": "\n".join(lines)[-1500:]})
    elif step == "vantage":
        on = ans in ("on", True, "yes")
        s["answers"]["vantage"] = "on" if on else "off"
        db.set_setting("proactive", True) if on else None
    elif step == "apps":
        picked = [a for a in (ans if isinstance(ans, list) else []) if a in {k for k, _ in APPS}]
        s["answers"]["apps"] = picked
        for svc in picked:
            if svc == "google" or _connected(svc):
                continue  # Google gets its own step next (it waits for the sign-in)
            out.append(_setup(svc))
    return [o for o in out if o]


def _setup(svc):
    """(text, cards) that set up one app."""
    if svc == "bank":
        return ("**Bank accounts:** link your banks at bridge.simplefin.org (read-only; SimpleFIN charges a small fee), make "
                "a setup token there, and paste it in Settings > Apps > Bank accounts.",
                [{"type": "onboarding_event", "text": "Settings > Apps > Bank accounts", "icon": "check"}])
    if svc == "passwords":
        return ("**Passwords:** for 1Password, make a service account for one vault and add OP_SERVICE_ACCOUNT_TOKEN "
                "on Railway. For Bitwarden, add BW_CLIENTID, BW_CLIENTSECRET and BW_PASSWORD. Either way I fill your "
                "logins in my browser and never see them.", [])
    try:
        from . import cards
        c = cards.connect(svc)
        return (f"**{c['name']}:** {c['why']}", [c])
    except Exception:  # noqa: BLE001
        return None


def typed(step, text):
    """A typed answer for these steps, or None to let the model have the message."""
    t = (text or "").strip()
    if re.match(r"^(skip|no|nope|not now|later|pass)\W*$", t, re.I):
        return "skip"
    if step == "contact":
        got = parse_contact(t)
        return got or None
    if step == "instructions":
        if len(t) > 400 or t.endswith("?"):
            return None
        return ["other: " + t]
    return None
