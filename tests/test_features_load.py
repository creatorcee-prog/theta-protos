"""Every feature in ext.FEATURES imports. A broken one is only logged at runtime (so Theta stays up), which once
let a syntax error in cards.py ship unnoticed; here it fails the suite instead."""
import os, sys, tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_DATA=tempfile.mkdtemp(), PROTOS_TZ="America/Denver")
from server import db, ext


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


db.init()
ext.reset()
loaded = {m.__name__.rsplit(".", 1)[-1] for m in ext.modules()}
check("no feature failed to load", not ext.errors(), ext.errors())
check("every listed feature is loaded", set(ext.FEATURES) <= loaded, sorted(set(ext.FEATURES) - loaded))
