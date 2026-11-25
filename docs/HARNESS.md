# Harness: how the best agents are configured, and what Theta should take from them

Date: 2026-11-25. Research only; no code. Every factual claim links its source. **(uncertain)** marks inference, secondhand reports, or claims I could only check against a summary. "My suggestion" marks design calls that are mine, not a source's.

## 1. Harnesses in plain words

A language model on its own does one thing: it reads some text and writes more text. Everything that turns that into an assistant is the **harness**, the program around the model. The harness decides:
- what the model gets to read (persona, date, memory, recent chat, tool results);
- which actions it is offered (tools) and how they are described;
- what happens to its output: run the tool, feed the result back, ask again, stop;
- what it may do without asking you;
- what gets saved for next time, and what gets logged so someone can see what went wrong.

OpenAI's guide reduces an agent to three parts: a model, tools and instructions, run in a loop "until an exit condition is reached" ([OpenAI guide, pp. 7, 14](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)). Anthropic's version is "LLMs using tools based on environmental feedback in a loop", with the core loop "gather context -> take action -> verify work -> repeat" ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), [Agent SDK post](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)).

**Why the same model can be great or bad.** The model only knows what is in its window at that moment. The harness controls that window, so it controls the result:
- SWE-agent ran the same GPT-4 Turbo in two harnesses. A plain shell solved 11.0% of SWE-bench Lite tasks; a purpose-built interface solved 18.0%. Removing one guardrail (a linter that rejects broken edits) cost 3 points ([SWE-agent paper](https://arxiv.org/html/2405.15793)).
- Anthropic's team "spent more time optimizing our tools than the overall prompt" for their SWE-bench agent ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).
- More context is not better. Recall degrades as the window fills ("context rot"), so context is "a finite resource with diminishing marginal returns" ([Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)). One study saw an average 39% drop when the same task arrived in pieces over several turns, because early wrong guesses stayed in the context ([Breunig, How contexts fail](https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html)).

One analogy: the model is a capable new hire who forgets everything when they leave the room. The harness is the briefing pack, the desk, the phone with only certain numbers on speed dial, and the manager who signs off before anything leaves the building.

## 2. Principles the best harnesses share

**P1. Start simple; add machinery only when it earns its place.**
"Finding the simplest solution possible, and only increasing complexity when needed"; prefer direct API calls over frameworks that hide the prompts ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)). OpenAI: "maximize a single agent's capabilities first" ([OpenAI guide, p. 16](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)).
*Why it works:* every layer is something you must debug, and you cannot fix a prompt you cannot see.

**P2. The loop has explicit stop conditions.**
Stop when the model answers without a tool call, calls a final-output tool, hits an error, or reaches a max-turn cap ([OpenAI guide, pp. 14-15](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)). Anthropic recommends "stopping conditions (such as a maximum number of iterations)" ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)). Claude Code's Stop hook sends the model back to work when a check fails, but gives up after eight blocked stops in a row ([Claude Code best practices](https://code.claude.com/docs/en/best-practices)).
*Why it works:* a loop without a ceiling turns one confused step into an unbounded bill.

**P3. Tools are an interface designed for the model, not a wrapper around an API.**
- Few, purpose-built, consolidated tools instead of one per endpoint, e.g. one scheduling tool that finds a slot *and* books it; namespaced names; return meaningful names, not opaque IDs; offer `response_format` concise/detailed; paginate or truncate big outputs (Claude Code caps tool responses at 25,000 tokens by default); write errors that say how to fix the call; describe each tool "as if you were explaining it to a new hire"; parameter names like `user_id`, not `user` ([Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)).
- Poka-yoke the arguments so mistakes are hard to make; Anthropic switched to absolute paths after relative paths caused errors ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).
- SWE-agent's rules: simple actions, compact actions, "informative but concise" feedback, guardrails. A 100-line file window beat both 30 lines and the whole file, and search capped at 50 results beat stepping through matches one by one ([SWE-agent paper](https://arxiv.org/html/2405.15793)).
- Overlap matters more than count. Some agents handle 15+ distinct tools, while others struggle with fewer than 10 overlapping ones ([OpenAI guide, p. 16](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)). A quantized Llama 3.1 8B failed with 46 tools and succeeded with 19 ([Breunig](https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html)).

