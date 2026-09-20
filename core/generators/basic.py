"""The built-in generator set."""

from __future__ import annotations

from ..alloc import BRICK_ROW, PLATE_ROW, TILE_ROW, Allocator
from ..model import AttachPoint, Placed
from .registry import SubResult, generator

_counter = {"n": 0}


def reset_ids() -> None:
    """Restart part numbering. Called once per compose() so ids are deterministic.

    Without this the counter is process-global: the same build composed twice produces p0447 in
    one run and p0470 in the next. Geometry, colour and subassembly are identical, but the ids
    differ -- which breaks replay ("the op list must reproduce the build byte for byte"), breaks
    diffing two versions, and makes the fixtures churn on every regeneration.
    """
    _counter["n"] = 0


def _pid() -> str:
    _counter["n"] += 1
    return f"p{_counter['n']:04d}"


def _lay(alloc: Allocator, w: int, d: int, y: int, color: int, palette, sub: str,
         layer_parity: int = 0) -> list[Placed] | None:
    taken = alloc.fill_rect(w, d, color, palette, layer_parity=layer_parity)
    if taken is None:
        return None
    return [Placed(_pid(), t.part, t.color, (t.dx, y, t.dz), t.rot, sub) for t in taken]


def _row_best(alloc: Allocator, length: int, color: int, palette, parity: int = 0):
    """A row of `length`, or the longest the bin can manage. See `_lay_best` for why."""
    row = alloc.fill_row(length, color, palette, offset_parity=parity)
    if row is not None:
        return row
    fill = alloc.best_fill(length, color, palette, offset_parity=parity)
    return list(fill.taken) if fill and fill.taken else None


def _lay_best(alloc: Allocator, w: int, d: int, y: int, color: int, palette, sub: str,
              layer_parity: int = 0) -> tuple[list[Placed], int, int] | None:
    """Lay the largest rectangle the bin can actually cover, and report the size it managed.

    A real brick bin is LONG-TAIL: measured on the user's own photos, 57 identified pieces spread
    across 49 distinct part+colour combinations, so almost everything is quantity one. Asking for
    an exact 10x4 and returning None on any shortfall is why "build me a rover" collapsed to three
    parts. Building the 6x4 the bin CAN cover, and telling the caller it did, is strictly better
    than refusing -- and the caller needs the real size or the next layer will not line up.
    """
    fill = alloc.best_rect(w, d, color, palette, layer_parity=layer_parity)
    if fill is None:
        return None
    cw, cd = fill.covered
    parts = [Placed(_pid(), t.part, t.color, (t.dx, y, t.dz), t.rot, sub) for t in fill.taken]
    return parts, cw, cd


def _top_attach(parts: list[Placed]) -> list[AttachPoint]:
    """Derive the attach surface from what was ACTUALLY built, not from what we intended.

    For every (x, z) column find the highest part; a column offers an attachment only if that
    topmost part has a stud there. A generator that declares studs it did not build produces
    children that float -- which the validator catches, but one layer too late.
    """
    from .. import meta as meta_mod

    top_at: dict[tuple[int, int], tuple[int, bool]] = {}
    for p in parts:
        m = meta_mod.get(p.part)
        studs = set(m.stud_cells(p.rot))
        for cx, cz in m.cells(p.rot):
            col = (p.x + cx, p.z + cz)
            top = p.y + m.h
            prev = top_at.get(col)
            if prev is None or top > prev[0]:
                top_at[col] = (top, (cx, cz) in studs)

    by_level: dict[int, list[tuple[int, int]]] = {}
    for col, (top, has_stud) in top_at.items():
        if has_stud:
            by_level.setdefault(top, []).append(col)
    return [AttachPoint((0, lvl, 0), "top", tuple(sorted(cols)))
            for lvl, cols in sorted(by_level.items(), key=lambda kv: -len(kv[1]))]


@generator("base", "vehicle", "building")
def slab(length: int = 6, width: int = 4, height: int = 1, *, alloc, color, sub) -> SubResult | None:
    """A solid rectangular block of plates or bricks, staggered layer to layer."""
    parts: list[Placed] = []
    y = 0
    parity = 0
    w, d = length, width
    while y < height:
        use_brick = (height - y) >= 3
        got = _lay_best(alloc, w, d, y, color,
                        BRICK_ROW if use_brick else PLATE_ROW, sub, parity)
        if got is None:
            break                       # the bin is spent; ship what we have rather than nothing
        layer, w, d = got               # later layers match the size the first one managed
        parts += layer
        y += 3 if use_brick else 1
        parity ^= 1
    if not parts:
        return None
    note = f"{w}x{d} slab, {len(parts)} pieces"
    if (w, d) != (length, width):
        note += f" (asked for {length}x{width}; the bin covered {w}x{d})"
    return SubResult(parts, _top_attach(parts), note)


@generator("vehicle", "base")
def chassis(length: int = 10, width: int = 4, style: str = "flat", *, alloc, color, sub) -> SubResult | None:
    """A vehicle base: a plate floor with a brick spine, lowered or flat."""
    got = _lay_best(alloc, length, width, 0, color, PLATE_ROW, sub, 0)
    if got is None:
        return None
    floor, length, width = got          # the deck must match the floor the bin could afford
    parts = list(floor)
    if style != "lowered":
        # A full-width brick deck, offset from the floor below so the seams stagger. A narrower
        # spine would leave the outer rows with nothing to attach to, and every child placed on
        # top would overhang into thin air.
        deck = _lay(alloc, length, width, 1, color, BRICK_ROW, sub, 1)
        if deck is None:
            return None
        parts += deck
    return SubResult(parts, _top_attach(parts), f"{length}x{width} {style} chassis")


