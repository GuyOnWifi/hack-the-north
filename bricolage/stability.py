"""Structural stability analysis — the physics the connectivity validator can't
see. A build can be fully connected and still fall over or rip apart under
gravity. This module proves (a tractable approximation of) static stability,
in the spirit of Luo et al., "Legolization" (SIGGRAPH Asia 2015).

Two failure modes, both real:
  TOPPLE     the whole model's centre of mass leaves the ground support polygon
             -> it tips over. (Nothing clutches the model to the table.)
  JOINT_RIP  at some horizontal cut, the centre of mass of everything above the
             cut lies beyond what the stud-clutch at that cut can hold in
             tension -> the overhang shears off. (Studs DO clutch, so LEGO can
             cantilever a little — unlike gravity-only masonry — but not forever.)

Pure Python, zero-dependency (keeps DEMO_SAFE). A full 3D static-equilibrium LP
(scipy) is a drop-in upgrade; this analytic model is robust and demonstrable.
"""
from __future__ import annotations
from dataclasses import dataclass

# a joint's stud-clutch lets a substructure's COM hang this many studs beyond
# the convex hull of its supporting studs before the joint tension is exceeded.
CLUTCH_OVERHANG_STUDS = 2.0
GROUND_MARGIN_STUDS = 0.4        # tolerance at the table (no clutch there)


@dataclass
class Instability:
    code: str
    parts: list
    human: str


# ------------------------------------------------------------- geometry helpers
def _hull(points):
    """Andrew's monotone chain. Returns hull vertices ccw; for <3 or collinear
    points returns the unique points (a segment or a point)."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return hull if len(hull) >= 3 else pts


def _dist_point_to_hull(pt, hull):
    """0 if pt is inside the (convex) hull, else the Euclidean distance to it.
    Handles degenerate hulls (point / segment)."""
    if len(hull) == 1:
        return _d(pt, hull[0])
    if len(hull) == 2:
        return _seg_dist(pt, hull[0], hull[1])
    inside = True
    for i in range(len(hull)):
        a, b = hull[i], hull[(i + 1) % len(hull)]
        if (b[0] - a[0]) * (pt[1] - a[1]) - (b[1] - a[1]) * (pt[0] - a[0]) < 0:
            inside = False
            break
    if inside:
        return 0.0
    return min(_seg_dist(pt, hull[i], hull[(i + 1) % len(hull)])
               for i in range(len(hull)))


def _d(p, q):
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return _d(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return _d(p, (a[0] + t * dx, a[1] + t * dy))


# ------------------------------------------------------------------- mechanics
def _mass(p):
    dx, dz = p.footprint()
    return dx * dz * p.height()          # volume proxy — density is uniform


def _com_xz(parts):
    m = sum(_mass(p) for p in parts)
    if m == 0:
        return (0.0, 0.0), 0.0
    cx = sum(_mass(p) * (p.pos[0] + p.footprint()[0] / 2) for p in parts) / m
    cz = sum(_mass(p) * (p.pos[2] + p.footprint()[1] / 2) for p in parts) / m
    return (cx, cz), m


def report(parts):
    """Structured data for VISUALISING the physics in the UI: the centre of
    mass, the ground support polygon, and each cut's overhang margin. This is
    what turns 'a GPT wrapper' into 'watch the AI's design teeter and get
    caught' — the invisible made visible."""
    parts = list(parts)
    if not parts:
        return {"stable": True, "com": None, "base": [], "cuts": []}
    ground_y = min(p.pos[1] for p in parts)
    ground_studs = [(p.pos[0] + i + 0.5, p.pos[2] + j + 0.5)
                    for p in parts if p.pos[1] == ground_y
                    for i in range(p.footprint()[0]) for j in range(p.footprint()[1])]
    com, mass = _com_xz(parts)
    base = _hull(ground_studs)
    fails = analyze(parts)
    return {"stable": not fails,
            "com": [round(com[0], 2), round(com[1], 2)],
            "mass": mass,
            "base": [[round(x, 1), round(z, 1)] for x, z in base],
            "topple_margin": round(GROUND_MARGIN_STUDS - _dist_point_to_hull(com, base), 2),
            "failures": [{"code": f.code, "human": f.human} for f in fails]}


