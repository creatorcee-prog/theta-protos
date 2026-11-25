# theta-protos

Theta's next shape: Theta runs on a Linux box (models, memory, Vantage) and
the phone app (a PWA in `web/`) is where you text it. Contract: `docs/SPEC.md`.

## Run

```sh
DEEPSEEK_API_KEY=sk-... PROTOS_KEY=change-me python3 -m server   # http://localhost:8780
python3 tests/test_core.py && python3 tests/test_router.py       # no network, fake models
```

Python 3.11+, standard library only (`requirements.txt` lists the optional push libs).

## Environment

| Var | What |
|---|---|
| `PORT`, `HOST` | listen address (default `0.0.0.0:8780`) |
| `PROTOS_KEY` | app key (`x-protos-key` header or `protos_key` cookie via `/api/login`). Unset = no auth, local dev only |
| `PROTOS_DATA` | data dir for `protos.db` (default `./data`) |
| `PROTOS_WEB` | web root (default `./web`) |
| `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY` | model providers; any subset |
| `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`), `ANTHROPIC_QUICK_MODEL`, `GEMINI_MODEL`, `GEMINI_THINK_MODEL`, `GROQ_MODEL`, `GROQ_THINK_MODEL` | model id overrides |
| `LOCAL_LLM_URL`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_KEY` | OpenAI-compatible local model (Ollama, LM Studio), `.../v1` URL |
| `PROTOS_LOCAL_FIRST=1` | try the local model first in every tier |
| `TAVILY_API_KEY` | live web search for the search tier (otherwise Theta says it couldn't check live) |
| `PROTOS_CLASSIFIER=0` | never make the tiny routing-classifier call |
| `PROTOS_TZ` | fallback time zone (the app's `tz` setting wins; default America/Denver) |
| `PROTOS_TICK=0` | don't run `proactive.run()` every 5 minutes |
| `PROTOS_MAX_TOKENS`, `PROTOS_LLM_TIMEOUT` | reply length cap (1200), provider timeout seconds (90) |
| `VANTAGE_URL`, `VANTAGE_KEY`, `VANTAGE_DIR` | Vantage bridge (see `server/vantage.py`) |

## Layout

```
server/app.py        WSGI app, routes, SSE chat, static web/, threaded dev server, 5-minute tick
server/db.py         SQLite (WAL, one connection per thread): messages, settings, push subs, seen, turns
server/models.py     streaming providers over urllib: deepseek, anthropic, gemini, groq, local
server/router.py     heuristics (+ optional tiny classifier) -> tier -> candidate models, Tavily search
server/persona.py    one system prompt for every model (persona/SOUL.md), clean(), ack templates
server/push.py       Web Push (VAPID)            server/proactive.py  Theta texts first
server/vantage.py    Vantage bridge              web/                 the phone app
tests/               python3 tests/test_*.py
```

Chat streams `event: user`, `route`, (`ack` for think/search turns), `delta`..., then `done` (or `error`).
`GET /api/turns?limit=` shows the per-turn routing and latency log.
