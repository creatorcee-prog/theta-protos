"""The golden evals run offline (fake models) through the real app: every case
passes, routing is 100% on the golden set, and the prompt shape holds.
Run: python3 tests/test_evals_offline.py"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evals"))

import run as evals  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {detail}")
        FAILED.append(name)


def main():
    cases = evals.load()
    check("golden set loads (~25 cases)", 20 <= len(cases) <= 60, len(cases))
    check("case ids unique", len({c["id"] for c in cases}) == len(cases))
    check("every case has a tier", all("tier" in c["expect"] for c in cases))
    results = evals.run(cases, repeat=2, live=False, log=lambda *a: None)
    s = evals.summarize(results, 2)
    for r in results:
        bad = [f"{c[0]}: {c[2]}" for t in r["trials"] for c in t["checks"] if c[1] is False]
        check(f"case {r['id']}", not bad, bad[:3])
    check("route accuracy 100%", s["route_accuracy"] == 1.0, s)
    check("pass^2 100% offline", s["pass_hat_k"] == 1.0, s["failed"])
    check("model-only checks are skipped offline, not passed", s["skipped_checks"] > 0)
    # the grader catches what it should
    case = {"id": "x", "turns": ["hi"], "expect": {"tier": "quick", "must": ["paris"], "max_chars": 20}}
    reply = {"text": "As an AI language model, I think it's Paris. Let me know if you have questions!",
             "meta": {"tier": "think"}}
    bad = {c[0] for c in evals.grade(case, reply, {}, live=True) if c[1] is False}
    check("grader flags tier, length and voice", {"tier", "max_chars", "voice: as an ai", "voice: sign-off offer"} <= bad
          and "must /paris/" not in bad, bad)
    check("grader flags naming the model", "voice: names the model" in
          {c[0] for c in evals.grade(case, {"text": "I run on DeepSeek.", "meta": {}}, {}, live=True) if c[1] is False})
    t = {"tools": ["web_search"]}
    check("grader checks tools from the turn log",
          [c[1] for c in evals.grade({"expect": {"tools": ["remind_me"]}}, {"text": "ok"}, t, live=True)
           if c[0].startswith("tools")] == [False])

    if FAILED:
        print(f"\n{len(FAILED)} failed: {', '.join(FAILED)}")
        sys.exit(1)
    print("\nall offline eval checks passed")


if __name__ == "__main__":
    main()
