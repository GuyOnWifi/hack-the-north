"""The silhouette generators: the shapes a person actually names.

WHY a second module. `basic.py` holds the primitives every build needs -- a slab, a chassis, a
box. Those make a model *exist*. These make it *read*: a wing says aircraft, a gable says house,
legs say creature. Ask for "a rover" and the difference between a designed model and a blob is
entirely in this file. The ecosystem sweep found no prior art for inventory-conditioned
parametric LEGO subassemblies, so none of this could be borrowed.

Three rules hold everywhere in here, and they are the reason these can be trusted:

1. **Connectivity is designed in, not hoped for.** Two parts side by side in the same layer are
   not joined -- the validator says so and it is physically right. So every shape here either
   leans on `fill_rect` (which bridges its rows with 2-wide parts) or has an explicit tying
   course that overlaps everything beneath it. Where the argument is subtle it is written out
   in the generator's own comment.
2. **Nothing floats.** A course only ever lands on cells the course below actually covered
   *with studs*. Slopes carry studs on one edge only, so their high edge is tracked explicitly
   rather than assumed -- getting that backwards is the easiest way to produce a roof whose
   ridge hangs in the air.
3. **A generator that gives up gives the bricks back.** `_Ledger` records every take, so a
   failed big attempt costs nothing and the smaller fallback still has the inventory it needs.
   `basic.py` predates this and leaks on failure; new work should not.

There is no randomness in here, so there is nothing for a seed to control: same arguments plus
same inventory produce byte-identical output.
"""

from __future__ import annotations

from typing import Callable, Iterable

from .. import meta as meta_mod
from ..alloc import BRICK_ROW, PLATE_ROW, Allocator, Taken
from ..model import Build, Placed
from ..validate import connections
from .basic import _pid, _top_attach
from .registry import SubResult, generator

# 45-degree slopes, longest first. All of these are 2 studs deep with studs on the HIGH edge
# only, which is what makes a pitched roof land on real studs instead of on sloped air.
SLOPE_45 = ["3038", "3039", "3040b"]          # 2x3, 2x2, 2x1
# Even-length tiles and plates. A fence rail is only supported where a picket is, so every rail
# piece has to start on an even stud -- which even-length pieces laid from x=0 guarantee.
EVEN_TILES = ["2431", "3069b"]                # tile 1x4, tile 1x2
EVEN_PLATES = ["3710", "3023b"]               # plate 1x4, plate 1x2
STUD_BLOCK = "3003"                           # brick 2x2
HALF_BLOCK = "3004"                           # brick 1x2
PIN_BLOCK = "3005"                            # brick 1x1

_MAX_COURSES = 40                             # every loop in here has a budget (invariant 8)


# ---------------------------------------------------------------------- allocation ledger


class _Ledger:
    """An Allocator wrapper that can hand back everything a failed attempt consumed.

    `Allocator.fill_row` already rolls back a row it could not finish, but a *generator* is many
    rows, and the fourth one failing must not leave the first three paid for. Without this, a
    composition that tries `wing(12, 4)`, fails, and falls back to `wing(8, 3)` has already
    spent the bricks the small wing needed.
    """

    def __init__(self, alloc: Allocator) -> None:
        self.alloc = alloc
        self._log: list[tuple[str, int]] = []

    def mark(self) -> int:
        return len(self._log)

    def undo_to(self, mark: int) -> None:
        while len(self._log) > mark:
            part, color = self._log.pop()
            self.alloc.give_back(part, color)

    def take(self, part: str, color: int) -> int | None:
        """One part in the best colour we have. Returns the colour taken, or None."""
        if not meta_mod.has(part):
            return None
        for c in self.alloc.best_colors(part, color):
            if self.alloc.take(part, c):
                self._log.append((part, c))
                return c
        return None

    def take_any(self, parts: Iterable[str], color: int) -> tuple[str, int] | None:
        """The first of `parts` we own. The palettes are ordered big-to-small, so this IS the
        degradation path: run out of 2x2s and you get 1x2s, not a failure."""
        for part in parts:
            c = self.take(part, color)
            if c is not None:
                return part, c
        return None

    def _record(self, taken: list[Taken] | None) -> list[Taken] | None:
        if taken is not None:
            self._log.extend((t.part, t.color) for t in taken)
        return taken

    def row(self, length: int, color: int, palette: list[str], parity: int = 0,
            strict: bool = False):
        """A row of `length` studs -- or the longest the bin can actually manage.

        A real bin is long-tail (measured: 57 pieces across 49 part+colour combinations), so
        insisting on an exact length makes a generator refuse far more often than it needs to.
        A shorter row is still geometrically valid: parts are placed at their own offsets within
        it, there is just less of it. Pass strict=True where an exact length is load-bearing.
        """
        if length <= 0:
            return []
        taken = self.alloc.fill_row(length, color, palette, offset_parity=parity)
        if taken is None and not strict:
            fill = self.alloc.best_fill(length, color, palette, offset_parity=parity)
            taken = list(fill.taken) if fill and fill.taken else None
        return self._record(taken)

    def rect(self, w: int, d: int, color: int, palette: list[str], parity: int = 0,
             strict: bool = False):
        """A w x d rectangle -- or the largest the bin can cover. See `row` for why."""
        if w <= 0 or d <= 0:
            return []
        taken = self.alloc.fill_rect(w, d, color, palette, layer_parity=parity)
        if taken is None and not strict:
            fill = self.alloc.best_rect(w, d, color, palette, layer_parity=parity)
            taken = list(fill.taken) if fill and fill.taken else None
        return self._record(taken)


