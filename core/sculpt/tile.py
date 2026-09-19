"""Legalize a voxel shape into real bricks from a finite inventory.

A voxel grid is not a build. Turning one into a build is where the project's actual claim lives:
the parts used must be parts you own, so covering a layer is a packing problem against a *finite*
multiset, not against an infinite catalogue.

The method (docs/01-architecture.md 4.3): per layer, per same-colour connected region, greedily
place the largest whitelisted part that both fits and is still in stock; repeat with randomized
restarts; keep the best. Greedy + restarts is milliseconds and good enough. CP-SAT for an exact
minimum-piece tiling is a stretch goal, never a starting point.

"Best" is scored as coverage first, then structure, then piece count and seam stagger. Structure
has to be in there: fewer pieces alone would pick a tiling that is three loose planks over one
that is a single object.

Two details that are not decoration:

* **Seams stagger, and courses cross.** The scan origin flips on alternate layers so vertical
  joins do not line up between courses -- a wall whose seams line up splits in half when you
  pick it up, and the validator already warns about it (`WEAK_BOND`). Alternate layers also
  prefer the opposite rotation, which matters more than it looks: a layer of 2x6 plates all
  laid along x is six separate strips, and a second identical layer on top of it joins strip to
  strip and nothing to nothing. Turning every other course 90 degrees is what makes the stack
  one object instead of a pile of planks.
* **The budget is a restart COUNT, not a wall clock.** Invariant 5 wants every loop bounded;
  invariant 6 wants byte-identical output for a given seed. A time-based cut-off would satisfy
  the first and break the second, so the bound is counted work: `restarts` attempts over a grid
  whose size the parser already capped.

Degradation is honest. When the inventory runs out, cells are left uncovered and named in
`notes` -- the tiler never invents a part it does not own, because the only way it can obtain
one is `Allocator.take`, which fails when the bin is empty.
"""

from __future__ import annotations

import functools
import random
from dataclasses import dataclass, field

from .. import meta as meta_mod
from ..alloc import Allocator
from ..model import Build, Inventory, Placed, SubAssembly
from ..validate import Report, connections, validate
from .parse import LayerMap

# One voxel layer is one plate by default: plates give the finest shape resolution and every
# layer then sits directly on studs of the layer below. Bricks are offered because a tall solid
# shape built from plates costs three times the pieces for the same height.
UNIT_HEIGHT = {"plate": 1, "brick": 3}

_PARTS = {
    "plate": ("3460", "3666", "3710", "3623", "3023b", "3024",      # 1x8 .. 1x1
              "3832", "3034", "3795", "3020", "3021", "3022"),      # 2x10 .. 2x2
    "brick": ("3008", "3009", "3010", "3622", "3004", "3005",
              "3006", "3007", "2456", "3001", "3002", "3003"),
}

# Anything this big or bigger counts as a "large piece" when scoring a restart. Two studs by two
# is the smallest part that ties two rows together, which is what makes a layer hold itself.
LARGE_AREA = 4


@dataclass(frozen=True, slots=True)
class Candidate:
    """One whitelisted part at one rotation, as a footprint the scanner can try."""

    part: str
    rot: int
    w: int          # footprint along x, after rotation
    d: int          # footprint along z, after rotation

    @property
    def area(self) -> int:
        return self.w * self.d


@dataclass(frozen=True, slots=True)
class SculptResult:
    build: Build
    report: Report
    notes: tuple[str, ...] = ()
    uncovered: int = 0
    score: float = 0.0
    remaining: Inventory = field(default_factory=Inventory)


