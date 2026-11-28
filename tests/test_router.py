"""Routing decisions and fallback (no network). Run: python3 tests/test_router.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import models, router  # noqa: E402

FAILED = []

KEYS = ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "LOCAL_LLM_URL",
        "PROTOS_LOCAL_FIRST", "ANTHROPIC_MODEL")


def env(**kw):
    for k in KEYS:
        os.environ.pop(k, None)
    for k, v in kw.items():
        os.environ[k] = v


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {detail}")
        FAILED.append(name)


def tier(text, history=(), attachments=()):
    return router.pick(text, history, attachments).tier


def main():
    router.CLASSIFIER = None  # never call a model from tests
    env(DEEPSEEK_API_KEY="x", ANTHROPIC_API_KEY="y", GEMINI_API_KEY="z", GROQ_API_KEY="w")
    check("available lists keyed providers", models.available() == ["deepseek", "anthropic", "gemini", "groq"],
          models.available())

    cases = [
        ("hey", "quick"), ("thanks!", "quick"), ("how are you today?", "quick"),
        ("what's the capital of France", "quick"),
        ("why do cats purr when they're anxious and should I worry about it", "think"),
        ("compare a Roth IRA vs a traditional one for me", "think"),
        ("what is 17 * 23 + 4", "think"),
        ("Traceback (most recent call last):\n  File \"x.py\", line 3\nKeyError: 'a'", "code"),
        ("my python script throws a TypeError when I call it", "code"),
        ("```js\nconst x = 1\n```", "code"),
        ("what's the bitcoin price right now", "search"),
        ("latest news on the storm", "search"),
        ("weather tomorrow?", "search"),
        ("what day is it today?", "quick"), ("what time is it", "quick"),  # the time is in the turn context
        ("ugh, today was rough. my boss yelled at me", "quick"), ("is the gym open today", "search"),
    ]
    for text, want in cases:
        got = tier(text)
        check(f"tier {want}: {text[:30]!r}", got == want, f"got {got}")

    r = router.pick("look", (), [{"type": "image", "data": "data:image/png;base64,AAA"}])
    check("vision tier for an image", r.tier == "vision" and r.provider == "gemini", r)

    r = router.pick("hi")
    check("quick defaults to deepseek-chat", (r.provider, r.model) == ("deepseek", "deepseek-chat"), r)
    r = router.pick("why is the sky blue and should i care")
    check("think defaults to deepseek-reasoner", (r.provider, r.model) == ("deepseek", "deepseek-reasoner"), r)
    r = router.pick("fix this TypeError in my function")
    check("code prefers claude", r.provider == "anthropic" and r.model == "claude-sonnet-5-5", r)
    os.environ["ANTHROPIC_MODEL"] = "claude-test-1"
    check("ANTHROPIC_MODEL overrides", router.pick("fix this TypeError").model == "claude-test-1")

    hist = [{"role": "user", "text": "fix my python bug"}, {"role": "assistant", "text": "...",
                                                             "meta": {"tier": "code"}}]
    check("short follow-up keeps code tier", tier("still broken after that", hist) == "code")

    # fallback when the tier's providers have no key
    env(GROQ_API_KEY="w")
    r = router.pick("why should i compare these two plans")
    check("think falls back to groq", r.tier == "think" and r.provider == "groq", r)
    env(GEMINI_API_KEY="z")
    r = router.pick("fix this TypeError")
    check("code falls back within tier list", r.provider == "gemini", r)
    env(DEEPSEEK_API_KEY="x")
    r = router.pick("look", (), [{"type": "image", "data": "data:image/png;base64,AAA"}])
    check("vision without a vision model falls back to quick", r.tier == "quick" and r.provider == "deepseek", r)
    env(DEEPSEEK_API_KEY="x", ANTHROPIC_API_KEY="y")
    r = router.pick("why should I compare these")
    check("candidates end with quick", r.candidates[0] == ("deepseek", "deepseek-reasoner")
          and ("anthropic", "claude-sonnet-5-5") in r.candidates and ("deepseek", "deepseek-chat") in r.candidates,
          r.candidates)

    env()
    try:
        router.pick("hi")
        check("no providers raises ModelError", False)
    except models.ModelError:
        check("no providers raises ModelError", True)

    # local first
    env(DEEPSEEK_API_KEY="x", LOCAL_LLM_URL="http://127.0.0.1:1/v1", PROTOS_LOCAL_FIRST="1")
    check("PROTOS_LOCAL_FIRST prefers local", router.pick("hi").provider == "local")
    check("local first, then the tier", router.pick("why should I").candidates[1][0] == "deepseek")
    env(DEEPSEEK_API_KEY="x", LOCAL_LLM_URL="http://127.0.0.1:1/v1")
    check("private things go local", router.pick("what's my bank account routing number again").tier == "local")
    check("without local-first, quick stays deepseek", router.pick("hi").provider == "deepseek")

    # classifier only for ambiguous messages, and injectable
    env(DEEPSEEK_API_KEY="x")
    calls = []
    router.CLASSIFIER = lambda t: calls.append(t) or "think"
    tier("hello")
    tier("my python code crashes")
    check("classifier not called for clear cases", calls == [], calls)
    amb = ("I've been going back and forth about the cabin trip with the crew and honestly I'm not sure "
           "what to tell them about the dates")
    got = tier(amb)
    check("classifier decides ambiguous medium messages", got == "think" and len(calls) == 1, (got, calls))
    router.CLASSIFIER = lambda t: (_ for _ in ()).throw(RuntimeError("boom"))
    check("classifier failure falls back to heuristic", tier(amb) == "quick")
    router.CLASSIFIER = None

    # stickiness: the previous route's model stays while the tier is close enough
    env(DEEPSEEK_API_KEY="x", ANTHROPIC_API_KEY="y")
    now = 1_800_000_000
    think = router.pick("why should I compare these two plans", now=now)
    check("Route records when it was picked", think.t == now)
    amb = ("I've been going back and forth about the cabin trip with the crew and honestly I'm not sure "
           "what to tell them about the dates")
    check("weak quick after think stays think (sticky)",
          router.pick(amb, last=think, now=now + 60).tier == "think" and "sticky" in router.pick(amb, last=think, now=now + 60).why)
    check("sticky expires after 10 minutes", router.pick(amb, last=think, now=now + 601).tier == "quick")
    check("a greeting is a real change: back to quick", router.pick("thanks!", last=think, now=now + 60).tier == "quick")
    check("code after think switches", router.pick("my python script throws a TypeError", last=think,
                                                   now=now + 60).tier == "code")
    check("search after quick switches tier", router.pick("latest news on the storm", last=router.pick("hi", now=now),
                                                          now=now + 30).tier == "search")
    # same tier, the last turn used a fallback model: keep it so its cache stays warm
    prev = {"role": "assistant", "text": "x", "t": now, "meta": {"tier": "think", "provider": "anthropic",
                                                                "model": "claude-sonnet-5-5"}}
    r = router.pick("why is that better, explain how it works", last=prev, now=now + 120)
    check("same tier reuses the last model (Message as last)", (r.provider, r.model) == ("anthropic", "claude-sonnet-5-5")
          and r.candidates[1] == ("deepseek", "deepseek-reasoner") and "sticky model" in r.why, r)
    r = router.pick("why is that better, explain how it works", last=prev, now=now + 900)
    check("old last route is ignored", r.provider == "deepseek", r)
    hist = [{"role": "user", "text": "q"}, prev, {"role": "assistant", "text": "On it.", "meta": {"ack": True}}]
    check("last_route finds the newest routed reply", router.last_route(hist)["provider"] == "anthropic"
          and router.last_route([prev, {"role": "assistant", "text": "x", "meta": {}}]) is None)
    env(DEEPSEEK_API_KEY="x")
    r = router.pick("why is that better, explain how it works", last=prev, now=now + 120)
    check("sticky model without a key is skipped", r.provider == "deepseek", r)
    check("vision is never sticky-blocked", router.pick("look", (), [{"type": "image", "data": "data:image/png;base64,A"}],
                                                        last=think, now=now + 5).tier != "think")

    # search context without a key: Theta's browser searches instead (faked here); with neither, it says so
    os.environ.pop("TAVILY_API_KEY", None)
    from server import browser
    real_results, real_avail = browser.web_results, browser.available
    browser.web_results = lambda q, n=5: [{"title": "BTC price today", "url": "https://coins.example/btc",
                                            "snippet": "Bitcoin is $91,000."}]
    block, sources = router.search_context("bitcoin price")
    check("without Tavily, a search in Theta's browser gives numbered results",
          "[1] BTC price today (https://coins.example/btc)" in block and sources == [
              {"title": "BTC price today", "url": "https://coins.example/btc"}], block)
    browser.web_results = lambda q, n=5: []
    block, sources = router.search_context("bitcoin price")
    check("search with neither says it can't check live", "couldn't check live" in block and sources == [])
    browser.web_results = real_results
    os.environ["THETA_BROWSER"] = "0"
    check("search_live: no key and no browser means no live search", router.search_live() is False)
    os.environ.pop("THETA_BROWSER")

    # Tavily call shape (urlopen faked)
    import io
    import json
    import urllib.request
    seen = {}

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        return R(json.dumps({"results": [{"title": "BTC", "url": "https://ex.com/btc", "content": "BTC is $1"}]})
                 .encode())
    real = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    os.environ["TAVILY_API_KEY"] = "tvly-test"
    try:
        block, sources = router.search_context("bitcoin price")
    finally:
        urllib.request.urlopen = real
        os.environ.pop("TAVILY_API_KEY", None)
    check("Tavily results go into context with URLs",
          seen.get("url") == "https://api.tavily.com/search" and "https://ex.com/btc" in block
          and sources == [{"title": "BTC", "url": "https://ex.com/btc"}], (seen, sources))

    # SSE parser
    lines = [b"event: x\n", b"data: {\"a\":1}\n", b"\n", b": comment\n", b"data: [DONE]\n", b"\n"]
    check("sse parser", list(models.sse_events(lines)) == [("x", '{"a":1}'), ("message", "[DONE]")])

    # deepseek-reasoner: reasoning_content skipped
    class Resp:
        def __init__(self, ls):
            self.ls = ls

        def __iter__(self):
            return iter(self.ls)

        def close(self):
            pass
    frames = [b'data: {"choices":[{"delta":{"reasoning_content":"hmm"}}]}\n', b"\n",
              b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n', b"\n",
              b'data: {"choices":[{"delta":{"content":" there"}}]}\n', b"\n", b"data: [DONE]\n", b"\n"]
    real_post = models._post
    models._post = lambda *a, **k: Resp(frames)
    try:
        out = list(models.stream("deepseek", "deepseek-reasoner", [{"role": "user", "content": "x"}], 10))
    finally:
        models._post = real_post
    check("reasoner streams content only", out == ["Hi", " there"], out)

    frames = [b"event: content_block_delta\n", b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Yo"}}\n',
              b"\n", b'data: {"type":"message_stop"}\n', b"\n"]
    models._post = lambda *a, **k: Resp(frames)
    os.environ["ANTHROPIC_API_KEY"] = "k"
    try:
        out = list(models.stream("anthropic", "m", [{"role": "system", "content": "s"},
                                                    {"role": "user", "content": "x"}], 10))
    finally:
        models._post = real_post
    check("anthropic stream parsing", out == ["Yo"], out)

    frames = [b'data: {"candidates":[{"content":{"parts":[{"text":"think","thought":true},{"text":"Hey"}]}}]}\n', b"\n"]
    models._post = lambda *a, **k: Resp(frames)
    os.environ["GEMINI_API_KEY"] = "k"
    try:
        out = list(models.stream("gemini", "gemini-x", [{"role": "user", "content": "x"}], 10))
    finally:
        models._post = real_post
    check("gemini stream parsing skips thoughts", out == ["Hey"], out)

    if FAILED:
        print(f"\n{len(FAILED)} failed: {', '.join(FAILED)}")
        sys.exit(1)
    router.CLASSIFIER = None
check("shopping for the best price is live facts (search), not short chat",
      router.decide("Find the best price on a pair of Sony WH-1000XM5 headphones.")[0] == "search")
check("a reminder that says 'tonight' isn't a live-facts question",
      router.decide("Remind me to call mom at 7pm tonight.")[0] != "search")
print("\nall router checks passed")


if __name__ == "__main__":
    main()
