"""Model providers over urllib with SSE parsing: streaming chat, usage numbers and tool calling.

    available()                                         -> ["deepseek", ...] (providers with keys)
    stream(provider, model, messages, max_tokens, usage=None) -> iterator of text chunks (raises ModelError)
    complete(provider, model, messages, max_tokens)     -> str
    call(provider, model, messages, tools, max_tokens, on_text=None, tool_choice="auto", timeout=None)
        -> {"text", "tool_calls": [{"id", "name", "args"}], "usage", "reasoning"}
    supports_tools(provider) -> bool
    cost(model, usage) -> float USD (an estimate from PRICES)

`messages` is a list of {"role": "system"|"user"|"assistant"|"tool", "content": str}:
  - a user message may carry "images": ["data:image/png;base64,...", ...] (vision tier);
  - an assistant message may carry "tool_calls": [{"id", "name", "args"}] (and "reasoning" for deepseek);
  - a "tool" message answers one call: {"role": "tool", "tool_call_id", "name", "content"}.
A leading system message becomes each provider's own system field (Anthropic's gets cache_control).

`usage` is a dict the call fills in: tokens_in (all input, cached included), tokens_out, cache_read, cache_write.

Keys come from the environment: DEEPSEEK_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, GROQ_API_KEY; local is
LOCAL_LLM_URL (+ LOCAL_LLM_MODEL, optional LOCAL_LLM_KEY).
"""

import json
import os
import socket
import urllib.error
import urllib.request
import uuid

TIMEOUT = float(os.environ.get("PROTOS_LLM_TIMEOUT", "90"))
UA = "theta-protos/0.1"