# ---------------------------------------------------------------------- placement helpers


def _put(taken: list[Taken], x0: int, y: int, z0: int, sub: str) -> list[Placed]:
    """Place an allocator result with its rows running along X."""
    return [Placed(_pid(), t.part, t.color, (x0 + t.dx, y, z0 + t.dz), t.rot, sub) for t in taken]


def _put_z(taken: list[Taken], x0: int, y: int, z0: int, sub: str) -> list[Placed]:
    """Place a 1-wide allocator row turned a quarter turn, so it runs along Z instead.

    The allocator only ever fills along X. Rotating here (rather than asking it for a Z fill)
    keeps one fill implementation and one rollback path.
    """
    out: list[Placed] = []
    for t in taken:
        m = meta_mod.get(t.part)
        rot = 90 if m.w >= m.d else 0
        out.append(Placed(_pid(), t.part, t.color, (x0 + t.dz, y, z0 + t.dx), rot, sub))
    return out


def _run(led: _Ledger, length: int, color: int, palette: list[str],
         x0: int, y: int, z0: int, sub: str, axis: str = "x", parity: int = 0):
    """One 1-wide run of parts along `axis`, or None if we cannot cover it."""
    taken = led.row(length, color, palette, parity)
    if taken is None:
        return None
    return _put(taken, x0, y, z0, sub) if axis == "x" else _put_z(taken, x0, y, z0, sub)


def _slope_band(led: _Ledger, run: int, color: int, rot: int,
                x0: int, y: int, z0: int, sub: str) -> list[Placed] | None:
    """A 2-deep band of 45-degree slopes, all facing the same way.

    `rot` picks the facing, and with it which edge carries the studs:
        0   high edge at +Z, falls toward -Z, band runs along X
        180 high edge at -Z, falls toward +Z, band runs along X
        90  high edge at -X, falls toward +X, band runs along Z
        270 high edge at +X, falls toward -X, band runs along Z
    Degrades to a plain brick band when the bin holds no slopes: the silhouette loses its pitch,
    but the model stands and the course above lands on MORE studs than the slopes offered.
    """
    along_x = rot in (0, 180)
    mark = led.mark()
    placed: list[Placed] = []
    i = 0
    while i < run:
        need = run - i
        for part in SLOPE_45:
            if not meta_mod.has(part):
                continue
            # A slope's LENGTH is its local w; d is always the 2 studs it slopes across. Using
            # max(w, d) would call the 2x1 slope two studs long and leave a hole in the roof.
            plen = meta_mod.get(part).w
            if plen > need:
                continue
            c = led.take(part, color)
            if c is None:
                continue
            pos = (x0 + i, y, z0) if along_x else (x0, y, z0 + i)
            placed.append(Placed(_pid(), part, c, pos, rot, sub))
            i += plen
            break
        else:
            led.undo_to(mark)
            taken = led.rect(run, 2, color, BRICK_ROW) if along_x else \
                led.rect(2, run, color, BRICK_ROW)
            if taken is None:
                led.undo_to(mark)
                return None
            return _put(taken, x0, y, z0, sub)
    return placed


def _shrink(led: _Ledger, once: Callable[..., list[Placed] | None],
            variants: Iterable[dict]) -> tuple[list[Placed] | None, dict | None]:
    """Try each variant in order, rolling the inventory back between attempts.

    This is the degradation path required by invariant 8, at the shape level: when we cannot
    afford the wing that was asked for, we build a smaller wing rather than nothing.
    """
    for kw in variants:
        mark = led.mark()
        parts = once(**kw)
        if parts:
            return parts, kw
        led.undo_to(mark)
    return None, None


