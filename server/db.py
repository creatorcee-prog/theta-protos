"""SQLite storage for theta-protos ($PROTOS_DATA/protos.db, default ./data).

One connection per thread (WAL mode), so the threaded dev server, the
proactive ticker and push can all call these functions at once. This module's
public functions are the interface other modules use (see docs/SPEC.md and
docs/HARNESS-PLAN.md).

    messages / settings / push_subs / seen     (v0, docs/SPEC.md)
    add_turn(**kw) / turns(limit)              turn log incl. tokens, cache, cost, steps, tools
    get_memory() / set_memory(text)            the memory block (memory.py owns the rules)
    get_summary(bot) -> (text, upto_id) / set_summary(bot, text, upto_id)
    add_approval(action) -> id / get_approval(id) / set_approval(id, state, expect=None) / approvals()
    add_job(due_t, kind, payload) -> id / due_jobs(now, claim=False) / finish_job(id, state, result) / jobs()
    get_plan(bot) / set_plan(bot, plan|None)
    search_messages(query, bot=None, limit=5)
    update_message(id, text=None, meta=None) / delete_messages(ids) / last_user_message(bot, before=None)
    set_feedback(message_id, vote, reason, prompt, reply, model, tier) / feedback(limit, include_dismissed)
    dismiss_feedback(ids) / feedback_version()
"""

import json
import os
import re
import sqlite3
import threading
import time