PROVIDERS = ("deepseek", "anthropic", "gemini", "groq", "local")
KEY_ENV = {"deepseek": "DEEPSEEK_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
           "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}
TOOL_PROVIDERS = ("deepseek", "groq", "anthropic", "gemini")
# other names people give the same keys on Railway: copied to the name Theta reads, once, at start
KEY_ALIASES = {"ANTHROPIC_API_KEY": ("CLAUDE_API_KEY", "ANTHROPIC_KEY", "CLAUDE_KEY"),
               "GEMINI_API_KEY": ("GOOGLE_API_KEY", "GOOGLE_GEMINI_API_KEY", "GEMINI_KEY", "GOOGLE_AI_API_KEY"),
               "GROQ_API_KEY": ("GROQ_KEY",), "DEEPSEEK_API_KEY": ("DEEPSEEK_KEY",),
               "TAVILY_API_KEY": ("TAVILY_KEY",), "GIPHY_API_KEY": ("GIPHY_KEY",)}


def _adopt_aliases():
    for main, others in KEY_ALIASES.items():
        if not (os.environ.get(main) or "").strip():
            for o in others:
                if (os.environ.get(o) or "").strip():
                    os.environ[main] = os.environ[o].strip()
                    break


_adopt_aliases()

# USD per million tokens: (input, cached input read, cache write, output). Estimates; a model not listed
# uses its provider's row. Override any row with PROTOS_PRICES='{"model": [in, read, write, out]}'.
PRICES = {
    "deepseek-chat": (0.28, 0.028, 0.28, 0.42),
    "deepseek-reasoner": (0.28, 0.028, 0.28, 0.42),
    "claude-sonnet-5-5": (3.0, 0.30, 3.75, 15.0),
    "claude-haiku-5-5": (1.0, 0.10, 1.25, 5.0),
    "gemini-3.8-flash": (0.30, 0.03, 0.30, 2.50),
    "llama-3.3-70b-versatile": (0.59, 0.59, 0.59, 0.79),
    "openai/gpt-oss-120b": (0.15, 0.15, 0.15, 0.60),
    "local": (0.0, 0.0, 0.0, 0.0),
}
_PROVIDER_PRICE = {"deepseek": "deepseek-chat", "anthropic": "claude-sonnet-5-5", "gemini": "gemini-3.8-flash",
                   "groq": "llama-3.3-70b-versatile", "local": "local"}


class ModelError(Exception):
    """A provider failed. `status` is the HTTP status when there was one;
    `retryable` is a hint that another provider may well succeed."""

    def __init__(self, message, status=None, retryable=True, provider=None):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.provider = provider


def default_model(provider):
    """The model id each provider uses when a tier doesn't name one."""
    env = os.environ.get
    return {
        "deepseek": env("DEEPSEEK_MODEL") or "deepseek-chat",
        "anthropic": env("ANTHROPIC_MODEL") or "claude-sonnet-5-5",
        "gemini": env("GEMINI_MODEL") or "gemini-3.8-flash",
        "groq": env("GROQ_MODEL") or "llama-3.3-70b-versatile",
        "local": env("LOCAL_LLM_MODEL") or "local",
    }.get(provider)


def _local_url():
    return (os.environ.get("LOCAL_LLM_URL") or "").strip().rstrip("/")


def available():
    """Providers that are configured (have a key, or a URL for local)."""
    out = [p for p in PROVIDERS if p != "local" and (os.environ.get(KEY_ENV[p]) or "").strip()]
    if _local_url():
        out.append("local")
    return out


def supports_tools(provider):
    """True for providers whose tool calling this module speaks (local servers vary, so not local)."""
    return provider in TOOL_PROVIDERS


def _price(model, provider=None):
    table = dict(PRICES)
    try:
        table.update({k: tuple(v) for k, v in json.loads(os.environ.get("PROTOS_PRICES") or "{}").items()})
    except (ValueError, TypeError, AttributeError):
        pass
    row = table.get(model)
    if row is None and provider:
        row = table.get(_PROVIDER_PRICE.get(provider))
    if row is None:
        for prefix, key in (("deepseek", "deepseek-chat"), ("claude-haiku", "claude-haiku-5-5"),
                            ("claude", "claude-sonnet-5-5"), ("gemini", "gemini-3.8-flash")):
            if (model or "").startswith(prefix):
                return table[key]
        return (0.0, 0.0, 0.0, 0.0)
    return row


def cost(model, usage, provider=None):
    """Estimated USD for one call's (or a turn's summed) usage."""
    if not usage:
        return 0.0
    p_in, p_read, p_write, p_out = _price(model, provider)
    t_in = int(usage.get("tokens_in") or 0)
    read = int(usage.get("cache_read") or 0)
    write = int(usage.get("cache_write") or 0)
    fresh = max(0, t_in - read - write)
    usd = (fresh * p_in + read * p_read + write * p_write + int(usage.get("tokens_out") or 0) * p_out) / 1e6
    return round(usd, 6)


def add_usage(total, part):
    """total += part (both usage dicts); returns total."""
    for k in ("tokens_in", "tokens_out", "cache_read", "cache_write"):
        total[k] = int(total.get(k) or 0) + int((part or {}).get(k) or 0)
    return total


def _set_usage(usage, tokens_in=None, tokens_out=None, cache_read=None, cache_write=None):
    if usage is None:
        return
    for k, v in (("tokens_in", tokens_in), ("tokens_out", tokens_out), ("cache_read", cache_read),
                 ("cache_write", cache_write)):
        if v is not None:
            usage[k] = int(v or 0)
        else:
            usage.setdefault(k, 0)


# ---- HTTP + SSE

def _post(provider, url, headers, body, timeout=None):
    data = json.dumps(body, ensure_ascii=False).encode()
    h = {"Content-Type": "application/json", "Accept": "text/event-stream", "User-Agent": UA}
    h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=timeout or TIMEOUT)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read(600).decode("utf-8", "replace")
        except Exception:
            detail = ""
        try:
            j = json.loads(detail)
            err = j.get("error") if isinstance(j, dict) else None
            if isinstance(j, list) and j and isinstance(j[0], dict):
                err = j[0].get("error")
            detail = (err.get("message") if isinstance(err, dict) else err) or detail
        except ValueError:
            pass
        retry = e.code in (408, 409, 425, 429) or e.code >= 500 or e.code in (401, 402, 403, 404)
        raise ModelError(f"{provider} HTTP {e.code}: {str(detail)[:200]}", status=e.code,
                         retryable=retry, provider=provider) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise ModelError(f"{provider} unreachable: {reason}", provider=provider) from None


