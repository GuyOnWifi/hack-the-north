"""Build brief -> assembled model.

A brief is a tree of *bodies*. Each body has its own stud grid and is built
from small stacked character grids (one per plate layer, bottom-up), which
the connectivity-first merge layout turns into real bricks and plates, then a
surfacing pass rounds its top edges with curved slopes. Bodies attach to each
other only through real connectors:

- side: a side-stud brick (87087 / 11211) in the parent; the child's studs
  point along the side stud (SNOT, "studs not on top").
- hinge: a hinge brick base (3937) in the parent; the child is built on the
  hinge top (3938) and pivots about the hinge axis by `angle` degrees.

Details (eyes, beak bars) are parts placed on those connectors. Nothing ever
takes a free world coordinate: every position comes from grid cells and
connector geometry.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import kit
from .layout import Layout, Placed
from .merge import build as merge_build
from .parts import ALL as RECT_PARTS

UP_LOCAL = np.array([0.0, -1.0, 0.0])  # LDraw up


@dataclass
class PartOut:
    pid: str
    colour: int
    M: np.ndarray  # world transform
    body: str
    hinged: tuple = ()  # for a hinge base: the bodies mounted on its top


@dataclass
class Body:
    name: str
    frame: np.ndarray
    parts: list[PartOut] = field(default_factory=list)
    occ: dict = field(default_factory=dict)  # (i, layer, k) -> colour, for connectors and surfacing
    mask: np.ndarray | None = None
    origin: tuple[int, int, int] = (0, 0, 0)

    def add(self, pid, colour, local: np.ndarray):
        self.parts.append(PartOut(pid, colour, self.frame @ local, self.name))


def _grid_from_layers(layers: list[list[str]], palette: dict[str, int]):
    """Character layers (bottom-up; each a list of rows = z, chars = x) ->
    bool grid and colour grid (x, layer, z)."""
    Y = len(layers)
    Z = max(len(l) for l in layers)
    X = max(len(r) for l in layers for r in l)
    grid = np.zeros((X, Y, Z), bool)
    col = np.zeros((X, Y, Z), int)
    for y, rows in enumerate(layers):
        for z, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch in palette:
                    grid[x, y, z] = True
                    col[x, y, z] = palette[ch]
    return grid, col


def _surface(body: Body, grid: np.ndarray, col: np.ndarray, blocked=frozenset()):
    """Round off top edges: where two exposed top cells run toward an edge
    that drops away, cap them with a curved slope rising inward. That single
    move is most of the difference between a voxel lump and a LEGO shape."""
    X, Y, Z = grid.shape
    top = np.full((X, Z), -1)
    for x in range(X):
        for z in range(Z):
            ys = np.nonzero(grid[x, :, z])[0]
            if len(ys):
                top[x, z] = ys.max()
    used = np.zeros((X, Z), bool)
    # directions: (dx, dz, quarters) for a slope whose high end points inward
    # (native high end is +Z; rotate so it faces away from the drop)
    dirs = [(0, -1, 0), (0, 1, 2), (-1, 0, 1), (1, 0, 3)]
    for x in range(X):
        for z in range(Z):
            h = top[x, z]
            if h < 0 or used[x, z] or (x, h + 1, z) in blocked:
                continue
            for dx, dz, q in dirs:
                ox, oz = x + dx, z + dz  # outer (low) cell
                if not (0 <= ox < X and 0 <= oz < Z) or used[ox, oz] or top[ox, oz] != h or (ox, h + 1, oz) in blocked:
                    continue
                bx, bz = ox + dx, oz + dz  # beyond the outer cell: must drop away
                beyond = top[bx, bz] if (0 <= bx < X and 0 <= bz < Z) else -1
                if beyond >= h:
                    continue
                ix, iz = x - dx, z - dz  # behind the inner cell: must not drop
                behind = top[ix, iz] if (0 <= ix < X and 0 <= iz < Z) else -1
                if behind < h:
                    continue
                i0, k0 = min(x, ox), min(z, oz)
                body.add("11477", int(col[x, h, z]), kit.grid_matrix("11477", i0, h + 1, k0, q))
                used[x, z] = used[ox, oz] = True
                break


def build_body(spec: dict, palette: dict[str, int], frame: np.ndarray) -> Body:
    # a body's grid can start away from its attach point (e.g. a wing that
    # reaches past the body it hinges on)
    ox, oy, oz = spec.get("origin", (0, 0, 0))
    frame = frame @ kit.translate((ox * kit.STUD, -oy * kit.PLATE, oz * kit.STUD))
    body = Body(spec["name"], frame)
    if not spec.get("layers"):
        for pid, ck, (i, y, k), *rest in spec.get("parts", []):
            body.add(pid, palette[ck], kit.grid_matrix(pid, i, y, k, rest[0] if rest else 0))
        return body
    grid, col = _grid_from_layers(spec["layers"], palette)
    body.mask = grid
    # connectors and details reserve their cells first
    reserved = {}
    for c in spec.get("connectors", []):
        i, y, k = c["at"]
        pid = c["part"]
        q = c.get("quarters", 0)
        sx, sz = kit.footprint(pid, q)
        for dx in range(sx):
            for dz in range(sz):
                for dy in range(kit.G[pid].plates):
                    reserved[(i + dx, y + dy, k + dz)] = True
    work = grid.copy()
    for (i, y, k) in reserved:
        if 0 <= i < grid.shape[0] and 0 <= y < grid.shape[1] and 0 <= k < grid.shape[2]:
            work[i, y, k] = False
    layout: Layout = merge_build(work, col) if work.any() else Layout(shape=grid.shape)
    for p in layout.parts:
        q = 0 if p.along_x else 1
        body.add(p.part.id, p.colour, kit.grid_matrix(p.part.id, p.x, p.y, p.z, q))
    for c in spec.get("connectors", []):
        i, y, k = c["at"]
        colour = palette[c["colour"]] if isinstance(c["colour"], str) else c["colour"]
        body.add(c["part"], colour, kit.grid_matrix(c["part"], i, y, k, c.get("quarters", 0)))
    for pid, ck, (i, y, k), *rest in spec.get("parts", []):
        body.add(pid, palette[ck], kit.grid_matrix(pid, i, y, k, rest[0] if rest else 0))
    if spec.get("surface", True):
        _surface(body, grid, col, frozenset(reserved))
    return body


def assemble(brief: dict) -> list[PartOut]:
    palette = {k: int(v) for k, v in brief["palette"].items()}
    specs = {b["name"]: b for b in brief["bodies"]}
    bodies: dict[str, Body] = {}
    out: list[PartOut] = []

    def place(name: str, attach_frame: np.ndarray):
        spec = specs[name]
        body = build_body(spec, palette, attach_frame)
        frame = body.frame
        bodies[name] = body
        out.extend(body.parts)
        for c in spec.get("connectors", []):
            for att in c.get("attach", []):
                child = att["body"]
                i, y, k = c["at"]
                local = kit.grid_matrix(c["part"], i, y, k, c.get("quarters", 0))
                if c["kind"] == "side":
                    stud = kit.SIDE_STUDS[c["part"]][att.get("stud", 0)]
                    base = local @ np.array([*stud, 1.0])
                    direction = local[:3, :3] @ np.array([0.0, 0.0, -1.0])
                    world_base = frame @ base
                    world_dir = frame[:3, :3] @ direction
                    # child grid: its attach cell's bottom centre sits on the stud base,
                    # its up (-Y) points along the stud
                    ci, ck = att.get("cell", (0, 0))
                    anchor = np.array([(ci + 0.5) * kit.STUD, 0.0, (ck + 0.5) * kit.STUD])
                    R = kit.align(UP_LOCAL, world_dir)
                    roll = kit.rot_axis(world_dir, att.get("roll", 0.0))[:3, :3]
                    F = np.eye(4)
                    F[:3, :3] = roll @ R
                    F[:3, 3] = world_base[:3] - (roll @ R) @ anchor
                    place(child, F)
                elif c["kind"] == "hinge":
                    # child shares the parent's grid when closed; rotate about the hinge axis
                    pivot = local @ np.array([*kit.HINGE_PIVOT, 1.0])
                    axis = local[:3, :3] @ np.array([1.0, 0.0, 0.0])
                    # positive angle raises the child's +z side (axis along x) or +x side
                    # (axis along z), whatever the hinge's quarters, so briefs can reason about it
                    angle = att.get("angle", 0.0) * (-1 if c.get("quarters", 0) % 4 >= 2 else 1)
                    H = kit.translate(pivot[:3]) @ kit.rot_axis(axis, angle) @ kit.translate(-pivot[:3])
                    F = frame @ H
                    for p in body.parts:
                        if p.pid == "3937" and np.allclose(p.M, frame @ local):
                            p.hinged = (*p.hinged, child)
                    top_colour = palette[c["colour"]] if isinstance(c["colour"], str) else int(c["colour"])
                    out.append(PartOut("3938", top_colour, F @ local, child))
                    # the hinged body shares the parent's grid, shifted by its own origin
                    place(child, F)

    place(brief["root"], np.eye(4))
    for d in brief.get("details", []):
        out.extend(_detail(d, bodies, palette))
    return out


def _detail(d: dict, bodies: dict[str, Body], palette: dict[str, int]) -> list[PartOut]:
    """Single parts that make it read: bar beaks, round-tile eyes."""
    colour = palette[d["colour"]]
    body = bodies[d["body"]]
    parts = []
    if d["kind"] == "bar":
        # a bar standing in an open-stud round plate at a body cell, pointing up in that body
        i, y, k = d["at"]
        plate = kit.grid_matrix("85861", i, y, k)
        parts.append(PartOut("85861", palette.get(d.get("holder", ""), colour), body.frame @ plate, body.name))
        bar = np.eye(4)
        bar[:3, :3] = np.diag([1.0, -1.0, -1.0])  # native bar runs +Y; flip to run up
        bar[:3, 3] = plate[:3, 3] + np.array([0.0, 4.0, 0.0])
        parts.append(PartOut("30374", colour, body.frame @ bar, body.name))
    return parts


def to_ldr(parts: list[PartOut], name: str) -> str:
    lines = [f"0 {name}", f"0 Name: {name}.ldr", "0 Author: brickify", ""]
    by_body: dict[str, list[PartOut]] = {}
    for p in parts:
        by_body.setdefault(p.body, []).append(p)
    for body, ps in by_body.items():
        ps.sort(key=lambda p: -p.M[1, 3])
        for p in ps:
            m = p.M
            r = " ".join(f"{v:.6g}" for v in m[:3, :3].reshape(-1))
            lines.append(f"1 {p.colour} {m[0, 3]:.4g} {m[1, 3]:.4g} {m[2, 3]:.4g} {r} {p.pid}.dat")
        lines.append("0 STEP")
    return "\n".join(lines) + "\n"
