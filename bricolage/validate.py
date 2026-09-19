"""validate() — THE LAW (invariant #2, decision D3). Ordinary code, not a
model. Every mutation passes through here. Returns a structured Report whose
`human` strings are BOTH user-facing copy AND the repair prompt text.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from model import occupancy
from meta import PART_META, COLOR_NAME
import stability


@dataclass
class Report:
    ok: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def as_dict(self):
        return {"ok": self.ok, "errors": self.errors,
                "warnings": self.warnings, "stats": self.stats}


def _elem(part, color):
    name = PART_META.get(part, {}).get("name", part)
    return f"{name} in {COLOR_NAME.get(color, color)}"


def validate(build, inventory=None, physics=True):
    parts = build.parts
    errors, warnings = [], []

    # ---- 1. overlap ----------------------------------------------------
    occ, clashes = occupancy(parts)
    seen = set()
    for a, b, cell in clashes:
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        errors.append({"code": "OVERLAP", "parts": [a, b],
                       "human": f"Two parts occupy the same space at {cell}."})

    # ---- 2+3. connectivity & support (per connected component) --------
    # Parts connect when one rests directly on the other (vertical adjacency /
    # a stud->anti-stud interface). Support is a property of the COMPONENT, not
    # the part: a brick held by studs to a grounded assembly is not floating,
    # even if nothing sits directly beneath that individual brick. The ground
    # is the build's lowest layer, so wheels/skids under a chassis are grounded.
    ground_y = min((p.pos[1] for p in parts), default=0)
    by_id = {p.id: p for p in parts}
    adj = {p.id: set() for p in parts}
    for p in parts:
        for (x, y, z) in p.cells():
            up = (x, y + 1, z)
            if up in occ and occ[up] != p.id:
                adj[p.id].add(occ[up]); adj[occ[up]].add(p.id)

    comp = _components(adj) if parts else []
    grounded = [c for c in comp
                if any(by_id[i].pos[1] == ground_y for i in c)]
    floating = [c for c in comp if c not in grounded]

    for c in floating:
        # a whole component hovering above the floor with a gap beneath it
        cmin = min(by_id[i].pos[1] for i in c)
        errors.append({"code": "FLOATING", "parts": list(c),
                       "human": f"A group of {len(c)} part(s) floats in mid-air "
                                f"(lowest at layer {cmin}, nothing beneath it)."})

    if len(comp) > 1:
        comp.sort(key=len, reverse=True)
        orphan_ids = [i for c in comp[1:] for i in c]
        errors.append({"code": "DISCONNECTED", "parts": orphan_ids,
                       "human": f"The build is in {len(comp)} separate pieces; "
                                f"{len(orphan_ids)} part(s) don't connect to the "
                                f"main body."})

    # ---- 4. inventory (invariant #10: user data is truth) -------------
    stats_remaining = None
    if inventory is not None:
        need = {}
        for p in parts:
            need[(p.part, p.color)] = need.get((p.part, p.color), 0) + 1
        remaining = dict(inventory.counts)
        for (part, color), qty in sorted(need.items()):
            have = inventory.have(part, color)
            remaining[(part, color)] = have - qty
            if qty > have:
                errors.append({"code": "OUT_OF_BUDGET", "parts": [],
                               "element": [part, color], "short": qty - have,
                               "human": f"Needs {qty}x {_elem(part, color)}; "
                                        f"you have {have}."})
        stats_remaining = sum(v for v in remaining.values() if v > 0)

    # ---- 5. physics: does it actually stand up? -----------------------
    # only meaningful once the structure is geometrically sound (connected, no
    # floating) — otherwise the mass model is nonsense.
    if physics and not errors:
        for f in stability.analyze(parts):
            errors.append({"code": f.code, "parts": f.parts, "human": f.human})

    # ---- warnings (advisory) ------------------------------------------
    _bond_warnings(parts, warnings)

    stats = {"parts": len(parts),
             "studs_used": sum(p.footprint()[0] * p.footprint()[1] for p in parts),
             "subs": len(build.subs)}
    if stats_remaining is not None:
        stats["inventory_remaining"] = stats_remaining

    return Report(ok=not errors, errors=errors, warnings=warnings, stats=stats)


def _components(adj):
    seen, out = set(), []
    for node in adj:
        if node in seen:
            continue
        stack, comp = [node], []
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n); comp.append(n)
            stack.extend(adj[n] - seen)
        out.append(comp)
    return out


def _bond_warnings(parts, warnings):
    """Aligned vertical seams => the model splits. Detect stacked parts whose
    left edges align across a layer boundary (weak masonry bond)."""
    edges_by_layer = {}
    for p in parts:
        edges_by_layer.setdefault(p.pos[1], set()).add((p.pos[0], p.pos[2]))
    layers = sorted(edges_by_layer)
    aligned = 0
    for a, b in zip(layers, layers[1:]):
        aligned += len(edges_by_layer[a] & edges_by_layer[b])
    if aligned > max(4, len(parts) // 3):
        warnings.append({"code": "WEAK_BOND", "sub": None,
                         "human": "Many vertical seams line up; staggering the "
                                  "bricks would make it much stronger."})
