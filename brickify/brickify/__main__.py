"""python -m brickify MESH [--length 32] [--up y|z] [--colour 71] [--solid] [-o out.ldr]"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import layout as L
from .ldraw import to_ldr
from .voxelize import load, voxelize


def main():
    ap = argparse.ArgumentParser(prog="brickify")
    ap.add_argument("mesh")
    ap.add_argument("--length", type=int, default=32, help="longest horizontal side in studs")
    ap.add_argument("--up", default="y", choices=["y", "z"])
    ap.add_argument("--colour", type=int, default=71, help="LDraw colour code (71 = light bluish grey)")
    ap.add_argument("--solid", action="store_true", help="don't hollow the interior")
    ap.add_argument("--no-tiles", action="store_true")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()

    t0 = time.perf_counter()
    mesh = load(a.mesh, up=a.up)
    grid, _ = voxelize(mesh, a.length, shell=None if a.solid else 2)
    t1 = time.perf_counter()
    grid = L.keep_main_body(grid)
    lay = L.optimise(grid, default_colour=a.colour, tiles=not a.no_tiles)
    t2 = time.perf_counter()
    report = L.check(lay)
    report.update(grid=list(grid.shape), cells=int(grid.sum()), voxelize_s=round(t1 - t0, 2), layout_s=round(t2 - t1, 2))
    out = Path(a.out or Path(a.mesh).with_suffix(".ldr").name)
    out.write_text(to_ldr(lay, out.stem))
    print(json.dumps(report))
    print(f"wrote {out}")


def brief_main(path, out):
    from .assembly import assemble, to_ldr as brief_ldr
    from .check import check_world, resolve

    brief = json.loads(Path(path).read_text())
    t0 = time.perf_counter()
    parts = resolve(assemble(brief))
    report = check_world(parts)
    report["build_s"] = round(time.perf_counter() - t0, 2)
    Path(out).write_text(brief_ldr(parts, brief["name"]))
    print(json.dumps(report))


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
        brief_main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else Path(sys.argv[1]).with_suffix(".ldr").name)
    else:
        main()
