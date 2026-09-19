"""The build model. Frozen, integer, and the single source of truth.

INVARIANT: no floats live in here. `pos` is integer [x, y, z] (x/z studs, y plates),
`rot` is one of 0/90/180/270. Conversion to LDraw units happens only in core.geom.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Placed:
    """One part placed on the grid."""

    id: str
    part: str          # LDraw part number WITHOUT .dat, e.g. "3001"
    color: int         # LDraw colour code
    pos: tuple[int, int, int]
    rot: int = 0
    sub: str = "root"  # subassembly node id

    @property
    def x(self) -> int: return self.pos[0]
    @property
    def y(self) -> int: return self.pos[1]
    @property
    def z(self) -> int: return self.pos[2]


@dataclass(frozen=True, slots=True)
class AttachPoint:
    """Where a child subassembly may connect to this one. Frozen during edits."""

    at: tuple[int, int, int]
    face: str = "top"           # top | bottom | side
    studs: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class SubAssembly:
    id: str
    parent: str | None = None
    attach: tuple[AttachPoint, ...] = ()


@dataclass(frozen=True, slots=True)
class Build:
    id: str
    name: str
    parts: tuple[Placed, ...] = ()
    subassemblies: tuple[SubAssembly, ...] = ()
    version: int = 0
    provenance: dict = field(default_factory=dict)

    def with_parts(self, parts: Iterable[Placed]) -> "Build":
        return replace(self, parts=tuple(parts), version=self.version + 1)

    def add(self, *parts: Placed) -> "Build":
        return self.with_parts(self.parts + tuple(parts))

    def sub(self, sub_id: str) -> tuple[Placed, ...]:
        return tuple(p for p in self.parts if p.sub == sub_id)

    def without_sub(self, sub_id: str) -> "Build":
        return self.with_parts(p for p in self.parts if p.sub != sub_id)

    @property
    def counts(self) -> dict[tuple[str, int], int]:
        out: dict[tuple[str, int], int] = {}
        for p in self.parts:
            out[(p.part, p.color)] = out.get((p.part, p.color), 0) + 1
        return out


@dataclass(frozen=True, slots=True)
class Inventory:
    """What the user owns. (part, colour) -> quantity."""

    items: dict[tuple[str, int], int] = field(default_factory=dict)

    @classmethod
    def of(cls, **_) -> "Inventory":
        raise NotImplementedError

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[str, int, int]]) -> "Inventory":
        d: dict[tuple[str, int], int] = {}
        for part, color, qty in pairs:
            d[(part, color)] = d.get((part, color), 0) + qty
        return cls(d)

    def qty(self, part: str, color: int) -> int:
        return self.items.get((part, color), 0)

    def qty_any_color(self, part: str) -> int:
        return sum(q for (p, _), q in self.items.items() if p == part)

    def colors_of(self, part: str) -> list[int]:
        return [c for (p, c) in self.items if p == part]

    @property
    def total(self) -> int:
        return sum(self.items.values())

    def minus(self, counts: dict[tuple[str, int], int]) -> "Inventory":
        d = dict(self.items)
        for k, n in counts.items():
            d[k] = d.get(k, 0) - n
        return Inventory(d)
