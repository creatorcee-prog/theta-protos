"""Settings > Connections: the built connections come first with a category, the not-yet-built apps follow as
"soon", nothing shows twice, and every app with a known brand has a logo in web/logos.js."""
import json, os, re, sys, tempfile
sys.dont_write_bytecode = True
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_TZ="America/Denver")
for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
    os.environ.pop(k, None)
from server import app, catalog, db


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
conns = app.connections()
ids = [c["id"] for c in conns]
check("no app is listed twice", len(ids) == len(set(ids)), ids)
built = [c for c in conns if not c.get("soon")]
soon = [c for c in conns if c.get("soon")]
check("built connections come before the soon ones", ids.index(soon[0]["id"]) > max(ids.index(c["id"]) for c in built))
check("every app has a category", all(c.get("cat") for c in conns), [c["id"] for c in conns if not c.get("cat")])
check("soon apps are never shown as connected", all(c["connected"] is False for c in soon))
check("there are placeholder apps to show", len(soon) >= 20, len(soon))
g = {c["id"]: c for c in conns}["gmail"]
check("Gmail's line says what it does, not server setup steps", "GOOGLE_CLIENT_ID" not in g["what"] and "GOOGLE_CLIENT_ID" in g.get("note", ""), g)
check("an app a feature builds drops out of the soon list",
      [c["id"] for c in catalog.merge([{"id": "slack", "name": "Slack", "connected": True}]) if c["id"] == "slack"] == ["slack"])

logos = json.loads(re.search(r"window\.ThetaLogos = (\{.*\});", open(os.path.join(ROOT, "web", "logos.js")).read()).group(1))
no_logo = [c["id"] for c in soon if c["id"] not in logos]
check("every soon app has a logo", not no_logo, no_logo)
check("logos are a hex color and an SVG path", all(re.fullmatch(r"[0-9A-F]{6}", h) and p[:1] in "Mm" for h, p in logos.values()))
