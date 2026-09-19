"""Hand-written brief for the hummingbird concept image: the test that the
kernel + techniques can produce a LEGO-looking bird before any model writes
briefs. Shapes are written as small character layers, exactly the format a
vision model would emit."""
import json
from pathlib import Path

W, H = 4, 12  # body width (z) and height (plates)
L = 12        # body length (x): tail x=0 -> head x=11

def body_layers():
    layers = []
    for y in range(H):
        rows = []
        for z in range(W):
            row = ""
            for x in range(L):
                # egg-shaped torso x 1..8, head x 8..11 sits higher
                torso = 1 <= x <= 8 and 1 <= y <= 7 and not ((x <= 2 or x >= 8) and (y <= 1 or y >= 7))
                torso = torso and not (y == 1 and (z in (0, 3)))
                head = 8 <= x <= 11 and 5 <= y <= 11 and not (x == 11 and y >= 10)
                tail = x == 0 and 3 <= y <= 5 and z in (1, 2)
                if not (torso or head or tail):
                    row += "."
                    continue
                if tail:
                    ch = "k"          # black tail tip
                elif head and x >= 10 and y <= 7:
                    ch = "r"          # dark red throat
                elif head:
                    ch = "g"
                elif y <= 3 or (x >= 6 and y <= 5):
                    ch = "w"          # white belly and chest
                else:
                    ch = "g"
                row += ch
            rows.append(row)
        layers.append(rows)
    return layers

def wing_layers(right):
    shape = [
        "BBB.....",
        "BBBB....",
        "BBGGG...",
        "..GG....",  # inner row: only over the hinge top plate
        "..GG....",  # inner row: only over the hinge top plate
        "..GG....",  # inner row: only over the hinge top plate
        "..GG....",  # inner row: only over the hinge top plate
    ]
    rows = shape[::-1] if right else shape   # inner row sits on the hinge
    return [rows, rows]

# Display stand: 4x4 base, a clear 1x2 column, and a hinge brick turned 90
# degrees so it pitches the bird upright (head up, tail down) like the concept.
COLUMN = 15  # plates of clear column above the base
def stand_layers():
    base = ["dddd", "dddd", "dddd", "dddd"]
    col = ["....", ".cc.", "....", "...."]   # 1x2 column along x... rotated hinge needs 1 wide in x, 2 in z
    col = ["....", ".c..", ".c..", "...."]
    return [base] + [col] * COLUMN

TILT = 55  # degrees: hovering posture
BELLY = (5, 1)  # body cell that sits on the hinge top (x, z)

brief = {
    "name": "hummingbird",
    "palette": {"g": 2, "w": 15, "r": 320, "k": 0, "G": 2, "B": 43, "e": 0, "d": 72, "c": 47},
    "root": "stand",
    "bodies": [
        {
            "name": "stand",
            "layers": stand_layers(),
            "surface": False,
            "connectors": [
                # hinge on top of the column, axis along z (quarters=1), bird pitches about it
                {"part": "3937", "kind": "hinge", "at": [1, COLUMN + 1, 1], "quarters": 1, "colour": 72,
                 "attach": [{"body": "body", "angle": TILT}]},
            ],
        },
        {
            "name": "body",
            # the belly cell BELLY sits on the hinge top (hinge top studs at layer COLUMN+4)
            "origin": [1 - BELLY[0], COLUMN + 4, 1 - BELLY[1]],
            "layers": body_layers(),
            "connectors": [
                # eyes: side-stud bricks in the head, one per side
                {"part": "87087", "kind": "side", "at": [9, 8, 0], "quarters": 0, "colour": "g", "attach": [{"body": "eyeL"}]},
                {"part": "87087", "kind": "side", "at": [9, 8, 3], "quarters": 2, "colour": "g", "attach": [{"body": "eyeR"}]},
                # beak: side stud facing forward out of the head
                {"part": "87087", "kind": "side", "at": [11, 7, 1], "quarters": 3, "colour": "g", "attach": [{"body": "beak"}]},
                # wings: hinge bricks on the shoulders
                {"part": "3937", "kind": "hinge", "at": [4, 8, 0], "colour": 72, "attach": [{"body": "wingL", "angle": -38}]},
                {"part": "3937", "kind": "hinge", "at": [4, 8, 3], "colour": 72, "attach": [{"body": "wingR", "angle": 38}]},
            ],
        },
        {"name": "eyeL", "layers": [], "parts": [["98138", "e", [0, 0, 0]]], "surface": False},
        {"name": "eyeR", "layers": [], "parts": [["98138", "e", [0, 0, 0]]], "surface": False},
        {"name": "beak", "layers": [], "parts": [], "surface": False},
        {"name": "wingL", "origin": [2, 11, -6], "layers": wing_layers(False), "surface": False},
        {"name": "wingR", "origin": [2, 11, 3], "layers": wing_layers(True), "surface": False},
    ],
    "details": [{"kind": "bar", "body": "beak", "at": [0, 0, 0], "colour": "k", "holder": "k"}],
}
Path(__file__).with_name("hummingbird.json").write_text(json.dumps(brief, indent=1))
print("ok")
