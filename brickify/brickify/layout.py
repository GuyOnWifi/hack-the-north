"""Occupancy grid -> real parts.

Strategy (the way LEGO sculptures are actually built):
- Work in bands of 3 plates. Wherever a column is filled for the whole band,
  use bricks; the ragged edges left over become plates, layer by layer. That
  keeps part counts low without losing the silhouette.
- Alternate the long-axis direction and the scan direction every band/layer,
  so seams don't line up vertically and each part bridges the ones below it.
  That bonding is what makes the model hold together as one piece.
- Only merge cells of the same colour into one part.

Every cell is claimed by exactly one part, so overlaps are impossible by
construction; `check` still verifies it, plus connectivity.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .parts import BRICKS, PLATES, TILES, Part


@dataclass
class Placed:
    part: Part
    x: int  # min corner, studs
    y: int  # bottom layer, plates
    z: int
    along_x: bool  # part's long axis runs along world X
    colour: int  # LDraw colour code

    @property
    def sx(self):
        return self.part.length if self.along_x else self.part.width

    @property
    def sz(self):
        return self.part.width if self.along_x else self.part.length

    def cells(self):
        for dx in range(self.sx):
            for dz in range(self.sz):
                yield self.x + dx, self.z + dz


@dataclass
class Layout:
    parts: list[Placed] = field(default_factory=list)
    shape: tuple[int, int, int] = (0, 0, 0)


def _fits(free, colour, cx, cz, sx, sz, want):
    X, Z = free.shape
    if cx + sx > X or cz + sz > Z:
        return False
    block = free[cx : cx + sx, cz : cz + sz]
    if not block.all():
        return False
    return (colour[cx : cx + sx, cz : cz + sz] == want).all()


def _tile_region(region, colour, catalog: list[Part], parity: int):
    """Greedy tiling of a 2D region (x, z) with the catalog, largest parts first.
    `parity` flips both the preferred orientation and the scan direction."""
    free = region.copy()
    out = []
    X, Z = free.shape
    xs = range(X) if parity % 2 == 0 else range(X - 1, -1, -1)
    zs = list(range(Z)) if (parity // 2) % 2 == 0 else list(range(Z - 1, -1, -1))
    prefer_x = parity % 2 == 0
    for x in xs:
        for z in zs:
            if not free[x, z]:
                continue
            want = colour[x, z]
            placed = False
            for part in catalog:
                for along_x in ((prefer_x, not prefer_x) if part.length != part.width else (True,)):
                    sx = part.length if along_x else part.width
                    sz = part.width if along_x else part.length
                    # anchor the part so this cell is its first cell in scan order
                    cx = x if parity % 2 == 0 else x - sx + 1
                    cz = z if (parity // 2) % 2 == 0 else z - sz + 1
                    if cx < 0 or cz < 0:
                        continue
                    if _fits(free, colour, cx, cz, sx, sz, want):
                        free[cx : cx + sx, cz : cz + sz] = False
                        out.append((part, cx, cz, along_x, int(want)))
                        placed = True
                        break
                if placed:
                    break
    return out


def default_plan(grid: np.ndarray) -> dict:
    """Tiling variant per band (bricks) and per layer (plates); 4 variants each."""
    Y = grid.shape[1]
    return {"band": [(b // 3) % 4 for b in range(0, Y, 3)], "layer": [(y + 1) % 4 for y in range(Y)]}


def build(grid: np.ndarray, colour_codes: np.ndarray | None = None, default_colour: int = 71, tiles: bool = True, plan: dict | None = None) -> Layout:
    """grid: bool (x, y, z) in stud/plate cells. colour_codes: int LDraw colour per cell."""
    X, Y, Z = grid.shape
    plan = plan or default_plan(grid)
    colours = colour_codes if colour_codes is not None else np.full(grid.shape, default_colour, dtype=int)
    layout = Layout(shape=grid.shape)
    claimed = np.zeros_like(grid)

    for band in range(0, Y, 3):
        layers = grid[:, band : band + 3, :]
        if layers.shape[1] == 3:
            full = layers.all(axis=1)
            same = (colours[:, band, :] == colours[:, band + 1, :]) & (colours[:, band + 1, :] == colours[:, band + 2, :])
            region = full & same
            for part, cx, cz, along_x, c in _tile_region(region, colours[:, band + 1, :], BRICKS, plan["band"][band // 3]):
                layout.parts.append(Placed(part, cx, band, cz, along_x, c))
                claimed[cx : cx + (part.length if along_x else part.width), band : band + 3, cz : cz + (part.width if along_x else part.length)] = True
        for y in range(band, min(band + 3, Y)):
            rest = grid[:, y, :] & ~claimed[:, y, :]
            for part, cx, cz, along_x, c in _tile_region(rest, colours[:, y, :], PLATES, plan["layer"][y]):
                layout.parts.append(Placed(part, cx, y, cz, along_x, c))
                claimed[cx : cx + (part.length if along_x else part.width), y, cz : cz + (part.width if along_x else part.length)] = True

    if tiles:
        _smooth_tops(layout, grid)
    return layout


def _smooth_tops(layout: Layout, grid: np.ndarray):
    """Plates with nothing on top of any of their cells become tiles: exposed
    studs on a sloping surface are what make sculptures look like blobs."""
    Y = grid.shape[1]
    for p in layout.parts:
        if p.part.height != 1:
            continue
        key = (p.part.length, p.part.width)
        if key not in TILES:
            continue
        top = p.y + 1
        if top < Y and any(grid[cx, top, cz] for cx, cz in p.cells()):
            continue
        p.part = TILES[key]


def check(layout: Layout):
    """Overlaps (must be 0 by construction) and connectivity: parts connect
    when one sits directly on another with overlapping footprints."""
    owner = {}
    overlaps = 0
    for i, p in enumerate(layout.parts):
        for cx, cz in p.cells():
            for y in range(p.y, p.y + p.part.height):
                k = (cx, y, cz)
                if k in owner:
                    overlaps += 1
                owner[k] = i

    parent = list(range(len(layout.parts)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, p in enumerate(layout.parts):
        top = p.y + p.part.height
        if not p.part.studs:
            continue  # nothing can clutch a tile from above
        for cx, cz in p.cells():
            j = owner.get((cx, top, cz))
            if j is not None:
                parent[find(i)] = find(j)

    groups: dict[int, int] = {}
    for i in range(len(layout.parts)):
        r = find(i)
        groups[r] = groups.get(r, 0) + 1
    sizes = sorted(groups.values(), reverse=True)
    return {
        "parts": len(layout.parts),
        "overlaps": overlaps,
        "components": len(sizes),
        "largest_component": sizes[0] if sizes else 0,
        "loose_parts": sum(sizes[1:]),
    }


def keep_main_body(grid: np.ndarray) -> np.ndarray:
    """Drop voxel specks that don't touch the main body (face-connected); no
    brick layout can attach something that isn't connected to begin with."""
    from scipy import ndimage

    labels, n = ndimage.label(grid)
    if n <= 1:
        return grid
    sizes = ndimage.sum(grid, labels, range(1, n + 1))
    return labels == (int(np.argmax(sizes)) + 1)


