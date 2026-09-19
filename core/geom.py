"""Grid <-> LDraw coordinate conversion. The ONLY place floats are allowed.

Coordinate systems
------------------
GRID (our build model, integers only):
    x, z  in studs;  y in plates, increasing UPWARD, y=0 is the ground plane.
    A part at grid y with height h occupies plate layers [y, y+h).
    rot in {0, 90, 180, 270} degrees about the vertical axis.

LDRAW (export only, floats):
    1 LDU = 0.4mm.  Stud pitch 20 LDU.  Plate 8 LDU.  Brick 24 LDU.
    -Y IS UP, so higher in the world = more negative y.

    VERIFIED against the real library file, 2026: brick 3001.dat contains
        4 16 -40 0 -20  -40 24 -20  40 24 -20  40 0 -20
    so the body spans y in [0, 24] and -- since -Y is up -- the part origin sits at the
    centre of its TOP face, with the body extending DOWNWARD to y=+24.
    (An earlier draft of the docs said "bottom face, y in [-24,0]". That was wrong.)
"""

LDU_PER_STUD = 20
LDU_PER_PLATE = 8
PLATES_PER_BRICK = 3
LDU_PER_BRICK = LDU_PER_PLATE * PLATES_PER_BRICK  # 24

# 3x3 row-major rotation matrices about Y, as LDraw writes them (a b c d e f g h i).
ROT_MATRICES = {
    0:   (1, 0, 0, 0, 1, 0, 0, 0, 1),
    90:  (0, 0, -1, 0, 1, 0, 1, 0, 0),
    180: (-1, 0, 0, 0, 1, 0, 0, 0, -1),
    270: (0, 0, 1, 0, 1, 0, -1, 0, 0),
}
ROTATIONS = (0, 90, 180, 270)


def rotate_cell(dx: int, dz: int, rot: int) -> tuple[int, int]:
    """Rotate a footprint cell offset about the footprint origin."""
    if rot == 0:
        return dx, dz
    if rot == 90:
        return -dz, dx
    if rot == 180:
        return -dx, -dz
    if rot == 270:
        return dz, -dx
    raise ValueError(f"rot must be one of {ROTATIONS}, got {rot!r}")


def rotated_footprint(w: int, d: int, rot: int) -> tuple[int, int]:
    """Footprint (w, d) in studs after rotation."""
    return (d, w) if rot in (90, 270) else (w, d)


def grid_to_ldu(gx: int, gy: int, gz: int, rot: int, meta) -> tuple[float, float, float]:
    """Origin of a placed part, in LDraw units.

    `meta` supplies the part-local connector extents so this works for any part without
    assuming where its author put the origin.
    """
    w, d = rotated_footprint(meta.w, meta.d, rot)
    # Footprint centre in world studs, converted to LDU.
    cx = (gx + w / 2) * LDU_PER_STUD
    cz = (gz + d / 2) * LDU_PER_STUD
    # The part's own footprint centre, in part-local LDU, rotated the same way.
    lx, lz = meta.local_centre_x, meta.local_centre_z
    if rot == 90:
        lx, lz = -lz, lx
    elif rot == 180:
        lx, lz = -lx, -lz
    elif rot == 270:
        lx, lz = lz, -lx
    # Top face of the part sits at grid height (gy + h); -Y is up.
    y = -LDU_PER_PLATE * (gy + meta.h) - meta.local_top_y
    return (cx - lx, float(y), cz - lz)
