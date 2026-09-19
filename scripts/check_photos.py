#!/usr/bin/env python3
"""Check a photo shoot BEFORE you pack up. Ten seconds; saves discovering at hour 14 that
eighty photos are unusable.

Flags: blur (variance of Laplacian), resolution, busy backgrounds, and per-folder counts.

    python scripts/check_photos.py data/real/
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BLUR_FLOOR = 60.0       # variance of Laplacian; below this is visibly soft
MIN_EDGE = 900          # below this a 1x1 plate is a handful of pixels
BUSY_BG = 28.0          # std-dev of the border ring; high means a cluttered background


def check(path: pathlib.Path) -> dict:
    img = cv2.imread(str(path))
    if img is None:
        return {"file": path, "ok": False, "why": ["unreadable"]}
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    band = max(4, min(h, w) // 25)
    ring = np.concatenate([gray[:band].ravel(), gray[-band:].ravel(),
                           gray[:, :band].ravel(), gray[:, -band:].ravel()])
    bg_std = float(ring.std())

    why = []
    if min(h, w) < MIN_EDGE:
        why.append(f"small ({w}x{h})")
    if blur < BLUR_FLOOR:
        why.append(f"blurry ({blur:.0f})")
    if bg_std > BUSY_BG:
        why.append(f"busy background (sd {bg_std:.0f})")
    return {"file": path, "ok": not why, "why": why, "blur": blur, "bg": bg_std,
            "size": (w, h)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", default="data/real", nargs="?")
    args = ap.parse_args()
    root = pathlib.Path(args.folder)
    photos = sorted(p for p in root.rglob("*")
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not photos:
        print(f"no photos under {root}")
        print("Expected layout (see data/real/README.md):")
        print("  known_piles/      20 piles, each with a contents.csv")
        print("  labelled_piles/   20-30 piles to hand-mask in CVAT/Roboflow")
        return

    results = [check(p) for p in photos]
    bad = [r for r in results if not r["ok"]]

    by_folder: dict[str, int] = {}
    for p in photos:
        rel = p.relative_to(root).parts[0] if len(p.relative_to(root).parts) > 1 else "."
        by_folder[rel] = by_folder.get(rel, 0) + 1

    print(f"{len(photos)} photos, {len(photos) - len(bad)} usable\n")
    for folder, n in sorted(by_folder.items()):
        print(f"  {folder:22s} {n:4d}")

    if bad:
        print(f"\n{len(bad)} need reshooting:")
        for r in bad[:25]:
            print(f"  {str(r['file'].relative_to(root))[:48]:48s} {', '.join(r['why'])}")
        if len(bad) > 25:
            print(f"  ... and {len(bad) - 25} more")

    # Targets from docs/lanes/cv-runbook.md, post-research (no classifier to fine-tune).
    targets = {"known_piles": 20, "labelled_piles": 20}
    print()
    for folder, want in targets.items():
        have = by_folder.get(folder, 0)
        mark = "ok" if have >= want else f"need {want - have} more"
        print(f"  {folder:22s} {have:3d}/{want:<3d} {mark}")


if __name__ == "__main__":
    main()
