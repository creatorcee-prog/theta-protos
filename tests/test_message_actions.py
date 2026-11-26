"""Message actions: token usage in reply meta, editing your last message, like/dislike feedback and the
lessons it adds to the system prompt, the liked-replies export, and [n] source numbering.
No network: models.stream / models.call are fakes. Run: python3 tests/test_message_actions.py"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="protos-actions-")
os.environ["PROTOS_DATA"] = TMP
os.environ["PROTOS_WEB"] = os.path.join(TMP, "web-empty")
os.environ["PROTOS_TICK"] = "0"
os.environ["PROTOS_QUIET"] = "1"
os.environ["PROTOS_COMPACT"] = "0"
for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "LOCAL_LLM_URL", "TAVILY_API_KEY",
          "PROTOS_LOCAL_FIRST", "PROTOS_KEY", "VANTAGE_URL", "VANTAGE_DIR"):
    os.environ.pop(k, None)
os.environ["DEEPSEEK_API_KEY"] = "sk-test"

from server import app as appmod, db, models, persona, router, tools  # noqa: E402

router.CLASSIFIER = None
FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {detail}")
        FAILED.append(name)


# ---- fakes: the plain path streams, the tool path calls

SYSTEMS = []      # the system prompt of every model call, in order
REPLY = {"text": "Plain reply number one. It has a few words."}


def fake_stream(provider, model, messages, max_tokens=1024, usage=None):
    SYSTEMS.append(messages[0]["content"])

    def gen():
        for w in REPLY["text"].split(" "):
            yield w + " "
        if usage is not None:
            usage.update(tokens_in=1234, tokens_out=210, cache_read=1000, cache_write=0)
    return gen()


CALL_PLAN = []    # list of results models.call returns, in order


def fake_call(provider, model, messages, tools_=None, max_tokens=1024, on_text=None, tool_choice="auto", timeout=None):
    SYSTEMS.append(messages[0]["content"])
    res = CALL_PLAN.pop(0) if CALL_PLAN else {"text": "Saved that.", "tool_calls": []}
    if res.get("text") and on_text:
        on_text(res["text"])
    return {"text": res.get("text", ""), "tool_calls": res.get("tool_calls", []), "reasoning": "",
            "usage": {"tokens_in": 500, "tokens_out": 40, "cache_read": 300, "cache_write": 0}}


models.stream = fake_stream
models.call = fake_call


# ---- calling the WSGI app directly

def call(method, path, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    path, _, qs = path.partition("?")
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http"}
    got = {}

    def start(status, headers):
        got["status"], got["headers"] = int(status.split()[0]), dict(headers)
    out = b"".join(appmod.app(env, start))
    ctype = got["headers"].get("Content-Type", "")
    if ctype.startswith("application/json"):
        return got["status"], json.loads(out)
    if ctype.startswith("text/event-stream"):
        events = []
        for frame in out.decode().split("\n\n"):
            ev, data = None, []
            for line in frame.split("\n"):
                if line.startswith("event: "):
                    ev = line[7:]
                elif line.startswith("data: "):
                    data.append(line[6:])
            if ev:
                events.append((ev, json.loads("\n".join(data))))
        return got["status"], events
    return got["status"], out.decode()


def chat(text):
    st, j = call("POST", "/api/chat?stream=0", {"bot": "theta", "text": text})
    assert st == 200, (st, j)
    return j


def main():
    db.init(os.path.join(TMP, "protos.db"))

    # ---- 1. usage on the plain path
    j = chat("hey there")
    u = j["reply"]["meta"].get("usage") or {}
    check("plain path: meta.usage {in, out, cached, cost_usd, model}",
          u.get("in") == 1234 and u.get("out") == 210 and u.get("cached") == 1000
          and u.get("model") == j["reply"]["meta"]["model"] and isinstance(u.get("cost_usd"), float)
          and u["cost_usd"] > 0, u)
    check("plain path: the reply says which user message it answers",
          j["reply"]["meta"].get("reply_to") == j["user"]["id"])
    hist = call("GET", "/api/messages?bot=theta")[1]["messages"]
    check("usage comes back with history", any((m["meta"].get("usage") or {}).get("in") == 1234 for m in hist))

    # ---- 2. usage on the tool path (agent), research usage added in
    CALL_PLAN[:] = [{"text": "", "tool_calls": [{"id": "c1", "name": "memory_edit",
                                                 "args": {"op": "add", "text": "Vegetarian"}}]},
                    {"text": "Got it, I'll remember you're vegetarian."}]
    j = chat("remember that I'm vegetarian")
    m = j["reply"]["meta"]
    check("tool path: meta.usage summed over the loop's calls", (m.get("usage") or {}).get("in") == 1000
          and m["usage"]["out"] == 80 and m["usage"]["cached"] == 600 and m["usage"]["model"] == m["model"], m)
    check("tool path: write tool listed", m.get("tools") == ["memory_edit"], m)
    um = appmod._usage_meta({"tokens_in": 100, "tokens_out": 10}, "deepseek", "deepseek-chat",
                            [{"usage": {"tokens_in": 50, "tokens_out": 5, "cache_read": 20}, "cost_usd": 0.5}])
    check("research usage counts toward the reply's usage", um["in"] == 150 and um["out"] == 15
          and um["cached"] == 20 and um["cost_usd"] >= 0.5, um)
    check("no usage reported: no usage meta", appmod._usage_meta({}, "deepseek", "x") is None)

    # ---- 3. edit: only the latest user message
    tool_user, tool_reply = j["user"], j["reply"]
    acks_before = [x for x in db.messages("theta") if x["meta"].get("reply_to") == tool_user["id"]]
    brief = db.add_message("theta", "assistant", "Evening brief: all quiet.", {"proactive": True, "source": "brief"})
    turn_pro = db.add_message("theta", "assistant", "Made by that turn.", {"proactive": True,
                                                                           "reply_to": tool_user["id"]})
    older_user = [x for x in db.messages("theta") if x["role"] == "user"][0]
    st, err = call("POST", "/api/messages/edit", {"id": older_user["id"], "text": "something else"})
    check("edit an older message: 409", st == 409, (st, err))
    st, err = call("POST", "/api/messages/edit", {"id": tool_reply["id"], "text": "x"})
    check("edit a reply (not a user message): 404", st == 404, st)
    st, err = call("POST", "/api/messages/edit", {"id": tool_user["id"], "text": "  "})
    check("edit with empty text: 400", st == 400, st)

    REPLY["text"] = "Second answer, after the edit."
    n_sys = len(SYSTEMS)
    st, events = call("POST", "/api/messages/edit", {"id": tool_user["id"], "text": "hey, what's new"})
    names = [e for e, _ in events]
    data = dict(events)
    check("edit streams like /api/chat: deleted, user, route, delta, done",
          st == 200 and names[0] == "deleted" and names[1] == "user" and "route" in names and "delta" in names
          and names[-1] == "done", names)
    gone = set(data["deleted"]["ids"])
    check("edit removes the ack, the reply and that turn's proactive message",
          {tool_reply["id"], turn_pro["id"]} | {a["id"] for a in acks_before} <= gone, (gone, tool_reply["id"]))
    check("edit keeps other proactive texts", brief["id"] not in gone and db.get_message(brief["id"]) is not None)
    check("edit replaces the user message's text in place", data["user"]["id"] == tool_user["id"]
          and db.get_message(tool_user["id"])["text"] == "hey, what's new"
          and db.get_message(tool_user["id"])["meta"].get("edited"))
    check("the old reply is gone from the db", db.get_message(tool_reply["id"]) is None)
    new = data["done"]
    check("edit regenerates the reply", new["text"].startswith("Second answer") and len(SYSTEMS) > n_sys
          and new["meta"].get("reply_to") == tool_user["id"] and new["meta"].get("edited") is True, new)
    check("edit: a note says the earlier write tool wasn't undone",
          "already updated what I remember about you" in (new["meta"].get("note") or "")
          and "wasn't undone" in new["meta"]["note"], new["meta"])
    check("edit: the memory write stays done", "Vegetarian" in db.get_memory())
    check("edit: usage on the regenerated reply", (new["meta"].get("usage") or {}).get("in") == 1234)
    st, _ = call("POST", "/api/messages/edit", {"id": tool_user["id"], "text": "and again"})
    check("the same message can be edited again while it's still the latest", st == 200, st)
    chat("one more")
    st, _ = call("POST", "/api/messages/edit", {"id": tool_user["id"], "text": "too late"})
    check("after a newer message, editing it is 409", st == 409, st)

    # ---- 4. feedback
    last = db.messages("theta")[-1]
    st, j = call("POST", "/api/feedback", {"message_id": last["id"], "vote": -1, "reason": "Too long"})
    row = db.feedback()[0]
    check("feedback stored with prompt, reply, model, tier", st == 200 and row["message_id"] == last["id"]
          and row["vote"] == -1 and row["reason"] == "Too long" and row["prompt"] == "one more"
          and row["reply"] == last["text"] and row["model"] == last["meta"]["model"] and row["tier"], row)
    check("the vote shows on the message", db.get_message(last["id"])["meta"].get("vote") == -1)
    sp = persona.system_prompt()
    check("lesson in the system prompt, after memory", "Disliked: too long → keep replies shorter" in sp
          and sp.index("What you remember") < sp.index(persona.FEEDBACK_HEAD), sp[-400:])
    check("system prompt is byte-stable while feedback is unchanged", persona.system_prompt() == sp)
    SYSTEMS.clear()
    chat("next turn")
    check("the next turn's system prompt carries the lesson", "keep replies shorter" in SYSTEMS[-1])
    st, _ = call("POST", "/api/feedback", {"message_id": last["id"], "vote": 2})
    check("bad vote: 400", st == 400, st)
    st, _ = call("POST", "/api/feedback", {"message_id": 999999, "vote": 1})
    check("unknown message: 404", st == 404, st)

    # dedupe, newest first, at most 6, free text, likes need a pattern
    others = []
    for i in range(10):
        u_ = db.add_message("theta", "user", f"q{i}")
        others.append(db.add_message("theta", "assistant", f"a{i}", {"model": "deepseek-chat", "tier": "quick"}))
    for i, r in enumerate(["too long", "Tone", "Wrong", "Not what I asked", "used too many emoji", "Too long: rambly"]):
        call("POST", "/api/feedback", {"message_id": others[i]["id"], "vote": -1, "reason": r})
        db._conn().execute("UPDATE feedback SET t = ? WHERE message_id = ?", (1000 + i, others[i]["id"]))
    db._bump_feedback()
    les = persona.lessons()
    keys = [x["id"] for x in les]
    check("lessons de-duplicated (one 'too long')", keys.count("d:too-long") == 1, keys)
    check("lessons newest first", keys[0] == "d:too-long" and keys[1].startswith("d:x:"), keys)
    check("free-text reason becomes a lesson", any('"used too many emoji"' in x["text"] for x in les), les)
    check("at most 6 lessons in the block", len(persona.feedback_block().splitlines()) <= 7)
    for i in (6, 7):
        call("POST", "/api/feedback", {"message_id": others[i]["id"], "vote": 1})
    check("two likes are not yet a pattern", not any(x["id"].startswith("l:") for x in persona.lessons()))
    call("POST", "/api/feedback", {"message_id": others[8]["id"], "vote": 1})
    like = [x for x in persona.lessons() if x["id"].startswith("l:")]
    check("three likes of one tier and style: a 'Liked' lesson",
          like and like[0]["text"].startswith("Liked: quick replies that are short"), persona.lessons())

    # summary + delete a lesson
    st, summ = call("GET", "/api/feedback/summary")
    check("summary lists the lessons", st == 200 and summ["lessons"] and summ["likes"] == 3, summ)
    before = persona.system_prompt()
    st, j = call("DELETE", "/api/feedback/summary?id=d:tone")
    check("delete a lesson", st == 200 and "d:tone" not in [x["id"] for x in j["lessons"]], j)
    after = persona.system_prompt()
    check("the deleted lesson leaves the system prompt", "the tone" in before and "the tone" not in after)
    st, _ = call("DELETE", "/api/feedback/summary?id=nope")
    check("delete an unknown lesson: 404", st == 404, st)
    call("POST", "/api/feedback", {"message_id": others[6]["id"], "vote": 0})
    check("vote 0 removes the vote", not any(r["message_id"] == others[6]["id"] for r in db.feedback())
          and "vote" not in db.get_message(others[6]["id"])["meta"])

    # export
    st, body = call("GET", "/api/feedback/export")
    lines = [json.loads(x) for x in body.splitlines() if x.strip()]
    check("export: liked replies as jsonl {prompt, reply, tier, model}", st == 200 and len(lines) == 2
          and set(lines[0]) == {"prompt", "reply", "tier", "model"} and lines[-1]["reply"] == "a8"
          and lines[-1]["prompt"] == "q8", lines)
    check("nothing is written into the repo", not os.path.exists(os.path.join(ROOT, "evals", "feedback.jsonl")))

    # ---- 5. sources: web_search numbers by the turn's sources
    real = router.search_context
    os.environ["TAVILY_API_KEY"] = "t"
    try:
        ctx = {"sources": [{"title": "Old", "url": "https://old.example/a"}]}
        router.search_context = lambda q, max_results=5: (
            "Live web results\n\n[1] A (https://a.example)\nx\n\n[2] Old again (https://old.example/a)\ny",
            [{"title": "A", "url": "https://a.example"}, {"title": "Old again", "url": "https://old.example/a"}])
        out = tools._web_search({"query": "q"}, ctx)
        check("web_search numbers results by their place in meta.sources",
              "[2] A (https://a.example)" in out and "[1] Old again" in out and len(ctx["sources"]) == 2, out)
    finally:
        router.search_context = real
        os.environ.pop("TAVILY_API_KEY", None)
    from server import subagents
    nums = subagents._numbers([{"url": "https://b"}, {"url": "https://c"}], {"sources": [{"url": "https://c"}]})
    check("research renumbers helper citations to the turn's numbering",
          subagents._renumber("x [1] y [2] z [9]", [{"url": "https://b"}, {"url": "https://c"}], nums)
          == "x [2] y [1] z [9]", nums)
    check("persona tells the model to cite [n] right after the claim", "[n] right after the claim" in persona.STYLE)

    # ---- 6. the citation pill logic in app.js (node, if there is one)
    node = shutil.which("node")
    if node:
        js = r"""