@functools.cache
def _candidates(unit: str, prefer_rot: int = 0) -> tuple[Candidate, ...]:
    """Whitelisted footprints, largest first, `prefer_rot` winning ties between rotations.

    Within one area, the wider part wins before the longer one: a 2x2 bridges two rows and a
    1x4 does not, and a layer built only of 1xN strips is a layer that falls apart in the hand.
    Ties finally break on part id, so the order is fixed for a given (unit, prefer_rot).
    """
    out: list[Candidate] = []
    for part in _PARTS[unit]:
        if not meta_mod.has(part):
            continue
        m = meta_mod.get(part)
        for rot in (0, 90):
            w, d = m.footprint(rot)
            if rot == 90 and (w, d) == m.footprint(0):
                continue                       # square part: one rotation is enough
            out.append(Candidate(part, rot, w, d))
    out.sort(key=lambda c: (-c.area, -min(c.w, c.d), -max(c.w, c.d),
                            0 if c.rot == prefer_rot else 1, c.part, c.rot))
    return tuple(out)


# ------------------------------------------------------------------ regions

def _regions(lm: LayerMap, y: int) -> list[tuple[int, list[tuple[int, int]]]]:
    """Same-colour 4-connected regions of one layer, in a fixed order.

    Regions are found per colour because a part has exactly one colour; a region that spans two
    colours would be tiled with parts that straddle the boundary and quietly repaint the shape.
    """
    cells = {(x, z): c for (x, z, c) in lm.layer_cells(y)}
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, list[tuple[int, int]]]] = []
    for key in sorted(cells):
        if key in seen:
            continue
        color = cells[key]
        stack, comp = [key], []
        seen.add(key)
        while stack:
            x, z = stack.pop()
            comp.append((x, z))
            for nb in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
                if nb not in seen and cells.get(nb) == color:
                    seen.add(nb)
                    stack.append(nb)
        out.append((color, sorted(comp)))
    return out


# ------------------------------------------------------------------ one attempt

@dataclass(frozen=True, slots=True)
class _Piece:
    y: int
    part: str
    rot: int
    x: int
    z: int
    color: int
    w: int
    d: int


def _tile_region(alloc: Allocator, cells: list[tuple[int, int]], color: int, y: int,
                 cands: tuple[Candidate, ...], flip_x: bool, flip_z: bool,
                 skip_chance: float, rng: random.Random) -> tuple[list[_Piece], list[tuple[int, int]]]:
    free = set(cells)
    order = sorted(cells, key=lambda c: (-c[1] if flip_z else c[1], -c[0] if flip_x else c[0]))
    pieces: list[_Piece] = []
    uncovered: list[tuple[int, int]] = []

    for cell in order:
        if cell not in free:
            continue
        cx, cz = cell
        placed = False
        for cand in cands:
            # The anchor is the corner the scan reaches first, so flipping the scan direction
            # genuinely moves where seams fall instead of just reordering identical work.
            x0 = cx - cand.w + 1 if flip_x else cx
            z0 = cz - cand.d + 1 if flip_z else cz
            span = [(x0 + dx, z0 + dz) for dx in range(cand.w) for dz in range(cand.d)]
            if not all(s in free for s in span):
                continue
            if skip_chance and cand.area > 1 and rng.random() < skip_chance:
                continue                       # deliberate imperfection: what makes restarts differ
            # take_color pools across colours and tells us which one it actually gave us.
            # A bare take() would hand out a blue brick and then record it as red, producing a
            # build that claims parts the bin does not own -- OUT_OF_BUDGET at validate() time.
            got = alloc.take_color(cand.part, color)
            if got is None:
                continue
            free.difference_update(span)
            pieces.append(_Piece(y, cand.part, cand.rot, x0, z0, got, cand.w, cand.d))
            placed = True
            break
        if not placed:
            free.discard(cell)
            uncovered.append(cell)
    return pieces, uncovered


def _attempt(lm: LayerMap, alloc: Allocator, unit: str, unit_h: int,
             rng: random.Random, randomize: bool) -> tuple[list[_Piece], list[tuple[int, int, int]]]:
    pieces: list[_Piece] = []
    uncovered: list[tuple[int, int, int]] = []
    for li in range(lm.height):
        # Draw the bits unconditionally so every restart consumes the stream the same way;
        # restart 0 ignores them and runs the canonical masonry offset.
        bits = (rng.getrandbits(1), rng.getrandbits(1), rng.getrandbits(1))
        odd = bool(li % 2)
        flip_x = odd ^ (bool(bits[0]) if randomize else False)
        flip_z = bool(bits[1]) if randomize else False
        prefer = 90 if odd ^ (bool(bits[2]) if randomize else False) else 0
        cands = _candidates(unit, prefer)
        skip = 0.15 if randomize else 0.0
        for color, cells in _regions(lm, li):
            p, u = _tile_region(alloc, cells, color, li * unit_h, cands, flip_x, flip_z, skip, rng)
            pieces += p
            uncovered += [(x, li, z) for (x, z) in u]
    return pieces, uncovered