def sse_events(lines):
    """Parse an SSE byte-line iterator into (event, data) pairs."""
    event, data = None, []
    for raw in lines:
        line = raw.decode("utf-8", "replace").rstrip("\r\n") if isinstance(raw, bytes) else raw.rstrip("\r\n")
        if not line:
            if data:
                yield event or "message", "\n".join(data)
            event, data = None, []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)
    if data:
        yield event or "message", "\n".join(data)


def _events(provider, resp):
    try:
        for ev, data in sse_events(resp):
            yield ev, data
    except (socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise ModelError(f"{provider} stream broke: {e}", provider=provider) from None
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _split_system(messages):
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system" and m.get("content"))
    rest = [m for m in messages if m.get("role") in ("user", "assistant", "tool")]
    return system, rest


def _data_url(u):
    """'data:image/png;base64,AAA' -> ('image/png', 'AAA')."""
    head, _, b64 = (u or "").partition(",")
    mime = head[5:].split(";")[0] if head.startswith("data:") else "image/jpeg"
    return mime or "image/jpeg", b64


def _call_id():
    return "call_" + uuid.uuid4().hex[:16]


def _args_json(args):
    return json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False, sort_keys=True)


def _parse_args(raw):
    """Tool-call arguments as a dict. Unparseable JSON becomes {"_raw": text} so the tool layer can explain."""
    if isinstance(raw, dict):
        return raw
    if not raw or not str(raw).strip():
        return {}
    try:
        v = json.loads(raw)
    except ValueError:
        return {"_raw": str(raw)[:500]}
    return v if isinstance(v, dict) else {"_raw": str(raw)[:500]}


# ---- OpenAI-compatible (deepseek, groq, local)

def _openai_endpoint(provider):
    if provider == "local":
        base = _local_url()
        if not base:
            raise ModelError("local: LOCAL_LLM_URL isn't set", retryable=True, provider=provider)
        return base + "/chat/completions", os.environ.get("LOCAL_LLM_KEY", "")
    url = {"deepseek": "https://api.deepseek.com/chat/completions",
           "groq": "https://api.groq.com/openai/v1/chat/completions"}[provider]
    key = os.environ.get(KEY_ENV[provider], "")
    if not key:
        raise ModelError(f"{provider}: {KEY_ENV[provider]} isn't set", provider=provider)
    return url, key


def _openai_messages(provider, messages):
    msgs = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            msgs.append({"role": "tool", "tool_call_id": m.get("tool_call_id") or "", "content": m.get("content") or ""})
        elif role == "assistant" and m.get("tool_calls"):
            out = {"role": "assistant", "content": m.get("content") or "",
                   "tool_calls": [{"id": c["id"], "type": "function",
                                   "function": {"name": c["name"], "arguments": _args_json(c.get("args"))}}
                                  for c in m["tool_calls"]]}
            if provider == "deepseek" and m.get("reasoning"):
                out["reasoning_content"] = m["reasoning"]  # thinking mode wants it back within the turn
            msgs.append(out)
        elif m.get("images") and role == "user":
            parts = [{"type": "text", "text": m.get("content") or ""}]
            parts += [{"type": "image_url", "image_url": {"url": u}} for u in m["images"]]
            msgs.append({"role": "user", "content": parts})
        elif role in ("system", "user", "assistant"):
            msgs.append({"role": role, "content": m.get("content") or ""})
    return msgs


