"""The ASGI entry point: `uvicorn server.asgi:asgi_app --host 0.0.0.0 --port $PORT` (what `python -m server` runs
when uvicorn is installed).

Every HTTP route, the SSE chat stream and auth stay exactly as they are: the WSGI app (server/app.py) is mounted
whole through a2wsgi, on a thread pool, so its blocking code never stalls the event loop. The one thing ASGI adds
is a WebSocket: /api/calls/stream/{call_id}, where Telnyx streams a live call's audio both ways and
server/livecall.py bridges it to the Gemini Live API (full duplex, so the other person can talk over Theta).
"""
import contextlib

from a2wsgi import WSGIMiddleware
from starlette.applications import Starlette
from starlette.routing import Mount, WebSocketRoute

from . import app as wsgi
from . import livecall

# Each open chat stream (SSE) and each turn holds a worker thread for as long as it runs (up to a few minutes), so
# the pool is far bigger than a2wsgi's default of 10; the stdlib server had a thread per request.
WORKERS = 64


@contextlib.asynccontextmanager
async def _lifespan(_app):
    wsgi.startup()  # the same checks and background ticker as the stdlib server (refuses to start without a key)
    livecall.ASGI = True
    try:
        yield
    finally:
        livecall.ASGI = False
        import sys
        if "server.browser" in sys.modules:
            sys.modules["server.browser"].shutdown()


asgi_app = Starlette(
    routes=[
        WebSocketRoute("/api/calls/stream/{call_id}", livecall.ws_endpoint),
        Mount("/", app=WSGIMiddleware(wsgi.app, workers=WORKERS)),
    ],
    lifespan=_lifespan,
)
