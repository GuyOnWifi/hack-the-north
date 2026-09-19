"""Layout -> LDraw text, bottom-up with a 0 STEP per plate layer, so the app's
viewer and step-by-step manual can show it directly."""
from __future__ import annotations

from .layout import Layout
from .parts import LDU_PER_PLATE, LDU_PER_STUD

IDENTITY = "1 0 0 0 1 0 0 0 1"
QUARTER = "0 0 1 0 1 0 -1 0 0"  # rotate 90 degrees about Y: part's long axis onto world Z


def to_ldr(layout: Layout, name: str = "model") -> str:
    X, _, Z = layout.shape
    lines = [f"0 {name}", f"0 Name: {name}.ldr", "0 Author: brickify", ""]
    by_layer: dict[int, list[str]] = {}
    for p in layout.parts:
        # centre the model on the origin; LDraw is -Y up and the part origin is
        # its top surface centre
        cx = (p.x + p.sx / 2 - X / 2) * LDU_PER_STUD
        cz = (p.z + p.sz / 2 - Z / 2) * LDU_PER_STUD
        top = -(p.y + p.part.height) * LDU_PER_PLATE
        rot = IDENTITY if p.along_x else QUARTER
        by_layer.setdefault(p.y, []).append(f"1 {p.colour} {cx:g} {top:g} {cz:g} {rot} {p.part.id}.dat")
    for y in sorted(by_layer):
        lines.extend(by_layer[y])
        lines.append("0 STEP")
    return "\n".join(lines) + "\n"
