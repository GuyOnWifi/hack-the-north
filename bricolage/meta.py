"""The whitelist metadata table (invariant #5, decision D6).

Hand-verified in the real project against parsed .dat files. Here it's the
demo subset — enough parts to build vehicles and structures. dx/dz in studs,
h in plates, studs=whether the top face has studs (tiles don't).
"""

PART_META = {
    # bricks (h=3)
    "3001": {"name": "Brick 2x4", "dx": 2, "dz": 4, "h": 3, "studs": True},
    "3003": {"name": "Brick 2x2", "dx": 2, "dz": 2, "h": 3, "studs": True},
    "3004": {"name": "Brick 1x2", "dx": 1, "dz": 2, "h": 3, "studs": True},
    "3005": {"name": "Brick 1x1", "dx": 1, "dz": 1, "h": 3, "studs": True},
    "3010": {"name": "Brick 1x4", "dx": 1, "dz": 4, "h": 3, "studs": True},
    "3009": {"name": "Brick 1x6", "dx": 1, "dz": 6, "h": 3, "studs": True},
    "3002": {"name": "Brick 2x3", "dx": 2, "dz": 3, "h": 3, "studs": True},
    # plates (h=1)
    "3020": {"name": "Plate 2x4", "dx": 2, "dz": 4, "h": 1, "studs": True},
    "3022": {"name": "Plate 2x2", "dx": 2, "dz": 2, "h": 1, "studs": True},
    "3023": {"name": "Plate 1x2", "dx": 1, "dz": 2, "h": 1, "studs": True},
    "3024": {"name": "Plate 1x1", "dx": 1, "dz": 1, "h": 1, "studs": True},
    "3021": {"name": "Plate 2x3", "dx": 2, "dz": 3, "h": 1, "studs": True},
    "3795": {"name": "Plate 2x6", "dx": 2, "dz": 6, "h": 1, "studs": True},
    "3832": {"name": "Plate 2x10", "dx": 2, "dz": 10, "h": 1, "studs": True},
    # tiles (h=1, no studs on top)
    "3068b": {"name": "Tile 2x2", "dx": 2, "dz": 2, "h": 1, "studs": False},
    "3069b": {"name": "Tile 1x2", "dx": 1, "dz": 2, "h": 1, "studs": False},
    # slopes (treated as brick footprint; insertion still straight down)
    "3040": {"name": "Slope 45 2x1", "dx": 1, "dz": 2, "h": 3, "studs": False},
    "3039": {"name": "Slope 45 2x2", "dx": 2, "dz": 2, "h": 3, "studs": False},
    # round 1x1 as a wheel/stud stand-in (no Technic — anti-goal)
    "4073": {"name": "Round Plate 1x1", "dx": 1, "dz": 1, "h": 1, "studs": True},
}

COLOR_NAME = {
    0: "black", 1: "blue", 2: "green", 4: "red", 14: "yellow", 15: "white",
    71: "light gray", 72: "dark gray", 70: "reddish brown", 19: "tan",
    25: "orange", 7: "gray",
}

# LDraw colour code -> approx sRGB (for any local preview / debug)
COLOR_RGB = {
    0: (33, 33, 33), 1: (0, 85, 191), 2: (35, 120, 65), 4: (201, 26, 9),
    14: (245, 205, 47), 15: (244, 244, 244), 71: (160, 165, 169),
    72: (108, 110, 104), 70: (91, 47, 20), 19: (228, 205, 158),
    25: (254, 138, 24), 7: (155, 161, 157),
}


# --------------------------------------------------------- substitution rules
# When an element is short in the bin, replace one part with a set of smaller
# parts expressed as GRID OFFSETS (dx, dz within the footprint), not matrices
# (decision D6 / substitute lane). color is inherited. Each rule preserves the
# exact footprint and height so geometry stays valid by construction.
SUBSTITUTIONS = {
    "3001": [  # Brick 2x4  ->  two Brick 2x2
        [("3003", 0, 0), ("3003", 0, 2)],
        [("3004", 0, 0), ("3004", 0, 2), ("3004", 1, 0), ("3004", 1, 2)],  # 4x 1x2
    ],
    "3003": [  # Brick 2x2  ->  two Brick 1x2
        [("3004", 0, 0), ("3004", 1, 0)],
    ],
    "3010": [  # Brick 1x4  ->  two Brick 1x2
        [("3004", 0, 0), ("3004", 0, 2)],
    ],
    "3009": [  # Brick 1x6  ->  Brick 1x4 + Brick 1x2
        [("3010", 0, 0), ("3004", 0, 4)],
    ],
    "3020": [  # Plate 2x4  ->  two Plate 2x2
        [("3022", 0, 0), ("3022", 0, 2)],
    ],
    "3022": [  # Plate 2x2  ->  two Plate 1x2
        [("3023", 0, 0), ("3023", 1, 0)],
    ],
    "3795": [  # Plate 2x6  ->  Plate 2x4 + Plate 2x2
        [("3020", 0, 0), ("3022", 0, 4)],
    ],
}
