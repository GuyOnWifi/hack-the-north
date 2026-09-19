#!/usr/bin/env python3
"""COCO instance annotations -> our .truth.json format.

You need this whichever way the photo question lands:
  * you label your own piles in CVAT / Roboflow / Label Studio  -> they export COCO
  * you download someone else's annotated LEGO dataset          -> it ships COCO

    python -m eval.import_coco annotations.json --images data/real/labelled_piles/
    python -m eval.import_coco _annotations.coco.json --images . --map-categories

CLASS-AGNOSTIC DATASETS ARE STILL USEFUL. A dataset whose only category is "brick" cannot score
classification, but it CAN score segmentation recall -- which is the riskier half of our pipeline.
Those rows get part=null and the eval harness scores recall only, rather than silently treating
"unlabelled" as "correctly identified".
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vision.resolve import resolve

# Category names that mean "this is a brick" rather than naming a specific part.
GENERIC = re.compile(r"^(lego|brick|bricks|piece|pieces|part|parts|object|block)s?$", re.I)
# A part id hiding in a category name: "3001", "brick 3001", "3023b - Plate 1 x 2", "3648b_72".
# NOTE: \b does not work here -- underscore is a word character, so \b never matches between
# "2780" and "_0", which silently turned a fully labelled dataset into a class-agnostic one.
PART_IN_NAME = re.compile(r"(?:^|[^0-9A-Za-z])(\d{3,6}[a-z]?)(?:[^0-9A-Za-z]|$)", re.I)
# "<part>_<ldraw colour>" -- used by the Brickognize test set, and free colour ground truth.
PART_COLOUR = re.compile(r"^(\d{3,6}[a-z]?)_(\d{1,3})$", re.I)


def category_to_part(name: str, map_categories: bool) -> tuple[str | None, str]:
    part, _colour, how = category_to_part_colour(name, map_categories)
    return part, how


def category_to_part_colour(name: str, map_categories: bool) -> tuple[str | None, int | None, str]:
    """(ldraw part, ldraw colour or None, how). Colour comes free from `part_colour` names."""
    name = name.strip()
    if GENERIC.match(name):
        return None, None, "generic-class"
    if not map_categories:
        return None, None, "not-mapped"

    pc = PART_COLOUR.match(name)
    if pc:
        part, how = resolve(pc.group(1))
        return part, int(pc.group(2)), f"{how}+colour"

    m = PART_IN_NAME.search(name)
    if not m:
        return None, None, f"no-part-id-in:{name[:24]}"
    part, how = resolve(m.group(1))
    return part, None, how


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("coco", help="COCO annotations json")
    ap.add_argument("--images", default=".", help="folder the .truth.json files go next to")
    ap.add_argument("--map-categories", action="store_true",
                    help="try to read a part id out of each category name")
    ap.add_argument("--min-area", type=float, default=0.0)
    args = ap.parse_args()

    data = json.loads(pathlib.Path(args.coco).read_text())
    out_dir = pathlib.Path(args.images)
    out_dir.mkdir(parents=True, exist_ok=True)

    cats = {c["id"]: c.get("name", str(c["id"])) for c in data.get("categories", [])}
    resolved: dict[int, tuple[str | None, int | None, str]] = {
        cid: category_to_part_colour(name, args.map_categories) for cid, name in cats.items()
    }

    by_image: dict[int, list[dict]] = defaultdict(list)
    for a in data.get("annotations", []):
        if a.get("area", 1) < args.min_area:
            continue
        by_image[a["image_id"]].append(a)

    written = 0
    labelled = generic = 0
    for img in data.get("images", []):
        anns = by_image.get(img["id"], [])
        if not anns:
            continue
        pieces = []
        for a in anns:
            part, colour, _how = resolved.get(a.get("category_id"), (None, None, "unknown"))
            x, y, w, h = a.get("bbox", [0, 0, 0, 0])
            piece = {"part": part, "bbox": [int(x), int(y), int(w), int(h)]}
            if colour is not None:
                piece["color"] = colour
            pieces.append(piece)
            if part:
                labelled += 1
            else:
                generic += 1
        stem = pathlib.Path(img["file_name"]).stem
        (out_dir / f"{stem}.truth.json").write_text(json.dumps({
            "image": img["file_name"],
            "pieces": pieces,
            "note": f"imported from {pathlib.Path(args.coco).name}",
        }, indent=2) + "\n")
        written += 1

    print(f"categories: {len(cats)}")
    for cid, name in list(cats.items())[:10]:
        part, colour, how = resolved[cid]
        print(f"  {name[:28]:28s} -> {str(part):8s} colour={str(colour):4s} ({how})")
    print(f"\nwrote {written} .truth.json files to {out_dir}")
    print(f"pieces: {labelled} with a part id, {generic} class-agnostic")
    if generic and not labelled:
        print("\nThis dataset is CLASS-AGNOSTIC: it can score segmentation recall, not classification.")
        print("That is still the riskier half of our pipeline, so it is worth having.")


if __name__ == "__main__":
    main()
