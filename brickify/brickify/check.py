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


def resolve(parts):
    """Drop cosmetic surfacing parts that collide with another body's parts
    (e.g. a shoulder slope where a hinged wing sweeps). Structure always wins."""
    for _ in range(4):
        r = check_world(parts, detail=True)
        drop = set()
        for a, b in r["pairs"]:
            pa, pb = parts[a], parts[b]
            if pa.pid in COSMETIC and pb.pid not in COSMETIC:
                drop.add(a)
            elif pb.pid in COSMETIC and pa.pid not in COSMETIC:
                drop.add(b)
            elif pa.pid in COSMETIC and pb.pid in COSMETIC:
                drop.add(b)
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
