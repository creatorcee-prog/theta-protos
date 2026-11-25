"""Memory block, running summary, history search and the new db tables
(approvals, jobs, plans, turn usage columns). No network. Run: python3 tests/test_memory.py"""

import os
import shutil
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="protos-mem-")
os.environ["PROTOS_DATA"] = TMP

from server import db, memory, persona  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {detail}")
        FAILED.append(name)


def main():
    # ---- migration: a v0 database gets the new turns columns
    old = os.path.join(TMP, "old.db")
    c = sqlite3.connect(old)
    c.executescript("CREATE TABLE turns (id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL NOT NULL, bot TEXT, "
                    "user_id INTEGER, reply_id INTEGER, tier TEXT, provider TEXT, model TEXT, why TEXT, "
                    "ttft_ms INTEGER, total_ms INTEGER, chars_in INTEGER, chars_out INTEGER, ok INTEGER NOT NULL "
                    "DEFAULT 1, error TEXT, tried TEXT NOT NULL DEFAULT '[]');"
                    "INSERT INTO turns (t, bot) VALUES (1, 'theta');")
    c.commit()
    c.close()
    db.init(old)
    db.init(old)  # idempotent
    cols = {r["name"] for r in db._conn().execute("PRAGMA table_info(turns)").fetchall()}
    check("old db migrated with usage columns", {"tokens_in", "tokens_out", "cache_read", "cache_write",
                                                 "cost_usd", "steps", "tools"} <= cols, cols)
    check("old turn rows still read", db.turns(5)[-1]["tools"] == [] and db.turns(5)[-1]["bot"] == "theta")

    db.init(os.path.join(TMP, "protos.db"))

    # ---- turns usage
    tid = db.add_turn(bot="theta", tier="quick", provider="deepseek", model="deepseek-chat", ok=True,
                      tokens_in=1200, tokens_out=80, cache_read=1024, cache_write=0, cost_usd=0.00042, steps=2,
                      tools=["web_search", "memory_edit"], tried=["deepseek/deepseek-chat"], bogus="ignored")
    t = db.turns(1)[0]
    check("add_turn stores usage, cost, steps, tools", t["id"] == tid and t["tokens_in"] == 1200
          and t["cache_read"] == 1024 and abs(t["cost_usd"] - 0.00042) < 1e-12 and t["steps"] == 2
          and t["tools"] == ["web_search", "memory_edit"] and t["tried"] == ["deepseek/deepseek-chat"], t)
    db.add_turn(bot="theta", ok=False, error="x")
    t = db.turns(1)[0]
    check("add_turn without usage keys", t["tokens_in"] is None and t["tools"] == [] and t["ok"] is False)

    # ---- approvals
    a = db.add_approval({"tool": "send_email_draft", "args": {"to": "sam@example.com"}, "summary": "Email Sam"})
    got = db.get_approval(a)
    check("approval starts pending", got["state"] == "pending" and got["action"]["args"]["to"] == "sam@example.com")
    check("approve once (expect pending)", db.set_approval(a, "approved", expect="pending") is True
          and db.set_approval(a, "approved", expect="pending") is False)
    db.set_approval(a, "done")
    check("approval done", db.get_approval(a)["state"] == "done")
    check("unknown approval is None", db.get_approval(999) is None and db.get_approval("x") is None)
    try:
        db.set_approval(a, "bogus")
        check("bad approval state refused", False)
    except ValueError:
        check("bad approval state refused", True)
    check("approvals list by state", [x["id"] for x in db.approvals("done")] == [a] and db.approvals("pending") == [])

    # ---- jobs
    j1 = db.add_job(100, "remind", {"text": "call mum"})
    j2 = db.add_job(200, "remind", {"text": "later"})
    check("due_jobs only due + pending", [j["id"] for j in db.due_jobs(150)] == [j1]
          and db.due_jobs(150)[0]["payload"] == {"text": "call mum"})
    claimed = db.due_jobs(250, claim=True)
    check("claim marks running so a second tick skips them", [j["id"] for j in claimed] == [j1, j2]
          and all(j["state"] == "running" for j in claimed) and db.due_jobs(250) == [])
    db.finish_job(j1, "done", {"message_id": 7})
    db.finish_job(j2, "pending")
    check("finish_job stores result", db.get_job(j1)["state"] == "done" and db.get_job(j1)["result"] == {"message_id": 7}
          and db.get_job(j1)["done_t"])
    check("job back to pending is due again", [j["id"] for j in db.due_jobs(250)] == [j2])
    check("jobs list", [j["id"] for j in db.jobs()] == [j1, j2] and [j["id"] for j in db.jobs("done")] == [j1])

    # ---- plans
    check("no plan yet", db.get_plan("theta") is None)
    db.set_plan("theta", {"goal": "book flights", "steps": [{"text": "find dates", "done": True}]})
    check("plan round trip", db.get_plan("theta")["steps"][0]["done"] is True)
    db.set_plan("theta", None)
    check("plan cleared", db.get_plan("theta") is None)

    # ---- memory block
    check("empty memory block", memory.block() == "")
    db.set_setting("memory", ["Likes the Broncos", {"text": "Gym at 6am"}])
    check("v0 notes show until the first edit", memory.block() == "- Likes the Broncos\n- Gym at 6am")
    r = memory.edit("add", "Brother is Sam")
    check("add a fact (keeps v0 notes)", r["ok"] and r["block"] == "- Likes the Broncos\n- Gym at 6am\n- Brother is Sam"
          and db.get_memory() == r["block"], r)
    check("add duplicate is a no-op", memory.edit("add", "- brother is sam")["block"] == r["block"])
    r = memory.edit("replace", "Gym at 7am", old="Gym at 6am")
    check("replace a line", r["ok"] and "- Gym at 7am" in r["block"] and "6am" not in r["block"], r)
    r = memory.edit("replace", "Nuggets", old="Broncos")
    check("replace words inside a line", r["ok"] and "- Likes the Nuggets" in r["block"], r)
    r = memory.edit("remove", None, old="likes the nuggets")
    check("remove a line (case-insensitive)", r["ok"] and "Nuggets" not in r["block"], r)
    r = memory.edit("remove", "no such thing")
    check("remove missing says how to fix", not r["ok"] and "copy the exact words" in r["error"], r)
    r = memory.edit("replace", "x")
    check("replace without old refused", not r["ok"] and "old=" in r["error"])
    check("unknown op refused", not memory.edit("forget", "x")["ok"])
    check("empty add refused", not memory.edit("add", "  ")["ok"])
    check("one fact is one line", memory.edit("add", "line one\nline two")["block"].endswith("- line one line two"))
    before = memory.block()
    n = 0
    while memory.edit("add", f"filler fact number {n} " + "x" * 200)["ok"]:
        n += 1
        if n > 50:
            break
    r = memory.edit("add", "one more " + "y" * 250)
    check("refuses over the cap", not r["ok"] and "full" in r["error"] and len(memory.block()) <= memory.CAP, r)
    check("cap respected", len(db.get_memory()) <= memory.CAP and memory.block().startswith(before[:20]))
    check("too-long fact refused", not memory.edit("add", "z" * 400)["ok"])
    db.set_memory("- Gym at 7am")
    sp = persona.system_prompt()
    check("memory block in the system prompt", "Gym at 7am" in sp and "What you remember" in sp)

    # ---- history search
    db.add_message("theta", "user", "my passport expires in March 2027")
    db.add_message("theta", "assistant", "Noted: passport renewal before March.")
    db.add_message("theta", "user", "the cabin trip is 12-14 June with the crew")
    db.add_message("theta", "assistant", "On it.", {"ack": True})
    hits = memory.search("passport")
    check("search finds newest first", [h["role"] for h in hits] == ["assistant", "user"] and "March" in hits[1]["text"],
          hits)
    check("search every word when phrase missing", len(memory.search("cabin crew")) == 1)
    check("search escapes LIKE wildcards", memory.search("%") == [] and memory.search("_") == [])
    check("search skips acks", memory.search("On it.") == [])
    check("search limit + before", len(memory.search("passport", limit=1)) == 1
          and memory.search("passport", before=hits[1]["id"]) == [])
    check("empty search", memory.search("") == [])

    # ---- summary + compaction
    db.init(os.path.join(TMP, "sum.db"))
    for i in range(25):
        db.add_message("theta", "user", f"user message {i}")
        db.add_message("theta", "assistant", f"reply {i}")
    asked = []

    def summarize(prompt):
        asked.append(prompt)
        return "User said messages 0 to 14."
    check("no summary yet", memory.summary("theta") == "")
    check("compact without a summarizer does nothing", memory.compact("theta") is False)
    check("compact folds old turns", memory.compact("theta", summarize=summarize) is True)
    text, upto = db.get_summary("theta")
    recent = db.messages("theta", limit=memory.KEEP)
    check("summary stored up to the last aged-out message", text == "User said messages 0 to 14."
          and upto == recent[0]["id"] - 1, (upto, recent[0]["id"]))
    check("summarizer saw old turns only", "User: user message 0" in asked[0] and "user message 15" not in asked[0]
          and "Theta: reply 14" in asked[0] and "(none yet)" in asked[0], asked[0][-300:])
    check("compact waits for MIN_NEW new old turns", memory.compact("theta", summarize=summarize) is False)
    for i in range(4):
        db.add_message("theta", "user", f"more {i}")
        db.add_message("theta", "assistant", f"more reply {i}")
    check("still fewer than 10 new", memory.compact("theta", summarize=summarize) is False)
    db.add_message("theta", "user", "more 4")
    db.add_message("theta", "assistant", "more reply 4")
    check("10 new old turns: folds again", memory.compact("theta", summarize=summarize) is True
          and "User said messages 0 to 14." in asked[-1] and "Theta: more reply 4" not in asked[-1])
    check("summarizer failure keeps the old summary",
          memory.compact("theta", summarize=lambda p: 1 / 0, min_new=0) is False
          and db.get_summary("theta")[0] == "User said messages 0 to 14.")
    check("empty summary is ignored", memory.compact("theta", summarize=lambda p: "  ", min_new=1) is False)
    check("summary() reads it", memory.summary("theta") == "User said messages 0 to 14.")
    built = persona.build(db.messages("theta", limit=persona.HISTORY), "hi")
    check("build: system, summary note, recent turns, user turn", built[0]["role"] == "system"
          and built[1]["role"] == "system" and "User said messages 0 to 14." in built[1]["content"]
          and "Summary of your earlier conversation" in built[1]["content"] and len(built) == 2 + 20 + 1
          and persona.said(built[-1]["content"]) == "hi")
    check("build summary='' leaves it out", len(persona.build([], "hi", summary="")) == 2)
    sp1 = persona.build([], "a", now=0)[0]["content"]
    sp2 = persona.build([], "b", now=10 ** 9, extra="search stuff", context="vantage stuff")[0]["content"]
    check("system prompt identical across turns (cache prefix)", sp1 == sp2)
    last = persona.build([], "b", now=0, extra="search stuff", context="vantage stuff")[-1]["content"]
    check("vantage then search in the turn block", last.index("vantage stuff") < last.index("search stuff"))
    check("compact on a short chat does nothing", memory.compact("other", summarize=summarize) is False)

    shutil.rmtree(TMP, ignore_errors=True)
    if FAILED:
        print(f"\n{len(FAILED)} failed: {', '.join(FAILED)}")
        sys.exit(1)
    print("\nall memory checks passed")


if __name__ == "__main__":
    main()
