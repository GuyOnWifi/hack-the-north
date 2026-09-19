"""The `sculpt` backend. The LLM emits a stack of solid layer footprints (a
CHOICE of shape — still no coordinates): each layer is (width, depth), centred.
Our code tiles every layer with the masonry bond and stacks them, so the result
is connected and stands up by construction. Thin organic SHELLS are out of
scope (anti-goal: we're not competing on render fidelity) — sculpt does solid,
stepped voxel forms. Real Opus streams the layer list (client.messages.stream).
"""
from __future__ import annotations
from model import Build, SubAssembly, Part
from generators import bonded

# each entry: list of (width, depth) footprints, bottom -> top, centred
SHAPES = {
    "pyramid": [(6, 6), (4, 4), (2, 2)],
    "tree":    [(2, 2), (6, 6), (4, 4), (2, 2)],
    "diamond": [(2, 2), (4, 4), (6, 6), (4, 4), (2, 2)],
    "tower":   [(2, 2)] * 5,
    # a heart approximated as a solid stepped form (no thin shell)
    "heart":   [(6, 6), (6, 4), (4, 2), (2, 2)],
}


SUPPORT = 71   # light gray for auto-generated support columns


def legalize_voxels(voxels, tape=None):
    """The SOLVER. Take an arbitrary target shape (a dict cell->colour) the LLM
    imagined and make it physically real: add support columns under any cell
    that would float, so nothing is left hanging. This is visible, non-trivial
    work — the agent 'noticing the petals would fall and propping them up'.
    Returns (cells, n_support)."""
    cells = dict(voxels)
    if not cells:
        return cells, 0
    ground = min(y for _, y, _ in cells)
    added = 0
    for (x, y, z), col in sorted(voxels.items()):
        yy = y - 1
        while yy >= ground and (x, yy, z) not in cells:
            cells[(x, yy, z)] = col        # column inherits the colour above it
            added += 1
            yy -= 1
    if tape and added:
        tape.emit("repair", "support",
                  f"solver: added {added} support brick(s) under overhangs so "
                  f"nothing floats", status="ok", ms=6)
    return cells, added


def tile_voxels(cells, tape=None):
    """Tile a voxel field (cell->colour) into real plates. Uses 2x2 plates where
    they fit (they span 4 cells and BOND them horizontally), then 1x2, then 1x1.
    The scan order alternates per layer so seams stagger -> upper plates bridge
    the seams below -> the whole mass is connected (real masonry bond)."""
    from model import Part
    parts, n = [], 0
    by_layer = {}
    for (x, y, z), col in cells.items():
        by_layer.setdefault(y, {})[(x, z)] = col

    for y in sorted(by_layer):
        occ = by_layer[y]
        used = set()
        phase = y % 2                 # offset the 2x2 grid on odd layers...

        def free(cs):
            return all(c in occ and c not in used for c in cs)

        # pass 1: place 2x2 plates on a parity-offset grid. Alternating the grid
        # per layer means a 2x2 above STRADDLES the seams of the layer below ->
        # the columns bond into one mass (real masonry bond, in 2D).
        for (x, z) in sorted(occ):
            if (x - phase) % 2 or (z - phase) % 2 or (x, z) in used:
                continue
            quad = [(x, z), (x + 1, z), (x, z + 1), (x + 1, z + 1)]
            if free(quad):
                parts.append(Part(f"v{n}", "3022", occ[(x, z)], (x, y, z), 0, "hull"))
                used |= set(quad); n += 1
        # pass 2: fill leftovers with 1x2 then 1x1
        for (x, z) in sorted(occ):
            if (x, z) in used:
                continue
            col = occ[(x, z)]
            if free([(x, z), (x, z + 1)]):
                parts.append(Part(f"v{n}", "3023", col, (x, y, z), 0, "hull")); used |= {(x, z), (x, z + 1)}
            elif free([(x, z), (x + 1, z)]):
                parts.append(Part(f"v{n}", "3023", col, (x, y, z), 90, "hull")); used |= {(x, z), (x + 1, z)}
            else:
                parts.append(Part(f"v{n}", "3024", col, (x, y, z), 0, "hull")); used.add((x, z))
            n += 1
        if tape:
            tape.emit("scribe", "tile", f"solver: tiled layer {y} ({len(occ)} cells)", ms=3)
    return parts


