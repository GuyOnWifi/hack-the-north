"""The build model. Integer grid. No floats live here (invariant #1).

Coordinate convention (OUR model, not LDraw):
    pos = (x, y, z), all integers.
    x, z are in STUDS.   y is in PLATES.   +y is UP.
    LDraw's -Y-up / LDU conversion happens ONLY in ldraw.py.

A part occupies a box of unit cells. One cell = 1 stud x 1 plate x 1 stud.
A standard brick is 3 plates tall, so it fills 3 layers of cells.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Optional
import copy

from meta import PART_META


# ---------------------------------------------------------------- placed part
@dataclass(frozen=True)
class Part:
    id: str
    part: str          # LDraw part number, always (invariant #5)
    color: int         # LDraw colour code, computed never guessed (invariant #6)
    pos: tuple         # (x, y, z) integers
    rot: int = 0       # {0, 90, 180, 270}
    sub: str = "root"  # which subassembly owns it

    def footprint(self):
        m = PART_META[self.part]
        dx, dz = m["dx"], m["dz"]
        return (dz, dx) if self.rot in (90, 270) else (dx, dz)

    def height(self):
        return PART_META[self.part]["h"]

    def has_studs(self):
        return PART_META[self.part]["studs"]

    def cells(self):
        """Every unit cell this part fills, in world coords."""
        dx, dz = self.footprint()
        x0, y0, z0 = self.pos
        return {
            (x0 + i, y0 + k, z0 + j)
            for i in range(dx)
            for j in range(dz)
            for k in range(self.height())
        }

    def bottom_cells(self):
        dx, dz = self.footprint()
        x0, y0, z0 = self.pos
        return {(x0 + i, y0, z0 + j) for i in range(dx) for j in range(dz)}

    def top_layer(self):
        return self.pos[1] + self.height()

    def translated(self, dx, dy, dz, sub=None):
        p = replace(self, pos=(self.pos[0] + dx, self.pos[1] + dy, self.pos[2] + dz))
        return replace(p, sub=sub) if sub is not None else p


# ------------------------------------------------------------------ subassembly
@dataclass(frozen=True)
class SubAssembly:
    name: str
    parent: Optional[str]
    gen: str                 # generator name that produced it
    args: tuple              # frozen kv pairs, the semantic knobs
    attach: Optional[str]    # parent socket name this plugs into (FROZEN on edit)
    sockets: tuple           # names this node advertises to children


# ------------------------------------------------------------------------ build
@dataclass(frozen=True)
class Build:
    id: str
    version: int
    name: str
    parts: tuple             # tuple[Part]
    subs: tuple              # tuple[SubAssembly]
    provenance: dict = field(default_factory=dict)

    def with_parts(self, parts, bump=True):
        return replace(self, parts=tuple(parts),
                       version=self.version + 1 if bump else self.version)

    def sub(self, name):
        for s in self.subs:
            if s.name == name:
                return s
        return None


# ------------------------------------------------------------------- inventory
@dataclass
class Inventory:
    """The user's bin. element = (part, color). The AI never sees raw qty
    prose — it sees a capability summary (see summarize())."""
    counts: dict  # {(part, color): qty}

    def copy(self):
        return Inventory(copy.deepcopy(self.counts))

    def have(self, part, color):
        return self.counts.get((part, color), 0)

    def summarize(self):
        """Capability vocabulary for the LLM — NOT a parts list.
        The LLM reasons in 'plenty of 2x4 brick in red', never in qty=6."""
        from meta import PART_META, COLOR_NAME
        buckets = {}
        for (part, color), qty in self.counts.items():
            name = PART_META.get(part, {}).get("name", part)
            band = "plenty" if qty >= 6 else "some" if qty >= 2 else "few"
            buckets.setdefault(band, []).append(
                f"{name} in {COLOR_NAME.get(color, color)}")
        lines = []
        for band in ("plenty", "some", "few"):
            if band in buckets:
                lines.append(f"{band}: " + ", ".join(sorted(set(buckets[band]))))
        return "; ".join(lines)


def occupancy(parts):
    """Map every filled cell -> owning part id. Also flags overlaps."""
    occ = {}
    clashes = []
    for p in parts:
        for c in p.cells():
            if c in occ:
                clashes.append((occ[c], p.id, c))
            else:
                occ[c] = p.id
    return occ, clashes
