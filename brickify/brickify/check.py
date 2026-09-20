"""World-space checks on an assembled model: parts may touch but not
interpenetrate. Each part's body box (studs excluded, shrunk 1.5 LDU for
contact tolerance) is sampled on a 4-LDU lattice, transformed to world space
and bucketed; a bucket claimed by two different parts is a collision.
Designed interlocks (a hinge top inside its base, a bar inside its holder)
are exempt."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from . import kit

EXEMPT = {frozenset(("3937", "3938")), frozenset(("30374", "85861"))}
STEP = 4.0
SHRINK = 1.5


def _samples(pid: str) -> np.ndarray:
    g = kit.G[pid]
    h = max(g.plates, 1) * kit.PLATE
    y0, y1 = (-h, 0.0) if g.origin == "bottom" else (0.0, h)
    if pid == "30374":
        y0, y1 = 0.0, 80.0
    axes = [np.arange(a + SHRINK, b - SHRINK + 1e-6, STEP) for a, b in ((g.x0, g.x1), (y0, y1), (g.z0, g.z1))]
    axes = [a if len(a) else np.array([(lo + hi) / 2]) for a, (lo, hi) in zip(axes, ((g.x0, g.x1), (y0, y1), (g.z0, g.z1)))]
    X, Y, Z = np.meshgrid(*axes, indexing="ij")
    return np.stack([X.ravel(), Y.ravel(), Z.ravel(), np.ones(X.size)], axis=1)


COSMETIC = {"11477", "93273", "15068"}  # surfacing slopes: they give way to structure


TRIM_SHARE = 0.34  # past this, a child is in the wrong place, not just overlapping


def _size(parts, body: str) -> int:
    return sum(1 for p in parts if p.body == body)


def resolve(parts):
    """Make an assembly legal the way a builder would, before bothering a model.

    Cosmetic surfacing slopes give way to structure, and a sub-assembly mounted
    on another (a wing on a hinge, a face on side studs) gets the few pieces
    that reach back into its parent trimmed off. Anything worse is left alone
    and reported: it means the brief put the part in the wrong place."""
    for _ in range(4):
        r = check_world(parts, detail=True)
        drop: set[int] = set()
        for a, b in r["pairs"]:
            pa, pb = parts[a], parts[b]
            if pa.pid in COSMETIC and pb.pid not in COSMETIC:
                drop.add(a)
            elif pb.pid in COSMETIC and pa.pid not in COSMETIC:
                drop.add(b)
            elif pa.pid in COSMETIC and pb.pid in COSMETIC:
                drop.add(b)
            elif pa.parent == pb.body:
                drop.add(a)
            elif pb.parent == pa.body:
                drop.add(b)
            elif pa.parent and pa.parent == pb.parent:
                # two sub-assemblies on the same body (a flipper sweeping into
                # the head): the smaller one gives way
                drop.add(a if _size(parts, pa.body) <= _size(parts, pb.body) else b)
        # trimming a sliver is a fix; trimming a third of a body is a cover-up
        by_body: dict[str, int] = {}
        for i in drop:
            by_body[parts[i].body] = by_body.get(parts[i].body, 0) + 1
        sizes = {name: sum(1 for p in parts if p.body == name) for name in by_body}
        drop -= {i for i in drop if by_body[parts[i].body] > max(2, TRIM_SHARE * sizes[parts[i].body])}
        if not drop:
            break
        parts = [p for i, p in enumerate(parts) if i not in drop]
    return parts


def _hinged(a, b) -> bool:
    """A hinge base against the body mounted on its top: the real base has
    knuckle cut-outs for the swing, which this box model doesn't."""
    return (a.pid == "3937" and b.body in getattr(a, "hinged", ())) or (b.pid == "3937" and a.body in getattr(b, "hinged", ()))


def check_world(parts, detail: bool = False) -> dict:
    cache: dict[str, np.ndarray] = {}
    owner: dict[tuple, int] = {}
    hits = defaultdict(int)
    for idx, p in enumerate(parts):
        s = cache.setdefault(p.pid, _samples(p.pid))
        w = (p.M @ s.T).T[:, :3]
        for key in map(tuple, np.floor(w / STEP).astype(int)):
            o = owner.get(key)
            if o is None:
                owner[key] = idx
            # within one body the grid rules out overlaps; only check across bodies
            elif o != idx and parts[o].body != p.body and frozenset((parts[o].pid, p.pid)) not in EXEMPT and not _hinged(parts[o], p):
                hits[(min(o, idx), max(o, idx))] += 1
    real = [(a, b) for (a, b), n in hits.items() if n >= 3]
    pairs = [(parts[a].pid, parts[a].body, parts[b].pid, parts[b].body, hits[(a, b)]) for a, b in real]
    out = {"parts": len(parts), "collisions": len(pairs), "worst": sorted(pairs, key=lambda t: -t[4])[:6]}
    if detail:
        out["pairs"] = real
    return out


def stands(parts) -> dict:
    """Will it stand on a table? Centre of mass (every part weighted by its
    body volume) must fall inside the footprint of the parts touching the
    ground, with a little margin. Returns {stable, margin, direction} where
    margin is in studs (negative = how far outside the base the weight sits)."""
    if not parts:
        return {"stable": False, "margin": 0.0, "direction": None}
    cache: dict[str, np.ndarray] = {}
    world = []
    for p in parts:
        s = cache.setdefault(p.pid, _samples(p.pid))
        world.append((p.M @ s.T).T[:, :3])
    pts = np.concatenate(world)
    ground = pts[:, 1].max()  # LDraw: +y is down
    com = pts[:, [0, 2]].mean(axis=0)
    base = np.concatenate([w[w[:, 1] > ground - kit.PLATE, :][:, [0, 2]] for w in world if (w[:, 1] > ground - kit.PLATE).any()])
    margin, direction = _inside(com, base)
    # studs grip, so weight right on the edge still stands; only weight clearly
    # past the base tips it over
    return {"stable": margin > -0.25, "margin": round(margin, 2), "direction": direction}


def _inside(point: np.ndarray, cloud: np.ndarray) -> tuple[float, str | None]:
    """Signed distance in studs from `point` to the edge of the convex hull of
    `cloud` (x/z, LDU): positive inside. Also names the side it leans toward."""
    from scipy.spatial import ConvexHull, QhullError

    try:
        hull = ConvexHull(cloud)
    except (QhullError, ValueError):  # a single row of studs: degenerate base
        lo, hi = cloud.min(axis=0), cloud.max(axis=0)
        d = np.minimum(point - lo, hi - point).min()
        return float(d / kit.STUD), None
    # hull.equations: n . x + c <= 0 inside; distance to each edge is -(n.x + c)
    dist = -(hull.equations[:, :2] @ point + hull.equations[:, 2])
    worst = int(np.argmin(dist))
    n = hull.equations[worst, :2]
    side = ("+x" if n[0] > 0 else "-x") if abs(n[0]) >= abs(n[1]) else ("+z" if n[1] > 0 else "-z")
    return float(dist[worst] / kit.STUD), side
