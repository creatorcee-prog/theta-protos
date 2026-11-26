"""Settings > General > Models (server/modelcheck.py): what each tier uses, a one-word check of every model, plain
reasons when one fails, and a model name the key can't use being replaced by a working one (no network)."""
import os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "LOCAL_LLM_URL", "TAVILY_API_KEY", "GEMINI_MODEL", "DEEPSEEK_MODEL"):
    os.environ.pop(k, None)
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_QUIET="1", DEEPSEEK_API_KEY="sk-test", GEMINI_API_KEY="g-test")
from server import db, modelcheck, models, router


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
SEEN = []
LIVE = {("deepseek", "deepseek-chat"), ("deepseek", "deepseek-reasoner"), ("gemini", "gemini-2.5-flash")}


def fake_complete(provider, model, messages, max_tokens=1024):
    SEEN.append((provider, model, max_tokens))
    if (provider, model) in LIVE:
        return "OK"
    if provider == "gemini":
        raise models.ModelError("gemini HTTP 404: models/%s is not found for API version v1beta" % model)
    raise models.ModelError("HTTP 401: invalid api key sk-abcdefghijklmnop")


models.complete = fake_complete
modelcheck.listed = lambda p: ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro",
                               "text-embedding-004"] if p == "gemini" else []

st = modelcheck.status()
check("status lists which providers have keys", {p["id"]: p["key"] for p in st["providers"]}["gemini"] is True
      and {p["id"]: p["key"] for p in st["providers"]}["anthropic"] is False)
check("and what each tier uses, best first", st["tiers"][0]["tier"] == "quick" and st["tiers"][0]["models"][0] == {"provider": "deepseek", "model": "deepseek-chat"})
r = modelcheck.check()
rows = {(x["provider"], x["model"]): x for x in r["results"]}
check("every model gets a one-word test, with room for reasoning models to think", all(m >= 300 for _p, _m, m in SEEN))
check("a working model shows as answered", rows[("deepseek", "deepseek-chat")]["ok"] and rows[("deepseek", "deepseek-reasoner")]["ok"])
g = rows[("gemini", models.default_model("gemini"))]
check("a model name the key can't use is replaced by the closest working one of the same family",
      g["ok"] and g["fixed"] == "gemini-2.5-flash" and "now uses gemini-2.5-flash" in g["note"], g)
check("and Theta uses the replacement from then on", ("gemini", "gemini-2.5-flash") in router.candidates("vision"), router.candidates("vision"))
check("suggestions skip lite, embedding and preview models", modelcheck.suggest("gemini", "gemini-9-flash",
      ["gemini-3.0-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite", "text-embedding-004"]) == "gemini-2.5-flash")
check("a refused key is said plainly, and the key never shows", "key was refused" in modelcheck._short("HTTP 401: invalid api key sk-abcdefghijklmnop")
      and "abcdefgh" not in modelcheck._short("HTTP 401: invalid api key sk-abcdefghijklmnop"))
check("so is a quota problem", "quota" in modelcheck._short("HTTP 429: You exceeded your current quota"))
print("all modelcheck checks passed")
