# theta-protos: shared spec (v0)

The next evolution of Theta.
- **Theta itself** runs on a Linux system: the model(s), memory, tools, Vantage.
- **The phone app** (a PWA, installable to the home screen) is where you talk to it.

It feels like a personal bot app: one assistant you text. Behind the scenes it picks the right model for each message but always answers in the same voice, and it texts you and pushes a notification on its own when something matters.

The reference screenshots are in `docs/ref-*.png`. Use them as a stencil for layout and flow only. Keep Theta's own identity:
- the dot-globe avatar
- the dot themes
- Theta's name and voice (`persona/SOUL.md`)

Never use another product's name, mascot or branding.

## Layout

```
server/            Python 3.11+, standard library only (plus optional `pywebpush`/`http_ece` for push)
  app.py           WSGI app + `python -m server` dev server (PORT, default 8780)
  db.py            SQLite storage ($PROTOS_DATA/protos.db, default ./data)
  models.py        providers: deepseek, anthropic, gemini, groq, openai-compatible local (Ollama etc.)
  router.py        picks the model per message
  persona.py       one system prompt for every model, so it answers the same
  push.py          Web Push (VAPID)
  proactive.py     decides when Theta texts first; runs every 5 minutes
  vantage.py       bridge to Vantage (events in, near you / world)
web/               the phone app: index.html, app.js, style.css, orb.js, sw.js, manifest.webmanifest, icons
persona/SOUL.md    copied from theta-app
deploy/            systemd units for the Linux box
tests/             test_*.py, stdlib only, run with `python3 tests/test_x.py`
```

## Auth

`PROTOS_KEY` (env) is sent as the `x-protos-key` header or the `protos_key` cookie. `/api/login` (POST {key}) and passkey sign-in set the cookie (HttpOnly, SameSite=Lax) to a random session token, never the key. 20 wrong keys in 10 minutes refuse the key for everyone for a while; session tokens are never locked out. Everything under `/api/` except `/api/login` and `/api/health` needs it. If `PROTOS_KEY` is unset, auth is off (local dev only); the app prints a warning.

## HTTP API (JSON unless noted)

```
GET  /                          the app (web/index.html); /static/* serves web/
GET  /api/health                {"ok": true, "version": "..."}
GET  /api/bots                  [{"id": "theta", "name": "Theta", "avatar": {...}}]   one bot in v0, list for later
GET  /api/messages?bot=theta&before=<id>&limit=50   {"messages": [Message...]}  oldest first
POST /api/chat                  {"bot": "theta", "text": "...", "client_id": "..."}
                                -> text/event-stream:
                                   event: user     data: Message (the stored user message)
                                   event: route    data: {"model": "deepseek-chat", "tier": "quick", "why": "short chat"}
                                   event: delta    data: {"text": "..."}         (many)
                                   event: done     data: Message (the stored reply, full text)
                                   event: error    data: {"error": "..."}
                                POST /api/chat?stream=0 returns {"user": Message, "reply": Message}
POST /api/messages/edit         {"id", "text"}: rewrite your latest user message (else 409), delete Theta's replies to it
                                (not other proactive texts) and answer again; streams like /api/chat, starting with
                                event: deleted data: {"ids": [...]}. Tool effects stay done; meta.note says so.
POST /api/feedback              {"message_id", "vote": 1|-1|0, "reason"?}  like / dislike a reply (0 removes it)
GET  /api/feedback/summary      {"lessons": [{"id", "text", "n"}], "likes", "dislikes"}; DELETE ?id=<lesson id> drops one
GET  /api/feedback/export       liked replies as JSONL {prompt, reply, tier, model}: save as evals/feedback.jsonl
GET  /api/inbox?since=<id>      {"messages": [Message...]}  new messages since id (incl. proactive ones); the app polls every 20 s while open
GET  /api/push/key              {"key": "<VAPID public key, base64url>"}
POST /api/push/subscribe        {"subscription": {...}}  -> {"ok": true}
POST /api/push/test             sends a test push
GET  /api/connections           [{"id": "gmail", "name": "Gmail", "connected": false, "what": "Search, read, draft..."}]  v0: status only
GET  /api/settings / POST /api/settings   {"proactive": true, "quiet": [22, 7], "tz": "America/Denver", "loc": {"lat":..,"lon":..}|null}
```

