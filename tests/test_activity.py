"""The status line (server/activity.py): each tool call becomes plain words ("Drafting “Rent” to Sam", "Opening
megaplex.com", "Clicking “Showtimes”"), names come from saved contacts, nothing secret, typed or long-numbered
shows, and agent.run streams them as `activity` events and keeps them for the reply. The model is faked."""
import os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp(),
                  DEEPSEEK_API_KEY="sk-test")
from server import activity, agent, browser, contacts, db, ext, models, router, tools


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


db.init()
ext.reset(); tools._ext_reset(); tools._ext()
D = activity.describe
contacts.upsert({"name": "Sam Lee", "phone": "+13035550142", "email": "sam@example.com"})

check("an email draft names the subject and the person (from contacts)",
      D("gmail_draft", {"to": "sam@example.com", "subject": "Rent for December", "body": "secret body"})[0]
      == "Drafting “Rent for December” to Sam Lee")
check("never the body", "secret body" not in D("send_email_draft", {"to": "x@y.com", "body": "secret body"})[0])
check("someone not saved: the name part of the address", D("gmail_draft", {"to": "pat.k@work.com"})[0] == "Drafting an email to pat.k")
check("a text to a saved number says who; an unsaved one only its last digits",
      D("send_text", {"to": "+1 303 555 0142", "message": "hi"})[0] == "Texting Sam Lee"
      and D("send_text", {"to": "+17205559876"})[0] == "Texting the number ending 9876")
check("a search shows what's searched", D("web_search", {"query": "Megaplex showtimes Friday"})[0]
      == "Searching the web for “Megaplex showtimes Friday”")
check("a key in a search is hidden", "sk-abcdef123456" not in D("web_search", {"query": "my key sk-abcdef123456"})[0])
check("opening a site shows its host, not its path", D("browse_open", {"url": "https://www.megaplextheatres.com/tix?token=abc"})[0]
      == "Opening megaplextheatres.com")
check("bulk mail actions count what they touch", D("gmail_archive", {"message_ids": ["a", "b", "c"]})[0] == "Archiving 3 emails"
      and D("gmail_trash", {"query": "from:promo"})[0] == "Trashing emails matching “from:promo”")
check("calendar and Drive in words", D("calendar_add", {"title": "Dentist"})[0] == "Adding “Dentist” to your calendar"
      and D("drive_make_folder", {"name": "Taxes 2026"})[0] == "Making the folder “Taxes 2026”")
check("chips in words", D("chip_open", {"name": "Plan my day"})[0] == "Opening your “Plan my day” chip")
check("an unknown tool still says something true", D("mystery_tool", {})[0] == "Using mystery tool")

# browser steps use the labels from the page Theta has open
class S:
    url, title = "https://megaplextheatres.com/", "Megaplex"
    els = {"e4": {"label": "Showtimes"}, "e7": {"label": "Email"}}
browser._engine.sessions["theta"] = S()
ctx = {"bot": "theta"}
check("a click names what's clicked", D("browse_act", {"actions": [{"do": "click", "ref": "e4"}]}, ctx)[0] == "Clicking “Showtimes”")
check("typing names the field, never what's typed",
      D("browse_act", {"actions": [{"do": "type", "ref": "e7", "text": "sam@example.com"}, {"do": "click", "ref": "e4"}]}, ctx)[0]
      == "Filling in “Email” (+1 more)")
check("a submit waits for the OK, in words", D("browse_submit", {"ref": "e4"}, ctx)[0] == "Getting “Showtimes” ready for your OK")
check("signing in names the site", D("browse_sign_in", {}, ctx)[0] == "Signing in to megaplextheatres.com")
del browser._engine.sessions["theta"]

# through a real agent turn
SCRIPT = [{"text": "Checking.", "tool_calls": [{"id": "c1", "name": "web_search", "args": {"query": "Megaplex hours"}},
                                                {"id": "c2", "name": "remind_me", "args": {"text": "movie", "in_minutes": 30}}]},
          {"text": "Done: it opens at 10."}]


def fake_call(provider, model, messages, tools_=None, max_tokens=1024, on_text=None, tool_choice="auto", timeout=None):
    step = SCRIPT.pop(0) if SCRIPT else {"text": "ok"}
    if on_text and step.get("text"):
        on_text(step["text"])
    return {"text": step.get("text", ""), "tool_calls": step.get("tool_calls") or [], "reasoning": "",
            "usage": {"tokens_in": 1, "tokens_out": 1, "cache_read": 0, "cache_write": 0}}


models.call = fake_call
tools.BY_NAME["web_search"]["run"] = lambda a, c: (c["activity"]("Reading 3 results"), "1. Megaplex opens at 10")[1]
events, info = [], {}
route = router.Route(tier="quick", model="deepseek-chat", provider="deepseek", why="t", candidates=(("deepseek", "deepseek-chat"),))
agent.run(route, [{"role": "system", "content": "x"}, {"role": "user", "content": "hours?"}],
          lambda ev, d: events.append((ev, d)), info=info, ctx={"bot": "theta"})
acts = [d for ev, d in events if ev == "activity"]
texts = [a["text"] for a in acts]
check("each tool call streams an activity line as it starts", "Searching the web for “Megaplex hours”" in texts
      and "Setting the reminder" in texts and all(a["state"] == "start" for a in acts))
check("a tool can add its own step", "Reading 3 results" in texts)
check("the turn keeps them, in order, for the line under the reply", info["activity"][0].startswith("Searching the web")
      and "_act" not in info)
print("all activity checks passed")