# ---------------------------------------------------------------------- self-check


def _components(parts: list[Placed]) -> list[set[str]]:
    """The connected pieces of a part list, by the same rules the validator uses.

    Calling the real `connections()` here rather than a private copy is deliberate: a generator
    that checked its own work against its own idea of a join would only ever prove itself right.
    """
    adj: dict[str, set[str]] = {p.id: set() for p in parts}
    for a, b, _ in connections(Build("_check", "_check", tuple(parts))):
        adj[a].add(b)
        adj[b].add(a)
    seen: set[str] = set()
    out: list[set[str]] = []
    for start in adj:
        if start in seen:
            continue
        stack, comp = [start], set()
        while stack:
            n = stack.pop()
            if n in comp:
                continue
            comp.add(n)
            seen.add(n)
            stack.extend(adj[n] - comp)
        out.append(comp)
    return out


def _stitch(led: _Ledger, parts: list[Placed], color: int, sub: str,
            budget: int = 16) -> list[Placed]:
    """Bridge leftover seams with 1x2 plates until the shape is one object.

    Two parts lying side by side in one layer share no studs, so a fill that happens to break a
    row exactly where the layer above also breaks leaves two pieces that would fall apart. Most
    of the time the offset courses already straddle it; where they do not, one plate laid across
    the seam fixes it. That is cheaper, and more useful to the person holding the bin, than
    refusing to build a wing because a 2x10 and a 2x2 met on a clean line.
    """
    parts = list(parts)
    for _ in range(budget):
        comps = _components(parts)
        if len(comps) <= 1:
            return parts
        owner = {pid: i for i, comp in enumerate(comps) for pid in comp}
        filled: set[tuple[int, int, int]] = set()
        top: dict[tuple[int, int], tuple[int, str, bool]] = {}
        for p in parts:
            m = meta_mod.get(p.part)
            studs = set(m.stud_cells(p.rot))
            for cx, cz in m.cells(p.rot):
                col = (p.x + cx, p.z + cz)
                for k in range(m.h):
                    filled.add((col[0], p.y + k, col[1]))
                lvl = p.y + m.h
                cur = top.get(col)
                if cur is None or lvl > cur[0]:
                    top[col] = (lvl, p.id, (cx, cz) in studs)
        bridge = None
        for (x, z), (lvl, pid, has_stud) in sorted(top.items()):
            if not has_stud:
                continue
            for dx, dz in ((1, 0), (0, 1)):
                other = top.get((x + dx, z + dz))
                if other is None or not other[2] or other[0] != lvl:
                    continue
                if owner[pid] == owner[other[1]]:
                    continue
                if (x, lvl, z) in filled or (x + dx, lvl, z + dz) in filled:
                    continue
                bridge = (x, lvl, z, 0 if dx else 90)
                break
            if bridge:
                break
        if bridge is None:
            return parts
        c = led.take("3023b", color)      # only a 1x2 can straddle a seam; a 1x1 cannot
        if c is None:
            return parts
        x, lvl, z, rot = bridge
        parts.append(Placed(_pid(), "3023b", c, (x, lvl, z), rot, sub))
    return parts


def _finish(led: _Ledger, parts: list[Placed] | None, color: int,
            sub: str) -> list[Placed] | None:
    """Stitch, then REFUSE anything still in more than one piece.

    This is the line between "probably fine" and "checked". A generator that cannot prove its
    own output is one object returns None, and `_shrink` tries a smaller shape instead.
    """
    if not parts:
        return None
    parts = _stitch(led, parts, color, sub)
    return parts if len(_components(parts)) == 1 else None


# ---------------------------------------------------------------------- generators


