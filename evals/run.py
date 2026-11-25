"""Golden-conversation evals (docs/HARNESS.md P12): run evals/golden.jsonl through the
real app in-process (POST /api/chat?stream=0 on the WSGI app, a fresh database
per trial) and grade the final reply with code graders.

    python3 evals/run.py                      # offline: fake models, for CI (default)
    python3 evals/run.py --live --repeat 3    # real models (needs DEEPSEEK_API_KEY or another key)
    python3 evals/run.py --live --only math,greet --json out.json

A case: {"id", "turns": [user texts], "expect": {tier?, must?, must_not?, max_chars?, tools?}}
  tier       the routed tier of the final turn (route accuracy)
  must       regexes (case-insensitive) that must ALL match the final reply
  must_not   regexes that must NOT match it
  max_chars  the final reply's length limit
  tools      tool names the final turn must have called (from the turns log)
Every reply is also checked for model tells: "As an AI", filler openers,
naming the model or provider, sign-off offers, an empty reply.

Offline mode replaces models.stream / models.call / models.complete with a fake
that answers instantly. It grades routing, the length limit, the voice post-pass
and the prompt shape (a stable system prompt across turns; the time in the
latest user turn), and skips the checks only a real model can pass
(must, must_not, tools), reported as "skipped".

Reported: pass@1 (share of trials that pass), pass^k (cases where every one of k
trials passes), route accuracy, latency, tokens and cost when the app logs them.
"""

import argparse
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden.jsonl")

GLOBAL_MUST_NOT = [
    ("as an ai", r"\bas an ai\b|\bas a (large )?language model\b|\bI(?:'m| am) (?:just )?an ai\b"),
    ("filler opener", r"^\s*(certainly|absolutely|of course|great question|good question|sure thing)\b"),
    ("names the model", r"\b(deepseek|openai|chatgpt|gpt-?\d|anthropic|claude|gemini|llama|groq|mistral)\b"),
    ("sign-off offer", r"let me know if (you (have|need)|there'?s)|i hope (this|that) helps|feel free to ask"),
    ("leaks the context block", r"context for this turn"),
    ("raw tool-call text", r"</?tool_call>|\{\s*\"name\"\s*:\s*\"\w+\"\s*,\s*\"arguments\""),
]
DEFAULT_MAX = 2500
PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "LOCAL_LLM_URL", "DEEPSEEK_API_KEY")


def load(path=GOLDEN, only=None):
    cases = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            c = json.loads(line)
            if not c.get("id") or not isinstance(c.get("turns"), list) or not c["turns"]:
                raise ValueError(f"{path}:{n}: a case needs an id and a non-empty turns list")
            c.setdefault("expect", {})
            cases.append(c)
    if only:
        want = set(only)
        cases = [c for c in cases if c["id"] in want]
    return cases


# ---- the app, in-process

