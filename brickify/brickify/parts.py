"""The part catalog: real LDraw parts with footprints verified against the
LDraw library's geometry (long axis = X, origin on the top surface at the
footprint centre, body extending +Y down: 8 LDU per plate).

Grid units everywhere in brickify: x/z in studs, y in plates (+y up).
A brick is 3 plates tall; 1 stud (8 mm) is 2.5 plates (3.2 mm) tall.
"""
from __future__ import annotations

from dataclasses import dataclass

LDU_PER_STUD = 20
LDU_PER_PLATE = 8
PLATES_PER_STUD = 2.5  # 8 mm / 3.2 mm


@dataclass(frozen=True)
class Part:
    id: str
    name: str
    length: int  # studs along the part's own long axis (LDraw X)
    width: int  # studs along LDraw Z
    height: int  # plates
    studs: bool = True  # tiles have a smooth top


# Rectangular parts the layout can use, largest first within each family.
PLATES = [
    Part("3034", "Plate 2x8", 8, 2, 1),
    Part("3795", "Plate 2x6", 6, 2, 1),
    Part("3020", "Plate 2x4", 4, 2, 1),
    Part("3021", "Plate 2x3", 3, 2, 1),
    Part("3022", "Plate 2x2", 2, 2, 1),
    Part("3460", "Plate 1x8", 8, 1, 1),
    Part("3666", "Plate 1x6", 6, 1, 1),
    Part("3710", "Plate 1x4", 4, 1, 1),
    Part("3623", "Plate 1x3", 3, 1, 1),
    Part("3023", "Plate 1x2", 2, 1, 1),
    Part("3024", "Plate 1x1", 1, 1, 1),
]

BRICKS = [
    Part("3007", "Brick 2x8", 8, 2, 3),
    Part("2456", "Brick 2x6", 6, 2, 3),
    Part("3001", "Brick 2x4", 4, 2, 3),
    Part("3002", "Brick 2x3", 3, 2, 3),
    Part("3003", "Brick 2x2", 2, 2, 3),
    Part("3008", "Brick 1x8", 8, 1, 3),
    Part("3009", "Brick 1x6", 6, 1, 3),
    Part("3010", "Brick 1x4", 4, 1, 3),
    Part("3622", "Brick 1x3", 3, 1, 3),
    Part("3004", "Brick 1x2", 2, 1, 3),
    Part("3005", "Brick 1x1", 1, 1, 3),
]

# Smooth-topped plates, keyed by the plate footprint they can replace.
TILES = {
    (1, 1): Part("3070b", "Tile 1x1", 1, 1, 1, studs=False),
    (2, 1): Part("3069b", "Tile 1x2", 2, 1, 1, studs=False),
    (3, 1): Part("63864", "Tile 1x3", 3, 1, 1, studs=False),
    (4, 1): Part("2431", "Tile 1x4", 4, 1, 1, studs=False),
    (2, 2): Part("3068b", "Tile 2x2", 2, 2, 1, studs=False),
}

ALL = {p.id: p for p in [*PLATES, *BRICKS, *TILES.values()]}