_lock = threading.Lock()
_local = threading.local()
_path = None
_gen = 0  # bumped by init() so per-thread connections reopen on a new path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    bot   TEXT NOT NULL,
    role  TEXT NOT NULL,
    text  TEXT NOT NULL,
    t     REAL NOT NULL,
    meta  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS messages_bot_id ON messages (bot, id);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS push_subs (
    endpoint TEXT PRIMARY KEY,
    sub      TEXT NOT NULL,
    t        REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    t         REAL NOT NULL,
    bot       TEXT,
    user_id   INTEGER,
    reply_id  INTEGER,
    tier      TEXT,
    provider  TEXT,
    model     TEXT,
    why       TEXT,
    ttft_ms   INTEGER,
    total_ms  INTEGER,
    chars_in  INTEGER,
    chars_out INTEGER,
    ok        INTEGER NOT NULL DEFAULT 1,
    error     TEXT,
    tried     TEXT NOT NULL DEFAULT '[]',
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    cache_read  INTEGER,
    cache_write INTEGER,
    cost_usd    REAL,
    steps       INTEGER,
    tools       TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS seen (
    key   TEXT PRIMARY KEY,
    until REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS memory (
    id    INTEGER PRIMARY KEY CHECK (id = 1),
    text  TEXT NOT NULL,
    t     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS summary (
    bot     TEXT PRIMARY KEY,
    text    TEXT NOT NULL,
    upto_id INTEGER NOT NULL DEFAULT 0,
    t       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    t       REAL NOT NULL,
    action  TEXT NOT NULL,
    state   TEXT NOT NULL DEFAULT 'pending',
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    t       REAL NOT NULL,
    due_t   REAL NOT NULL,
    kind    TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    state   TEXT NOT NULL DEFAULT 'pending',
    result  TEXT,
    done_t  REAL
);
CREATE INDEX IF NOT EXISTS jobs_state_due ON jobs (state, due_t);
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    t          REAL NOT NULL,
    message_id INTEGER NOT NULL UNIQUE,
    vote       INTEGER NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    prompt     TEXT NOT NULL DEFAULT '',
    reply      TEXT NOT NULL DEFAULT '',
    model      TEXT,
    tier       TEXT,
    dismissed  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plans (
    bot   TEXT PRIMARY KEY,
    plan  TEXT NOT NULL,
    t     REAL NOT NULL
);
"""

# columns added after v0, ALTERed onto older databases by init()
_ADDED = [("turns", "tokens_in", "INTEGER"), ("turns", "tokens_out", "INTEGER"),
          ("turns", "cache_read", "INTEGER"), ("turns", "cache_write", "INTEGER"),
          ("turns", "cost_usd", "REAL"), ("turns", "steps", "INTEGER"),
          ("turns", "tools", "TEXT NOT NULL DEFAULT '[]'")]


def data_dir():
    """The folder Theta keeps its files in (the database's folder). Features put their files in a subfolder."""
    return os.path.dirname(_path or _default_path())


def _default_path():
    # Railway mounts the service's volume at RAILWAY_VOLUME_MOUNT_PATH; keeping the database there is what makes
    # it survive redeploys
    data = (os.environ.get("PROTOS_DATA") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
            or os.path.join(os.getcwd(), "data"))
    return os.path.join(data, "protos.db")


def init(path=None):
    """Create the database and tables (idempotent). path=None uses
    $PROTOS_DATA/protos.db. Calling it again with another path switches
    every thread to that database."""
    global _path, _gen
    with _lock:
        _path = path or _default_path()
        if _path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(_path)), exist_ok=True)
        _gen += 1
    migrate(_conn())


def migrate(c):
    """Bring a database up to this version's tables and columns (idempotent; also used on a backup before it's
    restored)."""
    c.executescript(_SCHEMA)
    for table, col, typ in _ADDED:  # databases made before these columns existed
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def columns(c):
    """{table: set of column names} for every table this version uses."""
    names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return {t: {r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()} for t in names if not t.startswith("sqlite_")}


def fits(c):
    """'' if the database `c` has every table and column this version needs, else what's missing."""
    ref = sqlite3.connect(":memory:")
    migrate(ref)
    need, have = columns(ref), columns(c)
    ref.close()
    for t, cols in need.items():
        miss = cols - have.get(t, set())
        if miss:
            return f"{t} has no {', '.join(sorted(miss))}"
    return ""


def _conn():
    if _path is None:
        init()
    c = getattr(_local, "conn", None)
    if c is None or getattr(_local, "gen", None) != _gen:
        if c is not None:
            try:
                c.close()
            except sqlite3.Error:
                pass
        c = sqlite3.connect(_path, timeout=10, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=10000")
        _local.conn, _local.gen = c, _gen
    return c


def _msg(row):
    try:
        meta = json.loads(row["meta"] or "{}")
    except ValueError:
        meta = {}
    t = row["t"]
    return {"id": row["id"], "bot": row["bot"], "role": row["role"], "text": row["text"],
            "t": int(t) if float(t).is_integer() else t, "meta": meta}


# ---- messages

def add_message(bot, role, text, meta=None):
    """Store one message; returns the Message dict."""
    if role not in ("user", "assistant"):
        raise ValueError("role must be 'user' or 'assistant'")
    t = int(time.time())
    m = json.dumps(meta or {}, ensure_ascii=False)
    cur = _conn().execute("INSERT INTO messages (bot, role, text, t, meta) VALUES (?, ?, ?, ?, ?)",
                          (bot, role, text or "", t, m))
    return {"id": cur.lastrowid, "bot": bot, "role": role, "text": text or "", "t": t, "meta": dict(meta or {})}


def messages(bot, before=None, limit=50):
    """Up to `limit` messages of `bot` (older than id `before` if given), oldest first."""
    limit = max(1, min(int(limit or 50), 500))
    if before:
        rows = _conn().execute("SELECT * FROM messages WHERE bot = ? AND id < ? ORDER BY id DESC LIMIT ?",
                               (bot, int(before), limit)).fetchall()
    else:
        rows = _conn().execute("SELECT * FROM messages WHERE bot = ? ORDER BY id DESC LIMIT ?",
                               (bot, limit)).fetchall()
    return [_msg(r) for r in reversed(rows)]


def since(msg_id, bot=None, limit=500):
    """Messages with id > msg_id (all bots unless `bot`), oldest first."""
    msg_id = int(msg_id or 0)
    if bot:
        rows = _conn().execute("SELECT * FROM messages WHERE id > ? AND bot = ? ORDER BY id LIMIT ?",
                               (msg_id, bot, int(limit))).fetchall()
    else:
        rows = _conn().execute("SELECT * FROM messages WHERE id > ? ORDER BY id LIMIT ?",
                               (msg_id, int(limit))).fetchall()
    return [_msg(r) for r in rows]


def get_message(msg_id):
    """One Message by id, or None."""
    row = _conn().execute("SELECT * FROM messages WHERE id = ?", (int(msg_id),)).fetchone()
    return _msg(row) if row else None


def update_message(msg_id, text=None, meta=None):
    """Change a message's text and/or merge `meta` keys into its meta (a key set to None is removed).
    Returns the updated Message, or None if there is no such message."""
    c = _conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        row = c.execute("SELECT * FROM messages WHERE id = ?", (int(msg_id),)).fetchone()
        if row is None:
            c.execute("COMMIT")
            return None
        m = _msg(row)
        if meta:
            for k, v in meta.items():
                if v is None:
                    m["meta"].pop(k, None)
                else:
                    m["meta"][k] = v
        if text is not None:
            m["text"] = text
        c.execute("UPDATE messages SET text = ?, meta = ? WHERE id = ?",
                  (m["text"], json.dumps(m["meta"], ensure_ascii=False), m["id"]))
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    return m


def delete_messages(ids):
    """Delete messages by id; returns how many went."""
    ids = [int(i) for i in (ids or [])]
    if not ids:
        return 0
    return _conn().execute(f"DELETE FROM messages WHERE id IN ({', '.join('?' * len(ids))})", ids).rowcount


def last_user_message(bot, before=None):
    """The bot's most recent user message (older than id `before` if given), or None."""
    if before:
        row = _conn().execute("SELECT * FROM messages WHERE bot = ? AND role = 'user' AND id < ? "
                              "ORDER BY id DESC LIMIT 1", (bot, int(before))).fetchone()
    else:
        row = _conn().execute("SELECT * FROM messages WHERE bot = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
                              (bot,)).fetchone()
    return _msg(row) if row else None


# ---- settings (JSON values)

def get_setting(key, default=None):
    row = _conn().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except ValueError:
        return default


def set_setting(key, value):
    _conn().execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)))