@generator("vehicle", "creature", "detail")
def wing(span: int = 10, depth: int = 4, *, alloc, color, sub) -> SubResult | None:
    """A flat delta wing: symmetric about its centreline, tapering front to back.

    Two plate layers over the same tapered outline, and the second one is the whole trick. Its
    rows are paired one row LATER than the first layer's -- rows (0), (1,2), (3,4) against rows
    (0,1), (2,3) -- so every seam in one layer is straddled by a part in the other. Build both
    layers the same way and the wing is a stack of loose slats: parts side by side in one layer
    touch, but they do not connect.
    """
    led = _Ledger(alloc)

    def extent(z: int, span: int) -> tuple[int, int]:
        """(x0, length) of row z: each pair of rows steps 2 studs in from BOTH tips, which is
        what keeps the taper symmetric about the centreline."""
        b = z // 2
        return 2 * b, span - 4 * b

    def once(span: int, depth: int) -> list[Placed] | None:
        if span < 2 or depth < 1:
            return None
        rows = 0
        while rows < depth and extent(rows, span)[1] >= 2:
            rows += 1
        if rows == 0:
            return None
        parts: list[Placed] = []
        z = 0
        while z < rows:                                   # layer 0: rows paired from row 0
            n = 2 if z + 1 < rows and extent(z + 1, span) == extent(z, span) else 1
            x0, length = extent(z + n - 1, span)
            taken = led.rect(length, n, color, PLATE_ROW, parity=(z // 2) % 2)
            if taken is None:
                return None
            parts += _put(taken, x0, 0, z, sub)
            z += n
        x0, length = extent(0, span)
        first = led.rect(length, 1, color, PLATE_ROW, parity=1)
        if first is None:
            return None
        parts += _put(first, x0, 1, 0, sub)
        z = 1
        while z < rows:                                   # layer 1: pairs offset by one row
            n = 2 if z + 1 < rows else 1
            x0, length = extent(z + n - 1, span)          # the narrower of the pair, so it is
            taken = led.rect(length, n, color, PLATE_ROW, # fully supported by layer 0
                             parity=(z // 2 + 1) % 2)
            if taken is None:
                return None
            parts += _put(taken, x0, 1, z, sub)
            z += n
        return _finish(led, parts, color, sub)

    parts, kw = _shrink(led, once, [
        {"span": span, "depth": depth},
        {"span": span, "depth": max(1, depth - 1)},
        {"span": max(2, span - 4), "depth": max(1, depth - 1)},
        {"span": max(2, span - 6), "depth": 1},
    ])
    if parts is None:
        return None
    return SubResult(parts, _top_attach(parts),
                     f"{kw['span']}x{kw['depth']} tapered wing, {len(parts)} pieces")


@generator("building", "detail")
def roof_gable(length: int = 8, width: int = 6, *, alloc, color, sub) -> SubResult | None:
    """A pitched roof: courses of opposed slopes stepping inward to a ridge.

    Each course is [slope facing out | bricks | slope facing out] capped by a plate layer that
    spans exactly the studs that course left exposed -- the slopes' high edges and the middle
    fill. The cap is what the next, narrower course stands on, and what stops the two sides of
    the roof being two separate models.
    """
    led = _Ledger(alloc)

    def once(length: int, width: int) -> list[Placed] | None:
        if length < 1 or width < 1:
            return None
        base = led.rect(length, width, color, PLATE_ROW)
        if base is None:
            return None
        parts = _put(base, 0, 0, 0, sub)
        y, z0, w = 1, 0, width
        for _ in range(_MAX_COURSES):
            if w < 4:
                break
            left = _slope_band(led, length, color, 0, 0, y, z0, sub)
            right = _slope_band(led, length, color, 180, 0, y, z0 + w - 2, sub)
            if left is None or right is None:
                return None
            parts += left + right
            middle = w - 4
            if middle > 0:
                fill = led.rect(length, middle, color, BRICK_ROW)
                if fill is None:
                    return None
                parts += _put(fill, 0, y, z0 + 2, sub)
            cap = led.rect(length, w - 2, color, PLATE_ROW, parity=1)
            if cap is None:
                return None
            parts += _put(cap, 0, y + 3, z0 + 1, sub)
            y += 4
            z0 += 1
            w -= 2
        ridge = led.rect(length, w, color, BRICK_ROW)
        if ridge is None:
            return None
        parts += _put(ridge, 0, y, z0, sub)
        return _finish(led, parts, color, sub)

    parts, kw = _shrink(led, once, [
        {"length": length, "width": width},
        {"length": length, "width": max(1, width - 2)},
        {"length": max(1, length - 2), "width": max(1, width - 2)},
        {"length": max(1, length - 4), "width": min(width, 3)},
        {"length": max(1, length - 4), "width": min(width, 2)},
    ])
    if parts is None:
        return None
    return SubResult(parts, _top_attach(parts),
                     f"gable roof {kw['length']}x{kw['width']}, {len(parts)} pieces")


@generator("building", "detail")
def arch(width: int = 2, height: int = 6, *, alloc, color, sub) -> SubResult | None:
    """A doorway or window: two piers and a lintel that spans the opening in ONE piece.

    A lintel assembled from several short bricks has a piece in the middle resting on nothing,
    which the validator rightly refuses. So the opening is only as wide as the longest brick we
    actually own, and if we own nothing long enough the opening SHRINKS until we do. That is the
    honest degradation: a narrower door, not a door that falls in.
    """
    led = _Ledger(alloc)
    courses = max(1, height // 3)

    def once(width: int, pier: int) -> list[Placed] | None:
        if width < 1:
            return None
        total = width + 2 * pier
        span = _take_span(led, total, color)
        if span is None:
            return None
        part, span_color, plen = span
        parts: list[Placed] = []
        y = 0
        for _ in range(courses):
            for x in (0, total - pier):
                run = _run(led, pier, color, BRICK_ROW, x, y, 0, sub)
                if run is None:
                    return None
                parts += run
            y += 3
        parts.append(Placed(_pid(), part, span_color, (0, y, 0), 0, sub))
        y += meta_mod.get(part).h
        # A capping row over the lintel: it ties the lintel to anything built above and gives
        # _top_attach a full-width surface instead of the lintel's own studs alone.
        cap = _run(led, max(total, plen), color, PLATE_ROW, 0, y, 0, sub)
        if cap is not None:
            parts += cap
        return _finish(led, parts, color, sub)

    # Two-stud piers first at every opening width, then one-stud piers: a thinner pier is a
    # worse-looking doorway, but it buys two studs of opening out of the same lintel.
    parts, kw = _shrink(led, once, [{"width": w, "pier": p}
                                    for p in (2, 1) for w in range(width, 0, -1)])
    if parts is None:
        return None
    note = f"arch, {kw['width']}-stud opening, {courses * 3} plates tall"
    if kw["width"] != width:
        note += f" (asked for {width}, no brick long enough to span it)"
    return SubResult(parts, _top_attach(parts), note)


def _take_span(led: _Ledger, need: int, color: int) -> tuple[str, int, int] | None:
    """The SHORTEST single part at least `need` studs long that we own. Bricks before plates."""
    for palette in (BRICK_ROW, PLATE_ROW):
        options = sorted(
            ((max(meta_mod.get(p).w, meta_mod.get(p).d), p) for p in palette if meta_mod.has(p)),
            key=lambda pl: pl[0],
        )
        for plen, part in options:
            if plen < need:
                continue
            c = led.take(part, color)
            if c is not None:
                return part, c, plen
    return None


@generator("building", "detail")
def turret(radius: int = 2, height: int = 9, *, alloc, color, sub) -> SubResult | None:
    """A hollow round-ish tower: a square ring whose corners change hands every course.

    Honest about the shape: a true cylinder needs curved wall parts we cannot assume are in a
    loose bin, so this is a square ring softened by 2x2 corner blocks where they are affordable.
    The important part is the alternation -- on even courses the North and South runs own the
    corners, on odd courses the East and West runs do. That overlap is what ties the four walls
    into one object; build every course the same way and you get four unconnected towers.
    """
    led = _Ledger(alloc)
    d = max(1, 2 * radius)
    courses = max(1, height // 3)

    def once(d: int, courses: int) -> list[Placed] | None:
        parts: list[Placed] = []
        for k in range(min(courses, _MAX_COURSES)):
            layer = _ring_layer(led, d, k * 3, color, sub, k % 2, BRICK_ROW)
            if layer is None:
                return None
            parts += layer
        # Always cap with a plate ring at the opposite parity. A one-course turret would
        # otherwise be four loose walls, and the cap gives children a surface to attach to.
        cap = _ring_layer(led, d, courses * 3, color, sub, courses % 2, PLATE_ROW)
        if cap is None:
            return None
        return _finish(led, parts + cap, color, sub)

    parts, kw = _shrink(led, once, [
        {"d": d, "courses": courses},
        {"d": d, "courses": max(1, courses - 1)},
        {"d": max(1, d - 1), "courses": max(1, courses // 2)},
        {"d": max(1, d - 2), "courses": 1},
    ])
    if parts is None:
        return None
    return SubResult(parts, _top_attach(parts),
                     f"{kw['d']}-stud turret, {kw['courses']} courses, {len(parts)} pieces")


def _ring_layer(led: _Ledger, d: int, y: int, color: int, sub: str,
                parity: int, palette: list[str]) -> list[Placed] | None:
    """One course of a hollow d x d ring. `parity` decides which pair of walls owns the corners."""
    if d <= 1:
        taken = led.row(1, color, palette)
        return _put(taken, 0, y, 0, sub) if taken else None

    parts: list[Placed] = []
    blocks = 0
    if parity == 0 and d >= 5 and palette is BRICK_ROW:
        # 2x2 corner blocks round the profile off and stiffen the join between two walls.
        # Purely opportunistic: if the bin has no 2x2s the plain runs below cover the same cells.
        mark = led.mark()
        corner_parts: list[Placed] = []
        for cx, cz in ((0, 0), (d - 2, 0), (0, d - 2), (d - 2, d - 2)):
            c = led.take(STUD_BLOCK, color)
            if c is None:
                led.undo_to(mark)
                corner_parts = []
                break
            corner_parts.append(Placed(_pid(), STUD_BLOCK, c, (cx, y, cz), 0, sub))
        parts += corner_parts
        blocks = len(corner_parts)

    if blocks:
        runs = [("x", 2, d - 4, 0), ("x", 2, d - 4, d - 1),
                ("z", 2, d - 4, 0), ("z", 2, d - 4, d - 1)]
    elif parity == 0:
        runs = [("x", 0, d, 0), ("x", 0, d, d - 1)]
        if d > 2:
            runs += [("z", 1, d - 2, 0), ("z", 1, d - 2, d - 1)]
    else:
        runs = [("z", 0, d, 0), ("z", 0, d, d - 1)]
        if d > 2:
            runs += [("x", 1, d - 2, 0), ("x", 1, d - 2, d - 1)]

    for axis, start, length, fixed in runs:
        if length <= 0:
            continue
        if axis == "x":
            run = _run(led, length, color, palette, start, y, fixed, sub, "x")
        else:
            run = _run(led, length, color, palette, fixed, y, start, sub, "z")
        if run is None:
            return None
        parts += run
    return parts


@generator("vehicle", "creature")
def cockpit(length: int = 6, width: int = 4, *, alloc, color, sub) -> SubResult | None:
    """A tapered nose: courses stepping in from the front and both sides, finished with slopes.

    Every course sits strictly inside the one below it, so support is automatic and the taper is
    visible from any angle. The slope band on the front of the top course is what turns a
    staircase into a nose; if there are no slopes in the bin it becomes a plate and the shape is
    merely blunt rather than broken.
    """
    led = _Ledger(alloc)

    def once(length: int, width: int, steps: int) -> list[Placed] | None:
        if length < 2 or width < 1:
            return None
        parts: list[Placed] = []
        y = 0
        last: tuple[int, int, int] | None = None   # (x0, z0, depth) of the top course
        for k in range(min(steps, _MAX_COURSES)):
            x0, z0 = k, k
            xl, zd = length - k, width - 2 * k
            if xl < 2 or zd < 1:
                break
            # The parity is computed from the course's GLOBAL z origin, not from k. A course
            # that is inset one row AND flipped is back in step with the course below it, and
            # its 2-wide parts then sit directly on the ones beneath instead of bridging them.
            taken = led.rect(xl, zd, color, BRICK_ROW, parity=(k + z0) % 2)
            if taken is None:
                return None
            parts += _put(taken, x0, y, z0, sub)
            last = (x0, z0, zd)
            y += 3
        if last is None:
            return None
        nose = _slope_band(led, last[2], color, 270, last[0], y, last[1], sub)
        if nose is not None:
            parts += nose
        return _finish(led, parts, color, sub)

    parts, kw = _shrink(led, once, [
        {"length": length, "width": width, "steps": 3},
        {"length": length, "width": width, "steps": 2},
        {"length": max(2, length - 2), "width": max(1, width - 2), "steps": 2},
        {"length": max(2, length - 2), "width": max(1, width - 2), "steps": 1},
    ])
    if parts is None:
        return None
    return SubResult(parts, _top_attach(parts),
                     f"tapered nose {kw['length']}x{kw['width']}, {kw['steps']} steps")


@generator("creature", "building", "vehicle")
def legs(count: int = 4, height: int = 6, *, alloc, color, sub) -> SubResult | None:
    """`count` columns in a row, evenly spaced, tied together at the top.

    The tie is not decoration. Columns standing on the ground share no studs, so legs without a
    tie are `count` separate models. Each tie reaches from the LAST stud of one leg to the FIRST
    stud of the next -- one stud shorter than feels natural, and deliberately so: a tie spanning
    leg-start to leg-end would overlap its neighbour by two studs and put two bricks in the same
    place. Spacing is chosen from what we own rather than from what was asked: a 2x4 plate in
    the bin means legs 4 studs apart, a 2x2 means 2.
    """
    led = _Ledger(alloc)
    count = max(1, count)
    courses = max(1, height // 3)

    def once(size: int, spacing: int, tie: str | None) -> list[Placed] | None:
        if spacing < size or (tie is not None and not meta_mod.has(tie)):
            return None
        parts: list[Placed] = []
        for i in range(count):
            column = _column(led, i * spacing, 0, courses, size, color, sub)
            if column is None:
                return None
            parts += column
        y = courses * 3
        if count == 1:
            # Nothing to tie. A plate cap still gives children a surface, and for a leg built
            # from paired 1x2s it is what holds the pair together.
            cap = led.rect(size, size, color, PLATE_ROW)
            if cap is None:
                return None
            return _finish(led, parts + _put(cap, 0, y, 0, sub), color, sub)
        if tie is not None:
            for i in range(count - 1):
                c = led.take(tie, color)
                if c is None:
                    return None
                parts.append(Placed(_pid(), tie, c, (i * spacing + size - 1, y, 0), 0, sub))
            return _finish(led, parts, color, sub)
        # 1-stud legs cannot be tied pairwise without two ties meeting on the same stud, so
        # they get ONE part long enough to reach every leg.
        reach = (count - 1) * spacing + 1
        span = _take_span(led, reach, color)
        if span is not None:
            part, span_color, _ = span
            parts.append(Placed(_pid(), part, span_color, (0, y, 0), 0, sub))
            return _finish(led, parts, color, sub)
        if spacing > 1:
            return None
        # Legs standing shoulder to shoulder need no single part: an ordinary plate row lands
        # on legs the whole way along, and _finish stitches whatever seam is left over.
        row = _run(led, reach, color, PLATE_ROW, 0, y, 0, sub)
        if row is None:
            return None
        return _finish(led, parts + row, color, sub)

    parts, kw = _shrink(led, once, [
        {"size": 2, "spacing": 4, "tie": "3020"},    # plate 2x4 between 2x2 legs
        {"size": 2, "spacing": 2, "tie": "3022"},    # plate 2x2 between touching 2x2 legs
        {"size": 1, "spacing": 2, "tie": None},      # one long plate over 1x1 legs
        {"size": 1, "spacing": 1, "tie": None},
    ])
    if parts is None:
        return None
    return SubResult(parts, _top_attach(parts),
                     f"{count} legs, {kw['size']}x{kw['size']}, "
                     f"{kw['spacing']} studs apart, {courses * 3} plates tall")


def _column(led: _Ledger, x: int, z: int, courses: int, size: int,
            color: int, sub: str) -> list[Placed] | None:
    """A vertical column `size` studs square. Degrades 2x2 -> paired 1x2 -> nothing."""
    parts: list[Placed] = []
    for k in range(min(courses, _MAX_COURSES)):
        y = k * 3
        if size == 1:
            c = led.take(PIN_BLOCK, color)
            if c is None:
                return None
            parts.append(Placed(_pid(), PIN_BLOCK, c, (x, y, z), 0, sub))
            continue
        c = led.take(STUD_BLOCK, color)
        if c is not None:
            parts.append(Placed(_pid(), STUD_BLOCK, c, (x, y, z), 0, sub))
            continue
        # Out of 2x2s: two 1x2s per course, turned a quarter turn each course so that the pair
        # below is bridged by the pair above. Laid the same way every course they never touch.
        rot = 0 if k % 2 == 0 else 90
        for off in (0, 1):
            c = led.take(HALF_BLOCK, color)
            if c is None:
                return None
            pos = (x, y, z + off) if rot == 0 else (x + off, y, z)
            parts.append(Placed(_pid(), HALF_BLOCK, c, pos, rot, sub))
    return parts


@generator("creature", "detail")
def neck(height: int = 9, lean: int = 1, *, alloc, color, sub) -> SubResult | None:
    """A stepped column that leans, for a neck, a tail or a chimney.

    `lean` is the sideways step per course, clamped to -1..1: a 2-stud course stepped 2 studs
    sideways shares no studs with the course below it, which is a pile of bricks on the floor,
    not a neck. Leaning therefore costs exactly one stud of overlap per course and the shape
    stays a real structure.
    """
    led = _Ledger(alloc)
    lean = max(-1, min(1, int(lean)))
    courses = max(1, height // 3)
    parts: list[Placed] = []
    for k in range(min(courses, _MAX_COURSES)):
        x, y = k * lean, k * 3
        taken = led.take_any((STUD_BLOCK, HALF_BLOCK) if lean else
                             (STUD_BLOCK, HALF_BLOCK, PIN_BLOCK), color)
        if taken is None:
            led.undo_to(0)
            return None
        part, c = taken
        parts.append(Placed(_pid(), part, c, (x, y, 0), 0, sub))
    return SubResult(parts, _top_attach(parts),
                     f"{courses}-course neck, lean {lean} per course")


@generator("detail", "building")
def fence(length: int = 8, height: int = 6, *, alloc, color, sub) -> SubResult | None:
    """A thin rail: two plate courses, pickets every other stud, a tiled top.

    The second plate course is deliberately offset one stud from the first. Without it two
    identical courses have identical seams and the fence is several loose segments; with it
    every upper piece straddles a lower seam and the base is one object. The rail uses
    even-length pieces laid from x=0, so every piece begins on a picket -- a 1x1 tile landing
    between two pickets would be resting on air.
    """
    led = _Ledger(alloc)

    def once(length: int) -> list[Placed] | None:
        if length < 1:
            return None
        base = _run(led, length, color, PLATE_ROW, 0, 0, 0, sub)
        if base is None:
            return None
        parts = list(base)
        tie = _offset_row(led, length, color, sub, y=1)
        if tie is None:
            return None
        parts += tie

        picket = _in_stock(led.alloc, (PIN_BLOCK, "3024"), color)   # brick 1x1, then plate 1x1
        if picket is None:
            return None
        unit_h = meta_mod.get(picket).h
        units = max(0, (height - 3) // unit_h)
        for x in range(0, length, 2):
            for u in range(units):
                c = led.take(picket, color)
                if c is None:
                    return None
                parts.append(Placed(_pid(), picket, c, (x, 2 + u * unit_h, 0), 0, sub))
        rail_y = 2 + units * unit_h

        covered = length - (length % 2)
        rail = _even_row(led, covered, color, rail_y, sub)
        if rail is None:
            return None
        parts += rail
        if length % 2:
            # The odd last stud has a picket under it, so a single tile there is supported.
            got = led.take_any(("3070b", "3024"), color)
            if got is not None:
                parts.append(Placed(_pid(), got[0], got[1], (length - 1, rail_y, 0), 0, sub))
        return _finish(led, parts, color, sub)

    parts, kw = _shrink(led, once, [{"length": length},
                                    {"length": max(1, length - 2)},
                                    {"length": max(1, length // 2)}])
    if parts is None:
        return None
    return SubResult(parts, _top_attach(parts),
                     f"{kw['length']}-stud fence, {height} plates tall")


def _in_stock(alloc: Allocator, parts: Iterable[str], color: int) -> str | None:
    """The first of `parts` we still own, in any colour. A probe, not a take."""
    for part in parts:
        if meta_mod.has(part) and alloc.best_colors(part, color):
            return part
    return None


def _offset_row(led: _Ledger, length: int, color: int, sub: str, y: int) -> list[Placed] | None:
    """A plate course deliberately offset one stud, so its seams cannot line up with the one
    below. A 1x1 at the start is the cheapest way to guarantee it; `offset_parity` only shifts
    the seam when the bin holds more than one length of plate."""
    mark = led.mark()
    c = led.take("3024", color)
    if c is not None:
        rest = led.row(length - 1, color, PLATE_ROW)
        if rest is not None:
            return ([Placed(_pid(), "3024", c, (0, y, 0), 0, sub)]
                    + _put(rest, 1, y, 0, sub))
        led.undo_to(mark)
    return _run(led, length, color, PLATE_ROW, 0, y, 0, sub, parity=1)


def _even_row(led: _Ledger, length: int, color: int, y: int, sub: str) -> list[Placed] | None:
    """Cover `length` studs with even-length pieces only, tiles before plates."""
    if length <= 0:
        return []
    for palette in (EVEN_TILES, EVEN_PLATES):
        mark = led.mark()
        parts: list[Placed] = []
        x = 0
        while x < length:
            need = length - x
            for part in palette:
                if not meta_mod.has(part):
                    continue
                plen = max(meta_mod.get(part).w, meta_mod.get(part).d)
                if plen > need:
                    continue
                c = led.take(part, color)
                if c is None:
                    continue
                parts.append(Placed(_pid(), part, c, (x, y, 0), 0, sub))
                x += plen
                break
            else:
                led.undo_to(mark)
                parts = []
                break
        if parts:
            return parts
    return None
