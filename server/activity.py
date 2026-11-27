"""What Theta is doing right now, in plain words, for the status line under the working globe ("Drafting an
email to Sam", "Reading Megaplex Theatres", "Clicking Showtimes"). agent.py emits one per tool call:

    emit("activity", {"id", "text", "state": "start"|"done", "kind", "ok"?})

and a tool can add a step of its own through ctx["activity"](text, kind) (browse_open says "Reading <the page's
title>" once the page is in). The texts of a turn go on the reply as meta.activity, and the app turns them into
"Took 6s · read your inbox, drafted an email" under it.

Honest and safe: the words say what is really happening, and never carry a message body, typed text, a URL path,
or anything that looks like a secret or a long number. Names come from saved contacts when they can.
"""
import re
import threading
import urllib.parse

KINDS = ("think", "search", "read", "write", "browse", "helpers", "call", "image", "send")
MAX_TEXTS = 40

_SECRETISH = re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[abp]|AIza|ya29|ops)[-_.A-Za-z0-9]{6,}|\b[A-Za-z0-9_\-+/=]{24,}"
                        r"|(?:\+?\d[ ().-]?){9,}\d\b|(?i:\b(?:password|passwd|pwd|token|secret|api[_ -]?key)\b\s*[:=]?\s*\S+)")


