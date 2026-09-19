"""photo -> inventory.json  (Contract 1 in docs/lanes/00-contracts.md)

    python -m vision.pipeline photo.jpg -o fixtures/inventory.json
    python -m vision.pipeline data/real/known_piles/ --debug out/

The confidence policy is the point. Nothing is ever silently wrong:

    part score >= 0.85            -> confirmed      (green)
    0.50 <= part score < 0.85     -> needs_review   (amber, top-3 alternatives one tap away)
    part score < 0.50             -> unknown        (counted in the total, excluded from the solver)

Every row keeps its evidence -- the crop it came from and the runner-up candidates -- so a wrong
guess is a UI affordance rather than a failure.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import cv2
import numpy as np

from . import brickness as brickness_mod
from . import classify as classify_mod
from . import color as color_mod
from .resolve import resolve_candidates
from .segment import Piece, segment

CONFIRM_AT = 0.85
REVIEW_AT = 0.50

# Colour is our weakest measured stage (0.70 accuracy on high-confidence rows only), so it must
# not be a hard constraint on generation. The market leader ignores colour entirely when matching
# builds; Rebrickable exposes Exact / Similar / Ignore as a user-visible toggle. We do the same:
# the inventory records our best guess and how sure we are, and the solver decides how much to
# trust it. That takes our worst number off the critical path without hiding it.
COLOUR_TRUSTED_AT = 0.60
MIN_PIECES_TO_BUILD = 40


# Retry variants, cheapest and most likely first. Only crops that came back with NOTHING are
# retried, so the cost is a handful of extra calls per photo rather than 4x the whole batch.
#
# MEASURED on the plain-table photos: 16 crops returned nothing on the first pass; the ladder
# recovered an answer for 9 of them (56%), 7 of which were placeable. Which variant won:
# rot90 x4, unmasked x3, rot180 x1, pad40 x1 -- no single one dominates, which is why it is a
# ladder and not one better default. Brickognize's own API notes that multiple views of the same
# item improve accuracy; this is that, from a single photograph.
RETRY_VARIANTS = (
    ("rot90", lambda piece, work, full: cv2.rotate(
        piece.crop_on_white(work, full_res=full), cv2.ROTATE_90_CLOCKWISE)),
    ("unmasked", lambda piece, work, full: piece.crop(work)),
    ("rot180", lambda piece, work, full: cv2.rotate(
        piece.crop_on_white(work, full_res=full), cv2.ROTATE_180)),
    ("pad40", lambda piece, work, full: piece.crop_on_white(work, full_res=full, pad=40)),
)


def _png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("failed to encode crop")
    return buf.tobytes()


def analyse_photo(path: str | pathlib.Path, *, debug_dir: pathlib.Path | None = None,
                  progress=None, classify: bool = True) -> list[dict]:
    """One photo -> a list of detection rows (not yet aggregated into inventory items)."""
    path = pathlib.Path(path)
    image = cv2.imread(str(path))
    if image is None:
        raise FileNotFoundError(f"cannot read image: {path}")

    work, pieces = segment(image)
    if not pieces:
        return []

    # Crop at full resolution: `work` is downscaled for segmentation, `image` is not.
    cropped = [p.crop_on_white(work, full_res=image) for p in pieces]

    # Drop crops that are the table rather than a brick, BEFORE paying for a classifier call.
    # Measured on the user's 9 photos: 562 of 1,296 crops were the blanket or the pegboard they
    # were shot on, and 479 of those resolved to a placeable part -- i.e. phantom inventory. Off
    # by default: see vision/brickness.py for what it does and does not generalise to.
    if brickness_mod.ENABLED and pieces:
        keep = [i for i, (p, c) in enumerate(zip(pieces, cropped))
                if brickness_mod.is_brick(c, solidity=p.solidity)]
        if len(keep) < len(pieces):
            print(f"  brickness: dropped {len(pieces) - len(keep)}/{len(pieces)} crops as background")
        pieces = [pieces[i] for i in keep]
        cropped = [cropped[i] for i in keep]
        if not pieces:
            return []

    crops = [_png(c) for c in cropped]
    # Segmentation-only mode: score recall without hammering a free API 5,000 times.
    results = (classify_mod.classify_many(crops, progress=progress) if classify
               else [[] for _ in crops])

    if classify:
        retried = 0
        for i, (piece, cands) in enumerate(zip(pieces, results)):
            if cands:
                continue
            for _name, make in RETRY_VARIANTS:
                again = classify_mod.classify_bytes(_png(make(piece, work, image)))
                if again:
                    results[i] = again
                    retried += 1
                    break
        if retried:
            print(f"\n  recovered {retried} crop(s) on retry", end="")

    # Estimate the white point ONCE from the full frame: a single brick crop is far too small
    # a sample. Measured effect on real photos: hue confusions (Black->Brown, Grey->Nougat)
    # largely disappear and high-confidence colour accuracy rises 0.605 -> 0.703.
    illum = color_mod.estimate_illuminant(work)

    rows: list[dict] = []
    for piece, cands, png in zip(pieces, results, crops):
        code, cname, cconf = color_mod.colour_of(work, piece.mask, illum)
        # Brickognize speaks BrickLink ids; everything downstream speaks LDraw. See vision/resolve.py.
        part, how, best = resolve_candidates(cands)
        score = best.score if best else 0.0
        status = ("confirmed" if score >= CONFIRM_AT
                  else "needs_review" if score >= REVIEW_AT else "unknown")
        if part is None and cands:
            status = "unknown"
        rows.append({
            "photo": path.name,
            "piece": piece.index,
            "bbox": list(piece.bbox),
            "part": part,
            "raw_part": best.part if best else None,
            "resolved_by": how,
            "name": best.name if best else "unidentified",
            "color": code,
            "color_name": cname,
            "confidence": {"part": round(score, 3), "color": round(cconf, 3)},
            "status": status,
            "alternatives": [c.to_dict() for c in cands[1:4]],
        })

        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)
            tag = part or "unknown"
            (debug_dir / f"{path.stem}_{piece.index:02d}_{tag}.png").write_bytes(png)

    if debug_dir:
        overlay = work.copy()
        for p, r in zip(pieces, rows):
            x, y, w, h = p.bbox
            col = {"confirmed": (0, 200, 0), "needs_review": (0, 190, 255),
                   "unknown": (120, 120, 120)}[r["status"]]
            cv2.rectangle(overlay, (x, y), (x + w, y + h), col, 2)
            cv2.putText(overlay, f'{r["part"] or "?"}', (x, max(12, y - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
        cv2.imwrite(str(debug_dir / f"{path.stem}_overlay.jpg"), overlay)

    return rows


def analyse_folder(folder: str | pathlib.Path, **kw) -> list[dict]:
    folder = pathlib.Path(folder)
    photos = sorted(p for p in folder.rglob("*")
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic"})
    rows: list[dict] = []
    for p in photos:
        try:
            rows += analyse_photo(p, **kw)
        except Exception as exc:                       # one bad photo must not kill the batch
            print(f"  ! {p.name}: {exc}", file=sys.stderr)
    return rows


def to_inventory(rows: list[dict], session_id: str = "ses_local") -> dict:
    """Aggregate detections into Contract 1. Identical (part, colour) rows merge into a qty."""
    from core import meta as meta_mod

    buckets: dict[tuple[str | None, int], dict] = {}
    unknown = 0
    for r in rows:
        if r["status"] == "unknown" or not r["part"]:
            unknown += 1
            continue
        key = (r["part"], r["color"])
        b = buckets.setdefault(key, {"rows": [], "qty": 0})
        b["rows"].append(r)
        b["qty"] += 1

    items = []
    for i, ((part, color), b) in enumerate(sorted(buckets.items()), 1):
        first = b["rows"][0]
        worst = min(r["confidence"]["part"] for r in b["rows"])
        name = first["name"]
        if meta_mod.has(part):
            name = meta_mod.get(part).name
        items.append({
            "id": f"inv_{i:03d}",
            "part": part,
            "name": name,
            "color": color,
            "color_name": first["color_name"],
            "qty": b["qty"],
            "source": "photo",
            "confidence": {
                "part": round(sum(r["confidence"]["part"] for r in b["rows"]) / len(b["rows"]), 3),
                "color": round(min(r["confidence"]["color"] for r in b["rows"]), 3),
            },
            "status": "confirmed" if worst >= CONFIRM_AT else "needs_review",
            "placeable": meta_mod.has(part),
            # "exact" -> trust the colour; "similar" -> treat as a hint the solver may override.
            "color_mode": "exact" if min(r["confidence"]["color"] for r in b["rows"]) >= COLOUR_TRUSTED_AT else "similar",
            "evidence": {
                "photo": first["photo"],
                "bbox": first["bbox"],
                # Every instance's location, not just the first. This is what powers "show me
                # where my 6 red 2x4s are in the photo" -- the single most-praised feature of the
                # closest comparable product. Keeping only first["bbox"] silently threw away
                # qty-1 locations per row.
                "bboxes": [r["bbox"] for r in b["rows"]],
                "alternatives": first["alternatives"],
            },
        })

    pieces = sum(i["qty"] for i in items) + unknown
    return {
        "session_id": session_id,
        "items": items,
        "totals": {
            "pieces": pieces,
            "distinct": len(items),
            "unknown": unknown,
            "unplaceable": sum(1 for i in items if not i["placeable"]),
        },
        # Below this, generation produces something embarrassing rather than something small.
        # Saying "spread more bricks out and rescan" is deliberate product behaviour; emitting a
        # 4-brick "model" is a demo failure. The comparable product gates at ~150.
        "sufficient": pieces >= MIN_PIECES_TO_BUILD,
        "guidance": (None if pieces >= MIN_PIECES_TO_BUILD else
                     f"Found {pieces} pieces. Spread more bricks out in a single layer and scan "
                     f"again -- we need about {MIN_PIECES_TO_BUILD} to design something worth building."),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="photo(s) -> inventory.json")
    ap.add_argument("input", help="an image, or a folder of images")
    ap.add_argument("-o", "--out", default="inventory.json")
    ap.add_argument("--debug", help="write crops and an annotated overlay here")
    args = ap.parse_args()

    debug = pathlib.Path(args.debug) if args.debug else None
    src = pathlib.Path(args.input)

    def progress(done, total):
        print(f"\r  classifying {done}/{total}", end="", flush=True)

    rows = (analyse_folder(src, debug_dir=debug, progress=progress) if src.is_dir()
            else analyse_photo(src, debug_dir=debug, progress=progress))
    print()

    inv = to_inventory(rows)
    pathlib.Path(args.out).write_text(json.dumps(inv, indent=2) + "\n")

    t = inv["totals"]
    print(f"{t['pieces']} pieces · {t['distinct']} distinct · {t['unknown']} unknown "
          f"· {t['unplaceable']} not placeable")
    for it in inv["items"][:15]:
        flag = "" if it["status"] == "confirmed" else "  <- review"
        print(f"  {it['qty']:3d}x {it['part']:8s} {it['color_name'][:16]:16s} "
              f"{it['name'][:30]:30s} {it['confidence']['part']:.2f}{flag}")
    print(f"\nwrote {args.out}   cache: {classify_mod.cache_stats()}")


if __name__ == "__main__":
    main()
