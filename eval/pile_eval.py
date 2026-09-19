#!/usr/bin/env python3
"""Score the CV pipeline against ground truth. Build this BEFORE tuning anything.

Three numbers, and only these three matter:

  1. RECALL          did we find the bricks?           (segmentation)
  1b. PRECISION      how much of what we "found" is real? A segmenter that returns 200 masks for
                     39 bricks scores perfect recall and floods the inventory with phantom rows,
                     each of which costs a Brickognize call and a line of UI the user must delete.
  2. TOP-1 / TOP-5   did we name them right?           (classification, over matched pieces)
  3. SET ACCURACY    |predicted multiset ^ true|/|true|  (what the user actually experiences)

Synthetic validation accuracy will read ~99% and mean nothing. Only real photos move these.

    python -m eval.pile_eval data/test/pile01.png
    python -m eval.pile_eval data/real/labelled_piles/     # a folder of img + .truth.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vision.pipeline import analyse_photo
from vision.resolve import resolve

RESULTS = pathlib.Path(__file__).resolve().parents[1] / "eval" / "results.tsv"


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def canonical(part: str | None) -> str | None:
    """Compare on resolved LDraw ids so a BrickLink/LDraw suffix difference isn't a 'miss'."""
    if not part:
        return None
    r, _ = resolve(part)
    return r or part


def score_one(image: pathlib.Path, truth: dict, scale: float, classify: bool = True) -> dict:
    rows = analyse_photo(image, classify=classify)
    truth_pieces = truth["pieces"]

    # Truth boxes are in original-image pixels; the pipeline works on a downscaled copy.
    tboxes = [[v * scale for v in p["bbox"]] for p in truth_pieces]

    matched: list[tuple[int, int]] = []
    used_pred: set[int] = set()
    for ti, tb in enumerate(tboxes):
        best, best_iou = -1, 0.0
        for pi, r in enumerate(rows):
            if pi in used_pred:
                continue
            v = iou(tb, r["bbox"])
            if v > best_iou:
                best, best_iou = pi, v
        if best >= 0 and best_iou >= 0.3:
            matched.append((ti, best))
            used_pred.add(best)

    recall = len(matched) / max(1, len(truth_pieces))
    precision = len(matched) / max(1, len(rows))

    # A class-agnostic dataset (every category is just "brick") can score segmentation recall but
    # NOT classification. Scoring it anyway would compare None to None and report a perfect 1.00,
    # which is the most misleading number this harness could produce.
    scorable = [(ti, pi) for ti, pi in matched if truth_pieces[ti].get("part")]
    top1 = top5 = 0
    for ti, pi in scorable:
        want = canonical(truth_pieces[ti]["part"])
        got = canonical(rows[pi].get("part"))
        alts = [canonical(a["part"]) for a in rows[pi].get("alternatives", [])]
        if got == want:
            top1 += 1
        if want in ([got] + alts):
            top5 += 1

    labelled = [p for p in truth_pieces if p.get("part")]
    want_set = Counter(canonical(p["part"]) for p in labelled)
    got_set = Counter(canonical(r["part"]) for r in rows if r.get("part"))
    overlap = sum((want_set & got_set).values())
    set_acc = overlap / max(1, sum(want_set.values())) if labelled else float("nan")

    return {
        "image": image.name,
        "truth": len(truth_pieces),
        "detected": len(rows),
        "matched": len(matched),
        "recall": round(recall, 3),
        "precision": round(precision, 3),
        "classifiable": len(scorable),
        "top1": round(top1 / len(scorable), 3) if scorable else float("nan"),
        "top5": round(top5 / len(scorable), 3) if scorable else float("nan"),
        "set_accuracy": round(set_acc, 3),
        "missed_parts": sorted((want_set - got_set).elements()),
        "phantom_parts": sorted((got_set - want_set).elements()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--max-edge", type=int, default=1600, help="must match vision.segment.MAX_EDGE")
    ap.add_argument("--tag", default="", help="label this run in results.tsv")
    ap.add_argument("--seg-only", action="store_true",
                    help="score segmentation recall only -- no classifier calls")
    ap.add_argument("--limit", type=int, default=0, help="score at most N images")
    args = ap.parse_args()

    target = pathlib.Path(args.target)
    images = ([target] if target.is_file()
              else sorted(p for p in target.rglob("*")
                          if p.suffix.lower() in {".png", ".jpg", ".jpeg"}))
    if args.seg_only:
        print("segmentation-only: classification columns will be NaN\n")

    rows = []
    for img in images:
        tpath = img.with_suffix("").with_suffix(".truth.json")
        if not tpath.exists():
            tpath = img.with_name(img.stem + ".truth.json")
        if not tpath.exists():
            print(f"  skip {img.name}: no .truth.json beside it")
            continue
        truth = json.loads(tpath.read_text())
        from PIL import Image
        with Image.open(img) as im:
            scale = min(1.0, args.max_edge / max(im.size))
        rows.append(score_one(img, truth, scale, classify=not args.seg_only))
        if args.limit and len(rows) >= args.limit:
            break

    if not rows:
        print("nothing scored -- every image needs a matching <name>.truth.json")
        return

    print(f"\n{'image':22s} {'truth':>5s} {'det':>4s} {'recall':>7s} {'prec':>6s} "
          f"{'top1':>6s} {'top5':>6s} {'set':>6s}")
    print("-" * 70)
    for r in rows:
        print(f"{r['image'][:22]:22s} {r['truth']:5d} {r['detected']:4d} "
              f"{r['recall']:7.2f} {r['precision']:6.2f} {r['top1']:6.2f} "
              f"{r['top5']:6.2f} {r['set_accuracy']:6.2f}")
    def mean(k):
        vals = [r[k] for r in rows if r[k] == r[k]]        # drop NaN (class-agnostic truth)
        return sum(vals) / len(vals) if vals else float("nan")
    avg = {k: mean(k) for k in ("recall", "precision", "top1", "top5", "set_accuracy")}
    if any(r["classifiable"] == 0 for r in rows):
        print("\nnote: some images have class-agnostic truth -- recall is scored, classification is not")
    print("-" * 70)
    print(f"{'MEAN':22s} {'':5s} {'':4s} {avg['recall']:7.2f} {avg['precision']:6.2f} "
          f"{avg['top1']:6.2f} {avg['top5']:6.2f} {avg['set_accuracy']:6.2f}")

    missed = sorted({p for r in rows for p in r["missed_parts"]})
    phantom = sorted({p for r in rows for p in r["phantom_parts"]})
    if missed:
        print(f"\nmissed:  {', '.join(str(m) for m in missed[:16])}")
    if phantom:
        print(f"phantom: {', '.join(str(p) for p in phantom[:16])}")

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    new = not RESULTS.exists()
    with RESULTS.open("a") as f:
        if new:
            f.write("tag\timages\trecall\tprecision\ttop1\ttop5\tset_accuracy\n")
        f.write(f"{args.tag or target.name}\t{len(rows)}\t{avg['recall']:.3f}\t"
                f"{avg['precision']:.3f}\t{avg['top1']:.3f}\t{avg['top5']:.3f}\t"
                f"{avg['set_accuracy']:.3f}\n")
    print(f"\nappended to {RESULTS}")


if __name__ == "__main__":
    main()