# ---- web push subscriptions

def add_push_sub(sub):
    """Store (or replace) a PushSubscription JSON object, keyed by its endpoint."""
    endpoint = (sub or {}).get("endpoint")
    if not endpoint or not isinstance(endpoint, str):
        raise ValueError("subscription needs an endpoint")
    _conn().execute("INSERT INTO push_subs (endpoint, sub, t) VALUES (?, ?, ?) "
                    "ON CONFLICT(endpoint) DO UPDATE SET sub = excluded.sub, t = excluded.t",
                    (endpoint, json.dumps(sub), time.time()))


def push_subs():
    rows = _conn().execute("SELECT sub FROM push_subs ORDER BY t").fetchall()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["sub"]))
        except ValueError:
            pass
    return out


def drop_push_sub(endpoint):
    _conn().execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))


# ---- dedupe for proactive sends

def seen(key):
    """True if `key` was mark()ed and hasn't expired."""
    row = _conn().execute("SELECT until FROM seen WHERE key = ?", (key,)).fetchone()
    return bool(row) and row["until"] > time.time()


def mark(key, ttl_days=7):
    now = time.time()
    c = _conn()
    c.execute("INSERT INTO seen (key, until) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET until = excluded.until",
              (key, now + float(ttl_days) * 86400))
    c.execute("DELETE FROM seen WHERE until < ?", (now,))


# ---- turn log (routing + latency, for evals)


_TURN_COLS = ("bot", "user_id", "reply_id", "tier", "provider", "model", "why", "ttft_ms", "total_ms",
              "chars_in", "chars_out", "ok", "error",
              "tokens_in", "tokens_out", "cache_read", "cache_write", "cost_usd", "steps")


def _loads(v, default=None):
    if v is None:
        return default
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default


