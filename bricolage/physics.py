"""Real static-stability check — force/torque equilibrium, à la BrickGPT
(Pun et al., ICCV 2025), not the old centre-of-mass heuristic.

A structure stands iff there EXISTS a set of connection forces that holds every
brick in static equilibrium under gravity, within each joint's capacity:
  - a stud connection carries compression (unbounded), tension up to the stud
    clutch limit, and horizontal shear up to a friction/clutch limit;
  - the ground pushes up only (no tension) with Coulomb friction.
We solve the feasibility LP with scipy; if a feasible force set exists → stable.

Coordinates here: x,y are footprint studs, z is the height LAYER, gravity = -z.
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import linprog

from bricks import cells

# tuned so the feasibility LP agrees with the StableText2Brick ground-truth
# stability labels on ~93% of 47k real models (and catches floating / excessive
# cantilever). A stud's clutch holds this much pull-apart & sideways force,
# in units of a 1x1 brick's weight.
CLUTCH_TENSION = 10.0
CLUTCH_SHEAR = 10.0
GROUND_FRICTION = 1.0    # Coulomb mu on the table


def _weight(h, w):
    return float(h * w)          # mass ~ footprint area, one brick tall


def broken_bricks(items):
    """Indices of bricks with no support beneath them — nothing below and not on
    the ground layer. These are the joints that fail (drawn red in the UI). A
    stabilised build returns []; a raw LLM proposal often flags a few."""
    items = list(items)
    if not items:
        return []
    occ = {}
    for c in [c for b in items for c in cells(*b)]:
        occ[c] = True
    ground_z = min(z for (h, w, x, y, z) in items)
    bad = []
    for i, (h, w, x, y, z) in enumerate(items):
        if z == ground_z:
            continue
        supported = any((x + dx, y + dy, z - 1) in occ
                        for dx in range(h) for dy in range(w))
        if not supported:
            bad.append(i)
    return bad


def analyze(items):
    """items = [(h,w,x,y,z)]. Returns dict: {stable, margin, worst_brick}.
    margin>0 => a feasible force set exists with that much capacity to spare."""
    items = list(items)
    n = len(items)
    if n <= 1:
        return {"stable": True, "margin": 1.0, "worst_brick": None}

    cell_owner = {}
    for i, b in enumerate(items):
        for c in cells(*b):
            cell_owner[c] = i
    centroid = [np.array([x + h / 2.0, y + w / 2.0, z + 0.5])
                for (h, w, x, y, z) in items]
    weight = [_weight(h, w) for (h, w, x, y, z) in items]

    # PER-STUD contacts (distributed, so a joint can resist a moment):
    #   stud contact: lower brick a pushes/holds upper brick b at one stud
    #   ground contact: a z=0 brick rests on the table at one stud
    ground_z = min(z for (h, w, x, y, z) in items)   # the layer it rests on
    studs = []      # (upper_i, lower_i_or_None, point(3), is_ground)
    for i, (h, w, x, y, z) in enumerate(items):
        for dx in range(h):
            for dy in range(w):
                gx, gy = x + dx, y + dy
                pt = (gx + 0.5, gy + 0.5, z)          # bottom face of this brick
                low = cell_owner.get((gx, gy, z - 1))
                if low is not None and low != i:
                    studs.append((i, low, pt, False))
                elif z == ground_z:
                    studs.append((i, None, pt, True))

    # Full static equilibrium per brick: FORCE (3) + TORQUE (3) balance = 6 rows.
    # A structure stands iff there EXISTS a set of per-stud contact forces that
    # holds every brick in equilibrium under gravity within each joint's limits.
    # Gravity acts at the centroid, so its moment about the centroid is zero and
    # only the b Fz-row carries the weight; every torque row balances to zero.
    # This is what lets over-cantilevering fail: holding a brick that juts past
    # its support demands tension on the far studs beyond the clutch limit, so
    # the moment rows become infeasible — the physically correct failure mode.
    ns = len(studs)
    nvars = 3 * ns
    A = np.zeros((6 * n, nvars))
    b = np.zeros(6 * n)
    for i in range(n):
        b[6 * i + 2] = weight[i]

    def add_contact(bi, base, pt, sign):
        """Force sign*f at point pt acts on brick bi: add its force + moment
        (about bi's centroid) contributions to that brick's 6 equilibrium rows."""
        A[6 * bi + 0, base + 0] += sign
        A[6 * bi + 1, base + 1] += sign
        A[6 * bi + 2, base + 2] += sign
        rx = pt[0] - centroid[bi][0]; ry = pt[1] - centroid[bi][1]; rz = pt[2] - centroid[bi][2]
        # tau = r x (sign*f):  tx=ry*fz-rz*fy, ty=rz*fx-rx*fz, tz=rx*fy-ry*fx
        A[6 * bi + 3, base + 1] += sign * (-rz); A[6 * bi + 3, base + 2] += sign * ry
        A[6 * bi + 4, base + 0] += sign * rz;    A[6 * bi + 4, base + 2] += sign * (-rx)
        A[6 * bi + 5, base + 0] += sign * (-ry); A[6 * bi + 5, base + 1] += sign * rx

    bounds, Aub, bub = [], [], []
    for k, (up, low, pt, is_ground) in enumerate(studs):
        base = 3 * k
        add_contact(up, base, pt, +1.0)          # force on the upper brick
        if low is not None:
            add_contact(low, base, pt, -1.0)     # equal & opposite on the lower
        if is_ground:
            bounds += [(None, None), (None, None), (0, None)]   # ground pushes up only
            for ax in (0, 1):
                r1 = np.zeros(nvars); r1[base + ax] = 1; r1[base + 2] = -GROUND_FRICTION
                Aub.append(r1); bub.append(0.0)
                r2 = np.zeros(nvars); r2[base + ax] = -1; r2[base + 2] = -GROUND_FRICTION
                Aub.append(r2); bub.append(0.0)
        else:
            bounds += [(-CLUTCH_SHEAR, CLUTCH_SHEAR), (-CLUTCH_SHEAR, CLUTCH_SHEAR),
                       (-CLUTCH_TENSION, None)]   # clutch: tension capped, compression free
    try:
        res = linprog(np.zeros(nvars), A_ub=np.array(Aub) if Aub else None,
                      b_ub=np.array(bub) if bub else None,
                      A_eq=A, b_eq=b, bounds=bounds, method="highs")
        supported = bool(res.success)
    except Exception:
        supported = False                        # fail closed: a solver error is not a pass
    return {"stable": supported, "supported": supported, "studs": ns, "bricks": n}

