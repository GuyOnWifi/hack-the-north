"""The BrickGPT text grammar <-> our grid. A build is a list of bricks, each
`hxw (x,y,z)`: an h-by-w footprint at grid position (x,y,z), one brick tall,
z = height layer (20x20x20 world, à la BrickGPT / StableText2Brick).

This is the language the LLM speaks; we lint it, physics-check it, and convert
it to a Lane-B Build (and thence to LDraw). Fewer tokens than raw LDraw, and it
carries dimensions so we can validate every placement.
"""
from __future__ import annotations
import re
from model import Part, Build

GRID = 20                       # 20x20x20 world
BRICK_H = 3                     # one grid layer = one brick = 3 plates in Lane B

# (h,w) footprint -> LDraw part. Canonical parts store the min-dim first.
_PARTS = {(1, 1): "3005", (1, 2): "3004", (1, 3): "3622", (1, 4): "3010",
          (1, 6): "3009", (1, 8): "3008", (2, 2): "3003", (2, 3): "3002",
          (2, 4): "3001", (2, 6): "2456", (2, 8): "3007"}


def part_for(h, w):
    """Return (ldraw_part, rot) for an h x w footprint, or None if unsupported."""
    if (h, w) in _PARTS:
        return _PARTS[(h, w)], 0
    if (w, h) in _PARTS:
        return _PARTS[(w, h)], 90
    return None


_LINE = re.compile(r"(\d+)\s*x\s*(\d+)\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\)")


def parse(text):
    """Text -> list of (h, w, x, y, z) tuples. Tolerates prose around the lines."""
    out = []
    for m in _LINE.finditer(text):
        out.append(tuple(int(v) for v in m.groups()))
    return out


def cells(h, w, x, y, z):
    """The grid cells (footprint x layer) an h x w brick at (x,y,z) fills."""
    return {(x + i, y + j, z) for i in range(h) for j in range(w)}


def lint(items):
    """Structural lint of a brick list. Returns (kept, issues). Drops bricks
    that are out of bounds / unknown size / collide — the LLM's mistakes."""
    kept, issues, occ = [], [], {}
    for idx, (h, w, x, y, z) in enumerate(items):
        if not part_for(h, w):
            issues.append({"i": idx, "code": "UNKNOWN_PART", "why": f"no {h}x{w} brick"})
            continue
        if not (0 <= x and x + h <= GRID and 0 <= y and y + w <= GRID and 0 <= z < GRID):
            issues.append({"i": idx, "code": "OUT_OF_BOUNDS", "why": f"{h}x{w} @({x},{y},{z})"})
            continue
        cs = cells(h, w, x, y, z)
        hit = cs & occ.keys()
        if hit:
            issues.append({"i": idx, "code": "COLLISION",
                           "why": f"{h}x{w} @({x},{y},{z}) overlaps {occ[min(hit)]}"})
            continue
        for c in cs:
            occ[c] = idx
        kept.append((h, w, x, y, z))
    return kept, issues


def to_build(items, name="Model", color=4, colors=None):
    """Brick list -> Lane B Build on the plate grid (y up = layer*3). `colors`,
    if given, is a per-index colour override list."""
    parts = []
    for i, (h, w, x, y, z) in enumerate(items):
        pr = part_for(h, w)
        if not pr:
            continue
        part, rot = pr
        c = colors[i] if colors and i < len(colors) else color
        parts.append(Part(f"p{i}", part, c, (x, z * BRICK_H, y), rot, "hull"))
    return Build("bld", 0, name, tuple(parts), (), {"backend": "harness",
                 "bricks": items})


def from_build(build):
    """Lane B Build -> brick list text (round-trip / LLM context)."""
    from meta import PART_META
    lines = []
    for p in build.parts:
        m = PART_META.get(p.part, {})
        dx, dz = m.get("dx", 1), m.get("dz", 1)
        h, w = (dz, dx) if p.rot in (90, 270) else (dx, dz)
        x, yl, z = p.pos
        lines.append(f"{h}x{w} ({x},{z},{yl // BRICK_H})")
    return "\n".join(lines)