class Harness:
    """Imports the server with a temp data dir and, offline, fake models."""

    def __init__(self, live=False, keep_keys=False):
        self.live = live
        self.tmp = tempfile.mkdtemp(prefix="protos-evals-")
        os.environ["PROTOS_DATA"] = self.tmp
        os.environ["PROTOS_TICK"] = "0"
        os.environ["PROTOS_QUIET"] = "1"
        os.environ.pop("PROTOS_KEY", None)
        os.environ.pop("PROTOS_LOCAL_FIRST", None)
        if not live:
            for k in PROVIDER_KEYS + ("TAVILY_API_KEY",):
                os.environ.pop(k, None)
            os.environ["DEEPSEEK_API_KEY"] = "sk-offline"
            os.environ["ANTHROPIC_API_KEY"] = "sk-offline"
        elif not keep_keys:
            for k in PROVIDER_KEYS:
                if k != "DEEPSEEK_API_KEY":
                    os.environ.pop(k, None)
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from server import app as appmod, db, models, persona, router
        self.app, self.db, self.models, self.persona, self.router = appmod, db, models, persona, router
        self.prompts = []  # the messages each fake model call saw (offline)
        if not live:
            router.CLASSIFIER = None
            self._fake()
        if not models.available():
            raise SystemExit("no model provider is configured (set DEEPSEEK_API_KEY for --live)")
        self.n = 0

    def _fake(self):
        models, persona, prompts = self.models, self.persona, self.prompts

        def reply_for(messages):
            prompts.append(messages)
            n = sum(1 for m in messages if m.get("role") == "user")
            # "Certainly!" checks the voice post-pass; never echoes the user (graders would see their words)
            return ["Certainly! ", "Here's the short answer ", f"(turn {n})."]

        def fake_stream(provider, model, messages, max_tokens=1024, usage=None, **kw):
            chunks = reply_for(messages)
            if isinstance(usage, dict):
                usage.update({"tokens_in": sum(len(str(m.get("content"))) for m in messages) // 4,
                              "tokens_out": 12, "cache_read": 0, "cache_write": 0})

            def gen():
                yield from chunks
            return gen()

        def fake_call(provider, model, messages, tools=None, max_tokens=1024, on_text=None, **kw):
            text = "".join(reply_for(messages))
            if callable(on_text):
                on_text(text)
            return {"text": text, "tool_calls": [], "usage": {"tokens_in": 100, "tokens_out": 12,
                                                               "cache_read": 0, "cache_write": 0}}

        def fake_complete(provider, model, messages, max_tokens=1024, **kw):
            return "".join(reply_for(messages))

        models.stream = fake_stream
        models.complete = fake_complete
        if hasattr(models, "call"):
            models.call = fake_call

    def fresh(self):
        self.n += 1
        self.db.init(os.path.join(self.tmp, f"trial-{self.n}.db"))
        del self.prompts[:]

    def chat(self, text):
        body = json.dumps({"bot": "theta", "text": text}).encode()
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/chat", "QUERY_STRING": "stream=0",
               "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/json",
               "wsgi.input": io.BytesIO(body), "wsgi.url_scheme": "http", "SERVER_NAME": "evals",
               "SERVER_PORT": "0"}
        got = {}

        def start(status, headers, exc_info=None):
            got["status"] = status
        t0 = time.monotonic()
        raw = b"".join(self.app.app(env, start))
        ms = int((time.monotonic() - t0) * 1000)
        try:
            j = json.loads(raw)
        except ValueError:
            j = {"error": raw[:200].decode("utf-8", "replace")}
        turn = (self.db.turns(1) or [{}])[0]
        return j, turn, ms

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---- grading

def grade(case, reply, turn, live, prompts=None):
    """[(check, ok | None for skipped, detail)] for one trial's final turn."""
    exp = case.get("expect") or {}
    text = (reply or {}).get("text") or ""
    meta = (reply or {}).get("meta") or {}
    out = [("replied", bool(text.strip()), "" if text.strip() else "no reply")]
    if "tier" in exp:
        got = meta.get("tier") or turn.get("tier")
        out.append(("tier", got == exp["tier"], f"want {exp['tier']}, got {got} ({turn.get('why')})"))
    limit = int(exp.get("max_chars") or DEFAULT_MAX)
    out.append(("max_chars", len(text) <= limit, f"{len(text)} > {limit}"))
    for name, rx in GLOBAL_MUST_NOT:
        m = re.search(rx, text, re.I | re.M)
        out.append((f"voice: {name}", m is None, f"matched {m.group(0)!r}" if m else ""))
    for rx in exp.get("must") or []:
        ok = re.search(rx, text, re.I | re.M) is not None if live else None
        out.append((f"must /{rx}/", ok, "not found"))
    for rx in exp.get("must_not") or []:
        m = re.search(rx, text, re.I | re.M) if live else None
        out.append((f"must_not /{rx}/", (m is None) if live else None, f"matched {m.group(0)!r}" if m else ""))
    if exp.get("tools"):
        called = list(turn.get("tools") or [])
        ok = all(t in called for t in exp["tools"]) if live else None
        out.append((f"tools {exp['tools']}", ok, f"called {called}"))
    if prompts:  # offline: the shape of what the model was sent
        systems = [next((m["content"] for m in p if m.get("role") == "system"), None) for p in prompts]
        chat_prompts = [p for p in prompts if any(m.get("role") == "system" for m in p)]
        last_user = [next((m for m in reversed(p) if m.get("role") == "user"), {}) for p in chat_prompts]
        head = getattr(_persona(), "CONTEXT_HEAD", "Context for this turn")
        out.append(("prompt: context on the latest turn",
                    bool(last_user) and all(head in (u.get("content") or "") for u in last_user), ""))
        firsts = [s for s in systems if s]
        out.append(("prompt: stable system prompt", len(set(firsts)) <= 1, f"{len(set(firsts))} variants"))
    return out


def _persona():
    from server import persona
    return persona


