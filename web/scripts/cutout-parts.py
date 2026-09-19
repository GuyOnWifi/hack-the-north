"""Make the white background of the bundled Rebrickable part renders transparent
(flood fill from the border, so white areas inside a part survive) and trim.

    python3 scripts/cutout-parts.py
"""
from pathlib import Path
from collections import deque
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent / "public" / "parts"

def near_white(p, tol=18):
    return p[0] > 255 - tol and p[1] > 255 - tol and p[2] > 255 - tol

def cutout(path):
    im = Image.open(path).convert("RGBA")
    if im.getpixel((0, 0))[3] == 0:
        return False  # already processed
    w, h = im.size
    px = im.load()
    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        q.append((x, 0)); q.append((x, h - 1))
    for y in range(h):
        q.append((0, y)); q.append((w - 1, y))
    while q:
        x, y = q.popleft()
        i = y * w + x
        if seen[i]:
            continue
        seen[i] = 1
        p = px[x, y]
        if not near_white(p):
            continue
        px[x, y] = (255, 255, 255, 0)
        if x > 0: q.append((x - 1, y))
        if x < w - 1: q.append((x + 1, y))
        if y > 0: q.append((x, y - 1))
        if y < h - 1: q.append((x, y + 1))
    # soften the fringe: semi-transparent for light pixels touching the cut
    bbox = im.getbbox()
    if bbox:
        pad = 4
        l, t, r, b = bbox
        im = im.crop((max(0, l - pad), max(0, t - pad), min(w, r + pad), min(h, b + pad)))
    im.save(path)
    return True

n = sum(cutout(p) for p in ROOT.rglob("*.png"))
print(f"processed {n} images")