Message = `{"id": int, "bot": "theta", "role": "user"|"assistant", "text": str, "t": unix seconds, "meta": {...}}`.
The meta keys are:
- `model`, `tier`: assistant replies. `usage: {in, out, cached, cost_usd, model}` (the turn's tokens; research
  helpers included), `sources: [{title, url}]` (the reply cites them as [n]), `reply_to` (the user message it
  answers), `vote` (1 / -1 after feedback), `note` (after an edit, tool effects that weren't undone).
- `proactive: true`, `source: "vantage"|"brief"|"reminder"`, `level: 3|4`: messages Theta sent first.

## db.py interface (owned by the backend; others call only these)

```python
init(path=None)                          # creates tables; idempotent
add_message(bot, role, text, meta=None) -> dict   # returns the Message
messages(bot, before=None, limit=50) -> list[dict]
since(msg_id, bot=None) -> list[dict]
get_setting(key, default=None) / set_setting(key, value)   # JSON values
add_push_sub(sub: dict) / push_subs() -> list[dict] / drop_push_sub(endpoint)
seen(key) -> bool / mark(key, ttl_days=7)                   # dedupe for proactive sends
```

## Routing ("picks the model, answers the same")

`router.pick(text, history, attachments=()) -> Route(tier, model, provider, why)`

| Tier | When | Default model |
|---|---|---|
| quick | short chat, greetings, simple facts | deepseek-chat (or groq llama, gemini flash) |
| think | planning, math, multi-step, "why/compare/should I" | deepseek-reasoner (or claude) |
| code | code, errors, stack traces | the best coder available |
| search | news, prices, "today", live facts | quick model + web search (Tavily if `TAVILY_API_KEY`) |
| vision | an image attached | gemini / claude |
| local | `PROTOS_LOCAL_FIRST=1`, or private things | `LOCAL_LLM_URL` (OpenAI-compatible) |

How picking works:
1. A fast heuristic decides first, so there is no extra model call for most messages.
2. Only ambiguous cases go to a tiny classifier call to the quick model.
3. Fallback: if the chosen provider has no key or fails, try the next one in that tier, then quick.

The persona prompt is identical across models, and a light post-pass enforces the same voice (no "As an AI", short first).

## Proactive (Theta texts first)

Every 5 minutes, `proactive.run(now)` collects candidates from:
- Vantage
- the morning (7:00) and evening (18:00) brief
- reminders (later)

Each candidate is scored. A candidate that passes becomes an assistant message with `meta.proactive=true`, and it is pushed as `notify(title="Theta", body=..., url="/?m=<id>")`.

Rules:
- Each event goes out once (`db.seen/mark`).
- Never rumors.
- Quiet hours: Orange waits, Red (level 4) wakes you.
- At most N proactive messages a day (default 6).

## Vantage

Vantage runs inside Theta (theta-app) at `/vantage`. The bridge reads `VANTAGE_URL` (e.g. `https://<theta>/vantage`) with `VANTAGE_KEY` (Theta's dashboard key) from `GET /api/state`, or reads a local Vantage checkout via `VANTAGE_DIR`. It turns that into events. The event rules come from theta-app `api/_parts/vantage.py` `vantage_events()`: near you (quake, tsunami, official alerts, storm or volcano zones, military activity confirmed by 3+ outlets, severe space weather) and world (a story 5+ outlets carry, M7+, a region far above normal, a tsunami warning, a market shock).

Storage note: **SQLite, local.** Theta-app went down when its hosted Redis ran out of free commands; protos must never depend on a metered per-command store.
