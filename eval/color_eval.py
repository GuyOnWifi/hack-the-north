#!/usr/bin/env python3
"""Score the colour stage against ground truth, using the TRUTH boxes.

Segmentation and classification are evaluated elsewhere; this isolates colour so a bad number
here means the colour code is wrong, not that we failed to find the brick.

    python -m eval.color_eval data/external/brickognize_dataset/uncontrolled/

Needs `.truth.json` files whose pieces carry a "color" (LDraw code). `eval/import_coco.py`
extracts those automatically from `part_colour` category names.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vision.color import colour_of, estimate_illuminant, palette


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--pad", type=int, default=2, help="shrink each truth box by this many px")
    ap.add_argument("--no-wb", action="store_true", help="disable white balance, for A/B")
    args = ap.parse_args()

    names = {c[0]: c[1] for c in palette(False)}
    root = pathlib.Path(args.folder)
    truths = sorted(root.glob("*.truth.json"))[: args.limit]

    total = correct = 0
    confusion: Counter = Counter()
    by_conf: dict[str, list[int]] = {"high": [], "low": []}

    for tp in truths:
        truth = json.loads(tp.read_text())
        img_path = root / truth["image"]
        if not img_path.exists():
            continue
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        H, W = img.shape[:2]
        illum = None if args.no_wb else estimate_illuminant(img)
        for piece in truth["pieces"]:
            want = piece.get("color")
            if want is None:
                continue
            x, y, w, h = piece["bbox"]
            x0, y0 = max(0, x + args.pad), max(0, y + args.pad)
            x1, y1 = min(W, x + w - args.pad), min(H, y + h - args.pad)
            if x1 - x0 < 3 or y1 - y0 < 3:
                continue
            sub = img[y0:y1, x0:x1]
            mask = np.full(sub.shape[:2], 255, np.uint8)
            got, _name, conf = colour_of(sub, mask, illum)
            total += 1
            hit = got == want
            correct += hit
            if not hit:
                confusion[(want, got)] += 1
            by_conf["high" if conf >= 0.5 else "low"].append(1 if hit else 0)

    if not total:
        print("no colour ground truth found -- run eval/import_coco.py with --map-categories first")
        return

    print(f"colour accuracy: {correct}/{total} = {correct / total:.3f}   "
          f"({len(truths)} images)")
    for bucket, vals in by_conf.items():
        if vals:
            print(f"  confidence {bucket:4s}: {sum(vals)}/{len(vals)} = {sum(vals)/len(vals):.3f}")
    print("\ntop confusions (truth -> predicted):")
    for (want, got), n in confusion.most_common(8):
        print(f"  {n:5d}x  {names.get(want, want)} -> {names.get(got, got)}")


if __name__ == "__main__":
    main()