def loose_layers(layout: Layout) -> set[int]:
    """Bottom layers of every part that isn't in the largest connected group."""
    owner = {}
    for i, p in enumerate(layout.parts):
        for cx, cz in p.cells():
            for y in range(p.y, p.y + p.part.height):
                owner[(cx, y, cz)] = i
    parent = list(range(len(layout.parts)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, p in enumerate(layout.parts):
        if not p.part.studs:
            continue
        for cx, cz in p.cells():
            j = owner.get((cx, p.y + p.part.height, cz))
            if j is not None:
                parent[find(i)] = find(j)
    counts: dict[int, int] = {}
    for i in range(len(layout.parts)):
        counts[find(i)] = counts.get(find(i), 0) + 1
    main = max(counts, key=counts.get) if counts else None
    return {p.y for i, p in enumerate(layout.parts) if find(i) != main}


def optimise(grid: np.ndarray, colour_codes=None, default_colour: int = 71, tiles: bool = True, passes: int = 3) -> Layout:
    """Coordinate descent over the tiling plan: for every band/layer that still
    has loose parts, try each tiling variant and keep the one that leaves the
    fewest loose parts. Layouts take milliseconds, so this is cheap."""
    plan = default_plan(grid)

    def score(p):
        lay = build(grid, colour_codes, default_colour, tiles, p)
        r = check(lay)
        return (r["loose_parts"], r["parts"]), lay

    best, lay = score(plan)
    for _ in range(passes):
        improved = False
        for y in sorted(loose_layers(lay)):
            for key, idx in (("layer", y), ("band", y // 3)):
                current = plan[key][idx]
                for variant in range(4):
                    if variant == current:
                        continue
                    trial = {"band": list(plan["band"]), "layer": list(plan["layer"])}
                    trial[key][idx] = variant
                    s, l = score(trial)
                    if s < best:
                        best, lay, plan, improved = s, l, trial, True
                        current = variant
        if not improved or best[0] == 0:
            break
    return lay
