"""Step sequencing: the order a human can physically build the model in.

Two constraints no LDraw tool computes for you (they all just READ `0 STEP`):

  1. SUPPORT     -- a part may only be placed after everything it rests on.
  2. INSERTION SWEEP -- sweep the part's own volume straight up from its final position to the
     top of the model. If any already-placed part sits in that column, the placement is
     physically impossible: you cannot slide a brick in underneath something you already built.

Locality then picks among the legal candidates, which produces the natural "keep building
outward from what you just placed" feel of a real manual.
"""

from __future__ import annotations

from . import meta as meta_mod
from .model import Build, Placed
from .validate import connections


def _columns(p: Placed) -> tuple[set[tuple[int, int]], int, int]:
    m = meta_mod.get(p.part)
    cols = {(p.x + cx, p.z + cz) for cx, cz in m.cells(p.rot)}
    return cols, p.y, p.y + m.h


def order_parts(build: Build) -> list[Placed]:
    by_id = {p.id: p for p in build.parts}
    supports: dict[str, set[str]] = {p.id: set() for p in build.parts}
    for lower, upper, _ in connections(build):
        supports[upper].add(lower)

    top = max((p.y + meta_mod.get(p.part).h) for p in build.parts)
    remaining = list(build.parts)
    placed: list[Placed] = []
    placed_ids: set[str] = set()
    # occupancy of columns above each placed part, for the sweep test
    filled: dict[tuple[int, int], set[int]] = {}

    def sweep_clear(p: Placed) -> bool:
        cols, y0, y1 = _columns(p)
        for c in cols:
            occupied = filled.get(c)
            if occupied and any(level >= y1 for level in occupied):
                return False
        return True

    def mark(p: Placed) -> None:
        cols, y0, y1 = _columns(p)
        for c in cols:
            filled.setdefault(c, set()).update(range(y0, y1))

    while remaining:
        legal = [p for p in remaining
                 if supports[p.id] <= placed_ids and sweep_clear(p)]
        if not legal:
            # Fall back to support-only ordering so we always produce a manual, but say so.
            legal = [p for p in remaining if supports[p.id] <= placed_ids]
        if not legal:
            raise Unbuildable(
                f"{len(remaining)} part(s) cannot be reached in any order: "
                f"{', '.join(sorted(p.id for p in remaining)[:6])}. "
                f"The validator let through a build that cannot be assembled."
            )
        legal.sort(key=lambda p: (p.y, -_contacts(p, placed_ids, supports), _dist(p, placed)))
        pick = legal[0]
        remaining.remove(pick)
        placed.append(pick)
        placed_ids.add(pick.id)
        mark(pick)
    return placed


class Unbuildable(RuntimeError):
    """Raised when no legal assembly order exists -- means the validator has a hole."""


def _contacts(p: Placed, placed_ids: set[str], supports: dict[str, set[str]]) -> int:
    return len(supports[p.id] & placed_ids)


def _dist(p: Placed, placed: list[Placed]) -> int:
    if not placed:
        return 0
    q = placed[-1]
    return abs(p.x - q.x) + abs(p.z - q.z)


def group_steps(ordered: list[Placed], min_size: int = 1, max_size: int = 6) -> list[list[Placed]]:
    """1-6 parts per step, same subassembly and layer, preferring identical parts.

    The first three steps stay small: gentle starts read as professional.
    """
    steps: list[list[Placed]] = []
    cur: list[Placed] = []

    def cap() -> int:
        return 3 if len(steps) < 3 else max_size

    for p in ordered:
        if cur:
            same = (cur[0].sub == p.sub and cur[0].y == p.y)
            identical = (cur[0].part == p.part and cur[0].color == p.color)
            if not same or len(cur) >= (cap() if not identical else max_size):
                steps.append(cur); cur = []
        cur.append(p)
    if cur:
        steps.append(cur)

    # never leave a single orphan as the last step
    if len(steps) > 1 and len(steps[-1]) == 1 and len(steps[-2]) < max_size:
        steps[-2].extend(steps.pop())
    return steps


def sequence(build: Build) -> list[list[Placed]]:
    return group_steps(order_parts(build))
