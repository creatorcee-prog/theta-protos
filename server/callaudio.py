"""Phone audio for live calls (server/livecall.py), standard library only: 16-bit PCM byte order (detected from
speech), 24 kHz -> 16 kHz resampling, and in-band keypad (DTMF) tones."""
import array
import math
import re
import sys

def _samples(raw, order):
    a = array.array("h")
    a.frombytes(raw[: len(raw) // 2 * 2])
    if (order == "big") == (sys.byteorder == "little"):
        a.byteswap()
    return a


def _bytes(a, order):
    a = array.array("h", a)
    if (order == "big") == (sys.byteorder == "little"):
        a.byteswap()
    return a.tobytes()


def roughness(raw, order):
    """How noise-like the audio reads in this byte order (lower = smoother = speech); None if it's near silence."""
    a = _samples(raw, order)
    if len(a) < 64:
        return None
    level = sum(abs(x) for x in a) / len(a)
    if level < 30:
        return None
    return sum(abs(a[i] - a[i - 1]) for i in range(1, len(a))) / (len(a) - 1) / level


def guess_order(raw):
    """"little" / "big" from a stretch of caller audio, or None when it can't tell (silence)."""
    lo, hi = roughness(raw, "little"), roughness(raw, "big")
    if lo is None and hi is None:
        return None
    if lo is None:
        return "big"
    if hi is None:
        return "little"
    return "little" if lo <= hi else "big"


def to_le(raw, order):
    """Telnyx L16 (in `order`) -> little-endian PCM, which Gemini takes."""
    return raw if order == "little" else _bytes(_samples(raw, "big"), "little")


def resample_24k_to_16k(pcm_le):
    """Gemini's 24 kHz little-endian PCM -> 16 kHz (linear interpolation, 3 samples to 2)."""
    a = _samples(pcm_le, "little")
    n = len(a) * 2 // 3
    out = array.array("h", bytes(2 * n))
    for i in range(n):
        x = i * 1.5
        j = int(x)
        f = x - j
        b = a[j + 1] if j + 1 < len(a) else a[j]
        out[i] = int(a[j] + (b - a[j]) * f)
    return _bytes(out, "little")


_DTMF = {"1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "A": (697, 1633), "4": (770, 1209), "5": (770, 1336),
         "6": (770, 1477), "B": (770, 1633), "7": (852, 1209), "8": (852, 1336), "9": (852, 1477), "C": (852, 1633),
         "*": (941, 1209), "0": (941, 1336), "#": (941, 1477), "D": (941, 1633)}
KEYS_OK = re.compile(r"^[0-9*#wW]{1,32}$")


def dtmf_pcm(digits, rate=16000, tone_ms=160, gap_ms=90):
    """In-band keypad tones (16 kHz little-endian PCM): each key's two frequencies; w = 0.5 s pause, W = 1 s."""
    out = array.array("h")
    for k in digits:
        if k in "wW":
            out.extend([0] * (rate // (2 if k == "w" else 1)))
            continue
        lo, hi = _DTMF[k]
        n = rate * tone_ms // 1000
        out.extend(int(7000 * (math.sin(2 * math.pi * lo * i / rate) + math.sin(2 * math.pi * hi * i / rate))) for i in range(n))
        out.extend([0] * (rate * gap_ms // 1000))
    return _bytes(out, "little")


def from_le(pcm_le, order):
    return pcm_le if order == "little" else _bytes(_samples(pcm_le, "little"), "big")