def build_voxels(voxels, name="Model", tape=None, seed=0, legalize=True, base=True):
    """arbitrary target shape -> legalised, tiled, connected Build. `base` mounts
    the shape on a bonded plate baseplate (a display stand): every cell then
    connects DOWN to the base, so even a FLAT silhouette (a heart, a letter) is
    one connected, stable mass — otherwise side-by-side plates in one layer don't
    bond and the shape falls apart."""
    from model import Build, SubAssembly, Part
    cells = legalize_voxels(voxels, tape)[0] if legalize else dict(voxels)
    parts = tile_voxels(cells, tape)

    if base and cells:
        xs = [x for (x, _, _) in cells]; zs = [z for (_, _, z) in cells]
        gy = min(y for (_, y, _) in cells)
        x0, z0 = min(xs) - 1, min(zs) - 1
        W, D = max(xs) - min(xs) + 3, max(zs) - min(zs) + 3
        for p in bonded(W, D, 0, 71, seed, plates=True, courses=2, sub="base"):
            parts.append(Part(p.id, p.part, p.color,
                              (p.pos[0] + x0, gy - 2 + p.pos[1], p.pos[2] + z0),
                              0, "base"))
        if tape:
            tape.emit("scribe", "base", "solver: mounted the shape on a baseplate "
                      "so it holds together and stands", ms=4)

    parts = [type(p)(f"p{i}", p.part, p.color, p.pos, p.rot, p.sub)
             for i, p in enumerate(parts)]
    sub = SubAssembly("hull", None, "sculpt", (), None, ())
    return Build(id="bld_sculpt", version=0, name=name, parts=tuple(parts),
                 subs=(sub,), provenance={"backend": "sculpt", "seed": seed})


def build_voxels_naive(voxels, name="Model", seed=0):
    """What you get if the model just PLACES what it imagined — one 1x1 plate per
    cell, no support legalisation, no bond. This is the 'LLM places bricks'
    baseline: overhangs float, the mass isn't connected, it can't be built. The
    contrast with build_voxels() is the whole thesis, made visible."""
    from model import Build, SubAssembly, Part
    parts = [Part(f"p{i}", "3024", col, (x, y, z), 0, "hull")
             for i, ((x, y, z), col) in enumerate(sorted(voxels.items()))]
    sub = SubAssembly("hull", None, "sculpt-naive", (), None, ())
    return Build(id="bld_naive", version=0, name=name, parts=tuple(parts),
                 subs=(sub,), provenance={"backend": "naive", "seed": seed})


def build_sculpt(noun, size=1.0, seed=0, color=4):
    layers = SHAPES.get(noun, SHAPES["pyramid"])
    base = max(w for w, _ in layers)
    parts, y, n = [], 0, 0
    for i, (w, d) in enumerate(layers):
        ox, oz = (base - w) // 2, (base - d) // 2      # centre each layer
        # 2 bonded courses per voxel layer => each layer is internally connected,
        # and each layer rests on the one below => the stack is one solid mass.
        for p in bonded(w, d, y, color, seed + i, plates=False, courses=2, sub="hull"):
            parts.append(Part(f"p{n}", p.part, p.color,
                              (p.pos[0] + ox, p.pos[1], p.pos[2] + oz), 0, "hull"))
            n += 1
        y += 6
    sub = SubAssembly("hull", None, "sculpt", (), None, ())
    return Build(id="bld_sculpt", version=0, name=noun.title(),
                 parts=tuple(parts), subs=(sub,),
                 provenance={"backend": "sculpt", "noun": noun, "seed": seed})
