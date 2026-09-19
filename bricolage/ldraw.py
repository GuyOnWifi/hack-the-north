"""LDraw export — the ONLY place floats and LDU exist (invariant #1).

Our grid -> LDU:  x_ldu = x_stud*20,  z_ldu = z_stud*20,  y_ldu = -(y_plate*8)
(-Y is up in LDraw). A brick's origin is the centre of its bottom face, so we
shift by half the footprint. `0 STEP` lines let three.js LDrawLoader render the
manual natively (decision D5).
"""
from __future__ import annotations

STUD = 20      # LDU per stud
PLATE = 8      # LDU per plate

ROT = {  # 3x3 row-major, applied before translation
    0:   (1, 0, 0, 0, 1, 0, 0, 0, 1),
    90:  (0, 0, -1, 0, 1, 0, 1, 0, 0),
    180: (-1, 0, 0, 0, 1, 0, 0, 0, -1),
    270: (0, 0, 1, 0, 1, 0, -1, 0, 0),
}


def _fmt(v):
    return str(int(v)) if float(v).is_integer() else f"{v:.3f}".rstrip("0").rstrip(".")


def part_line(p):
    from meta import PART_META
    dx, dz = p.footprint()
    # centre of footprint in studs -> LDU; y at bottom face of the part
    cx = (p.pos[0] + dx / 2) * STUD
    cz = (p.pos[2] + dz / 2) * STUD
    cy = -(p.pos[1] * PLATE)
    m = ROT[p.rot]
    coords = " ".join(_fmt(v) for v in (cx, cy, cz, *m))
    return f"1 {p.color} {coords} {p.part}.dat"


def to_ldr(build, steps=None):
    """Full model as .ldr text with 0 STEP separators if steps given."""
    out = [f"0 {build.name}", f"0 Name: {build.id}.ldr",
           "0 Author: Bricolage", "0 !LICENSE Redistributable under CC BY 4.0"]
    by_id = {p.id: p for p in build.parts}
    if steps is None:
        for p in build.parts:
            out.append(part_line(p))
    else:
        for s in steps["steps"]:
            for pid in s["parts"]:
                out.append(part_line(by_id[pid]))
            out.append("0 STEP")
    return "\n".join(out) + "\n"