*Why it works:* the model chooses and fills in tools from their descriptions alone. Ambiguous descriptions lead to ambiguous calls.

**P4. Treat context as a budget: write, select, compress, isolate.**
- LangChain's four moves: write context outside the window, select what to pull in, compress to what's needed, isolate across sub-agents or state ([LangChain](https://www.langchain.com/blog/context-engineering-for-agents)).
- Failure modes to design against: poisoning, distraction, confusion and clash ([Breunig](https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html)).
- The system prompt should sit at the "right altitude", between brittle if-then rules and vague guidance. Use a few diverse, canonical examples rather than a pile of edge-case rules ([Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)).
- Load just in time: keep light references (paths, queries, links) and fetch with tools when needed ([same](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)). Cursor sends only skill and MCP tool *names* up front and lets the agent look up details, which cut total tokens by 46.9% in runs that used an MCP tool ([Cursor](https://cursor.com/blog/dynamic-context-discovery)). Aider sends a ranked repo map under a 1k-token default budget ([Aider](https://aider.chat/docs/repomap.html)).

*Why it works:* attention is spread over every token in the window, so irrelevant tokens dilute the relevant ones.

**P5. Keep the prompt prefix stable so the provider can cache it.**
- Manus calls KV-cache hit rate "the single most important metric for a production-stage AI agent". Its input:output ratio is about 100:1, and cached Sonnet input cost $0.30/MTok against $3 uncached. Common mistake: a timestamp at the top of the system prompt. Keep context append-only and serialization deterministic, since even JSON key order matters ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)).
- Every provider Theta uses caches by **prefix**:
  - **Anthropic:** cache order is tools → system → messages; up to 4 breakpoints; 5-minute default TTL (1 h optional); writes cost 1.25x and reads about 0.1x base for most models; one top-level `cache_control` turns on automatic caching ([Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)).
  - **OpenAI-style:** automatic; static content first, variable content last; ≥1,024 tokens; hits reported as `cached_tokens` ([OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)).
  - **DeepSeek:** on by default, best effort; reports `prompt_cache_hit_tokens` ([DeepSeek](https://api-docs.deepseek.com/guides/kv_cache)).
  - **Gemini:** implicit caching on 2.5+ with a 2,048-4,096-token minimum ([Gemini caching](https://aistudio.google.com/docs/caching)).

*Why it works:* the provider skips recomputing a prefix it has already seen. A single changed byte invalidates everything after it.

**P6. Long conversations are compacted, not just cut off.**
- Summarize near the limit and continue from the summary; tune for recall first, precision second. Clearing old tool results is the lightest-touch form ([Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)).
- Anthropic's context editing cut tokens 84% in a 100-turn web-search eval. With the memory tool it scored 39% over baseline ([Context management](https://claude.com/blog/context-management)). These are vendor-reported numbers.
- Cursor keeps the full chat history as a file, so the agent can search it to recover what a lossy summary dropped ([Cursor](https://cursor.com/blog/dynamic-context-discovery)). Manus keeps compression restorable, e.g. dropping a page body but keeping its URL ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)).

*Why it works:* a summary holds decisions and facts in far fewer tokens than the raw turns. Keeping the raw turns retrievable means summarizing loses nothing for good.

**P7. Memory lives outside the window, and the agent maintains it.**
- MemGPT treats the window like OS main memory, paging information in and out of slower storage ([MemGPT](https://arxiv.org/abs/2310.08560)).
- Letta's memory blocks are labeled, size-capped sections that are always in context and that the agent edits through tools. They can be marked read-only ([Letta memory blocks](https://docs.letta.com/guides/agents/memory-blocks); fetched page was the v1-SDK version).
- Anthropic's memory tool is file-based and client-side: the developer owns the storage ([Context management](https://claude.com/blog/context-management)).
- Claude Code loads CLAUDE.md into every session, so keep it short ([Claude Code best practices](https://code.claude.com/docs/en/best-practices)).
- Caution: memory pulled in unexpectedly makes users feel the window "no longer belongs to them" ([LangChain](https://www.langchain.com/blog/context-engineering-for-agents)).

*Why it works:* a few curated facts that are always visible beat a big store the model has to remember to search.

**P8. Long or multi-step work keeps an explicit plan or to-do state.**
- Manus rewrites a `todo.md` throughout a task (about 50 tool calls on average) to keep goals near the end of the context ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)).
- Anthropic's research lead agent saves its plan to memory because context beyond 200k tokens gets truncated ([Multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system)).
- Long-running coding agents use a progress file plus a JSON feature list with a `passes` flag, work one feature at a time, and otherwise tend to "declare victory" too early ([Effective harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).

*Why it works:* the plan survives compaction and restarts, and restating it keeps the model on goal.

**P9. Rules that must always hold are enforced in code, not in the prompt.**
- Prompt rules are followed "nearly every time", but whether they are followed is still the model's call. "If something has to happen every time, make it a hook, a deny rule, or a managed setting" ([Claude Code best practices](https://code.claude.com/docs/en/best-practices)).
- OpenAI rates each tool low/medium/high risk (read vs write, reversibility, financial impact) and escalates to a human for high-risk actions or after repeated failures ([OpenAI guide, pp. 26, 31](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)).
- Codex: sandbox modes plus approval policies, with network off by default ([Codex approvals](https://learn.chatgpt.com/docs/agent-approvals-security)).
- LangGraph `interrupt()` pauses before a `send_email` tool runs, persists state, and resumes on approval. Side effects before an interrupt must be idempotent ([LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)).
- The "lethal trifecta" is private data + untrusted content + a way to send data out. Email is the textbook attack, and guardrails that catch "95%" are a "failing grade" ([Willison](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)).

*Why it works:* a prompt can be talked out of a rule (including by text inside an email); an `if` statement cannot.

**P10. Errors stay visible and recovery is built in.**
- Manus leaves failed actions and stack traces in context so the model updates and doesn't repeat them ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)).
- Errors compound in long agents, so Anthropic resumes from checkpoints instead of restarting ([Multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system)).
- Tool errors should be actionable text, not tracebacks ([Writing tools](https://www.anthropic.com/engineering/writing-tools-for-agents)).
- Self-check before "done": rules and linters, screenshots, an LLM judge ([Agent SDK post](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)).

*Why it works:* the model can only correct mistakes it can see.

**P11. Route per task, and baseline with the best model first.**
- Prototype with the most capable model, then swap in smaller models where evals say they're good enough ([OpenAI guide, p. 8](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)).
- Routing is a named pattern ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).
- RouteLLM reports more than 2x cost savings without quality loss on its benchmarks ([RouteLLM](https://arxiv.org/abs/2406.18665)).
- The GPT-5 router launch shows a misrouting failure is very visible to users ([docs/RESEARCH.md §2](RESEARCH.md)).

*Why it works:* most messages are easy, so you pay for a big model only when it changes the answer.

**P12. Evals and traces drive every change.**
- Start with "20-50 simple tasks drawn from real failures"; grade the outcome, not the path; use code graders where possible and model graders calibrated against humans; run several trials. pass^k (every trial passes) is the metric for user-facing consistency. Read the transcripts ([Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)).
- Anthropic's research system started with about 20 real queries and uses full production tracing ([Multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system)).
- Tools improve by running evals and reading transcripts ([Writing tools](https://www.anthropic.com/engineering/writing-tools-for-agents)).

*Why it works:* prompt and tool changes have non-local effects, and without a re-runnable set you only learn about regressions from users.

**P13. Cost and latency are harness decisions.**
- Token use explained 80% of performance variance on BrowseComp. Agents use about 4x chat's tokens and multi-agent systems about 15x. Parallel tool calls cut research time up to 90%. Effort-scaling rules in the prompt (3-10 tool calls for a simple fact) keep easy tasks cheap ([Multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system)).
- Cache hits (P5) and lazy loading (P4) are the other big levers.

*Why it works:* spend follows what the harness lets into the window and how many steps it allows.

## 3. Where experts disagree

1. **Multi-agent vs single-agent.**
   - Cognition: "Don't build multi-agents." Share full traces, because "actions carry implicit decisions". Parallel sub-agents built a Mario-style background for a Flappy Bird clone. Their default is one linear agent plus a compression model for long histories ([Cognition](https://cognition.com/blog/dont-build-multi-agents)).
   - Anthropic: a multi-agent research system beat single-agent Opus by 90.2%, at about 15x chat's tokens. Anthropic agrees it fits poorly where agents share context or depend on each other, including most coding ([Multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system)).
   - Middle ground: OpenAI says go single-agent first and split on complex logic or tool overload ([OpenAI guide](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)). Sub-agents that only *answer questions* and return 1-2k-token summaries are the pattern both sides accept ([Cognition](https://cognition.com/blog/dont-build-multi-agents), [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)).
   - Takeaway: the split is by task shape. Breadth-first reading parallelizes; writing and acting don't.
2. **Fixed tool list vs dynamic tool loading.**
   - Manus: don't add or remove tools mid-task, because it breaks the cache and confuses the model; mask them instead ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)).
   - Cursor loads MCP tool details lazily ([Cursor](https://cursor.com/blog/dynamic-context-discovery)). LangChain cites RAG over tool descriptions tripling selection accuracy, a figure the post itself sources only to "some recent papers" **(uncertain)** ([LangChain](https://www.langchain.com/blog/context-engineering-for-agents)).
   - They agree on one thing: keep the *visible list* stable (names), and fetch details on demand.
3. **Truncate tool output vs offload it.** Anthropic paginates and truncates ([Writing tools](https://www.anthropic.com/engineering/writing-tools-for-agents)). Cursor writes long output to a file instead of truncating ([Cursor](https://cursor.com/blog/dynamic-context-discovery)).
4. **Agentic search vs semantic search.**
   - Anthropic's SDK post says start with agentic (grep-style) search ([Agent SDK post](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)).
   - Cursor reports semantic search plus grep is 12.5% more accurate than grep alone ([Cursor search docs](https://cursor.com/docs/agent/tools/search.md)). I saw only the summary of this claim **(uncertain)**.
5. **LLM-as-judge.**
   - In Anthropic's research system, an LLM judge was the most consistent grader and the closest to human judgment ([Multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system)).
   - The SDK post calls it "generally not a very robust method" ([Agent SDK post](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)).
   - The evals post: use it, but calibrate against humans ([Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)).
6. **How much to ask the user.** More approvals feel safer. But sandboxing cut Claude Code's permission prompts by 84%, and Anthropic warns that "approval fatigue" makes people stop reading what they approve ([Sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing)). Gate the few irreversible things hard and let the rest flow.
7. **Frameworks.** Anthropic advises starting with raw API calls ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)). OpenAI pushes a code-first SDK over declarative graphs ([OpenAI guide, p. 20](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)). LangGraph is a graph framework with built-in checkpoints and interrupts ([LangGraph](https://docs.langchain.com/oss/python/langgraph/interrupts)). Theta's stdlib-only rule (SPEC) already answers this: raw calls.
8. **Compaction method.** Anthropic uses general summarization ([context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)). Cognition fine-tuned a dedicated compression model and says it is hard to get right ([Cognition](https://cognition.com/blog/dont-build-multi-agents)). Manus prefers restorable dropping over summarizing ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)).
9. **Poke's harness.** Nothing official is public. The acquisition post covers only behavior: it texts first and follows up ([Cognition/Interaction](https://cognition.com/blog/interaction)). The "one interaction agent speaks, hidden execution agents work" design comes from unofficial prompt dumps and write-ups **(uncertain)** ([OpenPoke write-up](https://composio.dev/content/open-poke)). Grok Bot's public docs cover UX, not internals ([RESEARCH.md](RESEARCH.md)).

## 4. Lessons for Theta (prioritized, each buildable)

Current state (read on 2026-11-25), to be re-checked:
- `persona.system_prompt` puts SOUL → STYLE → **minute-level time** → memory notes → `extra`.
- `persona.HISTORY = 20` is a hard cut.
- `models.py` streams text only, without usage numbers, and sends no `cache_control`.
- `app._chat_worker` already sends a templated ack for think/search turns and logs each turn to `turns` (tier, model, ttft/total ms, chars, fallbacks).
- There are no tools yet.

### P0: do before tools land

1. **Stable prefix, volatile last** (`persona.py`, `models.py`).
   - Order the prompt: SOUL → STYLE → tool docs → memory block (changes rarely) → compacted summary → history. Then a short final context line with the date, time, place and any search results, attached to the *latest user turn*.
   - Never put the time in the system prompt. Today it changes every minute and invalidates the cache for everything after it ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)).
   - Serialize tool schemas and JSON deterministically (sorted keys).
   - In `_anthropic_stream`, add top-level `cache_control: {"type": "ephemeral"}` ([Anthropic caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)).
   - Two caveats. Today's prompt is roughly 700 tokens (SOUL.md is 2.1 KB; my estimate), below several providers' minimums, so savings start once tools and history are in the prefix. Caches are per model, so switching providers between messages forfeits hits **(inference)**. My suggestion: keep the router "sticky" within a burst of messages unless the tier really changes.
2. **Per-turn usage, cost and cache logging** (`models.py`, `db.turns`, `app.py`).
   - Have `stream()` yield a final usage record: input, cached, output tokens, read from each provider's usage fields ([OpenAI](https://developers.openai.com/api/docs/guides/prompt-caching), [DeepSeek](https://api-docs.deepseek.com/guides/kv_cache), [Anthropic](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)).
   - Add `tokens_in / tokens_cached / tokens_out / cost_usd / steps / tool_calls` columns to `turns`.
   - Show the cache hit rate and spend per day at `/api/turns`.
3. **`tools.py`: a small registry written like docs for a new hire** ([Writing tools](https://www.anthropic.com/engineering/writing-tools-for-agents)).
   - Each tool gets a namespaced name (`gmail_search`, `calendar_find_time`, `calendar_book`, `reminder_set`, `web_search`), a description with when to use it, when *not* to, and an example, and a `risk` of low/med/high ([OpenAI guide](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)).
   - Poka-yoke the arguments: absolute ISO datetimes with time zone, never "tomorrow"; contact names, not raw IDs.
   - Results are short and readable (sender, subject, date, a one-line snippet). The concise format is the default and the detailed format is available on request. Output is capped; my suggestion is about 2k tokens for a phone assistant, with "N more, narrow the query" on overflow ([SWE-agent](https://arxiv.org/html/2405.15793)).
   - Errors say what to change ("date must include a time zone, e.g. 2026-11-26T09:00-07:00").
   - Start with 5-8 tools that don't overlap, and keep the list the same across turns ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)).
4. **`agent.py`: one tool loop with hard limits** ([OpenAI guide](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf), [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).
   - Call the model with tools. If it makes no tool call, stream the answer and stop. Otherwise run the calls (read-only ones in parallel), append the results, and repeat.
   - Caps (my suggestion): 6 steps for chat and 20 for background jobs; about 15 s per tool and 60 s per turn.
   - At the cap, make one last call with no tools: "answer with what you have, say what's missing."
   - Tool errors go back into the context as results ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)). Retry transient HTTP failures once with backoff.
   - Keep today's rule that provider fallback happens only before any text or side effect has gone out.
   - Use the same loop for every provider that supports tool calls. Whether the local model and each quick-tier model call tools reliably is **(uncertain)**; test with evals, and route tool turns only to models that pass.
5. **Approval gates in code for anything that sends, deletes, books or pays** (`tools.py`, `app.py`, web cards).
   - High-risk tools never execute when the model calls them. They store a pending action (a message with `meta.pending_action` holding the exact arguments) and show an Approve / Edit / Discard card.
   - On approve, the *server* runs the action with those stored arguments, without another model call. Approvals expire after about 30 minutes ([RESEARCH.md](RESEARCH.md)). Execution is idempotent, keyed by action ID ([LangGraph](https://docs.langchain.com/oss/python/langgraph/interrupts)).
   - Gmail gives Theta the full lethal trifecta ([Willison](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)). Wrap email and web text in an "untrusted content" frame, and never let content fetched in a turn unlock a send without the user's tap.
   - Low-risk reads run freely, to avoid approval fatigue ([Sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing)).
6. **Ack-then-result for tool turns too** (`app.py`, `persona.ack`).
   - Extend today's think/search ack to any turn that will call a tool.
   - If the loop passes about 10 s, keep working in the background and deliver the result as a new message through inbox + push ([RESEARCH.md §3](RESEARCH.md)).
   - Any "I'll tell you later" must create a scheduled job row at that moment ([RESEARCH.md §5](RESEARCH.md)).

### P1: next

7. **A memory block the model edits** (`memory.py`, used by `persona.py`).
   - Replace the "last 8 notes" with a labeled, size-capped core block (my suggestion: about 2,000 characters, in sections such as `about_you`, `preferences`, `people`), always in the prompt ([Letta](https://docs.letta.com/guides/agents/memory-blocks)).
   - Tools: `memory_add(section, fact)` and `memory_replace(old, new)`.
   - Write after the reply is sent, so it never delays the turn (my suggestion).
   - Keep older or long facts in SQLite with a `memory_search` tool ([MemGPT](https://arxiv.org/abs/2310.08560)).
   - Add a "What Theta remembers" screen where the user can edit or delete entries ([LangChain](https://www.langchain.com/blog/context-engineering-for-agents)).
8. **Compaction instead of a 20-message cut** (`persona.build`, `db`).
   - When history passes a token budget, the quick model folds the oldest turns into a running `summary` (facts, decisions, open promises), written for recall ([Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)).
   - Raw messages stay in SQLite, and a `history_search` tool can recover details ([Cursor](https://cursor.com/blog/dynamic-context-discovery)).
   - Clear bulky old tool results first; it is the cheapest compaction step ([Context management](https://claude.com/blog/context-management)).
   - Update the summary only every N turns so the prefix stays cacheable.
9. **Plan / to-do state for multi-step tasks** (`db.tasks`, `agent.py`).
   - A `plan_update(steps, done)` tool writes a small task row. The current plan is restated at the end of the context on each step ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)).
   - Background jobs resume from the saved plan instead of starting over ([Multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system)).
   - A task is "done" only when its check passes ([Effective harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
   - The same table powers the "pending commitments" cards.
10. **Golden-conversation evals** (`tests/evals/`, stdlib).
    - Start with 20-50 cases taken from real transcripts and failures ([Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)). Each case has a history, a message and checks.
    - Code graders: expected tier from `router.pick`; no "As an AI" or filler; length limit; the right tool and arguments; no send without approval.
    - A model grader for "sounds like SOUL.md", spot-checked by a human.
    - Run each case 3 times and report pass^k. Re-run after any change to the persona, router, tools or model.
    - Add a router-only set of about 100 labeled messages, since routing is cheap to test offline.
11. **Traces you can read** (`db`, `/api/turns`).
    - Store each step of a turn (model call, tool name, arguments, result size, latency, error) in a `steps` table linked to `turns`.
    - Review failed and slow turns weekly and turn them into eval cases ([Agent SDK post](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)).
    - Redact email bodies in logs (my suggestion).
12. **Router calibration** (`router.py`).
    - Run the evals on the strongest model per tier first, then downgrade wherever pass^k holds ([OpenAI guide](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)).
    - Keep the heuristic-first design. Log the "why" and check misroutes against the eval set.
    - Honor "think harder" from the user.
13. **Persona at the right altitude** (`persona/SOUL.md`, `persona.STYLE`).
    - Replace growing rule lists with 3-5 short, varied example exchanges ([Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)), varied so models don't copy one template ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)).
    - Keep the hard rules (no "As an AI") in `persona.clean`, which is code ([Claude Code best practices](https://code.claude.com/docs/en/best-practices)).

### P2: later

14. **Proactive under the same harness** (`proactive.py`).
    - Briefs use the same cached prefix and the quick tier.
    - A proactive run may only *offer* actions, as cards through the same approval gate, and never act on email or Vantage text as instructions ([Willison](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)).
    - Add a daily token and cost budget beside the existing message cap.
15. **Sub-agents only for read-only fan-out.** A morning brief could read email, calendar and Vantage in parallel workers, each returning a summary of at most about 1k tokens. Only Theta's single voice writes to the user, and workers never act ([Cognition](https://cognition.com/blog/dont-build-multi-agents), [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)). Skip this until a single loop is measurably too slow.
16. **Cost and latency knobs.** Set `max_tokens` per tier, run parallel reads, keep the cheap model for classifier and summaries, and add an effort-scaling line in the tool prompt ("simple lookups: 1-3 tool calls") ([Multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system)).

## 5. Sources

- Anthropic, Building effective agents: https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, Effective context engineering for AI agents: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, Writing effective tools for agents: https://www.anthropic.com/engineering/writing-tools-for-agents
- Anthropic, How we built our multi-agent research system: https://www.anthropic.com/engineering/multi-agent-research-system
- Anthropic, Building agents with the Claude Agent SDK: https://claude.com/blog/building-agents-with-the-claude-agent-sdk
- Anthropic, Effective harnesses for long-running agents: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Anthropic, Demystifying evals for AI agents: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Anthropic, Claude Code sandboxing: https://www.anthropic.com/engineering/claude-code-sandboxing
- Anthropic, Managing context (context editing, memory tool): https://claude.com/blog/context-management
- Claude Code best practices: https://code.claude.com/docs/en/best-practices
- Anthropic prompt caching docs: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- OpenAI, A practical guide to building agents (PDF): https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- OpenAI prompt caching: https://developers.openai.com/api/docs/guides/prompt-caching
- OpenAI Codex approvals and security: https://learn.chatgpt.com/docs/agent-approvals-security
- Cognition, Don't build multi-agents: https://cognition.com/blog/dont-build-multi-agents
- Cognition, Welcoming The Interaction Company (Poke): https://cognition.com/blog/interaction
- Manus, Context engineering for AI agents: https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus
- Cursor, Dynamic context discovery: https://cursor.com/blog/dynamic-context-discovery
- Cursor, search tool docs: https://cursor.com/docs/agent/tools/search.md
- Aider, Repository map: https://aider.chat/docs/repomap.html
- SWE-agent paper (ACI): https://arxiv.org/html/2405.15793
- MemGPT paper: https://arxiv.org/abs/2310.08560
- Letta memory blocks: https://docs.letta.com/guides/agents/memory-blocks
- LangChain, Context engineering for agents: https://www.langchain.com/blog/context-engineering-for-agents
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- Drew Breunig, How long contexts fail: https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html
- Simon Willison, The lethal trifecta: https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
- DeepSeek context caching: https://api-docs.deepseek.com/guides/kv_cache
- Gemini context caching: https://aistudio.google.com/docs/caching
- RouteLLM paper: https://arxiv.org/abs/2406.18665
- OpenPoke write-up (unofficial, Poke architecture): https://composio.dev/content/open-poke
- Theta's own research on Grok Bot and Poke UX: docs/RESEARCH.md
