#!/usr/bin/env python3
"""End-to-end demo: inventory -> composition -> validated build -> manual steps -> .ldr

    python scripts/demo.py
    python scripts/demo.py --scarce     # same request, a bin that cannot afford it
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core import meta
from core.compose import Composition, compose
from core.ldraw import to_ldraw
from core.model import Inventory
from core.sequence import sequence

RICH = [("3001", 4, 8), ("3003", 4, 10), ("3002", 4, 4), ("2456", 15, 3), ("3007", 0, 2),
        ("3006", 4, 1), ("3004", 4, 12), ("3005", 4, 14), ("3010", 4, 6), ("3622", 15, 5),
        ("3020", 15, 7), ("3022", 4, 9), ("3021", 0, 4), ("3795", 15, 3), ("3034", 4, 2),
        ("3023b", 4, 15), ("3024", 4, 18), ("3623", 15, 6), ("3710", 4, 5), ("3460", 15, 2),
        ("3069b", 4, 6), ("3070b", 15, 8)]
SCARCE = [("3024", 4, 6), ("3023b", 4, 4), ("3005", 4, 3)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scarce", action="store_true")
    ap.add_argument("-o", "--out", default="rover.ldr")
    args = ap.parse_args()

    inv = Inventory.from_pairs(SCARCE if args.scarce else RICH)
    print(f"bin: {inv.total} pieces across {len(inv.items)} part/colour combinations\n")

    build, report, notes = compose(Composition("chassis", [
        {"id": "chassis", "gen": "chassis", "args": {"length": 10, "width": 4}, "color": 4},
        {"id": "cabin", "gen": "cabin", "attach_to": "chassis", "at": "top_rear",
         "args": {"length": 4, "width": 4, "height": 6}, "color": 15},
    ]), inv, name="Desk Rover")

    for n in notes:
        print(f"  · {n}")
    print(f"\nvalid: {report.ok}   {report.stats}")
    for e in report.errors:
        print(f"  ERROR   {e.code}: {e.human}")
    for w in report.warnings:
        print(f"  warning {w.code}: {w.human}")

    if not build.parts:
        print("\nNothing could be built from this bin -- which is the correct answer, not a crash.")
        return

    steps = sequence(build)
    print(f"\n{len(steps)} steps:")
    for i, group in enumerate(steps, 1):
        counts: dict[tuple[str, int], int] = {}
        for p in group:
            counts[(p.part, p.color)] = counts.get((p.part, p.color), 0) + 1
        items = ", ".join(f"{n}x {meta.get(pt).name}" for (pt, _c), n in sorted(counts.items()))
        print(f"  {i:2d}. [{group[0].sub}] {items}")

    pathlib.Path(args.out).write_text(to_ldraw(build, steps))
    print(f"\nwrote {args.out} -- open it in LeoCAD, BrickLink Studio, or the three.js LDrawLoader")


if __name__ == "__main__":
    main()