# ------------------------------------------------------------------ scoring

def _structure(pieces: list[_Piece]) -> tuple[int, int]:
    """(number of connected components, pieces outside the largest one).

    Cheap enough to run on every restart, which is the point: without it the scorer happily
    prefers a nine-piece tiling that is three loose planks over an eleven-piece tiling that is
    one object, and the prune step then quietly throws two thirds of the model away.
    """
    if not pieces:
        return 0, 0
    courses = sorted({p.y for p in pieces})
    below_of = {b: a for a, b in zip(courses, courses[1:])}
    at: dict[tuple[int, int, int], int] = {}
    for i, p in enumerate(pieces):
        for dx in range(p.w):
            for dz in range(p.d):
                at[(p.y, p.x + dx, p.z + dz)] = i

    parent = list(range(len(pieces)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, p in enumerate(pieces):
        below = below_of.get(p.y)
        if below is None:
            continue
        for dx in range(p.w):
            for dz in range(p.d):
                j = at.get((below, p.x + dx, p.z + dz))
                if j is not None:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj

    sizes: dict[int, int] = {}
    for i in range(len(pieces)):
        r = find(i)
        sizes[r] = sizes.get(r, 0) + 1
    return len(sizes), len(pieces) - max(sizes.values())


def _score(pieces: list[_Piece], uncovered: int) -> float:
    """Bigger is better. Coverage dominates, then structure, then piece count and seams."""
    by_course: dict[int, dict[int, list[tuple[int, int]]]] = {}
    for p in pieces:
        rows = by_course.setdefault(p.y, {})
        for dz in range(p.d):
            rows.setdefault(p.z + dz, []).append((p.x, p.x + p.w))

    seams: dict[int, set[tuple[int, int]]] = {}
    for y, rows in by_course.items():
        s: set[tuple[int, int]] = set()
        for z, spans in rows.items():
            lo = min(a for a, _ in spans)
            hi = max(b for _, b in spans)
            for a, b in spans:
                # Only interior joins can split the model; the outer edge is not a seam.
                if lo < a < hi:
                    s.add((a, z))
                if lo < b < hi:
                    s.add((b, z))
        seams[y] = s

    courses = sorted(seams)
    aligned = sum(len(seams[a] & seams[b]) for a, b in zip(courses, courses[1:]))
    large = sum(1 for p in pieces if p.w * p.d >= LARGE_AREA)
    comps, orphans = _structure(pieces)
    return (-1000.0 * uncovered
            - 100.0 * max(0, comps - 1) - 25.0 * orphans
            - len(pieces) - 3.0 * aligned + 2.0 * large)


# ------------------------------------------------------------------ pruning

# A connectivity prune that would delete most of the model is not a repair, it is a cover-up.
# Past this fraction we keep everything and let the validator say DISCONNECTED out loud.
PRUNE_FLOOR = 0.5


def _prune(parts: list[Placed]) -> tuple[list[Placed], list[Placed]]:
    """Drop parts a degraded tiling left floating or orphaned. Returns (kept, dropped).

    A tiling that ran out of bricks can leave an island with nothing under it. Shipping that as
    a "build" is worse than shipping less of it, so we remove what cannot physically stay.

    Connectivity is pruned far more cautiously than support, because some shapes are honestly
    disconnected and no tiling fixes them: a one-layer mosaic is rows of plates lying side by
    side with no course above to tie them, so "keep the largest component" would return a single
    brick and call it ok. When the largest component is not most of the model we keep the whole
    thing and let `validate()` report DISCONNECTED -- which is true, and which rung 0 of the
    repair ladder knows how to act on.
    """
    kept = list(parts)
    dropped: list[Placed] = []
    while kept:
        conns = connections(Build("tmp", "tmp", tuple(kept)))
        supported = {u for _, u, _ in conns}
        floating = [p for p in kept if p.y > 0 and p.id not in supported]
        if not floating:
            break
        ids = {p.id for p in floating}
        dropped += floating
        kept = [p for p in kept if p.id not in ids]

    if not kept:
        return [], dropped

    adj: dict[str, set[str]] = {p.id: set() for p in kept}
    for a, b, _ in connections(Build("tmp", "tmp", tuple(kept))):
        adj[a].add(b)
        adj[b].add(a)
    seen: set[str] = set()
    comps: list[set[str]] = []
    for start in sorted(adj):
        if start in seen:
            continue
        stack, comp = [start], set()
        while stack:
            n = stack.pop()
            if n in comp:
                continue
            comp.add(n)
            seen.add(n)
            stack.extend(adj[n] - comp)
        comps.append(comp)
    comps.sort(key=lambda c: (-len(c), min(c)))
    best = comps[0]
    if len(best) < PRUNE_FLOOR * len(kept):
        return kept, dropped
    dropped += [p for p in kept if p.id not in best]
    return [p for p in kept if p.id in best], dropped


# ------------------------------------------------------------------ the entry point

def tile(lm: LayerMap, inventory: Inventory, *, seed: int = 0, restarts: int = 20,
         unit: str = "plate", sub: str = "sculpt", name: str = "Sculpt",
         build_id: str = "bld_sculpt", prune: bool = True) -> SculptResult:
    """Legalize `lm` into a validated Build using only bricks from `inventory`."""
    if unit not in UNIT_HEIGHT:
        raise ValueError(f"unit must be one of {sorted(UNIT_HEIGHT)}, not {unit!r}")
    unit_h = UNIT_HEIGHT[unit]
    restarts = max(1, int(restarts))

    best: tuple[tuple[float, int], list[_Piece], list, Allocator] | None = None
    for i in range(restarts):
        # A string seed keeps this reproducible across processes -- Python salts str hashing,
        # but random.Random(str) hashes the seed itself and is stable.
        rng = random.Random(f"{seed}:{i}")
        alloc = Allocator(inventory)
        pieces, uncovered = _attempt(lm, alloc, unit, unit_h, rng, randomize=i > 0)
        key = (_score(pieces, len(uncovered)), -i)   # ties go to the earliest restart
        if best is None or key > best[0]:
            best = (key, pieces, uncovered, alloc)

    key, pieces, uncovered, alloc = best
    notes: list[str] = []
    if uncovered:
        notes.append(
            f"{len(uncovered)} of {lm.filled} cells were left empty: the bin ran out of parts "
            f"in the colours the shape asks for. The model is the largest piece of that shape "
            f"you can actually build.")

    parts = [
        Placed(f"s{n:04d}", p.part, p.color, (p.x, p.y, p.z), p.rot, sub)
        for n, p in enumerate(sorted(pieces, key=lambda p: (p.y, p.z, p.x, p.part, p.rot)), 1)
    ]
    if prune and parts:
        parts, dropped = _prune(parts)
        for p in dropped:
            alloc.give_back(p.part, p.color)
        if dropped:
            notes.append(f"Removed {len(dropped)} of {len(dropped) + len(parts)} part(s) that "
                         f"the gaps left floating or detached from the main model.")

    build = Build(
        build_id, name, tuple(parts), (SubAssembly(sub, None, ()),),
        provenance={"backend": "sculpt", "seed": seed, "restarts": restarts, "unit": unit},
    )
    report = validate(build, inventory)
    if not report.ok:
        notes += [e.human for e in report.errors]
    return SculptResult(build, report, tuple(notes), len(uncovered), key[0],
                        Inventory(dict(alloc.remaining)))
