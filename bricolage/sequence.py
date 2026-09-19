"""sequence() — turn a validated Build into buildable steps.

Bottom-up topological order + an INSERTION SWEEP (can a hand physically lower
the piece straight down into place? invariant: insertion is always straight
down, no Technic) + step grouping (1-6 pieces, same subassembly, same layer,
prefer identical parts). If Unbuildable ever fires on a VALID build, the
validator has a hole — that's a gift (build order note in llm.md).
"""
from __future__ import annotations
from model import occupancy


class Unbuildable(Exception):
    pass


def sequence(build):
    parts = list(build.parts)
    # bottom-up: lower y first, then stable by subassembly then id
    parts.sort(key=lambda p: (p.pos[1], p.sub, p.id))

    # insertion sweep: as we place each part, every cell in the column ABOVE
    # its footprint (up to the tallest thing already placed) must be empty,
    # or a hand can't lower it straight down.
    placed = []
    occ = {}
    max_y = max((p.top_layer() for p in parts), default=0)
    for p in parts:
        for (x, y, z) in p.bottom_cells():
            for yy in range(p.top_layer(), max_y + 1):
                if occ.get((x, yy, z)):
                    raise Unbuildable(
                        f"{p.id} ({p.part}) is trapped under {occ[(x, yy, z)]} "
                        f"at column ({x},{z}); cannot insert straight down.")
        for c in p.cells():
            occ[c] = p.id
        placed.append(p)

    return _group_steps(placed)


def _group_steps(parts):
    steps, cur = [], []

    def flush():
        if cur:
            steps.append({"n": len(steps) + 1, "sub": cur[0].sub,
                          "layer": cur[0].pos[1],
                          "parts": [p.id for p in cur],
                          "elements": _count(cur)})
            cur.clear()

    for p in parts:
        same = cur and cur[0].sub == p.sub and cur[0].pos[1] == p.pos[1]
        if not same or len(cur) >= 6:
            flush()
        cur.append(p)
    flush()

    # prefer grouping identical parts first within each step (readability)
    for s in steps:
        s["parts"].sort()
    return {"build_id": parts and parts[0].id.split(".")[0] or "bld",
            "n_steps": len(steps), "steps": steps}


def _count(parts):
    c = {}
    for p in parts:
        k = f"{p.part}:{p.color}"
        c[k] = c.get(k, 0) + 1
    return c