def _openai_tools(tools):
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["params"]}} for t in tools]


def _openai_usage(u, usage):
    if not isinstance(u, dict):
        return
    details = u.get("prompt_tokens_details") or {}
    read = u.get("prompt_cache_hit_tokens")
    if read is None:
        read = details.get("cached_tokens") if isinstance(details, dict) else 0
    _set_usage(usage, u.get("prompt_tokens"), u.get("completion_tokens"), read or 0, 0)


def _openai_gen(provider, model, messages, max_tokens, tools=None, usage=None, tool_choice="auto", timeout=None):
    """Yields ("text", s), ("reasoning", s), finally ("tool_calls", [...]) if any."""
    url, key = _openai_endpoint(provider)
    body = {"model": model, "messages": _openai_messages(provider, messages), "stream": True,
            "max_tokens": int(max_tokens)}
    if tools:
        body["tools"] = _openai_tools(tools)
        body["tool_choice"] = "none" if tool_choice == "none" else "auto"
    if provider in ("deepseek", "groq"):
        body["stream_options"] = {"include_usage": True}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    resp = _post(provider, url, headers, body, timeout)
    calls = {}
    _set_usage(usage)
    for _ev, data in _events(provider, resp):
        if data.strip() == "[DONE]":
            break
        try:
            j = json.loads(data)
        except ValueError:
            continue
        if j.get("error"):
            err = j["error"]
            raise ModelError(f"{provider}: {err.get('message') if isinstance(err, dict) else err}", provider=provider)
        if j.get("usage"):
            _openai_usage(j["usage"], usage)
        elif isinstance(j.get("x_groq"), dict) and j["x_groq"].get("usage"):
            _openai_usage(j["x_groq"]["usage"], usage)
        for ch in j.get("choices") or []:
            delta = ch.get("delta") or {}
            # deepseek-reasoner streams its thinking as reasoning_content: never shown, kept for tool turns
            if delta.get("reasoning_content"):
                yield "reasoning", delta["reasoning_content"]
            if delta.get("content"):
                yield "text", delta["content"]
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", len(calls))
                slot = calls.setdefault(idx, {"id": None, "name": "", "args": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]
    if calls:
        yield "tool_calls", [{"id": c["id"] or _call_id(), "name": c["name"], "args": _parse_args(c["args"])}
                             for _i, c in sorted(calls.items())]


# ---- Anthropic Messages API

def _anthropic_body(model, messages, max_tokens, tools=None, tool_choice="auto"):
    system, rest = _split_system(messages)
    msgs = []
    for m in rest:
        role = "user" if m["role"] == "tool" else m["role"]
        if m["role"] == "tool":
            content = [{"type": "tool_result", "tool_use_id": m.get("tool_call_id") or "",
                        "content": m.get("content") or "(empty)"}]
        elif m["role"] == "assistant" and m.get("tool_calls"):
            content = [{"type": "text", "text": m["content"]}] if (m.get("content") or "").strip() else []
            content += [{"type": "tool_use", "id": c["id"], "name": c["name"],
                         "input": c.get("args") if isinstance(c.get("args"), dict) else {}} for c in m["tool_calls"]]
        elif m.get("images") and m["role"] == "user":
            content = []
            for u in m["images"]:
                mime, b64 = _data_url(u)
                content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
            content.append({"type": "text", "text": m.get("content") or "(image)"})
        else:
            content = [{"type": "text", "text": m.get("content") or "…"}]
        if msgs and msgs[-1]["role"] == role:  # the API wants alternating turns
            msgs[-1]["content"].extend(content)
        else:
            msgs.append({"role": role, "content": content})
    for m in msgs:  # tool_result blocks must come first in their user turn
        if m["role"] == "user" and any(b.get("type") == "tool_result" for b in m["content"]):
            m["content"].sort(key=lambda b: 0 if b.get("type") == "tool_result" else 1)
    if msgs and msgs[0]["role"] != "user":
        msgs.insert(0, {"role": "user", "content": [{"type": "text", "text": "(earlier conversation)"}]})
    body = {"model": model, "max_tokens": int(max_tokens), "messages": msgs, "stream": True}
    if tools:
        body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["params"]}
                         for t in tools]
        body["tool_choice"] = {"type": "none" if tool_choice == "none" else "auto"}
    if system:
        # tools -> system is the stable prefix; one breakpoint here caches both
        body["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    return body


def _anthropic_gen(provider, model, messages, max_tokens, tools=None, usage=None, tool_choice="auto", timeout=None):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ModelError("anthropic: ANTHROPIC_API_KEY isn't set", provider=provider)
    body = _anthropic_body(model, messages, max_tokens, tools, tool_choice)
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    resp = _post(provider, "https://api.anthropic.com/v1/messages", headers, body, timeout)
    blocks = {}
    u = {"in": 0, "read": 0, "write": 0, "out": 0}
    _set_usage(usage)

    def put_usage(x):
        if not isinstance(x, dict):
            return
        for src, dst in (("input_tokens", "in"), ("cache_read_input_tokens", "read"),
                         ("cache_creation_input_tokens", "write"), ("output_tokens", "out")):
            if x.get(src) is not None:
                u[dst] = int(x[src] or 0)
        _set_usage(usage, u["in"] + u["read"] + u["write"], u["out"], u["read"], u["write"])

    for ev, data in _events(provider, resp):
        try:
            j = json.loads(data)
        except ValueError:
            continue
        kind = j.get("type") or ev
        if kind == "message_start":
            put_usage((j.get("message") or {}).get("usage"))
        elif kind == "content_block_start":
            cb = j.get("content_block") or {}
            if cb.get("type") == "tool_use":
                blocks[j.get("index", len(blocks))] = {"id": cb.get("id") or _call_id(), "name": cb.get("name") or "",
                                                       "args": ""}
        elif kind == "content_block_delta":
            d = j.get("delta") or {}
            if d.get("type") == "text_delta" and d.get("text"):
                yield "text", d["text"]
            elif d.get("type") == "input_json_delta":
                b = blocks.get(j.get("index"))
                if b is not None:
                    b["args"] += d.get("partial_json") or ""
        elif kind == "message_delta":
            put_usage(j.get("usage"))
        elif kind == "error":
            err = j.get("error") or {}
            raise ModelError(f"anthropic: {err.get('message') or err}", provider=provider)
        elif kind == "message_stop":
            break
    if blocks:
        yield "tool_calls", [{"id": b["id"], "name": b["name"], "args": _parse_args(b["args"])}
                             for _i, b in sorted(blocks.items())]


# ---- Gemini streamGenerateContent (alt=sse)

def _gemini_body(messages, max_tokens, tools=None, tool_choice="auto"):
    system, rest = _split_system(messages)
    contents = []
    for m in rest:
        if m["role"] == "tool":
            role = "user"
            parts = [{"functionResponse": {"name": m.get("name") or "tool",
                                           "response": {"result": m.get("content") or ""}}}]
        elif m["role"] == "assistant":
            role = "model"
            has_text = bool((m.get("content") or "").strip())
            parts = [{"text": m["content"]}] if has_text else ([] if m.get("tool_calls") else [{"text": "…"}])
            for c in m.get("tool_calls") or []:
                p = {"functionCall": {"name": c["name"],
                                      "args": c.get("args") if isinstance(c.get("args"), dict) else {}}}
                if c.get("signature"):
                    p["thoughtSignature"] = c["signature"]
                parts.append(p)
        else:
            role = "user"
            parts = [{"text": m.get("content") or "…"}]
            for u in m.get("images") or []:
                mime, b64 = _data_url(u)
                parts.append({"inline_data": {"mime_type": mime, "data": b64}})
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": parts})
    body = {"contents": contents, "generationConfig": {"maxOutputTokens": int(max_tokens)}}
    if tools:
        body["tools"] = [{"functionDeclarations": [{"name": t["name"], "description": t["description"],
                                                    "parameters": t["params"]} for t in tools]}]
        body["toolConfig"] = {"functionCallingConfig": {"mode": "NONE" if tool_choice == "none" else "AUTO"}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return body


def _gemini_gen(provider, model, messages, max_tokens, tools=None, usage=None, tool_choice="auto", timeout=None):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise ModelError("gemini: GEMINI_API_KEY isn't set", provider=provider)
    body = _gemini_body(messages, max_tokens, tools, tool_choice)
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{urllib.request.quote(model, safe='-._')}:streamGenerateContent?alt=sse")
    resp = _post(provider, url, {"x-goog-api-key": key}, body, timeout)
    calls = []
    _set_usage(usage)
    for _ev, data in _events(provider, resp):
        try:
            j = json.loads(data)
        except ValueError:
            continue
        if j.get("error"):
            raise ModelError(f"gemini: {j['error'].get('message')}", provider=provider)
        um = j.get("usageMetadata")
        if isinstance(um, dict):
            _set_usage(usage, um.get("promptTokenCount"),
                       int(um.get("candidatesTokenCount") or 0) + int(um.get("thoughtsTokenCount") or 0),
                       um.get("cachedContentTokenCount") or 0, 0)
        for cand in j.get("candidates") or []:
            for part in (cand.get("content") or {}).get("parts") or []:
                if part.get("functionCall"):
                    fc = part["functionCall"]
                    calls.append({"id": fc.get("id") or _call_id(), "name": fc.get("name") or "",
                                  "args": fc.get("args") if isinstance(fc.get("args"), dict) else {},
                                  "signature": part.get("thoughtSignature")})
                    continue
                if part.get("thought"):
                    continue
                if part.get("text"):
                    yield "text", part["text"]
    if calls:
        yield "tool_calls", calls


_GENS = {"deepseek": _openai_gen, "groq": _openai_gen, "local": _openai_gen,
         "anthropic": _anthropic_gen, "gemini": _gemini_gen}


def _gen(provider):
    fn = _GENS.get(provider)
    if fn is None:
        raise ModelError(f"unknown provider {provider!r}", retryable=False, provider=provider)
    return fn


def stream(provider, model, messages, max_tokens=1024, usage=None):
    """Stream a reply as text chunks. Raises ModelError (on the first next()
    for connection/HTTP failures, later if the stream breaks). If `usage` is a
    dict it is filled with the provider's token counts by the end of the stream."""
    fn = _gen(provider)
    gen = fn(provider, model or default_model(provider), messages, max_tokens, None, usage)
    return (s for kind, s in gen if kind == "text")


def complete(provider, model, messages, max_tokens=1024):
    """The whole reply as one string."""
    return "".join(stream(provider, model, messages, max_tokens))


def call(provider, model, messages, tools=None, max_tokens=1024, on_text=None, tool_choice="auto", timeout=None):
    """One model step with tools. `tools` are dicts with name, description, params (JSON schema).
    Text is passed to on_text(chunk) as it streams. tool_choice="none" forbids new calls (the
    tools are still declared, since providers reject tool history without them).
    Returns {"text", "tool_calls": [{"id", "name", "args"(dict)}], "usage", "reasoning"}."""
    fn = _gen(provider)
    usage = {}
    text, reasoning, calls = [], [], []
    for kind, val in fn(provider, model or default_model(provider), messages, max_tokens, tools or None, usage,
                        tool_choice, timeout):
        if kind == "text":
            text.append(val)
            if on_text:
                on_text(val)
        elif kind == "reasoning":
            reasoning.append(val)
        elif kind == "tool_calls":
            calls = [c for c in val if c.get("name")]
    return {"text": "".join(text), "tool_calls": calls, "usage": usage, "reasoning": "".join(reasoning)}
