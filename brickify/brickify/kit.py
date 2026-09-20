"""The build kit: part geometry in LDraw units, verified against the LDraw
library (see the probes in the design notes), and the maths to place a part
on a body's stud grid.

LDraw axes: -Y is up, 1 stud = 20 LDU, 1 plate = 8 LDU. A body's grid cell
(i, layer, k) spans x in [20i, 20i+20], z in [20k, 20k+20] and
y in [-8(layer+1), -8 layer] in that body's own frame.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

STUD = 20.0
PLATE = 8.0


@dataclass(frozen=True)
class Geom:
    """Native geometry: footprint box in LDU (x0, x1, z0, z1), height in
    plates, and where the origin sits vertically: 'top' (studded parts: origin
    on the top surface) or 'bottom' (curved slopes)."""

    x0: float
    x1: float
    z0: float
    z1: float
    plates: int
    origin: str = "top"
    studs_on_top: bool = True
    name: str = ""


G: dict[str, Geom] = {}


def _rect(pid, length, width, plates, name, studs=True):
    G[pid] = Geom(-length * 10, length * 10, -width * 10, width * 10, plates, "top", studs, name)


for pid, l, w, name in [("3024", 1, 1, "Plate 1x1"), ("3023", 2, 1, "Plate 1x2"), ("3623", 3, 1, "Plate 1x3"), ("3710", 4, 1, "Plate 1x4"), ("3666", 6, 1, "Plate 1x6"), ("3460", 8, 1, "Plate 1x8"), ("3022", 2, 2, "Plate 2x2"), ("3021", 3, 2, "Plate 2x3"), ("3020", 4, 2, "Plate 2x4"), ("3795", 6, 2, "Plate 2x6"), ("3034", 8, 2, "Plate 2x8")]:
    _rect(pid, l, w, 1, name)
for pid, l, w, name in [("3005", 1, 1, "Brick 1x1"), ("3004", 2, 1, "Brick 1x2"), ("3622", 3, 1, "Brick 1x3"), ("3010", 4, 1, "Brick 1x4"), ("3009", 6, 1, "Brick 1x6"), ("3008", 8, 1, "Brick 1x8"), ("3003", 2, 2, "Brick 2x2"), ("3002", 3, 2, "Brick 2x3"), ("3001", 4, 2, "Brick 2x4"), ("2456", 6, 2, "Brick 2x6"), ("3007", 8, 2, "Brick 2x8")]:
    _rect(pid, l, w, 3, name)
for pid, l, w, name in [("3070b", 1, 1, "Tile 1x1"), ("3069b", 2, 1, "Tile 1x2"), ("63864", 3, 1, "Tile 1x3"), ("2431", 4, 1, "Tile 1x4"), ("3068b", 2, 2, "Tile 2x2")]:
    _rect(pid, l, w, 1, name, studs=False)

# Round and detail parts
G["98138"] = Geom(-10, 10, -10, 10, 1, "top", False, "Tile 1x1 Round")
G["6141"] = Geom(-10, 10, -10, 10, 1, "top", True, "Plate 1x1 Round")
G["85861"] = Geom(-10, 10, -10, 10, 1, "top", True, "Plate 1x1 Round with Open Stud")
G["3062b"] = Geom(-10, 10, -10, 10, 3, "top", True, "Brick 1x1 Round")
# Side-stud bricks: side studs on the -Z face, 10 LDU below the top.
G["87087"] = Geom(-10, 10, -10, 10, 3, "top", True, "Brick 1x1 with Stud on Side")
G["11211"] = Geom(-20, 20, -10, 10, 3, "top", True, "Brick 1x2 with 2 Studs on Side")
SIDE_STUDS = {"87087": [(0.0, 10.0, -10.0)], "11211": [(-10.0, 10.0, -10.0), (10.0, 10.0, -10.0)]}
# Curved slopes: origin at the bottom, long axis along Z, high end at +Z.
G["11477"] = Geom(-10, 10, -20, 20, 2, "bottom", False, "Slope Curved 2x1")
G["93273"] = Geom(-10, 10, -40, 40, 2, "bottom", False, "Slope Curved 4x1 Double")
G["15068"] = Geom(-20, 20, -20, 20, 2, "bottom", False, "Slope Curved 2x2")
# Hinge brick: base and top plate share an origin when closed; the top pivots
# about an axis along X through (y=10, z=0).
G["3937"] = Geom(-20, 20, -10, 10, 3, "top", False, "Hinge Brick 1x2 Base")
G["3938"] = Geom(-20, 20, -10, 10, 0, "top", True, "Hinge Brick 1x2 Top")
HINGE_PIVOT = np.array([0.0, 10.0, 0.0])
# Wedge plates (right/left), footprint 2x3 / 2x4 along Z.
G["43722"] = Geom(-20, 20, -30, 30, 1, "top", True, "Wedge Plate 3x2 Right")
G["43723"] = Geom(-20, 20, -30, 30, 1, "top", True, "Wedge Plate 3x2 Left")
G["41769"] = Geom(-20, 20, -40, 40, 1, "top", True, "Wedge Plate 4x2 Right")
G["41770"] = Geom(-20, 20, -40, 40, 1, "top", True, "Wedge Plate 4x2 Left")
# Bar (4L), native axis +Y from its origin.
G["30374"] = Geom(-4, 4, -4, 4, 0, "top", False, "Bar 4L")
# Wheels. A 2x2 plate carries two pins along X at y=5 (measured: the plate is a
# normal 2x2, the pins reach x=+-34). The rim and tyre are discs whose native
# axis is +Z, so they turn onto the pin and sit just outside the plate's side.
G["4600"] = Geom(-20, 20, -20, 20, 1, "top", True, "Plate 2x2 with Wheel Pins")
G["4624"] = Geom(-10, 10, -8, 8, 0, "top", False, "Wheel Rim 6.4 x 8")
G["3641"] = Geom(-18, 18, -8, 8, 0, "top", False, "Tyre 6/50 x 8")
WHEEL_PIN = np.array([28.0, 5.0, 0.0])  # centre of a mounted wheel, in 4600's frame
WHEEL_RADIUS = 18.0


def rot_y(quarters: int) -> np.ndarray:
    """Rotation by 90-degree steps about the vertical axis."""
    c, s = [(1, 0), (0, 1), (-1, 0), (0, -1)][quarters % 4]
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)


def footprint(pid: str, quarters: int) -> tuple[int, int]:
    """Cells covered along body x and z after rotating the part."""
    g = G[pid]
    sx, sz = round((g.x1 - g.x0) / STUD), round((g.z1 - g.z0) / STUD)
    return (sz, sx) if quarters % 2 else (sx, sz)


def grid_matrix(pid: str, i: int, layer: int, k: int, quarters: int = 0) -> np.ndarray:
    """4x4 body-local transform placing part `pid` so its (rotated) footprint
    covers cells [i, i+sx) x [k, k+sz) with its bottom at `layer`."""
    g = G[pid]
    R = rot_y(quarters)
    sx, sz = footprint(pid, quarters)
    centre_native = np.array([(g.x0 + g.x1) / 2, 0.0, (g.z0 + g.z1) / 2])
    target = np.array([(i + sx / 2) * STUD, 0.0, (k + sz / 2) * STUD])
    pos = target - R @ centre_native
    pos[1] = -layer * PLATE if g.origin == "bottom" else -(layer + g.plates) * PLATE
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = pos
    return M


def translate(v) -> np.ndarray:
    M = np.eye(4)
    M[:3, 3] = v
    return M


def rot_axis(axis, degrees: float) -> np.ndarray:
    a = np.asarray(axis, float)
    a /= np.linalg.norm(a)
    t = np.radians(degrees)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    R = np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * K @ K
    M = np.eye(4)
    M[:3, :3] = R
    return M


def align(frm, to, roll_hint=(1.0, 0.0, 0.0)) -> np.ndarray:
    """Rotation taking direction `frm` onto `to` (3x3)."""
    f = np.asarray(frm, float) / np.linalg.norm(frm)
    t = np.asarray(to, float) / np.linalg.norm(to)
    v = np.cross(f, t)
    c = float(np.dot(f, t))
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        # 180 degrees: rotate about any axis perpendicular to f
        p = np.cross(f, roll_hint)
        if np.linalg.norm(p) < 1e-9:
            p = np.cross(f, (0, 0, 1))
        p /= np.linalg.norm(p)
        return 2 * np.outer(p, p) - np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * (1 / (1 + c))
