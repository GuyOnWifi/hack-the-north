"""Assemble a tree of generator calls into a validated Build.

This is what the LLM actually produces: a COMPOSITION. Never coordinates.

    {"root": "chassis",
     "nodes": [{"id": "chassis", "gen": "chassis", "args": {"length": 10, "width": 4}},
               {"id": "cabin", "gen": "cabin", "attach_to": "chassis", "at": "top_rear"}]}

Invalid generator names or arguments are rejected by the schema, not by producing a broken
model, so the worst case is a retry rather than a build that cannot exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from .alloc import Allocator
from .generators import generate
from .model import Build, Inventory, Placed, SubAssembly
from .validate import Report, validate

# Where on the parent a child lands, as a fraction of the parent's footprint.
ANCHORS = {
    "top_front":  (0.0, 0.0),
    "top_rear":   (1.0, 0.0),
    "top_centre": (0.5, 0.0),
    "top_left":   (0.5, 0.0),
    "top_right":  (0.5, 1.0),
}


@dataclass
class Composition:
    root: str
    nodes: list[dict]


def _span(parts: list[Placed]) -> tuple[int, int, int, int, int]:
    from . import meta as meta_mod
    if not parts:
        # A generator that degraded all the way to nothing. Callers treat an empty span as
        # "occupies no space", which is true, rather than crashing on min() of an empty list.
        return (0, 0, 0, 0, 0)
    xs, zs, tops = [], [], []
    for p in parts:
        m = meta_mod.get(p.part)
        w, d = m.footprint(p.rot)
        xs += [p.x, p.x + w]
        zs += [p.z, p.z + d]
        tops.append(p.y + m.h)
    return min(xs), max(xs), min(zs), max(zs), max(tops)


def compose(comp: Composition, inventory: Inventory, color: int = 4,
            name: str = "Build", build_id: str = "bld_local") -> tuple[Build, Report, list[str]]:
    """Build -> validate. Returns (build, report, notes). Never raises on a bad node."""
    # Deterministic part ids: same composition + inventory -> identical Build, ids included.
    # The generators number parts from a module counter, so it has to be restarted per compose.
    from .generators.basic import reset_ids
    reset_ids()

    alloc = Allocator(inventory)
    placed: list[Placed] = []
    subs: list[SubAssembly] = []
    frames: dict[str, tuple[int, int, int, int, int]] = {}
    attaches: dict[str, list] = {}
    occupied: set[tuple[int, int, int]] = set()
    notes: list[str] = []

    order = _resolve_order(comp)
    for node in order:
        nid = node["id"]
        gen = node.get("gen", nid)
        args = dict(node.get("args") or {})
        node_color = int(node.get("color", color))
        try:
            res = generate(gen, alloc, node_color, sub=nid, **args)
        except (KeyError, TypeError) as exc:
            notes.append(f"{nid}: rejected ({exc})")
            continue
        if res is None or not res.parts:
            notes.append(f"{nid}: not enough bricks for {gen}({args}) -- skipped")
            continue

        parent = node.get("attach_to")
        offset = (0, 0, 0)
        if parent and parent in attaches:
            fx, fz = ANCHORS.get(node.get("at", "top_centre"), (0.5, 0.0))
            offset, why = _place_on(res.parts, attaches[parent], occupied, fx, fz)
            if offset is None:
                notes.append(f"{nid}: {why} -- skipped")
                continue
            if why:
                notes.append(f"{nid}: {why}")
        elif parent:
            notes.append(f"{nid}: attach_to '{parent}' is not a known node -- placed at origin")

        res = res.offset(*offset, nid)
        for cell in _cells_of(res.parts):
            occupied.add(cell)
        placed += res.parts
        subs.append(SubAssembly(nid, parent, tuple(res.attach)))
        frames[nid] = _span(res.parts)
        if res.attach:
            attaches[nid] = res.attach
        if res.note:
            notes.append(f"{nid}: {res.note}")

    build = Build(build_id, name, tuple(placed), tuple(subs), version=1,
                  provenance={"backend": "compose", "nodes": [n["id"] for n in order]})
    return build, validate(build, inventory), notes


def _cells_of(parts: list[Placed]) -> set[tuple[int, int, int]]:
    from . import meta as meta_mod
    out = set()
    for p in parts:
        m = meta_mod.get(p.part)
        for cx, cz in m.cells(p.rot):
            for k in range(m.h):
                out.add((p.x + cx, p.y + k, p.z + cz))
    return out


def _place_on(parts, attach_points, occupied, fx, fz):
    """Try the parent's attach surfaces, highest first, and take the first that does not collide.

    A generator may expose several surfaces at different heights (a chassis offers its floor AND
    its spine top). Picking the one with the most studs puts a cabin inside the spine; picking
    the highest blindly ignores wider lower surfaces. So: try them, test, take the first that fits.
    """
    from . import meta as meta_mod
    cw, cd = _width(parts), _depth(parts)
    base = _cells_of(parts)
    bx = min(c[0] for c in base); bz = min(c[2] for c in base); by = min(c[1] for c in base)
    tried = []
    fallbacks = []
    for ap in sorted(attach_points, key=lambda a: -a.at[1]):
        if not ap.studs:
            continue
        ax0 = min(s[0] for s in ap.studs); ax1 = max(s[0] for s in ap.studs) + 1
        az0 = min(s[1] for s in ap.studs); az1 = max(s[1] for s in ap.studs) + 1
        dx = ax0 + max(0, int((ax1 - ax0 - cw) * fx)) - bx
        dz = az0 + max(0, int((az1 - az0 - cd) * fz)) - bz
        dy = ap.at[1] - by
        moved = {(x + dx, y + dy, z + dz) for (x, y, z) in base}
        if moved & occupied:
            tried.append(f"level {ap.at[1]} was occupied")
            continue
        seated = {(x + dx, z + dz) for (x, y, z) in base if y == by}
        studs = set(ap.studs)
        unsupported = seated - studs
        if unsupported:
            # Partially seated means the overhanging parts float. Remember it as a fallback and
            # keep looking for a surface that fully supports the child.
            fallbacks.append(((dx, dy, dz), len(unsupported), ap.at[1],
                              f"{len(unsupported)} of {len(seated)} footprint cells overhang the "
                              f"{ax1-ax0}x{az1-az0} surface at level {ap.at[1]}"))
            tried.append(f"level {ap.at[1]} supports only {len(seated)-len(unsupported)}/{len(seated)}")
            continue
        return (dx, dy, dz), ""
    if fallbacks:
        fallbacks.sort(key=lambda f: (f[1], -f[2]))
        off, _, _, why = fallbacks[0]
        return off, why + " -- it will need support"
    return None, "no attach surface fits (" + "; ".join(tried) + ")" if tried else "no attach surface"


def _width(parts: list[Placed]) -> int:
    x0, x1, _, _, _ = _span(parts)
    return x1 - x0


def _depth(parts: list[Placed]) -> int:
    _, _, z0, z1, _ = _span(parts)
    return z1 - z0


def _resolve_order(comp: Composition) -> list[dict]:
    """Parents before children; unreferenced nodes keep their given order."""
    by_id = {n["id"]: n for n in comp.nodes}
    out: list[dict] = []
    seen: set[str] = set()

    def visit(nid: str, guard: frozenset[str] = frozenset()):
        if nid in seen or nid not in by_id or nid in guard:
            return
        node = by_id[nid]
        parent = node.get("attach_to")
        if parent:
            visit(parent, guard | {nid})
        seen.add(nid)
        out.append(node)

    visit(comp.root)
    for n in comp.nodes:
        visit(n["id"])
    return out