def run(cases, repeat=1, live=False, keep_keys=False, log=print):
    h = Harness(live=live, keep_keys=keep_keys)
    results = []
    try:
        for case in cases:
            trials = []
            for k in range(repeat):
                h.fresh()
                reply, turn, ms, err = None, {}, 0, None
                total_ms = 0
                tokens = {"tokens_in": 0, "tokens_out": 0, "cache_read": 0, "cost_usd": 0.0}
                for text in case["turns"]:
                    j, turn, ms = h.chat(text)
                    total_ms += ms
                    for key in tokens:
                        v = turn.get(key)
                        if isinstance(v, (int, float)):
                            tokens[key] += v
                    reply = j.get("reply")
                    if not reply:
                        err = j.get("error") or "no reply"
                        break
                checks = grade(case, reply, turn, live, None if live else list(h.prompts))
                if err:
                    checks.insert(0, ("app answered", False, str(err)[:200]))
                ok = all(c[1] is not False for c in checks)
                trials.append({"ok": ok, "checks": checks, "text": (reply or {}).get("text", ""),
                               "tier": ((reply or {}).get("meta") or {}).get("tier") or turn.get("tier"),
                               "model": turn.get("model"), "ms": total_ms, **tokens})
                mark = "ok  " if ok else "FAIL"
                why = "; ".join(f"{c[0]}: {c[2]}" for c in checks if c[1] is False)
                log(f"  {mark} {case['id']} #{k + 1} [{trials[-1]['tier']}/{trials[-1]['model']}] "
                    f"{total_ms} ms{(' - ' + why) if why else ''}")
            results.append({"id": case["id"], "expect": case.get("expect"), "trials": trials})
    finally:
        h.close()
    return results


def summarize(results, repeat):
    n_trials = sum(len(r["trials"]) for r in results)
    passed = sum(t["ok"] for r in results for t in r["trials"])
    all_k = sum(all(t["ok"] for t in r["trials"]) for r in results)
    tier_cases = [(r, t) for r in results if "tier" in (r["expect"] or {}) for t in r["trials"]]
    tier_ok = sum(t["tier"] == r["expect"]["tier"] for r, t in tier_cases)
    skipped = sum(c[1] is None for r in results for t in r["trials"] for c in t["checks"])
    ms = sorted(t["ms"] for r in results for t in r["trials"]) or [0]
    return {
        "cases": len(results), "trials": n_trials, "repeat": repeat,
        "pass_at_1": passed / n_trials if n_trials else 0.0,
        "pass_hat_k": all_k / len(results) if results else 0.0,
        "route_accuracy": tier_ok / len(tier_cases) if tier_cases else 1.0,
        "skipped_checks": skipped,
        "p50_ms": ms[len(ms) // 2], "max_ms": ms[-1],
        "tokens_in": sum(t["tokens_in"] for r in results for t in r["trials"]),
        "tokens_out": sum(t["tokens_out"] for r in results for t in r["trials"]),
        "cache_read": sum(t["cache_read"] for r in results for t in r["trials"]),
        "cost_usd": round(sum(t["cost_usd"] for r in results for t in r["trials"]), 6),
        "failed": [r["id"] for r in results if not all(t["ok"] for t in r["trials"])],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--live", action="store_true", help="use real models (default: offline fakes)")
    ap.add_argument("--repeat", type=int, default=3, help="trials per case (pass^k uses all of them)")
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--golden", default=GOLDEN)
    ap.add_argument("--keep-keys", action="store_true", help="live: keep every provider key (default: DeepSeek only)")
    ap.add_argument("--json", default="", help="write full results to this file")
    ap.add_argument("--min-pass", type=float, default=0.0, help="exit 1 if pass^k is below this (0..1)")
    a = ap.parse_args(argv)
    cases = load(a.golden, [x for x in a.only.split(",") if x])
    mode = "live" if a.live else "offline"
    print(f"evals: {len(cases)} cases x {a.repeat} ({mode})")
    results = run(cases, repeat=max(1, a.repeat), live=a.live, keep_keys=a.keep_keys)
    s = summarize(results, a.repeat)
    print(f"\npass@1 {s['pass_at_1']:.0%}   pass^{a.repeat} {s['pass_hat_k']:.0%} ({s['cases'] - len(s['failed'])}"
          f"/{s['cases']} cases)   route accuracy {s['route_accuracy']:.0%}   p50 {s['p50_ms']} ms   "
          f"max {s['max_ms']} ms")
    if s["tokens_in"] or s["cost_usd"]:
        print(f"tokens in {s['tokens_in']}, cached {s['cache_read']}, out {s['tokens_out']}, ${s['cost_usd']:.4f}")
    if s["skipped_checks"]:
        print(f"{s['skipped_checks']} model-only checks skipped (offline)")
    if s["failed"]:
        print("failed: " + ", ".join(s["failed"]))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"summary": s, "results": results}, f, indent=1, ensure_ascii=False)
    return 1 if s["pass_hat_k"] < a.min_pass else 0


if __name__ == "__main__":
    sys.exit(main())