def stabilize(parts, seed=0):
    """Physics self-repair: if the build topples, add a wider bonded-plate
    FOUNDATION beneath it, sized so the combined centre of mass falls back
    inside the support polygon. Deterministic. Returns (new_parts, n_added).
    The agentic arc's payoff: physics rejects -> the agent props it up -> stands."""
    parts = list(parts)
    fails = analyze(parts)
    if not any(f.code == "TOPPLE" for f in fails):
        return parts, 0
    from generators import bonded
    from model import Part

    ground_y = min(p.pos[1] for p in parts)
    com, _ = _com_xz(parts)
    xs = [p.pos[0] for p in parts] + [p.pos[0] + p.footprint()[0] for p in parts]
    zs = [p.pos[2] for p in parts] + [p.pos[2] + p.footprint()[1] for p in parts]
    # cover the structure AND reach past the COM, with a margin
    x0 = int(min(min(xs), com[0])) - 2
    x1 = int(max(max(xs), com[0])) + 2
    z0 = int(min(min(zs), com[1])) - 2
    z1 = int(max(max(zs), com[1])) + 2
    base = []
    for p in bonded(x1 - x0, z1 - z0, 0, 71, seed, plates=True, courses=2, sub="base"):
        base.append(Part(f"base{len(base)}", p.part, p.color,
                         (p.pos[0] + x0, ground_y - 2 + p.pos[1], p.pos[2] + z0),
                         0, "base"))
    return parts + base, len(base)


def analyze(parts):
    """Return a list of Instability findings ([] means it stands up)."""
    parts = list(parts)
    if len(parts) < 2:
        return []
    fails = []

    # ---- 1. global toppling: COM over the ground support polygon -----------
    ground_y = min(p.pos[1] for p in parts)
    ground_studs = [(p.pos[0] + i + 0.5, p.pos[2] + j + 0.5)
                    for p in parts if p.pos[1] == ground_y
                    for i in range(p.footprint()[0]) for j in range(p.footprint()[1])]
    com, _ = _com_xz(parts)
    base = _hull(ground_studs)
    if _dist_point_to_hull(com, base) > GROUND_MARGIN_STUDS:
        fails.append(Instability(
            "TOPPLE", [],
            f"The whole model tips over — its centre of mass sits "
            f"{_dist_point_to_hull(com, base):.1f} studs outside the footprint "
            f"it rests on."))
        return fails   # if it topples wholesale, joint checks are moot

    # ---- 2. joint rip: COM above each cut vs the clutch that holds it -------
    # occupancy for finding which studs bridge a horizontal cut
    filled = {}
    for p in parts:
        for i in range(p.footprint()[0]):
            for j in range(p.footprint()[1]):
                for k in range(p.height()):
                    filled[(p.pos[0] + i, p.pos[1] + k, p.pos[2] + j)] = p.id

    levels = sorted({p.pos[1] for p in parts if p.pos[1] > ground_y})
    for y in levels:
        above = [p for p in parts if p.pos[1] >= y]
        if not above:
            continue
        # studs that clutch across this cut: a cell at y with a filled cell at y-1
        joint_studs = [(x + 0.5, z + 0.5) for (x, yy, z) in filled
                       if yy == y and (x, yy - 1, z) in filled]
        if not joint_studs:
            continue
        com_above, _ = _com_xz(above)
        hull = _hull(joint_studs)
        overhang = _dist_point_to_hull(com_above, hull)
        if overhang > CLUTCH_OVERHANG_STUDS:
            fails.append(Instability(
                "JOINT_RIP", [p.id for p in above],
                f"The section above layer {y} cantilevers too far: its centre "
                f"of mass hangs {overhang:.1f} studs past the studs holding it "
                f"(clutch gives ~{CLUTCH_OVERHANG_STUDS:.0f}). It shears off."))
            break    # report the lowest failing cut; repair fixes bottom-up
    return fails