def safe_words(text, cap=48):
    """A short, single-line, secret-free version of some words (a search, a label, a title)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = _SECRETISH.sub("…", t)
    t = re.sub(r"[<>`*_\[\]{}|\\]", "", t)
    if len(t) > cap:
        t = t[:cap].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"
    return t


def host(url):
    u = str(url or "").strip()
    if re.match(r"^[a-z][a-z0-9+.-]*:(?!\d)", u, re.I) and not re.match(r"^https?://", u, re.I):
        return ""
    if u and "://" not in u:
        u = "https://" + u
    try:
        h = (urllib.parse.urlsplit(u).hostname or "").lower()
    except ValueError:
        h = ""
    h = h[4:] if h.startswith("www.") else h
    return h if re.fullmatch(r"[a-z0-9.-]{1,80}", h or "") else ""


def who(to):
    """A person for "to": the saved contact's name, else the email's name part, else 'a number ending 1234'."""
    raw = to[0] if isinstance(to, list) and to else to
    raw = str(raw or "").strip()
    if not raw:
        return ""
    try:
        from . import contacts
        hit = contacts.find(raw) if hasattr(contacts, "find") else None
        if isinstance(hit, list):
            hit = hit[0] if hit else None
        if isinstance(hit, dict) and hit.get("name"):
            name = safe_words(hit["name"], 30)
            return name + (f" and {len(to) - 1} more" if isinstance(to, list) and len(to) > 1 else "")
    except Exception:  # noqa: BLE001
        pass
    if "@" in raw:
        name = raw.split("@", 1)[0]
        out = safe_words(name, 30) if not re.search(r"\d{4,}", name) else raw.split("@", 1)[1]
    else:
        digits = re.sub(r"\D", "", raw)
        out = f"the number ending {digits[-4:]}" if len(digits) >= 7 else safe_words(raw, 30)
    return out + (f" and {len(to) - 1} more" if isinstance(to, list) and len(to) > 1 else "")


def _q(text, cap=40):
    t = safe_words(text, cap)
    return f"“{t}”" if t else ""


def _ref_label(ref, ctx):
    try:
        from . import browser
        return safe_words(browser.ref_label(ctx, ref), 36)
    except Exception:  # noqa: BLE001
        return ""


def _browse_act(args, ctx):
    acts = [a for a in (args.get("actions") or []) if isinstance(a, dict)]
    if not acts:
        return "Using the page"
    a = acts[0]
    do = str(a.get("do") or "").lower()
    label = _ref_label(a.get("ref"), ctx) if a.get("ref") else ""
    lab = f"“{label}”" if label else ""
    if do == "click":
        out = f"Clicking {lab}" if lab else "Clicking on the page"
    elif do == "type":  # never the typed text itself
        out = f"Filling in {lab}" if lab else "Typing on the page"
    elif do == "select":
        pick = safe_words(a.get("text"), 30) if a.get("text") and str(a.get("text")).lower() not in ("on", "off", "true", "false") else ""
        out = f"Picking {_q(pick)}" if pick else (f"Choosing {lab}" if lab else "Picking an option")
    elif do == "hover":
        out = f"Opening the {lab} menu" if lab else "Opening a menu"
    elif do == "key":
        out = f"Pressing {safe_words(a.get('text'), 12)}"
    elif do == "scroll":
        out = "Scrolling the page"
    elif do == "wait":
        out = "Waiting for the page to load"
    elif do == "upload":
        out = f"Attaching your photo to {lab}" if lab else "Attaching your photo"
    elif do == "back":
        out = "Going back a page"
    else:
        out = "Using the page"
    if len(acts) > 1:
        out += f" (+{len(acts) - 1} more)"
    return out


def _n(ids, query, one, many):
    if isinstance(ids, list) and ids:
        return f"{len(ids)} {one if len(ids) == 1 else many}"
    return f"{many} matching {_q(query)}" if query else many


_FIXED = {
    "gmail_read": ("Reading an email", "read"),
    "calendar_list": ("Checking your calendar", "read"),
    "drive_read": ("Reading a file from your Drive", "read"),
    "drive_list": ("Looking through your Drive", "read"),
    "routine_list": ("Checking your routines", "read"),
    "workflow_list": ("Checking your workflows", "read"),
    "vantage_now": ("Checking what's happening around you", "read"),
    "browse_screenshot": ("Taking a picture of the page", "browse"),
    "bank_accounts": ("Checking your bank balances", "read"),
    "plan_update": ("Updating your plan", "write"),
    "remind_me": ("Setting the reminder", "write"),
    "react": ("Reacting", "write"),
    "show_card": ("Making a card", "write"),
    "vault_logins": ("Checking your saved logins", "read"),
}


def describe(name, args=None, ctx=None):
    """(text, kind) for one tool call. Unknown tools get "Using <tool name in words>"."""
    a = args if isinstance(args, dict) else {}
    name = str(name or "")
    try:
        if name == "web_search":
            return (f"Searching the web for {_q(a.get('query'))}" if a.get("query") else "Searching the web"), "search"
        if name == "research":
            n = len([x for x in (a.get("angles") or []) if str(x or "").strip()])
            return (f"Sending {n} helpers to dig into it" if n > 1 else "Digging into it"), "helpers"
        if name == "history_search":
            return f"Looking back through our chats for {_q(a.get('query'))}", "read"
        if name == "memory_edit":
            return ("Forgetting that" if a.get("op") == "remove" else "Remembering that"), "write"
        if name == "gmail_search":
            q = str(a.get("query") or "").strip()
            return (f"Searching your email for {_q(q)}" if q else "Reading your inbox"), "read"
        if name in ("gmail_draft", "send_email_draft"):
            to, subj = who(a.get("to")), _q(a.get("subject"), 36)
            text = "Drafting " + (f"{subj} " if subj else "an email ") + (f"to {to}" if to else "")
            return text.strip(), "write"
        if name == "gmail_reply_draft":
            return "Drafting the reply", "write"
        if name in ("gmail_archive", "gmail_mark_read", "gmail_restore", "gmail_trash"):
            verb = {"gmail_archive": "Archiving", "gmail_mark_read": "Marking as read", "gmail_restore": "Restoring",
                    "gmail_trash": "Trashing"}[name]
            return f"{verb} {_n(a.get('message_ids'), a.get('query'), 'email', 'emails')}", "write"
        if name == "gmail_unsubscribe":
            return "Unsubscribing you", "write"
        if name == "gmail_filter":
            return (f"Making a filter for mail from {who(a.get('from'))}" if a.get("from") else "Making a Gmail filter"), "write"
        if name == "gmail_filter_delete":
            return "Removing a Gmail filter", "write"
        if name == "calendar_add":
            return f"Adding {_q(a.get('title'))} to your calendar".replace("Adding  to", "Adding it to"), "write"
        if name == "calendar_invite":
            return f"Drafting the invite for {_q(a.get('title'))}", "write"
        if name == "calendar_delete":
            return "Removing the event from your calendar", "write"
        if name == "calendar_move":
            return "Moving the event", "write"
        if name == "drive_search":
            return f"Searching your Drive for {_q(a.get('query'))}", "read"
        if name in ("drive_make_folder", "drive_rename", "drive_copy"):
            verb = {"drive_make_folder": "Making the folder", "drive_rename": "Renaming it to",
                    "drive_copy": "Copying it as"}[name]
            return f"{verb} {_q(a.get('name'))}".strip(), "write"
        if name in ("drive_move", "drive_restore", "drive_trash", "drive_save_photo"):
            return {"drive_move": "Moving the file", "drive_restore": "Restoring the file",
                    "drive_trash": "Trashing the file", "drive_save_photo": "Saving your photo to Drive"}[name], "write"
        if name == "drive_share":
            return f"Sharing the file with {who(a.get('email'))}", "send"
        if name == "docs_create":
            return f"Writing the doc {_q(a.get('title'))}".strip(), "write"
        if name == "slides_create":
            return f"Making the slides {_q(a.get('title'))}".strip(), "write"
        if name == "generate_image":
            return "Making the image", "image"
        if name == "routine_create":
            return f"Setting up {_q(a.get('name'))}".strip() if a.get("name") else "Setting up the routine", "write"
        if name in ("routine_delete", "routine_run_now"):
            return ("Removing the routine" if name == "routine_delete" else "Running the routine"), "write"
        if name in ("workflow_save", "workflow_run"):
            return (f"Saving {_q(a.get('name'))}" if name == "workflow_save" else f"Running {_q(a.get('name'))}"), "write"
        if name == "browse_open":
            h = host(a.get("url"))
            return (f"Opening {h}" if h else "Opening the page"), "browse"
        if name == "browse_act":
            return _browse_act(a, ctx), "browse"
        if name == "browse_submit":
            label = _ref_label(a.get("ref"), ctx)
            return (f"Getting “{label}” ready for your OK" if label else "Getting that ready for your OK"), "browse"
        if name == "browse_sign_in":
            try:
                from . import browser
                h = host(browser.current_url(ctx))
            except Exception:  # noqa: BLE001
                h = ""
            return (f"Signing in to {h}" if h else "Signing in"), "browse"
        if name == "call_me":
            return "Calling you", "call"
        if name == "call_someone":
            n = safe_words(a.get("name"), 30) or who(a.get("to"))
            return (f"Getting the call to {n} ready" if n else "Getting the call ready"), "call"
        if name == "send_text":
            return (f"Texting {who(a.get('to'))}" if a.get("to") else "Writing the text"), "send"
        if name == "find_contact":
            return f"Looking up {_q(a.get('query'))} in your contacts", "read"
        if name == "save_contact":
            return f"Saving {safe_words(a.get('name'), 30)} to your contacts", "write"
        if name == "weather":
            p = safe_words(a.get("place"), 30)
            return (f"Checking the weather in {p}" if p else "Checking the weather"), "read"
        if name == "bank_transactions":
            s = str(a.get("search") or "").strip()
            return (f"Looking through your transactions for {_q(s)}" if s else "Looking through your transactions"), "read"
        if name in _FIXED:
            return _FIXED[name]
    except Exception:  # noqa: BLE001  status text must never break a turn
        pass
    from . import tools
    tool = tools.BY_NAME.get(name) or {}
    words = re.sub(r"[^a-z0-9 ]", "", name.replace("_", " ").lower()).strip()[:40] or "a tool"
    return f"Using {words}", ("write" if tool.get("risk") in ("write", "send") else "read")


THINKING = "Thinking it through"


class Activity:
    """Emits activity start/done events for one turn and keeps their texts (for meta.activity)."""

    def __init__(self, emit, texts):
        self.emit, self.texts = emit, texts
        self.n = 0
        self.lock = threading.Lock()

    def start(self, text, kind="read", id=None, keep=True):
        kind = kind if kind in KINDS else "read"
        with self.lock:
            self.n += 1
            aid = str(id or f"act{self.n}")
            if keep and len(self.texts) < MAX_TEXTS and (not self.texts or self.texts[-1] != text):
                self.texts.append(text)
        self.emit("activity", {"id": aid, "text": text, "state": "start", "kind": kind})
        return aid

    def done(self, aid, text, kind="read", ok=True):
        self.emit("activity", {"id": aid, "text": text, "state": "done", "kind": kind if kind in KINDS else "read",
                               "ok": bool(ok)})

    def call(self, c, ctx):
        text, kind = describe(c.get("name"), c.get("args"), ctx)
        return self.start(text, kind), text, kind

    def reporter(self):
        """ctx["activity"] for tools: report(text, kind="read") -> id. Words are cleaned here."""
        def report(text, kind="read"):
            text = safe_words(text, 60)
            return self.start(text, kind) if text else None
        return report