@generator("vehicle")
def cabin(length: int = 4, width: int = 4, height: int = 6, style: str = "open",
          *, alloc, color, sub) -> SubResult | None:
    """A hollow box with walls and an optional roof -- a cab, cockpit or room.

    Courses ALTERNATE WHICH WALLS OWN THE CORNERS, which is how a real LEGO box is bound
    together. A single course is a flat ring: its bricks sit beside each other, and bricks beside
    each other are not connected -- only a stud into an anti-stud is. Stack two identical courses
    and every brick links to exactly the one beneath it, so the ring is still four loose walls,
    which is precisely what the validator kept reporting.

    Swapping corner ownership each course makes the brick above straddle two bricks below at
    every corner, tying the ring into one piece. It is also just how you would lay real bricks.
    """
    parts: list[Placed] = []
    y = 0
    course_no = 0
    while y < height:
        course: list[Placed] = []
        long_owns_corners = course_no % 2 == 0

        if long_owns_corners:
            x0, xlen = 0, length
            z0, zlen = 1, width - 2
        else:
            x0, xlen = 1, length - 2
            z0, zlen = 0, width

        ok = True
        # walls running along X, at the two extremes of Z
        if xlen > 0:
            for dz in (0, width - 1):
                row = _row_best(alloc, xlen, color, BRICK_ROW, course_no % 2)
                if row is None:
                    ok = False
                    break
                course += [Placed(_pid(), t.part, t.color, (x0 + t.dx, y, dz), t.rot, sub)
                           for t in row]

        # walls running along Z, at the two extremes of X. A 1x2 here must be ROTATED to run
        # along z: brick 1x2 is w=2,d=1, so unrotated it would poke out past the end wall.
        if ok and zlen > 0:
            for dx in (0, length - 1):
                dz = z0
                while dz < z0 + zlen:
                    remaining = z0 + zlen - dz
                    placed = False
                    if remaining >= 2:
                        cs = alloc.best_colors("3004", color)
                        if cs and alloc.take("3004", cs[0]):
                            course.append(Placed(_pid(), "3004", cs[0], (dx, y, dz), 90, sub))
                            dz += 2
                            placed = True
                    if not placed:
                        cs = alloc.best_colors("3005", color)
                        if cs and alloc.take("3005", cs[0]):
                            course.append(Placed(_pid(), "3005", cs[0], (dx, y, dz), 0, sub))
                            dz += 1
                        else:
                            ok = False
                            break
                if not ok:
                    break

        if not ok or not course:
            # A half-built course leaves bricks with nothing beside or above them. Stop at the
            # last whole course rather than shipping a ring with a hole in it.
            break
        parts += course
        y += 3
        course_no += 1

    if len(parts) == 0:
        return None
    if course_no < 2:
        # One course is a flat ring and cannot be connected. Say so rather than return it.
        return None

    if style == "closed":
        roof = _lay(alloc, length, width, y, color, PLATE_ROW, sub, 0)
        if roof is not None:
            parts += roof
            y += 1
    return SubResult(parts, _top_attach(parts), f"{style} cabin {length}x{width}, {course_no} courses")


@generator("building")
def tower(height: int = 12, size: int = 4, *, alloc, color, sub) -> SubResult | None:
    """A square hollow tower, staggered like masonry so it does not split."""
    return cabin(length=size, width=size, height=height, style="open",
                 alloc=alloc, color=color, sub=sub)


@generator("detail")
def wall(length: int = 8, height: int = 6, *, alloc, color, sub) -> SubResult | None:
    """A single-thickness staggered wall."""
    parts: list[Placed] = []
    y = 0
    parity = 0
    while y < height:
        row = _row_best(alloc, length, color, BRICK_ROW, parity)
        if row is None:
            break
        parts += [Placed(_pid(), t.part, t.color, (t.dx, y, 0), t.rot, sub) for t in row]
        y += 3
        parity ^= 1
    if not parts:
        return None
    return SubResult(parts, _top_attach(parts), f"{length}-long wall, {height} plates high")


@generator("detail", "vehicle")
def fin(length: int = 4, height: int = 3, *, alloc, color, sub) -> SubResult | None:
    """A thin vertical fin or spoiler."""
    return wall(length=length, height=height, alloc=alloc, color=color, sub=sub)


@generator("detail")
def roof_flat(length: int = 6, width: int = 4, *, alloc, color, sub) -> SubResult | None:
    """A flat tiled roof or finished deck (tiles: nothing attaches on top)."""
    taken = alloc.fill_rect(length, width, color, TILE_ROW)
    if taken is None:
        taken = alloc.fill_rect(length, width, color, PLATE_ROW)
    if taken is None:
        return None
    parts = [Placed(_pid(), t.part, t.color, (t.dx, 0, t.dz), t.rot, sub) for t in taken]
    return SubResult(parts, [], f"{length}x{width} flat roof")
