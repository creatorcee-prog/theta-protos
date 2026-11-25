# Harness plan: applying docs/HARNESS.md (v0.2)

Two builders work in parallel. Each owns separate files; the interfaces below connect them.

## Builder A: context, memory, evals
Owns: `server/persona.py`, `server/router.py`, `server/db.py`, `server/memory.py` (new), `evals/` (new), and their tests.

### 1. Prompt order for caching (persona.py)
The system prompt is stable: SOUL, style rules, a few short example exchanges in place of a growing rule list, the tool guide, and the memory block (changes rarely).

Everything that changes per turn goes LAST, inside the latest user turn as a context block:
- date and time
- search results
- Vantage context

`build(history, text, ...)` returns messages in this order:
1. the system prompt
2. the running summary of old turns (an assistant-visible note)
3. the recent turns
4. the user turn with the volatile context appended

Keep `system_prompt()`, `build()`, `clean()` and `ack()` working (app.py calls them).

### 2. Router stickiness (router.py)
`pick(text, history, attachments, last=None)`: if `last` (the previous turn's Route) is within 10 minutes and its tier is "close enough", reuse that model so the provider cache stays warm. Switch only on a real tier change (quick↔think↔code, or vision or search needed).

### 3. Memory the model can edit (memory.py), stored in db
```
block() -> str                      the current memory block (cap 2,000 chars) for the system prompt
edit(op, text, old=None) -> dict    op in add|replace|remove; returns {"ok", "block"}; refuses over the cap
summary(bot) -> str                 the running summary of turns older than the last 20
compact(bot, summarize=fn) -> bool  folds turns older than the last 20 into the summary when there are >= 10 new
                                    old turns; summarize(text)->str is injected (the quick model, via app)
search(query, limit=5) -> list      LIKE search over full message history (a tool will call it)
```

### 4. db.py additions
- `turns` gets these columns: `tokens_in`, `tokens_out`, `cache_read`, `cache_write`, `cost_usd`, `steps`, `tools` (JSON list).
- `add_turn(**kw)` accepts them.
- New tables and functions:
```
memory:    get_memory()->str / set_memory(text)
summary:   get_summary(bot)->(text, upto_id) / set_summary(bot, text, upto_id)
approvals: add_approval(action:dict)->id ; get_approval(id) ; set_approval(id, state)  state: pending|approved|denied|expired|done|failed
jobs:      add_job(due_t, kind, payload:dict)->id ; due_jobs(now)->list ; finish_job(id, state, result=None)
plans:     get_plan(bot)->dict|None ; set_plan(bot, plan:dict|None)
```

### 5. evals/
- `evals/golden.jsonl`: about 25 golden conversations, each with fields `{id, turns:[user texts], expect: {tier?, must?, must_not?, max_chars?}}`.
- `evals/run.py`: runs them through the real app in-process with `--repeat 3`, and reports pass rates and route accuracy.
- Offline mode with fake models for CI. A live mode (DeepSeek works in this sandbox) is used for real checks.

## Builder B: tools, agent loop, approvals, jobs
Owns: `server/models.py`, `server/tools.py` (new), `server/agent.py` (new), `server/app.py`, and their tests.

### 1. models.py
- Report usage for each provider (tokens in and out, cache read and write) via `stream(..., usage=dict)`, which fills the passed dict.
- Anthropic: `cache_control` on the system block.
- Tool calling: `call(provider, model, messages, tools, max_tokens) -> {"text", "tool_calls":[{id,name,args}], "usage"}` for deepseek and groq (OpenAI-style), anthropic (tool_use) and gemini (functionDeclarations).

### 2. tools.py
5 to 8 tools that don't overlap, each `{name, description (written like docs for a new hire), params (JSON schema), risk: "read"|"write"|"send", run(args)->str}`. Outputs are capped (~2,000 chars); errors say how to fix the call.

The v0 tools:
- `web_search` (Tavily)
- `memory_edit` (memory.edit)
- `history_search` (memory.search)
- `remind_me` (db.add_job: a "later" promise becomes a real job)
- `vantage_now` (the server.vantage state summary)
- `plan_update` (db.set_plan)
- `send_email_draft`: risk "send", approval-gated; a stub until Gmail is connected

### 3. agent.py
`run(route, messages, emit) -> final text`:
- The loop calls models.call with tools.
- Step cap of 6. Timeouts: 20 s per tool, 90 s per turn.
- At the cap, a final no-tools answer.
- Tools rated read and write run directly.
- Tools rated "send" never run: they create `db.add_approval` and emit an approval card. The message gets `meta.actions = [{label:"Approve", value:"approve:<id>"}, {label:"Discard", value:"deny:<id>"}]`, and the action runs only when the user taps it (POST /api/approve {id, decision}).
- `emit(event, data)` sends SSE `tool` events: `{"name", "state": "running"|"done"}`. The phone shows them as task cards (meta.task).
- Final text streams as usual.

### 4. app.py wiring
- The chat handler uses agent.run when tools are relevant; plain stream for quick chat with no tools.
- It logs usage, cost, steps and tools in add_turn.
- After the reply, it calls `memory.compact(bot, summarize=quick model)` in the background.
- New routes:
  - `GET /api/memory`, `POST /api/memory` {op, text, old}
  - `POST /api/approve`
  - `GET /api/plan`
  - `GET /api/jobs`
- Jobs: the 5-minute tick runs `due_jobs(now)`. A "remind" job sends a proactive message plus a push (through `server.proactive`'s send helper, or `db.add_message` plus `push.notify`).
- Ack-then-result is extended to tool turns: if the first step calls a tool, send the ack first.
