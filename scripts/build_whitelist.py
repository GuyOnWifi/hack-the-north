#!/usr/bin/env python3
"""Derive the placeable-part whitelist from the official LDraw catalog + bricknet metadata.

Derived, not invented. The result is defensible in one sentence: "every common Brick, Plate,
Tile and Slope in the official LDraw library that sits on a stud grid and that we have
connector data for" -- rather than 200 part numbers somebody typed from memory.

Usage:  python scripts/build_whitelist.py [--limit 250]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import re
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core import meta

CATALOG_URL = "https://library.ldraw.org/library.csv"
CACHE = pathlib.Path(__file__).resolve().parents[1] / "data" / "library.csv"
KEEP_CATEGORIES = {"Brick", "Plate", "Tile", "Slope"}

# Printed/patterned/sticker variants: 3001p01, 3007d01, 973pb0123 ... we want the plain moulds.
DECORATED = re.compile(r"^\d+[a-z]?(p|d|c|pb|ps)\w*$", re.I)

# The plain rectangular moulds -- "brick 2x4", "plate 1x2", "tile 2x2 with groove",
# "slope brick 45 2x1". Anything with a qualifier ("with hook holder", "corner", "double
# concave") is a specialist part that our box-shaped occupancy model would describe badly.
PLAIN = re.compile(
    r"^(brick|plate|tile)\s+\d+\s*x\s*\d+(\s+with groove)?$"
    r"|^slope brick 45\s+\d+\s*x\s*\d+$",
    re.I,
)


def load_catalog_rows() -> list[dict]:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        print(f"fetching {CATALOG_URL} ...")
        # library.ldraw.org 403s urllib's default User-Agent. Same wall you will hit on
        # rebrickable.com/downloads -- if a fetch fails, download it in a browser and drop the
        # file at data/library.csv; everything downstream reads the cache.
        req = urllib.request.Request(CATALOG_URL, headers={
            "User-Agent": "Bricolage/0.1 (hackathon project; +https://github.com/)",
            "Accept": "text/csv,*/*",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                CACHE.write_bytes(r.read())
        except Exception as exc:
            raise SystemExit(
                f"could not fetch {CATALOG_URL} ({exc}).\n"
                f"Open it in a browser and save it to {CACHE}, then re-run."
            ) from None
    text = CACHE.read_text(encoding="utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=250)
    ap.add_argument("--max-studs", type=int, default=8)
    args = ap.parse_args()

    rows = load_catalog_rows()
    cat = meta.catalog()
    picked: list[dict] = []
    skipped = {"category": 0, "no_metadata": 0, "decorated": 0, "too_big": 0}

    for row in rows:
        fname = (row.get("part_number") or "").strip()
        category = (row.get("category") or "").strip().strip('"')
        if category not in KEEP_CATEGORIES:
            skipped["category"] += 1
            continue
        stem = fname[:-4] if fname.endswith(".dat") else fname
        if DECORATED.match(stem):
            skipped["decorated"] += 1
            continue
        m = cat.get(stem)
        if m is None:
            skipped["no_metadata"] += 1
            continue
        if max(m.w, m.d) > args.max_studs or m.h > 3:
            skipped["too_big"] += 1
            continue
        picked.append({
            "plain": bool(PLAIN.match(m.name)),
            "part": stem,
            "name": m.name,
            "category": category,
            "w": m.w, "d": m.d, "h": m.h,
            "studs": len(m.studs),
            "antistuds": len(m.antistuds),
            "tile": m.is_tile,
        })

    # Plain moulds first, then by footprint area. Without Rebrickable's frequency table (its
    # downloads page 403s scripted fetches) "is this a plain rectangular mould" is the best
    # available proxy for "is this common", and it is the right filter regardless: our
    # occupancy model is a box, so box-shaped parts are exactly what it describes correctly.
    picked.sort(key=lambda p: (0 if PLAIN.match(p["name"]) else 1, p["w"] * p["d"], p["part"]))
    picked = picked[: args.limit]

    out = pathlib.Path(__file__).resolve().parents[1] / "data" / "core_parts.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"parts": picked}, indent=2) + "\n")

    by_cat: dict[str, int] = {}
    for p in picked:
        by_cat[p["category"]] = by_cat.get(p["category"], 0) + 1
    print(f"catalog rows: {len(rows)}   skipped: {skipped}")
    print(f"whitelist: {len(picked)} parts  {by_cat}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
