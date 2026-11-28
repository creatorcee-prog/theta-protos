"""The opening, ready before anyone answers. A live call to someone used to start in silence: only once they picked
up did Theta connect to Gemini, ask for the opening and wait for it to be spoken (about 8 seconds on a real call).
The phone rings for longer than that, so when Theta places a call it now connects to Gemini and has the opening
spoken right away, keeping the audio; when the call is answered and Telnyx's stream connects, server/livecall.py
adopts this session and plays the opening at once. The opening still goes through the same transcript check (the
AI disclosure word for word) before anything the caller says reaches Gemini.

    start(call)   from server/calls.py when Theta dials a call that will go live (runs on the server's event loop)
    take(cid)     the Warm for a call, once (or None); livecall adopts its session and queue
    close(w)      end its Gemini session

A session nobody adopts within TTL seconds (no answer, voicemail, a turn-by-turn call) is closed.
"""
import asyncio
import time

LOOP = None   # the ASGI server's event loop (server/asgi.py sets it): calls are dialed from worker threads
TTL = 75
_warm = {}


class Warm:
    def __init__(self, cid):
        self.cid, self.t0 = cid, time.time()
        self.q = asyncio.Queue()        # Gemini's messages for the opening, then None
        self.cm = self.session = None
        self.failed = False
        self.adopted = False
        self.ready_ms = None            # when the opening's first audio was ready, after dialing


async def _life(w, call):
    from .livecall import _instruction, connect
    from .livevoice import voice
    try:
        w.cm = connect(_instruction(call), voice())
        w.session = await w.cm.__aenter__()
        await w.session.send_client_content(turns={"role": "user", "parts": [{"text": (
            "[From the app, not the caller] The call is connecting now. Say your opening, exactly as written.")}]},
            turn_complete=True)
        async for m in w.session.receive():
            sc = m.server_content
            if w.ready_ms is None and sc and sc.model_turn:
                w.ready_ms = int((time.time() - w.t0) * 1000)
            await w.q.put(m)
            if sc and sc.turn_complete:
                break
    except Exception:  # noqa: BLE001  the call simply connects the usual way
        w.failed = True
    finally:
        await w.q.put(None)
    end = w.t0 + TTL
    while not w.adopted and time.time() < end:
        await asyncio.sleep(1)
    if not w.adopted:
        _warm.pop(w.cid, None)
        await close(w)


def start(call):
    """Begin the opening for a call Theta is dialing (no-op unless live calls are on and the server runs ASGI)."""
    from . import livecall
    if LOOP is None or not livecall.ready() or call["id"] in _warm:
        return None
    w = Warm(call["id"])
    _warm[call["id"]] = w
    asyncio.run_coroutine_threadsafe(_life(w, call), LOOP)
    return w


def take(cid):
    w = _warm.pop(cid, None)
    if w is not None:
        w.adopted = True
    return w


async def close(w):
    cm, w.cm, w.session = w.cm, None, None
    if cm is not None:
        try:
            await cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
