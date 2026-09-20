"""Inventory-constrained allocation: covering a region using ONLY bricks you own.

This is the project's actual contribution. The ecosystem sweep found generative LEGO systems
(BrickGPT/LegoGPT, legolization, BrickNet) and mature instruction tooling -- and nothing that
conditions generation on a finite part set. BrickNet's own paper lists that as future work.

So the inventory is not a check applied afterwards. It is a constraint the allocator cannot
violate: `take()` is the only way to obtain a part, and it fails when you are out.

THE LONG-TAIL PROBLEM
---------------------
Measured on the user's own bin: 74 detections -> 57 identified pieces across 49 distinct
part+colour combinations. Almost everything is quantity ONE, so a generator that wants four red
2x4s finds one and gives up -- which is how "build me a rover" collapsed to a three-part build.

Ignoring colour, the SAME bin is 29 distinct parts with twelve brick 2x4s. Colour is also our
weakest recognition stage (0.70 accuracy), so insisting on it is spending our least reliable
signal to make the build worse. Three fixes live in here, in order of how much they bought:

1. **Colour pooling** (`color_policy`, and per-row `color_mode` from Contract 1). A request for a
   red 2x4 may be satisfied by the blue one, and the substitution is recorded so the UI can say
   so. `"exact"` restores the old behaviour.
2. **Part substitution** (`core.substitute`). A row that wants a brick 1x4 will take two 1x2s.
3. **Use what you have** (`best_fill`, `best_rect`). Return the largest thing that CAN be built
   and report the shortfall, instead of returning None and taking the whole subassembly with it.

None of this may ever hand out more than the bin holds. That is the premise of the project:
`remaining` never goes negative, and the sum of `used` never exceeds the sum of the inventory.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import meta as meta_mod
from .model import Inventory
from .substitute import Rule, rules_for

# Row-fill palettes, longest first. Keys are official LDraw filenames (bricknet vocabulary).
BRICK_ROW = ["3008", "3009", "3010", "3622", "3004", "3005"]           # 1x8,1x6,1x4,1x3,1x2,1x1
PLATE_ROW = ["3460", "3666", "3710", "3623", "3023b", "3024"]          # 1x8,1x6,1x4,1x3,1x2,1x1
TILE_ROW = ["2431", "63864", "3069b", "3070b"]                         # 1x4,1x3,1x2,1x1

# 2-wide parts. These are what make a layer STRUCTURALLY CONNECTED: a row of 1xN parts laid side
# by side is not joined to the row beside it -- physically true, and the validator says so. A
# 2-wide part bridges two rows at once.
BRICK_WIDE = ["3006", "3007", "2456", "3001", "3002", "3003"]          # 2x10,2x8,2x6,2x4,2x3,2x2
PLATE_WIDE = ["3832", "3034", "3795", "3020", "3021", "3022"]          # 2x10,2x8,2x6,2x4,2x3,2x2

_WIDE_FOR = {id(BRICK_ROW): BRICK_WIDE, id(PLATE_ROW): PLATE_WIDE}

#: Colour policies, in order of how much freedom they give the allocator.
#:   exact   -- never hand out a colour that was not asked for (the pre-long-tail behaviour)
#:   similar -- pool across colour, but respect a row that CV was confident about
#:   ignore  -- colour is irrelevant; any colour of the part satisfies any request
COLOR_POLICIES = ("exact", "similar", "ignore")
DEFAULT_COLOR_POLICY = "similar"

# Every loop that searches gets a budget (invariant 8).
SUBSTITUTE_DEPTH = 2        # how many times a replacement may itself be replaced
BEST_FIT_BUDGET = 64        # how many shrunken shapes `best_rect` will try before giving up

# Debug-friendly names only, and deliberately a copy of the table in `api/llm/prompts.py`:
# `core` does not import `api`. Colour is computed from pixels, never chosen by a model.
_COLOR_NAMES = {
    0: "black", 1: "blue", 2: "green", 4: "red", 14: "yellow", 15: "white",
    19: "tan", 25: "orange", 70: "reddish brown", 71: "light grey", 72: "dark grey",
}


def color_name(code: int) -> str:
    return _COLOR_NAMES.get(code, f"colour {code}")


def part_name(part: str) -> str:
    return meta_mod.get(part).name if meta_mod.has(part) else part


@dataclass
class Taken:
    """One part the allocator has handed out, positioned relative to the fill's own origin.

    `dx` runs along the fill; `dz` across it (0 or 1 -- only a width substitution ever sets it).
    There is no `dy`: row filling never changes height, which is why height-changing
    substitution rules are excluded from it.
    """

    part: str
    rot: int
    dx: int
    dz: int
    length: int
    color: int = 0


@dataclass(frozen=True, slots=True)
class Substitution:
    """A record of the allocator not giving you quite what you asked for.

    `human` is user-facing copy, written once here so the UI, the tape and the repair prompt all
    say the same thing (the same discipline as `Report.human` in Contract 3).
    """

    kind: str                       # color | part
    part: str                       # what was asked for
    human: str
    wanted_color: int | None = None
    used_color: int | None = None
    rule: str | None = None         # substitute.Rule.id, when kind == "part"
    penalty: int = 0


@dataclass(frozen=True, slots=True)
class RowFill:
    """What `best_fill` could actually build, and by how much it fell short."""

    taken: tuple[Taken, ...]
    requested: int
    covered: int
    substitutions: tuple[Substitution, ...] = ()

    @property
    def shortfall(self) -> int:
        return self.requested - self.covered

    @property
    def complete(self) -> bool:
        return self.covered >= self.requested

    @property
    def human(self) -> str:
        if self.complete:
            return f"filled {self.covered} studs"
        return (f"you asked for {self.requested} studs and the bin covers {self.covered}; "
                f"{self.shortfall} short")


@dataclass(frozen=True, slots=True)
class RectFill:
    """What `best_rect` could actually build. `covered` is a real rectangle, never ragged."""

    taken: tuple[Taken, ...]
    requested: tuple[int, int]
    covered: tuple[int, int]
    substitutions: tuple[Substitution, ...] = ()

    @property
    def complete(self) -> bool:
        return self.covered == self.requested

    @property
    def human(self) -> str:
        rw, rd = self.requested
        cw, cd = self.covered
        if self.complete:
            return f"filled {cw}x{cd}"
        return f"you asked for {rw}x{rd} and the bin covers {cw}x{cd}"


class OutOfBricks(RuntimeError):
    pass


class Allocator:
    """Hands out parts from a finite inventory. The only way to obtain a brick.

    `color_policy` and `color_modes` decide how freely colour may be pooled. `color_modes` is
    Contract 1's per-row `color_mode` keyed by `(part, colour)`: a row CV was confident about
    (`"exact"`) is only ever handed out for a request in that same colour, while a row it was
    unsure about (`"similar"`, the default) will satisfy a request in any colour.
    """

    def __init__(self, inventory: Inventory, *,
                 color_policy: str = DEFAULT_COLOR_POLICY,
                 color_modes: dict[tuple[str, int], str] | None = None,
                 substitute: bool = True):
        if color_policy not in COLOR_POLICIES:
            raise ValueError(f"color_policy must be one of {COLOR_POLICIES}, got {color_policy!r}")
        self.remaining: dict[tuple[str, int], int] = dict(inventory.items)
        self.used: dict[tuple[str, int], int] = {}
        self.color_policy = color_policy
        self.color_modes: dict[tuple[str, int], str] = dict(color_modes or {})
        self.substitute = substitute
        self.substitutions: list[Substitution] = []
        # Which colour was really handed out for each (part, requested colour), newest last.
        # `give_back` pops it, so a caller that records the colour it ASKED for still returns
        # the colour it was GIVEN -- otherwise a rollback quietly invents inventory.
        self._alias: dict[tuple[str, int], list[int]] = {}

    # ---------------------------------------------------------------- bookkeeping

    def have(self, part: str, color: int) -> int:
        return self.remaining.get((part, color), 0)

    def have_any_color(self, part: str) -> int:
        return sum(n for (p, _), n in self.remaining.items() if p == part and n > 0)

    @property
    def total_used(self) -> int:
        return sum(self.used.values())

    def _snapshot(self) -> tuple:
        """A cheap exact copy of everything a failed attempt can touch.

        Substitution makes rollback by `give_back` fiddly (a replaced part was never taken in the
        colour it stood in for), and the one thing this class may never get wrong is the count.
        The dicts hold tens of rows, so copying them is cheaper than being clever.
        """
        return (dict(self.remaining), dict(self.used),
                {k: list(v) for k, v in self._alias.items()}, len(self.substitutions))

    def _restore(self, snap: tuple) -> None:
        self.remaining, self.used, self._alias = snap[0], snap[1], snap[2]
        del self.substitutions[snap[3]:]

    # ---------------------------------------------------------------- colour pooling

    def _poolable(self, part: str, color: int, policy: str) -> bool:
        """May a row of `(part, color)` stand in for a DIFFERENT requested colour?"""
        if policy == "ignore":
            return True
        return self.color_modes.get((part, color), "similar") != "exact"

    def best_colors(self, part: str, preferred: int, *, policy: str | None = None) -> list[int]:
        """Preferred colour first, then whatever else we have most of.

        Under `"exact"` this is the preferred colour or nothing. Ties keep inventory order, which
        is insertion order and therefore reproducible (invariant 6).
        """
        pol = policy or self.color_policy
        head = [preferred] if self.have(part, preferred) > 0 else []
        if pol == "exact":
            return head
        others = sorted(
            (c for (p, c), n in self.remaining.items()
             if p == part and n > 0 and c != preferred and self._poolable(part, c, pol)),
            key=lambda c: -self.remaining[(part, c)],
        )
        return head + others

    # ---------------------------------------------------------------- taking

    def take_color(self, part: str, color: int, *, policy: str | None = None) -> int | None:
        """Take one `part`, pooling across colour per the policy. Returns the colour taken.

        Prefer this over `take` in new code: the caller has to place the part in the colour it
        was actually given, not the one it asked for, or the build claims bricks the bin does
        not hold and the validator rejects it.
        """
        for c in self.best_colors(part, color, policy=policy):
            if self.remaining.get((part, c), 0) <= 0:
                continue
            self.remaining[(part, c)] -= 1
            self.used[(part, c)] = self.used.get((part, c), 0) + 1
            if c != color:
                self._alias.setdefault((part, color), []).append(c)
                self.substitutions.append(Substitution(
                    kind="color", part=part, wanted_color=color, used_color=c,
                    human=(f"used {color_name(c)} {part_name(part)} instead of "
                           f"{color_name(color)} -- you had no {color_name(color)} one"),
                ))
            return c
        return None

    def take(self, part: str, color: int) -> bool:
        """Take EXACTLY this part in EXACTLY this colour. True if the bin could pay for it.

        This one does not pool, and that is deliberate. Its callers place the part in the colour
        they asked for, so an allocator that quietly handed over a different colour would produce
        a build claiming bricks the bin does not hold -- which is precisely the invariant this
        module exists to defend. (Measured, not theorised: making `take` pool turned the sculpt
        backend's own fixture red and it failed OUT_OF_BUDGET.)

        Pooling belongs to `take_color`, which returns the colour it gave you. The normal caller
        pattern -- `best_colors()` for the ranked colours, then `take()` on the one it chose --
        pools correctly because the choice and the placement then agree.
        """
        return self.take_color(part, color, policy="exact") is not None

    def give_back(self, part: str, color: int) -> None:
        """Return one `part`, undoing the colour substitution if there was one.

        Callers disagree about which colour they hand back. A generator returns the colour it was
        GIVEN (it kept the `Taken`); a caller that only ever saw `take()` returns the colour it
        ASKED for. So: if we are actually holding one of that colour, that is the one coming
        back; only when we are not do we consult the substitution log. Getting this wrong does
        not merely mislabel a brick -- it makes `used` and `remaining` disagree, and then the
        build spends bricks the bin never paid for.
        """
        if self.used.get((part, color), 0) > 0:
            actual = color
        else:
            stack = self._alias.get((part, color))
            actual = stack.pop() if stack else color
        self.remaining[(part, actual)] = self.remaining.get((part, actual), 0) + 1
        self.used[(part, actual)] = max(0, self.used.get((part, actual), 0) - 1)
        if actual != color:
            for i in range(len(self.substitutions) - 1, -1, -1):
                s = self.substitutions[i]
                if (s.kind == "color" and s.part == part
                        and s.wanted_color == color and s.used_color == actual):
                    del self.substitutions[i]
                    break

    # ---------------------------------------------------------------- substitution

    def _taken_for(self, part: str, dx: int, dz: int, color: int) -> Taken:
        """A placed result. Rotation puts the part's long axis along the fill direction."""
        m = meta_mod.get(part)
        return Taken(part, 0 if m.w >= m.d else 90, dx, dz, max(m.w, m.d), color)

    def _expand(self, part: str, color: int, dx: int, dz: int, *,
                max_width: int, depth: int) -> list[Taken] | None:
        """One `part` at (dx, dz) -- directly if we own it, else via a substitution rule.

        Only flat rules are used: `Taken` has no dy, so stacking three plates where a brick was
        wanted has to be done by a caller that understands height. That rule still exists in
        `core.substitute` for such a caller; it is simply not reachable from row filling.
        """
        if not meta_mod.has(part):
            return None
        c = self.take_color(part, color)
        if c is not None:
            return [self._taken_for(part, dx, dz, c)]
        if depth <= 0:
            return None
        for rule in rules_for(part, flat_only=True, max_width=max_width):
            if dz + rule.width > max_width:
                continue
            snap = self._snapshot()
            out: list[Taken] = []
            for ch in rule.children:
                got = self._expand(ch.part, color, dx + ch.dx, dz + ch.dz,
                                   max_width=max_width, depth=depth - 1)
                if got is None:
                    out = []
                    break
                out += got
            if out:
                self.substitutions.insert(snap[3], self._part_sub(part, rule))
                return out
            self._restore(snap)
        return None

    @staticmethod
    def _part_sub(part: str, rule: Rule) -> Substitution:
        return Substitution(kind="part", part=part, rule=rule.id, penalty=rule.penalty,
                            human=f"no {part_name(part)} left, so {rule.why}")

    # ---------------------------------------------------------------- row filling

    def fill_row(self, length: int, color: int, palette: list[str],
                 allow_other_colors: bool = True, offset_parity: int = 0,
                 substitute: bool | None = None) -> list[Taken] | None:
        """Cover `length` studs in a 1-wide row. Longest piece that fits and is in stock.

        `offset_parity` nudges the first piece shorter so seams stagger between layers --
        masonry bond, which is what stops the model splitting along a vertical line.

        When no palette part of a usable length is left, the row falls back on `core.substitute`
        (two 1x2s where a 1x4 was wanted). Width-splitting rules are refused here: this row is
        one stud deep and the replacement has to stay inside it.
        """
        sub_on = self.substitute if substitute is None else substitute
        entry = self._snapshot()
        out: list[Taken] = []
        x = 0
        first = True
        while x < length:
            need = length - x
            placed = False
            for part in palette:
                if not meta_mod.has(part):
                    continue
                m = meta_mod.get(part)
                plen = max(m.w, m.d)
                if plen > need:
                    continue
                # Stagger the seam on odd courses by refusing a single part that fills the whole
                # row -- but only when the row is long enough for staggering to mean anything.
                # A 2-stud row has nothing to stagger against, and skipping its only 1x2 made the
                # row unfillable whenever 1x1s were out of stock (which is most real bins).
                if first and offset_parity and plen == need and need > 2:
                    continue
                c = self.take_color(part, color,
                                    policy=None if allow_other_colors else "exact")
                if c is None:
                    continue
                out.append(self._taken_for(part, x, 0, c))
                x += plen
                placed = True
                first = False
                break
            if not placed and sub_on:
                for part in palette:
                    if not meta_mod.has(part):
                        continue
                    plen = max(meta_mod.get(part).w, meta_mod.get(part).d)
                    if plen > need or (first and offset_parity and plen == need
                                       and plen > 1 and need > 1):
                        continue
                    got = self._expand(part, color, x, 0,
                                       max_width=1, depth=SUBSTITUTE_DEPTH)
                    if got is not None:
                        out += got
                        x += plen
                        placed = True
                        first = False
                        break
            if not placed:
                self._restore(entry)
                return None
        return out

    def fill_band(self, length: int, color: int, wide_palette: list[str],
                  offset_parity: int = 0, substitute: bool | None = None) -> list[Taken] | None:
        """Cover a `length` x 2 band with 2-wide parts, so the two rows are joined.

        Substitution may replace a 2-wide part with two 1-wide ones side by side. That gives up
        the bridging this method exists for, so the rule carries the highest penalty and is only
        reached once every 2-wide option is gone -- at which point the alternative is no build.
        """
        sub_on = self.substitute if substitute is None else substitute
        entry = self._snapshot()
        out: list[Taken] = []
        x = 0
        first = True
        while x < length:
            need = length - x
            placed = False
            for part in wide_palette:
                if not meta_mod.has(part):
                    continue
                m = meta_mod.get(part)
                plen = max(m.w, m.d)
                if min(m.w, m.d) != 2 or plen > need:
                    continue
                # Same rule as fill_row: only stagger when the band is long enough to matter.
                if first and offset_parity and plen == need and need > 2:
                    continue
                c = self.take_color(part, color)
                if c is None:
                    continue
                out.append(self._taken_for(part, x, 0, c))
                x += plen
                placed = True
                first = False
                break
            if not placed and sub_on:
                for part in wide_palette:
                    if not meta_mod.has(part):
                        continue
                    m = meta_mod.get(part)
                    plen = max(m.w, m.d)
                    if min(m.w, m.d) != 2 or plen > need:
                        continue
                    if first and offset_parity and plen == need and plen > 2 and need > 2:
                        continue
                    got = self._expand(part, color, x, 0,
                                       max_width=2, depth=SUBSTITUTE_DEPTH)
                    if got is not None:
                        out += got
                        x += plen
                        placed = True
                        first = False
                        break
            if not placed:
                self._restore(entry)
                return None
        return out

    def fill_rect(self, w: int, d: int, color: int, palette: list[str],
                  layer_parity: int = 0, substitute: bool | None = None) -> list[Taken] | None:
        """Cover a w x d rectangle, joining rows with 2-wide parts wherever possible.

        Row pairing starts at z=0 on even layers and z=1 on odd layers, so a leftover single
        row in an odd-depth rectangle is bridged by the layer above it rather than left loose.
        """
        wide = _WIDE_FOR.get(id(palette))
        entry = self._snapshot()
        out: list[Taken] = []
        z = 0
        if wide and d >= 3 and layer_parity:
            row = self.fill_row(w, color, palette, offset_parity=1, substitute=substitute)
            if row is None:
                self._restore(entry)
                return None
            out += row
            z = 1
        while z < d:
            if wide and d - z >= 2:
                band = self.fill_band(w, color, wide, offset_parity=(z + layer_parity) % 2,
                                      substitute=substitute)
                if band is not None:
                    for t in band:
                        # `+=`, not `=`: a width substitution already put this piece on row 1 of
                        # the band, and clobbering that would stack two parts in the same cell.
                        t.dz += z
                        out.append(t)
                    z += 2
                    continue
            row = self.fill_row(w, color, palette, offset_parity=(z + layer_parity) % 2,
                                substitute=substitute)
            if row is None:
                self._restore(entry)
                return None
            for t in row:
                t.dz += z
                out.append(t)
            z += 1
        return out

    # ---------------------------------------------------------------- use what you have

    def best_fill(self, length: int, color: int, palette: list[str], *,
                  offset_parity: int = 0, min_length: int = 1,
                  substitute: bool | None = None) -> RowFill | None:
        """The longest row this bin can actually fill, up to `length`. Never a ragged row.

        Generators return None on any shortfall, which on a long-tail bin loses the whole
        subassembly -- and with it the build. This returns the best row it CAN lay plus the
        shortfall, so the caller can shrink the design instead of abandoning it.

        A shorter row is re-tiled from scratch rather than trimmed, because a trimmed row can
        end mid-part; the search is bounded by `length`.
        """
        for want in range(length, max(0, min_length - 1), -1):
            mark = len(self.substitutions)
            row = self.fill_row(want, color, palette, offset_parity=offset_parity,
                                substitute=substitute)
            if row is not None:
                return RowFill(tuple(row), length, want, tuple(self.substitutions[mark:]))
        return None

    def best_rect(self, w: int, d: int, color: int, palette: list[str], *,
                  layer_parity: int = 0, min_width: int = 1, min_depth: int | None = None,
                  substitute: bool | None = None,
                  budget: int = BEST_FIT_BUDGET) -> RectFill | None:
        """The largest rectangle this bin can actually fill, no bigger than w x d.

        Shapes are tried biggest-area first, and deeper before wider at equal area because depth
        is what makes a base stable. `budget` caps the search (invariant 8).
        """
        lo_d = d if min_depth is None else max(1, min_depth)
        shapes = [(ww, dd) for dd in range(d, lo_d - 1, -1)
                  for ww in range(w, max(0, min_width - 1), -1)]
        shapes.sort(key=lambda s: (-s[0] * s[1], -s[1], -s[0]))
        for ww, dd in shapes[:budget]:
            mark = len(self.substitutions)
            got = self.fill_rect(ww, dd, color, palette, layer_parity=layer_parity,
                                 substitute=substitute)
            if got is not None:
                return RectFill(tuple(got), (w, d), (ww, dd),
                                tuple(self.substitutions[mark:]))
        return None


# ---------------------------------------------------------------------- Contract 1 loading


def inventory_from_rows(rows) -> tuple[Inventory, dict[tuple[str, int], str]]:
    """Contract 1 `items` -> `(Inventory, color_modes)`.

    `status: "unknown"` rows count in the user's totals but are excluded from the solver, and so
    is anything the whitelist cannot place. `color_mode` rides along per row rather than being
    folded into the Inventory, because `Inventory` is a frozen value type shared by everything
    and this is a hint for the allocator only.
    """
    pairs: list[tuple[str, int, int]] = []
    modes: dict[tuple[str, int], str] = {}
    for r in rows:
        if r.get("status") == "unknown" or r.get("placeable") is False:
            continue
        key = (str(r["part"]), int(r["color"]))
        pairs.append((key[0], key[1], int(r.get("qty", 0))))
        mode = r.get("color_mode")
        if mode in ("exact", "similar", "ignore"):
            # Two rows of the same element disagreeing: the stricter one wins, because a row CV
            # was confident about is evidence about the colour, not about that one brick.
            modes[key] = "exact" if "exact" in (mode, modes.get(key, mode)) else mode
    return Inventory.from_pairs(pairs), modes


def allocator_from_rows(rows, *, color_policy: str = DEFAULT_COLOR_POLICY,
                        substitute: bool = True) -> Allocator:
    """An Allocator straight from a Contract 1 `inventory.json` item list."""
    inv, modes = inventory_from_rows(rows)
    return Allocator(inv, color_policy=color_policy, color_modes=modes, substitute=substitute)