const fs = require("fs"), src = fs.readFileSync(process.argv[1], "utf8");
const m = /\/\/ ---- cite: start[^\n]*\n([\s\S]*?)\/\/ ---- cite: end/.exec(src);
if (!m) { console.log(JSON.stringify({err: "no cite block"})); process.exit(0); }
const f = new Function(m[1] + "; return {citeParts, domain};")();
const S = [{title: "Reuters", url: "https://www.reuters.com/x"}, {title: "Bad", url: "javascript:alert(1)"}];
console.log(JSON.stringify({
  a: f.citeParts("[1]", S), b: f.citeParts("[2]", S), c: f.citeParts("[3]", S), d: f.citeParts("[1, 3]", S),
  e: f.domain("https://www.bbc.co.uk/news"), g: f.domain("http://x.test"),
}));
"""
        r = subprocess.run([node, "-e", js, os.path.join(ROOT, "web", "app.js")], capture_output=True, text=True,
                           timeout=20)
        try:
            got = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            got = {"err": r.stdout + r.stderr}
        check("cite: [1] with a source is a pill showing the domain",
              got.get("a") == [{"n": 1, "url": "https://www.reuters.com/x", "label": "reuters.com", "title": "Reuters"}],
              got)
        check("cite: a non-https source stays text", got.get("b") is None, got)
        check("cite: unknown [n] stays text", got.get("c") is None, got)
        check("cite: [1, 3] with one unknown stays text", got.get("d") is None, got)
        check("cite: domain() drops www and refuses http", got.get("e") == "bbc.co.uk" and got.get("g") is None, got)
    else:
        print("SKIP cite pill logic (no node)")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    if FAILED:
        print(f"\n{len(FAILED)} failed: {FAILED}")
        sys.exit(1)
    print("\nall message-actions tests passed")
