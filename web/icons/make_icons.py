"""Draws Theta's dot-globe app icons (the same globe as web/orb.js: ~520 dots on a Fibonacci sphere, depth-sorted,
near dots bigger and brighter, a white-hot core and a cyan/blue halo) on the app's dark background.

    python3 web/icons/make_icons.py      # writes icon-192.png, icon-512.png, apple-touch-icon.png, badge-72.png

Needs Pillow. The globe sits inside the central 60% so the 512 icon also works as a maskable icon.
"""
import colorsys
import math
import os
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
BG = (20, 20, 20)
HUE, SAT, LIGHT, EDGE_HUE = 195, 0.95, 0.62, 222


def hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, max(0, min(1, l)), max(0, min(1, s)))
    return int(r * 255), int(g * 255), int(b * 255)


def globe(size, n=520, seed=7):
    rnd = random.Random(seed)
    ss = 4  # supersampling
    S = size * ss
    img = Image.new("RGB", (S, S), BG)
    c = S / 2
    R = S * 0.27

    # halo: cyan in the middle, blue at the edge
    halo = Image.new("RGB", (S, S), (0, 0, 0))
    hd = ImageDraw.Draw(halo)
    steps = 60
    for i in range(steps, 0, -1):
        u = i / steps
        rr = R * 2.3 * u
        k = (1 - u) ** 1.6
        h = HUE + (EDGE_HUE - HUE) * u
        col = hsl(h, 1, 0.5)
        a = 0.55 * k
        hd.ellipse([c - rr, c - rr, c + rr, c + rr], fill=tuple(int(v * a) for v in col))
    halo = halo.filter(ImageFilter.GaussianBlur(S * 0.02))
    img = add(img, halo)

    # dots
    yaw, pitch, D = 0.6, 0.3, 3.2
    cy_, sy_, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    pts = []
    for i in range(n):
        y = 1 - (i / (n - 1)) * 2
        r = math.sqrt(max(0, 1 - y * y))
        th = i * 2.39996
        x, z = math.cos(th) * r, math.sin(th) * r
        s = rnd.random()
        x1, z1 = x * cy_ - z * sy_, x * sy_ + z * cy_
        y2, z2 = y * cp - z1 * sp, y * sp + z1 * cp
        pr = D / (D + z2)
        pts.append((c + x1 * R * pr, c + y2 * R * pr, z2, pr, s))
    pts.sort(key=lambda p: -p[2])
    layer = Image.new("RGB", (S, S), (0, 0, 0))
    ld = ImageDraw.Draw(layer)
    core_done = False
    for px, py, z, pr, s in pts:
        if not core_done and z < 0:
            layer = add(layer, core(S, c, R))
            ld = ImageDraw.Draw(layer)
            core_done = True
        fog = max(0.12, min(1, 0.62 - z * 0.55))
        h = HUE + s * 18 - 9 + max(0, z) * (EDGE_HUE - HUE)
        l = LIGHT + ((pr - 0.8) * 50) / 100
        a = min(1, (0.1 + 0.55 * (0.4 + 0.6 * s)) * fog * 1.5)
        col = tuple(int(v * a) for v in hsl(h, SAT, l))
        rad = max(1.2 * ss, R * 0.027 * pr * pr * (0.8 + 0.4 * s))
        ld.ellipse([px - rad, py - rad, px + rad, py + rad], fill=col)
    if not core_done:
        layer = add(layer, core(S, c, R))
    img = add(img, layer)
    return img.resize((size, size), Image.LANCZOS)


def core(S, c, R):
    im = Image.new("RGB", (S, S), (0, 0, 0))
    d = ImageDraw.Draw(im)
    cr = R * 0.2 * 3.2
    steps = 50
    for i in range(steps, 0, -1):
        u = i / steps
        rr = cr * u
        if u < 0.06:
            col, a = (255, 255, 255), 1
        else:
            col, a = hsl(HUE, SAT, LIGHT + 0.3 * (1 - u) ** 3), (1 - u) ** 2.2 * 0.9
        d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=tuple(int(v * a) for v in col))
    return im.filter(ImageFilter.GaussianBlur(R * 0.03))


def add(a, b):
    return ImageChops.add(a, b)


def badge(size=72):
    """A monochrome badge (Android's status bar shows only the alpha): a ring of dots."""
    ss = 4
    S = size * ss
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c, R = S / 2, S * 0.36
    n = 140
    for i in range(n):
        y = 1 - (i / (n - 1)) * 2
        r = math.sqrt(max(0, 1 - y * y))
        th = i * 2.39996
        x, z = math.cos(th) * r, math.sin(th) * r
        if z < -0.1:
            continue
        rad = S * 0.022 * (0.7 + 0.5 * (z + 1) / 2)
        d.ellipse([c + x * R - rad, c + y * R - rad, c + x * R + rad, c + y * R + rad], fill=(255, 255, 255, 255))
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
        globe(size).save(os.path.join(HERE, name), optimize=True)
        print("wrote", name)
    badge().save(os.path.join(HERE, "badge-72.png"), optimize=True)
    print("wrote badge-72.png")
