"""LDraw export. The ONLY module that converts the integer grid into floats.

`0 STEP` markers are read natively by three.js LDrawLoader, which exposes
`group.userData.numBuildingSteps` and `child.userData.buildingStep` -- so emitting steps here
is the entire step-viewer feature on the frontend.
"""

from __future__ import annotations

from . import meta as meta_mod
from .geom import ROT_MATRICES, grid_to_ldu
from .model import Build, Placed


def _fmt(v: float) -> str:
    """LDraw wants plain decimals; keep integers looking like integers."""
    r = round(v, 4)
    return str(int(r)) if r == int(r) else f"{r:g}"


def part_line(p: Placed) -> str:
    m = meta_mod.get(p.part)
    x, y, z = grid_to_ldu(p.x, p.y, p.z, p.rot, m)
    mat = " ".join(str(v) for v in ROT_MATRICES[p.rot])
    return f"1 {p.color} {_fmt(x)} {_fmt(y)} {_fmt(z)} {mat} {p.part}.dat"


def to_ldraw(build: Build, steps: list[list[Placed]] | None = None) -> str:
    """Render a build as .ldr text. `steps` groups parts; None means one part per step."""
    lines = [
        f"0 {build.name}",
        f"0 Name: {build.id}.ldr",
        "0 Author: Bricolage",
        "0 !LDRAW_ORG Unofficial_Model",
        "",
    ]
    groups = steps if steps is not None else [[p] for p in build.parts]
    for group in groups:
        for p in group:
            lines.append(part_line(p))
        lines.append("0 STEP")
    return "\n".join(lines) + "\n"


def write(build: Build, path, steps=None) -> None:
    import pathlib
    pathlib.Path(path).write_text(to_ldraw(build, steps))