def _json_list(v):
    out = _loads(v, [])
    return out if isinstance(out, list) else []


def add_turn(**kw):
    """Log one chat turn. Keys: bot, user_id, reply_id, tier, provider, model, why,
    ttft_ms (latency to first token), total_ms, chars_in, chars_out, ok, error,
    tried (list of "provider/model" attempted), tokens_in, tokens_out,
    cache_read, cache_write (token counts), cost_usd, steps (agent loop steps)
    and tools (list of tool names called, in order). Unknown keys are ignored."""
    vals = [kw.get(c) for c in _TURN_COLS]
    vals[_TURN_COLS.index("ok")] = 1 if kw.get("ok", True) else 0
    cur = _conn().execute(
        f"INSERT INTO turns (t, {', '.join(_TURN_COLS)}, tried, tools) "
        f"VALUES (?, {', '.join('?' * len(_TURN_COLS))}, ?, ?)",
        [time.time()] + vals + [json.dumps(list(kw.get("tried") or [])),
                                json.dumps([str(x) for x in (kw.get("tools") or [])])])
    return cur.lastrowid


def turns(limit=50):
    """Most recent turns first."""
    rows = _conn().execute("SELECT * FROM turns ORDER BY id DESC LIMIT ?",
                           (max(1, min(int(limit or 50), 1000)),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["ok"] = bool(d["ok"])
        d["tried"] = _json_list(d.get("tried"))
        d["tools"] = _json_list(d.get("tools"))
        out.append(d)
    return out


# ---- memory block (one editable text; memory.py owns the format and the cap)

def get_memory():
    """The memory block text ("" if there is none yet)."""
    row = _conn().execute("SELECT text FROM memory WHERE id = 1").fetchone()
    return row["text"] if row else ""


def set_memory(text):
    _conn().execute("INSERT INTO memory (id, text, t) VALUES (1, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET text = excluded.text, t = excluded.t",
                    (text or "", time.time()))


# ---- running summary of old turns, per bot

def get_summary(bot):
    """(text, upto_id): the summary and the id of the last message folded into it; ("", 0) if none."""
    row = _conn().execute("SELECT text, upto_id FROM summary WHERE bot = ?", (bot,)).fetchone()
    return (row["text"], int(row["upto_id"])) if row else ("", 0)


def set_summary(bot, text, upto_id):
    _conn().execute("INSERT INTO summary (bot, text, upto_id, t) VALUES (?, ?, ?, ?) ON CONFLICT(bot) DO UPDATE "
                    "SET text = excluded.text, upto_id = excluded.upto_id, t = excluded.t",
                    (bot, text or "", int(upto_id or 0), time.time()))


# ---- approvals: "send"-risk actions wait here until the user taps Approve or Discard

APPROVAL_STATES = ("pending", "approved", "denied", "expired", "done", "failed")


def _approval(row):
    return {"id": row["id"], "t": row["t"], "action": _loads(row["action"], {}), "state": row["state"],
            "updated": row["updated"]}


def add_approval(action):
    """Store a pending action (a JSON-able dict, e.g. {"tool", "args", "summary"}); returns its id."""
    if not isinstance(action, dict):
        raise ValueError("action must be a dict")
    now = time.time()
    cur = _conn().execute("INSERT INTO approvals (t, action, state, updated) VALUES (?, ?, 'pending', ?)",
                          (now, json.dumps(action, ensure_ascii=False), now))
    return cur.lastrowid


def get_approval(approval_id):
    """{"id", "t", "action", "state", "updated"} or None."""
    try:
        approval_id = int(approval_id)
    except (TypeError, ValueError):
        return None
    row = _conn().execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    return _approval(row) if row else None


def set_approval(approval_id, state, expect=None):
    """Set an approval's state (one of APPROVAL_STATES). With `expect`, only when
    its current state is `expect` (expect="pending" stops a double tap running it
    twice). Returns True if it changed."""
    if state not in APPROVAL_STATES:
        raise ValueError(f"state must be one of {', '.join(APPROVAL_STATES)}")
    sql = "UPDATE approvals SET state = ?, updated = ? WHERE id = ?"
    args = [state, time.time(), int(approval_id)]
    if expect is not None:
        sql += " AND state = ?"
        args.append(expect)
    return _conn().execute(sql, args).rowcount > 0


def approvals(state=None, limit=50):
    """Approvals newest first, optionally only one state."""
    limit = max(1, min(int(limit or 50), 500))
    if state:
        rows = _conn().execute("SELECT * FROM approvals WHERE state = ? ORDER BY id DESC LIMIT ?",
                               (state, limit)).fetchall()
    else:
        rows = _conn().execute("SELECT * FROM approvals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_approval(r) for r in rows]


# ---- jobs: things promised for later ("remind me at 5"), run by the 5-minute tick

JOB_STATES = ("pending", "running", "done", "failed", "cancelled")


def _job(row):
    return {"id": row["id"], "t": row["t"], "due_t": row["due_t"], "kind": row["kind"],
            "payload": _loads(row["payload"], {}), "state": row["state"], "result": _loads(row["result"]),
            "done_t": row["done_t"]}


def add_job(due_t, kind, payload=None):
    """Schedule a job of `kind` at unix time `due_t`; returns its id."""
    if not kind or not isinstance(kind, str):
        raise ValueError("kind is required")
    cur = _conn().execute("INSERT INTO jobs (t, due_t, kind, payload) VALUES (?, ?, ?, ?)",
                          (time.time(), float(due_t), kind, json.dumps(payload or {}, ensure_ascii=False)))
    return cur.lastrowid


def due_jobs(now=None, claim=False, limit=100):
    """Pending jobs with due_t <= now, soonest first. claim=True also marks them
    "running" in one transaction, so two ticks can't both take the same job."""
    now = time.time() if now is None else float(now)
    c = _conn()
    sql = "SELECT * FROM jobs WHERE state = 'pending' AND due_t <= ? ORDER BY due_t, id LIMIT ?"
    if not claim:
        return [_job(r) for r in c.execute(sql, (now, int(limit))).fetchall()]
    c.execute("BEGIN IMMEDIATE")
    try:
        rows = c.execute(sql, (now, int(limit))).fetchall()
        c.executemany("UPDATE jobs SET state = 'running' WHERE id = ?", [(r["id"],) for r in rows])
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    out = [_job(r) for r in rows]
    for j in out:
        j["state"] = "running"
    return out


def finish_job(job_id, state, result=None):
    """Close a job: "done" | "failed" | "cancelled" (or "pending" again to retry
    on a later tick). `result` is any JSON-able value. Returns True if it changed."""
    if state not in JOB_STATES:
        raise ValueError(f"state must be one of {', '.join(JOB_STATES)}")
    done = time.time() if state in ("done", "failed", "cancelled") else None
    res = None if result is None else json.dumps(result, ensure_ascii=False)
    return _conn().execute("UPDATE jobs SET state = ?, result = ?, done_t = ? WHERE id = ?",
                           (state, res, done, int(job_id))).rowcount > 0


def get_job(job_id):
    row = _conn().execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
    return _job(row) if row else None


def jobs(state=None, limit=50):
    """Jobs soonest due first, optionally only one state."""
    limit = max(1, min(int(limit or 50), 500))
    if state:
        rows = _conn().execute("SELECT * FROM jobs WHERE state = ? ORDER BY due_t, id LIMIT ?",
                               (state, limit)).fetchall()
    else:
        rows = _conn().execute("SELECT * FROM jobs ORDER BY due_t, id LIMIT ?", (limit,)).fetchall()
    return [_job(r) for r in rows]


# ---- plans: the current multi-step plan per bot

def get_plan(bot):
    """The plan dict, or None."""
    row = _conn().execute("SELECT plan FROM plans WHERE bot = ?", (bot,)).fetchone()
    return _loads(row["plan"]) if row else None


def set_plan(bot, plan):
    """Store the plan (a dict), or clear it with None."""
    if plan is None:
        _conn().execute("DELETE FROM plans WHERE bot = ?", (bot,))
        return
    if not isinstance(plan, dict):
        raise ValueError("plan must be a dict or None")
    _conn().execute("INSERT INTO plans (bot, plan, t) VALUES (?, ?, ?) "
                    "ON CONFLICT(bot) DO UPDATE SET plan = excluded.plan, t = excluded.t",
                    (bot, json.dumps(plan, ensure_ascii=False), time.time()))


# ---- history search (memory.search calls this)

def _like(term):
    return "%" + term.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def search_messages(query, bot=None, limit=5):
    """Messages whose text contains `query` (case-insensitive LIKE), newest first.
    When the whole phrase isn't found, messages that contain every word of it."""
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(limit or 5), 50))

    def run(terms):
        where = " AND ".join(["text LIKE ? ESCAPE '!'"] * len(terms))
        args = [_like(t) for t in terms]
        if bot:
            where += " AND bot = ?"
            args.append(bot)
        rows = _conn().execute(f"SELECT * FROM messages WHERE {where} ORDER BY id DESC LIMIT ?",
                               args + [limit]).fetchall()
        return [_msg(r) for r in rows]
    found = run([q])
    words = [w for w in re.findall(r"[\w'-]+", q) if len(w) > 1]
    if not found and len(words) > 1:
        found = run(words[:8])
    return found


# ---- feedback: the user's like / dislike on a reply (persona.py turns it into lessons)

def _feedback(row):
    d = dict(row)
    d["dismissed"] = bool(d["dismissed"])
    return d


def set_feedback(message_id, vote, reason="", prompt="", reply="", model=None, tier=None):
    """Store (or replace) the vote on one message: 1 like, -1 dislike, 0 removes it. Returns the row or None."""
    vote = int(vote)
    if vote not in (-1, 0, 1):
        raise ValueError("vote must be 1, -1 or 0")
    c = _conn()
    if vote == 0:
        c.execute("DELETE FROM feedback WHERE message_id = ?", (int(message_id),))
        _bump_feedback()
        return None
    c.execute("INSERT INTO feedback (t, message_id, vote, reason, prompt, reply, model, tier) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(message_id) DO UPDATE SET t = excluded.t, "
              "vote = excluded.vote, reason = excluded.reason, prompt = excluded.prompt, reply = excluded.reply, "
              "model = excluded.model, tier = excluded.tier, dismissed = 0",
              (time.time(), int(message_id), vote, str(reason or "")[:300], str(prompt or "")[:4000],
               str(reply or "")[:8000], model, tier))
    _bump_feedback()
    row = c.execute("SELECT * FROM feedback WHERE message_id = ?", (int(message_id),)).fetchone()
    return _feedback(row) if row else None


def feedback(limit=200, include_dismissed=False, vote=None):
    """Feedback rows, newest first."""
    where, args = [], []
    if not include_dismissed:
        where.append("dismissed = 0")
    if vote is not None:
        where.append("vote = ?")
        args.append(int(vote))
    sql = "SELECT * FROM feedback" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY t DESC, id DESC LIMIT ?"
    return [_feedback(r) for r in _conn().execute(sql, args + [max(1, min(int(limit or 200), 5000))]).fetchall()]


def dismiss_feedback(ids):
    """Hide these feedback rows from the lessons (the user removed the lesson). Returns how many changed."""
    ids = [int(i) for i in (ids or [])]
    if not ids:
        return 0
    n = _conn().execute(f"UPDATE feedback SET dismissed = 1 WHERE id IN ({', '.join('?' * len(ids))})", ids).rowcount
    _bump_feedback()
    return n


def _bump_feedback():
    set_setting("feedback_version", int(get_setting("feedback_version", 0) or 0) + 1)


def feedback_version():
    """A counter that changes whenever feedback does (persona.py rebuilds its lessons block only then)."""
    return int(get_setting("feedback_version", 0) or 0)
