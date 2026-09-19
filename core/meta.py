"""Part metadata, derived from bricknet's connector table (MIT, 14,603 parts).

This replaces the hand-written `build_part_meta.py` in the original plan. We do NOT parse
mesh geometry: bricknet ships authored stud / anti-stud / axle connector poses, and that is
strictly better data than anything we would derive from bounding boxes.

Derivation, and why it works
----------------------------
An LDraw part's origin sits at the centre of its TOP face (verified against 3001.dat), so:
  * the top plane is y = 0 in part-local LDU;
  * anti-stud ("hole") connectors sit on the bottom plane, so height = max hole y;
  * footprint cells come from stud and hole connectors, which lie on a 20 LDU lattice.
Footprint size comes from the SPAN of the connector extremes, not from counting distinct
coordinates. That matters: tile 3069b (1x2) has holes at x = -10, 0, +10 -- the middle one is a
corner feature that bricknet still files under hole/hole -- so counting distinct values yields 3
studs where the span (20 LDU) correctly yields 2. Only the extremes are trusted.

Occupancy is a BOX (w x d x h). For slopes and round parts this over-claims volume, which is
conservative: it can refuse a legal placement, never accept an illegal one. Parts carry a
`shape` flag so a later version can refine it.
"""

from __future__ import annotations

import functools
import json
import lzma
import pathlib
from dataclasses import dataclass

from .geom import LDU_PER_PLATE, LDU_PER_STUD, rotate_cell, rotated_footprint

# Connector families that describe a real footprint cell (not a corner).
_FOOTPRINT_KEYS = (("stud", "stud"), ("hole", "hole"))
_UPWARD_TOL = 1e-6


@dataclass(frozen=True, slots=True)
class PartMeta:
    part: str
    name: str
    w: int                                   # studs along local X
    d: int                                   # studs along local Z
    h: int                                   # height in plates
    studs: tuple[tuple[int, int], ...]       # top-face cells with an upward stud
    antistuds: tuple[tuple[int, int], ...]   # bottom-face cells with an anti-stud
    local_centre_x: float
    local_centre_z: float
    local_top_y: float
    shape: str = "box"

    @property
    def is_tile(self) -> bool:
        return not self.studs

    def cells(self, rot: int) -> tuple[tuple[int, int], ...]:
        """Footprint cell offsets after rotation, normalised so min is (0,0)."""
        mx, mz = self._rot_origin(rot)
        return tuple(
            (rotate_cell(dx, dz, rot)[0] - mx, rotate_cell(dx, dz, rot)[1] - mz)
            for dx in range(self.w) for dz in range(self.d)
        )

    def stud_cells(self, rot: int) -> tuple[tuple[int, int], ...]:
        return self._rot_cells(self.studs, rot)

    def antistud_cells(self, rot: int) -> tuple[tuple[int, int], ...]:
        return self._rot_cells(self.antistuds, rot)

    def _rot_cells(self, cells, rot: int) -> tuple[tuple[int, int], ...]:
        if not cells:
            return ()
        mx, mz = self._rot_origin(rot)
        out = []
        for dx, dz in cells:
            rx, rz = rotate_cell(dx, dz, rot)
            out.append((rx - mx, rz - mz))
        return tuple(sorted(out))

    def _rot_origin(self, rot: int) -> tuple[int, int]:
        corners = [rotate_cell(dx, dz, rot) for dx in (0, self.w - 1) for dz in (0, self.d - 1)]
        return min(c[0] for c in corners), min(c[1] for c in corners)

    def footprint(self, rot: int) -> tuple[int, int]:
        return rotated_footprint(self.w, self.d, rot)


def _bricknet_dir() -> pathlib.Path:
    import bricknet
    return pathlib.Path(bricknet.__file__).parent / "_data" / "v1"


@functools.cache
def _raw_labels() -> dict:
    return json.loads(lzma.open(_bricknet_dir() / "labels.json.xz").read())


@functools.cache
def _raw_names() -> dict:
    return json.loads((_bricknet_dir() / "part_names.json").read_text())


def _axis(values: list[float]) -> tuple[float, float, int] | None:
    """(min, max, size_in_studs) for one axis, from the extremes only.

    Returns None if the span is not a whole number of stud pitches -- such a part does not sit
    on our grid and we refuse to place it rather than model it wrongly.
    """
    lo, hi = min(values), max(values)
    span = hi - lo
    n = int(round(span / LDU_PER_STUD))
    if abs(span - n * LDU_PER_STUD) > 1.0:
        return None
    return lo, hi, n + 1


