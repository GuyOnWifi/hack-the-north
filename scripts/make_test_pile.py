#!/usr/bin/env python3
"""Build a synthetic 'pile' photo from real LDraw part renders, with ground truth.

This lets you validate the whole CV pipeline BEFORE you take a single photograph -- and it gives
the eval harness something to score on day one.

It is NOT a substitute for real photos: these renders have clean edges, no shadows, no motion
blur and perfect lighting, so scores here will be optimistic. Treat it as a plumbing test and a
regression guard, and keep the real-photo numbers as the ones that count.

    python scripts/make_test_pile.py -n 12 -o data/test/pile01
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import random
import sys

import numpy as np
import requests
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "library.csv"
PART_CACHE = ROOT / "data" / "part_png"

# Plain, common moulds -- the ones a home bin is actually full of.
DEFAULT_PARTS = ["3001", "3003", "3004", "3005", "3010", "3020", "3022", "3023b",
                 "3024", "3622", "3623", "3069b", "3070b", "3002", "3710"]


def part_png(part: str) -> Image.Image | None:
    PART_CACHE.mkdir(parents=True, exist_ok=True)
    cached = PART_CACHE / f"{part}.png"
    if cached.exists():
        return Image.open(cached).convert("RGBA")
    rows = csv.DictReader(io.StringIO(CATALOG.read_text(errors="replace")))
    url = next((r["image_url"] for r in rows if r["part_number"] == f"{part}.dat"), None)
    if not url:
        return None
    try:
        data = requests.get(url, timeout=20, headers={"User-Agent": "Bricolage/0.1"}).content
    except requests.RequestException:
        return None
    cached.write_bytes(data)
    return Image.open(cached).convert("RGBA")


def tint(img: Image.Image, rgb: tuple[int, int, int]) -> Image.Image:
    """Recolour a part render toward an LDraw colour, keeping its shading.

    The library's PNGs are all rendered in one colour, so an untinted pile gives the colour stage
    nothing to be wrong about -- and a colour metric that cannot fail is worse than none.
    """
    arr = np.asarray(img.convert("RGBA")).astype(np.float64)
    rgb_px, alpha = arr[..., :3], arr[..., 3:]
    lum = rgb_px.mean(axis=2, keepdims=True) / 255.0
    shaded = np.clip(np.array(rgb, dtype=np.float64) * (0.45 + 0.75 * lum), 0, 255)
    return Image.fromarray(np.concatenate([shaded, alpha], axis=2).astype(np.uint8), "RGBA")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--count", type=int, default=12)
    ap.add_argument("-o", "--out", default="data/test/pile01")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--size", type=int, default=1400)
    ap.add_argument("--bg", default="240,238,232", help="background r,g,b")
    ap.add_argument("--recolor", action="store_true",
                    help="tint parts to real LDraw colours (the source renders are all one colour)")
    ap.add_argument("--noise", type=float, default=0.0, help="gaussian noise sigma, 0-20")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)

    bg = tuple(int(v) for v in args.bg.split(","))
    canvas = Image.new("RGB", (args.size, args.size), bg)
    truth: list[dict] = []

    cols, cell = 4, args.size // 4
    slots = [(c * cell, r * cell) for r in range(cols) for c in range(cols)]
    rng.shuffle(slots)

    for i in range(min(args.count, len(slots))):
        part = DEFAULT_PARTS[i % len(DEFAULT_PARTS)]
        img = part_png(part)
        if img is None:
            print(f"  ! no render for {part}")
            continue
        colour_code = None
        if args.recolor:
            from vision.color import palette
            pal = [p for p in palette() if p[0] in (0, 1, 2, 4, 14, 15, 19, 25, 70, 71, 72)]
            colour_code, _cname, crgb, _lab = rng.choice(pal)
            img = tint(img, crgb)
        scale = rng.uniform(0.55, 0.85) * cell / max(img.size)
        img = img.resize((max(8, int(img.width * scale)), max(8, int(img.height * scale))),
                         Image.LANCZOS)
        img = img.rotate(rng.uniform(0, 360), expand=True, resample=Image.BICUBIC)
        sx, sy = slots[i]
        px = sx + rng.randint(4, max(5, cell - img.width - 4))
        py = sy + rng.randint(4, max(5, cell - img.height - 4))
        canvas.paste(img, (px, py), img)
        piece = {"part": part, "bbox": [px, py, img.width, img.height]}
        if colour_code is not None:
            piece["color"] = colour_code
        truth.append(piece)

    if args.noise > 0:
        a = np.asarray(canvas).astype(np.float64)
        a += np.random.default_rng(args.seed).normal(0, args.noise, a.shape)
        canvas = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    img_path = out.with_suffix(".png")
    canvas.save(img_path)
    out.with_suffix(".truth.json").write_text(json.dumps(
        {"image": img_path.name, "pieces": truth,
         "note": "synthetic: clean renders, no shadows. Optimistic vs real photos."}, indent=2) + "\n")
    print(f"wrote {img_path} with {len(truth)} pieces")
    print(f"wrote {out.with_suffix('.truth.json')}")


if __name__ == "__main__":
    main()