def _derive(part_key: str, conns: dict) -> PartMeta | None:
    pts: list[tuple[float, float, float]] = []
    for kind, sub in _FOOTPRINT_KEYS:
        rows = conns.get(kind, {}).get(sub, [])
        pts.extend((r[0], r[1], r[2]) for r in rows)
    if not pts:
        return None

    ax = _axis([p[0] for p in pts])
    az = _axis([p[2] for p in pts])
    if ax is None or az is None:
        return None
    min_x, max_x, w = ax
    min_z, max_z, d = az

    holes = conns.get("hole", {}).get("hole", []) + conns.get("hole", {}).get("tube", [])
    h_ldu = max((r[1] for r in holes), default=0.0)
    if h_ldu <= 0:
        return None
    h = int(round(h_ldu / LDU_PER_PLATE))
    if h <= 0:
        return None

    def cell(px: float, pz: float) -> tuple[int, int] | None:
        """Map a connector to a footprint cell, or None if it sits on a cell corner."""
        fx = (px - min_x) / LDU_PER_STUD
        fz = (pz - min_z) / LDU_PER_STUD
        ix, iz = round(fx), round(fz)
        if abs(fx - ix) > 0.05 or abs(fz - iz) > 0.05:
            return None
        if not (0 <= ix < w and 0 <= iz < d):
            return None
        return (ix, iz)

    studs = tuple(sorted({
        c for r in conns.get("stud", {}).get("stud", [])
        if abs(r[3]) < _UPWARD_TOL and (c := cell(r[0], r[2])) is not None
    }))
    antis = tuple(sorted({
        c for r in conns.get("hole", {}).get("hole", [])
        if (c := cell(r[0], r[2])) is not None
    }))

    stem = part_key[:-4] if part_key.endswith(".dat") else part_key
    return PartMeta(
        part=stem,
        name=_raw_names().get(stem, stem),
        w=w, d=d, h=h,
        studs=studs, antistuds=antis,
        local_centre_x=(min_x + max_x) / 2,
        local_centre_z=(min_z + max_z) / 2,
        local_top_y=0.0,
    )


@functools.cache
def catalog() -> dict[str, PartMeta]:
    """Every part we can derive a rectangular grid footprint for."""
    out: dict[str, PartMeta] = {}
    for key, conns in _raw_labels().items():
        m = _derive(key, conns)
        if m is not None:
            out[m.part] = m
    return out


def get(part: str) -> PartMeta:
    try:
        return catalog()[part]
    except KeyError:
        raise KeyError(
            f"no metadata for part {part!r}. bricknet keys are exact LDraw filenames "
            f"(e.g. '3023b', not '3023') and its alias table is effectively empty -- "
            f"resolve the variant letter when building the whitelist."
        ) from None


def has(part: str) -> bool:
    return part in catalog()


_QUALIFIER = __import__("re").compile(r"\b(with|without|and|for)\b", __import__("re").I)
_STEM = __import__("re").compile(r"^(\d+)([a-z]*)$", __import__("re").I)


def resolve_id(part: str) -> str | None:
    """Best LDraw filename for a part id that may be written in another catalogue's convention.

    Invariant 5 says `part` is always an LDraw part number, but ids cross lane and API boundaries
    written BrickLink-style, which drops the variant suffix: "3023" for what LDraw calls
    "3023b.dat" (3023.dat does not exist -- only 3023a "with flat pin" and 3023b, the plain plate
    everybody actually owns). Picking the variant with the PLAINEST NAME rather than the first
    letter alphabetically is what stops the commonest plate in LEGO resolving to a rare variant.

    Lives in core so every lane translates the same way. Returns None when nothing matches, which
    is an honest "we cannot place this", not an error.
    """
    if not part:
        return None
    if has(part):
        return part
    m = _STEM.match(part)
    if not m:
        return None
    digits, suffix = m.group(1), m.group(2).lower()
    variants = [f"{digits}{s}" for s in ("", "a", "b", "c", "d", "e")
                if f"{digits}{s}" != part and has(f"{digits}{s}")]
    if variants:
        return min(variants, key=lambda v: (len(_QUALIFIER.findall(get(v).name)),
                                            len(get(v).name), v))
    if suffix and has(digits):
        return digits
    return None
